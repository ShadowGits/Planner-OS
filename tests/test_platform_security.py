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


def test_api_requires_bearer_auth_for_workspace_listing() -> None:
    user_id, workspace_id = uuid4(), uuid4()
    runtime = FakeRuntime(user_id, workspace_id)
    client = TestClient(create_app(runtime=runtime, verifier=FakeVerifier(user_id)))

    assert client.get("/api/workspaces").status_code == 401
    response = client.get("/api/workspaces", headers={"Authorization": "Bearer valid-token"})

    assert response.status_code == 200
    assert response.json()["data"]["workspaces"][0]["id"] == str(workspace_id)


def test_stage_5_migration_limits_oauth_state_consumer_to_service_role() -> None:
    sql = Path("supabase/migrations/0002_google_oauth.sql").read_text(encoding="utf-8").casefold()

    assert "security definer" in sql
    assert "consumed_at is null" in sql
    assert "expires_at > now()" in sql
    assert "revoke execute" in sql
    assert "to service_role" in sql
