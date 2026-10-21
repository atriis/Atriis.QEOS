"""Traces (ADR-037): what an upload may be, the checks made while it streams, and the one stored copy per
(project, sha256). The body goes to a temporary key first; only a verified file is copied to its
content-addressed key, so `artifacts/{project_id}/{sha256}` never holds bytes that are not that hash."""
import hashlib
import uuid
from typing import AsyncIterator, Optional

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from src.ingestion.models import Blob
from src.ingestion.service import collection_settings_service
from src.ingestion.utils.artifact_store import ArtifactStore, artifact_key

MAX_TRACE_BYTES = 100 * 1024 * 1024
# A list, so videos add their type later (spec 4.1); each type names the first bytes its files start with
MAGIC = {"application/zip": b"PK\x03\x04"}
MEDIA_TYPES = tuple(MAGIC)
TOO_LARGE = "Trace over 100 MB"


def traces_enabled(db: Session, project_id: int, store: Optional[ArtifactStore]) -> bool:
    """Storage is configured and the project keeps traces. Either one missing, the collector sends none."""
    return store is not None and bool(collection_settings_service.get(db, project_id).keep_traces)


def find_trace(db: Session, project_id: int, sha256: str) -> Optional[Blob]:
    return db.query(Blob).filter(
        Blob.project_id == project_id, Blob.sha256 == sha256, Blob.kind == "trace").first()


def incoming_key(project_id: int) -> str:
    """Where an upload streams before it is verified: its own key, so two uploads at once never share one."""
    return f"artifacts/{project_id}/incoming/{uuid.uuid4().hex}"


class UploadRejected(Exception):
    """The body broke a rule while streaming; the endpoint answers status_code with detail."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class CheckedBody:
    """The request body on its way to the store: hashed and counted as it passes, and stopped (UploadRejected) as
    soon as it is over MAX_TRACE_BYTES or its first bytes are not the type's, before the object is completed."""

    def __init__(self, source: AsyncIterator[bytes], media_type: str) -> None:
        self._source = source
        self._magic = MAGIC[media_type]
        self._head = b""
        self._hash = hashlib.sha256()
        self.size = 0

    async def chunks(self) -> AsyncIterator[bytes]:
        async for chunk in self._source:
            if not chunk:
                continue
            self.size += len(chunk)
            if self.size > MAX_TRACE_BYTES:
                raise UploadRejected(413, TOO_LARGE)
            if len(self._head) < len(self._magic):
                self._head += chunk[:len(self._magic) - len(self._head)]
                if not self._magic.startswith(self._head):
                    raise UploadRejected(400, "The bytes are not the declared type")
            self._hash.update(chunk)
            yield chunk

    @property
    def type_matches(self) -> bool:
        """False for a body shorter than the magic bytes (the stream already stopped any other mismatch)."""
        return self._head == self._magic

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()


def keep_trace(db: Session, store: ArtifactStore, project_id: int, sha256: str, media_type: str, size: int,
               incoming: str) -> bool:
    """Copies a verified upload to its content-addressed key and records it. True when the trace is new; False when
    this project already has it (also when another upload of it wrote the row first). The caller deletes the
    incoming object either way. Sync: the queries and the store call block, so the endpoint runs this in the
    threadpool, and no transaction is open during the copy."""
    if find_trace(db, project_id, sha256) is not None:
        db.commit()
        return False
    db.commit()  # ends the transaction and hands the connection back to the pool
    store.copy(incoming, artifact_key(project_id, sha256))
    # ON CONFLICT DO NOTHING in either dialect: two uploads of one trace at once both succeed, with one row
    insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
    result = db.execute(
        insert(Blob).values(project_id=project_id, sha256=sha256, kind="trace", media_type=media_type, bytes=size)
        .on_conflict_do_nothing(index_elements=["project_id", "sha256"])
    )
    db.commit()
    return result.rowcount == 1
