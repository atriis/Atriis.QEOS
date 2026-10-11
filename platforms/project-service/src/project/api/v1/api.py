from fastapi import APIRouter

from src.project.api.v1.endpoints import overview_layout, projects, repositories

api_router = APIRouter()
api_router.include_router(projects.org_router, prefix="/organizations/{org_id}/projects", tags=["projects"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(
    repositories.router, prefix="/projects/{project_id}/repositories", tags=["repositories"]
)
api_router.include_router(
    overview_layout.router, prefix="/projects/{project_id}/overview-layout", tags=["overview-layout"]
)

__all__ = ["api_router"]
