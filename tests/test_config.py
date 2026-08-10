"""Minimal tests for Settings (KEYWORDS_PATH, defaults)."""

from __future__ import annotations

from pathlib import Path

from opportunity_ingest.config import Settings, get_settings


def test_settings_defaults(monkeypatch):
    # Clear relevant env so defaults apply
    for key in (
        "STORAGE_BACKEND",
        "DATA_DIR",
        "SQLITE_PATH",
        "KEYWORDS_PATH",
        "STATE_PATH",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)

    s = Settings(_env_file=None)
    assert s.storage_backend == "sqlite"
    assert s.keywords_path == Path("config/keywords.yaml")
    assert s.data_dir == Path("data")
    assert s.resolved_sqlite_path() == Path("data") / "contract_opportunities.db"


def test_settings_keywords_path_from_env(monkeypatch):
    monkeypatch.setenv("KEYWORDS_PATH", "custom/kw.yaml")
    monkeypatch.setenv("STORAGE_BACKEND", "SQLite")
    s = Settings(_env_file=None)
    assert s.keywords_path == Path("custom/kw.yaml")
    assert s.storage_backend == "sqlite"


def test_get_settings_callable():
    s = get_settings()
    assert isinstance(s, Settings)
    assert s.keywords_path is not None
