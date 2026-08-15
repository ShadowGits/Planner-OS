"""Tests for the Postgres → Google Calendar bridge (/v2/calendar/sync)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from planner_api.app import create_app
# _blocks_for_day moved to planner_core.services when the day-view logic was
# consolidated there; the bridge imports it from the same place.
from planner_core.services import _blocks_for_day
from planner_integrations.google_calendar import CalendarSyncResult
from planner_platform.google_oauth import GoogleConnectionRequiredError

USER_ID = uuid4()
WORKSPACE_ID = uuid4()


# ---------------------------------------------------------------------------
# pure mapping
# ---------------------------------------------------------------------------

def test_blocks_for_day_maps_timed_tasks_and_skips_untimed() -> None:
    items = [
        {"id": "t1", "title": "German unit 3", "start_time": "09:30", "estimated_minutes": 45},
        {"id": "t2", "title": "Inbox idea", "start_time": None, "estimated_minutes": 30},
        {"id": "t3", "title": "Gym", "start_time": "07:00", "estimated_minutes": None},
    ]
    blocks = _blocks_for_day(items, date(2026, 7, 22), "Asia/Kolkata")

    assert len(blocks) == 2  # the untimed task is skipped
    german = blocks[0]
    assert german.title == "German unit 3"
    assert german.start == datetime(2026, 7, 22, 9, 30, tzinfo=german.start.tzinfo)
    assert (german.end - german.start).total_seconds() == 45 * 60
    # event identity is tied to the task id so moves update, not duplicate
    assert german.metadata["planner_block_id"] == "t1"
    assert german.metadata["source_task_id"] == "t1"
    # missing estimate falls back to 30 minutes
    assert (blocks[1].end - blocks[1].start).total_seconds() == 30 * 60


# ---------------------------------------------------------------------------
# endpoint
# ---------------------------------------------------------------------------

class MemoryGateway:
    def __init__(self, workspace_row):
        self.tables = {"workspaces": [workspace_row]}

    def select(self, table, *, filters, columns="*", limit=None):
        rows = [row for row in self.tables.get(table, []) if self._matches(row, filters)]
        return rows[:limit] if limit else rows

    def insert(self, table, payload):
        row = {"id": str(uuid4()), **dict(payload)}
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
        self.tables[table] = [r for r in self.tables.get(table, []) if not self._matches(r, filters)]

    @staticmethod
    def _matches(row, filters):
        return all(str(row.get(k)).casefold() == str(v).casefold() for k, v in filters.items())


def _workspace_row():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(WORKSPACE_ID),
        "user_id": str(USER_ID),
        "name": "Main",
        "timezone": "Asia/Kolkata",
        "active_execution_target": "google_calendar",
        "workbook_bucket": "planner-workbooks",
        "workbook_key": "x",
        "workbook_sha256": None,
        "revision": 0,
        "settings_revision": 0,
        "is_active": True,
        "lock_owner": None,
        "locked_until": None,
        "created_at": now,
        "updated_at": now,
    }


class FakeCalendarClient:
    def __init__(self):
        self.calls = 0

    def sync_plan(self, plan, *, start=None, end=None, scope=None):
        self.calls += 1
        return CalendarSyncResult(created=0, updated=0, deleted=0, unchanged=0)


class FakeRuntime:
    """FakeRuntime whose google_client_factory returns `factory` (a callable)."""

    def __init__(self, factory):
        self.service_client = MemoryGateway(_workspace_row())
        self._factory = factory

    def google_client_factory(self):
        return self._factory


class FakeVerifier:
    def verify(self, token):
        from planner_platform.auth import AuthenticatedUser, AuthenticationError

        if token != "valid-token":
            raise AuthenticationError("bad token")
        return AuthenticatedUser(user_id=USER_ID, access_token=None)


def _client(monkeypatch, factory):
    monkeypatch.setenv("MCP_USER_ID", str(USER_ID))
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    return TestClient(create_app(runtime=FakeRuntime(factory), verifier=FakeVerifier()))


CRON = {"X-Cron-Key": "cron-secret"}


def test_sync_requires_cron_key(monkeypatch) -> None:
    client = _client(monkeypatch, lambda context: FakeCalendarClient())
    assert client.post("/v2/calendar/sync").status_code == 401
    assert client.post("/v2/calendar/sync", headers={"X-Cron-Key": "nope"}).status_code == 401


def test_sync_reports_google_not_connected(monkeypatch) -> None:
    def factory(context):
        raise GoogleConnectionRequiredError("Connect Google Calendar for this workspace first")

    client = _client(monkeypatch, factory)
    res = client.post("/v2/calendar/sync", headers=CRON)
    assert res.status_code == 409
    assert "GOOGLE_NOT_CONNECTED" in res.json()["errors"]


def test_sync_runs_once_per_day_in_window(monkeypatch) -> None:
    fake = FakeCalendarClient()
    client = _client(monkeypatch, lambda context: fake)
    res = client.post("/v2/calendar/sync?days=3", headers=CRON)
    assert res.status_code == 200
    body = res.json()
    assert body["data"]["days"] == 3
    assert fake.calls == 3  # one reconcile per day in the window
