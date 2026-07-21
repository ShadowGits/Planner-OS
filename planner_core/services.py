"""Deterministic services over the v2 Postgres planner tables.

All decisions here are rule-based: what is due, what slipped, what completion
percentage a project has, whether a reminder should fire. Intelligence (what to
plan, how to phrase advice) stays with the AI client calling the MCP tools.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from planner_core.repository import PlannerCoreError, PlannerCoreRepository

OPEN_TASK_STATUSES = {"todo", "in_progress", "blocked"}
CLOSED_TASK_STATUSES = {"done", "skipped"}
TASK_STATUSES = OPEN_TASK_STATUSES | CLOSED_TASK_STATUSES
MILESTONE_STATUSES = {"not_started", "in_progress", "blocked", "done"}
PROJECT_STATUSES = {"active", "paused", "done", "archived"}
PRIORITIES = {"low", "medium", "high", "critical"}
DEADLINE_WINDOW_DAYS = 7


def _envelope(success: bool, message: str, data: dict[str, Any] | None = None, errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "success": success,
        "message": message,
        "data": data or {},
        "warnings": [],
        "errors": errors or [],
        "preview_id": None,
        "requires_confirmation": False,
        "operation": None,
        "target": None,
        "decision_id": None,
    }


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_time(value: Any) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _local_today(timezone: str) -> date:
    return datetime.now(ZoneInfo(timezone)).date()


class ProjectService:
    def __init__(self, repository: PlannerCoreRepository) -> None:
        self.repository = repository

    def create_project(
        self,
        name: str,
        *,
        track: str | None = None,
        description: str | None = None,
        target_date: str | None = None,
    ) -> dict[str, Any]:
        if not name.strip():
            raise PlannerCoreError("Project name is required")
        _parse_date(target_date)
        row = self.repository.insert_row(
            "projects",
            {"name": name.strip(), "track": track, "description": description, "target_date": target_date},
        )
        return _envelope(True, f"Project created: {row['name']}", {"project": row})

    def update_project(self, project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"name", "track", "description", "status", "target_date"}
        payload = {key: value for key, value in updates.items() if key in allowed}
        if not payload:
            raise PlannerCoreError(f"No valid project fields in update; allowed: {sorted(allowed)}")
        status = payload.get("status")
        if status is not None and status not in PROJECT_STATUSES:
            raise PlannerCoreError(f"Invalid project status: {status}")
        row = self.repository.update_row("projects", project_id, payload)
        return _envelope(True, f"Project updated: {row['name']}", {"project": row})

    def add_milestone(
        self,
        project_id: str,
        name: str,
        *,
        target_date: str | None = None,
        sort_order: int = 0,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if self.repository.get_row("projects", project_id) is None:
            raise PlannerCoreError(f"Project was not found: {project_id}")
        _parse_date(target_date)
        row = self.repository.insert_row(
            "milestones",
            {
                "project_id": project_id,
                "name": name.strip(),
                "target_date": target_date,
                "sort_order": sort_order,
                "notes": notes,
            },
        )
        return _envelope(True, f"Milestone added: {row['name']}", {"milestone": row})

    def update_milestone(self, milestone_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"name", "status", "target_date", "sort_order", "notes"}
        payload = {key: value for key, value in updates.items() if key in allowed}
        if not payload:
            raise PlannerCoreError(f"No valid milestone fields in update; allowed: {sorted(allowed)}")
        status = payload.get("status")
        if status is not None and status not in MILESTONE_STATUSES:
            raise PlannerCoreError(f"Invalid milestone status: {status}")
        row = self.repository.update_row("milestones", milestone_id, payload)
        return _envelope(True, f"Milestone updated: {row['name']}", {"milestone": row})

    def project_tree(self) -> dict[str, Any]:
        projects = self.repository.list_rows("projects")
        milestones = self.repository.list_rows("milestones")
        tasks = self.repository.list_rows("planner_tasks")
        by_project_milestones: dict[str, list[dict[str, Any]]] = {}
        for milestone in sorted(milestones, key=lambda row: (row.get("sort_order") or 0, str(row.get("target_date") or "9999"))):
            by_project_milestones.setdefault(str(milestone["project_id"]), []).append(milestone)
        open_by_project: dict[str, int] = {}
        done_by_project: dict[str, int] = {}
        for task in tasks:
            key = str(task.get("project_id") or "")
            if not key:
                continue
            if task["status"] in CLOSED_TASK_STATUSES:
                done_by_project[key] = done_by_project.get(key, 0) + 1
            else:
                open_by_project[key] = open_by_project.get(key, 0) + 1
        tree = []
        for project in sorted(projects, key=lambda row: str(row.get("target_date") or "9999")):
            key = str(project["id"])
            tree.append(
                {
                    **project,
                    "milestones": by_project_milestones.get(key, []),
                    "open_tasks": open_by_project.get(key, 0),
                    "done_tasks": done_by_project.get(key, 0),
                }
            )
        return _envelope(True, f"{len(tree)} projects", {"projects": tree})


class TaskService:
    def __init__(self, repository: PlannerCoreRepository, timezone: str = "UTC") -> None:
        self.repository = repository
        self.timezone = timezone

    def create_task(
        self,
        title: str,
        *,
        project_id: str | None = None,
        milestone_id: str | None = None,
        due_date: str | None = None,
        scheduled_date: str | None = None,
        start_time: str | None = None,
        priority: str = "medium",
        estimated_minutes: int | None = None,
        recurrence_key: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if not title.strip():
            raise PlannerCoreError("Task title is required")
        if priority not in PRIORITIES:
            raise PlannerCoreError(f"Invalid priority: {priority}")
        _parse_date(due_date)
        _parse_date(scheduled_date)
        _parse_time(start_time)
        row = self.repository.insert_row(
            "planner_tasks",
            {
                "title": title.strip(),
                "project_id": project_id,
                "milestone_id": milestone_id,
                "due_date": due_date,
                "scheduled_date": scheduled_date,
                "start_time": start_time,
                "priority": priority,
                "estimated_minutes": estimated_minutes,
                "recurrence_key": recurrence_key,
                "notes": notes,
            },
        )
        return _envelope(True, f"Task created: {row['title']}", {"task": row})

    def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "title",
            "project_id",
            "milestone_id",
            "status",
            "priority",
            "due_date",
            "scheduled_date",
            "start_time",
            "estimated_minutes",
            "recurrence_key",
            "notes",
        }
        payload = {key: value for key, value in updates.items() if key in allowed}
        if not payload:
            raise PlannerCoreError(f"No valid task fields in update; allowed: {sorted(allowed)}")
        status = payload.get("status")
        if status is not None and status not in TASK_STATUSES:
            raise PlannerCoreError(f"Invalid task status: {status}")
        if "start_time" in payload:
            _parse_time(payload["start_time"])
        row = self.repository.update_row("planner_tasks", task_id, payload)
        return _envelope(True, f"Task updated: {row['title']}", {"task": row})

    def delete_task(self, task_id: str) -> dict[str, Any]:
        row = self.repository.get_row("planner_tasks", task_id)
        if row is None:
            raise PlannerCoreError(f"Task was not found: {task_id}")
        self.repository.delete_row("planner_tasks", task_id)
        return _envelope(True, f"Task deleted: {row['title']}", {"task": row})

    def complete_task(self, task_id: str, *, source: str = "mcp", note: str | None = None) -> dict[str, Any]:
        task = self.repository.get_row("planner_tasks", task_id)
        if task is None:
            raise PlannerCoreError(f"Task was not found: {task_id}")
        completed = self.repository.update_row(
            "planner_tasks",
            task_id,
            {"status": "done", "completed_at": datetime.now(ZoneInfo(self.timezone)).isoformat()},
        )
        self.repository.insert_row(
            "task_completions",
            {
                "task_id": task_id,
                "recurrence_key": task.get("recurrence_key"),
                "completed_on": _local_today(self.timezone).isoformat(),
                "source": source,
                "note": note,
            },
        )
        return _envelope(True, f"Done: {completed['title']}", {"task": completed})

    def complete_by_title(self, text: str, *, source: str = "mcp") -> dict[str, Any]:
        """Fuzzy-complete the best open-task match for free text (Telegram tick-back)."""
        needle = text.strip().casefold()
        if not needle:
            raise PlannerCoreError("Nothing to match: empty text")
        open_tasks = [
            row
            for row in self.repository.list_rows("planner_tasks")
            if row["status"] in OPEN_TASK_STATUSES
        ]
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in open_tasks:
            title = str(row["title"]).casefold()
            key = str(row.get("recurrence_key") or "").casefold()
            if needle == title or (key and needle == key):
                scored.append((3, row))
            elif needle in title or title in needle:
                scored.append((2, row))
            elif any(word in title for word in needle.split() if len(word) > 2):
                scored.append((1, row))
        if not scored:
            return _envelope(False, f"No open task matches: {text!r}", errors=["NO_MATCH"])
        scored.sort(key=lambda item: (-item[0], str(item[1].get("due_date") or "9999")))
        best_score = scored[0][0]
        best = [row for score, row in scored if score == best_score]
        if best_score < 3 and len(best) > 1:
            titles = [row["title"] for row in best[:5]]
            return _envelope(
                False,
                f"Ambiguous: {text!r} matches {titles}",
                {"candidates": titles},
                errors=["AMBIGUOUS_MATCH"],
            )
        return self.complete_task(str(best[0]["id"]), source=source, note=f"matched from: {text}")

    def today(self) -> dict[str, Any]:
        today = _local_today(self.timezone)
        rows = self.repository.list_rows("planner_tasks")
        scheduled, due, overdue = [], [], []
        for row in rows:
            if row["status"] in CLOSED_TASK_STATUSES:
                continue
            due_on = _parse_date(row.get("due_date"))
            planned = _parse_date(row.get("scheduled_date"))
            if planned == today:
                scheduled.append(row)
            if due_on == today:
                due.append(row)
            elif due_on is not None and due_on < today:
                overdue.append(row)
        completions = [
            row
            for row in self.repository.list_rows("task_completions")
            if _parse_date(row.get("completed_on")) == today
        ]
        return _envelope(
            True,
            f"{len(scheduled)} scheduled, {len(due)} due, {len(overdue)} overdue, {len(completions)} completed today",
            {
                "date": today.isoformat(),
                "scheduled": scheduled,
                "due_today": due,
                "overdue": sorted(overdue, key=lambda row: str(row.get("due_date"))),
                "completed_today": completions,
            },
        )

    def today_checklist(self) -> dict[str, Any]:
        """One flat list of today's tasks, each flagged done or not, for a
        tick-box view. A task belongs to today if it is scheduled today, due
        today, or was completed today; done tasks sort to the bottom."""
        today = _local_today(self.timezone)
        completed_task_ids = {
            str(row.get("task_id"))
            for row in self.repository.list_rows("task_completions")
            if _parse_date(row.get("completed_on")) == today and row.get("task_id")
        }
        items: list[dict[str, Any]] = []
        for row in self.repository.list_rows("planner_tasks"):
            due = _parse_date(row.get("due_date"))
            planned = _parse_date(row.get("scheduled_date"))
            is_done = row["status"] == "done" or str(row["id"]) in completed_task_ids
            belongs = planned == today or due == today or str(row["id"]) in completed_task_ids
            if not belongs:
                continue
            items.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "done": is_done,
                    "due_date": row.get("due_date"),
                    "priority": row.get("priority"),
                }
            )
        items.sort(key=lambda item: (item["done"], str(item.get("due_date") or "9999"), item["title"]))
        done_count = len([item for item in items if item["done"]])
        return _envelope(
            True,
            f"{done_count} of {len(items)} done today",
            {
                "date": today.isoformat(),
                "items": items,
                "done_count": done_count,
                "total_count": len(items),
            },
        )

    def reopen_task(self, task_id: str) -> dict[str, Any]:
        """Un-tick a task: back to todo and drop its completion rows for today,
        so checklists and metrics agree with the visible state."""
        task = self.repository.get_row("planner_tasks", task_id)
        if task is None:
            raise PlannerCoreError(f"Task was not found: {task_id}")
        row = self.repository.update_row(
            "planner_tasks", task_id, {"status": "todo", "completed_at": None}
        )
        today = _local_today(self.timezone)
        for completion in self.repository.list_rows("task_completions", {"task_id": task_id}):
            if _parse_date(completion.get("completed_on")) == today:
                self.repository.delete_row("task_completions", str(completion["id"]))
        return _envelope(True, f"Reopened: {row['title']}", {"task": row})

    def day_view(self, on_date: str | None = None) -> dict[str, Any]:
        """Tasks belonging to one date, shaped for a timeline: tasks with a
        start_time carry their slot, the rest form the unscheduled tray."""
        target = _parse_date(on_date) or _local_today(self.timezone)
        items: list[dict[str, Any]] = []
        for row in self.repository.list_rows("planner_tasks"):
            planned = _parse_date(row.get("scheduled_date"))
            due = _parse_date(row.get("due_date"))
            if planned != target and due != target:
                continue
            items.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "status": row["status"],
                    "done": row["status"] in CLOSED_TASK_STATUSES,
                    "start_time": row.get("start_time"),
                    "estimated_minutes": row.get("estimated_minutes"),
                    "priority": row.get("priority"),
                    "due_date": row.get("due_date"),
                    "scheduled_date": row.get("scheduled_date"),
                    "notes": row.get("notes"),
                    "project_id": row.get("project_id"),
                }
            )
        items.sort(
            key=lambda item: (
                item["start_time"] is None,
                str(item["start_time"] or ""),
                item["title"],
            )
        )
        done_count = len([item for item in items if item["done"]])
        return _envelope(
            True,
            f"{done_count} of {len(items)} done on {target.isoformat()}",
            {
                "date": target.isoformat(),
                "items": items,
                "done_count": done_count,
                "total_count": len(items),
            },
        )

    def list_tasks(self, *, status: str | None = None, project_id: str | None = None) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if status is not None:
            if status not in TASK_STATUSES:
                raise PlannerCoreError(f"Invalid task status: {status}")
            filters["status"] = status
        if project_id is not None:
            filters["project_id"] = project_id
        rows = self.repository.list_rows("planner_tasks", filters)
        rows.sort(key=lambda row: (str(row.get("due_date") or "9999"), str(row.get("created_at") or "")))
        return _envelope(True, f"{len(rows)} tasks", {"tasks": rows})


class MetricsService:
    """Aggregate dashboard-ready metrics from raw rows. Pure computation."""

    def __init__(self, repository: PlannerCoreRepository, timezone: str = "UTC") -> None:
        self.repository = repository
        self.timezone = timezone

    def snapshot(self) -> dict[str, Any]:
        today = _local_today(self.timezone)
        projects = self.repository.list_rows("projects")
        milestones = self.repository.list_rows("milestones")
        tasks = self.repository.list_rows("planner_tasks")
        completions = self.repository.list_rows("task_completions")

        project_metrics = [self._project_metrics(project, milestones, tasks, today) for project in projects]
        deadlines = self._upcoming_deadlines(milestones, tasks, today)
        streaks = self._streaks(completions, today)
        open_tasks = [task for task in tasks if task["status"] in OPEN_TASK_STATUSES]
        overdue = [
            task
            for task in open_tasks
            if (due := _parse_date(task.get("due_date"))) is not None and due < today
        ]
        completed_today = [row for row in completions if _parse_date(row.get("completed_on")) == today]
        return {
            "generated_on": today.isoformat(),
            "timezone": self.timezone,
            "projects": project_metrics,
            "upcoming_deadlines": deadlines,
            "streaks": streaks,
            "totals": {
                "open_tasks": len(open_tasks),
                "overdue_tasks": len(overdue),
                "completed_today": len(completed_today),
                "completions_last_7_days": len(
                    [
                        row
                        for row in completions
                        if (done := _parse_date(row.get("completed_on"))) is not None
                        and today - timedelta(days=6) <= done <= today
                    ]
                ),
            },
        }

    def flat_snapshot(self) -> dict[str, str]:
        """Flat {metric: value} map in the shape the Deutschland-Dash
        Planner_Snapshot sheet consumes (<track>_units_total style keys)."""
        data = self.snapshot()
        flat: dict[str, str] = {
            "open_tasks": str(data["totals"]["open_tasks"]),
            "overdue_tasks": str(data["totals"]["overdue_tasks"]),
            "completed_today": str(data["totals"]["completed_today"]),
        }
        for project in data["projects"]:
            key = _slug(project["track"] or project["name"])
            flat[f"{key}_units_total"] = str(project["total_tasks"])
            flat[f"{key}_units_left"] = str(project["open_tasks"])
            if project["target_date"]:
                flat[f"{key}_target_date"] = str(project["target_date"])
            flat[f"{key}_pct_done"] = str(project["completion_pct"])
        for key, streak in data["streaks"].items():
            flat[f"{_slug(key)}_streak_days"] = str(streak)
        return flat

    def _project_metrics(
        self,
        project: dict[str, Any],
        milestones: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        today: date,
    ) -> dict[str, Any]:
        key = str(project["id"])
        own_tasks = [task for task in tasks if str(task.get("project_id") or "") == key]
        own_milestones = [row for row in milestones if str(row["project_id"]) == key]
        done = len([task for task in own_tasks if task["status"] == "done"])
        total = len([task for task in own_tasks if task["status"] != "skipped"])
        milestones_done = len([row for row in own_milestones if row["status"] == "done"])
        target = _parse_date(project.get("target_date"))
        return {
            "id": key,
            "name": project["name"],
            "track": project.get("track"),
            "status": project["status"],
            "target_date": project.get("target_date"),
            "days_to_target": (target - today).days if target else None,
            "total_tasks": total,
            "open_tasks": total - done,
            "completion_pct": round(done * 100 / total, 1) if total else 0.0,
            "milestones_total": len(own_milestones),
            "milestones_done": milestones_done,
            "next_milestone": self._next_milestone(own_milestones),
        }

    @staticmethod
    def _next_milestone(milestones: list[dict[str, Any]]) -> dict[str, Any] | None:
        pending = [row for row in milestones if row["status"] != "done"]
        if not pending:
            return None
        pending.sort(key=lambda row: (str(row.get("target_date") or "9999"), row.get("sort_order") or 0))
        head = pending[0]
        return {"name": head["name"], "target_date": head.get("target_date"), "status": head["status"]}

    @staticmethod
    def _upcoming_deadlines(
        milestones: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        today: date,
        window_days: int = 30,
    ) -> list[dict[str, Any]]:
        horizon = today + timedelta(days=window_days)
        items: list[dict[str, Any]] = []
        for row in milestones:
            target = _parse_date(row.get("target_date"))
            if row["status"] != "done" and target is not None and target <= horizon:
                items.append(
                    {
                        "kind": "milestone",
                        "name": row["name"],
                        "date": target.isoformat(),
                        "days_left": (target - today).days,
                        "overdue": target < today,
                    }
                )
        for row in tasks:
            due = _parse_date(row.get("due_date"))
            if row["status"] in OPEN_TASK_STATUSES and due is not None and due <= horizon:
                items.append(
                    {
                        "kind": "task",
                        "name": row["title"],
                        "date": due.isoformat(),
                        "days_left": (due - today).days,
                        "overdue": due < today,
                    }
                )
        items.sort(key=lambda item: item["date"])
        return items

    @staticmethod
    def _streaks(completions: list[dict[str, Any]], today: date) -> dict[str, int]:
        by_key: dict[str, set[date]] = {}
        for row in completions:
            key = row.get("recurrence_key")
            done_on = _parse_date(row.get("completed_on"))
            if key and done_on:
                by_key.setdefault(str(key), set()).add(done_on)
        streaks: dict[str, int] = {}
        for key, days in by_key.items():
            streak = 0
            # A streak survives until a full missed day; today still counts as
            # pending, so start from today and allow one gap at the head.
            cursor = today if today in days else today - timedelta(days=1)
            while cursor in days:
                streak += 1
                cursor -= timedelta(days=1)
            streaks[key] = streak
        return streaks


class ReminderService:
    """Decide which reminders are due and record sends idempotently."""

    MORNING_WINDOW = range(6, 12)
    EVENING_WINDOW = range(18, 23)

    def __init__(
        self,
        repository: PlannerCoreRepository,
        metrics: MetricsService,
        tasks: TaskService,
        timezone: str = "UTC",
    ) -> None:
        self.repository = repository
        self.metrics = metrics
        self.tasks = tasks
        self.timezone = timezone

    def due_reminders(self, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or datetime.now(ZoneInfo(self.timezone))
        today = current.date()
        sent_today = {
            row["kind"]
            for row in self.repository.list_rows("reminder_log")
            if _parse_date(row.get("sent_on")) == today
        }
        due: list[dict[str, Any]] = []
        if current.hour in self.MORNING_WINDOW and "morning_brief" not in sent_today:
            message = self._morning_brief()
            if message:
                due.append({"kind": "morning_brief", "message": message})
        if current.hour in self.EVENING_WINDOW and "evening_nudge" not in sent_today:
            message = self._evening_nudge()
            if message:
                due.append({"kind": "evening_nudge", "message": message})
        if "deadline_alert" not in sent_today:
            message = self._deadline_alert()
            if message:
                due.append({"kind": "deadline_alert", "message": message})
        return due

    def record_sent(self, kind: str, channel: str, payload: dict[str, Any]) -> None:
        self.repository.insert_row(
            "reminder_log",
            {
                "kind": kind,
                "sent_on": _local_today(self.timezone).isoformat(),
                "channel": channel,
                "payload": payload,
            },
        )

    def _morning_brief(self) -> str | None:
        today = self.tasks.today()["data"]
        lines = [f"Good morning. Plan for {today['date']}:"]
        for row in today["scheduled"] or today["due_today"]:
            lines.append(f"- {row['title']}" + (f" (due {row['due_date']})" if row.get("due_date") else ""))
        if today["overdue"]:
            lines.append(f"Overdue: {len(today['overdue'])} — oldest: {today['overdue'][0]['title']}")
        if len(lines) == 1:
            lines.append("Nothing scheduled. Pick the next milestone task.")
        return "\n".join(lines)

    def _evening_nudge(self) -> str | None:
        today = self.tasks.today()["data"]
        if today["completed_today"]:
            return None
        open_today = today["scheduled"] + today["due_today"]
        if not open_today and not today["overdue"]:
            return None
        head = open_today[0]["title"] if open_today else today["overdue"][0]["title"]
        return f"Nothing ticked today. Smallest win still open: {head}. Even 20 minutes counts."

    def _deadline_alert(self) -> str | None:
        snapshot = self.metrics.snapshot()
        close = [
            item
            for item in snapshot["upcoming_deadlines"]
            if item["days_left"] <= DEADLINE_WINDOW_DAYS
        ]
        if not close:
            return None
        lines = ["Deadlines within a week:"]
        for item in close[:8]:
            state = "OVERDUE" if item["overdue"] else f"{item['days_left']}d left"
            lines.append(f"- [{item['kind']}] {item['name']} — {item['date']} ({state})")
        return "\n".join(lines)


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")
