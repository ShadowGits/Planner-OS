"""Typed models used by the Planner Engine."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    """Known planner task statuses."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"

    @classmethod
    def from_value(cls, value: Any) -> "TaskStatus":
        """Normalize a workbook status value into a typed status."""

        if value is None:
            return cls.UNKNOWN

        normalized = " ".join(str(value).strip().lower().replace("_", " ").split())
        aliases = {
            "not started": cls.NOT_STARTED,
            "todo": cls.NOT_STARTED,
            "to do": cls.NOT_STARTED,
            "pending": cls.NOT_STARTED,
            "in progress": cls.IN_PROGRESS,
            "progress": cls.IN_PROGRESS,
            "doing": cls.IN_PROGRESS,
            "done": cls.DONE,
            "complete": cls.DONE,
            "completed": cls.DONE,
            "blocked": cls.BLOCKED,
        }
        return aliases.get(normalized, cls.UNKNOWN)


class Priority(str, Enum):
    """Known planner priority levels."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"

    @classmethod
    def from_value(cls, value: Any) -> "Priority":
        """Normalize a workbook priority value into a typed priority."""

        if value is None:
            return cls.UNKNOWN

        normalized = " ".join(str(value).strip().lower().split())
        aliases = {
            "high": cls.HIGH,
            "h": cls.HIGH,
            "medium": cls.MEDIUM,
            "med": cls.MEDIUM,
            "m": cls.MEDIUM,
            "low": cls.LOW,
            "l": cls.LOW,
        }
        return aliases.get(normalized, cls.UNKNOWN)


@dataclass(frozen=True)
class MonthlyGoal:
    """A monthly goal row parsed from the planner workbook."""

    name: str
    category: str | None
    priority: Priority
    target_week: str | None
    status: TaskStatus
    notes: str | None
    sheet_name: str
    row_number: int
    cell_references: dict[str, str]
    raw_priority: str | None = None
    raw_status: str | None = None


@dataclass(frozen=True)
class PlannerTask:
    """A weekly planner task parsed from the workbook."""

    name: str
    category: str | None
    priority: Priority
    status: TaskStatus
    notes: str | None
    sheet_name: str
    row_number: int
    week_name: str
    cell_references: dict[str, str]
    raw_priority: str | None = None
    raw_status: str | None = None


@dataclass(frozen=True)
class WeekSection:
    """A weekly section and its parsed task rows."""

    name: str
    title: str
    sheet_name: str
    heading_row: int
    header_row: int
    start_row: int
    end_row: int
    tasks: list[PlannerTask]
    cell_references: dict[str, str]


@dataclass(frozen=True)
class MonthPlan:
    """A parsed monthly planner sheet."""

    month: str
    sheet_name: str
    monthly_goals: list[MonthlyGoal]
    week_sections: list[WeekSection]


@dataclass(frozen=True)
class CellUpdate:
    """A single workbook cell update request."""

    sheet: str
    cell: str
    value: Any


@dataclass(frozen=True)
class WriteResult:
    """Result metadata for a completed workbook write."""

    backup_path: Path
    update: CellUpdate
