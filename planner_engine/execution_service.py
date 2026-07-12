"""Generate planner blocks and publish through the one active target."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from planner_engine.dated_task_scheduler import DatedTaskScheduler
from planner_engine.execution_manager import ExecutionManager
from planner_engine.models import ScheduledBlock
from planner_engine.planner import PlannerEngine
from planner_engine.rules import RulesEngine
from planner_engine.scheduler import SchedulerEngine


@dataclass(frozen=True)
class ExecutionPublishResponse:
    success: bool
    message: str
    active_target: str
    start_date: str
    end_date: str
    workbook_changes: int
    external_changes: dict[str, Any]
    publication_skipped: bool
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionPublishingService:
    def __init__(self, engine: PlannerEngine, rules: RulesEngine, manager: ExecutionManager, scheduler: SchedulerEngine | None = None) -> None:
        self.engine = engine
        self.rules = rules
        self.manager = manager
        self.scheduler = scheduler or SchedulerEngine(rules)

    def publish_today(self, today: date | None = None) -> ExecutionPublishResponse:
        target = today or date.today()
        return self.publish_range(target, target)

    def publish_date(self, target: date) -> ExecutionPublishResponse:
        return self.publish_range(target, target)

    def publish_current_week(self, today: date | None = None) -> ExecutionPublishResponse:
        current = today or date.today()
        start = current - timedelta(days=current.weekday())
        return self.publish_range(start, start + timedelta(days=6))

    def publish_range(self, start: date, end: date) -> ExecutionPublishResponse:
        if end < start:
            raise ValueError("end date must not precede start date")
        blocks = self.blocks_for_range(start, end)
        result = self.manager.publish_blocks(blocks)
        active = self.manager.get_active_execution_target()
        skipped = active == "none"
        message = f"Published {start.isoformat()} to {end.isoformat()} using {active}" if not skipped else "Workbook plan retained; external publication skipped"
        return ExecutionPublishResponse(result.success, message, active, start.isoformat(), end.isoformat(), 0, result.to_dict(), skipped, result.warnings, result.errors)

    def blocks_for_range(self, start: date, end: date) -> list[ScheduledBlock]:
        if end < start:
            raise ValueError("end date must not precede start date")
        blocks: list[ScheduledBlock] = []
        cursor = start
        while cursor <= end:
            month = cursor.strftime("%b %Y")
            day = self.scheduler.plan_day(self.engine.get_month_plan(month), cursor)
            dated, _ = DatedTaskScheduler(self.rules).schedule_date(cursor, self.engine.list_dated_tasks(month, cursor), day.blocks)
            dated_source_task_ids = {
                str((block.metadata or {}).get("source_task_id"))
                for block in dated
                if (block.metadata or {}).get("source_task_id")
            }
            blocks.extend([
                block
                for block in day.blocks
                if block.is_fixed
                or str((block.metadata or {}).get("source_task_id"))
                not in dated_source_task_ids
            ])
            blocks.extend(dated)
            cursor += timedelta(days=1)
        return blocks
