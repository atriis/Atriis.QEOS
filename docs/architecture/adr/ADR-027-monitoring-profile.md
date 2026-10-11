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
  `test_case_creation_total{type}`. One uvicorn worker per service is assumed. `/metrics` is never
  routed by the gateway.
- **Jobs report through a heartbeat table.** Ingestion migration 017 `job_heartbeats`; each pass of
  retention, rollup and weekly summary upserts its row (error text: one line, at most 500 characters,
  credentials scrubbed). Ingestion's `/metrics` reads the rows at scrape time into
  `job_last_success_timestamp_seconds{job}` / `job_last_error_timestamp_seconds{job}`; a failed read
  drops those series and counts `job_heartbeat_read_errors_total`, it never fails `/metrics`. The
  ingestion scrape uses `honor_labels` so `job` names the loop job.
- **A compose profile, not a second deployment.** `COMPOSE_PROFILES=monitoring` starts Prometheus
  v3.5.0, Alertmanager v0.28.1 (for `msteamsv2_configs`), Grafana 12.0.2, node-exporter v1.9.1,
  cAdvisor v0.54.1 and postgres-exporter v0.17.1 (role `qeos_monitor`, `pg_monitor` only), each with a
  memory limit (about 1.1 GB in all; 8 GB RAM recommended). Off, nothing changes except PostgreSQL
  preloading `pg_stat_statements`.
- **Alerts** in `monitoring/prometheus/alerts.yml`, unit-tested with promtool; recording rules publish
  the blueprint's PostgreSQL names. Alertmanager's config is rendered from `.env` at start; an unset
  channel (email, Slack, Teams) is left out. Critical alerts go to every configured channel; warnings
  go to Slack and Teams, and to email only when email is the sole channel.
- **Grafana at `/grafana/` behind the QEOS sign-in.** `/users/me` carries `monitoring_url` for
  superusers; `POST /auth/grafana-session` answers `200 {"url":"/grafana/"}` and sets `qeos_grafana`
  (JWT, audience `grafana`, a `pwv` claim, httpOnly, Secure, SameSite=Strict, `Path=/grafana`, 8 h).
  `pwv` is an HMAC of the user's password hash. The gateway's `auth_request` asks
  `GET /internal/v1/grafana-check`, which re-reads the user on every request: a password change, a
  demotion or a deactivation cuts access on the next request. It returns `X-QEOS-User-Email`, which the
  gateway always overwrites before Grafana's auth proxy reads it. A 401 goes to the dashboard's
  `/monitoring` page, which signs in if needed and hands the cookie over. Logout clears it. With
  monitoring off the gateway answers `/grafana/` with 404. Break-glass: Grafana's admin login on
  `127.0.0.1:3000` of the VM only.
- **The `next` path is untrusted at both ends.** The gateway builds `next` from `$request_uri`, path
  only, and passes only RFC 3986 path characters (no header or redirect injection). The `/monitoring`
  page decodes it exactly once, requires the `/grafana/` prefix, and refuses `%`, `//`, backslashes,
  `.` and `..` segments and control characters; anything else opens `/grafana/`. A `sessionStorage`
  marker (`qeos.grafanaHandoff`, 10 s) stops a hand-over loop if Grafana still answers 401.

## Deviations from the plan (what shipped differs)
- **cAdvisor is v0.54.1**, not the version first planned.
- **postgres-exporter v0.17.1 exports no query text.** It has no `--collector.stat_statements.include_query`
  (that came in v0.18), so the statement series carry `queryid` only.
- **Grafana is on two networks only**, `grafana-front` and `monitoring`; the gateway has a fixed
  address on `grafana-front` (`GATEWAY_GRAFANA_FRONT_IP`, default 172.30.1.10) and
  `GF_AUTH_PROXY_WHITELIST` lists exactly that address, so a user header from any other container is
  refused.
- **Warning alerts reach email only when it is the only channel**, to keep a mailbox for criticals.
- **Per-endpoint latency shows p95 only.** The spec asks for p50/p95/p99 per route; the overview shows
  p50/p95/p99 for the whole service and p95 per endpoint, to keep the per-endpoint panel readable.
- **cAdvisor still mounts `/:/rootfs` and `/var/run`.** Dropping them was planned for Phase 3 but needs a
  live check that container discovery survives; it is a TODO follow-up.

## Stays TARGET (blueprint §11), each behind its trigger
| Piece | Trigger |
|---|---|
| Kubernetes service discovery, Prometheus federation | First multi-node deployment (the Kubernetes trigger) |
| Downsampling; 3-month aggregated and 3-year retention | An operator needs metrics older than `PROMETHEUS_RETENTION` (15 d), or Prometheus's disk passes `PROMETHEUS_RETENTION_SIZE` at that retention |
| Loki, with JSON logs carrying `traceId` | An incident cannot be diagnosed from `docker compose logs` (logs lost across a container recreate), or a second VM |
| OpenTelemetry tracing | A request crosses more than two services synchronously, or a latency problem cannot be placed from per-service metrics |
| `role` label on `api_requests_total` | A per-request role lookup exists (today roles come from project-service per call) |
| Metrics of Kafka, MongoDB, Redis, Elasticsearch, workflows, knowledge | Each arrives with its component |
| Profiling, synthetic monitoring, PagerDuty, SMS and webhook alerts | Not scheduled |

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
- Grafana trusts `X-QEOS-User-Email` only from the gateway's fixed `grafana-front` address
  (`GF_AUTH_PROXY_WHITELIST`). Grafana checks the real socket address, so the header from any other container,
  from the break-glass port `127.0.0.1:3000` or behind a spoofed `X-Forwarded-For`/`X-Real-IP` is refused
  (`auth-proxy.invalid-ip`). Residual: on Docker 28's bridge, other containers can reach Grafana's admin
  login page, which still needs `GRAFANA_ADMIN_PASSWORD`.
- The `qeos_grafana` cookie lasts 8 h. Signing out clears it in that browser, and a password change,
  demotion or deactivation stops it on the next request; a copy of the cookie elsewhere stays valid until
  one of those happens or it expires.
- A deep link to Grafana from Slack or email always passes `/monitoring` once (SameSite=Strict), and
  loses its query string.
- More uvicorn workers per service need prometheus_client's multi-process mode first.
- The gateway smoke checks the gate and the exporter role, and CI runs it both with and without the
  monitoring profile.
