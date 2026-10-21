"""Traces (ADR-037): blobs.kind, result_artifacts, collection_settings.keep_traces and trace_days

blobs.kind says what the bytes are: every existing row is a screenshot. result_artifacts links a result to its
traces (blob rows of kind trace), as result_screenshots does for images. keep_traces is off by default and
trace_days (1..90, default 14) is how long a project's traces are kept.

Revision ID: 027
Revises: 026
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("blobs") as batch:
        batch.add_column(sa.Column("kind", sa.String(length=16), nullable=False, server_default="screenshot"))
        batch.create_check_constraint("chk_blobs_kind", "kind IN ('screenshot','trace')")
    op.execute(sa.text("UPDATE blobs SET kind = 'screenshot'"))
    with op.batch_alter_table("collection_settings") as batch:
        batch.add_column(sa.Column("keep_traces", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("trace_days", sa.Integer(), nullable=False, server_default=sa.text("14")))
        batch.create_check_constraint("chk_collection_settings_trace_days", "trace_days BETWEEN 1 AND 90")
    op.create_table(
        "result_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("blob_id", sa.Integer(), sa.ForeignKey("blobs.id"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('trace')", name="chk_result_artifacts_kind"),
    )
    op.create_index("ix_result_artifacts_result_position", "result_artifacts", ["result_id", "position"])
    op.create_index("ix_result_artifacts_blob_id", "result_artifacts", ["blob_id"])


def downgrade() -> None:
    op.drop_index("ix_result_artifacts_blob_id", table_name="result_artifacts")
    op.drop_index("ix_result_artifacts_result_position", table_name="result_artifacts")
    op.drop_table("result_artifacts")
    with op.batch_alter_table("collection_settings") as batch:
        batch.drop_constraint("chk_collection_settings_trace_days", type_="check")
        batch.drop_column("trace_days")
        batch.drop_column("keep_traces")
    with op.batch_alter_table("blobs") as batch:
        batch.drop_constraint("chk_blobs_kind", type_="check")
        batch.drop_column("kind")
