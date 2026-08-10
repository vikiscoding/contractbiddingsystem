"""SQLite OpportunityStore: create-only writes with unique OpportunityID/Link."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from opportunity_ingest.models import ExistingKeys, OpportunityFields
from opportunity_ingest.storage.base import (
    SkipDuplicate,
    StoreError,
    StoreWriteError,
    normalize_link,
)

UTC = timezone.utc

DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS contract_opportunities (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      Title TEXT NOT NULL,
      OpportunityID TEXT NOT NULL,
      Source TEXT NOT NULL DEFAULT 'CanadaBuys',
      Buyer TEXT,
      Link TEXT NOT NULL,
      PublishedDate TEXT,
      ClosingDate TEXT,
      Category TEXT,
      Description TEXT,
      KeywordsMatched TEXT,
      RelevanceScore INTEGER,
      Status TEXT NOT NULL DEFAULT 'New',
      DateAdded TEXT NOT NULL,
      Notes TEXT,
      created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_opportunity_id
      ON contract_opportunities (OpportunityID)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_link
      ON contract_opportunities (Link)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_status ON contract_opportunities (Status)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_closing ON contract_opportunities (ClosingDate)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_score ON contract_opportunities (RelevanceScore)
    """,
)

_INSERT_SQL = """
INSERT INTO contract_opportunities (
  Title, OpportunityID, Source, Buyer, Link,
  PublishedDate, ClosingDate, Category, Description,
  KeywordsMatched, RelevanceScore, Status, DateAdded, Notes
) VALUES (
  ?, ?, ?, ?, ?,
  ?, ?, ?, ?,
  ?, ?, ?, ?, ?
)
"""


def _fmt_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _fmt_datetime_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    # Stable ISO UTC with Z suffix (seconds precision is enough for DateAdded/Closing).
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class SqliteOpportunityStore:
    """Local SQLite backend for Contract Opportunities (day-1 default)."""

    name: str = "sqlite"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        # Enforce foreign keys / integrity; unique indexes raise IntegrityError.
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def ensure_schema(self) -> None:
        """Create table and indexes if missing."""
        try:
            with self._connect() as conn:
                for stmt in DDL_STATEMENTS:
                    conn.execute(stmt)
                conn.commit()
        except sqlite3.Error as exc:
            raise StoreError(f"SQLite schema ensure failed at {self.path}: {exc}") from exc

    def health_check(self) -> None:
        """Open the DB and ensure schema; raise StoreError if unusable."""
        self.ensure_schema()
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1 FROM contract_opportunities LIMIT 1")
        except sqlite3.Error as exc:
            raise StoreError(f"SQLite health_check failed at {self.path}: {exc}") from exc

    def load_existing_keys(self) -> ExistingKeys:
        """Return OpportunityID set and normalized Link set for dedupe."""
        self.ensure_schema()
        ids: set[str] = set()
        links: set[str] = set()
        try:
            with self._connect() as conn:
                for row in conn.execute(
                    "SELECT OpportunityID, Link FROM contract_opportunities"
                ):
                    oid = row["OpportunityID"]
                    if oid is not None and str(oid).strip():
                        ids.add(str(oid))
                    link = row["Link"]
                    if link is not None:
                        links.add(normalize_link(str(link)))
        except sqlite3.Error as exc:
            raise StoreError(f"SQLite load_existing_keys failed at {self.path}: {exc}") from exc
        return ExistingKeys(opportunity_ids=ids, links=links)

    def create(self, fields: OpportunityFields) -> str:
        """Insert one opportunity; return string row id. Create-only (no updates).

        Link is stored in normalized form for unique-index dedupe.
        Unique violations raise ``SkipDuplicate``; other DB errors raise
        ``StoreWriteError``.
        """
        self.ensure_schema()
        link_norm = normalize_link(fields.Link)
        if not fields.OpportunityID or not str(fields.OpportunityID).strip():
            raise StoreWriteError("OpportunityID is required for create")
        if not link_norm:
            raise StoreWriteError(
                f"Link is required for OpportunityID={fields.OpportunityID!r}"
            )

        values = (
            fields.Title,
            fields.OpportunityID,
            fields.Source or "CanadaBuys",
            fields.Buyer,
            link_norm,
            _fmt_date(fields.PublishedDate),
            _fmt_datetime_utc(fields.ClosingDate),
            fields.Category,
            fields.Description,
            fields.KeywordsMatched,
            int(fields.RelevanceScore),
            fields.Status or "New",
            _fmt_datetime_utc(fields.DateAdded) or _fmt_datetime_utc(datetime.now(UTC)),
            fields.Notes if fields.Notes is not None else "",
        )

        try:
            with self._connect() as conn:
                cur = conn.execute(_INSERT_SQL, values)
                conn.commit()
                row_id = cur.lastrowid
        except sqlite3.IntegrityError as exc:
            # Unique on OpportunityID or Link — treat consistently as skip-duplicate.
            raise SkipDuplicate(
                f"Duplicate OpportunityID or Link for "
                f"OpportunityID={fields.OpportunityID!r}: {exc}"
            ) from exc
        except sqlite3.Error as exc:
            raise StoreWriteError(
                f"SQLite create failed for OpportunityID={fields.OpportunityID!r}: {exc}"
            ) from exc

        if row_id is None:
            raise StoreWriteError(
                f"SQLite create returned no row id for OpportunityID={fields.OpportunityID!r}"
            )
        return str(row_id)
