# Organization Service

Manages organizations (tenants) and their memberships for QEOS.

## Responsibilities

- Organization CRUD (`/api/v1/organizations`)
- Membership management (`/api/v1/organizations/{org_id}/members`) with roles:
  `owner`, `admin`, `member`, `viewer`, `billing_manager`. Only an owner may grant or
  remove a member with the `owner`/`admin` role. The member list carries each member's email,
  read from auth-service (best effort: blank when auth-service does not answer).
  `GET /api/v1/organizations/{org_id}/members/me` returns the caller's role; project-service,
  ingestion-service and test-management-service authorize through it.
- Email-based invitations (`/api/v1/organizations/{org_id}/invitations` to create/list/revoke,
  `GET /api/v1/invitations/{token}` for a signed-in user to preview it,
  `/api/v1/invitations/{token}/accept` to accept; valid 7 days, single use). This service does
  not send email -- the
  create response includes the invite `token`; delivering it is a separate concern (a
  frontend or notification-service's job). Whoever holds a valid, unexpired, unused invite
  token and is logged in may accept it; there is no email-match check against the invitee.
- Validates member `user_id`s against auth-service's internal API
  (`/internal/v1/users/{id}`, HTTP Basic with `INTERNAL_API_USERNAME`/`INTERNAL_API_PASSWORD`)
  before adding them: `404` means no such user; any other answer is a `502`, never a silent yes
  or no.
- Entra app roles (ADR-033). Owners map an app role value to `admin`, `member` or `viewer` (never
  `owner` or `billing_manager`):
  - `GET /api/v1/organizations/{org_id}/sso-role-mappings` lists `[{id, app_role, role, created_at}]`.
  - `POST` takes `{"app_role": "QEOS.Member", "role": "member"}` and answers 201. The value is 1 to 100
    characters after trimming. The same value twice (case-insensitive) answers 409 `duplicate_app_role`.
    An unknown role, `owner`, `billing_manager` or a blank value answers 422.
  - `DELETE .../{mapping_id}` answers 204, or 404 when the mapping is not this organization's.
  - Only owners may call these routes; a member with another role gets 403, and someone who is not a member gets 404.
  Deleting a mapping changes no member; the next Microsoft sign-in of each person does.
  - A mapping applies only after an active superuser approved the organization, because any user may create and own
    one. `PUT /api/v1/organizations/{org_id}/entra-sync` with `{"approved": true|false}` sets or clears the approval
    and answers the organization; `GET /api/v1/organizations/entra-sync` lists `[{id, name, slug, mappings,
    entra_sync_approved, entra_sync_approved_at}]` for organizations with a mapping or an approval. Both ask
    auth-service's internal API whether the caller is an active superuser: no answers 403, auth-service unreachable
    502. Superusers need not be members. Organizations carry `entra_sync_approved` so owners see the state.
    Revoking keeps the members Entra created and stops changing them.
- Managed members: a member created by a mapping has `managed_by: "entra"` (`null` for hand-made members).
  `DELETE .../members/{member_id}` on a managed member answers 409 `managed_by_entra`.
- Internal API, `POST /internal/v1/sso-roles`, called by auth-service after a Microsoft sign-in. HTTP Basic
  with `INTERNAL_CALLER_USERNAME` (default `auth-service`) and `INTERNAL_API_PASSWORD`. An empty password
  answers 503, wrong credentials 401. The body is `{"user_id": 7, "roles": ["QEOS.Member"]}`, at most 50
  roles (more answers 422). The answer is `{"changes": [{"organization_id", "action", "from", "to"}]}`,
  empty when nothing changed. Only approved organizations with a mapping are touched, and only members marked
  `managed_by = entra`. Each change is logged at INFO. The gateway does not route `/internal/`.
- Prometheus metrics at `/metrics` (not routed by the gateway).

## Tables

- `organizations`, `organization_members`, `organization_invitations`.
- `organization_members.managed_by` (migration 004): `NULL` for hand-made members, `entra` for members kept in
  step by the app-role mapping.
- `organization_sso_role_mappings` (migration 004): `organization_id`, `app_role` (up to 100 characters),
  `role` (`admin`, `member` or `viewer`). The pair (organization, lower-cased `app_role`) is unique.

## Auth model

This service does not issue tokens. It trusts JWTs signed by auth-service
(shared `SECRET_KEY`/`HS256`) and reads the user id from the `sub` claim.

## Out of scope (see docs/superpowers/specs/2026-09-16-organization-service-core-design.md)

- `organization_settings` (SSO/MFA/session config per org)

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env  # set SECRET_KEY to match auth-service's
alembic upgrade head
uvicorn src.organization.api.main:app --reload
```

## Testing

```bash
SECRET_KEY=test-secret pytest -v
```
