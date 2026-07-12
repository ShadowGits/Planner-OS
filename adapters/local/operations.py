"""Local JSONL operation repository."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from planner_platform.context import PlannerContext


class LocalOperationRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def record(
        self,
        context: PlannerContext,
        *,
        tool_name: str,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        path = self.root / str(context.user_id) / str(context.workspace_id) / "operations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "operation_id": str(context.operation_id),
            "user_id": str(context.user_id),
            "workspace_id": str(context.workspace_id),
            "tool_name": tool_name,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": result or {},
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

