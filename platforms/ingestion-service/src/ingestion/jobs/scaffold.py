"""What every loop job does around its pass: JSON log lines, one pass at a time across copies (a PostgreSQL advisory
lock), the heartbeat after a pass that ran, and the loop.

impact_rollup uses it. retention, rollup and weekly_summary still carry their own copies: their tests patch each
module's `_advisory_lock` and `run_pass`, and retention adds its own failure handling and SIGTERM, so moving them is
a separate change."""
import argparse
import json
import signal
import sys
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.jobs import heartbeat


def log(record: dict, error: bool = False) -> None:
    print(json.dumps(record), file=sys.stderr if error else sys.stdout, flush=True)


@contextmanager
def advisory_lock(engine: Engine, lock_id: int) -> Iterator[bool]:
    """True when this copy holds `lock_id` for the block; always True off PostgreSQL (the tests use SQLite)."""
    if engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as conn:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id}).scalar())
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id})
                conn.commit()


def run_once(*, job: str, event: str, lock_id: int, session_factory: sessionmaker, lock_engine: Engine,
             work: Callable[[Session], object]) -> bool:
    """One pass under the lock, then its heartbeat. A failure is logged and recorded, never raised: the loop must
    survive a bad pass. A pass skipped for the lock records nothing (the copy holding it does)."""
    try:
        with advisory_lock(lock_engine, lock_id) as acquired:
            if not acquired:
                log({"event": event, "skipped": "another copy holds the lock"})
                return True
            with session_factory() as db:
                work(db)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        log({"event": event, "error": message}, error=True)
        heartbeat.record_error(session_factory, job, message)
        return False
    heartbeat.record_success(session_factory, job)
    return True


def parser(description: str, loop_help: str) -> argparse.ArgumentParser:
    """The job's command line with `--loop`; a job may add its own arguments."""
    built = argparse.ArgumentParser(description=description)
    built.add_argument("--loop", action="store_true", help=loop_help)
    return built


def connections(session_factory: Optional[sessionmaker], lock_engine: Optional[Engine]) -> Tuple[sessionmaker, Engine]:
    """The runtime session factory and its engine unless the caller (a test) gives its own."""
    if session_factory is None:
        from src.ingestion.db.session import SessionLocal

        session_factory = SessionLocal
    return session_factory, lock_engine if lock_engine is not None else session_factory.kw["bind"]


def serve(once: Callable[[], bool], *, loop: bool, stop: Optional[threading.Event], interval_seconds: float) -> int:
    """One pass now; without `loop` the exit code says how it went, with `loop` one more pass every interval until
    `stop` is set; SIGTERM sets it too, so the loop ends cleanly."""
    if stop is None:
        stop = threading.Event()
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
    ok = once()
    if not loop:
        return 0 if ok else 1
    while not stop.wait(interval_seconds):
        once()
    return 0
