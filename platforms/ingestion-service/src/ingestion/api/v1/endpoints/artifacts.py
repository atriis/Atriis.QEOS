"""Traces, uploaded by the collector before the run that refers to them (ADR-037). Project API key auth, as
/collect/blobs. The body is streamed to the store, never held whole: up to 100 MB per trace."""
import asyncio
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from src.ingestion.api.deps import get_db
from src.ingestion.api.key_auth import get_api_key
from src.ingestion.models import ApiKey
from src.ingestion.service import artifact_service
from src.ingestion.utils.artifact_store import ArtifactStore, get_artifact_store

logger = logging.getLogger(__name__)
router = APIRouter()  # mounted at /collect/artifacts
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
    _checked_hash(sha256)
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
    return {"sha256": sha256}
