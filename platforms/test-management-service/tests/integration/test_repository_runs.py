"""Run on repository suites (repository-suites spec 5.4): dispatch goes to the suite's own workflow with its
suite id, one active run per workflow, and GitHub is asked first whether that workflow is already running."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from src.casebook.models import Case, CiTarget, RunRequest, Suite, SuiteCase
from src.casebook.utils import secret_box

BASE = "/api/v1/projects/1"
URL = f"{BASE}/run-requests"
GH = "https://api.github.com/repos/acme/obt/actions"
TOKEN = "github_pat_" + "e" * 40
FLIGHTS, HOTELS, CI = "suite-flights.yml", "suite-hotels.yml", "qeos-run.yml"


def add_case(db, number, path="tests/a.feature", name=None, status="ready"):
    db.add(Case(project_id=1, number=number, title=f"Case {number}", steps=[], created_by=1, status=status,
                source_path=path, source_key=f"{number:064d}" if path else None,
                scenario_name=name if name is not None else (f"Scenario {number}" if path else None)))


def add_suite(db, name, numbers, origin="repository", workflow=FLIGHTS, external_id=None, group="Flights",
              source_repo="Acme/OBT"):
    suite = Suite(project_id=1, name=name, created_by=1, origin=origin)
    if origin == "repository":
        suite.workflow, suite.external_id, suite.group_name, suite.source_repo = (
            workflow, external_id or name, group, source_repo)
    db.add(suite)
    db.commit()
    ids = {c.number: c.id for c in db.query(Case)}
    db.add_all([SuiteCase(suite_id=suite.id, case_id=ids[n], position=i) for i, n in enumerate(numbers)])
    db.commit()
    return suite


@pytest.fixture
def project(client, auth, project_role, secrets_key, db):
    project_role("member")
    for number in range(1, 6):
        add_case(db, number)
    add_case(db, 6, status="archived")
    add_case(db, 7, path=None)  # a manual case
    db.add(CiTarget(project_id=1, provider="github", repo="acme/obt", workflow=CI, ref="main",
                    token_encrypted=secret_box.encrypt(TOKEN), token_last4=TOKEN[-4:], updated_by=1,
                    updated_at=datetime.now(timezone.utc)))
    db.commit()
    return client


@pytest.fixture
def legs(db, project):
    """Flights has two legs that share case 2; Hotels has one."""
    return {
        "non_booking": add_suite(db, "Flights amadeus non booking", [1, 2, 6, 7],
                                 external_id="flights-amadeus-non-booking"),
        "booking": add_suite(db, "Flights booking", [3, 2], external_id="flights-booking"),
        "hotels": add_suite(db, "Hotels", [4], workflow=HOTELS, external_id="hotels", group="Hotels"),
    }


def runs_route(http, workflow, *runs, status=200):
    return http.get(f"{GH}/workflows/{workflow}/runs", name=f"runs-{workflow}").mock(
        return_value=httpx.Response(status, json={"total_count": len(runs), "workflow_runs": list(runs)}))


def dispatch_route(http, workflow, run_id=None):
    if run_id is None:
        response = httpx.Response(204)
    else:
        response = httpx.Response(200, json={"workflow_run_id": run_id,
                                             "html_url": f"https://github.com/acme/obt/actions/runs/{run_id}"})
    return http.post(f"{GH}/workflows/{workflow}/dispatches", name=f"dispatch-{workflow}").mock(
        return_value=response)


def play(client, auth, **body):
    return client.post(URL, json=body, headers=auth())


def sent(route):
    return json.loads(route.calls.last.request.read())


def test_run_repository_suite_dispatches_its_workflow(project, auth, http, db, legs):
    runs_route(http, FLIGHTS)
    route = dispatch_route(http, FLIGHTS, run_id=900)
    r = play(project, auth, suite_id=legs["non_booking"].id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert sent(route) == {"ref": "main", "return_run_details": True,
                           "inputs": {"suites": "flights-amadeus-non-booking", "request_id": str(body["id"])}}
    # QEOS's view of the membership, archived and manual cases included: the workflow runs its folders
    assert [c["case_number"] for c in body["selection"]] == [1, 2, 6, 7]
    assert body["selection"][0] == {"case_number": 1, "key": "TC-1", "path": "tests/a.feature", "name": "Scenario 1"}
    assert (body["case_count"], body["skipped_manual"], body["suite_id"]) == (4, 0, legs["non_booking"].id)
    assert body["github_run_id"] == 900
    assert db.get(RunRequest, body["id"]).workflow == FLIGHTS


def test_run_all_sends_blank_suites(project, auth, http, db, legs):
    runs_route(http, FLIGHTS)
    route = dispatch_route(http, FLIGHTS)
    r = play(project, auth, workflow_group=FLIGHTS)
    assert r.status_code == 201, r.text
    body = r.json()
    assert sent(route)["inputs"] == {"suites": "", "request_id": str(body["id"])}
    assert [c["case_number"] for c in body["selection"]] == [1, 2, 6, 7, 3]  # by suite, then position, once each
    assert body["suite_id"] is None
    assert db.get(RunRequest, body["id"]).workflow == FLIGHTS


def test_large_group_is_not_capped_at_200(project, auth, http, db):
    for number in range(100, 351):
        add_case(db, number)
    db.commit()
    add_suite(db, "Big", list(range(100, 351)), external_id="big")
    runs_route(http, FLIGHTS)
    dispatch_route(http, FLIGHTS)
    r = play(project, auth, workflow_group=FLIGHTS)
    assert r.status_code == 201, r.text
    assert r.json()["case_count"] == 251


def test_empty_membership_still_runs(project, auth, http, db):
    suite = add_suite(db, "Nothing imported", [], external_id="empty")
    runs_route(http, FLIGHTS)
    route = dispatch_route(http, FLIGHTS)
    r = play(project, auth, suite_id=suite.id)
    assert r.status_code == 201, r.text
    assert (r.json()["case_count"], r.json()["selection"]) == (0, [])
    assert sent(route)["inputs"]["suites"] == "empty"


def test_busy_workflow_is_409_and_nothing_dispatched(project, auth, http, db, legs):
    runs_route(http, FLIGHTS, {"id": 77, "status": "waiting", "event": "schedule",
                               "run_started_at": "2026-10-19T21:00:00Z", "created_at": "2026-10-19T20:59:00Z",
                               "html_url": "https://github.com/acme/obt/actions/runs/77"})
    route = dispatch_route(http, FLIGHTS)
    r = play(project, auth, suite_id=legs["booking"].id)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == {
        "code": "workflow_busy", "run_url": "https://github.com/acme/obt/actions/runs/77",
        "message": "Flights is already running on GitHub (started 21:00). Try again when it finishes."}
    assert not route.called
    assert db.query(RunRequest).count() == 0


@pytest.mark.parametrize("failure", [
    {"side_effect": httpx.ConnectTimeout("slow")},
    {"return_value": httpx.Response(500)},
    {"return_value": httpx.Response(429, headers={"retry-after": "30"})},
])
def test_github_unreachable_refuses(project, auth, http, db, legs, failure):
    http.get(f"{GH}/workflows/{FLIGHTS}/runs").mock(**failure)
    route = dispatch_route(http, FLIGHTS)
    r = play(project, auth, suite_id=legs["booking"].id)
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == {
        "code": "github_unavailable", "message": "GitHub could not be asked whether Flights is running; try again."}
    assert not route.called
    assert db.query(RunRequest).count() == 0  # no row, so no slot is held


def test_repository_mismatch_is_409(project, auth, http, db):
    suite = add_suite(db, "Elsewhere", [1], external_id="elsewhere", source_repo="other-org/tests")
    route = dispatch_route(http, FLIGHTS)
    r = play(project, auth, suite_id=suite.id)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == {"code": "repository_mismatch",
                                  "message": "Set up Run from QEOS in Project Settings for other-org/tests"}
    assert not route.called and db.query(RunRequest).count() == 0


def test_a_suite_synced_without_a_repository_runs_against_the_target(project, auth, http, db):
    suite = add_suite(db, "Local sync", [1], external_id="local", source_repo=None)
    runs_route(http, FLIGHTS)
    route = dispatch_route(http, FLIGHTS)
    assert play(project, auth, suite_id=suite.id).status_code == 201
    assert route.called


def test_two_workflows_run_at_once(project, auth, http, legs):
    runs_route(http, FLIGHTS)
    runs_route(http, HOTELS)
    dispatch_route(http, FLIGHTS, run_id=901)
    dispatch_route(http, HOTELS, run_id=902)
    dispatch_route(http, CI, run_id=903)
    assert play(project, auth, suite_id=legs["booking"].id).status_code == 201
    assert play(project, auth, workflow_group=HOTELS).status_code == 201
    assert play(project, auth, case_numbers=[5]).status_code == 201  # the CI target's workflow has its own slot


def test_same_workflow_twice_is_run_active(project, auth, http, legs):
    runs_route(http, FLIGHTS)
    dispatch = dispatch_route(http, FLIGHTS, run_id=901)
    first = play(project, auth, suite_id=legs["booking"].id).json()
    http.get(f"{GH}/runs/901").mock(return_value=httpx.Response(200, json={"id": 901, "status": "in_progress"}))
    r = play(project, auth, workflow_group=FLIGHTS)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == {"code": "run_active", "message": "A run of Flights is in progress",
                                  "run_request_id": first["id"]}
    assert dispatch.call_count == 1


def test_hand_made_suite_still_uses_ci_target_workflow(project, auth, http, db, legs):
    suite = add_suite(db, "Smoke", [3, 1], origin="manual")
    route = dispatch_route(http, CI)
    r = play(project, auth, suite_id=suite.id)
    assert r.status_code == 201, r.text
    assert sent(route)["inputs"] == {"paths": json.dumps(["tests/a.feature"]),
                                     "names": json.dumps(["Scenario 3", "Scenario 1"]),
                                     "request_id": str(r.json()["id"])}
    assert not [c for c in http.calls if c.request.url.path.endswith("/runs")]  # no busy check
    assert db.get(RunRequest, r.json()["id"]).workflow == CI


def test_unknown_workflow_group_is_404(project, auth, http, db, legs):
    add_suite(db, "Hand made", [1], origin="manual")
    assert play(project, auth, workflow_group="suite-nope.yml").status_code == 404
    assert play(project, auth, workflow_group=CI).status_code == 404  # no repository suite has it
    assert play(project, auth, workflow_group="../x.yml").status_code == 422
    assert play(project, auth, workflow_group=FLIGHTS, suite_id=legs["booking"].id).status_code == 422
    assert not [c for c in http.calls if "/dispatches" in c.request.url.path]


def test_refresh_matches_title_in_row_workflow(project, auth, http, legs):
    runs_route(http, FLIGHTS)
    dispatch_route(http, FLIGHTS)  # a 204: no run details
    rid = play(project, auth, suite_id=legs["booking"].id).json()["id"]
    route = runs_route(http, FLIGHTS, {"id": 950, "display_title": f"QEOS #{rid}", "status": "in_progress",
                                       "event": "workflow_dispatch", "created_at": "2099-01-01T00:00:00Z",
                                       "html_url": "https://github.com/acme/obt/actions/runs/950"})
    body = project.get(f"{URL}/{rid}", headers=auth()).json()
    assert (body["github_run_id"], body["status"]) == (950, "running")
    assert route.calls.last.request.url.params["event"] == "workflow_dispatch"
    assert not [c for c in http.calls if f"/workflows/{CI}/" in c.request.url.path]
