"""Authenticated, immutable execution context passed to Planner OS services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo


EXECUTION_TARGETS = frozenset({"google_calendar", "apple_calendar", "none"})


@dataclass(frozen=True)
class PlannerContext:
    """Identify one operation against one owned planner workspace."""

    user_id: UUID
    workspace_id: UUID
    operation_id: UUID
    workbook_path: Path
    timezone: str
    execution_target: str
    source_revision: int
    rules_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workbook_path", Path(self.workbook_path))
        if self.execution_target not in EXECUTION_TARGETS:
            raise ValueError(f"Unsupported execution target: {self.execution_target}")
        if self.source_revision < 0:
            raise ValueError("source_revision cannot be negative")
        ZoneInfo(self.timezone)

