from datetime import date, timedelta
from unittest import TestCase

from planner_engine import MonthPlan, MonthlyGoal, PlannerTask, Priority, TaskStatus, WeekSection
from planner_engine.progress import ExecutionStatus, ProgressEngine


def task(
    name: str,
    category: str = "Learning",
    priority: Priority = Priority.MEDIUM,
    status: TaskStatus = TaskStatus.NOT_STARTED,
) -> PlannerTask:
    """Build a representative planner task."""

    return PlannerTask(
        name=name,
        category=category,
        priority=priority,
        status=status,
        notes=None,
        sheet_name="Jul 2026",
        row_number=23,
        week_name="WEEK 2",
        cell_references={"name": "B23"},
    )


def goal(
    name: str,
    category: str = "Learning",
    priority: Priority = Priority.HIGH,
    target_week: str = "W2",
    status: TaskStatus = TaskStatus.NOT_STARTED,
) -> MonthlyGoal:
    """Build a representative monthly goal."""

    return MonthlyGoal(
        name=name,
        category=category,
        priority=priority,
        target_week=target_week,
        status=status,
        notes=None,
        sheet_name="Jul 2026",
        row_number=10,
        cell_references={"name": "B10"},
    )


def month_plan() -> MonthPlan:
    """Build a small month plan for progress tests."""

    tasks = [
        task("German: Babbel A1 Units 3-4", "Learning"),
        task("Gym: Fri 5 PM HRX", "Fitness"),
    ]
    return MonthPlan(
        month="Jul 2026",
        sheet_name="Jul 2026",
        monthly_goals=[
            goal("Complete A1 German module", "Learning", target_week="W2"),
            goal("Gym 9 sessions/week", "Fitness", target_week="W2-W5"),
        ],
        week_sections=[
            WeekSection(
                name="WEEK 2",
                title="WEEK 2 · 06 Jul – 12 Jul 2026",
                sheet_name="Jul 2026",
                heading_row=35,
                header_row=36,
                start_row=37,
                end_row=48,
                tasks=tasks,
                cell_references={"heading": "B35"},
            )
        ],
    )


class ProgressEngineTests(TestCase):
    """Tests for Progress Engine v1."""

    def test_completion_tracking(self) -> None:
        engine = ProgressEngine()
        execution = engine.record_completion(
            "German: Babbel A1 Units 3-4",
            date(2026, 7, 6),
            category="Learning",
        )

        self.assertEqual(execution.status, ExecutionStatus.COMPLETED)
        self.assertEqual(execution.completion_ratio, 1.0)
        daily = engine.calculate_daily_progress(
            date(2026, 7, 6),
            planned_tasks=[task("German: Babbel A1 Units 3-4", "Learning")],
        )
        self.assertEqual(daily.completed_tasks, ["German: Babbel A1 Units 3-4"])
        self.assertEqual(daily.completion_percentage, 100.0)

    def test_skip_tracking(self) -> None:
        engine = ProgressEngine()
        engine.record_skip("Piano 60 minutes", date(2026, 7, 6), category="Skill")

        daily = engine.calculate_daily_progress(
            date(2026, 7, 6),
            planned_tasks=[task("Piano 60 minutes", "Skill")],
        )

        self.assertEqual(daily.skipped_tasks, ["Piano 60 minutes"])
        self.assertEqual(daily.completion_percentage, 0.0)

    def test_partial_completion_contributes_to_percentage(self) -> None:
        engine = ProgressEngine()
        engine.record_partial_completion(
            "IELTS: Diagnostic test + plan",
            date(2026, 7, 6),
            completion_ratio=0.5,
            category="Learning",
        )

        daily = engine.calculate_daily_progress(
            date(2026, 7, 6),
            planned_tasks=[task("IELTS: Diagnostic test + plan", "Learning")],
        )

        self.assertEqual(daily.partial_tasks, ["IELTS: Diagnostic test + plan"])
        self.assertEqual(daily.completion_percentage, 50.0)

    def test_streaks(self) -> None:
        engine = ProgressEngine()
        for offset in range(3):
            engine.record_completion(
                "German study",
                date(2026, 7, 6) + timedelta(days=offset),
                recurring_key="german",
            )
        engine.record_completion("German study", date(2026, 7, 11), recurring_key="german")

        streak = engine.calculate_streak("german", date(2026, 7, 8))

        self.assertEqual(streak.current_count, 3)
        self.assertEqual(streak.longest_count, 3)
        self.assertEqual(streak.last_completed_date, date(2026, 7, 11))

    def test_weekly_percentage_and_recurring_adherence(self) -> None:
        engine = ProgressEngine()
        planned = [
            task("German: Babbel A1 Units 3-4", "Learning"),
            task("IELTS: Diagnostic test + plan", "Learning"),
            task("Gym: Fri 5 PM HRX", "Fitness"),
            task("Piano 60 minutes", "Skill"),
        ]
        engine.record_completion("German: Babbel A1 Units 3-4", date(2026, 7, 6), category="Learning")
        engine.record_completion("IELTS: Diagnostic test + plan", date(2026, 7, 7), category="IELTS")
        engine.record_partial_completion("Gym: Fri 5 PM HRX", date(2026, 7, 10), 0.5, category="Fitness")
        for offset in range(5):
            engine.record_completion("German study", date(2026, 7, 6) + timedelta(days=offset), recurring_key="german")
        for offset in range(7):
            engine.record_completion("Piano practice", date(2026, 7, 6) + timedelta(days=offset), recurring_key="piano")

        weekly = engine.calculate_weekly_progress(date(2026, 7, 6), planned_tasks=planned)

        self.assertEqual(weekly.completion_percentage, 62.5)
        self.assertEqual(weekly.recurring_adherence["german"], 0.71)
        self.assertEqual(weekly.recurring_adherence["piano"], 1.0)

    def test_monthly_percentage(self) -> None:
        engine = ProgressEngine()
        plan = month_plan()
        engine.record_completion("Complete A1 German module", date(2026, 7, 8), category="Learning")
        engine.record_completion("German: Babbel A1 Units 3-4", date(2026, 7, 8), category="Learning")

        monthly = engine.calculate_monthly_progress(
            plan,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )

        self.assertEqual(monthly.completed_goals, 1)
        self.assertEqual(monthly.total_goals, 2)
        self.assertEqual(monthly.completed_tasks, 2)
        self.assertEqual(monthly.total_tasks, 4)
        self.assertEqual(monthly.completion_percentage, 50.0)

    def test_recurring_session_targets(self) -> None:
        engine = ProgressEngine()
        week_start = date(2026, 7, 6)
        engine.record_completion("Gym double", week_start, recurring_key="gym", sessions_completed=2)
        engine.record_completion("Gym single", week_start + timedelta(days=1), recurring_key="gym", sessions_completed=1)
        engine.record_completion("IELTS listening", week_start, recurring_key="ielts")
        engine.record_completion("IGNOU Unit 1", week_start, recurring_key="ignou")
        engine.record_completion("IGNOU Unit 2", week_start + timedelta(days=2), recurring_key="ignou")

        weekly = engine.calculate_weekly_progress(week_start)

        self.assertEqual(weekly.gym_sessions_completed, 3)
        self.assertEqual(weekly.gym_sessions_required, 9)
        self.assertEqual(weekly.ielts_sessions_completed, 1)
        self.assertEqual(weekly.ielts_sessions_target, 2)
        self.assertEqual(weekly.ignou_sessions_completed, 2)
        self.assertEqual(weekly.ignou_sessions_min, 2)
        self.assertEqual(weekly.ignou_sessions_max, 3)

    def test_category_progress(self) -> None:
        engine = ProgressEngine()
        planned = [
            task("Read Dark Forest chapters 1-10", "Reading"),
            task("Finish Dark Forest", "Reading"),
            task("IELTS: Listening practice", "Learning"),
        ]
        engine.record_completion("Read Dark Forest chapters 1-10", date(2026, 7, 6), category="Reading")
        engine.record_completion("IELTS: Listening practice", date(2026, 7, 6), category="Learning")

        daily = engine.calculate_daily_progress(date(2026, 7, 6), planned_tasks=planned)

        self.assertEqual(daily.per_category_completion["Reading"], 50.0)
        self.assertEqual(daily.per_category_completion["Learning"], 100.0)

    def test_overdue_detection_and_slippage_alerts(self) -> None:
        engine = ProgressEngine()
        plan = month_plan()
        overdue = [task("IELTS: Diagnostic test + plan", "Learning", Priority.HIGH)]

        alerts = engine.generate_alerts(
            current_date=date(2026, 7, 10),
            week_start=date(2026, 7, 6),
            month_plan=plan,
            current_week_number=3,
            overdue_tasks=overdue,
        )

        reasons = {alert.reason for alert in alerts}
        self.assertIn("German missed today", reasons)
        self.assertIn("Gym cannot mathematically reach weekly target", reasons)
        self.assertIn("Monthly goal behind schedule", reasons)
        self.assertIn("High-priority task overdue", reasons)

    def test_ielts_slippage_alert(self) -> None:
        engine = ProgressEngine()

        alerts = engine.detect_slippage(
            current_date=date(2026, 7, 12),
            week_start=date(2026, 7, 6),
        ).alerts

        self.assertTrue(
            any(alert.reason == "IELTS cannot reach weekly target" for alert in alerts)
        )

    def test_progress_summary_tracks_habits_forecast_and_risk(self) -> None:
        engine = ProgressEngine()
        through = date(2026, 7, 12)
        for offset in range(3):
            engine.record_completion(
                "German study",
                through - timedelta(days=offset),
                recurring_key="german",
            )
        engine.record_completion("Goal A", through, recurring_key="goal")

        summary = engine.summarize_progress(
            planned_minutes=300,
            carry_forward_count=2,
            overdue_tasks=[task("Overdue IELTS", "Learning", Priority.HIGH)],
            through_date=through,
            target_dates={
                "Goal A": date(2026, 7, 31),
                "Goal B": date(2026, 7, 13),
            },
        )

        self.assertGreater(summary.completed_minutes, 0)
        self.assertEqual(summary.overdue_count, 1)
        self.assertEqual(summary.carry_forward_count, 2)
        self.assertEqual(summary.streaks["german"], 3)
        self.assertEqual(summary.target_date_forecast["Goal A"], "complete")
        self.assertEqual(summary.target_date_forecast["Goal B"], "at_risk")
        self.assertEqual(summary.slippage_risk, "high")
