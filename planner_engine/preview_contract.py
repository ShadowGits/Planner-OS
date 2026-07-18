"""Shared stale-preview and source-revision enforcement for local previews.

Every previewed mutation stores a contract alongside its payload: the preview
kind, creation and expiry times, a single-use applied marker, and a content
fingerprint of the planner state it was computed from. Apply operations
validate the contract in one place instead of each service reimplementing
its own subset of the checks.

Previews saved before this contract existed carry no ``_contract`` block.
They validate as legacy previews so an upgrade never invalidates a preview
the user is about to apply; each service's pre-existing checks still run.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

CONTRACT_KEY = "_contract"
DEFAULT_TTL_HOURS = 24


class PreviewContractError(ValueError):
    """Base error for preview contract violations."""


class PreviewNotFoundError(PreviewContractError):
    pass


class PreviewKindMismatchError(PreviewContractError):
    pass


class PreviewExpiredError(PreviewContractError):
    pass


class PreviewAlreadyAppliedError(PreviewContractError):
    pass


class StalePreviewError(PreviewContractError):
    pass


def compute_fingerprint(sources: Mapping[str, Path]) -> dict[str, str]:
    """Hash each named source file's content; absent files hash as "absent"."""

    fingerprint: dict[str, str] = {}
    for name in sorted(sources):
        path = Path(sources[name])
        if path.exists():
            fingerprint[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            fingerprint[name] = "absent"
    return fingerprint


class PreviewContract:
    """Seal and validate previews against named planner source files.

    ``sources`` maps dependency names (for example ``workbook``, ``rules``,
    ``settings``, ``external_links``) to the files whose content a preview
    may depend on. Each sealed preview records which dependencies it used,
    so unrelated changes never invalidate it.
    """

    def __init__(
        self,
        sources: Mapping[str, str | Path],
        ttl_hours: float = DEFAULT_TTL_HOURS,
    ) -> None:
        self.sources = {name: Path(path) for name, path in sources.items()}
        self.ttl_hours = ttl_hours

    def seal(
        self,
        payload: dict[str, Any],
        *,
        kind: str,
        depends_on: Iterable[str],
    ) -> dict[str, Any]:
        """Attach a contract block to a preview payload before persisting it."""

        selected = {name: self.sources[name] for name in depends_on}
        now = datetime.now(timezone.utc)
        payload[CONTRACT_KEY] = {
            "kind": kind,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=self.ttl_hours)).isoformat(),
            "applied_at": None,
            "source_fingerprint": compute_fingerprint(selected),
        }
        return payload

    def validate(self, payload: Mapping[str, Any], *, kind: str) -> None:
        """Reject mismatched, expired, consumed, or stale sealed previews."""

        meta = payload.get(CONTRACT_KEY)
        if meta is None:
            return
        if meta.get("kind") != kind:
            raise PreviewKindMismatchError(
                f"Preview was created for {meta.get('kind')!r}, not {kind!r}"
            )
        if meta.get("applied_at"):
            raise PreviewAlreadyAppliedError(
                "Preview was already applied; run the preview again"
            )
        expires_at = meta.get("expires_at")
        if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
            raise PreviewExpiredError("Preview has expired; run the preview again")
        expected = meta.get("source_fingerprint") or {}
        current = compute_fingerprint(
            {name: self.sources[name] for name in expected if name in self.sources}
        )
        for name, digest in expected.items():
            if current.get(name, digest) != digest:
                raise StalePreviewError(
                    f"Preview is stale because {name.replace('_', ' ')} changed "
                    "since the preview; run the preview again"
                )

    @staticmethod
    def load_and_validate_file(
        contract: "PreviewContract",
        path: Path,
        *,
        kind: str,
    ) -> dict[str, Any]:
        """Load one stored preview JSON file and validate its contract."""

        if not path.exists():
            raise PreviewNotFoundError("Unknown preview")
        payload = json.loads(path.read_text(encoding="utf-8"))
        contract.validate(payload, kind=kind)
        return payload

    @staticmethod
    def mark_applied_file(path: Path) -> None:
        """Set the single-use applied marker on one stored preview file."""

        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.setdefault(CONTRACT_KEY, {})
        meta["applied_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
