"""Settings shared by every QEOS service."""
from typing import Optional
from urllib.parse import quote

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Subclass this and add whatever else your service needs."""

    APP_NAME: str = "QEOS Service"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    API_V1_STR: str = "/api/v1"

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "postgres"
    DATABASE_URL: Optional[PostgresDsn] = None

    # No default, deliberately: a service that cannot find a secret must refuse to start
    # rather than run on a predictable one. organization-service previously defaulted this
    # to the literal "your-secret-key-here".
    SECRET_KEY: str
    ALGORITHM: str = "HS256"

    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    # Outgoing email (qeos_shared.mail). Empty SMTP_HOST: no email is sent
    SMTP_TLS: bool = True
    SMTP_PORT: int = 587
    SMTP_HOST: str = ""
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    # True for a server that only takes signed-in mail (Azure Communication Services): without SMTP_USER and
    # SMTP_PASSWORD it would refuse every message, so mail counts as not configured. False (Compose's Mailpit and
    # other relays that need no sign-in): the credentials are optional
    SMTP_REQUIRE_LOGIN: bool = False
    EMAILS_FROM_EMAIL: str = ""
    EMAILS_FROM_NAME: str = ""

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")

    @property
    def database_url(self) -> str:
        """The database URL, always as a str.

        Every consumer either hands this to create_engine or calls a str method on it --
        organization-service's alembic/env.py does `.replace("%", "%%")`, which raises
        AttributeError against a PostgresDsn object. auth-service returned PostgresDsn and
        organization-service returned str; unifying on str removes that trap.

        The components path escapes user and password. Neither service's original
        components path was correct: organization-service's f-string didn't encode at
        all, and auth-service's `PostgresDsn.build` raised on a password containing `:`
        or `/` instead of escaping it. `quote(value, safe="")` is used rather than
        `quote_plus` because `quote_plus` turns a space into `+`, which a URL parser
        then decodes back as a literal `+` instead of a space -- corrupting the password.
        """
        if self.DATABASE_URL:
            return str(self.DATABASE_URL)
        user = quote(self.POSTGRES_USER, safe="")
        password = quote(self.POSTGRES_PASSWORD, safe="")
        return f"postgresql://{user}:{password}@{self.POSTGRES_SERVER}/{self.POSTGRES_DB}"
