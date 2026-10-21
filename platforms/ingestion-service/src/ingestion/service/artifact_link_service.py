"""One-time links for the trace viewer (ADR-037). The self-hosted viewer fetches the trace by URL and cannot send the
Bearer token, so a reader asks for a link: a random 32-byte token, of which only the SHA-256 is stored, valid 60 s,
for one artifact, the user who asked and the address they asked from. Within the 60 s the viewer may make several
GET and Range requests; afterwards, or from another address, the link is unknown."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import NamedTuple, Optional, Tuple

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ingestion.models import ArtifactLink, Blob, ResultArtifact, Run, RunResult

LINK_SECONDS = 60
# secrets.token_urlsafe(32): 43 URL-safe base64 characters. Anything else is not looked up
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


class LinkedFile(NamedTuple):
    project_id: int
    artifact_id: int
    sha256: str
    media_type: str
    size: int


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def client_ip(request: Request) -> str:
    """The caller's address, as auth-service reads it: the gateway overwrites X-Forwarded-For with the address it saw
    (gateway/nginx.conf.template), so its first entry is trusted; without it, the socket peer. "" when neither."""
    first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else ""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create(db: Session, artifact_id: int, user_id: int, ip: str) -> Tuple[str, datetime]:
    """A new link; returns the token (never stored, never logged) and when it expires."""
    token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(seconds=LINK_SECONDS)
    db.add(ArtifactLink(token_sha256=_hash(token), artifact_id=artifact_id, user_id=user_id, client_ip=ip,
                        expires_at=expires_at))
    db.commit()
    return token, expires_at


def _aware(value: datetime) -> datetime:
    # SQLite (the tests) gives the stored time back without its offset; it was written in UTC
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def resolve(db: Session, token: str, ip: str) -> Optional[LinkedFile]:
    """The file a live link points to, asked from its address; None for every other case (malformed, unknown,
    expired, another address, an artifact gone), which the caller answers with one and the same 404."""
    if not TOKEN.fullmatch(token) or not ip:
        return None
    row = db.execute(
        select(ArtifactLink.expires_at, ArtifactLink.client_ip, Blob.project_id, ArtifactLink.artifact_id,
               Blob.sha256, Blob.media_type, Blob.bytes)
        .join(ResultArtifact, ResultArtifact.id == ArtifactLink.artifact_id)
        .join(Blob, Blob.id == ResultArtifact.blob_id)
        .join(RunResult, RunResult.id == ResultArtifact.result_id)
        .join(Run, Run.id == RunResult.run_id)
        # As every artifact read: a row whose blob is not its run's project's is invisible
        .where(ArtifactLink.token_sha256 == _hash(token), Blob.project_id == Run.project_id)
    ).one_or_none()
    if row is None or utcnow() >= _aware(row.expires_at) or row.client_ip != ip:
        return None
    return LinkedFile(row.project_id, row.artifact_id, row.sha256, row.media_type, row.bytes)


def delete_expired(db: Session, now: datetime, dry_run: bool) -> int:
    """For the retention job: deletes the links expired at `now` and returns how many (a dry run counts them)."""
    expired = ArtifactLink.expires_at <= now
    if dry_run:
        count = db.execute(select(func.count()).select_from(ArtifactLink).where(expired)).scalar_one()
        db.commit()  # ends the read transaction
        return count
    deleted = db.query(ArtifactLink).filter(expired).delete(synchronize_session=False)
    db.commit()
    return deleted
