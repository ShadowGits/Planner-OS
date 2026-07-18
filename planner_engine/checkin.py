"""Daily progress review and recurring-task materialization for Planner OS."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from planner_engine.date_utils import week_number_for_date
from planner_engine.models import DatedTask, MonthPlan, MonthlyGoal, PlannerTask, TaskStatus
from planner_engine.planner import PlannerEngine
from planner_engine.progress import ProgressEngine
from planner_engine.rules import RulesEngine

RULES_ACTIVITY_TITLES: dict[str, str] = {
    "german": "German study",
    "piano": "Piano practice",
    "reading": "Reading",
    "gym": "Gym",
}

RULES_ACTIVITY_DURATIONS: dict[str, int] = {
    "german": 45,
    "piano": 30,
    "reading": 30,
    "gym": 60,
}


def ensure_recurring_tasks_in_workbook(
    target: date,
    rules_engine: RulesEngine,
    writer: "Writer",
) -> list[str]:
    """Write workbook rows for each enabled recurring activity if not already present.

    Returns the list of titles that were added (empty if all already existed).
    """
    from planner_engine.writer import Writer

    added: list[str] = []
    for rule_key, title in RULES_ACTIVITY_TITLES.items():
        if not rules_engine.is_rule_enabled(rule_key):
            continue
        duration = RULES_ACTIVITY_DURATIONS[rule_key]
        if rule_key == "piano":
            duration = rules_engine.piano_duration_minutes()
        result = writer.add_dated_task(
            target,
            title,
            duration,
            category=rule_key,
            notes="Recurring (from rules)",
        )
        if result.success:
            added.append(title)
    return added


@dataclass(frozen=True)
class DailyCheckInReport:
    date: date
    planned_tasks: list[str]
    completed_tasks: list[str]
    missed_tasks: list[str]
    partial_tasks: list[str]
    recurring_status: dict[str, Any]
    streaks: dict[str, int]
    slippage_alerts: list[dict[str, Any]]
    today_completion_percentage: float
    weekly_completion_percentage: float
    monthly_completion_percentage: float
    recommended_actions: list[str]
    tomorrow_carryover: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["date"] = self.date.isoformat()
        return data


class DailyCheckInService:
    """Generate daily check-ins from workbook state, rules, and Progress Engine."""

    def __init__(
        self,
        engine: PlannerEngine,
        progress_engine: ProgressEngine | None = None,
        rules_engine: RulesEngine | None = None,
        writer: "Writer | None" = None,
    ) -> None:
        self.engine = engine
        self.progress = progress_engine or ProgressEngine()
        self.rules_engine = rules_engine
        self._writer = writer

    def generate_daily_checkin(self, target_date: date | None = None) -> DailyCheckInReport:
        target = target_date or date.today()
        if self.rules_engine and self._writer:
            ensure_recurring_tasks_in_workbook(target, self.rules_engine, self._writer)
        month_plan = self.engine.get_month_plan(target.strftime("%b %Y"))
        planned = self._planned_for_date(month_plan, target)
        dated_tasks = self.engine.list_dated_tasks(target.strftime("%b %Y"), target)
        self._seed_completed(planned, target)
        self._seed_completed_dated(dated_tasks, target)
        completed = [item.name for item in planned if item.status == TaskStatus.DONE]
        completed.extend(item.title for item in dated_tasks if item.status == TaskStatus.DONE)
        partial = [item.name for item in planned if item.status == TaskStatus.IN_PROGRESS]
        partial.extend(item.title for item in dated_tasks if item.status == TaskStatus.IN_PROGRESS)
        missed = [item.name for item in planned if item.status not in {TaskStatus.DONE, TaskStatus.IN_PROGRESS}]
        missed.extend(item.title for item in dated_tasks if item.status not in {TaskStatus.DONE, TaskStatus.IN_PROGRESS})
        week_start = target - timedelta(days=target.weekday())
        all_items = self._all_items(month_plan)
        daily = self.progress.calculate_daily_progress(target, planned)
        weekly = self.progress.calculate_weekly_progress(week_start, all_items)
        monthly = self.progress.calculate_monthly_progress(month_plan, target.replace(day=1), target)
        alerts = self.progress.generate_alerts(
            current_date=target,
            week_start=week_start,
            month_plan=month_plan,
            current_week_number=week_number_for_date(month_plan, target),
        )
        german_done = self._contains(completed, "german")
        recommendations: list[str] = []
        if not german_done:
            recommendations.append("Do German now if time remains; otherwise carry it to tomorrow as urgent")
        recommendations.extend(f"Move to tomorrow: {name}" for name in missed[:3])
        if weekly.gym_sessions_completed < weekly.gym_sessions_required:
            recommendations.append(
                f"Gym shortfall: {weekly.gym_sessions_required - weekly.gym_sessions_completed} session(s)"
            )
        carryover = [name for name in missed if name not in completed]
        total_today = len(planned) + len(dated_tasks)
        today_percentage = round(((len(completed) + 0.5 * len(partial)) / total_today) * 100, 2) if total_today else 0.0
        return DailyCheckInReport(
            date=target,
            planned_tasks=[item.name for item in planned] + [item.title for item in dated_tasks],
            completed_tasks=completed,
            missed_tasks=missed,
            partial_tasks=partial,
            recurring_status={
                "german_done": german_done,
                "gym_sessions_completed": weekly.gym_sessions_completed,
                "gym_sessions_required": weekly.gym_sessions_required,
                "ielts_sessions_completed": weekly.ielts_sessions_completed,
                "ielts_sessions_target": weekly.ielts_sessions_target,
                "ignou_sessions_completed": weekly.ignou_sessions_completed,
                "ignou_sessions_min": weekly.ignou_sessions_min,
            },
            streaks={
                "german": self.progress.calculate_streak("german", target).current_count,
                "piano": self.progress.calculate_streak("piano", target).current_count,
            },
            slippage_alerts=[
                {"item": item.item, "reason": item.reason, "severity": item.severity}
                for item in alerts
            ],
            today_completion_percentage=today_percentage,
            weekly_completion_percentage=weekly.completion_percentage,
            monthly_completion_percentage=monthly.completion_percentage,
            recommended_actions=recommendations,
            tomorrow_carryover=carryover,
        )

    def _planned_for_date(self, plan: MonthPlan, target: date) -> list[PlannerTask | MonthlyGoal]:
        dated: list[PlannerTask | MonthlyGoal] = []
        for item in self._all_items(plan):
            match = re.search(r"Planned\s+(\d{4}-\d{2}-\d{2})", item.notes or "", re.I)
            if match and date.fromisoformat(match.group(1)) == target:
                dated.append(item)
        if dated:
            return dated
        week = week_number_for_date(plan, target)
        tasks = (
            [
                task
                for task in plan.week_sections[week - 1].tasks
                if not task.scheduled_dates
            ]
            if 1 <= week <= len(plan.week_sections)
            else []
        )
        recurring = [goal for goal in plan.monthly_goals if self._contains([goal.name, goal.category or ""], "german")]
        return [*tasks, *recurring]

    def _seed_completed(self, items: list[PlannerTask | MonthlyGoal], target: date) -> None:
        for item in items:
            if item.status == TaskStatus.DONE:
                self.progress.record_completion(
                    item.name,
                    target,
                    category=item.category,
                    priority=item.priority,
                    recurring_key=self._recurring_key(item),
                )

    def _seed_completed_dated(
        self,
        items: list[DatedTask],
        target: date,
    ) -> None:
        for item in items:
            if item.status == TaskStatus.DONE:
                self.progress.record_completion(
                    item.title,
                    target,
                    category=item.category,
                    recurring_key=self._dated_recurring_key(item),
                )

    def _all_items(self, plan: MonthPlan) -> list[PlannerTask | MonthlyGoal]:
        return [*plan.monthly_goals, *(task for section in plan.week_sections for task in section.tasks)]

    def _recurring_key(self, item: PlannerTask | MonthlyGoal) -> str | None:
        for key in ("german", "piano", "gym", "ielts", "ignou"):
            if self._contains([item.name, item.category or ""], key):
                return key
        return item.category

    def _dated_recurring_key(self, item: DatedTask) -> str | None:
        for key in ("german", "piano", "gym", "ielts", "ignou"):
            if self._contains([item.title, item.category or ""], key):
                return key
        return item.category

    def _contains(self, values: list[str], needle: str) -> bool:
        return any(needle.casefold() in value.casefold() for value in values)


def generate_daily_checkin(
    engine: PlannerEngine,
    target_date: date | None = None,
    progress_engine: ProgressEngine | None = None,
    rules_engine: RulesEngine | None = None,
) -> DailyCheckInReport:
    return DailyCheckInService(engine, progress_engine, rules_engine=rules_engine).generate_daily_checkin(target_date)
