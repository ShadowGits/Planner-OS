"""Cost budgets: useful fields only, no hidden full-planner scans."""
from test_day_api import APP_KEY, client, runtime
from test_day_api import USER_ID, WORKSPACE_ID
from uuid import uuid4
from fastapi.testclient import TestClient


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
