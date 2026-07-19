"""Single-owner adapter for the existing local external-link store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from planner_engine.external_links import ExternalLinkStore
from planner_platform.context import PlannerContext


class LocalExternalLinkRepository:
    """Adapt local mappings; Stage 3 supplies true tenant-scoped storage."""

    def __init__(self, path: str | Path) -> None:
        self.store = ExternalLinkStore(path)

    def list(
        self,
        context: PlannerContext,
        *,
        target_name: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.store.list(target_name=target_name, status=status)

    def active_for(self, context: PlannerContext, planner_block_id: str) -> dict[str, Any] | None:
        return self.store.active_for(planner_block_id)

    def upsert(
        self,
        context: PlannerContext,
        planner_block_id: str,
        target_name: str,
        external_id: str,
        checksum: str,
    ) -> dict[str, Any]:
        return self.store.upsert(planner_block_id, target_name, external_id, checksum)

    def remove(self, context: PlannerContext, planner_block_id: str, target_name: str) -> None:
        self.store.remove(planner_block_id, target_name)

