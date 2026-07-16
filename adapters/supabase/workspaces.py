"""Tenant-safe Supabase workspace metadata and lock repository."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from adapters.supabase.client import SupabaseGateway
from adapters.supabase.models import workspace_from_row
from planner_platform.context import PlannerContext
from planner_platform.ports.workspaces import WorkspaceRecord


class WorkspaceBusyError(RuntimeError):
    pass


class StaleWorkspaceRevisionError(RuntimeError):
    pass


class SupabaseWorkspaceRepository:
    def __init__(self, client: SupabaseGateway) -> None:
        self.client = client

    def create(
        self,
        user_id: UUID,
        *,
        name: str,
        timezone: str,
    ) -> WorkspaceRecord:
        workspace_id = uuid4()
        payload = {
            "id": str(workspace_id),
            "user_id": str(user_id),
            "name": name,
            "timezone": timezone,
            "workbook_bucket": "planner-workbooks",
            "workbook_key": f"{user_id}/{workspace_id}/current.xlsx",
        }
        rows = self.client.insert("workspaces", payload)
        if not rows:
            raise RuntimeError("Workspace creation returned no record")
        return workspace_from_row(rows[0])

    def get_owned(self, user_id: UUID, workspace_id: UUID) -> WorkspaceRecord | None:
        rows = self.client.select(
            "workspaces",
            filters={"id": str(workspace_id), "user_id": str(user_id)},
            limit=1,
        )
        return workspace_from_row(rows[0]) if rows else None

    def get_by_id(self, workspace_id: UUID) -> WorkspaceRecord | None:
        """Look up a workspace by ID only — for service role clients that bypass RLS."""
        rows = self.client.select(
            "workspaces",
            filters={"id": str(workspace_id)},
            limit=1,
        )
        return workspace_from_row(rows[0]) if rows else None

    def list_owned(self, user_id: UUID) -> list[WorkspaceRecord]:
        rows = self.client.select("workspaces", filters={"user_id": str(user_id)})
        return [workspace_from_row(row) for row in rows]

    def get_active(self, user_id: UUID) -> WorkspaceRecord | None:
        rows = self.client.select(
            "workspaces",
            filters={"user_id": str(user_id), "is_active": "true"},
            limit=1,
        )
        return workspace_from_row(rows[0]) if rows else None

    def activate(self, user_id: UUID, workspace_id: UUID) -> WorkspaceRecord:
        owned = self.get_owned(user_id, workspace_id)
        if owned is None:
            raise ValueError("Workspace not found")
        result = self.client.rpc(
            "activate_workspace",
            {"p_workspace_id": str(workspace_id)},
        )
        if not result:
            raise ValueError("Workspace could not be activated")
        row = result[0] if isinstance(result, list) else result
        return workspace_from_row(row)

    def acquire_lock(self, context: PlannerContext, ttl_seconds: int = 60) -> WorkspaceRecord:
        from datetime import datetime, timezone, timedelta
        
        ws_res = self.client.select("workspaces", filters={"id": str(context.workspace_id)})
        if not ws_res:
            raise ValueError("Workspace not found")
        w = ws_res[0]
        
        now = datetime.now(timezone.utc)
        locked_until_str = w.get("locked_until")
        locked_until = datetime.fromisoformat(locked_until_str) if locked_until_str else None
        
        if w.get("lock_owner") and locked_until and locked_until > now and w.get("lock_owner") != str(context.operation_id):
            raise WorkspaceBusyError("Workspace is already locked")
            
        update_res = self.client.update(
            "workspaces", 
            {
                "lock_owner": str(context.operation_id),
                "locked_until": (now + timedelta(seconds=ttl_seconds)).isoformat()
            },
            filters={"id": str(context.workspace_id)}
        )
        
        if not update_res:
            raise WorkspaceBusyError("Workspace is already locked")
            
        return workspace_from_row(update_res[0])

    def release_lock(self, context: PlannerContext) -> bool:
        update_res = self.client.update(
            "workspaces",
            {
                "lock_owner": None,
                "locked_until": None
            },
            filters={
                "id": str(context.workspace_id),
                "lock_owner": str(context.operation_id)
            }
        )
        return bool(update_res)

    def advance_revision(self, context: PlannerContext, checksum: str) -> WorkspaceRecord:
        rows = self.client.update(
            "workspaces",
            {
                "revision": context.source_revision + 1,
                "workbook_sha256": checksum,
            },
            filters={
                "id": str(context.workspace_id),
                "user_id": str(context.user_id),
                "revision": context.source_revision,
                "lock_owner": str(context.operation_id),
            },
        )
        if not rows:
            raise StaleWorkspaceRevisionError("Workspace revision changed before commit")
        return workspace_from_row(rows[0])
