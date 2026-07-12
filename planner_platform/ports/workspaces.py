"""Owned workspace metadata and lock port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from planner_platform.context import PlannerContext


@dataclass(frozen=True)
class WorkspaceRecord:
    id: UUID
    user_id: UUID
    name: str
    timezone: str
    active_execution_target: str
    workbook_bucket: str
    workbook_key: str
    revision: int
    settings_revision: int
    is_active: bool = False
    workbook_sha256: str | None = None
    lock_owner: UUID | None = None
    locked_until: datetime | None = None


class WorkspaceRepository(Protocol):
    def list_owned(self, user_id: UUID) -> list[WorkspaceRecord]: ...

    def get_owned(self, user_id: UUID, workspace_id: UUID) -> WorkspaceRecord | None: ...

    def get_active(self, user_id: UUID) -> WorkspaceRecord | None: ...

    def activate(self, user_id: UUID, workspace_id: UUID) -> WorkspaceRecord: ...

    def acquire_lock(self, context: PlannerContext, ttl_seconds: int = 60) -> WorkspaceRecord: ...

    def release_lock(self, context: PlannerContext) -> bool: ...

    def advance_revision(self, context: PlannerContext, checksum: str) -> WorkspaceRecord: ...
