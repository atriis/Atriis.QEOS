"""Screenshot images (ADR-036): what an upload may be, and the one stored copy per (project, sha256)."""
from typing import Optional

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from src.ingestion.models import Blob
from src.ingestion.service import collection_settings_service
from src.ingestion.utils.artifact_store import ArtifactStore, screenshot_key, store_slot

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")


def screenshots_enabled(db: Session, project_id: int, store: Optional[ArtifactStore]) -> bool:
    """Storage is configured and the project keeps screenshots. Either one missing, the collector sends none."""
    return store is not None and bool(collection_settings_service.get(db, project_id).keep_screenshots)


def sniff_image(data: bytes) -> Optional[str]:
    """The media type the first bytes say, or None. The Content-Type header is the client's word; this is not."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def find_blob(db: Session, project_id: int, sha256: str) -> Optional[Blob]:
    return db.query(Blob).filter(Blob.project_id == project_id, Blob.sha256 == sha256).first()


def store_blob(db: Session, store: ArtifactStore, project_id: int, sha256: str, media_type: str,
               data: bytes) -> Blob:
    """Idempotent: a stored image is returned as it is, with no second put. The object goes in before the row, so a
    row never points at nothing; a crash in between leaves an object the next upload of it simply reuses.
    The transaction ends before the put, so a slow store holds a thread but no pooled connection. Raises
    ArtifactStoreBusy when every store slot is taken."""
    existing = find_blob(db, project_id, sha256)
    if existing is not None:
        return existing
    db.commit()  # ends the transaction and hands the connection back to the pool
    with store_slot():
        store.put(screenshot_key(project_id, sha256), data, media_type)
    # ON CONFLICT DO NOTHING in either dialect: two uploads of one image at once both succeed, with one row
    insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
    db.execute(
        insert(Blob).values(project_id=project_id, sha256=sha256, media_type=media_type, bytes=len(data))
        .on_conflict_do_nothing(index_elements=["project_id", "sha256"])
    )
    db.commit()
    return find_blob(db, project_id, sha256)
