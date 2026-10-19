"""suite=none: imported, live cases that no repository suite holds."""
import pytest

from src.casebook.models import Case, Suite, SuiteCase

P = "/api/v1/projects/1"


def feature(name, *scenarios):
    return f"Feature: {name}\n" + "".join(f"  Scenario: {s}\n    Given {s}\n" for s in scenarios)


@pytest.fixture
def seeded(client, auth, db, project_role):
    project_role("member")
    files = [{"path": "tests/features/a.feature", "content": feature("A", "in repo suite", "in manual suite",
                                                                       "in none", "archived one")}]
    assert client.post(f"{P}/cases/import", json={"files": files}, headers=auth()).status_code == 200
    client.post(f"{P}/cases", json={"title": "manual case"}, headers=auth())
    ids = {c.title: c.id for c in db.query(Case).all()}
    repo = Suite(project_id=1, name="Repo", created_by=1, origin="repository")
    manual = Suite(project_id=1, name="Manual", created_by=1)
    db.add_all([repo, manual])
    db.flush()
    db.add_all([
        SuiteCase(suite_id=repo.id, case_id=ids["in repo suite"], position=0),
        SuiteCase(suite_id=manual.id, case_id=ids["in manual suite"], position=0),
    ])
    db.query(Case).filter(Case.id == ids["archived one"]).update({"status": "archived"})
    db.commit()


EXPECTED = ["in manual suite", "in none"]


def test_none_lists_imported_cases_in_no_repository_suite(client, auth, seeded):
    response = client.get(f"{P}/cases?suite=none", headers=auth())
    assert response.status_code == 200, response.text
    assert sorted(c["title"] for c in response.json()["items"]) == EXPECTED
    assert response.json()["total"] == 2


def test_none_through_search(client, auth, seeded):
    response = client.post(f"{P}/cases/search", json={"suite": "none"}, headers=auth())
    assert response.status_code == 200, response.text
    assert sorted(c["title"] for c in response.json()["items"]) == EXPECTED


def test_other_suite_values_are_422(client, auth, seeded):
    assert client.get(f"{P}/cases?suite=3", headers=auth()).status_code == 422
    assert client.post(f"{P}/cases/search", json={"suite": "3"}, headers=auth()).status_code == 422
