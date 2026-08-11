# Ops runbook — CanadaBuys opportunity ingest

Operator guide for day-1 SQLite storage, Status triage, calibration, create caps, keyword ownership, alerts, cache re-runs, **Google Sheets view**, SharePoint activation, and rollback.

**Audience:** operators who review opportunities and manage the daily schedule.  
**Engineering owns:** `config/keywords.yaml`, pipeline code, GitHub workflow YAML.  
**LLM / data rules:** [AGENTS.md](../AGENTS.md), [DATA_UPDATE_DIRECTIVES](../docs/DATA_UPDATE_DIRECTIVES.md), [AS_BUILT](../docs/AS_BUILT.md).  
**Related:** [README.md](../README.md), [google_sheets_setup.md](google_sheets_setup.md), [provision_sharepoint_list.md](provision_sharepoint_list.md), [daily_sync.ps1](daily_sync.ps1).

---

## 0. Recommended daily flow

```text
1. run --write          → SQLite system of record (create-only)
2. sync-sheets          → optional full-replace of Google tab "Ingest"
3. export-csv           → optional Excel snapshot
4. Human Status triage  → SQLite / export / Sheet Review tab (not Ingest if auto-synced)
```

Windows automation sample: [`daily_sync.ps1`](daily_sync.ps1) (Task Scheduler).

---

## 1. Daily human Status triage (export-csv / SQL)

Ingest is **create-only**: new rows land with `Status = New`. Humans own Status and Notes after create. The pipeline never overwrites existing rows.

### Status values

| Status | Meaning |
|--------|---------|
| `New` | Just ingested; needs triage |
| `Reviewing` | Under evaluation |
| `Relevant` | Fits our capabilities |
| `Bidding` | Active pursuit |
| `Discarded` | Not a fit |

### Export for review

```bash
# Default path under DATA_DIR (typically data/export-opportunities.csv)
python -m opportunity_ingest export-csv

# Explicit path
python -m opportunity_ingest export-csv --out data/export-opportunities.csv
```

Open the CSV in Excel or Power BI. Sort by `RelevanceScore` (desc) and filter `Status = New` (or exclude `Discarded`).

> `export-csv` is supported for `STORAGE_BACKEND=sqlite` only. SharePoint review uses the list UI after activation.

### Google Sheets view (optional)

```bash
pip install -e ".[sheets]"
python -m opportunity_ingest sync-sheets
```

- Setup: [google_sheets_setup.md](google_sheets_setup.md)
- **Ingest** tab is **full-replaced** every sync — put manual notes on a separate **Review** tab
- SQLite remains system of record; Sheets is a derived view
- Normative rules: [DATA_UPDATE_DIRECTIVES.md](../docs/DATA_UPDATE_DIRECTIVES.md) §3

### SQL triage (sqlite3)

Default DB: `data/contract_opportunities.db` (or `SQLITE_PATH` / `{DATA_DIR}/contract_opportunities.db`).

```bash
# Queue: non-discarded, highest score first
sqlite3 data/contract_opportunities.db "
SELECT OpportunityID, Title, ClosingDate, RelevanceScore, Status, Link
FROM contract_opportunities
WHERE Status != 'Discarded'
ORDER BY RelevanceScore DESC, ClosingDate ASC;
"

# Only New
sqlite3 data/contract_opportunities.db "
SELECT OpportunityID, Title, ClosingDate, RelevanceScore, Link
FROM contract_opportunities
WHERE Status = 'New'
ORDER BY RelevanceScore DESC;
"
```

### Update Status / Notes

```bash
# Mark reviewing
sqlite3 data/contract_opportunities.db "
UPDATE contract_opportunities
SET Status = 'Reviewing', Notes = 'Assigned to capture team'
WHERE OpportunityID = 'YOUR-REF-NUMBER';
"

# Discard noise
sqlite3 data/contract_opportunities.db "
UPDATE contract_opportunities
SET Status = 'Discarded', Notes = 'Out of scope'
WHERE OpportunityID = 'YOUR-REF-NUMBER';
"
```

Prefer updating by `OpportunityID` (unique). Avoid bulk Status changes unless you intend to.

### CI / Actions artifact note

Scheduled runs use [`.github/workflows/daily-canadabuys-ingest.yml`](../.github/workflows/daily-canadabuys-ingest.yml) (**Daily CanadaBuys Opportunity Ingest**). Each run uploads a recovery artifact (`data/*.db`, `state/`, `logs/`); cache of `data/` + `state/` is best-effort continuity only.

To triage remotely: download the latest run artifact, then open the DB or run:

```bash
# Point at the downloaded DB
set SQLITE_PATH=path/to/downloaded/contract_opportunities.db   # Windows cmd
# export SQLITE_PATH=...   # Unix
python -m opportunity_ingest export-csv --out data/export-from-artifact.csv
```

---

## 2. Amendment caveat (create-only)

CanadaBuys notices can **amend** after first publication (closing date, text, etc.). This pipeline:

- Dedupes on **OpportunityID** and **Link**
- **Creates** only; never updates existing rows
- Therefore **stored ClosingDate / Title / Description can go stale** if the source amends the same notice

**Operator rule:** for any opportunity still in play (`Reviewing` / `Relevant` / `Bidding`), **open the Link** on CanadaBuys for the latest closing date and notice text. Do not treat the DB ClosingDate as authoritative after first create.

Same OpportunityID reappearing on a later ingest is **skipped as duplicate** — amendments will not refresh the row automatically.

---

## 3. Calibration procedure

Before relying on the daily schedule at full volume, calibrate against live data.

### Step A — Dry-run (no writes)

```bash
# Live download (default dry-run — no store reads, no writes)
python -m opportunity_ingest run

# Offline sample (two-step)
python -m opportunity_ingest download-sample
# Default path: data/sample-openTenderNotice.csv
python -m opportunity_ingest run --csv data/sample-openTenderNotice.csv

# Or any local open-tender CSV / fixture
python -m opportunity_ingest run --csv tests/fixtures/open_tender_sample.csv
```

Record from the CLI summary line (printed after every `run`):

| Metric | Meaning |
|--------|---------|
| `parsed` | Rows read from the CSV |
| **`filtered`** | Keyword hits (`filtered_count`) — **primary volume signal** for MAX_CREATE policy |
| `mapped` | Successfully mapped candidates (map errors are separate) |
| `would_create` | On **dry-run**: candidates that would be created under the attempt budget. Default dry-run does **not** load store keys, so every mapped candidate is treated as new (intra-run dups still skipped). **Not** zero just because the store was unused. |
| `skipped_dup` | Duplicate OpportunityID/Link (intra-run, or vs loaded keys) |
| `skipped_max` | Eligible new candidates left unattempted because the attempt budget was exhausted |
| `added` | Actual creates — only increments on **`--write`** (stays 0 on dry-run) |

Dry-run **with existing store keys** (still no writes; store must be available):

```bash
# Live feed + load keys from configured store
python -m opportunity_ingest run --with-existing

# Offline sample + load keys
python -m opportunity_ingest run --csv data/sample-openTenderNotice.csv --with-existing
```

With `--with-existing`, `would_create` / `skipped_dup` reflect dedupe against `load_existing_keys()` — use this to estimate true new volume vs a populated store. `--with-existing` is dry-run only (CLI rejects it with `--write`).

### Step B — Measure Link length risk

Links are stored as full plain-text URLs and are **never silent-truncated**. Day-1 mapping does **not** hard-skip long Links (multi-line TEXT / multi-line SharePoint field); still measure `max(len(link))` so ops/eng know live URL size.

After `download-sample` (or any open-tender CSV):

```bash
python -c "import csv; from pathlib import Path; p=Path('data/sample-openTenderNotice.csv');
rows=list(csv.DictReader(p.open(encoding='utf-8-sig', newline='')));
lens=[]
for row in rows:
    link=(row.get('noticeURL-URLavis-eng') or row.get('noticeURL-URLavis-fra') or '').strip()
    if link: lens.append(len(link))
print(f'urls={len(lens)} max_len={max(lens) if lens else 0}')"
```

Optional after a smoke write + export (stored Link column):

```bash
python -m opportunity_ingest export-csv --out data/export-opportunities.csv
python -c "import csv; from pathlib import Path; p=Path('data/export-opportunities.csv');
lens=[len((r.get('Link') or '').strip()) for r in csv.DictReader(p.open(encoding='utf-8-sig', newline='')) if (r.get('Link') or '').strip()];
print(f'stored={len(lens)} max_len={max(lens) if lens else 0}')"
```

If max length is unexpectedly large or tooling breaks on long URLs, open a GitHub issue for engineering — not an ops-only keyword tweak.

### Step C — Smoke write with a tight cap

```bash
python -m opportunity_ingest run --write --max-create 10
python -m opportunity_ingest export-csv --out data/export-smoke.csv
python -m opportunity_ingest check-store
```

Confirm:

- New rows appear with `Status = New`
- Duplicates on re-run are skipped
- `skipped_max` increases if more than 10 new candidates exist

### Step D — Schedule

Enable / leave enabled the daily workflow (`.github/workflows/daily-canadabuys-ingest.yml`) with:

| Setting | Day-1 value |
|---------|-------------|
| `STORAGE_BACKEND` | `sqlite` |
| `INGEST_MAX_CREATE` (GitHub variable) | `50` |
| `TEAMS_WEBHOOK_URL` | set (strongly recommended) |

Use workflow_dispatch `max_create` / `dry_run` inputs for controlled re-runs during calibration.

---

## 4. MAX_CREATE policy

`MAX_CREATE` / `INGEST_MAX_CREATE` is a **create-attempt budget** per run (success **or** failure both consume an attempt). `0` means unlimited. Unattempted new candidates increment `skipped_max_create_count`.

### Steady-state policy (resolved)

| Stage | Cap | When |
|-------|-----|------|
| Default | **50** | Always start here for scheduled runs |
| Raise | **100** | Typical **filtered** volume **&lt; 30/day** (after calibration, multiple quiet-but-stable days) |
| Unlimited | **0** | Only after **7 consecutive dry-runs** each showing **&lt; 50 filtered** candidates/day |

**Do not** uncap (`0`) on a single quiet day. Prefer raising 50 → 100 first.

### How to change

- **GitHub Actions variable:** `INGEST_MAX_CREATE` (repo or environment variable).
- **Local / one-off:** `MAX_CREATE` env or CLI `--max-create N`.
- **Workflow dispatch:** optional `max_create` input overrides the variable for that run.

After any raise, watch `skipped_max` on the next few scheduled runs. Persistent non-zero `skipped_max` with healthy error counts means the cap is binding — either raise per policy or triage keyword noise.

---

## 5. Keyword changes — ownership

| Role | Responsibility |
|------|----------------|
| **Ops** | File a **GitHub issue** describing false positives/negatives (examples: OpportunityID, title snippet, expected behavior). |
| **Engineering** | Owns `config/keywords.yaml` PRs, review, merge, and release to the schedule. |

Ops must **not** commit keyword edits on shared branches without eng review. Keyword floods are mitigated by eng ownership plus `MAX_CREATE`.

Suggested issue template fields:

- Sample titles / refs that should match or should not
- Whether this is precision (too much noise) or recall (missed tenders)
- Urgency (blocking bid deadline?)

---

## 6. Zero-new streak and Teams alerts

### Streak state

- File: `state/zero_new_streak.json` (override with `STATE_PATH`)
- Updated only on successful **`--write`** runs (not dry-run)
- Counts **UTC calendar days** with zero new creates; same-day re-runs do not double-count
- Threshold: `ZERO_NEW_STREAK_THRESHOLD` (default **3**)

When streak ≥ threshold after a write with `added == 0`, Python posts a Teams alert (`notify_reason=zero_new_streak`) and exits 0.

### What alerts go to Teams

| Condition | Exit | Notify |
|-----------|------|--------|
| Hard fail (download/parse/config/store health) | 1 | Yes |
| Create `error_count` ≥ `PARTIAL_ERROR_EXIT_THRESHOLD` (default 5) | 1 | Yes |
| Zero-new streak ≥ threshold | 0 | Yes |
| Soft partial errors below threshold | 0 | No |
| Successful adds | 0 | No |

Primary notify is **Python** via `TEAMS_WEBHOOK_URL`. Actions may backup-notify only if the job failed and Python did not set `notified=true` (avoids double-notify for handled failures).

### Operator response

1. Open the failing Actions run URL (included when `GITHUB_RUN_URL` is set).
2. Check run JSON under `logs/run-*.json` and workflow logs.
3. For zero-new streak: confirm CanadaBuys feed is live, keywords still sensible, and store is not accidentally full of false dups — then file eng issue if needed.
4. Smoke-test webhook once before go-live (POST Adaptive Card via Workflows template).

---

## 7. Cache re-run behavior (`run_attempt`)

Workflow: [`.github/workflows/daily-canadabuys-ingest.yml`](../.github/workflows/daily-canadabuys-ingest.yml).

Daily job restores/saves `data/` (SQLite) and `state/` via GitHub Actions cache:

- Cache key prefix: `canadabuys-ingest-`
- Key includes **`github.run_id`** and **`github.run_attempt`**
- Restore-keys fall back to prior `canadabuys-ingest-${{ runner.os }}-` entries
- Cache **save** is best-effort (`continue-on-error`) so a failed save on re-run does not fail the whole job
- Per-run **artifact** (`data/*.db`, `state/`, `logs/`) is the recovery path if cache is missing or stale

### Why `run_attempt` matters

GitHub Actions cache keys are immutable once written. A job **re-run** gets a new `run_attempt`. Using `run_id` + `run_attempt` avoids “cache already exists” failures that would block persistence of updated SQLite/streak state.

### Operator notes

- Prefer **workflow_dispatch** (optional `max_create` / `dry_run` inputs) for intentional re-runs during incidents.
- After a re-run, confirm the latest **artifact** reflects new rows (`export-csv` or `check-store` against the downloaded DB).
- If cache restore yields an empty/old DB, restore from a recent successful run’s uploaded artifact or a known-good local backup — see Rollback.

---

## 8. SharePoint activation checklist

Day-1 production path is **SQLite**. SharePoint is a pluggable `OpportunityStore` backend: set `STORAGE_BACKEND=sharepoint` and the Azure/SharePoint secrets below when Entra, site, and list are ready. Until then, leave `STORAGE_BACKEND=sqlite` (no Azure secrets required).

### Checklist

1. Complete **[scripts/provision_sharepoint_list.md](provision_sharepoint_list.md)** (list creation, site/list IDs, Entra app, `Sites.Selected` grant):
   - Create list **Contract Opportunities** (UI source of truth; multi-line plain-text Link — not Hyperlink column)
   - Resolve site/list IDs
   - Entra app + `Sites.Selected` + admin consent
   - Chicken-and-egg site permission grant (`roles: ["write"]`) to the ingest app
2. Set GitHub secrets (or environment secrets):

   | Secret | Purpose |
   |--------|---------|
   | `AZURE_TENANT_ID` | Entra tenant |
   | `AZURE_CLIENT_ID` | App id |
   | `AZURE_CLIENT_SECRET` | App secret |
   | `SHAREPOINT_SITE_ID` | Graph site id |
   | `SHAREPOINT_LIST_ID` | List GUID |

3. Set `STORAGE_BACKEND=sharepoint` on the daily workflow env (and local `.env` for smoke tests). Keep `INGEST_MAX_CREATE` / soft cap policy from §4.
4. Smoke (with secrets present and backend flipped):

   ```bash
   python -m opportunity_ingest check-store
   python -m opportunity_ingest run --write --max-create 5
   ```

   `check-store` performs backend health + sample key load against Graph when `STORAGE_BACKEND=sharepoint`.

5. Optional one-time migration: export SQLite CSV → manual import or scripted creates. **No dual-write** in Phase 1 — switch backends; do not write both.
6. Human Status triage after flip: use SharePoint list views. `export-csv` remains the sqlite review path.

Do **not** require SharePoint for day-1 go-live.

---

## 9. Rollback / disable schedule

### Disable ingest quickly

1. **GitHub Actions →** workflow **Daily CanadaBuys Opportunity Ingest** → ⋯ → **Disable workflow**  
   (or remove/comment the `schedule:` cron and merge).
2. Optionally cancel any in-progress run.

### Roll back data (SQLite)

1. Download a known-good `data/` artifact or restore from backup of `contract_opportunities.db`.
2. Replace the active DB path (`DATA_DIR` / `SQLITE_PATH`).
3. Re-enable schedule only after `check-store` and a dry-run look healthy.

### Roll back backend flip

If SharePoint activation misbehaves:

1. Set `STORAGE_BACKEND=sqlite` again on the workflow.
2. Confirm Azure secrets are no longer required for the job.
3. Investigate SP list/permissions offline via the provisioning runbook — do not leave the schedule on a broken backend.

### Soft containment (no full disable)

Limit blast radius **without** disabling the workflow:

- Dispatch with **`dry_run=true`** (no writes), **or**
- Dispatch with a **low** `max_create` override (**10** or **25**), **or** temporarily lower repo variable `INGEST_MAX_CREATE` to **10** / **25**.

**Never use `0` for containment.** `MAX_CREATE` / `INGEST_MAX_CREATE=0` means **unlimited** create attempts (see §4). Unlimited is only appropriate after the steady-state policy criteria, not during an incident.

---

## Quick reference — CLI

```text
python -m opportunity_ingest run [--write | --dry-run] [--csv PATH] [--max-create N] [--with-existing]
python -m opportunity_ingest download-sample [--out PATH]
python -m opportunity_ingest check-store
python -m opportunity_ingest export-csv [--out PATH]
```

Only **`--write`** persists. Default (and `--dry-run`) never writes. `DRY_RUN` env never enables write alone.

## Quick reference — key env / vars

| Name | Default | Notes |
|------|---------|--------|
| `STORAGE_BACKEND` | `sqlite` | `sharepoint` when activated |
| `DATA_DIR` | `data` | SQLite + exports |
| `MAX_CREATE` / `INGEST_MAX_CREATE` | `50` | Attempt budget; `0` = unlimited |
| `ZERO_NEW_STREAK_THRESHOLD` | `3` | Teams after N zero-new UTC days |
| `PARTIAL_ERROR_EXIT_THRESHOLD` | `5` | Exit 1 + notify |
| `TEAMS_WEBHOOK_URL` | — | Strongly recommended day-1 |
| `KEYWORDS_PATH` | `config/keywords.yaml` | Eng-owned |
| `STATE_PATH` | `state/zero_new_streak.json` | Streak JSON |

---

*End of ops runbook.*
