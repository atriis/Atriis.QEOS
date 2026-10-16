from fastapi import FastAPI
from qeos_shared.metrics import install_metrics
from starlette.middleware.cors import CORSMiddleware
from src.auth.api.v1.api import api_router
from src.auth.api.v1.endpoints import internal
from src.auth.config import settings
from src.auth.db.session import SessionLocal
from src.auth.service.auth_mode import apply_auth_mode, check_sso_only_settings, warn_if_no_break_glass
from src.auth.service import org_roles_sync
from src.auth.service.bootstrap import bootstrap_first_superuser

app = FastAPI(
    title=settings.APP_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)


@app.on_event("startup")
def _bootstrap_first_superuser() -> None:
    db = SessionLocal()
    try:
        bootstrap_first_superuser(db)
    finally:
        db.close()


@app.on_event("startup")
def _apply_auth_mode() -> None:
    # ADR-031. Registered after the bootstrap, so the superuser it creates counts for the warning.
    # A listed provider that cannot work stops start-up here, before any database access.
    check_sso_only_settings()
    org_roles_sync.warn_if_unconfigured()
    db = SessionLocal()
    try:
        apply_auth_mode(db)
        warn_if_no_break_glass(db)
    finally:
        db.close()

# Set all CORS enabled origins
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(internal.router, prefix="/internal/v1", include_in_schema=False)
install_metrics(app, service="auth")

@app.get("/health")
def health_check():
    return {"status": "healthy"}
