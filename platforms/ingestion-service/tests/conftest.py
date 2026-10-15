import atexit
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.ingestion.api.main import app
from src.ingestion.core.config import settings
from src.ingestion.db.base import Base
from src.ingestion.db.session import get_db
from src.ingestion.models import ApiKey, Run, RunResult  # noqa: F401  registers tables
from src.ingestion.models.run import FULL_SCOPE

# The service resumes queued log-value scans at start-up on its own database (ADR-032); TestClient runs start-up
# hooks, and the tests drive scans themselves
settings.LOG_SCAN_RESUME_ON_STARTUP = False

# A database file of this run's own: two runs of the suite at once (two terminals, two agents) used to share
# ./test.db and drop each other's tables mid-test
_DB_DIR = tempfile.mkdtemp(prefix="qeos-tests-")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{Path(_DB_DIR, 'test.db').as_posix()}"
atexit.register(lambda: (engine.dispose(), shutil.rmtree(_DB_DIR, ignore_errors=True)))

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_md5(dbapi_connection, _record):
    """PostgreSQL's md5(text) for SQLite, so the impact rollup's SQL runs here unchanged (models/impact.unit_hash)."""
    from src.ingestion.models.impact import unit_hash

    dbapi_connection.create_function("md5", 1, lambda value: None if value is None else unit_hash(value),
                                     deterministic=True)
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
    from src.ingestion.api.main import HEARTBEATS

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    # /metrics reads job_heartbeats through its own sessions: point them at the test database
    previous = HEARTBEATS.session_factory
    HEARTBEATS.session_factory = TestingSessionLocal
    try:
        with TestClient(app) as c:
            yield c
    finally:
        HEARTBEATS.session_factory = previous
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
    import httpx

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


@pytest.fixture
def make_key(db):
    """Insert an API key directly; returns (row, plaintext key)."""
    from datetime import datetime, timezone

    from src.ingestion.utils.keys import display_prefix, generate_key, hash_key

    def _make(project_id=1, organization_id=10, name="ci", revoked=False, can_read_impact=False):
        key = generate_key()
        row = ApiKey(
            project_id=project_id, organization_id=organization_id, name=name,
            key_prefix=display_prefix(key), key_hash=hash_key(key), created_by=1,
            revoked_at=datetime.now(timezone.utc) if revoked else None, can_read_impact=can_read_impact,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row, key

    return _make


# ---- report (docs/superpowers/specs/2026-10-08-report-deep-analysis-design.md) ----
REPORT_NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
REPORT_URL = "/api/v1/projects/1/analytics/report"


def report_key(name: str) -> str:
    """The test_key seed_run gives a result named `name` (suite "s", class "C")."""
    from src.ingestion.service.ingest_service import test_key
    return test_key("s", "C", name)


@pytest.fixture
def report_now(monkeypatch):
    """Freeze the report endpoint's clock at REPORT_NOW (Thursday 8 October 2026, 12:00 UTC)."""
    from src.ingestion.api.v1.endpoints import report
    monkeypatch.setattr(report, "_now", lambda: REPORT_NOW)
    return REPORT_NOW


@pytest.fixture
def seed_run(db, make_key):
    """seed_run(started_at, results=((name, status, duration_ms[, message]), ...), **run fields) inserts
    one run. A name listed twice is a retry: two rows with the same key, later rows win."""
    from collections import Counter

    keys = {}

    def _seed(started_at, results=(("t1", "passed", 10),), project_id=1, branch="main", environment=None,
              ci_provider="local", ci_run_url=None, duration_ms=1000, commit_sha=None, scope=FULL_SCOPE,
              stages=None):
        if project_id not in keys:
            keys[project_id] = make_key(project_id=project_id)[0]
        counts = Counter(r[1] for r in results)
        run = Run(project_id=project_id, api_key_id=keys[project_id].id, request_hash="h", ci_provider=ci_provider,
                  ci_run_url=ci_run_url, branch=branch, environment=environment, commit_sha=commit_sha,
                  scope=scope, stages=stages,
                  started_at=started_at, finished_at=started_at + timedelta(seconds=1), duration_ms=duration_ms,
                  total=len(results), passed=counts["passed"], failed=counts["failed"],
                  skipped=counts["skipped"], errored=counts["errored"], created_at=started_at)
        db.add(run)
        db.flush()
        for r in results:
            name, status, duration = r[0], r[1], r[2]
            message = r[3] if len(r) > 3 else (None if status in ("passed", "skipped") else f"{name} {status}")
            db.add(RunResult(run_id=run.id, test_key=report_key(name), suite="s", class_name="C", name=name,
                             status=status, duration_ms=duration, message=message))
        db.commit()
        return run

    return _seed


@pytest.fixture
def seed_change_run(db, seed_run):
    """seed_change_run(started_at, results, paths=("src/app.py",), truncated=False, base_branch=None, **seed_run fields):
    a run with changed files, stored as an upload with `changes` stores it (test impact, spec 2026-10-12). Without a
    base branch the diff's base ref is a single commit ("abc1234^"), as the collector sends outside pull requests."""
    from src.ingestion.models import RunChangedFile

    def _seed(started_at, results=(("t1", "passed", 10),), paths=("src/app.py",), truncated=False, base_branch=None,
              **fields):
        run = seed_run(started_at, results=results, **fields)
        run.base_branch = base_branch
        run.change_base_ref = f"origin/{base_branch}" if base_branch else "abc1234^"
        run.changed_files = len(paths)
        run.additions, run.deletions = len(paths), 0
        run.changes_truncated = truncated
        for path in paths:
            db.add(RunChangedFile(run_id=run.id, path=path, status="M", additions=1, deletions=0))
        db.commit()
        return run

    return _seed


@pytest.fixture
def seed_impact_history(seed_change_run):
    """seed_impact_history(start, branch="main", project_id=1) -> runs: 15 runs with changed files, one a day from
    `start`. The first 11 change docs/guide.md and `pays` passes; the last 4 change src/pay/api.py and `pays` passes,
    fails, passes, fails. So `pays` newly failed in 2 of the 4 runs that changed src/pay/ (confidence 0.5) and in 2 of
    15 overall (base rate 0.1333, lift 3.75), and is not flaky (3 flips in 14 pairs, under the Flaky view's 0.3).
    `steady` passes in every run."""

    def _seed(start, branch="main", project_id=1):
        runs = []
        statuses = ["passed"] * 11 + ["passed", "failed", "passed", "failed"]
        for day, status in enumerate(statuses):
            paths = ("docs/guide.md",) if day < 11 else ("src/pay/api.py",)
            runs.append(seed_change_run(start + timedelta(days=day), results=(("pays", status, 5), ("steady", "passed", 5)),
                                        paths=paths, branch=branch, project_id=project_id))
        return runs

    return _seed


def post_report(client, auth, **body):
    """POST the report with a 7-day UTC period (1-7 October 2026) unless the body says otherwise."""
    payload = {"from": "2026-10-01", "to": "2026-10-07", "tz": "UTC", "sections": ["summary"], **body}
    return client.post(REPORT_URL, json=payload, headers=auth())
