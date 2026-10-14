"""test_results.failed_step_definition / failed_step_pattern: the failed step's step definition and its text with the
matched arguments replaced (spec 2026-10-14 §3.1)

Revision ID: 022
Revises: 021
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

INDEX = "ix_test_results_failed_step_definition"
WHERE = "failed_step_definition IS NOT NULL"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    where = {"postgresql_where": sa.text(WHERE), "sqlite_where": sa.text(WHERE)}
    if _postgres():
        # Nullable columns without a default are a metadata-only change. The partial index is built CONCURRENTLY, so
        # uploads are not blocked on a large table (as 016); CONCURRENTLY cannot run in a transaction, and IF NOT EXISTS
        # lets a re-run go through after a failed build
        op.execute("ALTER TABLE test_results ADD COLUMN IF NOT EXISTS failed_step_definition VARCHAR(500)")
        op.execute("ALTER TABLE test_results ADD COLUMN IF NOT EXISTS failed_step_pattern VARCHAR(1000)")
        with op.get_context().autocommit_block():
            op.create_index(INDEX, "test_results", ["failed_step_definition"], postgresql_concurrently=True,
                            if_not_exists=True, **where)
        return
    with op.batch_alter_table("test_results") as batch:
        batch.add_column(sa.Column("failed_step_definition", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("failed_step_pattern", sa.String(length=1000), nullable=True))
    op.create_index(INDEX, "test_results", ["failed_step_definition"], **where)


def downgrade() -> None:
    if _postgres():
        with op.get_context().autocommit_block():
            op.drop_index(INDEX, table_name="test_results", postgresql_concurrently=True, if_exists=True)
        op.execute("ALTER TABLE test_results DROP COLUMN IF EXISTS failed_step_pattern")
        op.execute("ALTER TABLE test_results DROP COLUMN IF EXISTS failed_step_definition")
        return
    op.drop_index(INDEX, table_name="test_results")
    with op.batch_alter_table("test_results") as batch:
        batch.drop_column("failed_step_pattern")
        batch.drop_column("failed_step_definition")
