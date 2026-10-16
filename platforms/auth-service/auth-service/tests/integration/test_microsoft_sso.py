"""Microsoft (Entra ID) SSO. A locally generated RSA key stands in for Microsoft's, so the full
verification path runs offline, as the Google tests do."""
import logging
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClientConnectionError

from src.auth.config import settings
from src.auth.models.oauth import OAuthAccount
from src.auth.models.user import User
from src.auth.service import sso_service

SIGN_IN = "/api/v1/sso/microsoft"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER_TENANT = "99999999-8888-7777-6666-555555555555"
OID = "00000000-0000-0000-0000-000000000001"
DROP = object()


@pytest.fixture
def microsoft_key(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class _StubKey:
        key = private_key.public_key()

    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", f"{TENANT},{OTHER_TENANT}")
    monkeypatch.setattr(settings, "AZURE_TENANT_ID", "")
    monkeypatch.setattr(sso_service._microsoft_jwks_client, "get_signing_key_from_jwt", lambda token: _StubKey())
    return private_key


def ms_token(private_key, key=None, algorithm="RS256", **overrides):
    now = datetime.now(timezone.utc)
    tid = overrides.pop("tid", TENANT)
    claims = {
        "ver": "2.0",
        "iss": f"https://login.microsoftonline.com/{TENANT if tid is DROP else tid}/v2.0",
        "aud": CLIENT_ID,
        "tid": tid,
        "oid": OID,
        "sub": "pairwise-subject",
        "email": "ann@example.com",
        "preferred_username": "ann@example.com",
        "name": "Ann Example",
        "nbf": now - timedelta(minutes=1),
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not DROP}
    return pyjwt.encode(claims, private_key if key is None else key, algorithm=algorithm)


def sign_in(client, token):
    return client.post(SIGN_IN, json={"credential": token})


def test_a_valid_token_signs_in_and_creates_a_passwordless_user(client, db, microsoft_key):
    response = sign_in(client, ms_token(microsoft_key))

    assert response.status_code == 200, response.text
    assert response.json()["access_token"] and response.json()["refresh_token"]
    user = db.query(User).filter(User.email == "ann@example.com").one()
    assert user.hashed_password is None and user.full_name == "Ann Example"
    link = db.query(OAuthAccount).filter(OAuthAccount.user_id == user.id).one()
    assert (link.provider, link.provider_user_id) == ("microsoft", f"{TENANT}:{OID}")


@pytest.mark.xfail(strict=True, reason="Task 6 stores the roles")
def test_the_tokens_app_roles_are_stored_on_the_link(client, db, microsoft_key):
    assert sign_in(client, ms_token(microsoft_key, roles=["QEOS.Member", "QEOS.Viewer"])).status_code == 200
    link = db.query(OAuthAccount).one()
    assert link.sso_roles == ["QEOS.Member", "QEOS.Viewer"]
    assert link.sso_roles_at is not None


def test_a_returning_user_is_found_by_identity_even_if_the_email_changed(client, db, microsoft_key):
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200
    again = sign_in(client, ms_token(microsoft_key, email="ann.renamed@example.com"))

    assert again.status_code == 200, again.text
    assert db.query(User).count() == 1
    assert db.query(User).one().email == "ann@example.com"  # not written back


@pytest.mark.parametrize("case, overrides", [
    ("wrong_audience", {"aud": "someone-elses-app"}),
    ("expired", {"exp": datetime.now(timezone.utc) - timedelta(minutes=5)}),
    ("not_yet_valid", {"nbf": datetime.now(timezone.utc) + timedelta(minutes=10)}),
    ("tenant_not_allowed", {"tid": "12345678-0000-0000-0000-000000000000"}),
    ("iss_other_tenant", {"iss": f"https://login.microsoftonline.com/{OTHER_TENANT}/v2.0"}),
    ("v1_token", {"ver": "1.0"}),
    ("v1_issuer", {"iss": f"https://sts.windows.net/{TENANT}/"}),
    ("missing_tid", {"tid": DROP}),
    ("missing_oid", {"oid": DROP}),
    ("missing_nbf", {"nbf": DROP}),
])
def test_refused_tokens(client, db, microsoft_key, case, overrides):
    response = sign_in(client, ms_token(microsoft_key, **overrides))

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid Microsoft token"}
    assert db.query(User).count() == 0


@pytest.mark.parametrize("case", ["hs256", "none", "other_key", "garbage"])
def test_forged_tokens_are_refused(client, db, microsoft_key, case):
    if case == "hs256":
        token = ms_token(microsoft_key, key="a-shared-secret", algorithm="HS256")
    elif case == "none":
        token = pyjwt.encode({"tid": TENANT, "oid": OID, "aud": CLIENT_ID}, None, algorithm="none")
    elif case == "other_key":
        token = ms_token(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    else:
        token = "not-a-jwt"

    response = sign_in(client, token)
    assert response.status_code == 400
    assert db.query(User).count() == 0


def test_a_refused_tenant_is_logged(client, microsoft_key, caplog):
    stranger = "12345678-0000-0000-0000-000000000000"
    with caplog.at_level(logging.WARNING, logger="src.auth.service.sso_service"):
        sign_in(client, ms_token(microsoft_key, tid=stranger))
    assert stranger in caplog.text


def test_allowed_tenants_are_case_insensitive(client, monkeypatch, microsoft_key):
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", TENANT.upper())
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200


def test_azure_tenant_id_is_the_fallback_allowlist(client, monkeypatch, microsoft_key):
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", "")
    monkeypatch.setattr(settings, "AZURE_TENANT_ID", TENANT)
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200


@pytest.mark.parametrize("setting", ["AZURE_CLIENT_ID", "AZURE_ALLOWED_TENANTS"])
def test_not_configured_is_503(client, monkeypatch, microsoft_key, setting):
    monkeypatch.setattr(settings, setting, "")
    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 503
    assert response.json() == {"detail": "Microsoft SSO is not configured"}


def test_microsoft_key_outage_is_503(client, monkeypatch, microsoft_key):
    def unreachable(token):
        raise PyJWKClientConnectionError("Fail to fetch data from the url")

    monkeypatch.setattr(sso_service._microsoft_jwks_client, "get_signing_key_from_jwt", unreachable)
    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 503
    assert response.json() == {"detail": "Microsoft sign-in is temporarily unavailable"}


def test_preferred_username_is_used_without_an_email_claim(client, db, microsoft_key):
    response = sign_in(client, ms_token(microsoft_key, email=DROP, preferred_username="ann@example.com"))
    assert response.status_code == 200, response.text
    assert db.query(User).one().email == "ann@example.com"


@pytest.mark.parametrize("overrides", [
    {"email": DROP, "preferred_username": DROP},
    {"email": DROP, "preferred_username": "ann"},
    {"email": "not an email", "preferred_username": DROP},
    # Passes a naive check but not the user model's EmailStr: used to be a 500
    {"email": "ann@corp.local", "preferred_username": DROP},
])
def test_an_account_without_an_email_is_refused(client, db, microsoft_key, overrides):
    response = sign_in(client, ms_token(microsoft_key, **overrides))
    assert response.status_code == 400
    assert response.json() == {"detail": "Microsoft account has no email address"}
    assert db.query(User).count() == 0


def test_an_existing_account_with_the_email_is_not_taken_over(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    response = sign_in(client, ms_token(microsoft_key))

    assert response.status_code == 409
    assert "/api/v1/users/me/link/microsoft" in response.json()["detail"]
    assert db.query(OAuthAccount).count() == 0


def test_the_same_oid_in_another_tenant_is_another_identity(client, db, microsoft_key):
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200
    other = sign_in(client, ms_token(microsoft_key, tid=OTHER_TENANT, preferred_username="ann@other.example.com"))

    assert other.status_code == 200, other.text
    ids = sorted(link.provider_user_id for link in db.query(OAuthAccount))
    assert ids == sorted([f"{TENANT}:{OID}", f"{OTHER_TENANT}:{OID}"])
    assert db.query(User).count() == 2


def test_an_inactive_user_is_refused(client, db, microsoft_key):
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200
    user = db.query(User).one()
    user.is_active = False
    db.commit()

    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 400
    assert response.json() == {"detail": "Inactive user"}


def test_the_old_azure_route_is_gone(client):
    assert client.post("/api/v1/sso/azure", json={"code": "x", "tenant_id": "y"}).status_code == 404


LINK = "/api/v1/users/me/link/microsoft"


def bearer(login):
    return {"Authorization": f"Bearer {login['access_token']}"}


def test_link_microsoft_to_a_password_account(client, db, microsoft_key, register_and_verify):
    login = register_and_verify("bob@example.com")
    linked = client.post(LINK, json={"credential": ms_token(microsoft_key), "current_password": "securepassword123"},
                         headers=bearer(login))

    assert linked.status_code == 200, linked.text
    assert db.query(OAuthAccount).filter(OAuthAccount.user_id == linked.json()["id"]).one().provider == "microsoft"
    # That Microsoft identity now signs in to this account, whatever its email says
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200
    assert db.query(User).count() == 1


@pytest.mark.parametrize("password", [None, "wrong-password"])
def test_link_microsoft_requires_the_current_password(client, db, microsoft_key, register_and_verify, password):
    login = register_and_verify("bob@example.com")
    body = {"credential": ms_token(microsoft_key)}
    if password is not None:
        body["current_password"] = password

    response = client.post(LINK, json=body, headers=bearer(login))
    assert response.status_code == 400
    assert response.json() == {"detail": "current_password is incorrect"}
    assert db.query(OAuthAccount).count() == 0


def test_link_microsoft_refuses_an_identity_linked_elsewhere(client, db, microsoft_key, register_and_verify):
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200  # ann@corp.test owns it
    login = register_and_verify("bob@example.com")

    response = client.post(LINK, json={"credential": ms_token(microsoft_key), "current_password": "securepassword123"},
                           headers=bearer(login))
    assert response.status_code == 409
    assert response.json() == {"detail": "This Microsoft account is already linked to a different user"}


def test_link_microsoft_refuses_a_second_link_on_the_same_account(client, db, microsoft_key, register_and_verify):
    login = register_and_verify("bob@example.com")
    first = client.post(LINK, json={"credential": ms_token(microsoft_key), "current_password": "securepassword123"},
                        headers=bearer(login))
    assert first.status_code == 200
    second = client.post(LINK, json={"credential": ms_token(microsoft_key, oid="another-oid"),
                                     "current_password": "securepassword123"}, headers=bearer(login))
    assert second.status_code == 409
    assert second.json() == {"detail": "A Microsoft account is already linked to this account"}


def test_link_microsoft_requires_sign_in(client, microsoft_key):
    assert client.post(LINK, json={"credential": ms_token(microsoft_key)}).status_code == 401


# Found by the final review: Entra does not verify the `email` claim (a tenant admin can set a
# user's mail attribute to anything); the UPN must be on one of the tenant's verified domains.
def test_an_unverified_email_claim_is_not_trusted(client, db, microsoft_key):
    response = sign_in(client, ms_token(microsoft_key, email="ceo@other-company.example.com",
                                        preferred_username="ann@example.com"))
    assert response.status_code == 200, response.text
    assert db.query(User).one().email == "ann@example.com"


def test_a_domain_verified_email_claim_is_used(client, db, microsoft_key):
    response = sign_in(client, ms_token(microsoft_key, email="ann.mail@example.com",
                                        preferred_username="ann@example.com", xms_edov=True))
    assert response.status_code == 200, response.text
    assert db.query(User).one().email == "ann.mail@example.com"


@pytest.mark.parametrize("edov", ["true", 1, False])
def test_only_a_boolean_true_xms_edov_counts(client, db, microsoft_key, edov):
    response = sign_in(client, ms_token(microsoft_key, email="ann.mail@example.com",
                                        preferred_username="ann@example.com", xms_edov=edov))
    assert response.status_code == 200, response.text
    assert db.query(User).one().email == "ann@example.com"


def test_an_unverified_email_without_a_upn_is_refused(client, db, microsoft_key):
    response = sign_in(client, ms_token(microsoft_key, email="ann@example.com", preferred_username=DROP))
    assert response.status_code == 400
    assert response.json() == {"detail": "Microsoft account has no email address"}


# Found by the final review: Entra sets nbf to the issue time, so any clock difference failed
def test_a_small_clock_difference_is_tolerated(client, microsoft_key):
    soon = datetime.now(timezone.utc) + timedelta(seconds=30)
    assert sign_in(client, ms_token(microsoft_key, nbf=soon)).status_code == 200


# The one-time link allowance (ADR-031). The test client closes the shared session after each
# request, which detaches loaded users: ids are kept before a request and rows re-read after it.

def _allow(db, email, minutes=7 * 24 * 60):
    user = db.query(User).filter(User.email == email).one()
    user.microsoft_link_allowed_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    db.commit()
    return user.id, user.microsoft_link_allowed_until


def test_an_allowed_account_is_linked_at_its_next_microsoft_sign_in(client, db, microsoft_key, register_and_verify, caplog):
    register_and_verify("ann@example.com")
    ann_id, _ = _allow(db, "ann@example.com")

    with caplog.at_level(logging.WARNING, logger="src.auth.api.v1.endpoints.sso"):
        response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 200, response.text
    link = db.query(OAuthAccount).one()
    assert (link.user_id, link.provider, link.provider_user_id) == (ann_id, "microsoft", f"{TENANT}:{OID}")
    assert db.get(User, ann_id).microsoft_link_allowed_until is None  # used once
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
    ann_id, allowed_until = _allow(db, "ann@example.com")

    other = sign_in(client, ms_token(microsoft_key, oid="00000000-0000-0000-0000-000000000002",
                                     email="bob@example.com", preferred_username="bob@example.com"))
    assert other.status_code == 200, other.text
    bob = db.query(User).filter(User.email == "bob@example.com").one()
    assert db.query(OAuthAccount).one().user_id == bob.id  # Bob's own new account
    assert db.get(User, ann_id).microsoft_link_allowed_until == allowed_until  # untouched, still Ann's


def test_an_allowance_does_not_replace_an_existing_link(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    ann_id, _ = _allow(db, "ann@example.com")
    db.add(OAuthAccount(user_id=ann_id, provider="microsoft", provider_user_id=f"{TENANT}:someone-else"))
    db.commit()

    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 409
    assert response.json() == {"detail": "This account is linked to a different Microsoft identity"}
    assert db.get(User, ann_id).microsoft_link_allowed_until is not None
    assert db.query(OAuthAccount).count() == 1


def test_an_allowance_on_an_inactive_account_does_not_link(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    ann_id, _ = _allow(db, "ann@example.com")
    db.get(User, ann_id).is_active = False
    db.commit()
    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 409
    assert db.query(OAuthAccount).count() == 0
    assert db.get(User, ann_id).microsoft_link_allowed_until is not None


def test_a_token_from_another_tenant_never_uses_the_allowance(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    ann_id, _ = _allow(db, "ann@example.com")
    response = sign_in(client, ms_token(microsoft_key, tid="12345678-0000-0000-0000-000000000000"))
    assert response.status_code == 400
    assert db.get(User, ann_id).microsoft_link_allowed_until is not None
    assert db.query(OAuthAccount).count() == 0


def test_the_allowance_works_in_sso_only_mode(client, db, microsoft_key, register_and_verify, monkeypatch):
    register_and_verify("ann@example.com")  # before the switch: registration is off afterwards
    _allow(db, "ann@example.com")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    assert sign_in(client, ms_token(microsoft_key)).status_code == 200


# Final review #1: Entra addresses are often mixed case, while the account may be lower case.
def test_the_allowance_matches_the_address_whatever_its_case(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    ann_id, _ = _allow(db, "ann@example.com")

    response = sign_in(client, ms_token(microsoft_key, email="Ann@Example.com", preferred_username="Ann@Example.com"))
    assert response.status_code == 200, response.text
    assert db.query(User).count() == 1  # no second, empty account
    assert db.query(OAuthAccount).one().user_id == ann_id
    assert db.get(User, ann_id).microsoft_link_allowed_until is None


def test_a_case_variant_of_an_existing_address_is_not_a_new_account(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    response = sign_in(client, ms_token(microsoft_key, email="Ann@Example.com", preferred_username="Ann@Example.com"))
    assert response.status_code == 409
    assert db.query(User).count() == 1
    assert db.query(OAuthAccount).count() == 0


def test_two_accounts_that_differ_only_in_case_are_never_linked(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    register_and_verify("Ann@example.com")
    _allow(db, "ann@example.com")
    _allow(db, "Ann@example.com")

    response = sign_in(client, ms_token(microsoft_key, email="ANN@example.com", preferred_username="ANN@example.com"))
    assert response.status_code == 409
    assert db.query(User).count() == 2
    assert db.query(OAuthAccount).count() == 0


# Final review #2: in the mode an ordinary user cannot sign in to link, so the 409 must not ask them to
def test_the_existing_account_409_in_normal_mode_points_at_the_link_endpoint(client, db, microsoft_key, register_and_verify):
    register_and_verify("ann@example.com")
    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 409
    assert response.json() == {"detail": (
        "An account with this email already exists. Sign in to it and link Microsoft "
        "with POST /api/v1/users/me/link/microsoft."
    )}


def test_the_existing_account_409_in_sso_only_mode_asks_for_an_administrator(client, db, microsoft_key, register_and_verify, monkeypatch):
    register_and_verify("ann@example.com")  # before the switch: registration is off afterwards
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 409
    assert response.json() == {"detail": (
        "An account with this email already exists but is not linked to Microsoft. "
        "Ask an administrator to allow linking at your next Microsoft sign-in."
    )}
    assert db.query(OAuthAccount).count() == 0


# Final review #3: "used once" must hold when two first sign-ins race. A request that read a valid
# allowance which another request has since consumed finds nothing to consume, and does not link.
def test_an_allowance_consumed_after_it_was_read_does_not_link(client, db, microsoft_key, register_and_verify, monkeypatch):
    from src.auth.api.v1.endpoints import sso as sso_endpoint

    register_and_verify("ann@example.com")
    ann_id, _ = _allow(db, "ann@example.com")
    db.get(User, ann_id).microsoft_link_allowed_until = None  # the other request's UPDATE won
    db.commit()
    # ... after this request had already read the allowance as valid
    monkeypatch.setattr(sso_endpoint, "valid_allowance",
                        lambda user, now=None: datetime.now(timezone.utc) + timedelta(days=1))

    response = sign_in(client, ms_token(microsoft_key))
    assert response.status_code == 409
    assert db.query(OAuthAccount).count() == 0
