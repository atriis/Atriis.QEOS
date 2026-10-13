"""Database queries for the analytics endpoints. Counting stays in SQL; the ranking and day
grouping live in src/ingestion/analytics."""
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session, aliased

from src.ingestion.analytics.flaky import FlipCount, LatestExecution, MixedCommit
from src.ingestion.analytics.trends import RunRow, as_utc, pass_rate
from src.ingestion.models import MutedTest, Run, RunResult


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


def failed_step_of(status, message, details, step_text, step_line) -> Optional[dict]:
    """The failed step for a failed/errored result (spec 2026-10-13 §3.3). Rows stored before the collector
    sent `failed_step` hold the step on details' first line, unless that line is just the message."""
    if status not in ("failed", "errored"):
        return None
    if step_text:
        return {"text": step_text, **({"line": step_line} if step_line else {})}
    first = (details or "").split("\n", 1)[0].strip()
    if first and first != (message or "").split("\n", 1)[0].strip():
        return {"text": first}
    return None


def latest_results(db: Session, project_id: int, keys: List[str]) -> dict:
    keys = sorted({k.lower() for k in keys})
    ranked = _latest_ranked(
        [Run.project_id == project_id, RunResult.test_key.in_(keys)],
        RunResult.status, RunResult.message, RunResult.details, RunResult.failed_step_text,
        RunResult.failed_step_line, Run.id.label("run_id"), Run.branch, Run.environment, Run.started_at,
    )
    out = {}
    for r in db.execute(select(ranked).where(ranked.c.position == 1)).mappings():
        entry = {"status": r["status"], "run_id": r["run_id"], "branch": r["branch"],
                 "environment": r["environment"], "started_at": as_utc(r["started_at"]), "message": r["message"]}
        step = failed_step_of(r["status"], r["message"], r["details"], r["failed_step_text"], r["failed_step_line"])
        if step:
            entry["failed_step"] = step
        out[r["test_key"]] = entry
    return out


def latest_keys(db: Session, project_id: int, status: str, branch: Optional[str] = None) -> List[str]:
    """Test keys whose most recent result (by run start) has `status`; failed includes errored.
    `any`: every test with at least one result. Used by the dashboard's latest-result case filter."""
    filters = [Run.project_id == project_id]
    if branch:
        filters.append(Run.branch == branch)
    if status == "any":
        rows = db.execute(select(RunResult.test_key).distinct().join(Run, Run.id == RunResult.run_id).where(*filters))
        return sorted(k for (k,) in rows)
    ranked = _latest_ranked(filters, RunResult.status)
    wanted = ("failed", "errored") if status == "failed" else (status,)
    rows = db.execute(select(ranked.c.test_key).where(ranked.c.position == 1, ranked.c.status.in_(wanted)))
    return sorted(k for (k,) in rows)


def run_strip(db: Session, project_id: int, keys: List[str], limit: int = 10,
              branch: Optional[str] = None) -> dict:
    """Each test's status in the project's last `limit` runs, oldest to newest (Cases 'Last runs').
    More than one result row for a test in a run is a re-run; errored counts as failed."""
    filters = [Run.project_id == project_id]
    if branch:
        filters.append(Run.branch == branch)
    recent = db.execute(
        select(Run.id, Run.started_at, Run.branch).where(*filters)
        .order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
    ).all()
    recent = list(reversed(recent))
    keys = sorted({k.lower() for k in keys})
    statuses = {k: [None] * len(recent) for k in keys}
    if recent and keys:
        position = {run.id: i for i, run in enumerate(recent)}
        rows = db.execute(
            select(RunResult.run_id, RunResult.test_key, func.count(RunResult.id), func.max(RunResult.status))
            .where(RunResult.run_id.in_(list(position)), RunResult.test_key.in_(keys))
            .group_by(RunResult.run_id, RunResult.test_key)
        ).all()
        for run_id, key, count, status in rows:
            if count > 1:
                value = "rerun"
            else:
                value = "failed" if status in ("failed", "errored") else status
            statuses[key][position[run_id]] = value
    return {"runs": [{"id": r.id, "started_at": r.started_at, "branch": r.branch} for r in recent],
            "statuses": statuses}
