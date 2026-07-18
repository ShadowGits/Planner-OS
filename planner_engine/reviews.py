"""Read-only daily, weekly, and monthly planner reviews."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from planner_engine.checkin import DailyCheckInService
from planner_engine.date_utils import month_bounds, week_number_for_date
from planner_engine.models import TaskStatus
from planner_engine.planner import PlannerEngine
from planner_engine.rules import RulesEngine


@dataclass(frozen=True)
class PlannerReview:
    period: str
    start_date: str
    end_date: str
    planned: list[str]
    completed: list[str]
    skipped: list[str]
    overdue: list[str]
    recurring_adherence: dict[str, Any]
    goal_progress: dict[str, Any]
    upcoming_risks: list[str]
    recommended_adjustments: list[str]
    missed_commitments: list[str] = None
    moved: list[str] = None
    recurring_streaks: dict[str, int] = None

    def to_dict(self):
        data = asdict(self)
        data["missed_commitments"] = data["missed_commitments"] or []
        data["moved"] = data["moved"] or []
        data["recurring_streaks"] = data["recurring_streaks"] or {}
        return data


class ReviewService:
    def __init__(self, engine: PlannerEngine, rules_engine: RulesEngine | None = None) -> None:
        self.engine = engine
        self.rules_engine = rules_engine

    def daily_review(self, target: date | None = None):
        day = target or date.today()
        report = DailyCheckInService(self.engine, rules_engine=self.rules_engine).generate_daily_checkin(day)
        return PlannerReview(
            "daily",
            day.isoformat(),
            day.isoformat(),
            report.planned_tasks,
            report.completed_tasks,
            [],
            report.missed_tasks,
            report.recurring_status,
            {
                "daily_completion_percentage": report.today_completion_percentage,
                "weekly_completion_percentage": report.weekly_completion_percentage,
                "monthly_completion_percentage": report.monthly_completion_percentage,
                "tomorrow_carryover": report.tomorrow_carryover,
            },
            [item["reason"] for item in report.slippage_alerts],
            report.recommended_actions,
            missed_commitments=report.missed_tasks,
            moved=report.tomorrow_carryover,
            recurring_streaks=report.streaks,
        )

    def weekly_review(self, target: date | None = None):
        day = target or date.today()
        start, end = day - timedelta(days=day.weekday()), day - timedelta(days=day.weekday()) + timedelta(days=6)
        plan = self.engine.get_month_plan(day.strftime("%b %Y"))
        week = week_number_for_date(plan, day)
        items = list(plan.week_sections[week - 1].tasks) if 0 < week <= len(plan.week_sections) else []
        return self._review("weekly", start, end, items)

    def monthly_review(self, month: str):
        start, end = month_bounds(month)
        plan = self.engine.get_month_plan(month)
        items = [*plan.monthly_goals, *(task for section in plan.week_sections for task in section.tasks)]
        return self._review("monthly", start, end, items)

    def _review(self, period, start, end, items):
        completed = [item.name for item in items if item.status == TaskStatus.DONE]
        skipped = [item.name for item in items if self._is_skipped(item)]
        overdue = [
            item.name
            for item in items
            if item.status != TaskStatus.DONE and not self._is_skipped(item)
        ]
        percentage = round(len(completed) / len(items) * 100, 2) if items else 0.0
        moved = [
            item.name
            for item in items
            if "moved" in str(getattr(item, "notes", "") or "").casefold()
            or "rescheduled" in str(getattr(item, "notes", "") or "").casefold()
        ]
        recommendations = [f"Review or carry forward: {name}" for name in overdue[:3]]
        recurring = self._recurring_adherence(items)
        risks = [f"{len(overdue)} incomplete item(s)" ] if overdue else []
        if skipped:
            risks.append(f"{len(skipped)} skipped item(s)")
        return PlannerReview(
            period,
            start.isoformat(),
            end.isoformat(),
            [item.name for item in items],
            completed,
            skipped,
            overdue,
            recurring,
            {
                "completion_percentage": percentage,
                "completed_count": len(completed),
                "planned_count": len(items),
                "overdue_count": len(overdue),
            },
            risks,
            recommendations,
            missed_commitments=overdue,
            moved=moved,
            recurring_streaks={},
        )

    def _is_skipped(self, item) -> bool:
        raw_status = getattr(item, "raw_status", None)
        return " ".join(str(raw_status or "").casefold().split()) == "skipped"

    def _recurring_adherence(self, items) -> dict[str, Any]:
        names = " ".join(item.name.casefold() for item in items)
        return {
            "german_planned": "german" in names,
            "gym_planned": "gym" in names,
            "ielts_planned": "ielts" in names,
            "ignou_planned": "ignou" in names,
        }
