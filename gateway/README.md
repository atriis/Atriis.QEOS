# Gateway

NGINX in front of every QEOS service. Configuration only — no code.
Design: `docs/superpowers/specs/2026-09-28-api-gateway-design.md`.

## Routes

| Path | Service |
|---|---|
| `/api/v1/organizations/{id}/projects…` | project-service |
| `/api/v1/projects/{id}/cases…`, `…/case-labels…`, `…/case-folders…`, `…/case-features…`, `…/case-areas`, `…/features…`, `…/suites…`, `…/ci-target…`, `…/run-requests…` | test-management-service |
| `/api/v1/projects/{id}/api-keys…`, `…/runs…`, `…/analytics…`, `…/masking-patterns…`, `…/log-patterns…`, `…/export`, `…/notification-channels…`, `…/collection-settings`, `…/screenshots…`, `…/artifacts…` | ingestion-service |
| `/api/v1/runs…`, `/api/v1/collect…` | ingestion-service |
| `/api/v1/projects…` | project-service |
| `/api/v1/organizations…`, `/api/v1/invitations…` | organization-service |
| `/api/v1/auth…`, `/api/v1/users…`, `/api/v1/sso…` | auth-service |
| `/health` | the gateway itself |
| `/health/auth`, `/health/organizations`, `/health/projects`, `/health/ingestion`, `/health/test-management` | that service's `/health` |
| `/grafana/…` | Grafana, behind auth-service's check (monitoring on); `404 {"detail":"Not Found"}` when off — see below |
| any other `/api/…` path | `404 {"detail":"Not Found"}` |
| anything else | the dashboard (its own NGINX falls back to `index.html`; ADR-017) |

The first three rows are regex locations: NGINX checks regex locations before prefix ones, which
is what takes `/organizations/{id}/projects` away from organization-service and the
`/projects/{id}/…` paths away from project-service. `/metrics` and `/internal` are never routed:
they fall through to the dashboard.

CI keeps this table honest: `scripts/check_architecture_docs.py` replays NGINX's location choice for every
router prefix in each service's `api/v1/api.py` and fails when a prefix reaches another service, a location
proxies to a service with no such route, or a row here names the wrong service.

## Grafana (`/grafana/`, ADR-027)

`entrypoint.sh` picks the location from `MONITORING_ENABLED`, the same `.env` value auth-service reads
(`true`, `1`, `yes`, `on`, any case, as auth-service accepts them):

- **Off** (unset or false, the default): `grafana-off.conf`. `/grafana` and `/grafana/…` answer the JSON
  404 for everyone, signed in or not.
- **On**: `grafana-on.conf`. `/grafana` redirects to `/grafana/`. Every `/grafana/…` request first goes
  through `auth_request` to auth-service's `GET /internal/v1/grafana-check` (an `internal` location, so no
  client can call it; `/internal/` itself stays unrouted). The subrequest carries only the browser's
  `Cookie` header (the `qeos_grafana` cookie is the credential), plus the request id and forwarding
  headers: no body, no `Authorization`, no other client header.
  - 200: the request goes to `grafana:3000` with `X-QEOS-User-Email` set from the check's answer.
    The gateway **always overwrites** that header, so a client sending its own never chooses who Grafana
    signs in; Grafana trusts it only from the gateway's fixed `grafana-front` address
    (`GATEWAY_GRAFANA_FRONT_IP`). `Authorization` is removed toward Grafana, and so is the `qeos_grafana`
    cookie: Grafana gets `$grafana_cookie`, the browser's `Cookie` header without it (two chained maps in
    `nginx.conf.template`; Grafana's own cookies such as `grafana_session` pass unchanged). The check
    itself still receives the full `$http_cookie`. Fail closed: if a `qeos_grafana` is still in
    `$grafana_cookie` (only a hand-made header does that: a third copy, a space before `=`), the request
    gets `400 {"detail":"Bad Request"}` and never reaches Grafana.
  - 401: `302 /monitoring?next=<path>`. The dashboard's `/monitoring` page signs in if needed, mints the
    cookie and comes back. `next` is the path of the raw request line, still percent-encoded as the
    client sent it (`$grafana_next`, a map on `$request_uri`), never NGINX's decoded `$uri`: a decoded
    `%0d%0a` would split the `Location` header and inject response headers. A deep link's query string is
    dropped (Ruling 4). RFC 3986 path characters only (no raw `&`, no raw non-ASCII); anything else, or a path
    that does not start with `/grafana/`, falls back to `/grafana/`.
  - `location ^~ /grafana/`, so no regex location can take a `/grafana/` path past the check.
  - 403: `403 {"detail":"Forbidden"}`. auth-service down, or any other answer: `502 {"detail":"Bad Gateway"}`.
    Nothing but a 2xx reaches Grafana.
- Grafana is resolved when a request comes, so the gateway starts while Grafana is down and answers 502
  until it is up. No WebSockets: Grafana Live is off. The limit is the API zone with a burst of 100
  (a dashboard loads many assets).

## Limits

- Per client IP: 20 requests/s (burst 40) on every `/api/v1` route and the dashboard; additionally
  5 requests/s (burst 10) on `login`, `mfa/verify`, `register`, `forgot-password`, `reset-password`,
  `change-password`, `resend-verification` and every `/api/v1/sso` route.
  Over the limit: `429 {"detail":"Too Many Requests"}` with `Retry-After: 1`. Health routes are
  never limited.
- `/api/v1/collect` has its own limit instead: 10 requests/s per IP (burst 20).
- `/api/v1/collect/blobs` (step screenshots) has a third: 50 requests/s per IP (burst 100), and bodies up to 6 MB.
- `/api/v1/collect/artifacts` (traces) has a fourth: 10 requests/s per IP (burst 20), bodies up to 101 MB, and request
  buffering off, so a trace streams through to ingestion instead of being written to the gateway's disk first.
- Request bodies up to 10 MB, except the Gherkin import (`/projects/{id}/cases/import`):
  `GATEWAY_IMPORT_MAX_BODY`, default 25 MB. Upstream connect timeout 3 s, read timeout 30 s, except trace uploads
  (`/api/v1/collect/artifacts`): upstream read and send timeouts 120 s and a 60 s client body timeout, since
  ingestion still stores and copies up to 100 MB after the last byte arrives.
- Responses are gzipped only on `/projects/{id}/analytics/report` and `/projects/{id}/case-areas`,
  never server-wide (compressing responses that carry secrets opens BREACH).
- NGINX's own errors (404, 413, 429, 502, 504) are JSON; the services' errors pass through.

## TLS

HTTPS on host port `${GATEWAY_HTTPS_PORT:-8443}`; HTTP on `${GATEWAY_HTTP_PORT:-8080}` redirects
to it. On first start the entrypoint generates a self-signed certificate for `localhost` into the
compose volume `qeos_gateway_certs` (physical name `qa-vision_qav_gateway_certs`). Use `curl -k`, or trust it once:
`docker compose cp gateway:/etc/nginx/certs/tls.crt ./qeos-localhost.crt`.
To use your own, put `tls.crt` and `tls.key` in that volume before starting.

## Non-root and read-only (ADR-038)

The image is `nginxinc/nginx-unprivileged` and runs as `nginx` (uid 101), so inside the container it listens on
8443 (HTTPS) and 8080 (HTTP); compose publishes those on the host ports above, and the production edge proxies to
`https://gateway:8443`. The entrypoint renders `nginx.conf`, `grafana.conf` and `real_ip.conf` into
`NGINX_RENDER_DIR` (default `/etc/nginx`) and keeps the certificate in `NGINX_CERT_DIR` (default
`/etc/nginx/certs`); the pid file and NGINX's temporary files are in `/tmp`. With a read-only root filesystem
(Kubernetes), set `NGINX_RENDER_DIR=/tmp/nginx` and an `NGINX_CERT_DIR` that is writable or holds a mounted
certificate. A certificate volume made by an older gateway belongs to root; compose's one-shot `gateway-certs` job
hands it to uid 101 before the gateway starts. `bash scripts/check_readonly_images.sh` starts every platform image
with `--read-only --tmpfs /tmp` and checks that it answers as a non-root user.

## Requests and logs

Every response carries `X-Request-ID` (yours if you sent one); the same id is forwarded to the
service. `X-Forwarded-For` is replaced with the connecting address, never appended to, so a client
cannot choose its own rate-limit bucket. `docker compose logs gateway` shows one JSON line per
request.

## Adding a service

1. In `nginx.conf.template`, add a `location` for its path prefix with
   `limit_req zone=api burst=40 nodelay;`, `set $upstream http://<service>:8000;` and
   `proxy_pass $upstream;` — plus a `= /health/<name>` location. Keep the upstream in a variable:
   that is what lets the gateway find a recreated container without a restart.
2. In the root `docker-compose.yml`, add the service, its `-migrate` job, its database to
   `scripts/postgres-init.sh`, and a `depends_on` entry under `gateway`.
3. Add a routing check and a `/health/<name>` check to `scripts/smoke_gateway.sh`.

## Checking a change

```bash
docker build -t qeos/gateway:local gateway && docker run --rm qeos/gateway:local nginx -t
docker run --rm -e MONITORING_ENABLED=true qeos/gateway:local nginx -t   # the gated /grafana/
export SECRET_KEY=dev        # every docker compose command needs it, not just `up`
docker compose up -d --build --wait gateway
bash scripts/smoke_gateway.sh
```
