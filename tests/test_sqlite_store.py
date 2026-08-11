"""Tests for SQLite OpportunityStore: schema, create, keys, uniqueness."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from opportunity_ingest.config import Settings
from opportunity_ingest.models import OpportunityFields
from opportunity_ingest.storage import (
    OpportunityStore,
    SkipDuplicate,
    SqliteOpportunityStore,
    StoreWriteError,
    build_store,
    normalize_link,
)
from opportunity_ingest.storage.sqlite_store import _is_unique_constraint

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 15, 30, 0, tzinfo=UTC)


def _fields(**overrides: object) -> OpportunityFields:
    base: dict[str, object] = dict(
        Title="Cloud RPA services",
        OpportunityID="PW-2026-001",
        Source="CanadaBuys",
        Buyer="PSPC",
        Link="https://canadabuys.canada.ca/en/tender-opportunities/notice/pw-2026-001",
        PublishedDate=date(2026, 8, 8),
        ClosingDate=datetime(2026, 8, 20, 14, 0, 0, tzinfo=UTC),
        Category="D302A",
        Description="Azure and RPA",
        KeywordsMatched="azure, rpa",
        RelevanceScore=42,
        Status="New",
        DateAdded=NOW,
        Notes="",
    )
    base.update(overrides)
    return OpportunityFields(**base)  # type: ignore[arg-type]


@pytest.fixture
def store(tmp_path: Path) -> SqliteOpportunityStore:
    db = tmp_path / "contract_opportunities.db"
    s = SqliteOpportunityStore(db)
    s.health_check()
    return s


def test_normalize_link_strip_lower_trailing_slash():
    assert (
        normalize_link("  HTTPS://Example.COM/Path/  ")
        == "https://example.com/path"
    )
    assert normalize_link("https://example.com") == "https://example.com"
    assert normalize_link("") == ""


def test_health_check_creates_schema_and_indexes(store: SqliteOpportunityStore):
    with sqlite3.connect(store.path) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "contract_opportunities" in tables
        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "ux_opportunity_id" in indexes
        assert "ux_link" in indexes
        assert "ix_status" in indexes
        assert "ix_closing" in indexes
        assert "ix_score" in indexes


def test_create_and_load_existing_keys(store: SqliteOpportunityStore):
    row_id = store.create(_fields())
    assert row_id.isdigit()

    keys = store.load_existing_keys()
    assert "PW-2026-001" in keys.opportunity_ids
    expected_link = normalize_link(
        "https://canadabuys.canada.ca/en/tender-opportunities/notice/pw-2026-001"
    )
    assert expected_link in keys.links


def test_create_stores_normalized_link(store: SqliteOpportunityStore):
    mixed = "  HTTPS://CanadaBuys.Canada.CA/en/Notice/ABC/  "
    store.create(_fields(OpportunityID="ABC-1", Link=mixed))
    keys = store.load_existing_keys()
    assert normalize_link(mixed) in keys.links
    # Stored form matches normalized form (unique index on Link).
    with sqlite3.connect(store.path) as conn:
        link = conn.execute(
            "SELECT Link FROM contract_opportunities WHERE OpportunityID=?",
            ("ABC-1",),
        ).fetchone()[0]
    assert link == normalize_link(mixed)


def test_unique_opportunity_id_raises_skip_duplicate(store: SqliteOpportunityStore):
    store.create(_fields(OpportunityID="DUP-ID", Link="https://example.com/a"))
    with pytest.raises(SkipDuplicate):
        store.create(
            _fields(
                OpportunityID="DUP-ID",
                Link="https://example.com/different",
            )
        )


def test_unique_link_raises_skip_duplicate(store: SqliteOpportunityStore):
    store.create(_fields(OpportunityID="ID-1", Link="https://example.com/same/"))
    with pytest.raises(SkipDuplicate):
        store.create(
            _fields(
                OpportunityID="ID-2",
                Link="  HTTPS://Example.COM/same  ",
            )
        )


def test_create_only_no_update_on_duplicate(store: SqliteOpportunityStore):
    store.create(_fields(Title="Original", OpportunityID="U-1", Link="https://e.com/u1"))
    with pytest.raises(SkipDuplicate):
        store.create(
            _fields(Title="Changed", OpportunityID="U-1", Link="https://e.com/u1")
        )
    with sqlite3.connect(store.path) as conn:
        title = conn.execute(
            "SELECT Title FROM contract_opportunities WHERE OpportunityID=?",
            ("U-1",),
        ).fetchone()[0]
    assert title == "Original"


def test_load_existing_keys_empty(store: SqliteOpportunityStore):
    keys = store.load_existing_keys()
    assert keys.opportunity_ids == set()
    assert keys.links == set()


def test_implements_protocol(store: SqliteOpportunityStore):
    assert isinstance(store, OpportunityStore)
    assert store.name == "sqlite"


def test_factory_sqlite_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("SQLITE_PATH", raising=False)
    settings = Settings(
        _env_file=None,
        storage_backend="sqlite",
        data_dir=tmp_path,
        sqlite_path=tmp_path / "db.sqlite",
    )
    built = build_store(settings)
    assert isinstance(built, SqliteOpportunityStore)
    assert built.path == tmp_path / "db.sqlite"
    built.health_check()


def test_factory_sharepoint_not_implemented(monkeypatch: pytest.MonkeyPatch):
    settings = Settings(_env_file=None, storage_backend="sharepoint")
    with pytest.raises(NotImplementedError, match="SharePoint"):
        build_store(settings)


def test_factory_unknown_backend():
    settings = Settings(_env_file=None, storage_backend="sheets")
    with pytest.raises(ValueError, match="Unknown STORAGE_BACKEND"):
        build_store(settings)


def test_date_fields_serialized_as_text(store: SqliteOpportunityStore):
    store.create(_fields())
    with sqlite3.connect(store.path) as conn:
        row = conn.execute(
            "SELECT PublishedDate, ClosingDate, DateAdded FROM contract_opportunities"
        ).fetchone()
    assert row[0] == "2026-08-08"
    assert row[1] == "2026-08-20T14:00:00Z"
    assert row[2] == "2026-08-10T15:30:00Z"


def test_opportunity_id_stripped_on_store(store: SqliteOpportunityStore):
    store.create(_fields(OpportunityID="  PW-PADDED  ", Link="https://example.com/pad"))
    keys = store.load_existing_keys()
    assert "PW-PADDED" in keys.opportunity_ids
    assert "  PW-PADDED  " not in keys.opportunity_ids
    with sqlite3.connect(store.path) as conn:
        oid = conn.execute(
            "SELECT OpportunityID FROM contract_opportunities WHERE Link=?",
            (normalize_link("https://example.com/pad"),),
        ).fetchone()[0]
    assert oid == "PW-PADDED"


def test_empty_title_raises_store_write_error(store: SqliteOpportunityStore):
    with pytest.raises(StoreWriteError, match="Title"):
        store.create(_fields(Title=""))
    with pytest.raises(StoreWriteError, match="Title"):
        store.create(_fields(Title="   \t  "))


def test_is_unique_constraint_classifies_messages():
    assert _is_unique_constraint(
        sqlite3.IntegrityError(
            "UNIQUE constraint failed: contract_opportunities.OpportunityID"
        )
    )
    assert _is_unique_constraint(
        sqlite3.IntegrityError("UNIQUE constraint failed: contract_opportunities.Link")
    )
    assert not _is_unique_constraint(
        sqlite3.IntegrityError(
            "NOT NULL constraint failed: contract_opportunities.Title"
        )
    )
    assert not _is_unique_constraint(
        sqlite3.IntegrityError("CHECK constraint failed: RelevanceScore")
    )


def test_non_unique_integrity_error_is_store_write_error(
    store: SqliteOpportunityStore, monkeypatch: pytest.MonkeyPatch
):
    """Regression: NOT NULL IntegrityError must not become SkipDuplicate."""
    from unittest.mock import MagicMock

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None
    mock_conn.execute.side_effect = sqlite3.IntegrityError(
        "NOT NULL constraint failed: contract_opportunities.Title"
    )
    # Schema already ensured by fixture; only the insert connect is patched.
    monkeypatch.setattr(store, "_connect", lambda: mock_conn)
    with pytest.raises(StoreWriteError, match="integrity error") as exc_info:
        store.create(_fields(OpportunityID="IE-1", Link="https://example.com/ie-1"))
    assert not isinstance(exc_info.value, SkipDuplicate)


def test_ensure_schema_runs_once(store: SqliteOpportunityStore, monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}
    real = store._connect

    def counting_connect() -> sqlite3.Connection:
        calls["n"] += 1
        return real()

    # Schema already ready from fixture health_check; further ensure_schema is no-op.
    monkeypatch.setattr(store, "_connect", counting_connect)
    store.ensure_schema()
    store.ensure_schema()
    assert calls["n"] == 0
    assert store._schema_ready is True
