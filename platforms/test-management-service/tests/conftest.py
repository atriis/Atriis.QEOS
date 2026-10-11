import atexit
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.casebook.api.main import app
from src.casebook.core.config import settings
from src.casebook.db.base import Base
from src.casebook.db.session import get_db
import src.casebook.models  # noqa: F401  registers tables

# A database file of this run's own: two runs of the suite at once (two terminals, two agents) used to share
# ./test.db and drop each other's tables mid-test
_DB_DIR = tempfile.mkdtemp(prefix="qeos-tests-")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{Path(_DB_DIR, 'test.db').as_posix()}"
atexit.register(lambda: (engine.dispose(), shutil.rmtree(_DB_DIR, ignore_errors=True)))

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def make_token(user_id: int, **claims) -> str:
    payload = {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5), **claims}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth():
    """auth(user_id) -> headers carrying a valid access token for that user."""

    def _auth(user_id: int = 1) -> dict:
        return {"Authorization": f"Bearer {make_token(user_id)}"}

    return _auth


@pytest.fixture
def http():
    """A respx router active for the test; any outgoing request without a route raises."""
    with respx.mock(assert_all_called=False) as router:
        yield router


PROJECT_URL = "{base}/api/v1/projects/{project_id}"


def project_body(project_id: int, organization_id: int, role: str) -> dict:
    """The shape project-service's GET /projects/{id} returns (ProjectOut)."""
    return {
        "id": project_id, "organization_id": organization_id, "name": f"P{project_id}", "slug": f"p{project_id}",
        "description": None,
        "settings": {"result_retention_days": 90, "default_environment": None, "notify_on_failure": False},
        "created_by": 1, "created_at": "2026-09-29T00:00:00Z", "updated_at": None, "my_role": role,
    }


@pytest.fixture
def project_role(http):
    """Mock project-service's GET /projects/{id} for one project; calling it again for the same
    project replaces the answer (respx replaces routes that share a name)."""
    def _set(role="owner", project_id=1, organization_id=10, status_code=200, body=None, exc=None):
        route = http.get(
            PROJECT_URL.format(base=settings.PROJECT_SERVICE_URL, project_id=project_id),
            name=f"project-{project_id}",
        )
        if exc is not None:
            return route.mock(side_effect=exc)
        payload = project_body(project_id, organization_id, role) if body is None else body
        return route.mock(return_value=httpx.Response(status_code, json=payload))

    return _set


GH = "https://api.github.com"


@pytest.fixture
def secrets_key(monkeypatch):
    """TM_SECRETS_KEY set to a fresh Fernet key for this test."""
    monkeypatch.setattr(settings, "TM_SECRETS_KEY", Fernet.generate_key().decode())


@pytest.fixture
def no_secrets_key(monkeypatch):
    monkeypatch.setattr(settings, "TM_SECRETS_KEY", "")


class GitHubStub:
    """GitHub's REST API on the test's respx router: each method answers one endpoint, and a later
    call with the same name replaces the earlier answer. Nothing reaches the real api.github.com."""

    repo = "acme/obt"
    workflow = "qeos-run.yml"

    def __init__(self, router):
        self.router = router

    def _url(self, path: str) -> str:
        return f"{GH}/repos/{self.repo}{path}"

    def check(self, status=200, workflow_status=None, expires="2027-03-12 00:00:00 UTC", headers=None):
        extra = {"github-authentication-token-expiration": expires} if expires else {}
        extra.update(headers or {})
        self.router.get(self._url(""), name="gh-repo").mock(
            return_value=httpx.Response(status, json={"full_name": self.repo}, headers=extra))
        return self.router.get(self._url(f"/actions/workflows/{self.workflow}"), name="gh-workflow").mock(
            return_value=httpx.Response(workflow_status if workflow_status is not None else status,
                                        json={"id": 1, "path": f".github/workflows/{self.workflow}"}))

    def dispatch(self, run_id=None, status=None, headers=None):
        """With run_id: GitHub's 200 with run details (return_run_details). Without: a 204, the fallback."""
        if run_id is not None:
            body = {"workflow_run_id": run_id, "run_url": f"{GH}/repos/{self.repo}/actions/runs/{run_id}",
                    "html_url": f"https://github.com/{self.repo}/actions/runs/{run_id}"}
            response = httpx.Response(status or 200, json=body, headers=headers or {})
        else:
            response = httpx.Response(status or 204, headers=headers or {})
        return self.router.post(self._url(f"/actions/workflows/{self.workflow}/dispatches"), name="gh-dispatch").mock(
            return_value=response)

    def runs(self, *runs):
        return self.router.get(self._url(f"/actions/workflows/{self.workflow}/runs"), name="gh-runs").mock(
            return_value=httpx.Response(200, json={"total_count": len(runs), "workflow_runs": list(runs)}))

    def run(self, body):
        return self.router.get(self._url(f"/actions/runs/{body['id']}"), name=f"gh-run-{body['id']}").mock(
            return_value=httpx.Response(200, json=body))

    def cancel(self, run_id, status=202):
        return self.router.post(self._url(f"/actions/runs/{run_id}/cancel"), name=f"gh-cancel-{run_id}").mock(
            return_value=httpx.Response(status, json={}))

    def run_body(self, run_id, request_id, status="queued", conclusion=None, title=None,
                 created_at="2026-10-07T10:00:05Z"):
        return {"id": run_id, "display_title": title or f"QEOS #{request_id}", "status": status,
                "conclusion": conclusion, "event": "workflow_dispatch", "created_at": created_at,
                "html_url": f"https://github.com/{self.repo}/actions/runs/{run_id}"}


@pytest.fixture
def github(http):
    return GitHubStub(http)
