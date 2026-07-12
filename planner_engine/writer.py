"""Safe semantic writer operations for Planner OS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from uuid import uuid4

from planner_engine.decision_log import DecisionLog, DecisionOutcome
from planner_engine.models import CellUpdate, DatedTask, MonthlyGoal, PlannerTask, Priority, TaskStatus
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
    warnings: tuple[str, ...] = ()


class Writer:
    """Expose safe semantic planner write operations."""

    def __init__(
        self,
        engine: PlannerEngine,
        progress_engine: ProgressEngine | None = None,
        decision_log: DecisionLog | None = None,
    ) -> None:
        self.engine = engine
        self.progress_engine = progress_engine or ProgressEngine()
        self.decision_log = decision_log or DecisionLog()

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
            reason="Add monthly goal through Semantic Writer",
            constraints_considered=("semantic write", "backup before mutation"),
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
            reason="Add weekly task through Semantic Writer",
            constraints_considered=("semantic write", "backup before mutation"),
            metadata={"week": week},
        )

    def add_weekly_tasks(
        self,
        month: str,
        tasks: list[dict[str, Any]],
        *,
        overwrite_existing: bool = False,
    ) -> WriterResult:
        """Apply an approved planning batch with one backup and decision record."""

        operation = "apply_planning_batch"
        if not tasks:
            return WriterResult(operation=operation, success=True, item_name="Approved plan")
        payloads: list[dict[str, Any]] = []
        skipped: list[str] = []
        target_weeks = {int(task["week"]) for task in tasks}
        for task in tasks:
            name = self._required_text(task.get("task"), "task")
            week = int(task["week"])
            if not name:
                return self._failure(operation, "Approved plan", ["task is required"])
            if self._task_exists_in_week(month, week, name):
                if not overwrite_existing:
                    skipped.append(name)
                    continue
            payloads.append(
                {
                    "week": week,
                    "task": name,
                    "category": self._optional_text(task.get("category")),
                    "status": self._normalize_status(task.get("status", "Not Started")),
                    "notes": self._optional_text(task.get("notes")),
                }
            )
        if not payloads:
            return WriterResult(
                operation=operation,
                success=True,
                item_name="Approved plan",
                metadata={"written": 0, "skipped": skipped},
            )
        names = [payload["task"] for payload in payloads]
        clear_updates: list[CellUpdate] = []
        if overwrite_existing:
            month_plan = self.engine.get_month_plan(month)
            for week_number in target_weeks:
                if week_number < 1 or week_number > len(month_plan.week_sections):
                    return self._failure(
                        operation,
                        "Approved plan",
                        [f"Unknown week {week_number} in month {month}"],
                    )
                for existing in month_plan.week_sections[week_number - 1].tasks:
                    if not existing.scheduled_dates:
                        clear_updates.extend(self._clear_updates_for_item(existing))

        def action() -> None:
            if clear_updates:
                self.engine._write_cells_without_backup(clear_updates)
            self.engine._append_weekly_tasks_without_backup(month, payloads)

        return self._with_backup(
            operation=operation,
            item_name="Approved plan",
            action=action,
            updated_fields=("week", "task", "category", "status", "notes"),
            metadata={
                "written": len(payloads),
                "skipped": skipped,
                "tasks": names,
                "overwritten_weeks": sorted(target_weeks) if overwrite_existing else [],
            },
            reason="Apply explicitly approved planning preview",
            constraints_considered=(
                "preview before apply",
                "semantic write",
                "single backup before batch mutation",
                "calendar not synced",
            ),
        )

    def add_dated_task(
        self,
        task_date: date,
        title: str,
        estimated_minutes: int,
        *,
        preferred_daypart: str | None = None,
        start_time: str | time | None = None,
        end_time: str | time | None = None,
        hard_time: bool | None = None,
        category: str | None = None,
        notes: str | None = None,
    ) -> WriterResult:
        """Add a task to one exact workbook day column."""

        operation = "add_dated_task"
        title = self._required_text(title, "title")
        try:
            payload = self._dated_payload(
                task_date,
                title,
                estimated_minutes,
                preferred_daypart,
                start_time,
                end_time,
                hard_time,
                category,
                notes,
                task_id=self._new_dated_task_id(),
            )
            if any(
                task.title.casefold() == title.casefold()
                for task in self.engine.list_dated_tasks(task_date.strftime("%b %Y"), task_date)
            ):
                return self._failure(operation, title, [f"Duplicate dated task on {task_date}: {title}"])
        except Exception as error:
            return self._failure(operation, title, [str(error)])
        return self._with_backup(
            operation=operation,
            item_name=title,
            action=lambda: self.engine._append_dated_tasks_without_backup(
                task_date.strftime("%b %Y"), [payload]
            ),
            updated_fields=("date", "title", "time_block", "category", "status", "notes"),
            metadata={"date": task_date.isoformat(), "time_value": payload["time_value"]},
            reason="Add exact-date task to workbook day column",
            constraints_considered=("exact date preserved", "backup before mutation", "not a generic weekly task"),
        )

    def add_dated_tasks(
        self,
        tasks: list[dict[str, Any]],
        *,
        overwrite_generated: bool = False,
        overwrite_start: date | None = None,
        overwrite_end: date | None = None,
    ) -> WriterResult:
        """Add multiple exact-date tasks with one workbook backup."""

        operation = "add_dated_task_batch"
        if not tasks:
            return self._failure(operation, "Dated task batch", ["At least one dated task is required"])
        payloads_by_month: dict[str, list[dict[str, Any]]] = {}
        titles: list[str] = []
        try:
            for item in tasks:
                task_date = item.get("date")
                if isinstance(task_date, str):
                    task_date = date.fromisoformat(task_date)
                if not isinstance(task_date, date):
                    raise ValueError("date is required for every dated task")
                payload = self._dated_payload(
                    task_date,
                    str(item.get("title", "")),
                    int(item.get("estimated_minutes", 0)),
                    item.get("preferred_daypart"),
                    item.get("start_time"),
                    item.get("end_time"),
                    item.get("hard_time"),
                    item.get("category"),
                    item.get("notes"),
                    status=item.get("status", "Not Started"),
                    task_id=item.get("id") or item.get("task_id") or self._new_dated_task_id(),
                )
                month = task_date.strftime("%b %Y")
                duplicates = [
                    existing
                    for existing in self.engine.list_dated_tasks(month, task_date)
                    if existing.title.casefold() == payload["title"].casefold()
                ]
                if duplicates and not (
                    overwrite_generated
                    and all(
                        "planner os generated" in (existing.notes or "").casefold()
                        for existing in duplicates
                    )
                ):
                    raise ValueError(
                        f"Duplicate dated task on {task_date}: {payload['title']}"
                    )
                payloads_by_month.setdefault(month, []).append(payload)
                titles.append(payload["title"])
        except Exception as error:
            return self._failure(operation, "Dated task batch", [str(error)])

        clear_updates: list[CellUpdate] = []
        if overwrite_generated:
            seen_rows: set[tuple[str, int]] = set()
            for month, payloads in payloads_by_month.items():
                target_dates = {payload["date"] for payload in payloads}
                for existing in self.engine.list_dated_tasks(month):
                    row_key = (existing.sheet_name, existing.row_number)
                    in_overwrite_range = (
                        overwrite_start is not None
                        and overwrite_end is not None
                        and overwrite_start <= existing.date <= overwrite_end
                    )
                    if (
                        (existing.date in target_dates or in_overwrite_range)
                        and "planner os generated" in (existing.notes or "").casefold()
                        and row_key not in seen_rows
                    ):
                        clear_updates.extend(self._clear_updates_for_item(existing))
                        seen_rows.add(row_key)

        def action() -> None:
            if clear_updates:
                self.engine._write_cells_without_backup(clear_updates)
            for month, payloads in payloads_by_month.items():
                self.engine._append_dated_tasks_without_backup(month, payloads)

        return self._with_backup(
            operation=operation,
            item_name="Dated task batch",
            action=action,
            updated_fields=("date", "title", "time_block", "category", "status", "notes"),
            metadata={
                "written": len(titles),
                "tasks": titles,
                "overwrote_generated_rows": len(clear_updates) > 0,
            },
            reason="Add approved exact-date task batch to workbook day columns",
            constraints_considered=(
                "exact dates preserved",
                "single backup before batch mutation",
                "not generic weekly tasks",
            ),
        )

    def update_dated_task(self, task_id: str, **changes: Any) -> WriterResult:
        """Update or move an exact-date workbook task with one backup."""

        operation = "update_dated_task"
        task = self.engine.find_dated_task(task_id)
        if task is None:
            return self._failure(operation, task_id, [f"Dated task not found: {task_id}"])
        task_date = changes.get("date", task.date)
        if isinstance(task_date, str):
            task_date = date.fromisoformat(task_date)
        try:
            payload = self._dated_payload(
                task_date,
                changes.get("title", task.title),
                int(changes.get("estimated_minutes", task.estimated_minutes)),
                changes.get("preferred_daypart", task.preferred_daypart),
                changes.get("start_time", task.start_time),
                changes.get("end_time", task.end_time),
                changes.get("hard_time", task.hard_time),
                changes.get("category", task.category),
                changes.get("notes", task.notes),
                status=changes.get("status", task.status.value),
                task_id=task.id,
            )
        except Exception as error:
            return self._failure(operation, task.title, [str(error)])

        if task_date != task.date:
            clear = self._clear_updates_for_item(task)

            def action() -> None:
                self.engine._append_dated_tasks_without_backup(task_date.strftime("%b %Y"), [payload])
                self.engine._write_cells_without_backup(clear)

            return self._with_backup(
                operation=operation,
                item_name=task.title,
                action=action,
                updated_fields=("date", "title", "time_block", "category", "status", "notes"),
                metadata={"old_date": task.date.isoformat(), "date": task_date.isoformat()},
                reason="Move exact-date task only after an explicit dated-task update",
                constraints_considered=("exact destination date", "backup before mutation"),
            )

        values = {
            "name": payload["title"],
            "category": payload["category"],
            "status": payload["status"],
            "notes": payload["notes"],
            "time_block": payload["time_value"],
        }
        return self._write_updates(
            operation,
            task.title,
            self._updates_for_item(task, values),
            reason="Update exact-date task through Semantic Writer",
            constraints_considered=("exact date preserved", "backup before mutation"),
        )

    def delete_dated_task(self, task_id: str) -> WriterResult:
        """Delete one exact-date task row through Semantic Writer."""

        task = self.engine.find_dated_task(task_id)
        if task is None:
            return self._failure("delete_dated_task", task_id, [f"Dated task not found: {task_id}"])
        return self._write_updates(
            "delete_dated_task",
            task.title,
            self._clear_updates_for_item(task),
            updated_fields=tuple(task.cell_references),
            reason="Delete exact-date task through Semantic Writer",
            constraints_considered=("exact dated task", "backup before mutation"),
        )

    def list_dated_tasks(
        self,
        task_date: date,
    ) -> list[DatedTask]:
        """Return exact-date tasks without mutating the workbook."""

        return self.engine.list_dated_tasks(task_date.strftime("%b %Y"), task_date)

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
        return self._write_updates(
            operation,
            task.name,
            updates,
            reason="Update task through Semantic Writer",
            constraints_considered=("semantic write", "backup before mutation"),
        )

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
            warnings=result.warnings,
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
            reason="Move unfinished task instead of deleting it",
            constraints_considered=(
                "preserve metadata",
                "preserve notes",
                "backup before mutation",
            ),
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
            reason="Delete task through Semantic Writer",
            constraints_considered=("semantic write", "backup before mutation"),
        )

    def _write_updates(
        self,
        operation: str,
        item_name: str,
        updates: list[CellUpdate],
        updated_fields: tuple[str, ...] | None = None,
        reason: str = "Write task fields through Semantic Writer",
        constraints_considered: tuple[str, ...] = ("semantic write",),
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
            reason=reason,
            constraints_considered=constraints_considered,
        )

    def _with_backup(
        self,
        operation: str,
        item_name: str,
        action: Any,
        updated_fields: tuple[str, ...],
        metadata: dict[str, Any] | None = None,
        reason: str = "Planner mutation through Semantic Writer",
        constraints_considered: tuple[str, ...] = ("semantic write",),
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

        warnings = self._record_decision(
            action=operation,
            reason=reason,
            affected_tasks=[item_name],
            constraints_considered=list(constraints_considered),
            outcome=DecisionOutcome.SUCCESS,
            backup_path=backup_path,
            metadata={
                "updated_fields": list(updated_fields),
                **(metadata or {}),
            },
        )

        return WriterResult(
            operation=operation,
            success=True,
            item_name=item_name,
            backup_path=backup_path,
            updated_fields=updated_fields,
            metadata=metadata or {},
            warnings=tuple(warnings),
        )

    def _record_decision(
        self,
        *,
        action: str,
        reason: str,
        affected_tasks: list[str],
        constraints_considered: list[str],
        outcome: DecisionOutcome,
        backup_path: Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        """Record a decision without breaking the planner action."""

        try:
            self.decision_log.record(
                action=action,
                reason=reason,
                confidence=1.0,
                affected_tasks=affected_tasks,
                constraints_considered=constraints_considered,
                outcome=outcome,
                backup_path=backup_path,
                metadata=metadata,
            )
        except Exception as error:
            return [f"Decision log warning: {error}"]
        return []

    def _updates_for_item(
        self,
        item: PlannerTask | MonthlyGoal | DatedTask,
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

    def _clear_updates_for_item(self, item: PlannerTask | MonthlyGoal | DatedTask) -> list[CellUpdate]:
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

    def _dated_payload(
        self,
        task_date: date,
        title: str,
        estimated_minutes: int,
        preferred_daypart: str | None,
        start_time: str | time | None,
        end_time: str | time | None,
        hard_time: bool | None,
        category: str | None,
        notes: str | None,
        *,
        status: str = "Not Started",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if not title.strip():
            raise ValueError("title is required")
        if estimated_minutes <= 0:
            raise ValueError("estimated_minutes must be positive")
        parsed_start = self._parse_time(start_time)
        parsed_end = self._parse_time(end_time)
        if (parsed_start is None) != (parsed_end is None):
            raise ValueError("start_time and end_time must be provided together")
        if parsed_start and parsed_end and parsed_end <= parsed_start:
            raise ValueError("end_time must be after start_time")
        if hard_time and not (parsed_start and parsed_end):
            raise ValueError("hard_time requires start_time and end_time")
        allowed_dayparts = {"morning", "afternoon", "evening", "night"}
        daypart = preferred_daypart.casefold() if preferred_daypart else None
        if daypart and daypart not in allowed_dayparts:
            raise ValueError(f"Unknown preferred_daypart: {preferred_daypart}")
        if parsed_start and parsed_end:
            time_value = f"{parsed_start.strftime('%H:%M')}-{parsed_end.strftime('%H:%M')}"
            estimated_minutes = int(
                (
                    datetime.combine(task_date, parsed_end)
                    - datetime.combine(task_date, parsed_start)
                ).total_seconds()
                // 60
            )
        else:
            time_value = f"{estimated_minutes} min"
            if daypart:
                time_value += f" · {daypart}"
        normalized_status = self._normalize_status(status) or "Not Started"
        stable_task_id = task_id or self._new_dated_task_id()
        return {
            "date": task_date,
            "id": stable_task_id,
            "title": title.strip(),
            "estimated_minutes": estimated_minutes,
            "preferred_daypart": daypart,
            "time_value": time_value,
            "category": self._optional_text(category) or "Personal",
            "status": normalized_status,
            "notes": self._notes_with_dated_task_id(notes, stable_task_id),
        }

    def _new_dated_task_id(self) -> str:
        return f"dt_{uuid4().hex}"

    def _notes_with_dated_task_id(self, notes: str | None, task_id: str) -> str:
        clean_notes = self._optional_text(notes)
        marker = f"[planner_os_task_id: {task_id}]"
        if marker.casefold() in clean_notes.casefold():
            return clean_notes
        return f"{clean_notes}\n{marker}".strip()

    def _parse_time(self, value: str | time | None) -> time | None:
        if value is None or value == "":
            return None
        return value if isinstance(value, time) else time.fromisoformat(str(value))

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
