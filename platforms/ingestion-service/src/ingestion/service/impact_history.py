"""Test impact analysis: which tests newly failed (spec 2026-10-12 §3.1, plan Rulings 6, 7, 8).

A test newly failed in run R when its outcome in R fails (failed or errored; the outcome is the last attempt among
non-skipped results) and its previous outcome on R's branch within the 90 days before R passed. A branch with no
previous outcome there (a new PR branch) uses the test's latest outcome on R's base branch before R, within the same
90 days. The caller's `excluded` set leaves out flaky and muted tests.

One reading of the one definition serves one run (an upload's outcome, replay) and many (the rollup): both go
through `_newly_failed`, which reads outcomes with the Report's `_outcomes` (report_service.py): the same outcome
rule and its PostgreSQL work (one sort; only failing outcomes and their neighbours come back).
tests/integration/test_impact_newly_failed.py pins the one-run and bulk answers to agree.
"""
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

from sqlalchemy import Integer, and_, func, or_, select
from sqlalchemy.orm import Session

from src.ingestion.analytics import rollup
from src.ingestion.analytics.flaky import rank_flaky
from src.ingestion.analytics.impact_rules import (
    FAILING, FLAKY_MIN_FLIP_RATE, FLAKY_MIN_RUNS, WINDOW_DAYS, base_branch_of,
)
from src.ingestion.analytics.impact_score import ImpactTest
from src.ingestion.analytics.report_streaks import build_sequences
from src.ingestion.analytics.trends import as_utc
from src.ingestion.models import Run, RunChangedFile, RunResult
from src.ingestion.service import analytics_service
from src.ingestion.service.report_service import _outcomes, in_list

LOOKBACK = timedelta(days=WINDOW_DAYS)


@dataclass(frozen=True)
class ChangeRun:
    """A run with uploaded changed files, as the statistics and replay read it."""

    id: int
    project_id: int
    branch: Optional[str]
    base: Optional[str]  # base_branch_of(...)
    started_at: datetime  # UTC
    paths: Tuple[str, ...]


class _Target(NamedTuple):
    """A run whose new failures are wanted."""

    id: int
    branch: Optional[str]
    base: Optional[str]
    started_at: datetime  # UTC


class _RunAt(NamedTuple):
    """What `_outcomes` reads of each run."""

    branch: Optional[str]
    started_at: datetime


def run_outcomes(db: Session, run_id: int) -> Dict[str, Tuple[str, ImpactTest]]:
    """{test key: (status, test)} for one run: each test's last attempt (highest id) among its non-skipped results."""
    rows = db.execute(
        select(RunResult.test_key, RunResult.status, RunResult.suite, RunResult.class_name, RunResult.name)
        .where(RunResult.run_id == run_id, RunResult.status != "skipped")
        .order_by(RunResult.id)
    ).all()
    return {key: (status, ImpactTest(key, suite, class_name, name)) for key, status, suite, class_name, name in rows}


def _on_branch(branch: Optional[str]):
    return Run.branch.is_(None) if branch is None else Run.branch == branch


def _before(target: _Target):
    return or_(Run.started_at < target.started_at, and_(Run.started_at == target.started_at, Run.id < target.id))


def _latest_on_branch(db: Session, project_id: int, target: _Target, branch: str, keys: List[str]) -> Dict[str, str]:
    """Each key's latest outcome on `branch` before `target`, within LOOKBACK: the base-branch fallback. Not served by
    `_outcomes`, which keeps only outcomes next to a failure, while the latest base outcome is usually a pass after
    passes."""
    ranked = (
        select(
            RunResult.test_key.label("test_key"), RunResult.status.label("status"),
            func.row_number().over(
                partition_by=RunResult.test_key, order_by=(Run.started_at.desc(), Run.id.desc(), RunResult.id.desc()),
            ).label("position"),
        )
        .join(Run, Run.id == RunResult.run_id)
        .where(Run.project_id == project_id, _on_branch(branch), _before(target),
               Run.started_at >= target.started_at - LOOKBACK, RunResult.status != "skipped",
               in_list(db, RunResult.test_key, keys))
    ).subquery()
    rows = db.execute(select(ranked.c.test_key, ranked.c.status).where(ranked.c.position == 1))
    return {key: status for key, status in rows}


def _failing_keys(db: Session, run_ids: List[int], excluded: Set[str]) -> List[str]:
    """Tests with a failing result in any of the runs (the partial index serves this): only they can newly fail."""
    rows = db.execute(
        select(RunResult.test_key).distinct()
        .where(in_list(db, RunResult.run_id, run_ids, Integer), RunResult.status.in_(FAILING))
    )
    return sorted({key for (key,) in rows} - excluded)


def _newly_failed(db: Session, project_id: int, targets: Iterable[_Target], excluded: Set[str]) -> Dict[int, Set[str]]:
    """{run id: newly failed keys} for runs of one project."""
    targets = sorted(targets, key=lambda t: (t.started_at, t.id))
    if not targets:
        return {}
    keys = _failing_keys(db, [t.id for t in targets], excluded)
    if not keys:
        return {}
    first, last = targets[0], targets[-1]
    branches = {t.branch for t in targets}
    # Every run on the targets' branches from LOOKBACK before the first target up to the last one: the history
    history = db.execute(
        select(Run.id, Run.branch, Run.started_at)
        .where(Run.project_id == project_id, Run.started_at >= first.started_at - LOOKBACK,
               Run.started_at <= last.started_at)
    ).all()
    by_id = {run_id: _RunAt(branch, as_utc(started_at)) for run_id, branch, started_at in history
             if branch in branches and (as_utc(started_at), run_id) <= (last.started_at, last.id)}
    sequences = build_sequences(_outcomes(db, list(by_id), keys, by_id, with_headlines=False))
    position = {(o.run_id, o.test_key): (sequence, at)
                for sequence in sequences.values() for at, o in enumerate(sequence)}
    newly: Dict[int, Set[str]] = defaultdict(set)
    for target in targets:
        unseen = []
        for key in keys:
            found = position.get((target.id, key))
            if found is None:
                continue
            sequence, at = found
            if sequence[at].passed:
                continue
            previous = sequence[at - 1] if at else None
            if previous is not None and previous.started_at >= target.started_at - LOOKBACK:
                if previous.passed:
                    newly[target.id].add(key)
            elif target.base is not None:
                unseen.append(key)
        if unseen:
            base = _latest_on_branch(db, project_id, target, target.base, unseen)
            newly[target.id].update(key for key in unseen if base.get(key) == "passed")
    return {run_id: keys_ for run_id, keys_ in newly.items() if keys_}


def newly_failed_in_run(db: Session, run: Run, excluded: Set[str]) -> List[ImpactTest]:
    """The tests that newly failed in one run, by name."""
    target = _Target(run.id, run.branch, base_branch_of(run.branch, run.base_branch, run.change_base_ref),
                     as_utc(run.started_at))
    keys = _newly_failed(db, run.project_id, [target], excluded).get(run.id, set())
    if not keys:
        return []
    tests = {key: test for key, (_, test) in run_outcomes(db, run.id).items() if key in keys}
    return sorted(tests.values(), key=lambda t: (t.name, t.test_key))


def newly_failed_bulk(db: Session, runs: List[ChangeRun], excluded: Set[str]) -> Dict[int, Set[str]]:
    """{run id: newly failed keys} for many runs of one project (the rollup)."""
    if not runs:
        return {}
    return _newly_failed(db, runs[0].project_id, [_Target(r.id, r.branch, r.base, r.started_at) for r in runs],
                         excluded)


def change_runs(db: Session, project_id: int, start: datetime, end: datetime, *,
                include_truncated: bool = False) -> List[ChangeRun]:
    """Runs started in [start, end) with at least one changed file, oldest first. A run whose change list the
    collector truncated is left out of the statistics (spec §3.1) unless `include_truncated` (replay scores it, as an
    upload does; plan Ruling 16)."""
    filters = [Run.project_id == project_id, Run.started_at >= start, Run.started_at < end, Run.changed_files > 0]
    if not include_truncated:
        filters.append(or_(Run.changes_truncated.is_(None), Run.changes_truncated.is_(False)))
    runs = db.execute(
        select(Run.id, Run.branch, Run.base_branch, Run.change_base_ref, Run.started_at)
        .where(*filters).order_by(Run.started_at, Run.id)
    ).all()
    paths: Dict[int, List[str]] = defaultdict(list)
    if runs:
        rows = db.execute(
            select(RunChangedFile.run_id, RunChangedFile.path)
            .where(in_list(db, RunChangedFile.run_id, [r.id for r in runs], Integer)).order_by(RunChangedFile.id)
        )
        for run_id, path in rows:
            paths[run_id].append(path)
    return [ChangeRun(r.id, project_id, r.branch, base_branch_of(r.branch, r.base_branch, r.change_base_ref),
                      as_utc(r.started_at), tuple(paths[r.id])) for r in runs]


def flaky_keys(db: Session, project_id: int, since: datetime) -> Set[str]:
    """Tests flagged flaky since `since` with the Flaky view's defaults (plan Ruling 6), read as GET /analytics/flaky
    reads them: from the daily rollups when the project has them."""
    if rollup.has_rollups(db, project_id):
        inputs = rollup.rollup_inputs(db, project_id, since.date(), None)
    else:
        inputs = analytics_service.flaky_inputs(db, project_id, since, None)
    ranked = rank_flaky(*inputs, min_runs=FLAKY_MIN_RUNS, min_flip_rate=FLAKY_MIN_FLIP_RATE, limit=sys.maxsize)
    return {item["test_key"] for item in ranked}
