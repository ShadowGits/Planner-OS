"""Tests for the day-planner PWA surface: /v2/day API and the static shell."""

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
    "reminder_log": {"channel": "telegram", "payload": None},
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
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    return TestClient(create_app(runtime=FakeRuntime(), verifier=FakeVerifier()))


def test_day_requires_app_key(client) -> None:
    assert client.get("/v2/day").status_code == 401
    assert client.get("/v2/day", headers={"X-App-Key": "wrong"}).status_code == 401


def test_add_then_read_day(client) -> None:
    created = client.post(
        "/v2/day/tasks",
        json={"title": "German unit 3", "date": "2026-07-22", "start_time": "09:30", "estimated_minutes": 45},
        headers=APP_KEY,
    )
    assert created.status_code == 201

    day = client.get("/v2/day?date=2026-07-22", headers=APP_KEY)
    assert day.status_code == 200
    data = day.json()["data"]
    assert data["timezone"] == "Asia/Kolkata"
    assert data["total_count"] == 1 and data["done_count"] == 0
    item = data["items"][0]
    assert item["title"] == "German unit 3"
    assert item["start_time"] == "09:30"
    assert item["estimated_minutes"] == 45

    other = client.get("/v2/day?date=2026-07-23", headers=APP_KEY)
    assert other.json()["data"]["items"] == []


def test_tick_untick_and_reschedule(client) -> None:
    created = client.post(
        "/v2/day/tasks",
        json={"title": "Gym", "date": "2026-07-22", "start_time": "07:00"},
        headers=APP_KEY,
    )
    task_id = created.json()["data"]["task"]["id"]

    done = client.patch(f"/v2/day/tasks/{task_id}", json={"done": True}, headers=APP_KEY)
    assert done.status_code == 200
    assert done.json()["data"]["task"]["status"] == "done"

    undone = client.patch(f"/v2/day/tasks/{task_id}", json={"done": False}, headers=APP_KEY)
    assert undone.json()["data"]["task"]["status"] == "todo"

    moved = client.patch(
        f"/v2/day/tasks/{task_id}", json={"start_time": "18:15"}, headers=APP_KEY
    )
    assert moved.json()["data"]["task"]["start_time"] == "18:15"

    day = client.get("/v2/day?date=2026-07-22", headers=APP_KEY)
    item = day.json()["data"]["items"][0]
    assert item["start_time"] == "18:15" and item["done"] is False


def test_untick_removes_todays_completion_from_checklist(client, monkeypatch) -> None:
    from datetime import date

    today = date.today().isoformat()
    created = client.post(
        "/v2/day/tasks", json={"title": "Call HR", "date": today}, headers=APP_KEY
    )
    task_id = created.json()["data"]["task"]["id"]
    client.patch(f"/v2/day/tasks/{task_id}", json={"done": True}, headers=APP_KEY)
    client.patch(f"/v2/day/tasks/{task_id}", json={"done": False}, headers=APP_KEY)

    day = client.get(f"/v2/day?date={today}", headers=APP_KEY)
    assert day.json()["data"]["done_count"] == 0


def test_bad_patch_rejected(client) -> None:
    created = client.post(
        "/v2/day/tasks", json={"title": "X", "date": "2026-07-22"}, headers=APP_KEY
    )
    task_id = created.json()["data"]["task"]["id"]

    empty = client.patch(f"/v2/day/tasks/{task_id}", json={}, headers=APP_KEY)
    assert empty.status_code == 400

    bad_time = client.patch(
        f"/v2/day/tasks/{task_id}", json={"start_time": "25:99"}, headers=APP_KEY
    )
    assert bad_time.status_code == 400


def test_delete_day_task(client) -> None:
    created = client.post(
        "/v2/day/tasks", json={"title": "Temp", "date": "2026-07-22"}, headers=APP_KEY
    )
    task_id = created.json()["data"]["task"]["id"]

    gone = client.delete(f"/v2/day/tasks/{task_id}", headers=APP_KEY)
    assert gone.status_code == 200

    day = client.get("/v2/day?date=2026-07-22", headers=APP_KEY)
    assert day.json()["data"]["items"] == []

    assert client.delete(f"/v2/day/tasks/{task_id}", headers=APP_KEY).status_code == 404
    assert client.delete(f"/v2/day/tasks/{task_id}").status_code == 401


def test_static_shell_is_served(client) -> None:
    page = client.get("/app/")
    assert page.status_code == 200
    assert "Day" in page.text and "app.js" in page.text
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/styles.css").status_code == 200
    assert client.get("/app/manifest.webmanifest").status_code == 200
    assert client.get("/app/icon-180.png").status_code == 200
