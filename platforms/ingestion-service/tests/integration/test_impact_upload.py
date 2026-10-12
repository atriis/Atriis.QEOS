"""The suggestion stored with an upload, scored before its results, and its outcome (spec 2026-10-12 §3.4, §9; plan
Rulings 1, 2, 16)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.ingestion.analytics.impact_rules import ChangedFiles, change_units
from src.ingestion.models import Run, RunResult
from src.ingestion.models.impact import ImpactPair, ImpactTestBase, RunImpact, unit_hash
from src.ingestion.models.muted import MutedTest
from src.ingestion.service import impact_service
from src.ingestion.service.ingest_service import test_key as key_of

URL = "/api/v1/collect/runs"
PAYS, CART = key_of("s", "C", "pays"), key_of("s", "C", "cart")


def hours_ago(hours):
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def upload(client, key, results, paths=("src/pay/api.py",), branch="main", started=None, idempotency_key=None,
           base_branch=None):
    started = started or hours_ago(0.1)
    run = {"ci_provider": "local", "branch": branch, "started_at": started.isoformat(),
           "finished_at": (started + timedelta(seconds=30)).isoformat()}
    if base_branch:
        run["base_branch"] = base_branch
    body = {"run": run, "results": [{"suite": "s", "class_name": "C", "name": name, "status": status, "duration_ms": 5}
                                    for name, status in results]}
    if paths is not None:
        body["changes"] = {"base_ref": "origin/main", "truncated": False,
                           "files": [{"path": p, "status": "M", "additions": 1, "deletions": 0} for p in paths]}
    headers = {"Authorization": f"Bearer {key}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    response = client.post(URL, json=body, headers=headers)
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def stored(db, run_id):
    db.expire_all()
    return db.get(RunImpact, run_id)


def base_row(name, runs, flaky=False, file=None, new_failures=0, project_id=1):
    return ImpactTestBase(project_id=project_id, test_key=key_of("s", "C", name), runs=runs, new_failures=new_failures,
                          flaky=flaky, suite="s", class_name="C", name=name, file=file, computed_at=hours_ago(5))


def pair_row(unit, name, changed_runs=4, new_failures=2, project_id=1):
    return ImpactPair(project_id=project_id, unit_hash=unit_hash(unit), test_key=key_of("s", "C", name),
                      path_unit=unit, changed_runs=changed_runs, new_failures=new_failures, computed_at=hours_ago(5))


def test_the_suggestion_is_stored_with_the_run_and_the_outcome_follows(client, db, make_key, seed_change_run):
    seed_change_run(hours_ago(3), results=(("pays", "passed", 5), ("old", "failed", 5)))
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed"), ("old", "failed")]))
    assert (row.model_version, row.replayed) == ("stats-v1", False)
    assert row.suggested["state"] == "not_enough_history"
    assert [(t["name"], t["kind"]) for t in row.suggested["tests"]] == [("old", "failing_on_branch")]
    assert row.caught == [] and [t["name"] for t in row.missed] == ["pays"]  # old failed before: not new
    assert row.evaluated_at is not None


def test_the_suggestion_never_sees_its_own_run_or_results(client, db, make_key, seed_change_run, monkeypatch):
    seed_change_run(hours_ago(3), results=(("pays", "passed", 5),))
    seen = {}
    real = impact_service.score_change

    def spy(session, project_id, changed_paths, branch, *, now, **kw):
        seen["runs"], seen["results"] = session.query(Run).count(), session.query(RunResult).count()
        return real(session, project_id, changed_paths, branch, now=now, **kw)

    monkeypatch.setattr(impact_service, "score_change", spy)
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed"), ("new", "failed")]))
    assert seen == {"runs": 1, "results": 1}  # only the seeded run: neither this run nor its results existed yet
    assert row.suggested["tests"] == []       # its own failures are not "failing on this branch"


def test_a_suggested_test_that_newly_fails_is_caught(client, db, make_key, seed_change_run):
    seed_change_run(hours_ago(3), results=(("pays", "passed", 5),))
    db.add(base_row("pays", runs=1))
    db.commit()
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed")]))
    assert [(t["name"], t["kind"]) for t in row.suggested["tests"]] == [("pays", "no_history")]
    assert [t["name"] for t in row.caught] == ["pays"] and row.missed == []


def test_a_statistical_suggestion_is_scored_from_the_change_units(client, db, make_key, seed_change_run):
    for hour in range(20, 40):  # 20 runs with changed files: enough history
        seed_change_run(hours_ago(hour), results=(("pays", "passed", 5),), paths=("docs/a.md",))
    db.add_all([base_row("pays", runs=40, new_failures=2), pair_row("src/pay/", "pays")])
    db.commit()
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed")]))
    assert row.suggested["state"] == "ok"
    [entry] = row.suggested["tests"]
    assert (entry["name"], entry["kind"], entry["evidence"]["path_unit"]) == ("pays", "statistical", "src/pay/")
    assert [t["name"] for t in row.caught] == ["pays"]


def test_scoring_loads_only_the_change_units_and_the_tests_that_can_carry_a_label(db):
    """Ruling (perf): never the whole project's statistics: pairs by the change's unit hashes, base rows of those
    pairs' tests, of tests whose recorded file may be in the change, and of tests with no history yet."""
    db.add_all([
        pair_row("src/pay/", "pays"), pair_row("src/cart/", "cart"), pair_row("src/pay/", "other", project_id=2),
        base_row("pays", runs=40), base_row("cart", runs=40), base_row("steady", runs=40, file="tests/test_steady.py"),
        base_row("fresh", runs=1), base_row("own", runs=40, file="/ci/repo/tests/test_own.py"),
        base_row("cased", runs=40, file="tests\\test_cased.py"), base_row("wild", runs=40, file="tests/test_%_.py"),
    ])
    db.commit()
    # "docs/%_.py": LIKE wildcards in a changed name are escaped, or "%_.py" would load test_steady.py too
    paths = ["src/pay/api.py", "tests/test_own.py", "repo/tests/test_cased.py", "docs/%_.py"]
    pairs, bases = impact_service.load_statistics(db, 1, change_units(paths), ChangedFiles(paths))
    assert [(p.path_unit, p.test_key) for p in pairs] == [("src/pay/", PAYS)]
    # "wild" is read (its file contains the changed name "%_.py") and then not labelled: scoring's own check decides
    assert {b.test.name for b in bases.values()} == {"pays", "fresh", "own", "cased", "wild"}


def test_muted_and_flagged_flaky_tests_are_left_out_of_the_outcome(client, db, make_key, seed_change_run):
    seed_change_run(hours_ago(3), results=(("pays", "passed", 5), ("cart", "passed", 5)))
    db.add(MutedTest(project_id=1, test_key=PAYS, muted_by_user_id=1))
    db.add(base_row("cart", runs=9, flaky=True))
    db.commit()
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed"), ("cart", "failed")]))
    assert row.caught == [] and row.missed == []


def test_a_new_branch_is_compared_with_its_base_branch(client, db, make_key, seed_run):
    seed_run(hours_ago(3), results=(("pays", "passed", 5),), branch="main")
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed")], branch="feature/pay", base_branch="main"))
    assert [t["name"] for t in row.missed] == ["pays"]


def test_a_late_upload_reads_the_branch_as_it_was_before_the_run(client, db, make_key, seed_run):
    seed_run(hours_ago(5), results=(("early", "failed", 5),))
    seed_run(hours_ago(1), results=(("later", "failed", 5),))
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "passed")], started=hours_ago(3)))
    assert [t["name"] for t in row.suggested["tests"]] == ["early"]


def test_each_collector_part_is_its_own_run_with_its_own_suggestion(client, db, make_key):
    _, key = make_key(project_id=1)
    started = hours_ago(0.5)
    first = upload(client, key, [("pays", "failed")], started=started, idempotency_key="ci-7-part-1")
    second = upload(client, key, [("cart", "failed")], started=started, idempotency_key="ci-7-part-2")
    assert first != second
    rows = [stored(db, first), stored(db, second)]
    assert all(row is not None and row.evaluated_at is not None for row in rows)
    assert [[t["name"] for t in row.missed] for row in rows] == [[], []]  # no earlier outcome: nothing newly failed


def test_no_suggestion_without_changed_files(client, db, make_key):
    _, key = make_key(project_id=1)
    assert stored(db, upload(client, key, [("pays", "failed")], paths=None)) is None
    assert stored(db, upload(client, key, [("pays", "failed")], paths=())) is None


def test_a_replayed_upload_is_not_scored_again(client, db, make_key, monkeypatch):
    _, key = make_key(project_id=1)
    started = hours_ago(1)
    run_id = upload(client, key, [("pays", "passed")], started=started, idempotency_key="ci-1")
    calls = []
    monkeypatch.setattr(impact_service, "score_change", lambda *args, **kwargs: calls.append(1) or {})
    assert upload(client, key, [("pays", "passed")], started=started, idempotency_key="ci-1") == run_id
    assert calls == [] and db.query(RunImpact).count() == 1


def test_a_failing_scoring_never_fails_the_upload(client, db, make_key, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise RuntimeError("scoring broke")

    monkeypatch.setattr(impact_service, "score_change", boom)
    _, key = make_key(project_id=1)
    run_id = upload(client, key, [("pays", "failed")])
    assert db.query(RunResult).filter_by(run_id=run_id).count() == 1
    assert stored(db, run_id) is None
    err = capsys.readouterr().err
    assert '"event": "impact_failed"' in err and '"step": "score"' in err and "scoring broke" not in err


def test_a_database_error_while_scoring_still_stores_the_upload(client, db, make_key, monkeypatch, capsys):
    def broken_query(session, *_args, **_kwargs):
        session.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setattr(impact_service, "load_statistics", broken_query)
    _, key = make_key(project_id=1)
    started = hours_ago(0.1)
    body = {"run": {"ci_provider": "local", "branch": "main", "started_at": started.isoformat(),
                    "finished_at": (started + timedelta(seconds=30)).isoformat()},
            "results": [{"suite": "s", "class_name": "C", "name": "pays", "status": "failed", "duration_ms": 5}],
            "changes": {"base_ref": "origin/main", "truncated": False,
                        "files": [{"path": "src/a.py", "status": "M", "additions": 1, "deletions": 0}]}}
    response = client.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    assert db.query(RunResult).filter_by(run_id=run_id).count() == 1 and stored(db, run_id) is None
    assert '"step": "score"' in capsys.readouterr().err


def test_a_failing_outcome_keeps_the_suggestion_without_one(client, db, make_key, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise RuntimeError("outcome broke")

    monkeypatch.setattr(impact_service, "newly_failed_in_run", boom)
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed")]))
    assert row is not None and row.evaluated_at is None and row.caught is None
    err = capsys.readouterr().err
    assert '"step": "outcome"' in err and "outcome broke" not in err


def test_the_outcome_runs_after_the_response_not_in_the_request(client, db, make_key, monkeypatch):
    """newly_failed_in_run costs 120-585 ms per run: it must never run inside the upload's request."""
    from src.ingestion.api.v1.endpoints import collect

    queued, computed = [], []
    monkeypatch.setattr(collect.BackgroundTasks, "add_task",
                        lambda self, func, *args, **kwargs: queued.append((func, args)))
    monkeypatch.setattr(impact_service, "newly_failed_in_run", lambda *_a, **_k: computed.append(1) or [])
    _, key = make_key(project_id=1)
    run_id = upload(client, key, [("pays", "failed")])
    assert (impact_service.evaluate_run, run_id) in [(func, args[-1]) for func, args in queued]
    assert computed == [] and stored(db, run_id).evaluated_at is None  # queued, never run inside the request


def test_a_truncated_change_list_is_still_scored(client, db, make_key):
    _, key = make_key(project_id=1)
    started = hours_ago(0.1)
    body = {"run": {"ci_provider": "local", "branch": "main", "started_at": started.isoformat(),
                    "finished_at": (started + timedelta(seconds=30)).isoformat()},
            "results": [{"suite": "s", "class_name": "C", "name": "pays", "status": "passed", "duration_ms": 5}],
            "changes": {"base_ref": "origin/main", "truncated": True,
                        "files": [{"path": "src/a.py", "status": "M", "additions": 1, "deletions": 0}]}}
    response = client.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 201
    assert stored(db, response.json()["id"]) is not None


def test_the_nightly_pass_writes_an_outcome_the_response_never_wrote(client, db, make_key, seed_change_run,
                                                                      monkeypatch):
    from src.ingestion.jobs import impact_rollup

    seed_change_run(hours_ago(3), results=(("pays", "passed", 5),))
    monkeypatch.setattr(impact_service, "evaluate_run", lambda *_args: None)  # the process stopped after the response
    _, key = make_key(project_id=1)
    late, recent = upload(client, key, [("pays", "failed")]), upload(client, key, [("pays", "failed")])
    db.get(RunImpact, late).scored_at = hours_ago(0.6)
    db.get(RunImpact, recent).scored_at = hours_ago(0.4)  # under 30 minutes: the response's step may still come
    db.commit()
    assert impact_rollup.run_pass(db)["outcomes"] == 1
    row = stored(db, late)
    assert row.evaluated_at is not None and row.caught == [] and [t["name"] for t in row.missed] == ["pays"]
    assert stored(db, recent).evaluated_at is None


def test_an_outcome_is_written_once(client, db, make_key, seed_change_run, monkeypatch):
    """The background step and the nightly pass can both reach a run: the first outcome stays."""
    from sqlalchemy.orm import sessionmaker

    seed_change_run(hours_ago(3), results=(("pays", "passed", 5),))
    monkeypatch.setattr(impact_service, "evaluate_run", lambda *_args: None)
    _, key = make_key(project_id=1)
    run_id = upload(client, key, [("pays", "failed")])
    factory = sessionmaker(bind=db.get_bind())
    real = impact_service.newly_failed_in_run

    def raced(session, run, excluded):
        monkeypatch.setattr(impact_service, "newly_failed_in_run", real)
        with factory() as other:  # another evaluation finishes first, while this one is computing
            assert impact_service.evaluate(other, run.id, hours_ago(0.01)) is True
        return real(session, run, excluded)

    monkeypatch.setattr(impact_service, "newly_failed_in_run", raced)
    with factory() as session:
        assert impact_service.evaluate(session, run_id, datetime.now(timezone.utc)) is False
    first = stored(db, run_id).evaluated_at
    with factory() as session:
        assert impact_service.evaluate(session, run_id, datetime.now(timezone.utc)) is False
    assert stored(db, run_id).evaluated_at == first


def test_no_history_rows_are_read_only_as_far_as_the_label_can_list(db):
    from src.ingestion.analytics.impact_rules import MAX_PER_LABEL

    db.add_all([base_row(f"n{i:03d}", runs=1) for i in range(MAX_PER_LABEL * 3)])
    db.add_all([pair_row("src/pay/", "n250"), pair_row("src/pay/", "n251")])
    db.commit()
    _, bases = impact_service.load_statistics(db, 1, set(), ChangedFiles([]))
    assert sorted(b.test.name for b in bases.values()) == [f"n{i:03d}" for i in range(MAX_PER_LABEL)]
    # two pair tests may be listed first, as statistical: two more rows, and the pair tests themselves
    _, bases = impact_service.load_statistics(db, 1, change_units(["src/pay/a.py"]), ChangedFiles([]), failing=3)
    assert len(bases) == MAX_PER_LABEL + 2 + 3 + 2


def test_failing_on_branch_reads_the_last_attempt(db, seed_run):
    seed_run(hours_ago(2), results=(("flip", "failed", 5), ("flip", "passed", 5), ("bad", "errored", 5),
                                    ("late", "passed", 5), ("late", "failed", 5), ("fine", "passed", 5)))
    names = [t.name for t in impact_service.failing_on_branch(db, 1, "main", hours_ago(1))]
    assert names == ["bad", "late"]


class _FakeSession:
    """Records what score_upload sends, as PostgreSQL would receive it."""

    def __init__(self, log):
        self.log = log
        self.dialect = type("Dialect", (), {"name": "postgresql"})()

    def get_bind(self):
        return self

    def execute(self, statement, params=None):
        self.log.append((str(statement), params))
        return type("Result", (), {"scalar_one": lambda _self: "30s"})()

    def rollback(self):
        self.log.append(("rollback", None))


def test_scoring_runs_under_a_statement_timeout_on_postgresql_and_restores_it(monkeypatch):
    log = []
    monkeypatch.setattr(impact_service, "monotonic", lambda: 0.0)
    monkeypatch.setattr(impact_service, "score_change", lambda *_a, **_k: log.append(("score", None)) or {"tests": []})
    assert impact_service.score_upload(_FakeSession(log), 1, ["a.py"], "main", hours_ago(0)) is not None
    assert [entry for entry, _ in log] == [
        "SELECT current_setting('statement_timeout')", "SET LOCAL statement_timeout = '2000ms'", "score",
        "SELECT set_config('statement_timeout', :value, true)"]
    assert log[-1][1] == {"value": "30s"}


def test_a_scoring_timeout_rolls_back_and_the_upload_carries_on(monkeypatch, capsys):
    class QueryCanceled(Exception):
        pass

    def timed_out(*_args, **_kwargs):
        raise QueryCanceled()

    log = []
    monkeypatch.setattr(impact_service, "score_change", timed_out)
    assert impact_service.score_upload(_FakeSession(log), 1, ["a.py"], "main", hours_ago(0)) is None
    assert log[-1][0] == "rollback"  # which also undoes SET LOCAL
    assert '"error": "QueryCanceled"' in capsys.readouterr().err


def test_a_budget_used_up_between_statements_leaves_the_upload_without_a_suggestion(client, db, make_key, monkeypatch,
                                                                                    capsys):
    """One total budget: the clock passes 2 s after the first statements, so scoring gives up though no single
    statement was slow. The upload still succeeds."""
    ticks = iter([0.0, 0.0, 0.1] + [5.0] * 100)
    monkeypatch.setattr(impact_service, "monotonic", lambda: next(ticks))
    _, key = make_key(project_id=1)
    run_id = upload(client, key, [("pays", "failed")])
    assert db.get(Run, run_id) is not None
    assert stored(db, run_id) is None
    assert '"error": "ScoringTimeout"' in capsys.readouterr().err
