from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from adapters.supabase.calendar import (
    SupabaseCalendarConnectionRepository,
    SupabaseOAuthStateRepository,
)
from planner_api.app import create_app
from planner_platform.auth import AuthenticationError, SupabaseJWTVerifier
from planner_platform.context import PlannerContext
from planner_platform.google_oauth import (
    CredentialCipher,
    GoogleConnectionRequiredError,
    GoogleOAuthService,
    SupabaseGoogleCalendarClientFactory,
)
from planner_platform.workbook_session import WorkbookSession


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.select_result = []
        self.insert_result = []
        self.update_result = []
        self.rpc_result = None

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


def test_supabase_jwt_identity_comes_only_from_verified_subject() -> None:
    expected = uuid4()
    verifier = SupabaseJWTVerifier(
        issuer="https://project.supabase.co/auth/v1",
        decoder=lambda token, issuer, audience: {
            "sub": str(expected),
            "role": "authenticated",
            "iss": issuer,
            "aud": audience,
        },
    )

    user = verifier.verify("signed-user-token")

    assert user.user_id == expected
    assert "signed-user-token" not in repr(user)


def test_supabase_jwt_rejects_invalid_or_non_user_tokens() -> None:
    verifier = SupabaseJWTVerifier(
        issuer="https://project.supabase.co/auth/v1",
        decoder=lambda *_: {"sub": "not-a-uuid", "role": "service_role"},
    )

    with pytest.raises(AuthenticationError):
        verifier.verify("bad-token")


class SessionWorkspaces:
    def __init__(self, workspace):
        self.workspace = workspace
        self.calls = []

    def get_owned(self, user_id, workspace_id):
        self.calls.append(("get_owned", user_id, workspace_id))
        return self.workspace if self.workspace.user_id == user_id and self.workspace.id == workspace_id else None

    def get_active(self, user_id):
        return self.workspace if self.workspace.user_id == user_id else None

    def acquire_lock(self, context, ttl_seconds=60):
        self.calls.append(("acquire", context.operation_id, ttl_seconds))
        return self.workspace

    def release_lock(self, context):
        self.calls.append(("release", context.operation_id))
        return True

    def advance_revision(self, context, checksum):
        self.calls.append(("advance", context.source_revision, checksum))
        return self.workspace


class SessionStorage:
    def __init__(self, content=b"original-workbook"):
        self.content = content
        self.calls = []

    def download_current(self, context, destination_dir):
        path = destination_dir / "current.xlsx"
        path.write_bytes(self.content)
        self.calls.append(("download", context.user_id, context.workspace_id))
        return path

    def download_rules(self, context, destination_dir):
        return None

    def backup_current(self, context, checksum):
        self.calls.append(("backup", checksum))
        return "backup.xlsx"

    def upload_current(self, context, source):
        self.calls.append(("upload", source.read_bytes()))


class SessionOperations:
    def __init__(self):
        self.calls = []

    def record(self, context, *, tool_name, status, result=None):
        self.calls.append((tool_name, status, result))


class SessionTools:
    def __init__(self, context, mutate):
        self.context = context
        self.mutate = mutate

    def __getattr__(self, name):
        def call(*args):
            if self.mutate and name == "add_task":
                self.context.workbook_path.write_bytes(b"changed-workbook")
            return {"success": True, "tool": name, "args": list(args)}

        return call


class SessionToolsFactory:
    def __init__(self, context, mutate):
        self.context = context
        self.mutate = mutate

    def create(self, context):
        assert context.user_id == self.context.user_id
        return SessionTools(context, self.mutate)


def _workspace(user_id, workspace_id):
    return SimpleNamespace(
        id=workspace_id,
        user_id=user_id,
        timezone="Asia/Kolkata",
        active_execution_target="none",
        revision=4,
    )


def _session(tmp_path, *, mutate):
    user_id, workspace_id = uuid4(), uuid4()
    workspace = _workspace(user_id, workspace_id)
    workspaces = SessionWorkspaces(workspace)
    storage = SessionStorage()
    operations = SessionOperations()

    def builder(root, context):
        del root
        return SessionToolsFactory(context, mutate)

    return (
        WorkbookSession(
            user_id=user_id,
            workspace_id=workspace_id,
            workspaces=workspaces,
            storage=storage,
            operations=operations,
            tools_factory_builder=builder,
        ),
        workspaces,
        storage,
        operations,
    )


def test_read_session_does_not_lock_backup_or_upload(tmp_path) -> None:
    session, workspaces, storage, operations = _session(tmp_path, mutate=False)

    result = session.execute("validate")

    assert result["success"] is True
    assert [call[0] for call in storage.calls] == ["download"]
    assert not any(call[0] in {"acquire", "release", "advance"} for call in workspaces.calls)
    assert [call[1] for call in operations.calls] == ["running", "succeeded"]


def test_workbook_write_locks_backs_up_uploads_and_advances_revision(tmp_path) -> None:
    session, workspaces, storage, operations = _session(tmp_path, mutate=True)

    result = session.execute("add_task", {"task": "Read", "week": 1})

    assert result["source_revision"] == 5
    assert [call[0] for call in storage.calls] == ["download", "backup", "upload"]
    assert [call[0] for call in workspaces.calls] == ["get_owned", "acquire", "advance", "release"]
    assert operations.calls[-1][1] == "succeeded"


def test_credential_cipher_is_tenant_bound_and_authenticated(tmp_path) -> None:
    cipher = CredentialCipher(b"k" * 32)
    first = PlannerContext(uuid4(), uuid4(), uuid4(), tmp_path / "a.xlsx", "UTC", "none", 0)
    second = PlannerContext(uuid4(), first.workspace_id, uuid4(), tmp_path / "b.xlsx", "UTC", "none", 0)
    encrypted = cipher.encrypt(b'{"refresh_token":"secret"}', context=first)

    assert b"secret" not in encrypted
    assert cipher.decrypt(encrypted, context=first) == b'{"refresh_token":"secret"}'
    with pytest.raises(Exception):
        cipher.decrypt(encrypted, context=second)


def test_oauth_state_stores_only_hash_and_is_consumed_atomically(tmp_path) -> None:
    context = PlannerContext(uuid4(), uuid4(), uuid4(), tmp_path / "a.xlsx", "UTC", "none", 0)
    user_gateway, service_gateway = FakeGateway(), FakeGateway()
    repository = SupabaseOAuthStateRepository(user_gateway, service_gateway)

    state = repository.create(context, "http://localhost:8000/auth/google/callback", "pkce-verifier")

    payload = user_gateway.calls[0][2]
    assert state not in str(payload)
    assert len(payload["state_hash"]) == 64
    service_gateway.rpc_result = {
        **payload,
        "user_id": str(context.user_id),
        "workspace_id": str(context.workspace_id),
    }
    consumed = repository.consume(state)
    assert consumed.user_id == context.user_id
    assert service_gateway.calls[0][1] == "consume_google_oauth_state"


def test_calendar_connection_repository_never_stores_plaintext_credentials(tmp_path) -> None:
    context = PlannerContext(uuid4(), uuid4(), uuid4(), tmp_path / "a.xlsx", "UTC", "none", 0)
    gateway = FakeGateway()
    encrypted = b"encrypted-bytes"
    row = {
        "user_id": str(context.user_id),
        "workspace_id": str(context.workspace_id),
        "provider": "google_calendar",
        "encrypted_credentials": "\\x" + encrypted.hex(),
        "target_calendar_id": "primary",
        "status": "active",
    }
    gateway.insert_result = [row]

    saved = SupabaseCalendarConnectionRepository(gateway).save(context, encrypted)

    assert saved.encrypted_credentials == encrypted
    assert gateway.calls[-1][2]["encrypted_credentials"] == "\\x" + encrypted.hex()
    assert "refresh_token" not in str(gateway.calls)


def test_google_client_factory_requires_workspace_connection(tmp_path) -> None:
    context = PlannerContext(uuid4(), uuid4(), uuid4(), tmp_path / "a.xlsx", "UTC", "none", 0)
    repository = SimpleNamespace(get=lambda *_: None)

    with pytest.raises(GoogleConnectionRequiredError):
        SupabaseGoogleCalendarClientFactory(repository, CredentialCipher(b"k" * 32))(context)


def test_google_oauth_start_and_callback_keep_identity_in_one_time_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", "web-client")
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_SECRET", "web-secret")
    context = PlannerContext(uuid4(), uuid4(), uuid4(), tmp_path / "a.xlsx", "UTC", "none", 0)

    class States:
        def create(self, received, redirect_uri, code_verifier):
            assert received == context
            assert redirect_uri.endswith("/auth/google/callback")
            assert code_verifier
            return "state-value"

        def consume(self, state):
            assert state == "state-value"
            return SimpleNamespace(
                user_id=context.user_id,
                workspace_id=context.workspace_id,
                redirect_uri="http://localhost:8000/auth/google/callback",
                code_verifier="pkce-verifier",
            )

    saved = []

    class Connections:
        def save(self, received, encrypted):
            saved.append((received, encrypted))

    class Flow:
        credentials = SimpleNamespace(to_json=lambda: '{"refresh_token":"secret"}')

        def authorization_url(self, **kwargs):
            assert kwargs["access_type"] == "offline"
            return "https://accounts.google.com/o/oauth2/auth", "state-value"

        def fetch_token(self, *, code):
            assert code == "authorization-code"

    service = GoogleOAuthService(
        States(),
        Connections(),
        CredentialCipher(b"k" * 32),
        flow_factory=lambda redirect_uri, state, code_verifier: Flow(),
    )

    start = service.start(context)
    completed = service.complete(state="state-value", code="authorization-code")

    assert start.authorization_url.startswith("https://accounts.google.com/")
    assert completed.user_id == context.user_id
    assert b"secret" not in saved[0][1]


class FakeVerifier:
    def __init__(self, user_id):
        self.user_id = user_id

    def verify(self, token):
        if token != "valid-token":
            raise AuthenticationError("invalid token")
        return SimpleNamespace(user_id=self.user_id, access_token=token)


class FakeRuntime:
    def __init__(self, user_id, workspace_id):
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.execute_calls = []

    def workspaces(self, user):
        assert user.user_id == self.user_id
        record = SimpleNamespace(
            id=self.workspace_id,
            name="Planner",
            timezone="UTC",
            active_execution_target="none",
            revision=1,
            is_active=True,
        )
        return SimpleNamespace(list_owned=lambda _: [record])

    def execute(self, user, workspace_id, tool_name, arguments):
        self.execute_calls.append((user.user_id, workspace_id, tool_name, arguments))
        return {"success": True, "message": "done", "data": {}}


def test_api_requires_bearer_auth_and_never_accepts_client_user_id() -> None:
    user_id, workspace_id = uuid4(), uuid4()
    runtime = FakeRuntime(user_id, workspace_id)
    client = TestClient(create_app(runtime=runtime, verifier=FakeVerifier(user_id)))

    assert client.get("/api/workspaces").status_code == 401
    response = client.post(
        f"/api/workspaces/{workspace_id}/tools/validate",
        headers={"Authorization": "Bearer valid-token"},
        json={"arguments": {}},
    )
    injected = client.post(
        f"/api/workspaces/{workspace_id}/tools/validate",
        headers={"Authorization": "Bearer valid-token"},
        json={"arguments": {"user_id": str(uuid4())}},
    )

    assert response.status_code == 200
    assert runtime.execute_calls[0][0] == user_id
    assert injected.status_code == 400
    assert injected.json()["errors"] == ["TOOL_REGISTRY_ERROR"]
    assert len(runtime.execute_calls) == 1


def test_api_tool_catalog_matches_92_tool_manifest_and_disables_apple_cloud_tools() -> None:
    user_id, workspace_id = uuid4(), uuid4()
    client = TestClient(create_app(runtime=FakeRuntime(user_id, workspace_id), verifier=FakeVerifier(user_id)))

    response = client.get("/api/tools", headers={"Authorization": "Bearer valid-token"})
    tools = response.json()["data"]["tools"]

    assert response.status_code == 200
    assert len(tools) == 92
    assert all(not item["available"] for item in tools if item["name"].startswith("apple_calendar"))
    assert next(item for item in tools if item["name"] == "validate")["available"] is True
    schema = client.get("/openapi.json").json()
    assert f"/api/workspaces/{{workspace_id}}/tools/{{tool_name}}" in schema["paths"]


def test_stage_5_migration_limits_oauth_state_consumer_to_service_role() -> None:
    sql = Path("supabase/migrations/0002_google_oauth.sql").read_text(encoding="utf-8").casefold()

    assert "security definer" in sql
    assert "consumed_at is null" in sql
    assert "expires_at > now()" in sql
    assert "revoke execute" in sql
    assert "to service_role" in sql
