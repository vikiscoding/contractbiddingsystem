"""Tests for logical field mapping (no Link truncation)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from opportunity_ingest.filter_keywords import KeywordMatchResult
from opportunity_ingest.map_fields import (
    DESCRIPTION_MAX_LEN,
    TITLE_MAX_LEN,
    MapError,
    map_to_dict,
    map_to_opportunity_fields,
)
from opportunity_ingest.models import OpportunityFields, TenderRecord

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 15, 30, 0, tzinfo=UTC)


def _match(terms: list[str] | None = None) -> KeywordMatchResult:
    terms = terms or ["azure", "rpa"]
    return KeywordMatchResult(
        matched=True,
        terms=tuple(terms),
        groups=("microsoft_cloud", "automation_process"),
        weights={t: 10 for t in terms},
    )


def _tender(**overrides: object) -> TenderRecord:
    base = dict(
        title="Cloud RPA services",
        reference_number="PW-2026-001",
        solicitation_number=None,
        publication_date=date(2026, 8, 8),
        closing_date=datetime(2026, 8, 20, 14, 0, 0, tzinfo=UTC),
        buyer="Public Services and Procurement Canada",
        link="https://canadabuys.canada.ca/en/tender-opportunities/notice/pw-2026-001",
        description="Azure and RPA managed services",
        gsin="D302A",
        gsin_desc="IT services",
        procurement_category="Services",
        status_text="Open",
    )
    base.update(overrides)
    return TenderRecord(**base)  # type: ignore[arg-type]


def test_map_fields_logical_schema():
    fields = map_to_opportunity_fields(_tender(), _match(), score=42, now=NOW)
    assert isinstance(fields, OpportunityFields)
    assert fields.Title == "Cloud RPA services"
    assert fields.OpportunityID == "PW-2026-001"
    assert fields.Source == "CanadaBuys"
    assert fields.Buyer == "Public Services and Procurement Canada"
    assert fields.Link.startswith("https://canadabuys.canada.ca/")
    assert fields.PublishedDate == date(2026, 8, 8)
    assert fields.ClosingDate == datetime(2026, 8, 20, 14, 0, 0, tzinfo=UTC)
    assert fields.Category == "D302A"  # GSIN preferred
    assert fields.Description == "Azure and RPA managed services"
    assert fields.KeywordsMatched == "azure, rpa"
    assert fields.RelevanceScore == 42
    assert fields.Status == "New"
    assert fields.DateAdded == NOW
    assert fields.Notes == ""


def test_map_to_dict_keys():
    d = map_to_dict(_tender(), _match(), score=10, now=NOW)
    assert d["Source"] == "CanadaBuys"
    assert d["Status"] == "New"
    assert d["RelevanceScore"] == 10
    assert "Link" in d


def test_title_truncated_to_255():
    long_title = "A" * 300
    fields = map_to_opportunity_fields(
        _tender(title=long_title),
        _match(),
        score=1,
        now=NOW,
    )
    assert len(fields.Title) == TITLE_MAX_LEN
    assert fields.Title == "A" * TITLE_MAX_LEN


def test_description_truncated_to_2000():
    long_desc = "B" * 2500
    fields = map_to_opportunity_fields(
        _tender(description=long_desc),
        _match(),
        score=1,
        now=NOW,
    )
    assert fields.Description is not None
    assert len(fields.Description) == DESCRIPTION_MAX_LEN


def test_no_link_truncation_for_long_urls():
    # Far longer than any single-line hyperlink limit (255).
    long_url = "https://canadabuys.canada.ca/en/tender-opportunities/notice/" + (
        "segment/" * 80
    ) + "end-id-with-query?a=" + ("x" * 200)
    assert len(long_url) > 255
    fields = map_to_opportunity_fields(
        _tender(link=long_url),
        _match(),
        score=5,
        now=NOW,
    )
    assert fields.Link == long_url
    assert len(fields.Link) == len(long_url)


def test_enforce_single_line_link_limit_raises_not_truncates():
    long_url = "https://example.com/" + ("a" * 300)
    with pytest.raises(MapError, match="single-line limit"):
        map_to_opportunity_fields(
            _tender(link=long_url),
            _match(),
            score=1,
            now=NOW,
            enforce_single_line_link_limit=True,
            single_line_link_max=255,
        )


def test_empty_link_raises():
    with pytest.raises(MapError, match="Link"):
        map_to_opportunity_fields(
            _tender(link=""),
            _match(),
            score=1,
            now=NOW,
        )


def test_empty_opportunity_id_raises():
    with pytest.raises(MapError, match="OpportunityID"):
        map_to_opportunity_fields(
            _tender(reference_number=None, solicitation_number=None),
            _match(),
            score=1,
            now=NOW,
        )


def test_category_falls_back_to_procurement_category():
    fields = map_to_opportunity_fields(
        _tender(gsin=None, procurement_category="Services"),
        _match(),
        score=1,
        now=NOW,
    )
    assert fields.Category == "Services"


def test_score_clamped_on_map():
    fields = map_to_opportunity_fields(_tender(), _match(), score=150, now=NOW)
    assert fields.RelevanceScore == 100
    fields_neg = map_to_opportunity_fields(_tender(), _match(), score=-5, now=NOW)
    assert fields_neg.RelevanceScore == 0


def test_opportunity_id_from_solicitation_when_no_reference():
    fields = map_to_opportunity_fields(
        _tender(reference_number=None, solicitation_number="SOL-99"),
        _match(),
        score=1,
        now=NOW,
    )
    assert fields.OpportunityID == "SOL-99"
