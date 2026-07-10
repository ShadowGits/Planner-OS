"""Typed models used by the Planner Engine."""

from dataclasses import dataclass
from datetime import date, datetime
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
class FixedCommitment:
    """An immovable calendar commitment supplied to the scheduler."""

    title: str
    start: datetime
    end: datetime
    category: str = "fixed"
    notes: str | None = None


@dataclass(frozen=True)
class SchedulingConflict:
    """A structured scheduling issue that needs attention."""

    reason: str
    item: str
    date: date | None = None
    severity: str = "warning"


@dataclass(frozen=True)
class ScheduledBlock:
    """A scheduled time block in a daily or weekly plan."""

    title: str
    start: datetime
    end: datetime
    category: str
    source: str
    is_fixed: bool = False
    priority: Priority = Priority.UNKNOWN
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class DailyPlan:
    """A scheduled plan for one date."""

    date: date
    blocks: list[ScheduledBlock]
    conflicts: list[SchedulingConflict]


@dataclass(frozen=True)
class WeeklyPlan:
    """A scheduled plan for a week."""

    week_start: date
    days: list[DailyPlan]
    conflicts: list[SchedulingConflict]


@dataclass(frozen=True)
class SchedulingRequest:
    """Inputs for producing a day or week schedule."""

    month_plan: MonthPlan
    target_date: date | None = None
    target_week_start: date | None = None
    fixed_commitments: list[FixedCommitment] | None = None
    context_overrides: dict[str, Any] | None = None
    unfinished_tasks: list[PlannerTask | MonthlyGoal] | None = None


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
