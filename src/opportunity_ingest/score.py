"""Rule-based RelevanceScore (0–100). Scoring clock is UTC."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Mapping

from opportunity_ingest.filter_keywords import KeywordMatchResult
from opportunity_ingest.models import TenderRecord

UTC = timezone.utc

# Closing urgency (future closings only).
CLOSING_WITHIN_14_DAYS_BONUS = 5
CLOSING_WITHIN_7_DAYS_EXTRA = 5
# Freshness: published within last 3 calendar days (UTC).
PUBLISHED_WITHIN_3_DAYS_BONUS = 3
# Cross-group diversity bonus.
MULTI_GROUP_BONUS_PER = 3
MULTI_GROUP_BONUS_CAP = 15


def category_boost(procurement_category: str | None, boosts: Mapping[str, int]) -> int:
    """Return best matching category boost for the raw CSV procurement category.

    Keys starting with ``*`` are substring (case-insensitive) needles;
    other keys are exact match (case-insensitive).
    """
    if not procurement_category or not boosts:
        return 0
    cat = procurement_category.strip()
    if not cat:
        return 0
    cat_upper = cat.upper()
    best = 0
    for key, boost in boosts.items():
        if not key:
            continue
        if key.startswith("*"):
            needle = key[1:]
            if needle and needle.upper() in cat_upper:
                best = max(best, int(boost))
        elif key.upper() == cat_upper:
            best = max(best, int(boost))
    return best


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def compute_score(
    tender: TenderRecord,
    match: KeywordMatchResult,
    category_boosts: Mapping[str, int] | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """Compute integer RelevanceScore 0–100 using the design formula.

    ```
    score = sum(unique matched term weights)
    score += min(15, 3 * (unique_group_count - 1))
    score += category_boost(procurement_category)
    if closing within 14 days UTC: +5; within 7 days: +5 more
    if published within 3 days UTC: +3
    score = clamp(0, 100)
    ```

    ``now`` defaults to current UTC (injectable for tests).
    """
    if now is None:
        now = datetime.now(UTC)
    else:
        now = _as_utc(now)

    # Unique matched term weights (already unique in KeywordMatchResult).
    score = sum(int(w) for w in match.weights.values())

    group_count = len(match.groups)
    if group_count > 0:
        score += min(MULTI_GROUP_BONUS_CAP, MULTI_GROUP_BONUS_PER * (group_count - 1))

    score += category_boost(tender.procurement_category, category_boosts or {})

    if tender.closing_date is not None:
        closing = _as_utc(tender.closing_date)
        delta = closing - now
        # Future (or exact now) closings within windows.
        if timedelta(0) <= delta <= timedelta(days=14):
            score += CLOSING_WITHIN_14_DAYS_BONUS
        if timedelta(0) <= delta <= timedelta(days=7):
            score += CLOSING_WITHIN_7_DAYS_EXTRA

    if tender.publication_date is not None:
        today: date = now.date()
        pub = tender.publication_date
        age_days = (today - pub).days
        if 0 <= age_days <= 3:
            score += PUBLISHED_WITHIN_3_DAYS_BONUS

    return max(0, min(100, score))
