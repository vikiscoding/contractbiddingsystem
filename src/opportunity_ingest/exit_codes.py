"""Exit-code matrix and notify decisions for the ingest pipeline.

Normative matrix (design):

| Condition                                      | Exit | Notify (Python)          |
|------------------------------------------------|------|--------------------------|
| CLI usage error                                | 2    | no                       |
| Hard fail (download/parse/config/store health) | 1    | yes                      |
| Unhandled crash                                | 1    | maybe not (Actions backup)|
| All creates OK, adds > 0                       | 0    | no                       |
| All creates OK, adds == 0                      | 0    | if zero-streak ≥ thresh  |
| Soft partial errors (error_count < N)          | 0    | no                       |
| error_count >= PARTIAL_ERROR_EXIT_THRESHOLD    | 1    | yes                      |
| Dry-run (no hard fail)                         | 0    | no                       |
"""

from __future__ import annotations

from dataclasses import dataclass

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

DEFAULT_PARTIAL_ERROR_THRESHOLD = 5


@dataclass(frozen=True, slots=True)
class ExitDecision:
    """Resolved exit code + whether Python should notify Teams."""

    exit_code: int
    should_notify: bool
    notify_reason: str | None = None


def resolve_exit_code(
    *,
    hard_fail: bool,
    error_count: int,
    partial_error_threshold: int = DEFAULT_PARTIAL_ERROR_THRESHOLD,
) -> int:
    """Return process exit code for a completed (or hard-failed) run.

    Dry-run does not change the matrix: only hard_fail / error_count matter.
    Callers still skip streak updates and soft notifies on dry-run separately.
    """
    if hard_fail:
        return EXIT_FAILURE
    threshold = max(1, int(partial_error_threshold))
    if int(error_count) >= threshold:
        return EXIT_FAILURE
    return EXIT_OK


def resolve_exit_decision(
    *,
    hard_fail: bool,
    error_count: int,
    partial_error_threshold: int = DEFAULT_PARTIAL_ERROR_THRESHOLD,
    dry_run: bool = False,
    zero_new_streak_reached: bool = False,
) -> ExitDecision:
    """Full exit + notify decision for a run.

    Notify rules:
    - hard fail → yes (``hard_fail``), even on dry-run
    - error_count >= threshold → yes (``partial_errors``); dry-run never has create errors
    - zero-new streak ≥ threshold after write with adds==0 → yes (``zero_new_streak``)
    - soft partial / success with adds → no
    - dry-run success → no (streak notify skipped)
    """
    exit_code = resolve_exit_code(
        hard_fail=hard_fail,
        error_count=error_count,
        partial_error_threshold=partial_error_threshold,
    )

    if hard_fail:
        return ExitDecision(
            exit_code=exit_code,
            should_notify=True,
            notify_reason="hard_fail",
        )

    threshold = max(1, int(partial_error_threshold))
    if int(error_count) >= threshold:
        return ExitDecision(
            exit_code=exit_code,
            should_notify=True,
            notify_reason="partial_errors",
        )

    if not dry_run and zero_new_streak_reached:
        return ExitDecision(
            exit_code=exit_code,
            should_notify=True,
            notify_reason="zero_new_streak",
        )

    return ExitDecision(exit_code=exit_code, should_notify=False, notify_reason=None)
