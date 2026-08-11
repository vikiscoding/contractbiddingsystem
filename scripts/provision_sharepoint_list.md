# SharePoint activation runbook — Contract Opportunities list

**Not a day-1 gate.** Day-1 production uses `STORAGE_BACKEND=sqlite`. Follow this runbook only when you are ready to flip the pipeline to SharePoint.

**Related:** [AGENTS.md](../AGENTS.md) · [DATA_UPDATE_DIRECTIVES](../docs/DATA_UPDATE_DIRECTIVES.md) §5 · [AS_BUILT](../docs/AS_BUILT.md) · [ops_runbook](ops_runbook.md)

The SharePoint Graph adapter is already implemented (`SharePointOpportunityStore`). Activation is **config + secrets + one-time site grant** — no pipeline rewrite.

Dual-write (SQLite + SharePoint) is **not** Phase 1. Switch backends; migrate data out-of-band if needed.

**Single-writer assumption:** Unlike SQLite, SharePoint has no UNIQUE index on OpportunityID/Link. The adapter pre-checks via `load_existing_keys` but does **not** raise `SkipDuplicate` on create. Avoid parallel `STORAGE_BACKEND=sharepoint --write` jobs (one schedule, concurrency group). Optional later hardening: Power Automate / list validation rules.

---

## 1. Create the list (UI is source of truth)

In the target SharePoint site, create a list named **Contract Opportunities**.

### Column schema

Use these **display names** (internal names should match when created without spaces/special chars). Prefer creating columns in the UI rather than Graph create-list (choice defaults and UX are clearer in UI).

| Column | Type | Required | Notes |
|--------|------|----------|-------|
| **Title** | Single line of text | Yes | Built-in; max 255 |
| **OpportunityID** | Single line of text | Yes | Business key for dedupe; **no Graph UNIQUE index** — process-level uniqueness only (single writer + optional Power Automate) |
| **Source** | Choice or single line | Yes | Default / value `CanadaBuys` |
| **Buyer** | Single line of text | No | |
| **Link** | **Multiple lines of text — plain text (not enhanced/rich text)** | Yes | **Not** Hyperlink; **not** rich text (rich text returns HTML and breaks URL dedupe) |
| **PublishedDate** | Date only | No | |
| **ClosingDate** | Date and time | No | Store/display UTC-aware values from pipeline |
| **Category** | Single line of text | No | GSIN or procurement category |
| **Description** | Multiple lines of text | No | Up to ~2000 chars from pipeline |
| **KeywordsMatched** | Single line or multi-line | No | Comma-separated terms |
| **RelevanceScore** | Number | No | 0–100 |
| **Status** | Choice | Yes | `New`, `Reviewing`, `Relevant`, `Bidding`, `Discarded`; default **New** |
| **DateAdded** | Date and time | Yes | UTC ISO from pipeline |
| **Notes** | Multiple lines of text | No | Empty on automated create; humans edit later |

### Why multi-line plain text for Link?

Graph Hyperlink columns are awkward (object shape `{Url, Description}`, length quirks). Phase 1 stores the full CanadaBuys notice URL as a **plain string** in a multi-line text column.

When creating the column in SharePoint UI:

1. Type: **Multiple lines of text**
2. Specify the type of text: **Plain text** (not “Enhanced rich text”)

Enhanced/rich text stores HTML (`<div>`, `<a href=...>`) which breaks plain-string dedupe and human copy/paste. The adapter also **reads** legacy Hyperlink objects (`{Url: ...}`) if an old column type remains.

---

## 2. Resolve site ID and list ID

Set these as `SHAREPOINT_SITE_ID` and `SHAREPOINT_LIST_ID`.

### Preferred: client-side match (avoid `$filter=displayName` pitfalls)

Graph `$filter` on list `displayName` is unreliable across tenants. Prefer:

1. Resolve the **site** id, then list all lists and match by display name locally.

**Site by hostname + path** (example):

```http
GET https://graph.microsoft.com/v1.0/sites/{hostname}:/{server-relative-path}
Authorization: Bearer {token}
```

Example path shape:

```text
contoso.sharepoint.com:/sites/ContractBidding
```

Response `id` is a composite site id (e.g. `contoso.sharepoint.com,guid,guid`) — use it as `SHAREPOINT_SITE_ID`.

**Lists on that site:**

```http
GET https://graph.microsoft.com/v1.0/sites/{site-id}/lists?$select=id,displayName,name
Authorization: Bearer {token}
```

In the JSON `value` array, find `displayName == "Contract Opportunities"` (or your chosen name) and copy `id` → `SHAREPOINT_LIST_ID`.

### Optional: browser / UI

- Site settings / list settings URLs sometimes expose GUIDs; Graph composite **site** id is still easiest via the API above.
- List settings → URL often contains `List=%7B...%7D` (URL-encoded GUID).

### PowerShell / Graph Explorer

Use [Graph Explorer](https://developer.microsoft.com/en-us/graph/graph-explorer) signed in as a **SharePoint Administrator** (or Global Admin) for grant operations, or any script with an app token that already has site access (after step 4 grant).

---

## 3. Register Entra ID app (client credentials)

1. Azure Portal → **Microsoft Entra ID** → **App registrations** → **New registration**.
2. Name e.g. `opportunity-ingest-graph`.
3. **Accounts in this organizational directory only**.
4. No redirect URI required for client credentials.
5. **Certificates & secrets** → create a **client secret**; store it as `AZURE_CLIENT_SECRET` (show-once).
6. Note **Application (client) ID** → `AZURE_CLIENT_ID`.
7. Note **Directory (tenant) ID** → `AZURE_TENANT_ID`.

### API permission: Sites.Selected (least privilege)

1. App → **API permissions** → **Add a permission** → **Microsoft Graph** → **Application permissions**.
2. Add **`Sites.Selected`**.
3. **Grant admin consent** for the tenant.

`Sites.Selected` alone does **not** grant access to any site until a separate **site permission** is assigned to this app (next section). That is intentional least privilege.

---

## 4. Chicken-and-egg site grant (`Sites.Selected`)

The ingest app cannot grant itself site access. A **privileged caller** must POST a site permission that names the ingest app and role **`write`** (or `read` if you only smoke-test reads first; pipeline creates need **`write`**).

This API creates **application** site permissions only. For **delegated** calls (Graph Explorer), Microsoft Graph requires a directory administrator role such as **SharePoint Administrator or Global Administrator** — **site collection admin alone is not sufficient** and typically returns HTTP 403.

### Option A — Graph Explorer (interactive admin)

1. Sign in to Graph Explorer as a **SharePoint Administrator** or **Global Administrator** (not merely site collection admin).
2. Consent to delegated **`Sites.FullControl.All`** for Graph Explorer **as the signed-in user** (admin consent as required by your tenant).
3. POST:

```http
POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
Content-Type: application/json

{
  "roles": ["write"],
  "grantedToIdentities": [
    {
      "application": {
        "id": "{AZURE_CLIENT_ID}",
        "displayName": "opportunity-ingest-graph"
      }
    }
  ]
}
```

4. Confirm with:

```http
GET https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
```

### Option B — Temporary privileged app (application permissions)

1. Create a **short-lived** admin app registration with application permission **`Sites.FullControl.All`** + **admin consent**.
2. Acquire a client-credentials token for that admin app (scope `https://graph.microsoft.com/.default`), then POST the same permission body targeting the **ingest** app’s client id.
3. **Remove** `Sites.FullControl.All` / delete the admin app secret when done.

Example (PowerShell-friendly sketch; replace placeholders):

```powershell
# --- Admin app (Sites.FullControl.All) token ---
$tenantId  = "{ADMIN_OR_SAME_TENANT_ID}"
$adminAppId = "{ADMIN_APP_CLIENT_ID}"
$adminSecret = "{ADMIN_APP_CLIENT_SECRET}"
$siteId = "{SHAREPOINT_SITE_ID}"
$ingestAppId = "{AZURE_CLIENT_ID}"   # the Sites.Selected ingest app

$tokenBody = @{
  client_id     = $adminAppId
  client_secret = $adminSecret
  scope         = "https://graph.microsoft.com/.default"
  grant_type    = "client_credentials"
}
$token = Invoke-RestMethod `
  -Method POST `
  -Uri "https://login.microsoftonline.com/$tenantId/oauth2/v2.0/token" `
  -Body $tokenBody

$headers = @{
  Authorization  = "Bearer $($token.access_token)"
  "Content-Type" = "application/json"
}
$grantBody = @{
  roles = @("write")
  grantedToIdentities = @(
    @{
      application = @{
        id          = $ingestAppId
        displayName = "opportunity-ingest-graph"
      }
    }
  )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method POST `
  -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/permissions" `
  -Headers $headers `
  -Body $grantBody
```

Or with curl:

```bash
# 1) Token
curl -s -X POST "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token" \
  -d "client_id={admin_app_id}" \
  -d "client_secret={admin_secret}" \
  -d "scope=https://graph.microsoft.com/.default" \
  -d "grant_type=client_credentials"

# 2) Grant (use access_token from step 1)
curl -s -X POST "https://graph.microsoft.com/v1.0/sites/{site-id}/permissions" \
  -H "Authorization: Bearer {admin_access_token}" \
  -H "Content-Type: application/json" \
  -d '{"roles":["write"],"grantedToIdentities":[{"application":{"id":"{ingest_client_id}","displayName":"opportunity-ingest-graph"}}]}'
```

### Verify app-only access

With the **ingest** app client credentials:

```http
GET https://graph.microsoft.com/v1.0/sites/{site-id}/lists/{list-id}?$select=id,displayName
Authorization: Bearer {ingest-app-token}
```

Expect HTTP 200. HTTP 403 → grant missing, wrong site id, or **propagation delay** (wait a few minutes and retry).

Token scope for the ingest app:

```text
https://graph.microsoft.com/.default
```

(MSAL client credentials / client secret flow.)

---

## 5. Secrets and configuration

### Local `.env` / environment

```env
STORAGE_BACKEND=sharepoint
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
SHAREPOINT_SITE_ID=...
SHAREPOINT_LIST_ID=...
# optional
HTTP_TIMEOUT_SECONDS=120
```

Keep `STORAGE_BACKEND=sqlite` until steps 1–4 succeed.

### GitHub Actions secrets (when schedule flips)

| Secret | Required for SP |
|--------|-----------------|
| `AZURE_TENANT_ID` | Yes |
| `AZURE_CLIENT_ID` | Yes |
| `AZURE_CLIENT_SECRET` | Yes |
| `SHAREPOINT_SITE_ID` | Yes |
| `SHAREPOINT_LIST_ID` | Yes |
| `TEAMS_WEBHOOK_URL` | Recommended (unchanged) |

Workflow env: `STORAGE_BACKEND: sharepoint` (only after smoke tests pass). Day-1 schedule remains `sqlite`.

---

## 6. `check-store` health check

With secrets loaded and package installed:

```powershell
$env:STORAGE_BACKEND = "sharepoint"
# ... set Azure + SharePoint env vars ...
python -m opportunity_ingest check-store
```

This acquires a Graph token (client credentials → `https://graph.microsoft.com/.default`) and performs a simple list access. Non-zero exit / hard fail → fix grant, ids, or secrets before enabling `--write`.

> Note: full CLI `check-store` wiring lands with pipeline orchestration (PR 6). Until then you can smoke-test with a short Python snippet:

```python
from opportunity_ingest.config import get_settings
from opportunity_ingest.storage import build_store

store = build_store(get_settings())
store.health_check()
keys = store.load_existing_keys()
print(store.name, len(keys.opportunity_ids), len(keys.links))
store.close()  # optional; owned httpx client
```

---

## 7. Smoke write (manual)

Create one list item with a full Link string, Status **New**, DateAdded UTC:

```python
from datetime import datetime, timezone
from opportunity_ingest.config import get_settings
from opportunity_ingest.models import OpportunityFields
from opportunity_ingest.storage import build_store

with build_store(get_settings()) as store:
    store.health_check()
    item_id = store.create(
        OpportunityFields(
            Title="SP smoke test",
            OpportunityID="SMOKE-SP-001",
            Source="CanadaBuys",
            Buyer="Test",
            Link="https://canadabuys.canada.ca/en/tender-opportunities/notice/smoke-sp-001",
            PublishedDate=None,
            ClosingDate=None,
            Category=None,
            Description="provisioning smoke",
            KeywordsMatched="",
            RelevanceScore=0,
            Status="New",
            DateAdded=datetime.now(timezone.utc),
            Notes="",
        )
    )
    print("created", item_id)
```

Confirm in the SharePoint UI: Link is the full URL **plain text** (no HTML wrapper), Status = New, DateAdded set.

Delete the smoke row from the UI if you do not want it in production data.

---

## 8. Flip the pipeline (when ready)

1. Optional: export SQLite → CSV (`export-csv`) for backup / migration reference.
2. Optional one-time migration: import CSV into the list (manual or scripted creates). **Not** automatic dual-write in Phase 1.
3. Set `STORAGE_BACKEND=sharepoint` + secrets in the environment / Actions.
4. Ensure only **one** scheduled writer (Actions concurrency group); do not run parallel sharepoint `--write` jobs.
5. Run `check-store` and a controlled `--write` with low `MAX_CREATE` / `INGEST_MAX_CREATE`.
6. Monitor Teams failure notifications and Graph 403/429 rates.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| MSAL `invalid_client` / secret errors | Wrong tenant/client/secret; secret expired |
| HTTP 403 on list GET (immediate after grant) | **Permission propagation delay** — wait 2–10 minutes and retry; then check grant / site id |
| HTTP 403 on list GET (persists) | Site permission grant missing; wrong `SHAREPOINT_SITE_ID`; delegated grant done as non-admin |
| HTTP 403 on `POST .../permissions` (Option A) | Caller is not SharePoint Admin / Global Admin; site collection admin is insufficient |
| HTTP 404 on list | Wrong `SHAREPOINT_LIST_ID` or site |
| Create 400 on field name | Column internal name mismatch — check list columns in Graph `columns` API |
| Create 400 on Link object | Link must be multi-line **plain text**, not Hyperlink |
| Link values contain `<div>` / `<a` / HTML | Column is **enhanced rich text** — recreate as multi-line **plain text** |
| Duplicate OpportunityID / Link rows | Concurrent sharepoint writers **or** no SP unique index — Phase 1: single schedule only; optional Power Automate later |
| Empty dedupe keys | List empty or `$expand=fields` column names differ from OpportunityID/Link |
| HTTP 429 during key load | Graph throttling — adapter retries a few times with `Retry-After`; reduce parallel jobs |

Inspect columns:

```http
GET https://graph.microsoft.com/v1.0/sites/{site-id}/lists/{list-id}/columns?$select=name,displayName
```

---

## References

- [List items — Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/listitem-list?view=graph-rest-1.0)
- [Create list item](https://learn.microsoft.com/en-us/graph/api/listitem-create?view=graph-rest-1.0)
- [Create site permission](https://learn.microsoft.com/en-us/graph/api/site-post-permissions?view=graph-rest-1.0)
- [Sites.Selected overview](https://learn.microsoft.com/en-us/graph/permissions-reference#sitesselected)
- Design: `docs/phase1-canadabuys-sharepoint-implementation-schema.md`
