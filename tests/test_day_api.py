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


def test_patch_task_milestone_id(client, runtime) -> None:
    runtime.service_client.insert("milestones", {"id": "ms-123", "user_id": str(USER_ID), "workspace_id": str(WORKSPACE_ID), "name": "Owned milestone"})
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


def test_starring_a_habit_day_sticks(client, runtime) -> None:
    """Starring a habit used to tick on screen and spring straight back.

    A habit occurrence has no task row, so the patch fell through the habit
    branch — which only understood done, date and time — to "nothing to
    change", and the app reverted its optimistic star.
    """
    from planner_api.v2 import build_core

    core = build_core(runtime.service_client, USER_ID)
    core.habits.add_habit(
        "Gym", recurrence_key="gym", start_time="07:00", estimated_minutes=45,
        start_date="2026-07-20",
    )

    items = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"]
    gym = [i for i in items if i["title"] == "Gym"][0]
    assert gym["starred"] is False

    res = client.patch(f"/v2/day/tasks/{gym['id']}", json={"starred": True}, headers=APP_KEY)
    assert res.status_code == 200, res.json()

    day = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]
    assert [i for i in day["items"] if i["title"] == "Gym"][0]["starred"] is True
    assert day["starred_total"] == 1

    # One day only: the rule is untouched, so tomorrow's gym is not a win.
    other = client.get("/v2/day?date=2026-07-23", headers=APP_KEY).json()["data"]
    assert [i for i in other["items"] if i["title"] == "Gym"][0]["starred"] is False

    # And it can be taken back off.
    assert client.patch(
        f"/v2/day/tasks/{gym['id']}", json={"starred": False}, headers=APP_KEY
    ).status_code == 200
    back = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]
    assert [i for i in back["items"] if i["title"] == "Gym"][0]["starred"] is False


def test_renaming_a_habit_day_renames_the_habit(client, runtime) -> None:
    """A rename from either app used to be dropped for a habit: the habit
    branch only understood done, date, time and star, so a rename alone came
    back "nothing to change" and the app undid it, and a rename with a time
    change kept the old name."""
    from planner_api.v2 import build_core

    core = build_core(runtime.service_client, USER_ID)
    core.habits.add_habit(
        "Gym", recurrence_key="gym", start_time="07:00", estimated_minutes=45,
        start_date="2026-07-20",
    )
    items = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"]
    gym = [i for i in items if i["title"] == "Gym"][0]

    res = client.patch(f"/v2/day/tasks/{gym['id']}", json={"title": "Gym and cardio"}, headers=APP_KEY)
    assert res.status_code == 200, res.json()
    for day in ("2026-07-22", "2026-07-23"):
        titles = [i["title"] for i in client.get(f"/v2/day?date={day}", headers=APP_KEY).json()["data"]["items"]]
        assert "Gym and cardio" in titles and "Gym" not in titles, (day, titles)

    # As Android saves an edit: the name with the day's date, time and length.
    res = client.patch(
        f"/v2/day/tasks/{gym['id']}",
        json={"title": "Strength", "scheduled_date": "2026-07-22", "start_time": "08:00", "estimated_minutes": 45},
        headers=APP_KEY,
    )
    assert res.status_code == 200, res.json()
    moved = [i for i in client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"] if i["title"] == "Strength"]
    assert moved and moved[0]["start_time"].startswith("08:00"), moved

    blank = client.patch(f"/v2/day/tasks/{gym['id']}", json={"title": "  "}, headers=APP_KEY)
    assert blank.status_code == 400


def test_renaming_a_task_alone_sticks(client) -> None:
    """The iPhone editor sends only what changed, so a rename is a patch of
    the title and nothing else."""
    created = client.post(
        "/v2/day/tasks", json={"title": "Draft SOP", "date": "2026-07-22", "start_time": "10:00"}, headers=APP_KEY
    ).json()["data"]["task"]
    res = client.patch(f"/v2/day/tasks/{created['id']}", json={"title": "Draft SOP for TUM"}, headers=APP_KEY)
    assert res.status_code == 200, res.json()
    items = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"]
    renamed = [i for i in items if i["id"] == created["id"]][0]
    assert renamed["title"] == "Draft SOP for TUM" and renamed["start_time"].startswith("10:00")
    assert client.patch(f"/v2/day/tasks/{created['id']}", json={"title": " "}, headers=APP_KEY).status_code == 400


def test_push_test_requires_auth_and_forwards_selected_device(client, monkeypatch):
    calls = []
    def send(*args, **kwargs):
        calls.append(kwargs)
        return {"sent": 1, "failed": 0, "expired": 0}
    monkeypatch.setattr("planner_core.push.send_push_to_all", send)
    endpoint = "https://web.push.apple.com/test-device"
    assert client.post("/v2/day/push/test", json={"endpoint": endpoint}).status_code == 401
    response = client.post("/v2/day/push/test", headers=APP_KEY, json={"endpoint": endpoint})
    assert response.status_code == 200
    assert response.json()["data"]["sent"] == 1
    assert calls == [{"url": "/app/", "endpoint": endpoint}]
    assert client.post("/v2/day/push/test", headers=APP_KEY, json={"endpoint": "http://127.0.0.1/private"}).status_code == 400
    assert len(calls) == 1


def test_rotated_subscription_preserves_other_browser_installations(client, runtime):
    def register(endpoint, label):
        return client.post("/v2/day/push/subscribe", headers=APP_KEY, json={
            "endpoint": endpoint, "keys": {"p256dh": "key", "auth": "auth"}, "device_label": label,
        })
    assert register("https://web.push.apple.com/first", "Same browser [installation-one]").status_code == 200
    assert register("https://web.push.apple.com/second", "Same browser [installation-two]").status_code == 200
    assert register("https://web.push.apple.com/rotated", "Same browser [installation-one]").status_code == 200
    rows = runtime.service_client.tables["push_subscriptions"]
    assert {row["endpoint"] for row in rows} == {"https://web.push.apple.com/second", "https://web.push.apple.com/rotated"}


def _task_row(runtime, task_id: str) -> dict:
    return next(row for row in runtime.service_client.tables["planner_tasks"] if row["id"] == task_id)


def _make_task(client, runtime, title: str, **fields) -> str:
    created = client.post(
        "/v2/day/tasks", json={"title": title, "date": "2026-07-22"}, headers=APP_KEY
    )
    task_id = created.json()["data"]["task"]["id"]
    _task_row(runtime, task_id).update(fields)
    return task_id


def test_triage_move_takes_a_past_deadline_task_out_of_the_backlog(client, runtime) -> None:
    """Planning a late task for a new day is not enough on its own.

    The inbox lists a task by its deadline as well as its slot, so a task whose
    deadline has passed would stay in the overdue pile after a move that only
    changed its day. Moving it has to carry the broken deadline along.
    """
    from datetime import date, timedelta

    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    late = _make_task(
        client, runtime, "Collect APS documents",
        due_date=(today - timedelta(days=40)).isoformat(),
        scheduled_date=(today - timedelta(days=40)).isoformat(),
        start_time="14:00",
    )
    still_ahead = _make_task(
        client, runtime, "Send LOR follow-up",
        due_date=(today + timedelta(days=10)).isoformat(),
        scheduled_date=(today - timedelta(days=2)).isoformat(),
    )

    resp = client.post(
        "/v2/day/tasks/triage",
        json={"task_ids": [late, still_ahead], "action": "move", "to_date": tomorrow},
        headers=APP_KEY,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert sorted(data["updated"]) == sorted([late, still_ahead])
    assert data["deadline_moved"] == [late]

    moved = _task_row(runtime, late)
    assert moved["scheduled_date"] == tomorrow
    assert moved["due_date"] == tomorrow, "a passed deadline moves with the task"
    assert moved["start_time"] is None, "it lands untimed, not on top of that day's plan"

    kept = _task_row(runtime, still_ahead)
    assert kept["scheduled_date"] == tomorrow
    assert kept["due_date"] == (today + timedelta(days=10)).isoformat(), "a future deadline is real; leave it"


def test_triage_drop_skips_rather_than_deletes(client, runtime) -> None:
    keep = _make_task(client, runtime, "Keep me")
    drop = _make_task(client, runtime, "Drop me")
    finished = _make_task(client, runtime, "Already done", status="done")

    resp = client.post(
        "/v2/day/tasks/triage",
        json={"task_ids": [drop, finished], "action": "drop"},
        headers=APP_KEY,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["updated"] == [drop]
    assert data["already_closed"] == [finished]

    assert _task_row(runtime, drop)["status"] == "skipped", "dropped, with its history kept"
    assert _task_row(runtime, finished)["status"] == "done", "a finished task is not reopened as skipped"
    assert _task_row(runtime, keep)["status"] == "todo"


def test_triage_refuses_bad_input(client, runtime) -> None:
    from datetime import date, timedelta

    task = _make_task(client, runtime, "Anything")
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    cases = [
        {"task_ids": [task], "action": "move"},  # no day to move to
        {"task_ids": [task], "action": "move", "to_date": yesterday},  # straight back into the backlog
        {"task_ids": [task], "action": "archive"},
        {"task_ids": ["1,2)"], "action": "drop"},  # would rewrite the PostgREST filter
    ]
    for body in cases:
        assert client.post("/v2/day/tasks/triage", json=body, headers=APP_KEY).status_code == 400, body
    assert _task_row(runtime, task)["status"] == "todo"

    assert client.post(
        "/v2/day/tasks/triage", json={"task_ids": [task], "action": "drop"}
    ).status_code == 401


def test_week_items_carry_their_milestone(client, runtime) -> None:
    task = _make_task(client, runtime, "Screen 10 colleges", milestone_id="ms-shortlist", starred=True)
    items = client.get("/v2/week?date=2026-07-22", headers=APP_KEY).json()["data"]["items"]
    item = next(i for i in items if i["id"] == task)
    assert item["milestone_id"] == "ms-shortlist"
    assert item["starred"] is True


def _milestone(runtime, milestone_id: str, target: str | None, status: str = "in_progress") -> dict:
    row = {
        "id": milestone_id, "user_id": str(USER_ID), "workspace_id": str(WORKSPACE_ID),
        "project_id": "proj-1", "name": f"Milestone {milestone_id}", "status": status,
        "target_date": target,
    }
    runtime.service_client.insert("milestones", row)
    return next(m for m in runtime.service_client.tables["milestones"] if m["id"] == milestone_id)


def test_moving_a_task_past_its_milestone_extends_the_milestone(client, runtime) -> None:
    """A milestone cannot end before its own work does."""
    milestone = _milestone(runtime, "ms-short", "2026-11-02")
    task = _make_task(client, runtime, "Cut list to 20", milestone_id="ms-short", scheduled_date="2026-11-01")

    resp = client.patch(f"/v2/day/tasks/{task}", json={"scheduled_date": "2026-11-09"}, headers=APP_KEY)
    assert resp.status_code == 200, resp.text
    assert milestone["target_date"] == "2026-11-09"
    assert resp.json()["data"]["milestones_extended"] == [
        {"milestone_id": "ms-short", "name": "Milestone ms-short", "from": "2026-11-02", "to": "2026-11-09"}
    ]


def test_the_new_target_is_the_milestones_last_task_not_just_the_moved_one(client, runtime) -> None:
    milestone = _milestone(runtime, "ms-last", "2026-11-02")
    _make_task(client, runtime, "Already later", milestone_id="ms-last", scheduled_date="2026-11-20")
    _make_task(client, runtime, "Finished, ignored", milestone_id="ms-last", scheduled_date="2026-12-31", status="done")
    task = _make_task(client, runtime, "Moved", milestone_id="ms-last", scheduled_date="2026-11-01")

    client.patch(f"/v2/day/tasks/{task}", json={"scheduled_date": "2026-11-05"}, headers=APP_KEY)
    assert milestone["target_date"] == "2026-11-20", "ends with its last open task"


def test_milestones_are_only_ever_extended(client, runtime) -> None:
    earlier = _milestone(runtime, "ms-earlier", "2026-11-30")
    done = _milestone(runtime, "ms-done", "2026-10-01", status="done")
    undated = _milestone(runtime, "ms-undated", None)
    a = _make_task(client, runtime, "Pulled in", milestone_id="ms-earlier", scheduled_date="2026-11-25")
    b = _make_task(client, runtime, "Leftover", milestone_id="ms-done", scheduled_date="2026-10-01")
    c = _make_task(client, runtime, "No target", milestone_id="ms-undated", scheduled_date="2026-10-01")

    for task, day in ((a, "2026-11-03"), (b, "2026-12-01"), (c, "2026-12-01")):
        resp = client.patch(f"/v2/day/tasks/{task}", json={"scheduled_date": day}, headers=APP_KEY)
        assert resp.json()["data"]["milestones_extended"] == []
    assert earlier["target_date"] == "2026-11-30", "moving work earlier does not pull a milestone in"
    assert done["target_date"] == "2026-10-01", "a finished milestone keeps its date"
    assert undated["target_date"] is None, "no target is not invented"


def test_triage_moves_extend_milestones_too(client, runtime) -> None:
    from datetime import date, timedelta

    target = (date.today() + timedelta(days=2)).isoformat()
    later = (date.today() + timedelta(days=9)).isoformat()
    milestone = _milestone(runtime, "ms-triage", target)
    task = _make_task(
        client, runtime, "Late task", milestone_id="ms-triage",
        due_date=(date.today() - timedelta(days=3)).isoformat(),
    )

    resp = client.post(
        "/v2/day/tasks/triage",
        json={"task_ids": [task], "action": "move", "to_date": later},
        headers=APP_KEY,
    )
    assert resp.status_code == 200, resp.text
    assert milestone["target_date"] == later
    assert resp.json()["data"]["milestones_extended"][0]["to"] == later


# --- Fitting the day: giving loose ends a time that does not clash ---------


def _make(client, title, **fields):
    created = client.post(
        "/v2/day/tasks", json={"title": title, "date": "2026-07-22", **fields}, headers=APP_KEY
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]["task"]["id"]


def _times(client, date="2026-07-22"):
    day = client.get(f"/v2/day?date={date}", headers=APP_KEY)
    return {item["title"]: item["start_time"] for item in day.json()["data"]["items"]}


def test_fit_requires_app_key(client) -> None:
    assert client.post("/v2/day/fit", json={}).status_code == 401


def test_fit_gives_an_untimed_task_a_time(client) -> None:
    _make(client, "Write the brief", estimated_minutes=60)
    answer = client.post("/v2/day/fit", json={"date": "2026-07-22"}, headers=APP_KEY)
    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    assert data["placed_count"] == 1
    assert data["placements"][0]["start_time"] == "07:00"
    assert data["saved"] == [data["placements"][0]["id"]]
    # And it really was written, not just worked out.
    assert _times(client)["Write the brief"] == "07:00"


def test_fit_never_books_over_what_is_already_there(client) -> None:
    _make(client, "Appointment", start_time="11:30", estimated_minutes=60)
    _make(client, "Deep work", estimated_minutes=120)
    client.post("/v2/day/fit", json={"date": "2026-07-22"}, headers=APP_KEY)
    times = _times(client)
    assert times["Appointment"] == "11:30"
    start = times["Deep work"]
    # Two hours from 07:00 ends at 09:00, well clear of the appointment.
    assert start == "07:00"


def test_fit_queues_several_tasks_without_overlapping(client) -> None:
    for n in range(3):
        _make(client, f"Task {n}", estimated_minutes=60)
    client.post("/v2/day/fit", json={"date": "2026-07-22"}, headers=APP_KEY)
    times = _times(client)
    starts = sorted(times[f"Task {n}"] for n in range(3))
    assert starts == ["07:00", "08:00", "09:00"]


def test_fit_respects_a_window(client) -> None:
    _make(client, "Afternoon only", estimated_minutes=60)
    client.post(
        "/v2/day/fit",
        json={"date": "2026-07-22", "window_start": "14:00", "window_end": "18:00"},
        headers=APP_KEY,
    )
    assert _times(client)["Afternoon only"] == "14:00"


def test_fit_leaves_a_gap_when_asked(client) -> None:
    _make(client, "One", estimated_minutes=60)
    _make(client, "Two", estimated_minutes=60)
    client.post("/v2/day/fit", json={"date": "2026-07-22", "gap": 15}, headers=APP_KEY)
    starts = sorted(_times(client).values())
    assert starts == ["07:00", "08:15"]


def test_fit_says_what_would_not_fit_and_leaves_it_alone(client) -> None:
    _make(client, "All day", start_time="07:00", estimated_minutes=15 * 60)
    _make(client, "Homeless", estimated_minutes=60)
    answer = client.post("/v2/day/fit", json={"date": "2026-07-22"}, headers=APP_KEY)
    data = answer.json()["data"]
    assert data["placed_count"] == 0
    assert [one["title"] for one in data["unplaced"]] == ["Homeless"]
    assert _times(client)["Homeless"] is None
    assert "would not fit" in data["spoken"]


def test_fit_dry_run_changes_nothing(client) -> None:
    _make(client, "Write", estimated_minutes=60)
    answer = client.post(
        "/v2/day/fit", json={"date": "2026-07-22", "dry_run": True}, headers=APP_KEY
    )
    data = answer.json()["data"]
    assert data["placed_count"] == 1 and data["dry_run"] is True
    assert data["saved"] == []
    assert _times(client)["Write"] is None


def test_fit_only_touches_the_tasks_it_is_given(client) -> None:
    wanted = _make(client, "Wanted", estimated_minutes=60)
    _make(client, "Left alone", estimated_minutes=60)
    client.post(
        "/v2/day/fit", json={"date": "2026-07-22", "task_ids": [wanted]}, headers=APP_KEY
    )
    times = _times(client)
    assert times["Wanted"] == "07:00"
    assert times["Left alone"] is None


def test_fit_explains_a_task_it_cannot_move(client) -> None:
    done = _make(client, "Finished", start_time="08:00")
    client.patch(f"/v2/day/tasks/{done}", json={"done": True}, headers=APP_KEY)
    answer = client.post(
        "/v2/day/fit",
        json={"date": "2026-07-22", "task_ids": [done, "no-such-task"]},
        headers=APP_KEY,
    )
    reasons = {one["id"]: one["reason"] for one in answer.json()["data"]["unplaced"]}
    assert reasons == {done: "already_done", "no-such-task": "not_on_this_day"}


def test_fit_starts_after_a_given_time(client) -> None:
    _make(client, "This afternoon", estimated_minutes=60)
    client.post("/v2/day/fit", json={"date": "2026-07-22", "after": "15:00"}, headers=APP_KEY)
    assert _times(client)["This afternoon"] == "15:00"


def test_fit_moves_a_slot_that_has_already_gone_by(client) -> None:
    _make(client, "Missed call", start_time="09:00", estimated_minutes=30)
    _make(client, "Under way", start_time="13:00", estimated_minutes=120)
    client.post("/v2/day/fit", json={"date": "2026-07-22", "after": "14:00"}, headers=APP_KEY)
    times = _times(client)
    # The 13:00 block is running at 14:00, so it stays; the 09:00 call slipped.
    assert times["Under way"] == "13:00"
    assert times["Missed call"] == "15:00"


def test_fit_refuses_a_backwards_window(client) -> None:
    answer = client.post(
        "/v2/day/fit",
        json={"date": "2026-07-22", "window_start": "18:00", "window_end": "09:00"},
        headers=APP_KEY,
    )
    assert answer.status_code == 400
    assert answer.json()["errors"] == ["FIT_INVALID"]


def test_fit_refuses_a_time_that_is_not_a_time(client) -> None:
    answer = client.post(
        "/v2/day/fit", json={"date": "2026-07-22", "after": "half past tea"}, headers=APP_KEY
    )
    assert answer.status_code == 400


def test_fit_reports_how_full_the_day_is(client) -> None:
    _make(client, "Booked", start_time="09:00", estimated_minutes=120)
    answer = client.post(
        "/v2/day/fit",
        json={"date": "2026-07-22", "window_start": "09:00", "window_end": "17:00", "dry_run": True},
        headers=APP_KEY,
    )
    data = answer.json()["data"]
    assert data["booked_minutes"] == 120
    assert data["free_minutes"] == 6 * 60


# --- Finding tasks by what they are called --------------------------------


def test_search_requires_app_key(client) -> None:
    assert client.get("/v2/tasks/search?q=transcript").status_code == 401


def test_search_finds_tasks_by_part_of_the_name(client) -> None:
    _make(client, "Order transcripts from college")
    _make(client, "Email Shashank sir about the LOR")
    _make(client, "Buy milk")
    found = client.get("/v2/tasks/search?q=transcript", headers=APP_KEY)
    assert found.status_code == 200, found.text
    data = found.json()["data"]
    assert [one["title"] for one in data["tasks"]] == ["Order transcripts from college"]
    assert data["total"] == 1


def test_search_ignores_case(client) -> None:
    _make(client, "Email Shashank sir about the LOR")
    for query in ("shashank", "SHASHANK", "Shashank Sir"):
        found = client.get(f"/v2/tasks/search?q={query}", headers=APP_KEY)
        assert len(found.json()["data"]["tasks"]) == 1, query


def test_search_finds_every_match_not_just_todays(client) -> None:
    _make(client, "Transcript request one", date="2026-07-22")
    _make(client, "Transcript request two", date="2026-09-30")
    _make(client, "Transcript request three")
    found = client.get("/v2/tasks/search?q=transcript", headers=APP_KEY)
    assert found.json()["data"]["total"] == 3


def test_search_leaves_out_finished_tasks_by_default(client) -> None:
    done = _make(client, "Transcript already sorted")
    _make(client, "Transcript still to do")
    client.patch(f"/v2/day/tasks/{done}", json={"done": True}, headers=APP_KEY)
    open_only = client.get("/v2/tasks/search?q=transcript", headers=APP_KEY)
    assert [one["title"] for one in open_only.json()["data"]["tasks"]] == ["Transcript still to do"]
    everything = client.get("/v2/tasks/search?q=transcript&open=false", headers=APP_KEY)
    assert everything.json()["data"]["total"] == 2


def test_search_puts_the_soonest_first(client) -> None:
    _make(client, "Transcript later", date="2026-09-30")
    _make(client, "Transcript sooner", date="2026-07-22")
    found = client.get("/v2/tasks/search?q=transcript", headers=APP_KEY)
    assert [one["title"] for one in found.json()["data"]["tasks"]] == [
        "Transcript sooner",
        "Transcript later",
    ]


def test_search_caps_what_comes_back_and_says_so(client) -> None:
    for n in range(5):
        _make(client, f"Transcript {n}")
    found = client.get("/v2/tasks/search?q=transcript&limit=2", headers=APP_KEY)
    data = found.json()["data"]
    assert len(data["tasks"]) == 2
    assert data["total"] == 5 and data["truncated"] is True


def test_search_refuses_one_letter(client) -> None:
    assert client.get("/v2/tasks/search?q=t", headers=APP_KEY).status_code == 422


def test_search_then_move_everything_it_found(client) -> None:
    """Both spoken halves of "move all the transcript tasks to today"."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    _make(client, "Transcript one", date="2026-07-20")
    _make(client, "Transcript two", date="2026-07-20")
    _make(client, "Something else", date="2026-07-20")

    found = client.get("/v2/tasks/search?q=transcript", headers=APP_KEY)
    ids = [one["id"] for one in found.json()["data"]["tasks"]]
    assert len(ids) == 2

    moved = client.post(
        "/v2/day/tasks/triage",
        json={"task_ids": ids, "action": "move", "to_date": today},
        headers=APP_KEY,
    )
    assert moved.status_code == 200, moved.text
    titles = set(_times(client, today).keys())
    assert {"Transcript one", "Transcript two"} <= titles
    # And only what matched moved.
    assert "Something else" not in titles


def test_open_tasks_requires_app_key(client) -> None:
    assert client.get("/v2/tasks/open").status_code == 401


def test_open_tasks_lists_every_unfinished_task_soonest_first(client) -> None:
    _make(client, "Later", date="2026-09-30")
    _make(client, "Sooner", date="2026-07-22")
    done = _make(client, "Finished", date="2026-07-21")
    client.patch(f"/v2/day/tasks/{done}", json={"done": True}, headers=APP_KEY)
    listed = client.get("/v2/tasks/open", headers=APP_KEY)
    assert listed.status_code == 200, listed.text
    data = listed.json()["data"]
    assert [one["title"] for one in data["tasks"]] == ["Sooner", "Later"]
    assert data["total"] == 2


def test_open_tasks_caps_and_says_so(client) -> None:
    for n in range(4):
        _make(client, f"Task {n}")
    data = client.get("/v2/tasks/open?limit=2", headers=APP_KEY).json()["data"]
    assert len(data["tasks"]) == 2 and data["total"] == 4 and data["truncated"] is True
    assert client.get("/v2/tasks/open?limit=0", headers=APP_KEY).status_code == 422


# --- What Fit must never do: place into the past, or move an appointment ---


def _freeze(monkeypatch, year, month, day, hour, minute=0):
    """Pin the planner's clock, so 'now' means the same thing on every run."""
    import planner_core.services as services
    from datetime import datetime as real

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return cls(year, month, day, hour, minute, tzinfo=tz)

    monkeypatch.setattr(services, "datetime", Frozen)


def _from_calendar(runtime, title):
    """Mark a task as an event pulled in from the calendar."""
    for row in runtime.service_client.tables["planner_tasks"]:
        if row["title"] == title:
            row["metadata"] = {"source": "apple_calendar", "apple_uid": f"uid-{title}"}


def test_fit_never_gives_today_a_time_that_has_gone_by(client, monkeypatch) -> None:
    _freeze(monkeypatch, 2026, 7, 22, 15, 7)
    _make(client, "Write the brief", estimated_minutes=60)
    data = client.post("/v2/day/fit", json={"date": "2026-07-22"}, headers=APP_KEY).json()["data"]
    # Asked at 15:07 with no "after" at all: not 07:00 this morning, and not
    # 15:07 either — the next five-minute mark.
    assert data["placements"][0]["start_time"] == "15:10"
    assert _times(client)["Write the brief"] == "15:10"


def test_fit_ignores_an_after_that_is_already_behind_the_clock(client, monkeypatch) -> None:
    _freeze(monkeypatch, 2026, 7, 22, 15, 0)
    _make(client, "Write the brief", estimated_minutes=60)
    client.post("/v2/day/fit", json={"date": "2026-07-22", "after": "09:00"}, headers=APP_KEY)
    assert _times(client)["Write the brief"] == "15:00"


def test_fit_still_honours_an_after_that_is_ahead_of_the_clock(client, monkeypatch) -> None:
    _freeze(monkeypatch, 2026, 7, 22, 10, 0)
    _make(client, "This evening", estimated_minutes=60)
    client.post("/v2/day/fit", json={"date": "2026-07-22", "after": "18:00"}, headers=APP_KEY)
    assert _times(client)["This evening"] == "18:00"


def test_fit_leaves_a_future_day_starting_at_the_top_of_its_window(client, monkeypatch) -> None:
    _freeze(monkeypatch, 2026, 7, 21, 15, 0)
    _make(client, "Tomorrow's task", estimated_minutes=60)
    client.post("/v2/day/fit", json={"date": "2026-07-22", "after": "now"}, headers=APP_KEY)
    assert _times(client)["Tomorrow's task"] == "07:00"


def test_fit_after_midnight_does_not_reach_back_into_the_evening(client, monkeypatch) -> None:
    # One in the morning: the app is still showing the 22nd, the day that runs
    # to four. Nothing may land at seven on a morning that is long gone.
    _freeze(monkeypatch, 2026, 7, 23, 1, 0)
    _make(client, "Loose end", estimated_minutes=60)
    data = client.post(
        "/v2/day/fit", json={"date": "2026-07-22", "after": "now"}, headers=APP_KEY
    ).json()["data"]
    assert data["placements"] == []
    assert [one["title"] for one in data["unplaced"]] == ["Loose end"]
    assert _times(client)["Loose end"] is None


def test_fit_never_moves_a_calendar_event(client, runtime, monkeypatch) -> None:
    _freeze(monkeypatch, 2026, 7, 22, 15, 0)
    _make(client, "Dance class", start_time="09:00", estimated_minutes=50)
    _make(client, "Festival")
    _make(client, "Real loose end", estimated_minutes=30)
    _from_calendar(runtime, "Dance class")
    _from_calendar(runtime, "Festival")
    data = client.post("/v2/day/fit", json={"date": "2026-07-22"}, headers=APP_KEY).json()["data"]
    assert [one["title"] for one in data["placements"]] == ["Real loose end"]
    times = _times(client)
    # The class went by unticked and the festival has no time: both are
    # appointments, and neither is anyone's to reschedule.
    assert times["Dance class"] == "09:00"
    assert times["Festival"] is None


def test_fit_says_why_a_named_calendar_event_will_not_move(client, runtime) -> None:
    event = _make(client, "Dance class", start_time="09:00")
    _from_calendar(runtime, "Dance class")
    data = client.post(
        "/v2/day/fit", json={"date": "2026-07-22", "task_ids": [event]}, headers=APP_KEY
    ).json()["data"]
    assert data["unplaced"][0]["reason"] == "fixed"


def test_day_says_which_items_came_from_the_calendar(client, runtime) -> None:
    _make(client, "Dance class", start_time="09:00")
    _make(client, "Own task", start_time="10:00")
    _from_calendar(runtime, "Dance class")
    items = client.get("/v2/day?date=2026-07-22", headers=APP_KEY).json()["data"]["items"]
    sources = {item["title"]: item["source"] for item in items}
    assert sources == {"Dance class": "apple_calendar", "Own task": None}
    # And the rest of the metadata stays on the server.
    assert all("metadata" not in item for item in items)


def test_a_calendar_event_that_has_passed_is_not_overdue(client, runtime, monkeypatch) -> None:
    _freeze(monkeypatch, 2026, 7, 25, 12, 0)
    _make(client, "Festival")
    _make(client, "Dance class", start_time="18:30")
    _make(client, "Real missed task", start_time="09:00")
    _from_calendar(runtime, "Festival")
    _from_calendar(runtime, "Dance class")
    inbox = client.get("/v2/day/inbox", headers=APP_KEY).json()["data"]["items"]
    # Three days on, only the piece of work is waiting. The events are over.
    assert [item["title"] for item in inbox] == ["Real missed task"]
