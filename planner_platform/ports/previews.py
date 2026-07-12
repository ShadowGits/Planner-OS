"""Owner-scoped preview persistence port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from planner_platform.context import PlannerContext


@dataclass(frozen=True)
class StoredPreview:
    preview_id: str
    operation: str
    payload: dict[str, Any]
    source_revision: int
    created_at: datetime
    expires_at: datetime
    settings_revision: int = 0
    active_execution_target: str | None = None
    consumed_at: datetime | None = None


class PreviewRepository(Protocol):
    def save(self, context: PlannerContext, preview: StoredPreview) -> None: ...

    def get(self, context: PlannerContext, preview_id: str) -> StoredPreview | None: ...

    def consume(self, context: PlannerContext, preview_id: str) -> StoredPreview: ...
