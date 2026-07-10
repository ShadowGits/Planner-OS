"""Safe semantic writer operations for Planner OS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from planner_engine.models import CellUpdate, MonthlyGoal, PlannerTask, Priority, TaskStatus
from planner_engine.planner import PlannerEngine
from planner_engine.progress import ProgressEngine, TaskExecution


_STATUS_VALUES = {
    "not started": "Not Started",
    "to do": "To Do",
    "todo": "To Do",
    "in progress": "In Progress",
    "done": "Done",
    "complete": "Done",
    "completed": "Done",
    "blocked": "Blocked",
    "skipped": "Skipped",
}

_PRIORITY_VALUES = {
    "high": "High",
    "medium": "Medium",
    "med": "Medium",
    "low": "Low",
}


@dataclass(frozen=True)
class WriterResult:
    """Structured outcome from a semantic writer operation."""

    operation: str
    success: bool
    item_name: str | None = None
    backup_path: Path | None = None
    errors: tuple[str, ...] = ()
    updated_fields: tuple[str, ...] = ()
    progress_execution: TaskExecution | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Writer:
    """Expose safe semantic planner write operations."""

    def __init__(
        self,
        engine: PlannerEngine,
        progress_engine: ProgressEngine | None = None,
    ) -> None:
        self.engine = engine
        self.progress_engine = progress_engine or ProgressEngine()

    def add_monthly_goal(
        self,
        month: str,
        goal: str,
        *,
        category: str,
        priority: str,
        target_week: str,
        status: str = "Not Started",
        notes: str | None = None,
    ) -> WriterResult:
        """Add a monthly goal by planner concept, not cell location."""

        operation = "add_monthly_goal"
        normalized_goal = self._required_text(goal, "goal")
        normalized_priority = self._normalize_priority(priority)
        normalized_status = self._normalize_status(status)
        validation_errors = self._validation_errors(
            normalized_goal,
            status_input=status,
            normalized_status=normalized_status,
            priority_input=priority,
            normalized_priority=normalized_priority,
        )
        if validation_errors:
            return self._failure(operation, normalized_goal or goal, validation_errors)

        try:
            duplicate_error = self._duplicate_error(month, normalized_goal)
        except Exception as error:
            return self._failure(operation, normalized_goal, [str(error)])
        if duplicate_error:
            return self._failure(operation, normalized_goal, [duplicate_error])

        payload = {
            "goal": normalized_goal,
            "category": self._optional_text(category),
            "priority": normalized_priority,
            "target_week": self._optional_text(target_week),
            "status": normalized_status,
            "notes": self._optional_text(notes),
        }
        return self._with_backup(
            operation=operation,
            item_name=normalized_goal,
            action=lambda: self.engine._append_monthly_goals_without_backup(
                month,
                [payload],
            ),
            updated_fields=("goal", "category", "priority", "target_week", "status", "notes"),
        )

    def add_weekly_task(
        self,
        month: str,
        week: int,
        task: str,
        *,
        category: str | None = None,
        status: str = "Not Started",
        notes: str | None = None,
    ) -> WriterResult:
        """Add a weekly task by month and week number."""

        operation = "add_weekly_task"
        normalized_task = self._required_text(task, "task")
        normalized_status = self._normalize_status(status)
        validation_errors = self._validation_errors(
            normalized_task,
            status_input=status,
            normalized_status=normalized_status,
        )
        if validation_errors:
            return self._failure(operation, normalized_task or task, validation_errors)

        try:
            duplicate_in_week = self._task_exists_in_week(month, week, normalized_task)
        except Exception as error:
            return self._failure(operation, normalized_task, [str(error)])
        if duplicate_in_week:
            return self._failure(
                operation,
                normalized_task,
                [f"Duplicate task in week {week}: {normalized_task}"],
            )

        payload = {
            "week": week,
            "task": normalized_task,
            "category": self._optional_text(category),
            "status": normalized_status,
            "notes": self._optional_text(notes),
        }
        return self._with_backup(
            operation=operation,
            item_name=normalized_task,
            action=lambda: self.engine._append_weekly_tasks_without_backup(
                month,
                [payload],
            ),
            updated_fields=("task", "category", "status", "notes"),
        )

    def update_task(
        self,
        month: str,
        task_name: str,
        *,
        new_name: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        target_week: str | None = None,
        status: str | None = None,
        notes: str | None = None,
    ) -> WriterResult:
        """Update semantic fields for an existing task or monthly goal."""

        operation = "update_task"
        task = self.engine.find_task(month, task_name)
        if task is None:
            return self._failure(operation, task_name, [f"Task not found: {task_name}"])

        normalized_status = self._normalize_status(status) if status is not None else None
        normalized_priority = (
            self._normalize_priority(priority) if priority is not None else None
        )
        validation_errors = self._validation_errors(
            task.name,
            status_input=status,
            normalized_status=normalized_status,
            priority_input=priority,
            normalized_priority=normalized_priority,
        )
        if new_name is not None:
            normalized_name = self._required_text(new_name, "task")
            if not normalized_name:
                validation_errors.append("task is required")
            elif self._duplicate_error(month, normalized_name, ignore=task):
                validation_errors.append(f"Duplicate task: {normalized_name}")
        else:
            normalized_name = None
        if validation_errors:
            return self._failure(operation, task.name, validation_errors)

        try:
            updates = self._updates_for_item(
                task,
                {
                    "name": normalized_name,
                    "category": self._optional_text(category) if category is not None else None,
                    "priority": normalized_priority,
                    "target_week": (
                        self._optional_text(target_week)
                        if target_week is not None
                        else None
                    ),
                    "status": normalized_status,
                    "notes": self._optional_text(notes) if notes is not None else None,
                },
            )
        except ValueError as error:
            return self._failure(operation, task.name, [str(error)])
        return self._write_updates(operation, task.name, updates)

    def complete_task(
        self,
        month: str,
        task_name: str,
        *,
        completion_date: date | None = None,
    ) -> WriterResult:
        """Mark a task done and record completion in the Progress Engine."""

        operation = "complete_task"
        task = self.engine.find_task(month, task_name)
        if task is None:
            return self._failure(operation, task_name, [f"Task not found: {task_name}"])

        result = self._write_updates(
            operation,
            task.name,
            self._updates_for_item(task, {"status": "Done"}),
        )
        if not result.success:
            return result

        execution = self.progress_engine.record_completion(
            task_name=task.name,
            execution_date=completion_date or date.today(),
            category=task.category,
            priority=task.priority,
        )
        return WriterResult(
            operation=operation,
            success=True,
            item_name=task.name,
            backup_path=result.backup_path,
            updated_fields=result.updated_fields,
            progress_execution=execution,
            metadata=result.metadata,
        )

    def move_task(
        self,
        month: str,
        task_name: str,
        destination_week: int,
        *,
        status: str | None = None,
    ) -> WriterResult:
        """Move a weekly task to another week while preserving its metadata."""

        operation = "move_task"
        task = self.engine.find_task(month, task_name)
        if task is None:
            return self._failure(operation, task_name, [f"Task not found: {task_name}"])
        if isinstance(task, MonthlyGoal):
            return self._failure(
                operation,
                task.name,
                [f"Task is not a weekly task: {task.name}"],
            )

        normalized_status = self._normalize_status(status) if status is not None else None
        validation_errors = self._validation_errors(
            task.name,
            status_input=status,
            normalized_status=normalized_status,
        )
        if validation_errors:
            return self._failure(operation, task.name, validation_errors)
        try:
            duplicate_in_week = self._task_exists_in_week(
                month,
                destination_week,
                task.name,
                ignore=task,
            )
        except Exception as error:
            return self._failure(operation, task.name, [str(error)])
        if duplicate_in_week:
            return self._failure(
                operation,
                task.name,
                [f"Duplicate task in week {destination_week}: {task.name}"],
            )

        payload = {
            "week": destination_week,
            "task": task.name,
            "category": task.category,
            "status": normalized_status or task.raw_status or "Not Started",
            "notes": task.notes,
        }
        clear_updates = self._clear_updates_for_item(task)

        def action() -> None:
            self.engine._append_weekly_tasks_without_backup(month, [payload])
            self.engine._write_cells_without_backup(clear_updates)

        return self._with_backup(
            operation=operation,
            item_name=task.name,
            action=action,
            updated_fields=("week", "task", "category", "status", "notes"),
            metadata={"destination_week": destination_week},
        )

    def delete_task(self, month: str, task_name: str) -> WriterResult:
        """Delete a task row by clearing its semantic values."""

        operation = "delete_task"
        task = self.engine.find_task(month, task_name)
        if task is None:
            return self._failure(operation, task_name, [f"Task not found: {task_name}"])

        return self._write_updates(
            operation,
            task.name,
            self._clear_updates_for_item(task),
            updated_fields=tuple(task.cell_references),
        )

    def _write_updates(
        self,
        operation: str,
        item_name: str,
        updates: list[CellUpdate],
        updated_fields: tuple[str, ...] | None = None,
    ) -> WriterResult:
        """Back up once, write a batch of cell updates, and roll back on failure."""

        if not updates:
            return WriterResult(
                operation=operation,
                success=True,
                item_name=item_name,
                updated_fields=(),
            )

        return self._with_backup(
            operation=operation,
            item_name=item_name,
            action=lambda: self.engine._write_cells_without_backup(updates),
            updated_fields=updated_fields or tuple(self._field_name(update) for update in updates),
        )

    def _with_backup(
        self,
        operation: str,
        item_name: str,
        action: Any,
        updated_fields: tuple[str, ...],
        metadata: dict[str, Any] | None = None,
    ) -> WriterResult:
        """Execute a write operation with one backup and rollback on failure."""

        backup_path = self.engine.backup()
        try:
            action()
        except Exception as error:  # pragma: no cover - exercised via public tests
            self.engine.restore_backup(backup_path)
            return self._failure(
                operation,
                item_name,
                [str(error)],
                backup_path=backup_path,
                metadata=metadata,
            )

        return WriterResult(
            operation=operation,
            success=True,
            item_name=item_name,
            backup_path=backup_path,
            updated_fields=updated_fields,
            metadata=metadata or {},
        )

    def _updates_for_item(
        self,
        item: PlannerTask | MonthlyGoal,
        values: dict[str, Any],
    ) -> list[CellUpdate]:
        """Create cell updates for available semantic fields on an item."""

        updates: list[CellUpdate] = []
        unavailable_fields: list[str] = []
        for field_name, value in values.items():
            if value is None:
                continue
            cell = item.cell_references.get(field_name)
            if cell is None:
                unavailable_fields.append(field_name)
                continue
            updates.append(CellUpdate(sheet=item.sheet_name, cell=cell, value=value))
        if unavailable_fields:
            raise ValueError(f"Field not available for task: {', '.join(unavailable_fields)}")
        return updates

    def _clear_updates_for_item(self, item: PlannerTask | MonthlyGoal) -> list[CellUpdate]:
        """Create updates that clear semantic values from a parsed item row."""

        return [
            CellUpdate(sheet=item.sheet_name, cell=cell, value=None)
            for cell in item.cell_references.values()
        ]

    def _duplicate_error(
        self,
        month: str,
        name: str,
        ignore: PlannerTask | MonthlyGoal | None = None,
    ) -> str | None:
        """Return a duplicate-task error if a matching item already exists."""

        found = self.engine.find_task(month, name)
        if found is None:
            return None
        if ignore is not None and (
            found.sheet_name,
            found.row_number,
            found.name.casefold(),
        ) == (ignore.sheet_name, ignore.row_number, ignore.name.casefold()):
            return None
        return f"Duplicate task: {name}"

    def _task_exists_in_week(
        self,
        month: str,
        week: int,
        task_name: str,
        ignore: PlannerTask | MonthlyGoal | None = None,
    ) -> bool:
        """Return whether a task name exists in a destination week."""

        week_name = f"WEEK {week}"
        month_plan = self.engine.get_month_plan(month)
        for section in month_plan.week_sections:
            if section.name.casefold() != week_name.casefold():
                continue
            for task in section.tasks:
                if ignore is not None and (
                    task.sheet_name,
                    task.row_number,
                ) == (ignore.sheet_name, ignore.row_number):
                    continue
                if task.name.casefold() == task_name.casefold():
                    return True
            return False
        raise ValueError(f"Unknown week {week} in month {month}")

    def _validation_errors(
        self,
        item_name: str,
        *,
        status_input: str | None = None,
        normalized_status: str | None = None,
        priority_input: str | None = None,
        normalized_priority: str | None = None,
    ) -> list[str]:
        """Collect common semantic validation errors."""

        errors: list[str] = []
        if not item_name:
            errors.append("task is required")
        if normalized_status == "":
            errors.append(f"Invalid status: {status_input}")
        if normalized_priority == "":
            errors.append(f"Invalid priority: {priority_input}")
        return errors

    def _normalize_status(self, status: str | None) -> str:
        """Normalize a user-facing status value."""

        normalized = " ".join((status or "").casefold().replace("_", " ").split())
        return _STATUS_VALUES.get(normalized, "")

    def _normalize_priority(self, priority: str | None) -> str:
        """Normalize a user-facing priority value."""

        normalized = " ".join((priority or "").casefold().split())
        return _PRIORITY_VALUES.get(normalized, "")

    def _required_text(self, value: str | None, field_name: str) -> str:
        """Return required text stripped of surrounding whitespace."""

        del field_name
        return (value or "").strip()

    def _optional_text(self, value: str | None) -> str:
        """Return optional text in workbook-safe form."""

        return (value or "").strip()

    def _field_name(self, update: CellUpdate) -> str:
        """Best-effort field label for a cell update."""

        return update.cell

    def _failure(
        self,
        operation: str,
        item_name: str | None,
        errors: list[str],
        backup_path: Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WriterResult:
        """Build a structured failed result."""

        return WriterResult(
            operation=operation,
            success=False,
            item_name=item_name,
            backup_path=backup_path,
            errors=tuple(errors),
            metadata=metadata or {},
        )
