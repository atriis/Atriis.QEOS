"""one active run request per (project, workflow)

Revision ID: 010
Revises: 009
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None

ACTIVE_WHERE = "status IN ('queued','running','cancelling')"
DEFAULT_WORKFLOW = "qeos-run.yml"


def upgrade() -> None:
    # A null workflow would escape the unique index (nulls are distinct): fill every row first. Rows made
    # between 009 and 010 take the CI target's workflow; a project without a target, the default file name
    op.execute(
        "UPDATE run_requests SET workflow = "
        "(SELECT ci_targets.workflow FROM ci_targets WHERE ci_targets.project_id = run_requests.project_id) "
        "WHERE workflow IS NULL"
    )
    op.execute(f"UPDATE run_requests SET workflow = '{DEFAULT_WORKFLOW}' WHERE workflow IS NULL")
    op.drop_index("uq_run_requests_one_active", table_name="run_requests")
    op.create_index("uq_run_requests_one_active", "run_requests", ["project_id", "workflow"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE), sqlite_where=sa.text(ACTIVE_WHERE))


def downgrade() -> None:
    # Fails while one project has active runs in two workflows: stop one first
    op.drop_index("uq_run_requests_one_active", table_name="run_requests")
    op.create_index("uq_run_requests_one_active", "run_requests", ["project_id"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE), sqlite_where=sa.text(ACTIVE_WHERE))
