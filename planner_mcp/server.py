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
