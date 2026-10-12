"""The three test impact endpoints (spec 2026-10-12 §3.5, §9; plan Rulings 17, 18, 19): states, roles, limits, other
projects."""
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from src.ingestion.analytics import impact_score
from src.ingestion.api.deps import READ_ROLES
from src.ingestion.api.v1.endpoints import analytics
from src.ingestion.jobs import impact_rollup
from src.ingestion.models.impact import RunImpact
from src.ingestion.service import impact_read, impact_service
from src.ingestion.service.ingest_service import test_key as key_of

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
IMPACT = "/api/v1/projects/1/analytics/impact"
ACCURACY = "/api/v1/projects/1/analytics/impact-accuracy"
SERVICE = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(analytics, "_now", lambda: NOW)


@pytest.fixture
def viewer(project_role):
    project_role("viewer", project_id=1)


def run_url(run_id, project_id=1):
    return f"/api/v1/projects/{project_id}/runs/{run_id}/impact"


def ref(name):
    return {"test_key": key_of("s", "C", name), "suite": "s", "class_name": "C", "name": name}


def suggested(*names):
    return tuple({**ref(n), "kind": "no_history", "evidence": None} for n in names)


def store(db, run, *, caught=(), missed=(), replayed=False, evaluated=True, tests=()):
    db.add(RunImpact(
        run_id=run.id, model_version="stats-v1", replayed=replayed, scored_at=NOW,
        suggested={"state": "ok", "history_runs": 25, "needed_runs": 20, "statistical_total": 0, "tests": list(tests)},
        caught=[ref(n) for n in caught] if evaluated else None, missed=[ref(n) for n in missed] if evaluated else None,
        evaluated_at=NOW if evaluated else None,
    ))
    db.commit()


def test_the_schemas_raise_no_pydantic_warning():
    """`model_version` is in pydantic's protected `model_` namespace: the schema opts out, and the JSON name stays."""
    done = subprocess.run([sys.executable, "-W", "error", "-c", "import src.ingestion.schemas.impact"], cwd=SERVICE,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


# ---- GET /projects/{id}/runs/{run_id}/impact ----

def test_a_run_without_changed_files_has_no_change_data(client, auth, viewer, seed_run):
    run = seed_run(NOW - timedelta(hours=1))
    response = client.get(run_url(run.id), headers=auth())
    assert response.status_code == 200
    assert response.json() == {"run_id": run.id, "state": "no_change_data", "changed_paths": [], "replayed": False,
                               "scored_at": None, "suggestion": None, "outcome": None}


def test_changed_files_without_a_stored_suggestion_are_not_scored(client, auth, viewer, seed_change_run):
    run = seed_change_run(NOW - timedelta(hours=1))
    body = client.get(run_url(run.id), headers=auth()).json()
    assert (body["state"], body["changed_paths"], body["suggestion"]) == ("not_scored", ["src/app.py"], None)


def test_the_stored_suggestion_and_its_outcome(client, auth, viewer, seed_change_run, db):
    run = seed_change_run(NOW - timedelta(hours=1), paths=("src/pay/api.py",))
    store(db, run, missed=("pays",), tests=({**ref("old"), "kind": "failing_on_branch", "evidence": None},))
    body = client.get(run_url(run.id), headers=auth()).json()
    assert (body["state"], body["changed_paths"], body["replayed"]) == ("ok", ["src/pay/api.py"], False)
    assert body["suggestion"]["model_version"] == "stats-v1" and body["suggestion"]["history_runs"] == 25
    assert body["suggestion"]["tests"] == [{**ref("old"), "kind": "failing_on_branch", "evidence": None}]
    assert body["outcome"]["caught"] == [] and body["outcome"]["missed"] == [ref("pays")]


def test_a_suggestion_waiting_for_its_outcome(client, auth, viewer, seed_change_run, db):
    run = seed_change_run(NOW - timedelta(hours=1))
    store(db, run, evaluated=False)
    body = client.get(run_url(run.id), headers=auth()).json()
    assert body["state"] == "ok" and body["outcome"] is None


def test_a_run_of_another_project_is_not_found(client, auth, viewer, seed_change_run):
    other = seed_change_run(NOW - timedelta(hours=1), project_id=2)
    assert client.get(run_url(other.id), headers=auth()).status_code == 404
    assert client.get(run_url(999_999), headers=auth()).status_code == 404


@pytest.mark.parametrize("role", READ_ROLES)
def test_every_reading_role_reads_a_runs_impact(client, auth, project_role, seed_change_run, role):
    project_role(role, project_id=1)
    run = seed_change_run(NOW - timedelta(hours=1))
    assert client.get(run_url(run.id), headers=auth()).status_code == 200


def test_access_failures(client, auth, project_role, seed_change_run):
    run = seed_change_run(NOW - timedelta(hours=1))
    project_role(status_code=404, body={"detail": "Project not found"}, project_id=1)
    assert client.get(run_url(run.id), headers=auth()).status_code == 404
    project_role(exc=httpx.ConnectError("refused"), project_id=1)
    assert client.get(run_url(run.id), headers=auth()).status_code == 503
    assert client.get(run_url(run.id)).status_code == 401


# ---- POST /projects/{id}/analytics/impact ----

def test_scoring_a_change_suggests_from_the_statistics(client, auth, viewer, db, seed_impact_history, monkeypatch):
    monkeypatch.setattr(impact_score, "MIN_HISTORY_RUNS", 10)
    seed_impact_history(start=NOW - timedelta(days=15))
    impact_rollup.run_pass(db, now=lambda: NOW)
    response = client.post(IMPACT, json={"changed_paths": ["src/pay/new.py"], "branch": None}, headers=auth())
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["state"], body["model_version"], body["history_runs"]) == ("ok", "stats-v1", 15)
    assert [(t["name"], t["kind"]) for t in body["tests"]] == [("pays", "statistical")]
    assert body["tests"][0]["evidence"]["path_unit"] == "src/pay/"


def test_the_branch_adds_its_failing_tests(client, auth, viewer, seed_run):
    seed_run(NOW - timedelta(hours=1), results=(("pays", "failed", 5),), branch="feature/x")
    body = client.post(IMPACT, json={"changed_paths": ["src/a.py"], "branch": "feature/x"}, headers=auth()).json()
    assert body["state"] == "not_enough_history"
    assert [(t["name"], t["kind"]) for t in body["tests"]] == [("pays", "failing_on_branch")]


def test_a_change_of_only_ignored_files_answers_with_labels_only(client, auth, viewer):
    response = client.post(IMPACT, json={"changed_paths": ["poetry.lock", "/"]}, headers=auth())
    assert response.status_code == 200 and response.json()["tests"] == []


def test_a_project_the_rollup_has_not_visited_answers_without_statistics(client, auth, viewer, seed_change_run):
    for day in range(1, 21):
        seed_change_run(NOW - timedelta(days=day))
    body = client.post(IMPACT, json={"changed_paths": ["src/app.py"]}, headers=auth()).json()
    assert (body["state"], body["history_runs"], body["tests"]) == ("ok", 20, [])


@pytest.fixture
def rollbacks(db, monkeypatch):
    """Counts db.rollback calls: the scoring endpoint ends its read-only transaction (and its SET LOCAL) itself."""
    calls = []
    real = db.rollback
    monkeypatch.setattr(db, "rollback", lambda: (calls.append(1), real())[1])
    return calls


def test_scoring_ends_its_transaction(client, auth, viewer, rollbacks):
    assert client.post(IMPACT, json={"changed_paths": ["src/a.py"]}, headers=auth()).status_code == 200
    assert rollbacks


def test_scoring_starts_its_budget_before_scoring(client, auth, viewer, monkeypatch):
    """The same 2 s total budget as at upload (PostgreSQL only; limit_scoring_time is a no-op on SQLite), set first."""
    calls = []
    monkeypatch.setattr(impact_service, "limit_scoring_time", lambda db, remaining=None: calls.append("limit"))
    real = impact_service.score_change
    monkeypatch.setattr(impact_service, "score_change", lambda *a, **k: (calls.append("score"), real(*a, **k))[1])
    assert client.post(IMPACT, json={"changed_paths": ["src/a.py"]}, headers=auth()).status_code == 200
    assert calls[0] == "limit" and "score" in calls


def test_limit_scoring_time_caps_the_timeout_at_what_is_left_but_at_least_1ms():
    sent = []

    class Session:
        def get_bind(self):
            return type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()

        def execute(self, statement, *args):
            sent.append(str(statement))

    impact_service.limit_scoring_time(Session(), 0.75)
    impact_service.limit_scoring_time(Session(), 0.0001)
    assert sent == ["SET LOCAL statement_timeout = '750ms'", "SET LOCAL statement_timeout = '1ms'"]


def test_a_budget_used_up_between_statements_answers_503(client, auth, viewer, monkeypatch, rollbacks):
    """One total budget: each statement is fast, but the scoring as a whole is over 2 s."""
    ticks = iter([0.0, 0.0, 0.5] + [3.0] * 100)
    monkeypatch.setattr(impact_service, "monotonic", lambda: next(ticks))
    response = client.post(IMPACT, json={"changed_paths": ["src/a.py"]}, headers=auth())
    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "impact_timeout", "message": impact_service.SCORING_TIMEOUT_MESSAGE}
    assert rollbacks


def test_a_scoring_timeout_answers_503_with_a_message(client, auth, viewer, monkeypatch, rollbacks):
    class Canceled(Exception):
        sqlstate = "57014"

    def slow(*args, **kwargs):
        raise OperationalError("SELECT ...", {}, Canceled())

    monkeypatch.setattr(impact_service, "score_change", slow)
    response = client.post(IMPACT, json={"changed_paths": ["src/a.py"]}, headers=auth())
    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "impact_timeout", "message": impact_service.SCORING_TIMEOUT_MESSAGE}
    assert rollbacks


def test_another_database_error_is_not_turned_into_a_timeout(client, auth, viewer, monkeypatch):
    def broken(*args, **kwargs):
        raise OperationalError("SELECT ...", {}, Exception("connection lost"))

    monkeypatch.setattr(impact_service, "score_change", broken)
    with pytest.raises(OperationalError):
        client.post(IMPACT, json={"changed_paths": ["src/a.py"]}, headers=auth())


@pytest.mark.parametrize("body", [
    {"changed_paths": []},
    {"changed_paths": ["a"] * 5001},
    {"changed_paths": [""]},
    {"changed_paths": ["x" * 1001]},
    {"changed_paths": ["src/\u0000a.py"]},
    {"changed_paths": ["src/a.py"], "branch": "b" * 256},
    {"changed_paths": ["src/a.py"], "extra": 1},
    {"branch": "main"},
])
def test_input_limits(client, auth, viewer, body):
    assert client.post(IMPACT, json=body, headers=auth()).status_code == 422


def test_the_limits_themselves_pass(client, auth, viewer):
    body = {"changed_paths": [f"src/m{i}/f.py" for i in range(4999)] + ["x" * 1000], "branch": "b" * 255}
    assert client.post(IMPACT, json=body, headers=auth()).status_code == 200


# ---- GET /projects/{id}/analytics/impact-accuracy ----

def test_accuracy_counts_caught_and_missed_new_failures_in_the_window(client, auth, viewer, db, seed_change_run):
    a = seed_change_run(NOW - timedelta(days=2))
    store(db, a, caught=("pays", "cart"), missed=("ship",), tests=suggested("pays", "cart", "x"))
    store(db, seed_change_run(NOW - timedelta(days=5)), caught=("pays",), tests=suggested("pays"))
    c = seed_change_run(NOW - timedelta(days=10))
    store(db, c, missed=("old",), tests=suggested("a", "b", "c", "d", "e"))
    store(db, seed_change_run(NOW - timedelta(days=1)), evaluated=False, tests=suggested("p"))  # pending: not counted
    store(db, seed_change_run(NOW - timedelta(days=1), project_id=2), caught=("x",), missed=("elsewhere",),
          tests=suggested("x"))  # another project: neither counted nor listed
    week = client.get(ACCURACY, params={"days": 7}, headers=auth()).json()
    assert (week["days"], week["caught"], week["missed"], week["rate"], week["includes_replayed"]) == (7, 3, 1, 0.75, False)
    assert week["live"] == {"runs": 2, "caught": 3, "missed": 1, "suggested": 4}
    assert week["replayed"] == {"runs": 0, "caught": 0, "missed": 0, "suggested": 0}
    assert week["avg_suggested"] == 2.0  # beside the rate: suggesting everything would show here
    assert [(m["name"], m["run_id"], m["replayed"]) for m in week["misses"]] == [("ship", a.id, False)]
    assert week["misses_total"] == 1
    month = client.get(ACCURACY, params={"days": 30}, headers=auth()).json()
    assert (month["caught"], month["missed"], month["avg_suggested"]) == (3, 2, 3.0)
    assert [m["name"] for m in month["misses"]] == ["ship", "old"]  # newest run first


def test_replayed_and_live_parts_are_reported_apart(client, auth, viewer, db, seed_change_run):
    store(db, seed_change_run(NOW - timedelta(days=1)), caught=("pays",), tests=suggested("pays"))
    store(db, seed_change_run(NOW - timedelta(days=3)), missed=("cart",), replayed=True, tests=suggested("x", "y"))
    body = client.get(ACCURACY, headers=auth()).json()
    assert body["days"] == 30 and body["includes_replayed"] is True
    assert body["live"] == {"runs": 1, "caught": 1, "missed": 0, "suggested": 1}
    assert body["replayed"] == {"runs": 1, "caught": 0, "missed": 1, "suggested": 2}
    assert body["avg_suggested"] == 1.5
    assert body["misses"][0]["replayed"] is True


def test_no_new_failures_has_no_rate(client, auth, viewer, db, seed_change_run):
    store(db, seed_change_run(NOW - timedelta(days=1)))
    body = client.get(ACCURACY, headers=auth()).json()
    assert (body["rate"], body["caught"], body["missed"], body["live"]["runs"]) == (None, 0, 0, 1)
    assert body["avg_suggested"] == 0.0


def test_no_scored_runs_has_no_rate_and_no_average(client, auth, viewer):
    body = client.get(ACCURACY, headers=auth()).json()
    assert (body["rate"], body["avg_suggested"], body["misses"], body["misses_total"]) == (None, None, [], 0)


def test_at_most_50_misses_are_listed(client, auth, viewer, db, seed_change_run):
    for hours in range(1, 4):
        store(db, seed_change_run(NOW - timedelta(hours=hours)), missed=tuple(f"m{hours}-{i:02}" for i in range(20)))
    body = client.get(ACCURACY, headers=auth()).json()
    assert (len(body["misses"]), body["misses_total"], body["missed"]) == (impact_read.MAX_MISSES, 60, 60)
    assert impact_read.MAX_MISSES == 50
    assert body["misses"][0]["name"] == "m1-00" and body["misses"][-1]["name"] == "m3-09"


@pytest.mark.parametrize("days", [1, 10, 31, 90])
def test_days_other_than_7_14_30_are_refused(client, auth, viewer, days):
    assert client.get(ACCURACY, params={"days": days}, headers=auth()).status_code == 422


def test_the_days_check_comes_after_the_role_check(client, auth, project_role):
    project_role(status_code=404, body={"detail": "Project not found"}, project_id=1)
    assert client.get(ACCURACY, params={"days": 10}, headers=auth()).status_code == 404


@pytest.mark.parametrize("role", READ_ROLES)
def test_every_reading_role_scores_and_reads_accuracy(client, auth, project_role, role):
    project_role(role, project_id=1)
    assert client.post(IMPACT, json={"changed_paths": ["src/a.py"]}, headers=auth()).status_code == 200
    assert client.get(ACCURACY, headers=auth()).status_code == 200


def test_scoring_and_accuracy_need_a_member(client, auth, project_role):
    project_role(status_code=404, body={"detail": "Project not found"}, project_id=1)
    assert client.post(IMPACT, json={"changed_paths": ["src/a.py"]}, headers=auth()).status_code == 404
    assert client.get(ACCURACY, headers=auth()).status_code == 404
    assert client.post(IMPACT, json={"changed_paths": ["src/a.py"]}).status_code == 401
    assert client.get(ACCURACY).status_code == 401
