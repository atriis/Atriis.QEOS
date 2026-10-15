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
    # The log-value re-scan (ADR-032, migration 023). Adding a pattern bumps log_scan_requested; a pass that finishes
    # sets log_scan_done to the number it started from. A scan is queued or running while requested > done;
    # log_scan_started_at is the current pass's start (None between passes)
    log_scan_requested = Column(Integer, nullable=False, default=0, server_default=text("0"))
    log_scan_done = Column(Integer, nullable=False, default=0, server_default=text("0"))
    log_scan_started_at = Column(DateTime(timezone=True), nullable=True)
