"""Request-scoped workbook download, locking, execution, and commit lifecycle."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping
from uuid import UUID, uuid4

from planner_platform.context import PlannerContext
from planner_platform.function_manifest import build_manifest
from planner_platform.policies import EffectType, policy_for
from planner_platform.ports.operations import OperationRepository
from planner_platform.ports.previews import PreviewRepository, StoredPreview
from planner_platform.ports.storage import WorkbookObjectStore
from planner_platform.ports.tools import PlannerToolsFactory
from planner_platform.ports.workspaces import WorkspaceRepository
from planner_platform.services import PlannerExecutionService


class WorkspaceNotFoundError(ValueError):
    pass


class WorkbookSession:
    """Execute one registered tool against one authenticated user's workbook."""

    def __init__(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID | None,
        workspaces: WorkspaceRepository,
        storage: WorkbookObjectStore,
        operations: OperationRepository,
        tools_factory_builder: Any,
        previews: PreviewRepository | None = None,
    ) -> None:
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.workspaces = workspaces
        self.storage = storage
        self.operations = operations
        self.tools_factory_builder = tools_factory_builder
        self.previews = previews

    def execute(self, tool_name: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        workspace = (
            self.workspaces.get_owned(self.user_id, self.workspace_id)
            if self.workspace_id
            else self.workspaces.get_active(self.user_id)
        )
        if workspace is None:
            raise WorkspaceNotFoundError("Planner workspace was not found")
        policy = self._policy(tool_name)
        operation_id = uuid4()
        with TemporaryDirectory(prefix="planner-os-") as directory:
            root = Path(directory)
            initial_context = PlannerContext(
                user_id=self.user_id,
                workspace_id=workspace.id,
                operation_id=operation_id,
                workbook_path=root / "current.xlsx",
                timezone=workspace.timezone,
                execution_target=workspace.active_execution_target,
                source_revision=workspace.revision,
            )
            locked = policy.effect in {EffectType.WORKBOOK_WRITE, EffectType.MIXED}
            if locked:
                self.workspaces.acquire_lock(initial_context, policy.timeout_seconds)
            try:
                workbook_path = self.storage.download_current(initial_context, root)
                rules_path = self.storage.download_rules(initial_context, root)
                if rules_path is None:
                    rules_path = root / "rules.yaml"
                    try:
                        import shutil
                        from planner_engine.config import DEFAULT_RULES_PATH
                        shutil.copy(DEFAULT_RULES_PATH, rules_path)
                    except FileNotFoundError:
                        fallback = (
                            "profile:\n"
                            "  name: Shadow\n"
                            "  timezone: Asia/Kolkata\n"
                            "  location: Gurgaon, India\n"
                            "sleep:\n"
                            "  start: 03:00\n"
                            "  end: 09:30\n"
                            "work:\n"
                            "  active_days:\n"
                            "  - Monday\n"
                            "  - Tuesday\n"
                            "  - Wednesday\n"
                            "  - Thursday\n"
                            "  - Friday\n"
                            "  no_work_days:\n"
                            "  - Saturday\n"
                            "  - Sunday\n"
                            "  july_august:\n"
                            "    start: '11:00'\n"
                            "    end: '19:00'\n"
                            "  september_onward:\n"
                            "    start: '20:30'\n"
                            "    end: 03:30\n"
                            "gym:\n"
                            "  sessions_per_week: 9\n"
                            "  double_class_days_per_week: 3\n"
                            "  single_class_days_per_week: 3\n"
                            "  one_class_equals_one_session: true\n"
                            "  dance_forbidden_days:\n"
                            "  - Tuesday\n"
                            "  - Wednesday\n"
                            "german:\n"
                            "  frequency: none\n"
                            "  allow_breaks: false\n"
                            "ielts:\n"
                            "  sessions_per_week: 2\n"
                            "ignou:\n"
                            "  sessions_per_week_min: 2\n"
                            "  sessions_per_week_max: 3\n"
                            "piano:\n"
                            "  duration_minutes: 60\n"
                            "reading:\n"
                            "  preferred_time: evening\n"
                            "planning:\n"
                            "  excel_is_source_of_truth: true\n"
                            "  edit_immediately: true\n"
                            "  backup_before_write: true\n"
                            "  move_unfinished_tasks_instead_of_deleting: true\n"
                            "  daily_follow_up: true\n"
                            "  alert_on_weekly_slippage: true\n"
                            "  alert_on_monthly_slippage: true\n"
                        )
                        rules_path.write_text(fallback)
                    
                context = PlannerContext(**{**initial_context.__dict__, "workbook_path": workbook_path})
                original_checksum = self._checksum(workbook_path)
                original_rules_checksum = self._checksum(rules_path)
                self.operations.record(context, tool_name=tool_name, status="running")
                settings_revision = getattr(workspace, "settings_revision", 0)
                self._prepare_apply_preview(
                    context,
                    root,
                    tool_name,
                    payload or {},
                    settings_revision=settings_revision,
                )
                tools_factory: PlannerToolsFactory = self.tools_factory_builder(root, context)
                result = PlannerExecutionService(tools_factory).execute(
                    context,
                    tool_name,
                    payload,
                    cloud_mode=True,
                )
                if not bool(result.get("success", True)):
                    self.operations.record(context, tool_name=tool_name, status="failed", result=result)
                    return result
                self._persist_preview(
                    context,
                    root,
                    tool_name,
                    result,
                    settings_revision=settings_revision,
                )
                final_checksum = self._checksum(workbook_path)
                final_rules_checksum = self._checksum(rules_path)
                
                if final_checksum != original_checksum or final_rules_checksum != original_rules_checksum:
                    if not locked:
                        raise RuntimeError("Read-only tool unexpectedly changed the workbook or rules")
                        
                    if final_checksum != original_checksum:
                        backup_key = self.storage.backup_current(context, original_checksum)
                        self.storage.upload_current(context, workbook_path)
                        self.workspaces.advance_revision(context, final_checksum)
                        result = {
                            **self._sanitized_result(result),
                            "source_revision": context.source_revision + 1,
                            "cloud_backup_key": backup_key,
                        }
                    else:
                        result = self._sanitized_result(result)
                        
                    if final_rules_checksum != original_rules_checksum:
                        self.storage.upload_rules(context, rules_path)
                else:
                    result = self._sanitized_result(result)
                self.operations.record(context, tool_name=tool_name, status="succeeded", result=result)
                return result
            except Exception:
                try:
                    self.operations.record(initial_context, tool_name=tool_name, status="failed")
                except Exception:
                    pass
                raise
            finally:
                if locked:
                    self.workspaces.release_lock(initial_context)

    @staticmethod
    def _checksum(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _policy(tool_name: str):
        record = next((item for item in build_manifest()["tools"] if item["name"] == tool_name), None)
        if record is None:
            raise ValueError(f"Tool is not registered: {tool_name}")
        return policy_for(record)

    def _prepare_apply_preview(
        self,
        context: PlannerContext,
        root: Path,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        settings_revision: int,
    ) -> StoredPreview | None:
        if not tool_name.startswith("apply_") or self.previews is None:
            return None
        preview_id = payload.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id:
            raise ValueError("Apply operations require a preview_id")
        stored = self.previews.get(context, preview_id)
        if stored is None:
            raise ValueError("Preview was not found for this workspace")
        expected = "preview_" + tool_name.removeprefix("apply_")
        if stored.operation != expected:
            raise ValueError("Preview operation does not match apply operation")
        if stored.source_revision != context.source_revision:
            raise ValueError("Preview is stale because the workbook revision changed")
        if stored.settings_revision != settings_revision:
            raise ValueError("Preview is stale because workspace settings changed")
        if stored.active_execution_target != context.execution_target:
            raise ValueError("Preview is stale because the execution target changed")
        consumed = self.previews.consume(context, preview_id)
        session_state = root / "state" / str(context.operation_id)
        for relative, content in consumed.payload.get("session_files", {}).items():
            destination = (session_state / relative).resolve()
            if session_state.resolve() not in destination.parents:
                raise ValueError("Stored preview contains an invalid path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(str(content), encoding="utf-8")
        return consumed

    def _persist_preview(
        self,
        context: PlannerContext,
        root: Path,
        tool_name: str,
        result: dict[str, Any],
        *,
        settings_revision: int,
    ) -> None:
        if not tool_name.startswith("preview_") or self.previews is None:
            return
        preview_id = self._find_preview_id(result)
        if not preview_id:
            raise ValueError("Preview tool did not return a preview_id")
        session_state = root / "state" / str(context.operation_id)
        files: dict[str, str] = {}
        if session_state.exists():
            for path in session_state.rglob("*.json"):
                if path.name in {"execution-settings.json", "external-links.json"}:
                    continue
                files[str(path.relative_to(session_state))] = path.read_text(encoding="utf-8")
        now = datetime.now(timezone.utc)
        self.previews.save(
            context,
            StoredPreview(
                preview_id=preview_id,
                operation=tool_name,
                payload={"result": self._sanitized_result(result), "session_files": files},
                source_revision=context.source_revision,
                settings_revision=settings_revision,
                active_execution_target=context.execution_target,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            ),
        )

    @classmethod
    def _find_preview_id(cls, value):
        if isinstance(value, dict):
            direct = value.get("preview_id")
            if isinstance(direct, str) and direct:
                return direct
            for item in value.values():
                found = cls._find_preview_id(item)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = cls._find_preview_id(item)
                if found:
                    return found
        return None

    @classmethod
    def _sanitized_result(cls, value):
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                if key in {"access_token", "credentials", "token"}:
                    continue
                if key.endswith("_path"):
                    sanitized[key] = None
                else:
                    sanitized[key] = cls._sanitized_result(item)
            return sanitized
        if isinstance(value, list):
            return [cls._sanitized_result(item) for item in value]
        return value
