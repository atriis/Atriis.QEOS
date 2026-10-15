"""The log-value re-scan (ADR-032): past logs within 90 days, idempotent, one scan per project at a time."""
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.api import main
from src.ingestion.core.config import settings
from src.ingestion.jobs import log_scan
from src.ingestion.models import LogPattern, LogValue, RunResult
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session_factory(db):
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)


@pytest.fixture
def logged(db, seed_run):
    """logged(days_ago, log, project_id=1) -> result id: one run (stored `days_ago` before NOW) with one result."""
    def _add(days_ago, log, project_id=1):
        run = seed_run(NOW - timedelta(days=days_ago), results=(("t", "passed", 5),), project_id=project_id)
        row = db.query(RunResult).filter_by(run_id=run.id).one()
        row.log = log
        db.commit()
        return row.id
    return _add


def add_pattern(db, name, regex, project_id=1):
    row = LogPattern(project_id=project_id, name=name, pattern=regex)
    db.add(row)
    db.commit()
    return row


def values(db):
    db.expire_all()
    return sorted((v.result_id, v.pattern_id, v.position, v.value) for v in db.query(LogValue))


def scan(session_factory, project_id=1):
    return log_scan.run_scan(session_factory, project_id, now=lambda: NOW, batch_size=2)


def test_a_queued_scan_fills_values_for_the_last_90_days_only(db, session_factory, logged):
    recent = [logged(days, f'tripId="{days}"') for days in (1, 10, 89)]
    logged(91, 'tripId="91"')
    trip = add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    assert log_scan.scan_state(db, 1)["state"] == "running"
    assert scan(session_factory) is True
    assert values(db) == sorted((rid, trip.id, 0, str(days)) for rid, days in zip(recent, (1, 10, 89)))
    db.expire_all()
    assert log_scan.scan_state(db, 1) == {"state": "idle", "since": None}


def test_a_second_scan_changes_nothing(db, session_factory, logged):
    logged(1, 'tripId="1" tripId="2"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    scan(session_factory)
    first = values(db)
    log_scan.request_scan(db, 1)
    assert scan(session_factory) is True
    assert values(db) == first and len(first) == 2


def test_nothing_queued_means_nothing_to_do(db, session_factory, logged):
    logged(1, 'tripId="1"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    assert scan(session_factory) is True
    assert values(db) == []


def test_another_projects_logs_are_never_scanned(db, session_factory, logged):
    logged(1, 'tripId="1"', project_id=2)
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    scan(session_factory)
    assert values(db) == []


def test_one_scan_per_project_at_a_time(db, session_factory, logged):
    logged(1, 'tripId="1"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    with log_scan._project_lock(session_factory.kw["bind"], 1) as held:
        assert held is True
        assert scan(session_factory) is False   # the scan holding the project sees the request
        assert values(db) == []
        with log_scan._project_lock(session_factory.kw["bind"], 2) as other:
            assert other is True                # another project is not blocked
    db.expire_all()
    assert log_scan.scan_state(db, 1)["state"] == "running"  # still queued
    assert scan(session_factory) is True
    assert len(values(db)) == 1


def test_a_pattern_added_during_a_pass_gets_its_values(db, session_factory, logged, monkeypatch):
    logged(1, 'tripId="1" routeKey="wasToBos"')
    logged(2, 'tripId="2"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    real, passes = log_scan.scan_pass, []

    def pass_then_add(db_, project_id, since, batch_size):
        scanned = real(db_, project_id, since, batch_size)
        passes.append(scanned)
        if len(passes) == 1:  # added after this pass had walked every result
            with session_factory() as other:
                add_pattern(other, "route_key", r'routeKey="([^"]+)"')
                log_scan.request_scan(other, 1)
        return scanned

    monkeypatch.setattr(log_scan, "scan_pass", pass_then_add)
    assert scan(session_factory) is True
    assert passes == [2, 2]
    assert "wasToBos" in [value for *_, value in values(db)]
    db.expire_all()
    assert log_scan.scan_state(db, 1)["state"] == "idle"


def test_a_failed_pass_stays_queued_and_the_next_run_finishes_it(db, session_factory, logged, monkeypatch):
    logged(1, 'tripId="1"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    real = log_scan.scan_pass

    def broken(*args):
        raise RuntimeError("database went away")

    monkeypatch.setattr(log_scan, "scan_pass", broken)
    assert scan(session_factory) is False
    db.expire_all()
    assert log_scan.scan_state(db, 1)["state"] == "running"
    monkeypatch.setattr(log_scan, "scan_pass", real)
    assert scan(session_factory) is True
    assert len(values(db)) == 1


def test_a_result_valued_at_upload_is_not_valued_twice_by_the_scan(client, make_key, db, session_factory):
    trip = add_pattern(db, "trip_id", r'tripId="(\d+)"')
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "t", "status": "passed", "log": 'tripId="1" tripId="2"'}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    at_upload = values(db)
    assert [(p, pos, v) for _, p, pos, v in at_upload] == [(trip.id, 0, "1"), (trip.id, 1, "2")]
    log_scan.request_scan(db, 1)
    assert log_scan.run_scan(session_factory, 1) is True  # the real clock: the upload is seconds old
    assert values(db) == at_upload


def test_a_deleted_pattern_leaves_no_values_behind(db, session_factory, logged):
    logged(1, 'tripId="1"')
    trip = add_pattern(db, "trip_id", r'tripId="(\d+)"')
    db.delete(trip)
    db.commit()
    log_scan.request_scan(db, 1)
    assert scan(session_factory) is True
    assert values(db) == []


def test_resume_all_runs_every_queued_project(db, session_factory, logged):
    logged(1, 'tripId="1"', project_id=1)
    logged(1, 'tripId="2"', project_id=2)
    add_pattern(db, "trip_id", r'tripId="(\d+)"', project_id=1)
    add_pattern(db, "trip_id", r'tripId="(\d+)"', project_id=2)
    log_scan.request_scan(db, 1)
    log_scan.request_scan(db, 2)
    assert log_scan.resume_all(session_factory) == 2
    assert len(values(db)) == 2


def test_the_service_resumes_queued_scans_when_it_starts(monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(log_scan, "resume_all", lambda session_factory: started.set())
    monkeypatch.setattr(settings, "LOG_SCAN_RESUME_ON_STARTUP", True)
    main._resume_log_scans()
    assert started.wait(5)


def test_resuming_can_be_switched_off(monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(log_scan, "resume_all", lambda session_factory: started.set())
    monkeypatch.setattr(settings, "LOG_SCAN_RESUME_ON_STARTUP", False)
    main._resume_log_scans()
    assert not started.wait(0.2)
