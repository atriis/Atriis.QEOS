"""Latest result per test key on any branch, with the failed step (spec 2026-10-13 §3.3)."""
from datetime import datetime, timedelta, timezone

from src.ingestion.models import RunResult
from tests.conftest import report_key

URL = "/api/v1/projects/1/analytics/latest-results"
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_latest_on_any_branch_with_the_failed_step(client, auth, project_role, seed_run, db):
    project_role("viewer")
    seed_run(T0, results=(("search", "passed", 5),), branch="main")
    run = seed_run(T0 + timedelta(hours=1), results=(("search", "failed", 5),), branch="feature/x")
    row = db.query(RunResult).filter_by(run_id=run.id).one()
    row.message, row.failed_step_text, row.failed_step_line = "boom", "When I search Lisbon", 14
    db.commit()
    key = report_key("search")
    body = client.post(URL, json={"keys": [key]}, headers=auth()).json()
    got = body["results"][key]
    assert got["status"] == "failed" and got["branch"] == "feature/x" and got["run_id"] == run.id
    assert got["failed_step"] == {"text": "When I search Lisbon", "line": 14} and got["message"] == "boom"
    assert got["started_at"].startswith("2026-10-01T01:00:00") and got["started_at"].endswith("+00:00")


def test_keys_without_results_are_absent(client, auth, project_role):
    project_role("viewer")
    assert client.post(URL, json={"keys": ["a" * 64]}, headers=auth()).json() == {"results": {}}


def test_keys_are_case_insensitive(client, auth, project_role, seed_run):
    project_role("viewer")
    seed_run(T0, results=(("search", "passed", 5),))
    key = report_key("search")
    assert key.lower() in client.post(URL, json={"keys": [key.upper()]}, headers=auth()).json()["results"]


def test_limits_and_roles(client, auth, project_role):
    project_role("viewer")
    assert client.post(URL, json={"keys": []}, headers=auth()).status_code == 422
    assert client.post(URL, json={"keys": [f"{i:064x}" for i in range(501)]}, headers=auth()).status_code == 422
    assert client.post(URL, json={"keys": ["not-a-key"]}, headers=auth()).status_code == 422
    project_role(status_code=404)
    assert client.post(URL, json={"keys": ["a" * 64]}, headers=auth()).status_code == 404


def test_duplicate_keys_give_one_entry(client, auth, project_role, seed_run):
    project_role("viewer")
    seed_run(T0, results=(("search", "passed", 5),))
    key = report_key("search")
    resp = client.post(URL, json={"keys": [key, key, key.upper()]}, headers=auth())
    assert resp.status_code == 200 and list(resp.json()["results"]) == [key.lower()]


def test_another_projects_results_are_never_returned(client, auth, project_role, seed_run):
    project_role("viewer")
    seed_run(T0, results=(("search", "failed", 5),), project_id=2)
    assert client.post(URL, json={"keys": [report_key("search")]}, headers=auth()).json() == {"results": {}}


def test_two_rows_of_one_test_in_a_run_rank_by_id(client, auth, project_role, seed_run):
    project_role("viewer")
    seed_run(T0, results=(("search", "failed", 5), ("search", "passed", 5)))
    got = client.post(URL, json={"keys": [report_key("search")]}, headers=auth()).json()["results"]
    assert got[report_key("search")]["status"] == "passed"


def test_the_message_is_cut_to_the_excerpt(client, auth, project_role, seed_run, db):
    from src.ingestion.service.analytics_service import MESSAGE_EXCERPT

    project_role("viewer")
    run = seed_run(T0, results=(("search", "failed", 5),))
    row = db.query(RunResult).filter_by(run_id=run.id).one()
    row.message = "x" * 5000
    db.commit()
    key = report_key("search")
    got = client.post(URL, json={"keys": [key]}, headers=auth()).json()["results"][key]
    assert len(got["message"]) == MESSAGE_EXCERPT
