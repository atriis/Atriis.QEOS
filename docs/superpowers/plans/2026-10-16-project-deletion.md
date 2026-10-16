# Project deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owners and admins delete a project from Settings after typing its name; the project waits 7 days greyed out and restorable by owners and admins, then a purge removes everything of it in test-management, ingestion and project-service.

**Architecture:** project-service keeps the state (`deleted_at`, new `deleted_by`, new `purge_state`), answers 410 with the purge date for a pending project, adds `restore`, an owners/admins-only `include_pending` list, and internal endpoints for the purge. The ingestion retention job becomes the purge driver: after `PROJECT_DELETE_GRACE_DAYS` it calls test-management's new internal delete, empties ingestion, then deletes the project row, recording each confirmed step so a failed pass resumes. Ingestion refuses uploads for a pending project (410, read from the internal project feed, cached 60 s). The dashboard adds the delete dialog, greyed rows with Restore for owners and admins, and a notice page for members.

**Tech Stack:** FastAPI 0.143, SQLAlchemy 2.1, Alembic, Pydantic 2, httpx, respx (services); React 19, TypeScript, TanStack Query 5, MSW, Vitest (dashboard).

**Spec:** `docs/superpowers/specs/2026-10-16-project-deletion-design.md` (binding; read it before any task).

## Global Constraints

- Only **owners and admins** (`MANAGE_ROLES = ("owner", "admin")`) delete, restore, and see pending projects. Every other role never gets a pending project from a list; on its URLs they get the notice (410 body).
- Grace: `PROJECT_DELETE_GRACE_DAYS` (default **7**), read by project-service (purge date shown) and by the purge job; it replaces ingestion's `RETENTION_DELETED_GRACE_DAYS`.
- Pending project: `GET /api/v1/projects/{id}` answers **410** `{"detail": {"code": "pending_deletion", "message": "This project is scheduled for deletion", "organization_id": int, "deleted_at": iso, "deleted_by": int|null, "purge_at": iso}}` to every member; every other project route answers 404 as today; non-members always 404.
- `POST /api/v1/projects/{id}/restore`: owners/admins → 200 project; a live or unknown project → 404; a name or slug now taken by a live project → 409 `"A live project already uses this name or slug; rename it first"`; once the purge has started (`purge_state` not empty) → 409 `"The purge has started; this project can no longer be restored"`.
- `DELETE /api/v1/projects/{id}` under a legal hold → **409** `"Release the legal hold before deleting this project"`.
- Uploads (every API-key route) for a pending project → **410** `"Project scheduled for deletion"`; if project-service cannot be read, uploads go through (fail open) and the last known answer is used.
- API keys are **not** revoked during the 7 days (a restore brings them back); the purge deletes them.
- Purge order, each step idempotent and recorded in `purge_state`: `started` → `test_management` → `ingestion` → project row. Recording `started` is the atomic check: project-service refuses it (409) for a live project, and refuses a restore once it is recorded, so a restore and a purge can never both win. The row goes last and only after both data steps are recorded.
- Delete confirmation: the project name typed **exactly** (case-sensitive, trimmed input compared to the name).
- Docs updated in the same commits as behaviour (ADR-033, SETUP §4.7, SECURITY, PRODUCT, TECHNICAL_SPECIFICATION, DESIGN, the three service READMEs, `.env.example`).
- Another session may work in this tree: `git add <paths>` then `git commit -o <paths> -m …`; never `git add -A`. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Push only a SHA the user clears.
- Every dashboard UI task starts by invoking the `ui-ux-pro-max` skill (project rule).
- Never run the smoke script or migrations against the user's running stack (compose project `qeos`).

**How to run things (Git Bash, repo root `C:/dev/github/Atriis.QEOS`):**

- Python services: create a CI-matching venv once per service, e.g. `py -3.11 -m venv "$HOME/.venvs/qeos-project" && "$HOME/.venvs/qeos-project/Scripts/python.exe" -m pip install -r platforms/project-service/requirements.txt`; same for `qeos-testmgmt` (test-management-service). Ingestion's is `$HOME/.venvs/qeos-ingestion`. Run from the service directory: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/<file> -q`.
- Dashboard, from `dashboard/`: `npx vitest run <files>`, `npm run lint`, `npm run typecheck`, `npm run build`; gate `npx vitest run --no-file-parallelism`. Run commands from absolute paths (`cd /c/dev/github/Atriis.QEOS/dashboard && …`) so a parallel call never runs vitest from the repo root.
- Migrations on PostgreSQL: throwaway `postgres:16-alpine` on port 55432 (`docker run -d --rm --name qeos-mig-check -e POSTGRES_PASSWORD=x -p 55432:5432 postgres:16-alpine`), alembic from the service directory with `DATABASE_URL=postgresql://postgres:x@localhost:55432/postgres`, then `docker stop qeos-mig-check`.
- Smoke: `bash -n scripts/smoke_gateway.sh` only. Architecture docs: `python scripts/check_architecture_docs.py`.

## Review Focus

1. **Restore after the name was reused.** A deleted project's name is free (the unique index covers live rows only), so someone may create a new project with that name during the 7 days; Restore must answer 409 with a clear message, never a 500 or two live projects with one name. Pinned in Task 1 (`test_restore_when_the_name_was_reused_is_409`).
2. **A purge that fails halfway.** test-management down, or the project-service delete failing, must leave the project pending with the confirmed steps recorded, and the next pass must continue from there without redoing or skipping a step. Pinned in Task 6 (`test_a_failed_test_management_step_leaves_it_for_the_next_pass`, `test_a_recorded_step_is_not_redone`).
3. **Restore racing the purge.** A project restored while a pass runs must keep everything: the purge first records `started`, which project-service refuses for a live project, and after which it refuses any restore. Pinned in Task 1 (`test_restore_after_the_purge_started_is_409`), Task 2 (`test_internal_delete_refuses_a_live_project`) and Task 6 (`test_a_restored_project_is_never_purged`, `test_a_project_restored_after_the_feed_was_read_is_left_alone`).
4. **Uploads during the window and after a restore.** A CI pipeline uploading to a pending project gets 410 with the reason, nothing stored; after Restore the same key works again within the cache time. Pinned in Task 5 (`test_an_upload_to_a_pending_project_is_410_and_stores_nothing`, `test_after_restore_the_key_works_again`).
5. **A member who opens a pending project's URL.** They see the notice with the purge date, not a blank 404 page and not the project's data; owners and admins see Restore there too. Pinned in Task 8 (`a member sees the deletion notice`, `an owner can restore from the notice`).

## File Structure

project-service: `alembic/versions/005_project_deletion.py` (new), `src/project/models/project.py`, `src/project/core/config.py`, `src/project/schemas/project.py`, `src/project/service/project_service.py`, `src/project/api/deps.py`, `src/project/api/v1/endpoints/projects.py`, `src/project/api/v1/endpoints/internal.py`; tests `tests/integration/test_project_deletion.py` (new), `test_internal_endpoints.py`, `tests/unit/test_migration.py`, `test_projects_endpoints.py`.

test-management: `src/casebook/core/config.py`, `src/casebook/api/internal.py` (new), `src/casebook/service/purge_service.py` (new), `src/casebook/api/main.py`, `src/casebook/utils/project_client.py`; tests `tests/integration/test_internal_purge.py` (new), `tests/integration/test_cases.py`.

ingestion: `src/ingestion/core/config.py`, `src/ingestion/utils/project_client.py`, `src/ingestion/utils/project_state.py` (new), `src/ingestion/api/key_auth.py`, `src/ingestion/jobs/retention.py`, `src/ingestion/jobs/purge.py` (new); tests `tests/unit/test_project_client.py`, `tests/integration/test_pending_uploads.py` (new), `tests/integration/test_retention_job.py`, `tests/integration/test_purge.py` (new).

dashboard: `src/api/orgs.ts`, `src/components/DeleteProjectDialog.tsx` (new) + test, `src/components/DataCard.tsx`, `src/pages/PickerPage.tsx` + test, `src/pages/ProjectLayout.tsx`, `src/components/PendingDeletion.tsx` (new) + test, `src/index.css`.

Repo: `docker-compose.yml`, `.env.example`, `scripts/smoke_gateway.sh`, `docs/architecture/adr/ADR-033-project-deletion.md` (new), `docs/architecture/adr/INDEX.md`, `docs/SETUP.md`, `SECURITY.md`, `PRODUCT.md`, `TECHNICAL_SPECIFICATION.md`, `DESIGN.md`, the three service READMEs.

---

### Task 1: project-service — delete records who, restore, the pending answer, `include_pending`

**Files:**
- Create: `platforms/project-service/alembic/versions/005_project_deletion.py`
- Modify: `src/project/models/project.py`, `src/project/core/config.py`, `src/project/schemas/project.py`, `src/project/service/project_service.py`, `src/project/api/v1/endpoints/projects.py`
- Create: `platforms/project-service/tests/integration/test_project_deletion.py`
- Modify: `tests/unit/test_migration.py` (only if it lists columns explicitly; run it to see)

**Interfaces:**
- Produces (columns): `Project.deleted_by` (Integer, nullable), `Project.purge_state` (JSON, nullable; e.g. `{"test_management": "2026-10-23T03:00:00+00:00"}`).
- Produces (settings): `PROJECT_DELETE_GRACE_DAYS: int = 7`.
- Produces (schemas): `DeletionOut(deleted_at: datetime, deleted_by: Optional[int], purge_at: datetime)`; `ProjectOut.deletion: Optional[DeletionOut] = None`.
- Produces (service): `project_service.soft_delete(db, project, user_id)` (raises `LegalHoldActive`); `project_service.restore(db, project) -> Project` (raises `PurgeStarted`, `DuplicateProject`); `project_service.purge_at(project) -> datetime`; `project_service.get_pending(db, project_id) -> Optional[Project]`; `project_service.list_projects(db, org_id, limit, offset, include_pending=False)`.
- Produces (HTTP): see Global Constraints.

- [ ] **Step 1: Write the failing tests** — create `platforms/project-service/tests/integration/test_project_deletion.py`:

```python
"""Project deletion (spec 2026-10-16): who deleted it, 7 days pending, restore, and what each role sees."""
from datetime import datetime, timedelta, timezone

import pytest

from src.project.models.project import Project

MANAGERS = ("owner", "admin")
OTHERS = ("member", "viewer", "billing_manager")


def delete(client, auth, project_id, user_id=1):
    return client.delete(f"/api/v1/projects/{project_id}", headers=auth(user_id))


def test_delete_records_who_and_when(client, auth, org_role, make_project, db):
    project = make_project()
    org_role("admin")
    assert delete(client, auth, project.id, user_id=7).status_code == 204
    db.expire_all()
    row = db.get(Project, project.id)
    assert row.deleted_by == 7 and row.deleted_at is not None


def test_delete_under_legal_hold_is_409(client, auth, org_role, make_project, db):
    project = make_project()
    project.legal_hold_at = datetime.now(timezone.utc)
    db.commit()
    org_role("owner")
    response = delete(client, auth, project.id)
    assert response.status_code == 409
    assert response.json()["detail"] == "Release the legal hold before deleting this project"


@pytest.mark.parametrize("role", MANAGERS + OTHERS)
def test_a_pending_project_answers_410_with_the_purge_date(client, auth, org_role, make_project, db, role):
    project = make_project()
    deleted_at = datetime(2026, 10, 16, 14, 5, tzinfo=timezone.utc)
    project.deleted_at, project.deleted_by = deleted_at, 7
    db.commit()
    org_role(role)
    response = client.get(f"/api/v1/projects/{project.id}", headers=auth())
    assert response.status_code == 410
    detail = response.json()["detail"]
    assert detail["code"] == "pending_deletion" and detail["deleted_by"] == 7
    assert detail["organization_id"] == project.organization_id
    assert detail["purge_at"].startswith("2026-10-23T14:05")


def test_a_non_member_gets_404_for_a_pending_project(client, auth, org_role, make_project, db):
    project = make_project()
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
    org_role(status_code=404, body={"detail": "Organization not found"})
    assert client.get(f"/api/v1/projects/{project.id}", headers=auth()).status_code == 404


def test_other_routes_of_a_pending_project_are_404(client, auth, org_role, make_project, db):
    project = make_project()
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
    org_role("owner")
    assert client.patch(f"/api/v1/projects/{project.id}", json={"description": "x"}, headers=auth()).status_code == 404
    assert delete(client, auth, project.id).status_code == 404


@pytest.mark.parametrize("role", MANAGERS)
def test_owners_and_admins_restore(client, auth, org_role, make_project, db, role):
    project = make_project()
    org_role(role)
    delete(client, auth, project.id)
    response = client.post(f"/api/v1/projects/{project.id}/restore", headers=auth())
    assert response.status_code == 200, response.text
    assert response.json()["deletion"] is None
    assert client.get(f"/api/v1/projects/{project.id}", headers=auth()).status_code == 200
    db.expire_all()
    row = db.get(Project, project.id)
    assert (row.deleted_at, row.deleted_by, row.purge_state) == (None, None, None)


@pytest.mark.parametrize("role", OTHERS)
def test_other_roles_cannot_restore(client, auth, org_role, make_project, db, role):
    project = make_project()
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
    org_role(role)
    assert client.post(f"/api/v1/projects/{project.id}/restore", headers=auth()).status_code == 403


def test_restoring_a_live_or_unknown_project_is_404(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    assert client.post(f"/api/v1/projects/{project.id}/restore", headers=auth()).status_code == 404
    assert client.post("/api/v1/projects/999/restore", headers=auth()).status_code == 404


def test_restore_when_the_name_was_reused_is_409(client, auth, org_role, make_project, db):
    project = make_project(name="Checkout", slug="checkout")
    org_role("owner")
    delete(client, auth, project.id)
    assert client.post("/api/v1/organizations/1/projects", json={"name": "Checkout"}, headers=auth()).status_code == 201
    response = client.post(f"/api/v1/projects/{project.id}/restore", headers=auth())
    assert response.status_code == 409
    assert response.json()["detail"] == "A live project already uses this name or slug; rename it first"
    db.expire_all()
    assert db.get(Project, project.id).deleted_at is not None


def test_restore_after_the_purge_started_is_409(client, auth, org_role, make_project, db):
    project = make_project()
    project.deleted_at = datetime.now(timezone.utc) - timedelta(days=8)
    project.purge_state = {"started": "2026-10-23T03:00:00+00:00"}
    db.commit()
    org_role("owner")
    response = client.post(f"/api/v1/projects/{project.id}/restore", headers=auth())
    assert response.status_code == 409
    assert response.json()["detail"] == "The purge has started; this project can no longer be restored"


@pytest.mark.parametrize("role", MANAGERS)
def test_owners_and_admins_see_pending_projects_when_they_ask(client, auth, org_role, make_project, db, role):
    live = make_project(name="Live")
    pending = make_project(name="Pending")
    pending.deleted_at, pending.deleted_by = datetime.now(timezone.utc) - timedelta(days=1), 3
    db.commit()
    org_role(role)
    plain = client.get("/api/v1/organizations/1/projects", headers=auth()).json()
    assert [p["id"] for p in plain] == [live.id]
    both = client.get("/api/v1/organizations/1/projects?include_pending=true", headers=auth()).json()
    assert [p["id"] for p in both] == [live.id, pending.id]
    assert both[0]["deletion"] is None and both[1]["deletion"]["deleted_by"] == 3


@pytest.mark.parametrize("role", OTHERS)
def test_other_roles_never_see_pending_projects(client, auth, org_role, make_project, db, role):
    make_project(name="Live")
    pending = make_project(name="Pending")
    pending.deleted_at = datetime.now(timezone.utc)
    db.commit()
    org_role(role)
    listed = client.get("/api/v1/organizations/1/projects?include_pending=true", headers=auth()).json()
    assert [p["name"] for p in listed] == ["Live"]
```

- [ ] **Step 2: Run them to verify they fail**

Run (from `platforms/project-service`): `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_project_deletion.py -q`
Expected: FAIL (`deleted_by` attribute missing, 404 where 410 is expected, restore route 404/405).

- [ ] **Step 3: Migration** — create `platforms/project-service/alembic/versions/005_project_deletion.py`:

```python
"""project deletion: who deleted a project, and which purge steps other services confirmed (spec 2026-10-16)

Revision ID: 005
Revises: 004
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("deleted_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("purge_state", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("purge_state")
        batch.drop_column("deleted_by")
```

- [ ] **Step 4: Model, setting, schemas.**
  - `src/project/models/project.py`: add `JSON` to the sqlalchemy import if missing, and after `deleted_at = Column(...)`:

```python
    # Who deleted it (spec 2026-10-16), and which purge steps other services confirmed: {"test_management": iso, ...}
    deleted_by = Column(Integer, nullable=True)
    purge_state = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
```
    (import `from sqlalchemy.dialects.postgresql import JSONB` if the file does not have it).
  - `src/project/core/config.py`, after `INTERNAL_API_PASSWORD`: `    # A deleted project is purged everywhere this long after the deletion; until then it can be restored\n    PROJECT_DELETE_GRACE_DAYS: int = 7`.
  - `src/project/schemas/project.py`: after `LegalHoldOut` add

```python
class DeletionOut(BaseModel):
    """A pending deletion (spec 2026-10-16): restorable by owners and admins until purge_at."""

    deleted_at: datetime
    deleted_by: Optional[int] = None
    purge_at: datetime
```
    and in `ProjectOut` after `legal_hold: …` add `    deletion: Optional[DeletionOut] = None`.

- [ ] **Step 5: Service.** In `src/project/service/project_service.py`, add `timedelta` to the datetime import, `from src.project.core.config import settings`, and replace `soft_delete` with:

```python
class LegalHoldActive(Exception):
    pass


class PurgeStarted(Exception):
    pass


def purge_at(project: Project) -> datetime:
    deleted_at = project.deleted_at if project.deleted_at.tzinfo else project.deleted_at.replace(tzinfo=timezone.utc)
    return deleted_at + timedelta(days=settings.PROJECT_DELETE_GRACE_DAYS)


def soft_delete(db: Session, project: Project, user_id: int) -> None:
    """Pending deletion: hidden from everyone but owners and admins, restorable until purge_at, then purged by the
    ingestion retention job (spec 2026-10-16). Data under a legal hold cannot be deleted."""
    if project.legal_hold_at is not None:
        raise LegalHoldActive("Release the legal hold before deleting this project")
    project.deleted_at = datetime.now(timezone.utc)
    project.deleted_by = user_id
    project.purge_state = None
    db.commit()


def get_pending(db: Session, project_id: int) -> Optional[Project]:
    return db.query(Project).filter(Project.id == project_id, Project.deleted_at.isnot(None)).first()


def restore(db: Session, project: Project) -> Project:
    if project.purge_state:
        # The purge job recorded "started": data may already be gone in other services
        raise PurgeStarted("The purge has started; this project can no longer be restored")
    project.deleted_at = project.deleted_by = project.purge_state = None
    try:
        _commit(db)
    except DuplicateProject:
        raise DuplicateProject("A live project already uses this name or slug; rename it first")
    db.refresh(project)
    return project
```
    (add `Optional` to a `from typing import Optional` import). Change `list_projects` to:

```python
def list_projects(db: Session, org_id: int, limit: int, offset: int, include_pending: bool = False) -> list[Project]:
    query = db.query(Project).filter(Project.organization_id == org_id)
    if not include_pending:
        query = query.filter(Project.deleted_at.is_(None))
    return query.order_by(Project.id).offset(offset).limit(limit).all()
```

- [ ] **Step 6: Endpoints.** In `src/project/api/v1/endpoints/projects.py`:
  - import `DeletionOut` with the other schemas, `from src.project.api.deps import Caller, get_caller` additions as needed, and `from src.project.api import deps`;
  - in `_out`, add after `legal_hold=(…),`:

```python
        deletion=(
            DeletionOut(deleted_at=project.deleted_at, deleted_by=project.deleted_by,
                        purge_at=project_service.purge_at(project))
            if project.deleted_at is not None else None
        ),
```
  - replace `list_projects` with:

```python
@org_router.get("", response_model=list[ProjectOut])
def list_projects(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    # Owners and admins may also see projects pending deletion, to restore them (spec 2026-10-16)
    include_pending: bool = Query(False),
    db: Session = Depends(get_db),
    access: OrgAccess = Depends(require_org_role(*READ_ROLES)),
):
    pending = include_pending and access.role in MANAGE_ROLES
    projects = project_service.list_projects(db, access.org_id, limit, offset, include_pending=pending)
    return [_out(project, access.role) for project in projects]
```
  - replace `get_project` with:

```python
@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    caller: deps.Caller = Depends(deps.get_caller),
):
    """A pending project answers 410 with when it will be purged, to any member (spec 2026-10-16); the dashboard
    shows a notice instead of a blank page. Other services treat 410 as "not found"."""
    pending = project_service.get_pending(db, project_id)
    if pending is not None:
        org_id = pending.organization_id
        db.rollback()  # no transaction held over the HTTP call (see deps)
        deps.role_in(org_id, caller, "Project not found")
        raise HTTPException(status_code=status.HTTP_410_GONE, detail={
            "code": "pending_deletion", "message": "This project is scheduled for deletion",
            "organization_id": org_id, "deleted_at": pending.deleted_at.isoformat(), "deleted_by": pending.deleted_by,
            "purge_at": project_service.purge_at(pending).isoformat(),
        })
    access = deps.require_project_role(*READ_ROLES)(project_id, db, caller)
    return _out(access.project, access.role)
```
  - in `src/project/api/deps.py`, rename `_role_in` to `role_in` (update its two callers in the file) so the endpoint can call it;
  - replace `delete_project` and add `restore_project`:

```python
@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    try:
        project_service.soft_delete(db, access.project, access.user_id)
    except project_service.LegalHoldActive as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/restore", response_model=ProjectOut)
def restore_project(
    project_id: int,
    db: Session = Depends(get_db),
    caller: deps.Caller = Depends(deps.get_caller),
):
    """Undo a pending deletion (owners and admins). A live or purged project is 404."""
    pending = project_service.get_pending(db, project_id)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    org_id = pending.organization_id
    db.rollback()
    role = deps.role_in(org_id, caller, "Project not found")
    if role not in MANAGE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    project = project_service.get_pending(db, project_id)
    if project is None:  # restored or purged meanwhile
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        project = project_service.restore(db, project)
    except (project_service.PurgeStarted, project_service.DuplicateProject) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _out(project, role)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q`
Expected: PASS, except the existing `test_deleted_project_is_gone_for_everyone` in `test_projects_endpoints.py`, which now gets 410 on `GET` for a member: change its `GET` assertion to 410 and rename it `test_a_deleted_project_is_pending_for_its_members` (its other routes stay 404). `tests/unit/test_migration.py` passes with migration 005.

- [ ] **Step 8: Migration on PostgreSQL** (throwaway container; `upgrade head`, `downgrade 004`, `upgrade head`). Expected: exit 0; `\d projects` shows `deleted_by` and `purge_state jsonb`.

- [ ] **Step 9: Commit**

```bash
git add platforms/project-service/alembic/versions/005_project_deletion.py platforms/project-service/src platforms/project-service/tests
git commit -o platforms/project-service/alembic/versions/005_project_deletion.py platforms/project-service/src platforms/project-service/tests -m "feat(project): project deletion pending 7 days: who deleted it, 410 with the purge date, restore, include_pending for owners and admins" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: project-service — internal purge endpoints

**Files:**
- Modify: `platforms/project-service/src/project/api/v1/endpoints/internal.py`
- Test: `platforms/project-service/tests/integration/test_internal_endpoints.py` (append; update the expected feed rows)

**Interfaces:**
- Consumes: `Project.purge_state`, `Project.deleted_by` (Task 1).
- Produces (HTTP, HTTP Basic internal credentials): feed rows gain `"purge_state": dict | null`; `POST /internal/v1/projects/{id}/purge-state` body `{"step": "started" | "test_management" | "ingestion"}` → 204 (records `{step: now}`); 409 when the project is live (so a restored project is never purged); 404 when unknown. `DELETE /internal/v1/projects/{id}` → 204 after deleting overview layouts, repositories and the row; 409 `"Project is not pending deletion"` when live; 409 `"Purge steps missing: …"` unless both steps are recorded; 204 when already gone.

- [ ] **Step 1: Write the failing tests.** In `test_internal_endpoints.py`, add `"purge_state": None` to each of the three expected rows in `test_correct_credentials_list_every_project_with_its_retention`, then append:

```python
def pending_project(make_project, db, purge_state=None):
    project = make_project(name="Pending")
    project.deleted_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    project.purge_state = purge_state
    db.commit()
    return project


def test_purge_state_records_a_confirmed_step(client, configured, make_project, db):
    project = pending_project(make_project, db)
    response = client.post(f"/internal/v1/projects/{project.id}/purge-state", json={"step": "test_management"},
                           headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 204
    db.expire_all()
    assert set(db.get(Project, project.id).purge_state) == {"test_management"}
    feed = client.get(URL, headers=basic("ingestion-service", PASSWORD)).json()["projects"]
    assert set(feed[0]["purge_state"]) == {"test_management"}


def test_purge_state_of_a_live_project_is_409(client, configured, make_project):
    project = make_project()
    response = client.post(f"/internal/v1/projects/{project.id}/purge-state", json={"step": "ingestion"},
                           headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 409


def test_internal_delete_refuses_a_live_project(client, configured, make_project, db):
    project = make_project()
    response = client.delete(f"/internal/v1/projects/{project.id}", headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 409
    assert db.get(Project, project.id) is not None


def test_internal_delete_needs_both_steps(client, configured, make_project, db):
    project = pending_project(make_project, db, {"test_management": "2026-10-08T03:00:00+00:00"})
    response = client.delete(f"/internal/v1/projects/{project.id}", headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 409 and "ingestion" in response.json()["detail"]


def test_internal_delete_removes_the_project_and_its_rows(client, configured, make_project, db):
    from src.project.models.overview_layout import OverviewLayout
    from src.project.models.repository import Repository

    project = pending_project(make_project, db, {"test_management": "x", "ingestion": "y"})
    db.add(OverviewLayout(project_id=project.id, user_id=None, layout={}, version=1, updated_by=1))
    db.add(Repository(project_id=project.id, name="r", url="https://github.com/acme/r", provider="github",
                      added_by=1))
    other = make_project(name="Other")
    db.commit()
    response = client.delete(f"/internal/v1/projects/{project.id}", headers=basic("ingestion-service", PASSWORD))
    assert response.status_code == 204
    db.expire_all()
    assert db.get(Project, project.id) is None
    assert db.query(OverviewLayout).filter_by(project_id=project.id).count() == 0
    assert db.query(Repository).filter_by(project_id=project.id).count() == 0
    assert db.get(Project, other.id) is not None
    again = client.delete(f"/internal/v1/projects/{project.id}", headers=basic("ingestion-service", PASSWORD))
    assert again.status_code == 204


def test_internal_purge_routes_need_the_credentials(client, configured, make_project, db):
    project = pending_project(make_project, db)
    assert client.delete(f"/internal/v1/projects/{project.id}").status_code == 401
    assert client.post(f"/internal/v1/projects/{project.id}/purge-state", json={"step": "ingestion"}).status_code == 401
```
  (add `from src.project.models.project import Project` to the imports. Check the `Repository` constructor fields against `src/project/models/repository.py` and use the required ones.)

- [ ] **Step 2: Run them to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_internal_endpoints.py -q`
Expected: FAIL (`purge_state` missing from the feed; 404/405 on the new routes).

- [ ] **Step 3: Implement.** In `internal.py`:
  - add `purge_state: Optional[dict] = None` to `ProjectRetention` and `purge_state=project.purge_state,` in `list_retention`;
  - add imports `from typing import Literal`, `from datetime import datetime, timezone`, `from fastapi import Response`, `from src.project.models.overview_layout import OverviewLayout`, `from src.project.models.repository import Repository`;
  - append:

```python
PURGE_STEPS = ("test_management", "ingestion")


class PurgeStepIn(BaseModel):
    # "started" first: from then on a restore is refused (Task 1), so restore and purge never both win
    step: Literal["started", "test_management", "ingestion"]


def _pending_or_error(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project is not pending deletion")
    return project


@router.post("/projects/{project_id}/purge-state", status_code=status.HTTP_204_NO_CONTENT)
def record_purge_step(project_id: int, payload: PurgeStepIn, _: None = Depends(require_internal_caller),
                      db: Session = Depends(get_db)):
    """The purge job confirms one service emptied the project (spec 2026-10-16 §5)."""
    project = _pending_or_error(db, project_id)
    # A new dict, so SQLAlchemy sees the change
    project.purge_state = {**(project.purge_state or {}), payload.step: datetime.now(timezone.utc).isoformat()}
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_project(project_id: int, _: None = Depends(require_internal_caller), db: Session = Depends(get_db)):
    """The last purge step: the project row and what hangs off it. Only a pending project whose other services
    confirmed their part; a project already gone is 204 (the step is idempotent)."""
    project = db.get(Project, project_id)
    if project is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    project = _pending_or_error(db, project_id)
    missing = [step for step in PURGE_STEPS if step not in (project.purge_state or {})]
    if missing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Purge steps missing: {', '.join(missing)}")
    # Children explicitly: SQLite (the tests) does not enforce ON DELETE CASCADE
    db.query(OverviewLayout).filter(OverviewLayout.project_id == project_id).delete(synchronize_session=False)
    db.query(Repository).filter(Repository.project_id == project_id).delete(synchronize_session=False)
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/project-service/src/project/api/v1/endpoints/internal.py platforms/project-service/tests/integration/test_internal_endpoints.py
git commit -o platforms/project-service/src/project/api/v1/endpoints/internal.py platforms/project-service/tests/integration/test_internal_endpoints.py -m "feat(project): internal purge endpoints: record a confirmed step, delete the project row last" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: ingestion and test-management read 410 as "not found"

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/utils/project_client.py`, `platforms/test-management-service/src/casebook/utils/project_client.py`
- Test: `platforms/ingestion-service/tests/unit/test_project_client.py`, `platforms/test-management-service/tests/integration/test_cases.py` (append)

**Interfaces:** Produces: both `get_project` raise `ProjectNotFound` on 410 (a pending project), so their routes answer 404 as before.

- [ ] **Step 1: Write the failing tests.** Append to ingestion's `tests/unit/test_project_client.py`:

```python
def test_410_a_project_pending_deletion_is_project_not_found(project_role):
    project_role(project_id=7, status_code=410, body={"detail": {"code": "pending_deletion"}})
    with pytest.raises(project_client.ProjectNotFound):
        project_client.get_project(7, "t")
```
  Append to test-management's `tests/integration/test_cases.py`:

```python
def test_a_project_pending_deletion_is_404(client, auth, project_role):
    project_role(status_code=410, body={"detail": {"code": "pending_deletion"}})
    assert client.get("/api/v1/projects/1/cases", headers=auth()).status_code == 404
```
  (use the file's own auth fixture name; read its first test to match.)

- [ ] **Step 2: Run them to verify they fail** — ingestion: `ProjectServiceUnavailable` raised; test-management: 503.

- [ ] **Step 3: Implement** — in both `project_client.py`, change `if response.status_code == 404:` to:

```python
    # 410: the project is pending deletion (spec 2026-10-16); for every other service it no longer exists
    if response.status_code in (404, 410):
```

- [ ] **Step 4: Run the full suites of both services.** Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/utils/project_client.py platforms/ingestion-service/tests/unit/test_project_client.py platforms/test-management-service/src/casebook/utils/project_client.py platforms/test-management-service/tests/integration/test_cases.py
git commit -o platforms/ingestion-service/src/ingestion/utils/project_client.py platforms/ingestion-service/tests/unit/test_project_client.py platforms/test-management-service/src/casebook/utils/project_client.py platforms/test-management-service/tests/integration/test_cases.py -m "fix: a project pending deletion (410 from project-service) is not found in ingestion and test-management" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: test-management — internal purge endpoint

**Files:**
- Modify: `platforms/test-management-service/src/casebook/core/config.py`, `src/casebook/api/main.py`
- Create: `src/casebook/api/internal.py`, `src/casebook/service/purge_service.py`, `tests/integration/test_internal_purge.py`
- Modify: `docker-compose.yml` (`x-testmgmt-env`: `INTERNAL_API_PASSWORD`)

**Interfaces:** Produces (HTTP): `DELETE /internal/v1/projects/{id}` with HTTP Basic (`INTERNAL_API_USERNAME` default `"ingestion-service"`, `INTERNAL_API_PASSWORD`) → 204; 401 without them; 503 when the password is not configured. Produces (service): `purge_service.purge_project(db, project_id) -> dict[str, int]` (rows deleted per table).

- [ ] **Step 1: Write the failing tests** — create `tests/integration/test_internal_purge.py`:

```python
"""DELETE /internal/v1/projects/{id}: the purge job empties test-management of one project (spec 2026-10-16)."""
import base64
from datetime import datetime, timezone

import pytest

from src.casebook.core.config import settings
from src.casebook.models import (
    Case, CaseLabel, CiTarget, CiTargetEvent, FeatureFile, RunRequest, Suite, SuiteCase,
)

PASSWORD = "internal-test-password"
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_USERNAME", "ingestion-service")
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", PASSWORD)


def basic(user="ingestion-service", password=PASSWORD):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def seed(db, project_id):
    case = Case(project_id=project_id, number=1, key=f"TC-{project_id}", title="t", steps=[], status="draft",
                priority="medium", created_by=1)
    db.add(case)
    db.flush()
    db.add(CaseLabel(case_id=case.id, label="smoke"))
    suite = Suite(project_id=project_id, name=f"s{project_id}", created_by=1)
    db.add(suite)
    db.flush()
    db.add(SuiteCase(suite_id=suite.id, case_id=case.id))
    db.add(FeatureFile(project_id=project_id, path="f.feature", content="Feature: f", imported_by=1))
    db.add(RunRequest(project_id=project_id, requested_by=1, requested_at=NOW, selection=[], status="completed"))
    db.add(CiTarget(project_id=project_id, repository="acme/r", workflow="qeos.yml", ref="main", updated_by=1))
    db.add(CiTargetEvent(project_id=project_id, action="saved", by=1, at=NOW))
    db.commit()


def count(db, project_id):
    return sum(db.query(m).filter(m.project_id == project_id).count()
               for m in (Case, Suite, FeatureFile, RunRequest, CiTarget, CiTargetEvent))


def test_it_deletes_every_row_of_the_project_and_nothing_else(client, configured, db):
    seed(db, 1)
    seed(db, 2)
    response = client.delete("/internal/v1/projects/1", headers=basic())
    assert response.status_code == 204
    db.expire_all()
    assert count(db, 1) == 0 and db.query(CaseLabel).count() == 1 and db.query(SuiteCase).count() == 1
    assert count(db, 2) == 6


def test_a_project_with_nothing_is_204(client, configured):
    assert client.delete("/internal/v1/projects/99", headers=basic()).status_code == 204


@pytest.mark.parametrize("headers", [{}, basic(password="wrong"), basic(user="someone-else")])
def test_without_the_credentials_it_is_401(client, configured, headers, db):
    seed(db, 1)
    assert client.delete("/internal/v1/projects/1", headers=headers).status_code == 401
    assert count(db, 1) == 6


def test_without_a_configured_password_it_is_503(client):
    assert client.delete("/internal/v1/projects/1", headers=basic()).status_code == 503
```
  Before Step 2, open `src/casebook/models/*.py` and adjust the constructor arguments in `seed` to each model's real required columns (names above are the likely ones; a wrong name fails loudly in Step 2, fix it there and ledger nothing: it is test setup).

- [ ] **Step 2: Run them to verify they fail** — 404 (no route).

- [ ] **Step 3: Implement.**
  - `src/casebook/core/config.py`, after `PROJECT_SERVICE_TIMEOUT_SECONDS`: 

```python
    # Internal API (DELETE /internal/v1/projects/{id}), called by ingestion's purge job with HTTP Basic (spec 2026-10-16)
    INTERNAL_API_USERNAME: str = "ingestion-service"
    INTERNAL_API_PASSWORD: str = ""
```
  - `src/casebook/service/purge_service.py`:

```python
"""Purge one project's test-management data (spec 2026-10-16): the purge job calls it once the project's
deletion window is over. Children first: SQLite (the tests) does not enforce ON DELETE CASCADE."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.casebook.models import Case, CaseLabel, CiTarget, CiTargetEvent, FeatureFile, RunRequest, Suite, SuiteCase


def purge_project(db: Session, project_id: int) -> dict:
    cases = select(Case.id).where(Case.project_id == project_id)
    suites = select(Suite.id).where(Suite.project_id == project_id)
    deleted = {
        "suite_cases": db.query(SuiteCase).filter(SuiteCase.suite_id.in_(suites)).delete(synchronize_session=False),
        "case_labels": db.query(CaseLabel).filter(CaseLabel.case_id.in_(cases)).delete(synchronize_session=False),
    }
    for model in (Suite, Case, FeatureFile, RunRequest, CiTargetEvent, CiTarget):
        deleted[model.__tablename__] = (
            db.query(model).filter(model.project_id == project_id).delete(synchronize_session=False))
    db.commit()
    return deleted
```
  - `src/casebook/api/internal.py`:

```python
import hmac
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from src.casebook.api.deps import get_db
from src.casebook.core.config import settings
from src.casebook.service import purge_service

router = APIRouter()  # mounted at /internal/v1, outside the gateway's routes
_basic = HTTPBasic(auto_error=False)


def _same(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def require_internal_caller(credentials: Optional[HTTPBasicCredentials] = Depends(_basic)) -> None:
    if not settings.INTERNAL_API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Internal API is not configured")
    # Both parts are always compared, so the timing does not tell which one was wrong
    user_ok = credentials is not None and _same(credentials.username, settings.INTERNAL_API_USERNAME)
    password_ok = credentials is not None and _same(credentials.password, settings.INTERNAL_API_PASSWORD)
    if not (user_ok and password_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal credentials",
                            headers={"WWW-Authenticate": "Basic"})


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge(project_id: int, _: None = Depends(require_internal_caller), db: Session = Depends(get_db)):
    """Every case, label, suite, feature file, run request and CI target of the project. Idempotent."""
    purge_service.purge_project(db, project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```
  - `src/casebook/api/main.py`: `from src.casebook.api import internal` and after `app.include_router(api_router, …)`: `app.include_router(internal.router, prefix="/internal/v1", include_in_schema=False)`.
  - `docker-compose.yml`, in the `x-testmgmt-env` anchor: `  # Internal API (DELETE /internal/v1/projects/{id}), called by ingestion's purge job\n  INTERNAL_API_PASSWORD: ${INTERNAL_API_PASSWORD:?set INTERNAL_API_PASSWORD (service-to-service internal APIs; URL-safe characters)}`.
  Verify the gateway does not route `/internal/`: `grep -n "internal" gateway/nginx.conf.template` — it must show only a deny or nothing that proxies it.

- [ ] **Step 4: Run the test-management suite.** Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/test-management-service/src/casebook/core/config.py platforms/test-management-service/src/casebook/api/main.py platforms/test-management-service/src/casebook/api/internal.py platforms/test-management-service/src/casebook/service/purge_service.py platforms/test-management-service/tests/integration/test_internal_purge.py docker-compose.yml
git commit -o platforms/test-management-service/src/casebook/core/config.py platforms/test-management-service/src/casebook/api/main.py platforms/test-management-service/src/casebook/api/internal.py platforms/test-management-service/src/casebook/service/purge_service.py platforms/test-management-service/tests/integration/test_internal_purge.py docker-compose.yml -m "feat(test-management): internal purge of one project's cases, suites, features, run requests and CI target" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: ingestion — uploads to a pending project are 410

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/utils/project_state.py`, `tests/integration/test_pending_uploads.py`
- Modify: `src/ingestion/api/key_auth.py`, `docker-compose.yml` (move `PROJECT_SERVICE_INTERNAL_URL` into `x-ingestion-env`)

**Interfaces:**
- Consumes: `retention.parse_internal_url`, `retention.fetch_policies`, `Policy.deleted` (existing).
- Produces: `project_state.is_pending(project_id: int) -> bool` (cached 60 s; fail open); `project_state.reset()` (tests); `get_api_key` raises 410 for a pending project.

- [ ] **Step 1: Write the failing tests** — create `tests/integration/test_pending_uploads.py`:

```python
"""A project pending deletion takes no uploads (spec 2026-10-16 §4); a restore lets the key in again."""
import httpx
import pytest

from src.ingestion.core.config import settings
from src.ingestion.models import Run
from src.ingestion.utils import project_state
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

INTERNAL = "http://ingestion-service:secret@project-service:8000"
FEED = "http://project-service:8000/internal/v1/projects/retention"


def row(project_id, deleted):
    return {"project_id": project_id, "result_retention_days": 90, "deleted": deleted,
            "deleted_at": "2026-10-16T10:00:00+00:00" if deleted else None, "legal_hold": False}


@pytest.fixture
def feed(http, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_SERVICE_INTERNAL_URL", INTERNAL)
    project_state.reset()

    def _answer(*rows, status_code=200):
        return http.get(FEED, name="feed").mock(return_value=httpx.Response(status_code, json={"projects": list(rows)}))
    yield _answer
    project_state.reset()


def test_an_upload_to_a_pending_project_is_410_and_stores_nothing(client, make_key, db, feed):
    feed(row(1, True))
    _, key = make_key(project_id=1)
    response = client.post(URL, json=upload_body(), headers=key_headers(key))
    assert response.status_code == 410
    assert response.json()["detail"] == "Project scheduled for deletion"
    assert db.query(Run).count() == 0


def test_a_live_project_uploads_as_before(client, make_key, feed):
    feed(row(1, False))
    _, key = make_key(project_id=1)
    assert client.post(URL, json=upload_body(), headers=key_headers(key)).status_code == 201


def test_after_restore_the_key_works_again(client, make_key, feed, monkeypatch):
    route = feed(row(1, True))
    _, key = make_key(project_id=1)
    assert client.post(URL, json=upload_body(), headers=key_headers(key)).status_code == 410
    route.mock(return_value=httpx.Response(200, json={"projects": [row(1, False)]}))
    project_state.reset()  # the cache's 60 s, elapsed
    assert client.post(URL, json=upload_body(), headers=key_headers(key)).status_code == 201


def test_project_service_unreachable_lets_uploads_through(client, make_key, http, monkeypatch):
    monkeypatch.setattr(settings, "PROJECT_SERVICE_INTERNAL_URL", INTERNAL)
    project_state.reset()
    http.get(FEED).mock(side_effect=httpx.ConnectError("refused"))
    _, key = make_key(project_id=1)
    assert client.post(URL, json=upload_body(), headers=key_headers(key)).status_code == 201
    project_state.reset()


def test_the_feed_is_read_once_a_minute(client, make_key, feed):
    route = feed(row(1, False))
    _, key = make_key(project_id=1)
    for _ in range(3):
        client.post(URL, json=upload_body(), headers=key_headers(key))
    assert route.call_count == 1
```

- [ ] **Step 2: Run them to verify they fail** — 201 where 410 is expected.

- [ ] **Step 3: Implement.**
  - `src/ingestion/utils/project_state.py`:

```python
"""Which projects are pending deletion (spec 2026-10-16 §4), read from project-service's internal feed and kept 60 s.
Uploads to them are refused. Fail open: without an answer, the last known one is used (none at first), so a
project-service outage never stops CI uploads."""
import threading
import time
from typing import FrozenSet, Optional

from src.ingestion.core.config import settings

TTL_SECONDS = 60.0
_lock = threading.Lock()
_pending: FrozenSet[int] = frozenset()
_read_at: Optional[float] = None


def reset() -> None:
    global _pending, _read_at
    with _lock:
        _pending, _read_at = frozenset(), None


def is_pending(project_id: int) -> bool:
    global _pending, _read_at
    if not settings.PROJECT_SERVICE_INTERNAL_URL:
        return False
    with _lock:
        fresh = _read_at is not None and time.monotonic() - _read_at < TTL_SECONDS
        if not fresh:
            from src.ingestion.jobs.retention import RetentionError, fetch_policies, parse_internal_url
            try:
                policies = fetch_policies(parse_internal_url(settings.PROJECT_SERVICE_INTERNAL_URL))
                _pending = frozenset(p.project_id for p in policies if p.deleted)
            except RetentionError:
                pass  # keep the last answer
            _read_at = time.monotonic()
        return project_id in _pending
```
  - `src/ingestion/api/key_auth.py`: `from src.ingestion.utils import project_state` and before `return key`:

```python
    if project_state.is_pending(key.project_id):
        # Not a 401: the key is fine, and a restore within the deletion window brings it back (spec 2026-10-16)
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Project scheduled for deletion")
```
  - `docker-compose.yml`: move the `PROJECT_SERVICE_INTERNAL_URL: …` line (with its comment) from the `ingestion-retention` service into the `x-ingestion-env` anchor, so ingestion-service reads the feed too.
  - Every existing ingestion test runs with `PROJECT_SERVICE_INTERNAL_URL` empty unless it sets it, so `is_pending` is False there; the retention tests set it and never upload. If a test that sets it does upload, call `project_state.reset()` in its fixture.

- [ ] **Step 4: Run the ingestion suite** (`tests/ -q`, about 11 minutes). Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/utils/project_state.py platforms/ingestion-service/src/ingestion/api/key_auth.py platforms/ingestion-service/tests/integration/test_pending_uploads.py docker-compose.yml
git commit -o platforms/ingestion-service/src/ingestion/utils/project_state.py platforms/ingestion-service/src/ingestion/api/key_auth.py platforms/ingestion-service/tests/integration/test_pending_uploads.py docker-compose.yml -m "feat(ingestion): uploads to a project pending deletion answer 410; keys keep working after a restore" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: ingestion — the purge after 7 days

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/jobs/purge.py`, `tests/integration/test_purge.py`
- Modify: `src/ingestion/core/config.py`, `src/ingestion/jobs/retention.py`, `tests/integration/test_retention_job.py`, `docker-compose.yml` (`TEST_MANAGEMENT_INTERNAL_URL` on `ingestion-retention`)

**Interfaces:**
- Consumes: project-service `POST …/purge-state`, `DELETE /internal/v1/projects/{id}` (Task 2); test-management `DELETE /internal/v1/projects/{id}` (Task 4).
- Produces (settings): `PROJECT_DELETE_GRACE_DAYS: int = 7` (replaces `RETENTION_DELETED_GRACE_DAYS`), `TEST_MANAGEMENT_INTERNAL_URL: str = ""`.
- Produces: `Policy.purge_state: Optional[dict]`; `Endpoint.base: str` (the URL without the feed path); `purge.purge_ingestion(db, project_id) -> int`; `purge.purge_project(db, policy, project_ep, tm_ep, now) -> list[str]` (steps done this pass; raises `retention.RetentionError` on a failed call); `run_pass` purges each `deleted` policy past the grace and no longer revokes keys during it; summary gains `"projects_purged"`.

- [ ] **Step 1: Write the failing tests** — create `tests/integration/test_purge.py`:

```python
"""The purge (spec 2026-10-16 §5): after the 7 days, test-management, then ingestion, then the project row."""
from datetime import timedelta

import httpx
import pytest

from src.ingestion.core.config import settings
from src.ingestion.models import ApiKey, CollectionSettings, LogPattern, MaskingPattern, Run
from tests.integration.test_retention_job import NOW, add_run, answer, gone, live, run_job, session_factory  # noqa: F401

TM_INTERNAL = "http://ingestion-service:p%40ss%3Aw%2Frd@test-management-service:8000"
TM_DELETE = "http://test-management-service:8000/internal/v1/projects/{pid}"
PS_STEP = "http://project-service:8000/internal/v1/projects/{pid}/purge-state"
PS_DELETE = "http://project-service:8000/internal/v1/projects/{pid}"


@pytest.fixture(autouse=True)
def tm_configured(monkeypatch):
    monkeypatch.setattr(settings, "TEST_MANAGEMENT_INTERNAL_URL", TM_INTERNAL)


@pytest.fixture
def services(http):
    def _routes(pid, tm_status=204, ps_delete_status=204):
        return {
            "tm": http.delete(TM_DELETE.format(pid=pid), name=f"tm-{pid}").mock(return_value=httpx.Response(tm_status)),
            "step": http.post(PS_STEP.format(pid=pid), name=f"step-{pid}").mock(return_value=httpx.Response(204)),
            "row": http.delete(PS_DELETE.format(pid=pid), name=f"row-{pid}").mock(
                return_value=httpx.Response(ps_delete_status)),
        }
    return _routes


def extras(db, project_id):
    db.add_all([CollectionSettings(project_id=project_id),
                LogPattern(project_id=project_id, name="trip_id", pattern="x"),
                MaskingPattern(project_id=project_id, name="secret", pattern="x", created_by=1)])
    db.commit()


def test_a_project_past_the_grace_is_purged_everywhere_in_order(db, session_factory, answer, add_run, services):
    keep = add_run(2, 1)
    add_run(1, 1)
    extras(db, 1)
    answer([gone(1, days_ago=8), live(2, 90)])
    routes = services(1)
    assert run_job(session_factory) == 0
    order = [call.request.url.path for call in routes["tm"].calls + routes["step"].calls + routes["row"].calls]
    assert routes["tm"].call_count == 1 and routes["row"].call_count == 1
    steps = [call.request.read() for call in routes["step"].calls]
    assert steps == [b'{"step":"started"}', b'{"step":"test_management"}', b'{"step":"ingestion"}']
    db.expire_all()
    assert [r.id for r in db.query(Run)] == [keep]
    for model in (ApiKey, CollectionSettings, LogPattern, MaskingPattern):
        assert db.query(model).filter(model.project_id == 1).count() == 0
    assert db.query(ApiKey).filter(ApiKey.project_id == 2).count() == 1
    assert order  # every call went to the expected hosts


def test_within_the_grace_nothing_is_deleted_and_keys_stay(db, session_factory, answer, add_run, services):
    add_run(1, 40)
    answer([gone(1, days_ago=6, days=30)])
    routes = services(1)
    assert run_job(session_factory) == 0
    assert routes["tm"].call_count == 0
    db.expire_all()
    assert db.query(Run).count() == 1  # pending: not even the usual retention, it can be restored as it was
    assert db.query(ApiKey).filter(ApiKey.revoked_at.isnot(None)).count() == 0


def test_a_failed_test_management_step_leaves_it_for_the_next_pass(db, session_factory, answer, add_run, services):
    add_run(1, 1)
    answer([gone(1, days_ago=8)])
    routes = services(1, tm_status=503)
    assert run_job(session_factory) == 1  # the pass reports the failure
    assert [call.request.read() for call in routes["step"].calls] == [b'{"step":"started"}']
    assert routes["row"].call_count == 0
    db.expire_all()
    assert db.query(Run).count() == 1


def test_a_recorded_step_is_not_redone(db, session_factory, answer, add_run, services):
    add_run(1, 1)
    row = gone(1, days_ago=8)
    row["purge_state"] = {"started": "2026-10-09T03:00:00+00:00", "test_management": "2026-10-09T03:00:00+00:00"}
    answer([row])
    routes = services(1)
    assert run_job(session_factory) == 0
    assert routes["tm"].call_count == 0
    assert [call.request.read() for call in routes["step"].calls] == [b'{"step":"ingestion"}']
    assert routes["row"].call_count == 1


def test_a_restored_project_is_never_purged(db, session_factory, answer, add_run, services):
    add_run(1, 1)
    answer([live(1, 90)])
    routes = services(1)
    assert run_job(session_factory) == 0
    assert routes["tm"].call_count == 0 and routes["row"].call_count == 0
    db.expire_all()
    assert db.query(Run).count() == 1


def test_a_project_restored_after_the_feed_was_read_is_left_alone(db, session_factory, answer, add_run, http):
    add_run(1, 1)
    answer([gone(1, days_ago=8)])
    tm = http.delete(TM_DELETE.format(pid=1)).mock(return_value=httpx.Response(204))
    http.post(PS_STEP.format(pid=1)).mock(
        return_value=httpx.Response(409, json={"detail": "Project is not pending deletion"}))
    assert run_job(session_factory) == 0  # restored meanwhile: not a failure
    assert tm.call_count == 0
    db.expire_all()
    assert db.query(Run).count() == 1


def test_a_pending_project_on_legal_hold_is_not_purged(db, session_factory, answer, add_run, services):
    add_run(1, 1)
    row = gone(1, days_ago=8)
    row["legal_hold"] = True
    answer([row])
    routes = services(1)
    assert run_job(session_factory) == 0
    assert routes["tm"].call_count == 0
```
  In `tests/integration/test_retention_job.py`: `test_a_deleted_projects_runs_are_deleted_and_its_keys_revoked` and `test_a_recently_deleted_project_keeps_its_runs_for_the_grace_period` describe the old behaviour (keys revoked at once). Replace the first with a test that a deleted project within the grace keeps its runs and keys, and adapt the second's grace to 7 days with `PROJECT_DELETE_GRACE_DAYS`; delete nothing else. Ledger the two changes.

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Implement.**
  - `config.py`: replace the `RETENTION_DELETED_GRACE_DAYS` lines with

```python
    # A deleted project waits this long, restorable, before the retention job purges it everywhere (spec 2026-10-16)
    PROJECT_DELETE_GRACE_DAYS: int = 7
    # test-management's internal API for the purge, with HTTP Basic credentials: http://user:password@host:port
    TEST_MANAGEMENT_INTERNAL_URL: str = ""
```
  - `retention.py`:
    - `Policy`: add `purge_state: Optional[dict] = None`; `_policy`: `purge_state=item.get("purge_state") if isinstance(item.get("purge_state"), dict) else None,`.
    - `Endpoint`: add `base: str = ""` as the last field; `parse_internal_url` sets `base=urlunsplit((parts.scheme, host, path, "", ""))`; give it an optional `name` parameter (default `"PROJECT_SERVICE_INTERNAL_URL"`) used in the problem message.
    - `run_pass(db, policies, now, *, batch_size, dry_run, grace_days=7, purge=None)`: replace the loop body's deleted-project branch so that a `deleted` policy within the grace is skipped entirely (no runs deleted, no keys revoked), and one past the grace (and not on legal hold) is handed to `purge(policy)` when `purge` is given (not in dry run; a dry run counts it in `projects_purged` only). Live projects keep today's retention exactly. Return `projects_purged` in the summary.
    - `run_once`: build `tm = parse_internal_url(settings.TEST_MANAGEMENT_INTERNAL_URL, name="TEST_MANAGEMENT_INTERNAL_URL")` only when it is set; pass `grace_days=settings.PROJECT_DELETE_GRACE_DAYS` and `purge=lambda p: purge_project(db, p, endpoint, tm, now())` (from `src.ingestion.jobs.purge`). Without `TEST_MANAGEMENT_INTERNAL_URL`, pending projects past the grace are logged `{"event": "purge_skipped", "reason": "TEST_MANAGEMENT_INTERNAL_URL is not set"}` and left alone.
  - `src/ingestion/jobs/purge.py`:

```python
"""Purge a project whose deletion window is over (spec 2026-10-16 §5): test-management, then ingestion, then the
project row in project-service, each step idempotent and recorded there, so a pass that fails resumes next time."""
from datetime import datetime
from typing import List

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ingestion.jobs.retention import TIMEOUT_SECONDS, Endpoint, Policy, RetentionError, _delete_in_batches
from src.ingestion.models import (
    ApiKey, CollectionSettings, FlakyDaily, FlakyRollupDay, ImpactPair, ImpactTestBase, LogPattern, LogValue,
    MaskingPattern, MutedTest, NotificationChannel, Run,
)

PER_PROJECT = (ApiKey, CollectionSettings, FlakyDaily, FlakyRollupDay, ImpactPair, ImpactTestBase, MaskingPattern,
               MutedTest, NotificationChannel)


def purge_ingestion(db: Session, project_id: int, batch_size: int = 500) -> int:
    """Every run (results, log values, children) and every per-project row of ingestion. Returns runs deleted."""
    runs = _delete_in_batches(db, db.query(Run.id).filter(Run.project_id == project_id), batch_size)
    patterns = select(LogPattern.id).where(LogPattern.project_id == project_id)
    db.query(LogValue).filter(LogValue.pattern_id.in_(patterns)).delete(synchronize_session=False)
    db.query(LogPattern).filter(LogPattern.project_id == project_id).delete(synchronize_session=False)
    for model in PER_PROJECT:
        db.query(model).filter(model.project_id == project_id).delete(synchronize_session=False)
    db.commit()
    return runs


def _call(method: str, endpoint: Endpoint, path: str, **kwargs) -> int:
    try:
        response = httpx.request(method, endpoint.base + path, auth=(endpoint.username, endpoint.password),
                                 timeout=TIMEOUT_SECONDS, **kwargs)
    except httpx.HTTPError as exc:
        raise RetentionError(f"cannot reach {endpoint.display}: {type(exc).__name__}") from None
    return response.status_code


class Restored(Exception):
    """project-service refused "started": the project was restored after the feed was read."""


def _record(project: Endpoint, project_id: int, step: str) -> None:
    status = _call("POST", project, f"/internal/v1/projects/{project_id}/purge-state", json={"step": step})
    if status == 409 and step == "started":
        raise Restored()
    if status != 204:
        raise RetentionError(f"{project.display} refused purge step {step} for project {project_id}: {status}")


def purge_project(db: Session, policy: Policy, project: Endpoint, tm: Endpoint, now: datetime) -> List[str]:
    """The steps done this pass; [] when the project was restored meanwhile (nothing touched)."""
    done = dict(policy.purge_state or {})
    steps: List[str] = []
    pid = policy.project_id
    if "started" not in done:
        try:
            _record(project, pid, "started")  # atomic: refused for a live project; blocks any later restore
        except Restored:
            return []
        steps.append("started")
    if "test_management" not in done:
        status = _call("DELETE", tm, f"/internal/v1/projects/{pid}")
        if status != 204:
            raise RetentionError(f"{tm.display} refused to purge project {pid}: {status}")
        _record(project, pid, "test_management")
        steps.append("test_management")
    if "ingestion" not in done:
        purge_ingestion(db, pid)
        _record(project, pid, "ingestion")
        steps.append("ingestion")
    status = _call("DELETE", project, f"/internal/v1/projects/{pid}")
    if status != 204:
        # 409: restored meanwhile (the row is live again) or a step not recorded; the next pass sees it
        raise RetentionError(f"{project.display} refused to delete project {pid}: {status}")
    steps.append("project")
    return steps
```
    In `run_pass`, a `RetentionError` from one project's purge is logged (`{"event": "purge_failed", "project_id", "error"}`) and makes the pass report failure (`run_once` returns False after finishing the other projects), so the heartbeat shows it. Each successful purge logs `{"event": "project_purged", "project_id", "steps"}`; an empty result logs `{"event": "purge_skipped", "project_id", "reason": "restored"}` and is not a failure.
  - `docker-compose.yml`, `ingestion-retention` environment: `      # test-management's internal API for the purge of deleted projects (spec 2026-10-16)\n      TEST_MANAGEMENT_INTERNAL_URL: http://ingestion-service:${INTERNAL_API_PASSWORD:?…}@test-management-service:8000`, and add `test-management-service: condition: service_healthy` to its `depends_on`.

- [ ] **Step 4: Run the ingestion suite.** Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/core/config.py platforms/ingestion-service/src/ingestion/jobs/retention.py platforms/ingestion-service/src/ingestion/jobs/purge.py platforms/ingestion-service/tests/integration/test_purge.py platforms/ingestion-service/tests/integration/test_retention_job.py docker-compose.yml
git commit -o platforms/ingestion-service/src/ingestion/core/config.py platforms/ingestion-service/src/ingestion/jobs/retention.py platforms/ingestion-service/src/ingestion/jobs/purge.py platforms/ingestion-service/tests/integration/test_purge.py platforms/ingestion-service/tests/integration/test_retention_job.py docker-compose.yml -m "feat(ingestion): purge a deleted project everywhere after 7 days, in order, resumable; nothing changes during the window" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: dashboard — the delete dialog in Settings → Data

**Files:**
- Modify: `dashboard/src/api/orgs.ts`
- Create: `dashboard/src/components/DeleteProjectDialog.tsx`, `dashboard/src/components/DeleteProjectDialog.test.tsx`
- Modify: `dashboard/src/components/DataCard.tsx`, `dashboard/src/index.css`

**Interfaces:**
- Produces (in `api/orgs.ts`): `interface Deletion { deleted_at: string; deleted_by: number | null; purge_at: string }`; `Project.deletion?: Deletion | null`; `deleteProject(projectId)`, `restoreProject(projectId): Promise<Project>`, `listProjects(orgId, { includePending?: boolean })`; `formatPurgeDate(iso): string` ("23 Oct 2026, 14:05", local time).
- Produces: `DeleteProjectDialog({ project, onDeleted })`.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill** (destructive confirmation: typed name, danger button, focus).

- [ ] **Step 1: Write the failing tests** — create `DeleteProjectDialog.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import DeleteProjectDialog from "./DeleteProjectDialog";

const PROJECT = { id: 42, name: "Web Checkout", organization_id: 1, my_role: "owner", legal_hold: null };

function renderDialog(project: object = PROJECT, onDeleted = vi.fn()) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><DeleteProjectDialog project={project as never} onDeleted={onDeleted} /></QueryClientProvider>);
  return onDeleted;
}

test("the danger button opens a dialog that says what goes and when", async () => {
  renderDialog();
  await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
  const dialog = screen.getByRole("dialog", { name: "Delete Web Checkout?" });
  expect(dialog).toHaveTextContent(/runs, results, logs, test cases, suites, API keys and settings/);
  expect(dialog).toHaveTextContent(/7 days/);
  expect(dialog).toHaveTextContent(/any owner or admin can restore it/i);
  expect(screen.getByLabelText(/type the project name/i)).toHaveFocus();
});

test("Delete stays disabled until the name is typed exactly, then deletes", async () => {
  let deleted = false;
  server.use(http.delete("/api/v1/projects/42", () => { deleted = true; return new HttpResponse(null, { status: 204 }); }));
  const onDeleted = renderDialog();
  await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
  const confirm = screen.getByRole("button", { name: "Delete permanently in 7 days" });
  expect(confirm).toBeDisabled();
  await userEvent.type(screen.getByLabelText(/type the project name/i), "web checkout");
  expect(confirm).toBeDisabled();  // case matters
  await userEvent.clear(screen.getByLabelText(/type the project name/i));
  await userEvent.type(screen.getByLabelText(/type the project name/i), "Web Checkout");
  expect(confirm).toBeEnabled();
  await userEvent.click(confirm);
  await vi.waitFor(() => expect(onDeleted).toHaveBeenCalled());
  expect(deleted).toBe(true);
});

test("Escape and Cancel close it without deleting, focus back on the button", async () => {
  renderDialog();
  const open = screen.getByRole("button", { name: "Delete project" });
  await userEvent.click(open);
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(open).toHaveFocus();
});

test("under a legal hold the button is disabled with the reason", () => {
  renderDialog({ ...PROJECT, legal_hold: { since: "2026-10-01T00:00:00Z", by: 1, reason: "audit" } });
  expect(screen.getByRole("button", { name: "Delete project" })).toBeDisabled();
  expect(screen.getByText("Release the legal hold before deleting this project.")).toBeInTheDocument();
});

test("a refusal from the server is shown in the dialog", async () => {
  server.use(http.delete("/api/v1/projects/42", () => HttpResponse.json(
    { detail: "Release the legal hold before deleting this project" }, { status: 409 })));
  renderDialog();
  await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
  await userEvent.type(screen.getByLabelText(/type the project name/i), "Web Checkout");
  await userEvent.click(screen.getByRole("button", { name: "Delete permanently in 7 days" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Release the legal hold");
});
```

- [ ] **Step 2: Run them to verify they fail** (`./DeleteProjectDialog` does not resolve).

- [ ] **Step 3: Implement.**
  - `api/orgs.ts`: add the `Deletion` interface, `deletion?: Deletion | null;` on `Project`, and

```ts
export function listProjects(orgId: number, opts: { includePending?: boolean } = {}): Promise<Project[]> {
  return apiFetch(`/api/v1/organizations/${orgId}/projects${opts.includePending ? "?include_pending=true" : ""}`);
}

/** Pending deletion for PROJECT_DELETE_GRACE_DAYS (7), restorable by owners and admins, then purged everywhere. */
export function deleteProject(projectId: number): Promise<void> {
  return apiFetch(`/api/v1/projects/${projectId}`, { method: "DELETE" });
}

export function restoreProject(projectId: number): Promise<Project> {
  return apiFetch(`/api/v1/projects/${projectId}/restore`, { method: "POST" });
}

/** "23 Oct 2026, 14:05" in the reader's time zone. */
export function formatPurgeDate(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    .format(new Date(iso));
}
```
  - `components/DeleteProjectDialog.tsx`:

```tsx
import { FormEvent, useId, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { Project, deleteProject } from "../api/orgs";
import ErrorBanner from "./ErrorBanner";

/** Settings → Data's danger zone (spec 2026-10-16): a native <dialog> that says what is deleted and when, offers the
 *  export first, and needs the project name typed exactly before the danger button works. */
export default function DeleteProjectDialog({ project, onDeleted }: { project: Project; onDeleted: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const openRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const [typed, setTyped] = useState("");
  const remove = useMutation({ mutationFn: () => deleteProject(project.id), onSuccess: onDeleted });
  const held = project.legal_hold != null;
  const matches = typed.trim() === project.name;

  function open() {
    setTyped("");
    remove.reset();
    dialogRef.current?.showModal();
  }
  function close() {
    dialogRef.current?.close();
  }
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (matches) remove.mutate();
  }

  return (
    <div className="danger-zone">
      <h3>Delete this project</h3>
      <p className="muted">
        The project is hidden at once and deleted permanently 7 days later, everywhere. Until then any owner or admin
        can restore it from the project list.
      </p>
      <button ref={openRef} type="button" className="danger" onClick={open} disabled={held}>
        <Trash2 size={15} aria-hidden="true" /> Delete project
      </button>
      {held && <p className="muted">Release the legal hold before deleting this project.</p>}
      <dialog ref={dialogRef} className="confirm-dialog" aria-labelledby={titleId}
        onClose={() => openRef.current?.focus()}>
        <form method="dialog" onSubmit={onSubmit}>
          <h2 id={titleId}>Delete {project.name}?</h2>
          <p>
            Its runs, results, logs, test cases, suites, API keys and settings are deleted permanently in 7 days.
            Until then any owner or admin can restore it.
          </p>
          <p className="muted">Want a copy? Use <strong>Download all results</strong> above before deleting.</p>
          <label>
            Type the project name to confirm
            <input autoFocus autoComplete="off" spellCheck={false} value={typed} onChange={(e) => setTyped(e.target.value)}
              placeholder={project.name} />
          </label>
          {remove.error != null && <ErrorBanner error={remove.error} />}
          <div className="button-row">
            <button type="button" onClick={close}>Cancel</button>
            <button type="submit" className="danger" disabled={!matches || remove.isPending}>
              {remove.isPending ? "Deleting…" : "Delete permanently in 7 days"}
            </button>
          </div>
        </form>
      </dialog>
    </div>
  );
}
```
  (jsdom lacks `showModal`/`close`: if the tests fail on it, add to `src/test/setup.ts` a polyfill `HTMLDialogElement.prototype.showModal = function () { this.open = true; }` and `close = function () { this.open = false; this.dispatchEvent(new Event("close")); }` guarded by `if (!HTMLDialogElement.prototype.showModal)`; Escape: handle `onKeyDown` on the dialog closing it when the polyfill is active. Check first whether the project already has such a polyfill: `grep -rn showModal dashboard/src/test`.)
  - `DataCard.tsx`: add `onDeleted?: () => void` to `Props` and, inside the `canManage` branch after the export row: `<DeleteProjectDialog project={project} onDeleted={onDeleted ?? (() => {})} />`. In `ProjectSettingsPage.tsx`, pass `onDeleted={() => navigate("/")}` (import `useNavigate`; `/` is the picker) and invalidate `["projects", orgId]`.
  - `index.css`: `.danger-zone { margin-top: var(--space-5); padding-top: var(--space-4); border-top: 1px solid var(--border); }` and `.confirm-dialog { max-width: 520px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-5); background: var(--surface-1); color: var(--text-primary); }` `.confirm-dialog::backdrop { background: rgb(0 0 0 / 0.45); }` `.confirm-dialog label { display: flex; flex-direction: column; gap: var(--space-1); margin: var(--space-3) 0; }` (reuse existing tokens; check names in `index.css`).

- [ ] **Step 4: Run** `npx vitest run src/components/DeleteProjectDialog.test.tsx src/pages/ProjectSettingsPage.test.tsx`, `npm run lint`, `npm run typecheck`. Expected: PASS.

- [ ] **Step 5: Commit** the five files (plus `src/test/setup.ts` if the polyfill was added) with `feat(dashboard): delete a project from Settings after typing its name; 7 days to restore`.

---

### Task 8: dashboard — greyed pending projects with Restore; the notice page

**Files:**
- Modify: `dashboard/src/pages/PickerPage.tsx`, `dashboard/src/pages/ProjectLayout.tsx`, `dashboard/src/index.css`
- Create: `dashboard/src/components/PendingDeletion.tsx`, `dashboard/src/components/PendingDeletion.test.tsx`
- Test: `dashboard/src/pages/PickerPage.test.tsx` (append)

**Interfaces:**
- Consumes: `listProjects(orgId, { includePending })`, `restoreProject`, `formatPurgeDate`, `Project.deletion` (Task 7); `listMembers(orgId)` (existing, for the deleter's email).
- Produces: `PendingDeletion({ projectId, info, canRestore })` where `info` is the 410 body's detail.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill** (disabled-looking but operable row, status badge, restore action).

- [ ] **Step 1: Write the failing tests.** Append to `PickerPage.test.tsx` (reuse its render helper and org mocks; read the file first):

```tsx
test("owners and admins see a pending project greyed with the purge date and Restore", async () => {
  server.use(
    http.get("/api/v1/organizations/1/projects", ({ request }) => {
      const pending = new URL(request.url).searchParams.get("include_pending") === "true";
      return HttpResponse.json([
        { id: 1, name: "Live" },
        ...(pending ? [{ id: 2, name: "Old", deletion: { deleted_at: "2026-10-16T13:05:00Z", deleted_by: 9, purge_at: "2026-10-23T13:05:00Z" } }] : []),
      ]);
    }),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([{ id: 1, organization_id: 1, user_id: 9, email: "ana@example.com", role: "admin", status: "active", created_at: "x", updated_at: null }])),
    http.post("/api/v1/projects/2/restore", () => HttpResponse.json({ id: 2, name: "Old", deletion: null })),
  );
  renderPicker({ role: "owner" });
  const row = await screen.findByRole("group", { name: "Old, deletion pending" });
  expect(row).toHaveTextContent(/removed on 23 Oct 2026/);
  expect(row).toHaveTextContent(/deleted by ana@example.com/);
  expect(within(row).queryByRole("link")).toBeNull();
  await userEvent.click(within(row).getByRole("button", { name: "Restore Old" }));
  await vi.waitFor(() => expect(screen.queryByRole("group", { name: "Old, deletion pending" })).toBeNull());
});

test("members never ask for pending projects", async () => {
  const asked: string[] = [];
  server.use(http.get("/api/v1/organizations/1/projects", ({ request }) => { asked.push(request.url); return HttpResponse.json([{ id: 1, name: "Live" }]); }));
  renderPicker({ role: "member" });
  await screen.findByRole("link", { name: /Live/ });
  expect(asked.every((u) => !u.includes("include_pending"))).toBe(true);
});
```
  (adapt `renderPicker({ role })` to the file's helper: the org's role comes from `listMyOrganizations`.)
  Create `PendingDeletion.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import PendingDeletion from "./PendingDeletion";

const INFO = { code: "pending_deletion", message: "x", organization_id: 1, deleted_at: "2026-10-16T13:05:00Z", deleted_by: 9, purge_at: "2026-10-23T13:05:00Z" };

function renderIt(canRestore: boolean) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><PendingDeletion projectId={42} info={INFO} canRestore={canRestore} /></MemoryRouter></QueryClientProvider>);
}

test("a member sees the deletion notice", () => {
  renderIt(false);
  expect(screen.getByRole("heading", { name: "This project is scheduled for deletion" })).toBeInTheDocument();
  expect(screen.getByText(/23 Oct 2026/)).toBeInTheDocument();
  expect(screen.getByText(/ask an owner or admin if this is a mistake/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /restore/i })).toBeNull();
});

test("an owner can restore from the notice", async () => {
  let restored = false;
  server.use(http.post("/api/v1/projects/42/restore", () => { restored = true; return HttpResponse.json({ id: 42, name: "Web", deletion: null }); }));
  renderIt(true);
  await userEvent.click(screen.getByRole("button", { name: "Restore project" }));
  await vi.waitFor(() => expect(restored).toBe(true));
});
```

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Implement.**
  - `PickerPage.tsx` (`OrgProjects`): `const projects = useQuery({ queryKey: ["projects", org.id, canCreate], queryFn: () => listProjects(org.id, { includePending: canCreate }) });` (move `canCreate` above it; `canCreate` is the owners/admins test already). Add `const members = useQuery({ queryKey: ["members", org.id], queryFn: () => listMembers(org.id), enabled: canCreate && (projects.data ?? []).some((p) => p.deletion) });` and a `restore` mutation (`restoreProject`, then invalidate `["projects", org.id]`). Render live projects as today; render each pending one as:

```tsx
<div key={project.id} className="project-tile is-pending" role="group" aria-label={`${project.name}, deletion pending`}>
  <span className="project-tile-name"><FolderKanban size={18} aria-hidden="true" /> {project.name}</span>
  <span className="badge badge-muted">
    {`Deletion pending · removed on ${formatPurgeDate(project.deletion!.purge_at)}`}
    {deleter(project) && ` · deleted by ${deleter(project)}`}
  </span>
  <button type="button" onClick={() => restore.mutate(project.id)} disabled={restore.isPending}
    aria-label={`Restore ${project.name}`}>Restore</button>
</div>
```
    where `deleter = (p) => members.data?.find((m) => m.user_id === p.deletion?.deleted_by)?.email ?? null`. Show `restore.error` with `ErrorBanner` (a 409 name clash reads its message).
  - `components/PendingDeletion.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { formatPurgeDate, restoreProject } from "../api/orgs";
import ErrorBanner from "./ErrorBanner";

export interface PendingInfo { code: string; message: string; organization_id: number; deleted_at: string; deleted_by: number | null; purge_at: string }

/** What a pending project's URLs show (spec 2026-10-16): when it goes, and Restore for owners and admins. */
export default function PendingDeletion({ projectId, info, canRestore }: { projectId: number; info: PendingInfo; canRestore: boolean }) {
  const qc = useQueryClient();
  const restore = useMutation({
    mutationFn: () => restoreProject(projectId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["project", projectId] }),
  });
  return (
    <div className="card pending-deletion" role="region" aria-labelledby="pending-title">
      <h1 id="pending-title">This project is scheduled for deletion</h1>
      <p>It will be deleted permanently on <strong>{formatPurgeDate(info.purge_at)}</strong>, with everything in it.</p>
      {canRestore ? (
        <button type="button" className="primary" onClick={() => restore.mutate()} disabled={restore.isPending}>
          {restore.isPending ? "Restoring…" : "Restore project"}
        </button>
      ) : (
        <p className="muted">Ask an owner or admin if this is a mistake.</p>
      )}
      {restore.error != null && <ErrorBanner error={restore.error} />}
    </div>
  );
}
```
  - `ProjectLayout.tsx`: when `project.error instanceof ApiError && project.error.status === 410`, render `<PendingDeletion projectId={id} info={project.error.body.detail} canRestore={…} />` instead of `<Outlet />`. `canRestore`: the caller's org role, from `myRole(info's org)`. The 410 detail carries `organization_id` (Task 1): query the caller's role in that organization the way the dashboard already does elsewhere (`grep -rn "my_role\|myRole" dashboard/src` and reuse that query), and pass `canRestore` true for `owner` and `admin`. Set `retry: (count, err) => !(err instanceof ApiError && err.status === 410) && count < 3` on the project query.
  - `index.css`: `.project-tile.is-pending { opacity: 0.72; background: var(--surface-2); flex-wrap: wrap; gap: var(--space-2); }` `.project-tile.is-pending .project-tile-name { color: var(--text-secondary); }` `.pending-deletion { max-width: 640px; }` (the opacity keeps the badge and button above 4.5:1; check with the contrast tool already in `src/lib/contrast.test.ts` style if the tokens are close).

- [ ] **Step 4: Run** the touched tests, lint, typecheck, build. Expected: PASS.

- [ ] **Step 5: Commit** with `feat(dashboard): pending projects greyed with Restore for owners and admins; members see the deletion notice`.

---

### Task 9: Docs, ADR-033, smoke, gate

**Files:** `docs/architecture/adr/ADR-033-project-deletion.md` (new), `docs/architecture/adr/INDEX.md`, `docs/SETUP.md` (§4.7), `SECURITY.md`, `PRODUCT.md`, `TECHNICAL_SPECIFICATION.md`, `DESIGN.md`, `platforms/project-service/README.md`, `platforms/ingestion-service/README.md`, `platforms/test-management-service/README.md`, `.env.example`, `scripts/smoke_gateway.sh`.

- [ ] **Step 1: ADR-033** — `docs/architecture/adr/ADR-033-project-deletion.md`:

```markdown
# ADR-033: Project deletion — 7 days pending and restorable, then purged in every service

Status: Accepted (2026-10-16) · Spec: `docs/superpowers/specs/2026-10-16-project-deletion-design.md`

## Context
Projects could be soft-deleted through the API only; there was no confirmation, no restore, and the purge emptied
ingestion runs but left test-management data and the project row behind for ever.

## Decision
- Owners and admins delete a project from Settings after typing its name. project-service records `deleted_at` and
  `deleted_by`; for `PROJECT_DELETE_GRACE_DAYS` (7) the project is pending: hidden from members (who get a notice
  with the purge date on its URLs, a 410 for every other service read as not found), listed greyed with Restore for
  owners and admins (`include_pending`), restorable as it was (keys included). Uploads answer 410.
- A legal hold blocks deletion.
- After the window the ingestion retention job purges it: test-management (internal delete), ingestion (every
  per-project table), then the project row; each step is idempotent and recorded in `projects.purge_state`, and the
  row goes last, only after both others confirmed, so a failed pass resumes.

## Consequences
- Deleting is reversible for 7 days and final after; the export is offered before deleting.
- A name freed by a pending project can be taken; restoring it then asks to rename the new one first (409).
- `RETENTION_DELETED_GRACE_DAYS` is replaced by `PROJECT_DELETE_GRACE_DAYS`; `TEST_MANAGEMENT_INTERNAL_URL` is new.
```
  Add the INDEX row after ADR-032.

- [ ] **Step 2: SETUP §4.7** — replace "When a project is deleted, its API keys are revoked on the next retention pass, and its runs are deleted 7 days later. Until then, the deletion can still be undone." with:

```markdown
**Deleting a project.** Settings → **Data** → **Delete project** (owners and admins): type the project name to
confirm. The project disappears for members at once and waits **7 days** (`PROJECT_DELETE_GRACE_DAYS`): owners and
admins still see it in the project list, greyed, with **Restore**, which brings everything back as it was, API keys
included. Uploads to it answer 410 meanwhile. After the 7 days the retention job deletes it everywhere (runs, results,
logs, test cases, suites, keys, settings and the project itself). A project on legal hold cannot be deleted.
```
  and in the env table, replace `RETENTION_DELETED_GRACE_DAYS` with `PROJECT_DELETE_GRACE_DAYS` and add `TEST_MANAGEMENT_INTERNAL_URL` (set by compose).

- [ ] **Step 3: The rest.** SECURITY (Data deletion: confirmed by name, 7 days, purge everywhere, internal endpoints behind HTTP Basic, never routed by the gateway), PRODUCT (capability line), TECHNICAL_SPECIFICATION (endpoints, states, settings), DESIGN (§Data card danger zone and dialog; picker pending tile; notice page), the three service READMEs (their new endpoints/settings), `.env.example` (`PROJECT_DELETE_GRACE_DAYS=7` commented).

- [ ] **Step 4: Smoke** — in `scripts/smoke_gateway.sh`, after the project is created and before it is used elsewhere, create a throwaway project `smoke-delete`, `DELETE` it (204), `GET` it (410, body has `"pending_deletion"`), list with `include_pending=true` (body has `smoke-delete`), `POST …/restore` (200), `GET` it (200). Run `bash -n scripts/smoke_gateway.sh`.

- [ ] **Step 5: Gate.** project-service, test-management, ingestion full suites; dashboard lint, typecheck, build, `npx vitest run --no-file-parallelism`; `python scripts/check_architecture_docs.py`; `bash -n scripts/smoke_gateway.sh`; migration 005 on PostgreSQL done in Task 1.

- [ ] **Step 6: Commit** the docs and smoke with `docs: project deletion (ADR-033) — confirm, 7 days to restore, purge everywhere; smoke`.

---

## Spec coverage (self-review)

| Spec | Task |
|---|---|
| §2 states, `PROJECT_DELETE_GRACE_DAYS` | 1, 6 |
| §3 migration, delete with `deleted_by`, legal hold 409, restore, `include_pending`, 410 for members, other routes 404 | 1 |
| §3 other services treat it as not found | 3 |
| §4 uploads 410, keys kept, cache 60 s | 5, 6 |
| §5 purge order, idempotent, `purge_state`, resume, restore race, internal endpoints | 2, 4, 6 |
| §6 dialog, navigation, greyed rows with Restore, notice page, picker | 7, 8 |
| §7 tests, smoke | each task, 9 |
| §8 docs | 9 |

Decisions this plan takes where the spec is silent or a detail does not fit the code:
- `deleted_by_name` is not sent by project-service (organization-service knows emails, not names): the dashboard shows the deleter's email from the members list it already reads.
- A second `DELETE` of a pending project, and placing a legal hold on one, answer 404 like every other route of a pending project (the spec said 204 and 409): one rule for all routes, and both actions are meaningless on a pending project.
- The 410 body carries `organization_id` so the notice page can ask the caller's role for the Restore button.
- Uploads fail open when project-service cannot be read; the purge uses the same feed and never acts without it.
- Members get no pending projects even with `include_pending=true` (silently, not 403), so one dashboard query works for every role.
- The spec's "re-read `deleted_at` before step 1 and before step 3" becomes a `started` step recorded in project-service before step 1: one atomic check instead of two reads with a window between them. Cost: once the purge has started (the 7 days are over) the project can no longer be restored, which matches the date shown to users.
