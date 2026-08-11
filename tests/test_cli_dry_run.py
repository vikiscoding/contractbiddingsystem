"""CLI / pipeline dry-run and write-path tests (sqlite, offline CSV)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from opportunity_ingest.cli import main
from opportunity_ingest.config import Settings
from opportunity_ingest.pipeline import run_pipeline
from opportunity_ingest.state import load_zero_new_streak
from opportunity_ingest.storage.sqlite_store import SqliteOpportunityStore

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_CSV = REPO_ROOT / "tests" / "fixtures" / "open_tender_pipeline.csv"
KEYWORDS = REPO_ROOT / "config" / "keywords.yaml"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        storage_backend="sqlite",
        data_dir=tmp_path / "data",
        sqlite_path=tmp_path / "data" / "contract_opportunities.db",
        keywords_path=KEYWORDS,
        state_path=tmp_path / "state" / "zero_new_streak.json",
        teams_webhook_url=None,
        max_create=50,
        zero_new_streak_threshold=3,
        partial_error_exit_threshold=5,
    )


def test_dry_run_default_no_writes(settings: Settings, tmp_path: Path):
    metrics = run_pipeline(
        settings,
        write=False,
        csv_path=PIPELINE_CSV,
        write_log=True,
        logs_dir=tmp_path / "logs",
    )
    assert metrics.exit_code == 0
    assert metrics.hard_fail is False
    assert metrics.write is False
    assert metrics.added_count == 0
    # Pipeline fixture has 3 keyword hits (M365, ServiceNow, Azure); 1 non-match.
    assert metrics.filtered_count == 3
    assert metrics.mapped_count == 3
    assert metrics.would_create_count == 3
    assert metrics.create_attempts == 3
    # No DB file created on pure dry-run without --with-existing.
    assert not settings.resolved_sqlite_path().is_file()
    # Streak not updated on dry-run.
    streak = load_zero_new_streak(settings.state_path)
    assert streak.consecutive_zero_new_days == 0


def test_dry_run_max_create_caps_would_create(settings: Settings, tmp_path: Path):
    metrics = run_pipeline(
        settings,
        write=False,
        csv_path=PIPELINE_CSV,
        max_create=1,
        write_log=False,
        logs_dir=tmp_path / "logs",
    )
    assert metrics.exit_code == 0
    assert metrics.would_create_count == 1
    assert metrics.skipped_max_create_count == 2
    assert metrics.create_attempts == 1


def test_write_persists_and_export_csv(settings: Settings, tmp_path: Path):
    metrics = run_pipeline(
        settings,
        write=True,
        csv_path=PIPELINE_CSV,
        max_create=10,
        write_log=False,
        logs_dir=tmp_path / "logs",
    )
    assert metrics.exit_code == 0
    assert metrics.added_count == 3
    assert metrics.error_count == 0
    assert metrics.would_create_count == 0
    assert settings.resolved_sqlite_path().is_file()

    store = SqliteOpportunityStore(settings.resolved_sqlite_path())
    keys = store.load_existing_keys()
    assert len(keys.opportunity_ids) == 3

    export_path = tmp_path / "export.csv"
    n = store.export_csv(export_path)
    assert n == 3
    with export_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3
    assert "OpportunityID" in rows[0]
    assert "Link" in rows[0]


def test_write_second_run_all_duplicates_increments_streak(
    settings: Settings, tmp_path: Path
):
    run_pipeline(
        settings,
        write=True,
        csv_path=PIPELINE_CSV,
        write_log=False,
        logs_dir=tmp_path / "logs",
    )
    m2 = run_pipeline(
        settings,
        write=True,
        csv_path=PIPELINE_CSV,
        write_log=False,
        logs_dir=tmp_path / "logs",
    )
    assert m2.added_count == 0
    assert m2.skipped_duplicate_count == 3
    assert m2.consecutive_zero_new_days == 1
    # Reset after first run had adds; second is first zero day.
    assert m2.exit_code == 0


def test_zero_new_streak_notifies_at_threshold(settings: Settings, tmp_path: Path):
    settings = settings.model_copy(
        update={
            "zero_new_streak_threshold": 2,
            "teams_webhook_url": "https://example.com/hook",
        }
    )
    # Seed empty DB + two zero-add days via streak file path simulation:
    # First write with empty filtered would need empty candidates — use max_create
    # after already full store.
    run_pipeline(
        settings,
        write=True,
        csv_path=PIPELINE_CSV,
        write_log=False,
        logs_dir=tmp_path / "logs",
    )
    with patch("opportunity_ingest.pipeline.notify_ingest_alert", return_value=True) as n1:
        m1 = run_pipeline(
            settings,
            write=True,
            csv_path=PIPELINE_CSV,
            write_log=False,
            logs_dir=tmp_path / "logs",
        )
    assert m1.consecutive_zero_new_days == 1
    assert m1.notified is False
    n1.assert_not_called()

    with patch("opportunity_ingest.pipeline.notify_ingest_alert", return_value=True) as n2:
        m2 = run_pipeline(
            settings,
            write=True,
            csv_path=PIPELINE_CSV,
            write_log=False,
            logs_dir=tmp_path / "logs",
        )
    assert m2.consecutive_zero_new_days == 2
    assert m2.notified is True
    assert m2.notify_reason == "zero_new_streak"
    n2.assert_called_once()
    assert n2.call_args.kwargs["reason"] == "zero_new_streak"


def test_hard_fail_missing_csv(settings: Settings, tmp_path: Path):
    with patch("opportunity_ingest.pipeline.notify_ingest_alert", return_value=False):
        metrics = run_pipeline(
            settings,
            write=False,
            csv_path=tmp_path / "nope.csv",
            write_log=False,
            logs_dir=tmp_path / "logs",
        )
    assert metrics.exit_code == 1
    assert metrics.hard_fail is True
    assert metrics.notify_reason == "hard_fail"


def test_dry_run_with_existing_loads_keys(settings: Settings, tmp_path: Path):
    run_pipeline(
        settings,
        write=True,
        csv_path=PIPELINE_CSV,
        max_create=1,
        write_log=False,
        logs_dir=tmp_path / "logs",
    )
    metrics = run_pipeline(
        settings,
        write=False,
        with_existing=True,
        csv_path=PIPELINE_CSV,
        write_log=False,
        logs_dir=tmp_path / "logs",
    )
    assert metrics.exit_code == 0
    # 1 already in store → skipped dup; 2 would create (if budget unlimited)
    assert metrics.skipped_duplicate_count == 1
    assert metrics.would_create_count == 2


def test_cli_run_dry_run_offline(tmp_path: Path, monkeypatch):
    db = tmp_path / "data" / "db.sqlite"
    state = tmp_path / "state" / "zero_new_streak.json"
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setenv("KEYWORDS_PATH", str(KEYWORDS))
    monkeypatch.setenv("STATE_PATH", str(state))
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)

    code = main(["run", "--csv", str(PIPELINE_CSV), "--max-create", "5"])
    assert code == 0
    assert not db.is_file()


def test_cli_run_write_offline(tmp_path: Path, monkeypatch):
    db = tmp_path / "data" / "db.sqlite"
    state = tmp_path / "state" / "zero_new_streak.json"
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setenv("KEYWORDS_PATH", str(KEYWORDS))
    monkeypatch.setenv("STATE_PATH", str(state))
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)

    code = main(
        ["run", "--write", "--csv", str(PIPELINE_CSV), "--max-create", "10"]
    )
    assert code == 0
    assert db.is_file()
    store = SqliteOpportunityStore(db)
    assert len(store.load_existing_keys().opportunity_ids) == 3


def test_cli_check_store(tmp_path: Path, monkeypatch):
    db = tmp_path / "data" / "db.sqlite"
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    code = main(["check-store"])
    assert code == 0
    assert db.is_file()


def test_cli_export_csv(tmp_path: Path, monkeypatch):
    db = tmp_path / "data" / "db.sqlite"
    state = tmp_path / "state" / "s.json"
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KEYWORDS_PATH", str(KEYWORDS))
    monkeypatch.setenv("STATE_PATH", str(state))

    assert main(["run", "--write", "--csv", str(PIPELINE_CSV)]) == 0
    out = tmp_path / "out.csv"
    assert main(["export-csv", "--out", str(out)]) == 0
    assert out.is_file()
    text = out.read_text(encoding="utf-8-sig")
    assert "OpportunityID" in text
    assert "PW-PIPE-001" in text


def test_cli_export_csv_sharepoint_not_supported(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sharepoint")
    code = main(["export-csv", "--out", str(tmp_path / "x.csv")])
    assert code == 1


def test_run_log_written(settings: Settings, tmp_path: Path):
    logs = tmp_path / "logs"
    run_pipeline(
        settings,
        write=False,
        csv_path=PIPELINE_CSV,
        write_log=True,
        logs_dir=logs,
    )
    files = list(logs.glob("run-*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert "exit_code" in data
    assert "storage_backend" in data
    assert data["filtered_count"] == 3


def test_write_resets_streak_after_adds(settings: Settings, tmp_path: Path):
    # Force streak high then write with adds.
    from opportunity_ingest.state import ZeroNewStreakState, save_zero_new_streak

    save_zero_new_streak(
        settings.state_path, ZeroNewStreakState(consecutive_zero_new_days=5)
    )
    m = run_pipeline(
        settings,
        write=True,
        csv_path=PIPELINE_CSV,
        write_log=False,
        logs_dir=tmp_path / "logs",
    )
    assert m.added_count == 3
    assert m.consecutive_zero_new_days == 0
