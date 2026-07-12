"""Persistent local preference management for Planner OS."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from planner_engine.execution_manager import ExecutionSettings
from planner_engine.rules_manager import RulesManager


@dataclass(frozen=True)
class PreferenceResult:
    success: bool
    message: str
    preferences: dict[str, Any]
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PreferenceService:
    """Expose editable user preferences without source-code changes."""

    RULE_ALIASES = {
        "work_days": "work.active_days",
        "no_work_days": "work.no_work_days",
        "sleep_schedule": "sleep",
        "work_hours": "work.hours",
        "gym_target": "gym.weekly_sessions",
        "dance_restrictions": "dance.restrictions",
        "german_frequency": "german.frequency",
        "ielts_frequency": "ielts.weekly_sessions",
        "ignou_frequency": "ignou.weekly_sessions",
        "piano_duration": "piano.daily_minutes",
        "reading_preference": "reading.preferred_daypart",
        "preferred_dayparts": "preferences.preferred_dayparts",
        "carry_forward_behavior": "preferences.carry_forward",
        "preview_apply_policy": "preferences.preview_apply_policy",
        "google_calendar_target_calendar": "google.calendar_id",
    }

    EXECUTION_ALIASES = {"active_execution_target", "apple_calendar_target_calendar"}

    def __init__(self, rules: RulesManager, execution_settings: ExecutionSettings) -> None:
        self.rules = rules
        self.execution_settings = execution_settings

    def list_preferences(self) -> PreferenceResult:
        prefs = {
            "rules": self.rules.list_rules(),
            "execution": self.execution_settings.list_targets(),
            "aliases": {
                **{key: value for key, value in sorted(self.RULE_ALIASES.items())},
                "active_execution_target": "execution.active_target",
                "apple_calendar_target_calendar": "execution.apple_calendar_id",
            },
        }
        return PreferenceResult(True, "Preferences listed", prefs, list(self.execution_settings.migration_warnings), [])

    def get_preference(self, name: str) -> PreferenceResult:
        try:
            value = self._get(name)
            return PreferenceResult(True, f"Preference {name} loaded", {name: value}, [], [])
        except Exception as error:
            return PreferenceResult(False, f"Preference {name} not available", {}, [], [str(error)])

    def update_preference(self, name: str, value: Any) -> PreferenceResult:
        try:
            if name == "active_execution_target":
                updated = {"active_execution_target": self.execution_settings.set_active(str(value))}
            elif name == "apple_calendar_target_calendar":
                updated = {"apple_calendar_target_calendar": self.execution_settings.set_apple_calendar_id(str(value))}
            else:
                path = self.RULE_ALIASES.get(name, name)
                updated = self.rules.update_rule(path, value)
            return PreferenceResult(True, f"Preference {name} updated", {name: self._get(name), "raw": updated}, [], [])
        except Exception as error:
            return PreferenceResult(False, f"Preference {name} was not updated", {}, [], [str(error)])

    def reset_preference(self, name: str) -> PreferenceResult:
        if name == "active_execution_target":
            return self.update_preference(name, "none")
        return PreferenceResult(False, f"Preference {name} cannot be reset automatically", {}, [], ["Only active_execution_target has a safe built-in reset in this build"])

    def explain_active_constraints(self) -> PreferenceResult:
        rules = self.rules.list_rules()
        execution = self.execution_settings.list_targets()
        constraints = {
            "active_execution_target": execution["active_target"],
            "no_work_days": rules.get("work", {}).get("no_work_days", rules.get("work", {}).get("off_days", [])),
            "work_days": rules.get("work", {}).get("active_days", []),
            "sleep": rules.get("sleep", {}),
            "calendar_publication": "disabled" if execution["active_target"] == "none" else f"publishes to {execution['active_target']}",
            "preview_policy": execution.get("publish_mode", "preview_first"),
        }
        return PreferenceResult(True, "Active constraints explained", constraints, [], [])

    def _get(self, name: str) -> Any:
        if name == "active_execution_target":
            return self.execution_settings.get_active()
        if name == "apple_calendar_target_calendar":
            return self.execution_settings.get_apple_calendar_id()
        rules = self.rules.list_rules()
        path = self.RULE_ALIASES.get(name, name)
        value: Any = rules
        for key in path.split("."):
            if not isinstance(value, dict) or key not in value:
                raise KeyError(f"Unknown preference: {name}")
            value = value[key]
        return value
