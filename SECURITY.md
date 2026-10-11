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
([@carneiru](https://github.com/carneiru)). GitHub's private vulnerability
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
- **Access control.** Organisation roles (owner, admin, member, viewer,
  billing_manager) checked on every request; project access follows the
  organisation role; non-members get 404.
- **CI uploads.** Per-project API keys, stored as SHA-256 hashes and shown once.
  A key can also be traded for a 5-minute service token that only the Gherkin
  import accepts.
- **Masking.** Secrets and personal data in failure messages (authorization
  headers, cookies, passwords in URLs and command lines, JWTs, cloud and vendor
  tokens, private keys, key=value secrets, email addresses, card numbers) are
  masked before storage. Projects can add their own patterns, which run on RE2
  so that no pattern can stall ingestion.
- **Gateway.** TLS 1.2/1.3. Per-IP rate limits: 20 requests/s on the API,
  10/s on uploads, and 5/s on sign-in, registration, password and MFA
  endpoints. 10 MB body cap. `X-Forwarded-For` is replaced, not appended, and
  `/metrics` and `/internal` are never routed.
- **Internal APIs.** HTTP Basic with `INTERNAL_API_PASSWORD`. When it is unset
  they answer 503, never open.
- **Stored secrets.** The GitHub token used by Run from QEOS is encrypted at rest
  (Fernet, `TM_SECRETS_KEY`) and never returned. Notification webhook URLs are
  never returned, and are checked against SSRF (vendor hosts, public addresses
  only, no redirects).
- **Monitoring database role.** With monitoring on, PostgreSQL gets a login role
  `qeos_monitor` that is a member of `pg_monitor` only: it reads statistics and
  settings and cannot read table data. It can still see query text in
  `pg_stat_activity` and `pg_stat_statements`, which may contain literals.
- **Data.** Per-project retention, legal hold and a full NDJSON export.
- **Production package** (`deploy/`). A Caddy TLS edge with Let's Encrypt and
  HSTS is the only published service. Secrets are generated into a mode-600
  `.env`, and databases are backed up daily.
- **Supply chain.** CodeQL analysis and Dependabot updates for pip, npm and
  GitHub Actions.

## Known limitations

- Access tokens cannot be revoked before they expire (up to 60 minutes).
- Refresh tokens and notification webhook URLs are stored in plain text in
  their service's database.
- Rate limits are per gateway instance (no shared store).
- Planned, not built: SAML, GitHub sign-in (answers 501), an audit log,
  secrets management (Vault), a GitHub App instead of personal tokens for Run
  from QEOS, and per-action permissions. Monitoring and alerting are in
  progress (`docs/superpowers/specs/2026-10-10-monitoring-design.md`).

## Acknowledgments

We appreciate the efforts of everyone who has helped to improve the
security of our software by responsibly disclosing issues.
