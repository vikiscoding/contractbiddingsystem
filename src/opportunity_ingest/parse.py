"""Parse CanadaBuys open tender CSV with bilingual header resolution."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from opportunity_ingest.models import TenderRecord

logger = logging.getLogger(__name__)

HEADER_CANDIDATES: dict[str, list[str]] = {
    "title_eng": ["title-titre-eng"],
    "title_fra": ["title-titre-fra"],
    "reference_number": ["referenceNumber-numeroReference"],
    "solicitation_number": ["solicitationNumber-numeroSollicitation"],
    "publication_date": ["publicationDate-datePublication"],
    "closing_date": [
        "tenderClosingDate-appelOffresDateCloture",
        "tenderClosingDate-appelOffresdateCloture",  # historical alias
    ],
    "buyer_eng": ["contractingEntityName-nomEntitContractante-eng"],
    "buyer_fra": ["contractingEntityName-nomEntitContractante-fra"],
    "link_eng": ["noticeURL-URLavis-eng"],
    "link_fra": ["noticeURL-URLavis-fra"],
    "description_eng": ["tenderDescription-descriptionAppelOffres-eng"],
    "description_fra": ["tenderDescription-descriptionAppelOffres-fra"],
    "gsin": ["gsin-nibs"],
    "gsin_desc_eng": ["gsinDescription-nibsDescription-eng"],
    "procurement_category": ["procurementCategory-categorieApprovisionnement"],
    "status_eng": ["tenderStatus-appelOffresStatut-eng"],
}

# Required logical header groups: at least one candidate column must resolve.
REQUIRED_HEADER_GROUPS: dict[str, tuple[str, ...]] = {
    "title": ("title_eng", "title_fra"),
    "reference_or_solicitation": ("reference_number", "solicitation_number"),
    "notice_url": ("link_eng", "link_fra"),
}

try:
    _TORONTO_TZ = ZoneInfo("America/Toronto")
except ZoneInfoNotFoundError:  # pragma: no cover - Windows without tzdata
    _TORONTO_TZ = timezone(timedelta(hours=-5))

UTC = timezone.utc


class ParseError(Exception):
    """Hard-fail parse errors (e.g. missing required header groups)."""


def _normalize_header(name: str) -> str:
    return name.strip().lower()


def resolve_headers(fieldnames: Sequence[str] | None) -> dict[str, str]:
    """Map logical field keys → original CSV header strings (case-insensitive).

    Raises:
        ParseError: if a required header group cannot be resolved.
    """
    if not fieldnames:
        raise ParseError("CSV has no header row")

    by_norm: dict[str, str] = {}
    for raw in fieldnames:
        if raw is None:
            continue
        norm = _normalize_header(raw)
        # First occurrence wins if duplicates
        by_norm.setdefault(norm, raw)

    resolved: dict[str, str] = {}
    for logical, candidates in HEADER_CANDIDATES.items():
        for cand in candidates:
            key = _normalize_header(cand)
            if key in by_norm:
                resolved[logical] = by_norm[key]
                break

    missing_groups: list[str] = []
    for group_name, logical_keys in REQUIRED_HEADER_GROUPS.items():
        if not any(k in resolved for k in logical_keys):
            missing_groups.append(group_name)
    if missing_groups:
        raise ParseError(
            "Missing required CSV header group(s): " + ", ".join(missing_groups)
        )

    return resolved


def _cell(row: Mapping[str, Any], header: str | None) -> str:
    if not header:
        return ""
    val = row.get(header)
    if val is None:
        return ""
    return str(val).strip()


def coalesce_en_fr(eng: str, fra: str) -> str:
    """English preferred; French if English empty."""
    return eng if eng else fra


def parse_closing_date(raw: str) -> datetime | None:
    """Parse closing date; naive values treated as America/Toronto (or UTC-0500).

    Returns timezone-aware UTC datetime, or None if empty/unparseable.
    """
    text = (raw or "").strip()
    if not text:
        return None

    # Support ISO with Z / offset, date-only, and space-separated datetime.
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")

    dt: datetime | None = None
    for cand in candidates:
        try:
            dt = datetime.fromisoformat(cand)
            break
        except ValueError:
            pass

    if dt is None:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
        ):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue

    if dt is None:
        logger.warning("Unparseable closing date: %r", text)
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TORONTO_TZ)
    return dt.astimezone(UTC)


def parse_publication_date(raw: str) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    # Date-only or datetime prefix
    try:
        if "T" in text or " " in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.date()
        return date.fromisoformat(text[:10])
    except ValueError:
        for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(text[:10], fmt).date()
            except ValueError:
                continue
    logger.warning("Unparseable publication date: %r", text)
    return None


def row_to_record(
    row: Mapping[str, Any],
    headers: Mapping[str, str],
    *,
    row_number: int,
) -> TenderRecord | None:
    """Coalesce one CSV row into a TenderRecord, or None to skip (missing IDs)."""
    ref = _cell(row, headers.get("reference_number")) or None
    sol = _cell(row, headers.get("solicitation_number")) or None
    if not ref and not sol:
        logger.error(
            "Skipping row %s: empty reference and solicitation numbers",
            row_number,
        )
        return None

    title = coalesce_en_fr(
        _cell(row, headers.get("title_eng")),
        _cell(row, headers.get("title_fra")),
    )
    link = coalesce_en_fr(
        _cell(row, headers.get("link_eng")),
        _cell(row, headers.get("link_fra")),
    )
    # Link must never be truncated; store as-is even if empty (header group already required).
    buyer = (
        coalesce_en_fr(
            _cell(row, headers.get("buyer_eng")),
            _cell(row, headers.get("buyer_fra")),
        )
        or None
    )
    description = (
        coalesce_en_fr(
            _cell(row, headers.get("description_eng")),
            _cell(row, headers.get("description_fra")),
        )
        or None
    )
    gsin_desc = _cell(row, headers.get("gsin_desc_eng")) or None
    gsin = _cell(row, headers.get("gsin")) or None
    procurement_category = _cell(row, headers.get("procurement_category")) or None
    status_text = _cell(row, headers.get("status_eng")) or None
    publication_date = parse_publication_date(_cell(row, headers.get("publication_date")))
    closing_date = parse_closing_date(_cell(row, headers.get("closing_date")))

    return TenderRecord(
        title=title,
        reference_number=ref,
        solicitation_number=sol,
        publication_date=publication_date,
        closing_date=closing_date,
        buyer=buyer,
        link=link,
        description=description,
        gsin=gsin,
        gsin_desc=gsin_desc,
        procurement_category=procurement_category,
        status_text=status_text,
    )


def parse_csv_file(path: str | Path) -> list[TenderRecord]:
    """Parse a CSV file path (utf-8-sig)."""
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        return parse_csv_stream(fh)


def parse_csv_text(text: str) -> list[TenderRecord]:
    """Parse CSV content already decoded (BOM should be stripped if present)."""
    return parse_csv_stream(io.StringIO(text))


def parse_csv_stream(stream: TextIO) -> list[TenderRecord]:
    """Parse an open text stream into TenderRecords."""
    reader = csv.DictReader(stream)
    headers = resolve_headers(reader.fieldnames)
    records: list[TenderRecord] = []
    # DictReader row 1 is first data row; header is row 0 conceptually
    for i, row in enumerate(reader, start=2):
        rec = row_to_record(row, headers, row_number=i)
        if rec is not None:
            records.append(rec)
    logger.info("Parsed %s tender records", len(records))
    return records


def parse_csv(source: str | Path | TextIO | Iterable[str]) -> list[TenderRecord]:
    """Convenience entry: path, raw text (if looks multi-line CSV), or stream."""
    if isinstance(source, Path):
        return parse_csv_file(source)
    if isinstance(source, str):
        # Treat as path if it exists; otherwise as CSV text
        p = Path(source)
        if p.is_file():
            return parse_csv_file(p)
        return parse_csv_text(source)
    return parse_csv_stream(source)  # type: ignore[arg-type]
