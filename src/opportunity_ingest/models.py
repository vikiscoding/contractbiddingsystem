"""Normalized data models for CanadaBuys open tender ingestion."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class TenderRecord:
    """One open-tender row after bilingual header resolution and EN/FR coalesce.

    ``opportunity_id`` is derived: reference_number if set, else solicitation_number.
    Link is never truncated. Closing date, when present, is timezone-aware UTC.
    Title is already EN-else-FR coalesced (same for buyer, description, link).
    """

    title: str
    reference_number: str | None
    solicitation_number: str | None
    publication_date: date | None
    closing_date: datetime | None
    buyer: str | None
    link: str
    description: str | None
    gsin: str | None
    gsin_desc: str | None
    procurement_category: str | None
    status_text: str | None

    @property
    def opportunity_id(self) -> str:
        """CanadaBuys-native key: reference number, else solicitation number."""
        if self.reference_number:
            return self.reference_number
        if self.solicitation_number:
            return self.solicitation_number
        return ""


@dataclass(frozen=True, slots=True)
class OpportunityFields:
    """Logical Contract Opportunities schema (SQLite + SharePoint).

    Field names match the storage/list columns. Link is full URL (never truncated).
    """

    Title: str
    OpportunityID: str
    Source: str
    Buyer: str | None
    Link: str
    PublishedDate: date | None
    ClosingDate: datetime | None
    Category: str | None
    Description: str | None
    KeywordsMatched: str
    RelevanceScore: int
    Status: str
    DateAdded: datetime
    Notes: str

    def as_dict(self) -> dict[str, Any]:
        """Plain dict with logical schema keys (for create adapters / tests)."""
        return asdict(self)


@dataclass(slots=True)
class ExistingKeys:
    """In-memory dedupe keys loaded from an OpportunityStore.

    ``links`` must contain **normalized** links (strip, lower, trailing slash).
    """

    opportunity_ids: set[str]
    links: set[str]

    @classmethod
    def empty(cls) -> ExistingKeys:
        """Return empty key sets (useful for dry-run without ``--with-existing``)."""
        return cls(opportunity_ids=set(), links=set())
