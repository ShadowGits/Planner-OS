"""Tenant-scoped Supabase operation repository."""

from __future__ import annotations

from typing import Any

from adapters.supabase.client import SupabaseGateway
from planner_platform.context import PlannerContext


class SupabaseOperationRepository:
    def __init__(self, client: SupabaseGateway) -> None:
        self.client = client

    def record(
        self,
        context: PlannerContext,
        *,
        tool_name: str,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        filters = {
            "id": str(context.operation_id),
            "user_id": str(context.user_id),
            "workspace_id": str(context.workspace_id),
        }
        existing = self.client.select("planner_operations", filters=filters, limit=1)
        payload = {"status": status, "sanitized_result": result or {}}
        if existing:
            self.client.update("planner_operations", payload, filters=filters)
            return
        self.client.insert(
            "planner_operations",
            {
                **filters,
                "tool_name": tool_name,
                **payload,
            },
        )

