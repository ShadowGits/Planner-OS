"""Apple Calendar transport models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AppleCalendarStatus:
    permission: str
    calendar_id: str | None
    helper_ready: bool
