"""test_runs.scope and test_runs.stages, api_keys.can_read_impact: suggested tests first in CI (test impact release B)

run-impact uploads a run with its stages; a run of only the suggested tests is scope 'impact-subset' and stays out of
the impact statistics, the outcome evaluation and the accuracy figure (spec 2026-10-13 §3.1). Every existing run is a
full run: on PostgreSQL 11+ a constant default makes the new columns a metadata-only change, with no table rewrite.

api_keys.can_read_impact: may the key read its project's test suggestions (POST /collect/impact)? Off for every key,
existing or new, until an owner or admin allows it (spec 2026-10-13 §9).

On PostgreSQL the scope check is added NOT VALID (new rows are checked at once, no scan) and validated in its own
transaction, which scans test_runs under a SHARE UPDATE EXCLUSIVE lock that lets uploads go on. Every existing row is
'full', so the validation cannot fail. The PostgreSQL path is re-runnable (IF NOT EXISTS, and a guarded constraint), as
016's is, in case the validation is interrupted after the first transaction committed.

Revision ID: 020
Revises: 019
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

# Frozen here as migration 020 created them; the model takes the scopes from models/run.SCOPES
CHECK = "chk_test_runs_scope"
SCOPE_IN = "scope IN ('full','impact-subset')"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _postgres():
        op.execute("ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS scope VARCHAR(20) NOT NULL DEFAULT 'full'")
        op.execute("ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS stages JSON")
        op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS can_read_impact BOOLEAN NOT NULL DEFAULT false")
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{CHECK}') THEN"
            f" ALTER TABLE test_runs ADD CONSTRAINT {CHECK} CHECK ({SCOPE_IN}) NOT VALID; END IF; END $$"
        )
        with op.get_context().autocommit_block():
            op.execute(f"ALTER TABLE test_runs VALIDATE CONSTRAINT {CHECK}")
        return
    with op.batch_alter_table("test_runs") as batch:
        batch.add_column(sa.Column("scope", sa.String(length=20), nullable=False, server_default="full"))
        batch.add_column(sa.Column("stages", sa.JSON(), nullable=True))
        batch.create_check_constraint(CHECK, SCOPE_IN)
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("can_read_impact", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    if _postgres():
        op.execute(f"ALTER TABLE test_runs DROP CONSTRAINT IF EXISTS {CHECK}")
        op.execute("ALTER TABLE test_runs DROP COLUMN IF EXISTS stages")
        op.execute("ALTER TABLE test_runs DROP COLUMN IF EXISTS scope")
        op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS can_read_impact")
        return
    with op.batch_alter_table("api_keys") as batch:
        batch.drop_column("can_read_impact")
    with op.batch_alter_table("test_runs") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.drop_column("stages")
        batch.drop_column("scope")
