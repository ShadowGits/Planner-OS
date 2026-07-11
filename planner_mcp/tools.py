"""MCP tool implementations backed by existing Planner OS engines."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from planner_engine.excel import ExcelPlannerStore
from planner_engine.importer import PlannerImporter
from planner_engine.models import MonthPlan, MonthlyGoal, PlannerTask, TaskStatus
from planner_engine.planner import PlannerEngine
from planner_engine.progress import ProgressEngine
from planner_engine.rules import RulesEngine
from planner_engine.scheduler import SchedulerEngine
from planner_engine.writer import Writer, WriterResult
from planner_integrations.google_calendar import GoogleCalendarClient
from planner_mcp.models import PlannerMCPConfig, ToolResult


class PlannerMCPTools:
    """Structured MCP tools for Planner OS."""

    def __init__(self, config: PlannerMCPConfig | None = None) -> None:
        self.config = config or PlannerMCPConfig()

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

    def status(self) -> dict[str, Any]:
        """Return progress status and active slippage alerts."""

        try:
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
                },
            ).to_dict()
        except Exception as error:
            return self._error("Could not generate status", error)

    def complete_task(self, task_name: str, month: str | None = None) -> dict[str, Any]:
        """Mark a task complete through the Semantic Writer."""

        result = self._writer().complete_task(
            month or self._month_name(date.today()),
            task_name,
            completion_date=date.today(),
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
            month or self._month_name(date.today()),
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
            month or self._month_name(date.today()),
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
            month or self._month_name(date.today()),
            task_name,
            destination_week,
            status=status,
        )
        return self._writer_result(result, "Task moved")

    def delete_task(self, task_name: str, month: str | None = None) -> dict[str, Any]:
        """Delete a task through the Semantic Writer."""

        result = self._writer().delete_task(
            month or self._month_name(date.today()),
            task_name,
        )
        return self._writer_result(result, "Task deleted")

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
            today = date.today()
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
        """Generate this week's plan and sync it to Google Calendar."""

        try:
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
            plan = SchedulerEngine(RulesEngine(self.config.rules_path)).plan_week(
                self._month_plan(today),
                week_start,
            )
            result = self._calendar_client().sync_plan(plan)
            return ToolResult(
                success=result.success,
                message="Calendar sync complete" if result.success else "Calendar sync had errors",
                data=result.to_dict(),
                errors=result.errors,
            ).to_dict()
        except Exception as error:
            return self._error("Could not sync this week's calendar plan", error)

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

        return GoogleCalendarClient()

    def _month_plan(self, target_date: date) -> MonthPlan:
        """Load the configured or inferred month plan."""

        return self._planner_engine().get_month_plan(self._month_name(target_date))

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
