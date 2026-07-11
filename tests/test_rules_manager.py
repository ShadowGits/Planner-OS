from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import yaml

from planner_engine.models import MonthPlan
from planner_engine.rules import RulesEngine
from planner_engine.rules_manager import RulePathError, RulesManager
from planner_engine.scheduler import SchedulerEngine


class RulesManagerTests(TestCase):
    """Tests for persistent, data-only planner rule updates."""

    def temporary_rules(self, directory: str) -> Path:
        rules = yaml.safe_load(Path("config/rules.yaml").read_text(encoding="utf-8"))
        path = Path(directory) / "rules.yaml"
        path.write_text(yaml.safe_dump(rules, sort_keys=False), encoding="utf-8")
        return path

    def empty_month_plan(self) -> MonthPlan:
        return MonthPlan(
            month="Jul 2026",
            sheet_name="Jul 2026",
            monthly_goals=[],
            week_sections=[],
        )

    def test_weekends_are_no_work_and_weekdays_remain_active(self) -> None:
        with TemporaryDirectory() as directory:
            engine = RulesEngine(self.temporary_rules(directory))

            self.assertFalse(engine.is_work_day("Saturday"))
            self.assertFalse(engine.is_work_day("Sunday"))
            self.assertTrue(engine.is_work_day("Monday"))
            self.assertTrue(engine.is_work_day("Friday"))

    def test_updating_rules_persists_to_config(self) -> None:
        with TemporaryDirectory() as directory:
            rules_path = self.temporary_rules(directory)
            manager = RulesManager(rules_path)

            manager.update_rule("reading.preferred_time", "morning")
            persisted = yaml.safe_load(rules_path.read_text(encoding="utf-8"))

            self.assertEqual(persisted["reading"]["preferred_time"], "morning")
            self.assertEqual(manager.list_rules(), persisted)

    def test_scheduler_respects_updated_work_days(self) -> None:
        with TemporaryDirectory() as directory:
            rules_path = self.temporary_rules(directory)
            RulesManager(rules_path).set_work_days(["Tuesday"])
            scheduler = SchedulerEngine(RulesEngine(rules_path))

            monday = scheduler.plan_day(
                self.empty_month_plan(),
                date(2026, 7, 6),
                context_overrides={"skip_gym_today": True},
            )
            tuesday = scheduler.plan_day(
                self.empty_month_plan(),
                date(2026, 7, 7),
                context_overrides={"skip_gym_today": True},
            )

            self.assertFalse(any(block.category == "work" for block in monday.blocks))
            self.assertTrue(any(block.category == "work" for block in tuesday.blocks))

    def test_no_work_day_helpers_persist_consistent_day_sets(self) -> None:
        with TemporaryDirectory() as directory:
            rules_path = self.temporary_rules(directory)
            manager = RulesManager(rules_path)

            manager.add_no_work_day("Friday")
            self.assertFalse(RulesEngine(rules_path).is_work_day("Friday"))
            manager.remove_no_work_day("Friday")
            self.assertTrue(RulesEngine(rules_path).is_work_day("Friday"))

    def test_invalid_rule_path_has_clear_error(self) -> None:
        with TemporaryDirectory() as directory:
            manager = RulesManager(self.temporary_rules(directory))

            with self.assertRaisesRegex(
                RulePathError,
                "Unknown rule path: work.python_override",
            ):
                manager.update_rule("work.python_override", "edit source")
