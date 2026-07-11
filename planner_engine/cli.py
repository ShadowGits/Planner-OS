"""Command-line interface for Shadow's Planner OS."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from planner_engine.config import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_GOOGLE_CALENDAR_ID,
    DEFAULT_GOOGLE_CREDENTIALS_PATH,
    DEFAULT_GOOGLE_TIMEZONE,
    DEFAULT_GOOGLE_TOKEN_PATH,
    DEFAULT_PLANNER_PATH,
    DEFAULT_RULES_PATH,
)
from planner_engine.calendar_sync import CalendarSyncService
from planner_engine.checkin import DailyCheckInService
from planner_engine.command_router import PlannerCommandRouter, parse_common_intent
from planner_engine.current_time import CurrentTimePlanner
from planner_engine.dated_task_scheduler import DatedTaskScheduler
from planner_engine.excel import ExcelPlannerStore
from planner_engine.importer import PlannerImporter
from planner_engine.models import DailyPlan, MonthPlan, MonthlyGoal, PlannerTask, TaskStatus
from planner_engine.planner import PlannerEngine
from planner_engine.monthly_planner import MonthlyPlanningRequest
from planner_engine.planning_commands import PlanningCommandService, WeekPlanningRequest
from planner_engine.progress import ProgressEngine
from planner_engine.rules import RulesEngine
from planner_engine.rules_manager import RulesManager
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
        if self.args.period == "month":
            service = self._planning_service()
            preview = service.preview_month_plan(
                MonthlyPlanningRequest(
                    month=self._selected_month(today),
                    planning_mode="remaining_month",
                    current_datetime=datetime.now(),
                )
            )
            return self._print_or_apply_preview(service, preview, "month")
        if self.args.period == "week":
            if self.args.week is None:
                raise ValueError("plan week requires --week")
            service = self._planning_service()
            preview = service.preview_week_plan(
                WeekPlanningRequest(
                    month=self._selected_month(today),
                    week_number=self.args.week,
                    current_datetime=datetime.now(),
                )
            )
            return self._print_or_apply_preview(service, preview, "week")
        month_plan = self._month_plan(today)
        progress = self._progress_from_workbook(month_plan, today)
        daily_progress = progress.calculate_daily_progress(
            today,
            self._planned_items(month_plan),
        )
        rules = RulesEngine(self.args.rules)
        plan = (
            CurrentTimePlanner(rules).plan_today_from_now(month_plan)
            if self.args.from_now
            else SchedulerEngine(rules).plan_day(month_plan, today)
        )
        plan = self._with_dated_tasks(plan, today, rules)

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

    def _run_replan(self) -> int:
        if self.args.period != "today" or not self.args.from_now:
            raise ValueError("Use: shadow replan today --from-now")
        today = date.today()
        plan = CurrentTimePlanner(RulesEngine(self.args.rules)).replan_today_from_now(
            self._month_plan(today)
        )
        plan = self._with_dated_tasks(plan, today, RulesEngine(self.args.rules))
        self._print_day_plan(plan, "Replanned from current time")
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
        dated = self._planner_engine().list_dated_tasks(self._month_name(today), today)
        print(f"Dated tasks today: {len(dated)}")
        for task in dated:
            print(f"  • {task.title} ({task.status.value})")
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

    def _run_rules(self) -> int:
        """List or update permanent rules in the configured YAML file."""

        manager = RulesManager(self.args.rules)
        if self.args.rules_action == "list":
            import yaml

            print(yaml.safe_dump(manager.list_rules(), sort_keys=False).rstrip())
            return 0
        if self.args.rules_action == "set-work-days":
            manager.set_work_days(self.args.days)
            print("✅ Work days updated")
            return 0
        raise ValueError(f"Unknown rules action: {self.args.rules_action}")

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
        service = self._calendar_sync_service()
        if self.args.period == "today":
            plan = SchedulerEngine(RulesEngine(self.args.rules)).plan_day(
                self._month_plan(today), today
            )
            legacy = self._calendar_client().sync_plan(plan)
            print(f"Synced date: {today.isoformat()} to {today.isoformat()}")
            print(f"Created: {legacy.created}")
            print(f"Updated: {legacy.updated}")
            print(f"Deleted: {legacy.deleted}")
            print(f"Unchanged: {legacy.unchanged}")
            return 0 if not legacy.errors else 1
        if self.args.period == "date":
            target = date.fromisoformat(self.args.date) if self.args.date else today
            result = service.calendar_sync_date(target)
        elif self.args.period in {"week", "current-week"}:
            if self.args.period == "week" and self.args.week is not None:
                result = service.calendar_sync_week_number(
                    self.args.sync_month or self._selected_month(today), self.args.week
                )
            elif self.args.period == "week":
                raise ValueError("Ambiguous week sync: use current-week, next-week, or --week")
            else:
                result = service.calendar_sync_current_week(today)
        elif self.args.period == "next-week":
            result = service.calendar_sync_next_week(today)
        elif self.args.period == "range":
            if not self.args.start or not self.args.end:
                raise ValueError("calendar-sync range requires --start and --end")
            result = service.calendar_sync_range(
                date.fromisoformat(self.args.start), date.fromisoformat(self.args.end)
            )
        elif self.args.period == "month":
            result = service.calendar_sync_month(
                self.args.sync_month or self._selected_month(today)
            )
        else:
            raise ValueError(f"Unknown calendar sync period: {self.args.period}")
        print(result.message)
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

    def _run_checkin(self) -> int:
        target = date.fromisoformat(self.args.date) if self.args.date else date.today()
        report = DailyCheckInService(self._planner_engine()).generate_daily_checkin(target)
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    def _run_add_dated_task(self) -> int:
        result = Writer(self._planner_engine()).add_dated_task(
            date.fromisoformat(self.args.date),
            self.args.title,
            self.args.minutes,
            preferred_daypart=self.args.daypart,
            start_time=self.args.start_time,
            end_time=self.args.end_time,
            hard_time=self.args.hard_time,
            category=self.args.category,
            notes=self.args.notes,
        )
        if not result.success:
            self._print_errors("Could not add dated task", result.errors)
            return 1
        print("✅ Dated task added")
        print(f"Date: {self.args.date}")
        print(f"Backup created: {result.backup_path}")
        return 0

    def _run_dated_tasks(self) -> int:
        target = date.fromisoformat(self.args.date)
        tasks = Writer(self._planner_engine()).list_dated_tasks(target)
        print(json.dumps([
            {
                "id": item.id,
                "date": item.date.isoformat(),
                "title": item.title,
                "estimated_minutes": item.estimated_minutes,
                "preferred_daypart": item.preferred_daypart,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "status": item.status.value,
            }
            for item in tasks
        ], indent=2))
        return 0

    def _run_parse(self) -> int:
        print(json.dumps(parse_common_intent(self.args.text).to_dict(), indent=2))
        return 0

    def _run_route(self) -> int:
        command = parse_common_intent(self.args.text)
        if self.args.confirm:
            if command.confidence == "low":
                print("Clarification required; low-confidence command was not executed")
                return 1
            command = replace(command, requires_confirmation=False)
        result = self._command_router_service().route_command(command)
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.success else 1

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

    def _planning_service(self) -> PlanningCommandService:
        engine = self._planner_engine()
        rules = RulesEngine(self.args.rules)
        return PlanningCommandService(engine, rules, Writer(engine, ProgressEngine()))

    def _calendar_sync_service(self) -> CalendarSyncService:
        return CalendarSyncService(
            self._planner_engine(), RulesEngine(self.args.rules), self._calendar_client()
        )

    def _command_router_service(self) -> PlannerCommandRouter:
        engine = self._planner_engine()
        rules = RulesEngine(self.args.rules)
        planning = PlanningCommandService(engine, rules, Writer(engine, ProgressEngine()))
        return PlannerCommandRouter(
            planning,
            Writer(engine, ProgressEngine()),
            RulesManager(self.args.rules),
            CalendarSyncService(engine, rules, self._calendar_client()),
            DailyCheckInService(engine),
        )

    def _month_plan(self, target_date: date) -> MonthPlan:
        """Load the selected month plan."""

        return self._planner_engine().get_month_plan(self._month_name(target_date))

    def _month_name(self, target_date: date) -> str:
        """Resolve the CLI month option or infer it from a date."""

        return self.args.month or target_date.strftime("%b %Y")

    def _selected_month(self, target_date: date) -> str:
        return getattr(self.args, "sync_month", None) or self._month_name(target_date)

    def _print_or_apply_preview(
        self,
        service: PlanningCommandService,
        preview: Any,
        scope: str,
    ) -> int:
        if not self.args.apply:
            print(json.dumps(preview.to_dict(), indent=2))
            return 0
        result = (
            service.apply_month_plan(preview)
            if scope == "month"
            else service.apply_week_plan(preview)
        )
        print(result.message)
        print("Calendar not synced")
        return 0 if result.success else 1

    def _print_day_plan(self, plan: Any, heading: str) -> None:
        print(f"🗓️  {heading}: {plan.date.isoformat()}")
        for block in plan.blocks:
            print(f"{block.start.strftime('%H:%M')}–{block.end.strftime('%H:%M')}  {block.title}")
        for conflict in plan.conflicts:
            print(f"⚠️  {conflict.item}: {conflict.reason}")

    def _with_dated_tasks(
        self,
        plan: DailyPlan,
        target: date,
        rules: RulesEngine,
    ) -> DailyPlan:
        dated = self._planner_engine().list_dated_tasks(self._month_name(target), target)
        blocks, conflicts = DatedTaskScheduler(rules).schedule_date(
            target, dated, plan.blocks, datetime.now()
        )
        return DailyPlan(
            date=target,
            blocks=sorted(
                [*plan.blocks, *blocks],
                key=lambda item: (
                    item.start.replace(
                        tzinfo=ZoneInfo(rules.rules.profile.timezone)
                    )
                    if item.start.tzinfo is None
                    else item.start
                ),
            ),
            conflicts=[*plan.conflicts, *conflicts],
        )

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
    plan_parser.add_argument("period", choices=("today", "week", "month"))
    plan_parser.add_argument("--week", type=int)
    plan_parser.add_argument("--preview", action="store_true")
    plan_parser.add_argument("--apply", action="store_true")
    plan_parser.add_argument("--from-now", action="store_true")

    replan_parser = subparsers.add_parser("replan")
    replan_parser.add_argument("period", choices=("today",))
    replan_parser.add_argument("--from-now", action="store_true")

    complete_parser = subparsers.add_parser("complete")
    complete_parser.add_argument("task_name")

    subparsers.add_parser("calendar-auth")

    calendar_sync_parser = subparsers.add_parser("calendar-sync")
    calendar_sync_parser.add_argument(
        "period",
        choices=("today", "date", "week", "current-week", "next-week", "range", "month"),
    )
    calendar_sync_parser.add_argument("--month", dest="sync_month")
    calendar_sync_parser.add_argument("--week", type=int)
    calendar_sync_parser.add_argument("--start")
    calendar_sync_parser.add_argument("--end")
    calendar_sync_parser.add_argument("--date")

    checkin_parser = subparsers.add_parser("checkin")
    checkin_parser.add_argument("--date")

    add_dated_parser = subparsers.add_parser("add-dated-task")
    add_dated_parser.add_argument("--date", required=True)
    add_dated_parser.add_argument("--title", required=True)
    add_dated_parser.add_argument("--minutes", type=int, required=True)
    add_dated_parser.add_argument("--daypart", choices=("morning", "afternoon", "evening", "night"))
    add_dated_parser.add_argument("--start-time")
    add_dated_parser.add_argument("--end-time")
    add_dated_parser.add_argument("--hard-time", action="store_true")
    add_dated_parser.add_argument("--category")
    add_dated_parser.add_argument("--notes")

    dated_parser = subparsers.add_parser("dated-tasks")
    dated_parser.add_argument("--date", required=True)

    route_parser = subparsers.add_parser("route")
    route_parser.add_argument("text")
    route_parser.add_argument("--confirm", action="store_true")
    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("text")

    rules_parser = subparsers.add_parser("rules")
    rules_subparsers = rules_parser.add_subparsers(
        dest="rules_action",
        required=True,
    )
    rules_subparsers.add_parser("list")
    set_work_days_parser = rules_subparsers.add_parser("set-work-days")
    set_work_days_parser.add_argument("days", nargs="+")

    subparsers.add_parser("status")
    subparsers.add_parser("validate")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Shadow CLI."""

    args = build_parser().parse_args(argv)
    return ShadowCLI(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
