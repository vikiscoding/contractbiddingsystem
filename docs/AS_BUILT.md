# As-built architecture (Phase 1)

**Source of truth for the implemented system.** Supersedes design-doc details when they differ.

| Field | Value |
|-------|--------|
| Status | Implemented and manually exercised (Windows, 2026-08-10) |
| Package | `opportunity_ingest` |
| Python | 3.11+ (verified on 3.14 in local venv) |

---

## 1. Pipeline

```text
CanadaBuys CSV
    → download (UA headers, 1 retry)
    → parse (bilingual headers, EN/FR coalesce)
    → filter_keywords (any-match; short terms word-boundary; span-aware nested suppress)
    → score (0–100, UTC)
    → map_fields (OpportunityFields)
    → load_existing_keys (store)
    → for each new candidate while attempts < MAX_CREATE:
          store.create()
    → streak state (write runs)
    → optional Teams notify
    → exit code matrix
    → optional: export-csv | sync-sheets
```

---

## 2. Components

| Module | Path | Responsibility |
|--------|------|----------------|
| CLI | `cli.py` | `run`, `download-sample`, `check-store`, `export-csv`, `sync-sheets` |
| Pipeline | `pipeline.py` | Orchestration, metrics, run logs |
| Download | `download.py` | HTTP GET + DEFAULT_HEADERS (anti-403) |
| Parse | `parse.py` | HEADER_CANDIDATES, TenderRecord |
| Filter | `filter_keywords.py` | keywords.yaml load + match |
| Score | `score.py` | Rule-based RelevanceScore |
| Map | `map_fields.py` | Schema mapping, Link required |
| Config | `config.py` | pydantic-settings / `.env` |
| State | `state.py` | zero-new streak |
| Notify | `notify.py` | Teams Workflows Adaptive Card + GITHUB_OUTPUT |
| Exit | `exit_codes.py` | Exit + notify decisions |
| Sheets | `sheets_sync.py` | Full tab replace via gspread |
| Store protocol | `storage/base.py` | `OpportunityStore` |
| Factory | `storage/factory.py` | `sqlite` \| `sharepoint` |
| SQLite | `storage/sqlite_store.py` | Default backend, export_csv |
| SharePoint | `storage/sharepoint_store.py` | Graph client credentials |

---

## 3. Storage backends

### 3.1 SQLite (default)

- Path: `{DATA_DIR}/contract_opportunities.db` (default `data/…`)
- Unique indexes on OpportunityID, Link  
- `list_rows` / `export_csv` for review  
- No cloud secrets  

### 3.2 SharePoint (optional)

- MSAL client credentials → Graph  
- Paginated key load; create list items  
- Requires app registration + Sites.Selected grant (see provision runbook)  
- Export-csv / sync-sheets: **sqlite-oriented** today  

### 3.3 Google Sheets (derived view)

- Not a `STORAGE_BACKEND`  
- Command: `sync-sheets`  
- Extra deps: `pip install -e ".[sheets]"` (`gspread`, `google-auth`)  
- Full replace of tab (default `Ingest`)  

---

## 4. Configuration

Loaded from environment and optional **repo-root** `.env` (`config.py`).

| Variable | Default | Notes |
|----------|---------|--------|
| `STORAGE_BACKEND` | `sqlite` | `sharepoint` when activated |
| `DATA_DIR` | `data` | |
| `SQLITE_PATH` | `{DATA_DIR}/contract_opportunities.db` | |
| `MAX_CREATE` | `50` | 0=unlimited |
| `KEYWORDS_PATH` | `config/keywords.yaml` | |
| `STATE_PATH` | `state/zero_new_streak.json` | |
| `ZERO_NEW_STREAK_THRESHOLD` | `3` | |
| `PARTIAL_ERROR_EXIT_THRESHOLD` | `5` | |
| `TEAMS_WEBHOOK_URL` | unset | optional |
| `GOOGLE_SHEET_ID` | unset | for sync-sheets |
| `GOOGLE_SHEET_TAB` | `Ingest` | |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | unset | path to JSON key |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | unset | inline JSON (CI) |
| Azure / SharePoint IDs | unset | only for SP backend |

---

## 5. CLI examples (as used in validation)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
pip install -e ".[sheets]"   # if using Google Sheets

python -m opportunity_ingest download-sample
python -m opportunity_ingest run --csv data/sample-openTenderNotice.csv
python -m opportunity_ingest run --write --csv data/sample-openTenderNotice.csv --max-create 10
python -m opportunity_ingest export-csv
python -m opportunity_ingest sync-sheets
```

**Observed sample dry-run (live CSV ~6MB):** parsed≈893, filtered≈83, mapped≈27, many map skips for empty Link (expected).

---

## 6. Automation

| Mechanism | Path / notes |
|-----------|----------------|
| CI | `.github/workflows/ci.yml` — ruff + pytest on 3.11/3.12 |
| Daily ingest | `.github/workflows/daily-canadabuys-ingest.yml` — cron `0 14 * * *` UTC, sqlite default, cache `data/`+`state/`, MAX_CREATE soft cap |
| Local daily + Sheets | Operator: Task Scheduler → `run --write` then `sync-sheets` (see google_sheets_setup.md) |

Sheets sync is **not** yet wired into the GitHub Actions YAML by default (add optional step when secrets exist).

---

## 7. Testing

```bash
pytest -q
ruff check src tests
```

Fixtures: `tests/fixtures/open_tender_*.csv`  
Sheets unit tests mock JSON load only (no live Google).  
SharePoint tests mock HTTP (no live Graph).

---

## 8. Operational pitfalls (learned)

1. **`pip install -e` requires `.`** → `pip install -e .`  
2. **CanadaBuys 403** without browser User-Agent → fixed in `download.py`  
3. **`.env` must be repo root**, not `scripts/.env`  
4. **Windows double extension** `file.json.json` breaks service account path  
5. **Map skips** when keyword hits but notice URL empty — by design  
6. Quotes in `.env` values usually unnecessary  

---

## 9. Related docs

- Data rules: [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md)  
- Change recipes: [`CHANGE_PLAYBOOK.md`](CHANGE_PLAYBOOK.md)  
- Decisions: [`DECISIONS.md`](DECISIONS.md)  
- Original design: [`phase1-canadabuys-sharepoint-implementation-schema.md`](phase1-canadabuys-sharepoint-implementation-schema.md)  
