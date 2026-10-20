"""The screenshot paths SQLite cannot test (ADR-036): the FOR KEY SHARE lock on the blobs an upload links and the
savepoint around the link insert, on a real PostgreSQL. Skipped unless QEOS_TEST_POSTGRES_URL is set.

Each test drops and creates the ingestion tables (Base.metadata) around itself, so the URL must name a scratch database
on localhost or 127.0.0.1 whose name contains "test" or "scratch"; anything else ends the run before it connects.

Run from platforms/ingestion-service, with `pip install -r requirements.txt` done. In bash:

    docker run -d --rm --name qeos-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=qeos_test -p 55432:5432 postgres:16-alpine
    until docker exec qeos-pg pg_isready -U postgres -d qeos_test; do sleep 1; done
    SECRET_KEY=x QEOS_TEST_POSTGRES_URL=postgresql+psycopg://postgres:pw@localhost:55432/qeos_test         python -m pytest tests/integration/test_screenshots_postgres.py -q
    docker stop qeos-pg

In PowerShell, the same container, then:

    $env:SECRET_KEY = "x"
    $env:QEOS_TEST_POSTGRES_URL = "postgresql+psycopg://postgres:pw@localhost:55432/qeos_test"
    python -m pytest tests/integration/test_screenshots_postgres.py -q
    docker stop qeos-pg
"""
import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

URL = os.environ.get("QEOS_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="QEOS_TEST_POSTGRES_URL is not set")

SHA = hashlib.sha256(b"png").hexdigest()
LOCK_NOT_AVAILABLE = "55P03"


def _refuse_unless_scratch(url: str) -> None:
    """The fixtures drop tables: never on a database that is not plainly a local scratch one."""
    parsed = make_url(url)
    name = (parsed.database or "").lower()
    if parsed.host not in ("localhost", "127.0.0.1") or not ("test" in name or "scratch" in name):
        pytest.exit(f"QEOS_TEST_POSTGRES_URL must point at localhost or 127.0.0.1 and a database whose name contains "
                    f"'test' or 'scratch' (got host={parsed.host!r}, database={parsed.database!r}); "
                    f"these tests drop the ingestion tables", returncode=2)


@pytest.fixture
def pg():
    from src.ingestion.db.base import Base
    from src.ingestion.models import ApiKey, Blob, CollectionSettings, Run, RunResult  # noqa: F401  registers tables

    _refuse_unless_scratch(URL)
    engine = create_engine(URL)
    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    finally:
        engine.dispose()
        cleanup = create_engine(URL, connect_args={"options": "-c lock_timeout=5000"})
        try:
            Base.metadata.drop_all(bind=cleanup)
        finally:
            cleanup.dispose()


@pytest.fixture
def seeded(pg):
    """A key, a project that keeps screenshots, and one blob old enough for the cleanup job."""
    from src.ingestion.models import ApiKey, Blob, CollectionSettings

    with pg() as db:
        key = ApiKey(project_id=7, organization_id=10, name="ci", key_prefix="qeos_x", key_hash="h", created_by=1)
        db.add_all([key, CollectionSettings(project_id=7, collect_manual=True, keep_screenshots=True, discarded_count=0),
                    Blob(project_id=7, sha256=SHA, media_type="image/png", bytes=3,
                         created_at=datetime.now(timezone.utc) - timedelta(days=30))])
        db.commit()
        return pg


def upload():
    from src.ingestion.schemas.collect import RunUpload

    now = datetime.now(timezone.utc)
    return RunUpload.model_validate({
        "run": {"ci_provider": "local", "started_at": (now - timedelta(seconds=5)).isoformat(),
                "finished_at": now.isoformat()},
        "results": [{"name": "t", "status": "failed", "screenshots": [
            {"sha256": SHA, "media_type": "image/png", "step_text": "Given a step"}]}],
    })


def test_a_link_insert_that_fails_on_the_foreign_key_keeps_the_run(seeded, monkeypatch):
    from src.ingestion.models import ApiKey, ResultScreenshot, Run, RunResult
    from src.ingestion.service import ingest_service
    from src.ingestion.utils.artifact_store import MemoryArtifactStore

    real = ingest_service._blob_ids
    # The lookup runs as usual; the id it returns belongs to no blob: the foreign key refuses the insert
    monkeypatch.setattr(ingest_service, "_blob_ids", lambda *a, **k: {sha: 999_999 for sha in real(*a, **k)})
    with seeded() as db:
        run, created = ingest_service.ingest(db, db.query(ApiKey).one(), upload(), None, MemoryArtifactStore())
        assert created and run.screenshots_dropped == 1
    with seeded() as db:
        assert db.query(Run).count() == 1 and db.query(RunResult).count() == 1
        assert db.query(ResultScreenshot).count() == 0


def test_the_upload_links_on_postgres(seeded):
    from src.ingestion.models import ApiKey, ResultScreenshot
    from src.ingestion.service import ingest_service
    from src.ingestion.utils.artifact_store import MemoryArtifactStore

    with seeded() as db:
        run, _ = ingest_service.ingest(db, db.query(ApiKey).one(), upload(), None, MemoryArtifactStore())
        assert run.screenshots_dropped == 0
    with seeded() as db:
        assert db.query(ResultScreenshot).count() == 1


def _delete_blob_soon(factory, lock_timeout="500ms"):
    """What the cleanup job's DELETE does, in its own session and transaction."""
    from src.ingestion.jobs import retention

    db = factory()
    try:
        db.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention.BLOB_GRACE_DAYS)
        from src.ingestion.models import Blob

        ids = [i for (i,) in db.query(Blob.id)]
        rows = retention._delete_blobs(db, ids, cutoff)
        db.commit()
        return rows
    finally:
        db.close()


def test_the_key_share_lock_holds_a_blob_the_upload_looked_up(seeded):
    """Two steps, one after the other (not a true race): while the upload's lookup holds FOR KEY SHARE, the cleanup
    DELETE is blocked (it hits the lock timeout); once the upload has linked and committed, `_delete_blobs` re-checks
    "unreferenced", finds the reference and deletes nothing."""
    from src.ingestion.models import ApiKey, Blob
    from src.ingestion.service import ingest_service
    from src.ingestion.utils.artifact_store import MemoryArtifactStore

    upload_session = seeded()
    try:
        ids = ingest_service._blob_ids(upload_session, 7, [upload().results[0].screenshots], MemoryArtifactStore())
        assert ids == {SHA: ids[SHA]}  # the lookup holds FOR KEY SHARE on the row until this transaction ends
        with pytest.raises(DBAPIError) as timeout:
            _delete_blob_soon(seeded)
        assert timeout.value.orig.sqlstate == LOCK_NOT_AVAILABLE

        # The upload finishes: ingest does its own lookup and links in one transaction
        upload_session.rollback()
        ingest_service.ingest(upload_session, upload_session.query(ApiKey).one(), upload(), None, MemoryArtifactStore())
    finally:
        upload_session.close()  # also on failure: an open transaction would block the schema drop in teardown
    assert _delete_blob_soon(seeded) == []
    with seeded() as db:
        assert db.query(Blob).count() == 1


def test_without_the_lock_the_same_delete_goes_through(seeded):
    """The control for the test above: after a plain SELECT, with no row lock, the same DELETE goes through, so that
    test fails if the lock is removed."""
    from src.ingestion.models import Blob

    upload_session = seeded()
    try:
        upload_session.query(Blob.id).all()  # a plain SELECT: no row lock
        assert len(_delete_blob_soon(seeded)) == 1
    finally:
        upload_session.close()
