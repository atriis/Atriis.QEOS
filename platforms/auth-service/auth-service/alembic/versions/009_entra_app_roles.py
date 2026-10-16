"""Entra app roles: the last roles a Microsoft sign-in carried, and when they were applied (ADR-033)

Revision ID: 009
Revises: 008
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_accounts", sa.Column("sso_roles", sa.JSON(), nullable=True))
    op.add_column("oauth_accounts", sa.Column("sso_roles_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_accounts", sa.Column("sso_roles_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_accounts", "sso_roles_synced_at")
    op.drop_column("oauth_accounts", "sso_roles_at")
    op.drop_column("oauth_accounts", "sso_roles")
