"""Overview layouts: /api/v1/projects/{id}/overview-layout (spec 2026-10-11 §3.3, §3.4; plan Rulings 4-7)."""
import json

import pytest

ALL_ROLES = ("owner", "admin", "member", "viewer", "billing_manager")
LIMIT = 65536


def url(project_id: int, path: str = "") -> str:
    return f"/api/v1/projects/{project_id}/overview-layout{path}"


def layout(*types: str) -> dict:
    return {"schema": 1, "widgets": [{"id": f"w{i + 1}", "type": t, "size": "normal"} for i, t in enumerate(types)]}


def put(client, auth, project_id, scope, body_layout, version, user=1):
    return client.put(url(project_id, f"/{scope}"), json={"layout": body_layout, "version": version}, headers=auth(user))


def put_bytes(client, auth, project_id, scope, raw: bytes, user=1):
    headers = {**auth(user), "Content-Type": "application/json"}
    return client.put(url(project_id, f"/{scope}"), content=raw, headers=headers)


# (method, path, body, roles allowed, success status): the endpoint table of spec §3.3
ROUTES = [
    ("GET", "", None, ALL_ROLES, 200),
    ("PUT", "/personal", {"layout": layout("latest_run"), "version": 0}, ALL_ROLES, 200),
    ("DELETE", "/personal", None, ALL_ROLES, 204),
    ("PUT", "/project", {"layout": layout("latest_run"), "version": 0}, ("owner", "admin"), 200),
    ("DELETE", "/project", None, ("owner", "admin"), 204),
]


@pytest.mark.parametrize("method, path, body, allowed, ok", ROUTES)
@pytest.mark.parametrize("role", ALL_ROLES)
def test_role_matrix(client, auth, org_role, make_project, method, path, body, allowed, ok, role):
    project = make_project()
    org_role(role)
    response = client.request(method, url(project.id, path), json=body, headers=auth())
    assert response.status_code == (ok if role in allowed else 403)


@pytest.mark.parametrize("method, path, body, allowed, ok", ROUTES)
def test_a_non_member_gets_404_everywhere(client, auth, org_role, make_project, method, path, body, allowed, ok):
    project = make_project()
    org_role(status_code=404, body={"detail": "Not a member"})
    assert client.request(method, url(project.id, path), json=body, headers=auth()).status_code == 404


def test_a_deleted_projects_layouts_are_unreachable(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    put(client, auth, project.id, "project", layout("latest_run"), 0)
    assert client.delete(f"/api/v1/projects/{project.id}", headers=auth()).status_code == 204
    assert client.get(url(project.id), headers=auth()).status_code == 404


def test_nothing_saved_is_the_builtin_default(client, auth, org_role, make_project):
    project = make_project()
    org_role("viewer")
    assert client.get(url(project.id), headers=auth()).json() == {
        "effective": None, "source": "builtin", "personal": None, "project": None,
    }


def test_the_project_default_reaches_everyone_without_a_personal_layout(client, auth, org_role, make_project):
    project = make_project()
    org_role("admin")
    saved = put(client, auth, project.id, "project", layout("pass_rate_trend"), 0, user=3)
    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    assert saved.json()["updated_by"] == 3
    assert saved.json()["layout"] == layout("pass_rate_trend")
    org_role("viewer")
    body = client.get(url(project.id), headers=auth(9)).json()
    assert body["source"] == "project"
    assert body["effective"] == layout("pass_rate_trend")
    assert body["personal"] is None
    assert body["project"]["version"] == 1
    assert body["project"]["updated_by"] == 3
    assert body["project"]["layout"] == layout("pass_rate_trend")


def test_a_personal_layout_wins_and_belongs_to_its_user_only(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    put(client, auth, project.id, "project", layout("latest_run"), 0)
    org_role("viewer")
    assert put(client, auth, project.id, "personal", layout("my_suites"), 0, user=5).status_code == 200
    mine = client.get(url(project.id), headers=auth(5)).json()
    assert mine["source"] == "personal"
    assert mine["effective"] == layout("my_suites")
    assert mine["personal"]["version"] == 1
    # Reset and "Edit project default" need the default even when the personal layout wins
    assert mine["project"]["layout"] == layout("latest_run")
    other = client.get(url(project.id), headers=auth(6)).json()
    assert other["source"] == "project"
    assert other["effective"] == layout("latest_run")


def test_each_save_bumps_the_version(client, auth, org_role, make_project):
    project = make_project()
    org_role("member")
    put(client, auth, project.id, "personal", layout("latest_run"), 0, user=5)
    second = put(client, auth, project.id, "personal", layout("coverage"), 1, user=5)
    assert second.status_code == 200
    assert second.json()["version"] == 2
    assert second.json()["layout"] == layout("coverage")


def test_a_stale_version_is_409_with_the_stored_row(client, auth, org_role, make_project):
    project = make_project()
    org_role("admin")
    put(client, auth, project.id, "project", layout("latest_run"), 0, user=3)
    put(client, auth, project.id, "project", layout("coverage"), 1, user=4)  # someone saved in between
    stale = put(client, auth, project.id, "project", layout("my_suites"), 1, user=3)
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "stale_version"
    assert detail["current"]["version"] == 2
    assert detail["current"]["updated_by"] == 4
    assert detail["current"]["updated_at"]
    assert client.get(url(project.id), headers=auth(3)).json()["effective"] == layout("coverage")


def test_creating_over_an_existing_layout_is_409(client, auth, org_role, make_project):
    project = make_project()
    org_role("viewer")
    put(client, auth, project.id, "personal", layout("latest_run"), 0, user=5)
    again = put(client, auth, project.id, "personal", layout("coverage"), 0, user=5)
    assert again.status_code == 409
    assert again.json()["detail"]["current"]["version"] == 1


def test_updating_a_layout_that_is_gone_is_409_without_a_row(client, auth, org_role, make_project):
    project = make_project()
    org_role("viewer")
    response = put(client, auth, project.id, "personal", layout("latest_run"), 3, user=5)
    assert response.status_code == 409
    assert response.json()["detail"]["current"] is None


def test_reset_personal_falls_back_to_the_project_default(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    put(client, auth, project.id, "project", layout("latest_run"), 0)
    put(client, auth, project.id, "personal", layout("coverage"), 0)
    assert client.delete(url(project.id, "/personal"), headers=auth()).status_code == 204
    body = client.get(url(project.id), headers=auth()).json()
    assert body["source"] == "project"
    assert body["personal"] is None


def test_deleting_the_default_falls_back_to_builtin(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    put(client, auth, project.id, "project", layout("latest_run"), 0)
    assert client.delete(url(project.id, "/project"), headers=auth()).status_code == 204
    assert client.get(url(project.id), headers=auth()).json()["source"] == "builtin"


def test_deleting_what_is_not_there_is_still_204(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    assert client.delete(url(project.id, "/personal"), headers=auth()).status_code == 204
    assert client.delete(url(project.id, "/project"), headers=auth()).status_code == 204


def test_a_departed_users_layout_is_not_served_and_returns_if_they_rejoin(client, auth, org_role, make_project):
    project = make_project()
    org_role("member")
    put(client, auth, project.id, "personal", layout("my_suites"), 0, user=5)
    org_role(status_code=404, body={"detail": "Not a member"})  # removed from the organization
    assert client.get(url(project.id), headers=auth(5)).status_code == 404
    org_role("viewer")  # invited back
    assert client.get(url(project.id), headers=auth(5)).json()["source"] == "personal"


@pytest.mark.parametrize("bad", [
    {"layout": {"schema": 2, "widgets": []}, "version": 0},
    {"layout": layout("marketplace"), "version": 0},
    {"layout": layout("latest_run"), "version": -1},
    {"layout": layout("latest_run"), "version": True},
    {"layout": layout("latest_run"), "version": 1.0},
    {"layout": layout("latest_run")},
    {"layout": layout("latest_run"), "version": 0, "extra": True},
])
def test_invalid_bodies_are_422(client, auth, org_role, make_project, bad):
    project = make_project()
    org_role("owner")
    assert client.put(url(project.id, "/personal"), json=bad, headers=auth()).status_code == 422


def test_a_viewer_is_refused_the_default_before_the_body_is_judged(client, auth, org_role, make_project):
    project = make_project()
    org_role("viewer")
    response = client.put(url(project.id, "/project"), json={"layout": {"schema": 9}, "version": 0}, headers=auth())
    assert response.status_code == 403


def _padded(total: int) -> bytes:
    """A valid PUT body of exactly `total` bytes: trailing JSON whitespace makes up the difference."""
    raw = json.dumps({"layout": layout("latest_run"), "version": 0}).encode()
    return raw + b" " * (total - len(raw))


def test_a_body_of_exactly_the_limit_is_accepted(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    raw = _padded(LIMIT)
    assert len(raw) == LIMIT
    assert put_bytes(client, auth, project.id, "personal", raw).status_code == 200


def test_a_body_one_byte_over_the_limit_is_422(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    raw = _padded(LIMIT + 1)
    assert len(raw) == LIMIT + 1
    response = put_bytes(client, auth, project.id, "personal", raw)
    assert response.status_code == 422
    assert "64 KB" in response.text


def test_the_body_limit_is_judged_after_the_role(client, auth, org_role, make_project):
    project = make_project()
    org_role("viewer")
    assert put_bytes(client, auth, project.id, "project", _padded(LIMIT + 1)).status_code == 403


def test_the_largest_valid_layout_fits(client, auth, org_role, make_project):
    """24 widgets with 255-character settings of 4-byte UTF-8 characters, sent unescaped, on types that declare them."""
    project = make_project()
    org_role("owner")
    text = "\U0001F600" * 255
    widgets = []
    for i in range(24):
        if i % 2:
            widgets.append({"id": f"w{i}", "type": "my_failures", "size": "wide", "settings": {"author": text, "rows": 10}})
        else:
            widgets.append({"id": f"w{i}", "type": "slowest_tests", "size": "wide",
                            "settings": {"period": 30, "branch": text, "rows": 10}})
    raw = json.dumps({"layout": {"schema": 1, "widgets": widgets}, "version": 0}, ensure_ascii=False).encode("utf-8")
    assert len(raw) <= LIMIT
    assert put_bytes(client, auth, project.id, "personal", raw).status_code == 200


def test_get_reports_the_same_updated_at_as_the_save(client, auth, org_role, make_project):
    project = make_project()
    org_role("member")
    saved = put(client, auth, project.id, "personal", layout("latest_run"), 0, user=5).json()
    fetched = client.get(url(project.id), headers=auth(5)).json()
    assert fetched["personal"]["updated_at"] == saved["updated_at"]


def test_a_create_that_loses_the_race_is_409_with_the_stored_row(client, auth, org_role, make_project, monkeypatch):
    from src.project.service import overview_layout_service as service

    project = make_project()
    org_role("member")
    assert put(client, auth, project.id, "personal", layout("latest_run"), 0, user=5).status_code == 200
    real, calls = service.get_row, []

    def row_missing_once(*args, **kwargs):
        calls.append(args)
        return None if len(calls) == 1 else real(*args, **kwargs)  # the first look misses a row that is already there

    monkeypatch.setattr(service, "get_row", row_missing_once)
    response = put(client, auth, project.id, "personal", layout("coverage"), 0, user=5)  # insert hits the unique index
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_version"
    assert response.json()["detail"]["current"]["version"] == 1
