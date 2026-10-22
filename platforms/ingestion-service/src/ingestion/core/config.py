"""Configuration management for Ingestion Service."""
from typing import Optional

from qeos_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    APP_NAME: str = "Ingestion Service"
    APP_VERSION: str = "0.1.0"

    POSTGRES_DB: str = "ingestion_db"

    # People's roles come from project-service's GET /projects/{id} (my_role)
    PROJECT_SERVICE_URL: str = "http://localhost:8002"
    PROJECT_SERVICE_TIMEOUT_SECONDS: float = 3.0

    # One upload is one transaction; these keep it bounded
    MAX_RESULTS_PER_RUN: int = 20000
    MAX_TEXT_BYTES: int = 65536

    # The retention job (src/ingestion/jobs/retention.py). project-service's internal API with
    # HTTP Basic credentials in the URL: http://user:password@host:port (percent-encode special
    # characters in the password), or http://host:port with the password in INTERNAL_API_PASSWORD (user
    # "ingestion-service"): on Kubernetes the password comes from Key Vault, not a ConfigMap
    PROJECT_SERVICE_INTERNAL_URL: str = ""
    INTERNAL_API_PASSWORD: str = ""
    RETENTION_INTERVAL_HOURS: float = 24.0
    RETENTION_BATCH_SIZE: int = 500
    # A deleted project's runs are kept this long after the deletion (it can still be undone)
    # A deleted project waits this long, restorable, before the retention job purges it everywhere (spec 2026-10-16)
    PROJECT_DELETE_GRACE_DAYS: int = 7
    # test-management's internal API for that purge, with HTTP Basic credentials: http://user:password@host:port, or without them (INTERNAL_API_PASSWORD).
    # Unset: deleted projects are never purged (the purge needs every service), and each pass says so
    TEST_MANAGEMENT_INTERNAL_URL: str = ""
    # The log-value re-scan (ADR-032): results per committed batch, and whether a scan queued when the service
    # stopped runs again when it starts (off in the tests)
    LOG_SCAN_BATCH_SIZE: int = 500
    LOG_SCAN_RESUME_ON_STARTUP: bool = True

    # Artifact storage for screenshots (ADR-036): any S3-compatible service, MinIO in the compose files. Unless all
    # four are set there is no store and screenshots are off
    ARTIFACTS_S3_ENDPOINT: Optional[str] = None
    ARTIFACTS_S3_BUCKET: Optional[str] = None
    ARTIFACTS_S3_ACCESS_KEY: Optional[str] = None
    ARTIFACTS_S3_SECRET_KEY: Optional[str] = None
    # s3 (the four settings above) or azure: Azure Blob through DefaultAzureCredential, workload identity on AKS, no
    # keys (ADR-038). With azure and no account URL (https://<account>.blob.core.windows.net) there is no store either
    ARTIFACTS_BACKEND: str = "s3"
    ARTIFACTS_AZURE_ACCOUNT_URL: Optional[str] = None
    ARTIFACTS_AZURE_CONTAINER: str = "qeos-artifacts"

    # Public origin of the dashboard, for the run link in failure notifications. Empty: no link
    DASHBOARD_URL: str = ""
    NOTIFY_TIMEOUT_SECONDS: float = 5.0
    # Weekly summaries go out on Mondays from this hour (UTC), for the previous ISO week
    WEEKLY_SUMMARY_HOUR_UTC: int = 7


settings = Settings()
