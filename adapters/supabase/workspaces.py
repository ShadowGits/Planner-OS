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

    def list_owned(self, user_id: UUID) -> list[WorkspaceRecord]:
        rows = self.client.select("workspaces", filters={"user_id": str(user_id)})
        return [workspace_from_row(row) for row in rows]

    def get_active(self, user_id: UUID) -> WorkspaceRecord | None:
        rows = self.client.select(
            "workspaces",
            filters={"user_id": str(user_id), "is_active": True},
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
        result = self.client.rpc(
            "acquire_workspace_lock",
            {
                "p_workspace_id": str(context.workspace_id),
                "p_lock_owner": str(context.operation_id),
                "p_ttl_seconds": ttl_seconds,
            },
        )
        if not result:
            raise WorkspaceBusyError("Workspace is already locked")
        row = result[0] if isinstance(result, list) else result
        return workspace_from_row(row)

    def release_lock(self, context: PlannerContext) -> bool:
        return bool(
            self.client.rpc(
                "release_workspace_lock",
                {
                    "p_workspace_id": str(context.workspace_id),
                    "p_lock_owner": str(context.operation_id),
                },
            )
        )

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
