"""SSO-only mode: the last applied mode, and the one-time Microsoft link allowance (ADR-031)

Revision ID: 008
Revises: 007
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("microsoft_link_allowed_until", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "auth_mode_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("sso_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_auth_mode_state_single_row"),
    )
    # Seeded so the start-up's SELECT ... FOR UPDATE always has a row to lock
    op.execute("INSERT INTO auth_mode_state (id, sso_only) VALUES (1, false)")


def downgrade() -> None:
    op.drop_table("auth_mode_state")
    op.drop_column("users", "microsoft_link_allowed_until")
