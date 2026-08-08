"""Tests for the v2 Postgres planner core: services, metrics, reminders, Telegram."""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from planner_core.repository import PlannerCoreError, PlannerCoreRepository
from planner_core.services import MetricsService, ProjectService, ReminderService, TaskService
from planner_core.telegram import parse_command, sender_chat_id

USER_ID = uuid4()
WORKSPACE_ID = uuid4()
TZ = "Asia/Kolkata"



TABLE_DEFAULTS = {
    "projects": {"status": "active", "track": None, "description": None, "target_date": None},
    "milestones": {"status": "not_started", "target_date": None, "sort_order": 0, "notes": None},
    "planner_tasks": {
        "status": "todo",
        "priority": "medium",
        "project_id": None,
        "milestone_id": None,
        "due_date": None,
        "scheduled_date": None,
        "start_time": None,
        "estimated_minutes": None,
        "recurrence_key": None,
        "depends_on": None,
        "notes": None,
        "completed_at": None,
    },
    "task_completions": {"task_id": None, "recurrence_key": None, "note": None},
    "reminder_log": {"channel": "telegram", "payload": None},
}

class MemoryGateway:
    """In-memory PostgREST stand-in supporting the eq-filter subset the client uses."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def select(self, table, *, filters, columns="*", limit=None, query_string=None):
        rows = [row for row in self.tables.get(table, []) if self._matches(row, filters)]
        return rows[:limit] if limit else rows

    def insert(self, table, payload):
        if isinstance(payload, list):
            return [self.insert(table, p)[0] for p in payload]
        row = {"id": str(uuid4()), **TABLE_DEFAULTS.get(table, {}), **dict(payload)}
        self.tables.setdefault(table, []).append(row)
        return [dict(row)]

    def update(self, table, payload, *, filters):
        updated = []
        for row in self.tables.get(table, []):
            if self._matches(row, filters):
                row.update(payload)
                updated.append(dict(row))
        return updated

    def delete(self, table, *, filters):
        if not filters:
            raise ValueError("Refusing to delete without filters")
        self.tables[table] = [
            row for row in self.tables.get(table, []) if not self._matches(row, filters)
        ]

    @staticmethod
    def _matches(row, filters):
        for key, value in filters.items():
            row_val = str(row.get(key)).casefold()
            if isinstance(value, list):
                if not any(row_val == str(v).casefold() for v in value):
                    return False
            else:
                if row_val != str(value).casefold():
                    return False
        return True


@pytest.fixture()
def repo():
    return PlannerCoreRepository(MemoryGateway(), USER_ID, WORKSPACE_ID)


@pytest.fixture()
def services(repo):
    tasks = TaskService(repo, TZ)
    projects = ProjectService(repo)
    metrics = MetricsService(repo, TZ)
    reminders = ReminderService(repo, metrics, tasks, TZ)
    return tasks, projects, metrics, reminders


def _today() -> date:
    return datetime.now(ZoneInfo(TZ)).date()


def test_repository_scopes_every_row_to_the_tenant(repo) -> None:
    row = repo.insert_row("projects", {"name": "Germany Move"})

    assert row["user_id"] == str(USER_ID)
    assert row["workspace_id"] == str(WORKSPACE_ID)
    other = PlannerCoreRepository(repo.gateway, uuid4(), uuid4())
    assert other.list_rows("projects") == []


def test_project_milestone_task_lifecycle_and_tree(services) -> None:
    tasks, projects, _, _ = services

    project = projects.create_project("Germany Move", track="Colleges", target_date="2027-07-15")
    project_id = project["data"]["project"]["id"]
    milestone = projects.add_milestone(project_id, "Shortlist done", target_date="2026-10-15")
    milestone_id = milestone["data"]["milestone"]["id"]
    created = tasks.create_task(
        "Compare TU9 programs", project_id=project_id, milestone_id=milestone_id, due_date="2026-10-01"
    )
    tasks.complete_task(created["data"]["task"]["id"])
    projects.update_milestone(milestone_id, {"status": "in_progress"})

    tree = projects.project_tree()["data"]["projects"]
    assert tree[0]["name"] == "Germany Move"
    assert tree[0]["milestones"][0]["status"] == "in_progress"
    assert tree[0]["done_tasks"] == 1 and tree[0]["open_tasks"] == 0


def test_create_tasks_batch_creates_all_and_validates_before_writing(services) -> None:
    tasks, _, _, _ = services

    result = tasks.create_tasks_batch(
        [
            {"title": "Book visa slot", "due_date": "2026-08-01", "priority": "high"},
            {"title": "German lesson", "scheduled_date": "2026-07-24", "start_time": "18:00"},
        ]
    )
    assert result["message"] == "Created 2 tasks"
    titles = [task["title"] for task in result["data"]["tasks"]]
    assert titles == ["Book visa slot", "German lesson"]

    with pytest.raises(PlannerCoreError, match="Task 2"):
        tasks.create_tasks_batch([{"title": "Fine"}, {"title": "Bad", "priority": "urgent"}])
    all_titles = [row["title"] for row in tasks.list_tasks()["data"]["tasks"]]
    assert "Fine" not in all_titles
    with pytest.raises(PlannerCoreError):
        tasks.create_tasks_batch([])


def test_invalid_inputs_are_rejected(services) -> None:
    tasks, projects, _, _ = services

    with pytest.raises(PlannerCoreError):
        projects.create_project("   ")
    with pytest.raises(PlannerCoreError):
        tasks.create_task("Task", priority="urgent")
    with pytest.raises(PlannerCoreError):
        tasks.update_task("some-id", {"status": "finished"})
    with pytest.raises(PlannerCoreError):
        projects.add_milestone("missing-project", "Milestone")
    with pytest.raises(ValueError):
        tasks.create_task("Task", due_date="not-a-date")


def test_complete_task_records_completion_and_streak(services) -> None:
    tasks, _, metrics, _ = services

    created = tasks.create_task("German lesson", recurrence_key="german")
    result = tasks.complete_task(created["data"]["task"]["id"], source="telegram")

    assert result["success"] and result["data"]["task"]["status"] == "done"
    snapshot = metrics.snapshot()
    assert snapshot["streaks"]["german"] == 1
    assert snapshot["totals"]["completed_today"] == 1


def test_complete_by_title_fuzzy_matching(services) -> None:
    tasks, _, _, _ = services
    tasks.create_task("Study German A1 vocab")
    tasks.create_task("Book IELTS slot")

    exact = tasks.complete_by_title("book ielts slot", source="telegram")
    assert exact["success"]

    partial = tasks.complete_by_title("german vocab")
    assert partial["success"]

    nothing = tasks.complete_by_title("water the plants")
    assert not nothing["success"] and nothing["errors"] == ["NO_MATCH"]


def test_today_buckets_scheduled_due_and_overdue(services) -> None:
    tasks, _, _, _ = services
    today = _today().isoformat()
    tasks.create_task("Scheduled today", scheduled_date=today)
    tasks.create_task("Due today", due_date=today)
    tasks.create_task("Old overdue", due_date="2026-01-01")
    done = tasks.create_task("Finished", scheduled_date=today)
    tasks.complete_task(done["data"]["task"]["id"])

    data = tasks.today()["data"]

    assert [row["title"] for row in data["due_today"]] == ["Due today"]
    assert [row["title"] for row in data["overdue"]] == ["Old overdue"]
    assert len(data["completed_today"]) == 1
    assert "Scheduled today" in [row["title"] for row in data["scheduled"]]


def test_today_surfaces_past_scheduled_tasks_as_overdue(services) -> None:
    """A timed block planned for a past day with no due date must still resurface
    so replan can push it forward instead of silently losing it."""
    tasks, _, _, _ = services
    tasks.create_task("Yesterday's German", scheduled_date="2026-01-01", start_time="09:30")
    # A task due today but scheduled in the past belongs in due_today, not overdue.
    tasks.create_task("Due today, planned earlier", due_date=_today().isoformat(), scheduled_date="2026-01-02")

    data = tasks.today()["data"]
    overdue_titles = [row["title"] for row in data["overdue"]]

    assert "Yesterday's German" in overdue_titles
    assert "Due today, planned earlier" not in overdue_titles
    assert "Due today, planned earlier" in [row["title"] for row in data["due_today"]]


def test_today_checklist_flags_done_and_sorts_open_first(services) -> None:
    tasks, _, _, _ = services
    today = _today().isoformat()
    tasks.create_task("Gym", scheduled_date=today)
    tasks.create_task("Write SOP", due_date=today)
    done = tasks.create_task("Call baby HR", scheduled_date=today)
    tasks.create_task("Not today", due_date="2027-01-01")
    tasks.complete_task(done["data"]["task"]["id"])

    data = tasks.today_checklist()["data"]
    titles = [item["title"] for item in data["items"]]

    assert data["done_count"] == 1 and data["total_count"] == 3
    assert "Not today" not in titles
    assert titles[-1] == "Call baby HR"  # done sorts to the bottom
    assert data["items"][-1]["done"] is True
    assert all(item["done"] is False for item in data["items"][:-1])


def test_metrics_snapshot_and_dashboard_flat_shape(services) -> None:
    tasks, projects, metrics, _ = services
    project = projects.create_project("German", track="german", target_date="2026-08-22")
    project_id = project["data"]["project"]["id"]
    first = tasks.create_task("Unit 1", project_id=project_id)
    tasks.create_task("Unit 2", project_id=project_id, due_date="2026-01-01")
    tasks.complete_task(first["data"]["task"]["id"])

    snapshot = metrics.snapshot()
    project_metrics = snapshot["projects"][0]
    assert project_metrics["completion_pct"] == 50.0
    assert snapshot["totals"]["overdue_tasks"] == 1
    assert snapshot["upcoming_deadlines"][0]["overdue"] is True

    flat = metrics.flat_snapshot()
    assert flat["german_units_total"] == "2"
    assert flat["german_units_left"] == "1"
    assert flat["german_target_date"] == "2026-08-22"


def test_metrics_counts_past_scheduled_as_overdue(services) -> None:
    """core_metrics must agree with core_today: an open task planned for a past
    day with no due date is overdue, but one due today (planned earlier) is not."""
    tasks, _, metrics, _ = services
    tasks.create_task("Yesterday's German", scheduled_date="2026-01-01", start_time="09:30")
    tasks.create_task("Due today, planned earlier", due_date=_today().isoformat(), scheduled_date="2026-01-02")

    assert metrics.snapshot()["totals"]["overdue_tasks"] == 1


def test_reminders_fire_in_windows_and_are_idempotent(services) -> None:
    tasks, _, _, reminders = services
    today = _today().isoformat()
    tasks.create_task("Write SOP", scheduled_date=today, due_date=today)

    local_today = _today()
    morning = datetime(local_today.year, local_today.month, local_today.day, 8, 0, tzinfo=ZoneInfo(TZ))
    due = reminders.due_reminders(morning)
    kinds = {item["kind"] for item in due}
    assert "morning_brief" in kinds and "deadline_alert" in kinds

    for item in due:
        reminders.record_sent(item["kind"], "telegram", {"message": item["message"]})
    assert reminders.due_reminders(morning) == []

    evening = datetime(local_today.year, local_today.month, local_today.day, 20, 0, tzinfo=ZoneInfo(TZ))
    nudge = reminders.due_reminders(evening)
    assert [item["kind"] for item in nudge] == ["evening_nudge"]
    assert "Write SOP" in nudge[0]["message"]


def test_evening_nudge_skipped_after_a_completion(services) -> None:
    tasks, _, _, reminders = services
    created = tasks.create_task("Anything", scheduled_date=_today().isoformat())
    tasks.complete_task(created["data"]["task"]["id"])

    local_today = _today()
    evening = datetime(local_today.year, local_today.month, local_today.day, 20, 0, tzinfo=ZoneInfo(TZ))
    assert [item["kind"] for item in reminders.due_reminders(evening)] == []


def test_telegram_parse_command_and_chat_extraction() -> None:
    update = {"message": {"chat": {"id": 42}, "text": "done german lesson"}}

    assert parse_command(update) == ("done", "german lesson")
    assert sender_chat_id(update) == "42"
    assert parse_command({"message": {"chat": {"id": 1}, "text": "/today"}}) == ("today", "")
    assert parse_command({"message": {"chat": {"id": 1}, "text": "hello"}}) is None
    assert parse_command({}) is None


def test_milestone_crud_and_task_linking(services) -> None:
    tasks, projects, _, _ = services
    project = projects.create_project("Germany Move", track="Colleges")
    project_id = project["data"]["project"]["id"]

    # Add a milestone
    ms = projects.add_milestone(project_id, "Shortlist done", target_date="2026-10-01")
    milestone_id = ms["data"]["milestone"]["id"]

    # Create a task linked to the milestone
    t = tasks.create_task("Compare TU9", project_id=project_id, milestone_id=milestone_id)
    assert t["data"]["task"]["milestone_id"] == milestone_id

    # Update milestone status
    projects.update_milestone(milestone_id, {"status": "in_progress"})
    tree = projects.project_tree()["data"]["projects"]
    assert tree[0]["milestones"][0]["status"] == "in_progress"

    # Update task to link to a different milestone
    ms2 = projects.add_milestone(project_id, "Applications sent")
    ms2_id = ms2["data"]["milestone"]["id"]
    tasks.update_task(t["data"]["task"]["id"], {"milestone_id": ms2_id})


def test_goal_service_monthly_and_weekly(services) -> None:
    from planner_core.services import GoalService
    tasks, projects, _, _ = services
    goals = GoalService(tasks.repository)

    project = projects.create_project("German", track="german")
    pid = project["data"]["project"]["id"]

    # Monthly goal upsert
    result = goals.add_monthly_goal(pid, "2026-08-01", "Finish A1 vocab")
    assert result["success"]
    goal_id = result["data"]["monthly_goal"]["id"]

    # Upsert same month overwrites
    result2 = goals.add_monthly_goal(pid, "2026-08-01", "Finish A1 + A2 vocab")
    assert result2["data"]["monthly_goal"]["id"] == goal_id
    assert result2["data"]["monthly_goal"]["description"] == "Finish A1 + A2 vocab"

    # Weekly goal
    wg = goals.add_weekly_goal(pid, "2026-08-03", "Complete 3 lessons")
    assert wg["success"]

    # Week view returns goals
    wv = goals.week_view(date(2026, 8, 3))
    assert len(wv["monthly_goals"]) == 1
    assert len(wv["weekly_goals"]) == 1

    # Delete monthly goal
    goals.delete_monthly_goal(goal_id)


def test_batch_delete_removes_tasks(services) -> None:
    tasks, _, _, _ = services
    t1 = tasks.create_task("Task A")
    t2 = tasks.create_task("Task B")
    t3 = tasks.create_task("Task C")
    ids = [t1["data"]["task"]["id"], t2["data"]["task"]["id"]]

    result = tasks.delete_tasks_batch(ids)
    assert result["success"]
    assert len(result["data"]["deleted"]) == 2

    remaining = tasks.list_tasks()["data"]["tasks"]
    titles = [t["title"] for t in remaining]
    assert "Task C" in titles
    assert "Task A" not in titles
    assert "Task B" not in titles


def test_week_view_groups_tasks_in_week(services) -> None:
    tasks, _, _, _ = services
    tasks.create_task("Monday task", scheduled_date="2026-08-03")
    tasks.create_task("Wednesday task", scheduled_date="2026-08-05")
    tasks.create_task("Next week", scheduled_date="2026-08-10")

    wv = tasks.week_view("2026-08-04")  # Tuesday → week of Aug 3
    items = wv["data"]["items"]
    titles = [i["title"] for i in items]

    assert "Monday task" in titles
    assert "Wednesday task" in titles
    assert "Next week" not in titles
    assert wv["data"]["week_start"] == "2026-08-03"


def test_core_tools_register_on_a_fastmcp_server() -> None:
    from mcp.server.fastmcp import FastMCP

    from planner_core.mcp_tools import register_core_tools

    server = FastMCP("test")
    register_core_tools(server)
    names = sorted(server._tool_manager._tools)

    expected = [
        "core_add_milestone",
        "core_add_monthly_goal",
        "core_add_project_qna",
        "core_add_project_widget",
        "core_add_weekly_goal",
        "core_complete_task",
        "core_create_project",
        "core_create_task",
        "core_create_tasks_batch",
        "core_delete_monthly_goal",
        "core_delete_project_qna",
        "core_delete_project_widget",
        "core_delete_task",
        "core_delete_tasks_batch",
        "core_list_project_widgets",
        "core_list_projects",
        "core_list_tasks",
        "core_metrics",
        "core_sync_calendar",
        "core_today",
        "core_update_milestone",
        "core_update_monthly_goal",
        "core_update_project",
        "core_update_project_qna",
        "core_update_project_widget",
        "core_update_task",
        "core_update_task_date_time_batch",
    ]
    assert names == expected
