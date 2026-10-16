"""Entra app roles to organization roles (spec 2026-10-16, ADR-033)."""
import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.organization.models.member import OrganizationMember
from src.organization.models.organization import Organization
from src.organization.models.sso_role_mapping import OrganizationSsoRoleMapping
from src.organization.schemas.sso_role_mapping import SsoRoleChange

logger = logging.getLogger(__name__)


class DuplicateAppRole(Exception):
    pass


def normalize_app_role(value: str) -> str:
    return value.strip().lower()


def list_mappings(db: Session, org_id: int) -> list[OrganizationSsoRoleMapping]:
    return (db.query(OrganizationSsoRoleMapping)
            .filter(OrganizationSsoRoleMapping.organization_id == org_id)
            .order_by(func.lower(OrganizationSsoRoleMapping.app_role))
            .all())


def create_mapping(db: Session, org_id: int, app_role: str, role: str) -> OrganizationSsoRoleMapping:
    taken = (db.query(OrganizationSsoRoleMapping)
             .filter(OrganizationSsoRoleMapping.organization_id == org_id,
                     func.lower(OrganizationSsoRoleMapping.app_role) == normalize_app_role(app_role))
             .first())
    if taken is not None:
        raise DuplicateAppRole(app_role)
    mapping = OrganizationSsoRoleMapping(organization_id=org_id, app_role=app_role.strip(), role=role)
    db.add(mapping)
    try:
        db.commit()
    except IntegrityError:  # the unique index, when two owners add the same value at once
        db.rollback()
        raise DuplicateAppRole(app_role)
    db.refresh(mapping)
    return mapping


def delete_mapping(db: Session, org_id: int, mapping_id: int) -> bool:
    mapping = (db.query(OrganizationSsoRoleMapping)
               .filter(OrganizationSsoRoleMapping.id == mapping_id,
                       OrganizationSsoRoleMapping.organization_id == org_id)
               .first())
    if mapping is None:
        return False
    db.delete(mapping)
    db.commit()
    return True


_RANK = {"viewer": 1, "member": 2, "admin": 3}


def _winning_role(mappings: list[OrganizationSsoRoleMapping], wanted: set[str]) -> tuple[str | None, list[str]]:
    matched = [m for m in mappings if normalize_app_role(m.app_role) in wanted]
    if not matched:
        return None, []
    best = max(matched, key=lambda m: _RANK[m.role])
    return best.role, sorted(m.app_role.strip() for m in matched)


def _log(org_id: int, user_id: int, action: str, old, new, matched: list[str]) -> None:
    logger.info("entra role: org=%s user=%s %s %s->%s roles=%s", org_id, user_id, action, old, new, ",".join(matched))


def _apply(db: Session, org_id: int, user_id: int, role: str | None, matched: list[str]) -> SsoRoleChange | None:
    row = db.query(OrganizationMember).filter_by(organization_id=org_id, user_id=user_id).one_or_none()
    if row is not None and row.managed_by != "entra":
        return None  # made by hand: the mapping never touches it
    if row is None:
        if role is None:
            return None
        db.add(OrganizationMember(organization_id=org_id, user_id=user_id, role=role, status="active", managed_by="entra"))
        _log(org_id, user_id, "created", None, role, matched)
        return SsoRoleChange(organization_id=org_id, action="created", from_role=None, to_role=role)
    if role is None:
        old = row.role
        db.delete(row)
        _log(org_id, user_id, "removed", old, None, matched)
        return SsoRoleChange(organization_id=org_id, action="removed", from_role=old, to_role=None)
    if row.role != role:
        old, row.role = row.role, role
        _log(org_id, user_id, "updated", old, role, matched)
        return SsoRoleChange(organization_id=org_id, action="updated", from_role=old, to_role=role)
    return None


def reconcile(db: Session, user_id: int, roles: list[str]) -> list[SsoRoleChange]:
    """Rules of spec 2026-10-16 §3 for every live organization that has a mapping; one commit per organization,
    so a concurrent sign-in that created the same row (R5) costs only that organization's retry."""
    wanted = {normalize_app_role(r) for r in roles if r.strip()}
    org_ids = [row[0] for row in (db.query(OrganizationSsoRoleMapping.organization_id)
                                  .join(Organization, Organization.id == OrganizationSsoRoleMapping.organization_id)
                                  .filter(Organization.deleted_at.is_(None))
                                  .distinct().order_by(OrganizationSsoRoleMapping.organization_id).all())]
    changes: list[SsoRoleChange] = []
    for org_id in org_ids:
        role, matched = _winning_role(list_mappings(db, org_id), wanted)
        change = _apply(db, org_id, user_id, role, matched)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            change = _apply(db, org_id, user_id, role, matched)
            db.commit()
        if change is not None:
            changes.append(change)
    return changes
