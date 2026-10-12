# Collect manual CI runs (project toggle) — design

Status: approved in conversation 2026-10-12 (sections 1–3 and the self-review amendments), plus a second
self-review of the written spec (upload counting, toggle history, token-dispatched runs, container image,
atomic counter).
ADR: ADR-030 (ADR-029 is test impact analysis).
Blueprint: ingestion (Intelligence/QIP domain) owns per-project collection settings, as it owns masking
patterns and notification channels; PostgreSQL only; no new service, no cross-service call on the upload path.

## 1. Goal and scope

A project setting decides whether QEOS keeps results of CI runs that **a person started by hand**. Teams that
run suites on a schedule and also start ad-hoc debugging runs can keep the ad-hoc ones out of Runs, analytics,
flaky detection, the Report and notifications.

Decided with the user:

- **Off means not stored (option A).** The upload is accepted and discarded; nothing reaches Runs,
  analytics, the Report, notifications or the weekly summary.
- **Default on.** Existing and new projects keep collecting everything until someone switches it off. No
  backfill.
- **Ownership: ingestion-service** (approach 1). The upload is checked against ingestion's own database.
- **Classification in the collector** (§3), sent as `trigger`. A run the collector cannot classify counts as
  automatic and is collected.
- **A person's re-run of an automatic run counts as manual** (GitHub "Re-run jobs" by a person).
- **Runs started from QEOS are always collected** (`trigger = qeos`).

Not in scope: hiding or filtering stored runs by trigger in the views (option B), a "manual" badge in the UI
(the API returns `trigger`, so a later badge needs no API change), test case sync (`import-features` is not
a run upload and is unaffected).

## 2. Behaviour

### 2.1 The toggle
Project Settings › **Collection** card, placed before "Run from QEOS":

- One switch: **Collect runs started manually in CI**. On by default.
- Help text: what counts as manual (§3, short form); runs started from QEOS are always collected; needs
  `qeos-collector` 0.5.0 or later, because older collectors send no trigger and their manual runs are still
  collected.
- When anything was discarded: "*N* manual uploads not collected, last *time ago*". Uploads, not runs: a
  matrix run uploads once per job, so one manual run can count several times.
- Owners and admins change it; other members see it read-only (the switch disabled, with the reason).

### 2.2 An upload while the toggle is off

| `trigger` in the payload | Result |
|---|---|
| `manual` | `202 Accepted`, `{"discarded": true, "reason": "manual runs are not collected for this project"}`; nothing stored |
| `automatic`, `qeos`, absent | stored as today (`201`, or `200` on an idempotent replay) |

While the toggle is on, every upload is stored, with its `trigger` saved.

Switching the toggle never touches stored runs: turning it off does not delete manual runs already
collected, and turning it on does not bring back discarded ones (they were never stored).

The collector prints `qeos: run not collected: manual runs are not collected for this project` and exits 0:
results deliberately left out must not fail the CI job.

## 3. Classification (collector)

The collector sets `trigger` from the CI environment. Order: an explicit `--trigger` flag wins; then the
rules below; anything not matched is unknown, and the field is left out of the payload.

| CI | `qeos` | `manual` | `automatic` |
|---|---|---|---|
| GitHub Actions | `GITHUB_EVENT_NAME=workflow_dispatch` and the event payload (`GITHUB_EVENT_PATH`) has `inputs.request_id` | `workflow_dispatch` without `request_id` and `GITHUB_TRIGGERING_ACTOR` not ending in `[bot]`; or `GITHUB_RUN_ATTEMPT` > 1 with a triggering actor not ending in `[bot]` | every other event (`push`, `pull_request`, `schedule`, `repository_dispatch`, …) and dispatches by a bot |
| GitLab CI | — | `CI_PIPELINE_SOURCE=web`, or `CI_JOB_MANUAL=true` | any other `CI_PIPELINE_SOURCE` |
| Azure Pipelines | — | `BUILD_REASON=Manual` | any other `BUILD_REASON` |
| Jenkins | — | `BUILD_CAUSE` contains `MANUALTRIGGER` or `USERIDCAUSE` (needs a plugin that sets it) | `BUILD_CAUSE` set to anything else |

`GITHUB_TRIGGERING_ACTOR` falls back to `GITHUB_ACTOR` when absent. An unreadable or missing event payload
means no `request_id`. Jenkins without `BUILD_CAUSE` is unknown, so collected; `--trigger` covers that setup.

`--trigger manual|automatic|qeos` overrides detection, for CI the rules don't cover.

Two cases to document in SETUP:

- **A script dispatching with a person's token.** A scheduler that calls `workflow_dispatch` with a
  personal access token looks manual (the triggering actor is that person). Use a GitHub App or
  `GITHUB_TOKEN` for automated dispatches, or pass `--trigger automatic` in that workflow.
- **The collector container image.** It sees only the variables passed to it. Without
  `GITHUB_EVENT_NAME`, `GITHUB_TRIGGERING_ACTOR`, `GITHUB_RUN_ATTEMPT` and the event file
  (`GITHUB_EVENT_PATH`, mounted), the trigger is unknown and the run is collected. The composite
  action and `pip` installs see the runner's environment and need nothing extra.

## 4. Server (ingestion-service)

### 4.1 Data (migration 019, or the next free number when implemented)

`collection_settings`:

| Column | Type | Notes |
|---|---|---|
| `project_id` | integer, primary key | |
| `collect_manual` | boolean, not null, default true | |
| `discarded_count` | integer, not null, default 0 | manual uploads discarded since the row was created |
| `last_discarded_at` | timestamptz, null | |
| `updated_at` | timestamptz, null | last change of `collect_manual` |
| `updated_by` | integer, null | user id of that change |

No row means the defaults. `test_runs.trigger`: `String(10)`, nullable, check constraint
`trigger IN ('manual','automatic','qeos')`; existing runs stay null.

### 4.2 Upload (`POST /api/v1/collect/runs`)

- Payload: optional `trigger` (`Literal["manual","automatic","qeos"] | None`); any other value is a 422.
- When `trigger == "manual"` and the project's settings have `collect_manual = false`: increment
  `discarded_count`, set `last_discarded_at`, write a structured log line (project, API key id, CI run URL),
  increment `runs_discarded_total{reason="manual"}`, answer 202 as in §2.2. The idempotency record is not
  written, so a replay is evaluated again and, with the toggle still off, gets the same 202.
- The check runs before any test-result processing, so a discarded upload costs one indexed read and one
  update.
- The counter update is one atomic `UPDATE … SET discarded_count = discarded_count + 1`: concurrent
  matrix uploads must not lose increments. A row always exists when the toggle is off, because only a
  `PUT` can switch it off.
- Otherwise unchanged, with `trigger` stored on the run. Run list and detail responses include `trigger`.

### 4.3 Settings API

`/api/v1/projects/{id}/collection-settings`

- `GET`: any project member (viewer and up). Returns `collect_manual`, `discarded_count`,
  `last_discarded_at`, `updated_at`, `updated_by`, with defaults when no row exists.
- `PUT {"collect_manual": bool}`: owner or admin. Upsert; sets `updated_at` and `updated_by`; returns the
  stored settings. Other roles get 403; non-members get 404, like the other project endpoints.

### 4.4 Gateway

Add `collection-settings` to ingestion's project regex in `gateway/nginx.conf.template` and to
`gateway/README.md`'s Routes table. `scripts/check_architecture_docs.py` fails until both match the new
router prefix.

## 5. Security

`trigger` is reported by the collector, so whoever holds a project's API key can label a manual run
`automatic`. The toggle is a noise filter, not an access control; API keys remain the boundary. SECURITY.md
states this.

## 6. Testing

Test-first, red then green.

- **Collector:** one test per cell of the §3 table (including a bot dispatch, a person's re-run attempt,
  `request_id`, Jenkins with and without `BUILD_CAUSE`, an unreadable event payload, a missing
  `GITHUB_TRIGGERING_ACTOR` falling back to `GITHUB_ACTOR`); `--trigger` overrides;
  `trigger` omitted when unknown; a 202 discard prints the notice and exits 0.
- **Ingestion:** unit tests of the discard rule; integration: off + manual is 202, nothing stored, counter
  and timestamp updated; off + `automatic` / `qeos` / absent stored; on + manual stored with `trigger`;
  replay of a discarded upload gets 202 again; concurrent discards all counted; invalid `trigger` is 422; settings defaults without a row,
  admin `PUT`, member `PUT` 403, non-member 404; migration test for the new revision.
- **Gateway:** the architecture docs check and `scripts/smoke_gateway.sh` (one `GET` of the settings).
- **Dashboard:** Collection card renders the default, toggles and saves, read-only for members, shows the
  discard line, shows a failed save; `npm run lint`, `typecheck`, tests, `build`.

## 7. Documentation

ADR-030 and its INDEX row; SETUP (a "Collection" subsection with the §3 table, and a troubleshooting row
"my run doesn't appear in QEOS"); collector README (`--trigger`, the 202 notice, exit codes); ingestion and
gateway READMEs; TECHNICAL_SPECIFICATION (payload field, endpoint); SECURITY (§5); PRODUCT; TODO; the
blueprint banner where its rows change.

## 8. Delivery

Each step lands on master after the full suites pass.

1. **Server:** migration, upload rule, settings API, gateway route. Old collectors work unchanged.
2. **Collector 0.5.0:** classification, `--trigger`, the 202 notice; tag `collector-v0.5.0`; move the
   template, docs, Jenkins step and the dashboard's `COLLECTOR_REF` to it.
3. **Dashboard:** the Collection card (layout checked with ui-ux-pro-max before building).

A repository starts filtering once its workflows use `collector-v0.5.0` and someone switches the toggle off.
