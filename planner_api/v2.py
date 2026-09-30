"""v2 API surface: Postgres-backed metrics, reminder cron, and Telegram tick-back.

These routes never touch the Excel workbook. They read and write the v2 tables
through planner_core, so they are fast enough for a dashboard poll and safe for
an unattended cron.
"""

from __future__ import annotations

import logging
import os
import secrets
import re
import time
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile

from adapters.supabase import SupabaseWorkspaceRepository
from planner_core.repository import PlannerCoreError, PlannerCoreRepository
from planner_core.services import (
    FinanceService,
    HabitService,
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
        self.habits = HabitService(repository, timezone)
        self.tasks = TaskService(repository, timezone, habits=self.habits)
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
            push_title = reminder.get("title") or {
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
                    url=reminder.get("url", "/"),
                    # Both warnings for one task share a tag, so the five
                    # minute one replaces the thirty minute one instead of
                    # leaving two entries to clear.
                    tag=reminder.get("tag"),
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
        from planner_core.push import validate_push_subscription
        try:
            endpoint, p256dh, auth = validate_push_subscription(request_body)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid push subscription") from error
        device_label = str(request_body.get("device_label", ""))[:200]
        user_id = user.user_id
        core = build_core(cloud.service_client, user_id)

        # Upsert: delete existing sub for same endpoint, then insert
        try:
            existing = cloud.service_client.select(
                "push_subscriptions",
                filters={"user_id": str(user_id), "workspace_id": str(core.repository.workspace_id), "endpoint": endpoint},
            )
            if existing:
                cloud.service_client.delete(
                    "push_subscriptions",
                    filters={"id": existing[0]["id"], "user_id": str(user_id), "workspace_id": str(core.repository.workspace_id)},
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

        user_id = user.user_id
        core = build_core(cloud.service_client, user_id)
        try:
            cloud.service_client.delete(
                "push_subscriptions",
                filters={"user_id": str(user_id), "workspace_id": str(core.repository.workspace_id), "endpoint": endpoint},
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

    def _project(core, project_id):
        project = core.repository.get_row("projects", project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    def _drive(core, user):
        service = get_drive_service(user, core.repository.gateway, core.repository.workspace_id)
        if service is None:
            raise HTTPException(status_code=409, detail="Connect Google Drive for this workspace first")
        return service

    def _folder(core, project_id, project, service):
        folder_id = get_or_create_project_folder(service, project["name"], project.get("drive_folder_id"))
        if not folder_id:
            raise HTTPException(status_code=502, detail="Project folder could not be created")
        if folder_id != project.get("drive_folder_id"):
            core.repository.update_row("projects", project_id, {"drive_folder_id": folder_id})
        return folder_id

    def _file_reference(core, project_id, project, file_id, service):
        # Accept the database UUID or an untracked Drive ID shown in the
        # project folder listing. Never operate on an arbitrary OAuth-visible
        # file just because the caller knows its ID.
        rows = core.repository.list_rows("project_files", {"project_id": project_id}, strict=True)
        row = next((r for r in rows if r.get("id") == file_id or r.get("drive_file_id") == file_id), None)
        drive_id = row.get("drive_file_id") if row else file_id
        folder_id = project.get("drive_folder_id")
        if not folder_id or not drive_id:
            raise HTTPException(status_code=404, detail="Project file not found")
        try:
            metadata = service.files().get(fileId=drive_id, fields="id,name,parents,trashed").execute()
        except Exception as error:
            raise HTTPException(status_code=404, detail="Project file not found") from error
        if metadata.get("trashed") or folder_id not in metadata.get("parents", []):
            raise HTTPException(status_code=404, detail="Project file not found")
        return drive_id, row, metadata

    @api.get("/v2/projects/{project_id}/files")
    def list_project_files(project_id: str, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        project = _project(core, project_id)
        files = core.repository.list_rows("project_files", {"project_id": project_id}, strict=True)
        folder_id = project.get("drive_folder_id")
        service = get_drive_service(user, core.repository.gateway, core.repository.workspace_id)
        if service and folder_id:
            try:
                if not re.fullmatch(r"[A-Za-z0-9_-]+", folder_id):
                    raise ValueError("Invalid stored folder ID")
                page_token = None
                tracked = {row.get("drive_file_id") for row in files}
                while True:
                    res = service.files().list(q=f"'{folder_id}' in parents and trashed = false",
                                              fields="files(id,name,webViewLink,mimeType),nextPageToken",
                                              pageToken=page_token, pageSize=100).execute()
                    for item in res.get("files", []):
                        fid = item["id"]
                        if fid not in tracked:
                            files.append({"id": fid, "project_id": project_id, "name": item.get("name"),
                                          "file_type": "excel" if "spreadsheet" in item.get("mimeType", "") else "text",
                                          "drive_file_id": fid, "drive_web_view_link": item.get("webViewLink"),
                                          "drive_embed_link": f"https://drive.google.com/file/d/{fid}/preview"})
                    page_token = res.get("nextPageToken")
                    if not page_token:
                        break
            except Exception as error:
                logger.warning("Project Drive listing failed (%s)", type(error).__name__)
                raise HTTPException(status_code=502, detail="Project Drive files could not be listed") from error
        return _envelope(True, "Project files retrieved", {"files": files})

    def _save_file(core, project_id, name, file_type, result):
        if not result or not result.get("drive_file_id"):
            raise HTTPException(status_code=502, detail="Google Drive did not create the file")
        # A database failure remains a failure; never invent a successful row.
        return core.repository.insert_row("project_files", {
            "project_id": project_id, "name": name, "file_type": file_type,
            "drive_file_id": result["drive_file_id"],
            "drive_web_view_link": result.get("drive_web_view_link"),
            "drive_embed_link": result.get("drive_embed_link"),
        })

    @api.post("/v2/projects/{project_id}/files/create-document")
    def create_project_document(project_id: str, body: dict, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        project = _project(core, project_id)
        name, file_type = body.get("name", "Untitled Document"), body.get("file_type", "text")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 300 or file_type not in {"text", "excel"}:
            raise HTTPException(status_code=400, detail="Invalid document name or type")
        service = _drive(core, user)
        try:
            folder_id = _folder(core, project_id, project, service)
            result = create_drive_document(service, folder_id, name, file_type)
            row = _save_file(core, project_id, name, file_type, result)
        except HTTPException:
            raise
        except Exception as error:
            logger.error("Project document creation failed (%s)", type(error).__name__)
            raise HTTPException(status_code=502, detail="Project document could not be saved") from error
        return _envelope(True, "Google document created", {"file": row})

    @api.post("/v2/projects/{project_id}/files/upload")
    async def upload_project_file(project_id: str, file: UploadFile = File(...), user=Depends(current_user)):
        import anyio.to_thread
        max_size = 20 * 1024 * 1024
        file_bytes = await file.read(max_size + 1)
        if len(file_bytes) > max_size:
            raise HTTPException(status_code=413, detail="Files must be 20 MB or smaller")
        filename = file.filename or "uploaded_file"
        if len(filename) > 300:
            raise HTTPException(status_code=400, detail="File name is too long")

        def upload():
            core = build_core(cloud.service_client, user.user_id)
            project = _project(core, project_id)
            service = _drive(core, user)
            try:
                folder_id = _folder(core, project_id, project, service)
                result = upload_drive_file(service, folder_id, filename, file_bytes,
                                           file.content_type or "application/octet-stream")
                return _save_file(core, project_id, filename, result["file_type"] if result else "other", result)
            except HTTPException:
                raise
            except Exception as error:
                logger.error("Project upload failed (%s)", type(error).__name__)
                raise HTTPException(status_code=502, detail="Project file could not be uploaded") from error

        row = await anyio.to_thread.run_sync(upload)
        return _envelope(True, "Project file uploaded", {"file": row})

    @api.delete("/v2/projects/{project_id}/files/{file_id}")
    def delete_project_file(project_id: str, file_id: str, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        project = _project(core, project_id)
        service = _drive(core, user)
        drive_id, row, _ = _file_reference(core, project_id, project, file_id, service)
        try:
            service.files().update(fileId=drive_id, body={"trashed": True}).execute()
            if row:
                core.repository.delete_row("project_files", row["id"])
        except Exception as error:
            logger.error("Project file deletion failed (%s)", type(error).__name__)
            raise HTTPException(status_code=502, detail="Project file could not be deleted") from error
        return _envelope(True, "File deleted")

    @api.get("/v2/projects/{project_id}/files/{file_id}/download")
    def download_project_file(project_id: str, file_id: str, user=Depends(current_user)):
        core = build_core(cloud.service_client, user.user_id)
        project = _project(core, project_id)
        service = _drive(core, user)
        drive_id, _, _ = _file_reference(core, project_id, project, file_id, service)
        from planner_integrations.google_drive import download_drive_file
        content = download_drive_file(service, drive_id)
        if content is None:
            raise HTTPException(status_code=502, detail="Project file could not be downloaded")
        from fastapi.responses import Response
        return Response(content=content, media_type="application/octet-stream")


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
        except PlannerCoreError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as e:
            logger.error(f"Failed to create project task: {e}")
            raise HTTPException(status_code=500, detail={"code": "CREATE_FAILED", "message": "Operation could not be completed"})

    @api.get("/v2/projects/{project_id}/tasks")
    def get_project_tasks(
        project_id: str,
        fields: str | None = Query(default=None),
        milestone_id: str | None = Query(default=None),
        user=Depends(current_user),
    ):
        core = build_core(cloud.service_client, user.user_id)
        # Tasks only. Slots are how a task gets onto the timeline and the
        # calendar; the dashboard lists the work itself, so a task split into
        # three sittings appears once rather than four times.
        #
        # fields lets a caller that only needs a column or two say so. A task
        # row carries notes and a metadata blob, so a screen wanting nothing
        # but tick state was pulling hundreds of times what it read.
        allowed_fields = {
            "id", "title", "project_id", "milestone_id", "status", "priority", "due_date",
            "scheduled_date", "start_time", "estimated_minutes", "recurrence_key", "depends_on",
            "notes", "completed_at", "parent_task_id", "metadata", "starred", "created_at", "updated_at",
        }
        requested_fields = [part.strip() for part in fields.split(",") if part.strip()] if fields else []
        if fields and (not requested_fields or not set(requested_fields).issubset(allowed_fields)):
            raise HTTPException(status_code=400, detail="Invalid task fields")
        columns = ",".join(requested_fields) if fields else "*"
        # milestone_id narrows it to one group, so a screen showing collapsed
        # milestones can fetch the rows for the one you opened instead of every
        # task in the project.
        filters = {"project_id": project_id}
        if milestone_id:
            filters["milestone_id"] = milestone_id
        tasks = core.repository.list_rows(
            "planner_tasks",
            filters,
            columns=columns,
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
                start_date=body.get("start_date"),
                notes=body.get("notes"),
            )
            return _envelope(True, "Milestone created", result["data"])
        except Exception as e:
            logger.error(f"Failed to create milestone: {e}")
            raise HTTPException(status_code=500, detail={"code": "CREATE_FAILED", "message": "Operation could not be completed"})

    @api.patch("/v2/milestones/{milestone_id}")
    def update_milestone(milestone_id: str, body: dict, user=Depends(current_user)):
        """Change a milestone's dates, name, status or notes.

        Milestones had no update route at all, so start_date could be stored
        but never set from anywhere — the dashboard's health panel was left
        deriving every start from the earliest task.
        """
        core = build_core(cloud.service_client, user.user_id)
        allowed = {"name", "status", "target_date", "start_date", "sort_order", "notes"}
        updates = {key: value for key, value in body.items() if key in allowed}
        if not updates:
            raise HTTPException(
                status_code=400,
                detail={"code": "PATCH_EMPTY", "message": f"Nothing to change; allowed: {sorted(allowed)}"},
            )
        try:
            result = core.projects.update_milestone(milestone_id, updates)
        except (PlannerCoreError, ValueError) as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "MILESTONE_UPDATE_INVALID", "message": str(error)},
            ) from error
        return _envelope(True, result["message"], result["data"])

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
        limit: int = Query(default=200, ge=1, le=1000),
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
    def retired_drive_cleanup(user=Depends(current_user)):
        # This old global service-account endpoint deleted same-name folders
        # without checking tenant ownership or whether they contained files.
        raise HTTPException(status_code=410, detail="Legacy global Drive cleanup has been retired")
