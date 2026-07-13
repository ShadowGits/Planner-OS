"""Tenant-scoped Supabase preview repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from adapters.supabase.client import SupabaseGateway
from planner_platform.context import PlannerContext
from planner_platform.ports.previews import StoredPreview


class SupabasePreviewRepository:
    def __init__(self, client: SupabaseGateway) -> None:
        self.client = client

    def save(self, context: PlannerContext, preview: StoredPreview) -> None:
        self.client.insert(
            "planner_previews",
            {
                "id": preview.preview_id,
                "user_id": str(context.user_id),
                "workspace_id": str(context.workspace_id),
                "operation_type": preview.operation,
                "payload": preview.payload,
                "source_revision": preview.source_revision,
                "settings_revision": preview.settings_revision,
                "active_execution_target": preview.active_execution_target or context.execution_target,
                "created_at": preview.created_at.isoformat(),
                "expires_at": preview.expires_at.isoformat(),
                "consumed_at": preview.consumed_at.isoformat() if preview.consumed_at else None,
            },
        )

    def get(self, context: PlannerContext, preview_id: str) -> StoredPreview | None:
        rows = self.client.select(
            "planner_previews",
            filters={
                "id": preview_id,
                "user_id": str(context.user_id),
                "workspace_id": str(context.workspace_id),
            },
            limit=1,
        )
        return self._from_row(rows[0]) if rows else None

    def consume(self, context: PlannerContext, preview_id: str) -> StoredPreview:
        from dataclasses import replace
        from datetime import datetime, timezone
        
        preview = self.get(context, preview_id)
        if not preview:
            raise ValueError("Preview is missing")
            
        now = datetime.now(timezone.utc)
        if preview.consumed_at is not None:
            raise ValueError("Preview is already consumed")
        if preview.expires_at < now:
            raise ValueError("Preview is expired")
            
        self.client.update(
            "planner_previews",
            {"consumed_at": now.isoformat()},
            filters={
                "id": preview_id,
                "workspace_id": str(context.workspace_id),
                "user_id": str(context.user_id),
            }
        )
        return replace(preview, consumed_at=now)

    @staticmethod
    def _from_row(row: dict[str, Any]) -> StoredPreview:
        return StoredPreview(
            preview_id=str(row["id"]),
            operation=str(row["operation_type"]),
            payload=dict(row["payload"]),
            source_revision=int(row["source_revision"]),
            settings_revision=int(row.get("settings_revision", 0)),
            active_execution_target=str(row["active_execution_target"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            expires_at=datetime.fromisoformat(str(row["expires_at"])),
            consumed_at=(datetime.fromisoformat(str(row["consumed_at"])) if row.get("consumed_at") else None),
        )

