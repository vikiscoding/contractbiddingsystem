# Project status

Living snapshot of implementation and ops readiness.  
**Update this file when go-live state, integrations, or known issues change.**

| Field | Value |
|-------|--------|
| **Last updated** | 2026-08-11 |
| **Phase** | Phase 1 ingest + optional Grok interpret-rank (post-ingest) |
| **Overall status** | **Ingest implemented & locally validated; Grok/Ranked coded + unit-tested; live Grok E2E pending** |
| **GitHub** | Private repository (see `git remote -v`) |
| **Default branch** | `main` |
| **Recommended next** | **Human plug-in:** [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md). Eng roadmap: [`BACKLOG.md`](BACKLOG.md). Long-horizon multi-geo vision: BACKLOG **§7**. |

---

## 1. Capability matrix

| Capability | Status | Notes |
|------------|--------|--------|
| Download CanadaBuys open tender CSV | **Working** | Browser User-Agent required (403 without) |
| Bilingual parse + keyword filter + score | **Working** | `config/keywords.yaml` eng-owned; **single global pack** (no per-site packs yet) |
| SQLite create-only store | **Working** | System of record (day-1) |
| Dedupe OpportunityID + Link | **Working** | Unique indexes + pre-check |
| CLI dry-run / `--write` / export-csv | **Working** | Only `--write` persists |
| Google Sheets `Ingest` full-replace | **Working (local)** | `sync-sheets`; service account + shared sheet |
| Google Sheets `Ranked` full-replace | **Implemented** | From Grok report; same sheet/SA; **never** writes `Ingest` |
| Grok interpret-rank (post-ingest) | **Implemented (optional)** | `interpret-rank`; needs `XAI_API_KEY` + `.[ai]`; does **not** mutate SQLite |
| Re-push rankings without Grok | **Implemented** | `sync-rank-sheets` from latest `data/rankings/interpret-*.json` |
| SharePoint Graph adapter | **Implemented, not activated** | Needs Entra + Sites.Selected grant |
| Teams Workflows ops notify | **Code ready** | hard fail / partial / streak → `TEAMS_WEBHOOK_URL` |
| Teams high-match capture ping | **Implemented** | score ≥40; Adaptive Card + OpenUrl CTA; `config/notify.yaml` |
| Slack high-match capture ping | **Implemented** | ≥40; Slack CLI `SLACK_BOT_TOKEN` + channel via `chat.postMessage`; webhook legacy fallback |
| GitHub Actions CI (`ci.yml`) | **In repo** | ruff + pytest |
| GitHub Actions daily ingest | **In repo, not yet scheduled live** | Needs vars/secrets; enable after calibration |
| Source/website-type keyword packs | **Not built** | Tracked: [`BACKLOG.md`](BACKLOG.md) B-01, B-02 |
| AI auto-suggest keywords CLI | **Not built** | Tracked: B-03 |
| Multi-source / auto-bidding | **Out of scope** | Non-goals; see BACKLOG §3 |

---

## 2. Validated local runs

### 2.1 Ingest + Sheets Ingest (2026-08-10)

| Step | Result |
|------|--------|
| `pip install -e .` / `.[sheets]` | OK |
| `download-sample` | OK (~6.2 MB open tender CSV) after UA fix |
| Dry-run on sample | parsed≈**893**, filtered≈**83**, mapped≈**27** (many map skips: empty Link) |
| `run --write` (capped) | SQLite rows created (~27 local) |
| `export-csv` | OK → `data/export-opportunities.csv` (local, gitignored) |
| `sync-sheets` | OK → rows written to Google Sheet tab **`Ingest`** |
| Unit tests (ingest era) | **pytest** green |

### 2.2 Grok interpret-rank + Ranked tab (2026-08-11)

| Step | Result |
|------|--------|
| Code: `interpret_rank.py`, CLI, `objectives.yaml` | **In tree** |
| Code: `sync_rankings_to_sheet` / `sync-rank-sheets` | **In tree** |
| Docs: DATA_UPDATE, AGENTS, README, playbook | **Updated** |
| Unit tests (mocked Grok, no live xAI) | **pytest green** (210 as of doc update) |
| Live `XAI_API_KEY` → real Grok ranking | **Not recorded as validated** (see BACKLOG B-07) |
| Live push to sheet tab **`Ranked`** | **Not recorded as validated** (B-07) |

---

## 3. Local configuration checklist

| Item | Expected | Notes |
|------|----------|--------|
| Python venv | `.venv` | Activate before CLI |
| Root `.env` | Present (gitignored) | **Not** `scripts/.env` |
| `STORAGE_BACKEND` | `sqlite` | Day-1 default |
| `secrets/google-service-account.json` | Present (gitignored) | Exact `.json` name (not `.json.json`) |
| `GOOGLE_SHEET_ID` / `Ingest` tab | Configured | Sheet shared Editor with SA email |
| `GOOGLE_SHEET_RANK_TAB` | `Ranked` (default) | Created on first rank sync if missing |
| `XAI_API_KEY` | Optional | Required only for `interpret-rank` |
| `config/objectives.yaml` | Present | Eng-owned frame for Grok (template until customized) |
| `TEAMS_WEBHOOK_URL` | Optional | Alerts silent if unset |
| SharePoint secrets | Not required | Until SP activation |

---

## 4. Data / integration posture

| Store / view | Role | Live? |
|--------------|------|-------|
| SQLite `data/contract_opportunities.db` | **System of record** | Local yes |
| Google Sheets `Ingest` | Derived opportunity view (full replace) | Yes (user sheet) |
| Google Sheets `Ranked` | Derived Grok ranking view (full replace) | Code ready; live E2E pending |
| Google Sheets `Review` (if used) | Human notes | Operator-owned |
| `data/rankings/*` | Local Grok reports | Local only; gitignored |
| SharePoint list | Alternate SoR | Not activated |
| Teams | Failure / streak notify | Not configured |

**Data rules:** see [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md).  
Create-only ingest; never silent-truncate Link; Sheets is not SoR; Grok never rewrites SQLite Status/Notes/scores.

---

## 5. Known issues / pitfalls

1. CanadaBuys **403** if User-Agent missing (fixed in `download.py`).  
2. Windows **double extension** on service account file (`.json.json`).  
3. Keyword hits with **empty notice URL** → map skip (by design).  
4. `MAX_CREATE=0` means **unlimited**, not “block writes”.  
5. Daily Actions workflow does **not** run Sheets sync or interpret-rank by default.  
6. `export-csv` / `sync-sheets` / `interpret-rank` are **sqlite-oriented**.  
7. Rule keywords are **global only** — false positives (e.g. construction “service desk”) still possible; type packs not built (BACKLOG B-01/B-02).  
8. `objectives.yaml` still template company name until customized.  
9. Without `XAI_API_KEY`, `interpret-rank` exits usage error (expected).  

---

## 6. Go-live checklist (GitHub Actions)

- [x] Code on default branch (`main`) of the GitHub remote  
- [ ] CI green on push (watch **Actions** tab after first push)  
- [ ] Repo variable `INGEST_MAX_CREATE=50` (or desired)  
- [ ] Secret `TEAMS_WEBHOOK_URL` (recommended)  
- [ ] Optional Sheets: secrets `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` + workflow step  
- [ ] Optional Grok: secret `XAI_API_KEY` + workflow step (BACKLOG B-06)  
- [ ] Manual `workflow_dispatch` dry-run / capped write successful  
- [ ] Live interpret-rank + Ranked tab smoke (BACKLOG B-07)  
- [ ] Enable schedule confidence after calibration week  
- [ ] Operators following [`scripts/ops_runbook.md`](../scripts/ops_runbook.md)  

---

## 7. Doc entry points

| Need | Doc |
|------|-----|
| **Human keys + plug-and-play + function list + roadmap** | [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md) |
| **Processor role, triggers, outputs** | [`PROCESSOR_OVERVIEW.md`](PROCESSOR_OVERVIEW.md) |
| LLM / agent context | [`../AGENTS.md`](../AGENTS.md) |
| Architecture (what exists) | [`AS_BUILT.md`](AS_BUILT.md) |
| **Discussed / not built** | [`BACKLOG.md`](BACKLOG.md) |
| Data MUST/MUST NOT | [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) |
| How to change code | [`CHANGE_PLAYBOOK.md`](CHANGE_PLAYBOOK.md) |
| Decisions (ADR) | [`DECISIONS.md`](DECISIONS.md) |
| Doc index | [`INDEX.md`](INDEX.md) |
| Sheets setup | [`../scripts/google_sheets_setup.md`](../scripts/google_sheets_setup.md) |
| Ops | [`../scripts/ops_runbook.md`](../scripts/ops_runbook.md) |

---

## 8. How to update this file

When something material changes, edit §1–§6 and bump **Last updated**. Examples:

- First successful Actions scheduled run  
- Live Grok + Ranked tab validation (close B-07)  
- SharePoint activation  
- Sheets / interpret-rank wired into Actions  
- Keyword/policy changes that affect typical filtered volume  
- New known issues  
- Backlog item shipped → mark Done in BACKLOG + capability matrix  

Keep STATUS factual and short; put deep rules in DATA_UPDATE_DIRECTIVES / AS_BUILT; put unbuilt designs in BACKLOG.
