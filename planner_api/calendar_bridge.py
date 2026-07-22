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


def _blocks_for_day(items: list[dict[str, Any]], on_date, timezone: str) -> list[ScheduledBlock]:
    """Map a day's timed tasks to calendar blocks; untimed tasks are skipped."""
    tz = ZoneInfo(timezone)
    blocks: list[ScheduledBlock] = []
    for item in items:
        start_time = item.get("start_time")
        if not start_time:
            continue
        hour, minute = (int(part) for part in str(start_time).split(":")[:2])
        start = datetime(on_date.year, on_date.month, on_date.day, hour, minute, tzinfo=tz)
        duration = item.get("estimated_minutes") or 30
        task_id = str(item["id"])
        blocks.append(
            ScheduledBlock(
                title=item["title"],
                start=start,
                end=start + timedelta(minutes=duration),
                category="task",
                source="postgres",
                metadata={"planner_block_id": task_id, "source_task_id": task_id},
            )
        )
    return blocks


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
        today = datetime.now(ZoneInfo(timezone)).date()
        totals = {"created": 0, "updated": 0, "deleted": 0, "unchanged": 0}
        errors: list[str] = []
        for offset in range(days):
            on_date = today + timedelta(days=offset)
            items = tasks.day_view(on_date.isoformat())["data"]["items"]
            plan = DailyPlan(date=on_date, blocks=_blocks_for_day(items, on_date, timezone), conflicts=[])
            result = client.sync_plan(plan, start=on_date, end=on_date + timedelta(days=1))
            totals["created"] += result.created
            totals["updated"] += result.updated
            totals["deleted"] += result.deleted
            totals["unchanged"] += result.unchanged
            errors.extend(result.errors)

        message = (
            f"{totals['created']} created, {totals['updated']} updated, "
            f"{totals['deleted']} removed over {days} day(s)"
        )
        return _envelope(True, message, {**totals, "errors": errors, "days": days})
