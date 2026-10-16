from typing import Optional
from sqlalchemy.orm import Session
from src.organization.models.member import OrganizationMember
from src.organization.utils.auth_client import user_exists


class ManagedByEntra(Exception):
    """The member is created and kept in step by the Entra app-role mapping; removing it by hand would be undone at
    their next Microsoft sign-in (ADR-033)."""


def get_role(db: Session, org_id: int, user_id: int) -> Optional[str]:
    member = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        )
        .first()
    )
    return member.role if member else None


def _assert_can_grant_role(granter_role: str, target_role: str) -> None:
    """Only an owner may grant, or remove a member holding, an owner/admin-tier role.

    Shared by add_member (granting), remove_member (removing a privileged member is as much
    a takeover as granting the role), and invitation_service.create_invitation (checked once,
    against the inviter's role, at invite-creation time -- accept_invitation does not call
    this again, see _create_member_row below).
    """
    if target_role in ("owner", "admin") and granter_role != "owner":
        raise PermissionError(f"only an owner can grant or remove the '{target_role}' role")


def _create_member_row(db: Session, org_id: int, user_id: int, role: str) -> OrganizationMember:
    """The mechanism only -- no grant-policy check.

    add_member calls _assert_can_grant_role first, then this. invitation_service.accept_invitation
    calls this directly: the policy was already checked once, against the inviter's role, when the
    invitation was created -- re-checking it here against the ACCEPTER's role (who has none yet)
    would be wrong, not just redundant.
    """
    if role not in OrganizationMember.ROLES:
        raise ValueError(f"invalid role: {role}")
    if not user_exists(user_id):
        raise ValueError("user not found")

    existing = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.organization_id == org_id, OrganizationMember.user_id == user_id)
        .first()
    )
    if existing:
        raise ValueError("already a member")

    member = OrganizationMember(organization_id=org_id, user_id=user_id, role=role, status="active")
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def add_member(db: Session, org_id: int, user_id: int, role: str, granter_role: str) -> OrganizationMember:
    _assert_can_grant_role(granter_role, role)
    return _create_member_row(db, org_id, user_id, role)


def list_members(db: Session, org_id: int) -> list[OrganizationMember]:
    return (
        db.query(OrganizationMember)
        .filter(OrganizationMember.organization_id == org_id, OrganizationMember.status == "active")
        .all()
    )


def remove_member(db: Session, org_id: int, member_id: int, granter_role: str) -> bool:
    member = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.id == member_id, OrganizationMember.organization_id == org_id)
        .first()
    )
    if member is None:
        return False

    if member.managed_by == "entra":
        raise ManagedByEntra()

    _assert_can_grant_role(granter_role, member.role)

    if member.role == "owner":
        owner_count = (
            db.query(OrganizationMember)
            .filter(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.role == "owner",
                OrganizationMember.status == "active",
            )
            .count()
        )
        if owner_count <= 1:
            raise ValueError("cannot remove the last owner")

    db.delete(member)
    db.commit()
    return True
