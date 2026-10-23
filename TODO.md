# QEOS Implementation Progress

> Live item-level record. Forward plan: IMPLEMENTATION_PLAN.md. Target
> architecture + adoption triggers: ARCHITECTURE_BLUEPRINT_V1_0.md (read its
> Implementation Status banner first). Current-state spec:
> TECHNICAL_SPECIFICATION.md. New features name the blueprint section they
> serve; TARGET technologies enter only when their trigger fires.

## Completed Tasks

### Phase 1: Foundation Services - AUTHENTICATION SERVICE (COMPLETED)
1. [x] Analyze QEOS platform requirements and architecture specifications
2. [x] Brainstorm core architecture components and their interactions
3. [x] Design database schema for PostgreSQL based on requirements
4. [x] Plan microservices architecture and communication patterns
5. [x] Design plugin SDK architecture for extensibility
6. [x] Plan deployment strategies for multiple cloud platforms
7. [x] Design AI engine capabilities for test analysis
8. [x] Plan real-time features with WebSockets
9. [x] Design security and compliance features
10. [x] Plan observability and monitoring stack

### Documentation Created
- `docs/superpowers/specs/2026-07-13-qa-vision-architecture-brainstorm.md` - High-level architecture overview
- `docs/superpowers/specs/2026-07-13-qa-vision-database-schema.md` - Complete PostgreSQL schema design
- `docs/superpowers/specs/2026-07-13-qa-vision-microservices.md` - Detailed microservices architecture
- `docs/superpowers/specs/2026-07-13-qa-vision-plugin-sdk.md` - Plugin SDK design for extensibility
- `docs/superpowers/specs/2026-07-13-qa-vision-deployment-strategies.md` - Multi-cloud deployment strategies
- `docs/superpowers/specs/2026-07-13-qa-vision-ai-engine.md` - AI engine capabilities for test analysis
- `docs/superpowers/specs/2026-07-13-qa-vision-realtime-features.md` - WebSocket-based real-time features
- `docs/superpowers/specs/2026-07-13-qa-vision-security-compliance.md` - Security and compliance architecture
- `docs/superpowers/specs/2026-07-13-qa-vision-observability-monitoring.md` - Observability and monitoring stack

### Authentication Service Implementation (Phase 1 - Complete)
11. [x] Set up Auth Service project structure with FastAPI
12. [x] Implement PostgreSQL database models for Users, Sessions, and OAuth Accounts
13. [x] Create Alembic migration system for database schema management
14. [x] Implement secure password hashing with bcrypt (work factor 12)
15. [x] Develop JWT-based access token and refresh token system with rotation
16. [x] Build User Service for CRUD operations and authentication logic
17. [x] Build Auth Service for token management and user authentication
18. [x] Implement SSO framework with Google ID token validation
19. [x] Create RESTful API endpoints for:
    - User registration and email/password authentication
    - Token refresh and secure logout
    - Password reset (emailed single-use link) and signed-in password change, both ending every session
    - Google SSO authentication (GitHub/Azure placeholders for future implementation)
    - User profile management (self-service and admin endpoints)
20. [x] Implement comprehensive input validation with Pydantic models
21. [x] Add role-based access control (superuser vs regular users)
22. [x] Create Dockerfile and docker-compose for containerized deployment
23. [x] Develop comprehensive test suite (unit and integration tests)
24. [x] Generate interactive API documentation (Swagger UI and ReDoc)
25. [x] Create precise documentation with implementation status clarity
26. [x] Implement environment-based configuration management
27. [x] Add security best practices: CORS protection, SQL injection prevention, input validation
28. [x.1] [x] Implement refresh token rotation to prevent replay attacks
28. [x.2] [x] Password reset and change: hashed single-use 30-minute links, session revocation, dashboard pages (forgot / reset / Security), stricter gateway rate zone
28. [x.3] [x] Establish SSO foundation for future provider implementations

## In Progress / Next Steps

### Phase 2: Organization Service (delivered; reconciled 2026-10-04)
29. [x] Design organization and team management data models — organizations, organization_members (roles), organization_invitations
30. [x] Implement organization CRUD operations (soft delete included)
31. [~] Membership and roles done (owner/admin/member/viewer/billing_manager, last-owner protection); sub-teams inside an organization not built — no consumer yet
32. [x] Implement role-based access control (RBAC) within organizations — require_org_role, grant policy (admins cannot grant/remove owners)
33. [x] Develop invitation system for team members — single-use tokens, atomic claim, preview, dashboard accept page
34. [x] Create API endpoints for organization and team management
35. [x] Implement multi-tenancy data isolation — database per service; every project/ingestion read checks organization membership via /members/me
36. [x] Write comprehensive test suite (101 tests)
37. [x] Create API documentation — OpenAPI + platforms/organization-service/README.md
38. [x] Add Docker support — root compose, migration job
39. [x] Integrate with Auth Service for authentication and authorization — shared JWT, internal user lookup (single + batch)

### Phase 3: Project Service
40. [x] Design project management data models
41. [x] Implement project creation, updating, archiving
42. [ ] Create member and permission management within projects *(deferred: access follows organization roles; see the project-service design spec)*
43. [ ] Implement project categorization and tagging system *(not started)*
44. [ ] Develop project templates and cloning functionality *(not started)*
45. [x] Create API endpoints for project management
46. [x] Implement integration with Organization service for access control
47. [x] Write comprehensive test suite
48. [x] Create API documentation
49. [x] Add Docker support
50. [x] Integrate with Auth and Organization services
50.1. [x] Release the DB session before outbound HTTP calls (members/me, provider verification) so slow upstreams cannot exhaust the connection pool — read-only transactions end (rollback) before org-service members/me and before the repository provider call; the same defect fixed in ingestion's run detail (access check via project-service). Tests assert no open transaction at the moment of each HTTP call
50.2. [x] Map only uniqueness violations to 409 in project_service._commit; re-raise other IntegrityErrors — SQLSTATE 23505 on PostgreSQL (verified live: duplicate name → 409), SQLite message in tests; NOT NULL and other failures now surface as themselves

### API Gateway and full stack
- [x] NGINX gateway: routing, per-IP rate limits, self-signed TLS, JSON errors, request ids, JSON access log
- [x] Repository-root docker-compose: one Postgres, db-init, per-service migration jobs, shared SECRET_KEY
- [x] CI: full-stack smoke test through the gateway
- [x] Rename the compose project `qa-vision` to `qeos` (done 2026-10-11; Prometheus and Grafana volumes pinned too) (containers `qeos-*`, local images `qeos/*`) — agreed 2026-10-11, after the monitoring push. The data volumes keep their pinned names (`qa-vision_qav_postgres_data`, `qa-vision_qav_gateway_certs`), so no data moves; one `docker compose -p qa-vision down` (no `-v`) per host, then update scripts/CI/docs that name `qa-vision-*` containers and check `deploy/`
- [x] Monitoring follow-ups (Phase 3 final review, 2026-10-11), done 2026-10-11: cAdvisor dropped `/:/rootfs` and mounts the Docker and containerd sockets instead of all of `/var/run` (both sockets are needed; 17 compose services discovered before and after); the gateway strips `qeos_grafana` from the Cookie header it forwards to Grafana (Grafana's own cookies kept, the check still reads the full header); the job panels show "never" for a 0 timestamp; the smoke refuses a non-local `DOCKER_HOST`/docker context; the smoke checks that a forged header on the break-glass port `127.0.0.1:3000` gets 401 `auth-proxy.invalid-ip`

### Gateway follow-ups
- [x] Monitoring dashboards (Prometheus/Grafana) — *Phase 1, "Basic monitoring stack"*. Done 2026-10 (ADR-027): see "Execution intelligence and operations" item 2
- [x] Single-VM production deployment package — `deploy/` (ADR-019): Caddy TLS edge with Let's Encrypt as the only published service, gateway real-IP rate limits trusting only Caddy's fixed address, restart policies, `init-env.sh` strong secrets, daily `backup.sh` with restore verified, installation guide. Waiting on a VM + domain
- [x] Kubernetes ingress; real certificates — staging done 2026-10-22 (ADR-038): Gateway API edge (AKS Application Routing) and cert-manager with Let's Encrypt; first real deploy pending
  - [ ] AKS Stage 2: NetworkPolicies beyond the edge's (built 2026-10-23: ingress default deny, each Service open to its callers, checked on kind under Pod Security `restricted`; egress stays open, ADR-038), read-only root filesystem checked on the cluster, kube-prometheus-stack with QEOS's rules and the five dashboards, the Grafana proxy sidecar (header secret instead of IP trust), Container Insights
  - [ ] AKS Stage 3: production cluster, approval-gated deploy of `platform-v*`, restore drill proving 5 minutes of data loss and 1 hour to restore, the CI switch-over checklist
  - [ ] **User action:** create the two GitHub identities (build: AcrPush, master and per-release tag credentials; deploy: the cluster roles, `environment:staging` only; `deploy/azure/README.md` section 2, item 5), apply the GitHub environment branch policies (`staging`: master only; `production`: master and `platform-v*` tags; `deploy/azure/README.md` section 5.1), then run the first staging deploy and the checks in ADR-038 "Verify on the first real deploy"
- [x] Service-to-service auth so organization-service can check users in auth-service — auth-service gained `GET /internal/v1/users/{id}` (HTTP Basic, same INTERNAL_API_PASSWORD pattern as project-service's retention API); the superuser `AUTH_SERVICE_TOKEN` is gone from config, compose and docs
- [ ] Shared rate limits in Redis — *when more than one gateway instance runs*
- [ ] JWT validation and per-user limits at the gateway — *when the gateway should reject bad tokens itself*
- [ ] API docs through the gateway — *when a frontend or partner needs browsable docs*
- [ ] WebSockets / SSE — *Phase 3, real-time features*. Deferred by ADR-021: new runs reach the dashboard by polling every 30 s; push starts (SSE first, Redis fan-out) when the collector streams partial results
- [x] Run ingestion's PostgreSQL-only tests in CI (done 2026-10-20): the `ingestion-postgres` job in `ci.yml` starts a `postgres:16-alpine` service with a `qeos_test` database, points `QEOS_TEST_POSTGRES_URL` at it and runs `tests/integration/test_screenshots_postgres.py` (the screenshot `FOR KEY SHARE` lock and link savepoint, ADR-036) on every push. The job fails unless the pytest summary is "N passed" with nothing skipped, so a lost URL cannot turn it green
- [x] `scripts/smoke_gateway.sh` only runs against the stack its HTTP checks reach (done 2026-10-20). Its bare `docker compose exec/run/ps` calls reach the project named by `COMPOSE_PROJECT_NAME`, else `name: qeos`, so a smoke run aimed at a second stack used to sign tokens, run `psql` and the jobs inside the developer's running `qeos` stack and leave smoke users and keys there (found 2026-10-20). It now asks that project for its gateway's published ports (`docker compose port gateway 8443` and `8080`, the container ports since ADR-038) and stops with `FAIL` when the gateway is not running there or publishes other ports than `GATEWAY_HTTPS_PORT` and `GATEWAY_HTTP_PORT`

### Ingestion (Phase 2, step 1)
- [x] ingestion-service: project API keys, POST /collect/runs (validation, idempotency, truncation), run read API, Prometheus metrics
- [x] In the root stack and behind the gateway; smoke-tested end to end

### Ingestion follow-ups
- [x] Collector agent MVP (JUnit XML parser, uploader with retry) — `collector/`, see below
- [ ] Queue-based processing for 1000+ events/second — *Phase 2 exit criterion*
- [x] PII detection and redaction; retention policies — masking on ingest, `ingestion-retention` job
- [~] mTLS between agent and platform — collector side done (`--client-cert`/`--client-key`); server-side enforcement (nginx ssl_verify_client) is a deployment decision
- [~] Artifacts (screenshots, videos, traces, logs) — step screenshots shipped 2026-10-20 (ADR-036, collector 0.11.0); Playwright screenshots 2026-10-20 (collector 0.13.0); traces stage 1 (download) 2026-10-21 (ADR-037, collector 0.14.0, release pending); the trace viewer in the browser (stage 2: one-time links, self-hosted Playwright viewer) 2026-10-22; videos remain
- [x] Per-test history endpoints — analytics `tests/{test_key}/history`, dashboard History view
- [x] Revoke a project's API keys when the project is deleted — superseded by project deletion (ADR-034): keys stay during the 7 days (uploads answer 410, a restore brings them back) and are deleted by the purge
- [x] Project deletion (ADR-034, 2026-10-16) — Settings › Data, name typed to confirm, 7 days pending and restorable by owners and admins (greyed in the project list; members see a notice), then purged in test-management, ingestion and project-service in recorded, resumable steps
- [x] Re-mask results stored before masking existed — `python -m src.ingestion.jobs.remask [--dry-run] [--project ID]`: id-ordered committed batches, JSON summary, idempotent; text lengthened past 64 KB is cut back and flagged. Pilot data (9,853 results) checked: nothing to change
- [x] Custom masking patterns per project — project Settings → Masking: up to 20 RE2 patterns (linear time, no ReDoS; ADR-020), refused with a reason when invalid or matching empty text, named markers `[REDACTED:customer_id]`, a preview showing the sample exactly as it would be stored; applied at ingest and by the re-mask command, never across projects
- [x] Legal hold and data export before deletion. In Settings → Data, owners and admins can place
  or release a legal hold. The hold is stored in project-service columns with who, when and why.
  The retention list reports it, and the retention job deletes nothing of a held project; an
  answer without the field stops the pass. The same card downloads an NDJSON export of every
  run and result, streamed from ingestion and masked as stored. Verified live: the dry run
  reports `projects_held: 1`, and the export runs through the gateway.

### Collector agent (Phase 2, step 2)
- [x] `qeos-collector upload`: JUnit XML (pytest, Surefire, Playwright, cucumber-js), one run per CI job
- [x] GitHub Actions, GitLab CI and Jenkins detection; retry-safe Idempotency-Keys; parts past 20,000 results / 9 MB
- [x] Retries with backoff and a 2-minute budget; HTTPS and verified TLS; the key never printed
- [x] CI: tests on Python 3.9 and 3.12; end-to-end upload through the gateway in the smoke test
- [x] Tag `collector-v0.1.0` — release workflow builds+verifies on the tag
- [x] Dogfooding: this repository's CI reports its own results (four service suites, dashboard, collector on 3.9/3.12) through the collector built from the same commit; enabled by the QEOS_URL repository variable + QEOS_API_KEY secret, push and same-repo PRs only, never fails the build
- [ ] Phase 2 exit criteria: agents on 3 CI platforms in real projects; 10k test executions ingested

### Collect manual CI runs (ADR-030)
- [x] Server side (2026-10-12): `collection_settings` and `test_runs.trigger` (migration 019), `GET/PUT /projects/{id}/collection-settings`, a manual upload to a project that switched collection off answers 202 and stores nothing, gateway route
- [x] Collector 0.5.0: classify the run from the CI environment, `--trigger`, the 202 notice; tag `collector-v0.5.0`
- [x] Collector 0.5.1 (2026-10-12, final review): `--gate` on a discarded run decides on the local results; spooled and partial-run discard messages; tag `collector-v0.5.1`
- [x] Collector 0.5.2 (2026-10-13): collector-action installs from its own checkout (`$GITHUB_ACTION_PATH/../collector`); the old git URL came up empty inside reusable workflows ("empty revision"); CI now runs the action
- [ ] Collector 0.7.0: `impact` and `run-impact` (suggested tests first, Cucumber); the action's `impact` and `test-command` inputs, the Jenkins step's `impact` and `testCommand`; release and tag `collector-v0.7.0` (plan Tasks 21-22)
- [x] Dashboard (2026-10-12): the Collection card in Project Settings (switch, discard count)
- [x] Docs (2026-10-12): SETUP 4.1.8a and troubleshooting, collector and ingestion READMEs, PRODUCT, README

- [ ] Python 3.9 has been end-of-life since October 2025; the CI jobs that test it are pinned to ubuntu-24.04 (ubuntu-latest is 26.04, which has no 3.9) until 3.9 support is dropped, then remove the pin in ci.yml and release-collector.yml

### Collector — nice to have
Distribution
- [~] Publish to PyPI: workflow ready (trusted publishing, gated on repo variable PYPI_PUBLISH=true); needs the one-off publisher config on pypi.org (project qeos-collector, repo atriis/Atriis.QEOS, workflow release-collector.yml, environment pypi)
- [x] Ready-made GitHub Action (`uses: atriis/Atriis.QEOS/collector-action@collector-v0.1.0`) and GitLab CI template (`templates/qeos-collector.gitlab-ci.yml`) — both install the collector pinned to the tag
- [x] A Jenkins shared-library step — `collector-jenkins/vars/qeosCollectorUpload.groovy` (workspace venv install, PEP 668-safe; key via env only). Proven against a real Jenkins LTS in Docker: library loaded from a git repo via JCasC, pipeline build SUCCESS, run stored with ci_provider=jenkins and the build URL
- [x] Azure DevOps (collector 0.2.0). The collector detects Azure Pipelines (`TF_BUILD`):
  commit, branch (the source branch on PRs), PR number (the visible number for GitHub-hosted
  code), target branch and build URL (project names percent-encoded). A job retry is a new
  run.
  - Ingestion accepts `ci_provider=azure_pipelines` (migration 011).
  - Repositories accept Azure DevOps URLs (`dev.azure.com`, legacy `visualstudio.com`, SSH v3,
    and `org@` clone URLs), stored as owner `org/project`, project-service migration 003. They
    are verified through the anonymous REST API; a private project's 401/203 reads as
    "not found or private".
  - Step template `templates/qeos-collector.azure-pipelines.yml` and an Azure Pipelines CI
    snippet in Settings.
  - Verified live: an upload with an Azure PR environment was stored with every field, and a
    real public Azure repository was verified.
- [x] A Docker image and a single-file (zipapp) build for runners without pip — zipapp (`collector/scripts/build_zipapp.py`, stdlib-only, runs on any Python 3.9+) and `collector/Dockerfile` (python:3.12-slim + git). On every `collector-v*` tag the release workflow uploads sdist+wheel+pyz to a GitHub Release and pushes `ghcr.io/atriis/qeos-collector:<version>` + `:latest` (user-approved public surfaces, 2026-10-03)

Formats
- [x] Cucumber JSON (classic formatter) — scenarios map to the existing result shape (suite=feature, class=uri; background folds in; failed step fails, undefined/pending skip). Rich tags/steps columns still need ingestion fields — deferred until a consumer exists
- [x] Playwright JSON — own reporter format; retries kept as per-attempt results, projectName as suite, timedOut→failed, interrupted→errored. Attachments wait for artifact ingestion (below)
- [x] TestNG XML, NUnit 3 XML, xUnit.net v2 XML, .NET TRX — dispatched on the XML root element (`formats.py`); same result shape, formats mix freely in one upload

Richer data
- [x] Keep each retry attempt as its own result, so flaky tests become visible — Surefire flakyFailure/flakyError/rerunFailure/rerunError expand into per-attempt results (duplicate testcases, pytest-rerunfailures style, already passed through)
- [x] Git metadata: commit author and message (git log -1, best effort), PR number + base branch (GitHub/GitLab env), stored per run and shown on run detail
- [x] Code-change data, not just JUnit: changed files and diff stats per run — collector gitdiff module, ingestion migration 005 + run API, dashboard Changes card. Correlation analytics remain Phase 6 input.
- [x] Components under test: `--component NAME@SHA` (or `QEOS_COMPONENTS`) records which repo versions the run exercised (e.g. the product build an E2E suite ran against) — ingestion migration 008 + run API, "Under test" line on run detail. Dormant Phase 6 input; cross-repo correlation and Workspaces stay behind their triggers (ADR-018).
- [x] Test ownership from CODEOWNERS — collector matches each result's `file` (git semantics, last line wins; root/.github/docs locations), ingestion stores `owner` per result (migration 009), run detail shows it
- [~] Artifact upload (screenshots, videos, traces) — step screenshots from Cucumber JSON done (ADR-036, collector 0.11.0, off by default per project); Playwright JSON image attachments done (collector 0.13.0, spec 2026-10-20); traces stage 1 done 2026-10-21 (ADR-037: upload, download button, `keep_traces` off by default, collector 0.14.0 release pending); trace viewer (stage 2) done 2026-10-22 (one-time links, Playwright's viewer served at `/trace-viewer/`); videos not started
- [ ] Traces follow-ups (ADR-037, final review 2026-10-22): document a bucket lifecycle rule `AbortIncompleteMultipartUpload` for production storage (one line in docs/SETUP.md 4.12 done); `ArtifactOut.media_type` when videos land; collector: no key check when no trace is readable, dedupe traces by content before upload, retry on `SSLEOFError`, `--dry-run` reports the upload budget
- [ ] Step screenshots follow-ups (ADR-036): a separate, shorter retention for images if storage grows; traces stage 1 done (ADR-037), stage 2 viewer done 2026-10-22 (design `docs/superpowers/specs/2026-10-21-traces-and-videos-design.md`), videos later (its section 8). Done 2026-10-20: Playwright JSON image attachments (collector 0.13.0, spec `docs/superpowers/specs/2026-10-20-playwright-screenshots-design.md`); `no-screenshots: true` in `.qeos.yml` (collector 0.12.0); the `minio` scrape job and the "Screenshot storage used" and "Screenshots stored" panels on the Host and containers dashboard

Reliability and operations
- [x] Keep a failed upload on disk and retry it later — automatic via `--spool` (below); a separate `retry` command adds nothing, the next upload resends first
- [ ] Stream partial results during long runs — needs a long-running watch mode (the collector currently runs after the tests finish; multi-part uploads already flow sequentially). Revisit if a real pipeline shows the need
- [x] `qeos-collector check`: verifies URL shape, TLS trust, API key (GET /collect/key names the project) and report parsing, without uploading; exits 2 on the first failure
- [x] Keep-and-retry failed uploads: `--spool DIR` / `QEOS_SPOOL` stores undelivered parts (base64 JSON, capped at 100) and the next invocation resends them under their original Idempotency-Key; non-retryable rejections (401/409/4xx/TLS) are dropped, not respooled
- [x] A `.qeos.yml` config file — flat keys + string lists, built-in reader (zero dependencies kept for the zipapp); precedence flags > env > file; API key never accepted in the file
- [x] Client certificates (mTLS) — `--client-cert`/`--client-key` (`QEOS_CLIENT_CERT`/`QEOS_CLIENT_KEY`) load into the TLS context; server-side enforcement is a deployment concern (nginx `ssl_verify_client`), not in the local stack

### Microsoft SSO
- [x] Sign in with Microsoft (Entra ID) ID tokens from an allowlist of tenants; link to an existing account
- [x] Signing-key fetch hardened for Google and Microsoft (timeout, throttled refresh); outages answer 503
- [x] SSO-only mode (`AUTH_SSO_ONLY`, ADR-031): Microsoft sign-in only, active superusers keep a logged password break-glass, non-superuser sessions revoked once per switch, readiness and a one-time 7-day link allowance
- [ ] Personal Microsoft accounts (outlook.com)
- [x] Map Entra groups / app roles to organization roles (app roles, ADR-033, spec 2026-10-16; groups not planned)
- [x] A superuser approves each organization before its app-role mappings apply (ADR-033 amendment 2026-10-17: any user could otherwise pull Entra-assigned people into an organization they own)
- [ ] SCIM provisioning and deprovisioning (ends the sessions of people removed from Entra; today they last until the refresh token expires, ADR-031)
- [ ] Owner override for Entra-managed members (take over or remove at once; today removal waits for the person's next Microsoft sign-in)
- [ ] Entra app-role mappings scoped to a tenant id (today every allowed tenant can grant every mapped role)
- [ ] GitHub SSO
- [ ] Single sign-out
- [x] MFA for password accounts: TOTP enrollment (QR + otpauth URI), verification on login, recovery codes; SSO sign-ins defer MFA to the identity provider
- [ ] SAML 2.0 sign-in for enterprise IdPs that don't do OIDC (SP-initiated, signed assertions, per-organization IdP metadata); complements the existing Google/Microsoft ID-token flows

### Analytics API (Phase 3, step 1)
- [x] Daily trends in a requested time zone; per-test list, history; flaky detection (same commit + environment, flip rate)
- [x] Summary tables: flaky_daily rollups + analytics-rollup job; window raised to 90 days (90d: 3.9 s from rollups vs 11.3 s live; 14d: 0.8 s)
- [x] Weekly and monthly views — trends bucket=day|week|month (Monday weeks, local calendar), dashboard View select, window up to 365 days
- [x] Branch comparison — per-branch aggregates endpoint + Branches tab with two-branch pass-rate chart
- [x] Mute / acknowledge a flaky test — muted_tests table, mute/unmute endpoints, dashboard controls
- [x] CSV export — client-side, tests and flaky views (see Dashboard follow-ups)
- [x] Dashboard UI — login, project picker, trends, tests, history, flaky (`dashboard/`)
- [ ] Report regressions at size B is at p95 8.4 s against the 8 s target (README Report timing; accepted 2026-10-10, size A is the expected volume). When a real project's 90-day results near size B: first a per-request `SET LOCAL work_mem`, then the per-test daily rollup. The covering index the spec lists first did not pay at size B (experimental one dropped, README Report timing, task-20-perf-report.md "Why no covering index"); try it only if production shows a small window over a large mixed table.

### Dashboard follow-ups
- [ ] Speed up the slowest dashboard tests. `maxWorkers: 4` (vite.config.ts) cut timeouts on a loaded laptop from 9 to about 2, but some tests are close to the 15 s limit on their own: "at most 200 cases can be selected" (RunFromQeos.test.tsx, about 11 s alone, renders 260 cases over 4 pages) and the Report page's "announced only when every section asked has loaded"
- [x] SSO sign-in buttons (Google, Microsoft) in the login page — rendered only when `VITE_*` client ids are baked at build time; manual verification against a real tenant still pending
- [x] SSO-only mode in the dashboard (ADR-031): sign-in page from `/auth/methods` with an administrator disclosure, recovery pages point to sign-in, Security page Microsoft link card, superuser readiness card with the one-time link allowance
- [x] Refresh token in an httpOnly cookie — `qeos_refresh`, Secure, SameSite=Strict, Path=/api/v1/auth (ADR-013)
- [x] Mute / acknowledge flaky tests
- [x] CSV export buttons on the tests and flaky views (client-side; tests view pages the API at limit=200, capped at 10k rows)
- [x] Branch comparison — per-branch aggregates endpoint + Branches tab with two-branch pass-rate chart
- [x] Organization management UI — `/organizations/:orgId` (members list/remove, invite by email+role, pending invitations with revoke; controls gated on owner/admin via `GET /members/me`; the invite link with the single-use token is shown once, from the 201) and `/invitations/:token` accept page closing the self-service loop; Manage link per organization in the picker. Audit follow-ups landed: member rows carry emails (auth batch internal lookup, best effort), the accept page previews organization+role via authenticated `GET /invitations/{token}` (dead token = unknown token), per-row accessible action names, copy button on the invite link

- [x] Registration in the UI — /register page (full name optional, "check your email" state says where the link lands when SMTP is unconfigured), /verify-email SPA landing that verifies and signs the person in (the emailed link now points there instead of the raw API endpoint), Create account link on the login page
- [x] Dashboard redesign (2026-10-04, user decisions: sidebar navigation, overview as the project entry, nothing sacred) — design tokens (spacing scale, radius, two-step shadows, accent-text/accent-fill/danger-text with every text pair computed >= 4.5:1 in both themes), app shell with a sidebar (project switcher grouped by organization, project views with icons, workspace and account sections) that becomes an accessible drawer under 900px, an Overview page answering 'what is broken now' (latest run verdict in words, its failures, this week's pass rate and the flaky count, as the API computed them; a guided empty state), and a Projects page listing every organization's projects at once. Verified rendered: desktop light and dark, 390px, zero horizontal scroll
- [x] Keyboard and screen-reader navigation — skip link + <main> landmark (WCAG 2.4.1), per-view document titles e.g. "Runs · Shop E2E · QEOS" (2.4.2), focus moves to the new view's content on navigation (not on load or redirects). Destructive actions (revoke API key, remove member, revoke invitation) confirm in place: the confirm button takes focus, Escape/Cancel return it to the trigger
- [x] Error banner text in dark mode was 3.6:1 — new --danger-text token (#d03b3b light 4.6:1, #ec7272 dark 6.0:1); charts and status dots keep the validated status hue
- [x] CI wiring snippets in project Settings — ready-to-paste GitHub Action / GitLab include / Jenkins step / plain CLI, with this deployment's origin filled in and the key always referenced as a CI secret. Decision 2026-10-03: ingestion stays push-based; a "connect repository" (GitHub App, webhooks, artifact pull) would still require the repo's CI to produce JUnit XML, adds third-party credential custody, and locks to one forge — deferred to the Phase 4/6 slice below
- [x] Quality report (roadmap Phase 3, step 5). The project's **Report** view covers the last
  7/30/90 days: a summary (runs, executions, pass rate without skipped tests, failures), a
  weekly table, the most failing and slowest tests, flaky tests and branches. It is built on
  the existing analytics API, with tables rather than charts, so it reads and prints well.
  - **Save as PDF** prints through a print stylesheet: no app chrome, no page breaks inside rows.
  - **Download CSV** gives the per-test data behind the report.
  - Scheduled delivery (TODO 66) is done: the weekly summary below.
- [x] Weekly summary (TODO 66). Any notification channel (email, Slack, Teams, webhook) can get
  last ISO week's numbers every Monday from 07:00 UTC, alongside failed-run alerts or instead of
  them. It covers runs, executions, pass rate against the week before, failures, the five
  most-failing tests and a link to the Report.
  - A quiet week says "no runs", so a pipeline that stopped uploading is noticed.
  - The `weekly-summary` job sends once per channel per week (`last_weekly_week`, advisory lock).
  - "Send summary" in Settings sends it on demand.
  - Spec: `docs/superpowers/specs/2026-10-05-weekly-summary-design.md`. Verified against Mailpit:
    one email with the right numbers, and no resend after a restart.
- [x] Live runs (roadmap Phase 3, step 7, by polling: ADR-021). The first page of **Runs** and
  the **Overview** refresh every 30 s while the tab is visible. New runs get a short tint and a
  polite "N new runs" announcement; later pages never move under the reader. A new latest run
  also refreshes the Overview's weekly pass rate and flaky count.
- [x] Run filters and search (roadmap Phase 3, step 8). The **Runs** view filters by status
  (with failures / all green) and branch, and **More filters** adds environment, CI, commit
  prefix, pull request, author and a date range. Filters live in the URL, so a filtered view
  can be shared and survives back/forward. The Tests view already had name search.
  "From/to" are whole days in the viewer's time zone; the API takes instants.
- [x] Repositories in project Settings — attach the repository the tests live in by pasting a browser or clone URL (optional default branch, otherwise the provider's), status in words (Reachable / Not found or private / Not checked) with Check again, remove with an in-place confirm; viewers and billing managers read only. Rendered at 1280px and 375px
- [x] CI snippet on a localhost deployment — the CLI leads by default with the self-signed certificate step, and choosing GitHub or GitLab shows that their hosted runners cannot reach localhost (CLI, self-hosted runner with --ca-file, or a public deployment)
- [x] Wire up your CI: "What to add" switches between the upload step and the test-case sync; the GitHub sync is the standalone qeos-sync-cases.yml with the first_sync input, as SETUP 4.2.3 (2026-10-15)
- [x] collector-action `command: import-features` (collector 0.9.2): the GitHub sync goes through the action, which installs from its own checkout; pip from git+https fails on a runner while Atriis.QEOS is private (2026-10-15)
- [ ] GitHub App integration ("connect repository") — justified when cross-repo correlation starts (Phase 6 consumes product-repo commits via API; run_components/ADR-018 already capture the link). Scope then: app registration, webhook ingestion of commits/PRs for connected product repos, optional run discovery. Not an ingestion replacement
- [x] Create flows in the UI — "New organization" (slug derived from the name, editable, backend pattern enforced) and "New project" (owner/admin only) in the picker; Settings tab per project with API-key management (create shows the full key once with a copy button, list shows prefix/created/last-used, revoke; revoked keys lose the action). Closes the last curl-only step: a team can go from register to first upload entirely in the browser

### Phase 4: Test Management
51. [x] Design test case and test suite data models (spec `docs/superpowers/specs/2026-10-06-test-management-design.md`)
52. [~] Implement test case creation, versioning, and organization: creation, labels, priority, status and archive done; versioning open
53. [x] Create test execution tracking and result storage: run requests (Play and Stop, ADR-025) are tracked in test-management; results stay in ingestion and reach a case through its automated-test link
54. [x] Develop test suite management and execution ordering (static, ordered suites)
55. [~] Implement test case linking and dependencies: link to the automated test done; dependencies open
56. [x] Create API endpoints for test management (`platforms/test-management-service`)
57. [x] Implement integration with Project service (project roles, as ingestion)
58. [x] Write comprehensive test suite (42 tests: cases, suites, migration)
59. [x] Create API documentation (service README; OpenAPI at /api/v1/openapi.json)
60. [x] Add Docker support (image, compose service + migrate job, gateway route, CI tests and smoke)
61. [x] Integrate with Auth, Organization, and Project services (JWT + project roles)

### Phase 5: Analytics & Reporting
Delivered by ingestion-service's analytics API, the Report (ADR-026) and the dashboard; the
item-level record is "Analytics API (Phase 3, step 1)" and "Dashboard follow-ups" above.
62. [x] Design analytics data models and metrics collection (flaky_daily rollups, report indexes; `/metrics` on every service)
63. [x] Implement test execution analytics and trends
64. [x] Create defect analysis and reporting capabilities: failures by cause, run compare, the Report (failure causes, regressions, by area, coverage, duration)
65. [x] Develop dashboard and visualization framework (`dashboard/`)
66. [x] Implement scheduled report generation and delivery: weekly summary on notification channels (see below)
67. [x] Create API endpoints for analytics and reporting
68. [x] Implement integration with all previous services (project roles; the dashboard joins test-management's case areas)
69. [x] Write comprehensive test suite
70. [x] Create API documentation (`platforms/ingestion-service/README.md`)
71. [x] Add Docker support
72. [x] Integrate with all foundation services

### Execution intelligence and operations (agreed 2026-10-08, in this order)
Kubernetes stayed out until its blueprint trigger fired; it fired 2026-10-21 (AKS, ADR-038). Docker Compose on one VM remains a supported install.
1. [x] Suite duration prediction (done 2026-10-08): ingestion `POST /analytics/duration-estimate` (per-test p50 of passed runs, p90 of all, per-environment with fallback, project overhead + parallelism fitted on the last 20 runs); estimate in the Run dialog, live in the selection bar and on suite detail; stored on run requests (test-management migration 008) for "≈ n min left" and "estimated vs took". Later: warn when the estimate exceeds the workflow timeout
2. [x] Monitoring: Prometheus, Grafana and Alertmanager as an opt-in profile of the production compose; `/metrics` on every service, Postgres and container exporters, starter dashboards and alerts (service down, 5xx rate, disk). Done 2026-10: ADR-027, spec `docs/superpowers/specs/2026-10-10-monitoring-design.md`; blueprint §11 names, job heartbeats (ingestion migration 017), five dashboards, alerts to email/Slack/Teams, Grafana at `/grafana/` for superusers
3. [x] Customisable Overview (done 2026-10-11, ADR-028, spec `docs/superpowers/specs/2026-10-11-customisable-overview-design.md`): 14 widgets over the existing analytics and three templates (QA lead, Developer, Flaky hunt); a project default (owners/admins) and a personal layout per user with "reset to project default" (project-service migration 004, optimistic versions, 409 Reload/Overwrite); one widget catalogue file shared by validation and the dashboard registry (24 widgets, 64 KB); refresh on a new run driven by each widget's stale keys; test-management `GET /suites?created_by=me`
   - [ ] Follow-up (Phase 2 review, 2026-10-11): `DELETE /overview-layout/project` carries no version (spec §3.3), so one admin's stale "Reset to built-in default" removes another admin's newer default; give DELETE the same version check as PUT in a later spec revision
4. [x] Test impact analysis (done 2026-10-12, ADR-029, spec `docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md`): co-failure statistics on PostgreSQL rebuilt by the `impact-rollup` job (ingestion migration 018, heartbeat `impact_rollup`); each upload with changed files stores its suggestion before its results and its outcome after; `GET /runs/{id}/impact`, `POST /analytics/impact`, `GET /analytics/impact-accuracy`; the run page card, the Report's Test impact section, the Overview widget Impact accuracy (15 widgets now), and Run likely affected on Test cases; `--backfill-days` replays history
   - [ ] Follow-up: `impact_test_base.id` is a 32-bit serial rebuilt nightly; make it BigInteger or drop it for `(project_id, test_key)` before real scale.
   - [ ] Follow-up: tune the thresholds with real data. The random-failure benchmark suggested about 76 tests per change; watch `avg_suggested`.
   - [x] Release B, suggested tests first in CI (built 2026-10-13; spec `docs/superpowers/specs/2026-10-13-suggested-tests-first-design.md`, ADR-029 "Release B"):
     - `qeos-collector impact` (cucumber, list, json; exit 0/3/4, 2 on configuration) and `run-impact` (Cucumber: two stages, one run, `--fail-fast`, `--suggested-only`, `--no-fallback`, the step summary);
     - a scoring or setup problem always runs the whole command; only `--suggested-only --no-fallback` exits without tests;
     - run scope and stages (ingestion migration 020); subset runs out of the statistics, outcomes and accuracy;
     - `POST /collect/impact` with the per-key "test suggestions" permission (`can_read_impact`);
     - the action's `impact` and `test-command` inputs, the Jenkins step's `impact` and `testCommand`, GitLab and Azure examples.
   - [ ] Follow-up: run-impact formats beyond Cucumber, as small follow-ups: JUnit with Maven/Gradle (`-Dtest=`), pytest (node ids), Playwright/JS (`--grep` or file:line)
   - [ ] Follow-up: verify run-impact on a real cucumber-jvm project with Maven and with Gradle (system-property forwarding), and on Ruby Cucumber; those adapters follow their documented options and are unit-tested with recorded command lines, and only cucumber-js 12.6.0 was run for real
   - [ ] Mark suggested-only runs on the Overview's Latest run / Failing in latest run / Recent runs widgets
   - [ ] A learned model on the same features once outcomes accumulate; it must beat `stats-v1` on the catch rate (with the average suggestion size beside it), with no new infrastructure
   - [ ] Phase 6 embeddings: code embeddings and semantic similarity (Qdrant) when "Phase 6 AI engine work begins"
   - [ ] The accuracy figure in the weekly summary
   - [ ] A repository prefix for path units once runs record their repository (the collector sends it; spec §3.1)
   - [ ] A narrow layout for Report tables (Report-wide: the Test impact misses table is one of several that overflow at phone width)
- [ ] Report origin marker (ADR-026 fallback): a Play workflow input → collector field → ingestion `test_runs.origin` column and a backfill. Only if the URL match proves unreliable.
- [ ] My recent failures by email (ADR-028 follow-up): the collector records the commit author's email (`git log --format=%ae`), ingestion stores it (column and migration), and the widget matches the signed-in user's email instead of a name
- [ ] The project export includes the Overview project default (ADR-028, spec §3.4): needs project-service data in the export, which today holds ingestion data only

### Phase 6: AI Engine (Original Starting Point)
73. [ ] Design AI/ML model architecture for test analysis
74. [ ] Implement test failure pattern recognition
75. [ ] Create intelligent test case generation suggestions
76. [ ] Develop risk-based test prioritization algorithms
77. [ ] Implement predictive analytics for test outcomes
78. [ ] Create natural language processing for test requirements
79. [ ] Develop anomaly detection in test execution patterns
80. [ ] Design model training and retraining pipelines
81. [ ] Create API endpoints for AI-powered insights
82. [ ] Implement integration with Test Management and Analytics services
83. [ ] Write comprehensive test suite
84. [ ] Create API documentation
85. [ ] Add Docker support
86. [ ] Integrate with all platform services

## Next Version (v2) — Backlog

Not scheduled. These move QEOS from *observing* test runs (the roadmap's scope: a
collector reports results from the customer's own CI) to also *authoring and running*
them. Items marked *(suggested)* were added during review as natural companions to the
requested ones. Each group needs its own design spec before implementation.

### A. Test case management
- [x] Friendly UI to browse, create and edit test cases (TCs): **Test cases** view (list, filters, editor with ordered steps, read-only for viewers)
- [x] Create/add labels on TCs; filter and search by label
- [x] Create suites — static (hand-picked TCs), ordered, edited in place
- [x] Link a TC to the automated test that implements it; the case shows that test's latest result
- [x] Repository suites (2026-10-19, ADR-035): sync of the CI suite workflows' matrix legs into Suites (read-only), Add to suite, "Not in any suite" filter, sync warnings, `--suites` in collector 0.10.0; stage 2: Run and Run all through the repository's own workflows, one active run per workflow, busy and repository checks (spec `docs/superpowers/specs/2026-10-19-repository-suites-design.md`). Open: the end-to-end run, after the OBT PR (atriis/Atriis.Test.Automation.OBT#563) is merged, which waits for QEOS running this version and collector 0.10.0 tagged
- [ ] Last result per suite on the Suites list (passed, failed, not run, from its cases' latest results) *(follow-up of repository suites)*
- [ ] Copy a repository suite into an editable QEOS suite *(follow-up of repository suites)*
- [ ] Per-workflow busy check reads only the newest 100 runs of the workflow, and the dashboard gate reads only the newest 50 requests; page further if a busier history shows a miss *(follow-up of repository suites)*
- [ ] Quiet window before the nightly: refuse or warn when a QEOS run of a repository suite could still be running at the scheduler's time *(follow-up of repository suites)*
- [ ] Repository suites, smaller follow-ups (final review 2026-10-19 judged none blocking):
  - Run requests: the dashboard polls full `selection` lists while a run is active; a repository "Run all" can make each poll large. Add a summary-only list or a smaller page
  - Busy check: a GitHub 401/403/404 shows as "GitHub could not be asked … try again"; name the token problem instead. Commit the read transaction before asking GitHub. Remove the unused `active_request(workflow=None)` fallback
  - PUT /ci-target: refuse a workflow change while a run of the CI target's workflow is active
  - OBT reruns: a blank `run_id` can still pick a partial manual run (suites set, no request_id) as "the latest run"; GitHub's run list does not show inputs
  - Sync: suites cut at 1000 cases show the rest under "Not in any suite"; name claims on clashes depend on processing order; a concurrent delete can answer 500 instead of `import_conflict`; NULL `scenario_line` sorts differently on SQLite and PostgreSQL; a literal `[` in a path is read as a glob
  - Collector: check the 20-pattern / 200-character limits locally; print "Suites: no changes" when nothing changed
  - Dashboard: the `repository_mismatch` notice stays until the page remounts; the long mismatch reason repeats on every row; the Add to suite status should use a persistent live region; group order is alphabetical
  - Tests to add: repository-workflow index race, rollback when the suite apply fails, another project's case number on append, a CI-target run blocking a manual suite, glob `*` across `/`, invalid matrix JSON and a missing `include`
  - Code tidy: shared case-number checks in `suite_service`, `MAX_SUITE_CASES` placement, duplicate-id check order in the parser
  - Docs: ADR-035 in the full ADR template; split this item's long done line; SETUP "own slot" qualifier when the Settings workflow is also a suite workflow
- [ ] Test isolation: auth-service calls `load_dotenv()`, which finds the repository root `.env`, so a local `MONITORING_ENABLED=true` fails three monitoring-off tests on a developer machine (CI has no `.env`). Load only an explicit path, or clear the variable in the test fixture
- [ ] Dynamic suites defined by a label query, e.g. `smoke AND checkout` *(suggested)*
- [ ] TC versioning: who changed what, and when *(suggested)*
- [x] Import existing TCs from the repo (Gherkin `.feature` files, JUnit XML) *(suggested)* (Gherkin done 2026-10-06, ADR-023; JUnit still open)
- [x] qeos-collector import-features: CI keeps cases in sync; API-key access to test-management; refuse a full import that would archive over half the imported cases without --allow-mass-archive (2026-10-06, ADR-024)
- [x] Dashboard 'complete features folder' option (full=true): archives cases of missing files, keeps renamed files' numbers; the confirm button names the archive count (2026-10-06)
- [x] Case filters: folder dropdown with the tree, feature, Azure DevOps item, link and latest-result filters on All Cases (`/cases/search`, `/case-folders`, `/case-features`, `latest-keys`), the searchable `FilterSelect`, gateway route and smoke checks (2026-10-06)
- [x] Failed step on scenarios (spec `docs/superpowers/specs/2026-10-13-failed-step-and-feature-layout-design.md`): server part done 2026-10-13 (ingestion migration 021, `failed_step` in the result payload, `POST /analytics/latest-results`); collector 0.6.0 sends `failed_step`; dashboard shows the red failed step, tooltip, last-result pill and "Failed in Background" on scenario and feature-page cards (done 2026-10-13)
- [x] Skipped scenarios mark the step they stopped at (2026-10-15): collector 0.9.1 sends the first step that did not pass (undefined/pending/ambiguous/hook-skipped) as `failed_step` with the reason as `message` (0.9.3: the step's text attachment, whole, else the status); `latest-results` returns it for skipped rows that have one; the scenario and feature pages mark it in Skipped Yellow with the word "skipped", the dashed-circle icon and the same tooltip ("Skipped in Background" on a card)
- [x] Failed steps across test cases (spec `docs/superpowers/specs/2026-10-14-failed-steps-across-cases-design.md`, plan `docs/superpowers/plans/2026-10-14-failed-steps-across-cases.md`): phase 1 server (migration 022, `failed_step.definition`/`pattern` stored masked, unknown `failed_step` fields ignored); phase 2 collector 0.8.0 (released: tag `collector-v0.8.0`, `collector-v0` follows; container image pending the release-workflow permission fix); phase 3 `GET /projects/{id}/runs/{run_id}/failed-steps`, the run page's Failed steps section, the failed-step tooltip line ("Also failed in N other test cases in this run · failing since run #430") linking to it; "failing since" counts runs on the run's branch only. Done: phase 3 dashboard: Failed steps on the run page, tooltip line (2026-10-14). Deferred follow-ups: the collector 0.8.0 container image arrives with the next release; error-shape refinements (the JUnit `expected:<...>` form, apostrophes inside quoted values); "failing for more than 90 days" can read too long when the tests did not run between the window and the oldest failing run (needs the latest pre-window row per test).
- [x] Last runs column: run-strip endpoint, RunStrip component with one-link design and shape cues, Cases column with skeleton and error states, legend, DESIGN.md and TODO docs (2026-10-06)
- [x] Test cases by Feature (dashboard): Group by Feature | Scenario on the Cases list (`group`), feature rows expanding in place with tri-state selection and an "n failing" count, Search in Feature/Scenario/Both (`search_in`), the Feature page with the raw file, line numbers, case chips and Run feature (rebuilt from the cases until re-import), case titles at 500 (2026-10-08)
- [ ] Bound latest-keys (window over full history) — time-bound or DISTINCT ON when projects get large (suggested). Note: `latest-results` / `_latest_ranked` also carry `message` and `details` through the window; when bounding, rank on `RunResult.id` only and join the text columns back
- [x] Dashboard major upgrades as coordinated sets (2026-10-08: Vite 8 + plugin-react 6 + vitest 5 + msw 3, React 19.3, ESLint 10 + typescript-eslint 8.71 + react-hooks 7 classic rules, TypeScript 6.0.3; TypeScript 7 held back by Dependabot until typescript-eslint supports it). Open: react-hooks' React Compiler rules (33 findings: render-time ref reads, setState in effects) and eslint-plugin-react-refresh (13 mixed-export files) are not enabled yet
- [x] SQLAlchemy 2.1: switch the services to psycopg 3 (or explicit `postgresql+psycopg2://` URLs) and lift the Dependabot ignore. 2.1 makes `postgresql://` default to psycopg 3, which broke CI on 2026-10-07 (pinned back to 2.0.54). Done 2026-10-08: all five services on SQLAlchemy 2.1.4 + `psycopg[binary]` 3.3.6 (psycopg2 removed, plain `postgresql://` URLs kept), shared on `>=2.1,<2.2`, Dependabot ignore lifted
- [ ] Link TCs to requirements/tickets (Azure DevOps, Jira) *(suggested)*
- [ ] Bulk actions: label, move, archive many TCs at once *(suggested)*

### B. Test execution
- [x] Run a single TC, a selection ("bunch"), or a whole suite (v1 Play and Stop, 2026-10-07; spec `docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md`)
- [ ] Re-run only the failures from a previous run
- [x] First version triggers the customer's CI (GitHub Actions `workflow_dispatch`) rather than running tests on QEOS's own infrastructure *(suggested — far smaller security surface than executing customer code)* (v1 Play and Stop, 2026-10-07; spec `docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md`)
- [ ] Live run progress and cancel a running job (see `specs/2026-07-13-qa-vision-realtime-features.md`) *(suggested)* (cancel done in v1 as Stop; live step progress is out of scope)
- [ ] Pause and Resume a running job (cucumber `BeforeStep` hook asks QEOS whether to continue; screenshot on pause; time limit; fails open if QEOS is unreachable)
- [ ] Stop followed by a resuming re-run, plus "Re-run failures" of a finished run
- [ ] A GitHub App instead of the personal token (short-lived installation tokens owned by no single person)
- [ ] Run parameters (target environment, browser/device matrix), scheduled runs (nightly, per branch) and more CI providers (GitLab, Azure Pipelines) for runs from QEOS *(suggested)*
- [ ] A dedicated `execution-service` once execution outgrows test-management
- [ ] Team run queue (requested 2026-10-13): many people press Play; requests wait in a per-project queue instead of being refused by the one-active-run rule, with position, who started each, cancel-your-own, and fair ordering *(v2)*
- [ ] Local execution through a QEOS runner (requested 2026-10-13): a small agent on a machine the team controls (a laptop, a test server, a lab PC) takes requests from the queue, runs the tests with the team's own environment and secrets, and uploads results with the collector. QEOS servers still never run customer code (ADR-025 kept, like a GitHub self-hosted runner). Open questions for the design: personal runners (only my own requests) vs shared team runners vs both; runner registration and token; labels to route a request to a runner (OS, browser, environment); heartbeats and a stuck-run timeout; Stop on a local run. Probably together with the dedicated `execution-service` above *(v2)*
- [x] Flaky-test quarantine. Quarantining a test (Flaky view, the former Mute) keeps it running and
  shown, but its failures stop counting:
  - a run failing only in quarantine reads "Passed · N quarantined";
  - failure alerts skip such runs, and otherwise mention "N quarantined, not counted";
  - the upload receipt carries `quarantined`/`blocking`, and `qeos-collector upload --gate` exits 1
    on failures outside quarantine (and fails closed when the upload did not happen).
  The run page and the failure groups mark quarantined tests. An auto-retry policy stays with the
  test runner (Playwright `retries`, pytest-rerunfailures); the platform already keeps every attempt.

### C. Results, history and evidence
- [x] Log values (ADR-032): a project's patterns pick values (a trip id, a route) out of each result's masked log; they show on every Last runs bar's tooltip, on the test case page and on the feature page's scenario cards, copyable and optionally linked. Spec: `docs/superpowers/specs/2026-10-14-log-values-design.md`.
- [x] Search runs by a log value: `value`/`pattern` on the runs list and the run page, a Log value filter on Runs, a "runs" link on every value chip (spec `docs/superpowers/specs/2026-10-15-log-values-follow-ups-design.md`).
- [x] Show a result's whole log: on demand on the run page, the case page and the feature cards, values marked, copy and download (same spec).
- [ ] TC run history (pass/fail/duration over time) — already planned in roadmap Phases 2–3
- [~] View screenshots and screen recordings attached to a run — screenshots done (camera button on Gherkin steps and run results, ADR-036); recordings not started
- [~] Playwright trace viewer and step-by-step logs per failed TC *(suggested)* — trace download done (ADR-037, stage 1); the viewer in the browser done 2026-10-22 (stage 2)
- [x] Compare two runs side by side. `/projects/{id}/runs/{run}/compare/{base}` sorts each test
  into new failures, fixed, still failing, slower, added and removed. The run page links to a
  comparison with the previous run on its branch, and any run number can be typed in instead.
- [x] Causes over time: each cause on the run page shows whether it is new in this run, how many
  runs in a row it has failed (since #N), and how often it appeared in the last 20 runs of the
  branch. The Overview marks new causes.
- [x] Group failures by error signature, so one broken locator shows as one problem, not forty. The first error line, with numbers, ids and hashes ignored (`analytics/signature.py`), groups a run's failures: `GET /api/v1/runs/{id}/failure-groups`; the run page shows **Failures by cause**, the Overview lists causes instead of tests
- [ ] Shareable link to a failed run *(suggested)*
- [x] Failure notifications to Slack/Teams/email. Slack, Microsoft Teams (Workflows webhook,
  Adaptive Card), generic https webhooks and email (one to five addresses) are done. Channels live in Settings → Notifications:
  - per-branch filter, a test button, and the last delivery shown in words;
  - delivery is a background task after the upload, one attempt, outcome recorded;
  - an SSRF guard (vendor hosts, public addresses only, checked again at send time, no
    redirects), and URLs are never returned.

  Spec: `docs/superpowers/specs/2026-10-05-failure-notifications-design.md`. Email goes through
  `qeos_shared.mail`, shared with auth. Compose now passes `SMTP_*` to auth and ingestion: before,
  the documented SMTP settings reached no container. Verified with a local Mailpit sink: the
  verification email, a test message and a failed-run message were all delivered. Roadmap
  Phase 3, step 4.

### D. AI prompt chat
- [ ] Create TCs from a prompt
- [ ] Fix failing TCs from a prompt
- [ ] Every AI change is delivered as a pull request or a reviewable diff, never committed directly *(suggested — keeps a human in the loop)*
- [ ] Explain a failure from its logs and screenshots *(suggested)*
- [ ] Turn manual TC steps into an automated test *(suggested)*
- [ ] Ask questions about test data in plain language ("which tests failed most this week?") — roadmap Phase 6 *(suggested)*
- Note: the roadmap defers "natural language test generation" past year one because predictive ML needs months of collected data. An assistant built on a hosted LLM does not depend on that data, so this group can be scheduled independently of Phase 6.

### D2. AI skills: reusable Markdown playbooks for the AI engine
Requested 2026-10-07. Users create or import `*.md` files as **skills**: reusable instructions the AI follows for one job, such as a custom report, generating test cases in the team's style, analysing a failure or a release-readiness check. Depends on group D, because a skill needs an AI assistant to run it.
- [ ] **Skill format.** Markdown with YAML frontmatter: `name`, `description` (when to use it), `inputs` (for example a run, a suite or a date range), `output` (report, test cases or analysis) and `version`. Keep it compatible with the Agent Skills `SKILL.md` layout so existing skills import as they are. v1 is Markdown only: no bundled scripts and no executable content.
- [ ] **Create, import, edit and export** (`.md`, or a `.zip` with reference files), with a preview and a dry run against sample data before saving.
- [ ] **Scopes:** user (private), team, organization, and built-in skills shipped by QEOS.
  - Resolution order: user, then team, then organization, then built-in. A name clash shows which one wins.
  - **Teams don't exist yet**: sub-teams are not built (TODO 31). Until they are, team scope maps to project.
- [ ] **Governance:**
  - Only owners and admins publish organization skills.
  - Every change is versioned (who, when, a diff), and a skill can be rolled back.
  - Usage is counted, and unused skills are flagged.
- [ ] **Security** (a skill is a prompt, so it is untrusted input):
  - A skill never widens access. The AI sees only the data and tools the *calling user's* role allows, and PII masking still applies.
  - A skill cannot carry secrets or URLs the AI would call.
  - Size limit, and a scan on import for instructions to exfiltrate data.
  - Outputs that change state, such as new test cases or fixes, arrive as drafts or PRs for a human to approve (group D rule).
- [ ] **Run a skill** from the AI chat ("/release-readiness for run 433"), from a run, case or suite page ("Analyse with…"), or on a schedule. A scheduled custom report goes through the existing notification channels.
- [ ] **Starter skills:** failure triage for a run, flaky-test report, Gherkin test cases from a requirement, weekly quality summary and release readiness.
- [ ] **Later:**
  - share skills across organizations through the marketplace (the `marketplace/` prototype);
  - skill evaluations, where a skill's output is checked against expected examples before publishing.

### E. Repository configuration and secrets
- [ ] Edit configuration files (`*.json`) — restricted to a configured config path only
- [ ] Validate edits against a JSON schema and show a diff before saving; save as a PR *(suggested)*
- [ ] Manage the repo's environment variables (the GitHub `.env`)
- [ ] Store them as GitHub Actions secrets/variables through the GitHub API rather than committing a `.env` file; values write-only and masked in the UI *(suggested — a committed `.env` leaks its secrets to everyone with read access)*
- [ ] Per-environment profiles (dev / staging / prod) *(suggested)*
- [ ] Audit log of every config and secret change *(suggested)*

### F. UX
- [ ] Onboarding wizard: connect a repository, install the collector, first run *(suggested)*
- [x] Global search: the Ctrl K command palette covers test cases, tests, runs (by number or exact branch), pages and projects (layout phase 3)
- [x] Search suites from the palette, and runs by partial branch name, with case-key search and a run summary read for "#N" (`branch_contains`, `/runs/{id}/summary`, suites `search`)
- [x] Personal dashboard: my suites, my recent failures — the My suites and My recent failures Overview widgets (2026-10-11, ADR-028)

### G. Built-in terminal
A terminal in the browser (xterm.js over a WebSocket). An interactive shell is remote code
execution by design, so this ships in three levels, each its own spec, and each level only
after the one before it is proven:
- [ ] **Level 1 — live output console (read-only):** stream a run's stdout/stderr as it happens, with ANSI colours, search, and download. No input. Low risk; reuses the run/job infrastructure from group B
- [ ] **Level 2 — command console (allow-listed):** a terminal-style prompt that only accepts platform commands (`run suite smoke`, `rerun failed`, `git status`, `show config`), each mapped to an API call and bound by the same per-action permissions as the UI. No arbitrary shell
- [ ] **Level 3 — full interactive shell:** a real PTY inside an ephemeral, per-user sandbox container (repo checked out, test toolchain installed), destroyed at session end. Requires: container isolation (gVisor/Firecracker class, no host mounts, no Docker socket), egress restrictions, CPU/memory/time limits, idle timeout, no platform secrets inside the sandbox, session recording to the audit log, and an explicit per-organization opt-in
- Note: Level 3 means running customer code on QEOS's own infrastructure — the exact surface group B's `workflow_dispatch` approach avoids. Build it only if Levels 1–2 leave a real gap.

### H. Platform prerequisites for v2
These are not features, but groups B, C, D, E and G cannot ship without them:
- [x] Frontend application (React/TypeScript, per the roadmap tech stack): `dashboard/`
- [ ] GitHub App integration — scoped repo access, workflow dispatch, secrets API — instead of personal access tokens
- [~] Artifact storage for screenshots, videos and traces (S3-compatible; MinIO for local development) — MinIO on compose and production, screenshots (ADR-036) and traces (ADR-037); videos reuse it
- [ ] Job queue for runs and AI requests (Redis is not in the stack: it waits on its blueprint trigger)
- [ ] Secrets management (Vault or cloud equivalent) — brought forward from "prepare for" to required
- [ ] Permissions per action: who may run tests, edit config, manage secrets, accept AI changes

## Completed Documentation (Reference)
All architectural specifications and design documents from the initial brainstorming phase have been completed and serve as the foundation for implementation phases.

## Current Status
Updated 2026-10-12. Phases 1–3 are delivered, test management (Phase 4) is in use, and the Report,
notifications, Run from QEOS and the single-VM production package have shipped. Monitoring has
shipped (item 2 under "Execution intelligence and operations", ADR-027), and so has the customisable
Overview (item 3, ADR-028) and test impact analysis (item 4, ADR-029). What runs today: README.md and
TECHNICAL_SPECIFICATION.md; next steps: IMPLEMENTATION_PLAN.md §2.
