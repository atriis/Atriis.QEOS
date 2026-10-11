"""Suites: a named, ordered list of a project's cases."""
import pytest

BASE = "/api/v1/projects/1"


@pytest.fixture
def cases(client, auth, project_role):
    project_role("member")
    for title in ("Pays", "Logs in", "Searches"):
        assert client.post(f"{BASE}/cases", json={"title": title}, headers=auth()).status_code == 201


def suite(client, auth, name="Smoke", **body):
    response = client.post(f"{BASE}/suites", json={"name": name, **body}, headers=auth())
    assert response.status_code == 201, response.text
    return response.json()


def test_create_list_and_rename(client, auth, cases):
    created = suite(client, auth, description="Before every deploy")
    assert (created["name"], created["description"], created["case_count"]) == ("Smoke", "Before every deploy", 0)
    renamed = client.patch(f"{BASE}/suites/{created['id']}", json={"name": "Smoke (web)"}, headers=auth()).json()
    assert renamed["name"] == "Smoke (web)"
    assert [s["name"] for s in client.get(f"{BASE}/suites", headers=auth()).json()] == ["Smoke (web)"]


def test_names_are_unique_per_project(client, auth, cases):
    suite(client, auth)
    assert client.post(f"{BASE}/suites", json={"name": "Smoke"}, headers=auth()).status_code == 409
    other = suite(client, auth, name="Regression")
    assert client.patch(f"{BASE}/suites/{other['id']}", json={"name": "Smoke"}, headers=auth()).status_code == 409


def test_cases_are_set_in_order_and_reordered_by_replacing_the_list(client, auth, cases):
    s = suite(client, auth)
    body = client.put(f"{BASE}/suites/{s['id']}/cases", json={"cases": [3, 1]}, headers=auth()).json()
    assert [c["number"] for c in body["cases"]] == [3, 1] and body["case_count"] == 2
    body = client.put(f"{BASE}/suites/{s['id']}/cases", json={"cases": [1, 2, 3]}, headers=auth()).json()
    assert [c["title"] for c in body["cases"]] == ["Pays", "Logs in", "Searches"]
    detail = client.get(f"{BASE}/suites/{s['id']}", headers=auth()).json()
    assert [c["key"] for c in detail["cases"]] == ["TC-1", "TC-2", "TC-3"]


@pytest.mark.parametrize("numbers", [[1, 1], [99], list(range(1, 1002))])
def test_bad_case_lists_are_422(client, auth, cases, numbers):
    s = suite(client, auth)
    assert client.put(f"{BASE}/suites/{s['id']}/cases", json={"cases": numbers}, headers=auth()).status_code == 422


def test_another_projects_cases_cannot_be_added(client, auth, cases, project_role):
    project_role("member", project_id=2)
    client.post("/api/v1/projects/2/cases", json={"title": "Elsewhere"}, headers=auth())
    s = suite(client, auth)
    # Number 4 does not exist in project 1, whatever project 2 has
    assert client.put(f"{BASE}/suites/{s['id']}/cases", json={"cases": [4]}, headers=auth()).status_code == 422


def test_deleting_a_suite_keeps_its_cases(client, auth, cases):
    s = suite(client, auth)
    client.put(f"{BASE}/suites/{s['id']}/cases", json={"cases": [1]}, headers=auth())
    assert client.delete(f"{BASE}/suites/{s['id']}", headers=auth()).status_code == 204
    assert client.get(f"{BASE}/suites/{s['id']}", headers=auth()).status_code == 404
    assert client.get(f"{BASE}/cases/1", headers=auth()).status_code == 200


def test_archived_cases_stay_in_a_suite_marked(client, auth, cases):
    s = suite(client, auth)
    client.put(f"{BASE}/suites/{s['id']}/cases", json={"cases": [1, 2]}, headers=auth())
    client.patch(f"{BASE}/cases/2", json={"status": "archived"}, headers=auth())
    detail = client.get(f"{BASE}/suites/{s['id']}", headers=auth()).json()
    assert [(c["number"], c["status"]) for c in detail["cases"]] == [(1, "draft"), (2, "archived")]


def test_a_case_lists_its_suites(client, auth, cases):
    a, b = suite(client, auth), suite(client, auth, name="Regression")
    client.put(f"{BASE}/suites/{a['id']}/cases", json={"cases": [1]}, headers=auth())
    client.put(f"{BASE}/suites/{b['id']}/cases", json={"cases": [1, 2]}, headers=auth())
    assert [s["name"] for s in client.get(f"{BASE}/cases/1", headers=auth()).json()["suites"]] == ["Regression", "Smoke"]


def test_another_projects_suite_is_404(client, auth, cases, project_role):
    s = suite(client, auth)
    project_role("member", project_id=2)
    assert client.get(f"/api/v1/projects/2/suites/{s['id']}", headers=auth()).status_code == 404


def test_viewers_read_suites_but_cannot_change_them(client, auth, cases, project_role):
    s = suite(client, auth)
    project_role("viewer")
    assert client.get(f"{BASE}/suites/{s['id']}", headers=auth()).status_code == 200
    assert client.put(f"{BASE}/suites/{s['id']}/cases", json={"cases": [1]}, headers=auth()).status_code == 403
    assert client.delete(f"{BASE}/suites/{s['id']}", headers=auth()).status_code == 403


def test_suite_detail_carries_source_path_null_for_manual_cases(client, auth, cases, db):
    from src.casebook.models import Case
    db.query(Case).filter(Case.number == 2).one().source_path = "tests/features/login.feature"
    db.commit()
    s = suite(client, auth)
    client.put(f"{BASE}/suites/{s['id']}/cases", json={"cases": [1, 2]}, headers=auth())
    detail = client.get(f"{BASE}/suites/{s['id']}", headers=auth()).json()
    assert [c["source_path"] for c in detail["cases"]] == [None, "tests/features/login.feature"]


def test_created_by_me_lists_only_the_callers_suites(client, auth, project_role):
    project_role("member")
    assert client.post(f"{BASE}/suites", json={"name": "Mine"}, headers=auth(1)).status_code == 201
    assert client.post(f"{BASE}/suites", json={"name": "Theirs"}, headers=auth(2)).status_code == 201
    mine = client.get(f"{BASE}/suites", params={"created_by": "me"}, headers=auth(1)).json()
    assert [s["name"] for s in mine] == ["Mine"]
    everyone = client.get(f"{BASE}/suites", headers=auth(1)).json()
    assert [s["name"] for s in everyone] == ["Mine", "Theirs"]


def test_created_by_me_combines_with_search(client, auth, project_role):
    project_role("member")
    for name in ("Smoke", "Regression"):
        client.post(f"{BASE}/suites", json={"name": name}, headers=auth(1))
    found = client.get(f"{BASE}/suites", params={"created_by": "me", "search": "smo"}, headers=auth(1)).json()
    assert [s["name"] for s in found] == ["Smoke"]


@pytest.mark.parametrize("value", ["someone", "1", ""])
def test_created_by_takes_only_me(client, auth, project_role, value):
    project_role("viewer")
    assert client.get(f"{BASE}/suites", params={"created_by": value}, headers=auth()).status_code == 422
