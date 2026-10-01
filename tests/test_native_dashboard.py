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
