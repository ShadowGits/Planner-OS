"""Actual work is recorded separately from a task's planned duration."""
from datetime import date
import json
from typing import Any
from urllib.error import HTTPError
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from planner_api.v2 import build_core, _configured_user_id
from planner_core.services import parse_habit_item_id


def database_error_message(error):
    """Classify transport-wrapped RPC errors without exposing SQL response text."""
    if hasattr(error, "_planner_rpc_classification"):
        return error._planner_rpc_classification
    cause = error.__cause__
    if isinstance(cause, HTTPError):
        try:
            data = json.loads(cause.read(8192))
            message = data.get("message", "")
            if message in ("SPLIT_NOT_FOUND", "WORK_NOT_FOUND"):
                error._planner_rpc_classification = message
                return message
            for prefix in ("SPLIT_INVALID:", "WORK_INVALID:"):
                if isinstance(message, str) and message.startswith(prefix):
                    result = prefix + " The entry is no longer valid. Refresh or correct it and try again."
                    error._planner_rpc_classification = result
                    return result
            if data.get("code") in ("PGRST202", "PGRST205", "42883", "42P01"):
                error._planner_rpc_classification = "schema cache"
                return "schema cache"
        except (ValueError, AttributeError, OSError):
            pass
    return str(error)


def planned_seconds(task):
    minutes = int(task.get('estimated_minutes') or 30)
    budget = (task.get('metadata') or {}).get('_work_budget') or {}
    if str(budget.get('minutes')) == str(minutes):
        try:
            return max(1, int(budget['seconds']))
        except (KeyError, TypeError, ValueError):
            pass
    return minutes * 60


def attach_work_progress(data, repo):
    """One scoped read, without making the existing Day feed depend on a migration."""
    items = data.get('items', [])
    if not items:
        return
    refs = [str(item['id']) for item in items]
    sessions = []
    try:
        for start in range(0, len(refs), 100):
            sessions.extend(repo.list_rows('task_work_sessions', {'task_ref': refs[start:start+100]}, query_string='order=created_at.asc', columns='task_ref,seconds,planned_seconds,created_at', strict=True))
    except Exception as error:
        if any(term in str(error).lower() for term in ('pgrst202', 'pgrst205', 'does not exist', 'schema cache')):
            return
        raise
    # Day-view DTOs omit task metadata. Read exact split budgets in one batch.
    split_ids = [str(item['id']) for item in items if item.get('parent_task_id')]
    regular = []
    for start in range(0, len(split_ids), 100):
        regular.extend(repo.list_rows('planner_tasks', {'id': split_ids[start:start+100]}, columns='id,estimated_minutes,work_budget:metadata->_work_budget', strict=True))
    tasks = {str(row['id']): {**row, 'metadata': {'_work_budget': row.get('work_budget')}} for row in regular}
    by_ref = {}
    for session in sessions:
        by_ref.setdefault(session['task_ref'], []).append(session)
    for item in items:
        rows = by_ref.get(str(item['id']), [])
        planned = planned_seconds(tasks.get(str(item['id']), item))
        if item['id'].startswith('habit:') and rows:
            planned = int(rows[0]['planned_seconds'])
        item.update(planned_seconds=planned, worked_seconds=sum(int(row['seconds']) for row in rows))


class WorkEntry(BaseModel):
    request_id: UUID
    seconds: int = Field(ge=0, le=86400)
    source: str = Field(pattern="^(manual|timer)$")
    finish: bool = False
    split: bool = False
    remainder_date: date | None = None
    remainder_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class TaskSplit(BaseModel):
    request_id: UUID
    first_seconds: int = Field(gt=0, le=86400)
    expected_remaining: int = Field(gt=1, le=86400)


def register_work_log_routes(api: FastAPI, cloud: Any, authorize: Any):
    def core():
        return build_core(cloud.service_client, _configured_user_id())

    def unavailable(error):
        message = database_error_message(error).lower()
        if any(term in message for term in ("pgrst202", "pgrst205", "does not exist", "schema cache")):
            raise HTTPException(409, detail={"message": "Time logging needs database migration 0035. Your saved timer entry is still on this device."}) from error
        raise HTTPException(503, detail={"message": "Time could not be saved. Your entry is kept; retry when connected."}) from error

    @api.post("/v2/day/tasks/{task_id}/split")
    def split_task(task_id: UUID, body: TaskSplit, x_app_key: str | None = Header(default=None)):
        authorize(x_app_key)
        if body.first_seconds >= body.expected_remaining:
            raise HTTPException(400, detail={"message": "Both sessions need some remaining work."})
        try:
            result = core().repository.call_function("planner_split_task", {
                "p_request_id": str(body.request_id), "p_task_id": str(task_id),
                "p_first_seconds": body.first_seconds, "p_expected_remaining": body.expected_remaining,
            })
        except Exception as error:
            message = database_error_message(error)
            if "SPLIT_INVALID:" in message:
                raise HTTPException(400, detail={"message": message.split("SPLIT_INVALID:", 1)[1].split('"', 1)[0].strip()}) from error
            if "SPLIT_NOT_FOUND" in message:
                raise HTTPException(404, detail={"message": "This task is no longer available."}) from error
            if any(term in message.lower() for term in ("pgrst202", "does not exist", "schema cache")):
                raise HTTPException(409, detail={"message": "Splitting needs database migration 0036. The original task is unchanged."}) from error
            raise HTTPException(503, detail={"message": "Split could not be confirmed. Retry this split to check the same request; no extra sessions will be created."}) from error
        return {"success": True, "message": "Task split", "data": result}

    @api.get("/v2/day/tasks/{task_ref}/work")
    def work_info(task_ref: str, x_app_key: str | None = Header(default=None)):
        authorize(x_app_key)
        bundle = core()
        repo = bundle.repository
        occurrence = parse_habit_item_id(task_ref)
        blocks = []
        if occurrence:
            habit_id, rule_day = occurrence
            habit = repo.get_row("habits", habit_id)
            if not habit:
                raise HTTPException(404, detail={"message": "This habit is no longer available."})
            overrides = repo.list_rows("habit_overrides", {"habit_id": habit_id, "on_date": rule_day.isoformat()}, strict=True)
            override = overrides[0] if overrides else {}
            shown = override.get("moved_to") or rule_day.isoformat()
            done = bool(repo.list_rows("task_completions", {"recurrence_key": habit["recurrence_key"], "completed_on": shown}, strict=True))
            task = {"id": task_ref, "title": habit["title"], "scheduled_date": str(shown), "start_time": override.get("start_time") or habit.get("start_time"), "estimated_minutes": override.get("estimated_minutes") or habit.get("estimated_minutes") or 30, "done": done, "is_habit": True}
        else:
            try:
                UUID(task_ref)
            except ValueError:
                raise HTTPException(400, detail={"message": "Invalid task."})
            task = repo.get_row("planner_tasks", task_ref)
            if not task:
                raise HTTPException(404, detail={"message": "This task is no longer available."})
            task = {**task, "done": task.get("status") == "done", "is_habit": False}
            blocks = repo.list_rows("planner_tasks", {"parent_task_id": task_ref}, strict=True)
        refs = [task_ref] + [str(b["id"]) for b in blocks]
        try:
            sessions = repo.list_rows("task_work_sessions", {"task_ref": refs}, query_string="order=created_at.asc", strict=True)
        except Exception as error:
            unavailable(error)
        planned = planned_seconds(task)
        if occurrence and sessions:
            planned = int(sessions[0]["planned_seconds"])
        worked = sum(int(s["seconds"]) for s in sessions)
        return {"success": True, "data": {"task": task, "blocks": blocks, "timezone": bundle.timezone, "planned_seconds": planned, "worked_seconds": worked, "remaining_seconds": max(0, planned-worked), "sessions": [{k: s.get(k) for k in ("id", "seconds", "source", "created_at")} for s in sessions]}}

    @api.post("/v2/day/tasks/{task_ref}/work")
    def log_work(task_ref: str, body: WorkEntry, x_app_key: str | None = Header(default=None)):
        authorize(x_app_key)
        if body.split and body.remainder_date is None:
            raise HTTPException(400, detail={"message": "Choose a date for the remaining work."})
        try:
            result = core().repository.call_function("planner_log_work", {
                "p_request_id": str(body.request_id), "p_task_ref": task_ref,
                "p_seconds": body.seconds, "p_source": body.source,
                "p_finish": body.finish, "p_split": body.split,
                "p_remainder_date": body.remainder_date.isoformat() if body.remainder_date else None,
                "p_remainder_time": body.remainder_time,
            })
        except Exception as error:
            message = database_error_message(error)
            if "WORK_INVALID:" in message:
                raise HTTPException(400, detail={"message": message.split("WORK_INVALID:", 1)[1].split('"', 1)[0].strip()}) from error
            if "WORK_NOT_FOUND" in message:
                raise HTTPException(404, detail={"message": "This task is no longer available."}) from error
            unavailable(error)
        return {"success": True, "message": "Time saved", "data": result}
