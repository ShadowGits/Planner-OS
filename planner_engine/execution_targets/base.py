"""Execution-target contracts and shared result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Protocol

from planner_engine.models import ScheduledBlock


@dataclass(frozen=True)
class ExecutionTargetCapabilities:
    supports_create: bool = True
    supports_update: bool = True
    supports_delete: bool = True
    supports_range_delete: bool = False
    supports_recurrence: bool = False
    supports_series_update: bool = False
    supports_series_delete: bool = False
    supports_live_reconciliation: bool = True
    supports_reminders: bool = False


@dataclass(frozen=True)
class ExternalExecutionItem:
    external_id: str
    planner_block_id: str
    title: str
    start: str
    end: str
    target_name: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishResult:
    success: bool
    target_name: str
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    mappings: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReconciliationReport:
    target_name: str
    start_date: str
    end_date: str
    missing_external: list[str] = field(default_factory=list)
    orphan_external: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionTarget(Protocol):
    name: str
    capabilities: ExecutionTargetCapabilities

    def publish_blocks(self, blocks: list[ScheduledBlock], *, replace_existing: bool = False) -> PublishResult: ...
    def update_block(self, block: ScheduledBlock, external_id: str) -> PublishResult: ...
    def delete_item(self, external_id: str, *, delete_scope: str = "single") -> PublishResult: ...
    def list_items(self, start_date: date, end_date: date) -> list[ExternalExecutionItem]: ...
    def reconcile(self, planned_blocks: list[ScheduledBlock], start_date: date, end_date: date) -> ReconciliationReport: ...
    def health(self) -> dict[str, Any]: ...
