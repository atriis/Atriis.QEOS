from sqlalchemy import (JSON, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, text)
from sqlalchemy.sql import func

from src.casebook.db.base import Base


class Suite(Base):
    """A named, ordered list of a project's cases, or (origin "repository") one CI workflow leg mirrored read-only."""

    __tablename__ = "suites"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_suites_project_name"),
        CheckConstraint("origin IN ('manual','repository')", name="chk_suites_origin"),
        Index("uq_suites_repository_leg", "project_id", "workflow", "external_id", unique=True,
              postgresql_where=text("origin = 'repository'"), sqlite_where=text("origin = 'repository'")),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    # Repository suites come from the test repository's CI workflows (sync); all null for a manual suite
    origin = Column(String(20), nullable=False, default="manual", server_default="manual")
    workflow = Column(String(100), nullable=True)  # the workflow file the leg belongs to
    group_name = Column(String(100), nullable=True)
    external_id = Column(String(200), nullable=True)  # the leg's id inside the workflow
    shard = Column(String(100), nullable=True)
    test_paths = Column(JSON, nullable=True)
    source_repo = Column(String(200), nullable=True)


class SuiteCase(Base):
    __tablename__ = "suite_cases"
    __table_args__ = (UniqueConstraint("suite_id", "case_id", name="uq_suite_cases_suite_case"),)

    id = Column(Integer, primary_key=True)
    suite_id = Column(Integer, ForeignKey("suites.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
