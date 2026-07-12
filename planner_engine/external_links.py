"""Persistent one-active-target mappings for planner blocks."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


class ExternalLinkConflict(ValueError):
    pass


class ExternalLinkStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def list(self, *, target_name: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        links = self._load()
        return [link for link in links if (target_name is None or link["target_name"] == target_name) and (status is None or link["status"] == status)]

    def active_for(self, planner_block_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list(status="active") if item["planner_block_id"] == planner_block_id), None)

    def upsert(self, planner_block_id: str, target_name: str, external_id: str, checksum: str) -> dict[str, Any]:
        links = self._load()
        active = next((item for item in links if item["planner_block_id"] == planner_block_id and item["status"] == "active"), None)
        if active and active["target_name"] != target_name:
            raise ExternalLinkConflict(f"Block {planner_block_id} is already active in {active['target_name']}; use an explicit migration")
        now = datetime.now(timezone.utc).isoformat()
        record = active or {"planner_block_id": planner_block_id, "published_at": now}
        record.update({"target_name": target_name, "external_id": external_id, "status": "active", "last_synced_at": now, "checksum": checksum})
        if active is None:
            links.append(record)
        self._save(links)
        return dict(record)

    def deactivate(self, planner_block_id: str, target_name: str) -> None:
        links = self._load()
        for item in links:
            if item["planner_block_id"] == planner_block_id and item["target_name"] == target_name and item["status"] == "active":
                item["status"] = "inactive"
        self._save(links)

    def retire_target(self, target_name: str) -> int:
        links = self._load()
        changed = 0
        for item in links:
            if item.get("target_name") == target_name and item.get("status") != "retired_unsupported":
                item["status"] = "retired_unsupported"
                item["retired_reason"] = f"Execution target {target_name} is no longer supported"
                changed += 1
        if changed:
            self._backup()
            self._save(links)
        return changed

    def _backup(self) -> None:
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".pre-mvp2-apple.bak"))

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []

    def _save(self, links: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
            json.dump(links, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(self.path)
