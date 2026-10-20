# Security Policy

## Supported Versions

The platform has no versioned release yet: security fixes land on `master`,
and a deployment is supported when it runs the current `master`. The
`qeos-collector` is released on its own (`collector-v*` tags); only the latest
release is supported.

| Component | Supported |
| --------- | --------- |
| Platform, current `master` | :white_check_mark: |
| Platform, older commits | :x: (update: `deploy/README.md` §8) |
| qeos-collector, latest release | :white_check_mark: |
| qeos-collector, older releases | :x: |

## Reporting a Vulnerability

Contact the maintainer privately through GitHub
([@AtriisPedroCarneiro](https://github.com/AtriisPedroCarneiro)). GitHub's private vulnerability
reporting is not enabled on this repository yet. If the issue is confirmed,
we will open a pull request to address the vulnerability.

We ask that you do not disclose the vulnerability publicly until we have
released a fix.

## Preferred Languages

We prefer all communications to be in English.

## Policy

We take the security of our product and services seriously, which includes
all source code repositories managed through our organization.

If you believe you have found a security vulnerability in any of our
repositories, please report it to us as described above.

Please do not create public GitHub issues for suspected security
vulnerabilities. Instead, please follow the instructions above.

We will acknowledge receipt of your report within 48 hours and will
respond in more detail within 5 business days regarding the next steps
in handling your report.

After the initial reply to your report, the security team will
keep you informed of the progress towards a fix and full announcement,
and may ask for additional information or guidance as part of the
investigation.

For critical vulnerabilities, we will aim to provide a fix within
72 hours of confirmation.

For important vulnerabilities, we will aim to provide a fix within
2 weeks of confirmation.

For minor vulnerabilities, we will aim to provide a fix within
30 days of confirmation.

We will send you a follow-up communication after the fix has been
released, including details of the fix and how to update your
installation to mitigate the vulnerability.

## What the platform does today

Verified against the code on 2026-10-11; `TECHNICAL_SPECIFICATION.md` has the
details.

- **Accounts.** Passwords hashed with bcrypt (at least 8 characters). Email
  verification before an account exists. Password reset by a single-use link
  (token stored hashed, valid 30 minutes); a reset or a password change ends
  every session.
- **Sessions.** Short-lived JWT access tokens (60 minutes, HS256, shared
  `SECRET_KEY`) and opaque refresh tokens (30 days) that rotate on use; reusing
  a spent refresh token revokes every session of that user. The refresh token
  travels in an httpOnly, Secure, SameSite=Strict cookie scoped to
  `/api/v1/auth`. Every service accepts only access tokens as sessions: MFA
  challenge, refresh and service tokens are rejected.
- **MFA.** TOTP with eight single-use recovery codes, stored bcrypt-hashed.
  Google and Microsoft sign-ins rely on the provider's own factor.
- **SSO.** Google and Microsoft ID tokens verified against the providers'
  signing keys; Microsoft sign-in limited to the tenants in
  `AZURE_ALLOWED_TENANTS`.
- **SSO-only mode (ADR-031).** `AUTH_SSO_ONLY=true` turns off registration,
  email verification, password recovery and password sign-in for everyone but
  active superusers (break-glass; MFA still applies). A refused password
  sign-in answers the same 403 whether the password was right or wrong, so it
  reveals neither superuser status nor password validity. Every break-glass
  sign-in is logged at WARNING with user id, email, IP and time; no password,
  token or client id is ever logged. auth-service refuses to start when a
  provider the mode lists is not configured. Turning the mode on ends every refresh session of every
  non-superuser once (access tokens expire within 60 minutes). A superuser can allow one account to
  link Microsoft at its next Microsoft sign-in (7 days, logged at WARNING, used once); it is never
  matched on the email alone.
- **Entra app roles (ADR-033).** A mapping grants at most `admin`; owners are granted only by hand. Only
  owners edit their organization's mapping, and a mapping applies only after an active superuser approved the
  organization (`PUT /api/v1/organizations/{id}/entra-sync`; organization-service asks auth-service at each call).
  Without that, any user could create an organization and have Entra add everyone holding a mapped app role to it,
  then read their addresses in its member list. Only members marked `managed_by = entra` follow the token;
  hand-made members are never touched. Managed members cannot be removed by hand (409). The internal
  endpoint `POST /internal/v1/sso-roles` uses HTTP Basic, answers 503 while its password is empty, and is
  never routed by the gateway. Each change is logged at INFO with organization, user, old and new role.
  auth-service pushes the roles with HTTP Basic, using `ORGANIZATION_INTERNAL_API_PASSWORD`, over the internal
  network. With an empty password it stores the roles but never applies them, and start-up logs a WARNING.
  A failed push logs only the exception class or the HTTP status, never credentials, and never blocks sign-in.
  Trust across tenants: `AZURE_ALLOWED_TENANTS` may list several tenants and a mapping carries no tenant, so an
  administrator of any allowed tenant can grant every mapped role in every organization that maps that value.
  List only tenants you trust that much.
- **Access control.** Organisation roles (owner, admin, member, viewer,
  billing_manager) checked on every request; project access follows the
  organisation role; non-members get 404.
- **Overview layouts.** A personal layout belongs to one user in one project:
  only that user reads or changes it (every role, viewers included). The
  project default is changed only by owners and admins. Every saved layout is
  validated on the server against the shared widget catalogue (known types,
  allowed settings, at most 24 widgets, a 64 KB body) and carries a version,
  so a save over a newer one is refused (409).
- **CI uploads.** Per-project API keys, stored as SHA-256 hashes and shown once.
  A key can also be traded for a 5-minute service token that only the Gherkin
  import accepts. Keys are upload-only unless an owner or admin allows test
  suggestions for that key (`can_read_impact`, off by default and for every key
  that existed before migration 020): only such a key may read its own project's
  suggestions (`POST /api/v1/collect/impact`: test names, path units, aggregate
  failure evidence, and which named tests failed in the branch's latest run (the `failing_on_branch` kind); never failure
  messages, stack traces or other runs' details), which the collector needs to run the likely affected
  tests first; any other key gets `403 impact_not_allowed`. Owners and admins set
  it when creating a key or later (`PATCH /projects/{id}/api-keys/{key_id}`); a
  member can create keys, upload-only ones.
- **The collector in CI.** The API key is read from the environment only and scrubbed from
  every log line and from the GitHub step summary. The GitHub Action hands every input to its
  scripts as an environment variable, never as script text; `test-command` runs as
  `bash -c "$QEOS_TEST_COMMAND"`, the same trust as a `run:` step its author writes, and
  `extra-args` is split into words by the collector (`QEOS_ACTION_EXTRA_ARGS`, flags only, not
  passed on to the tests). `run-impact` selects scenarios through rerun files, never by name,
  so no test name reaches a shell, and its own arguments reach a `bash -c` script as `"$@"`.
  On Windows it refuses a working directory whose characters cmd.exe would expand. The test
  command never sees the key: `QEOS_API_KEY`, `QAV_API_KEY` and `QEOS_ACTION_EXTRA_ARGS` are
  removed from its environment.
- **Collection of manual runs.** The project toggle that discards manual CI runs is a noise
  filter, not an access control. The collector reports `run.trigger`, so whoever holds the project's
  API key can label a manual run `automatic` and have it stored. API keys remain the boundary.
  Only owners and admins change the toggle (ADR-030).
- **Masking.** Secrets and personal data in failure messages (authorization
  headers, cookies, passwords in URLs and command lines, JWTs, cloud and vendor
  tokens, private keys, key=value secrets, email addresses, card numbers) are
  masked before storage. Projects can add their own patterns, which run on RE2
  so that no pattern can stall ingestion. The failed Cucumber step's text, step definition and pattern are masked the same way, at upload and by the re-mask job, and so is the step text of a screenshot (the images themselves are never masked, below). Each result's log (sent by collector 0.9.0 for log values, ADR-032) is masked the same way before it is stored and cut to 64 KB; it is never shown in full.
- **Screenshots (ADR-036).** Step screenshots from test runs are stored in MinIO, a private bucket that is not
  published outside the Docker network: only ingestion-service reads it. MinIO's Prometheus metrics need no token
  (`MINIO_PROMETHEUS_AUTH_TYPE=public`), so any container on the compose network, and the Docker host through the
  container's IP, can read them (they are never published): bucket names, object
  counts, bytes used and disk capacity, never object names or contents. This is acceptable only while MinIO keeps no
  published port. Screenshots are off by default for every project;
  a project owner or admin turns them on in Project Settings. **Images are never masked.** QEOS cannot read text
  inside an image, so a screenshot can show names, emails and booking data that the masking above would have
  removed from text. Switch them on only for projects whose test data is safe to show to every project reader.
  Images follow the retention days of their results and are deleted with the project. The MinIO volume holds them
  in clear: back it up and protect it like the database dump (`deploy/backup.sh`).
  An upload (`PUT /api/v1/collect/blobs/{sha256}`, project API key) is checked before it is stored: one of three image
  types (PNG, JPEG, WebP), first bytes that match the declared type, a SHA-256 equal to the path, at most 5 MB. An image
  is stored and looked up per project (`screenshots/{project_id}/{sha256}`), so a key sees only its own project's
  images. It answers 403 when the project has screenshots off or QEOS has no storage configured.
  For a Playwright report (collector 0.13.0), the collector reads a file the report names only when it resolves,
  symlinks followed, inside the working directory, is at most 5 MB and starts like the image type it claims, so a
  tampered report cannot make it upload another file from the CI machine.
  Reading: `GET /api/v1/projects/{id}/screenshots/{screenshot_id}` serves the image unmasked, read through
  ingestion-service, with a user JWT and the read roles of the project. A non-member, and an id that belongs to
  another project, both get 404. There are no presigned URLs and the bucket is never public. The response carries
  `Cache-Control: private, max-age=3600`, so a browser may keep an image for up to an hour after the user loses
  access to the project, and `X-Content-Type-Options: nosniff`.
- **Gateway.** TLS 1.2/1.3. Per-IP rate limits: 20 requests/s on the API,
  10/s on uploads, 50/s (burst 100, 6 MB body) on screenshot uploads, and 5/s on sign-in, registration, password and MFA
  endpoints. 10 MB body cap elsewhere. `X-Forwarded-For` is replaced, not appended, and
  `/metrics` and `/internal` are never routed.
- **Internal APIs.** HTTP Basic with `INTERNAL_API_PASSWORD`. When it is unset
  they answer 503, never open.
- **Dispatch targets.** Run from QEOS dispatches only workflow names taken from the project's synced repository
  suite rows or from its CI target, never a name from the browser. The token scope is unchanged (ADR-035).
  The repository suite names come from whoever holds the project's import key (the CI sync with `--suites`), not
  only from managers through `PUT /ci-target`. GitHub rejects a dispatch with inputs the workflow does not declare,
  so this reaches only workflows that declare both `suites` and `request_id`.
- **Stored secrets.** The GitHub token used by Run from QEOS is encrypted at rest
  (Fernet, `TM_SECRETS_KEY`) and never returned. Notification webhook URLs are
  never returned, and are checked against SSRF (vendor hosts, public addresses
  only, no redirects).
- **Monitoring database role.** Only when `MONITORING_DB_PASSWORD` is set (monitoring on; `init-env.sh`
  writes it commented out), PostgreSQL gets a login role
  `qeos_monitor` that is a member of `pg_monitor` only: it reads statistics and
  settings and cannot read table data. It can still see query text in
  `pg_stat_activity` and `pg_stat_statements`, which may contain literals. The
  exporter that feeds Prometheus runs without statement text, so query literals
  are not copied into the metrics.
- **Grafana sign-in cookie (monitoring).** `POST /api/v1/auth/grafana-session`
  (bearer access token only, so it has no CSRF exposure) gives an active
  superuser, and only while `MONITORING_ENABLED` is true, the `qeos_grafana`
  cookie: httpOnly, Secure, SameSite=Strict, `Path=/grafana`, 8 hours. It is a
  JWT with its own audience (`grafana`), so it is refused as an API bearer
  token, and an access token is refused in its place. Logout clears it on
  every answer, including when the access token has already expired. It is
  bound to the password: a `pwv` claim (a keyed digest of the password hash)
  makes a password change or reset invalidate every Grafana cookie. Logging
  out on another device does not: a copied cookie keeps working until it
  expires, an accepted residual like the 60-minute access token.
- **Grafana per-request re-check (monitoring).** auth-service's
  `GET /internal/v1/grafana-check` re-verifies the `qeos_grafana` cookie for
  every Grafana request: the user must still exist, be active and a superuser,
  the cookie's `pwv` must match the current password (compared in constant
  time), and `MONITORING_ENABLED` must be true. Anything else is a 401, so a
  demotion, deactivation, password change or monitoring turned off cuts access
  on the next request. It takes no HTTP Basic (the cookie is the credential;
  the gateway never routes `/internal/`), ignores the `Authorization` header,
  answers `Cache-Control: no-store` and never sends `WWW-Authenticate`.
- **Grafana behind the gateway (monitoring).** With `MONITORING_ENABLED` true,
  every `/grafana/` request goes through NGINX `auth_request` to that check
  (an `internal` location carrying only the browser's cookies: no body, no
  `Authorization`, no other client header). Only a 2xx reaches Grafana: a 401
  redirects to the dashboard's `/monitoring?next=<path>`, a 403 is refused, and
  an unreachable auth-service or any other answer is a 502. The gateway
  **always overwrites** `X-QEOS-User-Email` toward Grafana with the email from
  the check's answer, so a client sending its own header, with a valid cookie
  or without one, never chooses who Grafana signs in (verified live: a forged
  header for another address still shows the cookie owner). Grafana's auth
  proxy believes that header only from the gateway's fixed `grafana-front`
  address. The gateway also removes `Authorization` toward Grafana, so the
  QEOS access token never reaches it, and strips the `qeos_grafana` cookie from
  the `Cookie` header it forwards (Grafana keeps its own cookies). A hand-made
  header the stripping cannot clean (a third copy, a space before `=`) is
  refused with 400 before it is proxied, so Grafana does not receive the QEOS
  credential either way. With `MONITORING_ENABLED` unset or false,
  `/grafana/` is a JSON 404 for everyone.
- **Return paths after sign-in (`next`).** The dashboard follows a `next` only through
  `safeNext`: a path that starts with exactly one `/`, holds no backslash, whitespace or control
  character (U+0085 and U+FEFF included) and is not `/login`; anything else lands on `/`.
  Registration sends it to the auth-service so the verification email can carry it
  (`&next=…`, encoded whole); `RegisterRequest.next` applies the same rules, at most 2048
  characters, and refuses anything else with 422 (the dashboard then registers again without
  it). The dashboard validates the value again when it reads it from the link or from storage,
  never trusting either. An invitee's `next` is `/invitations/<token>`, so the invitation token
  now also appears in the verification email, in the auth-service log when SMTP is off, and in
  the verify page's URL (so in `Referer` headers and access logs): treat it like the
  verification link itself.
- **The `/monitoring` hand-off page (monitoring).** Anyone can craft a
  `/monitoring?next=` link, so the dashboard does not rely on the gateway's
  own restriction of `next`. It reads the raw value, decodes it exactly once
  (`decodeURIComponent` in try/catch; malformed encoding is refused), and
  follows it only when the decoded path starts with `/grafana/` and, after
  that one decode, holds no `%` (the gateway would decode it again, so
  `..%252f` would become `../` and leave the gated location), no `.` or `..`
  segment, no `//` after the first character, no backslash, and no control
  character or whitespace; anything else opens `/grafana/`. It navigates with
  `window.location.assign` on that relative path only, never an absolute URL
  built from input (the menu item checks the server's `url` the same way).
  The cookie is minted only by the bearer-token POST, so a crafted link
  cannot mint it for a visitor who is not signed in to the dashboard. A
  hand-off is marked in `sessionStorage` for 10 seconds: if Grafana sends
  the browser straight back, the page asks (Try again) instead of handing
  over again, so it cannot loop.
- **Grafana break-glass port (monitoring).** Grafana publishes `127.0.0.1:3000`
  for an admin login when auth-service is down. Because that port is published,
  Docker 28 and later makes Grafana's address on its `grafana-front` network
  reachable by IP from other containers on the host. Their requests arrive from
  the network's bridge gateway (`172.30.1.128` with the default subnet), not from the gateway's fixed
  address that Grafana's auth proxy trusts (`GF_AUTH_PROXY_WHITELIST`), so a user
  header they send is refused (401 `auth-proxy.invalid-ip`) and they reach only Grafana's own login, which
  needs `GRAFANA_ADMIN_PASSWORD`. A container that is already compromised could
  try that password; keep it long and random (`init-env.sh` does).
- **cAdvisor (monitoring).** It runs as root with only the Docker socket, the containerd socket,
  `/sys` and `/var/lib/docker` mounted, all read-only; there is no `/:/rootfs` mount and no whole
  `/var/run`, so it no longer sees the rest of the host filesystem (`.env` included). It still reads
  `/var/lib/docker`, which holds the volumes and so the PostgreSQL data, and both sockets are
  root-equivalent API access (`:ro` makes the socket file read-only, not the API behind it: a process
  that can write to either socket can start, stop or exec into containers): treat cAdvisor as trusted.
  It is opt-in and publishes no port. The containerd socket is required: without it cAdvisor discovers
  no container, and `CadvisorNoContainers` fires after 10 minutes.
- **Data.** Per-project retention, legal hold and a full NDJSON export (screenshot images are not exported, only their
  references). Step screenshots are deleted with their results, unreferenced ones after 7 days, and all of a project's
  with the project. Deleting a project (owners and admins,
  the name typed to confirm; refused under a legal hold) hides it at once and purges it in every service 7 days
  later (ADR-034). Meanwhile its uploads answer 410 and owners and admins can restore it; the purge runs in
  recorded steps over the internal APIs and never touches a restored project.
- **Production package** (`deploy/`). A Caddy TLS edge with Let's Encrypt and
  HSTS is the only published service. Secrets are generated into a mode-600
  `.env`, and databases are backed up daily.
- **Supply chain.** Dependabot updates for pip, npm and GitHub Actions. CodeQL analysis
  runs once GitHub Code Security is enabled for the repository and the repository variable
  `CODEQL_ENABLED` is `true`; until then the CodeQL workflow is skipped, not failed.

## Known limitations

- Access tokens cannot be revoked before they expire (up to 60 minutes).
- Refresh tokens and notification webhook URLs are stored in plain text in
  their service's database.
- Rate limits are per gateway instance (no shared store).
- SSO-only mode: someone removed from Entra ID keeps an existing QEOS session
  until its refresh token expires (30 days) unless deactivated in QEOS; SCIM
  deprovisioning is not built (ADR-031).
- Planned, not built: SAML, GitHub sign-in (answers 501), an audit log,
  secrets management (Vault), a GitHub App instead of personal tokens for Run
  from QEOS, and per-action permissions. Monitoring: the Prometheus, Alertmanager and exporter
  stack, the QEOS sign-in to Grafana and its dashboards are built (ADR-027)
  (`docs/superpowers/specs/2026-10-10-monitoring-design.md`).

## Acknowledgments

We appreciate the efforts of everyone who has helped to improve the
security of our software by responsibly disclosing issues.
