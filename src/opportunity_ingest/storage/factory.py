"""Build an OpportunityStore from Settings (sqlite default; sharepoint optional)."""

from __future__ import annotations

from opportunity_ingest.config import Settings
from opportunity_ingest.storage.base import OpportunityStore
from opportunity_ingest.storage.sharepoint_store import SharePointOpportunityStore
from opportunity_ingest.storage.sqlite_store import SqliteOpportunityStore


def build_store(settings: Settings) -> OpportunityStore:
    """Return the configured storage backend.

    * ``sqlite`` (default) → :class:`SqliteOpportunityStore`
    * ``sharepoint`` → :class:`SharePointOpportunityStore` (requires Azure + site/list IDs)
    """
    backend = (settings.storage_backend or "sqlite").strip().lower()
    if backend == "sqlite":
        return SqliteOpportunityStore(settings.resolved_sqlite_path())
    if backend == "sharepoint":
        return SharePointOpportunityStore(settings)
    raise ValueError(f"Unknown STORAGE_BACKEND: {backend!r}")
