"""POST /analytics/run-strip: each test's own last N results, oldest to newest (Cases 'Last runs')."""
from datetime import datetime, timedelta, timezone

import pytest

from qeos_shared.keys import test_key

URL = "/api/v1/projects/7/analytics/run-strip"
A, B, C = (test_key("", "", n) for n in "ABC")


def upload(client, key, *, started, results, branch="main"):
    run = {"ci_provider": "local", "branch": branch, "started_at": started.isoformat(),
           "finished_at": (started + timedelta(minutes=1)).isoformat()}
    r = client.post("/api/v1/collect/runs", json={"run": run, "results": results},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 201, r.text


@pytest.fixture
def runs(client, make_key, project_role):
    project_role("viewer", project_id=7)
    _, key = make_key(project_id=7)
    now = datetime.now(timezone.utc)
    upload(client, key, started=now - timedelta(hours=4), results=[{"name": "A", "status": "passed"}])
    upload(client, key, started=now - timedelta(hours=3), results=[
        {"name": "A", "status": "failed"}, {"name": "A", "status": "passed"}, {"name": "B", "status": "errored"}])
    upload(client, key, started=now - timedelta(hours=2), branch="dev", results=[{"name": "A", "status": "skipped"}])
    upload(client, key, started=now - timedelta(hours=1), results=[{"name": "B", "status": "passed"}])
    return client


def strip(client, auth, **body):
    r = client.post(URL, json={"test_keys": [A, B, C], **body}, headers=auth())
    assert r.status_code == 200, r.text
    return r.json()


def statuses(entries):
    return [e["status"] for e in entries]


def test_each_test_gets_only_the_runs_it_was_in_oldest_to_newest(runs, auth):
    tests = strip(runs, auth)["tests"]
    assert statuses(tests[A]) == ["passed", "rerun", "skipped"]
    assert statuses(tests[B]) == ["failed", "passed"]   # errored counts as failed
    assert tests[C] == []
    for entries in tests.values():
        assert [e["started_at"] for e in entries] == sorted(e["started_at"] for e in entries)
    assert {"run_id", "started_at", "branch", "status", "values"} == set(tests[A][0])
    assert all(entry["values"] == [] for entries in tests.values() for entry in entries)
    assert tests[A][2]["branch"] == "dev"


def test_a_test_missing_from_newer_runs_still_shows_its_own_last_results(client, make_key, project_role, auth):
    project_role("viewer", project_id=7)
    _, key = make_key(project_id=7)
    now = datetime.now(timezone.utc)
    upload(client, key, started=now - timedelta(hours=30), results=[{"name": "A", "status": "failed"}])
    for h in range(12, 0, -1):   # twelve newer runs of another suite
        upload(client, key, started=now - timedelta(hours=h), results=[{"name": "B", "status": "passed"}])
    tests = strip(client, auth)["tests"]
    assert statuses(tests[A]) == ["failed"]
    assert len(tests[B]) == 10


def test_a_retried_test_is_a_rerun_whatever_the_outcome(runs, auth):
    assert strip(runs, auth)["tests"][A][1]["status"] == "rerun"


def test_limit_keeps_each_tests_newest_results(runs, auth):
    tests = strip(runs, auth, limit=2)["tests"]
    assert statuses(tests[A]) == ["rerun", "skipped"]
    assert statuses(tests[B]) == ["failed", "passed"]


def test_branch_only_counts_that_branchs_runs(runs, auth):
    tests = strip(runs, auth, branch="main")["tests"]
    assert statuses(tests[A]) == ["passed", "rerun"]


def test_keys_are_case_insensitive(runs, auth):
    r = runs.post(URL, json={"test_keys": [A.upper()]}, headers=auth())
    assert statuses(r.json()["tests"][A]) == ["passed", "rerun", "skipped"]


def test_other_projects_runs_are_invisible(runs, auth, make_key, project_role):
    project_role("viewer", project_id=8)
    _, other = make_key(project_id=8)
    upload(runs, other, started=datetime.now(timezone.utc), results=[{"name": "A", "status": "failed"}])
    assert statuses(strip(runs, auth)["tests"][A]) == ["passed", "rerun", "skipped"]


@pytest.mark.parametrize("body", [{"test_keys": []}, {"test_keys": ["x"]}, {"test_keys": [A] * 201},
                                  {"test_keys": [A], "limit": 21}, {"test_keys": [A], "branch": "a\x00"}])
def test_bad_bodies_are_422(runs, auth, body):
    assert runs.post(URL, json=body, headers=auth()).status_code == 422


def test_runs_with_identical_started_at_are_ordered_by_id(client, make_key, project_role, auth):
    project_role("viewer", project_id=7)
    _, key = make_key(project_id=7)
    same = datetime.now(timezone.utc) - timedelta(hours=1)
    upload(client, key, started=same, results=[{"name": "A", "status": "passed"}])
    upload(client, key, started=same, results=[{"name": "A", "status": "failed"}])
    entries = strip(client, auth)["tests"][A]
    assert [e["run_id"] for e in entries] == sorted(e["run_id"] for e in entries)
    assert statuses(entries) == ["passed", "failed"]


def test_duplicate_and_mixed_case_keys_map_to_one_lowercased_entry(runs, auth):
    r = runs.post(URL, json={"test_keys": [A, A.upper(), A.title()]}, headers=auth())
    assert r.status_code == 200, r.text
    assert list(r.json()["tests"]) == [A]


def test_unknown_body_fields_are_422(runs, auth):
    assert runs.post(URL, json={"test_keys": [A], "extra": 1}, headers=auth()).status_code == 422


def test_each_bar_carries_the_values_of_its_run(client, make_key, project_role, auth, db):
    from src.ingestion.models import LogPattern

    project_role("viewer", project_id=7)
    db.add_all([LogPattern(project_id=7, name="trip_id", pattern=r'tripId="(\d+)"'),
                LogPattern(project_id=7, name="route_key", pattern=r'routeKey="([^"]+)"')])
    db.commit()
    _, key = make_key(project_id=7)
    now = datetime.now(timezone.utc)
    upload(client, key, started=now - timedelta(hours=3), results=[
        {"name": "A", "status": "passed", "log": 'tripId="3960562" routeKey="wasToBos" tripId="3960563"'},
        {"name": "B", "status": "skipped", "log": 'tripId="9"'}])
    upload(client, key, started=now - timedelta(hours=2), results=[{"name": "A", "status": "failed", "log": "no ids"}])
    upload(client, key, started=now - timedelta(hours=1), results=[   # a re-run: both attempts' values, once each
        {"name": "A", "status": "failed", "log": 'tripId="1"'},
        {"name": "A", "status": "passed", "log": 'tripId="1" tripId="2"'}])

    tests = strip(client, auth)["tests"]
    assert [e["values"] for e in tests[A]] == [
        [{"name": "route_key", "values": ["wasToBos"]}, {"name": "trip_id", "values": ["3960562", "3960563"]}],
        [],
        [{"name": "trip_id", "values": ["1", "2"]}],
    ]
    assert tests[B][0]["values"] == [{"name": "trip_id", "values": ["9"]}]  # whatever the status
    assert tests[C] == []
