"""CLI entry point — frozen subcommand contract.

Commands:
  python -m opportunity_ingest run [--write | --dry-run] [--csv PATH]
      [--max-create N] [--with-existing]
  python -m opportunity_ingest download-sample [--out PATH]
  python -m opportunity_ingest check-store
  python -m opportunity_ingest export-csv [--out PATH]
  python -m opportunity_ingest sync-sheets [--sheet-id ID] [--tab NAME]
  python -m opportunity_ingest interpret-rank [options] [--sync-sheets]
  python -m opportunity_ingest sync-rank-sheets [--from-json PATH] [--tab NAME]

Write gating: only ``--write`` persists. ``DRY_RUN`` env never enables write and
does not disable ``--write``. Default (neither flag) is dry-run.

``interpret-rank`` is post-ingest only: it never updates store Status/Notes/scores.
Grok rankings may full-replace a separate Google Sheet tab (default ``Ranked``),
never the opportunity ``Ingest`` tab.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opportunity_ingest.config import Settings, get_settings
from opportunity_ingest.download import DEFAULT_SAMPLE_PATH, DownloadError, download_to_path
from opportunity_ingest.exit_codes import EXIT_FAILURE, EXIT_USAGE
from opportunity_ingest.interpret_rank import (
    DEFAULT_BATCH_SIZE,
    InterpretRankError,
    run_interpret_rank,
)
from opportunity_ingest.logging_setup import setup_logging
from opportunity_ingest.notify import (
    dispatch_match_notifications,
    match_items_from_ranked,
)
from opportunity_ingest.pipeline import resolve_write_mode, run_pipeline
from opportunity_ingest.sheets_sync import (
    DEFAULT_RANK_TAB,
    SheetsSyncError,
    find_latest_rankings_json,
    load_rankings_json,
    sync_rankings_to_sheet,
    sync_sqlite_to_sheet,
)
from opportunity_ingest.storage.base import StoreError
from opportunity_ingest.storage.factory import build_store
from opportunity_ingest.storage.sqlite_store import SqliteOpportunityStore


def _usage_error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return EXIT_USAGE


def cmd_download_sample(out_path: str | None) -> int:
    """Download CanadaBuys open tender CSV to path (default data/sample-...)."""
    setup_logging()
    try:
        path = download_to_path(out_path if out_path is not None else DEFAULT_SAMPLE_PATH)
    except DownloadError as exc:
        print(f"error: download failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    print(f"Wrote {path}")
    return 0


def cmd_run(
    args: argparse.Namespace,
    settings: Settings | None = None,
) -> int:
    """Run the full ingest pipeline (dry-run default; ``--write`` persists)."""
    try:
        settings = settings or get_settings()
    except Exception as exc:  # pydantic ValidationError for bad MAX_CREATE, etc.
        print(f"error: invalid settings: {exc}", file=sys.stderr)
        return EXIT_USAGE

    setup_logging(settings.log_level)

    write = resolve_write_mode(
        write_flag=bool(args.write),
        dry_run_flag=bool(args.dry_run),
        dry_run_env=bool(settings.dry_run),
    )
    # --with-existing is dry-run only (validated in main before call).
    with_existing = bool(args.with_existing) and not write

    max_create = args.max_create
    if max_create is None:
        max_create = settings.max_create
    # Env-sourced negative should already fail Settings validation; belt-and-suspenders.
    if max_create is not None and max_create < 0:
        return _usage_error(
            f"MAX_CREATE/--max-create must be >= 0 (0=unlimited); got {max_create}"
        )

    metrics = run_pipeline(
        settings,
        write=write,
        csv_path=args.csv_path,
        max_create=max_create,
        with_existing=with_existing,
    )

    mode = "write" if write else "dry-run"
    print(
        f"[{mode}] parsed={metrics.parsed_count} filtered={metrics.filtered_count} "
        f"mapped={metrics.mapped_count} "
        f"added={metrics.added_count} would_create={metrics.would_create_count} "
        f"errors={metrics.error_count} skipped_dup={metrics.skipped_duplicate_count} "
        f"skipped_max={metrics.skipped_max_create_count} "
        f"streak={metrics.consecutive_zero_new_days} "
        f"exit={metrics.exit_code} notified={metrics.notified} "
        f"match_notified={metrics.match_notified} "
        f"slack_match_notified={metrics.slack_match_notified} "
        f"match_count={metrics.match_notify_count}"
    )
    if metrics.hard_fail and metrics.hard_fail_reason:
        print(f"error: {metrics.hard_fail_reason}", file=sys.stderr)
    return int(metrics.exit_code)


def cmd_check_store(settings: Settings | None = None) -> int:
    """Health-check backend + sample key load (backend-neutral)."""
    try:
        settings = settings or get_settings()
    except Exception as exc:
        print(f"error: invalid settings: {exc}", file=sys.stderr)
        return EXIT_USAGE
    setup_logging(settings.log_level)
    try:
        store = build_store(settings)
    except (ValueError, NotImplementedError) as exc:
        print(f"error: store config: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    try:
        store.health_check()
        keys = store.load_existing_keys()
    except StoreError as exc:
        print(f"error: store health check failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    print(
        f"ok backend={store.name} "
        f"opportunity_ids={len(keys.opportunity_ids)} "
        f"links={len(keys.links)}"
    )
    return 0


def cmd_export_csv(
    out_path: str | None,
    settings: Settings | None = None,
) -> int:
    """Dump opportunities to CSV for human review (primary path: sqlite).

    SharePoint export is not supported in this release; use STORAGE_BACKEND=sqlite
    or query Graph separately when activated.
    """
    try:
        settings = settings or get_settings()
    except Exception as exc:
        print(f"error: invalid settings: {exc}", file=sys.stderr)
        return EXIT_USAGE
    setup_logging(settings.log_level)

    backend = (settings.storage_backend or "sqlite").strip().lower()
    if backend != "sqlite":
        print(
            f"error: export-csv is supported for STORAGE_BACKEND=sqlite only "
            f"(current={backend!r}). SharePoint export is not implemented; "
            f"export from sqlite or use Graph tooling when SP is activated.",
            file=sys.stderr,
        )
        return EXIT_FAILURE

    try:
        store = build_store(settings)
    except (ValueError, NotImplementedError) as exc:
        print(f"error: store config: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    if not isinstance(store, SqliteOpportunityStore):
        print(
            "error: export-csv requires SqliteOpportunityStore",
            file=sys.stderr,
        )
        return EXIT_FAILURE

    out = Path(out_path) if out_path else settings.data_dir / "export-opportunities.csv"
    try:
        store.health_check()
        count = store.export_csv(out)
    except StoreError as exc:
        print(f"error: export failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except OSError as exc:
        print(f"error: cannot write CSV {out}: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    print(f"Wrote {count} rows to {out}")
    return 0


def cmd_sync_sheets(
    sheet_id: str | None,
    tab: str | None,
    settings: Settings | None = None,
) -> int:
    """Full-replace a Google Sheets tab from SQLite (service account)."""
    try:
        settings = settings or get_settings()
    except Exception as exc:
        print(f"error: invalid settings: {exc}", file=sys.stderr)
        return EXIT_USAGE
    setup_logging(settings.log_level)

    backend = (settings.storage_backend or "sqlite").strip().lower()
    if backend != "sqlite":
        print(
            "error: sync-sheets requires STORAGE_BACKEND=sqlite "
            f"(current={backend!r})",
            file=sys.stderr,
        )
        return EXIT_FAILURE

    resolved_id = (sheet_id or settings.google_sheet_id or "").strip()
    resolved_tab = (tab or settings.google_sheet_tab or "Ingest").strip()
    if not resolved_id:
        print(
            "error: set --sheet-id or GOOGLE_SHEET_ID",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        store = build_store(settings)
    except (ValueError, NotImplementedError) as exc:
        print(f"error: store config: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    if not isinstance(store, SqliteOpportunityStore):
        print("error: sync-sheets requires SqliteOpportunityStore", file=sys.stderr)
        return EXIT_FAILURE

    sa_file = settings.google_service_account_file
    sa_json = settings.google_service_account_json
    try:
        count = sync_sqlite_to_sheet(
            store,
            spreadsheet_id=resolved_id,
            worksheet_title=resolved_tab,
            service_account_file=sa_file,
            service_account_json=sa_json,
        )
    except SheetsSyncError as exc:
        print(f"error: sheets sync failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except StoreError as exc:
        print(f"error: store failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    print(f"Synced {count} rows to sheet {resolved_id} tab {resolved_tab!r}")
    return 0


def _resolve_rank_sheet_sync(
    args: argparse.Namespace,
    settings: Settings,
) -> bool:
    """Whether to push rankings to Google Sheets.

    ``--sync-sheets`` forces on; ``--no-sync-sheets`` forces off.
    Default (neither flag): on when GOOGLE_SHEET_ID is configured.
    """
    if getattr(args, "no_sync_sheets", False):
        return False
    if getattr(args, "sync_sheets", False):
        return True
    return bool((settings.google_sheet_id or "").strip())


def _push_rankings_to_sheet(
    *,
    ranked_rows: list[dict[str, object]],
    run_id: str,
    model: str,
    settings: Settings,
    sheet_id: str | None,
    rank_tab: str | None,
) -> tuple[int, str, str]:
    """Sync rankings; return (count, spreadsheet_id, tab). Raises SheetsSyncError."""
    resolved_id = (sheet_id or settings.google_sheet_id or "").strip()
    if not resolved_id:
        raise SheetsSyncError("set --sheet-id or GOOGLE_SHEET_ID")
    resolved_tab = (
        (rank_tab or settings.google_sheet_rank_tab or DEFAULT_RANK_TAB).strip()
        or DEFAULT_RANK_TAB
    )
    count = sync_rankings_to_sheet(
        ranked_rows,
        run_id=run_id,
        model=model,
        spreadsheet_id=resolved_id,
        worksheet_title=resolved_tab,
        service_account_file=settings.google_service_account_file,
        service_account_json=settings.google_service_account_json,
    )
    return count, resolved_id, resolved_tab


def cmd_interpret_rank(
    args: argparse.Namespace,
    settings: Settings | None = None,
) -> int:
    """Grok rephrase + fit-rank stored opportunities (report only; no store mutate)."""
    try:
        settings = settings or get_settings()
    except Exception as exc:
        print(f"error: invalid settings: {exc}", file=sys.stderr)
        return EXIT_USAGE
    setup_logging(settings.log_level)

    backend = (settings.storage_backend or "sqlite").strip().lower()
    if backend != "sqlite":
        print(
            "error: interpret-rank requires STORAGE_BACKEND=sqlite "
            f"(current={backend!r})",
            file=sys.stderr,
        )
        return EXIT_FAILURE

    api_key = (settings.xai_api_key or "").strip()
    if not api_key:
        print(
            "error: set XAI_API_KEY for interpret-rank "
            '(and pip install -e ".[ai]")',
            file=sys.stderr,
        )
        return EXIT_USAGE

    objectives_path = Path(args.objectives) if args.objectives else settings.objectives_path
    out_dir = (
        Path(args.out_dir)
        if args.out_dir
        else settings.data_dir / "rankings"
    )
    limit = args.limit
    if limit is not None and limit < 0:
        return _usage_error("--limit must be >= 0")
    min_score = args.min_score
    if min_score is not None and min_score < 0:
        return _usage_error("--min-score must be >= 0")
    batch_size = args.batch_size if args.batch_size is not None else DEFAULT_BATCH_SIZE
    if batch_size < 1:
        return _usage_error("--batch-size must be >= 1")

    try:
        store = build_store(settings)
    except (ValueError, NotImplementedError) as exc:
        print(f"error: store config: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    if not isinstance(store, SqliteOpportunityStore):
        print("error: interpret-rank requires SqliteOpportunityStore", file=sys.stderr)
        return EXIT_FAILURE

    try:
        store.health_check()
        rows = store.list_rows()
    except StoreError as exc:
        print(f"error: store failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    status = (args.status or "").strip() or None
    try:
        result = run_interpret_rank(
            rows,
            objectives_path=objectives_path,
            api_key=api_key,
            base_url=settings.xai_base_url,
            model=settings.xai_model,
            out_dir=out_dir,
            status=status,
            limit=limit,
            min_rule_score=min_score,
            batch_size=batch_size,
        )
    except InterpretRankError as exc:
        print(f"error: interpret-rank failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    top = result.ranked[0] if result.ranked else None
    print(
        f"interpret-rank model={result.model} input={result.input_count} "
        f"ranked={len(result.ranked)} run_id={result.run_id}"
    )
    if top:
        print(
            f"top #{top.rank} fit={top.fit_score} rec={top.recommendation} "
            f"id={top.opportunity_id} title={top.title[:80]}"
        )
    if result.markdown_path:
        print(f"Wrote {result.markdown_path}")
    if result.json_path:
        print(f"Wrote {result.json_path}")

    if _resolve_rank_sheet_sync(args, settings):
        try:
            count, sid, tab = _push_rankings_to_sheet(
                ranked_rows=[r.as_dict() for r in result.ranked],
                run_id=result.run_id,
                model=result.model,
                settings=settings,
                sheet_id=getattr(args, "sheet_id", None),
                rank_tab=getattr(args, "rank_tab", None),
            )
        except SheetsSyncError as exc:
            print(f"error: rank sheets sync failed: {exc}", file=sys.stderr)
            return EXIT_FAILURE
        print(f"Synced {count} ranking rows to sheet {sid} tab {tab!r}")

    # Teams + Slack capture pings for Grok fits at/above threshold (default 40).
    skip_chat = bool(getattr(args, "no_teams", False))
    if (
        not skip_chat
        and (
            settings.teams_match_notify_enabled or settings.slack_match_notify_enabled
        )
    ):
        thr = int(settings.teams_match_score_threshold)
        match_items = match_items_from_ranked(result.ranked, threshold=thr)
        dispatched = dispatch_match_notifications(
            match_items,
            threshold=thr,
            source="interpret-rank",
            run_url=settings.github_run_url,
            sheets_url=settings.resolved_google_sheet_url(),
            sheets_tab=settings.google_sheet_rank_tab or "Ranked",
            max_items=int(settings.teams_match_max_items),
            teams_webhook_url=settings.resolved_match_webhook_url(),
            teams_enabled=bool(settings.teams_match_notify_enabled),
            slack_bot_token=settings.resolved_slack_bot_token(),
            slack_channel_id=settings.resolved_slack_channel_id(),
            slack_webhook_url=settings.resolved_slack_match_webhook_url(),
            slack_enabled=bool(settings.slack_match_notify_enabled),
        )
        print(
            f"match_notify teams={dispatched.teams_posted} "
            f"slack={dispatched.slack_posted} "
            f"above_threshold={dispatched.match_count} threshold={thr}"
        )
    return 0


def cmd_sync_rank_sheets(
    args: argparse.Namespace,
    settings: Settings | None = None,
) -> int:
    """Push an existing interpret-rank JSON report to the Ranked Google Sheet tab."""
    try:
        settings = settings or get_settings()
    except Exception as exc:
        print(f"error: invalid settings: {exc}", file=sys.stderr)
        return EXIT_USAGE
    setup_logging(settings.log_level)

    from_json = Path(args.from_json) if args.from_json else None
    if from_json is None:
        latest = find_latest_rankings_json(settings.data_dir / "rankings")
        if latest is None:
            print(
                "error: no interpret-*.json under data/rankings; "
                "run interpret-rank first or pass --from-json",
                file=sys.stderr,
            )
            return EXIT_USAGE
        from_json = latest
        print(f"Using latest rankings file {from_json}")

    try:
        run_id, model, ranked = load_rankings_json(from_json)
        count, sid, tab = _push_rankings_to_sheet(
            ranked_rows=ranked,
            run_id=run_id,
            model=model,
            settings=settings,
            sheet_id=args.sheet_id,
            rank_tab=args.rank_tab,
        )
    except SheetsSyncError as exc:
        print(f"error: rank sheets sync failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    print(f"Synced {count} ranking rows to sheet {sid} tab {tab!r}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    # Omit prog= so usage reflects the invoked name (module or console script).
    parser = argparse.ArgumentParser(
        description=(
            "CanadaBuys open tender → contract opportunities store. "
            "Only --write persists; DRY_RUN env does not enable or block writes."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run [--write | --dry-run] [--csv PATH] [--max-create N] [--with-existing]
    run_p = sub.add_parser(
        "run",
        help=(
            "Download/filter/dedupe and optionally write opportunities "
            "(default dry-run; only --write persists)"
        ),
    )
    mode = run_p.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="Persist creates via configured storage backend (only way to write)",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (no writes); default when neither flag is set",
    )
    run_p.add_argument("--csv", dest="csv_path", metavar="PATH", help="Offline CSV path")
    run_p.add_argument(
        "--max-create",
        type=int,
        metavar="N",
        help=(
            "Create-attempt budget for this run "
            "(N>=1; 0=unlimited; default from MAX_CREATE env, package default 50)"
        ),
    )
    run_p.add_argument(
        "--with-existing",
        action="store_true",
        help="Dry-run only: load existing keys from store if available",
    )

    # download-sample [--out PATH]
    dl_p = sub.add_parser(
        "download-sample",
        help="Download a sample open-tender CSV for local fixtures",
    )
    dl_p.add_argument(
        "--out",
        dest="out_path",
        metavar="PATH",
        default=None,
        help=f"Output path for sample CSV (default: {DEFAULT_SAMPLE_PATH})",
    )

    # check-store
    sub.add_parser(
        "check-store",
        help="Health-check the configured storage backend",
    )

    # export-csv [--out PATH]
    exp_p = sub.add_parser(
        "export-csv",
        help="Export stored opportunities to CSV for human review",
    )
    exp_p.add_argument("--out", dest="out_path", metavar="PATH", help="Output CSV path")

    # sync-sheets [--sheet-id ID] [--tab NAME]
    sh_p = sub.add_parser(
        "sync-sheets",
        help=(
            "Full-replace a Google Sheets tab from SQLite "
            "(service account; requires gspread/google-auth)"
        ),
    )
    sh_p.add_argument(
        "--sheet-id",
        dest="sheet_id",
        metavar="ID",
        default=None,
        help="Spreadsheet ID (default: GOOGLE_SHEET_ID env)",
    )
    sh_p.add_argument(
        "--tab",
        dest="tab",
        metavar="NAME",
        default=None,
        help="Worksheet tab name to replace (default: Ingest / GOOGLE_SHEET_TAB)",
    )

    # interpret-rank — Grok rephrase + fit ranking (report only)
    ir_p = sub.add_parser(
        "interpret-rank",
        help=(
            "Grok-assisted plain-English rewrite + rank stored opportunities "
            "against config/objectives.yaml (writes reports; does not mutate store)"
        ),
    )
    ir_p.add_argument(
        "--objectives",
        dest="objectives",
        metavar="PATH",
        default=None,
        help="Company objectives YAML (default: OBJECTIVES_PATH / config/objectives.yaml)",
    )
    ir_p.add_argument(
        "--out-dir",
        dest="out_dir",
        metavar="DIR",
        default=None,
        help="Directory for JSON/Markdown reports (default: data/rankings)",
    )
    ir_p.add_argument(
        "--status",
        dest="status",
        metavar="STATUS",
        default=None,
        help="Only interpret rows with this Status (e.g. New)",
    )
    ir_p.add_argument(
        "--limit",
        dest="limit",
        type=int,
        metavar="N",
        default=None,
        help="Max opportunities to send to Grok (after sort by rule score)",
    )
    ir_p.add_argument(
        "--min-score",
        dest="min_score",
        type=int,
        metavar="N",
        default=None,
        help="Only rows with rule RelevanceScore >= N",
    )
    ir_p.add_argument(
        "--batch-size",
        dest="batch_size",
        type=int,
        metavar="N",
        default=None,
        help=f"Opportunities per Grok call (default {DEFAULT_BATCH_SIZE})",
    )
    ir_sync = ir_p.add_mutually_exclusive_group()
    ir_sync.add_argument(
        "--sync-sheets",
        dest="sync_sheets",
        action="store_true",
        help=(
            "Full-replace Google Sheet Ranked tab after ranking "
            "(default when GOOGLE_SHEET_ID is set)"
        ),
    )
    ir_sync.add_argument(
        "--no-sync-sheets",
        dest="no_sync_sheets",
        action="store_true",
        help="Do not push rankings to Google Sheets even if GOOGLE_SHEET_ID is set",
    )
    ir_p.add_argument(
        "--sheet-id",
        dest="sheet_id",
        metavar="ID",
        default=None,
        help="Spreadsheet ID for rank sync (default: GOOGLE_SHEET_ID)",
    )
    ir_p.add_argument(
        "--rank-tab",
        dest="rank_tab",
        metavar="NAME",
        default=None,
        help="Rankings worksheet tab (default: Ranked / GOOGLE_SHEET_RANK_TAB)",
    )
    ir_p.add_argument(
        "--no-teams",
        dest="no_teams",
        action="store_true",
        help="Skip Teams high-match capture ping after ranking",
    )

    # sync-rank-sheets — push existing ranking JSON without re-calling Grok
    srs_p = sub.add_parser(
        "sync-rank-sheets",
        help=(
            "Full-replace Google Sheet Ranked tab from an interpret-rank JSON "
            "(latest under data/rankings or --from-json); does not call Grok"
        ),
    )
    srs_p.add_argument(
        "--from-json",
        dest="from_json",
        metavar="PATH",
        default=None,
        help="Path to interpret-*.json (default: newest in data/rankings)",
    )
    srs_p.add_argument(
        "--sheet-id",
        dest="sheet_id",
        metavar="ID",
        default=None,
        help="Spreadsheet ID (default: GOOGLE_SHEET_ID env)",
    )
    srs_p.add_argument(
        "--rank-tab",
        dest="rank_tab",
        metavar="NAME",
        default=None,
        help=f"Worksheet tab to replace (default: {DEFAULT_RANK_TAB} / GOOGLE_SHEET_RANK_TAB)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        # --with-existing is dry-run only (design contract).
        if args.write and args.with_existing:
            return _usage_error("--with-existing is only valid with dry-run (not --write)")
        # N >= 1 = attempt budget; 0 = unlimited; negatives are invalid.
        if args.max_create is not None and args.max_create < 0:
            return _usage_error("--max-create must be >= 0 (0=unlimited)")
        return cmd_run(args)
    if args.command == "download-sample":
        return cmd_download_sample(args.out_path)
    if args.command == "check-store":
        return cmd_check_store()
    if args.command == "export-csv":
        return cmd_export_csv(args.out_path)
    if args.command == "sync-sheets":
        return cmd_sync_sheets(args.sheet_id, args.tab)
    if args.command == "interpret-rank":
        return cmd_interpret_rank(args)
    if args.command == "sync-rank-sheets":
        return cmd_sync_rank_sheets(args)

    raise AssertionError(f"unhandled command: {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
