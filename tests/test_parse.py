"""Unit tests for bilingual CSV header resolution and EN/FR coalesce."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from opportunity_ingest.parse import (
    CANADABUYS_NAIVE_TZ,
    ParseError,
    coalesce_en_fr,
    parse_closing_date,
    parse_csv_file,
    parse_csv_text,
    resolve_headers,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "open_tender_sample.csv"
HISTORICAL = FIXTURES / "open_tender_historical_closing_header.csv"


def test_resolve_headers_bilingual_and_case_insensitive():
    fieldnames = [
        "Title-Titre-Eng",
        "title-titre-fra",
        "referenceNumber-numeroReference",
        "solicitationNumber-numeroSollicitation",
        "noticeURL-URLavis-eng",
    ]
    headers = resolve_headers(fieldnames)
    assert headers["title_eng"] == "Title-Titre-Eng"
    assert headers["title_fra"] == "title-titre-fra"
    assert headers["reference_number"] == "referenceNumber-numeroReference"
    assert headers["link_eng"] == "noticeURL-URLavis-eng"


def test_resolve_headers_strips_bom_on_first_field():
    fieldnames = [
        "\ufefftitle-titre-eng",
        "referenceNumber-numeroReference",
        "noticeURL-URLavis-eng",
    ]
    headers = resolve_headers(fieldnames)
    assert headers["title_eng"] == "\ufefftitle-titre-eng"
    assert "title_eng" in headers


def test_resolve_headers_missing_title_group_hard_fails():
    fieldnames = [
        "referenceNumber-numeroReference",
        "noticeURL-URLavis-eng",
    ]
    with pytest.raises(ParseError, match="title"):
        resolve_headers(fieldnames)


def test_resolve_headers_missing_id_group_hard_fails():
    fieldnames = [
        "title-titre-eng",
        "noticeURL-URLavis-eng",
    ]
    with pytest.raises(ParseError, match="reference_or_solicitation"):
        resolve_headers(fieldnames)


def test_resolve_headers_missing_notice_url_hard_fails():
    fieldnames = [
        "title-titre-eng",
        "referenceNumber-numeroReference",
    ]
    with pytest.raises(ParseError, match="notice_url"):
        resolve_headers(fieldnames)


def test_resolve_headers_historical_closing_alias():
    fieldnames = [
        "title-titre-eng",
        "referenceNumber-numeroReference",
        "tenderClosingDate-appelOffresdateCloture",
        "noticeURL-URLavis-eng",
    ]
    headers = resolve_headers(fieldnames)
    assert headers["closing_date"] == "tenderClosingDate-appelOffresdateCloture"


def test_coalesce_en_preferred():
    assert coalesce_en_fr("EN", "FR") == "EN"
    assert coalesce_en_fr("", "FR") == "FR"
    assert coalesce_en_fr("EN", "") == "EN"
    assert coalesce_en_fr("", "") == ""


def test_parse_sample_skips_missing_ids_and_coalesces():
    records = parse_csv_file(SAMPLE)
    # 4 data rows; one skipped (empty both IDs) → 3
    assert len(records) == 3

    by_id = {r.opportunity_id: r for r in records}
    assert set(by_id) == {"REF-001", "SOL-FR-ONLY", "SOL-ONLY-REF-EMPTY"}

    eng = by_id["REF-001"]
    assert eng.title == "English Title Only"
    assert eng.buyer == "Public Works Canada"
    assert eng.description == "English description of the tender."
    assert eng.link.startswith("https://canadabuys.canada.ca/en/tender-opportunities/")
    assert "never-be-truncated" in eng.link
    assert eng.reference_number == "REF-001"
    assert eng.solicitation_number == "SOL-001"
    assert eng.publication_date == date(2026, 8, 1)
    assert eng.gsin == "N1"
    assert eng.gsin_desc == "IT Consulting Services"
    assert eng.procurement_category == "Services"
    assert eng.status_text == "Open"
    assert eng.closing_date is not None
    assert eng.closing_date.tzinfo is not None
    assert eng.closing_date == eng.closing_date.astimezone(timezone.utc)

    fr_only = by_id["SOL-FR-ONLY"]
    assert fr_only.title == "Titre FR seulement"
    assert fr_only.link == "https://canadabuys.canada.ca/fr/notice/sol-fr-only"
    assert fr_only.buyer == "Entité FR"
    assert fr_only.description == "Description en français uniquement."
    assert fr_only.reference_number is None
    assert fr_only.solicitation_number == "SOL-FR-ONLY"
    assert fr_only.opportunity_id == "SOL-FR-ONLY"

    sol_only = by_id["SOL-ONLY-REF-EMPTY"]
    assert sol_only.opportunity_id == "SOL-ONLY-REF-EMPTY"
    assert sol_only.reference_number is None
    assert sol_only.solicitation_number == "SOL-ONLY-REF-EMPTY"


def test_link_never_truncated():
    records = parse_csv_file(SAMPLE)
    eng = next(r for r in records if r.opportunity_id == "REF-001")
    assert len(eng.link) > 80
    assert eng.link.endswith("never-be-truncated-even-if-it-is-quite-long")


def test_closing_date_naive_as_fixed_utc_minus_5():
    # Design: naive CanadaBuys times are fixed UTC-0500 (not DST-aware).
    # 2026-09-15 17:00:00 UTC-05 → 2026-09-15 22:00:00 UTC (deterministic on all hosts).
    dt = parse_closing_date("2026-09-15 17:00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert CANADABUYS_NAIVE_TZ.utcoffset(None).total_seconds() == -5 * 3600
    assert dt == datetime(2026, 9, 15, 22, 0, 0, tzinfo=timezone.utc)


def test_closing_date_aware_preserved_as_utc():
    dt = parse_closing_date("2026-09-15T17:00:00+00:00")
    assert dt == datetime(2026, 9, 15, 17, 0, 0, tzinfo=timezone.utc)


def test_parse_historical_closing_header_fixture():
    records = parse_csv_file(HISTORICAL)
    assert len(records) == 1
    assert records[0].opportunity_id == "REF-HIST"
    assert records[0].closing_date is not None


def test_parse_csv_text_roundtrip_headers():
    text = SAMPLE.read_text(encoding="utf-8")
    records = parse_csv_text(text)
    assert len(records) == 3


def test_bom_decoded_utf8_sig(tmp_path: Path):
    raw = SAMPLE.read_bytes()
    bom_path = tmp_path / "with_bom.csv"
    bom_path.write_bytes(b"\xef\xbb\xbf" + raw)
    records = parse_csv_file(bom_path)
    assert len(records) == 3


def test_parse_csv_text_with_leading_bom_char():
    text = "\ufeff" + SAMPLE.read_text(encoding="utf-8")
    records = parse_csv_text(text)
    assert len(records) == 3
