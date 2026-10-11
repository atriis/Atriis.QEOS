"""The short-lived cookie that lets a QEOS superuser into Grafana at /grafana/ (monitoring spec §4, ADR-027).

A plain browser visit to /grafana/ carries neither the refresh cookie (scoped to /api/v1/auth) nor the
access token (in the dashboard's memory), so POST /auth/grafana-session hands over this cookie
explicitly. It is a JWT with its own audience: PyJWT refuses a token carrying `aud` when no audience is
asked for, and `token_type` fails is_access_token, so it never works as an access token; an access
token has no `aud`, so it never works here. The gateway's auth_request asks
GET /internal/v1/grafana-check on every /grafana/ request, which also re-checks the user."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Response

from src.auth.config import settings

GRAFANA_COOKIE = "qeos_grafana"
GRAFANA_COOKIE_PATH = "/grafana"
GRAFANA_AUDIENCE = "grafana"
GRAFANA_TOKEN_TYPE = "grafana"
GRAFANA_SESSION_HOURS = 8
MONITORING_URL = "/grafana/"


def create_grafana_token(user_id: int, now: Optional[datetime] = None) -> str:
    issued = now or datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "aud": GRAFANA_AUDIENCE,
        "token_type": GRAFANA_TOKEN_TYPE,
        "iat": issued,
        "exp": issued + timedelta(hours=GRAFANA_SESSION_HOURS),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def grafana_user_id(token: Optional[str]) -> Optional[int]:
    """The user a valid Grafana token names; None for anything else (bad signature, expired, wrong
    audience, an access token, garbage). It says nothing about whether that user may still use
    Grafana: the caller must re-load the user and check is_active and is_superuser."""
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience=GRAFANA_AUDIENCE,
            options={"require": ["exp", "iat", "sub", "aud"]},
        )
        if claims.get("token_type") != GRAFANA_TOKEN_TYPE:
            return None
        return int(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


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
