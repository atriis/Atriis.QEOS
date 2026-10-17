# QEOS — Technical Specification (Current State)

Updated 2026-10-11. This document specifies the system **as it runs today**.
The target architecture lives in ARCHITECTURE_BLUEPRINT_V1_0.md (see its
Implementation Status banner and adoption triggers); the delivery record is
TODO.md; the forward plan is IMPLEMENTATION_PLAN.md. The previous version of
this file duplicated Blueprint §5–§11 and described an unbuilt system.

## 1. System Overview

Five FastAPI services behind one NGINX gateway, a React SPA, a CLI collector
agent, and four background jobs — all on PostgreSQL 15, all deployed via the
repository-root docker-compose (production: the same stack on one VM behind a
Caddy TLS edge, `deploy/`, ADR-019).

```
qeos-collector (CI) ──► gateway ──► ingestion-service ──► ingestion_db
                               └──► test-management-service (Gherkin sync)
browser (dashboard SPA) ─► gateway ─► auth / organization / project / ingestion / test-management
jobs: ingestion-retention, analytics-rollup, impact-rollup, weekly-summary (ingestion image, advisory locks)
```

All cross-service communication is synchronous HTTP: project-role checks
against project-service (which asks organization-service), user lookups on
auth-service's internal API, and the retention job on project-service's
internal API. Services never call each other for page data; the dashboard
joins (ADR-022, ADR-026). Outbound calls: GitHub (Run from QEOS), repository
providers (verification), notification webhooks and SMTP. No event bus exists
(Kafka is a blueprint target gated on the 1000+ events/s trigger). Every
service serves Prometheus `/metrics` (never routed by the gateway); ingestion also
exposes job heartbeats (`job_last_success_timestamp_seconds{job}`, from the
`job_heartbeats` table, migration 017). The opt-in `monitoring` compose profile (Prometheus, Alertmanager,
node-exporter, cAdvisor, postgres-exporter, alert rules) scrapes them; Grafana
ships five provisioned dashboards (ADR-027). Its sign-in gate: with `MONITORING_ENABLED` on, the
gateway's `/grafana/` checks the `qeos_grafana` cookie with auth-service on every request and signs the
superuser into Grafana's auth proxy (otherwise `/grafana/` is a 404). The dashboard shows superusers a
Monitoring item (from `monitoring_url` on `/users/me`) that calls `POST /auth/grafana-session` and opens
Grafana; its `/monitoring?next=` page does the same when the gateway sends a cookieless visit there
(`docs/superpowers/specs/2026-10-10-monitoring-design.md`).

## 2. Services

### 2.1 auth-service (`platforms/auth-service/auth-service`)
- Registration with email verification (PendingRegistration → User on
  GET /auth/verify-email; unverified addresses are unclaimed).
- Login: JWT access token (60 min) + opaque refresh token (30 d, DB-stored,
  rotated on use, replay ⇒ every session revoked). Refresh token also set as
  httpOnly cookie `qeos_refresh` (Secure, SameSite=Strict, Path=/api/v1/auth);
  body token kept for API clients; `/auth/refresh-token` and `/auth/logout`
  accept body or cookie. The pre-rename cookie `qav_refresh` is still read when
  `qeos_refresh` is absent; every token issue clears it, and logout clears both
  cookies (and `qeos_grafana`) on every answer, even with an expired access
  token, and revokes the session behind each.
- Password reset and change: `/auth/forgot-password` sends a single-use link
  (token stored SHA-256-hashed, 30 min); `/auth/reset-password`,
  `/auth/change-password`; a reset or change ends every session.
  `/auth/resend-verification` re-sends the registration link. Without SMTP the
  links are written to the service log.
- MFA (TOTP): `/auth/mfa/enroll|confirm|disable`; login answers
  `{mfa_required, mfa_token}` (5-min purpose-bound JWT) and
  `/auth/mfa/verify` completes with a TOTP or single-use recovery code
  (8 issued once, bcrypt-hashed). SSO sign-ins bypass MFA (IdP's factor).
- SSO: `/sso/google`, `/sso/microsoft` verify provider ID tokens
  (`{credential}`) against JWKS; Microsoft restricted to AZURE_ALLOWED_TENANTS;
  signing-key fetch hardened (timeout, throttled refresh; outages ⇒ 503).
  `/sso/github` is an honest 501. `/users/me/link/google|microsoft` links a
  provider to an existing account.
- SSO-only mode (ADR-031): `AUTH_SSO_ONLY`, `AUTH_SSO_PROVIDERS`. Public
  `GET /auth/methods` → `{password, providers}` tells the dashboard what to show.
  In the mode, registration, verification and recovery answer 403
  `{"detail": {"code": "sso_only", ...}}`; `/auth/login` lets only active
  superusers through (same 403 for every other case, MFA kept, logged as
  break-glass); unlisted providers answer the same 403.
  `GET /users/me` carries `linked_providers`, `sso_only` and `has_password` for the
  Security page.
  Superusers: `GET /users/sso-readiness` (active users, how many linked Microsoft, the
  unlinked list) and `POST /users/{id}/allow-microsoft-link` (a one-time 7-day link
  allowance, logged at WARNING; 404 unknown, 409 linked or inactive), used at the
  next `/sso/microsoft` from an allowed tenant and then cleared.
  Off-to-on: non-superuser refresh sessions revoked once (`auth_mode_state`,
  migration 008, row lock).
- Every service accepts only access tokens as sessions (MFA challenge, refresh
  and service tokens are rejected). `/internal/v1/users[/{id}]` (HTTP Basic,
  INTERNAL_API_PASSWORD; not routed by the gateway) serves organization-service.
  organization-service has its own internal API (`/internal/v1/sso-roles`, section 2.2).
- Entra app roles (ADR-033, migration 009): `oauth_accounts` gains `sso_roles` (JSON),
  `sso_roles_at` and `sso_roles_synced_at`. After each Microsoft sign-in and link, auth-service
  posts the token's roles to organization-service's `/internal/v1/sso-roles` (HTTP Basic, user
  `auth-service`, 5 s timeout; settings `ORGANIZATION_SERVICE_URL` and
  `ORGANIZATION_INTERNAL_API_PASSWORD`). A failed push is logged and retried at the next token refresh.

### 2.2 organization-service
Organizations (soft delete), members (owner/admin/member/viewer/
billing_manager; only an owner grants or removes owner/admin), invitations
(7-day single-use token returned to the inviter — this service sends no email;
`GET /invitations/{token}` previews it for a signed-in user, then accept),
`GET /organizations` lists the caller's active memberships with role,
`GET /organizations/{id}/members/me` answers the caller's role for the other
services. Member lists carry emails from auth-service's internal API. Role
checks via JWT `sub` + membership.
Entra app roles (ADR-033, migration 004): `organization_sso_role_mappings` maps an
app role value to admin, member or viewer per organization (owners only:
`/organizations/{id}/sso-role-mappings`; 409 `duplicate_app_role`, 422 for owner or
billing_manager). Members carry `managed_by` (`entra` or null); a managed member
cannot be removed by hand (409 `managed_by_entra`). The internal API
`POST /internal/v1/sso-roles` (HTTP Basic, `INTERNAL_CALLER_USERNAME` and
INTERNAL_API_PASSWORD; not routed by the gateway) reconciles one user's managed
memberships from the token's app roles and logs each change at INFO. Only organizations
an active superuser approved are reconciled (migration 005, `entra_sync_approved_at`;
`PUT /organizations/{id}/entra-sync` and `GET /organizations/entra-sync`, superusers
checked through auth-service's internal user lookup, which now returns `is_superuser`).

### 2.3 project-service
Projects under organizations (access follows org roles), settings
(result_retention_days, default_environment, notify_on_failure), repositories
(GitHub, GitLab, Azure DevOps; checked against the provider's public API),
legal hold (owner/admin, with a required reason; retention deletes nothing of a
held project), internal retention endpoint (HTTP Basic, INTERNAL_API_PASSWORD)
consumed by the retention job. Project deletion (ADR-034): `DELETE` records who and
when (409 under a legal hold); a pending project answers 410 with `purge_at` on
`GET /projects/{id}` (404 elsewhere), is listed with `include_pending=true` for
owners/admins, `POST /projects/{id}/restore` undoes it (409 on a name taken
meanwhile or once the purge started); internal `POST /internal/v1/projects/{id}/purge-state`
and `DELETE /internal/v1/projects/{id}` drive the purge after
`PROJECT_DELETE_GRACE_DAYS` (7). Overview layouts (`/projects/{id}/overview-layout`):
GET resolves personal → project default → built-in; `PUT`/`DELETE /personal` for
every role, `/project` for owner/admin; a save names its `version` (0 creates) and
a stale one is a 409 carrying the stored row; layouts are validated against
`shared/qeos_shared/overview_widgets.json` (24 widgets, 64 KB).

### 2.4 ingestion-service
- **Collect**: `POST /collect/runs` with project API key (`qeos_` bearer; keys issued
  before the QEOS rename start with `qav_` and are still accepted).
  Validation (extra="forbid"), idempotency keys with body-hash replay
  detection, PII masking before truncation, server-computed counts, optional
  `changes` block (base ref + ≤1000 changed files; git name-status letters;
  null additions/deletions for binary), git metadata (author, message, PR,
  base branch), components under test (ADR-018). The receipt reports
  `quarantined`/`blocking` failures for `qeos-collector upload --gate`.
  `GET /collect/key` checks a key and answers `project_id`, `name` and `can_read_impact`; `POST /collect/token` trades it for a
  5-minute service token that only test-management's import accepts (ADR-024).
  `POST /collect/impact` scores a change for the key's project with the analytics route's scoring, limits and
  503 `impact_timeout`, for the collector's `impact` and `run-impact`; only keys with `can_read_impact`
  (403 `impact_not_allowed` otherwise).
  Optional `run.trigger` (`manual`, `automatic` or `qeos`; anything else is a 422), reported by the
  collector and stored on the run. When the project has switched off collection of manual runs
  and `trigger` is `manual`, the answer is `202 {"discarded": true, "reason": "manual runs are
  not collected for this project"}` and nothing is stored (ADR-030).
  Optional `run.scope` (`full` default, `impact-subset`) and `run.stages` (run-impact's stages: duration, tests
  and failures per stage, `time_to_first_failure_s`, `stopped_after_stage`; migration 020), left out of the
  request hash at their defaults; a split upload keeps the `stages` on its first part that sends them. A 422
  never echoes the submitted value (no `input` or `ctx`). Optional `results[].log` (string; masked, cut to 64 KB,
  stored in `test_results.log`, migration 023; left out of the request hash while null).
- **Collection settings**: `GET/PUT /projects/{id}/collection-settings` (`collect_manual`, default
  true; `discarded_count` and `last_discarded_at`; members read, owners and admins write), table
  `collection_settings` (ADR-030).
- **Masking**: built-in rules (authorization headers, cookies, URL and CLI
  passwords, JWTs, vendor tokens, private keys, key=value secrets, emails, card
  numbers) plus up to 20 per-project patterns on RE2 (`/masking-patterns`, with
  a preview; ADR-020); `python -m src.ingestion.jobs.remask` re-masks stored
  results.
- **Log values** (ADR-032): `GET/POST /projects/{id}/log-patterns`, `DELETE …/{pattern_id}`, `POST …/preview`;
  tables `log_patterns` (≤ 20 per project, RE2, at most one capture group, optional https `link_template`) and
  `log_values` (≤ 20 distinct values per pattern per result, 200 characters, cascading with the result and the
  pattern); the re-scan counters `collection_settings.log_scan_requested/done/started_at` (migration 023; `GET …/log-patterns` reports the scan as `idle`, `queued` or `running`). Values come
  from the masked `test_results.log`.
- **Read**: runs list per project (filters: branch, failing/passing, environment, CI, commit
  prefix, PR, author, started-at range, scope, an exact log `value` with an optional `pattern`), run detail with status and log-value filters and changed
  files, a result's whole masked log (`GET /projects/{id}/runs/{run_id}/results/{result_id}/log`, with its values), failed steps across test cases (`GET /projects/{id}/runs/{run_id}/failed-steps`: by step definition or text, errors by shape, failing since on the run's branch, 50 runs / 90 days), run summary, failures grouped by error signature, comparison of two
  runs. Access: user JWT + project role via project-service.
- **Analytics** (read roles): trends (`bucket=day|week|month`, Monday weeks,
  any IANA tz, ≤365 d), per-test list (sort/search/limit≤200/offset),
  history (encoded test_key), flaky (`window_days≤90`, min_runs,
  min_flip_rate, branch, include_muted), branches (per-branch aggregates),
  quarantine (`PUT/DELETE /flaky/mute`, edit roles: a quarantined test still
  runs and shows, but its failures do not fail a run or alert), latest-keys (optionally within a `since`/`until` period),
  latest-results (each test's latest result with its failed step (for a skipped result, the step it stopped at) and log values, or with `run_id` its result in
  that run, which a Last runs bar opens; the result payload's optional
  `failed_step` `{text 1-1000, line 1-1,000,000, definition 1-500, pattern 1-1000}` is stored masked; unknown fields in it are ignored) and
  run-strip (each test's own last results with their log values, for case lists), duration-estimate (Run from QEOS),
  test impact (ADR-029; every role that reads runs): `POST /analytics/impact`
  scores any change (1–5,000 paths of 1–1,000 characters, optional branch)
  against the co-failure statistics with the upload's scoring under the same
  2 s statement timeout (503 `impact_timeout` when it runs out);
  `GET /analytics/impact-accuracy?days=7|14|30` gives caught, missed, rate
  (null without new failures) and suggested tests per run, live and replayed
  apart, with at most 50 misses and their total; and
  `GET /projects/{id}/runs/{run_id}/impact` reads the suggestion stored with a
  run at upload (scored before its results), its changed paths and its outcome
  (`ok`, `not_enough_history`, `no_change_data` or `not_scored`). Its `evaluation` is `not_evaluated` for a
  run of only the suggested tests (`scope = impact-subset`), which the statistics, the outcome evaluation and
  the accuracy figure leave out.
- **Report**: `POST /analytics/report` with sections summary, failure_causes,
  regressions, tests, duration over a period (ADR-026; the dashboard joins
  test-management's case areas for "by area" and coverage).
- **Notifications**: channels per project (Slack, Teams, https webhook, email
  to 1–5 addresses), on failed runs (branch filter) and/or a weekly summary;
  test button, last delivery recorded; SSRF guard (public addresses, no
  redirects); URLs never returned.
- **Export**: `GET /projects/{id}/export` streams everything stored for a
  project as NDJSON.
- **Jobs**: `ingestion-retention` (per-project retention, skips projects on
  legal hold, purges deleted projects in every service after
  `PROJECT_DELETE_GRACE_DAYS` in recorded steps (ADR-034), pg advisory lock
  7351001); `analytics-rollup` (flaky_daily backfill ≤90 d + yesterday/today
  every 6 h, lock 7351002); `weekly-summary` (Mondays, once per channel per
  week, lock 7351003); `impact-rollup` (test impact statistics: impact_pairs
  and impact_test_base over 90 days, every 24 h, lock 7351004; ADR-029;
  `--backfill-days N`, 1–90, replays past runs once under lock 7351005, no
  heartbeat).

### 2.5 test-management-service (`platforms/test-management-service`, ADR-022)
- **Cases**: per-project numbers shown as `TC-n` (never reused; archive, no delete), title,
  description, up to 50 `{action, expected}` steps, up to 20 lower-case labels, priority,
  status (draft/ready/archived), optional link to an automated test (`automated_test_key`, the
  ingestion `test_key`; the dashboard reads its latest result from ingestion).
- **Lists**: search (title), label (ANDed), status, priority, folder, feature, link and
  latest-result filters, paging (`GET /cases`, `POST /cases/search`); `GET /case-labels`,
  `/case-folders`, `/case-features` count what is in use; `GET /case-areas` gives every active
  case's areas for the report.
- **Gherkin** (ADR-023, ADR-024): `POST /cases/import` takes `.feature` files from the browser
  or from `qeos-collector import-features` (CI, default branch, service token); scenarios become
  cases keyed by file and scenario, a full import archives cases of missing files. `GET /features`
  and `/features/detail` serve the Feature view and page.
- **Run from QEOS** (ADR-025): `ci-target` holds the GitHub repository, workflow and branch, and
  a token encrypted at rest with Fernet (`TM_SECRETS_KEY`); `run-requests` dispatches the
  workflow (`workflow_dispatch`) for a case, a selection or a suite, tracks its status, stops it,
  stores the duration estimate, and lists run URLs for the report.
- **Suites**: unique name per project, ordered cases replaced as a whole by
  `PUT /suites/{id}/cases` (≤1000, unknown or repeated numbers are a 422); deleting a suite keeps
  its cases. `GET /suites?created_by=me` lists the caller's own suites.
- Access: user JWT + project role via project-service (every role reads; owner/admin/member
  edit), the same contract as ingestion. The client is a copy of ingestion's (ADR-022).

## 3. Data

PostgreSQL 15; one database per service (auth_db, organization_db,
project_db, ingestion_db, testmgmt_db), created by db-init, migrated by per-service
Alembic jobs. Only the owning service writes its database; cross-domain
reads go through APIs (blueprint principle, enforced in practice).

Key ingestion tables: test_runs (+ change summary columns), test_results
(message/details masked+truncated, `failed_step_text`/`failed_step_line`/`failed_step_definition`/`failed_step_pattern` (text fields masked; partial index on the definition), `(test_key, run_id)` index),
run_changed_files, run_components, muted_tests (quarantine), flaky_daily /
flaky_rollup_days (daily flip aggregates + computed-day markers), impact_pairs /
impact_test_base (test impact statistics, rebuilt nightly) and run_impact (the
suggestion stored with a run and its outcome; cascades with the run), api_keys
(SHA-256 of the key; `can_read_impact`, off by default, set by owners and admins), masking_patterns,
notification_channels, collection_settings. Test-management:
cases, case_labels, suites, suite_cases, feature_files, ci_targets,
run_requests. Project: projects, repositories, overview_layouts (a JSONB layout
per project default or user, with a version for conflict checks).

## 4. Flaky Detection Semantics (rulings)

- **Confirmed (`same_commit`)**: the test passed and failed for one
  (commit, environment) across *different* runs — a duplicate inside one run
  is not a re-run.
- **Suspected (`flips`)**: outcome changes between consecutive executions,
  counted per branch; skipped excluded; errored↔failed is not a flip.
- Windows ≤90 d recombine exactly from `flaky_daily`
  (in-day flips + day-boundary transitions; pairs = per-branch runs−1);
  equivalence with the live scan is pinned by unit tests. Projects the
  rollup job has not visited fall back to the live scan.
- Measured (≈2M results): flaky 90 d 3.9 s from rollups vs 11.3 s live;
  14 d 0.83 s. Remaining 90 d cost is the failure-driven confirmed pass.

## 5. Gateway

NGINX: TLS (self-signed in dev), per-IP rate zones (`api` 20 r/s; `collect`
10 r/s on uploads; a stricter `auth` zone, 5 r/s, on login, register, password
reset/change, resend-verification, mfa/verify and sso), 10 MB bodies (the
Gherkin import route: `GATEWAY_IMPORT_MAX_BODY`, default 25 MB), gzip only on
the report and case-areas, JSON error pages, request IDs, regex routes sending
`/projects/{id}/(api-keys|runs|analytics|masking-patterns|log-patterns|export|notification-channels|collection-settings)`
to ingestion and `/projects/{id}/(cases|case-labels|case-folders|case-features|case-areas|features|suites|ci-target|run-requests)`
to test-management, SPA catch-all to the dashboard container with JSON 404
preserved for unrouted `/api/` paths; `/metrics` and `/internal` are never
proxied.

## 6. Dashboard (`dashboard/`)

React 19 + Vite + TypeScript, TanStack Query, Recharts (lazy chunks for
chart views). Access token in memory; session restored at boot via the
httpOnly cookie; 401s refresh once (auth/sso endpoints excluded). Views:
login (password/MFA step/SSO buttons when VITE_* client ids are baked; SSO-only layout from /auth/methods with a superuser disclosure),
register, verify email, forgot/reset password, org→project picker,
organization (members, invitations) and invitation accept, overview (a
customisable grid of 15 code-split widgets and three templates over the
existing queries, a personal layout and a project default, edit mode with
Reload/Overwrite on a stale save, ADR-028), trends
(day/week/month), tests, history, flaky (quarantine, CSV export), branches
(pick-two pass-rate comparison), runs (list + detail incl. changed files with
the likely affected tests and their outcome, ADR-029, and
failures by cause; new runs by polling every 30 s, ADR-021), run compare,
requested runs, report (incl. Test impact accuracy), test cases (Scenario and
Feature views, editor, Gherkin import, Feature page, Run likely affected), suites, project settings (API keys, CI
snippet, repositories, masking, notifications, Run from QEOS, legal hold,
export), account security (TOTP enrollment, password change), Ctrl K command
palette.
Design tokens with light/dark modes; WCAG AA contrast; status never
color-alone (PRODUCT.md commitments).

## 7. Collector (`collector/`)

`qeos-collector upload`: JUnit XML (pytest, Surefire incl.
flaky/rerun attempt expansion, Playwright, cucumber-js), Cucumber JSON,
Playwright JSON, TRX, NUnit 3, xUnit.net and TestNG; CI detection
(GitHub Actions/GitLab/Azure Pipelines/Jenkins), git code-change data
(GITHUB_BASE_REF / MR target / commit parent; never blocks an upload),
retry-safe idempotency keys, multi-part past 20k results / 9 MB, 2-minute
retry budget, `--spool` keeps failed parts for the next run, `--gate`,
`--component`, verified TLS (`--ca-file` pins a private CA). Also
`qeos-collector check` and `import-features`. Shipped as a GitHub Action
(`collector-action/`), a Jenkins library (`collector-jenkins/`), GitLab and
Azure templates (`templates/`), and per release tag a zipapp and a GHCR image.

From 0.7.0, `qeos-collector impact` prints the suggestion for the change (`POST /collect/impact`, which needs a key
with the "test suggestions" permission; cucumber, list or json; exit 0 printed, 3 nothing to suggest, 4 QEOS
unreachable or out of time, 2 a configuration error). `qeos-collector run-impact -- <cucumber command>`:
- discovers the scenarios with a Cucumber dry run (cucumber-js, cucumber-jvm through Maven/Gradle system properties,
  Ruby; `--cucumber` when the command hides the runner, `bash -c` command lines included);
- checks with a second dry run that rerun files alone select them, and refuses (exit 2) when profile `paths` or
  `--shard` would change that;
- runs the suggested ones, then the rest, from two rerun files, and uploads one run with `scope` and `stages`
  (`--fail-fast` and `--suggested-only` mark it `impact-subset`, stages go with the first part only);
- runs the whole command as one stage whenever scoring, setup or planning fails, and exits with the tests' code;
- writes a summary to the GitHub step summary, or to the log.

## 8. Verification

- Per-service pytest suites + shared tests, collector (Python 3.9/3.12),
  dashboard Vitest (Testing Library + MSW) + tsc + eslint + build.
- CI (`.github/workflows/ci.yml`): service matrix, collector matrix,
  dashboard job, per-service container smoke, gateway full-stack smoke
  (`scripts/smoke_gateway.sh`, 70+ checks), CodeQL.
- `scripts/analytics_benchmark.py`: seeded ~2M-result benchmark;
  `scripts/bench_report.py` times every report section; results recorded in
  platforms/ingestion-service/README.md.
- Workflow: direct pushes to master, full relevant suites green before every
  push; TDD (tests watched failing first) for behavior changes.

## 9. Explicitly Not Built (see blueprint triggers)

Event bus/Kafka, CDC, data lake/warehouse, knowledge graph, vector store,
Redis, MinIO, Elasticsearch, Kubernetes/service mesh/Vault/GitOps, QIP
services, SDKs, mobile, AI features. Monitoring stack (Prometheus,
Alertmanager, Grafana as an opt-in compose profile): shipped 2026-10-11 (ADR-027), plan
`docs/superpowers/plans/2026-10-10-monitoring.md`. `execution/`, `automation/`, `marketplace/`,
`collaboration/`, `intelligence/`, `platforms/qip-service` are unwired
prototypes excluded from compose/CI/gateway.
