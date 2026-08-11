# Contract Bidding System — Opportunity Ingest

Phase 1 pipeline: download CanadaBuys **Open Tender Notices** CSV, filter by keywords, dedupe, and **create-only** new **Contract Opportunities** into a durable store.

| | |
|--|--|
| **Default store** | Local **SQLite** (`STORAGE_BACKEND=sqlite`) |
| **Optional store** | SharePoint via Microsoft Graph (`STORAGE_BACKEND=sharepoint`) |
| **Optional view** | Google Sheets tab full-replace (`sync-sheets`) |
| **LLM / agent entry** | **[`AGENTS.md`](AGENTS.md)** ← start here for AI-assisted development |
| **Human plug-in** | **[`docs/PLUG_AND_PLAY.md`](docs/PLUG_AND_PLAY.md)** ← keys, steps, roadmap to go live |

---

## Documentation structure

| Doc | Audience | Purpose |
|-----|----------|---------|
| [`docs/PLUG_AND_PLAY.md`](docs/PLUG_AND_PLAY.md) | **Operators / humans** | **Keys to plug, function list, go-live sequence, roadmap** |
| [`AGENTS.md`](AGENTS.md) | LLMs + devs | Hard rules, module map, task routing |
| [`docs/STATUS.md`](docs/STATUS.md) | Everyone | Living readiness / what works now |
| [`docs/INDEX.md`](docs/INDEX.md) | Everyone | Full doc index |
| [`docs/AS_BUILT.md`](docs/AS_BUILT.md) | Devs / LLMs | Implemented architecture |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | Everyone | Roadmap / not built yet |
| [`docs/DATA_UPDATE_DIRECTIVES.md`](docs/DATA_UPDATE_DIRECTIVES.md) | Devs / LLMs | **MUST / MUST NOT** for data writes & sync |
| [`docs/CHANGE_PLAYBOOK.md`](docs/CHANGE_PLAYBOOK.md) | Devs / LLMs | How to make common changes |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Devs / LLMs | Key ADRs |
| [`docs/phase1-…-schema.md`](docs/phase1-canadabuys-sharepoint-implementation-schema.md) | Design history | Original Phase 1 design (rev 4) |
| [`scripts/ops_runbook.md`](scripts/ops_runbook.md) | Operators | Daily triage, MAX_CREATE, rollback |
| [`scripts/google_sheets_setup.md`](scripts/google_sheets_setup.md) | Operators | Free Sheets service-account setup |
| [`scripts/provision_sharepoint_list.md`](scripts/provision_sharepoint_list.md) | Operators | SharePoint activation |
| [`scripts/daily_sync.ps1`](scripts/daily_sync.ps1) | Operators | Windows daily ingest + optional Sheets |

If design doc and as-built conflict → **prefer code + AS_BUILT + DATA_UPDATE_DIRECTIVES**.

---

## Requirements

- Python **3.11+**
- `requirements.txt` / `requirements-dev.txt`
- Optional Sheets: `pip install -e ".[sheets]"`

---

## Quick start (Windows)

**Full human checklist (keys, Sheets, Grok, Teams, roadmap):**  
→ **[`docs/PLUG_AND_PLAY.md`](docs/PLUG_AND_PLAY.md)**

```powershell
cd "C:\Users\Vikrant\Documents\Agentic AI Learning\contractbiddingsystem"
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt -r requirements-dev.txt
pip install -e .

# .env must live at REPO ROOT (not scripts/)
copy .env.example .env
```

### Ingest smoke path

```powershell
python -m opportunity_ingest download-sample
python -m opportunity_ingest run --csv data/sample-openTenderNotice.csv
python -m opportunity_ingest run --write --csv data/sample-openTenderNotice.csv --max-create 10
python -m opportunity_ingest export-csv
```

### Google Sheets (optional free view)

```powershell
pip install -e ".[sheets]"
# Configure GOOGLE_* in root .env — see scripts/google_sheets_setup.md
python -m opportunity_ingest sync-sheets
```

### Grok interpret-rank (optional AI brief)

Plain-English rewrite + rank against `config/objectives.yaml` (does **not** change SQLite rows).  
When `GOOGLE_SHEET_ID` is set (your live sheet), rankings are **full-replaced** into a **`Ranked`** tab (separate from `Ingest`):

```powershell
pip install -e ".[ai]"
pip install -e ".[sheets]"   # same service account as sync-sheets
# Set XAI_API_KEY + existing GOOGLE_* in root .env
python -m opportunity_ingest interpret-rank --status New --limit 20
# Local: data/rankings/interpret-*.md
# Sheet: tab Ranked (created if missing)
# Skip sheet push: --no-sync-sheets
# Re-push last report without Grok: python -m opportunity_ingest sync-rank-sheets
```

**Notes learned in setup:**

- `pip install -e .` needs the trailing `.`
- CanadaBuys may return **403** without a browser User-Agent (handled in `download.py`)
- Service account file must be `secrets/google-service-account.json` (not `.json.json`)
- Root `.env` only

---

## CLI (frozen contract)

```text
python -m opportunity_ingest run [--write | --dry-run] [--csv PATH] [--max-create N] [--with-existing]
python -m opportunity_ingest download-sample [--out PATH]
python -m opportunity_ingest check-store
python -m opportunity_ingest export-csv [--out PATH]
python -m opportunity_ingest sync-sheets [--sheet-id ID] [--tab NAME]
python -m opportunity_ingest interpret-rank [--status STATUS] [--limit N] [--sync-sheets|--no-sync-sheets]
python -m opportunity_ingest sync-rank-sheets [--from-json PATH] [--rank-tab NAME]
```

| Command | Persist store? | Notes |
|---------|----------------|--------|
| `run` | Only with `--write` | Default dry-run |
| `export-csv` | No | Snapshot for Excel |
| `sync-sheets` | No SQLite write | **Full-replace** Sheet tab `Ingest` |
| `check-store` | No | Health + key count |
| `interpret-rank` | No | Grok rewrite + rank → `data/rankings/` + optional Sheets **Ranked** |
| `sync-rank-sheets` | No | Re-push ranking JSON → Sheets **Ranked** (no Grok call) |

---

## Storage & env (summary)

| Variable | Default | Purpose |
|----------|---------|---------|
| `STORAGE_BACKEND` | `sqlite` | `sqlite` \| `sharepoint` |
| `DATA_DIR` | `data` | DB + exports |
| `MAX_CREATE` | `50` | Create-**attempt** budget; `0`=unlimited |
| `GOOGLE_SHEET_ID` | — | Sheets sync |
| `GOOGLE_SHEET_TAB` | `Ingest` | Opportunity tab overwritten on sync |
| `GOOGLE_SHEET_RANK_TAB` | `Ranked` | Grok ranking tab overwritten on interpret-rank |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | — | Path to JSON key |
| `TEAMS_WEBHOOK_URL` | — | Ops alerts + match fallback |
| `TEAMS_MATCH_WEBHOOK_URL` | — | Optional capture-channel webhook |
| `TEAMS_MATCH_SCORE_THRESHOLD` | `40` | Ping when score ≥ N |
| `XAI_API_KEY` | — | Grok interpret-rank |
| `OBJECTIVES_PATH` | `config/objectives.yaml` | AI ranking frame of reference |

Full list: `.env.example`, `config/settings.example.env`, [`docs/PLUG_AND_PLAY.md`](docs/PLUG_AND_PLAY.md), `docs/AS_BUILT.md`.

**Data rules (critical):** create-only; never silent-truncate Link; Sheets is a view.  
→ [`docs/DATA_UPDATE_DIRECTIVES.md`](docs/DATA_UPDATE_DIRECTIVES.md)

**What exists vs not built:** [`docs/STATUS.md`](docs/STATUS.md) · [`docs/AS_BUILT.md`](docs/AS_BUILT.md) · [`docs/BACKLOG.md`](docs/BACKLOG.md)

---

## Development

```powershell
ruff check src tests
pytest -q
```

CI: `.github/workflows/ci.yml` (Python 3.11 / 3.12).

---

## Scheduled ingest (GitHub Actions)

Workflow: [`.github/workflows/daily-canadabuys-ingest.yml`](.github/workflows/daily-canadabuys-ingest.yml)

| Item | Detail |
|------|--------|
| Cron | `0 14 * * *` UTC |
| Default backend | sqlite |
| Soft cap | `INGEST_MAX_CREATE` default **50** |
| Cache | `data/` + `state/` with `run_id`+`run_attempt` (best-effort) |

Optional Sheets step: add after write using secrets `GOOGLE_SHEET_ID` + `GOOGLE_SERVICE_ACCOUNT_JSON` (see `docs/CHANGE_PLAYBOOK.md` §G).

### Secrets / variables

| Name | Day-1 sqlite | Purpose |
|------|----------------|---------|
| `TEAMS_WEBHOOK_URL` | Recommended | Alerts |
| Azure / SharePoint secrets | No | Only if `STORAGE_BACKEND=sharepoint` |
| `GOOGLE_*` (local or CI) | Optional | Sheets view |
| `INGEST_MAX_CREATE` (variable) | Default 50 | Schedule attempt budget |

---

## Layout

```text
AGENTS.md                 # LLM entry
README.md
docs/                     # AS_BUILT, directives, playbook, design
src/opportunity_ingest/   # package
config/keywords.yaml      # eng-owned keywords
scripts/                  # ops + Sheets + SP provision + daily_sync.ps1
tests/
data/                     # DB, samples, exports (contents gitignored)
state/                    # streak JSON
logs/                     # run metrics
secrets/                  # service account JSON (gitignored)
.github/workflows/
```

---

## Phase 1 non-goals

Other tender portals, AI ranking, auto-bidding, historical backfill, Power Apps, two-way Sheets Status sync, dual-write SQLite+SharePoint.
