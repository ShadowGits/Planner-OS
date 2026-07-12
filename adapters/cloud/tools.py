"""Build isolated Planner OS tool adapters for one cloud workbook request."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Callable

from planner_mcp.models import PlannerMCPConfig
from planner_mcp.tools import PlannerMCPTools
from planner_platform.context import PlannerContext


class CloudPlannerToolsFactory:
    def __init__(
        self,
        *,
        state_root: Path,
        google_client_factory: Callable[[PlannerContext], object] | None = None,
        external_links_factory: Callable[[PlannerContext], object] | None = None,
        base_config: PlannerMCPConfig | None = None,
    ) -> None:
        self.state_root = Path(state_root)
        self.google_client_factory = google_client_factory
        self.external_links_factory = external_links_factory
        self.base_config = base_config or PlannerMCPConfig()

    def create(self, context: PlannerContext) -> PlannerMCPTools:
        root = self.state_root / str(context.operation_id)
        root.mkdir(parents=True, exist_ok=True)
        settings = root / "execution-settings.json"
        settings.write_text(
            json.dumps(
                {
                    "execution": {
                        "active_target": context.execution_target,
                        "available_targets": ["google_calendar", "apple_calendar", "none"],
                        "publish_mode": "preview_first",
                    }
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        config = replace(
            self.base_config,
            planner_path=context.workbook_path,
            backup_dir=root / "backups",
            execution_settings_path=settings,
            external_links_path=root / "external-links.json",
            execution_preview_dir=root / "previews",
            decision_log_path=root / "decision-log.jsonl",
        )
        calendar_client = (
            (lambda: self.google_client_factory(context))
            if self.google_client_factory
            else None
        )
        links = self.external_links_factory(context) if self.external_links_factory else None
        return PlannerMCPTools(
            config,
            google_calendar_client=calendar_client,
            external_links_store=links,
        )
