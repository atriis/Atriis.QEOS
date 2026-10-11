"""
Configuration management for Auth Service
"""
from typing import Optional

from dotenv import load_dotenv
from pydantic import RedisDsn
from qeos_shared.config import BaseServiceSettings

# Load environment variables
load_dotenv()


class Settings(BaseServiceSettings):
    # Application
    APP_NAME: str = "Auth Service"
    APP_VERSION: str = "0.1.0"

    # Database
    POSTGRES_DB: str = "auth_db"

    # Redis - Individual components (for backwards compatibility)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # Redis - Full URL (optional, overrides individual components if set)
    REDIS_URL: Optional[RedisDsn] = None

    # Security
    # 60 minutes, was 8 days. Nothing can revoke an access token -- get_current_user decodes
    # the JWT and loads the user, with no database check against revocation -- so this value
    # IS the revocation delay. Logging out, changing a password or deactivating an account
    # all left a captured token able to read and modify the account for the rest of those 8
    # days. Refresh tokens are the long-lived, revocable half of the pair; the access token
    # should be short enough that its irrevocability stops mattering.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30  # 30 days

    # Superuser. Optional: nothing in this service reads these today, and making them
    # required meant Settings() raised on import, so the app could not start at all.
    # No default password is supplied on purpose -- a baked-in one would be worse than absent.
    FIRST_SUPERUSER: Optional[str] = None
    FIRST_SUPERUSER_PASSWORD: Optional[str] = None

    # Internal API (service-to-service, never routed by the gateway). Same pattern as
    # project-service's retention API: HTTP Basic with a shared secret. Unset password
    # means the internal API answers 503 rather than accepting anything.
    INTERNAL_API_USERNAME: str = "organization-service"
    INTERNAL_API_PASSWORD: str = ""

    # Monitoring (spec 2026-10-10, ADR-027): offer Grafana at /grafana/ to superusers. Same .env value
    # the gateway reads; the compose profile `monitoring` must be on too
    MONITORING_ENABLED: bool = False

    # Email: SMTP_* and EMAILS_FROM_* come from qeos_shared's BaseServiceSettings

    # Email verification (registration). BASE_URL has no other purpose in this service --
    # it exists so the verification link in the email points somewhere real. Defaulting to
    # localhost:8000 matches this service's own default port.
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24
    # Short on purpose: a reset link in a forwarded or leaked email should die quickly
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    BASE_URL: str = "http://localhost:8000"

    # SSO Providers
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    AZURE_TENANT_ID: str = ""
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    # Microsoft (Entra ID) sign-in: the tenants allowed to sign in, comma-separated tenant ids.
    # Empty falls back to AZURE_TENANT_ID as a one-entry list.
    AZURE_ALLOWED_TENANTS: str = ""
    SAML_SETTINGS: str = "{}"

    @property
    def redis_url(self) -> RedisDsn:
        """Return Redis URL, either direct or constructed from components."""
        if self.REDIS_URL:
            return self.REDIS_URL
        return RedisDsn.build(
            scheme="redis",
            host=self.REDIS_HOST,
            port=str(self.REDIS_PORT),
            path=f"/{self.REDIS_DB}"
        )

    @property
    def azure_allowed_tenants(self) -> list[str]:
        """Tenant ids are GUIDs; tokens carry them lower-cased."""
        raw = self.AZURE_ALLOWED_TENANTS or self.AZURE_TENANT_ID
        return [tenant.strip().lower() for tenant in raw.split(",") if tenant.strip()]


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
