"""Dashboard read surface: computed planner metrics behind a simple app key.

Same single-user trust model as the PWA (planner_api/day.py): requests carry
X-App-Key matching DASHBOARD_ACCESS_KEY (falling back to PWA_ACCESS_KEY) and
read the workspace of MCP_USER_ID. This surface is read-only — the dashboard
never writes. It exists because /v2/metrics is OAuth-gated, which a headless
Streamlit app cannot satisfy with a shared key.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from planner_api.v2 import build_core, _configured_user_id


def register_dashboard_routes(api: FastAPI, cloud: Any) -> None:
    def _envelope(success: bool, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"success": success, "message": message, "data": data or {}, "errors": []}

    def _authorize(key: str | None) -> None:
        expected = os.environ.get("DASHBOARD_ACCESS_KEY") or os.environ.get("PWA_ACCESS_KEY", "")
        if not expected or not key or not secrets.compare_digest(key, expected):
            raise HTTPException(
                status_code=401,
                detail={"code": "APP_KEY_INVALID", "message": "X-App-Key header is missing or wrong"},
            )

    @api.get("/v2/dashboard/metrics")
    def dashboard_metrics(x_app_key: str | None = Header(default=None)):
        _authorize(x_app_key)
        core = build_core(cloud.service_client, _configured_user_id())
        return _envelope(
            True,
            "Planner metrics",
            {"snapshot": core.metrics.snapshot(), "flat": core.metrics.flat_snapshot()},
        )
