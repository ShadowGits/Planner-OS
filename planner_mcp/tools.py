"""MCP tool implementations backed by existing Planner OS engines."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from planner_engine.excel import ExcelPlannerStore
from planner_engine.calendar_sync import CalendarSyncService
from planner_engine.calendar_operations import GoogleCalendarOperations
from planner_engine.checkin import DailyCheckInService
from planner_engine.command_router import PlannerCommand, PlannerCommandRouter, parse_common_intent
from planner_engine.current_time import CurrentTimePlanner
from planner_engine.decision_log import DecisionLog
from planner_engine.doctor import PlannerDoctor
from planner_engine.execution_factory import create_execution_manager
from planner_engine.execution_service import ExecutionPublishingService
from planner_engine.goal_planner import GoalBreakdownService, GoalPlanningRequest
from planner_engine.target_operations import ExecutionTargetOperations
from planner_engine.dated_task_scheduler import DatedTaskScheduler
from planner_engine.models import DailyPlan
from planner_engine.importer import PlannerImporter
from planner_engine.models import MonthPlan, MonthlyGoal, PlannerTask, TaskStatus
from planner_engine.planner import PlannerEngine
from planner_engine.monthly_planner import MonthlyPlanningRequest
from planner_engine.planning_commands import DayReplanRequest, PlanningCommandService, WeekPlanningRequest
from planner_engine.preferences import PreferenceService
from planner_engine.repair import PlannerRepairService
from planner_engine.recurrence import RecurrenceRequest, RecurrenceService
from planner_engine.progress import ProgressEngine
from planner_engine.rules import RulesEngine
from planner_engine.rules_manager import RulesManager
from planner_engine.reviews import ReviewService
from planner_engine.scheduler import SchedulerEngine
from planner_engine.undo import UndoService
from planner_engine.writer import Writer, WriterResult
from planner_integrations.google_calendar import GoogleCalendarClient
from planner_mcp.models import PlannerMCPConfig, ToolResult


class PlannerMCPTools:
    """Structured MCP tools for Planner OS."""

    def __init__(
        self,
        config: PlannerMCPConfig | None = None,
        *,
        google_calendar_client: Any | None = None,
        external_links_store: Any | None = None,
    ) -> None:
        self.config = config or PlannerMCPConfig()
        self._injected_google_calendar_client = google_calendar_client
        self._injected_external_links_store = external_links_store
        self._planning: PlanningCommandService | None = None
        self._calendar_sync: CalendarSyncService | None = None
        self._router: PlannerCommandRouter | None = None
        self._execution = None

    def validate(self) -> dict[str, Any]:
        """Check workbook readability, rules, and planner structure."""

        errors: list[str] = []
        engine = self._planner_engine()

        try:
            workbook = engine.load()
            workbook.close()
        except Exception as error:
            errors.append(f"Workbook is not readable: {error}")

        try:
            RulesEngine(self.config.rules_path)
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
            return ToolResult(
                success=False,
                message="Validation failed",
                errors=errors,
            ).to_dict()
        return ToolResult(success=True, message="Everything OK").to_dict()

    def list_rules(self) -> dict[str, Any]:
        """List permanent planner rules from user-editable YAML data."""

        try:
            return ToolResult(
                success=True,
                message="Rules listed",
                data={"rules": RulesManager(self.config.rules_path).list_rules()},
            ).to_dict()
        except Exception as error:
            return self._error("Could not list rules", error)

    def update_rule(self, path: str, value: Any) -> dict[str, Any]:
        """Update an existing permanent rule path."""

        try:
            rules = RulesManager(self.config.rules_path).update_rule(path, value)
            return ToolResult(
                success=True,
                message="Rule updated",
                data={"rules": rules},
            ).to_dict()
        except Exception as error:
            return self._error("Could not update rule", error)

    def set_work_days(self, days: list[str]) -> dict[str, Any]:
        """Set active work days in permanent planner rules."""

        try:
            rules = RulesManager(self.config.rules_path).set_work_days(days)
            return ToolResult(
                success=True,
                message="Work days updated",
                data={"rules": rules},
            ).to_dict()
        except Exception as error:
            return self._error("Could not set work days", error)

    def set_no_work_days(self, days: list[str]) -> dict[str, Any]:
        """Set no-work days in permanent planner rules."""

        try:
            rules = RulesManager(self.config.rules_path).set_no_work_days(days)
            return ToolResult(
                success=True,
                message="No-work days updated",
                data={"rules": rules},
            ).to_dict()
        except Exception as error:
            return self._error("Could not set no-work days", error)

    def list_execution_targets(self) -> dict[str, Any]:
        return self._execution_result("Execution targets listed", lambda: self._execution_manager().list_execution_targets())

    def get_active_execution_target(self) -> dict[str, Any]:
        return self._execution_result("Active execution target", lambda: {"active_target": self._execution_manager().get_active_execution_target()})

    def set_active_execution_target(self, target: str) -> dict[str, Any]:
        return self._execution_result("Execution target changed; existing external items untouched", lambda: self._execution_manager().set_active_execution_target(target))

    def preview_execution_target_switch(self, target: str) -> dict[str, Any]:
        return self._execution_result("Execution target switch preview", lambda: self._execution_manager().preview_execution_target_switch(target).to_dict())

    def apply_execution_target_switch(self, preview_id: str) -> dict[str, Any]:
        return self._execution_result("Execution target switch applied", lambda: self._execution_manager().apply_execution_target_switch(preview_id))

    def preview_move_external_items(self, source_target: str, destination_target: str, start_date: str, end_date: str) -> dict[str, Any]:
        return self._execution_result("External-item migration preview", lambda: self._execution_manager().preview_move_external_items(source_target, destination_target, date.fromisoformat(start_date), date.fromisoformat(end_date)).to_dict())

    def apply_move_external_items(self, preview_id: str) -> dict[str, Any]:
        return self._execution_result("External-item migration applied", lambda: self._execution_manager().apply_move_external_items(preview_id))

    def publish_date(self, target_date: str) -> dict[str, Any]:
        return self._execution_result("Date publication complete", lambda: self._execution_publisher().publish_date(date.fromisoformat(target_date)).to_dict())

    def publish_today(self) -> dict[str, Any]:
        return self._execution_result("Today publication complete", lambda: self._execution_publisher().publish_today().to_dict())

    def publish_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._execution_result("Range publication complete", lambda: self._execution_publisher().publish_range(date.fromisoformat(start_date), date.fromisoformat(end_date)).to_dict())

    def publish_current_week(self) -> dict[str, Any]:
        return self._execution_result("Current-week publication complete", lambda: self._execution_publisher().publish_current_week().to_dict())

    def apple_calendar_status(self) -> dict[str, Any]:
        return self._execution_result("Apple Calendar status", lambda: self._execution_manager().targets["apple_calendar"].health())

    def apple_calendar_calendars(self) -> dict[str, Any]:
        return self._execution_result("Apple calendars listed", lambda: {"calendars": self._execution_manager().targets["apple_calendar"].client.list_calendars()})

    def create_apple_calendar(self, title: str = "Planner OS") -> dict[str, Any]:
        def action() -> dict[str, Any]:
            manager = self._execution_manager()
            created = manager.targets["apple_calendar"].client.create_calendar(title)
            calendar_id = str(created["id"])
            manager.settings.set_apple_calendar_id(calendar_id)
            return {"success": True, "calendar": created, "apple_calendar_id": calendar_id}

        return self._execution_result("Apple Calendar created and selected", action)

    def set_apple_calendar(self, calendar_id: str) -> dict[str, Any]:
        return self._execution_result("Apple Calendar selected", lambda: {"apple_calendar_id": self._execution_manager().settings.set_apple_calendar_id(calendar_id)})

    def apple_calendar_list_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        target = self._execution_manager().targets["apple_calendar"]
        return self._execution_result("Planner OS Apple Calendar events listed", lambda: {"items": [asdict(item) for item in target.list_items(date.fromisoformat(start_date), date.fromisoformat(end_date))]})

    def apple_calendar_reconcile_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        target = self._execution_manager().targets["apple_calendar"]
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        return self._execution_result("Apple Calendar reconciliation complete", lambda: target.reconcile(self._execution_publisher().blocks_for_range(start, end), start, end).to_dict())

    def apple_calendar_delete_event(self, external_id: str, delete_scope: str = "single") -> dict[str, Any]:
        target = self._execution_manager().targets["apple_calendar"]
        return self._execution_result("Apple Calendar event deletion complete", lambda: target.delete_item(external_id, delete_scope=delete_scope).to_dict())

    def apple_calendar_update_event(self, external_id: str, block: dict[str, Any]) -> dict[str, Any]:
        target = self._execution_manager().targets["apple_calendar"]
        return self._execution_result("Apple Calendar event updated", lambda: target.update_block(self._scheduled_block(block), external_id).to_dict())

    def preview_apple_calendar_delete_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._execution_result("Apple Calendar delete-range preview", lambda: self._apple_operations().preview_delete_range(date.fromisoformat(start_date), date.fromisoformat(end_date)))

    def apply_apple_calendar_delete_range(self, preview_id: str) -> dict[str, Any]:
        return self._execution_result("Apple Calendar delete-range applied", lambda: self._apple_operations().apply_delete_range(preview_id))

    def calendar_list_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._execution_result("Planner OS Google events listed", lambda: {"events": self._calendar_operations().list_range(date.fromisoformat(start_date), date.fromisoformat(end_date))})

    def calendar_lookup_event(self, planner_block_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        return self._execution_result("Google event lookup complete", lambda: {"events": self._calendar_operations().lookup_event(planner_block_id, date.fromisoformat(start_date), date.fromisoformat(end_date))})

    def calendar_update_event(self, external_id: str, block: dict[str, Any]) -> dict[str, Any]:
        return self._execution_result("Google event updated", lambda: self._calendar_operations().update_event(external_id, self._scheduled_block(block)))

    def calendar_delete_event(self, external_id: str, scope: str = "single") -> dict[str, Any]:
        return self._execution_result("Google event deleted", lambda: self._calendar_operations().delete_event(external_id, scope))

    def preview_calendar_delete_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._execution_result("Google delete-range preview", lambda: self._calendar_operations().preview_delete_range(date.fromisoformat(start_date), date.fromisoformat(end_date)).to_dict())

    def apply_calendar_delete_range(self, preview_id: str) -> dict[str, Any]:
        return self._execution_result("Google delete-range applied", lambda: self._calendar_operations().apply_delete_range(preview_id))

    def calendar_reconcile_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        return self._execution_result("Google reconciliation complete", lambda: self._calendar_operations().reconcile_range(self._execution_publisher().blocks_for_range(start, end), start, end))

    def preview_calendar_cleanup_orphans(self, start_date: str, end_date: str) -> dict[str, Any]:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        return self._execution_result("Google orphan-cleanup preview", lambda: self._calendar_operations().preview_cleanup_orphans(self._execution_publisher().blocks_for_range(start, end), start, end).to_dict())

    def apply_calendar_cleanup_orphans(self, preview_id: str) -> dict[str, Any]:
        return self._execution_result("Google orphan cleanup applied", lambda: self._calendar_operations().apply_delete_range(preview_id, "calendar_cleanup_orphans"))

    def calendar_repair_mapping(self, external_id: str) -> dict[str, Any]:
        return self._execution_result("Google mapping repaired", lambda: self._calendar_operations().repair_mapping(external_id))

    def plan_today(self) -> dict[str, Any]:
        """Generate today's schedule without writing to Excel."""

        try:
            today = date.today()
            month_plan = self._month_plan(today)
            rules = RulesEngine(self.config.rules_path)
            progress = self._progress_from_workbook(month_plan, today)
            daily_progress = progress.calculate_daily_progress(
                today,
                self._planned_items(month_plan),
            )
            plan = SchedulerEngine(rules).plan_day(month_plan, today)
            return ToolResult(
                success=True,
                message="Plan generated",
                data={
                    "date": today.isoformat(),
                    "completion_percentage": daily_progress.completion_percentage,
                    "blocks": [
                        {
                            "title": block.title,
                            "start": block.start.isoformat(),
                            "end": block.end.isoformat(),
                            "category": block.category,
                            "source": block.source,
                            "is_fixed": block.is_fixed,
                        }
                        for block in plan.blocks
                    ],
                    "conflicts": [
                        {
                            "item": conflict.item,
                            "reason": conflict.reason,
                            "severity": conflict.severity,
                        }
                        for conflict in plan.conflicts
                    ],
                },
            ).to_dict()
        except Exception as error:
            return self._error("Could not generate plan", error)

    def plan_today_from_now(self, current_datetime: str | None = None) -> dict[str, Any]:
        """Generate today's plan without placing flexible blocks in the past."""

        return self._current_time_plan(current_datetime, replan=False)

    def replan_today_from_now(self, current_datetime: str | None = None) -> dict[str, Any]:
        """Replan today's remaining time without mutating Excel or Calendar."""

        return self._current_time_plan(current_datetime, replan=True)

    def preview_month_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            preview = self._planning_service().preview_month_plan(
                MonthlyPlanningRequest(**self._planning_payload(request))
            )
            return ToolResult(True, "Preview only: no workbook changes made", data=preview.to_dict()).to_dict()
        except Exception as error:
            return self._error("Could not preview month plan", error)

    def apply_month_plan(
        self,
        preview_id: str | None = None,
        preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._apply_payload(
            "month",
            lambda: self._planning_service().apply_month_plan(preview or preview_id or ""),
        )

    def preview_week_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            preview = self._planning_service().preview_week_plan(
                WeekPlanningRequest(**self._planning_payload(request))
            )
            return ToolResult(True, "Preview only: no workbook changes made", data=preview.to_dict()).to_dict()
        except Exception as error:
            return self._error("Could not preview week plan", error)

    def apply_week_plan(
        self,
        preview_id: str | None = None,
        preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._apply_payload(
            "week",
            lambda: self._planning_service().apply_week_plan(preview or preview_id or ""),
        )

    def preview_day_replan(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            preview = self._planning_service().preview_day_replan(
                DayReplanRequest(**self._planning_payload(request))
            )
            return ToolResult(True, "Preview only: no workbook changes made", data=preview.to_dict()).to_dict()
        except Exception as error:
            return self._error("Could not preview day replan", error)

    def apply_day_replan(
        self,
        preview_id: str | None = None,
        preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._apply_payload(
            "day",
            lambda: self._planning_service().apply_day_replan(preview or preview_id or ""),
        )

    def status(self) -> dict[str, Any]:
        """Return progress status and active slippage alerts."""

        try:
            today = self._today()
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
            dated_tasks = self._planner_engine().list_dated_tasks(
                self._month_name(today), today
            )
            return ToolResult(
                success=True,
                message="Status generated",
                data={
                    "date": today.isoformat(),
                    "today_completion_percentage": daily.completion_percentage,
                    "weekly_completion_percentage": weekly.completion_percentage,
                    "monthly_completion_percentage": monthly.completion_percentage,
                    "german_streak_days": german_streak.current_count,
                    "piano_streak_days": piano_streak.current_count,
                    "gym_sessions_completed": weekly.gym_sessions_completed,
                    "gym_sessions_required": weekly.gym_sessions_required,
                    "ielts_sessions_completed": weekly.ielts_sessions_completed,
                    "ielts_sessions_target": weekly.ielts_sessions_target,
                    "ignou_sessions_completed": weekly.ignou_sessions_completed,
                    "ignou_sessions_min": weekly.ignou_sessions_min,
                    "ignou_sessions_max": weekly.ignou_sessions_max,
                    "alerts": [
                        {
                            "item": alert.item,
                            "reason": alert.reason,
                            "severity": alert.severity,
                            "date": alert.alert_date.isoformat(),
                        }
                        for alert in alerts
                    ],
                    "dated_tasks": [self._dated_task_dict(task) for task in dated_tasks],
                },
            ).to_dict()
        except Exception as error:
            return self._error("Could not generate status", error)

    def complete_task(self, task_name: str, month: str | None = None) -> dict[str, Any]:
        """Mark a task complete through the Semantic Writer."""

        result = self._writer().complete_task(
            month or self._month_name(self._today()),
            task_name,
            completion_date=self._today(),
        )
        return self._writer_result(result, "Task complete")

    def add_task(
        self,
        task: str,
        week: int,
        month: str | None = None,
        category: str | None = None,
        status: str = "Not Started",
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Add a weekly task through the Semantic Writer."""

        result = self._writer().add_weekly_task(
            month or self._month_name(self._today()),
            week,
            task,
            category=category,
            status=status,
            notes=notes,
        )
        return self._writer_result(result, "Task added")

    def update_task(
        self,
        task_name: str,
        month: str | None = None,
        new_name: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        target_week: str | None = None,
        status: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing task through the Semantic Writer."""

        result = self._writer().update_task(
            month or self._month_name(self._today()),
            task_name,
            new_name=new_name,
            category=category,
            priority=priority,
            target_week=target_week,
            status=status,
            notes=notes,
        )
        return self._writer_result(result, "Task updated")

    def move_task(
        self,
        task_name: str,
        destination_week: int,
        month: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Move a weekly task through the Semantic Writer."""

        result = self._writer().move_task(
            month or self._month_name(self._today()),
            task_name,
            destination_week,
            status=status,
        )
        return self._writer_result(result, "Task moved")

    def delete_task(self, task_name: str, month: str | None = None) -> dict[str, Any]:
        """Delete a task through the Semantic Writer."""

        result = self._writer().delete_task(
            month or self._month_name(self._today()),
            task_name,
        )
        return self._writer_result(result, "Task deleted")

    def add_dated_task(
        self,
        task_date: str,
        title: str,
        estimated_minutes: int,
        preferred_daypart: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        hard_time: bool | None = None,
        category: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        result = self._writer().add_dated_task(
            date.fromisoformat(task_date), title, estimated_minutes,
            preferred_daypart=preferred_daypart, start_time=start_time,
            end_time=end_time, hard_time=hard_time, category=category, notes=notes,
        )
        return self._writer_result(result, "Dated task added")

    def add_dated_tasks(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        result = self._writer().add_dated_tasks(tasks)
        return self._writer_result(result, "Dated tasks added")

    def update_dated_task(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        return self._writer_result(
            self._writer().update_dated_task(task_id, **changes),
            "Dated task updated",
        )

    def delete_dated_task(self, task_id: str) -> dict[str, Any]:
        return self._writer_result(self._writer().delete_dated_task(task_id), "Dated task deleted")

    def list_dated_tasks(self, task_date: str) -> dict[str, Any]:
        try:
            tasks = self._writer().list_dated_tasks(date.fromisoformat(task_date))
            return ToolResult(
                True,
                "Dated tasks listed",
                data={"date": task_date, "tasks": [self._dated_task_dict(task) for task in tasks]},
            ).to_dict()
        except Exception as error:
            return self._error("Could not list dated tasks", error)

    def import_plan(self, input_path: str) -> dict[str, Any]:
        """Import a structured JSON plan through PlannerImporter."""

        result = PlannerImporter(self._planner_engine()).import_file(Path(input_path))
        if not result.success:
            return ToolResult(
                success=False,
                message="Import failed",
                data={"skipped_items": result.skipped_items},
                errors=result.validation_errors,
            ).to_dict()
        return ToolResult(
            success=True,
            message="Import complete",
            data={
                "goals_imported": result.goals_imported,
                "tasks_imported": result.tasks_imported,
                "skipped_items": result.skipped_items,
                "backup_path": str(result.backup_path) if result.backup_path else None,
            },
        ).to_dict()

    def calendar_sync_today(self) -> dict[str, Any]:
        """Generate today's plan and sync it to Google Calendar."""

        try:
            today = self._today()
            plan = SchedulerEngine(RulesEngine(self.config.rules_path)).plan_day(
                self._month_plan(today),
                today,
            )
            result = self._calendar_client().sync_plan(plan)
            return ToolResult(
                success=result.success,
                message="Calendar sync complete" if result.success else "Calendar sync had errors",
                data=result.to_dict(),
                errors=result.errors,
            ).to_dict()
        except Exception as error:
            return self._error("Could not sync today's calendar plan", error)

    def calendar_sync_week(self) -> dict[str, Any]:
        """Backward-compatible sync that explicitly means current week."""

        try:
            today = self._today()
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)
            plan = SchedulerEngine(RulesEngine(self.config.rules_path)).plan_week(
                self._month_plan(today), week_start
            )
            result = self._calendar_client().sync_plan(plan)
            data = result.to_dict()
            data.update({"start_date": week_start.isoformat(), "end_date": week_end.isoformat(), "scope": "current week"})
            return ToolResult(
                result.success,
                f"Synced current week: {week_start.isoformat()} to {week_end.isoformat()}",
                data=data,
                errors=result.errors,
            ).to_dict()
        except Exception as error:
            return self._error("Could not sync current week", error)

    def calendar_sync_current_week(self) -> dict[str, Any]:
        return self._sync_payload(lambda: self._calendar_sync_service().calendar_sync_current_week())

    def calendar_sync_next_week(self) -> dict[str, Any]:
        return self._sync_payload(lambda: self._calendar_sync_service().calendar_sync_next_week())

    def calendar_sync_week_number(self, month: str, week_number: int) -> dict[str, Any]:
        return self._sync_payload(lambda: self._calendar_sync_service().calendar_sync_week_number(month, week_number))

    def calendar_sync_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._sync_payload(
            lambda: self._calendar_sync_service().calendar_sync_range(
                date.fromisoformat(start_date), date.fromisoformat(end_date)
            )
        )

    def calendar_sync_month(self, month: str) -> dict[str, Any]:
        return self._sync_payload(lambda: self._calendar_sync_service().calendar_sync_month(month))

    def calendar_sync_date(self, task_date: str) -> dict[str, Any]:
        return self._sync_payload(
            lambda: self._calendar_sync_service().calendar_sync_date(date.fromisoformat(task_date))
        )

    def daily_checkin(self, task_date: str | None = None) -> dict[str, Any]:
        try:
            report = DailyCheckInService(self._planner_engine()).generate_daily_checkin(
                date.fromisoformat(task_date) if task_date else None
            )
            return ToolResult(True, "Daily check-in generated", data=report.to_dict()).to_dict()
        except Exception as error:
            return self._error("Could not generate daily check-in", error)

    def daily_review(self, task_date: str | None = None) -> dict[str, Any]:
        return self._execution_result("Daily review generated", lambda: ReviewService(self._planner_engine()).daily_review(date.fromisoformat(task_date) if task_date else None).to_dict())

    def weekly_review(self, task_date: str | None = None) -> dict[str, Any]:
        return self._execution_result("Weekly review generated", lambda: ReviewService(self._planner_engine()).weekly_review(date.fromisoformat(task_date) if task_date else None).to_dict())

    def monthly_review(self, month: str) -> dict[str, Any]:
        return self._execution_result("Monthly review generated", lambda: ReviewService(self._planner_engine()).monthly_review(month).to_dict())

    def planner_doctor(self) -> dict[str, Any]:
        return self._execution_result(
            "Planner doctor complete",
            lambda: PlannerDoctor(
                self.config.planner_path,
                self.config.rules_path,
                self.config.execution_settings_path,
                self.config.external_links_path,
                self.config.execution_preview_dir,
                self.config.decision_log_path,
                self.config.backup_dir,
            ).run().to_dict(),
        )

    def list_preferences(self) -> dict[str, Any]:
        return self._execution_result("Preferences listed", lambda: self._preference_service().list_preferences().to_dict())

    def get_preference(self, name: str) -> dict[str, Any]:
        return self._execution_result("Preference loaded", lambda: self._preference_service().get_preference(name).to_dict())

    def update_preference(self, name: str, value: Any) -> dict[str, Any]:
        return self._execution_result("Preference updated", lambda: self._preference_service().update_preference(name, value).to_dict())

    def reset_preference(self, name: str) -> dict[str, Any]:
        return self._execution_result("Preference reset", lambda: self._preference_service().reset_preference(name).to_dict())

    def explain_active_constraints(self) -> dict[str, Any]:
        return self._execution_result("Active constraints explained", lambda: self._preference_service().explain_active_constraints().to_dict())

    def preview_planner_repair(self) -> dict[str, Any]:
        return self._execution_result("Planner repair preview", lambda: self._repair_service().preview_repair().to_dict())

    def apply_planner_repair(self, preview_id: str) -> dict[str, Any]:
        return self._execution_result("Planner repair applied", lambda: self._repair_service().apply_repair(preview_id))

    def preview_undo(self, decision_id: str | None = None) -> dict[str, Any]:
        return self._execution_result("Undo preview", lambda: self._undo_service().preview_undo(decision_id).to_dict())

    def apply_undo(self, preview_id: str) -> dict[str, Any]:
        return self._execution_result("Undo applied", lambda: self._undo_service().apply_undo(preview_id))

    def undo_last_change(self) -> dict[str, Any]:
        return self._execution_result("Last workbook change undone", lambda: self._undo_service().undo_last_change())

    def preview_recurrence(self, request: dict[str, Any]) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            preview = self._recurrence_service().preview_recurrence(
                RecurrenceRequest(
                    title=str(request["title"]),
                    frequency=str(request["frequency"]),
                    start_date=date.fromisoformat(str(request["start_date"])),
                    until_date=date.fromisoformat(str(request["until_date"])) if request.get("until_date") else None,
                    count=int(request["count"]) if request.get("count") is not None else None,
                    selected_weekdays=[str(item) for item in request.get("selected_weekdays", [])],
                    estimated_minutes=int(request.get("estimated_minutes", 30)),
                    preferred_daypart=request.get("preferred_daypart"),
                    category=request.get("category"),
                )
            )
            return preview.to_dict()

        return self._execution_result("Recurrence preview", action)

    def apply_recurrence(self, preview_id: str) -> dict[str, Any]:
        return self._execution_result("Recurrence applied", lambda: asdict(self._recurrence_service().apply_recurrence(preview_id)))

    def list_recurrences(self) -> dict[str, Any]:
        return self._execution_result("Recurrences listed", lambda: {"recurrences": self._recurrence_service().list_recurrences()})

    def pause_recurrence(self, recurrence_id: str) -> dict[str, Any]:
        return self._execution_result("Recurrence paused", lambda: self._recurrence_service().pause_recurrence(recurrence_id))

    def resume_recurrence(self, recurrence_id: str) -> dict[str, Any]:
        return self._execution_result("Recurrence resumed", lambda: self._recurrence_service().resume_recurrence(recurrence_id))

    def preview_goal_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            preview = self._goal_service().preview_goal_plan(
                GoalPlanningRequest(
                    title=str(request["title"]),
                    target_date=date.fromisoformat(str(request["target_date"])),
                    start_date=date.fromisoformat(str(request["start_date"])),
                    category=request.get("category"),
                    current_level=request.get("current_level"),
                    target_level=request.get("target_level"),
                    weekly_capacity_minutes=int(request.get("weekly_capacity_minutes", 300)),
                    allowed_days=[str(item) for item in request.get("allowed_days", [])],
                    preferred_dayparts=[str(item) for item in request.get("preferred_dayparts", [])],
                    fixed_daily_minutes=int(request.get("fixed_daily_minutes", 45)),
                    supporting_activities=[str(item) for item in request.get("supporting_activities", [])],
                    hard_constraints=[str(item) for item in request.get("hard_constraints", [])],
                    notes=request.get("notes"),
                )
            )
            return preview.to_dict()

        return self._execution_result("Goal plan preview", action)

    def apply_goal_plan(self, preview_id: str) -> dict[str, Any]:
        return self._execution_result("Goal plan applied", lambda: self._goal_service().apply_goal_plan(preview_id))

    def parse_common_intent(self, text: str) -> dict[str, Any]:
        command = parse_common_intent(text)
        return ToolResult(True, "Intent parsed", data={"command": command.to_dict()}).to_dict()

    def route_planner_command(self, command: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._command_router().route_command(PlannerCommand(**command))
            return result.to_dict()
        except Exception as error:
            return self._error("Could not route planner command", error)

    def _planner_engine(self) -> PlannerEngine:
        """Create a workbook-backed PlannerEngine."""

        return PlannerEngine(
            ExcelPlannerStore(
                planner_path=self.config.planner_path,
                backup_dir=self.config.backup_dir,
            )
        )

    def _writer(self) -> Writer:
        """Create a Semantic Writer."""

        return Writer(self._planner_engine(), ProgressEngine())

    def _calendar_client(self) -> GoogleCalendarClient:
        """Create the Google Calendar client."""

        if callable(self._injected_google_calendar_client):
            return self._injected_google_calendar_client()
        return self._injected_google_calendar_client or GoogleCalendarClient()

    def _planning_service(self) -> PlanningCommandService:
        if self._planning is None:
            engine = self._planner_engine()
            rules = RulesEngine(self.config.rules_path)
            self._planning = PlanningCommandService(engine, rules, Writer(engine, ProgressEngine()))
        return self._planning

    def _calendar_sync_service(self) -> CalendarSyncService:
        if self._calendar_sync is None:
            self._calendar_sync = CalendarSyncService(
                self._planner_engine(),
                RulesEngine(self.config.rules_path),
                self._calendar_client(),
            )
        return self._calendar_sync

    def _command_router(self) -> PlannerCommandRouter:
        if self._router is None:
            engine = self._planner_engine()
            writer = Writer(engine, ProgressEngine())
            self._router = PlannerCommandRouter(
                self._planning_service(), writer, RulesManager(self.config.rules_path),
                self._calendar_sync_service(), DailyCheckInService(engine),
                execution_manager=self._execution_manager(),
                publisher=self._execution_publisher(),
                preferences=self._preference_service(),
                repair=self._repair_service(),
                undo=self._undo_service(),
                recurrence=self._recurrence_service(),
            )
        return self._router

    def _execution_manager(self):
        if self._execution is None:
            self._execution = create_execution_manager(
                settings_path=self.config.execution_settings_path,
                links_path=self.config.external_links_path,
                preview_dir=self.config.execution_preview_dir,
                apple_helper_path=self.config.apple_calendar_helper_path,
                apple_calendar_id=self.config.apple_calendar_id,
                google_client=self._calendar_client(),
                links_store=self._injected_external_links_store,
            )
        return self._execution

    def _execution_publisher(self) -> ExecutionPublishingService:
        return ExecutionPublishingService(self._planner_engine(), RulesEngine(self.config.rules_path), self._execution_manager())

    def _calendar_operations(self) -> GoogleCalendarOperations:
        manager = self._execution_manager()
        return GoogleCalendarOperations(manager.targets["google_calendar"].client, manager.links, self.config.execution_preview_dir / "google-calendar")

    def _preference_service(self) -> PreferenceService:
        return PreferenceService(RulesManager(self.config.rules_path), self._execution_manager().settings)

    def _repair_service(self) -> PlannerRepairService:
        return PlannerRepairService(self._execution_manager().links, self.config.execution_preview_dir / "repair")

    def _undo_service(self) -> UndoService:
        return UndoService(
            ExcelPlannerStore(self.config.planner_path, self.config.backup_dir),
            DecisionLog(self.config.decision_log_path),
            self.config.execution_preview_dir / "undo",
        )

    def _recurrence_service(self) -> RecurrenceService:
        engine = self._planner_engine()
        return RecurrenceService(
            self.config.planner_path,
            Writer(engine, ProgressEngine(), decision_log=DecisionLog(self.config.decision_log_path)),
            self.config.execution_preview_dir / "recurrence",
        )

    def _goal_service(self) -> GoalBreakdownService:
        engine = self._planner_engine()
        return GoalBreakdownService(
            self.config.planner_path,
            Writer(engine, ProgressEngine(), decision_log=DecisionLog(self.config.decision_log_path)),
            self.config.execution_preview_dir / "goal",
        )

    def _apple_operations(self):
        return ExecutionTargetOperations(self._execution_manager().targets["apple_calendar"], self.config.execution_preview_dir / "apple-calendar")

    def _scheduled_block(self, payload: dict[str, Any]):
        from planner_engine.models import ScheduledBlock
        return ScheduledBlock(
            title=str(payload["title"]), start=datetime.fromisoformat(str(payload["start"])),
            end=datetime.fromisoformat(str(payload["end"])), category=str(payload.get("category", "planner")),
            source=str(payload.get("source", "calendar_update")), is_fixed=bool(payload.get("is_fixed", False)),
            metadata=dict(payload.get("metadata", {})),
        )

    def _execution_result(self, message: str, action: Any) -> dict[str, Any]:
        try:
            data = action()
            success = bool(data.get("success", True)) if isinstance(data, dict) else True
            errors = list(data.get("errors", [])) if isinstance(data, dict) else []
            return ToolResult(success, message, data=data, errors=errors).to_dict()
        except Exception as error:
            return self._error(message, error)

    def _month_plan(self, target_date: date) -> MonthPlan:
        """Load the configured or inferred month plan."""

        return self._planner_engine().get_month_plan(self._month_name(target_date))


    def _today(self) -> date:
        if self.config.timezone:
            from zoneinfo import ZoneInfo
            from datetime import datetime
            return datetime.now(ZoneInfo(self.config.timezone)).date()
        return date.today()
    def _month_name(self, target_date: date) -> str:
        """Resolve configured month or infer one from date."""

        return self.config.month or target_date.strftime("%b %Y")

    def _progress_from_workbook(
        self,
        month_plan: MonthPlan,
        target_date: date,
    ) -> ProgressEngine:
        """Seed ProgressEngine from workbook statuses."""

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
        """Infer a recurring key for status summaries."""

        text = f"{item.name} {item.category or ''}".casefold()
        for key in ("german", "piano", "gym", "ielts", "ignou"):
            if key in text:
                return key
        return item.category

    def _session_count_for(self, item: PlannerTask | MonthlyGoal) -> int:
        """Infer session count for status summaries."""

        del item
        return 1

    def _week_of_month(self, target_date: date) -> int:
        """Return a simple one-based week number within a month."""

        return ((target_date.day - 1) // 7) + 1

    def _current_time_plan(self, current_datetime: str | None, *, replan: bool) -> dict[str, Any]:
        try:
            now = datetime.fromisoformat(current_datetime) if current_datetime else datetime.now()
            planner = CurrentTimePlanner(RulesEngine(self.config.rules_path))
            plan = (
                planner.replan_today_from_now(self._month_plan(now.date()), now)
                if replan
                else planner.plan_today_from_now(self._month_plan(now.date()), now)
            )
            dated = self._planner_engine().list_dated_tasks(
                self._month_name(now.date()), now.date()
            )
            dated_blocks, dated_conflicts = DatedTaskScheduler(
                RulesEngine(self.config.rules_path)
            ).schedule_date(now.date(), dated, plan.blocks, now)
            plan = DailyPlan(
                date=plan.date,
                blocks=[*plan.blocks, *dated_blocks],
                conflicts=[*plan.conflicts, *dated_conflicts],
            )
            return ToolResult(
                True,
                "Plan generated from current time; no workbook changes made",
                data={
                    "date": plan.date.isoformat(),
                    "blocks": [
                        {"title": item.title, "start": item.start.isoformat(), "end": item.end.isoformat(), "category": item.category, "source": item.source, "is_fixed": item.is_fixed}
                        for item in plan.blocks
                    ],
                    "conflicts": [
                        {"item": item.item, "reason": item.reason, "severity": item.severity}
                        for item in plan.conflicts
                    ],
                    "calendar_synced": False,
                },
            ).to_dict()
        except Exception as error:
            return self._error("Could not generate current-time plan", error)

    def _planning_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        for key in ("start_date", "end_date", "target_date"):
            if normalized.get(key) and isinstance(normalized[key], str):
                normalized[key] = date.fromisoformat(normalized[key])
        if normalized.get("current_datetime") and isinstance(normalized["current_datetime"], str):
            normalized["current_datetime"] = datetime.fromisoformat(normalized["current_datetime"])
        return normalized

    def _apply_payload(self, scope: str, action: Any) -> dict[str, Any]:
        try:
            result = action()
            return ToolResult(result.success, result.message, data=result.to_dict(), errors=result.errors).to_dict()
        except Exception as error:
            return self._error(f"Could not apply {scope} plan", error)

    def _sync_payload(self, action: Any) -> dict[str, Any]:
        try:
            result = action()
            return ToolResult(result.success, result.message, data=result.to_dict(), errors=result.errors).to_dict()
        except Exception as error:
            return self._error("Could not sync calendar range", error)

    def _dated_task_dict(self, task: Any) -> dict[str, Any]:
        data = asdict(task)
        data["date"] = task.date.isoformat()
        data["status"] = task.status.value
        return data

    def _writer_result(self, result: WriterResult, success_message: str) -> dict[str, Any]:
        """Convert WriterResult into a structured MCP payload."""

        if not result.success:
            return ToolResult(
                success=False,
                message="Writer operation failed",
                data={
                    "operation": result.operation,
                    "item_name": result.item_name,
                    "backup_path": str(result.backup_path) if result.backup_path else None,
                },
                errors=list(result.errors),
            ).to_dict()
        return ToolResult(
            success=True,
            message=success_message,
            data={
                "operation": result.operation,
                "item_name": result.item_name,
                "backup_path": str(result.backup_path) if result.backup_path else None,
                "updated_fields": list(result.updated_fields),
                "progress_updated": result.progress_execution is not None,
                "metadata": result.metadata,
            },
        ).to_dict()

    def _error(self, message: str, error: Exception) -> dict[str, Any]:
        """Return a structured error payload."""

        return ToolResult(
            success=False,
            message=message,
            errors=[str(error)],
        ).to_dict()
