"""Local workbook repository adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path

from planner_engine.excel import ExcelPlannerStore
from planner_platform.context import PlannerContext
from planner_platform.ports.workbooks import WorkbookRevision


class LocalWorkbookRepository:
    def __init__(self, backup_dir: str | Path) -> None:
        self.backup_dir = Path(backup_dir)

    def current(self, context: PlannerContext) -> WorkbookRevision:
        path = context.workbook_path
        if not path.is_file():
            raise FileNotFoundError(f"Planner not found: {path}")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        return WorkbookRevision(
            number=context.source_revision,
            checksum=checksum,
            path=path,
        )

    def create_backup(self, context: PlannerContext) -> Path:
        return ExcelPlannerStore(context.workbook_path, self.backup_dir).create_backup()

