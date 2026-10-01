"""Lazy, read-only mobile dashboard on a pool separate from Day requests."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Query

from planner_api.v2 import PlannerCoreBundle, _configured_user_id, build_core
from planner_core.repository import PlannerCoreRepository

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


def register_native_dashboard_routes(api: FastAPI, cloud: Any, authorize: Any) -> None:
    def read(section: str, project_id: UUID | None, offset: int, row_id: UUID | None, on_date: date | None):
        original = build_core(cloud.service_client, _configured_user_id())
        repository = DashboardReads(original.repository)
        core = PlannerCoreBundle(repository, original.timezone)
        if row_id is not None:
            if section not in TABLES:
                raise HTTPException(400, detail={"message": "This section has no record details."})
            row = repository.get_row(TABLES[section], str(row_id))
            if row is None or project_id is not None and str(row.get("project_id")) != str(project_id):
                raise HTTPException(404, detail={"message": "This record is no longer available."})
            row = dict(row)
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
            if section == "tasks":
                query = "parent_task_id=is.null&order=due_date.asc.nullslast,id.asc"
                columns = "id,title,status,priority,due_date,scheduled_date,start_time,estimated_minutes,project_id,milestone_id"
            else:
                query, columns = "order=id.asc", "*"
            rows = [dict(row) for row in repository.list_rows(TABLES[section], filters, columns=columns,
                                         query_string=f"{query}&limit=100&offset={offset}")]
            data = {"rows": rows, "next_offset": offset + 100 if len(rows) == 100 else None}
            if section == "milestones":
                progress = core.metrics._milestone_progress()
                for row in rows:
                    counts = progress.get(str(row["id"]), {})
                    row.update(done_tasks=counts.get("done", 0), total_tasks=counts.get("total", 0))
            if section == "habits":
                summary = core.metrics._completion_summary(datetime.now(ZoneInfo(core.timezone)).date())
                for row in rows:
                    row["streak_days"] = summary["streaks"].get(str(row.get("recurrence_key")), 0)
        return {"success": True, "message": "Dashboard", "errors": [],
                "data": {**data, "timezone": core.timezone, "warnings": repository.warnings}}

    @api.get("/v2/native/dashboard")
    async def dashboard(section: Section = "overview", project_id: UUID | None = None,
                        offset: int = Query(default=0, ge=0, le=100000), row_id: UUID | None = None,
                        on_date: date | None = None,
                        x_app_key: str | None = Header(default=None)):
        authorize(x_app_key)
        try:
            return await asyncio.get_running_loop().run_in_executor(_POOL, read, section, project_id, offset, row_id, on_date)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(503, detail={"message": "This dashboard section could not refresh. Your day remains available; retry this section."}) from error
