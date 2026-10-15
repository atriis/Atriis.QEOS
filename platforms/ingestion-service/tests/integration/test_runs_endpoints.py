from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.ingestion.models import Run, RunResult

ALL_ROLES = ("owner", "admin", "member", "viewer", "billing_manager")


@pytest.fixture
def make_run(db, make_key):
    key_row, _ = make_key()

    def _make(project_id=1, branch="main", statuses=("passed", "failed"), minutes_ago=0, **fields):
        now = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        run = Run(project_id=project_id, api_key_id=key_row.id, request_hash="h",
                  branch=branch, started_at=now - timedelta(seconds=1), finished_at=now, duration_ms=1000,
                  total=len(statuses), passed=statuses.count("passed"), failed=statuses.count("failed"),
                  skipped=statuses.count("skipped"), errored=statuses.count("errored"), created_at=now, **{"ci_provider": "local", **fields})
        db.add(run)
        db.flush()
        for i, st in enumerate(statuses):
            db.add(RunResult(run_id=run.id, test_key=f"{i:064d}", name=f"t{i}", status=st, duration_ms=1))
        db.commit()
        db.refresh(run)
        return run

    return _make


@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_role_can_list_runs(client, auth, project_role, role):
    project_role(role)
    assert client.get("/api/v1/projects/1/runs", headers=auth()).status_code == 200


@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_role_can_get_a_run(client, auth, project_role, make_run, role):
    run = make_run()
    project_role(role)
    assert client.get(f"/api/v1/runs/{run.id}", headers=auth()).status_code == 200


def test_list_is_newest_first_this_project_only_with_counts(client, auth, project_role, make_run):
    older = make_run(minutes_ago=10)
    newer = make_run(minutes_ago=1)
    make_run(project_id=2)
    project_role("viewer")
    body = client.get("/api/v1/projects/1/runs", headers=auth()).json()
    assert [r["id"] for r in body] == [newer.id, older.id]
    assert (body[0]["total"], body[0]["passed"], body[0]["failed"]) == (2, 1, 1)
    assert "results" not in body[0]


def test_list_filters_by_branch(client, auth, project_role, make_run):
    make_run(branch="main")
    feature = make_run(branch="feature/x")
    project_role("viewer")
    body = client.get("/api/v1/projects/1/runs?branch=feature/x", headers=auth()).json()
    assert [r["id"] for r in body] == [feature.id]


def test_list_pagination(client, auth, project_role, make_run):
    runs = [make_run(minutes_ago=m) for m in (5, 4, 3, 2, 1)]
    project_role("viewer")
    page = client.get("/api/v1/projects/1/runs?limit=2&offset=1", headers=auth()).json()
    assert [r["id"] for r in page] == [runs[3].id, runs[2].id]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_list_rejects_bad_pagination(client, auth, project_role, query):
    project_role("viewer")
    assert client.get(f"/api/v1/projects/1/runs?{query}", headers=auth()).status_code == 422


def test_get_run_returns_results_in_order(client, auth, project_role, make_run):
    run = make_run(statuses=("passed", "failed", "skipped"))
    project_role("viewer")
    body = client.get(f"/api/v1/runs/{run.id}", headers=auth()).json()
    assert [r["name"] for r in body["results"]] == ["t0", "t1", "t2"]
    assert body["results"][1]["status"] == "failed"
    assert set(body["results"][0]) >= {"test_key", "suite", "class_name", "name", "status", "duration_ms",
                                       "message", "details", "truncated", "file"}


def test_get_run_filters_by_status(client, auth, project_role, make_run):
    run = make_run(statuses=("passed", "failed", "failed"))
    project_role("viewer")
    body = client.get(f"/api/v1/runs/{run.id}?status=failed", headers=auth()).json()
    assert [r["status"] for r in body["results"]] == ["failed", "failed"]
    assert body["total"] == 3  # the run's counts are unaffected by the filter


def test_get_run_invalid_status_filter_is_422(client, auth, project_role, make_run):
    run = make_run()
    project_role("viewer")
    assert client.get(f"/api/v1/runs/{run.id}?status=flaky", headers=auth()).status_code == 422


def test_missing_run_is_404_without_calling_project_service(client, auth, http):
    assert client.get("/api/v1/runs/999", headers=auth()).status_code == 404
    assert not http.calls


def test_run_of_a_project_the_caller_cannot_see_is_404(client, auth, project_role, make_run):
    run = make_run(project_id=3)
    project_role(project_id=3, status_code=404, body={"detail": "Project not found"})
    response = client.get(f"/api/v1/runs/{run.id}", headers=auth())
    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"


def test_project_service_down_is_503(client, auth, project_role, make_run):
    run = make_run()
    project_role(exc=httpx.ConnectError("refused"))
    assert client.get(f"/api/v1/runs/{run.id}", headers=auth()).status_code == 503
    assert client.get("/api/v1/projects/1/runs", headers=auth()).status_code == 503


def test_non_member_listing_is_404(client, auth, project_role):
    project_role(status_code=404, body={"detail": "Project not found"})
    assert client.get("/api/v1/projects/1/runs", headers=auth()).status_code == 404


def test_missing_token_is_401(client):
    assert client.get("/api/v1/projects/1/runs").status_code == 401
    assert client.get("/api/v1/runs/1").status_code == 401



def ids(client, auth, query):
    response = client.get(f"/api/v1/projects/1/runs?{query}", headers=auth())
    assert response.status_code == 200, response.text
    return {r["id"] for r in response.json()}


def test_list_filters_failing_and_passing(client, auth, project_role, make_run):
    red = make_run(statuses=("passed", "failed"))
    broken = make_run(statuses=("errored",))
    green = make_run(statuses=("passed", "skipped"))
    project_role("viewer")
    assert ids(client, auth, "status=failing") == {red.id, broken.id}
    assert ids(client, auth, "status=passing") == {green.id}


def test_list_filters_by_environment_and_ci(client, auth, project_role, make_run):
    staging = make_run(environment="staging", ci_provider="azure_pipelines")
    make_run(environment="prod", ci_provider="azure_pipelines")
    make_run(environment="staging", ci_provider="github_actions")
    project_role("viewer")
    assert ids(client, auth, "environment=staging&ci_provider=azure_pipelines") == {staging.id}


def test_list_filters_by_commit_prefix_any_case(client, auth, project_role, make_run):
    hit = make_run(commit_sha="abc1234def")
    make_run(commit_sha="ffff000")
    project_role("viewer")
    assert ids(client, auth, "commit=ABC12") == {hit.id}


@pytest.mark.parametrize("commit", ["abc", "xyz12", "a%25bc1"])
def test_list_rejects_bad_commit_prefix(client, auth, project_role, commit):
    project_role("viewer")
    assert client.get(f"/api/v1/projects/1/runs?commit={commit}", headers=auth()).status_code == 422


def test_list_filters_by_pull_request(client, auth, project_role, make_run):
    pr = make_run(pr_number=42)
    make_run(pr_number=7)
    project_role("viewer")
    assert ids(client, auth, "pr=42") == {pr.id}


def test_list_filters_by_author_substring_with_literal_wildcards(client, auth, project_role, make_run):
    ana = make_run(commit_author="Ana Silva")
    make_run(commit_author="Bruno")
    odd = make_run(commit_author="100%_bot")
    project_role("viewer")
    assert ids(client, auth, "author=silva") == {ana.id}
    # % and _ match themselves, not "anything"
    assert ids(client, auth, "author=%25_") == {odd.id}


def test_list_filters_by_started_date_range(client, auth, project_role, make_run):
    old = make_run(minutes_ago=3 * 24 * 60)
    recent = make_run(minutes_ago=5)
    project_role("viewer")
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert ids(client, auth, f"since={since.replace('+', '%2B')}") == {recent.id}
    until = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert ids(client, auth, f"until={until.replace('+', '%2B')}") == {old.id}


def test_list_filters_combine(client, auth, project_role, make_run):
    hit = make_run(branch="main", statuses=("failed",), environment="qa")
    make_run(branch="main", statuses=("passed",), environment="qa")
    make_run(branch="dev", statuses=("failed",), environment="qa")
    project_role("viewer")
    assert ids(client, auth, "branch=main&status=failing&environment=qa") == {hit.id}


@pytest.mark.parametrize("query", ["status=red", "ci_provider=travis", "pr=0", "since=yesterday"])
def test_list_rejects_bad_filters(client, auth, project_role, query):
    project_role("viewer")
    assert client.get(f"/api/v1/projects/1/runs?{query}", headers=auth()).status_code == 422


def add_failures(db, run, failures):
    for i, (status, message) in enumerate(failures):
        db.add(RunResult(run_id=run.id, test_key=f"f{i:063d}", suite="checkout", class_name="Cart",
                         name=f"fails {i}", status=status, duration_ms=1, message=message))
    db.commit()


def test_failure_groups_put_one_cause_together(client, auth, project_role, make_run, db):
    run = make_run(statuses=("passed",))
    add_failures(db, run, [
        ("failed", "TimeoutError: Timeout 30000ms waiting for locator('#pay')\n  at a.ts:1"),
        ("failed", "TimeoutError: Timeout 15000ms waiting for locator('#pay')\n  at b.ts:9"),
        ("errored", "TimeoutError: Timeout 5000ms waiting for locator('#pay')"),
        ("failed", "AssertionError: 41.99 != 42.00"),
        ("failed", None),
    ])
    project_role("viewer")
    body = client.get(f"/api/v1/runs/{run.id}/failure-groups", headers=auth()).json()
    assert body["total"] == 5
    groups = body["groups"]
    assert [g["count"] for g in groups] == [3, 1, 1]
    first = groups[0]
    assert first["headline"] == "TimeoutError: Timeout 30000ms waiting for locator('#pay')"
    assert (first["failed"], first["errored"]) == (2, 1)
    assert [t["name"] for t in first["tests"]] == ["fails 0", "fails 1", "fails 2"]
    assert {"test_key", "suite", "class_name", "status"} <= set(first["tests"][0])
    assert groups[-1]["headline"] is None and groups[-1]["signature"] == "none"


def test_failure_groups_of_a_green_run_are_empty(client, auth, project_role, make_run):
    run = make_run(statuses=("passed", "skipped"))
    project_role("viewer")
    assert client.get(f"/api/v1/runs/{run.id}/failure-groups", headers=auth()).json() == {"total": 0, "quarantined": 0, "blocking": 0, "groups": []}


def test_failure_groups_cap_listed_tests_but_count_all(client, auth, project_role, make_run, db):
    run = make_run(statuses=("passed",))
    add_failures(db, run, [("failed", "Boom") for _ in range(120)])
    project_role("viewer")
    group = client.get(f"/api/v1/runs/{run.id}/failure-groups", headers=auth()).json()["groups"][0]
    assert group["count"] == 120 and len(group["tests"]) == 100


def test_failure_groups_respect_access(client, auth, project_role, make_run):
    run = make_run(project_id=3)
    assert client.get("/api/v1/runs/999999/failure-groups", headers=auth()).status_code == 404
    project_role(project_id=3, status_code=404, body={"detail": "Project not found"})
    response = client.get(f"/api/v1/runs/{run.id}/failure-groups", headers=auth())
    assert response.status_code == 404 and response.json()["detail"] == "Run not found"


# --- branch_contains (partial branch search) ---

def _branch_ids(client, auth, query):
    body = client.get(f"/api/v1/projects/1/runs?{query}", headers=auth()).json()
    return {r["id"] for r in body}


def test_branch_contains_matches_prefix_and_substring(client, auth, project_role, make_run):
    feat = make_run(branch="feature/login-page")
    other = make_run(branch="bugfix/login-crash")
    make_run(branch="main")
    project_role("viewer")
    assert _branch_ids(client, auth, "branch_contains=feature") == {feat.id}
    assert _branch_ids(client, auth, "branch_contains=login") == {feat.id, other.id}


def test_branch_contains_is_case_insensitive(client, auth, project_role, make_run):
    run = make_run(branch="Feature/ABC-1")
    project_role("viewer")
    assert _branch_ids(client, auth, "branch_contains=feature/abc") == {run.id}


def test_branch_contains_escapes_wildcards(client, auth, project_role, make_run):
    pct = make_run(branch="release/100%")
    under = make_run(branch="hot_fix")
    make_run(branch="hotXfix")
    make_run(branch="release/1000")
    project_role("viewer")
    assert _branch_ids(client, auth, "branch_contains=100%25") == {pct.id}
    assert _branch_ids(client, auth, "branch_contains=hot_fix") == {under.id}
    assert _branch_ids(client, auth, "branch_contains=%25") == {pct.id}
    assert _branch_ids(client, auth, "branch_contains=%5C") == set()


def test_branch_contains_combines_with_exact_branch(client, auth, project_role, make_run):
    hit = make_run(branch="feature/x")
    make_run(branch="feature/y")
    project_role("viewer")
    assert _branch_ids(client, auth, "branch=feature/x&branch_contains=feature") == {hit.id}
    assert _branch_ids(client, auth, "branch=feature/x&branch_contains=nomatch") == set()


def test_branch_contains_is_project_isolated(client, auth, project_role, make_run):
    mine = make_run(branch="feature/a")
    make_run(project_id=2, branch="feature/b")
    project_role("viewer")
    assert _branch_ids(client, auth, "branch_contains=feature") == {mine.id}


@pytest.mark.parametrize("value", ["a" * 256, "a%00b"])
def test_branch_contains_rejects_bad_input(client, auth, project_role, value):
    project_role("viewer")
    assert client.get(f"/api/v1/projects/1/runs?branch_contains={value}", headers=auth()).status_code == 422


def test_branch_contains_accepts_255_chars(client, auth, project_role):
    project_role("viewer")
    assert client.get(f"/api/v1/projects/1/runs?branch_contains={'a' * 255}", headers=auth()).status_code == 200


# --- run summary ---

SUMMARY_KEYS = {"id", "project_id", "started_at", "finished_at", "branch", "commit_sha", "environment",
                "status", "counts", "ci_provider", "ci_run_url"}


@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_role_can_get_a_run_summary(client, auth, project_role, make_run, role):
    run = make_run()
    project_role(role)
    assert client.get(f"/api/v1/projects/1/runs/{run.id}/summary", headers=auth()).status_code == 200


def test_summary_shape_has_header_and_counts_only(client, auth, project_role, make_run):
    run = make_run(branch="main", statuses=("passed", "passed", "failed", "skipped", "errored"),
                   commit_sha="abc123def", environment="qa", ci_provider="github_actions", ci_run_url="https://ci/1")
    project_role("viewer")
    body = client.get(f"/api/v1/projects/1/runs/{run.id}/summary", headers=auth()).json()
    assert set(body) == SUMMARY_KEYS
    assert body["id"] == run.id and body["project_id"] == 1
    assert (body["branch"], body["commit_sha"], body["environment"]) == ("main", "abc123def", "qa")
    assert (body["ci_provider"], body["ci_run_url"]) == ("github_actions", "https://ci/1")
    assert body["counts"] == {"passed": 2, "failed": 1, "errored": 1, "skipped": 1}
    assert body["status"] == "failing"
    assert "results" not in body


def test_summary_status_passing(client, auth, project_role, make_run):
    run = make_run(statuses=("passed", "skipped"))
    project_role("viewer")
    assert client.get(f"/api/v1/projects/1/runs/{run.id}/summary", headers=auth()).json()["status"] == "passing"


def test_summary_of_unknown_run_is_404(client, auth, project_role):
    project_role("viewer")
    assert client.get("/api/v1/projects/1/runs/999/summary", headers=auth()).status_code == 404


def test_summary_of_another_projects_run_is_404(client, auth, project_role, make_run):
    other = make_run(project_id=2)
    project_role("viewer")
    assert client.get(f"/api/v1/projects/1/runs/{other.id}/summary", headers=auth()).status_code == 404


def test_summary_for_non_member_is_404(client, auth, project_role, make_run):
    run = make_run()
    project_role(status_code=404, body={"detail": "Project not found"})
    assert client.get(f"/api/v1/projects/1/runs/{run.id}/summary", headers=auth()).status_code == 404


# --- log values: runs with a value, a run's rows holding it (spec 2026-10-15 §3) ---------------------------------


def with_value(db, run, name, value, project_id=1, result_index=0):
    """Gives one of the run's results a captured log value under pattern `name` (created on first use)."""
    from src.ingestion.models import LogPattern, LogValue

    pattern = db.query(LogPattern).filter_by(project_id=project_id, name=name).first()
    if pattern is None:
        pattern = LogPattern(project_id=project_id, name=name, pattern="x")
        db.add(pattern)
        db.flush()
    result = db.query(RunResult).filter_by(run_id=run.id).order_by(RunResult.id).all()[result_index]
    db.add(LogValue(result_id=result.id, pattern_id=pattern.id, position=0, value=value))
    db.commit()
    return result


def test_list_filters_by_log_value(client, auth, project_role, make_run, db):
    hit = make_run(minutes_ago=2)
    other = make_run(minutes_ago=1)
    with_value(db, hit, "trip_id", "3960562")
    with_value(db, other, "trip_id", "3960563")
    project_role("viewer")
    body = client.get("/api/v1/projects/1/runs?value=3960562", headers=auth()).json()
    assert [r["id"] for r in body] == [hit.id]
    assert client.get("/api/v1/projects/1/runs?value=396056", headers=auth()).json() == []  # exact, not a prefix


def test_list_filters_by_log_value_and_pattern(client, auth, project_role, make_run, db):
    trip = make_run(minutes_ago=2)
    route = make_run(minutes_ago=1)
    with_value(db, trip, "trip_id", "42")
    with_value(db, route, "route_key", "42")
    project_role("viewer")
    both = client.get("/api/v1/projects/1/runs?value=42", headers=auth()).json()
    assert {r["id"] for r in both} == {trip.id, route.id}
    only = client.get("/api/v1/projects/1/runs?value=42&pattern=trip_id", headers=auth()).json()
    assert [r["id"] for r in only] == [trip.id]


def test_pattern_without_value_is_422(client, auth, project_role, make_run):
    run = make_run()
    project_role("viewer")
    assert client.get("/api/v1/projects/1/runs?pattern=trip_id", headers=auth()).status_code == 422
    assert client.get(f"/api/v1/runs/{run.id}?pattern=trip_id", headers=auth()).status_code == 422


@pytest.mark.parametrize("value", ["", "a" * 201, "nul%00here"])
def test_an_impossible_value_is_422(client, auth, project_role, value):
    project_role("viewer")
    assert client.get(f"/api/v1/projects/1/runs?value={value}", headers=auth()).status_code == 422


def test_an_unknown_pattern_matches_nothing(client, auth, project_role, make_run, db):
    run = make_run()
    with_value(db, run, "trip_id", "1")
    project_role("viewer")
    assert client.get("/api/v1/projects/1/runs?value=1&pattern=nothing", headers=auth()).json() == []


def test_another_projects_value_never_matches(client, auth, project_role, make_run, db):
    theirs = make_run(project_id=2)
    with_value(db, theirs, "trip_id", "3960562", project_id=2)
    mine = make_run()
    project_role("viewer")
    assert client.get("/api/v1/projects/1/runs?value=3960562", headers=auth()).json() == []
    assert [r["id"] for r in client.get("/api/v1/projects/1/runs", headers=auth()).json()] == [mine.id]


def test_value_combines_with_the_other_filters(client, auth, project_role, make_run, db):
    green = make_run(statuses=("passed",), branch="main", minutes_ago=2)
    red = make_run(statuses=("failed",), branch="main", minutes_ago=1)
    with_value(db, green, "trip_id", "7")
    with_value(db, red, "trip_id", "7")
    project_role("viewer")
    body = client.get("/api/v1/projects/1/runs?value=7&status=failing&branch=main", headers=auth()).json()
    assert [r["id"] for r in body] == [red.id]


def test_get_run_scopes_its_rows_to_the_value_and_keeps_its_counts(client, auth, project_role, make_run, db):
    run = make_run(statuses=("passed", "failed", "passed"))
    holder = with_value(db, run, "trip_id", "3960562", result_index=1)
    project_role("viewer")
    body = client.get(f"/api/v1/runs/{run.id}?value=3960562", headers=auth()).json()
    assert [r["id"] for r in body["results"]] == [holder.id]
    assert body["total"] == 3 and body["failed"] == 1  # the run's counts describe the run
    assert client.get(f"/api/v1/runs/{run.id}?value=3960562&pattern=route_key", headers=auth()).json()["results"] == []
