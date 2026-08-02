"""Register the v2 Postgres planner tools on the cloud MCP server.

These handlers talk straight to planner_core over PostgREST — no workbook
download, no manifest parsing, no lock cycle. They resolve the acting user
from the MCP access token exactly like the legacy workbook handlers do.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


def _core_for_current_user():
    from mcp.server.auth.middleware.auth_context import get_access_token

    from adapters.supabase.client import SupabaseConfig, SupabaseRestClient
    from adapters.supabase.workspaces import SupabaseWorkspaceRepository
    from planner_core.repository import PlannerCoreRepository
    from planner_core.services import GoalService, MetricsService, ProjectService, ReminderService, TaskService

    token = get_access_token()
    if not token or not token.subject:
        raise ValueError(
            "Unauthorized: missing or invalid credentials. "
            "Re-authorize the Planner OS MCP integration."
        )
    user_id = UUID(token.subject)
    client = SupabaseRestClient(SupabaseConfig.from_env())
    workspace = SupabaseWorkspaceRepository(client).get_active(user_id)
    if workspace is None:
        raise ValueError(
            "No active Planner OS workspace found. "
            "Create and activate a workspace in the Planner OS web app first."
        )
    repository = PlannerCoreRepository(client, user_id, workspace.id)
    tasks = TaskService(repository, workspace.timezone)
    projects = ProjectService(repository)
    metrics = MetricsService(repository, workspace.timezone)
    reminders = ReminderService(repository, metrics, tasks, workspace.timezone)
    goals = GoalService(repository)
    return tasks, projects, metrics, reminders, goals


def register_core_tools(server: Any) -> None:
    @server.tool(name="core_create_project")
    async def core_create_project(
        name: str,
        track: str | None = None,
        description: str | None = None,
        target_date: str | None = None,
    ) -> dict:
        """Create a project (a Germany-move track, a course, any multi-week goal). Optional track label and YYYY-MM-DD target date."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.create_project(name, track=track, description=description, target_date=target_date)

    @server.tool(name="core_update_project")
    async def core_update_project(project_id: str, updates: dict) -> dict:
        """Update project fields: name, track, description, status (active/paused/done/archived), target_date."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.update_project(project_id, updates)

    @server.tool(name="core_add_milestone")
    async def core_add_milestone(
        project_id: str,
        name: str,
        target_date: str | None = None,
        sort_order: int = 0,
        notes: str | None = None,
    ) -> dict:
        """Add a milestone to a project with an optional YYYY-MM-DD target date."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.add_milestone(
            project_id, name, target_date=target_date, sort_order=sort_order, notes=notes
        )

    @server.tool(name="core_update_milestone")
    async def core_update_milestone(milestone_id: str, updates: dict) -> dict:
        """Update milestone fields: name, status (not_started/in_progress/blocked/done), target_date, sort_order, notes."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.update_milestone(milestone_id, updates)

    @server.tool(name="core_list_projects")
    async def core_list_projects() -> dict:
        """List all projects with their milestones and open/done task counts."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.project_tree()

    @server.tool(name="core_create_task")
    async def core_create_task(
        title: str,
        project_id: str | None = None,
        milestone_id: str | None = None,
        due_date: str | None = None,
        scheduled_date: str | None = None,
        start_time: str | None = None,
        priority: str = "medium",
        estimated_minutes: int | None = None,
        recurrence_key: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Create a task, optionally under a project/milestone, with due/scheduled YYYY-MM-DD dates, an HH:MM start_time for the day timeline, and a recurrence_key for habit streaks."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.create_task(
            title,
            project_id=project_id,
            milestone_id=milestone_id,
            due_date=due_date,
            scheduled_date=scheduled_date,
            start_time=start_time,
            priority=priority,
            estimated_minutes=estimated_minutes,
            recurrence_key=recurrence_key,
            notes=notes,
        )

    @server.tool(name="core_create_tasks_batch")
    async def core_create_tasks_batch(items: list[dict]) -> dict:
        """Create many tasks in one call. Each item takes the same fields as core_create_task: title (required), project_id, milestone_id, due_date, scheduled_date, start_time (HH:MM), priority, estimated_minutes, recurrence_key, notes. All items are validated before any task is created."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.create_tasks_batch(items)

    @server.tool(name="core_update_task")
    async def core_update_task(task_id: str, updates: dict) -> dict:
        """Update task fields: title, status (todo/in_progress/blocked/done/skipped), priority, due_date, scheduled_date, start_time (HH:MM), estimated_minutes, project_id, milestone_id, notes."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.update_task(task_id, updates)

    @server.tool(name="core_complete_task")
    async def core_complete_task(task_id: str, note: str | None = None) -> dict:
        """Mark a task done and record the completion for streaks and metrics."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.complete_task(task_id, source="mcp", note=note)

    @server.tool(name="core_delete_task")
    async def core_delete_task(task_id: str) -> dict:
        """Delete one task permanently."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.delete_task(task_id)

    @server.tool(name="core_delete_tasks_batch")
    async def core_delete_tasks_batch(task_ids: list[str]) -> dict:
        """Batch delete multiple tasks permanently."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.delete_tasks_batch(task_ids)

    @server.tool(name="core_list_tasks")
    async def core_list_tasks(status: str | None = None, project_id: str | None = None) -> dict:
        """List tasks, optionally filtered by status or project, sorted by due date."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.list_tasks(status=status, project_id=project_id)

    @server.tool(name="core_today")
    async def core_today() -> dict:
        """Today's view: scheduled tasks, due today, overdue, and completions so far."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.today()

    @server.tool(name="core_add_monthly_goal")
    async def core_add_monthly_goal(project_id: str, month: str, description: str) -> dict:
        """Add or update a monthly goal (upsert). month should be YYYY-MM-DD (typically the 1st of the month)."""
        _, _, _, _, goals = _core_for_current_user()
        return goals.add_monthly_goal(project_id, month, description)

    @server.tool(name="core_update_monthly_goal")
    async def core_update_monthly_goal(goal_id: str, description: str) -> dict:
        """Update the description of an existing monthly goal."""
        _, _, _, _, goals = _core_for_current_user()
        return goals.update_monthly_goal(goal_id, description)

    @server.tool(name="core_add_weekly_goal")
    async def core_add_weekly_goal(project_id: str, week_start: str, description: str) -> dict:
        """Add or update a weekly goal for a project. week_start should be YYYY-MM-DD (a Monday)."""
        _, _, _, _, goals = _core_for_current_user()
        return goals.add_weekly_goal(project_id, week_start, description)

    @server.tool(name="core_metrics")
    async def core_metrics() -> dict:
        """Full metrics snapshot: per-project completion, upcoming deadlines, streaks, totals."""
        _, _, metrics, _, _ = _core_for_current_user()
        return {"success": True, "message": "Planner metrics", "data": metrics.snapshot()}
