"""POST/GET run-requests: Play dispatches the CI workflow; GETs refresh from GitHub (stubbed)."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.casebook.models import Case, CiTarget, RunRequest, Suite, SuiteCase
from src.casebook.service import run_request_service
from src.casebook.utils import secret_box

BASE = "/api/v1/projects/1"
URL = f"{BASE}/run-requests"
TOKEN = "github_pat_" + "d" * 40
CHECKOUT, LOGIN = "tests/features/checkout.feature", "tests/features/login.feature"
VOUCHER_NAME = 'Pay with a "voucher" (50% off) $5 [promo]'
FEATURE = (
    "Feature: Checkout\n"
    "  Scenario: Pay by card\n    Given x\n"
    f"  Scenario: {VOUCHER_NAME}\n    Given y\n"
    "  Scenario Outline: Book <city> flight\n    Given <city>\n    Examples:\n      | city |\n      | Rome |\n"
)
# The import numbers cases in (path, scenario) order; the manual case comes last
BOOK, CARD, VOUCHER, LOG_IN, MANUAL = 1, 2, 3, 4, 5


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.at

    def tick(self, **delta):
        self.at += timedelta(**delta)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(run_request_service, "now", c)
    return c


@pytest.fixture
def project(client, auth, project_role, secrets_key, db, github):
    project_role("member")
    files = [{"path": CHECKOUT, "content": FEATURE},
             {"path": LOGIN, "content": "Feature: Login\n  Scenario: Log in\n    Given z\n"}]
    assert client.post(f"{BASE}/cases/import", json={"files": files}, headers=auth()).status_code == 200
    assert client.post(f"{BASE}/cases", json={"title": "Manual"}, headers=auth()).status_code == 201
    assert {c.number: c.scenario_name for c in db.query(Case)} == {
        BOOK: "Book <city> flight", CARD: "Pay by card", VOUCHER: VOUCHER_NAME, LOG_IN: "Log in", MANUAL: None}
    db.add(CiTarget(project_id=1, provider="github", repo=github.repo, workflow=github.workflow, ref="main",
                    token_encrypted=secret_box.encrypt(TOKEN), token_last4=TOKEN[-4:], updated_by=1,
                    updated_at=datetime.now(timezone.utc)))
    db.commit()
    return client


def play(client, auth, **body):
    return client.post(URL, json=body, headers=auth())


def get(client, auth, rid):
    r = client.get(f"{URL}/{rid}", headers=auth())
    assert r.status_code == 200, r.text
    return r.json()


def test_cases_become_files_and_raw_names_and_the_dispatch_body_is_exact(project, auth, github, clock):
    route = github.dispatch(run_id=500)
    r = play(project, auth, case_numbers=[CARD, BOOK, LOG_IN, CARD])
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["case_count"], body["refreshing"], body["requested_by"]) == ("queued", 3, True, 1)
    assert body["selection"][0] == {"case_number": CARD, "path": CHECKOUT, "name": "Pay by card"}
    assert json.loads(route.calls.last.request.read()) == {
        "ref": "main",
        "inputs": {
            "paths": json.dumps([CHECKOUT, LOGIN]),
            "names": json.dumps(["Pay by card", "Book <city> flight", "Log in"]),
            "request_id": str(body["id"]),
        },
        "return_run_details": True,
    }
    assert TOKEN not in r.text


def test_a_200_dispatch_stores_the_run_at_once_and_polling_never_lists_runs(project, auth, github, http, clock):
    github.dispatch(run_id=501)
    body = play(project, auth, case_numbers=[CARD]).json()
    assert (body["status"], body["github_run_id"], body["github_run_url"]) == (
        "queued", 501, f"https://github.com/{github.repo}/actions/runs/501")
    run = github.run(github.run_body(501, body["id"], status="in_progress"))
    clock.tick(minutes=3)  # well past the 2-minute fallback limit: a known run never becomes failed_to_start
    assert get(project, auth, body["id"])["status"] == "running"
    assert run.call_count == 1
    assert not [c for c in http.calls if c.request.url.path.endswith(f"/workflows/{github.workflow}/runs")]


def test_a_dispatch_url_outside_github_is_not_stored(project, auth, github, http, clock):
    http.post(f"https://api.github.com/repos/{github.repo}/actions/workflows/{github.workflow}/dispatches",
              name="gh-dispatch").mock(
        return_value=httpx.Response(200, json={"workflow_run_id": 501, "html_url": "javascript:alert(1)"}))
    body = play(project, auth, case_numbers=[CARD]).json()
    assert body["github_run_id"] == 501 and body["github_run_url"] is None


def test_a_name_with_quotes_and_regex_characters_is_sent_raw(project, auth, github, clock):
    route = github.dispatch()
    assert play(project, auth, case_numbers=[VOUCHER]).status_code == 201
    assert json.loads(json.loads(route.calls.last.request.read())["inputs"]["names"]) == [VOUCHER_NAME]


def test_a_suite_expands_in_its_order(project, auth, db, github, clock):
    suite = Suite(project_id=1, name="Smoke", created_by=1)
    db.add(suite)
    db.commit()
    ids = {c.number: c.id for c in db.query(Case)}
    db.add_all([SuiteCase(suite_id=suite.id, case_id=ids[LOG_IN], position=0),
                SuiteCase(suite_id=suite.id, case_id=ids[CARD], position=1)])
    db.commit()
    github.dispatch()
    r = play(project, auth, suite_id=suite.id)
    assert r.status_code == 201, r.text
    assert r.json()["suite_id"] == suite.id
    assert [c["case_number"] for c in r.json()["selection"]] == [LOG_IN, CARD]


def test_an_empty_suite_is_422_and_an_unknown_one_404(project, auth, db, github):
    suite = Suite(project_id=1, name="Empty", created_by=1)
    db.add(suite)
    db.commit()
    dispatch = github.dispatch()
    assert play(project, auth, suite_id=suite.id).status_code == 422
    assert play(project, auth, suite_id=999).status_code == 404
    assert not dispatch.called


def test_manual_archived_and_unknown_cases_are_rejected_with_their_numbers(project, auth, db, github):
    db.query(Case).filter(Case.number == BOOK).one().status = "archived"
    db.commit()
    dispatch = github.dispatch()
    r = play(project, auth, case_numbers=[BOOK, CARD, MANUAL, 99])
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "TC-99" in detail and "TC-5" in detail and "TC-1" in detail and "TC-2" not in detail
    assert "No such case: TC-99" in detail
    assert "Manual cases cannot run: TC-5" in detail
    assert "Archived cases cannot run: TC-1" in detail
    assert not dispatch.called


def test_a_case_without_scenario_name_asks_for_a_reimport(project, auth, db, github):
    db.query(Case).filter(Case.number == CARD).one().scenario_name = None
    db.commit()
    r = play(project, auth, case_numbers=[CARD])
    assert r.status_code == 422
    assert "re-import the .feature files first" in r.json()["detail"] and "TC-2" in r.json()["detail"]


@pytest.mark.parametrize("body", [
    {"case_numbers": []}, {"case_numbers": list(range(1, 202))}, {}, {"case_numbers": [1], "suite_id": 1},
    {"case_numbers": [0]}])
def test_bad_bodies_are_422(project, auth, body):
    assert project.post(URL, json=body, headers=auth()).status_code == 422


def test_a_selection_too_large_for_one_dispatch_is_422(project, auth, github):
    big = "Feature: Big\n" + "".join(f"  Scenario: {'x' * 330} {i}\n    Given x\n" for i in range(200))
    imported = project.post(f"{BASE}/cases/import", json={"files": [{"path": "tests/features/big.feature", "content": big}]},
                            headers=auth())
    assert imported.status_code == 200
    dispatch = github.dispatch()
    r = play(project, auth, case_numbers=list(range(6, 206)))
    assert r.status_code == 422 and "too large" in r.json()["detail"]
    assert not dispatch.called


def test_a_viewer_is_403(project, auth, project_role):
    project_role("viewer")
    assert play(project, auth, case_numbers=[CARD]).status_code == 403
    assert project.get(URL, headers=auth()).status_code == 200


def test_no_target_is_412(project, auth, db):
    db.query(CiTarget).delete()
    db.commit()
    assert play(project, auth, case_numbers=[CARD]).status_code == 412


def test_a_failed_dispatch_is_failed_to_start_and_frees_the_slot(project, auth, github, clock):
    github.dispatch(status=404)
    r = play(project, auth, case_numbers=[CARD])
    assert r.status_code == 201
    assert r.json()["status"] == "failed_to_start" and "default branch" in r.json()["error"]
    assert r.json()["refreshing"] is False
    github.dispatch()
    assert play(project, auth, case_numbers=[CARD]).status_code == 201


def test_a_rate_limited_dispatch_leaves_nothing_behind(project, auth, github, db, clock):
    github.dispatch(status=429, headers={"retry-after": "30"})
    r = play(project, auth, case_numbers=[CARD])
    assert r.status_code == 503 and r.json()["detail"] == "GitHub rate limit, try again in 30 s"
    assert r.headers["retry-after"] == "30"
    assert db.query(RunRequest).count() == 0


def test_an_active_run_still_running_on_github_is_409(project, auth, github, clock):
    github.dispatch(run_id=500)
    first = play(project, auth, case_numbers=[CARD]).json()
    github.run(github.run_body(500, first["id"], status="in_progress"))
    r = play(project, auth, case_numbers=[BOOK])
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "run_active" and r.json()["detail"]["run_request_id"] == first["id"]


def test_a_run_that_finished_unseen_does_not_block_the_next_play(project, auth, github, clock):
    github.dispatch(run_id=500)
    first = play(project, auth, case_numbers=[CARD]).json()
    github.run(github.run_body(500, first["id"], status="in_progress"))
    assert get(project, auth, first["id"])["status"] == "running"  # sets checked_at: the next GET is throttled
    github.run(github.run_body(500, first["id"], status="completed", conclusion="success"))
    github.dispatch(run_id=600)
    second = play(project, auth, case_numbers=[BOOK])  # no clock tick: only a forced refresh sees it ended
    assert second.status_code == 201, second.text
    assert get(project, auth, first["id"])["status"] == "completed"


def test_double_click_dispatches_once(project, auth, github, clock):
    dispatch = github.dispatch(run_id=500)
    run = github.run(github.run_body(500, 1, status="queued"))
    a = play(project, auth, case_numbers=[CARD])
    assert a.status_code == 201
    assert get(project, auth, a.json()["id"])["status"] == "queued"  # checked_at is set: a plain refresh is throttled
    assert run.call_count == 1
    b = play(project, auth, case_numbers=[CARD])
    assert b.status_code == 409
    assert run.call_count == 2  # the pre-409 refresh asked GitHub despite the throttle
    assert dispatch.call_count == 1


def test_two_simultaneous_plays_the_index_decides_and_the_loser_is_409(project, auth, github, clock, monkeypatch):
    dispatch = github.dispatch(run_id=500)
    first = play(project, auth, case_numbers=[CARD])
    assert first.status_code == 201
    monkeypatch.setattr(run_request_service, "active_request", lambda db, project_id, workflow=None: None)  # the race: no one seen
    r = play(project, auth, case_numbers=[BOOK])
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "run_active" and r.json()["detail"]["run_request_id"] is None
    assert dispatch.call_count == 1


def test_a_commit_that_loses_the_race_in_a_refresh_is_not_a_500(project, auth, github, db, clock, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    real_commit, calls = db.commit, []

    def commit():
        calls.append(1)
        if len(calls) == 2:  # the first commit ends the read transaction, the second writes the result
            db.rollback()
            raise IntegrityError("update", {}, Exception("uq_run_requests_one_active"))
        return real_commit()

    monkeypatch.setattr(db, "commit", commit)
    row = db.get(RunRequest, rid)
    assert run_request_service.refresh(db, row) is row
    assert (row.id, row.status) == (rid, "queued")  # the write was lost: the row is as the database has it


@pytest.mark.parametrize("gh_status, conclusion, status", [
    ("queued", None, "queued"), ("waiting", None, "queued"), ("requested", None, "queued"),
    ("pending", None, "queued"), ("in_progress", None, "running"), ("completed", "success", "completed"),
    ("completed", "failure", "completed"), ("completed", "timed_out", "completed"),
    ("completed", "cancelled", "cancelled")])
def test_github_status_maps_to_ours(project, auth, github, clock, gh_status, conclusion, status):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status=gh_status, conclusion=conclusion))
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["conclusion"]) == (status, conclusion)
    assert body["refreshing"] is (status in ("queued", "running"))


# --- The 204 fallback: GitHub gave no run details, so polling matches the run by its title ---

def test_after_a_204_the_run_is_matched_by_display_title(project, auth, github, clock):
    github.dispatch()  # 204: no run details
    started = play(project, auth, case_numbers=[CARD]).json()
    rid = started["id"]
    assert started["github_run_id"] is None and started["github_run_url"] is None
    github.runs(github.run_body(400, rid + 1), github.run_body(501, rid))
    clock.tick(seconds=6)
    matched = get(project, auth, rid)
    assert (matched["status"], matched["github_run_id"]) == ("queued", 501)
    assert matched["github_run_url"] == f"https://github.com/{github.repo}/actions/runs/501"
    github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    assert get(project, auth, rid)["status"] == "running"


def test_after_a_204_a_run_titled_by_a_pre_rename_workflow_still_matches(project, auth, github, clock):
    """Workflows copied before the QEOS rename keep run-name "QA Vision #<id>"."""
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs(github.run_body(501, rid, title=f"QA Vision #{rid}"))
    clock.tick(seconds=6)
    assert get(project, auth, rid)["github_run_id"] == 501


def test_a_run_url_outside_github_is_not_stored(project, auth, github, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs({**github.run_body(501, rid), "html_url": "javascript:alert(1)"})
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert body["github_run_id"] == 501 and body["github_run_url"] is None


def test_github_is_asked_at_most_every_5_seconds(project, auth, github, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    runs = github.runs()
    clock.tick(seconds=6)
    get(project, auth, rid)
    clock.tick(seconds=3)
    get(project, auth, rid)
    project.get(URL, headers=auth())
    assert runs.call_count == 1
    clock.tick(seconds=3)
    get(project, auth, rid)
    assert runs.call_count == 2


def test_the_run_list_is_asked_from_a_minute_before_the_request_in_utc(project, auth, github, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    runs = github.runs()
    clock.tick(seconds=6)
    get(project, auth, rid)
    params = runs.calls.last.request.url.params
    assert params["created"] == ">=2026-10-07T09:59:00Z" and params["event"] == "workflow_dispatch"


def test_a_run_never_seen_after_2_minutes_failed_to_start(project, auth, github, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs()
    clock.tick(seconds=119)
    assert get(project, auth, rid)["status"] == "queued"
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["error"], body["refreshing"]) == ("failed_to_start", "The workflow did not start", False)
    assert play(project, auth, case_numbers=[BOOK]).status_code == 201


def test_a_github_outage_within_2_minutes_keeps_the_row_active_and_says_why(project, auth, github, http, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    http.get(f"https://api.github.com/repos/{github.repo}/actions/workflows/{github.workflow}/runs",
             name="gh-runs").mock(return_value=httpx.Response(503))
    clock.tick(seconds=60)
    body = get(project, auth, rid)
    assert (body["status"], body["error"], body["refreshing"]) == ("queued", "GitHub answered 503", True)


@pytest.mark.parametrize("code", [401, 404, 503])
def test_a_github_failure_past_2_minutes_is_failed_to_start_with_the_reason(project, auth, github, http, clock, code):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    http.get(f"https://api.github.com/repos/{github.repo}/actions/workflows/{github.workflow}/runs",
             name="gh-runs").mock(return_value=httpx.Response(code))
    clock.tick(minutes=3)
    body = get(project, auth, rid)
    assert (body["status"], body["refreshing"]) == ("failed_to_start", False)
    assert body["error"].startswith("The workflow did not start") and len(body["error"]) > len("The workflow did not start")
    github.dispatch()
    assert play(project, auth, case_numbers=[BOOK]).status_code == 201


def test_a_rate_limit_on_the_fallback_past_2_minutes_is_failed_to_start(project, auth, github, http, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    http.get(f"https://api.github.com/repos/{github.repo}/actions/workflows/{github.workflow}/runs",
             name="gh-runs").mock(return_value=httpx.Response(429, headers={"retry-after": "30"}))
    clock.tick(minutes=3)
    body = get(project, auth, rid)
    assert body["status"] == "failed_to_start" and "rate limit" in body["error"]


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout("slow"), httpx.Response(500), httpx.Response(502)])
def test_a_dispatch_that_may_have_started_a_run_keeps_the_row_queued_for_matching(
        project, auth, github, http, clock, failure):
    route = http.post(f"https://api.github.com/repos/{github.repo}/actions/workflows/{github.workflow}/dispatches",
                      name="gh-dispatch")
    if isinstance(failure, Exception):
        route.mock(side_effect=failure)
    else:
        route.mock(return_value=failure)
    r = play(project, auth, case_numbers=[CARD])
    assert r.status_code == 201
    body = r.json()
    assert (body["status"], body["github_run_id"], body["refreshing"]) == ("queued", None, True)
    assert body["error"] == "GitHub did not confirm the start; checking…"
    github.runs(github.run_body(501, body["id"]))
    clock.tick(seconds=6)
    matched = get(project, auth, body["id"])
    assert (matched["github_run_id"], matched["error"]) == (501, None)


@pytest.mark.parametrize("code", [401, 403, 404, 422])
def test_a_dispatch_github_refused_is_failed_to_start_at_once(project, auth, github, clock, code):
    github.dispatch(status=code)
    body = play(project, auth, case_numbers=[CARD]).json()
    assert (body["status"], body["refreshing"]) == ("failed_to_start", False)


def test_a_cancelling_row_is_never_downgraded_by_a_refresh(project, auth, github, db, clock):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    db.query(RunRequest).filter(RunRequest.id == rid).update({"status": "cancelling"})
    db.commit()
    run = github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert run.call_count == 1 and (body["status"], body["refreshing"]) == ("cancelling", True)
    github.run(github.run_body(501, rid, status="completed", conclusion="cancelled"))
    clock.tick(seconds=6)
    assert get(project, auth, rid)["status"] == "cancelled"


def test_a_rate_limit_on_a_known_run_keeps_the_status_and_says_so(project, auth, github, http, clock):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    http.get(f"https://api.github.com/repos/{github.repo}/actions/runs/501", name="gh-run-501").mock(
        return_value=httpx.Response(429, headers={"retry-after": "30"}))
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["error"]) == ("queued", "GitHub rate limit, try again in 30 s")


def test_the_list_is_newest_first_with_a_total(project, auth, github, clock):
    github.dispatch(status=404)
    first = play(project, auth, case_numbers=[CARD]).json()  # failed_to_start frees the slot
    github.dispatch()
    second = play(project, auth, case_numbers=[LOG_IN]).json()
    github.runs()
    page = project.get(f"{URL}?limit=1", headers=auth()).json()
    assert page["total"] == 2 and [i["id"] for i in page["items"]] == [second["id"]]
    assert project.get(f"{URL}?limit=1&offset=1", headers=auth()).json()["items"][0]["id"] == first["id"]


def test_another_projects_request_is_404(project, auth, github, project_role, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    project_role("member", project_id=2)
    assert project.get(f"/api/v1/projects/2/run-requests/{rid}", headers=auth()).status_code == 404


# --- Controller ruling F1: a run GitHub no longer knows ends the row; other failures keep the state ---

def test_a_known_run_gone_from_github_ends_cancelled_and_frees_the_slot(project, auth, github, http, clock):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    http.get(f"https://api.github.com/repos/{github.repo}/actions/runs/501", name="gh-run-501").mock(
        return_value=httpx.Response(404))
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["error"], body["refreshing"]) == ("cancelled", "The run is no longer on GitHub", False)
    github.dispatch(run_id=502)
    assert play(project, auth, case_numbers=[BOOK]).status_code == 201


@pytest.mark.parametrize("code", [401, 403, 500, 503])
def test_other_github_failures_for_a_known_run_keep_the_status_and_store_the_error(
        project, auth, github, http, clock, code):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    http.get(f"https://api.github.com/repos/{github.repo}/actions/runs/501", name="gh-run-501").mock(
        return_value=httpx.Response(code))
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert body["status"] == "queued" and body["refreshing"] is True and body["error"]


def test_a_github_failure_that_clears_removes_the_stored_error(project, auth, github, http, clock):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    http.get(f"https://api.github.com/repos/{github.repo}/actions/runs/501", name="gh-run-501").mock(
        return_value=httpx.Response(500))
    clock.tick(seconds=6)
    assert get(project, auth, rid)["error"]
    github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["error"]) == ("running", None)


# --- Task 5: Stop ---

def known_run(project, auth, github, clock, status="in_progress"):
    """A request whose GitHub run (id 501, from the 200 dispatch) is in the given state."""
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status=status))
    clock.tick(seconds=6)
    assert get(project, auth, rid)["github_run_id"] == 501
    return rid


def test_stop_right_after_play_cancels_the_run_at_once(project, auth, github, clock):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status="queued"))
    cancel = github.cancel(501)
    r = project.post(f"{URL}/{rid}/stop", headers=auth(7))  # no tick, no matching: the id came with Play
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["stopped_by"]) == ("cancelling", 7)
    assert cancel.call_count == 1


def test_stop_cancels_on_github_and_records_who(project, auth, github, clock):
    rid = known_run(project, auth, github, clock)
    cancel = github.cancel(501)
    r = project.post(f"{URL}/{rid}/stop", headers=auth(7))
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["stopped_by"]) == ("cancelling", 7) and r.json()["stopped_at"]
    assert cancel.call_count == 1
    github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    assert get(project, auth, rid)["status"] == "cancelling"  # until GitHub says it ended
    github.run(github.run_body(501, rid, status="completed", conclusion="cancelled"))
    clock.tick(seconds=6)
    after = get(project, auth, rid)
    assert (after["status"], after["stopped_by"], after["refreshing"]) == ("cancelled", 7, False)


def test_stopping_a_finished_run_is_409(project, auth, github, clock):
    rid = known_run(project, auth, github, clock, status="completed")
    cancel = github.cancel(501)
    r = project.post(f"{URL}/{rid}/stop", headers=auth())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "run_finished"
    assert not cancel.called


def test_a_run_that_ends_while_stopping_is_409(project, auth, github, clock):
    rid = known_run(project, auth, github, clock)
    github.cancel(501, status=409)
    github.run(github.run_body(501, rid, status="completed", conclusion="success"))
    assert project.post(f"{URL}/{rid}/stop", headers=auth()).status_code == 409
    assert get(project, auth, rid)["status"] == "completed"


def test_a_run_that_turns_completed_during_the_cancel_call_is_409_and_not_overwritten(
        project, auth, github, db, clock, monkeypatch):
    rid = known_run(project, auth, github, clock)

    def cancel_while_it_ends(token, repo, run_id):
        db.query(RunRequest).filter(RunRequest.id == rid).update({"status": "completed", "conclusion": "success"})
        db.commit()  # a concurrent refresh wrote the end of the run first

    monkeypatch.setattr(run_request_service.github_client, "cancel_run", cancel_while_it_ends)
    r = project.post(f"{URL}/{rid}/stop", headers=auth(7))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "run_finished"
    row = db.query(RunRequest).filter(RunRequest.id == rid).one()
    db.refresh(row)
    assert (row.status, row.stopped_by) == ("completed", None)


def test_a_second_stop_leaves_the_first_stoppers_name(project, auth, github, clock):
    rid = known_run(project, auth, github, clock)
    cancel = github.cancel(501)
    first = project.post(f"{URL}/{rid}/stop", headers=auth(7)).json()
    second = project.post(f"{URL}/{rid}/stop", headers=auth(8))
    assert second.status_code == 200
    assert second.json()["status"] == "cancelling"
    assert (second.json()["stopped_by"], second.json()["stopped_at"]) == (7, first["stopped_at"])
    assert cancel.call_count == 1


def test_stop_when_github_no_longer_knows_the_run_ends_it_cancelled(project, auth, github, clock):
    rid = known_run(project, auth, github, clock)
    github.cancel(501, status=404)
    r = project.post(f"{URL}/{rid}/stop", headers=auth(7))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["error"], body["stopped_by"], body["refreshing"]) == (
        "cancelled", "The run is no longer on GitHub", 7, False)
    github.dispatch(run_id=502)
    assert play(project, auth, case_numbers=[BOOK]).status_code == 201


@pytest.mark.parametrize("code", [401, 403, 500, 502])
def test_stop_failing_at_github_keeps_the_state_and_says_why(project, auth, github, clock, code):
    rid = known_run(project, auth, github, clock)
    github.cancel(501, status=code)
    assert project.post(f"{URL}/{rid}/stop", headers=auth(7)).status_code == 502
    body = project.get(f"{URL}/{rid}", headers=auth()).json()
    assert (body["status"], body["stopped_by"], body["stopped_at"]) == ("running", None, None)
    assert body["error"]


def test_stop_on_a_network_failure_is_502_and_changes_nothing(project, auth, github, http, clock):
    rid = known_run(project, auth, github, clock)
    http.post(f"https://api.github.com/repos/{github.repo}/actions/runs/501/cancel", name="gh-cancel-501").mock(
        side_effect=httpx.ConnectError("down"))
    assert project.post(f"{URL}/{rid}/stop", headers=auth(7)).status_code == 502
    body = get(project, auth, rid)
    assert (body["status"], body["stopped_by"]) == ("running", None)


def test_stop_during_a_rate_limit_is_503_with_retry_after_and_changes_nothing(project, auth, github, http, clock):
    rid = known_run(project, auth, github, clock)
    http.post(f"https://api.github.com/repos/{github.repo}/actions/runs/501/cancel", name="gh-cancel-501").mock(
        return_value=httpx.Response(429, headers={"retry-after": "30"}))
    r = project.post(f"{URL}/{rid}/stop", headers=auth(7))
    assert r.status_code == 503 and r.headers["retry-after"] == "30"
    body = get(project, auth, rid)
    assert (body["status"], body["stopped_by"], body["error"]) == ("running", None, None)


def test_stop_without_a_target_is_412(project, auth, github, db, clock):
    rid = known_run(project, auth, github, clock)
    db.query(CiTarget).delete()
    db.commit()
    assert project.post(f"{URL}/{rid}/stop", headers=auth()).status_code == 412


def test_after_a_204_a_queued_request_without_a_run_is_cancelled_locally_then_on_github(project, auth, github, clock):
    github.dispatch()  # 204: no run details, the fallback
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs()
    r = project.post(f"{URL}/{rid}/stop", headers=auth(7))
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["stopped_by"], r.json()["refreshing"]) == ("cancelled", 7, True)
    assert play(project, auth, case_numbers=[LOG_IN]).status_code == 201  # the slot is free
    github.runs(github.run_body(501, rid))
    cancel = github.cancel(501)
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["github_run_id"], body["refreshing"]) == ("cancelled", 501, False)
    assert cancel.call_count == 1


def test_after_a_204_a_stopped_request_whose_run_never_appears_stops_looking_after_2_minutes(project, auth, github, clock):
    github.dispatch()  # 204
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs()
    project.post(f"{URL}/{rid}/stop", headers=auth())
    clock.tick(minutes=2, seconds=1)
    body = get(project, auth, rid)
    assert (body["status"], body["refreshing"]) == ("cancelled", False)


def test_a_viewer_cannot_stop_and_an_unknown_request_is_404(project, auth, github, clock, project_role):
    rid = known_run(project, auth, github, clock)
    project_role("viewer")
    assert project.post(f"{URL}/{rid}/stop", headers=auth()).status_code == 403
    project_role("member")
    assert project.post(f"{URL}/9999/stop", headers=auth()).status_code == 404


# --- Fix wave A1: refresh writes conditionally ---

def change_during_github_call(monkeypatch, db, rid, **changes):
    """GitHub's answer arrives after another request already changed the row."""
    real = run_request_service.github_client.get_run

    def get_run(token, repo, run_id):
        db.query(RunRequest).filter(RunRequest.id == rid).update(changes, synchronize_session=False)
        db.commit()
        return real(token, repo, run_id)

    monkeypatch.setattr(run_request_service.github_client, "get_run", get_run)


def test_a_refresh_never_overwrites_a_stop_that_landed_while_it_asked_github(project, auth, github, db, clock, monkeypatch):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    change_during_github_call(monkeypatch, db, rid, status="cancelling", stopped_by=7)
    body = get(project, auth, rid)
    assert (body["status"], body["stopped_by"]) == ("cancelling", 7)


def test_a_refresh_does_not_touch_a_row_whose_status_changed_meanwhile(project, auth, github, db, clock, monkeypatch):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    change_during_github_call(monkeypatch, db, rid, status="completed", conclusion="success")
    body = get(project, auth, rid)
    assert (body["status"], body["conclusion"]) == ("completed", "success")
    assert body["error"] is None and body["refreshing"] is False


# --- Fix wave A4: a list GET asks GitHub for a few rows, and never inside a transaction ---

def pending_cancels(db, clock, count):
    for _ in range(count):
        db.add(RunRequest(project_id=1, requested_by=1, requested_at=clock.at - timedelta(seconds=30),
                          selection=[], status="cancelled", stopped_by=1, stopped_at=clock.at - timedelta(seconds=20)))
    db.commit()


def test_a_list_get_refreshes_at_most_3_rows_and_the_next_poll_does_the_rest(project, auth, github, db, clock):
    pending_cancels(db, clock, 5)
    runs = github.runs()
    items = project.get(URL, headers=auth()).json()["items"]
    assert runs.call_count == 3
    assert sum(1 for i in items if i["checked_at"]) == 3 and all(i["refreshing"] for i in items)
    clock.tick(seconds=6)
    items = project.get(URL, headers=auth()).json()["items"]
    assert runs.call_count == 6
    assert all(i["checked_at"] for i in items)  # the two never asked go first


def test_github_is_asked_with_no_database_transaction_open(project, auth, github, db, clock, monkeypatch):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    real, open_during_call = run_request_service.github_client.get_run, []

    def get_run(token, repo, run_id):
        open_during_call.append(db.in_transaction())
        return real(token, repo, run_id)

    monkeypatch.setattr(run_request_service.github_client, "get_run", get_run)
    assert project.get(URL, headers=auth()).json()["items"][0]["status"] == "running"
    assert open_during_call == [False]


# --- Fix wave A5: a whole suite skips its manual cases ---

def make_suite(db, *numbers):
    suite = Suite(project_id=1, name="Mixed", created_by=1)
    db.add(suite)
    db.commit()
    ids = {c.number: c.id for c in db.query(Case)}
    db.add_all([SuiteCase(suite_id=suite.id, case_id=ids[n], position=i) for i, n in enumerate(numbers)])
    db.commit()
    return suite


def test_a_suite_skips_manual_cases_and_records_how_many(project, auth, db, github, clock):
    suite = make_suite(db, LOG_IN, MANUAL, CARD)
    dispatch = github.dispatch(run_id=500)
    r = play(project, auth, suite_id=suite.id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert [c["case_number"] for c in body["selection"]] == [LOG_IN, CARD]
    assert (body["case_count"], body["skipped_manual"]) == (2, 1)
    assert json.loads(json.loads(dispatch.calls.last.request.read())["inputs"]["names"]) == ["Log in", "Pay by card"]
    github.run(github.run_body(500, body["id"]))
    assert get(project, auth, body["id"])["skipped_manual"] == 1
    assert project.get(URL, headers=auth()).json()["items"][0]["skipped_manual"] == 1


def test_a_request_without_manual_cases_skips_none(project, auth, github, clock):
    github.dispatch()
    assert play(project, auth, case_numbers=[CARD]).json()["skipped_manual"] == 0


def test_a_suite_with_only_manual_cases_is_422(project, auth, db, github):
    suite = make_suite(db, MANUAL)
    dispatch = github.dispatch()
    r = play(project, auth, suite_id=suite.id)
    assert r.status_code == 422 and r.json()["detail"] == "This suite has no automated cases"
    assert not dispatch.called


def test_a_suite_still_rejects_archived_and_unnamed_cases(project, auth, db, github):
    suite = make_suite(db, LOG_IN, CARD, BOOK, MANUAL)
    db.query(Case).filter(Case.number == LOG_IN).one().status = "archived"
    db.query(Case).filter(Case.number == CARD).one().scenario_name = None
    db.commit()
    r = play(project, auth, suite_id=suite.id)
    assert r.status_code == 422
    assert "Archived cases cannot run: TC-4" in r.json()["detail"]
    assert "TC-2: re-import the .feature files first" in r.json()["detail"]
    assert "Manual" not in r.json()["detail"]


def test_an_explicit_selection_still_rejects_manual_cases(project, auth, github):
    r = play(project, auth, case_numbers=[CARD, MANUAL])
    assert r.status_code == 422 and "Manual cases cannot run: TC-5" in r.json()["detail"]


# --- Fix wave A8: Stop ---

def test_stopping_another_projects_request_is_404(project, auth, github, clock, project_role):
    rid = known_run(project, auth, github, clock)
    project_role("member", project_id=2)
    assert project.post(f"/api/v1/projects/2/run-requests/{rid}/stop", headers=auth()).status_code == 404


@pytest.mark.parametrize("role, expected", [("admin", 200), ("member", 200), ("owner", 200), ("billing_manager", 403)])
def test_stop_roles(project, auth, github, clock, project_role, role, expected):
    rid = known_run(project, auth, github, clock)
    github.cancel(501)
    project_role(role)
    assert project.post(f"{URL}/{rid}/stop", headers=auth()).status_code == expected


def test_a_pending_cancel_is_retried_after_github_fails_on_the_cancel(project, auth, github, clock):
    github.dispatch()  # 204
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs()
    assert project.post(f"{URL}/{rid}/stop", headers=auth(7)).status_code == 200
    github.runs(github.run_body(501, rid))
    github.cancel(501, status=500)
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["github_run_id"], body["refreshing"]) == ("cancelled", None, True)
    cancel = github.cancel(501)
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["github_run_id"], body["refreshing"]) == ("cancelled", 501, False)
    assert cancel.calls.last.response.status_code == 202


# ---- duration estimate (the dashboard sends what ingestion estimated; test-management never asks it) ----

def test_the_estimate_is_stored_and_returned_on_every_read(project, auth, github, clock):
    github.dispatch(run_id=900)
    body = play(project, auth, case_numbers=[CARD], estimate_ms=720_000, estimate_upper_ms=900_000).json()
    assert (body["estimate_ms"], body["estimate_upper_ms"]) == (720_000, 900_000)
    github.run(github.run_body(900, body["id"], status="in_progress"))
    assert (get(project, auth, body["id"])["estimate_ms"], get(project, auth, body["id"])["estimate_upper_ms"]) == (
        720_000, 900_000)
    listed = project.get(URL, headers=auth()).json()["items"][0]
    assert (listed["estimate_ms"], listed["estimate_upper_ms"]) == (720_000, 900_000)


def test_an_omitted_estimate_stays_null(project, auth, github, clock):
    github.dispatch(run_id=901)
    body = play(project, auth, case_numbers=[CARD]).json()
    assert (body["estimate_ms"], body["estimate_upper_ms"]) == (None, None)


def test_an_explicit_null_estimate_is_accepted(project, auth, github, clock):
    github.dispatch(run_id=902)
    r = play(project, auth, case_numbers=[CARD], estimate_ms=None, estimate_upper_ms=None)
    assert r.status_code == 201, r.text
    assert r.json()["estimate_ms"] is None


def test_the_estimate_bounds_are_inclusive(project, auth, github, clock):
    github.dispatch(run_id=903)
    r = play(project, auth, case_numbers=[CARD], estimate_ms=0, estimate_upper_ms=86_400_000)
    assert r.status_code == 201, r.text
    assert (r.json()["estimate_ms"], r.json()["estimate_upper_ms"]) == (0, 86_400_000)


@pytest.mark.parametrize("field", ["estimate_ms", "estimate_upper_ms"])
@pytest.mark.parametrize("value", [-1, 86_400_001, 1.5, "600000", True])
def test_a_bad_estimate_is_422(project, auth, field, value):
    assert play(project, auth, case_numbers=[CARD], **{field: value}).status_code == 422
