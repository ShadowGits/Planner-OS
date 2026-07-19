"""Stateless MCP transport for the cloud Planner OS runtime.

Authentication model
--------------------
Full OAuth 2.0 flow backed by static API keys.

Clients (Claude Desktop, claude.ai, mcp-remote) go through standard OAuth
discovery → dynamic client registration → authorize → token exchange.
The authorize step shows a simple HTML form where the user pastes their
API key. On success the server mints a short-lived access token and a
long-lived refresh token, persisted (hashed) in Supabase so they survive
deploys and cold starts.

Required environment variables
--------------------------------
MCP_API_KEY   – Long random secret shared only with Claude.
MCP_USER_ID   – UUID of the Planner OS owner whose workspace Claude should use.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import os
import secrets
import time
from typing import Any
from uuid import UUID

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from planner_platform.function_manifest import build_manifest
from planner_platform.policies import CloudStatus, policy_for


_ANNOTATIONS = {
    None: Any,
    "bool | None": bool | None,
    "dict": dict,
    "dict | None": dict | None,
    "int": int,
    "list[dict]": list[dict],
    "list[str]": list[str],
    "object": object,
    "str": str,
    "str | None": str | None,
}

ACCESS_TOKEN_TTL = 3600
REFRESH_TOKEN_TTL = 86400 * 30
AUTH_CODE_TTL = 300


class ApiKeyOAuthProvider:
    """OAuth provider backed by static API keys.

    Clients, auth codes, and tokens live in a pluggable state store. With the
    Supabase-backed store they survive deploys and cold starts, so connected
    MCP clients stay authorized. Codes and tokens are keyed by SHA-256 hash;
    the raw secrets are never persisted.
    """

    def __init__(self, accounts: dict[str, str], public_url: str, store: Any | None = None) -> None:
        if not accounts:
            raise ValueError("At least one MCP account must be configured.")
        for api_key in accounts:
            if len(api_key) < 32:
                raise ValueError("All MCP API keys must be at least 32 characters long.")
        self._accounts = accounts
        self._public_url = public_url
        if store is None:
            from adapters.supabase.oauth_state import MemoryOAuthStateStore

            store = MemoryOAuthStateStore()
        self._store = store

    @staticmethod
    def _digest(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        payload = self._store.get("client", client_id)
        if payload is None:
            return None
        return OAuthClientInformationFull.model_validate(payload)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._store.put(
            "client",
            client_info.client_id,
            client_info.model_dump(mode="json"),
            None,
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        return (
            f"{self._public_url}/oauth/authorize/confirm"
            f"?client_id={client.client_id}"
            f"&redirect_uri={params.redirect_uri}"
            f"&state={params.state or ''}"
            f"&code_challenge={params.code_challenge}"
            f"&redirect_uri_provided_explicitly={params.redirect_uri_provided_explicitly}"
        )

    async def create_authorization_code(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
        user_id: str,
    ) -> str:
        code = secrets.token_urlsafe(32)
        record = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            subject=user_id,
        )
        self._store.put(
            "auth_code",
            self._digest(code),
            record.model_dump(mode="json", exclude={"code"}),
            record.expires_at,
        )
        return code

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        payload = self._store.get("auth_code", self._digest(authorization_code))
        if payload is None:
            return None
        ac = AuthorizationCode.model_validate({**payload, "code": authorization_code})
        if ac.client_id == client.client_id and time.time() < ac.expires_at:
            return ac
        return None

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        self._store.delete("auth_code", self._digest(authorization_code.code))
        return self._issue_tokens(
            client.client_id, authorization_code.scopes, authorization_code.subject
        )

    def _issue_tokens(self, client_id: str, scopes: list[str], subject: str) -> OAuthToken:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        access_record = AccessToken(
            token=access,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time() + ACCESS_TOKEN_TTL),
            subject=subject,
        )
        refresh_record = RefreshToken(
            token=refresh,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time() + REFRESH_TOKEN_TTL),
            subject=subject,
        )
        self._store.put(
            "access_token",
            self._digest(access),
            access_record.model_dump(mode="json", exclude={"token"}),
            float(access_record.expires_at),
        )
        self._store.put(
            "refresh_token",
            self._digest(refresh),
            refresh_record.model_dump(mode="json", exclude={"token"}),
            float(refresh_record.expires_at),
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        payload = self._store.get("refresh_token", self._digest(refresh_token))
        if payload is None:
            return None
        rt = RefreshToken.model_validate({**payload, "token": refresh_token})
        if rt.client_id != client.client_id:
            return None
        if rt.expires_at and time.time() > rt.expires_at:
            self._store.delete("refresh_token", self._digest(refresh_token))
            return None
        return rt

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        self._store.delete("refresh_token", self._digest(refresh_token.token))
        return self._issue_tokens(
            client.client_id, scopes or refresh_token.scopes, refresh_token.subject
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        payload = self._store.get("access_token", self._digest(token))
        if payload is not None:
            at = AccessToken.model_validate({**payload, "token": token})
            if at.expires_at and time.time() > at.expires_at:
                self._store.delete("access_token", self._digest(token))
                return None
            return at
        user_id = self.validate_api_key(token)
        if user_id:
            return AccessToken(
                token=token,
                client_id="api-key-direct",
                scopes=[],
                expires_at=int(time.time() + ACCESS_TOKEN_TTL),
                subject=user_id,
            )
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self._store.delete("access_token", self._digest(token.token))
        self._store.delete("refresh_token", self._digest(token.token))

    def validate_api_key(self, api_key: str) -> str | None:
        api_key = api_key.strip()
        for stored_key, user_id in self._accounts.items():
            if secrets.compare_digest(api_key, stored_key):
                return user_id
        return None


def create_cloud_mcp(runtime) -> tuple[FastMCP, Any, ApiKeyOAuthProvider]:
    """Create a stateless MCP server with full OAuth support."""
    import json

    accounts = {}

    accounts_json = os.environ.get("MCP_ACCOUNTS")
    if accounts_json:
        try:
            accounts = json.loads(accounts_json)
        except json.JSONDecodeError as e:
            raise ValueError("MCP_ACCOUNTS environment variable is not valid JSON.") from e

    api_key = os.environ.get("MCP_API_KEY", "")
    user_id = os.environ.get("MCP_USER_ID", "")
    if api_key and user_id:
        accounts[api_key] = user_id

    if not accounts:
        raise ValueError(
            "No MCP accounts configured. "
            "Set MCP_ACCOUNTS to a JSON mapping of API keys to User UUIDs, "
            "or set MCP_API_KEY and MCP_USER_ID."
        )

    public_url = os.environ["PLANNER_API_URL"].rstrip("/")
    store = None
    try:
        from adapters.supabase.client import SupabaseConfig, SupabaseRestClient
        from adapters.supabase.oauth_state import SupabaseOAuthStateStore

        store = SupabaseOAuthStateStore(SupabaseRestClient(SupabaseConfig.from_env()))
    except ValueError:
        store = None
    oauth_provider = ApiKeyOAuthProvider(accounts, public_url, store=store)

    server = FastMCP(
        "Planner OS",
        instructions=(
            "You are connected to Planner OS — a personal planning engine. "
            "Use the available tools to read, plan, and modify the user's active workspace. "
            "Preview destructive changes before applying them."
        ),
        website_url=public_url,
        auth_server_provider=oauth_provider,
        auth=AuthSettings(
            issuer_url=public_url,
            resource_server_url=f"{public_url}/mcp",
            required_scopes=[],
            client_registration_options=ClientRegistrationOptions(enabled=True),
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
    )

    for record in build_manifest()["tools"]:
        policy = policy_for(record)
        if policy.cloud_status != CloudStatus.CANDIDATE:
            continue
        handler = _tool_handler(runtime, record)
        server.add_tool(
            handler,
            name=record["name"],
            description=record["description"],
            meta={
                "effect": policy.effect.value,
                "confirmation": policy.confirmation.value,
            },
        )

    return server, server.streamable_http_app(), oauth_provider


def _tool_handler(runtime, record):
    """Build a tool handler that runs as the authenticated user."""

    async def invoke(**arguments):
        from mcp.server.auth.middleware.auth_context import get_access_token

        token = get_access_token()
        if not token or not token.subject:
            raise ValueError(
                "Unauthorized: missing or invalid credentials. "
                "Re-authorize the Planner OS MCP integration."
            )

        try:
            user_id = UUID(token.subject)
        except ValueError as e:
            raise ValueError(f"Invalid user ID in auth context: {token.subject!r}") from e

        from adapters.supabase.client import SupabaseConfig, SupabaseRestClient
        from adapters.supabase.workspaces import SupabaseWorkspaceRepository

        service_client = SupabaseRestClient(SupabaseConfig.from_env())
        workspace = SupabaseWorkspaceRepository(service_client).get_active(user_id)
        if workspace is None:
            raise ValueError(
                "No active Planner OS workspace found. "
                "Create and activate a workspace in the Planner OS web app first."
            )

        from planner_platform.auth import AuthenticatedUser

        user = AuthenticatedUser(user_id=user_id, access_token=None)  # type: ignore
        return runtime.execute(user, workspace.id, record["name"], arguments)

    invoke.__name__ = str(record["name"])
    invoke.__doc__ = str(record["description"])
    invoke.__signature__ = inspect.Signature(
        parameters=[_parameter(item) for item in record["parameters"]],
        return_annotation=dict,
    )
    return invoke


def _parameter(record: dict[str, Any]) -> inspect.Parameter:
    default_text = record.get("default")
    default = inspect.Parameter.empty
    if default_text is not None:
        default = None if default_text == "None" else ast.literal_eval(default_text)
    return inspect.Parameter(
        str(record["name"]),
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        default=default,
        annotation=_ANNOTATIONS[record.get("annotation")],
    )
