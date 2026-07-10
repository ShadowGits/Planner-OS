"""Low-level workbook orchestration for Excel Planner Store."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from shutil import copy2
from typing import Any

from openpyxl import load_workbook as openpyxl_load_workbook
from openpyxl.workbook.workbook import Workbook

from planner_engine.excel.layout import LayoutMixin, SheetLayout
from planner_engine.excel.reader import ReaderMixin
from planner_engine.excel.writer import WriterMixin


class ExcelPlannerStore(WriterMixin, ReaderMixin, LayoutMixin):
    """Read, write, save, and back up an Excel planner workbook."""

    def __init__(self, planner_path: str | Path, backup_dir: str | Path) -> None:
        self.planner_path = Path(planner_path)
        self.backup_dir = Path(backup_dir)
        self._sheet_layout_cache: dict[str, SheetLayout] = {}

    def load_workbook(self) -> Workbook:
        """Load the planner workbook with formatting preserved."""

        if not self.planner_path.exists():
            raise FileNotFoundError(f"Planner not found: {self.planner_path}")

        return openpyxl_load_workbook(self.planner_path, data_only=False)

    def load_workbook_read_only(self) -> Workbook:
        """Load the planner workbook for read-only parsing."""

        if not self.planner_path.exists():
            raise FileNotFoundError(f"Planner not found: {self.planner_path}")

        return openpyxl_load_workbook(
            self.planner_path,
            read_only=True,
            data_only=False,
        )

    def save_workbook(self, workbook: Workbook) -> None:
        """Save a workbook back to the planner path."""

        workbook.save(self.planner_path)

    def create_backup(self) -> Path:
        """Create a collision-safe timestamped copy of the planner workbook."""

        if not self.planner_path.exists():
            raise FileNotFoundError(f"Planner not found: {self.planner_path}")

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = self.backup_dir / f"{self.planner_path.stem}_{timestamp}.xlsx"
        suffix = 1
        while backup_path.exists():
            backup_path = (
                self.backup_dir
                / f"{self.planner_path.stem}_{timestamp}_{suffix}.xlsx"
            )
            suffix += 1
        copy2(self.planner_path, backup_path)
        return backup_path

    def restore_backup(self, backup_path: str | Path) -> None:
        """Restore the planner workbook from a backup copy."""

        copy2(Path(backup_path), self.planner_path)

    def read_cell(self, sheet: str, cell: str) -> Any:
        """Read a value from a worksheet cell."""

        workbook = self.load_workbook()
        try:
            worksheet = workbook[sheet]
            return worksheet[cell].value
        finally:
            workbook.close()

    def write_cell(self, sheet: str, cell: str, value: Any) -> None:
        """Write a value to a worksheet cell and save the workbook."""

        workbook = self.load_workbook()
        try:
            worksheet = workbook[sheet]
            worksheet[cell].value = value
            self.save_workbook(workbook)
        finally:
            workbook.close()

    def write_cells(self, updates: list[tuple[str, str, Any]]) -> None:
        """Write multiple worksheet cells in one workbook save."""

        workbook = self.load_workbook()
        try:
            for sheet, cell, value in updates:
                workbook[sheet][cell].value = value
            self.save_workbook(workbook)
        finally:
            workbook.close()
