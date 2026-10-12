"""Per-project collection settings (ADR-030): readable by members, changed by owners and admins."""
URL = "/api/v1/projects/1/collection-settings"


def test_defaults_without_a_row(client, auth, project_role):
    project_role(role="viewer", project_id=1)
    body = client.get(URL, headers=auth()).json()
    assert body == {"collect_manual": True, "discarded_count": 0, "last_discarded_at": None,
                    "updated_at": None, "updated_by": None}


def test_an_admin_switches_manual_collection_off(client, auth, project_role):
    project_role(role="admin", project_id=1)
    response = client.put(URL, json={"collect_manual": False}, headers=auth(user_id=7))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["collect_manual"] is False and body["updated_by"] == 7 and body["updated_at"] is not None
    assert client.get(URL, headers=auth()).json()["collect_manual"] is False


def test_put_is_an_upsert(client, auth, project_role):
    project_role(role="owner", project_id=1)
    client.put(URL, json={"collect_manual": False}, headers=auth())
    assert client.put(URL, json={"collect_manual": True}, headers=auth()).json()["collect_manual"] is True


def test_a_member_cannot_change_it(client, auth, project_role):
    project_role(role="member", project_id=1)
    assert client.get(URL, headers=auth()).status_code == 200
    assert client.put(URL, json={"collect_manual": False}, headers=auth()).status_code == 403


def test_a_non_member_gets_404(client, auth, project_role):
    project_role(status_code=404, project_id=1)
    assert client.get(URL, headers=auth()).status_code == 404


def test_the_body_must_be_a_boolean(client, auth, project_role):
    project_role(role="owner", project_id=1)
    assert client.put(URL, json={"collect_manual": "no"}, headers=auth()).status_code == 422
    assert client.put(URL, json={}, headers=auth()).status_code == 422
