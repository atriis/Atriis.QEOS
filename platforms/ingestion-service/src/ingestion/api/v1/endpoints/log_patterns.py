from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.api.deps import EDIT_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.ingestion.core.config import settings
from src.ingestion.jobs import log_scan
from src.ingestion.schemas.log_pattern import (
    LogPatternCreate, LogPatternListOut, LogPatternOut, LogPreviewIn, LogPreviewOut,
)
from src.ingestion.service import ingest_service, log_pattern_service, masking_pattern_service
from src.ingestion.utils import log_values
from src.ingestion.utils.log_values import LogPatternError

router = APIRouter()  # mounted at /projects/{project_id}/log-patterns


def _refused(exc: LogPatternError) -> HTTPException:
    """The reason and the form field it belongs to, so the dashboard shows it there."""
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                         detail={"code": exc.field, "message": str(exc)})


@router.get("", response_model=LogPatternListOut)
def list_log_patterns(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return {"patterns": log_pattern_service.list_patterns(db, access.project_id),
            "scan": log_scan.scan_state(db, access.project_id)}


@router.post("", response_model=LogPatternOut, status_code=status.HTTP_201_CREATED)
def add_log_pattern(
    payload: LogPatternCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    """Adds the pattern and queues a re-scan of the last 90 days, which runs after the response (ADR-032)."""
    try:
        row = log_pattern_service.add_pattern(
            db, access.project_id, payload.name, payload.pattern, payload.link_template, access.user_id)
    except LogPatternError as exc:
        raise _refused(exc)
    except log_pattern_service.DuplicatePattern as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "name", "message": str(exc)})
    out = LogPatternOut.model_validate(row)
    log_scan.request_scan(db, access.project_id)
    background.add_task(log_scan.run_scan, sessionmaker(bind=db.get_bind()), access.project_id)
    return out


@router.post("/preview", response_model=LogPreviewOut)
def preview_log_pattern(
    payload: LogPreviewIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    """The sample as it would be stored (masked with the built-in rules and the project's masking patterns, cut at
    64 KB) and the values this pattern finds in it. Nothing is saved."""
    try:
        pattern = log_pattern_service.validate(payload.name, payload.pattern)
    except LogPatternError as exc:
        raise _refused(exc)
    masked, _ = ingest_service.mask(payload.sample, tuple(masking_pattern_service.compiled_for(db, access.project_id)))
    masked = ingest_service.truncate_utf8(masked, settings.MAX_TEXT_BYTES)[0]
    return LogPreviewOut(masked=masked, values=[value for _, _, value in log_values.extract(masked, [pattern])])


@router.delete("/{pattern_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log_pattern(
    pattern_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    if not log_pattern_service.delete_pattern(db, access.project_id, pattern_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log-value pattern not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
