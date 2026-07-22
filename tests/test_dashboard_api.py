"""Tests for the dashboard read surface: /v2/dashboard/metrics."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from planner_api.app import create_app

USER_ID = uuid4()
WORKSPACE_ID = uuid4()

TABLE_DEFAULTS = {
    "projects": {"status": "active", "track": None, "description": None, "target_date": None},
    "milestones": {"status": "not_started", "target_date": None, "sort_order": 0, "notes": None},
    "planner_tasks": {
        "status": "todo",
        "priority": "medium",
        "project_id": None,
        "milestone_id": None,
        "due_date": None,
        "scheduled_date": None,
        "start_time": None,
        "estimated_minutes": None,
        "recurrence_key": None,
        "depends_on": None,
        "notes": None,
        "completed_at": None,
    },
    "task_completions": {"task_id": None, "recurrence_key": None, "note": None},
}


class MemoryGateway:
    def __init__(self, workspace_row):
        self.tables = {"workspaces": [workspace_row]}

    def select(self, table, *, filters, columns="*", limit=None):
        rows = [row for row in self.tables.get(table, []) if self._matches(row, filters)]
        return rows[:limit] if limit else rows

    def insert(self, table, payload):
        row = {"id": str(uuid4()), **TABLE_DEFAULTS.get(table, {}), **dict(payload)}
        self.tables.setdefault(table, []).append(row)
        return [dict(row)]

    def update(self, table, payload, *, filters):
        updated = []
        for row in self.tables.get(table, []):
            if self._matches(row, filters):
                row.update(payload)
                updated.append(dict(row))
        return updated

    def delete(self, table, *, filters):
        self.tables[table] = [
            row for row in self.tables.get(table, []) if not self._matches(row, filters)
        ]

    @staticmethod
    def _matches(row, filters):
        return all(
            str(row.get(key)).casefold() == str(value).casefold()
            for key, value in filters.items()
        )


def _workspace_row():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(WORKSPACE_ID),
        "user_id": str(USER_ID),
        "name": "Main",
        "timezone": "Asia/Kolkata",
        "active_execution_target": "none",
        "workbook_bucket": "planner-workbooks",
        "workbook_key": f"{USER_ID}/{WORKSPACE_ID}/current.xlsx",
        "workbook_sha256": None,
        "revision": 0,
        "settings_revision": 0,
        "is_active": True,
        "lock_owner": None,
        "locked_until": None,
        "created_at": now,
        "updated_at": now,
    }


class FakeRuntime:
    def __init__(self):
        self.service_client = MemoryGateway(_workspace_row())


class FakeVerifier:
    def verify(self, token):
        from planner_platform.auth import AuthenticatedUser, AuthenticationError

        if token != "valid-token":
            raise AuthenticationError("bad token")
        return AuthenticatedUser(user_id=USER_ID, access_token=None)


APP_KEY = {"X-App-Key": "app-secret"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("MCP_USER_ID", str(USER_ID))
    monkeypatch.setenv("PWA_ACCESS_KEY", "app-secret")
    monkeypatch.delenv("DASHBOARD_ACCESS_KEY", raising=False)
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    return TestClient(create_app(runtime=FakeRuntime(), verifier=FakeVerifier()))


def test_dashboard_metrics_requires_app_key(client) -> None:
    assert client.get("/v2/dashboard/metrics").status_code == 401
    assert client.get("/v2/dashboard/metrics", headers={"X-App-Key": "wrong"}).status_code == 401


def test_dashboard_metrics_returns_snapshot_and_flat(client) -> None:
    res = client.get("/v2/dashboard/metrics", headers=APP_KEY)
    assert res.status_code == 200
    data = res.json()["data"]
    assert "snapshot" in data and "flat" in data
    snapshot = data["snapshot"]
    assert snapshot["timezone"] == "Asia/Kolkata"
    assert "totals" in snapshot and "projects" in snapshot
    assert snapshot["totals"]["open_tasks"] == 0


def test_dashboard_metrics_uses_dedicated_key_when_set(client, monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_ACCESS_KEY", "dash-only")
    # PWA_ACCESS_KEY no longer accepted once a dedicated key exists
    assert client.get("/v2/dashboard/metrics", headers=APP_KEY).status_code == 401
    assert client.get(
        "/v2/dashboard/metrics", headers={"X-App-Key": "dash-only"}
    ).status_code == 200
