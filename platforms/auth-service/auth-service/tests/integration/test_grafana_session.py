"""Monitoring sign-in hand-off (monitoring spec §4, ADR-027): monitoring_url on /users/me,
POST /auth/grafana-session, and logout clearing the cookie."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.auth.config import settings
from src.auth.models.user import User
from src.auth.utils.grafana_session import (
    GRAFANA_AUDIENCE,
    GrafanaClaims,
    create_grafana_token,
    grafana_claims,
    grafana_user_id,
    password_version,
)
from src.auth.utils.tokens import create_access_token, decode_token, is_access_token

SESSION = "/api/v1/auth/grafana-session"
ME = "/api/v1/users/me"
LOGOUT = "/api/v1/auth/logout"
PWV = "0123456789abcdef"


@pytest.fixture
def monitoring(monkeypatch):
    monkeypatch.setattr(settings, "MONITORING_ENABLED", True)


def make_user(db, email="ops@example.com", superuser=True, active=True):
    row = User(email=email, hashed_password="x", is_active=active, is_superuser=superuser)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def bearer(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


def grafana_cookie(response):
    return next((c for c in response.headers.get_list("set-cookie") if c.startswith("qeos_grafana=")), None)


def cookie_value(cookie):
    return cookie.split(";")[0].split("=", 1)[1]


def test_me_offers_monitoring_to_a_superuser_while_it_is_on(client, db, monitoring):
    assert client.get(ME, headers=bearer(make_user(db))).json()["monitoring_url"] == "/grafana/"


def test_me_offers_nothing_to_other_users(client, db, monitoring):
    assert client.get(ME, headers=bearer(make_user(db, superuser=False))).json()["monitoring_url"] is None


def test_me_offers_nothing_while_monitoring_is_off(client, db):
    assert client.get(ME, headers=bearer(make_user(db))).json()["monitoring_url"] is None


def test_a_superuser_gets_an_8_hour_strict_cookie_for_grafana_only(client, db, monitoring):
    user = make_user(db)
    response = client.post(SESSION, headers=bearer(user))
    assert response.status_code == 200, response.text
    assert response.json() == {"url": "/grafana/"}
    cookie = grafana_cookie(response)
    assert cookie is not None
    attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert attributes == {"httponly", "secure", "samesite=strict", "path=/grafana", "max-age=28800"}, attributes
    token = cookie_value(cookie)
    assert grafana_user_id(token) == user.id
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], audience=GRAFANA_AUDIENCE)
    assert claims["exp"] - claims["iat"] == 8 * 3600 and claims["token_type"] == "grafana"
    assert claims["aud"] == "grafana" and claims["sub"] == str(user.id)
    assert claims["pwv"] == password_version(user)
    assert grafana_claims(token) == GrafanaClaims(user_id=user.id, password_version=password_version(user))


def test_a_user_who_is_not_a_superuser_gets_403_and_no_cookie(client, db, monitoring):
    response = client.post(SESSION, headers=bearer(make_user(db, superuser=False)))
    assert response.status_code == 403 and grafana_cookie(response) is None


def test_an_inactive_superuser_gets_403(client, db, monitoring):
    response = client.post(SESSION, headers=bearer(make_user(db, active=False)))
    assert response.status_code == 403 and grafana_cookie(response) is None


def test_403_while_monitoring_is_off(client, db):
    response = client.post(SESSION, headers=bearer(make_user(db)))
    assert response.status_code == 403 and grafana_cookie(response) is None


def test_without_a_token_401(client, monitoring):
    assert client.post(SESSION).status_code == 401


def test_the_grafana_token_is_not_an_access_token(client, db, monitoring):
    """Review Focus 3: the cookie's JWT carries aud=grafana and token_type, so the API refuses it."""
    user = make_user(db)
    token = cookie_value(grafana_cookie(client.post(SESSION, headers=bearer(user))))
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(ME, headers=headers).status_code == 401
    assert client.get("/api/v1/users/", headers=headers).status_code == 401  # superuser-only route
    assert client.post(SESSION, headers=headers).status_code == 401  # cannot mint itself a fresh one


def test_the_grafana_token_fails_access_token_decoding():
    """Two independent locks: PyJWT refuses `aud` when no audience is asked for (every service's
    decode_token), and `token_type` fails is_access_token even if that ever changed."""
    token = create_grafana_token(7, PWV)
    with pytest.raises(ValueError):
        decode_token(token)
    claims = jwt.decode(
        token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], options={"verify_aud": False}
    )
    assert not is_access_token(claims)


def test_an_access_token_is_not_a_grafana_token():
    """Review Focus 3, the other way (Task 16's check relies on this): no `aud`, so refused."""
    token = create_access_token({"sub": "7"})
    assert grafana_user_id(token) is None and grafana_claims(token) is None


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "garbage",
        # right audience and claims, wrong key
        jwt.encode({"sub": "7", "aud": "grafana", "token_type": "grafana", "pwv": PWV,
                    "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                   "a-different-key-of-at-least-32-bytes", algorithm="HS256"),
    ],
)
def test_grafana_claims_refuse_anything_else(token):
    assert grafana_user_id(token) is None and grafana_claims(token) is None


def test_grafana_claims_refuse_an_expired_token():
    assert grafana_claims(create_grafana_token(7, PWV, now=datetime.now(timezone.utc) - timedelta(hours=9))) is None


def test_grafana_claims_refuse_an_unsigned_token():
    token = jwt.encode(
        {"sub": "7", "aud": "grafana", "token_type": "grafana", "pwv": PWV,
         "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        None, algorithm="none",
    )
    assert grafana_claims(token) is None


def _signed(**overrides):
    now = datetime.now(timezone.utc)
    claims = {"sub": "7", "aud": "grafana", "token_type": "grafana", "pwv": PWV,
              "iat": now, "exp": now + timedelta(hours=1)}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def test_a_well_formed_token_is_accepted():
    """Control for the refusals below: _signed() alone passes."""
    assert grafana_claims(_signed()) == GrafanaClaims(user_id=7, password_version=PWV)
    assert grafana_user_id(_signed()) == 7


@pytest.mark.parametrize(
    "overrides",
    [
        {"token_type": None},
        {"token_type": "refresh"},
        {"pwv": None},
        {"pwv": "short"},
        {"pwv": 1234567890123456},
        {"sub": "not-a-number"},
        {"iat": None},
        {"aud": "something-else"},
    ],
)
def test_grafana_claims_refuse_a_malformed_token(overrides):
    assert grafana_claims(_signed(**overrides)) is None


def test_the_password_version_follows_the_password(client, db, register_and_verify):
    """Ruling: the cookie is bound to the password, so a change or reset invalidates it."""
    tokens = register_and_verify("ops2@example.com")
    user = db.query(User).filter(User.email == "ops2@example.com").one()
    before = password_version(user)
    assert len(before) == 16 and before == password_version(user)
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "securepassword123", "new_password": "anothersecret456"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert changed.status_code == 200, changed.text
    db.expire_all()
    after = db.query(User).filter(User.email == "ops2@example.com").one()
    assert password_version(after) != before


def test_a_passwordless_account_still_has_a_password_version(db):
    user = make_user(db)
    user.hashed_password = None
    assert len(password_version(user)) == 16


def assert_every_cookie_cleared(response):
    """Logout's promise on every path: the Grafana cookie and both refresh cookies are deleted."""
    cleared = {}
    for cookie in response.headers.get_list("set-cookie"):
        lowered = cookie.lower()
        if "max-age=0" in lowered:
            cleared[cookie.split("=", 1)[0]] = lowered
    assert set(cleared) >= {"qeos_grafana", "qeos_refresh", "qav_refresh"}, cleared
    assert "path=/grafana" in cleared["qeos_grafana"]
    assert "path=/api/v1/auth" in cleared["qeos_refresh"] and "path=/api/v1/auth" in cleared["qav_refresh"]


def refresh_works(client, refresh_token):
    client.cookies.clear()
    return client.post("/api/v1/auth/refresh-token", json={"refresh_token": refresh_token}).status_code == 200


def test_logout_clears_the_grafana_cookie(client, register_and_verify):
    tokens = register_and_verify("leaver@example.com")
    response = client.post(LOGOUT, json={}, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 200, response.text
    assert_every_cookie_cleared(response)


def test_logout_with_an_expired_access_token_still_clears_and_revokes(client, db, register_and_verify):
    """The dashboard tab idled past 60 minutes: logout gets 401, but the browser must still end up
    signed out of QEOS and Grafana, and the refresh session it presented is over."""
    tokens = register_and_verify("idle@example.com")
    user = db.query(User).filter(User.email == "idle@example.com").one()
    expired = create_access_token({"sub": str(user.id)}, expires_delta=timedelta(minutes=-1))
    client.cookies.clear()
    response = client.post(
        LOGOUT,
        json={},
        headers={"Authorization": f"Bearer {expired}", "Cookie": f"qeos_refresh={tokens['refresh_token']}"},
    )
    assert response.status_code == 401, response.text
    assert response.headers.get("www-authenticate") == "Bearer"
    assert_every_cookie_cleared(response)
    assert not refresh_works(client, tokens["refresh_token"])


def test_logout_without_an_access_token_or_body_still_clears(client, register_and_verify):
    tokens = register_and_verify("nobody@example.com")
    client.cookies.clear()
    response = client.post(LOGOUT, headers={"Cookie": f"qeos_refresh={tokens['refresh_token']}"})
    assert response.status_code == 401, response.text
    assert_every_cookie_cleared(response)
    assert not refresh_works(client, tokens["refresh_token"])


def test_logout_with_a_bad_refresh_token_still_clears(client, register_and_verify):
    tokens = register_and_verify("typo@example.com")
    response = client.post(
        LOGOUT,
        json={"refresh_token": "not-a-real-token"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid refresh token"}
    assert_every_cookie_cleared(response)


def test_logout_by_an_inactive_user_still_clears(client, db, register_and_verify):
    tokens = register_and_verify("gone@example.com")
    user = db.query(User).filter(User.email == "gone@example.com").one()
    user.is_active = False
    db.commit()
    response = client.post(LOGOUT, json={}, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 400 and response.json() == {"detail": "Inactive user"}
    assert_every_cookie_cleared(response)


def test_logout_with_a_grafana_token_as_bearer_is_401_and_clears(client, db, monitoring):
    user = make_user(db)
    token = cookie_value(grafana_cookie(client.post(SESSION, headers=bearer(user))))
    response = client.post(LOGOUT, json={}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert_every_cookie_cleared(response)
