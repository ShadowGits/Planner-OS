"""Deterministic capacity calculations for Planner OS planning proposals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from planner_engine.models import FixedCommitment, ScheduledBlock
from planner_engine.rules import RulesEngine


DAYPARTS: dict[str, tuple[time, time]] = {
    "morning": (time(6, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(22, 0)),
    "night": (time(22, 0), time(23, 59, 59)),
}


@dataclass(frozen=True)
class CapacityRequest:
    """Inputs for calculating usable planning capacity."""

    start_date: date
    end_date: date
    required_minutes: int = 0
    fixed_commitments: tuple[FixedCommitment, ...] = ()
    scheduled_blocks: tuple[ScheduledBlock, ...] = ()
    preferred_study_windows: dict[str, tuple[str, str]] | None = None
    current_datetime: datetime | None = None
    from_now: bool = False
    hard_window_tasks: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CapacityReport:
    """Available capacity and feasibility for a date range."""

    start_date: date
    end_date: date
    total_available_minutes: int
    available_minutes_by_day: dict[str, int]
    available_minutes_by_daypart: dict[str, dict[str, int]]
    required_minutes: int
    overload_minutes: int
    feasibility_status: str
    conflicts: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["start_date"] = self.start_date.isoformat()
        data["end_date"] = self.end_date.isoformat()
        return data


class CapacityEngine:
    """Calculate free waking time after work and fixed commitments."""

    def __init__(self, rules_engine: RulesEngine) -> None:
        self.rules_engine = rules_engine
        self.timezone = ZoneInfo(rules_engine.rules.profile.timezone)

    def calculate(self, request: CapacityRequest) -> CapacityReport:
        """Calculate deterministic capacity without mutating planner state."""

        if request.end_date < request.start_date:
            raise ValueError("end_date must be on or after start_date")
        current = self._aware(request.current_datetime) if request.current_datetime else None
        by_day: dict[str, int] = {}
        by_daypart: dict[str, dict[str, int]] = {}
        conflicts: list[str] = []

        cursor = request.start_date
        while cursor <= request.end_date:
            intervals = self._waking_intervals(cursor)
            if self.rules_engine.is_work_day(cursor.strftime("%A")):
                intervals = self._subtract(intervals, [self._work_interval(cursor)])
            preferred_window = self._preferred_window(
                request.preferred_study_windows,
                cursor,
            )
            if preferred_window is not None:
                intervals = self._intersect_window(intervals, cursor, preferred_window)
            occupied = [
                (item.start, item.end)
                for item in (*request.fixed_commitments, *request.scheduled_blocks)
                if item.start.date() <= cursor <= item.end.date()
            ]
            intervals = self._subtract(intervals, occupied)
            if request.from_now and current and cursor == current.date():
                intervals = [(max(start, current), end) for start, end in intervals if end > current]
                intervals = [(start, end) for start, end in intervals if end > start]
            if current and cursor < current.date():
                intervals = []

            key = cursor.isoformat()
            by_day[key] = self._minutes(intervals)
            by_daypart[key] = {
                name: self._minutes(self._intersect_daypart(intervals, cursor, bounds))
                for name, bounds in DAYPARTS.items()
            }
            cursor += timedelta(days=1)

        for task in request.hard_window_tasks:
            task_date = self._as_date(task.get("date"))
            required = int(task.get("estimated_minutes", 0))
            daypart = str(task.get("preferred_daypart", "")).casefold()
            available = by_daypart.get(task_date.isoformat(), {}).get(daypart, 0)
            if required > available:
                conflicts.append(
                    f"{task.get('task_title', 'Hard-window task')} cannot fit in "
                    f"{daypart or 'requested window'} on {task_date.isoformat()}"
                )

        total = sum(by_day.values())
        overload = max(0, request.required_minutes - total)
        status = self._status(request.required_minutes, total, overload, len(by_day))
        suggestions: list[str] = []
        if overload:
            suggestions.append(f"Move at least {overload} minutes to a later day or week")
        if conflicts:
            suggestions.append("Move hard-window tasks or free the requested daypart")
        if status == "tight":
            suggestions.append("Keep low-priority tasks flexible and protect buffer time")
        if status in {"spillover", "impossible"}:
            suggestions.append("Deprioritize optional work or extend the planning range")

        return CapacityReport(
            start_date=request.start_date,
            end_date=request.end_date,
            total_available_minutes=total,
            available_minutes_by_day=by_day,
            available_minutes_by_daypart=by_daypart,
            required_minutes=request.required_minutes,
            overload_minutes=overload,
            feasibility_status=("spillover" if conflicts and status == "ok" else status),
            conflicts=conflicts,
            suggestions=suggestions,
        )

    def calculate_capacity(self, request: CapacityRequest) -> CapacityReport:
        """Compatibility alias with an explicit product-layer name."""

        return self.calculate(request)

    def _waking_intervals(self, day: date) -> list[tuple[datetime, datetime]]:
        sleep_start = self._clock(self.rules_engine.rules.sleep.start)
        sleep_end = self._clock(self.rules_engine.rules.sleep.end)
        day_start = datetime.combine(day, time.min, self.timezone)
        day_end = datetime.combine(day + timedelta(days=1), time.min, self.timezone)
        sleep_intervals: list[tuple[datetime, datetime]] = []
        if sleep_start <= sleep_end:
            sleep_intervals.append(
                (datetime.combine(day, sleep_start, self.timezone), datetime.combine(day, sleep_end, self.timezone))
            )
        else:
            sleep_intervals.extend(
                [
                    (day_start, datetime.combine(day, sleep_end, self.timezone)),
                    (datetime.combine(day, sleep_start, self.timezone), day_end),
                ]
            )
        return self._subtract([(day_start, day_end)], sleep_intervals)

    def _work_interval(self, day: date) -> tuple[datetime, datetime]:
        rules = (
            self.rules_engine.rules.work.july_august
            if day.month in {7, 8}
            else self.rules_engine.rules.work.september_onward
        )
        start = datetime.combine(day, self._clock(rules.start), self.timezone)
        end = datetime.combine(day, self._clock(rules.end), self.timezone)
        if end <= start:
            end += timedelta(days=1)
        return start, end

    def _subtract(
        self,
        intervals: Iterable[tuple[datetime, datetime]],
        occupied: Iterable[tuple[datetime, datetime]],
    ) -> list[tuple[datetime, datetime]]:
        result = list(intervals)
        for busy_start, busy_end in occupied:
            busy_start = self._aware(busy_start)
            busy_end = self._aware(busy_end)
            next_result: list[tuple[datetime, datetime]] = []
            for start, end in result:
                if busy_end <= start or busy_start >= end:
                    next_result.append((start, end))
                    continue
                if start < busy_start:
                    next_result.append((start, min(end, busy_start)))
                if busy_end < end:
                    next_result.append((max(start, busy_end), end))
            result = next_result
        return [(start, end) for start, end in result if end > start]

    def _intersect_daypart(
        self,
        intervals: list[tuple[datetime, datetime]],
        day: date,
        bounds: tuple[time, time],
    ) -> list[tuple[datetime, datetime]]:
        part_start = datetime.combine(day, bounds[0], self.timezone)
        part_end = datetime.combine(day, bounds[1], self.timezone)
        return [
            (max(start, part_start), min(end, part_end))
            for start, end in intervals
            if min(end, part_end) > max(start, part_start)
        ]

    def _intersect_window(
        self,
        intervals: list[tuple[datetime, datetime]],
        day: date,
        bounds: tuple[str, str],
    ) -> list[tuple[datetime, datetime]]:
        window_start = datetime.combine(day, self._clock(bounds[0]), self.timezone)
        window_end = datetime.combine(day, self._clock(bounds[1]), self.timezone)
        if window_end <= window_start:
            window_end += timedelta(days=1)
        return [
            (max(start, window_start), min(end, window_end))
            for start, end in intervals
            if min(end, window_end) > max(start, window_start)
        ]

    def _preferred_window(
        self,
        windows: dict[str, tuple[str, str]] | None,
        day: date,
    ) -> tuple[str, str] | None:
        if not windows:
            return None
        candidates = (
            day.isoformat(),
            day.strftime("%A"),
            day.strftime("%A").casefold(),
            "default",
        )
        for key in candidates:
            if key in windows:
                return windows[key]
        return None

    def _minutes(self, intervals: Iterable[tuple[datetime, datetime]]) -> int:
        return sum(max(0, int((end - start).total_seconds() // 60)) for start, end in intervals)

    def _status(self, required: int, available: int, overload: int, days: int) -> str:
        if required <= 0:
            return "ok"
        if available <= 0:
            return "impossible"
        if overload > max(240, available // 2):
            return "impossible"
        if overload:
            return "spillover"
        buffer = available - required
        return "tight" if buffer < max(120, days * 30) else "ok"

    def _aware(self, value: datetime) -> datetime:
        return value.replace(tzinfo=self.timezone) if value.tzinfo is None else value.astimezone(self.timezone)

    def _clock(self, value: str) -> time:
        return time.fromisoformat(value)

    def _as_date(self, value: Any) -> date:
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))
