"""Deterministic services over the v2 Postgres planner tables.

All decisions here are rule-based: what is due, what slipped, what completion
percentage a project has, whether a reminder should fire. Intelligence (what to
plan, how to phrase advice) stays with the AI client calling the MCP tools.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any
from planner_engine.models import DailyPlan, ScheduledBlock
from zoneinfo import ZoneInfo

from planner_core.repository import PlannerCoreError, PlannerCoreRepository

OPEN_TASK_STATUSES = {"todo", "in_progress", "blocked"}
CLOSED_TASK_STATUSES = {"done", "skipped"}
TASK_STATUSES = OPEN_TASK_STATUSES | CLOSED_TASK_STATUSES
MILESTONE_STATUSES = {"not_started", "in_progress", "blocked", "done"}
PROJECT_STATUSES = {"active", "paused", "done", "archived"}
PRIORITIES = {"low", "medium", "high", "critical"}
DEADLINE_WINDOW_DAYS = 7
DEADLINE_HORIZON_DAYS = 30
OVERDUE_LIST_LIMIT = 200
# task_completions.source carries a check constraint in the database listing
# exactly these. Naming them here means an unknown value is refused with a
# clear message instead of the insert failing with a 500 nobody can read.
COMPLETION_SOURCES = {"mcp", "telegram", "dashboard", "api"}


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


def _is_overdue(task: Mapping[str, Any], today: date) -> bool:
    """Whether an open task needs attention now rather than later.

    Overdue when its deadline has passed; when it has no deadline, when the day
    it was planned for has passed; and when it has neither a deadline nor a
    planned day at all — a loose task with no date has been sitting unhandled,
    and treating it as overdue is the only way it gets tracked instead of
    silently floating. A date in the future is genuinely not-yet-due and is
    never overdue. Shared by TaskService.today and MetricsService so both
    agree."""
    due = _parse_date(task.get("due_date"))
    if due is not None:
        return due < today
    planned = _parse_date(task.get("scheduled_date"))
    if planned is not None:
        return planned < today
    # No date of any kind: unplanned and unhandled, so it counts.
    return True


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
        tasks = self.repository.list_rows("planner_tasks", columns="id,project_id,status")
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

    def add_project_qna(self, project_id: str, question: str, answer: str | None = None, status: str = "Drafting", notes: str | None = None) -> dict[str, Any]:
        row = self.repository.insert_row(
            "project_qna",
            {
                "project_id": project_id,
                "question": question.strip(),
                "answer": answer.strip() if answer else None,
                "status": status,
                "notes": notes.strip() if notes else None,
            },
        )
        return _envelope(True, "QnA added", {"qna": row})

    def update_project_qna(self, qna_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"question", "answer", "status", "notes"}
        payload = {key: value for key, value in updates.items() if key in allowed}
        if not payload:
            raise PlannerCoreError(f"No valid QnA fields in update; allowed: {sorted(allowed)}")
        row = self.repository.update_row("project_qna", qna_id, payload)
        return _envelope(True, "QnA updated", {"qna": row})

    def delete_project_qna(self, qna_id: str) -> dict[str, Any]:
        self.repository.delete_row("project_qna", qna_id)
        return _envelope(True, "QnA deleted", None)

    def list_project_widgets(self, project_id: str) -> dict[str, Any]:
        widgets = self.repository.list_rows("project_widgets", {"project_id": project_id})
        widgets_sorted = sorted(widgets, key=lambda w: w.get("order_index", 0))
        return _envelope(True, f"Fetched {len(widgets_sorted)} widgets", {"widgets": widgets_sorted})

    def add_project_widget(self, project_id: str, widget_type: str, title: str | None = None, file_id: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "project_id": project_id,
            "widget_type": widget_type,
            "title": title,
            "file_id": file_id,
            "config": config or {}
        }
        row = self.repository.insert_row("project_widgets", payload)
        return _envelope(True, "Widget added", {"widget": row})

    def update_project_widget(self, widget_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "file_id", "config", "order_index"}
        payload = {k: v for k, v in updates.items() if k in allowed}
        if not payload:
            raise PlannerCoreError("No valid fields to update")
        row = self.repository.update_row("project_widgets", widget_id, payload)
        return _envelope(True, "Widget updated", {"widget": row})

    def delete_project_widget(self, widget_id: str) -> dict[str, Any]:
        self.repository.delete_row("project_widgets", widget_id)
        return _envelope(True, "Widget deleted", None)


class GoalService:
    def __init__(self, repository: PlannerCoreRepository) -> None:
        self.repository = repository

    def add_monthly_goal(self, project_id: str, month: str, description: str) -> dict[str, Any]:
        """Add or update a monthly goal (upsert by project/month). Month should be YYYY-MM-DD (typically the 1st)."""
        _parse_date(month)
        # Upsert emulation: try find existing
        existing = self.repository.list_rows("monthly_goals", {"project_id": project_id, "month": month})
        if existing:
            row = self.repository.update_row("monthly_goals", str(existing[0]["id"]), {"description": description.strip()})
        else:
            row = self.repository.insert_row(
                "monthly_goals",
                {"project_id": project_id, "month": month, "description": description.strip()}
            )
        return _envelope(True, "Monthly goal saved", {"monthly_goal": row})

    def update_monthly_goal(self, goal_id: str, description: str) -> dict[str, Any]:
        row = self.repository.update_row("monthly_goals", goal_id, {"description": description.strip()})
        return _envelope(True, "Monthly goal updated", {"monthly_goal": row})

    def delete_monthly_goal(self, goal_id: str) -> dict[str, Any]:
        self.repository.delete_row("monthly_goals", goal_id)
        return _envelope(True, "Monthly goal deleted", None)

    def add_weekly_goal(self, project_id: str, week_start: str, description: str) -> dict[str, Any]:
        """Add or update a weekly goal (upsert by project/week)."""
        _parse_date(week_start)
        existing = self.repository.list_rows("weekly_goals", {"project_id": project_id, "week_start": week_start})
        if existing:
            row = self.repository.update_row("weekly_goals", str(existing[0]["id"]), {"description": description.strip()})
        else:
            row = self.repository.insert_row(
                "weekly_goals",
                {"project_id": project_id, "week_start": week_start, "description": description.strip()}
            )
        return _envelope(True, "Weekly goal saved", {"weekly_goal": row})

    def week_view(self, week_start: date) -> dict[str, Any]:
        """Return monthly and weekly goals that intersect this week."""
        month_starts = {week_start.replace(day=1)}
        monthly_goals = []
        for ms in month_starts:
            monthly_goals.extend(self.repository.list_rows("monthly_goals", {"month": ms.isoformat()}))
        
        weekly_goals = self.repository.list_rows("weekly_goals", {"week_start": week_start.isoformat()})
        
        return {
            "monthly_goals": monthly_goals,
            "weekly_goals": weekly_goals
        }



def _blocks_for_day(items: list[dict[str, Any]], on_date, timezone: str) -> list[ScheduledBlock]:
    """Map a day's timed tasks to calendar blocks; untimed tasks are skipped."""
    tz = ZoneInfo(timezone)
    blocks: list[ScheduledBlock] = []
    for item in items:
        start_time = item.get("start_time")
        if not start_time:
            continue
        hour, minute = (int(part) for part in str(start_time).split(":")[:2])
        base_date = on_date
        if item.get("scheduled_date"):
            try:
                base_date = datetime.strptime(str(item["scheduled_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass
                
        if hour >= 24:
            start = datetime(base_date.year, base_date.month, base_date.day, hour - 24, minute, tzinfo=tz) + timedelta(days=1)
        else:
            start = datetime(base_date.year, base_date.month, base_date.day, hour, minute, tzinfo=tz)
        duration = item.get("estimated_minutes") or 30
        task_id = str(item["id"])
        blocks.append(
            ScheduledBlock(
                title=item["title"],
                start=start,
                end=start + timedelta(minutes=duration),
                category="task",
                source="postgres",
                metadata={"planner_block_id": task_id, "source_task_id": task_id},
            )
        )
    return blocks

class TaskService:
    def __init__(
        self,
        repository: PlannerCoreRepository,
        timezone: str = "UTC",
        habits: "HabitService | None" = None,
    ) -> None:
        self.repository = repository
        self.timezone = timezone
        # Habits have no rows, so the day and week views ask for them here
        # rather than every caller stitching two lists together.
        self.habits = habits or HabitService(repository, timezone)

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
        parent_task_id: str | None = None,
        depends_on: str | None = None,
        metadata: dict[str, Any] | None = None,
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
                "parent_task_id": parent_task_id,
                "depends_on": depends_on,
                "metadata": metadata,
            },
        )
        return _envelope(True, f"Task created: {row['title']}", {"task": row})

    def create_tasks_batch(self, items: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        if not items:
            raise PlannerCoreError("At least one task is required")
        
        payloads = []
        for index, item in enumerate(items, start=1):
            title = str(item.get("title") or "").strip()
            if not title:
                raise PlannerCoreError(f"Task {index}: title is required")
            priority = item.get("priority") or "medium"
            if priority not in PRIORITIES:
                raise PlannerCoreError(f"Task {index}: invalid priority: {priority}")
            due_date = item.get("due_date")
            scheduled_date = item.get("scheduled_date")
            start_time = item.get("start_time")
            if due_date: _parse_date(due_date)
            if scheduled_date: _parse_date(scheduled_date)
            if start_time: _parse_time(start_time)

            payloads.append({
                "title": title,
                "project_id": item.get("project_id"),
                "milestone_id": item.get("milestone_id"),
                "due_date": due_date,
                "scheduled_date": scheduled_date,
                "start_time": start_time,
                "priority": priority,
                "estimated_minutes": item.get("estimated_minutes") or 30,
                "recurrence_key": item.get("recurrence_key"),
                "notes": item.get("notes"),
                "parent_task_id": item.get("parent_task_id"),
                "metadata": item.get("metadata"),
                "depends_on": item.get("depends_on"),
            })
            
        created = self.repository.insert_rows("planner_tasks", payloads)
        return _envelope(True, f"Created {len(created)} tasks", {"tasks": created})

    def _settle_group(self, task: Mapping[str, Any], *, done: bool) -> None:
        """Split slots and the row that stands for them in the counts stay in
        agreement: finishing every slot finishes the task, reopening any slot
        reopens it, and ticking the task itself carries its slots along.

        `parent_task_id` marks which row leads a split group; the slots are
        otherwise peers, free to sit on whatever day and time suits them.
        """
        task_id = str(task["id"])
        leader_id = str(task.get("parent_task_id") or task_id)
        slots = self.repository.list_rows(
            "planner_tasks", {"parent_task_id": leader_id}, columns="id,status"
        )
        if not slots:  # the overwhelmingly common case: a task that never split
            return

        if done:
            patch = {
                "status": "done",
                "completed_at": datetime.now(ZoneInfo(self.timezone)).isoformat(),
            }
        else:
            patch = {"status": "todo", "completed_at": None}

        if task_id == leader_id:
            targets = [
                str(slot["id"])
                for slot in slots
                if (slot.get("status") in CLOSED_TASK_STATUSES) != done
            ]
        elif done:
            every_slot_closed = all(
                str(slot["id"]) == task_id or slot.get("status") in CLOSED_TASK_STATUSES
                for slot in slots
            )
            targets = [leader_id] if every_slot_closed else []
        else:
            targets = [leader_id]

        for target in targets:
            self.repository.update_row("planner_tasks", target, patch)

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
            "parent_task_id",
            "depends_on",
            # free-form columns a project brings with it: the study plan's
            # Subject and Source, for instance
            "metadata",
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

    def delete_tasks_batch(self, task_ids: list[str]) -> dict[str, Any]:
        if not task_ids:
            return _envelope(True, "No tasks to delete", {"deleted": []})
        self.repository.delete_rows("planner_tasks", {"id": task_ids})
        return _envelope(True, f"{len(task_ids)} tasks deleted", {"deleted": task_ids})

    def update_task_date_time_batch(self, updates: list[dict[str, Any]]) -> dict[str, Any]:
        if not updates:
            return _envelope(True, "No tasks to update", {"updated": []})
        
        updated_tasks = []
        for update in updates:
            task_id = update.get("id")
            if not task_id:
                continue
                
            allowed = {"scheduled_date", "due_date", "start_time"}
            payload = {k: v for k, v in update.items() if k in allowed}
            
            if payload:
                try:
                    row = self.repository.update_row("planner_tasks", task_id, payload)
                    updated_tasks.append(row)
                except Exception:
                    pass
                    
        return _envelope(True, f"{len(updated_tasks)} tasks updated", {"updated": updated_tasks})

    def complete_task(self, task_id: str, *, source: str = "mcp", note: str | None = None) -> dict[str, Any]:
        if source not in COMPLETION_SOURCES:
            raise PlannerCoreError(
                f"Unknown completion source: {source!r}. "
                f"Expected one of {', '.join(sorted(COMPLETION_SOURCES))}"
            )
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
        self._settle_group(task, done=True)
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
        today_str = today.isoformat()
        qs = f"or=(scheduled_date.lte.{today_str},due_date.lte.{today_str})"
        rows = self.repository.list_rows("planner_tasks", extra_filters={"status": list(OPEN_TASK_STATUSES)}, query_string=qs)
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
            if _is_overdue(row, today):
                overdue.append(row)
        completions = self.repository.list_rows(
            "task_completions",
            extra_filters={"completed_on": today_str},
        )
        return _envelope(
            True,
            f"{len(scheduled)} scheduled, {len(due)} due, {len(overdue)} overdue, {len(completions)} completed today",
            {
                "date": today.isoformat(),
                "scheduled": scheduled,
                "due_today": due,
                "overdue": sorted(
                    overdue,
                    key=lambda row: str(row.get("due_date") or row.get("scheduled_date") or ""),
                ),
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
            for row in self.repository.list_rows(
                "task_completions",
                extra_filters={"completed_on": today.isoformat()},
            )
            if row.get("task_id")
        }
        items: list[dict[str, Any]] = []
        today_str = today.isoformat()
        qs = f"or=(scheduled_date.eq.{today_str},due_date.eq.{today_str})"
        rows = self.repository.list_rows("planner_tasks", query_string=qs)
        if completed_task_ids:
            rows.extend(self.repository.list_rows("planner_tasks", {"id": list(completed_task_ids)}))
        
        seen = set()
        unique_rows = []
        for r in rows:
            if str(r["id"]) not in seen:
                seen.add(str(r["id"]))
                unique_rows.append(r)

        umbrellas = self._umbrella_ids(unique_rows)
        unique_rows = [row for row in unique_rows if str(row["id"]) not in umbrellas]

        for row in unique_rows:
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

        self._settle_group(task, done=False)
        return _envelope(True, f"Reopened: {row['title']}", {"task": row})

    def sync_calendar(self, client: Any, days: int = 7) -> dict[str, Any]:
        """Mirror the next `days` of scheduled work onto Google Calendar.

        Reconciled in one pass over the whole window rather than a pass per
        day. Each pass costs a Google listing, a read of every calendar link
        and a decision log write, so doing it daily meant a month's sync made
        over two hundred round trips and timed out before it finished.
        """
        today = datetime.now(ZoneInfo(self.timezone)).date()
        last_day = today + timedelta(days=days - 1)

        # One lookup for the whole window instead of three per day.
        habits_by_day: dict[str, list[dict[str, Any]]] = {}
        for occurrence in self.habits.occurrences(today, last_day):
            habits_by_day.setdefault(str(occurrence["scheduled_date"]), []).append(occurrence)

        blocks: list[ScheduledBlock] = []
        seen: set[str] = set()
        for offset in range(days):
            on_date = today + timedelta(days=offset)
            items = self.day_view(
                on_date.isoformat(), habit_items=habits_by_day.get(on_date.isoformat(), [])
            )["data"]["items"]
            for block in _blocks_for_day(items, on_date, self.timezone):
                # A task timed just after midnight is shown on the previous
                # evening as well as its own day, so it would otherwise be
                # collected twice for the same calendar slot.
                block_id = str(block.metadata.get("planner_block_id"))
                if block_id in seen:
                    continue
                seen.add(block_id)
                blocks.append(block)

        plan = DailyPlan(date=today, blocks=blocks, conflicts=[])
        result = client.sync_plan(plan, start=today, end=last_day + timedelta(days=1))
        totals = {
            "created": result.created,
            "updated": result.updated,
            "deleted": result.deleted,
            "unchanged": result.unchanged,
        }
        message = (
            f"{totals['created']} created, {totals['updated']} updated, "
            f"{totals['deleted']} removed over {days} day(s)"
        )
        return _envelope(True, message, {**totals, "errors": list(result.errors), "days": days})

    def _umbrella_ids(self, rows: list[dict[str, Any]]) -> set[str]:
        """Which of these rows have been split into slots.

        Splitting leaves the original holding the whole task's time — a 90
        minute task becomes two 45 minute slots plus a 90 minute original —
        so the timeline shows the slots and keeps the original out of it.
        Otherwise the day reads as 180 minutes of work and the spare block
        goes to Google Calendar.

        Scoped to the rows on screen, so this stays a small lookup however
        long the task list gets.
        """
        ids = [str(row["id"]) for row in rows]
        if not ids:
            return set()
        return {
            str(row["parent_task_id"])
            for row in self.repository.list_rows(
                "planner_tasks",
                columns="parent_task_id",
                query_string=f"parent_task_id=in.({','.join(ids)})",
            )
            if row.get("parent_task_id")
        }

    def day_view(
        self, on_date: str | None = None, habit_items: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Tasks belonging to one date, shaped for a timeline: tasks with a
        start_time carry their slot, the rest form the unscheduled tray.

        habit_items lets a caller that already worked out a whole range of
        occurrences hand this day's share in, instead of every day querying
        the habit tables again for itself."""
        target = _parse_date(on_date) or _local_today(self.timezone)
        items: list[dict[str, Any]] = []
        target_str = target.isoformat()
        next_day = target + timedelta(days=1)
        next_day_str = next_day.isoformat()
        qs = f"or=(scheduled_date.eq.{target_str},due_date.eq.{target_str},and(scheduled_date.eq.{next_day_str},start_time.lt.04:00:00))"
        all_rows = self.repository.list_rows("planner_tasks", query_string=qs)
        umbrellas = self._umbrella_ids(all_rows)

        for row in all_rows:
            if str(row["id"]) in umbrellas:
                continue
            planned = _parse_date(row.get("scheduled_date"))
            due = _parse_date(row.get("due_date"))

            is_next_day_spillover = False
            if planned:
                if planned != target:
                    if planned == next_day and row.get("start_time") and str(row.get("start_time")) < "04:00:00":
                        is_next_day_spillover = True
                    else:
                        continue
            else:
                if due != target:
                    continue
                    
            start_time_val = row.get("start_time")
            if is_next_day_spillover and start_time_val:
                # e.g., "01:30:00" -> "25:30:00"
                h, m, s = str(start_time_val).split(":")
                start_time_val = f"{int(h) + 24:02d}:{m}:{s}"

            items.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "status": row["status"],
                    "done": row["status"] in CLOSED_TASK_STATUSES,
                    "start_time": start_time_val,
                    "estimated_minutes": row.get("estimated_minutes"),
                    "priority": row.get("priority"),
                    "due_date": row.get("due_date"),
                    "scheduled_date": row.get("scheduled_date"),
                    "notes": row.get("notes"),
                    "project_id": row.get("project_id"),
                    # lets the timeline tag a slot as part of a split task
                    "parent_task_id": row.get("parent_task_id"),
                }
            )
        items.extend(
            habit_items if habit_items is not None else self.habits.occurrences(target, target)
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

    def week_view(self, on_date: str | None = None) -> dict[str, Any]:
        """Tasks belonging to a week (Mon-Sun) containing on_date."""
        target = _parse_date(on_date) or _local_today(self.timezone)
        monday = target - timedelta(days=target.weekday())
        week_dates = {monday + timedelta(days=i) for i in range(7)}
        
        items: list[dict[str, Any]] = []
        monday_str = monday.isoformat()
        sunday_str = (monday + timedelta(days=6)).isoformat()
        # Bounded at both ends and limited to the fields the view returns.
        # Without the upper bound this pulled every task dated from Monday to
        # the end of time — 2027 deadlines included — only to discard them below.
        qs = (
            f"or=(and(scheduled_date.gte.{monday_str},scheduled_date.lte.{sunday_str}),"
            f"and(due_date.gte.{monday_str},due_date.lte.{sunday_str}))"
        )
        all_rows = self.repository.list_rows(
            "planner_tasks",
            query_string=qs,
            columns=(
                "id,title,status,start_time,estimated_minutes,priority,"
                "due_date,scheduled_date,notes,project_id"
            ),
        )
        umbrellas = self._umbrella_ids(all_rows)

        for row in all_rows:
            if str(row["id"]) in umbrellas:
                continue
            planned = _parse_date(row.get("scheduled_date"))
            due = _parse_date(row.get("due_date"))
            if planned:
                if planned not in week_dates:
                    continue
            else:
                if due not in week_dates:
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
        items.extend(self.habits.occurrences(monday, monday + timedelta(days=6)))
        items.sort(
            key=lambda item: (
                str(item.get("scheduled_date") or item.get("due_date") or "9999"),
                item["start_time"] is None,
                str(item["start_time"] or ""),
                item["title"],
            )
        )
        return _envelope(True, "Week view", {"week_start": monday.isoformat(), "items": items})

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



HABIT_CADENCES = {"daily", "weekly"}
HABIT_PREFIX = "habit:"


def _habit_item_id(habit_id: str, on_date: date) -> str:
    """Occurrences have no row of their own, so the day view gives them an id
    the clients can hand straight back when one is ticked or moved."""
    return f"{HABIT_PREFIX}{habit_id}:{on_date.isoformat()}"


def parse_habit_item_id(item_id: str) -> tuple[str, date] | None:
    """The inverse. Returns None for an ordinary task id."""
    if not str(item_id).startswith(HABIT_PREFIX):
        return None
    try:
        _, habit_id, stamp = str(item_id).split(":", 2)
        return habit_id, date.fromisoformat(stamp)
    except ValueError:
        return None


class HabitService:
    """Things you do repeatedly, where missing a day costs a streak and
    nothing else. A habit is a rule; its occurrences are worked out on read,
    so nothing accumulates and nothing can go overdue."""

    def __init__(self, repository: PlannerCoreRepository, timezone: str = "UTC") -> None:
        self.repository = repository
        self.timezone = timezone

    # ── rules ─────────────────────────────────────────────────────────────
    def add_habit(
        self,
        title: str,
        *,
        recurrence_key: str | None = None,
        cadence: str = "daily",
        days_of_week: list[int] | None = None,
        start_time: str | None = None,
        estimated_minutes: int | None = None,
        project_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        if not title.strip():
            raise PlannerCoreError("Habit title is required")
        if cadence not in HABIT_CADENCES:
            raise PlannerCoreError(f"Invalid cadence: {cadence}; use one of {sorted(HABIT_CADENCES)}")
        days = sorted({int(d) for d in (days_of_week or [])})
        if any(d < 0 or d > 6 for d in days):
            raise PlannerCoreError("days_of_week must be 0 (Sunday) to 6 (Saturday)")
        if cadence == "weekly" and not days:
            raise PlannerCoreError("A weekly habit needs at least one day in days_of_week")
        _parse_time(start_time)
        row = self.repository.insert_row(
            "habits",
            {
                "title": title.strip(),
                "recurrence_key": (recurrence_key or _slug(title)),
                "cadence": cadence,
                "days_of_week": days,
                "start_time": start_time,
                "estimated_minutes": estimated_minutes,
                "project_id": project_id,
                "start_date": start_date or _local_today(self.timezone).isoformat(),
                "end_date": end_date,
            },
        )
        return _envelope(True, f"Habit created: {row['title']}", {"habit": row})

    def list_habits(self, *, include_inactive: bool = False) -> dict[str, Any]:
        rows = self.repository.list_rows("habits")
        if not include_inactive:
            rows = [row for row in rows if row.get("is_active")]
        return _envelope(True, f"{len(rows)} habits", {"habits": rows})

    def update_habit(self, habit_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "title", "recurrence_key", "cadence", "days_of_week", "start_time",
            "estimated_minutes", "project_id", "start_date", "end_date", "is_active",
        }
        payload = {k: v for k, v in updates.items() if k in allowed}
        if not payload:
            raise PlannerCoreError(f"No valid habit fields in update; allowed: {sorted(allowed)}")
        if payload.get("cadence") and payload["cadence"] not in HABIT_CADENCES:
            raise PlannerCoreError(f"Invalid cadence: {payload['cadence']}")
        if "start_time" in payload:
            _parse_time(payload["start_time"])
        row = self.repository.update_row("habits", habit_id, payload)
        return _envelope(True, f"Habit updated: {row['title']}", {"habit": row})

    def delete_habit(self, habit_id: str) -> dict[str, Any]:
        row = self.repository.get_row("habits", habit_id)
        if row is None:
            raise PlannerCoreError(f"Habit was not found: {habit_id}")
        self.repository.delete_row("habits", habit_id)
        return _envelope(True, f"Habit deleted: {row['title']}", {"habit": row})

    # ── occurrences ───────────────────────────────────────────────────────
    @staticmethod
    def _falls_on(habit: Mapping[str, Any], day: date) -> bool:
        start = _parse_date(habit.get("start_date"))
        end = _parse_date(habit.get("end_date"))
        if start and day < start:
            return False
        if end and day > end:
            return False
        days = list(habit.get("days_of_week") or [])
        if not days:
            return True
        # Python weekday() is Monday=0; the column is Sunday=0 to match JS.
        return ((day.weekday() + 1) % 7) in {int(d) for d in days}

    def occurrences(self, start: date, end: date) -> list[dict[str, Any]]:
        """Every habit occurrence between two dates, overrides applied and
        completions marked. One query per table however wide the window."""
        habits = [row for row in self.repository.list_rows("habits") if row.get("is_active")]
        if not habits:
            return []
        by_id = {str(row["id"]): row for row in habits}

        # An override can move an occurrence into or out of the window, so the
        # lookup has to be wider than the window itself.
        overrides: dict[tuple[str, str], dict[str, Any]] = {}
        moved_in: list[dict[str, Any]] = []
        for row in self.repository.list_rows("habit_overrides"):
            overrides[(str(row["habit_id"]), str(row["on_date"])[:10])] = row
            landing = _parse_date(row.get("moved_to"))
            if landing and start <= landing <= end and not row.get("skipped"):
                moved_in.append(row)

        keys = {str(row.get("recurrence_key")) for row in habits}
        done: set[tuple[str, str]] = set()
        for row in self.repository.list_rows(
            "task_completions",
            columns="recurrence_key,completed_on",
            query_string=f"completed_on=gte.{start.isoformat()}&completed_on=lte.{end.isoformat()}",
        ):
            if row.get("recurrence_key") in keys:
                done.add((str(row["recurrence_key"]), str(row["completed_on"])[:10]))

        items: list[dict[str, Any]] = []

        def emit(habit: Mapping[str, Any], rule_day: date, shown_on: date, override: Mapping[str, Any] | None) -> None:
            start_time = (override or {}).get("start_time") or habit.get("start_time")
            minutes = (override or {}).get("estimated_minutes") or habit.get("estimated_minutes")
            key = str(habit.get("recurrence_key"))
            items.append(
                {
                    "id": _habit_item_id(str(habit["id"]), rule_day),
                    "title": habit["title"],
                    "status": "done" if (key, shown_on.isoformat()) in done else "todo",
                    "done": (key, shown_on.isoformat()) in done,
                    "start_time": start_time,
                    "estimated_minutes": minutes,
                    "priority": "medium",
                    "due_date": None,
                    "scheduled_date": shown_on.isoformat(),
                    "notes": None,
                    "project_id": habit.get("project_id"),
                    "parent_task_id": None,
                    "is_habit": True,
                    "recurrence_key": key,
                }
            )

        day = start
        while day <= end:
            for habit in habits:
                if not self._falls_on(habit, day):
                    continue
                override = overrides.get((str(habit["id"]), day.isoformat()))
                if override:
                    if override.get("skipped"):
                        continue
                    landing = _parse_date(override.get("moved_to"))
                    if landing and landing != day:
                        continue  # emitted below, on the day it moved to
                emit(habit, day, day, override)
            day += timedelta(days=1)

        for override in moved_in:
            habit = by_id.get(str(override["habit_id"]))
            rule_day = _parse_date(override.get("on_date"))
            landing = _parse_date(override.get("moved_to"))
            if habit and rule_day and landing and rule_day != landing:
                emit(habit, rule_day, landing, override)

        return items

    # ── acting on one occurrence ──────────────────────────────────────────
    def _habit_for(self, habit_id: str) -> dict[str, Any]:
        habit = self.repository.get_row("habits", habit_id)
        if habit is None:
            raise PlannerCoreError(f"Habit was not found: {habit_id}")
        return habit

    def _shown_on(self, habit_id: str, rule_day: date) -> date:
        """Where the occurrence actually sits once any override is applied."""
        for row in self.repository.list_rows("habit_overrides", {"habit_id": habit_id}):
            if str(row.get("on_date"))[:10] == rule_day.isoformat():
                landing = _parse_date(row.get("moved_to"))
                return landing or rule_day
        return rule_day

    def complete_occurrence(self, habit_id: str, rule_day: date, *, source: str = "api") -> dict[str, Any]:
        if source not in COMPLETION_SOURCES:
            raise PlannerCoreError(
                f"Unknown completion source: {source!r}. "
                f"Expected one of {', '.join(sorted(COMPLETION_SOURCES))}"
            )
        habit = self._habit_for(habit_id)
        on_date = self._shown_on(habit_id, rule_day)
        key = str(habit.get("recurrence_key"))
        for row in self.repository.list_rows("task_completions", {"recurrence_key": key}):
            if str(row.get("completed_on"))[:10] == on_date.isoformat():
                return _envelope(True, f"Already done: {habit['title']}", {"habit": habit})
        self.repository.insert_row(
            "task_completions",
            {
                "task_id": None,
                "recurrence_key": key,
                "completed_on": on_date.isoformat(),
                "source": source,
                "note": None,
            },
        )
        return _envelope(True, f"Done: {habit['title']}", {"habit": habit})

    def reopen_occurrence(self, habit_id: str, rule_day: date) -> dict[str, Any]:
        habit = self._habit_for(habit_id)
        on_date = self._shown_on(habit_id, rule_day)
        key = str(habit.get("recurrence_key"))
        for row in self.repository.list_rows("task_completions", {"recurrence_key": key}):
            if str(row.get("completed_on"))[:10] == on_date.isoformat():
                self.repository.delete_row("task_completions", str(row["id"]))
        return _envelope(True, f"Reopened: {habit['title']}", {"habit": habit})

    def _upsert_override(self, habit_id: str, rule_day: date, patch: dict[str, Any]) -> dict[str, Any]:
        for row in self.repository.list_rows("habit_overrides", {"habit_id": habit_id}):
            if str(row.get("on_date"))[:10] == rule_day.isoformat():
                return self.repository.update_row("habit_overrides", str(row["id"]), patch)
        return self.repository.insert_row(
            "habit_overrides",
            {"habit_id": habit_id, "on_date": rule_day.isoformat(), "skipped": False, **patch},
        )

    def reschedule_occurrence(
        self,
        habit_id: str,
        rule_day: date,
        *,
        moved_to: str | None = None,
        start_time: str | None = None,
        estimated_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Move or retime one day of a habit without touching the rule, so
        skipping Tuesday's gym to Wednesday leaves every other week alone."""
        habit = self._habit_for(habit_id)
        patch: dict[str, Any] = {}
        if moved_to is not None:
            _parse_date(moved_to)
            patch["moved_to"] = moved_to
        if start_time is not None:
            _parse_time(start_time)
            patch["start_time"] = start_time
        if estimated_minutes is not None:
            patch["estimated_minutes"] = estimated_minutes
        if not patch:
            raise PlannerCoreError("Nothing to change on this occurrence")
        row = self._upsert_override(habit_id, rule_day, patch)
        return _envelope(True, f"Moved: {habit['title']}", {"override": row})

    def skip_occurrence(self, habit_id: str, rule_day: date) -> dict[str, Any]:
        habit = self._habit_for(habit_id)
        row = self._upsert_override(habit_id, rule_day, {"skipped": True, "moved_to": None})
        return _envelope(True, f"Skipped: {habit['title']}", {"override": row})


class MetricsService:
    """Aggregate dashboard-ready metrics from raw rows. Pure computation."""

    def __init__(self, repository: PlannerCoreRepository, timezone: str = "UTC") -> None:
        self.repository = repository
        self.timezone = timezone

    def snapshot(self) -> dict[str, Any]:
        today = _local_today(self.timezone)
        current_month = today.replace(day=1).isoformat()
        projects = self.repository.list_rows("projects")
        milestones = self.repository.list_rows("milestones")
        counts = self._task_counts(today)
        deadline_tasks = self._tasks_due_by(today + timedelta(days=DEADLINE_HORIZON_DAYS))
        overdue_list = self._overdue_tasks(today)
        completion_summary = self._completion_summary(today)
        monthly_goals = self.repository.list_rows("monthly_goals")
        project_files = self.repository.list_rows("project_files")

        from collections import defaultdict
        goals_by_project = defaultdict(list)
        for mg in monthly_goals:
            goals_by_project[str(mg["project_id"])].append(mg)

        files_by_project = defaultdict(list)
        for pf in project_files:
            files_by_project[str(pf["project_id"])].append(pf)

        # Sort goals by month ascending for each project
        for pid in goals_by_project:
            goals_by_project[pid].sort(key=lambda x: x["month"])

        project_metrics = []
        for project in projects:
            pm = self._project_metrics(project, milestones, counts, today)

            p_goals = goals_by_project.get(str(project["id"]), [])
            p_files = files_by_project.get(str(project["id"]), [])
            curr_goal = next((g for g in p_goals if g["month"] == current_month), None)

            pm["monthly_goal"] = curr_goal
            pm["monthly_goals"] = p_goals
            pm["files"] = p_files
            project_metrics.append(pm)
        deadlines = self._upcoming_deadlines(milestones, deadline_tasks, today)
        return {
            "generated_on": today.isoformat(),
            "timezone": self.timezone,
            "projects": project_metrics,
            "upcoming_deadlines": deadlines,
            "streaks": completion_summary["streaks"],
            "totals": {
                "open_tasks": sum(bucket["open"] for bucket in counts.values()),
                # Counted across every overdue task; the list below is capped
                # so a long backlog cannot bloat the dashboard payload.
                "overdue_tasks": sum(bucket["overdue"] for bucket in counts.values()),
                "overdue_list": overdue_list,
                "overdue_list_truncated": len(overdue_list) >= OVERDUE_LIST_LIMIT,
                "completed_today": completion_summary["completed_today"],
                "completions_last_7_days": completion_summary["completions_last_7_days"],
            },
        }

    def flat_snapshot(self, data: dict[str, Any] | None = None) -> dict[str, str]:
        """Flat {metric: value} map in the shape the Deutschland-Dash
        Planner_Snapshot sheet consumes (<track>_units_total style keys)."""
        if data is None:
            data = self.snapshot()
        flat: dict[str, str] = {
            "open_tasks": str(data["totals"]["open_tasks"]),
            "overdue_tasks": str(data["totals"]["overdue_tasks"]),
            "completed_today": str(data["totals"]["completed_today"]),
        }
        for project in data["projects"]:
            key = _slug(project["name"])
            flat[f"{key}_units_total"] = str(project["total_tasks"])
            flat[f"{key}_units_left"] = str(project["open_tasks"])
            if project["target_date"]:
                flat[f"{key}_target_date"] = str(project["target_date"])
            flat[f"{key}_pct_done"] = str(project["completion_pct"])
        for key, streak in data["streaks"].items():
            flat[f"{_slug(key)}_streak_days"] = str(streak)
        return flat

    OPEN_STATUS_LIST = "todo,in_progress,blocked"

    def _task_counts(self, today: date) -> dict[str, dict[str, int]]:
        """Per-project task counts, rolled up by Postgres rather than by
        shipping every row here to be counted. Falls back to the old full scan
        when the rollup function has not been installed yet, so a deploy that
        lands before the migration still serves a correct dashboard."""
        try:
            rows = self.repository.call_function(
                "planner_task_counts", {"p_today": today.isoformat()}
            )
        except Exception:
            rows = None

        if rows is None:
            return self._task_counts_by_scan(today)

        return {
            str(row.get("project_id") or ""): {
                "done": int(row.get("done_count") or 0),
                "total": int(row.get("total_count") or 0),
                "open": int(row.get("open_count") or 0),
                "overdue": int(row.get("overdue_count") or 0),
            }
            for row in rows
        }

    def _task_counts_by_scan(self, today: date) -> dict[str, dict[str, int]]:
        tasks = self.repository.list_rows(
            "planner_tasks",
            columns="id,project_id,status,scheduled_date,due_date",
            query_string="parent_task_id=is.null",
        )
        buckets: dict[str, dict[str, int]] = {}
        for task in tasks:
            key = str(task.get("project_id") or "")
            bucket = buckets.setdefault(key, {"done": 0, "total": 0, "open": 0, "overdue": 0})
            status = task.get("status")
            if status == "done":
                bucket["done"] += 1
            if status != "skipped":
                bucket["total"] += 1
            if status in OPEN_TASK_STATUSES:
                bucket["open"] += 1
                if _is_overdue(task, today):
                    bucket["overdue"] += 1
        return buckets

    def _completion_summary(self, today: date) -> dict[str, Any]:
        """Streaks and the two completion counts, rolled up by Postgres.

        This used to fetch ninety days of task_completions on every render to
        produce a handful of numbers, which made it the heaviest read on the
        dashboard. Falls back to that full scan when the function has not been
        installed yet, so a deploy landing before the migration still serves
        correct figures."""
        try:
            summary = self.repository.call_function(
                "planner_completion_summary", {"p_today": today.isoformat()}
            )
        except Exception:
            summary = None

        # rpc may hand back the single jsonb value or a one-row list of it
        if isinstance(summary, list):
            summary = summary[0] if summary else None
        if not isinstance(summary, dict):
            return self._completion_summary_by_scan(today)

        return {
            "streaks": {str(k): int(v) for k, v in (summary.get("streaks") or {}).items()},
            "completed_today": int(summary.get("completed_today") or 0),
            "completions_last_7_days": int(summary.get("completions_last_7_days") or 0),
        }

    def _completion_summary_by_scan(self, today: date) -> dict[str, Any]:
        cutoff = (today - timedelta(days=90)).isoformat()
        completions = self.repository.list_rows(
            "task_completions",
            columns="id,task_id,completed_on,recurrence_key",
            query_string=f"completed_on=gte.{cutoff}",
        )
        return {
            "streaks": self._streaks(completions, today),
            "completed_today": len(
                [row for row in completions if _parse_date(row.get("completed_on")) == today]
            ),
            "completions_last_7_days": len(
                [
                    row
                    for row in completions
                    if (done := _parse_date(row.get("completed_on"))) is not None
                    and today - timedelta(days=6) <= done <= today
                ]
            ),
        }

    def _tasks_due_by(self, horizon: date) -> list[dict[str, Any]]:
        """Only the open tasks with a deadline inside the window the dashboard
        actually lists."""
        return self.repository.list_rows(
            "planner_tasks",
            columns="id,title,due_date,status",
            query_string=(
                "parent_task_id=is.null"
                f"&status=in.({self.OPEN_STATUS_LIST})"
                f"&due_date=lte.{horizon.isoformat()}"
            ),
        )

    def _overdue_tasks(self, today: date) -> list[dict[str, Any]]:
        """Overdue open tasks, oldest deadline first. Capped: the dashboard
        shows this as a list, and nobody reads past a couple of hundred.

        Three cases count: a past due date, no due date but a past planned day,
        and no date of any kind (a loose task that has been sitting unhandled).
        The dated-and-late ones are shown first, oldest at the top; the dateless
        ones sit below them, since they have no deadline to be measured against.
        """
        stamp = today.isoformat()
        rows = self.repository.list_rows(
            "planner_tasks",
            columns="id,title,project_id,status,scheduled_date,due_date,priority",
            query_string=(
                "parent_task_id=is.null"
                f"&status=in.({self.OPEN_STATUS_LIST})"
                f"&or=(due_date.lt.{stamp},"
                f"and(due_date.is.null,scheduled_date.lt.{stamp}),"
                "and(due_date.is.null,scheduled_date.is.null))"
                f"&limit={OVERDUE_LIST_LIMIT}"
            ),
        )

        def sort_key(task: Mapping[str, Any]) -> tuple[int, str]:
            date_str = task.get("due_date") or task.get("scheduled_date")
            # dateless tasks have no deadline, so they sort after every dated
            # one; among dated tasks the oldest comes first.
            return (1, "") if not date_str else (0, str(date_str))

        return sorted(rows, key=sort_key)

    def _project_metrics(
        self,
        project: dict[str, Any],
        milestones: list[dict[str, Any]],
        counts: dict[str, dict[str, int]],
        today: date,
    ) -> dict[str, Any]:
        key = str(project["id"])
        bucket = counts.get(key, {"done": 0, "total": 0, "open": 0, "overdue": 0})
        own_milestones = [row for row in milestones if str(row["project_id"]) == key]
        done = bucket["done"]
        total = bucket["total"]
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
            for row in self.repository.list_rows(
                "reminder_log",
                extra_filters={"sent_on": today.isoformat()},
            )
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


EXPENSE_CATEGORIES = (
    "Food", "Groceries", "Transport", "Rent", "Utilities", "Health",
    "Education", "Shopping", "Entertainment", "Subscriptions", "Travel",
    "Savings", "Fees", "Family", "Other",
)
INCOME_CATEGORIES = ("Salary", "Freelance", "Refund", "Gift", "Interest", "Other")
TRANSACTION_TYPES = {"expense", "income"}
CADENCES = {"weekly", "monthly", "yearly"}
RECURRING_LOOKBACK_DAYS = 62


def _normalize_category(value: Any, kind: str = "expense") -> str | None:
    """Snap a category onto the canonical list so the summary doesn't end up
    with Food, food and Eating Out as three separate slices."""
    if value in (None, ""):
        return None
    raw = str(value).strip()
    known = EXPENSE_CATEGORIES if kind == "expense" else INCOME_CATEGORIES
    for candidate in known:
        if candidate.casefold() == raw.casefold():
            return candidate
    return raw.title()


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


class FinanceService:
    """Expense passbook, monthly summaries, and recurring charges.

    Amounts are never summed across currencies — day-to-day spending is in
    rupees while the Germany goals are in euros, and converting without a rate
    would invent numbers. Every total is reported per currency instead.
    """

    def __init__(self, repository: PlannerCoreRepository, timezone: str = "UTC") -> None:
        self.repository = repository
        self.timezone = timezone

    # ---------- transactions ----------

    def log_transaction(
        self,
        description: str,
        amount: float,
        *,
        on_date: str | None = None,
        category: str | None = None,
        currency: str = "INR",
        kind: str = "expense",
        merchant: str | None = None,
        payment_method: str | None = None,
        goal_id: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if not description.strip():
            raise PlannerCoreError("Description is required")
        if kind not in TRANSACTION_TYPES:
            raise PlannerCoreError(f"type must be one of {sorted(TRANSACTION_TYPES)}")
        value = _money(amount)
        if value <= 0:
            raise PlannerCoreError("Amount must be greater than zero")

        when = _parse_date(on_date) or _local_today(self.timezone)
        code = str(currency).strip().upper() or "INR"

        if goal_id and not self.repository.get_row("finance_goals", goal_id):
            raise PlannerCoreError(f"Savings goal was not found: {goal_id}")

        row = self.repository.insert_row(
            "finance_logs",
            {
                "date": when.isoformat(),
                "description": description.strip(),
                "amount": value,
                "currency": code,
                "type": kind,
                "category": _normalize_category(category, kind),
                "merchant": merchant.strip() if merchant else None,
                "payment_method": payment_method.strip() if payment_method else None,
                "goal_id": goal_id,
                "notes": notes,
            },
        )
        return _envelope(True, f"Logged {code} {value:,.2f} — {description.strip()}", {"transaction": row})

    def update_transaction(self, transaction_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "date", "description", "amount", "currency", "type",
            "category", "merchant", "payment_method", "goal_id", "notes",
        }
        payload = {key: value for key, value in updates.items() if key in allowed}
        if not payload:
            raise PlannerCoreError("No supported fields to update")

        if "type" in payload and payload["type"] not in TRANSACTION_TYPES:
            raise PlannerCoreError(f"type must be one of {sorted(TRANSACTION_TYPES)}")
        if "amount" in payload:
            payload["amount"] = _money(payload["amount"])
            if payload["amount"] <= 0:
                raise PlannerCoreError("Amount must be greater than zero")
        if "date" in payload:
            parsed = _parse_date(payload["date"])
            payload["date"] = parsed.isoformat() if parsed else None
        if "currency" in payload:
            payload["currency"] = str(payload["currency"]).strip().upper()
        if "category" in payload:
            existing = self.repository.get_row("finance_logs", transaction_id) or {}
            kind = payload.get("type") or existing.get("type") or "expense"
            payload["category"] = _normalize_category(payload["category"], kind)

        payload["updated_at"] = datetime.now(ZoneInfo(self.timezone)).isoformat()
        row = self.repository.update_row("finance_logs", transaction_id, payload)
        return _envelope(True, "Transaction updated", {"transaction": row})

    def delete_transaction(self, transaction_id: str) -> dict[str, Any]:
        self.repository.delete_row("finance_logs", transaction_id)
        return _envelope(True, "Transaction deleted", None)

    def list_transactions(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        category: str | None = None,
        kind: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """The passbook feed: newest first, optionally windowed by date."""
        rows = self._transactions_between(_parse_date(start), _parse_date(end))
        if category:
            wanted = str(category).casefold()
            rows = [r for r in rows if str(r.get("category") or "").casefold() == wanted]
        if kind:
            rows = [r for r in rows if r.get("type") == kind]
        rows.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("created_at") or "")), reverse=True)
        return _envelope(True, f"{len(rows)} transactions", {"transactions": rows[: max(1, limit)]})

    def _transactions_between(self, start: date | None, end: date | None) -> list[dict[str, Any]]:
        clauses = []
        if start:
            clauses.append(f"date=gte.{start.isoformat()}")
        if end:
            clauses.append(f"date=lte.{end.isoformat()}")
        qs = "&".join(clauses) if clauses else None
        return self.repository.list_rows("finance_logs", query_string=qs)

    # ---------- summary ----------

    def monthly_summary(self, month: str | None = None) -> dict[str, Any]:
        """Totals for one month, split by currency then by category, with the
        previous month alongside so the header can show the direction."""
        anchor = _parse_date(month) if month and len(str(month)) > 7 else None
        if anchor is None:
            if month:
                year, mon = str(month).split("-")[:2]
                anchor = date(int(year), int(mon), 1)
            else:
                anchor = _local_today(self.timezone).replace(day=1)
        start = anchor.replace(day=1)
        end = _end_of_month(start)
        prev_start = (start - timedelta(days=1)).replace(day=1)

        current = self._transactions_between(start, end)
        previous = self._transactions_between(prev_start, _end_of_month(prev_start))
        prev_expense = self._totals_by_currency(previous, "expense")

        currencies: dict[str, Any] = {}
        for code in sorted({str(r.get("currency") or "INR").upper() for r in current}):
            scoped = [r for r in current if str(r.get("currency") or "INR").upper() == code]
            expense = sum(_money(r["amount"]) for r in scoped if r.get("type") != "income")
            income = sum(_money(r["amount"]) for r in scoped if r.get("type") == "income")
            was = prev_expense.get(code, 0.0)
            currencies[code] = {
                "expense": round(expense, 2),
                "income": round(income, 2),
                "net": round(income - expense, 2),
                "previous_expense": round(was, 2),
                "change_pct": round((expense - was) / was * 100, 1) if was else None,
                "by_category": self._by_category(scoped, expense),
            }

        return _envelope(
            True,
            f"Summary for {start.strftime('%B %Y')}",
            {
                "month": start.strftime("%Y-%m"),
                "month_label": start.strftime("%B %Y"),
                "currencies": currencies,
                "transaction_count": len(current),
            },
        )

    @staticmethod
    def _totals_by_currency(rows: list[dict[str, Any]], kind: str) -> dict[str, float]:
        totals: dict[str, float] = {}
        for row in rows:
            if kind == "expense" and row.get("type") == "income":
                continue
            if kind == "income" and row.get("type") != "income":
                continue
            code = str(row.get("currency") or "INR").upper()
            totals[code] = totals.get(code, 0.0) + _money(row.get("amount"))
        return totals

    @staticmethod
    def _by_category(rows: list[dict[str, Any]], total: float) -> list[dict[str, Any]]:
        buckets: dict[str, float] = {}
        for row in rows:
            if row.get("type") == "income":
                continue
            name = row.get("category") or "Uncategorised"
            buckets[name] = buckets.get(name, 0.0) + _money(row.get("amount"))
        out = [
            {
                "category": name,
                "amount": round(amount, 2),
                "share_pct": round(amount / total * 100, 1) if total else 0.0,
            }
            for name, amount in buckets.items()
        ]
        out.sort(key=lambda item: item["amount"], reverse=True)
        return out

    # ---------- savings goals ----------

    def goal_progress(self) -> dict[str, Any]:
        """Germany savings goals with their hand-set baseline plus everything
        logged against them. Contributions in another currency are reported
        separately rather than converted at a rate we do not have."""
        goals = self.repository.list_rows("finance_goals")
        linked = [r for r in self.repository.list_rows("finance_logs") if r.get("goal_id")]

        by_goal: dict[str, dict[str, float]] = {}
        for row in linked:
            key = str(row["goal_id"])
            code = str(row.get("currency") or "INR").upper()
            by_goal.setdefault(key, {})
            by_goal[key][code] = by_goal[key].get(code, 0.0) + _money(row.get("amount"))

        out = []
        for goal in goals:
            code = str(goal.get("currency") or "EUR").upper()
            contributions = by_goal.get(str(goal["id"]), {})
            baseline = _money(goal.get("saved_amount"))
            matched = contributions.get(code, 0.0)
            saved = round(baseline + matched, 2)
            target = _money(goal.get("target_amount"))
            other = {c: round(a, 2) for c, a in contributions.items() if c != code}
            out.append({
                "id": goal["id"],
                "goal": goal.get("goal"),
                "currency": code,
                "target_amount": target,
                "baseline_amount": baseline,
                "contributed_amount": round(matched, 2),
                "saved_amount": saved,
                "remaining_amount": round(max(target - saved, 0), 2),
                "progress_pct": round(min(saved / target * 100, 100), 1) if target else 0.0,
                "deadline": goal.get("deadline"),
                "other_currency_contributions": other,
            })
        out.sort(key=lambda g: (g["deadline"] or "9999-12-31", g["goal"] or ""))
        return _envelope(True, f"{len(out)} savings goals", {"goals": out})

    # ---------- recurring charges ----------

    def add_recurring(
        self,
        description: str,
        amount: float,
        *,
        cadence: str = "monthly",
        day_of_month: int | None = None,
        day_of_week: int | None = None,
        category: str | None = None,
        currency: str = "INR",
        kind: str = "expense",
        merchant: str | None = None,
        payment_method: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if not description.strip():
            raise PlannerCoreError("Description is required")
        if cadence not in CADENCES:
            raise PlannerCoreError(f"cadence must be one of {sorted(CADENCES)}")
        if kind not in TRANSACTION_TYPES:
            raise PlannerCoreError(f"type must be one of {sorted(TRANSACTION_TYPES)}")
        value = _money(amount)
        if value <= 0:
            raise PlannerCoreError("Amount must be greater than zero")

        begins = _parse_date(start_date) or _local_today(self.timezone)
        ends = _parse_date(end_date)
        if ends and ends < begins:
            raise PlannerCoreError("end_date cannot be before start_date")
        if cadence == "monthly" and day_of_month is None:
            day_of_month = begins.day
        if cadence == "weekly" and day_of_week is None:
            day_of_week = begins.weekday()
        if day_of_month is not None and not 1 <= int(day_of_month) <= 31:
            raise PlannerCoreError("day_of_month must be between 1 and 31")
        if day_of_week is not None and not 0 <= int(day_of_week) <= 6:
            raise PlannerCoreError("day_of_week must be between 0 (Monday) and 6 (Sunday)")

        row = self.repository.insert_row(
            "finance_recurring",
            {
                "description": description.strip(),
                "amount": value,
                "currency": str(currency).strip().upper() or "INR",
                "type": kind,
                "cadence": cadence,
                "day_of_month": day_of_month,
                "day_of_week": day_of_week,
                "category": _normalize_category(category, kind),
                "merchant": merchant.strip() if merchant else None,
                "payment_method": payment_method.strip() if payment_method else None,
                "start_date": begins.isoformat(),
                "end_date": ends.isoformat() if ends else None,
                "notes": notes,
                "active": True,
            },
        )
        return _envelope(True, f"Recurring {cadence} charge saved — {description.strip()}", {"recurring": row})

    def list_recurring(self, *, include_inactive: bool = False) -> dict[str, Any]:
        rows = self.repository.list_rows("finance_recurring")
        if not include_inactive:
            rows = [r for r in rows if r.get("active")]
        rows.sort(key=lambda r: str(r.get("description") or ""))
        return _envelope(True, f"{len(rows)} recurring charges", {"recurring": rows})

    def update_recurring(self, recurring_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "description", "amount", "currency", "type", "cadence", "day_of_month",
            "day_of_week", "category", "merchant", "payment_method", "start_date",
            "end_date", "active", "notes",
        }
        payload = {key: value for key, value in updates.items() if key in allowed}
        if not payload:
            raise PlannerCoreError("No supported fields to update")
        if "cadence" in payload and payload["cadence"] not in CADENCES:
            raise PlannerCoreError(f"cadence must be one of {sorted(CADENCES)}")
        if "amount" in payload:
            payload["amount"] = _money(payload["amount"])
            if payload["amount"] <= 0:
                raise PlannerCoreError("Amount must be greater than zero")
        payload["updated_at"] = datetime.now(ZoneInfo(self.timezone)).isoformat()
        row = self.repository.update_row("finance_recurring", recurring_id, payload)
        return _envelope(True, "Recurring charge updated", {"recurring": row})

    def delete_recurring(self, recurring_id: str) -> dict[str, Any]:
        self.repository.delete_row("finance_recurring", recurring_id)
        return _envelope(True, "Recurring charge deleted", None)

    def materialize_recurring(self, on_date: str | None = None) -> dict[str, Any]:
        """Turn every recurring rule that has come due into a real passbook
        entry. Safe to run repeatedly: rows already generated for a date are
        skipped, and the unique index on (recurring_id, date) is the backstop."""
        today = _parse_date(on_date) or _local_today(self.timezone)
        rules = [r for r in self.repository.list_rows("finance_recurring") if r.get("active")]
        if not rules:
            return _envelope(True, "No recurring charges due", {"created": []})

        # One lookup for every rule at once, bounded to the catch-up window, so
        # this stays cheap however often the cron runs and however long the
        # passbook gets.
        window_start = (today - timedelta(days=RECURRING_LOOKBACK_DAYS)).isoformat()
        already: dict[str, set[str]] = {}
        for row in self.repository.list_rows(
            "finance_logs",
            {"recurring_id": [str(rule["id"]) for rule in rules]},
            columns="recurring_id,date",
            query_string=f"date=gte.{window_start}",
        ):
            already.setdefault(str(row["recurring_id"]), set()).add(str(row.get("date"))[:10])

        created: list[dict[str, Any]] = []
        for rule in rules:
            due = self._due_dates(rule, today)
            if not due:
                continue
            posted = already.get(str(rule["id"]), set())
            for when in due:
                if when.isoformat() in posted:
                    continue
                created.append(self.repository.insert_row(
                    "finance_logs",
                    {
                        "date": when.isoformat(),
                        "description": rule["description"],
                        "amount": _money(rule.get("amount")),
                        "currency": str(rule.get("currency") or "INR").upper(),
                        "type": rule.get("type") or "expense",
                        "category": rule.get("category"),
                        "merchant": rule.get("merchant"),
                        "payment_method": rule.get("payment_method"),
                        "recurring_id": rule["id"],
                        "notes": rule.get("notes"),
                    },
                ))

        return _envelope(
            True,
            f"{len(created)} recurring charges posted" if created else "No recurring charges due",
            {"created": created},
        )

    def _due_dates(self, rule: Mapping[str, Any], today: date) -> list[date]:
        """Occurrences between the lookback window and today. The window keeps
        the work bounded while still catching up a cron that was down."""
        begins = _parse_date(rule.get("start_date")) or today
        ends = _parse_date(rule.get("end_date"))
        window_start = max(begins, today - timedelta(days=RECURRING_LOOKBACK_DAYS))
        window_end = min(today, ends) if ends else today
        if window_start > window_end:
            return []

        cadence = rule.get("cadence") or "monthly"
        out: list[date] = []

        if cadence == "weekly":
            wanted = rule.get("day_of_week")
            wanted = begins.weekday() if wanted is None else int(wanted)
            cursor = window_start
            while cursor <= window_end:
                if cursor.weekday() == wanted:
                    out.append(cursor)
                cursor += timedelta(days=1)
            return out

        if cadence == "monthly":
            wanted = rule.get("day_of_month")
            wanted = begins.day if wanted is None else int(wanted)
            cursor = window_start.replace(day=1)
            while cursor <= window_end:
                # Rent set to the 31st still posts in February.
                day = min(wanted, _days_in_month(cursor))
                occurrence = cursor.replace(day=day)
                if window_start <= occurrence <= window_end:
                    out.append(occurrence)
                cursor = _end_of_month(cursor) + timedelta(days=1)
            return out

        # Yearly recurs on the anniversary of start_date.
        for year in range(window_start.year, window_end.year + 1):
            day = min(begins.day, _days_in_month(date(year, begins.month, 1)))
            occurrence = date(year, begins.month, day)
            if window_start <= occurrence <= window_end:
                out.append(occurrence)
        return out


def _days_in_month(any_day: date) -> int:
    import calendar

    return calendar.monthrange(any_day.year, any_day.month)[1]


def _end_of_month(any_day: date) -> date:
    return any_day.replace(day=_days_in_month(any_day))


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")
