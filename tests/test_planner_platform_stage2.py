from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from adapters.local.previews import LocalPreviewRepository
from adapters.local.tools import LocalPlannerToolsFactory
from adapters.local.workbooks import LocalWorkbookRepository
from planner_mcp.models import PlannerMCPConfig
from planner_mcp.tools import PlannerMCPTools
from planner_platform.context import PlannerContext
from planner_platform.policies import CloudStatus, ConfirmationPolicy, EffectType
from planner_platform.ports.previews import StoredPreview
from planner_platform.services import PlannerExecutionService
from planner_platform.tool_registry import (
    ToolDisabledInCloudError,
    ToolInputError,
    ToolNotRegisteredError,
    build_tool_registry,
)


def _context(tmp_path: Path, *, user_id=None, workspace_id=None) -> PlannerContext:
    workbook = tmp_path / "planner.xlsx"
    workbook.touch(exist_ok=True)
    return PlannerContext(
        user_id=user_id or uuid4(),
        workspace_id=workspace_id or uuid4(),
        operation_id=uuid4(),
        workbook_path=workbook,
        timezone="Asia/Kolkata",
        execution_target="google_calendar",
        source_revision=7,
    )


class FakeTools:
    def __getattr__(self, name):
        def invoke(*args):
            return {"success": True, "name": name, "args": list(args)}

        return invoke

    def calendar_delete_event(self, external_id, scope="single"):
        return {"success": True, "external_id": external_id, "scope": scope}


def test_planner_context_is_immutable_and_validated(tmp_path) -> None:
    context = _context(tmp_path)

    with pytest.raises(FrozenInstanceError):
        context.source_revision = 8
    with pytest.raises(ValueError, match="Unsupported execution target"):
        PlannerContext(**{**context.__dict__, "execution_target": "both"})


def test_registry_contains_all_92_tools_with_complete_policy() -> None:
    registry = build_tool_registry(FakeTools())

    assert len(registry.list()) == 92
    assert registry.get("validate").policy.effect == EffectType.READ
    assert registry.get("apply_week_plan").policy.confirmation == ConfirmationPolicy.PREVIEW_REQUIRED
    assert registry.get("apple_calendar_status").policy.cloud_status == CloudStatus.DISABLED
    assert all(spec.request_model and spec.response_model for spec in registry.list())


def test_registry_binds_all_tools_to_real_local_adapter_without_io(tmp_path) -> None:
    tools = PlannerMCPTools(PlannerMCPConfig(planner_path=tmp_path / "planner.xlsx"))

    registry = build_tool_registry(tools)

    assert len(registry.list()) == 92


def test_registry_rejects_unknown_invalid_and_cloud_disabled_calls() -> None:
    registry = build_tool_registry(FakeTools())

    with pytest.raises(ToolNotRegisteredError):
        registry.invoke("arbitrary_python", {})
    with pytest.raises(ToolInputError, match="Missing required fields"):
        registry.invoke("add_task", {"task": "Read"})
    with pytest.raises(ToolInputError, match="Unexpected fields"):
        registry.invoke("validate", {"user_id": "untrusted"})
    with pytest.raises(ToolDisabledInCloudError):
        registry.invoke("apple_calendar_status", {}, cloud_mode=True)


def test_registry_adapts_series_alias_without_duplicate_public_handler() -> None:
    registry = build_tool_registry(FakeTools())

    result = registry.invoke("calendar_delete_future_series", {"external_id": "event-1"})

    assert result == {"success": True, "external_id": "event-1", "scope": "future"}


def test_local_tools_factory_binds_context_workbook_without_mutating_base(tmp_path) -> None:
    base = PlannerMCPConfig(planner_path=tmp_path / "other.xlsx")
    context = _context(tmp_path)

    tools = LocalPlannerToolsFactory(base).create(context)

    assert tools.config.planner_path == context.workbook_path
    assert base.planner_path == tmp_path / "other.xlsx"


def test_execution_service_uses_fresh_context_scoped_factory(tmp_path) -> None:
    created = []

    class Factory:
        def create(self, context):
            created.append(context.operation_id)
            return FakeTools()

    service = PlannerExecutionService(Factory())
    first = _context(tmp_path)
    second = PlannerContext(**{**first.__dict__, "operation_id": uuid4()})

    assert service.execute(first, "validate")["success"] is True
    assert service.execute(second, "validate")["success"] is True
    assert created == [first.operation_id, second.operation_id]


def test_local_preview_repository_is_owner_scoped_and_single_use(tmp_path) -> None:
    context = _context(tmp_path)
    other = _context(tmp_path, user_id=uuid4(), workspace_id=context.workspace_id)
    now = datetime.now(timezone.utc)
    preview = StoredPreview(
        preview_id="preview-1",
        operation="week_plan",
        payload={"week": 3},
        source_revision=context.source_revision,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    repository = LocalPreviewRepository(tmp_path / "previews")

    repository.save(context, preview)

    assert repository.get(context, preview.preview_id) == preview
    assert repository.get(other, preview.preview_id) is None
    assert repository.consume(context, preview.preview_id).consumed_at is not None
    with pytest.raises(ValueError, match="already consumed"):
        repository.consume(context, preview.preview_id)


def test_local_workbook_repository_reports_context_revision_and_checksum(tmp_path) -> None:
    context = _context(tmp_path)
    context.workbook_path.write_bytes(b"planner-v1")

    revision = LocalWorkbookRepository(tmp_path / "backups").current(context)

    assert revision.number == 7
    assert len(revision.checksum) == 64
    assert revision.path == context.workbook_path
