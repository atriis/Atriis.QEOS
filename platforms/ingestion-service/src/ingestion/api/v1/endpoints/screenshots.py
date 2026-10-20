"""A step screenshot's image, read from the artifact store (ADR-036). JWT, as the run reads: the id resolves
through its result and run to the project, so another project's id is a 404. Sync endpoint, so the queries and the
store call run in the threadpool."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from src.ingestion.api.deps import READ_ROLES, ProjectAccess, get_db, require_project_role
from src.ingestion.service import screenshot_read
from src.ingestion.utils.artifact_store import (
    BUSY_RETRY_AFTER, ArtifactNotFound, ArtifactStore, ArtifactStoreBusy, get_artifact_store, screenshot_key, store_slot,
)

router = APIRouter()  # mounted at /projects/{project_id}/screenshots


@router.get("/{screenshot_id}", response_class=Response, responses={200: {"content": {"image/*": {}}}})
def get_screenshot(
    screenshot_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
    store: Optional[ArtifactStore] = Depends(get_artifact_store),
):
    found = screenshot_read.find_image(db, access.project_id, screenshot_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No artifact storage")
    sha256, media_type = found
    db.close()  # no pooled connection held while the store answers
    try:
        with store_slot():
            data = store.get(screenshot_key(access.project_id, sha256))
    except ArtifactNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")
    except ArtifactStoreBusy:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Artifact storage busy",
                            headers={"Retry-After": BUSY_RETRY_AFTER})
    return Response(content=data, media_type=media_type,
                    headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
