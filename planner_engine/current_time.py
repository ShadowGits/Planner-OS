"""Current-time-aware day planning for Planner OS."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from planner_engine.models import (
    BoundedSessionRequest,
    DailyPlan,
    MonthPlan,
    ScheduledBlock,
    SchedulingConflict,
)
from planner_engine.rules import RulesEngine
from planner_engine.scheduler import SchedulerEngine


class CurrentTimePlanner:
    """Shift flexible past blocks into the remaining usable day."""

    def __init__(self, rules_engine: RulesEngine, scheduler: SchedulerEngine | None = None) -> None:
        self.rules_engine = rules_engine
        self.scheduler = scheduler or SchedulerEngine(rules_engine)
        self.timezone = ZoneInfo(rules_engine.rules.profile.timezone)

    def plan_today_from_now(
        self,
        month_plan: MonthPlan,
        current_datetime: datetime | None = None,
        bounded_sessions: list[BoundedSessionRequest] | None = None,
    ) -> DailyPlan:
        """Generate today's plan using only future time for flexible work."""

        now = self._aware(current_datetime or datetime.now(self.timezone))
        original = self.scheduler.plan_day(
            month_plan,
            now.date(),
            context_overrides=self._completed_recurring_overrides(
                month_plan, now.date()
            ),
            bounded_sessions=bounded_sessions,
        )
        return self._shift_from_now(original, now)

    def replan_today_from_now(
        self,
        month_plan: MonthPlan,
        current_datetime: datetime | None = None,
        bounded_sessions: list[BoundedSessionRequest] | None = None,
    ) -> DailyPlan:
        """Replan today's remaining flexible blocks; fixed history is preserved."""

        return self.plan_today_from_now(
            month_plan,
            current_datetime,
            bounded_sessions,
        )

    def _shift_from_now(self, plan: DailyPlan, now: datetime) -> DailyPlan:
        fixed_or_future: list[ScheduledBlock] = []
        movable: list[ScheduledBlock] = []
        for block in plan.blocks:
            aware = replace(block, start=self._aware(block.start), end=self._aware(block.end))
            if aware.is_fixed or aware.end > now:
                fixed_or_future.append(aware)
            else:
                movable.append(aware)

        conflicts = list(plan.conflicts)
        cursor = self._round_up(now, 15)
        day_end = datetime.combine(now.date() + timedelta(days=1), time.min, self.timezone)
        sleep_start = time.fromisoformat(self.rules_engine.rules.sleep.start)
        if sleep_start > time.min:
            day_end = datetime.combine(now.date() + timedelta(days=1), sleep_start, self.timezone)

        for block in movable:
            duration = block.end - block.start
            slot = self._next_slot(cursor, duration, fixed_or_future, day_end)
            if slot is None:
                conflicts.append(
                    SchedulingConflict(
                        reason="No remaining time today; spill to tomorrow",
                        item=block.title,
                        date=now.date(),
                        severity="warning",
                    )
                )
                continue
            shifted = replace(
                block,
                start=slot,
                end=slot + duration,
                metadata={**(block.metadata or {}), "replanned_from_now": True},
            )
            fixed_or_future.append(shifted)
            cursor = shifted.end

        return DailyPlan(
            date=plan.date,
            blocks=sorted(fixed_or_future, key=lambda item: (item.start, item.end)),
            conflicts=conflicts,
        )

    def _next_slot(
        self,
        cursor: datetime,
        duration: timedelta,
        blocks: list[ScheduledBlock],
        limit: datetime,
    ) -> datetime | None:
        candidate = cursor
        for block in sorted((item for item in blocks if item.end > cursor), key=lambda item: item.start):
            if candidate + duration <= block.start:
                return candidate
            if candidate < block.end:
                candidate = self._round_up(block.end, 15)
        return candidate if candidate + duration <= limit else None

    def _aware(self, value: datetime) -> datetime:
        return value.replace(tzinfo=self.timezone) if value.tzinfo is None else value.astimezone(self.timezone)

    def _round_up(self, value: datetime, minutes: int) -> datetime:
        remainder = value.minute % minutes
        delta = (minutes - remainder) % minutes
        rounded = value + timedelta(minutes=delta)
        return rounded.replace(second=0, microsecond=0)

    def _completed_recurring_overrides(
        self,
        month_plan: MonthPlan,
        target_date: Any,
    ) -> dict[str, bool]:
        completed_text = " ".join(
            f"{item.name} {item.category or ''}"
            for section in month_plan.week_sections
            for item in section.tasks
            if item.status.value == "done"
            and (
                target_date in item.scheduled_dates
                or target_date.isoformat() in (item.notes or "")
                or "today" in f"{item.name} {item.notes or ''}".casefold()
            )
        ).casefold()
        return {
            "skip_gym_today": "gym" in completed_text,
            "skip_german_today": "german" in completed_text,
            "skip_piano_today": "piano" in completed_text,
            "skip_reading_today": "reading" in completed_text,
        }


def plan_today_from_now(
    month_plan: MonthPlan,
    rules_engine: RulesEngine,
    current_datetime: datetime | None = None,
) -> DailyPlan:
    return CurrentTimePlanner(rules_engine).plan_today_from_now(month_plan, current_datetime)


def replan_today_from_now(
    month_plan: MonthPlan,
    rules_engine: RulesEngine,
    current_datetime: datetime | None = None,
) -> DailyPlan:
    return CurrentTimePlanner(rules_engine).replan_today_from_now(month_plan, current_datetime)
