"""Unit tests for Google Sheets sync helpers (no live network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opportunity_ingest.sheets_sync import (
    DEFAULT_RANK_TAB,
    RANKING_EXPORT_COLUMNS,
    SheetsSyncError,
    _load_service_account_info,
    find_latest_rankings_json,
    load_rankings_json,
    rankings_to_sheet_values,
    sync_rankings_to_sheet,
)


def test_load_service_account_from_file(tmp_path: Path) -> None:
    path = tmp_path / "sa.json"
    path.write_text(
        json.dumps({"type": "service_account", "client_email": "a@b.iam"}),
        encoding="utf-8",
    )
    info = _load_service_account_info(path, None)
    assert info["client_email"] == "a@b.iam"


def test_load_service_account_from_inline_json() -> None:
    raw = json.dumps({"type": "service_account", "project_id": "p1"})
    info = _load_service_account_info(None, raw)
    assert info["project_id"] == "p1"


def test_load_service_account_missing_raises() -> None:
    with pytest.raises(SheetsSyncError, match="GOOGLE_SERVICE_ACCOUNT"):
        _load_service_account_info(None, None)


def test_load_service_account_bad_json() -> None:
    with pytest.raises(SheetsSyncError, match="not valid JSON"):
        _load_service_account_info(None, "{not-json")


def test_rankings_to_sheet_values_shape() -> None:
    rows = [
        {
            "rank": 1,
            "fit_score": 88,
            "recommendation": "pursue",
            "title": "Cloud RFP",
            "opportunity_id": "TECH-1",
            "buyer": "Agency",
            "closing_date": "2026-09-01",
            "keywords_matched": "azure",
            "rule_relevance_score": 40,
            "matched_objectives": ["microsoft_cloud", "ai_operations"],
            "plain_english": "Plain text",
            "interpreted_objective": "Modernize",
            "why_it_fits": "Stack match",
            "risks_or_mismatches": "None",
            "next_action": "Open link",
            "link": "https://example.com/a",
        }
    ]
    values = rankings_to_sheet_values(rows, run_id="run1", model="grok-4.5")
    assert values[0] == list(RANKING_EXPORT_COLUMNS)
    assert len(values) == 2
    assert values[1][0] == "run1"
    assert values[1][1] == "grok-4.5"
    assert values[1][2] == 1
    assert values[1][3] == 88
    assert values[1][11] == "microsoft_cloud, ai_operations"
    assert values[1][-1] == "https://example.com/a"


def test_sync_rankings_refuses_ingest_tab() -> None:
    with pytest.raises(SheetsSyncError, match="Refusing"):
        sync_rankings_to_sheet(
            [],
            run_id="r",
            model="m",
            spreadsheet_id="sheet123",
            worksheet_title="Ingest",
            service_account_json=json.dumps({"type": "service_account"}),
        )


def test_load_rankings_json_and_latest(tmp_path: Path) -> None:
    older = tmp_path / "interpret-20260101T000000Z.json"
    newer = tmp_path / "interpret-20260811T120000Z.json"
    payload = {
        "run_id": "20260811T120000Z",
        "model": "grok-4.5",
        "ranked": [
            {
                "rank": 1,
                "opportunity_id": "X",
                "title": "T",
                "fit_score": 50,
                "recommendation": "watch",
                "matched_objectives": [],
                "plain_english": "p",
                "interpreted_objective": "i",
                "why_it_fits": "w",
                "risks_or_mismatches": "r",
                "next_action": "n",
                "link": "https://example.com",
            }
        ],
    }
    older.write_text(json.dumps({"run_id": "old", "model": "m", "ranked": []}), encoding="utf-8")
    newer.write_text(json.dumps(payload), encoding="utf-8")
    # Ensure mtime ordering
    import os
    import time

    os.utime(older, (time.time() - 100, time.time() - 100))
    os.utime(newer, (time.time(), time.time()))

    run_id, model, ranked = load_rankings_json(newer)
    assert run_id == "20260811T120000Z"
    assert model == "grok-4.5"
    assert ranked[0]["opportunity_id"] == "X"

    latest = find_latest_rankings_json(tmp_path)
    assert latest == newer
    assert find_latest_rankings_json(tmp_path / "missing") is None
    assert DEFAULT_RANK_TAB == "Ranked"


def test_load_rankings_json_missing(tmp_path: Path) -> None:
    with pytest.raises(SheetsSyncError, match="not found"):
        load_rankings_json(tmp_path / "nope.json")
