"""SSO-only mode (ADR-031) at the HTTP boundary."""
import logging
from datetime import datetime, timedelta, timezone

import pyotp
import pytest

from src.auth.config import settings
from src.auth.models.oauth import OAuthAccount
from src.auth.models.pending_registration import PendingRegistration
from src.auth.models.user import User
from src.auth.service import mfa_service

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


LOGIN = "/api/v1/auth/login"
MFA_VERIFY = "/api/v1/auth/mfa/verify"
CHANGE = "/api/v1/auth/change-password"
MODE_LOGGER = "src.auth.service.auth_mode"

# The test client closes the shared session after each request, detaching the rows a test holds: ids and auth
# headers are taken before the first request, and rows are fetched again with db.get afterwards


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
    root_id = make_user("root@example.com", superuser=True).id
    with caplog.at_level(logging.WARNING, logger=MODE_LOGGER):
        response = client.post(LOGIN, json={"email": "root@example.com", "password": PASSWORD},
                               headers={"X-Forwarded-For": "203.0.113.7"})
    assert response.status_code == 200, response.text
    tokens = response.json()
    assert tokens["access_token"] and tokens["refresh_token"]
    lines = [r.getMessage() for r in caplog.records
             if r.levelno == logging.WARNING and "break-glass sign-in" in r.getMessage()]
    assert len(lines) == 1
    assert f"user_id={root_id}" in lines[0] and "email=root@example.com" in lines[0]
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
    root_id = root.id
    recovery = _enable_mfa(db, root)
    with caplog.at_level(logging.WARNING, logger=MODE_LOGGER):
        challenge = client.post(LOGIN, json={"email": "root@example.com", "password": PASSWORD})
    assert challenge.status_code == 200 and challenge.json()["mfa_required"] is True
    assert "access_token" not in challenge.json()
    assert "break-glass" not in caplog.text  # logged when the sign-in completes, not at the challenge
    with caplog.at_level(logging.WARNING, logger=MODE_LOGGER):
        verified = client.post(MFA_VERIFY, json={"mfa_token": challenge.json()["mfa_token"], "code": recovery[0]})
    assert verified.status_code == 200, verified.text
    assert "break-glass sign-in" in caplog.text and f"user_id={root_id}" in caplog.text
    assert recovery[0] not in caplog.text


def test_an_mfa_challenge_from_before_the_switch_lets_no_ordinary_user_in(client, db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    ann_id = ann.id
    recovery = _enable_mfa(db, ann)
    challenge = client.post(LOGIN, json={"email": "ann@example.com", "password": PASSWORD})
    assert challenge.json()["mfa_required"] is True  # issued while the mode was off

    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    response = client.post(MFA_VERIFY, json={"mfa_token": challenge.json()["mfa_token"], "code": recovery[0]})
    assert response.status_code == 403
    assert response.json() == SSO_ONLY_BODY
    assert response.headers.get("www-authenticate") is None
    # The recovery code was not spent by the refusal
    assert mfa_service.check_code(db, db.get(User, ann_id), recovery[0])


def test_change_password_is_for_superusers_only(client, sso_only, make_user, auth_header):
    ann_header = auth_header(make_user("ann@example.com"))
    root_header = auth_header(make_user("root@example.com", superuser=True))
    body = {"current_password": PASSWORD, "new_password": "another-password-9"}
    refused = client.post(CHANGE, json=body, headers=ann_header)
    assert refused.status_code == 403 and refused.json() == SSO_ONLY_BODY
    assert client.post(CHANGE, json=body, headers=root_header).status_code == 200


def test_a_password_cannot_be_set_through_the_profile_either(client, sso_only, make_user, auth_header):
    ann_header = auth_header(make_user("ann@example.com"))
    refused = client.put("/api/v1/users/me", json={"password": "another-password-9", "current_password": PASSWORD},
                         headers=ann_header)
    assert refused.status_code == 403 and refused.json() == SSO_ONLY_BODY
    assert client.put("/api/v1/users/me", json={"full_name": "Ann"}, headers=ann_header).status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/sso/google", "/api/v1/sso/github", "/api/v1/users/me/link/google"])
def test_providers_the_mode_does_not_list_are_refused(client, sso_only, make_user, auth_header, path):
    ann_header = auth_header(make_user("ann@example.com"))
    response = client.post(path, json={"credential": "x"}, headers=ann_header)
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


ME = "/api/v1/users/me"


def test_users_me_reports_links_the_mode_and_the_password(client, db, make_user, auth_header, monkeypatch):
    ann = make_user("ann@example.com")
    ann_id = ann.id
    header = auth_header(ann)
    db.add_all([
        OAuthAccount(user_id=ann_id, provider="microsoft", provider_user_id="tenant:oid"),
        OAuthAccount(user_id=ann_id, provider="google", provider_user_id="g-1"),
    ])
    db.commit()

    me = client.get(ME, headers=header).json()
    assert me["linked_providers"] == ["google", "microsoft"]
    assert me["sso_only"] is False and me["has_password"] is True

    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    assert client.get(ME, headers=header).json()["sso_only"] is True


def test_users_me_for_a_passwordless_unlinked_account(client, make_user, auth_header):
    bob = make_user("bob@example.com", password=None)
    me = client.get(ME, headers=auth_header(bob)).json()
    assert me["linked_providers"] == [] and me["has_password"] is False
    assert "hashed_password" not in me


READINESS = "/api/v1/users/sso-readiness"


def allow_url(user_id):
    return f"/api/v1/users/{user_id}/allow-microsoft-link"


def _link_microsoft(db, user_id, oid="oid-1"):
    db.add(OAuthAccount(user_id=user_id, provider="microsoft", provider_user_id=f"tenant:{oid}"))
    db.commit()


def _aware(value):
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def test_readiness_counts_active_users_and_lists_the_unlinked(client, db, make_user, auth_header):
    root = make_user("root@example.com", superuser=True)
    ann = make_user("ann@example.com")
    bob = make_user("bob@example.com")
    make_user("gone@example.com", active=False)
    root_id, ann_id, headers = root.id, ann.id, auth_header(root)
    _link_microsoft(db, bob.id)
    db.add(OAuthAccount(user_id=ann_id, provider="google", provider_user_id="g-1"))  # not a Microsoft link
    db.commit()

    # Declared before /users/{user_id}: otherwise "sso-readiness" is parsed as an id and this is a 422
    response = client.get(READINESS, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["active_users"] == 3 and body["linked"] == 1
    assert body["unlinked"] == [
        {"id": ann_id, "email": "ann@example.com", "full_name": None, "is_superuser": False, "link_allowed_until": None},
        {"id": root_id, "email": "root@example.com", "full_name": None, "is_superuser": True, "link_allowed_until": None},
    ]


def test_readiness_and_allow_are_for_superusers_only(client, db, make_user, auth_header):
    ann = make_user("ann@example.com")
    ann_id, headers = ann.id, auth_header(ann)
    assert client.get(READINESS, headers=headers).status_code == 403
    assert client.get(READINESS).status_code == 401
    assert client.post(allow_url(ann_id), headers=headers).status_code == 403
    assert db.get(User, ann_id).microsoft_link_allowed_until is None


def test_allowing_a_link_sets_seven_days_and_is_logged(client, db, make_user, auth_header, caplog):
    root = make_user("root@example.com", superuser=True)
    ann = make_user("ann@example.com")
    ann_id, headers = ann.id, auth_header(root)
    before = datetime.now(timezone.utc)
    with caplog.at_level(logging.WARNING, logger="src.auth.service.sso_readiness"):
        response = client.post(allow_url(ann_id), headers=headers)
    assert response.status_code == 200, response.text
    entry = response.json()
    assert (entry["id"], entry["email"], entry["is_superuser"]) == (ann_id, "ann@example.com", False)
    until = _aware(entry["link_allowed_until"])
    assert timedelta(days=7) - timedelta(minutes=1) < until - before < timedelta(days=7) + timedelta(minutes=1)
    assert "Microsoft link allowed" in caplog.text
    assert "root@example.com" in caplog.text and "ann@example.com" in caplog.text and until.date().isoformat() in caplog.text

    listed = client.get(READINESS, headers=headers).json()["unlinked"]
    assert next(u for u in listed if u["id"] == ann_id)["link_allowed_until"] is not None


def test_an_expired_allowance_reads_as_none(client, db, make_user, auth_header):
    root = make_user("root@example.com", superuser=True)
    ann = make_user("ann@example.com")
    ann_id, headers = ann.id, auth_header(root)
    ann.microsoft_link_allowed_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    listed = client.get(READINESS, headers=headers).json()["unlinked"]
    assert next(u for u in listed if u["id"] == ann_id)["link_allowed_until"] is None


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
    ann_id, headers = ann.id, auth_header(root)
    if case == "linked":
        _link_microsoft(db, ann_id)
    response = client.post(allow_url(ann_id), headers=headers)
    assert response.status_code == 409
    assert response.json() == {"detail": detail}
    assert db.get(User, ann_id).microsoft_link_allowed_until is None
