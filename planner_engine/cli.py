"""Command-line interface for Shadow's Planner OS."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from planner_engine.config import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_EXECUTION_PREVIEW_DIR,
    DEFAULT_EXECUTION_SETTINGS_PATH,
    DEFAULT_EXTERNAL_LINKS_PATH,
    DEFAULT_DECISION_LOG_PATH,
    DEFAULT_GOOGLE_CALENDAR_ID,
    DEFAULT_GOOGLE_CREDENTIALS_PATH,
    DEFAULT_GOOGLE_TIMEZONE,
    DEFAULT_GOOGLE_TOKEN_PATH,
    DEFAULT_PLANNER_PATH,
    DEFAULT_RULES_PATH,
    DEFAULT_APPLE_CALENDAR_HELPER_PATH,
)
from planner_engine.calendar_sync import CalendarSyncService
from planner_engine.calendar_operations import GoogleCalendarOperations
from planner_engine.checkin import DailyCheckInService
from planner_engine.command_router import PlannerCommandRouter, parse_common_intent
from planner_engine.current_time import CurrentTimePlanner
from planner_engine.dated_task_scheduler import DatedTaskScheduler
from planner_engine.doctor import PlannerDoctor
from planner_engine.decision_log import DecisionLog
from planner_engine.execution_factory import create_execution_manager
from planner_engine.execution_service import ExecutionPublishingService
from planner_engine.goal_planner import GoalBreakdownService, GoalPlanningRequest
from planner_engine.target_operations import ExecutionTargetOperations
from planner_engine.excel import ExcelPlannerStore
from planner_engine.importer import PlannerImporter
from planner_engine.models import DailyPlan, MonthPlan, MonthlyGoal, PlannerTask, ScheduledBlock, TaskStatus
from planner_engine.planner import PlannerEngine
from planner_engine.monthly_planner import MonthlyPlanningRequest
from planner_engine.planning_commands import PlanningCommandService, WeekPlanningRequest
from planner_engine.preferences import PreferenceService
from planner_engine.repair import PlannerRepairService
from planner_engine.recurrence import RecurrenceRequest, RecurrenceService
from planner_engine.progress import ProgressEngine
from planner_engine.rules import RulesEngine
from planner_engine.rules_manager import RulesManager
from planner_engine.reviews import ReviewService
from planner_engine.scheduler import SchedulerEngine
from planner_engine.undo import UndoService
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

    def _run_execution_target(self) -> int:
        manager = self._execution_manager()
        action = self.args.execution_action
        if action == "list":
            result = manager.list_execution_targets()
        elif action == "get":
            result = {"active_target": manager.get_active_execution_target()}
        elif action == "set":
            result = manager.set_active_execution_target(self.args.target)
        elif action == "switch-preview":
            result = manager.preview_execution_target_switch(self.args.target).to_dict()
        elif action == "switch-apply":
            result = manager.apply_execution_target_switch(self.args.preview_id)
        elif action == "move-preview":
            result = manager.preview_move_external_items(self.args.source, self.args.destination, date.fromisoformat(self.args.start_date), date.fromisoformat(self.args.end_date)).to_dict()
        elif action == "move-apply":
            result = manager.apply_move_external_items(self.args.preview_id)
        else:
            raise ValueError(f"Unsupported execution-target action: {action}")
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success", True) else 1

    def _run_publish(self) -> int:
        service = ExecutionPublishingService(self._planner_engine(), RulesEngine(self.args.rules), self._execution_manager())
        if self.args.period == "today":
            result = service.publish_today()
        elif self.args.period == "date":
            result = service.publish_date(date.fromisoformat(self.args.date))
        elif self.args.period == "current-week":
            result = service.publish_current_week()
        else:
            result = service.publish_range(date.fromisoformat(self.args.start), date.fromisoformat(self.args.end))
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.success else 1

    def _run_apple_calendar(self) -> int:
        manager = self._execution_manager()
        target = manager.targets["apple_calendar"]
        action = self.args.apple_action
        if action == "calendars":
            result = {"success": True, "calendars": target.client.list_calendars()}
        elif action == "status":
            result = target.health()
        elif action == "create-calendar":
            created = target.client.create_calendar(self.args.title)
            calendar_id = str(created["id"])
            manager.settings.set_apple_calendar_id(calendar_id)
            result = {"success": True, "calendar": created, "apple_calendar_id": calendar_id}
        elif action == "select":
            result = {"success": True, "apple_calendar_id": manager.settings.set_apple_calendar_id(self.args.calendar_id)}
        elif action in {"publish-today", "publish-date", "publish-range"}:
            if manager.get_active_execution_target() != "apple_calendar":
                raise ValueError("Apple Calendar must be the active execution target for publishing")
            service = ExecutionPublishingService(self._planner_engine(), RulesEngine(self.args.rules), manager)
            if action == "publish-today":
                response = service.publish_today()
            elif action == "publish-date":
                response = service.publish_date(date.fromisoformat(self.args.date))
            else:
                response = service.publish_range(date.fromisoformat(self.args.start_date), date.fromisoformat(self.args.end_date))
            result = response.to_dict()
        elif action == "list-range":
            result = {"success": True, "items": [item.__dict__ for item in target.list_items(date.fromisoformat(self.args.start_date), date.fromisoformat(self.args.end_date))]}
        elif action == "reconcile-range":
            start = date.fromisoformat(self.args.start_date)
            end = date.fromisoformat(self.args.end_date)
            blocks = ExecutionPublishingService(self._planner_engine(), RulesEngine(self.args.rules), manager).blocks_for_range(start, end)
            result = {"success": True, **target.reconcile(blocks, start, end).to_dict()}
        elif action == "delete-event":
            result = target.delete_item(self.args.external_id, delete_scope=self.args.scope).to_dict()
        elif action == "update-event":
            block = ScheduledBlock(
                title=self.args.title,
                start=datetime.fromisoformat(self.args.start),
                end=datetime.fromisoformat(self.args.end),
                category=self.args.category,
                source=self.args.source,
                is_fixed=True,
                metadata={"planner_block_id": self.args.planner_block_id} if self.args.planner_block_id else {},
            )
            result = target.update_block(block, self.args.external_id).to_dict()
        elif action == "delete-range-preview":
            result = ExecutionTargetOperations(target, self.args.execution_preview_dir / "apple-calendar").preview_delete_range(date.fromisoformat(self.args.start_date), date.fromisoformat(self.args.end_date))
        elif action == "delete-range-apply":
            result = ExecutionTargetOperations(target, self.args.execution_preview_dir / "apple-calendar").apply_delete_range(self.args.preview_id)
        else:
            raise ValueError(f"Unsupported Apple Calendar action: {action}")
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success", True) else 1

    def _run_review(self) -> int:
        service = ReviewService(self._planner_engine())
        if self.args.period == "daily":
            result = service.daily_review(date.fromisoformat(self.args.date) if self.args.date else None)
        elif self.args.period == "weekly":
            result = service.weekly_review(date.fromisoformat(self.args.date) if self.args.date else None)
        else:
            result = service.monthly_review(self.args.review_month or self._selected_month(date.today()))
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    def _run_doctor(self) -> int:
        report = PlannerDoctor(
            self.args.planner,
            self.args.rules,
            self.args.execution_settings,
            self.args.external_links,
            self.args.execution_preview_dir,
            self.args.decision_log,
            self.args.backup_dir,
        ).run()
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.success else 1

    def _run_preferences(self) -> int:
        service = self._preference_service()
        action = self.args.preferences_action
        if action == "list":
            result = service.list_preferences()
        elif action == "get":
            result = service.get_preference(self.args.name)
        elif action == "update":
            result = service.update_preference(self.args.name, self._json_value(self.args.value))
        elif action == "reset":
            result = service.reset_preference(self.args.name)
        elif action == "explain-active-constraints":
            result = service.explain_active_constraints()
        else:
            raise ValueError(f"Unsupported preferences action: {action}")
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return 0 if result.success else 1

    def _run_repair(self) -> int:
        service = PlannerRepairService(self._execution_manager().links, self.args.execution_preview_dir / "repair")
        if self.args.repair_action == "preview":
            result = service.preview_repair().to_dict()
        elif self.args.repair_action == "apply":
            result = service.apply_repair(self.args.preview_id)
        else:
            raise ValueError(f"Unsupported repair action: {self.args.repair_action}")
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success", True) else 1

    def _run_undo(self) -> int:
        service = UndoService(
            ExcelPlannerStore(self.args.planner, self.args.backup_dir),
            DecisionLog(self.args.decision_log),
            self.args.execution_preview_dir / "undo",
        )
        if self.args.undo_action == "preview":
            result = service.preview_undo(self.args.decision_id).to_dict()
        elif self.args.undo_action == "apply":
            result = service.apply_undo(self.args.preview_id)
        elif self.args.undo_action == "last":
            result = service.undo_last_change()
        else:
            raise ValueError(f"Unsupported undo action: {self.args.undo_action}")
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success", True) else 1

    def _run_recurrence(self) -> int:
        service = self._recurrence_service()
        action = self.args.recurrence_action
        if action == "preview":
            preview = service.preview_recurrence(
                RecurrenceRequest(
                    title=self.args.title,
                    frequency=self.args.frequency,
                    start_date=date.fromisoformat(self.args.start_date),
                    until_date=date.fromisoformat(self.args.until) if self.args.until else None,
                    count=self.args.count,
                    selected_weekdays=self.args.weekday or [],
                    estimated_minutes=self.args.minutes,
                    preferred_daypart=self.args.daypart,
                    category=self.args.category,
                )
            )
            result = preview.to_dict()
        elif action == "apply":
            writer_result = service.apply_recurrence(self.args.preview_id)
            result = asdict(writer_result)
        elif action == "list":
            result = {"success": True, "recurrences": service.list_recurrences()}
        elif action == "pause":
            result = service.pause_recurrence(self.args.recurrence_id)
        elif action == "resume":
            result = service.resume_recurrence(self.args.recurrence_id)
        else:
            raise ValueError(f"Unsupported recurrence action: {action}")
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success", True) else 1

    def _run_goal(self) -> int:
        service = self._goal_service()
        if self.args.goal_action == "preview":
            preview = service.preview_goal_plan(
                GoalPlanningRequest(
                    title=self.args.title,
                    target_date=date.fromisoformat(self.args.target_date),
                    start_date=date.fromisoformat(self.args.start_date),
                    category=self.args.category,
                    weekly_capacity_minutes=self.args.weekly_capacity,
                    allowed_days=self.args.allowed_day or [],
                    preferred_dayparts=[self.args.daypart] if self.args.daypart else [],
                    fixed_daily_minutes=self.args.minutes,
                    notes=self.args.notes,
                )
            )
            result = preview.to_dict()
        elif self.args.goal_action == "apply":
            result = service.apply_goal_plan(self.args.preview_id)
        else:
            raise ValueError(f"Unsupported goal action: {self.args.goal_action}")
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success", True) else 1

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

    def _run_calendar(self) -> int:
        action = self.args.calendar_action
        operations = self._calendar_operations()
        if action == "list-range":
            result = {"success": True, "events": operations.list_range(date.fromisoformat(self.args.start_date), date.fromisoformat(self.args.end_date))}
        elif action == "lookup-event":
            result = {"success": True, "events": operations.lookup_event(self.args.planner_block_id, date.fromisoformat(self.args.start_date), date.fromisoformat(self.args.end_date))}
        elif action in {"delete-event", "delete-series", "delete-future-series"}:
            scope = {"delete-event": "single", "delete-series": "series", "delete-future-series": "future"}[action]
            result = operations.delete_event(self.args.external_id, scope)
        elif action == "update-event":
            block = ScheduledBlock(
                title=self.args.title,
                start=datetime.fromisoformat(self.args.start),
                end=datetime.fromisoformat(self.args.end),
                category=self.args.category,
                source=self.args.source,
                is_fixed=True,
                metadata={"planner_block_id": self.args.planner_block_id} if self.args.planner_block_id else {},
            )
            result = operations.update_event(self.args.external_id, block)
        elif action == "delete-range-preview":
            result = operations.preview_delete_range(date.fromisoformat(self.args.start_date), date.fromisoformat(self.args.end_date)).to_dict()
        elif action == "delete-range-apply":
            result = operations.apply_delete_range(self.args.preview_id)
        elif action == "reconcile-range":
            start, end = date.fromisoformat(self.args.start_date), date.fromisoformat(self.args.end_date)
            blocks = ExecutionPublishingService(self._planner_engine(), RulesEngine(self.args.rules), self._execution_manager()).blocks_for_range(start, end)
            result = operations.reconcile_range(blocks, start, end)
        elif action == "cleanup-orphans-preview":
            start, end = date.fromisoformat(self.args.start_date), date.fromisoformat(self.args.end_date)
            blocks = ExecutionPublishingService(self._planner_engine(), RulesEngine(self.args.rules), self._execution_manager()).blocks_for_range(start, end)
            result = operations.preview_cleanup_orphans(blocks, start, end).to_dict()
        elif action == "cleanup-orphans-apply":
            result = operations.apply_delete_range(self.args.preview_id, "calendar_cleanup_orphans")
        elif action == "repair-mapping":
            result = operations.repair_mapping(self.args.external_id)
        else:
            raise ValueError(f"Unsupported calendar action: {action}")
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success", True) else 1

    def _run_checkin(self) -> int:
        target = date.fromisoformat(self.args.date) if self.args.date else date.today()
        rules = RulesEngine(self.args.rules)
        report = DailyCheckInService(self._planner_engine(), rules_engine=rules).generate_daily_checkin(target)
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

    def _execution_manager(self):
        return create_execution_manager(
            settings_path=self.args.execution_settings,
            links_path=self.args.external_links,
            preview_dir=self.args.execution_preview_dir,
            apple_helper_path=self.args.apple_calendar_helper,
            apple_calendar_id=self.args.apple_calendar_id,
            google_client=self._calendar_client(),
        )

    def _planning_service(self) -> PlanningCommandService:
        engine = self._planner_engine()
        rules = RulesEngine(self.args.rules)
        return PlanningCommandService(engine, rules, Writer(engine, ProgressEngine()))

    def _calendar_sync_service(self) -> CalendarSyncService:
        return CalendarSyncService(
            self._planner_engine(), RulesEngine(self.args.rules), self._calendar_client()
        )

    def _calendar_operations(self) -> GoogleCalendarOperations:
        manager = self._execution_manager()
        return GoogleCalendarOperations(
            manager.targets["google_calendar"].client,
            manager.links,
            self.args.execution_preview_dir / "google-calendar",
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
            DailyCheckInService(engine, rules_engine=rules),
            execution_manager=self._execution_manager(),
            publisher=ExecutionPublishingService(engine, rules, self._execution_manager()),
            preferences=self._preference_service(),
            repair=PlannerRepairService(self._execution_manager().links, self.args.execution_preview_dir / "repair"),
            undo=UndoService(
                ExcelPlannerStore(self.args.planner, self.args.backup_dir),
                DecisionLog(self.args.decision_log),
                self.args.execution_preview_dir / "undo",
            ),
            recurrence=self._recurrence_service(),
        )

    def _preference_service(self) -> PreferenceService:
        return PreferenceService(RulesManager(self.args.rules), self._execution_manager().settings)

    def _recurrence_service(self) -> RecurrenceService:
        engine = self._planner_engine()
        return RecurrenceService(
            self.args.planner,
            Writer(engine, ProgressEngine(), decision_log=DecisionLog(self.args.decision_log)),
            self.args.execution_preview_dir / "recurrence",
        )

    def _goal_service(self) -> GoalBreakdownService:
        engine = self._planner_engine()
        return GoalBreakdownService(
            self.args.planner,
            Writer(engine, ProgressEngine(), decision_log=DecisionLog(self.args.decision_log)),
            self.args.execution_preview_dir / "goal",
        )

    def _json_value(self, value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

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
    parser.add_argument("--execution-settings", type=Path, default=DEFAULT_EXECUTION_SETTINGS_PATH)
    parser.add_argument("--external-links", type=Path, default=DEFAULT_EXTERNAL_LINKS_PATH)
    parser.add_argument("--execution-preview-dir", type=Path, default=DEFAULT_EXECUTION_PREVIEW_DIR)
    parser.add_argument("--apple-calendar-helper", type=Path, default=DEFAULT_APPLE_CALENDAR_HELPER_PATH)
    parser.add_argument("--apple-calendar-id")
    parser.add_argument("--decision-log", type=Path, default=DEFAULT_DECISION_LOG_PATH)

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

    calendar_parser = subparsers.add_parser("calendar")
    calendar_subparsers = calendar_parser.add_subparsers(dest="calendar_action", required=True)
    for action in ("list-range", "reconcile-range", "delete-range-preview", "cleanup-orphans-preview"):
        item = calendar_subparsers.add_parser(action)
        item.add_argument("start_date")
        item.add_argument("end_date")
    lookup = calendar_subparsers.add_parser("lookup-event")
    lookup.add_argument("planner_block_id")
    lookup.add_argument("start_date")
    lookup.add_argument("end_date")
    for action in ("delete-event", "delete-series", "delete-future-series", "repair-mapping"):
        item = calendar_subparsers.add_parser(action)
        item.add_argument("external_id")
    google_update = calendar_subparsers.add_parser("update-event")
    google_update.add_argument("external_id")
    google_update.add_argument("--title", required=True)
    google_update.add_argument("--start", required=True)
    google_update.add_argument("--end", required=True)
    google_update.add_argument("--category", default="planner")
    google_update.add_argument("--source", default="google_calendar_update")
    google_update.add_argument("--planner-block-id")
    for action in ("delete-range-apply", "cleanup-orphans-apply"):
        item = calendar_subparsers.add_parser(action)
        item.add_argument("preview_id")

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

    execution_parser = subparsers.add_parser("execution-target")
    execution_subparsers = execution_parser.add_subparsers(dest="execution_action", required=True)
    execution_subparsers.add_parser("list")
    execution_subparsers.add_parser("get")
    execution_set = execution_subparsers.add_parser("set")
    execution_set.add_argument("target", choices=("google_calendar", "apple_calendar", "none"))
    switch_preview = execution_subparsers.add_parser("switch-preview")
    switch_preview.add_argument("target", choices=("google_calendar", "apple_calendar", "none"))
    switch_apply = execution_subparsers.add_parser("switch-apply")
    switch_apply.add_argument("preview_id")
    move_preview = execution_subparsers.add_parser("move-preview")
    move_preview.add_argument("source", choices=("google_calendar", "apple_calendar"))
    move_preview.add_argument("destination", choices=("google_calendar", "apple_calendar"))
    move_preview.add_argument("start_date")
    move_preview.add_argument("end_date")
    move_apply = execution_subparsers.add_parser("move-apply")
    move_apply.add_argument("preview_id")

    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("period", choices=("today", "date", "range", "current-week"))
    publish_parser.add_argument("--date")
    publish_parser.add_argument("--start")
    publish_parser.add_argument("--end")

    apple_parser = subparsers.add_parser("apple-calendar")
    apple_subparsers = apple_parser.add_subparsers(dest="apple_action", required=True)
    apple_subparsers.add_parser("calendars")
    apple_subparsers.add_parser("status")
    apple_create = apple_subparsers.add_parser("create-calendar")
    apple_create.add_argument("--title", default="Planner OS")
    apple_select = apple_subparsers.add_parser("select")
    apple_select.add_argument("calendar_id")
    apple_subparsers.add_parser("publish-today")
    apple_publish_date = apple_subparsers.add_parser("publish-date")
    apple_publish_date.add_argument("date")
    for action in ("publish-range", "list-range", "reconcile-range"):
        item = apple_subparsers.add_parser(action)
        item.add_argument("start_date")
        item.add_argument("end_date")
    apple_delete = apple_subparsers.add_parser("delete-event")
    apple_delete.add_argument("external_id")
    apple_delete.add_argument("--scope", choices=("single", "future", "series"), default="single")
    apple_update = apple_subparsers.add_parser("update-event")
    apple_update.add_argument("external_id")
    apple_update.add_argument("--title", required=True)
    apple_update.add_argument("--start", required=True)
    apple_update.add_argument("--end", required=True)
    apple_update.add_argument("--category", default="planner")
    apple_update.add_argument("--source", default="apple_calendar_update")
    apple_update.add_argument("--planner-block-id")
    apple_delete_preview = apple_subparsers.add_parser("delete-range-preview")
    apple_delete_preview.add_argument("start_date")
    apple_delete_preview.add_argument("end_date")
    apple_delete_apply = apple_subparsers.add_parser("delete-range-apply")
    apple_delete_apply.add_argument("preview_id")

    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("period", choices=("daily", "weekly", "monthly"))
    review_parser.add_argument("--date")
    review_parser.add_argument("--month", dest="review_month")

    preferences_parser = subparsers.add_parser("preferences")
    preferences_subparsers = preferences_parser.add_subparsers(dest="preferences_action", required=True)
    preferences_subparsers.add_parser("list")
    preferences_explain = preferences_subparsers.add_parser("explain-active-constraints")
    preferences_get = preferences_subparsers.add_parser("get")
    preferences_get.add_argument("name")
    preferences_update = preferences_subparsers.add_parser("update")
    preferences_update.add_argument("name")
    preferences_update.add_argument("value")
    preferences_reset = preferences_subparsers.add_parser("reset")
    preferences_reset.add_argument("name")

    repair_parser = subparsers.add_parser("repair")
    repair_subparsers = repair_parser.add_subparsers(dest="repair_action", required=True)
    repair_subparsers.add_parser("preview")
    repair_apply = repair_subparsers.add_parser("apply")
    repair_apply.add_argument("preview_id")

    undo_parser = subparsers.add_parser("undo")
    undo_subparsers = undo_parser.add_subparsers(dest="undo_action", required=True)
    undo_preview = undo_subparsers.add_parser("preview")
    undo_preview.add_argument("--decision-id")
    undo_apply = undo_subparsers.add_parser("apply")
    undo_apply.add_argument("preview_id")
    undo_subparsers.add_parser("last")

    recurrence_parser = subparsers.add_parser("recurrence")
    recurrence_subparsers = recurrence_parser.add_subparsers(dest="recurrence_action", required=True)
    recurrence_preview = recurrence_subparsers.add_parser("preview")
    recurrence_preview.add_argument("--title", required=True)
    recurrence_preview.add_argument("--frequency", required=True, choices=("daily", "weekdays", "weekends", "selected_weekdays", "weekly", "monthly"))
    recurrence_preview.add_argument("--start-date", required=True)
    recurrence_preview.add_argument("--until")
    recurrence_preview.add_argument("--count", type=int)
    recurrence_preview.add_argument("--weekday", action="append")
    recurrence_preview.add_argument("--minutes", type=int, default=30)
    recurrence_preview.add_argument("--daypart")
    recurrence_preview.add_argument("--category")
    recurrence_apply = recurrence_subparsers.add_parser("apply")
    recurrence_apply.add_argument("preview_id")
    recurrence_subparsers.add_parser("list")
    recurrence_pause = recurrence_subparsers.add_parser("pause")
    recurrence_pause.add_argument("recurrence_id")
    recurrence_resume = recurrence_subparsers.add_parser("resume")
    recurrence_resume.add_argument("recurrence_id")

    goal_parser = subparsers.add_parser("goal")
    goal_subparsers = goal_parser.add_subparsers(dest="goal_action", required=True)
    goal_preview = goal_subparsers.add_parser("preview")
    goal_preview.add_argument("--title", required=True)
    goal_preview.add_argument("--start-date", required=True)
    goal_preview.add_argument("--target-date", required=True)
    goal_preview.add_argument("--category")
    goal_preview.add_argument("--weekly-capacity", type=int, default=300)
    goal_preview.add_argument("--allowed-day", action="append")
    goal_preview.add_argument("--daypart")
    goal_preview.add_argument("--minutes", type=int, default=45)
    goal_preview.add_argument("--notes")
    goal_apply = goal_subparsers.add_parser("apply")
    goal_apply.add_argument("preview_id")

    subparsers.add_parser("doctor")
    subparsers.add_parser("status")
    subparsers.add_parser("validate")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Shadow CLI."""

    args = build_parser().parse_args(argv)
    return ShadowCLI(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
