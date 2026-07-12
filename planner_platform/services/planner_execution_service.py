"""Request-scoped execution boundary for registered Planner OS tools."""

from __future__ import annotations

from typing import Any, Mapping

from planner_platform.context import PlannerContext
from planner_platform.ports.tools import PlannerToolsFactory
from planner_platform.tool_registry import build_tool_registry


class PlannerExecutionService:
    def __init__(self, tools_factory: PlannerToolsFactory) -> None:
        self.tools_factory = tools_factory

    def execute(
        self,
        context: PlannerContext,
        tool_name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        cloud_mode: bool = False,
    ) -> dict[str, Any]:
        tools = self.tools_factory.create(context)
        registry = build_tool_registry(tools)
        return registry.invoke(tool_name, payload, cloud_mode=cloud_mode)

