"""Monthly goal breakdown into deterministic weekly and daily proposals."""

from __future__ import annotations

import calendar
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

from planner_engine.capacity import CapacityEngine, CapacityRequest
from planner_engine.date_utils import workbook_week_range
from planner_engine.models import MonthPlan, MonthlyGoal, Priority, TaskStatus
from planner_engine.planner import PlannerEngine
from planner_engine.rules import RulesEngine


@dataclass(frozen=True)
class MonthlyPlanningRequest:
    month: str
    start_date: date | None = None
    end_date: date | None = None
    planning_mode: str = "remaining_month"
    include_existing_tasks: bool = True
    overwrite_existing_plan: bool = False
    preview_only: bool = True
    current_datetime: datetime | None = None


@dataclass(frozen=True)
class WeeklyMilestone:
    week_number: int
    start_date: date
    end_date: date
    goal_name: str
    milestone_title: str
    units_planned: int
    estimated_minutes: int
    priority: str
    category: str | None = None
    unit_label: str | None = None
    cadence: str | None = None
    preferred_daypart: str | None = None
    flexible: bool = True


@dataclass(frozen=True)
class DailyTaskProposal:
    date: date
    week_number: int
    task_title: str
    category: str
    estimated_minutes: int
    source_goal: str
    priority: str
    flexible: bool
    preferred_daypart: str | None = None


@dataclass(frozen=True)
class MonthlyGoalBreakdown:
    goal_name: str
    category: str | None
    priority: str
    current_status: str
    target_week: str | None
    estimated_total_units: int
    completed_units: int
    remaining_units: int
    unit_label: str | None
    weekly_milestones: list[WeeklyMilestone]
    daily_tasks: list[DailyTaskProposal]
    feasibility_status: str
    spillover_reason: str | None = None
    estimate_confidence: str = "low"


@dataclass(frozen=True)
class MonthlyPlanPreview:
    month: str
    goals_processed: list[MonthlyGoalBreakdown]
    weekly_milestones: list[WeeklyMilestone]
    daily_tasks: list[DailyTaskProposal]
    feasibility_report: dict[str, Any]
    warnings: list[str]
    conflicts: list[str]
    proposed_excel_changes: list[dict[str, Any]]
    proposed_calendar_range: dict[str, str]
    preview_id: str = field(default_factory=lambda: str(uuid4()))
    overwrite_existing_plan: bool = False
    preview_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


class MonthlyPlanner:
    """Build a read-only monthly proposal from workbook goals and rules."""

    def __init__(
        self,
        planner_engine: PlannerEngine,
        rules_engine: RulesEngine,
        capacity_engine: CapacityEngine | None = None,
    ) -> None:
        self.planner_engine = planner_engine
        self.rules_engine = rules_engine
        self.capacity_engine = capacity_engine or CapacityEngine(rules_engine)

    def preview(self, request: MonthlyPlanningRequest) -> MonthlyPlanPreview:
        """Generate a monthly plan preview without writing Excel or Calendar."""

        if request.planning_mode not in {"remaining_month", "full_month"}:
            raise ValueError("planning_mode must be remaining_month or full_month")
        month_plan = self.planner_engine.get_month_plan(request.month)
        start, end = self._date_range(request)
        week_ranges = self._week_ranges(start, end, month_plan)
        breakdowns: list[MonthlyGoalBreakdown] = []
        milestones: list[WeeklyMilestone] = []

        for goal in month_plan.monthly_goals:
            if goal.status == TaskStatus.DONE:
                continue
            goal_milestones, unit_info = self._milestones_for_goal(goal, week_ranges)
            milestones.extend(goal_milestones)
            breakdowns.append(
                MonthlyGoalBreakdown(
                    goal_name=goal.name,
                    category=goal.category,
                    priority=goal.priority.value,
                    current_status=goal.status.value,
                    target_week=goal.target_week,
                    estimated_total_units=unit_info[0],
                    completed_units=unit_info[1],
                    remaining_units=unit_info[2],
                    unit_label=unit_info[3],
                    weekly_milestones=goal_milestones,
                    daily_tasks=[],
                    feasibility_status="ok",
                    estimate_confidence=unit_info[4],
                )
            )

        from planner_engine.daily_distributor import DailyDistributor

        distribution = DailyDistributor(self.rules_engine).distribute(
            milestones,
            start_date=start,
            end_date=end,
            current_datetime=request.current_datetime,
            from_now=request.planning_mode == "remaining_month",
        )
        required_minutes = sum(task.estimated_minutes for task in distribution.tasks)
        capacity = self.capacity_engine.calculate(
            CapacityRequest(
                start_date=start,
                end_date=end,
                required_minutes=required_minutes,
                current_datetime=request.current_datetime,
                from_now=request.planning_mode == "remaining_month",
            )
        )
        tasks_by_goal: dict[str, list[DailyTaskProposal]] = {}
        for task in distribution.tasks:
            tasks_by_goal.setdefault(task.source_goal.casefold(), []).append(task)
        resolved_breakdowns: list[MonthlyGoalBreakdown] = []
        for item in breakdowns:
            item_tasks = tasks_by_goal.get(item.goal_name.casefold(), [])
            status = capacity.feasibility_status
            spillover = None
            if any(item.goal_name.casefold() in warning.casefold() for warning in distribution.warnings):
                status = "spillover"
                spillover = "Not all proposed sessions fit in the requested date range"
            resolved_breakdowns.append(
                replace(
                    item,
                    daily_tasks=item_tasks,
                    feasibility_status=status,
                    spillover_reason=spillover,
                )
            )

        existing = {
            (scheduled_date, task.name.casefold())
            for section in month_plan.week_sections
            for task in section.tasks
            for scheduled_date in task.scheduled_dates
        }
        proposed_changes = []
        for task in distribution.tasks:
            if request.include_existing_tasks and (
                task.date,
                task.task_title.casefold(),
            ) in existing:
                continue
            proposed_changes.append(
                {
                    "operation": "add_dated_task",
                    "date": task.date.isoformat(),
                    "title": task.task_title,
                    "estimated_minutes": task.estimated_minutes,
                    "preferred_daypart": task.preferred_daypart,
                    "category": task.category,
                    "status": "Not Started",
                    "notes": (
                        f"Planner OS generated plan; planned {task.date.isoformat()}; "
                        f"{task.estimated_minutes} min; "
                        f"source goal: {task.source_goal}"
                    ),
                }
            )

        warnings = ["Preview only: no workbook changes made", "Calendar not synced"]
        warnings.extend(distribution.warnings)
        if capacity.feasibility_status != "ok":
            warnings.extend(capacity.suggestions)
        return MonthlyPlanPreview(
            month=request.month,
            goals_processed=resolved_breakdowns,
            weekly_milestones=milestones,
            daily_tasks=distribution.tasks,
            feasibility_report=capacity.to_dict(),
            warnings=list(dict.fromkeys(warnings)),
            conflicts=capacity.conflicts,
            proposed_excel_changes=proposed_changes,
            proposed_calendar_range={"start_date": start.isoformat(), "end_date": end.isoformat()},
            overwrite_existing_plan=request.overwrite_existing_plan,
        )

    def _date_range(self, request: MonthlyPlanningRequest) -> tuple[date, date]:
        month_start = datetime.strptime(request.month, "%b %Y").date().replace(day=1)
        month_end = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])
        today = (request.current_datetime.date() if request.current_datetime else date.today())
        default_start = month_start if request.planning_mode == "full_month" else max(month_start, today)
        start = request.start_date or default_start
        end = request.end_date or month_end
        if end < start:
            raise ValueError("end_date must be on or after start_date")
        return start, end

    def _week_ranges(
        self,
        start: date,
        end: date,
        month_plan: MonthPlan,
    ) -> list[tuple[int, date, date]]:
        ranges: list[tuple[int, date, date]] = []
        for week_number in range(1, len(month_plan.week_sections) + 1):
            week_start, week_end = workbook_week_range(month_plan, week_number)
            if week_end < start or week_start > end:
                continue
            ranges.append((week_number, max(start, week_start), min(end, week_end)))
        if not ranges:
            raise ValueError("Requested range does not overlap a workbook week section")
        return ranges

    def _milestones_for_goal(
        self,
        goal: MonthlyGoal,
        ranges: list[tuple[int, date, date]],
    ) -> tuple[list[WeeklyMilestone], tuple[int, int, int, str | None, str]]:
        total, completed, label, confidence = self._units(goal)
        remaining = max(0, total - completed)
        selected = self._target_ranges(goal.target_week, ranges)
        cadence, sessions, duration, daypart = self._heuristic(goal, remaining, selected)
        category = self._canonical_category(goal, cadence)
        if confidence == "low" and cadence in {"daily", "gym", "weekly_sessions", "sessions"}:
            total = sessions
            completed = 0
            remaining = sessions
            label = "session"
        allocations = self._allocate_units(max(remaining, sessions), len(selected))
        milestones = [
            WeeklyMilestone(
                week_number=week_number,
                start_date=start,
                end_date=end,
                goal_name=goal.name,
                milestone_title=f"{goal.name}: {units} {label or 'session'}{'s' if units != 1 else ''}",
                units_planned=units,
                estimated_minutes=max(duration, units * duration if cadence not in {"daily", "weekly_sessions"} else units * duration),
                priority=goal.priority.value,
                category=category,
                unit_label=label,
                cadence=cadence,
                preferred_daypart=daypart,
            )
            for (week_number, start, end), units in zip(selected, allocations)
            if units > 0
        ]
        return milestones, (total, completed, remaining, label, confidence)

    def _canonical_category(self, goal: MonthlyGoal, cadence: str) -> str | None:
        text = f"{goal.name} {goal.category or ''}".casefold()
        for category in ("german", "piano", "gym", "ielts", "ignou", "reading"):
            if category in text:
                return category
        return goal.category or cadence

    def _units(self, goal: MonthlyGoal) -> tuple[int, int, str | None, str]:
        text = f"{goal.name} {goal.notes or ''}"
        matches = re.findall(r"(\d+)\s*(chapters?|lessons?|sessions?|blocks?|units?)", text, re.I)
        completed_match = re.search(r"(?:done|completed)\s*[:=-]?\s*(\d+)", text, re.I)
        if matches:
            total = max(int(value) for value, _ in matches)
            label = matches[-1][1].lower().rstrip("s")
            completed = int(completed_match.group(1)) if completed_match else 0
            return total, min(completed, total), label, "high"
        return 1, 0, None, "low"

    def _target_ranges(
        self,
        target_week: str | None,
        ranges: list[tuple[int, date, date]],
    ) -> list[tuple[int, date, date]]:
        numbers = [int(value) for value in re.findall(r"\d+", target_week or "")]
        if not numbers:
            return ranges
        selected = [item for item in ranges if item[0] in numbers or (len(numbers) > 1 and min(numbers) <= item[0] <= max(numbers))]
        return selected or [ranges[-1]]

    def _heuristic(
        self,
        goal: MonthlyGoal,
        remaining: int,
        ranges: list[tuple[int, date, date]],
    ) -> tuple[str, int, int, str | None]:
        text = f"{goal.name} {goal.category or ''}".casefold()
        days = sum((end - start).days + 1 for _, start, end in ranges)
        weeks = len(ranges)
        if "german" in text:
            return "daily", days, 45, "evening"
        if "piano" in text:
            return "daily", days, self.rules_engine.piano_duration_minutes(), "evening"
        if "gym" in text:
            return "gym", weeks * self.rules_engine.required_gym_sessions(), 60, "evening"
        if "ielts" in text:
            return "weekly_sessions", weeks * self.rules_engine.required_ielts_sessions(), 90, "evening"
        if "ignou" in text:
            return "weekly_sessions", weeks * self.rules_engine.ignou_session_range()[0], 90, "evening"
        if "read" in text or remaining > 1:
            return "units", max(1, remaining), 30, "evening"
        sessions = 1 if goal.priority != Priority.HIGH else min(3, max(1, weeks))
        return "sessions", sessions, 60, None

    def _allocate_units(self, units: int, count: int) -> list[int]:
        if count <= 0:
            return []
        quotient, remainder = divmod(units, count)
        return [quotient + (1 if index < remainder else 0) for index in range(count)]


def _serialize(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value
