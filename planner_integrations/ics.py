"""Minimal iCalendar (.ics) reader for importing a public Apple/iCloud calendar.

Deliberately small and dependency-free — it parses the handful of fields an
import needs (UID, summary, start, end) from the VEVENTs in a feed, rather than
pulling in a full iCalendar library. Recurring events (RRULE) are skipped; a
repeating commitment belongs in the habit engine, not as a wall of imported
tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass
class VEvent:
    uid: str
    summary: str
    start: datetime | date       # date for an all-day event, datetime otherwise
    end: datetime | date | None
    all_day: bool
    recurring: bool


def _unfold(text: str) -> list[str]:
    """Join continuation lines. A line beginning with a space or tab continues
    the previous one — the standard iCalendar line-folding."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for line in raw:
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n").replace("\\N", "\n")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    )


def _split_prop(line: str) -> tuple[str, dict[str, str], str]:
    """Return (name, params, value) for one content line, e.g.
    'DTSTART;TZID=Asia/Kolkata:20260913T140000'."""
    head, _, value = line.partition(":")
    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v
    return name, params, value


def _parse_dt(value: str, params: dict[str, str]) -> tuple[datetime | date, bool]:
    """Parse an iCalendar date or datetime into a value plus an all-day flag.

    Timed values come back timezone-aware: a trailing Z is UTC, a TZID names a
    zone, and a bare local time is left naive for the caller to place in the
    workspace's zone.
    """
    if params.get("VALUE") == "DATE" or (len(value) == 8 and "T" not in value):
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8])), True

    stamp = value.rstrip("Z")
    dt = datetime.strptime(stamp, "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return dt.replace(tzinfo=ZoneInfo("UTC")), False
    tzid = params.get("TZID")
    if tzid:
        try:
            return dt.replace(tzinfo=ZoneInfo(tzid)), False
        except ZoneInfoNotFoundError:
            return dt, False   # unknown zone: treat as naive/local
    return dt, False


def parse_ics(text: str) -> list[VEvent]:
    """Every VEVENT in the feed, as VEvent records. Malformed events are
    skipped rather than failing the whole import."""
    events: list[VEvent] = []
    in_event = False
    cur: dict = {}
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            in_event, cur = True, {}
            continue
        if line == "END:VEVENT":
            in_event = False
            uid = cur.get("uid")
            start = cur.get("start")
            if uid and start is not None:
                events.append(
                    VEvent(
                        uid=uid,
                        summary=cur.get("summary", "(no title)"),
                        start=start,
                        end=cur.get("end"),
                        all_day=cur.get("all_day", False),
                        recurring=cur.get("recurring", False),
                    )
                )
            continue
        if not in_event:
            continue
        name, params, value = _split_prop(line)
        if name == "UID":
            cur["uid"] = value.strip()
        elif name == "SUMMARY":
            cur["summary"] = _unescape(value).strip()
        elif name == "DTSTART":
            cur["start"], cur["all_day"] = _parse_dt(value, params)
        elif name == "DTEND":
            cur["end"], _ = _parse_dt(value, params)
        elif name == "RRULE":
            cur["recurring"] = True
    return events


def occurrence_in_window(
    event: VEvent, window_start: date, window_end: date, timezone: str
) -> tuple[date, str | None, int | None] | None:
    """Where a one-off event lands for the workspace, or None if it falls
    outside the window or repeats.

    Returns (scheduled_date, start_time 'HH:MM' or None for all-day, duration
    in minutes or None), with any timezone-aware start converted into the
    workspace's local day and time.
    """
    if event.recurring:
        return None
    tz = ZoneInfo(timezone)

    if event.all_day:
        day = event.start if isinstance(event.start, date) and not isinstance(event.start, datetime) else event.start.date()
        if not (window_start <= day <= window_end):
            return None
        return day, None, None

    start = event.start
    if not isinstance(start, datetime):
        return None
    local = start.astimezone(tz) if start.tzinfo else start.replace(tzinfo=tz)
    day = local.date()
    if not (window_start <= day <= window_end):
        return None

    minutes = None
    end = event.end
    if isinstance(end, datetime):
        end_local = end.astimezone(tz) if end.tzinfo else end.replace(tzinfo=tz)
        minutes = max(1, int((end_local - local).total_seconds() // 60))

    return day, local.strftime("%H:%M"), minutes
