"""Tests for the v2 API: metrics endpoint, reminder cron auth, Telegram webhook."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from planner_api.app import create_app
from planner_platform.auth import AuthenticatedUser

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
        rows = [
            row
            for row in self.tables.get(table, [])
            if all(str(row.get(key)).casefold() == str(value).casefold() for key, value in filters.items())
        ]
        return rows[:limit] if limit else rows

    def insert(self, table, payload):
        row = {"id": str(uuid4()), **TABLE_DEFAULTS.get(table, {}), **dict(payload)}
        self.tables.setdefault(table, []).append(row)
        return [dict(row)]

    def update(self, table, payload, *, filters):
        updated = []
        for row in self.tables.get(table, []):
            if all(str(row.get(key)).casefold() == str(value).casefold() for key, value in filters.items()):
                row.update(payload)
                updated.append(dict(row))
        return updated

    def delete(self, table, *, filters):
        self.tables[table] = [
            row
            for row in self.tables.get(table, [])
            if not all(str(row.get(key)).casefold() == str(value).casefold() for key, value in filters.items())
        ]


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
        if token != "valid-token":
            from planner_platform.auth import AuthenticationError

            raise AuthenticationError("bad token")
        return AuthenticatedUser(user_id=USER_ID, access_token=None)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("MCP_USER_ID", str(USER_ID))
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "hook-secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    return TestClient(create_app(runtime=FakeRuntime(), verifier=FakeVerifier()))


def test_metrics_requires_auth_and_returns_snapshot(client) -> None:
    assert client.get("/v2/metrics").status_code == 401

    response = client.get("/v2/metrics", headers={"Authorization": "Bearer valid-token"})

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["snapshot"]["timezone"] == "Asia/Kolkata"
    assert "flat" in body and body["snapshot"]["totals"]["open_tasks"] == 0


def test_reminders_cron_rejects_bad_key_and_reports_unconfigured_telegram(client) -> None:
    assert client.post("/v2/reminders/run").status_code == 401
    assert client.post("/v2/reminders/run", headers={"X-Cron-Key": "wrong"}).status_code == 401

    response = client.post("/v2/reminders/run", headers={"X-Cron-Key": "cron-secret"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sent"] == []
    assert all(item["error"] == "TELEGRAM_NOT_CONFIGURED" for item in data["failed"])


def test_telegram_webhook_secret_chat_gating_and_done_flow(client) -> None:
    assert client.post("/v2/telegram/webhook", json={}).status_code == 401

    headers = {"X-Telegram-Bot-Api-Secret-Token": "hook-secret"}
    stranger = {"message": {"chat": {"id": 999}, "text": "done anything"}}
    assert client.post("/v2/telegram/webhook", json=stranger, headers=headers).json()["message"] == "Ignored"

    update = {"message": {"chat": {"id": 42}, "text": "status"}}
    response = client.post("/v2/telegram/webhook", json=update, headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["action"] == "status"


def test_today_command_renders_checklist_without_error(client) -> None:
    headers = {"X-Telegram-Bot-Api-Secret-Token": "hook-secret"}
    update = {"message": {"chat": {"id": 42}, "text": "today"}}

    response = client.post("/v2/telegram/webhook", json=update, headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["action"] == "today"
