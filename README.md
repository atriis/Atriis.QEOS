# QEOS

**Quality Engineering OS** — one place for a team's automated test results, test cases and test
runs: CI uploads results, QEOS shows trends, flaky tests, failure causes and regressions, keeps the
test-case catalogue in sync with your Gherkin features, and starts runs in your own CI.

The target architecture is [`ARCHITECTURE_BLUEPRINT_V1_0.md`](ARCHITECTURE_BLUEPRINT_V1_0.md) (its
banner says what is built and what waits for an adoption trigger); the item-level record is
[`TODO.md`](TODO.md).

## What it does today

- **Accounts and access** — email/password with verification, password reset and change, MFA
  (TOTP), Google and Microsoft (Entra ID, tenant allowlist) sign-in; organisations with
  owner / admin / member / viewer roles and invitations; projects with repositories and settings.
- **CI results** — the [`qeos-collector`](collector/README.md) uploads JUnit/Cucumber results from
  any CI (GitHub Action in [`collector-action/`](collector-action/action.yml), Jenkins library in
  [`collector-jenkins/`](collector-jenkins/README.md)) with a per-project API key; secrets and
  personal data in failure messages are masked before storage.
- **Analytics** — runs, tests and their history, trends (daily/weekly/monthly), branches, run
  comparison, flaky tests (same-commit detection, quarantine) on daily rollups.
- **Report** — a filterable, printable report per period: summary with deltas, failure causes
  (new / recurring / resolved), regressions and instability (flips), results by feature, folder,
  label or suite, coverage (never-run cases, tests without a case) and duration; CSV export.
- **Test cases** — a case catalogue with suites, a Feature view grouped by `.feature` file, Gherkin
  import from the browser and sync from the repository's default branch, links to automated tests.
- **Run from QEOS** — start a selection, a case or a suite in your GitHub Actions workflow, with a
  duration estimate before, during and after the run.
- **Operations** — Slack, Teams and email notifications (failed runs, weekly summary), data
  retention and legal hold, full export, `/metrics` in Prometheus format on every service, with job heartbeats for the
  background jobs (the opt-in monitoring stack — Prometheus, Alertmanager, Grafana, which superusers open from the
  account menu's **Monitoring** item — is being added; see
  [`docs/superpowers/specs/2026-10-10-monitoring-design.md`](docs/superpowers/specs/2026-10-10-monitoring-design.md)).

## What runs

| Component | Path | Role |
|---|---|---|
| Gateway | [`gateway/`](gateway/README.md) | NGINX: TLS, routing, rate limits, serves the dashboard |
| Dashboard | `dashboard/` | React 19 + TypeScript single-page app |
| auth-service | `platforms/auth-service/auth-service/` | Users, sign-in, tokens, SSO, MFA |
| organization-service | `platforms/organization-service/` | Organisations, members, invitations |
| project-service | `platforms/project-service/` | Projects, repositories, settings |
| ingestion-service | [`platforms/ingestion-service/`](platforms/ingestion-service/README.md) | Uploads, runs, analytics, report; jobs: retention, rollup, weekly summary |
| test-management-service | [`platforms/test-management-service/`](platforms/test-management-service/README.md) | Test cases, suites, Gherkin import/sync, run requests |
| PostgreSQL 15 | — | One server, one database per service |
| `shared/` | `shared/qeos_shared/` | Settings, DB session, mail and metrics helpers used by every service |

Services are Python 3.11 / FastAPI / SQLAlchemy / Alembic and never call each other for page data:
the dashboard joins (ADR-022). Decisions are recorded in
[`docs/architecture/adr/`](docs/architecture/adr/INDEX.md).

`execution/`, `automation/`, `marketplace/`, `collaboration/`, `intelligence/` and
`platforms/qip-service` are unwired prototypes: not in compose, CI or the gateway.

## Run it locally

```bash
cp .env.example .env            # then set SECRET_KEY and INTERNAL_API_PASSWORD (long random values)
docker compose up -d --build --wait gateway
curl -k https://localhost:8443/health          # {"status":"healthy"}
```

Open `https://localhost:8443` (self-signed certificate). Databases are created and migrated on
every `up`. Stop with `docker compose down`; wipe data with `docker compose down --volumes`.

**Complete setup guide** — every `.env` variable, first account and roles, MFA, SSO, email, then
each feature with what to configure (CI uploads, test cases and Gherkin sync, Run from QEOS,
analytics, notifications, masking, retention), wiring a real repository, upgrades and
troubleshooting: [`docs/SETUP.md`](docs/SETUP.md).

**Production on one VM** — the same stack behind a Caddy TLS edge with Let's Encrypt, generated
secrets and daily backups: [`deploy/README.md`](deploy/README.md).

## Tests

| What | Command |
|---|---|
| A Python service | `cd platforms/<service> && SECRET_KEY=test .venv/Scripts/python -m pytest -q` (auth: `platforms/auth-service/auth-service`) |
| Shared package | `cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests -q` |
| Dashboard | `cd dashboard && npm run lint && npm run typecheck && npx vitest run && npm run build` |
| Whole stack (Docker) | `bash scripts/smoke_gateway.sh` after `docker compose up` |

CI (`.github/workflows/ci.yml`) runs every service suite, the dashboard checks, container smoke
tests and the full-stack gateway smoke on each push.

## Security notes

Passwords hashed with bcrypt; short-lived JWT access tokens and rotating, revocable refresh tokens
in an httpOnly cookie; MFA; SSO ID tokens verified against the providers' keys; rate limits at the
gateway (sign-in endpoints stricter); per-project API keys for uploads; masking of secrets and
personal data in stored results; `/metrics` and internal endpoints are never routed publicly.
Access tokens are not revocable before they expire. See [`SECURITY.md`](SECURITY.md).

## License

MIT, as stated since the first commit; the LICENSE file itself is not in the repository yet.
