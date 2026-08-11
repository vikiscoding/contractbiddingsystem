# Change playbook

How to implement common changes safely. Follow [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) and [`AGENTS.md`](../AGENTS.md).

---

## A. Tune keywords

1. Edit `config/keywords.yaml` only (engineering-owned).  
2. Prefer multi-word phrases; short terms (≤4 chars) use word-boundary matching.  
3. Avoid bare high-noise terms (`teams`, `strategy` alone).  
4. Add/adjust tests in `tests/test_filter.py` / `tests/test_score.py`.  
5. Dry-run against live or sample CSV; record filtered_count.  
6. Do not change Status values based on keywords automatically.

---

## B. Change scoring formula

1. Edit `score.py` (keep 0–100 clamp, UTC clock).  
2. Update unit tests in `tests/test_score.py`.  
3. Document formula change in `docs/DECISIONS.md` if behavior shifts product metrics.  
4. Scores on **new** creates only (create-only; existing rows keep old scores).

---

## C. Fix / extend CSV field mapping

1. Live headers: re-download sample; inventory wins over historical aliases.  
2. Update `HEADER_CANDIDATES` in `parse.py` if CanadaBuys renames columns.  
3. Update `map_fields.py` for logical field rules.  
4. Add fixture CSV under `tests/fixtures/` + `tests/test_parse.py` / `test_map_fields.py`.  
5. **Never** silent-truncate Link.

---

## D. Change storage schema

1. Update logical fields in `models.py` (`OpportunityFields`).  
2. Update SQLite DDL + `EXPORT_COLUMNS` in `sqlite_store.py`.  
3. Update SharePoint field payload in `sharepoint_store.py` + provision runbook.  
4. Update Sheets sync (uses EXPORT_COLUMNS).  
5. Migration strategy Phase 1: document manual recreate or one-off script; no auto dual-write.  
6. Update `DATA_UPDATE_DIRECTIVES.md` schema table.

---

## E. Add a new CLI command

1. Add handler + argparse in `cli.py`.  
2. Extend frozen-command tests in `tests/test_smoke.py`.  
3. Document in `README.md`, `AGENTS.md`, `AS_BUILT.md`.  
4. Keep `run` write gating rules intact.

---

## E2. Tune Grok interpret-rank / company objectives

1. Edit `config/objectives.yaml` (eng-owned; align with keyword groups when possible).  
2. Prompt / schema / merge logic: `interpret_rank.py` + `tests/test_interpret_rank.py`.  
3. **Never** write fit scores into SQLite opportunity rows.  
4. Local run: `pip install -e ".[ai]"`, set `XAI_API_KEY`, then  
   `python -m opportunity_ingest interpret-rank --status New --limit 20`.  
5. Review `data/rankings/interpret-*.md` and Sheets **Ranked** tab; adjust objectives, not Status automation.  
6. Re-push without Grok: `python -m opportunity_ingest sync-rank-sheets`.  
7. Skip sheet: `--no-sync-sheets`.  

**Not yet implemented** (do not invent code paths): website-type keyword packs, `suggest-keywords` CLI — track in [`BACKLOG.md`](BACKLOG.md) B-01–B-03.

---

## F. Google Sheets behavior change

1. Default remains **full replace** of one tab unless product explicitly requests upsert.  
2. If upsert: key on OpportunityID; never wipe arbitrary human columns without design.  
3. Update `sheets_sync.py` + `scripts/google_sheets_setup.md` + data directives.  
4. Keep service account secrets out of git.

---

## G. Wire Sheets into GitHub Actions

1. Add secrets: `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`.  
2. After successful `run --write` step: `pip install -e ".[sheets]"` + `sync-sheets`.  
3. Ensure sqlite `data/` artifact/cache available to that step.  
4. Document in `README.md` secrets table.

---

## H. Activate SharePoint backend

1. Follow `scripts/provision_sharepoint_list.md` end-to-end.  
2. Set env secrets; `STORAGE_BACKEND=sharepoint`.  
3. `check-store` before schedule.  
4. Note: `export-csv` / `sync-sheets` remain sqlite-oriented — plan migration/export separately.  
5. Do not dual-write.

---

## I. Download / 403 issues

1. Confirm `download.py` `DEFAULT_HEADERS` User-Agent still present.  
2. Retry manually; CDN may rate-limit.  
3. Fallback: `--csv tests/fixtures/...` or last good `data/sample-openTenderNotice.csv`.

---

## J. Documentation updates (required with behavior changes)

When behavior or schema changes, update **all** that apply:

- [ ] `AGENTS.md` hard rules / task map  
- [ ] `docs/DATA_UPDATE_DIRECTIVES.md`  
- [ ] `docs/AS_BUILT.md`  
- [ ] `docs/DECISIONS.md` (new ADR if architectural)  
- [ ] `README.md` quick start / CLI  
- [ ] Relevant `scripts/*.md`  

---

## K. PR / verification minimum

```bash
ruff check src tests
pytest -q
```

For pipeline-affecting changes, also:

```bash
python -m opportunity_ingest run --csv tests/fixtures/open_tender_pipeline.csv
```
