"""Authenticated FastAPI surface for Planner OS cloud candidates."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from adapters.supabase import SupabaseCalendarConnectionRepository
from planner_api.config import load_local_environment
from mcp.server.auth.provider import AuthorizationParams
from planner_api.mcp import create_cloud_mcp
from planner_api.runtime import CloudRuntime
from planner_platform.auth import (
    AuthenticatedUser,
    AuthenticationError,
    SupabaseJWTVerifier,
    bearer_token,
)


logger = logging.getLogger(__name__)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)


def envelope(
    success: bool,
    message: str,
    *,
    data: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    operation: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    return {
        "success": success,
        "message": message,
        "data": data or {},
        "warnings": [],
        "errors": errors or [],
        "preview_id": None,
        "requires_confirmation": False,
        "operation": operation,
        "target": target,
        "decision_id": None,
    }


def create_app(*, runtime: CloudRuntime | None = None, verifier: SupabaseJWTVerifier | None = None) -> FastAPI:
    load_local_environment()
    cloud = runtime or CloudRuntime()
    # The REST API (/api/*) still uses Supabase JWT verification.
    token_verifier = verifier or SupabaseJWTVerifier()
    # MCP with full OAuth — activate when key + public URL are set.
    cloud_mcp = None
    cloud_mcp_app = None
    oauth_provider = None
    if os.environ.get("MCP_API_KEY") and os.environ.get("PLANNER_API_URL"):
        cloud_mcp, cloud_mcp_app, oauth_provider = create_cloud_mcp(cloud)
        logger.info("MCP server created with %d tools", len(cloud_mcp._tool_manager._tools))

    @asynccontextmanager
    async def lifespan(app):
        del app
        if cloud_mcp is None:
            yield
            return
        async with cloud_mcp.session_manager.run():
            yield

    api = FastAPI(
        title="Planner OS API",
        version="3.0-stage9",
        docs_url="/api/docs",
        lifespan=lifespan,
        servers=[{"url": os.environ.get("PLANNER_API_URL", "https://planner-os-api-2pikvfrvbq-uc.a.run.app")}],
    )
    origins = [item.strip() for item in os.environ.get("PLANNER_WEB_ORIGINS", "http://localhost:3000").split(",") if item.strip()]
    api.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @api.exception_handler(HTTPException)
    async def http_error_handler(request: Request, error: HTTPException):
        del request
        detail = error.detail if isinstance(error.detail, dict) else {"code": "REQUEST_FAILED", "message": str(error.detail)}
        return JSONResponse(
            status_code=error.status_code,
            content=envelope(False, detail.get("message", "Request failed"), errors=[detail.get("code", "REQUEST_FAILED")]),
        )

    @api.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, error: RequestValidationError):
        del request, error
        return JSONResponse(
            status_code=422,
            content=envelope(False, "Request validation failed", errors=["REQUEST_VALIDATION_FAILED"]),
        )

    def current_user(authorization: str | None = Header(default=None, include_in_schema=False)) -> AuthenticatedUser:
        try:
            token = bearer_token(authorization)
        except AuthenticationError as error:
            raise _api_error(401, "AUTHENTICATION_REQUIRED", str(error)) from error
        import secrets
        import json

        # Support single-tenant MCP_API_KEY
        mcp_key = os.environ.get("MCP_API_KEY")
        if mcp_key and secrets.compare_digest(token, mcp_key):
            return AuthenticatedUser(user_id=UUID(os.environ.get("MCP_USER_ID", "00000000-0000-0000-0000-000000000000")), access_token=None)
            
        # Support multi-tenant MCP_ACCOUNTS mapping
        accounts_json = os.environ.get("MCP_ACCOUNTS")
        if accounts_json:
            try:
                accounts = json.loads(accounts_json)
                for key, user_id in accounts.items():
                    if secrets.compare_digest(token, key):
                        return AuthenticatedUser(user_id=UUID(user_id), access_token=None)
            except json.JSONDecodeError:
                pass
        try:
            return token_verifier.verify(token)
        except AuthenticationError as error:
            raise _api_error(401, "AUTHENTICATION_REQUIRED", str(error)) from error

    @api.get("/api/health")
    def health_check() -> dict[str, Any]:
        """Simple health check endpoint."""
        import os
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        return envelope(True, "Planner OS API is ready", data={"version": api.version, "key_prefix": key[:15]})

    @api.get("/api/mcp-status")
    def mcp_status() -> dict[str, Any]:
        if cloud_mcp is None:
            return envelope(False, "MCP not configured", data={"tool_count": 0})
        tool_count = len(cloud_mcp._tool_manager._tools)
        tool_names = sorted(cloud_mcp._tool_manager._tools.keys())
        return envelope(True, "MCP server active", data={"tool_count": tool_count, "tools": tool_names})

    @api.get("/api/workspaces")
    def list_workspaces(user=Depends(current_user)):
        records = cloud.workspaces(user).list_owned(user.user_id)
        return envelope(True, "Planner workspaces listed", data={"workspaces": [_workspace(item) for item in records]})

    @api.post("/api/workspaces")
    def create_workspace(body: WorkspaceCreate, user=Depends(current_user)):
        try:
            repository = cloud.workspaces(user)
            workspace = repository.create(user.user_id, name=body.name, timezone=body.timezone)
            workspace = repository.activate(user.user_id, workspace.id)
            return envelope(True, "Planner workspace created", data={"workspace": _workspace(workspace)})
        except Exception as error:
            raise _api_error(400, "WORKSPACE_CREATE_FAILED", str(error)) from error

    @api.post("/api/workspaces/{workspace_id}/activate")
    def activate_workspace(workspace_id: UUID, user=Depends(current_user)):
        try:
            workspace = cloud.workspaces(user).activate(user.user_id, workspace_id)
            return envelope(True, "Planner workspace activated", data={"workspace": _workspace(workspace)})
        except ValueError as error:
            raise _api_error(404, "WORKSPACE_NOT_FOUND", str(error)) from error

    @api.post("/api/workspaces/{workspace_id}/google-calendar/connect")
    def connect_google(workspace_id: UUID, user=Depends(current_user)):
        try:
            context = cloud.context(user, workspace_id)
            result = cloud.google_oauth_for_user(user).start(context)
            return envelope(
                True,
                "Google Calendar authorization started",
                data={"authorization_url": result.authorization_url, "expires_in_seconds": result.expires_in_seconds},
                operation="google_calendar_connect",
                target="google_calendar",
            )
        except ValueError as error:
            raise _api_error(400, "GOOGLE_CONNECT_FAILED", str(error)) from error

    @api.get("/auth/google/callback")
    def google_callback(state: str = Query(min_length=32), code: str = Query(min_length=1)):
        try:
            context = cloud.google_oauth_callback().complete(state=state, code=code)
            html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Google Calendar Connected</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           display: flex; align-items: center; justify-content: center;
           min-height: 100vh; margin: 0; background: #f0fdf4; color: #166534; }}
    .card {{ text-align: center; padding: 2rem 3rem; background: white;
             border-radius: 1rem; box-shadow: 0 4px 24px rgba(0,0,0,.08); }}
    .icon {{ font-size: 3rem; margin-bottom: 1rem; }}
    h1 {{ font-size: 1.5rem; margin: 0 0 .5rem; }}
    p {{ color: #64748b; margin: 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">&#x2705;</div>
    <h1>Google Calendar Connected!</h1>
    <p>Workspace <code>{context.workspace_id}</code> is ready.<br>You can close this tab and return to your assistant.</p>
  </div>
  <script>setTimeout(() => window.close(), 3000);</script>
</body>
</html>"""
            return HTMLResponse(content=html, status_code=200)
        except Exception as error:
            logger.error(
                "Google Calendar callback failed (%s): %s",
                type(error).__name__,
                error,
            )
            raise _api_error(400, "GOOGLE_CALLBACK_FAILED", "Google Calendar authorization could not be completed") from error

    @api.get("/api/workspaces/{workspace_id}/google-calendar/status")
    def google_status(workspace_id: UUID, user=Depends(current_user)):
        context = cloud.context(user, workspace_id)
        connection = SupabaseCalendarConnectionRepository(cloud.user_client(user)).get(
            context.user_id,
            context.workspace_id,
        )
        return envelope(
            True,
            "Google Calendar connection status",
            data={
                "connected": bool(connection and connection.status == "active"),
                "status": connection.status if connection else "not_connected",
                "calendar_id": connection.target_calendar_id if connection else None,
            },
            target="google_calendar",
        )

    @api.delete("/api/workspaces/{workspace_id}/google-calendar")
    def disconnect_google(workspace_id: UUID, user=Depends(current_user)):
        context = cloud.context(user, workspace_id)
        SupabaseCalendarConnectionRepository(cloud.user_client(user)).set_status(context, "revoked")
        return envelope(True, "Google Calendar disconnected", target="google_calendar")

    from planner_api.calendar_bridge import register_calendar_routes
    from planner_api.dashboard import register_dashboard_routes
    from planner_api.day import register_day_routes
    from planner_api.v2 import register_v2_routes

    register_v2_routes(api, cloud, current_user)
    register_day_routes(api, cloud)
    register_dashboard_routes(api, cloud)
    register_calendar_routes(api, cloud)

    if cloud_mcp_app is not None and oauth_provider is not None:
        @api.get("/oauth/authorize/confirm", response_class=HTMLResponse)
        async def oauth_confirm_page(
            client_id: str = Query(...),
            redirect_uri: str = Query(...),
            state: str = Query(""),
            code_challenge: str = Query(...),
            redirect_uri_provided_explicitly: bool = Query(True),
        ):
            return f"""<!doctype html>
<html><head><title>Planner OS — Authorize</title>
<style>
  body {{ font-family: system-ui, sans-serif; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
  .card {{ background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.1);
           max-width: 400px; width: 100%; }}
  h1 {{ font-size: 1.2rem; margin: 0 0 1rem; }}
  input {{ width: 100%; padding: .6rem; margin: .5rem 0; box-sizing: border-box;
           border: 1px solid #ddd; border-radius: 6px; font-size: .95rem; }}
  button {{ width: 100%; padding: .7rem; margin-top: .5rem; background: #2563eb; color: white;
            border: none; border-radius: 6px; font-size: 1rem; cursor: pointer; }}
  button:hover {{ background: #1d4ed8; }}
  .error {{ color: #dc2626; font-size: .85rem; display: none; margin-top: .5rem; }}
</style></head><body>
<div class="card">
  <h1>Authorize Planner OS</h1>
  <p>Paste your API key to connect Claude to your workspace.</p>
  <form method="POST" action="/oauth/authorize/submit">
    <input type="hidden" name="client_id" value="{client_id}">
    <input type="hidden" name="redirect_uri" value="{redirect_uri}">
    <input type="hidden" name="state" value="{state}">
    <input type="hidden" name="code_challenge" value="{code_challenge}">
    <input type="hidden" name="redirect_uri_provided_explicitly" value="{redirect_uri_provided_explicitly}">
    <input type="password" name="api_key" placeholder="Your MCP API key" required autofocus>
    <button type="submit">Authorize</button>
  </form>
</div></body></html>"""

        @api.post("/oauth/authorize/submit")
        async def oauth_submit(request: Request):
            from urllib.parse import urlencode
            form = await request.form()
            api_key = str(form.get("api_key", ""))
            client_id = str(form.get("client_id", ""))
            redirect_uri_str = str(form.get("redirect_uri", ""))
            state = str(form.get("state", ""))
            code_challenge = str(form.get("code_challenge", ""))
            redirect_uri_explicit = str(form.get("redirect_uri_provided_explicitly", "True")).lower() == "true"

            matched_user = oauth_provider.validate_api_key(api_key)
            if not matched_user:
                return HTMLResponse(
                    "<html><body><h2>Invalid API key.</h2>"
                    "<p><a href='javascript:history.back()'>Try again</a></p>"
                    "</body></html>",
                    status_code=403,
                )

            client = await oauth_provider.get_client(client_id)
            if client is None:
                return HTMLResponse("<html><body><h2>Unknown client.</h2></body></html>", status_code=400)

            from pydantic import AnyUrl
            params = AuthorizationParams(
                state=state,
                scopes=[],
                code_challenge=code_challenge,
                redirect_uri=AnyUrl(redirect_uri_str),
                redirect_uri_provided_explicitly=redirect_uri_explicit,
            )
            code = await oauth_provider.create_authorization_code(client, params, matched_user)

            target = f"{redirect_uri_str}?{urlencode({'code': code, 'state': state})}"
            from starlette.responses import RedirectResponse
            return RedirectResponse(target, status_code=302)

        async def mcp_wrapper(scope, receive, send):
            if scope["type"] == "http" and scope.get("path") == "/messages":
                scope["path"] = "/messages/"
            await cloud_mcp_app(scope, receive, send)

        api.mount("/", mcp_wrapper)

    return api


def _workspace(record) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "name": record.name,
        "timezone": record.timezone,
        "active_execution_target": record.active_execution_target,
        "revision": record.revision,
        "is_active": record.is_active,
    }


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


_startup_error: str | None = None
try:
    app = create_app()
except Exception as _e:
    import sys
    import traceback
    _startup_error = f"{type(_e).__name__}: {_e}"
    traceback.print_exc(file=sys.stderr)
    app = FastAPI(title="Planner OS API (configuration required)")

    @app.get("/api/health")
    def configuration_health():
        return envelope(False, "Planner OS API configuration is incomplete", errors=[_startup_error or "Unknown startup error"])


