"""test_results.log, log_patterns, log_values and the log-value re-scan counters (ADR-032)

Revision ID: 023
Revises: 022
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _postgres():
        # A nullable column without a default is a metadata-only change: the large test_results table is not
        # rewritten. IF NOT EXISTS lets a re-run go through
        op.execute("ALTER TABLE test_results ADD COLUMN IF NOT EXISTS log TEXT")
    else:
        with op.batch_alter_table("test_results") as batch:
            batch.add_column(sa.Column("log", sa.Text(), nullable=True))
    # Constant defaults: metadata-only on PostgreSQL 11+ as well
    with op.batch_alter_table("collection_settings") as batch:
        batch.add_column(sa.Column("log_scan_requested", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("log_scan_done", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("log_scan_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "log_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("pattern", sa.String(length=256), nullable=False),
        sa.Column("link_template", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "name", name="uq_log_pattern_project_name"),
    )
    op.create_index("ix_log_patterns_id", "log_patterns", ["id"])
    op.create_index("ix_log_patterns_project_id", "log_patterns", ["project_id"])
    op.create_table(
        "log_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pattern_id", sa.Integer(), sa.ForeignKey("log_patterns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
    )
    op.create_index("ix_log_values_result_id", "log_values", ["result_id"])
    op.create_index("ix_log_values_pattern_id", "log_values", ["pattern_id"])


def downgrade() -> None:
    op.drop_index("ix_log_values_pattern_id", table_name="log_values")
    op.drop_index("ix_log_values_result_id", table_name="log_values")
    op.drop_table("log_values")
    op.drop_index("ix_log_patterns_project_id", table_name="log_patterns")
    op.drop_index("ix_log_patterns_id", table_name="log_patterns")
    op.drop_table("log_patterns")
    with op.batch_alter_table("collection_settings") as batch:
        batch.drop_column("log_scan_started_at")
        batch.drop_column("log_scan_done")
        batch.drop_column("log_scan_requested")
    if _postgres():
        op.execute("ALTER TABLE test_results DROP COLUMN IF EXISTS log")
    else:
        with op.batch_alter_table("test_results") as batch:
            batch.drop_column("log")
