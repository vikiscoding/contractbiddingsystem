# Opportunity Ingest — one key processor in the system

**Audience:** operators, capture leads, stakeholders (non-engineers OK).  
**As-of:** 2026-08-11  
**Package:** `opportunity_ingest` (this repo)

This page explains **what this app is**, **where it sits** in the wider contract-bidding / capture setup, **what triggers it**, and **what comes out** — in plain language.

| Want… | Go to |
|-------|--------|
| Keys & how to turn features on | [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md) |
| Technical architecture | [`AS_BUILT.md`](AS_BUILT.md) |
| Day-to-day ops | [`../scripts/ops_runbook.md`](../scripts/ops_runbook.md) |
| What is / isn’t built | [`STATUS.md`](STATUS.md) · [`BACKLOG.md`](BACKLOG.md) |

---

## 1. Plain-language description

**In one sentence:**  
This application is a **scheduled monitor for public tenders**. It downloads open notices, retains those that match configured capabilities, stores them, optionally ranks them in plain English with Grok, and can **notify Slack or Teams** when a score meets the threshold.

**What it is not:**

- Not the company website (e.g. Atlas Flow Group marketing site)  
- Not a bot that submits bids  
- Not a full CRM or proposal writer  
- Not an automated agent that sets Status  

**What a human still does:**  
Open the notice link, set Status (New → Reviewing → Bidding / Discarded), and choose pursue / pass.

---

## 2. Where this processor sits (end-to-end)

Capture is a sequence of stages. This repository implements **one stage**: find and alert on new public opportunities.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│  Wider capture / bidding system (conceptual)                            │
│                                                                         │
│  [1] Public market data                                                 │
│       CanadaBuys open tender notices (CSV open data)                    │
│              │                                                          │
│              ▼                                                          │
│  [2] ★ THIS APP — Opportunity Ingest processor ★                        │
│       Filter → score → store → optional AI rank → notify                │
│              │                                                          │
│              ▼                                                          │
│  [3] Human capture workspace                                            │
│       SQLite / Google Sheets (Ingest + Ranked) / CSV export             │
│       Slack (or Teams) channel cards with “Open notice”                 │
│              │                                                          │
│              ▼                                                          │
│  [4] Human decision (outside this app’s automation)                     │
│       Status, notes, bid / no-bid, proposals, submission                │
│              │                                                          │
│              ▼                                                          │
│  [5] Company positioning (related, not the same code)                   │
│       Company website → informs keywords.yaml and objectives.yaml       │
└─────────────────────────────────────────────────────────────────────────┘
```

| Step | Role | This repo? |
|------|------|------------|
| **1. Market feed** | Public open-tender list | Download only |
| **2. Ingest processor** | Filter, score, store, rank, alert | **Yes — primary job** |
| **3. Workspace views** | Sheets / Slack / CSV for people | Writes **views** / messages |
| **4. Decision & bid** | Humans pursue/pass | **No auto-bid** |
| **5. Brand / capabilities site** | Company positioning | Config only (`keywords` / `objectives`) |

---

## 3. What this processor does (steps inside the app)

| Internal step | Plain language | Technical name |
|---------------|----------------|----------------|
| A. Download | Get today’s open tender CSV from CanadaBuys | `download` / `run` |
| B. Parse | Read bilingual columns; prefer English | `parse` |
| C. Keyword filter | Keep rows that match our capability words | `filter_keywords` + `config/keywords.yaml` |
| D. Rule score | Give a 0–100 “relevance” number (rules, not AI) | `score` → `RelevanceScore` |
| E. Dedupe + store | Save **new** opportunities only; never overwrite human Status | SQLite create-only |
| F. Optional Sheets Ingest | Full-replace a spreadsheet tab for browsing | `sync-sheets` |
| G. Optional Grok rank | Rewrite in plain English; score fit to company objectives | `interpret-rank` → `fit_score` |
| H. Optional Sheets Ranked | Full-replace ranked tab | `sync-rank-sheets` / auto with rank |
| I. Optional Slack / Teams | Ping channel when score ≥ threshold (default **40**) | `notify` match alerts |

---

## 4. Trigger points (when this processor runs)

Nothing runs by itself unless **you or a scheduler** starts it.

| Trigger | How | Typical use |
|---------|-----|-------------|
| **Manual CLI** | Operator runs a command in the project folder | Smoke tests, ad-hoc refresh |
| **Windows Task Scheduler** | `scripts/daily_sync.ps1` (or similar) on a PC | Local daily job |
| **GitHub Actions schedule** | Workflow cron (e.g. ~14:00 UTC) | Unattended cloud daily |
| **Manual Actions** | `workflow_dispatch` on GitHub | One-off remote run |
| **Follow-on commands** | After ingest, human/script runs rank or sheets | Rank + Slack after store is warm |

### Command-level triggers

| You run… | Trigger effect |
|----------|----------------|
| `python -m opportunity_ingest run` | **Dry-run** filter/score (no DB write by default) |
| `python -m opportunity_ingest run --write` | **Processor write path:** create new DB rows; if score ≥ 40 → Slack/Teams match card |
| `python -m opportunity_ingest sync-sheets` | Push DB → Sheets **Ingest** tab |
| `python -m opportunity_ingest interpret-rank` | Grok ranks stored rows; Sheets **Ranked**; if fit ≥ 40 → Slack/Teams |
| `python -m opportunity_ingest sync-rank-sheets` | Re-push last ranking JSON to Sheets (no Grok call) |
| `python -m opportunity_ingest export-csv` | Snapshot file for Excel |
| `python -m opportunity_ingest check-store` | Health only |

### Score thresholds that trigger alerts

| Signal | Meaning | Default alert bar |
|--------|---------|-------------------|
| **RelevanceScore** | Rule-based match after keywords | ≥ **40** on **new creates** (`run --write`) |
| **Grok fit_score** | Fit vs `config/objectives.yaml` | ≥ **40** after `interpret-rank` |

Configured in `config/notify.yaml` / `TEAMS_MATCH_SCORE_THRESHOLD` (shared for Slack + Teams).

---

## 5. Inputs and outputs (black box)

### Inputs

| Input | Source |
|-------|--------|
| CanadaBuys open tender CSV | Public download or `--csv` file |
| Keyword list | `config/keywords.yaml` (eng-owned) |
| Company objectives (for Grok) | `config/objectives.yaml` |
| Secrets | Root `.env` (never committed) |
| Existing DB keys | SQLite (dedupe so we don’t double-add) |

### Outputs

| Output | What a human sees |
|--------|-------------------|
| SQLite DB | Master list of opportunities (`data/contract_opportunities.db`) |
| CSV export | Spreadsheet file for offline review |
| Google Sheets **Ingest** | Grid of opportunities (overwritten each sync) |
| Google Sheets **Ranked** | Grok-sorted plain-English brief |
| Local ranking files | `data/rankings/interpret-*.md` |
| **Slack channel** | Block Kit card: score, summary, **Open notice** button |
| Teams channel | Adaptive Card (ops + optional match) |
| Run logs | `logs/run-*.json` metrics |

---

## 6. Slack as a notification channel

When the processor finds a high-enough match, Slack is a **notification channel**, not a second database.

```text
SQLite (or Grok rank result)
        │ score ≥ 40
        ▼
  notify module (designed card)
        │
        ▼
  Slack channel (configured via SLACK_CHANNEL_ID)
        │ human clicks "Open notice"
        ▼
  Tender portal page → human decides
```

**Setup:** bot token + channel — [`../scripts/slack_cli_setup.md`](../scripts/slack_cli_setup.md).

---

## 7. Guarantees

| Promise | Why it matters |
|---------|----------------|
| **Create-only store** | Re-running ingest does not wipe Status or Notes |
| **Dedupe by ID + link** | Same tender is not added twice |
| **Dry-run by default** | `run` without `--write` does not change the DB |
| **Sheets are views** | Spreadsheet is not the system of record |
| **Grok does not write Status** | AI ranks; humans still own triage |
| **Alerts are CTAs** | Slack/Teams open the notice; no auto-bid |

---

## 8. Who owns what

| Role | Owns |
|------|------|
| **This processor (code)** | Download, filter, score, store, rank, notify |
| **Engineering** | Keywords, objectives, notify thresholds, app code |
| **Operators** | Secrets, schedules, Status triage, bid decisions |
| **Capture lead** | Act on Slack/Sheets; pursue/pass |

---

## 9. Related pages

| Doc | Purpose |
|-----|---------|
| [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md) | Keys, enable each output |
| [`AS_BUILT.md`](AS_BUILT.md) | Modules and pipeline detail |
| [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) | Hard rules for data |
| [`BACKLOG.md`](BACKLOG.md) §7 | **Future:** multi-geography source mesh, self-sustaining loop (lawful) |
| [`../README.md`](../README.md) | Quick start |
| [`../AGENTS.md`](../AGENTS.md) | Rules for AI coding agents |

---

## 10. Future direction (not built)

Long-term product intent is **not** “scrape the entire internet.”  
It is a **lawful multi-source opportunity mesh** (any geography we enable), with human Status feeding **suggested** filter improvements — still create-only, still no auto-bid.

Full register, architecture sketch, and decision principles: **[`BACKLOG.md`](BACKLOG.md) §7**.

---

*This document is the operator overview for the ingest processor. Update it when triggers, thresholds, or outputs change.*
