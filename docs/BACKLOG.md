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

Normative rules: [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) §2.8, §3.2.

**Note (2026-08-11):** Keyword/objective packs were manually derived from a full crawl of
https://atlasflowgroupwebsite.vikrant-singh1.workers.dev/ (home, services, approach, about, contact).
Automated site crawl → YAML (B-04) remains unbuilt; this was a one-off eng tuning pass.

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

Carried from Phase 1 design / AGENTS hard rules. Not “forgotten”—**intentionally not building now**.

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

**Already built — needs only keys:** see [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md) (Sheets, Grok, Teams, SQLite ingest).

| Horizon | Focus |
|---------|--------|
| **This week (ops)** | Plug `TEAMS_WEBHOOK_URL`; prove match card; GitHub secrets + one scheduled dry run |
| **This month (eng+ops)** | B-06 optional: Actions step for interpret-rank + Ranked; tune objectives from real Ranked outcomes |
| **Next** | B-01/B-02 type-aware keywords if false positives remain high |
| **Later** | B-03 suggest-keywords; B-04/B-05 crawls only with product OK |
| **Not planned now** | N-* auto-bid, dual-write, two-way Status (see §3) |

### Suggested implementation order (when prioritized)

```text
0) Human: PLUG_AND_PLAY — Teams webhook + Actions secrets (no code)
1) B-07 already largely done for Grok+Ranked; finish Teams live proof
2) B-06 Actions wire-up (if daily AI cost OK)
3) B-01 source type classifier (rules only)
4) B-02 keyword packs by type
5) B-03 suggest-keywords (Grok → PR diff)
6) B-04 / B-05 only after product answers
```

---

## 6. Related docs

| Doc | Role |
|-----|------|
| [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md) | Human keys, function list, go-live sequence |
| [`STATUS.md`](STATUS.md) | What works / validated |
| [`AS_BUILT.md`](AS_BUILT.md) | Architecture that exists |
| [`DECISIONS.md`](DECISIONS.md) | Locked ADRs |
| [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) | MUST / MUST NOT |
| [`CHANGE_PLAYBOOK.md`](CHANGE_PLAYBOOK.md) | How to change keywords / Grok objectives |
| [`../AGENTS.md`](../AGENTS.md) | Hard rules for agents |
