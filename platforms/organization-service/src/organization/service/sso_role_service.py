"""Entra app roles to organization roles (spec 2026-10-16, ADR-033)."""
import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.organization.models.sso_role_mapping import OrganizationSsoRoleMapping

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
