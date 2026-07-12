"""Shared preview-first destructive operations for execution targets."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


class ExecutionTargetOperations:
    def __init__(self, target, preview_dir: str | Path) -> None:
        self.target, self.preview_dir = target, Path(preview_dir)

    def preview_delete_range(self, start: date, end: date):
        items = self.target.list_items(start, end)
        preview = {
            "preview_id": str(uuid4()), "operation": f"{self.target.name}_delete_range",
            "target": self.target.name, "start_date": start.isoformat(), "end_date": end.isoformat(),
            "external_ids": [item.external_id for item in items],
            "items": [item.__dict__ for item in items],
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            "requires_confirmation": True,
        }
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        (self.preview_dir / f"{preview['preview_id']}.json").write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return preview

    def apply_delete_range(self, preview_id: str):
        path = self.preview_dir / f"{preview_id}.json"
        if not path.exists():
            raise ValueError("Unknown target deletion preview")
        preview = json.loads(path.read_text(encoding="utf-8"))
        if preview.get("applied_at"):
            raise ValueError("Target deletion preview was already applied")
        if preview["operation"] != f"{self.target.name}_delete_range":
            raise ValueError("Target deletion preview operation does not match")
        if datetime.fromisoformat(preview["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("Target deletion preview expired")
        current = self.target.list_items(date.fromisoformat(preview["start_date"]), date.fromisoformat(preview["end_date"]))
        if {item.external_id for item in current} != set(preview["external_ids"]):
            raise ValueError("External target changed since preview; create a new preview")
        errors, deleted = [], 0
        for external_id in preview["external_ids"]:
            result = self.target.delete_item(external_id)
            if result.success:
                deleted += 1
            else:
                errors.extend(result.errors)
        preview["applied_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"success": not errors, "deleted": deleted, "errors": errors}
