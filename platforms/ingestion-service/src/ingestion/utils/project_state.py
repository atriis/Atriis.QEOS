"""Which projects are pending deletion (ADR-033), read from project-service's internal feed and kept 60 s.
Uploads to them are refused. Fail open: without an answer, the last known one is used (none at first), so a
project-service outage never stops CI uploads. The feed is read outside the lock by one request at a time; every
other request meanwhile gets the last answer at once, so a hanging project-service delays one upload, not all."""
import threading
import time
from typing import FrozenSet, Optional

from src.ingestion.core.config import settings

TTL_SECONDS = 60.0
TIMEOUT_SECONDS = 2.0  # an upload waits at most this long, once a minute
_lock = threading.Lock()
_pending: FrozenSet[int] = frozenset()
_read_at: Optional[float] = None
_refreshing = False


def reset() -> None:
    global _pending, _read_at, _refreshing
    with _lock:
        _pending, _read_at, _refreshing = frozenset(), None, False


def _refresh() -> None:
    global _pending, _read_at, _refreshing
    from src.ingestion.jobs import retention

    fresh: Optional[FrozenSet[int]] = None
    try:
        endpoint = retention.parse_internal_url(settings.PROJECT_SERVICE_INTERNAL_URL)
        policies = retention.fetch_policies(endpoint, timeout=TIMEOUT_SECONDS)
        fresh = frozenset(p.project_id for p in policies if p.deleted)
    except retention.RetentionError:
        pass  # keep the last answer
    finally:
        with _lock:
            if fresh is not None:
                _pending = fresh
            _read_at = time.monotonic()
            _refreshing = False


def is_pending(project_id: int) -> bool:
    global _refreshing
    if not settings.PROJECT_SERVICE_INTERNAL_URL:
        return False
    with _lock:
        stale = _read_at is None or time.monotonic() - _read_at >= TTL_SECONDS
        refresh_here = stale and not _refreshing
        if refresh_here:
            _refreshing = True
        known = _pending
    if not refresh_here:
        return project_id in known
    _refresh()
    with _lock:
        return project_id in _pending
