"""Tests for the Apple/iCloud .ics reader and the one-way import into tasks."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from planner_integrations.ics import parse_ics, occurrence_in_window

TZ = "Asia/Kolkata"  # UTC+5:30, no DST — easy to reason about

SAMPLE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-timed@icloud
SUMMARY:Dentist appointment
DTSTART;TZID=Asia/Kolkata:20260915T140000
DTEND;TZID=Asia/Kolkata:20260915T150000
END:VEVENT
BEGIN:VEVENT
UID:evt-allday@icloud
SUMMARY:Public holiday
DTSTART;VALUE=DATE:20260916
DTEND;VALUE=DATE:20260917
END:VEVENT
BEGIN:VEVENT
UID:evt-utc@icloud
SUMMARY:Call overseas
DTSTART:20260915T033000Z
DTEND:20260915T040000Z
END:VEVENT
BEGIN:VEVENT
UID:evt-weekly@icloud
SUMMARY:Team standup
DTSTART;TZID=Asia/Kolkata:20260915T093000
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
BEGIN:VEVENT
UID:evt-folded@icloud
SUMMARY:A very long title that the feed has wrapped across two
  physical lines per the iCalendar spec
DTSTART;TZID=Asia/Kolkata:20260917T110000
END:VEVENT
END:VCALENDAR
"""


def test_parser_reads_timed_allday_utc_and_recurring():
    events = {e.uid: e for e in parse_ics(SAMPLE)}
    assert set(events) == {
        "evt-timed@icloud", "evt-allday@icloud", "evt-utc@icloud",
        "evt-weekly@icloud", "evt-folded@icloud",
    }
    assert events["evt-allday@icloud"].all_day is True
    assert events["evt-timed@icloud"].all_day is False
    assert events["evt-weekly@icloud"].recurring is True
    # line folding: the continuation joins onto the summary
    assert "two physical lines" in events["evt-folded@icloud"].summary


def test_utc_event_converts_into_the_workspace_day_and_time():
    events = {e.uid: e for e in parse_ics(SAMPLE)}
    # 03:30 UTC is 09:00 in Asia/Kolkata (+5:30)
    placed = occurrence_in_window(events["evt-utc@icloud"], date(2026, 9, 1), date(2026, 10, 1), TZ)
    assert placed == (date(2026, 9, 15), "09:00", 30)


def test_allday_event_has_no_time():
    events = {e.uid: e for e in parse_ics(SAMPLE)}
    placed = occurrence_in_window(events["evt-allday@icloud"], date(2026, 9, 1), date(2026, 10, 1), TZ)
    assert placed == (date(2026, 9, 16), None, None)


def test_recurring_event_is_skipped():
    events = {e.uid: e for e in parse_ics(SAMPLE)}
    assert occurrence_in_window(events["evt-weekly@icloud"], date(2026, 9, 1), date(2026, 10, 1), TZ) is None


def test_event_outside_the_window_is_skipped():
    events = {e.uid: e for e in parse_ics(SAMPLE)}
    placed = occurrence_in_window(events["evt-timed@icloud"], date(2026, 1, 1), date(2026, 1, 31), TZ)
    assert placed is None


# ---- import into tasks, with dedup ----

def _service():
    from tests.test_planner_core import MemoryGateway, TABLE_DEFAULTS, USER_ID, WORKSPACE_ID
    from planner_core.repository import PlannerCoreRepository
    from planner_core.services import TaskService

    gw = MemoryGateway()
    repo = PlannerCoreRepository(gw, USER_ID, WORKSPACE_ID)
    return TaskService(repo, TZ), gw


def test_import_creates_tasks_and_never_duplicates_on_rerun():
    tasks, _ = _service()

    first = tasks.import_ics(SAMPLE, window_days=60, today=date(2026, 9, 1))["data"]
    # timed, all-day, utc, folded = 4 one-off events in window; weekly skipped
    assert first["created"] == 4
    assert first["skipped"] == 0

    # Running it again imports nothing new — the UIDs are already there.
    second = tasks.import_ics(SAMPLE, window_days=60, today=date(2026, 9, 1))["data"]
    assert second["created"] == 0
    assert second["skipped"] == 4


def test_imported_task_carries_the_event_uid_and_time():
    tasks, gw = _service()
    tasks.import_ics(SAMPLE, window_days=60, today=date(2026, 9, 1))

    rows = gw.tables["planner_tasks"]
    dentist = [r for r in rows if r["title"] == "Dentist appointment"][0]
    assert dentist["scheduled_date"] == "2026-09-15"
    assert dentist["start_time"] == "14:00"
    assert dentist["estimated_minutes"] == 60
    assert dentist["metadata"]["apple_uid"] == "evt-timed@icloud"
    assert dentist["metadata"]["source"] == "apple_calendar"


def test_a_deleted_event_is_not_recreated_by_the_next_sync():
    """Deleting an imported task has to stick.

    The dedup set was read off existing tasks, so deleting one also deleted the
    only record that its event had ever been imported — and the next sync
    created it again. The task came back however many times it was deleted.
    """
    tasks, gw = _service()
    tasks.import_ics(SAMPLE, window_days=60, today=date(2026, 9, 1))

    dentist = [r for r in gw.tables["planner_tasks"] if r["title"] == "Dentist appointment"][0]
    tasks.delete_task(dentist["id"])

    again = tasks.import_ics(SAMPLE, window_days=60, today=date(2026, 9, 1))["data"]

    assert again["created"] == 0
    titles = [r["title"] for r in gw.tables["planner_tasks"]]
    assert "Dentist appointment" not in titles


def test_deleting_a_batch_also_keeps_those_events_away():
    tasks, gw = _service()
    tasks.import_ics(SAMPLE, window_days=60, today=date(2026, 9, 1))

    ids = [r["id"] for r in gw.tables["planner_tasks"]]
    tasks.delete_tasks_batch(ids)

    again = tasks.import_ics(SAMPLE, window_days=60, today=date(2026, 9, 1))["data"]

    assert again["created"] == 0
    assert gw.tables["planner_tasks"] == []
