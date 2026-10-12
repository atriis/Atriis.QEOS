"""Test impact scoring (spec 2026-10-12 §3.3, §3.4, §9; plan Rulings 1, 2): a change scored against the stored
statistics; an upload's suggestion scored before its run row or results exist and stored with the run; the outcome
written after the response from the stored results (and, for a suggestion whose outcome never came, by the nightly
impact-rollup pass). Neither step can fail an upload.

Scoring reads only what one change needs (the perf ruling): the impact_pairs rows of the change's unit hashes, the
impact_test_base rows of those pairs' tests and of tests whose recorded file contains a changed file's name, and the
first "no history yet" rows by name, as many as the label can list. Never the whole project's statistics."""
import json
import sys
from time import monotonic
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.analytics.impact_rules import (
    FAILING, MAX_PER_LABEL, MAX_STATISTICAL, MODEL_VERSION, NO_HISTORY_RUNS, WINDOW_DAYS, ChangedFiles, change_units,
    suffixes,
)
from src.ingestion.analytics.impact_score import BaseStat, ImpactTest, PairStat, suggest
from src.ingestion.analytics.trends import as_utc
from src.ingestion.models import Run, RunResult
from src.ingestion.models.impact import ImpactPair, ImpactTestBase, RunImpact, unit_hash
from src.ingestion.service.impact_history import newly_failed_in_run
from src.ingestion.service.impact_stats import live_excluded
from src.ingestion.service.report_service import in_list

NAMES_PER_QUERY = 200  # LIKE terms per query: SQLite's expression depth limit is 1,000
SCORING_BUDGET = 2.0  # seconds: one total budget for scoring a change (upload and POST /analytics/impact)
SCORING_TIMEOUT_MESSAGE = ("Scoring this change took longer than 2 seconds in total and was stopped. Try again in a moment, or "
                           "with fewer changed files.")
PENDING_AFTER = timedelta(minutes=30)  # a suggestion with no outcome this long after scoring is evaluated nightly
MAX_PENDING_PER_PASS = 500  # outcomes one nightly pass writes at most, oldest first; the rest wait for the next pass


def history_runs(db: Session, project_id: int, until: datetime) -> int:
    """Runs with changed files, not truncated, started in the 90 days before `until` ("not enough history" below 20)."""
    return db.execute(
        select(func.count()).select_from(Run).where(
            Run.project_id == project_id, Run.started_at >= until - timedelta(days=WINDOW_DAYS), Run.started_at < until,
            Run.changed_files > 0, or_(Run.changes_truncated.is_(None), Run.changes_truncated.is_(False)))
    ).scalar_one()


def failing_on_branch(db: Session, project_id: int, branch: Optional[str], before: datetime) -> List[ImpactTest]:
    """The failing tests of the branch's latest run started before `before`, by name. Only tests with a failing attempt
    in that run are read; of those, a test counts when its last non-skipped attempt (highest id) fails."""
    if branch is None:
        return []
    latest = db.execute(
        select(Run.id).where(Run.project_id == project_id, Run.branch == branch, Run.started_at < before)
        .order_by(Run.started_at.desc(), Run.id.desc()).limit(1)
    ).scalar()
    if latest is None:
        return []
    failed_keys = (select(RunResult.test_key)
                   .where(RunResult.run_id == latest, RunResult.status.in_(FAILING)).distinct())
    rows = db.execute(
        select(RunResult.test_key, RunResult.status, RunResult.suite, RunResult.class_name, RunResult.name)
        .where(RunResult.run_id == latest, RunResult.status != "skipped", RunResult.test_key.in_(failed_keys))
        .order_by(RunResult.id)
    ).all()
    last = {key: (status, ImpactTest(key, suite, class_name, name)) for key, status, suite, class_name, name in rows}
    return sorted((test for status, test in last.values() if status in FAILING), key=lambda t: (t.name, t.test_key))


_BASE_COLUMNS = (ImpactTestBase.test_key, ImpactTestBase.suite, ImpactTestBase.class_name, ImpactTestBase.name,
                 ImpactTestBase.runs, ImpactTestBase.new_failures, ImpactTestBase.file, ImpactTestBase.flaky)


def _like_contains(name: str) -> str:
    escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _file_names(changed_files: ChangedFiles) -> List[str]:
    """The changed files' last segments. A test's recorded file can only match a changed path ("test file changed")
    when it contains that path's file name, so these narrow the read; scoring's own check decides."""
    return sorted({suffixes(path)[-1] for path in changed_files.paths if suffixes(path)})


def _base_stat(row) -> BaseStat:
    key, suite, class_name, name, runs, new_failures, file, flaky = row
    return BaseStat(ImpactTest(key, suite, class_name, name), runs, new_failures, file, bool(flaky))


def _by_name(db: Session, column):
    """Ordered as Python orders str (code points): PostgreSQL's "C" collation; SQLite's default already is."""
    return column.collate("C") if db.get_bind().dialect.name == "postgresql" else column


def load_statistics(db: Session, project_id: int, units: Set[str], changed_files: Optional[ChangedFiles] = None,
                    failing: int = 0, deadline: Optional["Deadline"] = None
                    ) -> Tuple[List[PairStat], Dict[str, BaseStat]]:
    """The rows one scoring reads: the pairs of the change's units (by unit hash, the key's leading columns), their
    tests' base rows, the base rows whose recorded file contains a changed file's name, and the first "no history yet"
    rows by (name, test_key). `failing` is the number of tests failing on the branch.

    "No history yet" lists at most MAX_PER_LABEL tests that no earlier label listed, by (name, test_key); at most
    `listed` tests come before it (statistical, test file changed, failing on this branch), so the first
    MAX_PER_LABEL + listed rows in that order hold every one it can list."""
    def step() -> None:
        if deadline is not None:
            deadline.step(db)

    pairs: List[PairStat] = []
    if units:
        step()
        hashes = sorted({unit_hash(unit) for unit in units})
        pairs = [PairStat(*row) for row in db.execute(
            select(ImpactPair.path_unit, ImpactPair.test_key, ImpactPair.changed_runs, ImpactPair.new_failures)
            .where(ImpactPair.project_id == project_id, in_list(db, ImpactPair.unit_hash, hashes))
            .order_by(ImpactPair.unit_hash, ImpactPair.test_key))]
    bases: Dict[str, BaseStat] = {}
    keys = sorted({pair.test_key for pair in pairs})
    if keys:
        step()
        for row in db.execute(select(*_BASE_COLUMNS).where(ImpactTestBase.project_id == project_id,
                                                           in_list(db, ImpactTestBase.test_key, keys))):
            bases[row[0]] = _base_stat(row)
    names = _file_names(changed_files) if changed_files is not None else []
    for start in range(0, len(names), NAMES_PER_QUERY):
        terms = [ImpactTestBase.file.like(_like_contains(name), escape="\\")
                 for name in names[start:start + NAMES_PER_QUERY]]
        step()
        for row in db.execute(select(*_BASE_COLUMNS).where(ImpactTestBase.project_id == project_id, or_(*terms))):
            bases[row[0]] = _base_stat(row)
    touched = sum(1 for base in bases.values() if changed_files is not None and changed_files.touches(base.file))
    listed = min(MAX_STATISTICAL, len(keys)) + min(MAX_PER_LABEL, touched) + min(MAX_PER_LABEL, failing)
    step()
    for row in db.execute(
            select(*_BASE_COLUMNS)
            .where(ImpactTestBase.project_id == project_id, ImpactTestBase.runs < NO_HISTORY_RUNS)
            .order_by(_by_name(db, ImpactTestBase.name), _by_name(db, ImpactTestBase.test_key))
            .limit(MAX_PER_LABEL + listed)):
        bases.setdefault(row[0], _base_stat(row))
    return pairs, bases


# (units, changed files, tests failing on the branch) -> (pairs, base rows by test key): where the statistics come from
Statistics = Callable[[Set[str], ChangedFiles, int], Tuple[Sequence[PairStat], Mapping[str, BaseStat]]]


def score_change(db: Session, project_id: int, changed_paths: Sequence[str], branch: Optional[str], *,
                 now: datetime, statistics: Optional[Statistics] = None, deadline: Optional["Deadline"] = None) -> dict:
    """The suggestion for a change as of `now` (spec §3.3), from the stored statistics, or from `statistics` (replay,
    whose statistics are those of the days before the run): one scoring for live and replay."""
    units = change_units(changed_paths)
    changed_files = ChangedFiles(changed_paths)
    if deadline is not None:
        deadline.step(db)
    failing = failing_on_branch(db, project_id, branch, now)
    if statistics is None:
        pairs, bases = load_statistics(db, project_id, units, changed_files, failing=len(failing), deadline=deadline)
    else:
        pairs, bases = statistics(units, changed_files, len(failing))
    if deadline is not None:
        deadline.step(db)
    return suggest(units, pairs, bases, history_runs=history_runs(db, project_id, now), changed_files=changed_files,
                   failing_on_branch=failing)


class ScoringTimeout(Exception):
    """The scoring's total budget is used up (the same outcome as PostgreSQL cancelling a statement)."""


def limit_scoring_time(db: Session, remaining: float = SCORING_BUDGET) -> None:
    """Every statement of this transaction is cancelled after `remaining` seconds, at least 1 ms (PostgreSQL only;
    SET LOCAL ends with the transaction)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = '{max(1, int(remaining * 1000))}ms'"))


class Deadline:
    """One total budget for the whole scoring: `step` before each statement (or batch) raises ScoringTimeout once the
    budget is used up, and otherwise caps the next statement's statement_timeout at what is left."""

    def __init__(self, budget: float = SCORING_BUDGET):
        self.budget = budget
        self.started = monotonic()

    def remaining(self) -> float:
        return self.budget - (monotonic() - self.started)

    def step(self, db: Session) -> None:
        remaining = self.remaining()
        if remaining <= 0:
            raise ScoringTimeout()
        limit_scoring_time(db, remaining)


@dataclass(frozen=True)
class Scored:
    suggestion: dict
    scored_at: datetime


def _failed(step: str, exc: Exception, **context) -> None:
    # The exception type only: a message could carry data from the upload
    print(json.dumps({"event": "impact_failed", "step": step, **context, "error": type(exc).__name__}),
          file=sys.stderr, flush=True)


def score_upload(db: Session, project_id: int, changed_paths: Sequence[str], branch: Optional[str],
                 started_at: datetime) -> Optional[Scored]:
    """An upload's suggestion, scored before its run row or any of its results exists (spec §3.4), as of the run's
    start. One total budget of SCORING_BUDGET for the whole scoring (on PostgreSQL each statement is capped at what is
    left), and the previous timeout is restored for the rest of the
    upload. Never raises: on failure (a timeout too) the upload carries on without one. The rollback (a failed
    statement aborts a PostgreSQL transaction; it also undoes SET LOCAL) loses nothing, because nothing of the upload is
    written yet."""
    if not changed_paths:
        return None
    try:
        limited = db.get_bind().dialect.name == "postgresql"
        if limited:
            previous = db.execute(text("SELECT current_setting('statement_timeout')")).scalar_one()
        deadline = Deadline()
        deadline.step(db)
        suggestion = score_change(db, project_id, changed_paths, branch, now=as_utc(started_at), deadline=deadline)
        if limited:
            db.execute(text("SELECT set_config('statement_timeout', :value, true)"), {"value": previous})
        return Scored(suggestion, datetime.now(timezone.utc))
    except Exception as exc:
        db.rollback()
        _failed("score", exc, project_id=project_id)
        return None


def stored_suggestion(run_id: int, scored: Scored, *, replayed: bool) -> RunImpact:
    return RunImpact(run_id=run_id, suggested=scored.suggestion, model_version=MODEL_VERSION, replayed=replayed,
                     scored_at=scored.scored_at)


def outcome(suggested: dict, newly: Sequence[ImpactTest]) -> Tuple[List[dict], List[dict]]:
    """(caught, missed): the new failures the suggestion named, in any kind, and the others."""
    named = {test["test_key"] for test in suggested["tests"]}
    return ([t.out() for t in newly if t.test_key in named], [t.out() for t in newly if t.test_key not in named])


def record_outcome(db: Session, run_id: int, suggested: dict, newly: Sequence[ImpactTest], now: datetime) -> bool:
    """Write the outcome unless one is already there (one UPDATE ... WHERE evaluated_at IS NULL, so a second
    evaluation, the background task's and the nightly pass's, is a no-op). True when this call wrote it."""
    caught, missed = outcome(suggested, newly)
    written = db.execute(
        update(RunImpact).where(RunImpact.run_id == run_id, RunImpact.evaluated_at.is_(None))
        .values(caught=caught, missed=missed, evaluated_at=now)
        .execution_options(synchronize_session=False)
    )
    return written.rowcount == 1


def evaluate(db: Session, run_id: int, now: datetime) -> bool:
    """The run's new failures against its stored suggestion, committed. True when this call wrote the outcome."""
    row, run = db.get(RunImpact, run_id), db.get(Run, run_id)
    if row is None or run is None or row.evaluated_at is not None:
        return False
    suggested, excluded = row.suggested, live_excluded(db, run.project_id)
    written = record_outcome(db, run_id, suggested, newly_failed_in_run(db, run, excluded), now)
    db.commit()
    return written


def evaluate_run(session_factory: sessionmaker, run_id: int) -> None:
    """After the upload's response. Never raises; on failure the outcome stays empty (evaluated_at null) until the
    nightly pass evaluates it."""
    try:
        with session_factory() as db:
            evaluate(db, run_id, datetime.now(timezone.utc))
    except Exception as exc:
        _failed("outcome", exc, run_id=run_id)


def evaluate_pending(db: Session, now: datetime) -> int:
    """The impact-rollup pass: the outcome of every suggestion still without one PENDING_AFTER after scoring (the
    process stopped after the response, or the background step failed). One run at a time, oldest first, at most
    MAX_PENDING_PER_PASS (a backlog is worked off over several passes, never one unbounded pass); a run that fails is
    logged and left for the next pass. Returns the outcomes written."""
    run_ids = [run_id for (run_id,) in db.execute(
        select(RunImpact.run_id).where(RunImpact.evaluated_at.is_(None), RunImpact.scored_at < now - PENDING_AFTER)
        .order_by(RunImpact.scored_at, RunImpact.run_id).limit(MAX_PENDING_PER_PASS))]
    written = 0
    for run_id in run_ids:
        try:
            written += evaluate(db, run_id, now)
        except Exception as exc:
            db.rollback()
            _failed("outcome", exc, run_id=run_id)
    return written
