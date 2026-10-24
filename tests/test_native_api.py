"""Native reminder authentication, tenant isolation and per-device delivery."""
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from planner_api.v2 import build_core
from test_day_api import APP_KEY, USER_ID, WORKSPACE_ID, _workspace_row, client, runtime
from test_planner_core import MemoryGateway


@pytest.fixture()
def native_core(runtime):
    runtime.service_client = MemoryGateway()
    runtime.service_client.tables["workspaces"] = [_workspace_row()]
    return build_core(runtime.service_client, USER_ID)


@pytest.fixture()
def native_clock(monkeypatch):
    import planner_api.native as native
    local_day = datetime.now(ZoneInfo("Asia/Kolkata")).date()

    def set_time(hour, minute=0):
        moment = datetime.combine(local_day, datetime.min.time(), ZoneInfo("Asia/Kolkata")).replace(hour=hour, minute=minute)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return moment if tz is None else moment.astimezone(tz)

        monkeypatch.setattr(native, "datetime", Clock)
        return moment

    set_time(9)
    return set_time


@pytest.mark.parametrize("headers", [{}, {"X-App-Key": "wrong"}])
def test_native_reminders_require_the_app_key(client, native_core, headers, runtime, monkeypatch):
    def forbidden_read(*args, **kwargs):
        pytest.fail("Unauthenticated native requests must not read the database")
    monkeypatch.setattr(runtime.service_client, "select", forbidden_read)
    response = client.post("/v2/native/reminders", headers=headers, json={"sent_kinds": []})
    assert response.status_code == 401
    assert "APP_KEY_INVALID" in response.json()["errors"]


def test_native_reminders_fail_closed_without_configured_key(client, native_core, monkeypatch):
    monkeypatch.delenv("PWA_ACCESS_KEY", raising=False)
    assert client.post("/v2/native/reminders", headers=APP_KEY, json={}).status_code == 401


def test_non_ascii_native_key_is_rejected_without_server_error(client, native_core):
    response = client.post("/v2/native/reminders", headers={"X-App-Key": b"\xc3\xa9"}, json={})
    assert response.status_code == 401


@pytest.mark.parametrize("body", [
    {"sent_kinds": ["morning_brief"] * 2001},
    {"sent_kinds": ["x" * 301]},
    {"sent_kinds": [42]},
    {"sent_kinds": None},
    {"sent_kinds": [], "user_id": str(uuid4()), "workspace_id": str(uuid4())},
])
def test_native_reminder_input_is_bounded_and_rejects_tenant_fields(client, native_core, body):
    assert client.post("/v2/native/reminders", headers=APP_KEY, json=body).status_code == 422


@pytest.mark.parametrize("sent", [["morning_brief"] * 2000, ["x" * 300]])
def test_native_reminder_input_accepts_documented_boundaries(client, native_core, native_clock, sent):
    native_clock(14)
    assert client.post("/v2/native/reminders", headers=APP_KEY, json={"sent_kinds": sent}).status_code == 200


def test_native_reminder_feed_is_scoped_to_configured_tenant(client, native_core, native_clock, runtime):
    today = native_clock(9).date().isoformat()
    native_core.tasks.create_task("My morning work", scheduled_date=today, start_time="09:10")
    other_user, other_workspace = str(uuid4()), str(uuid4())
    runtime.service_client.tables["planner_tasks"].append({
        "id": str(uuid4()), "user_id": other_user, "workspace_id": other_workspace,
        "title": "Private foreign task", "status": "todo", "scheduled_date": today,
        "start_time": "09:25", "due_date": today,
    })
    runtime.service_client.tables["planner_tasks"].append({
        "id": str(uuid4()), "user_id": str(USER_ID), "workspace_id": other_workspace,
        "title": "Private other workspace", "status": "todo", "scheduled_date": today,
        "start_time": "09:25", "due_date": today,
    })
    response = client.post(
        f"/v2/native/reminders?user_id={other_user}&workspace_id={other_workspace}",
        headers={**APP_KEY, "X-User-ID": other_user, "X-Workspace-ID": other_workspace}, json={},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["timezone"] == "Asia/Kolkata"
    assert body["data"]["date"] == today
    assert "My morning work" in response.text
    assert "Private foreign task" not in response.text
    assert "Private other workspace" not in response.text


def test_each_native_device_has_independent_morning_and_event_reminders(client, native_core, native_clock, runtime):
    today = native_clock(9).date().isoformat()
    task = native_core.tasks.create_task("Morning study", scheduled_date=today, start_time="09:10")["data"]["task"]
    event_kind = f"event10:{task['id']}"
    for kind in ["morning_brief", event_kind]:
        native_core.reminders.record_sent(kind, "push", {})
    log_before = list(runtime.service_client.tables["reminder_log"])
    assert native_core.reminders.due_reminders(native_clock(9)) == [], "Global web reminders must retain their existing dedup"

    def feed(sent):
        response = client.post("/v2/native/reminders", headers=APP_KEY, json={"sent_kinds": sent})
        assert response.status_code == 200
        return response.json()["data"]["reminders"]

    # Existing web-push delivery does not silence a new Android installation.
    first_device = feed([])
    assert {item["kind"] for item in first_device} == {"morning_brief", event_kind}
    assert next(item for item in first_device if item["kind"] == event_kind)["title"] == "Morning study"
    assert [item["kind"] for item in feed(["morning_brief"])] == [event_kind]
    assert feed(["morning_brief", event_kind]) == []
    assert {item["kind"] for item in feed([])} == {"morning_brief", event_kind}, "A second device must not inherit the first device's dedup"
    assert runtime.service_client.tables["reminder_log"] == log_before, "This feed must never mutate delivery logs"

    native_clock(9, 1)
    assert feed(["morning_brief", event_kind]) == [], "An exact local alarm and the feed share the same delivery kind"
    native_clock(9, 5)
    assert feed(["morning_brief"]) == [], "No five-minute or starting-now task alert remains"
    native_clock(9, 10)
    assert feed(["morning_brief"]) == []


def test_native_event_feed_includes_habits_and_skips_done_or_untimed_tasks(client, native_core, native_clock):
    today = native_clock(14, 50).date().isoformat()
    done = native_core.tasks.create_task("Already done", scheduled_date=today, start_time="15:00")["data"]["task"]
    native_core.tasks.complete_task(done["id"])
    native_core.tasks.create_task("Unscheduled", scheduled_date=today)
    native_core.habits.add_habit("Daily walk", start_time="15:00", start_date=today)
    response = client.post("/v2/native/reminders", headers=APP_KEY, json={})
    assert response.status_code == 200
    reminders = response.json()["data"]["reminders"]
    assert len(reminders) == 1
    assert reminders[0]["title"] == "Daily walk"
    assert reminders[0]["kind"].startswith("event10:habit:")


def test_reminder_telegram_fallback_keeps_task_name(client, native_core, monkeypatch):
    import planner_api.v2 as v2
    from planner_core.services import ReminderService
    sent = []

    class Telegram:
        def send_message(self, message):
            sent.append(message)

    monkeypatch.setenv("CRON_SECRET", "test-cron-secret")
    monkeypatch.setattr(v2.TelegramClient, "from_env", lambda: Telegram())
    monkeypatch.setattr("planner_core.push.send_push_to_all", lambda *args, **kwargs: {"sent": 0, "failed": 0})
    monkeypatch.setattr(ReminderService, "due_reminders", lambda self: [{
        "kind": "event10:example", "title": "Study probability exercises",
        "message": "Starts in 10 min · 14:17", "tag": "event-example",
    }])
    response = client.post("/v2/reminders/run", headers={"X-Cron-Key": "test-cron-secret"})
    assert response.status_code == 200
    assert sent == ["Study probability exercises\nStarts in 10 min · 14:17"]
    assert response.json()["data"]["sent"] == ["event10:example"]
