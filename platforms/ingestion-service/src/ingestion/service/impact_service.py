"""Test impact scoring (spec 2026-10-12 §3.3, §3.4, §9; plan Rulings 1, 2): a change scored against the stored
statistics; an upload's suggestion scored before its run row or results exist and stored with the run; the outcome
written after the response from the stored results. Neither step can fail an upload.

Scoring reads only what one change needs (the perf ruling): the impact_pairs rows of the change's unit hashes, and
the impact_test_base rows of those pairs' tests plus the rows that can carry a label (a recorded file whose name is in
the change, or fewer than NO_HISTORY_RUNS runs). Never the whole project's statistics."""
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.analytics.impact_rules import (
    FAILING, MODEL_VERSION, NO_HISTORY_RUNS, WINDOW_DAYS, ChangedFiles, change_units, suffixes,
)
from src.ingestion.analytics.impact_score import BaseStat, ImpactTest, PairStat, suggest
from src.ingestion.analytics.trends import as_utc
from src.ingestion.models import Run
from src.ingestion.models.impact import ImpactPair, ImpactTestBase, RunImpact, unit_hash
from src.ingestion.service.impact_history import newly_failed_in_run, run_outcomes
from src.ingestion.service.impact_stats import live_excluded
from src.ingestion.service.report_service import in_list

NAMES_PER_QUERY = 200  # LIKE terms per query: SQLite's expression depth limit is 1,000


def history_runs(db: Session, project_id: int, until: datetime) -> int:
    """Runs with changed files, not truncated, started in the 90 days before `until` ("not enough history" below 20)."""
    return db.execute(
        select(func.count()).select_from(Run).where(
            Run.project_id == project_id, Run.started_at >= until - timedelta(days=WINDOW_DAYS), Run.started_at < until,
            Run.changed_files > 0, or_(Run.changes_truncated.is_(None), Run.changes_truncated.is_(False)))
    ).scalar_one()


def failing_on_branch(db: Session, project_id: int, branch: Optional[str], before: datetime) -> List[ImpactTest]:
    """The failing tests of the branch's latest run started before `before`, by name."""
    if branch is None:
        return []
    latest = db.execute(
        select(Run.id).where(Run.project_id == project_id, Run.branch == branch, Run.started_at < before)
        .order_by(Run.started_at.desc(), Run.id.desc()).limit(1)
    ).scalar()
    if latest is None:
        return []
    return sorted((test for status, test in run_outcomes(db, latest).values() if status in FAILING),
                  key=lambda t: (t.name, t.test_key))


_BASE_COLUMNS = (ImpactTestBase.test_key, ImpactTestBase.suite, ImpactTestBase.class_name, ImpactTestBase.name,
                 ImpactTestBase.runs, ImpactTestBase.new_failures, ImpactTestBase.file, ImpactTestBase.flaky)


def _like_contains(name: str) -> str:
    escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _file_names(changed_files: ChangedFiles) -> List[str]:
    """The changed files' last segments. A test's recorded file can only match a changed path ("test file changed")
    when it contains that path's file name, so these narrow the read; scoring's own check decides."""
    return sorted({suffixes(path)[-1] for path in changed_files.paths if suffixes(path)})


def load_statistics(db: Session, project_id: int, units: Set[str],
                    changed_files: Optional[ChangedFiles] = None) -> Tuple[List[PairStat], Dict[str, BaseStat]]:
    """The rows one scoring reads: the pairs of the change's units (by unit hash, the key's leading columns), their
    tests' base rows, and the base rows that can carry a label: a recorded file containing a changed file's name, or
    fewer than NO_HISTORY_RUNS runs."""
    pairs: List[PairStat] = []
    if units:
        hashes = sorted({unit_hash(unit) for unit in units})
        pairs = [PairStat(*row) for row in db.execute(
            select(ImpactPair.path_unit, ImpactPair.test_key, ImpactPair.changed_runs, ImpactPair.new_failures)
            .where(ImpactPair.project_id == project_id, in_list(db, ImpactPair.unit_hash, hashes))
            .order_by(ImpactPair.unit_hash, ImpactPair.test_key))]
    wanted = [[ImpactTestBase.runs < NO_HISTORY_RUNS]]
    keys = sorted({pair.test_key for pair in pairs})
    if keys:
        wanted[0].append(in_list(db, ImpactTestBase.test_key, keys))
    names = _file_names(changed_files) if changed_files is not None else []
    for start in range(0, len(names), NAMES_PER_QUERY):
        wanted.append([ImpactTestBase.file.like(_like_contains(name), escape="\\")
                       for name in names[start:start + NAMES_PER_QUERY]])
    bases: Dict[str, BaseStat] = {}
    for conditions in wanted:
        for key, suite, class_name, name, runs, new_failures, file, flaky in db.execute(
                select(*_BASE_COLUMNS).where(ImpactTestBase.project_id == project_id, or_(*conditions))):
            bases[key] = BaseStat(ImpactTest(key, suite, class_name, name), runs, new_failures, file, bool(flaky))
    return pairs, bases


def score_change(db: Session, project_id: int, changed_paths: Sequence[str], branch: Optional[str], *,
                 now: datetime) -> dict:
    """The suggestion for a change as of `now` (spec §3.3)."""
    units = change_units(changed_paths)
    changed_files = ChangedFiles(changed_paths)
    pairs, bases = load_statistics(db, project_id, units, changed_files)
    return suggest(units, pairs, bases, history_runs=history_runs(db, project_id, now), changed_files=changed_files,
                   failing_on_branch=failing_on_branch(db, project_id, branch, now))


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
    start. Never raises: on failure the upload carries on without one. The rollback (a failed statement aborts a
    PostgreSQL transaction) loses nothing, because nothing of the upload is written yet."""
    if not changed_paths:
        return None
    try:
        suggestion = score_change(db, project_id, changed_paths, branch, now=as_utc(started_at))
        return Scored(suggestion, datetime.now(timezone.utc))
    except Exception as exc:
        db.rollback()
        _failed("score", exc, project_id=project_id)
        return None


def stored_suggestion(run_id: int, scored: Scored, *, replayed: bool) -> RunImpact:
    return RunImpact(run_id=run_id, suggested=scored.suggestion, model_version=MODEL_VERSION, replayed=replayed,
                     scored_at=scored.scored_at)


def record_outcome(row: RunImpact, newly: Sequence[ImpactTest], now: datetime) -> None:
    """Caught: the new failures the suggestion named, in any kind; missed: the others."""
    named = {test["test_key"] for test in row.suggested["tests"]}
    row.caught = [t.out() for t in newly if t.test_key in named]
    row.missed = [t.out() for t in newly if t.test_key not in named]
    row.evaluated_at = now


def evaluate_run(session_factory: sessionmaker, run_id: int) -> None:
    """After the upload's response: the run's new failures against its stored suggestion. Never raises; on failure
    the outcome stays empty (evaluated_at null)."""
    try:
        with session_factory() as db:
            row, run = db.get(RunImpact, run_id), db.get(Run, run_id)
            if row is None or run is None or row.evaluated_at is not None:
                return
            excluded = live_excluded(db, run.project_id)
            record_outcome(row, newly_failed_in_run(db, run, excluded), datetime.now(timezone.utc))
            db.commit()
    except Exception as exc:
        _failed("outcome", exc, run_id=run_id)
