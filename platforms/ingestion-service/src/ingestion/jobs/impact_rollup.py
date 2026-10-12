"""Test impact rollup (spec 2026-10-12 §3.2, plan Ruling 14): rebuild impact_pairs and impact_test_base per project.

    python -m src.ingestion.jobs.impact_rollup [--loop]

Each pass visits every project with runs, and every project that still has statistics (so a project whose runs are
gone loses them). Over the runs with changed files from 90 days before today 00:00 UTC until now, it replaces the
project's rows in one transaction; the same data gives the same rows. One pass at a time across copies (PostgreSQL
advisory lock), like the other jobs; each pass that ran writes the impact_rollup heartbeat.
"""
import sys
import threading
from datetime import datetime, time, timedelta, timezone
from typing import Callable, List, Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.analytics.impact_rules import WINDOW_DAYS
from src.ingestion.jobs import scaffold
from src.ingestion.models import Run
from src.ingestion.models.impact import ImpactTestBase
from src.ingestion.service import analytics_service
from src.ingestion.service.impact_history import flaky_keys
from src.ingestion.service.impact_stats import rebuild_statistics

LOCK_ID = 7_351_004  # distinct from retention's, rollup's and weekly summary's locks
DEFAULT_INTERVAL_HOURS = 24.0
JOB = "impact_rollup"


def window_start(now: datetime) -> datetime:
    """90 days before today 00:00 UTC: every pass of one day starts at the same moment."""
    today = datetime.combine(now.astimezone(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    return today - timedelta(days=WINDOW_DAYS)


def _projects(db: Session) -> List[int]:
    with_runs = {pid for (pid,) in db.execute(select(Run.project_id).distinct())}
    with_rows = {pid for (pid,) in db.execute(select(ImpactTestBase.project_id).distinct())}
    return sorted(with_runs | with_rows)


def run_pass(db: Session, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    moment = now()
    start = window_start(moment)
    projects = _projects(db)
    pairs_written = tests_written = 0
    for project_id in projects:
        pairs, tests = rebuild_statistics(db, project_id, start, moment, flaky_keys(db, project_id, start),
                                          analytics_service.muted_keys(db, project_id), moment)
        pairs_written += pairs
        tests_written += tests
    summary = {"event": "impact_rollup", "projects": len(projects), "pairs": pairs_written, "tests": tests_written}
    scaffold.log(summary)
    return summary


def run_once(*, session_factory: sessionmaker, lock_engine: Engine) -> bool:
    # run_pass is looked up at call time, so a test can replace it
    return scaffold.run_once(job=JOB, event="impact_rollup", lock_id=LOCK_ID, session_factory=session_factory,
                             lock_engine=lock_engine, work=lambda db: run_pass(db))


def main(
    argv: Optional[list] = None,
    *,
    session_factory: Optional[sessionmaker] = None,
    lock_engine: Optional[Engine] = None,
    stop: Optional[threading.Event] = None,
    interval_hours: float = DEFAULT_INTERVAL_HOURS,
) -> int:
    args = scaffold.parser(__doc__, "run forever, one pass every 24 hours").parse_args(argv)
    session_factory, lock_engine = scaffold.connections(session_factory, lock_engine)
    return scaffold.serve(lambda: run_once(session_factory=session_factory, lock_engine=lock_engine),
                          loop=args.loop, stop=stop, interval_seconds=interval_hours * 3600)


if __name__ == "__main__":
    sys.exit(main())
