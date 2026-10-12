"""Replay (spec 2026-10-12 §3.6, plan Ruling 13): score past runs with changed files as if at upload, with statistics
built only from runs started before the run's day (UTC), and store each with its real outcome, marked replayed.

The scoring is live scoring's (impact_service.score_change), fed the day's statistics instead of the stored ones, so
live and replay agree on the same statistics. Days are replayed oldest first, each day's runs in batches of
BATCH_RUNS, one commit and one progress line per batch: a long replay keeps what it did if it stops."""
import json
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Sequence, Set

from sqlalchemy import Integer, select
from sqlalchemy.orm import Session

from src.ingestion.analytics.impact_rules import WINDOW_DAYS, ChangedFiles
from src.ingestion.analytics.impact_score import PairStat
from src.ingestion.models import Run
from src.ingestion.models.impact import RunImpact
from src.ingestion.service import analytics_service
from src.ingestion.service.impact_history import ChangeRun, change_runs, flaky_keys, newly_failed_in_run
from src.ingestion.service.impact_service import Scored, outcome, score_change, stored_suggestion
from src.ingestion.service.impact_stats import build_statistics
from src.ingestion.service.report_service import in_list

BATCH_RUNS = 200  # runs stored per commit


def _progress(record: dict) -> None:
    print(json.dumps({"event": "impact_backfill_progress", **record}), file=sys.stdout, flush=True)


def _stored(db: Session, run_ids: List[int]) -> Set[int]:
    found: Set[int] = set()
    for start in range(0, len(run_ids), 1000):
        found.update(run_id for (run_id,) in db.execute(
            select(RunImpact.run_id).where(in_list(db, RunImpact.run_id, run_ids[start:start + 1000], Integer))))
    return found


def replay_project(db: Session, project_id: int, start: datetime, now: datetime) -> int:
    """Runs with changed files started in [start, now) that have no stored suggestion; returns how many were stored.
    A live suggestion is never replaced, so a second replay finds nothing left to do."""
    targets = change_runs(db, project_id, start, now, include_truncated=True)
    if not targets:
        return 0
    stored = _stored(db, [run.id for run in targets])
    pending = [run for run in targets if run.id not in stored]  # oldest first, as change_runs orders them
    if not pending:
        return 0
    # Flaky and muted as known now: one set leaves tests out of the statistics and the outcomes alike
    flaky = flaky_keys(db, project_id, now - timedelta(days=WINDOW_DAYS))
    muted = analytics_service.muted_keys(db, project_id)
    by_day: Dict[date, List[ChangeRun]] = defaultdict(list)
    for run in pending:
        by_day[run.started_at.date()].append(run)
    done = 0
    for day in sorted(by_day):
        day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        pairs, bases = build_statistics(db, project_id, day_start - timedelta(days=WINDOW_DAYS), day_start, flaky, muted)
        by_unit: Dict[str, List[PairStat]] = defaultdict(list)
        for pair in pairs:
            by_unit[pair.path_unit].append(pair)
        by_key = {base.test.test_key: base for base in bases}

        def statistics(units: Set[str], _changed: ChangedFiles, _failing: int):
            return [pair for unit in sorted(units) for pair in by_unit.get(unit, ())], by_key

        runs = by_day[day]
        for batch_start in range(0, len(runs), BATCH_RUNS):
            batch: Sequence[ChangeRun] = runs[batch_start:batch_start + BATCH_RUNS]
            for change in batch:
                suggestion = score_change(db, project_id, change.paths, change.branch, now=change.started_at,
                                          statistics=statistics)
                row = stored_suggestion(change.id, Scored(suggestion, now), replayed=True)
                row.caught, row.missed = outcome(suggestion, newly_failed_in_run(db, db.get(Run, change.id),
                                                                                 flaky | muted))
                row.evaluated_at = now
                db.add(row)
            db.commit()
            done += len(batch)
            _progress({"project_id": project_id, "day": day.isoformat(), "done": done, "total": len(pending)})
    return len(pending)
