from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.sql import func

from src.project.db.base import Base
from src.project.models.project import SettingsJSON

# The project default is the row without a user
_DEFAULT_ROW = text("user_id IS NULL")


class OverviewLayout(Base):
    """An Overview layout (spec 2026-10-11 §3.1): the project default (user_id NULL) or one user's personal layout.

    `layout` is validated against shared/qeos_shared/overview_widgets.json before it is stored. `version` grows by one
    on every save; a save names the version it started from, and a stale one is refused (409).
    """

    __tablename__ = "overview_layouts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    # No FK: users live in auth-service's database
    user_id = Column(Integer, nullable=True)
    layout = Column(SettingsJSON, nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # NULLs are distinct in a unique constraint, so this holds the personal rows only
        UniqueConstraint("project_id", "user_id", name="uq_overview_layouts_project_user"),
        Index(
            "uq_overview_layouts_project_default", "project_id",
            unique=True, sqlite_where=_DEFAULT_ROW, postgresql_where=_DEFAULT_ROW,
        ),
    )
