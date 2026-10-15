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
    assert summary(capsys) == {"event": "retention", "projects": 1, "runs_deleted": 3, "keys_revoked": 0,
                               "projects_skipped": 0, "projects_held": 0, "dry_run": False}


def test_a_deleted_projects_runs_are_deleted_and_its_keys_revoked(db, session_factory, answer, add_run, make_key):
    add_run(2, 0)
    live_key, _ = make_key(project_id=2)
    old_revoked, _ = make_key(project_id=2, revoked=True)
    revoked_before = old_revoked.revoked_at
    answer([gone(2, days_ago=8)])

    assert run_job(session_factory) == 0

    assert remaining(db) == []
    db.refresh(live_key)
    db.refresh(old_revoked)
    assert live_key.revoked_at is not None
    assert old_revoked.revoked_at == revoked_before


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
    assert (reported["runs_deleted"], reported["keys_revoked"], reported["dry_run"]) == (2, 1, True)


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


def test_a_recently_deleted_project_keeps_its_runs_for_the_grace_period(db, session_factory, answer, add_run,
                                                                       make_key):
    # A soft delete can still be undone: only the usual retention applies until the grace period ends
    old, recent = add_run(4, 40), add_run(4, 1)
    key, _ = make_key(project_id=4)
    answer([gone(4, days_ago=6, days=30)])

    assert run_job(session_factory) == 0

    assert remaining(db) == [recent]
    db.refresh(key)
    assert key.revoked_at is not None  # but uploads stop at once


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
    # Keys still stop working: revoking a key deletes no data
    db.expire_all()
    assert db.get(ApiKey, key.id).revoked_at is not None


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
