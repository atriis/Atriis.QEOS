# Architecture Decision Records

**Accepted** — real decisions with evidence, extracted 2026-10-02 from
TODO.md, commit messages and benchmark rulings:

| ADR | Decision |
|---|---|
| [ADR-011](ADR-011-flaky-window-rollups.md) | 90-day flaky window via daily rollups; commit rollup and join rewrite rejected by benchmark |
| [ADR-012](ADR-012-same-commit-semantics.md) | A duplicate inside one run is not a re-run |
| [ADR-013](ADR-013-refresh-token-httponly-cookie.md) | Refresh token as httpOnly cookie; body kept for API clients |
| [ADR-014](ADR-014-pii-masking-on-ingest.md) | PII masking at ingest, before truncation; per-project retention |
| [ADR-015](ADR-015-idempotency-body-hash.md) | Idempotency keys with body-hash replay detection |
| [ADR-016](ADR-016-sso-bypasses-mfa.md) | SSO sign-ins bypass platform MFA |
| [ADR-017](ADR-017-gateway-spa-catchall.md) | Gateway catch-all serves the SPA; /api/ keeps JSON 404 |
| [ADR-018](ADR-018-components-under-test.md) | Capture components-under-test per run now; correlate in Phase 6 |
| [ADR-019](ADR-019-single-vm-deployment.md) | First production deployment: one VM, Compose + Caddy TLS edge, real-IP rate limits |
| [ADR-020](ADR-020-custom-masking-re2.md) | Per-project masking patterns run on RE2 (linear time), not Python's `re` |
| [ADR-021](ADR-021-live-runs-by-polling.md) | New runs reach the dashboard by polling every 30 s; push (SSE first) when the collector streams partial results |
| [ADR-022](ADR-022-test-management-service.md) | Test management is its own service (cases, suites, link to automated tests), started on product pull before the Phase 2 exit |
| [ADR-023](ADR-023-gherkin-import.md) | Gherkin import: the repository owns imported cases; moves, reactivation, and a previewed plan applied exactly |
| [ADR-024](ADR-024-service-tokens-for-ci-imports.md) | Service tokens for CI imports: ingestion trades a project API key for a 5-minute JWT that only the import route accepts |
| [ADR-025](ADR-025-run-tests-through-customer-ci.md) | Run tests from QEOS through the customer's CI: `workflow_dispatch`, an encrypted personal access token, no execution on our side |
| [ADR-026](ADR-026-report-joins-in-the-dashboard.md) | The report joins in the dashboard (case-areas + test keys); run origin is matched by CI run URL |
| [ADR-027](ADR-027-monitoring-profile.md) | Monitoring is an opt-in Prometheus/Alertmanager/Grafana compose profile; blueprint metric names; job heartbeats in a table; Grafana behind a QEOS cookie hand-off |
| [ADR-028](ADR-028-customisable-overview.md) | The customisable Overview: layouts in project-service (project default and personal, optimistic versions), one widget catalogue file shared by validation and the dashboard registry, refresh keys declared per widget, "my" widgets matched exactly by commit author name |
| [ADR-029](ADR-029-test-impact-analysis.md) | Test impact analysis: co-failure statistics on PostgreSQL rebuilt by the impact-rollup job, every suggestion stored at upload before its results and evaluated against its new failures, accuracy shown live and replayed apart; a learned model and embeddings come later; release B (2026-10-13, collector 0.7.0): suggested tests first in CI, partial runs kept out of the accuracy figure |
| [ADR-030](ADR-030-collect-manual-runs.md) | A project setting decides whether manual CI runs are collected: owned by ingestion, the collector classifies and sends `run.trigger`, an off project answers 202 and stores nothing, the trigger is client-reported (a noise filter, not access control) |
| [ADR-031](ADR-031-sso-only-mode.md) | SSO-only mode: `AUTH_SSO_ONLY` turns password registration, recovery and sign-in off except for active superusers (break-glass, logged); non-superuser sessions revoked once per off-to-on change; readiness and a one-time, 7-day Microsoft link allowance; switched in `.env`, never from the dashboard |
| [ADR-032](ADR-032-log-values.md) | Log values: each result's log is masked, cut to 64 KB and stored; per-project RE2 patterns (one capture group, optional https link) capture values from the masked log at upload and in a 90-day re-scan when a pattern is added; `run-strip` and `latest-results` carry them for the Last runs tooltips and the case page |
| [ADR-033](ADR-033-entra-app-roles.md) | Entra app roles: owners map app role values to admin, member or viewer (never owner); each Microsoft sign-in creates, updates or removes only `managed_by = entra` members, best effort and retried on refresh; managed members cannot be removed by hand; a superuser approves each organization first (amendment 2026-10-17) |
| [ADR-034](ADR-034-project-deletion.md) | Project deletion: owners and admins delete after typing the name; 7 days pending (410 with the date for members, greyed with Restore for owners and admins, uploads 410, nothing deleted); then the retention job purges test-management, ingestion and the project row, each step recorded so a failed pass resumes |
| [ADR-036](ADR-036-artifact-storage-step-screenshots.md) | Artifact storage: MinIO (S3-compatible, private, not published) holds step screenshots, content-addressed as `screenshots/{project_id}/{sha256}`; only ingestion reads and writes it, through `boto3`; off unless the four `ARTIFACTS_S3_*` settings are set; the volume needs its own backup; images cannot be masked |

**Proposed** — ADR-001..010 describe the TARGET architecture (DDD, Kafka,
Kubernetes, Go services, Neo4j, Qdrant, ...). Reclassified 2026-10-02: their
earlier "Accepted" status and 2024 provenance predate delivery and nothing in
them is deployed (the platform is Python/FastAPI + PostgreSQL throughout).
Each is adopted only when its trigger in the Blueprint's Implementation
Status banner fires. De facto accepted without ceremony: Python/FastAPI,
PostgreSQL, React + TypeScript (contradicting ADR-005's Go).
