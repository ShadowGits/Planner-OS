"""Constrained undo support backed by Decision Log workbook backups."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from planner_engine.decision_log import DecisionLog, DecisionRecord
from planner_engine.excel import ExcelPlannerStore


@dataclass(frozen=True)
class UndoPreview:
    preview_id: str
    operation: str
    decision_id: str
    action: str
    backup_path: str
    warnings: list[str] = field(default_factory=list)
    requires_confirmation: bool = True
    expires_at: str = field(default_factory=lambda: (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class UndoService:
    """Undo workbook mutations only when a Decision Log backup proves scope."""

    def __init__(self, store: ExcelPlannerStore, decision_log: DecisionLog, preview_dir: str | Path) -> None:
        self.store = store
        self.decision_log = decision_log
        self.preview_dir = Path(preview_dir)

    def preview_undo(self, decision_id: str | None = None) -> UndoPreview:
        record = self._record(decision_id)
        if not record.backup_path:
            raise ValueError("Selected decision has no workbook backup to restore")
        backup = Path(record.backup_path)
        if not backup.exists():
            raise ValueError(f"Decision backup no longer exists: {backup}")
        preview = UndoPreview(str(uuid4()), "undo_workbook_backup", record.id, record.action, str(backup), ["External calendar reversals are not applied automatically"])
        self._save(preview)
        return preview

    def apply_undo(self, preview_id: str) -> dict:
        preview = self._load(preview_id)
        backup = Path(preview.backup_path)
        if not backup.exists():
            raise ValueError("Undo backup no longer exists")
        safety_backup = self.store.create_backup()
        self.store.restore_backup(backup)
        self._mark_applied(preview_id)
        return {"success": True, "preview_id": preview_id, "restored_backup": str(backup), "pre_undo_backup": str(safety_backup), "external_reversal_applied": False}

    def undo_last_change(self) -> dict:
        preview = self.preview_undo(None)
        return self.apply_undo(preview.preview_id)

    def _record(self, decision_id: str | None) -> DecisionRecord:
        if decision_id:
            record = self.decision_log.find_by_id(decision_id)
            if record is None:
                raise ValueError("Unknown decision id")
            return record
        for record in reversed(self.decision_log.list_recent(50)):
            if record.backup_path:
                return record
        raise ValueError("No undoable workbook decision found")

    def _save(self, preview: UndoPreview) -> None:
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        (self.preview_dir / f"{preview.preview_id}.json").write_text(json.dumps(preview.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _load(self, preview_id: str) -> UndoPreview:
        path = self.preview_dir / f"{preview_id}.json"
        if not path.exists():
            raise ValueError("Unknown undo preview")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("applied_at"):
            raise ValueError("Undo preview was already applied")
        if data["operation"] != "undo_workbook_backup":
            raise ValueError("Undo preview operation does not match")
        if datetime.fromisoformat(data["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("Undo preview expired")
        return UndoPreview(**{key: data[key] for key in UndoPreview.__dataclass_fields__ if key in data})

    def _mark_applied(self, preview_id: str) -> None:
        path = self.preview_dir / f"{preview_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["applied_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
