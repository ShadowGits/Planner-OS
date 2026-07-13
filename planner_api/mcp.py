"""Stateless MCP transport for the cloud Planner OS runtime.

Authentication model
--------------------
We use a simple static API key instead of OAuth / Supabase JWT.

Claude sends the API key as:  Authorization: Bearer <MCP_API_KEY>

Required environment variables
--------------------------------
MCP_API_KEY   – Long random secret shared only with Claude.
MCP_USER_ID   – UUID of the Planner OS owner whose workspace Claude should use.
                (The Supabase service-role key provides access without a user JWT.)
"""

from __future__ import annotations

import ast
import inspect
import os
import secrets
from typing import Any
from uuid import UUID

from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP

from planner_platform.auth import AuthenticationError
from planner_platform.function_manifest import build_manifest
from planner_platform.policies import CloudStatus, policy_for


_ANNOTATIONS = {
    None: Any,
    "bool | None": bool | None,
    "dict": dict,
    "dict | None": dict | None,
    "int": int,
    "list[str]": list[str],
    "object": object,
    "str": str,
    "str | None": str | None,
}


class ApiKeyTokenVerifier:
    """Verify that the bearer token matches the static MCP_API_KEY env var.

    Returns an AccessToken on match, None on mismatch (→ MCP SDK sends 401).
    """

    def __init__(self, api_key: str) -> None:
        if not api_key or len(api_key) < 32:
            raise ValueError(
                "MCP_API_KEY must be at least 32 characters long. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        self._api_key = api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        # Use constant-time comparison to avoid timing attacks
        if not secrets.compare_digest(token.strip(), self._api_key):
            return None
        return AccessToken(
            token=token,
            client_id="claude",
            scopes=[],
            subject="mcp-owner",
        )


def create_cloud_mcp(runtime) -> tuple[FastMCP, Any]:
    """Create a stateless MCP server authenticated by a static API key."""
    api_key = os.environ.get("MCP_API_KEY", "")
    if not api_key:
        raise ValueError(
            "MCP_API_KEY environment variable is required. "
            "Set it to a long random secret (min 32 chars)."
        )

    public_url = os.environ["PLANNER_WEB_APP_URL"].rstrip("/")

    server = FastMCP(
        "Planner OS",
        instructions=(
            "You are connected to Planner OS — a personal planning engine. "
            "Use the available tools to read, plan, and modify the user's active workspace. "
            "Preview destructive changes before applying them."
        ),
        website_url=public_url,
        # No auth= / AuthSettings: Claude connects directly with the API key.
        # The ApiKeyTokenVerifier validates the key; no OAuth discovery needed.
        token_verifier=ApiKeyTokenVerifier(api_key),
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
            structured_output=True,
            meta={
                "effect": policy.effect.value,
                "confirmation": policy.confirmation.value,
            },
        )

    return server, server.streamable_http_app()


def _tool_handler(runtime, record):
    """Build a tool handler that runs as the configured MCP owner user."""

    async def invoke(**arguments):
        user_id_str = os.environ.get("MCP_USER_ID", "")
        if not user_id_str:
            raise ValueError(
                "MCP_USER_ID environment variable is required. "
                "Set it to your Planner OS user UUID."
            )
        try:
            user_id = UUID(user_id_str)
        except ValueError as e:
            raise ValueError(f"MCP_USER_ID is not a valid UUID: {user_id_str!r}") from e

        # Use the service-role client (no user JWT needed) so we can read
        # the workspace on behalf of the owner without Supabase RLS blocking us.
        from adapters.supabase.client import SupabaseConfig, SupabaseRestClient
        from adapters.supabase.workspaces import SupabaseWorkspaceRepository

        service_client = SupabaseRestClient(SupabaseConfig.from_env())
        workspace = SupabaseWorkspaceRepository(service_client).get_active(user_id)
        if workspace is None:
            raise ValueError(
                "No active Planner OS workspace found. "
                "Create and activate a workspace in the Planner OS web app first."
            )

        # Build a synthetic AuthenticatedUser using the service-role token so
        # CloudRuntime.execute() can construct a user-scoped Supabase client.
        from planner_platform.auth import AuthenticatedUser

        service_token = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        user = AuthenticatedUser(user_id=user_id, access_token=service_token)
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
