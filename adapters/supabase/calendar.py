"""Tenant-scoped Google Calendar connections, OAuth states, and event mappings."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from adapters.supabase.client import SupabaseGateway
from planner_platform.context import PlannerContext


@dataclass(frozen=True)
class CalendarConnection:
    user_id: UUID
    workspace_id: UUID
    encrypted_credentials: bytes
    target_calendar_id: str
    status: str
    provider_account_id: str | None = None


@dataclass(frozen=True)
class OAuthState:
    user_id: UUID
    workspace_id: UUID
    redirect_uri: str
    code_verifier: str
    expires_at: datetime


class SupabaseCalendarConnectionRepository:
    def __init__(self, client: SupabaseGateway) -> None:
        self.client = client

    def get(self, user_id: UUID, workspace_id: UUID) -> CalendarConnection | None:
        rows = self.client.select(
            "calendar_connections",
            filters={
                "user_id": str(user_id),
                "workspace_id": str(workspace_id),
                "provider": "google_calendar",
            },
            limit=1,
        )
        return self._from_row(rows[0]) if rows else None

    def save(
        self,
        context: PlannerContext,
        encrypted_credentials: bytes,
        *,
        target_calendar_id: str = "primary",
        provider_account_id: str | None = None,
    ) -> CalendarConnection:
        filters = {
            "user_id": str(context.user_id),
            "workspace_id": str(context.workspace_id),
            "provider": "google_calendar",
        }
        payload = {
            "encrypted_credentials": "\\x" + encrypted_credentials.hex(),
            "target_calendar_id": target_calendar_id,
            "provider_account_id": provider_account_id,
            "status": "active",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        existing = self.client.select("calendar_connections", filters=filters, limit=1)
        rows = (
            self.client.update("calendar_connections", payload, filters=filters)
            if existing
            else self.client.insert("calendar_connections", {**filters, **payload})
        )
        if not rows:
            raise RuntimeError("Google Calendar connection was not persisted")
        return self._from_row(rows[0])

    def set_status(self, context: PlannerContext, status: str) -> None:
        if status not in {"active", "expired", "revoked", "error"}:
            raise ValueError("Invalid calendar connection status")
        self.client.update(
            "calendar_connections",
            {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()},
            filters={
                "user_id": str(context.user_id),
                "workspace_id": str(context.workspace_id),
                "provider": "google_calendar",
            },
        )

    @staticmethod
    def _from_row(row: dict[str, Any]) -> CalendarConnection:
        encoded = row["encrypted_credentials"]
        if isinstance(encoded, str) and encoded.startswith("\\x"):
            encrypted = bytes.fromhex(encoded[2:])
        elif isinstance(encoded, bytes):
            encrypted = encoded
        else:
            raise ValueError("Calendar credentials have an invalid storage format")
        return CalendarConnection(
            user_id=UUID(str(row["user_id"])),
            workspace_id=UUID(str(row["workspace_id"])),
            encrypted_credentials=encrypted,
            target_calendar_id=str(row.get("target_calendar_id") or "primary"),
            status=str(row["status"]),
            provider_account_id=(str(row["provider_account_id"]) if row.get("provider_account_id") else None),
        )


class SupabaseOAuthStateRepository:
    def __init__(self, user_client: SupabaseGateway, service_client: SupabaseGateway) -> None:
        self.user_client = user_client
        self.service_client = service_client

    def create(
        self,
        context: PlannerContext,
        redirect_uri: str,
        code_verifier: str,
        ttl_minutes: int = 10,
    ) -> str:
        state = secrets.token_urlsafe(48)
        self.user_client.insert(
            "oauth_states",
            {
                "user_id": str(context.user_id),
                "workspace_id": str(context.workspace_id),
                "provider": "google_calendar",
                "state_hash": self._hash(state),
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat(),
            },
        )
        return state

    def consume(self, state: str) -> OAuthState:
        # Validating and burning the state is a single atomic call: no read
        # beforehand, and nothing about the row is logged — the payload carries
        # the PKCE code_verifier.
        result = self.service_client.rpc(
            "consume_google_oauth_state",
            {"p_state_hash": self._hash(state)},
        )
        if not result:
            raise ValueError("Google OAuth state is invalid, expired, or already used")
        row = result[0] if isinstance(result, list) else result
        return OAuthState(
            user_id=UUID(str(row["user_id"])),
            workspace_id=UUID(str(row["workspace_id"])),
            redirect_uri=str(row["redirect_uri"]),
            code_verifier=str(row["code_verifier"]),
            expires_at=datetime.fromisoformat(str(row["expires_at"])),
        )

    @staticmethod
    def _hash(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()


class SupabaseExternalLinkRepository:
    def __init__(self, client: SupabaseGateway) -> None:
        self.client = client

    def bind(self, context: PlannerContext) -> "BoundExternalLinkStore":
        return BoundExternalLinkStore(self, context)

    def list(self, context: PlannerContext, *, target_name=None, status=None):
        filters: dict[str, Any] = {
            "user_id": str(context.user_id),
            "workspace_id": str(context.workspace_id),
        }
        if target_name is not None:
            filters["provider"] = target_name
        if status is not None:
            filters["status"] = status
        rows = self.client.select("calendar_event_mappings", filters=filters)
        return [self._public(row) for row in rows]

    def active_for(self, context: PlannerContext, planner_block_id: str):
        rows = self.client.select(
            "calendar_event_mappings",
            filters={
                "user_id": str(context.user_id),
                "workspace_id": str(context.workspace_id),
                "planner_block_id": planner_block_id,
                "status": "active",
            },
            limit=1,
        )
        return self._public(rows[0]) if rows else None

    def upsert(self, context, planner_block_id, target_name, external_id, checksum, *, active_links=None):
        """Create or refresh the active link for a block.

        active_links, when given, is the complete set of active links for this
        workspace keyed by planner_block_id — a caller that already holds it
        saves a SELECT here. A calendar sync does: it loads every active link
        once before the loop, so re-reading one row per block was a network
        round trip for data already in memory, and a sync of a week with a
        creation backlog paid it a hundred times over. Absent from the map
        means no active link, so the "already linked to another target" guard
        still holds; it is only sound because the map covers every provider,
        not just the one being synced.
        """

        active = (
            active_links.get(planner_block_id)
            if active_links is not None
            else self.active_for(context, planner_block_id)
        )
        if active and active["target_name"] != target_name:
            raise ValueError("Planner block already has an active link on another target")
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "provider": target_name,
            "external_id": external_id,
            "checksum": checksum,
            "status": "active",
            "last_synced_at": now,
            "updated_at": now,
        }
        filters = {
            "user_id": str(context.user_id),
            "workspace_id": str(context.workspace_id),
            "planner_block_id": planner_block_id,
        }
        rows = (
            self.client.update("calendar_event_mappings", payload, filters=filters)
            if active
            else self.client.insert(
                "calendar_event_mappings",
                {**filters, **payload, "published_at": now},
            )
        )
        if not rows:
            raise RuntimeError("Calendar event mapping was not persisted")
        return self._public(rows[0])

    def upsert_many(self, context, records, *, active_links=None):
        """Write many links, sending every new one in a single insert.

        A first sync of a week is all new links, and one insert per block meant
        one network round trip per block. PostgREST takes a list, so they go
        together. Links that already exist still need a row-specific update
        each — there is no single statement for "set a different value per
        row" — but on a settled calendar almost nothing is left to update,
        because unchanged links are dropped before they reach here.

        Rows that fail are reported, not raised: one bad link must not cost
        the rest of the pass its mapping.
        """

        if not records:
            return {"written": [], "errors": {}}

        now = datetime.now(timezone.utc).isoformat()
        base = {
            "user_id": str(context.user_id),
            "workspace_id": str(context.workspace_id),
        }
        written: list[str] = []
        errors: dict[str, str] = {}
        fresh: list[dict[str, Any]] = []

        for record in records:
            block_id = str(record["planner_block_id"])
            target_name = record["target_name"]
            active = (
                active_links.get(block_id)
                if active_links is not None
                else self.active_for(context, block_id)
            )
            if active and active["target_name"] != target_name:
                errors[block_id] = "Planner block already has an active link on another target"
                continue
            payload = {
                "provider": target_name,
                "external_id": record["external_id"],
                "checksum": record["checksum"],
                "status": "active",
                "last_synced_at": now,
                "updated_at": now,
            }
            if active:
                try:
                    self.client.update(
                        "calendar_event_mappings",
                        payload,
                        filters={**base, "planner_block_id": block_id},
                    )
                    written.append(block_id)
                except Exception as error:  # noqa: BLE001 - one row must not sink the pass
                    errors[block_id] = str(error)
            else:
                fresh.append({**base, "planner_block_id": block_id, **payload, "published_at": now})

        if fresh:
            try:
                self.client.insert("calendar_event_mappings", fresh)
                written.extend(str(row["planner_block_id"]) for row in fresh)
            except Exception as error:  # noqa: BLE001
                for row in fresh:
                    errors[str(row["planner_block_id"])] = str(error)

        return {"written": written, "errors": errors}

    def deactivate(self, context, planner_block_id, target_name):
        self.client.update(
            "calendar_event_mappings",
            {"status": "inactive", "updated_at": datetime.now(timezone.utc).isoformat()},
            filters={
                "user_id": str(context.user_id),
                "workspace_id": str(context.workspace_id),
                "planner_block_id": planner_block_id,
                "provider": target_name,
                "status": "active",
            },
        )

    def remove(self, context, planner_block_id, target_name):
        self.client.delete(
            "calendar_event_mappings",
            filters={
                "user_id": str(context.user_id),
                "workspace_id": str(context.workspace_id),
                "planner_block_id": planner_block_id,
                "provider": target_name,
            },
        )

    @staticmethod
    def _public(row):
        return {
            "planner_block_id": str(row["planner_block_id"]),
            "target_name": str(row["provider"]),
            "external_id": str(row["external_id"]),
            "status": str(row["status"]),
            "checksum": str(row["checksum"]),
            "published_at": str(row.get("published_at", "")),
            "last_synced_at": str(row.get("last_synced_at", "")),
        }


class BoundExternalLinkStore:
    def __init__(self, repository: SupabaseExternalLinkRepository, context: PlannerContext) -> None:
        self.repository = repository
        self.context = context

    def list(self, *, target_name=None, status=None):
        return self.repository.list(self.context, target_name=target_name, status=status)

    def active_for(self, planner_block_id):
        return self.repository.active_for(self.context, planner_block_id)

    def upsert(self, planner_block_id, target_name, external_id, checksum, *, active_links=None):
        return self.repository.upsert(
            self.context,
            planner_block_id,
            target_name,
            external_id,
            checksum,
            active_links=active_links,
        )

    def upsert_many(self, records, *, active_links=None):
        return self.repository.upsert_many(self.context, records, active_links=active_links)

    def deactivate(self, planner_block_id, target_name):
        return self.repository.deactivate(self.context, planner_block_id, target_name)

    def remove(self, planner_block_id, target_name):
        return self.repository.remove(self.context, planner_block_id, target_name)

    def retire_target(self, target_name):
        return 0
