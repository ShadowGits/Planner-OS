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
def plan_today() -> dict:
    """Generate today's schedule without writing to Excel."""

    return planner_tools.plan_today()


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
def import_plan(input_path: str) -> dict:
    """Import a structured JSON planner file."""

    return planner_tools.import_plan(input_path=input_path)


def main() -> None:
    """Run the MCP server over STDIO."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
