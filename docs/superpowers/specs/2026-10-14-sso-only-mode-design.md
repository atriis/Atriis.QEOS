# SSO-only mode — design

Status: sections 1 (auth-service, with six review amendments) and 2 (dashboard) approved in conversation
2026-10-14; pending review of this written spec.
Blueprint: auth-service (Identity), dashboard (Collaboration); PostgreSQL only. New ADR-031.

## 1. Goal and scope

For the company deployment, people sign in to QEOS only with their Microsoft (Entra ID) work account.
Email/password registration, sign-in and recovery are switched off, with two exceptions decided with the user:

- **Break-glass:** active superusers keep password sign-in (MFA still applies), so a Microsoft outage or a
  misconfigured tenant never locks the administrators out.
- **Linking:** existing password users link their Microsoft account from the Security page before the mode
  is switched on; a readiness check shows who has not, and a superuser can let a user link at their next
  Microsoft sign-in if they missed it.

Not changed: CI API keys and collector uploads, internal service-to-service calls, the Grafana session,
project and organization roles. Only how people sign in changes.

Not in scope: user provisioning or deprovisioning from Entra (SCIM), Google or GitHub as the only provider,
switching the mode from the dashboard.

## 2. Today (for reference)

- `POST /sso/microsoft` verifies the ID token (allowed tenants: `AZURE_ALLOWED_TENANTS`, falling back to
  `AZURE_TENANT_ID`), finds the account by `(provider, provider_user_id)`, creates one for a new identity,
  and refuses (409, `MICROSOFT_EXISTING_ACCOUNT`) when an account with the same email exists but is not
  linked. Inactive users are refused.
- `POST /users/me/link/microsoft` links a Microsoft identity to the signed-in account; an account with a
  password must send `current_password`.
- Sessions are rows in `sessions` (refresh tokens, `is_revoked`); access tokens are JWTs that live
  `ACCESS_TOKEN_EXPIRE_MINUTES` (60); refresh tokens live `REFRESH_TOKEN_EXPIRE_DAYS` (30).

## 3. auth-service

### 3.1 Settings

| Setting | Default | Meaning |
|---|---|---|
| `AUTH_SSO_ONLY` | `false` | Turns the mode on. |
| `AUTH_SSO_PROVIDERS` | `microsoft` | Comma-separated SSO providers allowed in the mode. Only `microsoft` and `google` are valid. |

At startup, with `AUTH_SSO_ONLY=true`, auth-service **refuses to start** when a listed provider is not
configured (Microsoft: `AZURE_CLIENT_ID` and at least one allowed tenant; Google: `GOOGLE_CLIENT_ID`), and
logs which setting is missing. An unknown provider name also stops start-up. When the mode is on and no
active superuser exists, start-up continues but logs a WARNING: nobody could use the break-glass sign-in.

docker-compose.yml forwards both settings to auth-service from `.env`, and now also `AZURE_CLIENT_ID`,
`AZURE_TENANT_ID` and `AZURE_ALLOWED_TENANTS` (today they need an override file, SETUP §3.8), so the mode and
the provider it depends on are configured in one place. The dashboard's Microsoft button still needs
`VITE_MSAL_CLIENT_ID` at build time, as today.

### 3.2 `GET /api/v1/auth/methods` (public)

```json
{"password": false, "providers": ["microsoft"]}
```

`password` is `false` in SSO-only mode (the break-glass form is not advertised); `providers` lists the
configured providers, filtered by `AUTH_SSO_PROVIDERS` in the mode. Normal mode: `{"password": true,
"providers": [<configured>]}`. No secrets, no per-user data. The gateway's existing `location /api/v1/auth`
routes it; no gateway change.

### 3.3 Password routes in SSO-only mode

One 403 body for every refusal: `{"detail": {"code": "sso_only", "message": "Sign-in is through Microsoft
only."}}` (the provider names come from `AUTH_SSO_PROVIDERS`).

| Route | Behaviour |
|---|---|
| `POST /auth/register` | 403. |
| `POST /auth/forgot-password`, `POST /auth/reset-password`, `POST /auth/resend-verification`, `GET /auth/verify-email` | 403. |
| `POST /auth/login` | The password is verified first, exactly as today. Then: an **active superuser** gets tokens (MFA still asks for its code); **anyone else gets the same 403**, whether the password was right or wrong, so the answer never reveals who is a superuser or whether a password is valid. |
| `POST /auth/mfa/verify` | Unchanged (it only follows a successful superuser login). |
| `POST /auth/change-password` | Superusers only; others get the 403. |
| SSO routes not in `AUTH_SSO_PROVIDERS` | 403 with the same body. |

Every password sign-in that succeeds in the mode is logged at WARNING as `break-glass sign-in` with user
id, email, IP and time.

### 3.4 Sessions when the mode turns on

A one-row table `auth_mode_state (id=1, sso_only BOOLEAN, applied_at)` records the mode last applied
(migration 008). At start-up, when `AUTH_SSO_ONLY=true` and the stored value is `false` (or there is no row),
auth-service revokes every non-revoked session of every user who is not a superuser, then stores `true`,
in one transaction that locks the row (`SELECT … FOR UPDATE`), so two auth-service processes starting
together revoke once.
When the mode is off it stores `false`. So each off-to-on change revokes once, and restarts do not.

Access tokens already issued keep working until they expire (at most `ACCESS_TOKEN_EXPIRE_MINUTES`); the
next refresh is refused because its session is revoked.

### 3.5 Readiness and the one-time link allowance

`GET /api/v1/users/sso-readiness` (superusers only):

```json
{"active_users": 15, "linked": 12,
 "unlinked": [{"id": 7, "email": "ana@…", "full_name": "Ana", "link_allowed_until": null}]}
```

`unlinked` lists active users without a Microsoft `OAuthAccount`, sorted by email, superusers included
(each entry has `is_superuser`): they keep the break-glass, but should link too.

`POST /api/v1/users/{id}/allow-microsoft-link` (superusers only) sets `users.microsoft_link_allowed_until`
to now + 7 days (migration 008 adds the column), logs it at WARNING (who allowed whom, until when), and
returns the readiness entry. 404 for an unknown user,
409 when the user is already linked or inactive.

`POST /sso/microsoft`: when the identity is new, an account with the same email exists, is not linked and
has `microsoft_link_allowed_until` in the future, the identity is linked to that account (as
`/users/me/link/microsoft` would), the allowance is cleared, and the user is signed in with their projects
and roles. Without a valid allowance the 409 stays. The match is never made on the email alone: a superuser
allowed it for that account, and the token is from an allowed tenant.

### 3.6 `GET /users/me`

`UserMe` gains `linked_providers: ["microsoft", …]` and `sso_only: bool` so the Security page knows what to
show without a second request.

### 3.7 Known limitation

Someone removed from Entra cannot get a new Microsoft token, but a QEOS session they already hold lasts
until its refresh token expires (30 days). Deactivating them in QEOS ends it at once (`is_active` is checked
on refresh). Automatic deprovisioning (SCIM) goes in TODO.

## 4. Dashboard

### 4.1 Sign-in pages

- **Login** (`LoginPage`) reads `GET /auth/methods` on load.
  - SSO-only: only the provider buttons ("Sign in with Microsoft"), a line "Sign-in is through your
    Microsoft work account", no Register or Forgot-password links, and a closed native `<details>`
    "Administrator sign-in" holding the email and password form.
  - Normal mode: unchanged.
  - If `/auth/methods` fails, the page shows the normal form; the server still enforces the mode.
- **Register, Forgot password, Reset password, Verify email**: in SSO-only mode each shows "Sign-in is
  through Microsoft only" and a link to the login page instead of its form (bookmarks and old emails). The
  page also handles the 403 `sso_only` code the same way if `/auth/methods` was unavailable.

### 4.2 Security page

- **Microsoft account** card (every user; in normal mode only when Microsoft is configured): "Linked to
  Microsoft" when `linked_providers` has it; otherwise a **Link Microsoft account** button: MSAL sign-in,
  then `POST /users/me/link/microsoft` (asking for the current password when the account has one), then a
  success note. Errors in `ErrorBanner`.
- **Password** card: hidden in SSO-only mode for non-superusers.
- **Microsoft-only sign-in** card (superusers only):
  - Status: whether the mode is on, and how to change it (`AUTH_SSO_ONLY=true` in `.env`, then restart
    auth-service). The mode is not switched from the page, so a stolen session cannot change it.
  - Readiness: "12 of 15 active users have linked Microsoft", then the unlinked users, each with **Allow
    link at next sign-in** or, once allowed, "Allowed until <date>".

Existing card, button, `success-note` and `ErrorBanner` styles; one heading per card; ui-ux-pro-max reviews
the layout before it is built.

## 5. Testing

- **auth-service:** start-up refusal (missing Microsoft settings, unknown provider); the no-superuser warning; `/auth/methods` in both
  modes; each password route's 403; superuser break-glass with and without MFA; a non-superuser's 403 is
  identical for a right and a wrong password; the break-glass log line; Google refused when not listed;
  session revocation once per off-to-on change and not on restart, superuser sessions kept; readiness counts
  and list (superusers included); allowance set and logged, expiry, 404/409, consumed on sign-in, refused after
  expiry; `linked_providers`
  and `sso_only` on `/users/me`; Microsoft sign-in otherwise unchanged; migration 008 up and down.
- **Dashboard:** login page in both modes and the break-glass disclosure; the four pages' notice (from
  `/auth/methods` and from a 403 `sso_only`); link button success, password prompt and error; Password card
  hidden for non-superusers; superuser card status, readiness list and allow action; lint, typecheck, build.
- **Gateway smoke** (`scripts/smoke_gateway.sh`): `/auth/methods` answers 200 without a token, with
  `"password": true` on the default stack.

## 6. Documentation

ADR-031 (SSO-only mode). SETUP §3.8: link everyone first, check readiness, set `AUTH_SSO_ONLY=true`,
restart; break-glass; the known limitation; a new colleague signs in once with Microsoft before they can be
added to an organization or project (members are added by existing account). SECURITY (sign-in surface, break-glass, logging). auth-service
README (settings, endpoints, 403 code). PRODUCT, TODO (SCIM later), TECHNICAL_SPECIFICATION, DESIGN (login
and Security cards), `.env.example`.

## 7. Delivery

Each step lands on master after the full CI mirror passes.

1. **auth-service:** settings and start-up check, `/auth/methods`, route guards, migration 008, session
   revocation, readiness and allowance, `UserMe` fields, docs.
2. **Dashboard** and its docs.
