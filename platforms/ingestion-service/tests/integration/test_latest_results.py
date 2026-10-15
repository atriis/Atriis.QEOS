"""Latest result per test key on any branch, with the failed step (spec 2026-10-13 §3.3)."""
from datetime import datetime, timedelta, timezone

from src.ingestion.analytics.failed_steps import step_key
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
    assert got["failed_step"] == {"text": "When I search Lisbon", "line": 14,
                                  "key": step_key(None, "When I search Lisbon")[0]}
    assert got["message"] == "boom"
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


def test_run_id_gives_each_test_its_result_in_that_run(client, auth, project_role, seed_run, db):
    project_role("viewer")
    old = seed_run(T0, results=(("search", "failed", 5), ("login", "passed", 5)))
    seed_run(T0 + timedelta(hours=1), results=(("search", "passed", 5),))
    row = db.query(RunResult).filter_by(run_id=old.id, name="search").one()
    row.message, row.failed_step_text, row.failed_step_line = "boom", "When I search Lisbon", 14
    db.commit()
    search, login = report_key("search"), report_key("login")
    got = client.post(URL, json={"keys": [search, login], "run_id": old.id}, headers=auth()).json()["results"]
    assert got[search]["status"] == "failed" and got[search]["run_id"] == old.id
    assert got[search]["failed_step"] == {"text": "When I search Lisbon", "line": 14,
                                          "key": step_key(None, "When I search Lisbon")[0]}
    assert got[login]["status"] == "passed" and "failed_step" not in got[login]


def test_run_id_leaves_out_tests_not_in_that_run(client, auth, project_role, seed_run):
    project_role("viewer")
    run = seed_run(T0, results=(("login", "passed", 5),))
    seed_run(T0 + timedelta(hours=1), results=(("search", "failed", 5),))
    got = client.post(URL, json={"keys": [report_key("search")], "run_id": run.id}, headers=auth()).json()
    assert got == {"results": {}}


def test_run_id_takes_the_last_row_of_a_re_run(client, auth, project_role, seed_run):
    project_role("viewer")
    run = seed_run(T0, results=(("search", "failed", 5), ("search", "passed", 5)))
    seed_run(T0 + timedelta(hours=1), results=(("search", "failed", 5),))
    got = client.post(URL, json={"keys": [report_key("search")], "run_id": run.id}, headers=auth()).json()["results"]
    assert got[report_key("search")]["status"] == "passed"


def test_run_id_of_another_project_or_unknown_is_404(client, auth, project_role, seed_run):
    project_role("viewer")
    other = seed_run(T0, results=(("search", "failed", 5),), project_id=2)
    key = report_key("search")
    assert client.post(URL, json={"keys": [key], "run_id": other.id}, headers=auth()).status_code == 404
    assert client.post(URL, json={"keys": [key], "run_id": 999999}, headers=auth()).status_code == 404
    assert client.post(URL, json={"keys": [key], "run_id": 0}, headers=auth()).status_code == 422


def test_the_step_definition_and_pattern_and_key_come_with_the_failed_step(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0, results=(("search", "failed", 5),))
    row = db.query(RunResult).filter_by(run_id=run.id).one()
    row.failed_step_text, row.failed_step_line = "When I search Lisbon", 14
    row.failed_step_definition, row.failed_step_pattern = "steps/search.js:12", "When I search {…}"
    db.commit()
    key = report_key("search")
    got = client.post(URL, json={"keys": [key]}, headers=auth()).json()["results"][key]["failed_step"]
    assert got == {"text": "When I search Lisbon", "line": 14, "definition": "steps/search.js:12",
                   "pattern": "When I search {…}", "key": step_key("steps/search.js:12", "When I search Lisbon")[0]}


LINK = "https://backoffice.example.com/trips/{value}"


def add_values(db, run, *pairs):
    """pairs: (LogPattern, [values]) for the run's one result."""
    from src.ingestion.models import LogValue

    row = db.query(RunResult).filter_by(run_id=run.id).one()
    for pattern, values in pairs:
        db.add_all([LogValue(result_id=row.id, pattern_id=pattern.id, position=i, value=v)
                    for i, v in enumerate(values)])
    db.commit()


def test_the_latest_result_carries_its_values_with_their_link(client, auth, project_role, seed_run, db):
    from src.ingestion.models import LogPattern

    project_role("viewer")
    trip = LogPattern(project_id=1, name="trip_id", pattern=r'tripId="(\d+)"', link_template=LINK)
    route = LogPattern(project_id=1, name="route_key", pattern=r'routeKey="([^"]+)"')
    db.add_all([trip, route])
    db.commit()
    older = seed_run(T0, results=(("search", "passed", 5),))
    latest = seed_run(T0 + timedelta(hours=1), results=(("search", "failed", 5),))
    add_values(db, older, (trip, ["1"]))
    add_values(db, latest, (trip, ["3960562", "3960563"]), (route, ["wasToBos"]))
    key = report_key("search")

    got = client.post(URL, json={"keys": [key]}, headers=auth()).json()["results"][key]
    assert got["values"] == [
        {"name": "route_key", "values": ["wasToBos"], "link_template": None},
        {"name": "trip_id", "values": ["3960562", "3960563"], "link_template": LINK},
    ]
    as_of = client.post(URL, json={"keys": [key], "run_id": older.id}, headers=auth()).json()["results"][key]
    assert as_of["values"] == [{"name": "trip_id", "values": ["1"], "link_template": LINK}]


def test_a_result_without_values_has_an_empty_list(client, auth, project_role, seed_run):
    project_role("viewer")
    seed_run(T0, results=(("search", "passed", 5),))
    key = report_key("search")
    assert client.post(URL, json={"keys": [key]}, headers=auth()).json()["results"][key]["values"] == []


def test_a_skipped_result_carries_the_step_it_stopped_at(client, auth, project_role, seed_run, db):
    """Collector 0.9.1 sends the undefined/pending step of a skipped scenario as failed_step; it comes back the same way."""
    project_role("viewer")
    run = seed_run(T0, results=(("search", "skipped", 0), ("login", "skipped", 0)))
    row = db.query(RunResult).filter_by(run_id=run.id, name="search").one()
    row.message, row.failed_step_text, row.failed_step_line = "Undefined step", "When I search Lisbon", 14
    db.commit()
    search, login = report_key("search"), report_key("login")
    got = client.post(URL, json={"keys": [search, login]}, headers=auth()).json()["results"]
    assert got[search]["status"] == "skipped" and got[search]["message"] == "Undefined step"
    assert got[search]["failed_step"] == {"text": "When I search Lisbon", "line": 14,
                                          "key": step_key(None, "When I search Lisbon")[0]}
    # A skipped row from before 0.9.1 has no stored step and shows none
    assert got[login]["status"] == "skipped" and "failed_step" not in got[login]
