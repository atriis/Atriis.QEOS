# Ingestion Service

Receives test results from CI. Design: `docs/superpowers/specs/2026-09-29-ingestion-service-design.md`.

## For a CI pipeline

1. A project owner, admin or member creates a key (shown once — store it as a CI secret):

   ```bash
   curl -k -X POST https://localhost:8443/api/v1/projects/<project_id>/api-keys \
     -H "Authorization: Bearer <your login token>" -H "Content-Type: application/json" \
     -d '{"name":"GitHub Actions - main"}'
   ```

2. The pipeline uploads one run per job:

   ```bash
   curl -k -X POST https://localhost:8443/api/v1/collect/runs \
     -H "Authorization: Bearer $QEOS_API_KEY" -H "Idempotency-Key: $CI_RUN_ID-$CI_JOB" \
     -H "Content-Type: application/json" -d @run.json
   ```

   `run.json`:
   ```json
   {"run": {"ci_provider": "github_actions", "branch": "main", "commit_sha": "3f2a9c1",
            "started_at": "2026-09-29T10:00:00Z", "finished_at": "2026-09-29T10:04:12Z"},
    "results": [{"suite": "checkout", "class_name": "CartTest", "name": "adds item",
                 "status": "passed", "duration_ms": 812}]}
   ```

   `201` returns the run id and counts. Retrying with the same `Idempotency-Key` returns `200` and
   the same run — never a duplicate. The same key with a different body is `409`.
   The run may carry `"trigger": "manual" | "automatic" | "qeos"` (anything else is `422`). The request hash
   includes it (`null` when absent), so a retry that spans the deploy of this field, of a run stored earlier
   under the same `Idempotency-Key`, gets `409`; this is accepted (ADR-030).

## Collection settings

`GET /api/v1/projects/{id}/collection-settings` (any project member) returns `collect_manual` (default
`true`; no row means the defaults), `discarded_count`, `last_discarded_at`, `updated_at` and `updated_by`.
`PUT` with `{"collect_manual": bool}` (owner or admin; other roles 403, non-members 404) upserts it and
returns the stored settings.

With `collect_manual` off, an upload whose `run.trigger` is `manual` answers
`202 {"discarded": true, "reason": "manual runs are not collected for this project"}` and stores nothing.
`automatic`, `qeos` and no trigger are stored as usual. A discard:

- is counted by one atomic `UPDATE` (`discarded_count`, `last_discarded_at`): uploads, not runs, because a
  matrix run uploads once per job;
- writes a WARNING log line with the CI URL masked, and bumps the key's `last_used_at`;
- increments `qeos_runs_discarded_total{reason="manual"}`;
- writes no idempotency record, so a replay is evaluated again; a replay of a run stored earlier still
  answers `200`.

Turning the setting off or on never touches stored runs. `trigger` is reported by the collector, so it is a
noise filter, not access control. `test_runs.trigger` (migration 019) stores it and the run list and detail
return it. See ADR-030.

## Import token

`POST /api/v1/collect/token` with `Authorization: Bearer qeos_…` returns
`{"token", "expires_in": 300, "project_id"}`. The token is a JWT that test-management accepts only
on `POST /api/v1/projects/{id}/cases/import` for that project, so `qeos-collector import-features`
can sync cases without a user login. See ADR-024.

## Limits

- Up to 20,000 results per run (`422` beyond: split the run).
- `message` and `details` over 64 KB are truncated (the result's `truncated` is true), never rejected.
- `status`: `passed`, `failed`, `skipped`, `errored` (`error` is accepted as `errored`).
- `finished_at` may be at most 1 hour ahead of the server clock.
- Through the gateway, uploads are limited to 10 per second per IP (burst 20).

## Reading results

- `GET /api/v1/projects/<id>/runs?limit=&offset=` — newest first, with counts. Optional filters,
  combined with AND: `branch`, `branch_contains` (case-insensitive substring of the branch, at
  most 255 characters; `%` and `_` match themselves; combines with `branch`),
  `status=failing|passing` (failing means at least one failed or errored result), `environment`,
  `ci_provider`, `commit` (hex prefix of 4+ characters, any case), `pr`, `author`
  (case-insensitive substring; `%` and `_` match themselves), `since` (inclusive) and `until`
  (exclusive) on `started_at`, as ISO 8601 instants. `branch_contains` cannot use the branch
  index; a per-project scan is fine at today's sizes (a `pg_trgm` GIN index on `lower(branch)` is
  the fix if run tables grow very large).
- `GET /api/v1/projects/<id>/runs/<run_id>/summary` — one run's header only, no results:
  `{id, project_id, started_at, finished_at, branch, commit_sha, environment, status:
  "passing"|"failing", counts:{passed, failed, errored, skipped}, ci_provider, ci_run_url}`.
  Every project role may read it; 404 for an unknown run or a run of another project. The
  dashboard's search uses it to check that a run exists.
- `GET /api/v1/runs/<run_id>?status=failed` — one run with its results.
- `GET /api/v1/runs/<run_id>/failure-groups` — failed and errored tests grouped by cause. The
  cause is the first error line with numbers, ids and hashes ignored (`analytics/signature.py`).
  Each group has its `history` on the run's branch, over this run and up to 19 earlier ones:
  `seen_in`, the consecutive `streak` and `since_run_id`. A streak of 1 seen once means new.
- `GET /api/v1/runs/<run_id>/compare/<base_id>` — this run against another of the same
  project, test by test, using each test's last attempt: `new_failures`, `fixed`,
  `still_failing`, `slower` (passed in both, at least 1 s and 50% slower), `added`, `removed`.
  It also returns `counts`, and each list is capped at 200. Runs of different projects are a 404.

Every project role can read; roles come from project-service.

## Masking

Before a result is stored, its `message` and `details` are masked, and so are the run's commit
subject (`commit_message`) and a password inside its `ci_run_url`. Each masked value becomes `[REDACTED:<kind>]`; the text around it stays
readable. Test names, suites, classes, files and branches are never changed.

| Kind | Matches |
|---|---|
| `private_key` | `-----BEGIN … PRIVATE KEY-----` blocks (to the end of the text if unterminated) |
| `authorization` | the value of an `Authorization` / `Proxy-Authorization` header (the scheme word is kept) |
| `url_password` | the password in `scheme://user:password@` |
| `jwt` | JSON Web Tokens |
| `github_token`, `gitlab_token`, `aws_access_key`, `slack_token`, `stripe_key`, `google_api_key`, `npm_token`, `qav_key` | well-known token formats (`qav_key`: project API keys, `qeos_…` and the pre-rename `qav_…`; the kind keeps its pre-rename name for compatibility) |
| `password`, `secret`, `token`, `api_key`, `access_key`, `client_secret`, `private_key`, `credentials` | the value in `key=value`, `key: value`, `key => value`, `"key": "value"` (also escaped inside a log line) when the key ends with one of these names (`DB_PASSWORD`, `SECRET_KEY`, `X-Api-Key`, `accessToken`, …); also `curl -u user:pw`, `--password pw` and `<password>pw</password>` |
| `cookie` | the value of a `Cookie:` / `Set-Cookie:` header |
| `email` | email addresses |
| `card_number` | 13–19 digit card numbers with a card prefix that pass the Luhn check |

- **Project patterns:** `GET/POST /api/v1/projects/{id}/masking-patterns`, `DELETE …/{pattern_id}`
  (owner/admin/member; viewers read), and `POST …/preview` `{name, pattern, sample}` → the sample as
  it would be stored plus this pattern's match count. Up to 20 per project; RE2 syntax (no
  backreferences or lookarounds), so no pattern can stall ingestion (ADR-020); a pattern that
  matches empty text is refused. They run after the built-in rules, never inside an existing
  marker, and produce `[REDACTED:<name>]`; metrics count them as `kind="custom"`.
- Masking happens before the 64 KB cut, so a secret on the boundary is never half-stored.
- Each result has a `redacted` flag; `qav_ingest_redactions_total{kind}` counts results by kind.
- Results stored before masking existed (or before a new rule) are re-masked on demand:
  `python -m src.ingestion.jobs.remask [--dry-run] [--project ID] [--batch-size N]`
  (`docker compose exec ingestion-service python -m src.ingestion.jobs.remask --dry-run`). It
  walks results by id in committed batches (then run CI URLs and commit subjects), prints a JSON summary (`results_scanned`,
  `results_changed`, `runs_changed`, `kinds`), and is safe to repeat: masked text is skipped.
  Text that masking makes longer than 64 KB is cut back and marked `truncated`.

## Retention

`python -m src.ingestion.jobs.retention [--dry-run] [--loop]` (the `ingestion-retention` compose
service runs it with `--loop`):

- Gets every project's `result_retention_days` from project-service's
  `GET /internal/v1/projects/retention`, with the HTTP Basic credentials in
  `PROJECT_SERVICE_INTERNAL_URL` (`http://ingestion-service:<password>@project-service:8000`;
  percent-encode special characters).
- Deletes runs uploaded (`created_at`) more than that many days ago. A deleted project's API keys
  are revoked at once; its runs are all deleted once it has been deleted for more than
  `RETENTION_DELETED_GRACE_DAYS` (default 7) — until then a soft delete can still be undone.
- A project on **legal hold** (`legal_hold: true` in the answer) loses nothing, whatever its age
  or deletion; its keys are still revoked if it is deleted (that deletes no data). Each pass
  reports `projects_held`. The field is required: an answer without it is untrustworthy.
- Without a trustworthy answer (unreachable, not 200, unexpected body) it deletes nothing and
  exits 1. Projects missing from the answer are never touched.
- Each loop job (`retention`, `rollup`, `weekly_summary`, `impact_rollup`) records a heartbeat after every pass it
  runs (last success and last error, with a scrubbed one-line error text) in `job_heartbeats`;
  a pass skipped because another copy holds the advisory lock records nothing.

## Failure notifications

When a run with failed or errored tests is stored, each enabled channel of the project gets a
message. Channels can be limited to one branch (exact match, for example `main`). The message
has the counts, branch and commit, the first 5 failing tests (masked as stored) and a link
`{DASHBOARD_URL}/projects/{id}/runs/{run_id}`. Design:
`docs/superpowers/specs/2026-10-05-failure-notifications-design.md`.

- **Kinds:**
  - `slack`: an incoming webhook on `hooks.slack.com`.
  - `teams`: a Workflows (Power Automate) webhook on `*.logic.azure.com` or `*.powerplatform.com`,
    which gets an Adaptive Card.
  - `webhook`: any public `https` URL; it gets JSON with `event: "run.failed"` or, for the
    weekly summary, `event: "weekly.summary"`.
  - `email`: one to five addresses, as plain text through the SMTP settings shared with auth
    (`qeos_shared.mail`). Without `SMTP_HOST` the delivery is recorded as failed, saying so.
- **API:** `GET/POST /api/v1/projects/{id}/notification-channels`, `PATCH`/`DELETE …/{cid}`
  (`name`, `enabled`, `branch`, `on_failure`, `weekly_summary`), and `POST …/{cid}/test`
  (`?message=weekly` sends last week's real summary instead of a sample). Members and up can
  change channels; viewers can read them. At most 10 per project.
- **Weekly summary** (spec `docs/superpowers/specs/2026-10-05-weekly-summary-design.md`):
  - Channels with `weekly_summary` on get the previous ISO week's numbers: runs, executions,
    pass rate against the week before, failures and the five most-failing tests, with a link
    to the Report. The channel's branch filter applies.
  - The `weekly-summary` compose service runs `python -m src.ingestion.jobs.weekly_summary --loop`.
    From Monday `WEEKLY_SUMMARY_HOUR_UTC` (default 7) it sends each channel once per week;
    `last_weekly_week` remembers it across restarts and copies (advisory lock).
  - A failed delivery is recorded and not retried that week.
  - `on_failure` off turns a channel into summary-only.
- **Delivery:**
  - It runs after the collect response, as a background task, so the collector never waits.
  - No database session is open during the call, and redirects are never followed.
  - One attempt with `NOTIFY_TIMEOUT_SECONDS` (default 5); there is no queue (blueprint
    trigger). The outcome (`last_status`, `last_error`, `last_sent_at`) shows in Settings.
  - An idempotent replay sends nothing.
- **SSRF guard:**
  - Vendor hosts only, for Slack and Teams.
  - Webhooks must use `https` on port 443, with no credentials in the URL.
  - Every address the host resolves to must be public, checked again at send time: no
    loopback, private, link-local, CGNAT, multicast or reserved ranges, so neither the Docker
    network nor cloud metadata can be reached.
- **URLs are bearer secrets.** They are stored to deliver, never returned: the API shows the
  host and the last 4 characters.

## Export

`GET /api/v1/projects/{id}/export` (owners and admins) streams everything stored for a project
as NDJSON (`application/x-ndjson`, `attachment`): an `export` header line (`format: 1`), then each
run (`type: run`, with its `changed_files` and `components`) followed by its results
(`type: result`). Text is exported as stored, masked. For a legal request, or before deleting
a project. The dashboard's Settings → Data has a download button.
- `RETENTION_INTERVAL_HOURS` (default 24) between passes with `--loop`; `RETENTION_BATCH_SIZE`
  (default 500) runs per transaction. One pass at a time (PostgreSQL advisory lock).
- Logs one JSON line per pass; the password is never logged (`user:***@host`).

## Analytics

Read-only, under `/api/v1/projects/{project_id}/analytics/`, for every role that can read runs:

| Endpoint | Returns |
|---|---|
| `GET /trends?days=30&tz=UTC&branch=&environment=` | One entry per local day (`days` 1–365, zone `tz`), oldest first, empty days zero-filled: runs, counts, `pass_rate`, average and maximum run duration |
| `GET /tests?days=30&sort=failures&search=&limit=50&offset=0` | One row per test in the window (`days` 1–90; the cap stays at 90 because the scan grows with the window, about 1.3 s at 90 days in the benchmark above): counts, `pass_rate`, average duration, last status and when last seen; `sort` is `failures`, `duration` or `name`; `search` matches the name literally, case-insensitively |
| `GET /tests/{test_key}/history?days=30&branch=&limit=100` | One test: a summary over the window and its executions, newest first, with the message cut to 500 characters. 404 if the test was never seen in this project |
| `GET /flaky?window_days=14&min_runs=5&min_flip_rate=0.3&branch=` | At most 100 flaky tests (`window_days` 1–90) |
| `GET /latest-keys?status=any&branch=` | `{"keys": [...]}`: the `test_key`s whose latest result has that status (`passed`, `failed` including errored, `skipped`, or `any` for at least one result). Latest is the most recent run (`started_at`, then run id); `branch` narrows it. Test Management uses it for the "result" filter on All Cases |
| `POST /run-strip` | `{"runs": [{...}], "statuses": {key: [status\|null, ...]}}`: each test's status (passed, failed, rerun, skipped, or null) in the project's last `limit` runs (1–20, default 10). Request body: `{test_keys: 1–200 × 64-hex, limit?, branch?}`; unknown body fields are rejected with 422. The `statuses` keys are the lowercased, deduplicated request keys. Statuses: single result → `passed/failed/skipped`; multiple rows → `rerun`; errored → `failed`; no row → `null`. Runs are sorted oldest to newest |
| `POST /duration-estimate` | `{estimate_ms, upper_ms, tests_with_history, tests_without_history, environment_used, model: {overhead_ms, factor, runs, fitted}}`: how long a Play of these tests should take. Body: `{test_keys: 1–200 × 64-hex (lowercased, deduplicated), environment?}` (unknown fields 422). Over the last 30 days, per test: typical = median of its passed executions (else of its non-skipped ones), upper = p90 of every non-skipped execution (never below typical). With an `environment`, a test with at least 3 non-skipped executions there uses only those (`environment_used` counts them). The project's last 20 runs with a result (every branch) fit `wall ≈ overhead + factor × serial` by least squares from 5 runs (factor clamped to 0.05–1, overhead to 0–30 min); otherwise, or on a negative slope, overhead 0 and factor = median wall ÷ serial (1 with no runs). `estimate_ms` = overhead + factor × Σ typical, `upper_ms` likewise with Σ upper; both `null` when no test has history. Test Management stores them on the run request the dashboard creates. Known limit: a retried test counts each attempt as a separate execution |
| `POST /report` | The Report page's sections in one filtered, previous-period-compared request; see "Report" below (ADR-026) |

- `pass_rate` = passed ÷ (total − skipped); errored counts as not passed; `null` when nothing ran.
- An empty filter (`?branch=`) means no filter; `tz` must be a zone name from the IANA list.
- **Flaky, confirmed (`same_commit`):** the test both passed and failed (or errored) on the same commit **in the same environment**, with the pass and the fail in two different runs of that commit. Set `QEOS_ENVIRONMENT` (or `--environment`) per CI matrix leg: legs that do not set it share one environment, so a failure specific to one leg shows as confirmed.
- **Flaky, suspected (`flips`):** for other tests, the share of consecutive executions on a branch whose outcome (pass vs failed/errored) changed, over at least `min_runs` executions; skipped results are ignored.
- Computed on request; migration 003 adds the indexes the queries use.

### Report

`POST /api/v1/projects/{project_id}/analytics/report`, every project role. One request per section; the
dashboard sends them in parallel. Body (`extra` fields are a 422):

| Field | Rule |
|---|---|
| `from`, `to` | ISO dates in `tz`; `from` ≤ `to`; at most 90 days; `to` ≤ today + 1; `from` ≥ today − 400 days |
| `tz` | IANA zone, default `UTC` |
| `branch`, `environment` | exact match; empty means no filter (≤ 255 / ≤ 100 characters) |
| `ci_provider` | one of `CI_PROVIDERS` (`models/run.py`): `github_actions`, `gitlab_ci`, `jenkins`, `azure_pipelines`, `other`, `local`; anything else is a 422 |
| `origin`, `requested_run_urls` | `any` (default), `ci` or `qeos`; the URLs (≤ 5,000, from test-management's `run-urls`) are required with `ci`/`qeos`; a run is `qeos` when it is GitHub Actions and its `ci_run_url` matches one, case-insensitively (ADR-026) |
| `test_keys` | optional, 1–20,000 keys (64 hex); runs then count only when they have a result for one |
| `sections` | 1–5 of `summary`, `failure_causes`, `regressions`, `tests`, `duration` |
| `bucket` | `auto` (day up to 31 days, else Monday weeks), `day`, `week` |

The response carries `period`, `previous_period` (the same number of days just before), `tz`, `bucket`,
`generated_at`, `scope` and the asked sections. `summary`: current and previous totals (`previous` is null
without runs), buckets and `previous_buckets` (the previous period aligned bucket by bucket), the 10 most
failing and slowest tests, the 10 busiest branches, and facets (the period's 50 busiest branches,
environments and CI providers, ignoring the other filters). Each request runs under a 20 s statement
timeout; a timeout is 503 `{"detail": {"code": "report_timeout", ...}}`. Nothing is cached server-side.

- `failure_causes`: the failing rows (failed or errored) of both periods grouped by the run view's signature (first
  line, ids and numbers replaced, SHA-1 to 12 characters; `none` without a message). The 50 biggest groups (ties:
  newer `last_seen`, then signature, `none` last) with `status` `new` or `recurring` against the previous period,
  `first_seen` over both periods, per-bucket counts, up to 10 tests each, `other` for the rest, and up to 20
  `resolved` signatures (present in the previous period only). Quarantined occurrences are flagged and still count.
- `regressions`: each test's last non-skipped attempt per run, as a sequence per (test, branch), for tests with a
  failing execution in either period: `newly_failing` and `fixed` (100 each), `longest_failing` (50; a streak older
  than the look-back is `failing_since_bounded`), `time_to_fix` (mean, median, p90; `bounded` counts lower bounds),
  and per bucket `flakiness`: the tests executed, flaky tests and flips ("Instability (flips)", not the Flaky page's
  same-commit rule). Each list also reports its `total`. The outcome query reads only the failing outcomes and the
  outcomes next to one on the same branch (a pass between two passes starts, ends and flips nothing), and fetches
  a headline only for a sequence's last outcome when it fails; the streaks, fixes and flips are the same as over the
  full sequence.
- `tests`: one row per test executed in scope in the period, columnar (`columns` + `rows`): executions, the four
  counts, `flips` and `pairs` summed over branches (flips only computed for tests with a failure), summed duration
  and the last status. At most 50,000 rows (then `truncated`, most failing first). The dashboard groups these rows by
  the cases' feature, folder, label or suite (ADR-026).
- `duration`: per bucket the runs and average, p50, p90 and maximum, and the previous period's figures. Without
  test keys the basis is `run_wall_time` (`test_runs.duration_ms`); with them `test_time`, the summed duration of
  the selected tests per run. The `summary` KPI `avg_run_duration_ms` stays wall time (`test_runs.duration_ms`)
  even with test keys; only this section switches basis.
- Migration 016 adds `ix_test_results_failing` on `(run_id, test_key)` (partial, failing rows only), built
  `CONCURRENTLY` on PostgreSQL so uploads are not blocked. Failure causes and the regression candidates read through it.

Measured on a throwaway stack with 1,980 runs × 1,000 tests (about 2 million results over 90 days, two runs per commit like CI shards), PostgreSQL 15 in Docker:

| Query | Time |
|---|---|
| trends, 365 days | 15 ms |
| tests, 90 days, sort=failures | 1,280 ms |
| tests, 90 days, search | 514 ms |
| history, 90 days | 16 ms |
| flaky, 14 days, live scan | 2,130 ms |
| flaky, 30 days, live scan | 3,229 ms |
| flaky, 90 days, live scan | 11,305 ms |
| rollup backfill, 90 days (one-off) | 34,828 ms |
| flaky, 14 days, from rollups | 833 ms |
| flaky, 90 days, from rollups | 3,887 ms |

Regenerate with `docker compose exec -T ingestion-service python - < scripts/analytics_benchmark.py` in a throwaway stack.

Report sections (`scripts/bench_report.py`, 90-day period plus 90 days of look-back, PostgreSQL 15 in Docker on a Windows 11 developer machine, 20 logical CPUs and 32 GB; p95 of 20 runs per row, after `VACUUM ANALYZE`). Seeded totals cover the 180 days, so each size holds about half of them per 90 days. Measured 2026-10-09 to 10 after the Phase 3 query reshaping, on a quiet host: before each size no test run, build or other bench was running (checked with `docker stats` and the process list; total CPU about 10%, a memory indexer using about half a core). Size A was run twice: the first run read 1,123 ms for `regressions` on every branch and the second 719 ms; the table shows the second run, where every row is under 1 s:

| Size | Filters | summary | failure_causes | regressions | tests | duration |
|---|---|---|---|---|---|---|
| A (~100k results per 90 days; 3,060 runs x 67 over 180 days) | every branch | 463 ms | 158 ms | 719 ms | 818 ms | 54 ms |
| A | main only | 279 ms | 119 ms | 492 ms | 263 ms | 20 ms |
| A | 300 test keys | 229 ms | 125 ms | 362 ms | 243 ms | 120 ms |
| A | origin qeos, 2,000 seeded run URLs | 94 ms | 74 ms | 318 ms | 205 ms | 22 ms |
| A | 30 days, every branch | 85 ms | 70 ms | 271 ms | 180 ms | 13 ms |
| B (~2M results per 90 days; 3,960 runs x 1,000 over 180 days) | every branch | 2,464 ms | 1,770 ms | **8,425 ms** (p50 7,678) | 6,751 ms | 35 ms |
| B | main only | 2,303 ms | 1,356 ms | 7,522 ms | 4,727 ms | 28 ms |
| B | 300 test keys | 3,208 ms | 1,317 ms | 4,394 ms | 4,803 ms | 1,177 ms |
| B | origin qeos, 2,000 seeded run URLs | 814 ms | 640 ms | 3,093 ms | 1,752 ms | 17 ms |
| B | 30 days, every branch | 1,062 ms | 845 ms | 4,462 ms | 2,458 ms | 15 ms |

Every section meets its size A target (p95 1 s). At size B every section meets 8 s but one: `regressions` over 90 days on every branch, p95 8.4 s (p50 7.7 s), well under the 20 s statement timeout; `tests` there is 6.8 s, and `regressions` on main only is 7.5 s. A noisier earlier run (another test session overlapping) read 12.2 s and 8.5 s for the two. The two share one cost: one sort and window over the non-skipped results of every test that failed in scope (about 2 million rows for `tests`, the period; 3.9 million for `regressions`, with the look-back). The rest of `tests` no longer sorts every row of the period: the last status reads the newest runs first in doubling batches, and `pairs` counts non-skipped rows per (test, branch) less repeated attempts, instead of `count(DISTINCT run_id)`. `summary` counts distinct tests through a grouped subquery (2.5 s at B; 5.0 to 9.3 s on the same day before the change). A covering index `(run_id) INCLUDE (test_key, status, duration_ms)` was built on the size B data and EXPLAINed: PostgreSQL used it for none of these queries (the costs are sorts and hashes, not the scan), so it was not added. The next remedy for `regressions` at B is a daily per-test rollup of outcomes, or as an interim step a per-request `SET LOCAL work_mem` that keeps the sort in memory; neither is built: the size B miss was accepted on 2026-10-10, to revisit when a real project nears size B.

The flaky window goes up to 90 days. Flip counting recombines from the `flaky_daily` rollups the `analytics-rollup` job keeps current (backfill on start, then yesterday + today every 6 hours); a project the job has not visited yet falls back to the live scan with identical results (equivalence is pinned by `tests/unit/test_flaky_rollup.py`). Confirmed same-commit detection stays on the live failure-driven pass at every window — it rides the `(test_key, run_id)` index and dominates the remaining 90-day cost. The data is deliberately hard: failures are spread randomly, so nearly every test is a candidate.

## Test impact

QEOS suggests which tests a change is likely to affect, from which tests **newly failed** after earlier changes to
the same files or folders (spec `docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md`, ADR-029). No
coverage instrumentation, no AI: co-failure statistics on PostgreSQL.

### Statistics (the `impact-rollup` job)

- **Newly failed:** the test's outcome in run R fails (failed or errored; the outcome is the last attempt among
  non-skipped results) and its previous outcome on R's branch, within the 90 days before R, passed. A branch with
  no previous outcome there (a new PR branch) uses the test's latest outcome on the base branch before R
  (`base_branch`, else `change_base_ref` without `origin/`). Flaky tests (the Flaky view's defaults: 5 runs, 30%
  flips) and muted tests never newly fail. Outcomes are read with the Report's regressions query (one sort; only
  failing outcomes and their neighbours), so the two features cannot disagree on what an outcome is.
- **Path units:** each changed path and its nearest parent folders, at most 3 (`src/payment/api.py`,
  `src/payment/`, `src/`); empty, `.` and `..` segments are dropped. Lock files (`*.lock`, `package-lock.json`,
  `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`) and anything under `dist/`, `build/`, `vendor/` or `node_modules/`
  are not units. A change of more than 300 distinct paths counts at folder level only. Runs whose change list the
  collector truncated are left out.
- **Tables** (migration 018), rebuilt per project in one transaction by `python -m src.ingestion.jobs.impact_rollup`
  (one pass on start, then every 24 hours with `--loop`, lock 7351004, heartbeat `impact_rollup`):
  - `impact_pairs (project_id, unit_hash, test_key, path_unit, changed_runs, new_failures, computed_at)`: only
    pairs with at least one new failure, over the runs with changed files from 90 days before today 00:00 UTC.
    Keyed by `(project_id, unit_hash, test_key)` with `unit_hash = md5(path_unit)`: no id to run out, and a long
    path never enters an index;
  - `impact_test_base (project_id, test_key, runs, new_failures, flaky, suite, class_name, name, file,
    computed_at)`: every test that ran in those runs, with names and file from its newest such run, so scoring never
    scans `test_results`.
  The same data gives the same rows; a project whose runs are gone loses its rows at the next pass. The thresholds
  live in `src/ingestion/analytics/impact_rules.py`.
- **How a pass is built:** Python computes each run's path units (`impact_rules.py`) and its new failures, stages
  them in temporary tables (one `unnest()` insert each), and PostgreSQL does the rest: one `INSERT ... SELECT` per
  table. Early timing on PostgreSQL 15 (Docker, default settings; 1,980 runs of 1,000 tests over 90 days, one commit
  per run, 5% random failures, 502,000 pairs): 25-41 s per pass, against the 60 s budget. The pairs insert (about
  13 s) and the outcome read (8-14 s) are the largest parts; a full benchmark is to follow.

## Operations

- `GET /health`; `GET /metrics` (Prometheus, inside the Docker network only — not routed by the
  gateway): `qav_ingest_runs_total`, `qav_ingest_results_total`, `qav_ingest_rejected_total{reason}`,
  `qav_ingest_duration_seconds` (the `qav_` prefix predates the QEOS rename and is kept so dashboards and alerts keep working).
- Job heartbeats, read from `job_heartbeats` on every scrape: `job_last_success_timestamp_seconds{job}` and
  `job_last_error_timestamp_seconds{job}` (Unix seconds) for `retention`, `rollup` and `weekly_summary` (always present; any other job name with a row is exposed too). `0` means
  never: no successful (or no failed) pass has been recorded yet, so a job that has not succeeded yet looks stale.
  If the database read fails, the job series are left out and `job_heartbeat_read_errors_total` increases while
  `/metrics` keeps answering (the read has its own one-connection engine and a 2 s connect, pool and statement budget). Prometheus scrapes ingestion with `honor_labels: true` so `job` keeps the loop job's name.
- Uploads never call another service; key management and reads need project-service (503 if it is down).

## Known limitations

- Deleting a project does not revoke its keys; revoke them first.
- JSON only — parsing JUnit XML and other formats is the collector's job.

## Running locally

```bash
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # also installs ../../shared
cp .env.example .env                                         # set SECRET_KEY = auth-service's
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn src.ingestion.api.main:app --reload --port 8003
```

Tests: `SECRET_KEY=test-secret .venv/Scripts/python.exe -m pytest tests/ -q`
