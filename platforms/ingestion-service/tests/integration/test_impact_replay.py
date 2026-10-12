"""Replay (spec 2026-10-12 §3.6, plan Ruling 13): past runs scored with statistics from earlier days only, stored as
replayed with their real outcome."""
import json
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.analytics import impact_score
from src.ingestion.analytics.impact_rules import WINDOW_DAYS
from src.ingestion.jobs import impact_rollup, retention, rollup, scaffold, weekly_summary
from src.ingestion.models import RunResult
from src.ingestion.models.impact import RunImpact
from src.ingestion.models.job_heartbeat import JobHeartbeat
from src.ingestion.service import analytics_service, impact_replay, impact_service
from src.ingestion.service.impact_history import flaky_keys
from src.ingestion.service.impact_stats import rebuild_statistics

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
EMPTY = {"state": "ok", "history_runs": 0, "needed_runs": 20, "statistical_total": 0, "tests": []}


@pytest.fixture(autouse=True)
def ten_runs_are_enough(monkeypatch):
    monkeypatch.setattr(impact_score, "MIN_HISTORY_RUNS", 10)


def row(db, run_id):
    db.expire_all()
    return db.get(RunImpact, run_id)


def backfill(db, days=30):
    return impact_rollup.run_backfill(db, days, now=lambda: NOW)


def test_a_replayed_run_is_scored_from_the_days_before_it_only(db, seed_impact_history, seed_change_run):
    history = seed_impact_history(start=NOW - timedelta(days=15))  # one run a day, days -15 to -1, at 12:00
    today = seed_change_run(NOW - timedelta(hours=1), results=(("pays", "passed", 5), ("steady", "passed", 5)),
                            paths=("src/pay/new.py",))
    assert backfill(db)["runs_replayed"] == 16
    # Day -1: pays newly failed; before that day src/pay/ had 3 change runs and 1 new failure, too few
    last = row(db, history[-1].id)
    assert last.replayed is True and last.suggested["history_runs"] == 14
    assert [t["kind"] for t in last.suggested["tests"]] == []
    assert [t["name"] for t in last.missed] == ["pays"] and last.caught == []
    assert last.evaluated_at is not None and last.model_version == "stats-v1"
    # Today: the 15 earlier runs, so pays qualifies from statistics
    pays = next(t for t in row(db, today.id).suggested["tests"] if t["name"] == "pays")
    assert pays["kind"] == "statistical"
    assert pays["evidence"] == {"path_unit": "src/pay/", "changed_runs": 4, "new_failures": 2,
                                "confidence": 0.5, "lift": 3.75, "base_rate": 0.1333}


def test_runs_earlier_on_the_same_day_are_not_in_the_statistics(db, seed_impact_history, seed_change_run):
    """Ruling 13: the cut-off is the start of the run's UTC day, not its start. A run at 01:00 today changes src/pay/
    and steady newly fails in it; the 11:00 run's evidence for pays still counts only the days before (4 change runs
    of src/pay/, not 5)."""
    seed_impact_history(start=NOW - timedelta(days=15))
    day = datetime.combine(NOW.date(), time.min, tzinfo=timezone.utc)
    seed_change_run(day + timedelta(hours=1), results=(("steady", "failed", 5),), paths=("src/pay/b.py",))
    late = seed_change_run(day + timedelta(hours=11), results=(("pays", "passed", 5),), paths=("src/pay/new.py",))
    backfill(db)
    pays = next(t for t in row(db, late.id).suggested["tests"] if t["name"] == "pays")
    assert (pays["evidence"]["changed_runs"], pays["evidence"]["new_failures"]) == (4, 2)


def test_replay_scores_as_live_scoring_does_from_the_same_statistics(db, seed_impact_history, seed_change_run):
    """Live and replay agree: the statistics the nightly pass would have written at the start of the run's day, read
    by live scoring, give the suggestion replay stored. The fixture reaches every kind: statistical (pays), test file
    changed (steady's file), failing on the branch (rare, failing in main's latest run) and no history yet (fresh)."""
    seed_impact_history(start=NOW - timedelta(days=15))
    seed_change_run(NOW - timedelta(days=1, hours=-1), results=(("rare", "failed", 5), ("fresh", "passed", 5)),
                    paths=("docs/x.md",))
    db.query(RunResult).filter(RunResult.name == "steady").update({"file": "tests/pay/test_steady.py"})
    db.commit()
    paths = ["src/pay/new.py", "tests/pay/test_steady.py"]
    today = seed_change_run(NOW - timedelta(hours=1), results=(("pays", "passed", 5),), paths=tuple(paths))
    backfill(db)
    replayed = row(db, today.id).suggested
    assert [(t["name"], t["kind"]) for t in replayed["tests"]] == [
        ("pays", "statistical"), ("steady", "test_file_changed"), ("rare", "failing_on_branch"),
        ("fresh", "no_history")]

    day = datetime.combine(NOW.date(), time.min, tzinfo=timezone.utc)
    start = day - timedelta(days=WINDOW_DAYS)
    rebuild_statistics(db, 1, start, day, flaky_keys(db, 1, NOW - timedelta(days=WINDOW_DAYS)),
                       analytics_service.muted_keys(db, 1), day)
    live = impact_service.score_change(db, 1, paths, "main", now=NOW - timedelta(hours=1))
    assert replayed == live


def test_replay_keeps_live_suggestions_and_a_second_replay_adds_nothing(db, seed_change_run):
    live = seed_change_run(NOW - timedelta(hours=3), results=(("pays", "passed", 5),))
    other = seed_change_run(NOW - timedelta(hours=2), results=(("pays", "failed", 5),))
    db.add(RunImpact(run_id=live.id, suggested=EMPTY, model_version="stats-v1", replayed=False, scored_at=NOW))
    db.commit()
    assert backfill(db)["runs_replayed"] == 1
    assert row(db, live.id).replayed is False and row(db, live.id).evaluated_at is None
    assert row(db, other.id).replayed is True and [t["name"] for t in row(db, other.id).missed] == ["pays"]
    assert backfill(db)["runs_replayed"] == 0


def test_only_the_requested_days_are_replayed(db, seed_change_run):
    old = seed_change_run(NOW - timedelta(days=8))
    recent = seed_change_run(NOW - timedelta(days=2))
    backfill(db, days=7)
    assert row(db, old.id) is None and row(db, recent.id) is not None


def test_a_truncated_run_is_replayed_too(db, seed_change_run):
    run = seed_change_run(NOW - timedelta(days=1), truncated=True)
    backfill(db, days=7)
    assert row(db, run.id).replayed is True


def test_days_are_replayed_in_order_in_batches_with_progress(db, seed_change_run, monkeypatch, capsys):
    monkeypatch.setattr(impact_replay, "BATCH_RUNS", 2)
    commits = []
    real_commit = db.commit
    monkeypatch.setattr(db, "commit", lambda: (commits.append(1), real_commit()))
    for hours in (49, 48, 47, 25):  # 3 runs on day -2, 1 on day -1
        seed_change_run(NOW - timedelta(hours=hours))
    commits.clear()
    capsys.readouterr()
    assert backfill(db, days=7)["runs_replayed"] == 4
    progress = [json.loads(line) for line in capsys.readouterr().out.splitlines()
                if '"impact_backfill_progress"' in line]
    assert [(p["day"], p["done"], p["total"]) for p in progress] == [
        ("2026-10-10", 2, 4), ("2026-10-10", 3, 4), ("2026-10-11", 4, 4)]
    assert all(p["project_id"] == 1 for p in progress)
    assert len(commits) == 3  # one per batch


@pytest.mark.parametrize("value", ["0", "91", "x"])
def test_backfill_days_must_be_1_to_90(value):
    with pytest.raises(SystemExit):
        impact_rollup.main(["--backfill-days", value])


def test_backfill_refuses_loop():
    with pytest.raises(SystemExit):
        impact_rollup.main(["--backfill-days", "30", "--loop"])


def test_a_backfill_is_not_the_nightly_pass_so_it_writes_no_heartbeat(db, seed_change_run, capsys):
    seed_change_run(datetime.now(timezone.utc) - timedelta(days=1))
    factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
    assert impact_rollup.main(["--backfill-days", "7"], session_factory=factory) == 0
    db.expire_all()
    assert db.get(JobHeartbeat, "impact_rollup") is None
    assert '"runs_replayed": 1' in capsys.readouterr().out


def test_a_backfill_takes_its_own_lock_so_it_never_blocks_the_nightly_pass(db, monkeypatch):
    taken = []

    @contextmanager
    def lock(engine, lock_id):
        taken.append(lock_id)
        yield False

    monkeypatch.setattr(scaffold, "advisory_lock", lock)
    factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
    assert impact_rollup.run_backfill_once(session_factory=factory, lock_engine=db.get_bind(), days=7) is False
    assert taken == [impact_rollup.BACKFILL_LOCK_ID]
    others = {retention.LOCK_ID, rollup.LOCK_ID, weekly_summary.LOCK_ID, impact_rollup.LOCK_ID}
    assert impact_rollup.BACKFILL_LOCK_ID not in others and len(others) == 4


# ---- the nightly pass's pending outcomes are capped ----

def test_a_nightly_pass_evaluates_at_most_500_pending_outcomes_oldest_first(db, seed_change_run, monkeypatch):
    assert impact_service.MAX_PENDING_PER_PASS == 500
    monkeypatch.setattr(impact_service, "MAX_PENDING_PER_PASS", 2)
    runs = [seed_change_run(NOW - timedelta(hours=h)) for h in (5, 4, 3)]
    for minutes, run in zip((60, 120, 90), runs):  # scored: run 1 newest, run 2 oldest
        db.add(RunImpact(run_id=run.id, suggested=EMPTY, model_version="stats-v1", replayed=False,
                         scored_at=NOW - timedelta(minutes=minutes)))
    db.commit()
    assert impact_service.evaluate_pending(db, NOW) == 2
    assert [row(db, run.id).evaluated_at is not None for run in runs] == [False, True, True]
    assert impact_service.evaluate_pending(db, NOW) == 1
