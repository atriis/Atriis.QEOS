import base64
import json
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.core.config import settings
from src.ingestion.jobs import retention
from src.ingestion.models import ApiKey, Run, RunResult

PASSWORD = "p@ss:w/rd"  # URL-special characters: the connection string carries it percent-encoded
INTERNAL = "http://ingestion-service:p%40ss%3Aw%2Frd@project-service:8000"
RETENTION_URL = "http://project-service:8000/internal/v1/projects/retention"
NOW = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_SERVICE_INTERNAL_URL", INTERNAL)
    monkeypatch.setattr(settings, "RETENTION_BATCH_SIZE", 2)


@pytest.fixture
def session_factory(db):
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)


@pytest.fixture
def answer(http):
    def _answer(projects=None, status_code=200, body=None, text=None, exc=None):
        route = http.get(RETENTION_URL, name="retention")
        if exc is not None:
            return route.mock(side_effect=exc)
        if text is not None:
            return route.mock(return_value=httpx.Response(status_code, text=text))
        payload = {"projects": projects or []} if body is None else body
        return route.mock(return_value=httpx.Response(status_code, json=payload))

    return _answer


@pytest.fixture
def add_run(db, make_key):
    keys = {}

    def _add(project_id, days_old):
        if project_id not in keys:
            keys[project_id] = make_key(project_id=project_id)[0]
        created = NOW - timedelta(days=days_old)
        run = Run(project_id=project_id, api_key_id=keys[project_id].id, request_hash="h", ci_provider="local",
                  started_at=created, finished_at=created, duration_ms=0, total=1, passed=1, failed=0,
                  skipped=0, errored=0, created_at=created)
        db.add(run)
        db.flush()
        db.add(RunResult(run_id=run.id, test_key="0" * 64, name="t", status="passed", duration_ms=1))
        db.commit()
        return run.id

    return _add


def run_job(session_factory, *args):
    return retention.main(list(args), now=lambda: NOW, session_factory=session_factory)


def remaining(db):
    db.expire_all()
    return sorted(run.id for run in db.query(Run))


def summary(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def live(project_id, days):
    return {"project_id": project_id, "result_retention_days": days, "deleted": False, "deleted_at": None,
            "legal_hold": False}


def gone(project_id, days_ago, days=30):
    deleted_at = (NOW - timedelta(days=days_ago)).isoformat()
    return {"project_id": project_id, "result_retention_days": days, "deleted": True, "deleted_at": deleted_at,
            "legal_hold": False}


def test_runs_older_than_the_retention_period_are_deleted(db, session_factory, answer, add_run, capsys):
    for days_old in (31, 40, 400):  # three old runs: two batches of RETENTION_BATCH_SIZE=2
        add_run(1, days_old)
    recent = add_run(1, 29)
    answer([live(1, 30)])

    assert run_job(session_factory) == 0

    assert remaining(db) == [recent]
    assert db.query(RunResult).count() == 1
    assert summary(capsys) == {"event": "retention", "projects": 1, "runs_deleted": 3, "blobs_deleted": 0,
                               "traces_expired": 0, "incoming_deleted": 0, "links_deleted": 0,
                               "projects_purged": 0, "purge_failures": 0, "projects_skipped": 0, "projects_held": 0,
                               "dry_run": False}


def test_without_test_management_a_deleted_project_is_left_alone(db, session_factory, answer, add_run, make_key,
                                                                capsys):
    # The purge needs every service (spec 2026-10-16): without TEST_MANAGEMENT_INTERNAL_URL nothing of it is touched
    kept = add_run(2, 0)
    key, _ = make_key(project_id=2)
    answer([gone(2, days_ago=8)])

    assert run_job(session_factory) == 0

    assert remaining(db) == [kept]
    db.refresh(key)
    assert key.revoked_at is None
    assert '"event": "purge_skipped"' in capsys.readouterr().out


def test_projects_missing_from_the_list_are_never_touched(db, session_factory, answer, add_run, capsys):
    kept = add_run(3, 1000)
    answer([])

    assert run_job(session_factory) == 0

    assert remaining(db) == [kept]
    assert summary(capsys)["projects_skipped"] == 1


@pytest.mark.parametrize("reply", [
    {"exc": httpx.ConnectError("connection refused")},
    {"status_code": 401, "body": {"detail": "Invalid internal credentials"}},
    {"status_code": 500, "body": {"detail": "boom"}},
    {"text": "<html>maintenance</html>"},
    {"body": [1, 2]},
    {"body": {"projects": "all"}},
    {"body": {"projects": [{"project_id": "1", "result_retention_days": 30, "deleted": False}]}},
    {"body": {"projects": [{"project_id": True, "result_retention_days": 30, "deleted": False}]}},
    {"body": {"projects": [{"project_id": 1, "result_retention_days": 0, "deleted": False}]}},
    {"body": {"projects": [{"project_id": 1, "result_retention_days": 30, "deleted": "no"}]}},
])
def test_without_a_trustworthy_answer_nothing_is_deleted(db, session_factory, answer, add_run, capsys, reply):
    old = add_run(1, 400)
    answer(**reply)

    assert run_job(session_factory) == 1

    assert remaining(db) == [old]
    assert json.loads(capsys.readouterr().err.strip().splitlines()[-1])["event"] == "retention_failed"


def test_dry_run_reports_but_changes_nothing(db, session_factory, answer, add_run, capsys):
    old, recent, of_deleted = add_run(1, 400), add_run(1, 1), add_run(2, 0)
    answer([live(1, 30), gone(2, days_ago=30)])

    assert run_job(session_factory, "--dry-run") == 0

    assert remaining(db) == sorted([old, recent, of_deleted])
    assert db.query(ApiKey).filter(ApiKey.revoked_at.isnot(None)).count() == 0
    reported = summary(capsys)
    # The deleted project would be purged as a whole (spec 2026-10-16), not counted in runs_deleted
    assert (reported["runs_deleted"], reported["projects_purged"], reported["dry_run"]) == (1, 1, True)


def test_the_request_carries_basic_credentials_and_no_userinfo(session_factory, answer):
    route = answer([])

    assert run_job(session_factory) == 0

    request = route.calls.last.request
    assert str(request.url) == RETENTION_URL
    expected = base64.b64encode(f"ingestion-service:{PASSWORD}".encode()).decode()
    assert request.headers["Authorization"] == f"Basic {expected}"


def test_the_password_never_appears_in_the_output(session_factory, answer, capsys):
    answer(status_code=401, body={"detail": "Invalid internal credentials"})
    assert run_job(session_factory) == 1
    answer([])
    assert run_job(session_factory) == 0

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert PASSWORD not in output and "p%40ss" not in output
    assert "http://ingestion-service:***@project-service:8000" in captured.err


@pytest.mark.parametrize("url", [
    "",
    "not a url",
    "http://project-service:8000",
    "http://ingestion-service@project-service:8000",
    "http://ingestion-service:@project-service:8000",
    "ftp://ingestion-service:pw@project-service:8000",
])
def test_an_unusable_connection_string_fails_the_pass(session_factory, monkeypatch, capsys, http, url):
    monkeypatch.setattr(settings, "PROJECT_SERVICE_INTERNAL_URL", url)

    assert run_job(session_factory) == 1

    assert "PROJECT_SERVICE_INTERNAL_URL" in capsys.readouterr().err
    assert not http.calls


def test_the_loop_survives_a_failed_pass_and_stops_when_asked(monkeypatch, session_factory):
    calls = []
    stop = threading.Event()

    def fake_run_once(**kwargs):
        calls.append(kwargs["dry_run"])
        if len(calls) == 3:
            stop.set()
        return len(calls) != 1  # the first pass fails

    monkeypatch.setattr(retention, "run_once", fake_run_once)
    monkeypatch.setattr(settings, "RETENTION_INTERVAL_HOURS", 0)

    assert retention.main(["--loop"], now=lambda: NOW, session_factory=session_factory, stop=stop) == 0
    assert calls == [False, False, False]


def test_a_recently_deleted_project_keeps_everything_for_the_grace_period(db, session_factory, answer, add_run,
                                                                          make_key):
    # Pending deletion can be undone as it was (spec 2026-10-16): not even the usual retention runs, keys stay
    old, recent = add_run(4, 40), add_run(4, 1)
    key, _ = make_key(project_id=4)
    answer([gone(4, days_ago=6, days=30)])

    assert run_job(session_factory) == 0

    assert remaining(db) == [old, recent]
    db.refresh(key)
    assert key.revoked_at is None  # uploads are refused with 410 instead, so a restore brings the key back


@pytest.mark.parametrize("deleted_at", [None, "yesterday", 5])
def test_a_deleted_project_without_a_usable_deletion_time_fails_the_pass(db, session_factory, answer, add_run,
                                                                       deleted_at):
    old = add_run(1, 400)
    answer([{"project_id": 1, "result_retention_days": 30, "deleted": True, "deleted_at": deleted_at,
             "legal_hold": False}])

    assert run_job(session_factory) == 1
    assert remaining(db) == [old]


def held(policy):
    return {**policy, "legal_hold": True}


def test_a_project_on_legal_hold_loses_nothing(db, session_factory, answer, add_run, capsys):
    old = add_run(1, 400)
    answer([held(live(1, 30))])
    assert run_job(session_factory) == 0
    assert remaining(db) == [old]
    assert summary(capsys)["projects_held"] == 1


def test_a_deleted_project_on_legal_hold_is_not_emptied(db, session_factory, answer, add_run, make_key):
    kept = add_run(1, 1)
    key, _ = make_key(project_id=1)
    answer([held(gone(1, days_ago=60))])
    assert run_job(session_factory) == 0
    assert remaining(db) == [kept]
    db.expire_all()
    assert db.get(ApiKey, key.id).revoked_at is None  # nothing of a held project changes


def test_a_project_without_a_legal_hold_answer_stops_the_pass(db, session_factory, answer, add_run):
    # An older project-service that does not report holds: deleting could destroy held data
    old = add_run(1, 400)
    policy = live(1, 30)
    del policy["legal_hold"]
    answer([policy])
    assert run_job(session_factory) == 1
    assert remaining(db) == [old]


def test_log_values_go_with_their_results(db, session_factory, answer, add_run):
    from src.ingestion.models import LogPattern, LogValue

    old, recent = add_run(1, 40), add_run(1, 5)
    pattern = LogPattern(project_id=1, name="trip_id", pattern="x")
    db.add(pattern)
    db.flush()
    for run_id in (old, recent):
        result = db.query(RunResult).filter_by(run_id=run_id).one()
        db.add(LogValue(result_id=result.id, pattern_id=pattern.id, position=0, value=str(run_id)))
    db.commit()
    answer([live(1, 30)])

    assert run_job(session_factory) == 0

    db.expire_all()
    assert [v.value for v in db.query(LogValue)] == [str(recent)]


# Step screenshots (ADR-036): the images go with their results, and never pile up unreferenced

@pytest.fixture
def store(monkeypatch):
    from src.ingestion.utils.artifact_store import MemoryArtifactStore

    memory = MemoryArtifactStore()
    monkeypatch.setattr(retention, "get_artifact_store", lambda: memory)
    return memory


@pytest.fixture
def add_blob(db, store):
    from src.ingestion.models import Blob
    from src.ingestion.utils.artifact_store import screenshot_key

    def _add(days_old, project_id=1, sha="a"):
        sha = (sha * 64)[:64]
        blob = Blob(project_id=project_id, sha256=sha, media_type="image/png", bytes=3,
                    created_at=NOW - timedelta(days=days_old))
        db.add(blob)
        db.commit()
        store.put(screenshot_key(project_id, sha), b"png", "image/png")
        return blob.id

    return _add


def blob_ids(db):
    from src.ingestion.models import Blob

    db.expire_all()
    return sorted(b.id for b in db.query(Blob))


def test_gc_deletes_unreferenced_blob_older_than_7_days(db, session_factory, answer, add_blob, store):
    add_blob(8)
    answer([live(1, 30)])
    assert run_job(session_factory) == 0
    assert blob_ids(db) == []
    assert store.objects == {}


def test_gc_keeps_unreferenced_blob_6_days_old(db, session_factory, answer, add_blob, store):
    keep = add_blob(6)
    answer([live(1, 30)])
    assert run_job(session_factory) == 0
    assert blob_ids(db) == [keep]
    assert len(store.objects) == 1


def test_gc_keeps_blob_still_referenced_by_other_result(db, session_factory, answer, add_run, add_blob, store):
    from src.ingestion.models import ResultScreenshot

    blob = add_blob(30)
    old, recent = add_run(1, 40), add_run(1, 1)
    for run_id in (old, recent):
        result = db.query(RunResult).filter_by(run_id=run_id).one()
        db.add(ResultScreenshot(result_id=result.id, position=0, blob_id=blob, step_text="When x"))
    db.commit()
    answer([live(1, 30)])
    assert run_job(session_factory) == 0
    assert blob_ids(db) == [blob]  # the recent result still shows it
    assert len(store.objects) == 1
    assert db.query(ResultScreenshot).count() == 1


def test_retention_deletes_screenshot_rows_with_results(db, session_factory, answer, add_run, add_blob):
    from src.ingestion.models import ResultScreenshot

    blob = add_blob(1)
    run_id = add_run(1, 40)
    result = db.query(RunResult).filter_by(run_id=run_id).one()
    db.add(ResultScreenshot(result_id=result.id, position=0, blob_id=blob, step_text="When x"))
    db.commit()
    answer([live(1, 30)])
    assert run_job(session_factory) == 0
    db.expire_all()
    assert db.query(ResultScreenshot).count() == 0
    assert blob_ids(db) == [blob]  # too young for the garbage pass


def test_gc_deletes_rows_and_skips_objects_without_a_store(db, session_factory, answer, add_blob, monkeypatch):
    add_blob(8)
    monkeypatch.setattr(retention, "get_artifact_store", lambda: None)
    answer([live(1, 30)])
    assert run_job(session_factory) == 0
    assert blob_ids(db) == []


def test_gc_deletes_only_what_the_delete_itself_finds_unreferenced(db, store, add_blob, add_run):
    """The check runs inside the DELETE: a blob referenced in the meantime is neither deleted nor loses its object."""
    from src.ingestion.models import ResultScreenshot

    kept, doomed = add_blob(30, sha="a"), add_blob(30, sha="b")
    result = db.query(RunResult).filter_by(run_id=add_run(1, 1)).one()
    db.add(ResultScreenshot(result_id=result.id, position=0, blob_id=kept, step_text="When x"))
    db.commit()
    assert retention.collect_unreferenced_blobs(db, store, NOW, projects=[1]) == 1
    assert blob_ids(db) == [kept]
    assert len(store.objects) == 1


def test_gc_survives_a_store_that_refuses_to_delete(db, store, add_blob, capsys):
    from src.ingestion.utils.artifact_store import ArtifactDeleteError

    add_blob(8)

    def refuse(keys):
        raise ArtifactDeleteError("1 of 1 objects not deleted")

    store.delete = refuse
    assert retention.collect_unreferenced_blobs(db, store, NOW, projects=[1]) == 1
    assert blob_ids(db) == []
    assert "gc_objects_not_deleted" in capsys.readouterr().err


def test_gc_works_in_batches(db, store, add_blob):
    for letter in "abcde":
        add_blob(9, sha=letter)
    assert retention.collect_unreferenced_blobs(db, store, NOW, batch=2, projects=[1]) == 5
    assert blob_ids(db) == [] and store.objects == {}


def test_dry_run_gc_deletes_nothing(db, session_factory, answer, add_blob, store):
    keep = add_blob(9)
    answer([live(1, 30)])
    assert run_job(session_factory, "--dry-run") == 0
    assert blob_ids(db) == [keep] and len(store.objects) == 1


def test_gc_leaves_blobs_of_a_project_on_legal_hold(db, session_factory, answer, add_blob):
    keep = add_blob(9)
    answer([{**live(1, 30), "legal_hold": True}])
    assert run_job(session_factory) == 0
    assert blob_ids(db) == [keep]


def test_gc_touches_only_listed_projects(db, session_factory, answer, add_blob):
    keep = add_blob(9, project_id=2)
    answer([live(1, 30)])
    assert run_job(session_factory) == 0
    assert blob_ids(db) == [keep]


def test_an_empty_answer_deletes_no_blob(db, session_factory, answer, add_blob, store):
    keep = add_blob(9)
    answer([])
    assert run_job(session_factory) == 0
    assert blob_ids(db) == [keep] and len(store.objects) == 1


def test_gc_skips_a_blob_the_database_refuses_to_delete_and_deletes_the_rest(db, store, add_blob, capsys):
    from sqlalchemy import text

    first, contended, last = add_blob(9, sha="a"), add_blob(9, sha="b"), add_blob(9, sha="c")
    # What the foreign key does to a delete that missed a reference committed meanwhile
    db.execute(text("CREATE TRIGGER refuse BEFORE DELETE ON blobs WHEN OLD.sha256 = '" + "b" * 64 + "' "
                    "BEGIN SELECT RAISE(ABORT, 'FOREIGN KEY constraint failed'); END"))
    db.commit()
    assert retention.collect_unreferenced_blobs(db, store, NOW, batch=5, projects=[1]) == 2
    assert blob_ids(db) == [contended]
    assert len(store.objects) == 1
    assert "gc_blobs_skipped" in capsys.readouterr().err and first < last


def test_a_store_failure_during_the_job_does_not_fail_the_pass(db, session_factory, answer, add_blob, store, capsys):
    from src.ingestion.utils.artifact_store import ArtifactDeleteError

    add_blob(9)

    def refuse(keys):
        raise ArtifactDeleteError("not deleted")

    store.delete = refuse
    answer([live(1, 30)])
    assert run_job(session_factory) == 0
    assert blob_ids(db) == []
    assert summary(capsys)["blobs_deleted"] == 1


def test_gc_pages_by_id_and_a_skipped_row_does_not_stop_later_batches(db, store, add_blob, capsys):
    from sqlalchemy import text

    for number in range(7):  # four batches of two
        add_blob(9, sha=format(number, "x"))
    contended = db.execute(text("SELECT id FROM blobs WHERE sha256 = :h"), {"h": "2" * 64}).scalar()
    db.execute(text("CREATE TRIGGER refuse BEFORE DELETE ON blobs WHEN OLD.sha256 = '" + "2" * 64 + "' "
                    "BEGIN SELECT RAISE(ABORT, 'FOREIGN KEY constraint failed'); END"))
    db.commit()
    assert retention.collect_unreferenced_blobs(db, store, NOW, batch=2, projects=[1]) == 6
    assert blob_ids(db) == [contended]
    assert len(store.objects) == 1


# Traces (ADR-037): kept trace_days, independently of the results; unreferenced trace blobs go after 7 days

@pytest.fixture
def add_trace(db, store):
    from src.ingestion.models import Blob, ResultArtifact
    from src.ingestion.utils.artifact_store import artifact_key

    def _add(run_id, days_old=1, project_id=1, sha="t"):
        sha = (sha * 64)[:64]
        blob = db.query(Blob).filter_by(project_id=project_id, sha256=sha).one_or_none()
        if blob is None:
            blob = Blob(project_id=project_id, sha256=sha, kind="trace", media_type="application/zip", bytes=4,
                        created_at=NOW - timedelta(days=days_old))
            db.add(blob)
            db.flush()
            store.put(artifact_key(project_id, sha), b"PK\x03\x04", "application/zip")
        result = db.query(RunResult).filter_by(run_id=run_id).one()
        db.add(ResultArtifact(result_id=result.id, position=0, blob_id=blob.id, kind="trace"))
        db.commit()
        return blob.id

    return _add


def trace_runs(db):
    from src.ingestion.models import ResultArtifact

    db.expire_all()
    return sorted(run_id for (run_id,) in db.query(RunResult.run_id).join(
        ResultArtifact, ResultArtifact.result_id == RunResult.id))


def set_trace_days(db, project_id, days):
    from src.ingestion.models import CollectionSettings

    db.add(CollectionSettings(project_id=project_id, keep_traces=True, trace_days=days))
    db.commit()


def test_traces_go_after_trace_days_and_their_results_stay(db, session_factory, answer, add_run, add_trace, capsys):
    """Review Focus 4: trace_days 3, results kept 90 days. The traces of runs past 3 days go, every run stays."""
    set_trace_days(db, 1, 3)
    old, edge, recent = add_run(1, 10), add_run(1, 4), add_run(1, 2)
    for run_id in (old, edge, recent):
        add_trace(run_id, sha=str(run_id))
    answer([live(1, 90)])
    assert run_job(session_factory) == 0
    assert remaining(db) == sorted([old, edge, recent])
    assert db.query(RunResult).count() == 3
    assert trace_runs(db) == [recent]
    assert summary(capsys)["traces_expired"] == 2


def test_trace_days_default_to_14_without_settings(db, session_factory, answer, add_run, add_trace):
    old, recent = add_run(1, 15), add_run(1, 13)
    add_trace(old, sha="a")
    add_trace(recent, sha="b")
    answer([live(1, 90)])
    assert run_job(session_factory) == 0
    assert trace_runs(db) == [recent]


def test_trace_days_are_per_project(db, session_factory, answer, add_run, add_trace):
    set_trace_days(db, 1, 3)
    set_trace_days(db, 2, 30)
    one, two = add_run(1, 10), add_run(2, 10)
    add_trace(one, sha="a")
    add_trace(two, project_id=2, sha="b")
    answer([live(1, 90), live(2, 90)])
    assert run_job(session_factory) == 0
    assert trace_runs(db) == [two]


def test_traces_of_a_project_on_legal_hold_or_unlisted_stay(db, session_factory, answer, add_run, add_trace):
    set_trace_days(db, 1, 1)
    set_trace_days(db, 2, 1)
    held_run, unlisted = add_run(1, 10), add_run(2, 10)
    add_trace(held_run, sha="a")
    add_trace(unlisted, project_id=2, sha="b")
    answer([held(live(1, 90))])
    assert run_job(session_factory) == 0
    assert trace_runs(db) == sorted([held_run, unlisted])


def test_dry_run_counts_expired_traces_and_deletes_none(db, session_factory, answer, add_run, add_trace, capsys):
    set_trace_days(db, 1, 3)
    run_id = add_run(1, 10)
    add_trace(run_id)
    answer([live(1, 90)])
    assert run_job(session_factory, "--dry-run") == 0
    assert trace_runs(db) == [run_id]
    assert summary(capsys)["traces_expired"] == 1


def test_trace_rows_go_with_their_results(db, session_factory, answer, add_run, add_trace):
    from src.ingestion.models import ResultArtifact

    run_id = add_run(1, 40)
    add_trace(run_id)
    answer([live(1, 30)])
    assert run_job(session_factory) == 0
    db.expire_all()
    assert remaining(db) == [] and db.query(ResultArtifact).count() == 0


def test_gc_deletes_an_unreferenced_trace_after_7_days_and_its_object(db, session_factory, answer, add_run,
                                                                     add_trace, store):
    from src.ingestion.utils.artifact_store import artifact_key

    set_trace_days(db, 1, 3)
    old = add_trace(add_run(1, 10), days_old=10, sha="a")
    young = add_trace(add_run(1, 5), days_old=5, sha="b")  # expires now, but uploaded 5 days ago
    kept = add_trace(add_run(1, 1), days_old=30, sha="c")  # old blob, still referenced by a recent result
    answer([live(1, 90)])
    assert run_job(session_factory) == 0
    assert blob_ids(db) == sorted([young, kept])
    assert set(store.objects) == {artifact_key(1, "b" * 64), artifact_key(1, "c" * 64)}
    assert old not in blob_ids(db)


def test_gc_deletes_both_kinds_with_their_own_keys(db, store, add_blob, add_run, add_trace):
    from src.ingestion.models import ResultArtifact

    add_blob(9, sha="a")
    add_trace(add_run(1, 1), days_old=9, sha="b")
    db.query(ResultArtifact).delete()
    db.commit()
    assert retention.collect_unreferenced_blobs(db, store, NOW, projects=[1]) == 2
    assert blob_ids(db) == [] and store.objects == {}


def test_gc_deletes_incoming_objects_older_than_a_day_only(db, session_factory, answer, store):
    old, fresh, other = "artifacts/1/incoming/old", "artifacts/1/incoming/fresh", "artifacts/2/incoming/old"
    for key in (old, fresh, other):
        store.put(key, b"PK", "application/zip")
    store.modified[old] = NOW - timedelta(days=1, minutes=1)
    store.modified[fresh] = NOW - timedelta(hours=23)  # an upload may still be streaming into it
    store.modified[other] = NOW - timedelta(days=5)
    answer([live(1, 90)])  # project 2 is not listed: never touched
    assert run_job(session_factory) == 0
    assert set(store.objects) == {fresh, other}


def test_gc_of_incoming_objects_survives_a_store_failure(db, session_factory, answer, store, capsys):
    def broken(prefix, older_than):
        raise RuntimeError("storage is down")

    store.list_older = broken
    answer([live(1, 90)])
    assert run_job(session_factory) == 0
    assert "gc_incoming_not_deleted" in capsys.readouterr().err


# One-time links (ADR-037): valid 60 s; the pass deletes the expired ones, whatever the policies say

def test_expired_artifact_links_are_deleted(db, session_factory, answer, add_run, add_trace, capsys):
    from src.ingestion.models import ArtifactLink, ResultArtifact

    add_trace(add_run(1, 1))
    artifact_id = db.query(ResultArtifact.id).scalar()
    for name, expires in (("old", NOW - timedelta(days=2)), ("just", NOW - timedelta(seconds=1)),
                          ("live", NOW + timedelta(seconds=30))):
        db.add(ArtifactLink(token_sha256=(name * 64)[:64], artifact_id=artifact_id, user_id=1, client_ip="1.2.3.4",
                            expires_at=expires))
    db.commit()
    answer([])  # an empty answer touches no project, and still clears the expired links
    assert run_job(session_factory, "--dry-run") == 0
    assert summary(capsys)["links_deleted"] == 2
    assert db.query(ArtifactLink).count() == 3
    assert run_job(session_factory) == 0
    assert summary(capsys)["links_deleted"] == 2
    db.expire_all()
    assert [link.token_sha256[:4] for link in db.query(ArtifactLink)] == ["live"]
