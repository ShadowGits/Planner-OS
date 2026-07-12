"""Block allocation and free-slot search for Scheduler Engine."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from planner_engine.models import (
    BoundedSessionRequest,
    Priority,
    ScheduledBlock,
    SchedulingConflict,
)
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

    def _place_bounded_session_requests(
        self,
        target_date: date,
        existing_blocks: list[ScheduledBlock],
        requests: list[BoundedSessionRequest],
    ) -> tuple[list[ScheduledBlock], list[SchedulingConflict]]:
        """Place each bounded request atomically inside its requested window."""

        scheduled: list[ScheduledBlock] = []
        conflicts: list[SchedulingConflict] = []
        for request in requests:
            validation_error = self._bounded_request_error(request, target_date)
            if validation_error:
                conflicts.append(
                    SchedulingConflict(
                        reason=validation_error,
                        item=request.title,
                        date=target_date,
                        severity="error",
                    )
                )
                continue

            provisional: list[ScheduledBlock] = []
            for session_index in range(request.session_count):
                category = self._bounded_session_category(request, session_index)
                demand = ScheduleDemand(
                    title=request.title,
                    category=category,
                    duration_minutes=request.session_duration_minutes,
                    source=request.source,
                    requested_window_start=request.requested_window_start,
                    requested_window_end=request.requested_window_end,
                    hard_window=request.hard_window,
                    metadata={
                        "sessions": 1,
                        "session_index": session_index + 1,
                        "session_count": request.session_count,
                        "gap_minutes": request.gap_minutes,
                        "requested_window_start": (
                            request.requested_window_start.isoformat()
                        ),
                        "requested_window_end": request.requested_window_end.isoformat(),
                        "hard_window": request.hard_window,
                    },
                )
                placed = self._place_one_demand(
                    target_date=target_date,
                    demand=demand,
                    blocks=existing_blocks + scheduled + provisional,
                )
                if placed is None:
                    provisional = []
                    conflicts.append(
                        SchedulingConflict(
                            reason=(
                                f"{request.session_count} sessions of "
                                f"{request.session_duration_minutes} minutes with "
                                f"{request.gap_minutes}-minute gaps cannot fit inside "
                                "the requested window"
                            ),
                            item=request.title,
                            date=target_date,
                            severity="error",
                        )
                    )
                    break
                provisional.append(placed)
            scheduled.extend(provisional)
        return scheduled, conflicts

    def _bounded_request_error(
        self,
        request: BoundedSessionRequest,
        target_date: date,
    ) -> str | None:
        """Return a clear validation or hard-rule error for a bounded request."""

        if request.requested_window_end <= request.requested_window_start:
            return "Requested window end must be after its start"
        if (
            request.requested_window_start.date() != target_date
            or request.requested_window_end.date() != target_date
        ):
            return "Requested window must fall entirely on the target date"
        if request.session_count < 1:
            return "Session count must be at least 1"
        if request.session_duration_minutes < 1:
            return "Session duration must be at least 1 minute"
        if request.gap_minutes < 0:
            return "Gap minutes cannot be negative"
        requested_types = request.allowed_session_types or (request.category,)
        if any("dance" in session_type.casefold() for session_type in requested_types):
            if not self.rules_engine.is_dance_allowed(target_date.strftime("%A")):
                return f"Dance is not allowed on {target_date.strftime('%A')}"
        return None

    def _bounded_session_category(
        self,
        request: BoundedSessionRequest,
        session_index: int,
    ) -> str:
        """Choose an allowed session category deterministically."""

        allowed = request.allowed_session_types
        if not allowed:
            return request.category
        return allowed[session_index % len(allowed)]

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

        metadata = dict(demand.metadata or {})
        source_block_id = f"{demand.source}:{start.date().isoformat()}:{demand.title.casefold()}"
        if "session_index" in metadata:
            source_block_id = f"{source_block_id}:session-{metadata['session_index']}"
        metadata.setdefault("planner_block_id", source_block_id)
        metadata.setdefault("source_task_id", demand.source)
        metadata.setdefault("date", start.date().isoformat())
        metadata.setdefault("start", start.isoformat())
        metadata.setdefault("end", end.isoformat())
        metadata.setdefault("duration", int((end - start).total_seconds() // 60))
        metadata.setdefault("placement_reason", self._placement_reason(demand))
        metadata.setdefault("violated_soft_preferences", [])
        metadata.setdefault(
            "hard_constraint_status",
            "satisfied" if demand.hard_window else "not_applicable",
        )
        metadata.setdefault("resolved_publication_target", "active_execution_target")
        if demand.requested_window_start and demand.requested_window_end:
            metadata.setdefault(
                "requested_window_start",
                demand.requested_window_start.isoformat(),
            )
            metadata.setdefault(
                "requested_window_end",
                demand.requested_window_end.isoformat(),
            )
        return ScheduledBlock(
            title=demand.title,
            start=start,
            end=end,
            category=demand.category,
            source=demand.source,
            priority=demand.priority,
            metadata=metadata,
        )

    def _placement_reason(self, demand: ScheduleDemand) -> str:
        if demand.hard_window:
            return "Placed inside required hard window"
        if demand.requested_window_start and demand.requested_window_end:
            return "Placed inside requested soft window"
        if demand.priority == Priority.HIGH:
            return "Placed early because task priority is high"
        return "Placed in first available preferred window"

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
            if block.metadata and "gap_minutes" in block.metadata:
                end = max(
                    end,
                    block.end
                    + timedelta(minutes=int(block.metadata["gap_minutes"])),
                )
            intervals.append((start, end))
        return sorted(intervals, key=lambda interval: interval[0])

    def _blocks_overlap(self, first: ScheduledBlock, second: ScheduledBlock) -> bool:
        """Return whether two scheduled blocks overlap."""

        return first.start < second.end and second.start < first.end

    def _sort_blocks(self, blocks: list[ScheduledBlock]) -> list[ScheduledBlock]:
        """Sort scheduled blocks chronologically."""

        return sorted(blocks, key=lambda block: (block.start, block.end, block.title))
