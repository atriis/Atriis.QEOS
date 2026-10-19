"""Step screenshots (ADR-036): the stored images and the results that show them."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from src.ingestion.db.base import Base


class Blob(Base):
    """One stored image per (project, sha256), shared by every result that shows it. The bytes live in the artifact
    store; deleting a row is the garbage collector's job, so nothing here cascades."""

    __tablename__ = "blobs"
    __table_args__ = (UniqueConstraint("project_id", "sha256", name="uq_blobs_project_sha256"),)

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    media_type = Column(String(32), nullable=False)
    bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ResultScreenshot(Base):
    """One image of one result, `position` its order. The rows go with their result (ON DELETE CASCADE; the code also
    deletes them explicitly, because SQLite, the tests, does not enforce it)."""

    __tablename__ = "result_screenshots"
    __table_args__ = (
        Index("ix_result_screenshots_result_position", "result_id", "position"),
        # The garbage collector asks which blobs nothing refers to any more
        Index("ix_result_screenshots_blob_id", "blob_id"),
    )

    id = Column(Integer, primary_key=True)
    result_id = Column(Integer, ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    blob_id = Column(Integer, ForeignKey("blobs.id"), nullable=False)
    step_text = Column(String(1000), nullable=False)
    step_line = Column(Integer, nullable=True)
    hook = Column(String(8), nullable=True)
