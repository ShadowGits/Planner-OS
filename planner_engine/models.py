"""Typed models used by the Planner Engine."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
