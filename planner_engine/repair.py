"""Preview-first local repair operations for Planner OS."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from planner_engine.external_links import ExternalLinkStore


@dataclass(frozen=True)
class RepairPreview:
    preview_id: str
    operation: str
    actions: list[dict[str, str]]
    warnings: list[str] = field(default_factory=list)
    requires_confirmation: bool = True
    expires_at: str = field(default_factory=lambda: (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class PlannerRepairService:
    """Generate and apply safe local repairs. External deletion is not automatic."""

    def __init__(self, links: ExternalLinkStore, preview_dir: str | Path) -> None:
        self.links = links
        self.preview_dir = Path(preview_dir)

    def preview_repair(self) -> RepairPreview:
        links = self.links.list()
        actions: list[dict[str, str]] = []
        warnings: list[str] = []
        for item in links:
            if item.get("target_name") == "structured" and item.get("status") != "retired_unsupported":
                actions.append({"type": "retire_unsupported_link", "planner_block_id": str(item.get("planner_block_id", "")), "target_name": "structured"})
            if item.get("target_name") not in {"google_calendar", "apple_calendar", "none", "structured"}:
                actions.append({"type": "mark_invalid_target", "planner_block_id": str(item.get("planner_block_id", "")), "target_name": str(item.get("target_name", ""))})
            if not item.get("external_id"):
                actions.append({"type": "deactivate_missing_external_id", "planner_block_id": str(item.get("planner_block_id", "")), "target_name": str(item.get("target_name", ""))})
            if item.get("status") not in {"active", "inactive", "retired_unsupported", "inactive_duplicate", "orphaned", "deleted", "repaired-from-calendar"}:
                actions.append({"type": "normalize_invalid_status", "planner_block_id": str(item.get("planner_block_id", "")), "target_name": str(item.get("target_name", ""))})
        active_by_block: dict[str, list[dict]] = {}
        external_ids: dict[str, list[dict]] = {}
        for item in links:
            if item.get("status") == "active":
                active_by_block.setdefault(str(item.get("planner_block_id", "")), []).append(item)
                external_ids.setdefault(str(item.get("external_id", "")), []).append(item)
        for block_id, records in active_by_block.items():
            if len(records) > 1:
                for record in records[1:]:
                    actions.append({"type": "deactivate_duplicate_link", "planner_block_id": block_id, "target_name": str(record.get("target_name", ""))})
                warnings.append(f"Block {block_id} has duplicate active external links")
        for external_id, records in external_ids.items():
            if external_id and len(records) > 1:
                for record in records[1:]:
                    actions.append({"type": "deactivate_duplicate_external_id", "planner_block_id": str(record.get("planner_block_id", "")), "target_name": str(record.get("target_name", "")), "external_id": external_id})
                warnings.append(f"External item {external_id} is linked to multiple planner blocks")
        for path in self.preview_dir.rglob("*.json") if self.preview_dir.exists() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                expires_at = data.get("expires_at")
                if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
                    actions.append({"type": "archive_stale_preview", "preview_file": path.name})
            except Exception:
                actions.append({"type": "archive_unreadable_preview", "preview_file": path.name})
        preview = RepairPreview(str(uuid4()), "planner_repair", actions, warnings)
        self._save(preview)
        return preview

    def apply_repair(self, preview_id: str) -> dict:
        preview = self._load(preview_id)
        links = self.links._load()
        applied = 0
        for action in preview.actions:
            if action["type"] == "retire_unsupported_link":
                applied += self.links.retire_target(action["target_name"])
            elif action["type"] in {"deactivate_duplicate_link", "deactivate_duplicate_external_id", "deactivate_missing_external_id"}:
                for item in links:
                    if item.get("planner_block_id") == action["planner_block_id"] and item.get("target_name") == action["target_name"] and item.get("status") == "active":
                        item["status"] = "inactive_duplicate" if "duplicate" in action["type"] else "inactive"
                        applied += 1
                self.links._save(links)
            elif action["type"] == "mark_invalid_target":
                for item in links:
                    if item.get("planner_block_id") == action["planner_block_id"] and item.get("target_name") == action["target_name"]:
                        item["status"] = "unsupported_target"
                        applied += 1
                self.links._save(links)
            elif action["type"] == "normalize_invalid_status":
                for item in links:
                    if item.get("planner_block_id") == action["planner_block_id"] and item.get("target_name") == action["target_name"]:
                        item["status"] = "inactive"
                        applied += 1
                self.links._save(links)
            elif action["type"] in {"archive_stale_preview", "archive_unreadable_preview"}:
                path = self.preview_dir / action["preview_file"]
                if path.exists():
                    archive = self.preview_dir / "archive"
                    archive.mkdir(parents=True, exist_ok=True)
                    path.replace(archive / path.name)
                    applied += 1
        self._mark_applied(preview_id)
        return {"success": True, "preview_id": preview_id, "applied_actions": applied, "external_events_deleted": 0}

    def _save(self, preview: RepairPreview) -> None:
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        (self.preview_dir / f"{preview.preview_id}.json").write_text(json.dumps(preview.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _load(self, preview_id: str) -> RepairPreview:
        path = self.preview_dir / f"{preview_id}.json"
        if not path.exists():
            raise ValueError("Unknown repair preview")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("applied_at"):
            raise ValueError("Repair preview was already applied")
        if data["operation"] != "planner_repair":
            raise ValueError("Repair preview operation does not match")
        if datetime.fromisoformat(data["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("Repair preview expired")
        return RepairPreview(**{key: data[key] for key in RepairPreview.__dataclass_fields__ if key in data})

    def _mark_applied(self, preview_id: str) -> None:
        path = self.preview_dir / f"{preview_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["applied_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
