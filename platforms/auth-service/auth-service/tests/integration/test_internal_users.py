"""GET /internal/v1/users/{id}: lets sibling services (organization-service's
member add) ask whether a user exists, without a superuser token. Not routed
by the gateway; HTTP Basic with the shared internal credentials."""
import pytest

from src.auth.config import settings
from src.auth.models.user import User

URL = "/internal/v1/users"
CREDS = ("organization-service", "internal-test-secret")


@pytest.fixture
def internal_configured(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_USERNAME", CREDS[0], raising=False)
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", CREDS[1], raising=False)


@pytest.fixture
def user(db):
    row = User(email="someone@example.com", hashed_password="x", is_active=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_an_existing_user_is_returned(client, internal_configured, user):
    response = client.get(f"{URL}/{user.id}", auth=CREDS)
    assert response.status_code == 200, response.text
    assert response.json() == {"id": user.id, "email": "someone@example.com", "is_active": True, "is_superuser": False}


def test_a_missing_user_is_a_clean_404(client, internal_configured):
    assert client.get(f"{URL}/99999", auth=CREDS).status_code == 404


def test_wrong_credentials_are_401(client, internal_configured, user):
    assert client.get(f"{URL}/{user.id}", auth=("organization-service", "wrong")).status_code == 401
    assert client.get(f"{URL}/{user.id}").status_code == 401


def test_unconfigured_internal_api_is_503(client, user, monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", "", raising=False)
    assert client.get(f"{URL}/{user.id}", auth=CREDS).status_code == 503


def test_batch_lookup_returns_only_existing_users(client, internal_configured, db, user):
    second = User(email="other@example.com", hashed_password="x", is_active=False)
    db.add(second)
    db.commit()
    db.refresh(second)

    response = client.get(f"{URL}?ids={user.id},{second.id},99999", auth=CREDS)
    assert response.status_code == 200, response.text
    assert response.json() == {"users": [
        {"id": user.id, "email": "someone@example.com", "is_active": True, "is_superuser": False},
        {"id": second.id, "email": "other@example.com", "is_active": False, "is_superuser": False},
    ]}


def test_batch_lookup_caps_and_validates(client, internal_configured):
    too_many = ",".join(str(i) for i in range(1, 202))
    assert client.get(f"{URL}?ids={too_many}", auth=CREDS).status_code == 422
    assert client.get(f"{URL}?ids=a,b", auth=CREDS).status_code == 422
    assert client.get(f"{URL}?ids=", auth=CREDS).status_code == 422


def test_batch_lookup_needs_credentials(client, internal_configured, user):
    assert client.get(f"{URL}?ids={user.id}").status_code == 401


def test_a_superuser_is_marked(client, internal_configured, db):
    # organization-service asks this before a superuser approves Entra role sync for an organization (ADR-033)
    admin = User(email="admin@example.com", hashed_password="x", is_active=True, is_superuser=True)
    db.add(admin)
    db.commit()
    response = client.get(f"{URL}/{admin.id}", auth=CREDS)
    assert response.json()["is_superuser"] is True
