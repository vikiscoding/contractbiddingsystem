# Project status

Living snapshot of implementation and ops readiness.  
**Update this file when go-live state, integrations, or known issues change.**

| Field | Value |
|-------|--------|
| **Last updated** | 2026-08-10 |
| **Phase** | Phase 1 — CanadaBuys open tender ingest |
| **Overall status** | **Implemented & manually validated (local); code on GitHub** |
| **GitHub** | https://github.com/vikiscoding/contractbiddingsystem (**private**) |
| **Default branch** | `main` |
| **Recommended next** | Configure Actions secrets/vars → `workflow_dispatch` smoke → enable schedule |

---

## 1. Capability matrix

| Capability | Status | Notes |
|------------|--------|--------|
| Download CanadaBuys open tender CSV | **Working** | Browser User-Agent required (403 without) |
| Bilingual parse + keyword filter + score | **Working** | `config/keywords.yaml` eng-owned |
| SQLite create-only store | **Working** | System of record (day-1) |
| Dedupe OpportunityID + Link | **Working** | Unique indexes + pre-check |
| CLI dry-run / `--write` / export-csv | **Working** | Only `--write` persists |
| Google Sheets full-replace sync | **Working (local)** | `sync-sheets`; service account + shared sheet |
| SharePoint Graph adapter | **Implemented, not activated** | Needs Entra + Sites.Selected grant |
| Teams Workflows notify | **Code ready** | Needs `TEAMS_WEBHOOK_URL` |
| GitHub Actions CI (`ci.yml`) | **In repo** | Runs on push/PR once remote exists |
| GitHub Actions daily ingest | **In repo, not yet scheduled live** | Needs remote + vars/secrets; enable after calibration |
| Multi-source / AI ranking | **Out of scope** | Phase 1 non-goals |

---

## 2. Validated local runs (2026-08-10)

| Step | Result |
|------|--------|
| `pip install -e .` / `.[sheets]` | OK |
| `download-sample` | OK (~6.2 MB open tender CSV) after UA fix |
| Dry-run on sample | parsed≈**893**, filtered≈**83**, mapped≈**27** (many map skips: empty Link) |
| `run --write` (capped) | SQLite rows created |
| `export-csv` | OK → `data/export-opportunities.csv` (local, gitignored) |
| `sync-sheets` | OK → **27 rows** written to Google Sheet tab `Ingest` |
| Unit tests | **pytest** green (package + sheets unit tests) |

---

## 3. Local configuration checklist

| Item | Expected | Notes |
|------|----------|--------|
| Python venv | `.venv` | Activate before CLI |
| Root `.env` | Present (gitignored) | **Not** `scripts/.env` |
| `STORAGE_BACKEND` | `sqlite` | Day-1 default |
| `secrets/google-service-account.json` | Present (gitignored) | Exact `.json` name (not `.json.json`) |
| `GOOGLE_SHEET_ID` / tab | Configured | Sheet shared Editor with SA email |
| `TEAMS_WEBHOOK_URL` | Optional | Alerts silent if unset |
| SharePoint secrets | Not required | Until SP activation |

---

## 4. Data / integration posture

| Store / view | Role | Live? |
|--------------|------|-------|
| SQLite `data/contract_opportunities.db` | **System of record** | Local yes |
| Google Sheets `Ingest` | Derived view (full replace) | Yes (user sheet) |
| Google Sheets `Review` (if used) | Human notes | Operator-owned |
| SharePoint list | Alternate SoR | Not activated |
| Teams | Failure / streak notify | Not configured |

**Data rules:** see [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md).  
Create-only ingest; never silent-truncate Link; Sheets is not SoR.

---

## 5. Known issues / pitfalls

1. CanadaBuys **403** if User-Agent missing (fixed in `download.py`).  
2. Windows **double extension** on service account file (`.json.json`).  
3. Keyword hits with **empty notice URL** → map skip (by design).  
4. `MAX_CREATE=0` means **unlimited**, not “block writes”.  
5. Daily Actions workflow does **not** run Sheets sync by default (add step + secrets when ready).  
6. `export-csv` / `sync-sheets` are **sqlite-oriented**.  

---

## 6. Go-live checklist (GitHub Actions)

- [x] Code on default branch (`main`) of GitHub remote (`vikiscoding/contractbiddingsystem`)  
- [ ] CI green on push (watch **Actions** tab after first push)  
- [ ] Repo variable `INGEST_MAX_CREATE=50` (or desired)  
- [ ] Secret `TEAMS_WEBHOOK_URL` (recommended)  
- [ ] Optional Sheets: secrets `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` + workflow step  
- [ ] Manual `workflow_dispatch` dry-run / capped write successful  
- [ ] Enable schedule confidence after calibration week  
- [ ] Operators following [`scripts/ops_runbook.md`](../scripts/ops_runbook.md)  

---

## 7. Doc entry points

| Need | Doc |
|------|-----|
| LLM / agent context | [`../AGENTS.md`](../AGENTS.md) |
| Architecture | [`AS_BUILT.md`](AS_BUILT.md) |
| Data MUST/MUST NOT | [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) |
| How to change code | [`CHANGE_PLAYBOOK.md`](CHANGE_PLAYBOOK.md) |
| Doc index | [`INDEX.md`](INDEX.md) |
| Sheets setup | [`../scripts/google_sheets_setup.md`](../scripts/google_sheets_setup.md) |
| Ops | [`../scripts/ops_runbook.md`](../scripts/ops_runbook.md) |

---

## 8. How to update this file

When something material changes, edit §1–§6 and bump **Last updated**. Examples:

- First successful Actions scheduled run  
- SharePoint activation  
- Sheets wired into Actions  
- Keyword/policy changes that affect typical filtered volume  
- New known issues  

Keep STATUS factual and short; put deep rules in DATA_UPDATE_DIRECTIVES / AS_BUILT.
