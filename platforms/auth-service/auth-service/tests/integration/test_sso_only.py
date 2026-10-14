"""SSO-only mode (ADR-031) at the HTTP boundary."""
import pytest

from src.auth.config import settings

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
