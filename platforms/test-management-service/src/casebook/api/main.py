from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from qeos_shared.metrics import install_metrics
from starlette.middleware.cors import CORSMiddleware

from src.casebook.api import internal
from src.casebook.api.v1.api import api_router
from src.casebook.core.config import settings
from src.casebook.utils import metrics

app = FastAPI(
    title=settings.APP_NAME,
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


@app.exception_handler(RequestValidationError)
def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's 422 echoes each error's `input`, which for a body error is the whole body: a GitHub
    token would come back. Drop `input` and `ctx` (which can hold the value too)."""
    errors = [{k: v for k, v in error.items() if k not in ("input", "ctx")} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


app.include_router(api_router, prefix=settings.API_V1_STR)
# Service-to-service only: not routed by the gateway, not in the public OpenAPI
app.include_router(internal.router, prefix="/internal/v1", include_in_schema=False)
install_metrics(app, service="test-management", registry=metrics.REGISTRY)


@app.get("/health")
def health_check():
    return {"status": "healthy"}
