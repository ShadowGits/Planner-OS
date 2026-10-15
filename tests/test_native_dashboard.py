import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread
from time import monotonic
from uuid import uuid4

import pytest

from test_day_api import APP_KEY, client, runtime


def test_dashboard_is_key_guarded_and_sections_are_allowlisted(client):
    assert client.get("/v2/native/dashboard").status_code == 401
    assert client.get("/v2/native/dashboard?section=workspaces", headers=APP_KEY).status_code == 422
    assert client.get("/v2/native/dashboard?project_id=bad", headers=APP_KEY).status_code == 422


def test_rows_are_tenant_scoped_and_paged(client, runtime):
    calls = []
    select = runtime.service_client.select
    def tracked(table, **kwargs):
        calls.append((table, kwargs, current_thread().name))
        return select(table, **kwargs)
    runtime.service_client.select = tracked
    response = client.get("/v2/native/dashboard?section=books&offset=100", headers=APP_KEY)
    assert response.status_code == 200
    table, query, worker = next(c for c in calls if c[0] == "books")
    assert "user_id" in query["filters"] and "workspace_id" in query["filters"]
    assert "limit=100&offset=100" in query["query_string"]
    assert worker.startswith("planner-dashboard")
    assert not any(table == "planner_tasks" for table, _, _ in calls)


def test_task_list_excludes_split_children_and_heavy_metadata(client, runtime):
    calls = []
    select = runtime.service_client.select
    def tracked(table, **kwargs):
        calls.append((table, kwargs))
        return select(table, **kwargs)
    runtime.service_client.select = tracked
    response = client.get("/v2/native/dashboard?section=tasks", headers=APP_KEY)
    assert response.status_code == 200
    query = next(kwargs for table, kwargs in calls if table == "planner_tasks")
    assert "parent_task_id=is.null" in query["query_string"]
    assert "metadata" not in query["columns"]


def test_transaction_pagination_is_newest_first_with_stable_date_tie_break(client, runtime):
    calls = []
    select = runtime.service_client.select
    def tracked(table, **kwargs):
        calls.append((table, kwargs))
        return select(table, **kwargs)
    runtime.service_client.select = tracked
    response = client.get("/v2/native/dashboard?section=finance_transactions&offset=100", headers=APP_KEY)
    assert response.status_code == 200
    query = next(kwargs for table, kwargs in calls if table == "finance_logs")
    assert query["query_string"] == "order=date.desc,id.desc&limit=100&offset=100"


def test_failed_section_does_not_show_fake_empty_success(client, runtime):
    select = runtime.service_client.select
    def failing(table, **kwargs):
        if table == "books":
            raise ConnectionError("offline")
        return select(table, **kwargs)
    runtime.service_client.select = failing
    assert client.get("/v2/native/dashboard?section=books", headers=APP_KEY).status_code == 503
    assert client.get("/v2/day?date=2026-10-01", headers=APP_KEY).status_code == 200


def test_missing_tracker_is_explained_instead_of_showing_fake_zero(client, runtime):
    from adapters.supabase.client import SupabaseError
    select = runtime.service_client.select
    def missing(table, **kwargs):
        if table == "books":
            raise SupabaseError("Unavailable table", status_code=404)
        return select(table, **kwargs)
    runtime.service_client.select = missing
    response = client.get("/v2/native/dashboard?section=books", headers=APP_KEY)
    assert response.status_code == 409
    assert "not set up" in response.json()["message"]


def test_slow_dashboard_does_not_hold_day_request(client, runtime):
    started, release = Event(), Event()
    select = runtime.service_client.select
    def slow(table, **kwargs):
        if table == "books":
            started.set()
            assert release.wait(5)
        return select(table, **kwargs)
    runtime.service_client.select = slow
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(client.get, "/v2/native/dashboard?section=books", headers=APP_KEY)
        try:
            assert started.wait(2)
            then = monotonic()
            response = client.get("/v2/day?date=2026-10-01", headers=APP_KEY)
            assert response.status_code == 200
            assert monotonic() - then < 1
            assert not pending.done()
        finally:
            release.set()
        assert pending.result().status_code == 200


def test_record_details_cannot_read_another_project(client, runtime):
    row = runtime.service_client.insert("books", {"user_id":str(__import__('test_day_api').USER_ID),
                                                "workspace_id":str(__import__('test_day_api').WORKSPACE_ID), "book":"Book"})[0]
    response = client.get(f"/v2/native/dashboard?section=books&row_id={row['id']}&project_id={uuid4()}", headers=APP_KEY)
    assert response.status_code == 404


def test_week_and_month_navigation_use_requested_period(client):
    week = client.get("/v2/native/dashboard?section=week&on_date=2026-10-15", headers=APP_KEY)
    assert week.status_code == 200
    assert week.json()["data"]["week_start"] == "2026-10-12"
    money = client.get("/v2/native/dashboard?section=finance_summary&on_date=2026-09-01", headers=APP_KEY)
    assert money.status_code == 200
    assert money.json()["data"]["month"] == "2026-09"


def test_dashboard_progress_does_not_mutate_project_records(client, runtime):
    projects = runtime.service_client.select("projects", filters={})
    before = [dict(row) for row in projects]
    assert client.get("/v2/native/dashboard?section=projects", headers=APP_KEY).status_code == 200
    assert runtime.service_client.select("projects", filters={}) == before


@pytest.fixture()
def native_records(runtime):
    """Honor native paging/root filters that the general Day fake omits."""
    from urllib.parse import parse_qs
    from test_day_api import USER_ID, WORKSPACE_ID
    original = runtime.service_client.select
    calls = []
    def select(table, **kwargs):
        calls.append((table, kwargs))
        rows = original(table, **kwargs)
        query = parse_qs(kwargs.get("query_string") or "")
        if query.get("parent_task_id") == ["is.null"]:
            rows = [row for row in rows if not row.get("parent_task_id")]
        if query.get("order") == ["due_date.asc.nullslast,id.asc"]:
            rows = sorted(rows, key=lambda row: (str(row.get("due_date") or "9999"), row["id"]))
        offset = int(query.get("offset", [0])[0])
        limit = int(query.get("limit", [len(rows)])[0])
        rows = rows[offset:offset+limit]
        return [{**row, "work_budget": (row.get("metadata") or {}).get("_work_budget")} if "work_budget:" in kwargs.get("columns", "") else row for row in rows]
    runtime.service_client.select = select
    def insert(table, **fields):
        return runtime.service_client.insert(table, {"user_id":str(USER_ID), "workspace_id":str(WORKSPACE_ID), **fields})[0]
    return insert, calls


def test_native_milestone_health_matches_web_and_keeps_raw_status(client, native_records, monkeypatch):
    from datetime import date, datetime
    from planner_api import native_dashboard
    from planner_core.services import MetricsService
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 15, 12, tzinfo=tz)
    monkeypatch.setattr(native_dashboard, "datetime", Clock)
    insert, calls = native_records
    project = insert("projects", name="Germany")
    milestone = insert("milestones", project_id=project["id"], name="Applications", start_date="2026-09-01", target_date="2026-10-20", status="in_progress", notes="All applications")
    parent = insert("planner_tasks", title="Application", project_id=project["id"], milestone_id=milestone["id"], status="todo", scheduled_date="2026-10-01")
    insert("planner_tasks", title="Part one", project_id=project["id"], milestone_id=milestone["id"], parent_task_id=parent["id"], status="done")
    expected = MetricsService._milestone_health([milestone], [project], {milestone["id"]:{"done":0,"total":1,"first":date(2026,10,1),"last":date(2026,10,1)}}, date(2026,10,15))[0]
    listed = client.get("/v2/native/dashboard?section=milestones", headers=APP_KEY).json()["data"]["rows"][0]
    detail = client.get(f"/v2/native/dashboard?section=milestones&row_id={milestone['id']}", headers=APP_KEY).json()["data"]["record"]
    assert listed["health"] == detail["health"] == expected
    assert detail["health_status"] == "red"
    assert detail["start_date"] == "2026-09-01"  # Saved metadata is retained.
    assert detail["tracking_start_date"] == detail["health"]["start_date"] == "2026-10-01"
    assert detail["status"] == "in_progress"
    assert detail["total_tasks"] == 1 and detail["done_tasks"] == 0
    assert detail["project_name"] == "Germany" and detail["notes"] == "All applications"
    project_read = next(kwargs for table, kwargs in calls if table=="projects" and kwargs.get("columns")=="id,name")
    assert project_read["filters"]["id"] == [project["id"]]


def test_empty_and_explicitly_finished_milestones_have_truthful_health(client, native_records):
    insert, _ = native_records
    project = insert("projects", name="Life")
    empty = insert("milestones", project_id=project["id"], name="Empty", status="not_started")
    finished = insert("milestones", project_id=project["id"], name="Finished", status="done")
    rows = client.get("/v2/native/dashboard?section=milestones", headers=APP_KEY).json()["data"]["rows"]
    by_id = {row["id"]:row for row in rows}
    assert by_id[empty["id"]]["health"] is None
    assert by_id[empty["id"]]["health_status"] == "no_tasks"
    assert by_id[finished["id"]]["health"] is None
    assert by_id[finished["id"]]["health_status"] == "complete"


def test_milestone_task_page_is_scoped_paged_and_includes_split_work(client, native_records):
    insert, calls = native_records
    project = insert("projects", name="Germany")
    milestone = insert("milestones", project_id=project["id"], name="Maths")
    parent = insert("planner_tasks", title="Maths course", project_id=project["id"], milestone_id=milestone["id"], notes="Full notes", estimated_minutes=90)
    child = insert("planner_tasks", title="Maths part", project_id=project["id"], milestone_id=milestone["id"], parent_task_id=parent["id"], estimated_minutes=31, metadata={"_work_budget":{"seconds":1801,"minutes":31}})
    insert("task_work_sessions", task_ref=child["id"], seconds=301, planned_seconds=1801, created_at="2026-10-15T09:00:00Z")
    for i in range(100):
        insert("planner_tasks", title=f"Task {i}", project_id=project["id"], milestone_id=milestone["id"])
    insert("planner_tasks", title="Wrong milestone", project_id=project["id"], milestone_id=str(uuid4()))
    insert("planner_tasks", title="Other tenant", user_id=str(uuid4()), project_id=project["id"], milestone_id=milestone["id"])
    path=f"/v2/native/dashboard?section=tasks&milestone_id={milestone['id']}&include_parts=true&project_id={project['id']}"
    first = client.get(path, headers=APP_KEY).json()["data"]
    second = client.get(path+"&offset=100", headers=APP_KEY).json()["data"]
    assert len(first["rows"]) == 100 and first["next_offset"] == 100
    assert len(second["rows"]) == 2 and second["next_offset"] is None
    rows = first["rows"]+second["rows"]
    assert len({row["id"] for row in rows})==102
    assert all(row["milestone_id"]==milestone["id"] for row in rows)
    part = next(row for row in rows if row["id"]==child["id"])
    assert part["parent_task_id"] == parent["id"] and part["planned_seconds"]==1801
    assert part["parent_title"]=="Maths course" and part["part_index"]==1 and part["part_total"]==1
    assert part["worked_seconds"]==301 and part["remaining_seconds"]==1500
    assert part["done"] is False and part["is_habit"] is False
    assert next(row for row in rows if row["id"]==parent["id"])["notes"] == "Full notes"
    task_reads = [kwargs for table, kwargs in calls if table=="planner_tasks" and "limit=100" in (kwargs.get("query_string") or "")]
    assert all(q["filters"]["milestone_id"]==milestone["id"] and "user_id" in q["filters"] and "workspace_id" in q["filters"] for q in task_reads)
    assert all("parent_task_id=is.null" not in q["query_string"] for q in task_reads)
    assert all("metadata" not in q["columns"] for q in task_reads)
    root_page = client.get(path.replace("include_parts=true", "include_parts=false"), headers=APP_KEY).json()["data"]
    assert all(not row.get("parent_task_id") for row in root_page["rows"])


def test_milestone_filters_reject_foreign_mismatched_and_invalid_ids(client, native_records):
    insert, _ = native_records
    project = insert("projects", name="Germany")
    milestone = insert("milestones", project_id=project["id"], name="Owned")
    foreign = insert("milestones", user_id=str(uuid4()), project_id=project["id"], name="Foreign")
    assert client.get("/v2/native/dashboard?section=tasks&milestone_id=bad", headers=APP_KEY).status_code==422
    for suffix in [f"milestone_id={foreign['id']}",f"milestone_id={milestone['id']}&project_id={uuid4()}"]:
        assert client.get("/v2/native/dashboard?section=tasks&"+suffix, headers=APP_KEY).status_code==404
    assert client.get(f"/v2/native/dashboard?section=books&milestone_id={milestone['id']}", headers=APP_KEY).status_code==400


def test_native_milestone_patch_is_bounded_owned_and_app_key_guarded(client, native_records):
    insert, calls = native_records
    project=insert("projects", name="Germany")
    milestone=insert("milestones", project_id=project["id"], name="Start", status="not_started")
    path=f"/v2/native/milestones/{milestone['id']}"
    assert client.patch(path, json={"status":"done"}).status_code==401
    response=client.patch(path, json={"name":"  New name  ","status":"done","start_date":"2026-10-01","target_date":"2026-10-30","notes":"Full notes"}, headers=APP_KEY)
    assert response.status_code==200
    saved=response.json()["data"]["milestone"]
    assert saved["status"]=="done" and saved["name"]=="New name" and saved["notes"]=="Full notes"
    assert saved["start_date"]=="2026-10-01" and saved["target_date"]=="2026-10-30"
    reopened=client.patch(path, json={"status":"in_progress","target_date":None,"notes":None}, headers=APP_KEY)
    assert reopened.status_code==200 and reopened.json()["data"]["milestone"]["target_date"] is None
    for invalid,code in [({},400),({"status":None},400),({"name":"  "},400),({"status":"green"},422),({"target_date":"not-a-date"},422),({"project_id":str(uuid4())},422),({"notes":"x"*20001},422)]:
        assert client.patch(path,json=invalid,headers=APP_KEY).status_code==code
    foreign=insert("milestones",user_id=str(uuid4()),project_id=project["id"],name="Foreign")
    assert client.patch(f"/v2/native/milestones/{foreign['id']}",json={"status":"done"},headers=APP_KEY).status_code==404
    assert foreign["status"]=="not_started"
    assert client.patch("/v2/native/milestones/not-a-uuid",json={"status":"done"},headers=APP_KEY).status_code==422


def test_native_milestone_patch_reports_write_failure(client, native_records, runtime):
    insert, _=native_records
    project=insert("projects",name="Germany")
    milestone=insert("milestones",project_id=project["id"],name="Applications")
    def unavailable(*args,**kwargs):
        raise ConnectionError("Database unavailable")
    runtime.service_client.update=unavailable
    response=client.patch(f"/v2/native/milestones/{milestone['id']}",json={"status":"done"},headers=APP_KEY)
    assert response.status_code==503
    assert milestone["status"]=="not_started"


def test_day_create_inside_milestone_is_one_scoped_insert(client, native_records, runtime):
    insert, _=native_records
    project=insert("projects",name="Germany")
    milestone=insert("milestones",project_id=project["id"],name="German exam")
    before=len(runtime.service_client.tables.get("planner_tasks",[]))
    result=client.post("/v2/day/tasks",json={"title":"Prepare exam","milestone_id":milestone["id"]},headers=APP_KEY)
    assert result.status_code==201
    row=result.json()["data"]["task"]
    assert row["milestone_id"]==milestone["id"] and row["project_id"]==project["id"]
    assert len(runtime.service_client.tables["planner_tasks"])==before+1
    foreign=insert("milestones",user_id=str(uuid4()),project_id=project["id"],name="Foreign")
    for fields in [{"milestone_id":foreign["id"]},{"milestone_id":milestone["id"],"project_id":str(uuid4())}]:
        assert client.post("/v2/day/tasks",json={"title":"Invalid",**fields},headers=APP_KEY).status_code==400
    assert len(runtime.service_client.tables["planner_tasks"])==before+1
