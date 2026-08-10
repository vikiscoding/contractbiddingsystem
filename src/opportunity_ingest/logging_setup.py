"""Logging configuration for opportunity_ingest."""

from __future__ import annotations

import logging
import os
import sys


def setup_logging(level: str | int | None = None) -> None:
    """Configure root logger for the package (idempotent for basicConfig).

    Level defaults to ``LOG_LEVEL`` env (INFO if unset).
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
            stream=sys.stderr,
        )
    else:
        root.setLevel(level)

    logging.getLogger("opportunity_ingest").setLevel(level)
