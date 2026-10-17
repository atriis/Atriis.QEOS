"""A superuser's approval of Entra role sync per organization (ADR-033 amendment, 2026-10-17).

Any user may create an organization and own it, so an owner's mapping alone would let them make Entra add every
person holding a mapped app role to their organization, and read those people's addresses in its member list.
reconcile therefore touches an organization only after an active superuser approved it here.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.organization.api.deps import get_db, require_active_superuser
from src.organization.schemas.organization import EntraSyncEntry, EntraSyncUpdate, OrganizationOut
from src.organization.service import sso_role_service

router = APIRouter()


# Mounted before the organizations router: its /{org_id} route would otherwise answer 422 for "entra-sync"
@router.get("/entra-sync", response_model=list[EntraSyncEntry])
def list_entra_sync(db: Session = Depends(get_db), _superuser: int = Depends(require_active_superuser)):
    """Organizations that have a mapping or an approval, by name."""
    return sso_role_service.list_sync_organizations(db)


@router.put("/{org_id}/entra-sync", response_model=OrganizationOut)
def set_entra_sync(org_id: int, payload: EntraSyncUpdate, db: Session = Depends(get_db),
                   superuser_id: int = Depends(require_active_superuser)):
    org = sso_role_service.set_sync_approval(db, org_id, payload.approved, superuser_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org
