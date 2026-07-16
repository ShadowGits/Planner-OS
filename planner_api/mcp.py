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
from mcp.server.auth.settings import AuthSettings
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
    "list[dict]": list[dict],
    "list[str]": list[str],
    "object": object,
    "str": str,
    "str | None": str | None,
}


class ApiKeyTokenVerifier:
    """Verify that the bearer token matches a configured API key.

    Returns an AccessToken on match with the matching user_id as the subject,
    or None on mismatch (→ MCP SDK sends 401).
    """

    def __init__(self, accounts: dict[str, str]) -> None:
        if not accounts:
            raise ValueError("At least one MCP account must be configured.")
        for api_key in accounts.keys():
            if len(api_key) < 32:
                raise ValueError("All MCP API keys must be at least 32 characters long.")
        self._accounts = accounts

    async def verify_token(self, token: str) -> AccessToken | None:
        token = token.strip()
        matched_user_id = None
        
        for api_key, user_id in self._accounts.items():
            # Use constant-time comparison to avoid timing attacks
            if secrets.compare_digest(token, api_key):
                matched_user_id = user_id
                break
                
        if not matched_user_id:
            return None
            
        return AccessToken(
            token=token,
            client_id="claude",
            scopes=[],
            subject=matched_user_id,
        )


def create_cloud_mcp(runtime) -> tuple[FastMCP, Any]:
    """Create a stateless MCP server authenticated by static API keys."""
    import json
    
    accounts = {}
    
    accounts_json = os.environ.get("MCP_ACCOUNTS")
    if accounts_json:
        try:
            accounts = json.loads(accounts_json)
        except json.JSONDecodeError as e:
            raise ValueError("MCP_ACCOUNTS environment variable is not valid JSON.") from e
            
    # Fallback to single user config for backwards compatibility
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

    public_url = os.environ["PLANNER_WEB_APP_URL"].rstrip("/")

    server = FastMCP(
        "Planner OS",
        instructions=(
            "You are connected to Planner OS — a personal planning engine. "
            "Use the available tools to read, plan, and modify the user's active workspace. "
            "Preview destructive changes before applying them."
        ),
        website_url=public_url,
        token_verifier=ApiKeyTokenVerifier(accounts),
        # auth= is required by the SDK whenever token_verifier is set.
        # We use our own URL as issuer — this is just metadata for WWW-Authenticate
        # headers. No OAuth routes are added (no auth_server_provider).
        # mcp-remote --transport http-only skips OAuth discovery entirely.
        auth=AuthSettings(
            issuer_url=public_url,
            resource_server_url=f"{public_url}/mcp",
            required_scopes=[],
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

    return server, server.streamable_http_app()


def _tool_handler(runtime, record):
    """Build a tool handler that runs as the configured MCP owner user."""

    async def invoke(**arguments):
        from mcp.server.auth.middleware.auth_context import get_access_token
        
        token = get_access_token()
        if not token or not token.subject:
            raise ValueError(
                "Unauthorized: missing or invalid API key. "
                "Ensure your Claude config has the correct API_KEY environment variable."
            )
            
        try:
            user_id = UUID(token.subject)
        except ValueError as e:
            raise ValueError(f"Invalid user ID in auth context: {token.subject!r}") from e

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

        # Build a synthetic AuthenticatedUser with access_token=None so
        # CloudRuntime.execute() uses the service role key for both the
        # apikey and Authorization headers to bypass Supabase RLS.
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
