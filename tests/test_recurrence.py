from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine.decision_log import DecisionLog
from planner_engine.excel import ExcelPlannerStore
from planner_engine.planner import PlannerEngine
from planner_engine.recurrence import RecurrenceRequest, RecurrenceService
from planner_engine.writer import Writer
from test_planning_layer_continuation import dated_workbook


class RecurrenceTests(TestCase):
    def test_preview_and_apply_daily_recurrence_to_hidden_sheet_and_dated_tasks(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            workbook = tmp / "planner.xlsx"
            dated_workbook(workbook)
            engine = PlannerEngine(ExcelPlannerStore(workbook, tmp / "backups"))
            service = RecurrenceService(
                workbook,
                Writer(engine, decision_log=DecisionLog(tmp / "decisions.jsonl")),
                tmp / "previews",
            )

            preview = service.preview_recurrence(
                RecurrenceRequest(
                    title="German",
                    frequency="daily",
                    start_date=date(2026, 7, 10),
                    count=2,
                    estimated_minutes=30,
                    preferred_daypart="evening",
                    category="learning",
                )
            )
            self.assertEqual(len(preview.occurrences), 2)
            result = service.apply_recurrence(preview.preview_id)
            self.assertTrue(result.success, result.errors)
            self.assertEqual(len(service.list_recurrences()), 1)
            self.assertTrue(engine.list_dated_tasks("Jul 2026", date(2026, 7, 10)))
