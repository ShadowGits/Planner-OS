"""STDIO MCP server for Planner OS."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from planner_mcp.tools import PlannerMCPTools


planner_tools = PlannerMCPTools()
mcp = FastMCP("Planner OS")


@mcp.tool()
def validate() -> dict:
    """Check workbook readability, rules, and planner structure."""

    return planner_tools.validate()


@mcp.tool()
def list_rules() -> dict:
    """List permanent planner rules."""

    return planner_tools.list_rules()


@mcp.tool()
def update_rule(path: str, value: object) -> dict:
    """Update an existing permanent rule path."""

    return planner_tools.update_rule(path=path, value=value)


@mcp.tool()
def set_work_days(days: list[str]) -> dict:
    """Set active work days."""

    return planner_tools.set_work_days(days=days)


@mcp.tool()
def set_no_work_days(days: list[str]) -> dict:
    """Set no-work days."""

    return planner_tools.set_no_work_days(days=days)


@mcp.tool()
def list_execution_targets() -> dict:
    """List supported targets and the one active target."""
    return planner_tools.list_execution_targets()


@mcp.tool()
def get_active_execution_target() -> dict:
    """Return the persistent active downstream target."""
    return planner_tools.get_active_execution_target()


@mcp.tool()
def set_active_execution_target(target: str) -> dict:
    """Set future publishing target without moving existing items."""
    return planner_tools.set_active_execution_target(target)


@mcp.tool()
def preview_execution_target_switch(target: str) -> dict:
    """Preview changing future publishing to one target."""
    return planner_tools.preview_execution_target_switch(target)


@mcp.tool()
def apply_execution_target_switch(preview_id: str) -> dict:
    """Apply an approved target-switch preview."""
    return planner_tools.apply_execution_target_switch(preview_id)


@mcp.tool()
def preview_move_external_items(source_target: str, destination_target: str, start_date: str, end_date: str) -> dict:
    """Preview explicit cross-target migration of external items."""
    return planner_tools.preview_move_external_items(source_target, destination_target, start_date, end_date)


@mcp.tool()
def apply_move_external_items(preview_id: str) -> dict:
    """Apply an approved explicit cross-target migration."""
    return planner_tools.apply_move_external_items(preview_id)


@mcp.tool()
def publish_today() -> dict:
    """Publish today using only the active execution target."""
    return planner_tools.publish_today()


@mcp.tool()
def publish_date(date: str) -> dict:
    """Publish one date using only the active execution target."""
    return planner_tools.publish_date(date)


@mcp.tool()
def publish_range(start_date: str, end_date: str) -> dict:
    """Publish a range using only the active execution target."""
    return planner_tools.publish_range(start_date, end_date)


@mcp.tool()
def publish_current_week() -> dict:
    """Publish current week using only the active execution target."""
    return planner_tools.publish_current_week()


@mcp.tool()
def apple_calendar_status() -> dict:
    """Report native Apple Calendar permission and capabilities."""
    return planner_tools.apple_calendar_status()


@mcp.tool()
def apple_calendar_calendars() -> dict:
    """List writable local Apple calendars."""
    return planner_tools.apple_calendar_calendars()


@mcp.tool()
def create_apple_calendar(title: str = "Planner OS") -> dict:
    """Create and select a dedicated local Apple calendar."""
    return planner_tools.create_apple_calendar(title)


@mcp.tool()
def set_apple_calendar(calendar_id: str) -> dict:
    """Persist the selected Apple Calendar identifier."""
    return planner_tools.set_apple_calendar(calendar_id)


@mcp.tool()
def apple_calendar_list_range(start_date: str, end_date: str) -> dict:
    """List Planner OS-owned Apple events in a range."""
    return planner_tools.apple_calendar_list_range(start_date, end_date)


@mcp.tool()
def apple_calendar_reconcile_range(start_date: str, end_date: str) -> dict:
    """Reconcile Apple Calendar events in a range."""
    return planner_tools.apple_calendar_reconcile_range(start_date, end_date)


@mcp.tool()
def apple_calendar_delete_event(external_id: str, delete_scope: str = "single") -> dict:
    """Delete one explicitly identified Planner OS Apple event."""
    return planner_tools.apple_calendar_delete_event(external_id, delete_scope)


@mcp.tool()
def apple_calendar_update_event(external_id: str, block: dict) -> dict:
    """Update one explicitly identified Planner OS Apple event."""
    return planner_tools.apple_calendar_update_event(external_id, block)


@mcp.tool()
def preview_apple_calendar_delete_range(start_date: str, end_date: str) -> dict:
    """Preview exact Planner OS Apple events to delete."""
    return planner_tools.preview_apple_calendar_delete_range(start_date, end_date)


@mcp.tool()
def apply_apple_calendar_delete_range(preview_id: str) -> dict:
    """Apply an approved Apple Calendar range deletion."""
    return planner_tools.apply_apple_calendar_delete_range(preview_id)


@mcp.tool()
def calendar_list_range(start_date: str, end_date: str) -> dict:
    """List Planner OS-owned Google events in a range."""
    return planner_tools.calendar_list_range(start_date, end_date)


@mcp.tool()
def calendar_lookup_event(planner_block_id: str, start_date: str, end_date: str) -> dict:
    """Find Google events by stable planner block ID."""
    return planner_tools.calendar_lookup_event(planner_block_id, start_date, end_date)


@mcp.tool()
def calendar_update_event(external_id: str, block: dict) -> dict:
    """Update one explicitly identified Planner OS Google event."""
    return planner_tools.calendar_update_event(external_id, block)


@mcp.tool()
def calendar_delete_event(external_id: str) -> dict:
    """Delete one explicitly identified Planner OS Google event."""
    return planner_tools.calendar_delete_event(external_id)


@mcp.tool()
def calendar_delete_series(external_id: str) -> dict:
    """Delete a Planner OS Google recurring series."""
    return planner_tools.calendar_delete_event(external_id, "series")


@mcp.tool()
def calendar_delete_future_series(external_id: str) -> dict:
    """Delete this and future Planner OS Google recurring events."""
    return planner_tools.calendar_delete_event(external_id, "future")


@mcp.tool()
def preview_calendar_delete_range(start_date: str, end_date: str) -> dict:
    """Preview exact Planner OS Google events to delete."""
    return planner_tools.preview_calendar_delete_range(start_date, end_date)


@mcp.tool()
def apply_calendar_delete_range(preview_id: str) -> dict:
    """Apply an approved Google event range deletion."""
    return planner_tools.apply_calendar_delete_range(preview_id)


@mcp.tool()
def calendar_reconcile_range(start_date: str, end_date: str) -> dict:
    """Reconcile planner blocks with Google Calendar."""
    return planner_tools.calendar_reconcile_range(start_date, end_date)


@mcp.tool()
def preview_calendar_cleanup_orphans(start_date: str, end_date: str) -> dict:
    """Preview orphaned Planner OS Google events for cleanup."""
    return planner_tools.preview_calendar_cleanup_orphans(start_date, end_date)


@mcp.tool()
def apply_calendar_cleanup_orphans(preview_id: str) -> dict:
    """Apply an approved orphan cleanup."""
    return planner_tools.apply_calendar_cleanup_orphans(preview_id)


@mcp.tool()
def calendar_repair_mapping(external_id: str) -> dict:
    """Repair a local mapping from Planner OS Google event metadata."""
    return planner_tools.calendar_repair_mapping(external_id)


@mcp.tool()
def plan_today() -> dict:
    """Generate today's schedule without writing to Excel."""

    return planner_tools.plan_today()


@mcp.tool()
def plan_today_from_now(current_datetime: str | None = None) -> dict:
    """Plan today using only remaining time for flexible blocks."""

    return planner_tools.plan_today_from_now(current_datetime)


@mcp.tool()
def replan_today_from_now(current_datetime: str | None = None) -> dict:
    """Replan today from the current time without writing."""

    return planner_tools.replan_today_from_now(current_datetime)


@mcp.tool()
def preview_month_plan(request: dict) -> dict:
    """Preview monthly milestones and dated daily proposals without writing."""

    return planner_tools.preview_month_plan(request)


@mcp.tool()
def apply_month_plan(
    preview_id: str | None = None,
    preview: dict | None = None,
) -> dict:
    """Apply an explicitly approved monthly planning preview."""

    return planner_tools.apply_month_plan(preview_id, preview)


@mcp.tool()
def preview_week_plan(request: dict) -> dict:
    """Preview an explicit workbook week or date range without writing."""

    return planner_tools.preview_week_plan(request)


@mcp.tool()
def apply_week_plan(
    preview_id: str | None = None,
    preview: dict | None = None,
) -> dict:
    """Apply an explicitly approved weekly planning preview."""

    return planner_tools.apply_week_plan(preview_id, preview)


@mcp.tool()
def preview_day_replan(request: dict) -> dict:
    """Preview today's remaining-time replan without writing."""

    return planner_tools.preview_day_replan(request)


@mcp.tool()
def apply_day_replan(
    preview_id: str | None = None,
    preview: dict | None = None,
) -> dict:
    """Apply an explicitly approved day replan."""

    return planner_tools.apply_day_replan(preview_id, preview)


@mcp.tool()
def status() -> dict:
    """Return progress status and active slippage alerts."""

    return planner_tools.status()


@mcp.tool()
def complete_task(task_name: str, month: str | None = None) -> dict:
    """Mark a task complete."""

    return planner_tools.complete_task(task_name=task_name, month=month)


@mcp.tool()
def add_task(
    task: str,
    week: int,
    month: str | None = None,
    category: str | None = None,
    status: str = "Not Started",
    notes: str | None = None,
) -> dict:
    """Add a weekly task."""

    return planner_tools.add_task(
        task=task,
        week=week,
        month=month,
        category=category,
        status=status,
        notes=notes,
    )


@mcp.tool()
def update_task(
    task_name: str,
    month: str | None = None,
    new_name: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    target_week: str | None = None,
    status: str | None = None,
    notes: str | None = None,
) -> dict:
    """Update an existing task."""

    return planner_tools.update_task(
        task_name=task_name,
        month=month,
        new_name=new_name,
        category=category,
        priority=priority,
        target_week=target_week,
        status=status,
        notes=notes,
    )


@mcp.tool()
def move_task(
    task_name: str,
    destination_week: int,
    month: str | None = None,
    status: str | None = None,
) -> dict:
    """Move a weekly task to another week."""

    return planner_tools.move_task(
        task_name=task_name,
        destination_week=destination_week,
        month=month,
        status=status,
    )


@mcp.tool()
def delete_task(task_name: str, month: str | None = None) -> dict:
    """Delete a task."""

    return planner_tools.delete_task(task_name=task_name, month=month)


@mcp.tool()
def add_dated_task(
    date: str,
    title: str,
    estimated_minutes: int,
    preferred_daypart: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    hard_time: bool | None = None,
    category: str | None = None,
    notes: str | None = None,
) -> dict:
    """Add a task to one exact workbook date column."""

    return planner_tools.add_dated_task(
        date, title, estimated_minutes, preferred_daypart,
        start_time, end_time, hard_time, category, notes,
    )


@mcp.tool()
def add_dated_tasks(tasks: list[dict]) -> dict:
    """Add multiple tasks to exact workbook date columns."""
    
    return planner_tools.add_dated_tasks(tasks)


@mcp.tool()
def update_dated_task(task_id: str, changes: dict) -> dict:
    """Update a workbook-backed exact-date task."""

    return planner_tools.update_dated_task(task_id, changes)


@mcp.tool()
def delete_dated_task(task_id: str) -> dict:
    """Delete a workbook-backed exact-date task."""

    return planner_tools.delete_dated_task(task_id)


@mcp.tool()
def list_dated_tasks(date: str) -> dict:
    """List workbook tasks assigned to one exact date."""

    return planner_tools.list_dated_tasks(date)


@mcp.tool()
def import_plan(input_path: str) -> dict:
    """Import a structured JSON planner file."""

    return planner_tools.import_plan(input_path=input_path)


@mcp.tool()
def calendar_sync_today() -> dict:
    """Generate today's plan and sync it to Google Calendar."""

    return planner_tools.calendar_sync_today()


@mcp.tool()
def calendar_sync_week() -> dict:
    """Backward-compatible alias that explicitly syncs current week."""

    return planner_tools.calendar_sync_week()


@mcp.tool()
def calendar_sync_current_week() -> dict:
    """Sync the Monday-Sunday range containing today."""

    return planner_tools.calendar_sync_current_week()


@mcp.tool()
def calendar_sync_next_week() -> dict:
    """Sync the Monday-Sunday range after the current week."""

    return planner_tools.calendar_sync_next_week()


@mcp.tool()
def calendar_sync_week_number(month: str, week_number: int) -> dict:
    """Sync one explicit planner workbook week section."""

    return planner_tools.calendar_sync_week_number(month, week_number)


@mcp.tool()
def calendar_sync_range(start_date: str, end_date: str) -> dict:
    """Sync one explicit inclusive date range."""

    return planner_tools.calendar_sync_range(start_date, end_date)


@mcp.tool()
def calendar_sync_month(month: str) -> dict:
    """Sync all scheduled blocks in one explicit planner month."""

    return planner_tools.calendar_sync_month(month)


@mcp.tool()
def calendar_sync_date(date: str) -> dict:
    """Sync exactly one date, including workbook-backed dated tasks."""

    return planner_tools.calendar_sync_date(date)


@mcp.tool()
def daily_checkin(date: str | None = None) -> dict:
    """Generate a read-only daily progress check-in."""

    return planner_tools.daily_checkin(date)


@mcp.tool()
def daily_review(date: str | None = None) -> dict:
    """Generate a read-only daily review."""
    return planner_tools.daily_review(date)


@mcp.tool()
def weekly_review(date: str | None = None) -> dict:
    """Generate a read-only weekly review."""
    return planner_tools.weekly_review(date)


@mcp.tool()
def monthly_review(month: str) -> dict:
    """Generate a read-only monthly review."""
    return planner_tools.monthly_review(month)


@mcp.tool()
def planner_doctor() -> dict:
    """Run read-only local Planner OS diagnostics."""
    return planner_tools.planner_doctor()


@mcp.tool()
def list_preferences() -> dict:
    """List persistent planner preferences and editable aliases."""
    return planner_tools.list_preferences()


@mcp.tool()
def get_preference(name: str) -> dict:
    """Read one planner preference."""
    return planner_tools.get_preference(name)


@mcp.tool()
def update_preference(name: str, value) -> dict:
    """Update one planner preference through a validated local store."""
    return planner_tools.update_preference(name, value)


@mcp.tool()
def reset_preference(name: str) -> dict:
    """Reset one preference when a safe built-in reset exists."""
    return planner_tools.reset_preference(name)


@mcp.tool()
def explain_active_constraints() -> dict:
    """Explain the constraints currently affecting planning and publishing."""
    return planner_tools.explain_active_constraints()


@mcp.tool()
def preview_planner_repair() -> dict:
    """Preview local Planner OS consistency repairs."""
    return planner_tools.preview_planner_repair()


@mcp.tool()
def apply_planner_repair(preview_id: str) -> dict:
    """Apply an approved local repair preview."""
    return planner_tools.apply_planner_repair(preview_id)


@mcp.tool()
def preview_undo(decision_id: str | None = None) -> dict:
    """Preview restoring a workbook backup referenced by Decision Log."""
    return planner_tools.preview_undo(decision_id)


@mcp.tool()
def apply_undo(preview_id: str) -> dict:
    """Apply an approved workbook undo preview."""
    return planner_tools.apply_undo(preview_id)


@mcp.tool()
def undo_last_change() -> dict:
    """Undo the most recent workbook change with a Decision Log backup."""
    return planner_tools.undo_last_change()


@mcp.tool()
def preview_recurrence(request: dict) -> dict:
    """Preview generated occurrences for a recurrence definition."""
    return planner_tools.preview_recurrence(request)


@mcp.tool()
def apply_recurrence(preview_id: str) -> dict:
    """Apply an approved recurrence preview as dated workbook tasks."""
    return planner_tools.apply_recurrence(preview_id)


@mcp.tool()
def list_recurrences() -> dict:
    """List workbook-backed recurrence definitions."""
    return planner_tools.list_recurrences()


@mcp.tool()
def pause_recurrence(recurrence_id: str) -> dict:
    """Pause a workbook-backed recurrence definition."""
    return planner_tools.pause_recurrence(recurrence_id)


@mcp.tool()
def resume_recurrence(recurrence_id: str) -> dict:
    """Resume a workbook-backed recurrence definition."""
    return planner_tools.resume_recurrence(recurrence_id)


@mcp.tool()
def preview_goal_plan(request: dict) -> dict:
    """Preview deterministic breakdown of a structured goal."""
    return planner_tools.preview_goal_plan(request)


@mcp.tool()
def apply_goal_plan(preview_id: str) -> dict:
    """Apply an approved goal plan preview to the workbook."""
    return planner_tools.apply_goal_plan(preview_id)


@mcp.tool()
def parse_common_intent(text: str) -> dict:
    """Parse a small supported set of common planner phrases."""

    return planner_tools.parse_common_intent(text)


@mcp.tool()
def route_planner_command(command: dict) -> dict:
    """Route one validated structured planner command safely."""

    return planner_tools.route_planner_command(command)


def main() -> None:
    """Run the MCP server over STDIO."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
