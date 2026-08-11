# SharePoint activation runbook — Contract Opportunities list

**Not a day-1 gate.** Day-1 production uses `STORAGE_BACKEND=sqlite`. Follow this runbook only when you are ready to flip the pipeline to SharePoint.

The SharePoint Graph adapter is already implemented (`SharePointOpportunityStore`). Activation is **config + secrets + one-time site grant** — no pipeline rewrite.

Dual-write (SQLite + SharePoint) is **not** Phase 1. Switch backends; migrate data out-of-band if needed.

---

## 1. Create the list (UI is source of truth)

In the target SharePoint site, create a list named **Contract Opportunities**.

### Column schema

Use these **display names** (internal names should match when created without spaces/special chars). Prefer creating columns in the UI rather than Graph create-list (choice defaults and UX are clearer in UI).

| Column | Type | Required | Notes |
|--------|------|----------|-------|
| **Title** | Single line of text | Yes | Built-in; max 255 |
| **OpportunityID** | Single line of text | Yes | Unique business key (enforce via process / Power Automate if desired; Graph has no UNIQUE index) |
| **Source** | Choice or single line | Yes | Default / value `CanadaBuys` |
| **Buyer** | Single line of text | No | |
| **Link** | **Multiple lines of text** (plain text) | Yes | **Not** Hyperlink column — full notice URL, never truncated |
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

Graph Hyperlink columns are awkward (object shape `{Url, Description}`, length quirks). Phase 1 stores the full CanadaBuys notice URL as a **plain string** in a multi-line text column. The adapter also **reads** legacy Hyperlink objects (`{Url: ...}`) if an old column type remains.

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

Use [Graph Explorer](https://developer.microsoft.com/en-us/graph/graph-explorer) signed in as a site owner, or any script with an app token that already has site access (after step 4 grant).

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

### Option A — Graph Explorer (interactive admin)

1. Sign in to Graph Explorer as a **SharePoint admin / Global admin** (or a user with sufficient site collection admin rights for the grant API).
2. Consent to **`Sites.FullControl.All`** (or the grant permission your tenant uses) for Graph Explorer **as the signed-in user**.
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

### Option B — Temporary privileged app

1. Create a **short-lived** admin app with application permission **`Sites.FullControl.All`** + admin consent.
2. Client-credentials token for that admin app.
3. Same POST `/sites/{site-id}/permissions` as above, targeting the **ingest** app’s client id.
4. **Remove** `Sites.FullControl.All` / delete the admin app secret when done.

### Verify app-only access

With the **ingest** app client credentials:

```http
GET https://graph.microsoft.com/v1.0/sites/{site-id}/lists/{list-id}?$select=id,displayName
Authorization: Bearer {ingest-app-token}
```

Expect HTTP 200. HTTP 403 → grant missing or wrong site id.

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
```

---

## 7. Smoke write (manual)

Create one list item with a full Link string, Status **New**, DateAdded UTC:

```python
from datetime import datetime, timezone
from opportunity_ingest.config import get_settings
from opportunity_ingest.models import OpportunityFields
from opportunity_ingest.storage import build_store

store = build_store(get_settings())
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

Confirm in the SharePoint UI: Link is the full URL text, Status = New, DateAdded set.

Delete the smoke row from the UI if you do not want it in production data.

---

## 8. Flip the pipeline (when ready)

1. Optional: export SQLite → CSV (`export-csv`) for backup / migration reference.
2. Optional one-time migration: import CSV into the list (manual or scripted creates). **Not** automatic dual-write in Phase 1.
3. Set `STORAGE_BACKEND=sharepoint` + secrets in the environment / Actions.
4. Run `check-store` and a controlled `--write` with low `MAX_CREATE` / `INGEST_MAX_CREATE`.
5. Monitor Teams failure notifications and Graph 403/429 rates.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| MSAL `invalid_client` / secret errors | Wrong tenant/client/secret; secret expired |
| HTTP 403 on list GET | Site permission grant missing; wrong `SHAREPOINT_SITE_ID` |
| HTTP 404 on list | Wrong `SHAREPOINT_LIST_ID` or site |
| Create 400 on field name | Column internal name mismatch — check list columns in Graph `columns` API |
| Create 400 on Link object | Link must be multi-line **text**, not Hyperlink |
| Empty dedupe keys | List empty or `$expand=fields` column names differ from OpportunityID/Link |

Inspect columns:

```http
GET https://graph.microsoft.com/v1.0/sites/{site-id}/lists/{list-id}/columns?$select=name,displayName
```

---

## References

- [List items — Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/listitem-list?view=graph-rest-1.0)
- [Create list item](https://learn.microsoft.com/en-us/graph/api/listitem-create?view=graph-rest-1.0)
- [Sites.Selected overview](https://learn.microsoft.com/en-us/graph/permissions-reference#sitesselected)
- Design: `docs/phase1-canadabuys-sharepoint-implementation-schema.md`
