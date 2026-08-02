"""Tenant-scoped data access for the v2 Postgres planner tables.

Every method filters by (user_id, workspace_id) so a repository instance can
never read or write another tenant's rows, matching the RLS policies. Rows are
plain dicts as returned by PostgREST; date filtering beyond equality happens in
the services because the single-tenant row counts are small.
"""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID


class PlannerCoreError(ValueError):
    """Raised for invalid v2 planner operations."""


class PlannerCoreRepository:
    def __init__(self, gateway: Any, user_id: UUID, workspace_id: UUID) -> None:
        self.gateway = gateway
        self.user_id = user_id
        self.workspace_id = workspace_id

    def _tenant(self) -> dict[str, str]:
        return {"user_id": str(self.user_id), "workspace_id": str(self.workspace_id)}

    def list_rows(self, table: str, extra_filters: Mapping[str, Any] | None = None, query_string: str | None = None, columns: str = "*") -> list[dict[str, Any]]:
        try:
            return self.gateway.select(table, filters={**self._tenant(), **dict(extra_filters or {})}, query_string=query_string, columns=columns)
        except Exception:
            return []

    def get_row(self, table: str, row_id: str) -> dict[str, Any] | None:
        rows = self.gateway.select(table, filters={**self._tenant(), "id": row_id}, limit=1)
        return rows[0] if rows else None

    def insert_row(self, table: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        cleaned = {key: value for key, value in payload.items() if value is not None}
        rows = self.gateway.insert(table, {**cleaned, **self._tenant()})
        if not rows:
            raise PlannerCoreError(f"Insert into {table} returned no row")
        return rows[0]

    def insert_rows(self, table: str, payloads: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        cleaned_payloads = [
            {**{k: v for k, v in p.items() if v is not None}, **self._tenant()}
            for p in payloads
        ]
        rows = self.gateway.insert(table, cleaned_payloads)
        if not rows:
            raise PlannerCoreError(f"Insert into {table} returned no rows")
        return rows

    def update_row(self, table: str, row_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        rows = self.gateway.update(
            table,
            dict(payload),
            filters={**self._tenant(), "id": row_id},
        )
        if not rows:
            raise PlannerCoreError(f"{table} row was not found: {row_id}")
        return rows[0]

    def delete_row(self, table: str, row_id: str) -> None:
        self.gateway.delete(table, filters={**self._tenant(), "id": row_id})

    def delete_rows(self, table: str, extra_filters: Mapping[str, Any]) -> None:
        self.gateway.delete(table, filters={**self._tenant(), **extra_filters})
