from datetime import datetime
from unittest.mock import patch

import pytest

from planner_integrations.google_calendar import GoogleCalendarClient, GoogleCalendarError
from test_google_calendar import FakeExecute, FakeEvents, FakeService, HttpErrorish, block, plan_with


def test_reads_all_pages_even_when_an_intermediate_page_is_empty():
    service = FakeService()
    client = GoogleCalendarClient(service=service)
    responses = [{"items": [{"id": "first"}], "nextPageToken": "two"},
                 {"items": [], "nextPageToken": "three"}, {"items": [{"id": "last"}]}]
    with patch.object(FakeEvents, "list", side_effect=[FakeExecute(r) for r in responses]) as listing:
        assert [e["id"] for e in client.list_events(datetime(2026, 7, 11), datetime(2026, 7, 12))] == ["first", "last"]
        assert listing.call_args_list[1].kwargs["pageToken"] == "two"
        assert listing.call_args_list[2].kwargs["pageToken"] == "three"


def test_failed_later_calendar_page_never_writes():
    client = GoogleCalendarClient(service=FakeService())
    with patch.object(FakeEvents, "list", side_effect=[FakeExecute({"nextPageToken": "two"}), FakeExecute(error=RuntimeError("unavailable"))]):
        result = client.sync_plan(plan_with(block()))
    assert not result.success
    assert not client.service.calls


def test_removes_existing_duplicate_copies_preserving_personal_event():
    client = GoogleCalendarClient(service=FakeService())
    b = block()
    body = client.event_from_block(b)
    client.service.events_data = [{**body, "id": "a"}, {**body, "id": "b"}, {"id": "personal", "summary": b.title}]
    first = client.sync_plan(plan_with(b))
    assert first.success and first.deleted == 1 and first.unchanged == 1
    assert {e["id"] for e in client.service.events_data} == {"a", "personal"}
    second = client.sync_plan(plan_with(b))
    assert second.success and second.created == second.updated == second.deleted == 0


def test_deterministic_insert_recovers_a_lost_success_response_without_new_copy():
    client = GoogleCalendarClient(service=FakeService())
    b = block()
    existing = client._insert_body(b)
    client.service.events_data = [existing]
    # The event was committed by another sync but its listing was stale.
    client.service.insert_errors = [HttpErrorish(409, b"already exists")]
    with patch.object(client, "list_events", return_value=[]):
        result = client.sync_plan(plan_with(b))
    assert result.success and result.created == 1
    assert client.service.events_data == [existing]
    assert client._insert_body(b)["id"] == GoogleCalendarClient(service=FakeService())._insert_body(b)["id"]


def test_conflicting_deterministic_id_never_adopts_personal_event():
    client = GoogleCalendarClient(service=FakeService())
    b = block()
    client.service.events_data = [{"id": client._insert_body(b)["id"], "summary": "Personal"}]
    client.service.insert_errors = [HttpErrorish(409, b"already exists")]
    with patch.object(client, "list_events", return_value=[]):
        result = client.sync_plan(plan_with(b))
    assert not result.success and result.created == result.updated == result.deleted == 0
    assert client.service.events_data[0]["summary"] == "Personal"


def test_previously_unscheduled_block_can_restore_its_owned_cancelled_event():
    client = GoogleCalendarClient(service=FakeService())
    b = block()
    client.service.events_data = [{**client._insert_body(b), "status": "cancelled"}]
    client.service.insert_errors = [HttpErrorish(409, b"already exists")]
    with patch.object(client, "list_events", return_value=[]):
        result = client.sync_plan(plan_with(b))
    assert result.success
    assert len(client.service.events_data) == 1
    assert client.service.events_data[0]["status"] == "confirmed"


def test_linked_lookup_permission_error_aborts_instead_of_recreating():
    client = GoogleCalendarClient(service=FakeService(), external_links_store=object())
    with patch.object(client, "get_event", side_effect=HttpErrorish(403, b"forbidden")):
        with pytest.raises(HttpErrorish):
            client._linked_event("block", {"block": {"target_name": "google_calendar", "external_id": "linked"}})


def test_linked_personal_event_cannot_be_overwritten():
    client = GoogleCalendarClient(service=FakeService(), external_links_store=object())
    with pytest.raises(GoogleCalendarError):
        client._linked_event("block", {"block": {"target_name": "google_calendar", "external_id": "linked"}}, {"linked": {"id": "linked", "summary": "Personal"}})


def test_failed_write_does_not_remove_other_existing_data():
    client = GoogleCalendarClient(service=FakeService())
    stale = {**client.event_from_block(block("Old")), "id": "old"}
    client.service.events_data = [stale]
    client.service.insert_errors = [RuntimeError("unavailable")]
    result = client.sync_plan(plan_with(block("New")))
    assert not result.success and result.deleted == 0
    assert client.service.events_data == [stale]


def test_delete_retries_plain_google_quota_errors_without_replaying_successes():
    client = GoogleCalendarClient(service=FakeService())
    client.service.delete_errors = [HttpErrorish(403, b"Quota exceeded for quota metric 'Queries'")]
    with patch("planner_integrations.google_calendar._sleep"):
        result = client.batch_delete_events(["retry", "success"])
    assert result["errors"] == {}
    assert set(result["deleted"]) == {"retry", "success"}
    ids = [args["eventId"] for name, args in client.service.calls if name == "delete"]
    assert ids == ["retry", "success", "retry"]


def test_large_delete_is_paced_after_the_short_burst():
    client = GoogleCalendarClient(service=FakeService())
    with patch("planner_integrations.google_calendar._sleep") as sleep:
        result = client.batch_delete_events([str(i) for i in range(151)])
    assert len(result["deleted"]) == 151
    assert sleep.call_count == 2
