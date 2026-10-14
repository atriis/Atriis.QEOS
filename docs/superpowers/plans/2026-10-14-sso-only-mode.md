# SSO-only mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deployment can switch people to Microsoft (Entra ID) sign-in only, with active superusers keeping a password break-glass, a readiness view of who has not linked Microsoft, and a one-time link allowance a superuser can grant.

**Architecture:** auth-service gains two settings (`AUTH_SSO_ONLY`, `AUTH_SSO_PROVIDERS`), one module that owns the mode (`service/auth_mode.py`: start-up check, provider lists, the 403, the break-glass log, the off-to-on session revocation recorded in a one-row `auth_mode_state` table), guards on the password and provider routes, a public `GET /auth/methods`, readiness and allowance endpoints (`service/sso_readiness.py`), and an allowance branch in `/sso/microsoft`. The dashboard reads `/auth/methods` to switch the login and recovery pages, and `/users/me` (`linked_providers`, `sso_only`, `has_password`) to drive two new Security cards.

**Tech Stack:** FastAPI 0.143, SQLAlchemy 2.1, Alembic, Pydantic 2 (auth-service); React 19, TypeScript, React Router 7, MSW 3, Vitest (dashboard).

**Spec:** `docs/superpowers/specs/2026-10-14-sso-only-mode-design.md` (binding; read it before any task).

## Global Constraints

- `AUTH_SSO_ONLY`: bool, default `false`. `AUTH_SSO_PROVIDERS`: comma-separated string, default `"microsoft"`; valid names `microsoft`, `google` only (trimmed, case-insensitive). Any other name, an empty list, or a listed provider that is not configured (Microsoft: `AZURE_CLIENT_ID` and at least one allowed tenant from `AZURE_ALLOWED_TENANTS`/`AZURE_TENANT_ID`; Google: `GOOGLE_CLIENT_ID`) stops start-up while the mode is on.
- Every refusal in the mode answers 403 with exactly `{"detail": {"code": "sso_only", "message": "Sign-in is through Microsoft only."}}` (the provider names in the message come from `AUTH_SSO_PROVIDERS`: `"Sign-in is through Microsoft or Google only."` when both are listed).
- `POST /auth/login` in the mode: the password is verified first, exactly as today; then only an **active superuser** with the right password goes on (MFA still asks for its code); every other case gets the same 403 — same status, same body, no `WWW-Authenticate` header.
- Every password sign-in that succeeds in the mode logs one WARNING line `break-glass sign-in: user_id=<id> email=<email> ip=<ip> at=<ISO-8601 UTC>` on logger `src.auth.service.auth_mode`.
- No secret value is ever logged: not a password, token, client id or tenant id. Start-up errors name the **setting**, never its value.
- Link allowance: `users.microsoft_link_allowed_until` = now + **7 days**; logged at WARNING (who allowed whom, until when); used once; never matched on email alone (a superuser allowed that account, the token is from an allowed tenant).
- Migration **008** (`platforms/auth-service/auth-service/alembic/versions/008_sso_only_mode.py`, `down_revision = "007"`) adds `auth_mode_state` and `users.microsoft_link_allowed_until`. Sessions are rows of the `refresh_tokens` table (model `RefreshToken` in `src/auth/models/session.py`), not a table called `sessions`.
- The off-to-on revocation runs once per change, in one transaction that reads the state row with `SELECT … FOR UPDATE`; restarts with the mode already on revoke nothing; superuser sessions are never revoked.
- Docs are updated in the same commit as the behaviour they describe (README, SECURITY, SETUP, PRODUCT, TODO, TECHNICAL_SPECIFICATION, DESIGN, the auth-service README, `.env.example`, ADR-031).
- Never write the employer's name in code, tests, docs or commits; use `example.com` addresses and placeholder tenant ids.
- Another session works in a separate worktree: stage and commit only your own paths (`git add <paths>` then `git commit -o <paths>`); never `git add -A`, never push. The user pushes after the full CI mirror passes.
- Every dashboard UI task starts by invoking the `ui-ux-pro-max` skill (project rule). Existing classes only: `card`, `form-stack`, `button-row`, `success-note`, `mfa-status`, `muted`, `more-filters` (disclosure), `table.data`, `sr-only`; errors through `ErrorBanner`.

**How to run things (Git Bash, repo root `C:/dev/github/Atriis.QEOS`):**

- auth-service tests, from `platforms/auth-service/auth-service`:
  `PY=/c/dev/projects/QA-Vision-Platform/platforms/auth-service/auth-service/.venv/Scripts/python.exe`
  then `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/<file> -q` (one file) or `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` (all; 195 tests, about 2.5 minutes at planning time). CI sets only `SECRET_KEY`. If that interpreter is missing or cannot import `qeos_shared`, create a venv in the service directory and `python -m pip install -r requirements.txt` (it installs `../../../shared` editable).
- The tests run on SQLite (`tests/conftest.py`, a temp file per run, tables created per test). `SELECT … FOR UPDATE` is silently dropped on SQLite, so the lock is pinned by compiling the query for PostgreSQL (Task 4); migrations are tested offline (`alembic … sql=True`), as `tests/unit/test_alembic_env.py` already does, because their `now()` defaults do not run on SQLite.
- Dashboard, from `dashboard/`: `npx vitest run <files>`, `npm run lint`, `npm run typecheck`, `npm run build`. The full suite has flaky 15 s timeouts under machine load: run the touched files, and the full suite with `npx vitest run --no-file-parallelism` at the delivery gate.
- Architecture docs: `python scripts/check_architecture_docs.py` from the repo root (exit 0).

## Review Focus

1. **A login refusal that leaks who is a superuser or which passwords are right.** A non-superuser with the right password, the same with a wrong one, a superuser with a wrong password, an inactive superuser, a passwordless SSO account and an unknown address must all get byte-identical 403s (status, body, no `WWW-Authenticate`). Pinned in Task 3 (`test_a_login_refusal_never_tells_who_is_a_superuser`).
2. **The revocation running again on a restart, or not at all on a re-enable.** A session created after the switch (a Microsoft sign-in) must survive a restart with the mode still on; off then on again must revoke again; a user whose `is_superuser` is NULL counts as not a superuser. Pinned in Task 4 (`test_a_restart_with_the_mode_on_revokes_nothing`, `test_off_then_on_again_revokes_again`, `test_a_null_superuser_flag_is_not_a_superuser`).
3. **An allowance consumed by the wrong identity.** A Microsoft token for a different address must create that person's own account and leave the allowance where it was; an allowance must never replace an existing Microsoft link or link an inactive account; a token from a tenant that is not allowed never reaches it. Pinned in Task 7 (`test_the_allowance_belongs_to_its_account_not_to_the_next_token`, `test_an_allowance_does_not_replace_an_existing_link`, `test_an_allowance_on_an_inactive_account_does_not_link`, `test_a_token_from_another_tenant_never_uses_the_allowance`).
4. **`/auth/methods` failing or answering something unexpected on the login page** (500, network error, an old server's 404, a 200 of the wrong shape) — the page must show the normal password form and not crash; the server still enforces the mode. Pinned in Task 8 (`when /auth/methods gives %s, the normal form stays`).
5. **The MFA step around the switch.** A superuser with MFA in the mode gets the challenge, completes it and is logged as break-glass; an ordinary user's MFA challenge issued just before the switch must not complete afterwards (and must not burn the recovery code). Pinned in Task 3 (`test_a_superuser_with_mfa_still_gives_the_code`, `test_an_mfa_challenge_from_before_the_switch_lets_no_ordinary_user_in`).

## File Structure

auth-service (`platforms/auth-service/auth-service/`):

- `src/auth/config.py` — the two settings.
- `src/auth/service/auth_mode.py` (new) — everything about the mode itself: provider lists, start-up check, no-superuser warning, the 403, client IP and break-glass log, `apply_auth_mode` (revocation).
- `src/auth/models/auth_mode.py` (new) — `AuthModeState`.
- `src/auth/service/sso_readiness.py` (new) — readiness counts, allowance validity, allowing a link.
- `src/auth/api/main.py` — start-up hook.
- `src/auth/api/deps.py` — `password_routes_enabled`, `sso_provider_allowed(provider)`.
- `src/auth/api/v1/endpoints/auth.py`, `sso.py`, `users.py` — guards, `/auth/methods`, readiness, allowance.
- `src/auth/schemas/auth.py` (`AuthMethods`), `src/auth/schemas/user.py` (`UserMe` fields, `SsoReadinessEntry`, `SsoReadiness`).
- `src/auth/models/user.py` — `microsoft_link_allowed_until`.
- `alembic/versions/008_sso_only_mode.py` (new).
- Tests: `tests/conftest.py` (fixtures), `tests/unit/test_auth_mode.py` (new), `tests/integration/test_sso_only.py` (new), `tests/integration/test_microsoft_sso.py`, `tests/unit/test_alembic_env.py`.

Dashboard (`dashboard/src/`):

- `api/auth.ts` — `getAuthMethods`, `Me`, `linkMicrosoft`, `getSsoReadiness`, `allowMicrosoftLink`.
- `auth/useAuthMethods.ts` (new) — the hook and the SSO-only helpers.
- `components/SsoOnlyNotice.tsx` (new) — the notice the four recovery pages show.
- `pages/LoginPage.tsx`, `RegisterPage.tsx`, `ForgotPasswordPage.tsx`, `ResetPasswordPage.tsx`, `VerifyEmailPage.tsx`, `SecurityPage.tsx` and their tests; `test/server.ts` (default `/auth/methods` handler).

Repo: `docker-compose.yml`, `.env.example`, `scripts/smoke_gateway.sh`, `docs/architecture/adr/ADR-031-sso-only-mode.md` (new), `docs/architecture/adr/INDEX.md`, `docs/SETUP.md`, `SECURITY.md`, `PRODUCT.md`, `TODO.md`, `TECHNICAL_SPECIFICATION.md`, `DESIGN.md`, `platforms/auth-service/auth-service/README.md`. No gateway change: `location /api/v1/auth` already routes `/api/v1/auth/methods`.

---

## Delivery 1 — auth-service

### Task 1: Settings, start-up check, no-superuser warning, ADR-031

**Files:**
- Modify: `platforms/auth-service/auth-service/src/auth/config.py` (after `SAML_SETTINGS`)
- Create: `platforms/auth-service/auth-service/src/auth/service/auth_mode.py`
- Modify: `platforms/auth-service/auth-service/src/auth/api/main.py` (new start-up hook)
- Modify: `platforms/auth-service/auth-service/tests/conftest.py` (fixtures `sso_only`, `make_user`, `auth_header`)
- Create: `platforms/auth-service/auth-service/tests/unit/test_auth_mode.py`
- Modify: `docker-compose.yml` (`x-auth-env`), `.env.example`, `docs/SETUP.md` §3.8, `platforms/auth-service/auth-service/README.md`
- Create: `docs/architecture/adr/ADR-031-sso-only-mode.md`; Modify: `docs/architecture/adr/INDEX.md`

**Interfaces:**
- Produces (in `src.auth.service.auth_mode`): `VALID_PROVIDERS: tuple[str, ...] = ("microsoft", "google")`, `PROVIDER_LABELS: dict[str, str]`, `class AuthModeConfigError(RuntimeError)`, `sso_only_providers() -> list[str]`, `configured_providers() -> list[str]`, `available_providers() -> list[str]`, `check_sso_only_settings() -> None` (raises `AuthModeConfigError`), `warn_if_no_break_glass(db: Session) -> None`.
- Produces (in `src.auth.api.main`): `_apply_auth_mode() -> None`, registered with `@app.on_event("startup")` after `_bootstrap_first_superuser`.
- Produces (in `tests/conftest.py`): fixtures `sso_only` (mode on, Microsoft configured with client id `11111111-2222-3333-4444-555555555555` and tenant `aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee`, Google unset), `make_user` (factory `make_user(email, *, superuser=False, active=True, password="securepassword123") -> User`; `password=None` makes a passwordless account), `auth_header` (factory `auth_header(user) -> dict` with a Bearer access token).

- [ ] **Step 1: Add the test fixtures to `tests/conftest.py`** (append at the end of the file):

```python
SSO_CLIENT_ID = "11111111-2222-3333-4444-555555555555"
SSO_TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TEST_PASSWORD = "securepassword123"


@pytest.fixture
def sso_only(monkeypatch):
    """SSO-only mode (ADR-031) with Microsoft configured, Google not. The endpoints read settings per request,
    so this works whether it is set up before or after `client`. The ids match tests/integration/test_microsoft_sso.py."""
    from src.auth.config import settings

    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", SSO_CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", SSO_TENANT)
    monkeypatch.setattr(settings, "AZURE_TENANT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")


@pytest.fixture
def make_user(db):
    """A user row written straight to the database; `password=None` is a passwordless (SSO) account."""
    from src.auth.models.user import User
    from src.auth.utils.password import get_password_hash

    def _make(email, *, superuser=False, active=True, password=TEST_PASSWORD):
        user = User(
            email=email,
            hashed_password=get_password_hash(password) if password else None,
            is_active=active,
            is_superuser=superuser,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture
def auth_header():
    from src.auth.utils.tokens import create_access_token

    return lambda user: {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}
```

- [ ] **Step 2: Write the failing tests** — create `tests/unit/test_auth_mode.py`:

```python
"""SSO-only mode (ADR-031): the settings, the start-up check and the break-glass warning."""
import logging

import pytest

from src.auth.api.main import _apply_auth_mode
from src.auth.config import Settings, settings
from src.auth.service.auth_mode import (
    AuthModeConfigError,
    available_providers,
    check_sso_only_settings,
    configured_providers,
    sso_only_providers,
    warn_if_no_break_glass,
)

TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"
LOGGER = "src.auth.service.auth_mode"


@pytest.fixture
def nothing_configured(monkeypatch):
    for name in ("AZURE_CLIENT_ID", "AZURE_ALLOWED_TENANTS", "AZURE_TENANT_ID", "GOOGLE_CLIENT_ID"):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)


def test_the_mode_is_off_by_default_and_lists_microsoft():
    assert Settings.model_fields["AUTH_SSO_ONLY"].default is False
    assert Settings.model_fields["AUTH_SSO_PROVIDERS"].default == "microsoft"


def test_with_the_mode_off_nothing_is_checked(nothing_configured, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    check_sso_only_settings()


@pytest.mark.parametrize("present, missing", [
    ({}, "AZURE_CLIENT_ID"),
    ({"AZURE_CLIENT_ID": CLIENT_ID}, "AZURE_ALLOWED_TENANTS"),
    ({"AZURE_ALLOWED_TENANTS": TENANT}, "AZURE_CLIENT_ID"),
])
def test_start_up_refuses_microsoft_without_its_settings(nothing_configured, monkeypatch, caplog, present, missing):
    for name, value in present.items():
        monkeypatch.setattr(settings, name, value)
    with caplog.at_level(logging.ERROR, logger=LOGGER), pytest.raises(AuthModeConfigError, match=missing):
        check_sso_only_settings()
    assert missing in caplog.text
    # The setting is named, its value never written
    assert CLIENT_ID not in caplog.text and TENANT not in caplog.text


def test_azure_tenant_id_counts_as_an_allowed_tenant(nothing_configured, monkeypatch):
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_TENANT_ID", TENANT)
    check_sso_only_settings()


def test_google_listed_but_not_configured_stops_start_up(nothing_configured, monkeypatch):
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", TENANT)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft,google")
    with pytest.raises(AuthModeConfigError, match="GOOGLE_CLIENT_ID"):
        check_sso_only_settings()


@pytest.mark.parametrize("listed", ["github", "microsoft,okta", "", " , "])
def test_an_unknown_or_empty_provider_list_stops_start_up(nothing_configured, monkeypatch, listed):
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", TENANT)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", listed)
    with pytest.raises(AuthModeConfigError, match="AUTH_SSO_PROVIDERS"):
        check_sso_only_settings()


def test_provider_names_are_trimmed_case_insensitive_and_deduplicated(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", " Microsoft , GOOGLE,microsoft ")
    assert sso_only_providers() == ["microsoft", "google"]


def test_available_providers_follow_the_mode(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", TENANT)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    assert configured_providers() == ["microsoft", "google"]
    assert available_providers() == ["microsoft", "google"]
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    assert available_providers() == ["microsoft"]


def test_the_start_up_hook_refuses_before_touching_the_database(nothing_configured):
    with pytest.raises(AuthModeConfigError):
        _apply_auth_mode()


def test_no_active_superuser_is_a_warning(db, make_user, monkeypatch, caplog):
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    make_user("ann@example.com")
    make_user("gone@example.com", superuser=True, active=False)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        warn_if_no_break_glass(db)
    assert "no active superuser" in caplog.text


def test_an_active_superuser_silences_the_warning(db, make_user, monkeypatch, caplog):
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    make_user("root@example.com", superuser=True)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        warn_if_no_break_glass(db)
    assert "no active superuser" not in caplog.text


def test_no_warning_while_the_mode_is_off(db, monkeypatch, caplog):
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        warn_if_no_break_glass(db)
    assert caplog.text == ""
```

- [ ] **Step 3: Run them to verify they fail**

Run (from `platforms/auth-service/auth-service`): `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_auth_mode.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'src.auth.service.auth_mode'`.

- [ ] **Step 4: Add the settings** to `src/auth/config.py`, directly after `SAML_SETTINGS: str = "{}"`:

```python
    # SSO-only mode (ADR-031): people sign in only with the providers in AUTH_SSO_PROVIDERS. Active
    # superusers keep password sign-in (break-glass, MFA still applies). With the mode on, start-up
    # refuses a listed provider that is not configured above.
    AUTH_SSO_ONLY: bool = False
    # Comma-separated; valid names: microsoft, google
    AUTH_SSO_PROVIDERS: str = "microsoft"
```

- [ ] **Step 5: Create `src/auth/service/auth_mode.py`:**

```python
"""SSO-only mode (ADR-031, docs/superpowers/specs/2026-10-14-sso-only-mode-design.md).

Settings: AUTH_SSO_ONLY, AUTH_SSO_PROVIDERS. Messages name a setting, never its value: client ids and
tenant ids stay out of the log.
"""
import logging

from sqlalchemy.orm import Session

from src.auth.config import settings
from src.auth.models.user import User

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ("microsoft", "google")
PROVIDER_LABELS = {"microsoft": "Microsoft", "google": "Google"}
_NOT_CONFIGURED = {
    "microsoft": "Microsoft is not configured: set AZURE_CLIENT_ID and AZURE_ALLOWED_TENANTS (or AZURE_TENANT_ID)",
    "google": "Google is not configured: set GOOGLE_CLIENT_ID",
}


class AuthModeConfigError(RuntimeError):
    """AUTH_SSO_ONLY=true with a provider that cannot work: auth-service must not start."""


def _listed_names() -> list[str]:
    names: list[str] = []
    for raw in settings.AUTH_SSO_PROVIDERS.split(","):
        name = raw.strip().lower()
        if name and name not in names:
            names.append(name)
    return names


def sso_only_providers() -> list[str]:
    """The valid providers AUTH_SSO_PROVIDERS lists, in its order."""
    return [name for name in _listed_names() if name in VALID_PROVIDERS]


def configured_providers() -> list[str]:
    """Providers whose tokens this deployment can verify: the same conditions their sign-in routes use."""
    found = []
    if settings.AZURE_CLIENT_ID and settings.azure_allowed_tenants:
        found.append("microsoft")
    if settings.GOOGLE_CLIENT_ID:
        found.append("google")
    return found


def available_providers() -> list[str]:
    """What GET /auth/methods offers: the configured providers, limited to AUTH_SSO_PROVIDERS in the mode."""
    configured = configured_providers()
    if not settings.AUTH_SSO_ONLY:
        return configured
    listed = sso_only_providers()
    return [name for name in configured if name in listed]


def check_sso_only_settings() -> None:
    """Refuse to start when the mode is on and a listed provider cannot work."""
    if not settings.AUTH_SSO_ONLY:
        return
    names = _listed_names()
    problems = [] if names else ["AUTH_SSO_PROVIDERS lists no provider (valid: microsoft, google)"]
    configured = configured_providers()
    for name in names:
        if name not in VALID_PROVIDERS:
            problems.append(f"AUTH_SSO_PROVIDERS names an unknown provider {name!r} (valid: microsoft, google)")
        elif name not in configured:
            problems.append(_NOT_CONFIGURED[name])
    for problem in problems:
        logger.error("AUTH_SSO_ONLY=true but %s", problem)
    if problems:
        raise AuthModeConfigError("; ".join(problems))


def warn_if_no_break_glass(db: Session) -> None:
    """Start-up goes on without an active superuser, but nobody could use the password break-glass."""
    if not settings.AUTH_SSO_ONLY:
        return
    superuser = db.query(User.id).filter(
        User.is_superuser == True, User.is_active == True  # noqa: E712
    ).first()
    if superuser is None:
        logger.warning(
            "SSO-only mode is on and there is no active superuser: nobody can use the break-glass password sign-in"
        )
```

- [ ] **Step 6: Register the start-up hook** in `src/auth/api/main.py`. Add the import next to the bootstrap import:

```python
from src.auth.service.auth_mode import check_sso_only_settings, warn_if_no_break_glass
```

and, directly after the `_bootstrap_first_superuser` function, add:

```python
@app.on_event("startup")
def _apply_auth_mode() -> None:
    # ADR-031. Registered after the bootstrap, so the superuser it creates counts for the warning.
    # A listed provider that cannot work stops start-up here, before any database access.
    check_sso_only_settings()
    db = SessionLocal()
    try:
        warn_if_no_break_glass(db)
    finally:
        db.close()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_auth_mode.py -q`
Expected: all PASS (17 tests).

- [ ] **Step 8: Forward the settings in `docker-compose.yml`.** In the `x-auth-env: &auth-env` block, after the `MONITORING_ENABLED` line, add:

```yaml
  # Microsoft sign-in (SETUP section 3.8) and SSO-only mode (ADR-031). Empty Azure values leave Microsoft off;
  # with AUTH_SSO_ONLY=true auth-service refuses to start unless every provider in AUTH_SSO_PROVIDERS is configured
  AZURE_CLIENT_ID: ${AZURE_CLIENT_ID:-}
  AZURE_TENANT_ID: ${AZURE_TENANT_ID:-}
  AZURE_ALLOWED_TENANTS: ${AZURE_ALLOWED_TENANTS:-}
  AUTH_SSO_ONLY: ${AUTH_SSO_ONLY:-false}
  AUTH_SSO_PROVIDERS: ${AUTH_SSO_PROVIDERS:-microsoft}
```

Check: `docker compose config --quiet` exits 0 (needs `SECRET_KEY` and `INTERNAL_API_PASSWORD` in the environment or `.env`; `SECRET_KEY=x INTERNAL_API_PASSWORD=x docker compose config --quiet`).

- [ ] **Step 9: `.env.example`.** Replace the block that starts `# SSO (optional) — pair with the auth-service allowlist configuration.` with:

```
# SSO (optional). The dashboard's buttons need the VITE_* ids at build time; auth-service needs the
# same client ids to verify tokens (docs/SETUP.md section 3.8).
#VITE_GOOGLE_CLIENT_ID=
#VITE_MSAL_CLIENT_ID=
#VITE_MSAL_AUTHORITY=
#AZURE_CLIENT_ID=
#AZURE_ALLOWED_TENANTS=
# Microsoft-only sign-in (ADR-031). Link everyone first (Security page), then set true and restart
# auth-service: sessions of everyone who is not a superuser end. Superusers keep password sign-in.
#AUTH_SSO_ONLY=false
#AUTH_SSO_PROVIDERS=microsoft
```

- [ ] **Step 10: SETUP §3.8.** In `docs/SETUP.md`, replace the paragraph that starts `**The stock \`docker-compose.yml\` does not pass auth-service's SSO variables.**` through the line ending `docker-compose.override.yml …\`.` with:

```markdown
`docker-compose.yml` passes the Microsoft settings (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_ALLOWED_TENANTS`) and the SSO-only settings (`AUTH_SSO_ONLY`, `AUTH_SSO_PROVIDERS`) from `.env`
to auth-service. Google's `GOOGLE_CLIENT_ID` still needs a `docker-compose.override.yml` next to it
(Compose merges it automatically when you run `docker compose` without `-f`):

```yaml
# docker-compose.override.yml (local file)
services:
  auth-service:
    environment:
      GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID:-}
```
In production, add it explicitly:
`docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml -f docker-compose.override.yml …`.
```

and in the "Common problems (section 3)" table change the 503 row's fix to: `The dashboard has the \`VITE_*\` id but auth-service does not. Set \`AZURE_CLIENT_ID\`/\`AZURE_ALLOWED_TENANTS\` in \`.env\` (Microsoft) or add the override file above (Google), then recreate auth-service.` and add a row:

```markdown
| auth-service exits at start with "AUTH_SSO_ONLY=true but …" | A provider in `AUTH_SSO_PROVIDERS` is not configured or not valid (`microsoft`, `google`). The log names the missing setting. |
```

- [ ] **Step 11: auth-service README.** In `platforms/auth-service/auth-service/README.md`, under `### SSO Provider Configuration`, after the `AZURE_ALLOWED_TENANTS` bullet, add:

```markdown
- `AUTH_SSO_ONLY`: SSO-only mode (default `false`, ADR-031). People sign in only with the providers below; active superusers keep password sign-in (break-glass, MFA still applies).
- `AUTH_SSO_PROVIDERS`: comma-separated providers allowed in the mode (default `microsoft`; valid: `microsoft`, `google`). With the mode on, start-up stops when a listed provider is unknown or not configured, and logs the missing setting's name. With the mode on and no active superuser, start-up logs a WARNING.
```

- [ ] **Step 12: ADR-031.** Create `docs/architecture/adr/ADR-031-sso-only-mode.md`:

```markdown
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
```

Append to the Accepted table in `docs/architecture/adr/INDEX.md`, after the ADR-030 row:

```markdown
| [ADR-031](ADR-031-sso-only-mode.md) | SSO-only mode: `AUTH_SSO_ONLY` turns password registration, recovery and sign-in off except for active superusers (break-glass, logged); non-superuser sessions revoked once per off-to-on change; readiness and a one-time, 7-day Microsoft link allowance; switched in `.env`, never from the dashboard |
```

- [ ] **Step 13: Run the full auth-service suite and the docs check**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` (from the service dir) — Expected: all PASS.
Run: `python scripts/check_architecture_docs.py` (repo root) — Expected: exit 0, no findings.

- [ ] **Step 14: Commit**

```bash
git add platforms/auth-service/auth-service/src/auth/config.py platforms/auth-service/auth-service/src/auth/service/auth_mode.py platforms/auth-service/auth-service/src/auth/api/main.py platforms/auth-service/auth-service/tests/conftest.py platforms/auth-service/auth-service/tests/unit/test_auth_mode.py docker-compose.yml .env.example docs/SETUP.md platforms/auth-service/auth-service/README.md docs/architecture/adr/ADR-031-sso-only-mode.md docs/architecture/adr/INDEX.md
git commit -o platforms/auth-service/auth-service/src/auth/config.py platforms/auth-service/auth-service/src/auth/service/auth_mode.py platforms/auth-service/auth-service/src/auth/api/main.py platforms/auth-service/auth-service/tests/conftest.py platforms/auth-service/auth-service/tests/unit/test_auth_mode.py docker-compose.yml .env.example docs/SETUP.md platforms/auth-service/auth-service/README.md docs/architecture/adr/ADR-031-sso-only-mode.md docs/architecture/adr/INDEX.md -m "feat(auth): SSO-only mode settings and start-up check (ADR-031)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `GET /api/v1/auth/methods`

**Files:**
- Modify: `platforms/auth-service/auth-service/src/auth/schemas/auth.py` (new `AuthMethods`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py` (new route)
- Create: `platforms/auth-service/auth-service/tests/integration/test_sso_only.py`
- Modify: `scripts/smoke_gateway.sh`, `platforms/auth-service/auth-service/README.md`, `TECHNICAL_SPECIFICATION.md`

**Interfaces:**
- Consumes: `available_providers()` from Task 1; fixtures `sso_only`, `client`.
- Produces: `GET /api/v1/auth/methods` → `{"password": bool, "providers": list[str]}`; schema `src.auth.schemas.auth.AuthMethods`. The dashboard (Task 8) relies on this exact shape.

- [ ] **Step 1: Write the failing tests** — create `tests/integration/test_sso_only.py`:

```python
"""SSO-only mode (ADR-031) at the HTTP boundary."""
import pytest

from src.auth.config import settings

METHODS = "/api/v1/auth/methods"
PASSWORD = "securepassword123"
SSO_ONLY_BODY = {"detail": {"code": "sso_only", "message": "Sign-in is through Microsoft only."}}


@pytest.fixture
def no_providers(monkeypatch):
    for name in ("AZURE_CLIENT_ID", "AZURE_ALLOWED_TENANTS", "AZURE_TENANT_ID", "GOOGLE_CLIENT_ID"):
        monkeypatch.setattr(settings, name, "")


def test_methods_on_a_stack_without_sso(client, no_providers):
    response = client.get(METHODS)
    assert response.status_code == 200
    assert response.json() == {"password": True, "providers": []}


def test_methods_lists_the_configured_providers(client, no_providers, monkeypatch):
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "google-client")
    assert client.get(METHODS).json() == {"password": True, "providers": ["microsoft", "google"]}


def test_methods_in_sso_only_mode(client, sso_only, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "google-client")  # configured, but not listed
    assert client.get(METHODS).json() == {"password": False, "providers": ["microsoft"]}


def test_methods_needs_no_token_and_ignores_a_bad_one(client, sso_only):
    response = client.get(METHODS, headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 200
    assert set(response.json()) == {"password", "providers"}  # nothing per-user, nothing secret
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_sso_only.py -q`
Expected: FAIL, `assert 404 == 200` / `405` (no route).

- [ ] **Step 3: Implement.** In `src/auth/schemas/auth.py` add (the file already imports `BaseModel`; add `List` to its `typing` import if absent):

```python
class AuthMethods(BaseModel):
    # GET /auth/methods (public, ADR-031). password is false in SSO-only mode: the superuser
    # break-glass is not advertised. providers: configured, limited to AUTH_SSO_PROVIDERS in the mode.
    password: bool
    providers: List[str]
```

In `src/auth/api/v1/endpoints/auth.py` add `AuthMethods` to the `src.auth.schemas.auth` import, add `from src.auth.service.auth_mode import available_providers`, and after `router = APIRouter()` add:

```python
@router.get("/methods", response_model=AuthMethods)
def auth_methods():
    """Public: how people sign in to this deployment (ADR-031). No secrets, no per-user data; the
    dashboard's login and recovery pages read it."""
    return AuthMethods(password=not settings.AUTH_SSO_ONLY, providers=available_providers())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_sso_only.py -q`
Expected: 4 PASS.

- [ ] **Step 5: Gateway smoke.** In `scripts/smoke_gateway.sh`, after the `check "/api/v1/sso/microsoft -> auth-service (not configured)" …` command (its continuation line ends `-d '{"credential":"not-a-token"}'`), add:

```bash
# Public: how people sign in (ADR-031). The default stack is not in SSO-only mode
check "/api/v1/auth/methods without a token -> auth-service" 200 GET "$BASE/api/v1/auth/methods"
body_has "/auth/methods offers password sign-in on the default stack" '"password":true'
```

Check: `bash -n scripts/smoke_gateway.sh` exits 0. (The full smoke runs in CI's container job; locally only with the stack up: `bash scripts/smoke_gateway.sh`.)

- [ ] **Step 6: Docs.** auth-service README, `### Authentication` list, first bullet:

```markdown
- `GET /api/v1/auth/methods` - Public. `{"password": true|false, "providers": [...]}`: `password` is `false` in SSO-only mode (the superuser break-glass is not advertised); `providers` lists the configured providers (`microsoft`, `google`), limited to `AUTH_SSO_PROVIDERS` in the mode. No per-user data. The dashboard's sign-in and recovery pages read it (ADR-031).
```

`TECHNICAL_SPECIFICATION.md`, after the `- SSO: /sso/google, /sso/microsoft …` bullet (ends `provider to an existing account.`), add:

```markdown
- SSO-only mode (ADR-031): `AUTH_SSO_ONLY`, `AUTH_SSO_PROVIDERS`. Public
  `GET /auth/methods` → `{password, providers}` tells the dashboard what to show.
```

- [ ] **Step 7: Full suite, then commit**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` — Expected: all PASS.

```bash
git add platforms/auth-service/auth-service/src/auth/schemas/auth.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py platforms/auth-service/auth-service/tests/integration/test_sso_only.py scripts/smoke_gateway.sh platforms/auth-service/auth-service/README.md TECHNICAL_SPECIFICATION.md
git commit -o platforms/auth-service/auth-service/src/auth/schemas/auth.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py platforms/auth-service/auth-service/tests/integration/test_sso_only.py scripts/smoke_gateway.sh platforms/auth-service/auth-service/README.md TECHNICAL_SPECIFICATION.md -m "feat(auth): public GET /auth/methods for the sign-in pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Route guards, superuser break-glass, MFA in the mode

**Files:**
- Modify: `platforms/auth-service/auth-service/src/auth/service/auth_mode.py` (403, client IP, break-glass log)
- Modify: `platforms/auth-service/auth-service/src/auth/api/deps.py` (two dependencies)
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py` (`register_user`, `verify_email`, `resend_verification`, `login_access_token`, `mfa_verify`, `initiate_password_reset`, `reset_password`, `change_password`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/sso.py` (`google_login`, `microsoft_login`, `github_login`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py` (`update_user_me`, `link_google_account`, `link_microsoft_account`)
- Test: `platforms/auth-service/auth-service/tests/integration/test_sso_only.py`
- Modify: `platforms/auth-service/auth-service/README.md`, `SECURITY.md`, `TECHNICAL_SPECIFICATION.md`

**Interfaces:**
- Consumes: `sso_only_providers()`, `PROVIDER_LABELS` (Task 1); fixtures `sso_only`, `make_user`, `auth_header`.
- Produces (in `src.auth.service.auth_mode`): `sso_only_detail() -> dict`, `sso_only_error() -> HTTPException` (403), `client_ip(request: Request) -> Optional[str]`, `log_break_glass(user: User, ip: Optional[str]) -> None`.
- Produces (in `src.auth.api.deps`): `password_routes_enabled() -> None` (dependency), `sso_provider_allowed(provider: str) -> Callable[[], None]` (dependency factory).

- [ ] **Step 1: Write the failing tests** — append to `tests/integration/test_sso_only.py` (add these imports at the top of the file: `import logging`, `import pyotp`, `from src.auth.models.pending_registration import PendingRegistration`, `from src.auth.service import mfa_service`):

```python
LOGIN = "/api/v1/auth/login"
MFA_VERIFY = "/api/v1/auth/mfa/verify"
CHANGE = "/api/v1/auth/change-password"
MODE_LOGGER = "src.auth.service.auth_mode"


@pytest.mark.parametrize("method, path, body", [
    ("post", "/api/v1/auth/register", {"email": "new@example.com", "password": PASSWORD}),
    ("post", "/api/v1/auth/forgot-password", {"email": "ann@example.com"}),
    ("post", "/api/v1/auth/reset-password", {"token": "some-token", "password": PASSWORD}),
    ("post", "/api/v1/auth/resend-verification", {"email": "ann@example.com"}),
    ("get", "/api/v1/auth/verify-email?token=some-token", None),
])
def test_registration_verification_and_recovery_are_refused(client, db, sso_only, method, path, body):
    response = client.post(path, json=body) if method == "post" else client.get(path)
    assert response.status_code == 403
    assert response.json() == SSO_ONLY_BODY
    assert db.query(PendingRegistration).count() == 0


def _answer(response):
    return response.status_code, response.json(), response.headers.get("www-authenticate")


def test_a_login_refusal_never_tells_who_is_a_superuser(client, sso_only, make_user):
    make_user("ann@example.com")
    make_user("root@example.com", superuser=True)
    make_user("gone@example.com", superuser=True, active=False)
    make_user("sso@example.com", password=None)

    def login(email, password):
        return _answer(client.post(LOGIN, json={"email": email, "password": password}))

    answers = {
        "ordinary account, right password": login("ann@example.com", PASSWORD),
        "ordinary account, wrong password": login("ann@example.com", "wrong-password-1"),
        "superuser, wrong password": login("root@example.com", "wrong-password-1"),
        "inactive superuser, right password": login("gone@example.com", PASSWORD),
        "passwordless account": login("sso@example.com", PASSWORD),
        "unknown address": login("nobody@example.com", PASSWORD),
    }
    assert answers == dict.fromkeys(answers, (403, SSO_ONLY_BODY, None))


def test_a_superuser_signs_in_with_a_password_and_it_is_logged(client, sso_only, make_user, caplog):
    root = make_user("root@example.com", superuser=True)
    with caplog.at_level(logging.WARNING, logger=MODE_LOGGER):
        response = client.post(LOGIN, json={"email": "root@example.com", "password": PASSWORD},
                               headers={"X-Forwarded-For": "203.0.113.7"})
    assert response.status_code == 200, response.text
    tokens = response.json()
    assert tokens["access_token"] and tokens["refresh_token"]
    lines = [r.getMessage() for r in caplog.records
             if r.levelno == logging.WARNING and "break-glass sign-in" in r.getMessage()]
    assert len(lines) == 1
    assert f"user_id={root.id}" in lines[0] and "email=root@example.com" in lines[0]
    assert "ip=203.0.113.7" in lines[0] and "at=" in lines[0]
    # No secret in the log
    assert PASSWORD not in caplog.text
    assert tokens["access_token"] not in caplog.text and tokens["refresh_token"] not in caplog.text


def test_no_break_glass_line_outside_the_mode(client, make_user, caplog):
    make_user("root@example.com", superuser=True)
    with caplog.at_level(logging.WARNING, logger=MODE_LOGGER):
        assert client.post(LOGIN, json={"email": "root@example.com", "password": PASSWORD}).status_code == 200
    assert "break-glass" not in caplog.text


def _enable_mfa(db, user):
    secret, _ = mfa_service.start_enrollment(db, user)
    recovery = mfa_service.confirm_enrollment(db, user, pyotp.TOTP(secret).now())
    assert recovery
    return recovery


def test_a_superuser_with_mfa_still_gives_the_code(client, db, sso_only, make_user, caplog):
    root = make_user("root@example.com", superuser=True)
    recovery = _enable_mfa(db, root)
    challenge = client.post(LOGIN, json={"email": "root@example.com", "password": PASSWORD})
    assert challenge.status_code == 200 and challenge.json()["mfa_required"] is True
    assert "access_token" not in challenge.json()
    with caplog.at_level(logging.WARNING, logger=MODE_LOGGER):
        verified = client.post(MFA_VERIFY, json={"mfa_token": challenge.json()["mfa_token"], "code": recovery[0]})
    assert verified.status_code == 200, verified.text
    assert "break-glass sign-in" in caplog.text and f"user_id={root.id}" in caplog.text


def test_an_mfa_challenge_from_before_the_switch_lets_no_ordinary_user_in(client, db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    recovery = _enable_mfa(db, ann)
    challenge = client.post(LOGIN, json={"email": "ann@example.com", "password": PASSWORD})
    assert challenge.json()["mfa_required"] is True  # issued while the mode was off

    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    response = client.post(MFA_VERIFY, json={"mfa_token": challenge.json()["mfa_token"], "code": recovery[0]})
    assert response.status_code == 403
    assert response.json() == SSO_ONLY_BODY
    assert mfa_service.check_code(db, ann, recovery[0])  # the recovery code was not spent by the refusal


def test_change_password_is_for_superusers_only(client, sso_only, make_user, auth_header):
    ann = make_user("ann@example.com")
    root = make_user("root@example.com", superuser=True)
    body = {"current_password": PASSWORD, "new_password": "another-password-9"}
    refused = client.post(CHANGE, json=body, headers=auth_header(ann))
    assert refused.status_code == 403 and refused.json() == SSO_ONLY_BODY
    assert client.post(CHANGE, json=body, headers=auth_header(root)).status_code == 200


def test_a_password_cannot_be_set_through_the_profile_either(client, sso_only, make_user, auth_header):
    ann = make_user("ann@example.com")
    refused = client.put("/api/v1/users/me", json={"password": "another-password-9", "current_password": PASSWORD},
                         headers=auth_header(ann))
    assert refused.status_code == 403 and refused.json() == SSO_ONLY_BODY
    assert client.put("/api/v1/users/me", json={"full_name": "Ann"}, headers=auth_header(ann)).status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/sso/google", "/api/v1/sso/github", "/api/v1/users/me/link/google"])
def test_providers_the_mode_does_not_list_are_refused(client, sso_only, make_user, auth_header, path):
    ann = make_user("ann@example.com")
    response = client.post(path, json={"credential": "x"}, headers=auth_header(ann))
    assert response.status_code == 403
    assert response.json() == SSO_ONLY_BODY


def test_microsoft_is_not_refused_when_listed(client, sso_only):
    response = client.post("/api/v1/sso/microsoft", json={"credential": "not-a-token"})
    assert response.status_code == 400  # reached token verification
    assert response.json() == {"detail": "Invalid Microsoft token"}


def test_the_message_names_the_listed_providers(client, sso_only, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft,google")
    response = client.post("/api/v1/auth/register", json={"email": "new@example.com", "password": PASSWORD})
    assert response.json() == {"detail": {"code": "sso_only", "message": "Sign-in is through Microsoft or Google only."}}


def test_microsoft_is_refused_when_only_google_is_listed(client, sso_only, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "google")
    response = client.post("/api/v1/sso/microsoft", json={"credential": "x"})
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "sso_only", "message": "Sign-in is through Google only."}}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_sso_only.py -q`
Expected: the new tests FAIL (register answers 202, login answers 200/401, …); Task 2's four still PASS.

- [ ] **Step 3: The 403, client IP and break-glass log.** Append to `src/auth/service/auth_mode.py`, and extend its imports to:

```python
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from src.auth.config import settings
from src.auth.models.user import User
```

```python
def sso_only_detail() -> dict:
    """The one body every refusal in the mode carries; the names come from AUTH_SSO_PROVIDERS."""
    names = " or ".join(PROVIDER_LABELS[name] for name in sso_only_providers()) or "single sign-on"
    return {"code": "sso_only", "message": f"Sign-in is through {names} only."}


def sso_only_error() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=sso_only_detail())


def client_ip(request: Request) -> Optional[str]:
    """The caller's address. The gateway overwrites X-Forwarded-For with the address it saw
    (gateway/nginx.conf.template), so its first entry is trusted; without it, the socket peer."""
    first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else None


def log_break_glass(user: User, ip: Optional[str]) -> None:
    """Every password sign-in that succeeds in SSO-only mode. Identity and where from, never a secret."""
    logger.warning(
        "break-glass sign-in: user_id=%s email=%s ip=%s at=%s",
        user.id, user.email, ip or "unknown", datetime.now(timezone.utc).isoformat(),
    )
```

- [ ] **Step 4: The dependencies.** In `src/auth/api/deps.py` add the import `from src.auth.service.auth_mode import sso_only_error, sso_only_providers` and append:

```python
def password_routes_enabled() -> None:
    """Registration, email verification and password recovery are off in SSO-only mode (ADR-031)."""
    if settings.AUTH_SSO_ONLY:
        raise sso_only_error()


def sso_provider_allowed(provider: str):
    """A provider's sign-in and link routes answer the SSO-only 403 when the mode does not list it."""
    def _check() -> None:
        if settings.AUTH_SSO_ONLY and provider not in sso_only_providers():
            raise sso_only_error()
    return _check
```

- [ ] **Step 5: Guard the routes in `endpoints/auth.py`.** Add `from src.auth.service.auth_mode import client_ip, log_break_glass, sso_only_error` (merge with the Task 2 import). Then:

1. Add `dependencies=[Depends(deps.password_routes_enabled)]` to the decorators of `register_user` (`@router.post("/register", status_code=status.HTTP_202_ACCEPTED, dependencies=[...])`), `verify_email` (`@router.get("/verify-email", response_model=Token, dependencies=[...])`), `resend_verification`, `initiate_password_reset` and `reset_password`.

2. Replace `login_access_token` with:

```python
@router.post("/login", response_model=None)
def login_access_token(
    *,
    db: Session = Depends(deps.get_db),
    http_request: Request,
    response: Response,
    form_data: LoginRequest
):
    """
    Token login. With MFA enabled the response is a five-minute challenge
    instead of a session: {"mfa_required": true, "mfa_token": ...}.

    SSO-only mode (ADR-031): the password is checked first, as always; then only an active superuser
    goes on. Everyone else gets the same 403 whether the password was right or wrong, so the answer
    tells nobody who is a superuser or which passwords are valid.
    """
    user = AuthService.authenticate_user(db, form_data.email, form_data.password)
    if settings.AUTH_SSO_ONLY and not (user and user.is_active and user.is_superuser):
        raise sso_only_error()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    if user.mfa_enabled:
        return {"mfa_required": True, "mfa_token": mfa_service.create_mfa_token(user)}
    if settings.AUTH_SSO_ONLY:
        log_break_glass(user, client_ip(http_request))
    return _issue_tokens(db, user, response)
```

3. Replace `mfa_verify` with:

```python
@router.post("/mfa/verify", response_model=Token)
def mfa_verify(
    *,
    db: Session = Depends(deps.get_db),
    http_request: Request,
    response: Response,
    request: MfaVerifyRequest
):
    """Complete an MFA login: challenge token plus a TOTP or recovery code."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid MFA token or code",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user_id = mfa_service.verify_mfa_token(request.mfa_token)
    if user_id is None:
        raise invalid
    user = UserService.get_user_by_id(db, user_id)
    if not user or not user.is_active or not user.mfa_enabled:
        raise invalid
    if settings.AUTH_SSO_ONLY and not user.is_superuser:
        # A challenge issued just before the switch (it lives five minutes) must not finish an
        # ordinary password sign-in; refused before the code is checked, so no recovery code is spent
        raise sso_only_error()
    if not mfa_service.check_code(db, user, request.code):
        raise invalid
    if settings.AUTH_SSO_ONLY:
        log_break_glass(user, client_ip(http_request))
    return _issue_tokens(db, user, response)
```

4. In `change_password`, insert as the first statement of the body:

```python
    if settings.AUTH_SSO_ONLY and not current_user.is_superuser:
        raise sso_only_error()
```

- [ ] **Step 6: Guard `sso.py`.** Change the three decorators to:

```python
@router.post("/google", response_model=Token, dependencies=[Depends(deps.sso_provider_allowed("google"))])
```
```python
@router.post("/microsoft", response_model=Token, dependencies=[Depends(deps.sso_provider_allowed("microsoft"))])
```
```python
# GitHub is never a valid SSO-only provider, so the mode answers its 403 before the 501
@router.post("/github", response_model=Token, dependencies=[Depends(deps.sso_provider_allowed("github"))])
```

- [ ] **Step 7: Guard `users.py`.** Add `from src.auth.service.auth_mode import sso_only_error`. In `update_user_me`, directly after `changing_password = user_in.password is not None`, insert:

```python
    if changing_password and settings.AUTH_SSO_ONLY and not current_user.is_superuser:
        # The same rule as /auth/change-password in SSO-only mode (ADR-031)
        raise sso_only_error()
```

and change the two link decorators to:

```python
@router.post("/me/link/google", response_model=User, dependencies=[Depends(deps.sso_provider_allowed("google"))])
```
```python
@router.post("/me/link/microsoft", response_model=User, dependencies=[Depends(deps.sso_provider_allowed("microsoft"))])
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_sso_only.py -q`
Expected: all PASS.

- [ ] **Step 9: Docs.** auth-service README, after the `### SSO Authentication` list, add a section:

```markdown
### SSO-only mode (ADR-031)
With `AUTH_SSO_ONLY=true`, every refusal answers `403 {"detail": {"code": "sso_only", "message": "Sign-in is through Microsoft only."}}` (the names come from `AUTH_SSO_PROVIDERS`):
- `POST /auth/register`, `GET /auth/verify-email`, `POST /auth/resend-verification`, `POST /auth/forgot-password`, `POST /auth/reset-password`: always.
- `POST /auth/login`: the password is checked first; an active superuser goes on (MFA still asks for its code); everyone else gets the same 403, right or wrong password, so the answer reveals neither superuser status nor password validity. Each successful password sign-in is logged at WARNING: `break-glass sign-in: user_id=… email=… ip=… at=…`.
- `POST /auth/mfa/verify`: refuses a non-superuser's challenge (one issued just before the switch) without spending its code.
- `POST /auth/change-password` and a password in `PUT /users/me`: superusers only.
- `/sso/{provider}` and `/users/me/link/{provider}` for a provider not in `AUTH_SSO_PROVIDERS` (GitHub always).
```

`SECURITY.md`, in "What the platform does today", after the `- **SSO.** …` bullet, add:

```markdown
- **SSO-only mode (ADR-031).** `AUTH_SSO_ONLY=true` turns off registration,
  email verification, password recovery and password sign-in for everyone but
  active superusers (break-glass; MFA still applies). A refused password
  sign-in answers the same 403 whether the password was right or wrong, so it
  reveals neither superuser status nor password validity. Every break-glass
  sign-in is logged at WARNING with user id, email, IP and time; no password,
  token or client id is ever logged. auth-service refuses to start when a
  provider the mode lists is not configured.
```

`TECHNICAL_SPECIFICATION.md`, extend the Task 2 bullet with:

```markdown
  In the mode, registration, verification and recovery answer 403
  `{"detail": {"code": "sso_only", ...}}`; `/auth/login` lets only active
  superusers through (same 403 for every other case, MFA kept, logged as
  break-glass); unlisted providers answer the same 403.
```

- [ ] **Step 10: Full suite, then commit**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` — Expected: all PASS (normal-mode tests unchanged).

```bash
git add platforms/auth-service/auth-service/src/auth/service/auth_mode.py platforms/auth-service/auth-service/src/auth/api/deps.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/sso.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py platforms/auth-service/auth-service/tests/integration/test_sso_only.py platforms/auth-service/auth-service/README.md SECURITY.md TECHNICAL_SPECIFICATION.md
git commit -o platforms/auth-service/auth-service/src/auth/service/auth_mode.py platforms/auth-service/auth-service/src/auth/api/deps.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/sso.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py platforms/auth-service/auth-service/tests/integration/test_sso_only.py platforms/auth-service/auth-service/README.md SECURITY.md TECHNICAL_SPECIFICATION.md -m "feat(auth): SSO-only route guards and superuser break-glass sign-in" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Migration 008 and session revocation when the mode turns on

**Files:**
- Create: `platforms/auth-service/auth-service/alembic/versions/008_sso_only_mode.py`
- Create: `platforms/auth-service/auth-service/src/auth/models/auth_mode.py`
- Modify: `platforms/auth-service/auth-service/src/auth/models/user.py` (column `microsoft_link_allowed_until`)
- Modify: `platforms/auth-service/auth-service/src/auth/service/auth_mode.py` (`apply_auth_mode`, `_state_select`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/main.py` (`_apply_auth_mode` calls it)
- Modify: `platforms/auth-service/auth-service/tests/conftest.py` (`client` points the start-up hooks at the test database)
- Test: `platforms/auth-service/auth-service/tests/unit/test_auth_mode.py`, `tests/unit/test_alembic_env.py`
- Modify: `platforms/auth-service/auth-service/README.md`, `SECURITY.md`

**Interfaces:**
- Consumes: Task 1's module and hook.
- Produces: `src.auth.models.auth_mode.AuthModeState` (`id` int PK = 1, `sso_only` bool, `applied_at` datetime tz), `STATE_ROW_ID = 1`; `User.microsoft_link_allowed_until: DateTime(timezone=True), nullable` (Tasks 6, 7); `apply_auth_mode(db: Session) -> int` (sessions revoked); `_state_select()` (the locked select).

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_auth_mode.py` (add imports `from sqlalchemy.dialects import postgresql`, `from src.auth.models.auth_mode import AuthModeState`, `from src.auth.service.auth_mode import apply_auth_mode, _state_select`, `from src.auth.service.auth_service import AuthService`):

```python
def _revoked(db, session_row):
    db.refresh(session_row)
    return bool(session_row.is_revoked)


def test_turning_the_mode_on_revokes_every_non_superuser_session(db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    root = make_user("root@example.com", superuser=True)
    ann_a, ann_b = AuthService.create_user_session(db, ann), AuthService.create_user_session(db, ann)
    root_s = AuthService.create_user_session(db, root)
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)

    assert apply_auth_mode(db) == 2
    assert _revoked(db, ann_a) and _revoked(db, ann_b)
    assert not _revoked(db, root_s)
    state = db.get(AuthModeState, 1)
    assert state.sso_only is True and state.applied_at is not None


def test_a_restart_with_the_mode_on_revokes_nothing(db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    apply_auth_mode(db)
    after_switch = AuthService.create_user_session(db, ann)  # e.g. a Microsoft sign-in after the switch

    assert apply_auth_mode(db) == 0
    assert not _revoked(db, after_switch)


def test_off_then_on_again_revokes_again(db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    apply_auth_mode(db)
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    assert apply_auth_mode(db) == 0
    assert db.get(AuthModeState, 1).sso_only is False
    second = AuthService.create_user_session(db, ann)

    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    assert apply_auth_mode(db) == 1
    assert _revoked(db, second)


def test_the_mode_off_records_false_and_revokes_nothing(db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    kept = AuthService.create_user_session(db, ann)
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    assert apply_auth_mode(db) == 0
    assert db.get(AuthModeState, 1).sso_only is False
    assert not _revoked(db, kept)


def test_a_null_superuser_flag_is_not_a_superuser(db, make_user, monkeypatch):
    odd = make_user("odd@example.com")
    odd.is_superuser = None
    db.commit()
    session_row = AuthService.create_user_session(db, odd)
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    assert apply_auth_mode(db) == 1
    assert _revoked(db, session_row)


def test_the_state_row_is_read_with_a_row_lock():
    # SQLite drops FOR UPDATE, so the lock that keeps two starting processes from revoking twice is
    # pinned on the PostgreSQL rendering of the very query apply_auth_mode runs
    sql = str(_state_select().compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "auth_mode_state" in sql


def test_the_start_up_hook_records_the_mode(client, db):
    # The client fixture started the app: its hook ran against this run's database
    assert db.get(AuthModeState, 1).sso_only is False
```

Append to `tests/unit/test_alembic_env.py`:

```python
def test_migration_008_adds_the_mode_state_and_the_link_allowance(monkeypatch, capsys):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://svc:pw@dbhost:5432/auth_db")
    cfg = _config()
    cfg.set_main_option("sqlalchemy.url", "")

    command.upgrade(cfg, "007:008", sql=True)
    up = capsys.readouterr().out
    assert "CREATE TABLE auth_mode_state" in up
    assert "ADD COLUMN microsoft_link_allowed_until" in up
    assert "INSERT INTO auth_mode_state (id, sso_only) VALUES (1, false)" in up

    command.downgrade(cfg, "008:007", sql=True)
    down = capsys.readouterr().out
    assert "DROP TABLE auth_mode_state" in down
    assert "DROP COLUMN microsoft_link_allowed_until" in down
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_auth_mode.py tests/unit/test_alembic_env.py -q`
Expected: `test_auth_mode.py` errors at collection with `No module named 'src.auth.models.auth_mode'`; `test_alembic_env.py::test_migration_008_adds_the_mode_state_and_the_link_allowance` FAILS with `Can't locate revision identified by '008'`.

- [ ] **Step 3: The migration.** Create `alembic/versions/008_sso_only_mode.py`:

```python
"""SSO-only mode: the last applied mode, and the one-time Microsoft link allowance (ADR-031)

Revision ID: 008
Revises: 007
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("microsoft_link_allowed_until", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "auth_mode_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("sso_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_auth_mode_state_single_row"),
    )
    # Seeded so the start-up's SELECT ... FOR UPDATE always has a row to lock
    op.execute("INSERT INTO auth_mode_state (id, sso_only) VALUES (1, false)")


def downgrade() -> None:
    op.drop_table("auth_mode_state")
    op.drop_column("users", "microsoft_link_allowed_until")
```

- [ ] **Step 4: The models.** Create `src/auth/models/auth_mode.py`:

```python
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, text

from src.auth.db.base import Base

STATE_ROW_ID = 1


class AuthModeState(Base):
    """The SSO-only mode last applied at start-up (ADR-031). One row, id 1 (migration 008 seeds it)."""
    __tablename__ = "auth_mode_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_auth_mode_state_single_row"),)

    id = Column(Integer, primary_key=True, autoincrement=False)
    sso_only = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    applied_at = Column(DateTime(timezone=True), nullable=True)
```

In `src/auth/models/user.py`, after `mfa_enabled`, add:

```python
    # SSO-only mode (ADR-031): a superuser let this account link a Microsoft identity at its next
    # Microsoft sign-in, until this time. Cleared when used.
    microsoft_link_allowed_until = Column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 5: The revocation.** In `src/auth/service/auth_mode.py` extend the imports with:

```python
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.auth.models.auth_mode import STATE_ROW_ID, AuthModeState
from src.auth.models.session import RefreshToken
```

and append:

```python
def _state_select():
    return select(AuthModeState).where(AuthModeState.id == STATE_ROW_ID).with_for_update()


def apply_auth_mode(db: Session) -> int:
    """Record the mode; on an off-to-on change, revoke every refresh session of every user who is not a
    superuser. One transaction holding the state row's lock, so two processes starting together revoke
    once and a restart with the mode already on revokes nothing. Returns the number of sessions revoked."""
    wanted = bool(settings.AUTH_SSO_ONLY)
    state = db.execute(_state_select()).scalar_one_or_none()
    if state is None:
        # Only a database migrated without 008's seed row (the test schema is built from the models)
        state = AuthModeState(id=STATE_ROW_ID, sso_only=False)
        db.add(state)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()  # another process inserted it first: wait for its lock and read its result
            state = db.execute(_state_select()).scalar_one()

    revoked = 0
    if wanted and not state.sso_only:
        not_superusers = select(User.id).where(User.is_superuser.isnot(True))
        revoked = db.query(RefreshToken).filter(
            RefreshToken.is_revoked == False,  # noqa: E712
            RefreshToken.user_id.in_(not_superusers),
        ).update({RefreshToken.is_revoked: True}, synchronize_session=False)
        logger.warning("SSO-only mode turned on: revoked %d sessions of users who are not superusers", revoked)
    if state.sso_only != wanted:
        state.sso_only = wanted
        state.applied_at = datetime.now(timezone.utc)
    db.commit()
    return revoked
```

- [ ] **Step 6: Call it at start-up.** In `src/auth/api/main.py` import `apply_auth_mode` with the other two and make the hook body:

```python
    check_sso_only_settings()
    db = SessionLocal()
    try:
        apply_auth_mode(db)
        warn_if_no_break_glass(db)
    finally:
        db.close()
```

- [ ] **Step 7: Point the start-up hooks at the test database.** The hook now reads and writes `auth_mode_state` on every start, and `TestClient` runs start-up hooks, so without this every `client` test would try the real PostgreSQL. In `tests/conftest.py` replace the `client` fixture with:

```python
@pytest.fixture(scope="function")
def client(db, monkeypatch):
    def override_get_db():
        try:
            yield db
        finally:
            db.close()

    # The start-up hooks open their own session (SessionLocal: the configured PostgreSQL). Since ADR-031
    # one of them reads and writes auth_mode_state on every start, so point them at this run's SQLite file.
    import src.auth.api.main as api_main
    monkeypatch.setattr(api_main, "SessionLocal", TestingSessionLocal)

    app.dependency_overrides[get_db] = override_get_db
    # https base URL so the client's cookie jar accepts the Secure refresh cookie
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_auth_mode.py tests/unit/test_alembic_env.py -q`
Expected: all PASS.

- [ ] **Step 9: Docs.** auth-service README, at the end of the `### SSO-only mode (ADR-031)` section from Task 3, add:

```markdown
Sessions: the table `auth_mode_state` (migration 008, one row) records the mode last applied. At start-up, when `AUTH_SSO_ONLY=true` and the stored value is `false`, auth-service revokes every refresh session of every user who is not a superuser, then stores `true`, in one transaction that locks the row (`SELECT … FOR UPDATE`): each off-to-on change revokes once, restarts do not. Access tokens already issued work until they expire (at most `ACCESS_TOKEN_EXPIRE_MINUTES`); the next refresh is refused.
```

`SECURITY.md`, extend the SSO-only bullet with: `Turning the mode on ends every refresh session of every non-superuser once (access tokens expire within 60 minutes).`

- [ ] **Step 10: Full suite, then commit**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` — Expected: all PASS.

```bash
git add platforms/auth-service/auth-service/alembic/versions/008_sso_only_mode.py platforms/auth-service/auth-service/src/auth/models/auth_mode.py platforms/auth-service/auth-service/src/auth/models/user.py platforms/auth-service/auth-service/src/auth/service/auth_mode.py platforms/auth-service/auth-service/src/auth/api/main.py platforms/auth-service/auth-service/tests/conftest.py platforms/auth-service/auth-service/tests/unit/test_auth_mode.py platforms/auth-service/auth-service/tests/unit/test_alembic_env.py platforms/auth-service/auth-service/README.md SECURITY.md
git commit -o platforms/auth-service/auth-service/alembic/versions/008_sso_only_mode.py platforms/auth-service/auth-service/src/auth/models/auth_mode.py platforms/auth-service/auth-service/src/auth/models/user.py platforms/auth-service/auth-service/src/auth/service/auth_mode.py platforms/auth-service/auth-service/src/auth/api/main.py platforms/auth-service/auth-service/tests/conftest.py platforms/auth-service/auth-service/tests/unit/test_auth_mode.py platforms/auth-service/auth-service/tests/unit/test_alembic_env.py platforms/auth-service/auth-service/README.md SECURITY.md -m "feat(auth): migration 008; revoke non-superuser sessions once when SSO-only mode turns on" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `GET /users/me` carries `linked_providers`, `sso_only`, `has_password`

**Files:**
- Modify: `platforms/auth-service/auth-service/src/auth/schemas/user.py` (`UserMe`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py` (`read_user_me`)
- Test: `platforms/auth-service/auth-service/tests/integration/test_sso_only.py`
- Modify: `platforms/auth-service/auth-service/README.md`

**Interfaces:**
- Produces: `UserMe.linked_providers: List[str]` (sorted, distinct `OAuthAccount.provider` values), `UserMe.sso_only: bool` (= `AUTH_SSO_ONLY`), `UserMe.has_password: bool`. The dashboard's `Me` type (Task 10) mirrors these. `has_password` is not in the spec's §3.6 list; it lets the Security page ask for the current password only when `/users/me/link/microsoft` will require it (spec §4.2), without a second request.

- [ ] **Step 1: Write the failing tests** — append to `tests/integration/test_sso_only.py` (add `from src.auth.models.oauth import OAuthAccount` to the imports):

```python
ME = "/api/v1/users/me"


def test_users_me_reports_links_the_mode_and_the_password(client, db, make_user, auth_header, monkeypatch):
    ann = make_user("ann@example.com")
    db.add_all([
        OAuthAccount(user_id=ann.id, provider="microsoft", provider_user_id="tenant:oid"),
        OAuthAccount(user_id=ann.id, provider="google", provider_user_id="g-1"),
    ])
    db.commit()

    me = client.get(ME, headers=auth_header(ann)).json()
    assert me["linked_providers"] == ["google", "microsoft"]
    assert me["sso_only"] is False and me["has_password"] is True

    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    assert client.get(ME, headers=auth_header(ann)).json()["sso_only"] is True


def test_users_me_for_a_passwordless_unlinked_account(client, make_user, auth_header):
    bob = make_user("bob@example.com", password=None)
    me = client.get(ME, headers=auth_header(bob)).json()
    assert me["linked_providers"] == [] and me["has_password"] is False
    assert "hashed_password" not in me
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_sso_only.py -q -k users_me`
Expected: FAIL with `KeyError: 'linked_providers'`.

- [ ] **Step 3: Implement.** In `src/auth/schemas/user.py`, extend `UserMe`:

```python
class UserMe(User):
    # GET /users/me only: "/grafana/" for a superuser while MONITORING_ENABLED, else null (ADR-027).
    # The dashboard shows its Monitoring item only when this is set.
    monitoring_url: Optional[str] = None
    # SSO-only mode (ADR-031): the Security page's Microsoft card and Password card read these
    linked_providers: List[str] = []
    sso_only: bool = False
    has_password: bool = False
```

In `endpoints/users.py`, replace `read_user_me` with:

```python
@router.get("/me", response_model=UserMe)
def read_user_me(
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """
    Get current user. `monitoring_url` is set only for a superuser while monitoring is on (ADR-027);
    `linked_providers`, `sso_only` and `has_password` drive the Security page (ADR-031).
    get_current_active_user has already refused an inactive user.
    """
    me = User.model_validate(current_user, from_attributes=True)
    offered = settings.MONITORING_ENABLED and current_user.is_superuser
    providers = sorted({row.provider for row in db.query(OAuthAccount.provider).filter(
        OAuthAccount.user_id == current_user.id)})
    return UserMe(
        **me.model_dump(),
        monitoring_url=MONITORING_URL if offered else None,
        linked_providers=providers,
        sso_only=settings.AUTH_SSO_ONLY,
        has_password=current_user.hashed_password is not None,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_sso_only.py tests/integration/test_mfa.py -q`
Expected: all PASS (`test_mfa.py` covers the existing `/users/me` fields).

- [ ] **Step 5: Docs.** auth-service README, the `GET /api/v1/users/me` bullet, append: ``Also `linked_providers` (sorted provider names linked to the account), `sso_only` (the mode) and `has_password` (whether linking needs `current_password`), for the Security page (ADR-031).``

- [ ] **Step 6: Full suite, then commit**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` — Expected: all PASS.

```bash
git add platforms/auth-service/auth-service/src/auth/schemas/user.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py platforms/auth-service/auth-service/tests/integration/test_sso_only.py platforms/auth-service/auth-service/README.md
git commit -o platforms/auth-service/auth-service/src/auth/schemas/user.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py platforms/auth-service/auth-service/tests/integration/test_sso_only.py platforms/auth-service/auth-service/README.md -m "feat(auth): /users/me reports linked providers, the SSO-only mode and whether a password exists" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Readiness and the one-time link allowance (superusers)

**Files:**
- Create: `platforms/auth-service/auth-service/src/auth/service/sso_readiness.py`
- Modify: `platforms/auth-service/auth-service/src/auth/schemas/user.py` (`SsoReadinessEntry`, `SsoReadiness`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py` (two routes, **above** `read_user_by_id`)
- Test: `platforms/auth-service/auth-service/tests/integration/test_sso_only.py`
- Modify: `platforms/auth-service/auth-service/README.md`

**Interfaces:**
- Consumes: `User.microsoft_link_allowed_until` (Task 4); `deps.get_current_active_superuser`.
- Produces (in `src.auth.service.sso_readiness`): `MICROSOFT_LINK_ALLOWANCE_DAYS = 7`, `valid_allowance(user: User, now: Optional[datetime] = None) -> Optional[datetime]` (tz-aware, or `None` when unset or expired — Task 7 uses it), `readiness_entry(user: User) -> SsoReadinessEntry`, `readiness(db: Session) -> SsoReadiness`, `has_microsoft_link(db: Session, user_id: int) -> bool`, `allow_microsoft_link(db: Session, actor: User, user: User) -> SsoReadinessEntry`.
- Produces: `GET /api/v1/users/sso-readiness` → `{"active_users": int, "linked": int, "unlinked": [{"id", "email", "full_name", "is_superuser", "link_allowed_until"}]}`; `POST /api/v1/users/{user_id}/allow-microsoft-link` → one entry. The dashboard (Task 11) relies on these shapes.

- [ ] **Step 1: Write the failing tests** — append to `tests/integration/test_sso_only.py` (add `from datetime import datetime, timedelta, timezone` to the imports):

```python
READINESS = "/api/v1/users/sso-readiness"


def allow_url(user_id):
    return f"/api/v1/users/{user_id}/allow-microsoft-link"


def _link_microsoft(db, user, oid="oid-1"):
    db.add(OAuthAccount(user_id=user.id, provider="microsoft", provider_user_id=f"tenant:{oid}"))
    db.commit()


def _aware(value):
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def test_readiness_counts_active_users_and_lists_the_unlinked(client, db, make_user, auth_header):
    root = make_user("root@example.com", superuser=True)
    ann = make_user("ann@example.com")
    bob = make_user("bob@example.com")
    make_user("gone@example.com", active=False)
    _link_microsoft(db, bob)
    db.add(OAuthAccount(user_id=ann.id, provider="google", provider_user_id="g-1"))  # not a Microsoft link
    db.commit()

    # Declared before /users/{user_id}: otherwise "sso-readiness" is parsed as an id and this is a 422
    response = client.get(READINESS, headers=auth_header(root))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active_users"] == 3 and body["linked"] == 1
    assert body["unlinked"] == [
        {"id": ann.id, "email": "ann@example.com", "full_name": None, "is_superuser": False, "link_allowed_until": None},
        {"id": root.id, "email": "root@example.com", "full_name": None, "is_superuser": True, "link_allowed_until": None},
    ]


def test_readiness_and_allow_are_for_superusers_only(client, db, make_user, auth_header):
    ann = make_user("ann@example.com")
    assert client.get(READINESS, headers=auth_header(ann)).status_code == 403
    assert client.get(READINESS).status_code == 401
    assert client.post(allow_url(ann.id), headers=auth_header(ann)).status_code == 403
    db.refresh(ann)
    assert ann.microsoft_link_allowed_until is None


def test_allowing_a_link_sets_seven_days_and_is_logged(client, db, make_user, auth_header, caplog):
    root = make_user("root@example.com", superuser=True)
    ann = make_user("ann@example.com")
    before = datetime.now(timezone.utc)
    with caplog.at_level(logging.WARNING, logger="src.auth.service.sso_readiness"):
        response = client.post(allow_url(ann.id), headers=auth_header(root))
    assert response.status_code == 200, response.text
    entry = response.json()
    assert (entry["id"], entry["email"], entry["is_superuser"]) == (ann.id, "ann@example.com", False)
    until = _aware(entry["link_allowed_until"])
    assert timedelta(days=7) - timedelta(minutes=1) < until - before < timedelta(days=7) + timedelta(minutes=1)
    assert "Microsoft link allowed" in caplog.text
    assert "root@example.com" in caplog.text and "ann@example.com" in caplog.text and until.date().isoformat() in caplog.text

    listed = client.get(READINESS, headers=auth_header(root)).json()["unlinked"]
    assert next(u for u in listed if u["id"] == ann.id)["link_allowed_until"] is not None


def test_an_expired_allowance_reads_as_none(client, db, make_user, auth_header):
    root = make_user("root@example.com", superuser=True)
    ann = make_user("ann@example.com")
    ann.microsoft_link_allowed_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    listed = client.get(READINESS, headers=auth_header(root)).json()["unlinked"]
    assert next(u for u in listed if u["id"] == ann.id)["link_allowed_until"] is None


def test_allow_an_unknown_user_is_404(client, make_user, auth_header):
    root = make_user("root@example.com", superuser=True)
    response = client.post(allow_url(999999), headers=auth_header(root))
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


@pytest.mark.parametrize("case, detail", [
    ("linked", "User has already linked Microsoft"),
    ("inactive", "User is inactive"),
])
def test_allow_a_linked_or_inactive_user_is_409(client, db, make_user, auth_header, case, detail):
    root = make_user("root@example.com", superuser=True)
    ann = make_user("ann@example.com", active=(case != "inactive"))
    if case == "linked":
        _link_microsoft(db, ann)
    response = client.post(allow_url(ann.id), headers=auth_header(root))
    assert response.status_code == 409
    assert response.json() == {"detail": detail}
    db.refresh(ann)
    assert ann.microsoft_link_allowed_until is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_sso_only.py -q -k "readiness or allow"`
Expected: FAIL — readiness answers 422 (`sso-readiness` parsed as `user_id`), allow answers 404/405.

- [ ] **Step 3: Schemas.** Append to `src/auth/schemas/user.py`:

```python
class SsoReadinessEntry(BaseModel):
    # One active user without a Microsoft link (ADR-031). link_allowed_until: set only while a
    # superuser's one-time allowance is valid; an expired one reads as null.
    id: int
    email: str
    full_name: Optional[str] = None
    is_superuser: bool
    link_allowed_until: Optional[datetime] = None


class SsoReadiness(BaseModel):
    active_users: int
    linked: int
    unlinked: List[SsoReadinessEntry]
```

- [ ] **Step 4: The service.** Create `src/auth/service/sso_readiness.py`:

```python
"""Who can sign in with Microsoft yet, and the one-time link allowance (ADR-031)."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.models.oauth import OAuthAccount
from src.auth.models.user import User
from src.auth.schemas.user import SsoReadiness, SsoReadinessEntry

logger = logging.getLogger(__name__)

MICROSOFT_LINK_ALLOWANCE_DAYS = 7


def valid_allowance(user: User, now: Optional[datetime] = None) -> Optional[datetime]:
    """The allowance's end, tz-aware, while it is in the future; None when unset or expired.
    SQLite hands back naive datetimes for timezone-aware columns, so they are read as UTC."""
    until = user.microsoft_link_allowed_until
    if until is None:
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until if until > (now or datetime.now(timezone.utc)) else None


def readiness_entry(user: User) -> SsoReadinessEntry:
    return SsoReadinessEntry(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_superuser=bool(user.is_superuser),
        link_allowed_until=valid_allowance(user),
    )


def _microsoft_user_ids():
    return select(OAuthAccount.user_id).where(OAuthAccount.provider == "microsoft")


def has_microsoft_link(db: Session, user_id: int) -> bool:
    return db.query(OAuthAccount.id).filter(
        OAuthAccount.user_id == user_id, OAuthAccount.provider == "microsoft"
    ).first() is not None


def readiness(db: Session) -> SsoReadiness:
    """Active users, how many have linked Microsoft, and the rest sorted by email (superusers included:
    they keep the break-glass, but should link too)."""
    active = db.query(User).filter(User.is_active == True)  # noqa: E712
    linked = active.filter(User.id.in_(_microsoft_user_ids())).count()
    unlinked = active.filter(User.id.notin_(_microsoft_user_ids())).order_by(User.email).all()
    return SsoReadiness(
        active_users=linked + len(unlinked),
        linked=linked,
        unlinked=[readiness_entry(user) for user in unlinked],
    )


def allow_microsoft_link(db: Session, actor: User, user: User) -> SsoReadinessEntry:
    """Let `user` link a Microsoft identity at their next Microsoft sign-in, for 7 days. The caller has
    checked that the user exists, is active and is not linked."""
    until = datetime.now(timezone.utc) + timedelta(days=MICROSOFT_LINK_ALLOWANCE_DAYS)
    user.microsoft_link_allowed_until = until
    db.commit()
    db.refresh(user)
    logger.warning(
        "Microsoft link allowed: superuser %s (%s) let user %s (%s) link at their next Microsoft sign-in until %s",
        actor.id, actor.email, user.id, user.email, until.isoformat(),
    )
    return readiness_entry(user)
```

- [ ] **Step 5: The routes.** In `endpoints/users.py` add imports `from src.auth.schemas.user import SsoReadiness, SsoReadinessEntry` (merge into the existing schemas import) and `from src.auth.service import sso_readiness`. Insert these two routes **directly above** `@router.get("/{user_id}", response_model=User)`:

```python
@router.get("/sso-readiness", response_model=SsoReadiness)
def read_sso_readiness(
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_superuser),
):
    """Who has linked Microsoft yet (ADR-031). Superusers only. Declared before /{user_id}, which would
    otherwise take "sso-readiness" as an id."""
    return sso_readiness.readiness(db)


@router.post("/{user_id}/allow-microsoft-link", response_model=SsoReadinessEntry)
def allow_microsoft_link(
    user_id: int,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_superuser),
):
    """Let one account link Microsoft at its next Microsoft sign-in, for 7 days (ADR-031)."""
    user = UserService.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is inactive")
    if sso_readiness.has_microsoft_link(db, user.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User has already linked Microsoft")
    return sso_readiness.allow_microsoft_link(db, current_user, user)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_sso_only.py tests/integration/test_user_isolation.py -q`
Expected: all PASS (`test_user_isolation.py` covers `/users/{user_id}`, which must still work).

- [ ] **Step 7: Docs.** auth-service README, `### User Management`, after the `GET /api/v1/users/` bullet:

```markdown
- `GET /api/v1/users/sso-readiness` - SUPERUSER ONLY (ADR-031). `{"active_users", "linked", "unlinked": [{"id", "email", "full_name", "is_superuser", "link_allowed_until"}]}`: active users without a Microsoft link, by email, superusers included; `link_allowed_until` is null unless a valid allowance exists.
- `POST /api/v1/users/{user_id}/allow-microsoft-link` - SUPERUSER ONLY. Lets that account link Microsoft at its next Microsoft sign-in, for 7 days; logged at WARNING (who, whom, until). Returns the readiness entry. `404` unknown user; `409` already linked or inactive.
```

- [ ] **Step 8: Full suite, then commit**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` — Expected: all PASS.

```bash
git add platforms/auth-service/auth-service/src/auth/service/sso_readiness.py platforms/auth-service/auth-service/src/auth/schemas/user.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py platforms/auth-service/auth-service/tests/integration/test_sso_only.py platforms/auth-service/auth-service/README.md
git commit -o platforms/auth-service/auth-service/src/auth/service/sso_readiness.py platforms/auth-service/auth-service/src/auth/schemas/user.py platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py platforms/auth-service/auth-service/tests/integration/test_sso_only.py platforms/auth-service/auth-service/README.md -m "feat(auth): SSO readiness and a one-time Microsoft link allowance for superusers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `/sso/microsoft` uses the allowance; delivery-1 docs and gate

**Files:**
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/sso.py` (`_link_or_create_user`)
- Test: `platforms/auth-service/auth-service/tests/integration/test_microsoft_sso.py`
- Modify: `docs/SETUP.md` §3.8, `SECURITY.md` (Known limitations), `PRODUCT.md`, `TODO.md`, `TECHNICAL_SPECIFICATION.md`, `platforms/auth-service/auth-service/README.md`

**Interfaces:**
- Consumes: `valid_allowance(user)` (Task 6); `User.microsoft_link_allowed_until` (Task 4); the existing `microsoft_key` fixture, `ms_token(private_key, **overrides)`, `sign_in(client, token)`, constants `TENANT`, `OID` in `test_microsoft_sso.py`.
- Produces: the allowance branch in `_link_or_create_user`; nothing new for later tasks.

- [ ] **Step 1: Write the failing tests** — append to `tests/integration/test_microsoft_sso.py`:

```python
def _allow(db, email, minutes=7 * 24 * 60):
    user = db.query(User).filter(User.email == email).one()
    user.microsoft_link_allowed_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    db.commit()
    return user


def test_an_allowed_account_is_linked_at_its_next_microsoft_sign_in(client, db, microsoft_key, register_and_verify, caplog):
    register_and_verify("ann@example.com")
    ann = _allow(db, "ann@example.com")

    with caplog.at_level(logging.WARNING, logger="src.auth.api.v1.endpoints.sso"):
        response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 200, response.text
    link = db.query(OAuthAccount).one()
    assert (link.user_id, link.provider, link.provider_user_id) == (ann.id, "microsoft", f"{TENANT}:{OID}")
    db.refresh(ann)
    assert ann.microsoft_link_allowed_until is None  # used once
    assert db.query(User).count() == 1
    assert "one-time allowance" in caplog.text
    # From now on the identity finds the account by itself
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200


def test_an_expired_allowance_keeps_the_409(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    _allow(db, "ann@example.com", minutes=-1)
    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 409
    assert db.query(OAuthAccount).count() == 0


def test_the_allowance_belongs_to_its_account_not_to_the_next_token(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    ann = _allow(db, "ann@example.com")
    allowed_until = ann.microsoft_link_allowed_until

    other = sign_in(client, ms_token(microsoft_key, oid="00000000-0000-0000-0000-000000000002",
                                     email="bob@example.com", preferred_username="bob@example.com"))
    assert other.status_code == 200, other.text
    bob = db.query(User).filter(User.email == "bob@example.com").one()
    assert db.query(OAuthAccount).one().user_id == bob.id  # Bob's own new account
    db.refresh(ann)
    assert ann.microsoft_link_allowed_until == allowed_until  # untouched, still Ann's


def test_an_allowance_does_not_replace_an_existing_link(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    ann = _allow(db, "ann@example.com")
    db.add(OAuthAccount(user_id=ann.id, provider="microsoft", provider_user_id=f"{TENANT}:someone-else"))
    db.commit()

    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 409
    assert response.json() == {"detail": "This account is linked to a different Microsoft identity"}
    db.refresh(ann)
    assert ann.microsoft_link_allowed_until is not None
    assert db.query(OAuthAccount).count() == 1


def test_an_allowance_on_an_inactive_account_does_not_link(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    ann = _allow(db, "ann@example.com")
    ann.is_active = False
    db.commit()
    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 409
    assert db.query(OAuthAccount).count() == 0


def test_a_token_from_another_tenant_never_uses_the_allowance(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    ann = _allow(db, "ann@example.com")
    response = sign_in(client, ms_token(microsoft_key, tid="12345678-0000-0000-0000-000000000000"))
    assert response.status_code == 400
    db.refresh(ann)
    assert ann.microsoft_link_allowed_until is not None
    assert db.query(OAuthAccount).count() == 0


def test_the_allowance_works_in_sso_only_mode(client, db, microsoft_key, register_and_verify, monkeypatch):
    register_and_verify("ann@example.com")  # before the switch: registration is off afterwards
    _allow(db, "ann@example.com")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_microsoft_sso.py -q -k allowance`
Expected: `test_an_allowed_account_is_linked…` and `test_the_allowance_works_in_sso_only_mode` FAIL with `assert 409 == 200`; the refusal tests already PASS (they pin that nothing else changes).

- [ ] **Step 3: Implement.** In `endpoints/sso.py` add `from src.auth.service.sso_readiness import valid_allowance`. In `_link_or_create_user`, directly **before** the final `raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=existing_account_detail,)` (after the `existing_link` block and its long comment), insert:

```python
    # A superuser allowed this account to link at its next Microsoft sign-in (ADR-031). Not a match on
    # the email alone: the allowance names this account, the token is from an allowed tenant (checked
    # by verify_microsoft_credential) and the account holds no Microsoft link yet (checked above).
    # Used once.
    if provider == "microsoft" and user.is_active and valid_allowance(user) is not None:
        db.add(OAuthAccount(user_id=user.id, provider=provider, provider_user_id=provider_user_id))
        user.microsoft_link_allowed_until = None
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This {label} account is already linked",
            )
        db.refresh(user)
        logger.warning("Microsoft identity linked to user %s (%s) through the one-time allowance", user.id, user.email)
        return user
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_microsoft_sso.py -q`
Expected: all PASS (the existing `test_an_existing_account_with_the_email_is_not_taken_over` still answers 409).

- [ ] **Step 5: SETUP §3.8.** Replace the paragraph `Account rules: … The dashboard has no button for this.` with:

```markdown
Account rules: the first sign-in with a new address creates an account without a password.
An address that already has a password account is **not** linked automatically: the answer
is 409. A signed-in user links it with `POST /api/v1/users/me/link/{google|microsoft}`, or a
superuser allows that one account to link at its next Microsoft sign-in (below).
```

and add, before **Verify (section 3):**, a new subsection:

```markdown
**Microsoft-only sign-in (SSO-only mode, ADR-031)**

For a company deployment where people sign in only with their Microsoft work account:

1. Configure Microsoft as above and check that signing in with Microsoft works.
2. Ask everyone with a password account to link Microsoft (`POST /api/v1/users/me/link/microsoft`).
3. Check readiness as a superuser: `GET /api/v1/users/sso-readiness` lists the active users who have not
   linked. For someone who missed it, `POST /api/v1/users/{id}/allow-microsoft-link` lets that account
   link at its next Microsoft sign-in, for 7 days.
4. In `.env`: `AUTH_SSO_ONLY=true` (and `AUTH_SSO_PROVIDERS=microsoft`, the default). Then
   `docker compose up -d --wait auth-service`.

At that restart, every session of everyone who is not a superuser ends (once; later restarts do not);
access tokens already issued run out within 60 minutes. Registration, email verification and password
recovery answer 403. auth-service refuses to start if Microsoft is not configured, and warns in its log
when there is no active superuser.

**Break-glass:** active superusers keep password sign-in (two-factor authentication still applies).
Every such sign-in is logged at WARNING as `break-glass sign-in` with user id, email, IP and time:
`docker compose logs auth-service | grep break-glass`.

**New colleagues:** they sign in once with Microsoft (that creates their account), then an owner or
admin adds them to the organization or project; members are added by existing account.

**Known limitation:** someone removed from Entra ID cannot get a new Microsoft token, but a QEOS session
they already hold lasts until its refresh token expires (30 days). Deactivate them in QEOS to end it at
once. Automatic deprovisioning (SCIM) is not built.

To turn the mode off: `AUTH_SSO_ONLY=false`, restart auth-service.
```

Add a row to "Common problems (section 3)":

```markdown
| 403 "Sign-in is through Microsoft only." on sign-in, register or reset | SSO-only mode is on. Sign in with Microsoft; administrators use their password (superusers only). |
```

- [ ] **Step 6: The other docs.**

`SECURITY.md` → `## Known limitations`, add a bullet:

```markdown
- SSO-only mode: someone removed from Entra ID keeps an existing QEOS session
  until its refresh token expires (30 days) unless deactivated in QEOS; SCIM
  deprovisioning is not built (ADR-031).
```

and extend the SSO-only bullet in "What the platform does today" with: `A superuser can allow one account to link Microsoft at its next Microsoft sign-in (7 days, logged at WARNING, used once); it is never matched on the email alone.`

`PRODUCT.md`: change `auth-service (JWT, MFA, Google and\n  Microsoft SSO)` to `auth-service (JWT, MFA, Google and\n  Microsoft SSO, an optional Microsoft-only sign-in mode with a superuser break-glass)`.

`TODO.md` → `### Microsoft SSO`: add after the first two `[x]` lines:

```markdown
- [x] SSO-only mode (`AUTH_SSO_ONLY`, ADR-031): Microsoft sign-in only, active superusers keep a logged password break-glass, non-superuser sessions revoked once per switch, readiness and a one-time 7-day link allowance
```

and change `- [ ] SCIM provisioning and deprovisioning` to `- [ ] SCIM provisioning and deprovisioning (ends the sessions of people removed from Entra; today they last until the refresh token expires, ADR-031)`.

`TECHNICAL_SPECIFICATION.md`, extend the SSO-only bullet with:

```markdown
  Off-to-on: non-superuser refresh sessions revoked once (`auth_mode_state`,
  migration 008, row lock). `/users/sso-readiness` and
  `/users/{id}/allow-microsoft-link` (superusers; 7-day allowance used at the
  next `/sso/microsoft`); `/users/me` adds `linked_providers`, `sso_only`,
  `has_password`.
```

auth-service README, the `POST /api/v1/sso/microsoft` bullet, append: ``. An account that holds the token's address but no Microsoft link is linked only when a superuser allowed it (`allow-microsoft-link`, valid 7 days, cleared when used); otherwise 409.``

- [ ] **Step 7: Delivery gate (local CI mirror for auth-service)**

Run: `SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` (service dir) — Expected: all PASS.
Run: `python scripts/check_architecture_docs.py` (repo root) — Expected: exit 0.
Run: `bash -n scripts/smoke_gateway.sh` — Expected: exit 0. With Docker available: `docker compose up -d --build --wait` then `bash scripts/smoke_gateway.sh` — Expected: `ok    /api/v1/auth/methods without a token -> auth-service (200)` and no `FAIL`.

- [ ] **Step 8: Commit** (the user pushes delivery 1 after reviewing; do not push)

```bash
git add platforms/auth-service/auth-service/src/auth/api/v1/endpoints/sso.py platforms/auth-service/auth-service/tests/integration/test_microsoft_sso.py docs/SETUP.md SECURITY.md PRODUCT.md TODO.md TECHNICAL_SPECIFICATION.md platforms/auth-service/auth-service/README.md
git commit -o platforms/auth-service/auth-service/src/auth/api/v1/endpoints/sso.py platforms/auth-service/auth-service/tests/integration/test_microsoft_sso.py docs/SETUP.md SECURITY.md PRODUCT.md TODO.md TECHNICAL_SPECIFICATION.md platforms/auth-service/auth-service/README.md -m "feat(auth): a superuser's link allowance is used at the next Microsoft sign-in; SSO-only setup docs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Delivery 2 — dashboard

### Task 8: Login page reads `/auth/methods`

**Files:**
- Modify: `dashboard/src/api/auth.ts` (`AuthMethods`, `getAuthMethods`)
- Create: `dashboard/src/auth/useAuthMethods.ts`
- Modify: `dashboard/src/pages/LoginPage.tsx`
- Modify: `dashboard/src/test/server.ts` (default handler)
- Test: `dashboard/src/pages/LoginPage.test.tsx`
- Modify: `DESIGN.md`, `TECHNICAL_SPECIFICATION.md`

**Interfaces:**
- Consumes: `GET /api/v1/auth/methods` → `{password: boolean, providers: string[]}` (Task 2).
- Produces (in `src/api/auth.ts`): `interface AuthMethods { password: boolean; providers: string[] }`, `getAuthMethods(): Promise<AuthMethods>`.
- Produces (in `src/auth/useAuthMethods.ts`): `useAuthMethods(): AuthMethods | null` (null while loading, on failure, or on a malformed answer), `isSsoOnly(methods: AuthMethods | null): boolean`, `isSsoOnlyError(error: unknown): boolean` (an `ApiError` with `code === "sso_only"`), `providerNames(providers: readonly string[]): string` (`"Microsoft"`, `"Microsoft or Google"`), `ssoOnlyLine(providers: readonly string[]): string`.

- [ ] **Step 1: Invoke the `ui-ux-pro-max` skill before editing UI.** Ask it to review: the SSO-only login card (one line, the provider button as the card's one primary, a closed native `<details>` "Administrator sign-in" using the existing `.more-filters` summary style holding the email/password form, with the same `ChevronRight` summary markup as `src/components/FiltersDisclosure.tsx`), focus order, and that nothing new is needed in `index.css`. Fold its fixes into Steps 4–5.

- [ ] **Step 2: Write the failing tests** — append to `dashboard/src/pages/LoginPage.test.tsx` (add `within` to the `@testing-library/react` import):

```tsx
function methods(body: unknown, init?: ResponseInit) {
  server.use(http.get("/api/v1/auth/methods", () => HttpResponse.json(body as object, init)));
}

test("SSO-only: the Microsoft button and one line, no register or forgot-password links", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  methods({ password: false, providers: ["microsoft"] });
  renderLogin();
  expect(await screen.findByText("Sign-in is through your Microsoft work account.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sign in with Microsoft" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /create account/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /forgot password/i })).not.toBeInTheDocument();
  const disclosure = screen.getByText("Administrator sign-in").closest("details")!;
  expect(disclosure).not.toHaveAttribute("open");
  expect(within(disclosure).getByLabelText(/email/i)).toBeInTheDocument();
});

test("SSO-only: an administrator signs in with the password form inside the disclosure", async () => {
  methods({ password: false, providers: ["microsoft"] });
  server.use(http.post("/api/v1/auth/login", () =>
    HttpResponse.json({ access_token: "acc", refresh_token: "r", token_type: "bearer" })));
  renderLogin();
  await userEvent.click(await screen.findByText("Administrator sign-in"));
  await userEvent.type(screen.getByLabelText(/email/i), "root@b.co");
  await userEvent.type(screen.getByLabelText(/password/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
  expect(await screen.findByText("PICKER")).toBeInTheDocument();
});

test("SSO-only: a refusal from the server shows in the card", async () => {
  methods({ password: false, providers: ["microsoft"] });
  server.use(http.post("/api/v1/auth/login", () => HttpResponse.json(
    { detail: { code: "sso_only", message: "Sign-in is through Microsoft only." } }, { status: 403 })));
  renderLogin();
  await userEvent.click(await screen.findByText("Administrator sign-in"));
  await userEvent.type(screen.getByLabelText(/email/i), "ann@b.co");
  await userEvent.type(screen.getByLabelText(/password/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in is through Microsoft only.");
});

test("SSO-only hides a provider the mode does not list", async () => {
  vi.mocked(googleEnabled).mockReturnValue(true);
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  methods({ password: false, providers: ["microsoft"] });
  renderLogin();
  await screen.findByText("Sign-in is through your Microsoft work account.");
  expect(screen.queryByTestId("google-button")).not.toBeInTheDocument();
});

test("normal mode is unchanged when /auth/methods says password", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  let asked = false;
  server.use(http.get("/api/v1/auth/methods", () => {
    asked = true;
    return HttpResponse.json({ password: true, providers: ["microsoft"] });
  }));
  renderLogin();
  await waitFor(() => expect(asked).toBe(true));
  expect(screen.getByRole("link", { name: /forgot password/i })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /create account/i })).toBeInTheDocument();
  expect(screen.queryByText("Administrator sign-in")).not.toBeInTheDocument();
});

test.each<[string, () => Response]>([
  ["a server error", () => HttpResponse.json({ detail: "boom" }, { status: 500 })],
  ["a network error", () => HttpResponse.error()],
  ["an older server's 404", () => HttpResponse.json({ detail: "Not Found" }, { status: 404 })],
  ["an answer of the wrong shape", () => HttpResponse.json({})],
])("when /auth/methods gives %s, the normal form stays", async (_name, answer) => {
  let asked = false;
  server.use(http.get("/api/v1/auth/methods", () => {
    asked = true;
    return answer();
  }));
  renderLogin();
  await waitFor(() => expect(asked).toBe(true));
  await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
  expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /forgot password/i })).toBeInTheDocument();
  expect(screen.queryByText("Administrator sign-in")).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run them to verify they fail**

Run (from `dashboard/`): `npx vitest run src/pages/LoginPage.test.tsx`
Expected: the SSO-only tests FAIL (`Unable to find an element with the text: Sign-in is through your Microsoft work account.`); the existing tests PASS.

- [ ] **Step 4: API, hook and test default.** Append to `dashboard/src/api/auth.ts`:

```ts
/** GET /auth/methods (public, ADR-031): `password: false` means SSO-only mode; `providers` are the ones offered. */
export interface AuthMethods {
  password: boolean;
  providers: string[];
}

export function getAuthMethods(): Promise<AuthMethods> {
  return apiFetch("/api/v1/auth/methods");
}
```

Create `dashboard/src/auth/useAuthMethods.ts`:

```ts
import { useEffect, useState } from "react";
import { getAuthMethods, type AuthMethods } from "../api/auth";
import { ApiError } from "../api/http";

function wellFormed(value: unknown): value is AuthMethods {
  const v = value as AuthMethods | null;
  return typeof v?.password === "boolean" && Array.isArray(v.providers) && v.providers.every((p) => typeof p === "string");
}

/** How this deployment signs people in (ADR-031), read once per mount. Null while loading, and when the
 *  request fails or answers something unexpected: the page then shows its normal form, and the server
 *  still enforces the mode. */
export function useAuthMethods(): AuthMethods | null {
  const [methods, setMethods] = useState<AuthMethods | null>(null);
  useEffect(() => {
    let cancelled = false;
    getAuthMethods()
      .then((answer) => {
        if (!cancelled && wellFormed(answer)) setMethods(answer);
      })
      .catch(() => {
        // Normal form: see above
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return methods;
}

export function isSsoOnly(methods: AuthMethods | null): boolean {
  return methods !== null && !methods.password;
}

/** The server's SSO-only refusal: 403 {"detail": {"code": "sso_only", ...}} */
export function isSsoOnlyError(error: unknown): boolean {
  return error instanceof ApiError && error.code === "sso_only";
}

const LABELS: Record<string, string> = { microsoft: "Microsoft", google: "Google" };

export function providerNames(providers: readonly string[]): string {
  const names = providers.map((p) => LABELS[p] ?? p);
  return names.length > 0 ? names.join(" or ") : "single sign-on";
}

/** The login page's one line in SSO-only mode. */
export function ssoOnlyLine(providers: readonly string[]): string {
  if (providers.length === 1 && providers[0] === "microsoft") return "Sign-in is through your Microsoft work account.";
  return `Sign-in is through ${providerNames(providers)}.`;
}
```

In `dashboard/src/test/server.ts`, add to the `setupServer(...)` list, after the `/api/v1/users/me` handler:

```ts
  // Sign-in methods (ADR-031): password sign-in on, no SSO; SSO-only tests override
  http.get("/api/v1/auth/methods", () => HttpResponse.json({ password: true, providers: [] })),
```

- [ ] **Step 5: LoginPage.** In `dashboard/src/pages/LoginPage.tsx`:

1. Imports: add `import { ChevronRight } from "lucide-react";` and `import { isSsoOnly, ssoOnlyLine, useAuthMethods } from "../auth/useAuthMethods";`; `useRef` stays (for `nextRef`).
2. Replace `const googleRef = useRef<HTMLDivElement>(null);` with:

```tsx
  const methods = useAuthMethods();
  const ssoOnly = isSsoOnly(methods);
  // The Google button renders into whichever slot is mounted: the layout changes once /auth/methods answers
  const [googleSlot, setGoogleSlot] = useState<HTMLDivElement | null>(null);
```

3. Replace the mount-only Google `useEffect` with:

```tsx
  useEffect(() => {
    if (googleSlot) {
      initGoogleButton(googleSlot, (credential) => onGoogleCredential(credential)).catch((err) => setError(err));
    }
  }, [googleSlot]);
```

4. Replace `const anySso = googleEnabled() || microsoftEnabled();` and the final `return (…)` with:

```tsx
  // In SSO-only mode only the providers the mode lists; otherwise every provider this build has a client id for
  const offered = (provider: string) => !ssoOnly || methods!.providers.includes(provider);
  const showGoogle = googleEnabled() && offered("google");
  const showMicrosoft = microsoftEnabled() && offered("microsoft");
  const anySso = showGoogle || showMicrosoft;

  const credentials = (
    <>
      <TextField label="Email" type="email" autoComplete="email" value={email} onChange={setEmail} required />
      <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={setPassword} required />
    </>
  );

  if (ssoOnly) {
    return (
      <AuthShell title="Sign in">
        <div className="card">
          {expired && <p role="status" className="muted">Your session expired, sign in again.</p>}
          <p>{ssoOnlyLine(methods!.providers)}</p>
          {error != null && <ErrorBanner error={error} />}
          {showMicrosoft && (
            <button className="primary" type="button" onClick={onMicrosoft} style={{ width: "100%" }}>
              Sign in with Microsoft
            </button>
          )}
          {showGoogle && <div ref={setGoogleSlot} data-testid="google-button" style={{ marginTop: 8 }} />}
          {/* Break-glass for superusers (ADR-031): closed by default, not advertised */}
          <details className="more-filters" style={{ marginTop: 16 }}>
            <summary>
              <ChevronRight size={14} aria-hidden="true" className="chevron" />
              Administrator sign-in
            </summary>
            <form onSubmit={onSubmit}>
              {credentials}
              <button className="primary" type="submit" disabled={busy}>
                {busy ? "Signing in…" : "Sign in"}
              </button>
            </form>
          </details>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Sign in">
      <form className="card" onSubmit={onSubmit}>
        {expired && <p role="status" className="muted">Your session expired, sign in again.</p>}
        {credentials}
        {/* Router state, not a query string: an address in the URL ends up in history and access logs */}
        <Link className="field-link" to="/forgot-password" state={{ email }}>
          Forgot password?
        </Link>
        {error != null && <ErrorBanner error={error} />}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {anySso && (
          <>
            <p className="muted" style={{ textAlign: "center", margin: "16px 0 8px" }}>
              or
            </p>
            {showGoogle && <div ref={setGoogleSlot} data-testid="google-button" />}
            {showMicrosoft && (
              <button type="button" onClick={onMicrosoft} style={{ width: "100%", marginTop: 8 }}>
                Sign in with Microsoft
              </button>
            )}
          </>
        )}
        <p className="muted" style={{ marginBottom: 0 }}>
          New here? <Link to={withNext("/register", next)}>Create account</Link>
        </p>
      </form>
    </AuthShell>
  );
```

The MFA step (`if (mfaToken !== null)`) is unchanged and still comes first, so a superuser with MFA gets the code step in either layout.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run src/pages/LoginPage.test.tsx src/pages/publicPages.test.tsx src/App.routing.test.tsx`
Expected: all PASS.

- [ ] **Step 7: Docs.** `DESIGN.md`, after the `- **Public pages** (\`AuthShell\`) …` bullet, add:

```markdown
- **Sign in, SSO-only mode** (ADR-031, from `GET /auth/methods`): one card with one line ("Sign-in is through your Microsoft work account."), the provider button as the card's primary, then a closed native `<details>` "Administrator sign-in" (the `.more-filters` summary style) holding the email and password form for superusers. No Register or Forgot-password links. While `/auth/methods` loads, or if it fails, the normal form shows; the server enforces the mode either way.
```

`TECHNICAL_SPECIFICATION.md`, in the dashboard Views sentence, change `login (password/MFA step/SSO buttons when VITE_* client ids are baked),` to `login (password/MFA step/SSO buttons when VITE_* client ids are baked; SSO-only layout from /auth/methods with a superuser disclosure),`.

- [ ] **Step 8: Lint, typecheck, commit**

Run: `npm run lint` and `npm run typecheck` — Expected: no errors.

```bash
git add dashboard/src/api/auth.ts dashboard/src/auth/useAuthMethods.ts dashboard/src/pages/LoginPage.tsx dashboard/src/pages/LoginPage.test.tsx dashboard/src/test/server.ts DESIGN.md TECHNICAL_SPECIFICATION.md
git commit -o dashboard/src/api/auth.ts dashboard/src/auth/useAuthMethods.ts dashboard/src/pages/LoginPage.tsx dashboard/src/pages/LoginPage.test.tsx dashboard/src/test/server.ts DESIGN.md TECHNICAL_SPECIFICATION.md -m "feat(dashboard): SSO-only login page with an administrator sign-in disclosure" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Register, Forgot password, Reset password, Verify email point to sign-in

**Files:**
- Create: `dashboard/src/components/SsoOnlyNotice.tsx`
- Modify: `dashboard/src/pages/RegisterPage.tsx`, `ForgotPasswordPage.tsx`, `ResetPasswordPage.tsx`, `VerifyEmailPage.tsx`
- Test: `dashboard/src/pages/RegisterPage.test.tsx`, `ForgotPasswordPage.test.tsx`, `ResetPasswordPage.test.tsx`, `VerifyEmailPage.test.tsx`
- Modify: `DESIGN.md`

**Interfaces:**
- Consumes: `useAuthMethods`, `isSsoOnly`, `isSsoOnlyError`, `providerNames` (Task 8).
- Produces: `SsoOnlyNotice({ providers }: { providers?: readonly string[] })` (default `["microsoft"]`): `AuthShell` titled `Sign in with Microsoft`, a status line `Sign-in is through Microsoft only.`, a link `Go to sign in` → `/login`.

- [ ] **Step 1: Invoke the `ui-ux-pro-max` skill before editing UI.** Review the notice card (one h1 from `AuthShell`, one status line, one link; no form) for the four pages.

- [ ] **Step 2: Write the failing tests.** Append to each page's test file (each file already imports `http`, `HttpResponse`, `server`, `screen`, `userEvent`, and defines `renderPage`):

`RegisterPage.test.tsx`:

```tsx
const SSO_ONLY = { password: false, providers: ["microsoft"] };
const SSO_ONLY_403 = { detail: { code: "sso_only", message: "Sign-in is through Microsoft only." } };

test("in SSO-only mode the page points to sign-in instead of a form", async () => {
  server.use(http.get("/api/v1/auth/methods", () => HttpResponse.json(SSO_ONLY)));
  renderPage();
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: "Go to sign in" }));
  expect(await screen.findByText("LOGIN")).toBeInTheDocument();
});

test("a 403 sso_only gives the same notice when /auth/methods was unavailable", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.error()),
    http.post("/api/v1/auth/register", () => HttpResponse.json(SSO_ONLY_403, { status: 403 })),
  );
  renderPage();
  await userEvent.type(screen.getByLabelText(/email/i), "pedro@example.com");
  await userEvent.type(screen.getByLabelText(/password/i), "UmaPasswordForte123");
  await userEvent.click(screen.getByRole("button", { name: /create account/i }));
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: "Sign in with Microsoft" })).toBeInTheDocument();
});
```

`ForgotPasswordPage.test.tsx`:

```tsx
const SSO_ONLY_403 = { detail: { code: "sso_only", message: "Sign-in is through Microsoft only." } };

test("in SSO-only mode the page points to sign-in instead of a form", async () => {
  server.use(http.get("/api/v1/auth/methods", () => HttpResponse.json({ password: false, providers: ["microsoft"] })));
  renderPage();
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /send reset link/i })).not.toBeInTheDocument();
});

test("a 403 sso_only gives the same notice when /auth/methods was unavailable", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.error()),
    http.post("/api/v1/auth/forgot-password", () => HttpResponse.json(SSO_ONLY_403, { status: 403 })),
  );
  renderPage();
  await userEvent.type(screen.getByLabelText(/email/i), "ann@example.com");
  await userEvent.click(screen.getByRole("button", { name: /send reset link/i }));
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
});
```

`ResetPasswordPage.test.tsx` (its `fill(password, confirm)` helper submits):

```tsx
const SSO_ONLY_403 = { detail: { code: "sso_only", message: "Sign-in is through Microsoft only." } };

test("in SSO-only mode an old reset link points to sign-in", async () => {
  server.use(http.get("/api/v1/auth/methods", () => HttpResponse.json({ password: false, providers: ["microsoft"] })));
  renderPage("/reset-password?token=t");
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.queryByLabelText(/^new password/i)).not.toBeInTheDocument();
});

test("a 403 sso_only gives the same notice when /auth/methods was unavailable", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.error()),
    http.post("/api/v1/auth/reset-password", () => HttpResponse.json(SSO_ONLY_403, { status: 403 })),
  );
  renderPage("/reset-password?token=t");
  await fill("securepassword123", "securepassword123");
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
});
```

`VerifyEmailPage.test.tsx` (`renderPage(query)` defaults to `?token=tok-123`):

```tsx
const SSO_ONLY_403 = { detail: { code: "sso_only", message: "Sign-in is through Microsoft only." } };

test("in SSO-only mode an old verification link points to sign-in", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.json({ password: false, providers: ["microsoft"] })),
    http.get("/api/v1/auth/verify-email", () => HttpResponse.json(SSO_ONLY_403, { status: 403 })),
  );
  renderPage();
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /register/i })).not.toBeInTheDocument();
});

test("a 403 sso_only gives the same notice when /auth/methods was unavailable", async () => {
  server.use(
    http.get("/api/v1/auth/methods", () => HttpResponse.error()),
    http.get("/api/v1/auth/verify-email", () => HttpResponse.json(SSO_ONLY_403, { status: 403 })),
  );
  renderPage();
  expect(await screen.findByText("Sign-in is through Microsoft only.")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `npx vitest run src/pages/RegisterPage.test.tsx src/pages/ForgotPasswordPage.test.tsx src/pages/ResetPasswordPage.test.tsx src/pages/VerifyEmailPage.test.tsx`
Expected: the 8 new tests FAIL (`Unable to find an element with the text: Sign-in is through Microsoft only.`).

- [ ] **Step 4: The notice.** Create `dashboard/src/components/SsoOnlyNotice.tsx`:

```tsx
import { Link } from "react-router-dom";
import AuthShell from "./AuthShell";
import { providerNames } from "../auth/useAuthMethods";

/** What Register, Forgot password, Reset password and Verify email show in SSO-only mode (ADR-031),
 *  for bookmarks and old emails: no form, the way to sign in. */
export default function SsoOnlyNotice({ providers = ["microsoft"] }: { providers?: readonly string[] }) {
  const names = providerNames(providers);
  return (
    <AuthShell title={`Sign in with ${names}`} subtitle={false}>
      <div className="card">
        <p role="status">{`Sign-in is through ${names} only.`}</p>
        <Link to="/login">Go to sign in</Link>
      </div>
    </AuthShell>
  );
}
```

- [ ] **Step 5: Use it in the four pages.** In each page add the imports

```tsx
import SsoOnlyNotice from "../components/SsoOnlyNotice";
import { isSsoOnly, isSsoOnlyError, useAuthMethods } from "../auth/useAuthMethods";
```

add `const methods = useAuthMethods();` as the page's last hook call (after its other `useState`/`useEffect`/`useRef` calls, so hook order never depends on the mode), and put this as the **first** early return:

```tsx
  if (isSsoOnly(methods) || isSsoOnlyError(error)) return <SsoOnlyNotice providers={methods?.providers} />;
```

Exact placement per page:
- `RegisterPage.tsx`: hook after `const loginLink = withNext("/login", next);`; return before `if (done) {`.
- `ForgotPasswordPage.tsx`: hook after `const [sentTo, setSentTo] = useState<string | null>(null);`; return before `if (sentTo !== null) {`.
- `ResetPasswordPage.tsx`: hook after the `useEffect` that drops the token from the address bar; return before `if (!token) {` (an old link without a token also lands on the notice in the mode).
- `VerifyEmailPage.tsx`: hook after the verification `useEffect`; return before `if (!token) {`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run src/pages/RegisterPage.test.tsx src/pages/ForgotPasswordPage.test.tsx src/pages/ResetPasswordPage.test.tsx src/pages/VerifyEmailPage.test.tsx src/pages/publicPages.test.tsx`
Expected: all PASS (publicPages: still one h1 per page in normal mode).

- [ ] **Step 7: Docs.** `DESIGN.md`, extend the SSO-only bullet from Task 8 with: `Register, Forgot password, Reset password and Verify email show instead a notice card (\`SsoOnlyNotice\`): h1 "Sign in with Microsoft", the status line "Sign-in is through Microsoft only." and a "Go to sign in" link; also when the server answers 403 \`sso_only\` and \`/auth/methods\` was unavailable.`

- [ ] **Step 8: Lint, typecheck, commit**

Run: `npm run lint` and `npm run typecheck` — Expected: no errors.

```bash
git add dashboard/src/components/SsoOnlyNotice.tsx dashboard/src/pages/RegisterPage.tsx dashboard/src/pages/ForgotPasswordPage.tsx dashboard/src/pages/ResetPasswordPage.tsx dashboard/src/pages/VerifyEmailPage.tsx dashboard/src/pages/RegisterPage.test.tsx dashboard/src/pages/ForgotPasswordPage.test.tsx dashboard/src/pages/ResetPasswordPage.test.tsx dashboard/src/pages/VerifyEmailPage.test.tsx DESIGN.md
git commit -o dashboard/src/components/SsoOnlyNotice.tsx dashboard/src/pages/RegisterPage.tsx dashboard/src/pages/ForgotPasswordPage.tsx dashboard/src/pages/ResetPasswordPage.tsx dashboard/src/pages/VerifyEmailPage.tsx dashboard/src/pages/RegisterPage.test.tsx dashboard/src/pages/ForgotPasswordPage.test.tsx dashboard/src/pages/ResetPasswordPage.test.tsx dashboard/src/pages/VerifyEmailPage.test.tsx DESIGN.md -m "feat(dashboard): registration and recovery pages point to sign-in in SSO-only mode" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Security page — Microsoft account card; Password card hidden in the mode

**Files:**
- Modify: `dashboard/src/api/auth.ts` (`Me`, `getMe` type, `linkMicrosoft`)
- Modify: `dashboard/src/pages/SecurityPage.tsx`
- Test: `dashboard/src/pages/SecurityPage.test.tsx`
- Modify: `DESIGN.md`, `docs/SETUP.md` §3.8

**Interfaces:**
- Consumes: `/users/me` fields `linked_providers`, `sso_only`, `has_password`, `is_superuser` (Task 5); `POST /api/v1/users/me/link/microsoft` `{credential, current_password?}`; `microsoftEnabled()`, `getMicrosoftCredential()` from `src/auth/ssoProviders.ts`.
- Produces (in `src/api/auth.ts`): `interface Me { id: number; email: string; mfa_enabled: boolean; full_name?: string | null; monitoring_url?: string | null; is_superuser?: boolean; linked_providers?: string[]; sso_only?: boolean; has_password?: boolean }`, `getMe(): Promise<Me>`, `linkMicrosoft(credential: string, currentPassword?: string): Promise<void>`. In `SecurityPage.tsx`: state `me: Me | null` that Task 11 reads.

- [ ] **Step 1: Invoke the `ui-ux-pro-max` skill before editing UI.** Review the Microsoft account card (heading, status line with `CircleCheck` when linked, one password field only when the account has one, one primary "Link Microsoft account", success note, `ErrorBanner`) and the card order (Microsoft account, Password, Two-factor).

- [ ] **Step 2: Write the failing tests** — in `dashboard/src/pages/SecurityPage.test.tsx`, add after the `qrcode` mock:

```tsx
vi.mock("../auth/ssoProviders", () => ({
  microsoftEnabled: vi.fn(() => false),
  getMicrosoftCredential: vi.fn(async () => "ms-id-token"),
}));
```

add imports `import { within } from "@testing-library/react";` and `import { microsoftEnabled } from "../auth/ssoProviders";`, add `vi.mocked(microsoftEnabled).mockReturnValue(false);` inside the existing `beforeEach`, then append:

```tsx
type MeBody = Record<string, unknown>;
function meIs(body: MeBody) {
  server.use(http.get("/api/v1/users/me", () => HttpResponse.json({ id: 1, email: "a@b.co", mfa_enabled: false, ...body })));
}
async function microsoftCard() {
  return (await screen.findByRole("heading", { name: "Microsoft account" })).closest("form")!;
}

test("a password account links Microsoft after confirming its password", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  let linked = false;
  server.use(
    http.get("/api/v1/users/me", () => HttpResponse.json({ id: 1, email: "a@b.co", mfa_enabled: false,
      has_password: true, sso_only: false, linked_providers: linked ? ["microsoft"] : [] })),
    http.post("/api/v1/users/me/link/microsoft", async ({ request }) => {
      expect(await request.json()).toEqual({ credential: "ms-id-token", current_password: "my-password-1" });
      linked = true;
      return HttpResponse.json({ id: 1, email: "a@b.co" });
    }),
  );
  renderSecurity();
  const card = await microsoftCard();
  await userEvent.type(within(card).getByLabelText(/your qeos password/i), "my-password-1");
  await userEvent.click(within(card).getByRole("button", { name: "Link Microsoft account" }));
  expect(await within(card).findByText(/microsoft account linked/i)).toBeInTheDocument();
  expect(await within(card).findByText("Linked to Microsoft")).toBeInTheDocument();
  expect(within(card).queryByRole("button", { name: "Link Microsoft account" })).not.toBeInTheDocument();
});

test("a passwordless account links without a password prompt", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  meIs({ has_password: false, linked_providers: ["google"] });
  server.use(http.post("/api/v1/users/me/link/microsoft", async ({ request }) => {
    expect(await request.json()).toEqual({ credential: "ms-id-token" });
    return HttpResponse.json({ id: 1, email: "a@b.co" });
  }));
  renderSecurity();
  const card = await microsoftCard();
  expect(within(card).queryByLabelText(/your qeos password/i)).not.toBeInTheDocument();
  await userEvent.click(within(card).getByRole("button", { name: "Link Microsoft account" }));
  expect(await within(card).findByText(/microsoft account linked/i)).toBeInTheDocument();
});

test("a link refusal is shown in the card", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  meIs({ has_password: true, linked_providers: [] });
  server.use(http.post("/api/v1/users/me/link/microsoft", () =>
    HttpResponse.json({ detail: "This Microsoft account is already linked to a different user" }, { status: 409 })));
  renderSecurity();
  const card = await microsoftCard();
  await userEvent.type(within(card).getByLabelText(/your qeos password/i), "my-password-1");
  await userEvent.click(within(card).getByRole("button", { name: "Link Microsoft account" }));
  expect(await within(card).findByRole("alert")).toHaveTextContent("already linked to a different user");
});

test("a linked account says so and offers no button", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  meIs({ has_password: true, linked_providers: ["microsoft"] });
  renderSecurity();
  const card = await microsoftCard();
  expect(within(card).getByText("Linked to Microsoft")).toBeInTheDocument();
  expect(within(card).queryByRole("button")).not.toBeInTheDocument();
});

test("without Microsoft configured and outside the mode there is no Microsoft card", async () => {
  meIs({ has_password: true, linked_providers: [], sso_only: false });
  renderSecurity();
  await screen.findByText(/two-factor authentication: off/i);
  expect(screen.queryByRole("heading", { name: "Microsoft account" })).not.toBeInTheDocument();
});

test("in SSO-only mode the Password card is hidden for a non-superuser", async () => {
  meIs({ has_password: true, linked_providers: ["microsoft"], sso_only: true, is_superuser: false });
  renderSecurity();
  await screen.findByRole("heading", { name: "Microsoft account" });
  expect(screen.queryByRole("heading", { name: "Password" })).not.toBeInTheDocument();
});

test("in SSO-only mode a superuser keeps the Password card", async () => {
  meIs({ has_password: true, linked_providers: [], sso_only: true, is_superuser: true });
  server.use(http.get("/api/v1/users/sso-readiness", () => HttpResponse.json({ active_users: 1, linked: 0, unlinked: [] })));
  renderSecurity();
  await screen.findByRole("heading", { name: "Microsoft account" });
  expect(screen.getByRole("heading", { name: "Password" })).toBeInTheDocument();
});
```

(The last test registers the readiness handler Task 11 will call, so it keeps passing after Task 11.)

- [ ] **Step 3: Run them to verify they fail**

Run: `npx vitest run src/pages/SecurityPage.test.tsx`
Expected: the new tests FAIL (`Unable to find role="heading" and name "Microsoft account"`); the existing ones PASS.

- [ ] **Step 4: API.** In `dashboard/src/api/auth.ts`, replace the `getMe` doc comment and function with:

```ts
/** The signed-in account (GET /users/me). `monitoring_url` is set only for a superuser while monitoring is on
 *  (ADR-027); `linked_providers`, `sso_only` and `has_password` drive the Security page (ADR-031). The newer
 *  fields are optional so an older server's answer still types. */
export interface Me {
  id: number;
  email: string;
  mfa_enabled: boolean;
  full_name?: string | null;
  monitoring_url?: string | null;
  is_superuser?: boolean;
  linked_providers?: string[];
  sso_only?: boolean;
  has_password?: boolean;
}

export function getMe(): Promise<Me> {
  return apiFetch("/api/v1/users/me");
}
```

and append:

```ts
/** Links the Microsoft identity behind `credential` to the signed-in account; an account with a password
 *  must confirm it. */
export async function linkMicrosoft(credential: string, currentPassword?: string): Promise<void> {
  const body: Record<string, string> = { credential };
  if (currentPassword) body.current_password = currentPassword;
  await apiFetch("/api/v1/users/me/link/microsoft", { method: "POST", body: JSON.stringify(body) });
}
```

- [ ] **Step 5: SecurityPage.** In `dashboard/src/pages/SecurityPage.tsx`:

1. Imports: change the auth import to `import { changePassword, getMe, linkMicrosoft, mfaConfirm, mfaDisable, mfaEnroll, type Me } from "../api/auth";` and add `import { getMicrosoftCredential, microsoftEnabled } from "../auth/ssoProviders";`.

2. Add this component above `export default function SecurityPage()`:

```tsx
/** Link a Microsoft work account (ADR-031). Every user in SSO-only mode; otherwise only when this build has
 *  Microsoft sign-in. */
function MicrosoftAccountCard({ me, onLinked }: { me: Me; onLinked: () => void }) {
  const linked = me.linked_providers?.includes("microsoft") ?? false;
  const needsPassword = me.has_password === true;
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const credential = await getMicrosoftCredential();
      await linkMicrosoft(credential, needsPassword ? password : undefined);
      setPassword("");
      setDone(true);
      onLinked();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form-stack" onSubmit={onSubmit}>
      <h3>Microsoft account</h3>
      {done && (
        <p className="success-note" role="status">
          <CircleCheck size={18} aria-hidden="true" />
          <span>Microsoft account linked. You can sign in with Microsoft from now on.</span>
        </p>
      )}
      {linked ? (
        <p className="mfa-status">
          <CircleCheck size={16} aria-hidden="true" /> <strong>Linked to Microsoft</strong>
        </p>
      ) : (
        <>
          <p className="muted">
            {me.sso_only ? "Sign-in here is through Microsoft. " : ""}
            Link your Microsoft work account to sign in with it.
          </p>
          {error != null && <ErrorBanner error={error} />}
          {needsPassword && (
            <TextField label="Your QEOS password" type="password" required autoComplete="current-password"
              value={password} onChange={setPassword} />
          )}
          {microsoftEnabled() ? (
            <div>
              <button className="primary" type="submit" disabled={busy}>
                {busy ? "Linking…" : "Link Microsoft account"}
              </button>
            </div>
          ) : (
            <p className="muted">This build has no Microsoft sign-in configured. Ask your administrator.</p>
          )}
        </>
      )}
    </form>
  );
}
```

3. In `SecurityPage`, replace the `known` state's loader with one that keeps the account:

```tsx
  const [known, setKnown] = useState<Known>("unknown");
  const [me, setMe] = useState<Me | null>(null);
  const loadStatus = () =>
    getMe().then((account) => {
      setMe(account);
      setKnown(account.mfa_enabled ? "on" : "off");
    }).catch(() => {
      // The line stays "unknown" rather than guessing
    });
```

4. Replace `<ChangePasswordCard />` in the returned JSX with:

```tsx
      {me !== null && (me.sso_only === true || microsoftEnabled()) && (
        <MicrosoftAccountCard me={me} onLinked={() => void loadStatus()} />
      )}
      {/* SSO-only mode: only superusers keep a password (ADR-031) */}
      {!(me?.sso_only === true && me.is_superuser !== true) && <ChangePasswordCard />}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run src/pages/SecurityPage.test.tsx`
Expected: all PASS.

- [ ] **Step 7: Docs.** `DESIGN.md`, after the SSO-only bullet, add:

```markdown
- **Security page, Microsoft account card** (ADR-031): shown to every user in SSO-only mode, otherwise only when the build has Microsoft sign-in. Linked: a status line with the check icon, "Linked to Microsoft". Not linked: one muted line, "Your QEOS password" only when the account has one, and the card's primary "Link Microsoft account" (MSAL popup, then the link request); success is a `success-note`, a refusal an `ErrorBanner`. In SSO-only mode the Password card is hidden for everyone but superusers.
```

`docs/SETUP.md` §3.8, step 2 of "Microsoft-only sign-in": replace `Ask everyone with a password account to link Microsoft (\`POST /api/v1/users/me/link/microsoft\`).` with `Ask everyone with a password account to link Microsoft: account menu → Security → Microsoft account → Link Microsoft account (they confirm their QEOS password, then sign in with Microsoft).`

- [ ] **Step 8: Lint, typecheck, commit**

Run: `npm run lint` and `npm run typecheck` — Expected: no errors.

```bash
git add dashboard/src/api/auth.ts dashboard/src/pages/SecurityPage.tsx dashboard/src/pages/SecurityPage.test.tsx DESIGN.md docs/SETUP.md
git commit -o dashboard/src/api/auth.ts dashboard/src/pages/SecurityPage.tsx dashboard/src/pages/SecurityPage.test.tsx DESIGN.md docs/SETUP.md -m "feat(dashboard): link a Microsoft account from the Security page; no Password card in SSO-only mode" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Security page — superuser "Microsoft-only sign-in" card; delivery-2 gate

**Files:**
- Modify: `dashboard/src/api/auth.ts` (`SsoReadinessEntry`, `SsoReadiness`, `getSsoReadiness`, `allowMicrosoftLink`)
- Modify: `dashboard/src/pages/SecurityPage.tsx`
- Test: `dashboard/src/pages/SecurityPage.test.tsx`
- Modify: `DESIGN.md`, `docs/SETUP.md` §3.8, `TODO.md`

**Interfaces:**
- Consumes: `GET /api/v1/users/sso-readiness`, `POST /api/v1/users/{id}/allow-microsoft-link` (Task 6); `me` state (Task 10).
- Produces: `getSsoReadiness(): Promise<SsoReadiness>`, `allowMicrosoftLink(userId: number): Promise<SsoReadinessEntry>`; component `SsoOnlyAdminCard({ ssoOnly }: { ssoOnly: boolean })` in `SecurityPage.tsx`.

- [ ] **Step 1: Invoke the `ui-ux-pro-max` skill before editing UI.** Review the superuser card: status line (On/Off with icon and text, never colour alone), the how-to-change sentence with `AUTH_SSO_ONLY` in `<code>`, the readiness sentence, the unlinked users as a `table.data` (User, Next sign-in) with a secondary "Allow link at next sign-in" button per row whose accessible name includes the email, "Allowed until <date>" once allowed, errors in `ErrorBanner`.

- [ ] **Step 2: Write the failing tests** — append to `dashboard/src/pages/SecurityPage.test.tsx`:

```tsx
const READINESS = {
  active_users: 15,
  linked: 12,
  unlinked: [
    { id: 7, email: "ana@example.com", full_name: "Ana", is_superuser: false, link_allowed_until: null },
    { id: 1, email: "root@example.com", full_name: null, is_superuser: true, link_allowed_until: "2026-10-21T10:00:00+00:00" },
  ],
};

test("a superuser sees the mode, the readiness and who has not linked", async () => {
  meIs({ is_superuser: true, sso_only: false, has_password: true, linked_providers: [] });
  server.use(http.get("/api/v1/users/sso-readiness", () => HttpResponse.json(READINESS)));
  renderSecurity();
  const card = (await screen.findByRole("heading", { name: "Microsoft-only sign-in" })).closest("section")!;
  expect(within(card).getByText("Microsoft-only sign-in: Off")).toBeInTheDocument();
  expect(within(card).getByText("AUTH_SSO_ONLY=true")).toBeInTheDocument();
  expect(await within(card).findByText("12 of 15 active users have linked Microsoft.")).toBeInTheDocument();
  expect(within(card).getByRole("button", { name: "Allow link at next sign-in for ana@example.com" })).toBeInTheDocument();
  const rootRow = within(card).getByText("root@example.com").closest("tr")!;
  expect(within(rootRow).getByText(/allowed until/i)).toBeInTheDocument();
  expect(within(rootRow).getByText(/superuser/i)).toBeInTheDocument();
});

test("allowing a link shows until when", async () => {
  meIs({ is_superuser: true, sso_only: true, has_password: true, linked_providers: ["microsoft"] });
  server.use(
    http.get("/api/v1/users/sso-readiness", () => HttpResponse.json(READINESS)),
    http.post("/api/v1/users/7/allow-microsoft-link", () => HttpResponse.json(
      { ...READINESS.unlinked[0], link_allowed_until: "2026-10-21T12:00:00+00:00" })),
  );
  renderSecurity();
  await userEvent.click(await screen.findByRole("button", { name: "Allow link at next sign-in for ana@example.com" }));
  const anaRow = (await screen.findByText("ana@example.com")).closest("tr")!;
  expect(await within(anaRow).findByText(/allowed until/i)).toBeInTheDocument();
  expect(screen.getByText("Microsoft-only sign-in: On")).toBeInTheDocument();
});

test("an allow refusal is shown in the card", async () => {
  meIs({ is_superuser: true, sso_only: true, has_password: true, linked_providers: ["microsoft"] });
  server.use(
    http.get("/api/v1/users/sso-readiness", () => HttpResponse.json(READINESS)),
    http.post("/api/v1/users/7/allow-microsoft-link", () =>
      HttpResponse.json({ detail: "User has already linked Microsoft" }, { status: 409 })),
  );
  renderSecurity();
  await userEvent.click(await screen.findByRole("button", { name: "Allow link at next sign-in for ana@example.com" }));
  const card = screen.getByRole("heading", { name: "Microsoft-only sign-in" }).closest("section")!;
  expect(await within(card).findByRole("alert")).toHaveTextContent("User has already linked Microsoft");
});

test("a non-superuser neither sees the card nor asks for readiness", async () => {
  let asked = false;
  meIs({ is_superuser: false, sso_only: true, has_password: false, linked_providers: ["microsoft"] });
  server.use(http.get("/api/v1/users/sso-readiness", () => {
    asked = true;
    return HttpResponse.json(READINESS);
  }));
  renderSecurity();
  await screen.findByRole("heading", { name: "Microsoft account" });
  expect(screen.queryByRole("heading", { name: "Microsoft-only sign-in" })).not.toBeInTheDocument();
  expect(asked).toBe(false);
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `npx vitest run src/pages/SecurityPage.test.tsx`
Expected: the 4 new tests FAIL (`Unable to find role="heading" and name "Microsoft-only sign-in"`).

- [ ] **Step 4: API.** Append to `dashboard/src/api/auth.ts`:

```ts
/** One active user without a Microsoft link (GET /users/sso-readiness, superusers; ADR-031). */
export interface SsoReadinessEntry {
  id: number;
  email: string;
  full_name: string | null;
  is_superuser: boolean;
  /** Set while a one-time link allowance is valid */
  link_allowed_until: string | null;
}

export interface SsoReadiness {
  active_users: number;
  linked: number;
  unlinked: SsoReadinessEntry[];
}

export function getSsoReadiness(): Promise<SsoReadiness> {
  return apiFetch("/api/v1/users/sso-readiness");
}

/** Lets that account link Microsoft at its next Microsoft sign-in, for 7 days. */
export function allowMicrosoftLink(userId: number): Promise<SsoReadinessEntry> {
  return apiFetch(`/api/v1/users/${userId}/allow-microsoft-link`, { method: "POST", body: "{}" });
}
```

- [ ] **Step 5: The card.** In `SecurityPage.tsx` extend the auth import with `allowMicrosoftLink, getSsoReadiness, type SsoReadiness`, and add above `export default function SecurityPage()`:

```tsx
function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Superusers only (ADR-031): whether the mode is on and how to change it (never from here, so a stolen
 *  session cannot switch it), who has linked Microsoft, and the one-time link allowance. */
function SsoOnlyAdminCard({ ssoOnly }: { ssoOnly: boolean }) {
  const [readiness, setReadiness] = useState<SsoReadiness | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [allowing, setAllowing] = useState<number | null>(null);

  useEffect(() => {
    getSsoReadiness().then(setReadiness).catch((err) => setError(err));
  }, []);

  async function onAllow(userId: number) {
    setError(null);
    setAllowing(userId);
    try {
      const entry = await allowMicrosoftLink(userId);
      setReadiness((current) => current && {
        ...current,
        unlinked: current.unlinked.map((user) => (user.id === userId ? entry : user)),
      });
    } catch (err) {
      setError(err);
    } finally {
      setAllowing(null);
    }
  }

  return (
    <section className="card" aria-labelledby="sso-only-heading">
      <h3 id="sso-only-heading">Microsoft-only sign-in</h3>
      <p className="mfa-status" role="status">
        {ssoOnly
          ? <><CircleCheck size={16} aria-hidden="true" /> <strong>Microsoft-only sign-in: On</strong></>
          : <><CircleSlash size={16} aria-hidden="true" /> <strong>Microsoft-only sign-in: Off</strong></>}
      </p>
      <p className="muted">
        {ssoOnly ? (
          <>Only superusers can still sign in with a password. To turn it off, set <code>AUTH_SSO_ONLY=false</code> in <code>.env</code> and restart auth-service.</>
        ) : (
          <>Link everyone first. Then set <code>AUTH_SSO_ONLY=true</code> in <code>.env</code> and restart auth-service: everyone who is not a superuser is signed out once.</>
        )}
      </p>
      {error != null && <ErrorBanner error={error} />}
      {readiness && (
        <>
          <p>{`${readiness.linked} of ${readiness.active_users} active users have linked Microsoft.`}</p>
          {readiness.unlinked.length > 0 && (
            <table className="data">
              <caption className="sr-only">Active users who have not linked Microsoft</caption>
              <thead>
                <tr>
                  <th scope="col">User</th>
                  <th scope="col">Next sign-in</th>
                </tr>
              </thead>
              <tbody>
                {readiness.unlinked.map((user) => (
                  <tr key={user.id}>
                    <td>
                      {user.full_name && <>{user.full_name}<br /></>}
                      <span className={user.full_name ? "muted" : undefined}>{user.email}</span>
                      {user.is_superuser && <span className="muted"> · superuser</span>}
                    </td>
                    <td>
                      {user.link_allowed_until ? (
                        `Allowed until ${formatDay(user.link_allowed_until)}`
                      ) : (
                        <button type="button" onClick={() => void onAllow(user.id)} disabled={allowing !== null}
                          aria-label={`Allow link at next sign-in for ${user.email}`}>
                          Allow link at next sign-in
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
```

and in the returned JSX of `SecurityPage`, after the two-factor `card` `</div>`, add:

```tsx
      {me?.is_superuser === true && <SsoOnlyAdminCard ssoOnly={me.sso_only === true} />}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run src/pages/SecurityPage.test.tsx`
Expected: all PASS.

- [ ] **Step 7: Docs.** `DESIGN.md`, after the Microsoft account card bullet, add:

```markdown
- **Security page, Microsoft-only sign-in card** (superusers, ADR-031): a status line "Microsoft-only sign-in: On/Off" (icon and text), one muted sentence on how to change it (`AUTH_SSO_ONLY` in `.env`, restart auth-service; never switched from the page), "12 of 15 active users have linked Microsoft.", then the unlinked users in a `table.data` (User, Next sign-in): a secondary "Allow link at next sign-in" button per row (accessible name includes the email) or "Allowed until <date>". Errors in `ErrorBanner`.
```

`docs/SETUP.md` §3.8, step 3 of "Microsoft-only sign-in": replace the readiness and allowance API mentions with: `Check readiness as a superuser: Security → Microsoft-only sign-in shows "N of M active users have linked Microsoft" and lists who has not. For someone who missed it, **Allow link at next sign-in** lets that account link at its next Microsoft sign-in, for 7 days (APIs: \`GET /api/v1/users/sso-readiness\`, \`POST /api/v1/users/{id}/allow-microsoft-link\`).`

`TODO.md` → `### Dashboard follow-ups`, after the SSO sign-in buttons line, add:

```markdown
- [x] SSO-only mode in the dashboard (ADR-031): sign-in page from `/auth/methods` with an administrator disclosure, recovery pages point to sign-in, Security page Microsoft link card, superuser readiness card with the one-time link allowance
```

- [ ] **Step 8: Delivery gate (local CI mirror for the dashboard)**

From `dashboard/`:
Run: `npm run lint` — Expected: no errors.
Run: `npm run typecheck` — Expected: no errors.
Run: `npm run build` — Expected: build succeeds.
Run: `npx vitest run --no-file-parallelism` — Expected: all PASS (re-run a file alone if it hits the known 15 s timeout under load; it must pass alone).
From the repo root: `python scripts/check_architecture_docs.py` — Expected: exit 0.

- [ ] **Step 9: Commit** (the user pushes delivery 2 after reviewing; do not push)

```bash
git add dashboard/src/api/auth.ts dashboard/src/pages/SecurityPage.tsx dashboard/src/pages/SecurityPage.test.tsx DESIGN.md docs/SETUP.md TODO.md
git commit -o dashboard/src/api/auth.ts dashboard/src/pages/SecurityPage.tsx dashboard/src/pages/SecurityPage.test.tsx DESIGN.md docs/SETUP.md TODO.md -m "feat(dashboard): superuser Microsoft-only sign-in card with readiness and link allowance" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage (self-review)

| Spec | Task |
|---|---|
| §3.1 settings, start-up refusal, unknown provider, no-superuser warning, compose forwarding | 1 |
| §3.2 `/auth/methods` | 2 |
| §3.3 password routes, login break-glass, identical 403, MFA, change-password, unlisted SSO routes, break-glass log | 3 |
| §3.4 `auth_mode_state`, migration 008, locked once-per-change revocation | 4 |
| §3.5 readiness (superusers included), allowance (7 days, logged, 404/409) | 6 |
| §3.5 allowance consumed at `/sso/microsoft`, 409 kept otherwise | 7 |
| §3.6 `linked_providers`, `sso_only` | 5 |
| §3.7 known limitation | 7 (SETUP, SECURITY, TODO) |
| §4.1 login page, fallback on failure; four pages' notice from methods and from 403 | 8, 9 |
| §4.2 Microsoft account card, Password card, superuser card | 10, 11 |
| §5 gateway smoke | 2 |
| §6 ADR-031, SETUP, SECURITY, README, PRODUCT, TODO, TECH SPEC, DESIGN, `.env.example` | 1–11 |

Decisions this plan takes where the spec is silent or the code differs (all reported to the user):
- `/users/me` also carries `has_password`, so the Security page asks for the current password only when the link endpoint will require it.
- `POST /auth/mfa/verify` refuses a non-superuser in the mode (a challenge issued in the five minutes before the switch), before the code is checked.
- A password set through `PUT /users/me` follows the `/auth/change-password` rule (superusers only in the mode).
- `/users/me/link/google` and `/sso/github` count as "SSO routes not in `AUTH_SSO_PROVIDERS`".
- An expired allowance reads as `null` in readiness; readiness entries carry `is_superuser` (the spec's JSON example omits it, its text requires it).
- Migration 008 seeds the state row; `apply_auth_mode` still handles a missing row.
- The login page shows the normal form while `/auth/methods` loads (no blank card; the request is small and same-origin).
