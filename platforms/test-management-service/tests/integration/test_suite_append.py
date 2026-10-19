"""Appending cases to a manual suite: new numbers go to the end, ones already in it are skipped."""
import pytest

from src.casebook.models import Case, Suite

BASE = "/api/v1/projects/1"


@pytest.fixture
def cases(client, auth, project_role):
    project_role("member")
    for title in ("Pays", "Logs in", "Searches", "Exits"):
        assert client.post(f"{BASE}/cases", json={"title": title}, headers=auth()).status_code == 201


def suite(client, auth, name="Smoke"):
    response = client.post(f"{BASE}/suites", json={"name": name}, headers=auth())
    assert response.status_code == 201, response.text
    return response.json()


def append(client, auth, suite_id, numbers):
    return client.post(f"{BASE}/suites/{suite_id}/cases/append", json={"cases": numbers}, headers=auth())


def test_append_skips_existing_keeps_order(client, auth, cases):
    s = suite(client, auth)
    client.put(f"{BASE}/suites/{s['id']}/cases", json={"cases": [3, 1]}, headers=auth())
    response = append(client, auth, s["id"], [1, 4, 2])
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["added"], body["already"]) == (2, 1)
    assert [c["number"] for c in body["suite"]["cases"]] == [3, 1, 4, 2]
    assert body["suite"]["case_count"] == 4


def test_append_to_repository_suite_is_409(client, auth, db, cases):
    row = Suite(project_id=1, name="Flights", created_by=1, origin="repository", workflow="suite-flights.yml")
    db.add(row)
    db.commit()
    response = append(client, auth, row.id, [1])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "repository_suite"


def test_append_over_1000_is_422(client, auth, db, cases):
    s = suite(client, auth)
    db.add_all(Case(project_id=1, number=n, title=f"bulk {n}", created_by=1) for n in range(100, 1100))
    db.commit()
    assert append(client, auth, s["id"], list(range(100, 1100))).status_code == 200
    response = append(client, auth, s["id"], [1])
    assert response.status_code == 422
    detail = client.get(f"{BASE}/suites/{s['id']}", headers=auth()).json()
    assert detail["case_count"] == 1000


def test_append_unknown_case_is_422(client, auth, cases):
    s = suite(client, auth)
    assert append(client, auth, s["id"], [1, 99]).status_code == 422
    assert client.get(f"{BASE}/suites/{s['id']}", headers=auth()).json()["case_count"] == 0


def test_append_duplicates_in_request_is_422(client, auth, cases):
    s = suite(client, auth)
    assert append(client, auth, s["id"], [2, 2]).status_code == 422
