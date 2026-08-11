"""End-to-end ingest pipeline: download → parse → filter → score → map → store.

Orchestrates OpportunityStore creates under ``MAX_CREATE`` attempt budget,
zero-new streak updates, Teams notify, and exit-code matrix.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
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
from opportunity_ingest.notify import (
    match_items_from_opportunity_fields,
    notify_ingest_alert,
    notify_match_alerts,
)
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
    match_notified: bool = False
    match_notify_count: int = 0
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
    dry_run_env: bool = False,
) -> bool:
    """Return True only when ``--write`` is set.

    Write gating:
    - Only ``--write`` enables persistence.
    - ``DRY_RUN`` env never enables write alone and never disables ``--write``.
    - Default (neither CLI flag) is dry-run.
    """
    if dry_run_env:
        logger.debug(
            "DRY_RUN env is set but does not change write gating "
            "(only --write persists; --write is not blocked by DRY_RUN)"
        )
    if write_flag:
        return True
    if dry_run_flag:
        return False
    return False


def _validate_max_create(max_create: int | None) -> int | None:
    """Ensure max_create is None or >= 0 before AttemptBudget (env + CLI defense)."""
    if max_create is None:
        return None
    n = int(max_create)
    if n < 0:
        raise PipelineHardFail(
            "max_create",
            f"max_create must be >= 0 (0=unlimited); got {n}",
        )
    return n


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
) -> dict[str, Any]:
    """Dedupe + create loop. On dry-run, counts would-create without store writes.

    Write path also returns ``created``: list of successfully created OpportunityFields
    (for Teams high-match pings).
    """
    added = 0
    errors = 0
    skipped_dup = 0
    skipped_max = 0
    would_create = 0
    attempts = 0
    created: list[OpportunityFields] = []

    for fields in candidates:
        if is_duplicate(fields.OpportunityID, fields.Link, keys):
            skipped_dup += 1
            continue
        if not budget.can_attempt():
            skipped_max += 1
            continue

        if not write:
            # Dry-run: count as would-create / attempt without calling store.create.
            if not budget.consume():
                skipped_max += 1
                continue
            attempts += 1
            would_create += 1
            # Register so intra-run dups are skipped (mirrors write path).
            register_created(keys, fields.OpportunityID, fields.Link)
            continue

        if store is None:
            logger.error(
                "Write path missing store for OpportunityID=%s; treating as error",
                fields.OpportunityID,
            )
            if not budget.consume():
                skipped_max += 1
                continue
            attempts += 1
            errors += 1
            continue

        if not budget.consume():
            skipped_max += 1
            continue
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
            created.append(fields)
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
        "created": created,
    }


def write_run_log(metrics: RunMetrics, logs_dir: str | Path = "logs") -> Path:
    """Write ``logs/run-<utc-timestamp>.json`` and return its path.

    Filename includes microseconds to avoid same-second overwrites.
    """
    out_dir = Path(logs_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = out_dir / f"run-{ts}.json"
    path.write_text(
        json.dumps(metrics.to_log_dict(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    logger.info("Wrote run log %s", path)
    return path


def _best_effort_load_streak(settings: Settings, metrics: RunMetrics) -> None:
    """Load on-disk streak into metrics without saving (observability)."""
    try:
        current = load_zero_new_streak(settings.state_path)
        metrics.consecutive_zero_new_days = current.consecutive_zero_new_days
    except Exception as exc:  # noqa: BLE001 — never fail run for observability
        logger.warning("Could not load streak for metrics: %s", exc)


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
    today: date | None = None,
) -> RunMetrics:
    """Execute one ingest run. Never raises for soft create errors.

    Hard failures set ``metrics.hard_fail`` and return (caller still applies notify
    + exit). Unexpected exceptions propagate.

    ``today``: optional UTC date override for calendar-day streak (tests).
    """
    resolved_max = max_create if max_create is not None else settings.max_create
    metrics = RunMetrics(
        dry_run=not write,
        write=write,
        with_existing=with_existing,
        storage_backend=(settings.storage_backend or "sqlite"),
        max_create=resolved_max,
        zero_new_streak_threshold=settings.zero_new_streak_threshold,
    )

    try:
        metrics.max_create = _validate_max_create(metrics.max_create)

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

        try:
            budget = AttemptBudget(max_create=metrics.max_create)
        except ValueError as exc:
            # Defense in depth if a non-Settings caller passes a bad value.
            raise PipelineHardFail("max_create", str(exc)) from exc

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
        created_fields: list[OpportunityFields] = list(stats.get("created") or [])

        # Streak: write runs only (UTC calendar-day semantics).
        streak_reached = False
        streak_day = today if today is not None else datetime.now(UTC).date()
        if write:
            prior = load_zero_new_streak(settings.state_path)
            new_state = update_streak_after_write(
                prior,
                added_count=metrics.added_count,
                today=streak_day,
            )
            try:
                save_zero_new_streak(settings.state_path, new_state)
            except OSError as exc:
                # Soft-continue: creates already applied; keep exit matrix.
                logger.error(
                    "Failed to save zero-new streak state (%s): %s",
                    settings.state_path,
                    exc,
                )
                metrics.extra["streak_save_error"] = str(exc)
            metrics.consecutive_zero_new_days = new_state.consecutive_zero_new_days
            streak_reached = streak_meets_threshold(
                new_state, settings.zero_new_streak_threshold
            )
        else:
            # Report current streak for observability without mutating.
            _best_effort_load_streak(settings, metrics)

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

        # High-match capture pings (new creates only; dry-run never posts).
        if write and created_fields and settings.teams_match_notify_enabled:
            thr = int(settings.teams_match_score_threshold)
            match_items = match_items_from_opportunity_fields(
                created_fields, threshold=thr
            )
            metrics.match_notify_count = len(match_items)
            if match_items:
                metrics.match_notified = notify_match_alerts(
                    settings.resolved_match_webhook_url(),
                    match_items,
                    threshold=thr,
                    source="ingest",
                    run_url=settings.github_run_url,
                    max_items=int(settings.teams_match_max_items),
                    enabled=True,
                )

        logger.info(
            "Run complete: write=%s added=%s errors=%s would_create=%s "
            "skipped_dup=%s skipped_max=%s exit=%s notified=%s "
            "match_notified=%s match_count=%s",
            write,
            metrics.added_count,
            metrics.error_count,
            metrics.would_create_count,
            metrics.skipped_duplicate_count,
            metrics.skipped_max_create_count,
            metrics.exit_code,
            metrics.notified,
            metrics.match_notified,
            metrics.match_notify_count,
        )

    except PipelineHardFail as exc:
        logger.error("Hard fail (%s): %s", exc.reason, exc.message)
        metrics.hard_fail = True
        metrics.hard_fail_reason = f"{exc.reason}: {exc.message}"
        metrics.exit_code = EXIT_FAILURE
        metrics.notify_reason = "hard_fail"
        # Observability: report on-disk streak even when run failed early.
        _best_effort_load_streak(settings, metrics)
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
