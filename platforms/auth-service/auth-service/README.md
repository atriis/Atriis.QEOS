# Authentication Service

Authentication for the QEOS platform: email/password accounts, JWT access tokens with revocable database-backed refresh tokens, and Google SSO.

## Overview

This service provides core authentication and authorization functionality for the QEOS platform. It implements industry-standard security practices including:
- Secure user registration and authentication with bcrypt password hashing
- JWT access tokens (configurable, default 60 minutes)
- Opaque refresh tokens stored server-side, rotated on use and revocable on logout
- Google SSO with full ID token verification against Google's JWKS
- Role-based access control with superuser privileges for administrative functions
- Pydantic-based request/response validation and OpenAPI documentation

## Current Implementation Status

### ✅ Implemented and tested
- **Email/Password Authentication**: registration (gated on email verification), login, logout
- **Token Management**: JWT access tokens (60 minutes) and opaque database-backed refresh tokens (30 days) with rotation on use, replay detection, and server-side revocation
- **Google SSO**: ID tokens verified against Google's JWKS (RS256 signature, audience, issuer, expiry, verified email)
- **Microsoft SSO (Entra ID)**: v2.0 ID tokens from an allowlist of tenants, verified against Microsoft's JWKS (RS256, audience, tenant, issuer, expiry); identity is tenant id + object id
- **User Management**: self-service profile read and update, restricted to non-privileged fields
- **Administrative Functions**: superuser-only user listing
- **Security**: bcrypt password hashing, CORS configuration, cross-user isolation on every identity-resolving path
- **Testing**: 137 unit and integration tests, including the SSO verification path against a locally generated signing key
- **Documentation**: auto-generated OpenAPI/Swagger
- **Deployment**: Dockerfile and docker-compose configuration

- **Password reset and change**: emailed single-use link (30 minutes, only its SHA-256 stored); both end every refresh session

### ⛔ Not implemented — these endpoints return 501
- **GitHub SSO**: requires an OAuth code exchange that does not exist

### 📝 Not built
- **Registering an address now requires proving control of it.** `/auth/register` no longer creates an account -- it creates an expiring, unclaimed record and emails a link. Nothing is reserved until that link is used, so an attacker who never verifies has claimed nothing: a later registration or Google SSO for that address proceeds normally.
- **Account-existence leaks on registration and resend.** `/auth/register` returns a different status and body for an address that already has a completed account (`400`) versus one that is pending or unknown (`202`) — a direct, not just timing-based, leak of whether an address is registered. `/auth/resend-verification` returns identical response bodies regardless of state, but the branch that does real work (a token rotation, a commit, sending mail) is measurably slower than the branch that does nothing, so a network-timing side channel can still distinguish states its response content cannot. Neither is defended against; this spec's threat model is lockout prevention, not enumeration resistance.
- **An unauthenticated party can choose between two weak outcomes for an address's resend.** Registering a second time for an address (no rate limiting anywhere in this service) makes `/auth/resend-verification` decline for everyone, including the real registrant, until only one attempt remains unexpired — a convenience denial only; the real registrant's own original link still works, and re-registering is a full substitute. Keeping exactly one attempt alive instead (an unauthenticated resend refreshes its own expiry indefinitely) reaches the residual documented above, where resend serves that one surviving attempt. Registration itself is never refused and no one's own link is ever invalidated by either choice; both are stated here because nothing else in this document says the attacker gets to pick which of the two applies.
- **Account lockout**: no failed-attempt tracking exists anywhere in this service
- **Redis token blacklisting**: a Redis URL is configurable, but nothing reads it
- **HTTP-only cookie sessions**: bearer tokens only
- Rate limiting on authentication endpoints
- Additional SSO providers (SAML, etc.)
- Multi-factor authentication (MFA)
- Advanced session management (device tracking, concurrent session limits)

## Getting Started

### Prerequisites
- Python 3.9+
- PostgreSQL 12+
- (Optional) Docker and Docker Compose

### Local Development Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd qa-ai-dashboard/src/services/auth-service
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration (see Environment Variables section below)
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Database setup**
   ```bash
   # Ensure PostgreSQL is running and create the database if needed
   # Then apply migrations
   alembic upgrade head
   ```

5. **Run the application**
   ```bash
   # Development mode
   uvicorn src.auth.api.main:app --reload

   # API will be available at http://localhost:8000
   # API documentation:
   # - Swagger UI: http://localhost:8000/api/v1/docs
   # - ReDoc: http://localhost:8000/api/v1/redoc
   ```

### Docker Deployment

```bash
# Required, no default; use the same value for organization-service
export SECRET_KEY=<a long random value>
docker compose up --build
```

## Environment Variables

Copy `.env.example` to `.env` and configure as needed:

### Application Settings
- `APP_NAME`: Service name (default: "Auth Service")
- `APP_VERSION`: Version identifier (default: "0.1.0")
- `DEBUG`: Enable debug mode (default: False)

### API Configuration
- `API_V1_STR`: API version prefix (default: "/api/v1")

### Security Settings
- `SECRET_KEY`: Secret key for JWT signing (REQUIRED - change in production!)
- `ACCESS_TOKEN_EXPIRE_MINUTES`: Access token lifetime in minutes (default: 60). Nothing can revoke an access token, so this value is the revocation delay — logout, a password change and deactivation all leave an already-issued token working until it expires. It previously defaulted to 8 days.
- `REFRESH_TOKEN_EXPIRE_DAYS`: Refresh token lifetime in days (default: 30)
- `ALGORITHM`: JWT signing algorithm (default: "HS256")
- `MONITORING_ENABLED`: Offer Grafana at `/grafana/` to superusers (default: false). The same `.env` value the gateway reads; the compose profile `monitoring` must be on too. While false, `monitoring_url` is null and `POST /auth/grafana-session` answers 403.

### Database Connection
- `POSTGRES_SERVER`: Database host (default: "localhost")
- `POSTGRES_USER`: Database username (default: "postgres")
- `POSTGRES_PASSWORD`: Database password (default: "postgres")
- `POSTGRES_DB`: Database name (default: "auth_db")
- **OR** `DATABASE_URL`: Full connection string (overrides individual POSTGRES_* vars)

### Redis Configuration (Optional - for token blacklisting)
- `REDIS_HOST`: Redis host (default: "localhost")
- `REDIS_PORT`: Redis port (default: 6379)
- `REDIS_DB`: Redis database number (default: 0)

### SMTP Configuration (For Email Verification)
- `SMTP_TLS`: Enable TLS (default: True)
- `SMTP_PORT`: SMTP port (default: 587)
- `SMTP_HOST`: SMTP hostname
- `SMTP_USER`: SMTP username
- `SMTP_PASSWORD`: SMTP password
- `EMAILS_FROM_EMAIL`: Sender email address
- `EMAILS_FROM_NAME`: Sender name
- `EMAIL_VERIFICATION_EXPIRE_HOURS`: hours a registration's verification link stays valid (default: 24)
- `PASSWORD_RESET_EXPIRE_MINUTES`: minutes a password-reset link stays valid (default: 30)
- `BASE_URL`: base URL used to build the verification and reset links in the email (default: `http://localhost:8000`)

When `SMTP_HOST` is unset (the default), verification and reset links are logged at WARNING rather than emailed -- this keeps registration and recovery usable in development and tests without a real mail server. Configure `SMTP_HOST` to send real email.

### SSO Provider Configuration
- `GOOGLE_CLIENT_ID`: Google OAuth Client ID
- `GOOGLE_CLIENT_SECRET`: Google OAuth Client Secret

- `AZURE_CLIENT_ID`: the Entra app registration's client id (the required token audience)
- `AZURE_ALLOWED_TENANTS`: comma-separated tenant ids allowed to sign in (empty: `AZURE_TENANT_ID`, if set)
- `AUTH_SSO_ONLY`: SSO-only mode (default `false`, ADR-031). People sign in only with the providers below; active superusers keep password sign-in (break-glass, MFA still applies).
- `AUTH_SSO_PROVIDERS`: comma-separated providers allowed in the mode (default `microsoft`; valid: `microsoft`, `google`). With the mode on, start-up stops when a listed provider is unknown or not configured, and logs the missing setting's name. With the mode on and no active superuser, start-up logs a WARNING.

Without both, `POST /sso/microsoft` answers 503. The settings below are accepted by the config
module but nothing reads them yet:
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` (GitHub SSO returns 501)
- `AZURE_CLIENT_SECRET` (the ID-token flow needs no secret)
- `SAML_SETTINGS`

#### Setting up Microsoft sign-in

1. In Entra ID, register an application as a **single-page application** with your frontend's
   redirect URI, and enable **ID tokens**. Its *Application (client) ID* is `AZURE_CLIENT_ID`.
2. Put your tenant id (and each customer tenant you onboard) in `AZURE_ALLOWED_TENANTS`. A
   sign-in from any other tenant is refused and its tenant id is logged — copy it from there.
3. In the frontend, get an ID token with MSAL and post it:

```js
const msal = new PublicClientApplication({ auth: { clientId: "<AZURE_CLIENT_ID>",
  authority: "https://login.microsoftonline.com/organizations" } });
await msal.initialize();
const { idToken } = await msal.loginPopup({ scopes: ["openid", "profile", "email"] });
await fetch("/api/v1/sso/microsoft", { method: "POST",
  headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credential: idToken }) });
```

The account's email is the user principal name (`preferred_username`), which Entra only allows
on the tenant's verified domains. The `email` claim is used only when the app registration adds
the optional claim `xms_edov` and it is `true`: Entra does not verify `email` (a tenant admin can
set it to any address). The address must be one the user model accepts; otherwise sign-in answers
400 "Microsoft account has no email address". Tokens get 60 s of clock leeway.

### CORS Configuration
- `BACKEND_CORS_ORIGINS`: List of allowed origins (default: ["http://localhost:3000", "http://localhost:8000"])

## API Endpoints

### Authentication
- `GET /api/v1/auth/methods` - Public. `{"password": true|false, "providers": [...]}`: `password` is `false` in SSO-only mode (the superuser break-glass is not advertised); `providers` lists the configured providers (`microsoft`, `google`), limited to `AUTH_SSO_PROVIDERS` in the mode. No per-user data. The dashboard's sign-in and recovery pages read it (ADR-031).
- `POST /api/v1/auth/register` - Begin registration. Creates an unclaimed, expiring pending record and emails a verification link -- returns `202`, not a user. The address is not reserved until verified.
- `GET /api/v1/auth/verify-email?token=...` - Complete registration: creates the account and returns `Token` (auto-login). `400` if the token is invalid or expired; `409` if the address was claimed by another path (e.g. Google SSO) in the meantime.
- `POST /api/v1/auth/resend-verification` - Resend the verification link. Always answers identically regardless of whether the address has a pending registration, a completed account, or neither. Declines to act (same response, nothing sent) when more than one unexpired registration attempt exists for the address -- which of them is legitimate isn't knowable from this endpoint alone.
- `POST /api/v1/auth/login` - Login with email/password (returns access & refresh tokens)
- `POST /api/v1/auth/refresh-token` - Refresh access token using refresh token
- `POST /api/v1/auth/logout` - Logout by revoking refresh token (body or cookie; the body is optional). Every answer -- `200`, `400` (unknown refresh token, inactive user) and `401` (access token missing or expired) -- clears both refresh cookies and the `qeos_grafana` cookie (`Path=/grafana`), so a browser always ends signed out.
- `POST /api/v1/auth/grafana-session` - Bearer access token only. For an active superuser while `MONITORING_ENABLED` is true, answers `200 {"url": "/grafana/"}` and sets the `qeos_grafana` cookie (see Token Management); `403` for anyone else or while monitoring is off; `401` without a valid access token. The dashboard's `/monitoring` page calls it, then opens Grafana (ADR-027).
- `POST /api/v1/auth/forgot-password` - `{email}`. Always `202` with the same body, so it reveals no accounts. For an account with a password, cancels earlier unused links and emails a new one (`/reset-password?token=…`). SSO-only accounts get nothing.
- `POST /api/v1/auth/reset-password` - `{token, password}` (min 8). Sets the password and revokes every refresh session. `400 "Invalid or expired reset token"` when used, expired, superseded or unknown.
- `POST /api/v1/auth/change-password` - Signed in; `{current_password, new_password}`. Revokes every refresh session, then returns a fresh `Token` for this client. `400` on a wrong current password or an SSO-only account.

### SSO Authentication
- `POST /api/v1/sso/google` - Authenticate with a Google ID token
- `POST /api/v1/sso/github` - **501, not implemented**
- `POST /api/v1/sso/microsoft` - Authenticate with a Microsoft (Entra ID) ID token from an allowed tenant
- `POST /api/v1/users/me/link/microsoft` - Link a Microsoft identity to the signed-in account (requires `current_password` when the account has one)

### SSO-only mode (ADR-031)
With `AUTH_SSO_ONLY=true`, every refusal answers `403 {"detail": {"code": "sso_only", "message": "Sign-in is through Microsoft only."}}` (the names come from `AUTH_SSO_PROVIDERS`):
- `POST /auth/register`, `GET /auth/verify-email`, `POST /auth/resend-verification`, `POST /auth/forgot-password`, `POST /auth/reset-password`: always.
- `POST /auth/login`: the password is checked first; an active superuser goes on (MFA still asks for its code); everyone else gets the same 403, right or wrong password, so the answer reveals neither superuser status nor password validity. Each successful password sign-in is logged at WARNING: `break-glass sign-in: user_id=… email=… ip=… at=…`.
- `POST /auth/mfa/verify`: refuses a non-superuser's challenge (one issued just before the switch) without spending its code.
- `POST /auth/change-password` and a password in `PUT /users/me`: superusers only.
- `/sso/{provider}` and `/users/me/link/{provider}` for a provider not in `AUTH_SSO_PROVIDERS` (GitHub always).

Sessions: the table `auth_mode_state` (migration 008, one row) records the mode last applied. At start-up, when `AUTH_SSO_ONLY=true` and the stored value is `false`, auth-service revokes every refresh session of every user who is not a superuser, then stores `true`, in one transaction that locks the row (`SELECT … FOR UPDATE`): each off-to-on change revokes once, restarts do not. Access tokens already issued work until they expire (at most `ACCESS_TOKEN_EXPIRE_MINUTES`); the next refresh is refused.

### User Management
- `GET /api/v1/users/me` - Get current user's profile. `monitoring_url` is `"/grafana/"` for a superuser while `MONITORING_ENABLED` is true, otherwise `null`; the dashboard shows its Monitoring item only when it is set. Also `linked_providers` (sorted provider names linked to the account), `sso_only` (the mode) and `has_password` (whether linking needs `current_password`), for the Security page (ADR-031).
- `PUT /api/v1/users/me` - Update current user's profile. Accepts `UserSelfUpdate` only: password (with `current_password`), full_name, avatar_url, department, job_title. Unknown fields are rejected with 422 rather than silently ignored, so `email`, `is_active` and `is_superuser` all fail loudly. Changing a password revokes every session; an SSO account cannot gain a password here.
- `POST /api/v1/users/me/link/google` - Link a Google identity to the current authenticated account. Requires `current_password` unless the account is passwordless. Refuses if that identity is linked elsewhere, or if the caller already has a Google link.
- `GET /api/v1/users/` - List all users (SUPERUSER ONLY)
- `GET /api/v1/users/sso-readiness` - SUPERUSER ONLY (ADR-031). `{"active_users", "linked", "unlinked": [{"id", "email", "full_name", "is_superuser", "link_allowed_until"}]}`: active users without a Microsoft link, by email, superusers included; `link_allowed_until` is null unless a valid allowance exists.
- `POST /api/v1/users/{user_id}/allow-microsoft-link` - SUPERUSER ONLY. Lets that account link Microsoft at its next Microsoft sign-in, for 7 days; logged at WARNING (who, whom, until). Returns the readiness entry. `404` unknown user; `409` already linked or inactive.
- `GET /api/v1/users/{user_id}` - Get a user by id (own account, or any account for a superuser)

There is no endpoint that grants superuser through the API. It is either bootstrapped once at startup from `FIRST_SUPERUSER`/`FIRST_SUPERUSER_PASSWORD` (permanent no-op once any superuser exists) or set directly in the database.

### Internal (for the gateway and other services)
Mounted at `/internal/v1`, outside the public OpenAPI; the gateway never routes `/internal/`. `GET /internal/v1/users` and `GET /internal/v1/users/{user_id}` take HTTP Basic (`INTERNAL_API_USERNAME` / `INTERNAL_API_PASSWORD`).
- `GET /internal/v1/grafana-check` - The check the gateway's `auth_request` calls for every `/grafana/` request while `MONITORING_ENABLED` is true (`gateway/grafana-on.conf`; the subrequest carries only the browser's cookies). No HTTP Basic: the `qeos_grafana` cookie is the only credential, and the `Authorization` header is ignored. Answers `200` with `X-QEOS-User-Email: <email>` and an empty body when the cookie is valid, its user exists, is active and a superuser, its `pwv` matches `password_version(user)` (constant-time compare), and `MONITORING_ENABLED` is true; `401` with an empty body otherwise, with no `WWW-Authenticate` so a browser never shows a Basic dialog. Every answer is `Cache-Control: no-store`. The user is re-read on every call, so a demotion, deactivation or password change cuts access at once.

## Security Implementation Details

### Password Security
- Passwords hashed using bcrypt with work factor 12 via `passlib[bcrypt]`
- Never stored or transmitted in plain text
- Secure comparison using constant-time algorithms

### Token Management
- Access tokens: JWT signed with HMAC-SHA256, configurable expiration (default 60 minutes)
- Refresh tokens: opaque 32-byte random strings (`secrets.token_urlsafe`) stored in `refresh_tokens`, default 30d. They are not JWTs — being database rows is what makes revocation immediate and rotation meaningful.
- Refresh token rotation: on each use the presented token is revoked and a new one issued
- Expiry is enforced on verification, not only at issuance
- With a valid access token, logout revokes only a token belonging to the caller, so knowing someone else's token value does not let you end their session. Without one (the tab idled past the access token's lifetime), it revokes the refresh tokens presented and answers `401`: holding a refresh token already lets you spend it at `/auth/refresh-token`, which revokes it on rotation, so this grants nothing more
- Grafana cookie `qeos_grafana` (`src/auth/utils/grafana_session.py`): a JWT signed with the same `SECRET_KEY` and algorithm, carrying the user id, `aud: "grafana"` and `token_type: "grafana"`, a `pwv` claim (`password_version`: HMAC-SHA256 of the password hash keyed with `SECRET_KEY`, first 16 hex characters), valid 8 hours. Set httpOnly, Secure, SameSite=Strict, `Path=/grafana`, `Max-Age=28800`, so it reaches only `/grafana/` and never the API. Its own audience keeps it apart from access tokens both ways: every `decode_token` refuses a token carrying `aud`, and `token_type` fails `is_access_token`, so it is never a session; an access token has no `aud`, so `grafana_claims` refuses it. Issued only to active superusers while monitoring is on; logout clears it, and a password change or reset makes `pwv` stale, which invalidates every cookie minted before it.

### Request Validation
- All input validated using Pydantic models
- Email format validation, password strength rules, length constraints
- Automatic 422 responses for malformed requests with detailed error messages

### SSO Security
- Google ID tokens are verified against Google's published JWKS: RS256 signature, `aud` matching `GOOGLE_CLIENT_ID`, issuer in Google's set, `exp`, and `email_verified` being boolean `true`
- With no `GOOGLE_CLIENT_ID` configured the endpoint returns 503 rather than verifying without an audience, which would accept ID tokens minted for any other Google application
- Just-in-time provisioning: a first-time Google user is created with no password
- **Identity is the Google `sub`, not the email.** A returning user is resolved through the `(provider, provider_user_id)` link, so a Google account whose address changed still reaches its own account, and the new address is not written back.
- **Google is never linked to an account that already exists.** A verified Google email proves control of the mailbox, not ownership of a local account sharing that address, so only a first-time address creates an account; any address already held returns 409. An earlier version auto-linked when the existing row had no password, reasoning that there was no credential to hijack — but a passwordless unlinked row is exactly what pre-provisioning produces, so that handed a seeded account (possibly a superuser) to whoever presented a Google token for the address first. Adopting SSO on an existing account now has its own endpoint: `POST /users/me/link/google` (authenticated). It requires `current_password` when the account has one -- an access token can be a short-lived, stolen bearer credential, and linking a new, durable login method to an account is exactly the kind of change that must not be reachable by holding one for a minute; the same reasoning as the password-change guard. Refuses (409) if the Google identity is already linked to a different account, or if the caller already has a Google link (at most one per user).

- **Microsoft** follows the same account rules (identity first, no linking by email, inactive users refused). Its tokens must be v2.0, signed with Microsoft's keys (RS256), meant for `AZURE_CLIENT_ID`, from a tenant in `AZURE_ALLOWED_TENANTS`, with `iss` naming that same tenant — all tenants share one key set, so the signature alone does not prove the tenant. The identity key is `tid:oid` (an object id is unique only within its tenant). The account email is the UPN (`preferred_username`), on one of the tenant's verified domains; the unverified `email` claim is used only with `xms_edov: true`. Existing accounts are still never adopted by email.
- Signing keys (Google and Microsoft) are fetched with a 5 s timeout and cached; a token naming an unknown key id forces at most one re-fetch per 5 minutes. A provider outage answers 503, not "invalid token".

**Remaining limitation:** self-service email *changes* on `PUT /users/me` are still not accepted at all (422). Verifying a new address the same way registration now does is not built, so allowing changes would reopen the address-squatting problem registration itself no longer has.

### Administrative Controls
- Superuser-only endpoints protected by role-based checks
- Sensitive operations (user listing, admin lookups) restricted to privileged accounts
- Regular users can only access their own data

## Project Structure

```
src/
└── auth/                    # Main Python package
    ├── api/                 # FastAPI route handlers
    │   ├── v1/              # API version 1
    │   │   ├── endpoints/   # Route definitions
    │   │   │   ├── auth.py      # Authentication endpoints
    │   │   │   ├── users.py     # User management endpoints
    │   │   │   └── sso.py       # SSO authentication endpoints
    │   │   └── deps.py        # Dependency injection (DB, auth)
    │   └── main.py          # Application entry point
    ├── core/                # Core configuration and settings
    │   └── config.py        # Pydantic settings management
    ├── db/                  # Database layer
    │   ├── session.py       # Database session management
    │   └── models/          # SQLAlchemy models
    ├── models/              # Pydantic and SQLAlchemy models
    │   ├── user.py          # User model and related entities
    │   └── oauth.py         # OAuth account linking model
    ├── schemas/             # Pydantic validation schemas
    │   ├── auth.py          # Authentication request/response models
    │   └── user.py          # User request/response models
    ├── service/             # Business logic layer
    │   ├── user_service.py  # User CRUD and authentication logic
    │   ├── auth_service.py  # Token creation, validation, refresh logic
    │   └── sso_service.py   # SSO token validation and processing
    ├── utils/               # Utility functions
    │   ├── password.py      # Bcrypt password hashing/verification
    │   ├── tokens.py        # JWT token creation and validation
    │   └── dependencies.py  # FastAPI dependencies (auth, DB)
    └── tests/               # Test suite
        ├── conftest.py      # Pytest fixtures and configuration
        ├── test_*py         # Unit and integration tests
```

## Metrics

`GET /metrics` (Prometheus text, inside the Docker network only; the gateway never routes it) serves the shared request metrics from `qeos_shared.metrics` — `api_requests_total`, `http_requests_duration_seconds`, `http_requests_in_flight`, `build_info` — and the process metrics. See the monitoring design, `docs/superpowers/specs/2026-10-10-monitoring-design.md`.

## Running Tests

```bash
# From the auth-service directory
pytest

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Run specific test files
pytest tests/test_auth_endpoints.py
pytest tests/test_user_service.py
```

## Docker Deployment

### Development
```bash
export SECRET_KEY=<a long random value>
docker compose up --build
```

### Production
```bash
# Build image -- the context is the repository root, so the image can COPY shared/
docker build -f Dockerfile -t qtauth-service ../../..

# Run container
docker run -p 8000:8000 \
  --env-file .env.prod \
  qtauth-service
```

### docker-compose.yml Services
- `app`: FastAPI application server
- `db`: PostgreSQL database
- `redis`: Redis instance (optional, for token blacklisting)

## Production Considerations

### Environment Security
- **SECRET_KEY**: Must be strong and kept secret (use secrets manager in production)
- **Database Credentials**: Use managed secrets or environment-specific configuration
- **SSO Credentials**: Store provider secrets securely (never commit to version control)

### Performance & Scaling
- Database connection pooling configured via SQLAlchemy
- Stateless API design enables horizontal scaling behind load balancer
- Redis recommended for token blacklisting in multi-instance deployments
- Consider CDN for serving OpenAPI documentation in production

### Monitoring & Observability
- Structured logging recommended for production deployment
- Health check endpoint available at `/health` (add via middleware if needed)
- Consider integrating with APM (Application Performance Monitoring) tools
- Audit logging for security-sensitive operations (login attempts, privilege changes)

### Backup & Recovery
- Regular database backups recommended
- Point-in-time recovery capability depends on PostgreSQL configuration
- Test backup and restore procedures regularly

## Maintenance

### Database Migrations
```bash
# Generate new migration after model changes
alembic revision --autogenerate -m "description"

# Apply pending migrations
alembic upgrade head

# Rollback last migration
alembic downgrade -1
```

### Dependency Updates
```bash
# Check for outdated packages
pip list --outdated

# Update specific package
pip install -U package-name

# Update all packages (review changes first!)
pip list --outdated --format=freeze | grep -v '^\-e' | cut -d = -f 1 | xargs -n1 pip install -U
```

## Troubleshooting

### Common Issues

**Database Connection Errors**
- Verify PostgreSQL is running and accessible
- Check `POSTGRES_*` environment variables or `DATABASE_URL`
- Ensure database exists and user has correct permissions

**Authentication Failures**
- Verify `SECRET_KEY` is consistent across all instances (if scaled)
- Check token expiration settings
- Ensure bcrypt is properly installed (`pip install passlib[bcrypt]`)

**SSO Authentication Issues**
- Verify Google Client ID/Secret are correctly configured
- Check system clock synchronization (token validation is time-sensitive)
- Review OAuth consent screen configuration in Google Cloud Console

**Email Verification Issues**
- Verify SMTP server connectivity and credentials
- Check `EMAILS_FROM_EMAIL` and `EMAILS_FROM_NAME` settings
- Test email delivery independently of application
- With `SMTP_HOST` unset, verification links are logged instead -- check application logs at INFO level rather than a mail server

### Log Analysis
- Application logs startup configuration and connection status
- Authentication attempts logged at INFO level (no credentials, password hashing, user creation, and token operations)
- Clean interfaces for token generation and validation
- Integrates with user service for data persistence and uses secure password handling via bcrypt

Usage: The auth service is called by API endpoints to handle user registration, login, password reset, and session management. It ensures secure credential storage and verification while providing clean interfaces for token generation and validation.