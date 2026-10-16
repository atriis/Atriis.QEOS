# Entra App Roles to Organization Roles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Microsoft sign-in gives the person the organization role their Entra app roles map to, and keeps Entra-managed memberships in step at every sign-in.

**Architecture:** organization-service owns a per-organization mapping table (app role value → admin/member/viewer) and a `managed_by` flag on members, and applies the reconcile rules in one transaction behind a new HTTP Basic internal endpoint. auth-service reads the `roles` claim of the Microsoft ID token, stores it on the Microsoft link, pushes it to that endpoint after sign-in and after linking, and retries on token refresh while a push is pending. The dashboard gets a "Microsoft roles" card for owners and an "Entra" badge on managed members.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, httpx, pytest (+ respx in organization-service); React 19 + TypeScript, TanStack Query, vitest + msw.

**Spec:** `docs/superpowers/specs/2026-10-16-entra-app-roles-design.md` (binding).

## Global Constraints

- Mapped roles are exactly `admin`, `member`, `viewer`. `owner` and `billing_manager` are refused (422) by the mapping API and never offered in the dashboard select.
- Precedence when several mappings match: `admin` > `member` > `viewer`.
- `app_role`: 1-100 characters after strip; compared case-insensitively; unique per organization case-insensitively.
- Token roles: at most 50 values kept (the rest dropped with one WARNING), each cut to 100 characters; non-strings and blanks dropped; absent or non-list `roles` means `[]`.
- `organization_members.managed_by`: NULL or `entra`. Hand-made rows (NULL) are never touched by the reconcile.
- Organizations with no mapping, and soft-deleted organizations (`deleted_at` set), are never touched.
- Internal endpoint `POST /internal/v1/sso-roles` on organization-service, HTTP Basic, username `auth-service`, password `INTERNAL_API_PASSWORD`; empty password → 503; wrong → 401; never routed by the gateway; `include_in_schema=False`.
- auth-service settings: `ORGANIZATION_SERVICE_URL` (default `http://organization-service:8000`), `ORGANIZATION_INTERNAL_API_PASSWORD` (default empty: push skipped, one WARNING at start-up `Entra app roles are not applied: ORGANIZATION_INTERNAL_API_PASSWORD is not set`). Push timeout 5 s.
- A failed push never fails sign-in, linking or refresh.
- Log line on organization-service per change, INFO: `entra role: org=<id> user=<id> <created|updated|removed> <old>-><new> roles=<matched values>`; on auth-service, WARNING `entra role sync deferred: user=<id> reason=<...>`.
- 409 body for removing a managed member: `{"detail": {"code": "managed_by_entra", "message": "Managed by Entra: remove the app role instead."}}`. 409 body for a duplicate mapping: `{"detail": {"code": "duplicate_app_role", "message": "This app role is already mapped."}}`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Every behaviour commit updates the docs it affects in the same commit.
- UI tasks: invoke the `ui-ux-pro-max` skill before editing dashboard UI; existing CSS tokens and classes only.
- Never write the employer's name in code, tests or examples beyond what the repo already contains; use `example.com`, `QEOS.Member` style values.

## Rulings where the spec is silent or inexact

- **R1 Refresh route.** The spec says `POST /auth/refresh`; the real route is `POST /api/v1/auth/refresh-token` (`refresh_access_token` in `src/auth/api/v1/endpoints/auth.py`). The retry goes there.
- **R2 Usernames.** organization-service's existing `INTERNAL_API_USERNAME` (`organization-service`) is what it *sends* to auth-service. For the inbound endpoint add `INTERNAL_CALLER_USERNAME: str = "auth-service"`; the password is the same `INTERNAL_API_PASSWORD`. auth-service sends username `auth-service` (constant `ORG_INTERNAL_USERNAME` in its sync module).
- **R3 Non-owners on the mapping API.** Use the existing `require_org_role("owner")`: a non-member gets 404, a member with another role gets 403, as every other guarded route in organization-service does today (the spec's "404" line follows the general rule; the existing dependency is the rule).
- **R4 Reconcile creates rows directly.** It does not call `_create_member_row` (that one asks auth-service whether the user exists; the caller *is* auth-service).
- **R5 Concurrent pushes.** A create that hits `uq_org_member` (two sign-ins at once) rolls back that one organization's step and re-reads the row, then applies the update rule; the result is the same as a sequential run.
- **R6 Dedupe.** Token roles are deduplicated case-insensitively on auth-service, keeping first-seen order.

## Review Focus

1. **A token whose `roles` is a string, a dict, or a list with numbers and blanks** — treated as the cleaned list or `[]`, never a 500. Test in Task 5 (`test_roles_claim_shapes`).
2. **A mapping saved as ` qeos.member ` against a token value `QEOS.Member`** — matches (strip + case-insensitive). Test in Task 3 (`test_match_ignores_case_and_spaces`).
3. **The same push twice in a row (retry after a timeout that actually reached the server)** — the second answers `{"changes": []}` and changes nothing. Test in Task 3 (`test_a_repeated_push_changes_nothing`).
4. **A soft-deleted organization that still has mappings** — never gets a member created. Test in Task 3 (`test_a_deleted_organization_is_skipped`).
5. **An admin (not owner) tries to remove a managed member** — 409 `managed_by_entra`, not 403, so the UI shows the right reason. Test in Task 4 (`test_an_admin_removing_a_managed_member_gets_409`).

## Setup (once per worktree)

```bash
git worktree add -b entra-roles /c/dev/github/qeos-entra origin/master
WT=/c/dev/github/qeos-entra
cd $WT/platforms/organization-service && py -3.12 -m venv .venv && .venv/Scripts/python.exe -m pip install -q -r requirements.txt
cd $WT/platforms/auth-service/auth-service && py -3.12 -m venv .venv && .venv/Scripts/python.exe -m pip install -q -r requirements.txt
cd $WT/dashboard && npm ci
ORG_PY=$WT/platforms/organization-service/.venv/Scripts/python.exe
AUTH_PY=$WT/platforms/auth-service/auth-service/.venv/Scripts/python.exe
```

- organization-service tests: `cd $WT/platforms/organization-service && SECRET_KEY=test $ORG_PY -m pytest -q <paths>`
- auth-service tests: `cd $WT/platforms/auth-service/auth-service && SECRET_KEY=test $AUTH_PY -m pytest -q <paths>`
- dashboard: `cd $WT/dashboard && npx vitest run <file>`; gate: `npm run lint && npm run typecheck && npm run test && npm run build`
- `.venv/` must stay untracked (check `git status` before each commit).

## File Structure

organization-service (`platforms/organization-service/`):
- Create `alembic/versions/004_entra_app_roles.py` — mapping table, `managed_by`.
- Create `src/organization/models/sso_role_mapping.py` — `OrganizationSsoRoleMapping`.
- Modify `src/organization/models/member.py` — `managed_by`, `MANAGED_BY`.
- Modify `src/organization/models/__init__.py` — export the new model.
- Create `src/organization/schemas/sso_role_mapping.py` — `SsoRoleMappingCreate`, `SsoRoleMappingOut`, `SsoRolesPush`, `SsoRolesResult`, `SsoRoleChange`.
- Create `src/organization/service/sso_role_service.py` — mapping CRUD and `reconcile`.
- Create `src/organization/api/v1/endpoints/sso_role_mappings.py` — owner API.
- Create `src/organization/api/internal.py` — `require_internal_caller` + `POST /sso-roles`.
- Modify `src/organization/api/v1/api.py`, `src/organization/api/main.py`, `src/organization/core/config.py`.
- Modify `src/organization/schemas/member.py`, `src/organization/service/member_service.py`, `src/organization/api/v1/endpoints/members.py` — `managed_by`, 409.
- Tests: `tests/unit/test_migration.py`, `tests/integration/test_sso_role_mappings.py`, `tests/integration/test_sso_roles_internal.py`, `tests/integration/test_members_managed.py`.

auth-service (`platforms/auth-service/auth-service/`):
- Create `alembic/versions/009_entra_app_roles.py`.
- Modify `src/auth/models/oauth.py` — three columns.
- Modify `src/auth/service/sso_service.py` — `_app_roles`, `roles` in the identity.
- Create `src/auth/service/org_roles_sync.py` — `record_and_push`, `retry_pending`, `warn_if_unconfigured`.
- Modify `src/auth/api/v1/endpoints/sso.py`, `src/auth/api/v1/endpoints/users.py`, `src/auth/api/v1/endpoints/auth.py`, `src/auth/api/main.py`, `src/auth/config.py`.
- Tests: `tests/unit/test_app_roles_claim.py`, `tests/integration/test_microsoft_sso.py` (appended).

dashboard (`dashboard/src/`):
- Modify `api/orgs.ts` — `Member.managed_by`, mapping client.
- Create `components/MicrosoftRolesCard.tsx` (+ `.test.tsx`).
- Modify `pages/OrganizationPage.tsx` (+ `.test.tsx`), `index.css` (one rule).

Root: `docker-compose.yml`, ADR-033 + `docs/architecture/adr/INDEX.md`, README, PRODUCT, TECHNICAL_SPECIFICATION, SECURITY, TODO, DESIGN, `docs/SETUP.md`, both service READMEs.

---

### Task 1: organization-service storage (migration 004, models)

**Files:**
- Create: `platforms/organization-service/alembic/versions/004_entra_app_roles.py`
- Create: `platforms/organization-service/src/organization/models/sso_role_mapping.py`
- Modify: `platforms/organization-service/src/organization/models/member.py`
- Modify: `platforms/organization-service/src/organization/models/__init__.py`
- Test: `platforms/organization-service/tests/unit/test_migration.py`

**Interfaces:**
- Produces: `OrganizationSsoRoleMapping` (`id`, `organization_id`, `app_role`, `role`, `created_at`, `updated_at`; `ROLES = ("admin", "member", "viewer")`); `OrganizationMember.managed_by` (`Optional[str]`), `OrganizationMember.MANAGED_BY = ("entra",)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_migration.py`, and add the new model to its import line (`from src.organization.models import Organization, OrganizationMember, OrganizationInvitation, OrganizationSsoRoleMapping  # noqa: F401`):

```python
def _org(conn, slug="acme"):
    conn.execute(text(f"INSERT INTO organizations (name, slug, plan_tier) VALUES ('{slug}', '{slug}', 'free')"))
    return conn.execute(text(f"SELECT id FROM organizations WHERE slug = '{slug}'")).scalar_one()


def test_migration_004_mapping_role_check(migrated_engine):
    with migrated_engine.begin() as conn:
        org = _org(conn)
        conn.execute(text(f"INSERT INTO organization_sso_role_mappings (organization_id, app_role, role) VALUES ({org}, 'QEOS.Member', 'member')"))
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text(f"INSERT INTO organization_sso_role_mappings (organization_id, app_role, role) VALUES ({org}, 'QEOS.Owner', 'owner')"))


def test_migration_004_app_role_unique_per_org_ignoring_case(migrated_engine):
    with migrated_engine.begin() as conn:
        org = _org(conn)
        other = _org(conn, "beta")
        conn.execute(text(f"INSERT INTO organization_sso_role_mappings (organization_id, app_role, role) VALUES ({org}, 'QEOS.Member', 'member')"))
        # Another organization may map the same value
        conn.execute(text(f"INSERT INTO organization_sso_role_mappings (organization_id, app_role, role) VALUES ({other}, 'QEOS.Member', 'viewer')"))
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text(f"INSERT INTO organization_sso_role_mappings (organization_id, app_role, role) VALUES ({org}, 'qeos.member', 'admin')"))


def test_migration_004_managed_by_is_null_or_entra(migrated_engine):
    with migrated_engine.begin() as conn:
        org = _org(conn)
        conn.execute(text(f"INSERT INTO organization_members (organization_id, user_id, role, status) VALUES ({org}, 1, 'owner', 'active')"))
        conn.execute(text(f"INSERT INTO organization_members (organization_id, user_id, role, status, managed_by) VALUES ({org}, 2, 'member', 'active', 'entra')"))
        assert conn.execute(text("SELECT managed_by FROM organization_members WHERE user_id = 1")).scalar_one() is None
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text(f"INSERT INTO organization_members (organization_id, user_id, role, status, managed_by) VALUES ({org}, 3, 'member', 'active', 'scim')"))


def test_migration_004_downgrade_and_upgrade_again(tmp_path):
    url = f"sqlite:///{(tmp_path / 'roundtrip.db').as_posix()}"
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "003")
    engine = create_engine(url)
    try:
        assert "organization_sso_role_mappings" not in inspect(engine).get_table_names()
        assert "managed_by" not in {c["name"] for c in inspect(engine).get_columns("organization_members")}
    finally:
        engine.dispose()
    command.upgrade(cfg, "head")
```

- [ ] **Step 2: Run to verify they fail**

Run: `SECRET_KEY=test $ORG_PY -m pytest -q tests/unit/test_migration.py`
Expected: FAIL (`ImportError: cannot import name 'OrganizationSsoRoleMapping'`).

- [ ] **Step 3: Implement the model, member column and migration**

`src/organization/models/sso_role_mapping.py`:

```python
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, func
from src.organization.db.base import Base


class OrganizationSsoRoleMapping(Base):
    """An Entra app role value and the organization role it grants (spec 2026-10-16, ADR-033). Never owner."""

    __tablename__ = "organization_sso_role_mappings"

    ROLES = ("admin", "member", "viewer")

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    app_role = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('admin','member','viewer')", name="chk_sso_mapping_role"),
    )


# Case-insensitive uniqueness per organization; SQLite and PostgreSQL both support expression indexes
Index(
    "uq_org_sso_mapping_app_role",
    OrganizationSsoRoleMapping.organization_id,
    func.lower(OrganizationSsoRoleMapping.app_role),
    unique=True,
)
```

`src/organization/models/member.py` — add after `status`, and extend `__table_args__`:

```python
    MANAGED_BY = ("entra",)
    # NULL: made by hand (invitation, creator, add member). "entra": created and kept in step by the Entra
    # app-role mapping at each Microsoft sign-in (ADR-033); never touched by hand
    managed_by = Column(String(20), nullable=True)
```

```python
        CheckConstraint("managed_by IS NULL OR managed_by IN ('entra')", name="chk_member_managed_by"),
```

`src/organization/models/__init__.py`:

```python
from src.organization.models.organization import Organization
from src.organization.models.member import OrganizationMember
from src.organization.models.invitation import OrganizationInvitation
from src.organization.models.sso_role_mapping import OrganizationSsoRoleMapping

__all__ = ["Organization", "OrganizationMember", "OrganizationInvitation", "OrganizationSsoRoleMapping"]
```

`alembic/versions/004_entra_app_roles.py`:

```python
"""Entra app roles: per-organization mapping, and members managed by it (ADR-033)

Revision ID: 004
Revises: 003
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode: SQLite (tests) cannot ALTER a table to add a CHECK constraint
    with op.batch_alter_table("organization_members") as batch:
        batch.add_column(sa.Column("managed_by", sa.String(20), nullable=True))
        batch.create_check_constraint("chk_member_managed_by", "managed_by IS NULL OR managed_by IN ('entra')")
    op.create_table(
        "organization_sso_role_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_role", sa.String(100), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin','member','viewer')", name="chk_sso_mapping_role"),
    )
    op.create_index("ix_organization_sso_role_mappings_id", "organization_sso_role_mappings", ["id"])
    op.create_index("ix_organization_sso_role_mappings_organization_id", "organization_sso_role_mappings", ["organization_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_org_sso_mapping_app_role "
        "ON organization_sso_role_mappings (organization_id, lower(app_role))"
    )


def downgrade() -> None:
    op.drop_index("uq_org_sso_mapping_app_role", table_name="organization_sso_role_mappings")
    op.drop_index("ix_organization_sso_role_mappings_organization_id", table_name="organization_sso_role_mappings")
    op.drop_index("ix_organization_sso_role_mappings_id", table_name="organization_sso_role_mappings")
    op.drop_table("organization_sso_role_mappings")
    with op.batch_alter_table("organization_members") as batch:
        batch.drop_constraint("chk_member_managed_by", type_="check")
        batch.drop_column("managed_by")
```

- [ ] **Step 4: Run to verify they pass, then the whole suite**

Run: `SECRET_KEY=test $ORG_PY -m pytest -q tests/unit/test_migration.py` → PASS. Then `SECRET_KEY=test $ORG_PY -m pytest -q tests/` → all PASS (`test_migration_columns_match_models` proves model and migration agree).

- [ ] **Step 5: Commit**

```bash
git add platforms/organization-service/alembic/versions/004_entra_app_roles.py platforms/organization-service/src/organization/models platforms/organization-service/tests/unit/test_migration.py
git commit -m "feat(organization): migration 004 for Entra app roles (mapping table, managed_by on members; ADR-033)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(Docs for organization-service go with Task 4, which makes the storage reachable.)

---

### Task 2: mapping API (owners only)

**Files:**
- Create: `platforms/organization-service/src/organization/schemas/sso_role_mapping.py`
- Create: `platforms/organization-service/src/organization/service/sso_role_service.py`
- Create: `platforms/organization-service/src/organization/api/v1/endpoints/sso_role_mappings.py`
- Modify: `platforms/organization-service/src/organization/api/v1/api.py`
- Test: `platforms/organization-service/tests/integration/test_sso_role_mappings.py`

**Interfaces:**
- Consumes: Task 1's `OrganizationSsoRoleMapping`.
- Produces: `sso_role_service.list_mappings(db, org_id) -> list[OrganizationSsoRoleMapping]`, `create_mapping(db, org_id, app_role: str, role: str) -> OrganizationSsoRoleMapping` (raises `DuplicateAppRole`), `delete_mapping(db, org_id, mapping_id) -> bool`, `normalize_app_role(value: str) -> str`; schemas `SsoRoleMappingCreate {app_role, role}`, `SsoRoleMappingOut {id, app_role, role, created_at}`. Routes `GET/POST /api/v1/organizations/{org_id}/sso-role-mappings`, `DELETE /api/v1/organizations/{org_id}/sso-role-mappings/{mapping_id}`.

- [ ] **Step 1: Write the failing tests** — `tests/integration/test_sso_role_mappings.py`:

```python
"""The Entra app-role mapping of an organization (spec 2026-10-16 §5.2). Owners only; never owner."""
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import respx

from src.organization.core.config import settings

OWNER, ADMIN, OUTSIDER = 1, 2, 3


def _auth(user_id: int) -> dict:
    token = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                       settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def org(client):
    org_id = client.post("/api/v1/organizations", json={"name": "Acme", "slug": "acme", "plan_tier": "free"},
                         headers=_auth(OWNER)).json()["id"]
    with respx.mock:
        respx.get(f"{settings.AUTH_SERVICE_URL}/internal/v1/users/{ADMIN}").mock(return_value=httpx.Response(200, json={"id": ADMIN}))
        assert client.post(f"/api/v1/organizations/{org_id}/members", json={"user_id": ADMIN, "role": "admin"},
                           headers=_auth(OWNER)).status_code == 201
    return org_id


def url(org_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/sso-role-mappings{suffix}"


def test_an_owner_adds_lists_and_deletes_a_mapping(client, org):
    created = client.post(url(org), json={"app_role": "  QEOS.Member ", "role": "member"}, headers=_auth(OWNER))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["app_role"] == "QEOS.Member" and body["role"] == "member"
    client.post(url(org), json={"app_role": "QEOS.Admin", "role": "admin"}, headers=_auth(OWNER))
    listed = client.get(url(org), headers=_auth(OWNER)).json()
    assert [m["app_role"] for m in listed] == ["QEOS.Admin", "QEOS.Member"]
    assert client.delete(url(org, f"/{body['id']}"), headers=_auth(OWNER)).status_code == 204
    assert [m["app_role"] for m in client.get(url(org), headers=_auth(OWNER)).json()] == ["QEOS.Admin"]


def test_the_same_value_in_another_case_is_a_duplicate(client, org):
    assert client.post(url(org), json={"app_role": "QEOS.Member", "role": "member"}, headers=_auth(OWNER)).status_code == 201
    again = client.post(url(org), json={"app_role": "qeos.member", "role": "viewer"}, headers=_auth(OWNER))
    assert again.status_code == 409
    assert again.json()["detail"] == {"code": "duplicate_app_role", "message": "This app role is already mapped."}


@pytest.mark.parametrize("payload", [
    {"app_role": "QEOS.Owner", "role": "owner"},
    {"app_role": "QEOS.Billing", "role": "billing_manager"},
    {"app_role": "QEOS.X", "role": "superuser"},
    {"app_role": "   ", "role": "member"},
    {"app_role": "x" * 101, "role": "member"},
])
def test_refused_mappings(client, org, payload):
    assert client.post(url(org), json=payload, headers=_auth(OWNER)).status_code == 422


def test_an_admin_cannot_read_or_change_the_mapping(client, org):
    assert client.get(url(org), headers=_auth(ADMIN)).status_code == 403
    assert client.post(url(org), json={"app_role": "QEOS.Admin", "role": "admin"}, headers=_auth(ADMIN)).status_code == 403


def test_an_outsider_does_not_see_the_organization(client, org):
    assert client.get(url(org), headers=_auth(OUTSIDER)).status_code == 404


def test_deleting_another_organizations_mapping_is_404(client, org):
    other = client.post("/api/v1/organizations", json={"name": "Beta", "slug": "beta", "plan_tier": "free"},
                        headers=_auth(OWNER)).json()["id"]
    mapping = client.post(url(other), json={"app_role": "QEOS.Member", "role": "member"}, headers=_auth(OWNER)).json()
    assert client.delete(url(org, f"/{mapping['id']}"), headers=_auth(OWNER)).status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `SECRET_KEY=test $ORG_PY -m pytest -q tests/integration/test_sso_role_mappings.py`
Expected: FAIL (404 for the route).

- [ ] **Step 3: Implement schemas, service and endpoints**

`src/organization/schemas/sso_role_mapping.py`:

```python
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

MappedRole = Literal["admin", "member", "viewer"]


class SsoRoleMappingCreate(BaseModel):
    app_role: str
    role: MappedRole

    @field_validator("app_role")
    @classmethod
    def _app_role(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("app_role must be 1-100 characters")
        return value


class SsoRoleMappingOut(BaseModel):
    id: int
    app_role: str
    role: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SsoRolesPush(BaseModel):
    user_id: int = Field(gt=0)
    roles: list[str] = Field(default_factory=list, max_length=50)


class SsoRoleChange(BaseModel):
    organization_id: int
    action: Literal["created", "updated", "removed"]
    from_role: Optional[str] = Field(default=None, serialization_alias="from")
    to_role: Optional[str] = Field(default=None, serialization_alias="to")


class SsoRolesResult(BaseModel):
    changes: list[SsoRoleChange]
```

`src/organization/service/sso_role_service.py` (mapping part; Task 3 adds `reconcile` to the same file):

```python
"""Entra app roles to organization roles (spec 2026-10-16, ADR-033)."""
import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.organization.models.sso_role_mapping import OrganizationSsoRoleMapping

logger = logging.getLogger(__name__)


class DuplicateAppRole(Exception):
    pass


def normalize_app_role(value: str) -> str:
    return value.strip().lower()


def list_mappings(db: Session, org_id: int) -> list[OrganizationSsoRoleMapping]:
    return (db.query(OrganizationSsoRoleMapping)
            .filter(OrganizationSsoRoleMapping.organization_id == org_id)
            .order_by(func.lower(OrganizationSsoRoleMapping.app_role))
            .all())


def create_mapping(db: Session, org_id: int, app_role: str, role: str) -> OrganizationSsoRoleMapping:
    taken = (db.query(OrganizationSsoRoleMapping)
             .filter(OrganizationSsoRoleMapping.organization_id == org_id,
                     func.lower(OrganizationSsoRoleMapping.app_role) == normalize_app_role(app_role))
             .first())
    if taken is not None:
        raise DuplicateAppRole(app_role)
    mapping = OrganizationSsoRoleMapping(organization_id=org_id, app_role=app_role.strip(), role=role)
    db.add(mapping)
    try:
        db.commit()
    except IntegrityError:  # the unique index, when two owners add the same value at once
        db.rollback()
        raise DuplicateAppRole(app_role)
    db.refresh(mapping)
    return mapping


def delete_mapping(db: Session, org_id: int, mapping_id: int) -> bool:
    mapping = (db.query(OrganizationSsoRoleMapping)
               .filter(OrganizationSsoRoleMapping.id == mapping_id,
                       OrganizationSsoRoleMapping.organization_id == org_id)
               .first())
    if mapping is None:
        return False
    db.delete(mapping)
    db.commit()
    return True
```

`src/organization/api/v1/endpoints/sso_role_mappings.py`:

```python
"""The Entra app-role mapping of an organization (ADR-033): owners only, so whoever edits app-role assignments
in Entra can never reach this editor through a role the mapping itself grants."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.organization.api.deps import get_db, require_org_role
from src.organization.schemas.sso_role_mapping import SsoRoleMappingCreate, SsoRoleMappingOut
from src.organization.service import sso_role_service

router = APIRouter()


@router.get("", response_model=list[SsoRoleMappingOut])
def list_mappings(org_id: int, db: Session = Depends(get_db), _role: str = Depends(require_org_role("owner"))):
    return sso_role_service.list_mappings(db, org_id)


@router.post("", response_model=SsoRoleMappingOut, status_code=status.HTTP_201_CREATED)
def create_mapping(org_id: int, payload: SsoRoleMappingCreate, db: Session = Depends(get_db),
                   _role: str = Depends(require_org_role("owner"))):
    try:
        return sso_role_service.create_mapping(db, org_id, payload.app_role, payload.role)
    except sso_role_service.DuplicateAppRole:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "duplicate_app_role", "message": "This app role is already mapped."})


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(org_id: int, mapping_id: int, db: Session = Depends(get_db),
                   _role: str = Depends(require_org_role("owner"))):
    if not sso_role_service.delete_mapping(db, org_id, mapping_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
```

`src/organization/api/v1/api.py` — import `sso_role_mappings` and add:

```python
api_router.include_router(sso_role_mappings.router, prefix="/organizations/{org_id}/sso-role-mappings", tags=["sso-role-mappings"])
```

- [ ] **Step 4: Run to verify they pass**

Run: `SECRET_KEY=test $ORG_PY -m pytest -q tests/integration/test_sso_role_mappings.py` → PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/organization-service/src platforms/organization-service/tests/integration/test_sso_role_mappings.py
git commit -m "feat(organization): owners map Entra app roles to admin, member or viewer (ADR-033)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: reconcile and the internal endpoint

**Files:**
- Modify: `platforms/organization-service/src/organization/service/sso_role_service.py` (add `reconcile`)
- Create: `platforms/organization-service/src/organization/api/internal.py`
- Modify: `platforms/organization-service/src/organization/api/main.py`
- Modify: `platforms/organization-service/src/organization/core/config.py`
- Test: `platforms/organization-service/tests/integration/test_sso_roles_internal.py`

**Interfaces:**
- Consumes: Task 1 models, Task 2 `list_mappings`/`normalize_app_role`, schemas `SsoRolesPush`, `SsoRolesResult`, `SsoRoleChange`.
- Produces: `sso_role_service.reconcile(db, user_id: int, roles: list[str]) -> list[SsoRoleChange]`; route `POST /internal/v1/sso-roles` (body `SsoRolesPush`, answer `{"changes": [{"organization_id", "action", "from", "to"}]}`); setting `INTERNAL_CALLER_USERNAME = "auth-service"`.

- [ ] **Step 1: Write the failing tests** — `tests/integration/test_sso_roles_internal.py`:

```python
"""POST /internal/v1/sso-roles: the reconcile of section 3 of the spec, behind HTTP Basic."""
import logging

import pytest

from src.organization.core.config import settings
from src.organization.models import Organization, OrganizationMember, OrganizationSsoRoleMapping

PUSH = "/internal/v1/sso-roles"
USER = 42


@pytest.fixture(autouse=True)
def internal_password(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", "s3cret")


def basic():
    return ("auth-service", "s3cret")


def org(db, slug, mappings=(), deleted=False):
    from datetime import datetime, timezone
    o = Organization(name=slug, slug=slug, plan_tier="free", deleted_at=datetime.now(timezone.utc) if deleted else None)
    db.add(o)
    db.commit()
    for app_role, role in mappings:
        db.add(OrganizationSsoRoleMapping(organization_id=o.id, app_role=app_role, role=role))
    db.commit()
    return o.id


def member(db, org_id, user_id=USER):
    return db.query(OrganizationMember).filter_by(organization_id=org_id, user_id=user_id).one_or_none()


def push(client, roles, user_id=USER):
    response = client.post(PUSH, json={"user_id": user_id, "roles": roles}, auth=basic())
    assert response.status_code == 200, response.text
    return response.json()["changes"]


def test_without_a_password_the_endpoint_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_PASSWORD", "")
    assert client.post(PUSH, json={"user_id": 1, "roles": []}, auth=basic()).status_code == 503


@pytest.mark.parametrize("credentials", [("auth-service", "wrong"), ("organization-service", "s3cret"), None])
def test_wrong_credentials_are_401(client, credentials):
    kwargs = {"auth": credentials} if credentials else {}
    assert client.post(PUSH, json={"user_id": 1, "roles": []}, **kwargs).status_code == 401


def test_more_than_50_roles_is_422(client):
    assert client.post(PUSH, json={"user_id": 1, "roles": [f"r{i}" for i in range(51)]}, auth=basic()).status_code == 422


def test_a_matching_role_creates_a_managed_member(client, db, caplog):
    acme = org(db, "acme", [("QEOS.Member", "member")])
    with caplog.at_level(logging.INFO):
        changes = push(client, ["QEOS.Member"])
    assert changes == [{"organization_id": acme, "action": "created", "from": None, "to": "member"}]
    row = member(db, acme)
    assert (row.role, row.status, row.managed_by) == ("member", "active", "entra")
    assert f"entra role: org={acme} user={USER} created None->member roles=QEOS.Member" in caplog.text


def test_highest_matching_role_wins(client, db):
    acme = org(db, "acme", [("QEOS.Viewer", "viewer"), ("QEOS.Admin", "admin"), ("QEOS.Member", "member")])
    push(client, ["QEOS.Viewer", "QEOS.Member", "QEOS.Admin"])
    assert member(db, acme).role == "admin"


def test_match_ignores_case_and_spaces(client, db):
    acme = org(db, "acme", [(" qeos.member ", "member")])
    push(client, ["QEOS.Member"])
    assert member(db, acme).role == "member"


def test_a_managed_member_is_raised_lowered_and_removed(client, db):
    acme = org(db, "acme", [("QEOS.Admin", "admin"), ("QEOS.Viewer", "viewer")])
    push(client, ["QEOS.Viewer"])
    assert push(client, ["QEOS.Admin"]) == [{"organization_id": acme, "action": "updated", "from": "viewer", "to": "admin"}]
    assert push(client, ["QEOS.Viewer"])[0]["to"] == "viewer"
    assert push(client, []) == [{"organization_id": acme, "action": "removed", "from": "viewer", "to": None}]
    assert member(db, acme) is None


def test_a_hand_made_member_is_never_touched(client, db):
    acme = org(db, "acme", [("QEOS.Admin", "admin")])
    db.add(OrganizationMember(organization_id=acme, user_id=USER, role="viewer", status="active"))
    db.commit()
    assert push(client, ["QEOS.Admin"]) == []
    assert push(client, []) == []
    row = member(db, acme)
    assert (row.role, row.managed_by) == ("viewer", None)


def test_an_organization_without_mappings_is_never_touched(client, db):
    plain = org(db, "plain")
    assert push(client, ["QEOS.Admin"]) == []
    assert member(db, plain) is None


def test_a_deleted_organization_is_skipped(client, db):
    gone = org(db, "gone", [("QEOS.Member", "member")], deleted=True)
    assert push(client, ["QEOS.Member"]) == []
    assert member(db, gone) is None


def test_several_organizations_at_once(client, db):
    acme = org(db, "acme", [("QEOS.Member", "member")])
    beta = org(db, "beta", [("QEOS.Member", "viewer"), ("Beta.Admin", "admin")])
    changes = push(client, ["QEOS.Member"])
    assert {(c["organization_id"], c["to"]) for c in changes} == {(acme, "member"), (beta, "viewer")}


def test_a_repeated_push_changes_nothing(client, db):
    org(db, "acme", [("QEOS.Member", "member")])
    push(client, ["QEOS.Member"])
    assert push(client, ["QEOS.Member"]) == []


def test_the_endpoint_is_not_in_the_public_schema(client):
    assert "/internal/v1/sso-roles" not in client.get("/api/v1/openapi.json").json()["paths"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `SECRET_KEY=test $ORG_PY -m pytest -q tests/integration/test_sso_roles_internal.py`
Expected: FAIL (404 for the route).

- [ ] **Step 3: Implement reconcile, the endpoint and the setting**

`src/organization/core/config.py` — add after `INTERNAL_API_PASSWORD`:

```python
    # Who may call THIS service's internal API (POST /internal/v1/sso-roles): auth-service, with the same
    # shared INTERNAL_API_PASSWORD. INTERNAL_API_USERNAME above is what this service sends to auth-service
    INTERNAL_CALLER_USERNAME: str = "auth-service"
```

Append to `src/organization/service/sso_role_service.py`:

```python
from src.organization.models.member import OrganizationMember
from src.organization.models.organization import Organization
from src.organization.schemas.sso_role_mapping import SsoRoleChange

_RANK = {"viewer": 1, "member": 2, "admin": 3}


def _winning_role(mappings: list[OrganizationSsoRoleMapping], wanted: set[str]) -> tuple[str | None, list[str]]:
    matched = [m for m in mappings if normalize_app_role(m.app_role) in wanted]
    if not matched:
        return None, []
    best = max(matched, key=lambda m: _RANK[m.role])
    return best.role, sorted(m.app_role.strip() for m in matched)


def _log(org_id: int, user_id: int, action: str, old, new, matched: list[str]) -> None:
    logger.info("entra role: org=%s user=%s %s %s->%s roles=%s", org_id, user_id, action, old, new, ",".join(matched))


def _apply(db: Session, org_id: int, user_id: int, role: str | None, matched: list[str]) -> SsoRoleChange | None:
    row = db.query(OrganizationMember).filter_by(organization_id=org_id, user_id=user_id).one_or_none()
    if row is not None and row.managed_by != "entra":
        return None  # made by hand: the mapping never touches it
    if row is None:
        if role is None:
            return None
        db.add(OrganizationMember(organization_id=org_id, user_id=user_id, role=role, status="active", managed_by="entra"))
        _log(org_id, user_id, "created", None, role, matched)
        return SsoRoleChange(organization_id=org_id, action="created", from_role=None, to_role=role)
    if role is None:
        old = row.role
        db.delete(row)
        _log(org_id, user_id, "removed", old, None, matched)
        return SsoRoleChange(organization_id=org_id, action="removed", from_role=old, to_role=None)
    if row.role != role:
        old, row.role = row.role, role
        _log(org_id, user_id, "updated", old, role, matched)
        return SsoRoleChange(organization_id=org_id, action="updated", from_role=old, to_role=role)
    return None


def reconcile(db: Session, user_id: int, roles: list[str]) -> list[SsoRoleChange]:
    """Rules of spec 2026-10-16 §3 for every live organization that has a mapping; one commit per organization,
    so a concurrent sign-in that created the same row (R5) costs only that organization's retry."""
    wanted = {normalize_app_role(r) for r in roles if r.strip()}
    org_ids = [row[0] for row in (db.query(OrganizationSsoRoleMapping.organization_id)
                                  .join(Organization, Organization.id == OrganizationSsoRoleMapping.organization_id)
                                  .filter(Organization.deleted_at.is_(None))
                                  .distinct().order_by(OrganizationSsoRoleMapping.organization_id).all())]
    changes: list[SsoRoleChange] = []
    for org_id in org_ids:
        role, matched = _winning_role(list_mappings(db, org_id), wanted)
        change = _apply(db, org_id, user_id, role, matched)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            change = _apply(db, org_id, user_id, role, matched)
            db.commit()
        if change is not None:
            changes.append(change)
    return changes
```

`src/organization/api/internal.py`:

```python
"""Endpoints for other services, not for people (ADR-033).

Not routed by the gateway and not in the public OpenAPI. auth-service authenticates with HTTP Basic:
INTERNAL_CALLER_USERNAME / INTERNAL_API_PASSWORD. Same pattern as project-service's internal API.
"""
import hmac
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from src.organization.core.config import settings
from src.organization.db.session import get_db
from src.organization.schemas.sso_role_mapping import SsoRolesPush, SsoRolesResult
from src.organization.service import sso_role_service

router = APIRouter()
_basic = HTTPBasic(auto_error=False)


def _same(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def require_internal_caller(credentials: Optional[HTTPBasicCredentials] = Depends(_basic)) -> None:
    if not settings.INTERNAL_API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Internal API is not configured")
    user_ok = credentials is not None and _same(credentials.username, settings.INTERNAL_CALLER_USERNAME)
    password_ok = credentials is not None and _same(credentials.password, settings.INTERNAL_API_PASSWORD)
    if not (user_ok and password_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal credentials",
                            headers={"WWW-Authenticate": "Basic"})


@router.post("/sso-roles", response_model=SsoRolesResult, response_model_by_alias=True)
def push_sso_roles(payload: SsoRolesPush, _: None = Depends(require_internal_caller), db: Session = Depends(get_db)):
    """A Microsoft sign-in's app roles: apply the organization mappings to this user."""
    return SsoRolesResult(changes=sso_role_service.reconcile(db, payload.user_id, payload.roles))
```

`src/organization/api/main.py` — after `app.include_router(api_router, ...)`:

```python
from src.organization.api import internal  # noqa: E402  (keep with the other router imports at the top)
app.include_router(internal.router, prefix="/internal/v1", include_in_schema=False)
```

(Put the import with the others at the top of the file.)

- [ ] **Step 4: Run to verify they pass, then the suite**

Run: `SECRET_KEY=test $ORG_PY -m pytest -q tests/integration/test_sso_roles_internal.py` → PASS; `SECRET_KEY=test $ORG_PY -m pytest -q tests/` → PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/organization-service/src platforms/organization-service/tests/integration/test_sso_roles_internal.py
git commit -m "feat(organization): internal POST /internal/v1/sso-roles reconciles Entra-managed members (ADR-033)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: members show and protect managed rows; organization-service docs, ADR-033; delivery 1

**Files:**
- Modify: `platforms/organization-service/src/organization/schemas/member.py`
- Modify: `platforms/organization-service/src/organization/service/member_service.py`
- Modify: `platforms/organization-service/src/organization/api/v1/endpoints/members.py`
- Test: `platforms/organization-service/tests/integration/test_members_managed.py`
- Docs: `docs/architecture/adr/ADR-033-entra-app-roles.md`, `docs/architecture/adr/INDEX.md`, `platforms/organization-service/README.md`, `TECHNICAL_SPECIFICATION.md`, `SECURITY.md`

**Interfaces:**
- Produces: `MemberOut.managed_by: Optional[str]`; `member_service.ManagedByEntra` exception; `DELETE` on a managed member → 409 `managed_by_entra`.

- [ ] **Step 1: Write the failing tests** — `tests/integration/test_members_managed.py`:

```python
"""Entra-managed members are visible as such and cannot be removed by hand (spec §5.3)."""
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import respx

from src.organization.core.config import settings
from src.organization.models import OrganizationMember

OWNER, ADMIN, MANAGED = 1, 2, 9


def _auth(user_id: int) -> dict:
    token = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                       settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def org(client, db):
    org_id = client.post("/api/v1/organizations", json={"name": "Acme", "slug": "acme", "plan_tier": "free"},
                         headers=_auth(OWNER)).json()["id"]
    with respx.mock:
        respx.get(f"{settings.AUTH_SERVICE_URL}/internal/v1/users/{ADMIN}").mock(return_value=httpx.Response(200, json={"id": ADMIN}))
        client.post(f"/api/v1/organizations/{org_id}/members", json={"user_id": ADMIN, "role": "admin"}, headers=_auth(OWNER))
    db.add(OrganizationMember(organization_id=org_id, user_id=MANAGED, role="member", status="active", managed_by="entra"))
    db.commit()
    return org_id


def managed_id(db, org_id):
    return db.query(OrganizationMember).filter_by(organization_id=org_id, user_id=MANAGED).one().id


def test_members_carry_managed_by(client, org):
    with respx.mock:
        respx.get(f"{settings.AUTH_SERVICE_URL}/internal/v1/users").mock(return_value=httpx.Response(200, json={"users": []}))
        rows = client.get(f"/api/v1/organizations/{org}/members", headers=_auth(OWNER)).json()
    by_user = {r["user_id"]: r["managed_by"] for r in rows}
    assert by_user == {OWNER: None, ADMIN: None, MANAGED: "entra"}


@pytest.mark.parametrize("remover", [OWNER, ADMIN])
def test_removing_a_managed_member_is_409(client, db, org, remover):
    response = client.delete(f"/api/v1/organizations/{org}/members/{managed_id(db, org)}", headers=_auth(remover))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "managed_by_entra", "message": "Managed by Entra: remove the app role instead."}


def test_an_admin_removing_a_managed_member_gets_409(client, db, org):
    assert client.delete(f"/api/v1/organizations/{org}/members/{managed_id(db, org)}", headers=_auth(ADMIN)).status_code == 409


def test_a_hand_made_member_is_still_removable(client, db, org):
    admin_row = db.query(OrganizationMember).filter_by(organization_id=org, user_id=ADMIN).one()
    assert client.delete(f"/api/v1/organizations/{org}/members/{admin_row.id}", headers=_auth(OWNER)).status_code == 204
```

(`emails_by_ids` calls `GET {AUTH_SERVICE_URL}/internal/v1/users?ids=…` and answers `{"users": [...]}`; the mock keeps the test offline.)

- [ ] **Step 2: Run to verify they fail**

Run: `SECRET_KEY=test $ORG_PY -m pytest -q tests/integration/test_members_managed.py`
Expected: FAIL (`managed_by` missing; delete answers 204).

- [ ] **Step 3: Implement**

`schemas/member.py` — in `MemberOut` after `status`:

```python
    managed_by: Optional[str] = None  # "entra": kept in step by the app-role mapping (ADR-033)
```

`service/member_service.py` — add near the top:

```python
class ManagedByEntra(Exception):
    """The member is created and kept in step by the Entra app-role mapping; removing it by hand would be undone at
    their next Microsoft sign-in (ADR-033)."""
```

and in `remove_member`, right after the `member is None` check, before `_assert_can_grant_role`:

```python
    if member.managed_by == "entra":
        raise ManagedByEntra()
```

`api/v1/endpoints/members.py` — in `remove_member`, add before the `PermissionError` clause:

```python
    except member_service.ManagedByEntra:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "managed_by_entra", "message": "Managed by Entra: remove the app role instead."})
```

- [ ] **Step 4: Run to verify they pass, then the full organization-service CI step**

Run: `SECRET_KEY=test $ORG_PY -m pytest -q tests/integration/test_members_managed.py` → PASS. Then the CI matrix entry: `SECRET_KEY=test $ORG_PY -m pytest tests/ -q` and `SECRET_KEY=test $ORG_PY -m pytest ../../shared/tests -q` → PASS.

- [ ] **Step 5: Docs for organization-service and ADR-033**

- Create `docs/architecture/adr/ADR-033-entra-app-roles.md` from `docs/architecture/adr/TEMPLATE.md`: Status Accepted, Date 2026-10-16, Spec link; Decision = spec §1 bullets and §3 rules; Alternatives (each with Pros/Cons/Decision "Not Selected"/Rejected because): security groups (200-group overage, raw GUIDs in QEOS), fixed role names in auth-service (one mapping for every organization), reconcile everyone (a hand-made owner would lose access when Entra omits them), additive only (leaving a role in Entra would do nothing), the dashboard passing the token to organization-service (a second token verifier); Consequences: Entra can grant at most admin; an organization keeps at least one hand-made owner; managed members cannot be removed by hand; sync is best effort and heals on refresh within 60 minutes.
- Add the ADR-033 row to `docs/architecture/adr/INDEX.md` in the format of the ADR-032 row.
- `platforms/organization-service/README.md`: tables (`organization_sso_role_mappings`, `organization_members.managed_by`), migration 004, the three mapping routes with bodies and codes, the members `managed_by` field and the 409, the internal endpoint (auth, body, answer, 503/401/422) and `INTERNAL_CALLER_USERNAME`.
- `TECHNICAL_SPECIFICATION.md` §2.2 organization-service: the same in one paragraph; the internal API line next to project-service's.
- `SECURITY.md`: new bullet "Entra app roles (ADR-033)": a mapping grants at most admin, owners only by hand, mapping editable by owners only, managed members cannot be removed by hand, internal endpoint HTTP Basic and never routed, each change logged at INFO.
- Run `python scripts/check_architecture_docs.py` from the repo root → passes.

- [ ] **Step 6: Commit, gate and push delivery 1**

```bash
git add platforms/organization-service docs/architecture/adr TECHNICAL_SPECIFICATION.md SECURITY.md
git commit -m "feat(organization): Entra-managed members are marked and cannot be removed by hand; ADR-033" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git fetch origin && git rebase origin/master
# if the rebase brought commits in, re-run Step 4's commands
git push origin HEAD:master
```

---

### Task 5: auth-service reads and stores the token's roles (migration 009)

**Files:**
- Create: `platforms/auth-service/auth-service/alembic/versions/009_entra_app_roles.py`
- Modify: `platforms/auth-service/auth-service/src/auth/models/oauth.py`
- Modify: `platforms/auth-service/auth-service/src/auth/service/sso_service.py`
- Test: `platforms/auth-service/auth-service/tests/unit/test_app_roles_claim.py`

**Interfaces:**
- Produces: `sso_service._app_roles(claims: dict) -> list[str]`; `validate_microsoft_token(...)["roles"]: list[str]`; `OAuthAccount.sso_roles` (JSON list or None), `.sso_roles_at`, `.sso_roles_synced_at` (timezone-aware datetimes or None).

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_app_roles_claim.py`:

```python
import logging

import pytest

from src.auth.service.sso_service import _app_roles


@pytest.mark.parametrize("claims, expected", [
    ({}, []),
    ({"roles": "QEOS.Admin"}, []),
    ({"roles": {"a": 1}}, []),
    ({"roles": ["QEOS.Admin", 7, None, "  ", " QEOS.Member "]}, ["QEOS.Admin", "QEOS.Member"]),
    ({"roles": ["QEOS.Admin", "qeos.admin", "QEOS.Viewer"]}, ["QEOS.Admin", "QEOS.Viewer"]),
    ({"roles": ["x" * 150]}, ["x" * 100]),
])
def test_roles_claim_shapes(claims, expected):
    assert _app_roles(claims) == expected


def test_more_than_50_roles_keeps_50_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        got = _app_roles({"roles": [f"R{i}" for i in range(60)]})
    assert got == [f"R{i}" for i in range(50)]
    assert "60 app roles" in caplog.text
```

Also add to `tests/integration/test_microsoft_sso.py`, after `test_a_valid_token_signs_in_and_creates_a_passwordless_user`:

```python
def test_the_tokens_app_roles_are_stored_on_the_link(client, db, microsoft_key):
    assert sign_in(client, ms_token(microsoft_key, roles=["QEOS.Member", "QEOS.Viewer"])).status_code == 200
    link = db.query(OAuthAccount).one()
    assert link.sso_roles == ["QEOS.Member", "QEOS.Viewer"]
    assert link.sso_roles_at is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `SECRET_KEY=test $AUTH_PY -m pytest -q tests/unit/test_app_roles_claim.py tests/integration/test_microsoft_sso.py -k "roles"`
Expected: FAIL (`ImportError: cannot import name '_app_roles'`).

- [ ] **Step 3: Implement**

`sso_service.py` — near the top (after `logger`):

```python
APP_ROLES_MAX = 50
APP_ROLE_LENGTH = 100


def _app_roles(claims: dict) -> list[str]:
    """The ID token's Entra app roles (ADR-033): strings only, stripped, cut to 100 characters, deduplicated without
    regard to case (first one kept), at most 50."""
    raw = claims.get("roles")
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        value = item.strip()[:APP_ROLE_LENGTH]
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        values.append(value)
    if len(values) > APP_ROLES_MAX:
        logger.warning("Microsoft token carries %s app roles; only the first %s are used", len(values), APP_ROLES_MAX)
        values = values[:APP_ROLES_MAX]
    return values
```

and in `validate_microsoft_token`'s returned dict add `"roles": _app_roles(claims),`.

`models/oauth.py` — add `JSON` to the SQLAlchemy import and after `expires_at`:

```python
    # The last Entra app roles a Microsoft sign-in carried, and when they reached organization-service (ADR-033)
    sso_roles = Column(JSON, nullable=True)
    sso_roles_at = Column(DateTime(timezone=True), nullable=True)
    sso_roles_synced_at = Column(DateTime(timezone=True), nullable=True)
```

`alembic/versions/009_entra_app_roles.py`:

```python
"""Entra app roles: the last roles a Microsoft sign-in carried, and when they were applied (ADR-033)

Revision ID: 009
Revises: 008
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_accounts", sa.Column("sso_roles", sa.JSON(), nullable=True))
    op.add_column("oauth_accounts", sa.Column("sso_roles_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_accounts", sa.Column("sso_roles_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_accounts", "sso_roles_synced_at")
    op.drop_column("oauth_accounts", "sso_roles_at")
    op.drop_column("oauth_accounts", "sso_roles")
```

The stored-roles integration test passes only after Task 6 writes them; mark it now with `@pytest.mark.xfail(strict=True, reason="Task 6 stores the roles")` and remove the mark in Task 6.

- [ ] **Step 4: Run to verify, then the auth suite**

Run: `SECRET_KEY=test $AUTH_PY -m pytest -q tests/unit/test_app_roles_claim.py` → PASS; `SECRET_KEY=test $AUTH_PY -m pytest -q tests/` → PASS (the xfail counts as expected; auth's migration test, if any, proves model and migration agree).

- [ ] **Step 5: Commit**

```bash
git add platforms/auth-service/auth-service/alembic/versions/009_entra_app_roles.py platforms/auth-service/auth-service/src/auth/models/oauth.py platforms/auth-service/auth-service/src/auth/service/sso_service.py platforms/auth-service/auth-service/tests
git commit -m "feat(auth): read the Microsoft token's app roles; migration 009 stores them on the link (ADR-033)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: auth-service pushes roles at sign-in and link, retries on refresh; compose; docs; delivery 2

**Files:**
- Create: `platforms/auth-service/auth-service/src/auth/service/org_roles_sync.py`
- Modify: `platforms/auth-service/auth-service/src/auth/config.py`
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/sso.py` (`microsoft_login`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/users.py` (`link_microsoft_account`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/v1/endpoints/auth.py` (`refresh_access_token`)
- Modify: `platforms/auth-service/auth-service/src/auth/api/main.py` (start-up warning)
- Modify: `docker-compose.yml`
- Test: `platforms/auth-service/auth-service/tests/integration/test_microsoft_sso.py` (append)
- Docs: `platforms/auth-service/auth-service/README.md`, `docs/SETUP.md`

**Interfaces:**
- Consumes: Task 5 `identity["roles"]`, `OAuthAccount.sso_roles*`; Task 3's endpoint contract.
- Produces: `org_roles_sync.record_and_push(db, link: OAuthAccount, roles: list[str]) -> bool`, `org_roles_sync.retry_pending(db, user_id: int) -> None`, `org_roles_sync.warn_if_unconfigured() -> None`, `org_roles_sync._post(url: str, auth: tuple[str, str], body: dict) -> int` (the seam tests replace). Settings `ORGANIZATION_SERVICE_URL`, `ORGANIZATION_INTERNAL_API_PASSWORD`.

- [ ] **Step 1: Write the failing tests** — append to `tests/integration/test_microsoft_sso.py` and remove the xfail mark from Task 5's test:

```python
# --- Entra app roles pushed to organization-service (ADR-033) ---------------------------------------------

from src.auth.service import org_roles_sync  # noqa: E402


@pytest.fixture
def org_calls(monkeypatch):
    """Records each push; answers what the test sets in .status (200 by default; an Exception to raise)."""
    class Calls(list):
        status = 200
    calls = Calls()

    def fake_post(url, auth, body):
        calls.append((url, auth, body))
        if isinstance(calls.status, Exception):
            raise calls.status
        return calls.status

    monkeypatch.setattr(settings, "ORGANIZATION_SERVICE_URL", "http://org.test")
    monkeypatch.setattr(settings, "ORGANIZATION_INTERNAL_API_PASSWORD", "s3cret")
    monkeypatch.setattr(org_roles_sync, "_post", fake_post)
    return calls


def test_sign_in_pushes_the_roles(client, db, microsoft_key, org_calls):
    assert sign_in(client, ms_token(microsoft_key, roles=["QEOS.Member"])).status_code == 200
    user_id = db.query(User).one().id
    assert org_calls == [("http://org.test/internal/v1/sso-roles", ("auth-service", "s3cret"),
                          {"user_id": user_id, "roles": ["QEOS.Member"]})]
    assert db.query(OAuthAccount).one().sso_roles_synced_at is not None


def test_a_token_without_roles_pushes_an_empty_list(client, db, microsoft_key, org_calls):
    sign_in(client, ms_token(microsoft_key))
    assert org_calls[0][2]["roles"] == []


@pytest.mark.parametrize("answer", [503, 401, ConnectionError("down")])
def test_a_failed_push_still_signs_in_and_is_left_pending(client, db, microsoft_key, org_calls, caplog, answer):
    org_calls.status = answer
    with caplog.at_level(logging.WARNING):
        response = sign_in(client, ms_token(microsoft_key, roles=["QEOS.Member"]))
    assert response.status_code == 200
    link = db.query(OAuthAccount).one()
    assert link.sso_roles_synced_at is None
    assert "entra role sync deferred" in caplog.text


def test_refresh_retries_a_pending_push_then_stops(client, db, microsoft_key, org_calls):
    org_calls.status = 503
    first = sign_in(client, ms_token(microsoft_key, roles=["QEOS.Admin"])).json()
    org_calls.status = 200
    refreshed = client.post("/api/v1/auth/refresh-token", json={"refresh_token": first["refresh_token"]})
    assert refreshed.status_code == 200
    assert len(org_calls) == 2 and org_calls[1][2]["roles"] == ["QEOS.Admin"]
    assert db.query(OAuthAccount).one().sso_roles_synced_at is not None
    again = client.post("/api/v1/auth/refresh-token", json={"refresh_token": refreshed.json()["refresh_token"]})
    assert again.status_code == 200 and len(org_calls) == 2


def test_a_failed_retry_never_fails_the_refresh(client, db, microsoft_key, org_calls):
    org_calls.status = 503
    first = sign_in(client, ms_token(microsoft_key, roles=["QEOS.Admin"])).json()
    assert client.post("/api/v1/auth/refresh-token", json={"refresh_token": first["refresh_token"]}).status_code == 200


def test_linking_microsoft_pushes_the_roles(client, db, microsoft_key, org_calls, register_and_verify):
    login = register_and_verify("bob@example.com")
    linked = client.post(LINK, json={"credential": ms_token(microsoft_key, roles=["QEOS.Viewer"]),
                                     "current_password": "securepassword123"}, headers=bearer(login))
    assert linked.status_code == 200
    assert org_calls[-1][2] == {"user_id": linked.json()["id"], "roles": ["QEOS.Viewer"]}


def test_without_the_password_nothing_is_pushed(client, db, microsoft_key, org_calls, monkeypatch):
    monkeypatch.setattr(settings, "ORGANIZATION_INTERNAL_API_PASSWORD", "")
    assert sign_in(client, ms_token(microsoft_key, roles=["QEOS.Member"])).status_code == 200
    assert org_calls == []
    assert db.query(OAuthAccount).one().sso_roles == ["QEOS.Member"]


def test_the_start_up_warns_when_the_password_is_missing(monkeypatch, caplog):
    monkeypatch.setattr(settings, "ORGANIZATION_INTERNAL_API_PASSWORD", "")
    with caplog.at_level(logging.WARNING):
        org_roles_sync.warn_if_unconfigured()
    assert "Entra app roles are not applied: ORGANIZATION_INTERNAL_API_PASSWORD is not set" in caplog.text
```

Append to `tests/integration/test_sso_endpoints.py` (Google sign-in carries no roles and never pushes):

```python
def test_google_sign_in_never_pushes_roles(client, db, google_key, monkeypatch):
    from src.auth.service import org_roles_sync
    calls = []
    monkeypatch.setattr(settings, "ORGANIZATION_INTERNAL_API_PASSWORD", "s3cret")
    monkeypatch.setattr(org_roles_sync, "_post", lambda url, auth, body: calls.append(body) or 200)
    assert client.post("/api/v1/sso/google", json={"credential": _id_token(google_key)}).status_code == 200
    assert calls == []
```

(`settings` is imported at the top of that file; if not, add `from src.auth.config import settings`.)

- [ ] **Step 2: Run to verify they fail**

Run: `SECRET_KEY=test $AUTH_PY -m pytest -q tests/integration/test_microsoft_sso.py`
Expected: FAIL (`cannot import name 'org_roles_sync'`).

- [ ] **Step 3: Implement**

`config.py` — after `INTERNAL_API_PASSWORD`:

```python
    # Entra app roles (ADR-033): where a Microsoft sign-in's roles are pushed, and the password of
    # organization-service's internal API. Empty password: roles are stored but never applied (one start-up warning)
    ORGANIZATION_SERVICE_URL: str = "http://organization-service:8000"
    ORGANIZATION_INTERNAL_API_PASSWORD: str = ""
```

`service/org_roles_sync.py`:

```python
"""Push a Microsoft sign-in's Entra app roles to organization-service (ADR-033). Best effort: a failure never fails
the sign-in, the link or the refresh; a pending push is retried at the next token refresh."""
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from src.auth.config import settings
from src.auth.models.oauth import OAuthAccount

logger = logging.getLogger(__name__)

ORG_INTERNAL_USERNAME = "auth-service"
TIMEOUT_SECONDS = 5.0


def _post(url: str, auth: tuple[str, str], body: dict) -> int:
    """The one network call; tests replace it."""
    return httpx.post(url, auth=auth, json=body, timeout=TIMEOUT_SECONDS).status_code


def warn_if_unconfigured() -> None:
    if not settings.ORGANIZATION_INTERNAL_API_PASSWORD:
        logger.warning("Entra app roles are not applied: ORGANIZATION_INTERNAL_API_PASSWORD is not set")


def _push(db: Session, link: OAuthAccount) -> bool:
    if not settings.ORGANIZATION_INTERNAL_API_PASSWORD:
        return False
    url = f"{settings.ORGANIZATION_SERVICE_URL.rstrip('/')}/internal/v1/sso-roles"
    body = {"user_id": link.user_id, "roles": list(link.sso_roles or [])}
    try:
        status = _post(url, (ORG_INTERNAL_USERNAME, settings.ORGANIZATION_INTERNAL_API_PASSWORD), body)
    except Exception as exc:  # connection refused, timeout, DNS: never the sign-in's problem
        logger.warning("entra role sync deferred: user=%s reason=%s", link.user_id, type(exc).__name__)
        return False
    if not 200 <= status < 300:
        logger.warning("entra role sync deferred: user=%s reason=HTTP %s", link.user_id, status)
        return False
    link.sso_roles_synced_at = datetime.now(timezone.utc)
    db.commit()
    return True


def record_and_push(db: Session, link: Optional[OAuthAccount], roles: list[str]) -> bool:
    """Store the roles a Microsoft sign-in (or link) carried, then push them."""
    if link is None:
        return False
    link.sso_roles = list(roles)
    link.sso_roles_at = datetime.now(timezone.utc)
    db.commit()
    return _push(db, link)


def retry_pending(db: Session, user_id: int) -> None:
    """At a token refresh: push again when the last roles never reached organization-service."""
    link = db.query(OAuthAccount).filter(OAuthAccount.user_id == user_id, OAuthAccount.provider == "microsoft").first()
    if link is None or link.sso_roles_at is None:
        return
    synced = link.sso_roles_synced_at
    if synced is not None and _aware(synced) >= _aware(link.sso_roles_at):
        return
    _push(db, link)


def _aware(value: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes for timezone=True columns
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
```

`endpoints/sso.py` — in `microsoft_login`, after `tokens = sso_sign_in(...)`:

```python
    link = db.query(OAuthAccount).filter(
        OAuthAccount.provider == "microsoft", OAuthAccount.provider_user_id == identity["provider_user_id"],
    ).first()
    org_roles_sync.record_and_push(db, link, identity.get("roles", []))
```

(import `OAuthAccount` if not already imported, and `from src.auth.service import org_roles_sync`).

`endpoints/users.py` — replace the body of `link_microsoft_account`:

```python
    seen: dict = {}

    def verify(credential: str) -> dict:
        identity = verify_microsoft_credential(credential)
        seen.update(identity)
        return identity

    user = _link_identity(db, current_user, request.credential, request.current_password, verify, "Microsoft")
    link = db.query(OAuthAccount).filter(
        OAuthAccount.user_id == current_user.id, OAuthAccount.provider == "microsoft",
    ).first()
    org_roles_sync.record_and_push(db, link, seen.get("roles", []))
    return user
```

(`from src.auth.service import org_roles_sync`).

`endpoints/auth.py` — in `refresh_access_token`, right before `# Issue new tokens`:

```python
    # A Microsoft sign-in whose app roles never reached organization-service: try again (ADR-033)
    org_roles_sync.retry_pending(db, user.id)
```

(`from src.auth.service import org_roles_sync`).

`api/main.py` — in `_apply_auth_mode()` right after `check_sso_only_settings()`:

```python
    org_roles_sync.warn_if_unconfigured()
```

(`from src.auth.service import org_roles_sync`).

`docker-compose.yml` — in `x-auth-env`, after `AUTH_SSO_PROVIDERS`:

```yaml
  # Entra app roles (ADR-033): a Microsoft sign-in's roles go to organization-service's internal API
  ORGANIZATION_SERVICE_URL: http://organization-service:8000
  ORGANIZATION_INTERNAL_API_PASSWORD: ${INTERNAL_API_PASSWORD:?set INTERNAL_API_PASSWORD (service-to-service internal APIs; URL-safe characters)}
```

- [ ] **Step 4: Run to verify they pass, then the full auth-service CI step**

Run: `SECRET_KEY=test $AUTH_PY -m pytest -q tests/integration/test_microsoft_sso.py` → PASS; `SECRET_KEY=test $AUTH_PY -m pytest tests/ -q` → PASS. From the repo root: `docker compose config -q` → no error.

- [ ] **Step 5: Docs**

- `platforms/auth-service/auth-service/README.md`: the two settings, the push after Microsoft sign-in and link, the retry on refresh, migration 009, the WARNING lines.
- `docs/SETUP.md` §3.8, new subsection **App roles (organization role from Entra, ADR-033)** after "Microsoft-only sign-in": IT steps (App registration → App roles → Create app role: display name "QEOS Admin", allowed member types Users/Groups, value `QEOS.Admin`; same for `QEOS.Member`, `QEOS.Viewer`; Enterprise applications → the app → Users and groups → Add user/group → pick the role); no optional claim needed, `roles` comes in the ID token; QEOS side (an owner opens the Organization page → Microsoft roles → maps each value to admin, member or viewer); the rules in plain words (at each Microsoft sign-in the role follows Entra for members Entra created; members invited by hand are never changed; owners are always granted by hand; highest role wins; removing a mapping changes nobody until their next sign-in; a sync missed while organization-service was down is retried within the hour); the settings `ORGANIZATION_SERVICE_URL`, `ORGANIZATION_INTERNAL_API_PASSWORD` in the settings table and in "New colleagues" (they now get their role at first sign-in when a mapping matches). AKS/other deployments: pass both settings to auth-service and `INTERNAL_API_PASSWORD` to organization-service.

- [ ] **Step 6: Commit, gate and push delivery 2**

```bash
git add platforms/auth-service/auth-service docker-compose.yml docs/SETUP.md
git commit -m "feat(auth): push a Microsoft sign-in's app roles to organization-service, retry on refresh (ADR-033)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git fetch origin && git rebase origin/master
# if the rebase brought commits in, re-run Step 4's commands and Task 4 Step 4's commands
git push origin HEAD:master
```

---

### Task 7: dashboard card, badge, docs; delivery 3

**Files:**
- Modify: `dashboard/src/api/orgs.ts`
- Create: `dashboard/src/components/MicrosoftRolesCard.tsx`, `dashboard/src/components/MicrosoftRolesCard.test.tsx`
- Modify: `dashboard/src/pages/OrganizationPage.tsx`, `dashboard/src/pages/OrganizationPage.test.tsx`
- Modify: `dashboard/src/index.css` (only if no existing class fits the badge spacing)
- Docs: `DESIGN.md`, `README.md`, `PRODUCT.md`, `TODO.md`

**Interfaces:**
- Consumes: routes from Tasks 2 and 4.
- Produces: `Member.managed_by: "entra" | null`; `SsoRoleMapping {id, app_role, role, created_at}`; `MAPPED_ROLES = ["admin", "member", "viewer"] as const`; `listSsoRoleMappings(orgId)`, `createSsoRoleMapping(orgId, appRole, role)`, `deleteSsoRoleMapping(orgId, mappingId)`; `<MicrosoftRolesCard orgId={number} />`.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill** before editing UI; read `OrganizationPage.test.tsx` for its msw setup and render helper.

- [ ] **Step 1: Write the failing tests** — `components/MicrosoftRolesCard.test.tsx`:

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import MicrosoftRolesCard from "./MicrosoftRolesCard";

const URL = "/api/v1/organizations/5/sso-role-mappings";
const row = (id: number, app_role: string, role: string) => ({ id, app_role, role, created_at: "2026-10-16T09:00:00Z" });

function renderCard() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MicrosoftRolesCard orgId={5} /></QueryClientProvider>);
}

test("lists the mappings with the lead line", async () => {
  server.use(http.get(URL, () => HttpResponse.json([row(1, "QEOS.Admin", "admin"), row(2, "QEOS.Member", "member")])));
  renderCard();
  expect(screen.getByRole("heading", { name: "Microsoft roles" })).toBeInTheDocument();
  expect(screen.getByText(/Owners are always granted by hand\./)).toBeInTheDocument();
  const table = await screen.findByRole("table");
  expect(within(table).getByText("QEOS.Admin")).toBeInTheDocument();
  expect(within(table).getByText("member")).toBeInTheDocument();
});

test("empty state", async () => {
  server.use(http.get(URL, () => HttpResponse.json([])));
  renderCard();
  expect(await screen.findByText("No app roles mapped yet.")).toBeInTheDocument();
});

test("the role select offers admin, member and viewer only", async () => {
  server.use(http.get(URL, () => HttpResponse.json([])));
  renderCard();
  const select = await screen.findByLabelText("QEOS role");
  expect([...(select as HTMLSelectElement).options].map((o) => o.value)).toEqual(["admin", "member", "viewer"]);
});

test("adds a mapping", async () => {
  let rows = [row(1, "QEOS.Admin", "admin")];
  server.use(
    http.get(URL, () => HttpResponse.json(rows)),
    http.post(URL, async ({ request }) => {
      const body = (await request.json()) as { app_role: string; role: string };
      expect(body).toEqual({ app_role: "QEOS.Viewer", role: "viewer" });
      rows = [...rows, row(2, "QEOS.Viewer", "viewer")];
      return HttpResponse.json(rows[1], { status: 201 });
    }),
  );
  renderCard();
  await userEvent.type(await screen.findByLabelText("App role"), "QEOS.Viewer");
  await userEvent.selectOptions(screen.getByLabelText("QEOS role"), "viewer");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  expect(await screen.findByText("QEOS.Viewer")).toBeInTheDocument();
  expect(screen.getByLabelText("App role")).toHaveValue("");
});

test("a duplicate shows at the field", async () => {
  server.use(
    http.get(URL, () => HttpResponse.json([row(1, "QEOS.Admin", "admin")])),
    http.post(URL, () => HttpResponse.json({ detail: { code: "duplicate_app_role", message: "This app role is already mapped." } }, { status: 409 })),
  );
  renderCard();
  await userEvent.type(await screen.findByLabelText("App role"), "qeos.admin");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  expect(await screen.findByText("This app role is already mapped.")).toBeInTheDocument();
});

test("removes a mapping after confirmation", async () => {
  let rows = [row(1, "QEOS.Admin", "admin")];
  server.use(
    http.get(URL, () => HttpResponse.json(rows)),
    http.delete(`${URL}/1`, () => { rows = []; return new HttpResponse(null, { status: 204 }); }),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("button", { name: "Remove mapping QEOS.Admin" }));
  expect(screen.getByText(/Members keep their role until their next Microsoft sign-in\./)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(screen.getByText("No app roles mapped yet.")).toBeInTheDocument());
});

test("a failed load shows the error with Retry inside the card", async () => {
  server.use(http.get(URL, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  renderCard();
  expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
```

Adjust the confirm-button names to what `ConfirmButton` renders (read its test once): trigger accessible name comes from `ariaLabel`, the confirm button from `confirmLabel`.

In `OrganizationPage.test.tsx`: add `within` to the testing-library import; add `managed_by: null` to both `MEMBERS` rows; add the mock and tests below. The card stays hidden by default (`microsoftEnabled` → false), so the existing tests' `getByLabelText(/role/i)` keeps finding only the invitation select.

```tsx
import { microsoftEnabled } from "../auth/ssoProviders";

vi.mock("../auth/ssoProviders", () => ({ microsoftEnabled: vi.fn(() => false) }));
beforeEach(() => vi.mocked(microsoftEnabled).mockReturnValue(false));

const MANAGED = { id: 3, organization_id: 7, user_id: 12, email: "eve@example.com", role: "member", status: "active",
  created_at: "2026-10-04T10:00:00Z", updated_at: null, managed_by: "entra" };

test("an Entra-managed member shows the badge and cannot be removed", async () => {
  mockOrg();
  server.use(http.get("/api/v1/organizations/7/members", () => HttpResponse.json([...MEMBERS, MANAGED])));
  renderPage();
  const row = (await screen.findByText("eve@example.com")).closest("tr")!;
  expect(within(row).getByText("Entra")).toHaveAttribute("title", "Managed by Entra");
  const remove = within(row).getByRole("button", { name: /Remove/ });
  expect(remove).toBeDisabled();
  expect(remove).toHaveAttribute("title", "Managed by Entra: remove the app role instead.");
  // A hand-made member keeps the normal Remove
  const handMade = screen.getByText("user 11").closest("tr")!;
  expect(within(handMade).getByRole("button", { name: /Remove user 11/ })).toBeEnabled();
});

test("the Microsoft roles card shows for owners when the build has Microsoft sign-in", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  mockOrg("owner");
  server.use(http.get("/api/v1/organizations/7/sso-role-mappings", () => HttpResponse.json([])));
  renderPage();
  expect(await screen.findByRole("heading", { name: "Microsoft roles" })).toBeInTheDocument();
});

test("the card is hidden for admins", async () => {
  vi.mocked(microsoftEnabled).mockReturnValue(true);
  mockOrg("admin");
  renderPage();
  await screen.findByText("owner@example.com");
  expect(screen.queryByRole("heading", { name: "Microsoft roles" })).not.toBeInTheDocument();
});

test("the card is hidden when the build has no Microsoft sign-in", async () => {
  mockOrg("owner");
  renderPage();
  await screen.findByText("owner@example.com");
  expect(screen.queryByRole("heading", { name: "Microsoft roles" })).not.toBeInTheDocument();
});
```

For the admin test, `me` must answer once `members/me` has resolved; if the heading check runs before `me` loads, add `await screen.findByRole("button", { name: /Remove user 11/ })` first (admins see Remove), which proves `me` has loaded.

- [ ] **Step 2: Run to verify they fail**

Run: `cd $WT/dashboard && npx vitest run src/components/MicrosoftRolesCard.test.tsx src/pages/OrganizationPage.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

`api/orgs.ts` — `Member` gains `managed_by: "entra" | null;` and add:

```ts
/** An Entra app role value and the organization role it grants (ADR-033). Never owner. */
export interface SsoRoleMapping {
  id: number;
  app_role: string;
  role: string;
  created_at: string | null;
}

export const MAPPED_ROLES = ["admin", "member", "viewer"] as const;

export function listSsoRoleMappings(orgId: number): Promise<SsoRoleMapping[]> {
  return apiFetch(`/api/v1/organizations/${orgId}/sso-role-mappings`);
}

export function createSsoRoleMapping(orgId: number, appRole: string, role: string): Promise<SsoRoleMapping> {
  return apiFetch(`/api/v1/organizations/${orgId}/sso-role-mappings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_role: appRole, role }),
  });
}

export function deleteSsoRoleMapping(orgId: number, mappingId: number): Promise<void> {
  return apiFetch(`/api/v1/organizations/${orgId}/sso-role-mappings/${mappingId}`, { method: "DELETE" });
}
```

`components/MicrosoftRolesCard.tsx`:

```tsx
import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/http";
import { MAPPED_ROLES, createSsoRoleMapping, deleteSsoRoleMapping, listSsoRoleMappings } from "../api/orgs";
import ConfirmButton from "./ConfirmButton";
import ErrorBanner from "./ErrorBanner";

/** Owners map Entra app roles to admin, member or viewer (ADR-033). Owners are never granted by a mapping. */
export default function MicrosoftRolesCard({ orgId }: { orgId: number }) {
  const qc = useQueryClient();
  const key = ["org", orgId, "sso-role-mappings"];
  const mappings = useQuery({ queryKey: key, queryFn: () => listSsoRoleMappings(orgId) });
  const [appRole, setAppRole] = useState("");
  const [role, setRole] = useState<string>("member");
  const [fieldError, setFieldError] = useState("");

  const add = useMutation({
    mutationFn: () => createSsoRoleMapping(orgId, appRole.trim(), role),
    onSuccess: () => { setAppRole(""); setFieldError(""); qc.invalidateQueries({ queryKey: key }); },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) setFieldError("This app role is already mapped.");
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteSsoRoleMapping(orgId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFieldError("");
    add.mutate();
  }

  const addError = add.error != null && !(add.error instanceof ApiError && add.error.status === 409) ? add.error : null;

  return (
    <div className="card">
      <h2>Microsoft roles</h2>
      <p className="muted">
        People assigned to these app roles in Entra get the role below at each Microsoft sign-in. Owners are always granted by hand.
      </p>
      {mappings.error != null && <ErrorBanner error={mappings.error} onRetry={() => mappings.refetch()} />}
      {(addError ?? remove.error) != null && <ErrorBanner error={(addError ?? remove.error)!} />}
      {mappings.isPending && <p className="muted">Loading app roles…</p>}
      {mappings.data && mappings.data.length === 0 && <p className="muted">No app roles mapped yet.</p>}
      {mappings.data && mappings.data.length > 0 && (
        <table className="data">
          <thead>
            <tr><th>App role</th><th>QEOS role</th><th><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {mappings.data.map((m) => (
              <tr key={m.id}>
                <td><code>{m.app_role}</code></td>
                <td>{m.role}</td>
                <td>
                  <ConfirmButton
                    label="Remove"
                    ariaLabel={`Remove mapping ${m.app_role}`}
                    question={`Remove this mapping? Members keep their role until their next Microsoft sign-in.`}
                    confirmLabel="Remove"
                    onConfirm={() => remove.mutate(m.id)}
                    disabled={remove.isPending}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form className="inline-form" onSubmit={onSubmit}>
        <label>
          App role
          <input value={appRole} onChange={(e) => setAppRole(e.target.value)} placeholder="QEOS.Member" required maxLength={100}
            aria-invalid={fieldError ? "true" : undefined} aria-describedby={fieldError ? "sso-role-error" : undefined} />
        </label>
        <label>
          QEOS role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {MAPPED_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <button type="submit" disabled={add.isPending}>Add</button>
      </form>
      {fieldError && <p id="sso-role-error" className="field-error">{fieldError}</p>}
    </div>
  );
}
```

`pages/OrganizationPage.tsx`:
- import `MicrosoftRolesCard` and `microsoftEnabled` from `../auth/ssoProviders`;
- `const isOwner = me.data?.role === "owner";`
- in the members row, role cell: `<td>{member.role}{member.managed_by === "entra" && <> <span className="badge badge-muted" title="Managed by Entra" aria-label="Managed by Entra">Entra</span></>}</td>`;
- actions cell for a managed row: `<button type="button" disabled title="Managed by Entra: remove the app role instead.">Remove<span className="sr-only">Managed by Entra: remove the app role instead.</span></button>` instead of `ConfirmButton`;
- after the Invitations card: `{isOwner && microsoftEnabled() && <MicrosoftRolesCard orgId={id} />}`.

- [ ] **Step 4: Run to verify, then the dashboard gate**

Run: `npx vitest run src/components/MicrosoftRolesCard.test.tsx src/pages/OrganizationPage.test.tsx` → PASS. Then `npm run lint && npm run typecheck && npm run test && npm run build` and `node --test ../templates/github/qeos-run.test.mjs` → all PASS.

- [ ] **Step 5: Docs**

- `DESIGN.md`: under the Organization page, "Microsoft roles card" (owners only, Microsoft builds only; lead line; table App role mono / QEOS role / Remove with the destructive confirmation; add row; empty, loading, error states; duplicate as field error) and "Entra badge" (muted badge, `title` "Managed by Entra", disabled Remove with the reason as `title` and visually hidden text).
- `README.md` feature list: one bullet "Organization role from Entra" (app roles mapped per organization by its owners; kept in step at each Microsoft sign-in; owners always by hand).
- `PRODUCT.md` access model: one sentence on Entra app roles.
- `TODO.md`: tick `- [x] Map Entra groups / app roles to organization roles` with "(app roles, ADR-033, spec 2026-10-16; groups not planned)".
- `python scripts/check_architecture_docs.py` → passes.

- [ ] **Step 6: Commit, gate and push delivery 3**

```bash
git add dashboard/src DESIGN.md README.md PRODUCT.md TODO.md
git commit -m "feat(dashboard): owners map Entra app roles on the Organization page; managed members carry an Entra badge (ADR-033)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git fetch origin && git rebase origin/master
# if the rebase brought commits in, re-run Step 4's commands
git push origin HEAD:master
```

After delivery 3, rebuild locally: `docker compose up -d --build --wait organization-service auth-service dashboard` (organization-service and auth-service run their migrations at start).
