"""Running tests from QEOS (docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md)."""
from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, Text, text

from src.casebook.db.base import Base

ACTIVE_STATUSES = ("queued", "running", "cancelling")
RUN_STATUSES = ("queued", "running", "completed", "cancelling", "cancelled", "failed_to_start")
EVENT_ACTIONS = ("created", "updated", "token_replaced", "deleted")
ACTIVE_WHERE = "status IN ('queued','running','cancelling')"


class CiTarget(Base):
    """Where Play dispatches for one project: a GitHub repository, workflow file, branch and token."""

    __tablename__ = "ci_targets"

    project_id = Column(Integer, primary_key=True, autoincrement=False)
    provider = Column(String(20), nullable=False, default="github")
    repo = Column(String(200), nullable=False)
    workflow = Column(String(200), nullable=False)
    ref = Column(String(255), nullable=False, default="main")
    token_encrypted = Column(Text, nullable=False)  # Fernet ciphertext; never returned
    token_last4 = Column(String(4), nullable=False)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class RunRequest(Base):
    """One Play. The partial unique index keeps one active request per project."""

    __tablename__ = "run_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','cancelling','cancelled','failed_to_start')",
            name="chk_run_requests_status",
        ),
        Index("uq_run_requests_one_active", "project_id", unique=True,
              postgresql_where=text(ACTIVE_WHERE), sqlite_where=text(ACTIVE_WHERE)),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False, index=True)
    requested_by = Column(Integer, nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False)
    selection = Column(JSON, nullable=False)  # [{"case_number", "path", "name"}]
    suite_id = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False)
    conclusion = Column(String(30), nullable=True)
    github_run_id = Column(BigInteger, nullable=True)
    github_run_url = Column(Text, nullable=True)
    stopped_by = Column(Integer, nullable=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(String(500), nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=True)
    skipped_manual = Column(Integer, nullable=False, default=0, server_default="0")  # manual cases a suite run left out
    # What the dashboard estimated before Play (from ingestion; test-management never asks it): null when unknown
    estimate_ms = Column(Integer, nullable=True)
    estimate_upper_ms = Column(Integer, nullable=True)
    workflow = Column(String(100), nullable=True)  # the repository suite's workflow file; null: the project's default


class CiTargetEvent(Base):
    """Audit trail of the credential; kept when the target is deleted."""

    __tablename__ = "ci_target_events"
    __table_args__ = (
        CheckConstraint("action IN ('created','updated','token_replaced','deleted')", name="chk_ci_target_events_action"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False)
