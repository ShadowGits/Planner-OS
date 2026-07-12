"""Create a fresh local PlannerMCPTools adapter for each operation context."""

from __future__ import annotations

from dataclasses import replace

from planner_mcp.models import PlannerMCPConfig
from planner_mcp.tools import PlannerMCPTools
from planner_platform.context import PlannerContext


class LocalPlannerToolsFactory:
    def __init__(self, base_config: PlannerMCPConfig | None = None) -> None:
        self.base_config = base_config or PlannerMCPConfig()

    def create(self, context: PlannerContext) -> PlannerMCPTools:
        return PlannerMCPTools(
            replace(self.base_config, planner_path=context.workbook_path)
        )

