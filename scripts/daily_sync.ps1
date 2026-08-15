# Daily ingest + optional Google Sheets sync (Windows Task Scheduler).
# Schedule after ~10:00 local (CanadaBuys open file refreshes ~07:00–08:30 America/Toronto).
#
# Task action example:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "...\scripts\daily_sync.ps1"

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (Test-Path .\.venv\Scripts\Activate.ps1) {
    & .\.venv\Scripts\Activate.ps1
}

python -m opportunity_ingest run --write --max-create 50
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Optional: full-replace Google Sheets Ingest tab (requires .env + secrets + pip install -e ".[sheets]")
if ($env:GOOGLE_SHEET_ID -or (Select-String -Path .env -Pattern '^\s*GOOGLE_SHEET_ID=' -Quiet -ErrorAction SilentlyContinue)) {
    python -m opportunity_ingest sync-sheets
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

exit 0
