"""POST/GET /projects/{id}/run-requests (run-from-QEOS spec): Play and its state."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.casebook.api.deps import EDIT_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.casebook.api.v1.endpoints.ci_target import github_failure
from src.casebook.schemas.ci import RunRequestIn, RunRequestList, RunRequestOut
from src.casebook.service import run_request_service as runs
from src.casebook.utils import github_client, secret_box

router = APIRouter()  # mounted at /projects/{project_id}/run-requests

NO_TARGET = "No CI target: configure one in Project Settings"


def _row_or_404(db: Session, access: ProjectAccess, request_id: int):
    row = runs.get_request(db, access.project_id, request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run request not found")
    return row


@router.post("", response_model=RunRequestOut, status_code=status.HTTP_201_CREATED)
def create_run_request(
    payload: RunRequestIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    try:
        row = runs.create(db, access.project_id, access.user_id, payload.case_numbers, payload.suite_id,
                          payload.estimate_ms, payload.estimate_upper_ms, payload.workflow_group)
    except runs.NoTarget:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, detail=NO_TARGET)
    except secret_box.SecretsUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except runs.SuiteNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Suite not found")
    except runs.BadSelection as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except runs.RunActive as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": "run_active", "message": str(exc), "run_request_id": exc.request_id})
    except runs.RepositoryNotTarget as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "repository_mismatch", "message": str(exc)})
    except runs.WorkflowBusy as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": "workflow_busy", "message": str(exc), "run_url": exc.run_url})
    except runs.GitHubUnavailable as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, headers=headers, detail={
            "code": "github_unavailable", "message": str(exc)})
    except github_client.RateLimited as exc:
        raise github_failure(exc, status.HTTP_502_BAD_GATEWAY)
    return runs.out(row)


@router.get("", response_model=RunRequestList)
def list_run_requests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    total, rows = runs.list_requests(db, access.project_id, limit, offset)
    return {"total": total, "items": [runs.out(r) for r in rows]}


@router.get("/run-urls")
def run_urls(
    since: datetime = Query(...),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """The Play requests' GitHub run URLs, for the report's origin filter (ADR-026)."""
    moment = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    if moment < datetime.now(timezone.utc) - timedelta(days=runs.RUN_URLS_MAX_AGE_DAYS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"since is more than {runs.RUN_URLS_MAX_AGE_DAYS} days ago")
    urls, truncated = runs.run_urls(db, access.project_id, moment)
    return {"urls": urls, "truncated": truncated}


@router.get("/{request_id}", response_model=RunRequestOut)
def get_run_request(
    request_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return runs.out(_row_or_404(db, access, request_id))


@router.post("/{request_id}/stop", response_model=RunRequestOut)
def stop_run_request(
    request_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    row = _row_or_404(db, access, request_id)
    try:
        row = runs.stop(db, row, access.user_id)
    except runs.AlreadyFinished:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": "run_finished", "message": "This run has already finished"})
    except runs.NoTarget:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, detail=NO_TARGET)
    except secret_box.SecretsUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except github_client.GitHubError as exc:
        raise github_failure(exc, status.HTTP_502_BAD_GATEWAY)
    return runs.out(row)
