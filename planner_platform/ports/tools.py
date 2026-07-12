"""Request-scoped Planner MCP tool factory port."""

from __future__ import annotations

from typing import Any, Protocol

from planner_platform.context import PlannerContext


class PlannerToolsFactory(Protocol):
    def create(self, context: PlannerContext) -> Any: ...

