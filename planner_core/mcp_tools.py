"""Register the v2 Postgres planner tools on the cloud MCP server.

These handlers talk straight to planner_core over PostgREST — no workbook
download, no manifest parsing, no lock cycle. They resolve the acting user
from the MCP access token exactly like the legacy workbook handlers do.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID
from planner_platform.google_oauth import CredentialCipher, SupabaseGoogleCalendarClientFactory
from adapters.supabase import SupabaseCalendarConnectionRepository
from adapters.supabase import SupabaseExternalLinkRepository


def _repository_for_current_user():
    """Resolve the caller's workspace repository and timezone from the MCP token."""
    from mcp.server.auth.middleware.auth_context import get_access_token

    from adapters.supabase.client import SupabaseConfig, SupabaseRestClient
    from adapters.supabase.workspaces import SupabaseWorkspaceRepository
    from planner_core.repository import PlannerCoreRepository

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
    return PlannerCoreRepository(client, user_id, workspace.id), workspace.timezone


class _CoreBundle:
    """Every v2 service bound to the caller's workspace."""

    def __init__(self, repository: Any, timezone: str) -> None:
        from planner_core.services import (
            FinanceService, GoalService, MetricsService,
            ProjectService, ReminderService, TaskService,
        )

        self.repository = repository
        self.timezone = timezone
        self.tasks = TaskService(repository, timezone)
        self.projects = ProjectService(repository)
        self.metrics = MetricsService(repository, timezone)
        self.reminders = ReminderService(repository, self.metrics, self.tasks, timezone)
        self.goals = GoalService(repository)
        self.finance = FinanceService(repository, timezone)


def _core() -> _CoreBundle:
    return _CoreBundle(*_repository_for_current_user())


def _core_for_current_user():
    """Tuple shape the older tools unpack. New tools should use _core()."""
    core = _core()
    return core.tasks, core.projects, core.metrics, core.reminders, core.goals


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
        parent_task_id: str | None = None,
        depends_on: str | None = None,
    ) -> dict:
        """Create a task, optionally under a project/milestone, with due/scheduled YYYY-MM-DD dates, an HH:MM start_time for the day timeline, and a recurrence_key for habit streaks. To split a task across several sittings, pass the original task's ID as parent_task_id; each slot keeps its own day and time, and finishing them all finishes the original."""
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
            parent_task_id=parent_task_id,
            depends_on=depends_on,
        )

    @server.tool(name="core_create_tasks_batch")
    async def core_create_tasks_batch(items: list[dict]) -> dict:
        """Create many tasks in one call. Each item takes the same fields as core_create_task: title (required), project_id, milestone_id, due_date, scheduled_date, start_time (HH:MM), priority, estimated_minutes, recurrence_key, notes, parent_task_id, depends_on. All items are validated before any task is created."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.create_tasks_batch(items)

    @server.tool(name="core_update_task")
    async def core_update_task(task_id: str, updates: dict) -> dict:
        """Update task fields: title, status (todo/in_progress/blocked/done/skipped), priority, due_date, scheduled_date, start_time (HH:MM), estimated_minutes, project_id, milestone_id, notes, parent_task_id, depends_on."""
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

    @server.tool(name="core_sync_calendar")
    async def core_sync_calendar(days: int = 7) -> dict:
        """Mirror scheduled tasks to Google Calendar. Returns the number of events created, updated, and deleted."""
        tasks, _, _, _, _ = _core_for_current_user()
        
        # We need the Google Client. We instantiate it exactly like CloudRuntime does.
        from mcp.server.auth.middleware.auth_context import get_access_token
        from adapters.supabase.client import SupabaseConfig, SupabaseRestClient
        token = get_access_token()
        client = SupabaseRestClient(SupabaseConfig.from_env())
        
        cipher = CredentialCipher.from_env()
        factory = SupabaseGoogleCalendarClientFactory(
            SupabaseCalendarConnectionRepository(client),
            cipher,
            SupabaseExternalLinkRepository(client)
        )
        
        from planner_platform.context import PlannerContext
        from pathlib import Path
        context = PlannerContext(
            user_id=tasks.repository.user_id,
            workspace_id=tasks.repository.workspace_id,
            operation_id=tasks.repository.user_id, # Mock operation ID
            workbook_path=Path("calendar-sync.xlsx"),
            timezone=tasks.timezone,
            execution_target="google_calendar",
            source_revision=0,
        )
        
        try:
            google_client = factory(context)
            return tasks.sync_calendar(google_client, days)
        except Exception as e:
            return {"success": False, "message": str(e), "data": {}, "errors": [str(e)]}

    @server.tool(name="core_metrics")
    async def core_metrics() -> dict:
        """Full metrics snapshot: per-project completion, upcoming deadlines, streaks, totals."""
        _, _, metrics, _, _ = _core_for_current_user()
        return {"success": True, "message": "Planner metrics", "data": metrics.snapshot()}

    @server.tool(name="core_update_task_date_time_batch")
    def core_update_task_date_time_batch(updates: list[dict]) -> str:
        """Batch update scheduled dates and times for multiple tasks.
        Updates should be a list of dicts, each with 'id' and optionally 'scheduled_date', 'due_date', 'start_time'."""
        result = _core().tasks.update_task_date_time_batch(updates)
        return json.dumps(result)

    @server.tool(name="core_add_project_widget")
    def core_add_project_widget(project_id: str, widget_type: str, title: str | None = None, file_id: str | None = None, config: dict | None = None) -> str:
        """Add a widget (qna, csv, text) to a project dashboard."""
        result = _core().projects.add_project_widget(project_id, widget_type, title, file_id, config)
        return json.dumps(result)

    @server.tool(name="core_update_project_widget")
    def core_update_project_widget(widget_id: str, updates: dict) -> str:
        """Update a project widget configuration."""
        result = _core().projects.update_project_widget(widget_id, updates)
        return json.dumps(result)

    @server.tool(name="core_delete_project_widget")
    def core_delete_project_widget(widget_id: str) -> str:
        """Delete a project widget."""
        result = _core().projects.delete_project_widget(widget_id)
        return json.dumps(result)

    @server.tool(name="core_list_project_widgets")
    def core_list_project_widgets(project_id: str) -> str:
        """List all widgets on a project dashboard."""
        result = _core().projects.list_project_widgets(project_id)
        return json.dumps(result)

    @server.tool(name="core_add_project_qna")
    def core_add_project_qna(project_id: str, question: str, answer: str | None = None, status: str = "open", notes: str | None = None) -> str:
        """Add a QnA entry to a project."""
        result = _core().projects.add_project_qna(project_id, question, answer, status, notes)
        return json.dumps(result)

    @server.tool(name="core_update_project_qna")
    def core_update_project_qna(qna_id: str, updates: dict) -> str:
        """Update a QnA entry."""
        result = _core().projects.update_project_qna(qna_id, updates)
        return json.dumps(result)

    @server.tool(name="core_delete_project_qna")
    def core_delete_project_qna(qna_id: str) -> str:
        """Delete a QnA entry."""
        result = _core().projects.delete_project_qna(qna_id)
        return json.dumps(result)

    @server.tool(name="core_delete_monthly_goal")
    def core_delete_monthly_goal(goal_id: str) -> str:
        """Delete a monthly goal."""
        result = _core().goals.delete_monthly_goal(goal_id)
        return json.dumps(result)

    # ---------- personal finance ----------

    @server.tool(name="core_log_expense")
    def core_log_expense(
        description: str,
        amount: float,
        category: str | None = None,
        currency: str = "INR",
        date: str | None = None,
        merchant: str | None = None,
        payment_method: str | None = None,
        goal_id: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Log money spent. Amount is a positive number; currency is INR (default, day-to-day spending) or EUR (Germany costs). Date defaults to today, YYYY-MM-DD otherwise. Pick category from: Food, Groceries, Transport, Rent, Utilities, Health, Education, Shopping, Entertainment, Subscriptions, Travel, Savings, Fees, Family, Other — reuse these exact names so monthly summaries stay consistent. Pass goal_id when the spend is a transfer into a savings goal (use core_finance_goals to find the id)."""
        result = _core().finance.log_transaction(
            description, amount, on_date=date, category=category, currency=currency,
            kind="expense", merchant=merchant, payment_method=payment_method,
            goal_id=goal_id, notes=notes,
        )
        return json.dumps(result)

    @server.tool(name="core_log_income")
    def core_log_income(
        description: str,
        amount: float,
        category: str | None = None,
        currency: str = "INR",
        date: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Log money received. Pick category from: Salary, Freelance, Refund, Gift, Interest, Other."""
        result = _core().finance.log_transaction(
            description, amount, on_date=date, category=category,
            currency=currency, kind="income", notes=notes,
        )
        return json.dumps(result)

    @server.tool(name="core_update_transaction")
    def core_update_transaction(transaction_id: str, updates: dict) -> str:
        """Correct a logged transaction. Updatable fields: date, description, amount, currency, type, category, merchant, payment_method, goal_id, notes."""
        result = _core().finance.update_transaction(transaction_id, updates)
        return json.dumps(result)

    @server.tool(name="core_delete_transaction")
    def core_delete_transaction(transaction_id: str) -> str:
        """Delete a logged transaction."""
        result = _core().finance.delete_transaction(transaction_id)
        return json.dumps(result)

    @server.tool(name="core_list_transactions")
    def core_list_transactions(
        start: str | None = None,
        end: str | None = None,
        category: str | None = None,
        type: str | None = None,
        limit: int = 200,
    ) -> str:
        """List transactions newest first. Window with start/end as YYYY-MM-DD, and filter by category or by type (expense/income)."""
        result = _core().finance.list_transactions(
            start=start, end=end, category=category, kind=type, limit=limit
        )
        return json.dumps(result)

    @server.tool(name="core_finance_summary")
    def core_finance_summary(month: str | None = None) -> str:
        """Spending summary for a month (YYYY-MM, defaults to the current one): totals and category breakdown per currency, with last month alongside for comparison. Currencies are never added together — there is no exchange rate here."""
        result = _core().finance.monthly_summary(month)
        return json.dumps(result)

    @server.tool(name="core_finance_goals")
    def core_finance_goals() -> str:
        """Savings goals with real progress: the hand-set baseline plus every transaction logged against each goal. Contributions made in a different currency to the goal are reported separately rather than converted."""
        result = _core().finance.goal_progress()
        return json.dumps(result)

    @server.tool(name="core_add_recurring_charge")
    def core_add_recurring_charge(
        description: str,
        amount: float,
        cadence: str = "monthly",
        day_of_month: int | None = None,
        day_of_week: int | None = None,
        category: str | None = None,
        currency: str = "INR",
        type: str = "expense",
        merchant: str | None = None,
        payment_method: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Set up a repeating charge — rent, a subscription, an EMI, or recurring income like salary. cadence is weekly, monthly, or yearly. For monthly give day_of_month (1-31; a 31 posts on the last day of shorter months). For weekly give day_of_week (0=Monday to 6=Sunday). Yearly repeats on the anniversary of start_date. These post into the passbook automatically as they fall due."""
        result = _core().finance.add_recurring(
            description, amount, cadence=cadence, day_of_month=day_of_month,
            day_of_week=day_of_week, category=category, currency=currency, kind=type,
            merchant=merchant, payment_method=payment_method,
            start_date=start_date, end_date=end_date, notes=notes,
        )
        return json.dumps(result)

    @server.tool(name="core_list_recurring_charges")
    def core_list_recurring_charges(include_inactive: bool = False) -> str:
        """List repeating charges (rent, subscriptions, EMIs, salary)."""
        result = _core().finance.list_recurring(include_inactive=include_inactive)
        return json.dumps(result)

    @server.tool(name="core_update_recurring_charge")
    def core_update_recurring_charge(recurring_id: str, updates: dict) -> str:
        """Change a repeating charge. Set active to false to stop it without losing its history. Updatable: description, amount, currency, type, cadence, day_of_month, day_of_week, category, merchant, payment_method, start_date, end_date, active, notes."""
        result = _core().finance.update_recurring(recurring_id, updates)
        return json.dumps(result)

    @server.tool(name="core_delete_recurring_charge")
    def core_delete_recurring_charge(recurring_id: str) -> str:
        """Delete a repeating charge. Transactions it already posted are kept."""
        result = _core().finance.delete_recurring(recurring_id)
        return json.dumps(result)
