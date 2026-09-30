"""Read-only native reminder feed using the same rules as web push.

Each Android installation remembers its own delivered reminder kinds. Web
push delivery to a different device must not suppress this device's alerts.
No credential, arbitrary tenant id, or database write is accepted here.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from planner_api.v2 import _configured_user_id, build_core


class NativeReminderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sent_kinds: list[str] = Field(default_factory=list, max_length=2000)


def register_native_routes(api: FastAPI, cloud: Any) -> None:
    @api.post("/v2/native/reminders")
    def native_reminders(body: NativeReminderRequest, x_app_key: str | None = Header(default=None)):
        expected = os.environ.get("PWA_ACCESS_KEY", "")
        if not expected or not x_app_key or not secrets.compare_digest(expected.encode("utf-8"), x_app_key.encode("utf-8")):
            raise HTTPException(
                status_code=401,
                detail={"code": "APP_KEY_INVALID", "message": "X-App-Key header is missing or wrong"},
            )
        if any(len(kind) > 300 for kind in body.sent_kinds):
            raise HTTPException(status_code=422, detail="Invalid reminder identifier")
        core = build_core(cloud.service_client, _configured_user_id())
        now = datetime.now(ZoneInfo(core.timezone))
        return {
            "success": True,
            "message": "Native reminders",
            "errors": [],
            "data": {
                "date": now.date().isoformat(),
                "timezone": core.timezone,
                "reminders": core.reminders.due_reminders(now, sent_kinds=set(body.sent_kinds)),
            },
        }
