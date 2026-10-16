"""Configuration management for Project Service."""
from qeos_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    APP_NAME: str = "Project Service"
    APP_VERSION: str = "0.1.0"

    POSTGRES_DB: str = "project_db"

    # Every request's role comes from organization-service's members/me
    ORGANIZATION_SERVICE_URL: str = "http://localhost:8001"
    ORGANIZATION_SERVICE_TIMEOUT_SECONDS: float = 3.0

    # Public-API reachability check for repositories (GitHub allows 60 unauthenticated
    # requests per hour per server IP, shared by every user of the platform)
    REPO_VERIFY_TIMEOUT_SECONDS: float = 3.0
    REPO_VERIFY_COOLDOWN_SECONDS: int = 60

    # GET /internal/v1/projects/retention, for ingestion-service's retention job (HTTP Basic).
    # An empty password turns the endpoint off (503); it is never open by default.
    INTERNAL_API_USERNAME: str = "ingestion-service"
    INTERNAL_API_PASSWORD: str = ""

    # A deleted project is purged everywhere this long after the deletion; until then it can be restored
    PROJECT_DELETE_GRACE_DAYS: int = 7


settings = Settings()
