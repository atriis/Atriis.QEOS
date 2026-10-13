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


CHECK = "chk_test_results_failed_step_line"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _postgres():
        # Nullable columns without a default are a metadata-only change. The check is added NOT VALID (no scan under
        # ACCESS EXCLUSIVE) and validated in its own transaction, as 020 does; re-runnable.
        op.execute("ALTER TABLE test_results ADD COLUMN IF NOT EXISTS failed_step_text VARCHAR(1000)")
        op.execute("ALTER TABLE test_results ADD COLUMN IF NOT EXISTS failed_step_line INTEGER")
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{CHECK}') THEN"
            f" ALTER TABLE test_results ADD CONSTRAINT {CHECK} CHECK (failed_step_line > 0) NOT VALID;"
            f" END IF; END $$"
        )
        with op.get_context().autocommit_block():
            op.execute(f"ALTER TABLE test_results VALIDATE CONSTRAINT {CHECK}")
        return
    with op.batch_alter_table("test_results") as batch:
        batch.add_column(sa.Column("failed_step_text", sa.String(length=1000), nullable=True))
        batch.add_column(sa.Column("failed_step_line", sa.Integer(), nullable=True))
        batch.create_check_constraint(CHECK, "failed_step_line > 0")


def downgrade() -> None:
    if _postgres():
        op.execute(f"ALTER TABLE test_results DROP CONSTRAINT IF EXISTS {CHECK}")
        op.execute("ALTER TABLE test_results DROP COLUMN IF EXISTS failed_step_line")
        op.execute("ALTER TABLE test_results DROP COLUMN IF EXISTS failed_step_text")
        return
    with op.batch_alter_table("test_results") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.drop_column("failed_step_line")
        batch.drop_column("failed_step_text")
