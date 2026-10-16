from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, func
from src.organization.db.base import Base


class OrganizationSsoRoleMapping(Base):
    """An Entra app role value and the organization role it grants (spec 2026-10-16, ADR-033). Never owner."""

    __tablename__ = "organization_sso_role_mappings"

    ROLES = ("admin", "member", "viewer")

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    app_role = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('admin','member','viewer')", name="chk_sso_mapping_role"),
    )


# Case-insensitive uniqueness per organization; SQLite and PostgreSQL both support expression indexes
Index(
    "uq_org_sso_mapping_app_role",
    OrganizationSsoRoleMapping.organization_id,
    func.lower(OrganizationSsoRoleMapping.app_role),
    unique=True,
)
