"""Newly failed (spec 2026-10-12 §3.1, plan Rulings 6, 7, 8): one run's answer, and the rollup's bulk answer that
must agree with it."""
from datetime import datetime, timedelta, timezone

from src.ingestion.models import Run
from src.ingestion.service import impact_history
from src.ingestion.service.ingest_service import test_key as key_of

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def ago(hours):
    return NOW - timedelta(hours=hours)


def newly(db, run, excluded=()):
    db.expire_all()
    return [t.name for t in impact_history.newly_failed_in_run(db, db.get(Run, run.id), set(excluded))]


def test_passed_then_failed_is_newly_failed(db, seed_run):
    seed_run(ago(3), results=(("pays", "passed", 1),))
    assert newly(db, seed_run(ago(2), results=(("pays", "failed", 1),))) == ["pays"]


def test_failed_then_failed_is_not(db, seed_run):
    seed_run(ago(3), results=(("pays", "failed", 1),))
    assert newly(db, seed_run(ago(2), results=(("pays", "failed", 1),))) == []


def test_errored_is_failing_too(db, seed_run):
    seed_run(ago(3), results=(("pays", "passed", 1),))
    assert newly(db, seed_run(ago(2), results=(("pays", "errored", 1),))) == ["pays"]


def test_a_skipped_result_is_not_the_previous_one(db, seed_run):
    seed_run(ago(4), results=(("pays", "passed", 1),))
    seed_run(ago(3), results=(("pays", "skipped", 0),))
    assert newly(db, seed_run(ago(2), results=(("pays", "failed", 1),))) == ["pays"]


def test_the_last_attempt_is_the_outcome(db, seed_run):
    seed_run(ago(5), results=(("pays", "passed", 1),))
    retried = seed_run(ago(4), results=(("pays", "failed", 1), ("pays", "passed", 1)))  # failed, passed on retry
    assert newly(db, retried) == []
    # the retried run's outcome (passed) is the previous result of the next run, whose last attempt failed
    assert newly(db, seed_run(ago(3), results=(("pays", "passed", 1), ("pays", "failed", 1)))) == ["pays"]


def test_another_branch_is_not_the_previous_result(db, seed_run):
    seed_run(ago(3), results=(("pays", "passed", 1),), branch="main")
    assert newly(db, seed_run(ago(2), results=(("pays", "failed", 1),), branch="dev")) == []


def test_a_new_branch_falls_back_to_its_base_branch(db, seed_run, seed_change_run):
    seed_run(ago(3), results=(("pays", "passed", 1),), branch="main")
    pr = seed_change_run(ago(2), results=(("pays", "failed", 1),), branch="feature/pay", base_branch="main")
    assert newly(db, pr) == ["pays"]


def test_the_base_branch_also_comes_from_the_diffs_base_ref(db, seed_run, seed_change_run):
    seed_run(ago(3), results=(("pays", "passed", 1),), branch="develop")
    pr = seed_change_run(ago(2), results=(("pays", "failed", 1),), branch="feature/pay")
    pr.change_base_ref = "origin/develop"
    db.commit()
    assert newly(db, pr) == ["pays"]


def test_the_base_branch_counts_only_results_before_the_run(db, seed_run, seed_change_run):
    seed_run(ago(4), results=(("pays", "failed", 1),), branch="main")
    pr = seed_change_run(ago(3), results=(("pays", "failed", 1),), branch="feature/pay", base_branch="main")
    seed_run(ago(2), results=(("pays", "passed", 1),), branch="main")
    assert newly(db, pr) == []


def test_the_base_branchs_latest_outcome_counts_even_after_a_run_of_passes(db, seed_run, seed_change_run):
    """The fallback reads the base branch's latest outcome before the run, not only outcomes next to a failure."""
    for hours in (6, 5, 4):
        seed_run(ago(hours), results=(("pays", "passed", 1),), branch="main")
    pr = seed_change_run(ago(3), results=(("pays", "failed", 1),), branch="feature/pay", base_branch="main")
    assert newly(db, pr) == ["pays"]


def test_excluded_tests_never_newly_fail(db, seed_run):
    seed_run(ago(3), results=(("pays", "passed", 1),))
    run = seed_run(ago(2), results=(("pays", "failed", 1),))
    assert newly(db, run, excluded={key_of("s", "C", "pays")}) == []


def test_a_previous_result_older_than_90_days_does_not_count(db, seed_run):
    seed_run(NOW - timedelta(days=91), results=(("pays", "passed", 1),))
    assert newly(db, seed_run(ago(1), results=(("pays", "failed", 1),))) == []


def test_change_runs_leave_out_truncated_runs_and_runs_without_files(db, seed_run, seed_change_run):
    kept = seed_change_run(ago(3), paths=("src/a.py", "src/b.py"))
    seed_change_run(ago(2), paths=("src/c.py",), truncated=True)
    seed_run(ago(1))
    runs = impact_history.change_runs(db, 1, NOW - timedelta(days=1), NOW)
    assert [(r.id, r.paths, r.base) for r in runs] == [(kept.id, ("src/a.py", "src/b.py"), None)]
    assert len(impact_history.change_runs(db, 1, NOW - timedelta(days=1), NOW, include_truncated=True)) == 2


def test_the_bulk_answer_agrees_with_the_one_run_answer(db, seed_run, seed_change_run):
    """The rollup's window must find exactly what an upload's outcome finds, run by run."""
    seed_run(NOW - timedelta(days=95), results=(("old", "passed", 1),))  # beyond the look-back of every run
    seed_run(ago(60), results=(("pays", "passed", 1), ("cart", "failed", 1)))
    seed_change_run(ago(50), results=(("pays", "failed", 1), ("cart", "failed", 1), ("old", "failed", 1)))
    seed_change_run(ago(40), results=(("pays", "failed", 1), ("pays", "passed", 1), ("cart", "passed", 1)))
    seed_change_run(ago(30), results=(("pays", "errored", 1), ("cart", "skipped", 0)))
    seed_run(ago(25), results=(("ship", "passed", 1),), branch="main")
    seed_change_run(ago(20), results=(("ship", "failed", 1), ("pays", "failed", 1)), branch="feature/ship",
                    base_branch="main")
    seed_run(ago(15), results=(("ship", "passed", 1),), branch="feature/ship")
    seed_change_run(ago(10), results=(("ship", "failed", 1),), branch="feature/ship", base_branch="main")
    seed_change_run(ago(5), results=(("lone", "failed", 1),), branch=None)
    runs = impact_history.change_runs(db, 1, NOW - timedelta(days=100), NOW)
    bulk = impact_history.newly_failed_bulk(db, runs, set())
    for run in runs:
        expected = {t.test_key for t in impact_history.newly_failed_in_run(db, db.get(Run, run.id), set())}
        assert bulk.get(run.id, set()) == expected, run.id
    assert sum(len(keys) for keys in bulk.values()) == 4  # pays at 50 h and 30 h, ship at 20 h (base) and 10 h


def test_flaky_keys_use_the_flaky_views_defaults(db, seed_run):
    for i, status in enumerate(("passed", "failed") * 3):
        seed_run(ago(10 - i), results=(("flips", status, 1), ("steady", "passed", 1)))
    assert impact_history.flaky_keys(db, 1, NOW - timedelta(days=14)) == {key_of("s", "C", "flips")}
