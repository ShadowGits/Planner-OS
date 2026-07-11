"""Scheduler Engine v1 for Planner OS."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from planner_engine.decision_log import DecisionLog, DecisionOutcome
from planner_engine.models import (
    DailyPlan,
    FixedCommitment,
    MonthPlan,
    MonthlyGoal,
    PlannerTask,
    ScheduledBlock,
    SchedulingConflict,
    WeeklyPlan,
)
from planner_engine.rules import RulesEngine
from planner_engine.scheduler.allocator import AllocatorMixin
from planner_engine.scheduler.conflicts import ConflictMixin
from planner_engine.scheduler.constraints import ConstraintsMixin
from planner_engine.scheduler.durations import (
    DEFAULT_DURATIONS_MINUTES,
    ScheduleDemand,
    merged_durations,
)
from planner_engine.scheduler.heuristics import HEAVY_CATEGORIES, HeuristicsMixin


class SchedulerEngine(
    ConstraintsMixin,
    HeuristicsMixin,
    AllocatorMixin,
    ConflictMixin,
):
    """Generate read-only day and week plans from rules and planner demand."""

    DEFAULT_DURATIONS_MINUTES: dict[str, int] = DEFAULT_DURATIONS_MINUTES
    HEAVY_CATEGORIES = HEAVY_CATEGORIES

    def __init__(
        self,
        rules_engine: RulesEngine,
        durations: dict[str, int] | None = None,
        decision_log: DecisionLog | None = None,
    ) -> None:
        self.rules_engine = rules_engine
        self.durations = merged_durations(durations)
        self.decision_log = decision_log or DecisionLog()
        self.decision_log_warnings: list[str] = []

    def plan_day(
        self,
        month_plan: MonthPlan,
        target_date: date,
        fixed_commitments: list[FixedCommitment] | None = None,
        context_overrides: dict[str, Any] | None = None,
        unfinished_tasks: list[PlannerTask | MonthlyGoal] | None = None,
    ) -> DailyPlan:
        """Generate a daily plan without writing to Excel."""

        fixed_commitments = fixed_commitments or []
        context_overrides = context_overrides or {}
        unfinished_tasks = unfinished_tasks or []
        conflicts = self._fixed_commitment_conflicts(fixed_commitments)
        conflicts.extend(self._dance_commitment_conflicts(fixed_commitments))
        blocks = self._base_blocks_for_day(target_date, fixed_commitments, conflicts)
        demands = self._daily_demands(target_date, context_overrides)
        demands.extend(self._task_demands(unfinished_tasks, source_prefix="unfinished"))
        demands.extend(self._task_demands(self._planner_items(month_plan), limit=2))

        scheduled_blocks, placement_conflicts = self._place_demands_for_day(
            target_date=target_date,
            existing_blocks=blocks,
            demands=demands,
        )
        blocks.extend(scheduled_blocks)
        conflicts.extend(placement_conflicts)
        plan = DailyPlan(
            date=target_date,
            blocks=self._sort_blocks(blocks),
            conflicts=conflicts,
        )
        self._record_plan_decision(
            action="plan_day",
            reason="Generate daily plan from planner goals, rules, and constraints",
            affected_tasks=[block.title for block in scheduled_blocks],
            conflicts=conflicts,
            metadata={
                "date": target_date.isoformat(),
                "blocks": len(plan.blocks),
                "unfinished_tasks": [task.name for task in unfinished_tasks],
                "moved_or_rescheduled_tasks": [
                    task.name for task in unfinished_tasks
                ],
            },
        )
        return plan

    def plan_week(
        self,
        month_plan: MonthPlan,
        target_week_start: date,
        fixed_commitments: list[FixedCommitment] | None = None,
        context_overrides: dict[str, Any] | None = None,
        unfinished_tasks: list[PlannerTask | MonthlyGoal] | None = None,
    ) -> WeeklyPlan:
        """Generate a weekly plan without writing to Excel."""

        fixed_commitments = fixed_commitments or []
        context_overrides = context_overrides or {}
        unfinished_tasks = unfinished_tasks or []
        conflicts = self._fixed_commitment_conflicts(fixed_commitments)
        conflicts.extend(self._dance_commitment_conflicts(fixed_commitments))

        per_day_demands: dict[date, list[ScheduleDemand]] = {
            target_week_start + timedelta(days=offset): []
            for offset in range(7)
        }
        self._add_weekly_recurring_demands(per_day_demands, context_overrides, conflicts)
        self._spread_planner_demands(
            per_day_demands=per_day_demands,
            month_plan=month_plan,
            unfinished_tasks=unfinished_tasks,
        )

        days: list[DailyPlan] = []
        for day in per_day_demands:
            day_conflicts = list(conflicts) if day == target_week_start else []
            blocks = self._base_blocks_for_day(day, fixed_commitments, day_conflicts)
            scheduled_blocks, placement_conflicts = self._place_demands_for_day(
                target_date=day,
                existing_blocks=blocks,
                demands=per_day_demands[day],
            )
            blocks.extend(scheduled_blocks)
            day_conflicts.extend(placement_conflicts)
            days.append(
                DailyPlan(
                    date=day,
                    blocks=self._sort_blocks(blocks),
                    conflicts=day_conflicts,
                )
            )

        weekly_conflicts = [conflict for day in days for conflict in day.conflicts]
        self._validate_weekly_gym_target(days, weekly_conflicts)
        plan = WeeklyPlan(
            week_start=target_week_start,
            days=days,
            conflicts=weekly_conflicts,
        )
        self._record_plan_decision(
            action="plan_week",
            reason="Generate weekly plan from planner goals, rules, and constraints",
            affected_tasks=[
                block.title
                for day in days
                for block in day.blocks
                if not block.is_fixed
            ],
            conflicts=weekly_conflicts,
            metadata={
                "week_start": target_week_start.isoformat(),
                "days": len(days),
                "blocks": sum(len(day.blocks) for day in days),
                "unfinished_tasks": [task.name for task in unfinished_tasks],
                "moved_or_rescheduled_tasks": [
                    task.name for task in unfinished_tasks
                ],
            },
        )
        return plan

    def _record_plan_decision(
        self,
        *,
        action: str,
        reason: str,
        affected_tasks: list[str],
        conflicts: list[SchedulingConflict],
        metadata: dict[str, Any],
    ) -> None:
        """Record scheduler decisions without affecting plan generation."""

        try:
            self.decision_log.record(
                action=action,
                reason=reason,
                confidence=0.8,
                affected_tasks=affected_tasks,
                constraints_considered=[
                    "sleep protection",
                    "work hours",
                    "recurring rules",
                    "fixed commitments",
                    "no overlap",
                ],
                outcome=(
                    DecisionOutcome.WARNING
                    if conflicts
                    else DecisionOutcome.GENERATED
                ),
                metadata={
                    **metadata,
                    "conflicts": [
                        {
                            "item": conflict.item,
                            "reason": conflict.reason,
                            "severity": conflict.severity,
                        }
                        for conflict in conflicts
                    ],
                    "unscheduled_reasons": [
                        f"{conflict.item}: {conflict.reason}"
                        for conflict in conflicts
                    ],
                },
            )
        except Exception as error:
            self.decision_log_warnings.append(f"Decision log warning: {error}")
