"""Progress tracking and alerting for Planner OS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Any

from planner_engine.models import MonthPlan, MonthlyGoal, PlannerTask, Priority, TaskStatus


class ExecutionStatus(str, Enum):
    """Recorded execution outcomes."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    PARTIAL = "partial"


@dataclass(frozen=True)
class TaskExecution:
    """A recorded execution event for a task or recurring habit."""

    task_name: str
    execution_date: date
    status: ExecutionStatus
    category: str | None = None
    priority: Priority = Priority.UNKNOWN
    completion_ratio: float = 1.0
    sessions_completed: int = 1
    recurring_key: str | None = None


@dataclass(frozen=True)
class DailyProgress:
    """Progress metrics for one day."""

    date: date
    completed_tasks: list[str]
    skipped_tasks: list[str]
    partial_tasks: list[str]
    overdue_tasks: list[str]
    completion_percentage: float
    per_category_completion: dict[str, float]
    recurring_adherence: dict[str, bool]


@dataclass(frozen=True)
class WeeklyProgress:
    """Progress metrics for one week."""

    week_start: date
    week_end: date
    completed_tasks: list[str]
    skipped_tasks: list[str]
    overdue_tasks: list[str]
    completion_percentage: float
    per_category_completion: dict[str, float]
    recurring_adherence: dict[str, float]
    gym_sessions_completed: int
    gym_sessions_required: int
    ielts_sessions_completed: int
    ielts_sessions_target: int
    ignou_sessions_completed: int
    ignou_sessions_min: int
    ignou_sessions_max: int


@dataclass(frozen=True)
class MonthlyProgress:
    """Progress metrics for one month plan."""

    month: str
    completed_goals: int
    total_goals: int
    completed_tasks: int
    total_tasks: int
    overdue_tasks: list[str]
    completion_percentage: float
    per_category_completion: dict[str, float]


@dataclass(frozen=True)
class Streak:
    """Consecutive completion streak for a recurring task."""

    name: str
    current_count: int
    longest_count: int
    last_completed_date: date | None


@dataclass(frozen=True)
class ProgressAlert:
    """A progress alert generated from slippage rules."""

    reason: str
    item: str
    alert_date: date
    severity: str = "warning"


@dataclass(frozen=True)
class SlippageReport:
    """Structured slippage findings before alert rendering."""

    alerts: list[ProgressAlert] = field(default_factory=list)


@dataclass(frozen=True)
class ProgressSummary:
    """Deterministic progress rollup across planner object types."""

    planned_minutes: int
    completed_minutes: int
    completion_percentage: float
    streaks: dict[str, int]
    adherence_percentage: dict[str, float]
    overdue_count: int
    carry_forward_count: int
    slippage_risk: str
    target_date_forecast: dict[str, str]


class ProgressEngine:
    """Track execution and calculate progress metrics without side effects."""

    def __init__(
        self,
        gym_sessions_required: int = 9,
        ielts_sessions_target: int = 2,
        ignou_sessions_min: int = 2,
        ignou_sessions_max: int = 3,
    ) -> None:
        self.executions: list[TaskExecution] = []
        self.gym_sessions_required = gym_sessions_required
        self.ielts_sessions_target = ielts_sessions_target
        self.ignou_sessions_min = ignou_sessions_min
        self.ignou_sessions_max = ignou_sessions_max

    def record_completion(
        self,
        task_name: str,
        execution_date: date,
        category: str | None = None,
        priority: Priority = Priority.UNKNOWN,
        sessions_completed: int = 1,
        recurring_key: str | None = None,
    ) -> TaskExecution:
        """Record a completed task or session."""

        execution = TaskExecution(
            task_name=task_name,
            execution_date=execution_date,
            status=ExecutionStatus.COMPLETED,
            category=category,
            priority=priority,
            completion_ratio=1.0,
            sessions_completed=sessions_completed,
            recurring_key=self._normalized_key(recurring_key or category or task_name),
        )
        self.executions.append(execution)
        return execution

    def record_skip(
        self,
        task_name: str,
        execution_date: date,
        category: str | None = None,
        priority: Priority = Priority.UNKNOWN,
        recurring_key: str | None = None,
    ) -> TaskExecution:
        """Record a skipped task."""

        execution = TaskExecution(
            task_name=task_name,
            execution_date=execution_date,
            status=ExecutionStatus.SKIPPED,
            category=category,
            priority=priority,
            completion_ratio=0.0,
            sessions_completed=0,
            recurring_key=self._normalized_key(recurring_key or category or task_name),
        )
        self.executions.append(execution)
        return execution

    def record_partial_completion(
        self,
        task_name: str,
        execution_date: date,
        completion_ratio: float,
        category: str | None = None,
        priority: Priority = Priority.UNKNOWN,
        recurring_key: str | None = None,
    ) -> TaskExecution:
        """Record a partial completion with a ratio from 0.0 to 1.0."""

        bounded_ratio = min(1.0, max(0.0, completion_ratio))
        execution = TaskExecution(
            task_name=task_name,
            execution_date=execution_date,
            status=ExecutionStatus.PARTIAL,
            category=category,
            priority=priority,
            completion_ratio=bounded_ratio,
            sessions_completed=0,
            recurring_key=self._normalized_key(recurring_key or category or task_name),
        )
        self.executions.append(execution)
        return execution

    def calculate_daily_progress(
        self,
        target_date: date,
        planned_tasks: list[PlannerTask | MonthlyGoal] | None = None,
        overdue_tasks: list[PlannerTask | MonthlyGoal] | None = None,
    ) -> DailyProgress:
        """Calculate progress for one day."""

        planned_tasks = planned_tasks or []
        overdue_tasks = overdue_tasks or []
        executions = self._executions_between(target_date, target_date)
        return DailyProgress(
            date=target_date,
            completed_tasks=[
                execution.task_name
                for execution in executions
                if execution.status == ExecutionStatus.COMPLETED
            ],
            skipped_tasks=[
                execution.task_name
                for execution in executions
                if execution.status == ExecutionStatus.SKIPPED
            ],
            partial_tasks=[
                execution.task_name
                for execution in executions
                if execution.status == ExecutionStatus.PARTIAL
            ],
            overdue_tasks=[task.name for task in overdue_tasks],
            completion_percentage=self._completion_percentage(planned_tasks, executions),
            per_category_completion=self._per_category_completion(planned_tasks, executions),
            recurring_adherence={
                "german": self._has_completion("german", target_date),
                "piano": self._has_completion("piano", target_date),
            },
        )

    def calculate_weekly_progress(
        self,
        week_start: date,
        planned_tasks: list[PlannerTask | MonthlyGoal] | None = None,
        overdue_tasks: list[PlannerTask | MonthlyGoal] | None = None,
    ) -> WeeklyProgress:
        """Calculate progress for a week beginning on week_start."""

        planned_tasks = planned_tasks or []
        overdue_tasks = overdue_tasks or []
        week_end = week_start + timedelta(days=6)
        executions = self._executions_between(week_start, week_end)
        return WeeklyProgress(
            week_start=week_start,
            week_end=week_end,
            completed_tasks=[
                execution.task_name
                for execution in executions
                if execution.status == ExecutionStatus.COMPLETED
            ],
            skipped_tasks=[
                execution.task_name
                for execution in executions
                if execution.status == ExecutionStatus.SKIPPED
            ],
            overdue_tasks=[task.name for task in overdue_tasks],
            completion_percentage=self._completion_percentage(planned_tasks, executions),
            per_category_completion=self._per_category_completion(planned_tasks, executions),
            recurring_adherence={
                "german": self._adherence_ratio("german", week_start, week_end, 7),
                "piano": self._adherence_ratio("piano", week_start, week_end, 7),
            },
            gym_sessions_completed=self._session_count("gym", week_start, week_end),
            gym_sessions_required=self.gym_sessions_required,
            ielts_sessions_completed=self._session_count("ielts", week_start, week_end),
            ielts_sessions_target=self.ielts_sessions_target,
            ignou_sessions_completed=self._session_count("ignou", week_start, week_end),
            ignou_sessions_min=self.ignou_sessions_min,
            ignou_sessions_max=self.ignou_sessions_max,
        )

    def calculate_monthly_progress(
        self,
        month_plan: MonthPlan,
        start_date: date | None = None,
        end_date: date | None = None,
        overdue_tasks: list[PlannerTask | MonthlyGoal] | None = None,
    ) -> MonthlyProgress:
        """Calculate progress for a parsed month plan."""

        overdue_tasks = overdue_tasks or []
        planned_items = self._month_items(month_plan)
        if start_date is None:
            start_date = min(
                (execution.execution_date for execution in self.executions),
                default=date.min,
            )
        if end_date is None:
            end_date = max(
                (execution.execution_date for execution in self.executions),
                default=date.max,
            )
        executions = self._executions_between(start_date, end_date)
        completed_names = {
            execution.task_name.casefold()
            for execution in executions
            if execution.status == ExecutionStatus.COMPLETED
        }
        completed_goals = sum(
            1 for goal in month_plan.monthly_goals if goal.name.casefold() in completed_names
        )
        return MonthlyProgress(
            month=month_plan.month,
            completed_goals=completed_goals,
            total_goals=len(month_plan.monthly_goals),
            completed_tasks=len(
                [item for item in planned_items if item.name.casefold() in completed_names]
            ),
            total_tasks=len(planned_items),
            overdue_tasks=[task.name for task in overdue_tasks],
            completion_percentage=self._completion_percentage(planned_items, executions),
            per_category_completion=self._per_category_completion(planned_items, executions),
        )

    def calculate_streak(
        self,
        recurring_key: str,
        through_date: date,
    ) -> Streak:
        """Calculate current and longest daily completion streak."""

        normalized_key = self._normalized_key(recurring_key)
        completed_dates = {
            execution.execution_date
            for execution in self.executions
            if execution.recurring_key == normalized_key
            and execution.status == ExecutionStatus.COMPLETED
        }
        if not completed_dates:
            return Streak(
                name=normalized_key,
                current_count=0,
                longest_count=0,
                last_completed_date=None,
            )

        longest = 0
        current_run = 0
        previous_day: date | None = None
        for completed_date in sorted(completed_dates):
            if previous_day is not None and completed_date == previous_day + timedelta(days=1):
                current_run += 1
            else:
                current_run = 1
            longest = max(longest, current_run)
            previous_day = completed_date

        current = 0
        cursor = through_date
        while cursor in completed_dates:
            current += 1
            cursor -= timedelta(days=1)

        return Streak(
            name=normalized_key,
            current_count=current,
            longest_count=longest,
            last_completed_date=max(completed_dates),
        )

    def detect_slippage(
        self,
        current_date: date,
        week_start: date,
        month_plan: MonthPlan | None = None,
        current_week_number: int | None = None,
        overdue_tasks: list[PlannerTask | MonthlyGoal] | None = None,
    ) -> SlippageReport:
        """Detect progress slippage against hard progress rules."""

        alerts: list[ProgressAlert] = []
        overdue_tasks = overdue_tasks or []
        week_end = week_start + timedelta(days=6)
        remaining_days = max(0, (week_end - current_date).days + 1)

        if not self._has_completion("german", current_date):
            alerts.append(
                ProgressAlert(
                    reason="German missed today",
                    item="German",
                    alert_date=current_date,
                    severity="error",
                )
            )

        gym_completed = self._session_count("gym", week_start, current_date)
        if gym_completed + (remaining_days * 2) < self.gym_sessions_required:
            alerts.append(
                ProgressAlert(
                    reason="Gym cannot mathematically reach weekly target",
                    item="Gym sessions",
                    alert_date=current_date,
                    severity="error",
                )
            )

        ielts_completed = self._session_count("ielts", week_start, current_date)
        if ielts_completed + remaining_days < self.ielts_sessions_target:
            alerts.append(
                ProgressAlert(
                    reason="IELTS cannot reach weekly target",
                    item="IELTS sessions",
                    alert_date=current_date,
                    severity="error",
                )
            )

        for task in overdue_tasks:
            if task.priority == Priority.HIGH:
                alerts.append(
                    ProgressAlert(
                        reason="High-priority task overdue",
                        item=task.name,
                        alert_date=current_date,
                        severity="error",
                    )
                )

        if month_plan is not None and current_week_number is not None:
            for goal in month_plan.monthly_goals:
                target_end_week = self._target_end_week(goal.target_week)
                if (
                    target_end_week is not None
                    and current_week_number > target_end_week
                    and goal.status != TaskStatus.DONE
                    and not self._task_completed(goal.name)
                ):
                    alerts.append(
                        ProgressAlert(
                            reason="Monthly goal behind schedule",
                            item=goal.name,
                            alert_date=current_date,
                            severity="warning",
                        )
                    )

        return SlippageReport(alerts=alerts)

    def generate_alerts(
        self,
        current_date: date,
        week_start: date,
        month_plan: MonthPlan | None = None,
        current_week_number: int | None = None,
        overdue_tasks: list[PlannerTask | MonthlyGoal] | None = None,
    ) -> list[ProgressAlert]:
        """Generate progress alerts from slippage detection."""

        return self.detect_slippage(
            current_date=current_date,
            week_start=week_start,
            month_plan=month_plan,
            current_week_number=current_week_number,
            overdue_tasks=overdue_tasks,
        ).alerts

    def summarize_progress(
        self,
        *,
        planned_minutes: int = 0,
        carry_forward_count: int = 0,
        overdue_tasks: list[PlannerTask | MonthlyGoal] | None = None,
        through_date: date | None = None,
        target_dates: dict[str, date] | None = None,
    ) -> ProgressSummary:
        """Return a deterministic MVP2 progress model for tasks, habits, and goals."""

        overdue_tasks = overdue_tasks or []
        through_date = through_date or max(
            (execution.execution_date for execution in self.executions),
            default=date.today(),
        )
        completed_minutes = sum(
            int((execution.completion_ratio or 0.0) * 60)
            * max(1, execution.sessions_completed)
            for execution in self.executions
            if execution.status in {ExecutionStatus.COMPLETED, ExecutionStatus.PARTIAL}
        )
        denominator = planned_minutes or completed_minutes
        completion = round((completed_minutes / denominator) * 100, 2) if denominator else 0.0
        adherence = {
            "german": round(self._adherence_ratio("german", through_date - timedelta(days=6), through_date, 7) * 100, 2),
            "piano": round(self._adherence_ratio("piano", through_date - timedelta(days=6), through_date, 7) * 100, 2),
            "gym": round((self._session_count("gym", through_date - timedelta(days=6), through_date) / max(1, self.gym_sessions_required)) * 100, 2),
            "ielts": round((self._session_count("ielts", through_date - timedelta(days=6), through_date) / max(1, self.ielts_sessions_target)) * 100, 2),
        }
        target_date_forecast = {
            name: self._forecast_status(name, target, through_date)
            for name, target in (target_dates or {}).items()
        }
        risk = "high" if overdue_tasks or any(value < 50 for value in adherence.values()) else "low"
        if risk == "low" and (carry_forward_count or any(value < 80 for value in adherence.values())):
            risk = "medium"
        return ProgressSummary(
            planned_minutes=planned_minutes,
            completed_minutes=completed_minutes,
            completion_percentage=completion,
            streaks={
                "german": self.calculate_streak("german", through_date).current_count,
                "piano": self.calculate_streak("piano", through_date).current_count,
            },
            adherence_percentage=adherence,
            overdue_count=len(overdue_tasks),
            carry_forward_count=carry_forward_count,
            slippage_risk=risk,
            target_date_forecast=target_date_forecast,
        )

    def _executions_between(self, start_date: date, end_date: date) -> list[TaskExecution]:
        """Return execution records inside an inclusive date range."""

        return [
            execution
            for execution in self.executions
            if start_date <= execution.execution_date <= end_date
        ]

    def _completion_percentage(
        self,
        planned_tasks: list[PlannerTask | MonthlyGoal],
        executions: list[TaskExecution],
    ) -> float:
        """Calculate weighted completion percentage for planned tasks."""

        if not planned_tasks:
            return 0.0
        execution_by_name = {
            execution.task_name.casefold(): execution for execution in executions
        }
        completed = 0.0
        for task in planned_tasks:
            execution = execution_by_name.get(task.name.casefold())
            if execution is not None:
                completed += execution.completion_ratio
        return round((completed / len(planned_tasks)) * 100, 2)

    def _per_category_completion(
        self,
        planned_tasks: list[PlannerTask | MonthlyGoal],
        executions: list[TaskExecution],
    ) -> dict[str, float]:
        """Calculate completion percentage per planned category."""

        by_category: dict[str, list[PlannerTask | MonthlyGoal]] = {}
        for task in planned_tasks:
            category = task.category or "Uncategorized"
            by_category.setdefault(category, []).append(task)
        return {
            category: self._completion_percentage(tasks, executions)
            for category, tasks in by_category.items()
        }

    def _adherence_ratio(
        self,
        recurring_key: str,
        start_date: date,
        end_date: date,
        expected_days: int,
    ) -> float:
        """Calculate recurring completion adherence as a ratio."""

        if expected_days == 0:
            return 0.0
        completed_dates = {
            execution.execution_date
            for execution in self._executions_between(start_date, end_date)
            if execution.recurring_key == self._normalized_key(recurring_key)
            and execution.status == ExecutionStatus.COMPLETED
        }
        return round(len(completed_dates) / expected_days, 2)

    def _session_count(self, recurring_key: str, start_date: date, end_date: date) -> int:
        """Count completed sessions for a recurring key."""

        normalized_key = self._normalized_key(recurring_key)
        return sum(
            execution.sessions_completed
            for execution in self._executions_between(start_date, end_date)
            if execution.recurring_key == normalized_key
            and execution.status == ExecutionStatus.COMPLETED
        )

    def _has_completion(self, recurring_key: str, target_date: date) -> bool:
        """Return whether a recurring key was completed on a date."""

        normalized_key = self._normalized_key(recurring_key)
        return any(
            execution.recurring_key == normalized_key
            and execution.execution_date == target_date
            and execution.status == ExecutionStatus.COMPLETED
            for execution in self.executions
        )

    def _task_completed(self, task_name: str) -> bool:
        """Return whether a task name has any recorded completion."""

        normalized_name = task_name.casefold()
        return any(
            execution.task_name.casefold() == normalized_name
            and execution.status == ExecutionStatus.COMPLETED
            for execution in self.executions
        )

    def _month_items(self, month_plan: MonthPlan) -> list[PlannerTask | MonthlyGoal]:
        """Return all goals and weekly tasks in a month plan."""

        items: list[PlannerTask | MonthlyGoal] = list(month_plan.monthly_goals)
        for section in month_plan.week_sections:
            items.extend(section.tasks)
        return items

    def _target_end_week(self, target_week: str | None) -> int | None:
        """Extract the last week number from target week text."""

        if not target_week:
            return None
        digits = [int(character) for character in target_week if character.isdigit()]
        if not digits:
            return None
        return max(digits)

    def _normalized_key(self, value: str | None) -> str:
        """Normalize recurring keys and category names."""

        return " ".join((value or "").casefold().split())

    def _forecast_status(self, name: str, target: date, through_date: date) -> str:
        if self._task_completed(name):
            return "complete"
        days_remaining = (target - through_date).days
        if days_remaining < 0:
            return "overdue"
        if days_remaining <= 2:
            return "at_risk"
        return "on_track"
