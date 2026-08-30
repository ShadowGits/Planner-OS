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
import datetime

def _normalize_spillover(date_str, time_str):
    if not time_str:
        return date_str, time_str
    try:
        parts = time_str.split(":")
        h = int(parts[0])
        if h >= 24:
            parts[0] = f"{h - 24:02d}"
            new_time = ":".join(parts)
            new_date = date_str
            if date_str:
                d = datetime.date.fromisoformat(date_str)
                new_date = (d + datetime.timedelta(days=1)).isoformat()
            return new_date, new_time
    except Exception:
        pass
    return date_str, time_str

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from planner_api.v2 import build_core, _configured_user_id
from planner_core.repository import PlannerCoreError
from planner_core.services import parse_habit_item_id

STATIC_DIR = Path(__file__).parent / "static" / "pwa"


class DayTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    date: str | None = None
    start_time: str | None = None
    estimated_minutes: int | None = Field(default=None, gt=0, le=24 * 60)
    notes: str | None = None
    parent_task_id: str | None = None
    project_id: str | None = None


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
    milestone_id: str | None = None


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

class ProjectWidgetCreate(BaseModel):
    widget_type: str = Field(min_length=1)
    title: str | None = None
    file_id: str | None = None
    config: dict[str, Any] | None = None

class ProjectWidgetPatch(BaseModel):
    title: str | None = None
    file_id: str | None = None
    config: dict[str, Any] | None = None
    order_index: int | None = None


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
            norm_date, norm_time = _normalize_spillover(body.date, body.start_time)
            result = core.tasks.create_task(
                body.title,
                scheduled_date=norm_date,
                start_time=norm_time,
                estimated_minutes=body.estimated_minutes,
                notes=body.notes,
                parent_task_id=body.parent_task_id,
                project_id=body.project_id,
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

        # A habit occurrence has no row, so the day view gives it a synthetic
        # id and it comes back here. Ticking writes a completion; moving or
        # retiming writes an override for that one day, leaving the rule and
        # every other day alone.
        occurrence = parse_habit_item_id(task_id)
        if occurrence is not None:
            habit_id, rule_day = occurrence
            try:
                result = None
                if body.done is True:
                    result = core.habits.complete_occurrence(habit_id, rule_day, source="dashboard")
                elif body.done is False:
                    result = core.habits.reopen_occurrence(habit_id, rule_day)
                moved = {
                    "moved_to": body.scheduled_date,
                    "start_time": body.start_time,
                    "estimated_minutes": body.estimated_minutes,
                }
                moved = {k: v for k, v in moved.items() if k.replace("moved_to", "scheduled_date") in body.model_fields_set}
                # The day view runs past midnight, so a small-hours slot arrives
                # as 24:30 meaning "half past midnight, still tonight". Tasks
                # already translate that into the next date; habits have to as
                # well, or the clock parser rejects hour 24.
                if moved.get("start_time"):
                    base = body.scheduled_date or rule_day.isoformat()
                    norm_date, norm_time = _normalize_spillover(base, moved["start_time"])
                    if norm_time != moved["start_time"]:
                        moved["start_time"] = norm_time
                        moved["moved_to"] = norm_date
                if moved:
                    result = core.habits.reschedule_occurrence(habit_id, rule_day, **moved)
                if result is None:
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "PATCH_EMPTY", "message": "Nothing to change"},
                    )
            except (PlannerCoreError, ValueError) as error:
                raise HTTPException(
                    status_code=400, detail={"code": "HABIT_UPDATE_INVALID", "message": str(error)}
                ) from error
            return _envelope(True, result["message"], result["data"])

        try:
            if body.done is True:
                result = core.tasks.complete_task(task_id, source="dashboard")
            elif body.done is False:
                result = core.tasks.reopen_task(task_id)
            else:
                result = None
            updates = {
                field: getattr(body, field)
                for field in ("start_time", "scheduled_date", "estimated_minutes", "title", "milestone_id")
                if field in body.model_fields_set
            }
            
            if "start_time" in updates and updates["start_time"]:
                try:
                    h = int(updates["start_time"].split(":")[0])
                    if h >= 24:
                        curr_date = updates.get("scheduled_date")
                        if not curr_date:
                            task = core.repository.get_row("planner_tasks", task_id)
                            curr_date = task.get("scheduled_date") if task else None
                        norm_date, norm_time = _normalize_spillover(curr_date, updates["start_time"])
                        updates["scheduled_date"] = norm_date
                        updates["start_time"] = norm_time
                except Exception:
                    pass
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

        # Deleting one day of a habit means skipping that day, not removing
        # the habit — you did not stop going to the gym.
        occurrence = parse_habit_item_id(task_id)
        if occurrence is not None:
            habit_id, rule_day = occurrence
            try:
                result = core.habits.skip_occurrence(habit_id, rule_day)
            except (PlannerCoreError, ValueError) as error:
                raise HTTPException(
                    status_code=404, detail={"code": "HABIT_NOT_FOUND", "message": str(error)}
                ) from error
            return _envelope(True, result["message"], result["data"])

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

    @api.get("/v2/projects/{project_id}/widgets")
    def get_project_widgets(project_id: str, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.projects.list_project_widgets(project_id)
            return result
        except PlannerCoreError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @api.post("/v2/projects/{project_id}/widgets")
    def create_project_widget(project_id: str, body: ProjectWidgetCreate, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.projects.add_project_widget(
                project_id, 
                body.widget_type, 
                body.title, 
                body.file_id, 
                body.config
            )
            return result
        except PlannerCoreError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @api.patch("/v2/widgets/{widget_id}")
    def patch_project_widget(widget_id: str, body: ProjectWidgetPatch, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            updates = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
            result = core.projects.update_project_widget(widget_id, updates)
            return result
        except PlannerCoreError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @api.delete("/v2/widgets/{widget_id}")
    def delete_project_widget(widget_id: str, x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = _core()
        try:
            result = core.projects.delete_project_widget(widget_id)
            return result
        except PlannerCoreError as e:
            raise HTTPException(status_code=400, detail=str(e))

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
    class RevalidatingStaticFiles(StaticFiles):
        """Serve the PWA with no-cache.

        Without a Cache-Control header a browser applies its own guess at how
        long a file stays fresh, and can keep serving an old app.js without
        ever asking the server. The service worker fetches through that same
        cache, so a deploy could not reach the phone at all.

        no-cache does not mean no caching: the copy is still stored and still
        reused, the browser just has to ask first. The reply is a 304 with an
        empty body whenever the file has not moved on.
        """

        def file_response(self, *args, **kwargs):
            response = super().file_response(*args, **kwargs)
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
            return response

    api.mount("/app", RevalidatingStaticFiles(directory=STATIC_DIR, html=True), name="day-planner")
