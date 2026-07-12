"""Tenant-aware external event mapping port."""

from __future__ import annotations

from typing import Any, Protocol

from planner_platform.context import PlannerContext


class ExternalLinkRepository(Protocol):
    def list(
        self,
        context: PlannerContext,
        *,
        target_name: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def active_for(
        self,
        context: PlannerContext,
        planner_block_id: str,
    ) -> dict[str, Any] | None: ...

    def upsert(
        self,
        context: PlannerContext,
        planner_block_id: str,
        target_name: str,
        external_id: str,
        checksum: str,
    ) -> dict[str, Any]: ...

