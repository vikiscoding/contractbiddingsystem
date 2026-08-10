"""Allow `python -m opportunity_ingest` entry point."""

from opportunity_ingest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
