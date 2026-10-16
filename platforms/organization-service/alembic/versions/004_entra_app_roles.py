"""Entra app roles: per-organization mapping, and members managed by it (ADR-033)

Revision ID: 004
Revises: 003
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode: SQLite (tests) cannot ALTER a table to add a CHECK constraint
    with op.batch_alter_table("organization_members") as batch:
        batch.add_column(sa.Column("managed_by", sa.String(20), nullable=True))
        batch.create_check_constraint("chk_member_managed_by", "managed_by IS NULL OR managed_by IN ('entra')")
    op.create_table(
        "organization_sso_role_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_role", sa.String(100), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin','member','viewer')", name="chk_sso_mapping_role"),
    )
    op.create_index("ix_organization_sso_role_mappings_id", "organization_sso_role_mappings", ["id"])
    op.create_index("ix_organization_sso_role_mappings_organization_id", "organization_sso_role_mappings", ["organization_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_org_sso_mapping_app_role "
        "ON organization_sso_role_mappings (organization_id, lower(app_role))"
    )


def downgrade() -> None:
    op.drop_index("uq_org_sso_mapping_app_role", table_name="organization_sso_role_mappings")
    op.drop_index("ix_organization_sso_role_mappings_organization_id", table_name="organization_sso_role_mappings")
    op.drop_index("ix_organization_sso_role_mappings_id", table_name="organization_sso_role_mappings")
    op.drop_table("organization_sso_role_mappings")
    with op.batch_alter_table("organization_members") as batch:
        batch.drop_constraint("chk_member_managed_by", type_="check")
        batch.drop_column("managed_by")
