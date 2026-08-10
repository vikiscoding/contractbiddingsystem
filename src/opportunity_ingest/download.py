"""Download CanadaBuys open tender notice CSV (UTF-8 BOM, one retry).

Retry policy: one retry on transport/HTTP failures **and** on content sanity
failures (empty body, HTML-looking body), then hard-fail with ``DownloadError``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CSV_URL = (
    "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv"
)
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_SAMPLE_PATH = Path("data/sample-openTenderNotice.csv")
_UTF8_BOM = b"\xef\xbb\xbf"


class DownloadError(Exception):
    """Raised when the CanadaBuys CSV cannot be downloaded or fails sanity checks."""


def _resolve_url(url: str | None) -> str:
    if url:
        return url
    return os.environ.get("CANADABUYS_CSV_URL", DEFAULT_CSV_URL)


def _resolve_timeout(timeout: float | None) -> float:
    if timeout is not None:
        return timeout
    raw = os.environ.get("HTTP_TIMEOUT_SECONDS")
    if raw:
        try:
            return float(raw)
        except ValueError as exc:
            raise DownloadError(
                f"Invalid HTTP_TIMEOUT_SECONDS value: {raw!r} (expected a number)"
            ) from exc
    return DEFAULT_TIMEOUT_SECONDS


def _sanity_check_content(content: bytes) -> None:
    if not content or not content.strip():
        raise DownloadError("Downloaded CSV is empty")
    # Strip leading BOM then whitespace so BOM-prefixed HTML error pages are caught.
    head = content.removeprefix(_UTF8_BOM).lstrip()[:200].lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        raise DownloadError("Downloaded content looks like HTML, not CSV")


def download_csv_bytes(
    url: str | None = None,
    *,
    timeout: float | None = None,
    client: httpx.Client | None = None,
) -> bytes:
    """GET open-tender CSV bytes. One retry on failure (transport or content), then raise.

    Decodes as UTF-8 with BOM only when writing text; raw bytes preserve BOM for
    ``utf-8-sig`` consumers.
    """
    resolved_url = _resolve_url(url)
    resolved_timeout = _resolve_timeout(timeout)
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=resolved_timeout, follow_redirects=True)

    assert client is not None
    last_exc: Exception | None = None
    try:
        for attempt in range(2):  # initial try + one retry
            try:
                logger.info(
                    "Downloading CanadaBuys CSV (attempt %s/2): %s",
                    attempt + 1,
                    resolved_url,
                )
                response = client.get(resolved_url)
                response.raise_for_status()
                content = response.content
                _sanity_check_content(content)
                logger.info("Downloaded %s bytes", len(content))
                return content
            except Exception as exc:  # network / HTTP / content sanity
                last_exc = exc
                logger.warning(
                    "Download attempt %s/2 failed: %s",
                    attempt + 1,
                    exc,
                )
                if attempt == 0:
                    continue
                break
    finally:
        if owns_client:
            client.close()

    if isinstance(last_exc, DownloadError):
        raise DownloadError(f"Failed to download CSV after retry: {last_exc}") from last_exc
    raise DownloadError(f"Failed to download CSV after retry: {last_exc}") from last_exc


def download_csv_text(
    url: str | None = None,
    *,
    timeout: float | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Download CSV and decode as utf-8-sig (strips BOM)."""
    raw = download_csv_bytes(url, timeout=timeout, client=client)
    return raw.decode("utf-8-sig")


def download_to_path(
    path: str | Path | None = None,
    url: str | None = None,
    *,
    timeout: float | None = None,
    client: httpx.Client | None = None,
) -> Path:
    """Download CSV to ``path`` (default ``data/sample-openTenderNotice.csv``).

    Writes bytes as received (typically UTF-8 with BOM). Parent dirs are created.
    """
    out = Path(path) if path is not None else DEFAULT_SAMPLE_PATH
    content = download_csv_bytes(url, timeout=timeout, client=client)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    logger.info("Wrote sample CSV to %s (%s bytes)", out, len(content))
    return out
