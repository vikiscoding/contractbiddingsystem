"""Tests for exit-code matrix and notify decisions."""

from __future__ import annotations

from opportunity_ingest.exit_codes import (
    EXIT_FAILURE,
    EXIT_OK,
    resolve_exit_code,
    resolve_exit_decision,
)


def test_hard_fail_exits_1_and_notifies():
    d = resolve_exit_decision(hard_fail=True, error_count=0)
    assert d.exit_code == EXIT_FAILURE
    assert d.should_notify is True
    assert d.notify_reason == "hard_fail"


def test_all_ok_with_adds_exit_0_no_notify():
    d = resolve_exit_decision(
        hard_fail=False,
        error_count=0,
        dry_run=False,
        zero_new_streak_reached=False,
    )
    assert d.exit_code == EXIT_OK
    assert d.should_notify is False


def test_zero_adds_streak_notify_exit_0():
    d = resolve_exit_decision(
        hard_fail=False,
        error_count=0,
        dry_run=False,
        zero_new_streak_reached=True,
    )
    assert d.exit_code == EXIT_OK
    assert d.should_notify is True
    assert d.notify_reason == "zero_new_streak"


def test_soft_partial_errors_exit_0_no_notify():
    d = resolve_exit_decision(
        hard_fail=False,
        error_count=4,
        partial_error_threshold=5,
        dry_run=False,
    )
    assert d.exit_code == EXIT_OK
    assert d.should_notify is False


def test_high_partial_errors_exit_1_and_notify():
    d = resolve_exit_decision(
        hard_fail=False,
        error_count=5,
        partial_error_threshold=5,
        dry_run=False,
    )
    assert d.exit_code == EXIT_FAILURE
    assert d.should_notify is True
    assert d.notify_reason == "partial_errors"


def test_error_count_above_threshold():
    assert resolve_exit_code(hard_fail=False, error_count=10, partial_error_threshold=5) == 1


def test_dry_run_success_no_notify_even_if_streak_flag():
    # Streak is not updated on dry-run; callers pass zero_new_streak_reached=False.
    # Even if True, dry_run suppresses streak notify.
    d = resolve_exit_decision(
        hard_fail=False,
        error_count=0,
        dry_run=True,
        zero_new_streak_reached=True,
    )
    assert d.exit_code == EXIT_OK
    assert d.should_notify is False


def test_hard_fail_notifies_even_on_dry_run():
    d = resolve_exit_decision(hard_fail=True, error_count=0, dry_run=True)
    assert d.exit_code == EXIT_FAILURE
    assert d.should_notify is True
    assert d.notify_reason == "hard_fail"


def test_partial_errors_take_priority_over_streak():
    d = resolve_exit_decision(
        hard_fail=False,
        error_count=5,
        partial_error_threshold=5,
        dry_run=False,
        zero_new_streak_reached=True,
    )
    assert d.notify_reason == "partial_errors"
    assert d.exit_code == EXIT_FAILURE
