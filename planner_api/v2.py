"""v2 API surface: Postgres-backed metrics, reminder cron, and Telegram tick-back.

These routes never touch the Excel workbook. They read and write the v2 tables
through planner_core, so they are fast enough for a dashboard poll and safe for
an unattended cron.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile

from adapters.supabase import SupabaseWorkspaceRepository
from planner_core.repository import PlannerCoreRepository
from planner_core.services import (
    FinanceService,
    GoalService,
    MetricsService,
    ProjectService,
    ReminderService,
    TaskService,
)
from planner_core.telegram import TelegramClient, TelegramError, parse_command, sender_chat_id

from planner_integrations.google_drive import (
    create_drive_document,
    get_drive_service,
    get_or_create_project_folder,
    upload_drive_file,
)

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
        self.goals = GoalService(repository)
        self.finance = FinanceService(repository, timezone)


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
            {"snapshot": (s := core.metrics.snapshot()), "flat": core.metrics.flat_snapshot(s)},
        )

    @api.post("/v2/google-calendar/connect")
    def connect_google_v2(user=Depends(current_user)):
        try:
            from planner_api.app import envelope
            workspace = cloud.workspaces(user).get_active(user.user_id)
            if not workspace:
                raise ValueError("No active workspace found")
            context = cloud.context(user, workspace.id)
            result = cloud.google_oauth_for_user(user).start(context)
            return envelope(
                True,
                "Google Calendar authorization started",
                data={"authorization_url": result.authorization_url, "expires_in_seconds": result.expires_in_seconds},
                operation="google_calendar_connect",
                target="google_calendar",
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @api.post("/v2/reminders/run")
    def run_reminders(x_cron_key: str | None = Header(default=None)):
        expected = os.environ.get("CRON_SECRET", "")
        if not expected or not x_cron_key or not secrets.compare_digest(x_cron_key, expected):
            raise HTTPException(
                status_code=401,
                detail={"code": "CRON_KEY_INVALID", "message": "X-Cron-Key header is missing or wrong"},
            )
        from planner_core.push import send_push_to_all

        user_id = _configured_user_id()
        core = build_core(cloud.service_client, user_id)
        telegram = TelegramClient.from_env()

        # Rent, subscriptions and EMIs post themselves on the back of this
        # cron rather than needing a scheduler job of their own. Idempotent, so
        # a schedule that fires more than once a day charges nothing twice.
        # Never let a finance problem stop the reminders going out.
        try:
            posted = len(core.finance.materialize_recurring()["data"]["created"])
        except Exception as error:
            logger.error("Recurring charges failed to post: %s", error)
            posted = 0

        due = core.reminders.due_reminders()
        sent, failed = [], []
        for reminder in due:
            # Send via push notifications (macOS/iOS/iPadOS popups)
            push_title = {
                "morning_brief": "☀️ Morning Brief",
                "evening_nudge": "🌙 Evening Nudge",
                "deadline_alert": "⚠️ Deadline Alert",
            }.get(reminder["kind"], "📋 Planner OS")
            try:
                push_result = send_push_to_all(
                    cloud.service_client,
                    str(user_id),
                    str(core.repository.workspace_id),
                    push_title,
                    reminder["message"],
                    url="/",
                )
                if push_result["sent"] > 0:
                    core.reminders.record_sent(reminder["kind"], "push", {"message": reminder["message"], **push_result})
                    sent.append(reminder["kind"])
            except Exception as push_err:
                logger.error("Push send failed (%s): %s", reminder["kind"], push_err)

            # Also try Telegram as fallback
            if reminder["kind"] not in sent and telegram is not None:
                try:
                    telegram.send_message(reminder["message"])
                    core.reminders.record_sent(reminder["kind"], "telegram", {"message": reminder["message"]})
                    sent.append(reminder["kind"])
                except TelegramError as error:
                    logger.error("Telegram send failed (%s): %s", reminder["kind"], error)
                    failed.append({"kind": reminder["kind"], "error": str(error)})
            elif reminder["kind"] not in sent:
                failed.append({**reminder, "error": "NO_PUSH_OR_TELEGRAM"})

        return _envelope(
            True,
            f"{len(sent)} reminders sent",
            {"sent": sent, "failed": failed, "due": len(due), "recurring_posted": posted},
        )

    # ── Push subscription management ──────────────────────────────────────

    @api.post("/v2/push/subscribe")
    def push_subscribe(request_body: dict, user=Depends(current_user)):
        endpoint = request_body.get("endpoint")
        keys = request_body.get("keys", {})
        p256dh = keys.get("p256dh")
        auth = keys.get("auth")
        device_label = request_body.get("device_label", "")

        if not endpoint or not p256dh or not auth:
            raise HTTPException(status_code=400, detail="Missing endpoint or keys")

        user_id = _configured_user_id()
        core = build_core(cloud.service_client, user_id)

        # Upsert: delete existing sub for same endpoint, then insert
        try:
            existing = cloud.service_client.select(
                "push_subscriptions",
                filters={"user_id": str(user_id), "endpoint": endpoint},
            )
            if existing:
                cloud.service_client.delete(
                    "push_subscriptions",
                    filters={"id": existing[0]["id"]},
                )
        except Exception:
            pass

        cloud.service_client.insert("push_subscriptions", {
            "user_id": str(user_id),
            "workspace_id": str(core.repository.workspace_id),
            "endpoint": endpoint,
            "p256dh": p256dh,
            "auth": auth,
            "device_label": device_label,
        })

        return _envelope(True, "Push subscription saved")

    @api.post("/v2/push/unsubscribe")
    def push_unsubscribe(request_body: dict, user=Depends(current_user)):
        endpoint = request_body.get("endpoint")
        if not endpoint:
            raise HTTPException(status_code=400, detail="Missing endpoint")

        user_id = _configured_user_id()
        try:
            cloud.service_client.delete(
                "push_subscriptions",
                filters={"user_id": str(user_id), "endpoint": endpoint},
            )
        except Exception:
            pass
        return _envelope(True, "Push subscription removed")

    @api.get("/v2/push/vapid-key")
    def get_vapid_key():
        key = os.environ.get("VAPID_PUBLIC_KEY", "")
        if not key:
            raise HTTPException(status_code=503, detail="VAPID keys not configured")
        return _envelope(True, "VAPID public key", {"public_key": key})

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

    @api.get("/v2/projects/{project_id}/files")
    def list_project_files(project_id: str, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        files = core.repository.list_rows("project_files", {"project_id": project_id})
        
        # Always fetch files from Google Drive if configured, and merge with database files
        drive_file_rows = []
        project = core.repository.get_row("projects", project_id)
        if project:
            drive_service = get_drive_service(user, core.repository.gateway, core.repository.workspace_id, allow_service_account=True)
            if drive_service:
                folder_id = get_or_create_project_folder(drive_service, project["name"], project.get("drive_folder_id"))
                if folder_id:
                    try:
                        drive_q = f"'{folder_id}' in parents and trashed = false"
                        res = drive_service.files().list(q=drive_q, fields="files(id, name, webViewLink, mimeType)").execute()
                        drive_files = res.get("files", [])
                        for f in drive_files:
                            is_excel = "spreadsheet" in f.get("mimeType", "") or any(ext in f.get("name", "").lower() for ext in [".xls", ".xlsx", ".csv"])
                            ftype = "excel" if is_excel else "text"
                            fid = f["id"]
                            embed = f"https://drive.google.com/file/d/{fid}/preview"
                            # Skip if this drive file is already tracked in the database
                            if any(db_f.get("drive_file_id") == fid for db_f in files):
                                continue
                                
                            drive_file_rows.append({
                                "id": fid,
                                "project_id": project_id,
                                "name": f.get("name"),
                                "file_type": ftype,
                                "drive_file_id": fid,
                                "drive_web_view_link": f.get("webViewLink"),
                                "drive_embed_link": embed
                            })
                    except Exception as e:
                        logger.warning(f"Failed listing files from Drive folder {folder_id}: {e}")

        all_files = files + drive_file_rows
        return _envelope(True, "Project files retrieved", {"files": all_files})

    @api.post("/v2/projects/{project_id}/files/create-document")
    async def create_project_document(project_id: str, request: Request, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        body = await request.json()
        name = body.get("name", "Untitled Document")
        file_type = body.get("file_type", "text")

        project = core.repository.get_row("projects", project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        drive_service = get_drive_service(user, core.repository.gateway, core.repository.workspace_id)
        if not drive_service:
            # Fallback if Google Drive service is not authenticated
            try:
                file_row = core.repository.insert_row("project_files", {
                    "project_id": project_id,
                    "name": name,
                    "file_type": file_type,
                    "drive_file_id": "dummy_id",
                    "drive_web_view_link": "#",
                    "drive_embed_link": "#"
                })
            except Exception:
                file_row = {"id": "dummy_id", "project_id": project_id, "name": name, "file_type": file_type, "drive_file_id": "dummy_id", "drive_web_view_link": "#", "drive_embed_link": "#"}
            return _envelope(True, "File metadata saved (Drive unconfigured)", {"file": file_row})

        folder_id = get_or_create_project_folder(drive_service, project["name"], project.get("drive_folder_id"))
        if folder_id and folder_id != project.get("drive_folder_id"):
            try:
                core.repository.update_row("projects", project_id, {"drive_folder_id": folder_id})
            except Exception:
                pass

        doc_res = create_drive_document(drive_service, folder_id, name, file_type)
        if not doc_res:
            fid = f"doc_{project_id[:8]}_{int(datetime.now().timestamp())}"
            folder_url = f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else "https://drive.google.com/drive/u/0/my-drive"
            doc_res = {
                "drive_file_id": fid,
                "name": name,
                "drive_web_view_link": folder_url,
                "drive_embed_link": folder_url
            }

        try:
            file_row = core.repository.insert_row("project_files", {
                "project_id": project_id,
                "name": name,
                "file_type": file_type,
                "drive_file_id": doc_res["drive_file_id"],
                "drive_web_view_link": doc_res["drive_web_view_link"],
                "drive_embed_link": doc_res["drive_embed_link"]
            })
        except Exception as insert_err:
            logger.warning(f"Could not insert project_files row into Supabase: {insert_err}")
            file_row = {
                "id": doc_res["drive_file_id"],
                "project_id": project_id,
                "name": name,
                "file_type": file_type,
                "drive_file_id": doc_res["drive_file_id"],
                "drive_web_view_link": doc_res["drive_web_view_link"],
                "drive_embed_link": doc_res["drive_embed_link"]
            }

        return _envelope(True, f"Created Google {file_type.capitalize()} document", {"file": file_row})

    @api.post("/v2/projects/{project_id}/files/upload")
    async def upload_project_file(project_id: str, file: UploadFile = File(...), user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        project = core.repository.get_row("projects", project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        file_bytes = await file.read()
        filename = file.filename or "uploaded_file"
        content_type = file.content_type or "application/octet-stream"

        drive_service = get_drive_service(user, core.repository.gateway, core.repository.workspace_id)
        try:
            folder_id = get_or_create_project_folder(drive_service, project["name"], project.get("drive_folder_id")) if drive_service else None
            if folder_id and folder_id != project.get("drive_folder_id"):
                try:
                    core.repository.update_row("projects", project_id, {"drive_folder_id": folder_id})
                except Exception:
                    pass

            res = upload_drive_file(drive_service, folder_id, filename, file_bytes, content_type) if drive_service and folder_id else None
        except Exception as drive_err:
            return _envelope(False, f"Google Drive API Error: {str(drive_err)}")

        if not res:
            is_excel = any(ext in filename.lower() for ext in ['.xls', '.xlsx', '.csv'])
            file_type = "excel" if is_excel else "text"
            fid = f"file_{project_id[:8]}_{int(datetime.now().timestamp())}"
            folder_url = f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else "https://drive.google.com/drive/u/0/my-drive"
            res = {
                "drive_file_id": fid,
                "name": filename,
                "file_type": file_type,
                "drive_web_view_link": folder_url,
                "drive_embed_link": folder_url
            }

        try:
            file_row = core.repository.insert_row("project_files", {
                "project_id": project_id,
                "name": filename,
                "file_type": res["file_type"],
                "drive_file_id": res["drive_file_id"],
                "drive_web_view_link": res["drive_web_view_link"],
                "drive_embed_link": res["drive_embed_link"]
            })
        except Exception as insert_err:
            logger.warning(f"Could not insert project_files row into Supabase: {insert_err}")
            file_row = {
                "id": res["drive_file_id"],
                "project_id": project_id,
                "name": filename,
                "file_type": res["file_type"],
                "drive_file_id": res["drive_file_id"],
                "drive_web_view_link": res["drive_web_view_link"],
                "drive_embed_link": res["drive_embed_link"]
            }

        return _envelope(True, f"Uploaded {filename} to Google Drive", {"file": file_row})

    @api.delete("/v2/projects/{project_id}/files/{file_id}")
    def delete_project_file(project_id: str, file_id: str, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        
        # Also attempt to delete from Drive directly
        project = core.repository.get_row("projects", project_id)
        drive_service = get_drive_service(user, core.repository.gateway, core.repository.workspace_id)
        if drive_service:
            try:
                # Try to trash the file in drive instead of permanent delete, or just delete
                drive_service.files().update(fileId=file_id, body={'trashed': True}).execute()
            except Exception as e:
                logger.warning(f"Could not trash file {file_id} in Drive: {e}")

        try:
            core.repository.delete_row("project_files", file_id)
        except Exception:
            try:
                cloud.service_client.delete("project_files", {"drive_file_id": file_id})
            except Exception as e:
                logger.warning(f"Could not delete project file row {file_id}: {e}")
        return _envelope(True, "File deleted")


    @api.get("/v2/projects/{project_id}/files/{file_id}/download")
    def download_project_file(project_id: str, file_id: str, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        drive_service = get_drive_service(user, core.repository.gateway, core.repository.workspace_id, allow_service_account=True)
        if not drive_service:
            raise HTTPException(status_code=401, detail="Google Drive not authenticated")
            
        from planner_integrations.google_drive import download_drive_file
        file_bytes = download_drive_file(drive_service, file_id)
        if file_bytes is None:
            raise HTTPException(status_code=404, detail="File not found or could not be downloaded")
            
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=file_bytes)


    @api.post("/v2/projects/{project_id}/tasks")
    def create_project_task(project_id: str, body: dict, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)

        title = body.get("title")
        if not title:
            raise HTTPException(status_code=400, detail={"code": "MISSING_TITLE", "message": "Task title is required"})

        date = body.get("scheduled_date")
        milestone_id = body.get("milestone_id")

        try:
            result = core.tasks.create_task(
                title=title,
                project_id=project_id,
                scheduled_date=date,
                milestone_id=milestone_id,
            )
            return _envelope(True, "Project task created", result["data"])
        except Exception as e:
            logger.error(f"Failed to create project task: {e}")
            raise HTTPException(status_code=500, detail={"code": "CREATE_FAILED", "message": str(e)})

    @api.get("/v2/projects/{project_id}/tasks")
    def get_project_tasks(project_id: str, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        # Tasks only. Slots are how a task gets onto the timeline and the
        # calendar; the dashboard lists the work itself, so a task split into
        # three sittings appears once rather than four times.
        tasks = core.repository.list_rows(
            "planner_tasks",
            {"project_id": project_id},
            query_string="parent_task_id=is.null",
        )
        return _envelope(True, "Project tasks retrieved", {"tasks": tasks})

    # ── Milestones ────────────────────────────────────────────────────────

    @api.get("/v2/projects/{project_id}/milestones")
    def get_project_milestones(project_id: str, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        milestones = core.repository.list_rows("milestones", {"project_id": project_id})
        sorted_milestones = sorted(milestones, key=lambda m: (m.get("sort_order") or 0, str(m.get("target_date") or "9999")))
        return _envelope(True, "Project milestones", {"milestones": sorted_milestones})

    @api.post("/v2/projects/{project_id}/milestones")
    def create_project_milestone(project_id: str, body: dict, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        name = body.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail={"code": "MISSING_NAME", "message": "Milestone name is required"})
        try:
            result = core.projects.add_milestone(
                project_id,
                name,
                target_date=body.get("target_date"),
                notes=body.get("notes"),
            )
            return _envelope(True, "Milestone created", result["data"])
        except Exception as e:
            logger.error(f"Failed to create milestone: {e}")
            raise HTTPException(status_code=500, detail={"code": "CREATE_FAILED", "message": str(e)})

    @api.get("/v2/study/topics")
    def get_study_topics(user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        topics = core.repository.list_rows("study_topics")
        return _envelope(True, "Study topics retrieved", {"topics": topics})

    @api.get("/v2/study/logs")
    def get_study_logs(user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        logs = core.repository.list_rows("study_logs")
        return _envelope(True, "Study logs retrieved", {"logs": logs})

    @api.get("/v2/books")
    def get_books(user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        books = core.repository.list_rows("books")
        return _envelope(True, "Books retrieved", {"books": books})

    @api.get("/v2/germany/documents")
    def get_germany_documents(user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        documents = core.repository.list_rows("germany_documents")
        return _envelope(True, "Germany documents retrieved", {"documents": documents})

    @api.get("/v2/finance/goals")
    def get_finance_goals(user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        goals = core.repository.list_rows("finance_goals")
        return _envelope(True, "Finance goals retrieved", {"goals": goals})

    @api.get("/v2/finance/goals/progress")
    def get_finance_goal_progress(user=Depends(current_user)):
        """Goals with logged contributions folded in, so saved_amount reflects
        what was actually transferred rather than what was last typed in."""
        core = build_core(cloud.service_client, user.user_id)
        return _envelope(True, "Goal progress", core.finance.goal_progress()["data"])

    @api.get("/v2/finance/summary")
    def get_finance_summary(month: str | None = None, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        return _envelope(True, "Finance summary", core.finance.monthly_summary(month)["data"])

    @api.get("/v2/finance/transactions")
    def get_finance_transactions(
        start: str | None = None,
        end: str | None = None,
        category: str | None = None,
        limit: int = 200,
        user=Depends(current_user),
    ):
        core = build_core(cloud.service_client, user.user_id)
        result = core.finance.list_transactions(start=start, end=end, category=category, limit=limit)
        return _envelope(True, result["message"], result["data"])

    @api.post("/v2/finance/recurring/run")
    def run_recurring_charges(x_cron_key: str | None = Header(default=None)):
        """Cron hook: post any rent/subscription/EMI that has fallen due.
        Idempotent, so a daily schedule with retries cannot double-charge."""
        expected = os.environ.get("CRON_SECRET", "")
        if not expected or not x_cron_key or not secrets.compare_digest(x_cron_key, expected):
            raise HTTPException(
                status_code=401,
                detail={"code": "CRON_KEY_INVALID", "message": "X-Cron-Key header is missing or wrong"},
            )
        core = build_core(cloud.service_client, _configured_user_id())
        result = core.finance.materialize_recurring()
        return _envelope(True, result["message"], result["data"])

    @api.post("/v2/admin/cleanup-duplicates")
    async def cleanup_duplicate_folders(user=Depends(current_user)):
        """Temporary endpoint to delete duplicate empty project folders generated during the scope bug."""
        try:
            import os, json
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
            creds_file = os.environ.get("GCP_SERVICE_ACCOUNT_FILE")
            
            if creds_json:
                info = json.loads(creds_json)
                creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
            elif creds_file and os.path.exists(creds_file):
                creds = service_account.Credentials.from_service_account_file(creds_file, scopes=["https://www.googleapis.com/auth/drive"])
            else:
                raise Exception("No Service Account credentials found to run cleanup.")

            service = build("drive", "v3", credentials=creds)
            ROOT = "11BSxfqTZmGOEDONsfpfuKtNHtR9dEFZi"
            q = f"mimeType='application/vnd.google-apps.folder' and '{ROOT}' in parents and trashed=false"
            res = service.files().list(q=q, fields="files(id, name, createdTime)", orderBy="createdTime asc").execute()
            folders = res.get("files", [])

            seen = set()
            deleted_ids = []
            for f in folders:
                name = f["name"]
                if name in seen:
                    try:
                        service.files().delete(fileId=f["id"]).execute()
                        deleted_ids.append(f["id"])
                    except Exception as e:
                        logger.warning(f"Failed to delete duplicate folder {name} ({f['id']}): {e}")
                else:
                    seen.add(name)

            return _envelope(True, f"Cleanup complete. Deleted {len(deleted_ids)} duplicate folders.", {"deleted": deleted_ids})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
