"""overview layouts: one project default and one personal layout per user, per project

Revision ID: 004
Revises: 003
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

DEFAULT_ROW = sa.text("user_id IS NULL")


def upgrade() -> None:
    op.create_table(
        "overview_layouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("layout", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "user_id", name="uq_overview_layouts_project_user"),
    )
    op.create_index("ix_overview_layouts_project_id", "overview_layouts", ["project_id"])
    op.create_index(
        "uq_overview_layouts_project_default", "overview_layouts", ["project_id"],
        unique=True, sqlite_where=DEFAULT_ROW, postgresql_where=DEFAULT_ROW,
    )


def downgrade() -> None:
    op.drop_index("uq_overview_layouts_project_default", table_name="overview_layouts")
    op.drop_index("ix_overview_layouts_project_id", table_name="overview_layouts")
    op.drop_table("overview_layouts")
