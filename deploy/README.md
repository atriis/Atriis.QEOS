# Deploying QEOS on one VM

The whole platform runs on a single Linux VM with the same Docker Compose stack used in
development, plus one extra service: **Caddy**, which obtains and renews a Let's Encrypt
certificate and is the only thing exposed to the internet. Kubernetes enters only when the
first multi-node deployment does (see the blueprint's adoption triggers).

```
internet ──443──▶ edge (Caddy, Let's Encrypt) ──▶ gateway (NGINX) ──▶ services ──▶ PostgreSQL
                  the only published ports         rate limits, routing    not reachable from outside
```

## 1. What you need

- **A VM**: Ubuntu 24.04 LTS, 2 vCPU, 4 GB RAM, 30 GB disk is enough for a pilot
  (Azure `B2s`, AWS `t3.medium` or similar).
  With the optional monitoring profile (section 10), use **8 GB RAM** (`B2ms`, `t3.large`): its six
  containers can use about 1.1 GB together.
- **A domain name** you can add a DNS record to, e.g. `qeos.example.com`.
- **An email address** for Let's Encrypt certificate-expiry notices.

## 2. Network

1. Create a DNS **A record** for the domain pointing at the VM's public IP.
2. Firewall / network security group, inbound:
   - `443/tcp` from anywhere (the platform)
   - `80/tcp` from anywhere (Let's Encrypt validation and the HTTP→HTTPS redirect)
   - `22/tcp` from your own IP only (SSH)

   Nothing else: PostgreSQL and the services are never published.
3. The gateway always joins a small Docker network, `grafana-front`, fixed at `172.30.1.0/24`, even
   with monitoring off. If the VM already uses that range, `up` fails: see "Address range" in section 10.

## 3. Install Docker

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out and back in afterwards
docker compose version            # 2.24 or newer
```

## 4. Install QEOS

```bash
git clone https://github.com/carneiru/QA-Vision-Platform.git
cd QA-Vision-Platform
bash deploy/init-env.sh qeos.example.com ops@example.com
```

`init-env.sh` writes `.env` (mode 600, git-ignored) with the domain and freshly generated
secrets: `SECRET_KEY`, `INTERNAL_API_PASSWORD`, `POSTGRES_PASSWORD`, `TM_SECRETS_KEY`. It also writes `GRAFANA_ADMIN_PASSWORD` and `MONITORING_DB_PASSWORD`
commented out (section 10). It refuses to overwrite
an existing `.env`. **Back this file up somewhere safe**: losing it means losing access to
the database. Include it in every `.env` backup: `TM_SECRETS_KEY` encrypts the GitHub tokens used to
run tests from QEOS, and losing it means re-entering each project's GitHub token.

Then start everything:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build --wait edge
```

The first start takes a few minutes (image builds, migrations, certificate issuance).
Open `https://qeos.example.com`, create the first account, organization and project.

> Tip: put `alias qeos='docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml'`
> in `~/.bashrc`; the commands below then shorten to `qeos ps`, `qeos logs -f gateway`, …

## 5. Email

Without SMTP settings the platform still works: verification and password-reset links are
written to the auth-service log (`qeos logs auth-service | grep "Verification email"`), and
email notification channels report "SMTP is not configured". To send real email, add to `.env`
and recreate the services that send mail (`qeos up -d auth-service ingestion-service weekly-summary`).
Compose passes these variables to all three:

```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=…
SMTP_PASSWORD=…
EMAILS_FROM_EMAIL=qeos@example.com
# optional: SMTP_TLS=false for a relay without STARTTLS; EMAILS_FROM_NAME=QEOS
```

## 6. Connect CI

In each repository that reports to QEOS:

- secret `QEOS_API_KEY`: a key from the project's **Settings → API keys**
- variable or env `QEOS_URL`: `https://qeos.example.com`

The **Settings → Wire up your CI** card shows the ready-to-paste snippet for GitHub
Actions, GitLab CI, Azure Pipelines, Jenkins or the plain CLI, with this address filled in. No `--ca-file`
is needed: the certificate is a real one.

## 7. Backups

`deploy/backup.sh` dumps every database (one compressed file) and keeps 14 days.
Schedule it daily:

```bash
crontab -e
# 03:15 every day
15 3 * * * cd /home/<you>/QA-Vision-Platform && bash deploy/backup.sh >> backups/backup.log 2>&1
```

Copy the `backups/` directory off the VM regularly (object storage, another machine):
a backup on the same disk does not survive the disk. Settings: `QEOS_BACKUP_DIR`,
`QEOS_BACKUP_KEEP_DAYS`.

**Restore** (onto a fresh install with the same `.env`):

```bash
qeos up -d --wait postgres
gunzip -c backups/qeos-<timestamp>.sql.gz | qeos exec -T postgres psql -U postgres
qeos up -d --build --wait edge
```

One `ERROR: role "postgres" already exists` during the restore is expected and harmless.

## 8. Updates

```bash
cd QA-Vision-Platform
bash deploy/backup.sh          # always before an update
git pull
qeos up -d --build --wait edge
```

With monitoring on (section 10), name its six containers too, so they are rebuilt and waited for:
`qeos up -d --build --wait edge prometheus alertmanager grafana node-exporter cadvisor postgres-exporter`.

This release (the monitoring work) restarts PostgreSQL once, to preload `pg_stat_statements`, and recreates
the gateway, which joins a new network, even with monitoring off. Expect a short interruption.

Database migrations run automatically on every start.

**Existing installs and `TM_SECRETS_KEY`.** `init-env.sh` never overwrites an existing `.env`, so an install
made before "Run from QEOS" has no `TM_SECRETS_KEY`. Add it once, by hand, then restart:

```bash
# either (needs only openssl)
echo "TM_SECRETS_KEY=$(openssl rand -base64 32 | tr '+/' '-_')" >> .env
# or (needs the cryptography package)
python3 -c "from cryptography.fernet import Fernet; print('TM_SECRETS_KEY=' + Fernet.generate_key().decode())" >> .env
qeos up -d --wait edge
```

Without the key everything else works, but Project Settings shows "Running tests from QEOS is not
configured on this server" and Play stays disabled. Keep the key in your `.env` backups: changing or losing
it makes stored GitHub tokens unreadable, and owners then save them again in Settings.

### Upgrading from QA Vision names

The platform was called QA Vision before it became QEOS. An install from before the rename keeps
working after `git pull`; only these settings change name:

- **`.env`:** rename `QAV_DOMAIN` to `QEOS_DOMAIN` (compose stops with "set QEOS_DOMAIN" until you
  do). If `EMAILS_FROM_NAME=QA Vision` is set, change it to `QEOS`. `TM_SECRETS_KEY` and every
  other variable keep their names. `deploy/backup.sh` still reads `QAV_BACKUP_DIR` and
  `QAV_BACKUP_KEEP_DAYS` when the `QEOS_*` names are not set, and old `qav-*.sql.gz` dumps age
  out with the new ones.
- **CI:** the collector reads `QEOS_URL` and `QEOS_API_KEY`. The `QAV_*` names still work, with
  a one-line deprecation warning, and so does the `qav-collector` command (see `collector/README.md`).
- **What keeps working unchanged:** API keys that start with `qav_` (new keys start with `qeos_`),
  and signed-in browsers: the old `qav_refresh` cookie is accepted once and replaced by
  `qeos_refresh`, so nobody is logged out.
- **Data:** the Docker volumes keep their physical names (`qa-vision_qav_postgres_data`,
  `qa-vision_qav_gateway_certs`, `qa-vision_qav_caddy_data`, `qa-vision_qav_caddy_config`) and
  the compose project is still `qa-vision`, so no data moves. If Compose ever asks to recreate a
  volume, answer N.

## 9. Security notes

- Only Caddy publishes ports to the network (with monitoring on, Grafana also listens on `127.0.0.1:3000`
  of the VM itself, see section 10). The gateway trusts `X-Forwarded-For` from Caddy's fixed
  address alone, so per-IP rate limits (login: 5 requests/s) apply to each real client.
- Caddy sends `Strict-Transport-Security`, and renews the certificate on its own.
- `.env` holds every secret. Changing `SECRET_KEY` signs everyone out; API keys keep working.
- Keep the OS patched: `sudo apt-get upgrade` monthly, or enable unattended upgrades.

## 10. Monitoring (optional)

Prometheus, Alertmanager and Grafana run as the compose profile `monitoring`, with node-exporter (the
VM), cAdvisor (containers) and postgres-exporter. Off by default; an install without it runs exactly as
before. Design: `docs/superpowers/specs/2026-10-10-monitoring-design.md`.

> **Status.** The stack, the metrics, the alert rules, the alert channels and the five dashboards are
> built. The QEOS sign-in to Grafana is half built: with `MONITORING_ENABLED=true` the gateway serves
> `https://<domain>/grafana/` to active superusers only (auth-service checks the `qeos_grafana` cookie
> on every request and Grafana signs the user in by the header the gateway sets), but the account-menu
> **Monitoring** item and the dashboard's `/monitoring` page that hand the cookie over are **not built
> yet**, so a browser visit to `/grafana/` is sent to `/monitoring` and stops there. Today the way into
> Grafana is still the break-glass login below. Prometheus is not published; it works and fires alerts
> regardless.

**Turn it on.** A new install's `.env` already holds the four lines below, commented out, with
generated passwords: uncomment them. (An install from before monitoring: add them by hand, passwords of
letters and digits, 32+ characters.) Until then no monitoring database role exists.

```bash
COMPOSE_PROFILES=monitoring
MONITORING_ENABLED=true
GRAFANA_ADMIN_PASSWORD=...
MONITORING_DB_PASSWORD=...
```

`MONITORING_ENABLED` is read by auth-service and the gateway: true opens `/grafana/` to superusers through
the gateway; unset or false, `/grafana/` is a 404 for everyone (Grafana itself still runs with the profile).
Then `qeos up -d --build --wait edge prometheus alertmanager grafana node-exporter cadvisor postgres-exporter` (naming the services starts the profile's containers
and waits for them, not for the one-shot jobs). `db-init` creates the PostgreSQL role `qeos_monitor` on that `up`: it is a
member of `pg_monitor` only, so it reads statistics and settings and no table data, but it can see query
text in `pg_stat_activity`. The first `up` after this release also restarts PostgreSQL once, to load
`pg_stat_statements`. Grafana and postgres-exporter refuse to start while their password is empty.

**Grafana's admin password is read on its first start only.** Changing `GRAFANA_ADMIN_PASSWORD`
afterwards does not change the login. Either reset it in place:
`qeos exec grafana grafana cli admin reset-admin-password '<new password>'`, or, since Grafana keeps nothing
you would miss (its dashboards are provisioned from the repository), delete its volume (`qeos rm -sf grafana`, then
`docker volume rm qa-vision_qeos_grafana_data`) and start again.

**Dashboards.** Five dashboards are provisioned read-only from the repository (`monitoring/grafana/dashboards`)
into the folder **QEOS**; edits made in the Grafana UI cannot be saved, change the JSON and the dashboards reload
within a minute. The first is Grafana's home page.

| Dashboard | Shows |
|---|---|
| QEOS overview | per service: up, requests per second, 5xx share, 95th percentile, deployed version, firing alerts |
| Service detail | one service (pick it at the top): per endpoint rate and latency, status codes, requests in flight, process memory and CPU |
| Jobs and uploads | time since each background job's last success and error, uploads accepted and rejected, results per hour, upload time, test executions and cases created |
| PostgreSQL | connections, database sizes, transactions, cache hit rate, locks, slowest statements |
| Host and containers | VM CPU, memory and disk with a 24 hour disk prediction; per container CPU, memory and restarts |

How to open them today: the break-glass login, `ssh -L 3000:127.0.0.1:3000 <vm>` (or on the VM itself)
and then `http://127.0.0.1:3000/grafana/`, user `admin` and `GRAFANA_ADMIN_PASSWORD` (the login form and
basic auth stay on for this; through the gateway nobody reaches them without passing auth-service's check).
Once the dashboard's **Monitoring** item is built, a superuser opens `https://<domain>/grafana/` (or **Monitoring** in the account menu) with the usual QEOS login. The
"Slowest statements" table lists `queryid`, database, user, calls and mean time only: statement text is not
collected on purpose (it could carry secrets or personal data); look a `queryid` up in `pg_stat_statements`.

**Resources.** Six containers with these memory limits: Prometheus 512 MB, Grafana 256 MB, cAdvisor
128 MB, Alertmanager, node-exporter and postgres-exporter 64 MB each, about 1.1 GB in all. Use a VM with
8 GB RAM (4 GB is enough without monitoring).

**What the exporters show.**

- node-exporter runs on the compose network, not with `network_mode: host`, so its **network** metrics
  are the container's, not the VM's. CPU, memory and disk are the VM's. Disk metrics of a mount added
  after start need a restart of node-exporter.
- postgres-exporter (v0.17.1) is deliberately run **without statement query text**: query literals could
  copy secrets or personal data into Prometheus. The slowest-statements view shows the `queryid` and
  timings only.
- cAdvisor is v0.54.1: v0.52.1 finds no container under Docker's containerd image store.

**Alerts.** Each channel turns on when its settings are present; an unset one is left out:

| Variable | Channel |
|---|---|
| `ALERT_EMAIL_TO` | Email (comma-separated addresses). Reuses `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS`, `EMAILS_FROM_EMAIL`; without `SMTP_HOST` email stays off. |
| `ALERT_SLACK_WEBHOOK_URL` | Slack incoming webhook |
| `ALERT_TEAMS_WEBHOOK_URL` | Microsoft Teams workflow webhook |

Critical alerts (service down, 5xx burst, disk filling up, PostgreSQL down) go to every channel; warnings
(slow requests, stale or failing jobs, rejected uploads, memory pressure, connections, database size) go
to Slack and Teams, or to email when it is the only channel. With no channel, alerts are only held in
Alertmanager. The channel settings are read when Alertmanager starts: after changing them, run
`qeos up -d --force-recreate alertmanager`. Check what was configured:
`qeos logs alertmanager | grep channels`. Silences last until Alertmanager restarts.

| Variable | Default | |
|---|---|---|
| `PROMETHEUS_RETENTION` | `15d` | How long metrics are kept |
| `PROMETHEUS_RETENTION_SIZE` | `5GB` | Cap on Prometheus's disk use |
| `POSTGRES_DB_SIZE_ALERT_GB` | `20` | `PostgresDatabaseGrowing` fires above this |

**Version.** `QEOS_COMMIT=$(git rev-parse --short HEAD) qeos up -d --build --wait edge` (plus the six containers when monitoring is on) makes every service
report the deployed commit in its `build_info` metric (`unknown` otherwise; `QEOS_VERSION` defaults to
`dev`).

**Address range.** The gateway has a fixed address on the network it shares with Grafana, and Grafana
trusts the user header only from that address. The defaults are `172.30.1.0/24`, the gateway at
`172.30.1.10`. The network is created even with monitoring off, so if the VM already uses that range
`up` fails. Pick a free range and set all three in `.env` (the Grafana whitelist follows the gateway
address):

```bash
GRAFANA_FRONT_SUBNET=10.99.7.0/24
GRAFANA_FRONT_IP_RANGE=10.99.7.128/25   # the upper half: Docker hands out addresses from here
GATEWAY_GRAFANA_FRONT_IP=10.99.7.10     # inside the subnet, outside that range
```

The production edge's own network uses `172.30.0.0/24`; keep the two apart. Changing the range of an
existing install needs the network recreated: `qeos down`, then `up` (data volumes are kept).

**Break-glass.** Grafana's own admin login works from the VM only. From your machine:
`ssh -L 3000:127.0.0.1:3000 <vm>`, then `http://localhost:3000/grafana/login`, user `admin`, password
`GRAFANA_ADMIN_PASSWORD`. Port 3000 is bound to `127.0.0.1` of the VM and is not reachable from outside.

**Security.** Grafana is on the `grafana-front` network (with the gateway only) and on `monitoring`, not
on the platform's network, so no service container can resolve it by name. Its auth proxy
(`GF_AUTH_PROXY_WHITELIST`) believes a user header only from the gateway's fixed address. One residual
remains: because the break-glass port is published, Docker 28 and later makes Grafana's `grafana-front`
address reachable by IP from other containers on the host. Such requests arrive from the network's
bridge gateway (`172.30.1.128` with the default subnet), not from the whitelisted gateway, so the auth proxy ignores any user
header they send, and they get nothing beyond Grafana's own login, which still needs the admin
password. Keep `GRAFANA_ADMIN_PASSWORD` strong; `init-env.sh` generates 32 characters. The query text
visible to `qeos_monitor` is described in `SECURITY.md`. cAdvisor runs as root with `/:/rootfs:ro` and the
`/var/run` (the Docker socket) mounted, so it can read the whole VM filesystem, including `.env` and the
PostgreSQL data, and has root-equivalent Docker API access; it is opt-in and publishes no port, and
dropping the `/:/rootfs` mount is planned (Phase 3).

**Dead-man's switch (not built).** The `Watchdog` alert always fires and goes nowhere. To be told when the
whole VM or Alertmanager is gone, route `Watchdog` to an external heartbeat service (any hosted "dead
man's snitch") by editing `monitoring/alertmanager/alertmanager.yml.template`.

**Data.** Volumes `qa-vision_qeos_prometheus_data` and `qa-vision_qeos_grafana_data`. Grafana needs no
backup (its dashboards are provisioned from the repository); `deploy/backup.sh` is unchanged.

**Turn it off.** Remove `COMPOSE_PROFILES=monitoring`, then stop and remove the six containers (Compose
does not do this for a profile that was switched off):
`qeos --profile monitoring rm -sf prometheus alertmanager grafana node-exporter cadvisor postgres-exporter`.
