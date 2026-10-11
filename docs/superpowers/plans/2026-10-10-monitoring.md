# Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Phases.** P1 (metrics everywhere), P2 (the stack), P3 (Grafana and the sign-in gate) each ship on their own. The last task of each phase is a gate: every suite, the CI-mirroring steps, then the user pushes.

**Goal:** Whoever operates a QEOS install learns that it is down or unhealthy before its users do and can see why: every service exposes Prometheus metrics, an opt-in `monitoring` compose profile runs Prometheus, Alertmanager, Grafana and three exporters, alerts reach email, Slack or Teams, and QEOS superusers open Grafana at `/grafana/` behind the QEOS sign-in.

**Architecture:**
- **`shared/qeos_shared/metrics.py`** gives every service one call, `install_metrics(app, service=..., registry=None)`: a pure ASGI middleware that counts and times each request by its matched route template, `GET /metrics`, the process collector and `build_info`. Names follow blueprint §11.2 (no `qeos_` prefix).
- **ingestion-service** passes its existing registry (the `qav_*` metrics stay), adds `test_executions_total{status}`, migration **017** `job_heartbeats`, a heartbeat upsert after every pass of the three loop jobs, and a custom collector that turns the heartbeat rows into `job_last_success_timestamp_seconds{job}` / `job_last_error_timestamp_seconds{job}` at scrape time, surviving a database failure.
- **test-management-service** adds `test_case_creation_total{type}`.
- **`monitoring/`** holds the Prometheus config, recording and alert rules with promtool unit tests, the Alertmanager template and its POSIX-sh renderer, Grafana provisioning and five dashboards, and `monitoring/check.sh`, which runs every static check in containers (locally and in CI).
- **`docker-compose.yml`** gains profile `monitoring` (six containers, pinned tags, memory limits); `scripts/postgres-init.sh` creates role `qeos_monitor` on every `up`.
- **The sign-in gate:** auth-service adds `monitoring_url` to `/users/me`, `POST /api/v1/auth/grafana-session` (sets the `qeos_grafana` cookie, `Path=/grafana`, 8 h), `GET /internal/v1/grafana-check` (NGINX `auth_request`), and logout clears the cookie. The gateway's `/grafana/` location runs `auth_request`, overwrites `X-QEOS-User-Email`, and answers 404 when monitoring is off. The dashboard gets a **Monitoring** item in the account menu and a `/monitoring` hand-off page.

**Tech Stack:** FastAPI 0.142, Starlette, prometheus-client 0.26.0, SQLAlchemy 2.1, Alembic 1.20, PyJWT 2.15, pytest 9 (SQLite in tests). Prometheus v3.5.0, Alertmanager v0.28.1, Grafana 12.0.2, node-exporter v1.9.1, cAdvisor v0.54.1 (not v0.52.1: it finds no container under Docker's containerd image store), postgres-exporter v0.17.1, PostgreSQL 15, NGINX 1.27 (`auth_request`). React 19, TypeScript 6, TanStack Query 5, vitest + msw + Testing Library, lucide-react.

**Spec:** `docs/superpowers/specs/2026-10-10-monitoring-design.md`, as amended 2026-10-10 to make blueprint §11 (`ARCHITECTURE_BLUEPRINT_V1_0.md`) binding: metric names and labels from §11.2, the process collector, two business metrics, recording rules for the blueprint's PostgreSQL names, and the list of what stays TARGET. Executors read the spec with this plan. Where this plan decides something the spec left open or got wrong against the code, the decision is under **Rulings** and repeated in the task.

## Global Constraints

Every task implicitly includes all of these.

- **Metric names and labels (blueprint §11.2, no `qeos_` prefix):**
  - Counter `api_requests_total{service, endpoint, method, status_code}`.
  - Histogram `http_requests_duration_seconds{service, endpoint, method}` (the blueprint spells it with "requests"); buckets `0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30` seconds.
  - Gauge `http_requests_in_flight{service}`.
  - Gauge `build_info{service, version, commit}`, always 1.
  - `endpoint` is the matched route template (e.g. `/api/v1/projects/{project_id}/cases/{number}`), never the raw path; a request matching no route is `endpoint="unmatched"`. `status_code` is the exact code as a string. `/metrics` and `/health` are not counted.
  - Each service's registry also registers prometheus_client's `ProcessCollector` (`process_cpu_seconds_total`, `process_resident_memory_bytes`, `process_open_fds`).
  - Ingestion: `test_executions_total{status}` per stored result, `status` one of `passed`, `failed`, `errored`, `skipped`, all four pre-created. Test-management: `test_case_creation_total{type}`, `type="manual"` for cases a person creates through the UI/API, `type="api"` for Gherkin import and sync, both pre-created. `"generated"` waits for the AI engine.
  - Job heartbeats: `job_last_success_timestamp_seconds{job}`, `job_last_error_timestamp_seconds{job}`, `job_heartbeat_read_errors_total`.
  - The existing ingestion metrics `qav_ingest_runs_total`, `qav_ingest_results_total`, `qav_ingest_rejected_total{reason}`, `qav_ingest_duration_seconds`, `qav_ingest_redactions_total{kind}` stay unchanged.
  - Prometheus recording rules publish `postgresql_database_size_bytes{datname}` (from `pg_database_size_bytes`) and `postgresql_connections{state}` (from `pg_stat_activity_count`); dashboards and alerts use these names.
- **No metric carries a user, organisation, project, test or case identifier. No secrets in metrics, logs, heartbeat error texts or rendered files that leave the container.**
- **Services run one uvicorn worker.** More workers need prometheus_client's multi-process mode; `metrics.py`'s docstring says so.
- **`/metrics` stays inside the Docker network.** The gateway keeps not routing it (the smoke check pins that the public `/metrics` is the SPA).
- **Monitoring is opt-in.** With `COMPOSE_PROFILES` unset, no monitoring container starts, the gateway answers `/grafana/` with 404, `monitoring_url` is `null`, and nothing in `.env` is required that was not required before.
- **Images pinned to exact tags; Alertmanager ≥ 0.28 (for `msteamsv2_configs`).** Memory limits: prometheus 512 MB, alertmanager 64 MB, grafana 256 MB, node-exporter 64 MB, cadvisor 128 MB, postgres-exporter 64 MB. Every monitoring container: internal network only (Grafana additionally `127.0.0.1:3000` for break-glass), a healthcheck, `restart: unless-stopped`.
- **Alert thresholds** exactly as spec §5 (with Ruling 6 for the weekly-summary job). Delivery: group by `alertname`, `service`; `group_wait` 30 s; `repeat_interval` 4 h; critical to every configured channel; warning to Slack and Teams (email only if it is the only channel); inhibition as §5; an unset channel is left out of the rendered file.
- **Sign-in gate:** cookie `qeos_grafana`, httpOnly, Secure, SameSite=Strict, `Path=/grafana`, 8 hours, JWT with audience `grafana`. Only active superusers; a demotion or deactivation cuts access on the next request. The gateway always overwrites `X-QEOS-User-Email`.
- **What stays TARGET (ADR-027 and blueprint §11 list it, each gated by a trigger):** Kubernetes service discovery and Prometheus federation (Kubernetes trigger); downsampling and the 3-month / 3-year retention; Loki logs with JSON logs carrying `traceId`; OpenTelemetry tracing; the `role` label on `api_requests_total` (needs a per-request role lookup); metrics for components that do not exist yet (Kafka, MongoDB, Redis, Elasticsearch, workflows, knowledge).
- **Dashboard:** invoke the `ui-ux-pro-max` skill before editing any `.tsx` or `.css` file. Colours from `index.css` tokens only, lucide icons with `aria-hidden`, no `any`.
- **Commands:**
  - Python, one service: `cd platforms/<svc> && SECRET_KEY=test .venv/Scripts/python -m pytest -q` (auth: `platforms/auth-service/auth-service`). One file: append its path. Every service has a `.venv`.
  - Shared package: `cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests -q`.
  - Pytest runs **serially per service** (each suite shares `./test.db` in its service directory): never run two suites of the same service at once.
  - Dashboard: `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build`.
  - Monitoring static checks: `bash monitoring/check.sh` (needs Docker).
- **Git:** work on `master`; never push (the user pushes after the phase gate). Another session may be editing `collector/`, `docs/SETUP.md` and dashboard files: re-read a shared file right before editing it, and commit only your own paths: `git add <paths> && git commit -m "<msg>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- <paths>`. Never `git add -A`.

## Rulings

Decisions where the spec is silent or wrong against the code. Each is repeated in its task.

1. **The internal check's path is `GET /internal/v1/grafana-check`.** auth-service mounts its internal router at `/internal/v1` (`src/auth/api/main.py`), not under `/api/v1`; `/api/v1/internal/...` would also fall under the gateway's public `/api/` prefix rules.
2. **The internal check uses no HTTP Basic.** Every other internal endpoint does, but the NGINX subrequest carries only the browser's headers; giving the gateway `INTERNAL_API_PASSWORD` would widen that secret. The `qeos_grafana` cookie is itself the credential, the endpoint only says who that cookie's own user is, and the gateway never routes `/internal/`.
3. **"Profile off → 404" needs the gateway to know.** `auth_request` cannot answer 404, and an unauthenticated visitor would be redirected before Grafana's absence showed. The gateway reads `MONITORING_ENABLED` (the same `.env` value auth-service reads); `entrypoint.sh` includes `grafana-on.conf` or `grafana-off.conf`. Off: `/grafana/` is the JSON 404 for everyone. On: Grafana is still resolved at request time, so the gateway starts when the grafana container is down (it answers 502).
4. **A 401 on `/grafana/` redirects to the dashboard's `/monitoring?next=<path>`, not straight to `/login`.** Signing in alone does not mint the Grafana cookie. `/monitoring` is a signed-in page (so a signed-out visitor goes through `/login?next=/monitoring...` first) that calls `POST /auth/grafana-session` and then opens `next` when it starts with `/grafana/`, else `/grafana/`. NGINX cannot URL-encode, so `next` is `$uri` (path only): a deep link's query string is dropped. Because the cookie is SameSite=Strict, a link to Grafana from Slack or an email always takes this path once.
5. **The heartbeat label `job` collides with Prometheus's own `job` target label** (it would arrive as `exported_job`). The ingestion scrape job sets `honor_labels: true`; nothing else ingestion exposes carries `job` or `instance`, so its other series keep `job="ingestion"` and `up{job="ingestion"}` is unaffected.
6. **JobStale for `weekly_summary` is 1 hour, not 8 days.** The spec's rule is "2× the job's interval"; its 8-day figure assumed a weekly pass, but the job passes every 30 minutes (`DEFAULT_INTERVAL_MINUTES = 30.0`) and records success on each one. Retention (24 h) → 2 d and rollup (6 h) → 12 h match the code.
7. **The heartbeat collector always emits the three known jobs**, with 0 when a job has no row yet or a timestamp is null. A job that has never succeeded therefore counts as stale (JobStale), and an error with no success fires JobFailing.
8. **A pass skipped because another copy holds the advisory lock writes no heartbeat**; the copy that runs writes it.
9. **`POSTGRES_DB_SIZE_ALERT_GB` reaches the rules through a rendered recording rule.** Prometheus rule files cannot read the environment. `monitoring/prometheus/entrypoint.sh` writes `/tmp/thresholds.yml` with `postgresql_database_size_alert_bytes = GB × 1e9` before starting Prometheus; the promtool tests use a committed copy at 20 GB.
10. **"Slowest statements" needs `pg_stat_statements`.** PostgreSQL always starts with `shared_preload_libraries=pg_stat_statements` (one PostgreSQL restart on the upgrade that brings this; nothing else changes for installs without monitoring). `postgres-init.sh` creates the extension in the `postgres` database together with the role.
11. **Email alerts need `SMTP_HOST` as well as `ALERT_EMAIL_TO`.** With only `ALERT_EMAIL_TO`, the renderer leaves email out and logs a warning (it would otherwise fail at the first alert).
12. **`Watchdog` routes to a `null` receiver**; the external dead-man's switch stays documented, not built.
13. **Grafana Live is off (`GF_LIVE_MAX_CONNECTIONS=0`).** The gateway location does not carry WebSockets; dashboards refresh by polling.
14. **`build_info`'s version and commit come from `QEOS_VERSION` and `QEOS_COMMIT`** (defaults `dev` and `unknown`), passed through compose; `deploy/README.md` shows `QEOS_COMMIT=$(git rev-parse --short HEAD)` on update.
15. **`method` is bounded:** anything outside `GET POST PUT PATCH DELETE HEAD OPTIONS` is `method="other"`, so a scanner cannot create series through the method either.
16. **Volume keys follow the compose file's convention:** `qeos_prometheus_data`, `qeos_grafana_data` (no explicit `name:`; they are new).
17. **Grafana and postgres-exporter refuse to start without their passwords** through a one-line shell guard in their entrypoint. `${VAR:?}` is not usable: compose interpolates the whole file even with the profile off, which would break installs without monitoring.
18. **node-exporter mounts `/:/host:ro` without `rslave`**, which Docker Desktop rejects; disk metrics of mounts added after start need a restart of node-exporter.
19. **Alertmanager keeps silences only until it restarts** (no volume; the spec lists two volumes).
20. **`test_case_creation_total{type="api"}`** counts the cases an applied import creates (`summary["created"]`), whether a person or CI sends it; dry runs count nothing. `type="manual"` counts `POST /cases`.
21. **`ProcessCollector` reads `/proc`:** it exposes nothing on Windows, so tests assert the process series only on Linux (CI).
22. **Image tags** are versions published well before today: `prom/prometheus:v3.5.0`, `prom/alertmanager:v0.28.1`, `grafana/grafana:12.0.2`, `prom/node-exporter:v1.9.1`, `gcr.io/cadvisor/cadvisor:v0.54.1` (v0.52.1 finds no container under Docker's containerd image store, Docker Desktop's default), `quay.io/prometheuscommunity/postgres-exporter:v0.17.1`. Task 11 checks each with `docker manifest inspect` before use.

## Review Focus

Inputs the spec implies but does not test, most likely to bite first. Each has a test in the owning task.

1. **Scanner traffic:** random paths and made-up HTTP methods must not create new series (`endpoint="unmatched"`, `method="other"`). Task 1.
2. **A heartbeat error carrying a connection string** (`postgresql://user:secret@db/...`, multi-line tracebacks): the stored text must hold no password, one line, ≤ 500 characters. Task 4.
3. **A Grafana cookie used as an API bearer token, or an access token planted as the Grafana cookie:** both rejected. Tasks 15 and 16.
4. **A client sending its own `X-QEOS-User-Email`:** Grafana must see the cookie owner's email, never the client's. Task 19 (smoke).
5. **Alert channel secrets containing YAML-special characters** (`'`, `:`, `#`): the rendered Alertmanager file stays valid and the value verbatim. Task 9.

---

## File map

**shared** — Create `shared/qeos_shared/metrics.py`, `shared/tests/test_metrics.py`. Modify `shared/pyproject.toml`, `shared/README.md`.

**auth-service** (`platforms/auth-service/auth-service/`) — Create `src/auth/utils/grafana_session.py`, `tests/integration/test_metrics.py`, `tests/integration/test_grafana_session.py`, `tests/integration/test_grafana_check.py`. Modify `requirements.txt`, `src/auth/api/main.py`, `src/auth/config.py`, `src/auth/schemas/user.py`, `src/auth/api/v1/endpoints/users.py`, `src/auth/api/v1/endpoints/auth.py`, `src/auth/api/v1/endpoints/internal.py`.

**organization-service, project-service** — Create `tests/integration/test_metrics.py`. Modify `requirements.txt`, `src/<pkg>/api/main.py`.

**test-management-service** — Create `src/casebook/utils/metrics.py`, `tests/integration/test_metrics.py`. Modify `requirements.txt`, `src/casebook/api/main.py`, `src/casebook/api/v1/endpoints/cases.py`, `src/casebook/api/v1/endpoints/case_import.py`.

**ingestion-service** (`platforms/ingestion-service/`) — Create `alembic/versions/017_job_heartbeats.py`, `src/ingestion/models/job_heartbeat.py`, `src/ingestion/jobs/heartbeat.py`, `src/ingestion/utils/job_metrics.py`, `tests/unit/test_heartbeat.py`, `tests/integration/test_job_heartbeats.py`, `tests/integration/test_heartbeat_metrics.py`. Modify `src/ingestion/utils/metrics.py`, `src/ingestion/api/main.py`, `src/ingestion/api/v1/endpoints/collect.py`, `src/ingestion/models/__init__.py`, `src/ingestion/jobs/retention.py`, `src/ingestion/jobs/rollup.py`, `src/ingestion/jobs/weekly_summary.py`, `tests/conftest.py`, `tests/unit/test_migration.py`, `tests/integration/test_health_and_metrics.py`.

**monitoring/** — Create `check.sh`; `prometheus/{prometheus.yml,recording.yml,alerts.yml,entrypoint.sh}`, `prometheus/tests/{alerts.test.yml,thresholds.yml}`; `alertmanager/{alertmanager.yml.template,render.sh,test_render.sh}`; `grafana/provisioning/datasources/prometheus.yml`, `grafana/provisioning/dashboards/qeos.yml`, `grafana/dashboards/{overview,service-detail,jobs-uploads,postgresql,host-containers}.json`, `grafana/check_dashboards.py`.

**Stack and docs** — Modify `docker-compose.yml`, `deploy/docker-compose.prod.yml`, `deploy/init-env.sh`, `deploy/README.md`, `.env.example`, `scripts/postgres-init.sh`, `scripts/smoke_gateway.sh`, `.github/workflows/ci.yml`, `gateway/nginx.conf.template`, `gateway/entrypoint.sh`, `gateway/Dockerfile`, `docs/SETUP.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md`, `TODO.md`, `docs/architecture/adr/INDEX.md`. Create `gateway/grafana-on.conf`, `gateway/grafana-off.conf`, `docs/architecture/adr/ADR-027-monitoring-profile.md`.

**dashboard** — Create `src/lib/browser.ts`, `src/pages/MonitoringPage.tsx`, `src/pages/MonitoringPage.test.tsx`, `src/components/UserMenu.test.tsx`. Modify `src/api/auth.ts`, `src/components/UserMenu.tsx`, `src/App.tsx`, `src/pageHeadings.test.tsx`.

---

# Phase 1 — Metrics everywhere

Useful by itself: any Prometheus can scrape QEOS after this phase.

### Task 1: `qeos_shared.metrics` and `install_metrics`

**Files:**
- Create: `shared/qeos_shared/metrics.py`
- Create: `shared/tests/test_metrics.py`
- Modify: `shared/pyproject.toml` (dependencies)
- Modify: `shared/README.md` ("What's here")
- Modify: `platforms/organization-service/requirements.txt` (so the shared suite's venv has prometheus-client)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `install_metrics(app: FastAPI, service: str, registry: Optional[CollectorRegistry] = None, *, version: Optional[str] = None, commit: Optional[str] = None) -> CollectorRegistry` — adds the middleware, `GET /metrics` (not in the OpenAPI schema), registers `ProcessCollector` and sets `build_info`; returns the registry used (a new one when `registry` is None).
  - `route_template(app, scope) -> str` and constants `BUCKETS`, `NOT_COUNTED = {"/metrics", "/health"}`, `UNMATCHED = "unmatched"`, `METHODS`.
  - Metric names: `api_requests_total`, `http_requests_duration_seconds`, `http_requests_in_flight`, `build_info`.

- [ ] **Step 1: Add the dependency and install it**

In `shared/pyproject.toml`, replace the `dependencies` list with:

```toml
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.2",
    "sqlalchemy>=2.1,<2.2",
    # qeos_shared.metrics; each service pins the exact version in its requirements.txt
    "prometheus-client>=0.20",
]
```

In `platforms/organization-service/requirements.txt`, add after `respx==0.23.1`:

```
prometheus-client==0.26.0
```

Run: `cd platforms/organization-service && .venv/Scripts/python -m pip install -r requirements.txt`
Expected: ends with `Successfully installed ... prometheus-client-0.26.0` (or "Requirement already satisfied").

- [ ] **Step 2: Write the failing tests**

Create `shared/tests/test_metrics.py`:

```python
"""qeos_shared.metrics: one call gives a service request metrics named after blueprint §11.2."""
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, Counter, generate_latest

from qeos_shared.metrics import install_metrics

CASE = "/api/v1/projects/{project_id}/cases/{number}"


def make_app(registry=None, **kwargs):
    app = FastAPI()
    holder = {}

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.get(CASE)
    def case(project_id: int, number: int):
        return {"ok": True}

    @app.post("/api/v1/items")
    def create():
        raise HTTPException(status_code=409, detail="taken")

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    @app.get("/inflight")
    def inflight():
        return {"value": holder["registry"].get_sample_value("http_requests_in_flight", {"service": "svc"})}

    kwargs.setdefault("version", "1.2.3")
    kwargs.setdefault("commit", "abc1234")
    holder["registry"] = install_metrics(app, service="svc", registry=registry, **kwargs)
    return app, holder["registry"]


@pytest.fixture
def svc():
    app, registry = make_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, registry


def requests(registry, **labels):
    return registry.get_sample_value("api_requests_total", {"service": "svc", **labels}) or 0.0


def test_the_endpoint_label_is_the_route_template_never_the_raw_path(svc):
    client, registry = svc
    assert client.get("/api/v1/projects/7/cases/3").status_code == 200
    assert requests(registry, method="GET", endpoint=CASE, status_code="200") == 1
    assert "/projects/7" not in generate_latest(registry).decode()


def test_a_path_that_matches_no_route_is_unmatched(svc):
    client, registry = svc
    client.get("/wp-login.php")
    client.get("/api/v1/does-not-exist/12345")
    assert requests(registry, method="GET", endpoint="unmatched", status_code="404") == 2
    text = generate_latest(registry).decode()
    assert "wp-login" not in text and "12345" not in text


def test_the_status_code_is_the_exact_code(svc):
    client, registry = svc
    assert client.post("/api/v1/items").status_code == 409
    assert requests(registry, method="POST", endpoint="/api/v1/items", status_code="409") == 1


def test_a_known_route_with_the_wrong_method_keeps_its_template(svc):
    client, registry = svc
    assert client.get("/api/v1/items").status_code == 405
    assert requests(registry, method="GET", endpoint="/api/v1/items", status_code="405") == 1


def test_an_unknown_method_is_counted_as_other(svc):
    """Review Focus 1: a scanner's made-up methods must not create series."""
    client, registry = svc
    client.request("BREW", "/api/v1/items")
    assert requests(registry, method="other", endpoint="/api/v1/items", status_code="405") == 1
    assert 'method="BREW"' not in generate_latest(registry).decode()


def test_an_unhandled_exception_counts_as_500(svc):
    client, registry = svc
    assert client.get("/boom").status_code == 500
    assert requests(registry, method="GET", endpoint="/boom", status_code="500") == 1


def test_health_and_metrics_are_not_counted(svc):
    client, registry = svc
    client.get("/health")
    client.get("/metrics")
    text = generate_latest(registry).decode()
    assert 'endpoint="/health"' not in text and 'endpoint="/metrics"' not in text


def test_the_in_flight_gauge_counts_the_request_and_returns_to_zero(svc):
    client, registry = svc
    assert client.get("/inflight").json() == {"value": 1.0}
    assert registry.get_sample_value("http_requests_in_flight", {"service": "svc"}) == 0.0


def test_durations_are_observed_per_template(svc):
    client, registry = svc
    client.get("/api/v1/projects/7/cases/3")
    labels = {"service": "svc", "method": "GET", "endpoint": CASE}
    assert registry.get_sample_value("http_requests_duration_seconds_count", labels) == 1
    assert registry.get_sample_value("http_requests_duration_seconds_bucket", {**labels, "le": "30.0"}) == 1
    assert registry.get_sample_value("http_requests_duration_seconds_bucket", {**labels, "le": "0.01"}) is not None


def test_build_info_is_one_with_version_and_commit(svc):
    _, registry = svc
    assert registry.get_sample_value("build_info", {"service": "svc", "version": "1.2.3", "commit": "abc1234"}) == 1


def test_build_info_falls_back_to_the_environment_then_defaults(monkeypatch):
    monkeypatch.setenv("QEOS_VERSION", "0.4.0")
    monkeypatch.setenv("QEOS_COMMIT", "7802daf")
    _, registry = make_app(version=None, commit=None)
    assert registry.get_sample_value("build_info", {"service": "svc", "version": "0.4.0", "commit": "7802daf"}) == 1
    monkeypatch.delenv("QEOS_VERSION")
    monkeypatch.delenv("QEOS_COMMIT")
    _, registry = make_app(version=None, commit=None)
    assert registry.get_sample_value("build_info", {"service": "svc", "version": "dev", "commit": "unknown"}) == 1


def test_metrics_endpoint_serves_prometheus_text(svc):
    client, _ = svc
    client.get("/api/v1/projects/7/cases/3")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "api_requests_total" in response.text


def test_metrics_is_not_in_the_openapi_schema(svc):
    client, _ = svc
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


def test_a_given_registry_is_used_and_keeps_its_own_metrics():
    registry = CollectorRegistry()
    Counter("qav_ingest_runs", "Test runs stored", registry=registry).inc()
    app, used = make_app(registry=registry)
    assert used is registry
    with TestClient(app) as client:
        text = client.get("/metrics").text
    assert "qav_ingest_runs_total 1.0" in text and "build_info" in text


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ProcessCollector reads /proc (Ruling 21)")
def test_process_metrics_are_exposed(svc):
    client, _ = svc
    text = client.get("/metrics").text
    for name in ("process_cpu_seconds_total", "process_resident_memory_bytes", "process_open_fds"):
        assert name in text
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests/test_metrics.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'qeos_shared.metrics'`.

- [ ] **Step 4: Write the module**

Create `shared/qeos_shared/metrics.py`:

```python
"""Prometheus metrics for every QEOS service: one call, `install_metrics(app, service="project")`.

It adds a middleware that counts and times each request, `GET /metrics` serving the service's
registry, prometheus_client's process collector and `build_info`. Names and labels follow the
architecture blueprint §11.2 (spec docs/superpowers/specs/2026-10-10-monitoring-design.md §3):

    api_requests_total{service, endpoint, method, status_code}
    http_requests_duration_seconds{service, endpoint, method}
    http_requests_in_flight{service}
    build_info{service, version, commit}   always 1

`endpoint` is the matched route template, never the raw path, and a request matching no route is
"unmatched"; an HTTP method outside METHODS is "other". So no label ever carries a user,
organisation, project, test or case identifier, and a scanner cannot create series. /metrics and
/health are not counted.

/metrics is served inside the Docker network only: the gateway does not route it (its catch-all
serves the dashboard SPA).

One uvicorn worker per service is assumed. With several workers each process keeps its own
counters and a scrape sees only one of them: switch to prometheus_client's multi-process mode
(PROMETHEUS_MULTIPROC_DIR) before adding workers.
"""
import os
import time
from typing import Optional

from fastapi import FastAPI
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ProcessCollector,
    generate_latest,
)
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Up to 30 s, so report calls near the 20 s statement timeout stay visible
BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0)
NOT_COUNTED = frozenset({"/metrics", "/health"})
UNMATCHED = "unmatched"
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


class _Metrics:
    def __init__(self, registry: CollectorRegistry, service: str, version: str, commit: str) -> None:
        self.service = service
        self.requests = Counter(
            "api_requests", "HTTP requests handled", ["service", "endpoint", "method", "status_code"],
            registry=registry,
        )
        self.duration = Histogram(
            "http_requests_duration_seconds", "Time to handle an HTTP request", ["service", "endpoint", "method"],
            buckets=BUCKETS, registry=registry,
        )
        self.in_flight = Gauge("http_requests_in_flight", "HTTP requests being handled", ["service"], registry=registry)
        build_info = Gauge("build_info", "Always 1; the labels say what is deployed", ["service", "version", "commit"],
                           registry=registry)
        build_info.labels(service, version, commit).set(1)
        self.in_flight.labels(service)  # visible at 0 before the first request


def _template(route) -> str:
    return getattr(route, "path_format", None) or getattr(route, "path", None) or UNMATCHED


def route_template(app: FastAPI, scope: Scope) -> str:
    """The template of the route that will handle this request; a known path with the wrong method
    (405) keeps its template, anything else is "unmatched"."""
    partial = None
    for route in app.router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return _template(route)
        if match == Match.PARTIAL and partial is None:
            partial = route
    return _template(partial) if partial is not None else UNMATCHED


class MetricsMiddleware:
    """Pure ASGI (no BaseHTTPMiddleware), so streaming responses and background tasks are untouched."""

    def __init__(self, app: ASGIApp, metrics: _Metrics, fastapi_app: FastAPI) -> None:
        self.app = app
        self.metrics = metrics
        self.fastapi_app = fastapi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in NOT_COUNTED:
            await self.app(scope, receive, send)
            return
        service = self.metrics.service
        endpoint = route_template(self.fastapi_app, scope)
        method = scope["method"] if scope["method"] in METHODS else "other"
        status_code = 500  # an exception before the response starts becomes ServerErrorMiddleware's 500

        async def send_and_record_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        in_flight = self.metrics.in_flight.labels(service)
        in_flight.inc()
        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_and_record_status)
        finally:
            in_flight.dec()
            self.metrics.duration.labels(service, endpoint, method).observe(time.perf_counter() - started)
            self.metrics.requests.labels(service, endpoint, method, str(status_code)).inc()


def install_metrics(
    app: FastAPI,
    service: str,
    registry: Optional[CollectorRegistry] = None,
    *,
    version: Optional[str] = None,
    commit: Optional[str] = None,
) -> CollectorRegistry:
    """Instrument `app` and serve `GET /metrics` from `registry` (a new one when None; ingestion passes
    its own so its qav_* metrics stay on the same page). Call once per app, at import time."""
    registry = registry if registry is not None else CollectorRegistry()
    ProcessCollector(registry=registry)
    metrics = _Metrics(
        registry,
        service,
        version or os.environ.get("QEOS_VERSION") or "dev",
        commit or os.environ.get("QEOS_COMMIT") or "unknown",
    )
    app.add_middleware(MetricsMiddleware, metrics=metrics, fastapi_app=app)

    def metrics_endpoint() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)
    return registry
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests -q`
Expected: all pass (the process test is skipped on Windows), including the existing config/db/keys/mail tests.

- [ ] **Step 6: Document it**

In `shared/README.md`, add to the "What's here" list:

```markdown
- `install_metrics(app, service="...", registry=None)` (`qeos_shared.metrics`) — request metrics named
  after blueprint §11.2 (`api_requests_total`, `http_requests_duration_seconds`,
  `http_requests_in_flight`, `build_info`), the process collector, and `GET /metrics`. Labels carry the
  route template, never the raw path. One uvicorn worker is assumed (see the module docstring).
```

- [ ] **Step 7: Commit**

```bash
git add shared/qeos_shared/metrics.py shared/tests/test_metrics.py shared/pyproject.toml shared/README.md platforms/organization-service/requirements.txt
git commit -m "feat(shared): install_metrics gives every service blueprint-named request metrics and /metrics" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- shared/qeos_shared/metrics.py shared/tests/test_metrics.py shared/pyproject.toml shared/README.md platforms/organization-service/requirements.txt
```

---

### Task 2: Wire `install_metrics` into auth, organization, project and test-management

**Files:**
- Modify: `platforms/auth-service/auth-service/requirements.txt`, `platforms/project-service/requirements.txt`, `platforms/test-management-service/requirements.txt`
- Modify: `platforms/auth-service/auth-service/src/auth/api/main.py`
- Modify: `platforms/organization-service/src/organization/api/main.py`
- Modify: `platforms/project-service/src/project/api/main.py`
- Modify: `platforms/test-management-service/src/casebook/api/main.py`
- Create: `platforms/test-management-service/src/casebook/utils/metrics.py`
- Modify: `platforms/test-management-service/src/casebook/api/v1/endpoints/cases.py`, `.../case_import.py`
- Create: `tests/integration/test_metrics.py` in each of the four services

**Interfaces:**
- Consumes: `install_metrics(app, service, registry=None)` from Task 1.
- Produces: `/metrics` on each service with `service` = `auth`, `organization`, `project`, `test-management` (Prometheus scrape job names in Task 8 use the same strings). Test-management: `src.casebook.utils.metrics.REGISTRY`, `CASES_CREATED` (`test_case_creation_total{type}`).

- [ ] **Step 1: Pin and install prometheus-client in the three remaining venvs**

Add `prometheus-client==0.26.0` after the `respx==0.23.1` line in `platforms/project-service/requirements.txt` and `platforms/test-management-service/requirements.txt`, and after `httpx==0.28.1` in `platforms/auth-service/auth-service/requirements.txt`. Then:

```bash
cd platforms/auth-service/auth-service && .venv/Scripts/python -m pip install -r requirements.txt
cd platforms/project-service && .venv/Scripts/python -m pip install -r requirements.txt
cd platforms/test-management-service && .venv/Scripts/python -m pip install -r requirements.txt
```
Expected: each ends with prometheus-client installed or already satisfied.

- [ ] **Step 2: Write the failing tests**

Create `platforms/organization-service/tests/integration/test_metrics.py`:

```python
def test_metrics_answer_and_count_requests_by_template(client):
    client.get("/api/v1/no-such-route/42")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "api_requests_total" in response.text
    assert 'service="organization"' in response.text
    assert 'endpoint="unmatched"' in response.text
    assert 'build_info{service="organization"' in response.text
```

Create `platforms/project-service/tests/integration/test_metrics.py`:

```python
def test_metrics_answer_and_count_requests_by_template(client):
    client.get("/api/v1/no-such-route/42")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "api_requests_total" in response.text
    assert 'service="project"' in response.text
    assert 'endpoint="unmatched"' in response.text
    assert 'build_info{service="project"' in response.text
```

Create `platforms/auth-service/auth-service/tests/integration/test_metrics.py`:

```python
def test_metrics_answer_and_count_requests_by_template(client):
    client.get("/api/v1/no-such-route/42")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "api_requests_total" in response.text
    assert 'service="auth"' in response.text
    assert 'endpoint="unmatched"' in response.text
    assert 'build_info{service="auth"' in response.text
```

Create `platforms/test-management-service/tests/integration/test_metrics.py`:

```python
import pytest

from src.casebook.utils import metrics

CASES = "/api/v1/projects/1/cases"
IMPORT = "/api/v1/projects/1/cases/import"
FEATURE = "Feature: A\n  Scenario: one\n    Given x\n  Scenario: two\n    Given y\n"


@pytest.fixture
def member(project_role):
    project_role("member")


def created(kind):
    return metrics.REGISTRY.get_sample_value("test_case_creation_total", {"type": kind}) or 0.0


def test_metrics_answer_and_count_requests_by_template(client):
    client.get("/api/v1/no-such-route/42")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "api_requests_total" in response.text
    assert 'service="test-management"' in response.text
    assert 'endpoint="unmatched"' in response.text


def test_both_case_creation_series_exist_before_any_case(client):
    text = client.get("/metrics").text
    assert 'test_case_creation_total{type="manual"}' in text
    assert 'test_case_creation_total{type="api"}' in text


def test_a_case_created_by_a_person_counts_as_manual(client, auth, member):
    before = created("manual")
    assert client.post(CASES, json={"title": "Pays with a stored card"}, headers=auth()).status_code == 201
    assert created("manual") == before + 1


def test_an_applied_import_counts_its_created_cases_as_api_and_a_dry_run_counts_nothing(client, auth, member):
    before = created("api")
    body = {"files": [{"path": "a.feature", "content": FEATURE}]}
    assert client.post(f"{IMPORT}?dry_run=true", json=body, headers=auth()).status_code == 200
    assert created("api") == before
    assert client.post(IMPORT, json=body, headers=auth()).status_code == 200
    assert created("api") == before + 2
```

- [ ] **Step 3: Run them to see them fail**

Run, one service at a time:
```bash
cd platforms/organization-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_metrics.py -q
cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_metrics.py -q
cd platforms/auth-service/auth-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_metrics.py -q
cd platforms/test-management-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_metrics.py -q
```
Expected: the first three FAIL (`/metrics` answers the 404 JSON, `assert 404 == 200`); test-management fails at import (`No module named 'src.casebook.utils.metrics'`).

- [ ] **Step 4: Wire the four apps**

`platforms/organization-service/src/organization/api/main.py` — add the import and, after `app.include_router(api_router, prefix=settings.API_V1_STR)`, the call:

```python
from qeos_shared.metrics import install_metrics
```
```python
install_metrics(app, service="organization")
```

`platforms/project-service/src/project/api/main.py` — same import; after the `internal.router` include line:

```python
install_metrics(app, service="project")
```

`platforms/auth-service/auth-service/src/auth/api/main.py` — same import; after `app.include_router(internal.router, prefix="/internal/v1", include_in_schema=False)`:

```python
install_metrics(app, service="auth")
```

Create `platforms/test-management-service/src/casebook/utils/metrics.py`:

```python
"""test-management's own metrics, on the registry install_metrics serves at /metrics (blueprint §11.2)."""
from prometheus_client import CollectorRegistry, Counter

REGISTRY = CollectorRegistry()

# type="manual": a person created the case (POST /cases); type="api": an applied Gherkin import or CI
# sync created it. "generated" waits for the AI engine.
CASES_CREATED = Counter("test_case_creation", "Test cases created", ["type"], registry=REGISTRY)
for _type in ("manual", "api"):
    CASES_CREATED.labels(type=_type)
```

`platforms/test-management-service/src/casebook/api/main.py` — imports and, after `app.include_router(api_router, prefix=settings.API_V1_STR)`:

```python
from qeos_shared.metrics import install_metrics

from src.casebook.utils import metrics
```
```python
install_metrics(app, service="test-management", registry=metrics.REGISTRY)
```

`platforms/test-management-service/src/casebook/api/v1/endpoints/cases.py` — add `from src.casebook.utils import metrics` to the imports, and in `create_case` count after the row is stored:

```python
    row = case_service.create_case(db, access.project_id, access.user_id, payload.model_dump())
    metrics.CASES_CREATED.labels(type="manual").inc()
    return case_service.out(row)
```

`platforms/test-management-service/src/casebook/api/v1/endpoints/case_import.py` — add `from src.casebook.utils import metrics`, and after the successful `apply_plan` (after the `except import_service.ImportConflict:` block, before `return _out(plan, payload.full)`):

```python
    metrics.CASES_CREATED.labels(type="api").inc(summary["created"])
    return _out(plan, payload.full)
```

(`summary` is computed above from `plan.summary()`; `apply_plan` only fills case numbers, it does not change the actions.)

- [ ] **Step 5: Run each full suite, one service at a time**

```bash
cd platforms/organization-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/auth-service/auth-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/test-management-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
```
Expected: every suite passes, including the new files.

- [ ] **Step 6: Commit**

```bash
git add platforms/auth-service/auth-service/requirements.txt platforms/auth-service/auth-service/src/auth/api/main.py platforms/auth-service/auth-service/tests/integration/test_metrics.py platforms/organization-service/src/organization/api/main.py platforms/organization-service/tests/integration/test_metrics.py platforms/project-service/requirements.txt platforms/project-service/src/project/api/main.py platforms/project-service/tests/integration/test_metrics.py platforms/test-management-service/requirements.txt platforms/test-management-service/src/casebook/api/main.py platforms/test-management-service/src/casebook/utils/metrics.py platforms/test-management-service/src/casebook/api/v1/endpoints/cases.py platforms/test-management-service/src/casebook/api/v1/endpoints/case_import.py platforms/test-management-service/tests/integration/test_metrics.py
git commit -m "feat: /metrics on auth, organization, project and test-management; test_case_creation_total" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/auth-service/auth-service/requirements.txt platforms/auth-service/auth-service/src/auth/api/main.py platforms/auth-service/auth-service/tests/integration/test_metrics.py platforms/organization-service/src/organization/api/main.py platforms/organization-service/tests/integration/test_metrics.py platforms/project-service/requirements.txt platforms/project-service/src/project/api/main.py platforms/project-service/tests/integration/test_metrics.py platforms/test-management-service/requirements.txt platforms/test-management-service/src/casebook/api/main.py platforms/test-management-service/src/casebook/utils/metrics.py platforms/test-management-service/src/casebook/api/v1/endpoints/cases.py platforms/test-management-service/src/casebook/api/v1/endpoints/case_import.py platforms/test-management-service/tests/integration/test_metrics.py
```

---

### Task 3: Ingestion on `install_metrics`, keeping its registry; `test_executions_total`

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/utils/metrics.py`
- Modify: `platforms/ingestion-service/src/ingestion/api/main.py`
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py`
- Modify: `platforms/ingestion-service/tests/integration/test_health_and_metrics.py`

**Interfaces:**
- Consumes: `install_metrics` (Task 1).
- Produces: `metrics.EXECUTIONS` (`test_executions_total{status}`) and `metrics.HEARTBEAT_READ_ERRORS` (`job_heartbeat_read_errors_total`, used by Task 6) in `src.ingestion.utils.metrics`; `metrics.REGISTRY` unchanged; `metrics.render()` and `metrics.CONTENT_TYPE` removed (only `api/main.py` used them).

- [ ] **Step 1: Write the failing tests**

Append to `platforms/ingestion-service/tests/integration/test_health_and_metrics.py`:

```python
from src.ingestion.utils import metrics


def test_request_metrics_share_the_page_with_the_qav_metrics(client):
    client.get("/api/v1/no-such-route/42")
    text = client.get("/metrics").text
    assert 'api_requests_total{service="ingestion",endpoint="unmatched",method="GET",status_code="404"}' in text
    assert "qav_ingest_runs_total" in text and "build_info" in text


def test_the_four_execution_series_exist_before_any_upload(client):
    text = client.get("/metrics").text
    for status in ("passed", "failed", "errored", "skipped"):
        assert f'test_executions_total{{status="{status}"}}' in text


def executions(status):
    return metrics.REGISTRY.get_sample_value("test_executions_total", {"status": status}) or 0.0


def test_each_stored_result_counts_once_by_status_and_a_replay_counts_nothing(client, make_key):
    _, key = make_key(project_id=7)
    before = {s: executions(s) for s in ("passed", "failed", "errored", "skipped")}
    body = {"run": {"ci_provider": "local", "started_at": "2026-10-10T10:00:00+00:00",
                    "finished_at": "2026-10-10T10:00:05+00:00"},
            "results": [{"name": "a", "status": "passed"}, {"name": "b", "status": "passed"},
                        {"name": "c", "status": "failed"}, {"name": "d", "status": "error"},
                        {"name": "e", "status": "skipped"}]}
    headers = {"Authorization": f"Bearer {key}", "Idempotency-Key": "exec-1"}
    assert client.post("/api/v1/collect/runs", json=body, headers=headers).status_code == 201
    assert client.post("/api/v1/collect/runs", json=body, headers=headers).status_code == 200
    assert {s: executions(s) - before[s] for s in before} == {"passed": 2, "failed": 1, "errored": 1, "skipped": 1}
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_health_and_metrics.py -q`
Expected: the three new tests FAIL (no `api_requests_total`, no `test_executions_total`); the two old ones pass.

- [ ] **Step 3: Implement**

Replace the end of `platforms/ingestion-service/src/ingestion/utils/metrics.py` (from `# Pre-create each reason's series` to the end of the file) with:

```python
# Blueprint §11.2: one execution is one stored test_results row
EXECUTIONS = Counter("test_executions", "Test results stored, by status", ["status"], registry=REGISTRY)
# Job heartbeats are read from the database on each scrape (utils/job_metrics.py); a failed read
# leaves the job series out and counts here, so a database blip never makes ingestion look down
HEARTBEAT_READ_ERRORS = Counter(
    "job_heartbeat_read_errors", "Scrapes that could not read job_heartbeats", registry=REGISTRY,
)

# Pre-create each label's series so it is visible (at 0) before the first event
for _reason in ("auth", "validation", "conflict"):
    REJECTED.labels(reason=_reason)
for _status in ("passed", "failed", "errored", "skipped"):
    EXECUTIONS.labels(status=_status)
```

and change the module docstring's first line to:

```python
"""Prometheus metrics, on their own registry: install_metrics (qeos_shared.metrics) serves it at /metrics
together with the request metrics. Served inside the Docker network; the gateway does not route /metrics."""
```

and the import line to:

```python
from prometheus_client import CollectorRegistry, Counter, Histogram
```

In `platforms/ingestion-service/src/ingestion/api/main.py`: replace `from fastapi import FastAPI, Request, Response` with `from fastapi import FastAPI, Request`; add `from qeos_shared.metrics import install_metrics`; delete the whole `@app.get("/metrics")` function; after `app.include_router(api_router, prefix=settings.API_V1_STR)` add:

```python
# Ingestion's own registry, so the qav_* metrics keep their names on the same page (spec §3)
install_metrics(app, service="ingestion", registry=metrics.REGISTRY)
```

In `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py`, inside `if created:` after `metrics.RESULTS.inc(run.total)`:

```python
        for name in ("passed", "failed", "errored", "skipped"):
            metrics.EXECUTIONS.labels(status=name).inc(getattr(run, name))
```

- [ ] **Step 4: Run the whole ingestion suite**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/utils/metrics.py platforms/ingestion-service/src/ingestion/api/main.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py platforms/ingestion-service/tests/integration/test_health_and_metrics.py
git commit -m "feat(ingestion): request metrics on the existing registry; test_executions_total by status" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/utils/metrics.py platforms/ingestion-service/src/ingestion/api/main.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py platforms/ingestion-service/tests/integration/test_health_and_metrics.py
```

---

### Task 4: Migration 017 `job_heartbeats`, the model and the heartbeat writer

**Files:**
- Create: `platforms/ingestion-service/alembic/versions/017_job_heartbeats.py`
- Create: `platforms/ingestion-service/src/ingestion/models/job_heartbeat.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/__init__.py`
- Create: `platforms/ingestion-service/src/ingestion/jobs/heartbeat.py`
- Create: `platforms/ingestion-service/tests/unit/test_heartbeat.py`
- Create: `platforms/ingestion-service/tests/integration/test_job_heartbeats.py`
- Modify: `platforms/ingestion-service/tests/unit/test_migration.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - Model `JobHeartbeat` (`src.ingestion.models.job_heartbeat`, also exported from `src.ingestion.models`): `job: String(50)` primary key, `last_success_at`, `last_error_at` (`DateTime(timezone=True)`, nullable), `last_error` (`Text`, nullable).
  - `src.ingestion.jobs.heartbeat`: `JOBS = ("retention", "rollup", "weekly_summary")`, `MAX_ERROR = 500`, `short_error(text: str) -> str`, `record_success(session_factory: sessionmaker, job: str, now: Optional[datetime] = None) -> None`, `record_error(session_factory: sessionmaker, job: str, error: str, now: Optional[datetime] = None) -> None`. Neither record function ever raises.

- [ ] **Step 1: Write the failing tests**

Create `platforms/ingestion-service/tests/unit/test_heartbeat.py`:

```python
"""Heartbeat error texts: one line, at most 500 characters, no secrets (spec §3, Review Focus 2)."""
from src.ingestion.jobs.heartbeat import MAX_ERROR, short_error


def test_only_the_first_line_is_kept():
    assert short_error("RuntimeError: boom\nTraceback (most recent call last):\n  File x") == "RuntimeError: boom"


def test_the_text_is_cut_at_500_characters():
    assert len(short_error("x" * 2000)) == MAX_ERROR == 500


def test_credentials_in_a_url_are_replaced():
    text = short_error('OperationalError: connection to "postgresql://postgres:s3cr%40t@postgres:5432/ingestion_db" failed')
    assert "s3cr" not in text and "postgres:s3cr" not in text
    assert "postgresql://***@postgres:5432/ingestion_db" in text


def test_a_password_pair_is_replaced():
    assert short_error("cannot connect: host=db password=hunter2 user=x") == "cannot connect: host=db password=*** user=x"


def test_an_empty_error_is_an_empty_string():
    assert short_error("") == ""
```

Create `platforms/ingestion-service/tests/integration/test_job_heartbeats.py`:

```python
"""Job heartbeats: each loop job upserts its row after every pass (spec §3)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.ingestion.jobs import heartbeat
from src.ingestion.models.job_heartbeat import JobHeartbeat

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session_factory(db):
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)


def aware(moment):
    """SQLite (the tests) hands timezone-aware columns back naive, in UTC."""
    return None if moment is None else (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc))


def row(db, job):
    db.expire_all()
    return db.get(JobHeartbeat, job)


def test_success_creates_the_row(db, session_factory):
    heartbeat.record_success(session_factory, "rollup", NOW)
    hb = row(db, "rollup")
    assert aware(hb.last_success_at) == NOW and hb.last_error_at is None and hb.last_error is None


def test_an_error_after_a_success_keeps_the_success_time(db, session_factory):
    heartbeat.record_success(session_factory, "rollup", NOW)
    heartbeat.record_error(session_factory, "rollup", "RuntimeError: boom\nTraceback", NOW + timedelta(hours=6))
    hb = row(db, "rollup")
    assert aware(hb.last_success_at) == NOW
    assert aware(hb.last_error_at) == NOW + timedelta(hours=6)
    assert hb.last_error == "RuntimeError: boom"


def test_a_later_success_moves_only_the_success_time(db, session_factory):
    heartbeat.record_error(session_factory, "retention", "RetentionError: x", NOW)
    heartbeat.record_success(session_factory, "retention", NOW + timedelta(days=1))
    hb = row(db, "retention")
    assert aware(hb.last_success_at) == NOW + timedelta(days=1) and aware(hb.last_error_at) == NOW


def test_the_stored_error_never_holds_a_password(db, session_factory):
    heartbeat.record_error(session_factory, "retention", "OperationalError: postgresql://u:topsecret@db/x refused", NOW)
    assert "topsecret" not in row(db, "retention").last_error


def test_a_failing_database_never_stops_the_job(capsys):
    def broken():
        raise OperationalError("INSERT", {}, Exception("connection refused"))

    heartbeat.record_success(broken, "rollup", NOW)  # must not raise
    heartbeat.record_error(broken, "rollup", "x", NOW)
    err = capsys.readouterr().err
    assert '"event": "heartbeat_failed"' in err and '"job": "rollup"' in err
```

Append to `platforms/ingestion-service/tests/unit/test_migration.py`:

```python
def test_job_heartbeats_table(migrated_engine):
    """Migration 017 (monitoring spec §3)."""
    inspector = inspect(migrated_engine)
    assert {col["name"] for col in inspector.get_columns("job_heartbeats")} == {
        "job", "last_success_at", "last_error_at", "last_error"}
    assert inspector.get_pk_constraint("job_heartbeats")["constrained_columns"] == ["job"]


def test_job_heartbeats_downgrade_drops_it(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_017.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "016")
    engine = create_engine(url)
    try:
        assert "job_heartbeats" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_heartbeat.py tests/integration/test_job_heartbeats.py tests/unit/test_migration.py -q`
Expected: collection errors (`No module named 'src.ingestion.jobs.heartbeat'`, `... models.job_heartbeat`); the migration tests fail with `NoSuchTableError: job_heartbeats`.

- [ ] **Step 3: Write the migration, the model and the writer**

Create `platforms/ingestion-service/alembic/versions/017_job_heartbeats.py`:

```python
"""job_heartbeats: when each loop job last succeeded and last failed

The loop jobs (retention, rollup, weekly_summary) have no HTTP port, so Prometheus cannot scrape them.
After each pass a job upserts its row here; ingestion's /metrics reads the rows on each scrape
(monitoring spec 2026-10-10 §3).

Revision ID: 017
Revises: 016
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_heartbeats",
        sa.Column("job", sa.String(length=50), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("job_heartbeats")
```

Create `platforms/ingestion-service/src/ingestion/models/job_heartbeat.py`:

```python
from sqlalchemy import Column, DateTime, String, Text

from src.ingestion.db.base import Base


class JobHeartbeat(Base):
    """One row per loop job: its last successful pass and its last failed one (migration 017)."""

    __tablename__ = "job_heartbeats"

    job = Column(String(50), primary_key=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)  # first line, at most 500 characters, no secrets
```

In `platforms/ingestion-service/src/ingestion/models/__init__.py`, add the import and the export:

```python
from src.ingestion.models.job_heartbeat import JobHeartbeat
```
```python
__all__ = ["ApiKey", "FlakyDaily", "FlakyRollupDay", "JobHeartbeat", "MaskingPattern", "MutedTest", "NotificationChannel", "Run", "RunChangedFile", "RunComponent", "RunResult"]
```

Create `platforms/ingestion-service/src/ingestion/jobs/heartbeat.py`:

```python
"""Job heartbeats (monitoring spec 2026-10-10 §3): after each pass a loop job upserts its row in
job_heartbeats; ingestion's /metrics turns the rows into job_last_success_timestamp_seconds and
job_last_error_timestamp_seconds (utils/job_metrics.py).

A heartbeat never stops a job: a failed write is logged and the loop carries on. An error text keeps
only its first line, at most MAX_ERROR characters, with URL credentials and password=... pairs
replaced, so no secret reaches the database or a dashboard.
"""
import json
import re
import sys
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.models.job_heartbeat import JobHeartbeat

JOBS = ("retention", "rollup", "weekly_summary")
MAX_ERROR = 500
_URL_CREDENTIALS = re.compile(r"(?<=://)[^/@\s]+@")
_PASSWORD_PAIR = re.compile(r"(?i)\b(password|pwd)=\S+")


def short_error(text: str) -> str:
    lines = str(text).strip().splitlines()
    first = lines[0] if lines else ""
    first = _URL_CREDENTIALS.sub("***@", first)
    first = _PASSWORD_PAIR.sub(r"\1=***", first)
    return first[:MAX_ERROR]


def _upsert(db: Session, job: str, values: dict) -> None:
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:  # SQLite: the tests
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(JobHeartbeat).values(job=job, **values)
    db.execute(statement.on_conflict_do_update(index_elements=[JobHeartbeat.job], set_=values))
    db.commit()


def _record(session_factory: sessionmaker, job: str, values: dict) -> None:
    try:
        with session_factory() as db:
            _upsert(db, job, values)
    except Exception as exc:  # the database may be the very thing that failed the pass
        print(json.dumps({"event": "heartbeat_failed", "job": job, "error": type(exc).__name__}),
              file=sys.stderr, flush=True)


def record_success(session_factory: sessionmaker, job: str, now: Optional[datetime] = None) -> None:
    _record(session_factory, job, {"last_success_at": now or datetime.now(timezone.utc)})


def record_error(session_factory: sessionmaker, job: str, error: str, now: Optional[datetime] = None) -> None:
    _record(session_factory, job, {"last_error_at": now or datetime.now(timezone.utc), "last_error": short_error(error)})
```

- [ ] **Step 4: Run the whole ingestion suite**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: all pass, including `test_migration_columns_match_models` (model and migration agree).

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/alembic/versions/017_job_heartbeats.py platforms/ingestion-service/src/ingestion/models/job_heartbeat.py platforms/ingestion-service/src/ingestion/models/__init__.py platforms/ingestion-service/src/ingestion/jobs/heartbeat.py platforms/ingestion-service/tests/unit/test_heartbeat.py platforms/ingestion-service/tests/integration/test_job_heartbeats.py platforms/ingestion-service/tests/unit/test_migration.py
git commit -m "feat(ingestion): migration 017 job_heartbeats and a heartbeat writer that never stops a job" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/alembic/versions/017_job_heartbeats.py platforms/ingestion-service/src/ingestion/models/job_heartbeat.py platforms/ingestion-service/src/ingestion/models/__init__.py platforms/ingestion-service/src/ingestion/jobs/heartbeat.py platforms/ingestion-service/tests/unit/test_heartbeat.py platforms/ingestion-service/tests/integration/test_job_heartbeats.py platforms/ingestion-service/tests/unit/test_migration.py
```

---

### Task 5: Heartbeats from the three loop jobs

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/jobs/retention.py` (`run_once`)
- Modify: `platforms/ingestion-service/src/ingestion/jobs/rollup.py` (`run_once`)
- Modify: `platforms/ingestion-service/src/ingestion/jobs/weekly_summary.py` (`run_once`)
- Modify: `platforms/ingestion-service/tests/integration/test_job_heartbeats.py` (append)

**Interfaces:**
- Consumes: `heartbeat.record_success`, `heartbeat.record_error` (Task 4).
- Produces: rows `retention`, `rollup`, `weekly_summary` in `job_heartbeats` after every pass that ran. A pass skipped because another copy holds the lock writes nothing (Ruling 8). Each module gets a constant `JOB`.

- [ ] **Step 1: Write the failing tests**

Append to `platforms/ingestion-service/tests/integration/test_job_heartbeats.py`:

```python
from contextlib import contextmanager

import httpx

from src.ingestion.core.config import settings
from src.ingestion.jobs import retention, rollup, weekly_summary

INTERNAL = "http://ingestion-service:p%40ss%3Aw%2Frd@project-service:8000"
RETENTION_URL = "http://project-service:8000/internal/v1/projects/retention"


def recent(moment):
    return abs(datetime.now(timezone.utc) - aware(moment)) < timedelta(minutes=1)


def test_a_retention_pass_records_its_success(db, session_factory, http, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_SERVICE_INTERNAL_URL", INTERNAL)
    http.get(RETENTION_URL).mock(return_value=httpx.Response(200, json={"projects": []}))
    assert retention.main([], now=lambda: NOW, session_factory=session_factory) == 0
    hb = row(db, "retention")
    assert aware(hb.last_success_at) == NOW and hb.last_error_at is None


def test_a_failed_retention_pass_records_the_error_without_the_password(db, session_factory, http, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_SERVICE_INTERNAL_URL", INTERNAL)
    http.get(RETENTION_URL).mock(return_value=httpx.Response(500))
    assert retention.main([], now=lambda: NOW, session_factory=session_factory) == 1
    hb = row(db, "retention")
    assert hb.last_success_at is None and aware(hb.last_error_at) == NOW
    assert "answered 500" in hb.last_error and "p@ss" not in hb.last_error and "p%40ss" not in hb.last_error


def test_an_unconfigured_retention_job_records_an_error(db, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_SERVICE_INTERNAL_URL", "")
    assert retention.main([], now=lambda: NOW, session_factory=session_factory) == 1
    assert row(db, "retention").last_error.startswith("PROJECT_SERVICE_INTERNAL_URL must look like")


def test_a_rollup_pass_records_its_success(db, session_factory):
    assert rollup.main([], session_factory=session_factory) == 0
    assert recent(row(db, "rollup").last_success_at)


def test_a_failed_rollup_pass_records_the_error(db, session_factory, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(rollup, "run_pass", boom)
    assert rollup.main([], session_factory=session_factory) == 1
    hb = row(db, "rollup")
    assert hb.last_success_at is None and hb.last_error == "RuntimeError: boom" and recent(hb.last_error_at)


def test_a_weekly_summary_pass_records_its_success(db, session_factory):
    assert weekly_summary.main([], session_factory=session_factory) == 0
    assert recent(row(db, "weekly_summary").last_success_at)


def test_a_failed_weekly_summary_pass_records_the_error(db, session_factory, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(weekly_summary, "run_pass", boom)
    assert weekly_summary.main([], session_factory=session_factory) == 1
    assert row(db, "weekly_summary").last_error == "RuntimeError: smtp down"


@pytest.mark.parametrize("module", [rollup, weekly_summary])
def test_a_pass_skipped_for_the_lock_writes_no_heartbeat(db, session_factory, monkeypatch, module):
    @contextmanager
    def held(_engine):
        yield False

    monkeypatch.setattr(module, "_advisory_lock", held)
    assert module.main([], session_factory=session_factory) == 0
    assert row(db, module.JOB) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_job_heartbeats.py -q`
Expected: the new job tests FAIL (`row(...)` is None / `AttributeError: module ... has no attribute 'JOB'`); the Task 4 tests still pass.

- [ ] **Step 3: Record heartbeats in each `run_once`**

`platforms/ingestion-service/src/ingestion/jobs/retention.py` — add `from src.ingestion.jobs import heartbeat` to the imports, `JOB = "retention"` under `TIMEOUT_SECONDS`, and replace `run_once` with:

```python
def run_once(*, dry_run: bool, now: Callable[[], datetime], session_factory: sessionmaker, lock_engine: Engine) -> bool:
    try:
        endpoint = parse_internal_url(settings.PROJECT_SERVICE_INTERNAL_URL)
        with _advisory_lock(lock_engine) as acquired:
            if not acquired:
                _log({"event": "retention_skipped", "reason": "another pass is already running"})
                return True  # the copy holding the lock writes the heartbeat
            policies = fetch_policies(endpoint)
            with session_factory() as db:
                summary = run_pass(
                    db, policies, now(), batch_size=settings.RETENTION_BATCH_SIZE, dry_run=dry_run,
                    grace_days=settings.RETENTION_DELETED_GRACE_DAYS,
                )
    except RetentionError as exc:
        _log({"event": "retention_failed", "error": str(exc)}, error=True)
        heartbeat.record_error(session_factory, JOB, str(exc), now())
        return False
    except Exception as exc:  # e.g. the database is down: report it; the loop tries again later
        message = f"{type(exc).__name__}: {exc}"
        _log({"event": "retention_failed", "error": message}, error=True)
        heartbeat.record_error(session_factory, JOB, message, now())
        return False
    _log(summary)
    heartbeat.record_success(session_factory, JOB, now())
    return True
```

`platforms/ingestion-service/src/ingestion/jobs/rollup.py` — add `from src.ingestion.jobs import heartbeat`, `JOB = "rollup"` under `DEFAULT_INTERVAL_HOURS`, and replace `run_once` with:

```python
def run_once(*, session_factory: sessionmaker, lock_engine: Engine) -> bool:
    try:
        with _advisory_lock(lock_engine) as acquired:
            if not acquired:
                _log({"event": "flaky_rollup", "skipped": "another copy holds the lock"})
                return True  # the copy holding the lock writes the heartbeat
            with session_factory() as db:
                run_pass(db)
    except Exception as exc:  # the loop must survive a bad pass
        message = f"{type(exc).__name__}: {exc}"
        _log({"event": "flaky_rollup", "error": message}, error=True)
        heartbeat.record_error(session_factory, JOB, message)
        return False
    heartbeat.record_success(session_factory, JOB)
    return True
```

`platforms/ingestion-service/src/ingestion/jobs/weekly_summary.py` — add `from src.ingestion.jobs import heartbeat`, `JOB = "weekly_summary"` under `DEFAULT_INTERVAL_MINUTES`, and replace `run_once` with:

```python
def run_once(*, session_factory: sessionmaker, lock_engine: Engine) -> bool:
    try:
        with _advisory_lock(lock_engine) as acquired:
            if not acquired:
                _log({"event": "weekly_summary", "skipped": "another copy holds the lock"})
                return True  # the copy holding the lock writes the heartbeat
            run_pass(session_factory)
    except Exception as exc:  # the loop must survive a bad pass
        message = f"{type(exc).__name__}: {exc}"
        _log({"event": "weekly_summary", "error": message}, error=True)
        heartbeat.record_error(session_factory, JOB, message)
        return False
    heartbeat.record_success(session_factory, JOB)
    return True
```

(A pass of `weekly_summary` before Monday's hour sends nothing and still succeeds: the job is alive. That is why JobStale uses 1 hour for it, Ruling 6.)

- [ ] **Step 4: Run the whole ingestion suite**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: all pass, including `test_retention_job.py`, `test_weekly_summary.py`, `test_flaky_rollup.py` unchanged.

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/jobs/retention.py platforms/ingestion-service/src/ingestion/jobs/rollup.py platforms/ingestion-service/src/ingestion/jobs/weekly_summary.py platforms/ingestion-service/tests/integration/test_job_heartbeats.py
git commit -m "feat(ingestion): retention, rollup and weekly summary record a heartbeat after every pass" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/jobs/retention.py platforms/ingestion-service/src/ingestion/jobs/rollup.py platforms/ingestion-service/src/ingestion/jobs/weekly_summary.py platforms/ingestion-service/tests/integration/test_job_heartbeats.py
```

---

### Task 6: Heartbeat gauges on ingestion's `/metrics`, surviving a database failure

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/utils/job_metrics.py`
- Modify: `platforms/ingestion-service/src/ingestion/api/main.py`
- Modify: `platforms/ingestion-service/tests/conftest.py` (`client` fixture)
- Create: `platforms/ingestion-service/tests/integration/test_heartbeat_metrics.py`

**Interfaces:**
- Consumes: `JobHeartbeat`, `heartbeat.JOBS` (Task 4), `metrics.HEARTBEAT_READ_ERRORS`, `metrics.REGISTRY` (Task 3).
- Produces: `JobHeartbeatCollector(session_factory)` with attribute `session_factory` (swappable in tests); `src.ingestion.api.main.HEARTBEATS`, the instance registered on `metrics.REGISTRY`. Series `job_last_success_timestamp_seconds{job}` and `job_last_error_timestamp_seconds{job}` (Unix seconds, 0 = never) for every job in `JOBS` plus any other row (Ruling 7).

- [ ] **Step 1: Write the failing tests**

Create `platforms/ingestion-service/tests/integration/test_heartbeat_metrics.py`:

```python
"""Ingestion's /metrics reads job_heartbeats on each scrape; a failed read never breaks /metrics (spec §3)."""
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError

from src.ingestion.api import main
from src.ingestion.models.job_heartbeat import JobHeartbeat
from src.ingestion.utils import metrics

SUCCESS = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
ERROR = datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc)


def sample(name, job):
    return metrics.REGISTRY.get_sample_value(name, {"job": job})


def test_every_known_job_is_exposed_at_zero_before_its_first_pass(client):
    text = client.get("/metrics").text
    for job in ("retention", "rollup", "weekly_summary"):
        assert f'job_last_success_timestamp_seconds{{job="{job}"}} 0.0' in text
        assert f'job_last_error_timestamp_seconds{{job="{job}"}} 0.0' in text


def test_heartbeat_rows_become_unix_timestamps_and_the_error_text_stays_out(client, db):
    db.add(JobHeartbeat(job="rollup", last_success_at=SUCCESS, last_error_at=ERROR, last_error="RuntimeError: boom"))
    db.commit()
    text = client.get("/metrics").text
    assert sample("job_last_success_timestamp_seconds", "rollup") == SUCCESS.timestamp()
    assert sample("job_last_error_timestamp_seconds", "rollup") == ERROR.timestamp()
    assert sample("job_last_success_timestamp_seconds", "retention") == 0.0
    assert "boom" not in text


def test_a_failing_heartbeat_read_leaves_the_job_series_out_and_metrics_still_answers(client):
    def broken():
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    before = metrics.REGISTRY.get_sample_value("job_heartbeat_read_errors_total")
    good = main.HEARTBEATS.session_factory
    main.HEARTBEATS.session_factory = broken
    try:
        response = client.get("/metrics")
    finally:
        main.HEARTBEATS.session_factory = good
    assert response.status_code == 200
    assert "job_last_success_timestamp_seconds" not in response.text
    assert "qav_ingest_runs_total" in response.text and "api_requests_total" in response.text
    assert metrics.REGISTRY.get_sample_value("job_heartbeat_read_errors_total") == before + 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_heartbeat_metrics.py -q`
Expected: FAIL (`AttributeError: module 'src.ingestion.api.main' has no attribute 'HEARTBEATS'`, and no `job_last_success_timestamp_seconds` in the text).

- [ ] **Step 3: Write the collector and register it**

Create `platforms/ingestion-service/src/ingestion/utils/job_metrics.py`:

```python
"""Job heartbeat gauges, read from job_heartbeats on every scrape (monitoring spec 2026-10-10 §3).

    job_last_success_timestamp_seconds{job}   Unix seconds; 0 = no successful pass yet
    job_last_error_timestamp_seconds{job}     Unix seconds; 0 = no failed pass yet

Every job in heartbeat.JOBS is always present (0 without a row), so a job that never succeeded is
stale for the JobStale alert. If the read fails, the job series are left out and
job_heartbeat_read_errors_total goes up: /metrics still answers, so a database blip cannot make
ingestion look down. Prometheus scrapes ingestion with honor_labels: true, so the `job` label here
names the loop job instead of becoming exported_job. The error text is never exposed.
"""
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional

from prometheus_client.core import GaugeMetricFamily
from sqlalchemy.orm import Session

from src.ingestion.jobs.heartbeat import JOBS
from src.ingestion.models.job_heartbeat import JobHeartbeat
from src.ingestion.utils import metrics


def _seconds(moment: Optional[datetime]) -> float:
    if moment is None:
        return 0.0
    if moment.tzinfo is None:  # SQLite hands timezone-aware columns back naive, in UTC
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


class JobHeartbeatCollector:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def describe(self) -> list:
        return []  # registering must not touch the database

    def collect(self) -> Iterator[GaugeMetricFamily]:
        try:
            with self.session_factory() as db:
                rows = {row.job: (row.last_success_at, row.last_error_at) for row in db.query(JobHeartbeat).all()}
        except Exception:
            metrics.HEARTBEAT_READ_ERRORS.inc()
            return
        success = GaugeMetricFamily(
            "job_last_success_timestamp_seconds", "When the job last finished a pass without error (0: never)",
            labels=["job"],
        )
        error = GaugeMetricFamily(
            "job_last_error_timestamp_seconds", "When the job last failed a pass (0: never)", labels=["job"],
        )
        for job in sorted(set(JOBS) | set(rows)):
            last_success, last_error = rows.get(job, (None, None))
            success.add_metric([job], _seconds(last_success))
            error.add_metric([job], _seconds(last_error))
        yield success
        yield error
```

In `platforms/ingestion-service/src/ingestion/api/main.py`, add the imports and, right after the `install_metrics(...)` line:

```python
from src.ingestion.db.session import SessionLocal
from src.ingestion.utils.job_metrics import JobHeartbeatCollector
```
```python
HEARTBEATS = JobHeartbeatCollector(SessionLocal)
metrics.REGISTRY.register(HEARTBEATS)
```

In `platforms/ingestion-service/tests/conftest.py`, replace the `client` fixture with:

```python
@pytest.fixture(scope="function")
def client(db):
    from src.ingestion.api.main import HEARTBEATS

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    # /metrics reads job_heartbeats through its own sessions: point them at the test database
    previous = HEARTBEATS.session_factory
    HEARTBEATS.session_factory = TestingSessionLocal
    try:
        with TestClient(app) as c:
            yield c
    finally:
        HEARTBEATS.session_factory = previous
        app.dependency_overrides.clear()
```

- [ ] **Step 4: Run the whole ingestion suite**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/utils/job_metrics.py platforms/ingestion-service/src/ingestion/api/main.py platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_heartbeat_metrics.py
git commit -m "feat(ingestion): job heartbeat gauges on /metrics that survive a database failure" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/utils/job_metrics.py platforms/ingestion-service/src/ingestion/api/main.py platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_heartbeat_metrics.py
```

---

### Task 7: Phase 1 gate

**Files:** none new (fixes only, in the files of Tasks 1–6).

**Interfaces:** Consumes everything in Phase 1; produces a pushable master.

- [ ] **Step 1: Every Python suite, serially**

```bash
cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests -q
cd platforms/organization-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/auth-service/auth-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/test-management-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
```
Expected: all green.

- [ ] **Step 2: The CI-mirroring container steps**

```bash
docker build -t qa-vision/gateway:ci gateway && docker run --rm qa-vision/gateway:ci nginx -t
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```
Expected: `nginx: configuration file /etc/nginx/nginx.conf test is successful`; smoke ends with no `FAIL` line (including "/metrics serves the SPA, not metrics").

- [ ] **Step 3: Metrics and heartbeats on the real stack**

```bash
for svc in auth-service organization-service project-service ingestion-service test-management-service; do
  SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose exec -T "$svc" python -c "import urllib.request; t = urllib.request.urlopen('http://localhost:8000/metrics').read().decode(); assert 'api_requests_total' in t and 'process_resident_memory_bytes' in t, t[:300]; print('$svc ok')"
done
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose exec -T postgres psql -U postgres -d ingestion_db -tAc "SELECT job, last_success_at IS NOT NULL FROM job_heartbeats ORDER BY job"
```
Expected: five `ok` lines; `retention|t`, `rollup|t`, `weekly_summary|t` (the jobs pass once at start-up).

- [ ] **Step 4: Tear down and hand over**

Run: `SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose down` (never `-v`).
Tell the user Phase 1 is ready to push. Do not push.

---

# Phase 2 — The stack

### Task 8: Prometheus configuration, recording and alert rules, promtool tests

**Files:**
- Create: `monitoring/prometheus/prometheus.yml`
- Create: `monitoring/prometheus/recording.yml`
- Create: `monitoring/prometheus/alerts.yml`
- Create: `monitoring/prometheus/entrypoint.sh`
- Create: `monitoring/prometheus/tests/thresholds.yml`
- Create: `monitoring/prometheus/tests/alerts.test.yml`
- Create: `monitoring/check.sh`
- Modify: `.github/workflows/ci.yml` (new job `monitoring`)

**Interfaces:**
- Consumes: the metric names of Tasks 1–6; scrape job names equal the `service` label values (`auth`, `organization`, `project`, `ingestion`, `test-management`) plus `node`, `cadvisor`, `postgres`, `prometheus`, `alertmanager`.
- Produces:
  - Container paths: config at `/etc/qeos/prometheus/prometheus.yml`; rules `/etc/qeos/prometheus/recording.yml`, `/etc/qeos/prometheus/alerts.yml`, `/tmp/thresholds.yml` (rendered by `entrypoint.sh` from `POSTGRES_DB_SIZE_ALERT_GB`, default 20).
  - Recording rules `postgresql_database_size_bytes{datname}`, `postgresql_connections{state}`, `postgresql_database_size_alert_bytes`.
  - Alerts (names used by Alertmanager inhibition in Task 9 and dashboards in Task 14): `ServiceDown`, `High5xxRate`, `SlowRequests`, `JobStale`, `JobFailing`, `UploadsRejected`, `DiskFillingUp`, `MemoryPressure`, `PostgresDown`, `PostgresTooManyConnections`, `PostgresDatabaseGrowing`, `Watchdog`; labels `severity` (`critical`, `warning`, `none`) and, where per service, `service`.
  - `monitoring/check.sh`: every static monitoring check, run in containers; Tasks 9 and 14 add to it.

- [ ] **Step 1: Write the rule tests first**

Create `monitoring/prometheus/tests/thresholds.yml` (the committed copy of what `entrypoint.sh` renders, at the default 20 GB):

```yaml
# What monitoring/prometheus/entrypoint.sh renders with POSTGRES_DB_SIZE_ALERT_GB=20 (Ruling 9); tests only
groups:
  - name: qeos-thresholds
    rules:
      - record: postgresql_database_size_alert_bytes
        expr: vector(20 * 1e9)
```

Create `monitoring/prometheus/tests/alerts.test.yml`:

```yaml
# promtool test rules monitoring/prometheus/tests/alerts.test.yml (monitoring/check.sh runs it).
# One test group per alert behaviour, with synthetic series (spec §8).
rule_files:
  - ../recording.yml
  - ../alerts.yml
  - thresholds.yml

evaluation_interval: 1m

tests:
  - name: recording rules publish the blueprint's PostgreSQL names
    interval: 1m
    input_series:
      - series: 'pg_database_size_bytes{datname="ingestion_db",instance="postgres-exporter:9187",job="postgres"}'
        values: '1000+0x5'
      - series: 'pg_stat_activity_count{datname="ingestion_db",state="active",instance="postgres-exporter:9187",job="postgres"}'
        values: '3+0x5'
      - series: 'pg_stat_activity_count{datname="auth_db",state="active",instance="postgres-exporter:9187",job="postgres"}'
        values: '2+0x5'
      - series: 'pg_stat_activity_count{datname="auth_db",state="idle",instance="postgres-exporter:9187",job="postgres"}'
        values: '4+0x5'
    promql_expr_test:
      - expr: postgresql_database_size_bytes
        eval_time: 2m
        exp_samples:
          - labels: 'postgresql_database_size_bytes{datname="ingestion_db"}'
            value: 1000
      - expr: postgresql_connections
        eval_time: 2m
        exp_samples:
          - labels: 'postgresql_connections{state="active"}'
            value: 5
          - labels: 'postgresql_connections{state="idle"}'
            value: 4

  - name: ServiceDown fires after two minutes down
    interval: 1m
    input_series:
      - series: 'up{job="project",instance="project-service:8000"}'
        values: '1 0 0 0 0 0'
    alert_rule_test:
      - eval_time: 2m
        alertname: ServiceDown
        exp_alerts: []
      - eval_time: 4m
        alertname: ServiceDown
        exp_alerts:
          - exp_labels: {severity: critical, job: project, instance: "project-service:8000", service: project}
            exp_annotations: {summary: "project is down (project-service:8000)"}

  - name: High5xxRate needs a 5% share and at least 20 requests
    interval: 1m
    input_series:
      - series: 'api_requests_total{service="project",endpoint="/x",method="GET",status_code="200"}'
        values: '0+60x20'
      - series: 'api_requests_total{service="project",endpoint="/x",method="GET",status_code="500"}'
        values: '0+10x20'
      # 33% failing, but only 15 requests in 5 minutes: no alert
      - series: 'api_requests_total{service="auth",endpoint="/y",method="GET",status_code="200"}'
        values: '0+2x20'
      - series: 'api_requests_total{service="auth",endpoint="/y",method="GET",status_code="503"}'
        values: '0+1x20'
    alert_rule_test:
      - eval_time: 12m
        alertname: High5xxRate
        exp_alerts:
          - exp_labels: {severity: critical, service: project}
            exp_annotations: {summary: "project: over 5% of requests answer 5xx"}

  - name: SlowRequests uses 2 s, and 10 s for the report
    interval: 1m
    input_series:
      # every request between 2 and 5 s: p95 = 4.85 s
      - series: 'http_requests_duration_seconds_bucket{service="project",endpoint="/api/v1/projects/{project_id}",method="GET",le="1"}'
        values: '0+0x20'
      - series: 'http_requests_duration_seconds_bucket{service="project",endpoint="/api/v1/projects/{project_id}",method="GET",le="2"}'
        values: '0+0x20'
      - series: 'http_requests_duration_seconds_bucket{service="project",endpoint="/api/v1/projects/{project_id}",method="GET",le="5"}'
        values: '0+60x20'
      - series: 'http_requests_duration_seconds_bucket{service="project",endpoint="/api/v1/projects/{project_id}",method="GET",le="+Inf"}'
        values: '0+60x20'
      # the same times on the report stay under its 10 s limit
      - series: 'http_requests_duration_seconds_bucket{service="ingestion",endpoint="/api/v1/projects/{project_id}/analytics/report",method="POST",le="1"}'
        values: '0+0x20'
      - series: 'http_requests_duration_seconds_bucket{service="ingestion",endpoint="/api/v1/projects/{project_id}/analytics/report",method="POST",le="2"}'
        values: '0+0x20'
      - series: 'http_requests_duration_seconds_bucket{service="ingestion",endpoint="/api/v1/projects/{project_id}/analytics/report",method="POST",le="5"}'
        values: '0+60x20'
      - series: 'http_requests_duration_seconds_bucket{service="ingestion",endpoint="/api/v1/projects/{project_id}/analytics/report",method="POST",le="+Inf"}'
        values: '0+60x20'
    alert_rule_test:
      - eval_time: 15m
        alertname: SlowRequests
        exp_alerts:
          - exp_labels: {severity: warning, service: project}
            exp_annotations: {summary: "project: 95th percentile response time over its limit"}

  - name: JobStale uses 2 d, 12 h and 1 h
    interval: 1m
    input_series:
      # at eval_time 10m, time() = 600: rollup last succeeded 50,600 s ago (> 12 h)
      - series: 'job_last_success_timestamp_seconds{job="rollup",instance="ingestion-service:8000"}'
        values: '-50000+0x15'
      # retention: 100,600 s ago, under 2 days
      - series: 'job_last_success_timestamp_seconds{job="retention",instance="ingestion-service:8000"}'
        values: '-100000+0x15'
      # weekly_summary: 600 s ago, under 1 hour
      - series: 'job_last_success_timestamp_seconds{job="weekly_summary",instance="ingestion-service:8000"}'
        values: '0+0x15'
    alert_rule_test:
      - eval_time: 10m
        alertname: JobStale
        exp_alerts:
          - exp_labels: {severity: warning, job: rollup, instance: "ingestion-service:8000"}
            exp_annotations: {summary: "Job rollup has not succeeded for over twice its interval"}

  - name: JobFailing after 30 minutes of an error newer than the last success
    interval: 1m
    input_series:
      - series: 'job_last_error_timestamp_seconds{job="retention",instance="ingestion-service:8000"}'
        values: '600+0x45'
      - series: 'job_last_success_timestamp_seconds{job="retention",instance="ingestion-service:8000"}'
        values: '0+0x45'
    alert_rule_test:
      - eval_time: 20m
        alertname: JobFailing
        exp_alerts: []
      - eval_time: 40m
        alertname: JobFailing
        exp_alerts:
          - exp_labels: {severity: warning, job: retention, instance: "ingestion-service:8000"}
            exp_annotations: {summary: "Job retention failed on its last pass"}

  - name: UploadsRejected over 25% with at least 10 uploads
    interval: 1m
    input_series:
      - series: 'qav_ingest_rejected_total{reason="auth",instance="ingestion-service:8000",job="ingestion"}'
        values: '0+2x40'
      - series: 'qav_ingest_runs_total{instance="ingestion-service:8000",job="ingestion"}'
        values: '0+2x40'
    alert_rule_test:
      - eval_time: 35m
        alertname: UploadsRejected
        exp_alerts:
          - exp_labels: {severity: warning}
            exp_annotations: {summary: "Over 25% of collector uploads are rejected"}

  - name: UploadsRejected ignores a handful of uploads
    interval: 1m
    input_series:
      - series: 'qav_ingest_rejected_total{reason="auth",instance="ingestion-service:8000",job="ingestion"}'
        values: '0+0.2x40'
      - series: 'qav_ingest_runs_total{instance="ingestion-service:8000",job="ingestion"}'
        values: '0+0.2x40'
    alert_rule_test:
      - eval_time: 35m
        alertname: UploadsRejected
        exp_alerts: []

  - name: DiskFillingUp over 85%
    interval: 1m
    input_series:
      - series: 'node_filesystem_avail_bytes{device="/dev/sda1",fstype="ext4",mountpoint="/",instance="node-exporter:9100",job="node"}'
        values: '10+0x20'
      - series: 'node_filesystem_size_bytes{device="/dev/sda1",fstype="ext4",mountpoint="/",instance="node-exporter:9100",job="node"}'
        values: '100+0x20'
    alert_rule_test:
      - eval_time: 10m
        alertname: DiskFillingUp
        exp_alerts:
          - exp_labels: {severity: critical, device: /dev/sda1, fstype: ext4, mountpoint: /, instance: "node-exporter:9100", job: node}
            exp_annotations: {summary: "Disk / is over 85% full or will fill within 24 hours"}

  - name: DiskFillingUp predicted full within 24 hours
    interval: 1m
    input_series:
      # 25% used at 30m, but losing 5 bytes a minute out of 750 left
      - series: 'node_filesystem_avail_bytes{device="/dev/sda1",fstype="ext4",mountpoint="/",instance="node-exporter:9100",job="node"}'
        values: '900-5x60'
      - series: 'node_filesystem_size_bytes{device="/dev/sda1",fstype="ext4",mountpoint="/",instance="node-exporter:9100",job="node"}'
        values: '1000+0x60'
    alert_rule_test:
      - eval_time: 30m
        alertname: DiskFillingUp
        exp_alerts:
          - exp_labels: {severity: critical, device: /dev/sda1, fstype: ext4, mountpoint: /, instance: "node-exporter:9100", job: node}
            exp_annotations: {summary: "Disk / is over 85% full or will fill within 24 hours"}

  - name: MemoryPressure on the VM
    interval: 1m
    input_series:
      - series: 'node_memory_MemAvailable_bytes{instance="node-exporter:9100",job="node"}'
        values: '5+0x20'
      - series: 'node_memory_MemTotal_bytes{instance="node-exporter:9100",job="node"}'
        values: '100+0x20'
    alert_rule_test:
      - eval_time: 5m
        alertname: MemoryPressure
        exp_alerts: []
      - eval_time: 15m
        alertname: MemoryPressure
        exp_alerts:
          - exp_labels: {severity: warning, instance: "node-exporter:9100", job: node}
            exp_annotations: {summary: "Less than 10% of the VM's memory is available"}

  - name: MemoryPressure for a restarting container
    interval: 1m
    input_series:
      - series: 'container_start_time_seconds{name="qa-vision-project-service-1",instance="cadvisor:8080",job="cadvisor"}'
        values: '100 200 300 400 500 500 500'
    alert_rule_test:
      - eval_time: 5m
        alertname: MemoryPressure
        exp_alerts:
          - exp_labels: {severity: warning, name: qa-vision-project-service-1, instance: "cadvisor:8080", job: cadvisor}
            exp_annotations: {summary: "Container qa-vision-project-service-1 restarted more than 3 times in 15 minutes"}

  - name: PostgresDown after two minutes
    interval: 1m
    input_series:
      - series: 'pg_up{instance="postgres-exporter:9187",job="postgres"}'
        values: '1 0 0 0 0 0'
    alert_rule_test:
      - eval_time: 4m
        alertname: PostgresDown
        exp_alerts:
          - exp_labels: {severity: critical, instance: "postgres-exporter:9187", job: postgres}
            exp_annotations: {summary: "PostgreSQL is unreachable from the exporter"}

  - name: PostgresTooManyConnections over 80% of max_connections
    interval: 1m
    input_series:
      - series: 'pg_stat_activity_count{datname="ingestion_db",state="active",instance="postgres-exporter:9187",job="postgres"}'
        values: '90+0x20'
      - series: 'pg_settings_max_connections{instance="postgres-exporter:9187",job="postgres"}'
        values: '100+0x20'
    alert_rule_test:
      - eval_time: 15m
        alertname: PostgresTooManyConnections
        exp_alerts:
          - exp_labels: {severity: warning}
            exp_annotations: {summary: "PostgreSQL connections above 80% of max_connections"}

  - name: PostgresDatabaseGrowing over POSTGRES_DB_SIZE_ALERT_GB
    interval: 1m
    input_series:
      - series: 'pg_database_size_bytes{datname="ingestion_db",instance="postgres-exporter:9187",job="postgres"}'
        values: '25000000000+0x20'
      - series: 'pg_database_size_bytes{datname="auth_db",instance="postgres-exporter:9187",job="postgres"}'
        values: '1000000+0x20'
    alert_rule_test:
      - eval_time: 15m
        alertname: PostgresDatabaseGrowing
        exp_alerts:
          - exp_labels: {severity: warning, datname: ingestion_db}
            exp_annotations: {summary: "Database ingestion_db is larger than POSTGRES_DB_SIZE_ALERT_GB"}

  - name: Watchdog always fires
    interval: 1m
    alert_rule_test:
      - eval_time: 1m
        alertname: Watchdog
        exp_alerts:
          - exp_labels: {severity: none}
            exp_annotations: {summary: "Always firing: proves that rules are evaluated and alerts delivered"}
```

- [ ] **Step 2: Write `check.sh` and see the tests fail**

Create `monitoring/check.sh`:

```bash
#!/usr/bin/env bash
# Static checks of the monitoring configuration, the same locally and in CI (spec §8). Needs Docker only.
#   bash monitoring/check.sh
set -euo pipefail
cd "$(dirname "$0")"
# Git Bash on Windows: a path Docker Desktop understands, and no MSYS rewriting of container paths
here="$(pwd -W 2>/dev/null || pwd)"
export MSYS_NO_PATHCONV=1

PROMETHEUS=prom/prometheus:v3.5.0

run() { docker run --rm -v "$here:/etc/qeos:ro" -w /etc/qeos "$@"; }

echo "== promtool: rules"
run --entrypoint promtool "$PROMETHEUS" check rules prometheus/recording.yml prometheus/alerts.yml prometheus/tests/thresholds.yml
echo "== promtool: rule unit tests"
run --entrypoint promtool "$PROMETHEUS" test rules prometheus/tests/alerts.test.yml
echo "== promtool: configuration (with the thresholds entrypoint.sh renders)"
run --entrypoint /bin/sh "$PROMETHEUS" -c 'sh prometheus/entrypoint.sh --version >/dev/null && promtool check config prometheus/prometheus.yml'
echo "monitoring: all checks passed"
```

Run: `bash monitoring/check.sh`
Expected: FAIL at the first step (`prometheus/recording.yml: no such file or directory`).

- [ ] **Step 3: Write the configuration and the rules**

Create `monitoring/prometheus/prometheus.yml`:

```yaml
# Prometheus for the `monitoring` compose profile (spec §2). Scrape job names equal the services'
# `service` label, so ServiceDown can name the service from `job`.
global:
  scrape_interval: 15s
  evaluation_interval: 15s

alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]

rule_files:
  - /etc/qeos/prometheus/recording.yml
  - /etc/qeos/prometheus/alerts.yml
  # Rendered by entrypoint.sh from POSTGRES_DB_SIZE_ALERT_GB (Ruling 9)
  - /tmp/thresholds.yml

scrape_configs:
  - job_name: auth
    static_configs: [{targets: ["auth-service:8000"]}]
  - job_name: organization
    static_configs: [{targets: ["organization-service:8000"]}]
  - job_name: project
    static_configs: [{targets: ["project-service:8000"]}]
  - job_name: ingestion
    # The job heartbeat gauges carry `job` = the loop job's name (Ruling 5); nothing else ingestion
    # exposes has a job or instance label, so its other series keep job="ingestion"
    honor_labels: true
    static_configs: [{targets: ["ingestion-service:8000"]}]
  - job_name: test-management
    static_configs: [{targets: ["test-management-service:8000"]}]
  - job_name: node
    static_configs: [{targets: ["node-exporter:9100"]}]
  - job_name: cadvisor
    static_configs: [{targets: ["cadvisor:8080"]}]
  - job_name: postgres
    static_configs: [{targets: ["postgres-exporter:9187"]}]
  - job_name: prometheus
    static_configs: [{targets: ["localhost:9090"]}]
  - job_name: alertmanager
    static_configs: [{targets: ["alertmanager:9093"]}]
```

Create `monitoring/prometheus/recording.yml`:

```yaml
# The blueprint's PostgreSQL names (§11.2), published from postgres-exporter's; dashboards and alerts use these
groups:
  - name: qeos-recording
    rules:
      - record: postgresql_database_size_bytes
        expr: sum by (datname) (pg_database_size_bytes)
      - record: postgresql_connections
        expr: sum by (state) (pg_stat_activity_count)
```

Create `monitoring/prometheus/alerts.yml`:

```yaml
# Alert rules (spec §5). Unit tests: tests/alerts.test.yml. Annotations hold no $value so tests stay exact.
groups:
  - name: qeos-services
    rules:
      - alert: ServiceDown
        expr: label_replace(up == 0, "service", "$1", "job", "(.*)")
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "{{ $labels.service }} is down ({{ $labels.instance }})"

      - alert: High5xxRate
        expr: |
          (
            sum by (service) (rate(api_requests_total{status_code=~"5.."}[5m]))
              / sum by (service) (rate(api_requests_total[5m]))
          ) > 0.05
          and sum by (service) (increase(api_requests_total[5m])) >= 20
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "{{ $labels.service }}: over 5% of requests answer 5xx"

      - alert: SlowRequests
        expr: |
          histogram_quantile(0.95, sum by (service, le) (rate(http_requests_duration_seconds_bucket{endpoint!~".*/analytics/report.*"}[5m]))) > 2
          or
          histogram_quantile(0.95, sum by (service, le) (rate(http_requests_duration_seconds_bucket{endpoint=~".*/analytics/report.*"}[5m]))) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "{{ $labels.service }}: 95th percentile response time over its limit"

  - name: qeos-jobs-and-uploads
    rules:
      # 2x each job's interval: retention 24 h, rollup 6 h, weekly summary 30 min (Ruling 6)
      - alert: JobStale
        expr: |
          time() - job_last_success_timestamp_seconds{job="retention"} > 2 * 86400
          or time() - job_last_success_timestamp_seconds{job="rollup"} > 12 * 3600
          or time() - job_last_success_timestamp_seconds{job="weekly_summary"} > 3600
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Job {{ $labels.job }} has not succeeded for over twice its interval"

      - alert: JobFailing
        expr: job_last_error_timestamp_seconds > job_last_success_timestamp_seconds
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Job {{ $labels.job }} failed on its last pass"

      - alert: UploadsRejected
        expr: |
          sum(increase(qav_ingest_rejected_total[15m]))
            / (sum(increase(qav_ingest_rejected_total[15m])) + sum(increase(qav_ingest_runs_total[15m]))) > 0.25
          and (sum(increase(qav_ingest_rejected_total[15m])) + sum(increase(qav_ingest_runs_total[15m]))) >= 10
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Over 25% of collector uploads are rejected"

  - name: qeos-host
    rules:
      - alert: DiskFillingUp
        expr: |
          (1 - node_filesystem_avail_bytes{fstype=~"ext[234]|xfs|btrfs|zfs"} / node_filesystem_size_bytes{fstype=~"ext[234]|xfs|btrfs|zfs"}) > 0.85
          or predict_linear(node_filesystem_avail_bytes{fstype=~"ext[234]|xfs|btrfs|zfs"}[6h], 24 * 3600) < 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Disk {{ $labels.mountpoint }} is over 85% full or will fill within 24 hours"

      - alert: MemoryPressure
        expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Less than 10% of the VM's memory is available"

      # cAdvisor has no restart counter: a new start time is a restart
      - alert: MemoryPressure
        expr: changes(container_start_time_seconds{name!=""}[15m]) > 3
        labels:
          severity: warning
        annotations:
          summary: "Container {{ $labels.name }} restarted more than 3 times in 15 minutes"

  - name: qeos-postgres
    rules:
      - alert: PostgresDown
        expr: pg_up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "PostgreSQL is unreachable from the exporter"

      - alert: PostgresTooManyConnections
        expr: sum(postgresql_connections) / scalar(max(pg_settings_max_connections)) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "PostgreSQL connections above 80% of max_connections"

      - alert: PostgresDatabaseGrowing
        expr: postgresql_database_size_bytes > scalar(postgresql_database_size_alert_bytes)
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Database {{ $labels.datname }} is larger than POSTGRES_DB_SIZE_ALERT_GB"

  - name: qeos-pipeline
    rules:
      - alert: Watchdog
        expr: vector(1)
        labels:
          severity: none
        annotations:
          summary: "Always firing: proves that rules are evaluated and alerts delivered"
```

Create `monitoring/prometheus/entrypoint.sh`:

```sh
#!/bin/sh
# Renders /tmp/thresholds.yml from POSTGRES_DB_SIZE_ALERT_GB (rule files cannot read the environment,
# Ruling 9), then runs Prometheus with the given arguments.
set -eu
gb="${POSTGRES_DB_SIZE_ALERT_GB:-20}"
case "$gb" in
  ''|*[!0-9.]*|*.*.*) echo "prometheus: POSTGRES_DB_SIZE_ALERT_GB must be a number of GB, got '$gb'" >&2; exit 1 ;;
esac
cat > /tmp/thresholds.yml <<EOF
groups:
  - name: qeos-thresholds
    rules:
      - record: postgresql_database_size_alert_bytes
        expr: vector($gb * 1e9)
EOF
exec /bin/prometheus "$@"
```

- [ ] **Step 4: Run the checks until they pass**

Run: `bash monitoring/check.sh`
Expected: `SUCCESS` lines from `check rules`, `SUCCESS` from `test rules` for every group, `SUCCESS` from `check config`, then `monitoring: all checks passed`. A failing group prints the expected and actual alerts: fix the rule (not the test) unless the test contradicts spec §5.

- [ ] **Step 5: Add the CI job**

In `.github/workflows/ci.yml`, add this job after `collector:` (before `gateway:`):

```yaml
  monitoring:
    name: Monitoring configuration
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      # promtool check/test rules and check config, amtool on rendered Alertmanager files, dashboard lint
      - name: Static checks
        run: bash monitoring/check.sh
```

- [ ] **Step 6: Commit**

```bash
git add monitoring/prometheus/prometheus.yml monitoring/prometheus/recording.yml monitoring/prometheus/alerts.yml monitoring/prometheus/entrypoint.sh monitoring/prometheus/tests/thresholds.yml monitoring/prometheus/tests/alerts.test.yml monitoring/check.sh .github/workflows/ci.yml
git commit -m "feat(monitoring): Prometheus config, recording and alert rules with promtool unit tests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- monitoring/prometheus/prometheus.yml monitoring/prometheus/recording.yml monitoring/prometheus/alerts.yml monitoring/prometheus/entrypoint.sh monitoring/prometheus/tests/thresholds.yml monitoring/prometheus/tests/alerts.test.yml monitoring/check.sh .github/workflows/ci.yml
```

---

### Task 9: Alertmanager template, its renderer and its tests

**Files:**
- Create: `monitoring/alertmanager/alertmanager.yml.template`
- Create: `monitoring/alertmanager/render.sh`
- Create: `monitoring/alertmanager/test_render.sh`
- Modify: `monitoring/check.sh`

**Interfaces:**
- Consumes: alert names and `severity` values from Task 8.
- Produces: `render.sh OUTPUT` reads `ALERT_EMAIL_TO`, `ALERT_SLACK_WEBHOOK_URL`, `ALERT_TEAMS_WEBHOOK_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS`, `EMAILS_FROM_EMAIL` and writes a valid `alertmanager.yml`; the container (Task 11) runs it at start into `/tmp/alertmanager.yml`. Receivers `null`, `critical`, `warning`.

- [ ] **Step 1: Write the render tests**

Create `monitoring/alertmanager/test_render.sh`:

```sh
#!/bin/sh
# Renders alertmanager.yml.template under several environments and checks each result; amtool validates
# every file when it is on PATH (monitoring/check.sh runs this inside the alertmanager image). Spec §5, §8.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
failures=0

fail() { echo "FAIL $1"; failures=$((failures + 1)); }

# render NAME [VAR=value ...]: a clean environment plus the given variables
render() {
  name="$1"
  shift
  env -i PATH="$PATH" "$@" sh "$here/render.sh" "$out/$name.yml" 2>"$out/$name.err"
  if command -v amtool >/dev/null 2>&1; then
    if ! amtool check-config "$out/$name.yml" >"$out/$name.amtool" 2>&1; then
      fail "$name: amtool rejected it"
      cat "$out/$name.amtool"
    fi
  fi
}

# expect NAME TEXT N: TEXT appears on N lines of NAME's rendered file
expect() {
  n="$(grep -cF -- "$2" "$out/$1.yml" || true)"
  if [ "$n" = "$3" ]; then echo "ok   $1: \"$2\" x$3"; else fail "$1: \"$2\" x$n, expected x$3"; fi
}

SMTP="SMTP_HOST=smtp.example.com"
SLACK="ALERT_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T000/B000/XXXX"
TEAMS="ALERT_TEAMS_WEBHOOK_URL=https://example.webhook.office.com/webhookb2/abc"

render none
expect none "email_configs:" 0
expect none "slack_configs:" 0
expect none "msteamsv2_configs:" 0

# email alone: critical and warning both go to email
render email_only "$SMTP" ALERT_EMAIL_TO=ops@example.com
expect email_only "email_configs:" 2
expect email_only "smtp_smarthost: 'smtp.example.com:587'" 1
expect email_only "smtp_require_tls: true" 1

# Ruling 11: no SMTP server, no email, a warning in the log
render email_without_smtp ALERT_EMAIL_TO=ops@example.com
expect email_without_smtp "email_configs:" 0
if grep -q "SMTP_HOST is empty" "$out/email_without_smtp.err"; then echo "ok   email_without_smtp: warned"; else fail "email_without_smtp: no warning"; fi

# with Slack, warnings stop going to email
render email_and_slack "$SMTP" ALERT_EMAIL_TO=ops@example.com "$SLACK"
expect email_and_slack "email_configs:" 1
expect email_and_slack "slack_configs:" 2

render all_three "$SMTP" ALERT_EMAIL_TO=ops@example.com "$SLACK" "$TEAMS"
expect all_three "email_configs:" 1
expect all_three "slack_configs:" 2
expect all_three "msteamsv2_configs:" 2

render teams_only "$TEAMS"
expect teams_only "msteamsv2_configs:" 2
expect teams_only "email_configs:" 0

# Review Focus 5: YAML-special characters stay verbatim, and never reach the log
render tricky "$SMTP" ALERT_EMAIL_TO=ops@example.com SMTP_USER=alerts "SMTP_PASSWORD=it's: #not' a comment" SMTP_TLS=false SMTP_PORT=2525
expect tricky "smtp_auth_password: 'it''s: #not'' a comment'" 1
expect tricky "smtp_smarthost: 'smtp.example.com:2525'" 1
expect tricky "smtp_require_tls: false" 1
if grep -qF "#not" "$out/tricky.err"; then fail "tricky: the password reached the log"; fi

if [ "$failures" -eq 0 ]; then
  echo "render: all checks passed"
else
  echo "render: $failures failure(s)"
  exit 1
fi
```

Append to `monitoring/check.sh`, before the final `echo "monitoring: all checks passed"`:

```bash
ALERTMANAGER=prom/alertmanager:v0.28.1
echo "== alertmanager: render and amtool check-config"
run --entrypoint /bin/sh "$ALERTMANAGER" alertmanager/test_render.sh
```

Run: `bash monitoring/check.sh`
Expected: the Prometheus checks pass, then FAIL: `can't open 'alertmanager/render.sh'` (or `No such file`).

- [ ] **Step 2: Write the template and the renderer**

Create `monitoring/alertmanager/alertmanager.yml.template`:

```yaml
# Rendered at start by render.sh (monitoring spec §5): each @@...@@ line is replaced from the environment.
# Edit this template, never the rendered /tmp/alertmanager.yml.
global:
  resolve_timeout: 5m
@@GLOBAL@@

route:
  receiver: "null"
  group_by: ["alertname", "service"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    # Watchdog always fires to prove the pipeline; route it to an external dead-man's switch here if you add one
    - matchers: ['alertname="Watchdog"']
      receiver: "null"
    - matchers: ['severity="critical"']
      receiver: critical
    - matchers: ['severity="warning"']
      receiver: warning

inhibit_rules:
  # A service that is down also fails and is slow: only say that it is down
  - source_matchers: ['alertname="ServiceDown"']
    target_matchers: ['alertname=~"High5xxRate|SlowRequests"']
    equal: ["service"]
  # PostgreSQL unreachable: its other alerts add nothing
  - source_matchers: ['alertname="PostgresDown"']
    target_matchers: ['alertname=~"PostgresTooManyConnections|PostgresDatabaseGrowing"']

receivers:
  - name: "null"
  - name: critical
@@CRITICAL@@
  - name: warning
@@WARNING@@
```

Create `monitoring/alertmanager/render.sh`:

```sh
#!/bin/sh
# Renders alertmanager.yml from alertmanager.yml.template and the environment (monitoring spec §5).
# A channel whose settings are missing is left out, so a missing value never stops start-up; with no
# channel at all every alert goes to the "null" receiver and is visible in Grafana only. Secrets go
# into the output file only, never to the log.
#   usage: render.sh OUTPUT
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
out="${1:?usage: render.sh OUTPUT}"
umask 077
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# A YAML single-quoted scalar: the value verbatim, single quotes doubled
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/''/g")"; }

email=""
slack=""
teams=""
if [ -n "${ALERT_EMAIL_TO:-}" ]; then
  if [ -n "${SMTP_HOST:-}" ]; then
    email=on
  else
    echo "alertmanager: ALERT_EMAIL_TO is set but SMTP_HOST is empty; email alerts are off" >&2
  fi
fi
if [ -n "${ALERT_SLACK_WEBHOOK_URL:-}" ]; then slack=on; fi
if [ -n "${ALERT_TEAMS_WEBHOOK_URL:-}" ]; then teams=on; fi

email_receiver() {
  echo "    email_configs:"
  echo "      - to: $(q "$ALERT_EMAIL_TO")"
  echo "        send_resolved: true"
}
slack_receiver() {
  echo "    slack_configs:"
  echo "      - api_url: $(q "$ALERT_SLACK_WEBHOOK_URL")"
  echo "        send_resolved: true"
}
teams_receiver() {
  echo "    msteamsv2_configs:"
  echo "      - webhook_url: $(q "$ALERT_TEAMS_WEBHOOK_URL")"
  echo "        send_resolved: true"
}

: > "$tmp/global"
if [ -n "$email" ]; then
  case "${SMTP_TLS:-true}" in
    true|True|TRUE|1|yes) tls=true ;;
    *) tls=false ;;
  esac
  {
    echo "  smtp_smarthost: $(q "${SMTP_HOST}:${SMTP_PORT:-587}")"
    echo "  smtp_from: $(q "${EMAILS_FROM_EMAIL:-no-reply@example.com}")"
    if [ -n "${SMTP_USER:-}" ] && [ -n "${SMTP_PASSWORD:-}" ]; then
      echo "  smtp_auth_username: $(q "$SMTP_USER")"
      echo "  smtp_auth_password: $(q "$SMTP_PASSWORD")"
    fi
    echo "  smtp_require_tls: $tls"
  } > "$tmp/global"
fi

# critical: every configured channel
: > "$tmp/critical"
if [ -n "$email" ]; then email_receiver >> "$tmp/critical"; fi
if [ -n "$slack" ]; then slack_receiver >> "$tmp/critical"; fi
if [ -n "$teams" ]; then teams_receiver >> "$tmp/critical"; fi

# warning: Slack and Teams; email only when it is the only channel
: > "$tmp/warning"
if [ -n "$slack" ]; then slack_receiver >> "$tmp/warning"; fi
if [ -n "$teams" ]; then teams_receiver >> "$tmp/warning"; fi
if [ -n "$email" ] && [ -z "$slack" ] && [ -z "$teams" ]; then email_receiver >> "$tmp/warning"; fi

awk -v g="$tmp/global" -v c="$tmp/critical" -v w="$tmp/warning" '
  function dump(file,   line) { while ((getline line < file) > 0) print line; close(file) }
  $0 == "@@GLOBAL@@"   { dump(g); next }
  $0 == "@@CRITICAL@@" { dump(c); next }
  $0 == "@@WARNING@@"  { dump(w); next }
  { print }
' "$here/alertmanager.yml.template" > "$out"
echo "alertmanager: channels email=${email:-off} slack=${slack:-off} teams=${teams:-off}" >&2
```

- [ ] **Step 3: Run the checks until they pass**

Run: `bash monitoring/check.sh`
Expected: only `ok   ...` lines, `render: all checks passed`, then `monitoring: all checks passed`; no `FAIL` line (amtool's output is shown only when it rejects a file).

- [ ] **Step 4: Commit**

```bash
git add monitoring/alertmanager/alertmanager.yml.template monitoring/alertmanager/render.sh monitoring/alertmanager/test_render.sh monitoring/check.sh
git commit -m "feat(monitoring): Alertmanager config rendered from .env, leaving unset channels out" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- monitoring/alertmanager/alertmanager.yml.template monitoring/alertmanager/render.sh monitoring/alertmanager/test_render.sh monitoring/check.sh
```

---

### Task 10: Role `qeos_monitor` and `pg_stat_statements`

**Files:**
- Modify: `scripts/postgres-init.sh`
- Modify: `docker-compose.yml` (`postgres` command, `db-init` environment)

**Interfaces:**
- Consumes: `MONITORING_DB_PASSWORD` from `.env`.
- Produces: login role `qeos_monitor`, member of `pg_monitor` only, password = `MONITORING_DB_PASSWORD`, created or updated on every `up` (new and existing installs alike, since `db-init` runs on every `up`); extension `pg_stat_statements` in database `postgres`; PostgreSQL started with `shared_preload_libraries=pg_stat_statements` (Ruling 10). Task 11's postgres-exporter connects as this role.

- [ ] **Step 1: Write the init step**

Append to `scripts/postgres-init.sh`:

```sh

# Monitoring (spec 2026-10-10 §7): role qeos_monitor with pg_monitor only, which reads statistics and
# settings but no table data. This script runs on every `up`, so the same step creates the role on a
# new install and on one made before monitoring existed, and keeps its password equal to
# MONITORING_DB_PASSWORD. Skipped while the password is unset (monitoring off).
if [ -n "${MONITORING_DB_PASSWORD:-}" ]; then
  psql -v ON_ERROR_STOP=1 -q -d postgres -v pw="$MONITORING_DB_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE qeos_monitor LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qeos_monitor')\gexec
ALTER ROLE qeos_monitor WITH LOGIN PASSWORD :'pw';
GRANT pg_monitor TO qeos_monitor;
-- the PostgreSQL dashboard's slowest statements (Ruling 10)
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL
  echo "role qeos_monitor ready"
fi
```

In `docker-compose.yml`, under `postgres:` add (after `image: postgres:15`):

```yaml
    # pg_stat_statements for the monitoring profile's slowest-statements panel (Ruling 10). Loading it
    # costs a few MB of shared memory and changes nothing else
    command: ["postgres", "-c", "shared_preload_libraries=pg_stat_statements"]
```

and in `db-init:` → `environment:` add:

```yaml
      # Empty unless monitoring is on: then postgres-init.sh creates role qeos_monitor (pg_monitor only)
      MONITORING_DB_PASSWORD: ${MONITORING_DB_PASSWORD:-}
```

- [ ] **Step 2: Verify on a running stack, twice (idempotent)**

```bash
export SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret MONITORING_DB_PASSWORD=local-monitor
docker compose up -d --wait postgres
docker compose run --rm db-init
docker compose run --rm db-init
docker compose exec -T postgres psql -U postgres -tAc "SHOW shared_preload_libraries"
docker compose exec -T postgres psql -U postgres -tAc "SELECT pg_has_role('qeos_monitor', 'pg_monitor', 'member'), rolsuper FROM pg_roles WHERE rolname = 'qeos_monitor'"
docker compose exec -T -e PGPASSWORD=local-monitor postgres psql -U qeos_monitor -h 127.0.0.1 -d postgres -tAc "SELECT count(*) >= 0 FROM pg_stat_statements"
docker compose exec -T -e PGPASSWORD=local-monitor postgres psql -U qeos_monitor -h 127.0.0.1 -d ingestion_db -tAc "SELECT 1 FROM test_runs LIMIT 1"
```
Expected: both `db-init` runs end with `role qeos_monitor ready` and no error; `pg_stat_statements`; `t|f`; `t`; the last command fails with `permission denied for table test_runs`.

- [ ] **Step 3: Without the password nothing changes**

Run: `MONITORING_DB_PASSWORD= docker compose run --rm db-init`
Expected: only the `database ... exists` lines; no `role qeos_monitor` line.

- [ ] **Step 4: Commit**

```bash
git add scripts/postgres-init.sh docker-compose.yml
git commit -m "feat(monitoring): role qeos_monitor (pg_monitor only) on every up; pg_stat_statements preloaded" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- scripts/postgres-init.sh docker-compose.yml
```

---

### Task 11: The `monitoring` compose profile

**Files:**
- Modify: `docker-compose.yml`
- Modify: `deploy/docker-compose.prod.yml`

**Interfaces:**
- Consumes: Task 8 (`monitoring/prometheus/*`), Task 9 (`monitoring/alertmanager/*`), Task 10 (`qeos_monitor`).
- Produces: services `prometheus`, `alertmanager`, `grafana`, `node-exporter`, `cadvisor`, `postgres-exporter`, all `profiles: [monitoring]`; volumes `qeos_prometheus_data`, `qeos_grafana_data`; anchor `x-build-env` (`QEOS_VERSION`, `QEOS_COMMIT`) merged into every service environment (Ruling 14). Grafana listens on `grafana:3000` inside the network, serving under `/grafana/`, and on `127.0.0.1:3000` of the host (break-glass). Task 14 adds Grafana provisioning, Task 17 the auth proxy.

- [ ] **Step 1: Check that every pinned image exists**

```bash
for image in prom/prometheus:v3.5.0 prom/alertmanager:v0.28.1 grafana/grafana:12.0.2 prom/node-exporter:v1.9.1 gcr.io/cadvisor/cadvisor:v0.54.1 quay.io/prometheuscommunity/postgres-exporter:v0.17.1; do
  docker manifest inspect "$image" >/dev/null && echo "ok $image" || echo "MISSING $image"
done
```
Expected: six `ok` lines. If one is missing, pick the nearest older patch release of the same minor version, use it everywhere this plan names the tag (including `monitoring/check.sh`), and say so in the commit message.

- [ ] **Step 2: Add the build-info environment**

In `docker-compose.yml`, add above `x-auth-env`:

```yaml
# build_info{version, commit} on every service's /metrics (Ruling 14). Set QEOS_COMMIT on update:
#   QEOS_COMMIT=$(git rev-parse --short HEAD) docker compose up -d --build --wait gateway
x-build-env: &build-env
  QEOS_VERSION: ${QEOS_VERSION:-dev}
  QEOS_COMMIT: ${QEOS_COMMIT:-unknown}
```

Then merge it into each service environment anchor: in `x-auth-env` and `x-ingestion-env` replace `<<: *smtp-env` with `<<: [*smtp-env, *build-env]`; in `x-organization-env`, `x-project-env` and `x-testmgmt-env` add `<<: *build-env` as the first line.

- [ ] **Step 3: Add the six services and two volumes**

In `docker-compose.yml`, add before `volumes:` (after `gateway:`):

```yaml
  # ---- monitoring profile (spec 2026-10-10, ADR-027): COMPOSE_PROFILES=monitoring in .env turns it on ----
  # Nothing here publishes a port to the internet; Grafana is reached through the gateway at /grafana/
  # and, for break-glass, on 127.0.0.1:3000 of the host only.

  prometheus:
    image: prom/prometheus:v3.5.0
    profiles: [monitoring]
    restart: unless-stopped
    mem_limit: 512m
    # Renders /tmp/thresholds.yml from POSTGRES_DB_SIZE_ALERT_GB, then runs Prometheus with `command`
    entrypoint: ["/bin/sh", "/etc/qeos/prometheus/entrypoint.sh"]
    command:
      - --config.file=/etc/qeos/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=${PROMETHEUS_RETENTION:-15d}
      - --storage.tsdb.retention.size=${PROMETHEUS_RETENTION_SIZE:-5GB}
    environment:
      POSTGRES_DB_SIZE_ALERT_GB: ${POSTGRES_DB_SIZE_ALERT_GB:-20}
    volumes:
      - ./monitoring/prometheus:/etc/qeos/prometheus:ro
      - qeos_prometheus_data:/prometheus
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:9090/-/healthy"]
      interval: 10s
      timeout: 5s
      retries: 12

  alertmanager:
    image: prom/alertmanager:v0.28.1
    profiles: [monitoring]
    restart: unless-stopped
    mem_limit: 64m
    # The config is rendered from the environment at every start (unset channels are left out)
    entrypoint: ["/bin/sh", "-c", "sh /etc/qeos/alertmanager/render.sh /tmp/alertmanager.yml && exec /bin/alertmanager --config.file=/tmp/alertmanager.yml --storage.path=/alertmanager"]
    environment:
      <<: *smtp-env
      ALERT_EMAIL_TO: ${ALERT_EMAIL_TO:-}
      ALERT_SLACK_WEBHOOK_URL: ${ALERT_SLACK_WEBHOOK_URL:-}
      ALERT_TEAMS_WEBHOOK_URL: ${ALERT_TEAMS_WEBHOOK_URL:-}
    volumes:
      - ./monitoring/alertmanager:/etc/qeos/alertmanager:ro
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:9093/-/healthy"]
      interval: 10s
      timeout: 5s
      retries: 12

  grafana:
    image: grafana/grafana:12.0.2
    profiles: [monitoring]
    restart: unless-stopped
    mem_limit: 256m
    # Refuses to start without an admin password (Ruling 17): an empty one would mean admin/admin
    entrypoint: ["/bin/sh", "-c", "if [ -z \"$$GF_SECURITY_ADMIN_PASSWORD\" ]; then echo 'grafana: set GRAFANA_ADMIN_PASSWORD in .env' >&2; exit 1; fi; exec /run.sh"]
    environment:
      GF_SERVER_ROOT_URL: https://localhost:${GATEWAY_HTTPS_PORT:-8443}/grafana/
      GF_SERVER_SERVE_FROM_SUB_PATH: "true"
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_AUTH_ANONYMOUS_ENABLED: "false"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
      GF_NEWS_NEWS_FEED_ENABLED: "false"
      # The gateway location carries no WebSockets (Ruling 13)
      GF_LIVE_MAX_CONNECTIONS: "0"
    ports:
      # Break-glass admin login when auth-service is down: ssh -L 3000:127.0.0.1:3000 <vm>
      - "127.0.0.1:3000:3000"
    volumes:
      - qeos_grafana_data:/var/lib/grafana
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O /dev/null http://localhost:3000/grafana/api/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 20s

  node-exporter:
    image: prom/node-exporter:v1.9.1
    profiles: [monitoring]
    restart: unless-stopped
    mem_limit: 64m
    command: ["--path.rootfs=/host"]
    pid: host
    volumes:
      # Without rslave, which Docker Desktop rejects (Ruling 18)
      - /:/host:ro
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:9100/metrics"]
      interval: 10s
      timeout: 5s
      retries: 12

  cadvisor:
    # v0.54.1, not v0.52.1: v0.52.1 finds no container under Docker's containerd image store
    image: gcr.io/cadvisor/cadvisor:v0.54.1
    profiles: [monitoring]
    restart: unless-stopped
    mem_limit: 128m
    command:
      - --housekeeping_interval=30s
      - --docker_only=true
      - --store_container_labels=false
      - --whitelisted_container_labels=com.docker.compose.service
      # Only CPU, memory and start times are used; the rest would cost memory and series
      - --disable_metrics=advtcp,cpu_topology,cpuset,hugetlb,memory_numa,percpu,process,referenced_memory,resctrl,sched,tcp,udp,disk,diskIO,network
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:8080/healthz"]
      interval: 10s
      timeout: 5s
      retries: 12

  postgres-exporter:
    image: quay.io/prometheuscommunity/postgres-exporter:v0.17.1
    profiles: [monitoring]
    restart: unless-stopped
    mem_limit: 64m
    # Refuses to start without its password (Ruling 17)
    entrypoint: ["/bin/sh", "-c", "if [ -z \"$$DATA_SOURCE_PASS\" ]; then echo 'postgres-exporter: set MONITORING_DB_PASSWORD in .env' >&2; exit 1; fi; exec /bin/postgres_exporter --collector.stat_statements --collector.stat_statements.include_query --collector.stat_statements.query_length=200"]
    environment:
      DATA_SOURCE_URI: postgres:5432/postgres?sslmode=disable
      DATA_SOURCE_USER: qeos_monitor
      DATA_SOURCE_PASS: ${MONITORING_DB_PASSWORD:-}
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:9187/metrics"]
      interval: 10s
      timeout: 5s
      retries: 12
    depends_on:
      db-init:
        condition: service_completed_successfully
```

Add to the `volumes:` section at the end of the file:

```yaml
  # Monitoring profile (Ruling 16). Grafana needs no backup: everything in it is provisioned from the repo
  qeos_prometheus_data:
  qeos_grafana_data:
```

In `deploy/docker-compose.prod.yml`, add under `services:` (after `dashboard:`):

```yaml
  grafana:
    environment:
      # Grafana's links and redirects must use the public address
      GF_SERVER_ROOT_URL: https://${QEOS_DOMAIN:?set QEOS_DOMAIN (see deploy/README.md)}/grafana/
```

- [ ] **Step 4: Without the profile, nothing changes**

```bash
export SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret
docker compose config --services | sort
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml config --quiet && echo prod-ok
```
Expected: the service list has no `prometheus`, `alertmanager`, `grafana`, `node-exporter`, `cadvisor` or `postgres-exporter`; `config` needs no new variable (with `QEOS_DOMAIN=x ACME_EMAIL=y` set for the prod check) and prints `prod-ok`.

- [ ] **Step 5: With the profile, every target is up**

```bash
export SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret COMPOSE_PROFILES=monitoring GRAFANA_ADMIN_PASSWORD=local-grafana MONITORING_DB_PASSWORD=local-monitor
docker compose up -d --build --wait --wait-timeout 300 gateway prometheus alertmanager grafana node-exporter cadvisor postgres-exporter
# Run the queries below about a minute later (scrapes every 15 s); re-run them while a target still shows "unknown"
docker compose exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/targets?state=active' | grep -o '"health":"[a-z]*"' | sort | uniq -c
docker compose exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=container_memory_working_set_bytes%7Bname%21%3D%22%22%7D' | grep -c qa-vision
docker compose exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=postgresql_connections' | grep -o '"state":"[a-z ]*"' | head
docker compose exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=job_last_success_timestamp_seconds' | grep -o '"job":"[a-z_]*"'
docker compose exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/alerts' | grep -o '"alertname":"[A-Za-z]*"' | sort | uniq -c
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep -E 'prometheus|alertmanager|grafana|node-exporter|cadvisor|postgres-exporter'
```
Expected: `10 "health":"up"` and no `down`; a non-zero count of `qa-vision` containers (if 0, add `privileged: true` to `cadvisor`, recreate, and record that in the commit message); connection states such as `"state":"active"` and `"state":"idle"`; `"job":"retention"`, `"job":"rollup"`, `"job":"weekly_summary"`; `Watchdog` firing and no other alert; each container under its limit. Then `docker compose logs alertmanager | grep channels` shows `email=off slack=off teams=off`. If `docker compose ps grafana` stays unhealthy and `docker inspect` shows `wget: not found`, change its healthcheck to `curl -fsS http://localhost:3000/grafana/api/health || exit 1`.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml deploy/docker-compose.prod.yml
git commit -m "feat(monitoring): compose profile with Prometheus, Alertmanager, Grafana and three exporters" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docker-compose.yml deploy/docker-compose.prod.yml
```

---

### Task 12: Operator docs, `.env.example` and `init-env.sh`

**Files:**
- Modify: `deploy/init-env.sh`
- Modify: `.env.example`
- Modify: `deploy/README.md` (§1 and a new §10)
- Modify: `docs/SETUP.md` (§2.3 tables, §6, new §7.4) — another session may be editing it: re-read it right before editing and commit only this path

**Interfaces:**
- Consumes: the variables of Tasks 8–11.
- Produces: `.env` from `init-env.sh` carries `GRAFANA_ADMIN_PASSWORD` and `MONITORING_DB_PASSWORD` (strong, `[A-Za-z0-9]`) and commented `COMPOSE_PROFILES=monitoring`, `MONITORING_ENABLED=true`.

- [ ] **Step 1: Check `init-env.sh` writes the passwords (fails first)**

```bash
tmp="$(mktemp -d)" && mkdir -p "$tmp/deploy" && cp deploy/init-env.sh "$tmp/deploy/" && bash "$tmp/deploy/init-env.sh" qeos.example.com ops@example.com >/dev/null && grep -E '^(GRAFANA_ADMIN_PASSWORD|MONITORING_DB_PASSWORD)=[A-Za-z0-9]{32,}$|^#(COMPOSE_PROFILES|MONITORING_ENABLED)=' "$tmp/.env"; rm -rf "$tmp"
```
Expected now: no output.

- [ ] **Step 2: Update `init-env.sh`**

In `deploy/init-env.sh`, inside the heredoc after `TM_SECRETS_KEY=$tm_key`, add:

```bash
GRAFANA_ADMIN_PASSWORD=$(secret 32)
MONITORING_DB_PASSWORD=$(secret 40)
# Monitoring (Prometheus, Alertmanager, Grafana at https://$domain/grafana/): uncomment both lines
# to turn it on. 8 GB RAM recommended. See deploy/README.md section 10.
#COMPOSE_PROFILES=monitoring
#MONITORING_ENABLED=true
```

Re-run Step 1's command. Expected: the two password lines and the two commented lines.

- [ ] **Step 3: `.env.example`**

Append to `.env.example`:

```bash

# Monitoring (optional): Prometheus, Alertmanager and Grafana at https://localhost:8443/grafana/
# for superusers. Both lines turn it on; the two passwords are then required.
#COMPOSE_PROFILES=monitoring
#MONITORING_ENABLED=true
#GRAFANA_ADMIN_PASSWORD=change-me
#MONITORING_DB_PASSWORD=change-me
# Alert channels: each turns on when set. Email also needs SMTP_HOST (and reuses the other SMTP_* values).
#ALERT_EMAIL_TO=ops@example.com
#ALERT_SLACK_WEBHOOK_URL=
#ALERT_TEAMS_WEBHOOK_URL=
#PROMETHEUS_RETENTION=15d
#PROMETHEUS_RETENTION_SIZE=5GB
#POSTGRES_DB_SIZE_ALERT_GB=20
```

- [ ] **Step 4: `deploy/README.md`**

In §1, after the VM bullet, add:

```markdown
  With the optional monitoring profile (section 10), use **8 GB RAM** (`B2ms`, `t3.large`): its six
  containers can use about 1.1 GB together.
```

In §4, change "freshly generated secrets: `SECRET_KEY`, `INTERNAL_API_PASSWORD`, `POSTGRES_PASSWORD`, `TM_SECRETS_KEY`" to "freshly generated secrets: `SECRET_KEY`, `INTERNAL_API_PASSWORD`, `POSTGRES_PASSWORD`, `TM_SECRETS_KEY`, `GRAFANA_ADMIN_PASSWORD`, `MONITORING_DB_PASSWORD`".

Add a new section at the end:

````markdown
## 10. Monitoring (optional)

Prometheus, Alertmanager and Grafana run as the compose profile `monitoring`, with node-exporter (the
VM), cAdvisor (containers) and postgres-exporter. Off by default; an install without it runs exactly as
before. Design: `docs/superpowers/specs/2026-10-10-monitoring-design.md`, ADR-027.

**Turn it on.** In `.env` (an install from before monitoring: add the two passwords by hand, letters and
digits, 32+ characters):

```bash
COMPOSE_PROFILES=monitoring
MONITORING_ENABLED=true
GRAFANA_ADMIN_PASSWORD=...
MONITORING_DB_PASSWORD=...
```

Then `qeos up -d --build --wait edge`. `db-init` creates the PostgreSQL role `qeos_monitor` (statistics
only, no table data) on that `up`. The first `up` after this release also restarts PostgreSQL once, to
load `pg_stat_statements`.

**Open Grafana.** Signed in as a QEOS superuser, use the account menu → **Monitoring**, or go to
`https://qeos.example.com/grafana/`. Access ends 8 hours later, at sign-out, or as soon as the account
stops being an active superuser. Dashboards: QEOS overview, Service detail, Jobs and uploads,
PostgreSQL, Host and containers.

**Alerts.** Each channel turns on when its settings are present; an unset one is left out:

| Variable | Channel |
|---|---|
| `ALERT_EMAIL_TO` | Email (comma-separated addresses). Reuses `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS`, `EMAILS_FROM_EMAIL`; without `SMTP_HOST` email stays off. |
| `ALERT_SLACK_WEBHOOK_URL` | Slack incoming webhook |
| `ALERT_TEAMS_WEBHOOK_URL` | Microsoft Teams workflow webhook |

Critical alerts (service down, 5xx burst, disk filling up, PostgreSQL down) go to every channel; warnings
(slow requests, stale or failing jobs, rejected uploads, memory pressure, connections, database size) go
to Slack and Teams, or to email when it is the only channel. With no channel, alerts show in Grafana
only. Check what was configured: `qeos logs alertmanager | grep channels`.

| Variable | Default | |
|---|---|---|
| `PROMETHEUS_RETENTION` | `15d` | How long metrics are kept |
| `PROMETHEUS_RETENTION_SIZE` | `5GB` | Cap on Prometheus's disk use |
| `POSTGRES_DB_SIZE_ALERT_GB` | `20` | `PostgresDatabaseGrowing` fires above this |

**Version on the overview.** `QEOS_COMMIT=$(git rev-parse --short HEAD) qeos up -d --build --wait edge`
shows the deployed commit on the overview dashboard (`unknown` otherwise).

**Break-glass.** When auth-service is down, Grafana's own admin login still works from the VM only:
`ssh -L 3000:127.0.0.1:3000 <vm>`, then `http://localhost:3000/grafana/login`, user `admin`, password
`GRAFANA_ADMIN_PASSWORD`. Port 3000 is bound to 127.0.0.1 and never reachable from outside.

**Dead-man's switch (not built).** The `Watchdog` alert always fires. To be told when the whole VM or
Alertmanager is gone, route `Watchdog` to an external heartbeat service (any hosted "dead man's
snitch") by editing `monitoring/alertmanager/alertmanager.yml.template`.

**Data.** Volumes `qa-vision_qeos_prometheus_data` and `qa-vision_qeos_grafana_data`. Grafana needs no
backup (it is provisioned from the repository); `deploy/backup.sh` is unchanged.

**Turn it off.** Remove the two lines, then `qeos up -d --remove-orphans --wait edge`.
````

- [ ] **Step 5: `docs/SETUP.md`** (re-read the file first)

In §2.3, add to the **Optional** table, after the `VITE_MSAL_AUTHORITY` row:

```markdown
| `COMPOSE_PROFILES` | empty | `monitoring` starts Prometheus, Alertmanager, Grafana and the exporters ([7.4](#74-monitoring-optional)). |
| `MONITORING_ENABLED` | `false` | `true` shows the Monitoring item to superusers and opens `/grafana/` at the gateway. Set it together with `COMPOSE_PROFILES`. |
| `GRAFANA_ADMIN_PASSWORD`, `MONITORING_DB_PASSWORD` | empty | Required with monitoring: Grafana's break-glass admin login, and PostgreSQL role `qeos_monitor`. |
| `ALERT_EMAIL_TO`, `ALERT_SLACK_WEBHOOK_URL`, `ALERT_TEAMS_WEBHOOK_URL` | empty | Alert channels; each turns on when set. Email also needs `SMTP_HOST`. |
| `PROMETHEUS_RETENTION`, `PROMETHEUS_RETENTION_SIZE`, `POSTGRES_DB_SIZE_ALERT_GB` | `15d`, `5GB`, `20` | Metrics kept, their disk cap, and the database size alert. |
| `QEOS_COMMIT`, `QEOS_VERSION` | `unknown`, `dev` | Shown as the deployed version on the overview dashboard. |
```

In §6, item 1, append: "With monitoring ([7.4](#74-monitoring-optional)), use 8 GB RAM."

Add after §7.3 (before §8):

````markdown
### 7.4 Monitoring (optional)

Prometheus, Alertmanager and Grafana with node-exporter, cAdvisor and postgres-exporter, as the compose
profile `monitoring`. In `.env`:

```
COMPOSE_PROFILES=monitoring
MONITORING_ENABLED=true
GRAFANA_ADMIN_PASSWORD=<letters and digits>
MONITORING_DB_PASSWORD=<letters and digits>
```

then `docker compose up -d --build --wait gateway`. Signed in as a superuser, open the account menu →
**Monitoring** (or `https://localhost:8443/grafana/`). Alert channels, retention, break-glass access and
turning it off: `deploy/README.md` section 10. Every service also serves `/metrics` inside the compose
network whether or not the profile is on; the gateway never routes it.
````

- [ ] **Step 6: Commit**

```bash
git add deploy/init-env.sh .env.example deploy/README.md docs/SETUP.md
git commit -m "docs(monitoring): how to turn the profile on, alert channels, break-glass; init-env writes the passwords" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- deploy/init-env.sh .env.example deploy/README.md docs/SETUP.md
```

---

### Task 13: Phase 2 gate

**Files:** none new (fixes only, in the files of Tasks 8–12).

- [ ] **Step 1:** Run every Python suite serially (the six commands of Task 7 Step 1). Expected: all green.
- [ ] **Step 2:** `bash monitoring/check.sh`. Expected: `monitoring: all checks passed`.
- [ ] **Step 3:** The CI-mirroring gateway steps without the profile (Task 7 Step 2, with `COMPOSE_PROFILES` unset). Expected: smoke has no `FAIL`.
- [ ] **Step 4:** With the profile: Task 11 Step 5. Expected as stated there.
- [ ] **Step 5:** `docker compose down` (never `-v`). Tell the user Phase 2 is ready to push. Do not push.

---

# Phase 3 — Grafana and the sign-in gate

### Task 14: Grafana provisioning and the five dashboards

**Files:**
- Create: `monitoring/grafana/provisioning/datasources/prometheus.yml`
- Create: `monitoring/grafana/provisioning/dashboards/qeos.yml`
- Create: `monitoring/grafana/dashboards/overview.json`, `service-detail.json`, `jobs-uploads.json`, `postgresql.json`, `host-containers.json`
- Create: `monitoring/grafana/check_dashboards.py`
- Modify: `monitoring/check.sh`
- Modify: `docker-compose.yml` (`grafana` environment and volumes)

**Interfaces:**
- Consumes: metric and recording-rule names (Global Constraints), scrape job names (Task 8).
- Produces: data source uid `prometheus`; dashboard uids `qeos-overview`, `qeos-service-detail`, `qeos-jobs-uploads`, `qeos-postgresql`, `qeos-host-containers`, read-only in folder "QEOS"; the overview is Grafana's home dashboard. `check_dashboards.py [DIR]` exits 1 on any problem.

- [ ] **Step 1: Write the lint script and see it fail**

Create `monitoring/grafana/check_dashboards.py`:

```python
"""Lints the provisioned Grafana dashboards (monitoring spec §8): valid JSON, the five expected uids, unique
panel ids, the provisioned Prometheus data source on every panel, a query on every panel, and no retired
metric names. Usage: python check_dashboards.py [DIR]; exits 1 on any problem."""
import json
import sys
from pathlib import Path

EXPECTED = {"qeos-overview", "qeos-service-detail", "qeos-jobs-uploads", "qeos-postgresql", "qeos-host-containers"}
# Names the plan replaced with blueprint §11.2 names; a dashboard using one would show "No data"
RETIRED = ("qeos_http_", "qeos_job_", "qeos_build_info", "http_request_duration_seconds")


def problems(path: Path):
    try:
        board = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path.name}: not valid JSON: {exc}"], None
    found = [f"{path.name}: missing {key}" for key in ("uid", "title", "panels", "schemaVersion") if key not in board]
    panels = board.get("panels", [])
    ids = [panel.get("id") for panel in panels]
    if len(ids) != len(set(ids)):
        found.append(f"{path.name}: duplicate panel ids")
    for panel in panels:
        where = f"{path.name} panel {panel.get('id')} ({panel.get('title')})"
        if (panel.get("datasource") or {}).get("uid") != "prometheus":
            found.append(f"{where}: data source is not the provisioned 'prometheus'")
        if "gridPos" not in panel:
            found.append(f"{where}: no gridPos")
        targets = panel.get("targets") or []
        if not targets or not all(target.get("expr") for target in targets):
            found.append(f"{where}: every panel needs a query")
        for target in targets:
            for name in RETIRED:
                if name in target.get("expr", ""):
                    found.append(f"{where}: uses retired metric name {name}")
    return found, board.get("uid")


def main(argv) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent / "dashboards"
    found, uids = [], []
    for path in sorted(folder.glob("*.json")):
        more, uid = problems(path)
        found += more
        uids.append(uid)
    if len(uids) != len(set(uids)):
        found.append("duplicate dashboard uids")
    if set(uids) != EXPECTED:
        found.append(f"dashboard uids {sorted(u for u in uids if u)} differ from {sorted(EXPECTED)}")
    for problem in found:
        print(f"FAIL {problem}")
    if not found:
        print(f"dashboards: {len(uids)} checked, all fine")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

Append to `monitoring/check.sh`, before the final `echo`:

```bash
echo "== grafana: dashboard lint"
run python:3.11-slim python grafana/check_dashboards.py
```

Run: `bash monitoring/check.sh`
Expected: FAIL at the dashboard lint: `dashboard uids [] differ from [...]`.

- [ ] **Step 2: Provisioning files**

Create `monitoring/grafana/provisioning/datasources/prometheus.yml`:

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
    jsonData:
      timeInterval: 15s
```

Create `monitoring/grafana/provisioning/dashboards/qeos.yml`:

```yaml
# Dashboards come from the repository, read-only: Grafana needs no backup (spec §7)
apiVersion: 1
providers:
  - name: qeos
    folder: QEOS
    type: file
    disableDeletion: true
    allowUiUpdates: false
    updateIntervalSeconds: 60
    options:
      path: /etc/qeos/grafana/dashboards
```

- [ ] **Step 3: The five dashboards**

Create `monitoring/grafana/dashboards/overview.json`:

```json
{
  "uid": "qeos-overview",
  "title": "QEOS overview",
  "description": "Per service: up, request rate, 5xx share, p95; deployed version; firing alerts (spec §6)",
  "tags": ["qeos"],
  "timezone": "utc",
  "schemaVersion": 39,
  "version": 1,
  "editable": false,
  "refresh": "30s",
  "time": {"from": "now-6h", "to": "now"},
  "templating": {"list": []},
  "panels": [
    {"id": 1, "type": "stat", "title": "Services up", "gridPos": {"h": 4, "w": 24, "x": 0, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"mappings": [{"type": "value", "options": {"0": {"text": "down"}, "1": {"text": "up"}}}],
                                  "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": null}, {"color": "green", "value": 1}]}},
                     "overrides": []},
     "options": {"colorMode": "background", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}},
     "targets": [{"refId": "A", "expr": "up{job=~\"auth|organization|project|ingestion|test-management\"}", "legendFormat": "{{job}}"}]},
    {"id": 2, "type": "timeseries", "title": "Requests per second", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "reqps"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (service) (rate(api_requests_total[5m]))", "legendFormat": "{{service}}"}]},
    {"id": 3, "type": "timeseries", "title": "5xx share", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "percentunit", "min": 0}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (service) (rate(api_requests_total{status_code=~\"5..\"}[5m])) / sum by (service) (rate(api_requests_total[5m]))", "legendFormat": "{{service}}"}]},
    {"id": 4, "type": "timeseries", "title": "95th percentile response time", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 12},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "s"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "histogram_quantile(0.95, sum by (service, le) (rate(http_requests_duration_seconds_bucket[5m])))", "legendFormat": "{{service}}"}]},
    {"id": 5, "type": "table", "title": "Deployed version", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 12},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {}, "overrides": []},
     "targets": [{"refId": "A", "expr": "build_info", "instant": true, "format": "table"}]},
    {"id": 6, "type": "table", "title": "Firing alerts", "gridPos": {"h": 8, "w": 24, "x": 0, "y": 20},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {}, "overrides": []},
     "targets": [{"refId": "A", "expr": "ALERTS{alertstate=\"firing\", alertname!=\"Watchdog\"}", "instant": true, "format": "table"}]}
  ]
}
```

Create `monitoring/grafana/dashboards/service-detail.json`:

```json
{
  "uid": "qeos-service-detail",
  "title": "Service detail",
  "description": "One service: per endpoint rate and latency, status codes, in-flight requests, process memory and CPU (spec §6)",
  "tags": ["qeos"],
  "timezone": "utc",
  "schemaVersion": 39,
  "version": 1,
  "editable": false,
  "refresh": "30s",
  "time": {"from": "now-6h", "to": "now"},
  "templating": {"list": [
    {"name": "service", "label": "Service", "type": "query", "datasource": {"type": "prometheus", "uid": "prometheus"},
     "query": "label_values(api_requests_total, service)", "definition": "label_values(api_requests_total, service)",
     "refresh": 2, "includeAll": false, "multi": false, "sort": 1}
  ]},
  "panels": [
    {"id": 1, "type": "timeseries", "title": "Requests per second by endpoint", "gridPos": {"h": 9, "w": 12, "x": 0, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "reqps"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (method, endpoint) (rate(api_requests_total{service=\"$service\"}[5m]))", "legendFormat": "{{method}} {{endpoint}}"}]},
    {"id": 2, "type": "timeseries", "title": "Response time p50 / p95 / p99", "gridPos": {"h": 9, "w": 12, "x": 12, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "s"}, "overrides": []},
     "targets": [
       {"refId": "A", "expr": "histogram_quantile(0.50, sum by (le) (rate(http_requests_duration_seconds_bucket{service=\"$service\"}[5m])))", "legendFormat": "p50"},
       {"refId": "B", "expr": "histogram_quantile(0.95, sum by (le) (rate(http_requests_duration_seconds_bucket{service=\"$service\"}[5m])))", "legendFormat": "p95"},
       {"refId": "C", "expr": "histogram_quantile(0.99, sum by (le) (rate(http_requests_duration_seconds_bucket{service=\"$service\"}[5m])))", "legendFormat": "p99"}]},
    {"id": 3, "type": "timeseries", "title": "p95 by endpoint", "gridPos": {"h": 9, "w": 12, "x": 0, "y": 9},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "s"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "histogram_quantile(0.95, sum by (endpoint, le) (rate(http_requests_duration_seconds_bucket{service=\"$service\"}[5m])))", "legendFormat": "{{endpoint}}"}]},
    {"id": 4, "type": "timeseries", "title": "Status codes", "gridPos": {"h": 9, "w": 12, "x": 12, "y": 9},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "reqps"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (status_code) (rate(api_requests_total{service=\"$service\"}[5m]))", "legendFormat": "{{status_code}}"}]},
    {"id": 5, "type": "timeseries", "title": "Requests in flight", "gridPos": {"h": 8, "w": 8, "x": 0, "y": 18},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "http_requests_in_flight{service=\"$service\"}", "legendFormat": "in flight"}]},
    {"id": 6, "type": "timeseries", "title": "Process memory", "gridPos": {"h": 8, "w": 8, "x": 8, "y": 18},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "process_resident_memory_bytes{job=\"$service\"}", "legendFormat": "resident"}]},
    {"id": 7, "type": "timeseries", "title": "Process CPU", "gridPos": {"h": 8, "w": 8, "x": 16, "y": 18},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "percentunit"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "rate(process_cpu_seconds_total{job=\"$service\"}[5m])", "legendFormat": "cpu"}]}
  ]
}
```

Create `monitoring/grafana/dashboards/jobs-uploads.json`:

```json
{
  "uid": "qeos-jobs-uploads",
  "title": "Jobs and uploads",
  "description": "Time since each job's last success and last error; uploads accepted and rejected; results per hour; upload handling time; executions and cases created (spec §6)",
  "tags": ["qeos"],
  "timezone": "utc",
  "schemaVersion": 39,
  "version": 1,
  "editable": false,
  "refresh": "1m",
  "time": {"from": "now-24h", "to": "now"},
  "templating": {"list": []},
  "panels": [
    {"id": 1, "type": "stat", "title": "Since last success", "description": "Stale above 2 days (retention), 12 h (rollup), 1 h (weekly summary)", "gridPos": {"h": 5, "w": 12, "x": 0, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "s"}, "overrides": []},
     "options": {"graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}},
     "targets": [{"refId": "A", "expr": "time() - job_last_success_timestamp_seconds", "legendFormat": "{{job}}"}]},
    {"id": 2, "type": "stat", "title": "Since last error", "description": "Jobs that never failed are not shown", "gridPos": {"h": 5, "w": 12, "x": 12, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "s"}, "overrides": []},
     "options": {"graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}},
     "targets": [{"refId": "A", "expr": "time() - (job_last_error_timestamp_seconds > 0)", "legendFormat": "{{job}}"}]},
    {"id": 3, "type": "timeseries", "title": "Uploads per hour, accepted and rejected", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 5},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
     "targets": [
       {"refId": "A", "expr": "sum(increase(qav_ingest_runs_total[1h]))", "legendFormat": "accepted"},
       {"refId": "B", "expr": "sum by (reason) (increase(qav_ingest_rejected_total[1h]))", "legendFormat": "rejected: {{reason}}"}]},
    {"id": 4, "type": "timeseries", "title": "Results stored per hour", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 5},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum(increase(qav_ingest_results_total[1h]))", "legendFormat": "results"}]},
    {"id": 5, "type": "timeseries", "title": "Upload handling time p95", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 13},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "s"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "histogram_quantile(0.95, sum by (le) (rate(qav_ingest_duration_seconds_bucket[5m])))", "legendFormat": "p95"}]},
    {"id": 6, "type": "timeseries", "title": "Test executions per hour by status", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 13},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (status) (increase(test_executions_total[1h]))", "legendFormat": "{{status}}"}]},
    {"id": 7, "type": "timeseries", "title": "Test cases created per day", "gridPos": {"h": 8, "w": 24, "x": 0, "y": 21},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (type) (increase(test_case_creation_total[1d]))", "legendFormat": "{{type}}"}]}
  ]
}
```

Create `monitoring/grafana/dashboards/postgresql.json`:

```json
{
  "uid": "qeos-postgresql",
  "title": "PostgreSQL",
  "description": "Connections, database sizes, transactions, cache hit rate, locks, slowest statements (spec §6)",
  "tags": ["qeos"],
  "timezone": "utc",
  "schemaVersion": 39,
  "version": 1,
  "editable": false,
  "refresh": "30s",
  "time": {"from": "now-6h", "to": "now"},
  "templating": {"list": []},
  "panels": [
    {"id": 1, "type": "stat", "title": "Reachable", "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"mappings": [{"type": "value", "options": {"0": {"text": "down"}, "1": {"text": "up"}}}],
                                  "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": null}, {"color": "green", "value": 1}]}},
                     "overrides": []},
     "options": {"colorMode": "background", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}},
     "targets": [{"refId": "A", "expr": "pg_up", "legendFormat": "postgres"}]},
    {"id": 2, "type": "timeseries", "title": "Connections by state", "gridPos": {"h": 8, "w": 18, "x": 6, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
     "targets": [
       {"refId": "A", "expr": "postgresql_connections", "legendFormat": "{{state}}"},
       {"refId": "B", "expr": "max(pg_settings_max_connections)", "legendFormat": "max_connections"}]},
    {"id": 3, "type": "timeseries", "title": "Database sizes", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "postgresql_database_size_bytes", "legendFormat": "{{datname}}"}]},
    {"id": 4, "type": "timeseries", "title": "Transactions per second", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (datname) (rate(pg_stat_database_xact_commit[5m]) + rate(pg_stat_database_xact_rollback[5m]))", "legendFormat": "{{datname}}"}]},
    {"id": 5, "type": "timeseries", "title": "Cache hit rate", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "percentunit", "max": 1}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum(rate(pg_stat_database_blks_hit[5m])) / (sum(rate(pg_stat_database_blks_hit[5m])) + sum(rate(pg_stat_database_blks_read[5m])))", "legendFormat": "hit rate"}]},
    {"id": 6, "type": "timeseries", "title": "Locks by mode", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 16},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (mode) (pg_locks_count)", "legendFormat": "{{mode}}"}]},
    {"id": 7, "type": "table", "title": "Slowest statements (mean seconds per call, last 5 minutes)", "gridPos": {"h": 10, "w": 24, "x": 0, "y": 24},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "s"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "topk(10, rate(pg_stat_statements_seconds_total[5m]) / rate(pg_stat_statements_calls_total[5m]))", "instant": true, "format": "table"}]}
  ]
}
```

Create `monitoring/grafana/dashboards/host-containers.json`:

```json
{
  "uid": "qeos-host-containers",
  "title": "Host and containers",
  "description": "VM CPU, memory and disk with trend; per container CPU, memory and restarts (spec §6)",
  "tags": ["qeos"],
  "timezone": "utc",
  "schemaVersion": 39,
  "version": 1,
  "editable": false,
  "refresh": "30s",
  "time": {"from": "now-24h", "to": "now"},
  "templating": {"list": []},
  "panels": [
    {"id": 1, "type": "timeseries", "title": "VM CPU used", "gridPos": {"h": 8, "w": 8, "x": 0, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "percentunit", "min": 0, "max": 1}, "overrides": []},
     "targets": [{"refId": "A", "expr": "1 - avg(rate(node_cpu_seconds_total{mode=\"idle\"}[5m]))", "legendFormat": "cpu"}]},
    {"id": 2, "type": "timeseries", "title": "VM memory available", "gridPos": {"h": 8, "w": 8, "x": 8, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "percentunit", "min": 0, "max": 1}, "overrides": []},
     "targets": [{"refId": "A", "expr": "node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "legendFormat": "available"}]},
    {"id": 3, "type": "timeseries", "title": "Disk used", "gridPos": {"h": 8, "w": 8, "x": 16, "y": 0},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "percentunit", "min": 0, "max": 1}, "overrides": []},
     "targets": [{"refId": "A", "expr": "1 - node_filesystem_avail_bytes{fstype=~\"ext[234]|xfs|btrfs|zfs\"} / node_filesystem_size_bytes{fstype=~\"ext[234]|xfs|btrfs|zfs\"}", "legendFormat": "{{mountpoint}}"}]},
    {"id": 4, "type": "timeseries", "title": "Free disk now and predicted in 24 hours", "gridPos": {"h": 8, "w": 24, "x": 0, "y": 8},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
     "targets": [
       {"refId": "A", "expr": "node_filesystem_avail_bytes{fstype=~\"ext[234]|xfs|btrfs|zfs\"}", "legendFormat": "{{mountpoint}} now"},
       {"refId": "B", "expr": "predict_linear(node_filesystem_avail_bytes{fstype=~\"ext[234]|xfs|btrfs|zfs\"}[6h], 24 * 3600)", "legendFormat": "{{mountpoint}} in 24 h"}]},
    {"id": 5, "type": "timeseries", "title": "Container CPU", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "percentunit"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (container_label_com_docker_compose_service) (rate(container_cpu_usage_seconds_total{name!=\"\"}[5m]))", "legendFormat": "{{container_label_com_docker_compose_service}}"}]},
    {"id": 6, "type": "timeseries", "title": "Container memory", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 16},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "bytes"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (container_label_com_docker_compose_service) (container_memory_working_set_bytes{name!=\"\"})", "legendFormat": "{{container_label_com_docker_compose_service}}"}]},
    {"id": 7, "type": "timeseries", "title": "Container restarts in the last hour", "gridPos": {"h": 8, "w": 24, "x": 0, "y": 24},
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
     "targets": [{"refId": "A", "expr": "sum by (container_label_com_docker_compose_service) (changes(container_start_time_seconds{name!=\"\"}[1h]))", "legendFormat": "{{container_label_com_docker_compose_service}}"}]}
  ]
}
```

- [ ] **Step 4: Mount them into Grafana**

In `docker-compose.yml` → `grafana:` → `environment:` add:

```yaml
      GF_PATHS_PROVISIONING: /etc/qeos/grafana/provisioning
      GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH: /etc/qeos/grafana/dashboards/overview.json
```

and to its `volumes:`:

```yaml
      - ./monitoring/grafana/provisioning:/etc/qeos/grafana/provisioning:ro
      - ./monitoring/grafana/dashboards:/etc/qeos/grafana/dashboards:ro
```

- [ ] **Step 5: The lint passes, and fails on a broken copy**

Run: `bash monitoring/check.sh`
Expected: `dashboards: 5 checked, all fine`, then `monitoring: all checks passed`.

Then prove the lint can fail:
```bash
tmp="$(mktemp -d)" && cp monitoring/grafana/dashboards/*.json "$tmp/" && sed -i 's/"uid": "prometheus"/"uid": "other"/' "$tmp/overview.json" && python monitoring/grafana/check_dashboards.py "$tmp"; echo "exit=$?"; rm -rf "$tmp"
```
Expected: `FAIL overview.json panel 1 (Services up): data source is not the provisioned 'prometheus'` (and the other panels), `exit=1`.

- [ ] **Step 6: The dashboards load and show data (break-glass login)**

```bash
export SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret COMPOSE_PROFILES=monitoring GRAFANA_ADMIN_PASSWORD=local-grafana MONITORING_DB_PASSWORD=local-monitor
docker compose up -d --build --wait --wait-timeout 300 gateway prometheus alertmanager grafana node-exporter cadvisor postgres-exporter
curl -s -u admin:local-grafana 'http://127.0.0.1:3000/grafana/api/search?tag=qeos' | grep -o '"title":"[^"]*"'
curl -s -u admin:local-grafana 'http://127.0.0.1:3000/grafana/api/datasources/uid/prometheus/health'
for q in pg_stat_database_xact_commit pg_stat_database_blks_hit pg_locks_count pg_stat_statements_seconds_total pg_stat_statements_calls_total; do
  printf '%s ' "$q"; docker compose exec -T prometheus wget -qO- "http://localhost:9090/api/v1/query?query=count($q)" | grep -o '"value":\[[^]]*\]' || echo "NO DATA"
done
```
Expected: the five titles; `"status":"OK"`; a value for each PostgreSQL metric. If one says `NO DATA`, list the exporter's real names (`docker compose exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/label/__name__/values' | tr ',' '\n' | grep '^"pg_'`) and change the panel query to the exporter's name (e.g. a `_total` suffix), then re-run Step 5. Open `http://127.0.0.1:3000/grafana/` in a browser, sign in as `admin`, and look at each dashboard: every panel shows data except "Since last error" (no job has failed) and the alert table.

- [ ] **Step 7: Commit**

```bash
git add monitoring/grafana monitoring/check.sh docker-compose.yml
git commit -m "feat(monitoring): Grafana provisioning and five read-only dashboards, with a lint in CI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- monitoring/grafana monitoring/check.sh docker-compose.yml
```

---

### Task 15: auth-service hands a superuser the Grafana cookie

**Files:**
- Create: `platforms/auth-service/auth-service/src/auth/utils/grafana_session.py`
- Modify: `platforms/auth-service/auth-service/src/auth/config.py`
- Modify: `platforms/auth-service/auth-service/src/auth/schemas/user.py`
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py` (`/me`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py` (new endpoint, logout)
- Create: `platforms/auth-service/auth-service/tests/integration/test_grafana_session.py`

**Interfaces:**
- Consumes: `deps.get_current_user`, `deps.get_current_active_user`, `settings`.
- Produces:
  - `settings.MONITORING_ENABLED: bool = False`.
  - `src.auth.utils.grafana_session`: `GRAFANA_COOKIE = "qeos_grafana"`, `GRAFANA_COOKIE_PATH = "/grafana"`, `GRAFANA_AUDIENCE = "grafana"`, `GRAFANA_SESSION_HOURS = 8`, `MONITORING_URL = "/grafana/"`, `create_grafana_token(user_id: int, now: Optional[datetime] = None) -> str`, `grafana_user_id(token: Optional[str]) -> Optional[int]`, `set_grafana_cookie(response, token) -> None`, `clear_grafana_cookie(response) -> None`. Task 16 uses `grafana_user_id` and `GRAFANA_COOKIE`.
  - `GET /api/v1/users/me` → adds `monitoring_url: str | null`.
  - `POST /api/v1/auth/grafana-session` → 200 `{"url": "/grafana/"}` plus the cookie; 403 unless monitoring is on and the user is an active superuser; 401 without a valid access token.
  - `POST /api/v1/auth/logout` also clears `qeos_grafana` (`Path=/grafana`).

- [ ] **Step 1: Write the failing tests**

Create `platforms/auth-service/auth-service/tests/integration/test_grafana_session.py`:

```python
"""Monitoring sign-in hand-off (monitoring spec §4, ADR-027): monitoring_url on /users/me,
POST /auth/grafana-session, and logout clearing the cookie."""
import jwt
import pytest

from src.auth.config import settings
from src.auth.models.user import User
from src.auth.utils.grafana_session import GRAFANA_AUDIENCE, grafana_user_id
from src.auth.utils.tokens import create_access_token

SESSION = "/api/v1/auth/grafana-session"
ME = "/api/v1/users/me"


@pytest.fixture
def monitoring(monkeypatch):
    monkeypatch.setattr(settings, "MONITORING_ENABLED", True)


def make_user(db, email="ops@example.com", superuser=True, active=True):
    row = User(email=email, hashed_password="x", is_active=active, is_superuser=superuser)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def bearer(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


def grafana_cookie(response):
    return next((c for c in response.headers.get_list("set-cookie") if c.startswith("qeos_grafana=")), None)


def test_me_offers_monitoring_to_a_superuser_while_it_is_on(client, db, monitoring):
    assert client.get(ME, headers=bearer(make_user(db))).json()["monitoring_url"] == "/grafana/"


def test_me_offers_nothing_to_other_users(client, db, monitoring):
    assert client.get(ME, headers=bearer(make_user(db, superuser=False))).json()["monitoring_url"] is None


def test_me_offers_nothing_while_monitoring_is_off(client, db):
    assert client.get(ME, headers=bearer(make_user(db))).json()["monitoring_url"] is None


def test_a_superuser_gets_an_8_hour_strict_cookie_for_grafana_only(client, db, monitoring):
    user = make_user(db)
    response = client.post(SESSION, headers=bearer(user))
    assert response.status_code == 200, response.text
    assert response.json() == {"url": "/grafana/"}
    cookie = grafana_cookie(response)
    assert cookie is not None
    lowered = cookie.lower()
    for part in ("httponly", "secure", "samesite=strict", "path=/grafana", "max-age=28800"):
        assert part in lowered, part
    token = cookie.split(";")[0].split("=", 1)[1]
    assert grafana_user_id(token) == user.id
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], audience=GRAFANA_AUDIENCE)
    assert claims["exp"] - claims["iat"] == 8 * 3600 and claims["token_type"] == "grafana"


def test_a_user_who_is_not_a_superuser_gets_403_and_no_cookie(client, db, monitoring):
    response = client.post(SESSION, headers=bearer(make_user(db, superuser=False)))
    assert response.status_code == 403 and grafana_cookie(response) is None


def test_an_inactive_superuser_gets_403(client, db, monitoring):
    assert client.post(SESSION, headers=bearer(make_user(db, active=False))).status_code == 403


def test_403_while_monitoring_is_off(client, db):
    assert client.post(SESSION, headers=bearer(make_user(db))).status_code == 403


def test_without_a_token_401(client, monitoring):
    assert client.post(SESSION).status_code == 401


def test_the_grafana_token_is_not_an_access_token(client, db, monitoring):
    """Review Focus 3: the cookie's JWT carries aud=grafana and token_type, so the API refuses it."""
    user = make_user(db)
    token = grafana_cookie(client.post(SESSION, headers=bearer(user))).split(";")[0].split("=", 1)[1]
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_logout_clears_the_grafana_cookie(client, register_and_verify):
    tokens = register_and_verify("leaver@example.com")
    response = client.post("/api/v1/auth/logout", json={}, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 200, response.text
    cookie = grafana_cookie(response)
    assert cookie is not None
    assert "max-age=0" in cookie.lower() and "path=/grafana" in cookie.lower()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/auth-service/auth-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_grafana_session.py -q`
Expected: collection error `No module named 'src.auth.utils.grafana_session'`.

- [ ] **Step 3: Implement**

In `platforms/auth-service/auth-service/src/auth/config.py`, add after `INTERNAL_API_PASSWORD: str = ""`:

```python
    # Monitoring (spec 2026-10-10, ADR-027): offer Grafana at /grafana/ to superusers. Same .env value
    # the gateway reads; the compose profile `monitoring` must be on too
    MONITORING_ENABLED: bool = False
```

Create `platforms/auth-service/auth-service/src/auth/utils/grafana_session.py`:

```python
"""The short-lived cookie that lets a QEOS superuser into Grafana at /grafana/ (monitoring spec §4, ADR-027).

A plain browser visit to /grafana/ carries neither the refresh cookie (scoped to /api/v1/auth) nor the
access token (in the dashboard's memory), so POST /auth/grafana-session hands over this cookie
explicitly. It is a JWT with its own audience: PyJWT refuses a token carrying `aud` when no audience is
asked for, and `token_type` fails is_access_token, so it never works as an access token; an access
token has no `aud`, so it never works here. The gateway's auth_request asks
GET /internal/v1/grafana-check on every /grafana/ request, which also re-checks the user."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Response

from src.auth.config import settings

GRAFANA_COOKIE = "qeos_grafana"
GRAFANA_COOKIE_PATH = "/grafana"
GRAFANA_AUDIENCE = "grafana"
GRAFANA_SESSION_HOURS = 8
MONITORING_URL = "/grafana/"


def create_grafana_token(user_id: int, now: Optional[datetime] = None) -> str:
    issued = now or datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "aud": GRAFANA_AUDIENCE,
        "token_type": "grafana",
        "iat": issued,
        "exp": issued + timedelta(hours=GRAFANA_SESSION_HOURS),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def grafana_user_id(token: Optional[str]) -> Optional[int]:
    """The user a valid Grafana token names; None for anything else (bad signature, expired, wrong
    audience, an access token, garbage)."""
    if not token:
        return None
    try:
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], audience=GRAFANA_AUDIENCE)
        if claims.get("token_type") != "grafana":
            return None
        return int(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def set_grafana_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        GRAFANA_COOKIE,
        token,
        max_age=GRAFANA_SESSION_HOURS * 3600,
        httponly=True,
        secure=True,
        samesite="strict",
        path=GRAFANA_COOKIE_PATH,
    )


def clear_grafana_cookie(response: Response) -> None:
    response.delete_cookie(GRAFANA_COOKIE, path=GRAFANA_COOKIE_PATH, secure=True, httponly=True, samesite="strict")
```

In `platforms/auth-service/auth-service/src/auth/schemas/user.py`, add after `class User`:

```python
class UserMe(User):
    # GET /users/me only: "/grafana/" for a superuser while MONITORING_ENABLED, else null (ADR-027).
    # The dashboard shows its Monitoring item only when this is set.
    monitoring_url: Optional[str] = None
```

In `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py`: change the schema import to `from src.auth.schemas.user import UserSelfUpdate, UserUpdate, User, UserMe`, add `from src.auth.config import settings` and `from src.auth.utils.grafana_session import MONITORING_URL`, and replace `read_user_me` with:

```python
@router.get("/me", response_model=UserMe)
def read_user_me(
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """
    Get current user. `monitoring_url` is set only for a superuser while monitoring is on (ADR-027).
    """
    me = User.model_validate(current_user, from_attributes=True)
    offered = settings.MONITORING_ENABLED and current_user.is_superuser
    return UserMe(**me.model_dump(), monitoring_url=MONITORING_URL if offered else None)
```

In `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py`: add the import

```python
from src.auth.utils.grafana_session import MONITORING_URL, clear_grafana_cookie, create_grafana_token, set_grafana_cookie
```

in `logout_user`, right after `clear_refresh_cookie(response)`:

```python
    clear_grafana_cookie(response)  # the Grafana hand-off ends with the session (ADR-027)
```

and add the endpoint after `logout_user`:

```python
@router.post("/grafana-session")
def grafana_session(response: Response, current_user: User = Depends(deps.get_current_user)):
    """Hands a QEOS superuser the qeos_grafana cookie for /grafana/ (monitoring spec §4, ADR-027).
    403 unless monitoring is on and the user is an active superuser (checked here, not by
    get_current_active_user, which answers an inactive user with 400)."""
    if not (settings.MONITORING_ENABLED and current_user.is_active and current_user.is_superuser):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Monitoring is available to superusers while it is turned on",
        )
    set_grafana_cookie(response, create_grafana_token(current_user.id))
    return {"url": MONITORING_URL}
```

- [ ] **Step 4: Run the whole auth suite**

Run: `cd platforms/auth-service/auth-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: all pass, including `test_refresh_cookie.py` (logout still clears both refresh cookies).

- [ ] **Step 5: Commit**

```bash
git add platforms/auth-service/auth-service/src/auth/utils/grafana_session.py platforms/auth-service/auth-service/src/auth/config.py platforms/auth-service/auth-service/src/auth/schemas/user.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py platforms/auth-service/auth-service/tests/integration/test_grafana_session.py
git commit -m "feat(auth): monitoring_url on /users/me and POST /auth/grafana-session for superusers; logout clears it" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/auth-service/auth-service/src/auth/utils/grafana_session.py platforms/auth-service/auth-service/src/auth/config.py platforms/auth-service/auth-service/src/auth/schemas/user.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py platforms/auth-service/auth-service/tests/integration/test_grafana_session.py
```

---

### Task 16: The internal Grafana check

**Files:**
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/internal.py`
- Create: `platforms/auth-service/auth-service/tests/integration/test_grafana_check.py`

**Interfaces:**
- Consumes: `GRAFANA_COOKIE`, `grafana_user_id`, `create_grafana_token` (Task 15).
- Produces: `GET /internal/v1/grafana-check` (Rulings 1 and 2): 200 with header `X-QEOS-User-Email: <email>` when monitoring is on and the `qeos_grafana` cookie is valid and names an existing, active superuser; 401 otherwise. No HTTP Basic. Task 17's NGINX `auth_request` calls it.

- [ ] **Step 1: Write the failing tests**

Create `platforms/auth-service/auth-service/tests/integration/test_grafana_check.py`:

```python
"""GET /internal/v1/grafana-check: NGINX's auth_request for /grafana/ (monitoring spec §4, Rulings 1-2).
The cookie is the credential; the user is re-checked on every request, so a demotion cuts access at once."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.auth.config import settings
from src.auth.models.user import User
from src.auth.utils.grafana_session import create_grafana_token
from src.auth.utils.tokens import create_access_token

CHECK = "/internal/v1/grafana-check"


@pytest.fixture
def monitoring(monkeypatch):
    monkeypatch.setattr(settings, "MONITORING_ENABLED", True)


@pytest.fixture
def superuser(db):
    row = User(email="ops@example.com", hashed_password="x", is_active=True, is_superuser=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def check(client, token):
    return client.get(CHECK, headers={"Cookie": f"qeos_grafana={token}"})


def test_a_valid_cookie_names_the_user_for_grafana(client, monitoring, superuser):
    response = check(client, create_grafana_token(superuser.id))
    assert response.status_code == 200, response.text
    assert response.headers["x-qeos-user-email"] == "ops@example.com"


def test_no_http_basic_is_needed_but_a_cookie_is(client, monitoring, superuser):
    assert client.get(CHECK).status_code == 401


def test_an_expired_cookie_is_401(client, monitoring, superuser):
    old = datetime.now(timezone.utc) - timedelta(hours=9)
    assert check(client, create_grafana_token(superuser.id, now=old)).status_code == 401


def test_a_token_for_another_audience_is_401(client, monitoring, superuser):
    other = jwt.encode({"sub": str(superuser.id), "aud": "other", "token_type": "grafana",
                        "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                       settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    assert check(client, other).status_code == 401


def test_an_access_token_planted_as_the_cookie_is_401(client, monitoring, superuser):
    """Review Focus 3."""
    assert check(client, create_access_token({"sub": str(superuser.id)})).status_code == 401


def test_a_token_signed_with_another_key_is_401(client, monitoring, superuser):
    forged = jwt.encode({"sub": str(superuser.id), "aud": "grafana", "token_type": "grafana",
                         "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "not-the-key", algorithm="HS256")
    assert check(client, forged).status_code == 401


def test_a_demoted_user_is_cut_off_at_once(client, db, monitoring, superuser):
    token = create_grafana_token(superuser.id)
    superuser.is_superuser = False
    db.commit()
    assert check(client, token).status_code == 401


def test_a_deactivated_user_is_cut_off_at_once(client, db, monitoring, superuser):
    token = create_grafana_token(superuser.id)
    superuser.is_active = False
    db.commit()
    assert check(client, token).status_code == 401


def test_a_deleted_user_is_401(client, db, monitoring, superuser):
    token = create_grafana_token(superuser.id)
    db.delete(superuser)
    db.commit()
    assert check(client, token).status_code == 401


def test_nothing_passes_while_monitoring_is_off(client, superuser):
    assert check(client, create_grafana_token(superuser.id)).status_code == 401
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/auth-service/auth-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_grafana_check.py -q`
Expected: every test FAILS: the route does not exist yet, so each answers 404.

- [ ] **Step 3: Implement**

In `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/internal.py`: change `from fastapi import APIRouter, Depends, HTTPException, status` to `from fastapi import APIRouter, Depends, HTTPException, Request, Response, status`, add `from src.auth.utils.grafana_session import GRAFANA_COOKIE, grafana_user_id`, and append:

```python
@router.get("/grafana-check")
def grafana_check(request: Request, response: Response, db: Session = Depends(get_db)):
    """NGINX auth_request for every /grafana/ request (monitoring spec §4, ADR-027).

    No HTTP Basic, unlike the other internal endpoints: the subrequest carries only the browser's
    headers, and the qeos_grafana cookie is itself the credential. It answers only who that cookie's
    own user is, and the gateway never routes /internal/. The user is re-read every time, so a
    demotion or deactivation cuts access at once."""
    user_id = grafana_user_id(request.cookies.get(GRAFANA_COOKIE)) if settings.MONITORING_ENABLED else None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active or not user.is_superuser:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in to monitoring")
    # Grafana's auth proxy signs this address in; the gateway always overwrites a client's copy
    response.headers["X-QEOS-User-Email"] = user.email
    return {"status": "ok"}
```

Also extend the module docstring's last sentence: "Second consumer: the gateway's auth_request for /grafana/ (`grafana-check`, cookie-authenticated)."

- [ ] **Step 4: Run the whole auth suite**

Run: `cd platforms/auth-service/auth-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platforms/auth-service/auth-service/src/auth/api/v1/endpoints/internal.py platforms/auth-service/auth-service/tests/integration/test_grafana_check.py
git commit -m "feat(auth): internal grafana-check for the gateway's auth_request; demotion cuts access at once" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/auth-service/auth-service/src/auth/api/v1/endpoints/internal.py platforms/auth-service/auth-service/tests/integration/test_grafana_check.py
```

---

### Task 17: The gateway's `/grafana/` location and Grafana's auth proxy

**Files:**
- Create: `gateway/grafana-on.conf`, `gateway/grafana-off.conf`
- Modify: `gateway/entrypoint.sh`, `gateway/Dockerfile`, `gateway/nginx.conf.template`
- Modify: `docker-compose.yml` (`x-auth-env`, `gateway`, `grafana`)
- Modify: `.github/workflows/ci.yml` (`gateway` job, NGINX check)

**Interfaces:**
- Consumes: `GET /internal/v1/grafana-check` (Task 16), the `grafana` service (Tasks 11 and 14), the dashboard route `/monitoring` (Task 18; the redirect works before it exists, landing on the SPA).
- Produces: with `MONITORING_ENABLED=true`: `/grafana` → 301 `/grafana/`; `/grafana/...` → `auth_request`; 401 → 302 `Location: /monitoring?next=<$uri>` (Ruling 4); 200 → proxied to `grafana:3000` with `X-QEOS-User-Email` set from the check. Otherwise `/grafana/` → JSON 404 (Ruling 3).

- [ ] **Step 1: The location files**

Create `gateway/grafana-off.conf`:

```nginx
# Monitoring is off (MONITORING_ENABLED is not true; ADR-027, Ruling 3): /grafana/ is a plain JSON 404
# for everyone, signed in or not.
location /grafana/ {
    add_header X-Request-ID $req_id always;
    return 404 '{"detail":"Not Found"}';
}
```

Create `gateway/grafana-on.conf`:

```nginx
# Monitoring is on (ADR-027). Every /grafana/ request is checked by auth-service first: the qeos_grafana
# cookie must belong to an active superuser. Grafana is resolved at request time, so the gateway starts
# without it (502 until it is up).

location = /grafana {
    absolute_redirect off;
    return 301 /grafana/;
}

location /grafana/ {
    # Grafana loads many assets per dashboard: a bigger burst than the API's
    limit_req zone=api burst=100 nodelay;

    auth_request /_qeos_grafana_check;
    auth_request_set $qeos_grafana_user $upstream_http_x_qeos_user_email;

    # error_page here replaces the server-level list, so the JSON pages are named again. A failed
    # check (auth-service down) is a 500 from auth_request: answered as 502 Bad Gateway
    error_page 401 = @grafana_sign_in;
    error_page 429 @too_many_requests;
    error_page 500 502 @bad_gateway;
    error_page 504 @gateway_timeout;

    # proxy_set_header here replaces the http-level list, so it is repeated in full
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Request-ID $req_id;
    # Always overwritten: a client-sent X-QEOS-User-Email never reaches Grafana's auth proxy
    proxy_set_header X-QEOS-User-Email $qeos_grafana_user;

    set $grafana_upstream http://grafana:3000;
    proxy_pass $grafana_upstream;
}

# Not signed in to monitoring: the dashboard's /monitoring page signs in if needed, hands over the cookie
# and comes back. $uri only: NGINX cannot URL-encode a query string (Ruling 4)
location @grafana_sign_in {
    absolute_redirect off;
    return 302 /monitoring?next=$uri;
}

location = /_qeos_grafana_check {
    internal;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Request-ID $req_id;
    # The cookie is the credential; a bearer token has no business here
    proxy_set_header Authorization "";
    set $auth_upstream http://auth-service:8000;
    proxy_pass $auth_upstream/internal/v1/grafana-check;
}
```

- [ ] **Step 2: Include them**

In `gateway/nginx.conf.template`, inside the `listen 443` server, immediately before `# ---- unknown API paths ----`, add:

```nginx
        # ---- Grafana (monitoring profile, ADR-027): grafana-on.conf or grafana-off.conf, chosen by
        # entrypoint.sh from MONITORING_ENABLED ----
        include /etc/nginx/grafana.conf;

```

In `gateway/Dockerfile`, after `COPY nginx.conf.template /etc/qeos/nginx.conf.template`:

```dockerfile
COPY grafana-on.conf grafana-off.conf /etc/qeos/
```

In `gateway/entrypoint.sh`, after the `envsubst` line:

```sh
# /grafana/ (ADR-027): the gated Grafana location when monitoring is on, a plain 404 when it is off.
# The same MONITORING_ENABLED value that makes auth-service offer the Monitoring item.
: "${MONITORING_ENABLED:=false}"
case "$MONITORING_ENABLED" in
  true|True|TRUE|1|yes) cp /etc/qeos/grafana-on.conf /etc/nginx/grafana.conf ;;
  *) cp /etc/qeos/grafana-off.conf /etc/nginx/grafana.conf ;;
esac
```

- [ ] **Step 3: NGINX accepts both, and the CI check covers both**

```bash
docker build -t qa-vision/gateway:ci gateway
docker run --rm qa-vision/gateway:ci nginx -t
docker run --rm -e MONITORING_ENABLED=true qa-vision/gateway:ci nginx -t
```
Expected: `test is successful` twice.

In `.github/workflows/ci.yml`, job `gateway`, step "Check the NGINX configuration", replace the `run:` block with:

```yaml
        run: |
          docker build -t qa-vision/gateway:ci gateway
          docker run --rm qa-vision/gateway:ci nginx -t
          # The gated /grafana/ location (ADR-027)
          docker run --rm -e MONITORING_ENABLED=true qa-vision/gateway:ci nginx -t
```

- [ ] **Step 4: Compose wiring**

In `docker-compose.yml`:
- `x-auth-env`: add `MONITORING_ENABLED: ${MONITORING_ENABLED:-false}` with the comment `# Offer Grafana to superusers (ADR-027); set with COMPOSE_PROFILES=monitoring`.
- `gateway` → `environment`: add `MONITORING_ENABLED: ${MONITORING_ENABLED:-false}` with the comment `# /grafana/ gated by auth-service when true, a 404 otherwise (ADR-027)`.
- `grafana` → `environment`: add

```yaml
      # Signed in by the gateway (ADR-027): it sets this header from auth-service's check and always
      # overwrites a client's. A user is created on first visit, as an Admin of the main organization
      GF_AUTH_PROXY_ENABLED: "true"
      GF_AUTH_PROXY_HEADER_NAME: X-QEOS-User-Email
      GF_AUTH_PROXY_HEADER_PROPERTY: email
      GF_AUTH_PROXY_AUTO_SIGN_UP: "true"
      GF_USERS_AUTO_ASSIGN_ORG_ROLE: Admin
```

- [ ] **Step 5: The gate on a running stack**

```bash
export SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret
docker compose up -d --build --wait gateway
curl -ks -o /dev/null -w '%{http_code}\n' https://localhost:8443/grafana/
export COMPOSE_PROFILES=monitoring MONITORING_ENABLED=true GRAFANA_ADMIN_PASSWORD=local-grafana MONITORING_DB_PASSWORD=local-monitor
docker compose up -d --build --wait --wait-timeout 300 gateway prometheus alertmanager grafana node-exporter cadvisor postgres-exporter
curl -ks -D - -o /dev/null https://localhost:8443/grafana/d/qeos-overview | grep -iE '^(HTTP|location)'
curl -ks -o /dev/null -w '%{http_code}\n' -H 'X-QEOS-User-Email: attacker@example.com' https://localhost:8443/grafana/api/user
```
Expected: `404`; then `HTTP/1.1 302` with `location: /monitoring?next=/grafana/d/qeos-overview`; then `302`. (The signed-in path is pinned by the smoke checks in Task 19.)

- [ ] **Step 6: Commit**

```bash
git add gateway/grafana-on.conf gateway/grafana-off.conf gateway/entrypoint.sh gateway/Dockerfile gateway/nginx.conf.template docker-compose.yml .github/workflows/ci.yml
git commit -m "feat(gateway): /grafana/ behind auth_request with the user header overwritten; 404 when monitoring is off" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- gateway/grafana-on.conf gateway/grafana-off.conf gateway/entrypoint.sh gateway/Dockerfile gateway/nginx.conf.template docker-compose.yml .github/workflows/ci.yml
```

---

### Task 18: The dashboard's Monitoring item and `/monitoring` hand-off page

**Before editing any `.tsx` or `.css` file, invoke the `ui-ux-pro-max` skill** (user rule) and apply what it says to this small change: one menu item, one short status page, an inline error.

**Files:**
- Create: `dashboard/src/lib/browser.ts`
- Modify: `dashboard/src/api/auth.ts` (`getMe` type, `startGrafanaSession`)
- Modify: `dashboard/src/components/UserMenu.tsx`
- Modify: `dashboard/src/index.css` (one rule next to the `.user-menu-*` rules)
- Create: `dashboard/src/pages/MonitoringPage.tsx`
- Modify: `dashboard/src/App.tsx` (route)
- Create: `dashboard/src/components/UserMenu.test.tsx`, `dashboard/src/pages/MonitoringPage.test.tsx`
- Modify: `dashboard/src/pageHeadings.test.tsx` (one route row)

Another session may be editing dashboard files: re-read each file right before editing it.

**Interfaces:**
- Consumes: `GET /api/v1/users/me` → `monitoring_url` and `POST /api/v1/auth/grafana-session` → `{url}` (Task 15); the gateway's redirect to `/monitoring?next=` (Task 17).
- Produces: `goTo(url: string): void` (`src/lib/browser.ts`, mockable); `startGrafanaSession(): Promise<string>` (`src/api/auth.ts`); `MonitoringPage` (default export) and `grafanaPath(raw: string | null): string` (named export) in `src/pages/MonitoringPage.tsx`; route `/monitoring` inside `RequireAuth`.

- [ ] **Step 1: Write the failing tests**

Create `dashboard/src/components/UserMenu.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, test, vi } from "vitest";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { goTo } from "../lib/browser";
import UserMenu from "./UserMenu";

vi.mock("../lib/browser", () => ({ goTo: vi.fn() }));

function renderMenu(me: Record<string, unknown>) {
  setAccessToken("acc");
  server.use(
    http.get("/api/v1/users/me", () =>
      HttpResponse.json({ id: 1, email: "ops@example.com", mfa_enabled: false, ...me }),
    ),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UserMenu />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openMenu(): Promise<HTMLElement> {
  await userEvent.click(await screen.findByRole("button", { name: "Account menu for ops@example.com" }));
  return document.getElementById("user-menu-popup")!;
}

function items(popup: HTMLElement): (string | undefined)[] {
  return within(popup).getAllByRole("listitem").map((li) => li.textContent?.trim());
}

afterEach(() => vi.mocked(goTo).mockReset());

describe("Monitoring item", () => {
  test("is hidden without monitoring_url", async () => {
    renderMenu({ monitoring_url: null });
    const popup = await openMenu();
    expect(within(popup).queryByRole("button", { name: "Monitoring" })).toBeNull();
    expect(items(popup)).toEqual(["Security", "Sign out"]);
  });

  test("shows before Sign out; a click hands over the Grafana cookie, then opens Grafana", async () => {
    let posted = false;
    server.use(
      http.post("/api/v1/auth/grafana-session", () => {
        posted = true;
        return HttpResponse.json({ url: "/grafana/" });
      }),
    );
    renderMenu({ monitoring_url: "/grafana/" });
    const popup = await openMenu();
    expect(items(popup)).toEqual(["Security", "Monitoring", "Sign out"]);
    await userEvent.click(within(popup).getByRole("button", { name: "Monitoring" }));
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/"));
    expect(posted).toBe(true);
  });

  test("a refusal is shown in the menu and nothing opens", async () => {
    server.use(
      http.post("/api/v1/auth/grafana-session", () =>
        HttpResponse.json({ detail: "Monitoring is available to superusers while it is turned on" }, { status: 403 }),
      ),
    );
    renderMenu({ monitoring_url: "/grafana/" });
    const popup = await openMenu();
    await userEvent.click(within(popup).getByRole("button", { name: "Monitoring" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Monitoring is available to superusers while it is turned on");
    expect(goTo).not.toHaveBeenCalled();
  });
});
```

Create `dashboard/src/pages/MonitoringPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, test, vi } from "vitest";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { goTo } from "../lib/browser";
import MonitoringPage, { grafanaPath } from "./MonitoringPage";

vi.mock("../lib/browser", () => ({ goTo: vi.fn() }));

function renderAt(path: string) {
  setAccessToken("acc");
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/monitoring" element={<MonitoringPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => vi.mocked(goTo).mockReset());

describe("MonitoringPage", () => {
  test("hands over the cookie, then opens the Grafana page the visitor came from", async () => {
    server.use(http.post("/api/v1/auth/grafana-session", () => HttpResponse.json({ url: "/grafana/" })));
    renderAt("/monitoring?next=/grafana/d/qeos-postgresql/postgresql");
    expect(screen.getByRole("heading", { level: 1, name: "Monitoring" })).toBeInTheDocument();
    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith("/grafana/d/qeos-postgresql/postgresql"));
    expect(goTo).toHaveBeenCalledTimes(1);
  });

  test("a refusal is shown and nothing opens", async () => {
    server.use(
      http.post("/api/v1/auth/grafana-session", () =>
        HttpResponse.json({ detail: "Monitoring is available to superusers while it is turned on" }, { status: 403 }),
      ),
    );
    renderAt("/monitoring");
    expect(await screen.findByRole("alert")).toHaveTextContent("Monitoring is available to superusers while it is turned on");
    expect(goTo).not.toHaveBeenCalled();
  });
});

describe("grafanaPath", () => {
  test.each([
    [null, "/grafana/"],
    ["/grafana/d/qeos-overview", "/grafana/d/qeos-overview"],
    ["/projects/1", "/grafana/"],
    ["//evil.example/grafana/", "/grafana/"],
    ["https://evil.example/grafana/", "/grafana/"],
    ["/grafana/\t/x", "/grafana/"],
  ])("%s -> %s", (raw, expected) => {
    expect(grafanaPath(raw)).toBe(expected);
  });
});
```

In `dashboard/src/pageHeadings.test.tsx`, add to `ROUTES` after `["/account/security", "Security"],`:

```tsx
  ["/monitoring", "Monitoring"],
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd dashboard && npx vitest run src/components/UserMenu.test.tsx src/pages/MonitoringPage.test.tsx src/pageHeadings.test.tsx`
Expected: FAIL: cannot resolve `../lib/browser` and `./MonitoringPage`.

- [ ] **Step 3: Implement**

Create `dashboard/src/lib/browser.ts`:

```ts
/** Leaves the single-page app for a page the server answers (Grafana under /grafana/). Its own module so
 *  tests can mock it: jsdom cannot navigate. */
export function goTo(url: string): void {
  window.location.assign(url);
}
```

In `dashboard/src/api/auth.ts`, replace `getMe` and add `startGrafanaSession` after it:

```ts
/** The signed-in account; `mfa_enabled` says whether two-factor sign-in is on, and `monitoring_url` is set
 *  only for a superuser while monitoring is on (ADR-027). */
export function getMe(): Promise<{ id: number; email: string; mfa_enabled: boolean; monitoring_url?: string | null }> {
  return apiFetch("/api/v1/users/me");
}

/** Hands over the qeos_grafana cookie (8 hours, /grafana only); resolves to where Grafana lives. */
export async function startGrafanaSession(): Promise<string> {
  const body = await apiFetch<{ url: string }>("/api/v1/auth/grafana-session", { method: "POST", body: "{}" });
  return body.url;
}
```

In `dashboard/src/components/UserMenu.tsx`:
- imports: `import { Activity, Building2, LogOut, ShieldCheck } from "lucide-react";`, `import { getMe, logout, startGrafanaSession } from "../api/auth";`, `import { ApiError } from "../api/http";`, `import { goTo } from "../lib/browser";`.
- the component's doc comment: "...who is signed in, Security, Organization, Monitoring (superusers, while it is on) and Sign out."
- after `const email = me.data?.email;` add:

```tsx
  const monitoringUrl = me.data?.monitoring_url ?? null;
  const [monitoringError, setMonitoringError] = useState<string | null>(null);
```

- after `onSignOut` add:

```tsx
  // Grafana is outside the SPA: hand over its cookie first, then leave (ADR-027)
  async function onMonitoring() {
    setMonitoringError(null);
    try {
      const url = await startGrafanaSession();
      setOpen(false);
      goTo(url);
    } catch (error) {
      setMonitoringError(error instanceof ApiError ? error.detail : "Monitoring could not be opened.");
    }
  }
```

- in the list, between the Organization item and `<li className="menu-signout">`:

```tsx
            {monitoringUrl && (
              <li>
                <button type="button" className="menu-item" onClick={onMonitoring}>
                  <Activity size={16} aria-hidden="true" /> Monitoring
                </button>
                {monitoringError && (
                  <p className="field-error user-menu-error" role="alert">
                    {monitoringError}
                  </p>
                )}
              </li>
            )}
```

In `dashboard/src/index.css`, after the `.user-menu-list { ... }` rule:

```css
.user-menu-error { padding: var(--space-1) var(--space-3); }
```

Create `dashboard/src/pages/MonitoringPage.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import ErrorBanner from "../components/ErrorBanner";
import { startGrafanaSession } from "../api/auth";
import { safeNext } from "../auth/redirect";
import { goTo } from "../lib/browser";

/** Where `next` may lead: a same-site path inside Grafana, else Grafana's home. */
export function grafanaPath(raw: string | null): string {
  const safe = safeNext(raw);
  return safe !== null && safe.startsWith("/grafana/") ? safe : "/grafana/";
}

/** Where the gateway sends a visitor whose Grafana cookie is missing or expired (ADR-027): signed in by
 *  RequireAuth, it hands over the cookie and opens the Grafana page they were going to. */
export default function MonitoringPage() {
  const [params] = useSearchParams();
  const next = grafanaPath(params.get("next"));
  const [error, setError] = useState<unknown>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice; one hand-off is enough
    started.current = true;
    startGrafanaSession().then(() => goTo(next), setError);
  }, [next]);

  return (
    <>
      <PageHeader title="Monitoring" subtitle="Grafana dashboards and alerts for this QEOS install" />
      {error ? <ErrorBanner error={error} /> : <p className="muted" role="status">Opening Grafana…</p>}
    </>
  );
}
```

In `dashboard/src/App.tsx`, add `import MonitoringPage from "./pages/MonitoringPage";` and, after `<Route path="/account/security" element={<SecurityPage />} />`:

```tsx
          <Route path="/monitoring" element={<MonitoringPage />} />
```

- [ ] **Step 4: Run the dashboard checks**

Run: `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build`
Expected: all green, including `AppShell.test.tsx`'s user-menu tests (the default `/users/me` mock has no `monitoring_url`, so their item lists are unchanged).

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/lib/browser.ts dashboard/src/api/auth.ts dashboard/src/components/UserMenu.tsx dashboard/src/index.css dashboard/src/pages/MonitoringPage.tsx dashboard/src/App.tsx dashboard/src/components/UserMenu.test.tsx dashboard/src/pages/MonitoringPage.test.tsx dashboard/src/pageHeadings.test.tsx
git commit -m "feat(dashboard): Monitoring item for superusers and the /monitoring hand-off page" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/lib/browser.ts dashboard/src/api/auth.ts dashboard/src/components/UserMenu.tsx dashboard/src/index.css dashboard/src/pages/MonitoringPage.tsx dashboard/src/App.tsx dashboard/src/components/UserMenu.test.tsx dashboard/src/pages/MonitoringPage.test.tsx dashboard/src/pageHeadings.test.tsx
```

---

### Task 19: Smoke checks, with and without the profile, in CI

**Files:**
- Modify: `scripts/smoke_gateway.sh`
- Modify: `.github/workflows/ci.yml` (`gateway` job)

**Interfaces:**
- Consumes: everything above. `MONITORING_ENABLED` and `MONITORING_DB_PASSWORD` from the caller's environment; `INVITEE_AUTH` and `SUFFIX` already defined in the script.
- Produces: smoke coverage of spec §8: without the profile `/grafana/` is 404 and public `/metrics` is the SPA (already checked); with it every Prometheus target is up, `/grafana/` without the cookie redirects to the sign-in hand-off, a superuser's cookie gets 200, and a client's own `X-QEOS-User-Email` is ignored (Review Focus 4).

- [ ] **Step 1: Add the checks**

In `scripts/smoke_gateway.sh`, extend the start-up guard: after the `for var in SECRET_KEY INTERNAL_API_PASSWORD; do ... done` loop add:

```bash
if [ "${MONITORING_ENABLED:-false}" = "true" ] && [ -z "${MONITORING_DB_PASSWORD:-}" ]; then
  echo "FAIL  MONITORING_ENABLED=true needs MONITORING_DB_PASSWORD: export the value the stack was started with"
  exit 1
fi
```

Insert this block immediately before `# ---- rate limiting last` (it uses `INVITEE_AUTH`, defined in the invitations section):

```bash
# ---- monitoring (spec 2026-10-10 §8, ADR-027) ----
if [ "${MONITORING_ENABLED:-false}" = "true" ]; then
  # Every Prometheus target up; they start as "unknown", so give them up to 90 s
  targets_up=0
  targets_other=1
  for _ in $(seq 1 18); do
    docker compose exec -T prometheus wget -qO- 'http://localhost:9090/api/v1/targets?state=active' > "$TMP/targets" 2>/dev/null || true
    targets_up="$(grep -o '"health":"up"' "$TMP/targets" | wc -l | tr -d ' ')"
    targets_other="$(grep -o '"health":"[a-z]*"' "$TMP/targets" | grep -vc '"up"' || true)"
    if [ "$targets_up" -ge 10 ] && [ "$targets_other" = "0" ]; then break; fi
    sleep 5
  done
  if [ "$targets_up" -ge 10 ] && [ "$targets_other" = "0" ]; then
    pass "every Prometheus target is up ($targets_up)"
  else
    fail "Prometheus targets: $targets_up up, $targets_other not: $(grep -o '"scrapeUrl":"[^"]*","globalUrl":"[^"]*","lastError":"[^"]*"' "$TMP/targets" | head -c 400)"
  fi

  check "/grafana/ without the cookie -> the sign-in hand-off" 302 GET "$BASE/grafana/d/qeos-overview"
  if grep -qi '^location: /monitoring?next=/grafana/d/qeos-overview' "$TMP/headers"; then
    pass "... redirects to /monitoring?next=/grafana/d/qeos-overview"
  else
    fail "... Location was: $(grep -i '^location:' "$TMP/headers")"
  fi
  check "a client's own X-QEOS-User-Email opens nothing" 302 GET "$BASE/grafana/api/user" \
    -H "X-QEOS-User-Email: attacker@example.com"
  check "a user who is not a superuser gets no Grafana cookie" 403 POST "$BASE/api/v1/auth/grafana-session" \
    "${INVITEE_AUTH[@]}" -H "Content-Type: application/json" -d '{}'

  # A superuser: inserted directly (no API promotes a user), then the normal hand-off
  SUPER_EMAIL="smoke-super-$SUFFIX@example.com"
  SUPER_ID="$(docker compose exec -T postgres psql -U postgres -d auth_db -tAc \
    "INSERT INTO users (email, is_active, is_superuser, mfa_enabled) VALUES ('$SUPER_EMAIL', true, true, false) RETURNING id" \
    | head -1 | tr -d ' \r\n')"
  SUPER_TOKEN="$(docker compose exec -T auth-service python -c '
import datetime, os, sys, jwt
exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
print(jwt.encode({"sub": sys.argv[1], "exp": exp}, os.environ["SECRET_KEY"], algorithm="HS256"))
' "$SUPER_ID" | tr -d '\r\n')"
  check "a superuser gets the Grafana cookie" 200 POST "$BASE/api/v1/auth/grafana-session" \
    -H "Authorization: Bearer $SUPER_TOKEN" -H "Content-Type: application/json" -d '{}' -c "$TMP/grafana_jar"
  check "/grafana/ with the superuser's cookie" 200 GET "$BASE/grafana/" -b "$TMP/grafana_jar"
  check "Grafana signs in the cookie's user, whatever header the client sends" 200 GET "$BASE/grafana/api/user" \
    -b "$TMP/grafana_jar" -H "X-QEOS-User-Email: attacker@example.com"
  body_has "... the superuser" "\"email\":\"$SUPER_EMAIL\""
  body_lacks "... never the client's header" "attacker@example.com"

  # qeos_monitor reads statistics, never table data
  if docker compose exec -T -e PGPASSWORD="$MONITORING_DB_PASSWORD" postgres psql -U qeos_monitor -h 127.0.0.1 \
      -d ingestion_db -tAc "SELECT 1 FROM test_runs LIMIT 1" >/dev/null 2>&1; then
    fail "qeos_monitor can read test_runs"
  else
    pass "qeos_monitor cannot read table data"
  fi
else
  check "/grafana/ is a 404 while monitoring is off" 404 GET "$BASE/grafana/"
  body_has "... the JSON 404" '{"detail":"Not Found"}'
fi
```

- [ ] **Step 2: Run it both ways**

```bash
export SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret
unset COMPOSE_PROFILES MONITORING_ENABLED
docker compose up -d --build --wait --wait-timeout 300 gateway && bash scripts/smoke_gateway.sh
export COMPOSE_PROFILES=monitoring MONITORING_ENABLED=true GRAFANA_ADMIN_PASSWORD=local-grafana MONITORING_DB_PASSWORD=local-monitor
docker compose up -d --build --wait --wait-timeout 300 gateway prometheus alertmanager grafana node-exporter cadvisor postgres-exporter && bash scripts/smoke_gateway.sh
```
Expected: both runs end with `all gateway checks passed`; the first shows `ok    /grafana/ is a 404 while monitoring is off (404)`, the second the monitoring lines.

- [ ] **Step 3: CI runs the second pass**

In `.github/workflows/ci.yml`, job `gateway`, after the step "Smoke-test through the gateway", add:

```yaml
      # The same stack with the monitoring profile: gateway and auth-service are recreated with
      # MONITORING_ENABLED, db-init re-runs and creates qeos_monitor (spec §8)
      - name: Start the monitoring profile
        env:
          COMPOSE_PROFILES: monitoring
          MONITORING_ENABLED: "true"
          GRAFANA_ADMIN_PASSWORD: ci-grafana-admin
          MONITORING_DB_PASSWORD: ci-monitor
        run: docker compose up -d --build --wait --wait-timeout 300 gateway prometheus alertmanager grafana node-exporter cadvisor postgres-exporter

      - name: Smoke-test with monitoring
        env:
          COMPOSE_PROFILES: monitoring
          MONITORING_ENABLED: "true"
          GRAFANA_ADMIN_PASSWORD: ci-grafana-admin
          MONITORING_DB_PASSWORD: ci-monitor
        run: bash scripts/smoke_gateway.sh
```

and give "Show logs on failure" and "Tear down" `env: {COMPOSE_PROFILES: monitoring}` so they include the monitoring containers.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_gateway.sh .github/workflows/ci.yml
git commit -m "test(gateway): smoke checks for /grafana/ with and without the monitoring profile" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- scripts/smoke_gateway.sh .github/workflows/ci.yml
```

---

### Task 20: ADR-027, the blueprint, TODO

**Files:**
- Create: `docs/architecture/adr/ADR-027-monitoring-profile.md`
- Modify: `docs/architecture/adr/INDEX.md`
- Modify: `ARCHITECTURE_BLUEPRINT_V1_0.md` (status banner, adoption triggers, §11)
- Modify: `TODO.md` ("Execution intelligence and operations" #1 and #2)

**Interfaces:** Consumes the built system; produces the record of it.

- [ ] **Step 1: The ADR**

Create `docs/architecture/adr/ADR-027-monitoring-profile.md`:

```markdown
# ADR-027: Monitoring is an opt-in Prometheus stack in the compose file; Grafana sits behind a QEOS cookie hand-off

Status: Accepted (2026-10-10) · Spec: `docs/superpowers/specs/2026-10-10-monitoring-design.md` · Plan: `docs/superpowers/plans/2026-10-10-monitoring.md`

## Context
QEOS runs on one VM (ADR-019). Its operator learned about an outage from users: no service exposed
metrics except ingestion's upload counters, the loop jobs had no port to scrape, and nothing alerted.
The blueprint (§11) is binding for names: `api_requests_total`, `http_requests_duration_seconds`,
`postgresql_database_size_bytes`, `postgresql_connections`, the process metrics.

## Decision
- **One shared module, every service.** `qeos_shared.metrics.install_metrics(app, service)` adds a pure
  ASGI middleware and `GET /metrics`: `api_requests_total{service, endpoint, method, status_code}`,
  `http_requests_duration_seconds`, `http_requests_in_flight`, `build_info`, the process collector.
  `endpoint` is the route template or `unmatched`; unknown methods are `other`. Ingestion keeps its
  registry and its `qav_*` names; it adds `test_executions_total{status}`, test-management
  `test_case_creation_total{type}`. One uvicorn worker per service is assumed.
- **Jobs report through a heartbeat table.** Ingestion migration 017 `job_heartbeats`; each pass of
  retention, rollup and weekly summary upserts its row (error text: one line, ≤ 500 characters,
  credentials scrubbed). Ingestion's `/metrics` reads the rows at scrape time into
  `job_last_success_timestamp_seconds{job}` / `job_last_error_timestamp_seconds{job}`; a failed read
  drops those series and counts `job_heartbeat_read_errors_total`, it never fails `/metrics`. The
  ingestion scrape uses `honor_labels` so `job` names the loop job.
- **A compose profile, not a second deployment.** `COMPOSE_PROFILES=monitoring` starts Prometheus
  v3.5.0, Alertmanager v0.28.1 (for `msteamsv2_configs`), Grafana 12.0.2, node-exporter, cAdvisor and
  postgres-exporter (role `qeos_monitor`, `pg_monitor` only), each with a memory limit (about 1.1 GB in
  all; 8 GB RAM recommended). Off, nothing changes except PostgreSQL preloading `pg_stat_statements`.
- **Alerts** in `monitoring/prometheus/alerts.yml`, unit-tested with promtool; recording rules publish
  the blueprint's PostgreSQL names. Alertmanager's config is rendered from `.env` at start; an unset
  channel (email, Slack, Teams) is left out.
- **Grafana at `/grafana/` behind the QEOS sign-in.** `/users/me` carries `monitoring_url` for
  superusers; `POST /auth/grafana-session` sets `qeos_grafana` (JWT, audience `grafana`, httpOnly,
  Secure, SameSite=Strict, `Path=/grafana`, 8 h); the gateway's `auth_request` asks
  `GET /internal/v1/grafana-check`, which re-reads the user every time (a demotion cuts access at
  once) and returns `X-QEOS-User-Email`, which the gateway always overwrites before Grafana's auth
  proxy reads it. A 401 goes to the dashboard's `/monitoring` page, which signs in if needed and hands
  the cookie over. Logout clears it. With monitoring off the gateway answers `/grafana/` with 404.
  Break-glass: Grafana's admin login on `127.0.0.1:3000` of the VM only.

## Stays TARGET (blueprint §11), each behind its trigger
| Piece | Trigger |
|---|---|
| Kubernetes service discovery, Prometheus federation | First multi-node deployment (the Kubernetes trigger) |
| Downsampling; 3-month aggregated and 3-year retention | An operator needs metrics older than `PROMETHEUS_RETENTION` (15 d), or Prometheus's disk passes `PROMETHEUS_RETENTION_SIZE` at that retention |
| Loki, with JSON logs carrying `traceId` | An incident cannot be diagnosed from `docker compose logs` (logs lost across a container recreate), or a second VM |
| OpenTelemetry tracing | A request crosses more than two services synchronously, or a latency problem cannot be placed from per-service metrics |
| `role` label on `api_requests_total` | A per-request role lookup exists (today roles come from project-service per call) |
| Metrics of Kafka, MongoDB, Redis, Elasticsearch, workflows, knowledge | Each arrives with its component |

## Alternatives rejected
- **VictoriaMetrics** instead of Prometheus: lighter, less familiar to operators; the memory budget fits Prometheus.
- **Metrics from the gateway's access log only:** no per-route, per-job or database visibility.
- **A Pushgateway for the jobs:** another container whose own staleness hides a dead job; the
  heartbeat table lives in the database the jobs already use.
- **Grafana's own login, published:** a second set of passwords and a second public login page.
  OAuth against auth-service: auth-service is not an OIDC provider.
- **`qeos_`-prefixed metric names:** the blueprint's names are binding.
- **An NGINX exporter:** `stub_status` gives connection counts only; `up == 0` and service metrics cover more.

## Consequences
- Anything on the compose network that reaches `grafana:3000` with `X-QEOS-User-Email` is signed in;
  only our own containers and the VM's loopback can.
- A deep link to Grafana from Slack or email always passes `/monitoring` once (SameSite=Strict), and
  loses its query string.
- More uvicorn workers per service need prometheus_client's multi-process mode first.
```

In `docs/architecture/adr/INDEX.md`, add after the ADR-026 row:

```markdown
| [ADR-027](ADR-027-monitoring-profile.md) | Monitoring is an opt-in Prometheus/Alertmanager/Grafana compose profile; blueprint metric names; job heartbeats in a table; Grafana behind a QEOS cookie hand-off |
```

- [ ] **Step 2: The blueprint**

In `ARCHITECTURE_BLUEPRINT_V1_0.md`:
- In the status banner table, add after the `Analytics` row:

```markdown
> | Observability (sect. 11) | CURRENT: `/metrics` on every service with §11.2 names (`api_requests_total`, `http_requests_duration_seconds`, process metrics, `test_executions_total`, `test_case_creation_total`), job heartbeats, opt-in Prometheus + Alertmanager (email/Slack/Teams) + Grafana compose profile with node, container and PostgreSQL exporters (ADR-027). Logs, tracing, profiling, synthetic checks: TARGET |
```

- In the adoption-triggers table, add:

```markdown
> | Loki (logs with `traceId`) | An incident cannot be diagnosed from `docker compose logs`, or a second VM |
> | OpenTelemetry tracing | A request crosses more than two services synchronously, or latency cannot be placed from per-service metrics |
> | Metrics downsampling / long retention | Metrics older than 15 days are needed, or Prometheus's disk passes its 5 GB cap |
```

- Directly under `## 11. Observability & Monitoring` and its first paragraph, add:

```markdown
> **As built (2026-10, ADR-027).** Metrics and alerting are CURRENT; everything else in this section
> stays TARGET behind its trigger.
>
> - **Every service** serves `/metrics` (inside the compose network only) through
>   `qeos_shared.metrics`: `api_requests_total{service, endpoint, method, status_code}`,
>   `http_requests_duration_seconds{service, endpoint, method}`, `http_requests_in_flight{service}`,
>   `build_info{service, version, commit}`, `process_cpu_seconds_total`,
>   `process_resident_memory_bytes`, `process_open_fds`. `endpoint` is the route template.
> - **Business metrics:** `test_executions_total{status}` (ingestion),
>   `test_case_creation_total{type="manual|api"}` (test-management); `"generated"` waits for the AI
>   engine. Ingestion's `qav_ingest_*` upload metrics are kept.
> - **Jobs:** `job_last_success_timestamp_seconds{job}`, `job_last_error_timestamp_seconds{job}` from the
>   `job_heartbeats` table (retention, rollup, weekly summary).
> - **Database:** `postgresql_database_size_bytes{datname}` and `postgresql_connections{state}` are
>   Prometheus recording rules over postgres-exporter.
> - **Stack:** the compose profile `monitoring` (Prometheus 15 d / 5 GB, Alertmanager, Grafana, node,
>   container and PostgreSQL exporters) on the one VM; Grafana at `/grafana/` for QEOS superusers.
> - **Alerts (11.6):** critical (service down, 5xx share, disk, PostgreSQL down) to every configured
>   channel among email, Slack and Teams; warnings (latency, jobs, rejected uploads, memory,
>   connections, database size) to Slack and Teams. Inhibition: a down service silences its 5xx and
>   latency alerts; PostgreSQL down silences the other PostgreSQL alerts. PagerDuty, SMS and webhooks
>   remain TARGET.
> - **Stays TARGET:** Kubernetes service discovery and federation (Kubernetes trigger); downsampling
>   and the 3-month / 3-year retention; Loki with JSON logs carrying `traceId` (11.1); OpenTelemetry
>   tracing (11.3); profiling (11.4); synthetic monitoring (11.5); the `role` label on
>   `api_requests_total` (needs a per-request role lookup); metrics for components that do not exist
>   yet (Kafka, MongoDB, Redis, Elasticsearch, workflows, knowledge).
```

- [ ] **Step 3: TODO.md**

In "Execution intelligence and operations", change item 1's `1. [ ]` to `1. [x]` (suite duration prediction, already shipped), and replace item 2's line with:

```markdown
2. [x] Monitoring: Prometheus, Grafana and Alertmanager as an opt-in profile of the production compose; `/metrics` on every service, Postgres and container exporters, starter dashboards and alerts (service down, 5xx rate, disk). Done 2026-10: ADR-027, spec `docs/superpowers/specs/2026-10-10-monitoring-design.md`; blueprint §11 names, job heartbeats (ingestion migration 017), five dashboards, alerts to email/Slack/Teams, Grafana at `/grafana/` for superusers
```

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/adr/ADR-027-monitoring-profile.md docs/architecture/adr/INDEX.md ARCHITECTURE_BLUEPRINT_V1_0.md TODO.md
git commit -m "docs: ADR-027 monitoring profile; blueprint §11 as built and what stays TARGET; TODO #1 and #2 done" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docs/architecture/adr/ADR-027-monitoring-profile.md docs/architecture/adr/INDEX.md ARCHITECTURE_BLUEPRINT_V1_0.md TODO.md
```

---

### Task 21: Phase 3 gate

**Files:** none new (fixes only, in the files of Tasks 14–20).

- [ ] **Step 1:** Every Python suite serially (Task 7 Step 1). Expected: all green.
- [ ] **Step 2:** `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build && node --test ../templates/github/qeos-run.test.mjs`. Expected: all green.
- [ ] **Step 3:** `bash monitoring/check.sh`. Expected: `monitoring: all checks passed`.
- [ ] **Step 4:** Both NGINX checks (Task 17 Step 3) and both smoke runs (Task 19 Step 2). Expected: `test is successful` twice; `all gateway checks passed` twice.
- [ ] **Step 5:** By hand, in a browser at `https://localhost:8443`: sign in as a superuser (promote one with `docker compose exec -T postgres psql -U postgres -d auth_db -c "UPDATE users SET is_superuser = true WHERE email = '<you>'"`), open the account menu → Monitoring, land on the QEOS overview dashboard; sign out, open `https://localhost:8443/grafana/` again and see the sign-in page, then Grafana after signing in.
- [ ] **Step 6:** `docker compose down` (never `-v`). Tell the user Phase 3 is ready to push. Do not push.

---

## Self-review

**Spec coverage.**
§1 goal and opt-in → Tasks 11, 13 (profile off changes nothing). §2 six containers, limits, healthchecks, restart, pinned tags, 8 GB note → Tasks 11, 12. §3 `install_metrics` and the metric table (as amended to blueprint names), route templates, `unmatched`, no identifiers, `/metrics` not routed, one worker → Tasks 1–3, 7; process collector and business metrics → Tasks 1–3; heartbeats, migration 017, upsert, gauges surviving DB failure → Tasks 4–6; uploads panels → Task 14. §4 sign-in gate steps 1–7 and break-glass, profile off → Tasks 15, 16, 17, 18, 11 (Rulings 1–4). §5 alerts and delivery, inhibition, channels, Watchdog, dead-man's switch documented → Tasks 8, 9, 12 (Rulings 6, 9, 11, 12). §6 five dashboards → Task 14. §7 volumes, `qeos_monitor`, new `.env` values, `init-env.sh` → Tasks 10, 11, 12. §8 every test listed → Tasks 1–6, 8, 9, 14–19. §9 three phases with gates → Tasks 7, 13, 21; ADR, blueprint, TODO → Task 20. Amendment: blueprint names, process collector, business metrics, recording rules with promtool tests, TARGET list → Global Constraints, Tasks 1–3, 8, 20. §10 out of scope: nothing built for it.

**Placeholder scan.** No TBD/TODO/"similar to". Four steps carry an explicit fallback with the exact action, because they depend on third-party images that cannot be verified offline: a missing image tag (Task 11 Step 1), cAdvisor without `privileged` (Task 11 Step 5), postgres-exporter metric names (Task 14 Step 6), and Grafana's healthcheck tool (Task 11 Step 5: if `docker compose ps grafana` stays unhealthy with `wget: not found`, use `curl -fsS` in the same command).

**Type consistency.** `install_metrics(app, service, registry=None, *, version, commit)` is used the same way in Tasks 2, 3. `metrics.REGISTRY`, `metrics.EXECUTIONS`, `metrics.HEARTBEAT_READ_ERRORS` (Task 3) are what Task 6 uses. `heartbeat.record_success/record_error(session_factory, job, ...)` and `JOB` constants (Tasks 4, 5) match the tests. `HEARTBEATS.session_factory` (Task 6) matches the conftest change. `grafana_user_id`, `create_grafana_token(user_id, now=None)`, `GRAFANA_COOKIE`, `MONITORING_URL` (Task 15) match Task 16. `startGrafanaSession`, `goTo`, `grafanaPath` (Task 18) match its tests. Metric names in rules, tests and dashboards match the Global Constraints; `check_dashboards.py` rejects the retired `qeos_` names.

**Review Focus.** 1 → Task 1 `test_an_unknown_method_is_counted_as_other`, `test_a_path_that_matches_no_route_is_unmatched`. 2 → Task 4 `test_credentials_in_a_url_are_replaced`, `test_the_stored_error_never_holds_a_password`, Task 5 retention password test. 3 → Task 15 `test_the_grafana_token_is_not_an_access_token`, Task 16 `test_an_access_token_planted_as_the_cookie_is_401`. 4 → Task 19 smoke. 5 → Task 9 `tricky` render.

