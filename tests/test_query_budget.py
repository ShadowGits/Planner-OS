"""Cost budgets: useful fields only, no hidden full-planner scans."""
from test_day_api import APP_KEY, client, runtime
from test_day_api import USER_ID, WORKSPACE_ID
from uuid import uuid4
from fastapi.testclient import TestClient
from pathlib import Path
import re


def test_apple_automatic_refresh_and_clock_network_contract():
    root = Path(__file__).resolve().parents[1] / "apple/PlannerOS"
    store = (root / "PlannerStore.swift").read_text()
    interval = re.search(r"func refreshIfStale\(after seconds: TimeInterval = (\d+)\)", store)
    assert interval and int(interval[1]) >= 120, "User approval required to increase automatic polling"
    clock = (root / "FloatingClock.swift").read_text()
    for network_entry in ("PlannerAPI", "refreshIfStale(", "refreshAll(", "loadDay(", "loadDays("):
        assert network_entry not in clock, "The floating clock must share the store's refresh loop"
    assert "refreshIfStale(after: 0)" not in (root / "RootView.swift").read_text()


def track(runtime, monkeypatch):
    calls = []
    original = runtime.service_client.select
    def select(table, **kwargs):
        calls.append((table, kwargs))
        return original(table, **kwargs)
    monkeypatch.setattr(runtime.service_client, "select", select)
    return calls


def test_project_names_do_not_read_tasks_or_work_sessions(client, runtime, monkeypatch):
    calls = track(runtime, monkeypatch)
    response = client.get("/v2/day/planning-context?projects_only=true", headers=APP_KEY)
    assert response.status_code == 200
    assert response.json()["data"]["items"] == []
    assert not ({"planner_tasks", "task_work_sessions"} & {table for table, _ in calls})
    assert next(kwargs["columns"] for table, kwargs in calls if table == "projects") == "id,name,status"


def test_reminder_week_is_bounded_and_omits_work_and_metrics(client, runtime, monkeypatch):
    calls = track(runtime, monkeypatch)
    response = client.get("/v2/day/reminder-schedule?date=2099-10-01", headers=APP_KEY)
    assert response.status_code == 200
    days = response.json()["data"]["days"]
    assert [day["date"] for day in days] == [f"2099-10-{day:02d}" for day in range(1, 8)]
    queries = [kwargs for table, kwargs in calls if table == "planner_tasks"]
    assert len(queries) == 1
    assert "scheduled_date.gte.2099-10-01,scheduled_date.lte.2099-10-07" in queries[0]["query_string"]
    assert "notes" not in queries[0]["columns"]
    assert not ({"task_work_sessions", "milestones", "project_widgets"} & {table for table, _ in calls})


def test_reminder_feed_rejects_unauthenticated_reads(client, runtime, monkeypatch):
    calls = track(runtime, monkeypatch)
    assert client.get("/v2/day/reminder-schedule?date=2099-10-01").status_code == 401
    assert calls == []


def test_milestone_labels_do_not_read_task_progress(client, runtime, monkeypatch):
    calls = track(runtime, monkeypatch)
    response = client.get("/v2/native/dashboard?section=milestones&details=false", headers=APP_KEY)
    assert response.status_code == 200
    assert not ({"planner_tasks", "task_work_sessions", "task_completions"} & {table for table, _ in calls})
    assert next(kwargs["columns"] for table, kwargs in calls if table == "milestones") == "id,name,target_date,status"


def test_reminder_projection_preserves_reports_midnight_and_scope(client, runtime):
    gateway = runtime.service_client
    def task(title, **values):
        return gateway.insert("planner_tasks", {"user_id": str(USER_ID), "workspace_id": str(WORKSPACE_ID),
            "title": title, "scheduled_date": "2099-10-01", "start_time": "12:00", **values})[0]
    task("Open")
    task("Completed", status="done")
    task("Untimed", start_time=None)
    task("Due only", scheduled_date=None, due_date="2099-10-01", start_time=None)
    task("Calendar", metadata={"source": "apple_calendar"})
    parent = task("Split umbrella")
    task("Split child", parent_task_id=parent["id"])
    task("Foreign user", user_id=str(uuid4()))
    task("Foreign workspace", workspace_id=str(uuid4()))
    task("Outside week", scheduled_date="2099-10-09")
    task("After midnight", scheduled_date="2099-10-08", start_time="01:30")
    task("Too late for spillover", scheduled_date="2099-10-08", start_time="09:00")
    days = client.get("/v2/day/reminder-schedule?date=2099-10-01", headers=APP_KEY).json()["data"]["days"]
    first = {item["title"]: item for item in days[0]["items"]}
    assert set(first) == {"Open", "Completed", "Untimed", "Due only", "Calendar", "Split child"}
    assert first["Completed"]["done"] is True
    assert first["Calendar"]["source"] == "apple_calendar"
    assert [(item["title"], item["start_time"], item["scheduled_date"]) for item in days[-1]["items"]] == [
        ("After midnight", "25:30:00", "2099-10-08")]


def test_reminder_read_failure_is_not_an_empty_success(client, runtime, monkeypatch):
    original = runtime.service_client.select
    def fail(table, **kwargs):
        if table == "planner_tasks":
            raise RuntimeError("database unavailable")
        return original(table, **kwargs)
    monkeypatch.setattr(runtime.service_client, "select", fail)
    response = TestClient(client.app, raise_server_exceptions=False).get(
        "/v2/day/reminder-schedule?date=2099-10-01", headers=APP_KEY)
    assert response.status_code >= 500


def test_reminder_habits_match_daily_reads_with_one_query_per_table(client, runtime, monkeypatch):
    gateway = runtime.service_client
    tenant = {"user_id": str(USER_ID), "workspace_id": str(WORKSPACE_ID)}
    habit = gateway.insert("habits", {**tenant, "title": "Practice", "recurrence_key": "practice",
        "start_date": "2099-10-01", "start_time": "08:00", "estimated_minutes": 20})[0]
    gateway.insert("habit_overrides", {**tenant, "habit_id": habit["id"], "on_date": "2099-10-02", "skipped": True})
    gateway.insert("habit_overrides", {**tenant, "habit_id": habit["id"], "on_date": "2099-10-03",
        "moved_to": "2099-10-05", "start_time": "10:00", "estimated_minutes": 45})
    gateway.insert("task_completions", {**tenant, "recurrence_key": "practice", "completed_on": "2099-10-04"})
    calls = track(runtime, monkeypatch)
    days = client.get("/v2/day/reminder-schedule?date=2099-10-01", headers=APP_KEY).json()["data"]["days"]
    for table in ("habits", "habit_overrides", "task_completions"):
        assert sum(name == table for name, _ in calls) == 1
    keys = ("id", "title", "start_time", "estimated_minutes", "scheduled_date", "done", "source")
    def projected(items):
        return sorted(tuple(item.get(key) for key in keys) for item in items)
    for day in days:
        ordinary = client.get(f"/v2/day?date={day['date']}", headers=APP_KEY).json()["data"]
        assert projected(day["items"]) == projected(ordinary["items"])
    assert days[1]["items"] == []
    assert days[2]["items"] == []
    assert days[3]["items"][0]["done"] is True
    assert len(days[4]["items"]) == 2
