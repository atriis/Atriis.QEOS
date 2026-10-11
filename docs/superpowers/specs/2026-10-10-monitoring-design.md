# Monitoring: Prometheus, Grafana and Alertmanager — design

Date: 2026-10-10. Status: approved in conversation, awaiting written-spec review.
TODO: "Execution intelligence and operations" #2. Blueprint §11 (Observability & Monitoring).

## 1. Goal

Whoever operates a QEOS install learns that it is down or unhealthy before its users do, and can
see why. A crashed service, a burst of 5xx errors, slow requests, a stuck background job, rejected
collector uploads, a filling disk, memory pressure or a PostgreSQL problem raises an alert by
email, Slack or Microsoft Teams; Grafana shows the health of every service, the jobs, PostgreSQL
and the host.

Monitoring is **opt-in**: a small install that does not turn it on runs exactly as today.

Audience: the operator of the VM (a QEOS superuser), not QEOS's end users.

### Decisions taken with the user

| Question | Decision |
|---|---|
| Stack | Prometheus + Alertmanager + Grafana as a Docker Compose profile (approach A). Rejected: VictoriaMetrics (B, lighter but less familiar), gateway-log metrics only (C, no per-route or job visibility). |
| Alert channels | Email, Slack, Microsoft Teams; each turns on when its settings are present. |
| Grafana address | A path under the QEOS domain: `https://<domain>/grafana/`, through the gateway. |
| Grafana sign-in | Both: QEOS sign-in (superusers only) in front, plus a break-glass Grafana admin login reachable only through an SSH tunnel. |
| Scope beyond service-down / 5xx / disk | Request latency per service, PostgreSQL health, QEOS jobs and uploads, host and container resources. |

## 2. Components

Profile `monitoring` in the main `docker-compose.yml` (one definition for development and
production). Production turns it on with `COMPOSE_PROFILES=monitoring` in `.env`.

| Container | Role | Memory limit |
|---|---|---|
| `prometheus` | Scrapes every 15 s, evaluates alert rules, keeps `PROMETHEUS_RETENTION` (default `15d`) capped by `PROMETHEUS_RETENTION_SIZE` (default `5GB`) | 512 MB |
| `alertmanager` | Groups, inhibits and delivers alerts. Version ≥ 0.28 (for `msteamsv2_configs`) | 64 MB |
| `grafana` | Dashboards at `/grafana/` (`GF_SERVER_ROOT_URL=.../grafana/`, `GF_SERVER_SERVE_FROM_SUB_PATH=true`) | 256 MB |
| `node-exporter` | VM CPU, memory, disk, network | 64 MB |
| `cadvisor` | Per-container CPU, memory, restarts; `--housekeeping_interval=30s`, unused metric groups disabled | 128 MB |
| `postgres-exporter` | Connections, database sizes, transactions, cache hit rate, locks, slow statements, via role `qeos_monitor` | 64 MB |

All are on the internal network, none publishes a port to the internet, each has a healthcheck and
`restart: unless-stopped`. Image versions are pinned to exact tags. Total budget about 1.1 GB at the
limits; `deploy/README.md` recommends **8 GB RAM** when monitoring is on (4 GB stays fine without it).

Not included (YAGNI): an NGINX exporter (stub_status gives connection counts only; services' own
metrics cover 5xx and latency, and `up == 0` covers a service the gateway cannot reach), Loki/logs,
tracing, an external dead-man's switch (documented as an option, see §5).

## 3. Service metrics (`qeos_shared.metrics`)

Every service already installs `qeos_shared`. A new module `shared/qeos_shared/metrics.py` gives
each service one call: `install_metrics(app, service="project", registry=None)`, which adds a
middleware and `GET /metrics` on the service's registry. Ingestion passes its existing registry, so
its `qav_*` metrics stay as they are (renaming would break any dashboard built on them).

Names and labels follow blueprint §11.2 (no prefix; `service` added so one Prometheus tells the
services apart):

| Metric | Type | Labels |
|---|---|---|
| `api_requests_total` | counter | `service`, `endpoint`, `method`, `status_code` (the exact code) |
| `http_requests_duration_seconds` | histogram | `service`, `endpoint`, `method`; buckets 0.01 … 30 s, so report calls near the 20 s statement timeout are visible (the blueprint's spelling, "requests") |
| `http_requests_in_flight` | gauge | `service` |
| `build_info` | gauge, always 1 | `service`, `version`, `commit` |
| `process_cpu_seconds_total`, `process_resident_memory_bytes`, `process_open_fds` | prometheus_client's `ProcessCollector` on each service's registry | — |

Business metrics from blueprint §11.2:
- ingestion: `test_executions_total{status}`, one per stored result, `status` one of `passed`,
  `failed`, `errored`, `skipped` (all four pre-created);
- test-management: `test_case_creation_total{type}`, `type="manual"` for a case a person creates
  through the UI or API and `type="api"` for Gherkin import and sync (both pre-created). The
  blueprint's `"generated"` arrives with the AI engine.

Rules:
- `endpoint` is the matched route template (e.g. `/api/v1/projects/{project_id}/cases/{number}`),
  never the raw path; a request that matches no route is `endpoint="unmatched"`, so scanners cannot
  create series. `/metrics` and `/health` are not counted.
- No metric carries a user, organisation, project, test or case identifier.
- `/metrics` stays inside the Docker network; the gateway keeps not routing it (a smoke check pins
  that the public `/metrics` serves the SPA, not metrics).
- Services run one uvicorn worker. If a service ever gets more workers, `prometheus_client`'s
  multi-process mode becomes necessary; the module's docstring says so.

### Job heartbeats

The loop jobs (`retention`, `rollup`, `weekly_summary`) have no HTTP port. Ingestion migration
**017** adds `job_heartbeats (job varchar PK, last_success_at timestamptz, last_error_at timestamptz,
last_error text)`. After each pass a job upserts its row: success time, or error time and a short
error text (first line, at most 500 characters, no secrets).

Ingestion's `/metrics` reads the three rows on each scrape and exposes
`job_last_success_timestamp_seconds{job}` and `job_last_error_timestamp_seconds{job}`. If
the read fails, `/metrics` still answers: the job series are left out and
`job_heartbeat_read_errors_total` goes up, so a database blip cannot make ingestion look down.

### Uploads

The existing `qav_ingest_runs`, `qav_ingest_results`, `qav_ingest_rejected{reason}` and
`qav_ingest_duration_seconds` already cover collector uploads; they get dashboard panels.

## 4. Grafana sign-in gate

The QEOS session cannot gate a plain browser visit: the refresh cookie is scoped to
`/api/v1/auth` and the access token lives in the dashboard's memory. So a short-lived cookie for
Grafana is handed over explicitly:

1. `GET /api/v1/users/me` gains `monitoring_url`: `"/grafana/"` when `MONITORING_ENABLED=true` in
   auth-service and the user is a superuser, otherwise `null`. The dashboard's account menu shows a
   **Monitoring** item only when it is set.
2. Clicking it calls `POST /api/v1/auth/grafana-session` with the normal access token. 403 unless
   the user is an active superuser and monitoring is enabled.
3. The response sets `qeos_grafana`: httpOnly, Secure, SameSite=Strict, `Path=/grafana`, 8 hours,
   a signed token (JWT with its own audience `grafana`) naming the user. The browser then opens
   `/grafana/`.
4. For every `/grafana/` request NGINX runs `auth_request` against an `internal` location that
   proxies to a new auth-service endpoint `GET /api/v1/internal/grafana-check`. It checks the
   cookie's signature, expiry and audience, and that the user still exists, is active and is still a
   superuser (so a demotion cuts access at once). 200 with `X-QEOS-User-Email`, otherwise 401.
5. 401 → NGINX redirects to the QEOS sign-in page with a return path to `/grafana/`.
6. Grafana uses its auth proxy (`GF_AUTH_PROXY_ENABLED=true`, header `X-QEOS-User-Email`,
   auto-sign-up, role Admin). The gateway always overwrites that header, so a client cannot send it.
7. QEOS logout also clears `qeos_grafana` (`Path=/grafana`).

Break-glass: Grafana's own admin login (`GRAFANA_ADMIN_PASSWORD`) is reachable only on
`127.0.0.1:3000` of the VM (`ssh -L 3000:127.0.0.1:3000 <vm>`), for when auth-service is down.

Profile off: the gateway still starts (Grafana is resolved at request time) and answers `/grafana/`
with 404; `monitoring_url` is `null`, so no link leads there.

## 5. Alerts

Rules in `monitoring/prometheus/alerts.yml`:

| Alert | Fires when | Severity |
|---|---|---|
| `ServiceDown` | `up == 0` for a target for 2 min | critical |
| `High5xxRate` | a service's 5xx share > 5 % for 5 min, with ≥ 20 requests in the window | critical |
| `SlowRequests` | a service's p95 > 2 s for 10 min; routes under `/analytics/report` use 10 s | warning |
| `JobStale` | last success older than 2× the job's interval (retention 2 d, rollup 12 h, weekly summary 1 h: plan Ruling 6, the job passes every 30 min) | warning |
| `JobFailing` | last error newer than last success, for 30 min | warning |
| `UploadsRejected` | rejected uploads > 25 % of uploads for 15 min (with ≥ 10 uploads) | warning |
| `DiskFillingUp` | VM disk > 85 % used, or predicted full within 24 h | critical |
| `MemoryPressure` | VM memory available < 10 % for 10 min, or a container restarted > 3 times in 15 min (`changes(container_start_time_seconds[15m])`, cAdvisor has no restart counter) | warning |
| `CadvisorNoContainers` | cAdvisor is up but reports no compose container for 10 min (a socket mount is missing or wrong; added 2026-10-11) | warning |
| `PostgresDown` | the exporter cannot reach PostgreSQL for 2 min | critical |
| `PostgresTooManyConnections` | connections > 80 % of `max_connections` for 5 min | warning |
| `PostgresDatabaseGrowing` | a database larger than `POSTGRES_DB_SIZE_ALERT_GB` (default 20) | warning |
| `Watchdog` | always firing; proves the pipeline; routed nowhere by default | none |

Delivery (`monitoring/alertmanager/alertmanager.yml.template`, rendered from `.env` at start):
- group by `alertname` and `service`; `group_wait` 30 s; `repeat_interval` 4 h;
- `critical` → every configured channel; `warning` → Slack and Teams only (email if it is the only
  channel configured);
- inhibition: `ServiceDown` for a service silences `High5xxRate` and `SlowRequests` for it;
  `PostgresDown` silences the other Postgres alerts;
- channels: email when `ALERT_EMAIL_TO` is set (reuses `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
  `SMTP_PASSWORD`, `SMTP_TLS`, `EMAILS_FROM_EMAIL`); Slack when `ALERT_SLACK_WEBHOOK_URL` is set;
  Teams when `ALERT_TEAMS_WEBHOOK_URL` is set. An unset channel is left out of the rendered file, so
  a missing value never breaks start-up. With no channel set, alerts are visible in Grafana only.
- An external dead-man's switch (e.g. a hosted heartbeat receiving `Watchdog`) is documented as an
  option, not built.

### Database metric names

postgres-exporter publishes `pg_*` names. Prometheus recording rules (`monitoring/prometheus/recording.yml`)
publish the blueprint's names, and dashboards and alerts use those:
`postgresql_database_size_bytes{datname}` from `pg_database_size_bytes`, and
`postgresql_connections{state}` from `pg_stat_activity_count`. promtool tests cover them.

## 6. Dashboards

Provisioned read-only from `monitoring/grafana/dashboards/` with the Prometheus data source from
`monitoring/grafana/provisioning/`:

1. **QEOS overview** — per service: up, request rate, 5xx share, p95; deployed version; firing alerts.
2. **Service detail** — service picker; per route: rate, p50/p95/p99, status codes.
3. **Jobs and uploads** — time since each job's last success and last error; uploads accepted and
   rejected by reason; results stored per hour; upload handling time.
4. **PostgreSQL** — connections, database sizes, transactions per second, cache hit rate, locks,
   slowest statements.
5. **Host and containers** — VM CPU, memory, disk (with trend); per container CPU, memory, restarts.

## 7. Data, roles and secrets

- Volumes `prometheus-data`, `grafana-data`. Grafana needs no backup (everything is provisioned
  from the repo); `deploy/backup.sh` is unchanged.
- PostgreSQL role `qeos_monitor` with `pg_monitor` only (cannot read table data), created by
  `scripts/postgres-init.sh` for new installs and by an idempotent step for existing ones.
- New `.env` values: `COMPOSE_PROFILES`, `MONITORING_ENABLED`, `GRAFANA_ADMIN_PASSWORD`,
  `MONITORING_DB_PASSWORD`, `PROMETHEUS_RETENTION`, `PROMETHEUS_RETENTION_SIZE`,
  `POSTGRES_DB_SIZE_ALERT_GB`, `ALERT_EMAIL_TO`, `ALERT_SLACK_WEBHOOK_URL`,
  `ALERT_TEAMS_WEBHOOK_URL`. `deploy/init-env.sh` generates the two passwords.

## 8. Testing

- `qeos_shared.metrics`: pytest for endpoint templating, `unmatched`, exact status codes, process metrics, `/metrics`
  and `/health` not counted, in-flight gauge returns to 0, build info.
- Each service: a test that `/metrics` answers and carries `api_requests_total`; ingestion `test_executions_total`, test-management `test_case_creation_total`.
- Heartbeats: migration test (017 up/down); each job upserts on success and on error; `/metrics`
  survives a failing heartbeat read.
- Auth: `grafana-session` (403 for non-superusers and when disabled; cookie attributes), the
  internal check (valid, expired, wrong audience, demoted, inactive), logout clears the cookie,
  `monitoring_url` in `/users/me`.
- Dashboard: the Monitoring item shows only with `monitoring_url`; clicking calls the endpoint then
  navigates.
- CI: `promtool check rules` and `promtool test rules` (unit tests per alert with synthetic series),
  `amtool check-config` on a rendered template, Grafana dashboard JSON lint.
- Smoke (`scripts/smoke_gateway.sh`): without the profile, `/grafana/` is 404 and public `/metrics`
  is the SPA; with the profile, every Prometheus target is up, `/grafana/` without the cookie
  redirects to sign-in, and with a superuser's cookie returns 200.

## 9. Delivery order

Each phase ships on its own.

1. **Metrics everywhere** — `qeos_shared.metrics` on all five services, job heartbeats (migration
   017), tests. Useful by itself: any Prometheus can scrape QEOS.
2. **The stack** — the profile, Prometheus and exporters, `qeos_monitor`, alert rules with promtool
   tests, Alertmanager rendering and delivery, `deploy/README.md` and `docs/SETUP.md`.
3. **Grafana** — Grafana and dashboards, the sign-in gate (endpoints, gateway location, Monitoring
   item), smoke checks, a new ADR (Prometheus stack as a profile, cookie handoff, heartbeat table,
   rejected approaches), blueprint §11 updated to what was built, TODO #1 and #2 checked off.

## 10. Blueprint §11: what this builds and what stays target

Built: Prometheus collection, the §11.2 metric types and names listed above, about 2 weeks raw
retention (§11.2: "2 weeks raw"), Alertmanager with inhibition, routing and silencing, Grafana.

Stays TARGET (each behind its blueprint trigger, recorded in the ADR and the §11 status note):
Kubernetes service discovery and Prometheus federation (trigger: first multi-node deployment);
downsampling and the 3-month / 3-year retention tiers; the logs pillar (Loki, JSON logs carrying
`traceId`); the tracing pillar (OpenTelemetry, Tempo/Jaeger); the `role` label on
`api_requests_total` (needs a per-request organisation-role lookup); metrics for components that do
not exist yet (Kafka, MongoDB, Redis, Elasticsearch, workflows, knowledge items).

## 11. Out of scope

Logs (Loki), tracing, profiling, multi-VM federation, per-organisation monitoring views, an
external dead-man's switch, SLO dashboards. Kubernetes stays out until its blueprint trigger fires.
