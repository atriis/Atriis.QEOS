# ADR-030: A project setting decides whether manual CI runs are collected; ingestion owns it and discards the upload

Status: Accepted (2026-10-12) · Spec: `docs/superpowers/specs/2026-10-12-collect-manual-runs-design.md`

## Context
Teams run suites on a schedule and also start ad-hoc runs by hand to debug. The ad-hoc runs pollute Runs,
analytics, flaky detection, the Report and notifications. A project needs a way to keep them out.

CI systems do not agree on what "manual" means. GitHub reports a person's click and a bot's
`workflow_dispatch` the same way, and a person's "Re-run jobs" keeps the original event. Classification
therefore needs rules and an override, not a single variable.

## Decision
- **A project setting, `collect_manual`, on by default.** Existing and new projects keep collecting everything until someone switches it off. There is no backfill.
- **Ownership: ingestion-service.** The table `collection_settings` (migration 019) lives in ingestion's database, as masking patterns and notification channels do. The upload is checked against ingestion's own data: no new service and no cross-service call on the upload path.
- **The collector classifies, the server filters.** The payload carries an optional `run.trigger`: `manual`, `automatic` or `qeos`. A run the collector cannot classify sends nothing and counts as automatic. Runs started from QEOS are always collected (`qeos`). A person's re-run counts as manual.
- **Off means not stored.** With `collect_manual = false`, an upload with `trigger = manual` answers `202 {"discarded": true, "reason": "manual runs are not collected for this project"}` and stores nothing. Every other trigger, or none, is stored as before (`201`, or `200` on a replay).

| `trigger` | `collect_manual = true` | `collect_manual = false` |
|---|---|---|
| `manual` | stored | `202`, discarded |
| `automatic`, `qeos`, absent | stored | stored |

- **The discard is cheap and counted.** The check runs before any result processing. It does one atomic `UPDATE … SET discarded_count = discarded_count + 1` (matrix uploads must not lose increments), sets `last_discarded_at`, writes a WARNING log line with the CI URL masked, and increments `qeos_runs_discarded_total{reason="manual"}`. The API key's `last_used_at` is still updated. The idempotency record is not written, so a replay is evaluated again.
- **Settings API.** `GET/PUT /api/v1/projects/{id}/collection-settings`: any member reads, owners and admins write, non-members get 404. The gateway routes it to ingestion.
- **`test_runs.trigger`** stores the value (nullable, check constraint; existing runs stay null). Run list and detail return it.
- **Request hash.** The idempotency body hash now includes `"trigger": null` for payloads without a trigger. A retry that spans the deploy, of a run stored earlier under the same `Idempotency-Key`, gets `409`. This is accepted: the window is one deploy and the collector's retry budget is two minutes.

## Consequences
- **Old collectors keep collecting manual runs.** They send no trigger, so the filter only works from `qeos-collector` 0.5.0.
- **`trigger` is client-reported.** Whoever holds the API key can label a manual run `automatic`. The toggle is a noise filter, not access control. SECURITY.md says so.
- **The counter counts uploads, not runs.** A matrix run uploads once per job, so one manual run can count several times.
- Switching the toggle never touches stored runs, and discarded uploads cannot be brought back.
- A script that dispatches a workflow with a person's token looks manual. The collector docs tell teams to use a GitHub App, `GITHUB_TOKEN` or `--trigger automatic`.
- The collector exits 0 on a discard, so a deliberately omitted result never fails a CI job. With `--gate` it decides on the local results (exit 1 on any failed or errored test), the same as against a platform that reports no quarantine: a person's re-run of a failing job must not pass the required check just because it was not collected. `--fail-on-error` alone keeps meaning upload failures.

## Alternatives rejected
- **Store everything and hide manual runs in the views (option B):** every analytic and notification would need the filter, and the noise stays in the data. Left as a possible later step; the API already returns `trigger`.
- **The setting in project-service:** the upload would call another service, or cache its answer, on the hottest path.
- **A `4xx` for a discarded upload:** it would fail the CI job for results the team chose to leave out.
- **Server-side classification:** the server sees only the payload, while the CI environment is in the collector.

## Delivery
1. Server: migration 019, upload rule, settings API, gateway route.
2. Collector 0.5.0: classification, `--trigger`, the 202 notice.
3. Dashboard: the Collection card in Project Settings.
