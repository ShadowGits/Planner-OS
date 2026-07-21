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

    def select(self, table, *, filters, columns="*", limit=None):
        rows = [row for row in self.tables.get(table, []) if self._matches(row, filters)]
        return rows[:limit] if limit else rows

    def insert(self, table, payload):
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
        return all(str(row.get(key)).casefold() == str(value).casefold() for key, value in filters.items())


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


def test_reminders_fire_in_windows_and_are_idempotent(services) -> None:
    tasks, _, _, reminders = services
    today = _today().isoformat()
    tasks.create_task("Write SOP", scheduled_date=today, due_date=today)

    morning = datetime(2026, 7, 21, 8, 0, tzinfo=ZoneInfo(TZ))
    due = reminders.due_reminders(morning)
    kinds = {item["kind"] for item in due}
    assert "morning_brief" in kinds and "deadline_alert" in kinds

    for item in due:
        reminders.record_sent(item["kind"], "telegram", {"message": item["message"]})
    assert reminders.due_reminders(morning) == []

    evening = datetime(2026, 7, 21, 20, 0, tzinfo=ZoneInfo(TZ))
    nudge = reminders.due_reminders(evening)
    assert [item["kind"] for item in nudge] == ["evening_nudge"]
    assert "Write SOP" in nudge[0]["message"]


def test_evening_nudge_skipped_after_a_completion(services) -> None:
    tasks, _, _, reminders = services
    created = tasks.create_task("Anything", scheduled_date=_today().isoformat())
    tasks.complete_task(created["data"]["task"]["id"])

    evening = datetime(2026, 7, 21, 20, 0, tzinfo=ZoneInfo(TZ))
    assert [item["kind"] for item in reminders.due_reminders(evening)] == []


def test_telegram_parse_command_and_chat_extraction() -> None:
    update = {"message": {"chat": {"id": 42}, "text": "done german lesson"}}

    assert parse_command(update) == ("done", "german lesson")
    assert sender_chat_id(update) == "42"
    assert parse_command({"message": {"chat": {"id": 1}, "text": "/today"}}) == ("today", "")
    assert parse_command({"message": {"chat": {"id": 1}, "text": "hello"}}) is None
    assert parse_command({}) is None


def test_core_tools_register_on_a_fastmcp_server() -> None:
    from mcp.server.fastmcp import FastMCP

    from planner_core.mcp_tools import register_core_tools

    server = FastMCP("test")
    register_core_tools(server)
    names = sorted(server._tool_manager._tools)

    assert names == [
        "core_add_milestone",
        "core_complete_task",
        "core_create_project",
        "core_create_task",
        "core_delete_task",
        "core_list_projects",
        "core_list_tasks",
        "core_metrics",
        "core_today",
        "core_update_milestone",
        "core_update_project",
        "core_update_task",
    ]
