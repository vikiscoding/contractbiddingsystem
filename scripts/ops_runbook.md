# Ops runbook — CanadaBuys opportunity ingest

Operator guide for day-1 SQLite storage, Status triage, calibration, create caps, keyword ownership, alerts, cache re-runs, SharePoint activation, and rollback.

**Audience:** operators who review opportunities and manage the daily schedule.  
**Engineering owns:** `config/keywords.yaml`, pipeline code, GitHub workflow YAML.  
**Related docs:** [README.md](../README.md), [scripts/provision_sharepoint_list.md](provision_sharepoint_list.md), [design schema](../docs/phase1-canadabuys-sharepoint-implementation-schema.md).

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

On scheduled runs, the SQLite file lives under the Actions cache/artifact for `data/`. To triage remotely: download the latest `data/` artifact from the workflow run, open the DB or run `export-csv` locally against that file (`SQLITE_PATH=...`).

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
# Live download (default dry-run)
python -m opportunity_ingest run

# Or offline CSV
python -m opportunity_ingest run --csv path/to/openTenderNotice.csv
# / download-sample first:
python -m opportunity_ingest download-sample
python -m opportunity_ingest run --csv data/sample-open-tender.csv
```

Record from the CLI summary line:

- `parsed` — rows read
- **`filtered`** — keyword hits (`filtered_count`) — primary volume signal
- `would_create` — new vs existing (0 if no store keys loaded)
- `skipped_dup` / `skipped_max`

Optional dry-run with existing keys (requires store):

```bash
python -m opportunity_ingest run --with-existing
```

### Step B — Measure Link length risk

Links must never be silent-truncated. On a live or sample CSV, measure max URL length (PowerShell example):

```powershell
# After download-sample or a live dry-run that wrote a CSV path you control
python -c "import csv; from pathlib import Path; p=Path('data/sample-open-tender.csv');
# Or use a fixture; inspect link columns after parse in a notebook
print('Open fixture/sample and max(len(link)) from pipeline logs if emitted')"
```

Practical check: after a dry-run, inspect map/skip logs for Link policy skips. If `max(len(link))` approaches the hard skip threshold, open a GitHub issue for engineering (schema/limit), not an ops-only keyword tweak.

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

Daily workflow persists `data/` (SQLite) and `state/` via GitHub Actions cache:

- Cache key includes **`github.run_id`** and **`github.run_attempt`**
- Restore-keys allow fallback to prior successful caches
- Cache **save** uses `continue-on-error` so a failed save on re-run does not fail the whole job

### Why `run_attempt` matters

GitHub Actions cache keys are immutable once written. A job **re-run** gets a new `run_attempt`. Using `run_id` + `run_attempt` avoids “cache already exists” failures that would block persistence of updated SQLite/streak state.

### Operator notes

- Prefer **workflow_dispatch** for intentional re-runs during incidents.
- After a re-run, confirm the latest artifact/cache reflects new rows (export or `check-store`).
- If cache restore yields an empty/old DB, restore from a recent successful run’s uploaded `data/` artifact (if configured) or known-good local backup — see Rollback.

---

## 8. SharePoint activation checklist

Day-1 production path is **SQLite**. SharePoint is a pluggable backend (`STORAGE_BACKEND=sharepoint`); flip only when Entra/site/list are ready.

### Checklist

1. Complete **[scripts/provision_sharepoint_list.md](provision_sharepoint_list.md)**:
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

3. Set `STORAGE_BACKEND=sharepoint` on the daily workflow (and local `.env` for smoke tests).
4. Smoke:

   ```bash
   python -m opportunity_ingest check-store
   python -m opportunity_ingest run --write --max-create 5
   ```

5. Optional one-time migration: export SQLite CSV → manual import or scripted creates. **No dual-write** in Phase 1.
6. Note: `export-csv` remains sqlite-oriented; use SharePoint list views for human Status triage after the flip.

Do **not** require SharePoint for day-1 go-live. Azure secrets are optional while `STORAGE_BACKEND=sqlite`.

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

- Dispatch with `dry_run=true`, or set `INGEST_MAX_CREATE=0` only after policy criteria (or temporarily set a very low `max_create` via dispatch, e.g. `1` or `10`) to limit blast radius while debugging.

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
