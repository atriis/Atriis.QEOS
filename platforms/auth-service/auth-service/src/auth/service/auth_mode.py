"""SSO-only mode (ADR-031, docs/superpowers/specs/2026-10-14-sso-only-mode-design.md).

Settings: AUTH_SSO_ONLY, AUTH_SSO_PROVIDERS. Messages name a setting, never its value: client ids and
tenant ids stay out of the log.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from src.auth.config import settings
from src.auth.models.user import User

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ("microsoft", "google")
PROVIDER_LABELS = {"microsoft": "Microsoft", "google": "Google"}
_NOT_CONFIGURED = {"google": "Google is not configured: set GOOGLE_CLIENT_ID"}


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


def _not_configured(name: str) -> str:
    """Names only the settings that are actually missing."""
    if name != "microsoft":
        return _NOT_CONFIGURED[name]
    missing = []
    if not settings.AZURE_CLIENT_ID:
        missing.append("AZURE_CLIENT_ID")
    if not settings.azure_allowed_tenants:
        missing.append("AZURE_ALLOWED_TENANTS (or AZURE_TENANT_ID)")
    return "Microsoft is not configured: set " + " and ".join(missing)


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
            problems.append(_not_configured(name))
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
