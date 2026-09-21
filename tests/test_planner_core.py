"""Tests for the v2 Postgres planner core: services, metrics, reminders, Telegram."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from planner_core.repository import PlannerCoreError, PlannerCoreRepository
from planner_core.services import (
    MAX_STARRED_PER_DAY,
    OVERDUE_LIST_LIMIT,
    FinanceService,
    HabitService,
    MetricsService,
    ProjectService,
    ReminderService,
    TaskService,
    parse_habit_item_id,
)
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
    # Mirrors the column defaults in migration 0022; without them a habit
    # reads as inactive and every occurrence silently disappears.
    "habits": {
        "cadence": "daily",
        "days_of_week": [],
        "start_time": None,
        "estimated_minutes": None,
        "project_id": None,
        "end_date": None,
        "is_active": True,
    },
    "habit_overrides": {
        "moved_to": None,
        "start_time": None,
        "estimated_minutes": None,
        "skipped": False,
    },
    "reminder_log": {"channel": "telegram", "payload": None},
    # Mirrors migration 0032: without these a plan line reads as having no
    # instalments and an unknown certainty.
    "finance_plans": {"base_currency": "INR", "eur_rate": 100, "notes": None},
    "finance_plan_items": {
        "category": None, "due_date": None, "instalments": 1,
        "certainty": "likely", "notes": None, "sort_order": 0,
    },
}

class MemoryGateway:
    """In-memory PostgREST stand-in supporting the eq-filter subset the client uses."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def select(self, table, *, filters, columns="*", limit=None, query_string=None):
        rows = [row for row in self.tables.get(table, []) if self._matches(row, filters)]
        rows = [row for row in rows if self._matches_query(row, query_string)]
        rows = self._apply_directives(rows, query_string)
        return rows[:limit] if limit else rows

    def rpc(self, function, payload):
        """Only the rollups the metrics snapshot calls. Mirrors the SQL in
        migrations 0019, 0024 and 0027 so the tests cover the real path, not
        just the fallback."""
        if function == "planner_completion_summary":
            return self._completion_summary(payload)
        if function == "planner_milestone_progress":
            return self._milestone_progress(payload)
        if function != "planner_task_counts":
            raise NotImplementedError(function)

        today = str(payload["p_today"])
        buckets: dict = {}
        for row in self.tables.get("planner_tasks", []):
            if str(row.get("user_id")) != str(payload["p_user_id"]):
                continue
            if str(row.get("workspace_id")) != str(payload["p_workspace_id"]):
                continue
            if row.get("parent_task_id"):
                continue
            key = row.get("project_id")
            bucket = buckets.setdefault(
                key,
                {"project_id": key, "done_count": 0, "total_count": 0,
                 "open_count": 0, "overdue_count": 0},
            )
            status = row.get("status")
            if status == "done":
                bucket["done_count"] += 1
            if status != "skipped":
                bucket["total_count"] += 1
            if status in {"todo", "in_progress", "blocked"}:
                bucket["open_count"] += 1
                due, planned = row.get("due_date"), row.get("scheduled_date")
                # Mirrors migration 0025: past due, past planned, or no date.
                if (
                    (due and str(due) < today)
                    or (not due and planned and str(planned) < today)
                    or (not due and not planned)
                ):
                    bucket["overdue_count"] += 1
        return list(buckets.values())

    def _milestone_progress(self, payload):
        """Mirrors migration 0027: per-milestone done/total plus the span its
        tasks cover, skipping time-slot children."""
        buckets: dict = {}
        for row in self.tables.get("planner_tasks", []):
            if str(row.get("user_id")) != str(payload["p_user_id"]):
                continue
            if str(row.get("workspace_id")) != str(payload["p_workspace_id"]):
                continue
            if row.get("parent_task_id"):
                continue
            key = row.get("milestone_id")
            if not key:
                continue
            bucket = buckets.setdefault(
                str(key),
                {"milestone_id": str(key), "done_count": 0, "total_count": 0,
                 "first_date": None, "last_date": None},
            )
            status = row.get("status")
            if status == "done":
                bucket["done_count"] += 1
            if status != "skipped":
                bucket["total_count"] += 1
            when = row.get("scheduled_date") or row.get("due_date")
            if when:
                when = str(when)
                if bucket["first_date"] is None or when < bucket["first_date"]:
                    bucket["first_date"] = when
                if bucket["last_date"] is None or when > bucket["last_date"]:
                    bucket["last_date"] = when
        return list(buckets.values())

    def _completion_summary(self, payload):
        """Mirrors migration 0024: streaks walked back from an anchor of today,
        or yesterday when today is not ticked yet."""
        from datetime import date as _date, timedelta as _td

        today = _date.fromisoformat(str(payload["p_today"]))
        mine = [
            row
            for row in self.tables.get("task_completions", [])
            if str(row.get("user_id")) == str(payload["p_user_id"])
            and str(row.get("workspace_id")) == str(payload["p_workspace_id"])
            and row.get("completed_on")
        ]

        by_key: dict[str, set] = {}
        for row in mine:
            key = row.get("recurrence_key")
            day = _date.fromisoformat(str(row["completed_on"])[:10])
            if key and day <= today:
                by_key.setdefault(str(key), set()).add(day)

        streaks = {}
        for key, days in by_key.items():
            cursor = today if today in days else today - _td(days=1)
            streak = 0
            while cursor in days:
                streak += 1
                cursor -= _td(days=1)
            streaks[key] = streak

        stamps = [_date.fromisoformat(str(row["completed_on"])[:10]) for row in mine]
        return {
            "streaks": streaks,
            "completed_today": len([d for d in stamps if d == today]),
            "completions_last_7_days": len(
                [d for d in stamps if today - _td(days=6) <= d <= today]
            ),
        }

    @staticmethod
    def _split_top(text):
        """Split on commas that are not inside parentheses."""
        parts, depth, current = [], 0, ""
        for char in text:
            if char == "," and depth == 0:
                parts.append(current)
                current = ""
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            current += char
        if current:
            parts.append(current)
        return parts

    @classmethod
    def _evaluate(cls, row, expression):
        expression = expression.strip()
        for prefix, combine in (("and(", all), ("or(", any)):
            if expression.startswith(prefix) and expression.endswith(")"):
                inner = expression[len(prefix):-1]
                return combine(cls._evaluate(row, part) for part in cls._split_top(inner))
        column, _, condition = expression.partition(".")
        return cls._compare(row.get(column), condition)

    @staticmethod
    def _compare(actual, condition):
        op, _, value = condition.partition(".")
        if op == "is":
            return actual is None if value == "null" else actual is not None
        if op == "in":
            return actual is not None and str(actual) in value.strip("()").split(",")
        if actual is None:
            return False
        actual = str(actual)
        if op == "eq":
            return actual == value
        if op == "gte":
            return actual >= value
        if op == "lte":
            return actual <= value
        if op == "gt":
            return actual > value
        if op == "lt":
            return actual < value
        return True

    @classmethod
    def _matches_query(cls, row, query_string):
        """Evaluate the PostgREST filter grammar the services build, including
        nested or=(and(...),and(...)) groups."""
        if not query_string:
            return True
        for clause in query_string.split("&"):
            key, _, condition = clause.partition("=")
            if key in {"order", "limit", "offset", "select"} or not condition:
                continue
            if key in {"or", "and"}:
                if not cls._evaluate(row, f"{key}{condition}"):
                    return False
            elif not cls._compare(row.get(key), condition):
                return False
        return True

    @staticmethod
    def _apply_directives(rows, query_string):
        if not query_string:
            return rows
        for clause in query_string.split("&"):
            key, _, value = clause.partition("=")
            if key == "order":
                for spec in reversed(value.split(",")):
                    parts = spec.split(".")
                    column, descending = parts[0], "desc" in parts
                    rows = sorted(
                        rows,
                        key=lambda r, c=column: (r.get(c) is None, str(r.get(c) or "")),
                        reverse=descending,
                    )
            elif key == "limit":
                rows = rows[: int(value)]
        return rows

    # Check constraints the real database enforces. Without these the fake
    # accepts values Postgres refuses, which is exactly how a habit tick
    # shipped writing a source the constraint rejects — every test passed and
    # the phone got a 500.
    CHECKS = {
        "task_completions": {"source": {"mcp", "telegram", "dashboard", "api"}},
        "planner_tasks": {"status": {"todo", "in_progress", "blocked", "done", "skipped"}},
        # Migration 0032.
        "finance_plan_items": {
            "kind": {"cost", "fund"},
            "certainty": {"confirmed", "likely", "maybe"},
        },
    }

    def insert(self, table, payload):
        if isinstance(payload, list):
            return [self.insert(table, p)[0] for p in payload]
        for column, allowed in self.CHECKS.get(table, {}).items():
            value = dict(payload).get(column)
            if value is not None and value not in allowed:
                raise ValueError(
                    f"{table}.{column} violates its check constraint: {value!r} "
                    f"not in {sorted(allowed)}"
                )
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


def _seed_completions(repo, days, key="gym"):
    for offset in days:
        repo.insert_row(
            "task_completions",
            {
                "recurrence_key": key,
                "completed_on": (date.today() - timedelta(days=offset)).isoformat(),
                "source": "api",
            },
        )


def test_completion_summary_rollup_and_scan_agree(services, repo) -> None:
    """The rollup is an optimisation, so it has to produce exactly what the
    full scan produced. A run broken by a missed day stops at the gap."""
    _, _, metrics, _ = services
    # yesterday, and the three days before it — then a gap at day 5
    _seed_completions(repo, [1, 2, 3, 4, 6, 7])

    rolled = metrics._completion_summary(date.today())
    scanned = metrics._completion_summary_by_scan(date.today())

    assert rolled == scanned
    # today is unticked, so the streak is measured from yesterday and stops
    # at the missing fifth day
    assert rolled["streaks"]["gym"] == 4
    assert rolled["completed_today"] == 0
    # the window spans today and the six days before it, so day 7 is outside
    assert rolled["completions_last_7_days"] == 5


def test_completion_summary_falls_back_when_function_is_missing(services, repo) -> None:
    """A deploy can land before the migration does, and the dashboard still
    has to show the right numbers."""
    _, _, metrics, _ = services
    _seed_completions(repo, [0, 1, 2])

    original = repo.gateway.rpc
    repo.gateway.rpc = lambda function, payload: (_ for _ in ()).throw(
        RuntimeError("function does not exist")
    )
    try:
        summary = metrics._completion_summary(date.today())
    finally:
        repo.gateway.rpc = original

    assert summary["streaks"]["gym"] == 3
    assert summary["completed_today"] == 1


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


def test_event_reminders_fire_at_30_and_5_minutes_once_each(services) -> None:
    tasks, _, _, reminders = services
    local = _today()
    tasks.create_task("Dentist", scheduled_date=local.isoformat(), start_time="15:00")

    def at(hour, minute):
        return datetime(local.year, local.month, local.day, hour, minute, tzinfo=ZoneInfo(TZ))

    # 14:30 — exactly 30 minutes ahead → the yellow reminder, not the green one.
    due = reminders._event_reminders(at(14, 30), set())
    assert [d["kind"].split(":")[0] for d in due] == ["event30"]
    # The task's name belongs in the title: a phone shows that line first and
    # often only that, so "In 30 minutes" alone says nothing worth opening.
    assert due[0]["title"] == "🟡 IN 30 MINUTES : Dentist"
    assert "15:00" in due[0]["message"]

    # 14:57 — inside 5 minutes → the green reminder.
    green = reminders._event_reminders(at(14, 57), set())
    assert [d["kind"].split(":")[0] for d in green] == ["event5"]
    assert green[0]["title"] == "🟢 IN 3 MINUTES : Dentist"

    # Both warnings for one task carry the same tag, so the second replaces the
    # first on the phone rather than stacking up beside it.
    assert due[0]["tag"] == green[0]["tag"]

    # At the hour itself there is nothing left to count down to.
    starting = reminders._event_reminders(at(15, 0), set())
    assert starting[0]["title"] == "🟢 STARTING NOW : Dentist"

    # Already recorded for today → never fires twice.
    sent = {due[0]["kind"], green[0]["kind"]}
    assert reminders._event_reminders(at(14, 30), sent) == []
    assert reminders._event_reminders(at(14, 57), sent) == []

    # Well before (an hour out) → nothing yet.
    assert reminders._event_reminders(at(13, 0), set()) == []


def test_event_reminder_fires_once_across_cron_ticks(services) -> None:
    """The real dedup path: due_reminders reads the reminder log to decide what
    is already sent. Recording a fire must stop the next tick re-sending it —
    the bug was that the log write was rejected, so it fired every tick."""
    tasks, _, _, reminders = services
    local = _today()
    tasks.create_task("Dentist", scheduled_date=local.isoformat(), start_time="14:25")
    # 14:00 is outside the morning/evening digest windows, so only the event
    # reminder is in play; the task is 25 minutes out -> the 30-minute one.
    now = datetime(local.year, local.month, local.day, 14, 0, tzinfo=ZoneInfo(TZ))

    first = [r for r in reminders.due_reminders(now) if r["kind"].startswith("event30:")]
    assert len(first) == 1, "the 30-minute reminder should fire once"

    # Record it exactly as the cron does, then run again: it must not repeat.
    reminders.record_sent(first[0]["kind"], "push", {"message": first[0]["message"]})
    again = [r for r in reminders.due_reminders(now) if r["kind"].startswith("event30:")]
    assert again == [], "the reminder re-fired — dedup is broken"


def test_event_reminders_skip_done_and_untimed(services) -> None:
    tasks, _, _, reminders = services
    local = _today()
    done = tasks.create_task("Gym", scheduled_date=local.isoformat(), start_time="15:00")["data"]["task"]
    tasks.complete_task(done["id"])
    tasks.create_task("Someday", scheduled_date=local.isoformat())  # no start_time

    when = datetime(local.year, local.month, local.day, 14, 30, tzinfo=ZoneInfo(TZ))
    assert reminders._event_reminders(when, set()) == []


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
        "core_add_habit",
        "core_add_milestone",
        "core_add_monthly_goal",
        "core_add_plan_item",
        "core_add_project_qna",
        "core_add_project_widget",
        "core_add_recurring_charge",
        "core_add_weekly_goal",
        "core_complete_habit_day",
        "core_complete_task",
        "core_create_project",
        "core_create_task",
        "core_create_tasks_batch",
        "core_delete_habit",
        "core_delete_monthly_goal",
        "core_delete_plan_item",
        "core_delete_project_qna",
        "core_delete_project_widget",
        "core_delete_recurring_charge",
        "core_delete_task",
        "core_delete_tasks_batch",
        "core_delete_transaction",
        "core_finance_goals",
        "core_finance_summary",
        "core_list_habits",
        "core_list_project_widgets",
        "core_list_projects",
        "core_list_recurring_charges",
        "core_list_tasks",
        "core_list_transactions",
        "core_log_expense",
        "core_log_income",
        "core_metrics",
        "core_plan_overview",
        "core_reopen_habit_day",
        "core_reschedule_habit_day",
        "core_skip_habit_day",
        "core_sync_calendar",
        "core_today",
        "core_update_habit",
        "core_update_milestone",
        "core_update_monthly_goal",
        "core_update_plan",
        "core_update_plan_item",
        "core_update_project",
        "core_update_project_qna",
        "core_update_project_widget",
        "core_update_recurring_charge",
        "core_update_task",
        "core_update_task_date_time_batch",
        "core_update_transaction",
    ]
    assert names == expected


# ---------------------------------------------------------------- finance ---


@pytest.fixture()
def finance(repo):
    return FinanceService(repo, TZ)


def test_log_expense_normalises_category_and_defaults_to_today(finance):
    result = finance.log_transaction("Chai and samosa", 60, category="food")

    row = result["data"]["transaction"]
    assert row["category"] == "Food"  # snapped onto the canonical list
    assert row["currency"] == "INR"
    assert row["type"] == "expense"
    assert row["date"] == _today().isoformat()


def test_log_transaction_rejects_zero_and_negative_amounts(finance):
    for bad in (0, -250):
        with pytest.raises(PlannerCoreError, match="greater than zero"):
            finance.log_transaction("Refund gone wrong", bad)


def test_log_transaction_rejects_unknown_type(finance):
    with pytest.raises(PlannerCoreError, match="type must be"):
        finance.log_transaction("Mystery", 100, kind="transfer")


def test_log_transaction_rejects_unknown_goal(finance):
    with pytest.raises(PlannerCoreError, match="was not found"):
        finance.log_transaction("Savings", 5000, goal_id=str(uuid4()))


def test_summary_keeps_currencies_apart(finance):
    month = _today().replace(day=1).isoformat()
    finance.log_transaction("Groceries", 3000, category="Groceries", on_date=month)
    finance.log_transaction("Lunch", 500, category="Food", on_date=month)
    finance.log_transaction("Visa fee", 75, currency="EUR", category="Fees", on_date=month)
    finance.log_transaction("Salary", 90000, kind="income", on_date=month)

    data = finance.monthly_summary()["data"]

    inr, eur = data["currencies"]["INR"], data["currencies"]["EUR"]
    assert inr["expense"] == 3500.0
    assert inr["income"] == 90000.0
    assert inr["net"] == 86500.0
    # The euro fee must never be folded into the rupee total.
    assert eur["expense"] == 75.0
    assert eur["income"] == 0.0


def test_summary_ranks_categories_by_spend(finance):
    month = _today().replace(day=1).isoformat()
    finance.log_transaction("Rent", 20000, category="Rent", on_date=month)
    finance.log_transaction("Groceries", 4000, category="Groceries", on_date=month)
    finance.log_transaction("Chai", 1000, category="Food", on_date=month)

    inr = finance.monthly_summary()["data"]["currencies"]["INR"]

    assert [c["category"] for c in inr["by_category"]] == ["Rent", "Groceries", "Food"]
    assert inr["by_category"][0]["share_pct"] == 80.0


def test_summary_excludes_other_months(finance):
    this_month = _today().replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    finance.log_transaction("This month", 100, on_date=this_month.isoformat())
    finance.log_transaction("Last month", 999, on_date=last_month.isoformat())

    data = finance.monthly_summary(this_month.strftime("%Y-%m"))["data"]

    assert data["transaction_count"] == 1
    assert data["currencies"]["INR"]["expense"] == 100.0
    assert data["currencies"]["INR"]["previous_expense"] == 999.0


def test_goal_progress_adds_contributions_to_the_baseline(finance, repo):
    goal = repo.insert_row(
        "finance_goals",
        {"goal": "Blocked account", "target_amount": 12000, "saved_amount": 2000, "currency": "EUR"},
    )
    finance.log_transaction("Transfer", 1000, currency="EUR", goal_id=str(goal["id"]))

    tracked = finance.goal_progress()["data"]["goals"][0]

    assert tracked["baseline_amount"] == 2000.0
    assert tracked["contributed_amount"] == 1000.0
    assert tracked["saved_amount"] == 3000.0
    assert tracked["remaining_amount"] == 9000.0
    assert tracked["progress_pct"] == 25.0


def test_goal_progress_reports_other_currencies_separately(finance, repo):
    goal = repo.insert_row(
        "finance_goals",
        {"goal": "Blocked account", "target_amount": 12000, "saved_amount": 0, "currency": "EUR"},
    )
    finance.log_transaction("Rupee savings", 90000, currency="INR", goal_id=str(goal["id"]))

    tracked = finance.goal_progress()["data"]["goals"][0]

    # No exchange rate exists, so rupees must not inflate a euro goal.
    assert tracked["saved_amount"] == 0.0
    assert tracked["progress_pct"] == 0.0
    assert tracked["other_currency_contributions"] == {"INR": 90000.0}


# ----------------------------------------------------------- funding plan ---


@pytest.fixture()
def plan(finance, repo):
    """A plan priced in rupees at a round 100 to the euro, so a converted line
    is readable at a glance and the arithmetic below stays checkable."""
    repo.insert_row(
        "finance_plans",
        {"name": "Germany move", "base_currency": "INR", "eur_rate": 100},
    )
    return finance


def test_plan_overview_without_a_plan_says_so_rather_than_failing(finance):
    assert finance.plan_overview()["data"]["plan"] is None


def test_plan_separates_not_enough_money_from_not_enough_in_time(plan):
    plan.add_plan_item("cost", "Tuition instalment", 300000, due_date="2027-01-10")
    plan.add_plan_item("fund", "Fixed deposit matures", 350000, due_date="2027-03-01")

    totals = plan.plan_overview(as_of="2026-10-01")["data"]["totals"]

    # Enough money overall, but none of it lands before the January bill, so
    # the two numbers disagree on purpose.
    assert totals["gap"] == 50000.0
    assert totals["loan_needed"] == 300000.0
    assert totals["loan_by_month"] == "2027-01"
    assert totals["status"] == "amber"


def test_plan_is_red_when_the_money_does_not_cover_the_costs(plan):
    plan.add_plan_item("cost", "Tuition", 500000, due_date="2027-01-10")
    plan.add_plan_item("fund", "Savings", 200000)

    totals = plan.plan_overview(as_of="2026-10-01")["data"]["totals"]

    assert totals["gap"] == -300000.0
    assert totals["status"] == "red"


def test_plan_is_green_when_the_money_is_already_in_hand(plan):
    plan.add_plan_item("cost", "IELTS", 17000, due_date="2027-01-10")
    plan.add_plan_item("fund", "Current savings", 50000)  # no date: in the bank

    totals = plan.plan_overview(as_of="2026-10-01")["data"]["totals"]

    assert totals["status"] == "green"
    assert totals["loan_needed"] == 0.0


def test_spending_logged_against_a_line_reduces_what_is_left_to_fund(plan):
    item = plan.add_plan_item("cost", "APS certificate", 20000, due_date="2027-01-10")["data"]["item"]
    plan.log_transaction("APS application fee", 8000, plan_item_id=str(item["id"]))

    data = plan.plan_overview(as_of="2026-10-01")["data"]
    cost = data["costs"][0]

    assert cost["estimate"] == 20000.0
    assert cost["settled"] == 8000.0
    assert cost["outstanding"] == 12000.0
    assert cost["progress_pct"] == 40.0
    assert data["totals"]["cost_paid"] == 8000.0


def test_overspending_a_cost_is_reported_rather_than_swallowed(plan):
    item = plan.add_plan_item("cost", "IELTS", 17000, due_date="2027-01-10")["data"]["item"]
    plan.log_transaction("IELTS booking", 32000, plan_item_id=str(item["id"]))

    data = plan.plan_overview(as_of="2026-10-01")["data"]
    cost = data["costs"][0]

    assert cost["over_by"] == 15000.0
    assert data["totals"]["cost_overspend"] == 15000.0
    # The extra has already left the account, so it must not also be counted
    # as still owing, or the shortfall would double it.
    assert cost["outstanding"] == 0.0
    assert cost["progress_pct"] == 100.0
    assert data["timeline"]["months"] == []


def test_a_refund_against_a_cost_line_gives_the_money_back(plan):
    item = plan.add_plan_item("cost", "Exam fee", 20000, due_date="2027-01-10")["data"]["item"]
    plan.log_transaction("Exam fee", 20000, plan_item_id=str(item["id"]))
    plan.log_transaction(
        "Exam cancelled, part refunded", 5000, kind="income", plan_item_id=str(item["id"])
    )

    cost = plan.plan_overview(as_of="2026-10-01")["data"]["costs"][0]

    assert cost["settled"] == 15000.0
    assert cost["outstanding"] == 5000.0


def test_instalments_already_banked_drop_off_the_front_of_the_schedule(plan):
    item = plan.add_plan_item(
        "fund", "Monthly saving", 40000, due_date="2026-10-01", instalments=10
    )["data"]["item"]
    plan.log_transaction("October saving", 40000, kind="income", plan_item_id=str(item["id"]))
    plan.log_transaction("November saving", 40000, kind="income", plan_item_id=str(item["id"]))

    data = plan.plan_overview(as_of="2026-12-01")["data"]
    months = [m["month"] for m in data["timeline"]["months"]]

    assert data["funds"][0]["outstanding"] == 320000.0
    # Two of the ten are already in the bank, so eight months are still to
    # come — not ten smaller ones.
    assert months == [
        "2026-12", "2027-01", "2027-02", "2027-03",
        "2027-04", "2027-05", "2027-06", "2027-07",
    ]


def test_euro_lines_convert_at_the_plans_own_rate(plan):
    plan.add_plan_item("cost", "Blocked account", 11904, currency="EUR", due_date="2027-02-01")

    data = plan.plan_overview(as_of="2026-10-01")["data"]

    assert data["costs"][0]["estimate"] == 1190400.0
    assert data["totals"]["eur_rate"] == 100.0


def test_an_overdue_cost_moves_to_the_current_month(plan):
    plan.add_plan_item("cost", "Fee that slipped", 5000, due_date="2026-08-01")

    timeline = plan.plan_overview(as_of="2026-10-15")["data"]["timeline"]

    # Leaving it in August would put the low point in the past, where no loan
    # can reach it.
    assert [m["month"] for m in timeline["months"]] == ["2026-10"]


def test_undated_costs_count_towards_the_gap_but_are_flagged_as_unplaced(plan):
    plan.add_plan_item("cost", "Flights, dates not booked", 60000)
    plan.add_plan_item("fund", "Savings", 100000)

    data = plan.plan_overview(as_of="2026-10-01")["data"]

    assert data["totals"]["cost_outstanding"] == 60000.0
    assert data["totals"]["gap"] == 40000.0
    assert data["timeline"]["months"] == []
    assert [c["label"] for c in data["timeline"]["undated_costs"]] == ["Flights, dates not booked"]


def test_the_confirmed_only_view_drops_funding_that_is_not_committed(plan):
    plan.add_plan_item("cost", "Tuition", 300000, due_date="2027-01-10")
    plan.add_plan_item("fund", "Savings", 100000, certainty="confirmed")
    plan.add_plan_item("fund", "Hoping for a bonus", 250000, certainty="maybe")

    optimistic = plan.plan_overview(as_of="2026-10-01")["data"]["totals"]
    conservative = plan.plan_overview(
        as_of="2026-10-01", include_unconfirmed=False
    )["data"]["totals"]

    assert optimistic["gap"] == 50000.0
    assert conservative["gap"] == -200000.0
    assert conservative["status"] == "red"


def test_plan_items_sort_undated_costs_last_and_undated_funding_first(plan):
    plan.add_plan_item("cost", "Undated cost", 1000)
    plan.add_plan_item("cost", "Dated cost", 1000, due_date="2027-01-01")
    plan.add_plan_item("fund", "Undated funding", 1000)
    plan.add_plan_item("fund", "Dated funding", 1000, due_date="2027-01-01")

    data = plan.plan_overview(as_of="2026-10-01")["data"]

    assert [c["label"] for c in data["costs"]] == ["Dated cost", "Undated cost"]
    assert [f["label"] for f in data["funds"]] == ["Undated funding", "Dated funding"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "maybe", "label": "Something", "amount": 100},
        {"kind": "cost", "label": "  ", "amount": 100},
        {"kind": "cost", "label": "Something", "amount": 0},
        {"kind": "cost", "label": "Something", "amount": 100, "certainty": "hopeful"},
        {"kind": "cost", "label": "Something", "amount": 100, "instalments": 0},
    ],
)
def test_add_plan_item_refuses_values_the_database_would_reject(plan, kwargs):
    with pytest.raises(PlannerCoreError):
        plan.add_plan_item(
            kwargs.pop("kind"), kwargs.pop("label"), kwargs.pop("amount"), **kwargs
        )


def test_log_transaction_rejects_an_unknown_plan_line(plan):
    with pytest.raises(PlannerCoreError, match="Plan line was not found"):
        plan.log_transaction("Mystery fee", 500, plan_item_id=str(uuid4()))


def test_updating_the_plans_rate_reprices_every_euro_line(plan):
    plan.add_plan_item("cost", "Blocked account", 11904, currency="EUR", due_date="2027-02-01")

    plan.update_plan({"eur_rate": 105})
    data = plan.plan_overview(as_of="2026-10-01")["data"]

    assert data["costs"][0]["estimate"] == 1249920.0


def test_monthly_recurring_clamps_to_a_short_month(finance):
    finance.add_recurring(
        "Rent", 25000, cadence="monthly", day_of_month=31,
        category="Rent", start_date="2027-01-31",
    )

    posted = finance.materialize_recurring("2027-03-05")["data"]["created"]

    # The 31st does not exist in February, so rent posts on the 28th. March's
    # 31st has not arrived yet on the 5th, so it is not posted early.
    assert {r["date"] for r in posted} == {"2027-01-31", "2027-02-28"}


def test_recurring_does_not_post_twice(finance):
    finance.add_recurring("Netflix", 649, cadence="monthly", day_of_month=1, start_date="2027-01-01")

    first = finance.materialize_recurring("2027-02-10")["data"]["created"]
    again = finance.materialize_recurring("2027-02-10")["data"]["created"]

    assert len(first) == 2  # January and February
    assert again == []  # a second cron run charges nothing


def test_recurring_stops_after_end_date(finance):
    finance.add_recurring(
        "Gym", 1500, cadence="monthly", day_of_month=5,
        start_date="2027-01-05", end_date="2027-02-05",
    )

    posted = finance.materialize_recurring("2027-02-20")["data"]["created"]

    assert {r["date"] for r in posted} == {"2027-01-05", "2027-02-05"}


def test_recurring_catch_up_is_bounded_by_the_lookback_window(finance):
    """Adding a rule with an old start date must not retroactively post a
    year of charges — only the recent window is filled in."""
    finance.add_recurring(
        "Rent", 25000, cadence="monthly", day_of_month=1, start_date="2026-01-01",
    )

    posted = finance.materialize_recurring("2027-03-10")["data"]["created"]

    assert {r["date"] for r in posted} == {"2027-02-01", "2027-03-01"}


def test_weekly_recurring_posts_on_the_chosen_weekday(finance):
    # 2027-03-01 is a Monday.
    finance.add_recurring(
        "Cleaner", 500, cadence="weekly", day_of_week=0, start_date="2027-03-01",
    )

    posted = finance.materialize_recurring("2027-03-22")["data"]["created"]

    assert {r["date"] for r in posted} == {"2027-03-01", "2027-03-08", "2027-03-15", "2027-03-22"}


def test_inactive_recurring_charges_are_skipped(finance):
    created = finance.add_recurring(
        "Old subscription", 199, cadence="monthly", day_of_month=1, start_date="2027-01-01",
    )["data"]["recurring"]
    finance.update_recurring(str(created["id"]), {"active": False})

    assert finance.materialize_recurring("2027-02-10")["data"]["created"] == []


def test_recurring_rejects_a_bad_cadence(finance):
    with pytest.raises(PlannerCoreError, match="cadence must be"):
        finance.add_recurring("Nonsense", 100, cadence="fortnightly")


def test_recurring_rejects_end_before_start(finance):
    with pytest.raises(PlannerCoreError, match="end_date cannot be before"):
        finance.add_recurring("Backwards", 100, start_date="2027-05-01", end_date="2027-04-01")


def test_list_transactions_is_newest_first_and_filterable(finance):
    finance.log_transaction("Older", 100, category="Food", on_date="2027-01-01")
    finance.log_transaction("Newer", 200, category="Food", on_date="2027-01-05")
    finance.log_transaction("Transport", 50, category="Transport", on_date="2027-01-03")

    rows = finance.list_transactions()["data"]["transactions"]
    assert [r["description"] for r in rows] == ["Newer", "Transport", "Older"]

    food = finance.list_transactions(category="Food")["data"]["transactions"]
    assert {r["description"] for r in food} == {"Older", "Newer"}

    windowed = finance.list_transactions(start="2027-01-02", end="2027-01-04")["data"]["transactions"]
    assert [r["description"] for r in windowed] == ["Transport"]


# ------------------------------------------------- egress optimisations ---


def test_week_view_ignores_tasks_outside_the_week(services):
    tasks, _, _, _ = services
    monday = _today() - timedelta(days=_today().weekday())

    tasks.create_task("This week", scheduled_date=(monday + timedelta(days=2)).isoformat())
    tasks.create_task("Next month", scheduled_date=(monday + timedelta(days=40)).isoformat())
    tasks.create_task("Deadline in 2027", due_date="2027-07-31")

    titles = [item["title"] for item in tasks.week_view()["data"]["items"]]

    assert titles == ["This week"]


def test_the_week_shows_slots_and_leaves_out_the_task_they_came_from(services):
    tasks, _, _, _ = services
    day = (_today() - timedelta(days=_today().weekday())).isoformat()

    parent = tasks.create_task("Learn German", scheduled_date=day)["data"]["task"]
    tasks.create_task(
        "German slot", scheduled_date=day, start_time="09:00", parent_task_id=parent["id"]
    )

    titles = [item["title"] for item in tasks.week_view()["data"]["items"]]

    assert titles == ["German slot"]


def test_a_task_with_no_slots_is_its_own_slot(services):
    """Splitting is opt-in: an ordinary task still shows on the timeline and
    the calendar without needing a slot created under it."""
    tasks, _, _, _ = services
    day = _today().isoformat()

    tasks.create_task("Call the landlord", scheduled_date=day, start_time="10:00")

    titles = [item["title"] for item in tasks.day_view(day)["data"]["items"]]

    assert titles == ["Call the landlord"]


def test_the_day_shows_a_split_task_as_its_sittings_only(services):
    """Mirrors the study plan: a 90 minute task split into two 45 minute
    sittings must read as 90 minutes, not 180, and must not put a spare
    block on the calendar."""
    tasks, _, _, _ = services
    day = _today().isoformat()

    task = tasks.create_task(
        "Limits: limit laws", scheduled_date=day, start_time="16:00", estimated_minutes=90
    )["data"]["task"]
    for name, at in (("Session 1", "11:35"), ("Session 2", "15:00")):
        tasks.create_task(
            f"Limits: limit laws ({name})",
            scheduled_date=day,
            start_time=at,
            estimated_minutes=45,
            parent_task_id=task["id"],
        )

    items = tasks.day_view(day)["data"]["items"]

    assert [item["title"] for item in items] == [
        "Limits: limit laws (Session 1)",
        "Limits: limit laws (Session 2)",
    ]
    assert sum(item["estimated_minutes"] for item in items) == 90


def test_a_slot_can_be_moved_to_any_day(services):
    """Slots are peers, not dependents — moving one leaves the rest where
    they are instead of raising or dragging them along."""
    tasks, _, _, _ = services
    parent = tasks.create_task("Learn German", scheduled_date="2027-03-01")["data"]["task"]
    child = tasks.create_task(
        "Slot", scheduled_date="2027-03-01", parent_task_id=parent["id"]
    )["data"]["task"]

    tasks.update_task(child["id"], {"scheduled_date": "2027-03-05"})

    by_id = {t["id"]: t for t in tasks.list_tasks()["data"]["tasks"]}
    assert by_id[child["id"]]["scheduled_date"] == "2027-03-05"
    assert by_id[parent["id"]]["scheduled_date"] == "2027-03-01"


def test_finishing_every_slot_finishes_the_task_it_was_split_from(services):
    tasks, _, _, _ = services
    parent = tasks.create_task("Learn German", scheduled_date="2027-03-01")["data"]["task"]
    first = tasks.create_task(
        "Slot A", scheduled_date="2027-03-01", parent_task_id=parent["id"]
    )["data"]["task"]
    second = tasks.create_task(
        "Slot B", scheduled_date="2027-03-02", parent_task_id=parent["id"]
    )["data"]["task"]

    tasks.complete_task(first["id"])
    by_id = {t["id"]: t for t in tasks.list_tasks()["data"]["tasks"]}
    assert by_id[parent["id"]]["status"] == "todo"  # one slot left

    tasks.complete_task(second["id"])
    by_id = {t["id"]: t for t in tasks.list_tasks()["data"]["tasks"]}
    assert by_id[parent["id"]]["status"] == "done"

    # ...and un-ticking either slot reopens it again
    tasks.reopen_task(second["id"])
    by_id = {t["id"]: t for t in tasks.list_tasks()["data"]["tasks"]}
    assert by_id[parent["id"]]["status"] == "todo"


def test_ticking_a_split_task_closes_all_of_its_slots(services):
    tasks, _, _, _ = services
    parent = tasks.create_task("Learn German", scheduled_date="2027-03-01")["data"]["task"]
    for name in ("Slot A", "Slot B"):
        tasks.create_task(name, scheduled_date="2027-03-01", parent_task_id=parent["id"])

    tasks.complete_task(parent["id"])

    statuses = {t["title"]: t["status"] for t in tasks.list_tasks()["data"]["tasks"]}
    assert statuses == {"Learn German": "done", "Slot A": "done", "Slot B": "done"}


def test_a_split_task_counts_once_and_clears_when_its_slots_are_done(services):
    """The counts follow the task, not its slots, so splitting work into three
    sittings does not turn one job into three."""
    tasks, projects, metrics, _ = services
    project = projects.create_project("Germany Move")["data"]["project"]
    parent = tasks.create_task(
        "Learn German", project_id=project["id"], scheduled_date="2027-03-01"
    )["data"]["task"]
    slots = [
        tasks.create_task(
            name,
            project_id=project["id"],
            scheduled_date="2027-03-01",
            parent_task_id=parent["id"],
        )["data"]["task"]
        for name in ("Slot A", "Slot B")
    ]

    snapshot = metrics.snapshot()
    card = snapshot["projects"][0]
    assert card["total_tasks"] == 1 and card["open_tasks"] == 1
    assert snapshot["totals"]["open_tasks"] == 1

    for slot in slots:
        tasks.complete_task(slot["id"])

    snapshot = metrics.snapshot()
    card = snapshot["projects"][0]
    assert card["total_tasks"] == 1
    assert card["open_tasks"] == 0
    assert card["completion_pct"] == 100.0
    assert snapshot["totals"]["open_tasks"] == 0
    assert snapshot["totals"]["overdue_tasks"] == 0


def test_metrics_counts_match_between_the_rollup_and_a_full_scan(services):
    tasks, projects, metrics, _ = services
    project = projects.create_project("Germany Move")["data"]["project"]
    pid = project["id"]

    done = tasks.create_task("Done one", project_id=pid)["data"]["task"]
    tasks.complete_task(done["id"])
    tasks.create_task("Open one", project_id=pid)
    tasks.create_task("Stale", project_id=pid, scheduled_date="2020-01-01")
    skipped = tasks.create_task("Skipped", project_id=pid)["data"]["task"]
    tasks.update_task(skipped["id"], {"status": "skipped"})

    today = _today()
    rolled_up = metrics._task_counts(today)
    scanned = metrics._task_counts_by_scan(today)

    assert rolled_up == scanned
    assert rolled_up[str(pid)]["done"] == 1
    assert rolled_up[str(pid)]["open"] == 2  # Open one + Stale
    assert rolled_up[str(pid)]["total"] == 3  # the skipped one does not count
    # Both count: the 2020 one is past, and Open one has no date at all.
    assert rolled_up[str(pid)]["overdue"] == 2


def test_metrics_snapshot_totals_survive_the_rollup(services):
    tasks, projects, metrics, _ = services
    project = projects.create_project("Germany Move")["data"]["project"]
    pid = project["id"]

    tasks.create_task("Old and open", project_id=pid, scheduled_date="2020-01-01")
    tasks.create_task("Fine", project_id=pid, scheduled_date=_today().isoformat())

    snapshot = metrics.snapshot()

    assert snapshot["totals"]["open_tasks"] == 2
    # "Fine" is scheduled today, so it is not overdue; "Old and open" is.
    assert snapshot["totals"]["overdue_tasks"] == 1
    assert [t["title"] for t in snapshot["totals"]["overdue_list"]] == ["Old and open"]
    assert snapshot["totals"]["overdue_list_truncated"] is False
    assert snapshot["projects"][0]["total_tasks"] == 2


def test_dateless_overdue_tasks_survive_a_full_dated_backlog(services):
    """The whole point of counting dateless tasks is not to lose them. Even
    with more dated-overdue tasks than the list can hold, the loose ones must
    still appear — a server-side limit applied before sorting used to drop
    them."""
    tasks, projects, metrics, _ = services
    project = projects.create_project("Backlog")["data"]["project"]
    pid = project["id"]

    for i in range(OVERDUE_LIST_LIMIT + 5):
        tasks.create_task(f"Old {i}", project_id=pid, scheduled_date="2020-01-01")
    tasks.create_task("Loose one", project_id=pid)  # no date at all

    titles = [t["title"] for t in metrics._overdue_tasks(_today())]
    assert "Loose one" in titles, "a dateless task was lost behind the dated backlog"


def test_a_task_with_no_date_at_all_is_overdue(services):
    """A loose task with neither a due date nor a planned day used to float:
    never overdue, never surfaced. It now counts, so nothing goes missing."""
    tasks, projects, metrics, _ = services
    project = projects.create_project("Loose")["data"]["project"]
    pid = project["id"]

    tasks.create_task("No date at all", project_id=pid)  # no due, no scheduled

    snapshot = metrics.snapshot()
    assert snapshot["totals"]["overdue_tasks"] == 1
    assert [t["title"] for t in snapshot["totals"]["overdue_list"]] == ["No date at all"]
    assert metrics._task_counts(_today()) == metrics._task_counts_by_scan(_today())


def test_a_future_task_is_never_overdue(services):
    tasks, projects, metrics, _ = services
    project = projects.create_project("Future")["data"]["project"]
    pid = project["id"]

    tasks.create_task("Next week", project_id=pid,
                      scheduled_date=(_today() + timedelta(days=7)).isoformat())
    tasks.create_task("Due next month", project_id=pid,
                      due_date=(_today() + timedelta(days=30)).isoformat())

    snapshot = metrics.snapshot()
    assert snapshot["totals"]["overdue_tasks"] == 0
    assert snapshot["totals"]["overdue_list"] == []


def test_dateless_overdue_tasks_sort_below_the_dated_ones(services):
    """A genuinely late task has a deadline to measure; a dateless one does
    not, so the dated-and-late tasks are shown first with the oldest on top."""
    tasks, projects, metrics, _ = services
    project = projects.create_project("Mixed")["data"]["project"]
    pid = project["id"]

    tasks.create_task("Loose", project_id=pid)
    tasks.create_task("Newer miss", project_id=pid, scheduled_date="2021-06-01")
    tasks.create_task("Oldest miss", project_id=pid, due_date="2020-01-01")

    titles = [t["title"] for t in metrics.snapshot()["totals"]["overdue_list"]]
    assert titles == ["Oldest miss", "Newer miss", "Loose"]


def test_overdue_list_is_capped_but_the_count_is_not(services):
    tasks, projects, metrics, _ = services
    project = projects.create_project("Backlog")["data"]["project"]

    for i in range(OVERDUE_LIST_LIMIT + 25):
        tasks.create_task(f"Stale {i}", project_id=project["id"], scheduled_date="2020-01-01")

    snapshot = metrics.snapshot()

    # The dashboard renders the list, so it is bounded; the headline number
    # must still be the true total.
    assert len(snapshot["totals"]["overdue_list"]) == OVERDUE_LIST_LIMIT
    assert snapshot["totals"]["overdue_tasks"] == OVERDUE_LIST_LIMIT + 25
    assert snapshot["totals"]["overdue_list_truncated"] is True


def test_upcoming_deadlines_only_reach_the_horizon(services):
    tasks, _, metrics, _ = services
    today = _today()
    tasks.create_task("Soon", due_date=(today + timedelta(days=5)).isoformat())
    tasks.create_task("Far off", due_date=(today + timedelta(days=90)).isoformat())

    names = [d["name"] for d in metrics.snapshot()["upcoming_deadlines"] if d["kind"] == "task"]

    assert names == ["Soon"]


def _milestone_with_progress(tasks, projects, name, *, start, target, total, done):
    """A milestone whose tasks span start..target, with `done` of them ticked."""
    project = projects.create_project(name)["data"]["project"]
    milestone = projects.add_milestone(
        project["id"], f"{name} milestone", target_date=target.isoformat(),
        start_date=start.isoformat(),
    )["data"]["milestone"]
    for i in range(total):
        task = tasks.create_task(
            f"{name} {i}",
            project_id=project["id"],
            milestone_id=milestone["id"],
            scheduled_date=start.isoformat(),
        )["data"]["task"]
        if i < done:
            tasks.complete_task(task["id"])
    return milestone


def _health_for(metrics, milestone_id):
    rows = metrics.snapshot()["milestone_health"]
    return next(r for r in rows if r["milestone_id"] == milestone_id)


def test_milestone_health_rates_progress_against_time_spent(services):
    """Green while progress keeps up with the schedule, amber when it slips,
    red when it falls badly behind — the thresholds the dashboard rates on."""
    tasks, projects, metrics, _ = services
    today = _today()
    # A 100 day window with 50 days gone: half the schedule spent.
    start, target = today - timedelta(days=50), today + timedelta(days=50)

    on_track = _milestone_with_progress(
        tasks, projects, "OnTrack", start=start, target=target, total=4, done=2
    )
    slipping = _milestone_with_progress(
        tasks, projects, "Slipping", start=start, target=target, total=10, done=3
    )
    at_risk = _milestone_with_progress(
        tasks, projects, "AtRisk", start=start, target=target, total=4, done=0
    )

    # Half done at half time: no drift.
    assert _health_for(metrics, on_track["id"])["status"] == "green"
    # 30% done at half time: 0.20 drift, past the amber threshold.
    assert _health_for(metrics, slipping["id"])["status"] == "amber"
    # Nothing done at half time: 0.50 drift, well past red.
    assert _health_for(metrics, at_risk["id"])["status"] == "red"


def test_milestone_health_flags_a_passed_target_date_as_overdue(services):
    tasks, projects, metrics, _ = services
    today = _today()
    late = _milestone_with_progress(
        tasks, projects, "Late",
        start=today - timedelta(days=30), target=today - timedelta(days=1),
        total=2, done=1,
    )

    assert _health_for(metrics, late["id"])["status"] == "overdue"


def test_milestone_health_leaves_out_finished_and_empty_milestones(services):
    """A milestone with every task ticked reads complete rather than overdue,
    and one with no tasks at all is not rated — there is nothing to measure."""
    tasks, projects, metrics, _ = services
    today = _today()
    finished = _milestone_with_progress(
        tasks, projects, "Finished",
        start=today - timedelta(days=30), target=today - timedelta(days=1),
        total=2, done=2,
    )
    empty_project = projects.create_project("Empty")["data"]["project"]
    empty = projects.add_milestone(
        empty_project["id"], "No tasks yet", target_date=today.isoformat()
    )["data"]["milestone"]

    rows = metrics.snapshot()["milestone_health"]

    assert _health_for(metrics, finished["id"])["status"] == "complete"
    assert all(r["milestone_id"] != empty["id"] for r in rows)


def test_milestone_health_prefers_an_explicit_start_date(services):
    """Without a start date the earliest task stands in, but an explicit one
    wins — it is what makes the elapsed share meaningful."""
    tasks, projects, metrics, _ = services
    today = _today()
    project = projects.create_project("Explicit")["data"]["project"]
    milestone = projects.add_milestone(
        project["id"], "Long run",
        target_date=(today + timedelta(days=50)).isoformat(),
        start_date=(today - timedelta(days=50)).isoformat(),
    )["data"]["milestone"]
    # The only task sits today, so a derived start would make elapsed 0.
    tasks.create_task(
        "Only task", project_id=project["id"], milestone_id=milestone["id"],
        scheduled_date=today.isoformat(),
    )

    row = _health_for(metrics, milestone["id"])

    assert row["start_date"] == (today - timedelta(days=50)).isoformat()
    assert row["elapsed"] == 0.5


def test_a_task_carries_its_projects_own_columns(services):
    """The study plan tracks Subject and Source, which no fixed field covers.
    They ride along on the task so the project view can read them back."""
    tasks, _, _, _ = services

    task = tasks.create_task(
        "Limits: limit laws",
        metadata={"Subject": "Calculus refresh", "Source": "Paul's Online Math Notes"},
    )["data"]["task"]

    assert task["metadata"]["Subject"] == "Calculus refresh"

    tasks.update_task(task["id"], {"metadata": {"Subject": "Linear algebra"}})
    stored = [t for t in tasks.list_tasks()["data"]["tasks"] if t["id"] == task["id"]][0]

    assert stored["metadata"] == {"Subject": "Linear algebra"}


# ---------------------------------------------------------------------------
# habits
# ---------------------------------------------------------------------------

@pytest.fixture()
def habits(repo):
    return HabitService(repo, TZ)


def test_a_daily_habit_appears_every_day_without_storing_a_row(habits, repo):
    """The whole point: gym used to be 295 pre-generated rows, every missed
    one overdue for ever. It is one rule now."""
    habits.add_habit("Gym", start_time="07:00", estimated_minutes=45, start_date="2026-09-01")

    days = habits.occurrences(date(2026, 9, 1), date(2026, 9, 7))

    assert len(days) == 7
    assert {item["title"] for item in days} == {"Gym"}
    assert days[0]["start_time"] == "07:00"
    assert all(item["is_habit"] for item in days)
    # one rule row, and nothing generated per day
    assert len(repo.list_rows("habits")) == 1
    assert repo.list_rows("planner_tasks") == []


def test_a_weekly_habit_only_lands_on_its_days(habits):
    # 0=Sunday, so 1 and 3 are Monday and Wednesday.
    habits.add_habit(
        "Piano", cadence="weekly", days_of_week=[1, 3], start_date="2026-09-01"
    )

    days = habits.occurrences(date(2026, 9, 1), date(2026, 9, 14))

    # Sept 1 2026 is a Tuesday, so the first Monday is the 7th.
    assert [item["scheduled_date"] for item in days] == [
        "2026-09-02", "2026-09-07", "2026-09-09", "2026-09-14",
    ]


def test_a_weekly_habit_needs_days_and_the_cadence_must_be_known(habits):
    with pytest.raises(PlannerCoreError, match="at least one day"):
        habits.add_habit("Piano", cadence="weekly")
    with pytest.raises(PlannerCoreError, match="Invalid cadence"):
        habits.add_habit("Piano", cadence="fortnightly")


def test_one_day_can_be_moved_without_disturbing_the_rest(habits):
    habit = habits.add_habit("Gym", start_time="07:00", start_date="2026-09-01")["data"]["habit"]

    habits.reschedule_occurrence(habit["id"], date(2026, 9, 2), moved_to="2026-09-03", start_time="18:00")

    week = habits.occurrences(date(2026, 9, 1), date(2026, 9, 4))
    by_day: dict[str, list[dict]] = {}
    for item in week:
        by_day.setdefault(item["scheduled_date"], []).append(item)

    assert "2026-09-02" not in by_day                     # left its own day
    assert len(by_day["2026-09-03"]) == 2                 # and landed alongside the 3rd's
    moved = [i for i in by_day["2026-09-03"] if i["start_time"] == "18:00"]
    assert len(moved) == 1
    assert by_day["2026-09-01"][0]["start_time"] == "07:00"   # rule untouched
    assert by_day["2026-09-04"][0]["start_time"] == "07:00"


def test_skipping_a_day_removes_only_that_day(habits):
    habit = habits.add_habit("Gym", start_date="2026-09-01")["data"]["habit"]

    habits.skip_occurrence(habit["id"], date(2026, 9, 2))

    dates = [i["scheduled_date"] for i in habits.occurrences(date(2026, 9, 1), date(2026, 9, 3))]
    assert dates == ["2026-09-01", "2026-09-03"]


def test_ticking_a_day_feeds_the_streak_and_survives_a_reopen(habits, repo):
    habit = habits.add_habit("Gym", recurrence_key="gym", start_date="2026-09-01")["data"]["habit"]

    habits.complete_occurrence(habit["id"], date(2026, 9, 1))
    habits.complete_occurrence(habit["id"], date(2026, 9, 1))  # twice must not double-log

    logged = repo.list_rows("task_completions")
    assert len(logged) == 1
    assert logged[0]["recurrence_key"] == "gym"

    done = {i["scheduled_date"]: i["done"] for i in habits.occurrences(date(2026, 9, 1), date(2026, 9, 2))}
    assert done == {"2026-09-01": True, "2026-09-02": False}

    habits.reopen_occurrence(habit["id"], date(2026, 9, 1))
    assert repo.list_rows("task_completions") == []


def test_a_moved_day_is_ticked_on_the_day_it_moved_to(habits, repo):
    """The completion has to follow the occurrence, or the streak records a
    day you did not do it and misses the one you did."""
    habit = habits.add_habit("Gym", recurrence_key="gym", start_date="2026-09-01")["data"]["habit"]
    habits.reschedule_occurrence(habit["id"], date(2026, 9, 2), moved_to="2026-09-03")

    habits.complete_occurrence(habit["id"], date(2026, 9, 2))

    assert repo.list_rows("task_completions")[0]["completed_on"] == "2026-09-03"


def test_habits_never_reach_the_overdue_list_or_the_open_count(habits, services):
    """A habit from months ago is not owed. This is the bug the whole thing
    was built to kill."""
    tasks, _, metrics, _ = services
    habits.add_habit("Gym", start_date="2026-01-01")
    tasks.create_task("File the visa form", scheduled_date="2026-01-01")

    totals = metrics.snapshot()["totals"]

    assert totals["overdue_tasks"] == 1  # the visa form, and nothing else
    assert [row["title"] for row in totals["overdue_list"]] == ["File the visa form"]
    assert totals["open_tasks"] == 1


def test_the_day_view_shows_habits_beside_tasks_in_time_order(repo, habits):
    tasks = TaskService(repo, TZ, habits=habits)
    habits.add_habit("Gym", start_time="07:00", start_date="2026-09-01")
    tasks.create_task("Standup", scheduled_date="2026-09-01", start_time="09:30")

    items = tasks.day_view("2026-09-01")["data"]["items"]

    assert [item["title"] for item in items] == ["Gym", "Standup"]
    assert items[0]["id"].startswith("habit:")


def test_a_habit_item_id_survives_a_round_trip(habits):
    habit = habits.add_habit("Gym", start_date="2026-09-01")["data"]["habit"]
    item = habits.occurrences(date(2026, 9, 1), date(2026, 9, 1))[0]

    assert parse_habit_item_id(item["id"]) == (habit["id"], date(2026, 9, 1))
    assert parse_habit_item_id("not-a-habit-id") is None


def test_the_small_hours_of_the_next_day_still_belong_to_todays_view(services):
    """A day runs past midnight, so something rescheduled to 4am tomorrow has
    to stay on tonight's screen. 04:00 exactly used to fall out: the cutoff was
    a strict `< 04:00`, so dragging (which lands earlier) worked while editing
    the date to 4am made the task vanish from today.
    """
    tasks, _, _, _ = services
    tasks.create_task("Late night edit", scheduled_date="2026-09-15", start_time="04:00:00")
    tasks.create_task("Deep night", scheduled_date="2026-09-15", start_time="01:30:00")
    tasks.create_task("Properly tomorrow", scheduled_date="2026-09-15", start_time="09:00:00")

    items = tasks.day_view("2026-09-14")["data"]["items"]
    by_title = {i["title"]: i for i in items}

    assert "Late night edit" in by_title
    assert "Deep night" in by_title
    # Morning belongs to the next day alone, not to both.
    assert "Properly tomorrow" not in by_title
    # Spillover reads as hour + 24 so it sorts after the evening, not before
    # breakfast.
    assert by_title["Late night edit"]["start_time"] == "28:00:00"
    assert by_title["Deep night"]["start_time"] == "25:30:00"


# ---------------------------------------------------------------------------
# starred tasks — the few a day is judged by
# ---------------------------------------------------------------------------


def test_starring_marks_a_task_and_the_day_counts_them(services):
    tasks, _, _, _ = services
    day = _today().isoformat()
    a = tasks.create_task("Ship the thing", scheduled_date=day)["data"]["task"]
    tasks.create_task("Tidy inbox", scheduled_date=day)

    tasks.update_task(a["id"], {"starred": True})
    view = tasks.day_view(day)["data"]

    starred = [item for item in view["items"] if item.get("starred")]
    assert [item["title"] for item in starred] == ["Ship the thing"]
    assert view["starred_total"] == 1
    assert view["starred_done"] == 0

    tasks.complete_task(a["id"])
    assert tasks.day_view(day)["data"]["starred_done"] == 1


def test_a_day_refuses_more_stars_than_its_budget(services):
    """The cap is the feature: without it the stars become a second todo list
    and the day has no shape again."""
    tasks, _, _, _ = services
    day = _today().isoformat()
    made = [
        tasks.create_task(f"Task {i}", scheduled_date=day)["data"]["task"]
        for i in range(MAX_STARRED_PER_DAY + 1)
    ]
    for task in made[:MAX_STARRED_PER_DAY]:
        tasks.update_task(task["id"], {"starred": True})

    try:
        tasks.update_task(made[-1]["id"], {"starred": True})
    except PlannerCoreError as error:
        assert "Unstar one" in str(error)
    else:
        raise AssertionError("the budget should have refused the extra star")

    assert tasks.day_view(day)["data"]["starred_total"] == MAX_STARRED_PER_DAY


def test_restarring_an_already_starred_task_costs_nothing(services):
    """Saving a starred task again must not read as spending another slot."""
    tasks, _, _, _ = services
    day = _today().isoformat()
    made = [
        tasks.create_task(f"Task {i}", scheduled_date=day)["data"]["task"]
        for i in range(MAX_STARRED_PER_DAY)
    ]
    for task in made:
        tasks.update_task(task["id"], {"starred": True})

    tasks.update_task(made[0]["id"], {"starred": True})

    assert tasks.day_view(day)["data"]["starred_total"] == MAX_STARRED_PER_DAY


def test_a_starred_task_keeps_its_star_when_it_moves_to_another_day(services):
    """It did not stop mattering by being missed."""
    tasks, _, _, _ = services
    today = _today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    task = tasks.create_task("Ship the thing", scheduled_date=today.isoformat())["data"]["task"]
    tasks.update_task(task["id"], {"starred": True})

    tasks.update_task(task["id"], {"scheduled_date": tomorrow})

    assert tasks.day_view(today.isoformat())["data"]["starred_total"] == 0
    moved = tasks.day_view(tomorrow)["data"]
    assert moved["starred_total"] == 1


def test_milestone_health_ignores_a_start_date_after_its_target(services):
    """Work that slipped past its deadline leaves the earliest task sitting
    after the target, so a backfilled start can land the wrong side of it.
    Read literally that says the whole schedule is gone, which would mark a
    milestone at risk on the strength of a bad date rather than its progress.
    """
    tasks, projects, metrics, _ = services
    today = _today()
    project = projects.create_project("Slipped")["data"]["project"]
    milestone = projects.add_milestone(
        project["id"],
        "Ran late",
        target_date=(today + timedelta(days=20)).isoformat(),
        # After the target, and after every task below.
        start_date=(today + timedelta(days=60)).isoformat(),
    )["data"]["milestone"]
    for i in range(4):
        made = tasks.create_task(
            f"Bit {i}",
            project_id=project["id"],
            milestone_id=milestone["id"],
            scheduled_date=(today - timedelta(days=10)).isoformat(),
        )["data"]["task"]
        if i < 2:
            tasks.complete_task(made["id"])

    row = _health_for(metrics, milestone["id"])

    # Half done, a third of the way through the real span: on track, not red.
    assert row["status"] == "green"
    assert row["start_date"] == (today - timedelta(days=10)).isoformat()
