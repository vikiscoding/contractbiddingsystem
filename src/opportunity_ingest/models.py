"""Normalized data models for CanadaBuys open tender ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class TenderRecord:
    """One open-tender row after bilingual header resolution and EN/FR coalesce.

    ``opportunity_id`` is derived: reference_number if set, else solicitation_number.
    Link is never truncated. Closing date, when present, is timezone-aware UTC.
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
