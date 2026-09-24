"""Block → external event mappings.

The property under test is how many reads a sync costs. Calendar sync loads
every active link once up front and then writes one per block; if the store
re-reads a block's link on each write, a week with a creation backlog spends a
hundred sequential round trips looking up rows it is already holding, and the
sync takes minutes instead of seconds.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from adapters.supabase.calendar import SupabaseExternalLinkRepository
from planner_platform.context import PlannerContext

USER_ID = uuid4()
WORKSPACE_ID = uuid4()


class CountingGateway:
    """Records every read so a test can assert one did not happen."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.selects: list[dict] = []
        self.inserts: list[dict] = []
        self.updates: list[dict] = []

    def select(self, table, *, filters, columns="*", limit=None):
        self.selects.append(dict(filters))
        matched = [
            row for row in self.rows
            if all(str(row.get(key)) == str(value) for key, value in filters.items())
        ]
        return matched[:limit] if limit else matched

    def insert(self, table, payload):
        row = {"id": str(uuid4()), **dict(payload)}
        self.inserts.append(row)
        self.rows.append(row)
        return [row]

    def update(self, table, payload, *, filters):
        self.updates.append(dict(payload))
        for row in self.rows:
            if all(str(row.get(key)) == str(value) for key, value in filters.items()):
                row.update(payload)
                return [row]
        return []


def _context():
    return PlannerContext(
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        operation_id=uuid4(),
        workbook_path=Path("/tmp/planner.xlsx"),
        timezone="Asia/Kolkata",
        execution_target="google_calendar",
        source_revision=0,
    )


def _row(block_id, *, provider="google_calendar", external_id="g-1", checksum="old"):
    return {
        "user_id": str(USER_ID),
        "workspace_id": str(WORKSPACE_ID),
        "planner_block_id": block_id,
        "provider": provider,
        "external_id": external_id,
        "checksum": checksum,
        "status": "active",
        "published_at": "",
        "last_synced_at": "",
    }


def test_a_caller_holding_the_links_is_not_charged_a_lookup():
    gateway = CountingGateway([_row("block-1")])
    repository = SupabaseExternalLinkRepository(gateway)
    links = {"block-1": repository._public(_row("block-1"))}

    repository.upsert(
        _context(), "block-1", "google_calendar", "g-1", "new", active_links=links
    )

    assert gateway.selects == [], "the link was already in hand and read again anyway"
    assert gateway.updates, "an existing link must still be updated, not inserted"


def test_without_the_links_the_store_still_looks_the_block_up():
    """The saving is an optimisation, not a new requirement on callers."""
    gateway = CountingGateway([_row("block-1")])
    repository = SupabaseExternalLinkRepository(gateway)

    repository.upsert(_context(), "block-1", "google_calendar", "g-1", "new")

    assert len(gateway.selects) == 1
    assert gateway.updates


def test_a_block_missing_from_the_links_is_inserted():
    gateway = CountingGateway()
    repository = SupabaseExternalLinkRepository(gateway)

    repository.upsert(
        _context(), "block-1", "google_calendar", "g-1", "sum", active_links={}
    )

    assert gateway.selects == []
    assert len(gateway.inserts) == 1
    assert gateway.inserts[0]["planner_block_id"] == "block-1"


def test_the_other_target_guard_survives_the_shortcut():
    """A block holds one active link. Skipping the read must not skip this.

    It only holds because the map covers every provider — which is why
    _active_links_by_block loads them all rather than just the one being synced.
    """
    gateway = CountingGateway([_row("block-1", provider="apple_calendar")])
    repository = SupabaseExternalLinkRepository(gateway)
    links = {
        "block-1": repository._public(_row("block-1", provider="apple_calendar"))
    }

    with pytest.raises(ValueError):
        repository.upsert(
            _context(), "block-1", "google_calendar", "g-1", "sum", active_links=links
        )

    assert gateway.inserts == [], "a second active link was written for one block"
    assert gateway.updates == []
