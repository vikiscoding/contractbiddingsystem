"""Map TenderRecord + keyword matches + score → logical OpportunityFields.

Link is never silently truncated. Title max 255; Description max 2000.
"""

from __future__ import annotations

from datetime import datetime, timezone

from opportunity_ingest.filter_keywords import KeywordMatchResult
from opportunity_ingest.models import OpportunityFields, TenderRecord

UTC = timezone.utc

TITLE_MAX_LEN = 255
DESCRIPTION_MAX_LEN = 2000
SOURCE_CANADABUYS = "CanadaBuys"
STATUS_NEW = "New"

# Legacy single-line hyperlink field width (SharePoint Hyperlink column).
# Default backend uses multi-line TEXT — we do NOT apply this unless asked.
LEGACY_SINGLE_LINE_LINK_MAX = 255


class MapError(Exception):
    """Raised when a tender cannot be mapped to logical fields."""


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _join_keywords(terms: tuple[str, ...] | list[str]) -> str:
    return ", ".join(terms)


def map_to_opportunity_fields(
    tender: TenderRecord,
    match: KeywordMatchResult,
    score: int,
    *,
    now: datetime | None = None,
    enforce_single_line_link_limit: bool = False,
    single_line_link_max: int = LEGACY_SINGLE_LINE_LINK_MAX,
) -> OpportunityFields:
    """Build ``OpportunityFields`` for storage backends.

    Args:
        tender: Parsed open-tender row (title already EN-else-FR coalesced).
        match: Keyword match result (terms/groups).
        score: RelevanceScore 0–100.
        now: Override for DateAdded (UTC). Defaults to current UTC.
        enforce_single_line_link_limit: If True and Link exceeds
            ``single_line_link_max``, raise ``MapError`` instead of truncating.
            Default False stores the full URL (multi-line TEXT).
        single_line_link_max: Hard limit only when enforce flag is True.

    Raises:
        MapError: missing Title/OpportunityID/Link, or Link exceeds enforced limit.
    """
    if now is None:
        now = datetime.now(UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)

    opportunity_id = (tender.opportunity_id or "").strip()
    if not opportunity_id:
        raise MapError("OpportunityID is required (reference or solicitation empty)")

    link = tender.link if tender.link is not None else ""
    # Never silent-truncate Link. Optionally hard-fail on legacy single-line limit.
    if enforce_single_line_link_limit and len(link) > single_line_link_max:
        raise MapError(
            f"Link length {len(link)} exceeds hard single-line limit "
            f"{single_line_link_max}; refusing silent truncation"
        )
    if not link.strip():
        raise MapError(f"Link is required for OpportunityID={opportunity_id!r}")

    # Title is required on the logical schema; reject empty/whitespace after trim.
    title = _truncate((tender.title or "").strip(), TITLE_MAX_LEN)
    if not title:
        raise MapError(f"Title is required for OpportunityID={opportunity_id!r}")

    description: str | None = None
    if tender.description:
        description = _truncate(tender.description, DESCRIPTION_MAX_LEN)

    # Category: GSIN preferred, else procurement category (design mapping rules).
    category = tender.gsin or tender.procurement_category

    keywords_matched = _join_keywords(match.terms) if match.terms else ""

    clamped = max(0, min(100, int(score)))

    return OpportunityFields(
        Title=title,
        OpportunityID=opportunity_id,
        Source=SOURCE_CANADABUYS,
        Buyer=tender.buyer,
        Link=link,  # full URL; never truncated
        PublishedDate=tender.publication_date,
        ClosingDate=tender.closing_date,
        Category=category,
        Description=description,
        KeywordsMatched=keywords_matched,
        RelevanceScore=clamped,
        Status=STATUS_NEW,
        DateAdded=now,
        Notes="",
    )


def map_to_dict(
    tender: TenderRecord,
    match: KeywordMatchResult,
    score: int,
    *,
    now: datetime | None = None,
    enforce_single_line_link_limit: bool = False,
) -> dict[str, object]:
    """Same as ``map_to_opportunity_fields`` but returns a plain dict (logical schema keys)."""
    fields = map_to_opportunity_fields(
        tender,
        match,
        score,
        now=now,
        enforce_single_line_link_limit=enforce_single_line_link_limit,
    )
    return fields.as_dict()
