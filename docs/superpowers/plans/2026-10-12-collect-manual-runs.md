# Collect manual CI runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-project toggle that makes QEOS accept and discard uploads from CI runs a person started by hand.

**Architecture:** ingestion-service owns a `collection_settings` row per project and checks it on the upload path
(no cross-service call). The collector classifies each run's trigger from the CI environment and sends it as
`run.trigger`. The dashboard's Project Settings gets a Collection card.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL / SQLite in tests (ingestion); Python stdlib (collector,
3.9+); React 19, TanStack Query, MSW, Vitest (dashboard); NGINX.

**Spec:** `docs/superpowers/specs/2026-10-12-collect-manual-runs-design.md`

## Global Constraints

- Trigger values, exactly: `manual`, `automatic`, `qeos`. Unknown: field omitted, run collected.
- Default `collect_manual = true`; no row means the defaults; no backfill.
- Discard answer: HTTP `202`, body `{"discarded": true, "reason": "manual runs are not collected for this project"}`.
- Collector notice, exactly: `qeos: run not collected: manual runs are not collected for this project`; exit 0.
- Settings `GET`: `READ_ROLES`. `PUT`: owner and admin only (`MANAGE_ROLES = ("owner", "admin")`).
- ADR number 030. Migration revision `019`, down-revision `018` — re-check `alembic/versions` before starting
  Task 1 and take the next free number if another branch landed first.
- Collector version `0.5.0`, tag `collector-v0.5.0`.
- Never write the employer's name in code, tests, docs or commits; use `acme`, `example-org`, `octocat`.
- Each delivery step (server: Tasks 1–5; collector: 6–8; dashboard: 9–10) lands on master only after every CI
  step passes locally (`.github/workflows/ci.yml`: service pytest matrix, collector pytest, dashboard
  `npm run lint && npm run typecheck && npx vitest run && npm run build`, `python scripts/check_architecture_docs.py`).

## Review Focus

1. **Idempotent replay of a run stored while the toggle was on, after it is switched off** — must return the stored
   run (200), not a discard. Pinned in Task 3 (`test_replay_of_a_stored_run_is_not_discarded_later`).
2. **Matrix jobs uploading in parallel while off** — every discard counted. Pinned in Task 3
   (`test_concurrent_discards_are_all_counted`, sequential-in-threads against the real session factory).
3. **A multi-part upload (more than `MAX_RESULTS_PER_RUN` results) while off** — the collector stops after the first
   202 and does not send the remaining parts. Pinned in Task 7 (`test_a_discarded_first_part_stops_the_upload`).
4. **`--gate` / `--fail-on-error` on a discarded run** — exit 0, never a failed build. Pinned in Task 7
   (`test_gate_on_a_discarded_run_exits_zero`).
5. **GitHub event payload missing, unreadable or not JSON** — no crash, no `qeos`; classification continues.
   Pinned in Task 6 (`test_unreadable_event_payload_is_not_qeos`).

---

## Delivery 1 — server

### Task 1: Data model and migration 019

**Files:**
- Create: `platforms/ingestion-service/alembic/versions/019_collection_settings.py`
- Create: `platforms/ingestion-service/src/ingestion/models/collection_settings.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/__init__.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/run.py` (column + check constraint)
- Test: `platforms/ingestion-service/tests/unit/test_migration.py`

**Interfaces:**
- Produces: `CollectionSettings` model (table `collection_settings`: `project_id` int PK, `collect_manual` bool
  not null server default true, `discarded_count` int not null server default 0, `last_discarded_at` timestamptz
  null, `updated_at` timestamptz null, `updated_by` int null); `TRIGGERS = ("manual", "automatic", "qeos")` in
  `models/run.py`; `Run.trigger` (`String(10)`, nullable).

- [ ] **Step 1: Write the failing migration tests** (append to `tests/unit/test_migration.py`; `migrated_engine`,
  `KEY` and `RUN` already exist there; `test_migration_columns_match_models` will also fail until the model and
  migration agree)

```python
def test_trigger_check(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "c" * 64})
        conn.execute(text(RUN), {"idem": "t1", "provider": "github_actions"})
        conn.execute(text("UPDATE test_runs SET \"trigger\" = 'manual' WHERE idempotency_key = 't1'"))
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text("UPDATE test_runs SET \"trigger\" = 'cron' WHERE idempotency_key = 't1'"))


def test_collection_settings_defaults(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text("INSERT INTO collection_settings (project_id) VALUES (5)"))
        row = conn.execute(text(
            "SELECT collect_manual, discarded_count, last_discarded_at FROM collection_settings WHERE project_id = 5"
        )).one()
    assert (bool(row[0]), row[1], row[2]) == (True, 0, None)
```

- [ ] **Step 2: Run to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py -q`
Expected: FAIL (`no such column: trigger`, `no such table: collection_settings`).

- [ ] **Step 3: Model**

`src/ingestion/models/collection_settings.py`:

```python
from sqlalchemy import Boolean, Column, DateTime, Integer, true, text

from src.ingestion.db.base import Base


class CollectionSettings(Base):
    """What a project collects (migration 019). No row: the defaults (collect everything)."""

    __tablename__ = "collection_settings"

    project_id = Column(Integer, primary_key=True, autoincrement=False)
    collect_manual = Column(Boolean, nullable=False, default=True, server_default=true())
    # Uploads, not runs: a matrix run uploads once per job
    discarded_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_discarded_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    updated_by = Column(Integer, nullable=True)
```

In `models/run.py`, after `STATUSES`:

```python
TRIGGERS = ("manual", "automatic", "qeos")
```

In `Run`, after `base_branch`:

```python
    # How the CI run started, as the collector classified it (ADR-030); null: unknown or an older collector
    trigger = Column(String(10), nullable=True)
```

and in `Run.__table_args__` after the `ci_provider` check:

```python
        CheckConstraint("\"trigger\" IN ('manual','automatic','qeos')", name="chk_test_runs_trigger"),
```

`models/__init__.py`: import `CollectionSettings` and add it to `__all__` (alphabetical, after `ApiKey`).

- [ ] **Step 4: Migration** `alembic/versions/019_collection_settings.py`

```python
"""collection_settings and test_runs.trigger: collect manual CI runs or not (ADR-030)

A project can discard uploads from CI runs a person started by hand. No row: the defaults (collect
everything), so existing projects need no backfill. test_runs.trigger records how a stored run started.

Revision ID: 019
Revises: 018
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_settings",
        sa.Column("project_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("collect_manual", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("discarded_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("test_runs") as batch:
        batch.add_column(sa.Column("trigger", sa.String(length=10), nullable=True))
        batch.create_check_constraint("chk_test_runs_trigger", "\"trigger\" IN ('manual','automatic','qeos')")


def downgrade() -> None:
    with op.batch_alter_table("test_runs") as batch:
        batch.drop_constraint("chk_test_runs_trigger", type_="check")
        batch.drop_column("trigger")
    op.drop_table("collection_settings")
```

- [ ] **Step 5: Run the migration tests and the whole suite**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py -q`, then `... -m pytest -q`
Expected: PASS. Then on PostgreSQL: `docker compose run --rm ingestion-migrate` against the local stack succeeds.

- [ ] **Step 6: Commit** — `feat(ingestion): collection_settings table and test_runs.trigger (migration 019)`

### Task 2: Settings API

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/schemas/collection_settings.py`
- Create: `platforms/ingestion-service/src/ingestion/service/collection_settings_service.py`
- Create: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collection_settings.py`
- Modify: `platforms/ingestion-service/src/ingestion/api/deps.py` (`MANAGE_ROLES`, `__all__`)
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/api.py` (register the router)
- Test: `platforms/ingestion-service/tests/integration/test_collection_settings.py`

**Interfaces:**
- Consumes: `CollectionSettings` (Task 1).
- Produces: `collection_settings_service.get(db, project_id) -> CollectionSettings` (unsaved defaults when no row),
  `collection_settings_service.put(db, project_id, collect_manual: bool, user_id: int) -> CollectionSettings`,
  `collection_settings_service.collects_manual(db, project_id) -> bool`,
  `collection_settings_service.count_discard(db, project_id) -> None`. `MANAGE_ROLES` in `deps`.
  Route prefix `/projects/{project_id}/collection-settings`.

- [ ] **Step 1: Failing tests** `tests/integration/test_collection_settings.py`

```python
"""Per-project collection settings (ADR-030): readable by members, changed by owners and admins."""
URL = "/api/v1/projects/1/collection-settings"


def test_defaults_without_a_row(client, auth, project_role):
    project_role(role="viewer", project_id=1)
    body = client.get(URL, headers=auth()).json()
    assert body == {"collect_manual": True, "discarded_count": 0, "last_discarded_at": None,
                    "updated_at": None, "updated_by": None}


def test_an_admin_switches_manual_collection_off(client, auth, project_role):
    project_role(role="admin", project_id=1)
    response = client.put(URL, json={"collect_manual": False}, headers=auth(user_id=7))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["collect_manual"] is False and body["updated_by"] == 7 and body["updated_at"] is not None
    assert client.get(URL, headers=auth()).json()["collect_manual"] is False


def test_put_is_an_upsert(client, auth, project_role):
    project_role(role="owner", project_id=1)
    client.put(URL, json={"collect_manual": False}, headers=auth())
    assert client.put(URL, json={"collect_manual": True}, headers=auth()).json()["collect_manual"] is True


def test_a_member_cannot_change_it(client, auth, project_role):
    project_role(role="member", project_id=1)
    assert client.get(URL, headers=auth()).status_code == 200
    assert client.put(URL, json={"collect_manual": False}, headers=auth()).status_code == 403


def test_a_non_member_gets_404(client, auth, project_role):
    project_role(status_code=404, project_id=1)
    assert client.get(URL, headers=auth()).status_code == 404


def test_the_body_must_be_a_boolean(client, auth, project_role):
    project_role(role="owner", project_id=1)
    assert client.put(URL, json={"collect_manual": "no"}, headers=auth()).status_code == 422
    assert client.put(URL, json={}, headers=auth()).status_code == 422
```

(`project_role(status_code=404)` makes the stubbed project-service answer 404, which `check_project_role`
turns into "Project not found" 404 — the same path `test_deps.py` exercises.)

- [ ] **Step 2: Run** `SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_collection_settings.py -q` — FAIL (404 on every call).

- [ ] **Step 3: Schemas** `schemas/collection_settings.py`

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, StrictBool


class CollectionSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collect_manual: StrictBool


class CollectionSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collect_manual: bool
    discarded_count: int
    last_discarded_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None
```

- [ ] **Step 4: Service** `service/collection_settings_service.py`

```python
"""A project's collection settings (ADR-030). No row: the defaults."""
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.ingestion.models import CollectionSettings


def get(db: Session, project_id: int) -> CollectionSettings:
    row = db.get(CollectionSettings, project_id)
    if row is None:  # not added to the session: reading never writes
        row = CollectionSettings(project_id=project_id, collect_manual=True, discarded_count=0)
    return row


def put(db: Session, project_id: int, collect_manual: bool, user_id: int) -> CollectionSettings:
    row = db.get(CollectionSettings, project_id)
    if row is None:
        row = CollectionSettings(project_id=project_id, discarded_count=0)
        db.add(row)
    row.collect_manual = collect_manual
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = user_id
    db.commit()
    db.refresh(row)
    return row


def collects_manual(db: Session, project_id: int) -> bool:
    row = db.get(CollectionSettings, project_id)
    return True if row is None else bool(row.collect_manual)


def count_discard(db: Session, project_id: int) -> None:
    """One atomic UPDATE: parallel matrix uploads must not lose increments. A row exists whenever
    collection is off, because only put() can switch it off."""
    db.execute(
        update(CollectionSettings)
        .where(CollectionSettings.project_id == project_id)
        .values(discarded_count=CollectionSettings.discarded_count + 1,
                last_discarded_at=datetime.now(timezone.utc))
    )
    db.commit()
```

- [ ] **Step 5: Roles** in `api/deps.py`, after `EDIT_ROLES`:

```python
MANAGE_ROLES = ("owner", "admin")
```

and add `"MANAGE_ROLES"` to `__all__`.

- [ ] **Step 6: Endpoints** `api/v1/endpoints/collection_settings.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.ingestion.api.deps import MANAGE_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.ingestion.schemas.collection_settings import CollectionSettingsIn, CollectionSettingsOut
from src.ingestion.service import collection_settings_service

router = APIRouter()  # mounted at /projects/{project_id}/collection-settings


@router.get("", response_model=CollectionSettingsOut)
def get_collection_settings(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return collection_settings_service.get(db, access.project_id)


@router.put("", response_model=CollectionSettingsOut)
def put_collection_settings(
    payload: CollectionSettingsIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    return collection_settings_service.put(db, access.project_id, payload.collect_manual, access.user_id)
```

`api/v1/api.py`: add `collection_settings` to the endpoints import and

```python
api_router.include_router(
    collection_settings.router, prefix="/projects/{project_id}/collection-settings", tags=["collection"]
)
```

(re-read `api.py` first: other work may have added routers since this plan was written.)

- [ ] **Step 7: Run the new tests, then the whole suite** — PASS.

- [ ] **Step 8: Commit** — `feat(ingestion): collection settings API (GET for members, PUT for owners and admins)`

### Task 3: The upload rule

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/schemas/collect.py` (`RunIn.trigger`, `RunReceipt.trigger`)
- Modify: `platforms/ingestion-service/src/ingestion/schemas/run.py` (`RunOut.trigger`)
- Modify: `platforms/ingestion-service/src/ingestion/service/ingest_service.py`
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py`
- Modify: `platforms/ingestion-service/src/ingestion/utils/metrics.py`
- Test: `platforms/ingestion-service/tests/integration/test_collect_trigger.py`, `tests/unit/test_collect_schema.py`

**Interfaces:**
- Consumes: `collection_settings_service.collects_manual`, `count_discard` (Task 2); `Run.trigger` (Task 1).
- Produces: `ingest_service.Discarded` exception (attribute `reason: str`); `ingest_service.DISCARD_REASON =
  "manual runs are not collected for this project"`; metric `qeos_runs_discarded_total{reason}`.

- [ ] **Step 1: Failing schema test** (append to `tests/unit/test_collect_schema.py`, which already has
  `body(run=None, results=None)` and imports `RunUpload`, `ValidationError`, `pytest`)

```python
@pytest.mark.parametrize("trigger", ["manual", "automatic", "qeos", None])
def test_trigger_values(trigger):
    run = {} if trigger is None else {"trigger": trigger}
    assert RunUpload.model_validate(body(run=run)).run.trigger == trigger


def test_an_unknown_trigger_is_rejected():
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(run={"trigger": "cron"}))
```

- [ ] **Step 2: Failing integration tests** `tests/integration/test_collect_trigger.py`

```python
"""Manual runs are discarded while the project does not collect them (ADR-030)."""
import threading

from sqlalchemy.orm import sessionmaker

from src.ingestion.models import CollectionSettings, Run
from src.ingestion.utils import metrics
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

REASON = "manual runs are not collected for this project"


def switch_off(db, project_id=1):
    db.add(CollectionSettings(project_id=project_id, collect_manual=False, discarded_count=0))
    db.commit()


def discarded():
    return metrics.REGISTRY.get_sample_value("qeos_runs_discarded_total", {"reason": "manual"}) or 0.0


def test_off_and_manual_is_discarded(client, make_key, db):
    _, key = make_key(project_id=1)
    switch_off(db)
    before = discarded()
    response = client.post(URL, json=upload_body(trigger="manual"), headers=key_headers(key))
    assert response.status_code == 202
    assert response.json() == {"discarded": True, "reason": REASON}
    assert db.query(Run).count() == 0
    row = db.get(CollectionSettings, 1)
    db.refresh(row)
    assert row.discarded_count == 1 and row.last_discarded_at is not None
    assert discarded() == before + 1


def test_off_keeps_everything_else(client, make_key, db):
    _, key = make_key(project_id=1)
    switch_off(db)
    for trigger in ("automatic", "qeos", None):
        body = upload_body(trigger=trigger) if trigger else upload_body()
        assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    assert sorted(str(r.trigger) for r in db.query(Run)) == ["None", "automatic", "qeos"]


def test_on_stores_manual_with_its_trigger(client, make_key, db, auth, project_role):
    _, key = make_key(project_id=1)
    response = client.post(URL, json=upload_body(trigger="manual"), headers=key_headers(key))
    assert response.status_code == 201 and response.json()["trigger"] == "manual"
    project_role("viewer")
    detail = client.get(f"/api/v1/runs/{response.json()['id']}", headers=auth())
    assert detail.status_code == 200 and detail.json()["trigger"] == "manual"


def test_replay_of_a_discarded_upload_is_discarded_again(client, make_key, db):
    _, key = make_key(project_id=1)
    switch_off(db)
    for _ in range(2):
        assert client.post(URL, json=upload_body(trigger="manual"), headers=key_headers(key, idem="k-1")).status_code == 202
    assert db.get(CollectionSettings, 1).discarded_count == 2


def test_replay_of_a_stored_run_is_not_discarded_later(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(trigger="manual")
    first = client.post(URL, json=body, headers=key_headers(key, idem="k-2"))
    assert first.status_code == 201
    switch_off(db)
    again = client.post(URL, json=body, headers=key_headers(key, idem="k-2"))
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]


def test_concurrent_discards_are_all_counted(client, make_key, db):
    _, key = make_key(project_id=1)
    switch_off(db)
    threads = [threading.Thread(target=lambda: client.post(URL, json=upload_body(trigger="manual"),
                                                             headers=key_headers(key))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fresh = sessionmaker(bind=db.get_bind())()
    assert fresh.get(CollectionSettings, 1).discarded_count == 8
```

- [ ] **Step 3: Run** — FAIL (schema forbids `trigger`; no 202).

- [ ] **Step 4: Schema** `schemas/collect.py`: in `RunIn`, after `base_branch`:

```python
    # How the CI run started, as the collector classified it (ADR-030); absent: unknown, collected
    trigger: Optional[Literal["manual", "automatic", "qeos"]] = None
```

In `RunReceipt`, add `trigger: Optional[str] = None`. In `schemas/run.py` `RunOut`, add
`trigger: Optional[str] = None` after `base_branch`.

- [ ] **Step 5: Metric** `utils/metrics.py`, after `REJECTED`:

```python
DISCARDED = Counter("qeos_runs_discarded", "Uploads accepted and not stored, by reason", ["reason"], registry=REGISTRY)
DISCARDED.labels(reason="manual")
```

- [ ] **Step 6: Rule** in `service/ingest_service.py`:

```python
DISCARD_REASON = "manual runs are not collected for this project"


class Discarded(Exception):
    """The upload is valid and deliberately not stored (ADR-030)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
```

In `ingest()`, keep the idempotency lookup first (a run stored earlier is replayed whatever the toggle says now),
then before `counts = Counter(...)`:

```python
    if upload.run.trigger == "manual" and not collection_settings_service.collects_manual(db, key.project_id):
        collection_settings_service.count_discard(db, key.project_id)
        raise Discarded(DISCARD_REASON)
```

and pass `trigger=meta.trigger` in the `Run(...)` constructor. Import `collection_settings_service`.

- [ ] **Step 7: Endpoint** `collect.py`: `from fastapi.responses import JSONResponse`; `import logging`;
`logger = logging.getLogger(__name__)`. Inside `with metrics.DURATION.time():`, add before the
`IdempotencyConflict` handler:

```python
        except ingest_service.Discarded as exc:
            metrics.DISCARDED.labels(reason="manual").inc()
            logger.info("upload discarded", extra={"project_id": key.project_id, "api_key_id": key.id,
                                                   "ci_run_url": upload.run.ci_run_url, "reason": exc.reason})
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED,
                                content={"discarded": True, "reason": exc.reason})
```

Add `responses={202: {"description": "Accepted and not stored (manual run, ADR-030)"}}` to the decorator so the
OpenAPI document lists it.

- [ ] **Step 8: Run the new tests, then the whole ingestion suite** — PASS. If SQLite serialises the threaded
  test's commits with `database is locked`, give the test engine `connect_args={"timeout": 15}` only in that test
  (via a local engine), never in shared fixtures.

- [ ] **Step 9: Commit** — `feat(ingestion): discard manual runs while a project does not collect them`

### Task 4: Gateway route

**Files:**
- Modify: `gateway/nginx.conf.template` (ingestion's project regex)
- Modify: `gateway/README.md` (Routes table)
- Modify: `scripts/smoke_gateway.sh`

- [ ] **Step 1: See the check fail**

Run: `python scripts/check_architecture_docs.py`
Expected: FAIL with `gateway: /api/v1/projects/1/collection-settings (ingestion-service's /projects/{id}/collection-settings) goes to project-service`
and the matching Routes-table line.

- [ ] **Step 2: Route.** In `gateway/nginx.conf.template`, change
  `(api-keys|runs|analytics|masking-patterns|export|notification-channels)` to
  `(api-keys|runs|analytics|masking-patterns|export|notification-channels|collection-settings)`.
  In `gateway/README.md`, append `` `…/collection-settings` `` to the ingestion row's path cell.

- [ ] **Step 3: Smoke.** In `scripts/smoke_gateway.sh`, next to the masking-patterns check, add:

```bash
check "collection settings -> ingestion-service" 200 GET "$BASE/api/v1/projects/$PROJECT_ID/collection-settings" "${AUTH[@]}"
```

- [ ] **Step 4: Verify** — `python scripts/check_architecture_docs.py` passes; NGINX config test as in CI's gateway
  job; `docker compose up -d --build --wait gateway` then `bash scripts/smoke_gateway.sh` passes.

- [ ] **Step 5: Commit** — `feat(gateway): route collection-settings to ingestion-service`

### Task 5: Server docs, then push delivery 1

**Files:**
- Create: `docs/architecture/adr/ADR-030-collect-manual-runs.md` (from `TEMPLATE.md`)
- Modify: `docs/architecture/adr/INDEX.md`, `platforms/ingestion-service/README.md`, `TECHNICAL_SPECIFICATION.md`,
  `SECURITY.md`, `TODO.md`

- [ ] **Step 1: ADR-030** — Context (manual runs pollute analytics; GitHub calls bot dispatches manual too),
  Decision (spec §1 bullets, §3 table, ownership by ingestion, 202 discard), Consequences (old collectors still
  collected; trigger is client-reported, not access control; counts uploads not runs). Status: Accepted. Add the
  INDEX row in the existing format.
- [ ] **Step 2: ingestion README** — the `collection-settings` endpoints, the 202 answer, the `trigger` field,
  `qeos_runs_discarded_total`.
- [ ] **Step 3: TECHNICAL_SPECIFICATION** — `run.trigger` in the payload table; the endpoint in the ingestion API
  list; the 202 response.
- [ ] **Step 4: SECURITY** — one paragraph: the toggle is a noise filter; whoever holds the API key can label a
  run; API keys remain the boundary.
- [ ] **Step 5: TODO** — an item under the collector/ingestion section: server part done (date), collector and
  dashboard pending.
- [ ] **Step 6: Full CI locally** (every service suite, `python scripts/check_architecture_docs.py`,
  `bash monitoring/check.sh` unaffected), then commit `docs: collect manual runs (ADR-030), server side` and push.
  Watch CI on master until green.

## Delivery 2 — collector 0.5.0

### Task 6: Trigger classification

**Files:**
- Modify: `collector/src/qeos_collector/ci.py`
- Test: `collector/tests/test_ci.py`

**Interfaces:**
- Produces: `CIInfo.trigger: Optional[str]` (`"manual" | "automatic" | "qeos" | None`), set by `detect(env)`;
  module-level `detect_trigger(env: Mapping[str, str], read_event=_read_event) -> Optional[str]` (testable without
  files); `_read_event(path: str) -> dict` returns `{}` on any error.

- [ ] **Step 1: Failing tests** (append to `collector/tests/test_ci.py`)

```python
import json

import pytest

from qeos_collector.ci import detect, detect_trigger

GH = {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "1", "GITHUB_REPOSITORY": "acme/obt",
      "GITHUB_SERVER_URL": "https://github.com"}


def gh(**extra):
    return {**GH, **extra}


@pytest.mark.parametrize("env, event, expected", [
    (gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="octocat"), {}, "manual"),
    (gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="github-actions[bot]"), {}, "automatic"),
    (gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="octocat"),
     {"inputs": {"request_id": "42"}}, "qeos"),
    (gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_ACTOR="octocat"), {}, "manual"),  # no TRIGGERING_ACTOR
    (gh(GITHUB_EVENT_NAME="schedule", GITHUB_RUN_ATTEMPT="2", GITHUB_TRIGGERING_ACTOR="octocat"), {}, "manual"),
    (gh(GITHUB_EVENT_NAME="schedule", GITHUB_RUN_ATTEMPT="2", GITHUB_TRIGGERING_ACTOR="renovate[bot]"), {}, "automatic"),
    (gh(GITHUB_EVENT_NAME="push", GITHUB_RUN_ATTEMPT="1", GITHUB_TRIGGERING_ACTOR="octocat"), {}, "automatic"),
    (gh(GITHUB_EVENT_NAME="schedule"), {}, "automatic"),
    (gh(GITHUB_EVENT_NAME="repository_dispatch", GITHUB_TRIGGERING_ACTOR="octocat"), {}, "automatic"),
    (gh(), {}, None),  # no event name: unknown
    ({"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "web"}, {}, "manual"),
    ({"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "push", "CI_JOB_MANUAL": "true"}, {}, "manual"),
    ({"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "schedule"}, {}, "automatic"),
    ({"GITLAB_CI": "true"}, {}, None),
    ({"TF_BUILD": "True", "BUILD_REASON": "Manual"}, {}, "manual"),
    ({"TF_BUILD": "True", "BUILD_REASON": "IndividualCI"}, {}, "automatic"),
    ({"JENKINS_URL": "https://ci.example", "BUILD_CAUSE": "MANUALTRIGGER"}, {}, "manual"),
    ({"JENKINS_URL": "https://ci.example", "BUILD_CAUSE": "USERIDCAUSE"}, {}, "manual"),
    ({"JENKINS_URL": "https://ci.example", "BUILD_CAUSE": "TIMERTRIGGER"}, {}, "automatic"),
    ({"JENKINS_URL": "https://ci.example"}, {}, None),
    ({}, {}, None),
])
def test_trigger_classification(env, event, expected):
    assert detect_trigger(env, read_event=lambda _path: event) == expected


def test_detect_fills_trigger(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"request_id": "7"}}), encoding="utf-8")
    env = gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="octocat", GITHUB_EVENT_PATH=str(event))
    assert detect(env).trigger == "qeos"


@pytest.mark.parametrize("content", [None, "not json", "[1, 2]", '{"inputs": "x"}'])
def test_unreadable_event_payload_is_not_qeos(tmp_path, content):
    env = gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="octocat")
    if content is not None:
        (tmp_path / "e.json").write_text(content, encoding="utf-8")
        env["GITHUB_EVENT_PATH"] = str(tmp_path / "e.json")
    else:
        env["GITHUB_EVENT_PATH"] = str(tmp_path / "missing.json")
    assert detect(env).trigger == "manual"
```

- [ ] **Step 2: Run** `cd collector && python -m pytest tests/test_ci.py -q` — FAIL (`detect_trigger` missing).

- [ ] **Step 3: Implement** in `ci.py`: add `import json`; add `trigger: Optional[str] = None` to `CIInfo`; then

```python
def _read_event(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _person(actor: Optional[str]) -> bool:
    return bool(actor) and not actor.endswith("[bot]")


def detect_trigger(env: Mapping[str, str], read_event: Callable[[str], dict] = _read_event) -> Optional[str]:
    """manual, automatic or qeos (ADR-030); None when the environment does not say."""
    def get(name: str) -> Optional[str]:
        return env.get(name, "").strip() or None

    if get("GITHUB_ACTIONS") == "true":
        event = get("GITHUB_EVENT_NAME")
        if event is None:
            return None
        actor = get("GITHUB_TRIGGERING_ACTOR") or get("GITHUB_ACTOR")
        if event == "workflow_dispatch":
            payload = read_event(get("GITHUB_EVENT_PATH")) if get("GITHUB_EVENT_PATH") else {}
            inputs = payload.get("inputs")
            if isinstance(inputs, dict) and inputs.get("request_id"):
                return "qeos"
            return "manual" if _person(actor) else "automatic"
        attempt = _int_or_none(get("GITHUB_RUN_ATTEMPT")) or 1
        return "manual" if attempt > 1 and _person(actor) else "automatic"
    if get("GITLAB_CI") == "true":
        source = get("CI_PIPELINE_SOURCE")
        if source == "web" or get("CI_JOB_MANUAL") == "true":
            return "manual"
        return "automatic" if source else None
    if (get("TF_BUILD") or "").lower() == "true":
        reason = get("BUILD_REASON")
        return None if reason is None else ("manual" if reason == "Manual" else "automatic")
    if get("JENKINS_URL"):
        cause = (get("BUILD_CAUSE") or "").upper()
        if not cause:
            return None
        return "manual" if "MANUALTRIGGER" in cause or "USERIDCAUSE" in cause else "automatic"
    return None
```

Import `Callable` from `typing`. In `detect()`, set `trigger=detect_trigger(env)` in each provider's `CIInfo(...)`
(GitHub, GitLab, Azure, Jenkins); other providers leave it `None`. Keep 3.9-compatible syntax (`Optional`, no `|`).

- [ ] **Step 4: Run the collector suite** — PASS.
- [ ] **Step 5: Commit** — `feat(collector): classify each run's trigger (manual, automatic, qeos)`

### Task 7: Send the trigger, `--trigger`, handle the 202

**Files:**
- Modify: `collector/src/qeos_collector/payload.py` (`build_run(trigger=...)`)
- Modify: `collector/src/qeos_collector/upload.py` (accept 202)
- Modify: `collector/src/qeos_collector/cli.py` (`--trigger`, `QEOS_TRIGGER`, stop on discard)
- Modify: `collector/src/qeos_collector/__init__.py` (`__version__ = "0.5.0"`)
- Test: `collector/tests/test_payload.py`, `collector/tests/test_upload.py`, `collector/tests/test_cli.py`

**Interfaces:**
- Consumes: `CIInfo.trigger` (Task 6).
- Produces: `build_run(..., trigger: Optional[str] = None)` adds `run["trigger"]` only for the three values;
  `upload_part` returns `(202, body)` for a 202; `TRIGGERS = ("manual", "automatic", "qeos")` in `payload.py`.

- [ ] **Step 1: Failing tests.** Read `tests/test_cli.py` first and reuse its fake-server/`upload_part` stubbing
  helper (the file already drives `main([...])` against a stub); the names below assume a helper that records
  posted bodies and lets a test choose each response — adapt to the real one.

`tests/test_payload.py`:

```python
@pytest.mark.parametrize("trigger, sent", [("manual", "manual"), ("qeos", "qeos"), (None, None), ("cron", None)])
def test_trigger_is_sent_only_when_known(trigger, sent):
    now = datetime.now(timezone.utc)
    run = build_run(ci_provider="github_actions", started_at=now, finished_at=now, trigger=trigger)
    assert run.get("trigger") == sent
```

`tests/test_upload.py`:

```python
def test_a_202_is_returned_not_raised(monkeypatch):
    monkeypatch.setattr(upload, "_send", lambda *a, **k: (202, b'{"discarded": true, "reason": "r"}', {}))
    status, body = upload.upload_part("https://q.example/api/v1/collect/runs", "k", PART)
    assert (status, body["discarded"]) == (202, True)
```

(`PART` = the `Part` fixture the file already uses; reuse it.)

`tests/test_cli.py`:

```python
NOTICE = "qeos: run not collected: manual runs are not collected for this project"


def test_a_discarded_run_prints_the_notice_and_exits_zero(stub_server, capsys):
    stub_server.respond(202, {"discarded": True, "reason": "manual runs are not collected for this project"})
    assert main(["upload", JUNIT_FIXTURE]) == 0
    assert NOTICE in capsys.readouterr().err


def test_a_discarded_first_part_stops_the_upload(stub_server, many_results_fixture):
    stub_server.respond(202, {"discarded": True, "reason": "manual runs are not collected for this project"})
    assert main(["upload", many_results_fixture]) == 0
    assert len(stub_server.bodies) == 1


def test_gate_on_a_discarded_run_exits_zero(stub_server):
    stub_server.respond(202, {"discarded": True, "reason": "manual runs are not collected for this project"})
    assert main(["upload", "--gate", "--fail-on-error", FAILING_JUNIT_FIXTURE]) == 0


def test_trigger_flag_overrides_detection(stub_server, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_TRIGGERING_ACTOR", "octocat")
    main(["upload", "--trigger", "automatic", JUNIT_FIXTURE])
    assert stub_server.bodies[0]["run"]["trigger"] == "automatic"


def test_an_invalid_trigger_is_a_config_error(capsys):
    assert main(["upload", "--trigger", "cron", JUNIT_FIXTURE]) == 2
```

(`many_results_fixture` writes a JUnit file with `MAX_RESULTS_PER_PART + 1` cases so `build_parts` makes two parts;
use the part-size constant `payload.py` defines.)

- [ ] **Step 2: Run** `python -m pytest -q` — the new tests FAIL.

- [ ] **Step 3: payload.py** — `TRIGGERS = ("manual", "automatic", "qeos")`; `build_run(..., trigger:
  Optional[str] = None)`; at the end, `if trigger in TRIGGERS: run["trigger"] = trigger`.

- [ ] **Step 4: upload.py** — in `upload_part`, change `if status in (200, 201):` to
  `if status in (200, 201, 202):`.

- [ ] **Step 5: cli.py** —
  - `upload.add_argument("--trigger", help="manual, automatic or qeos (default: $QEOS_TRIGGER, else detected; ADR-030)")`
  - in `_upload`, after `provider` is resolved:

```python
    trigger = pick(args.trigger, "QEOS_TRIGGER", ci.trigger)
    if trigger is not None and trigger not in TRIGGERS:
        raise ConfigError(f"--trigger must be one of {', '.join(TRIGGERS)}, got {trigger!r}")
```

  - pass `trigger=trigger` to `build_run(...)`;
  - in the upload loop, right after `status, receipt = upload_part(...)`:

```python
        if status == 202 and receipt.get("discarded"):
            say(f"run not collected: {receipt.get('reason', 'the platform discarded it')}")
            return 0  # every part shares the trigger: the rest would be discarded too
```

  (`say` already prefixes `qeos: `; confirm by reading `_Output` and adjust so the printed line equals `NOTICE`.)
  - import `TRIGGERS` from `.payload`.

- [ ] **Step 6: Version** — `__version__ = "0.5.0"` in `__init__.py`; `tests/test_package.py` may assert the version
  — update it there.

- [ ] **Step 7: Run the collector suite on 3.9 and 3.12 as CI does** (`python -m pytest -q`; if only one Python is
  installed, run that one and say so) — PASS.

- [ ] **Step 8: Commit** — `feat(collector): send the trigger, --trigger, and stop on a discarded run (0.5.0)`

### Task 8: Collector docs and release

**Files:**
- Modify: `collector/README.md`; `docs/SETUP.md`; `README.md`; `templates/github/qeos-run.yml`;
  `templates/qeos-collector.gitlab-ci.yml`; `templates/qeos-collector.azure-pipelines.yml`;
  `collector-jenkins/vars/qeosCollectorUpload.groovy`; `dashboard/src/pages/ProjectSettingsPage.tsx` and its test
  (`COLLECTOR_REF`); `TODO.md`

- [ ] **Step 1: collector README** — `--trigger` / `QEOS_TRIGGER`, the classification table (spec §3), the 202
  notice and exit 0, the container-image variables (spec §3 "Two cases").
- [ ] **Step 2: Move refs** — replace every `collector-v0.4.1` with `collector-v0.5.0` in the files above (run
  `git grep -n "collector-v0.4.1" -- ':!docs/superpowers'` before and after; the second must print nothing).
- [ ] **Step 3: Full CI locally** (collector, dashboard lint/typecheck/test/build because `COLLECTOR_REF` changed,
  architecture check), commit `release: qeos-collector 0.5.0` and push; wait for CI green.
- [ ] **Step 4: Tag** — `git tag collector-v0.5.0 && git push origin collector-v0.5.0`; watch
  `release-collector.yml` until green (a Docker Hub 429 is transient: rerun the failed job once).

## Delivery 3 — dashboard

### Task 9: Collection card

**Files:**
- Create: `dashboard/src/api/collection.ts`
- Create: `dashboard/src/components/CollectionCard.tsx`
- Test: `dashboard/src/components/CollectionCard.test.tsx`
- Modify: `dashboard/src/pages/ProjectSettingsPage.tsx` (render it before `CiTargetCard`)

**Interfaces:**
- Consumes: `GET/PUT /api/v1/projects/{id}/collection-settings` (Task 2), `ago(iso)` from
  `dashboard/src/overview/format.ts`.
- Produces: `CollectionCard({ projectId: number; canManage: boolean | undefined })`.

- [ ] **Step 1: ui-ux-pro-max** — invoke the skill for the card: a labelled switch (`role="switch"`, visible label,
  `aria-checked`, keyboard), help text, read-only state with its reason, saving and error states. Keep the
  existing `.card` styles; no new colours.

- [ ] **Step 2: Failing tests** `CollectionCard.test.tsx` (same harness as `MaskingCard.test.tsx`):

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CollectionCard from "./CollectionCard";

const URL = "/api/v1/projects/42/collection-settings";
const DEFAULTS = { collect_manual: true, discarded_count: 0, last_discarded_at: null, updated_at: null, updated_by: null };

function renderCard(canManage: boolean | undefined = true) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><CollectionCard projectId={42} canManage={canManage} /></QueryClientProvider>);
}

test("shows the switch on by default and explains what manual means", async () => {
  server.use(http.get(URL, () => HttpResponse.json(DEFAULTS)));
  renderCard();
  const toggle = await screen.findByRole("switch", { name: /collect runs started manually in ci/i });
  expect(toggle).toHaveAttribute("aria-checked", "true");
  expect(screen.getByText(/runs started from qeos are always collected/i)).toBeInTheDocument();
  expect(screen.getByText(/0\.5\.0/)).toBeInTheDocument();
});

test("an admin switches it off and the change is saved", async () => {
  let sent: unknown = null;
  server.use(
    http.get(URL, () => HttpResponse.json(DEFAULTS)),
    http.put(URL, async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ ...DEFAULTS, collect_manual: false, updated_by: 1, updated_at: "2026-10-12T10:00:00Z" });
    }),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("switch"));
  expect(sent).toEqual({ collect_manual: false });
  expect(await screen.findByRole("switch")).toHaveAttribute("aria-checked", "false");
});

test("members see it read-only, with the reason", async () => {
  server.use(http.get(URL, () => HttpResponse.json(DEFAULTS)));
  renderCard(false);
  expect(await screen.findByRole("switch")).toBeDisabled();
  expect(screen.getByText(/only owners and admins/i)).toBeInTheDocument();
});

test("says how many manual uploads were not collected", async () => {
  server.use(http.get(URL, () => HttpResponse.json({
    ...DEFAULTS, collect_manual: false, discarded_count: 3, last_discarded_at: new Date(Date.now() - 2 * 3600e3).toISOString(),
  })));
  renderCard();
  expect(await screen.findByText(/3 manual uploads not collected/i)).toBeInTheDocument();
});

test("a failed save shows the error and keeps the old state", async () => {
  server.use(
    http.get(URL, () => HttpResponse.json(DEFAULTS)),
    http.put(URL, () => HttpResponse.json({ detail: "Insufficient role" }, { status: 403 })),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("switch"));
  expect(await screen.findByText(/insufficient role/i)).toBeInTheDocument();
  expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
});
```

- [ ] **Step 3: Run** `cd dashboard && npx vitest run src/components/CollectionCard.test.tsx` — FAIL (module missing).

- [ ] **Step 4: API** `src/api/collection.ts`

```ts
import { apiFetch } from "./http";

// Mirrors platforms/ingestion-service/src/ingestion/schemas/collection_settings.py

export interface CollectionSettings {
  collect_manual: boolean;
  discarded_count: number;
  last_discarded_at: string | null;
  updated_at: string | null;
  updated_by: number | null;
}

const base = (projectId: number) => `/api/v1/projects/${projectId}/collection-settings`;

export function getCollectionSettings(projectId: number): Promise<CollectionSettings> {
  return apiFetch(base(projectId));
}

export function putCollectionSettings(projectId: number, collectManual: boolean): Promise<CollectionSettings> {
  return apiFetch(base(projectId), { method: "PUT", body: JSON.stringify({ collect_manual: collectManual }) });
}
```

- [ ] **Step 5: Component** `src/components/CollectionCard.tsx`

```tsx
import { useId } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getCollectionSettings, putCollectionSettings } from "../api/collection";
import { ago } from "../overview/format";
import ErrorBanner from "./ErrorBanner";

interface Props {
  projectId: number;
  /** Undefined while the role is loading: the state shows, the switch waits. */
  canManage: boolean | undefined;
}

export default function CollectionCard({ projectId, canManage }: Props) {
  const qc = useQueryClient();
  const queryKey = ["collection-settings", projectId];
  const hint = useId();
  const settings = useQuery({ queryKey, queryFn: () => getCollectionSettings(projectId) });
  const save = useMutation({
    mutationFn: (collectManual: boolean) => putCollectionSettings(projectId, collectManual),
    onSuccess: (data) => qc.setQueryData(queryKey, data),
  });
  const on = settings.data?.collect_manual ?? true;

  return (
    <div className="card">
      <h2>Collection</h2>
      <div className="toggle-row">
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-describedby={hint}
          disabled={canManage !== true || settings.isLoading || save.isPending}
          onClick={() => save.mutate(!on)}
        >
          Collect runs started manually in CI
        </button>
      </div>
      <p id={hint} className="muted">
        Manual means a person started the run: “Run workflow” or a re-run on GitHub, a pipeline run from
        GitLab’s web page or a manual job, a manual Azure build. Runs started from QEOS are always collected.
        Needs qeos-collector 0.5.0 or later; older collectors are always collected.
        {canManage === false && " Only owners and admins can change this."}
      </p>
      {settings.data != null && settings.data.discarded_count > 0 && (
        <p className="muted">
          {settings.data.discarded_count} manual uploads not collected
          {settings.data.last_discarded_at != null && `, last ${ago(settings.data.last_discarded_at)}`}.
        </p>
      )}
      {settings.error != null && <ErrorBanner error={settings.error} />}
      {save.error != null && <ErrorBanner error={save.error} />}
    </div>
  );
}
```

Adjust markup and classes to what ui-ux-pro-max settled in Step 1 (a visual switch track styled in `index.css`
under a `.switch` rule using existing tokens); the tests drive roles and text only. Check `ErrorBanner`'s prop name
before using it.

- [ ] **Step 6: Page** — in `ProjectSettingsPage.tsx`, before the `CiTargetCard` line:

```tsx
      <CollectionCard
        projectId={id}
        canManage={project.data == null ? undefined : MANAGE_ROLES.includes(project.data.my_role ?? "")}
      />
```

and the import. Update `ProjectSettingsPage.test.tsx` if it asserts card order or headings.

- [ ] **Step 7: Run** `npm run lint && npm run typecheck && npx vitest run && npm run build` — PASS.
- [ ] **Step 8: Commit** — `feat(dashboard): Collection card in Project Settings (collect manual CI runs)`

### Task 10: Remaining docs, push, rebuild

**Files:**
- Modify: `docs/SETUP.md`, `PRODUCT.md`, `TODO.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md` (only if a banner row changes),
  `README.md` (Features list)

- [ ] **Step 1: SETUP** — a "Collection" subsection under project settings: the toggle, spec §3 table, the two
  cases (token-dispatched schedulers, container image), and a troubleshooting row "My run doesn't appear in QEOS"
  → check Settings › Collection and the collector's `run not collected` line.
- [ ] **Step 2: PRODUCT / README Features / TODO** — one line each; TODO item done with the date.
- [ ] **Step 3: Employer-name check** — a case-insensitive `git grep` for the employer's name prints nothing (Global Constraints).
- [ ] **Step 4: Full CI locally**, commit `docs: collect manual runs, setup and product`, push, watch CI green.
- [ ] **Step 5: Rebuild the local stack's dashboard and ingestion** —
  `docker compose up -d --build --wait ingestion-migrate ingestion-service dashboard gateway`, then
  `bash scripts/smoke_gateway.sh`.
