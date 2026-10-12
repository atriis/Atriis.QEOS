"""Job heartbeats (monitoring spec 2026-10-10 §3): after each pass a loop job upserts its row in
job_heartbeats; ingestion's /metrics turns the rows into job_last_success_timestamp_seconds and
job_last_error_timestamp_seconds (utils/job_metrics.py).

A heartbeat never stops a job: a failed write is logged and the loop carries on. An error text keeps
only its first line, at most MAX_ERROR characters, with URL credentials (greedy, then utils/redaction.py),
glued secret keys, passphrase=... pairs and bare Bearer tokens replaced, so no secret reaches the
database or a dashboard.
"""
import json
import re
import sys
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.models.job_heartbeat import JobHeartbeat
from src.ingestion.utils.redaction import _SECRET_NAMES, redact

JOBS = ("retention", "rollup", "weekly_summary", "impact_rollup")
MAX_ERROR = 500
# Userinfo of scheme://userinfo@host up to the LAST "@" before whitespace or a quote, so a
# password holding "@" or "/" is removed whole.
_URL_CREDENTIALS = re.compile(r"""(?<=://)[^\s"']*@""")
# Guards after redact() for what utils/redaction.py misses: a key glued to a long word (redact needs a
# non-word character before the key), passphrase, and a bare "Bearer <token>" with no Authorization
# header in front. The key names come from redaction's _SECRET_NAMES, so heartbeat and result masking
# cannot drift; each normalised name ("secretkey") also matches secret_key, secret-key, SecretKey and
# secret.key. Every quantifier is bounded or over a disjoint class, so no input backtracks badly.
_GUARD_NAMES = sorted({name for name, _ in _SECRET_NAMES} | {"passphrase"}, key=lambda n: (-len(n), n))
_SECRET_GUARD = re.compile(
    r"""(?i)((?:""" + "|".join(r"[_.\-]?".join(map(re.escape, name)) for name in _GUARD_NAMES)
    + r""")["']?[ \t]{0,5}(?:=>|:=|=|:)[ \t]{0,5})("[^"]*"|'[^']*'|[^\s"']+)"""
)

_BEARER = re.compile(r"""(?i)\b(bearer\s+)("[^"]*"|'[^']*'|[^\s"']+)""")
SCAN_LIMIT = 4096  # the first line is cut here before any regex runs


def short_error(text: str) -> str:
    lines = str(text).strip().splitlines()
    first = lines[0][:SCAN_LIMIT] if lines else ""
    first = _URL_CREDENTIALS.sub("***@", first)
    first = redact(first)[0]  # the platform's tested masking: Authorization, JSON pairs, tokens, ...
    first = _SECRET_GUARD.sub(r"\1***", first)  # glued keys, passphrase, quoted keys
    first = _BEARER.sub(r"\1***", first)
    return first[:MAX_ERROR]


def _upsert(db: Session, job: str, values: dict) -> None:
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:  # SQLite: the tests
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(JobHeartbeat).values(job=job, **values)
    db.execute(statement.on_conflict_do_update(index_elements=[JobHeartbeat.job], set_=values))
    db.commit()


def _utc(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now


def _record(session_factory: sessionmaker, job: str, values: dict) -> None:
    try:
        with session_factory() as db:
            _upsert(db, job, values)
    except Exception as exc:  # the database may be the very thing that failed the pass
        print(json.dumps({"event": "heartbeat_failed", "job": job, "error": type(exc).__name__}),
              file=sys.stderr, flush=True)


def record_success(session_factory: sessionmaker, job: str, now: Optional[datetime] = None) -> None:
    _record(session_factory, job, {"last_success_at": _utc(now)})


def record_error(session_factory: sessionmaker, job: str, error: str, now: Optional[datetime] = None) -> None:
    _record(session_factory, job, {"last_error_at": _utc(now), "last_error": short_error(error)})
