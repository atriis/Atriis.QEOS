from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from src.organization.api.deps import get_db, require_org_role
from src.organization.models.member import OrganizationMember
from src.organization.schemas.member import MemberCreate, MemberOut, MyRoleOut
from src.organization.service import member_service
from src.organization.utils.auth_client import AuthServiceUnavailable, emails_by_ids

router = APIRouter()


@router.post("", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    org_id: int,
    payload: MemberCreate,
    db: Session = Depends(get_db),
    granter_role: str = Depends(require_org_role("owner", "admin")),
):
    try:
        member = member_service.add_member(db, org_id, payload.user_id, payload.role, granter_role)
    except AuthServiceUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return member


@router.get("", response_model=list[MemberOut])
def list_members(
    org_id: int,
    db: Session = Depends(get_db),
    # any member role may list; require_org_role also 404s on a soft-deleted org
    _role: str = Depends(require_org_role(*OrganizationMember.ROLES)),
):
    members = member_service.list_members(db, org_id)
    emails = emails_by_ids([m.user_id for m in members])  # best effort: {} when auth is down
    enriched = []
    for member in members:
        out = MemberOut.model_validate(member, from_attributes=True)
        out.email = emails.get(member.user_id)
        enriched.append(out)
    return enriched


@router.get("/me", response_model=MyRoleOut)
def my_role(
    org_id: int,
    # require_org_role already 404s on a soft-deleted org and on anyone who is not an *active* member
    role: str = Depends(require_org_role(*OrganizationMember.ROLES)),
):
    return {"role": role}


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    org_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    granter_role: str = Depends(require_org_role("owner", "admin")),
):
    try:
        removed = member_service.remove_member(db, org_id, member_id, granter_role)
    except member_service.ManagedByEntra:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "managed_by_entra", "message": "Managed by Entra: remove the app role instead."})
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
