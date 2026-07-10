"""Scheduling heuristics for workload balancing and preferences."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

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
        planner_demands = self._task_demands(
            unfinished_tasks,
            source_prefix="unfinished",
        )
        planner_demands.extend(self._task_demands(self._planner_items(month_plan)))

        day_index = 0
        last_heavy_day: date | None = None
        for demand in planner_demands:
            chosen_day = days[day_index % len(days)]
            if demand.category.casefold() in self.HEAVY_CATEGORIES:
                for candidate in days:
                    if candidate != last_heavy_day:
                        chosen_day = candidate
                        break
                last_heavy_day = chosen_day
            per_day_demands[chosen_day].append(demand)
            day_index += 1

    def _planner_items(self, month_plan: MonthPlan) -> list[PlannerTask | MonthlyGoal]:
        """Collect incomplete planner goals and tasks."""

        items: list[PlannerTask | MonthlyGoal] = []
        for goal in month_plan.monthly_goals:
            if goal.status != TaskStatus.DONE:
                items.append(goal)
        for section in month_plan.week_sections:
            for task in section.tasks:
                if task.status != TaskStatus.DONE:
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
                )
            )
        return sorted(
            demands,
            key=lambda demand: (
                0 if demand.priority == Priority.HIGH else 1,
                demand.title.casefold(),
            ),
        )

    def _preferred_windows(
        self,
        target_date: date,
        demand: ScheduleDemand,
    ) -> list[tuple[datetime, datetime]]:
        """Return preferred scheduling windows for a demand."""

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

        result = [
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
