"""Semantic write support for Excel planner workbooks."""

from __future__ import annotations

from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from planner_engine.excel.layout import PlannerWorkbookError


class WriterMixin:
    """Append planner concepts to workbook sections."""

    def append_monthly_goals(
        self,
        month: str,
        goals: list[dict[str, Any]],
    ) -> int:
        """Back up the workbook, then append monthly goal rows."""

        if not goals:
            return 0

        self.create_backup()
        return self._append_monthly_goals_without_backup(month, goals)

    def _append_monthly_goals_without_backup(
        self,
        month: str,
        goals: list[dict[str, Any]],
    ) -> int:
        """Append monthly goal rows after backup safety has been handled."""

        workbook = self.load_workbook()
        try:
            worksheet = self._get_month_worksheet(workbook, month)
            header_row, end_row, header_map = self._monthly_goal_table(worksheet)
            task_column = self._required_column(
                header_map,
                ("GOAL / TASK", "TASK / GOAL"),
            )
            rows = self._blank_rows(
                worksheet=worksheet,
                task_column=task_column,
                start_row=header_row + 1,
                end_row=end_row,
                count=len(goals),
            )
            for row_number, goal in zip(rows, goals):
                self._write_row_values(
                    worksheet,
                    row_number,
                    header_map,
                    {
                        "GOAL / TASK": goal.get("goal"),
                        "CATEGORY": goal.get("category"),
                        "PRIORITY": goal.get("priority"),
                        "TARGET WEEK": goal.get("target_week"),
                        "STATUS": goal.get("status"),
                        "NOTES": goal.get("notes"),
                    },
                )
            self.save_workbook(workbook)
            return len(goals)
        finally:
            workbook.close()

    def append_weekly_tasks(
        self,
        month: str,
        week_tasks: list[dict[str, Any]],
    ) -> int:
        """Back up the workbook, then append weekly task rows."""

        if not week_tasks:
            return 0

        self.create_backup()
        return self._append_weekly_tasks_without_backup(month, week_tasks)

    def _append_weekly_tasks_without_backup(
        self,
        month: str,
        week_tasks: list[dict[str, Any]],
    ) -> int:
        """Append weekly task rows after backup safety has been handled."""

        workbook = self.load_workbook()
        try:
            worksheet = self._get_month_worksheet(workbook, month)
            written = 0
            for week_task in week_tasks:
                week_number = int(week_task["week"])
                header_row, end_row, header_map = self._week_task_table(
                    worksheet,
                    week_number,
                )
                task_column = self._required_column(
                    header_map,
                    ("TASK / GOAL", "GOAL / TASK"),
                )
                row_number = self._blank_rows(
                    worksheet=worksheet,
                    task_column=task_column,
                    start_row=header_row + 1,
                    end_row=end_row,
                    count=1,
                )[0]
                self._write_row_values(
                    worksheet,
                    row_number,
                    header_map,
                    {
                        "TASK / GOAL": week_task.get("task"),
                        "CATEGORY": week_task.get("category"),
                        "STATUS": week_task.get("status"),
                        "NOTES": week_task.get("notes"),
                    },
                )
                written += 1
            self.save_workbook(workbook)
            return written
        finally:
            workbook.close()

    def _blank_rows(
        self,
        worksheet: Worksheet,
        task_column: int,
        start_row: int,
        end_row: int,
        count: int,
    ) -> list[int]:
        """Find blank data rows in a planner section."""

        rows: list[int] = []
        for row_number in range(start_row, end_row + 1):
            value = self._string_or_none(worksheet.cell(row_number, task_column).value)
            if value and value.startswith("↳"):
                continue
            if value:
                continue
            rows.append(row_number)
            if len(rows) == count:
                return rows

        raise PlannerWorkbookError(
            f"Not enough blank rows in sheet '{worksheet.title}'"
        )

    def _write_row_values(
        self,
        worksheet: Worksheet,
        row_number: int,
        header_map: dict[str, int],
        values: dict[str, Any],
    ) -> None:
        """Write values into a planner row by semantic heading."""

        for heading, value in values.items():
            column = header_map.get(self._normalize_label(heading))
            if column is not None:
                worksheet.cell(row_number, column).value = value
