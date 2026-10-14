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
