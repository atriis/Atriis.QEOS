"""project deletion: who deleted a project, and which purge steps other services confirmed (spec 2026-10-16)

Revision ID: 005
Revises: 004
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("deleted_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("purge_state", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("purge_state")
        batch.drop_column("deleted_by")
