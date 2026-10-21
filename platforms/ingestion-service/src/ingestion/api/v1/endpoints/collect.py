import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.api.deps import get_db
from src.ingestion.api.key_auth import get_api_key
from src.ingestion.api.v1.endpoints.analytics import ImpactIn, score_or_503
from src.ingestion.core.config import settings
from src.ingestion.models import ApiKey
from src.ingestion.schemas.collect import KeyCheck, RunReceipt, RunUpload
from src.ingestion.schemas.impact import SuggestionOut
from src.ingestion.service import artifact_service, blob_service, impact_service, ingest_service, notification_service, run_service
from src.ingestion.utils import metrics
from src.ingestion.utils.artifact_store import ArtifactStore, get_artifact_store

logger = logging.getLogger(__name__)
router = APIRouter()  # mounted at /collect

SERVICE_TOKEN_SECONDS = 300
IMPORT_SCOPE = "cases:import"
IMPACT_NOT_ALLOWED = {
    "code": "impact_not_allowed",
    "message": "This API key may not read test suggestions. Ask a project owner or admin to allow test suggestions "
               "for this key.",
}


def _touch(db: Session, key: ApiKey, now: Optional[datetime] = None) -> None:
    """Marks the key as used, the way an upload does."""
    key.last_used_at = now or datetime.now(timezone.utc)
    db.commit()


@router.get("/key", response_model=KeyCheck)
def check_key(
    key: ApiKey = Depends(get_api_key), db: Session = Depends(get_db),
    store: Optional[ArtifactStore] = Depends(get_artifact_store),
):
    """Proof the key works, for `qeos-collector check` — uploads nothing. Also the collector's one signal whether to
    send step screenshots and traces: a HEAD on a blob has no body to say it."""
    return KeyCheck(
        project_id=key.project_id, name=key.name, can_read_impact=key.can_read_impact,
        screenshots=blob_service.screenshots_enabled(db, key.project_id, store),
        artifacts=artifact_service.traces_enabled(db, key.project_id, store),
    )


@router.post("/token")
def import_token(db: Session = Depends(get_db), key: ApiKey = Depends(get_api_key)):
    """Trades the project's API key for a 5-minute token that test-management accepts on its
    import route only (ADR-024). `sub` is not a number, so every user route rejects it."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": f"apikey:{key.id}", "project_id": key.project_id, "organization_id": key.organization_id,
        "scope": IMPORT_SCOPE, "token_type": "service",
        "iat": now, "exp": now + timedelta(seconds=SERVICE_TOKEN_SECONDS),
    }
    _touch(db, key, now)
    return {
        "token": jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM),
        "expires_in": SERVICE_TOKEN_SECONDS, "project_id": key.project_id,
    }


def get_impact_key(key: ApiKey = Depends(get_api_key)) -> ApiKey:
    """A key an owner or admin allowed to read test suggestions (can_read_impact, spec 2026-10-13 §9). Resolved before
    the body is validated, so a key without the permission learns nothing more than the 403."""
    if not key.can_read_impact:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=IMPACT_NOT_ALLOWED)
    return key


@router.post("/impact", response_model=SuggestionOut)
def collect_impact(body: ImpactIn, db: Session = Depends(get_db), key: ApiKey = Depends(get_impact_key)):
    """Likely affected tests for a change, for `qeos-collector impact` and `run-impact` (spec 2026-10-13 §2): the
    scoring of POST /projects/{id}/analytics/impact for the key's own project, with the key instead of a user's token.
    Reads only; stores nothing beyond the key's last_used_at."""
    _touch(db, key)
    return score_or_503(db, key.project_id, body)


@router.post(
    "/runs", response_model=RunReceipt, status_code=status.HTTP_201_CREATED,
    responses={202: {"description": "Accepted and not stored (manual run, ADR-030)"}},
)
def collect_run(
    upload: RunUpload,
    response: Response,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(get_api_key),
    store: Optional[ArtifactStore] = Depends(get_artifact_store),
    idempotency_key: Optional[str] = Header(
        None, alias="Idempotency-Key", min_length=1, max_length=255, pattern=r"^[\x21-\x7e]+$"
    ),
):
    with metrics.DURATION.time():
        try:
            run, created = ingest_service.ingest(db, key, upload, idempotency_key, store)
        except ingest_service.Discarded as exc:
            metrics.DISCARDED.labels(reason="manual").inc()
            logger.warning("upload discarded: project=%s api_key_id=%s ci_run_url=%s reason=%s",
                           key.project_id, key.id, exc.ci_run_url, exc.reason)
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED,
                                content={"discarded": True, "reason": exc.reason})
        except ingest_service.IdempotencyConflict:
            metrics.REJECTED.labels(reason="conflict").inc()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Idempotency-Key reused with a different payload"
            )
    if created:
        metrics.RUNS.inc()
        metrics.RESULTS.inc(run.total)
        for name in ("passed", "failed", "errored", "skipped"):
            metrics.EXECUTIONS.labels(status=name).inc(getattr(run, name))
        if run.failed + run.errored:
            # After the response: the collector never waits on Slack or Teams
            background.add_task(notification_service.notify_run, sessionmaker(bind=db.get_bind()), run.id)
        # A run of only the suggested tests is never evaluated (spec 2026-10-13 §3.1)
        if run.changed_files and run.is_full:
            # After the response, from the stored results: the outcome of the suggestion stored with the run (spec
            # §3.4). Never in the request: finding the new failures takes 120-585 ms per run
            background.add_task(impact_service.evaluate_run, sessionmaker(bind=db.get_bind()), run.id)
    else:
        response.status_code = status.HTTP_200_OK
    return RunReceipt.model_validate(run).model_copy(update=run_service.quarantine_counts(db, run))
