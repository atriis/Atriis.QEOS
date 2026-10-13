import pytest

from src.ingestion.models import ApiKey
from src.ingestion.utils.keys import hash_key

ALL_ROLES = ("owner", "admin", "member", "viewer", "billing_manager")
EDITORS = ("owner", "admin", "member")
BASE = "/api/v1/projects/1/api-keys"


@pytest.mark.parametrize("role", ALL_ROLES)
def test_create_is_for_editors(client, auth, project_role, role):
    project_role(role)
    response = client.post(BASE, json={"name": "GitHub Actions"}, headers=auth())
    assert response.status_code == (201 if role in EDITORS else 403)


@pytest.mark.parametrize("role", ALL_ROLES)
def test_list_is_for_every_role(client, auth, project_role, role):
    project_role(role)
    assert client.get(BASE, headers=auth()).status_code == 200


@pytest.mark.parametrize("role", ALL_ROLES)
def test_revoke_is_for_editors(client, auth, project_role, make_key, role):
    row, _ = make_key()
    project_role(role)
    response = client.delete(f"{BASE}/{row.id}", headers=auth())
    assert response.status_code == (204 if role in EDITORS else 403)


def test_create_returns_the_key_once_and_stores_only_its_hash(client, auth, project_role, db):
    project_role("admin", organization_id=77)
    body = client.post(BASE, json={"name": "GitHub Actions"}, headers=auth(9)).json()
    assert body["key"].startswith("qeos_")
    assert body["key_prefix"] == body["key"][:13]
    row = db.query(ApiKey).one()
    assert row.key_hash == hash_key(body["key"])
    assert body["key"] not in {row.key_hash, row.key_prefix, row.name}
    assert (row.project_id, row.organization_id, row.created_by) == (1, 77, 9)

    listed = client.get(BASE, headers=auth()).json()
    assert listed[0]["key_prefix"] == body["key_prefix"]
    assert "key" not in listed[0] and "key_hash" not in listed[0]


@pytest.mark.parametrize("name", ["", "   ", "x" * 256])
def test_invalid_name_is_422(client, auth, project_role, name):
    project_role("owner")
    assert client.post(BASE, json={"name": name}, headers=auth()).status_code == 422


def test_unknown_field_is_422(client, auth, project_role):
    project_role("owner")
    assert client.post(BASE, json={"name": "k", "scopes": ["all"]}, headers=auth()).status_code == 422


def test_list_shows_only_this_projects_keys(client, auth, project_role, make_key):
    make_key(project_id=1, name="mine")
    make_key(project_id=2, name="theirs")
    project_role("viewer")
    assert [k["name"] for k in client.get(BASE, headers=auth()).json()] == ["mine"]


def test_revoke_sets_revoked_at_and_is_repeatable(client, auth, project_role, make_key, db):
    row, _ = make_key()
    project_role("member")
    assert client.delete(f"{BASE}/{row.id}", headers=auth()).status_code == 204
    db.refresh(row)
    first = row.revoked_at
    assert first is not None
    assert client.delete(f"{BASE}/{row.id}", headers=auth()).status_code == 204
    db.refresh(row)
    assert row.revoked_at == first


def test_revoking_another_projects_key_is_404(client, auth, project_role, make_key, db):
    row, _ = make_key(project_id=2)
    project_role("owner", project_id=1)
    assert client.delete(f"{BASE}/{row.id}", headers=auth()).status_code == 404
    db.refresh(row)
    assert row.revoked_at is None


def test_non_member_is_404(client, auth, project_role):
    project_role(status_code=404, body={"detail": "Project not found"})
    assert client.get(BASE, headers=auth()).status_code == 404


# ---- can_read_impact: may the key read test suggestions (spec 2026-10-13 §9) ----
MANAGERS = ("owner", "admin")


@pytest.mark.parametrize("role", EDITORS)
def test_a_new_key_cannot_read_impact_by_default(client, auth, project_role, db, role):
    project_role(role)
    body = client.post(BASE, json={"name": "ci"}, headers=auth()).json()
    assert body["can_read_impact"] is False
    assert db.get(ApiKey, body["id"]).can_read_impact is False


@pytest.mark.parametrize("role", ALL_ROLES)
def test_only_owners_and_admins_create_a_key_that_reads_impact(client, auth, project_role, db, role):
    project_role(role)
    response = client.post(BASE, json={"name": "ci", "can_read_impact": True}, headers=auth())
    assert response.status_code == (201 if role in MANAGERS else 403)
    if role in MANAGERS:
        assert response.json()["can_read_impact"] is True
        assert db.get(ApiKey, response.json()["id"]).can_read_impact is True
    else:
        assert db.query(ApiKey).count() == 0  # nothing created, not even an upload-only key


def test_the_list_shows_the_permission_and_existing_keys_are_upload_only(client, auth, project_role, make_key, db):
    existing, _ = make_key()  # a key as migration 020 finds it: no value given
    project_role("viewer")
    assert [(k["id"], k["can_read_impact"]) for k in client.get(BASE, headers=auth()).json()] == [(existing.id, False)]
    existing.can_read_impact = True
    db.commit()
    assert client.get(BASE, headers=auth()).json()[0]["can_read_impact"] is True


@pytest.mark.parametrize("role", ALL_ROLES)
def test_only_owners_and_admins_change_the_permission(client, auth, project_role, make_key, db, role):
    row, _ = make_key()
    project_role(role)
    response = client.patch(f"{BASE}/{row.id}", json={"can_read_impact": True}, headers=auth())
    assert response.status_code == (200 if role in MANAGERS else 403)
    db.expire_all()
    assert db.get(ApiKey, row.id).can_read_impact is (role in MANAGERS)


def test_the_permission_toggles_on_and_off(client, auth, project_role, make_key, db):
    row, _ = make_key()
    project_role("admin")
    on = client.patch(f"{BASE}/{row.id}", json={"can_read_impact": True}, headers=auth())
    assert (on.status_code, on.json()["id"], on.json()["can_read_impact"]) == (200, row.id, True)
    assert "key" not in on.json() and "key_hash" not in on.json()
    off = client.patch(f"{BASE}/{row.id}", json={"can_read_impact": False}, headers=auth())
    assert off.json()["can_read_impact"] is False
    db.expire_all()
    assert db.get(ApiKey, row.id).can_read_impact is False


@pytest.mark.parametrize("body", [{}, {"can_read_impact": "yes please"}, {"can_read_impact": True, "name": "x"}])
def test_an_invalid_change_is_422(client, auth, project_role, make_key, body):
    row, _ = make_key()
    project_role("owner")
    assert client.patch(f"{BASE}/{row.id}", json=body, headers=auth()).status_code == 422


def test_changing_another_projects_or_an_unknown_key_is_404(client, auth, project_role, make_key, db):
    other, _ = make_key(project_id=2)
    project_role("owner")
    for key_id in (other.id, 9999):
        assert client.patch(f"{BASE}/{key_id}", json={"can_read_impact": True}, headers=auth()).status_code == 404
    db.expire_all()
    assert db.get(ApiKey, other.id).can_read_impact is False


def test_a_revoked_key_cannot_be_changed(client, auth, project_role, make_key, db):
    row, _ = make_key(revoked=True)
    project_role("owner")
    assert client.patch(f"{BASE}/{row.id}", json={"can_read_impact": True}, headers=auth()).status_code == 409
    db.expire_all()
    assert db.get(ApiKey, row.id).can_read_impact is False


def test_a_non_member_cannot_change_the_permission(client, auth, project_role, make_key, db):
    row, _ = make_key()
    project_role(status_code=404, body={"detail": "Project not found"})
    assert client.patch(f"{BASE}/{row.id}", json={"can_read_impact": True}, headers=auth()).status_code == 404
    db.expire_all()
    assert db.get(ApiKey, row.id).can_read_impact is False
