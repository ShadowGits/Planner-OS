"""Preview/apply command services for large Planner OS planning operations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from planner_engine.current_time import CurrentTimePlanner
from planner_engine.config import DEFAULT_PLANNING_PREVIEW_DIR
from planner_engine.date_utils import workbook_week_range
from planner_engine.dated_task_scheduler import DatedTaskScheduler
from planner_engine.models import BoundedSessionRequest, DailyPlan
from planner_engine.monthly_planner import (
    DailyTaskProposal,
    MonthlyGoalBreakdown,
    MonthlyPlanPreview,
    MonthlyPlanner,
    MonthlyPlanningRequest,
    WeeklyMilestone,
)
from planner_engine.planner import PlannerEngine
from planner_engine.rules import RulesEngine
from planner_engine.writer import Writer


@dataclass(frozen=True)
class WeekPlanningRequest:
    month: str
    week_number: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    overwrite_existing_plan: bool = False
    preview_only: bool = True
    current_datetime: datetime | None = None


@dataclass(frozen=True)
class DayReplanRequest:
    month: str
    target_date: date | None = None
    current_datetime: datetime | None = None
    preview_only: bool = True
    bounded_sessions: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class DayReplanPreview:
    month: str
    date: date
    blocks: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    proposed_excel_changes: list[dict[str, Any]]
    proposed_calendar_range: dict[str, str]
    warnings: list[str]
    preview_id: str = field(default_factory=lambda: str(uuid4()))
    preview_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["date"] = self.date.isoformat()
        return data


@dataclass(frozen=True)
class PlanApplyResult:
    success: bool
    message: str
    backup_path: str | None
    applied_changes: int
    warnings: list[str]
    errors: list[str]
    calendar_synced: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlanningCommandService:
    """Enforce preview-before-apply around deterministic planning engines."""

    def __init__(
        self,
        engine: PlannerEngine,
        rules_engine: RulesEngine,
        writer: Writer | None = None,
        preview_dir: str | Path = DEFAULT_PLANNING_PREVIEW_DIR,
    ) -> None:
        self.engine = engine
        self.rules_engine = rules_engine
        self.writer = writer or Writer(engine)
        self.monthly_planner = MonthlyPlanner(engine, rules_engine)
        self._previews: dict[str, MonthlyPlanPreview | DayReplanPreview] = {}
        self._preview_revisions: dict[str, str] = {}
        self.preview_dir = Path(preview_dir)

    def preview_month_plan(self, request: MonthlyPlanningRequest) -> MonthlyPlanPreview:
        preview = self.monthly_planner.preview(request)
        self._remember(preview)
        return preview

    def apply_month_plan(
        self,
        preview: str | dict[str, Any] | MonthlyPlanPreview,
    ) -> PlanApplyResult:
        return self._apply(self._resolve(preview, MonthlyPlanPreview))

    def preview_week_plan(self, request: WeekPlanningRequest) -> MonthlyPlanPreview:
        month_plan = self.engine.get_month_plan(request.month)
        if request.week_number is None and (request.start_date is None or request.end_date is None):
            raise ValueError("Specify week_number or an explicit start_date/end_date range")
        start, end = (
            workbook_week_range(month_plan, request.week_number)
            if request.week_number is not None
            else (request.start_date, request.end_date)
        )
        assert start is not None and end is not None
        preview = self.monthly_planner.preview(
            MonthlyPlanningRequest(
                month=request.month,
                start_date=start,
                end_date=end,
                planning_mode="full_month",
                overwrite_existing_plan=request.overwrite_existing_plan,
                current_datetime=request.current_datetime,
            )
        )
        self._remember(preview)
        return preview

    def apply_week_plan(
        self,
        preview: str | dict[str, Any] | MonthlyPlanPreview,
    ) -> PlanApplyResult:
        return self._apply(self._resolve(preview, MonthlyPlanPreview))

    def preview_day_replan(self, request: DayReplanRequest) -> DayReplanPreview:
        timezone = ZoneInfo(self.rules_engine.rules.profile.timezone)
        now = request.current_datetime or datetime.now(timezone)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone)
        else:
            now = now.astimezone(timezone)
        target = request.target_date or now.date()
        if target != now.date():
            raise ValueError("Current-time day replan supports today only")
        plan = CurrentTimePlanner(self.rules_engine).replan_today_from_now(
            self.engine.get_month_plan(request.month),
            now,
            self._bounded_sessions(request.bounded_sessions or [], now),
        )
        existing_dated = self.engine.list_dated_tasks(request.month, target)
        dated_blocks, dated_conflicts = DatedTaskScheduler(
            self.rules_engine
        ).schedule_date(target, existing_dated, plan.blocks, now)
        dated_categories = {
            block.category.casefold()
            for block in dated_blocks
            if block.category
        }
        base_blocks = [
            block
            for block in plan.blocks
            if block.is_fixed
            or block.category.casefold() not in dated_categories
        ]
        plan = DailyPlan(
            date=target,
            blocks=sorted([*base_blocks, *dated_blocks], key=lambda item: item.start),
            conflicts=[*plan.conflicts, *dated_conflicts],
        )
        proposed_changes = [
            {
                "operation": "add_dated_task",
                "date": target.isoformat(),
                "title": block.title,
                "estimated_minutes": max(
                    1, int((block.end - block.start).total_seconds() // 60)
                ),
                "start_time": block.start.strftime("%H:%M"),
                "end_time": block.end.strftime("%H:%M"),
                "hard_time": True,
                "category": block.category,
                "notes": "Planner OS generated day replan",
            }
            for block in plan.blocks
            if not block.is_fixed
            and block.source != "workbook_dated_task"
            and block.end > now
        ]
        warnings = ["Preview only: no workbook changes made", "Calendar not synced"]
        if request.bounded_sessions:
            warnings.append("Bounded-session request retained for explicit scheduling")
        preview = DayReplanPreview(
            month=request.month,
            date=target,
            blocks=[self._block_dict(block) for block in plan.blocks],
            conflicts=[
                {"item": item.item, "reason": item.reason, "severity": item.severity}
                for item in plan.conflicts
            ],
            proposed_excel_changes=proposed_changes,
            proposed_calendar_range={"start_date": target.isoformat(), "end_date": target.isoformat()},
            warnings=warnings,
        )
        self._remember(preview)
        return preview

    def apply_day_replan(
        self,
        preview: str | dict[str, Any] | DayReplanPreview,
    ) -> PlanApplyResult:
        resolved = self._resolve(preview, DayReplanPreview)
        tasks = [
            change
            for change in resolved.proposed_excel_changes
            if change.get("operation") == "add_dated_task"
        ]
        if tasks:
            result = self.writer.add_dated_tasks(
                tasks,
                overwrite_generated=True,
            )
            if not result.success:
                return PlanApplyResult(
                    False,
                    "Day replan apply failed",
                    str(result.backup_path) if result.backup_path else None,
                    0,
                    list(result.warnings),
                    list(result.errors),
                )
            return PlanApplyResult(
                True,
                (
                    f"Applied plan: workbook backup created at {result.backup_path}"
                    if result.backup_path
                    else "Applied day replan: no new workbook tasks"
                ),
                str(result.backup_path) if result.backup_path else None,
                int(result.metadata.get("written", 0)),
                [*result.warnings, "Calendar not synced"],
                [],
            )
        return PlanApplyResult(
            success=True,
            message="Applied day replan: no workbook changes were required",
            backup_path=None,
            applied_changes=0,
            warnings=[*resolved.warnings, "Calendar not synced"],
            errors=[],
        )

    def _apply(self, preview: MonthlyPlanPreview) -> PlanApplyResult:
        tasks = [
            change
            for change in preview.proposed_excel_changes
            if change.get("operation") == "add_dated_task"
        ]
        if not tasks:
            return PlanApplyResult(
                True,
                "Applied plan: no new workbook tasks",
                None,
                0,
                ["Calendar not synced"],
                [],
            )
        result = self.writer.add_dated_tasks(
            tasks,
            overwrite_generated=preview.overwrite_existing_plan,
            overwrite_start=(
                date.fromisoformat(preview.proposed_calendar_range["start_date"])
                if preview.overwrite_existing_plan
                else None
            ),
            overwrite_end=(
                date.fromisoformat(preview.proposed_calendar_range["end_date"])
                if preview.overwrite_existing_plan
                else None
            ),
        )
        if not result.success:
            return PlanApplyResult(False, "Plan apply failed", str(result.backup_path) if result.backup_path else None, 0, list(result.warnings), list(result.errors))
        written = int(result.metadata.get("written", 0))
        backup = str(result.backup_path) if result.backup_path else None
        message = f"Applied plan: workbook backup created at {backup}" if backup else "Applied plan: no new workbook tasks"
        return PlanApplyResult(True, message, backup, written, [*result.warnings, "Calendar not synced"], [])

    def _resolve(self, preview: str | Any, expected: type[Any]) -> Any:
        resolved = preview
        if isinstance(preview, str):
            resolved = self._previews.get(preview)
            cached_revision = self._preview_revisions.get(preview)
            if cached_revision and cached_revision != self._workbook_revision():
                raise ValueError("Planning preview is stale because workbook changed")
            if resolved is None:
                resolved = self._load_preview(preview)
        if isinstance(resolved, dict):
            resolved = self._preview_from_dict(resolved, expected)
        if not isinstance(resolved, expected):
            raise ValueError("Unknown or incompatible preview; preview again before apply")
        return resolved

    def _remember(self, preview: MonthlyPlanPreview | DayReplanPreview) -> None:
        self._previews[preview.preview_id] = preview
        revision = self._workbook_revision()
        self._preview_revisions[preview.preview_id] = revision
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        destination = self.preview_dir / f"{preview.preview_id}.json"
        payload = preview.to_dict()
        payload.setdefault("_preview_meta", {})
        payload["_preview_meta"].update(
            {
                "source_revision": revision,
                "operation_type": type(preview).__name__,
                "stored_at": datetime.now().isoformat(),
            }
        )
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.preview_dir,
                prefix=f".{preview.preview_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                temporary = Path(handle.name)
            temporary.replace(destination)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def _load_preview(self, preview_id: str) -> dict[str, Any] | None:
        path = self.preview_dir / f"{preview_id}.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        meta = raw.get("_preview_meta", {}) if isinstance(raw, dict) else {}
        if meta.get("source_revision") and meta["source_revision"] != self._workbook_revision():
            raise ValueError("Planning preview is stale because workbook changed")
        return raw if isinstance(raw, dict) else None

    def _preview_from_dict(self, data: dict[str, Any], expected: type[Any]) -> Any:
        if expected is DayReplanPreview:
            return DayReplanPreview(
                month=str(data["month"]),
                date=self._date(data["date"]),
                blocks=list(data.get("blocks", [])),
                conflicts=list(data.get("conflicts", [])),
                proposed_excel_changes=list(data.get("proposed_excel_changes", [])),
                proposed_calendar_range=dict(data.get("proposed_calendar_range", {})),
                warnings=list(data.get("warnings", [])),
                preview_id=str(data["preview_id"]),
                preview_only=bool(data.get("preview_only", True)),
            )
        if expected is MonthlyPlanPreview:
            milestones = [self._milestone(item) for item in data.get("weekly_milestones", [])]
            daily_tasks = [self._daily_task(item) for item in data.get("daily_tasks", [])]
            goals = []
            for item in data.get("goals_processed", []):
                goals.append(
                    MonthlyGoalBreakdown(
                        goal_name=str(item["goal_name"]),
                        category=item.get("category"),
                        priority=str(item["priority"]),
                        current_status=str(item["current_status"]),
                        target_week=item.get("target_week"),
                        estimated_total_units=int(item["estimated_total_units"]),
                        completed_units=int(item["completed_units"]),
                        remaining_units=int(item["remaining_units"]),
                        unit_label=item.get("unit_label"),
                        weekly_milestones=[
                            self._milestone(value)
                            for value in item.get("weekly_milestones", [])
                        ],
                        daily_tasks=[
                            self._daily_task(value)
                            for value in item.get("daily_tasks", [])
                        ],
                        feasibility_status=str(item["feasibility_status"]),
                        spillover_reason=item.get("spillover_reason"),
                        estimate_confidence=str(item.get("estimate_confidence", "low")),
                    )
                )
            return MonthlyPlanPreview(
                month=str(data["month"]),
                goals_processed=goals,
                weekly_milestones=milestones,
                daily_tasks=daily_tasks,
                feasibility_report=dict(data.get("feasibility_report", {})),
                warnings=list(data.get("warnings", [])),
                conflicts=list(data.get("conflicts", [])),
                proposed_excel_changes=list(data.get("proposed_excel_changes", [])),
                proposed_calendar_range=dict(data.get("proposed_calendar_range", {})),
                preview_id=str(data["preview_id"]),
                overwrite_existing_plan=bool(data.get("overwrite_existing_plan", False)),
                preview_only=bool(data.get("preview_only", True)),
            )
        return data

    def _milestone(self, data: dict[str, Any]) -> WeeklyMilestone:
        return WeeklyMilestone(
            **{
                **data,
                "week_number": int(data["week_number"]),
                "start_date": self._date(data["start_date"]),
                "end_date": self._date(data["end_date"]),
                "units_planned": int(data["units_planned"]),
                "estimated_minutes": int(data["estimated_minutes"]),
            }
        )

    def _daily_task(self, data: dict[str, Any]) -> DailyTaskProposal:
        return DailyTaskProposal(
            **{
                **data,
                "date": self._date(data["date"]),
                "week_number": int(data["week_number"]),
                "estimated_minutes": int(data["estimated_minutes"]),
            }
        )

    def _date(self, value: Any) -> date:
        return value if isinstance(value, date) else date.fromisoformat(str(value))

    def _workbook_revision(self) -> str:
        path = self.engine.store.planner_path
        stat = path.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"

    def _block_dict(self, block: Any) -> dict[str, Any]:
        return {
            "title": block.title,
            "start": block.start.isoformat(),
            "end": block.end.isoformat(),
            "category": block.category,
            "source": block.source,
            "is_fixed": block.is_fixed,
        }

    def _bounded_sessions(
        self,
        payloads: list[dict[str, Any]],
        now: datetime,
    ) -> list[BoundedSessionRequest]:
        requests: list[BoundedSessionRequest] = []
        for payload in payloads:
            start_hour = int(payload["start_hour"])
            end_hour = int(payload["end_hour"])
            start = now.replace(
                hour=start_hour,
                minute=int(payload.get("start_minute", 0)),
                second=0,
                microsecond=0,
            )
            end = now.replace(
                hour=end_hour,
                minute=int(payload.get("end_minute", 0)),
                second=0,
                microsecond=0,
            )
            requests.append(
                BoundedSessionRequest(
                    title=str(payload.get("title", "Bounded session")),
                    category=str(payload.get("category", "gym")),
                    requested_window_start=start,
                    requested_window_end=end,
                    session_count=int(payload.get("session_count", 1)),
                    session_duration_minutes=int(
                        payload.get("session_duration_minutes", 60)
                    ),
                    gap_minutes=int(payload.get("gap_minutes", 15)),
                    hard_window=bool(payload.get("hard_window", True)),
                    source="planner_command_router",
                )
            )
        return requests
