"""Block allocation and free-slot search for Scheduler Engine."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from planner_engine.models import Priority, ScheduledBlock, SchedulingConflict
from planner_engine.scheduler.durations import ScheduleDemand


class AllocatorMixin:
    """Place movable blocks into non-overlapping free slots."""

    def _place_demands_for_day(
        self,
        target_date: date,
        existing_blocks: list[ScheduledBlock],
        demands: list[ScheduleDemand],
    ) -> tuple[list[ScheduledBlock], list[SchedulingConflict]]:
        """Place movable demands into available day windows."""

        scheduled: list[ScheduledBlock] = []
        conflicts: list[SchedulingConflict] = []
        ordered_demands = sorted(
            demands,
            key=lambda demand: (
                self._category_order(demand.category),
                0 if demand.priority == Priority.HIGH else 1,
            ),
        )
        for demand in ordered_demands:
            placed = self._place_one_demand(
                target_date=target_date,
                demand=demand,
                blocks=existing_blocks + scheduled,
            )
            if placed is None:
                conflicts.append(
                    SchedulingConflict(
                        reason=self._conflict_reason(demand),
                        item=demand.title,
                        date=target_date,
                        severity=self._conflict_severity(demand),
                    )
                )
            else:
                scheduled.append(placed)
        return scheduled, conflicts

    def _place_one_demand(
        self,
        target_date: date,
        demand: ScheduleDemand,
        blocks: list[ScheduledBlock],
    ) -> ScheduledBlock | None:
        """Place one demand in its preferred windows, then any free window."""

        duration = timedelta(minutes=demand.duration_minutes)
        if duration >= timedelta(days=1):
            return None

        for window_start, window_end in self._preferred_windows(target_date, demand):
            placement = self._first_fit(
                demand=demand,
                duration=duration,
                blocks=blocks,
                window_start=window_start,
                window_end=window_end,
            )
            if placement is not None:
                return placement
        return None

    def _first_fit(
        self,
        demand: ScheduleDemand,
        duration: timedelta,
        blocks: list[ScheduledBlock],
        window_start: datetime,
        window_end: datetime,
    ) -> ScheduledBlock | None:
        """Find the first non-overlapping placement in a window."""

        occupied = self._occupied_intervals(blocks)
        cursor = window_start
        for start, end in occupied:
            if end <= cursor:
                continue
            if start >= window_end:
                break
            if cursor + duration <= min(start, window_end):
                return self._scheduled_block(demand, cursor, cursor + duration)
            if end > cursor:
                cursor = end
        if cursor + duration <= window_end:
            return self._scheduled_block(demand, cursor, cursor + duration)
        return None

    def _scheduled_block(
        self,
        demand: ScheduleDemand,
        start: datetime,
        end: datetime,
    ) -> ScheduledBlock:
        """Create a scheduled block from demand."""

        return ScheduledBlock(
            title=demand.title,
            start=start,
            end=end,
            category=demand.category,
            source=demand.source,
            priority=demand.priority,
            metadata=demand.metadata,
        )

    def _occupied_intervals(
        self,
        blocks: list[ScheduledBlock],
    ) -> list[tuple[datetime, datetime]]:
        """Return sorted occupied intervals, with buffers where needed."""

        buffer = timedelta(minutes=self.durations["buffer"])
        intervals: list[tuple[datetime, datetime]] = []
        for block in blocks:
            start = block.start
            end = block.end
            if block.is_fixed or block.category.startswith("gym"):
                start -= buffer
                end += buffer
            intervals.append((start, end))
        return sorted(intervals, key=lambda interval: interval[0])

    def _blocks_overlap(self, first: ScheduledBlock, second: ScheduledBlock) -> bool:
        """Return whether two scheduled blocks overlap."""

        return first.start < second.end and second.start < first.end

    def _sort_blocks(self, blocks: list[ScheduledBlock]) -> list[ScheduledBlock]:
        """Sort scheduled blocks chronologically."""

        return sorted(blocks, key=lambda block: (block.start, block.end, block.title))
