"""Typed models for the Planner OS MCP adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from planner_engine.config import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_EXECUTION_PREVIEW_DIR,
    DEFAULT_EXECUTION_SETTINGS_PATH,
    DEFAULT_EXTERNAL_LINKS_PATH,
    DEFAULT_DECISION_LOG_PATH,
    DEFAULT_PLANNER_PATH,
    DEFAULT_RULES_PATH,
    DEFAULT_APPLE_CALENDAR_HELPER_PATH,
)


@dataclass(frozen=True)
class PlannerMCPConfig:
    """Configuration for connecting MCP tools to a planner workbook."""

    planner_path: Path = DEFAULT_PLANNER_PATH
    backup_dir: Path = DEFAULT_BACKUP_DIR
    rules_path: Path = DEFAULT_RULES_PATH
    month: str | None = None
    execution_settings_path: Path = DEFAULT_EXECUTION_SETTINGS_PATH
    external_links_path: Path = DEFAULT_EXTERNAL_LINKS_PATH
    execution_preview_dir: Path = DEFAULT_EXECUTION_PREVIEW_DIR
    apple_calendar_helper_path: Path = DEFAULT_APPLE_CALENDAR_HELPER_PATH
    apple_calendar_id: str | None = None
    decision_log_path: Path = DEFAULT_DECISION_LOG_PATH
    timezone: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """Structured success/error payload returned by MCP tools."""

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    preview_id: str | None = None
    requires_confirmation: bool = False
    operation: str | None = None
    target: str | None = None
    decision_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)
