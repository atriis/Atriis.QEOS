"""Log-value patterns and the values they found in each result's masked log (ADR-032)."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from src.ingestion.db.base import Base

LOG_VALUE_LENGTH = 200


class LogPattern(Base):
    """A project's pattern for values in its test logs: RE2, at most one capture group, an optional https link."""

    __tablename__ = "log_patterns"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_log_pattern_project_name"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    name = Column(String(32), nullable=False)
    pattern = Column(String(256), nullable=False)
    link_template = Column(String(500), nullable=True)
    created_by_user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LogValue(Base):
    """One distinct value one pattern found in one result's log; `position` is its order of first appearance.
    The rows go with their result and with their pattern (ON DELETE CASCADE; the code also deletes them explicitly,
    because SQLite, the tests, does not enforce it)."""

    __tablename__ = "log_values"
    __table_args__ = (
        Index("ix_log_values_result_id", "result_id"),
        # A deleted pattern's values are found by pattern
        Index("ix_log_values_pattern_id", "pattern_id"),
        # The runs search by a value (migration 024, spec 2026-10-15 §3.1): value first, the pattern narrows it
        Index("ix_log_values_value", "value", "pattern_id"),
    )

    id = Column(Integer, primary_key=True)
    result_id = Column(Integer, ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False)
    pattern_id = Column(Integer, ForeignKey("log_patterns.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    value = Column(String(LOG_VALUE_LENGTH), nullable=False)
