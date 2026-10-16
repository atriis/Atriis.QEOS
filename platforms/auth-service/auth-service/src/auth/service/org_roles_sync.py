"""Push a Microsoft sign-in's Entra app roles to organization-service (ADR-033). Best effort: a failure never fails
the sign-in, the link or the refresh; a pending push is retried at the next token refresh."""
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from src.auth.config import settings
from src.auth.models.oauth import OAuthAccount

logger = logging.getLogger(__name__)

ORG_INTERNAL_USERNAME = "auth-service"
TIMEOUT_SECONDS = 5.0


def _post(url: str, auth: tuple[str, str], body: dict) -> int:
    """The one network call; tests replace it."""
    return httpx.post(url, auth=auth, json=body, timeout=TIMEOUT_SECONDS).status_code


def warn_if_unconfigured() -> None:
    if not settings.ORGANIZATION_INTERNAL_API_PASSWORD:
        logger.warning("Entra app roles are not applied: ORGANIZATION_INTERNAL_API_PASSWORD is not set")


def _push(db: Session, link: OAuthAccount) -> bool:
    if not settings.ORGANIZATION_INTERNAL_API_PASSWORD:
        return False
    url = f"{settings.ORGANIZATION_SERVICE_URL.rstrip('/')}/internal/v1/sso-roles"
    body = {"user_id": link.user_id, "roles": list(link.sso_roles or [])}
    try:
        status = _post(url, (ORG_INTERNAL_USERNAME, settings.ORGANIZATION_INTERNAL_API_PASSWORD), body)
    except Exception as exc:  # connection refused, timeout, DNS: never the sign-in's problem
        logger.warning("entra role sync deferred: user=%s reason=%s", link.user_id, type(exc).__name__)
        return False
    if not 200 <= status < 300:
        logger.warning("entra role sync deferred: user=%s reason=HTTP %s", link.user_id, status)
        return False
    link.sso_roles_synced_at = datetime.now(timezone.utc)
    db.commit()
    return True


def record_and_push(db: Session, link: Optional[OAuthAccount], roles: list[str]) -> bool:
    """Store the roles a Microsoft sign-in (or link) carried, then push them."""
    if link is None:
        return False
    link.sso_roles = list(roles)
    link.sso_roles_at = datetime.now(timezone.utc)
    db.commit()
    return _push(db, link)


def retry_pending(db: Session, user_id: int) -> None:
    """At a token refresh: push again when the last roles never reached organization-service. Never raises."""
    try:
        link = db.query(OAuthAccount).filter(
            OAuthAccount.user_id == user_id, OAuthAccount.provider == "microsoft").first()
        if link is None or link.sso_roles_at is None:
            return
        synced = link.sso_roles_synced_at
        if synced is not None and _aware(synced) >= _aware(link.sso_roles_at):
            return
        _push(db, link)
    except Exception as exc:  # a database error here must not fail the refresh
        db.rollback()
        logger.warning("entra role sync deferred: user=%s reason=%s", user_id, type(exc).__name__)


def _aware(value: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes for timezone=True columns
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
