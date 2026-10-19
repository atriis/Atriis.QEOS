"""blobs.created_at NOT NULL, default now()

The garbage collector (ADR-036) ages blobs by created_at, and a NULL never compares as old, so such a blob would
never be collected. 025 shipped the column nullable; rows without a time get now().

Revision ID: 026
Revises: 025
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE blobs SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
    with op.batch_alter_table("blobs") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False,
                           server_default=sa.func.now())


def downgrade() -> None:
    with op.batch_alter_table("blobs") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=True,
                           server_default=sa.func.now())
