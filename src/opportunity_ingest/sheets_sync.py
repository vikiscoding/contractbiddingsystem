"""Sync SQLite opportunities to Google Sheets (service account + Sheets API).

Free path: full replace of one worksheet tab (default ``Ingest``).
Requires optional deps: ``pip install gspread google-auth``
(or ``pip install -e ".[sheets]"``).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from opportunity_ingest.storage.sqlite_store import SqliteOpportunityStore

logger = logging.getLogger(__name__)

DEFAULT_TAB = "Ingest"


class SheetsSyncError(Exception):
    """Raised when Google Sheets sync cannot complete."""


def _load_service_account_info(
    json_path: str | Path | None,
    json_inline: str | None,
) -> dict[str, Any]:
    """Load service account dict from file path or inline JSON string."""
    if json_inline and json_inline.strip():
        raw = json_inline.strip()
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SheetsSyncError(
                "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON"
            ) from exc
        if not isinstance(info, dict):
            raise SheetsSyncError("GOOGLE_SERVICE_ACCOUNT_JSON must be a JSON object")
        return info

    path_raw = json_path or os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not path_raw:
        raise SheetsSyncError(
            "Set GOOGLE_SERVICE_ACCOUNT_FILE (path to JSON key) "
            "or GOOGLE_SERVICE_ACCOUNT_JSON (inline JSON)"
        )
    path = Path(path_raw)
    if not path.is_file():
        raise SheetsSyncError(f"Service account file not found: {path}")
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SheetsSyncError(f"Cannot read service account JSON at {path}: {exc}") from exc
    if not isinstance(info, dict):
        raise SheetsSyncError("Service account file must contain a JSON object")
    return info


def _import_gspread():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise SheetsSyncError(
            "Google Sheets deps missing. Install with: "
            'pip install "gspread>=6.0" "google-auth>=2.0" '
            'or pip install -e ".[sheets]"'
        ) from exc
    return gspread, Credentials


def sync_sqlite_to_sheet(
    store: SqliteOpportunityStore,
    *,
    spreadsheet_id: str,
    worksheet_title: str = DEFAULT_TAB,
    service_account_file: str | Path | None = None,
    service_account_json: str | None = None,
) -> int:
    """Replace worksheet contents with all SQLite opportunity rows.

    Returns number of data rows written (excluding header).
    """
    if not spreadsheet_id or not spreadsheet_id.strip():
        raise SheetsSyncError("GOOGLE_SHEET_ID is required")

    gspread, Credentials = _import_gspread()
    info = _load_service_account_info(service_account_file, service_account_json)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id.strip())
    except Exception as exc:
        raise SheetsSyncError(
            f"Failed to open spreadsheet {spreadsheet_id!r}. "
            f"Share the sheet with the service account email as Editor. Detail: {exc}"
        ) from exc

    title = (worksheet_title or DEFAULT_TAB).strip() or DEFAULT_TAB
    try:
        try:
            worksheet = spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=20)
            logger.info("Created worksheet tab %r", title)
    except Exception as exc:
        raise SheetsSyncError(f"Cannot open/create worksheet {title!r}: {exc}") from exc

    store.health_check()
    rows = store.list_rows()
    headers = list(SqliteOpportunityStore.EXPORT_COLUMNS)
    values: list[list[Any]] = [headers]
    for row in rows:
        values.append([_cell(row.get(col)) for col in headers])

    try:
        worksheet.clear()
        # Batch update is one efficient API call for the full grid.
        worksheet.update(values, value_input_option="USER_ENTERED")
    except Exception as exc:
        raise SheetsSyncError(f"Failed to write sheet values: {exc}") from exc

    data_rows = len(rows)
    logger.info(
        "Synced %s rows to sheet %s tab %r",
        data_rows,
        spreadsheet_id,
        title,
    )
    return data_rows


def _cell(value: Any) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    return str(value)
