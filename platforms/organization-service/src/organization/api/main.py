from fastapi import FastAPI
from qeos_shared.metrics import install_metrics
from starlette.middleware.cors import CORSMiddleware
from src.organization.api import internal
from src.organization.api.v1.api import api_router
from src.organization.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
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
app.include_router(internal.router, prefix="/internal/v1", include_in_schema=False)
install_metrics(app, service="organization")


@app.get("/health")
def health_check():
    return {"status": "healthy"}
