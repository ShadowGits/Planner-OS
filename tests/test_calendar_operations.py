from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine.calendar_operations import GoogleCalendarOperations
from planner_engine.calendar_sync import CalendarSyncService
from planner_engine.external_links import ExternalLinkStore
from planner_engine.models import MonthPlan, ScheduledBlock
from planner_engine.rules import RulesEngine
from planner_integrations.google_calendar import GoogleCalendarClient
from test_google_calendar import FakeService, block


class GoogleCalendarOperationsTests(TestCase):
    def test_range_preview_apply_and_mapping_repair(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            client = GoogleCalendarClient(service=FakeService())
            event = {"id": "owned", **client.event_from_block(block("German"))}
            client.service.events_data = [event]
            operations = GoogleCalendarOperations(client, ExternalLinkStore(tmp / "links.json"), tmp / "previews")
            preview = operations.preview_delete_range(date(2026, 7, 11), date(2026, 7, 11))
            self.assertEqual(len(preview.events), 1)
            result = operations.apply_delete_range(preview.preview_id)
            self.assertTrue(result["success"])
            self.assertEqual(result["deleted"], 1)

            client.service.events_data = [event]
            repaired = operations.repair_mapping("owned")
            self.assertTrue(repaired["success"])
            self.assertEqual(repaired["mapping"]["target_name"], "google_calendar")

    def test_preview_rejects_calendar_drift(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            client = GoogleCalendarClient(service=FakeService())
            event = {"id": "owned", **client.event_from_block(block("German"))}
            client.service.events_data = [event]
            operations = GoogleCalendarOperations(client, ExternalLinkStore(tmp / "links.json"), tmp / "previews")
            preview = operations.preview_delete_range(date(2026, 7, 11), date(2026, 7, 11))
            client.service.events_data = []
            with self.assertRaisesRegex(ValueError, "changed since preview"):
                operations.apply_delete_range(preview.preview_id)

    def test_cleanup_preview_only_selects_owned_orphans(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            client = GoogleCalendarClient(service=FakeService())
            valid_block = ScheduledBlock(
                title="Call plumber",
                start=datetime(2026, 7, 13, 10, 0),
                end=datetime(2026, 7, 13, 10, 30),
                category="personal",
                source="workbook_dated_task",
                metadata={"planner_block_id": "dated-task-1"},
            )
            stale_block = ScheduledBlock(
                title="Call plumber",
                start=datetime(2026, 7, 12, 10, 0),
                end=datetime(2026, 7, 12, 10, 30),
                category="personal",
                source="workbook_dated_task",
                metadata={"planner_block_id": "dated-task-old"},
            )
            valid_event = {"id": "valid", **client.event_from_block(valid_block)}
            stale_event = {"id": "stale", **client.event_from_block(stale_block)}
            manual_event = {
                "id": "manual",
                "summary": "Call plumber",
                "start": {"dateTime": "2026-07-12T10:00:00+05:30"},
                "end": {"dateTime": "2026-07-12T10:30:00+05:30"},
            }
            client.service.events_data = [valid_event, stale_event, manual_event]
            operations = GoogleCalendarOperations(
                client,
                ExternalLinkStore(tmp / "links.json"),
                tmp / "previews",
            )

            preview = operations.preview_cleanup_orphans(
                [valid_block],
                date(2026, 7, 12),
                date(2026, 7, 13),
            )

            self.assertEqual([event["external_id"] for event in preview.events], ["stale"])

    def test_disabled_german_rule_produces_no_calendar_publication(self):
        class FakeEngine:
            def get_month_plan(self, month):
                return MonthPlan(month, month, [], [])

            def list_dated_tasks(self, month, target_date):
                del month, target_date
                return []

        client = GoogleCalendarClient(service=FakeService())
        service = CalendarSyncService(
            FakeEngine(),
            RulesEngine(Path("config/rules.yaml")),
            client,
        )

        result = service.calendar_sync_date(date(2026, 7, 13))

        self.assertTrue(result.success)
        published_titles = [
            call[1]["body"]["summary"]
            for call in client.service.calls
            if call[0] == "insert"
        ]
        self.assertNotIn("German study", published_titles)
