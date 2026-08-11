# Architectural decisions (as-built)

Condensed ADRs for Phase 1. See also design-doc Key Decisions (rev 4).

| ID | Decision | Rationale |
|----|----------|-----------|
| D-1 | Python 3.11+ package `opportunity_ingest` | CSV/httpx/msal/sqlite ergonomics; tests |
| D-2 | GitHub Actions daily schedule (`0 14 * * *` UTC) | Free, secrets-native; after CanadaBuys morning refresh |
| D-3 | Default store **SQLite** | Local-first; no Entra gate for go-live |
| D-4 | Pluggable `OpportunityStore` Protocol | SharePoint later via config only |
| D-5 | SharePoint = Graph app-only + Sites.Selected | Unattended; least privilege when activated |
| D-6 | Create-only ingest | Protects human Status/Notes |
| D-7 | Dedupe OpportunityID + normalized Link | Stable identity; prevent double create |
| D-8 | MAX_CREATE = attempt budget (default 50) | Flood control; 0 means unlimited |
| D-9 | Rule-based RelevanceScore 0–100 UTC | Explainable; no ML in Phase 1 |
| D-10 | Keywords in repo YAML; eng-owned | Reviewable PRs; ops via issues |
| D-11 | Teams Workflows webhook (not legacy connectors) | Supported notify path |
| D-12 | Streak state in JSON + Actions cache rotation | Best-effort dryness alerts |
| D-13 | CanadaBuys browser User-Agent | CDN 403 without it |
| D-14 | Link plain text, never truncated | Graph Hyperlink quirks; reviewability |
| D-15 | Google Sheets = full-replace **view** via service account | Free, efficient daily bulk sync; SQLite remains SoR |
| D-16 | `sync-sheets` optional extra (`[sheets]`) | Keep core install light |
| D-17 | EN preferred, FR fallback on bilingual CSV | Maximize non-empty Title/Description/Link |
| D-18 | Closing naive times as fixed UTC−05:00 | Deterministic vs DST-dependent ZoneInfo |
| D-19 | Grok ranking is **post-ingest only** (optional) | Ingest stays explainable rule-based; AI never blocks create path |
| D-20 | Grok never UPDATEs SQLite Status/Notes/RelevanceScore | Protects human triage; AI is a report, not SoR |
| D-21 | Company objectives in `config/objectives.yaml` (eng-owned) | Same review model as keywords; frame for fit_score |
| D-22 | Optional `[ai]` extra + `XAI_API_KEY` (xAI / Grok) | Keep core install light; OpenAI-compatible `https://api.x.ai/v1` |
| D-23 | Google Sheets **Ranked** tab separate from **Ingest** | Full-replace both; refuse writing rankings into Ingest |
| D-24 | Auto Ranked sync when `GOOGLE_SHEET_ID` set (`--no-sync-sheets` opt-out) | Live sheet path without extra flags; explicit skip for offline |
| D-25 | `sync-rank-sheets` re-push from local JSON | Avoid re-calling Grok to refresh the sheet |

---

## Explicit non-decisions (deferred)

Tracked in detail: [`BACKLOG.md`](BACKLOG.md).

- Multi-source adapters (MERX, municipal) as first-class ingest  
- Learning-to-rank / AI scoring from Status feedback into store  
- Two-way Sheets ↔ SQLite Status sync  
- Automatic amendment/closing-date refresh  
- Dual-write SQLite + SharePoint  
- Website/source-type classifier + keyword packs by portal (B-01, B-02)  
- Grok auto-suggest keywords into production YAML without human PR (forbidden; B-03 is suggest-only if built)  
- Company-website crawl for capability vocabulary (B-04)  
- Notice `Link` HTML crawl enrichment (B-05)  
- Auto-bidding / proposal generation  
- Historical backfill campaigns  
