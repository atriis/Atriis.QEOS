"""The Entra app-role mapping of an organization (ADR-033): owners only, so whoever edits app-role assignments
in Entra can never reach this editor through a role the mapping itself grants."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.organization.api.deps import get_db, require_org_role
from src.organization.schemas.sso_role_mapping import SsoRoleMappingCreate, SsoRoleMappingOut
from src.organization.service import sso_role_service

router = APIRouter()


@router.get("", response_model=list[SsoRoleMappingOut])
def list_mappings(org_id: int, db: Session = Depends(get_db), _role: str = Depends(require_org_role("owner"))):
    return sso_role_service.list_mappings(db, org_id)


@router.post("", response_model=SsoRoleMappingOut, status_code=status.HTTP_201_CREATED)
def create_mapping(org_id: int, payload: SsoRoleMappingCreate, db: Session = Depends(get_db),
                   _role: str = Depends(require_org_role("owner"))):
    try:
        return sso_role_service.create_mapping(db, org_id, payload.app_role, payload.role)
    except sso_role_service.DuplicateAppRole:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "duplicate_app_role", "message": "This app role is already mapped."})


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(org_id: int, mapping_id: int, db: Session = Depends(get_db),
                   _role: str = Depends(require_org_role("owner"))):
    if not sso_role_service.delete_mapping(db, org_id, mapping_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
