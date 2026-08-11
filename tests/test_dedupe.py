"""Backend-agnostic dedupe tests (fake store + SQLite load_existing_keys)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from opportunity_ingest.models import ExistingKeys, OpportunityFields
from opportunity_ingest.storage import (
    SkipDuplicate,
    SqliteOpportunityStore,
    is_duplicate,
    normalize_link,
    register_created,
)
from opportunity_ingest.storage.base import StoreWriteError

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


def _fields(
    opportunity_id: str = "PW-1",
    link: str = "https://canadabuys.canada.ca/en/tender-opportunities/notice/pw-1",
    **overrides: object,
) -> OpportunityFields:
    base: dict[str, object] = dict(
        Title="T",
        OpportunityID=opportunity_id,
        Source="CanadaBuys",
        Buyer=None,
        Link=link,
        PublishedDate=date(2026, 8, 1),
        ClosingDate=None,
        Category=None,
        Description=None,
        KeywordsMatched="",
        RelevanceScore=10,
        Status="New",
        DateAdded=NOW,
        Notes="",
    )
    base.update(overrides)
    return OpportunityFields(**base)  # type: ignore[arg-type]


class FakeStore:
    """Minimal in-memory OpportunityStore for protocol-level dedupe tests."""

    name = "fake"

    def __init__(self) -> None:
        self._by_id: dict[str, OpportunityFields] = {}
        self._by_link: dict[str, OpportunityFields] = {}
        self.create_calls = 0

    def health_check(self) -> None:
        return None

    def load_existing_keys(self) -> ExistingKeys:
        return ExistingKeys(
            opportunity_ids=set(self._by_id.keys()),
            links=set(self._by_link.keys()),
        )

    def create(self, fields: OpportunityFields) -> str:
        self.create_calls += 1
        link_n = normalize_link(fields.Link)
        if fields.OpportunityID in self._by_id or link_n in self._by_link:
            raise SkipDuplicate("duplicate")
        self._by_id[fields.OpportunityID] = fields
        self._by_link[link_n] = fields
        return str(self.create_calls)


def test_is_duplicate_by_opportunity_id():
    keys = ExistingKeys(opportunity_ids={"PW-1"}, links=set())
    assert is_duplicate("PW-1", "https://other.example/x", keys) is True
    assert is_duplicate("PW-2", "https://other.example/x", keys) is False


def test_is_duplicate_by_normalized_link():
    keys = ExistingKeys(
        opportunity_ids=set(),
        links={normalize_link("https://Example.COM/a/")},
    )
    assert is_duplicate("NEW", "  HTTPS://example.com/a  ", keys) is True
    assert is_duplicate("NEW", "https://example.com/b", keys) is False


def test_register_created_updates_keys():
    keys = ExistingKeys.empty()
    register_created(keys, "PW-9", "HTTPS://Ex.COM/z/")
    assert "PW-9" in keys.opportunity_ids
    assert "https://ex.com/z" in keys.links
    assert is_duplicate("PW-9", "https://ex.com/z", keys)


def test_is_duplicate_strips_opportunity_id():
    keys = ExistingKeys(opportunity_ids={"PW-1"}, links=set())
    assert is_duplicate("  PW-1  ", "https://other.example/x", keys) is True
    register_created(keys, "  PW-2  ", "https://example.com/p2")
    assert "PW-2" in keys.opportunity_ids
    assert is_duplicate("PW-2", "https://example.com/other", keys) is True


def test_precheck_skips_create_on_fake_store():
    store = FakeStore()
    store.create(_fields("A", "https://example.com/a"))
    keys = store.load_existing_keys()

    candidates = [
        _fields("A", "https://example.com/other"),  # id dup
        _fields("B", "https://example.com/a/"),  # link dup (normalized)
        _fields("C", "https://example.com/c"),  # new
    ]
    created: list[str] = []
    skipped = 0
    for f in candidates:
        if is_duplicate(f.OpportunityID, f.Link, keys):
            skipped += 1
            continue
        store.create(f)
        register_created(keys, f.OpportunityID, f.Link)
        created.append(f.OpportunityID)

    assert skipped == 2
    assert created == ["C"]
    assert store.create_calls == 2  # first seed + C


def test_intra_run_duplicate_caught_by_register_created():
    store = FakeStore()
    keys = ExistingKeys.empty()
    batch = [
        _fields("X", "https://example.com/x"),
        _fields("X", "https://example.com/x2"),  # same id, different link
    ]
    created = 0
    skipped = 0
    for f in batch:
        if is_duplicate(f.OpportunityID, f.Link, keys):
            skipped += 1
            continue
        store.create(f)
        register_created(keys, f.OpportunityID, f.Link)
        created += 1
    assert created == 1
    assert skipped == 1


def test_sqlite_load_keys_feeds_is_duplicate(tmp_path: Path):
    store = SqliteOpportunityStore(tmp_path / "t.db")
    store.health_check()
    store.create(_fields("SQ-1", "https://canadabuys.canada.ca/en/notice/sq-1/"))
    keys = store.load_existing_keys()
    assert is_duplicate("SQ-1", "https://other", keys)
    assert is_duplicate(
        "OTHER",
        "  HTTPS://canadabuys.canada.ca/en/notice/sq-1  ",
        keys,
    )
    assert not is_duplicate("SQ-2", "https://canadabuys.canada.ca/en/notice/sq-2", keys)


def test_unique_violation_without_precheck_is_skip_duplicate(tmp_path: Path):
    store = SqliteOpportunityStore(tmp_path / "t.db")
    store.create(_fields("Z-1", "https://example.com/z1"))
    with pytest.raises(SkipDuplicate):
        store.create(_fields("Z-1", "https://example.com/z1-other"))


def test_skip_duplicate_is_store_error():
    # Soft skip path: SkipDuplicate is a StoreError (not a hard StoreWriteError).
    from opportunity_ingest.storage.base import StoreError

    assert issubclass(SkipDuplicate, StoreError)
    assert not issubclass(SkipDuplicate, StoreWriteError)
