"""collection_settings and test_runs.trigger: collect manual CI runs or not (ADR-030)

A project can discard uploads from CI runs a person started by hand. No row: the defaults (collect
everything), so existing projects need no backfill. test_runs.trigger records how a stored run started.

Revision ID: 019
Revises: 018
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_settings",
        sa.Column("project_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("collect_manual", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("discarded_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("test_runs") as batch:
        batch.add_column(sa.Column("trigger", sa.String(length=10), nullable=True))
        batch.create_check_constraint("chk_test_runs_trigger", "\"trigger\" IN ('manual','automatic','qeos')")


def downgrade() -> None:
    with op.batch_alter_table("test_runs") as batch:
        batch.drop_constraint("chk_test_runs_trigger", type_="check")
        batch.drop_column("trigger")
    op.drop_table("collection_settings")
