"""Traces (ADR-037). Upload: the collector sends them before the run that refers to them, project API key auth as
/collect/blobs, the body streamed to the store, never held whole (up to 100 MB per trace). Download: JWT and the
read roles, as the run reads, streamed too, one byte range at a time if asked. The trace viewer, which cannot send the
Bearer token, reads the same way through a one-time link."""
import asyncio
import logging
import re
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from src.ingestion.api.deps import READ_ROLES, ProjectAccess, get_db, require_project_role
from src.ingestion.api.key_auth import get_api_key
from src.ingestion.core.config import settings
from src.ingestion.models import ApiKey
from src.ingestion.service import artifact_link_service, artifact_read, artifact_service
from src.ingestion.utils.artifact_store import (
    BUSY_RETRY_AFTER, ArtifactNotFound, ArtifactRangeError, ArtifactStore, ArtifactStoreBusy, artifact_key,
    get_artifact_store, store_slot,
)

logger = logging.getLogger(__name__)
router = APIRouter()  # mounted at /collect/artifacts
project_router = APIRouter()  # mounted at /projects/{project_id}/artifacts
SHA256 = re.compile(r"[0-9a-f]{64}")
TRACES_OFF = {
    "code": "traces_off",
    "message": "Traces are not enabled for this project, or this QEOS has no artifact storage.",
}


def _checked_hash(sha256: str) -> str:
    if not SHA256.fullmatch(sha256):  # not match() with "$", which lets a trailing "\n" through
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return sha256


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.head("/{sha256}", status_code=status.HTTP_200_OK, response_class=Response)
def head_artifact(sha256: str, db: Session = Depends(get_db), key: ApiKey = Depends(get_api_key)):
    if artifact_service.find_trace(db, key.project_id, _checked_hash(sha256)) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return Response(status_code=status.HTTP_200_OK)


def _check_enabled(db: Session, project_id: int, store: Optional[ArtifactStore]) -> None:
    enabled = artifact_service.traces_enabled(db, project_id, store)
    db.commit()  # no connection held while the body arrives
    if not enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=TRACES_OFF)


def _declared_length(request: Request) -> Optional[int]:
    """The Content-Length, or None for a chunked body. Over the cap it is refused before a byte is read."""
    declared = request.headers.get("content-length")
    if not (declared and declared.isdigit()):
        return None
    if int(declared) > artifact_service.MAX_TRACE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=artifact_service.TOO_LARGE)
    return int(declared)


# Trace uploads streaming at once in this process. Each buffers a multipart part or two (8-16 MB), and slow ones pile
# up under the gateway's rate, so a leaked key could otherwise exhaust the container's memory. One counter is enough:
# the event loop runs one handler step at a time. Not store_slot: an upload holds its place for minutes, which would
# starve the screenshot and download calls that share those slots
MAX_TRACE_UPLOADS = 4
_uploading = 0


def _busy() -> HTTPException:
    """503 with Retry-After: the collector retries a 5xx with backoff, within its upload budget."""
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail="Too many trace uploads at once; try again shortly",
                         headers={"Retry-After": BUSY_RETRY_AFTER})


def _delete_quietly(store: ArtifactStore, key: str) -> None:
    try:
        store.delete([key])
    except Exception:
        # The answer stays the upload's own; an incoming object left behind holds no verified bytes
        logger.warning("could not delete the incoming trace object %s", key, exc_info=True)


@router.put("/{sha256}", status_code=status.HTTP_201_CREATED, responses={200: {"description": "Already stored"}})
async def put_artifact(
    sha256: str, request: Request, response: Response, db: Session = Depends(get_db),
    key: ApiKey = Depends(get_api_key), store: Optional[ArtifactStore] = Depends(get_artifact_store),
):
    global _uploading
    _checked_hash(sha256)
    if _uploading >= MAX_TRACE_UPLOADS:
        raise _busy()
    _uploading += 1
    try:
        await _receive(sha256, request, response, db, key, store)
    finally:
        _uploading -= 1
    return {"sha256": sha256}


async def _receive(sha256: str, request: Request, response: Response, db: Session, key: ApiKey,
                   store: Optional[ArtifactStore]) -> None:
    """The upload itself, while it holds one of MAX_TRACE_UPLOADS places."""
    project_id = key.project_id  # read before the commit below expires the key
    await run_in_threadpool(_check_enabled, db, project_id, store)
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in artifact_service.MEDIA_TYPES:
        raise _bad_request("Content-Type must be application/zip")
    declared = _declared_length(request)
    incoming = artifact_service.incoming_key(project_id)
    body = artifact_service.CheckedBody(request.stream(), media_type)
    try:
        try:
            await store.put_stream(incoming, body.chunks(), media_type)
        except artifact_service.UploadRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)
        except ClientDisconnect:
            raise _bad_request("The upload ended before the whole body arrived")
        if declared is not None and body.size != declared:
            raise _bad_request("The body is shorter than its Content-Length")
        if not body.type_matches:
            raise _bad_request("The bytes are not the declared type")
        if body.sha256 != sha256:
            raise _bad_request("The sha256 of the body does not match the path")
        created = await run_in_threadpool(
            artifact_service.keep_trace, db, store, project_id, sha256, media_type, body.size, incoming)
    finally:
        # Every outcome, success included: the verified bytes now live at the content-addressed key. Shielded, so a
        # cancelled request still deletes it
        await asyncio.shield(asyncio.to_thread(_delete_quietly, store, incoming))
    if not created:
        response.status_code = status.HTTP_200_OK


# ---- download ----

SINGLE_RANGE = re.compile(r"bytes=([0-9]*)-([0-9]*)")
MAX_RANGE_HEADER = 64  # two 20-digit numbers fit; a longer header is not a range this endpoint serves


class Unsatisfiable(Exception):
    """The range starts at or past the end of the file: 416."""


def byte_range(header: Optional[str], size: int) -> Optional[Tuple[int, int]]:
    """(start, end), both inclusive, of one `bytes=` range of a file of `size` bytes; None for the whole file.
    Several ranges, another unit or an unreadable header get the whole file (RFC 9110 lets a server ignore Range);
    an end past the file is cut to it. Raises Unsatisfiable for a start at or past the end or an empty suffix."""
    if header is None or len(header) > MAX_RANGE_HEADER:
        return None
    match = SINGLE_RANGE.fullmatch(header.strip())
    if match is None:
        return None
    first, last = match.groups()
    if not first:
        if not last:
            return None
        suffix = int(last)  # bytes=-N: the last N bytes
        if suffix == 0:
            raise Unsatisfiable()
        return max(0, size - suffix), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if last and end < start:
        return None  # an invalid range is ignored
    if start >= size:
        raise Unsatisfiable()
    return start, min(end, size - 1)


def _busy() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Artifact storage busy",
                         headers={"Retry-After": BUSY_RETRY_AFTER})


def _file_headers(artifact_id: int) -> dict:
    return {
        "Content-Disposition": f'attachment; filename="trace-{artifact_id}.zip"',
        "Accept-Ranges": "bytes",
        # Traces can hold cookies and tokens of test accounts: no copy kept by a browser or a proxy
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }


def _serve_file(store: ArtifactStore, project_id: int, artifact_id: int, sha256: str, media_type: str, size: int,
                range_header: Optional[str], not_found: str) -> Response:
    """The stored file, streamed (never read whole into memory): the whole of it, or one byte range (206), or 416.
    For the download and the one-time links alike; `not_found` is the detail of the 404 for an object missing from
    storage. Call it with no database connection held: the store answers and the body streams afterwards."""
    headers = _file_headers(artifact_id)
    unsatisfiable = Response(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                             headers={**headers, "Content-Range": f"bytes */{size}"})
    try:
        wanted = byte_range(range_header, size)
    except Unsatisfiable:
        return unsatisfiable
    key = artifact_key(project_id, sha256)
    try:
        with store_slot():
            if wanted is None:
                chunks, length = store.open(key)
            else:
                chunks, length = store.open_range(key, *wanted), wanted[1] - wanted[0] + 1
    except ArtifactNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=not_found)
    except ArtifactRangeError:  # the stored object is shorter than its row says
        return unsatisfiable
    except ArtifactStoreBusy:
        raise _busy()
    headers["Content-Length"] = str(length)
    if wanted is None:
        return StreamingResponse(chunks, media_type=media_type, headers=headers)
    headers["Content-Range"] = f"bytes {wanted[0]}-{wanted[1]}/{size}"
    return StreamingResponse(chunks, status_code=status.HTTP_206_PARTIAL_CONTENT, media_type=media_type,
                             headers=headers)


def _no_store() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No artifact storage")


FILE_RESPONSES = {
    200: {"content": {"application/zip": {}}}, 206: {"description": "One byte range"},
    416: {"description": "The range starts past the end of the file"},
}


@project_router.get("/{artifact_id}", response_class=StreamingResponse, responses=FILE_RESPONSES)
def download_artifact(
    artifact_id: int,
    range_header: Optional[str] = Header(None, alias="range"),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
    store: Optional[ArtifactStore] = Depends(get_artifact_store),
):
    """The trace file, streamed: never read whole into memory. The id resolves through its result and run to the
    project, so another project's id is a 404. Sync endpoint: the queries and the store call run in the threadpool,
    and the body is sent chunk by chunk afterwards."""
    found = artifact_read.find_file(db, access.project_id, artifact_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    if store is None:
        raise _no_store()
    sha256, media_type, size = found
    db.close()  # no pooled connection held while the store answers, nor while the body streams
    return _serve_file(store, access.project_id, artifact_id, sha256, media_type, size, range_header,
                       "Artifact not found")


# ---- one-time links for the trace viewer ----

link_router = APIRouter()  # mounted at /artifact-links: no Bearer token, the link is the credential
LINK_NOT_FOUND = "Not found"  # one detail for every refusal: unknown, expired, another address, artifact gone


@project_router.post("/{artifact_id}/link", status_code=status.HTTP_201_CREATED)
def create_link(
    artifact_id: int,
    request: Request,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """A one-time URL for the self-hosted trace viewer, which cannot send the Bearer token: valid 60 s, for this
    artifact, this user and the address asking. The token is in this answer only; the database keeps its SHA-256."""
    if artifact_read.find_file(db, access.project_id, artifact_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    token, expires_at = artifact_link_service.create(
        db, artifact_id, access.user_id, artifact_link_service.client_ip(request))
    return {"url": f"{settings.API_V1_STR}/artifact-links/{token}", "expires_at": expires_at.isoformat()}


@link_router.api_route("/{token}", methods=["GET", "HEAD"], response_class=StreamingResponse,
                       responses=FILE_RESPONSES)
def follow_link(
    token: str,
    request: Request,
    range_header: Optional[str] = Header(None, alias="range"),
    db: Session = Depends(get_db),
    store: Optional[ArtifactStore] = Depends(get_artifact_store),
):
    """The linked trace, as the download serves it (whole or one range), while the link lives and from its address;
    otherwise 404, the same for every case. HEAD answers the headers of the whole file without reading storage."""
    found = artifact_link_service.resolve(db, token, artifact_link_service.client_ip(request))
    db.close()  # no pooled connection held while the store answers, nor while the body streams
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=LINK_NOT_FOUND)
    # The audit trail of each use: who the link was made for, what and from where. Never the token
    logger.info("artifact link used: user_id=%s artifact_id=%s ip=%s", found.user_id, found.artifact_id,
                artifact_link_service.client_ip(request))
    if store is None:
        raise _no_store()
    if request.method == "HEAD":
        headers = {**_file_headers(found.artifact_id), "Content-Length": str(found.size)}
        return Response(status_code=status.HTTP_200_OK, media_type=found.media_type, headers=headers)
    return _serve_file(store, found.project_id, found.artifact_id, found.sha256, found.media_type, found.size,
                       range_header, LINK_NOT_FOUND)
