"""Zero-new-day streak state (`state/zero_new_streak.json`).

Persisted across daily runs (GitHub Actions cache of ``state/``). Independent of
the opportunity store. Only updated on successful ``--write`` runs (not dry-run).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("state/zero_new_streak.json")


@dataclass(slots=True)
class ZeroNewStreakState:
    """Consecutive days with zero new creates (write runs only)."""

    consecutive_zero_new_days: int = 0

    def __post_init__(self) -> None:
        n = int(self.consecutive_zero_new_days)
        if n < 0:
            raise ValueError("consecutive_zero_new_days must be >= 0")
        self.consecutive_zero_new_days = n


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
    return ZeroNewStreakState(consecutive_zero_new_days=days)


def save_zero_new_streak(path: str | Path, state: ZeroNewStreakState) -> None:
    """Write streak state JSON (creates parent dirs)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info(
        "Saved zero-new streak: consecutive_zero_new_days=%s → %s",
        state.consecutive_zero_new_days,
        p,
    )


def update_streak_after_write(
    state: ZeroNewStreakState,
    *,
    added_count: int,
) -> ZeroNewStreakState:
    """Return new streak after a successful write run.

    * ``added_count > 0`` → reset to 0
    * ``added_count == 0`` → increment by 1
    """
    if added_count < 0:
        raise ValueError("added_count must be >= 0")
    if added_count > 0:
        return ZeroNewStreakState(consecutive_zero_new_days=0)
    return ZeroNewStreakState(
        consecutive_zero_new_days=state.consecutive_zero_new_days + 1
    )


def streak_meets_threshold(state: ZeroNewStreakState, threshold: int) -> bool:
    """True when consecutive zero-new days >= threshold (default threshold is 3)."""
    if threshold < 1:
        return False
    return state.consecutive_zero_new_days >= threshold
