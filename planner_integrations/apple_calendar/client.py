"""JSON subprocess client for the native EventKit helper."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


class AppleCalendarError(RuntimeError):
    pass


class AppleCalendarClient:
    def __init__(self, helper_path: str | Path, calendar_id: str | None = None, timeout: int = 10, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self.helper_path = Path(helper_path)
        self.calendar_id = calendar_id
        self.timeout = timeout
        self.runner = runner

    def call(self, operation: str, **payload: Any) -> dict[str, Any]:
        if not self.helper_path.exists():
            raise AppleCalendarError(f"Apple Calendar helper not built: {self.helper_path}. See planner_integrations/apple_calendar/README.md")
        request = {"operation": operation, "calendar_id": self.calendar_id, **payload}
        if self._app_bundle_path() is not None and self.runner is subprocess.run:
            response = self._call_app_bundle(request)
            if not response.get("success", False):
                raise AppleCalendarError("; ".join(response.get("errors", ["Apple Calendar operation failed"])))
            return response
        completed = self.runner([str(self.helper_path)], input=json.dumps(request), capture_output=True, text=True, timeout=self.timeout, check=False)
        if completed.returncode:
            raise AppleCalendarError(completed.stderr.strip() or f"Apple Calendar helper failed with exit {completed.returncode}")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise AppleCalendarError("Apple Calendar helper returned invalid JSON") from error
        if not response.get("success", False):
            raise AppleCalendarError("; ".join(response.get("errors", ["Apple Calendar operation failed"])))
        return response

    def _app_bundle_path(self) -> Path | None:
        for parent in self.helper_path.parents:
            if parent.suffix == ".app":
                return parent
        return None

    def _call_app_bundle(self, request: dict[str, Any]) -> dict[str, Any]:
        app_path = self._app_bundle_path()
        if app_path is None:
            raise AppleCalendarError("Apple Calendar app bundle not found")
        with tempfile.TemporaryDirectory(prefix="planner-apple-calendar-") as directory:
            request_path = Path(directory) / "request.json"
            response_path = Path(directory) / "response.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            completed = self.runner(
                [
                    "open",
                    "-W",
                    str(app_path),
                    "--args",
                    "--request-file",
                    str(request_path),
                    "--response-file",
                    str(response_path),
                ],
                capture_output=True,
                text=True,
                timeout=max(self.timeout, 35),
                check=False,
            )
            if completed.returncode:
                raise AppleCalendarError(completed.stderr.strip() or f"Apple Calendar helper failed with exit {completed.returncode}")
            if not response_path.exists():
                raise AppleCalendarError("Apple Calendar helper returned no response")
            try:
                return json.loads(response_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise AppleCalendarError("Apple Calendar helper returned invalid JSON") from error

    def permission_status(self) -> dict[str, Any]:
        return self.call("permission_status")

    def list_calendars(self) -> list[dict[str, Any]]:
        return list(self.call("list_calendars").get("data", {}).get("calendars", []))

    def create_calendar(self, title: str = "Planner OS") -> dict[str, Any]:
        return self.call("create_calendar", title=title)["data"]

    def create_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return self.call("create_event", event=event)["data"]

    def read_event(self, external_id: str) -> dict[str, Any]:
        return self.call("read_event", external_id=external_id)["data"]

    def update_event(self, external_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return self.call("update_event", external_id=external_id, event=event)["data"]

    def delete_event(self, external_id: str, delete_scope: str = "single") -> None:
        self.call("delete_event", external_id=external_id, delete_scope=delete_scope)

    def list_events(self, start: str, end: str) -> list[dict[str, Any]]:
        return list(self.call("list_events", start=start, end=end).get("data", {}).get("events", []))
