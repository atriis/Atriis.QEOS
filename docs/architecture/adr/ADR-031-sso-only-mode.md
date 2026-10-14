# ADR-031: SSO-only mode — Microsoft sign-in only, superuser password break-glass

- Status: Accepted
- Date: 2026-10-14
- Authors: QEOS maintainers
- Decision Owner: Platform owner
- Supersedes: None
- Superseded By: None

Spec: `docs/superpowers/specs/2026-10-14-sso-only-mode-design.md`

---

# Context

## Business Problem
A company deployment wants people to sign in only with their Microsoft (Entra ID) work account, so joining
and leaving follow the company directory and no QEOS password exists to phish, reuse or forget.

## Technical Problem
auth-service offers email/password registration, sign-in and recovery next to Google and Microsoft ID-token
sign-in. Nothing switches the password routes off, existing password users have no dashboard way to link
Microsoft, and turning password sign-in off without a fallback would lock administrators out during a
Microsoft outage or a tenant misconfiguration.

## Architectural Drivers
- Directory-controlled identity for people; CI keys and service calls unchanged.
- Never lock out administrators.
- A mode switch must not depend on the dashboard (a stolen session must not be able to flip it).

## Stakeholders
Administrators (superusers), every QEOS user, operators of the deployment, security reviewers.

## Constraints
PostgreSQL only; settings come from `.env` through docker-compose; one auth-service image for every deployment.

## Assumptions
Entra ID is reachable from browsers; the UPN is on a verified tenant domain (as sign-in already assumes).

## Architecture Principles
Secure by default per deployment, fail closed at start-up, one owner per concern (auth-service owns sign-in).

## Quality Attributes Involved
Security, availability of administrator access, operability.

---

# Decision

Two settings, `AUTH_SSO_ONLY` (default `false`) and `AUTH_SSO_PROVIDERS` (default `microsoft`; `microsoft`,
`google`). With the mode on:

- Registration, email verification and password recovery answer 403 `{"code": "sso_only", ...}`.
- `POST /auth/login` verifies the password as before, then lets only an active superuser through (MFA
  still applies); everyone else gets the same 403, so the answer reveals neither superuser status nor
  password validity. Each such sign-in is logged at WARNING as `break-glass sign-in`.
- Providers not listed answer the same 403.
- auth-service refuses to start when a listed provider is not configured; it warns when no active
  superuser exists.
- On each off-to-on change auth-service revokes every non-superuser refresh session once, recorded in a
  one-row `auth_mode_state` table read with `SELECT … FOR UPDATE`.
- `GET /auth/methods` (public) tells the dashboard what to show; `GET /users/me` carries
  `linked_providers`, `sso_only` and `has_password`.
- A superuser sees who has not linked Microsoft (`GET /users/sso-readiness`) and can allow one account to
  be linked at its next Microsoft sign-in for 7 days (`POST /users/{id}/allow-microsoft-link`).

The mode is switched only in `.env` plus a restart, never from the dashboard.

## Success Metrics / Evaluation Criteria
After the switch, no non-superuser can obtain a session except through Microsoft; every password sign-in
appears in the log as break-glass; readiness shows 100% linked before the switch.

## Scope
Sign-in of people. Not: CI API keys, collector uploads, internal service calls, the Grafana session, roles.

## Affected Components/Services/Domains
auth-service (Identity), dashboard (sign-in pages, Security page), docker-compose.

## Implementation Boundaries
The gateway is unchanged (`location /api/v1/auth` already routes `/auth/methods`).

---

# Alternatives Considered

## Turn password sign-in off for everyone
### Pros
- Smallest surface.
### Cons
- A Microsoft outage or tenant misconfiguration locks every administrator out.
### Decision
Not Selected
### Rejected because
Recovery would need database access on the host.

## Link existing accounts by email at first Microsoft sign-in
### Pros
- No linking step for users.
### Cons
- Pre-registration takeover (an address squatted with a password gets attached to the real person).
### Decision
Not Selected
### Rejected because
`sso.py` refuses email-only linking for this reason; the one-time allowance keeps a superuser decision in the loop.

## A dashboard toggle for the mode
### Pros
- No restart.
### Cons
- A stolen superuser session could switch password sign-in back on.
### Decision
Not Selected
### Rejected because
The switch belongs to whoever controls the deployment's configuration.

---

# Consequences

## Positive
- People's access follows the company directory; no QEOS passwords for ordinary users.
- Administrators keep a way in.

## Negative
- Someone removed from Entra keeps an existing QEOS session until its refresh token expires (30 days)
  unless deactivated in QEOS; SCIM deprovisioning is future work (TODO).
- A new colleague must sign in once with Microsoft before being added to an organization or project.

---

# Implementation

## Affected Components/Services
auth-service: `service/auth_mode.py`, `service/sso_readiness.py`, endpoints `auth.py`, `sso.py`, `users.py`,
migration 008. Dashboard: `LoginPage`, the four recovery pages, `SecurityPage`.

## Affected Domains
Identity, Collaboration.

## Deployment Implications
`docker-compose.yml` forwards `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_ALLOWED_TENANTS`, `AUTH_SSO_ONLY`,
`AUTH_SSO_PROVIDERS` to auth-service. The dashboard's Microsoft button still needs `VITE_MSAL_CLIENT_ID`
at build time.

## Operational Considerations
Watch for `break-glass sign-in` WARNING lines; check readiness before switching (SETUP §3.8).

## Migration Considerations
Migration 008 adds `auth_mode_state` (seeded `sso_only = false`) and `users.microsoft_link_allowed_until`.

---

# Risks

| Risk | Mitigation |
|------|------------|
| No active superuser when the mode is on | Start-up WARNING; FIRST_SUPERUSER bootstrap |
| Two auth-service processes revoke twice | Row lock on `auth_mode_state` |
| Access tokens outlive the switch | At most `ACCESS_TOKEN_EXPIRE_MINUTES` (60); the next refresh is refused |

---

# Related Decisions
- ADR-013: Refresh token as httpOnly cookie
- ADR-016: SSO sign-ins bypass platform MFA

---

# Change Log
| Date | Version | Description |
|------|---------|-------------|
| 2026-10-14 | 1.0 | Initial version |

---

# References
- `docs/superpowers/specs/2026-10-14-sso-only-mode-design.md`
- `docs/SETUP.md` §3.8

---

# Review
When SCIM provisioning is built, or a second provider is used as the only one.
