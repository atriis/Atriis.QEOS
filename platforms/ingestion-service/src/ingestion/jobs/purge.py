"""Purge a project whose deletion window is over (spec 2026-10-16 §5): test-management, then ingestion, then the
project row in project-service, each step idempotent and recorded there, so a pass that fails resumes next time."""
from typing import List

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ingestion.jobs.retention import TIMEOUT_SECONDS, Endpoint, Policy, RetentionError, _delete_in_batches
from src.ingestion.models import (
    ApiKey, CollectionSettings, FlakyDaily, FlakyRollupDay, ImpactPair, ImpactTestBase, LogPattern, LogValue,
    MaskingPattern, MutedTest, NotificationChannel, Run,
)

PER_PROJECT = (ApiKey, CollectionSettings, FlakyDaily, FlakyRollupDay, ImpactPair, ImpactTestBase, MaskingPattern,
               MutedTest, NotificationChannel)


def purge_ingestion(db: Session, project_id: int, batch_size: int = 500) -> int:
    """Every run (results, log values, children) and every per-project row of ingestion. Returns runs deleted."""
    runs = _delete_in_batches(db, db.query(Run.id).filter(Run.project_id == project_id), batch_size)
    patterns = select(LogPattern.id).where(LogPattern.project_id == project_id)
    db.query(LogValue).filter(LogValue.pattern_id.in_(patterns)).delete(synchronize_session=False)
    db.query(LogPattern).filter(LogPattern.project_id == project_id).delete(synchronize_session=False)
    for model in PER_PROJECT:
        db.query(model).filter(model.project_id == project_id).delete(synchronize_session=False)
    db.commit()
    return runs


def _call(method: str, endpoint: Endpoint, path: str, **kwargs) -> int:
    try:
        response = httpx.request(method, endpoint.base + path, auth=(endpoint.username, endpoint.password),
                                 timeout=TIMEOUT_SECONDS, **kwargs)
    except httpx.HTTPError as exc:
        raise RetentionError(f"cannot reach {endpoint.display}: {type(exc).__name__}") from None
    return response.status_code


class Restored(Exception):
    """project-service refused "started": the project was restored after the feed was read."""


def _record(project: Endpoint, project_id: int, step: str) -> None:
    status = _call("POST", project, f"/internal/v1/projects/{project_id}/purge-state", json={"step": step})
    if status == 409 and step == "started":
        raise Restored()
    if status != 204:
        raise RetentionError(f"{project.display} refused purge step {step} for project {project_id}: {status}")


def purge_project(db: Session, policy: Policy, project: Endpoint, tm: Endpoint) -> List[str]:
    """The steps done this pass; [] when the project was restored meanwhile (nothing touched)."""
    done = dict(policy.purge_state or {})
    steps: List[str] = []
    pid = policy.project_id
    if "started" not in done:
        try:
            _record(project, pid, "started")  # atomic: refused for a live project; blocks any later restore
        except Restored:
            return []
        steps.append("started")
    if "test_management" not in done:
        status = _call("DELETE", tm, f"/internal/v1/projects/{pid}")
        if status != 204:
            raise RetentionError(f"{tm.display} refused to purge project {pid}: {status}")
        _record(project, pid, "test_management")
        steps.append("test_management")
    if "ingestion" not in done:
        purge_ingestion(db, pid)
        _record(project, pid, "ingestion")
        steps.append("ingestion")
    status = _call("DELETE", project, f"/internal/v1/projects/{pid}")
    if status != 204:
        # 409: restored meanwhile (the row is live again) or a step not recorded; the next pass sees it
        raise RetentionError(f"{project.display} refused to delete project {pid}: {status}")
    steps.append("project")
    return steps
