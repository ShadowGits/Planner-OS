"""Register the v2 Postgres planner tools on the cloud MCP server.

These handlers talk straight to planner_core over PostgREST — no workbook
download, no manifest parsing, no lock cycle. They resolve the acting user
from the MCP access token exactly like the legacy workbook handlers do.
"""

from __future__ import annotations

import functools
import inspect
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
            FinanceService, GoalService, HabitService, MetricsService,
            ProjectService, ReminderService, TaskService,
        )

        self.repository = repository
        self.timezone = timezone
        self.habits = HabitService(repository, timezone)
        self.tasks = TaskService(repository, timezone, habits=self.habits)
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


class _OffloadedTools:
    """Register tools so their blocking work runs off the event loop.

    Every tool here talks to Postgres or Google over synchronous HTTP, and
    FastMCP offers no way to say so. It inspects the handler and, for anything
    that is not a coroutine function, calls it inline:

        if fn_is_async:
            return await fn(...)
        else:
            return fn(...)

    So a plain `def` handler runs on the event loop just as surely as an
    `async def` one that never awaits. Either way the process serves nothing
    else until the handler returns — every other tool call, and /api/health,
    waits behind it. A calendar sync runs for minutes, which is how one call
    took the whole service down while the container sat there healthy.

    Wrapping each handler in a coroutine that awaits a worker thread is what
    actually moves the blocking off the loop. functools.wraps keeps the
    signature FastMCP builds its argument model from, and anyio copies the
    current context into the thread, so the access token the handlers resolve
    the caller from still reaches them.
    """

    def __init__(self, server: Any) -> None:
        self._server = server

    def __getattr__(self, name: str) -> Any:
        return getattr(self._server, name)

    def tool(self, *args: Any, **kwargs: Any) -> Any:
        register = self._server.tool(*args, **kwargs)

        def decorator(fn: Any) -> Any:
            if inspect.iscoroutinefunction(fn):
                return register(fn)

            @functools.wraps(fn)
            async def offloaded(*call_args: Any, **call_kwargs: Any) -> Any:
                import anyio.to_thread

                return await anyio.to_thread.run_sync(
                    functools.partial(fn, *call_args, **call_kwargs)
                )

            return register(offloaded)

        return decorator


def register_core_tools(server: Any) -> None:
    # Every handler below is written as a plain, blocking function. This makes
    # each one run on a worker thread instead of the event loop.
    server = _OffloadedTools(server)

    @server.tool(name="core_create_project")
    def core_create_project(
        name: str,
        track: str | None = None,
        description: str | None = None,
        target_date: str | None = None,
    ) -> dict:
        """Create a project (a Germany-move track, a course, any multi-week goal). Optional track label and YYYY-MM-DD target date."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.create_project(name, track=track, description=description, target_date=target_date)

    @server.tool(name="core_update_project")
    def core_update_project(project_id: str, updates: dict) -> dict:
        """Update project fields: name, track, description, status (active/paused/done/archived), target_date."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.update_project(project_id, updates)

    @server.tool(name="core_add_milestone")
    def core_add_milestone(
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
    def core_update_milestone(milestone_id: str, updates: dict) -> dict:
        """Update milestone fields: name, status (not_started/in_progress/blocked/done), target_date, sort_order, notes."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.update_milestone(milestone_id, updates)

    @server.tool(name="core_delete_milestone")
    def core_delete_milestone(milestone_id: str) -> dict:
        """Delete a milestone permanently. Its tasks are kept, just no longer linked to any milestone. Returns how many tasks were unlinked."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.delete_milestone(milestone_id)

    @server.tool(name="core_list_projects")
    def core_list_projects() -> dict:
        """List all projects with their milestones and open/done task counts."""
        _, projects, _, _, _ = _core_for_current_user()
        return projects.project_tree()

    @server.tool(name="core_create_task")
    def core_create_task(
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
        metadata: dict | None = None,
    ) -> dict:
        """Create a task, optionally under a project/milestone, with due/scheduled YYYY-MM-DD dates, an HH:MM start_time for the day timeline, and a recurrence_key for habit streaks. To split a task across several sittings, pass the original task's ID as parent_task_id; each slot keeps its own day and time, and finishing them all finishes the original. metadata holds any extra columns the project tracks — the study plan uses {"Subject": "Linear algebra", "Source": "Strang"} — and the project view renders whatever keys it finds as table columns."""
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
            metadata=metadata,
        )

    @server.tool(name="core_create_tasks_batch")
    def core_create_tasks_batch(items: list[dict]) -> dict:
        """Create many tasks in one call. Each item takes the same fields as core_create_task: title (required), project_id, milestone_id, due_date, scheduled_date, start_time (HH:MM), priority, estimated_minutes, recurrence_key, notes, parent_task_id, depends_on, metadata. All items are validated before any task is created."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.create_tasks_batch(items)

    @server.tool(name="core_update_task")
    def core_update_task(task_id: str, updates: dict) -> dict:
        """Update task fields: title, status (todo/in_progress/blocked/done/skipped), priority, due_date, scheduled_date, start_time (HH:MM), estimated_minutes, project_id, milestone_id, notes, parent_task_id, depends_on, and metadata (extra project columns, replaced wholesale). Moving a milestone's task past the milestone's target date extends the target to the milestone's last open task (never shortens it; done or undated milestones are left alone); see milestones_extended in the result."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.update_task(task_id, updates)

    @server.tool(name="core_complete_task")
    def core_complete_task(task_id: str, note: str | None = None) -> dict:
        """Mark a task done and record the completion for streaks and metrics."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.complete_task(task_id, source="mcp", note=note)

    @server.tool(name="core_delete_task")
    def core_delete_task(task_id: str) -> dict:
        """Delete one task permanently."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.delete_task(task_id)

    @server.tool(name="core_delete_tasks_batch")
    def core_delete_tasks_batch(task_ids: list[str]) -> dict:
        """Batch delete multiple tasks permanently."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.delete_tasks_batch(task_ids)

    @server.tool(name="core_triage_tasks")
    def core_triage_tasks(task_ids: list[str], action: str, to_date: str | None = None) -> dict:
        """Clear backlog tasks in bulk. action "move" plans them for to_date (YYYY-MM-DD, today or later) with no time, so they land in that day's unscheduled tray; a deadline that has already passed moves to to_date too, a deadline still ahead is kept. action "drop" closes them as skipped (not deleted, history kept). Already-closed tasks are left alone and reported. Moving a milestone's task past the milestone's target date extends the target to the milestone's last open task (never shortens it; done or undated milestones are left alone); see milestones_extended in the result."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.triage_tasks(task_ids, action, to_date)

    @server.tool(name="core_search_tasks")
    def core_search_tasks(
        text: str,
        open_only: bool = True,
        project_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Find tasks by what they are called, anywhere in the workspace and on any date — the only way to ask for "the transcript ones" or "Shashank sir", since core_list_tasks can only filter by status and project. Case-insensitive match on any part of the title, soonest first. Returns total as well as the tasks, so you can see when more matched than came back. Pair it with core_triage_tasks to move or drop everything that matched."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.search_tasks(text, open_only=open_only, project_id=project_id, limit=limit)

    @server.tool(name="core_open_tasks")
    def core_open_tasks(limit: int = 1000) -> dict:
        """Every unfinished task in the workspace, on any date or none, soonest first, up to limit (1-2000). Returns total as well, so you can see when more exist than came back. To find tasks by name use core_search_tasks instead."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.open_tasks(limit=limit)

    @server.tool(name="core_fit_day")
    def core_fit_day(
        on_date: str | None = None,
        task_ids: list[str] | None = None,
        after: str | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
        gap: int = 0,
        dry_run: bool = False,
    ) -> dict:
        """Give a day's loose ends a start time that does not clash with anything already booked. Plain arithmetic over the day's real gaps, not a judgement call: it never double-books, it never shortens a task to make it fit, and it refuses rather than cramming. task_ids names what to place; left out it takes everything unfinished on the day that has either no time at all or a slot that has already gone by. after="now" starts from the clock (today only), or pass a time like "14:00" to sort out the afternoon and leave the morning alone. window_start/window_end bound where it may put things, 07:00 to 22:00 by default; gap is minutes of breathing space between tasks. A habit is never moved, and nor is a task that is finished or under way right now. dry_run works out the same answer and saves nothing, so you can show it before doing it. Returns placements, whatever would not fit and why, and how full the window is."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.fit_day(
            on_date=on_date,
            task_ids=task_ids,
            after=after,
            window_start=window_start,
            window_end=window_end,
            gap=gap,
            dry_run=dry_run,
        )

    @server.tool(name="core_list_tasks")
    def core_list_tasks(status: str | None = None, project_id: str | None = None) -> dict:
        """List tasks, optionally filtered by status or project, sorted by due date."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.list_tasks(status=status, project_id=project_id)

    @server.tool(name="core_inbox_view")
    def core_inbox_view(on_date: str | None = None) -> dict:
        """List all open overdue, missed scheduled and unplanned tasks across the workspace. Optional YYYY-MM-DD date defaults to today. Original dates/times are retained; this does not move calendar blocks."""
        core = _core()
        result = core.tasks.inbox_view(on_date)
        result["data"]["timezone"] = core.timezone
        return result

    @server.tool(name="core_today")
    def core_today() -> dict:
        """Today's view: scheduled tasks, due today, overdue, and completions so far."""
        tasks, _, _, _, _ = _core_for_current_user()
        return tasks.today()

    @server.tool(name="core_add_monthly_goal")
    def core_add_monthly_goal(project_id: str, month: str, description: str) -> dict:
        """Add or update a monthly goal (upsert). month should be YYYY-MM-DD (typically the 1st of the month)."""
        _, _, _, _, goals = _core_for_current_user()
        return goals.add_monthly_goal(project_id, month, description)

    @server.tool(name="core_update_monthly_goal")
    def core_update_monthly_goal(goal_id: str, description: str) -> dict:
        """Update the description of an existing monthly goal."""
        _, _, _, _, goals = _core_for_current_user()
        return goals.update_monthly_goal(goal_id, description)

    @server.tool(name="core_add_weekly_goal")
    def core_add_weekly_goal(project_id: str, week_start: str, description: str) -> dict:
        """Add or update a weekly goal for a project. week_start should be YYYY-MM-DD (a Monday)."""
        _, _, _, _, goals = _core_for_current_user()
        return goals.add_weekly_goal(project_id, week_start, description)

    @server.tool(name="core_sync_calendar")
    def core_sync_calendar(days: int = 7) -> dict:
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

    @server.tool(name="core_import_apple_calendar")
    def core_import_apple_calendar(days: int = 30, forget_deletions: bool = False) -> dict:
        """Pull one-off events from the published Apple/iCloud calendar (APPLE_ICS_URL) into tasks, for today through `days` ahead.

        Each event is keyed by its calendar UID, so running this again never duplicates anything. Repeating events are deliberately skipped — a repeating commitment belongs in the habit engine. An event you deleted here stays deleted; set forget_deletions to true to let the ones you removed come back.

        Returns how many were created and how many were already there. If APPLE_ICS_URL is not set on the server, it says so rather than silently importing nothing — which is the usual reason events do not appear."""
        import os
        import urllib.request

        url = os.environ.get("APPLE_ICS_URL", "").strip()
        if not url:
            return {
                "success": False,
                "message": "APPLE_ICS_URL is not set on the server, so there is no calendar to read",
                "data": {},
                "errors": ["APPLE_ICS_URL_NOT_SET"],
            }
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]

        tasks, _, _, _, _ = _core_for_current_user()
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
        except Exception as error:  # the feed is someone else's server
            return {
                "success": False,
                "message": f"Could not read the calendar feed: {error}",
                "data": {},
                "errors": [str(error)],
            }
        result = tasks.import_ics(text, window_days=days, forget_deletions=forget_deletions)

        # Say what became of each event. "0 imported, 48 already there" is true
        # and useless when the question is why an event is not on the timeline:
        # already a task, deleted here and remembered as deleted, and repeating
        # all count as "already there" or vanish silently.
        from datetime import date as _date, timedelta as _timedelta

        from planner_core.services import _local_today
        from planner_integrations.ics import occurrence_in_window, parse_ics

        start = _local_today(tasks.timezone)
        end = start + _timedelta(days=days)
        by_uid: dict[str, str] = {}
        for row in tasks.repository.list_rows("planner_tasks", columns="title,scheduled_date,metadata"):
            uid = (row.get("metadata") or {}).get("apple_uid")
            if uid:
                by_uid[str(uid)] = "on the timeline"
        buried: set[str] = set()
        try:
            for row in tasks.repository.list_rows("apple_event_tombstones", columns="apple_uid"):
                if row.get("apple_uid"):
                    buried.add(str(row["apple_uid"]))
        except Exception:
            pass

        events = []
        for event in parse_ics(text):
            placed = occurrence_in_window(event, start, end, tasks.timezone)
            if placed is None:
                if event.recurring:
                    events.append({"title": event.summary, "state": "repeats, so it is not imported"})
                continue
            on_date, at_time, minutes = placed
            events.append({
                "title": event.summary,
                "date": on_date.isoformat(),
                "time": at_time or "all day",
                "minutes": minutes,
                "state": (
                    "deleted here, so it stays out" if event.uid in buried
                    else by_uid.get(event.uid, "imported just now")
                ),
            })
        events.sort(key=lambda e: (e.get("date") or "9999", e.get("time") or ""))
        result["data"]["events"] = events
        return result

    @server.tool(name="core_metrics")
    def core_metrics() -> dict:
        """Full metrics snapshot: per-project completion, upcoming deadlines, streaks, totals."""
        _, _, metrics, _, _ = _core_for_current_user()
        return {"success": True, "message": "Planner metrics", "data": metrics.snapshot()}

    @server.tool(name="core_update_task_date_time_batch")
    def core_update_task_date_time_batch(updates: list[dict]) -> str:
        """Batch update scheduled dates and times for multiple tasks.
        Updates should be a list of dicts, each with 'id' and optionally 'scheduled_date', 'due_date', 'start_time'. Moving a milestone's task past the milestone's target date extends the target to the milestone's last open task (never shortens it; done or undated milestones are left alone); see milestones_extended in the result."""
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

    # ── habits ────────────────────────────────────────────────────────────

    @server.tool(name="core_add_habit")
    def core_add_habit(
        title: str,
        cadence: str = "daily",
        days_of_week: list[int] | None = None,
        start_time: str | None = None,
        estimated_minutes: int | None = None,
        recurrence_key: str | None = None,
        project_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Create a habit — something repeated where missing a day costs a streak and nothing else, like gym or sleep. Habits never appear in overdue and are never counted as open work; use core_create_task for anything that stays owed when you miss it. cadence is daily or weekly; a weekly habit needs days_of_week as numbers with 0=Sunday. Occurrences are worked out on read, so no rows are generated and none can go stale."""
        return _core().habits.add_habit(
            title,
            cadence=cadence,
            days_of_week=days_of_week,
            start_time=start_time,
            estimated_minutes=estimated_minutes,
            recurrence_key=recurrence_key,
            project_id=project_id,
            start_date=start_date,
            end_date=end_date,
        )

    @server.tool(name="core_list_habits")
    def core_list_habits(include_inactive: bool = False) -> dict:
        """List habits and their rules. Streak counts come from core_metrics."""
        return _core().habits.list_habits(include_inactive=include_inactive)

    @server.tool(name="core_update_habit")
    def core_update_habit(habit_id: str, updates: dict) -> dict:
        """Change a habit's rule for good: title, cadence, days_of_week, start_time, estimated_minutes, project_id, start_date, end_date, is_active. Set is_active false to retire a habit while keeping its history. To change one day only, use core_reschedule_habit_day."""
        return _core().habits.update_habit(habit_id, updates)

    @server.tool(name="core_delete_habit")
    def core_delete_habit(habit_id: str) -> dict:
        """Delete a habit and its per-day changes. Completions already recorded stay, so past streaks survive."""
        return _core().habits.delete_habit(habit_id)

    @server.tool(name="core_reschedule_habit_day")
    def core_reschedule_habit_day(
        habit_id: str,
        on_date: str,
        moved_to: str | None = None,
        start_time: str | None = None,
        estimated_minutes: int | None = None,
    ) -> dict:
        """Move or retime a single day of a habit, leaving the rule and every other day untouched — Tuesday's gym pushed to Wednesday, or today's session shortened. on_date is the day the rule put it on, YYYY-MM-DD."""
        from datetime import date as _date

        return _core().habits.reschedule_occurrence(
            habit_id,
            _date.fromisoformat(on_date),
            moved_to=moved_to,
            start_time=start_time,
            estimated_minutes=estimated_minutes,
        )

    @server.tool(name="core_skip_habit_day")
    def core_skip_habit_day(habit_id: str, on_date: str) -> dict:
        """Drop one day of a habit from the plan, e.g. no gym on a rest day. The streak still shows the day as missed; this only stops it appearing."""
        from datetime import date as _date

        return _core().habits.skip_occurrence(habit_id, _date.fromisoformat(on_date))

    @server.tool(name="core_complete_habit_day")
    def core_complete_habit_day(habit_id: str, on_date: str) -> dict:
        """Tick one day of a habit, which is what feeds its streak."""
        from datetime import date as _date

        return _core().habits.complete_occurrence(habit_id, _date.fromisoformat(on_date), source="mcp")

    @server.tool(name="core_reopen_habit_day")
    def core_reopen_habit_day(habit_id: str, on_date: str) -> dict:
        """Un-tick one day of a habit."""
        from datetime import date as _date

        return _core().habits.reopen_occurrence(habit_id, _date.fromisoformat(on_date))

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
        plan_item_id: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Log money spent. Amount is a positive number; currency is INR (default, day-to-day spending) or EUR (Germany costs). Date defaults to today, YYYY-MM-DD otherwise. Pick category from: Food, Groceries, Transport, Rent, Utilities, Health, Education, Shopping, Entertainment, Subscriptions, Travel, Savings, Fees, Family, Other — reuse these exact names so monthly summaries stay consistent. Pass goal_id when the spend is a transfer into a savings goal (use core_finance_goals to find the id). Pass plan_item_id when the spend is one of the costs budgeted in the funding plan (use core_plan_overview to find the id) — that is what makes the plan show estimate against actual."""
        result = _core().finance.log_transaction(
            description, amount, on_date=date, category=category, currency=currency,
            kind="expense", merchant=merchant, payment_method=payment_method,
            goal_id=goal_id, plan_item_id=plan_item_id, notes=notes,
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
        """Correct a logged transaction. Updatable fields: date, description, amount, currency, type, category, merchant, payment_method, goal_id, plan_item_id, notes."""
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

    @server.tool(name="core_plan_overview")
    def core_plan_overview(include_unconfirmed: bool = True, as_of: str | None = None) -> str:
        """The funding plan for the move: every budgeted cost against every source of money, both net of what has already been spent or received, plus a month-by-month cash-flow walk.

        Read two numbers off it, and do not confuse them. totals.gap is whether there is enough money at all — negative means a real shortfall. totals.loan_needed is the worst the running balance ever gets, which is the bridge loan required even when the plan is fully funded, because money arriving in March does not pay a bill due in January; totals.loan_by_month says when it is first needed. status is green (covered), amber (funded but mistimed) or red (genuinely short).

        Amounts are converted into totals.base_currency at the plan's own hand-set eur_rate, never a live one. Set include_unconfirmed to false to see the picture using only funding marked confirmed. timeline.undated_costs lists costs that count towards the gap but could not be placed on the timeline because they have no date — give them one for the loan figure to be trustworthy."""
        result = _core().finance.plan_overview(
            include_unconfirmed=include_unconfirmed, as_of=as_of
        )
        return json.dumps(result)

    @server.tool(name="core_add_plan_item")
    def core_add_plan_item(
        kind: str,
        label: str,
        amount: float,
        currency: str = "INR",
        category: str | None = None,
        due_date: str | None = None,
        instalments: int = 1,
        certainty: str = "likely",
        notes: str | None = None,
    ) -> str:
        """Add one line to the funding plan. kind is 'cost' (money going out — a test fee, tuition, an application) or 'fund' (money coming in — savings, salary put aside, family help, a loan).

        amount is PER INSTALMENT, not the total: saving 40,000 a month for ten months is amount 40000 with instalments 10, while a one-off fee is amount 12000 with instalments 1. due_date is when a cost is payable or when funding becomes available, and instalments repeat monthly from it. Leave due_date out for money already in hand; leaving it out on a cost keeps it in the totals but out of the cash-flow timeline.

        certainty applies to funding: 'confirmed' (committed), 'likely' (default) or 'maybe'. Cost categories: Tests, Tuition, Applications, Courses, Documents, Visa, Travel, Living, Family, Other. Funding categories: Savings, Salary, Family, Sale, Scholarship, Loan, Other."""
        result = _core().finance.add_plan_item(
            kind, label, amount, currency=currency, category=category,
            due_date=due_date, instalments=instalments, certainty=certainty, notes=notes,
        )
        return json.dumps(result)

    @server.tool(name="core_update_plan_item")
    def core_update_plan_item(item_id: str, updates: dict) -> str:
        """Correct one line of the funding plan. Updatable fields: label, category, amount (per instalment), currency, due_date, instalments, certainty, notes, sort_order, kind."""
        result = _core().finance.update_plan_item(item_id, updates)
        return json.dumps(result)

    @server.tool(name="core_delete_plan_item")
    def core_delete_plan_item(item_id: str) -> str:
        """Remove a line from the funding plan. Spending already logged against it stays in the passbook and simply stops being attributed to the plan."""
        result = _core().finance.delete_plan_item(item_id)
        return json.dumps(result)

    @server.tool(name="core_update_plan")
    def core_update_plan(updates: dict) -> str:
        """Change the funding plan itself. Updatable fields: name, base_currency, eur_rate (how many units of the base currency one euro is worth, used for every conversion in the plan), notes."""
        result = _core().finance.update_plan(updates)
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
