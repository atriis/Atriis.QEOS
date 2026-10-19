"""suites.origin and the repository-suite columns; run_requests.workflow

Revision ID: 009
Revises: 008
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None

LEG_WHERE = "origin = 'repository'"


def upgrade() -> None:
    with op.batch_alter_table("suites") as batch:
        batch.add_column(sa.Column("origin", sa.String(20), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("workflow", sa.String(100), nullable=True))
        batch.add_column(sa.Column("group_name", sa.String(100), nullable=True))
        batch.add_column(sa.Column("external_id", sa.String(200), nullable=True))
        batch.add_column(sa.Column("shard", sa.String(100), nullable=True))
        batch.add_column(sa.Column("test_paths", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("source_repo", sa.String(200), nullable=True))
        batch.create_check_constraint("chk_suites_origin", "origin IN ('manual','repository')")
    op.create_index("uq_suites_repository_leg", "suites", ["project_id", "workflow", "external_id"], unique=True,
                    postgresql_where=sa.text(LEG_WHERE), sqlite_where=sa.text(LEG_WHERE))

    # A plain ADD COLUMN: batch mode would rebuild the table and could lose the partial unique index
    op.add_column("run_requests", sa.Column("workflow", sa.String(100), nullable=True))
    op.execute(
        "UPDATE run_requests SET workflow = "
        "(SELECT ci_targets.workflow FROM ci_targets WHERE ci_targets.project_id = run_requests.project_id)"
    )


def downgrade() -> None:
    op.drop_column("run_requests", "workflow")
    op.drop_index("uq_suites_repository_leg", table_name="suites")
    with op.batch_alter_table("suites") as batch:
        batch.drop_constraint("chk_suites_origin", type_="check")
        for column in ("source_repo", "test_paths", "shard", "external_id", "group_name", "workflow", "origin"):
            batch.drop_column(column)
