from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from adapters.supabase.calendar import SupabaseExternalLinkRepository
from planner_api.app import create_app
from planner_platform.auth import AuthenticationError
from planner_platform.context import PlannerContext
from planner_platform.function_manifest import build_manifest
from planner_platform.ports.previews import StoredPreview
from planner_platform.workbook_session import WorkbookSession


class MemoryPreviews:
    def __init__(self) -> None:
        self.items: dict[tuple[UUID, UUID, str], StoredPreview] = {}

    @staticmethod
    def key(context: PlannerContext, preview_id: str):
        return context.user_id, context.workspace_id, preview_id

    def save(self, context: PlannerContext, preview: StoredPreview) -> None:
        self.items[self.key(context, preview.preview_id)] = preview

    def get(self, context: PlannerContext, preview_id: str) -> StoredPreview | None:
        return self.items.get(self.key(context, preview_id))

    def consume(self, context: PlannerContext, preview_id: str) -> StoredPreview:
        key = self.key(context, preview_id)
        preview = self.items.get(key)
        if preview is None or preview.consumed_at or preview.expires_at <= datetime.now(timezone.utc):
            raise ValueError("Preview is missing, expired, or already consumed")
        consumed = replace(preview, consumed_at=datetime.now(timezone.utc))
        self.items[key] = consumed
        return consumed


class MemoryWorkspaces:
    def __init__(self, record) -> None:
        self.record = record
        self.calls = []

    def get_owned(self, user_id, workspace_id):
        if self.record.user_id == user_id and self.record.id == workspace_id:
            return self.record
        return None

    def get_active(self, user_id):
        return self.record if self.record.user_id == user_id else None

    def acquire_lock(self, context, ttl_seconds=60):
        self.calls.append(("lock", context.operation_id, ttl_seconds))
        return self.record

    def release_lock(self, context):
        self.calls.append(("release", context.operation_id))
        return True

    def advance_revision(self, context, checksum):
        self.calls.append(("revision", context.source_revision, checksum))
        return self.record


class MemoryStorage:
    def __init__(self) -> None:
        self.content = b"workbook"
        self.calls = []

    def download_current(self, context, destination_dir):
        path = destination_dir / "current.xlsx"
        path.write_bytes(self.content)
        return path

    def backup_current(self, context, checksum):
        self.calls.append(("backup", checksum))
        return "tenant/backup.xlsx"

    def upload_current(self, context, source):
        self.content = source.read_bytes()
        self.calls.append(("upload", self.content))


class MemoryOperations:
    def record(self, context, *, tool_name, status, result=None):
        del context, tool_name, status, result


class PreviewTools:
    def __init__(self, state_root: Path, context: PlannerContext) -> None:
        self.state_root = state_root
        self.context = context

    def preview_day_replan(self, request):
        preview_id = "day-preview-1"
        state = self.state_root / str(self.context.operation_id) / "previews"
        state.mkdir(parents=True, exist_ok=True)
        (state / f"{preview_id}.json").write_text('{"preview_id":"day-preview-1"}', encoding="utf-8")
        return {"success": True, "message": "preview", "data": {"request": request}, "preview_id": preview_id}

    def apply_day_replan(self, preview_id, preview=None):
        del preview
        state = self.state_root / str(self.context.operation_id) / "previews" / f"{preview_id}.json"
        assert state.exists()
        self.context.workbook_path.write_bytes(b"applied-workbook")
        return {"success": True, "message": "applied", "data": {"preview_id": preview_id}}

    def __getattr__(self, name):
        def unused_handler(*args):
            return {"success": True, "message": name, "data": {"args": list(args)}}

        return unused_handler


class PreviewToolsFactory:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root

    def create(self, context):
        return PreviewTools(self.state_root, context)


def workspace_record(user_id=None, workspace_id=None, **updates):
    values = {
        "id": workspace_id or uuid4(),
        "user_id": user_id or uuid4(),
        "timezone": "Asia/Kolkata",
        "active_execution_target": "none",
        "revision": 4,
        "settings_revision": 2,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def session_for(record, previews, storage, *, user_id=None):
    workspaces = MemoryWorkspaces(record)

    def builder(root, context):
        return PreviewToolsFactory(root / "state")

    return WorkbookSession(
        user_id=user_id or record.user_id,
        workspace_id=record.id,
        workspaces=workspaces,
        storage=storage,
        operations=MemoryOperations(),
        tools_factory_builder=builder,
        previews=previews,
    )


def test_preview_survives_request_restart_and_is_single_use() -> None:
    record = workspace_record()
    previews, storage = MemoryPreviews(), MemoryStorage()

    preview = session_for(record, previews, storage).execute("preview_day_replan", {"request": {"from_now": True}})
    applied = session_for(record, previews, storage).execute("apply_day_replan", {"preview_id": preview["preview_id"]})

    assert applied["success"] is True
    assert storage.content == b"applied-workbook"
    assert [call[0] for call in storage.calls] == ["backup", "upload"]
    with pytest.raises(ValueError, match="expired|consumed"):
        session_for(record, previews, storage).execute("apply_day_replan", {"preview_id": preview["preview_id"]})


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"revision": 5}, "workbook revision"),
        ({"settings_revision": 3}, "settings"),
        ({"active_execution_target": "google_calendar"}, "execution target"),
    ],
)
def test_stale_preview_is_rejected_after_authoritative_state_changes(updates, reason) -> None:
    record = workspace_record()
    previews, storage = MemoryPreviews(), MemoryStorage()
    preview = session_for(record, previews, storage).execute("preview_day_replan", {"request": {}})
    changed = workspace_record(user_id=record.user_id, workspace_id=record.id, **updates)

    with pytest.raises(ValueError, match=reason):
        session_for(changed, previews, storage).execute("apply_day_replan", {"preview_id": preview["preview_id"]})


def test_preview_is_owner_scoped() -> None:
    record = workspace_record()
    previews, storage = MemoryPreviews(), MemoryStorage()
    preview = session_for(record, previews, storage).execute("preview_day_replan", {"request": {}})
    other = workspace_record(user_id=uuid4(), workspace_id=record.id)

    with pytest.raises(ValueError, match="not found"):
        session_for(other, previews, storage).execute("apply_day_replan", {"preview_id": preview["preview_id"]})


def test_expired_preview_cannot_be_applied() -> None:
    record = workspace_record()
    previews, storage = MemoryPreviews(), MemoryStorage()
    preview = session_for(record, previews, storage).execute("preview_day_replan", {"request": {}})
    key = (record.user_id, record.id, preview["preview_id"])
    previews.items[key] = replace(previews.items[key], expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))

    with pytest.raises(ValueError, match="expired|consumed"):
        session_for(record, previews, storage).execute("apply_day_replan", {"preview_id": preview["preview_id"]})


class MultiUserVerifier:
    def __init__(self, users):
        self.users = users

    def verify(self, token):
        if token not in self.users:
            raise AuthenticationError("invalid token")
        return SimpleNamespace(user_id=self.users[token], access_token=token)


class OwnedRepository:
    def __init__(self, records, user_id):
        self.records = records
        self.user_id = user_id

    def list_owned(self, user_id):
        return [record for record in self.records if record.user_id == user_id == self.user_id]


class MultiUserRuntime:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def workspaces(self, user):
        return OwnedRepository(self.records, user.user_id)

    def execute(self, user, workspace_id, tool_name, arguments):
        owned = next((item for item in self.records if item.id == workspace_id and item.user_id == user.user_id), None)
        if owned is None:
            raise ValueError("Planner workspace was not found")
        self.calls.append((user.user_id, workspace_id, tool_name, arguments))
        return {"success": True, "message": "done", "data": {}}


def api_record(user_id, workspace_id):
    return SimpleNamespace(id=workspace_id, user_id=user_id, name="Planner", timezone="UTC", active_execution_target="none", revision=1, is_active=True)


def test_two_users_cannot_list_or_invoke_each_others_workspaces() -> None:
    user_a, user_b = uuid4(), uuid4()
    workspace_a, workspace_b = uuid4(), uuid4()
    runtime = MultiUserRuntime([api_record(user_a, workspace_a), api_record(user_b, workspace_b)])
    client = TestClient(create_app(runtime=runtime, verifier=MultiUserVerifier({"token-a": user_a, "token-b": user_b})))

    listed = client.get("/api/workspaces", headers={"Authorization": "Bearer token-a"})
    denied = client.post(
        "/api/v1/tools/validate/invoke",
        headers={"Authorization": "Bearer token-a"},
        json={"workspace_id": str(workspace_b), "arguments": {}},
    )

    assert [item["id"] for item in listed.json()["data"]["workspaces"]] == [str(workspace_a)]
    assert denied.status_code == 404
    assert runtime.calls == []


def test_versioned_catalog_matches_all_90_canonical_tools() -> None:
    user_id, workspace_id = uuid4(), uuid4()
    runtime = MultiUserRuntime([api_record(user_id, workspace_id)])
    client = TestClient(create_app(runtime=runtime, verifier=MultiUserVerifier({"token": user_id})))

    response = client.get("/api/v1/tools", headers={"Authorization": "Bearer token"})
    described = client.get("/api/v1/tools/validate", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.json()["data"]["count"] == 90
    assert {tool["name"] for tool in response.json()["data"]["tools"]} == {tool["name"] for tool in build_manifest()["tools"]}
    assert described.json()["data"]["tool"]["name"] == "validate"


class DownloadRuntime(MultiUserRuntime):
    def __init__(self, records):
        super().__init__(records)
        self.downloads = []

    def context(self, user, workspace_id):
        owned = next((item for item in self.records if item.id == workspace_id and item.user_id == user.user_id), None)
        if owned is None:
            raise ValueError("Planner workspace was not found")
        return PlannerContext(user.user_id, workspace_id, uuid4(), Path("current.xlsx"), "UTC", "none", owned.revision)

    def user_client(self, user):
        runtime = self

        class Client:
            def storage_download(self, bucket, object_key):
                runtime.downloads.append((user.user_id, bucket, object_key))
                return b"PK-test-workbook"

        return Client()


def test_workbook_download_uses_authenticated_owner_path_only() -> None:
    user_a, user_b = uuid4(), uuid4()
    workspace_a, workspace_b = uuid4(), uuid4()
    runtime = DownloadRuntime([api_record(user_a, workspace_a), api_record(user_b, workspace_b)])
    client = TestClient(create_app(runtime=runtime, verifier=MultiUserVerifier({"token-a": user_a})))

    allowed = client.get(f"/api/workspaces/{workspace_a}/workbook", headers={"Authorization": "Bearer token-a"})
    denied = client.get(f"/api/workspaces/{workspace_b}/workbook", headers={"Authorization": "Bearer token-a"})

    assert allowed.status_code == 200
    assert allowed.content == b"PK-test-workbook"
    assert runtime.downloads == [(user_a, "planner-workbooks", f"{user_a}/{workspace_a}/current.xlsx")]
    assert denied.status_code == 404


def test_lock_rpc_allows_expired_lock_recovery_and_never_trusts_user_parameter() -> None:
    sql = Path("supabase/migrations/0001_mvp3_foundation.sql").read_text(encoding="utf-8").casefold()
    function = sql.split("create or replace function public.acquire_workspace_lock", 1)[1].split("$$;", 1)[0]

    assert "w.locked_until <= now()" in function
    assert "w.user_id = (select auth.uid())" in function
    assert "p_user_id" not in function


def test_client_bundle_sources_do_not_reference_server_only_secrets() -> None:
    web_sources = [*Path("app").rglob("*.tsx"), *Path("components").rglob("*.tsx"), *Path("lib").rglob("*.ts")]
    contents = "\n".join(path.read_text(encoding="utf-8") for path in web_sources)

    assert "SUPABASE_SERVICE_ROLE_KEY" not in contents
    assert "GOOGLE_WEB_CLIENT_SECRET" not in contents
    assert ".planner-os/token.json" not in contents


def test_cloud_models_defer_annotations_for_python_312() -> None:
    source = Path("planner_engine/models.py").read_text(encoding="utf-8")

    assert source.startswith('"""Typed models used by the Planner Engine."""\n\nfrom __future__ import annotations')


def test_account_creation_uses_validated_email_password_signup() -> None:
    source = Path("components/auth-panel.tsx").read_text(encoding="utf-8")

    assert 'auth.signUp(credentials)' in source
    assert 'credentials = { email: email.trim(), password }' in source
    assert 'type="submit" name="auth-action" value="signup"' in source
    assert "signInAnonymously" not in source


class MappingGateway:
    def __init__(self) -> None:
        self.calls = []

    def select(self, table, *, filters, columns="*", limit=None):
        self.calls.append((table, dict(filters), columns, limit))
        return []


def test_calendar_mapping_queries_are_always_tenant_scoped(tmp_path) -> None:
    context = PlannerContext(uuid4(), uuid4(), uuid4(), tmp_path / "current.xlsx", "UTC", "google_calendar", 1)
    gateway = MappingGateway()
    repository = SupabaseExternalLinkRepository(gateway)

    repository.list(context, target_name="google_calendar")
    repository.active_for(context, "block-1")

    assert all(call[1]["user_id"] == str(context.user_id) for call in gateway.calls)
    assert all(call[1]["workspace_id"] == str(context.workspace_id) for call in gateway.calls)
    assert gateway.calls[1][1]["planner_block_id"] == "block-1"


def test_vercel_configuration_keeps_api_server_side_and_documents_release_gate() -> None:
    import json

    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    guide = Path("docs/mvp3_deployment.md").read_text(encoding="utf-8")

    assert config["framework"] == "nextjs"
    assert "api/index.py" in config["functions"]
    assert any(rule["source"] == "/auth/google/callback" for rule in config["rewrites"])
    assert "SUPABASE_SERVICE_ROLE_KEY" in guide
    assert "two-user" in guide.casefold()
    assert "python -m pytest" in guide
