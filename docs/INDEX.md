# Documentation index

Central map for humans and LLMs. **Start at [`../AGENTS.md`](../AGENTS.md).**

---

## Core (LLM-optimized)

| Doc | Description |
|-----|-------------|
| [`../AGENTS.md`](../AGENTS.md) | Entry point: hard rules, module map, task routing |
| [`STATUS.md`](STATUS.md) | Living implementation / ops readiness snapshot |
| [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md) | **Human keys + next steps** to turn on built features |
| [`PROCESSOR_OVERVIEW.md`](PROCESSOR_OVERVIEW.md) | **Plain-language view:** this app as one processor — triggers, I/O, place in system |
| [`AS_BUILT.md`](AS_BUILT.md) | Implemented architecture (source of truth for “what exists now”) |
| [`BACKLOG.md`](BACKLOG.md) | Roadmap / not built — includes **§7 long-horizon multi-geo vision** |
| [`DATA_UPDATE_DIRECTIVES.md`](DATA_UPDATE_DIRECTIVES.md) | Normative data write/sync rules (MUST / MUST NOT) |
| [`CHANGE_PLAYBOOK.md`](CHANGE_PLAYBOOK.md) | Step recipes for common development changes |
| [`DECISIONS.md`](DECISIONS.md) | Key architectural decisions (ADR-style, as-built) |

---

## Design history

| Doc | Description |
|-----|-------------|
| [`phase1-canadabuys-sharepoint-implementation-schema.md`](phase1-canadabuys-sharepoint-implementation-schema.md) | Phase 1 design rev 4 (local-first + SharePoint-ready). Historical + deep detail. Prefer AS_BUILT on conflicts. |

---

## Operations

| Doc | Description |
|-----|-------------|
| [`../scripts/ops_runbook.md`](../scripts/ops_runbook.md) | Daily triage, MAX_CREATE policy, calibration, rollback |
| [`../scripts/google_sheets_setup.md`](../scripts/google_sheets_setup.md) | Free Sheets service-account setup + `sync-sheets` |
| [`../scripts/slack_cli_setup.md`](../scripts/slack_cli_setup.md) | Slack CLI / Bolt tokens for match notify |
| [`../scripts/provision_sharepoint_list.md`](../scripts/provision_sharepoint_list.md) | SharePoint list + Sites.Selected activation |

---

## Config templates

| File | Description |
|------|-------------|
| [`../.env.example`](../.env.example) | Root env template |
| [`../config/settings.example.env`](../config/settings.example.env) | Settings mirror |
| [`../config/keywords.yaml`](../config/keywords.yaml) | Keyword groups for ingest filter (eng-owned) |
| [`../config/objectives.yaml`](../config/objectives.yaml) | Company objectives for Grok interpret-rank (eng-owned) |
| [`../config/notify.yaml`](../config/notify.yaml) | Teams match threshold / card limits |

---

## User-facing

| Doc | Description |
|-----|-------------|
| [`../README.md`](../README.md) | Quick start, CLI, secrets table, links |
| [`PROCESSOR_OVERVIEW.md`](PROCESSOR_OVERVIEW.md) | Plain-language processor role, triggers, outputs |
| [`PLUG_AND_PLAY.md`](PLUG_AND_PLAY.md) | Operator plug-in checklist (keys → working stack) |
