import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.api.deps import get_db
from src.ingestion.api.key_auth import get_api_key
from src.ingestion.core.config import settings
from src.ingestion.models import ApiKey
from src.ingestion.schemas.collect import KeyCheck, RunReceipt, RunUpload
from src.ingestion.service import ingest_service, notification_service, run_service
from src.ingestion.utils import metrics

logger = logging.getLogger(__name__)
router = APIRouter()  # mounted at /collect

SERVICE_TOKEN_SECONDS = 300
IMPORT_SCOPE = "cases:import"


@router.get("/key", response_model=KeyCheck)
def check_key(key: ApiKey = Depends(get_api_key)):
    """Proof the key works, for `qeos-collector check` — uploads nothing."""
    return key


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
    key.last_used_at = now
    db.commit()
    return {
        "token": jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM),
        "expires_in": SERVICE_TOKEN_SECONDS, "project_id": key.project_id,
    }


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
    idempotency_key: Optional[str] = Header(
        None, alias="Idempotency-Key", min_length=1, max_length=255, pattern=r"^[\x21-\x7e]+$"
    ),
):
    with metrics.DURATION.time():
        try:
            run, created = ingest_service.ingest(db, key, upload, idempotency_key)
        except ingest_service.Discarded as exc:
            metrics.DISCARDED.labels(reason="manual").inc()
            logger.info("upload discarded", extra={"project_id": key.project_id, "api_key_id": key.id,
                                                   "ci_run_url": upload.run.ci_run_url, "reason": exc.reason})
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
    else:
        response.status_code = status.HTTP_200_OK
    return RunReceipt.model_validate(run).model_copy(update=run_service.quarantine_counts(db, run))
