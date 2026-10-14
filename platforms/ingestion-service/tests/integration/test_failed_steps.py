"""Failed steps across test cases (spec 2026-10-14 §3.2-§3.3)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from src.ingestion.analytics.failed_steps import step_key
from src.ingestion.api.deps import READ_ROLES
from src.ingestion.models import RunResult
from tests.conftest import report_key

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
SEARCH = "features/step_definitions/search.js:12"
LOGIN = "features/step_definitions/login.js:3"


def url(run_id):
    return f"/api/v1/projects/1/runs/{run_id}/failed-steps"


@pytest.fixture
def step_run(seed_run, db):
    """step_run(started_at, {name: status | (status, step_text, definition, message)}, **seed_run fields): a run whose
    failing tests carry a failed step; with a definition the pattern is "When I search {…}"."""
    def _seed(started_at, tests, **fields):
        run = seed_run(started_at, results=tuple(
            (name, spec if isinstance(spec, str) else spec[0], 5) for name, spec in tests.items()), **fields)
        for row in db.query(RunResult).filter_by(run_id=run.id):
            spec = tests[row.name]
            if isinstance(spec, tuple):
                _, text, definition, message = spec
                row.failed_step_text, row.failed_step_definition, row.message = text, definition, message
                row.failed_step_pattern = "When I search {…}" if definition == SEARCH else None
        db.commit()
        return run

    return _seed


def get(client, auth, run):
    response = client.get(url(run.id), headers=auth())
    assert response.status_code == 200, response.text
    return response.json()["steps"]


def failing(text, definition=SEARCH, message="boom"):
    return ("failed", text, definition, message)


def test_one_step_across_cases_with_its_errors(client, auth, project_role, step_run):
    project_role("viewer")
    run = step_run(T0, {
        "lisbon": failing("When I search Lisb0n", message="Invalid city 'Lisb0n'"),
        "porto": failing("When I search P0rto", message="Invalid city 'P0rto'\n  at search.js:40"),
        "faro": ("errored", "When I search Faro", SEARCH, "Timeout of 3000ms exceeded"),
        "login": failing("Given I log in", definition=LOGIN),
        "ok": "passed",
    })
    search, login = get(client, auth, run)
    assert search["key"] == step_key(SEARCH, "x")[0] and search["by"] == "definition"
    assert search["definition"] == SEARCH and search["pattern"] == "When I search {…}" and search["cases"] == 3
    invalid, timeout = search["errors"]
    assert invalid == {"shape": "Invalid city '…'", "example": "Invalid city 'Lisb0n'", "cases": 2, "tests": [
        {"test_key": report_key("lisbon"), "name": "lisbon", "text": "When I search Lisb0n"},
        {"test_key": report_key("porto"), "name": "porto", "text": "When I search P0rto"}]}
    assert timeout["shape"] == "Timeout of …ms exceeded" and timeout["cases"] == 1 and "more" not in timeout
    assert search["since"]["run_id"] == run.id and search["since"]["runs"] == 1 and search["since"]["capped"] is False
    assert search["since"]["started_at"].startswith("2026-10-01T00:00:00")
    assert "last_passed" not in search
    assert login["cases"] == 1 and login["pattern"] == "Given I log in"


def test_without_a_definition_steps_group_by_text(client, auth, project_role, step_run):
    project_role("viewer")
    run = step_run(T0, {
        "a": failing("When I search Lisbon", definition=None),
        "b": failing("when  i search lisbon", definition=None),
        "c": failing("When I search Porto", definition=None),
    })
    lisbon, porto = get(client, auth, run)
    assert lisbon["by"] == "text" and lisbon["cases"] == 2 and "definition" not in lisbon
    assert lisbon["pattern"] in ("When I search Lisbon", "when  i search lisbon")
    assert porto["cases"] == 1 and porto["pattern"] == "When I search Porto"


def test_steps_sort_by_cases_then_pattern(client, auth, project_role, step_run):
    project_role("viewer")
    run = step_run(T0, {"a": failing("Then b", definition=None), "b": failing("Given a", definition=None),
                        "c": failing("When I search x"), "d": failing("When I search y")})
    assert [s["pattern"] for s in get(client, auth, run)] == ["When I search {…}", "Given a", "Then b"]


def test_a_re_run_that_passed_is_not_a_failed_step(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0, results=(("search", "failed", 5), ("search", "passed", 5)))
    first = db.query(RunResult).filter_by(run_id=run.id, status="failed").one()
    first.failed_step_text, first.failed_step_definition = "When I search Lisbon", SEARCH
    db.commit()
    assert get(client, auth, run) == []


def test_at_most_50_tests_per_error_with_the_rest_counted(client, auth, project_role, step_run):
    project_role("viewer")
    run = step_run(T0, {f"t{i:02d}": failing(f"When I search c{i}") for i in range(55)})
    (step,) = get(client, auth, run)
    (error,) = step["errors"]
    assert step["cases"] == 55 and error["cases"] == 55 and len(error["tests"]) == 50 and error["more"] == 5


def test_a_run_without_failed_steps_answers_an_empty_list(client, auth, project_role, seed_run):
    project_role("viewer")
    run = seed_run(T0, results=(("ok", "passed", 5), ("junit", "failed", 5)))  # junit: no step, details is None
    assert get(client, auth, run) == []


def test_since_walks_back_while_the_step_keeps_failing_and_names_the_run_that_passed(
        client, auth, project_role, step_run):
    project_role("viewer")
    passed = step_run(T0, {"lisbon": "passed"})
    first = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    step_run(T0 + timedelta(hours=2), {"other": "passed"})  # without the step's tests: passed over
    step_run(T0 + timedelta(hours=3), {"lisbon": "skipped"})  # did not run: passed over (R3)
    run = step_run(T0 + timedelta(hours=4), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == first.id and step["since"]["runs"] == 2 and step["since"]["capped"] is False
    assert step["last_passed"]["run_id"] == passed.id
    assert step["last_passed"]["started_at"].startswith("2026-10-01T00:00:00")


def test_a_failure_at_another_step_stops_the_streak_without_last_passed(client, auth, project_role, step_run):
    project_role("viewer")
    step_run(T0, {"lisbon": failing("Given I log in", definition=LOGIN)})
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == run.id and step["since"]["runs"] == 1 and "last_passed" not in step


def test_the_streak_continues_while_one_of_the_tests_failed_at_the_step(client, auth, project_role, step_run):
    project_role("viewer")
    first = step_run(T0, {"lisbon": "passed", "porto": failing("When I search Porto")})
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon"),
                                             "porto": failing("When I search Porto")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == first.id and step["since"]["runs"] == 2


def test_rows_from_before_collector_0_8_count_by_their_text(client, auth, project_role, step_run):
    project_role("viewer")
    old = step_run(T0, {"lisbon": failing("When I search Lisbon", definition=None)})
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["by"] == "definition" and step["since"]["run_id"] == old.id and step["since"]["runs"] == 2


def test_impact_subset_runs_count_like_any_run(client, auth, project_role, step_run):
    project_role("viewer")
    subset = step_run(T0, {"lisbon": failing("When I search Lisbon")}, scope="impact-subset")
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == subset.id


def test_only_runs_of_the_same_branch_join_the_streak(client, auth, project_role, step_run):
    project_role("viewer")
    step_run(T0, {"lisbon": failing("When I search Lisbon")}, branch="feature/x")
    step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")}, branch="main")
    run = step_run(T0 + timedelta(hours=2), {"lisbon": failing("When I search Lisbon")}, branch="main")
    (step,) = get(client, auth, run)
    assert step["since"]["runs"] == 2 and step["since"]["run_id"] != run.id


def test_a_run_without_a_branch_walks_every_branch(client, auth, project_role, step_run):
    project_role("viewer")
    step_run(T0, {"lisbon": failing("When I search Lisbon")}, branch="feature/x")
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")}, branch=None)
    (step,) = get(client, auth, run)
    assert step["since"]["runs"] == 2


def test_a_run_on_another_branch_never_caps_the_streak(client, auth, project_role, step_run):
    project_role("viewer")
    step_run(T0 - timedelta(days=100), {"lisbon": failing("When I search Lisbon")}, branch="feature/x")
    step_run(T0 - timedelta(days=1), {"lisbon": failing("When I search Lisbon")}, branch="feature/x")
    run = step_run(T0, {"lisbon": failing("When I search Lisbon")}, branch="main")
    (step,) = get(client, auth, run)
    assert step["since"] == {**step["since"], "run_id": run.id, "runs": 1, "capped": False}


def test_many_runs_on_another_branch_never_cap_the_streak(client, auth, project_role, step_run):
    project_role("viewer")
    for i in range(50):
        step_run(T0 + timedelta(minutes=i), {"lisbon": failing("When I search Lisbon")}, branch="feature/x")
    first = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")}, branch="main")
    run = step_run(T0 + timedelta(hours=2), {"lisbon": failing("When I search Lisbon")}, branch="main")
    (step,) = get(client, auth, run)
    assert step["since"] == {**step["since"], "run_id": first.id, "runs": 2, "capped": False}


def test_an_earlier_re_run_that_passed_stops_the_streak_as_last_passed(
        client, auth, project_role, seed_run, step_run, db):
    project_role("viewer")
    step_run(T0, {"lisbon": failing("When I search Lisbon")})
    retried = seed_run(T0 + timedelta(hours=1), results=(("lisbon", "failed", 5), ("lisbon", "passed", 5)))
    first = db.query(RunResult).filter_by(run_id=retried.id, status="failed").one()
    first.failed_step_text, first.failed_step_definition = "When I search Lisbon", SEARCH
    db.commit()
    run = step_run(T0 + timedelta(hours=2), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == run.id and step["since"]["runs"] == 1
    assert step["last_passed"]["run_id"] == retried.id


def test_an_earlier_run_whose_last_row_was_skipped_is_passed_over(client, auth, project_role, seed_run, step_run, db):
    project_role("viewer")
    old = step_run(T0, {"lisbon": failing("When I search Lisbon")})
    seed_run(T0 + timedelta(hours=1), results=(("lisbon", "passed", 5), ("lisbon", "skipped", 5)))  # last: skipped
    run = step_run(T0 + timedelta(hours=2), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == old.id and step["since"]["runs"] == 2 and "last_passed" not in step


def test_several_steps_cost_a_bounded_number_of_queries(client, auth, project_role, step_run, db):
    project_role("viewer")
    tests = {f"t{i}": failing(f"When I do thing {i}", definition=None) for i in range(5)}
    for hours in range(3):
        step_run(T0 + timedelta(hours=hours), tests)
    step_run(T0 - timedelta(days=100), tests)  # before the window: the "ran before" check runs too
    run = step_run(T0 + timedelta(hours=3), tests)
    statements, engine = [], db.get_bind()  # the session's own engine: the one the endpoint queries through

    def count(*_):
        statements.append(1)

    event.listen(engine, "before_cursor_execute", count)
    try:
        steps = get(client, auth, run)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(steps) == 5 and all(s["since"]["runs"] == 4 and s["since"]["capped"] for s in steps)
    assert len(statements) <= 6


def test_another_projects_runs_never_join_the_streak(client, auth, project_role, step_run):
    project_role("viewer")
    step_run(T0, {"lisbon": failing("When I search Lisbon")}, project_id=2)
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["runs"] == 1 and step["since"]["capped"] is False


def test_the_walk_stops_at_50_runs(client, auth, project_role, step_run):
    project_role("viewer")
    runs = [step_run(T0 + timedelta(minutes=i), {"lisbon": failing("When I search Lisbon")}) for i in range(51)]
    (step,) = get(client, auth, runs[-1])
    assert step["since"] == {**step["since"], "runs": 50, "capped": True, "run_id": runs[1].id}
    assert "last_passed" not in step


def test_exactly_50_runs_with_nothing_before_is_not_capped(client, auth, project_role, step_run):
    project_role("viewer")
    runs = [step_run(T0 + timedelta(minutes=i), {"lisbon": failing("When I search Lisbon")}) for i in range(50)]
    (step,) = get(client, auth, runs[-1])
    assert step["since"]["runs"] == 50 and step["since"]["capped"] is False and step["since"]["run_id"] == runs[0].id


def test_the_walk_stops_at_90_days(client, auth, project_role, step_run):
    project_role("viewer")
    step_run(T0 - timedelta(days=100), {"lisbon": failing("When I search Lisbon")})
    inside = step_run(T0 - timedelta(days=80), {"lisbon": failing("When I search Lisbon")})
    run = step_run(T0, {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == inside.id and step["since"]["runs"] == 2 and step["since"]["capped"] is True


def test_a_run_of_another_project_or_unknown_is_404(client, auth, project_role, step_run):
    project_role("viewer")
    other = step_run(T0, {"lisbon": failing("When I search Lisbon")}, project_id=2)
    assert client.get(url(other.id), headers=auth()).status_code == 404
    assert client.get(url(999999), headers=auth()).status_code == 404


@pytest.mark.parametrize("role", READ_ROLES)
def test_every_project_role_reads_it(client, auth, project_role, step_run, role):
    project_role(role)
    run = step_run(T0, {"lisbon": failing("When I search Lisbon")})
    assert client.get(url(run.id), headers=auth()).status_code == 200


def test_no_project_access_is_404(client, auth, project_role, step_run):
    run = step_run(T0, {"lisbon": failing("When I search Lisbon")})
    project_role(status_code=404)
    assert client.get(url(run.id), headers=auth()).status_code == 404
