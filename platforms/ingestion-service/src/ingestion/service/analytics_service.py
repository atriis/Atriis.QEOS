"""Database queries for the analytics endpoints. Counting stays in SQL; the ranking and day
grouping live in src/ingestion/analytics."""
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session, aliased

from src.ingestion.analytics.failed_steps import step_key
from src.ingestion.analytics.flaky import FlipCount, LatestExecution, MixedCommit
from src.ingestion.analytics.trends import RunRow, as_utc, pass_rate
from src.ingestion.models import MutedTest, Run, RunResult
from src.ingestion.service import log_value_service, screenshot_read


def _count(*statuses: str):
    return func.sum(case((RunResult.status.in_(statuses), 1), else_=0))


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def window_filters(project_id: int, since: datetime, branch: Optional[str] = None) -> list:
    filters = [Run.project_id == project_id, Run.started_at >= since]
    if branch:  # an empty filter (?branch=) means no filter
        filters.append(Run.branch == branch)
    return filters


def trend_rows(db: Session, project_id: int, since: datetime, branch: Optional[str],
               environment: Optional[str]) -> List[RunRow]:
    query = db.query(Run.started_at, Run.total, Run.passed, Run.failed, Run.errored, Run.skipped,
                     Run.duration_ms).filter(*window_filters(project_id, since, branch))
    if environment:
        query = query.filter(Run.environment == environment)
    return [RunRow(*row) for row in query.all()]


def latest_executions(db: Session, filters: list, keys_clause) -> Dict[str, LatestExecution]:
    """The newest execution (started_at, then run id) of each test matching the filters."""
    ranked = (
        select(
            RunResult.test_key, RunResult.suite, RunResult.class_name, RunResult.name, RunResult.status,
            Run.started_at,
            func.row_number().over(
                partition_by=RunResult.test_key, order_by=(Run.started_at.desc(), Run.id.desc())
            ).label("position"),
        )
        .join(Run, Run.id == RunResult.run_id)
        .where(*filters, keys_clause)
    ).subquery()
    rows = db.execute(select(ranked).where(ranked.c.position == 1)).all()
    return {
        row.test_key: LatestExecution(row.test_key, row.suite, row.class_name, row.name, row.status,
                                      as_utc(row.started_at))
        for row in rows
    }


def list_tests(db: Session, project_id: int, since: datetime, *, sort: str, search: Optional[str],
               limit: int, offset: int) -> List[dict]:
    failures = _count("failed", "errored")
    average = func.avg(RunResult.duration_ms)
    name = func.max(RunResult.name)
    filters = window_filters(project_id, since)
    query = (
        db.query(
            RunResult.test_key, func.max(RunResult.suite), func.max(RunResult.class_name), name,
            func.count(RunResult.id), _count("passed"), _count("failed"), _count("errored"), _count("skipped"),
            average,
        )
        .join(Run, Run.id == RunResult.run_id)
        .filter(*filters)
        .group_by(RunResult.test_key)
    )
    if search:
        query = query.filter(RunResult.name.ilike(f"%{_escape_like(search)}%", escape="\\"))
    order = {"failures": failures.desc(), "duration": average.desc(), "name": name.asc()}[sort]
    rows = query.order_by(order, RunResult.test_key).offset(offset).limit(limit).all()

    latest = latest_executions(db, filters, RunResult.test_key.in_([row[0] for row in rows])) if rows else {}
    out = []
    for key, suite, class_name, test_name, runs, passed, failed, errored, skipped, avg in rows:
        last = latest[key]
        out.append({
            "test_key": key, "suite": suite, "class_name": class_name, "name": test_name,
            "runs": runs, "passed": int(passed), "failed": int(failed), "errored": int(errored),
            "skipped": int(skipped), "pass_rate": pass_rate(int(passed), runs, int(skipped)),
            "avg_duration_ms": round(float(avg)) if avg is not None else None,
            "last_status": last.status, "last_seen": last.started_at,
        })
    return out


MESSAGE_EXCERPT = 500


def test_seen(db: Session, project_id: int, test_key: str) -> bool:
    return db.query(RunResult.id).join(Run, Run.id == RunResult.run_id).filter(
        Run.project_id == project_id, RunResult.test_key == test_key
    ).first() is not None


test_seen.__test__ = False  # not a pytest test, despite the name


def test_history(db: Session, project_id: int, test_key: str, since: datetime, branch: Optional[str],
                 limit: int) -> dict:
    filters = window_filters(project_id, since, branch) + [RunResult.test_key == test_key]
    base = db.query(RunResult).join(Run, Run.id == RunResult.run_id).filter(*filters)
    rows = base.with_entities(
        Run.id, Run.started_at, Run.branch, Run.commit_sha, Run.environment, RunResult.status,
        RunResult.duration_ms, RunResult.message, RunResult.suite, RunResult.class_name, RunResult.name,
    ).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit).all()
    runs, passed, failed, errored, skipped, avg = base.with_entities(
        func.count(RunResult.id), _count("passed"), _count("failed"), _count("errored"), _count("skipped"),
        func.avg(RunResult.duration_ms),
    ).one()

    if rows:
        identity = rows[0][8:11]
    else:  # known test, nothing in the window: identity from its latest execution ever
        identity = db.query(RunResult.suite, RunResult.class_name, RunResult.name).join(
            Run, Run.id == RunResult.run_id
        ).filter(Run.project_id == project_id, RunResult.test_key == test_key).order_by(
            Run.started_at.desc(), Run.id.desc()
        ).first()
    passed, failed, errored, skipped = (int(v or 0) for v in (passed, failed, errored, skipped))
    return {
        "test_key": test_key, "suite": identity[0], "class_name": identity[1], "name": identity[2],
        "summary": {
            "runs": runs, "passed": passed, "failed": failed, "errored": errored, "skipped": skipped,
            "pass_rate": pass_rate(passed, runs, skipped),
            "avg_duration_ms": round(float(avg)) if avg is not None else None,
        },
        "executions": [
            {"run_id": run_id, "started_at": as_utc(started_at), "branch": run_branch, "commit_sha": commit_sha,
             "environment": environment, "status": status, "duration_ms": duration_ms,
             "message": message[:MESSAGE_EXCERPT] if message is not None else None}
            for run_id, started_at, run_branch, commit_sha, environment, status, duration_ms, message, *_ in rows
        ],
    }


test_history.__test__ = False  # not a pytest test, despite the name


def flaky_inputs(db: Session, project_id: int, since: datetime, branch: Optional[str]):
    """Per-test flip totals, mixed (commit, environment) groups, and latest executions, for the
    tests with at least one failure in the window. All counting happens in the database, in two
    passes over the window's results (measured: see the README's Analytics section)."""
    filters = window_filters(project_id, since, branch)
    candidates = select(RunResult.test_key).join(Run, Run.id == RunResult.run_id).where(
        *filters, RunResult.status.in_(("failed", "errored"))
    ).distinct()
    executions = filters + [RunResult.status != "skipped", RunResult.test_key.in_(candidates)]

    # Pass 1: flips per branch and the latest execution, from one scan
    outcome = case((RunResult.status == "passed", "pass"), else_="fail")
    sequence = (
        select(
            RunResult.test_key.label("test_key"),
            RunResult.suite.label("suite"),
            RunResult.class_name.label("class_name"),
            RunResult.name.label("name"),
            RunResult.status.label("status"),
            Run.started_at.label("started_at"),
            outcome.label("outcome"),
            func.lag(outcome).over(
                partition_by=(RunResult.test_key, Run.branch), order_by=(Run.started_at, Run.id)
            ).label("previous"),
            func.row_number().over(
                partition_by=RunResult.test_key, order_by=(Run.started_at.desc(), Run.id.desc())
            ).label("position"),
        )
        .join(Run, Run.id == RunResult.run_id)
        .where(*executions)
    ).subquery()
    has_previous = sequence.c.previous.is_not(None)
    newest = sequence.c.position == 1

    def at_newest(column):
        return func.max(case((newest, column)))

    rows = db.execute(
        select(
            sequence.c.test_key,
            func.count(),
            func.sum(case(((has_previous & (sequence.c.previous != sequence.c.outcome)), 1), else_=0)),
            func.sum(case((has_previous, 1), else_=0)),
            at_newest(sequence.c.suite), at_newest(sequence.c.class_name), at_newest(sequence.c.name),
            at_newest(sequence.c.status), at_newest(sequence.c.started_at),
        ).group_by(sequence.c.test_key)
    ).all()
    flips, latest = [], {}
    for key, runs, flipped, pairs, suite, class_name, name, status, started_at in rows:
        flips.append(FlipCount(key, runs, int(flipped or 0), int(pairs or 0)))
        latest[key] = LatestExecution(key, suite, class_name, name, status, as_utc(started_at))

    mixed = mixed_commits(db, project_id, since, branch)
    return flips, mixed, latest


def muted_keys(db: Session, project_id: int) -> set:
    rows = db.execute(select(MutedTest.test_key).where(MutedTest.project_id == project_id)).all()
    return {key for (key,) in rows}


def mute_test(db: Session, project_id: int, test_key: str, user_id: int) -> None:
    """Idempotent: muting an already-muted test is a no-op."""
    exists = db.execute(
        select(MutedTest.id).where(MutedTest.project_id == project_id, MutedTest.test_key == test_key)
    ).first()
    if exists:
        return
    db.add(MutedTest(project_id=project_id, test_key=test_key, muted_by_user_id=user_id))
    db.commit()


def unmute_test(db: Session, project_id: int, test_key: str) -> bool:
    row = db.execute(
        select(MutedTest).where(MutedTest.project_id == project_id, MutedTest.test_key == test_key)
    ).scalar_one_or_none()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def branch_stats(db: Session, project_id: int, since: datetime, limit: int) -> List[dict]:
    """Per-branch run aggregates in the window, most recently active first."""
    rows = db.execute(
        select(
            Run.branch,
            func.count(Run.id),
            func.sum(Run.total),
            func.sum(Run.passed),
            func.sum(Run.failed),
            func.sum(Run.errored),
            func.sum(Run.skipped),
            func.max(Run.started_at),
        )
        .where(Run.project_id == project_id, Run.started_at >= since)
        .group_by(Run.branch)
        .order_by(func.max(Run.started_at).desc())
        .limit(limit)
    ).all()
    return [
        {
            "branch": branch,
            "runs": runs,
            "total": int(total or 0),
            "passed": int(passed or 0),
            "failed": int(failed or 0),
            "errored": int(errored or 0),
            "skipped": int(skipped or 0),
            "pass_rate": pass_rate(int(passed or 0), int(total or 0), int(skipped or 0)),
            "last_seen": as_utc(seen),
        }
        for branch, runs, total, passed, failed, errored, skipped, seen in rows
    ]


def mixed_commits(db: Session, project_id: int, since: datetime, branch: Optional[str]) -> List[MixedCommit]:
    """Pass 2 of flaky detection, on its own: the rollup path reuses it, since
    it is failure-driven through the (test_key, run_id) index and stays fast
    at any window."""
    filters = window_filters(project_id, since, branch)
    # mixed outcomes per (commit, environment). Start from the failures -- a few percent of
    # the rows -- and ask, through the (test_key, run_id) index, whether another run of the same
    # commit and environment passed. Grouping every result by (test, commit, environment) instead
    # was the slowest part on large projects, and a duplicate inside one run is not a re-run.
    other_run, passing = aliased(Run), aliased(RunResult)
    passed_elsewhere = (
        select(literal(1))
        .select_from(passing)
        .join(other_run, other_run.id == passing.run_id)
        .where(
            passing.test_key == RunResult.test_key,
            passing.status == "passed",
            other_run.project_id == project_id,
            other_run.started_at >= since,
            other_run.commit_sha == Run.commit_sha,
            func.coalesce(other_run.environment, "") == func.coalesce(Run.environment, ""),
            other_run.id != Run.id,
            *([other_run.branch == branch] if branch else []),
        )
        .exists()
    )
    mixed_rows = db.execute(
        select(RunResult.test_key, Run.commit_sha, Run.environment, func.max(Run.started_at))
        .join(Run, Run.id == RunResult.run_id)
        .where(*filters, RunResult.status.in_(("failed", "errored")), Run.commit_sha.is_not(None), passed_elsewhere)
        .group_by(RunResult.test_key, Run.commit_sha, Run.environment)
    ).all()
    mixed = [MixedCommit(key, sha, env, as_utc(seen)) for key, sha, env, seen in mixed_rows]
    return mixed


def _latest_ranked(filters, *columns):
    """Each test's results ranked newest first (run start, run id, row id): position 1 is its latest."""
    return (
        select(RunResult.test_key, *columns,
               func.row_number().over(partition_by=RunResult.test_key,
                                      order_by=(Run.started_at.desc(), Run.id.desc(), RunResult.id.desc())).label("position"))
        .join(Run, Run.id == RunResult.run_id).where(*filters)
    ).subquery()


def failed_step_of(status, message, details, step_text, step_line, definition=None, pattern=None) -> Optional[dict]:
    """The failed step for a failed/errored result (spec 2026-10-13 §3.3), or the step a skipped scenario stopped at
    (undefined, pending, ambiguous or hook-skipped; collector 0.9.1 sends it as failed_step too). Failed/errored rows
    stored before the collector sent `failed_step` hold the step on details' first line, unless that line is just the
    message; a skipped row without a stored step has none. From collector 0.8.0 the step also has its definition and
    pattern; `key` names the step across test cases (spec 2026-10-14)."""
    if status not in ("failed", "errored", "skipped"):
        return None
    if step_text:
        step = {"text": step_text, **({"line": step_line} if step_line else {})}
    elif status == "skipped":
        return None
    else:
        first = (details or "").split("\n", 1)[0].strip()
        if not first or first == (message or "").split("\n", 1)[0].strip():
            return None
        step = {"text": first}
    if definition:
        step["definition"] = definition
    if pattern:
        step["pattern"] = pattern
    step["key"] = step_key(definition, step["text"])[0]
    return step


def run_in_project(db: Session, project_id: int, run_id: int) -> bool:
    return db.execute(select(Run.id).where(Run.id == run_id, Run.project_id == project_id)).first() is not None


def latest_results(db: Session, project_id: int, keys: List[str], run_id: Optional[int] = None) -> dict:
    """Each test's latest result, or with `run_id` its result in that run (a re-run's last row)."""
    keys = sorted({k.lower() for k in keys})
    filters = [Run.project_id == project_id, RunResult.test_key.in_(keys)]
    if run_id is not None:
        filters.append(Run.id == run_id)
    ranked = _latest_ranked(
        filters,
        RunResult.id.label("result_id"),
        RunResult.status, RunResult.message, RunResult.details, RunResult.failed_step_text,
        RunResult.failed_step_line, RunResult.failed_step_definition, RunResult.failed_step_pattern,
        Run.id.label("run_id"), Run.branch, Run.environment, Run.started_at,
    )
    rows = list(db.execute(select(ranked).where(ranked.c.position == 1)).mappings())
    values = log_value_service.values_by_result(db, [r["result_id"] for r in rows])
    steps = screenshot_read.steps_by_result(db, project_id, [r["result_id"] for r in rows])
    out = {}
    for r in rows:
        entry = {"status": r["status"], "run_id": r["run_id"], "result_id": r["result_id"], "branch": r["branch"],
                 "environment": r["environment"], "started_at": as_utc(r["started_at"]),
                 "message": r["message"][:MESSAGE_EXCERPT] if r["message"] is not None else None,
                 # Log values of this result (ADR-032), with each pattern's link template
                 "values": values.get(r["result_id"], [])}
        step = failed_step_of(r["status"], r["message"], r["details"], r["failed_step_text"], r["failed_step_line"],
                              r["failed_step_definition"], r["failed_step_pattern"])
        if step:
            entry["failed_step"] = step
        if r["result_id"] in steps:  # absent when the result has no screenshots (ADR-036)
            entry["screenshot_steps"] = steps[r["result_id"]]
        out[r["test_key"]] = entry
    return out


def latest_keys(db: Session, project_id: int, status: str, branch: Optional[str] = None,
                since: Optional[datetime] = None, until: Optional[datetime] = None) -> List[str]:
    """Test keys whose most recent result (by run start) has `status`; failed includes errored.
    `any`: every test with at least one result. With a period (`since` inclusive, `until` exclusive, on the run's
    start) only the results in it count, and "latest" is the latest within it. Used by the dashboard's
    latest-result and period case filters."""
    filters = [Run.project_id == project_id]
    if branch:
        filters.append(Run.branch == branch)
    if since is not None:
        filters.append(Run.started_at >= since)
    if until is not None:
        filters.append(Run.started_at < until)
    if status == "any":
        rows = db.execute(select(RunResult.test_key).distinct().join(Run, Run.id == RunResult.run_id).where(*filters))
        return sorted(k for (k,) in rows)
    ranked = _latest_ranked(filters, RunResult.status)
    wanted = ("failed", "errored") if status == "failed" else (status,)
    rows = db.execute(select(ranked.c.test_key).where(ranked.c.position == 1, ranked.c.status.in_(wanted)))
    return sorted(k for (k,) in rows)


def run_strip(db: Session, project_id: int, keys: List[str], limit: int = 10,
              branch: Optional[str] = None) -> dict:
    """Each test's own last `limit` results, oldest to newest (Cases 'Last runs'): only runs the test was in,
    so a run of another suite never shows as a gap. More than one result row for a test in a run is a re-run;
    errored counts as failed."""
    keys = sorted({k.lower() for k in keys})
    tests: Dict[str, list] = {k: [] for k in keys}
    filters = [Run.project_id == project_id, RunResult.test_key.in_(keys)]
    if branch:
        filters.append(Run.branch == branch)
    newest_first = func.row_number().over(
        partition_by=RunResult.test_key, order_by=(Run.started_at.desc(), Run.id.desc())).label("rank")
    per_run = (
        select(RunResult.test_key, Run.id.label("run_id"), Run.started_at, Run.branch,
               func.count(RunResult.id).label("count"), func.max(RunResult.status).label("status"), newest_first)
        .join(Run, Run.id == RunResult.run_id).where(*filters)
        .group_by(RunResult.test_key, Run.id, Run.started_at, Run.branch)
    ).subquery()
    rows = db.execute(
        select(per_run).where(per_run.c.rank <= limit)
        .order_by(per_run.c.test_key, per_run.c.started_at, per_run.c.run_id)
    ).all()
    # Log values per bar (ADR-032): the test's results in that run, merged per pattern
    values = log_value_service.values_by_test_run(db, keys, {row.run_id for row in rows})
    for row in rows:
        if row.count > 1:
            value = "rerun"
        else:
            value = "failed" if row.status in ("failed", "errored") else row.status
        tests[row.test_key].append({"run_id": row.run_id, "started_at": row.started_at, "branch": row.branch,
                                    "status": value, "values": values.get((row.test_key, row.run_id), [])})
    return {"tests": tests}
