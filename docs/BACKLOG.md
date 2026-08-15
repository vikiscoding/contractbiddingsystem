# Backlog — discussed, deferred, or not yet built

**Purpose:** Track ideas and designs that were **discussed or proposed** but are **not implemented** (or only partially documented).  
**Do not treat this as as-built.** For what exists in code, use [`AS_BUILT.md`](AS_BUILT.md) and [`STATUS.md`](STATUS.md).

| Field | Value |
|-------|--------|
| **Last updated** | 2026-08-11 |
| **Owner** | Engineering (product decisions via issues / review) |

---

## How to use this file

| Status | Meaning |
|--------|---------|
| **Proposed** | Discussed; no design decision locked |
| **Designed (not built)** | Approach agreed in conversation/docs; no production code |
| **Deferred** | Explicitly out of current phase |
| **Blocked** | Waiting on secrets, product answer, or dependency |

When an item ships: move a one-line note to `STATUS.md` / `AS_BUILT.md` / `DECISIONS.md`, then mark the backlog row **Done** or remove it.

---

## 1. Built recently (do not re-open as “missing”)

These **are implemented** in code as of 2026-08-11. Listed here only so reviewers do not confuse them with backlog.

| ID | Item | Where |
|----|------|--------|
| B-DONE-1 | Grok post-ingest interpret + fit rank | `interpret_rank.py`, CLI `interpret-rank` |
| B-DONE-2 | Company objectives frame of reference | `config/objectives.yaml` |
| B-DONE-3 | Local ranking reports | `data/rankings/interpret-*.{json,md}` (gitignored) |
| B-DONE-4 | Sheets **Ranked** tab full-replace | `sheets_sync.sync_rankings_to_sheet`, CLI `sync-rank-sheets` |
| B-DONE-5 | Auto sheet push when `GOOGLE_SHEET_ID` set | `interpret-rank` default; `--no-sync-sheets` to skip |
| B-DONE-6 | Hard refuse rankings → `Ingest` tab | `sync_rankings_to_sheet` |
| B-DONE-7 | Optional extras | `pip install -e ".[ai]"`, `".[sheets]"` |
| B-DONE-8 | Atlas Flow Group site-tuned keywords + objectives | `config/keywords.yaml`, `config/objectives.yaml` (crawl 2026-08-11) |
| B-DONE-9 | Teams high-match capture pipeline (≥40 score) | `config/notify.yaml`, `notify_match_alerts`, ingest write + interpret-rank |
| B-DONE-10 | Slack high-match engine (CLI/Bolt tokens + legacy webhook) | `SLACK_BOT_TOKEN`/`SLACK_CHANNEL_ID`, `slack-sdk`, `scripts/slack_cli_setup.md` |

Normative rules: [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) §2.8, §3.2.

**Note (2026-08-11):** Keyword and objective packs were derived from a review of the
Atlas Flow Group public site (home, services, approach, about, contact).
Automated site crawl → YAML (B-04) remains unbuilt; this was a one-off engineering tuning pass.

---

## 2. Active backlog (discussed, not built)

### B-01 — Source / website-type classifier  
| | |
|--|--|
| **Status** | **Designed (not built)** |
| **Discussed** | 2026-08-11 — model keywords by interpreting “website type” / notice context |
| **Intent** | Classify each notice by portal (CanadaBuys / MERX / Ariba host), instrument (RFI/RFP/RFSA/ITQ), and category family (services vs construction) **before** keyword matching |
| **Proposed approach** | Cheap rules on URL + title/category cues → `SourceType` labels; no LLM required for daily path |
| **Depends on** | Product answers: which “type” axes matter first (portal vs instrument vs company site) |
| **Out of scope for now** | Full multi-source crawlers |

### B-02 — Keyword packs by type  
| | |
|--|--|
| **Status** | **Designed (not built)** |
| **Discussed** | 2026-08-11 — “most appropriate keywords from website type” |
| **Intent** | Split `keywords.yaml` into `global` + packs (`by_portal`, `by_category`, `by_instrument`); active terms = union of packs for classified type |
| **Proposed approach** | Extend `filter_keywords.py` loader; keep rule-based match engine |
| **Constraint** | Keywords remain **eng-owned** (D-10); no silent AI rewrite of production YAML |

### B-03 — Grok `suggest-keywords` (human-in-the-loop)  
| | |
|--|--|
| **Status** | **Proposed** |
| **Discussed** | 2026-08-11 — AI for discovery, not silent filter mutation |
| **Intent** | Offline/on-demand CLI that reads recent opportunities + false positives + `objectives.yaml` and **proposes** a keywords.yaml patch (PR), does not auto-merge |
| **Depends on** | B-01/B-02 optional; `XAI_API_KEY` already used by interpret-rank |
| **Must not** | Auto-edit `config/keywords.yaml` in the daily pipeline |

### B-04 — Company website → capability vocabulary  
| | |
|--|--|
| **Status** | **Proposed** |
| **Discussed** | 2026-08-11 — alternate “compare against” design: crawl *our* site, not only tender portals |
| **Intent** | Extract services language from company website sections → seed objectives + keyword suggestions |
| **Depends on** | Product: real company URL + which pages are authoritative |
| **Note** | Distinct from tender-portal type packs (B-01/B-02) |

### B-05 — Notice `Link` page crawl / enrichment  
| | |
|--|--|
| **Status** | **Proposed** |
| **Discussed** | 2026-08-11 — CSV description often thin; some rows already point at MERX/Ariba |
| **Intent** | Optional fetch of notice abstract HTML to improve filter/rank input |
| **Risks** | ToS, rate limits, auth walls, non-determinism; create-only store must not overwrite existing rows with “refresh” without new design |
| **Constraint** | Never invent Links; never silent-truncate Links |

### B-06 — Wire Grok rank + Ranked Sheets into GitHub Actions  
| | |
|--|--|
| **Status** | **Deferred** (ops) |
| **Intent** | After `run --write` (+ optional `sync-sheets`), run `interpret-rank` in Actions with `XAI_API_KEY` + sheet secrets |
| **Depends on** | Live Grok validation, cost/budget policy, secrets on repo |

### B-07 — Live E2E validation of interpret-rank + Ranked tab  
| | |
|--|--|
| **Status** | **Blocked** (operator secrets / credits) |
| **Intent** | Document a successful live run: `XAI_API_KEY` + real Grok call + Ranked tab visible on shared sheet |
| **Current** | Unit tests mock Grok; Sheets ranking helpers tested without network; live path not recorded as validated in STATUS §2 |

---

## 3. Explicit phase non-goals (still deferred)

Carried from Phase 1 design / AGENTS hard rules. These items are **intentionally deferred**.

| ID | Item | Notes |
|----|------|--------|
| N-1 | Multi-source first-class adapters (MERX/municipal as ingest SoR) | CanadaBuys open-data CSV remains primary |
| N-2 | Learning-to-rank / AI scoring from human Status feedback | Separate from post-ingest Grok fit report |
| N-3 | Two-way Sheets ↔ SQLite Status sync | Sheets remain views |
| N-4 | Automatic amendment / closing-date row refresh | Operator opens `Link` |
| N-5 | Dual-write SQLite + SharePoint | Single `STORAGE_BACKEND` |
| N-6 | Auto-bidding / proposal generation | Out of scope |
| N-7 | Historical backfill campaigns | Day-forward ingest |
| N-8 | AI auto-mutates production `keywords.yaml` on schedule | Conflicts with D-10 / eng ownership |

---

## 4. Open product questions (need answers before B-01–B-04)

Recorded from 2026-08-11 design discussion. Update when answered.

1. **Website type definition:** portal host vs notice instrument vs category family vs company website — which axis first?  
2. **AI role on keywords:** suggest-only (PR) vs any automatic weight tweak? (Default recommendation: **suggest-only**.)  
3. **Primary pain:** fewer false positives vs more true positives vs multi-source readiness?  
4. **Ingest surface:** stay on CanadaBuys CSV only, or also crawl notice `Link` pages?  
5. **Company identity:** keep template `objectives.yaml` or lock real firm name/services for ranking quality?

---

## 5. Roadmap summary (humans)

**Already built — needs only keys:** see [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md) (Sheets, Grok, Teams/Slack, SQLite ingest).

| Horizon | Focus |
|---------|--------|
| **This week (ops)** | Slack/Teams match cards stable; Actions secrets + one scheduled dry run |
| **This month (eng+ops)** | B-06 optional: Actions step for interpret-rank + Ranked; tune objectives from real Ranked outcomes |
| **Next** | B-01/B-02 type-aware keywords if false positives remain high |
| **Later** | B-03 suggest-keywords; B-04/B-05 crawls only with product OK |
| **Long horizon** | §7 multi-geography **lawful** source mesh + self-improving rank loop (not unrestricted web scrape) |
| **Not planned now** | N-* auto-bid, dual-write, two-way Status (see §3) |

### Suggested implementation order (when prioritized)

```text
0) Human: PLUG_AND_PLAY — channel webhooks + Actions secrets (no code)
1) B-07 finish remaining live proofs (Teams ops if needed)
2) B-06 Actions wire-up (if daily AI cost OK)
3) B-01 source type classifier (rules only)
4) B-02 keyword packs by type
5) B-03 suggest-keywords (Grok → PR diff)
6) B-04 / B-05 only after product answers
7) Long horizon: V-* items in §7 (adapter mesh, geography packs, feedback loop)
```

---

## 6. Related docs

| Doc | Role |
|-----|------|
| [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md) | Human keys, function list, go-live sequence |
| [`PROCESSOR_OVERVIEW.md`](PROCESSOR_OVERVIEW.md) | Processor role |
| [`STATUS.md`](STATUS.md) | What works / validated |
| [`AS_BUILT.md`](AS_BUILT.md) | Architecture that exists |
| [`DECISIONS.md`](DECISIONS.md) | Locked ADRs |
| [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) | MUST / MUST NOT |
| [`CHANGE_PLAYBOOK.md`](CHANGE_PLAYBOOK.md) | How to change keywords / Grok objectives |
| [`../AGENTS.md`](../AGENTS.md) | Hard rules for agents |

---

## 7. Long-horizon vision — multi-geography opportunity intelligence

**Status:** Future goals only (not scheduled for build).  
**Recorded:** 2026-08-11 (product discussion: global data lakes / USMCA / self-sustaining system).  
**Guardrails:** Only the constraints of **this project** ([`AGENTS.md`](../AGENTS.md), DATA_UPDATE, Phase 1 non-goals N-*).  
**Processor context:** [`PROCESSOR_OVERVIEW.md`](PROCESSOR_OVERVIEW.md).

### 7.1 Intent (restated from first principles)

**Common informal request:** scrape every public data source for bids, any geography.

**Goal this project will track (lawful and useful):**

> Continuously discover **high-signal procurement / opportunity records** from **declared, permitted sources**, normalize them into **one opportunity schema**, rank them against **our objectives**, and improve filters from **human Status feedback** — for **any geography we choose to enable** — without auto-bidding and without violating create-only / eng-owned control planes.

**Explicitly out of bounds (even as “future”):**

- Unrestricted scraping of the whole public web  
- Bypassing ToS, paywalls, auth, or robots where prohibited  
- Inventing Links or silent-truncating URLs  
- Auto-mutate production `keywords.yaml` without eng review (N-8)  
- Auto-bid / proposal auto-submit (N-6)  
- Treating Sheets as system of record  

Opaque translation of signals is allowed **only** as: structured extraction from a **registered source adapter** + optional LLM **interpretation** into the same schema — not unrestricted harvesting of arbitrary pages.

### 7.2 Future goal register (V-*)

| ID | Goal | Status | Notes |
|----|------|--------|--------|
| **V-1** | **Source registry** — catalog of lakes/portals per geography (open data APIs, official CSVs, licensed aggregators) | Proposed | Each source: license, rate limit, identity keys, health |
| **V-2** | **Adapter interface** — pluggable fetch→normalize→`TenderRecord`/`OpportunityFields` | Designed (not built) | Generalizes CanadaBuys download/parse; multi-source N-1 becomes real |
| **V-3** | **Geography packs** — keywords + objectives + legal flags per region (CA / US / other) | Proposed | USMCA: mark set-aside / domestic-preference when known |
| **V-4** | **Signal fusion** — same real-world tender from two portals → one OpportunityID/Link family | Proposed | Extends current dedupe; never invent IDs |
| **V-5** | **Enrichment lane** — optional fetch of notice `Link` body when CSV is thin | Proposed | Same as B-05; per-source ToS gate |
| **V-6** | **Opaque → structured** — LLM maps messy HTML/PDF fields into schema (post-fetch) | Proposed | Post-ingest / side table; do not overwrite Status |
| **V-7** | **Human feedback loop** — Status/Discarded/Bidding trains **suggested** keyword/objective diffs | Proposed | B-03 + N-2 hybrid; eng merge only |
| **V-8** | **Self-sustaining ops** — schedule, budgets (MAX_CREATE), cost caps (Grok), source health, Slack/Teams heartbeats | Partial | Daily Actions + notify exist; multi-source health TBD |
| **V-9** | **Advantage layer** — rank not only “keyword hit” but **winnability** (set-aside, clearance, geography, partner-needed) | Proposed | Grok objectives expand; still report-only |
| **V-10** | **Commercial + public** — optional private RFP feeds / partner drops as first-class sources | Proposed | Not only government open data |

### 7.3 Evolutionary architecture (self-sustaining, under project constraints)

```text
                    ┌──────────────────────────┐
                    │  Source Registry (V-1)   │
                    │  CA · US · … (enabled)   │
                    └────────────┬─────────────┘
                                 │ lawful adapters only (V-2)
                                 ▼
┌──────────────┐    normalize     ┌────────────────────────────┐
│ CanadaBuys   │─────────────────►│ Opportunity mesh (SQLite)  │
│ + future     │    dedupe V-4    │ create-only SoR            │
└──────────────┘                  └────────────┬───────────────┘
                                               │
                    optional enrich V-5/V-6    │
                                               ▼
                                  ┌────────────────────────────┐
                                  │ Rank / interpret (Grok)    │
                                  │ geography packs V-3 / V-9  │
                                  └────────────┬───────────────┘
                                               │
                          views + alerts       │
                     Sheets · Slack · Teams    │
                                               ▼
                                  ┌────────────────────────────┐
                                  │ Human Status (truth)       │
                                  │ pursue / discard / bid     │
                                  └────────────┬───────────────┘
                                               │ suggest-only V-7
                                               ▼
                                  ┌────────────────────────────┐
                                  │ Eng PR: keywords/objectives│
                                  │ (never silent AI overwrite)│
                                  └────────────────────────────┘
```

**Self-sustaining means:** scheduled runs + budget caps + source health + human-in-the-loop learning **suggestions** — not unsupervised self-rewriting of production rules.

### 7.4 Decision principles

**Question:** How should this project pursue multi-geography coverage while staying inside project guardrails and remaining operable?

**Review lenses (advisory):**

| Seat | Lens | Core claim |
|------|------|------------|
| **Systems engineer** | Interfaces | One schema plus adapters is preferable to a single unrestricted crawler |
| **Procurement** | Markets | Geography is a **policy surface** (set-asides, TAA), not only additional HTTP sources |
| **Security / counsel** | Lawful use | Only sources that can be defended; license and terms of use are product features |
| **Capture lead** | ROI | Alert quality over coverage volume; Status feedback is the training signal |
| **Company positioning** | Fit | Canada public-sector plus partner/commercial sources before large US federal scope |

**Atomic unit of value:**  
A **deduplicated opportunity with a real Link**, a **justified fit score**, and a **human action** (open / pursue / discard) — not additional pages retrieved.

**Adopted principles:**

1. **Operating constraint:** Wins come from **timely, relevant, actionable** notices — not from total bytes retrieved.  
2. **Exclude:** Unbounded crawl, dual system of record, auto-bid, silent keyword mutation.  
3. **Keep / build:** Adapter mesh (V-2), geography packs (V-3), fusion dedupe (V-4), human feedback → engineering PR (V-7), cost-capped rank + alerts (already started).  
4. **Expansion rule:** Add geography only when the **Canada loop is stable** and a **named source** has a clear license and identity model.  
5. **Iteration:** Each new source is a **module with a disable switch**, not a rewrite of the core processor.

**Decision:**  
Pursue broader coverage via a **lawful, extensible source mesh and a human-feedback rank loop**, not unrestricted scraping. That is the only path that stays inside AGENTS hard rules and can remain operable.

### 7.5 Phased enablement (when product prioritizes)

| Phase | Deliver | Exit criteria |
|-------|---------|---------------|
| **G0** (now) | Single source CanadaBuys + rank + Slack | Operators use Status weekly |
| **G1** | V-1 registry + second **official** adapter (e.g. one more CA or licensed feed) | Create-only + dedupe still green |
| **G2** | V-3 geography pack US (flags only) + optional partner feed | Clear “skip set-aside” behavior |
| **G3** | V-5/V-6 enrichment + V-7 suggest-keywords from Status | Eng merges PRs; no silent YAML write |
| **G4** | Multi-geo schedule + cost/health automation V-8 | Budget alarms; dead sources auto-disable |

### 7.6 Product questions for long horizon

1. Which **second source** is first (MERX, provincial, SAM unrestricted only, commercial feed)?  
2. Who owns **source license** approval?  
3. Is **US** a geography pack for Atlas, or only partner-sub signals?  
4. What Status values feed **positive** vs **negative** training for V-7?  
5. Hard **monthly $ cap** on Grok + fetch?
