"""Unambiguous date-parameterized calendar synchronization commands."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from planner_engine.date_utils import (
    current_week_range,
    month_bounds,
    next_week_range,
    workbook_week_range,
)
from planner_engine.dated_task_scheduler import DatedTaskScheduler
from planner_engine.models import DailyPlan
from planner_engine.models import WeeklyPlan
from planner_engine.planner import PlannerEngine
from planner_engine.rules import RulesEngine
from planner_engine.scheduler import SchedulerEngine
from planner_integrations.google_calendar import CalendarSyncResult, GoogleCalendarClient


@dataclass(frozen=True)
class ParameterizedSyncResult:
    success: bool
    message: str
    start_date: str
    end_date: str
    scope: str
    created: int
    updated: int
    deleted: int
    unchanged: int
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CalendarSyncService:
    """Generate and sync only explicitly named or bounded planner ranges."""

    def __init__(
        self,
        engine: PlannerEngine,
        rules_engine: RulesEngine,
        client: GoogleCalendarClient,
        scheduler: SchedulerEngine | None = None,
    ) -> None:
        self.engine = engine
        self.rules_engine = rules_engine
        self.client = client
        self.scheduler = scheduler or SchedulerEngine(rules_engine)

    def calendar_sync_current_week(self, today: date | None = None) -> ParameterizedSyncResult:
        start, end = current_week_range(today or date.today())
        return self._sync_range(start, end, "current week")

    def calendar_sync_next_week(self, today: date | None = None) -> ParameterizedSyncResult:
        start, end = next_week_range(today or date.today())
        return self._sync_range(start, end, "next week")

    def calendar_sync_week_number(self, month: str, week_number: int) -> ParameterizedSyncResult:
        start, end = workbook_week_range(self.engine.get_month_plan(month), week_number)
        return self._sync_range(start, end, f"{month} week {week_number}")

    def calendar_sync_range(self, start_date: date, end_date: date) -> ParameterizedSyncResult:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        return self._sync_range(start_date, end_date, "date range")

    def calendar_sync_date(self, target_date: date) -> ParameterizedSyncResult:
        """Sync exactly one date, including workbook-backed dated tasks."""

        return self._sync_range(target_date, target_date, "date")

    def calendar_sync_month(self, month: str) -> ParameterizedSyncResult:
        start, end = month_bounds(month)
        return self._sync_range(start, end, month)

    def calendar_sync_week(self, today: date | None = None) -> ParameterizedSyncResult:
        """Backward-compatible alias that explicitly means current week."""

        return self.calendar_sync_current_week(today)

    def _sync_range(self, start: date, end: date, scope: str) -> ParameterizedSyncResult:
        days = []
        cursor = start
        while cursor <= end:
            month = cursor.strftime("%b %Y")
            month_plan = self.engine.get_month_plan(month)
            day_plan = self.scheduler.plan_day(month_plan, cursor)
            dated = self.engine.list_dated_tasks(month, cursor)
            dated_blocks, dated_conflicts = DatedTaskScheduler(
                self.rules_engine
            ).schedule_date(cursor, dated, day_plan.blocks)
            dated_categories = {
                block.category.casefold()
                for block in dated_blocks
                if block.category
            }
            base_blocks = [
                block
                for block in day_plan.blocks
                if block.is_fixed
                or block.category.casefold() not in dated_categories
            ]
            days.append(
                DailyPlan(
                    date=cursor,
                    blocks=[*base_blocks, *dated_blocks],
                    conflicts=[*day_plan.conflicts, *dated_conflicts],
                )
            )
            cursor += timedelta(days=1)
        plan = WeeklyPlan(
            week_start=start,
            days=days,
            conflicts=[conflict for day in days for conflict in day.conflicts],
        )
        result = self.client.sync_plan(plan, start=start, end=end, scope=scope)
        label = scope[0].upper() + scope[1:]
        return ParameterizedSyncResult(
            success=result.success,
            message=f"Synced {scope}: {start.isoformat()} to {end.isoformat()}",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            scope=label,
            created=result.created,
            updated=result.updated,
            deleted=result.deleted,
            unchanged=result.unchanged,
            warnings=result.warnings,
            errors=result.errors,
        )
