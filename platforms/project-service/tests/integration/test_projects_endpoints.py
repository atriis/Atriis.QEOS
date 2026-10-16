from datetime import datetime, timezone

import httpx
import pytest

ALL_ROLES = ("owner", "admin", "member", "viewer", "billing_manager")

# (method, path, body, roles allowed, success status) -- the endpoint table in the design spec
ROUTES = [
    ("POST", "/api/v1/organizations/1/projects", {"name": "New Project"}, ("owner", "admin"), 201),
    ("GET", "/api/v1/organizations/1/projects", None, ALL_ROLES, 200),
    ("GET", "/api/v1/projects/{pid}", None, ALL_ROLES, 200),
    ("PATCH", "/api/v1/projects/{pid}", {"description": "updated"}, ("owner", "admin"), 200),
    ("PATCH", "/api/v1/projects/{pid}/settings", {"notify_on_failure": True}, ("owner", "admin", "member"), 200),
    ("DELETE", "/api/v1/projects/{pid}", None, ("owner", "admin"), 204),
]


@pytest.mark.parametrize("method, path, body, allowed, ok", ROUTES)
@pytest.mark.parametrize("role", ALL_ROLES)
def test_role_matrix(client, auth, org_role, make_project, method, path, body, allowed, ok, role):
    project = make_project()
    org_role(role)
    response = client.request(method, path.format(pid=project.id), json=body, headers=auth())
    assert response.status_code == (ok if role in allowed else 403)


def test_create_sets_creator_slug_defaults_and_my_role(client, auth, org_role):
    org_role("admin")
    response = client.post(
        "/api/v1/organizations/1/projects",
        json={"name": "Checkout E2E", "description": "web checkout"},
        headers=auth(7),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["organization_id"] == 1
    assert body["slug"] == "checkout-e2e"
    assert body["created_by"] == 7
    assert body["my_role"] == "admin"
    assert body["settings"] == {"result_retention_days": 90, "default_environment": None, "notify_on_failure": False}


def test_explicit_slug_is_kept(client, auth, org_role):
    org_role("owner")
    response = client.post(
        "/api/v1/organizations/1/projects", json={"name": "Checkout", "slug": "co-web"}, headers=auth()
    )
    assert response.json()["slug"] == "co-web"


@pytest.mark.parametrize("slug", ["Has Space", "UPPER", "-lead", "trail-", "double--dash", "x" * 101])
def test_invalid_explicit_slug_is_422(client, auth, org_role, slug):
    org_role("owner")
    response = client.post("/api/v1/organizations/1/projects", json={"name": "P", "slug": slug}, headers=auth())
    assert response.status_code == 422


@pytest.mark.parametrize("name", ["!!!", "***"])
def test_name_that_slugifies_to_nothing_is_422(client, auth, org_role, name):
    org_role("owner")
    response = client.post("/api/v1/organizations/1/projects", json={"name": name}, headers=auth())
    assert response.status_code == 422
    assert "slug" in response.text


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_name_is_422(client, auth, org_role, name):
    org_role("owner")
    response = client.post("/api/v1/organizations/1/projects", json={"name": name}, headers=auth())
    assert response.status_code == 422


def test_duplicate_name_in_same_org_is_409_and_session_recovers(client, auth, org_role, make_project):
    make_project(name="Checkout", slug="checkout")
    org_role("owner")
    response = client.post(
        "/api/v1/organizations/1/projects", json={"name": "Checkout", "slug": "other"}, headers=auth()
    )
    assert response.status_code == 409
    # the next request on the same session still works (the failed insert was rolled back)
    assert client.get("/api/v1/organizations/1/projects", headers=auth()).status_code == 200


def test_same_name_in_another_org_is_fine(client, auth, org_role, make_project):
    make_project(org_id=2, name="Checkout", slug="checkout")
    org_role("owner", org_id=1)
    response = client.post("/api/v1/organizations/1/projects", json={"name": "Checkout"}, headers=auth())
    assert response.status_code == 201


def test_deleted_projects_name_can_be_reused(client, auth, org_role, make_project):
    project = make_project(name="Checkout", slug="checkout")
    org_role("owner")
    assert client.delete(f"/api/v1/projects/{project.id}", headers=auth()).status_code == 204
    response = client.post("/api/v1/organizations/1/projects", json={"name": "Checkout"}, headers=auth())
    assert response.status_code == 201


def test_rename_onto_a_live_name_is_409(client, auth, org_role, make_project):
    make_project(name="Taken", slug="taken")
    project = make_project(name="Mine", slug="mine")
    org_role("owner")
    response = client.patch(f"/api/v1/projects/{project.id}", json={"name": "Taken"}, headers=auth())
    assert response.status_code == 409
    assert client.get(f"/api/v1/projects/{project.id}", headers=auth()).json()["name"] == "Mine"


def test_rename_onto_a_deleted_name_is_allowed(client, auth, org_role, make_project, db):
    gone = make_project(name="Old", slug="old")
    gone.deleted_at = datetime.now(timezone.utc)
    db.commit()
    project = make_project(name="Mine", slug="mine")
    org_role("owner")
    response = client.patch(f"/api/v1/projects/{project.id}", json={"name": "Old", "slug": "old"}, headers=auth())
    assert response.status_code == 200
    assert response.json()["slug"] == "old"


@pytest.mark.parametrize("field", ["name", "slug"])
def test_patch_cannot_null_a_required_field(client, auth, org_role, make_project, field):
    project = make_project()
    org_role("owner")
    response = client.patch(f"/api/v1/projects/{project.id}", json={field: None}, headers=auth())
    assert response.status_code == 422


def test_patch_can_clear_description(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    client.patch(f"/api/v1/projects/{project.id}", json={"description": "x"}, headers=auth())
    response = client.patch(f"/api/v1/projects/{project.id}", json={"description": None}, headers=auth())
    assert response.json()["description"] is None


def test_list_only_this_orgs_live_projects_in_id_order(client, auth, org_role, make_project, db):
    first = make_project(name="A", slug="a")
    second = make_project(name="B", slug="b")
    deleted = make_project(name="C", slug="c")
    deleted.deleted_at = datetime.now(timezone.utc)
    db.commit()
    make_project(org_id=2, name="Other", slug="other")
    org_role("viewer")
    body = client.get("/api/v1/organizations/1/projects", headers=auth()).json()
    assert [p["id"] for p in body] == [first.id, second.id]
    assert all(p["my_role"] == "viewer" for p in body)


def test_list_pagination(client, auth, org_role, make_project):
    for i in range(5):
        make_project(name=f"P{i}", slug=f"p{i}")
    org_role("viewer")
    page = client.get("/api/v1/organizations/1/projects?limit=2&offset=2", headers=auth()).json()
    assert [p["name"] for p in page] == ["P2", "P3"]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_list_rejects_bad_pagination(client, auth, org_role, query):
    org_role("viewer")
    assert client.get(f"/api/v1/organizations/1/projects?{query}", headers=auth()).status_code == 422


def test_settings_patch_merges_and_null_reverts(client, auth, org_role, make_project):
    project = make_project()
    org_role("member")
    url = f"/api/v1/projects/{project.id}/settings"
    client.patch(url, json={"result_retention_days": 30}, headers=auth())
    client.patch(url, json={"notify_on_failure": True}, headers=auth())
    body = client.get(f"/api/v1/projects/{project.id}", headers=auth()).json()["settings"]
    assert body == {"result_retention_days": 30, "default_environment": None, "notify_on_failure": True}

    reverted = client.patch(url, json={"result_retention_days": None}, headers=auth()).json()["settings"]
    assert reverted["result_retention_days"] == 90


@pytest.mark.parametrize(
    "patch", [{"retention_dayz": 5}, {"result_retention_days": 0}, {"result_retention_days": "lots"}]
)
def test_invalid_settings_are_422_and_nothing_is_stored(client, auth, org_role, make_project, patch):
    project = make_project()
    org_role("member")
    response = client.patch(f"/api/v1/projects/{project.id}/settings", json=patch, headers=auth())
    assert response.status_code == 422
    assert client.get(f"/api/v1/projects/{project.id}", headers=auth()).json()["settings"]["result_retention_days"] == 90


def test_settings_body_must_be_an_object(client, auth, org_role, make_project):
    project = make_project()
    org_role("member")
    response = client.patch(f"/api/v1/projects/{project.id}/settings", json=[1, 2], headers=auth())
    assert response.status_code == 422


def test_a_deleted_project_is_pending_for_its_members(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    client.delete(f"/api/v1/projects/{project.id}", headers=auth())
    # 410 with the purge date (spec 2026-10-16); every other route of it is 404
    assert client.get(f"/api/v1/projects/{project.id}", headers=auth()).status_code == 410
    assert client.patch(f"/api/v1/projects/{project.id}/settings", json={}, headers=auth()).status_code == 404


def test_org_service_down_is_503(client, auth, org_role, make_project):
    project = make_project()
    org_role(exc=httpx.ConnectError("refused"))
    assert client.get(f"/api/v1/projects/{project.id}", headers=auth()).status_code == 503


def test_project_with_a_stale_stored_setting_is_still_readable(client, auth, org_role, make_project, db):
    project = make_project()
    project.settings = {"legacy_setting": 5}
    db.commit()
    org_role("viewer")
    response = client.get(f"/api/v1/projects/{project.id}", headers=auth())
    assert response.status_code == 200
    assert response.json()["settings"]["result_retention_days"] == 90


def test_settings_patch_drops_a_stale_stored_setting(client, auth, org_role, make_project, db):
    project = make_project()
    project.settings = {"legacy_setting": 5}
    db.commit()
    org_role("member")
    response = client.patch(
        f"/api/v1/projects/{project.id}/settings", json={"result_retention_days": 30}, headers=auth()
    )
    assert response.status_code == 200
    db.refresh(project)
    assert "legacy_setting" not in project.settings
