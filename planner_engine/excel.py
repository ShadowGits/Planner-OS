"""Excel workbook storage for Planner Engine."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from shutil import copy2
from typing import Any

from openpyxl import load_workbook as openpyxl_load_workbook
from openpyxl.workbook.workbook import Workbook


class ExcelPlannerStore:
    """Read, write, save, and back up an Excel planner workbook."""

    def __init__(self, planner_path: str | Path, backup_dir: str | Path) -> None:
        self.planner_path = Path(planner_path)
        self.backup_dir = Path(backup_dir)

    def load_workbook(self) -> Workbook:
        """Load the planner workbook with formatting preserved."""

        if not self.planner_path.exists():
            raise FileNotFoundError(f"Planner not found: {self.planner_path}")

        return openpyxl_load_workbook(self.planner_path, data_only=False)

    def save_workbook(self, workbook: Workbook) -> None:
        """Save a workbook back to the planner path."""

        workbook.save(self.planner_path)

    def create_backup(self) -> Path:
        """Create a timestamped copy of the planner workbook."""

        if not self.planner_path.exists():
            raise FileNotFoundError(f"Planner not found: {self.planner_path}")

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"{self.planner_path.stem}_{timestamp}.xlsx"
        copy2(self.planner_path, backup_path)
        return backup_path

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
