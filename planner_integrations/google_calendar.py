"""Google Calendar integration for Planner OS scheduled blocks."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from planner_engine.config import (
    DEFAULT_EXTERNAL_LINKS_PATH,
    DEFAULT_GOOGLE_CALENDAR_ID,
    DEFAULT_GOOGLE_CREDENTIALS_PATH,
    DEFAULT_GOOGLE_TIMEZONE,
    DEFAULT_GOOGLE_TOKEN_PATH,
)
from planner_engine.decision_log import DecisionLog, DecisionOutcome
from planner_engine.external_links import ExternalLinkStore
from planner_engine.models import DailyPlan, ScheduledBlock, WeeklyPlan


SCOPES = ("https://www.googleapis.com/auth/calendar.events",)


class GoogleCalendarError(RuntimeError):
    """Raised for Google Calendar integration configuration errors."""


@dataclass(frozen=True)
class CalendarSyncResult:
    """Structured result from synchronizing a plan to Google Calendar."""

    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    sync_scope: str | None = None

    @property
    def success(self) -> bool:
        """Return whether sync completed without API errors."""

        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        data = asdict(self)
        data["success"] = self.success
        return data


class GoogleCalendarClient:
    """Synchronize Planner OS scheduled blocks to Google Calendar."""

    def __init__(
        self,
        credentials_path: str | Path = DEFAULT_GOOGLE_CREDENTIALS_PATH,
        token_path: str | Path = DEFAULT_GOOGLE_TOKEN_PATH,
        calendar_id: str = DEFAULT_GOOGLE_CALENDAR_ID,
        timezone: str = DEFAULT_GOOGLE_TIMEZONE,
        service: Any | None = None,
        decision_log: DecisionLog | None = None,
        external_links_path: str | Path | None = None,
    ) -> None:
        self.credentials_path = Path(credentials_path).expanduser()
        self.token_path = Path(token_path).expanduser()
        self.calendar_id = calendar_id
        self.timezone = timezone
        self.service = service
        self.decision_log = decision_log or DecisionLog()
        self.external_links = (
            ExternalLinkStore(external_links_path)
            if external_links_path is not None
            else (ExternalLinkStore(DEFAULT_EXTERNAL_LINKS_PATH) if service is None else None)
        )

    def authenticate(self) -> Any:
        """Authenticate with Desktop OAuth and return a Calendar service."""

        if self.service is not None:
            return self.service
        if not self.credentials_path.exists():
            raise GoogleCalendarError(
                "Google Calendar credentials.json not found. Place it at "
                f"{self.credentials_path} or override the configured credentials path."
            )

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as error:
            raise GoogleCalendarError(
                "Google Calendar dependencies are missing. Install requirements.txt."
            ) from error

        credentials = None
        if self.token_path.exists():
            credentials = Credentials.from_authorized_user_file(
                str(self.token_path),
                SCOPES,
            )

        if credentials and credentials.expired and credentials.refresh_token:
            try:
                from google.auth.transport.requests import Request
            except ImportError as error:
                raise GoogleCalendarError(
                    "Google Calendar dependencies are missing. Install requirements.txt."
                ) from error
            credentials.refresh(Request())

        if not credentials or not credentials.valid:
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
            except ImportError as error:
                raise GoogleCalendarError(
                    "Google Calendar dependencies are missing. Install requirements.txt."
                ) from error
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.credentials_path),
                SCOPES,
            )
            credentials = flow.run_local_server(port=0)

        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        self.service = build(
            "calendar",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )
        return self.service

    def list_events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """List calendar events in a date-time range."""

        service = self.authenticate()
        response = (
            service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=self._api_datetime(start),
                timeMax=self._api_datetime(end),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return list(response.get("items", []))

    def create_event(self, block: ScheduledBlock) -> dict[str, Any]:
        """Create a Google Calendar event for a scheduled block."""

        return (
            self.authenticate()
            .events()
            .insert(calendarId=self.calendar_id, body=self.event_from_block(block))
            .execute()
        )

    def update_event(self, event_id: str, block: ScheduledBlock) -> dict[str, Any]:
        """Update a Planner OS-owned calendar event."""

        return (
            self.authenticate()
            .events()
            .update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=self.event_from_block(block),
            )
            .execute()
        )

    def delete_event(self, event_id: str) -> None:
        """Delete a Planner OS-owned calendar event."""

        (
            self.authenticate()
            .events()
            .delete(calendarId=self.calendar_id, eventId=event_id)
            .execute()
        )

    def get_event(self, event_id: str) -> dict[str, Any]:
        """Read one event before an ownership-sensitive mutation."""

        return (
            self.authenticate()
            .events()
            .get(calendarId=self.calendar_id, eventId=event_id)
            .execute()
        )

    def delete_planner_event(self, event_id: str) -> None:
        """Delete one event only when Planner OS private metadata owns it."""

        event = self.get_event(event_id)
        if not self._is_planner_event(event):
            raise GoogleCalendarError("Refusing to delete an event not owned by Planner OS")
        self.delete_event(event_id)

    def delete_event_scope(self, event_id: str, delete_scope: str) -> None:
        """Delete a Planner OS event, recurring series, or this-and-future instances."""

        event = self.get_event(event_id)
        if not self._is_planner_event(event):
            raise GoogleCalendarError("Refusing to delete an event not owned by Planner OS")
        if delete_scope == "single":
            self.delete_event(event_id)
            return
        recurring_id = event.get("recurringEventId") or event.get("id")
        if delete_scope == "series":
            self.delete_planner_event(str(recurring_id))
            return
        if delete_scope != "future":
            raise ValueError("delete_scope must be single, series, or future")
        original = event.get("originalStartTime", {}).get("dateTime") or event.get("start", {}).get("dateTime")
        if not original:
            raise GoogleCalendarError("Recurring instance has no start time")
        master = self.get_event(str(recurring_id))
        if not self._is_planner_event(master):
            raise GoogleCalendarError("Refusing to update a series not owned by Planner OS")
        start = datetime.fromisoformat(str(original).replace("Z", "+00:00"))
        until = (start - timedelta(seconds=1)).astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
        recurrence = list(master.get("recurrence", []))
        if not recurrence:
            raise GoogleCalendarError("Event is not a recurring series")
        recurrence[0] = self._rrule_with_until(recurrence[0], until)
        body = dict(master)
        body["recurrence"] = recurrence
        self.authenticate().events().update(calendarId=self.calendar_id, eventId=str(recurring_id), body=body).execute()

    def list_planner_events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """List only Planner OS-owned events in a range."""

        return [event for event in self.list_events(start, end) if self._is_planner_event(event)]

    def lookup_by_planner_block_id(self, planner_block_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return [event for event in self.list_planner_events(start, end) if self._planner_block_id_from_event(event) == planner_block_id]

    def sync_plan(
        self,
        plan: DailyPlan | WeeklyPlan,
        *,
        start: datetime | date | None = None,
        end: datetime | date | None = None,
        scope: str | None = None,
    ) -> CalendarSyncResult:
        """Idempotently synchronize a daily or weekly plan."""

        blocks = self._blocks_for_plan(plan)
        sync_start = self._range_datetime(start, beginning=True)
        sync_end = self._range_datetime(end, beginning=False)
        if sync_start is None and blocks:
            sync_start = min(block.start for block in blocks)
        if sync_end is None and blocks:
            sync_end = max(block.end for block in blocks)
        if sync_start is None or sync_end is None:
            result = CalendarSyncResult(sync_scope=scope)
            self._record_sync(plan, result)
            return result
        start_date = sync_start.date().isoformat()
        end_date = (sync_end - timedelta(microseconds=1)).date().isoformat()
        try:
            existing_events = self.list_events(
                sync_start,
                sync_end,
            )
        except Exception as error:
            result = CalendarSyncResult(
                errors=[f"list_events: {error}"],
                start_date=start_date,
                end_date=end_date,
                sync_scope=scope,
            )
            warnings = self._record_sync(plan, result)
            return CalendarSyncResult(
                errors=result.errors,
                warnings=warnings,
                start_date=start_date,
                end_date=end_date,
                sync_scope=scope,
            )

        planner_events = {
            self._planner_block_id_from_event(event): event
            for event in existing_events
            if self._is_planner_event(event)
            and self._planner_block_id_from_event(event) is not None
        }
        desired_blocks = {self.stable_block_id(block): block for block in blocks}

        created = updated = deleted = unchanged = 0
        errors: list[str] = []

        for block_id, block in desired_blocks.items():
            existing = planner_events.get(block_id)
            if existing is None:
                existing = self._linked_event(block_id)
            try:
                if existing is None:
                    created_event = self.create_event(block)
                    self._record_external_link(block_id, str(created_event["id"]), block)
                    created += 1
                elif self._event_matches_block(existing, block):
                    self._record_external_link(block_id, str(existing["id"]), block)
                    unchanged += 1
                else:
                    self.update_event(str(existing["id"]), block)
                    self._record_external_link(block_id, str(existing["id"]), block)
                    updated += 1
            except Exception as error:
                errors.append(f"{block.title}: {error}")

        for block_id, event in planner_events.items():
            if block_id in desired_blocks:
                continue
            try:
                self.delete_event(str(event["id"]))
                deleted += 1
            except Exception as error:
                errors.append(f"{event.get('summary', event.get('id'))}: {error}")

        result = CalendarSyncResult(
            created=created,
            updated=updated,
            deleted=deleted,
            unchanged=unchanged,
            errors=errors,
            start_date=start_date,
            end_date=end_date,
            sync_scope=scope,
        )
        warnings = self._record_sync(plan, result)
        return CalendarSyncResult(
            created=result.created,
            updated=result.updated,
            deleted=result.deleted,
            unchanged=result.unchanged,
            errors=result.errors,
            warnings=warnings,
            start_date=start_date,
            end_date=end_date,
            sync_scope=scope,
        )

    def _linked_event(self, block_id: str) -> dict[str, Any] | None:
        """Load an already-linked event even when it is outside this sync range."""

        if self.external_links is None:
            return None
        link = self.external_links.active_for(block_id)
        if not link or link.get("target_name") != "google_calendar":
            return None
        try:
            event = self.get_event(str(link["external_id"]))
        except Exception:
            return None
        if self._is_planner_event(event) and self._planner_block_id_from_event(event) == block_id:
            return event
        return None

    def _record_external_link(self, block_id: str, external_id: str, block: ScheduledBlock) -> None:
        """Persist the Planner OS block to Google event mapping when configured."""

        if self.external_links is None:
            return
        try:
            self.external_links.upsert(block_id, "google_calendar", external_id, self._checksum(block))
        except Exception:
            return

    def _checksum(self, block: ScheduledBlock) -> str:
        event = self.event_from_block(block)
        identity = "|".join(
            [
                event["summary"],
                event["start"]["dateTime"],
                event["end"]["dateTime"],
                event["extendedProperties"]["private"]["planner_block_id"],
            ]
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def event_from_block(self, block: ScheduledBlock) -> dict[str, Any]:
        """Map a ScheduledBlock to a Google Calendar event resource."""

        block_id = self.stable_block_id(block)
        return {
            "summary": block.title,
            "description": (
                f"Planner OS block\n"
                f"Category: {block.category}\n"
                f"Source: {block.source}"
            ),
            "start": {
                "dateTime": self._api_datetime(block.start),
                "timeZone": self.timezone,
            },
            "end": {
                "dateTime": self._api_datetime(block.end),
                "timeZone": self.timezone,
            },
            "extendedProperties": {
                "private": {
                    "planner_os": "true",
                    "planner_block_id": block_id,
                    "planner_task_id": str((block.metadata or {}).get("source_task_id", "")),
                    "planner_source": block.source,
                    "planner_version": "mvp2",
                    "category": block.category,
                }
            },
        }

    def stable_block_id(self, block: ScheduledBlock) -> str:
        """Return a stable Planner OS identifier for a block."""

        metadata = block.metadata or {}
        if metadata.get("planner_block_id"):
            return str(metadata["planner_block_id"])
        identity = "|".join(
            [
                block.title,
                block.start.isoformat(),
                block.end.isoformat(),
                block.category,
                block.source,
            ]
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]

    def _blocks_for_plan(self, plan: DailyPlan | WeeklyPlan) -> list[ScheduledBlock]:
        """Return all scheduled blocks from a daily or weekly plan."""

        if isinstance(plan, DailyPlan):
            return plan.blocks
        return [block for day in plan.days for block in day.blocks]

    def _is_planner_event(self, event: dict[str, Any]) -> bool:
        """Return whether an event was created by Planner OS."""

        private = event.get("extendedProperties", {}).get("private", {})
        return private.get("planner_os") == "true"

    def _planner_block_id_from_event(self, event: dict[str, Any]) -> str | None:
        """Read Planner OS block id from a Google event."""

        private = event.get("extendedProperties", {}).get("private", {})
        block_id = private.get("planner_block_id")
        return str(block_id) if block_id else None

    def _event_matches_block(
        self,
        event: dict[str, Any],
        block: ScheduledBlock,
    ) -> bool:
        """Return whether an existing event already matches a block."""

        desired = self.event_from_block(block)
        private = event.get("extendedProperties", {}).get("private", {})
        desired_private = desired["extendedProperties"]["private"]
        return (
            event.get("summary") == desired["summary"]
            and event.get("description") == desired["description"]
            and event.get("start", {}).get("dateTime") == desired["start"]["dateTime"]
            and event.get("start", {}).get("timeZone") == desired["start"]["timeZone"]
            and event.get("end", {}).get("dateTime") == desired["end"]["dateTime"]
            and event.get("end", {}).get("timeZone") == desired["end"]["timeZone"]
            and private.get("planner_os") == desired_private["planner_os"]
            and private.get("planner_block_id") == desired_private["planner_block_id"]
            and private.get("planner_task_id", "") == desired_private["planner_task_id"]
            and private.get("planner_source") == desired_private["planner_source"]
            and private.get("planner_version") == desired_private["planner_version"]
            and private.get("category") == desired_private["category"]
        )

    def _rrule_with_until(self, rule: str, until: str) -> str:
        parts = [part for part in rule.split(";") if not part.startswith(("UNTIL=", "COUNT="))]
        parts.append(f"UNTIL={until}")
        return ";".join(parts)

    def _record_sync(
        self,
        plan: DailyPlan | WeeklyPlan,
        result: CalendarSyncResult,
    ) -> list[str]:
        """Record calendar sync in the Decision Log without blocking sync."""

        try:
            self.decision_log.record(
                action="calendar_sync",
                reason="Synchronize Planner OS scheduled blocks to Google Calendar",
                confidence=1.0 if result.success else 0.5,
                affected_tasks=[
                    block.title for block in self._blocks_for_plan(plan)
                ],
                constraints_considered=[
                    "idempotent sync",
                    "preserve manual events",
                    "Planner OS private extended properties",
                ],
                outcome=(
                    DecisionOutcome.SUCCESS if result.success else DecisionOutcome.WARNING
                ),
                metadata=result.to_dict(),
            )
        except Exception as error:
            return [f"Decision log warning: {error}"]
        return []

    def _api_datetime(self, value: datetime) -> str:
        """Return an RFC3339 timestamp acceptable to Google Calendar APIs."""

        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(self.timezone))
        return value.isoformat()

    def _range_datetime(
        self,
        value: datetime | date | None,
        *,
        beginning: bool,
    ) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if beginning:
            return datetime.combine(value, time.min, ZoneInfo(self.timezone))
        return datetime.combine(value + timedelta(days=1), time.min, ZoneInfo(self.timezone))
