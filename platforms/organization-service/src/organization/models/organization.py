from sqlalchemy import Column, Integer, String, DateTime, CheckConstraint
from sqlalchemy.sql import func
from src.organization.db.base import Base


class Organization(Base):
    __tablename__ = "organizations"

    PLAN_TIERS = ("free", "pro", "enterprise", "enterprise_plus")

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    plan_tier = Column(String(50), nullable=False, default="free")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # Entra role sync (ADR-033) touches this organization only once an active superuser approved it: any user may
    # create and own an organization, so an owner's mapping alone must not let Entra add people to it.
    entra_sync_approved_at = Column(DateTime(timezone=True), nullable=True)
    entra_sync_approved_by = Column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "plan_tier IN ('free','pro','enterprise','enterprise_plus')", name="chk_plan_tier"
        ),
    )

    @property
    def entra_sync_approved(self) -> bool:
        return self.entra_sync_approved_at is not None
