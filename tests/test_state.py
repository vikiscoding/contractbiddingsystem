"""Tests for zero-new streak state load/save/update."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opportunity_ingest.state import (
    ZeroNewStreakState,
    load_zero_new_streak,
    save_zero_new_streak,
    streak_meets_threshold,
    update_streak_after_write,
)


def test_default_state_is_zero():
    s = ZeroNewStreakState()
    assert s.consecutive_zero_new_days == 0


def test_state_rejects_negative():
    with pytest.raises(ValueError, match="consecutive_zero_new_days"):
        ZeroNewStreakState(consecutive_zero_new_days=-1)


def test_load_missing_file_returns_zero(tmp_path: Path):
    p = tmp_path / "missing" / "zero_new_streak.json"
    state = load_zero_new_streak(p)
    assert state.consecutive_zero_new_days == 0


def test_save_and_load_roundtrip(tmp_path: Path):
    p = tmp_path / "state" / "zero_new_streak.json"
    save_zero_new_streak(p, ZeroNewStreakState(consecutive_zero_new_days=3))
    assert p.is_file()
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw == {"consecutive_zero_new_days": 3}
    loaded = load_zero_new_streak(p)
    assert loaded.consecutive_zero_new_days == 3


def test_load_invalid_json_returns_zero(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not-json", encoding="utf-8")
    assert load_zero_new_streak(p).consecutive_zero_new_days == 0


def test_load_invalid_shape_returns_zero(tmp_path: Path):
    p = tmp_path / "list.json"
    p.write_text("[1,2,3]", encoding="utf-8")
    assert load_zero_new_streak(p).consecutive_zero_new_days == 0


def test_update_streak_increments_on_zero_adds():
    prior = ZeroNewStreakState(consecutive_zero_new_days=2)
    nxt = update_streak_after_write(prior, added_count=0)
    assert nxt.consecutive_zero_new_days == 3


def test_update_streak_resets_on_positive_adds():
    prior = ZeroNewStreakState(consecutive_zero_new_days=5)
    nxt = update_streak_after_write(prior, added_count=2)
    assert nxt.consecutive_zero_new_days == 0


def test_update_streak_rejects_negative_adds():
    with pytest.raises(ValueError, match="added_count"):
        update_streak_after_write(ZeroNewStreakState(), added_count=-1)


def test_streak_meets_threshold_default_3():
    assert streak_meets_threshold(ZeroNewStreakState(2), 3) is False
    assert streak_meets_threshold(ZeroNewStreakState(3), 3) is True
    assert streak_meets_threshold(ZeroNewStreakState(4), 3) is True


def test_streak_threshold_below_one_never_notifies():
    assert streak_meets_threshold(ZeroNewStreakState(10), 0) is False
