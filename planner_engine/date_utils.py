"""Shared, explicit date-range helpers for Planner OS product commands."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

from planner_engine.models import MonthPlan


def parse_month(month: str) -> date:
    """Return the first date represented by a planner month label."""

    return datetime.strptime(month, "%b %Y").date().replace(day=1)


def month_bounds(month: str) -> tuple[date, date]:
    """Return inclusive month boundaries."""

    start = parse_month(month)
    return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])


def current_week_range(today: date) -> tuple[date, date]:
    """Return the Monday-Sunday range containing today."""

    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def next_week_range(today: date) -> tuple[date, date]:
    """Return the Monday-Sunday range after the week containing today."""

    start, _ = current_week_range(today)
    start += timedelta(days=7)
    return start, start + timedelta(days=6)


def workbook_week_range(month_plan: MonthPlan, week_number: int) -> tuple[date, date]:
    """Resolve a workbook WEEK section to its explicit heading date range."""

    if week_number < 1 or week_number > len(month_plan.week_sections):
        raise ValueError(f"Unknown week {week_number} in month {month_plan.month}")
    section = month_plan.week_sections[week_number - 1]
    parsed = _parse_week_title(section.title, month_plan.month)
    if parsed is not None:
        return parsed
    month_start, month_end = month_bounds(month_plan.month)
    start = month_start + timedelta(days=(week_number - 1) * 7)
    return start, min(month_end, start + timedelta(days=6))


def week_number_for_date(month_plan: MonthPlan, target_date: date) -> int:
    """Return the explicit workbook week containing a date."""

    for number in range(1, len(month_plan.week_sections) + 1):
        start, end = workbook_week_range(month_plan, number)
        if start <= target_date <= end:
            return number
    return ((target_date.day - 1) // 7) + 1


def _parse_week_title(title: str, month: str) -> tuple[date, date] | None:
    normalized = " ".join(title.replace("–", "-").replace("—", "-").split())
    match = re.search(
        r"(?P<sd>\d{1,2})\s+(?P<sm>[A-Za-z]{3})"
        r"(?:\s+(?P<sy>\d{4}))?\s*-\s*"
        r"(?P<ed>\d{1,2})\s+(?P<em>[A-Za-z]{3})\s+(?P<ey>\d{4})",
        normalized,
    )
    if match is None:
        return None
    end_year = int(match.group("ey"))
    if match.group("sy"):
        start_year = int(match.group("sy"))
    else:
        start_month = datetime.strptime(match.group("sm"), "%b").month
        end_month = datetime.strptime(match.group("em"), "%b").month
        start_year = end_year - 1 if start_month > end_month else end_year
    start = datetime.strptime(
        f"{match.group('sd')} {match.group('sm')} {start_year}", "%d %b %Y"
    ).date()
    end = datetime.strptime(
        f"{match.group('ed')} {match.group('em')} {end_year}", "%d %b %Y"
    ).date()
    return start, end
