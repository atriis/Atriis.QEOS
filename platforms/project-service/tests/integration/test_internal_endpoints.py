import base64
from datetime import datetime, timezone

import pytest

from src.project.core.config import settings
from src.project.models.project import Project

URL = "/internal/v1/projects/retention"
PASSWORD = "internal-test-password"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_USERNAME", "ingestion-service")
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", PASSWORD)


def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def test_correct_credentials_list_every_project_with_its_retention(client, configured, make_project, db):
    default = make_project(name="Default")
    custom = make_project(name="Custom")
    custom.settings = {"result_retention_days": 30}
    gone = make_project(name="Gone")
    gone.deleted_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    db.commit()

    response = client.get(URL, headers=basic("ingestion-service", PASSWORD))

    assert response.status_code == 200
    projects = response.json()["projects"]
    # When it was deleted, so the retention job can wait out a grace period before emptying it
    assert projects[2].pop("deleted_at").startswith("2026-09-01T12:00:00")
    assert projects == [
        {"project_id": default.id, "result_retention_days": 90, "deleted": False, "deleted_at": None, "legal_hold": False, "purge_state": None},
        {"project_id": custom.id, "result_retention_days": 30, "deleted": False, "deleted_at": None, "legal_hold": False, "purge_state": None},
        {"project_id": gone.id, "result_retention_days": 90, "deleted": True, "legal_hold": False, "purge_state": None},
    ]


@pytest.mark.parametrize("headers", [
    {},
    basic("ingestion-service", "wrong"),
    basic("someone-else", PASSWORD),
    {"Authorization": "Bearer not-basic"},
])
def test_missing_or_wrong_credentials_are_401(client, configured, headers):
    response = client.get(URL, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Basic"


def test_a_user_token_is_not_accepted(client, configured, auth):
    assert client.get(URL, headers=auth()).status_code == 401


def test_without_a_password_the_endpoint_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", "")
    response = client.get(URL, headers=basic("ingestion-service", ""))
    assert response.status_code == 503
    assert response.json() == {"detail": "Internal API is not configured"}


def test_internal_credentials_do_not_open_the_public_api(client, configured, make_project):
    project = make_project()
    assert client.get(f"/api/v1/projects/{project.id}", headers=basic("ingestion-service", PASSWORD)).status_code == 401


def test_the_endpoint_is_not_in_the_public_openapi(client):
    assert "/internal/v1/projects/retention" not in client.get("/api/v1/openapi.json").json()["paths"]


def pending_project(make_project, db, purge_state=None):
    project = make_project(name="Pending")
    project.deleted_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    project.purge_state = purge_state
    db.commit()
    return project


def test_purge_state_records_a_confirmed_step(client, configured, make_project, db):
    project = pending_project(make_project, db)
    response = client.post(f"/internal/v1/projects/{project.id}/purge-state", json={"step": "test_management"},
                           headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 204
    db.expire_all()
    assert set(db.get(Project, project.id).purge_state) == {"test_management"}
    feed = client.get(URL, headers=basic("ingestion-service", PASSWORD)).json()["projects"]
    assert set(feed[0]["purge_state"]) == {"test_management"}


def test_purge_state_of_a_live_project_is_409(client, configured, make_project):
    project = make_project()
    response = client.post(f"/internal/v1/projects/{project.id}/purge-state", json={"step": "ingestion"},
                           headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 409


def test_internal_delete_refuses_a_live_project(client, configured, make_project, db):
    project = make_project()
    response = client.delete(f"/internal/v1/projects/{project.id}", headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 409
    assert db.get(Project, project.id) is not None


def test_internal_delete_needs_both_steps(client, configured, make_project, db):
    project = pending_project(make_project, db, {"test_management": "2026-10-08T03:00:00+00:00"})
    response = client.delete(f"/internal/v1/projects/{project.id}", headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 409 and "ingestion" in response.json()["detail"]


def test_internal_delete_removes_the_project_and_its_rows(client, configured, make_project, db):
    from src.project.models.overview_layout import OverviewLayout
    from src.project.models.repository import Repository

    project = pending_project(make_project, db, {"test_management": "x", "ingestion": "y"})
    db.add(OverviewLayout(project_id=project.id, user_id=None, layout={}, version=1, updated_by=1))
    db.add(Repository(project_id=project.id, provider="github", owner="acme", name="r", full_name_key="acme/r",
                      url="https://github.com/acme/r", default_branch="main"))
    other = make_project(name="Other")
    db.commit()
    response = client.delete(f"/internal/v1/projects/{project.id}", headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 204
    db.expire_all()
    assert db.get(Project, project.id) is None
    assert db.query(OverviewLayout).filter_by(project_id=project.id).count() == 0
    assert db.query(Repository).filter_by(project_id=project.id).count() == 0
    assert db.get(Project, other.id) is not None
    again = client.delete(f"/internal/v1/projects/{project.id}", headers=basic("ingestion-service", PASSWORD))
    assert again.status_code == 204


def test_internal_purge_routes_need_the_credentials(client, configured, make_project, db):
    project = pending_project(make_project, db)
    assert client.delete(f"/internal/v1/projects/{project.id}").status_code == 401
    assert client.post(f"/internal/v1/projects/{project.id}/purge-state", json={"step": "ingestion"}).status_code == 401
