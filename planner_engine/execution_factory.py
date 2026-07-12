"""Factory for local execution-target services."""

from __future__ import annotations

from pathlib import Path

from planner_engine.execution_manager import ExecutionManager, ExecutionSettings
from planner_engine.execution_targets.google_calendar import GoogleCalendarExecutionTarget
from planner_engine.execution_targets.null import NullExecutionTarget
from planner_engine.execution_targets.apple_calendar import AppleCalendarExecutionTarget
from planner_engine.external_links import ExternalLinkStore
from planner_integrations.google_calendar import GoogleCalendarClient
from planner_integrations.apple_calendar import AppleCalendarClient


def create_execution_manager(
    *, settings_path: str | Path, links_path: str | Path, preview_dir: str | Path,
    apple_helper_path: str | Path, google_client: GoogleCalendarClient,
    apple_calendar_id: str | None = None,
) -> ExecutionManager:
    settings = ExecutionSettings(settings_path)
    links = ExternalLinkStore(links_path)
    settings.get_active()
    links.retire_target("structured")
    selected_apple_calendar = apple_calendar_id or settings.get_apple_calendar_id()
    return ExecutionManager(
        settings, links,
        {
            "google_calendar": GoogleCalendarExecutionTarget(google_client),
            "apple_calendar": AppleCalendarExecutionTarget(AppleCalendarClient(apple_helper_path, selected_apple_calendar)),
            "none": NullExecutionTarget(),
        }, preview_dir,
    )
