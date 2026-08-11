"""CLI entry point — frozen subcommand contract.

Commands:
  python -m opportunity_ingest run [--write | --dry-run] [--csv PATH]
      [--max-create N] [--with-existing]
  python -m opportunity_ingest download-sample [--out PATH]
  python -m opportunity_ingest check-store
  python -m opportunity_ingest export-csv [--out PATH]
  python -m opportunity_ingest sync-sheets [--sheet-id ID] [--tab NAME]

Write gating: only ``--write`` persists. ``DRY_RUN`` env never enables write and
does not disable ``--write``. Default (neither flag) is dry-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opportunity_ingest.config import Settings, get_settings
from opportunity_ingest.download import DEFAULT_SAMPLE_PATH, DownloadError, download_to_path
from opportunity_ingest.exit_codes import EXIT_FAILURE, EXIT_USAGE
from opportunity_ingest.logging_setup import setup_logging
from opportunity_ingest.pipeline import resolve_write_mode, run_pipeline
from opportunity_ingest.sheets_sync import SheetsSyncError, sync_sqlite_to_sheet
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
        f"exit={metrics.exit_code} notified={metrics.notified}"
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

    raise AssertionError(f"unhandled command: {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
