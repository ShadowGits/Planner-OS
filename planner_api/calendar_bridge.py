"""Postgres → Google Calendar bridge.

Mirrors scheduled tasks (those with a scheduled_date and a start_time) from the
v2 Postgres tables into the user's Google Calendar, reusing the existing OAuth
client factory and the idempotent sync in planner_integrations. Runs unattended
behind CRON_SECRET — same trust model as /v2/reminders/run.

Each event is tied to its task by planner_block_id = task id, so when a task is
moved (drag/replan) the next sync updates the same event instead of creating a
duplicate, and when a task is unscheduled or deleted its event is removed.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Query

from adapters.supabase import SupabaseWorkspaceRepository
from planner_api.v2 import _configured_user_id
from planner_core.repository import PlannerCoreRepository
from planner_core.services import TaskService
from planner_engine.models import DailyPlan, ScheduledBlock
from planner_platform.context import PlannerContext
from planner_platform.google_oauth import GoogleConnectionRequiredError



def register_calendar_routes(api: FastAPI, cloud: Any) -> None:
    def _envelope(success: bool, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"success": success, "message": message, "data": data or {}, "errors": []}

    def _authorize_cron(key: str | None) -> None:
        expected = os.environ.get("CRON_SECRET", "")
        if not expected or not key or not secrets.compare_digest(key, expected):
            raise HTTPException(
                status_code=401,
                detail={"code": "CRON_KEY_INVALID", "message": "X-Cron-Key header is missing or wrong"},
            )

    @api.post("/v2/calendar/sync")
    def sync_calendar(
        days: int = Query(default=7, ge=1, le=31),
        x_cron_key: str | None = Header(default=None),
    ):
        _authorize_cron(x_cron_key)
        user_id = _configured_user_id()
        workspace = SupabaseWorkspaceRepository(cloud.service_client).get_active(user_id)
        if workspace is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "WORKSPACE_NOT_FOUND", "message": "No active Planner OS workspace"},
            )
        timezone = workspace.timezone
        context = PlannerContext(
            user_id=user_id,
            workspace_id=workspace.id,
            operation_id=uuid4(),
            workbook_path=Path("calendar-sync.xlsx"),
            timezone=timezone,
            execution_target="google_calendar",
            source_revision=workspace.revision,
        )
        try:
            client = cloud.google_client_factory()(context)
        except GoogleConnectionRequiredError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "GOOGLE_NOT_CONNECTED", "message": str(error)},
            ) from error

        tasks = TaskService(PlannerCoreRepository(cloud.service_client, user_id, workspace.id), timezone)
        result = tasks.sync_calendar(client, days)
        return _envelope(True, result["message"], result["data"])

    @api.post("/v2/calendar/import-apple")
    def import_apple_calendar(
        days: int = Query(default=30, ge=1, le=90),
        x_cron_key: str | None = Header(default=None),
        x_app_key: str | None = Header(default=None),
    ):
        # Runnable by the cron and by hand from the app, so accept either key.
        pwa_key = os.environ.get("PWA_ACCESS_KEY", "")
        cron_ok = x_cron_key and os.environ.get("CRON_SECRET", "") and secrets.compare_digest(
            x_cron_key, os.environ["CRON_SECRET"]
        )
        app_ok = x_app_key and pwa_key and secrets.compare_digest(x_app_key, pwa_key)
        if not (cron_ok or app_ok):
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "X-Cron-Key or X-App-Key required"},
            )

        ics_url = os.environ.get("APPLE_ICS_URL", "")
        if not ics_url:
            raise HTTPException(
                status_code=503,
                detail={"code": "APPLE_ICS_NOT_CONFIGURED",
                        "message": "Set APPLE_ICS_URL to your published iCloud calendar link"},
            )

        user_id = _configured_user_id()
        workspace = SupabaseWorkspaceRepository(cloud.service_client).get_active(user_id)
        if workspace is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "WORKSPACE_NOT_FOUND", "message": "No active Planner OS workspace"},
            )

        # webcal:// is just https for fetching; normalise it.
        url = ics_url.strip()
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]

        import urllib.request
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                ics_text = resp.read().decode("utf-8", errors="replace")
        except Exception as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "APPLE_ICS_FETCH_FAILED", "message": str(error)},
            ) from error

        repository = PlannerCoreRepository(cloud.service_client, user_id, workspace.id)
        tasks = TaskService(repository, workspace.timezone)
        result = tasks.import_ics(ics_text, window_days=days)
        return _envelope(True, result["message"], result["data"])
