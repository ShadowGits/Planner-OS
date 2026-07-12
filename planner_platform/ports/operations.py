"""Operation and audit persistence port."""

from __future__ import annotations

from typing import Any, Protocol

from planner_platform.context import PlannerContext


class OperationRepository(Protocol):
    def record(
        self,
        context: PlannerContext,
        *,
        tool_name: str,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> None: ...

