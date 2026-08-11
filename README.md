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

No Azure/SharePoint secrets are required when `STORAGE_BACKEND=sqlite`.

## CLI (frozen contract)

```text
python -m opportunity_ingest run [--write | --dry-run] [--csv PATH] [--max-create N] [--with-existing]
python -m opportunity_ingest download-sample [--out PATH]
python -m opportunity_ingest check-store
python -m opportunity_ingest export-csv [--out PATH]
```

- **`run`** — dry-run by default (no writes). Use `--write` to persist to the configured store.
- **`download-sample`** — fetch a sample open-tender CSV.
- **`check-store`** — health-check the configured backend + sample key load.
- **`export-csv`** — export stored opportunities for human review (sqlite primary; SharePoint not supported yet).

## Development

```bash
ruff check src tests
pytest
```

CI (`.github/workflows/ci.yml`) runs on push/PR: install deps, `ruff check`, `pytest` on Python 3.11+.

## Layout

```text
src/opportunity_ingest/   # installable package (src layout)
tests/                    # pytest
config/                   # keywords + settings examples
data/                     # local SQLite + exports (gitignored contents)
state/                    # streak state (gitignored JSON)
logs/                     # run logs (gitignored)
```

## Design

See [docs/phase1-canadabuys-sharepoint-implementation-schema.md](docs/phase1-canadabuys-sharepoint-implementation-schema.md).
