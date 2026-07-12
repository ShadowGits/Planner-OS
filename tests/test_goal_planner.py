from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from openpyxl import load_workbook

from planner_engine.decision_log import DecisionLog
from planner_engine.excel import ExcelPlannerStore
from planner_engine.goal_planner import GoalBreakdownService, GoalPlanningRequest
from planner_engine.planner import PlannerEngine
from planner_engine.writer import Writer
from test_planning_layer_continuation import dated_workbook


class GoalPlannerTests(TestCase):
    def test_goal_preview_persists_and_apply_writes_workbook_without_calendar(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            workbook = tmp / "planner.xlsx"
            dated_workbook(workbook)
            engine = PlannerEngine(ExcelPlannerStore(workbook, tmp / "backups"))
            service = GoalBreakdownService(
                workbook,
                Writer(engine, decision_log=DecisionLog(tmp / "decisions.jsonl")),
                tmp / "previews",
            )
            before = workbook.read_bytes()

            preview = service.preview_goal_plan(
                GoalPlanningRequest(
                    title="Finish German A1",
                    start_date=date(2026, 7, 10),
                    target_date=date(2026, 7, 11),
                    category="learning",
                    allowed_days=["Friday", "Saturday"],
                    preferred_dayparts=["evening"],
                )
            )
            self.assertEqual(workbook.read_bytes(), before)
            result = service.apply_goal_plan(preview.preview_id)
            self.assertTrue(result["success"], result["errors"])
            self.assertFalse(result["calendar_published"])
            self.assertTrue(engine.list_dated_tasks("Jul 2026", date(2026, 7, 10)))

    def test_stale_goal_preview_rejected_after_workbook_revision_changes(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            workbook = tmp / "planner.xlsx"
            dated_workbook(workbook)
            engine = PlannerEngine(ExcelPlannerStore(workbook, tmp / "backups"))
            service = GoalBreakdownService(
                workbook,
                Writer(engine, decision_log=DecisionLog(tmp / "decisions.jsonl")),
                tmp / "previews",
            )
            preview = service.preview_goal_plan(
                GoalPlanningRequest(
                    title="Finish German A1",
                    start_date=date(2026, 7, 10),
                    target_date=date(2026, 7, 11),
                    category="learning",
                )
            )
            book = load_workbook(workbook)
            try:
                book["Jul 2026"]["L10"] = "Workbook changed after preview"
                book.save(workbook)
            finally:
                book.close()

            with self.assertRaisesRegex(ValueError, "preview is stale"):
                service.apply_goal_plan(preview.preview_id)
