"""Tests for UTC RelevanceScore rule engine."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from opportunity_ingest.filter_keywords import KeywordMatchResult
from opportunity_ingest.models import TenderRecord
from opportunity_ingest.score import category_boost, compute_score

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


def _match(
    terms: list[str],
    groups: list[str],
    weights: dict[str, int],
) -> KeywordMatchResult:
    return KeywordMatchResult(
        matched=bool(terms),
        terms=tuple(terms),
        groups=tuple(groups),
        weights=weights,
    )


def _tender(
    *,
    closing: datetime | None = None,
    published: date | None = None,
    procurement_category: str | None = None,
) -> TenderRecord:
    return TenderRecord(
        title="t",
        reference_number="R1",
        solicitation_number=None,
        publication_date=published,
        closing_date=closing,
        buyer=None,
        link="https://example.com/x",
        description=None,
        gsin=None,
        gsin_desc=None,
        procurement_category=procurement_category,
        status_text=None,
    )


def test_sum_unique_term_weights():
    match = _match(
        ["azure", "copilot"],
        ["microsoft_cloud"],
        {"azure": 14, "copilot": 20},
    )
    score = compute_score(_tender(), match, {}, now=NOW)
    assert score == 34  # 14+20; single group → no multi-group bonus


def test_multi_group_bonus():
    # 2 groups → min(15, 3*(2-1)) = 3
    match = _match(
        ["rpa", "itsm"],
        ["automation_process", "itsm_servicenow"],
        {"rpa": 14, "itsm": 16},
    )
    score = compute_score(_tender(), match, {}, now=NOW)
    assert score == 14 + 16 + 3


def test_multi_group_bonus_caps_at_15():
    # 7 groups → 3*6 = 18 → capped at 15
    groups = [f"g{i}" for i in range(7)]
    terms = [f"t{i}" for i in range(7)]
    weights = {t: 1 for t in terms}
    match = _match(terms, groups, weights)
    score = compute_score(_tender(), match, {}, now=NOW)
    assert score == 7 + 15


def test_category_boost_exact_and_wildcard():
    assert category_boost("SRV", {"SRV": 5, "*SVRTGD": 3}) == 5
    assert category_boost("FOO-SVRTGD-BAR", {"*SVRTGD": 3, "SVRTGD": 3}) == 3
    assert category_boost("Goods", {"SRV": 5, "*SRV": 5}) == 0
    assert category_boost(None, {"SRV": 5}) == 0
    # Wildcard case-insensitive
    assert category_boost("x-srv-y", {"*SRV": 5}) == 5


def test_category_boost_added_to_score():
    match = _match(["msp"], ["managed_services"], {"msp": 10})
    score = compute_score(
        _tender(procurement_category="Services SRV"),
        match,
        {"*SRV": 5, "SRV": 5},
        now=NOW,
    )
    assert score == 10 + 5


def test_closing_within_14_and_7_days_utc():
    match = _match(["azure"], ["microsoft_cloud"], {"azure": 14})
    # Within 7 days → +5 +5 = +10
    closing_5d = NOW + timedelta(days=5)
    score = compute_score(_tender(closing=closing_5d), match, {}, now=NOW)
    assert score == 14 + 10

    # Within 14 but not 7 → +5 only
    closing_10d = NOW + timedelta(days=10)
    score = compute_score(_tender(closing=closing_10d), match, {}, now=NOW)
    assert score == 14 + 5

    # Past closing → no urgency
    past = NOW - timedelta(days=1)
    score = compute_score(_tender(closing=past), match, {}, now=NOW)
    assert score == 14

    # Beyond 14 days → no urgency
    far = NOW + timedelta(days=30)
    score = compute_score(_tender(closing=far), match, {}, now=NOW)
    assert score == 14


def test_published_within_3_days_utc():
    match = _match(["azure"], ["microsoft_cloud"], {"azure": 14})
    score = compute_score(
        _tender(published=date(2026, 8, 9)),  # 1 day before NOW
        match,
        {},
        now=NOW,
    )
    assert score == 14 + 3

    score_old = compute_score(
        _tender(published=date(2026, 7, 1)),
        match,
        {},
        now=NOW,
    )
    assert score_old == 14


def test_score_clamped_to_100():
    terms = [f"term{i}" for i in range(10)]
    weights = {t: 20 for t in terms}
    match = _match(terms, ["g1", "g2", "g3", "g4", "g5", "g6"], weights)
    # 200 + multi-group + bonuses would exceed 100
    score = compute_score(
        _tender(
            closing=NOW + timedelta(days=2),
            published=date(2026, 8, 10),
            procurement_category="SRV",
        ),
        match,
        {"SRV": 5},
        now=NOW,
    )
    assert score == 100


def test_scoring_clock_uses_utc_naive_now_injection():
    """Naive ``now`` is treated as UTC."""
    match = _match(["azure"], ["microsoft_cloud"], {"azure": 14})
    naive_now = datetime(2026, 8, 10, 12, 0, 0)  # no tz
    closing = datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)
    score = compute_score(_tender(closing=closing), match, {}, now=naive_now)
    assert score == 14 + 10  # within 7 days
