"""Entra role sync needs a superuser's approval per organization (ADR-033 amendment)

Revision ID: 005
Revises: 004
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both NULL for every existing organization: mappings made before this revision stay paused until a superuser
    # approves the organization
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("entra_sync_approved_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("entra_sync_approved_by", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("entra_sync_approved_by")
        batch.drop_column("entra_sync_approved_at")
