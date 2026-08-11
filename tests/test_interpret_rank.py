"""Unit tests for Grok interpret-rank (mocked client; no live API)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from opportunity_ingest.interpret_rank import (
    CompanyObjectives,
    InterpretRankError,
    _extract_json_object,
    build_user_prompt,
    filter_rows,
    load_objectives,
    merge_model_rankings,
    prepare_opportunity_payload,
    rank_opportunities,
    render_markdown,
    run_interpret_rank,
    write_reports,
)


class FakeGrok:
    """Deterministic client for tests."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.calls = 0

    def complete_json(self, *, system: str, user: str) -> dict:
        self.calls += 1
        # Pull opportunity ids from the JSON block in the user prompt.
        start = user.find("## Opportunities to interpret")
        assert start >= 0
        # Find first [ after that header for the opportunities array.
        arr_start = user.find("[", start)
        arr_end = user.find("\n## Required JSON schema", arr_start)
        blob = user[arr_start:arr_end].strip()
        opps = json.loads(blob)
        rankings = []
        for i, o in enumerate(opps):
            oid = o["opportunity_id"]
            # Higher for known tech-ish ids in fixtures.
            fit = 90 - i * 5 if "TECH" in oid else 40 - i
            rankings.append(
                {
                    "opportunity_id": oid,
                    "fit_score": fit,
                    "recommendation": "pursue" if fit >= 70 else "watch",
                    "plain_english": f"Plain summary for {oid}",
                    "interpreted_objective": f"Buyer wants outcome for {oid}",
                    "matched_objectives": ["microsoft_cloud"],
                    "why_it_fits": "Matches cloud skills.",
                    "risks_or_mismatches": "Limited description.",
                    "next_action": "Open the Link and confirm scope.",
                }
            )
        return {"rankings": rankings}


def _sample_objectives(tmp_path: Path) -> Path:
    data = {
        "version": 1,
        "company": {"name": "Test Co", "summary": "Cloud services"},
        "objectives": [
            {
                "id": "microsoft_cloud",
                "label": "M365",
                "priority": "critical",
                "description": "Microsoft work",
            }
        ],
        "guidance": {"prefer": ["IT"], "deprioritize": ["construction"]},
    }
    path = tmp_path / "objectives.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_load_objectives_ok(tmp_path: Path):
    path = _sample_objectives(tmp_path)
    obj = load_objectives(path)
    assert obj.version == 1
    assert obj.company["name"] == "Test Co"
    assert obj.objectives[0]["id"] == "microsoft_cloud"


def test_load_objectives_missing(tmp_path: Path):
    with pytest.raises(InterpretRankError, match="not found"):
        load_objectives(tmp_path / "nope.yaml")


def test_filter_rows_status_limit_and_score():
    rows = [
        {"OpportunityID": "A", "Status": "New", "RelevanceScore": 10},
        {"OpportunityID": "B", "Status": "New", "RelevanceScore": 50},
        {"OpportunityID": "C", "Status": "Discarded", "RelevanceScore": 99},
    ]
    out = filter_rows(rows, status="New", min_rule_score=20, limit=1)
    assert len(out) == 1
    assert out[0]["OpportunityID"] == "B"


def test_prepare_and_merge_roundtrip():
    rows = [
        {
            "Title": "Cloud RFP",
            "OpportunityID": "TECH-1",
            "Buyer": "Agency",
            "Description": "Need SharePoint &amp; Power Apps",
            "KeywordsMatched": "sharepoint",
            "RelevanceScore": 40,
            "Link": "https://example.com/a",
            "ClosingDate": "2026-09-01T00:00:00Z",
        }
    ]
    prepared = prepare_opportunity_payload(rows)
    assert prepared[0]["description"] == "Need SharePoint & Power Apps"
    model = {
        "rankings": [
            {
                "opportunity_id": "TECH-1",
                "fit_score": 88,
                "recommendation": "pursue",
                "plain_english": "Buyer needs Power Platform help.",
                "interpreted_objective": "Modernize collaboration tools.",
                "matched_objectives": ["microsoft_cloud"],
                "why_it_fits": "Direct stack match.",
                "risks_or_mismatches": "None major.",
                "next_action": "Download full package.",
            }
        ]
    }
    ranked = merge_model_rankings(prepared, model)
    assert len(ranked) == 1
    assert ranked[0].rank == 1
    assert ranked[0].fit_score == 88
    assert ranked[0].recommendation == "pursue"


def test_merge_fills_missing_model_rows():
    prepared = [
        {"opportunity_id": "X", "title": "T", "buyer": None, "link": "u",
         "closing_date": None, "keywords_matched": None, "rule_relevance_score": 1,
         "description": "d"},
    ]
    ranked = merge_model_rankings(prepared, {"rankings": []})
    assert ranked[0].fit_score == 0
    assert "Model did not return" in ranked[0].interpreted_objective


def test_extract_json_fenced():
    data = _extract_json_object('```json\n{"rankings": []}\n```')
    assert data == {"rankings": []}


def test_rank_and_write_reports(tmp_path: Path):
    path = _sample_objectives(tmp_path)
    objectives = load_objectives(path)
    rows = [
        {
            "Title": "Tech deal",
            "OpportunityID": "TECH-9",
            "Buyer": "B",
            "Description": "Azure migration",
            "KeywordsMatched": "azure",
            "RelevanceScore": 30,
            "Link": "https://example.com/t",
            "Status": "New",
        },
        {
            "Title": "Other",
            "OpportunityID": "OTH-1",
            "Buyer": "B",
            "Description": "Something else",
            "KeywordsMatched": "service desk",
            "RelevanceScore": 10,
            "Link": "https://example.com/o",
            "Status": "New",
        },
    ]
    client = FakeGrok()
    result = rank_opportunities(rows, objectives, client, model_name="fake", batch_size=10)
    assert client.calls == 1
    assert result.input_count == 2
    assert result.ranked[0].opportunity_id == "TECH-9"
    assert result.ranked[0].fit_score >= result.ranked[1].fit_score

    written = write_reports(result, objectives, out_dir=tmp_path / "rankings", objectives_path=path)
    assert written.json_path is not None and written.json_path.is_file()
    assert written.markdown_path is not None and written.markdown_path.is_file()
    md = written.markdown_path.read_text(encoding="utf-8")
    assert "Fit score" in md
    assert "TECH-9" in md
    payload = json.loads(written.json_path.read_text(encoding="utf-8"))
    assert payload["ranked_count"] == 2


def test_run_interpret_rank_with_factory(tmp_path: Path):
    path = _sample_objectives(tmp_path)
    rows = [
        {
            "Title": "Tech deal",
            "OpportunityID": "TECH-1",
            "Buyer": "B",
            "Description": "Power Platform",
            "KeywordsMatched": "power platform",
            "RelevanceScore": 50,
            "Link": "https://example.com/a",
            "Status": "New",
        }
    ]
    result = run_interpret_rank(
        rows,
        objectives_path=path,
        api_key="test-key",
        model="fake-model",
        out_dir=tmp_path / "out",
        client_factory=FakeGrok,
    )
    assert result.ranked[0].plain_english.startswith("Plain summary")
    assert result.markdown_path is not None


def test_build_user_prompt_includes_objectives():
    obj = CompanyObjectives(
        version=1,
        company={"name": "Co"},
        objectives=[{"id": "x", "label": "X"}],
        guidance={},
        raw={},
    )
    prompt = build_user_prompt(
        obj,
        [{"opportunity_id": "1", "title": "T"}],
    )
    assert "Company objectives" in prompt
    assert "opportunity_id" in prompt


def test_render_markdown_empty():
    from opportunity_ingest.interpret_rank import InterpretRankResult

    obj = CompanyObjectives(1, {"name": "Co"}, [{"id": "a"}], {}, {})
    md = render_markdown(
        InterpretRankResult("rid", "m", [], 0),
        obj,
    )
    assert "No opportunities" in md
