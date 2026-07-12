"""Private workbook object-storage port."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from planner_platform.context import PlannerContext


class WorkbookObjectStore(Protocol):
    def download_current(self, context: PlannerContext, destination_dir: Path) -> Path: ...

    def upload_current(self, context: PlannerContext, source: Path) -> None: ...

    def backup_current(self, context: PlannerContext, checksum: str) -> str: ...

