"""Workbook storage port."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from planner_platform.context import PlannerContext


@dataclass(frozen=True)
class WorkbookRevision:
    number: int
    checksum: str
    path: Path


class WorkbookRepository(Protocol):
    def current(self, context: PlannerContext) -> WorkbookRevision: ...

    def create_backup(self, context: PlannerContext) -> Path: ...

