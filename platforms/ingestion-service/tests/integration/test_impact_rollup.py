"""The impact-rollup job (spec 2026-10-12 §3.2; plan Rulings 6, 9, 14, 16): impact_pairs and impact_test_base."""
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.analytics.impact_rules import change_units
from src.ingestion.jobs import impact_rollup
from src.ingestion.models import Run, RunChangedFile, RunResult
from src.ingestion.models.impact import ImpactPair, ImpactTestBase, unit_hash
from src.ingestion.models.job_heartbeat import JobHeartbeat
from src.ingestion.models.muted import MutedTest
from src.ingestion.service import impact_stats
from src.ingestion.service.impact_history import change_runs, flaky_keys, newly_failed_bulk
from src.ingestion.service.impact_stats import live_excluded
from src.ingestion.service.ingest_service import test_key as key_of

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
PAYS, STEADY = key_of("s", "C", "pays"), key_of("s", "C", "steady")
PAY_UNITS = ("src/pay/api.py", "src/pay/", "src/")


def rows(db, project_id=1):
    db.expire_all()
    pairs = {(p.path_unit, p.test_key): (p.changed_runs, p.new_failures)
             for p in db.query(ImpactPair).filter_by(project_id=project_id)}
    bases = {b.test_key: (b.runs, b.new_failures, b.flaky)
             for b in db.query(ImpactTestBase).filter_by(project_id=project_id)}
    return pairs, bases


def rollup(db, at=NOW):
    return impact_rollup.run_pass(db, now=lambda: at)


def hours_ago(hours):
    return NOW - timedelta(hours=hours)


def test_a_pass_writes_the_pairs_with_new_failures_and_every_tests_base_rate(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15))
    summary = rollup(db)
    pairs, bases = rows(db)
    assert pairs == {(unit, PAYS): (4, 2) for unit in PAY_UNITS}
    assert bases == {PAYS: (15, 2, False), STEADY: (15, 0, False)}
    assert summary == {"event": "impact_rollup", "projects": 1, "pairs": 3, "tests": 2}


def test_each_pair_is_keyed_by_the_md5_of_its_unit(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15))
    rollup(db)
    assert {(p.unit_hash, p.path_unit) for p in db.query(ImpactPair)} == {(unit_hash(u), u) for u in PAY_UNITS}


def test_the_sql_statistics_equal_the_python_rules(db, seed_run, seed_change_run):
    """Path units, ignored paths, the 300-file rule and the counts: the SQL the job runs against impact_rules.py and
    newly_failed_bulk, recounted here in Python, on a varied fixture. Each test flips once on main, so none is flaky."""
    plan = [  # (hours ago, branch, base, paths)
        (30, "main", None, ("src/pay/api.py", "src/pay/util.py", "poetry.lock")),
        (28, "main", None, ("src//pay/api.py", "web/node_modules/x/i.js", "a/b/c/d/e.py")),
        (26, "main", None, tuple(f"lib/m{i}/f.py" for i in range(301))),
        (24, "main", None, ("lib/m1/f.py", "README.md", "./lib/../lib/m1/f.py")),
        (22, "feature/x", "main", ("src/pay/api.py",)),
        (20, "main", None, ("src/páginas/ação.py",)),
        (18, "main", None, ("src/páginas/ação.py", "dist/app.js")),
        (16, "main", None, ("src/pay/api.py",)),
    ]
    first_failing = {"a": 1, "b": 3, "d": 6}  # c fails only on feature/x: newly failed through the base branch
    for index, (hours, branch, base, paths) in enumerate(plan):
        results = [(name, "failed" if index >= at else "passed", 5) for name, at in first_failing.items()]
        results.append(("c", "failed" if branch == "feature/x" else "passed", 5))
        if index == 7:
            results[-2] = ("d", "errored", 5)
        seed_change_run(hours_ago(hours), results=tuple(results), paths=paths, branch=branch, base_branch=base)
    seed_run(hours_ago(14), results=(("a", "passed", 5),))  # no changed files: history only
    rollup(db)

    start = impact_rollup.window_start(NOW)
    runs = change_runs(db, 1, start, NOW)
    flaky = flaky_keys(db, 1, start)
    newly = newly_failed_bulk(db, runs, flaky)
    changed, failed, pairs = Counter(), Counter(), Counter()
    for run in runs:
        units = change_units(run.paths)
        changed.update(units)
        failed.update(newly.get(run.id, set()))
        pairs.update((unit, key) for unit in units for key in newly.get(run.id, set()))
    expected_pairs = {(unit, key): (changed[unit], count) for (unit, key), count in pairs.items()}
    expected_bases = {key_of("s", "C", name): (len(runs), failed[key_of("s", "C", name)], key_of("s", "C", name) in flaky)
                      for name in ("a", "b", "c", "d")}
    assert rows(db) == (expected_pairs, expected_bases)
    assert not flaky and sum(failed.values()) == 4 and len(expected_pairs) > 10  # the fixture exercises the rules


def test_build_statistics_reads_what_a_pass_writes(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15))
    rollup(db)
    pairs, bases = impact_stats.build_statistics(db, 1, impact_rollup.window_start(NOW), NOW, set(), set())
    assert ({(p.path_unit, p.test_key): (p.changed_runs, p.new_failures) for p in pairs},
            {b.test.test_key: (b.runs, b.new_failures, b.flaky) for b in bases}) == rows(db)
    assert {b.test.name for b in bases} == {"pays", "steady"}


def test_names_and_the_test_file_are_kept_for_scoring(db, seed_change_run):
    run = seed_change_run(hours_ago(1), results=(("pays", "passed", 5),))
    db.query(RunResult).filter_by(run_id=run.id).update({"file": "tests/test_pay.py"})
    db.commit()
    rollup(db)
    base = db.query(ImpactTestBase).one()
    assert (base.suite, base.class_name, base.name, base.file) == ("s", "C", "pays", "tests/test_pay.py")


def test_the_test_file_comes_from_the_newest_run(db, seed_change_run):
    for hours, file in ((3, "tests/z_old_place.py"), (2, "tests/test_pay.py"), (1, None)):
        run = seed_change_run(hours_ago(hours), results=(("pays", "passed", 5),))
        db.query(RunResult).filter_by(run_id=run.id).update({"file": file})
    db.commit()
    rollup(db)
    assert db.query(ImpactTestBase).one().file is None  # the newest run recorded none: max() would say z_old_place
    db.query(RunResult).filter(RunResult.file.is_(None)).update({"file": "tests/test_pay.py"})
    db.commit()
    rollup(db)
    db.expire_all()
    assert db.query(ImpactTestBase).one().file == "tests/test_pay.py"


def test_running_twice_the_same_day_writes_the_same_rows(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15))
    rollup(db)
    first = rows(db)
    rollup(db, NOW + timedelta(hours=6))
    assert rows(db) == first


def test_a_truncated_change_list_is_left_out_but_its_results_are_still_history(db, seed_change_run):
    seed_change_run(hours_ago(3), results=(("pays", "failed", 5),), paths=("docs/guide.md",))
    seed_change_run(hours_ago(2), results=(("pays", "passed", 5),), paths=("src/pay/api.py",), truncated=True)
    seed_change_run(hours_ago(1), results=(("pays", "failed", 5),), paths=("src/cart/x.py",))
    rollup(db)
    pairs, bases = rows(db)
    # newly failed after the truncated run's pass; the truncated run's src/pay/ is not counted
    assert pairs == {(unit, PAYS): (1, 1) for unit in ("src/cart/x.py", "src/cart/", "src/")}
    assert bases[PAYS] == (2, 1, False)


def test_a_change_of_more_than_300_files_counts_only_its_folders(db, seed_change_run):
    seed_change_run(hours_ago(2), results=(("pays", "passed", 5),), paths=("docs/guide.md",))
    seed_change_run(hours_ago(1), results=(("pays", "failed", 5),), paths=tuple(f"src/big/f{i}.py" for i in range(301)))
    rollup(db)
    assert rows(db)[0] == {("src/big/", PAYS): (1, 1), ("src/", PAYS): (1, 1)}


def test_lock_files_and_vendored_paths_make_no_pairs(db, seed_change_run):
    seed_change_run(hours_ago(2), results=(("pays", "passed", 5),), paths=("docs/guide.md",))
    seed_change_run(hours_ago(1), results=(("pays", "failed", 5),), paths=("poetry.lock", "web/node_modules/x/index.js"))
    rollup(db)
    pairs, bases = rows(db)
    assert pairs == {} and bases[PAYS] == (2, 1, False)


def test_a_flaky_test_counts_no_new_failures_and_is_flagged(db, seed_change_run):
    for hours, status in zip(range(6, 0, -1), ("passed", "failed") * 3):
        seed_change_run(hours_ago(hours), results=(("pays", status, 5),), paths=("src/pay/api.py",))
    rollup(db)
    pairs, bases = rows(db)
    assert pairs == {} and bases[PAYS] == (6, 0, True)
    assert live_excluded(db, 1) == {PAYS}


def test_a_muted_test_counts_no_new_failures(db, seed_change_run):
    seed_change_run(hours_ago(2), results=(("pays", "passed", 5),))
    seed_change_run(hours_ago(1), results=(("pays", "failed", 5),))
    db.add(MutedTest(project_id=1, test_key=PAYS, muted_by_user_id=1))
    db.commit()
    rollup(db)
    pairs, bases = rows(db)
    assert pairs == {} and bases[PAYS] == (2, 0, False)
    assert live_excluded(db, 1) == {PAYS}


def test_runs_before_the_window_are_left_out(db, seed_change_run):
    # the window starts 90 days before today 00:00 UTC: 2026-07-14 00:00
    seed_change_run(datetime(2026, 7, 13, 23, 0, tzinfo=timezone.utc), results=(("old", "passed", 5),))
    seed_change_run(datetime(2026, 7, 14, 0, 30, tzinfo=timezone.utc), results=(("new", "passed", 5),))
    rollup(db)
    assert set(rows(db)[1]) == {key_of("s", "C", "new")}


def test_each_project_has_its_own_rows(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15), project_id=1)
    seed_impact_history(start=NOW - timedelta(days=15), project_id=2)
    assert rollup(db)["projects"] == 2
    assert rows(db, 1) == rows(db, 2) and rows(db, 1)[0]


def test_a_project_whose_runs_are_gone_loses_its_rows(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15))
    rollup(db)
    db.query(RunChangedFile).delete()
    db.query(RunResult).delete()
    db.query(Run).delete()
    db.commit()
    assert rollup(db)["projects"] == 1
    assert rows(db) == ({}, {})


@pytest.fixture
def session_factory(db):
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)


def test_a_pass_records_its_heartbeat_and_logs_a_summary(db, session_factory, capsys):
    assert impact_rollup.main([], session_factory=session_factory) == 0
    db.expire_all()
    assert db.get(JobHeartbeat, "impact_rollup").last_success_at is not None
    assert '"event": "impact_rollup"' in capsys.readouterr().out


def test_a_failed_pass_records_the_error_and_exits_1(db, session_factory, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(impact_rollup, "run_pass", boom)
    assert impact_rollup.main([], session_factory=session_factory) == 1
    db.expire_all()
    heartbeat = db.get(JobHeartbeat, "impact_rollup")
    assert heartbeat.last_success_at is None and heartbeat.last_error == "RuntimeError: boom"


def test_a_pass_skipped_for_the_lock_writes_no_heartbeat(db, session_factory, monkeypatch, capsys):
    from contextlib import contextmanager

    from src.ingestion.jobs import scaffold

    @contextmanager
    def held(_engine, _lock_id):
        yield False

    monkeypatch.setattr(scaffold, "advisory_lock", held)
    assert impact_rollup.main([], session_factory=session_factory) == 0
    db.expire_all()
    assert db.get(JobHeartbeat, "impact_rollup") is None
    assert "another copy holds the lock" in capsys.readouterr().out


def test_the_loop_survives_a_failed_pass_and_stops_when_asked(session_factory, monkeypatch):
    stop = threading.Event()
    calls = []

    def flaky_pass(db, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first pass fails")
        stop.set()
        return {}

    monkeypatch.setattr(impact_rollup, "run_pass", flaky_pass)
    assert impact_rollup.main(["--loop"], session_factory=session_factory, stop=stop, interval_hours=0) == 0
    assert len(calls) == 2
