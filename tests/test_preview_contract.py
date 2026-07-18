from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine.planning_commands import PlanningCommandService
from planner_engine.preview_contract import (
    CONTRACT_KEY,
    PreviewAlreadyAppliedError,
    PreviewContract,
    PreviewExpiredError,
    PreviewKindMismatchError,
    StalePreviewError,
    compute_fingerprint,
)
from planner_engine.recurrence import RecurrenceRequest, RecurrenceService
from planner_engine.monthly_planner import MonthlyPlanPreview
from planner_engine.rules import RulesEngine
from test_execution_targets import manager
from test_planning_layer_continuation import TARGET, services
from test_writer import create_writer_workbook, writer_for

REPO_RULES = Path(__file__).resolve().parents[1] / "config" / "rules.yaml"


class PreviewContractUnitTests(TestCase):
    def _contract(self, tmp: Path, ttl_hours: float = 24) -> PreviewContract:
        (tmp / "source.txt").write_text("original", encoding="utf-8")
        return PreviewContract({"source": tmp / "source.txt"}, ttl_hours=ttl_hours)

    def test_sealed_preview_validates_while_sources_unchanged(self) -> None:
        with TemporaryDirectory() as directory:
            contract = self._contract(Path(directory))
            payload = contract.seal({"data": 1}, kind="demo", depends_on=("source",))

            contract.validate(payload, kind="demo")

    def test_kind_mismatch_applied_expiry_and_staleness_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            contract = self._contract(tmp)
            payload = contract.seal({"data": 1}, kind="demo", depends_on=("source",))

            with self.assertRaises(PreviewKindMismatchError):
                contract.validate(payload, kind="other")

            applied = json.loads(json.dumps(payload))
            applied[CONTRACT_KEY]["applied_at"] = datetime.now(timezone.utc).isoformat()
            with self.assertRaises(PreviewAlreadyAppliedError):
                contract.validate(applied, kind="demo")

            expired = json.loads(json.dumps(payload))
            expired[CONTRACT_KEY]["expires_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat()
            with self.assertRaises(PreviewExpiredError):
                contract.validate(expired, kind="demo")

            (tmp / "source.txt").write_text("changed", encoding="utf-8")
            with self.assertRaises(StalePreviewError):
                contract.validate(payload, kind="demo")

    def test_legacy_preview_without_contract_block_still_validates(self) -> None:
        with TemporaryDirectory() as directory:
            contract = self._contract(Path(directory))

            contract.validate({"data": 1}, kind="demo")

    def test_absent_source_files_fingerprint_and_detect_creation(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            contract = PreviewContract({"settings": tmp / "settings.json"})
            payload = contract.seal({}, kind="demo", depends_on=("settings",))
            self.assertEqual(
                payload[CONTRACT_KEY]["source_fingerprint"], {"settings": "absent"}
            )

            (tmp / "settings.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(StalePreviewError):
                contract.validate(payload, kind="demo")

    def test_fingerprint_is_content_based_not_mtime_based(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            (tmp / "a.txt").write_text("same", encoding="utf-8")
            first = compute_fingerprint({"a": tmp / "a.txt"})
            (tmp / "a.txt").write_text("same", encoding="utf-8")
            self.assertEqual(first, compute_fingerprint({"a": tmp / "a.txt"}))


def _month_preview() -> MonthlyPlanPreview:
    return MonthlyPlanPreview(
        month="Jul 2026", goals_processed=[], weekly_milestones=[], daily_tasks=[],
        feasibility_report={}, warnings=[], conflicts=[],
        proposed_excel_changes=[{
            "operation": "add_dated_task", "date": TARGET.isoformat(),
            "title": "Contract task", "estimated_minutes": 30,
            "notes": "Planner OS generated plan",
        }],
        proposed_calendar_range={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
        overwrite_existing_plan=False,
    )


class PlanningPreviewContractTests(TestCase):
    def test_apply_is_single_use(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            _, engine, writer, _, rules = services(tmp)
            service = PlanningCommandService(engine, rules, writer, tmp / "previews")
            preview = _month_preview()
            service._remember(preview)

            result = service.apply_month_plan(preview.preview_id)
            self.assertTrue(result.success, result.errors)

            with self.assertRaises(PreviewAlreadyAppliedError):
                service.apply_month_plan(preview.preview_id)

    def test_rules_change_after_preview_rejects_apply(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            planner_path, engine, writer, _, _ = services(tmp)
            rules_path = tmp / "rules.yaml"
            shutil.copy(REPO_RULES, rules_path)
            rules = RulesEngine(rules_path)
            service = PlanningCommandService(engine, rules, writer, tmp / "previews")
            preview = _month_preview()
            service._remember(preview)

            rules_path.write_text(
                rules_path.read_text(encoding="utf-8").replace(
                    "sessions_per_week: 9", "sessions_per_week: 5"
                ),
                encoding="utf-8",
            )

            with self.assertRaises(StalePreviewError):
                service.apply_month_plan(preview.preview_id)

    def test_expired_planning_preview_rejects_apply(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            _, engine, writer, _, rules = services(tmp)
            preview_dir = tmp / "previews"
            service = PlanningCommandService(engine, rules, writer, preview_dir)
            preview = _month_preview()
            service._remember(preview)
            service._previews.clear()
            service._preview_revisions.clear()

            path = preview_dir / f"{preview.preview_id}.json"
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored[CONTRACT_KEY]["expires_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat()
            path.write_text(json.dumps(stored), encoding="utf-8")

            with self.assertRaises(PreviewExpiredError):
                service.apply_month_plan(preview.preview_id)


class ExecutionPreviewContractTests(TestCase):
    def test_switch_preview_is_single_use(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            execution, _, _ = manager(tmp)
            preview = execution.preview_execution_target_switch("apple_calendar")

            applied = execution.apply_execution_target_switch(preview.preview_id)
            self.assertEqual(applied["active_target"], "apple_calendar")

            with self.assertRaises(PreviewAlreadyAppliedError):
                execution.apply_execution_target_switch(preview.preview_id)

    def test_switch_preview_is_stale_after_settings_change(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            execution, _, _ = manager(tmp)
            preview = execution.preview_execution_target_switch("apple_calendar")

            execution.set_active_execution_target("none")

            with self.assertRaises(StalePreviewError):
                execution.apply_execution_target_switch(preview.preview_id)


class RecurrencePreviewContractTests(TestCase):
    def test_stored_recurrence_preview_is_stale_after_workbook_change(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            planner_path = tmp / "planner.xlsx"
            create_writer_workbook(planner_path)
            writer, _ = writer_for(planner_path, tmp / "backups")
            recurrence = RecurrenceService(planner_path, writer, tmp / "previews")
            preview = recurrence.preview_recurrence(
                RecurrenceRequest(
                    title="German",
                    frequency="daily",
                    start_date=date(2026, 7, 13),
                    count=2,
                )
            )

            from openpyxl import load_workbook

            book = load_workbook(planner_path)
            try:
                book["Jul 2026"]["L10"] = "Changed after preview"
                book.save(planner_path)
            finally:
                book.close()

            with self.assertRaises(StalePreviewError):
                recurrence.apply_recurrence(preview.preview_id)
