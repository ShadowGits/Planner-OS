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
    # Column defaults from migration 0022. Without is_active a habit reads as
    # retired and none of its days show up.
    "habits": {
        "cadence": "daily",
        "days_of_week": [],
        "start_time": None,
        "estimated_minutes": None,
        "project_id": None,
        "end_date": None,
        "is_active": True,
    },
    "habit_overrides": {
        "moved_to": None,
        "start_time": None,
        "estimated_minutes": None,
        "skipped": False,
    },
}


class MemoryGateway:
    def __init__(self, workspace_row):
        self.tables = {"workspaces": [workspace_row]}

    def select(self, table, *, filters, columns="*", limit=None, query_string=None):
        rows = [row for row in self.tables.get(table, []) if self._matches(row, filters)]
        return rows[:limit] if limit else rows

    # Check constraints the real database enforces. Without these the fake
    # accepts values Postgres refuses, which is exactly how a habit tick
    # shipped writing a source the constraint rejects — every test passed and
    # the phone got a 500.
    CHECKS = {
        "task_completions": {"source": {"mcp", "telegram", "dashboard", "api"}},
        "planner_tasks": {"status": {"todo", "in_progress", "blocked", "done", "skipped"}},
    }

    def insert(self, table, payload):
        if isinstance(payload, list):
            return [self.insert(table, p)[0] for p in payload]
        for column, allowed in self.CHECKS.get(table, {}).items():
            value = dict(payload).get(column)
            if value is not None and value not in allowed:
                raise ValueError(
                    f"{table}.{column} violates its check constraint: {value!r} "
                    f"not in {sorted(allowed)}"
                )
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
        for key, value in filters.items():
            row_val = str(row.get(key)).casefold()
            if isinstance(value, list):
                if not any(row_val == str(v).casefold() for v in value):
                    return False
            else:
                if row_val != str(value).casefold():
                    return False
        return True


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
def runtime():
    return FakeRuntime()


@pytest.fixture()
def client(monkeypatch, runtime):
    monkeypatch.setenv("MCP_USER_ID", str(USER_ID))
    monkeypatch.setenv("PWA_ACCESS_KEY", "app-secret")
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    return TestClient(create_app(runtime=runtime, verifier=FakeVerifier()))


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


def test_patch_task_milestone_id(client) -> None:
    created = client.post(
        "/v2/day/tasks",
        json={"title": "Review SOP", "date": "2026-07-22"},
        headers=APP_KEY,
    )
    task_id = created.json()["data"]["task"]["id"]

    patched = client.patch(
        f"/v2/day/tasks/{task_id}",
        json={"milestone_id": "ms-123"},
        headers=APP_KEY,
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["task"]["milestone_id"] == "ms-123"

    # Clear milestone_id by setting to None is an update too
    patched2 = client.patch(
        f"/v2/day/tasks/{task_id}",
        json={"milestone_id": None},
        headers=APP_KEY,
    )
    assert patched2.status_code == 200


def test_week_endpoint(client) -> None:
    client.post(
        "/v2/day/tasks",
        json={"title": "Mon gym", "date": "2026-07-20"},
        headers=APP_KEY,
    )
    client.post(
        "/v2/day/tasks",
        json={"title": "Wed review", "date": "2026-07-22"},
        headers=APP_KEY,
    )

    resp = client.get("/v2/week?date=2026-07-21", headers=APP_KEY)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "week_start" in data
    titles = [i["title"] for i in data["items"]]
    assert "Mon gym" in titles
    assert "Wed review" in titles
    assert data["timezone"] == "Asia/Kolkata"

    # Without auth
    assert client.get("/v2/week").status_code == 401


def test_batch_delete_via_api(client) -> None:
    ids = []
    for title in ["A", "B", "C"]:
        r = client.post("/v2/day/tasks", json={"title": title, "date": "2026-07-22"}, headers=APP_KEY)
        ids.append(r.json()["data"]["task"]["id"])

    resp = client.post(
        "/v2/day/tasks/batch-delete",
        json={"task_ids": ids[:2]},
        headers=APP_KEY,
    )
    assert resp.status_code == 200

    day = client.get("/v2/day?date=2026-07-22", headers=APP_KEY)
    remaining = [i["title"] for i in day.json()["data"]["items"]]
    assert remaining == ["C"]

    # Without auth
    assert client.post("/v2/day/tasks/batch-delete", json={"task_ids": []}).status_code == 401


def test_static_shell_is_served(client) -> None:
    page = client.get("/app/")
    assert page.status_code == 200
    assert "Day" in page.text and "app.js" in page.text
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/styles.css").status_code == 200
    assert client.get("/app/manifest.webmanifest").status_code == 200
    assert client.get("/app/icon-180.png").status_code == 200


def test_a_slot_lands_on_the_day_it_was_split_from(client) -> None:
    """The PWA's split button posts `date`; an earlier version posted
    `scheduled_date`, which the model dropped, so every slot it made was
    created with no date and showed up nowhere."""
    created = client.post(
        "/v2/day/tasks",
        json={"title": "Limits", "date": "2026-07-22", "start_time": "09:00", "estimated_minutes": 90},
        headers=APP_KEY,
    )
    task_id = created.json()["data"]["task"]["id"]

    first = client.post(
        "/v2/day/tasks",
        json={
            "title": "Limits",
            "date": "2026-07-22",
            "start_time": "09:00",
            "estimated_minutes": 45,
            "parent_task_id": task_id,
        },
        headers=APP_KEY,
    )
    second = client.post(
        "/v2/day/tasks",
        json={
            "title": "Limits",
            "date": "2026-07-22",
            "estimated_minutes": 45,
            "parent_task_id": task_id,
        },
        headers=APP_KEY,
    )

    assert first.json()["data"]["task"]["scheduled_date"] == "2026-07-22"
    assert second.json()["data"]["task"]["scheduled_date"] == "2026-07-22"

    items = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"]

    # The task it was split from steps off the timeline, and the halves add
    # back up to the original 90 minutes rather than tripling it.
    assert [item["id"] for item in items] == [
        first.json()["data"]["task"]["id"],
        second.json()["data"]["task"]["id"],
    ]
    assert sum(item["estimated_minutes"] for item in items) == 90


def test_dragging_a_habit_past_midnight_lands_on_the_next_day(client, runtime) -> None:
    """The day view runs past midnight, so dragging something to half past
    midnight sends 24:30 — still tonight, as far as the screen is concerned.
    Tasks already understood that; habits rejected it as an impossible hour."""
    from planner_api.v2 import build_core

    core = build_core(runtime.service_client, USER_ID)
    core.habits.add_habit(
        "Wind down", recurrence_key="winddown", start_time="23:00",
        estimated_minutes=60, start_date="2026-07-20",
    )

    items = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"]
    occurrence = [i for i in items if i["title"] == "Wind down"][0]

    res = client.patch(
        f"/v2/day/tasks/{occurrence['id']}", json={"start_time": "24:30"}, headers=APP_KEY
    )
    assert res.status_code == 200, res.json()

    # it belongs to the small hours of the 23rd now, and the screen for the
    # 22nd still shows it because that day runs to 04:00
    on_23rd = [
        i for i in client.get("/v2/day?date=2026-07-23", headers=APP_KEY).json()["data"]["items"]
        if i["title"] == "Wind down" and i["start_time"] == "00:30"
    ]
    assert len(on_23rd) == 1


def test_the_pwa_can_tick_move_and_skip_a_habit_day(client, runtime) -> None:
    """A habit occurrence has no row, so the day view hands out a synthetic id
    and the PWA sends it straight back to the same endpoints."""
    from planner_api.v2 import build_core

    core = build_core(runtime.service_client, USER_ID)
    habit = core.habits.add_habit(
        "Gym", recurrence_key="gym", start_time="07:00", estimated_minutes=45,
        start_date="2026-07-20",
    )["data"]["habit"]

    items = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"]
    gym = [i for i in items if i["title"] == "Gym"][0]
    assert gym["id"].startswith("habit:")
    assert gym["done"] is False

    # tick
    assert client.patch(f"/v2/day/tasks/{gym['id']}", json={"done": True}, headers=APP_KEY).status_code == 200
    items = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"]
    assert [i for i in items if i["title"] == "Gym"][0]["done"] is True

    # move it to the next day
    assert client.patch(
        f"/v2/day/tasks/{gym['id']}",
        json={"scheduled_date": "2026-07-23", "start_time": "18:00"},
        headers=APP_KEY,
    ).status_code == 200
    assert not [i for i in client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"] if i["title"] == "Gym"]
    moved = [i for i in client.get("/v2/day?date=2026-07-23", headers=APP_KEY).json()["data"]["items"] if i["title"] == "Gym"]
    assert len(moved) == 2  # the 23rd's own occurrence, plus the one moved in
    assert "18:00" in {i["start_time"] for i in moved}

    # deleting one day skips it rather than destroying the habit
    twentyfourth = [
        i for i in client.get("/v2/day?date=2026-07-24", headers=APP_KEY).json()["data"]["items"]
        if i["title"] == "Gym"
    ][0]
    assert client.delete(f"/v2/day/tasks/{twentyfourth['id']}", headers=APP_KEY).status_code == 200
    assert not [i for i in client.get("/v2/day?date=2026-07-24", headers=APP_KEY).json()["data"]["items"] if i["title"] == "Gym"]
    assert core.habits.list_habits()["data"]["habits"][0]["id"] == habit["id"]
