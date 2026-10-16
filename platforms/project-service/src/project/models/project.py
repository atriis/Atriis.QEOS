from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from src.project.db.base import Base

# JSONB on PostgreSQL, plain JSON on SQLite (tests)
SettingsJSON = JSON().with_variant(JSONB(), "postgresql")
# None is SQL NULL here, not JSON null, so "no purge step yet" is one value a WHERE can test
PurgeStateJSON = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")

_LIVE = text("deleted_at IS NULL")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    # No FK: organizations live in organization-service's database
    organization_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    # Only explicitly-set keys are stored; defaults come from schemas.settings.ProjectSettings.
    # Always assign a new dict -- SQLAlchemy does not see in-place mutation of a JSON value.
    settings = Column(SettingsJSON, nullable=False, default=dict)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # Who deleted it (spec 2026-10-16), and which purge steps were confirmed: {"started": iso, "test_management": iso, ...}
    deleted_by = Column(Integer, nullable=True)
    purge_state = Column(PurgeStateJSON, nullable=True)
    # Legal hold: while set, retention deletes nothing of this project. Columns, not a settings
    # key: only owners and admins may change it, and who/when/why must be recorded.
    legal_hold_at = Column(DateTime(timezone=True), nullable=True)
    legal_hold_by = Column(Integer, nullable=True)
    legal_hold_reason = Column(String(500), nullable=True)

    __table_args__ = (
        # Unique among live projects only, so a deleted project's name and slug can be reused
        Index(
            "uq_project_org_name", "organization_id", "name",
            unique=True, sqlite_where=_LIVE, postgresql_where=_LIVE,
        ),
        Index(
            "uq_project_org_slug", "organization_id", "slug",
            unique=True, sqlite_where=_LIVE, postgresql_where=_LIVE,
        ),
    )
