"""Read-only local Planner OS diagnostics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from planner_engine.execution_manager import ExecutionSettings
from planner_engine.external_links import ExternalLinkStore
from planner_engine.rules import RulesEngine
from planner_engine.workbook_schema import WorkbookSchemaInspector


@dataclass(frozen=True)
class DoctorReport:
    success: bool
    checks: dict[str, str]
    warnings: list[str]
    errors: list[str]

    def to_dict(self):
        return asdict(self)


class PlannerDoctor:
    def __init__(self, workbook: Path, rules: Path, settings: Path, links: Path, previews: Path, decision_log: Path, backups: Path) -> None:
        self.workbook, self.rules, self.settings, self.links = workbook, rules, settings, links
        self.previews, self.decision_log, self.backups = previews, decision_log, backups

    def run(self):
        checks, warnings, errors = {}, [], []
        try:
            capabilities, issues = WorkbookSchemaInspector(self.workbook).inspect()
            checks["workbook"] = "readable"
            if issues:
                errors.extend(f"{item.section}: expected {item.expected}; actual {item.actual}" for item in issues)
            checks["workbook_capabilities"] = json.dumps(capabilities.to_dict(), sort_keys=True)
        except Exception as error:
            errors.append(f"workbook: {error}")
        try:
            RulesEngine(self.rules)
            checks["rules"] = "valid"
        except Exception as error:
            errors.append(f"rules: {error}")
        try:
            target = ExecutionSettings(self.settings).get_active()
            checks["active_target"] = target
        except Exception as error:
            errors.append(f"execution settings: {error}")
        links = ExternalLinkStore(self.links).list()
        active_ids = [item["planner_block_id"] for item in links if item.get("status") == "active"]
        duplicates = sorted({item for item in active_ids if active_ids.count(item) > 1})
        if duplicates:
            errors.append(f"duplicate active external links: {', '.join(duplicates)}")
        checks["external_links"] = f"{len(links)} record(s)"
        stale = 0
        now = datetime.now(timezone.utc)
        for path in self.previews.rglob("*.json") if self.previews.exists() else []:
            try:
                expiry = json.loads(path.read_text(encoding="utf-8")).get("expires_at")
                stale += int(bool(expiry and datetime.fromisoformat(expiry) <= now))
            except Exception:
                warnings.append(f"Unreadable preview: {path.name}")
        checks["stale_previews"] = str(stale)
        malformed = 0
        if self.decision_log.exists():
            for line in self.decision_log.read_text(encoding="utf-8").splitlines():
                try: json.loads(line)
                except json.JSONDecodeError: malformed += 1
        checks["decision_log_corruption"] = str(malformed)
        if malformed:
            errors.append(f"decision log has {malformed} malformed record(s)")
        backup_count = len(list(self.backups.glob("*.xlsx"))) if self.backups.exists() else 0
        checks["backups"] = str(backup_count)
        if not backup_count:
            warnings.append("No workbook backup is currently available")
        return DoctorReport(not errors, checks, warnings, errors)
