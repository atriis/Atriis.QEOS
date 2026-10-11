"""The project Overview's layout (spec 2026-10-11 §3.3). GET resolves personal -> project default -> built-in
(`effective` null: the dashboard holds the built-in default). The role check runs before anything is read, so a
personal layout of someone who has left the organization is never served (§3.4)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from src.project.api.deps import MANAGE_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.project.models.overview_layout import OverviewLayout
from src.project.schemas.overview_layout import (
    MAX_BODY_BYTES, LayoutIn, LayoutRowOut, OverviewLayoutOut, PersonalMeta, ProjectMeta,
)
from src.project.service import overview_layout_service as layouts

router = APIRouter()  # mounted at /projects/{project_id}/overview-layout


async def limit_body(request: Request) -> None:
    """Refuses a body over the catalogue's 64 KB (plan Ruling 6). Declared after the role dependency, so it runs after it."""
    if len(await request.body()) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"The layout body is over {MAX_BODY_BYTES // 1024} KB",
        )


def _row(row: OverviewLayout) -> LayoutRowOut:
    return LayoutRowOut(layout=row.layout, version=row.version, updated_by=row.updated_by, updated_at=row.updated_at)


def _conflict(exc: layouts.StaleVersion) -> HTTPException:
    current = exc.current
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "stale_version",
            "message": "This layout was changed since you started editing it",
            "current": None if current is None else {
                "version": current.version,
                "updated_by": current.updated_by,
                "updated_at": current.updated_at.isoformat(),
            },
        },
    )


def _save(db: Session, project_id: int, user_id: Optional[int], payload: LayoutIn, by: int) -> LayoutRowOut:
    try:
        return _row(layouts.save(db, project_id, user_id, payload.layout, payload.version, by=by))
    except layouts.StaleVersion as exc:
        raise _conflict(exc)


@router.get("", response_model=OverviewLayoutOut)
def get_layout(
    project_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    personal = layouts.get_row(db, project_id, access.user_id)
    project = layouts.get_row(db, project_id, None)
    source = "personal" if personal else "project" if project else "builtin"
    effective = personal.layout if personal else project.layout if project else None
    return OverviewLayoutOut(
        effective=effective,
        source=source,
        personal=PersonalMeta(version=personal.version, updated_at=personal.updated_at) if personal else None,
        project=ProjectMeta(
            version=project.version, updated_by=project.updated_by, updated_at=project.updated_at, layout=project.layout,
        ) if project else None,
    )


@router.put("/personal", response_model=LayoutRowOut)
def save_personal(
    project_id: int,
    payload: LayoutIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
    _limit: None = Depends(limit_body),
):
    return _save(db, project_id, access.user_id, payload, by=access.user_id)


@router.delete("/personal", status_code=status.HTTP_204_NO_CONTENT)
def reset_personal(
    project_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    layouts.delete(db, project_id, access.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/project", response_model=LayoutRowOut)
def save_project_default(
    project_id: int,
    payload: LayoutIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
    _limit: None = Depends(limit_body),
):
    return _save(db, project_id, None, payload, by=access.user_id)


@router.delete("/project", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_default(
    project_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    layouts.delete(db, project_id, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
