# Shared Package Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the config and database-session boilerplate that auth-service and organization-service each reimplemented into an installable `shared/` package, and retrofit both services onto it — fixing three real defects the divergence has already produced.

**Architecture:** A new root-level `shared/` package (`qav-shared` / `qav_shared`) holding `BaseServiceSettings` and two session factories. Each service installs it editable via a relative path in `requirements.txt`, and each Dockerfile mirrors the repo layout so that same relative path resolves inside the image. The declarative `Base` deliberately stays per-service.

**Tech Stack:** Python 3.11, Pydantic v2 / pydantic-settings, SQLAlchemy 2.0, setuptools, pytest, Docker.

**Spec:** `docs/superpowers/specs/2026-09-25-shared-package-extraction-design.md`

## Global Constraints

- Distribution name `qav-shared`; import name `qav_shared`; `requires-python = ">=3.11"`.
- Shared dependencies are lower bounds only: `pydantic>=2.7`, `pydantic-settings>=2.2`, `sqlalchemy>=2.0`. Services keep their exact pins.
- `BaseServiceSettings.SECRET_KEY` has **no default** — a service with no secret must refuse to start.
- `database_url` returns `str`, always, and escapes user and password with `quote_plus`.
- `Base = declarative_base()` stays in each service's own `db/base.py`. It does **not** move to `shared/`.
- No logging module and no exceptions module in `shared/` — neither service has either today.
- Both service suites must stay green: auth-service **60 tests**, organization-service **80 tests**.
- Both Dockerfiles move to `python:3.11-slim` and a repository-root build context.

---

### Task 1: Create the `shared/` package

**Files:**
- Create: `shared/pyproject.toml`
- Create: `shared/qav_shared/__init__.py`
- Create: `shared/qav_shared/config.py`
- Create: `shared/qav_shared/db.py`
- Create: `shared/tests/test_config.py`
- Create: `shared/tests/test_db.py`

**Interfaces:**
- Produces, consumed by Tasks 2 and 3:
  - `qav_shared.config.BaseServiceSettings` — a `pydantic_settings.BaseSettings` subclass with fields `APP_NAME, APP_VERSION, DEBUG, API_V1_STR, POSTGRES_SERVER, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, DATABASE_URL, SECRET_KEY, ALGORITHM, BACKEND_CORS_ORIGINS` and a read-only property `database_url -> str`.
  - `qav_shared.db.make_session_factory(database_url: str) -> sqlalchemy.orm.sessionmaker`
  - `qav_shared.db.make_get_db(session_factory: sessionmaker) -> Callable[[], Generator[Session, None, None]]`

- [ ] **Step 1: Create the package skeleton**

`shared/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "qav-shared"
version = "0.1.0"
description = "Shared configuration and database wiring for QA Vision Platform services"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.2",
    "sqlalchemy>=2.0",
]

# Declared explicitly rather than left to auto-discovery: with tests/ sitting beside
# qav_shared/, setuptools' flat-layout discovery errors out rather than guessing.
[tool.setuptools]
packages = ["qav_shared"]
```

`shared/qav_shared/__init__.py`:
```python
"""Shared configuration and database wiring for QA Vision Platform services."""
```

- [ ] **Step 2: Write the failing config tests**

`shared/tests/test_config.py`:
```python
from urllib.parse import quote_plus

import pytest
from pydantic import ValidationError

from qav_shared.config import BaseServiceSettings


class _Settings(BaseServiceSettings):
    """A concrete subclass, since BaseServiceSettings is meant to be extended."""

    model_config = BaseServiceSettings.model_config | {"env_file": None}


def test_explicit_database_url_wins_over_components():
    settings = _Settings(
        SECRET_KEY="x",
        DATABASE_URL="postgresql://someone:somewhere@dbhost/somedb",
        POSTGRES_USER="ignored",
        POSTGRES_PASSWORD="ignored",
        POSTGRES_SERVER="ignored",
        POSTGRES_DB="ignored",
    )
    assert settings.database_url == "postgresql://someone:somewhere@dbhost/somedb"


def test_database_url_is_built_from_components_when_unset():
    settings = _Settings(
        SECRET_KEY="x",
        POSTGRES_USER="svc",
        POSTGRES_PASSWORD="pw",
        POSTGRES_SERVER="dbhost",
        POSTGRES_DB="svc_db",
    )
    assert settings.database_url == "postgresql://svc:pw@dbhost/svc_db"


def test_database_url_escapes_password_special_characters():
    """organization-service built this with a raw f-string, so a password containing @ or :
    produced a URL that parses with the wrong host. The escaped form round-trips."""
    settings = _Settings(
        SECRET_KEY="x",
        POSTGRES_USER="svc",
        POSTGRES_PASSWORD="p@ss:w/rd",
        POSTGRES_SERVER="dbhost",
        POSTGRES_DB="svc_db",
    )
    assert quote_plus("p@ss:w/rd") in settings.database_url
    assert "@dbhost/svc_db" in settings.database_url
    # the raw password must not appear unescaped -- that is the bug being fixed
    assert "p@ss:w/rd@" not in settings.database_url


def test_database_url_is_always_a_str():
    """organization-service's alembic/env.py calls .replace() on this. auth-service
    returned a PostgresDsn, on which that raises AttributeError."""
    settings = _Settings(SECRET_KEY="x", DATABASE_URL="postgresql://a:b@c/d")
    assert isinstance(settings.database_url, str)
    assert settings.database_url.replace("%", "%%") == "postgresql://a:b@c/d"


def test_secret_key_is_required(monkeypatch):
    """Cleared from the environment explicitly: this suite must fail the same way whether
    or not the developer running it happens to have SECRET_KEY exported."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        _Settings()
```

- [ ] **Step 3: Run the config tests to verify they fail**

Run: `cd shared && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'qav_shared.config'`

- [ ] **Step 4: Write `qav_shared/config.py`**

```python
"""Settings shared by every QA Vision Platform service."""
from typing import Optional
from urllib.parse import quote_plus

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Subclass this and add whatever else your service needs."""

    APP_NAME: str = "QA Vision Service"
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

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")

    @property
    def database_url(self) -> str:
        """The database URL, always as a str.

        Every consumer either hands this to create_engine or calls a str method on it --
        organization-service's alembic/env.py does `.replace("%", "%%")`, which raises
        AttributeError against a PostgresDsn object. auth-service returned PostgresDsn and
        organization-service returned str; unifying on str removes that trap.

        The components path escapes user and password. auth-service got this right via
        PostgresDsn.build; organization-service's f-string did not, so any password
        containing @, / or : produced a malformed URL there.
        """
        if self.DATABASE_URL:
            return str(self.DATABASE_URL)
        user = quote_plus(self.POSTGRES_USER)
        password = quote_plus(self.POSTGRES_PASSWORD)
        return f"postgresql://{user}:{password}@{self.POSTGRES_SERVER}/{self.POSTGRES_DB}"
```

- [ ] **Step 5: Run the config tests to verify they pass**

Run: `cd shared && python -m pytest tests/test_config.py -v`
Expected: 5 passed

- [ ] **Step 6: Write the failing db tests**

`shared/tests/test_db.py`:
```python
import pytest
from sqlalchemy.orm import Session

from qav_shared.db import make_get_db, make_session_factory

SQLITE_URL = "sqlite://"  # in-memory, no file, no cleanup


def test_make_session_factory_produces_usable_sessions():
    factory = make_session_factory(SQLITE_URL)
    session = factory()
    try:
        assert isinstance(session, Session)
    finally:
        session.close()


def test_make_session_factory_does_not_connect_eagerly():
    """Both services' conftest.py import their db.session module while settings point at a
    Postgres URL that does not exist in the test environment. That only works because
    create_engine is lazy -- nothing may connect until first use."""
    factory = make_session_factory("postgresql://nobody:nothing@127.0.0.1:1/nowhere")
    assert factory is not None


def test_get_db_yields_a_session_and_closes_it():
    factory = make_session_factory(SQLITE_URL)
    get_db = make_get_db(factory)

    generator = get_db()
    session = next(generator)
    assert isinstance(session, Session)
    assert session.is_active

    with pytest.raises(StopIteration):
        next(generator)
    # after the generator finishes, the finally block has closed the session
    assert not session.in_transaction()


def test_get_db_closes_the_session_when_the_consumer_raises():
    factory = make_session_factory(SQLITE_URL)
    get_db = make_get_db(factory)

    generator = get_db()
    session = next(generator)

    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("consumer blew up"))

    assert not session.in_transaction()
```

- [ ] **Step 7: Run the db tests to verify they fail**

Run: `cd shared && python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'qav_shared.db'`

- [ ] **Step 8: Write `qav_shared/db.py`**

```python
"""Database session wiring shared by every QA Vision Platform service.

Note what is NOT here: the declarative Base. A declarative base is a mutable global
registry of mapped classes, so one shared instance would put separate services'
databases into a single Base.metadata -- and a create_all() in one service's test suite
would start creating another service's tables. Each service keeps its own three-line
db/base.py.
"""
from typing import Callable, Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_session_factory(database_url: str) -> sessionmaker:
    """Build the engine and session factory for one service's database.

    create_engine does not open a connection; the first connect happens on first use.
    That laziness is load-bearing: both services' conftest.py import their db.session
    module (to get get_db) while settings still point at a Postgres URL that does not
    exist in the test environment.
    """
    engine = create_engine(database_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def make_get_db(
    session_factory: sessionmaker,
) -> Callable[[], Generator[Session, None, None]]:
    """Build the FastAPI dependency that yields a session and always closes it."""

    def get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    return get_db
```

- [ ] **Step 9: Run the whole shared suite**

Run: `cd shared && python -m pytest tests/ -v`
Expected: 9 passed (5 config + 4 db)

- [ ] **Step 10: Verify the package actually installs**

Install it into one of the existing venvs as a smoke test — an editable install that fails here would otherwise fail confusingly in the middle of Task 2:

Run:
```bash
cd platforms/organization-service
.venv/Scripts/python.exe -m pip install -e ../../shared
.venv/Scripts/python.exe -c "from qav_shared.config import BaseServiceSettings; from qav_shared.db import make_get_db, make_session_factory; print('import ok')"
```
Expected: `Successfully installed qav-shared-0.1.0` then `import ok`

- [ ] **Step 11: Commit**

```bash
git add shared/
git commit -m "feat(shared): add qav-shared with BaseServiceSettings and session factories"
```

---

### Task 2: Retrofit organization-service

The simpler of the two services, and the one carrying both config defects — do it first so the abstraction meets a real consumer before auth-service depends on it.

**Files:**
- Modify: `platforms/organization-service/requirements.txt` (add the editable path)
- Modify: `platforms/organization-service/src/organization/core/config.py` (full rewrite, shown below)
- Modify: `platforms/organization-service/src/organization/db/session.py` (full rewrite, shown below)
- Modify: `platforms/organization-service/Dockerfile` (full rewrite, shown below)
- Modify: `platforms/organization-service/docker-compose.yml` (build stanza only)
- Test: `platforms/organization-service/tests/` (existing 80 tests, unchanged)

**Interfaces:**
- Consumes: `qav_shared.config.BaseServiceSettings`, `qav_shared.db.make_session_factory`, `qav_shared.db.make_get_db` (Task 1).
- Produces: nothing new. `settings`, `SessionLocal` and `get_db` keep the same names and import paths they have today, so no call site changes.

- [ ] **Step 1: Install the shared package into the service venv**

Run:
```bash
cd platforms/organization-service
.venv/Scripts/python.exe -m pip install -e ../../shared
```
Expected: `Successfully installed qav-shared-0.1.0` (or `already satisfied` if Task 1's Step 10 used this venv)

- [ ] **Step 2: Add the dependency to requirements.txt**

Append this as the last line of `platforms/organization-service/requirements.txt`:
```
# Relative path, resolved from this file's directory. The Dockerfile mirrors the repo
# layout so this same path resolves inside the image.
-e ../../shared
```

- [ ] **Step 3: Rewrite `src/organization/core/config.py`**

Replace the entire file with:
```python
"""Configuration management for Organization Service."""
from qav_shared.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    # Application
    APP_NAME: str = "Organization Service"
    APP_VERSION: str = "0.1.0"
    PROJECT_NAME: str = "Organization Service"

    # Database
    POSTGRES_DB: str = "organization_db"

    # Service-to-service call to auth-service for user existence checks
    AUTH_SERVICE_URL: str = "http://localhost:8000"
    AUTH_SERVICE_TOKEN: str = ""


settings = Settings()
```

Everything else the old file declared (`DEBUG`, `API_V1_STR`, `POSTGRES_SERVER/USER/PASSWORD`, `DATABASE_URL`, `SECRET_KEY`, `ALGORITHM`, `BACKEND_CORS_ORIGINS`, `model_config`, the `database_url` property) now comes from the base. `SECRET_KEY` loses its `"your-secret-key-here"` default and becomes required — both `.env.example` and `docker-compose.yml` already supply one, so nothing configured today breaks.

- [ ] **Step 4: Rewrite `src/organization/db/session.py`**

Replace the entire file with:
```python
from qav_shared.db import make_get_db, make_session_factory

from src.organization.core.config import settings

SessionLocal = make_session_factory(settings.database_url)
get_db = make_get_db(SessionLocal)
```

- [ ] **Step 5: Run the suite**

Run:
```bash
cd platforms/organization-service
rm -f test.db && SECRET_KEY=test-secret .venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: `80 passed`

If anything fails, do not adjust the tests — the retrofit is supposed to be behaviour-preserving for everything except the `SECRET_KEY` default. A failure means the base class and the old file disagree about a field; fix the config, not the test.

- [ ] **Step 6: Verify the required SECRET_KEY actually bites**

Run:
```bash
cd platforms/organization-service
.venv/Scripts/python.exe -c "import os; os.environ.pop('SECRET_KEY', None); from src.organization.core.config import Settings; Settings(_env_file=None)"
```
Expected: `pydantic_core._pydantic_core.ValidationError` naming `SECRET_KEY` as missing.

This is the security half of the change; if it does not raise, the base class default leaked back in.

- [ ] **Step 7: Rewrite the Dockerfile**

Replace `platforms/organization-service/Dockerfile` with:
```dockerfile
# Python 3.11 to match the version this service is developed and tested against; the
# image previously specified 3.9, which nothing ever ran.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# The repo layout is mirrored inside the image so that requirements.txt's
# `-e ../../shared` resolves to /app/shared, exactly as it resolves to the repo's
# shared/ during local development. One relative path, one source of truth.
COPY shared/ ./shared/
COPY platforms/organization-service/requirements.txt ./platforms/organization-service/

WORKDIR /app/platforms/organization-service
RUN pip install --no-cache-dir -r requirements.txt

# Application code and the migration tooling, so `alembic upgrade head` can run from the image
COPY platforms/organization-service/src/ ./src/
COPY platforms/organization-service/alembic/ ./alembic/
COPY platforms/organization-service/alembic.ini ./alembic.ini

EXPOSE 8000

CMD ["uvicorn", "src.organization.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 8: Point docker-compose at the new build context**

In `platforms/organization-service/docker-compose.yml`, replace:
```yaml
    build: .
```
with:
```yaml
    # Context is the repo root so the image can COPY shared/ alongside this service.
    build:
      context: ../..
      dockerfile: platforms/organization-service/Dockerfile
```
Leave every other line of the file unchanged.

- [ ] **Step 9: Verify the image builds**

Run:
```bash
cd platforms/organization-service && docker compose build organization-service
```
Expected: build completes, ending in a successful `pip install` that reports `qav-shared` among the installed packages.

- [ ] **Step 10: Commit**

```bash
git add platforms/organization-service/
git commit -m "refactor(organization-service): consume qav-shared for settings and session wiring"
```

---

### Task 3: Retrofit auth-service

**Files:**
- Modify: `platforms/auth-service/auth-service/requirements.txt` (add the editable path)
- Modify: `platforms/auth-service/auth-service/src/auth/config.py` (drop the shared fields, shown below)
- Modify: `platforms/auth-service/auth-service/src/auth/db/session.py` (full rewrite, shown below)
- Modify: `platforms/auth-service/auth-service/Dockerfile` (full rewrite, shown below)
- Modify: `platforms/auth-service/auth-service/docker-compose.yml` (build stanza only)
- Test: `platforms/auth-service/auth-service/tests/` (existing 60 tests, unchanged)

**Interfaces:**
- Consumes: `qav_shared.config.BaseServiceSettings`, `qav_shared.db.make_session_factory`, `qav_shared.db.make_get_db` (Task 1).
- Produces: nothing new. `settings`, `get_settings()`, `SessionLocal` and `get_db` keep their names and import paths.

- [ ] **Step 1: Install the shared package into the service venv**

Run:
```bash
cd platforms/auth-service/auth-service
.venv/Scripts/python.exe -m pip install -e ../../../shared
```
Expected: `Successfully installed qav-shared-0.1.0`

- [ ] **Step 2: Add the dependency to requirements.txt**

Append this as the last line of `platforms/auth-service/auth-service/requirements.txt`:
```
# Relative path, resolved from this file's directory. The Dockerfile mirrors the repo
# layout so this same path resolves inside the image.
-e ../../../shared
```

- [ ] **Step 3: Rewrite the top of `src/auth/config.py`**

Replace the imports and the class declaration through the `ALGORITHM` line — that is, everything from the file's first line down to and including `ALGORITHM: str = "HS256"` — with:

```python
"""
Configuration management for Auth Service
"""
from typing import Optional

from dotenv import load_dotenv
from pydantic import RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
from qav_shared.config import BaseServiceSettings

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
```

`SECRET_KEY`, `ALGORITHM`, `DEBUG`, `API_V1_STR`, `POSTGRES_SERVER/USER/PASSWORD` and `DATABASE_URL` all come from the base now. Keep every field below this point (`FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, the SMTP block, `EMAIL_VERIFICATION_EXPIRE_HOURS`, `BASE_URL`, the SSO provider block) exactly as it is — Step 4 handles the remaining shared declarations further down the file.

- [ ] **Step 4: Delete the CORS block, the `model_config` and the `database_url` property; keep `redis_url`**

`BACKEND_CORS_ORIGINS` sits near the bottom of this file, below the range Step 3 replaced, so it survives that edit and must be removed here. Redeclaring it would be legal Pydantic (same type, same default) but leaves two places to change one value. Delete:

```python
    # CORS
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]
```

Then delete this block entirely (the base provides both):

```python
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env"
    )

    @property
    def database_url(self) -> PostgresDsn:
        """Return database URL, either direct or constructed from components."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return PostgresDsn.build(
            scheme="postgresql",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            path=f"/{self.POSTGRES_DB or ''}"
        )
```

Keep the `redis_url` property, `get_settings()` and the module-level `settings = get_settings()` exactly as they are — Redis is auth-only and does not belong in the base.

After this step `PostgresDsn` and `SettingsConfigDict` may be unused imports in this file. Remove them if so; `RedisDsn` is still needed.

- [ ] **Step 5: Rewrite `src/auth/db/session.py`**

Replace the entire file with:
```python
from qav_shared.db import make_get_db, make_session_factory

from src.auth.config import settings

# This module previously hardcoded a postgres:// URL that ignored settings entirely, and
# later carried its own engine/sessionmaker/get_db boilerplate. Both now come from the
# shared package; settings.database_url is already a str, so the old str() wrapper and the
# SQLALCHEMY_DATABASE_URL constant it fed are gone (nothing imported that name).
SessionLocal = make_session_factory(settings.database_url)
get_db = make_get_db(SessionLocal)
```

Note `src/auth/db/base.py` is untouched — `Base` stays here, per the spec.

- [ ] **Step 6: Run the suite**

Run:
```bash
cd platforms/auth-service/auth-service
rm -f test.db && SECRET_KEY=test-secret .venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: `60 passed`

As in Task 2: a failure means the base class and the old config disagree. Fix the config, not the tests.

- [ ] **Step 7: Verify `database_url` is now a str and still correct**

Run:
```bash
cd platforms/auth-service/auth-service
SECRET_KEY=test-secret .venv/Scripts/python.exe -c "from src.auth.config import settings; u = settings.database_url; print(type(u).__name__, u); assert isinstance(u, str); print(u.replace('%', '%%'))"
```
Expected: prints `str postgresql://postgres:postgres@localhost/auth_db` (or whatever the local `.env` sets), then the same string again — proving the `.replace()` call that organization-service's alembic makes would now work here too.

- [ ] **Step 8: Rewrite the Dockerfile**

Replace `platforms/auth-service/auth-service/Dockerfile` with:
```dockerfile
# Python 3.11 to match the version this service is developed and tested against; the
# image previously specified 3.9, which nothing ever ran.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# The repo layout is mirrored inside the image so that requirements.txt's
# `-e ../../../shared` resolves to /app/shared, exactly as it resolves to the repo's
# shared/ during local development. One relative path, one source of truth.
COPY shared/ ./shared/
COPY platforms/auth-service/auth-service/requirements.txt ./platforms/auth-service/auth-service/

WORKDIR /app/platforms/auth-service/auth-service
RUN pip install --no-cache-dir -r requirements.txt

COPY platforms/auth-service/auth-service/src/ ./src/
COPY platforms/auth-service/auth-service/alembic/ ./alembic/
COPY platforms/auth-service/auth-service/alembic.ini ./alembic.ini

EXPOSE 8000

CMD ["python", "src/auth/main.py"]
```

- [ ] **Step 9: Point docker-compose at the new build context**

In `platforms/auth-service/auth-service/docker-compose.yml`, replace:
```yaml
    build: .
```
with:
```yaml
    # Context is the repo root so the image can COPY shared/ alongside this service.
    build:
      context: ../../..
      dockerfile: platforms/auth-service/auth-service/Dockerfile
```
Leave every other line unchanged.

- [ ] **Step 10: Verify the image builds**

Run:
```bash
cd platforms/auth-service/auth-service && docker compose build auth-service
```
Expected: build completes, with `qav-shared` among the installed packages.

- [ ] **Step 11: Run both suites together, to confirm nothing crossed over**

Run:
```bash
cd platforms/auth-service/auth-service && rm -f test.db && SECRET_KEY=test-secret .venv/Scripts/python.exe -m pytest tests/ -q
cd ../../organization-service && rm -f test.db && SECRET_KEY=test-secret .venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: `60 passed` then `80 passed`.

- [ ] **Step 12: Commit**

```bash
git add platforms/auth-service/auth-service/
git commit -m "refactor(auth-service): consume qav-shared for settings and session wiring"
```

---

### Task 4: Document the shared package

**Files:**
- Create: `shared/README.md`
- Modify: `README.md` (repo root — the Project Structure block)

**Interfaces:** none (docs only).

- [ ] **Step 1: Write `shared/README.md`**

```markdown
# qav-shared

Configuration and database wiring shared by QA Vision Platform services.

## What's here

- `BaseServiceSettings` — the settings every service needs: app metadata, `API_V1_STR`,
  Postgres connection components, `SECRET_KEY`/`ALGORITHM`, CORS origins, and a
  `database_url` property that always returns a `str` and escapes the user and password.
- `make_session_factory(url)` / `make_get_db(factory)` — the engine, sessionmaker and
  FastAPI dependency each service would otherwise rewrite.

## What's deliberately not here

- **`Base = declarative_base()`.** A declarative base is a mutable global registry of
  mapped classes; sharing one instance would put separate services' models into a single
  `Base.metadata`. Each service keeps its own `db/base.py`.
- **Logging and exception modules.** No service configures logging or defines a custom
  exception hierarchy today, so there is nothing to consolidate — only new abstraction to
  invent against zero real usage.

## Using it

Add to your service's `requirements.txt`, as a path relative to that file:

```
-e ../../shared
```

Then:

```python
from qav_shared.config import BaseServiceSettings
from qav_shared.db import make_get_db, make_session_factory


class Settings(BaseServiceSettings):
    APP_NAME: str = "Your Service"
    POSTGRES_DB: str = "your_db"


settings = Settings()
SessionLocal = make_session_factory(settings.database_url)
get_db = make_get_db(SessionLocal)
```

`SECRET_KEY` has no default. A service without one in its environment will not start.

## Dockerfiles

Mirror the repo layout inside the image so the relative path in `requirements.txt`
resolves there too — see either service's Dockerfile for the pattern. The build context
must be the repository root.

## Tests

```bash
cd shared && python -m pytest tests/ -v
```
```

- [ ] **Step 2: Add `shared/` to the root README's Project Structure block**

In the repository root `README.md`, find the `## Project Structure` code block and add this line immediately after the `Atriis.QEOS/` line, before `├── platforms/`:

```
├── shared/                         # qav-shared: settings + DB session wiring used by services
```

- [ ] **Step 3: Commit**

```bash
git add shared/README.md README.md
git commit -m "docs(shared): document qav-shared and add it to the repo structure"
```
