"""Scheduling heuristics for workload balancing and preferences."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta

from planner_engine.date_utils import workbook_week_range
from planner_engine.models import MonthPlan, MonthlyGoal, PlannerTask, Priority, TaskStatus
from planner_engine.scheduler.durations import ScheduleDemand


HEAVY_CATEGORIES = {"ielts", "ignou", "learning", "planner_work"}


class HeuristicsMixin:
    """Preference and balancing heuristics for movable scheduler demand."""

    HEAVY_CATEGORIES = HEAVY_CATEGORIES

    def _spread_planner_demands(
        self,
        per_day_demands: dict[date, list[ScheduleDemand]],
        month_plan: MonthPlan,
        unfinished_tasks: list[PlannerTask | MonthlyGoal],
    ) -> None:
        """Spread planner and unfinished work across the week."""

        days = list(per_day_demands)
        for demand in self._task_demands(unfinished_tasks, source_prefix="unfinished"):
            per_day_demands[self._deterministic_day_for_source(days, demand.source)].append(
                demand
            )

        last_heavy_day: date | None = None
        for item in self._planner_items(month_plan):
            demand = self._task_demands([item])[0]
            if isinstance(item, PlannerTask):
                target_days = self._target_days_for_task(month_plan, item, days)
            else:
                target_days = self._target_days_for_goal(month_plan, item, days)
            for chosen_day in target_days:
                if demand.category.casefold() in self.HEAVY_CATEGORIES:
                    for candidate in days:
                        if candidate != last_heavy_day:
                            chosen_day = candidate
                            break
                    last_heavy_day = chosen_day
                per_day_demands[chosen_day].append(demand)

    def _planner_items(
        self,
        month_plan: MonthPlan,
        target_date: date | None = None,
    ) -> list[PlannerTask | MonthlyGoal]:
        """Collect incomplete planner goals and tasks."""

        items: list[PlannerTask | MonthlyGoal] = []
        for goal in month_plan.monthly_goals:
            if goal.status == TaskStatus.DONE:
                continue
            if target_date is None:
                items.append(goal)
                continue
            if target_date in self._target_days_for_goal(month_plan, goal):
                items.append(goal)
        for section in month_plan.week_sections:
            for task in section.tasks:
                if task.status == TaskStatus.DONE:
                    continue
                if target_date is None:
                    items.append(task)
                    continue
                if target_date in self._target_days_for_task(month_plan, task):
                    items.append(task)
        return items

    def _task_demands(
        self,
        tasks: list[PlannerTask | MonthlyGoal],
        source_prefix: str = "planner",
        limit: int | None = None,
    ) -> list[ScheduleDemand]:
        """Convert parsed planner items into schedule demands."""

        demands: list[ScheduleDemand] = []
        for task in tasks[:limit]:
            category = (task.category or "planner_task").casefold()
            if category == "work":
                category = "planner_work"
            duration_key = (
                "monthly_goal" if isinstance(task, MonthlyGoal) else "planner_task"
            )
            demands.append(
                ScheduleDemand(
                    title=task.name,
                    category=category,
                    duration_minutes=self.durations[duration_key],
                    source=f"{source_prefix}:{task.sheet_name}:{task.row_number}",
                    priority=task.priority,
                    metadata={
                        "source_task_id": f"{task.sheet_name}:{task.row_number}",
                        "planner_block_id": f"{source_prefix}:{task.sheet_name}:{task.row_number}",
                    },
                )
            )
        return sorted(
            demands,
            key=lambda demand: (
                0 if demand.priority == Priority.HIGH else 1,
                demand.title.casefold(),
            ),
        )

    def _target_days_for_task(
        self,
        month_plan: MonthPlan,
        task: PlannerTask,
        candidate_days: list[date] | None = None,
    ) -> list[date]:
        """Return the exact scheduler date(s) for a weekly workbook task."""

        if task.scheduled_dates:
            allowed = set(candidate_days) if candidate_days is not None else None
            if allowed is None:
                return list(task.scheduled_dates)
            return [scheduled for scheduled in task.scheduled_dates if scheduled in allowed]

        section = next(
            (
                candidate
                for candidate in month_plan.week_sections
                if candidate.name == task.week_name
            ),
            None,
        )
        if section is None:
            return []
        try:
            section_index = month_plan.week_sections.index(section) + 1
            start, end = workbook_week_range(month_plan, section_index)
        except Exception:
            return []
        week_days = [
            start + timedelta(days=offset)
            for offset in range((end - start).days + 1)
        ]
        candidates = (
            [day for day in week_days if day in set(candidate_days)]
            if candidate_days is not None
            else week_days
        )
        if not candidates:
            return []
        if (task.category or "").casefold() == "work":
            work_days = [
                day
                for day in candidates
                if self.rules_engine.is_work_day(day.strftime("%A"))
            ]
            candidates = work_days or candidates
        return [
            self._deterministic_day_for_source(
                candidates,
                f"planner:{task.sheet_name}:{task.row_number}",
            )
        ]

    def _target_days_for_goal(
        self,
        month_plan: MonthPlan,
        goal: MonthlyGoal,
        candidate_days: list[date] | None = None,
    ) -> list[date]:
        """Return one deterministic date for a monthly goal."""

        days = self._goal_week_days(month_plan, goal)
        if candidate_days is not None:
            allowed = set(candidate_days)
            days = [day for day in days if day in allowed]
        if not days:
            return []
        if goal.target_week:
            return [sorted(days)[0]]
        return [
            self._deterministic_day_for_source(
                days,
                f"planner:{goal.sheet_name}:{goal.row_number}",
            )
        ]

    def _goal_week_days(self, month_plan: MonthPlan, goal: MonthlyGoal) -> list[date]:
        if goal.target_week:
            match = re.search(r"\d+", goal.target_week)
            if match:
                try:
                    start, end = workbook_week_range(month_plan, int(match.group()))
                    return [
                        start + timedelta(days=offset)
                        for offset in range((end - start).days + 1)
                    ]
                except Exception:
                    pass
        if not month_plan.week_sections:
            return []
        try:
            start, end = workbook_week_range(month_plan, 1)
        except Exception:
            return []
        return [
            start + timedelta(days=offset)
            for offset in range((end - start).days + 1)
        ]

    def _deterministic_day_for_source(self, days: list[date], source: str) -> date:
        """Choose one stable date for a non-recurring planner source."""

        ordered_days = sorted(days)
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return ordered_days[int(digest[:8], 16) % len(ordered_days)]

    def _preferred_windows(
        self,
        target_date: date,
        demand: ScheduleDemand,
    ) -> list[tuple[datetime, datetime]]:
        """Return preferred scheduling windows for a demand."""

        if demand.requested_window_start and demand.requested_window_end:
            requested_window = [
                (demand.requested_window_start, demand.requested_window_end)
            ]
            if demand.hard_window:
                return requested_window
        else:
            requested_window = []

        day_start = datetime.combine(target_date, time.min)
        day_end = day_start + timedelta(days=1)
        category = demand.category.casefold()
        if category == "german":
            windows = [(time(9, 30), time(11, 0)), (time(14, 0), time(18, 0))]
        elif category == "piano":
            windows = [(time(10, 0), time(11, 0)), (time(15, 0), time(18, 30))]
        elif category in {"ielts", "ignou", "learning", "work"}:
            windows = [(time(13, 0), time(18, 30)), (time(9, 30), time(11, 0))]
        elif category.startswith("gym"):
            windows = [(time(19, 15), time(22, 30)), (time(16, 30), time(20, 15))]
        elif category == "reading":
            windows = [(time(19, 30), time(23, 0)), (time(18, 0), time(20, 15))]
        else:
            windows = [(time(13, 0), time(18, 30)), (time(9, 30), time(23, 0))]

        result = requested_window + [
            (
                datetime.combine(target_date, start),
                datetime.combine(target_date, end),
            )
            for start, end in windows
        ]
        result.append((day_start, day_end))
        return result

    def _category_order(self, category: str) -> int:
        """Return deterministic placement priority by category."""

        order = {
            "german": 0,
            "piano": 1,
            "ielts": 2,
            "ignou": 3,
            "gym_strength": 4,
            "gym_dance": 5,
            "reading": 8,
        }
        return order.get(category.casefold(), 6)
