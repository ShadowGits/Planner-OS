"""Durable JSONL decision log for Planner OS."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_DECISION_LOG_PATH = Path("logs/decision_log.jsonl")


class DecisionOutcome(str, Enum):
    """Outcome states for logged planner decisions."""

    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"
    GENERATED = "generated"


@dataclass(frozen=True)
class DecisionRecord:
    """A durable planner decision or mutation record."""

    id: str
    timestamp: str
    action: str
    reason: str
    confidence: float
    affected_tasks: list[str]
    constraints_considered: list[str]
    outcome: DecisionOutcome
    backup_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        data = asdict(self)
        data["outcome"] = self.outcome.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionRecord":
        """Build a record from persisted JSON data."""

        return cls(
            id=str(data["id"]),
            timestamp=str(data["timestamp"]),
            action=str(data["action"]),
            reason=str(data["reason"]),
            confidence=float(data["confidence"]),
            affected_tasks=[str(item) for item in data.get("affected_tasks", [])],
            constraints_considered=[
                str(item) for item in data.get("constraints_considered", [])
            ],
            outcome=DecisionOutcome(str(data["outcome"])),
            backup_path=(
                str(data["backup_path"]) if data.get("backup_path") is not None else None
            ),
            metadata=dict(data.get("metadata", {})),
        )


class DecisionLog:
    """Append and query planner decision records from JSONL storage."""

    def __init__(self, log_path: str | Path = DEFAULT_DECISION_LOG_PATH) -> None:
        self.log_path = Path(log_path)

    def record(
        self,
        *,
        action: str,
        reason: str,
        confidence: float,
        affected_tasks: list[str] | None = None,
        constraints_considered: list[str] | None = None,
        outcome: DecisionOutcome = DecisionOutcome.SUCCESS,
        backup_path: str | Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionRecord:
        """Persist a planner decision and return the typed record."""

        record = DecisionRecord(
            id=str(uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            action=action,
            reason=reason,
            confidence=confidence,
            affected_tasks=affected_tasks or [],
            constraints_considered=constraints_considered or [],
            outcome=outcome,
            backup_path=str(backup_path) if backup_path is not None else None,
            metadata=metadata or {},
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
        return record

    def list_recent(self, limit: int = 10) -> list[DecisionRecord]:
        """Return the most recent valid records."""

        if limit <= 0:
            return []
        return self._read_records()[-limit:]

    def find_by_id(self, record_id: str) -> DecisionRecord | None:
        """Find a record by unique id."""

        for record in self._read_records():
            if record.id == record_id:
                return record
        return None

    def list_by_action(self, action: str) -> list[DecisionRecord]:
        """Return records matching an action."""

        normalized = action.casefold()
        return [
            record
            for record in self._read_records()
            if record.action.casefold() == normalized
        ]

    def list_by_task(self, task_name: str) -> list[DecisionRecord]:
        """Return records affecting a task name."""

        normalized = task_name.casefold()
        return [
            record
            for record in self._read_records()
            if any(task.casefold() == normalized for task in record.affected_tasks)
        ]

    def clear_test_log(self) -> None:
        """Clear this log file for isolated tests."""

        if self.log_path.exists():
            self.log_path.unlink()

    def _read_records(self) -> list[DecisionRecord]:
        """Read valid JSONL records, skipping malformed lines."""

        if not self.log_path.exists():
            return []

        records: list[DecisionRecord] = []
        with self.log_path.open("r", encoding="utf-8") as log_file:
            for line in log_file:
                try:
                    raw = json.loads(line)
                    if isinstance(raw, dict):
                        records.append(DecisionRecord.from_dict(raw))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
        return records
