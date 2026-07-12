"""Typed rules loading and validation for Planner OS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class RulesValidationError(ValueError):
    """Raised when a rules configuration is missing required data."""


@dataclass(frozen=True)
class ProfileRules:
    """User profile rules."""

    name: str
    timezone: str
    location: str


@dataclass(frozen=True)
class TimeWindowRules:
    """A start and end time window."""

    start: str
    end: str


@dataclass(frozen=True)
class WorkRules:
    """Work schedule rule windows."""

    active_days: tuple[str, ...]
    no_work_days: tuple[str, ...]
    july_august: TimeWindowRules
    september_onward: TimeWindowRules


@dataclass(frozen=True)
class GymRules:
    """Gym frequency and class rules."""

    sessions_per_week: int
    double_class_days_per_week: int
    single_class_days_per_week: int
    one_class_equals_one_session: bool
    dance_forbidden_days: tuple[str, ...]


@dataclass(frozen=True)
class GermanRules:
    """German study cadence rules."""

    frequency: str
    allow_breaks: bool


@dataclass(frozen=True)
class WeeklySessionRules:
    """A weekly fixed session target."""

    sessions_per_week: int


@dataclass(frozen=True)
class IgnouRules:
    """IGNOU weekly session range."""

    sessions_per_week_min: int
    sessions_per_week_max: int


@dataclass(frozen=True)
class PianoRules:
    """Piano practice duration rules."""

    duration_minutes: int


@dataclass(frozen=True)
class ReadingRules:
    """Reading preference rules."""

    preferred_time: str


@dataclass(frozen=True)
class PlanningRules:
    """Planner behavior guardrails."""

    excel_is_source_of_truth: bool
    edit_immediately: bool
    backup_before_write: bool
    move_unfinished_tasks_instead_of_deleting: bool
    daily_follow_up: bool
    alert_on_weekly_slippage: bool
    alert_on_monthly_slippage: bool


@dataclass(frozen=True)
class PlannerRules:
    """Complete typed rules configuration."""

    profile: ProfileRules
    sleep: TimeWindowRules
    work: WorkRules
    gym: GymRules
    german: GermanRules
    ielts: WeeklySessionRules
    ignou: IgnouRules
    piano: PianoRules
    reading: ReadingRules
    planning: PlanningRules


class RulesEngine:
    """Load, validate, and query Planner OS rules."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self.rules = self._load_rules()

    def is_dance_allowed(self, day_name: str) -> bool:
        """Return whether dance is allowed on a day name."""

        forbidden_days = {
            day.casefold() for day in self.rules.gym.dance_forbidden_days
        }
        return day_name.casefold() not in forbidden_days

    def is_work_day(self, day_name: str) -> bool:
        """Return whether office work is scheduled on a day name."""

        normalized_day = day_name.casefold()
        active_days = {day.casefold() for day in self.rules.work.active_days}
        no_work_days = {day.casefold() for day in self.rules.work.no_work_days}
        return normalized_day in active_days and normalized_day not in no_work_days

    def is_rule_enabled(self, rule_name: str) -> bool:
        """Return whether a rule section should generate scheduled blocks."""

        section = getattr(self, "_raw_rules", {}).get(rule_name, {})
        if not isinstance(section, dict):
            return True
        if section.get("enabled") is False:
            return False
        if str(section.get("status", "")).strip().casefold() == "disabled":
            return False
        frequency = section.get("frequency")
        if frequency is not None and str(frequency).strip().casefold() == "none":
            return False
        return True

    def required_gym_sessions(self) -> int:
        """Return the weekly gym session target."""

        return self.rules.gym.sessions_per_week

    def required_german_sessions(self, days_in_period: int) -> int:
        """Return required German sessions for a period."""

        if self.rules.german.frequency != "daily":
            raise RulesValidationError(
                f"Unsupported german.frequency: {self.rules.german.frequency}"
            )
        return days_in_period

    def required_ielts_sessions(self) -> int:
        """Return the weekly IELTS session target."""

        return self.rules.ielts.sessions_per_week

    def ignou_session_range(self) -> tuple[int, int]:
        """Return the weekly IGNOU session range."""

        return (
            self.rules.ignou.sessions_per_week_min,
            self.rules.ignou.sessions_per_week_max,
        )

    def piano_duration_minutes(self) -> int:
        """Return the required piano practice duration."""

        return self.rules.piano.duration_minutes

    def _load_rules(self) -> PlannerRules:
        """Load and validate rules from YAML."""

        if not self.config_path.exists():
            raise FileNotFoundError(f"Rules config not found: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as rules_file:
            raw_rules = yaml.safe_load(rules_file)

        if not isinstance(raw_rules, dict):
            raise RulesValidationError("Rules config must be a YAML mapping.")

        self._raw_rules = raw_rules
        self._validate_required_fields(raw_rules)
        return self._build_rules(raw_rules)

    def _validate_required_fields(self, raw_rules: dict[str, Any]) -> None:
        """Validate all required sections and fields exist."""

        required_paths = (
            ("profile", "name"),
            ("profile", "timezone"),
            ("profile", "location"),
            ("sleep", "start"),
            ("sleep", "end"),
            ("work", "july_august", "start"),
            ("work", "july_august", "end"),
            ("work", "september_onward", "start"),
            ("work", "september_onward", "end"),
            ("gym", "sessions_per_week"),
            ("gym", "double_class_days_per_week"),
            ("gym", "single_class_days_per_week"),
            ("gym", "one_class_equals_one_session"),
            ("gym", "dance_forbidden_days"),
            ("german", "frequency"),
            ("german", "allow_breaks"),
            ("ielts", "sessions_per_week"),
            ("ignou", "sessions_per_week_min"),
            ("ignou", "sessions_per_week_max"),
            ("piano", "duration_minutes"),
            ("reading", "preferred_time"),
            ("planning", "excel_is_source_of_truth"),
            ("planning", "edit_immediately"),
            ("planning", "backup_before_write"),
            ("planning", "move_unfinished_tasks_instead_of_deleting"),
            ("planning", "daily_follow_up"),
            ("planning", "alert_on_weekly_slippage"),
            ("planning", "alert_on_monthly_slippage"),
        )

        for path in required_paths:
            self._require_path(raw_rules, path)

    def _require_path(self, raw_rules: dict[str, Any], path: tuple[str, ...]) -> None:
        """Raise a clear validation error if a required path is missing."""

        current: Any = raw_rules
        for key in path:
            if not isinstance(current, dict) or key not in current:
                dotted_path = ".".join(path)
                raise RulesValidationError(
                    f"Missing required rules field: {dotted_path}"
                )
            current = current[key]

    def _build_rules(self, raw_rules: dict[str, Any]) -> PlannerRules:
        """Build typed rules from validated raw YAML data."""

        return PlannerRules(
            profile=ProfileRules(**raw_rules["profile"]),
            sleep=TimeWindowRules(**raw_rules["sleep"]),
            work=WorkRules(
                active_days=tuple(
                    raw_rules["work"].get(
                        "active_days",
                        ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"),
                    )
                ),
                no_work_days=tuple(
                    raw_rules["work"].get(
                        "no_work_days",
                        raw_rules["work"].get(
                            "off_days",
                            ("Saturday", "Sunday"),
                        ),
                    )
                ),
                july_august=TimeWindowRules(**raw_rules["work"]["july_august"]),
                september_onward=TimeWindowRules(
                    **raw_rules["work"]["september_onward"]
                ),
            ),
            gym=GymRules(
                sessions_per_week=raw_rules["gym"]["sessions_per_week"],
                double_class_days_per_week=raw_rules["gym"][
                    "double_class_days_per_week"
                ],
                single_class_days_per_week=raw_rules["gym"][
                    "single_class_days_per_week"
                ],
                one_class_equals_one_session=raw_rules["gym"][
                    "one_class_equals_one_session"
                ],
                dance_forbidden_days=tuple(raw_rules["gym"]["dance_forbidden_days"]),
            ),
            german=GermanRules(**raw_rules["german"]),
            ielts=WeeklySessionRules(**raw_rules["ielts"]),
            ignou=IgnouRules(**raw_rules["ignou"]),
            piano=PianoRules(**raw_rules["piano"]),
            reading=ReadingRules(**raw_rules["reading"]),
            planning=PlanningRules(**raw_rules["planning"]),
        )
