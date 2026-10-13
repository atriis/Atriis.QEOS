# QEOS: complete setup guide

This guide takes you from nothing to a running QEOS. It then covers each feature: what you
have to configure, and how to check that it works. Read sections 1 to 3 once, in order.
After that, go only to the features you need.

| Stage | Where QEOS runs | Who can send results | Sections |
|---|---|---|---|
| **Local** | your machine | your machine, and self-hosted runners on your network | 1–5 |
| **Pilot** | your machine, plus a tunnel | GitHub/GitLab/Azure hosted CI, while the tunnel is open | [4.1.9](#419-hosted-ci-against-a-local-stack-tunnel) |
| **Production** | one VM with a domain | everyone, all the time | [6](#6-production) and [`deploy/README.md`](../deploy/README.md) |

Commands are given for **Windows PowerShell** and for **bash** (Linux, macOS, Git Bash) where
they differ. If a block has no label, it works in both. On Windows, run Git Bash by its full
path (`& "C:\Program Files\Git\bin\bash.exe"`). A plain `bash` typed in PowerShell can start WSL
instead.

> **Names.** The product is QEOS. It used to be called QA Vision, and some technical names
> stay on purpose: the Docker volumes are still `qa-vision_qav_*` (and `qa-vision_qeos_*` for
> monitoring), and the repository is `carneiru/QA-Vision-Platform`. The Compose project, and so the
> container names, became `qeos` on 2026-10-11 ([7.1](#71-updating)). The collector is
> `qeos-collector` and reads `QEOS_URL` / `QEOS_API_KEY`. The old `qav-collector` command and
> the `QAV_*` variables still work, with a deprecation warning.

## Contents

1. [Prerequisites](#1-prerequisites)
2. [First-time setup](#2-first-time-setup)
   [2.1 Clone](#21-clone) · [2.2 Create `.env`](#22-create-env) · [2.3 Every variable](#23-every-variable-in-env) · [2.4 Start](#24-start-the-platform) · [2.5 Stop, and never `down -v`](#25-stop-restart-and-why-never-down--v) · [2.6 Health and smoke check](#26-health-and-smoke-check) · [2.7 Trust the local certificate](#27-trust-the-local-https-certificate)
3. [Accounts, organizations and access](#3-accounts-organizations-and-access)
   [3.1 First account](#31-first-account-and-email-verification) · [3.2 Email (SMTP)](#32-email-smtp) · [3.3 Organization and project](#33-organization-and-project) · [3.4 Roles](#34-roles) · [3.5 Invitations](#35-invitations) · [3.6 Passwords](#36-passwords) · [3.7 MFA](#37-two-factor-authentication-mfa) · [3.8 SSO](#38-single-sign-on-google-and-microsoft)
4. [Features](#4-features)
   - [4.1 Sending test results](#41-sending-test-results)
   - [4.2 Test cases](#42-test-cases)
   - [4.3 Run from QEOS (Play and Stop)](#43-run-from-qeos-play-and-stop)
   - [4.4 Analytics](#44-analytics)
   - [4.5 Notifications](#45-notifications)
   - [4.6 Masking](#46-masking)
   - [4.7 Retention, legal hold and export](#47-retention-legal-hold-and-export)
   - [4.8 Ctrl K search and KPI tiles](#48-ctrl-k-search-and-kpi-tiles)
   - [4.9 Security operations](#49-security-operations)
5. [Wiring a real test repository end to end](#5-wiring-a-real-test-repository-end-to-end)
6. [Production](#6-production)
7. [Upgrades and maintenance](#7-upgrades-and-maintenance)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Prerequisites

| What | Version | Needed for |
|---|---|---|
| **Docker** with **Compose v2** (Docker Desktop on Windows/macOS) | Compose **2.24 or newer** (`docker compose version`) | Running the whole platform. |
| **Git** | any recent version | Cloning the repository. `pip` also uses it to install the collector from a tag. |
| **Git Bash** (Windows only, comes with Git for Windows) | any | `deploy/init-env.sh` and `scripts/smoke_gateway.sh`. |
| **Python** | **3.9 or newer** | Only for running `qeos-collector` on your machine. CI runners install it themselves. |
| **curl** | any | Health checks and the smoke test. In PowerShell, type `curl.exe`: plain `curl` is an alias for `Invoke-WebRequest`. |
| **openssl** | any | Optional. One way to generate secrets. Git Bash includes it. |

You do **not** need Node.js or a local Python for the services: the dashboard and every service
are built inside Docker. A test repository that uses [Run from QEOS](#43-run-from-qeos-play-and-stop)
needs Node.js on its own GitHub runner. That is a matter for the test repository, not for this machine.

Resources: the stack runs about a dozen containers. Give Docker Desktop at least 4 GB of RAM.
The first build takes a few minutes.

---

## 2. First-time setup

### 2.1 Clone

```
git clone https://github.com/carneiru/QA-Vision-Platform.git
cd QA-Vision-Platform
```

Keep line endings as they are. The repository's `.gitattributes` forces LF on shell scripts, and a
script with CRLF endings breaks the container build (see [Troubleshooting](#8-troubleshooting)).

### 2.2 Create `.env`

Compose reads `.env` in the repository root on **every** command (`up`, `ps`, `logs`,
`exec`, …). The file is git-ignored. You never export secrets by hand.

**Option A: from `.env.example` (shown here).**

PowerShell:
```powershell
Copy-Item .env.example .env
```
bash:
```bash
cp .env.example .env
```

Then open `.env` in an editor and set the four secrets. **Replace both `change-me` values.**
Compose accepts them as they are, which is exactly the danger.

```
SECRET_KEY=<64 hex characters>
INTERNAL_API_PASSWORD=<40 letters/digits>
POSTGRES_PASSWORD=<40 letters/digits>      # uncomment it; set it BEFORE the first start
TM_SECRETS_KEY=<Fernet key>                # uncomment it; needed only for Run from QEOS
```

Generate the values with one of the following.

PowerShell (no extra tools):
```powershell
function New-Bytes([int]$n) { $b = New-Object byte[] $n; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); $b }
"SECRET_KEY="            + (-join (New-Bytes 32 | ForEach-Object { $_.ToString('x2') }))
"INTERNAL_API_PASSWORD=" + (-join (New-Bytes 20 | ForEach-Object { $_.ToString('x2') }))
"POSTGRES_PASSWORD="     + (-join (New-Bytes 20 | ForEach-Object { $_.ToString('x2') }))
"TM_SECRETS_KEY="        + [Convert]::ToBase64String((New-Bytes 32)).Replace('+','-').Replace('/','_')
```
bash (openssl):
```bash
echo "SECRET_KEY=$(openssl rand -hex 32)"
echo "INTERNAL_API_PASSWORD=$(openssl rand -hex 20)"
echo "POSTGRES_PASSWORD=$(openssl rand -hex 20)"
echo "TM_SECRETS_KEY=$(openssl rand -base64 32 | tr '+/' '-_')"
```
Or, with the Python `cryptography` package installed, generate the Fernet key with:
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

Paste the printed lines into `.env`. Save the file as plain UTF-8 or ASCII, without a BOM.

**Option B: one command.** `deploy/init-env.sh` writes a complete `.env` with all four secrets
(plus `QEOS_DOMAIN` and `ACME_EMAIL`, which only production uses). It refuses to overwrite an
existing `.env`.

PowerShell:
```powershell
& "C:\Program Files\Git\bin\bash.exe" deploy/init-env.sh localhost you@example.com
```
bash:
```bash
bash deploy/init-env.sh localhost you@example.com
```

> **Back up `.env`.** Together with the database volume, it *is* the installation. Losing
> `POSTGRES_PASSWORD` locks you out of the database. Losing `TM_SECRETS_KEY` makes stored GitHub
> tokens unreadable.

### 2.3 Every variable in `.env`

**Required.** Compose stops with `set SECRET_KEY …` / `set INTERNAL_API_PASSWORD …` if either is missing.

| Variable | What it is | How to set it |
|---|---|---|
| `SECRET_KEY` | Signs and verifies every login token (JWT). All services share it. | Long and random (64 hex). Changing it later signs everyone out. API keys keep working. |
| `INTERNAL_API_PASSWORD` | Shared secret for service-to-service APIs: auth ↔ organization (member checks) and project ↔ retention job. | Letters and digits only. It goes inside a URL, so `@ : / %` break it. |

**Recommended.**

| Variable | Default | What it does |
|---|---|---|
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL superuser password. It is applied **only when the database volume is first created**. Changing it in `.env` afterwards does not change the database, and the services then fail to connect (see [4.9](#49-security-operations)). PostgreSQL is never published to the host, so the default is acceptable on a laptop. Production always sets it. |
| `TM_SECRETS_KEY` | empty | Fernet key that encrypts each project's GitHub token for [Run from QEOS](#43-run-from-qeos-play-and-stop). Empty turns that feature off: Settings says so and Play stays disabled. Keep it in every `.env` backup. |

**Optional.**

| Variable | Default | What it does |
|---|---|---|
| `GATEWAY_HTTPS_PORT` | `8443` | Host port for HTTPS. Links in emails and notifications follow it automatically. |
| `GATEWAY_HTTP_PORT` | `8080` | Host port for HTTP, which only redirects to HTTPS. Change it if 8080 is taken (for example to `18080`). |
| `SMTP_HOST` | empty | Outgoing mail server. Empty means no email is sent: auth logs its links, and email notification channels record "SMTP is not configured". See [3.2](#32-email-smtp). |
| `SMTP_PORT` | `587` | |
| `SMTP_TLS` | `true` | STARTTLS. Use `false` for a relay without it. Implicit TLS (port 465) is not supported. |
| `SMTP_USER`, `SMTP_PASSWORD` | empty | Login is used only when both are set. |
| `EMAILS_FROM_EMAIL` | empty (falls back to `no-reply@example.com`) | Sender address. |
| `EMAILS_FROM_NAME` | `QEOS` | Sender name. |
| `IMPORT_MAX_FILES` | `2000` | Gherkin import: files per request. |
| `IMPORT_MAX_FILE_BYTES` | `262144` | Gherkin import: size of one file. |
| `IMPORT_MAX_TOTAL_BYTES` | `10485760` | Gherkin import: all content in one request. |
| `GATEWAY_IMPORT_MAX_BODY` | `25m` | Gateway body cap on the import path. Keep it about 2.5× `IMPORT_MAX_TOTAL_BYTES`. |
| `VITE_GOOGLE_CLIENT_ID` | empty | Shows the Google button. Baked in at build time. See [3.8](#38-single-sign-on-google-and-microsoft). |
| `VITE_MSAL_CLIENT_ID` | empty | Shows the Microsoft button. Baked in at build time. |
| `VITE_MSAL_AUTHORITY` | `https://login.microsoftonline.com/organizations` | MSAL authority. |
| `COMPOSE_PROFILES` | empty | `monitoring` starts Prometheus, Alertmanager, Grafana and the exporters ([7.4](#74-monitoring-optional)). |
| `MONITORING_ENABLED` | `false` | The QEOS sign-in to Grafana: when true, the gateway opens `/grafana/` to active superusers (checked by auth-service on every request); otherwise `/grafana/` is a 404. Superusers open it from the dashboard's **Monitoring** item. |
| `GRAFANA_ADMIN_PASSWORD`, `MONITORING_DB_PASSWORD` | empty | Required with monitoring: Grafana's admin login (read on its first start only), and the password of PostgreSQL role `qeos_monitor`. |
| `ALERT_EMAIL_TO`, `ALERT_SLACK_WEBHOOK_URL`, `ALERT_TEAMS_WEBHOOK_URL` | empty | Alert channels; each turns on when set. Email also needs `SMTP_HOST`. |
| `PROMETHEUS_RETENTION`, `PROMETHEUS_RETENTION_SIZE`, `POSTGRES_DB_SIZE_ALERT_GB` | `15d`, `5GB`, `20` | Metrics kept, their disk cap, and the database size alert. |
| `GRAFANA_FRONT_SUBNET`, `GRAFANA_FRONT_IP_RANGE`, `GATEWAY_GRAFANA_FRONT_IP` | `172.30.1.0/24`, `172.30.1.128/25`, `172.30.1.10` | The gateway always joins a network with this fixed range, monitoring or not. Change all three only if the host already uses it ([7.4](#74-monitoring-optional)). |
| `QEOS_COMMIT`, `QEOS_VERSION` | `unknown`, `dev` | Reported by every service in its `build_info` metric. |

**Production only** (written by `init-env.sh` and read by `deploy/docker-compose.prod.yml`):
`QEOS_DOMAIN` (the public host name) and `ACME_EMAIL` (Let's Encrypt notices). Optional:
`EDGE_HTTP_PORT` / `EDGE_HTTPS_PORT` (default `80` / `443`). `deploy/backup.sh` reads
`QEOS_BACKUP_DIR` and `QEOS_BACKUP_KEEP_DAYS` from its own shell environment, not from `.env`.

**Not forwarded by `docker-compose.yml`.** Some service settings exist in the code, but the
stock compose file does not pass them through, so putting them in `.env` has no effect.
Examples: auth-service's `GOOGLE_CLIENT_ID`, `AZURE_CLIENT_ID` and `AZURE_ALLOWED_TENANTS`
(see [3.8](#38-single-sign-on-google-and-microsoft) for how to pass them), ingestion's
`WEEKLY_SUMMARY_HOUR_UTC` (fixed at 7), `RETENTION_INTERVAL_HOURS` (fixed at 24) and
`NOTIFY_TIMEOUT_SECONDS` (fixed at 5).

### 2.4 Start the platform

```
docker compose up -d --build --wait gateway
```

- You only name `gateway`: it depends on every service, so this starts everything. That means
  PostgreSQL, the `db-init` job (it creates any missing database), the five `*-migrate` jobs
  (`alembic upgrade head`), the five services, the dashboard, the background jobs
  (`ingestion-retention`, `analytics-rollup`, `impact-rollup`, `weekly-summary`) and finally the gateway.
- `--wait` returns only when everything is healthy. The first run takes a few minutes.
- Open **https://localhost:8443**. Until you complete [2.7](#27-trust-the-local-https-certificate),
  the browser warns about the certificate. Accept it once.

Everyday commands:

| Task | Command |
|---|---|
| Status of every container | `docker compose ps -a` |
| Follow one service's log | `docker compose logs -f auth-service` |
| Recent errors everywhere | `docker compose logs --since 10m` |
| Restart one service | `docker compose restart ingestion-service` |
| Apply a changed `.env` | `docker compose up -d --wait gateway` (recreates only what changed) |
| Rebuild after a code change or `git pull` | `docker compose up -d --build --wait gateway` |
| Open a database shell | `docker compose exec postgres psql -U postgres -d project_db` |

### 2.5 Stop, restart, and why never `down -v`

```
docker compose down          # stops and removes the containers; the data stays
docker compose up -d --wait gateway
```

**Never run `docker compose down -v` (`--volumes`)** unless you really mean to destroy
everything. It deletes the named volumes:

- `qa-vision_qav_postgres_data`: **every database**, including accounts, organizations, projects,
  API keys, runs, results, test cases and stored GitHub tokens. There is no undo.
- `qa-vision_qav_gateway_certs`: the local certificate. A new one is generated, and every machine
  that trusted the old one (browsers, `--ca-file`) has to trust it again.

The same applies to `docker volume rm` and `docker volume prune` on those volumes. If you want a
clean slate on purpose, take a backup first ([7.3](#73-backups-local-stack)). The volumes keep
their pre-rename names (`qav_`) on purpose. If Compose ever offers to recreate a volume, answer **N**.

### 2.6 Health and smoke check

**Quick health check.** Each of these must return `200`:

PowerShell:
```powershell
curl.exe -k https://localhost:8443/health
foreach ($s in "auth","organizations","projects","ingestion","test-management") { curl.exe -k -s -o NUL -w "$s %{http_code}`n" "https://localhost:8443/health/$s" }
```
bash:
```bash
curl -k https://localhost:8443/health
for s in auth organizations projects ingestion test-management; do curl -ks -o /dev/null -w "$s %{http_code}\n" "https://localhost:8443/health/$s"; done
```
`/health` answers `{"status":"healthy"}`. `docker compose ps -a` must show every long-running
service `healthy` (or `running`, for the four background jobs) and the `*-migrate` and `db-init`
jobs `exited (0)`. Plain `docker compose ps` hides the finished jobs.

**Full smoke test.** `scripts/smoke_gateway.sh` runs end-to-end checks through the gateway:
every route, an API key, an upload, the collector, masking, analytics, imports,
invitations, the retention job, the SPA and the rate limits. It needs `SECRET_KEY` and
`INTERNAL_API_PASSWORD` **exported in the shell** (it does not read `.env` itself), plus `curl`,
and Python 3.9+ for the collector check.

PowerShell:
```powershell
& "C:\Program Files\Git\bin\bash.exe" -c "set -a; . ./.env; set +a; bash scripts/smoke_gateway.sh"
```
bash:
```bash
set -a; . ./.env; set +a
bash scripts/smoke_gateway.sh
```
It ends with `all gateway checks passed`. Run it on a **local** stack only: it refuses to start
when `DOCKER_HOST`, or else the current docker context, points anywhere but a local socket
(`unix://` or `npipe://`). It talks to
`https://localhost:${GATEWAY_HTTPS_PORT:-8443}` and leaves its own "Smoke …" organizations,
projects, runs and a test account (`smoke-invitee-…@example.com`) in the database. These
belong to no real user, so they do not appear in your dashboard. It also triggers the login
rate limit on purpose, so sign-ins from your machine may be refused for a few seconds right
after it runs.

**With the monitoring profile on** (`MONITORING_ENABLED=true`), also export
`MONITORING_DB_PASSWORD`, the value the stack was started with. The smoke then checks that every
Prometheus target is up, that `/grafana/` without the cookie redirects to `/monitoring`, that a
client-sent `X-QEOS-User-Email` header opens nothing, that a non-superuser gets 403 from
`/api/v1/auth/grafana-session`, that a superuser's cookie gets Grafana, that a forged user header
on the break-glass port `127.0.0.1:3000` is refused (401 `auth-proxy.invalid-ip`; skipped, and
said so, when that port is not reachable), and that `qeos_monitor` cannot read table data. It creates its own superuser (`smoke-super-…@example.com`) directly in the
database, like the invitee. With monitoring off it checks that `/grafana/` is a JSON 404. CI runs
the smoke both ways.

### 2.7 Trust the local HTTPS certificate

On its first start, the gateway generates a self-signed certificate for `localhost`,
`127.0.0.1`, `gateway` and `host.docker.internal`, valid for 825 days. It is stored in the
`qa-vision_qav_gateway_certs` volume. Export it once:

PowerShell:
```powershell
docker compose cp gateway:/etc/nginx/certs/tls.crt $HOME\qeos-ca.crt
```
bash (in Git Bash, `MSYS_NO_PATHCONV=1` stops it rewriting the container path):
```bash
MSYS_NO_PATHCONV=1 docker compose cp gateway:/etc/nginx/certs/tls.crt ~/qeos-ca.crt
```

Then do one or both of the following:

- **For the collector and scripts**, pass `--ca-file ~/qeos-ca.crt` (or set `QEOS_CA_FILE`).
  This is the recommended way. The collector always verifies certificates and has no "insecure"
  switch.
- **For browsers**, add it to the OS trust store:
  - Windows: `Import-Certificate -FilePath $HOME\qeos-ca.crt -CertStoreLocation Cert:\CurrentUser\Root`
    and confirm the dialog. Edge and Chrome use this store. Firefox needs its own import
    (Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import).
  - macOS: `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/qeos-ca.crt`
  - Debian/Ubuntu: `sudo cp ~/qeos-ca.crt /usr/local/share/ca-certificates/qeos-localhost.crt && sudo update-ca-certificates`

  Restart the browser afterwards.

**Using your own certificate** (for example for a LAN host name the self-signed one does not
cover): copy `tls.crt` and `tls.key` into the volume, then restart the gateway:
```
docker compose cp my.crt gateway:/etc/nginx/certs/tls.crt
docker compose cp my.key gateway:/etc/nginx/certs/tls.key
docker compose restart gateway
```
In production, Caddy obtains a real Let's Encrypt certificate and none of this is needed.

**Verify (section 2):** `https://localhost:8443` opens the QEOS sign-in page without a warning,
and `curl.exe https://localhost:8443/health --ssl-no-revoke` (PowerShell) or
`curl --cacert ~/qeos-ca.crt https://localhost:8443/health` (bash) succeeds without `-k`.

**Common problems (section 2)**

| Symptom | Fix |
|---|---|
| `set SECRET_KEY (shared by every service)` on any compose command | `.env` is missing, is not in the repository root, or does not contain the variable. |
| `port is already allocated` | Another program uses 8080 or 8443. Set `GATEWAY_HTTP_PORT=18080` (or `GATEWAY_HTTPS_PORT`) in `.env`. |
| `--wait` fails and a `*-migrate` job exited 1 | `docker compose logs auth-migrate` (or the failing one). The usual cause is a `POSTGRES_PASSWORD` that differs from the one the volume was created with. |
| `exec … no such file or directory` while building | A shell script got CRLF endings. Re-checkout it: `git checkout -- <file>`. |
| `curl` on Windows fails on a trusted certificate | Windows checks revocation, which a local CA does not publish. Add `--ssl-no-revoke`. |
| The smoke test fails with `SECRET_KEY is not set` | Export the variables first (`set -a; . ./.env; set +a`). |

---

## 3. Accounts, organizations and access

### 3.1 First account and email verification

1. On the sign-in page, choose **Create account** and register with an email and a password.
2. **Verify the email.** QEOS sends a link. Without SMTP ([3.2](#32-email-smtp)) the link is
   written to the auth-service log instead:

   PowerShell:
   ```powershell
   docker compose logs auth-service | Select-String "Verification email"
   ```
   bash:
   ```bash
   docker compose logs auth-service | grep "Verification email"
   ```
   Open the `https://localhost:8443/verify-email?token=…` link. It creates the account and
   signs you in. A link works **once** and expires after **24 hours**. Until it is used,
   nothing is reserved: registering again sends a new link.

### 3.2 Email (SMTP)

Prerequisite: an SMTP server that offers STARTTLS (or plain SMTP on a trusted relay).

1. Add to `.env`:
   ```
   SMTP_HOST=smtp.example.com
   SMTP_PORT=587
   SMTP_USER=…
   SMTP_PASSWORD=…
   EMAILS_FROM_EMAIL=qeos@example.com
   # optional: SMTP_TLS=false (relay without STARTTLS), EMAILS_FROM_NAME=QEOS
   ```
2. Apply it: `docker compose up -d --wait gateway`. This recreates `auth-service`,
   `ingestion-service` and `weekly-summary`, the three containers that send mail.

What sends email: verification links, password-reset links, and **email** notification
channels ([4.5](#45-notifications)). Invitations are **never** emailed: you copy the link
([3.5](#35-invitations)).

**Verify:** Settings → Notifications → add an Email channel → **Send test**. "Last delivery"
shows success, or the SMTP error. Or register a second account and check the inbox.

### 3.3 Organization and project

1. On first sign-in, **Welcome to QEOS** asks for an organization. Enter a name and choose
   **Create organization**. You become its **owner**.
2. Under the organization, enter a project name and choose **Create project**. Only owners and
   admins can create projects.
3. Optional: in the project's **Settings → Repositories**, add the repository your tests live
   in. GitHub, GitLab and Azure DevOps URLs are accepted. QEOS checks it anonymously and shows
   **Reachable**, **Not found or private** (a private repository looks the same as a missing
   one), or **Not checked** (the provider was unreachable or rate-limited; use **Check again**
   later). The repository is saved in every case. This card is informational: uploads,
   imports and Play do not depend on it.

### 3.4 Roles

Roles are per **organization**. There are no project-level members: your organization role
applies to every project in it.

| Can… | owner | admin | member | viewer / billing_manager |
|---|---|---|---|---|
| Read everything in the organization's projects | ✓ | ✓ | ✓ | ✓ |
| Create API keys, revoke them, edit cases, suites, imports, masking, notifications, quarantine, retention days | ✓ | ✓ | ✓ | |
| Play and Stop runs from QEOS | ✓ | ✓ | ✓ | |
| Create, rename and delete projects; legal hold; export; Run from QEOS settings (GitHub token) | ✓ | ✓ | | |
| Invite people and remove members | ✓ | ✓ | | |
| Grant or remove the `owner`/`admin` role | ✓ | | | |

Someone who is not a member gets "not found", never "forbidden". There is no UI for changing a
member's role: remove the member and invite them again with the new role.

### 3.5 Invitations

1. Sidebar → **Organization** (or "Members and invitations" on the project list).
2. Under **Invitations**, enter the email, pick a role, and choose **Invite**.
3. Choose **Copy link**. The `https://…/invitations/<token>` link is shown **once**. Send it
   to the person yourself.
4. The invitee creates an account (or signs in) and opens the link. The link expires after
   **7 days** and works once. Pending invitations can be revoked from the same page.

Anyone who is signed in and holds the link can accept it: QEOS does not check that the email
matches. Treat the link like a password.

### 3.6 Passwords

- **Forgot password:** sign-in page → **Forgot password?**. Without SMTP, the link is in the log:
  `docker compose logs auth-service | Select-String "Password reset email"` (PowerShell) or
  `… | grep "Password reset email"` (bash). It works **once** and expires after **30 minutes**.
  Using it signs out every device.
- **Change password:** user menu → **Security** (`/account/security`) → **Password**. Other
  devices are signed out.
- Accounts created through Google or Microsoft have no password here.
- Sessions: an access token lasts 60 minutes and is refreshed silently. The refresh session
  lasts 30 days.

### 3.7 Two-factor authentication (MFA)

Each user turns it on for themselves. Nothing needs to be configured on the server.

1. User menu → **Security** → **Two-factor authentication (TOTP)** → start enrollment.
2. Scan the QR code with an authenticator app (or type the secret in by hand), and enter
   the 6-digit **Code from the app**.
3. Save the **recovery codes**. They are shown **once**. Each one works a single time, in
   place of a code.
4. From then on, password sign-in asks for a code. To turn it off, enter a current code or a
   recovery code under the same section.

MFA covers password sign-in. Google and Microsoft sign-in rely on the provider's own MFA.

**Lost the authenticator and every recovery code?** There is no self-service reset. An
administrator with shell access to the host can clear it:
```
docker compose exec postgres psql -U postgres -d auth_db -c "DELETE FROM mfa_recovery_codes WHERE user_id = (SELECT id FROM users WHERE email = 'user@example.com'); UPDATE users SET mfa_enabled = false, mfa_secret = NULL WHERE email = 'user@example.com';"
```

### 3.8 Single sign-on (Google and Microsoft)

Optional. Without it, sign-in is email and password. GitHub SSO and SAML are **not
implemented**.

Two halves must match:

- The **dashboard** shows a button only when its client id was baked in at build time
  (`VITE_*` in `.env`, passed as build arguments).
- **auth-service** verifies the provider's ID token and must know the same client id.
  Without it, `POST /api/v1/sso/{google|microsoft}` answers 503.

**The stock `docker-compose.yml` does not pass auth-service's SSO variables.** Add a
`docker-compose.override.yml` next to it (Compose merges it automatically when you run
`docker compose` without `-f`):

```yaml
# docker-compose.override.yml (local file; keep it out of git if it holds tenant ids you consider private)
services:
  auth-service:
    environment:
      GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID:-}
      AZURE_CLIENT_ID: ${AZURE_CLIENT_ID:-}
      AZURE_ALLOWED_TENANTS: ${AZURE_ALLOWED_TENANTS:-}
```
In production, add it explicitly:
`docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml -f docker-compose.override.yml …`.

**Google**

1. Google Cloud Console → APIs & Services → Credentials → **Create OAuth client ID** →
   *Web application*. Under **Authorized JavaScript origins**, add the address you open QEOS
   at (`https://localhost:8443`, or `https://qeos.example.com`).
2. In `.env`, set the same id twice:
   ```
   VITE_GOOGLE_CLIENT_ID=1234-abc.apps.googleusercontent.com
   GOOGLE_CLIENT_ID=1234-abc.apps.googleusercontent.com
   ```
3. Rebuild the dashboard and recreate auth-service: `docker compose up -d --build --wait gateway`.

**Microsoft (Entra ID)**

1. Entra ID → App registrations → New registration. Platform: **Single-page application**.
   Redirect URI: the address you open QEOS at, for example `https://localhost:8443`. Enable
   **ID tokens**.
2. In `.env`:
   ```
   VITE_MSAL_CLIENT_ID=<Application (client) ID>
   AZURE_CLIENT_ID=<the same id>
   AZURE_ALLOWED_TENANTS=<your tenant id>[,<another tenant id>]
   # optional: VITE_MSAL_AUTHORITY=https://login.microsoftonline.com/<tenant id>
   ```
3. `docker compose up -d --build --wait gateway`.

A sign-in from a tenant that is not in `AZURE_ALLOWED_TENANTS` is refused, and its tenant id
is logged by auth-service, so you can copy it from there. The account email is the user
principal name. Personal Microsoft accounts are not supported.

Account rules: the first sign-in with a new address creates an account without a password.
An address that already has a password account is **not** linked automatically: the answer
is 409. The `POST /api/v1/users/me/link/{google|microsoft}` API links them for a signed-in
user. The dashboard has no button for this.

**Verify (section 3):** the sign-in page shows the Google / Microsoft buttons, and signing in
lands on the project list. `docker compose logs auth-service` shows no "not configured".

**Common problems (section 3)**

| Symptom | Fix |
|---|---|
| "Invalid or expired verification token" | Links work once and for 24 h. Already used: sign in. Expired: register again. |
| No verification email | SMTP not configured. Take the link from the auth-service log. |
| SSO button visible but sign-in fails with 503 | The dashboard has the `VITE_*` id but auth-service does not. Add the override file above. |
| SSO button missing | The `VITE_*` value was set after the build. Rebuild with `--build`. |
| Google: "origin not allowed" | Add the exact origin, including the port, to Authorized JavaScript origins. |
| Invitee sees "not found" on the link | The link was already used, revoked, or is older than 7 days. Invite again. |
| 429 Too Many Requests on sign-in | 5 requests per second per IP on the auth routes. Wait a second. |

---

## 4. Features

Each feature lists **what it does**, **prerequisites**, **setup**, **verify** and **limits**.
In UI paths, "Settings" always means the project's **Settings** in the sidebar.

### 4.1 Sending test results

**What it does.** After your tests run, `qeos-collector` reads the report files, turns them
into **one run** (branch, commit, CI job link, environment, results) and uploads it with the
project's API key. Everything else (Overview, Runs, Flaky, Trends, KPIs, notifications) is
built from these runs.

**Prerequisites:** a project ([3.3](#33-organization-and-project)), tests that write a supported
report, and a CI runner (or your machine) that can reach `QEOS_URL` over HTTPS.

#### 4.1.1 API keys

1. Settings → **API keys** → enter a name (for example `github-actions`) → **Create key**.
   Owners, admins and members can do this.
2. Choose **Copy key**. The full key (`qeos_…`) is shown **only once**. Afterwards only its
   prefix is visible.
3. Store it as a **CI secret** named `QEOS_API_KEY`. Never put it in a file, a flag or a
   workflow input. The collector reads it only from the environment and never prints it.

One key belongs to one project. Use one key per CI system, so you can revoke one without
breaking the others. The **Last used** column shows whether a key is still in use.
Revoking a key works immediately ([4.9](#49-security-operations)). Old `qav_…` keys keep
working.

**Test suggestions.** Keys are upload-only by default. To let `qeos-collector impact` and
`run-impact` read this project's test suggestions (the likely affected tests for a change), an
owner or admin ticks **Can read test suggestions** when creating the key, or turns the key's
**Test suggestions** switch on in the table later. The column reads On or Off for every role;
members create upload-only keys. A key without it gets `403 impact_not_allowed` from
`POST /api/v1/collect/impact`. Such a key reads only test names, path units, aggregate failure
evidence and which named tests failed in the branch's latest run; never failure messages, stack traces or other runs'
details ([SECURITY.md](../SECURITY.md)). A revoked key
cannot be changed.

#### 4.1.2 Report formats

The collector reads, and detects from the file content:

- **JUnit XML**: pytest (`--junitxml=reports/junit.xml`), Maven Surefire
  (`target/surefire-reports/*.xml`, including flaky reruns), Playwright
  (`--reporter=junit`), cucumber-js, and anything else that writes `<testsuites>`/`<testsuite>`.
- **.NET TRX** (`dotnet test --logger trx`), **NUnit 3**, **xUnit.net v2**, **TestNG**.
- **Cucumber JSON** (cucumber-jvm/js/rb): one result per scenario. Needed for the automatic
  link between Gherkin cases and results ([4.2](#42-test-cases)).
- **Playwright JSON** (`--reporter=json`): each retry is kept, so a flaky spec shows as fail
  plus pass.

Formats can be mixed in one upload. Files over 50 MB, malformed XML, and XML with a DOCTYPE
are skipped with a warning.

#### 4.1.3 Collector CLI (any machine)

PowerShell:
```powershell
pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@collector-v0.6.0#subdirectory=collector"
$env:QEOS_URL = "https://localhost:8443"
$env:QEOS_API_KEY = "<your key>"
qeos-collector check "reports/**/*.xml" --ca-file $HOME\qeos-ca.crt     # verifies everything, uploads nothing
qeos-collector upload "reports/**/*.xml" --ca-file $HOME\qeos-ca.crt
```
bash:
```bash
pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@collector-v0.6.0#subdirectory=collector"
export QEOS_URL=https://localhost:8443
export QEOS_API_KEY=<your key>
qeos-collector check "reports/**/*.xml" --ca-file ~/qeos-ca.crt
qeos-collector upload "reports/**/*.xml" --ca-file ~/qeos-ca.crt
```

- Pin the tag (`collector-v0.6.0`) for strict reproducibility, or use the floating `collector-v0` (the latest
  0.x release; it moves on every stable release, so a new collector reaches your CI without an edit; the
  GitHub Action and the Jenkins `ref` accept it). `--ca-file` is needed only for the local
  self-signed certificate or a private CA.
- `check` tests, in order: the URL, TLS trust, the API key (it names the project), and that the
  files match and parse. It exits 2 on the first failure.
- `upload --dry-run` prints the JSON and sends nothing. It needs neither a URL nor a key.
- Exit codes: `0` uploaded (or the platform was unreachable: by default, an outage never turns a
  build red); `1` the upload failed and `--fail-on-error` or `--gate` is set; `2` a
  configuration error (no URL or key, no file matched, `http://` to a non-localhost address,
  a bad `--ca-file`, an invalid `--trigger`).

Useful options (flag / environment variable): `--environment` / `QEOS_ENVIRONMENT` (set it per
CI matrix leg; it makes flaky detection precise), `--trigger` / `QEOS_TRIGGER`
(`manual`, `automatic` or `qeos`; [4.1.8a](#418a-manual-runs-and-the-run-trigger)), `--branch`, `--commit`, `--ci-run-url`
(detected automatically on GitHub, GitLab, Jenkins and Azure), `--component NAME@SHA` /
`QEOS_COMPONENTS` (the product build an E2E suite ran against, up to 20), `--fail-on-error`,
`--gate` ([4.4](#44-analytics), quarantine), `--spool DIR` (keeps undelivered parts and
resends them next time), `--no-changes` (skip the git change list), and `--client-cert` /
`--client-key` (mTLS). Defaults can live in a `.qeos.yml` in the working directory (`url`,
`environment`, `ca-file`, `spool`, `fail-on-error`, `patterns`, `components`, `features`).
The API key is never read from that file. Full reference: [`collector/README.md`](../collector/README.md).

With a `CODEOWNERS` file (root, `.github/` or `docs/`), each result carries its owners, which
are shown on the run page. For a list of changed files per run, check out at least two commits
(`fetch-depth: 2` on GitHub).

#### 4.1.4 GitHub Actions

1. Repository → Settings → Secrets and variables → Actions:
   - **Secret** `QEOS_API_KEY` = the project's API key
   - **Variable** `QEOS_URL` = `https://qeos.example.com` (no trailing slash)
2. After the test step (the tests must write a report), add:
   ```yaml
   - uses: carneiru/QA-Vision-Platform/collector-action@collector-v0.6.0
     if: always()                      # report failing builds too
     with:
       url: ${{ vars.QEOS_URL }}
       patterns: "reports/**/*.xml"    # space-separated globs
       # environment: staging
       # extra-args: --ca-file certs/ca.pem --fail-on-error
     env:
       QEOS_API_KEY: ${{ secrets.QEOS_API_KEY }}
   ```
   The action installs the collector at its own tag. It needs Python and git on the runner,
   which GitHub-hosted runners have.

#### 4.1.5 GitLab CI

1. Project → Settings → CI/CD → Variables: `QEOS_URL`, and `QEOS_API_KEY` as **masked**.
2. In `.gitlab-ci.yml`:
   ```yaml
   include:
     - remote: https://raw.githubusercontent.com/carneiru/QA-Vision-Platform/collector-v0.6.0/templates/qeos-collector.gitlab-ci.yml

   qeos-collector-upload:
     variables:
       QEOS_PATTERNS: "reports/**/*.xml"
       # QEOS_ENVIRONMENT: staging
       # QEOS_EXTRA_ARGS: "--fail-on-error"
   ```
   The template adds a `qeos-collector-upload` job in the `.post` stage that always runs. The
   test job must keep its report as an artifact (`artifacts: when: always, paths: [reports/]`)
   so the upload job can read it. Alternatively, run the collector in the test job's
   `after_script`, as `collector/README.md` shows.

#### 4.1.6 Azure Pipelines

1. Pipeline → Edit → Variables → add `QEOS_API_KEY` and tick **Keep this value secret**.
2. Copy `templates/qeos-collector.azure-pipelines.yml` into your repository and, after the
   test step:
   ```yaml
   steps:
     - template: templates/qeos-collector.azure-pipelines.yml
       parameters:
         url: https://qeos.example.com
         patterns: "reports/**/*.xml"
         # environment: staging
         # failOnError: true
   ```
   Or use the inline step that Settings → Wire up your CI shows. Either way, the secret
   **must be mapped in `env:`** (`QEOS_API_KEY: $(QEOS_API_KEY)`), because Azure never hands
   secrets to scripts by itself. An unmapped secret arrives as the literal text
   `$(QEOS_API_KEY)` and the upload fails with 401.

#### 4.1.7 Jenkins

1. Install the shared library: copy `collector-jenkins/vars/qeosCollectorUpload.groovy` (and
   `qavCollectorUpload.groovy`, if old Jenkinsfiles use it) into your existing shared library,
   or mirror `collector-jenkins/` into its own repository and register it as a Global Pipeline
   Library named `qeos`. Details: [`collector-jenkins/README.md`](../collector-jenkins/README.md).
2. Add a **Secret text** credential with the id `qeos-api-key`.
3. In the Jenkinsfile (the agent needs Python 3.9+ and git):
   ```groovy
   @Library('qeos') _
   post {
     always {
       withCredentials([string(credentialsId: 'qeos-api-key', variable: 'QEOS_API_KEY')]) {
         withEnv(['QEOS_URL=https://qeos.example.com']) {
           qeosCollectorUpload(patterns: 'reports/**/*.xml', ref: 'collector-v0.6.0')
         }
       }
     }
   }
   ```
   Optional parameters: `environment`, `caFile`, `failOnError`, `extraArgs`, `source` (a pip
   requirement for an internal mirror).

#### 4.1.8 Any other CI, or a private CA

Run the CLI from [4.1.3](#413-collector-cli-any-machine) as a step that always runs, with
`QEOS_URL` and `QEOS_API_KEY` in the step's environment. Set `--branch`, `--commit` and
`--ci-run-url` yourself if your CI is not detected (`--ci-provider other`).

If `QEOS_URL` uses a certificate from a **private/corporate CA**, give the collector the CA
certificate: `--ca-file`, `QEOS_CA_FILE`, `ca-file:` in `.qeos.yml`, `extra-args: --ca-file …`
in the GitHub action, or `caFile:` in Jenkins. Through a proxy, `HTTPS_PROXY` and `NO_PROXY`
are honoured.

#### 4.1.8a Manual runs and the run trigger

From 0.5.0 the collector sends how each run started (`manual`, `automatic` or `qeos`), detected from the CI
environment; `--trigger` / `QEOS_TRIGGER` overrides it. Any other value than `manual`, `automatic` or
`qeos` is a configuration error (exit 2). Collectors older than 0.5.0 send no trigger, so their runs are
always collected.

A project can switch manual collection off: **Settings › Collection**, the switch "Collect runs started
manually in CI". Everyone in the project sees it; only owners and admins can change it. While it is off, the
platform answers 202 and stores nothing, and the collector prints
`qeos: run not collected: manual runs are not collected for this project` and exits 0. With `--gate` it
decides on the local results instead (`gate: decided on local results (run not collected)`): exit 1 when
any test failed or errored, so a person's re-run of a failing job still fails the required check. The card counts the
manual uploads not collected and when the last one arrived (uploads, not runs: a matrix run uploads once
per job). Turning it on or off never touches stored runs. Runs started from QEOS are always collected.
The detection table is in the [collector README](../collector/README.md#run-trigger-and-manual-runs).
Two cases:

- **A script dispatching with a person's token** looks manual (the triggering actor is that person). Use a
  GitHub App or `GITHUB_TOKEN` for automated dispatches, or pass `--trigger automatic` in that workflow.
- **GitLab's remote template** uploads from its own `.post` job, where `CI_JOB_MANUAL` (per job) is not
  seen, so a manual test job in an automatic pipeline is stored as automatic. Pass `--trigger manual`
  through `QEOS_EXTRA_ARGS`, or upload from the test job itself.
- **The collector container image** sees only the variables passed to it. Without `GITHUB_EVENT_NAME`,
  `GITHUB_TRIGGERING_ACTOR`, `GITHUB_RUN_ATTEMPT` and the event file (`GITHUB_EVENT_PATH`, mounted), the
  trigger is unknown and the run is collected. The composite action and `pip` installs need nothing extra.

In the workflow that uploads, use `collector-action@collector-v0.5.0` or later (or the floating
`@collector-v0`); an older pin sends no trigger and everything is collected. A workflow QEOS dispatches
(**Run from QEOS**) keeps its `request_id` input, so its runs are `qeos` and always collected. If the same
workflow can also be started by hand and you want those runs collected, set the trigger on the step:

```yaml
- uses: carneiru/QA-Vision-Platform/collector-action@collector-v0
  if: always()
  with:
    url: ${{ vars.QEOS_URL }}
    patterns: "reports/**/*.xml"
  env:
    QEOS_API_KEY: ${{ secrets.QEOS_API_KEY }}
    QEOS_TRIGGER: automatic   # omit to let a hand-started run count as manual
```

#### 4.1.9 Hosted CI against a local stack (tunnel)

GitHub-, GitLab- and Microsoft-hosted runners cannot reach `localhost`. For a short pilot, a
tunnel gives the local stack a public address. **Check your company's policy first**: while it
is open, your machine is reachable from the internet.

1. In a separate window, start the tunnel and keep the window open:
   ```powershell
   & "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url https://localhost:8443 --no-tls-verify
   ```
   (bash: `cloudflared tunnel --url https://localhost:8443 --no-tls-verify`.) It prints an
   address like `https://random-words.trycloudflare.com`.
2. Set that address as `QEOS_URL` in the CI system. No `--ca-file` is needed: the tunnel
   presents a public certificate.
3. Limits: the address **changes every time the tunnel restarts** (a new random name; the old
   one stops resolving), so update `QEOS_URL` in every repository that uses it, each time.
   While the tunnel runs, its current address is at `http://127.0.0.1:20241/quicktunnel`
   (`{"hostname": "..."}`). To read it and update a GitHub repository in one go:
   ```bash
   gh variable set QEOS_URL -R <owner>/<repo> --body "https://$(curl -s http://127.0.0.1:20241/quicktunnel | sed 's/.*"hostname":"\([^"]*\)".*/\1/')"
   ```
   A named tunnel (`cloudflared tunnel create`, with a DNS route on a domain in Cloudflare)
   keeps one hostname, so `QEOS_URL` is set once. Results sent while the tunnel or the laptop is down are lost; builds stay green.
   Links in notifications still point to `https://localhost:8443`. For anything lasting, go to
   [production](#6-production).

The alternative is a **self-hosted runner** on your own network, which can reach your machine.
Pass `--ca-file` for the self-signed certificate.

**Verify (4.1):** `qeos-collector check …` exits 0, then the project's **Overview** shows the
run within a few seconds (the dashboard polls every 30 s). **Runs** lists it with its branch,
commit and CI link. Settings → **Wire up your CI** always shows a ready-to-paste snippet with
this deployment's address filled in.

**Limits (4.1):** 20,000 results per run (the collector splits bigger uploads into `part 1 of N`
runs); messages and output are cut at 64 KB; `finished_at` may be at most 1 hour in the future;
uploads are limited to 10 requests per second per IP (burst 20). Retries are safe: the
Idempotency-Key makes a repeated upload return the stored run instead of storing a duplicate.

---

### 4.2 Test cases

**What it does.** **Test cases** holds written cases (title, steps, labels, priority, status)
and links each case to the automated test that implements it. Cases come from two places:
written by hand (**manual**) or **imported** from Gherkin `.feature` files, where each scenario
becomes one case. Suites are ordered lists of cases.

**Prerequisites:** a project. For links to results: uploads that contain the same tests
(Cucumber JSON for Gherkin, [4.1](#41-sending-test-results)).

#### 4.2.1 Manual cases

1. Sidebar → **Test cases** → **New case**.
2. Fill in the title, description, steps (action and expected result), labels, priority
   (`low`, `medium`, `high`, `critical`) and status (`draft`, `ready`, `archived`).
3. Optional: link it to an automated test that QEOS has seen in uploads. **Unlink** removes the
   link.

Cases are numbered per project: `TC-1`, `TC-2`, …

#### 4.2.2 Gherkin import from the dashboard

1. **Test cases** → **Import from Gherkin**.
2. Drop a folder or `.feature` files, or use **Choose folder** / **Choose files**.
3. **Path prefix**: the stored paths must match what your test runner reports. For example,
   if you chose the `features/` folder but the runner reports `tests/features/…`, enter
   `tests/`. This is what links imported cases to their results, and Play needs paths under
   `tests/features/` ([4.3](#43-run-from-qeos-play-and-stop)).
4. **This is my complete features folder**:
   - **Off** (default): only the chosen files are compared. Nothing else is archived, and a
     renamed file's scenarios are created again.
   - **On**: cases whose file is missing are **archived**, and renamed files keep their case
     numbers.
5. **Preview** shows the plan (created, updated, moved, reactivated, archived) and any syntax
   errors or warnings. Then choose **Import N changes**. If someone else imported in the
   meantime, QEOS asks you to review the new plan.

The repository owns an imported case: its title, steps, labels and Gherkin are read-only in
QEOS, while status, priority and suites stay editable. A scenario that disappears from an
imported file is archived.

**How tags become fields:**

| Gherkin tag | Becomes |
|---|---|
| `@smoke`, `@checkout` | labels `smoke`, `checkout` (lower-cased; `:` becomes `-`) |
| `@ADO:12345` | label `ado-12345`, which the **Azure DevOps** filter lists as 12345 |
| `@priority:high` (`low`/`medium`/`high`/`critical`) | the case's priority, not a label |
| Feature and Rule tags | inherited by every scenario |

Invalid tags are skipped with a warning. A case keeps at most 20 labels, each matching
`[a-z0-9._-]{1,40}`.

#### 4.2.3 Keeping cases in sync from CI (`import-features`)

**How the sync works.** QEOS never fetches `.feature` files. It keeps no read access to your
repositories: the repository card in Settings is checked anonymously, so a private repository
shows **Not found or private**, and that is expected. Instead the repository **sends** its files
by running `qeos-collector import-features` in its own CI. CI already knows when the files
change, the same command works on every CI system, and the only secret is the project API key
(ADR-023, ADR-024). The cost: **each repository needs a workflow file, and it stays there.** If
you delete it, the sync stops.

**What one run does.**
- It trades the API key for a 5-minute token that can only import cases into the key's
  project. Changes are recorded as made by CI.
- It reads the `.feature` files that match the pattern, with paths relative to the working
  directory, and sends them all.
- It is a **full** sync by default: new scenarios become cases, changed ones are updated, and
  the cases of deleted files are archived. `--no-full` compares only the files given and never
  archives anything.
- A full sync that would archive more than half of the imported cases is refused (exit 1, 409
  `mass_archive`) unless you pass `--allow-mass-archive`.
- `--dry-run` prints the plan and changes nothing. `--strict` exits 1 when a file fails to parse.

**Which branch it syncs from.** Only the repository's **default branch** (`main` or `master`).
The collector reads it from the GitHub Actions event (`repository.default_branch`), GitLab's
`CI_DEFAULT_BRANCH`, or the clone's `origin/HEAD`. On any other branch it prints
`skipped: on <branch>; cases sync from <default>` and exits 0, so the same step can run on
every build. Where the default branch cannot be read (Azure Pipelines, most Jenkins agents) it
falls back to `master`: set `QEOS_IMPORT_BRANCH` (or pass `--branch`) to name the branch
yourself. On Jenkins the agent must also know the current branch (`GIT_BRANCH`); otherwise the
command cannot tell and imports anyway, so guard the stage with
`when { branch '<default branch>' }`. Run locally, outside CI, there is no branch check.

**Paths must match the report.** A case links to its results through a key built from the
Feature name, the file path and the scenario name. The paths the sync sends must be the paths
your Cucumber report records, normally relative to the repository root
(`tests/features/...`). So run the command from the repository root, and do not mix it with a
dashboard import whose paths carry another prefix (for example the name of the folder you
picked, such as `MyRepo/tests/features/...`).

##### Set it up on GitHub Actions

1. In the repository: **Settings → Secrets and variables → Actions**.
   - **Variables** tab: `QEOS_URL`, the QEOS address (no trailing `/`, no spaces).
   - **Secrets** tab: `QEOS_API_KEY`, a key from the QEOS project the cases belong to
     ([4.1.1](#411-api-keys)).

   Put them at repository level. Values set on an **Environment** reach a job only when the job
   names that environment.
2. Commit this file as `.github/workflows/qeos-sync-cases.yml` on the default branch:
   ```yaml
   name: QEOS sync test cases

   on:
     push:
       paths: ["tests/features/**"]
     workflow_dispatch:
       inputs:
         first_sync:
           description: "First sync only: allow archiving the old dashboard-imported cases"
           type: boolean
           default: false

   jobs:
     sync:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with: { python-version: "3.12" }
         - run: pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@collector-v0.6.0#subdirectory=collector"
         - run: qeos-collector import-features "tests/features/**/*.feature" ${{ inputs.first_sync && '--allow-mass-archive' || '' }}
           env:
             QEOS_URL: ${{ vars.QEOS_URL }}
             QEOS_API_KEY: ${{ secrets.QEOS_API_KEY }}
   ```
   Change the pattern and `paths:` if your features live elsewhere.
3. Run it once by hand: **Actions → QEOS sync test cases → Run workflow**. Tick `first_sync`
   only if the project already has imported cases under other paths (see below).

**When it runs.**
- **Automatically, on every push that changes a file under `tests/features/`**, on any branch.
  On the default branch it syncs. On another branch the job starts, prints `skipped`, and ends
  green in a few seconds. Merging a pull request is a push to the default branch, so a merge
  syncs. A push that changes no file under `tests/features/` does not start the workflow.
- **By hand**, from the Actions tab (**Run workflow**), for the first sync or to resync at any
  time.
- **Never on a schedule, and never from QEOS.** Editing a case in QEOS does not change the
  repository, and a changed file does nothing until it is pushed.

**First sync after a dashboard import.** If the cases were first imported from the dashboard
with other paths, the first full sync sees all of them as deleted and is refused with 409
`mass_archive`. Run the workflow by hand once with `first_sync` ticked. It archives the old
cases and creates them again under the right paths. **They get new TC numbers**: suite
membership and status or priority edits on the old cases do not carry over, and archived
numbers are never reused. Leave `first_sync` off from then on; a push never sets it.

##### Other CI systems and the command line

The same command works anywhere, with `QEOS_URL` and `QEOS_API_KEY` in the step's environment.
The snippets under Settings → **Wire up your CI** include it for GitLab, Azure Pipelines,
Jenkins and the CLI.

To run it once from your own machine, from the **repository root** (the folder that contains
`tests/`):
```powershell
$env:QEOS_URL = "https://qeos.example.com"
$env:QEOS_API_KEY = "<project API key>"
qeos-collector import-features "tests/features/**/*.feature" --dry-run
qeos-collector import-features "tests/features/**/*.feature"
```
(bash: `export QEOS_URL=...` and `export QEOS_API_KEY=...`.) `QEOS_URL` can also go in
`.qeos.yml` (`url: ...`); the key cannot: it is read from `QEOS_API_KEY` only. Against the local
stack on `https://localhost:8443`, add `--ca-file qeos-ca.crt` ([4.1.3](#413-collector-cli-any-machine)).

#### 4.2.4 Finding cases: folders, features, labels, filters and chips

- **Search** matches the title and the Gherkin text. `TC-12`, `tc12` or `12` also finds case 12
  and puts it first.
- **Folder**: the folders of imported cases (their `.feature` paths); subfolders are included.
- **Filters** (expand the filters disclosure): Label, Status (default "Draft and ready";
  archived cases are hidden unless you pick Archived), Priority, Origin (Manual / Imported),
  Link (Linked / Not linked), **Latest result** (Passed / Failed / Skipped / Never ran),
  Feature (the Gherkin `Feature:` name), and **Azure DevOps** (cases labelled `ado-<n>`).
- **Quick chips**: one click for **Failing**, **Never ran** and **Linked**. Active filters appear
  as chips that you can remove one by one, or all at once with **Clear all**. Filters live in the URL, so
  a filtered view can be bookmarked and shared.
- **Last runs** column: for each linked case, its status in the project's last 10 runs, oldest
  to newest (Passed, Failed, Re-run, Skipped, Didn't run). Unlinked cases show "not linked".

Suites: **Test cases** → **Suites** tab → create a suite (its name must be unique), add cases,
order them, and **Run suite** ([4.3](#43-run-from-qeos-play-and-stop)). Deleting a suite keeps
its cases.

**Verify (4.2):** after an import, **View imported cases** lists them with a file icon. After the
next upload of the same suite, the **Last runs** column fills in and the **Failing** chip
works.

**Limits (4.2):** title 200 characters; 50 steps of up to 2,000 characters; 20 labels; 1,000 cases
per suite; import limits from `IMPORT_MAX_*` (over a limit: 413, with a message that names the
setting; raise it in `.env` and run `docker compose up -d --wait gateway`). Two scenarios with
the same name in one file: the second is skipped. The "Latest result" filter falls back to the
other filters when a project has more than 20,000 tests.

**Common problems (4.2)**

| Symptom | Fix |
|---|---|
| Imported cases never get a "Last runs" strip | The import paths do not match the runner's report paths. Re-import with the right **Path prefix**, and upload Cucumber JSON. |
| CI step always prints `skipped: on main; cases sync from master` | The CI does not expose the default branch (Azure Pipelines, Jenkins). Set `QEOS_IMPORT_BRANCH=main`. |
| CI import exits 1 with 409 `mass_archive` | The first sync after a dashboard import with other paths: run the workflow once with `first_sync`. Otherwise the pattern found too few files (wrong glob or wrong working directory): fix it. |
| `qeos: no platform URL: pass --url, set QEOS_URL, or add url to .qeos.yml` | Locally: set `QEOS_URL` in the shell. In GitHub Actions: the step has no `env:` with `QEOS_URL: ${{ vars.QEOS_URL }}`, or the value is under **Secrets** or an Environment instead of the repository's **Variables**. |
| `qeos: no .feature files match tests/features/**/*.feature` | Not run from the repository root. `cd` to the folder that contains `tests/`. |
| `cannot reach the platform ([Errno -2] Name or service not known)` | `QEOS_URL` names a host that no longer exists, usually an old quick-tunnel address ([4.1.9](#419-hosted-ci-against-a-local-stack-tunnel)). |
| The repository shows **Not found or private** in Settings | Expected for a private repository: the check is anonymous. Uploads and the sync do not depend on it. |
| 413 on import | Raise `IMPORT_MAX_*` and `GATEWAY_IMPORT_MAX_BODY` together. |

---

### 4.3 Run from QEOS (Play and Stop)

**What it does.** Select imported cases (or a suite) and choose **Run**. QEOS starts a dedicated
GitHub Actions workflow in your test repository (`workflow_dispatch`) for exactly those
scenarios, shows its progress, and lets you **Stop** it. QEOS never runs test code itself. The
results come back through the normal upload ([4.1](#41-sending-test-results)).

**Run likely affected.** On **Test cases**, members and above can choose **Run likely affected**:

1. Enter a branch; it defaults to the CI target's branch. Choose **Find tests**.
2. QEOS takes the newest run with changed files among the branch's last 20 runs, scores that change now
   (the same likely affected tests as on the run page, see [Test impact](#test-impact)) and selects the cases linked
   to the suggested tests, strongest first, at most 200. Only imported cases are selected: Play cannot run a
   manual case.
3. Review the selection; the duration estimate follows it. Then **Run selected** as usual.

Suggested tests that no case links to are listed as *not runnable from QEOS (no linked case)*; link them by
setting an imported case's automated test. Tests linked only to manual cases are listed as *not runnable from QEOS
(linked only to a manual case)*. When no recent run of the branch has changed files (the CI checkout had fewer
than 2 commits, see [4.1.3](#413-collector-cli-any-machine)), when the project has too little history and nothing else applies,
or when nothing is suggested, the panel says so and selects nothing; so does a run whose changed files can no longer
be read ("Run #N has no readable change data"). Viewers do not get the button.

**Prerequisites**

- The test repository is on **GitHub**. Other CI providers are not supported for Play.
- The suite uses **cucumber-js** with `.feature` files under **`tests/features/`**, and the
  cases were imported with those paths ([4.2](#42-test-cases)). Manual cases cannot be run.
- The server can reach `api.github.com`, and GitHub's runners can reach `QEOS_URL` to upload
  results (production, or a tunnel for a pilot).
- `TM_SECRETS_KEY` is set ([2.3](#23-every-variable-in-env)).

**Setup**

1. **Server:** set `TM_SECRETS_KEY` in `.env`, then `docker compose up -d --wait gateway`.
   Without it, Settings shows "Running tests from QEOS is not configured on this server".
2. **Workflow files, on the repository's default branch.** GitHub dispatches only workflows that
   exist there:
   - `.github/workflows/qeos-run.yml`: copy it from Settings → **Run from QEOS** → **How to set it
     up** (that copy already guards the branch you configure), or from
     [`templates/github/qeos-run.yml`](../templates/github/qeos-run.yml) (then change
     `refs/heads/main` in the `if:` to your branch).
   - `.github/scripts/qeos-run.mjs`: from the same place, or
     [`templates/github/qeos-run.mjs`](../templates/github/qeos-run.mjs).
   - If the branch you will run on is not the default branch, both files must exist on **that
     branch as well**: the run reads them from there.
3. **Adapt the template to your repository.** It was written for one suite and assumes:
   - a local action `./.github/actions/setup-test-env` fed by a secret `ENV`. Replace this step
     with your own setup (for example `actions/setup-node`, `npm ci`, installing browsers,
     writing your env file);
   - a cucumber-js profile named **`ci`**, and a JSON report at
     **`test-results/cucumber-report.json`** (the upload step and the "no scenario matched"
     check read it);
   - `runs-on: ubuntu-24.04`, a 200-minute timeout, and one run at a time (`concurrency: qeos-run`).

   Keep the `workflow_dispatch` inputs (`paths`, `names`, `request_id`) and the `run-name`
   (`QEOS #<id>`) exactly as they are: QEOS finds its run by that name.
4. **Repository secrets and variables** (Settings → Secrets and variables → Actions): secret
   `QEOS_API_KEY` (a project API key), variable `QEOS_URL` (the QEOS address), plus whatever
   your own setup step needs.
5. **GitHub token.** GitHub → your profile → Settings → Developer settings → Personal access
   tokens → **Fine-grained tokens** → Generate new token:
   - Resource owner: the repository's owner. If that is an organization, it may need to
     approve the token.
   - Repository access: **Only select repositories** → only the test repository.
   - Permissions → Repository: **Actions: Read and write**. Nothing else (Metadata: read is
     added automatically).
   - Expiration: your policy. QEOS warns owners and admins 14 days before it expires.
6. **QEOS:** Settings → **Run from QEOS** (owners and admins only): **Repository link** (paste
   the repository's GitHub address, such as `https://github.com/owner/name`; `owner/name` also
   works, and the line under the field shows `Runs in owner/name`), **Workflow file**
   (`qeos-run.yml`), **Branch** (`main`), **Token** → **Save**. QEOS checks the token with GitHub
   before it stores it, and tells you if the token is invalid or expired, has no Actions access,
   or the repository or workflow is not found. The card then shows
   `Connected: owner/name · token …abcd · expires …` and who changed it last.
   After a save, the repository is also added to Settings → **Repositories** if it is not there
   yet, with a note saying so. A private repository shows **Not found or private** there: that
   check is anonymous, and Play does not depend on it.

**Use**

- **Test cases** → tick imported cases → **Run selected (N)** → check the list and
  `repo @ branch` → **Run**.
- Or open one case → **Run**, or a suite → **Run suite** (its manual cases are skipped).
- The run panel on **Test cases** (and on the case page) shows the state, a link to the GitHub
  run, and **Stop**. **Runs → Requested runs** lists every request, with who started or stopped it.
- When the workflow's upload step finishes, the run appears under **Runs** like any other.
  If it never arrives, the panel says "Results not received: check the QEOS upload step".

**Verify (4.3):** the GitHub **Actions** tab shows a run named `QEOS #<id>`. It runs only the
selected scenarios, then a new run appears in QEOS.

**Limits (4.3)**

- 200 cases per run, and one active run per project. Workers 1, retries 0.
- GitHub is polled at most every 5 s, and only while someone is looking.
- A dispatch whose run is not seen within 2 minutes ends as `failed_to_start`. A Stop issued
  before the run is found is applied on GitHub only within that window.
- If the token loses access, or you change the repository in Settings, an active request ends
  as `cancelled` while the GitHub run may continue.
- Selection is by file and exact scenario name. Outline `<placeholders>` match any example
  value. A renamed or moved scenario no longer matches: re-import, then run again.
- **Security:** the token can start, cancel and delete *any* `workflow_dispatch` workflow in that
  repository, and those workflows run with its secrets. Prefer a repository where
  `qeos-run.yml` is the only `workflow_dispatch` workflow. The token is stored encrypted with
  `TM_SECRETS_KEY`, is never shown again (only its last 4 characters), and can be removed
  with **Disconnect**.

**Common problems (4.3)**

| Symptom | Fix |
|---|---|
| Play disabled, "not configured on this server" | Set `TM_SECRETS_KEY` and recreate (`docker compose up -d --wait gateway`). |
| Save: "repository or workflow not found…" | Either the **token cannot see the repository** (a fine-grained token whose resource owner is your account instead of the organization, a token the organization has not approved, or a classic token not authorized for the organization's SSO), or the workflow file is not on the **default** branch, or its name differs. To tell which, with the same token: `curl -H "Authorization: Bearer <token>" https://api.github.com/repos/<owner>/<name>` (404: the token) and `.../repos/<owner>/<name>/actions/workflows/qeos-run.yml` (404: the file). |
| Save, or a run "Didn't start": "token has no Actions access… resource owner is "<owner>"…" | The message names the repository's owner. A fine-grained token reaches only the repositories of the owner picked when it was made, and that defaults to your own account: create a new one with that owner (the organization, for an organization's repository), access to the test repository and **Actions: Read and write**. The owner may also have to approve it. The token's page in GitHub says "This token does not have access to any repositories" until all three are right. |
| 422 "re-import the .feature files first" | The case was imported before scenario names were stored. Run a full import once. |
| Job fails with "path not allowed" | The case's path is not under `tests/features/`. Fix the import's **Path prefix**. |
| Run ends with "No scenario matched this QEOS selection" | The scenario was renamed or moved. Re-import, then run again. |
| `failed_to_start` | The workflow's `if:` guard does not match the configured branch, or the files are missing on that branch. |
| GitHub run passed but QEOS shows no results | `QEOS_URL`/`QEOS_API_KEY` are missing in the repository, the report path is wrong, or the runner cannot reach QEOS. |
| "The GitHub token expires on …" banner | Create a new token, then Settings → Run from QEOS → **Replace token**. |

---

### 4.4 Analytics

Nothing to configure beyond [sending results](#41-sending-test-results). The background job
`analytics-rollup` (started by compose) keeps the flaky statistics fast. Every role can read
everything listed here.

| View (sidebar) | What it shows | Options |
|---|---|---|
| **Overview** | Widgets; by default the latest run, its failures grouped by cause, the pass rate this week and flaky tests in the last 14 days. | **Customise** (every role): move, resize, remove and add widgets, change their settings, then **Save**. Owners and admins: **Edit project default**. See [Customise the Overview](#customise-the-overview). |
| **Runs** | Every run, newest first, with counts and duration. | Status (With failures / All green), Branch; **More filters**: Environment, CI, Commit (4+ hex), Pull request, Author, From, To; sort by Failed or Duration. Tab **Requested runs** ([4.3](#43-run-from-qeos-play-and-stop)). |
| Run page | Results, failures grouped by cause (new, or failing for N runs in a row), owners from CODEOWNERS, changed files with the **likely affected tests** beside them (evidence, and which new failures were suggested or missed), components, a link to the CI job. | **Compare with previous run #N**. |
| Compare (`runs/<id>/compare/<base>`) | New failures, fixed, still failing, slower (≥1 s and ≥50 %), added, removed. Up to 200 each. | Choose any other run of the project. |
| **Test results** | Every test seen in the window: runs, pass rate, average duration, last status. Click a test for its history. | 7 / 30 / 90 days, sort, search, CSV. |
| **Flaky** | Tests that both pass and fail. **Confirmed**: passed and failed on the same commit in the same environment. **Suspected**: the result flips between consecutive runs on a branch. | Window 7/14/30/90 days, minimum runs, minimum flip rate, branch. **Quarantine** / **Release** (members and above). |
| **Branches** | Per-branch runs, counts and pass rate. **Compare A / Compare B** charts two branches' daily pass rates. | 7 / 30 / 90 days. |
| **Trends** | Runs, results, pass rate and duration over time. | 7 / 30 / 90 days, Daily / Weekly / Monthly, branch, environment. |
| **Report** | Summary, pass rate by week, flaky tests, branches, the top failing and slowest tests, and **Test impact**: how often the likely affected tests stored with each run contained its new failures, how many tests they suggested per run, and the misses. | Period 7 / 30 / 90 days (Test impact uses the Report's period when it is the last 7, 14 or 30 days up to today, and 30 days otherwise); **Save as PDF** (the browser's print dialog), **Download CSV**. |

- **Pass rate** = passed ÷ (executions − skipped). Errored counts as not passed.
- **Confirmed flaky needs environments.** Set `QEOS_ENVIRONMENT` (or `environment:` in the action)
  per CI matrix leg. Otherwise every leg shares one environment, and a failure that happens on
  only one leg looks flaky.
- **Quarantine and the build gate.** A quarantined test keeps running and showing up, but its
  failures stop counting. To let quarantine decide whether the build fails, add `--gate` to the
  upload (`extra-args: --gate` in the action) and let the test step itself not fail the job
  (`continue-on-error: true` on GitHub, `continueOnError: true` on Azure, `allow_failure: true`
  on GitLab). With `--gate`, the collector exits 1 when there are failures outside quarantine,
  or when the upload did not happen.
- **Weekly summary**: an email, Slack, Teams or webhook message on Mondays, set up per channel
  in [4.5](#45-notifications).

#### Test impact

Nothing to configure. **What it needs:** runs uploaded with changed files (the collector sends them by default;
`--no-changes` turns that off, and the CI checkout needs at least 2 commits) and 20 runs with changed files in
the last 90 days before suggestions appear. The `impact-rollup` job (started by compose) rebuilds the statistics
every 24 hours.

- **Run page, Likely affected tests** (beside **Changes**): the suggested tests come strongest first, each with its
  evidence (in how many of the runs that changed a file or folder the test newly failed, and how often it fails
  normally). Tests always included carry a label instead: *test file changed*, *failing on this branch* or *no
  history yet*. The suggestion was made at upload, before the results. While the outcome is being written the card
  says so and updates itself; then it says which new failures were suggested and which were missed. A run with no
  change data gets a compact one-line card.
- **Not enough history yet:** below 20 runs with changed files only the labelled tests are listed.
- **Report, Test impact** and the Overview widget **Impact accuracy:** the catch rate, caught ÷ (caught + missed)
  new failures in runs that had a stored suggestion, over 7, 14 or 30 days, with the average number of tests
  suggested per run beside it (suggesting everything catches everything), live and replayed apart, and the misses.
- **Run likely affected** on **Test cases**: see [4.3](#43-run-from-qeos-play-and-stop).
- **Replay history:** to fill the figure from past runs, run once
  `docker compose run --rm impact-rollup python -m src.ingestion.jobs.impact_rollup --backfill-days 30`
  (1 to 90 days). Those runs are scored with statistics from earlier days only, marked *replayed* and counted
  apart. It takes its own lock and can take long on a large project (about 1 min per replayed day on a busy one): run it
  once, off hours.
- **What counts:**
  - a test newly fails when it fails after passing on the same branch (or on the base branch for a new branch);
    flaky and muted tests never do;
  - lock files and `dist/`, `build/`, `vendor/`, `node_modules/` are ignored;
  - a change of more than 300 files counts by folder;
  - a change list the collector truncated is still scored but not learned from.
- **Monitoring:** the job's heartbeat is `impact_rollup`, and the JobStale alert fires after two days without a pass.

#### Customise the Overview

Every role can arrange their own Overview, per project: **Customise** in the Overview header opens
edit mode. Move widgets up or down, make them wide or normal, open a widget's settings (rows, period,
branch; **All branches** is the default), remove it, or **Add widget**, which also offers three
templates that replace the draft: **QA lead** (Pass-rate trend, Failure causes, Regressions and flips,
Coverage, Test cases), **Developer** (Latest run, Failing in latest run, Branch health, Recent runs, My
recent failures) and **Flaky hunt** (Flaky tests over 30 days, Regressions and flips, Slowest tests,
Pass-rate trend by day). The page shows your draft;
nothing changes until **Save**. **Reset to project default** puts the default back in the draft, and
Save then removes your own layout, so later changes to the default reach you again. **Cancel**
discards the draft, asking first when you changed something. If the same layout was saved elsewhere
meanwhile, Save offers **Reload** (start again from the stored layout) or **Overwrite**. A layout
holds at most 24 widgets, and a widget type may appear more than once with different settings.

**Widgets** (15; settings are a period of 7, 14 or 30 days, 5 or 10 rows, a view, a branch or a name):

- **Latest run**, **Failing in latest run**, **Pass rate this week** and **Flaky tests**: the built-in
  four cards.
- **Pass-rate trend:** the Trends view's chart, per day over 30 days or per week or month over 90 days.
- **Failure causes**, **Regressions and flips** and **Slowest tests:** the Report's figures over the
  period (30 days by default), on all branches or one; the title opens the Report at that section.
- **Coverage:** active, linked and manual cases, automated cases not run in the period, and tests
  without a case, across every branch.
- **Recent runs:** the newest runs with their verdicts, on all branches or one.
- **Branch health:** each branch's pass rate, runs and last run over 30 days, newest first.
- **Test cases:** the Cases tiles, wide by default.
- **My suites:** the suites you created.
- **Impact accuracy:** how often the likely affected tests stored with each run contained its new failures, over 7, 14 or 30 days on every branch, with how many tests were suggested per run; replayed runs are counted and said.
- **My recent failures:** failed runs whose commit author is you. It matches the name git records
  exactly (ignoring case): by default your QEOS full name. If git spells it differently, or your profile
  has no full name, set **Your name in git** in its settings; with no name at all it says so and loads
  nothing.

Recent runs and My recent failures read the newest page of runs (50), so older failures beyond that
page do not appear. A widget set to a branch with no runs in its period says so ("No runs on release
in the last 30 days") with **Change settings**, which opens edit mode on that widget's settings.

Owners and admins also set the **project default**, which everyone without a personal layout sees:
**Customise → Edit project default**. The bar says who changed it last; Save asks for confirmation
(**Save for everyone**); **Reset to built-in default** goes back to the four standard widgets.

**Verify (4.4):** after two or more uploads, **Trends** shows points, and **Compare with previous
run** appears on the newer run.

**Limits (4.4):** the Test results view goes back at most 90 days, Trends up to 365 days through the
API, Flaky up to 90 days and 100 tests. Flaky needs at least `min runs` executions (5 by default).

---

### 4.5 Notifications

**What it does.** It sends a message when a run with failed or errored tests arrives (the
counts, branch, commit, the first 5 failing tests and a link to the run). On Mondays it can
also send last week's summary (runs, executions, pass rate against the week before, failures,
the five most-failing tests, and a link to the Report).

**Prerequisites:** results arriving ([4.1](#41-sending-test-results)). For email: SMTP
([3.2](#32-email-smtp)). Run links use the gateway address (in production, `https://QEOS_DOMAIN`),
which compose sets automatically.

**Setup:** Settings → **Notifications** → **Add a channel** (owners, admins and members):

| Kind | What to paste |
|---|---|
| **Slack** | An incoming webhook: Slack app → Incoming Webhooks → Add New Webhook to Workspace. It must be on `https://hooks.slack.com/`. |
| **Microsoft Teams** | A Workflows webhook: in the channel, … → Workflows → "Post to a channel when a webhook request is received", then copy its URL (`*.logic.azure.com` or `*.powerplatform.com`). Office 365 connectors are retired. |
| **Webhook** | Any **public** `https://` address on port 443, with no credentials in the URL. It receives JSON with `event: "run.failed"` or `event: "weekly.summary"`. |
| **Email** | Up to 5 addresses, separated by commas. |

Then give it a **Name**, an optional **Only branch** (an exact match, for example `main`), and
tick **Failed runs** and/or **Weekly summary (Mondays, 07:00 UTC)**. Use **Send test** (a
sample) and **Send summary** (last week's real summary) to try it. **Pause** / **Resume**
turns a channel off and on without deleting it.

**Verify (4.5):** **Send test** arrives, and the **Last delivery** column shows success (or the
error the receiver returned).

**Limits (4.5):** 10 channels per project. One attempt per message, with a 5-second timeout and
no retry queue; a failed delivery is recorded and shown. A replayed upload sends nothing. Webhook
URLs are secrets: after saving, only the host and the last 4 characters are shown. Addresses
that resolve to private, loopback or link-local networks are refused, so a webhook on your
LAN or in Docker does not work. The weekly hour is fixed at 07:00 UTC in the compose stack.

---

### 4.6 Masking

**What it does.** Before anything is stored, QEOS masks secrets and personal data in failure
messages, output, commit subjects and CI URLs. A masked value becomes `[REDACTED:<kind>]` and
the rest of the text stays readable. Built-in rules are always on: private keys,
`Authorization` headers, URL passwords, JWTs, GitHub/GitLab/AWS/Slack/Stripe/Google/npm tokens,
QEOS API keys, `password=` / `secret:` / `token` style values, cookies, email addresses and card
numbers. Test names, suites, files and branches are never changed.

**Setup (optional, your own patterns):** Settings → **Masking** → **Add a pattern**: a name and
an RE2 regular expression (no backreferences or lookarounds). Paste a sample failure message and
choose **Preview** to see the masked result and the match count. Then **Add pattern**. Owners,
admins and members can do this; there are at most 20 patterns per project.

**Results stored before a rule existed** are re-masked on demand:
```
docker compose exec ingestion-service python -m src.ingestion.jobs.remask --dry-run
docker compose exec ingestion-service python -m src.ingestion.jobs.remask            # add --project <id> for one project
```
It is safe to repeat.

**Verify (4.6):** the smoke test checks masking. Manually: upload a result whose message contains
`ann@acme.test`. The run page shows `[REDACTED:email]`.

---

### 4.7 Retention, legal hold and export

**Retention.** The `ingestion-retention` job (started by compose) deletes runs older than the
project's retention period once a day. The default is **90 days**, and the range is 1 to 365.
Settings → **Data** shows the current value. **It can only be changed through the API** (owners,
admins and members):

bash:
```bash
TOKEN=$(curl -s --cacert ~/qeos-ca.crt -X POST https://localhost:8443/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"…"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
curl --cacert ~/qeos-ca.crt -X PATCH https://localhost:8443/api/v1/projects/<project_id>/settings \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"result_retention_days": 180}'
```
PowerShell:
```powershell
$login = Invoke-RestMethod -Method Post https://localhost:8443/api/v1/auth/login -ContentType "application/json" -Body '{"email":"you@example.com","password":"…"}'
Invoke-RestMethod -Method Patch "https://localhost:8443/api/v1/projects/<project_id>/settings" -Headers @{ Authorization = "Bearer $($login.access_token)" } -ContentType "application/json" -Body '{"result_retention_days": 180}'
```
(An account with MFA gets a challenge instead of a token from `/auth/login`. Use an account
without MFA, or complete the challenge with `POST /api/v1/auth/mfa/verify`. PowerShell 5.1 needs
the local certificate trusted in Windows, [2.7](#27-trust-the-local-https-certificate).)

When a project is deleted, its API keys are revoked on the next retention pass, and its runs
are deleted 7 days later. Until then, the deletion can still be undone.

**Legal hold.** Settings → **Data** → enter a **Reason** → **Place legal hold** (owners and
admins). While a project is held, retention deletes **nothing** of it, whatever its age. The
hold records who placed it, when, and why. **Release legal hold** ends it; the next retention
pass then deletes anything older than the period.

**Export.** Settings → **Data** → **Download all results** (owners and admins). It downloads
every run and result as NDJSON (`qeos-project-<id>-<date>.ndjson`), masked as stored. Do this
before you delete a project or answer a data request. The Test results view and the Report also offer
CSV downloads.

**Verify (4.7):** `docker compose logs ingestion-retention` shows one JSON line per pass (with
`projects_held`). A dry run:
`docker compose run --rm -T ingestion-retention python -m src.ingestion.jobs.retention --dry-run`.

---

### 4.8 Ctrl K search and KPI tiles

**Search.** Press **Ctrl K** (**⌘K** on a Mac), press **/** anywhere outside a text field, or
click the search box in the top bar. Nothing to configure. It finds:

| Group | Searches | When |
|---|---|---|
| Recent | What you opened lately (kept in this browser, per user). | With an empty query. |
| Pages | The project views, All projects, each organization, Security. | Always. |
| Projects | Project names in every organization you belong to. | When you type. |
| Test cases | Title and Gherkin text; `TC-12`, `tc12` or `12` finds case 12. | Inside a project, from 2 characters. |
| Test results | Test names seen in the last 30 days. | Inside a project, from 2 characters. |
| Suites | Suite names. | Inside a project, from 2 characters. |
| Runs | Branch names that contain the text. `#433` or `433` opens run 433. | Inside a project, from 2 characters. |

Each group shows up to 5 matches. If a source cannot answer, its group says so and the others
still work.

**KPI tiles** (top of **Test cases**):

| Tile | Meaning | Click |
|---|---|---|
| Cases | All cases (archived ones excluded), and how many are imported. | — |
| Pass rate | This week's pass rate, and the change in points against last week. | — |
| Failing | Linked cases whose latest result failed. | Applies the **Failing** filter. |
| Flaky | Flaky tests in the last 14 days (quarantined ones excluded), and how many are quarantined. | Opens **Flaky**. |

Failing and Pass rate need [results](#41-sending-test-results). Failing also needs linked
cases ([4.2](#42-test-cases)). The tiles refresh at most once a minute.

---

### 4.9 Security operations

**Revoke or rotate an API key.** Settings → **API keys** → **Revoke**. Uploads that use it fail
with 401 straight away. To rotate a key: create a new one, update the CI secret, check that
**Last used** moves to the new key, then revoke the old one. Before you delete a project,
revoke its keys or export its data.

**Rotate the GitHub token (Run from QEOS).** Create a new fine-grained token
([4.3](#43-run-from-qeos-play-and-stop)). Settings → **Run from QEOS** → **Replace token** →
**Save**. Then revoke the old token on GitHub (Settings → Developer settings → Fine-grained
tokens → Revoke). **Disconnect** removes the token from QEOS completely; it is refused while a run is active.

**Rotate server secrets** (edit `.env`, then `docker compose up -d --wait gateway`):

| Secret | Effect of changing it |
|---|---|
| `SECRET_KEY` | Everyone is signed out. API keys, invitation links and stored data are not affected. |
| `INTERNAL_API_PASSWORD` | No effect for users. Every service that uses it is recreated with the new value. |
| `TM_SECRETS_KEY` | **Stored GitHub tokens become unreadable.** Owners must save the token again. Change it only if it leaked. |
| `POSTGRES_PASSWORD` | **Do not just edit `.env`**: the database keeps its old password. Change it inside the database first, then in `.env`: `docker compose exec postgres psql -U postgres -c "ALTER USER postgres PASSWORD '<new>'"`, then `docker compose up -d --wait gateway`. |

**Sessions.** A password change or reset signs out every other device. Access tokens cannot be
revoked and live 60 minutes. Refresh sessions last 30 days. MFA: [3.7](#37-two-factor-authentication-mfa).

**What is recorded (audit).** QEOS has no central audit-log page. What it records:

- API keys: when each was created, last used and revoked (Settings → API keys).
- Run from QEOS settings: every change, with who and when ("Last changed by … on …"). The trail
  is kept even after Disconnect.
- Run requests: who started and who stopped each one (Runs → Requested runs).
- Legal hold: who placed it, when, and the reason (Settings → Data).
- Quarantine: who quarantined a test.
- Imports from CI: recorded as made by CI.
- The gateway writes one JSON access-log line per request, with an `X-Request-ID` that is
  passed on to the services: `docker compose logs gateway`.

**Built-in protections, for reference.** Rate limits per IP: 20 requests/s on the API, 5/s on
sign-in, MFA, registration and password routes, and 10/s on uploads. Internal APIs and
`/metrics` are not routed by the gateway. The collector never follows redirects, so the key goes
only to `QEOS_URL`.

---

## 5. Wiring a real test repository end to end

This is the full setup for a typical Gherkin/cucumber-js repository on GitHub. It is the same
pattern as the first production suite that used QEOS, with no secrets from that suite. You end
up with three workflows that share **one** secret (`QEOS_API_KEY`) and **one** variable (`QEOS_URL`).

**Before you start:** QEOS reachable from GitHub (production, or a tunnel for a pilot), a
project, and an API key ([4.1.1](#411-api-keys)).

**Step 1. Repository settings.** Settings → Secrets and variables → Actions:
secret `QEOS_API_KEY`, variable `QEOS_URL`.

**Step 2. Make the suite write Cucumber JSON.** For example, in the cucumber-js profile your CI
uses:
```js
format: ["json:test-results/cucumber-report.json", /* your other formatters */]
```
JUnit also works for results, but the automatic link between imported cases and results needs
Cucumber JSON (feature `uri` = the `.feature` path).

**Step 3. Upload results from the existing suite workflow(s).** After the test step, in every
workflow that runs the suite (scheduled, per area, nightly…):
```yaml
      - name: Upload results to QEOS
        if: always() && vars.QEOS_URL != ''      # skipped cleanly where QEOS is not set up
        uses: carneiru/QA-Vision-Platform/collector-action@collector-v0.6.0
        with:
          url: ${{ vars.QEOS_URL }}
          patterns: test-results/cucumber-report.json
          environment: staging                    # one value per target environment / matrix leg
        env:
          QEOS_API_KEY: ${{ secrets.QEOS_API_KEY }}
```
Use `actions/checkout` with `fetch-depth: 2` if you want the changed files on each run. If
several jobs run in parallel shards, each uploads its own run, and that is expected.

**Step 4. Keep cases in sync.** Commit `.github/workflows/qeos-sync-cases.yml` from
[4.2.3](#423-keeping-cases-in-sync-from-ci-import-features) on the default branch and keep it
there: every push that changes `tests/features/**` syncs the cases. Run it once by hand
(Actions → QEOS sync test cases → Run workflow) for the first import, with `first_sync` ticked
if the cases were already imported from the dashboard under other paths.

**Step 5. Play and Stop.** Add `qeos-run.yml` and `qeos-run.mjs` on the default branch and adapt
the setup step, as in [4.3](#43-run-from-qeos-play-and-stop) steps 2–4. Create the fine-grained
token and save it in Settings → **Run from QEOS**.

**Step 6. Optional extras.**
- Notifications to the team channel for `main` only ([4.5](#45-notifications)).
- A `CODEOWNERS` file, so failing tests name their owners.
- `--component product-api@<sha>` in `extra-args`, to record which product build the suite ran
  against.
- `extra-args: --gate`, plus `continue-on-error: true` on the test step, to let quarantine
  decide whether the build fails.

**Verify the whole chain**

1. Push a change to a `.feature` file on `main`: the sync workflow imports it, and **Test cases**
   shows the new or updated case.
2. Run the suite workflow: a run appears under **Runs**, and the cases' **Last runs** strip fills in.
3. Select two cases → **Run selected (2)** → **Run**: `QEOS #<id>` appears in GitHub Actions,
   and a new run appears in QEOS when it finishes.

Templates and references: [`templates/github/`](../templates/github/),
[`collector/README.md`](../collector/README.md), [`collector-action/action.yml`](../collector-action/action.yml).

---

## 6. Production

Move to a VM when colleagues depend on the data, hosted CI must report all the time, or results
become worth keeping. The full guide is **[`deploy/README.md`](../deploy/README.md)**. In short:

1. An Ubuntu 24.04 VM (2 vCPU, 4 GB RAM, 30 GB disk is enough for a pilot), a DNS A record, and
   inbound 443 and 80 from anywhere, plus 22 from your IP only. With monitoring ([7.4](#74-monitoring-optional)), use 8 GB RAM.
2. Install Docker, clone the repository, then:
   ```bash
   bash deploy/init-env.sh qeos.example.com ops@example.com
   docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build --wait edge
   ```
   `init-env.sh` writes `.env` (mode 600) with `QEOS_DOMAIN`, `ACME_EMAIL`, `SECRET_KEY`,
   `INTERNAL_API_PASSWORD`, `POSTGRES_PASSWORD` and `TM_SECRETS_KEY`. Caddy (`edge`) obtains and
   renews the Let's Encrypt certificate and is the only service with published ports.
3. Add SMTP ([3.2](#32-email-smtp)), and SSO if you use it ([3.8](#38-single-sign-on-google-and-microsoft)).
   Remember the extra `-f` for an override file.
4. Schedule `deploy/backup.sh` daily with cron, and copy `backups/` off the VM.
5. **Back up `.env` separately**, in a password manager or vault. It holds `POSTGRES_PASSWORD`
   (needed to use a restored database) and `TM_SECRETS_KEY` (needed to read the stored GitHub
   tokens). A database backup without the matching `.env` is only half a backup.
6. Point every repository's `QEOS_URL` at `https://qeos.example.com`. No `--ca-file` is needed.

**Moving a local pilot to the VM:** dump the local database ([7.3](#73-backups-local-stack)),
restore it on the VM (`deploy/README.md` §7), and copy the local `TM_SECRETS_KEY` into the VM's
`.env` before the first start if you want to keep the stored GitHub tokens. Then change
`QEOS_URL` everywhere and close the tunnel.

**Upgrading an install from the QA Vision days** (`deploy/README.md`, "Upgrading from QA Vision names"):

- In `.env`, rename `QAV_DOMAIN` to **`QEOS_DOMAIN`**. Compose stops with "set QEOS_DOMAIN" until
  you do. Change `EMAILS_FROM_NAME=QA Vision` to `QEOS` if it is set. Every other variable
  keeps its name.
- An install made before Run from QEOS has no `TM_SECRETS_KEY`. Add it once (see
  [2.2](#22-create-env)), then start again.
- `backup.sh` still reads `QAV_BACKUP_DIR` / `QAV_BACKUP_KEEP_DAYS` when the `QEOS_*` names are
  unset.
- CI keeps working: `QAV_URL` / `QAV_API_KEY`, the `qav-collector` command, `qav_` keys, the
  `qavCollectorUpload` Jenkins step and old GitLab template variables all still work, with a
  deprecation warning. Move to `QEOS_*` and `collector-v0.6.0` when convenient. On Azure, a
  secret still named `QAV_API_KEY` must be renamed, or mapped as `QEOS_API_KEY: $(QAV_API_KEY)`.
- Data does not move: the volumes keep their `qa-vision_qav_*` names, pinned in the compose files. If Compose asks to
  recreate a volume, answer **N**.

---

## 7. Upgrades and maintenance

### 7.1 Updating

Local:
```
git pull
docker compose up -d --build --wait gateway
```
Production (`qeos` = `docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml`):
```bash
bash deploy/backup.sh          # always before an update
git pull
qeos up -d --build --wait edge
```

- **Migrations run automatically.** On every `up`, `db-init` creates any new database and each
  `*-migrate` job runs `alembic upgrade head` before its service starts. If a migration fails,
  its service does not start and `--wait` reports it: read
  `docker compose logs <service>-migrate`.
- If `docker-compose.yml` or `.env.example` changed in the pull, compare `.env` with
  `.env.example` for new variables.
- **One-off steps after some upgrades:** after test-management migrations 003 (Feature names)
  and 004 (scenario names for Play), run one **full** Gherkin import per project (dashboard
  with "This is my complete features folder", or `import-features` from CI). After new masking
  rules, run the `remask` job ([4.6](#46-masking)).
- **Collector:** CI pins a tag (`collector-v0.6.0`). Upgrading the platform does not change it.
  Move pipelines to a new tag when the release notes ask for it.
- **Compose project renamed to `qeos` (2026-10-11).** Containers are now `qeos-*` and local images
  `qeos/*`. Once, before the first `up` after pulling this change, stop the old project:
  `docker compose -p qa-vision down` (never `-v`; the volumes keep their pinned names and data). Without
  it the old containers still hold port 8443 and the fixed subnet, and `up` fails. The old
  `qa-vision/*:local` images can then go: `docker image ls -q 'qa-vision/*' | xargs docker image rm`.
- Old images pile up: `docker image prune` removes the unused ones. Never prune volumes
  ([2.5](#25-stop-restart-and-why-never-down--v)).

### 7.2 Routine checks

| What | How |
|---|---|
| Everything healthy | `docker compose ps` |
| Retention ran | `docker compose logs --since 25h ingestion-retention` |
| Weekly summary sent | `docker compose logs weekly-summary` (Mondays after 07:00 UTC) |
| Notification failures | Settings → Notifications → Last delivery |
| GitHub token expiry | Settings → Run from QEOS (a warning appears 14 days before) |
| Disk | `docker system df` |
| Local certificate | Valid for 825 days. To regenerate: `docker compose exec gateway rm /etc/nginx/certs/tls.crt /etc/nginx/certs/tls.key`, `docker compose restart gateway`, then trust it again ([2.7](#27-trust-the-local-https-certificate)). |

### 7.3 Backups (local stack)

Production uses `deploy/backup.sh` (daily, keeps 14 days; see `deploy/README.md` §7). For a
local stack:

PowerShell (writes the file inside the container first, so PowerShell's own encoding cannot
damage it):
```powershell
docker compose exec -T postgres pg_dumpall -U postgres -f /tmp/qeos-backup.sql
docker compose cp postgres:/tmp/qeos-backup.sql .\qeos-backup.sql
```
bash:
```bash
docker compose exec -T postgres pg_dumpall -U postgres | gzip > qeos-backup.sql.gz
```

Restore onto an **empty** volume with the **same** `.env`:
```
docker compose up -d --wait postgres
docker compose cp ./qeos-backup.sql postgres:/tmp/qeos-backup.sql
docker compose exec -T postgres psql -U postgres -f /tmp/qeos-backup.sql
docker compose up -d --build --wait gateway
```
One `ERROR: role "postgres" already exists` during the restore is expected.

### 7.4 Monitoring (optional)

Prometheus, Alertmanager and Grafana with node-exporter, cAdvisor and postgres-exporter, as the compose
profile `monitoring`. In `.env`:

```
COMPOSE_PROFILES=monitoring
GRAFANA_ADMIN_PASSWORD=<letters and digits>
MONITORING_DB_PASSWORD=<letters and digits>
```

then `docker compose up -d --build --wait gateway prometheus alertmanager grafana node-exporter cadvisor postgres-exporter`. Prometheus then scrapes every service, and Alertmanager sends alerts to the channels you
set. Five dashboards are provisioned. With `MONITORING_ENABLED=true` the gateway serves Grafana at
`https://localhost:8443/grafana/` to superusers only: sign in to the dashboard as a superuser and choose
**Monitoring** in the account menu (any Grafana link works too: the dashboard's `/monitoring` page hands
the sign-in over and comes back). Break-glass, when auth-service is down: Grafana's own admin login on
the machine that runs the stack, `http://localhost:3000/grafana/login`, user `admin`. Alert channels, resources,
break-glass access from a VM, the security notes and turning it off: `deploy/README.md` section 10.
Every service also serves `/metrics` inside the compose network whether or not the profile is on; the
gateway never routes it.

The gateway always joins a Docker network fixed at `172.30.1.0/24`, with monitoring on or off. If
`docker compose up` fails with an address-pool overlap, set `GRAFANA_FRONT_SUBNET`,
`GRAFANA_FRONT_IP_RANGE` and `GATEWAY_GRAFANA_FRONT_IP` in `.env` (`deploy/README.md`, "Address range").

---

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Compose: `set SECRET_KEY …`, `set INTERNAL_API_PASSWORD …` | `.env` is missing or lacks the variable. Run compose from the repository root. |
| Compose: `set QEOS_DOMAIN …` (production) | An install from before the rename: rename `QAV_DOMAIN` to `QEOS_DOMAIN` in `.env`. |
| `port is already allocated` | Set `GATEWAY_HTTP_PORT=18080` / `GATEWAY_HTTPS_PORT=…` in `.env`. |
| A `*-migrate` job exits 1: `password authentication failed` | `POSTGRES_PASSWORD` in `.env` differs from the one the volume was created with. Restore the old value, or change it inside the database ([4.9](#49-security-operations)). |
| `exec … no such file or directory` building a container | A shell script has CRLF endings. `git checkout -- <file>`; `.gitattributes` forces LF. |
| All data gone after a restart | Someone ran `down -v` or pruned volumes. Restore from a backup ([7.3](#73-backups-local-stack)). |
| Browser certificate warning after it was trusted | The certificate was regenerated (volume deleted, or older than 825 days). Export and trust it again. |
| `curl` on Windows fails on a trusted local certificate | Add `--ssl-no-revoke`. In PowerShell, use `curl.exe`, not `curl`. |
| Signed out after editing `.env` | `SECRET_KEY` changed. Sign in again; API keys keep working. |
| No verification or reset email | SMTP not configured: the links are in `docker compose logs auth-service`. If SMTP is configured, check that log for the SMTP error. |
| 429 Too Many Requests | Per-IP rate limit (5/s on sign-in, 20/s API, 10/s uploads). Wait a second. Behind a proxy in production, check `GATEWAY_TRUSTED_PROXIES` (set by the prod file). |
| SSO button shows, sign-in answers 503 | auth-service lacks `GOOGLE_CLIENT_ID` / `AZURE_CLIENT_ID` + `AZURE_ALLOWED_TENANTS`: use the override file ([3.8](#38-single-sign-on-google-and-microsoft)). |
| Collector exits 2 | A configuration problem (URL, key, no matching files, `http://` URL, bad `--ca-file`, invalid `--trigger`). `qeos-collector check` names it. |
| My run doesn't appear in QEOS | Check Settings › Collection and the collector's `run not collected` line: the run looked manual and the project does not collect manual runs ([4.1.8a](#418a-manual-runs-and-the-run-trigger)). Pass `--trigger automatic` if it is not. |
| `collector-action` fails with `has an empty revision (after @)` | collector-action 0.5.1 and earlier built its install URL from variables GitHub leaves empty inside reusable workflows. Use `@collector-v0.5.2` or later, or the floating `@collector-v0`. |
| Collector: certificate verify failed | Local stack: `--ca-file` with the gateway certificate. Private CA: `--ca-file` with that CA. |
| Upload 401 | Wrong, revoked or missing key. On Azure, the secret is not mapped in `env:` (you see the literal `$(QEOS_API_KEY)`). |
| CI build is green but no run arrives | `QEOS_URL` missing or unreachable (hosted runner → localhost, or a closed tunnel). By default the collector never fails the build; add `--fail-on-error` while you debug. |
| Run arrives without branch or commit | CI not detected: pass `--branch` / `--commit`, or check out with git history. |
| No changed files on runs | Check out at least 2 commits (`fetch-depth: 2`), or `--no-changes` is set. |
| Every failing test shows as "confirmed flaky" | The matrix legs share one environment. Set `QEOS_ENVIRONMENT` per leg. |
| `import-features` always "skipped" | The sync branch is the default branch, or `master` where the CI does not expose it. Set `QEOS_IMPORT_BRANCH`. |
| Imported cases never link to results | Import paths differ from report paths (fix **Path prefix**), or the upload is JUnit instead of Cucumber JSON. |
| Play disabled | No `TM_SECRETS_KEY` on the server, no Run from QEOS target in Settings, an expired token, or a run is already active. The reason is shown next to the button. |
| Play: `failed_to_start` | The workflow's `if:` branch guard does not match, or the workflow is missing on the default branch or the configured branch. |
| Email channel: "SMTP is not configured" | Set `SMTP_*` and `docker compose up -d --wait gateway`. |
| Webhook channel refused | It must be public `https` on port 443 with no credentials in the URL. LAN, Docker and loopback addresses are blocked on purpose. |
| Weekly summary did not arrive | It goes out once per channel per week, Mondays from 07:00 UTC, only to channels with **Weekly summary** ticked. A failed delivery is not retried that week. Use **Send summary** to test. |
| Lost MFA device and recovery codes | An administrator clears MFA in the database ([3.7](#37-two-factor-authentication-mfa)). |
| Need to see what a request did | Every response has `X-Request-ID`. Search for it in `docker compose logs gateway` and in the service logs. |
