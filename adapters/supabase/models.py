"""Conversions between Supabase rows and platform models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from planner_platform.ports.workspaces import WorkspaceRecord


def workspace_from_row(row: dict[str, Any]) -> WorkspaceRecord:
    return WorkspaceRecord(
        id=UUID(str(row["id"])),
        user_id=UUID(str(row["user_id"])),
        name=str(row["name"]),
        timezone=str(row["timezone"]),
        active_execution_target=str(row["active_execution_target"]),
        workbook_bucket=str(row["workbook_bucket"]),
        workbook_key=str(row["workbook_key"]),
        revision=int(row["revision"]),
        settings_revision=int(row.get("settings_revision", 0)),
        is_active=bool(row.get("is_active", False)),
        workbook_sha256=(str(row["workbook_sha256"]) if row.get("workbook_sha256") else None),
        lock_owner=(UUID(str(row["lock_owner"])) if row.get("lock_owner") else None),
        locked_until=(datetime.fromisoformat(str(row["locked_until"])) if row.get("locked_until") else None),
    )
