"""Global inbox completeness, task semantics and bounded database payloads."""

from datetime import datetime, timedelta
import json
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from adapters.supabase.client import SupabaseConfig, SupabaseRestClient
from planner_api.v2 import build_core
from planner_core.repository import PlannerCoreRepository
from planner_core.services import TaskService
from test_day_api import APP_KEY, USER_ID, WORKSPACE_ID, _workspace_row, client, runtime
from test_planner_core import MemoryGateway


@pytest.fixture()
def core(runtime):
    runtime.service_client = MemoryGateway()
    runtime.service_client.tables["workspaces"] = [_workspace_row()]
    return build_core(runtime.service_client, USER_ID)


@pytest.fixture()
def inbox_now(monkeypatch):
    import planner_core.services as services
    moment = datetime(2026, 10, 1, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment if tz is None else moment.astimezone(tz)

    monkeypatch.setattr(services, "datetime", Clock)
    return moment


@pytest.mark.parametrize("headers", [{}, {"X-App-Key": "wrong"}])
def test_inbox_authenticates_before_any_database_read(client, core, runtime, monkeypatch, headers):
    monkeypatch.setattr(runtime.service_client, "select", lambda *args, **kwargs: pytest.fail("unauthorized read"))
    assert client.get("/v2/day/inbox", headers=headers).status_code == 401


def test_inbox_contains_old_and_missed_work_with_original_slots(client, core, inbox_now):
    create = core.tasks.create_task
    create("Past planned future deadline", scheduled_date="2026-09-20", due_date="2026-11-01", start_time="08:00", estimated_minutes=45)
    create("Past deadline future planned", scheduled_date="2026-10-20", due_date="2026-09-30", start_time="10:00")
    create("Expired today", scheduled_date="2026-10-01", start_time="11:00", estimated_minutes=60)
    create("Still working", scheduled_date="2026-10-01", start_time="11:45", estimated_minutes=30)
    create("Later today", scheduled_date="2026-10-01", start_time="15:00")
    create("Today's todo", scheduled_date="2026-10-01")
    create("Dateless")
    create("Future loose", due_date="2026-11-01")
    for title, status in [("Completed old", "done"), ("Skipped old", "skipped")]:
        task = create(title, scheduled_date="2026-09-01")["data"]["task"]
        core.tasks.update_task(task["id"], {"status": status})
    response = client.get("/v2/day/inbox", headers=APP_KEY)
    assert response.status_code == 200
    data = response.json()["data"]
    items = {row["title"]: row for row in data["items"]}
    assert set(items) == {"Past planned future deadline", "Past deadline future planned", "Expired today", "Today's todo", "Dateless"}
    assert data["date"] == "2026-10-01" and data["timezone"] == "Asia/Kolkata"
    assert data["total_count"] == 5 and data["overdue_count"] == 4
    missed = items["Past planned future deadline"]
    assert (missed["scheduled_date"], missed["start_time"], missed["overdue_reason"]) == ("2026-09-20", "08:00", "missed_slot")
    assert items["Past deadline future planned"]["overdue_reason"] == "deadline"
    assert items["Today's todo"]["overdue"] is False
    assert items["Dateless"]["overdue"] is True
    # Overdue tasks stay on their own timeline; inbox reads do not reschedule.
    assert {item["title"] for item in core.tasks.day_view("2026-09-20")["data"]["items"]} == {"Past planned future deadline"}


def test_inbox_scope_cannot_be_overridden(client, core, runtime, inbox_now):
    core.tasks.create_task("Mine", scheduled_date="2026-09-20")
    for user_id, workspace_id in [(str(uuid4()), str(WORKSPACE_ID)), (str(USER_ID), str(uuid4()))]:
        runtime.service_client.tables["planner_tasks"].append({
            "id": str(uuid4()), "title": "Foreign private title", "status": "todo",
            "user_id": user_id, "workspace_id": workspace_id, "scheduled_date": "2026-09-20",
        })
    response = client.get(f"/v2/day/inbox?user_id={uuid4()}&workspace_id={uuid4()}", headers=APP_KEY)
    assert [item["title"] for item in response.json()["data"]["items"]] == ["Mine"]


def test_inbox_excludes_split_umbrella_but_keeps_overdue_slots(client, core, inbox_now):
    umbrella = core.tasks.create_task("Whole project", scheduled_date="2026-09-20")["data"]["task"]
    core.tasks.create_task("Part 1", scheduled_date="2026-09-20", parent_task_id=umbrella["id"], start_time="09:00")
    core.tasks.create_task("Part 2", scheduled_date="2026-11-01", parent_task_id=umbrella["id"], start_time="09:00")
    data = client.get("/v2/day/inbox", headers=APP_KEY).json()["data"]
    assert [item["title"] for item in data["items"]] == ["Part 1"]
    assert data["items"][0]["parent_task_id"] == umbrella["id"]


def test_inbox_transfers_only_candidates_and_no_metadata(client, core, runtime, inbox_now, monkeypatch):
    core.tasks.create_task("Old task", scheduled_date="2026-09-20", notes="Keep my notes")
    core.tasks.create_task("Far future", scheduled_date="2026-11-20")
    for row in runtime.service_client.tables["planner_tasks"]:
        row["metadata"] = {"large_import": "x" * 100_000}
    original = runtime.service_client.select
    transferred = []
    def projected(table, **kwargs):
        rows = original(table, **kwargs)
        columns = kwargs.get("columns", "*")
        rows = rows if columns == "*" else [{key: row.get(key) for key in columns.split(",")} for row in rows]
        if table == "planner_tasks":
            transferred.extend(rows)
        return rows
    monkeypatch.setattr(runtime.service_client, "select", projected)
    item = client.get("/v2/day/inbox", headers=APP_KEY).json()["data"]["items"][0]
    assert item["notes"] == "Keep my notes"
    assert "metadata" not in item
    assert not any(row.get("title") == "Far future" for row in transferred)
    assert len(json.dumps(transferred)) < 2000


def test_inbox_fetches_every_transport_page_even_below_1000_cap(monkeypatch, inbox_now):
    gateway = SupabaseRestClient(SupabaseConfig("https://project.supabase.co", "test-only"))
    calls = []
    def request(method, url, *args, **kwargs):
        query = parse_qs(urlsplit(url).query)
        calls.append(query)
        assert query["user_id"] == [f"eq.{USER_ID}"]
        assert query["workspace_id"] == [f"eq.{WORKSPACE_ID}"]
        if query["select"] == ["parent_task_id"]:
            # Bounded umbrella lookup URLs even when every row is overdue.
            assert len(query["parent_task_id"][0].split(",")) <= 100
            return []
        offset = int(query["offset"][0])
        return [{
            "id": str(uuid4()), "title": f"Late {number}", "status": "todo",
            "scheduled_date": "2026-09-20", "start_time": "09:00",
        } for number in range(offset, min(offset + 400, 1201))]
    monkeypatch.setattr(gateway, "_json_request", request)
    service = TaskService(PlannerCoreRepository(gateway, USER_ID, WORKSPACE_ID), "Asia/Kolkata")
    data = service.inbox_view()["data"]
    assert data["total_count"] == 1201 and data["overdue_count"] == 1201
    offsets = [query["offset"][0] for query in calls if query["select"] != ["parent_task_id"]]
    assert offsets == ["0", "400", "800", "1200", "1201"]


def test_inbox_read_failure_does_not_claim_empty_backlog(core, monkeypatch):
    monkeypatch.setattr(core.tasks.repository.gateway, "select", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("read failed")))
    with pytest.raises(RuntimeError, match="read failed"):
        core.tasks.inbox_view()


def test_inbox_invalid_date_returns_client_error(client, core):
    assert client.get("/v2/day/inbox?date=not-a-date", headers=APP_KEY).status_code == 400
