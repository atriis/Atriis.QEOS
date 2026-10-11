# QEOS — Implementation Plan

Updated 2026-10-11. Single forward plan, reconciled with TODO.md (the live
per-item record) and ARCHITECTURE_BLUEPRINT_V1_0.md (the target; its
Implementation Status banner carries the adoption triggers referenced here).
The previous version of this file was a day-one snapshot that still named
paths and phases long since superseded.

## 1. Done (verified, running, tested)

| Phase | Delivered |
|---|---|
| 1. Platform foundation | auth-service (JWT rotation + replay detection, email-verified registration, password reset and change, Google/Microsoft SSO with tenant allowlist, TOTP MFA + recovery codes, httpOnly refresh cookie), organization-service (orgs/members/roles/invitations), project-service (projects/settings/repositories/legal hold/internal retention API), NGINX gateway (rate zones, TLS, JSON errors, request IDs, SPA catch-all), compose stack, CI with full-stack smoke |
| 2. Ingestion | ingestion-service collect API (API keys, idempotency+replay, built-in and per-project masking, retention job, export), qeos-collector (JUnit incl. Surefire rerun attempts, Cucumber/Playwright JSON, TRX/NUnit/xUnit/TestNG, CI detection, git code-change data, retrying multi-part uploads, spool, `--gate`), GitHub Action, Jenkins library, GitLab/Azure templates, zipapp and GHCR image per release |
| 3. Analytics + UI | Analytics API (trends day/week/month, tests, history, flaky ≤90 d via daily rollups + rollup job, branches, quarantine, run compare, failures by cause), the Report (summary, failure causes, regressions/instability, by area, coverage, duration; ADR-026), notifications (Slack/Teams/webhook/email, weekly summary), React dashboard (login/MFA/SSO, picker, organization admin, all analytics views, runs browser incl. changed files, report, CSV export, account security, command palette), 20/20 design audit |
| 4. Test management (started on product pull) | test-management-service (ADR-022): cases, suites, Feature view, Gherkin import from the browser and sync from the default branch (ADR-023, ADR-024); Run from QEOS through the customer's GitHub Actions with a duration estimate (ADR-025) |
| Deployment | single-VM production package (`deploy/`, ADR-019: Compose + Caddy TLS edge, generated secrets, daily backups) |

Benchmarked: flaky 90 d 3.9 s (rollups) vs 11.3 s live on ~2M results; full
numbers in platforms/ingestion-service/README.md.

## 2. Now / Next (small, unblocked — TODO.md carries the authoritative list)

1. ~~Git metadata on runs~~ — done 2026-10-02: commit author/message, PR
   number, base branch stored per run (migration 007) and shown on run detail.
2. ~~Collector `--ca-file` fix~~ — done: `--ca-file` now pins trust exclusively (curl `--cacert` semantics); blending with the system store broke on Windows machines with CN=localhost dev certs in ROOT.
3. ~~Confirmed-flaky pass optimization~~ — investigated 2026-10-02 and
   closed without change: on the 2M-row benchmark the current failure-driven
   correlated-EXISTS pass measures 1.6 s at 90 d and beats an aggregate-join
   rewrite (3.8 s, identical result sets). The confirmed pass is a minority
   of the 90-day total; revisit only if real data shows otherwise.
4. ~~Collector distribution~~ — mostly done (full list in TODO.md
   "Collector — nice to have"): release tags `collector-v0.1.0`…`v0.4.1`
   with zipapp and GHCR image (PyPI trusted publishing is in the release
   workflow, switched on by `PYPI_PUBLISH`); GitHub Action, Jenkins library, GitLab/Azure templates; Cucumber
   JSON, Playwright JSON, TestNG/NUnit/xUnit/TRX; `qeos-collector check`;
   keep-and-retry failed uploads (`--spool`). Open: partial streaming.
5. Phase 2 exit proof: agents on 3 CI platforms in real projects; 10k real
   executions ingested.
6. ~~Components under test~~ — done 2026-10-02: runs may record which
   repo/versions they exercised (`--component NAME@SHA`); dormant data for
   Phase 6 cross-repo correlation (ADR-018).
7. Monitoring — in progress: Prometheus, Alertmanager and Grafana as an
   opt-in compose profile (spec `docs/superpowers/specs/2026-10-10-monitoring-design.md`,
   plan `docs/superpowers/plans/2026-10-10-monitoring.md`). Phase 1 of 3
   shipped 2026-10-11: `/metrics` with blueprint names on every service and job
   heartbeats. Phase 2 (the stack: Prometheus, Alertmanager, exporters, alert
   rules) built and pushed with this phase; Phase 3: the five Grafana dashboards
   are provisioned; the Grafana sign-in gate is in progress (auth-service's
   cookie and check, the gateway's gated `/grafana/` location, the dashboard's
   Monitoring item and `/monitoring` hand-off page); CI smoke checks, ADR-027
   and the Phase 3 gate are next.
8. Then, in the order agreed 2026-10-08 (TODO.md "Execution intelligence and
   operations"): customisable Overview, test impact analysis.

## 3. Blocked on external input

- SAML 2.0 sign-in and real-tenant SSO verification: need an IdP / client
  IDs (note: `collaboration/` vendors an xmlsec source tree usable for SAML).
- Production deployment: the package is ready and verified (`deploy/`, ADR-019: one VM,
  Compose + Caddy TLS edge); waiting on a VM and a domain.

## 4. Later — target-architecture slices, each behind its blueprint trigger

| Slice | Trigger |
|---|---|
| Queue-based ingestion (Kafka) | sustained 1000+ events/s or CI-visible upload latency |
| Redis shared rate limits / cache | second gateway instance |
| ClickHouse analytics warehouse | rollups stop holding at ~10× data |
| Artifact storage (MinIO) | artifacts feature starts (screenshots/videos/traces) |
| Kubernetes + real certs | first multi-node deployment (the monitoring stack does not wait for it: it is in progress as a compose profile, §2) |
| ~~Test Management service (blueprint capability)~~ | started 2026-10-06 on product pull (ADR-022): cases, suites, link to automated tests, Gherkin import (ADR-023) and sync (`qeos-collector import-features`, ADR-024), Run from QEOS (ADR-025). Next slices: versioning, dynamic suites, ticket links |
| Workspaces: group QA projects with the product repos they test (Phase 4) | product pull, after Phase 2 exit; components-under-test data (ADR-018) is already being captured |
| GitHub App "connect repository" (commits/PRs of product repos via API + webhooks) | cross-repo correlation work begins (Phase 6); ingestion stays push-based regardless |
| Phase 6 AI engine, QIP services, vector/graph stores | AI work begins; revive or replace the `intelligence/` prototype deliberately — failure↔product-commit correlation feeds on run components (ADR-018) |

## 5. Prototype directories

`execution/`, `automation/`, `marketplace/`, `collaboration/`,
`intelligence/`, `platforms/qip-service` are unwired prototypes (no compose,
CI, gateway, migrations). Decision pending: archive to a branch or revive
per-slice when their capability's trigger fires. Do not treat their presence
as shipped functionality.

## 6. Working agreement

- TODO.md is updated in the same commit as the work it records.
- Direct pushes to master; all relevant suites green before every push; TDD
  for behavior changes.
- Every new feature names the blueprint section it serves or amends; pulling
  a TARGET technology requires citing its trigger.
