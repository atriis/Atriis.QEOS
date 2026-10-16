import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.project.core.config import settings
from src.project.models.project import Project
from src.project.schemas.project import ProjectCreate, ProjectUpdate
from src.project.schemas.settings import merge_settings


class DuplicateProject(Exception):
    pass


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:100].rstrip("-")


UNIQUE_VIOLATION = "23505"  # PostgreSQL SQLSTATE


def _is_unique_violation(exc: IntegrityError) -> bool:
    # psycopg 3 (what this service runs) names it sqlstate; psycopg 2 named it pgcode
    if (getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)) == UNIQUE_VIOLATION:
        return True
    return "UNIQUE constraint failed" in str(exc.orig)  # SQLite, used by the test suite


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        # roll back so the session stays usable for the rest of the request and the next one
        db.rollback()
        if _is_unique_violation(exc):
            raise DuplicateProject("A project with this name or slug already exists in the organization")
        raise  # any other integrity failure is a bug, not a duplicate: surface it as a 500


def create_project(db: Session, org_id: int, user_id: int, data: ProjectCreate) -> Project:
    slug = data.slug or slugify(data.name)
    if not slug:
        raise ValueError("Could not derive a slug from the project name; supply one")
    project = Project(
        organization_id=org_id,
        name=data.name,
        slug=slug,
        description=data.description,
        settings={},
        created_by=user_id,
    )
    db.add(project)
    _commit(db)
    db.refresh(project)
    return project


def list_projects(db: Session, org_id: int, limit: int, offset: int, include_pending: bool = False) -> list[Project]:
    query = db.query(Project).filter(Project.organization_id == org_id)
    if not include_pending:
        query = query.filter(Project.deleted_at.is_(None))
    return query.order_by(Project.id).offset(offset).limit(limit).all()


def update_project(db: Session, project: Project, data: ProjectUpdate) -> Project:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    _commit(db)
    db.refresh(project)
    return project


def update_settings(db: Session, project: Project, patch: dict) -> Project:
    # merge_settings returns a new dict, which is what makes SQLAlchemy see the change
    project.settings = merge_settings(project.settings, patch)
    db.commit()
    db.refresh(project)
    return project


def place_legal_hold(db: Session, project: Project, user_id: int, reason: str) -> Project:
    project.legal_hold_at = datetime.now(timezone.utc)
    project.legal_hold_by = user_id
    project.legal_hold_reason = reason
    db.commit()
    db.refresh(project)
    return project


def release_legal_hold(db: Session, project: Project) -> Project:
    project.legal_hold_at = project.legal_hold_by = project.legal_hold_reason = None
    db.commit()
    db.refresh(project)
    return project


class LegalHoldActive(Exception):
    pass


class PurgeStarted(Exception):
    pass


def purge_at(project: Project) -> datetime:
    deleted_at = project.deleted_at if project.deleted_at.tzinfo else project.deleted_at.replace(tzinfo=timezone.utc)
    return deleted_at + timedelta(days=settings.PROJECT_DELETE_GRACE_DAYS)


def soft_delete(db: Session, project: Project, user_id: int) -> None:
    """Pending deletion: hidden from everyone but owners and admins, restorable until purge_at, then purged by the
    ingestion retention job (spec 2026-10-16). Data under a legal hold cannot be deleted."""
    if project.legal_hold_at is not None:
        raise LegalHoldActive("Release the legal hold before deleting this project")
    project.deleted_at = datetime.now(timezone.utc)
    project.deleted_by = user_id
    project.purge_state = None  # SQL NULL (none_as_null): restore's conditional UPDATE tests it
    db.commit()


def get_pending(db: Session, project_id: int) -> Optional[Project]:
    return db.query(Project).filter(Project.id == project_id, Project.deleted_at.isnot(None)).first()


PURGE_STARTED = "The purge has started; this project can no longer be restored"


def restore(db: Session, project: Project) -> Project:
    """One conditional UPDATE against the purge job's "started" step (ADR-033): whichever commits first wins, and
    the other matches no row. Under READ COMMITTED a blocked UPDATE re-checks its WHERE after the other commits."""
    if project.purge_state:
        raise PurgeStarted(PURGE_STARTED)
    try:
        restored = (
            db.query(Project)
            .filter(Project.id == project.id, Project.deleted_at.isnot(None), Project.purge_state.is_(None))
            .update({Project.deleted_at: None, Project.deleted_by: None}, synchronize_session=False)
        )
    except IntegrityError as exc:
        # The UPDATE itself hits the live-rows unique index when the name or slug was reused meanwhile
        db.rollback()
        if _is_unique_violation(exc):
            raise DuplicateProject("A live project already uses this name or slug; rename it first")
        raise
    if restored == 0:
        # The purge started after this request read the row (or it was restored meanwhile)
        db.rollback()
        raise PurgeStarted(PURGE_STARTED)
    try:
        _commit(db)
    except DuplicateProject:
        raise DuplicateProject("A live project already uses this name or slug; rename it first")
    db.refresh(project)
    return project
