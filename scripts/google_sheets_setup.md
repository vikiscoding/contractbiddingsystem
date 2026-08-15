# Google Sheets sync — service account + Sheets API (free path)

This guide sets up **daily-ready** sync from local **SQLite** into a Google Sheet  
using a **service account**. The app command is:

```bash
python -m opportunity_ingest sync-sheets
```

It **fully replaces** one worksheet tab (default name: **`Ingest`**).  
Use a separate tab (e.g. **Review**) for manual notes so they are not wiped.

**Cross-links (LLM + product rules):**

- [AGENTS.md](../AGENTS.md) — project entry for agents  
- [DATA_UPDATE_DIRECTIVES.md](../docs/DATA_UPDATE_DIRECTIVES.md) §3 — Sheets normative rules  
- [AS_BUILT.md](../docs/AS_BUILT.md) — architecture  
- [daily_sync.ps1](daily_sync.ps1) — Windows scheduled ingest + sync  

---

## Prerequisites

- Google account
- This project venv working (`run --write` already creates rows in SQLite)
- Python package extras for Sheets:

```powershell
cd <repository-root>
.\.venv\Scripts\Activate.ps1
pip install -e ".[sheets]"
```

---

## Part A — Google Cloud (one time)

### A1. Create or select a Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Top bar → project picker → **New Project** (or pick an existing one).
3. Name example: `contract-bidding-ingest` → **Create**.

### A2. Enable Google Sheets API

1. Menu → **APIs & Services** → **Library**.
2. Search **Google Sheets API** → open it → **Enable**.
3. (Recommended) Also enable **Google Drive API** the same way  
   (needed for some `gspread` open-by-key flows).

### A3. Create a service account

1. Menu → **IAM & Admin** → **Service Accounts**.
2. **+ Create Service Account**.
3. Name: `opportunity-sheets-sync` → **Create and Continue**.
4. Role: you can skip project roles for Sheets-only access (sharing the sheet is enough)  
   → **Continue** → **Done**.

### A4. Create a JSON key

1. Click the new service account email.
2. Tab **Keys** → **Add key** → **Create new key** → **JSON** → **Create**.
3. A `.json` file downloads. **Keep it secret** (never commit to git).

Suggested local path:

```text
secrets/google-service-account.json
```

Create the folder and move the file there:

```powershell
New-Item -ItemType Directory -Force -Path secrets | Out-Null
# Move the downloaded JSON into secrets\google-service-account.json
```

Ensure `.gitignore` ignores secrets (add `secrets/` if needed).

### A5. Copy the service account email

On the service account details page, copy the email, like:

```text
opportunity-sheets-sync@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

You will share the Sheet with this address.

---

## Part B — Google Sheet (one time)

### B1. Create a spreadsheet

1. Open [Google Sheets](https://sheets.google.com) → **Blank** spreadsheet.
2. Rename the file, e.g. **Contract Opportunities**.
3. Rename the first tab to **`Ingest`** (or leave default and set `GOOGLE_SHEET_TAB` later).
4. Optional: add a **`Ranked`** tab for Grok interpret-rank output (created automatically on first rank sync if missing). Do **not** put rankings on `Ingest`.
5. Optional: add a **`Review`** tab for human notes (pipeline will not touch it if you only sync `Ingest` / `Ranked`).

### B2. Share the sheet with the service account

1. Click **Share**.
2. Paste the **service account email**.
3. Role: **Editor**.
4. Uncheck “Notify people” if offered → **Share** / **Send**.

If you skip this step, sync fails with permission errors.

### B3. Copy the Spreadsheet ID

From the browser URL:

```text
https://docs.google.com/spreadsheets/d/  1abc...xyz  /edit#gid=0
                                         ^^^^^^^^^^
                                         SHEET_ID
```

Copy only the long `1abc...` segment → that is `GOOGLE_SHEET_ID`.

---

## Part C — Project configuration

### C1. Install Sheets dependencies

```powershell
pip install -e ".[sheets]"
```

### C2. Configure `.env`

Copy from example if needed, then edit `.env` in the repo root:

```env
STORAGE_BACKEND=sqlite
DATA_DIR=data

GOOGLE_SHEET_ID=1abc...your_id...xyz
GOOGLE_SHEET_TAB=Ingest
GOOGLE_SHEET_RANK_TAB=Ranked
GOOGLE_SERVICE_ACCOUNT_FILE=secrets/google-service-account.json
# Optional Grok (separate extra): XAI_API_KEY=...
```

**Do not** commit `.env` or the JSON key.

### C3. Put data in SQLite (if empty)

```powershell
python -m opportunity_ingest run --write --csv data/sample-openTenderNotice.csv --max-create 10
python -m opportunity_ingest check-store
```

---

## Part D — Run the sync

```powershell
python -m opportunity_ingest sync-sheets
```

Or override flags:

```powershell
python -m opportunity_ingest sync-sheets --sheet-id "1abc..." --tab Ingest
```

Expected success line (Ingest):

```text
Synced 10 rows to sheet 1abc... tab 'Ingest'
```

Open the Google Sheet in the browser → **Ingest** tab should show headers + rows  
(Title, OpportunityID, Link, RelevanceScore, Status, …).

### D2. Grok Ranked tab (optional)

Same spreadsheet and service account. Rankings never write to **Ingest**.

```powershell
pip install -e ".[ai]"
# XAI_API_KEY in root .env
python -m opportunity_ingest interpret-rank --status New --limit 20
# or re-push last local report without calling Grok:
python -m opportunity_ingest sync-rank-sheets
```

- Creates/replaces tab **`Ranked`** (or `GOOGLE_SHEET_RANK_TAB`).  
- Local copies: `data/rankings/interpret-*.md`.  
- Skip sheet push: `--no-sync-sheets`.  
- Full human checklist (all features): [`docs/PLUG_AND_PLAY.md`](../docs/PLUG_AND_PLAY.md).
- Architecture: [`docs/AS_BUILT.md`](../docs/AS_BUILT.md). Unbuilt ideas: [`docs/BACKLOG.md`](../docs/BACKLOG.md).

---

## Part E — Daily automatic update

### Option 1 — Windows Task Scheduler (operator workstation)

1. Use the checked-in script `scripts\daily_sync.ps1` (it changes to the repository root from its own location).

2. Task Scheduler → **Create Basic Task** → Daily after ~9:30 AM Eastern  
   (CanadaBuys refreshes earlier; 10:00 AM local is a safe start).
3. Action: start program  
   `powershell.exe`  
   Arguments:  
   `-NoProfile -ExecutionPolicy Bypass -File "<repository-root>\scripts\daily_sync.ps1"`

PC must be on at that time.

### Option 2 — GitHub Actions (unattended)

1. Repo secrets:
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_SERVICE_ACCOUNT_JSON` = **full contents** of the JSON key file  
   - `TEAMS_WEBHOOK_URL` optional  
2. After the existing `run --write` step, add:

```yaml
- name: Sync Google Sheets
  env:
    GOOGLE_SHEET_ID: ${{ secrets.GOOGLE_SHEET_ID }}
    GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
    GOOGLE_SHEET_TAB: Ingest
    STORAGE_BACKEND: sqlite
    DATA_DIR: data
  run: |
    pip install -e ".[sheets]"
    python -m opportunity_ingest sync-sheets
```

Use **inline JSON** (`GOOGLE_SERVICE_ACCOUNT_JSON`) in CI; use **file path** locally.

---

## Behaviour notes

| Topic | Behaviour |
|--------|-----------|
| Sync mode | **Full replace** of the target tab (clear + write all SQLite rows) |
| Manual edits on `Ingest` | **Overwritten** next sync |
| Manual work | Keep on a **Review** tab (not synced) |
| Empty DB | Writes header only (0 data rows) |
| Status field | Comes from SQLite; edit in DB/export workflow for now, not two-way |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Sheets deps missing` | `pip install -e ".[sheets]"` |
| `set --sheet-id or GOOGLE_SHEET_ID` | Put `.env` at **repo root** (not `scripts/.env`); restart shell |
| `Service account file not found` | Check path; enable File Explorer “File name extensions”; avoid `*.json.json` |
| Permission / 403 when opening sheet | Share sheet with service account email as **Editor** |
| `GOOGLE_SHEET_ID is required` | Set env or `--sheet-id` (no quotes needed in `.env`) |
| API not enabled | Enable **Google Sheets API** (+ Drive API) on the GCP project |
| Wrong project key | JSON key must belong to the project where APIs are enabled |
| No rows | Run `run --write` first; `check-store` / `export-csv` to verify SQLite |

---

## Security checklist

- [ ] `secrets/` and `.env` are gitignored  
- [ ] JSON key never pasted into chat/commits  
- [ ] Sheet shared only with your user + service account  
- [ ] CI uses GitHub **Secrets**, not plain env in logs  

---

## Command cheat sheet

```powershell
pip install -e ".[sheets]"

# fill DB
python -m opportunity_ingest run --write --csv data/sample-openTenderNotice.csv --max-create 10

# push to Google Sheets
python -m opportunity_ingest sync-sheets

# optional local CSV too
python -m opportunity_ingest export-csv
```
