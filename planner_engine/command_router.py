"""Safe structured command router and small deterministic intent parser."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from planner_engine.calendar_sync import CalendarSyncService
from planner_engine.checkin import DailyCheckInService
from planner_engine.date_utils import current_week_range, next_week_range, week_number_for_date
from planner_engine.monthly_planner import MonthlyPlanningRequest
from planner_engine.planning_commands import (
    DayReplanRequest,
    PlanningCommandService,
    WeekPlanningRequest,
)
from planner_engine.rules_manager import RulesManager
from planner_engine.writer import Writer


LARGE_WRITE_COMMANDS = {"apply_day_replan", "apply_week_plan", "apply_month_plan"}
COMMAND_TYPES = {
    "complete_task",
    "add_task",
    "update_task",
    "move_task",
    "set_rule",
    "preview_day_replan",
    "apply_day_replan",
    "preview_week_plan",
    "apply_week_plan",
    "preview_month_plan",
    "apply_month_plan",
    "calendar_sync_current_week",
    "calendar_sync_next_week",
    "calendar_sync_range",
    "calendar_sync_week_number",
    "calendar_sync_month",
    "daily_checkin",
    "add_dated_task",
    "update_dated_task",
    "delete_dated_task",
    "list_dated_tasks",
    "calendar_sync_date",
    "switch_active_execution_target",
    "publish_active_target",
    "preview_planner_repair",
    "apply_planner_repair",
    "preview_undo",
    "apply_undo",
    "undo_last_change",
    "update_preference",
    "list_preferences",
    "get_preference",
    "reset_preference",
    "explain_active_constraints",
    "create_goal_plan",
    "preview_goal_plan",
    "apply_goal_plan",
    "daily_review",
    "weekly_review",
    "monthly_review",
    "planner_doctor",
    "migrate_external_items",
    "preview_migrate_external_items",
    "apply_migrate_external_items",
    "delete_external_items",
    "preview_recurrence",
    "apply_recurrence",
    "pause_recurrence",
    "resume_recurrence",
}


@dataclass(frozen=True)
class PlannerCommand:
    command_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    preview_required: bool = False
    source_text: str | None = None
    confidence: str = "high"
    requires_confirmation: bool = False

    def __post_init__(self) -> None:
        if self.command_type in LARGE_WRITE_COMMANDS and not self.preview_required:
            object.__setattr__(self, "preview_required", True)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class PlannerCommandResult:
    success: bool
    message: str
    command_type: str
    preview: dict[str, Any] | None = None
    applied_changes: dict[str, Any] | None = None
    backup_path: str | None = None
    calendar_sync_result: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


class PlannerCommandRouter:
    """Validate commands and dispatch them to planner-owned services."""

    def __init__(
        self,
        planning: PlanningCommandService,
        writer: Writer,
        rules_manager: RulesManager,
        calendar: CalendarSyncService,
        checkin: DailyCheckInService,
        execution_manager: Any | None = None,
        publisher: Any | None = None,
        preferences: Any | None = None,
        repair: Any | None = None,
        undo: Any | None = None,
        recurrence: Any | None = None,
        reviews: Any | None = None,
        doctor: Any | None = None,
        goal_planner: Any | None = None,
    ) -> None:
        self.planning = planning
        self.writer = writer
        self.rules_manager = rules_manager
        self.calendar = calendar
        self.checkin = checkin
        self.execution_manager = execution_manager
        self.publisher = publisher
        self.preferences = preferences
        self.repair = repair
        self.undo = undo
        self.recurrence = recurrence
        self.reviews = reviews
        self.doctor = doctor
        self.goal_planner = goal_planner

    def route_command(self, command: PlannerCommand) -> PlannerCommandResult:
        """Route a validated command; ambiguous or unconfirmed writes are refused."""

        if command.command_type not in COMMAND_TYPES:
            return self._error(command, f"Unknown command_type: {command.command_type}")
        if command.requires_confirmation:
            return PlannerCommandResult(
                False,
                "Clarification or confirmation required; no write performed",
                command.command_type,
                warnings=["No workbook or calendar changes made"],
                requires_confirmation=True,
            )
        try:
            return self._dispatch(command)
        except Exception as error:
            return self._error(command, str(error))

    def _dispatch(self, command: PlannerCommand) -> PlannerCommandResult:
        payload = command.payload
        kind = command.command_type
        if kind == "complete_task":
            result = self.writer.complete_task(payload["month"], payload["task_name"])
            return self._writer_result(command, result)
        if kind == "add_task":
            result = self.writer.add_weekly_task(
                payload["month"], int(payload["week"]), payload["task"],
                category=payload.get("category"), notes=payload.get("notes"),
            )
            return self._writer_result(command, result)
        if kind == "update_task":
            fields = {key: value for key, value in payload.items() if key not in {"month", "task_name"}}
            return self._writer_result(command, self.writer.update_task(payload["month"], payload["task_name"], **fields))
        if kind == "move_task":
            return self._writer_result(
                command,
                self.writer.move_task(payload["month"], payload["task_name"], int(payload["destination_week"])),
            )
        if kind == "set_rule":
            rules = self.rules_manager.update_rule(payload["path"], payload["value"])
            return PlannerCommandResult(True, "Rule updated", kind, applied_changes={"rules": rules})
        if kind == "add_dated_task":
            if isinstance(payload.get("tasks"), list):
                return self._writer_result(
                    command,
                    self.writer.add_dated_tasks(payload["tasks"]),
                )
            task_date = _date(payload["date"])
            fields = {key: value for key, value in payload.items() if key != "date"}
            return self._writer_result(command, self.writer.add_dated_task(task_date, **fields))
        if kind == "update_dated_task":
            fields = {key: value for key, value in payload.items() if key != "task_id"}
            return self._writer_result(command, self.writer.update_dated_task(payload["task_id"], **fields))
        if kind == "delete_dated_task":
            return self._writer_result(command, self.writer.delete_dated_task(payload["task_id"]))
        if kind == "list_dated_tasks":
            tasks = self.writer.list_dated_tasks(_date(payload["date"]))
            return PlannerCommandResult(True, "Dated tasks listed", kind, preview={"tasks": [_serialize(asdict(task)) for task in tasks]})
        if kind == "preview_month_plan":
            preview = self.planning.preview_month_plan(MonthlyPlanningRequest(**payload))
            return PlannerCommandResult(True, "Monthly plan preview generated", kind, preview=preview.to_dict(), warnings=preview.warnings)
        if kind == "apply_month_plan":
            return self._apply_result(
                command,
                self.planning.apply_month_plan(
                    payload.get("preview") or payload.get("preview_id", "")
                ),
            )
        if kind == "preview_week_plan":
            normalized = self._normalize_relative_week(payload)
            preview = self.planning.preview_week_plan(WeekPlanningRequest(**normalized))
            return PlannerCommandResult(True, "Week plan preview generated", kind, preview=preview.to_dict(), warnings=preview.warnings)
        if kind == "apply_week_plan":
            return self._apply_result(
                command,
                self.planning.apply_week_plan(
                    payload.get("preview") or payload.get("preview_id", "")
                ),
            )
        if kind == "preview_day_replan":
            preview = self.planning.preview_day_replan(DayReplanRequest(**payload))
            return PlannerCommandResult(True, "Day replan preview generated", kind, preview=preview.to_dict(), warnings=preview.warnings)
        if kind == "apply_day_replan":
            return self._apply_result(
                command,
                self.planning.apply_day_replan(
                    payload.get("preview") or payload.get("preview_id", "")
                ),
            )
        if kind == "calendar_sync_current_week":
            result = self.calendar.calendar_sync_current_week(payload.get("today"))
            return PlannerCommandResult(result.success, result.message, kind, calendar_sync_result=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "calendar_sync_next_week":
            result = self.calendar.calendar_sync_next_week(payload.get("today"))
            return PlannerCommandResult(result.success, result.message, kind, calendar_sync_result=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "calendar_sync_range":
            result = self.calendar.calendar_sync_range(_date(payload["start_date"]), _date(payload["end_date"]))
            return PlannerCommandResult(result.success, result.message, kind, calendar_sync_result=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "calendar_sync_week_number":
            result = self.calendar.calendar_sync_week_number(
                str(payload["month"]), int(payload["week_number"])
            )
            return PlannerCommandResult(result.success, result.message, kind, calendar_sync_result=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "calendar_sync_month":
            result = self.calendar.calendar_sync_month(str(payload["month"]))
            return PlannerCommandResult(result.success, result.message, kind, calendar_sync_result=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "calendar_sync_date":
            result = self.calendar.calendar_sync_date(_date(payload["date"]))
            return PlannerCommandResult(result.success, result.message, kind, calendar_sync_result=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "daily_checkin":
            report = self.checkin.generate_daily_checkin(_date(payload["date"]) if payload.get("date") else None)
            return PlannerCommandResult(True, "Daily check-in generated", kind, preview=report.to_dict())
        if kind == "switch_active_execution_target":
            service = self._required("execution_manager", self.execution_manager)
            result = service.set_active_execution_target(str(payload["target"]))
            return PlannerCommandResult(True, "Active execution target switched", kind, applied_changes=result)
        if kind == "publish_active_target":
            service = self._required("publisher", self.publisher)
            if payload.get("date"):
                result = service.publish_date(_date(payload["date"]))
            elif payload.get("start_date") and payload.get("end_date"):
                result = service.publish_range(_date(payload["start_date"]), _date(payload["end_date"]))
            elif payload.get("period") == "current_week":
                result = service.publish_current_week()
            else:
                result = service.publish_today()
            return PlannerCommandResult(result.success, result.message, kind, applied_changes=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "update_preference":
            service = self._required("preferences", self.preferences)
            result = service.update_preference(str(payload["name"]), payload.get("value"))
            return PlannerCommandResult(result.success, result.message, kind, applied_changes=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "list_preferences":
            service = self._required("preferences", self.preferences)
            result = service.list_preferences()
            return PlannerCommandResult(result.success, result.message, kind, preview=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "get_preference":
            service = self._required("preferences", self.preferences)
            result = service.get_preference(str(payload["name"]))
            return PlannerCommandResult(result.success, result.message, kind, preview=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "reset_preference":
            service = self._required("preferences", self.preferences)
            result = service.reset_preference(str(payload["name"]))
            return PlannerCommandResult(result.success, result.message, kind, applied_changes=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "explain_active_constraints":
            service = self._required("preferences", self.preferences)
            return PlannerCommandResult(True, "Active constraints explained", kind, preview=service.explain_active_constraints().to_dict())
        if kind in {"create_goal_plan", "preview_goal_plan"}:
            service = self._required("goal_planner", self.goal_planner)
            preview = service.preview_goal_plan(payload["request"])
            return PlannerCommandResult(True, "Goal plan preview generated", kind, preview=preview.to_dict(), warnings=preview.assumptions)
        if kind == "apply_goal_plan":
            service = self._required("goal_planner", self.goal_planner)
            result = service.apply_goal_plan(str(payload["preview_id"]))
            return PlannerCommandResult(bool(result.get("success", True)), "Goal plan applied", kind, applied_changes=result, errors=list(result.get("errors", [])))
        if kind == "daily_review":
            service = self._required("reviews", self.reviews)
            result = service.daily_review(_date(payload["date"]) if payload.get("date") else None)
            return PlannerCommandResult(True, "Daily review generated", kind, preview=result.to_dict())
        if kind == "weekly_review":
            service = self._required("reviews", self.reviews)
            result = service.weekly_review(_date(payload["date"]) if payload.get("date") else None)
            return PlannerCommandResult(True, "Weekly review generated", kind, preview=result.to_dict())
        if kind == "monthly_review":
            service = self._required("reviews", self.reviews)
            result = service.monthly_review(str(payload["month"]))
            return PlannerCommandResult(True, "Monthly review generated", kind, preview=result.to_dict())
        if kind == "planner_doctor":
            service = self._required("doctor", self.doctor)
            result = service.run()
            return PlannerCommandResult(result.success, "Planner doctor completed", kind, preview=result.to_dict(), warnings=result.warnings, errors=result.errors)
        if kind == "preview_migrate_external_items":
            service = self._required("execution_manager", self.execution_manager)
            preview = service.preview_move_external_items(str(payload["source"]), str(payload["destination"]), _date(payload["start_date"]), _date(payload["end_date"]))
            return PlannerCommandResult(True, "External item migration preview generated", kind, preview=preview.to_dict(), warnings=preview.warnings)
        if kind in {"apply_migrate_external_items", "migrate_external_items"}:
            service = self._required("execution_manager", self.execution_manager)
            result = service.apply_move_external_items(str(payload["preview_id"]), payload.get("blocks_by_id"))
            return PlannerCommandResult(bool(result.get("success", True)), "External item migration applied", kind, applied_changes=result, warnings=list(result.get("warnings", [])), errors=list(result.get("errors", [])))
        if kind == "delete_external_items":
            return PlannerCommandResult(False, "External deletion requires a target-specific preview/apply command", kind, requires_confirmation=True, warnings=["No calendar changes made"])
        if kind == "preview_planner_repair":
            service = self._required("repair", self.repair)
            preview = service.preview_repair()
            return PlannerCommandResult(True, "Planner repair preview generated", kind, preview=preview.to_dict(), warnings=preview.warnings)
        if kind == "apply_planner_repair":
            service = self._required("repair", self.repair)
            result = service.apply_repair(str(payload["preview_id"]))
            return PlannerCommandResult(bool(result.get("success", True)), "Planner repair applied", kind, applied_changes=result, errors=list(result.get("errors", [])))
        if kind == "preview_undo":
            service = self._required("undo", self.undo)
            preview = service.preview_undo(payload.get("decision_id"))
            return PlannerCommandResult(True, "Undo preview generated", kind, preview=preview.to_dict(), warnings=preview.warnings)
        if kind == "apply_undo":
            service = self._required("undo", self.undo)
            result = service.apply_undo(str(payload["preview_id"]))
            return PlannerCommandResult(bool(result.get("success", True)), "Undo applied", kind, applied_changes=result, errors=list(result.get("errors", [])))
        if kind == "undo_last_change":
            service = self._required("undo", self.undo)
            result = service.undo_last_change()
            return PlannerCommandResult(bool(result.get("success", True)), "Last change undone", kind, applied_changes=result, errors=list(result.get("errors", [])))
        if kind == "preview_recurrence":
            service = self._required("recurrence", self.recurrence)
            preview = service.preview_recurrence(payload["request"])
            return PlannerCommandResult(True, "Recurrence preview generated", kind, preview=preview.to_dict(), warnings=preview.warnings)
        if kind == "apply_recurrence":
            service = self._required("recurrence", self.recurrence)
            result = service.apply_recurrence(str(payload["preview_id"]))
            return self._writer_result(command, result)
        if kind == "pause_recurrence":
            service = self._required("recurrence", self.recurrence)
            result = service.pause_recurrence(str(payload["recurrence_id"]))
            return PlannerCommandResult(bool(result.get("success", True)), "Recurrence paused", kind, applied_changes=result, errors=list(result.get("errors", [])))
        if kind == "resume_recurrence":
            service = self._required("recurrence", self.recurrence)
            result = service.resume_recurrence(str(payload["recurrence_id"]))
            return PlannerCommandResult(bool(result.get("success", True)), "Recurrence resumed", kind, applied_changes=result, errors=list(result.get("errors", [])))
        raise ValueError(f"Unsupported command_type: {kind}")

    def _required(self, name: str, service: Any | None) -> Any:
        if service is None:
            raise ValueError(f"Router service not configured: {name}")
        return service

    def _normalize_relative_week(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        relative = normalized.pop("relative_week", None)
        if relative:
            today = _date(normalized.pop("today", date.today()))
            start, end = next_week_range(today) if relative == "next" else current_week_range(today)
            normalized["start_date"] = start
            normalized["end_date"] = end
            normalized.setdefault("month", start.strftime("%b %Y"))
        return normalized

    def _writer_result(self, command: PlannerCommand, result: Any) -> PlannerCommandResult:
        return PlannerCommandResult(
            result.success,
            "Planner mutation applied" if result.success else "Planner mutation failed",
            command.command_type,
            applied_changes=result.metadata if result.success else None,
            backup_path=str(result.backup_path) if result.backup_path else None,
            warnings=list(result.warnings),
            errors=list(result.errors),
        )

    def _apply_result(self, command: PlannerCommand, result: Any) -> PlannerCommandResult:
        return PlannerCommandResult(
            result.success, result.message, command.command_type,
            applied_changes={"count": result.applied_changes},
            backup_path=result.backup_path,
            warnings=result.warnings,
            errors=result.errors,
        )

    def _error(self, command: PlannerCommand, message: str) -> PlannerCommandResult:
        return PlannerCommandResult(False, "Command rejected", command.command_type, errors=[message], requires_confirmation=command.requires_confirmation)


def parse_common_intent(text: str, today: date | None = None) -> PlannerCommand:
    """Parse a deliberately small set of common planner phrases."""

    source = text.strip()
    normalized = " ".join(source.casefold().split())
    today = today or date.today()
    month = today.strftime("%b %Y")

    if normalized in {"sync week", "sync the week"}:
        return PlannerCommand("calendar_sync_current_week", {}, source_text=source, confidence="low", requires_confirmation=True)
    if normalized in {"undo the last planner change", "undo last planner change", "undo last change"}:
        return PlannerCommand("undo_last_change", {}, source_text=source, confidence="medium", requires_confirmation=True)
    if normalized in {"diagnose planner", "run planner doctor"}:
        return PlannerCommand("planner_doctor", {}, source_text=source)
    if normalized in {"preview repair", "preview planner repair"}:
        return PlannerCommand("preview_planner_repair", {}, source_text=source)
    if normalized in {"daily review", "generate daily review"}:
        return PlannerCommand("daily_review", {"date": today}, source_text=source)
    if normalized in {"weekly review", "generate weekly review"}:
        return PlannerCommand("weekly_review", {"date": today}, source_text=source)
    if normalized in {"monthly review", "generate monthly review"}:
        return PlannerCommand("monthly_review", {"month": month}, source_text=source)
    if normalized in {"publish today using my active target", "publish today using active target"}:
        return PlannerCommand("publish_active_target", {"date": today}, source_text=source, confidence="medium", requires_confirmation=True)
    if normalized in {"publish current week using my active target", "publish current week using active target"}:
        return PlannerCommand("publish_active_target", {"period": "current_week"}, source_text=source, confidence="medium", requires_confirmation=True)
    if "switch future publishing to apple calendar" in normalized:
        return PlannerCommand("switch_active_execution_target", {"target": "apple_calendar"}, source_text=source, confidence="medium", requires_confirmation=True)
    if "switch future publishing to google calendar" in normalized:
        return PlannerCommand("switch_active_execution_target", {"target": "google_calendar"}, source_text=source, confidence="medium", requires_confirmation=True)
    if normalized in {"stop publishing externally", "turn off external publishing"}:
        return PlannerCommand("switch_active_execution_target", {"target": "none"}, source_text=source, confidence="medium", requires_confirmation=True)
    delete_apple = re.match(r"delete\s+tomorrow'?s\s+planner os events\s+from\s+apple calendar$", normalized)
    if delete_apple:
        return PlannerCommand(
            "delete_external_items",
            {"target": "apple_calendar", "date": today + timedelta(days=1)},
            source_text=source,
            confidence="medium",
            requires_confirmation=True,
        )
    if re.search(r"\bsync (?:the )?(?:next|coming) week\b", normalized):
        return PlannerCommand("calendar_sync_next_week", {"today": today}, source_text=source)
    if re.search(r"\bsync (?:the )?current week\b", normalized):
        return PlannerCommand("calendar_sync_current_week", {"today": today}, source_text=source)
    if re.search(r"\bplan (?:my |the )?coming week\b", normalized):
        return PlannerCommand("preview_week_plan", {"relative_week": "next", "today": today}, source_text=source)
    if normalized in {"daily checkin", "daily check-in", "checkin", "check-in"}:
        return PlannerCommand("daily_checkin", {"date": today}, source_text=source)
    if normalized in {"plan today from now", "replan today from now"}:
        return PlannerCommand(
            "preview_day_replan",
            {"month": month, "target_date": today, "current_datetime": datetime.now()},
            source_text=source,
        )
    split_task = re.fullmatch(
        r"(.+?)\s+half\s+today\s+and\s+half\s+tomorrow(?:\s+(morning|afternoon|evening|night))?",
        normalized,
    )
    if split_task:
        title = split_task.group(1).strip()
        tomorrow_daypart = split_task.group(2) or "afternoon"
        return PlannerCommand(
            "add_dated_task",
            {
                "tasks": [
                    {
                        "date": today,
                        "title": f"{title} - half today",
                        "estimated_minutes": 30,
                        "preferred_daypart": "evening",
                    },
                    {
                        "date": today + timedelta(days=1),
                        "title": f"{title} - half tomorrow",
                        "estimated_minutes": 30,
                        "preferred_daypart": tomorrow_daypart,
                    },
                ]
            },
            source_text=source,
            confidence="high",
            requires_confirmation=True,
        )
    if "german is yet to be done" in normalized and "coming hours" in normalized:
        return PlannerCommand(
            "preview_day_replan",
            {"month": month, "target_date": today, "current_datetime": datetime.now()},
            source_text=source,
        )
    if normalized in {"no work on weekends", "no office on saturday sunday"}:
        return PlannerCommand("set_rule", {"path": "work.no_work_days", "value": ["Saturday", "Sunday"]}, source_text=source)
    move_preference = re.match(r"move\s+(.+?)\s+to\s+(morning|afternoon|evening|night)$", normalized)
    if move_preference:
        return PlannerCommand(
            "update_preference",
            {
                "name": f"preferred_dayparts.{move_preference.group(1).replace(' ', '_')}",
                "value": move_preference.group(2),
            },
            source_text=source,
            confidence="medium",
            requires_confirmation=True,
        )
    complete = re.match(r"(?:complete|mark)\s+(.+?)(?:\s+done)?$", normalized)
    if complete:
        return PlannerCommand("complete_task", {"month": month, "task_name": complete.group(1)}, source_text=source)
    move = re.match(r"move\s+(.+?)\s+to\s+week\s+(\d+)$", normalized)
    if move:
        return PlannerCommand("move_task", {"month": month, "task_name": move.group(1), "destination_week": int(move.group(2))}, source_text=source)
    gym = re.search(r"(\d+)\s+gym sessions?\s+between\s+(\d{1,2})\s+and\s+(\d{1,2})", normalized)
    if gym:
        count, start_hour, end_hour = map(int, gym.groups())
        if start_hour < 12:
            start_hour += 12
        if end_hour < 12:
            end_hour += 12
        return PlannerCommand(
            "preview_day_replan",
            {
                "month": month,
                "target_date": today,
                "current_datetime": datetime.now(),
                "bounded_sessions": [{"title": "Gym", "session_count": count, "start_hour": start_hour, "end_hour": end_hour}],
            },
            source_text=source,
        )
    tomorrow_task = re.match(r"(.+?)\s+tomorrow$", normalized)
    if tomorrow_task:
        target = today + timedelta(days=1)
        return PlannerCommand(
            "add_dated_task",
            {
                "date": target,
                "title": tomorrow_task.group(1),
                "estimated_minutes": 30 if normalized.startswith("call ") else 90,
                "preferred_daypart": "morning" if normalized.startswith("call ") else None,
            },
            source_text=source,
            confidence="medium",
            requires_confirmation=True,
        )
    return PlannerCommand("preview_day_replan", {}, source_text=source, confidence="low", requires_confirmation=True)


def route_command(command: PlannerCommand, router: PlannerCommandRouter) -> PlannerCommandResult:
    return router.route_command(command)


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _serialize(value: Any) -> Any:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value
