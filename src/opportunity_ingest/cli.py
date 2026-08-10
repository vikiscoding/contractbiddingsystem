"""CLI entry point — frozen subcommand contract (stubs only for scaffold).

Commands (implemented in later PRs):
  python -m opportunity_ingest run [--write | --dry-run] [--csv PATH]
      [--max-create N] [--with-existing]
  python -m opportunity_ingest download-sample [--out PATH]
  python -m opportunity_ingest check-store
  python -m opportunity_ingest export-csv [--out PATH]
"""

from __future__ import annotations

import argparse
import sys


def _cmd_not_implemented(name: str) -> int:
    print(
        f"Command '{name}' is not implemented yet (scaffold only).",
        file=sys.stderr,
    )
    return 1


def _usage_error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    # Omit prog= so usage reflects the invoked name (module or console script).
    parser = argparse.ArgumentParser(
        description="CanadaBuys open tender → contract opportunities store",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run [--write | --dry-run] [--csv PATH] [--max-create N] [--with-existing]
    run_p = sub.add_parser("run", help="Download/filter/dedupe and optionally write opportunities")
    mode = run_p.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="Persist creates via configured storage backend",
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
        help="Create-attempt budget for this run (N>=1; 0=unlimited)",
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
    dl_p.add_argument("--out", dest="out_path", metavar="PATH", help="Output path for sample CSV")

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
        return _cmd_not_implemented("run")
    if args.command == "download-sample":
        return _cmd_not_implemented("download-sample")
    if args.command == "check-store":
        return _cmd_not_implemented("check-store")
    if args.command == "export-csv":
        return _cmd_not_implemented("export-csv")

    raise AssertionError(f"unhandled command: {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
