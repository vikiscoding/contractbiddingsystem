"""End-to-end ingest pipeline: download → parse → filter → score → map → store.

Orchestrates OpportunityStore creates under ``MAX_CREATE`` attempt budget,
zero-new streak updates, Teams notify, and exit-code matrix.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opportunity_ingest.config import Settings
from opportunity_ingest.download import DownloadError, download_csv_text
from opportunity_ingest.exit_codes import (
    EXIT_FAILURE,
    EXIT_OK,
    resolve_exit_decision,
)
from opportunity_ingest.filter_keywords import (
    KeywordConfigError,
    filter_tenders,
    load_keyword_config,
)
from opportunity_ingest.map_fields import MapError, map_to_opportunity_fields
from opportunity_ingest.models import ExistingKeys, OpportunityFields
from opportunity_ingest.notify import notify_ingest_alert
from opportunity_ingest.parse import ParseError, parse_csv_file, parse_csv_text
from opportunity_ingest.score import compute_score
from opportunity_ingest.state import (
    load_zero_new_streak,
    save_zero_new_streak,
    streak_meets_threshold,
    update_streak_after_write,
)
from opportunity_ingest.storage.base import (
    AttemptBudget,
    OpportunityStore,
    SkipDuplicate,
    StoreError,
    StoreWriteError,
    is_duplicate,
    register_created,
)
from opportunity_ingest.storage.factory import build_store

logger = logging.getLogger(__name__)
UTC = timezone.utc


@dataclass(slots=True)
class RunMetrics:
    """Aggregate counts for one pipeline run (also written to logs/run-*.json)."""

    parsed_count: int = 0
    filtered_count: int = 0
    mapped_count: int = 0
    map_error_count: int = 0
    would_create_count: int = 0
    added_count: int = 0
    error_count: int = 0
    skipped_duplicate_count: int = 0
    skipped_max_create_count: int = 0
    create_attempts: int = 0
    dry_run: bool = True
    write: bool = False
    with_existing: bool = False
    storage_backend: str = "sqlite"
    max_create: int | None = None
    consecutive_zero_new_days: int = 0
    zero_new_streak_threshold: int = 3
    hard_fail: bool = False
    hard_fail_reason: str | None = None
    exit_code: int = EXIT_OK
    notified: bool = False
    notify_reason: str | None = None
    csv_source: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_log_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class PipelineHardFail(Exception):
    """Download / parse / config / store health failure (exit 1 + notify)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def resolve_write_mode(
    *,
    write_flag: bool,
    dry_run_flag: bool,
    dry_run_env: bool,
) -> bool:
    """Return True only when ``--write`` is set.

    ``DRY_RUN`` env never enables write alone. Default (neither flag) is dry-run.
    ``dry_run_env`` is accepted for logging/compatibility only.
    """
    del dry_run_env  # never enables write; documented for callers
    if write_flag:
        return True
    if dry_run_flag:
        return False
    return False


def _load_tenders(
    *,
    csv_path: str | Path | None,
    settings: Settings,
) -> tuple[list[Any], str]:
    """Download or read CSV and parse to TenderRecords. Returns (records, source label)."""
    if csv_path is not None:
        path = Path(csv_path)
        if not path.is_file():
            raise PipelineHardFail(
                "csv_missing",
                f"CSV path does not exist: {path}",
            )
        try:
            records = parse_csv_file(path)
        except ParseError as exc:
            raise PipelineHardFail("parse", str(exc)) from exc
        except OSError as exc:
            raise PipelineHardFail("csv_read", f"Cannot read CSV {path}: {exc}") from exc
        return records, str(path)

    try:
        text = download_csv_text(
            url=settings.canadabuys_csv_url,
            timeout=settings.http_timeout_seconds,
        )
        records = parse_csv_text(text)
    except DownloadError as exc:
        raise PipelineHardFail("download", str(exc)) from exc
    except ParseError as exc:
        raise PipelineHardFail("parse", str(exc)) from exc
    return records, settings.canadabuys_csv_url or "canadabuys_default_url"


def _build_candidates(
    records: list[Any],
    settings: Settings,
) -> tuple[list[OpportunityFields], int, int]:
    """Filter → score → map. Returns (candidates, filtered_count, map_error_count)."""
    try:
        kw_config = load_keyword_config(settings.keywords_path)
    except KeywordConfigError as exc:
        raise PipelineHardFail("keywords", str(exc)) from exc

    matched = filter_tenders(records, kw_config)
    candidates: list[OpportunityFields] = []
    map_errors = 0
    for tender, match in matched:
        score = compute_score(tender, match, kw_config.category_boosts)
        try:
            fields = map_to_opportunity_fields(tender, match, score)
        except MapError as exc:
            map_errors += 1
            logger.warning("Map skip: %s", exc)
            continue
        candidates.append(fields)

    # Prefer higher relevance when MAX_CREATE caps attempts.
    candidates.sort(key=lambda f: (-int(f.RelevanceScore), f.OpportunityID))
    return candidates, len(matched), map_errors


def _process_candidates(
    candidates: list[OpportunityFields],
    *,
    store: OpportunityStore | None,
    keys: ExistingKeys,
    budget: AttemptBudget,
    write: bool,
) -> dict[str, int]:
    """Dedupe + create loop. On dry-run, counts would-create without store writes."""
    added = 0
    errors = 0
    skipped_dup = 0
    skipped_max = 0
    would_create = 0
    attempts = 0

    for fields in candidates:
        if is_duplicate(fields.OpportunityID, fields.Link, keys):
            skipped_dup += 1
            continue
        if not budget.can_attempt():
            skipped_max += 1
            continue

        if not write:
            # Dry-run: count as would-create / attempt without calling store.create.
            assert budget.consume()
            attempts += 1
            would_create += 1
            # Register so intra-run dups are skipped (mirrors write path).
            register_created(keys, fields.OpportunityID, fields.Link)
            continue

        assert store is not None
        assert budget.consume()
        attempts += 1
        try:
            store.create(fields)
        except SkipDuplicate as exc:
            skipped_dup += 1
            logger.info(
                "SkipDuplicate for %s: %s",
                fields.OpportunityID,
                exc,
            )
        except StoreWriteError as exc:
            errors += 1
            logger.error(
                "StoreWriteError for %s: %s",
                fields.OpportunityID,
                exc,
            )
        else:
            register_created(keys, fields.OpportunityID, fields.Link)
            added += 1
            logger.info(
                "Created opportunity %s (score=%s)",
                fields.OpportunityID,
                fields.RelevanceScore,
            )

    return {
        "added": added,
        "errors": errors,
        "skipped_duplicate": skipped_dup,
        "skipped_max_create": skipped_max,
        "would_create": would_create,
        "attempts": attempts,
    }


def write_run_log(metrics: RunMetrics, logs_dir: str | Path = "logs") -> Path:
    """Write ``logs/run-<utc-timestamp>.json`` and return its path."""
    out_dir = Path(logs_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"run-{ts}.json"
    path.write_text(
        json.dumps(metrics.to_log_dict(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    logger.info("Wrote run log %s", path)
    return path


def run_pipeline(
    settings: Settings,
    *,
    write: bool,
    csv_path: str | Path | None = None,
    max_create: int | None = None,
    with_existing: bool = False,
    store: OpportunityStore | None = None,
    logs_dir: str | Path = "logs",
    write_log: bool = True,
) -> RunMetrics:
    """Execute one ingest run. Never raises for soft create errors.

    Hard failures set ``metrics.hard_fail`` and return (caller still applies notify
    + exit). Unexpected exceptions propagate.
    """
    metrics = RunMetrics(
        dry_run=not write,
        write=write,
        with_existing=with_existing,
        storage_backend=(settings.storage_backend or "sqlite"),
        max_create=max_create if max_create is not None else settings.max_create,
        zero_new_streak_threshold=settings.zero_new_streak_threshold,
    )

    try:
        records, source = _load_tenders(csv_path=csv_path, settings=settings)
        metrics.csv_source = source
        metrics.parsed_count = len(records)
        logger.info("Parsed %s tenders from %s", metrics.parsed_count, source)

        candidates, filtered_count, map_errors = _build_candidates(records, settings)
        metrics.filtered_count = filtered_count
        metrics.mapped_count = len(candidates)
        metrics.map_error_count = map_errors
        logger.info(
            "Filtered=%s mapped=%s map_errors=%s",
            filtered_count,
            len(candidates),
            map_errors,
        )

        # Store access: write always; dry-run only with --with-existing.
        active_store = store
        keys = ExistingKeys.empty()
        if write or with_existing:
            if active_store is None:
                try:
                    active_store = build_store(settings)
                except (ValueError, NotImplementedError) as exc:
                    raise PipelineHardFail("store_config", str(exc)) from exc
            try:
                active_store.health_check()
                keys = active_store.load_existing_keys()
            except StoreError as exc:
                raise PipelineHardFail("store_health", str(exc)) from exc
            logger.info(
                "Loaded existing keys: ids=%s links=%s (backend=%s)",
                len(keys.opportunity_ids),
                len(keys.links),
                active_store.name,
            )
            metrics.storage_backend = active_store.name

        budget = AttemptBudget(max_create=metrics.max_create)
        stats = _process_candidates(
            candidates,
            store=active_store if write else None,
            keys=keys,
            budget=budget,
            write=write,
        )
        metrics.added_count = stats["added"]
        metrics.error_count = stats["errors"]
        metrics.skipped_duplicate_count = stats["skipped_duplicate"]
        metrics.skipped_max_create_count = stats["skipped_max_create"]
        metrics.would_create_count = stats["would_create"]
        metrics.create_attempts = stats["attempts"]

        # Streak: write runs only.
        streak_reached = False
        if write:
            prior = load_zero_new_streak(settings.state_path)
            new_state = update_streak_after_write(
                prior, added_count=metrics.added_count
            )
            save_zero_new_streak(settings.state_path, new_state)
            metrics.consecutive_zero_new_days = new_state.consecutive_zero_new_days
            streak_reached = streak_meets_threshold(
                new_state, settings.zero_new_streak_threshold
            )
        else:
            # Report current streak for observability without mutating.
            current = load_zero_new_streak(settings.state_path)
            metrics.consecutive_zero_new_days = current.consecutive_zero_new_days

        decision = resolve_exit_decision(
            hard_fail=False,
            error_count=metrics.error_count,
            partial_error_threshold=settings.partial_error_exit_threshold,
            dry_run=not write,
            zero_new_streak_reached=streak_reached,
        )
        metrics.exit_code = decision.exit_code
        metrics.notify_reason = decision.notify_reason

        if decision.should_notify:
            extra = [
                {"title": "Added", "value": str(metrics.added_count)},
                {"title": "Errors", "value": str(metrics.error_count)},
                {
                    "title": "Zero-new streak",
                    "value": str(metrics.consecutive_zero_new_days),
                },
            ]
            metrics.notified = notify_ingest_alert(
                settings.teams_webhook_url,
                reason=decision.notify_reason or "unknown",
                run_url=settings.github_run_url,
                storage_backend=metrics.storage_backend,
                extra_facts=extra,
            )

        logger.info(
            "Run complete: write=%s added=%s errors=%s would_create=%s "
            "skipped_dup=%s skipped_max=%s exit=%s notified=%s",
            write,
            metrics.added_count,
            metrics.error_count,
            metrics.would_create_count,
            metrics.skipped_duplicate_count,
            metrics.skipped_max_create_count,
            metrics.exit_code,
            metrics.notified,
        )

    except PipelineHardFail as exc:
        logger.error("Hard fail (%s): %s", exc.reason, exc.message)
        metrics.hard_fail = True
        metrics.hard_fail_reason = f"{exc.reason}: {exc.message}"
        metrics.exit_code = EXIT_FAILURE
        metrics.notify_reason = "hard_fail"
        metrics.notified = notify_ingest_alert(
            settings.teams_webhook_url,
            reason="hard_fail",
            run_url=settings.github_run_url,
            storage_backend=metrics.storage_backend,
            extra_facts=[
                {"title": "Detail", "value": exc.message[:500]},
                {"title": "Kind", "value": exc.reason},
            ],
        )

    if write_log:
        try:
            write_run_log(metrics, logs_dir=logs_dir)
        except OSError as exc:
            logger.warning("Could not write run log: %s", exc)

    return metrics
