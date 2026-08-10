"""Tests for keyword filtering (word-boundary short terms, any-match, groups)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from opportunity_ingest.filter_keywords import (
    KeywordConfigError,
    KeywordMatchResult,
    KeywordTerm,
    filter_tenders,
    load_keyword_config,
    match_keywords,
)
from opportunity_ingest.models import TenderRecord

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYWORDS_PATH = REPO_ROOT / "config" / "keywords.yaml"


def _tender(
    *,
    title: str = "Some tender",
    description: str | None = None,
    procurement_category: str | None = None,
    link: str = "https://canadabuys.canada.ca/en/tender-opportunities/123",
    reference: str = "REF-001",
) -> TenderRecord:
    return TenderRecord(
        title=title,
        reference_number=reference,
        solicitation_number=None,
        publication_date=date(2026, 8, 1),
        closing_date=None,
        buyer="PSPC",
        link=link,
        description=description,
        gsin=None,
        gsin_desc=None,
        procurement_category=procurement_category,
        status_text="Open",
    )


def _minimal_config(
    terms: list[tuple[str, int, str]],
    *,
    short_term_max_len: int = 4,
    search_category: bool = True,
    case_sensitive: bool = False,
) -> object:
    from opportunity_ingest.filter_keywords import KeywordConfig

    return KeywordConfig(
        version=1,
        case_sensitive=case_sensitive,
        search_category=search_category,
        short_term_max_len=short_term_max_len,
        terms=tuple(KeywordTerm(term=t, weight=w, group=g) for t, w, g in terms),
        category_boosts={},
        group_labels={},
    )


def test_load_shipped_keywords_yaml():
    cfg = load_keyword_config(KEYWORDS_PATH)
    assert cfg.version == 1
    assert cfg.case_sensitive is False
    assert cfg.search_category is True
    assert cfg.short_term_max_len == 4
    group_ids = {t.group for t in cfg.terms}
    assert group_ids == {
        "microsoft_cloud",
        "managed_services",
        "itsm_servicenow",
        "advisory_consulting",
        "automation_process",
        "ai_operations",
    }
    # No bare noisy terms in shipped defaults
    bare = {t.term.lower() for t in cfg.terms}
    assert "teams" not in bare
    assert "strategy" not in bare
    assert "microsoft teams" in bare


@pytest.mark.parametrize(
    "short_term",
    ["rpa", "msp", "llm", "itsm"],
)
def test_short_terms_word_boundary_match(short_term: str):
    cfg = _minimal_config([(short_term, 10, "g1")])
    hit = _tender(title=f"Need {short_term} specialists for ops")
    miss = _tender(title=f"embedded{short_term}token should not match")
    # Also miss when only a longer superstring with alphanumeric continuation
    miss2 = _tender(title=f"{short_term}xyz tooling")

    result = match_keywords(hit, cfg)
    assert result.matched is True
    assert short_term in result.terms

    assert match_keywords(miss, cfg).matched is False
    assert match_keywords(miss2, cfg).matched is False


def test_short_term_matches_at_punctuation_boundary():
    cfg = _minimal_config([("rpa", 14, "automation_process")])
    hit = _tender(description="Deploy RPA, then hand off.")
    assert match_keywords(hit, cfg).matched is True


def test_long_term_substring_match_case_insensitive():
    cfg = _minimal_config([("power automate", 18, "microsoft_cloud")])
    hit = _tender(title="POWER AUTOMATE workflow support")
    assert match_keywords(hit, cfg).matched is True
    assert match_keywords(hit, cfg).terms == ("power automate",)


def test_any_match_on_description():
    cfg = _minimal_config([("servicenow", 20, "itsm_servicenow")])
    hit = _tender(title="IT support", description="Includes ServiceNow CMDB refresh")
    miss = _tender(title="Office furniture", description="Desks and chairs")
    assert match_keywords(hit, cfg).matched is True
    assert match_keywords(miss, cfg).matched is False


def test_search_category_when_enabled():
    cfg = _minimal_config(
        [("azure", 14, "microsoft_cloud")],
        search_category=True,
    )
    hit = _tender(title="Cloud services", procurement_category="Azure hosting SRV")
    # Category-only match should hit when search_category=True
    assert match_keywords(hit, cfg).matched is True

    cfg_off = _minimal_config(
        [("azure", 14, "microsoft_cloud")],
        search_category=False,
    )
    assert match_keywords(hit, cfg_off).matched is False


def test_multi_group_and_unique_terms():
    cfg = _minimal_config(
        [
            ("rpa", 14, "automation_process"),
            ("itsm", 16, "itsm_servicenow"),
            ("servicenow", 20, "itsm_servicenow"),
        ]
    )
    hit = _tender(
        title="RPA and ITSM",
        description="ServiceNow platform management",
    )
    result = match_keywords(hit, cfg)
    assert result.matched is True
    assert set(result.terms) == {"rpa", "itsm", "servicenow"}
    assert set(result.groups) == {"automation_process", "itsm_servicenow"}
    assert result.weights["rpa"] == 14
    assert result.weights["servicenow"] == 20


def test_filter_tenders_drops_non_matches():
    cfg = _minimal_config([("copilot", 20, "microsoft_cloud")])
    tenders = [
        _tender(title="Microsoft Copilot rollout", reference="A"),
        _tender(title="Road maintenance", reference="B"),
    ]
    filtered = filter_tenders(tenders, cfg)
    assert len(filtered) == 1
    assert filtered[0][0].reference_number == "A"
    assert isinstance(filtered[0][1], KeywordMatchResult)


def test_load_missing_file_raises():
    with pytest.raises(KeywordConfigError):
        load_keyword_config(REPO_ROOT / "config" / "does-not-exist.yaml")
