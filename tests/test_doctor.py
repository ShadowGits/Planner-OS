from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine.doctor import PlannerDoctor
from test_planning_layer_continuation import dated_workbook


class DoctorTests(TestCase):
    def test_doctor_is_read_only_and_reports_core_health(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            workbook = tmp / "planner.xlsx"
            dated_workbook(workbook)
            rules = tmp / "rules.yaml"
            rules.write_text((Path(__file__).parents[1] / "config/rules.yaml").read_text())
            before = workbook.read_bytes()
            report = PlannerDoctor(workbook, rules, tmp / "settings.json", tmp / "links.json", tmp / "previews", tmp / "decisions.jsonl", tmp / "backups").run()
            self.assertTrue(report.success, report.errors)
            self.assertEqual(report.checks["workbook"], "readable")
            self.assertEqual(workbook.read_bytes(), before)
