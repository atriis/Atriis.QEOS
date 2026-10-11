import atexit
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.project.api.main import app
from src.project.core.config import settings
from src.project.db.base import Base
from src.project.db.session import get_db
from src.project.models import Project, Repository  # noqa: F401  registers tables

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
    """A respx router active for the test. Any outgoing request without a matching route
    raises, so a test can never silently reach the real network."""
    with respx.mock(assert_all_called=False) as router:
        yield router


ORG_ME_URL = "{base}/api/v1/organizations/{org_id}/members/me"


@pytest.fixture
def org_role(http):
    """Mock organization-service's members/me for one org. Calling it again for the same org
    replaces the previous answer (respx replaces routes that share a name)."""
    import httpx

    def _set(role="owner", org_id=1, status_code=200, body=None, exc=None):
        route = http.get(
            ORG_ME_URL.format(base=settings.ORGANIZATION_SERVICE_URL, org_id=org_id), name=f"org-me-{org_id}"
        )
        if exc is not None:
            return route.mock(side_effect=exc)
        # Exactly the contract shape from the design spec, unless a test overrides the body
        return route.mock(return_value=httpx.Response(status_code, json={"role": role} if body is None else body))

    return _set


@pytest.fixture
def make_project(db):
    """Insert a live project directly, bypassing the API and its role checks."""

    def _make(org_id=1, name="Checkout E2E", slug=None, created_by=1):
        project = Project(
            organization_id=org_id,
            name=name,
            slug=slug or name.lower().replace(" ", "-"),
            settings={},
            created_by=created_by,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    return _make
