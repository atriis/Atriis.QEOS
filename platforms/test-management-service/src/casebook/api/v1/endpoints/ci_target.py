"""GET/PUT/DELETE /projects/{id}/ci-target (run-from-QEOS spec)."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from src.casebook.api.deps import MANAGE_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.casebook.schemas.ci import CiTargetIn, CiTargetOut, clean_token
from src.casebook.service import ci_target_service, run_request_service
from src.casebook.utils import github_client, secret_box

router = APIRouter()  # mounted at /projects/{project_id}/ci-target


def github_failure(exc: github_client.GitHubError, refused_status: int) -> HTTPException:
    """GitHub's answer as ours: a rate limit is 503 with Retry-After (a 429 detail is hidden by the
    dashboard), a refusal of the token or names is `refused_status`, the rest is 502."""
    if isinstance(exc, github_client.RateLimited):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message,
                             headers={"Retry-After": str(exc.retry_after)})
    if exc.status in (401, 403, 404):
        return HTTPException(refused_status, detail=exc.message)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=exc.message)


@router.get("", response_model=CiTargetOut)
def get_ci_target(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return ci_target_service.out(db, access.project_id)


@router.put("", response_model=CiTargetOut)
def put_ci_target(
    payload: CiTargetIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    try:
        token = clean_token(payload.token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    try:
        ci_target_service.save_target(db, access.project_id, access.user_id, payload.repo, payload.workflow,
                                      payload.ref, token)
    except secret_box.SecretsUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except ci_target_service.TokenRequired:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="token: required on the first save")
    except github_client.GitHubError as exc:
        raise github_failure(exc, status.HTTP_422_UNPROCESSABLE_ENTITY)
    return ci_target_service.out(db, access.project_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_ci_target(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    for active in run_request_service.active_requests(db, access.project_id):
        run_request_service.refresh(db, active, force=True)  # a run that ended unseen must not block Disconnect
    if ci_target_service.has_active_run(db, access.project_id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A run is in progress: stop it or wait for it to end")
    if not ci_target_service.delete_target(db, access.project_id, access.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No CI target configured")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
