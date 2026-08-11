# As-built architecture (Phase 1 + post-ingest Grok)

**Source of truth for the implemented system.** Supersedes design-doc details when they differ.  
**Unbuilt / discussed ideas:** [`BACKLOG.md`](BACKLOG.md) — do not invent features from backlog into this file.

| Field | Value |
|-------|--------|
| Status | Ingest exercised (Windows, 2026-08-10); Grok/Ranked in code + unit tests (2026-08-11) |
| Package | `opportunity_ingest` |
| Python | 3.11+ (verified on 3.14 in local venv) |

---

## 1. Pipeline

### 1.1 Ingest (system of record)

```text
CanadaBuys CSV
    → download (UA headers, 1 retry)
    → parse (bilingual headers, EN/FR coalesce)
    → filter_keywords (any-match; short terms word-boundary; span-aware nested suppress)
    → score (0–100, UTC)          # rule-based RelevanceScore only
    → map_fields (OpportunityFields)
    → load_existing_keys (store)
    → for each new candidate while attempts < MAX_CREATE:
          store.create()            # create-only; never updates Status/Notes
    → streak state (write runs)
    → optional Teams notify
    → exit code matrix
    → optional: export-csv | sync-sheets (Ingest tab)
```

### 1.2 Post-ingest Grok rank (derived views only)

```text
SQLite contract_opportunities
    → filter optional Status / limit / min rule score
    → load config/objectives.yaml
    → Grok (xAI OpenAI-compatible API) batch interpret + fit_score
    → write data/rankings/interpret-*.json + .md
    → optional full-replace Google Sheet tab Ranked
       (default ON when GOOGLE_SHEET_ID set; --no-sync-sheets to skip)
```

**Not in pipeline today:** website-type classifier, per-portal keyword packs, notice-page crawl, AI rewriting `keywords.yaml` (see BACKLOG).

---

## 2. Components

| Module | Path | Responsibility |
|--------|------|----------------|
| CLI | `cli.py` | `run`, `download-sample`, `check-store`, `export-csv`, `sync-sheets`, `interpret-rank`, `sync-rank-sheets` |
| Pipeline | `pipeline.py` | Orchestration, metrics, run logs |
| Download | `download.py` | HTTP GET + DEFAULT_HEADERS (anti-403) |
| Parse | `parse.py` | HEADER_CANDIDATES, TenderRecord |
| Filter | `filter_keywords.py` | keywords.yaml load + match (global groups only) |
| Score | `score.py` | Rule-based RelevanceScore |
| Map | `map_fields.py` | Schema mapping, Link required |
| Interpret / rank | `interpret_rank.py` | Grok rephrase + fit rank vs objectives; local reports |
| Config | `config.py` | pydantic-settings / `.env` |
| State | `state.py` | zero-new streak |
| Notify | `notify.py` | Teams Workflows Adaptive Card + GITHUB_OUTPUT |
| Exit | `exit_codes.py` | Exit + notify decisions |
| Sheets | `sheets_sync.py` | Full tab replace: Ingest (SQLite) + Ranked (Grok JSON) |
| Store protocol | `storage/base.py` | `OpportunityStore` |
| Factory | `storage/factory.py` | `sqlite` \| `sharepoint` |
| SQLite | `storage/sqlite_store.py` | Default backend, export_csv |
| SharePoint | `storage/sharepoint_store.py` | Graph client credentials |

### Config files (repo)

| Path | Role |
|------|------|
| `config/keywords.yaml` | Eng-owned ingest filter terms + weights |
| `config/objectives.yaml` | Eng-owned company objectives for Grok ranking (not used by ingest filter) |

---

## 3. Storage backends and views

### 3.1 SQLite (default system of record)

- Path: `{DATA_DIR}/contract_opportunities.db` (default `data/…`)
- Unique indexes on OpportunityID, Link  
- `list_rows` / `export_csv` for review  
- No cloud secrets  
- **Grok never UPDATEs these rows**

### 3.2 SharePoint (optional)

- MSAL client credentials → Graph  
- Paginated key load; create list items  
- Requires app registration + Sites.Selected grant (see provision runbook)  
- Export-csv / sync-sheets / interpret-rank: **sqlite-oriented** today  

### 3.3 Google Sheets (derived views only)

| Tab | Command | Source | Mode |
|-----|---------|--------|------|
| `Ingest` (default) | `sync-sheets` | SQLite opportunities | Full clear + rewrite |
| `Ranked` (default) | `interpret-rank` / `sync-rank-sheets` | Grok ranking report | Full clear + rewrite |
| `Review` (optional) | human | operator notes | Not written by pipeline |

- Not a `STORAGE_BACKEND`  
- Extra deps: `pip install -e ".[sheets]"` (`gspread`, `google-auth`)  
- Rankings **refused** if target tab name is `Ingest`  
- Ranked columns: see `RANKING_EXPORT_COLUMNS` in `sheets_sync.py`  

### 3.4 Local ranking reports

- Directory: `{DATA_DIR}/rankings/` (default `data/rankings/`, gitignored)  
- Files: `interpret-{run_id}.json`, `interpret-{run_id}.md`  

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
| `GOOGLE_SHEET_TAB` | `Ingest` | opportunity rows |
| `GOOGLE_SHEET_RANK_TAB` | `Ranked` | Grok rankings |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | unset | path to JSON key |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | unset | inline JSON (CI) |
| `XAI_API_KEY` | unset | Grok interpret-rank |
| `XAI_BASE_URL` | `https://api.x.ai/v1` | OpenAI-compatible |
| `XAI_MODEL` | `grok-4.5` | |
| `OBJECTIVES_PATH` | `config/objectives.yaml` | company objectives for AI rank |
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

# Optional Grok ranking (post-ingest; does not mutate SQLite)
pip install -e ".[ai]"
# set XAI_API_KEY in root .env (and keep GOOGLE_* if Ranked push wanted)
python -m opportunity_ingest interpret-rank --status New --limit 20
# Skip Ranked sheet: --no-sync-sheets
# Re-push last JSON: python -m opportunity_ingest sync-rank-sheets
```

**Observed sample dry-run (live CSV ~6MB):** parsed≈893, filtered≈83, mapped≈27, many map skips for empty Link (expected).

---

## 6. Automation

| Mechanism | Path / notes |
|-----------|----------------|
| CI | `.github/workflows/ci.yml` — ruff + pytest on 3.11/3.12 |
| Daily ingest | `.github/workflows/daily-canadabuys-ingest.yml` — cron `0 14 * * *` UTC, sqlite default, cache `data/`+`state/`, MAX_CREATE soft cap |
| Local daily + Sheets | Operator: Task Scheduler → `run --write` then `sync-sheets` (see google_sheets_setup.md) |
| Local + Grok Ranked | After write: `interpret-rank` (needs `XAI_API_KEY`; auto Ranked if sheet id set) |

Sheets **Ingest** sync and **interpret-rank** are **not** yet wired into the GitHub Actions YAML by default (BACKLOG B-06).

---

## 7. Testing

```bash
pytest -q
ruff check src tests
```

Fixtures: `tests/fixtures/open_tender_*.csv`  
Sheets unit tests: SA JSON load + ranking grid/helpers (no live Google).  
Grok unit tests: fake client (no live xAI).  
SharePoint tests mock HTTP (no live Graph).

---

## 8. Operational pitfalls (learned)

1. **`pip install -e` requires `.`** → `pip install -e .`  
2. **CanadaBuys 403** without browser User-Agent → fixed in `download.py`  
3. **`.env` must be repo root**, not `scripts/.env`  
4. **Windows double extension** `file.json.json` breaks service account path  
5. **Map skips** when keyword hits but notice URL empty — by design  
6. Quotes in `.env` values usually unnecessary  
7. **Grok fit_score ≠ RelevanceScore** — do not treat Ranked fit as store score  
8. **Do not put Grok output on Ingest** — use Ranked (code enforces)  

---

## 9. Related docs

- **Human plug-and-play (keys, functions, roadmap):** [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md)  
- Data rules: [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md)  
- Change recipes: [`CHANGE_PLAYBOOK.md`](CHANGE_PLAYBOOK.md)  
- Decisions: [`DECISIONS.md`](DECISIONS.md)  
- Backlog (not built): [`BACKLOG.md`](BACKLOG.md)  
- Status snapshot: [`STATUS.md`](STATUS.md)  
- Original design: [`phase1-canadabuys-sharepoint-implementation-schema.md`](phase1-canadabuys-sharepoint-implementation-schema.md)  
