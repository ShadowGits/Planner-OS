"""User-editable Planner OS rules stored as validated YAML data."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable

import yaml

from planner_engine.rules import RulesEngine, RulesValidationError


WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_DAY_LOOKUP = {day.casefold(): day for day in WEEKDAYS}


class RulePathError(ValueError):
    """Raised when a requested rule path is not an editable config value."""


class RulesManager:
    """List and safely update permanent planner rules in YAML."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)

    def list_rules(self) -> dict[str, Any]:
        """Return a detached copy of the current rules mapping."""

        return deepcopy(self._load_raw_rules())

    def update_rule(self, path: str, value: Any) -> dict[str, Any]:
        """Update an existing dotted YAML path and persist it after validation."""

        keys = self._path_keys(path)
        rules = self._load_raw_rules()
        parent: Any = rules
        for key in keys[:-1]:
            if not isinstance(parent, dict) or key not in parent:
                raise RulePathError(f"Unknown rule path: {path}")
            parent = parent[key]

        leaf = keys[-1]
        if not isinstance(parent, dict) or leaf not in parent:
            raise RulePathError(f"Unknown rule path: {path}")

        if path == "work.active_days":
            return self.set_work_days(self._require_day_list(value, path))
        if path in {"work.no_work_days", "work.off_days"}:
            return self.set_no_work_days(self._require_day_list(value, path))

        parent[leaf] = value
        self._persist_validated(rules)
        return self.list_rules()

    def set_work_days(self, days: Iterable[str]) -> dict[str, Any]:
        """Set active work days and derive the complementary no-work days."""

        active_days = self._normalize_days(days)
        rules = self._load_raw_rules()
        work = self._work_mapping(rules)
        work["active_days"] = active_days
        work["no_work_days"] = [day for day in WEEKDAYS if day not in active_days]
        work.pop("off_days", None)
        self._persist_validated(rules)
        return self.list_rules()

    def set_no_work_days(self, days: Iterable[str]) -> dict[str, Any]:
        """Set no-work days and derive the complementary active work days."""

        no_work_days = self._normalize_days(days)
        rules = self._load_raw_rules()
        work = self._work_mapping(rules)
        work["no_work_days"] = no_work_days
        work["active_days"] = [day for day in WEEKDAYS if day not in no_work_days]
        work.pop("off_days", None)
        self._persist_validated(rules)
        return self.list_rules()

    def add_no_work_day(self, day: str) -> dict[str, Any]:
        """Add one no-work day without duplicating it."""

        rules = self._load_raw_rules()
        work = self._work_mapping(rules)
        current = work.get("no_work_days", work.get("off_days", ()))
        normalized = self._normalize_days([*current, day])
        return self.set_no_work_days(normalized)

    def remove_no_work_day(self, day: str) -> dict[str, Any]:
        """Remove one no-work day and make it active for work."""

        canonical_day = self._normalize_days([day])[0]
        rules = self._load_raw_rules()
        work = self._work_mapping(rules)
        current = self._normalize_days(
            work.get("no_work_days", work.get("off_days", ()))
        )
        return self.set_no_work_days(
            existing for existing in current if existing != canonical_day
        )

    def _load_raw_rules(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Rules config not found: {self.config_path}")
        with self.config_path.open("r", encoding="utf-8") as rules_file:
            rules = yaml.safe_load(rules_file)
        if not isinstance(rules, dict):
            raise RulesValidationError("Rules config must be a YAML mapping.")
        return rules

    def _persist_validated(self, rules: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.config_path.parent,
                prefix=f".{self.config_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                yaml.safe_dump(rules, temporary_file, sort_keys=False)
                temporary_path = Path(temporary_file.name)
            RulesEngine(temporary_path)
            temporary_path.replace(self.config_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _work_mapping(self, rules: dict[str, Any]) -> dict[str, Any]:
        work = rules.get("work")
        if not isinstance(work, dict):
            raise RulesValidationError("Missing required rules field: work")
        return work

    def _path_keys(self, path: str) -> list[str]:
        keys = path.split(".") if isinstance(path, str) else []
        if not keys or any(not key for key in keys):
            raise RulePathError(f"Invalid rule path: {path!r}")
        return keys

    def _require_day_list(self, value: Any, path: str) -> list[str]:
        if not isinstance(value, (list, tuple)):
            raise RulesValidationError(f"Rule {path} must be a list of day names")
        return list(value)

    def _normalize_days(self, days: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for day in days:
            if not isinstance(day, str) or day.strip().casefold() not in _DAY_LOOKUP:
                raise RulesValidationError(f"Invalid day name: {day!r}")
            canonical = _DAY_LOOKUP[day.strip().casefold()]
            if canonical not in normalized:
                normalized.append(canonical)
        return [day for day in WEEKDAYS if day in normalized]
