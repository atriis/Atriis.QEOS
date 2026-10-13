from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from src.ingestion.api.deps import EDIT_ROLES, MANAGE_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.ingestion.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, ApiKeyUpdate
from src.ingestion.service import api_key_service

router = APIRouter()  # mounted at /projects/{project_id}/api-keys

# Reading test suggestions exposes test names and path units: only owners and admins grant it (spec 2026-10-13 §9)
IMPACT_FORBIDDEN = "Only owners and admins can allow a key to read test suggestions"


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: ApiKeyCreate,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    if payload.can_read_impact and access.role not in MANAGE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=IMPACT_FORBIDDEN)
    row, key = api_key_service.create_key(db, access, payload.name, payload.can_read_impact)
    return ApiKeyCreated(id=row.id, name=row.name, key_prefix=row.key_prefix, key=key,
                         can_read_impact=row.can_read_impact, created_at=row.created_at)


@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return api_key_service.list_keys(db, access.project_id)


@router.patch("/{key_id}", response_model=ApiKeyOut)
def update_api_key(
    key_id: int,
    payload: ApiKeyUpdate,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    """Allow or stop the key's reading of test suggestions. A revoked key cannot be changed (409)."""
    row = api_key_service.get_key(db, access.project_id, key_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    if row.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="API key is revoked")
    return api_key_service.set_can_read_impact(db, row, payload.can_read_impact)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    if not api_key_service.revoke_key(db, access.project_id, key_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
