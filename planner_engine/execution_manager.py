"""Persistent single-active execution-target orchestration."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from planner_engine.execution_targets.base import ExecutionTarget, PublishResult
from planner_engine.external_links import ExternalLinkConflict, ExternalLinkStore
from planner_engine.models import ScheduledBlock
from planner_engine.preview_contract import CONTRACT_KEY, PreviewContract


TARGETS = ("google_calendar", "apple_calendar", "none")


@dataclass(frozen=True)
class ExecutionPreview:
    operation: str
    current_target: str
    destination_target: str
    summary: str
    external_changes: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    preview_id: str = field(default_factory=lambda: str(uuid4()))
    expires_at: str = field(default_factory=lambda: (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
    requires_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionSettings:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.migration_warnings: list[str] = []

    def get_active(self) -> str:
        return str(self._load()["execution"]["active_target"])

    def set_active(self, target: str) -> str:
        self._validate(target)
        data = self._load()
        data["execution"]["active_target"] = target
        self._save(data)
        return target

    def list_targets(self) -> dict[str, Any]:
        data = self._load()["execution"]
        return {"active_target": data["active_target"], "available_targets": list(TARGETS), "publish_mode": data["publish_mode"], "apple_calendar_id": data.get("apple_calendar_id"), "migration_warnings": list(self.migration_warnings)}

    def get_apple_calendar_id(self) -> str | None:
        return self._load()["execution"].get("apple_calendar_id")

    def set_apple_calendar_id(self, calendar_id: str) -> str:
        if not calendar_id.strip():
            raise ValueError("Apple Calendar identifier cannot be empty")
        data = self._load()
        data["execution"]["apple_calendar_id"] = calendar_id.strip()
        self._save(data)
        return calendar_id.strip()

    def _validate(self, target: str) -> None:
        if target not in TARGETS:
            raise ValueError(f"Unsupported execution target: {target}")

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"execution": {"active_target": "google_calendar", "available_targets": list(TARGETS), "publish_mode": "preview_first"}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        execution = data.setdefault("execution", {})
        execution.setdefault("active_target", "google_calendar")
        if execution["active_target"] == "structured":
            self._backup()
            execution["active_target"] = "none"
            execution["migrated_from_target"] = "structured"
            execution["migration_warning"] = "Structured is no longer supported. Active target changed to none; choose Google Calendar or Apple Calendar explicitly."
            self.migration_warnings = [execution["migration_warning"]]
            execution["available_targets"] = list(TARGETS)
            self._save(data)
        execution["available_targets"] = list(TARGETS)
        execution.setdefault("publish_mode", "preview_first")
        self._validate(execution["active_target"])
        return data

    def _backup(self) -> None:
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".pre-mvp2-apple.bak"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(self.path)


class ExecutionManager:
    def __init__(self, settings: ExecutionSettings, links: ExternalLinkStore, targets: dict[str, ExecutionTarget], preview_dir: str | Path) -> None:
        if set(targets) != set(TARGETS):
            raise ValueError("Execution targets must be exactly google_calendar, apple_calendar, and none")
        self.settings = settings
        self.links = links
        self.targets = targets
        self.preview_dir = Path(preview_dir)
        self._contract = PreviewContract(
            {"settings": settings.path, "external_links": links.path}
        )

    def list_execution_targets(self) -> dict[str, Any]:
        return self.settings.list_targets()

    def get_active_execution_target(self) -> str:
        return self.settings.get_active()

    def set_active_execution_target(self, target: str) -> dict[str, Any]:
        previous = self.settings.get_active()
        self.settings.set_active(target)
        return {"previous_target": previous, "active_target": target, "external_items_changed": 0}

    def preview_execution_target_switch(self, target: str) -> ExecutionPreview:
        self.settings._validate(target)
        current = self.settings.get_active()
        return self._save_preview(ExecutionPreview("target_switch", current, target, f"Future normal publishing will use {target}", [], ["Existing external items will remain untouched"]))

    def apply_execution_target_switch(self, preview_id: str) -> dict[str, Any]:
        preview = self._load_preview(preview_id, "target_switch")
        self._mark_applied(preview_id)
        result = self.set_active_execution_target(preview.destination_target)
        return {**result, "preview_id": preview_id}

    def publish_blocks(self, blocks: list[ScheduledBlock]) -> PublishResult:
        active = self.settings.get_active()
        if active == "none":
            return self.targets[active].publish_blocks(blocks)
        eligible = []
        for block in blocks:
            block_id = self._block_id(block, active)
            link = self.links.active_for(block_id)
            if link and link["target_name"] != active:
                return PublishResult(False, active, errors=[f"Block {block_id} is already active in {link['target_name']}; preview a migration"])
            eligible.append(block)
        result = self.targets[active].publish_blocks(eligible)
        if result.success:
            try:
                for mapping in result.mappings:
                    self.links.upsert(mapping["planner_block_id"], active, mapping["external_id"], mapping["checksum"])
            except ExternalLinkConflict as error:
                return PublishResult(False, active, created=result.created, updated=result.updated, warnings=result.warnings, errors=[str(error)])
        return result

    def preview_move_external_items(self, source_target: str, destination_target: str, start_date: date, end_date: date) -> ExecutionPreview:
        if source_target == destination_target or "none" in {source_target, destination_target}:
            raise ValueError("Migration requires two different downstream targets")
        source_items = self.targets[source_target].list_items(start_date, end_date)
        changes = [{"planner_block_id": item.planner_block_id, "source_external_id": item.external_id, "title": item.title, "start": item.start, "end": item.end} for item in source_items]
        return self._save_preview(ExecutionPreview("target_migration", source_target, destination_target, f"Move {len(changes)} external item(s) from {source_target} to {destination_target}", changes, ["Workbook tasks are unchanged"]))

    def apply_move_external_items(self, preview_id: str, blocks_by_id: dict[str, ScheduledBlock] | None = None) -> dict[str, Any]:
        preview = self._load_preview(preview_id, "target_migration")
        # Consume before executing: a migration that partially fails must not
        # be replayable from the same preview; the repair flow owns cleanup.
        self._mark_applied(preview_id)
        blocks_by_id = blocks_by_id or {
            item["planner_block_id"]: ScheduledBlock(
                title=item["title"], start=datetime.fromisoformat(item["start"]),
                end=datetime.fromisoformat(item["end"]), category="planner",
                source="explicit_execution_migration",
                metadata={"planner_block_id": item["planner_block_id"]},
            )
            for item in preview.external_changes
        }
        blocks = [blocks_by_id[item["planner_block_id"]] for item in preview.external_changes if item["planner_block_id"] in blocks_by_id]
        created = self.targets[preview.destination_target].publish_blocks(blocks)
        if not created.success:
            return {"success": False, "created": created.to_dict(), "deleted": 0, "repair_required": False, "errors": created.errors}
        deleted = 0
        errors = []
        for item in preview.external_changes:
            result = self.targets[preview.current_target].delete_item(item["source_external_id"])
            if result.success:
                deleted += 1
                self.links.deactivate(item["planner_block_id"], preview.current_target)
            else:
                errors.extend(result.errors)
        for mapping in created.mappings:
            if not self.links.active_for(mapping["planner_block_id"]):
                self.links.upsert(mapping["planner_block_id"], preview.destination_target, mapping["external_id"], mapping["checksum"])
        return {"success": not errors, "created": created.created, "deleted": deleted, "repair_required": bool(errors), "repair_preview": {"operation": "finish_source_cleanup", "items": [item for item in preview.external_changes if self.links.active_for(item["planner_block_id"])]} if errors else None, "errors": errors}

    def _block_id(self, block: ScheduledBlock, target: str) -> str:
        adapter = self.targets[target]
        if hasattr(adapter, "client") and hasattr(adapter.client, "stable_block_id"):
            return adapter.client.stable_block_id(block)
        if hasattr(adapter, "_block_id"):
            return adapter._block_id(block)
        return str((block.metadata or {}).get("planner_block_id", ""))

    def _save_preview(self, preview: ExecutionPreview) -> ExecutionPreview:
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        path = self.preview_dir / f"{preview.preview_id}.json"
        depends_on = (
            ("settings", "external_links")
            if preview.operation == "target_migration"
            else ("settings",)
        )
        payload = self._contract.seal(
            preview.to_dict(), kind=preview.operation, depends_on=depends_on
        )
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return preview

    def _load_preview(self, preview_id: str, operation: str) -> ExecutionPreview:
        path = self.preview_dir / f"{preview_id}.json"
        if not path.exists():
            raise ValueError("Unknown execution preview")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["operation"] != operation:
            raise ValueError("Preview operation type does not match")
        self._contract.validate(data, kind=operation)
        if datetime.fromisoformat(data["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("Execution preview has expired")
        data.pop(CONTRACT_KEY, None)
        return ExecutionPreview(**data)

    def _mark_applied(self, preview_id: str) -> None:
        PreviewContract.mark_applied_file(self.preview_dir / f"{preview_id}.json")
