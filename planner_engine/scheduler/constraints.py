"""Hard rules and protected blocks for Scheduler Engine."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from planner_engine.models import FixedCommitment, ScheduledBlock, SchedulingConflict
from planner_engine.scheduler.durations import ScheduleDemand


class ConstraintsMixin:
    """Build hard-rule demand and protected schedule blocks."""

    def _daily_demands(
        self,
        target_date: date,
        context_overrides: dict[str, Any],
    ) -> list[ScheduleDemand]:
        """Build recurring daily demands."""

        demands = [
            ScheduleDemand(
                title="German study",
                category="german",
                duration_minutes=self.durations["german"],
                source="rules:german",
            ),
            ScheduleDemand(
                title="Piano practice",
                category="piano",
                duration_minutes=self.rules_engine.piano_duration_minutes(),
                source="rules:piano",
            ),
            ScheduleDemand(
                title="Reading",
                category="reading",
                duration_minutes=self.durations["reading"],
                source="rules:reading",
            ),
        ]
        if not context_overrides.get("skip_gym_today"):
            gym_category = "gym_strength"
            if self.rules_engine.is_dance_allowed(target_date.strftime("%A")):
                gym_category = "gym_dance"
            demands.append(
                ScheduleDemand(
                    title="Gym class",
                    category=gym_category,
                    duration_minutes=self.durations["gym_class"],
                    source="rules:gym",
                    metadata={"sessions": 1},
                )
            )
        return demands

    def _add_weekly_recurring_demands(
        self,
        per_day_demands: dict[date, list[ScheduleDemand]],
        context_overrides: dict[str, Any],
        conflicts: list[SchedulingConflict],
    ) -> None:
        """Add recurring rule-driven weekly demand."""

        days = list(per_day_demands)
        for day in days:
            per_day_demands[day].append(
                ScheduleDemand(
                    title="German study",
                    category="german",
                    duration_minutes=self.durations["german"],
                    source="rules:german",
                )
            )
            per_day_demands[day].append(
                ScheduleDemand(
                    title="Piano practice",
                    category="piano",
                    duration_minutes=self.rules_engine.piano_duration_minutes(),
                    source="rules:piano",
                )
            )
            per_day_demands[day].append(
                ScheduleDemand(
                    title="Reading",
                    category="reading",
                    duration_minutes=self.durations["reading"],
                    source="rules:reading",
                )
            )

        for index in (0, 3):
            per_day_demands[days[index]].append(
                ScheduleDemand(
                    title="IELTS study",
                    category="ielts",
                    duration_minutes=self.durations["ielts"],
                    source="rules:ielts",
                )
            )

        for index in (1, 4):
            per_day_demands[days[index]].append(
                ScheduleDemand(
                    title="IGNOU study",
                    category="ignou",
                    duration_minutes=self.durations["ignou"],
                    source="rules:ignou",
                )
            )

        if context_overrides.get("skip_gym_this_week"):
            conflicts.append(
                SchedulingConflict(
                    reason="Impossible weekly gym target: gym skipped by override",
                    item="Gym target",
                    severity="error",
                )
            )
            return

        double_day_offsets = (0, 3, 5)
        single_day_offsets = (1, 2, 4)
        for offset in double_day_offsets:
            day = days[offset]
            if not self.rules_engine.is_dance_allowed(day.strftime("%A")):
                conflicts.append(
                    SchedulingConflict(
                        reason="Dance requested on forbidden day",
                        item="Gym dance class",
                        date=day,
                        severity="error",
                    )
                )
                continue
            per_day_demands[day].append(
                ScheduleDemand(
                    title="Gym strength class",
                    category="gym_strength",
                    duration_minutes=self.durations["gym_class"],
                    source="rules:gym",
                    metadata={"sessions": 1},
                )
            )
            per_day_demands[day].append(
                ScheduleDemand(
                    title="Gym dance class",
                    category="gym_dance",
                    duration_minutes=self.durations["gym_class"],
                    source="rules:gym",
                    metadata={"sessions": 1, "dance": True},
                )
            )

        for offset in single_day_offsets:
            day = days[offset]
            per_day_demands[day].append(
                ScheduleDemand(
                    title="Gym strength class",
                    category="gym_strength",
                    duration_minutes=self.durations["gym_class"],
                    source="rules:gym",
                    metadata={"sessions": 1},
                )
            )

    def _base_blocks_for_day(
        self,
        target_date: date,
        fixed_commitments: list[FixedCommitment],
        conflicts: list[SchedulingConflict],
    ) -> list[ScheduledBlock]:
        """Build sleep, work, and fixed blocks for a day."""

        blocks = [
            self._sleep_block(target_date),
            self._work_block(target_date),
        ]
        blocks = self._resolve_hard_block_overlaps(blocks, conflicts, target_date)

        day_start = datetime.combine(target_date, time.min)
        day_end = day_start + timedelta(days=1)
        for commitment in fixed_commitments:
            if commitment.end <= commitment.start:
                conflicts.append(
                    SchedulingConflict(
                        reason="Task duration exceeding available window",
                        item=commitment.title,
                        date=target_date,
                        severity="error",
                    )
                )
                continue
            if commitment.start < day_end and commitment.end > day_start:
                blocks.append(
                    ScheduledBlock(
                        title=commitment.title,
                        start=commitment.start,
                        end=commitment.end,
                        category=commitment.category,
                        source="fixed_commitment",
                        is_fixed=True,
                        metadata={"notes": commitment.notes},
                    )
                )
        return blocks

    def _resolve_hard_block_overlaps(
        self,
        blocks: list[ScheduledBlock],
        conflicts: list[SchedulingConflict],
        target_date: date,
    ) -> list[ScheduledBlock]:
        """Keep hard blocks non-overlapping while reporting impossible overlaps."""

        sleep_block = next(block for block in blocks if block.category == "sleep")
        work_block = next(block for block in blocks if block.category == "work")
        if not self._blocks_overlap(sleep_block, work_block):
            return blocks

        conflicts.append(
            SchedulingConflict(
                reason="Work hours overlap protected sleep; sleep block adjusted",
                item="sleep/work",
                date=target_date,
                severity="warning",
            )
        )
        if work_block.start <= sleep_block.start < work_block.end:
            adjusted_sleep = ScheduledBlock(
                title=sleep_block.title,
                start=work_block.end,
                end=sleep_block.end,
                category=sleep_block.category,
                source=sleep_block.source,
                is_fixed=sleep_block.is_fixed,
            )
            return [adjusted_sleep, work_block]
        return blocks

    def _sleep_block(self, target_date: date) -> ScheduledBlock:
        """Return protected sleep for a date."""

        sleep_rules = self.rules_engine.rules.sleep
        return ScheduledBlock(
            title="Sleep",
            start=self._datetime_for_rule_time(target_date, sleep_rules.start),
            end=self._datetime_for_rule_time(target_date, sleep_rules.end),
            category="sleep",
            source="rules:sleep",
            is_fixed=True,
        )

    def _work_block(self, target_date: date) -> ScheduledBlock:
        """Return protected work hours for a date."""

        work_rules = self.rules_engine.rules.work
        if target_date.month in (7, 8):
            window = work_rules.july_august
        else:
            window = work_rules.september_onward
        start = self._datetime_for_rule_time(target_date, window.start)
        end = self._datetime_for_rule_time(target_date, window.end)
        if end <= start:
            end += timedelta(days=1)
        return ScheduledBlock(
            title="Work",
            start=start,
            end=end,
            category="work",
            source="rules:work",
            is_fixed=True,
        )

    def _datetime_for_rule_time(self, target_date: date, value: str) -> datetime:
        """Build a datetime from a HH:MM rule value."""

        hour, minute = value.split(":", maxsplit=1)
        return datetime.combine(target_date, time(int(hour), int(minute)))
