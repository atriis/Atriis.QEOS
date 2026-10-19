"""The purge (spec 2026-10-16 §5): after the 7 days, test-management, then ingestion, then the project row."""
from datetime import timedelta

import httpx
import pytest

from src.ingestion.core.config import settings
from src.ingestion.models import ApiKey, CollectionSettings, LogPattern, MaskingPattern, Run
from tests.integration.test_retention_job import (  # noqa: F401  (fixtures, and the autouse configured)
    add_run, answer, configured, gone, live, run_job, session_factory,
)

TM_INTERNAL = "http://ingestion-service:p%40ss%3Aw%2Frd@test-management-service:8000"
TM_DELETE = "http://test-management-service:8000/internal/v1/projects/{pid}"
PS_STEP = "http://project-service:8000/internal/v1/projects/{pid}/purge-state"
PS_DELETE = "http://project-service:8000/internal/v1/projects/{pid}"


@pytest.fixture(autouse=True)
def tm_configured(monkeypatch):
    monkeypatch.setattr(settings, "TEST_MANAGEMENT_INTERNAL_URL", TM_INTERNAL)


@pytest.fixture
def services(http):
    def _routes(pid, tm_status=204, ps_delete_status=204):
        return {
            "tm": http.delete(TM_DELETE.format(pid=pid), name=f"tm-{pid}").mock(return_value=httpx.Response(tm_status)),
            "step": http.post(PS_STEP.format(pid=pid), name=f"step-{pid}").mock(return_value=httpx.Response(204)),
            "row": http.delete(PS_DELETE.format(pid=pid), name=f"row-{pid}").mock(
                return_value=httpx.Response(ps_delete_status)),
        }
    return _routes


def extras(db, project_id):
    db.add_all([CollectionSettings(project_id=project_id),
                LogPattern(project_id=project_id, name="trip_id", pattern="x"),
                MaskingPattern(project_id=project_id, name="secret", pattern="x")])
    db.commit()


def test_a_project_past_the_grace_is_purged_everywhere_in_order(db, session_factory, answer, add_run, services):
    keep = add_run(2, 1)
    add_run(1, 1)
    extras(db, 1)
    answer([gone(1, days_ago=8), live(2, 90)])
    routes = services(1)
    assert run_job(session_factory) == 0
    assert routes["tm"].call_count == 1 and routes["row"].call_count == 1
    steps = [call.request.read() for call in routes["step"].calls]
    assert steps == [b'{"step":"started"}', b'{"step":"test_management"}', b'{"step":"ingestion"}']
    db.expire_all()
    assert [r.id for r in db.query(Run)] == [keep]
    for model in (ApiKey, CollectionSettings, LogPattern, MaskingPattern):
        assert db.query(model).filter(model.project_id == 1).count() == 0
    assert db.query(ApiKey).filter(ApiKey.project_id == 2).count() == 1


def test_within_the_grace_nothing_is_deleted_and_keys_stay(db, session_factory, answer, add_run, services):
    add_run(1, 40)
    answer([gone(1, days_ago=6, days=30)])
    routes = services(1)
    assert run_job(session_factory) == 0
    assert routes["tm"].call_count == 0
    db.expire_all()
    assert db.query(Run).count() == 1  # pending: not even the usual retention, it can be restored as it was
    assert db.query(ApiKey).filter(ApiKey.revoked_at.isnot(None)).count() == 0


def test_a_failed_test_management_step_leaves_it_for_the_next_pass(db, session_factory, answer, add_run, services):
    add_run(1, 1)
    answer([gone(1, days_ago=8)])
    routes = services(1, tm_status=503)
    assert run_job(session_factory) == 1  # the pass reports the failure
    assert [call.request.read() for call in routes["step"].calls] == [b'{"step":"started"}']
    assert routes["row"].call_count == 0
    db.expire_all()
    assert db.query(Run).count() == 1


def test_a_recorded_step_is_not_redone(db, session_factory, answer, add_run, services):
    add_run(1, 1)
    row = gone(1, days_ago=8)
    row["purge_state"] = {"started": "2026-10-09T03:00:00+00:00", "test_management": "2026-10-09T03:00:00+00:00"}
    answer([row])
    routes = services(1)
    assert run_job(session_factory) == 0
    assert routes["tm"].call_count == 0
    assert [call.request.read() for call in routes["step"].calls] == [b'{"step":"ingestion"}']
    assert routes["row"].call_count == 1


def test_a_restored_project_is_never_purged(db, session_factory, answer, add_run, services):
    add_run(1, 1)
    answer([live(1, 90)])
    routes = services(1)
    assert run_job(session_factory) == 0
    assert routes["tm"].call_count == 0 and routes["row"].call_count == 0
    db.expire_all()
    assert db.query(Run).count() == 1


def test_a_project_restored_after_the_feed_was_read_is_left_alone(db, session_factory, answer, add_run, http):
    add_run(1, 1)
    answer([gone(1, days_ago=8)])
    tm = http.delete(TM_DELETE.format(pid=1)).mock(return_value=httpx.Response(204))
    http.post(PS_STEP.format(pid=1)).mock(
        return_value=httpx.Response(409, json={"detail": "Project is not pending deletion"}))
    assert run_job(session_factory) == 0  # restored meanwhile: not a failure
    assert tm.call_count == 0
    db.expire_all()
    assert db.query(Run).count() == 1


def test_a_pending_project_on_legal_hold_is_not_purged(db, session_factory, answer, add_run, services):
    add_run(1, 1)
    row = gone(1, days_ago=8)
    row["legal_hold"] = True
    answer([row])
    routes = services(1)
    assert run_job(session_factory) == 0
    assert routes["tm"].call_count == 0


def test_a_database_error_in_one_purge_does_not_stop_the_others(db, session_factory, answer, add_run, services,
                                                                 monkeypatch):
    from sqlalchemy.exc import OperationalError

    from src.ingestion.jobs import purge

    def broken(session, project_id, **kwargs):
        raise OperationalError("DELETE FROM test_runs", {}, Exception("deadlock detected"))

    monkeypatch.setattr(purge, "purge_ingestion", broken)
    add_run(1, 1)
    keep, old = add_run(2, 1), add_run(2, 400)
    answer([gone(1, days_ago=8), live(2, 30)])
    services(1)
    assert run_job(session_factory) == 1  # reported
    db.expire_all()
    assert sorted(r.id for r in db.query(Run).filter(Run.project_id == 2)) == [keep]  # the live project's retention ran


def test_purge_deletes_project_objects_and_rows(db, session_factory, answer, add_run, services, monkeypatch):
    from src.ingestion.jobs import purge
    from src.ingestion.models import Blob, ResultScreenshot, RunResult
    from src.ingestion.utils.artifact_store import MemoryArtifactStore, screenshot_key

    store = MemoryArtifactStore()
    monkeypatch.setattr(purge, "get_artifact_store", lambda: store)
    run_id = add_run(1, 1)
    add_run(2, 1)
    for project, sha in ((1, "a" * 64), (1, "b" * 64), (2, "c" * 64), (10, "d" * 64)):
        db.add(Blob(project_id=project, sha256=sha, media_type="image/png", bytes=1))
        store.put(screenshot_key(project, sha), b"png", "image/png")
    db.flush()
    first = db.query(Blob).filter_by(project_id=1, sha256="a" * 64).one()
    result = db.query(RunResult).filter_by(run_id=run_id).one()
    db.add(ResultScreenshot(result_id=result.id, position=0, blob_id=first.id, step_text="When x"))
    db.commit()
    answer([gone(1, days_ago=8)])
    services(1)
    assert run_job(session_factory) == 0
    db.expire_all()
    # Project 10's prefix starts with "1" too: the trailing slash keeps it
    assert set(store.objects) == {screenshot_key(2, "c" * 64), screenshot_key(10, "d" * 64)}
    assert [b.project_id for b in db.query(Blob).order_by(Blob.project_id)] == [2, 10]
    assert db.query(ResultScreenshot).count() == 0


def test_purge_without_a_store_deletes_only_the_rows(db, session_factory, answer, services, monkeypatch):
    from src.ingestion.jobs import purge
    from src.ingestion.models import Blob

    monkeypatch.setattr(purge, "get_artifact_store", lambda: None)
    db.add(Blob(project_id=1, sha256="a" * 64, media_type="image/png", bytes=1))
    db.commit()
    answer([gone(1, days_ago=8)])
    services(1)
    assert run_job(session_factory) == 0
    db.expire_all()
    assert db.query(Blob).count() == 0
