from __future__ import annotations

import json
import io
import sys
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest import TestCase
from unittest.mock import patch

from planner_engine.decision_log import DecisionLog
from planner_engine.models import DailyPlan, MonthPlan, ScheduledBlock
from planner_integrations.google_calendar import (
    GoogleCalendarClient,
    GoogleCalendarError,
)


class FakeExecute:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result if result is not None else {}
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.result


class FakeEvents:
    def __init__(self, service) -> None:
        self.service = service

    def list(self, **kwargs):
        self.service.calls.append(("list", kwargs))
        time_min = datetime.fromisoformat(kwargs["timeMin"])
        time_max = datetime.fromisoformat(kwargs["timeMax"])
        items = [
            event
            for event in self.service.events_data
            if self.service.event_start(event) < time_max
            and self.service.event_end(event) > time_min
        ]
        return FakeExecute({"items": items})

    def insert(self, **kwargs):
        self.service.calls.append(("insert", kwargs))
        if self.service.insert_errors:
            return FakeExecute(error=self.service.insert_errors.pop(0))
        event = {"id": f"created-{len(self.service.calls)}", **kwargs["body"]}
        self.service.events_data.append(event)
        return FakeExecute(event)

    def get(self, **kwargs):
        self.service.calls.append(("get", kwargs))
        event = next((item for item in self.service.events_data if item.get("id") == kwargs["eventId"]), None)
        return FakeExecute(event or {}, None if event else RuntimeError("not found"))

    def update(self, **kwargs):
        self.service.calls.append(("update", kwargs))
        if self.service.update_errors:
            return FakeExecute(error=self.service.update_errors.pop(0))
        event = {"id": kwargs["eventId"], **kwargs["body"]}
        self.service.events_data = [
            event if item.get("id") == kwargs["eventId"] else item
            for item in self.service.events_data
        ]
        return FakeExecute(event)

    def delete(self, **kwargs):
        self.service.calls.append(("delete", kwargs))
        if self.service.delete_errors:
            return FakeExecute(error=self.service.delete_errors.pop(0))
        self.service.events_data = [
            item for item in self.service.events_data if item.get("id") != kwargs["eventId"]
        ]
        return FakeExecute({})


class FakeBatch:
    """Mimic googleapiclient's batch request: run each add on execute()."""

    def __init__(self, service, callback) -> None:
        self.service = service
        self.callback = callback
        self.requests = []

    def add(self, request, request_id=None):
        self.requests.append((request_id, request))

    def execute(self):
        self.service.calls.append(("batch", {"size": len(self.requests)}))
        for request_id, request in self.requests:
            try:
                response = request.execute()
            except Exception as exc:  # noqa: BLE001 - mirror real batch callback
                self.callback(request_id, None, exc)
            else:
                self.callback(request_id, response, None)


class FakeService:
    def __init__(self, events_data=None) -> None:
        self.events_data = events_data or []
        self.calls = []
        self.insert_errors = []
        self.update_errors = []
        self.delete_errors = []

    def events(self):
        return FakeEvents(self)

    def new_batch_http_request(self, callback):
        return FakeBatch(self, callback)

    def event_start(self, event):
        return datetime.fromisoformat(event.get("start", {}).get("dateTime", "1900-01-01T00:00:00+00:00"))

    def event_end(self, event):
        return datetime.fromisoformat(event.get("end", {}).get("dateTime", "1900-01-01T00:00:00+00:00"))


def block(
    title: str = "Study",
    start: datetime = datetime(2026, 7, 11, 19, 0),
    end: datetime = datetime(2026, 7, 11, 20, 0),
    category: str = "learning",
) -> ScheduledBlock:
    return ScheduledBlock(
        title=title,
        start=start,
        end=end,
        category=category,
        source="test",
    )


def plan_with(*blocks: ScheduledBlock) -> DailyPlan:
    return DailyPlan(date=date(2026, 7, 11), blocks=list(blocks), conflicts=[])


class GoogleCalendarClientTests(TestCase):
    """Tests for mocked Google Calendar integration."""

    def test_missing_credentials_returns_clear_error(self) -> None:
        with TemporaryDirectory() as directory:
            client = GoogleCalendarClient(
                credentials_path=Path(directory) / "credentials.json",
                token_path=Path(directory) / "token.json",
            )

            with self.assertRaisesRegex(
                GoogleCalendarError,
                "credentials.json not found",
            ):
                client.authenticate()

    def test_oauth_configuration_writes_token(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            credentials_path = tmp_path / "credentials.json"
            token_path = tmp_path / "token.json"
            credentials_path.write_text("{}", encoding="utf-8")
            fake_credentials = FakeCredentials()

            with patch.dict(
                sys.modules,
                self._fake_google_modules(fake_credentials),
            ):
                client = GoogleCalendarClient(
                    credentials_path=credentials_path,
                    token_path=token_path,
                )
                service = client.authenticate()

            self.assertEqual(service, "calendar-service")
            self.assertEqual(json.loads(token_path.read_text(encoding="utf-8")), {"ok": True})
            self.assertEqual(FakeFlow.last_secrets_path, str(credentials_path))
            self.assertEqual(FakeFlow.last_scopes, ("https://www.googleapis.com/auth/calendar.events",))

    def test_existing_valid_token_skips_oauth_flow_import(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            credentials_path = tmp_path / "credentials.json"
            token_path = tmp_path / "token.json"
            credentials_path.write_text("{}", encoding="utf-8")
            token_path.write_text("{}", encoding="utf-8")
            modules = self._fake_google_modules(FakeCredentials())
            modules["google_auth_oauthlib.flow"] = None

            with patch.dict(sys.modules, modules):
                client = GoogleCalendarClient(
                    credentials_path=credentials_path,
                    token_path=token_path,
                )
                service = client.authenticate()

            self.assertEqual(service, "calendar-service")
            self.assertEqual(json.loads(token_path.read_text(encoding="utf-8")), {"ok": True})

    def test_event_mapping_timezone_category_and_stable_identifier(self) -> None:
        with TemporaryDirectory() as directory:
            client = GoogleCalendarClient(
                service=FakeService(),
                decision_log=DecisionLog(Path(directory) / "decision_log.jsonl"),
            )
            scheduled = block(category="fitness")

            event = client.event_from_block(scheduled)

            self.assertEqual(event["summary"], "Study")
            self.assertEqual(event["start"]["dateTime"], "2026-07-11T19:00:00+05:30")
            self.assertEqual(event["end"]["dateTime"], "2026-07-11T20:00:00+05:30")
            self.assertEqual(event["start"]["timeZone"], "Asia/Kolkata")
            self.assertEqual(event["end"]["timeZone"], "Asia/Kolkata")
            private = event["extendedProperties"]["private"]
            self.assertEqual(private["planner_os"], "true")
            self.assertEqual(private["category"], "fitness")
            self.assertEqual(
                private["planner_block_id"],
                client.stable_block_id(scheduled),
            )
            self.assertEqual(client.stable_block_id(scheduled), client.stable_block_id(scheduled))

    def test_cross_midnight_event_mapping(self) -> None:
        with TemporaryDirectory() as directory:
            client = GoogleCalendarClient(
                service=FakeService(),
                decision_log=DecisionLog(Path(directory) / "decision_log.jsonl"),
            )
            scheduled = block(
                title="Late work",
                start=datetime(2026, 9, 7, 20, 30),
                end=datetime(2026, 9, 8, 3, 30),
                category="work",
            )

            event = client.event_from_block(scheduled)

            self.assertEqual(event["start"]["dateTime"], "2026-09-07T20:30:00+05:30")
            self.assertEqual(event["end"]["dateTime"], "2026-09-08T03:30:00+05:30")

    def test_list_events_uses_timezone_aware_api_range(self) -> None:
        service = FakeService()
        client = GoogleCalendarClient(service=service)

        client.list_events(
            datetime(2026, 7, 11, 19, 0),
            datetime(2026, 7, 11, 20, 0),
        )

        self.assertEqual(service.calls[0][1]["timeMin"], "2026-07-11T19:00:00+05:30")
        self.assertEqual(service.calls[0][1]["timeMax"], "2026-07-11T20:00:00+05:30")

    def test_idempotent_sync_create_update_delete_unchanged_and_preserve_manual(self) -> None:
        with TemporaryDirectory() as directory:
            client = GoogleCalendarClient(
                service=FakeService(),
                decision_log=DecisionLog(Path(directory) / "decision_log.jsonl"),
            )
            create_block = block("Create")
            update_block = block("Update")
            unchanged_block = block("Unchanged")
            stale_event = self._event_for(client, block("Stale"), event_id="stale")
            manual_event = {"id": "manual", "summary": "Manual"}
            changed_event = self._event_for(client, update_block, event_id="update")
            changed_event["summary"] = "Old title"
            unchanged_event = self._event_for(client, unchanged_block, event_id="unchanged")
            client.service.events_data = [
                changed_event,
                unchanged_event,
                stale_event,
                manual_event,
            ]

            result = client.sync_plan(plan_with(create_block, update_block, unchanged_block))

            self.assertTrue(result.success)
            self.assertEqual(result.created, 1)
            self.assertEqual(result.updated, 1)
            self.assertEqual(result.deleted, 1)
            self.assertEqual(result.unchanged, 1)
            self.assertEqual(
                [call[0] for call in client.service.calls],
                ["list", "insert", "update", "delete"],
            )
            deleted_ids = [call[1]["eventId"] for call in client.service.calls if call[0] == "delete"]
            self.assertEqual(deleted_ids, ["stale"])

    def test_partial_api_failures_are_reported(self) -> None:
        with TemporaryDirectory() as directory:
            service = FakeService()
            service.insert_errors.append(RuntimeError("insert failed"))
            client = GoogleCalendarClient(
                service=service,
                decision_log=DecisionLog(Path(directory) / "decision_log.jsonl"),
            )

            result = client.sync_plan(plan_with(block("Create")))

            self.assertFalse(result.success)
            self.assertEqual(result.created, 0)
            self.assertIn("Create: insert failed", result.errors)

    def test_owned_event_delete_and_unrelated_event_preserved(self) -> None:
        client = GoogleCalendarClient(service=FakeService())
        owned = self._event_for(client, block("German"), event_id="owned")
        manual = {"id": "manual", "summary": "Manual"}
        client.service.events_data = [owned, manual]
        client.delete_planner_event("owned")
        self.assertEqual([call[0] for call in client.service.calls], ["get", "delete"])
        with self.assertRaisesRegex(GoogleCalendarError, "not owned"):
            client.delete_planner_event("manual")

    def test_recurring_series_and_future_deletion(self) -> None:
        client = GoogleCalendarClient(service=FakeService())
        master = self._event_for(client, block("German"), event_id="series")
        master["recurrence"] = ["RRULE:FREQ=DAILY"]
        instance = self._event_for(client, block("German"), event_id="instance")
        instance["recurringEventId"] = "series"
        instance["originalStartTime"] = {"dateTime": "2026-07-11T19:00:00+05:30"}
        client.service.events_data = [master, instance]
        client.delete_event_scope("instance", "future")
        update = [call for call in client.service.calls if call[0] == "update"][-1]
        self.assertIn("UNTIL=", update[1]["body"]["recurrence"][0])
        client.service.calls.clear()
        client.delete_event_scope("series", "series")
        self.assertIn("delete", [call[0] for call in client.service.calls])

    def test_cli_calendar_auth_and_sync(self) -> None:
        from planner_engine.cli import ShadowCLI, build_parser

        class FakeCalendarClient:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

            def authenticate(self):
                return object()

            def sync_plan(self, plan):
                del plan
                return FakeSyncResult()

        class FakeScheduler:
            def __init__(self, rules) -> None:
                del rules

            def plan_day(self, month_plan, target_date):
                del month_plan, target_date
                return plan_with(block())

        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            auth_args = build_parser().parse_args(
                [
                    "--google-token",
                    str(tmp_path / "token.json"),
                    "calendar-auth",
                ]
            )
            sync_args = build_parser().parse_args(["calendar-sync", "today"])
            with patch("planner_engine.cli.GoogleCalendarClient", FakeCalendarClient):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(ShadowCLI(auth_args).run(), 0)
            with (
                patch("planner_engine.cli.GoogleCalendarClient", FakeCalendarClient),
                patch("planner_engine.cli.SchedulerEngine", FakeScheduler),
                patch.object(ShadowCLI, "_month_plan", return_value=MonthPlan("Jul 2026", "Jul 2026", [], [])),
            ):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(ShadowCLI(sync_args).run(), 0)

    def test_mcp_calendar_sync_tools(self) -> None:
        from planner_mcp.tools import PlannerMCPTools

        class FakeScheduler:
            def __init__(self, rules) -> None:
                del rules

            def plan_day(self, month_plan, target_date):
                del month_plan, target_date
                return plan_with(block())

            def plan_week(self, month_plan, week_start):
                del month_plan, week_start
                return plan_with(block())

        class FakeCalendarClient:
            def sync_plan(self, plan):
                del plan
                return FakeSyncResult()

        tools = PlannerMCPTools()
        with (
            patch("planner_mcp.tools.SchedulerEngine", FakeScheduler),
            patch.object(PlannerMCPTools, "_month_plan", return_value=MonthPlan("Jul 2026", "Jul 2026", [], [])),
            patch.object(PlannerMCPTools, "_calendar_client", return_value=FakeCalendarClient()),
        ):
            today_result = tools.calendar_sync_today()
            week_result = tools.calendar_sync_week()

        self.assertTrue(today_result["success"])
        self.assertTrue(week_result["success"])
        self.assertEqual(today_result["data"]["created"], 1)

    def _event_for(
        self,
        client: GoogleCalendarClient,
        scheduled: ScheduledBlock,
        event_id: str,
    ) -> dict:
        event = client.event_from_block(scheduled)
        event["id"] = event_id
        return event

    def _fake_google_modules(self, credentials) -> dict[str, ModuleType]:
        request_module = ModuleType("google.auth.transport.requests")
        request_module.Request = lambda: object()

        credentials_module = ModuleType("google.oauth2.credentials")
        credentials_module.Credentials = FakeCredentialsClass

        flow_module = ModuleType("google_auth_oauthlib.flow")
        flow_module.InstalledAppFlow = FakeFlow
        FakeFlow.credentials = credentials

        discovery_module = ModuleType("googleapiclient.discovery")
        discovery_module.build = lambda *args, **kwargs: "calendar-service"

        return {
            "google.auth.transport.requests": request_module,
            "google.oauth2.credentials": credentials_module,
            "google_auth_oauthlib.flow": flow_module,
            "googleapiclient.discovery": discovery_module,
        }


class FakeCredentials:
    valid = True
    expired = False
    refresh_token = None

    def to_json(self) -> str:
        return json.dumps({"ok": True})


class FakeCredentialsClass:
    @classmethod
    def from_authorized_user_file(cls, path, scopes):
        del path, scopes
        return FakeCredentials()


class FakeFlow:
    credentials = FakeCredentials()
    last_secrets_path = ""
    last_scopes = ()

    @classmethod
    def from_client_secrets_file(cls, secrets_path, scopes):
        cls.last_secrets_path = secrets_path
        cls.last_scopes = tuple(scopes)
        return cls()

    def run_local_server(self, port=0):
        self.port = port
        return self.credentials


class FakeSyncResult:
    created = 1
    updated = 2
    deleted = 3
    unchanged = 4
    errors = []
    warnings = []
    success = True

    def to_dict(self) -> dict:
        return {
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "unchanged": self.unchanged,
            "errors": self.errors,
            "warnings": self.warnings,
            "success": self.success,
        }
