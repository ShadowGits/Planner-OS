from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine.execution_manager import ExecutionSettings
from planner_engine.preferences import PreferenceService
from planner_engine.rules_manager import RulesManager


class PreferenceTests(TestCase):
    def test_preferences_wrap_rules_and_execution_settings(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            rules = tmp / "rules.yaml"
            rules.write_text((Path(__file__).parents[1] / "config/rules.yaml").read_text())
            service = PreferenceService(RulesManager(rules), ExecutionSettings(tmp / "execution.json"))

            self.assertTrue(service.list_preferences().success)
            updated = service.update_preference("active_execution_target", "none")
            self.assertTrue(updated.success)
            self.assertEqual(service.get_preference("active_execution_target").preferences["active_execution_target"], "none")
            no_work = service.update_preference("no_work_days", ["Saturday", "Sunday"])
            self.assertTrue(no_work.success, no_work.errors)
            constraints = service.explain_active_constraints()
            self.assertEqual(constraints.preferences["no_work_days"], ["Saturday", "Sunday"])
