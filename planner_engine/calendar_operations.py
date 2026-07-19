"""Ownership-safe Google Calendar CRUD, previews, and reconciliation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from planner_engine.execution_targets.google_calendar import GoogleCalendarExecutionTarget
from planner_engine.external_links import ExternalLinkStore
from planner_engine.models import ScheduledBlock
from planner_integrations.google_calendar import GoogleCalendarClient, GoogleCalendarError


@dataclass(frozen=True)
class CalendarMutationPreview:
    operation: str
    events: list[dict[str, Any]]
    start_date: str
    end_date: str
    preview_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = field(default_factory=lambda: (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
    requires_confirmation: bool = True

    def to_dict(self):
        return asdict(self)


class GoogleCalendarOperations:
    def __init__(self, client: GoogleCalendarClient, links: ExternalLinkStore, preview_dir: str | Path) -> None:
        self.client, self.links, self.preview_dir = client, links, Path(preview_dir)
        self.target = GoogleCalendarExecutionTarget(client)

    def list_range(self, start: date, end: date):
        return [asdict(item) for item in self.target.list_items(start, end)]

    def list_external_events(self, start: date, end: date) -> list[dict[str, Any]]:
        """Return non-Planner-OS events in a range (events not created by us)."""
        zone = ZoneInfo(self.client.timezone)
        all_events = self.client.list_events(
            datetime.combine(start, time.min, zone),
            datetime.combine(end + timedelta(days=1), time.min, zone),
        )
        # One batched read instead of one link lookup per event. Rows whose
        # planner_block_id equals the external_id are legacy import markers
        # that never got a workbook task persisted; ignore them so those
        # events can be imported again.
        imported_external_ids = {
            str(link["external_id"])
            for link in self.links.list(target_name="google_calendar", status="active")
            if str(link.get("planner_block_id", "")) != str(link.get("external_id", ""))
        }
        external = []
        for event in all_events:
            if self.client._is_planner_event(event):
                continue
            event_id = str(event.get("id", ""))
            if event_id in imported_external_ids:
                continue
            start_raw = event.get("start", {})
            end_raw = event.get("end", {})
            external.append({
                "external_id": event_id,
                "title": str(event.get("summary", "(no title)")),
                "start": start_raw.get("dateTime") or start_raw.get("date", ""),
                "end": end_raw.get("dateTime") or end_raw.get("date", ""),
                "all_day": "date" in start_raw and "dateTime" not in start_raw,
                "description": str(event.get("description", "")),
            })
        return external

    def lookup_event(self, planner_block_id: str, start: date, end: date):
        return [item for item in self.list_range(start, end) if item["planner_block_id"] == planner_block_id]

    def update_event(self, external_id: str, block: ScheduledBlock):
        event = self.client.get_event(external_id)
        if not self.client._is_planner_event(event):
            raise GoogleCalendarError("Refusing to update an event not owned by Planner OS")
        result = self.target.update_block(block, external_id)
        if result.success:
            mapping = result.mappings[0] if result.mappings else {"planner_block_id": self.client.stable_block_id(block), "external_id": external_id, "checksum": "updated"}
            self.links.upsert(mapping["planner_block_id"], "google_calendar", external_id, mapping["checksum"])
        return result.to_dict()

    def delete_event(self, external_id: str, scope: str = "single"):
        event = self.client.get_event(external_id)
        block_id = self.client._planner_block_id_from_event(event)
        result = self.target.delete_item(external_id, delete_scope=scope)
        if result.success and block_id:
            self.links.deactivate(block_id, "google_calendar")
        return result.to_dict()

    def preview_delete_range(self, start: date, end: date, operation: str = "calendar_delete_range"):
        preview = CalendarMutationPreview(operation, self.list_range(start, end), start.isoformat(), end.isoformat())
        self._save(preview)
        return preview

    def apply_delete_range(self, preview_id: str, operation: str = "calendar_delete_range"):
        preview = self._load(preview_id, operation)
        current = {item["external_id"] for item in self.list_range(date.fromisoformat(preview.start_date), date.fromisoformat(preview.end_date))}
        expected = {item["external_id"] for item in preview.events}
        if current != expected:
            raise ValueError("Calendar changed since preview; create a new preview")
        deleted, errors = 0, []
        for item in preview.events:
            result = self.delete_event(item["external_id"])
            if result["success"]:
                deleted += 1
            else:
                errors.extend(result["errors"])
        self._mark_applied(preview_id)
        return {"success": not errors, "deleted": deleted, "errors": errors}

    def reconcile_range(self, blocks: list[ScheduledBlock], start: date, end: date):
        return self.target.reconcile(blocks, start, end).to_dict()

    def preview_cleanup_orphans(self, blocks: list[ScheduledBlock], start: date, end: date):
        report = self.target.reconcile(blocks, start, end)
        orphan_ids = set(report.orphan_external)
        events = [item for item in self.list_range(start, end) if item["planner_block_id"] in orphan_ids]
        preview = CalendarMutationPreview("calendar_cleanup_orphans", events, start.isoformat(), end.isoformat())
        self._save(preview)
        return preview

    def repair_mapping(self, external_id: str):
        event = self.client.get_event(external_id)
        if not self.client._is_planner_event(event):
            raise GoogleCalendarError("Event is not owned by Planner OS")
        block_id = self.client._planner_block_id_from_event(event)
        if not block_id:
            raise GoogleCalendarError("Planner event has no planner_block_id")
        record = self.links.upsert(block_id, "google_calendar", external_id, "repaired-from-calendar")
        return {"success": True, "mapping": record}

    def _save(self, preview):
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        (self.preview_dir / f"{preview.preview_id}.json").write_text(json.dumps(preview.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _load(self, preview_id, operation):
        path = self.preview_dir / f"{preview_id}.json"
        if not path.exists():
            raise ValueError("Unknown calendar preview")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("applied_at"):
            raise ValueError("Calendar preview was already applied")
        if data["operation"] != operation:
            raise ValueError("Calendar preview operation does not match")
        if datetime.fromisoformat(data["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("Calendar preview expired")
        return CalendarMutationPreview(**{key: data[key] for key in CalendarMutationPreview.__dataclass_fields__})

    def _mark_applied(self, preview_id):
        path = self.preview_dir / f"{preview_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["applied_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
