"""Schedule workbook-backed dated tasks on their exact dates."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from planner_engine.models import DatedTask, ScheduledBlock, SchedulingConflict, TaskStatus
from planner_engine.rules import RulesEngine


DAYPART_WINDOWS: dict[str, tuple[time, time]] = {
    "morning": (time(9, 30), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(22, 0)),
    "night": (time(22, 0), time(23, 59)),
}


class DatedTaskScheduler:
    """Place flexible dated tasks without changing their assigned date."""

    def __init__(self, rules_engine: RulesEngine) -> None:
        self.timezone = ZoneInfo(rules_engine.rules.profile.timezone)

    def schedule_date(
        self,
        target_date: date,
        tasks: list[DatedTask],
        existing_blocks: list[ScheduledBlock] | None = None,
        current_datetime: datetime | None = None,
    ) -> tuple[list[ScheduledBlock], list[SchedulingConflict]]:
        created: list[ScheduledBlock] = []
        conflicts: list[SchedulingConflict] = []
        occupied = list(existing_blocks or [])
        now = self._aware(current_datetime) if current_datetime else None
        for task in tasks:
            if task.date != target_date or task.status == TaskStatus.DONE:
                continue
            if task.is_fixed:
                start = datetime.combine(target_date, time.fromisoformat(task.start_time), self.timezone)
                end = datetime.combine(target_date, time.fromisoformat(task.end_time), self.timezone)
                block = self._block(task, start, end, True)
                if self._overlaps(block, occupied + created):
                    conflicts.append(SchedulingConflict("Fixed dated task overlaps another block", task.title, target_date, "error"))
                created.append(block)
                continue
            bounds = DAYPART_WINDOWS.get(task.preferred_daypart or "afternoon", DAYPART_WINDOWS["afternoon"])
            start = datetime.combine(target_date, bounds[0], self.timezone)
            limit = datetime.combine(target_date, bounds[1], self.timezone)
            if now and target_date == now.date():
                start = max(start, self._round_up(now, 15))
            duration = timedelta(minutes=task.estimated_minutes)
            slot = self._first_slot(start, limit, duration, occupied + created)
            if slot is None:
                conflicts.append(SchedulingConflict("Dated task cannot fit on its exact date; not moved", task.title, target_date, "error"))
                continue
            created.append(self._block(task, slot, slot + duration, False))
        return created, conflicts

    def _first_slot(self, start: datetime, limit: datetime, duration: timedelta, blocks: list[ScheduledBlock]) -> datetime | None:
        cursor = start
        for block in sorted((item for item in blocks if self._aware(item.end) > start and self._aware(item.start) < limit), key=lambda item: item.start):
            block_start = self._aware(block.start)
            block_end = self._aware(block.end)
            if cursor + duration <= block_start:
                return cursor
            if cursor < block_end:
                cursor = self._round_up(block_end, 15)
        return cursor if cursor + duration <= limit else None

    def _block(self, task: DatedTask, start: datetime, end: datetime, fixed: bool) -> ScheduledBlock:
        return ScheduledBlock(
            title=task.title,
            start=start,
            end=end,
            category=task.category or "dated_task",
            source="workbook_dated_task",
            is_fixed=fixed,
            metadata={
                "dated_task_id": task.id,
                "source_task_id": f"{task.sheet_name}:{task.row_number}",
                "hard_time": task.hard_time,
                "planner_block_id": f"dated-{task.id}",
            },
        )

    def _overlaps(self, candidate: ScheduledBlock, blocks: list[ScheduledBlock]) -> bool:
        return any(candidate.start < self._aware(item.end) and self._aware(item.start) < candidate.end for item in blocks)

    def _aware(self, value: datetime | None) -> datetime:
        if value is None:
            raise ValueError("datetime is required")
        return value.replace(tzinfo=self.timezone) if value.tzinfo is None else value.astimezone(self.timezone)

    def _round_up(self, value: datetime, minutes: int) -> datetime:
        remainder = value.minute % minutes
        return (value + timedelta(minutes=(minutes - remainder) % minutes)).replace(second=0, microsecond=0)
