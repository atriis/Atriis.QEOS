"""Repository suites: suites that mirror the test repository's CI workflows are read-only."""
import pytest

from src.casebook.models import Suite

BASE = "/api/v1/projects/1"


@pytest.fixture
def member(project_role):
    project_role("member")


def test_list_returns_origin_fields(client, auth, member):
    created = client.post(f"{BASE}/suites", json={"name": "Smoke"}, headers=auth())
    assert created.status_code == 201
    [row] = client.get(f"{BASE}/suites", headers=auth()).json()
    assert row["origin"] == "manual" and row["workflow"] is None
    assert row["group_name"] is None and row["external_id"] is None
    assert row["shard"] is None and row["test_paths"] is None and row["source_repo"] is None


def test_repository_suite_is_read_only(client, auth, db, member):
    row = Suite(project_id=1, name="Flights amadeus non booking", created_by=1, origin="repository",
                workflow="suite-flights.yml", external_id="flights-amadeus-non-booking", group_name="Flights")
    db.add(row)
    db.commit()
    url = f"{BASE}/suites/{row.id}"
    responses = [
        client.patch(url, json={"name": "Renamed"}, headers=auth()),
        client.put(f"{url}/cases", json={"cases": []}, headers=auth()),
        client.delete(url, headers=auth()),
    ]
    for response in responses:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "repository_suite"
        assert response.json()["detail"]["message"] == "Managed by the repository: change the workflow instead."
    shown = client.get(url, headers=auth()).json()
    assert shown["origin"] == "repository" and shown["workflow"] == "suite-flights.yml"
    assert shown["group_name"] == "Flights"
