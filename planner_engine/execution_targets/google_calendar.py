"""Google Calendar execution-target adapter."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from planner_engine.execution_targets.base import ExecutionTargetCapabilities, ExternalExecutionItem, PublishResult, ReconciliationReport
from planner_engine.models import ScheduledBlock
from planner_integrations.google_calendar import GoogleCalendarClient


class GoogleCalendarExecutionTarget:
    name = "google_calendar"
    capabilities = ExecutionTargetCapabilities(supports_range_delete=True, supports_recurrence=True, supports_series_update=True, supports_series_delete=True, supports_reminders=True)

    def __init__(self, client: GoogleCalendarClient) -> None:
        self.client = client

    def health(self):
        try:
            self.client.authenticate()
            return {"success": True, "target": self.name, "status": "ready", "capabilities": self.capabilities.__dict__}
        except Exception as error:
            return {"success": False, "target": self.name, "status": "unavailable", "errors": [str(error)], "capabilities": self.capabilities.__dict__}

    def publish_blocks(self, blocks: list[ScheduledBlock], *, replace_existing: bool = False) -> PublishResult:
        del replace_existing
        created = updated = unchanged = 0
        mappings = []
        errors = []
        if not blocks:
            return PublishResult(True, self.name)
        start, end = min(item.start for item in blocks), max(item.end for item in blocks)
        existing = {item.planner_block_id: item for item in self.list_items(start.date(), end.date())}
        for block in blocks:
            block_id = self.client.stable_block_id(block)
            try:
                found = existing.get(block_id)
                if found is None:
                    event = self.client.create_event(block)
                    external_id = str(event["id"])
                    created += 1
                else:
                    external_id = found.external_id
                    raw = found.raw
                    if self.client._event_matches_block(raw, block):
                        unchanged += 1
                    else:
                        self.client.update_event(external_id, block)
                        updated += 1
                mappings.append({"planner_block_id": block_id, "external_id": external_id, "checksum": self._checksum(block)})
            except Exception as error:
                errors.append(f"{block.title}: {error}")
        return PublishResult(not errors, self.name, created, updated, unchanged=unchanged, mappings=mappings, errors=errors)

    def update_block(self, block: ScheduledBlock, external_id: str) -> PublishResult:
        try:
            self.client.update_event(external_id, block)
            return PublishResult(True, self.name, updated=1)
        except Exception as error:
            return PublishResult(False, self.name, errors=[str(error)])

    def delete_item(self, external_id: str, *, delete_scope: str = "single") -> PublishResult:
        try:
            if delete_scope == "single":
                self.client.delete_planner_event(external_id)
            else:
                self.client.delete_event_scope(external_id, delete_scope)
            return PublishResult(True, self.name, deleted=1)
        except Exception as error:
            return PublishResult(False, self.name, errors=[str(error)])

    def list_items(self, start_date: date, end_date: date) -> list[ExternalExecutionItem]:
        zone = ZoneInfo(self.client.timezone)
        events = self.client.list_events(datetime.combine(start_date, time.min, zone), datetime.combine(end_date + timedelta(days=1), time.min, zone))
        items = []
        for event in events:
            if not self.client._is_planner_event(event):
                continue
            block_id = self.client._planner_block_id_from_event(event)
            if not block_id:
                continue
            items.append(ExternalExecutionItem(str(event["id"]), block_id, str(event.get("summary", "")), str(event.get("start", {}).get("dateTime", "")), str(event.get("end", {}).get("dateTime", "")), self.name, event))
        return items

    def reconcile(self, planned_blocks: list[ScheduledBlock], start_date: date, end_date: date) -> ReconciliationReport:
        desired = {self.client.stable_block_id(item): item for item in planned_blocks}
        external = self.list_items(start_date, end_date)
        by_id = {}
        for item in external:
            by_id.setdefault(item.planner_block_id, []).append(item)
        return ReconciliationReport(
            self.name, start_date.isoformat(), end_date.isoformat(),
            missing_external=sorted(set(desired) - set(by_id)),
            orphan_external=sorted(set(by_id) - set(desired)),
            duplicates=sorted(key for key, values in by_id.items() if len(values) > 1),
            stale=sorted(key for key, block in desired.items() if key in by_id and not self.client._event_matches_block(by_id[key][0].raw, block)),
        )

    def _checksum(self, block: ScheduledBlock) -> str:
        return hashlib.sha256(repr((block.title, block.start.isoformat(), block.end.isoformat(), block.category, block.source)).encode()).hexdigest()
