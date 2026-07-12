from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import json

from planner_engine.decision_log import DecisionLog
from planner_engine.excel import ExcelPlannerStore
from planner_engine.external_links import ExternalLinkStore
from planner_engine.repair import PlannerRepairService
from planner_engine.undo import UndoService
from test_planning_layer_continuation import dated_workbook


class RepairUndoTests(TestCase):
    def test_repair_is_preview_first_for_unsupported_links(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            links = ExternalLinkStore(tmp / "links.json")
            links._save([{"planner_block_id": "b1", "target_name": "structured", "external_id": "old", "status": "active"}])
            service = PlannerRepairService(links, tmp / "previews")

            preview = service.preview_repair()
            self.assertEqual(links.list()[0]["status"], "active")
            result = service.apply_repair(preview.preview_id)
            self.assertTrue(result["success"])
            self.assertEqual(links.list()[0]["status"], "retired_unsupported")

    def test_repair_catalog_handles_bad_links_and_stale_previews(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            preview_dir = tmp / "previews"
            preview_dir.mkdir()
            (preview_dir / "old.json").write_text(
                json.dumps({"expires_at": "2000-01-01T00:00:00+00:00"}) + "\n",
                encoding="utf-8",
            )
            links = ExternalLinkStore(tmp / "links.json")
            links._save(
                [
                    {"planner_block_id": "b1", "target_name": "google_calendar", "external_id": "evt", "status": "active"},
                    {"planner_block_id": "b2", "target_name": "google_calendar", "external_id": "evt", "status": "active"},
                    {"planner_block_id": "b3", "target_name": "unknown_target", "external_id": "", "status": "weird"},
                ]
            )
            service = PlannerRepairService(links, preview_dir)

            preview = service.preview_repair()
            action_types = {action["type"] for action in preview.actions}
            self.assertIn("deactivate_duplicate_external_id", action_types)
            self.assertIn("mark_invalid_target", action_types)
            self.assertIn("normalize_invalid_status", action_types)
            self.assertIn("archive_stale_preview", action_types)

            result = service.apply_repair(preview.preview_id)
            self.assertTrue(result["success"])
            self.assertTrue((preview_dir / "archive" / "old.json").exists())

    def test_undo_requires_decision_log_backup(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            workbook = tmp / "planner.xlsx"
            dated_workbook(workbook)
            store = ExcelPlannerStore(workbook, tmp / "backups")
            backup = store.create_backup()
            record = DecisionLog(tmp / "decisions.jsonl").record(
                action="test_write",
                reason="test",
                confidence=1.0,
                backup_path=backup,
            )
            service = UndoService(store, DecisionLog(tmp / "decisions.jsonl"), tmp / "undo")

            preview = service.preview_undo(record.id)
            result = service.apply_undo(preview.preview_id)
            self.assertTrue(result["success"])
            self.assertTrue(Path(result["pre_undo_backup"]).exists())
