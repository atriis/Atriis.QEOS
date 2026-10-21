"""One-time links for the trace viewer (ADR-037): artifact_links

A link holds the SHA-256 of its token (never the token), the artifact, the user who asked for it, their address and
when it expires (60 s after). The rows go with their artifact.

Revision ID: 028
Revises: 027
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_links",
        sa.Column("token_sha256", sa.String(length=64), primary_key=True),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("result_artifacts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifact_links_expires_at", "artifact_links", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_artifact_links_expires_at", table_name="artifact_links")
    op.drop_table("artifact_links")
