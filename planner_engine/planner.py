"""High-level Planner Engine API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl.workbook.workbook import Workbook

from planner_engine.excel import ExcelPlannerStore
from planner_engine.models import CellUpdate, WriteResult


class PlannerEngine:
    """Coordinate planner operations through the configured store."""

    def __init__(self, store: ExcelPlannerStore) -> None:
        self.store = store

    def load(self) -> Workbook:
        """Load the planner workbook."""

        return self.store.load_workbook()

    def backup(self) -> Path:
        """Create a backup of the planner workbook."""

        return self.store.create_backup()

    def read_cell(self, sheet: str, cell: str) -> Any:
        """Read a value from a planner cell."""

        return self.store.read_cell(sheet, cell)

    def write_cell(self, sheet: str, cell: str, value: Any) -> WriteResult:
        """Back up the planner, then write a value to a cell."""

        update = CellUpdate(sheet=sheet, cell=cell, value=value)
        backup_path = self.backup()
        self.store.write_cell(update.sheet, update.cell, update.value)
        return WriteResult(backup_path=backup_path, update=update)
