from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ingestion.analytics.signature import headline, signature
from src.ingestion.models import LogPattern, LogValue, MutedTest, Run, RunChangedFile, RunComponent, RunResult
from src.ingestion.service.analytics_service import _escape_like


@dataclass(frozen=True)
class RunFilters:
    branch: Optional[str] = None
    branch_contains: Optional[str] = None  # substring, case-insensitive
    # failing: at least one failed or errored result; passing: none
    status: Optional[Literal["failing", "passing"]] = None
    environment: Optional[str] = None
    ci_provider: Optional[str] = None
    commit: Optional[str] = None  # hex prefix, any case
    pr: Optional[int] = None
    author: Optional[str] = None  # substring, case-insensitive
    since: Optional[datetime] = None  # started_at >= since
    until: Optional[datetime] = None  # started_at < until
    scope: Optional[str] = None  # one of SCOPES; "full" hides runs of only the suggested tests
    # Log values (spec 2026-10-15 §3.1): runs with a result holding exactly `value`, under `pattern` when given
    value: Optional[str] = None
    pattern: Optional[str] = None


PATTERN_NAME = r"^[a-z][a-z0-9_]{0,31}$"


def _value_rows(value: str, pattern: Optional[str]):
    """The log_values rows of the enclosing RunResult that hold `value` (and `pattern`): an EXISTS, correlated to
    RunResult. Patterns belong to projects, so another project's values never match a project's runs."""
    rows = (
        select(LogValue.id)
        .join(LogPattern, LogPattern.id == LogValue.pattern_id)
        .where(LogValue.result_id == RunResult.id, LogValue.value == value)
    )
    if pattern is not None:
        rows = rows.where(LogPattern.name == pattern)
    return rows.correlate(RunResult).exists()


def list_runs(db: Session, project_id: int, limit: int, offset: int, filters: RunFilters = RunFilters()) -> list[Run]:
    query = db.query(Run).filter(Run.project_id == project_id)
    f = filters
    if f.branch is not None:
        query = query.filter(Run.branch == f.branch)
    if f.branch_contains is not None:
        query = query.filter(Run.branch.ilike(f"%{_escape_like(f.branch_contains)}%", escape="\\"))
    if f.status == "failing":
        query = query.filter((Run.failed + Run.errored) > 0)
    elif f.status == "passing":
        query = query.filter(Run.failed == 0, Run.errored == 0)
    if f.environment is not None:
        query = query.filter(Run.environment == f.environment)
    if f.ci_provider is not None:
        query = query.filter(Run.ci_provider == f.ci_provider)
    if f.commit is not None:
        query = query.filter(func.lower(Run.commit_sha).like(f"{f.commit.lower()}%"))
    if f.pr is not None:
        query = query.filter(Run.pr_number == f.pr)
    if f.author is not None:
        query = query.filter(Run.commit_author.ilike(f"%{_escape_like(f.author)}%", escape="\\"))
    if f.since is not None:
        query = query.filter(Run.started_at >= f.since)
    if f.until is not None:
        query = query.filter(Run.started_at < f.until)
    if f.scope is not None:
        query = query.filter(Run.scope == f.scope)
    if f.value is not None:
        holders = select(RunResult.id).where(RunResult.run_id == Run.id, _value_rows(f.value, f.pattern))
        query = query.filter(holders.correlate(Run).exists())
    return query.order_by(Run.created_at.desc(), Run.id.desc()).offset(offset).limit(limit).all()


def get_run(db: Session, run_id: int) -> Optional[Run]:
    return db.get(Run, run_id)


def list_results(db: Session, run_id: int, status: Optional[str], value: Optional[str] = None,
                 pattern: Optional[str] = None) -> list[RunResult]:
    query = db.query(RunResult).filter(RunResult.run_id == run_id)
    if status is not None:
        query = query.filter(RunResult.status == status)
    if value is not None:  # only the rows holding this log value (spec 2026-10-15 §3.1)
        query = query.filter(_value_rows(value, pattern))
    return query.order_by(RunResult.id).all()


def result_log(db: Session, run_id: int, result_id: int) -> tuple[bool, Optional[str]]:
    """(found, log): one result's stored, masked log, read as a column (it is deferred on the model, and the run
    payload never carries it). Not found when the result is not in that run."""
    row = db.execute(
        select(RunResult.log).where(RunResult.id == result_id, RunResult.run_id == run_id)
    ).one_or_none()
    return (False, None) if row is None else (True, row[0])


def result_in_run(db: Session, run_id: int, result_id: int) -> bool:
    """Whether the result is in that run, by id alone (no log column read)."""
    return db.execute(
        select(RunResult.id).where(RunResult.id == result_id, RunResult.run_id == run_id)
    ).first() is not None


def quarantined_failures(db: Session, run: Run) -> set:
    """test_keys of the run's failed or errored tests that are quarantined (muted) in its project.
    Quarantined tests still run and are still shown; their failures just do not count."""
    if run.failed + run.errored == 0:
        return set()
    rows = (
        db.query(RunResult.test_key).distinct()
        .join(MutedTest, (MutedTest.test_key == RunResult.test_key) & (MutedTest.project_id == run.project_id))
        .filter(RunResult.run_id == run.id, RunResult.status.in_(("failed", "errored"))).all()
    )
    return {r.test_key for r in rows}


def quarantine_counts(db: Session, run: Run, keys: Optional[set] = None) -> dict:
    """Failing results in quarantine, and the failing results that still count."""
    keys = quarantined_failures(db, run) if keys is None else keys
    quarantined = 0
    if keys:
        quarantined = (
            db.query(RunResult.id)
            .filter(RunResult.run_id == run.id, RunResult.status.in_(("failed", "errored")),
                    RunResult.test_key.in_(keys)).count()
        )
    return {"quarantined": quarantined, "blocking": run.failed + run.errored - quarantined}


MAX_GROUP_TESTS = 100
HISTORY_RUNS = 20


def _history_window(db: Session, run: Run) -> list:
    """This run and up to HISTORY_RUNS - 1 earlier runs of the same project and branch, newest first."""
    branch = Run.branch.is_(None) if run.branch is None else Run.branch == run.branch
    earlier = (
        db.query(Run.id, Run.started_at)
        .filter(Run.project_id == run.project_id, branch,
                (Run.started_at < run.started_at) | ((Run.started_at == run.started_at) & (Run.id < run.id)))
        .order_by(Run.started_at.desc(), Run.id.desc()).limit(HISTORY_RUNS - 1).all()
    )
    return [(run.id, run.started_at)] + [(r.id, r.started_at) for r in earlier]


def _signatures_by_run(db: Session, run_ids: list) -> dict:
    found: dict = {rid: set() for rid in run_ids}
    rows = (
        db.query(RunResult.run_id, RunResult.message)
        .filter(RunResult.run_id.in_(run_ids), RunResult.status.in_(("failed", "errored"))).all()
    )
    for r in rows:
        found[r.run_id].add(signature(r.message))
    return found


def failure_groups(db: Session, run: Run) -> dict:
    """The run's failed and errored tests grouped by cause, biggest group first, each with its
    history on the run's branch."""
    run_id = run.id
    quarantined = quarantined_failures(db, run)
    rows = (
        db.query(RunResult.id, RunResult.test_key, RunResult.suite, RunResult.class_name, RunResult.name,
                 RunResult.status, RunResult.message)
        .filter(RunResult.run_id == run_id, RunResult.status.in_(("failed", "errored")))
        .order_by(RunResult.id).all()
    )
    groups: dict = {}
    for r in rows:
        key = signature(r.message)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"signature": key, "headline": headline(r.message), "count": 0, "failed": 0,
                               "errored": 0, "quarantined": 0, "tests": [], "first": r.id}
        g["count"] += 1
        g[r.status] += 1
        in_quarantine = r.test_key in quarantined
        g["quarantined"] += in_quarantine
        if len(g["tests"]) < MAX_GROUP_TESTS:
            g["tests"].append({"id": r.id, "test_key": r.test_key, "suite": r.suite, "class_name": r.class_name,
                               "name": r.name, "status": r.status, "quarantined": in_quarantine})
    ordered = sorted(groups.values(), key=lambda g: (-g["count"], g["signature"] == "none", g["first"]))
    window = _history_window(db, run) if ordered else []
    seen = _signatures_by_run(db, [rid for rid, _ in window]) if ordered else {}
    for g in ordered:
        del g["first"]
        hits = [g["signature"] in seen[rid] for rid, _ in window]
        streak = hits.index(False) if False in hits else len(hits)
        since_id, since_at = window[streak - 1]
        g["history"] = {"window": len(window), "seen_in": sum(hits), "streak": streak,
                        "since_run_id": since_id, "since_started_at": since_at}
    held = sum(g["quarantined"] for g in ordered)
    return {"total": len(rows), "quarantined": held, "blocking": len(rows) - held, "groups": ordered}


MAX_COMPARE_ITEMS = 200
FAILING_STATUSES = ("failed", "errored")
# A test is "slower" when it took at least this much longer, and at least SLOWER_RATIO times as long
SLOWER_MIN_MS = 1000
SLOWER_RATIO = 1.5


def _last_attempts(db: Session, run_id: int) -> dict:
    rows = (
        db.query(RunResult.test_key, RunResult.suite, RunResult.class_name, RunResult.name, RunResult.status,
                 RunResult.duration_ms, RunResult.message)
        .filter(RunResult.run_id == run_id).order_by(RunResult.id).all()
    )
    return {r.test_key: r for r in rows}  # later rows win: a retry's outcome replaces the first attempt's


def compare_runs(db: Session, base: Run, head: Run) -> dict:
    before, after = _last_attempts(db, base.id), _last_attempts(db, head.id)
    lists: dict = {k: [] for k in ("new_failures", "fixed", "still_failing", "slower", "added", "removed")}
    unchanged = 0

    def item(key):
        b, h = before.get(key), after.get(key)
        any_row = h or b
        failing = h if h is not None and h.status in FAILING_STATUSES else b
        return {"test_key": key, "suite": any_row.suite, "class_name": any_row.class_name, "name": any_row.name,
                "base_status": b.status if b else None, "head_status": h.status if h else None,
                "base_duration_ms": b.duration_ms if b else None, "head_duration_ms": h.duration_ms if h else None,
                "message": headline(failing.message) if failing is not None else None}

    for key in after.keys() | before.keys():
        b, h = before.get(key), after.get(key)
        if b is None:
            lists["added"].append(item(key))
        elif h is None:
            lists["removed"].append(item(key))
        elif h.status in FAILING_STATUSES and b.status == "passed":
            lists["new_failures"].append(item(key))
        elif b.status in FAILING_STATUSES and h.status == "passed":
            lists["fixed"].append(item(key))
        elif b.status in FAILING_STATUSES and h.status in FAILING_STATUSES:
            lists["still_failing"].append(item(key))
        elif (b.status == h.status == "passed" and h.duration_ms - b.duration_ms >= SLOWER_MIN_MS
              and h.duration_ms >= SLOWER_RATIO * b.duration_ms):
            lists["slower"].append(item(key))
        else:
            unchanged += 1

    for name, values in lists.items():
        if name == "slower":
            values.sort(key=lambda i: (i["base_duration_ms"] - i["head_duration_ms"], i["name"]))
        else:
            values.sort(key=lambda i: (i["suite"], i["class_name"], i["name"]))
    counts = {name: len(values) for name, values in lists.items()}
    counts["unchanged"] = unchanged
    return {"base": base, "head": head, "counts": counts,
            **{name: values[:MAX_COMPARE_ITEMS] for name, values in lists.items()}}


def list_changes(db: Session, run_id: int) -> list[RunChangedFile]:
    return db.query(RunChangedFile).filter(RunChangedFile.run_id == run_id).order_by(RunChangedFile.id).all()


def list_components(db: Session, run_id: int) -> list[RunComponent]:
    return db.query(RunComponent).filter(RunComponent.run_id == run_id).order_by(RunComponent.id).all()
