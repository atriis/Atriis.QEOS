"""Endpoints for other services, not for people.

Not routed by the gateway (its catch-all answers 404) and not in the public OpenAPI. Callers
authenticate with HTTP Basic: INTERNAL_API_USERNAME / INTERNAL_API_PASSWORD.
"""
import hmac
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.project.core.config import settings
from src.project.db.session import get_db
from src.project.models.overview_layout import OverviewLayout
from src.project.models.project import Project
from src.project.models.repository import Repository
from src.project.schemas.settings import settings_view

router = APIRouter()
_basic = HTTPBasic(auto_error=False)


class ProjectRetention(BaseModel):
    project_id: int
    result_retention_days: int
    deleted: bool
    # When it was deleted: the retention job waits a grace period before emptying it
    deleted_at: Optional[datetime] = None
    # On legal hold: the retention job must delete nothing of it, whatever its age or deletion
    legal_hold: bool
    # Purge steps already confirmed for a deleted project (spec 2026-10-16), so a failed purge resumes
    purge_state: Optional[dict] = None


class RetentionList(BaseModel):
    projects: list[ProjectRetention]


def _same(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def require_internal_caller(credentials: Optional[HTTPBasicCredentials] = Depends(_basic)) -> None:
    if not settings.INTERNAL_API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Internal API is not configured")
    # Both parts are always compared, so the timing does not tell which one was wrong
    user_ok = credentials is not None and _same(credentials.username, settings.INTERNAL_API_USERNAME)
    password_ok = credentials is not None and _same(credentials.password, settings.INTERNAL_API_PASSWORD)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/projects/retention", response_model=RetentionList)
def list_retention(_: None = Depends(require_internal_caller), db: Session = Depends(get_db)):
    """Every project, deleted ones included, with its effective retention period."""
    projects = db.query(Project).order_by(Project.id).all()
    return RetentionList(projects=[
        ProjectRetention(
            project_id=project.id,
            result_retention_days=settings_view(project.settings).result_retention_days,
            deleted=project.deleted_at is not None,
            deleted_at=project.deleted_at,
            legal_hold=project.legal_hold_at is not None,
            purge_state=project.purge_state,
        )
        for project in projects
    ])


PURGE_STEPS = ("test_management", "ingestion")


class PurgeStepIn(BaseModel):
    # "started" first: from then on a restore is refused, so a restore and a purge never both win
    step: Literal["started", "test_management", "ingestion"]


def _pending_or_error(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project is not pending deletion")
    return project


@router.post("/projects/{project_id}/purge-state", status_code=status.HTTP_204_NO_CONTENT)
def record_purge_step(project_id: int, payload: PurgeStepIn, _: None = Depends(require_internal_caller),
                      db: Session = Depends(get_db)):
    """The purge job confirms one step for a deleted project (spec 2026-10-16 §5). 409 for a live project."""
    project = _pending_or_error(db, project_id)
    # A new dict, so SQLAlchemy sees the change
    project.purge_state = {**(project.purge_state or {}), payload.step: datetime.now(timezone.utc).isoformat()}
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_project(project_id: int, _: None = Depends(require_internal_caller), db: Session = Depends(get_db)):
    """The last purge step: the project row and what hangs off it. Only a pending project whose other services
    confirmed their part; a project already gone is 204 (the step is idempotent)."""
    if db.get(Project, project_id) is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    project = _pending_or_error(db, project_id)
    missing = [step for step in PURGE_STEPS if step not in (project.purge_state or {})]
    if missing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Purge steps missing: {', '.join(missing)}")
    # Children explicitly: SQLite (the tests) does not enforce ON DELETE CASCADE
    db.query(OverviewLayout).filter(OverviewLayout.project_id == project_id).delete(synchronize_session=False)
    db.query(Repository).filter(Repository.project_id == project_id).delete(synchronize_session=False)
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
