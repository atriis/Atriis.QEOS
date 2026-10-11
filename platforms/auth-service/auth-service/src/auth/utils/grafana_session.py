"""The short-lived cookie that lets a QEOS superuser into Grafana at /grafana/ (monitoring spec §4, ADR-027).

A plain browser visit to /grafana/ carries neither the refresh cookie (scoped to /api/v1/auth) nor the
access token (in the dashboard's memory), so POST /auth/grafana-session hands over this cookie
explicitly. It is a JWT with its own audience: PyJWT refuses a token carrying `aud` when no audience is
asked for, and `token_type` fails is_access_token, so it never works as an access token; an access
token has no `aud`, so it never works here. The gateway's auth_request asks
GET /internal/v1/grafana-check on every /grafana/ request, which also re-checks the user.

The token also carries `pwv`, a short keyed digest of the user's password hash at mint time
(password_version). A password change or reset changes the hash, so the check refuses every Grafana
cookie minted before it. The digest is keyed with SECRET_KEY so the token reveals nothing about the hash."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import NamedTuple, Optional

import jwt
from fastapi import Response

from src.auth.config import settings

GRAFANA_COOKIE = "qeos_grafana"
GRAFANA_COOKIE_PATH = "/grafana"
GRAFANA_AUDIENCE = "grafana"
GRAFANA_TOKEN_TYPE = "grafana"
GRAFANA_SESSION_HOURS = 8
MONITORING_URL = "/grafana/"
PASSWORD_VERSION_LENGTH = 16


class GrafanaClaims(NamedTuple):
    user_id: int
    password_version: str


def password_version(user) -> str:
    """HMAC-SHA256(SECRET_KEY, hashed_password or "") in hex, first 16 characters. Changes whenever
    the password does; the same for every passwordless (SSO-only) account state."""
    digest = hmac.new(
        settings.SECRET_KEY.encode(), (user.hashed_password or "").encode(), hashlib.sha256
    ).hexdigest()
    return digest[:PASSWORD_VERSION_LENGTH]


def create_grafana_token(user_id: int, pwv: str, now: Optional[datetime] = None) -> str:
    issued = now or datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "aud": GRAFANA_AUDIENCE,
        "token_type": GRAFANA_TOKEN_TYPE,
        "pwv": pwv,
        "iat": issued,
        "exp": issued + timedelta(hours=GRAFANA_SESSION_HOURS),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def grafana_claims(token: Optional[str]) -> Optional[GrafanaClaims]:
    """The user id and password version a valid Grafana token carries; None for anything else (bad
    signature, expired, wrong audience, missing claims, an access token, garbage). It says nothing
    about whether that user may still use Grafana: the caller must re-load the user, check
    is_active and is_superuser, and compare password_version(user) with
    hmac.compare_digest."""
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience=GRAFANA_AUDIENCE,
            options={"require": ["exp", "iat", "sub", "aud", "pwv"]},
        )
        if claims.get("token_type") != GRAFANA_TOKEN_TYPE:
            return None
        pwv = claims["pwv"]
        if not isinstance(pwv, str) or len(pwv) != PASSWORD_VERSION_LENGTH:
            return None
        return GrafanaClaims(user_id=int(claims["sub"]), password_version=pwv)
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def grafana_user_id(token: Optional[str]) -> Optional[int]:
    """grafana_claims' user id alone. Not enough for an access decision: see grafana_claims."""
    found = grafana_claims(token)
    return found.user_id if found else None


def set_grafana_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        GRAFANA_COOKIE,
        token,
        max_age=GRAFANA_SESSION_HOURS * 3600,
        httponly=True,
        secure=True,
        samesite="strict",
        path=GRAFANA_COOKIE_PATH,
    )


def clear_grafana_cookie(response: Response) -> None:
    response.delete_cookie(GRAFANA_COOKIE, path=GRAFANA_COOKIE_PATH, secure=True, httponly=True, samesite="strict")
