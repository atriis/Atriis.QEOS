"""Monitoring sign-in hand-off (monitoring spec §4, ADR-027): monitoring_url on /users/me,
POST /auth/grafana-session, and logout clearing the cookie."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.auth.config import settings
from src.auth.models.user import User
from src.auth.utils.grafana_session import GRAFANA_AUDIENCE, create_grafana_token, grafana_user_id
from src.auth.utils.tokens import create_access_token, decode_token, is_access_token

SESSION = "/api/v1/auth/grafana-session"
ME = "/api/v1/users/me"


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
    token = create_grafana_token(7)
    with pytest.raises(ValueError):
        decode_token(token)
    claims = jwt.decode(
        token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], options={"verify_aud": False}
    )
    assert not is_access_token(claims)


def test_an_access_token_is_not_a_grafana_token():
    """Review Focus 3, the other way (Task 16's check relies on this): no `aud`, so refused."""
    assert grafana_user_id(create_access_token({"sub": "7"})) is None


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "garbage",
        # right audience, wrong key
        jwt.encode({"sub": "7", "aud": "grafana", "token_type": "grafana",
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "a-different-key-of-at-least-32-bytes", algorithm="HS256"),
    ],
)
def test_grafana_user_id_refuses_anything_else(token):
    assert grafana_user_id(token) is None


def test_grafana_user_id_refuses_an_expired_token():
    assert grafana_user_id(create_grafana_token(7, now=datetime.now(timezone.utc) - timedelta(hours=9))) is None


def test_grafana_user_id_refuses_a_grafana_audience_without_its_token_type():
    token = jwt.encode(
        {"sub": "7", "aud": "grafana", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )
    assert grafana_user_id(token) is None


def test_grafana_user_id_refuses_an_unsigned_token():
    token = jwt.encode(
        {"sub": "7", "aud": "grafana", "token_type": "grafana",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        None, algorithm="none",
    )
    assert grafana_user_id(token) is None


def test_logout_clears_the_grafana_cookie(client, register_and_verify):
    tokens = register_and_verify("leaver@example.com")
    response = client.post("/api/v1/auth/logout", json={}, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 200, response.text
    cookie = grafana_cookie(response)
    assert cookie is not None
    lowered = cookie.lower()
    assert "max-age=0" in lowered and "path=/grafana" in lowered
    # the refresh cookies are still cleared alongside it
    assert any(c.startswith("qeos_refresh=") for c in response.headers.get_list("set-cookie"))
