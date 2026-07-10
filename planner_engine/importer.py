"""Structured JSON importer for Planner OS workbooks."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from shutil import copy2
from typing import Any

from planner_engine.excel import ExcelPlannerStore, PlannerWorkbookError
from planner_engine.planner import PlannerEngine


ALLOWED_PRIORITIES = {"High", "Medium", "Low"}
ALLOWED_STATUSES = {
    "Done",
    "In Progress",
    "To Do",
    "Not Started",
    "Blocked",
    "Skipped",
}


@dataclass(frozen=True)
class ImportResult:
    """Structured result from a planner import."""

    goals_imported: int = 0
    tasks_imported: int = 0
    skipped_items: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    backup_path: Path | None = None

    @property
    def success(self) -> bool:
        """Return whether the import completed without validation errors."""

        return not self.validation_errors


class PlannerImporter:
    """Import structured JSON planning data into an Excel planner."""

    def __init__(self, engine: PlannerEngine) -> None:
        self.engine = engine

    def import_file(self, input_path: str | Path) -> ImportResult:
        """Import a single JSON document from a path."""

        try:
            with Path(input_path).open("r", encoding="utf-8") as input_file:
                document = json.load(input_file)
        except json.JSONDecodeError as error:
            return ImportResult(
                validation_errors=[f"Malformed JSON: {error.msg}"],
            )

        return self.import_document(document)

    def import_document(self, document: Any) -> ImportResult:
        """Validate and import a JSON-compatible document."""

        validation_errors = self._validate_document_shape(document)
        if validation_errors:
            return ImportResult(validation_errors=validation_errors)

        month = document["month"]
        if month not in self.engine.list_months():
            return ImportResult(validation_errors=[f"Unknown planner month: {month}"])

        month_plan = self.engine.get_month_plan(month)
        prepared_goals, skipped_goals, goal_errors = self._prepare_monthly_goals(
            document["monthly_goals"],
            existing_names={goal.name for goal in month_plan.monthly_goals},
        )
        prepared_tasks, skipped_tasks, task_errors = self._prepare_weekly_tasks(
            document["weeks"],
            month_plan=month_plan,
        )
        validation_errors = goal_errors + task_errors
        skipped_items = skipped_goals + skipped_tasks
        if validation_errors:
            return ImportResult(
                skipped_items=skipped_items,
                validation_errors=validation_errors,
            )

        backup_path = self.engine.backup()
        try:
            goals_imported = self.engine._append_monthly_goals_without_backup(
                month,
                prepared_goals,
            )
            tasks_imported = self.engine._append_weekly_tasks_without_backup(
                month,
                prepared_tasks,
            )
            return ImportResult(
                goals_imported=goals_imported,
                tasks_imported=tasks_imported,
                skipped_items=skipped_items,
                backup_path=backup_path,
            )
        except Exception as error:
            copy2(backup_path, self.engine.store.planner_path)
            return ImportResult(
                skipped_items=skipped_items,
                validation_errors=[f"Import failed and was rolled back: {error}"],
                backup_path=backup_path,
            )

    def _validate_document_shape(self, document: Any) -> list[str]:
        """Validate top-level JSON document shape."""

        errors: list[str] = []
        if not isinstance(document, dict):
            return ["Input JSON must be an object."]

        if not isinstance(document.get("month"), str) or not document["month"].strip():
            errors.append("Missing or invalid field: month")
        if not isinstance(document.get("monthly_goals"), list):
            errors.append("Missing or invalid field: monthly_goals")
        if not isinstance(document.get("weeks"), list):
            errors.append("Missing or invalid field: weeks")
        return errors

    def _prepare_monthly_goals(
        self,
        goals: list[Any],
        existing_names: set[str],
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        """Validate and normalize monthly goal imports."""

        prepared: list[dict[str, Any]] = []
        skipped: list[str] = []
        errors: list[str] = []
        seen_names = {self._normalize_name(name) for name in existing_names}

        for index, goal in enumerate(goals, start=1):
            if not isinstance(goal, dict):
                errors.append(f"monthly_goals[{index}] must be an object")
                continue

            name = self._required_text(goal, "goal")
            if not name:
                errors.append(f"monthly_goals[{index}].goal is required")
                continue

            normalized_name = self._normalize_name(name)
            if normalized_name in seen_names:
                skipped.append(f"Duplicate monthly goal skipped: {name}")
                continue
            seen_names.add(normalized_name)

            priority = self._required_text(goal, "priority")
            status = self._required_text(goal, "status")
            if priority not in ALLOWED_PRIORITIES:
                errors.append(f"Invalid priority for monthly goal '{name}': {priority}")
            if status not in ALLOWED_STATUSES:
                errors.append(f"Invalid status for monthly goal '{name}': {status}")

            prepared.append(
                {
                    "goal": name,
                    "category": self._optional_text(goal, "category"),
                    "priority": priority,
                    "target_week": self._optional_text(goal, "target_week"),
                    "status": status,
                    "notes": self._optional_text(goal, "notes"),
                }
            )

        return prepared, skipped, errors

    def _prepare_weekly_tasks(
        self,
        weeks: list[Any],
        month_plan: Any,
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        """Validate and normalize weekly task imports."""

        prepared: list[dict[str, Any]] = []
        skipped: list[str] = []
        errors: list[str] = []
        existing_by_week = {
            self._week_number(section.name): {
                self._normalize_name(task.name) for task in section.tasks
            }
            for section in month_plan.week_sections
        }
        seen_by_week = {week: set(names) for week, names in existing_by_week.items()}

        for week_index, week in enumerate(weeks, start=1):
            if not isinstance(week, dict):
                errors.append(f"weeks[{week_index}] must be an object")
                continue
            week_number = week.get("week")
            if not isinstance(week_number, int):
                errors.append(f"weeks[{week_index}].week must be an integer")
                continue
            if week_number not in existing_by_week:
                errors.append(f"Unknown week {week_number} in month {month_plan.month}")
                continue
            if not isinstance(week.get("tasks"), list):
                errors.append(f"weeks[{week_index}].tasks must be a list")
                continue

            for task_index, task in enumerate(week["tasks"], start=1):
                if not isinstance(task, dict):
                    errors.append(
                        f"weeks[{week_index}].tasks[{task_index}] must be an object"
                    )
                    continue

                name = self._required_text(task, "task")
                if not name:
                    errors.append(
                        f"weeks[{week_index}].tasks[{task_index}].task is required"
                    )
                    continue

                normalized_name = self._normalize_name(name)
                if normalized_name in seen_by_week[week_number]:
                    skipped.append(f"Duplicate weekly task skipped: W{week_number} {name}")
                    continue
                seen_by_week[week_number].add(normalized_name)

                status = self._required_text(task, "status")
                if status not in ALLOWED_STATUSES:
                    errors.append(f"Invalid status for weekly task '{name}': {status}")

                prepared.append(
                    {
                        "week": week_number,
                        "task": name,
                        "category": self._optional_text(task, "category"),
                        "status": status,
                        "notes": self._optional_text(task, "notes"),
                    }
                )

        return prepared, skipped, errors

    def _week_number(self, week_name: str) -> int:
        """Extract the integer week number from a section name."""

        _, number = week_name.split(maxsplit=1)
        return int(number)

    def _required_text(self, item: dict[str, Any], key: str) -> str:
        """Return a stripped required string, or an empty string."""

        value = item.get(key)
        if value is None:
            return ""
        return str(value).strip()

    def _optional_text(self, item: dict[str, Any], key: str) -> str:
        """Return a stripped optional string."""

        value = item.get(key)
        if value is None:
            return ""
        return str(value).strip()

    def _normalize_name(self, name: str) -> str:
        """Normalize item names for duplicate detection."""

        return " ".join(name.casefold().split())


def build_parser() -> argparse.ArgumentParser:
    """Build the importer CLI parser."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--planner", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--backup-dir", default=Path("backups"), type=Path)
    return parser


def main() -> int:
    """Run the importer CLI."""

    args = build_parser().parse_args()
    engine = PlannerEngine(
        ExcelPlannerStore(planner_path=args.planner, backup_dir=args.backup_dir)
    )
    result = PlannerImporter(engine).import_file(args.input)
    print(
        json.dumps(
            {
                "goals_imported": result.goals_imported,
                "tasks_imported": result.tasks_imported,
                "skipped_items": result.skipped_items,
                "validation_errors": result.validation_errors,
                "backup_path": str(result.backup_path) if result.backup_path else None,
            },
            indent=2,
        )
    )
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
