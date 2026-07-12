"""Deterministic structured goal breakdown previews and apply."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from planner_engine.writer import Writer


@dataclass(frozen=True)
class GoalPlanningRequest:
    title: str
    target_date: date
    start_date: date
    category: str | None = None
    current_level: str | None = None
    target_level: str | None = None
    weekly_capacity_minutes: int = 300
    allowed_days: list[str] = field(default_factory=list)
    preferred_dayparts: list[str] = field(default_factory=list)
    fixed_daily_minutes: int = 45
    supporting_activities: list[str] = field(default_factory=list)
    hard_constraints: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass(frozen=True)
class GoalPlanPreview:
    preview_id: str
    operation: str
    normalized_goal: dict
    monthly_milestones: list[dict]
    weekly_outcomes: list[dict]
    dated_daily_tasks: list[dict]
    feasibility_report: dict
    conflicts: list[str]
    assumptions: list[str]
    workbook_changes: list[dict]
    active_execution_target_changes: list[dict]
    source_revision: str
    expires_at: str
    requires_confirmation: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class GoalBreakdownService:
    def __init__(self, workbook_path: str | Path, writer: Writer, preview_dir: str | Path) -> None:
        self.workbook_path = Path(workbook_path)
        self.writer = writer
        self.preview_dir = Path(preview_dir)

    def preview_goal_plan(self, request: GoalPlanningRequest) -> GoalPlanPreview:
        days = self._allowed_dates(request)
        capacity_days = max(1, len(days))
        minutes_per_day = max(15, min(request.fixed_daily_minutes, max(15, request.weekly_capacity_minutes // 5)))
        tasks = [
            {
                "date": day.isoformat(),
                "title": f"{request.title} - focus block",
                "estimated_minutes": minutes_per_day,
                "preferred_daypart": (request.preferred_dayparts or [None])[0],
                "category": request.category,
                "notes": "Planner OS generated goal plan",
            }
            for day in days
        ]
        weeks: dict[str, list[dict]] = {}
        for task in tasks:
            day = date.fromisoformat(task["date"])
            start = day - timedelta(days=day.weekday())
            weeks.setdefault(start.isoformat(), []).append(task)
        weekly = [
            {
                "week_start": start,
                "outcome": f"Advance {request.title}",
                "planned_minutes": sum(item["estimated_minutes"] for item in items),
                "task_count": len(items),
            }
            for start, items in sorted(weeks.items())
        ]
        required = sum(item["estimated_minutes"] for item in tasks)
        available = max(0, len(weekly) * request.weekly_capacity_minutes)
        status = "ok" if required <= available else "spillover"
        preview = GoalPlanPreview(
            preview_id=str(uuid4()),
            operation="apply_goal_plan",
            normalized_goal={
                "title": request.title.strip(),
                "category": request.category,
                "target_date": request.target_date.isoformat(),
                "current_level": request.current_level,
                "target_level": request.target_level,
            },
            monthly_milestones=[{"month": request.start_date.strftime("%b %Y"), "title": request.title, "target_date": request.target_date.isoformat()}],
            weekly_outcomes=weekly,
            dated_daily_tasks=tasks,
            feasibility_report={"status": status, "required_minutes": required, "available_minutes": available},
            conflicts=[] if status == "ok" else ["Goal exceeds provided weekly capacity"],
            assumptions=["Deterministic even distribution across allowed days", "No external calendar publication by default"],
            workbook_changes=[{"type": "monthly_goal"}, {"type": "dated_tasks", "count": len(tasks)}],
            active_execution_target_changes=[],
            source_revision=self._revision(),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        )
        self._save(preview)
        return preview

    def apply_goal_plan(self, preview_id: str) -> dict:
        preview = self._load(preview_id)
        if preview.source_revision != self._revision():
            raise ValueError("Goal preview is stale because workbook changed")
        month = date.fromisoformat(preview.normalized_goal["target_date"]).strftime("%b %Y")
        goal_result = self.writer.add_monthly_goal(
            month,
            preview.normalized_goal["title"],
            category=preview.normalized_goal.get("category") or "goal",
            priority="Medium",
            target_week="",
            notes="Planner OS generated goal plan",
        )
        if not goal_result.success:
            return {"success": False, "errors": list(goal_result.errors)}
        dated_result = self.writer.add_dated_tasks(preview.dated_daily_tasks)
        self._mark_applied(preview_id)
        return {
            "success": dated_result.success,
            "monthly_goal_backup": str(goal_result.backup_path) if goal_result.backup_path else None,
            "dated_tasks_backup": str(dated_result.backup_path) if dated_result.backup_path else None,
            "errors": list(dated_result.errors),
            "calendar_published": False,
        }

    def _allowed_dates(self, request: GoalPlanningRequest) -> list[date]:
        allowed = {item.casefold() for item in request.allowed_days}
        cursor = request.start_date
        days = []
        while cursor <= request.target_date:
            if not allowed or cursor.strftime("%A").casefold() in allowed:
                days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def _revision(self) -> str:
        stat = self.workbook_path.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"

    def _save(self, preview: GoalPlanPreview) -> None:
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        (self.preview_dir / f"{preview.preview_id}.json").write_text(json.dumps(preview.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _load(self, preview_id: str) -> GoalPlanPreview:
        path = self.preview_dir / f"{preview_id}.json"
        if not path.exists():
            raise ValueError("Unknown goal preview")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("applied_at"):
            raise ValueError("Goal preview was already applied")
        if data["operation"] != "apply_goal_plan":
            raise ValueError("Goal preview operation does not match")
        if datetime.fromisoformat(data["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("Goal preview expired")
        return GoalPlanPreview(**{key: data[key] for key in GoalPlanPreview.__dataclass_fields__ if key in data})

    def _mark_applied(self, preview_id: str) -> None:
        path = self.preview_dir / f"{preview_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["applied_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
