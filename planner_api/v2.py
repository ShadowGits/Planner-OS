"""v2 API surface: Postgres-backed metrics, reminder cron, and Telegram tick-back.

These routes never touch the Excel workbook. They read and write the v2 tables
through planner_core, so they are fast enough for a dashboard poll and safe for
an unattended cron.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Callable
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from adapters.supabase import SupabaseWorkspaceRepository
from planner_core.repository import PlannerCoreRepository
from planner_core.services import MetricsService, ProjectService, ReminderService, TaskService
from planner_core.telegram import TelegramClient, TelegramError, parse_command, sender_chat_id

logger = logging.getLogger(__name__)


class PlannerCoreBundle:
    """All v2 services bound to one user's active workspace."""

    def __init__(self, repository: PlannerCoreRepository, timezone: str) -> None:
        self.repository = repository
        self.timezone = timezone
        self.tasks = TaskService(repository, timezone)
        self.projects = ProjectService(repository)
        self.metrics = MetricsService(repository, timezone)
        self.reminders = ReminderService(repository, self.metrics, self.tasks, timezone)


def build_core(service_client: Any, user_id: UUID) -> PlannerCoreBundle:
    workspace = SupabaseWorkspaceRepository(service_client).get_active(user_id)
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "WORKSPACE_NOT_FOUND", "message": "No active Planner OS workspace"},
        )
    repository = PlannerCoreRepository(service_client, user_id, workspace.id)
    return PlannerCoreBundle(repository, workspace.timezone)


def _configured_user_id() -> UUID:
    raw = os.environ.get("MCP_USER_ID", "")
    if not raw:
        raise HTTPException(
            status_code=503,
            detail={"code": "NOT_CONFIGURED", "message": "MCP_USER_ID is not configured"},
        )
    return UUID(raw)


def _render_today(core: "PlannerCoreBundle") -> str:
    """Render today's tasks as a tick-box checklist with a done/total header."""
    data = core.tasks.today_checklist()["data"]
    header = f"\U0001F4C5 Today · {data['done_count']}/{data['total_count']} done"
    if not data["items"]:
        return header + "\n\nNothing for today. Add a task or rest up."
    lines = [header, ""]
    for item in data["items"]:
        mark = "✅" if item["done"] else "⬜"
        lines.append(f"{item['title']} {mark}")
    return "\n".join(lines)


def register_v2_routes(api: FastAPI, cloud: Any, current_user: Callable) -> None:
    def _envelope(success: bool, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"success": success, "message": message, "data": data or {}, "errors": []}

    @api.get("/v2/metrics")
    def metrics(user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        return _envelope(
            True,
            "Planner metrics",
            {"snapshot": core.metrics.snapshot(), "flat": core.metrics.flat_snapshot()},
        )

    @api.post("/v2/reminders/run")
    def run_reminders(x_cron_key: str | None = Header(default=None)):
        expected = os.environ.get("CRON_SECRET", "")
        if not expected or not x_cron_key or not secrets.compare_digest(x_cron_key, expected):
            raise HTTPException(
                status_code=401,
                detail={"code": "CRON_KEY_INVALID", "message": "X-Cron-Key header is missing or wrong"},
            )
        core = build_core(cloud.service_client, _configured_user_id())
        telegram = TelegramClient.from_env()
        due = core.reminders.due_reminders()
        sent, failed = [], []
        for reminder in due:
            if telegram is None:
                failed.append({**reminder, "error": "TELEGRAM_NOT_CONFIGURED"})
                continue
            try:
                telegram.send_message(reminder["message"])
                core.reminders.record_sent(reminder["kind"], "telegram", {"message": reminder["message"]})
                sent.append(reminder["kind"])
            except TelegramError as error:
                logger.error("Reminder send failed (%s): %s", reminder["kind"], error)
                failed.append({"kind": reminder["kind"], "error": str(error)})
        return _envelope(True, f"{len(sent)} reminders sent", {"sent": sent, "failed": failed, "due": len(due)})

    @api.post("/v2/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ):
        expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        if not expected or not x_telegram_bot_api_secret_token or not secrets.compare_digest(
            x_telegram_bot_api_secret_token, expected
        ):
            raise HTTPException(
                status_code=401,
                detail={"code": "WEBHOOK_SECRET_INVALID", "message": "Telegram secret token mismatch"},
            )
        update = await request.json()
        allowed_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        chat_id = sender_chat_id(update)
        command = parse_command(update)
        # Telegram retries non-200 responses, so unknown input is acknowledged, not errored.
        if command is None or chat_id is None or chat_id != allowed_chat:
            return _envelope(True, "Ignored")
        core = build_core(cloud.service_client, _configured_user_id())
        action, argument = command
        if action == "done":
            result = core.tasks.complete_by_title(argument, source="telegram")
            if result["success"]:
                reply = result["message"]
            elif "candidates" in result["data"]:
                reply = "Which one? " + "; ".join(result["data"]["candidates"])
            else:
                reply = result["message"]
        elif action == "today":
            reply = _render_today(core)
        else:
            reply = _render_today(core)
            snapshot = core.metrics.snapshot()
            if snapshot["projects"]:
                lines = ["", "Projects:"]
                for project in snapshot["projects"]:
                    lines.append(
                        f"- {project['name']}: {project['completion_pct']}% "
                        f"({project['open_tasks']} open)"
                    )
                reply += "\n" + "\n".join(lines)
        telegram = TelegramClient.from_env()
        if telegram is not None:
            try:
                telegram.send_message(reply)
            except TelegramError as error:
                logger.error("Telegram reply failed: %s", error)
        return _envelope(True, "Handled", {"action": action})
