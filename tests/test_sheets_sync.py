"""Unit tests for Google Sheets sync helpers (no live network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opportunity_ingest.sheets_sync import (
    SheetsSyncError,
    _load_service_account_info,
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
