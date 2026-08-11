# Data update directives

**Normative rules for any agent or developer that writes, migrates, or syncs opportunity data.**  
Violating these breaks dedupe, human review, or external views.

Last updated: 2026-08-11.

---

## 1. System of record

| Store | Role | Default |
|-------|------|---------|
| **SQLite** `data/contract_opportunities.db` | **System of record (day-1)** | `STORAGE_BACKEND=sqlite` |
| **SharePoint list** | Alternate store when activated | `STORAGE_BACKEND=sharepoint` |
| **Google Sheets `Ingest` tab** | **Derived view only** (full replace) | `sync-sheets` after writes |
| **Google Sheets `Ranked` tab** | **Derived Grok ranking view** (full replace) | `interpret-rank` / `sync-rank-sheets` |
| **`data/rankings/*`** | Local Grok reports (not SoR) | `interpret-rank` |
| **CSV export** | Snapshot for Excel / import | `export-csv` |

**MUST:** Treat SQLite (or active SharePoint backend) as authoritative for create/dedupe.  
**MUST NOT:** Treat Google Sheets as the database of record.  
**MUST NOT:** Dual-write SQLite and SharePoint in Phase 1 (pick one `STORAGE_BACKEND`).

---

## 2. Write path (ingest)

### 2.1 When writes happen

| Command | Writes store? |
|---------|----------------|
| `run` (default) | **No** (dry-run) |
| `run --dry-run` | **No** |
| `run --write` | **Yes** (creates only) |
| `export-csv` | No store write; writes CSV file |
| `sync-sheets` | No SQLite write; **replaces** Sheet tab |
| `download-sample` | Writes sample CSV file only |
| `interpret-rank` | **No SQLite write**; writes `data/rankings/*`; may full-replace Sheets **Ranked** tab |
| `sync-rank-sheets` | **No SQLite write**; full-replace Sheets **Ranked** tab from ranking JSON |

**MUST:** Use `--write` for persistence.  
**MUST NOT:** Rely on `DRY_RUN` env to enable writes (it never does).

### 2.2 Create-only policy

**MUST:** Only **insert** new opportunities.  
**MUST NOT:** UPDATE existing rows on re-ingest (closing dates, titles, descriptions).  
**MUST NOT:** DELETE rows during ingest.  
**Rationale:** Humans own `Status` and `Notes` after create.

**Operator rule for amendments:** Open the notice `Link` on CanadaBuys; do not expect ingest to refresh the row.

### 2.3 Eligibility for create

A candidate is written only if all hold:

1. Passed keyword filter (any configured term in allowed fields).
2. Mapped successfully to `OpportunityFields` (required Title, OpportunityID, Link).
3. Not duplicate: OpportunityID ∉ existing AND normalized Link ∉ existing.
4. Create-attempt budget remaining (`MAX_CREATE` / `--max-create`).

**MUST:** Skip (log error) if Title empty/whitespace or Link empty after mapping.  
**MUST NOT:** Silent-truncate Link to fit a length limit.  
**MUST:** Truncate Title to 255 and Description to 2000 only (not Link).

### 2.4 OpportunityID

**MUST:** `OpportunityID = referenceNumber` if present, else `solicitationNumber`.  
**MUST:** Strip whitespace when comparing/storing IDs.  
**MUST:** Skip row if both IDs empty.

### 2.5 Link normalization (dedupe)

```text
normalize_link(url) = strip → lower → rstrip('/')
```

**MUST:** Use the same normalization on load_existing_keys and before insert.  
**MUST:** Store human-readable full URL string (not Hyperlink object required for SQLite).

### 2.6 MAX_CREATE semantics

| Value | Meaning |
|-------|---------|
| unset / default **50** | Soft attempt budget |
| `N >= 1` | At most **N create API attempts** this run |
| **`0`** | **Unlimited** attempts |
| negative | **Invalid** (CLI usage error / settings ValidationError) |

**MUST:** Count both successful and failed creates as attempts.  
**MUST NOT:** Use `MAX_CREATE=0` to “limit blast radius” (that uncaps). Use small N (10–25) for containment.  
**Steady-state policy:** keep 50 → raise to 100 if typical filtered &lt; 30/day → unlimited only after **7 consecutive dry-runs** with &lt; 50 filtered candidates/day.

### 2.7 Status on create

**MUST:** Set `Status = New` on create.  
**MUST NOT:** Overwrite Status on later ingest.  
**Human Status values:** `New` | `Reviewing` | `Relevant` | `Bidding` | `Discarded`.

### 2.8 Grok interpret-rank (post-ingest)

**MUST:** Treat AI ranking as a **derived report**, not the system of record.  
**MUST NOT:** UPDATE `contract_opportunities` Status, Notes, RelevanceScore, Title, Description, or Link from Grok output.  
**MUST:** Persist local interpret-rank files under `data/rankings/` (JSON + Markdown) or an explicit `--out-dir`.  
**MUST:** Keep company objectives in engineering-owned `config/objectives.yaml` (not free-text secrets).  
**MUST NOT:** Commit `XAI_API_KEY` or ranking report dumps that contain secrets.  
**MUST:** Google Sheets ranking push targets the **Ranked** tab only (or another non-`Ingest` name via `GOOGLE_SHEET_RANK_TAB`).  
**MUST NOT:** Write Grok rankings into the opportunity **`Ingest`** tab (code refuses this).

---

## 3. Google Sheets sync directives

### 3.1 Opportunity tab (`sync-sheets`)

Command: `python -m opportunity_ingest sync-sheets`

| Rule | Detail |
|------|--------|
| **MUST** | Source rows from SQLite via `list_rows()` / same columns as `export-csv` |
| **MUST** | Full **clear + rewrite** of target tab (default `Ingest`) |
| **MUST NOT** | Partial append-only as the default Phase 1 mode |
| **MUST NOT** | Sync into a human `Review` tab without explicit product change |
| **MUST** | Require service account file **or** inline JSON; sheet shared as Editor |
| **MUST** | File name exactly `*.json` (Windows double-extension `.json.json` is a known failure mode) |
| **MUST** | Load `.env` from **repo root** (not `scripts/.env`) |

### 3.2 Ranked tab (`interpret-rank` / `sync-rank-sheets`)

| Rule | Detail |
|------|--------|
| **MUST** | Full **clear + rewrite** of target tab (default `Ranked` / `GOOGLE_SHEET_RANK_TAB`) |
| **MUST** | Same spreadsheet + service account as opportunity sync (`GOOGLE_SHEET_ID`) |
| **MUST NOT** | Target the `Ingest` tab for rankings |
| **Default** | When `GOOGLE_SHEET_ID` is set, `interpret-rank` syncs Ranked unless `--no-sync-sheets` |
| **Re-push** | `sync-rank-sheets` uses latest `data/rankings/interpret-*.json` (no Grok call) |

**After ingest recommended sequence:**

```text
run --write → sync-sheets → (optional) interpret-rank → (optional) export-csv
```

**MUST NOT:** Two-way sync Status from Sheets back to SQLite in Phase 1 (out of scope).

---

## 4. CSV export directives

Command: `export-csv [--out PATH]`

- Default path: `{DATA_DIR}/export-opportunities.csv`
- Encoding: UTF-8 with BOM (Excel-friendly)
- Columns: `SqliteOpportunityStore.EXPORT_COLUMNS` (logical schema + id)
- **sqlite only** in current implementation

---

## 5. SharePoint directives (when activated)

- Set `STORAGE_BACKEND=sharepoint` + Azure + site/list IDs.
- Create-only Graph POSTs; Link = plain text URL string.
- No `SkipDuplicate` from Graph unique indexes in Phase 1 — single writer assumed.
- Provisioning: `scripts/provision_sharepoint_list.md` (Sites.Selected chicken-and-egg grant).
- **MUST NOT** enable schedule on SharePoint until `check-store` succeeds.

---

## 6. External source directives (CanadaBuys)

| Rule | Detail |
|------|--------|
| Primary URL | `https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv` |
| **MUST** | Send browser-like `User-Agent` (403 without it) |
| **MUST** | One retry then hard-fail |
| **MUST** | Parse with `utf-8-sig`; case-insensitive header resolve |
| **MUST** | EN field preferred; FR if EN empty |
| Closing times | Naive timestamps treated as fixed **UTC−05:00** then stored UTC |
| Schedule | Prefer after ~09:00 America/Toronto; Actions uses `0 14 * * *` UTC |

---

## 7. Streak / notify (side data)

| Artifact | Update rule |
|----------|-------------|
| `state/zero_new_streak.json` | Only on **successful write runs**; calendar-day aware; same UTC day re-run does not double-count zeros |
| Teams webhook | Hard fail / high partial errors / zero-streak threshold; optional |
| `logs/run-*.json` | Every run; metrics only |

**MUST NOT:** Treat streak JSON as opportunity data store.

---

## 8. Forbidden data operations (Phase 1)

- Historical backfill of closed tenders from archives  
- MERX / provincial multi-source merge without new design  
- ML-based score overwriting rule score without design  
- Auto-changing Status based on keywords  
- Storing contact PII beyond what is already in open tender text fields in Description (prefer not to expand contact scraping)  
- Committing DB, exports, secrets, or live sample CSVs with secrets  

---

## 9. Schema (logical — both SQLite and SharePoint)

| Field | Required on create | Notes |
|-------|--------------------|-------|
| Title | Yes | max 255 |
| OpportunityID | Yes | unique |
| Source | Yes | `CanadaBuys` |
| Buyer | No | |
| Link | Yes | full URL, never truncated |
| PublishedDate | No | date |
| ClosingDate | No | datetime UTC |
| Category | No | |
| Description | No | max 2000 stored |
| KeywordsMatched | No | |
| RelevanceScore | No | 0–100 |
| Status | Yes | default `New` |
| DateAdded | Yes | UTC on create |
| Notes | No | empty on create |

SQLite unique indexes: `OpportunityID`, `Link`.

---

## 10. Validation checklist for data-related PRs

- [ ] Dry-run still default  
- [ ] Create-only preserved  
- [ ] Dedupe tests still pass  
- [ ] Link never truncated in map/store  
- [ ] MAX_CREATE attempt semantics unchanged unless intentionally redesigned  
- [ ] Sheets sync still full-replace and documented if behavior changes  
- [ ] No secrets in git  
