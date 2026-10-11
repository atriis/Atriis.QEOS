# qeos-shared

Configuration and database wiring shared by QEOS services.

## What's here

- `BaseServiceSettings` — the settings every service needs: app metadata, `API_V1_STR`,
  Postgres connection components, `SECRET_KEY`/`ALGORITHM`, CORS origins, and a
  `database_url` property that always returns a `str` and escapes the user and password.
- `make_session_factory(url)` / `make_get_db(factory)` — the engine, sessionmaker and
  FastAPI dependency each service would otherwise rewrite.
- `install_metrics(app, service="...", registry=None)` (`qeos_shared.metrics`) — request metrics named
  after blueprint §11.2 (`api_requests_total`, `http_requests_duration_seconds`,
  `http_requests_in_flight`, `build_info`), the process collector, and `GET /metrics`. Labels carry the
  route template, never the raw path. One uvicorn worker is assumed (see the module docstring).
- `load_catalog()` (`qeos_shared.overview_widgets`) — the Overview widget catalogue,
  `overview_widgets.json` beside the module: the 14 widget types, their settings and allowed values,
  and the layout limits (24 widgets, 64 KB). project-service validates layouts against it; the
  dashboard registry imports the same file (its Dockerfile copies it) and a dashboard test fails when
  the two disagree.

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
from qeos_shared.config import BaseServiceSettings
from qeos_shared.db import make_get_db, make_session_factory


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

The suite needs `pytest` and `psycopg` (psycopg 3, the driver SQLAlchemy 2.1 picks for a plain `postgresql://` URL) in addition to the package's own dependencies.
The simplest way to run it is with a service venv that already has both, e.g. on Windows:

```bash
cd shared && ../platforms/organization-service/.venv/Scripts/python.exe -m pytest tests/ -v
```
