"""Runs of only the suggested tests (scope impact-subset) stay out of the impact statistics, the outcome evaluation and
the accuracy figure; their suggestion is stored and answered as not evaluated (spec 2026-10-13 §3.1; plan Rulings 3,
4)."""
from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.api.v1.endpoints import analytics
from src.ingestion.jobs import impact_rollup
from src.ingestion.models.impact import ImpactPair, ImpactTestBase, RunImpact
from src.ingestion.models.run import FULL_SCOPE, SUBSET_SCOPE as SUBSET
from src.ingestion.service import impact_replay, impact_service
from src.ingestion.service.impact_history import change_runs
from src.ingestion.service.ingest_service import test_key as key_of

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
STOPPED = {"stages": [{"name": "suggested", "duration_s": 60.0, "tests": 2, "failed": 1}],
           "time_to_first_failure_s": 20.0, "stopped_after_stage": 1}
TWO_STAGES = {"stages": [{"name": "suggested", "duration_s": 60.0, "tests": 1, "failed": 1},
                         {"name": "rest", "duration_s": 600.0, "tests": 3, "failed": 0}],
              "time_to_first_failure_s": 20.0}
SUGGESTED = {"state": "ok", "history_runs": 25, "needed_runs": 20, "statistical_total": 0, "tests": []}
UPLOAD = "/api/v1/collect/runs"


def statistics(db, project_id=1):
    db.expire_all()
    pairs = {(p.path_unit, p.test_key): (p.changed_runs, p.new_failures)
             for p in db.query(ImpactPair).filter_by(project_id=project_id)}
    bases = {b.test_key: (b.runs, b.new_failures) for b in db.query(ImpactTestBase).filter_by(project_id=project_id)}
    return pairs, bases


def ref(name):
    return {"test_key": key_of("s", "C", name), "suite": "s", "class_name": "C", "name": name}


def stored(db, run, *, evaluated, missed=()):
    db.add(RunImpact(run_id=run.id, suggested=SUGGESTED, model_version="stats-v1", replayed=False, scored_at=NOW,
                     caught=[] if evaluated else None, missed=[ref(n) for n in missed] if evaluated else None,
                     evaluated_at=NOW if evaluated else None))
    db.commit()


def upload(client, key, results, *, scope=FULL_SCOPE, stages=None):
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    run = {"ci_provider": "local", "branch": "main", "started_at": started.isoformat(),
           "finished_at": (started + timedelta(seconds=30)).isoformat(), "scope": scope}
    if stages is not None:
        run["stages"] = stages
    body = {"run": run,
            "results": [{"suite": "s", "class_name": "C", "name": name, "status": status, "duration_ms": 5}
                        for name, status in results],
            "changes": {"base_ref": "origin/main", "truncated": False,
                        "files": [{"path": "src/pay/api.py", "status": "M", "additions": 1, "deletions": 0}]}}
    response = client.post(UPLOAD, json=body, headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_subset_runs_add_nothing_to_the_statistics(db, seed_impact_history, seed_change_run):
    seed_impact_history(NOW - timedelta(days=20))
    impact_rollup.run_pass(db, now=lambda: NOW)
    before = statistics(db)
    assert before[0]  # the history gives `pays` its pairs
    for hours in (30, 20, 10):
        seed_change_run(NOW - timedelta(hours=hours), results=(("pays", "failed", 5), ("only-in-subsets", "failed", 5)),
                        paths=("src/pay/api.py",), scope=SUBSET, stages=STOPPED)
    impact_rollup.run_pass(db, now=lambda: NOW)
    assert statistics(db) == before
    assert key_of("s", "C", "only-in-subsets") not in statistics(db)[1]


def test_history_runs_count_only_full_runs(db, seed_change_run):
    for hours in (1, 2, 3):
        seed_change_run(NOW - timedelta(hours=hours))
    seed_change_run(NOW - timedelta(hours=5), scope=SUBSET, stages=STOPPED)
    assert impact_service.history_runs(db, 1, NOW) == 3


def test_replay_never_scores_a_subset_run(db, seed_change_run):
    full = seed_change_run(NOW - timedelta(days=2))
    subset = seed_change_run(NOW - timedelta(days=1), scope=SUBSET, stages=STOPPED)
    assert [r.id for r in change_runs(db, 1, NOW - timedelta(days=30), NOW, include_truncated=True)] == [full.id]
    assert impact_replay.replay_project(db, 1, NOW - timedelta(days=30), NOW) == 1
    db.expire_all()
    assert db.get(RunImpact, full.id) is not None
    assert db.get(RunImpact, subset.id) is None


def test_a_subset_upload_stores_its_suggestion_and_is_never_evaluated(client, db, make_key, monkeypatch):
    scheduled = []
    monkeypatch.setattr(impact_service, "evaluate_run", lambda factory, run_id: scheduled.append(run_id))
    _, key = make_key(project_id=1)
    run_id = upload(client, key, [("pays", "failed")], scope=SUBSET, stages=STOPPED)
    db.expire_all()
    row = db.get(RunImpact, run_id)
    assert row is not None and row.evaluated_at is None
    assert scheduled == []  # no outcome is written after the response
    assert impact_service.evaluate(db, run_id, datetime.now(timezone.utc)) is False
    db.expire_all()
    assert db.get(RunImpact, run_id).evaluated_at is None


def test_a_two_stage_upload_is_evaluated_as_before(client, db, make_key, monkeypatch):
    scheduled = []
    monkeypatch.setattr(impact_service, "evaluate_run", lambda factory, run_id: scheduled.append(run_id))
    _, key = make_key(project_id=1)
    run_id = upload(client, key, [("pays", "failed")], scope=FULL_SCOPE, stages=TWO_STAGES)
    assert scheduled == [run_id]


def test_subset_suggestions_never_take_the_nightly_passes_places(db, seed_change_run, monkeypatch):
    """Review Focus 2: three old subset suggestions and a full one; with room for two, the full one is evaluated."""
    monkeypatch.setattr(impact_service, "MAX_PENDING_PER_PASS", 2)
    subsets = [seed_change_run(NOW - timedelta(hours=10 - i), scope=SUBSET, stages=STOPPED) for i in range(3)]
    full = seed_change_run(NOW - timedelta(hours=2))
    for run, scored_at in [(run, NOW - timedelta(hours=9)) for run in subsets] + [(full, NOW - timedelta(hours=1))]:
        db.add(RunImpact(run_id=run.id, suggested=SUGGESTED, model_version="stats-v1", replayed=False,
                         scored_at=scored_at))
    db.commit()
    assert impact_service.evaluate_pending(db, NOW) == 1
    db.expire_all()
    assert db.get(RunImpact, full.id).evaluated_at is not None
    assert all(db.get(RunImpact, run.id).evaluated_at is None for run in subsets)


def test_the_accuracy_figure_leaves_subset_runs_out(client, auth, project_role, db, seed_change_run, monkeypatch):
    monkeypatch.setattr(analytics, "_now", lambda: NOW)
    project_role("viewer", project_id=1)
    stored(db, seed_change_run(NOW - timedelta(days=1)), evaluated=True, missed=("cart",))
    # An outcome on a subset run, as one written before this release would be: never counted
    stored(db, seed_change_run(NOW - timedelta(days=2), scope=SUBSET, stages=STOPPED), evaluated=True, missed=("ship",))
    body = client.get("/api/v1/projects/1/analytics/impact-accuracy", params={"days": 7}, headers=auth()).json()
    assert (body["missed"], body["live"]["runs"]) == (1, 1)
    assert [m["name"] for m in body["misses"]] == ["cart"]


def test_the_run_impact_answer_says_whether_it_was_evaluated(client, auth, project_role, db, seed_change_run):
    project_role("viewer", project_id=1)
    subset = seed_change_run(NOW - timedelta(days=1), scope=SUBSET, stages=STOPPED)
    pending = seed_change_run(NOW - timedelta(days=2))
    done = seed_change_run(NOW - timedelta(days=3))
    stored(db, subset, evaluated=False)
    stored(db, pending, evaluated=False)
    stored(db, done, evaluated=True)

    def answer(run):
        return client.get(f"/api/v1/projects/1/runs/{run.id}/impact", headers=auth()).json()

    assert (answer(subset)["evaluation"], answer(subset)["outcome"]) == ("not_evaluated", None)
    assert answer(pending)["evaluation"] == "pending"
    assert answer(done)["evaluation"] == "evaluated"


@pytest.mark.parametrize("with_changes", [False, True], ids=["no_change_data", "not_scored"])
def test_a_run_without_a_stored_suggestion_has_a_null_evaluation(client, auth, project_role, seed_run,
                                                                 seed_change_run, with_changes):
    """`evaluation` is always in the answer, and null without a stored suggestion, even for a subset run: there is
    nothing to evaluate or not. (Rewritten from the plan's version, which `body.get` made unable to fail.)"""
    project_role("viewer", project_id=1)
    seed = seed_change_run if with_changes else seed_run
    run = seed(NOW - timedelta(days=1), scope=SUBSET, stages=STOPPED)
    body = client.get(f"/api/v1/projects/1/runs/{run.id}/impact", headers=auth()).json()
    assert body["state"] == ("not_scored" if with_changes else "no_change_data")
    assert "evaluation" in body and body["evaluation"] is None
