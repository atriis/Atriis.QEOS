"""Configuration management for Test Management Service."""
from qeos_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    APP_NAME: str = "Test Management Service"
    APP_VERSION: str = "0.1.0"

    POSTGRES_DB: str = "testmgmt_db"

    # People's roles come from project-service's GET /projects/{id} (my_role)
    PROJECT_SERVICE_URL: str = "http://localhost:8002"
    PROJECT_SERVICE_TIMEOUT_SECONDS: float = 3.0

    # Internal API (DELETE /internal/v1/projects/{id}), called by ingestion's purge job with HTTP Basic
    # (spec 2026-10-16). An empty password turns it off (503); it is never open by default.
    INTERNAL_API_USERNAME: str = "ingestion-service"
    INTERNAL_API_PASSWORD: str = ""

    # Gherkin import (ADR-023): one request is one transaction; these keep it bounded.
    # Raise them in .env; the gateway's GATEWAY_IMPORT_MAX_BODY must stay above the total
    IMPORT_MAX_FILES: int = 2000
    IMPORT_MAX_FILE_BYTES: int = 262144
    IMPORT_MAX_TOTAL_BYTES: int = 10485760

    # Running tests from QEOS: the Fernet key that encrypts each project's GitHub token.
    # Empty turns the feature off (GET ci-target says available=false, PUT answers 503). Generate one:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    TM_SECRETS_KEY: str = ""


settings = Settings()
