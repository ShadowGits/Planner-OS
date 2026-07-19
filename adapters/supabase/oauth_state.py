"""Persistent MCP OAuth state so tokens survive deploys and cold starts."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from adapters.supabase.client import SupabaseGateway


class MemoryOAuthStateStore:
    """In-memory store for local development and tests."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], tuple[dict[str, Any], float | None]] = {}

    def get(self, kind: str, record_key: str) -> dict[str, Any] | None:
        entry = self._records.get((kind, record_key))
        if entry is None:
            return None
        payload, expires_at = entry
        if expires_at is not None and time.time() > expires_at:
            self._records.pop((kind, record_key), None)
            return None
        return dict(payload)

    def put(
        self,
        kind: str,
        record_key: str,
        payload: dict[str, Any],
        expires_at: float | None,
    ) -> None:
        self._records[(kind, record_key)] = (dict(payload), expires_at)

    def delete(self, kind: str, record_key: str) -> None:
        self._records.pop((kind, record_key), None)


class SupabaseOAuthStateStore:
    """OAuth clients, codes, and tokens in the mcp_oauth_records table."""

    TABLE = "mcp_oauth_records"

    def __init__(self, client: SupabaseGateway) -> None:
        self.client = client

    def get(self, kind: str, record_key: str) -> dict[str, Any] | None:
        rows = self.client.select(
            self.TABLE,
            filters={"kind": kind, "record_key": record_key},
            limit=1,
        )
        if not rows:
            return None
        row = rows[0]
        expires_at = row.get("expires_at")
        if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
            self.delete(kind, record_key)
            return None
        payload = row.get("payload")
        return dict(payload) if isinstance(payload, dict) else None

    def put(
        self,
        kind: str,
        record_key: str,
        payload: dict[str, Any],
        expires_at: float | None,
    ) -> None:
        expires_text = (
            datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
            if expires_at is not None
            else None
        )
        record = {
            "kind": kind,
            "record_key": record_key,
            "payload": payload,
            "expires_at": expires_text,
        }
        existing = self.client.select(
            self.TABLE,
            filters={"kind": kind, "record_key": record_key},
            limit=1,
        )
        if existing:
            self.client.update(
                self.TABLE,
                {"payload": payload, "expires_at": expires_text},
                filters={"kind": kind, "record_key": record_key},
            )
        else:
            self.client.insert(self.TABLE, record)

    def delete(self, kind: str, record_key: str) -> None:
        self.client.delete(self.TABLE, filters={"kind": kind, "record_key": record_key})
