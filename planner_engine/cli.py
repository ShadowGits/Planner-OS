"""Command-line interface for Shadow's Planner OS."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

from planner_engine.config import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_GOOGLE_CALENDAR_ID,
    DEFAULT_GOOGLE_CREDENTIALS_PATH,
    DEFAULT_GOOGLE_TIMEZONE,
    DEFAULT_GOOGLE_TOKEN_PATH,
    DEFAULT_PLANNER_PATH,
    DEFAULT_RULES_PATH,
)
from planner_engine.excel import ExcelPlannerStore
from planner_engine.importer import PlannerImporter
from planner_engine.models import MonthPlan, MonthlyGoal, PlannerTask, TaskStatus
from planner_engine.planner import PlannerEngine
from planner_engine.progress import ProgressEngine
from planner_engine.rules import RulesEngine
from planner_engine.scheduler import SchedulerEngine
from planner_engine.writer import Writer
from planner_integrations.google_calendar import GoogleCalendarClient


class ShadowCLI:
    """Thin CLI orchestration over existing Planner OS engines."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

    def run(self) -> int:
        """Run the selected command and return a process exit code."""

        try:
            command_name = self.args.command.replace("-", "_")
            return int(getattr(self, f"_run_{command_name}")())
        except Exception as error:
            print(f"⚠️  {error}")
            return 1

    def _run_import(self) -> int:
        engine = self._planner_engine()
        result = PlannerImporter(engine).import_file(self.args.input)
        if not result.success:
            self._print_errors("Import needs attention", result.validation_errors)
            return 1

        print("✅ Import complete")
        print(f"Monthly goals imported: {result.goals_imported}")
        print(f"Weekly tasks imported: {result.tasks_imported}")
        print(f"Backup: {result.backup_path}")
        if result.skipped_items:
            print("Skipped:")
            for item in result.skipped_items:
                print(f"  • {item}")
        return 0

    def _run_plan(self) -> int:
        today = date.today()
        month_plan = self._month_plan(today)
        progress = self._progress_from_workbook(month_plan, today)
        daily_progress = progress.calculate_daily_progress(
            today,
            self._planned_items(month_plan),
        )
        rules = RulesEngine(self.args.rules)
        plan = SchedulerEngine(rules).plan_day(month_plan, today)

        print(f"🗓️  Shadow plan for {today.strftime('%A, %d %b %Y')}")
        print(f"Progress baseline: {daily_progress.completion_percentage:.2f}% complete")
        if not plan.blocks:
            print("No blocks scheduled.")
        for block in plan.blocks:
            print(
                f"{block.start.strftime('%H:%M')}–{block.end.strftime('%H:%M')}  "
                f"{block.title} · {block.category}"
            )
        if plan.conflicts:
            print("\n⚠️  Needs attention")
            for conflict in plan.conflicts:
                print(f"  • {conflict.item}: {conflict.reason}")
        return 0

    def _run_complete(self) -> int:
        writer = Writer(self._planner_engine(), ProgressEngine())
        result = writer.complete_task(
            self._month_name(date.today()),
            self.args.task_name,
            completion_date=date.today(),
        )
        if not result.success:
            self._print_errors("Could not complete task", result.errors)
            return 1

        print("✅ Task complete")
        print(f"Completed: {result.item_name}")
        print(f"Backup created: {result.backup_path}")
        print("Progress updated: yes")
        return 0

    def _run_status(self) -> int:
        today = date.today()
        month_plan = self._month_plan(today)
        progress = self._progress_from_workbook(month_plan, today)
        planned_items = self._planned_items(month_plan)
        week_start = today - timedelta(days=today.weekday())
        daily = progress.calculate_daily_progress(today, planned_items)
        weekly = progress.calculate_weekly_progress(week_start, planned_items)
        monthly = progress.calculate_monthly_progress(month_plan, today, today)
        german_streak = progress.calculate_streak("german", today)
        piano_streak = progress.calculate_streak("piano", today)
        alerts = progress.generate_alerts(
            current_date=today,
            week_start=week_start,
            month_plan=month_plan,
            current_week_number=self._week_of_month(today),
        )

        print(f"📍 Shadow status for {today.strftime('%d %b %Y')}")
        print(f"Today completion: {daily.completion_percentage:.2f}%")
        print(f"Weekly completion: {weekly.completion_percentage:.2f}%")
        print(f"Monthly completion: {monthly.completion_percentage:.2f}%")
        print(f"German streak: {german_streak.current_count} day(s)")
        print(f"Piano streak: {piano_streak.current_count} day(s)")
        print(f"Gym: {weekly.gym_sessions_completed} / {weekly.gym_sessions_required}")
        print(
            f"IELTS: {weekly.ielts_sessions_completed} / "
            f"{weekly.ielts_sessions_target}"
        )
        print(
            f"IGNOU: {weekly.ignou_sessions_completed} / "
            f"{weekly.ignou_sessions_min}-{weekly.ignou_sessions_max}"
        )
        print("Active slippage alerts:")
        if not alerts:
            print("  • None")
        for alert in alerts:
            print(f"  • {alert.item}: {alert.reason}")
        return 0

    def _run_validate(self) -> int:
        errors: list[str] = []
        engine = self._planner_engine()

        try:
            workbook = engine.load()
            workbook.close()
        except Exception as error:
            errors.append(f"Workbook is not readable: {error}")

        try:
            RulesEngine(self.args.rules)
        except Exception as error:
            errors.append(f"Rules failed to load: {error}")

        try:
            months = engine.list_months()
            if not months:
                errors.append("Planner has no monthly sheets.")
            for month in months:
                engine.get_month_plan(month)
        except Exception as error:
            errors.append(f"Planner structure is invalid: {error}")

        if errors:
            self._print_errors("Validation failed", errors)
            return 1

        print("✅ Everything OK")
        return 0

    def _run_calendar_auth(self) -> int:
        print("🔐 Starting Google Calendar authentication…", flush=True)
        client = self._calendar_client()
        client.authenticate()
        print("✅ Google Calendar authenticated")
        print(f"Token: {self.args.google_token}")
        return 0

    def _run_calendar_sync(self) -> int:
        today = date.today()
        print(f"📅 Preparing calendar sync for {self.args.period}…", flush=True)
        print("Loading rules…", flush=True)
        rules = RulesEngine(self.args.rules)
        scheduler = SchedulerEngine(rules)
        print("Reading planner and generating schedule…", flush=True)
        if self.args.period == "today":
            plan = scheduler.plan_day(self._month_plan(today), today)
        else:
            week_start = today - timedelta(days=today.weekday())
            plan = scheduler.plan_week(self._month_plan(today), week_start)

        block_count = len(plan.blocks) if hasattr(plan, "blocks") else sum(
            len(day.blocks) for day in plan.days
        )
        print(f"Syncing {block_count} scheduled blocks to Google Calendar…", flush=True)
        result = self._calendar_client().sync_plan(plan)
        print(f"📅 Calendar sync {self.args.period}")
        print(f"Created: {result.created}")
        print(f"Updated: {result.updated}")
        print(f"Deleted: {result.deleted}")
        print(f"Unchanged: {result.unchanged}")
        if result.warnings:
            print("Warnings:")
            for warning in result.warnings:
                print(f"  • {warning}")
        if result.errors:
            print("Errors:")
            for error in result.errors:
                print(f"  • {error}")
            return 1
        return 0

    def _planner_engine(self) -> PlannerEngine:
        """Create the workbook-backed planner engine."""

        return PlannerEngine(
            ExcelPlannerStore(
                planner_path=self.args.planner,
                backup_dir=self.args.backup_dir,
            )
        )

    def _calendar_client(self) -> GoogleCalendarClient:
        """Create the Google Calendar client."""

        return GoogleCalendarClient(
            credentials_path=self.args.google_credentials,
            token_path=self.args.google_token,
            calendar_id=self.args.google_calendar_id,
            timezone=self.args.google_timezone,
        )

    def _month_plan(self, target_date: date) -> MonthPlan:
        """Load the selected month plan."""

        return self._planner_engine().get_month_plan(self._month_name(target_date))

    def _month_name(self, target_date: date) -> str:
        """Resolve the CLI month option or infer it from a date."""

        return self.args.month or target_date.strftime("%b %Y")

    def _progress_from_workbook(
        self,
        month_plan: MonthPlan,
        target_date: date,
    ) -> ProgressEngine:
        """Seed ProgressEngine from workbook statuses for CLI reporting."""

        progress = ProgressEngine()
        for item in self._planned_items(month_plan):
            if item.status == TaskStatus.DONE:
                progress.record_completion(
                    task_name=item.name,
                    execution_date=target_date,
                    category=item.category,
                    priority=item.priority,
                    sessions_completed=self._session_count_for(item),
                    recurring_key=self._recurring_key_for(item),
                )
        return progress

    def _planned_items(self, month_plan: MonthPlan) -> list[PlannerTask | MonthlyGoal]:
        """Return monthly goals and weekly tasks as one list."""

        items: list[PlannerTask | MonthlyGoal] = list(month_plan.monthly_goals)
        for section in month_plan.week_sections:
            items.extend(section.tasks)
        return items

    def _recurring_key_for(self, item: PlannerTask | MonthlyGoal) -> str | None:
        """Infer recurring progress keys from planner text."""

        text = f"{item.name} {item.category or ''}".casefold()
        for key in ("german", "piano", "gym", "ielts", "ignou"):
            if key in text:
                return key
        return item.category

    def _session_count_for(self, item: PlannerTask | MonthlyGoal) -> int:
        """Infer session count for progress reporting."""

        text = f"{item.name} {item.category or ''}".casefold()
        return 1 if any(key in text for key in ("gym", "ielts", "ignou")) else 1

    def _week_of_month(self, target_date: date) -> int:
        """Return a simple one-based week number within a month."""

        return ((target_date.day - 1) // 7) + 1

    def _print_errors(self, heading: str, errors: Sequence[str]) -> None:
        """Print CLI validation errors."""

        print(f"⚠️  {heading}")
        for error in errors:
            print(f"  • {error}")


def build_parser() -> argparse.ArgumentParser:
    """Build the Shadow CLI parser."""

    parser = argparse.ArgumentParser(prog="shadow")
    parser.add_argument("--planner", type=Path, default=DEFAULT_PLANNER_PATH)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--month", default=None)
    parser.add_argument("--google-credentials", type=Path, default=DEFAULT_GOOGLE_CREDENTIALS_PATH)
    parser.add_argument("--google-token", type=Path, default=DEFAULT_GOOGLE_TOKEN_PATH)
    parser.add_argument("--google-calendar-id", default=DEFAULT_GOOGLE_CALENDAR_ID)
    parser.add_argument("--google-timezone", default=DEFAULT_GOOGLE_TIMEZONE)

    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("input", type=Path)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("period", choices=("today",))

    complete_parser = subparsers.add_parser("complete")
    complete_parser.add_argument("task_name")

    subparsers.add_parser("calendar-auth")

    calendar_sync_parser = subparsers.add_parser("calendar-sync")
    calendar_sync_parser.add_argument("period", choices=("today", "week"))

    subparsers.add_parser("status")
    subparsers.add_parser("validate")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Shadow CLI."""

    args = build_parser().parse_args(argv)
    return ShadowCLI(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
