"""High-level Planner Engine API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl.workbook.workbook import Workbook

from planner_engine.excel import ExcelPlannerStore
from planner_engine.models import (
    CellUpdate,
    MonthPlan,
    MonthlyGoal,
    PlannerTask,
    WeekSection,
    WriteResult,
)


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

    def append_monthly_goals(
        self,
        month: str,
        goals: list[dict[str, Any]],
    ) -> int:
        """Append monthly goals without creating a backup."""

        return self.store.append_monthly_goals(month, goals)

    def append_weekly_tasks(
        self,
        month: str,
        week_tasks: list[dict[str, Any]],
    ) -> int:
        """Append weekly tasks without creating a backup."""

        return self.store.append_weekly_tasks(month, week_tasks)

    def list_months(self) -> list[str]:
        """List available planner months."""

        return self.store.list_months()

    def get_month_plan(self, month: str) -> MonthPlan:
        """Read a parsed month plan."""

        return self.store.read_month_plan(month)

    def get_monthly_goals(self, month: str) -> list[MonthlyGoal]:
        """Read parsed monthly goals."""

        return self.store.read_monthly_goals(month)

    def get_week_sections(self, month: str) -> list[WeekSection]:
        """Read parsed weekly sections."""

        return self.store.read_week_sections(month)

    def find_task(self, month: str, task_name: str) -> PlannerTask | MonthlyGoal | None:
        """Find a task or goal by case-insensitive name."""

        return self.store.find_task(month, task_name)
