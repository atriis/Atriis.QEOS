from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.sql import func
from src.organization.db.base import Base


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    ROLES = ("owner", "admin", "member", "viewer", "billing_manager")
    STATUSES = ("pending", "active", "suspended", "removed")
    MANAGED_BY = ("entra",)

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    role = Column(String(50), nullable=False, default="member")
    status = Column(String(20), nullable=False, default="active")
    # NULL: made by hand (invitation, creator, add member). "entra": created and kept in step by the Entra
    # app-role mapping at each Microsoft sign-in (ADR-033); never touched by hand
    managed_by = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        CheckConstraint("role IN ('owner','admin','member','viewer','billing_manager')", name="chk_member_role"),
        CheckConstraint("status IN ('pending','active','suspended','removed')", name="chk_member_status"),
        CheckConstraint("managed_by IS NULL OR managed_by IN ('entra')", name="chk_member_managed_by"),
    )
