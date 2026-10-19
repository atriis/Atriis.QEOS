"""Screenshot images, uploaded by the collector before the run that refers to them (ADR-036). Project API key auth,
as /collect/runs."""
import hashlib
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from src.ingestion.api.deps import get_db
from src.ingestion.api.key_auth import get_api_key
from src.ingestion.models import ApiKey
from src.ingestion.service import blob_service
from src.ingestion.utils.artifact_store import ArtifactStore, get_artifact_store

router = APIRouter()  # mounted at /collect/blobs
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SCREENSHOTS_OFF = {
    "code": "screenshots_off",
    "message": "Step screenshots are not enabled for this project, or this QEOS has no artifact storage.",
}
TOO_LARGE = "Image over 5 MB"


def _checked_hash(sha256: str) -> str:
    if not SHA256.match(sha256):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return sha256


@router.head("/{sha256}", status_code=status.HTTP_200_OK, response_class=Response)
def head_blob(sha256: str, db: Session = Depends(get_db), key: ApiKey = Depends(get_api_key)):
    if blob_service.find_blob(db, key.project_id, _checked_hash(sha256)) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return Response(status_code=status.HTTP_200_OK)


async def _read_capped(request: Request) -> bytes:
    """The body, stopped one byte past the limit: an oversized upload is never held whole."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > blob_service.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=TOO_LARGE)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > blob_service.MAX_IMAGE_BYTES:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _check_enabled(db: Session, project_id: int, store: Optional[ArtifactStore]) -> None:
    if not blob_service.screenshots_enabled(db, project_id, store):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SCREENSHOTS_OFF)


def _store_checked(db: Session, store: ArtifactStore, project_id: int, sha256: str, media_type: str,
                   data: bytes) -> bool:
    """The checks on the body, then the store. True when the image is new. Sync: the queries and the object store
    call block, so the endpoint runs this in the threadpool."""
    if blob_service.sniff_image(data) != media_type:
        raise _bad_request("The bytes are not the declared image type")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise _bad_request("The sha256 of the body does not match the path")
    if blob_service.find_blob(db, project_id, sha256) is not None:
        return False
    blob_service.store_blob(db, store, project_id, sha256, media_type, data)
    return True


@router.put("/{sha256}", status_code=status.HTTP_201_CREATED, responses={200: {"description": "Already stored"}})
async def put_blob(
    sha256: str, request: Request, response: Response, db: Session = Depends(get_db),
    key: ApiKey = Depends(get_api_key), store: Optional[ArtifactStore] = Depends(get_artifact_store),
):
    _checked_hash(sha256)
    await run_in_threadpool(_check_enabled, db, key.project_id, store)
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in blob_service.MEDIA_TYPES:
        raise _bad_request("Content-Type must be image/png, image/jpeg or image/webp")
    data = await _read_capped(request)
    created = await run_in_threadpool(_store_checked, db, store, key.project_id, sha256, media_type, data)
    if not created:
        response.status_code = status.HTTP_200_OK
    return {"sha256": sha256}
