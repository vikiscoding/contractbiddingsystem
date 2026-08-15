"""Sync SQLite opportunities and Grok rankings to Google Sheets.

Free path: full replace of worksheet tabs via service account + Sheets API.
- ``Ingest`` (default): opportunity rows from SQLite
- ``Ranked`` (default for interpret-rank): Grok fit-rank report (separate tab)

Requires optional deps: ``pip install gspread google-auth``
(or ``pip install -e ".[sheets]"``).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from opportunity_ingest.storage.sqlite_store import SqliteOpportunityStore

logger = logging.getLogger(__name__)

DEFAULT_TAB = "Ingest"
DEFAULT_RANK_TAB = "Ranked"

# Columns written to the Ranked tab (full replace each interpret-rank sync).
RANKING_EXPORT_COLUMNS: tuple[str, ...] = (
    "RunId",
    "Model",
    "Rank",
    "FitScore",
    "Recommendation",
    "Title",
    "OpportunityID",
    "Buyer",
    "ClosingDate",
    "KeywordsMatched",
    "RuleRelevanceScore",
    "MatchedObjectives",
    "PlainEnglish",
    "InterpretedObjective",
    "WhyItFits",
    "RisksOrMismatches",
    "NextAction",
    "Link",
)


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


def _open_spreadsheet(
    spreadsheet_id: str,
    *,
    service_account_file: str | Path | None = None,
    service_account_json: str | None = None,
):
    """Authorize and open a spreadsheet by id. Returns (gspread_module, spreadsheet)."""
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
    return gspread, spreadsheet


def _get_or_create_worksheet(spreadsheet: Any, title: str, *, cols: int = 20) -> Any:
    gspread, _ = _import_gspread()
    try:
        try:
            return spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=cols)
            logger.info("Created worksheet tab %r", title)
            return worksheet
    except Exception as exc:
        raise SheetsSyncError(f"Cannot open/create worksheet {title!r}: {exc}") from exc


def _replace_worksheet_values(worksheet: Any, values: list[list[Any]]) -> None:
    try:
        worksheet.clear()
        # Batch update is one efficient API call for the full grid.
        worksheet.update(values, value_input_option="USER_ENTERED")
    except Exception as exc:
        raise SheetsSyncError(f"Failed to write sheet values: {exc}") from exc


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
    gspread_mod, spreadsheet = _open_spreadsheet(
        spreadsheet_id,
        service_account_file=service_account_file,
        service_account_json=service_account_json,
    )
    del gspread_mod  # only needed for WorksheetNotFound inside helper

    title = (worksheet_title or DEFAULT_TAB).strip() or DEFAULT_TAB
    worksheet = _get_or_create_worksheet(
        spreadsheet, title, cols=max(20, len(SqliteOpportunityStore.EXPORT_COLUMNS))
    )

    store.health_check()
    rows = store.list_rows()
    headers = list(SqliteOpportunityStore.EXPORT_COLUMNS)
    values: list[list[Any]] = [headers]
    for row in rows:
        values.append([_cell(row.get(col)) for col in headers])

    _replace_worksheet_values(worksheet, values)

    data_rows = len(rows)
    logger.info(
        "Synced %s opportunity rows to sheet %s tab %r",
        data_rows,
        spreadsheet_id,
        title,
    )
    return data_rows


def rankings_to_sheet_values(
    ranked_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    model: str,
) -> list[list[Any]]:
    """Build header + data grid for the Ranked tab from ranked dicts."""
    headers = list(RANKING_EXPORT_COLUMNS)
    values: list[list[Any]] = [headers]
    for row in ranked_rows:
        matched = row.get("matched_objectives")
        if isinstance(matched, list):
            matched_s = ", ".join(str(x) for x in matched)
        else:
            matched_s = matched or ""
        values.append(
            [
                _cell(run_id),
                _cell(model),
                _cell(row.get("rank")),
                _cell(row.get("fit_score")),
                _cell(row.get("recommendation")),
                _cell(row.get("title")),
                _cell(row.get("opportunity_id")),
                _cell(row.get("buyer")),
                _cell(row.get("closing_date")),
                _cell(row.get("keywords_matched")),
                _cell(row.get("rule_relevance_score")),
                _cell(matched_s),
                _cell(row.get("plain_english")),
                _cell(row.get("interpreted_objective")),
                _cell(row.get("why_it_fits")),
                _cell(row.get("risks_or_mismatches")),
                _cell(row.get("next_action")),
                _cell(row.get("link")),
            ]
        )
    return values


def sync_rankings_to_sheet(
    ranked_rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    model: str,
    spreadsheet_id: str,
    worksheet_title: str = DEFAULT_RANK_TAB,
    service_account_file: str | Path | None = None,
    service_account_json: str | None = None,
) -> int:
    """Full-replace the Ranked tab with Grok interpret-rank output.

    **Never** targets the opportunity ``Ingest`` tab (refused).
    Returns number of data rows written (excluding header).
    """
    title = (worksheet_title or DEFAULT_RANK_TAB).strip() or DEFAULT_RANK_TAB
    if title.lower() == DEFAULT_TAB.lower():
        raise SheetsSyncError(
            f"Refusing to write Grok rankings to the {DEFAULT_TAB!r} tab "
            f"(opportunity view). Use {DEFAULT_RANK_TAB!r} or another tab name."
        )

    _gspread, spreadsheet = _open_spreadsheet(
        spreadsheet_id,
        service_account_file=service_account_file,
        service_account_json=service_account_json,
    )
    worksheet = _get_or_create_worksheet(
        spreadsheet, title, cols=max(20, len(RANKING_EXPORT_COLUMNS))
    )
    values = rankings_to_sheet_values(ranked_rows, run_id=run_id, model=model)
    _replace_worksheet_values(worksheet, values)

    data_rows = max(0, len(values) - 1)
    logger.info(
        "Synced %s ranking rows to sheet %s tab %r (run_id=%s)",
        data_rows,
        spreadsheet_id,
        title,
        run_id,
    )
    return data_rows


def load_rankings_json(path: str | Path) -> tuple[str, str, list[dict[str, Any]]]:
    """Load interpret-rank JSON report → (run_id, model, ranked list)."""
    p = Path(path)
    if not p.is_file():
        raise SheetsSyncError(f"Rankings JSON not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SheetsSyncError(f"Cannot read rankings JSON {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise SheetsSyncError("Rankings JSON root must be an object")
    run_id = str(data.get("run_id") or p.stem)
    model = str(data.get("model") or "")
    ranked = data.get("ranked")
    if not isinstance(ranked, list):
        raise SheetsSyncError("Rankings JSON missing ranked[] array")
    rows: list[dict[str, Any]] = []
    for item in ranked:
        if isinstance(item, dict):
            rows.append(item)
    return run_id, model, rows


def find_latest_rankings_json(directory: str | Path) -> Path | None:
    """Return newest ``interpret-*.json`` under directory, or None."""
    d = Path(directory)
    if not d.is_dir():
        return None
    files = sorted(d.glob("interpret-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _cell(value: Any) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return str(value)
