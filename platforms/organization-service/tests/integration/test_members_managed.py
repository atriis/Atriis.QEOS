"""Entra-managed members are visible as such and cannot be removed by hand (spec §5.3)."""
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import respx

from src.organization.core.config import settings
from src.organization.models import OrganizationMember

OWNER, ADMIN, MANAGED = 1, 2, 9


def _auth(user_id: int) -> dict:
    token = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                       settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def org(client, db):
    org_id = client.post("/api/v1/organizations", json={"name": "Acme", "slug": "acme", "plan_tier": "free"},
                         headers=_auth(OWNER)).json()["id"]
    with respx.mock:
        respx.get(f"{settings.AUTH_SERVICE_URL}/internal/v1/users/{ADMIN}").mock(return_value=httpx.Response(200, json={"id": ADMIN}))
        client.post(f"/api/v1/organizations/{org_id}/members", json={"user_id": ADMIN, "role": "admin"}, headers=_auth(OWNER))
    db.add(OrganizationMember(organization_id=org_id, user_id=MANAGED, role="member", status="active", managed_by="entra"))
    db.commit()
    return org_id


def managed_id(db, org_id):
    return db.query(OrganizationMember).filter_by(organization_id=org_id, user_id=MANAGED).one().id


def test_members_carry_managed_by(client, org):
    with respx.mock:
        respx.get(f"{settings.AUTH_SERVICE_URL}/internal/v1/users").mock(return_value=httpx.Response(200, json={"users": []}))
        rows = client.get(f"/api/v1/organizations/{org}/members", headers=_auth(OWNER)).json()
    by_user = {r["user_id"]: r["managed_by"] for r in rows}
    assert by_user == {OWNER: None, ADMIN: None, MANAGED: "entra"}


@pytest.mark.parametrize("remover", [OWNER, ADMIN])
def test_removing_a_managed_member_is_409(client, db, org, remover):
    response = client.delete(f"/api/v1/organizations/{org}/members/{managed_id(db, org)}", headers=_auth(remover))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "managed_by_entra", "message": "Managed by Entra: remove the app role instead."}


def test_a_hand_made_member_is_still_removable(client, db, org):
    admin_row = db.query(OrganizationMember).filter_by(organization_id=org, user_id=ADMIN).one()
    assert client.delete(f"/api/v1/organizations/{org}/members/{admin_row.id}", headers=_auth(OWNER)).status_code == 204
