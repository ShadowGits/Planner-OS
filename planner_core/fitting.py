"""Finding room in a day: no clashes, no cramming.

Deciding where a task goes is arithmetic, not judgement. The day already
knows what is booked, how long each thing takes and where the gaps are, so
this works it out the same way every time and can be tested. Nothing here
reads the database or guesses: it takes a day's items, returns where things
should go, and leaves the saving to the caller.

Everything is counted in minutes from midnight of the day in question, so a
slot at half past midnight is 1530 — twenty-five thirty — the way the
timeline already shows it. The planner's day runs to four in the morning.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from typing import Any, Callable, Iterable

# The planner's day ends at 04:00 the next morning.
DAY_END = 28 * 60
# Where a task is put when nobody said how long it takes.
DEFAULT_MINUTES = 30
# Nothing is dropped into the small hours by itself. The timeline still runs
# to 04:00 and a task can still be dragged there by hand; this is only the
# stretch this module is willing to fill on its own.
DEFAULT_WINDOW_START = 7 * 60
DEFAULT_WINDOW_END = 22 * 60


def parse_clock(value: Any) -> int | None:
    """"09:30", "09:30:00" or "25:30" to minutes after midnight."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None
    if hours < 0 or minutes < 0 or minutes > 59:
        return None
    return hours * 60 + minutes


def format_clock(minutes: int) -> str:
    """Minutes after midnight back to "25:30", which the task API accepts."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def spoken_clock(minutes: int) -> str:
    """"7:05 pm", for a sentence read out loud rather than a timeline."""
    hour24 = (minutes // 60) % 24
    minute = minutes % 60
    suffix = "am" if hour24 < 12 else "pm"
    hour = hour24 % 12 or 12
    return f"{hour}:{minute:02d} {suffix}"


def item_minutes(item: dict[str, Any]) -> int:
    """How long an item takes, with a sane answer when nobody said."""
    raw = item.get("estimated_minutes")
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MINUTES
    return minutes if minutes > 0 else DEFAULT_MINUTES


def item_span(item: dict[str, Any]) -> tuple[int, int] | None:
    """The minutes an item occupies, or None when it has no time yet."""
    start = parse_clock(item.get("start_time"))
    if start is None:
        return None
    return (start, start + item_minutes(item))


def merge_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Overlapping and touching spans joined into as few as possible."""
    ordered = sorted(span for span in spans if span[1] > span[0])
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def busy_spans(items: Iterable[dict[str, Any]], moving: set[str]) -> list[tuple[int, int]]:
    """When the day is already taken, ignoring the items about to be moved.

    A finished task still holds its place: it happened, and the hour it
    happened in is gone.
    """
    spans = []
    for item in items:
        if str(item.get("id")) in moving:
            continue
        span = item_span(item)
        if span is not None:
            spans.append(span)
    return merge_spans(spans)


def free_gaps(
    busy: list[tuple[int, int]],
    window_start: int,
    window_end: int,
    after: int | None = None,
) -> list[tuple[int, int]]:
    """The stretches left over inside the window, earliest first."""
    floor = window_start if after is None else max(window_start, after)
    if floor >= window_end:
        return []
    gaps: list[tuple[int, int]] = []
    cursor = floor
    for start, end in busy:
        if end <= cursor:
            continue
        if start > cursor:
            gaps.append((cursor, min(start, window_end)))
        cursor = max(cursor, end)
        if cursor >= window_end:
            break
    if cursor < window_end:
        gaps.append((cursor, window_end))
    return [gap for gap in gaps if gap[1] > gap[0]]


def is_slipped(item: dict[str, Any], after: int) -> bool:
    """True when an unfinished item's whole slot has already gone by.

    A task that is under way right now is left alone: it is happening. Only
    a slot that finished without the task being ticked off counts as missed.
    """
    if item.get("done"):
        return False
    span = item_span(item)
    return span is not None and span[1] <= after


def needs_a_slot(item: dict[str, Any]) -> bool:
    """Unfinished and with no time on it at all."""
    return not item.get("done") and item_span(item) is None


def placement_order(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What gets first refusal on the good gaps.

    Starred first, because the day is judged by those. Then whatever is due
    soonest. Then the longest, since a long task has the fewest places it
    can go and loses out if the short ones eat the day first.
    """
    return sorted(
        items,
        key=lambda item: (
            not item.get("starred"),
            str(item.get("due_date") or "9999-12-31"),
            -item_minutes(item),
            str(item.get("title") or ""),
        ),
    )


@dataclass(frozen=True)
class Window:
    """A stretch of the day Fit may fill, and how full it may make it.

    cap is the most work — tasks, not habits or appointments — the stretch
    may hold once Fit has finished, counting what is already there. keep_free
    is break time that must be left over; habits already in the stretch (the
    gym, reading) count towards it, so only the rest is held back. through
    lets a stretch sit inside a block that fills most of it: an hour of work
    placed "in office hours" is meant to overlap the office, not avoid it.
    """

    start: int
    end: int
    cap: int | None = None
    keep_free: int = 0
    through: bool = False


def _overlap(span: tuple[int, int], window: Window) -> int:
    return max(min(span[1], window.end) - max(span[0], window.start), 0)


def _span_setting(name: str, fallback: str) -> tuple[int, int] | None:
    """"12:00-21:00" from the environment, or None when it is switched off."""
    raw = os.environ.get(name, fallback).strip()
    if not raw:
        return None
    left, _, right = raw.partition("-")
    start, end = parse_clock(left), parse_clock(right)
    if start is None or end is None or end <= start:
        return None
    return start, min(end, DAY_END)


def default_windows() -> list[Window]:
    """The hours Fit plans into when nobody names any.

    Work goes between noon and nine in the evening, with three hours of that
    kept for lunch, reading and the gym — six hours of work at most. One more
    hour may go inside office hours, nine to half past three. Each can be
    changed without a release through the environment:

        PLANNER_FIT_HOURS=12:00-21:00      PLANNER_FIT_BREAK_MINUTES=180
        PLANNER_FIT_OFFICE=21:00-27:30     PLANNER_FIT_OFFICE_MINUTES=60

    An empty PLANNER_FIT_OFFICE switches the office hour off.
    """
    def number(name: str, fallback: int) -> int:
        try:
            return max(int(os.environ.get(name, fallback)), 0)
        except ValueError:
            return fallback

    hours = _span_setting("PLANNER_FIT_HOURS", "12:00-21:00") or (12 * 60, 21 * 60)
    breaks = min(number("PLANNER_FIT_BREAK_MINUTES", 180), hours[1] - hours[0])
    windows = [
        Window(hours[0], hours[1], cap=(hours[1] - hours[0]) - breaks if breaks else None, keep_free=breaks)
    ]
    office = _span_setting("PLANNER_FIT_OFFICE", "21:00-27:30")
    office_minutes = number("PLANNER_FIT_OFFICE_MINUTES", 60)
    if office and office_minutes:
        windows.append(Window(office[0], office[1], cap=office_minutes, through=True))
    return windows


def fit_day(
    items: list[dict[str, Any]],
    *,
    move_ids: Iterable[str] | None = None,
    after: int | None = None,
    window_start: int = DEFAULT_WINDOW_START,
    window_end: int = DEFAULT_WINDOW_END,
    gap: int = 0,
    is_fixed: Callable[[dict[str, Any]], bool] | None = None,
    windows: list[Window] | None = None,
) -> dict[str, Any]:
    """Work out where the day's loose ends should go.

    move_ids names what to place; left out, it takes everything unfinished
    that has no time yet or whose slot has already passed. Anything `is_fixed`
    calls true — a habit, an appointment — stays where it is, and so does
    anything already finished.

    windows are the stretches it may fill, tried in order for each task; left
    out, it is the one stretch from window_start to window_end with no limit
    on how full it gets.

    Returns the placements, whatever would not fit and why, and how full the
    first window is, but changes nothing.
    """
    if not windows:
        windows = [Window(window_start, min(window_end, DAY_END))]
    fixed = is_fixed or (lambda item: False)
    by_id = {str(item.get("id")): item for item in items}
    chosen: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []

    if move_ids is None:
        chosen = [
            item
            for item in items
            if not fixed(item)
            and (needs_a_slot(item) or (after is not None and is_slipped(item, after)))
        ]
    else:
        # Named tasks get an answer each, including the ones that cannot move,
        # so the caller can say why rather than quietly skipping them.
        for task_id in move_ids:
            item = by_id.get(str(task_id))
            if item is None:
                unplaced.append({"id": str(task_id), "title": None, "reason": "not_on_this_day"})
            elif item.get("done"):
                unplaced.append({"id": str(task_id), "title": item.get("title"), "reason": "already_done"})
            elif fixed(item):
                unplaced.append({"id": str(task_id), "title": item.get("title"), "reason": "fixed"})
            else:
                chosen.append(item)

    moving = {str(item.get("id")) for item in chosen}
    # Start on a five-minute mark: nobody wants a task at 15:07 because that
    # happened to be the minute they asked. What has slipped is still judged
    # by the real minute, above.
    start_from = None if after is None else -(-after // 5) * 5
    staying = [
        (item, span)
        for item in items
        if str(item.get("id")) not in moving and (span := item_span(item)) is not None
    ]

    # For each stretch: the gaps in it, and how much more work it may take.
    rooms: list[dict[str, Any]] = []
    for window in windows:
        length = window.end - window.start
        in_the_way = [
            (item, span)
            for item, span in staying
            # A block filling most of the stretch is what the stretch sits in.
            if not (window.through and _overlap(span, window) * 2 >= length)
        ]
        gaps = free_gaps(merge_spans(span for _, span in in_the_way), window.start, window.end, start_from)
        work = sum(_overlap(span, window) for item, span in in_the_way if not fixed(item))
        routine = sum(_overlap(span, window) for item, span in in_the_way if fixed(item))
        budget = None if window.cap is None else max(window.cap - work, 0)
        if window.keep_free:
            held_back = max(window.keep_free - routine, 0)
            spare = max(sum(end - start for start, end in gaps) - held_back, 0)
            budget = spare if budget is None else min(budget, spare)
        rooms.append({"window": window, "gaps": gaps, "budget": budget})

    placements: list[dict[str, Any]] = []
    for item in placement_order(chosen):
        minutes = item_minutes(item)
        placed = False
        for room in rooms:
            if room["budget"] is not None and minutes > room["budget"]:
                continue
            window = room["window"]
            for index, (start, end) in enumerate(room["gaps"]):
                # A gap that follows something else owes it the breathing space.
                offset = gap if (start > window.start and (start_from is None or start > start_from)) else 0
                begin = start + offset
                if begin + minutes <= end:
                    placements.append(
                        {
                            "id": str(item.get("id")),
                            "title": item.get("title"),
                            "start_time": format_clock(begin),
                            "start_minutes": begin,
                            "minutes": minutes,
                            "was": item.get("start_time"),
                        }
                    )
                    room["gaps"][index] = (begin + minutes, end)
                    room["gaps"] = [one for one in room["gaps"] if one[1] > one[0]]
                    if room["budget"] is not None:
                        room["budget"] -= minutes
                    placed = True
                    break
            if placed:
                break
        if not placed:
            room_left = sum(
                one[1] - one[0]
                for room in rooms
                if room["budget"] is None or room["budget"] > 0
                for one in room["gaps"]
            )
            unplaced.append(
                {
                    "id": str(item.get("id")),
                    "title": item.get("title"),
                    "minutes": minutes,
                    "reason": "no_gap_big_enough" if room_left else "day_is_full",
                }
            )

    first = windows[0]
    booked = sum(_overlap(span, first) for span in merge_spans(span for _, span in staying))
    span = max(first.end - max(first.start, start_from or first.start), 0)
    return {
        "placements": placements,
        "unplaced": unplaced,
        "window": {"start": format_clock(first.start), "end": format_clock(first.end)},
        "booked_minutes": booked,
        "free_minutes": max(span - booked, 0),
        "considered": len(chosen),
    }


def spread_sentence(placed: int, days: int, left: int) -> str:
    """What clearing the overdue pile did, in one line."""
    if not placed and not left:
        return "Nothing is overdue."
    if not placed:
        return f"None of the {left} overdue tasks would fit in the coming days."
    line = f"Planned {placed} overdue {'task' if placed == 1 else 'tasks'} over {days} {'day' if days == 1 else 'days'}"
    if left:
        line += f". {left} would not fit"
    return line + "."


def fit_sentence(result: dict[str, Any]) -> str:
    """One line that works read out loud and as a message on a screen.

    Voice, both apps and the dashboard all say this same sentence, so none of
    them can describe the same change differently.
    """
    placed = result["placements"]
    missed = result["unplaced"]
    if not placed and not missed:
        return "Nothing needed moving."
    sentence = ""
    if placed:
        earliest = min(placed, key=lambda one: one["start_minutes"])
        if len(placed) == 1:
            sentence = f"Moved {earliest['title']} to {spoken_clock(earliest['start_minutes'])}"
        else:
            sentence = (
                f"Moved {len(placed)} tasks, from {spoken_clock(earliest['start_minutes'])}"
            )
    if missed:
        tail = f"{len(missed)} would not fit"
        sentence = f"{sentence}. {tail}" if sentence else tail[0].upper() + tail[1:]
    return sentence.rstrip(".") + "."
