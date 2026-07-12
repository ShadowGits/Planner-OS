"""Native Apple Calendar execution-target adapter."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from planner_engine.execution_targets.base import ExecutionTargetCapabilities, ExternalExecutionItem, PublishResult, ReconciliationReport
from planner_engine.models import ScheduledBlock
from planner_integrations.apple_calendar import AppleCalendarClient
from planner_integrations.apple_calendar.permissions import PERMISSION_INSTRUCTIONS


BLOCK_MARKER = re.compile(r"Planner OS block: ([A-Za-z0-9_-]+)")


class AppleCalendarExecutionTarget:
    name = "apple_calendar"
    capabilities = ExecutionTargetCapabilities(supports_range_delete=True, supports_recurrence=True, supports_series_update=True, supports_series_delete=True, supports_reminders=True)

    def __init__(self, client: AppleCalendarClient, timezone: str = "Asia/Kolkata") -> None:
        self.client = client
        self.timezone = timezone

    def health(self):
        try:
            status = self.client.permission_status()
            permission = status.get("data", {}).get("permission", "unknown")
            ready = permission in {"authorized", "full_access", "write_only"}
            return {"success": ready, "target": self.name, "status": "ready" if ready else "permission_required", "permission": permission, "instructions": None if ready else PERMISSION_INSTRUCTIONS, "calendar_id": self.client.calendar_id, "capabilities": self.capabilities.__dict__}
        except Exception as error:
            return {"success": False, "target": self.name, "status": "unavailable", "errors": [str(error)], "capabilities": self.capabilities.__dict__}

    def publish_blocks(self, blocks: list[ScheduledBlock], *, replace_existing: bool = False) -> PublishResult:
        del replace_existing
        if not self.client.calendar_id:
            return PublishResult(False, self.name, errors=["No Apple Calendar target calendar selected"])
        existing = {}
        if blocks:
            for item in self.list_items(min(block.start.date() for block in blocks), max(block.end.date() for block in blocks)):
                existing.setdefault(item.planner_block_id, []).append(item)
        created = updated = unchanged = 0
        mappings, errors, warnings = [], [], []
        for block in blocks:
            block_id = self._block_id(block)
            matches = existing.get(block_id, [])
            if len(matches) > 1:
                errors.append(f"Duplicate Apple Calendar events for block {block_id}")
                continue
            payload = self._event(block)
            try:
                if matches:
                    found = matches[0]
                    if self._matches(found.raw, payload):
                        unchanged += 1
                    else:
                        self.client.update_event(found.external_id, payload)
                        updated += 1
                    external_id = found.external_id
                else:
                    external_id = str(self.client.create_event(payload)["external_id"])
                    created += 1
                mappings.append({"planner_block_id": block_id, "external_id": external_id, "checksum": self._checksum(block)})
            except Exception as error:
                errors.append(f"{block.title}: {error}")
        return PublishResult(not errors, self.name, created, updated, unchanged=unchanged, mappings=mappings, warnings=warnings, errors=errors)

    def update_block(self, block: ScheduledBlock, external_id: str) -> PublishResult:
        try:
            self.client.update_event(external_id, self._event(block))
            return PublishResult(True, self.name, updated=1, mappings=[{"planner_block_id": self._block_id(block), "external_id": external_id, "checksum": self._checksum(block)}])
        except Exception as error:
            return PublishResult(False, self.name, errors=[str(error)])

    def delete_item(self, external_id: str, *, delete_scope: str = "single") -> PublishResult:
        try:
            event = self.client.read_event(external_id)
            if not self._marker(event):
                return PublishResult(False, self.name, errors=["Refusing to delete an Apple Calendar event not owned by Planner OS"])
            self.client.delete_event(external_id, delete_scope)
            return PublishResult(True, self.name, deleted=1)
        except Exception as error:
            return PublishResult(False, self.name, errors=[str(error)])

    def list_items(self, start_date: date, end_date: date) -> list[ExternalExecutionItem]:
        zone = ZoneInfo(self.timezone)
        start = datetime.combine(start_date, time.min, zone).isoformat()
        end = datetime.combine(end_date + timedelta(days=1), time.min, zone).isoformat()
        items = []
        for event in self.client.list_events(start, end):
            block_id = self._marker(event)
            if block_id:
                items.append(ExternalExecutionItem(str(event["external_id"]), block_id, str(event.get("title", "")), str(event.get("start", "")), str(event.get("end", "")), self.name, event))
        return items

    def reconcile(self, planned_blocks: list[ScheduledBlock], start_date: date, end_date: date) -> ReconciliationReport:
        desired = {self._block_id(block): block for block in planned_blocks}
        by_id = {}
        for item in self.list_items(start_date, end_date):
            by_id.setdefault(item.planner_block_id, []).append(item)
        return ReconciliationReport(self.name, start_date.isoformat(), end_date.isoformat(), missing_external=sorted(set(desired) - set(by_id)), orphan_external=sorted(set(by_id) - set(desired)), duplicates=sorted(key for key, values in by_id.items() if len(values) > 1), stale=sorted(key for key, block in desired.items() if key in by_id and not self._matches(by_id[key][0].raw, self._event(block))))

    def _block_id(self, block: ScheduledBlock) -> str:
        value = (block.metadata or {}).get("planner_block_id")
        if value:
            return str(value)
        identity = "|".join((block.title, block.start.isoformat(), block.end.isoformat(), block.category, block.source))
        return hashlib.sha256(identity.encode()).hexdigest()[:32]

    def _event(self, block: ScheduledBlock):
        marker = f"Planner OS block: {self._block_id(block)}"
        notes = str((block.metadata or {}).get("notes") or "")
        return {"title": block.title, "start": block.start.isoformat(), "end": block.end.isoformat(), "notes": f"{marker}\nPlanner source: {block.source}\n{notes}".strip(), "location": (block.metadata or {}).get("location"), "all_day": False}

    def _marker(self, event):
        match = BLOCK_MARKER.search(str(event.get("notes", "")))
        return match.group(1) if match else None

    def _matches(self, event, payload):
        return all(event.get(key) == payload.get(key) for key in ("title", "start", "end", "notes"))

    def _checksum(self, block):
        return hashlib.sha256(repr((block.title, block.start.isoformat(), block.end.isoformat(), block.category, block.source)).encode()).hexdigest()
