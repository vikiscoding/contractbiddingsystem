"""OpportunityStore protocol, link normalization, and dedupe helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from opportunity_ingest.models import ExistingKeys, OpportunityFields


class StoreError(Exception):
    """Base class for storage backend failures."""


class StoreWriteError(StoreError):
    """Raised when a create (or other write) fails after any backend retries."""


class SkipDuplicate(StoreError):
    """Raised when create hits a unique constraint (OpportunityID or Link).

    Treated as a soft skip (rare if ``load_existing_keys`` pre-check is correct).
    """


def normalize_link(link: str) -> str:
    """Normalize a notice URL for dedupe: strip, lower-case, strip trailing slash."""
    s = (link or "").strip().lower()
    return s.rstrip("/")


def is_duplicate(opportunity_id: str, link: str, keys: ExistingKeys) -> bool:
    """True if OpportunityID or normalized Link is already present in ``keys``."""
    if opportunity_id in keys.opportunity_ids:
        return True
    return normalize_link(link) in keys.links


def register_created(keys: ExistingKeys, opportunity_id: str, link: str) -> None:
    """Add keys after a successful create (avoids intra-run duplicates)."""
    keys.opportunity_ids.add(opportunity_id)
    keys.links.add(normalize_link(link))


@dataclass(slots=True)
class AttemptBudget:
    """Create-attempt budget for ``MAX_CREATE`` (normative: attempts, not only adds).

    ``max_create``:
      - ``N >= 1``: at most N create attempts (success or failure each count)
      - ``0``: unlimited
    """

    max_create: int
    used: int = 0

    def __post_init__(self) -> None:
        if self.max_create < 0:
            raise ValueError("max_create must be >= 0 (0 = unlimited)")

    @property
    def unlimited(self) -> bool:
        return self.max_create == 0

    def can_attempt(self) -> bool:
        """Return True if another create attempt is allowed."""
        if self.unlimited:
            return True
        return self.used < self.max_create

    def consume(self) -> bool:
        """If an attempt is allowed, increment used and return True; else False."""
        if not self.can_attempt():
            return False
        self.used += 1
        return True


@runtime_checkable
class OpportunityStore(Protocol):
    """Persistence for Contract Opportunities logical records."""

    name: str  # "sqlite" | "sharepoint"

    def health_check(self) -> None:
        """Raise if backend is not usable (missing perms, bad path, Graph 403, etc.)."""
        ...

    def load_existing_keys(self) -> ExistingKeys:
        """Return sets of OpportunityID and normalized Link for dedupe."""
        ...

    def create(self, fields: OpportunityFields) -> str:
        """Insert one new opportunity; return backend-native id (rowid or list item id).

        Raise ``SkipDuplicate`` on unique violation, ``StoreWriteError`` on other
        failures after retries. Must not update existing rows (create-only).
        """
        ...
