"""Retention: delete runs older than each project's retention period, and empty deleted projects.
A project on legal hold loses nothing.

    python -m src.ingestion.jobs.retention [--dry-run] [--loop]

Retention periods come from project-service's internal endpoint, called with the HTTP Basic
credentials in PROJECT_SERVICE_INTERNAL_URL. A pass that cannot get a trustworthy answer deletes
nothing, and projects missing from the answer are never touched, so a bug or an empty list can
never wipe data.
"""
import argparse
import json
import signal
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator, List, Optional
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Query, Session, sessionmaker

from src.ingestion.core.config import settings
from src.ingestion.jobs import heartbeat
from src.ingestion.models import ApiKey, LogValue, Run, RunResult

RETENTION_PATH = "/internal/v1/projects/retention"
LOCK_ID = 7_351_001  # any fixed number; only this job takes it
TIMEOUT_SECONDS = 10.0
JOB = "retention"


class RetentionError(Exception):
    """The pass cannot run safely, so it deletes nothing. Messages never contain the password."""


@dataclass(frozen=True)
class Policy:
    project_id: int
    days: int
    deleted: bool
    deleted_at: Optional[datetime] = None
    legal_hold: bool = False
    # Purge steps project-service already recorded for a deleted project (spec 2026-10-16), so a purge resumes
    purge_state: Optional[dict] = None


@dataclass(frozen=True)
class Endpoint:
    url: str        # without credentials
    username: str
    password: str
    display: str    # for logs: the password replaced with ***
    base: str = ""  # without credentials nor the feed path: other internal routes hang off it


def parse_internal_url(value: str, name: str = "PROJECT_SERVICE_INTERNAL_URL") -> Endpoint:
    problem = RetentionError(f"{name} must look like http://user:password@host:port")
    try:
        parts = urlsplit(value.strip())
        username, password, hostname = parts.username, parts.password, parts.hostname
    except ValueError:
        raise problem from None
    if parts.scheme not in ("http", "https") or not hostname or not username or not password:
        raise problem
    host = parts.netloc.rpartition("@")[2]
    path = parts.path.rstrip("/")
    return Endpoint(
        url=urlunsplit((parts.scheme, host, path + RETENTION_PATH, "", "")),
        username=unquote(username),
        password=unquote(password),
        display=urlunsplit((parts.scheme, f"{username}:***@{host}", path, "", "")),
        base=urlunsplit((parts.scheme, host, path, "", "")),
    )


def fetch_policies(endpoint: Endpoint) -> List[Policy]:
    try:
        response = httpx.get(endpoint.url, auth=(endpoint.username, endpoint.password), timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise RetentionError(f"cannot reach {endpoint.display}: {type(exc).__name__}: {exc}") from None
    if response.status_code != 200:
        raise RetentionError(f"{endpoint.display} answered {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise RetentionError(f"{endpoint.display} returned a body that is not JSON") from None
    projects = body.get("projects") if isinstance(body, dict) else None
    if not isinstance(projects, list):
        raise RetentionError(f"{endpoint.display} returned an unexpected body")
    return [_policy(item, endpoint) for item in projects]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)  # bool is a subclass of int


def _policy(item: object, endpoint: Endpoint) -> Policy:
    if (
        not isinstance(item, dict)
        or not _is_int(item.get("project_id"))
        or not _is_int(item.get("result_retention_days"))
        or not 1 <= item["result_retention_days"] <= 365
        or not isinstance(item.get("deleted"), bool)
        # Required, not defaulted: an answer that says nothing about holds could hide one
        or not isinstance(item.get("legal_hold"), bool)
    ):
        raise RetentionError(f"{endpoint.display} returned an unexpected body")
    deleted_at = None
    if item["deleted"]:
        # A deleted project's runs go only after the grace period, so its time must be trustworthy
        deleted_at = _aware_time(item.get("deleted_at"))
        if deleted_at is None:
            raise RetentionError(f"{endpoint.display} returned a deleted project without a usable deleted_at")
    return Policy(
        project_id=item["project_id"], days=item["result_retention_days"], deleted=item["deleted"],
        deleted_at=deleted_at, legal_hold=item["legal_hold"],
        purge_state=item.get("purge_state") if isinstance(item.get("purge_state"), dict) else None,
    )


def _aware_time(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # project-service on SQLite (its tests) serialises without an offset; its PostgreSQL column is UTC
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def run_pass(
    db: Session, policies: List[Policy], now: datetime, *, batch_size: int, dry_run: bool, grace_days: int = 7,
    purge: Optional[Callable[[Policy], List[str]]] = None,
) -> dict:
    """Live projects lose runs past their retention period. A deleted project (spec 2026-10-16) keeps everything
    while it can be restored, then `purge` removes it from every service; without `purge` it is left alone."""
    runs_deleted = projects_purged = purge_failures = projects_held = 0
    for policy in policies:
        if policy.legal_hold:
            projects_held += 1
            continue  # on hold: nothing of it is deleted, whatever its age or deletion
        if policy.deleted:
            if policy.deleted_at > now - timedelta(days=grace_days):
                continue  # pending: restorable as it was, so not even the usual retention
            if dry_run:
                projects_purged += 1
            elif purge is None:
                _log({"event": "purge_skipped", "project_id": policy.project_id,
                      "reason": "TEST_MANAGEMENT_INTERNAL_URL is not set"})
            else:
                try:
                    steps = purge(policy)
                except RetentionError as exc:
                    purge_failures += 1
                    _log({"event": "purge_failed", "project_id": policy.project_id, "error": str(exc)}, error=True)
                    continue
                if steps:
                    projects_purged += 1
                    _log({"event": "project_purged", "project_id": policy.project_id, "steps": steps})
                else:
                    _log({"event": "purge_skipped", "project_id": policy.project_id, "reason": "restored"})
            continue
        runs = db.query(Run.id).filter(
            Run.project_id == policy.project_id, Run.created_at < now - timedelta(days=policy.days))
        runs_deleted += runs.count() if dry_run else _delete_in_batches(db, runs, batch_size)
    listed = {policy.project_id for policy in policies}
    known = {pid for (pid,) in db.query(Run.project_id).distinct()} | {
        pid for (pid,) in db.query(ApiKey.project_id).distinct()
    }
    return {
        "event": "retention",
        "projects": len(policies),
        "runs_deleted": runs_deleted,
        "projects_purged": projects_purged,
        "purge_failures": purge_failures,
        "projects_skipped": len(known - listed),
        "projects_held": projects_held,
        "dry_run": dry_run,
    }


def _delete_in_batches(db: Session, runs: Query, batch_size: int) -> int:
    deleted = 0
    while True:
        batch = [run_id for (run_id,) in runs.order_by(Run.id).limit(batch_size)]
        if not batch:
            return deleted
        # Children first, explicitly: SQLite (the tests) does not enforce ON DELETE CASCADE by default. The results'
        # log values (ADR-032), then the results
        results = select(RunResult.id).where(RunResult.run_id.in_(batch))
        db.query(LogValue).filter(LogValue.result_id.in_(results)).delete(synchronize_session=False)
        db.query(RunResult).filter(RunResult.run_id.in_(batch)).delete(synchronize_session=False)
        db.query(Run).filter(Run.id.in_(batch)).delete(synchronize_session=False)
        db.commit()
        deleted += len(batch)


@contextmanager
def _advisory_lock(engine: Engine) -> Iterator[bool]:
    """One pass at a time across every copy of the job; PostgreSQL only (the tests use SQLite)."""
    if engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as conn:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}).scalar())
        conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
                conn.commit()


def _log(record: dict, error: bool = False) -> None:
    print(json.dumps(record), file=sys.stderr if error else sys.stdout, flush=True)


def run_once(*, dry_run: bool, now: Callable[[], datetime], session_factory: sessionmaker, lock_engine: Engine) -> bool:
    try:
        endpoint = parse_internal_url(settings.PROJECT_SERVICE_INTERNAL_URL)
        with _advisory_lock(lock_engine) as acquired:
            if not acquired:
                _log({"event": "retention_skipped", "reason": "another pass is already running"})
                return True  # the copy holding the lock writes the heartbeat
            policies = fetch_policies(endpoint)
            tm = (parse_internal_url(settings.TEST_MANAGEMENT_INTERNAL_URL, name="TEST_MANAGEMENT_INTERNAL_URL")
                  if settings.TEST_MANAGEMENT_INTERNAL_URL else None)
            with session_factory() as db:
                purge = None
                if tm is not None:
                    from src.ingestion.jobs.purge import purge_project

                    def purge(policy: Policy) -> List[str]:
                        return purge_project(db, policy, endpoint, tm)
                summary = run_pass(
                    db, policies, now(), batch_size=settings.RETENTION_BATCH_SIZE, dry_run=dry_run,
                    grace_days=settings.PROJECT_DELETE_GRACE_DAYS, purge=purge,
                )
    except RetentionError as exc:
        _log({"event": "retention_failed", "error": str(exc)}, error=True)
        heartbeat.record_error(session_factory, JOB, str(exc), now())
        return False
    except Exception as exc:  # e.g. the database is down: report it; the loop tries again later
        message = f"{type(exc).__name__}: {exc}"
        _log({"event": "retention_failed", "error": message}, error=True)
        heartbeat.record_error(session_factory, JOB, message, now())
        return False
    _log(summary)
    if summary["purge_failures"]:
        # Everything else was done; the failed purges resume from their recorded steps on the next pass
        heartbeat.record_error(session_factory, JOB, f"{summary['purge_failures']} project purge(s) failed", now())
        return False
    heartbeat.record_success(session_factory, JOB, now())
    return True


def main(
    argv: Optional[List[str]] = None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    session_factory: Optional[sessionmaker] = None,
    lock_engine: Optional[Engine] = None,
    stop: Optional[threading.Event] = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.ingestion.jobs.retention",
        description="Delete runs older than each project's retention period; empty deleted projects.",
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would be deleted; change nothing")
    parser.add_argument("--loop", action="store_true", help="a pass now, then every RETENTION_INTERVAL_HOURS")
    args = parser.parse_args(argv)

    if session_factory is None:
        from src.ingestion.db.session import SessionLocal

        session_factory = SessionLocal
    if lock_engine is None:
        lock_engine = session_factory.kw["bind"]

    def once() -> bool:
        return run_once(dry_run=args.dry_run, now=now, session_factory=session_factory, lock_engine=lock_engine)

    if not args.loop:
        return 0 if once() else 1

    if stop is None:
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while not stop.is_set():
        once()  # a failed pass is logged; the next one may succeed
        stop.wait(settings.RETENTION_INTERVAL_HOURS * 3600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
