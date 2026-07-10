"""Conflict helpers for Scheduler Engine."""

from __future__ import annotations

from planner_engine.models import DailyPlan, FixedCommitment, Priority, SchedulingConflict
from planner_engine.scheduler.durations import ScheduleDemand


class ConflictMixin:
    """Build and aggregate scheduler conflicts."""

    def _fixed_commitment_conflicts(
        self,
        fixed_commitments: list[FixedCommitment],
    ) -> list[SchedulingConflict]:
        """Detect overlapping fixed commitments."""

        conflicts: list[SchedulingConflict] = []
        sorted_commitments = sorted(fixed_commitments, key=lambda item: item.start)
        for index, commitment in enumerate(sorted_commitments):
            for other in sorted_commitments[index + 1 :]:
                if other.start >= commitment.end:
                    break
                conflicts.append(
                    SchedulingConflict(
                        reason="Duplicate fixed commitments overlap",
                        item=f"{commitment.title} / {other.title}",
                        date=commitment.start.date(),
                        severity="error",
                    )
                )
        return conflicts

    def _dance_commitment_conflicts(
        self,
        fixed_commitments: list[FixedCommitment],
    ) -> list[SchedulingConflict]:
        """Detect fixed dance commitments on forbidden days."""

        conflicts: list[SchedulingConflict] = []
        for commitment in fixed_commitments:
            is_dance = (
                "dance" in commitment.category.casefold()
                or "dance" in commitment.title.casefold()
            )
            if is_dance and not self.rules_engine.is_dance_allowed(
                commitment.start.strftime("%A")
            ):
                conflicts.append(
                    SchedulingConflict(
                        reason="Dance requested on forbidden day",
                        item=commitment.title,
                        date=commitment.start.date(),
                        severity="error",
                    )
                )
        return conflicts

    def _validate_weekly_gym_target(
        self,
        days: list[DailyPlan],
        conflicts: list[SchedulingConflict],
    ) -> None:
        """Add a conflict if the weekly gym target was not achieved."""

        sessions = 0
        for day in days:
            for block in day.blocks:
                if block.category.startswith("gym"):
                    sessions += int((block.metadata or {}).get("sessions", 1))
        if sessions != self.rules_engine.required_gym_sessions():
            conflicts.append(
                SchedulingConflict(
                    reason="Impossible weekly gym target",
                    item=(
                        f"Scheduled {sessions} of "
                        f"{self.rules_engine.required_gym_sessions()} gym sessions"
                    ),
                    severity="error",
                )
            )

    def _conflict_reason(self, demand: ScheduleDemand) -> str:
        """Return a structured conflict reason for an unplaced demand."""

        if demand.duration_minutes >= 24 * 60:
            return "Task duration exceeding available window"
        return "Insufficient free time"

    def _conflict_severity(self, demand: ScheduleDemand) -> str:
        """Return conflict severity for an unplaced demand."""

        return "error" if demand.priority == Priority.HIGH else "warning"
