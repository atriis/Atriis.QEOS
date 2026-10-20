from fastapi import APIRouter

from src.ingestion.api.v1.endpoints import analytics, api_keys, blobs, collect, collection_settings, export, log_patterns, masking_patterns, notifications, report, runs, screenshots

api_router = APIRouter()
api_router.include_router(api_keys.router, prefix="/projects/{project_id}/api-keys", tags=["api-keys"])
api_router.include_router(
    masking_patterns.router, prefix="/projects/{project_id}/masking-patterns", tags=["masking"]
)
api_router.include_router(
    log_patterns.router, prefix="/projects/{project_id}/log-patterns", tags=["log-values"]
)
api_router.include_router(
    notifications.router, prefix="/projects/{project_id}/notification-channels", tags=["notifications"]
)
api_router.include_router(export.router, prefix="/projects/{project_id}/export", tags=["export"])
api_router.include_router(runs.project_router, prefix="/projects/{project_id}/runs", tags=["runs"])
api_router.include_router(analytics.router, prefix="/projects/{project_id}/analytics", tags=["analytics"])
api_router.include_router(report.router, prefix="/projects/{project_id}/analytics", tags=["analytics"])
api_router.include_router(runs.router, prefix="/runs", tags=["runs"])
api_router.include_router(
    screenshots.router, prefix="/projects/{project_id}/screenshots", tags=["screenshots"]
)
api_router.include_router(blobs.router, prefix="/collect/blobs", tags=["collect"])
api_router.include_router(collect.router, prefix="/collect", tags=["collect"])
api_router.include_router(
    collection_settings.router, prefix="/projects/{project_id}/collection-settings", tags=["collection"]
)

__all__ = ["api_router"]
