"""File-backed owner-scoped preview repository for local execution."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from planner_platform.context import PlannerContext
from planner_platform.ports.previews import StoredPreview


class LocalPreviewRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, context: PlannerContext, preview: StoredPreview) -> None:
        path = self._path(context, preview.preview_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = asdict(preview)
        payload.update({"user_id": str(context.user_id), "workspace_id": str(context.workspace_id)})
        for field in ("created_at", "expires_at", "consumed_at"):
            value = payload[field]
            payload[field] = value.isoformat() if value is not None else None
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(path)

    def get(self, context: PlannerContext, preview_id: str) -> StoredPreview | None:
        path = self._path(context, preview_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("user_id") != str(context.user_id) or data.get("workspace_id") != str(context.workspace_id):
            return None
        return self._from_dict(data)

    def consume(self, context: PlannerContext, preview_id: str) -> StoredPreview:
        preview = self.get(context, preview_id)
        if preview is None:
            raise ValueError("Preview not found")
        now = datetime.now(timezone.utc)
        if preview.consumed_at is not None:
            raise ValueError("Preview already consumed")
        if preview.expires_at <= now:
            raise ValueError("Preview expired")
        consumed = StoredPreview(**{**asdict(preview), "consumed_at": now})
        self.save(context, consumed)
        return consumed

    def _path(self, context: PlannerContext, preview_id: str) -> Path:
        if not preview_id or Path(preview_id).name != preview_id:
            raise ValueError("Invalid preview identifier")
        return self.root / str(context.user_id) / str(context.workspace_id) / f"{preview_id}.json"

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> StoredPreview:
        return StoredPreview(
            preview_id=str(data["preview_id"]),
            operation=str(data["operation"]),
            payload=dict(data["payload"]),
            source_revision=int(data["source_revision"]),
            settings_revision=int(data.get("settings_revision", 0)),
            active_execution_target=(
                str(data["active_execution_target"])
                if data.get("active_execution_target")
                else None
            ),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            expires_at=datetime.fromisoformat(str(data["expires_at"])),
            consumed_at=(
                datetime.fromisoformat(str(data["consumed_at"]))
                if data.get("consumed_at")
                else None
            ),
        )
