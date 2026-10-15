"""log_values indexed by (value, pattern_id) for the runs search by a log value (spec 2026-10-15 §3.1)

Revision ID: 024
Revises: 023
Create Date: 2026-10-15
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_log_values_value", "log_values", ["value", "pattern_id"])


def downgrade() -> None:
    op.drop_index("ix_log_values_value", table_name="log_values")
