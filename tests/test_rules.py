from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine.rules import RulesEngine, RulesValidationError


RULES_YAML = """\
profile:
  name: Shadow
  timezone: Asia/Kolkata
  location: Gurgaon, India

sleep:
  start: "03:00"
  end: "09:30"

work:
  july_august:
    start: "11:00"
    end: "19:00"
  september_onward:
    start: "20:30"
    end: "03:30"

gym:
  sessions_per_week: 9
  double_class_days_per_week: 3
  single_class_days_per_week: 3
  one_class_equals_one_session: true
  dance_forbidden_days:
    - Tuesday
    - Wednesday

german:
  frequency: daily
  allow_breaks: false

ielts:
  sessions_per_week: 2

ignou:
  sessions_per_week_min: 2
  sessions_per_week_max: 3

piano:
  duration_minutes: 60

reading:
  preferred_time: evening

planning:
  excel_is_source_of_truth: true
  edit_immediately: true
  backup_before_write: true
  move_unfinished_tasks_instead_of_deleting: true
  daily_follow_up: true
  alert_on_weekly_slippage: true
  alert_on_monthly_slippage: true
"""


class RulesEngineTests(TestCase):
    """Tests for Planner OS rules loading and queries."""

    def write_rules(self, directory: str, contents: str = RULES_YAML) -> Path:
        """Write a temporary rules config."""

        rules_path = Path(directory) / "rules.yaml"
        rules_path.write_text(contents, encoding="utf-8")
        return rules_path

    def test_dance_allowed_rules(self) -> None:
        with TemporaryDirectory() as directory:
            engine = RulesEngine(self.write_rules(directory))

            self.assertFalse(engine.is_dance_allowed("Tuesday"))
            self.assertFalse(engine.is_dance_allowed("Wednesday"))
            self.assertTrue(engine.is_dance_allowed("Friday"))

    def test_session_targets(self) -> None:
        with TemporaryDirectory() as directory:
            engine = RulesEngine(self.write_rules(directory))

            self.assertEqual(engine.required_gym_sessions(), 9)
            self.assertEqual(engine.required_german_sessions(days_in_period=7), 7)
            self.assertEqual(engine.required_ielts_sessions(), 2)
            self.assertEqual(engine.ignou_session_range(), (2, 3))
            self.assertEqual(engine.piano_duration_minutes(), 60)

    def test_missing_required_config_fields_raise_clear_validation_error(self) -> None:
        invalid_rules = RULES_YAML.replace("  duration_minutes: 60\n", "")

        with TemporaryDirectory() as directory:
            rules_path = self.write_rules(directory, invalid_rules)

            with self.assertRaisesRegex(
                RulesValidationError,
                "Missing required rules field: piano.duration_minutes",
            ):
                RulesEngine(rules_path)
