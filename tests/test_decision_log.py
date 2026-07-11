from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine import ExcelPlannerStore, PlannerEngine, ProgressEngine, RulesEngine
from planner_engine.decision_log import DecisionLog, DecisionOutcome
from planner_engine.models import FixedCommitment
from planner_engine.scheduler import SchedulerEngine
from planner_engine.writer import Writer
from test_writer import create_writer_workbook


class DecisionLogTests(TestCase):
    """Tests for durable Planner OS decision logging."""

    def test_jsonl_persistence_and_unique_ids(self) -> None:
        with TemporaryDirectory() as directory:
            log = DecisionLog(Path(directory) / "decision_log.jsonl")

            first = log.record(
                action="add_task",
                reason="User requested task",
                confidence=1.0,
                affected_tasks=["Task A"],
                constraints_considered=["backup before mutation"],
                outcome=DecisionOutcome.SUCCESS,
            )
            second = log.record(
                action="complete_task",
                reason="User completed task",
                confidence=1.0,
                affected_tasks=["Task A"],
                constraints_considered=["progress tracking"],
                outcome=DecisionOutcome.SUCCESS,
            )

            self.assertNotEqual(first.id, second.id)
            records = log.list_recent(limit=10)
            self.assertEqual([record.id for record in records], [first.id, second.id])
            self.assertTrue(log.log_path.exists())
            lines = log.log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["action"], "add_task")

    def test_recent_action_task_and_id_queries(self) -> None:
        with TemporaryDirectory() as directory:
            log = DecisionLog(Path(directory) / "decision_log.jsonl")
            first = log.record(
                action="add_task",
                reason="Add A",
                confidence=0.9,
                affected_tasks=["Task A"],
                constraints_considered=[],
                outcome=DecisionOutcome.SUCCESS,
            )
            second = log.record(
                action="move_task",
                reason="Move B",
                confidence=0.8,
                affected_tasks=["Task B"],
                constraints_considered=[],
                outcome=DecisionOutcome.SUCCESS,
            )

            self.assertEqual(log.list_recent(limit=1)[0].id, second.id)
            self.assertEqual(log.find_by_id(first.id), first)
            self.assertEqual(log.list_by_action("move_task"), [second])
            self.assertEqual(log.list_by_task("Task A"), [first])

    def test_clear_test_log_and_malformed_log_lines_are_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            log = DecisionLog(Path(directory) / "decision_log.jsonl")
            valid = log.record(
                action="add_task",
                reason="Valid line",
                confidence=1.0,
                affected_tasks=["Task A"],
                constraints_considered=[],
                outcome=DecisionOutcome.SUCCESS,
            )
            with log.log_path.open("a", encoding="utf-8") as log_file:
                log_file.write("not-json\n")
                log_file.write(json.dumps({"missing": "required fields"}) + "\n")

            self.assertEqual(log.list_recent(limit=10), [valid])

            log.clear_test_log()

            self.assertEqual(log.list_recent(limit=10), [])
            self.assertFalse(log.log_path.exists())

    def test_writer_integration_records_mutations(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            planner_path = tmp_path / "planner.xlsx"
            log = DecisionLog(tmp_path / "decision_log.jsonl")
            create_writer_workbook(planner_path)
            writer = Writer(
                PlannerEngine(ExcelPlannerStore(planner_path, tmp_path / "backups")),
                ProgressEngine(),
                decision_log=log,
            )

            self.assertTrue(
                writer.add_weekly_task("Jul 2026", 2, "Logged Task").success
            )
            self.assertTrue(
                writer.update_task("Jul 2026", "Logged Task", notes="updated").success
            )
            self.assertTrue(writer.complete_task("Jul 2026", "Logged Task").success)
            self.assertTrue(writer.move_task("Jul 2026", "Logged Task", 1).success)
            self.assertTrue(writer.delete_task("Jul 2026", "Logged Task").success)

            actions = [record.action for record in log.list_recent(limit=10)]
            self.assertEqual(
                actions,
                [
                    "add_weekly_task",
                    "update_task",
                    "complete_task",
                    "move_task",
                    "delete_task",
                ],
            )
            self.assertEqual(len(log.list_by_task("Logged Task")), 5)

    def test_scheduler_integration_records_plan_and_conflicts(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            planner_path = tmp_path / "planner.xlsx"
            log = DecisionLog(tmp_path / "decision_log.jsonl")
            create_writer_workbook(planner_path)
            month_plan = PlannerEngine(
                ExcelPlannerStore(planner_path, tmp_path / "backups")
            ).get_month_plan("Jul 2026")
            scheduler = SchedulerEngine(
                RulesEngine(Path("config/rules.yaml")),
                decision_log=log,
            )

            plan = scheduler.plan_day(
                month_plan,
                datetime(2026, 7, 7).date(),
                fixed_commitments=[
                    FixedCommitment(
                        title="Appointment A",
                        start=datetime(2026, 7, 7, 10, 0),
                        end=datetime(2026, 7, 7, 11, 0),
                    ),
                    FixedCommitment(
                        title="Appointment B",
                        start=datetime(2026, 7, 7, 10, 30),
                        end=datetime(2026, 7, 7, 11, 30),
                    ),
                ],
            )

            records = log.list_by_action("plan_day")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].outcome, DecisionOutcome.WARNING)
            self.assertEqual(records[0].metadata["date"], plan.date.isoformat())
            self.assertTrue(records[0].metadata["conflicts"])
            self.assertTrue(records[0].metadata["unscheduled_reasons"])

    def test_logging_failure_is_non_fatal_for_writer(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            planner_path = tmp_path / "planner.xlsx"
            bad_parent = tmp_path / "not-a-directory"
            bad_parent.write_text("block mkdir", encoding="utf-8")
            create_writer_workbook(planner_path)
            writer = Writer(
                PlannerEngine(ExcelPlannerStore(planner_path, tmp_path / "backups")),
                ProgressEngine(),
                decision_log=DecisionLog(bad_parent / "decision_log.jsonl"),
            )

            result = writer.add_weekly_task("Jul 2026", 2, "Still Succeeds")

            self.assertTrue(result.success)
            self.assertTrue(result.warnings)
            self.assertIn("Decision log warning:", result.warnings[0])
