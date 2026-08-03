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


class DayTaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    scheduled_date: str | None = None
    start_time: str | None = None
    estimated_minutes: int | None = Field(default=None, gt=0, le=24 * 60)
    done: bool | None = None
    notes: str | None = None

class BatchDeleteRequest(BaseModel):
    task_ids: list[str]


class DayTaskPatch(BaseModel):
    done: bool | None = None
    start_time: str | None = None
    scheduled_date: str | None = None
    estimated_minutes: int | None = Field(default=None, gt=0, le=24 * 60)
    title: str | None = None


class MonthlyGoalCreate(BaseModel):
    project_id: str
    month: str
    description: str = Field(min_length=1)


class MonthlyGoalPatch(BaseModel):
    description: str

class ProjectQnaCreate(BaseModel):
    question: str = Field(min_length=1)
    answer: str | None = None
    status: str = "Drafting"
    notes: str | None = None

class ProjectQnaPatch(BaseModel):
    question: str | None = None
    answer: str | None = None
    status: str | None = None
    notes: str | None = None


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

    @api.get("/v2/week")
    def get_week(
        on_date: str | None = Query(default=None, alias="date"),
        x_app_key: str | None = Header(default=None),
    ):
        _authorize(x_app_key)
        core = _core()
        # core.tasks.week_view returns weekly tasks
        task_data = core.tasks.week_view(on_date)["data"]
        week_start_iso = task_data["week_start"]
        
        # core.goals.week_view returns goals for that week
        from datetime import date
        week_start_date = date.fromisoformat(week_start_iso)
        goal_data = core.goals.week_view(week_start_date)
        
        return _envelope(True, "Week view", {
            **task_data,
            "monthly_goals": goal_data["monthly_goals"],
            "weekly_goals": goal_data["weekly_goals"],
            "timezone": core.timezone
        })

    @api.post("/v2/goals/monthly", status_code=201)
    def create_monthly_goal(body: MonthlyGoalCreate, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.goals.add_monthly_goal(body.project_id, body.month, body.description)
        except (PlannerCoreError, ValueError) as error:
            raise HTTPException(
                status_code=400, detail={"code": "GOAL_CREATE_INVALID", "message": str(error)}
            ) from error
        return _envelope(True, result["message"], result["data"])

    @api.patch("/v2/goals/monthly/{goal_id}")
    def patch_monthly_goal(goal_id: str, body: MonthlyGoalPatch, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.goals.update_monthly_goal(goal_id, body.description)
        except (PlannerCoreError, ValueError) as error:
            raise HTTPException(
                status_code=400, detail={"code": "GOAL_UPDATE_INVALID", "message": str(error)}
            ) from error
        return _envelope(True, result["message"], result["data"])

    @api.delete("/v2/goals/monthly/{goal_id}")
    def delete_monthly_goal(goal_id: str, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.goals.delete_monthly_goal(goal_id)
        except (PlannerCoreError, ValueError) as error:
            raise HTTPException(
                status_code=400, detail={"code": "GOAL_DELETE_INVALID", "message": str(error)}
            ) from error
        return _envelope(True, result["message"], result.get("data"))

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

    @api.delete("/v2/day/tasks/{task_id}")
    def delete_day_task(task_id: str, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.tasks.delete_task(task_id)
        except (PlannerCoreError, ValueError) as error:
            raise HTTPException(
                status_code=404, detail={"code": "TASK_NOT_FOUND", "message": str(error)}
            ) from error
        return _envelope(True, result["message"], result["data"])

    @api.post("/v2/day/tasks/batch-delete")
    def delete_tasks_batch_endpoint(req: BatchDeleteRequest, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.tasks.delete_tasks_batch(req.task_ids)
        except (PlannerCoreError, ValueError) as error:
            raise HTTPException(
                status_code=400, detail={"code": "BATCH_DELETE_FAILED", "message": str(error)}
            ) from error
        return _envelope(True, result["message"], result["data"])

    @api.get("/v2/projects/{project_id}/{table_name}")
    def get_project_table(project_id: str, table_name: str, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        allowed_tables = {"germany_tests", "colleges", "applications", "professors", "research_papers", "project_qna"}
        if table_name not in allowed_tables:
            raise HTTPException(status_code=400, detail=f"Invalid table: {table_name}")
        try:
            rows = core.repository.list_rows(table_name, {"project_id": project_id})
            return _envelope(True, f"Fetched {table_name}", {table_name: rows})
        except PlannerCoreError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @api.post("/v2/projects/{project_id}/project_qna")
    def create_project_qna(project_id: str, body: ProjectQnaCreate, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.projects.add_project_qna(project_id, body.question, body.answer, body.status, body.notes)
            return _envelope(True, result["message"], result["data"])
        except PlannerCoreError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @api.patch("/v2/project_qna/{qna_id}")
    def patch_project_qna(qna_id: str, body: ProjectQnaPatch, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            updates = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
            result = core.projects.update_project_qna(qna_id, updates)
            return _envelope(True, result["message"], result["data"])
        except PlannerCoreError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @api.delete("/v2/project_qna/{qna_id}")
    def delete_project_qna(qna_id: str, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.projects.delete_project_qna(qna_id)
            return _envelope(True, result["message"], result["data"])
        except PlannerCoreError as e:
            raise HTTPException(status_code=400, detail=str(e))

    api.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="day-planner")
