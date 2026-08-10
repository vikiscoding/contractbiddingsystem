"""Minimal smoke tests so CI is green at scaffold."""

import pytest

from opportunity_ingest import __version__
from opportunity_ingest.cli import build_parser, main


def test_package_version():
    # Single source of truth is pyproject.toml via importlib.metadata when installed.
    assert __version__  # non-empty
    assert __version__ == "0.1.0"


def test_import_opportunity_ingest():
    import opportunity_ingest  # noqa: F401


def test_cli_parser_has_frozen_subcommands():
    parser = build_parser()
    # Subparsers live on the last action that is a subparsers action.
    subparsers_actions = [
        a
        for a in parser._actions
        if getattr(a, "choices", None) is not None and a.dest == "command"
    ]
    assert len(subparsers_actions) == 1
    choices = set(subparsers_actions[0].choices.keys())
    assert choices == {"run", "download-sample", "check-store", "export-csv"}


def test_cli_help_exits_cleanly():
    # argparse --help exits with SystemExit(0)
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected SystemExit from --help")


def test_cli_run_stub_returns_not_implemented():
    code = main(["run", "--dry-run"])
    assert code == 1


def test_cli_remaining_subcommands_stub_return_1():
    # download-sample is implemented in this PR; others remain stubs.
    assert main(["run"]) == 1
    assert main(["check-store"]) == 1
    assert main(["export-csv"]) == 1


def test_write_and_dry_run_are_mutually_exclusive():
    with pytest.raises(SystemExit) as exc_info:
        main(["run", "--write", "--dry-run"])
    assert exc_info.value.code == 2


def test_run_options_parse_onto_expected_destinations():
    args = build_parser().parse_args(
        ["run", "--csv", "f.csv", "--max-create", "3", "--with-existing"]
    )
    assert args.command == "run"
    assert args.csv_path == "f.csv"
    assert args.max_create == 3
    assert args.with_existing is True
    assert args.write is False
    assert args.dry_run is False


def test_with_existing_rejected_with_write():
    code = main(["run", "--write", "--with-existing"])
    assert code == 2


def test_max_create_negative_rejected():
    code = main(["run", "--max-create", "-1"])
    assert code == 2


def test_max_create_zero_allowed_as_unlimited_stub():
    # 0 = unlimited per design; stub still returns not-implemented.
    code = main(["run", "--max-create", "0"])
    assert code == 1
