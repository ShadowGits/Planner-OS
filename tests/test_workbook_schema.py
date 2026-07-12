from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from openpyxl import Workbook, load_workbook

from planner_engine.workbook_schema import WorkbookSchemaInspector
from test_planning_layer_continuation import dated_workbook


class WorkbookSchemaTests(TestCase):
    def test_realistic_planner_capabilities(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "planner.xlsx"
            dated_workbook(path)
            capabilities, issues = WorkbookSchemaInspector(path).inspect()
            self.assertTrue(capabilities.supports_monthly_goals)
            self.assertTrue(capabilities.supports_weekly_tasks)
            self.assertTrue(capabilities.supports_dated_tasks)
            self.assertTrue(capabilities.supports_progress_tracking)
            self.assertEqual(issues, [])

    def test_missing_sections_have_precise_schema_issues(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.xlsx"
            workbook = Workbook()
            workbook.save(path)
            workbook.close()
            _, issues = WorkbookSchemaInspector(path).inspect()
            self.assertEqual({item.section for item in issues}, {"monthly_goals", "weekly_tasks"})
            self.assertTrue(all(item.expected and item.actual for item in issues))
