"""Minimal smoke tests so CI is green at scaffold."""

from opportunity_ingest import __version__
from opportunity_ingest.cli import build_parser, main


def test_package_version():
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
