"""test_results.failed_step_text / failed_step_line: the Cucumber step that failed (spec 2026-10-13)

Revision ID: 021
Revises: 020
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("test_results") as batch:
        batch.add_column(sa.Column("failed_step_text", sa.String(length=1000), nullable=True))
        batch.add_column(sa.Column("failed_step_line", sa.Integer(), nullable=True))
        batch.create_check_constraint("chk_test_results_failed_step_line", "failed_step_line > 0")


def downgrade() -> None:
    with op.batch_alter_table("test_results") as batch:
        batch.drop_constraint("chk_test_results_failed_step_line", type_="check")
        batch.drop_column("failed_step_line")
        batch.drop_column("failed_step_text")
