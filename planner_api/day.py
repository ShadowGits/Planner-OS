"""Day-planner PWA surface: JSON day feed plus the static app shell.

The PWA is a single-user companion (same trust model as the Telegram webhook):
requests carry X-App-Key matching PWA_ACCESS_KEY and act on the workspace of
MCP_USER_ID. Interactive UI logic lives in the static files under /app.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from planner_api.v2 import build_core, _configured_user_id
from planner_core.repository import PlannerCoreError

STATIC_DIR = Path(__file__).parent / "static" / "pwa"


class DayTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    date: str | None = None
    start_time: str | None = None
    estimated_minutes: int | None = Field(default=None, gt=0, le=24 * 60)
    notes: str | None = None


class DayTaskPatch(BaseModel):
    done: bool | None = None
    start_time: str | None = None
    scheduled_date: str | None = None
    estimated_minutes: int | None = Field(default=None, gt=0, le=24 * 60)
    title: str | None = None


def register_day_routes(api: FastAPI, cloud: Any) -> None:
    def _envelope(success: bool, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"success": success, "message": message, "data": data or {}, "errors": []}

    def _authorize(key: str | None) -> None:
        expected = os.environ.get("PWA_ACCESS_KEY", "")
        if not expected or not key or not secrets.compare_digest(key, expected):
            raise HTTPException(
                status_code=401,
                detail={"code": "APP_KEY_INVALID", "message": "X-App-Key header is missing or wrong"},
            )

    def _core():
        return build_core(cloud.service_client, _configured_user_id())

    @api.get("/v2/day")
    def get_day(
        on_date: str | None = Query(default=None, alias="date"),
        x_app_key: str | None = Header(default=None),
    ):
        _authorize(x_app_key)
        core = _core()
        data = core.tasks.day_view(on_date)["data"]
        return _envelope(True, "Day view", {**data, "timezone": core.timezone})

    @api.post("/v2/day/tasks", status_code=201)
    def add_day_task(body: DayTaskCreate, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.tasks.create_task(
                body.title,
                scheduled_date=body.date,
                start_time=body.start_time,
                estimated_minutes=body.estimated_minutes,
                notes=body.notes,
            )
        except (PlannerCoreError, ValueError) as error:
            raise HTTPException(
                status_code=400, detail={"code": "TASK_INVALID", "message": str(error)}
            ) from error
        return _envelope(True, result["message"], result["data"])

    @api.patch("/v2/day/tasks/{task_id}")
    def patch_day_task(task_id: str, body: DayTaskPatch, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            if body.done is True:
                result = core.tasks.complete_task(task_id, source="dashboard")
            elif body.done is False:
                result = core.tasks.reopen_task(task_id)
            else:
                result = None
            updates = {
                field: getattr(body, field)
                for field in ("start_time", "scheduled_date", "estimated_minutes", "title")
                if field in body.model_fields_set
            }
            if updates:
                result = core.tasks.update_task(task_id, updates)
            if result is None:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "PATCH_EMPTY", "message": "Nothing to change"},
                )
        except (PlannerCoreError, ValueError) as error:
            raise HTTPException(
                status_code=400, detail={"code": "TASK_UPDATE_INVALID", "message": str(error)}
            ) from error
        return _envelope(True, result["message"], result["data"])

    api.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="day-planner")
