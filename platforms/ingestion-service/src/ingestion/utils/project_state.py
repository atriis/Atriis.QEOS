"""Which projects are pending deletion (spec 2026-10-16 §4), read from project-service's internal feed and kept 60 s.
Uploads to them are refused. Fail open: without an answer, the last known one is used (none at first), so a
project-service outage never stops CI uploads."""
import threading
import time
from typing import FrozenSet, Optional

from src.ingestion.core.config import settings

TTL_SECONDS = 60.0
_lock = threading.Lock()
_pending: FrozenSet[int] = frozenset()
_read_at: Optional[float] = None


def reset() -> None:
    global _pending, _read_at
    with _lock:
        _pending, _read_at = frozenset(), None


def is_pending(project_id: int) -> bool:
    global _pending, _read_at
    if not settings.PROJECT_SERVICE_INTERNAL_URL:
        return False
    with _lock:
        fresh = _read_at is not None and time.monotonic() - _read_at < TTL_SECONDS
        if not fresh:
            from src.ingestion.jobs.retention import RetentionError, fetch_policies, parse_internal_url
            try:
                policies = fetch_policies(parse_internal_url(settings.PROJECT_SERVICE_INTERNAL_URL))
                _pending = frozenset(p.project_id for p in policies if p.deleted)
            except RetentionError:
                pass  # keep the last answer
            _read_at = time.monotonic()
        return project_id in _pending
