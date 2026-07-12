from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine import ExcelPlannerStore, PlannerEngine
from planner_engine.reviews import ReviewService
from test_planning_layer_continuation import dated_workbook


class ReviewTests(TestCase):
    def test_reviews_are_read_only_and_cover_all_periods(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            path = tmp / "planner.xlsx"
            dated_workbook(path)
            engine = PlannerEngine(ExcelPlannerStore(path, tmp / "backups"))
            before = path.read_bytes()
            service = ReviewService(engine)
            self.assertEqual(service.daily_review(date(2026, 7, 11)).period, "daily")
            weekly = service.weekly_review(date(2026, 7, 11))
            monthly = service.monthly_review("Jul 2026")
            self.assertEqual(weekly.period, "weekly")
            self.assertEqual(monthly.period, "monthly")
            self.assertIn("missed_commitments", weekly.to_dict())
            self.assertIn("completed_count", weekly.goal_progress)
            self.assertIn("german_planned", weekly.recurring_adherence)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse((tmp / "backups").exists())
