from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine.execution_manager import ExecutionManager, ExecutionSettings
from planner_engine.execution_targets.apple_calendar import AppleCalendarExecutionTarget
from planner_engine.execution_targets.base import ExternalExecutionItem, PublishResult, ReconciliationReport
from planner_engine.execution_targets.null import NullExecutionTarget
from planner_engine.external_links import ExternalLinkStore
from planner_engine.models import ScheduledBlock
from planner_engine.target_operations import ExecutionTargetOperations


def block(block_id="block-1"):
    return ScheduledBlock("German", datetime(2026, 7, 13, 18), datetime(2026, 7, 13, 18, 30), "learning", "test", metadata={"planner_block_id": block_id})


class FakeTarget:
    def __init__(self, name, delete_fails=False):
        self.name, self.delete_fails = name, delete_fails
        self.published, self.deleted, self.items = [], [], []

    def publish_blocks(self, blocks, **kwargs):
        del kwargs
        self.published.extend(blocks)
        return PublishResult(True, self.name, created=len(blocks), mappings=[{"planner_block_id": item.metadata["planner_block_id"], "external_id": f"{self.name}-{item.metadata['planner_block_id']}", "checksum": "sum"} for item in blocks])

    def delete_item(self, external_id, **kwargs):
        del kwargs
        if self.delete_fails:
            return PublishResult(False, self.name, errors=["delete failed"])
        self.deleted.append(external_id)
        return PublishResult(True, self.name, deleted=1)

    def list_items(self, start, end):
        del start, end
        return self.items


def manager(tmp, google=None, apple=None):
    google, apple = google or FakeTarget("google_calendar"), apple or FakeTarget("apple_calendar")
    return ExecutionManager(ExecutionSettings(tmp / "settings.json"), ExternalLinkStore(tmp / "links.json"), {"google_calendar": google, "apple_calendar": apple, "none": NullExecutionTarget()}, tmp / "previews"), google, apple


class FakeAppleClient:
    def __init__(self, permission="full_access"):
        self.calendar_id = "cal-1"
        self.permission = permission
        self.events = {}
        self.counter = 0

    def permission_status(self):
        return {"data": {"permission": self.permission}}

    def list_calendars(self):
        return [{"id": "cal-1", "title": "Planner OS", "writable": True}]

    def create_event(self, payload):
        self.counter += 1
        event = {"external_id": f"apple-{self.counter}", **payload}
        self.events[event["external_id"]] = event
        return event

    def read_event(self, external_id):
        return self.events[external_id]

    def update_event(self, external_id, payload):
        self.events[external_id].update(payload)
        return self.events[external_id]

    def delete_event(self, external_id, scope="single"):
        del scope
        del self.events[external_id]

    def list_events(self, start, end):
        del start, end
        return list(self.events.values())


class ExecutionTargetTests(TestCase):
    def test_structured_setting_and_links_migrate_safely(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            settings_path, links_path = tmp / "settings.json", tmp / "links.json"
            settings_path.write_text(json.dumps({"execution": {"active_target": "structured", "publish_mode": "preview_first"}}))
            links_path.write_text(json.dumps([{"planner_block_id": "b", "target_name": "structured", "external_id": "s", "status": "active"}]))
            settings = ExecutionSettings(settings_path)
            self.assertEqual(settings.get_active(), "none")
            self.assertTrue(settings.migration_warnings)
            store = ExternalLinkStore(links_path)
            self.assertEqual(store.retire_target("structured"), 1)
            self.assertEqual(store.list()[0]["status"], "retired_unsupported")
            self.assertTrue(settings_path.with_suffix(".json.pre-mvp2-apple.bak").exists())

    def test_only_final_targets_are_accepted_and_persist(self):
        with TemporaryDirectory() as directory:
            service, google, apple = manager(Path(directory))
            preview = service.preview_execution_target_switch("apple_calendar")
            service.apply_execution_target_switch(preview.preview_id)
            self.assertEqual(service.get_active_execution_target(), "apple_calendar")
            self.assertEqual((google.published, apple.published), ([], []))
            with self.assertRaises(ValueError):
                service.set_active_execution_target("structured")

    def test_publish_uses_one_target_none_and_duplicate_rejection(self):
        with TemporaryDirectory() as directory:
            service, google, apple = manager(Path(directory))
            self.assertTrue(service.publish_blocks([block()]).success)
            service.set_active_execution_target("apple_calendar")
            rejected = service.publish_blocks([block()])
            self.assertFalse(rejected.success)
            self.assertEqual(apple.published, [])
            service.set_active_execution_target("none")
            self.assertTrue(service.publish_blocks([block("b2")]).success)

    def test_partial_migration_produces_repair(self):
        with TemporaryDirectory() as directory:
            google = FakeTarget("google_calendar", delete_fails=True)
            google.items = [ExternalExecutionItem("g1", "block-1", "German", "2026-07-13T18:00:00", "2026-07-13T18:30:00", "google_calendar")]
            service, _, _ = manager(Path(directory), google, FakeTarget("apple_calendar"))
            service.links.upsert("block-1", "google_calendar", "g1", "sum")
            preview = service.preview_move_external_items("google_calendar", "apple_calendar", date(2026, 7, 13), date(2026, 7, 13))
            result = service.apply_move_external_items(preview.preview_id, {"block-1": block()})
            self.assertTrue(result["repair_required"])

    def test_apple_calendar_crud_duplicate_reconcile_and_permission(self):
        client = FakeAppleClient()
        target = AppleCalendarExecutionTarget(client)
        created = target.publish_blocks([block()])
        self.assertTrue(created.success)
        external_id = created.mappings[0]["external_id"]
        self.assertEqual(client.read_event(external_id)["title"], "German")
        changed = ScheduledBlock("German B2", block().start, block().end, "learning", "test", metadata={"planner_block_id": "block-1"})
        self.assertTrue(target.update_block(changed, external_id).success)
        self.assertIn("German B2", client.read_event(external_id)["title"])
        report = target.reconcile([changed], date(2026, 7, 13), date(2026, 7, 13))
        self.assertEqual(report.missing_external, [])
        client.events["duplicate"] = {**client.events[external_id], "external_id": "duplicate"}
        self.assertIn("block-1", target.reconcile([changed], date(2026, 7, 13), date(2026, 7, 13)).duplicates)
        del client.events["duplicate"]
        self.assertTrue(target.delete_item(external_id).success)
        denied = AppleCalendarExecutionTarget(FakeAppleClient("denied")).health()
        self.assertFalse(denied["success"])
        self.assertIn("System Settings", denied["instructions"])

    def test_apple_range_delete_is_preview_first(self):
        with TemporaryDirectory() as directory:
            client = FakeAppleClient()
            target = AppleCalendarExecutionTarget(client)
            target.publish_blocks([block()])
            operations = ExecutionTargetOperations(target, Path(directory))
            preview = operations.preview_delete_range(date(2026, 7, 13), date(2026, 7, 13))
            self.assertEqual(len(client.events), 1)
            result = operations.apply_delete_range(preview["preview_id"])
            self.assertTrue(result["success"])
            self.assertEqual(client.events, {})
