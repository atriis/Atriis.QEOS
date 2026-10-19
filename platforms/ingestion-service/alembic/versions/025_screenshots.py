"""blobs, result_screenshots and collection_settings.keep_screenshots (ADR-036)

blobs: one stored image per (project, sha256), shared by every result that shows it. result_screenshots: the
images of one result, in order. A blob row has no cascade: the garbage collector owns blob deletion.
keep_screenshots is off by default, so existing projects keep nothing until an owner or admin allows it.

Revision ID: 025
Revises: 024
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collection_settings") as batch:
        batch.add_column(sa.Column("keep_screenshots", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "blobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "sha256", name="uq_blobs_project_sha256"),
    )
    op.create_table(
        "result_screenshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("blob_id", sa.Integer(), sa.ForeignKey("blobs.id"), nullable=False),
        sa.Column("step_text", sa.String(length=1000), nullable=False),
        sa.Column("step_line", sa.Integer(), nullable=True),
        sa.Column("hook", sa.String(length=8), nullable=True),
    )
    op.create_index("ix_result_screenshots_result_position", "result_screenshots", ["result_id", "position"])
    op.create_index("ix_result_screenshots_blob_id", "result_screenshots", ["blob_id"])


def downgrade() -> None:
    op.drop_index("ix_result_screenshots_blob_id", table_name="result_screenshots")
    op.drop_index("ix_result_screenshots_result_position", table_name="result_screenshots")
    op.drop_table("result_screenshots")
    op.drop_table("blobs")
    with op.batch_alter_table("collection_settings") as batch:
        batch.drop_column("keep_screenshots")
