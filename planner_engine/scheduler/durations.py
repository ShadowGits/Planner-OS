"""Default duration configuration for scheduler demand."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from planner_engine.models import Priority


DEFAULT_DURATIONS_MINUTES: dict[str, int] = {
    "buffer": 15,
    "german": 45,
    "ielts": 90,
    "ignou": 90,
    "piano": 60,
    "reading": 30,
    "gym_class": 60,
    "planner_task": 60,
    "monthly_goal": 90,
}


@dataclass(frozen=True)
class ScheduleDemand:
    """A movable item that the scheduler should place."""

    title: str
    category: str
    duration_minutes: int
    source: str
    priority: Priority = Priority.UNKNOWN
    metadata: dict[str, Any] | None = None
    requested_window_start: datetime | None = None
    requested_window_end: datetime | None = None
    hard_window: bool = False


def merged_durations(overrides: dict[str, int] | None = None) -> dict[str, int]:
    """Return default durations with optional caller overrides."""

    durations = dict(DEFAULT_DURATIONS_MINUTES)
    if overrides:
        durations.update(overrides)
    return durations
