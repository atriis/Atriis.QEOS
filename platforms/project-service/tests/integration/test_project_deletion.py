"""Project deletion (spec 2026-10-16): who deleted it, 7 days pending, restore, and what each role sees."""
from datetime import datetime, timedelta, timezone

import pytest

from src.project.models.project import Project

MANAGERS = ("owner", "admin")
OTHERS = ("member", "viewer", "billing_manager")


def delete(client, auth, project_id, user_id=1):
    return client.delete(f"/api/v1/projects/{project_id}", headers=auth(user_id))


def test_delete_records_who_and_when(client, auth, org_role, make_project, db):
    project = make_project()
    org_role("admin")
    assert delete(client, auth, project.id, user_id=7).status_code == 204
    db.expire_all()
    row = db.get(Project, project.id)
    assert row.deleted_by == 7 and row.deleted_at is not None


def test_delete_under_legal_hold_is_409(client, auth, org_role, make_project, db):
    project = make_project()
    project.legal_hold_at = datetime.now(timezone.utc)
    db.commit()
    org_role("owner")
    response = delete(client, auth, project.id)
    assert response.status_code == 409
    assert response.json()["detail"] == "Release the legal hold before deleting this project"


@pytest.mark.parametrize("role", MANAGERS + OTHERS)
def test_a_pending_project_answers_410_with_the_purge_date(client, auth, org_role, make_project, db, role):
    project = make_project()
    deleted_at = datetime(2026, 10, 16, 14, 5, tzinfo=timezone.utc)
    project.deleted_at, project.deleted_by = deleted_at, 7
    db.commit()
    org_role(role)
    response = client.get(f"/api/v1/projects/{project.id}", headers=auth())
    assert response.status_code == 410
    detail = response.json()["detail"]
    assert detail["code"] == "pending_deletion" and detail["deleted_by"] == 7
    assert detail["organization_id"] == project.organization_id
    assert detail["purge_at"].startswith("2026-10-23T14:05")


def test_a_non_member_gets_404_for_a_pending_project(client, auth, org_role, make_project, db):
    project = make_project()
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
    org_role(status_code=404, body={"detail": "Organization not found"})
    assert client.get(f"/api/v1/projects/{project.id}", headers=auth()).status_code == 404


def test_other_routes_of_a_pending_project_are_404(client, auth, org_role, make_project, db):
    project = make_project()
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
    org_role("owner")
    assert client.patch(f"/api/v1/projects/{project.id}", json={"description": "x"}, headers=auth()).status_code == 404
    assert delete(client, auth, project.id).status_code == 404


@pytest.mark.parametrize("role", MANAGERS)
def test_owners_and_admins_restore(client, auth, org_role, make_project, db, role):
    project = make_project()
    org_role(role)
    delete(client, auth, project.id)
    response = client.post(f"/api/v1/projects/{project.id}/restore", headers=auth())
    assert response.status_code == 200, response.text
    assert response.json()["deletion"] is None
    assert client.get(f"/api/v1/projects/{project.id}", headers=auth()).status_code == 200
    db.expire_all()
    row = db.get(Project, project.id)
    assert (row.deleted_at, row.deleted_by, row.purge_state) == (None, None, None)


@pytest.mark.parametrize("role", OTHERS)
def test_other_roles_cannot_restore(client, auth, org_role, make_project, db, role):
    project = make_project()
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
    org_role(role)
    assert client.post(f"/api/v1/projects/{project.id}/restore", headers=auth()).status_code == 403


def test_restoring_a_live_or_unknown_project_is_404(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    assert client.post(f"/api/v1/projects/{project.id}/restore", headers=auth()).status_code == 404
    assert client.post("/api/v1/projects/999/restore", headers=auth()).status_code == 404


def test_restore_when_the_name_was_reused_is_409(client, auth, org_role, make_project, db):
    project = make_project(name="Checkout", slug="checkout")
    org_role("owner")
    delete(client, auth, project.id)
    assert client.post("/api/v1/organizations/1/projects", json={"name": "Checkout"}, headers=auth()).status_code == 201
    response = client.post(f"/api/v1/projects/{project.id}/restore", headers=auth())
    assert response.status_code == 409
    assert response.json()["detail"] == "A live project already uses this name or slug; rename it first"
    db.expire_all()
    assert db.get(Project, project.id).deleted_at is not None


def test_restore_after_the_purge_started_is_409(client, auth, org_role, make_project, db):
    project = make_project()
    project.deleted_at = datetime.now(timezone.utc) - timedelta(days=8)
    project.purge_state = {"started": "2026-10-23T03:00:00+00:00"}
    db.commit()
    org_role("owner")
    response = client.post(f"/api/v1/projects/{project.id}/restore", headers=auth())
    assert response.status_code == 409
    assert response.json()["detail"] == "The purge has started; this project can no longer be restored"


@pytest.mark.parametrize("role", MANAGERS)
def test_owners_and_admins_see_pending_projects_when_they_ask(client, auth, org_role, make_project, db, role):
    live = make_project(name="Live")
    pending = make_project(name="Pending")
    pending.deleted_at, pending.deleted_by = datetime.now(timezone.utc) - timedelta(days=1), 3
    db.commit()
    org_role(role)
    plain = client.get("/api/v1/organizations/1/projects", headers=auth()).json()
    assert [p["id"] for p in plain] == [live.id]
    both = client.get("/api/v1/organizations/1/projects?include_pending=true", headers=auth()).json()
    assert [p["id"] for p in both] == [live.id, pending.id]
    assert both[0]["deletion"] is None and both[1]["deletion"]["deleted_by"] == 3


@pytest.mark.parametrize("role", OTHERS)
def test_other_roles_never_see_pending_projects(client, auth, org_role, make_project, db, role):
    make_project(name="Live")
    pending = make_project(name="Pending")
    pending.deleted_at = datetime.now(timezone.utc)
    db.commit()
    org_role(role)
    listed = client.get("/api/v1/organizations/1/projects?include_pending=true", headers=auth()).json()
    assert [p["name"] for p in listed] == ["Live"]
