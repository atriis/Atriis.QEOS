from sqlalchemy import Boolean, Column, DateTime, Integer, true, text

from src.ingestion.db.base import Base


class CollectionSettings(Base):
    """What a project collects (migration 019). No row: the defaults (collect everything)."""

    __tablename__ = "collection_settings"

    project_id = Column(Integer, primary_key=True, autoincrement=False)
    collect_manual = Column(Boolean, nullable=False, default=True, server_default=true())
    # Uploads, not runs: a matrix run uploads once per job
    discarded_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_discarded_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    updated_by = Column(Integer, nullable=True)
