"""The GitHub REST client: api.github.com only, no redirects, specific messages, no token in errors."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.casebook.utils import github_client as gh

TOKEN = "github_pat_" + "a" * 40


def test_check_sends_the_api_headers_and_returns_the_expiry(github):
    route = github.check()
    assert gh.check_target(TOKEN, github.repo, github.workflow) == datetime(2027, 3, 12, tzinfo=timezone.utc)
    sent = route.calls.last.request
    assert sent.url.host == "api.github.com"
    assert sent.headers["Accept"] == "application/vnd.github+json"
    assert sent.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert sent.headers["Authorization"] == f"Bearer {TOKEN}"


def test_a_token_without_expiry_returns_none(github):
    github.check(expires=None)
    assert gh.check_target(TOKEN, github.repo, github.workflow) is None


@pytest.mark.parametrize("value, expected", [
    ("2027-03-12 00:00:00 UTC", datetime(2027, 3, 12, tzinfo=timezone.utc)),
    ("2027-03-12 01:00:00 +0100", datetime(2027, 3, 12, tzinfo=timezone.utc)),
    ("soon", None), ("", None), (None, None)])
def test_expiry_header_parsing(value, expected):
    assert gh.parse_expiry(value) == expected


@pytest.mark.parametrize("status, message", [(401, gh.UNAUTHORIZED), (403, gh.forbidden("acme")), (404, gh.NOT_FOUND)])
def test_check_failures_have_specific_messages_without_the_token(github, status, message):
    github.check(status=status)
    with pytest.raises(gh.GitHubError) as err:
        gh.check_target(TOKEN, github.repo, github.workflow)
    assert (err.value.status, err.value.message) == (status, message)
    assert TOKEN not in str(err.value)


def test_a_workflow_missing_from_the_default_branch_is_the_404_message(github):
    github.check(workflow_status=404)
    with pytest.raises(gh.GitHubError) as err:
        gh.check_target(TOKEN, github.repo, github.workflow)
    assert "default branch" in err.value.message


def test_a_rate_limit_says_when_to_retry(github):
    reset = int(datetime.now(timezone.utc).timestamp()) + 42
    github.check(status=403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)})
    with pytest.raises(gh.RateLimited) as err:
        gh.check_target(TOKEN, github.repo, github.workflow)
    assert 40 <= err.value.retry_after <= 42
    assert err.value.message == f"GitHub rate limit, try again in {err.value.retry_after} s"


def test_redirects_are_not_followed(http):
    http.get(f"{gh.API}/repos/acme/obt").mock(
        return_value=httpx.Response(301, headers={"location": "https://evil.example/steal"}))
    with pytest.raises(gh.GitHubError):  # following it would hit an unrouted host and raise something else
        gh.check_target(TOKEN, "acme/obt", "qeos-run.yml")


def test_a_network_error_is_a_github_error_without_details(http):
    http.get(f"{gh.API}/repos/acme/obt").mock(side_effect=httpx.ConnectTimeout("boom"))
    with pytest.raises(gh.GitHubError) as err:
        gh.check_target(TOKEN, "acme/obt", "qeos-run.yml")
    assert err.value.status == 0 and TOKEN not in err.value.message


@pytest.mark.parametrize("repo, workflow", [
    ("acme", "x.yml"), ("acme/obt/x", "x.yml"), ("acme/..", "x.yml"), ("acme/.", "x.yml"),
    ("a" * 40 + "/x", "x.yml"), ("acme/obt", "x.json"), ("acme/obt", "../x.yml"), ("acme/obt", "a/x.yml")])
def test_names_are_checked_before_any_request(http, repo, workflow):
    with pytest.raises(ValueError):
        gh.check_target(TOKEN, repo, workflow)
    assert not http.calls


def test_dispatch_asks_for_run_details_and_returns_the_run(github):
    route = github.dispatch(run_id=501)
    result = gh.dispatch(TOKEN, github.repo, github.workflow, "main", {"paths": "[]", "names": "[]", "request_id": "7"})
    assert result == gh.DispatchResult(run_id=501, html_url=f"https://github.com/{github.repo}/actions/runs/501")
    # Compare the parsed body: httpx 0.28 sends compact JSON, older versions add spaces
    assert json.loads(route.calls.last.request.read()) == {
        "ref": "main", "inputs": {"paths": "[]", "names": "[]", "request_id": "7"}, "return_run_details": True}


def test_a_204_dispatch_returns_none_for_the_matching_fallback(github):
    github.dispatch()
    assert gh.dispatch(TOKEN, github.repo, github.workflow, "main", {"request_id": "7"}) is None


@pytest.mark.parametrize("body", [{}, {"workflow_run_id": "501"}, {"workflow_run_id": True}, ["x"]])
def test_a_200_without_a_usable_run_id_also_falls_back(http, body):
    http.post(f"{gh.API}/repos/acme/obt/actions/workflows/qeos-run.yml/dispatches").mock(
        return_value=httpx.Response(200, json=body))
    assert gh.dispatch(TOKEN, "acme/obt", "qeos-run.yml", "main", {"request_id": "7"}) is None


def test_find_run_matches_the_exact_title(github):
    since = datetime(2026, 10, 7, 9, 59, tzinfo=timezone.utc)
    github.runs(github.run_body(2, 8), github.run_body(4, 7, title="QEOS #77"), github.run_body(3, 7))
    assert gh.find_run(TOKEN, github.repo, github.workflow, "QEOS #7", since)["id"] == 3


def test_find_run_accepts_several_titles(github):
    """A workflow copied before the QEOS rename still names its runs "QA Vision #<id>"."""
    since = datetime(2026, 10, 7, 9, 59, tzinfo=timezone.utc)
    github.runs(github.run_body(2, 8), github.run_body(3, 7, title="QA Vision #7"))
    assert gh.find_run(TOKEN, github.repo, github.workflow, ("QEOS #7", "QA Vision #7"), since)["id"] == 3


def test_find_run_sends_created_in_utc_z(github):
    route = github.runs()
    since = datetime(2026, 10, 7, 10, 59, tzinfo=timezone(timedelta(hours=1)))
    assert gh.find_run(TOKEN, github.repo, github.workflow, "QEOS #7", since) is None
    params = route.calls.last.request.url.params
    assert params["created"] == ">=2026-10-07T09:59:00Z"
    assert params["event"] == "workflow_dispatch"


def test_find_run_skips_older_runs_other_events_and_claimed_ids(github):
    since = datetime(2026, 10, 7, 9, 59, tzinfo=timezone.utc)
    github.runs(
        github.run_body(1, 7, created_at="2026-10-07T09:40:00Z"),   # an older manual dispatch with the same title
        {**github.run_body(2, 7), "event": "push"},
        github.run_body(3, 7),                                       # already another request's run
        github.run_body(5, 7, created_at="2026-10-07T09:59:20Z"),
        github.run_body(4, 7, created_at="2026-10-07T09:59:10Z"),   # ours: GitHub's clock is 50 s behind ours
    )
    run = gh.find_run(TOKEN, github.repo, github.workflow, "QEOS #7", since, exclude_ids=frozenset({3}))
    assert run["id"] == 4   # the oldest remaining match


def test_get_and_cancel_a_run(github):
    github.run(github.run_body(9, 7, status="in_progress"))
    cancel = github.cancel(9)
    assert gh.get_run(TOKEN, github.repo, 9)["status"] == "in_progress"
    gh.cancel_run(TOKEN, github.repo, 9)
    assert cancel.call_count == 1


def test_cancelling_a_finished_run_is_a_409_github_error(github):
    github.cancel(9, status=409)
    with pytest.raises(gh.GitHubError) as err:
        gh.cancel_run(TOKEN, github.repo, 9)
    assert err.value.status == 409


@pytest.mark.parametrize("repo, workflow", [("acme/obt\n", "x.yml"), ("acme/obt", "x.yml\n")])
def test_a_trailing_newline_in_a_name_is_rejected_before_any_request(http, repo, workflow):
    with pytest.raises(ValueError):
        gh.check_target(TOKEN, repo, workflow)
    assert not http.calls


def test_find_run_accepts_a_naive_since_as_utc(github):
    github.runs(github.run_body(3, 7))
    naive = datetime(2026, 10, 7, 9, 59)
    assert gh.find_run(TOKEN, github.repo, github.workflow, "QEOS #7", naive)["id"] == 3


@pytest.mark.parametrize("status", [301, 302, 307])
def test_every_redirect_is_an_error_even_without_a_location(http, status):
    http.get(f"{gh.API}/repos/acme/obt").mock(return_value=httpx.Response(status))
    with pytest.raises(gh.GitHubError) as err:
        gh.check_target(TOKEN, "acme/obt", "qeos-run.yml")
    assert err.value.status == status


def test_a_bare_429_is_a_rate_limit(http):
    http.get(f"{gh.API}/repos/acme/obt").mock(return_value=httpx.Response(429))
    with pytest.raises(gh.RateLimited) as err:
        gh.check_target(TOKEN, "acme/obt", "qeos-run.yml")
    assert err.value.retry_after >= 1


def test_a_run_without_an_event_is_not_matched(github):
    since = datetime(2026, 10, 7, 9, 59, tzinfo=timezone.utc)
    no_event = github.run_body(3, 7)
    del no_event["event"]
    github.runs(no_event)
    assert gh.find_run(TOKEN, github.repo, github.workflow, "QEOS #7", since) is None


def test_a_5xx_is_a_github_error_with_its_status(github):
    github.check(status=502)
    with pytest.raises(gh.GitHubError) as err:
        gh.check_target(TOKEN, github.repo, github.workflow)
    assert err.value.status == 502 and not isinstance(err.value, gh.RateLimited)


def test_a_retry_after_header_sets_the_wait(github):
    github.check(status=403, headers={"retry-after": "17"})
    with pytest.raises(gh.RateLimited) as err:
        gh.check_target(TOKEN, github.repo, github.workflow)
    assert err.value.retry_after == 17


def test_a_rate_limited_dispatch_raises_rate_limited(github):
    github.dispatch(status=429, headers={"retry-after": "30"})
    with pytest.raises(gh.RateLimited) as err:
        gh.dispatch(TOKEN, github.repo, github.workflow, "main", {"request_id": "7"})
    assert err.value.retry_after == 30


def test_the_403_message_names_the_owner_the_token_must_belong_to():
    message = gh.forbidden("example-org")
    assert message.startswith("token has no Actions access to this repository. ")
    assert 'resource owner is "example-org"' in message and "Actions: Read and write" in message
    assert "approve" in message and len(message) <= 500  # run_requests.error is String(500)


def _runs(http, workflow, *runs, status=200):
    return http.get(f"https://api.github.com/repos/acme/obt/actions/workflows/{workflow}/runs").mock(
        return_value=httpx.Response(status, json={"total_count": len(runs), "workflow_runs": list(runs)}))


def test_busy_run_returns_the_newest_unfinished_run_on_any_branch(http):
    route = _runs(http, "suite-flights.yml",
                  {"id": 3, "status": "completed", "created_at": "2026-10-19T21:30:00Z"},
                  {"id": 2, "status": "waiting", "created_at": "2026-10-19T21:00:00Z"},
                  {"id": 1, "status": "in_progress", "created_at": "2026-10-19T20:00:00Z"})
    assert gh.busy_run(TOKEN, "acme/obt", "suite-flights.yml")["id"] == 2
    params = route.calls.last.request.url.params
    assert "branch" not in params and params["per_page"] == "100"  # concurrency groups are not branch-scoped


@pytest.mark.parametrize("state", ["queued", "in_progress", "waiting", "pending", "requested"])
def test_busy_run_counts_every_unfinished_status(http, state):
    _runs(http, "suite-flights.yml", {"id": 7, "status": state, "created_at": "2026-10-19T21:00:00Z"})
    assert gh.busy_run(TOKEN, "acme/obt", "suite-flights.yml")["id"] == 7


def test_busy_run_is_none_when_every_run_finished(http):
    _runs(http, "suite-flights.yml", {"id": 3, "status": "completed"}, "not a run")
    assert gh.busy_run(TOKEN, "acme/obt", "suite-flights.yml") is None


def test_busy_run_failures_are_github_errors(http):
    _runs(http, "suite-flights.yml", status=500)
    with pytest.raises(gh.GitHubError) as err:
        gh.busy_run(TOKEN, "acme/obt", "suite-flights.yml")
    assert err.value.status == 500


def test_busy_run_checks_names_first(http):
    with pytest.raises(ValueError):
        gh.busy_run(TOKEN, "acme/obt", "../x.yml")
