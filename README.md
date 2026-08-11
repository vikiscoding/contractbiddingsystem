# Contract Bidding System — Opportunity Ingest

Phase 1 pipeline: download CanadaBuys **Open Tender Notices** CSV, filter by keywords, dedupe, and create new **Contract Opportunities** records.

**Day-1 storage default: local SQLite** (`STORAGE_BACKEND=sqlite`). SharePoint is a pluggable backend for later activation (`STORAGE_BACKEND=sharepoint`).

## Requirements

- Python **3.11+**
- See `requirements.txt` (runtime) and `requirements-dev.txt` (pytest, ruff)

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt
pip install -e .

# Optional: local env
cp .env.example .env
# or: cp config/settings.example.env .env
```

### Storage backend

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_BACKEND` | **`sqlite`** | Backend selector: `sqlite` (day-1) or `sharepoint` (later) |
| `DATA_DIR` | `data` | Directory for SQLite DB and exports |
| `SQLITE_PATH` | `{DATA_DIR}/contract_opportunities.db` | Explicit DB path |
| `MAX_CREATE` | **`50`** | Create-attempt budget (`0` = unlimited; negatives rejected) |
| `ZERO_NEW_STREAK_THRESHOLD` | `3` | Notify after N UTC calendar zero-new days |
| `PARTIAL_ERROR_EXIT_THRESHOLD` | `5` | Exit 1 + notify when create errors ≥ N |

No Azure/SharePoint secrets are required when `STORAGE_BACKEND=sqlite`.

## CLI (frozen contract)

```text
python -m opportunity_ingest run [--write | --dry-run] [--csv PATH] [--max-create N] [--with-existing]
python -m opportunity_ingest download-sample [--out PATH]
python -m opportunity_ingest check-store
python -m opportunity_ingest export-csv [--out PATH]
```

- **`run`** — dry-run by default (no writes). **Only `--write` persists.** `DRY_RUN` env does not enable writes and does not disable `--write`.
- **`download-sample`** — fetch a sample open-tender CSV.
- **`check-store`** — health-check the configured backend + sample key load.
- **`export-csv`** — export stored opportunities for human review (sqlite primary; SharePoint not supported yet).

## Development

```bash
ruff check src tests
pytest
```

CI (`.github/workflows/ci.yml`) runs on push/PR: install deps, `ruff check`, `pytest` on Python 3.11+.

## Scheduled ingest (GitHub Actions)

Daily workflow: [`.github/workflows/daily-canadabuys-ingest.yml`](.github/workflows/daily-canadabuys-ingest.yml)

| Trigger | Detail |
|---------|--------|
| `schedule` | `0 14 * * *` (14:00 UTC) |
| `workflow_dispatch` | Manual run; optional `max_create` / `dry_run` inputs |

**Defaults:** `STORAGE_BACKEND=sqlite`, soft `--max-create` from repo variable `INGEST_MAX_CREATE` (default **50**). Cache rotates `data/` + `state/` with `run_id` / `run_attempt`. Python owns Teams notify; Actions posts a backup Adaptive Card only when the job fails and step output `notified != true`.

### Secrets

| Name | Required (day-1 sqlite) | Purpose |
|------|-------------------------|---------|
| `TEAMS_WEBHOOK_URL` | **Required for alerts** (strongly recommended) | Teams Workflows webhook for hard fail / zero-new streak / partial-error alerts |
| `AZURE_TENANT_ID` | No | Only when `STORAGE_BACKEND=sharepoint` |
| `AZURE_CLIENT_ID` | No | Only when SharePoint activated |
| `AZURE_CLIENT_SECRET` | No | Only when SharePoint activated |
| `SHAREPOINT_SITE_ID` | No | Only when SharePoint activated |
| `SHAREPOINT_LIST_ID` | No | Only when SharePoint activated |

Azure / SharePoint secrets are **optional until SP activation**. Day-1 schedule does not need them.

### Variables

| Name | Default | Purpose |
|------|---------|---------|
| `INGEST_MAX_CREATE` | **`50`** | Soft create-attempt budget for the schedule (`0` = unlimited). Override per run via `workflow_dispatch` → `max_create`. |

Set under **Settings → Secrets and variables → Actions → Variables**.

### Calibration checklist

1. Live dry-run: note downloaded / filtered / would-create counts.
2. Check `max(len(link))` on live URLs (Link field must never truncate).
3. Tune keywords (engineering-owned `config/keywords.yaml`).
4. Smoke write: `python -m opportunity_ingest run --write --max-create 10` against sqlite.
5. Enable schedule with `INGEST_MAX_CREATE=50`.
6. **Steady-state rule:** raise variable to **100** if typical filtered volume is &lt; 30/day; set **0** (unlimited) only after **7 consecutive dry-runs** with &lt; 50 filtered candidates/day. Do not uncap on a single quiet day.

## Layout

```text
src/opportunity_ingest/   # installable package (src layout)
tests/                    # pytest
config/                   # keywords + settings examples
data/                     # local SQLite + exports (gitignored contents)
state/                    # streak state (gitignored JSON)
logs/                     # run logs (gitignored)
.github/workflows/        # ci.yml + daily-canadabuys-ingest.yml
```

## Design

See [docs/phase1-canadabuys-sharepoint-implementation-schema.md](docs/phase1-canadabuys-sharepoint-implementation-schema.md).
