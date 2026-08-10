"""Create-attempt budget (MAX_CREATE) unit tests — attempts include failures."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from opportunity_ingest.models import ExistingKeys, OpportunityFields
from opportunity_ingest.storage import (
    AttemptBudget,
    SkipDuplicate,
    StoreWriteError,
    is_duplicate,
    normalize_link,
    register_created,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


def _fields(opportunity_id: str, link: str | None = None) -> OpportunityFields:
    return OpportunityFields(
        Title="T",
        OpportunityID=opportunity_id,
        Source="CanadaBuys",
        Buyer=None,
        Link=link or f"https://example.com/{opportunity_id}",
        PublishedDate=date(2026, 8, 1),
        ClosingDate=None,
        Category=None,
        Description=None,
        KeywordsMatched="",
        RelevanceScore=1,
        Status="New",
        DateAdded=NOW,
        Notes="",
    )


class ControllableFakeStore:
    """Fake store that can fail creates to verify attempts still consume budget."""

    name = "fake"

    def __init__(self, *, fail_ids: set[str] | None = None) -> None:
        self.fail_ids = fail_ids or set()
        self._ids: set[str] = set()
        self._links: set[str] = set()
        self.attempts: list[str] = []

    def health_check(self) -> None:
        return None

    def load_existing_keys(self) -> ExistingKeys:
        return ExistingKeys(opportunity_ids=set(self._ids), links=set(self._links))

    def create(self, fields: OpportunityFields) -> str:
        self.attempts.append(fields.OpportunityID)
        link_n = normalize_link(fields.Link)
        if fields.OpportunityID in self._ids or link_n in self._links:
            raise SkipDuplicate("dup")
        if fields.OpportunityID in self.fail_ids:
            raise StoreWriteError(f"forced fail for {fields.OpportunityID}")
        self._ids.add(fields.OpportunityID)
        self._links.add(link_n)
        return fields.OpportunityID


def run_with_budget(
    candidates: list[OpportunityFields],
    store: ControllableFakeStore,
    keys: ExistingKeys,
    max_create: int,
) -> dict[str, int]:
    """Minimal create loop mirroring pipeline MAX_CREATE semantics.

    Each candidate that reaches store.create counts as one attempt whether
    success or failure. Pre-check duplicates do not consume budget.
    Unattempted new candidates → skipped_max_create.
    """
    budget = AttemptBudget(max_create=max_create)
    added = 0
    errors = 0
    skipped_dup = 0
    skipped_max = 0

    for fields in candidates:
        if is_duplicate(fields.OpportunityID, fields.Link, keys):
            skipped_dup += 1
            continue
        if not budget.can_attempt():
            skipped_max += 1
            continue
        # Consume one attempt for this create (success or fail).
        assert budget.consume()
        try:
            store.create(fields)
        except SkipDuplicate:
            # Race / missed pre-check — still an attempt; do not add keys.
            skipped_dup += 1
        except StoreWriteError:
            errors += 1
        else:
            register_created(keys, fields.OpportunityID, fields.Link)
            added += 1

    return {
        "added": added,
        "errors": errors,
        "skipped_duplicate": skipped_dup,
        "skipped_max_create": skipped_max,
        "attempts": budget.used,
        "store_attempts": len(store.attempts),
    }


def test_attempt_budget_basic_can_attempt_and_consume():
    b = AttemptBudget(max_create=2)
    assert b.can_attempt()
    assert b.consume() is True
    assert b.used == 1
    assert b.consume() is True
    assert b.used == 2
    assert b.can_attempt() is False
    assert b.consume() is False
    assert b.used == 2


def test_attempt_budget_zero_is_unlimited():
    b = AttemptBudget(max_create=0)
    assert b.unlimited
    for _ in range(100):
        assert b.consume() is True
    assert b.used == 100


def test_attempt_budget_rejects_negative():
    with pytest.raises(ValueError, match="max_create"):
        AttemptBudget(max_create=-1)


def test_max_create_caps_attempts_not_only_adds():
    # 5 new candidates, budget 3 → 3 attempts, 2 skipped_max_create
    store = ControllableFakeStore()
    keys = ExistingKeys.empty()
    candidates = [_fields(f"N{i}") for i in range(5)]
    stats = run_with_budget(candidates, store, keys, max_create=3)
    assert stats["attempts"] == 3
    assert stats["added"] == 3
    assert stats["skipped_max_create"] == 2
    assert stats["store_attempts"] == 3


def test_failed_create_still_consumes_attempt():
    # fail_ids causes StoreWriteError; those still count toward MAX_CREATE.
    store = ControllableFakeStore(fail_ids={"F0", "F1"})
    keys = ExistingKeys.empty()
    candidates = [_fields("F0"), _fields("F1"), _fields("OK"), _fields("LATER")]
    stats = run_with_budget(candidates, store, keys, max_create=3)
    assert stats["attempts"] == 3
    assert stats["errors"] == 2
    assert stats["added"] == 1
    assert stats["skipped_max_create"] == 1
    assert store.attempts == ["F0", "F1", "OK"]


def test_duplicates_do_not_consume_budget():
    store = ControllableFakeStore()
    keys = ExistingKeys(opportunity_ids={"EXIST"}, links=set())
    candidates = [
        _fields("EXIST"),  # pre-check skip
        _fields("NEW1"),
        _fields("NEW2"),
    ]
    stats = run_with_budget(candidates, store, keys, max_create=1)
    assert stats["skipped_duplicate"] == 1
    assert stats["attempts"] == 1
    assert stats["added"] == 1
    assert stats["skipped_max_create"] == 1


def test_unlimited_budget_processes_all():
    store = ControllableFakeStore()
    keys = ExistingKeys.empty()
    candidates = [_fields(f"U{i}") for i in range(10)]
    stats = run_with_budget(candidates, store, keys, max_create=0)
    assert stats["added"] == 10
    assert stats["skipped_max_create"] == 0
    assert stats["attempts"] == 10
