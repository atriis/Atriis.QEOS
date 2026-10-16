import httpx
import pytest

from conftest import project_body
from src.ingestion.utils import project_client


def test_returns_role_and_organization_and_forwards_only_the_callers_token(project_role):
    route = project_role("admin", project_id=7, organization_id=42)
    info = project_client.get_project(7, "caller-token")
    assert info == project_client.ProjectInfo(role="admin", organization_id=42)
    assert route.calls.last.request.headers["Authorization"] == "Bearer caller-token"


def test_404_is_project_not_found(project_role):
    project_role(project_id=7, status_code=404, body={"detail": "Project not found"})
    with pytest.raises(project_client.ProjectNotFound):
        project_client.get_project(7, "t")


def test_401_is_invalid_credentials(project_role):
    project_role(project_id=7, status_code=401, body={"detail": "Could not validate credentials"})
    with pytest.raises(project_client.InvalidCredentials):
        project_client.get_project(7, "t")


@pytest.mark.parametrize("status_code", [403, 500, 502, 503])
def test_other_statuses_are_unavailable(project_role, status_code):
    project_role(project_id=7, status_code=status_code, body={"detail": "x"})
    with pytest.raises(project_client.ProjectServiceUnavailable):
        project_client.get_project(7, "t")


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")])
def test_network_failures_are_unavailable(project_role, exc):
    project_role(project_id=7, exc=exc)
    with pytest.raises(project_client.ProjectServiceUnavailable):
        project_client.get_project(7, "t")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(my_role="superuser"),
        lambda b: b.pop("my_role"),
        lambda b: b.update(organization_id="42"),
        lambda b: b.update(organization_id=True),
        lambda b: b.pop("organization_id"),
    ],
)
def test_200_outside_the_contract_is_unavailable(project_role, mutate):
    body = project_body(7, 42, "admin")
    mutate(body)
    project_role(project_id=7, body=body)
    with pytest.raises(project_client.ProjectServiceUnavailable):
        project_client.get_project(7, "t")


def test_non_json_200_is_unavailable(http):
    from src.ingestion.core.config import settings

    http.get(f"{settings.PROJECT_SERVICE_URL}/api/v1/projects/7", name="project-7").mock(
        return_value=httpx.Response(200, text="<html>")
    )
    with pytest.raises(project_client.ProjectServiceUnavailable):
        project_client.get_project(7, "t")


def test_trailing_slash_in_the_configured_url(http, monkeypatch):
    from src.ingestion.core.config import settings

    monkeypatch.setattr(settings, "PROJECT_SERVICE_URL", "http://projects.test/")
    route = http.get("http://projects.test/api/v1/projects/7").mock(
        return_value=httpx.Response(200, json=project_body(7, 42, "viewer"))
    )
    assert project_client.get_project(7, "t").role == "viewer"
    assert route.called


def test_410_a_project_pending_deletion_is_project_not_found(project_role):
    project_role(project_id=7, status_code=410, body={"detail": {"code": "pending_deletion"}})
    with pytest.raises(project_client.ProjectNotFound):
        project_client.get_project(7, "t")
