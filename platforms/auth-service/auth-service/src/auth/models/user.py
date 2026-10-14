from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from src.auth.db.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)  # Nullable for SSO-only users
    full_name = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # Tenant ID for multi-tenancy. Nullable: a user exists before belonging to any
    # organization (registration precedes org creation), and nothing in this service ever
    # assigned a value, so NOT NULL made user creation structurally impossible. Authoritative
    # membership now lives in organization-service's organization_members table.
    tenant_id = Column(Integer, nullable=True, index=True)

    # TOTP MFA: secret is set at enrollment and only counts once mfa_enabled is true
    mfa_secret = Column(String(64), nullable=True)
    mfa_enabled = Column(Boolean, nullable=False, default=False, server_default="false")

    # SSO-only mode (ADR-031): a superuser let this account link a Microsoft identity at its next
    # Microsoft sign-in, until this time. Cleared when used.
    microsoft_link_allowed_until = Column(DateTime(timezone=True), nullable=True)

    # Profile information
    avatar_url = Column(String(500), nullable=True)
    department = Column(String(100), nullable=True)
    job_title = Column(String(100), nullable=True)