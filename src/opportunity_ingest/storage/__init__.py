"""Pluggable opportunity storage backends (SQLite default; SharePoint optional)."""

from opportunity_ingest.storage.base import (
    AttemptBudget,
    OpportunityStore,
    SkipDuplicate,
    StoreError,
    StoreWriteError,
    is_duplicate,
    normalize_link,
    register_created,
)
from opportunity_ingest.storage.factory import build_store
from opportunity_ingest.storage.sharepoint_store import SharePointOpportunityStore
from opportunity_ingest.storage.sqlite_store import SqliteOpportunityStore

__all__ = [
    "AttemptBudget",
    "OpportunityStore",
    "SharePointOpportunityStore",
    "SkipDuplicate",
    "SqliteOpportunityStore",
    "StoreError",
    "StoreWriteError",
    "build_store",
    "is_duplicate",
    "normalize_link",
    "register_created",
]
