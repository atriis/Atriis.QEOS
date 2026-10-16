"""The Entra app-role mapping of an organization (spec 2026-10-16 §5.2). Owners only; never owner."""
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import respx

from src.organization.core.config import settings

OWNER, ADMIN, OUTSIDER = 1, 2, 3


def _auth(user_id: int) -> dict:
    token = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                       settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def org(client):
    org_id = client.post("/api/v1/organizations", json={"name": "Acme", "slug": "acme", "plan_tier": "free"},
                         headers=_auth(OWNER)).json()["id"]
    with respx.mock:
        respx.get(f"{settings.AUTH_SERVICE_URL}/internal/v1/users/{ADMIN}").mock(return_value=httpx.Response(200, json={"id": ADMIN}))
        assert client.post(f"/api/v1/organizations/{org_id}/members", json={"user_id": ADMIN, "role": "admin"},
                           headers=_auth(OWNER)).status_code == 201
    return org_id


def url(org_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/sso-role-mappings{suffix}"


def test_an_owner_adds_lists_and_deletes_a_mapping(client, org):
    created = client.post(url(org), json={"app_role": "  QEOS.Member ", "role": "member"}, headers=_auth(OWNER))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["app_role"] == "QEOS.Member" and body["role"] == "member"
    client.post(url(org), json={"app_role": "QEOS.Admin", "role": "admin"}, headers=_auth(OWNER))
    listed = client.get(url(org), headers=_auth(OWNER)).json()
    assert [m["app_role"] for m in listed] == ["QEOS.Admin", "QEOS.Member"]
    assert client.delete(url(org, f"/{body['id']}"), headers=_auth(OWNER)).status_code == 204
    assert [m["app_role"] for m in client.get(url(org), headers=_auth(OWNER)).json()] == ["QEOS.Admin"]


def test_the_same_value_in_another_case_is_a_duplicate(client, org):
    assert client.post(url(org), json={"app_role": "QEOS.Member", "role": "member"}, headers=_auth(OWNER)).status_code == 201
    again = client.post(url(org), json={"app_role": "qeos.member", "role": "viewer"}, headers=_auth(OWNER))
    assert again.status_code == 409
    assert again.json()["detail"] == {"code": "duplicate_app_role", "message": "This app role is already mapped."}


@pytest.mark.parametrize("payload", [
    {"app_role": "QEOS.Owner", "role": "owner"},
    {"app_role": "QEOS.Billing", "role": "billing_manager"},
    {"app_role": "QEOS.X", "role": "superuser"},
    {"app_role": "   ", "role": "member"},
    {"app_role": "x" * 101, "role": "member"},
])
def test_refused_mappings(client, org, payload):
    assert client.post(url(org), json=payload, headers=_auth(OWNER)).status_code == 422


def test_an_admin_cannot_read_or_change_the_mapping(client, org):
    assert client.get(url(org), headers=_auth(ADMIN)).status_code == 403
    assert client.post(url(org), json={"app_role": "QEOS.Admin", "role": "admin"}, headers=_auth(ADMIN)).status_code == 403


def test_an_outsider_does_not_see_the_organization(client, org):
    assert client.get(url(org), headers=_auth(OUTSIDER)).status_code == 404


def test_deleting_another_organizations_mapping_is_404(client, org):
    other = client.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta", "plan_tier": "free"},
                        headers=_auth(OWNER)).json()["id"]
    mapping = client.post(url(other), json={"app_role": "QEOS.Member", "role": "member"}, headers=_auth(OWNER)).json()
    assert client.delete(url(org, f"/{mapping['id']}"), headers=_auth(OWNER)).status_code == 404
