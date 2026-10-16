"""POST /internal/v1/sso-roles: the reconcile of section 3 of the spec, behind HTTP Basic."""
import logging

import pytest

from src.organization.core.config import settings
from src.organization.models import Organization, OrganizationMember, OrganizationSsoRoleMapping

PUSH = "/internal/v1/sso-roles"
USER = 42


@pytest.fixture(autouse=True)
def internal_password(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", "s3cret")


def basic():
    return ("auth-service", "s3cret")


def org(db, slug, mappings=(), deleted=False):
    from datetime import datetime, timezone
    o = Organization(name=slug, slug=slug, plan_tier="free", deleted_at=datetime.now(timezone.utc) if deleted else None)
    db.add(o)
    db.commit()
    for app_role, role in mappings:
        db.add(OrganizationSsoRoleMapping(organization_id=o.id, app_role=app_role, role=role))
    db.commit()
    return o.id


def member(db, org_id, user_id=USER):
    return db.query(OrganizationMember).filter_by(organization_id=org_id, user_id=user_id).one_or_none()


def push(client, roles, user_id=USER):
    response = client.post(PUSH, json={"user_id": user_id, "roles": roles}, auth=basic())
    assert response.status_code == 200, response.text
    return response.json()["changes"]


def test_without_a_password_the_endpoint_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", "")
    assert client.post(PUSH, json={"user_id": 1, "roles": []}, auth=basic()).status_code == 503


@pytest.mark.parametrize("credentials", [("auth-service", "wrong"), ("organization-service", "s3cret"), None])
def test_wrong_credentials_are_401(client, credentials):
    kwargs = {"auth": credentials} if credentials else {}
    assert client.post(PUSH, json={"user_id": 1, "roles": []}, **kwargs).status_code == 401


def test_more_than_50_roles_is_422(client):
    assert client.post(PUSH, json={"user_id": 1, "roles": [f"r{i}" for i in range(51)]}, auth=basic()).status_code == 422


def test_a_matching_role_creates_a_managed_member(client, db, caplog):
    acme = org(db, "acme", [("QEOS.Member", "member")])
    with caplog.at_level(logging.INFO):
        changes = push(client, ["QEOS.Member"])
    assert changes == [{"organization_id": acme, "action": "created", "from": None, "to": "member"}]
    row = member(db, acme)
    assert (row.role, row.status, row.managed_by) == ("member", "active", "entra")
    assert f"entra role: org={acme} user={USER} created None->member roles=QEOS.Member" in caplog.text


def test_highest_matching_role_wins(client, db):
    acme = org(db, "acme", [("QEOS.Viewer", "viewer"), ("QEOS.Admin", "admin"), ("QEOS.Member", "member")])
    push(client, ["QEOS.Viewer", "QEOS.Member", "QEOS.Admin"])
    assert member(db, acme).role == "admin"


def test_match_ignores_case_and_spaces(client, db):
    acme = org(db, "acme", [(" qeos.member ", "member")])
    push(client, ["QEOS.Member"])
    assert member(db, acme).role == "member"


def test_a_managed_member_is_raised_lowered_and_removed(client, db):
    acme = org(db, "acme", [("QEOS.Admin", "admin"), ("QEOS.Viewer", "viewer")])
    push(client, ["QEOS.Viewer"])
    assert push(client, ["QEOS.Admin"]) == [{"organization_id": acme, "action": "updated", "from": "viewer", "to": "admin"}]
    assert push(client, ["QEOS.Viewer"])[0]["to"] == "viewer"
    assert push(client, []) == [{"organization_id": acme, "action": "removed", "from": "viewer", "to": None}]
    assert member(db, acme) is None


def test_a_hand_made_member_is_never_touched(client, db):
    acme = org(db, "acme", [("QEOS.Admin", "admin")])
    db.add(OrganizationMember(organization_id=acme, user_id=USER, role="viewer", status="active"))
    db.commit()
    assert push(client, ["QEOS.Admin"]) == []
    assert push(client, []) == []
    row = member(db, acme)
    assert (row.role, row.managed_by) == ("viewer", None)


def test_an_organization_without_mappings_is_never_touched(client, db):
    plain = org(db, "plain")
    assert push(client, ["QEOS.Admin"]) == []
    assert member(db, plain) is None


def test_a_deleted_organization_is_skipped(client, db):
    gone = org(db, "gone", [("QEOS.Member", "member")], deleted=True)
    assert push(client, ["QEOS.Member"]) == []
    assert member(db, gone) is None


def test_several_organizations_at_once(client, db):
    acme = org(db, "acme", [("QEOS.Member", "member")])
    beta = org(db, "beta", [("QEOS.Member", "viewer"), ("Beta.Admin", "admin")])
    changes = push(client, ["QEOS.Member"])
    assert {(c["organization_id"], c["to"]) for c in changes} == {(acme, "member"), (beta, "viewer")}


def test_a_repeated_push_changes_nothing(client, db):
    org(db, "acme", [("QEOS.Member", "member")])
    push(client, ["QEOS.Member"])
    assert push(client, ["QEOS.Member"]) == []


def test_the_endpoint_is_not_in_the_public_schema(client):
    assert "/internal/v1/sso-roles" not in client.get("/api/v1/openapi.json").json()["paths"]
