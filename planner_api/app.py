"""Authenticated FastAPI surface for Planner OS cloud candidates."""

from __future__ import annotations

import base64
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from adapters.supabase import SupabaseCalendarConnectionRepository, SupabaseWorkbookObjectStore
from planner_api.config import load_local_environment
from planner_api.mcp import create_cloud_mcp
from planner_api.runtime import CloudRuntime
from planner_platform.auth import (
    AuthenticatedUser,
    AuthenticationError,
    SupabaseJWTVerifier,
    bearer_token,
)
from planner_platform.context import PlannerContext
from planner_platform.function_manifest import build_manifest
from planner_platform.policies import CloudStatus, policy_for
from planner_platform.tool_registry import ToolRegistryError


logger = logging.getLogger(__name__)


class ToolCall(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class VersionedToolCall(ToolCall):
    workspace_id: UUID


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    workbook_base64: str = Field(min_length=1)


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
    # MCP auth uses a simple API key — activate when key + public URL are set.
    cloud_mcp = None
    cloud_mcp_app = None
    if os.environ.get("MCP_API_KEY") and os.environ.get("PLANNER_WEB_APP_URL"):
        cloud_mcp, cloud_mcp_app = create_cloud_mcp(cloud)

    @asynccontextmanager
    async def lifespan(app):
        del app
        if cloud_mcp is None:
            yield
            return
        async with cloud_mcp.session_manager.run():
            yield

    api = FastAPI(title="Planner OS API", version="3.0-stage9", docs_url="/api/docs", lifespan=lifespan)
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

    def current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
        try:
            return token_verifier.verify(bearer_token(authorization))
        except AuthenticationError as error:
            raise _api_error(401, "AUTHENTICATION_REQUIRED", str(error)) from error

    @api.get("/api/health")
    def health_check() -> dict[str, Any]:
        """Simple health check endpoint."""
        import os
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        return envelope(True, "Planner OS API is ready", data={"version": api.version, "key_prefix": key[:15]})

    @api.get("/api/tools")
    @api.get("/api/v1/tools")
    def list_tools(user=Depends(current_user)):
        del user
        tools = []
        for record in build_manifest()["tools"]:
            policy = policy_for(record)
            tools.append(
                {
                    "name": record["name"],
                    "description": record["description"],
                    "parameters": record["parameters"],
                    "effect": policy.effect.value,
                    "confirmation": policy.confirmation.value,
                    "available": policy.cloud_status == CloudStatus.CANDIDATE,
                    "unavailable_reason": policy.cloud_reason if policy.cloud_status != CloudStatus.CANDIDATE else None,
                }
            )
        return envelope(True, "Planner tools listed", data={"tools": tools, "count": len(tools)})

    @api.get("/api/v1/tools/{tool_name}")
    def get_tool(tool_name: str, user=Depends(current_user)):
        del user
        record = next((item for item in build_manifest()["tools"] if item["name"] == tool_name), None)
        if record is None:
            raise _api_error(404, "TOOL_NOT_REGISTERED", "Planner tool was not found")
        policy = policy_for(record)
        return envelope(
            True,
            "Planner tool described",
            data={
                "tool": {
                    "name": record["name"],
                    "description": record["description"],
                    "parameters": record["parameters"],
                    "effect": policy.effect.value,
                    "confirmation": policy.confirmation.value,
                    "available": policy.cloud_status == CloudStatus.CANDIDATE,
                    "unavailable_reason": (
                        policy.cloud_reason if policy.cloud_status != CloudStatus.CANDIDATE else None
                    ),
                }
            },
        )

    @api.get("/api/workspaces")
    def list_workspaces(user=Depends(current_user)):
        records = cloud.workspaces(user).list_owned(user.user_id)
        return envelope(True, "Planner workspaces listed", data={"workspaces": [_workspace(item) for item in records]})

    @api.post("/api/workspaces")
    def create_workspace(body: WorkspaceCreate, user=Depends(current_user)):
        try:
            content = base64.b64decode(body.workbook_base64, validate=True)
            if not content.startswith(b"PK"):
                raise ValueError("Workbook must be an xlsx file")
            repository = cloud.workspaces(user)
            workspace = repository.create(user.user_id, name=body.name, timezone=body.timezone)
            context = PlannerContext(
                user_id=user.user_id,
                workspace_id=workspace.id,
                operation_id=uuid4(),
                workbook_path=Path("upload.xlsx"),
                timezone=workspace.timezone,
                execution_target=workspace.active_execution_target,
                source_revision=workspace.revision,
            )
            with TemporaryDirectory(prefix="planner-upload-") as directory:
                source = Path(directory) / "upload.xlsx"
                source.write_bytes(content)
                SupabaseWorkbookObjectStore(cloud.user_client(user)).upload_current(context, source)
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

    @api.get("/api/workspaces/{workspace_id}/workbook")
    def download_workbook(workspace_id: UUID, user=Depends(current_user)):
        try:
            context = cloud.context(user, workspace_id)
            content = cloud.user_client(user).storage_download(
                "planner-workbooks",
                f"{context.user_id}/{context.workspace_id}/current.xlsx",
            )
            return Response(
                content=content,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="planner-os.xlsx"'},
            )
        except ValueError as error:
            raise _api_error(404, "WORKSPACE_NOT_FOUND", "Planner workspace was not found") from error

    @api.post("/api/workspaces/{workspace_id}/tools/{tool_name}")
    def invoke_tool(
        workspace_id: UUID,
        tool_name: str,
        body: ToolCall,
        user=Depends(current_user),
    ):
        try:
            reserved = {"user_id", "workspace_id", "operation_id", "workbook_path", "access_token"}
            supplied = sorted(reserved.intersection(body.arguments))
            if supplied:
                raise ToolRegistryError(f"Authoritative request fields are not accepted: {supplied}")
            return cloud.execute(user, workspace_id, tool_name, body.arguments)
        except ToolRegistryError as error:
            raise _api_error(400, getattr(error, "code", "TOOL_REQUEST_INVALID"), str(error)) from error
        except ValueError as error:
            raise _api_error(404, "WORKSPACE_OR_RESOURCE_NOT_FOUND", str(error)) from error
        except Exception as error:
            raise _api_error(409, "PLANNER_OPERATION_CONFLICT", "Planner operation could not be completed") from error

    @api.post("/api/v1/tools/{tool_name}/invoke")
    def invoke_versioned_tool(tool_name: str, body: VersionedToolCall, user=Depends(current_user)):
        return invoke_tool(body.workspace_id, tool_name, ToolCall(arguments=body.arguments), user)

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
            web_app_url = os.environ.get("PLANNER_WEB_APP_URL", "").rstrip("/")
            if web_app_url:
                return RedirectResponse(
                    f"{web_app_url}/?calendar=connected&workspace_id={context.workspace_id}",
                    status_code=303,
                )
            return envelope(True, "Google Calendar connected", data={"workspace_id": str(context.workspace_id)}, operation="google_calendar_callback", target="google_calendar")
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

    if cloud_mcp_app is not None:
        api.mount("/", cloud_mcp_app)

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


