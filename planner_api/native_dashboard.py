"""Lazy mobile dashboard reads and bounded milestone edits on a separate pool."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from planner_api.v2 import PlannerCoreBundle, _configured_user_id, build_core
from planner_core.repository import PlannerCoreError, PlannerCoreRepository
from planner_core.services import CLOSED_TASK_STATUSES
from planner_api.work_log import attach_work_progress

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="planner-dashboard")
Section = Literal["overview", "week", "projects", "tasks", "milestones", "goals", "weekly_goals", "qna", "widgets", "files",
                  "topics", "subjects", "revisions", "problems", "study_logs", "books", "habits", "documents", "tests", "colleges",
                  "applications", "professors", "papers", "finance_summary", "finance_plan",
                  "finance_transactions", "finance_goals"]
TABLES = {
    "projects": "projects", "tasks": "planner_tasks", "milestones": "milestones",
    "goals": "monthly_goals", "weekly_goals": "weekly_goals", "qna": "project_qna", "widgets": "project_widgets", "files": "project_files",
    "topics": "study_topics", "study_logs": "study_logs", "books": "books",
    "subjects": "study_subjects", "revisions": "study_revisions", "problems": "study_problems",
    "habits": "habits", "documents": "germany_documents", "tests": "germany_tests",
    "colleges": "colleges", "applications": "applications", "professors": "professors",
    "papers": "research_papers", "finance_transactions": "finance_logs",
}


class NativeMilestonePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=300)
    status: Literal["not_started", "in_progress", "blocked", "done"] | None = None
    start_date: date | None = None
    target_date: date | None = None
    notes: str | None = Field(default=None, max_length=20000)


class DashboardReads(PlannerCoreRepository):
    """Unavailable optional panels are explicit; critical reads never become zero."""
    def __init__(self, repository: PlannerCoreRepository):
        super().__init__(repository.gateway, repository.user_id, repository.workspace_id)
        self.warnings: list[str] = []

    def list_rows(self, table, *args, **kwargs):
        kwargs["strict"] = True
        try:
            return super().list_rows(table, *args, **kwargs)
        except Exception as error:
            missing = getattr(error, "status_code", None) == 404
            if table in {"project_files", "monthly_goals"}:
                self.warnings.append(f"{table.replace('_', ' ').capitalize()} are not set up in this workspace." if missing else f"{table.replace('_', ' ').capitalize()} are temporarily unavailable.")
                return []
            if missing:
                raise HTTPException(409, detail={"message": "This tracker is not set up in your current workspace yet."}) from error
            raise


def _milestone_details(core: PlannerCoreBundle, rows: list[dict[str, Any]]) -> None:
    """Reuse web health semantics; never replace a milestone's editable status."""
    if not rows:
        return
    progress = core.metrics._milestone_progress()
    project_ids = sorted({str(row["project_id"]) for row in rows if row.get("project_id")})
    projects = core.repository.list_rows("projects", {"id": project_ids}, columns="id,name") if project_ids else []
    names = {str(project["id"]): project.get("name") for project in projects}
    today = datetime.now(ZoneInfo(core.timezone)).date()
    health = {item["milestone_id"]: item for item in core.metrics._milestone_health(rows, projects, progress, today)}
    for row in rows:
        counts = progress.get(str(row["id"]), {})
        done, total = int(counts.get("done") or 0), int(counts.get("total") or 0)
        rating = health.get(str(row["id"]))
        row.update(done_tasks=done, total_tasks=total, open_tasks=max(0, total-done),
                   completion_pct=round(done*100/total, 1) if total else 0,
                   project_name=names.get(str(row.get("project_id")), "General"),
                   health=rating,
                   health_status=rating["status"] if rating else "complete" if row.get("status")=="done" else "no_tasks")


def _task_details(core: PlannerCoreBundle, rows: list[dict[str, Any]]) -> None:
    """Task editor DTOs include notes, exact split budgets, and scoped work totals."""
    slots = core.tasks._slot_context(rows)
    for row in rows:
        row.update(done=row.get("status") in CLOSED_TASK_STATUSES, is_habit=False, **slots.get(str(row["id"]), {}))
    attach_work_progress({"items": rows}, core.repository)
    for row in rows:
        if "planned_seconds" in row:
            row["remaining_seconds"] = max(0, row["planned_seconds"]-row.get("worked_seconds", 0))


def register_native_dashboard_routes(api: FastAPI, cloud: Any, authorize: Any) -> None:
    def read(section: str, project_id: UUID | None, offset: int, row_id: UUID | None, on_date: date | None, milestone_id: UUID | None, include_parts: bool):
        original = build_core(cloud.service_client, _configured_user_id())
        repository = DashboardReads(original.repository)
        core = PlannerCoreBundle(repository, original.timezone)
        if milestone_id is not None:
            if section != "tasks":
                raise HTTPException(400, detail={"message": "Milestone filtering is available for tasks only."})
            milestone = repository.get_row("milestones", str(milestone_id))
            if milestone is None or project_id is not None and str(milestone.get("project_id")) != str(project_id):
                raise HTTPException(404, detail={"message": "This milestone is no longer available."})
        if row_id is not None:
            if section not in TABLES:
                raise HTTPException(400, detail={"message": "This section has no record details."})
            row = repository.get_row(TABLES[section], str(row_id))
            if row is None or project_id is not None and str(row.get("project_id")) != str(project_id):
                raise HTTPException(404, detail={"message": "This record is no longer available."})
            row = dict(row)
            if milestone_id is not None and str(row.get("milestone_id")) != str(milestone_id):
                raise HTTPException(404, detail={"message": "This task is not in the selected milestone."})
            if section == "milestones":
                _milestone_details(core, [row])
            elif section == "tasks":
                _task_details(core, [row])
            if section == "widgets" and row.get("file_id"):
                file = repository.get_row("project_files", str(row["file_id"]))
                if file and str(file.get("project_id")) == str(row.get("project_id")):
                    row["file_link"] = file.get("drive_web_view_link")
            data = {"record": row}
        elif section == "overview":
            data = {"snapshot": core.metrics.snapshot()}
        elif section == "week":
            data = core.tasks.week_view(on_date.isoformat() if on_date else None)["data"]
        elif section == "finance_summary":
            data = core.finance.monthly_summary(on_date.isoformat() if on_date else None)["data"]
        elif section == "finance_plan":
            data = core.finance.plan_overview()["data"]
        elif section == "finance_goals":
            data = core.finance.goal_progress()["data"]
        elif section == "projects":
            counts = core.metrics._task_counts(datetime.now(ZoneInfo(core.timezone)).date())
            rows = [dict(row) for row in repository.list_rows("projects")]
            for row in rows:
                count = counts.get(str(row["id"]), {})
                done, total = count.get("done", 0), count.get("total", 0)
                row.update(done_tasks=done, total_tasks=total, open_tasks=count.get("open", 0),
                           completion_pct=round(done*100/total, 1) if total else 0)
            data = {"rows": rows, "next_offset": None}
        else:
            filters = {"project_id": str(project_id)} if project_id else {}
            if milestone_id is not None:
                filters["milestone_id"] = str(milestone_id)
            if section == "tasks":
                query = ("" if include_parts else "parent_task_id=is.null&") + "order=due_date.asc.nullslast,id.asc"
                columns = "id,title,status,priority,due_date,scheduled_date,start_time,estimated_minutes,project_id,milestone_id"
                if milestone_id is not None:
                    columns += ",notes,parent_task_id,starred,recurrence_key,depends_on,completed_at,created_at,updated_at"
            elif section == "finance_transactions":
                query, columns = "order=date.desc,id.desc", "*"
            else:
                query, columns = "order=id.asc", "*"
            rows = [dict(row) for row in repository.list_rows(TABLES[section], filters, columns=columns,
                                         query_string=f"{query}&limit=100&offset={offset}")]
            data = {"rows": rows, "next_offset": offset + 100 if len(rows) == 100 else None}
            if section == "milestones":
                _milestone_details(core, rows)
            if section == "tasks" and milestone_id is not None:
                _task_details(core, rows)
                data["milestone_id"] = str(milestone_id)
                data["includes_parts"] = include_parts
            if section == "habits":
                summary = core.metrics._completion_summary(datetime.now(ZoneInfo(core.timezone)).date())
                for row in rows:
                    row["streak_days"] = summary["streaks"].get(str(row.get("recurrence_key")), 0)
        return {"success": True, "message": "Dashboard", "errors": [],
                "data": {**data, "timezone": core.timezone, "warnings": repository.warnings}}

    @api.get("/v2/native/dashboard")
    async def dashboard(section: Section = "overview", project_id: UUID | None = None,
                        offset: int = Query(default=0, ge=0, le=100000), row_id: UUID | None = None,
                        on_date: date | None = None, milestone_id: UUID | None = None,
                        include_parts: bool = False,
                        x_app_key: str | None = Header(default=None)):
        authorize(x_app_key)
        try:
            return await asyncio.get_running_loop().run_in_executor(_POOL, read, section, project_id, offset, row_id, on_date, milestone_id, include_parts)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(503, detail={"message": "This dashboard section could not refresh. Your day remains available; retry this section."}) from error


    def patch_milestone(milestone_id: UUID, updates: dict[str, Any]):
        original = build_core(cloud.service_client, _configured_user_id())
        repository = DashboardReads(original.repository)
        core = PlannerCoreBundle(repository, original.timezone)
        if repository.get_row("milestones", str(milestone_id)) is None:
            raise HTTPException(404, detail={"message": "This milestone is no longer available."})
        if not updates:
            raise HTTPException(400, detail={"message": "Choose a milestone field to change."})
        if "name" in updates:
            if not updates["name"] or not updates["name"].strip():
                raise HTTPException(400, detail={"message": "Milestone name is required."})
            updates["name"] = updates["name"].strip()
        if "status" in updates and updates["status"] is None:
            raise HTTPException(400, detail={"message": "Milestone status is required."})
        try:
            result = core.projects.update_milestone(str(milestone_id), updates)
        except (PlannerCoreError, ValueError) as error:
            raise HTTPException(400, detail={"message": str(error)}) from error
        # Keep writes small and independent of optional health/progress reads.
        # The detail page reconciles its health via the scoped read endpoint.
        return result

    @api.patch("/v2/native/milestones/{milestone_id}")
    async def update_native_milestone(milestone_id: UUID, body: NativeMilestonePatch,
                                      x_app_key: str | None = Header(default=None)):
        authorize(x_app_key)
        try:
            return await asyncio.get_running_loop().run_in_executor(
                _POOL, patch_milestone, milestone_id, body.model_dump(mode="json", exclude_unset=True)
            )
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(503, detail={"message": "This milestone could not be saved. Your other tasks are unchanged; retry this milestone."}) from error
