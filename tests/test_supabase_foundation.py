from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from adapters.supabase.client import SupabaseConfig
from adapters.supabase.operations import SupabaseOperationRepository
from adapters.supabase.previews import SupabasePreviewRepository
from adapters.supabase.storage import (
    WORKBOOK_BUCKET,
    SupabaseWorkbookObjectStore,
    workspace_object_key,
)
from adapters.supabase.workspaces import (
    StaleWorkspaceRevisionError,
    SupabaseWorkspaceRepository,
    WorkspaceBusyError,
)
from planner_platform.context import PlannerContext
from planner_platform.ports.previews import StoredPreview


MIGRATION = Path("supabase/migrations/0001_mvp3_foundation.sql")


class FakeSupabaseGateway:
    def __init__(self) -> None:
        self.calls = []
        self.select_result = []
        self.insert_result = []
        self.update_result = []
        self.rpc_result = None
        self.download_result = b"workbook"

    def select(self, table, *, filters, columns="*", limit=None):
        self.calls.append(("select", table, dict(filters), columns, limit))
        return list(self.select_result)

    def insert(self, table, payload):
        self.calls.append(("insert", table, dict(payload)))
        return list(self.insert_result)

    def update(self, table, payload, *, filters):
        self.calls.append(("update", table, dict(payload), dict(filters)))
        return list(self.update_result)

    def rpc(self, function, payload):
        self.calls.append(("rpc", function, dict(payload)))
        return self.rpc_result

    def storage_download(self, bucket, object_key):
        self.calls.append(("storage_download", bucket, object_key))
        return self.download_result

    def storage_upload(self, bucket, object_key, content, *, content_type, upsert):
        self.calls.append(("storage_upload", bucket, object_key, content, content_type, upsert))


def _context(tmp_path: Path, *, revision: int = 4) -> PlannerContext:
    return PlannerContext(
        user_id=uuid4(),
        workspace_id=uuid4(),
        operation_id=uuid4(),
        workbook_path=tmp_path / "current.xlsx",
        timezone="Asia/Kolkata",
        execution_target="google_calendar",
        source_revision=revision,
    )


def _workspace_row(context: PlannerContext, **updates):
    row = {
        "id": str(context.workspace_id),
        "user_id": str(context.user_id),
        "name": "My Planner",
        "timezone": context.timezone,
        "active_execution_target": context.execution_target,
        "workbook_bucket": WORKBOOK_BUCKET,
        "workbook_key": workspace_object_key(context.user_id, context.workspace_id),
        "revision": context.source_revision,
        "settings_revision": 2,
        "is_active": False,
        "workbook_sha256": None,
        "lock_owner": None,
        "locked_until": None,
    }
    row.update(updates)
    return row


def test_migration_creates_all_tables_and_enables_rls() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()
    tables = {
        "profiles",
        "workspaces",
        "calendar_connections",
        "calendar_event_mappings",
        "planner_previews",
        "planner_operations",
        "audit_events",
        "oauth_states",
        "tool_registry_versions",
    }

    for table in tables:
        assert f"create table public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
    assert "(select auth.uid()) = user_id" in sql
    assert "encrypted_credentials bytea" in sql
    assert "refresh_token" not in sql


def test_migration_creates_private_storage_and_restricted_atomic_rpcs() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "'planner-workbooks'" in sql
    assert "public = false" in sql
    assert "on storage.objects" in sql
    assert "storage.foldername(name)" in sql
    assert "security invoker" in sql
    assert "acquire_workspace_lock" in sql
    assert "release_workspace_lock" in sql
    assert "consume_planner_preview" in sql
    assert "activate_workspace" in sql
    assert "application/json" in sql
    assert "revoke execute" in sql
    assert "to authenticated" in sql


def test_supabase_config_redacts_server_credentials() -> None:
    config = SupabaseConfig(
        url="https://project.supabase.co",
        api_key="service-role-secret",
        access_token="user-jwt",
    )

    rendered = repr(config)

    assert "service-role-secret" not in rendered
    assert "user-jwt" not in rendered
    assert "<redacted>" in rendered


def test_supabase_config_uses_publishable_key_for_user_jwt(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "publishable-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")

    user_config = SupabaseConfig.from_env(user_access_token="user-jwt")
    server_config = SupabaseConfig.from_env()

    assert user_config.api_key == "publishable-key"
    assert user_config.access_token == "user-jwt"
    assert server_config.api_key == "service-role-key"
    assert server_config.access_token is None


def test_workspace_lookup_always_filters_user_and_workspace(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()
    gateway.select_result = [_workspace_row(context)]

    workspace = SupabaseWorkspaceRepository(gateway).get_owned(
        context.user_id,
        context.workspace_id,
    )

    assert workspace is not None
    assert workspace.user_id == context.user_id
    assert gateway.calls == [
        (
            "select",
            "workspaces",
            {"id": str(context.workspace_id), "user_id": str(context.user_id)},
            "*",
            1,
        )
    ]


def test_workspace_create_generates_server_owned_storage_key(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()

    def insert(table, payload):
        gateway.calls.append(("insert", table, dict(payload)))
        return [_workspace_row(context, id=payload["id"], workbook_key=payload["workbook_key"])]

    gateway.insert = insert
    repository = SupabaseWorkspaceRepository(gateway)

    workspace = repository.create(context.user_id, name="My Planner", timezone=context.timezone)

    payload = gateway.calls[0][2]
    assert payload["user_id"] == str(context.user_id)
    assert payload["workbook_key"] == f"{context.user_id}/{payload['id']}/current.xlsx"
    assert workspace.user_id == context.user_id


def test_workspace_activation_first_checks_owner_then_uses_authenticated_rpc(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()
    gateway.select_result = [_workspace_row(context)]
    gateway.rpc_result = _workspace_row(context, is_active=True)

    workspace = SupabaseWorkspaceRepository(gateway).activate(
        context.user_id,
        context.workspace_id,
    )

    assert gateway.calls[0][2] == {
        "id": str(context.workspace_id),
        "user_id": str(context.user_id),
    }
    assert gateway.calls[1] == (
        "rpc",
        "activate_workspace",
        {"p_workspace_id": str(context.workspace_id)},
    )
    assert workspace.is_active is True


def test_workspace_lock_rpc_never_accepts_caller_user_id(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()
    gateway.rpc_result = _workspace_row(
        context,
        lock_owner=str(context.operation_id),
        locked_until=datetime.now(timezone.utc).isoformat(),
    )

    workspace = SupabaseWorkspaceRepository(gateway).acquire_lock(context, 45)

    call = gateway.calls[0]
    assert call[1] == "acquire_workspace_lock"
    assert call[2] == {
        "p_workspace_id": str(context.workspace_id),
        "p_lock_owner": str(context.operation_id),
        "p_ttl_seconds": 45,
    }
    assert "user_id" not in call[2]
    assert workspace.lock_owner == context.operation_id


def test_workspace_busy_and_stale_revision_are_explicit(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()
    repository = SupabaseWorkspaceRepository(gateway)

    with pytest.raises(WorkspaceBusyError):
        repository.acquire_lock(context)
    with pytest.raises(StaleWorkspaceRevisionError):
        repository.advance_revision(context, "a" * 64)

    update_call = gateway.calls[-1]
    assert update_call[3]["user_id"] == str(context.user_id)
    assert update_call[3]["revision"] == context.source_revision
    assert update_call[3]["lock_owner"] == str(context.operation_id)


def test_preview_repository_scopes_reads_and_uses_atomic_consume_rpc(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()
    now = datetime.now(timezone.utc)
    row = {
        "id": "preview-1",
        "user_id": str(context.user_id),
        "workspace_id": str(context.workspace_id),
        "operation_type": "week_plan",
        "payload": {"week": 3},
        "source_revision": context.source_revision,
        "settings_revision": 2,
        "active_execution_target": context.execution_target,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "consumed_at": now.isoformat(),
    }
    gateway.select_result = [row]
    gateway.rpc_result = row
    repository = SupabasePreviewRepository(gateway)

    assert repository.get(context, "preview-1") is not None
    consumed = repository.consume(context, "preview-1")

    select_call, rpc_call = gateway.calls
    assert select_call[2] == {
        "id": "preview-1",
        "user_id": str(context.user_id),
        "workspace_id": str(context.workspace_id),
    }
    assert rpc_call == (
        "rpc",
        "consume_planner_preview",
        {"p_preview_id": "preview-1", "p_workspace_id": str(context.workspace_id)},
    )
    assert consumed.consumed_at is not None


def test_preview_save_persists_revision_settings_and_target(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()
    now = datetime.now(timezone.utc)
    preview = StoredPreview(
        preview_id="preview-2",
        operation="goal_plan",
        payload={"title": "German A1"},
        source_revision=context.source_revision,
        settings_revision=3,
        active_execution_target="google_calendar",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )

    SupabasePreviewRepository(gateway).save(context, preview)

    payload = gateway.calls[0][2]
    assert payload["user_id"] == str(context.user_id)
    assert payload["workspace_id"] == str(context.workspace_id)
    assert payload["source_revision"] == context.source_revision
    assert payload["settings_revision"] == 3
    assert payload["active_execution_target"] == "google_calendar"


def test_workbook_storage_uses_only_deterministic_uuid_paths(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()
    store = SupabaseWorkbookObjectStore(gateway)

    destination = store.download_current(context, tmp_path / "request")

    expected_key = f"{context.user_id}/{context.workspace_id}/current.xlsx"
    assert gateway.calls[0] == ("storage_download", WORKBOOK_BUCKET, expected_key)
    assert destination == tmp_path / "request" / "current.xlsx"
    assert destination.read_bytes() == b"workbook"
    with pytest.raises(TypeError):
        workspace_object_key("../../other-user", context.workspace_id)


def test_workbook_upload_and_backup_never_use_client_paths(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()
    store = SupabaseWorkbookObjectStore(gateway)
    workbook = tmp_path / "upload.xlsx"
    workbook.write_bytes(b"xlsx-data")

    store.upload_current(context, workbook)
    backup_key = store.backup_current(context, "a" * 64)

    current_key = workspace_object_key(context.user_id, context.workspace_id)
    assert gateway.calls[0][0:3] == ("storage_upload", WORKBOOK_BUCKET, current_key)
    assert gateway.calls[1] == ("storage_download", WORKBOOK_BUCKET, current_key)
    assert backup_key.startswith(f"{context.user_id}/{context.workspace_id}/backups/{context.source_revision}-")
    assert backup_key.endswith(f"-{'a' * 64}.xlsx")
    assert gateway.calls[2][2] == backup_key
    assert gateway.calls[2][-1] is False


def test_operation_repository_scopes_insert_and_update(tmp_path) -> None:
    context = _context(tmp_path)
    gateway = FakeSupabaseGateway()
    repository = SupabaseOperationRepository(gateway)

    repository.record(context, tool_name="validate", status="running")
    gateway.select_result = [{"id": str(context.operation_id)}]
    repository.record(
        context,
        tool_name="validate",
        status="succeeded",
        result={"success": True},
    )

    insert_payload = gateway.calls[1][2]
    update_filters = gateway.calls[-1][3]
    assert insert_payload["user_id"] == str(context.user_id)
    assert insert_payload["workspace_id"] == str(context.workspace_id)
    assert update_filters == {
        "id": str(context.operation_id),
        "user_id": str(context.user_id),
        "workspace_id": str(context.workspace_id),
    }
