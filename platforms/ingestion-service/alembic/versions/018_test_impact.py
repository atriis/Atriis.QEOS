"""test impact analysis: impact_pairs, impact_test_base, run_impact

impact_pairs and impact_test_base are rebuilt per project by the impact-rollup job; run_impact holds the suggestion
stored with an uploaded run and its outcome, and goes with its run (spec 2026-10-12 §3.2, §3.4, plan Ruling 15).

impact_pairs has no surrogate id, so a table rebuilt every night never runs out of 32-bit ids. Its key is
(project_id, unit_hash, test_key), where unit_hash is md5(path_unit) as 32 hex characters: path_unit can be 1,101
characters, and in multibyte UTF-8 that passes the 2,704-byte btree entry limit, so it is never indexed itself and
stays a plain column for display. test_key is a 64-character sha256 hex, so a key entry is about 100 bytes.
This supersedes the plan's hash index on path_unit (Ruling 27).

Downgrade warning: downgrading below 018 drops run_impact, and with it every live run's stored suggestion and its
outcome (caught / missed). They cannot be rebuilt exactly: a replay scores old runs against today's statistics.
impact_pairs and impact_test_base are rebuilt by the next impact-rollup pass after an upgrade.

Revision ID: 018
Revises: 017
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "impact_pairs",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("unit_hash", sa.String(length=32), nullable=False),
        sa.Column("test_key", sa.String(length=64), nullable=False),
        sa.Column("path_unit", sa.String(length=1101), nullable=False),
        sa.Column("changed_runs", sa.Integer(), nullable=False),
        sa.Column("new_failures", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("project_id", "unit_hash", "test_key", name="pk_impact_pairs"),
    )
    op.create_index("ix_impact_pairs_unit", "impact_pairs", ["project_id", "unit_hash"])
    op.create_table(
        "impact_test_base",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("test_key", sa.String(length=64), nullable=False),
        sa.Column("runs", sa.Integer(), nullable=False),
        sa.Column("new_failures", sa.Integer(), nullable=False),
        sa.Column("flaky", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suite", sa.String(length=500), nullable=False),
        sa.Column("class_name", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=1000), nullable=False),
        sa.Column("file", sa.String(length=1000), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "test_key", name="uq_impact_test_base"),
    )
    op.create_table(
        "run_impact",
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("test_runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("suggested", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(length=20), nullable=False),
        sa.Column("replayed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("caught", sa.JSON(), nullable=True),
        sa.Column("missed", sa.JSON(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Warning: drops run_impact, so live runs' stored suggestions and outcomes are lost (see the module docstring)."""
    op.drop_table("run_impact")
    op.drop_table("impact_test_base")
    op.drop_index("ix_impact_pairs_unit", table_name="impact_pairs")
    op.drop_table("impact_pairs")
