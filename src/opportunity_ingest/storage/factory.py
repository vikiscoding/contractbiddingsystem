"""Build an OpportunityStore from Settings (sqlite default)."""

from __future__ import annotations

from opportunity_ingest.config import Settings
from opportunity_ingest.storage.base import OpportunityStore
from opportunity_ingest.storage.sqlite_store import SqliteOpportunityStore


def build_store(settings: Settings) -> OpportunityStore:
    """Return the configured storage backend.

    * ``sqlite`` (default) → :class:`SqliteOpportunityStore`
    * ``sharepoint`` → not implemented in this PR (raises ``NotImplementedError``)
    """
    backend = (settings.storage_backend or "sqlite").strip().lower()
    if backend == "sqlite":
        return SqliteOpportunityStore(settings.resolved_sqlite_path())
    if backend == "sharepoint":
        raise NotImplementedError(
            "SharePoint OpportunityStore is not implemented yet "
            "(see PR 5). Use STORAGE_BACKEND=sqlite for day-1."
        )
    raise ValueError(f"Unknown STORAGE_BACKEND: {backend!r}")
