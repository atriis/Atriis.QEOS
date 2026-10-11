"""GET /internal/v1/grafana-check: NGINX's auth_request for /grafana/ (monitoring spec §4, Rulings 1-2).
The cookie is the credential; the user is re-checked on every request, so a demotion, deactivation or
password change cuts access at once."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.auth.config import settings
from src.auth.models.user import User
from src.auth.utils.grafana_session import create_grafana_token, password_version
from src.auth.utils.tokens import create_access_token

CHECK = "/internal/v1/grafana-check"


@pytest.fixture
def monitoring(monkeypatch):
    monkeypatch.setattr(settings, "MONITORING_ENABLED", True)


@pytest.fixture
def superuser(db):
    row = User(email="ops@example.com", hashed_password="x", is_active=True, is_superuser=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mint(user, now=None):
    return create_grafana_token(user.id, password_version(user), now=now)


def check(client, token):
    return client.get(CHECK, headers={"Cookie": f"qeos_grafana={token}"})


def assert_refused(response):
    assert response.status_code == 401, response.text
    assert "x-qeos-user-email" not in response.headers
    # A Basic challenge through auth_request would pop up a browser dialog
    assert "www-authenticate" not in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_a_valid_cookie_names_the_user_for_grafana(client, monitoring, superuser):
    response = check(client, mint(superuser))
    assert response.status_code == 200, response.text
    assert response.headers["x-qeos-user-email"] == "ops@example.com"
    assert response.headers["cache-control"] == "no-store"
    assert "ops@example.com" not in response.text


def test_no_cookie_is_401(client, monitoring, superuser):
    assert_refused(client.get(CHECK))


def test_garbage_is_401(client, monitoring, superuser):
    assert_refused(check(client, "not-a-jwt"))


def test_an_expired_cookie_is_401(client, monitoring, superuser):
    old = datetime.now(timezone.utc) - timedelta(hours=9)
    assert_refused(check(client, mint(superuser, now=old)))


def test_a_token_for_another_audience_is_401(client, monitoring, superuser):
    now = datetime.now(timezone.utc)
    other = jwt.encode({"sub": str(superuser.id), "aud": "other", "token_type": "grafana",
                        "pwv": password_version(superuser), "iat": now, "exp": now + timedelta(hours=1)},
                       settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    assert_refused(check(client, other))


def test_a_token_signed_with_another_key_is_401(client, monitoring, superuser):
    now = datetime.now(timezone.utc)
    forged = jwt.encode({"sub": str(superuser.id), "aud": "grafana", "token_type": "grafana",
                         "pwv": password_version(superuser), "iat": now, "exp": now + timedelta(hours=1)},
                        "not-the-key-but-long-enough-for-hs256", algorithm="HS256")
    assert_refused(check(client, forged))


def test_an_access_token_planted_as_the_cookie_is_401(client, monitoring, superuser):
    """Review Focus 3."""
    assert_refused(check(client, create_access_token({"sub": str(superuser.id)})))


def test_a_bearer_access_token_is_no_substitute_for_the_cookie(client, monitoring, superuser):
    token = create_access_token({"sub": str(superuser.id)})
    assert_refused(client.get(CHECK, headers={"Authorization": f"Bearer {token}"}))


def test_a_demoted_user_is_cut_off_at_once(client, db, monitoring, superuser):
    token = mint(superuser)
    superuser.is_superuser = False
    db.commit()
    assert_refused(check(client, token))


def test_a_deactivated_user_is_cut_off_at_once(client, db, monitoring, superuser):
    token = mint(superuser)
    superuser.is_active = False
    db.commit()
    assert_refused(check(client, token))


def test_a_password_change_after_mint_is_401(client, db, monitoring, superuser):
    token = mint(superuser)
    superuser.hashed_password = "y"
    db.commit()
    assert_refused(check(client, token))


def test_nothing_passes_while_monitoring_is_off(client, superuser):
    assert_refused(check(client, mint(superuser)))


def test_a_deleted_user_is_401(client, db, monitoring, superuser):
    token = mint(superuser)
    db.delete(superuser)
    db.commit()
    assert_refused(check(client, token))
