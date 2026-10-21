"""Result artifacts (ADR-037): the traces a result carries. The bytes are a `blobs` row of kind `trace`."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func

from src.ingestion.db.base import Base

ARTIFACT_NAME_LENGTH = 200  # result_artifacts.name


class ResultArtifact(Base):
    """One artifact of one result, `position` its order. Like result_screenshots, the rows go with their result by
    ON DELETE CASCADE in PostgreSQL; SQLite (the tests) does not enforce it, so retention deletes them explicitly.
    Only kind `trace` exists now; videos would add theirs."""

    __tablename__ = "result_artifacts"
    __table_args__ = (
        CheckConstraint("kind IN ('trace')", name="chk_result_artifacts_kind"),
        Index("ix_result_artifacts_result_position", "result_id", "position"),
        # The garbage collector asks which blobs nothing refers to any more
        Index("ix_result_artifacts_blob_id", "blob_id"),
    )

    id = Column(Integer, primary_key=True)
    result_id = Column(Integer, ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    blob_id = Column(Integer, ForeignKey("blobs.id"), nullable=False)
    kind = Column(String(16), nullable=False)
    name = Column(String(ARTIFACT_NAME_LENGTH), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
