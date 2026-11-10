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


def fit_day(
    items: list[dict[str, Any]],
    *,
    move_ids: Iterable[str] | None = None,
    after: int | None = None,
    window_start: int = DEFAULT_WINDOW_START,
    window_end: int = DEFAULT_WINDOW_END,
    gap: int = 0,
    is_fixed: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Work out where the day's loose ends should go.

    move_ids names what to place; left out, it takes everything unfinished
    that has no time yet or whose slot has already passed. Anything `is_fixed`
    calls true — a habit, an appointment — stays where it is, and so does
    anything already finished.

    Returns the placements, whatever would not fit and why, and how full the
    window is, but changes nothing.
    """
    window_end = min(window_end, DAY_END)
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
    busy = busy_spans(items, moving)
    # Start on a five-minute mark: nobody wants a task at 15:07 because that
    # happened to be the minute they asked. What has slipped is still judged
    # by the real minute, above.
    start_from = None if after is None else -(-after // 5) * 5
    gaps = free_gaps(busy, window_start, window_end, start_from)
    placements: list[dict[str, Any]] = []

    for item in placement_order(chosen):
        minutes = item_minutes(item)
        for index, (start, end) in enumerate(gaps):
            # A gap that follows something else owes it the breathing space.
            offset = gap if (start > window_start and (start_from is None or start > start_from)) else 0
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
                gaps[index] = (begin + minutes, end)
                gaps = [one for one in gaps if one[1] > one[0]]
                break
        else:
            room_left = sum(one[1] - one[0] for one in gaps)
            unplaced.append(
                {
                    "id": str(item.get("id")),
                    "title": item.get("title"),
                    "minutes": minutes,
                    "reason": "no_gap_big_enough" if room_left else "day_is_full",
                }
            )

    booked = sum(end - start for start, end in busy if end > window_start and start < window_end)
    span = max(window_end - max(window_start, start_from or window_start), 0)
    return {
        "placements": placements,
        "unplaced": unplaced,
        "window": {"start": format_clock(window_start), "end": format_clock(window_end)},
        "booked_minutes": booked,
        "free_minutes": max(span - booked, 0),
        "considered": len(chosen),
    }


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
