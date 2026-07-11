"""Typed models for the Planner OS MCP adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from planner_engine.config import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_PLANNER_PATH,
    DEFAULT_RULES_PATH,
)


@dataclass(frozen=True)
class PlannerMCPConfig:
    """Configuration for connecting MCP tools to a planner workbook."""

    planner_path: Path = DEFAULT_PLANNER_PATH
    backup_dir: Path = DEFAULT_BACKUP_DIR
    rules_path: Path = DEFAULT_RULES_PATH
    month: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """Structured success/error payload returned by MCP tools."""

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)
