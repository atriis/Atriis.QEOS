"""One-time links for the trace viewer (ADR-037): the self-hosted viewer cannot send the Bearer token, so a reader
asks for a link. Only the token's SHA-256 is stored; the token itself is in the answer to that request alone."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from src.ingestion.db.base import Base

CLIENT_IP_LENGTH = 64  # an IPv6 address with a zone fits


class ArtifactLink(Base):
    """A link to one artifact, for the user who asked and the address they asked from, until `expires_at` (60 s).
    The rows go with their artifact by ON DELETE CASCADE in PostgreSQL; the retention job deletes expired ones."""

    __tablename__ = "artifact_links"
    __table_args__ = (
        # The retention job deletes the expired links
        Index("ix_artifact_links_expires_at", "expires_at"),
    )

    token_sha256 = Column(String(64), primary_key=True)
    artifact_id = Column(Integer, ForeignKey("result_artifacts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, nullable=False)
    client_ip = Column(String(CLIENT_IP_LENGTH), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
