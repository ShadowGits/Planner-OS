from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from planner_engine.decision_log import DecisionLog
from planner_engine import (
    BoundedSessionRequest,
    FixedCommitment,
    MonthPlan,
    MonthlyGoal,
    PlannerTask,
    Priority,
    SchedulerEngine,
    TaskStatus,
    WeekSection,
)
from planner_engine.rules import RulesEngine


def rules_engine() -> RulesEngine:
    """Load the project rules config."""

    return RulesEngine(Path("config/rules.yaml"))


def month_plan() -> MonthPlan:
    """Build a representative parsed month plan for scheduler tests."""

    weekly_task = PlannerTask(
        name="Build planner reader",
        category="Work",
        priority=Priority.MEDIUM,
        status=TaskStatus.NOT_STARTED,
        notes=None,
        sheet_name="Jul 2026",
        row_number=23,
        week_name="WEEK 1",
        cell_references={"name": "B23"},
    )
    high_goal = MonthlyGoal(
        name="Finish IELTS essay",
        category="IELTS",
        priority=Priority.HIGH,
        target_week="Week 1",
        status=TaskStatus.NOT_STARTED,
        notes=None,
        sheet_name="Jul 2026",
        row_number=10,
        cell_references={"name": "B10"},
    )
    return MonthPlan(
        month="Jul 2026",
        sheet_name="Jul 2026",
        monthly_goals=[high_goal],
        week_sections=[
            WeekSection(
                name="WEEK 1",
                title="WEEK 1 · 06 Jul – 12 Jul 2026",
                sheet_name="Jul 2026",
                heading_row=20,
                header_row=21,
                start_row=22,
                end_row=33,
                tasks=[weekly_task],
                cell_references={"heading": "B20"},
            )
        ],
    )


def blocks_by_category(plan, category: str):
    """Return blocks matching a category across a weekly plan."""

    return [
        block
        for day in plan.days
        for block in day.blocks
        if block.category == category
    ]


def all_blocks(plan):
    """Return all blocks across a weekly plan."""

    return [block for day in plan.days for block in day.blocks]


def assert_no_overlaps(test_case: TestCase, blocks) -> None:
    """Assert visible scheduled blocks do not overlap."""

    sorted_blocks = sorted(blocks, key=lambda block: (block.start, block.end))
    for previous, current in zip(sorted_blocks, sorted_blocks[1:]):
        test_case.assertLessEqual(
            previous.end,
            current.start,
            f"{previous.title} overlaps {current.title}",
        )


class SchedulerEngineTests(TestCase):
    """Tests for Scheduler Engine v1 guardrails."""

    def setUp(self) -> None:
        self._tmp_directory = TemporaryDirectory()
        self.decision_log = DecisionLog(
            Path(self._tmp_directory.name) / "decision_log.jsonl"
        )

    def tearDown(self) -> None:
        self._tmp_directory.cleanup()

    def scheduler(
        self,
        durations: dict[str, int] | None = None,
    ) -> SchedulerEngine:
        """Create a scheduler with an isolated decision log."""

        return SchedulerEngine(
            rules_engine(),
            durations=durations,
            decision_log=self.decision_log,
        )

    def test_weekly_recurring_rules_are_scheduled(self) -> None:
        scheduler = self.scheduler()

        plan = scheduler.plan_week(month_plan(), date(2026, 7, 6))

        self.assertEqual(len(blocks_by_category(plan, "german")), 7)
        piano_blocks = blocks_by_category(plan, "piano")
        self.assertEqual(len(piano_blocks), 7)
        self.assertTrue(
            all(
                block.end - block.start == timedelta(minutes=60)
                for block in piano_blocks
            )
        )
        self.assertGreaterEqual(len(blocks_by_category(plan, "ielts")), 2)
        ignou_count = len(blocks_by_category(plan, "ignou"))
        self.assertGreaterEqual(ignou_count, 2)
        self.assertLessEqual(ignou_count, 3)

    def test_gym_target_uses_three_double_and_three_single_days_without_forbidden_dance(
        self,
    ) -> None:
        scheduler = self.scheduler()

        plan = scheduler.plan_week(month_plan(), date(2026, 7, 6))

        gym_blocks_by_day = {
            day.date: [
                block for block in day.blocks if block.category.startswith("gym")
            ]
            for day in plan.days
        }
        gym_sessions = sum(len(blocks) for blocks in gym_blocks_by_day.values())
        double_days = [day for day, blocks in gym_blocks_by_day.items() if len(blocks) == 2]
        single_days = [day for day, blocks in gym_blocks_by_day.items() if len(blocks) == 1]
        dance_blocks = blocks_by_category(plan, "gym_dance")

        self.assertEqual(gym_sessions, 9)
        self.assertEqual(len(double_days), 3)
        self.assertEqual(len(single_days), 3)
        self.assertTrue(
            all(
                block.start.strftime("%A") not in {"Tuesday", "Wednesday"}
                for block in dance_blocks
            )
        )

    def test_work_sleep_and_no_overlaps_are_protected(self) -> None:
        scheduler = self.scheduler()

        plan = scheduler.plan_week(month_plan(), date(2026, 7, 6))

        for day in plan.days:
            sleep_blocks = [block for block in day.blocks if block.category == "sleep"]
            work_blocks = [block for block in day.blocks if block.category == "work"]
            self.assertEqual(len(sleep_blocks), 1)
            self.assertEqual(sleep_blocks[0].start.time().isoformat(timespec="minutes"), "03:00")
            self.assertEqual(sleep_blocks[0].end.time().isoformat(timespec="minutes"), "09:30")
            if day.date.strftime("%A") in {"Saturday", "Sunday"}:
                self.assertEqual(work_blocks, [])
            else:
                self.assertEqual(len(work_blocks), 1)
                self.assertEqual(work_blocks[0].start.time().isoformat(timespec="minutes"), "11:00")
                self.assertEqual(work_blocks[0].end.time().isoformat(timespec="minutes"), "19:00")
            assert_no_overlaps(self, day.blocks)

    def test_reading_prefers_evening(self) -> None:
        scheduler = self.scheduler()

        plan = scheduler.plan_week(month_plan(), date(2026, 7, 6))

        for block in blocks_by_category(plan, "reading"):
            self.assertGreaterEqual(block.start.time().hour, 18)

    def test_fixed_commitments_are_preserved_and_unfinished_tasks_rescheduled(
        self,
    ) -> None:
        scheduler = self.scheduler()
        appointment = FixedCommitment(
            title="Dentist",
            start=datetime(2026, 7, 6, 9, 45),
            end=datetime(2026, 7, 6, 10, 30),
            category="appointment",
        )
        unfinished = PlannerTask(
            name="Carry over admin",
            category="Personal",
            priority=Priority.HIGH,
            status=TaskStatus.IN_PROGRESS,
            notes=None,
            sheet_name="Jul 2026",
            row_number=24,
            week_name="WEEK 1",
            cell_references={"name": "B24"},
        )

        plan = scheduler.plan_day(
            month_plan=month_plan(),
            target_date=date(2026, 7, 6),
            fixed_commitments=[appointment],
            unfinished_tasks=[unfinished],
        )

        self.assertTrue(
            any(
                block.title == "Dentist"
                and block.start == appointment.start
                and block.end == appointment.end
                and block.is_fixed
                for block in plan.blocks
            )
        )
        self.assertTrue(any(block.title == "Carry over admin" for block in plan.blocks))

    def test_high_priority_unschedulable_task_creates_conflict(self) -> None:
        scheduler = self.scheduler(durations={"monthly_goal": 24 * 60})

        plan = scheduler.plan_day(month_plan(), date(2026, 7, 6))

        self.assertTrue(
            any(
                conflict.item == "Finish IELTS essay"
                and conflict.reason == "Task duration exceeding available window"
                for conflict in plan.conflicts
            )
        )

    def test_september_overnight_work_hours_are_handled(self) -> None:
        scheduler = self.scheduler()

        plan = scheduler.plan_day(month_plan(), date(2026, 9, 7))

        work = next(block for block in plan.blocks if block.category == "work")
        self.assertEqual(work.start, datetime(2026, 9, 7, 20, 30))
        self.assertEqual(work.end, datetime(2026, 9, 8, 3, 30))
        assert_no_overlaps(self, plan.blocks)

    def test_cross_midnight_commitments_are_preserved(self) -> None:
        scheduler = self.scheduler()
        commitment = FixedCommitment(
            title="Late social event",
            start=datetime(2026, 7, 10, 22, 0),
            end=datetime(2026, 7, 11, 1, 0),
            category="social",
        )

        plan = scheduler.plan_day(
            month_plan=month_plan(),
            target_date=date(2026, 7, 10),
            fixed_commitments=[commitment],
        )

        self.assertTrue(
            any(
                block.title == "Late social event"
                and block.start == commitment.start
                and block.end == commitment.end
                for block in plan.blocks
            )
        )
        assert_no_overlaps(self, plan.blocks)

    def test_two_bounded_gym_sessions_fit_inside_requested_window(self) -> None:
        scheduler = self.scheduler()
        request = BoundedSessionRequest(
            title="Gym",
            category="gym_strength",
            requested_window_start=datetime(2026, 7, 11, 17, 0),
            requested_window_end=datetime(2026, 7, 11, 20, 0),
            session_count=2,
            session_duration_minutes=60,
            gap_minutes=15,
        )

        plan = scheduler.plan_day(
            month_plan(),
            date(2026, 7, 11),
            bounded_sessions=[request],
        )
        gym_blocks = [block for block in plan.blocks if block.title == "Gym"]

        self.assertEqual(len(gym_blocks), 2)
        self.assertTrue(
            all(block.end - block.start == timedelta(minutes=60) for block in gym_blocks)
        )
        self.assertTrue(
            all(
                request.requested_window_start <= block.start < block.end
                <= request.requested_window_end
                for block in gym_blocks
            )
        )
        self.assertGreaterEqual(
            gym_blocks[1].start - gym_blocks[0].end,
            timedelta(minutes=15),
        )

    def test_bounded_gym_conflict_is_atomic_and_never_leaves_window(self) -> None:
        scheduler = self.scheduler()
        request = BoundedSessionRequest(
            title="Gym",
            category="gym_strength",
            requested_window_start=datetime(2026, 7, 11, 17, 0),
            requested_window_end=datetime(2026, 7, 11, 18, 45),
            session_count=2,
            session_duration_minutes=60,
            gap_minutes=15,
        )

        plan = scheduler.plan_day(
            month_plan(),
            date(2026, 7, 11),
            bounded_sessions=[request],
        )

        self.assertFalse(any(block.title == "Gym" for block in plan.blocks))
        self.assertTrue(
            any(
                conflict.item == "Gym"
                and "cannot fit inside the requested window" in conflict.reason
                for conflict in plan.conflicts
            )
        )

    def test_bounded_dance_request_still_respects_forbidden_days(self) -> None:
        scheduler = self.scheduler()
        request = BoundedSessionRequest(
            title="Dance class",
            category="gym_dance",
            requested_window_start=datetime(2026, 7, 7, 19, 0),
            requested_window_end=datetime(2026, 7, 7, 21, 0),
            session_count=1,
            allowed_session_types=("gym_dance",),
        )

        plan = scheduler.plan_day(
            month_plan(),
            date(2026, 7, 7),
            bounded_sessions=[request],
        )

        self.assertFalse(any(block.title == "Dance class" for block in plan.blocks))
        self.assertTrue(
            any(
                conflict.item == "Dance class"
                and conflict.reason == "Dance is not allowed on Tuesday"
                for conflict in plan.conflicts
            )
        )
