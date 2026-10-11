# Project Service

Test projects owned by organizations, the repositories attached to them, and per-project settings.

Design: `docs/superpowers/specs/2026-09-28-project-service-design.md`.

## How access works

There are no project-level members. Every request asks organization-service for the caller's role
(`GET /api/v1/organizations/{org_id}/members/me`, forwarding the caller's own token):

| | owner / admin | member | viewer / billing_manager |
|---|---|---|---|
| Create, rename, delete projects | ✓ | | |
| Change settings, add/verify/remove repositories | ✓ | ✓ | |
| Read projects and repositories | ✓ | ✓ | ✓ |

Non-members get 404, never 403. If organization-service cannot answer, requests get 503.

## Repositories

Only `github.com`, `gitlab.com` and Azure DevOps URLs are accepted. Azure DevOps takes browser
and clone forms: `dev.azure.com/org/project/_git/repo` (an `org@` user name in clone URLs is
allowed and dropped), legacy `org.visualstudio.com/[DefaultCollection/]project/_git/repo`, and
SSH `git@ssh.dev.azure.com:v3/org/project/repo`. They are stored as owner `org/project`, and
project names may contain spaces. On save, the service checks the repository
through the provider's public API and records `verification_status`:

- `verified` — reachable; the provider's default branch is used unless you supplied one
- `not_found` — missing **or private** (the check is unauthenticated, so the two look the same)
- `unchecked` — the provider was unreachable or rate-limited

The repository is saved in every case. `POST .../repositories/{id}/verify` re-checks it, at most
once per `REPO_VERIFY_COOLDOWN_SECONDS` (default 60): GitHub allows 60 anonymous requests per hour
per server IP, shared by every user.

## Legal hold

`PUT /api/v1/projects/{id}/legal-hold` `{"reason": "…"}` places a hold, and `DELETE` releases it.
Both are for owners and admins only, and the reason is required. While held, retention deletes
nothing of the project. Every `GET /projects/{id}` shows `legal_hold: {since, by, reason}`, or
`null` when there is no hold. The hold is stored in its own columns, not in `settings`: settings
are editable by members, and a hold must record who placed it, when and why.

## Settings

`PATCH /api/v1/projects/{id}/settings` merge-patches: a key replaces, `null` reverts to the default,
an unknown key is a 422. Keys: `result_retention_days` (1–365, default 90), `default_environment`,
`notify_on_failure`.

## Overview layouts

The project Overview is a grid of widgets (spec `docs/superpowers/specs/2026-10-11-customisable-overview-design.md`).
Table `overview_layouts` (migration 004): one optional project default (`user_id` NULL) and one optional
personal layout per user, each a JSONB `layout` with a `version`.

| Method, path (`/api/v1/projects/{id}/overview-layout`) | Roles | Behaviour |
|---|---|---|
| `GET` | every project role | `{effective, source, personal, project}`: the caller's personal layout, else the project default, else `source: "builtin"` with `effective: null` (the dashboard holds the built-in default). `personal` is `{version, updated_at}`, `project` is `{version, updated_by, updated_at, layout}`, each `null` when absent |
| `PUT /personal` | every project role | `{"layout": ..., "version": n}`; `0` creates. Returns `{layout, version, updated_by, updated_at}` |
| `DELETE /personal` | every project role | back to the project default; 204 |
| `PUT /project` | owner, admin | as `PUT /personal`, for the project default |
| `DELETE /project` | owner, admin | back to the built-in default; 204 |

```json
{"schema": 1, "widgets": [{"id": "w1", "type": "pass_rate_trend", "size": "wide", "settings": {"granularity": "week", "branch": "main"}}]}
```

- **Validation** follows `shared/qeos_shared/overview_widgets.json`, the same file the dashboard registry
  imports: `schema` 1, at most 24 widgets, unique ids of 1–32 characters `[A-Za-z0-9_-]`, a known `type`,
  `size` `normal` or `wide`, only the settings the type declares with allowed values (branch and author
  name: 1–255 characters, no NUL; a widget without a `branch` setting shows all branches), a body of at
  most 64 KB (65536 bytes, judged after the role check). Anything else is a 422.
- **Versions:** a save names the version it started from. If the stored version differs (someone saved in
  between), or a row already exists for `version: 0`, the answer is 409 with
  `{"detail": {"code": "stale_version", "message": ..., "current": {version, updated_by, updated_at} | null}}`.
  DELETE takes no version.
- **Lifecycle:** the role check runs first, so the personal layout of someone who left the organization is
  never served (the row stays; it is a few KB). Deleting a project row deletes its layouts (`ON DELETE
  CASCADE`); a soft-deleted project's layouts answer 404 like the project.

## Internal API

`GET /internal/v1/projects/retention` lists every project — deleted ones too — with its effective
`result_retention_days` and whether it is on legal hold, for ingestion-service's retention job:

```json
{"projects": [{"project_id": 7, "result_retention_days": 90, "deleted": false, "deleted_at": null, "legal_hold": false}]}
```

- HTTP Basic, checked against `INTERNAL_API_USERNAME` (default `ingestion-service`) and
  `INTERNAL_API_PASSWORD`. Wrong or missing credentials: 401. A user's JWT is not accepted here,
  and these credentials are accepted nowhere else.
- With `INTERNAL_API_PASSWORD` unset the endpoint answers 503 — it is never open by default.
- The gateway does not route `/internal`, and the endpoint is not in the OpenAPI schema.

Prometheus metrics are served at `/metrics`; the gateway does not route it either.

## Running locally

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # also installs ../../shared
cp .env.example .env                                         # set SECRET_KEY = auth-service's
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn src.project.api.main:app --reload --port 8002
```

API docs: http://localhost:8002/docs

With Docker (organization-service running in its own stack on host port 8001):

```bash
export SECRET_KEY=<same value as auth-service and organization-service>
docker compose up -d --build
docker compose exec project-service alembic upgrade head  # first run, and after every pull that adds a migration
```

## Known limitations

- Response codes reveal whether a project id exists: a non-member gets 404 without organization-service
  being contacted, while a member gets 404/503 only after it answers. Project ids are sequential and no
  project data is exposed, so this is not treated as an information leak.
- A request waits on organization-service (up to 3s) and, when adding or re-verifying a repository, on the
  provider too (up to 3s more). Its database transaction is closed before each outbound call, so a slow
  upstream does not hold a pooled connection.

## Tests

```bash
SECRET_KEY=test-secret .venv/Scripts/python.exe -m pytest tests/ -q
```

Every outgoing HTTP call in the suite is mocked with `respx`; an unmocked request fails the test.
