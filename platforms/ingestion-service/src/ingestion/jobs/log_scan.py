"""Re-scan a project's stored logs for its log-value patterns (ADR-032, spec §3.4).

Adding a pattern queues a scan (request_scan bumps collection_settings.log_scan_requested). The scan runs inside
ingestion-service after the response (a background task), and again at start-up for a scan a restart cut short
(resume_all). It walks the logs stored in the last 90 days in committed batches, oldest result first, and replaces
each result's values for the project's current patterns, so running it again changes nothing. One scan per project
at a time: a PostgreSQL advisory lock per project (an in-process lock on SQLite, the tests). A pattern added while a
scan runs bumps the counter again, and the running scan makes another pass before it stops.
"""
import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterator, Optional

from sqlalchemy import text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.core.config import settings
from src.ingestion.models import CollectionSettings, Run, RunResult
from src.ingestion.service import log_pattern_service, log_value_service

logger = logging.getLogger(__name__)

SCAN_DAYS = 90
# With the project id: one advisory lock per project (the two-key form; retention's single key 7_351_001 is apart)
LOCK_CLASS = 7_351_023
_local_guard = threading.Lock()
_local_locks: Dict[int, threading.Lock] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def request_scan(db: Session, project_id: int) -> None:
    """Queue a scan. One atomic increment, so requests that race are all counted."""
    if db.get(CollectionSettings, project_id) is None:
        db.add(CollectionSettings(project_id=project_id, collect_manual=True, discarded_count=0))
        try:
            db.commit()
        except IntegrityError:  # another request created the row first
            db.rollback()
    db.execute(
        update(CollectionSettings).where(CollectionSettings.project_id == project_id)
        .values(log_scan_requested=CollectionSettings.log_scan_requested + 1)
    )
    db.commit()


def scan_state(db: Session, project_id: int) -> dict:
    """What GET …/log-patterns reports: running while a request is not finished, since the current pass started."""
    row = db.get(CollectionSettings, project_id)
    if row is None or (row.log_scan_requested or 0) <= (row.log_scan_done or 0):
        return {"state": "idle", "since": None}
    return {"state": "running", "since": row.log_scan_started_at}


@contextmanager
def _project_lock(engine: Engine, project_id: int) -> Iterator[bool]:
    if engine.dialect.name != "postgresql":
        with _local_guard:
            lock = _local_locks.setdefault(project_id, threading.Lock())
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()
        return
    with engine.connect() as conn:
        args = {"cls": LOCK_CLASS, "project": project_id}
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:cls, :project)"), args).scalar())
        conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:cls, :project)"), args)
                conn.commit()


def scan_pass(db: Session, project_id: int, since: datetime, batch_size: int) -> int:
    """One pass over the project's logs stored since `since`; returns the results scanned. The patterns are loaded
    again for every batch, so one added or deleted meanwhile is seen from the next batch on."""
    scanned, last_id, retried = 0, 0, False
    while True:
        patterns = log_pattern_service.compiled_for(db, project_id)
        if not patterns:
            return scanned
        batch = (
            db.query(RunResult.id, RunResult.log)
            .join(Run, Run.id == RunResult.run_id)
            .filter(Run.project_id == project_id, Run.created_at >= since, RunResult.id > last_id,
                    RunResult.log.isnot(None))
            .order_by(RunResult.id).limit(batch_size).all()
        )
        if not batch:
            return scanned
        log_value_service.replace_values(db, [(row.id, row.log) for row in batch], patterns)
        try:
            db.commit()
        except IntegrityError:
            # A pattern was deleted between loading it and inserting its values (PostgreSQL's foreign key): load the
            # patterns again and redo this batch, once
            db.rollback()
            if retried:
                raise
            retried = True
            continue
        retried = False
        scanned += len(batch)
        last_id = batch[-1].id


def _scan_until_idle(session_factory: sessionmaker, project_id: int, now: Callable[[], datetime],
                     batch_size: int) -> None:
    while True:
        with session_factory() as db:
            row = db.get(CollectionSettings, project_id)
            if row is None or row.log_scan_requested <= row.log_scan_done:
                return
            generation, started = row.log_scan_requested, now()
            row.log_scan_started_at = started
            db.commit()
            # A module global, looked up at call time (the tests replace it)
            scanned = scan_pass(db, project_id, started - timedelta(days=SCAN_DAYS), batch_size)
            finished = db.execute(
                update(CollectionSettings)
                .where(CollectionSettings.project_id == project_id,
                       CollectionSettings.log_scan_requested == generation)
                .values(log_scan_done=generation, log_scan_started_at=None)
            ).rowcount
            db.commit()
        logger.info(json.dumps({"event": "log_scan", "project_id": project_id, "results_scanned": scanned,
                                "finished": bool(finished)}))
        # Not finished: a pattern was added during the pass; the next pass reads every result again


def run_scan(session_factory: sessionmaker, project_id: int, *, lock_engine: Optional[Engine] = None,
             now: Callable[[], datetime] = _utcnow, batch_size: Optional[int] = None) -> bool:
    """Run the project's queued scan until nothing is queued. False when another scan holds the project (it sees
    the request) or a pass failed (logged; the request stays queued for the next start or the next pattern)."""
    engine = lock_engine if lock_engine is not None else session_factory.kw["bind"]
    size = batch_size or settings.LOG_SCAN_BATCH_SIZE
    try:
        while True:
            with _project_lock(engine, project_id) as acquired:
                if not acquired:
                    return False
                _scan_until_idle(session_factory, project_id, now, size)
            # A request that came in between the last finish and the unlock found the lock taken: take it again
            with session_factory() as db:
                if scan_state(db, project_id)["state"] == "idle":
                    return True
    except Exception:  # a background task has nobody to raise to
        logger.exception("log-value scan failed for project %s", project_id)
        return False


def resume_all(session_factory: sessionmaker) -> int:
    """Every project with a queued scan, one after another (start-up). Returns how many were run."""
    try:
        with session_factory() as db:
            projects = [project_id for (project_id,) in db.query(CollectionSettings.project_id).filter(
                CollectionSettings.log_scan_requested > CollectionSettings.log_scan_done
            ).order_by(CollectionSettings.project_id)]
    except Exception:
        logger.exception("queued log-value scans could not be read")
        return 0
    for project_id in projects:
        run_scan(session_factory, project_id)
    return len(projects)
