"""Distribute weekly milestones across actual dates without writing state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from planner_engine.monthly_planner import DailyTaskProposal, WeeklyMilestone
from planner_engine.rules import RulesEngine


@dataclass(frozen=True)
class DailyDistributionResult:
    tasks: list[DailyTaskProposal]
    warnings: list[str] = field(default_factory=list)
    spillover_units: int = 0


class DailyDistributor:
    """Spread recurring and flexible milestone units across allowed days."""

    def __init__(self, rules_engine: RulesEngine, daily_limit_minutes: int = 360) -> None:
        self.rules_engine = rules_engine
        self.daily_limit_minutes = daily_limit_minutes

    def distribute(
        self,
        milestones: list[WeeklyMilestone],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        current_datetime: datetime | None = None,
        from_now: bool = False,
    ) -> DailyDistributionResult:
        """Return balanced task proposals and explicit spillover warnings."""

        tasks: list[DailyTaskProposal] = []
        warnings: list[str] = []
        used: dict[date, int] = {}
        spillover = 0

        for milestone in sorted(milestones, key=lambda item: (item.week_number, item.priority != "high", item.goal_name)):
            range_start = max(milestone.start_date, start_date or milestone.start_date)
            range_end = min(milestone.end_date, end_date or milestone.end_date)
            candidates = self._candidate_days(milestone, range_start, range_end, current_datetime, from_now)
            session_count, duration = self._sessions(milestone, len(candidates))
            selected = self._select_days(milestone, candidates, session_count)
            placed = 0
            for index, day in enumerate(selected, start=1):
                if used.get(day, 0) + duration > self.daily_limit_minutes:
                    continue
                title = self._task_title(milestone, index, session_count)
                tasks.append(
                    DailyTaskProposal(
                        date=day,
                        week_number=milestone.week_number,
                        task_title=title,
                        category=milestone.category or "Planning",
                        estimated_minutes=duration,
                        source_goal=milestone.goal_name,
                        priority=milestone.priority,
                        flexible=milestone.flexible,
                        preferred_daypart=milestone.preferred_daypart,
                    )
                )
                used[day] = used.get(day, 0) + duration
                placed += 1
            missing = max(0, session_count - placed)
            if missing:
                spillover += missing
                warnings.append(f"{milestone.goal_name}: {missing} session(s) spilled over")

        return DailyDistributionResult(tasks=sorted(tasks, key=lambda item: (item.date, item.task_title)), warnings=warnings, spillover_units=spillover)

    def _candidate_days(
        self,
        milestone: WeeklyMilestone,
        start: date,
        end: date,
        current: datetime | None,
        from_now: bool,
    ) -> list[date]:
        if end < start:
            return []
        days: list[date] = []
        cursor = start
        while cursor <= end:
            if current and cursor < current.date():
                cursor += timedelta(days=1)
                continue
            text = f"{milestone.goal_name} {milestone.category or ''}".casefold()
            if "work" in text and not self.rules_engine.is_work_day(cursor.strftime("%A")):
                cursor += timedelta(days=1)
                continue
            if "dance" in text and not self.rules_engine.is_dance_allowed(cursor.strftime("%A")):
                cursor += timedelta(days=1)
                continue
            if from_now and current and cursor == current.date() and current.hour >= 23:
                cursor += timedelta(days=1)
                continue
            days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def _sessions(self, milestone: WeeklyMilestone, day_count: int) -> tuple[int, int]:
        cadence = milestone.cadence or "sessions"
        if cadence == "daily":
            count = min(day_count, milestone.units_planned)
        elif cadence == "gym":
            count = milestone.units_planned
        elif cadence == "weekly_sessions":
            count = milestone.units_planned
        else:
            count = max(1, milestone.units_planned)
        duration = max(15, milestone.estimated_minutes // max(1, milestone.units_planned))
        return count, duration

    def _select_days(self, milestone: WeeklyMilestone, days: list[date], count: int) -> list[date]:
        if not days or count <= 0:
            return []
        if milestone.cadence == "daily":
            return days[:count]
        if milestone.cadence == "gym" and count == 9 and len(days) >= 6:
            singles = days[:3]
            doubles = days[3:6]
            return singles + [day for day in doubles for _ in range(2)]
        if count >= len(days):
            return [days[index % len(days)] for index in range(count)]
        if count == 1:
            return [days[len(days) // 2]]
        indexes = [round(index * (len(days) - 1) / (count - 1)) for index in range(count)]
        return [days[index] for index in indexes]

    def _task_title(self, milestone: WeeklyMilestone, index: int, count: int) -> str:
        if count == 1:
            return milestone.goal_name
        return f"{milestone.goal_name} ({index}/{count})"

