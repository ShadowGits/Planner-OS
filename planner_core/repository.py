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
    # Service-role callers must validate reference ownership too: a UUID-only
    # SQL foreign key verifies existence, but not that both rows share a tenant.
    _REFERENCES = {
        "milestones": {"project_id": "projects"},
        "planner_tasks": {"project_id": "projects", "milestone_id": "milestones",
                          "parent_task_id": "planner_tasks", "depends_on": "planner_tasks"},
        "task_completions": {"task_id": "planner_tasks"},
        "project_files": {"project_id": "projects"},
        "project_qna": {"project_id": "projects"},
        "project_widgets": {"project_id": "projects"},
        "monthly_goals": {"project_id": "projects"},
        "weekly_goals": {"project_id": "projects"},
        "habits": {"project_id": "projects"},
        "habit_completions": {"habit_id": "habits"},
        "habit_overrides": {"habit_id": "habits"},
        "finance_logs": {"goal_id": "finance_goals", "recurring_id": "finance_recurring", "plan_item_id": "finance_plan_items"},
        "finance_plan_items": {"plan_id": "finance_plans"},
    }

    def _validate_references(self, table, payload, checked=None) -> None:
        checked = checked if checked is not None else set()
        for field, target in self._REFERENCES.get(table, {}).items():
            value = payload.get(field)
            if value is None:
                continue
            reference = (target, str(value))
            if reference not in checked:
                if self.get_row(target, str(value)) is None:
                    raise PlannerCoreError(f"{field} was not found in this workspace")
                checked.add(reference)

    def __init__(self, gateway: Any, user_id: UUID, workspace_id: UUID) -> None:
        self.gateway = gateway
        self.user_id = user_id
        self.workspace_id = workspace_id

    def _tenant(self) -> dict[str, str]:
        return {"user_id": str(self.user_id), "workspace_id": str(self.workspace_id)}

    def list_rows(
        self,
        table: str,
        extra_filters: Mapping[str, Any] | None = None,
        query_string: str | None = None,
        columns: str = "*",
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        """Rows matching the filters, or [] if the read fails.

        Swallowing the failure keeps a screen rendering when one panel's query
        breaks, but it makes a failed read indistinguishable from an empty
        table. That is fine for something that only gets displayed and actively
        dangerous for anything that decides whether to write: a dedup set that
        comes back empty because the database hiccuped means every record looks
        new, and the caller duplicates the lot.

        Pass strict=True from those callers so the failure propagates and the
        write is abandoned instead of doubling the data.
        """
        try:
            return self.gateway.select(table, filters={**dict(extra_filters or {}), **self._tenant()}, query_string=query_string, columns=columns)
        except Exception:
            if strict:
                raise
            return []

    def get_row(self, table: str, row_id: str) -> dict[str, Any] | None:
        rows = self.gateway.select(table, filters={**self._tenant(), "id": row_id}, limit=1)
        return rows[0] if rows else None

    def insert_row(self, table: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._validate_references(table, payload)
        cleaned = {key: value for key, value in payload.items() if value is not None}
        rows = self.gateway.insert(table, {**cleaned, **self._tenant()})
        if not rows:
            raise PlannerCoreError(f"Insert into {table} returned no row")
        return rows[0]

    def insert_rows(self, table: str, payloads: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        checked = set()
        for payload in payloads:
            self._validate_references(table, payload, checked)
        cleaned_payloads = [
            {**{k: v for k, v in p.items() if v is not None}, **self._tenant()}
            for p in payloads
        ]
        rows = self.gateway.insert(table, cleaned_payloads)
        if not rows:
            raise PlannerCoreError(f"Insert into {table} returned no rows")
        return rows

    def update_row(self, table: str, row_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._validate_references(table, payload)
        rows = self.gateway.update(
            table,
            {key: value for key, value in payload.items() if key not in {"id", "user_id", "workspace_id"}},
            filters={**self._tenant(), "id": row_id},
        )
        if not rows:
            raise PlannerCoreError(f"{table} row was not found: {row_id}")
        return rows[0]

    def delete_row(self, table: str, row_id: str) -> None:
        self.gateway.delete(table, filters={**self._tenant(), "id": row_id})

    def delete_rows(self, table: str, extra_filters: Mapping[str, Any]) -> None:
        self.gateway.delete(table, filters={**extra_filters, **self._tenant()})

    def call_function(self, name: str, payload: Mapping[str, Any] | None = None) -> Any:
        """Invoke a Postgres function with this tenant's ids already applied."""
        return self.gateway.rpc(
            name,
            {
                **dict(payload or {}),
                "p_user_id": str(self.user_id),
                "p_workspace_id": str(self.workspace_id),
            },
        )
