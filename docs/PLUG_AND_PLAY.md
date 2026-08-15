# Plug-and-play guide — human keys & next steps

**Audience:** operators and humans who will turn on what engineering already built.  
**As-of:** 2026-08-11  
**Code status:** features below are **implemented**; they stay idle until secrets and configuration are provided.

| Related docs | |
|--------------|--|
| **What this processor is** | [`PROCESSOR_OVERVIEW.md`](PROCESSOR_OVERVIEW.md) |
| What works now | [`STATUS.md`](STATUS.md) |
| Architecture | [`AS_BUILT.md`](AS_BUILT.md) |
| Future / not built | [`BACKLOG.md`](BACKLOG.md) · roadmap § below |
| Data rules | [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) |
| Daily ops | [`../scripts/ops_runbook.md`](../scripts/ops_runbook.md) |

---

## 1. Big picture (what the product does)

```text
CanadaBuys open tenders (CSV)
        │
        ▼
  keyword filter + rule score (0–100)
        │
        ▼
  SQLite create-only  ◄── system of record
        │
        ├──► export-csv
        ├──► Google Sheets tab Ingest   (view)
        ├──► Grok interpret-rank        (plain English + fit 0–100)
        │         ├──► data/rankings/*.md
        │         └──► Google Sheets tab Ranked
        └──► Teams
                  ├── ops alerts (fail / streak)
                  └── capture pings when score ≥ 40
```

**Not auto-bidding.** Humans still set Status and decide pursue/pass.

---

## 2. Function list (what you can run)

| CLI command | What it does | Needs human key? |
|-------------|--------------|------------------|
| `download-sample` | Download CanadaBuys open-tender CSV sample | No (public; User-Agent in code) |
| `run` | Dry-run ingest (default) | No |
| `run --write` | Create **new** opportunities in SQLite | No for local SQLite |
| `check-store` | Health + key counts | No (sqlite) |
| `export-csv` | Dump SQLite → CSV | No |
| `sync-sheets` | Full-replace Sheets **Ingest** | **Yes** — Google SA + sheet ID |
| `interpret-rank` | Grok rephrase + rank; optional Ranked tab + Teams | **Yes** — `XAI_API_KEY` (+ Sheets/Teams optional) |
| `sync-rank-sheets` | Re-push last ranking JSON → **Ranked** | **Yes** — Google SA + sheet ID |
| *(internal)* Teams match notify | Card when RelevanceScore or Grok fit ≥ threshold | **Yes** — Teams webhook |

**Install extras (one-time on the machine):**

```powershell
pip install -e .
pip install -e ".[sheets]"   # Google Sheets
pip install -e ".[ai]"       # Grok / xAI
```

---

## 3. Keys & secrets checklist (you provide)

Copy `.env.example` → **repo-root** `.env` (never `scripts/.env`). Never commit `.env` or `secrets/`.

| # | Secret / config | Where to get it | Unlocks |
|---|-----------------|-----------------|---------|
| 1 | *(none)* | — | Local ingest + SQLite + export-csv |
| 2 | `GOOGLE_SHEET_ID` | Spreadsheet URL `…/d/<ID>/edit` | Sheets sync |
| 3 | `GOOGLE_SERVICE_ACCOUNT_FILE` or `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Cloud SA key JSON | Sheets API |
| 4 | Share sheet **Editor** with SA email | Sheets UI Share | Sheets write works |
| 5 | `XAI_API_KEY` | [console.x.ai](https://console.x.ai) API keys | `interpret-rank` |
| 6 | `TEAMS_WEBHOOK_URL` | Teams channel → Workflows → “Post when webhook received” | Ops alerts + match fallback |
| 7 | `TEAMS_MATCH_WEBHOOK_URL` *(optional)* | Second Workflows webhook | Dedicated capture channel |
| 8 | `TEAMS_MATCH_SCORE_THRESHOLD` | Default **40** via env or `config/notify.yaml` | When to ping (Teams **and** Slack) |
| 8b | `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` | Slack CLI / Bolt app (`xoxb-` + channel) | High-match Slack posts (preferred) |
| 8c | `SLACK_APP_TOKEN` | Optional `xapp-` for Socket Mode only | Not required for match posts |
| 9 | Azure / SharePoint secrets | Only if `STORAGE_BACKEND=sharepoint` | Alternate store (not required day-1) |
| 10 | GitHub Actions secrets/vars | Repo Settings → Secrets | Unattended daily schedule |

### Minimal `.env` templates

**A — Local SQLite only (works immediately after `pip install -e .`)**

```env
STORAGE_BACKEND=sqlite
DATA_DIR=data
MAX_CREATE=50
LOG_LEVEL=INFO
```

**B — + Google Sheets (Ingest + Ranked)**

```env
GOOGLE_SHEET_ID=1yourSpreadsheetId
GOOGLE_SHEET_TAB=Ingest
GOOGLE_SHEET_RANK_TAB=Ranked
GOOGLE_SERVICE_ACCOUNT_FILE=secrets/google-service-account.json
```

**C — + Grok ranking**

```env
XAI_API_KEY=xai-...
XAI_MODEL=grok-4.5
OBJECTIVES_PATH=config/objectives.yaml
```

**D — + Teams**

```env
TEAMS_WEBHOOK_URL=https://...powerautomate.../invoke
# optional separate capture channel:
# TEAMS_MATCH_WEBHOOK_URL=https://...
TEAMS_MATCH_NOTIFY_ENABLED=true
TEAMS_MATCH_SCORE_THRESHOLD=40
```

**E — + Slack via Slack CLI / Bolt tokens (same match criteria as Teams)**

```env
# https://docs.slack.dev/tools/slack-cli/ — full steps: scripts/slack_cli_setup.md
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C...
# SLACK_APP_TOKEN=xapp-...   # optional; slack run Socket Mode only
SLACK_MATCH_NOTIFY_ENABLED=true
TEAMS_MATCH_SCORE_THRESHOLD=40
```

```powershell
pip install -e ".[slack]"
```

Detailed Sheets steps: [`../scripts/google_sheets_setup.md`](../scripts/google_sheets_setup.md).  
Slack CLI paste-config: [`../scripts/slack_cli_setup.md`](../scripts/slack_cli_setup.md).

---

## 4. Human plug-and-play sequence (recommended order)

Do these in order. Skip optional blocks you do not need yet.

### Step 0 — One-time machine setup (no keys)

```powershell
cd "<repo-root>"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
copy .env.example .env
# edit .env with STORAGE_BACKEND=sqlite at minimum
```

**Verify:**

```powershell
python -m opportunity_ingest --help
python -m opportunity_ingest check-store
```

### Step 1 — Ingest works offline

```powershell
python -m opportunity_ingest download-sample
python -m opportunity_ingest run --csv data/sample-openTenderNotice.csv
python -m opportunity_ingest run --write --csv data/sample-openTenderNotice.csv --max-create 25
python -m opportunity_ingest export-csv
python -m opportunity_ingest check-store
```

**You should see:** SQLite file under `data/`, CSV export, non-zero opportunity count.

### Step 2 — Google Sheets (human actions)

1. Create a Google Cloud **service account** → download JSON key.  
2. Save as `secrets/google-service-account.json` (**not** `.json.json`).  
3. Create a Google Sheet; rename first tab **`Ingest`** (optional tab **`Ranked`** / **`Review`**).  
4. **Share** the sheet with the service account email as **Editor**.  
5. Put `GOOGLE_SHEET_ID` + `GOOGLE_SERVICE_ACCOUNT_FILE` in root `.env`.  
6. `pip install -e ".[sheets]"`  
7. Run:

```powershell
python -m opportunity_ingest sync-sheets
```

**You should see:** Ingest tab filled with opportunity rows (full replace each run).

### Step 3 — Grok ranking (human actions)

1. Create key at [console.x.ai](https://console.x.ai); add credits.  
2. Set `XAI_API_KEY` in root `.env`.  
3. Review/edit **`config/objectives.yaml`** (company frame — currently Atlas Flow Group).  
4. `pip install -e ".[ai]"`  
5. Run:

```powershell
python -m opportunity_ingest interpret-rank --status New --limit 27
```

**You should see:**

- `data/rankings/interpret-*.md`  
- Sheets tab **`Ranked`** updated (if Sheets configured)  
- Console: `top #1 fit=…`

Skip sheet: `--no-sync-sheets`. Skip Teams: `--no-teams`.

### Step 4 — Teams and/or Slack capture pings (human actions)

**Teams**

1. **Workflows** → *Post to a channel when a webhook request is received* → copy URL.  
2. Set `TEAMS_WEBHOOK_URL` (and optionally `TEAMS_MATCH_WEBHOOK_URL`).  

**Slack (CLI / Bolt config)**

1. Install [Slack CLI](https://docs.slack.dev/tools/slack-cli/), run `slack login`, create/install an app with **`chat:write`**.  
2. Paste **Bot User OAuth Token** → `SLACK_BOT_TOKEN=xoxb-...`  
3. Set **channel** → `SLACK_CHANNEL_ID=C...` (invite bot to channel).  
4. `pip install -e ".[slack]"` — see [`../scripts/slack_cli_setup.md`](../scripts/slack_cli_setup.md). 

**Shared criteria**

3. Threshold **40** (`TEAMS_MATCH_SCORE_THRESHOLD` or `config/notify.yaml` → `match.score_threshold`).  
4. Enable flags: `TEAMS_MATCH_NOTIFY_ENABLED` / `SLACK_MATCH_NOTIFY_ENABLED` (default true).  
5. Trigger:

```powershell
# New high rule-score creates:
python -m opportunity_ingest run --write --max-create 10

# Or Grok fits ≥ 40:
python -m opportunity_ingest interpret-rank --limit 27
```

**You should see:** Teams Adaptive Card and/or Slack Block Kit message with summaries + open-notice buttons.  
Ops alerts (hard fail / streak) remain **Teams-only** today (`TEAMS_WEBHOOK_URL`).

### Step 5 — Daily automation (pick one)

| Path | Human work |
|------|------------|
| **Windows Task Scheduler** | Point at `scripts/daily_sync.ps1` (or extend it with `interpret-rank`) | PC must be on |
| **GitHub Actions** | Push `dev`/`main`; set secrets below; run `workflow_dispatch` once | Unattended |

**GitHub secrets / vars to plug:**

| Name | Required for |
|------|----------------|
| `TEAMS_WEBHOOK_URL` | Alerts (recommended) |
| `INGEST_MAX_CREATE` (variable) | Soft create budget (default 50) |
| `GOOGLE_SHEET_ID` + `GOOGLE_SERVICE_ACCOUNT_JSON` | Sheets in CI (optional; add step) |
| `XAI_API_KEY` | interpret-rank in CI (optional; not in workflow by default yet — BACKLOG B-06) |

Workflow file: [`.github/workflows/daily-canadabuys-ingest.yml`](../.github/workflows/daily-canadabuys-ingest.yml).

### Step 6 — Human triage (ongoing, no more keys)

1. Open Sheets **Ingest** or **Ranked**, or `export-csv`.  
2. Set **Status** / Notes on rows you care about (SQLite or Review tab — **not** relying on Ingest if it is auto-replaced).  
3. Act on Teams CTAs (open Link, decide pursue/pass).  
4. Request keyword/objective changes via eng (`config/keywords.yaml`, `config/objectives.yaml`).

---

## 5. Config files you may edit (no rebuild)

| File | Who | Purpose |
|------|-----|---------|
| `.env` | Ops | Secrets + paths (gitignored) |
| `config/keywords.yaml` | Eng | Ingest keyword groups / weights |
| `config/objectives.yaml` | Eng | Grok ranking company frame |
| `config/notify.yaml` | Eng/Ops | Match threshold, max items, enable flag |
| `secrets/google-service-account.json` | Ops | Sheets key (gitignored) |

---

## 6. End-to-end verification (all integrations enabled)

After Steps 0–4:

```powershell
.\.venv\Scripts\Activate.ps1
python -m opportunity_ingest run --write --max-create 50
python -m opportunity_ingest sync-sheets
python -m opportunity_ingest interpret-rank --status New --limit 50
```

| Output | Where |
|--------|--------|
| New rows | SQLite `data/contract_opportunities.db` |
| Opportunity grid | Sheets **Ingest** |
| Grok brief | `data/rankings/interpret-*.md` + Sheets **Ranked** |
| Capture ping | Teams channel if any score ≥ 40 |

---

## 7. Feature readiness vs human plug

| Capability | Code | Human must plug | Live-validated? |
|------------|------|-----------------|-----------------|
| CanadaBuys download + filter + score | Yes | — | Yes (local) |
| SQLite create-only store | Yes | — | Yes |
| export-csv | Yes | — | Yes |
| Sheets **Ingest** | Yes | SA + sheet share + ID | Yes (local) |
| Grok **interpret-rank** | Yes | `XAI_API_KEY` | Yes (local) |
| Sheets **Ranked** | Yes | same Sheets as Ingest | Yes (local) |
| Teams ops alerts | Yes | `TEAMS_WEBHOOK_URL` | Code ready; requires a configured webhook |
| Teams match ≥40 | Yes | webhook + threshold | Code ready; requires a configured webhook |
| Slack match ≥40 | Yes | `SLACK_WEBHOOK_URL` + same threshold | Code ready; requires a configured webhook |
| GitHub daily schedule | Yes | repo secrets + enable schedule | Not fully go-live |
| SharePoint SoR | Yes | Entra + Sites.Selected | Not activated |
| Type-based keyword packs / auto crawl | No | — | See roadmap |

---

## 8. Roadmap (what’s next — not plug-and-play yet)

Full detail: [`BACKLOG.md`](BACKLOG.md). Summary for humans:

| Priority | ID | Item | Blocked on |
|----------|-----|------|------------|
| Now (ops) | B-07 | Confirm Teams webhook live in channel | Human Workflows URL |
| Now (ops) | — | GitHub Actions secrets + first scheduled run | Human repo settings |
| Near | B-06 | Wire interpret-rank + Ranked + Teams into Actions YAML | Secrets + cost policy |
| Near | B-01 / B-02 | Source-type classifier + keyword packs | Product priority |
| Later | B-03 | Grok suggest-keywords (PR only) | Design sign-off |
| Later | B-04 / B-05 | Company-site crawl / notice page crawl | Product + ToS |
| Long horizon | V-1…V-10 | Multi-geography **lawful** source mesh + self-sustaining loop | [`BACKLOG.md`](BACKLOG.md) **§7** |
| Deferred | N-* | Unrestricted web scrape, auto-bid, dual-write, two-way Status | Project guardrails |

**Suggested human order after keys work:**

1. Plug Slack/Teams → prove one match card.  
2. Enable Actions schedule with small `INGEST_MAX_CREATE`.  
3. Weekly: review Ranked + Status triage.  
4. Eng: tune keywords/objectives from real false positives.  
5. Only then: discuss §7 second source / geography pack.

---

## 9. Quick troubleshooting

| Symptom | Check |
|---------|--------|
| CanadaBuys **403** | Code has User-Agent; retry; network block |
| `set XAI_API_KEY` | Root `.env`; restart shell; `pip install -e ".[ai]"` |
| Sheets permission error | Share sheet with **SA email** as Editor |
| SA file not found | Exact path; not `.json.json` |
| Teams silent | Webhook URL set; Workflows enabled; threshold too high vs scores |
| No new SQLite rows | Create-only + dedupe; already ingested IDs skip |
| Ranked empty | Run `interpret-rank` with key; not the same as `sync-sheets` |

---

## 10. Roles and responsibilities

| Role | Does |
|------|------|
| **Operators** | Keys, sheet share, Teams Workflow, Status triage, bid/no-bid |
| **Engineering** | keywords.yaml, objectives.yaml, code, tests, Actions YAML |
| **System (already built)** | Download, filter, score, store, export, Sheets replace, Grok rank, Teams cards |

When something is built but idle, the fix is almost always **this guide §3–4**, not new code.
