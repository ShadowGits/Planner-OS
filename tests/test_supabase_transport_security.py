from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from adapters.supabase.client import SupabaseConfig, SupabaseRestClient
from adapters.supabase.oauth_state import SupabaseOAuthStateStore
from planner_core.repository import PlannerCoreError, PlannerCoreRepository


def test_select_follows_all_pages_preserving_filters_and_columns(monkeypatch):
    client = SupabaseRestClient(SupabaseConfig("https://project.supabase.co", "secret"))
    calls = []
    def request(method, url, *args, **kwargs):
        query = parse_qs(urlsplit(url).query)
        calls.append(query)
        # Simulate an API configured with a lower max-rows cap than 1000.
        offset = int(query["offset"][0])
        return [{"id": str(n)} for n in range(offset, min(offset + 400, 1201))]
    monkeypatch.setattr(client, "_json_request", request)
    result = client.select("planner_tasks", filters={"user_id": "mine", "workspace_id": "active"},
                           columns="id,title", query_string="status=eq.todo&scheduled_date=gte.2026-01-01&scheduled_date=lte.2026-12-31")
    assert len(result) == 1201
    assert [query["offset"][0] for query in calls] == ["0", "400", "800", "1200", "1201"]
    for query in calls:
        assert query["user_id"] == ["eq.mine"]
        assert query["workspace_id"] == ["eq.active"]
        assert query["select"] == ["id,title"]
        assert query["scheduled_date"] == ["gte.2026-01-01", "lte.2026-12-31"]
        assert query["order"] == ["id.asc"]


def test_later_page_failure_does_not_return_partial_snapshot(monkeypatch):
    client = SupabaseRestClient(SupabaseConfig("https://project.supabase.co", "secret"))
    def request(method, url, *args, **kwargs):
        if parse_qs(urlsplit(url).query)["offset"] == ["0"]:
            return [{"id": "1"}]
        raise RuntimeError("later page failed")
    monkeypatch.setattr(client, "_json_request", request)
    with pytest.raises(RuntimeError, match="later page failed"):
        client.select("calendar_event_mappings", filters={"user_id": "mine"})


@pytest.mark.parametrize("kwargs", [{"limit": 1}, {"query_string": "limit=200&order=created_at.asc"}])
def test_explicit_limit_is_not_expanded(monkeypatch, kwargs):
    client = SupabaseRestClient(SupabaseConfig("https://project.supabase.co", "secret"))
    calls = []
    monkeypatch.setattr(client, "_json_request", lambda *args, **kw: calls.append(args) or [{"id": "1"}])
    assert client.select("projects", filters={}, **kwargs) == [{"id": "1"}]
    assert len(calls) == 1


def test_atomic_oauth_consume_uses_delete_returning_and_rejects_expiry(monkeypatch):
    client = SupabaseRestClient(SupabaseConfig("https://project.supabase.co", "secret"))
    calls = []
    rows = [{"payload": {"subject": "mine"}, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()}]
    def request(method, url, *args, **kw):
        calls.append((method, url, kw))
        returned = rows[:]
        rows.clear()
        return returned
    monkeypatch.setattr(client, "_json_request", request)
    store = SupabaseOAuthStateStore(client)
    assert store.consume("auth_code", "hashed-key") == {"subject": "mine"}
    assert store.consume("auth_code", "hashed-key") is None
    assert calls[0][0] == "DELETE"
    assert calls[0][2] == {"prefer": "return=representation"}
    query = parse_qs(urlsplit(calls[0][1]).query)
    assert query == {"kind": ["eq.auth_code"], "record_key": ["eq.hashed-key"]}


class Gateway:
    def __init__(self):
        self.calls = []
        self.rows = []
    def select(self, table, **kwargs):
        self.calls.append(("select", table, kwargs))
        return self.rows
    def update(self, table, payload, **kwargs):
        self.calls.append(("update", table, payload, kwargs))
        return [{"id": "owned"}]
    def insert(self, table, payload):
        self.calls.append(("insert", table, payload))
        return [{"id": "new"}]
    def delete(self, table, **kwargs):
        self.calls.append(("delete", table, kwargs))
    def rpc(self, function, payload):
        self.calls.append(("rpc", function, payload))
        return None


def test_repository_ignores_tenant_overrides_and_identity_updates():
    gateway = Gateway()
    user, workspace = uuid4(), uuid4()
    repository = PlannerCoreRepository(gateway, user, workspace)
    repository.list_rows("projects", {"user_id": "victim", "workspace_id": "other"})
    assert gateway.calls[-1][2]["filters"] == {"user_id": str(user), "workspace_id": str(workspace)}
    repository.delete_rows("projects", {"user_id": "victim"})
    assert gateway.calls[-1][2]["filters"]["user_id"] == str(user)
    repository.update_row("projects", "owned", {"id": "other", "user_id": "victim", "workspace_id": "other", "name": "Okay"})
    assert gateway.calls[-1][2] == {"name": "Okay"}
    repository.call_function("rollup", {"p_user_id": "victim", "p_workspace_id": "other"})
    assert gateway.calls[-1][2]["p_user_id"] == str(user)
    assert gateway.calls[-1][2]["p_workspace_id"] == str(workspace)


def test_foreign_reference_must_be_owned_before_insert_or_update():
    gateway = Gateway()
    repository = PlannerCoreRepository(gateway, uuid4(), uuid4())
    with pytest.raises(PlannerCoreError, match="not found in this workspace"):
        repository.insert_row("planner_tasks", {"title": "Attack", "project_id": "other-user-project"})
    with pytest.raises(PlannerCoreError):
        repository.update_row("planner_tasks", "mine", {"parent_task_id": "other-user-task"})
    assert all(call[0] == "select" for call in gateway.calls)
