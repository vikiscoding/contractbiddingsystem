"""CanadaBuys open tender opportunity ingestion pipeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("opportunity_ingest")
except PackageNotFoundError:  # pragma: no cover - editable/dev without install
    __version__ = "0.1.0"
