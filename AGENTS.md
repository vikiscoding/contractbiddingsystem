# AGENTS.md — LLM / future developer entry point

**Read this file first** before changing code, data flows, storage, or automation.

| Field | Value |
|-------|--------|
| **Project** | Contract Bidding System — Phase 1 opportunity ingest |
| **Package** | `opportunity_ingest` (`src/opportunity_ingest/`) |
| **As-of** | 2026-08-11 (as-built; Sheets sync + optional Grok interpret-rank) |
| **Primary language** | Python 3.11+ |
| **Default store** | SQLite (`STORAGE_BACKEND=sqlite`) |

---

## What this system does

Daily (or on-demand) pipeline:

1. Download CanadaBuys **Open Tender Notices** CSV (public open data).
2. Parse bilingual headers (EN preferred, FR fallback).
3. Filter by configurable keywords (`config/keywords.yaml`).
4. Score relevance 0–100 (rule-based, UTC clock).
5. Map to logical **Contract Opportunities** schema.
6. Dedupe by `OpportunityID` + normalized `Link`.
7. **Create-only** writes to SQLite (default) or SharePoint (optional).
8. Optional: export CSV, **full-replace sync to Google Sheets `Ingest` tab**, Teams alerts.
9. Optional post-ingest: **Grok interpret-rank** — plain-English rewrite + fit ranking vs `config/objectives.yaml` (report only).

**SQLite is the system of record for day-1.** Google Sheets is a **view** (overwritten on sync). SharePoint is a **pluggable store**, not required for go-live. Grok ranking writes reports under `data/rankings/`; it does **not** mutate store Status/Notes/RelevanceScore.

---

## Doc map (read order for agents)

| Priority | Path | Purpose |
|----------|------|---------|
| 1 | **This file (`AGENTS.md`)** | Non-negotiable rules + orientation |
| 2 | [`docs/STATUS.md`](docs/STATUS.md) | Living readiness snapshot (what works / next) |
| 3 | [`docs/PLUG_AND_PLAY.md`](docs/PLUG_AND_PLAY.md) | Human keys + plug-and-play steps for built features |
| 3b | [`docs/PROCESSOR_OVERVIEW.md`](docs/PROCESSOR_OVERVIEW.md) | Plain language: this app as one processor — triggers, I/O, system place |
| 4 | [`docs/DATA_UPDATE_DIRECTIVES.md`](docs/DATA_UPDATE_DIRECTIVES.md) | **MUST / MUST NOT** for data writes, schema, sync |
| 5 | [`docs/AS_BUILT.md`](docs/AS_BUILT.md) | Current architecture, modules, CLI, env |
| 6 | [`docs/BACKLOG.md`](docs/BACKLOG.md) | Roadmap / discussed but **not built** |
| 7 | [`docs/CHANGE_PLAYBOOK.md`](docs/CHANGE_PLAYBOOK.md) | How to implement common change types |
| 8 | [`docs/INDEX.md`](docs/INDEX.md) | Full documentation index |
| 9 | [`docs/DECISIONS.md`](docs/DECISIONS.md) | ADR-style as-built decisions |
| 10 | [`docs/phase1-canadabuys-sharepoint-implementation-schema.md`](docs/phase1-canadabuys-sharepoint-implementation-schema.md) | Original design (rev 4); prefer AS_BUILT if conflict |
| 11 | [`scripts/ops_runbook.md`](scripts/ops_runbook.md) | Human operator procedures |
| 12 | [`scripts/google_sheets_setup.md`](scripts/google_sheets_setup.md) | Sheets service-account setup |
| 13 | [`scripts/provision_sharepoint_list.md`](scripts/provision_sharepoint_list.md) | SharePoint activation (deferred) |

---

## Hard rules (do not violate)

1. **Only `--write` persists.** Default `run` is dry-run. `DRY_RUN` env does not enable writes.
2. **Create-only storage.** Never update existing rows on re-ingest (protects human `Status` / `Notes`). Amendments: operator opens `Link`.
3. **Never silent-truncate `Link` URLs.** Missing/empty Link → skip row with error, do not invent URLs.
4. **Dedupe keys:** `OpportunityID` (stripped) OR normalized Link (strip, lower, no trailing slash).
5. **`MAX_CREATE` = create-attempt budget** (success or fail counts as one attempt), not “successful adds only”. `0` = unlimited; **never use `0` for “soft containment”**.
6. **CanadaBuys download requires browser-like User-Agent** (CDN returns 403 otherwise). See `download.py` `DEFAULT_HEADERS`.
7. **Google Sheets `Ingest` tab is full-replace.** Manual edits on that tab are wiped next `sync-sheets`. Human work → separate tab (e.g. `Review`).
8. **Keywords:** engineering owns `config/keywords.yaml`. Ops request changes via issues.
9. **Secrets:** never commit `.env`, `secrets/`, service-account JSON, Azure secrets, `XAI_API_KEY`.
10. **Phase 1 non-goals:** multi-source (MERX/etc.), auto-bidding, historical backfill, dual-write SQLite+SharePoint, two-way Sheets Status sync.
11. **Grok interpret-rank is post-ingest only.** Never write AI fit scores into `contract_opportunities` Status/Notes/RelevanceScore. Objectives live in `config/objectives.yaml` (eng-owned).

---

## Repo layout (code)

```text
src/opportunity_ingest/
  cli.py              # argparse entry: run, download-sample, check-store, export-csv, sync-sheets
  pipeline.py         # end-to-end orchestration
  download.py         # CanadaBuys GET + UA + one retry
  parse.py            # bilingual CSV → TenderRecord
  filter_keywords.py  # keyword match + span-aware nested suppression
  score.py            # RelevanceScore 0–100 UTC
  map_fields.py       # → OpportunityFields
  models.py           # TenderRecord, OpportunityFields, ExistingKeys
  config.py           # pydantic-settings
  state.py            # zero-new streak JSON
  notify.py           # Teams + Slack match pings (score≥threshold); Teams ops alerts
  exit_codes.py       # exit + notify matrix
  sheets_sync.py      # SQLite → Google Sheets full tab replace
  interpret_rank.py   # Grok rephrase + fit rank (report only)
  storage/
    base.py           # OpportunityStore Protocol, normalize_link
    factory.py        # sqlite | sharepoint
    sqlite_store.py   # default backend + export_csv
    sharepoint_store.py  # Graph adapter (optional)
config/keywords.yaml
config/objectives.yaml   # company objectives for interpret-rank
config/notify.yaml       # Teams match threshold / card limits
.github/workflows/ci.yml
.github/workflows/daily-canadabuys-ingest.yml
```

---

## CLI (frozen contract)

```text
python -m opportunity_ingest run [--write | --dry-run] [--csv PATH] [--max-create N] [--with-existing]
python -m opportunity_ingest download-sample [--out PATH]
python -m opportunity_ingest check-store
python -m opportunity_ingest export-csv [--out PATH]
python -m opportunity_ingest sync-sheets [--sheet-id ID] [--tab NAME]
python -m opportunity_ingest interpret-rank [--status STATUS] [--limit N] [--sync-sheets|--no-sync-sheets] [--rank-tab NAME]
python -m opportunity_ingest sync-rank-sheets [--from-json PATH] [--rank-tab NAME]
```

Optional install extras: `pip install -e ".[sheets]"` for Google Sheets; `pip install -e ".[ai]"` for Grok interpret-rank; SharePoint uses core deps (`msal`, `httpx`). Grok rankings sync to tab **`Ranked`** (never `Ingest`).

---

## Common tasks → where to edit

| Task | Primary files |
|------|----------------|
| Add/tune keywords | `config/keywords.yaml` (+ tests in `tests/test_filter.py`) |
| Change scoring | `score.py`, `tests/test_score.py` |
| CSV column mapping | `parse.py`, `map_fields.py`, fixtures under `tests/fixtures/` |
| Dedupe / Link rules | `storage/base.py`, `map_fields.py`, `sqlite_store.py` |
| Store schema | `sqlite_store.py` DDL + `models.OpportunityFields` + design schema |
| Pipeline order / metrics | `pipeline.py` |
| Exit / notify policy | `exit_codes.py`, `notify.py` |
| Sheets sync (opportunities) | `sheets_sync.py`, `cli.py` `sync-sheets` → tab `Ingest` |
| Sheets sync (Grok ranks) | `sheets_sync.py` `sync_rankings_to_sheet`, `interpret-rank --sync-sheets`, `sync-rank-sheets` → tab `Ranked` |
| Grok interpret / rank | `interpret_rank.py`, `config/objectives.yaml`, `cli.py` `interpret-rank` |
| SharePoint | `storage/sharepoint_store.py`, `scripts/provision_sharepoint_list.md` |
| Daily schedule | `.github/workflows/daily-canadabuys-ingest.yml` |
| Env vars | `config.py`, `.env.example`, `config/settings.example.env` |

---

## Data locations (local)

| Path | Role |
|------|------|
| `data/contract_opportunities.db` | SQLite system of record |
| `data/sample-openTenderNotice.csv` | Downloaded open-tender sample |
| `data/rankings/interpret-*.md` | Grok ranked brief (human) |
| `data/rankings/interpret-*.json` | Grok ranked brief (machine) |
| `data/export-opportunities.csv` | Human CSV export |
| `state/zero_new_streak.json` | Zero-new calendar streak |
| `logs/run-*.json` | Per-run metrics |
| `secrets/google-service-account.json` | Sheets key (**gitignored**; name must be `.json` not `.json.json`) |
| `.env` | Local secrets/config (**gitignored**; must be **repo root**, not `scripts/.env`) |

---

## Verification before claiming done

```bash
ruff check src tests
pytest -q
python -m opportunity_ingest --help
```

For data path smoke:

```bash
python -m opportunity_ingest run --csv tests/fixtures/open_tender_pipeline.csv
python -m opportunity_ingest check-store
```

---

## Conflict resolution

If **design doc (rev 4)** conflicts with **code or AS_BUILT**, prefer **code + AS_BUILT + DATA_UPDATE_DIRECTIVES**. Update design notes only if documenting intentional new design.
