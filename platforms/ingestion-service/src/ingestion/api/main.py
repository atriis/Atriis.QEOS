import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from qeos_shared.metrics import install_metrics
from starlette.middleware.cors import CORSMiddleware

from src.ingestion.api.v1.api import api_router
from src.ingestion.core.config import settings
from src.ingestion.jobs import log_scan
from src.ingestion.utils import metrics
from src.ingestion.utils.job_metrics import JobHeartbeatCollector, make_heartbeat_session_factory


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _resume_log_scans()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=_lifespan,
)

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)

# Ingestion's own registry, so the qav_* metrics keep their names on the same page (spec §3)
install_metrics(app, service="ingestion", registry=metrics.REGISTRY)
HEARTBEATS = JobHeartbeatCollector(make_heartbeat_session_factory(settings.database_url))
metrics.REGISTRY.register(HEARTBEATS)


def _resume_log_scans() -> None:
    """A log-value scan queued when the service last stopped (ADR-032) runs again, in a thread: start-up does not
    wait for it, and the per-project lock keeps a second worker from scanning the same project."""
    if not settings.LOG_SCAN_RESUME_ON_STARTUP:
        return
    from src.ingestion.db.session import SessionLocal

    threading.Thread(target=log_scan.resume_all, args=(SessionLocal,), name="log-scan-resume", daemon=True).start()


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's 422 echoes each error's `input` (for a body error, the whole body: a secret in an upload would come
    back) and `ctx`, which can hold the value too. A NaN there made the default handler itself fail with a 500. Both
    are dropped, as in test-management (ADR-025). 422s on the upload endpoint are counted."""
    if request.url.path == f"{settings.API_V1_STR}/collect/runs":
        metrics.REJECTED.labels(reason="validation").inc()
    errors = [{k: v for k, v in error.items() if k not in ("input", "ctx")} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


@app.get("/health")
def health_check():
    return {"status": "healthy"}

