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

---

## Explicit non-decisions (deferred)

- Multi-source adapters (MERX, municipal)  
- Learning-to-rank / AI scoring from Status feedback  
- Two-way Sheets ↔ SQLite Status sync  
- Automatic amendment/closing-date refresh  
- Dual-write SQLite + SharePoint  
