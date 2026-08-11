"""Zero-new-day streak state (`state/zero_new_streak.json`).

Persisted across daily runs (GitHub Actions cache of ``state/``). Independent of
the opportunity store. Only updated on successful ``--write`` runs (not dry-run).

Semantics are **calendar-day based** (UTC): consecutive days with zero new
creates. Same-day re-runs (e.g. workflow_dispatch) do not double-count.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("state/zero_new_streak.json")
UTC = timezone.utc


@dataclass(slots=True)
class ZeroNewStreakState:
    """Consecutive UTC calendar days with zero new creates (write runs only)."""

    consecutive_zero_new_days: int = 0
    # ISO date (YYYY-MM-DD) of last write run that counted toward a zero-new day.
    last_zero_new_date: str | None = None

    def __post_init__(self) -> None:
        n = int(self.consecutive_zero_new_days)
        if n < 0:
            raise ValueError("consecutive_zero_new_days must be >= 0")
        self.consecutive_zero_new_days = n
        if self.last_zero_new_date is not None:
            self.last_zero_new_date = str(self.last_zero_new_date).strip() or None


def load_zero_new_streak(path: str | Path) -> ZeroNewStreakState:
    """Load streak state from JSON; missing/invalid file → zero streak."""
    p = Path(path)
    if not p.is_file():
        logger.info("Streak state file missing (%s); starting at 0", p)
        return ZeroNewStreakState(consecutive_zero_new_days=0)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read streak state %s (%s); starting at 0", p, exc)
        return ZeroNewStreakState(consecutive_zero_new_days=0)

    if not isinstance(raw, dict):
        logger.warning("Streak state root is not an object in %s; starting at 0", p)
        return ZeroNewStreakState(consecutive_zero_new_days=0)

    try:
        days = int(raw.get("consecutive_zero_new_days", 0))
    except (TypeError, ValueError):
        logger.warning("Invalid consecutive_zero_new_days in %s; starting at 0", p)
        return ZeroNewStreakState(consecutive_zero_new_days=0)

    if days < 0:
        days = 0

    last_date = raw.get("last_zero_new_date")
    last_s: str | None
    if last_date is None or last_date == "":
        last_s = None
    else:
        last_s = str(last_date).strip() or None

    return ZeroNewStreakState(
        consecutive_zero_new_days=days,
        last_zero_new_date=last_s,
    )


def save_zero_new_streak(path: str | Path, state: ZeroNewStreakState) -> None:
    """Write streak state JSON (creates parent dirs).

    Raises ``OSError`` on I/O failure (callers may catch and soft-continue).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info(
        "Saved zero-new streak: consecutive_zero_new_days=%s last_zero_new_date=%s → %s",
        state.consecutive_zero_new_days,
        state.last_zero_new_date,
        p,
    )


def update_streak_after_write(
    state: ZeroNewStreakState,
    *,
    added_count: int,
    today: date | None = None,
) -> ZeroNewStreakState:
    """Return new streak after a successful write run (UTC calendar-day aware).

    * ``added_count > 0`` → reset to 0 (clear last zero-new date)
    * ``added_count == 0`` on a **new** UTC calendar day → increment by 1
    * ``added_count == 0`` on the **same** UTC day as ``last_zero_new_date`` →
      no increment (same-day re-run / workflow_dispatch)
    """
    if added_count < 0:
        raise ValueError("added_count must be >= 0")
    if today is None:
        today = datetime.now(UTC).date()
    today_s = today.isoformat()

    if added_count > 0:
        return ZeroNewStreakState(
            consecutive_zero_new_days=0,
            last_zero_new_date=None,
        )

    if state.last_zero_new_date == today_s:
        # Same calendar day: keep count (do not double-count re-runs).
        return ZeroNewStreakState(
            consecutive_zero_new_days=state.consecutive_zero_new_days,
            last_zero_new_date=today_s,
        )

    return ZeroNewStreakState(
        consecutive_zero_new_days=state.consecutive_zero_new_days + 1,
        last_zero_new_date=today_s,
    )


def streak_meets_threshold(state: ZeroNewStreakState, threshold: int) -> bool:
    """True when consecutive zero-new days >= threshold (default threshold is 3)."""
    if threshold < 1:
        return False
    return state.consecutive_zero_new_days >= threshold
