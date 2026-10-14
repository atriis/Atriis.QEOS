from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, text

from src.auth.db.base import Base

STATE_ROW_ID = 1


class AuthModeState(Base):
    """The SSO-only mode last applied at start-up (ADR-031). One row, id 1 (migration 008 seeds it)."""
    __tablename__ = "auth_mode_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_auth_mode_state_single_row"),)

    id = Column(Integer, primary_key=True, autoincrement=False)
    sso_only = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    applied_at = Column(DateTime(timezone=True), nullable=True)
