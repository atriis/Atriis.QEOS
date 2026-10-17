"""Entra role sync needs a superuser's approval per organization (ADR-033 amendment, 2026-10-17).

Any user may create an organization and own it, so an owner's mapping alone must not let Entra add people to it:
reconcile skips an organization until an active superuser approves it.
"""
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import respx

from src.organization.core.config import settings
from src.organization.models import Organization, OrganizationMember

OWNER, SUPERUSER, PLAIN, INACTIVE_SUPERUSER, SIGNER = 1, 7, 8, 9, 42
ALL = "/api/v1/organizations/entra-sync"


def _auth(user_id: int) -> dict:
    token = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                       settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


def _approve_url(org_id: int) -> str:
    return f"/api/v1/organizations/{org_id}/entra-sync"


@pytest.fixture(autouse=True)
def auth_service():
    """auth-service's internal user lookup: 7 is an active superuser, 8 is not one, 9 is a deactivated superuser."""
    users = {
        SUPERUSER: {"id": SUPERUSER, "email": "root@example.com", "is_active": True, "is_superuser": True},
        PLAIN: {"id": PLAIN, "email": "plain@example.com", "is_active": True, "is_superuser": False},
        INACTIVE_SUPERUSER: {"id": INACTIVE_SUPERUSER, "email": "gone@example.com", "is_active": False,
                             "is_superuser": True},
        OWNER: {"id": OWNER, "email": "owner@example.com", "is_active": True, "is_superuser": False},
    }
    with respx.mock(assert_all_called=False) as mock:
        for user_id, body in users.items():
            mock.get(f"{settings.AUTH_SERVICE_URL}/internal/v1/users/{user_id}").mock(
                return_value=httpx.Response(200, json=body))
        yield mock


@pytest.fixture(autouse=True)
def internal_password(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", "s3cret")


@pytest.fixture
def org(client):
    """An organization whose owner (an ordinary user) mapped QEOS.Member to viewer."""
    org_id = client.post("/api/v1/organizations", json={"name": "Acme", "slug": "acme", "plan_tier": "free"},
                         headers=_auth(OWNER)).json()["id"]
    created = client.post(f"/api/v1/organizations/{org_id}/sso-role-mappings",
                          json={"app_role": "QEOS.Member", "role": "viewer"}, headers=_auth(OWNER))
    assert created.status_code == 201, created.text
    return org_id


def _push(client, roles):
    response = client.post("/internal/v1/sso-roles", json={"user_id": SIGNER, "roles": roles},
                           auth=("auth-service", "s3cret"))
    assert response.status_code == 200, response.text
    return response.json()["changes"]


def _member(db, org_id):
    return db.query(OrganizationMember).filter_by(organization_id=org_id, user_id=SIGNER).one_or_none()


def test_an_owners_mapping_alone_adds_nobody(client, db, org):
    assert _push(client, ["QEOS.Member"]) == []
    assert _member(db, org) is None


def test_after_a_superuser_approves_the_mapping_applies(client, db, org):
    approved = client.put(_approve_url(org), json={"approved": True}, headers=_auth(SUPERUSER))
    assert approved.status_code == 200, approved.text
    assert approved.json()["entra_sync_approved"] is True
    assert _push(client, ["QEOS.Member"]) == [
        {"organization_id": org, "action": "created", "from": None, "to": "viewer"}]
    assert _member(db, org).managed_by == "entra"


def test_the_superuser_does_not_need_to_be_a_member(client, org):
    # the approver is the deployment's administrator, not someone inside the organization
    assert client.put(_approve_url(org), json={"approved": True}, headers=_auth(SUPERUSER)).status_code == 200


@pytest.mark.parametrize("user_id", [OWNER, PLAIN, INACTIVE_SUPERUSER])
def test_only_an_active_superuser_approves(client, org, user_id):
    response = client.put(_approve_url(org), json={"approved": True}, headers=_auth(user_id))
    assert response.status_code == 403
    assert client.get(f"/api/v1/organizations/{org}", headers=_auth(OWNER)).json()["entra_sync_approved"] is False


def test_unknown_user_is_403(client, org, auth_service):
    auth_service.get(f"{settings.AUTH_SERVICE_URL}/internal/v1/users/99").mock(return_value=httpx.Response(404))
    assert client.put(_approve_url(org), json={"approved": True}, headers=_auth(99)).status_code == 403


def test_auth_service_down_is_502_and_changes_nothing(client, org, auth_service):
    auth_service.get(f"{settings.AUTH_SERVICE_URL}/internal/v1/users/{SUPERUSER}").mock(
        side_effect=httpx.ConnectError("refused"))
    assert client.put(_approve_url(org), json={"approved": True}, headers=_auth(SUPERUSER)).status_code == 502
    assert client.get(f"/api/v1/organizations/{org}", headers=_auth(OWNER)).json()["entra_sync_approved"] is False


def test_revoking_stops_the_sync_and_keeps_existing_members(client, db, org):
    client.put(_approve_url(org), json={"approved": True}, headers=_auth(SUPERUSER))
    _push(client, ["QEOS.Member"])
    revoked = client.put(_approve_url(org), json={"approved": False}, headers=_auth(SUPERUSER))
    assert revoked.status_code == 200 and revoked.json()["entra_sync_approved"] is False
    # no longer touched by Entra: neither removed when the role goes, nor re-created
    assert _push(client, []) == []
    assert _member(db, org) is not None


def test_a_deleted_or_missing_organization_is_404(client, db, org):
    assert client.put(_approve_url(999), json={"approved": True}, headers=_auth(SUPERUSER)).status_code == 404
    db.get(Organization, org).deleted_at = datetime.now(timezone.utc)
    db.commit()
    assert client.put(_approve_url(org), json={"approved": True}, headers=_auth(SUPERUSER)).status_code == 404


def test_approval_records_who_and_when(client, db, org):
    client.put(_approve_url(org), json={"approved": True}, headers=_auth(SUPERUSER))
    row = db.get(Organization, org)
    db.refresh(row)
    assert row.entra_sync_approved_by == SUPERUSER and row.entra_sync_approved_at is not None
    client.put(_approve_url(org), json={"approved": False}, headers=_auth(SUPERUSER))
    db.refresh(row)
    assert row.entra_sync_approved_by is None and row.entra_sync_approved_at is None


def test_superusers_list_the_organizations_waiting_or_approved(client, org):
    plain = client.post("/api/v1/organizations", json={"name": "Plain", "slug": "plain", "plan_tier": "free"},
                        headers=_auth(OWNER)).json()["id"]
    listed = client.get(ALL, headers=_auth(SUPERUSER))
    assert listed.status_code == 200, listed.text
    # an organization without a mapping and never approved has nothing to approve
    assert [(o["id"], o["mappings"], o["entra_sync_approved"]) for o in listed.json()] == [(org, 1, False)]
    assert plain not in [o["id"] for o in listed.json()]
    client.put(_approve_url(org), json={"approved": True}, headers=_auth(SUPERUSER))
    entry = client.get(ALL, headers=_auth(SUPERUSER)).json()[0]
    assert entry["entra_sync_approved"] is True and entry["entra_sync_approved_at"] is not None
    assert entry["name"] == "Acme" and entry["slug"] == "acme"


@pytest.mark.parametrize("user_id", [OWNER, PLAIN])
def test_the_list_is_for_superusers_only(client, org, user_id):
    assert client.get(ALL, headers=_auth(user_id)).status_code == 403


def test_owners_see_whether_their_organization_is_approved(client, org):
    mine = client.get("/api/v1/organizations", headers=_auth(OWNER)).json()
    assert [o["entra_sync_approved"] for o in mine] == [False]
