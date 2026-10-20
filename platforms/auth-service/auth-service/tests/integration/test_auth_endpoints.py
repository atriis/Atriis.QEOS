from datetime import datetime, timedelta, timezone

import pytest

from src.auth.models.pending_registration import PendingRegistration
from src.auth.models.user import User


def test_register_verify_and_login(client, db):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@example.com",
            "password": "securepassword123",
            "full_name": "Test User",
        },
    )
    assert response.status_code == 202, response.text
    assert db.query(User).filter(User.email == "test@example.com").first() is None
    pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "test@example.com"
    ).first()
    assert pending is not None

    verified = client.get(f"/api/v1/auth/verify-email?token={pending.token}")
    assert verified.status_code == 200, verified.text
    token_data = verified.json()
    assert "access_token" in token_data
    assert "refresh_token" in token_data
    assert token_data["token_type"] == "bearer"
    assert db.query(PendingRegistration).filter(
        PendingRegistration.email == "test@example.com"
    ).first() is None

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )
    assert response.status_code == 200
    user_info = response.json()
    assert user_info["email"] == "test@example.com"
    assert user_info["full_name"] == "Test User"


def test_registering_twice_creates_independent_rows(client, db):
    """Rotating a second attempt into the first used to let one caller's password
    silently replace another's, while the verification link kept going to the same
    mailbox -- see the spec's Amendment. Two attempts must coexist, and neither's token
    is invalidated by the other existing."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "twice@example.com", "password": "firstpassword1"},
    )
    first_pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "twice@example.com"
    ).first()
    first_token = first_pending.token

    client.post(
        "/api/v1/auth/register",
        json={"email": "twice@example.com", "password": "secondpassword1"},
    )
    assert db.query(PendingRegistration).filter(
        PendingRegistration.email == "twice@example.com"
    ).count() == 2, "a second registration must create an independent row, not replace the first"

    # the first token is still independently valid, and still verifies with the FIRST
    # attempt's password -- not the second's
    verified = client.get(f"/api/v1/auth/verify-email?token={first_token}")
    assert verified.status_code == 200, verified.text

    assert client.post(
        "/api/v1/auth/login",
        json={"email": "twice@example.com", "password": "firstpassword1"},
    ).status_code == 200, "the winning account must use the FIRST attempt's password"
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "twice@example.com", "password": "secondpassword1"},
    ).status_code == 401, "the second attempt's password must never take effect"


def test_verifying_the_first_attempt_deletes_the_second(client, db):
    client.post(
        "/api/v1/auth/register",
        json={"email": "cleanup@example.com", "password": "firstpassword1"},
    )
    first_pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "cleanup@example.com"
    ).first()
    first_token = first_pending.token

    client.post(
        "/api/v1/auth/register",
        json={"email": "cleanup@example.com", "password": "secondpassword1"},
    )
    assert db.query(PendingRegistration).filter(
        PendingRegistration.email == "cleanup@example.com"
    ).count() == 2

    verified = client.get(f"/api/v1/auth/verify-email?token={first_token}")
    assert verified.status_code == 200, verified.text

    assert db.query(PendingRegistration).filter(
        PendingRegistration.email == "cleanup@example.com"
    ).count() == 0, "the losing attempt must be cleaned up, not left independently clickable"


def test_resend_verification_declines_when_attacker_registers_after_victim(client, db):
    """A first attempt at this fix served the oldest unexpired attempt on resend -- that
    only closes the credential-injection exploit when the victim registers before any
    attacker does (see the spec's corrected Amendment). Once a second, ambiguous attempt
    exists for the address, resend must decline entirely rather than guess by any
    ordering. The victim's own original link is untouched either way."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "oldest@example.com", "password": "victimpassword1"},
    )
    victim_pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "oldest@example.com"
    ).first()
    victim_id = victim_pending.id
    victim_token = victim_pending.token

    client.post(
        "/api/v1/auth/register",
        json={"email": "oldest@example.com", "password": "attackerpassword1"},
    )

    resend = client.post(
        "/api/v1/auth/resend-verification", json={"email": "oldest@example.com"}
    )
    assert resend.status_code == 200, resend.text

    # re-query rather than db.refresh(victim_pending): the shared `db` session is closed by
    # the app's get_db dependency teardown after every request above, detaching the
    # previously-loaded instance -- refreshing a detached instance raises, a fresh query
    # does not.
    victim_pending = db.query(PendingRegistration).filter(
        PendingRegistration.id == victim_id
    ).first()
    assert victim_pending.token == victim_token, "resend must not rotate anything when ambiguous"

    verified = client.get(f"/api/v1/auth/verify-email?token={victim_token}")
    assert verified.status_code == 200, verified.text
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "oldest@example.com", "password": "victimpassword1"},
    ).status_code == 200, "the victim's own original link and password must still work untouched"


def test_resend_verification_declines_when_multiple_attempts_exist(client, db):
    """The property that actually closes the credential-injection exploit for BOTH
    registration orderings: resend must never guess which of several pending attempts is
    legitimate. Covers the ordering the round-1 fix missed -- attacker registers FIRST."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "ambiguous@example.com", "password": "attackerpassword1"},
    )
    client.post(
        "/api/v1/auth/register",
        json={"email": "ambiguous@example.com", "password": "victimpassword1"},
    )
    # order by id (strictly monotonic) rather than created_at: created_at has only
    # second resolution in SQLite, and both registrations above can land in the same
    # second, making a created_at-only ordering ambiguous about which row is the victim's.
    attacker_pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "ambiguous@example.com"
    ).order_by(PendingRegistration.id.asc()).first()
    attacker_id = attacker_pending.id
    attacker_token = attacker_pending.token

    victim_pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "ambiguous@example.com"
    ).order_by(PendingRegistration.id.desc()).first()
    victim_id = victim_pending.id
    victim_token = victim_pending.token

    resend = client.post(
        "/api/v1/auth/resend-verification", json={"email": "ambiguous@example.com"}
    )
    assert resend.status_code == 200, resend.text

    # neither row's token was rotated -- nothing was sent to anyone
    victim_pending = db.query(PendingRegistration).filter(
        PendingRegistration.id == victim_id
    ).first()
    assert victim_pending.token == victim_token, "resend must not act when ambiguous"

    attacker_pending = db.query(PendingRegistration).filter(
        PendingRegistration.id == attacker_id
    ).first()
    assert attacker_pending.token == attacker_token, (
        "resend must not rotate the attacker's older row either -- a regression to "
        "oldest-wins would rotate exactly this row and this assertion is what catches it"
    )

    # the victim's OWN original link still works, entirely unaffected
    verified = client.get(f"/api/v1/auth/verify-email?token={victim_token}")
    assert verified.status_code == 200, verified.text
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "ambiguous@example.com", "password": "victimpassword1"},
    ).status_code == 200, "the victim's own password must be the one that wins"


def test_expired_verification_token_is_refused_and_releases_the_address(client, db):
    client.post(
        "/api/v1/auth/register",
        json={"email": "expired@example.com", "password": "securepassword123"},
    )
    pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "expired@example.com"
    ).first()
    pending.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    response = client.get(f"/api/v1/auth/verify-email?token={pending.token}")
    assert response.status_code == 400, response.text

    retry = client.post(
        "/api/v1/auth/register",
        json={"email": "expired@example.com", "password": "anotherpassword1"},
    )
    assert retry.status_code == 202, retry.text


def test_verifying_after_the_address_was_claimed_by_sso_is_refused(client, db, monkeypatch):
    """The scenario the design exists for: an attacker's pending registration must not
    matter once the real owner has claimed the address through any path -- here, Google SSO
    racing ahead of a stale, unverified password registration. Builds a minimal local Google
    token rather than depending on test_sso_endpoints.py's fixtures, keeping this file's
    dependency on that module's internals at zero."""
    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from src.auth.config import settings
    from src.auth.service import sso_service

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class _StubKey:
        key = private_key.public_key()

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(
        sso_service._jwks_client, "get_signing_key_from_jwt", lambda token: _StubKey()
    )

    client.post(
        "/api/v1/auth/register",
        json={"email": "person@example.com", "password": "attackerpassword1"},
    )
    pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "person@example.com"
    ).first()
    pending_token = pending.token

    claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id.apps.googleusercontent.com",
        "sub": "google-user-1",
        "email": "person@example.com",
        "email_verified": True,
        "name": "Real Owner",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    credential = pyjwt.encode(claims, private_key, algorithm="RS256")
    sso_response = client.post("/api/v1/sso/google", json={"credential": credential})
    assert sso_response.status_code == 200, sso_response.text

    response = client.get(f"/api/v1/auth/verify-email?token={pending_token}")
    assert response.status_code == 409, response.text
    assert db.query(User).filter(User.email == "person@example.com").count() == 1
    assert db.query(PendingRegistration).filter(
        PendingRegistration.email == "person@example.com"
    ).first() is None


def test_refresh_token(client, register_and_verify):
    tokens = register_and_verify("test2@example.com")

    response = client.post(
        "/api/v1/auth/refresh-token",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert response.status_code == 200
    new_tokens = response.json()
    assert "access_token" in new_tokens
    assert "refresh_token" in new_tokens
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    response = client.post(
        "/api/v1/auth/refresh-token",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert response.status_code == 401


def test_resend_verification_rotates_the_token(client, db):
    client.post(
        "/api/v1/auth/register",
        json={"email": "resend@example.com", "password": "securepassword123"},
    )
    first_pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "resend@example.com"
    ).first()
    first_token = first_pending.token

    response = client.post(
        "/api/v1/auth/resend-verification", json={"email": "resend@example.com"}
    )
    assert response.status_code == 200, response.text

    stale = client.get(f"/api/v1/auth/verify-email?token={first_token}")
    assert stale.status_code == 400, stale.text

    refreshed_pending = db.query(PendingRegistration).filter(
        PendingRegistration.email == "resend@example.com"
    ).first()
    verified = client.get(f"/api/v1/auth/verify-email?token={refreshed_pending.token}")
    assert verified.status_code == 200, verified.text


def test_resend_verification_answers_identically_regardless_of_state(client, register_and_verify):
    """Matches /forgot-password's enumeration-prevention: the same response for a pending
    registration, a completed account, and an address nobody has ever used."""
    register_and_verify("completed@example.com")
    client.post(
        "/api/v1/auth/register",
        json={"email": "pending@example.com", "password": "securepassword123"},
    )

    responses = [
        client.post("/api/v1/auth/resend-verification", json={"email": "pending@example.com"}),
        client.post("/api/v1/auth/resend-verification", json={"email": "completed@example.com"}),
        client.post("/api/v1/auth/resend-verification", json={"email": "nobody@example.com"}),
    ]
    bodies = {r.status_code for r in responses}
    messages = {r.json()["message"] for r in responses}
    assert bodies == {200}
    assert len(messages) == 1


def _sent_links(monkeypatch):
    from src.auth.service.email_sender import EmailSender

    links = []
    monkeypatch.setattr(EmailSender, "send_verification_email", staticmethod(lambda to, link: links.append(link)))
    return links


def test_the_verification_link_carries_the_page_the_person_was_heading_to(client, monkeypatch):
    """An invitee registers from /invitations/<token>; the emailed link is often opened in
    another browser, so the way back travels in the link, not only in the first tab's storage."""
    links = _sent_links(monkeypatch)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "invitee@example.com", "password": "securepassword123", "next": "/invitations/tok-1?x=1"},
    )
    assert response.status_code == 202, response.text
    assert len(links) == 1
    assert links[0].endswith("&next=%2Finvitations%2Ftok-1%3Fx%3D1")


def test_without_a_next_the_verification_link_is_unchanged(client, monkeypatch):
    links = _sent_links(monkeypatch)
    client.post("/api/v1/auth/register", json={"email": "plain@example.com", "password": "securepassword123"})
    assert "next=" not in links[0]


@pytest.mark.parametrize(
    "unsafe",
    ["//evil.example", "https://evil.example", "/\\evil.example", "/\t/evil.example", "invitations/x", "/login?next=/x", "/" + "a" * 2048],
)
def test_a_next_that_could_leave_the_site_is_refused(client, monkeypatch, unsafe):
    links = _sent_links(monkeypatch)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "evil@example.com", "password": "securepassword123", "next": unsafe},
    )
    assert response.status_code == 422, response.text
    assert links == []
