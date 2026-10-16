# Entra app roles to organization roles — design

Status: approach and sections approved in conversation 2026-10-16; pending review of this written spec.
Blueprint: auth-service (Identity), organization-service (Collaboration), dashboard; PostgreSQL only.
New ADR-033. Builds on ADR-031 (SSO-only mode, spec `2026-10-14-sso-only-mode-design.md`).

## 1. Goal and scope

A person who signs in with Microsoft gets their organization role from Entra ID, so joining, changing
role and leaving follow the company directory instead of a hand-made invitation. IT assigns people (or
groups) to **app roles** on the QEOS app registration; the ID token then carries a `roles` claim; QEOS maps
each app role value to a role of one organization and keeps the membership in step at every Microsoft
sign-in.

Decided with the user:

- **App roles, not security groups.** No group ids in QEOS, no 200-group overage, nesting handled by Entra.
- **The mapping is per organization, edited by its owners in the dashboard.** No tenant in the mapping:
  `AZURE_ALLOWED_TENANTS` is already the global allowlist.
- **A mapping grants `admin`, `member` or `viewer`, never `owner`** (and `billing_manager` is hidden for
  now). Owners stay a human decision: whoever edits app-role assignments in Entra must not be able to reach
  the mapping editor through it, and an organization always keeps at least one owner Entra cannot remove.
- **Entra-managed memberships follow the token** on every Microsoft sign-in: raised, lowered, or removed
  when no mapped app role remains. Memberships made by hand (invitations, the organization's creator) are
  never touched by a mapping.
- **Linking counts as a sign-in:** a password user who links Microsoft from Security gets the same
  reconcile at once.

Not changed: CI API keys and collector uploads, superusers, the Grafana session, project access (it still
follows the organization role), SSO-only mode. Google sign-in carries no roles and is not reconciled.

Not in scope: security groups, SCIM, personal Microsoft accounts, mapping to project-level rights,
removing memberships when a mapping is deleted (the next sign-in does it).

## 2. Today (for reference)

- `validate_microsoft_token` (auth-service, `sso_service.py`) verifies the v2.0 ID token and returns
  `email`, `full_name`, `provider`, `provider_user_id` (`"{tid}:{oid}"`). It reads no `roles`.
- `sso_sign_in` finds or creates the account and issues tokens. `POST /users/me/link/microsoft` links an
  identity to the signed-in account.
- organization-service owns `organization_members` (`role` in owner/admin/member/viewer/billing_manager,
  `status`), with `GET/POST /organizations/{id}/members`, `DELETE /organizations/{id}/members/{member_id}`
  (owner/admin), invitations, and `GET /organizations/{id}/members/me`. It calls auth-service's internal
  API (HTTP Basic, `INTERNAL_API_USERNAME`/`INTERNAL_API_PASSWORD`) to enrich members with emails. It has
  no internal API of its own; project-service has one (`require_internal_caller`, HTTP Basic), which is the
  pattern to copy.
- A new Microsoft user has no organization: an owner adds them by hand (SETUP §3.8 "New colleagues").

## 3. Rules

1. The token's `roles` claim is a list of app role values (strings). Absent or empty means "no app role".
   At most 50 values are kept (the rest ignored, logged once per sign-in at WARNING); each value is cut
   to 100 characters.
2. For each organization that has **at least one** mapping, the matching mappings are those whose
   `app_role` equals a token value, compared case-insensitively. The highest matching QEOS role wins:
   `admin` > `member` > `viewer`.
3. For that organization and user:
   - no member row, a match → a row is created: `role` = the winning role, `status` = active,
     `managed_by` = `entra`;
   - a row with `managed_by = entra`, a match → `role` set to the winning role when it differs;
   - a row with `managed_by = entra`, no match → the row is deleted;
   - a row with `managed_by` NULL (hand-made) → untouched, whatever the token says;
   - no row, no match → nothing.
4. Deleting a mapping, or all of them, does not touch members: the next Microsoft sign-in of each person
   reconciles them. The dashboard says so next to the delete action.
5. Organizations without any mapping are never touched, so a deployment that never configures mappings
   behaves exactly as today.
6. Every change made by rule 3 is logged at INFO by organization-service: `entra role: org=<id> user=<id>
   <created|updated|removed> <old>→<new> roles=<matched values>`.
7. Superusers are auth-service state; their organization memberships follow the same rules as anyone's.
8. A hand-made member who also has a mapped app role keeps the hand-made role. To hand them over to
   Entra, an owner removes them; their next sign-in re-creates them as managed.

## 4. auth-service

### 4.1 Token

`validate_microsoft_token` also returns `roles`: the `roles` claim when it is a list of strings, else
`[]`, after rule 1. `verify_microsoft_credential` passes it through.

### 4.2 Storage

Migration 009: `oauth_accounts` gains `sso_roles` (JSON, nullable: the last list received),
`sso_roles_at` (timestamptz, nullable) and `sso_roles_synced_at` (timestamptz, nullable). JSON is used
instead of an array type so SQLite (tests) and PostgreSQL both work, as elsewhere in auth-service.

### 4.3 Sync call

After a successful `POST /sso/microsoft` and after a successful `POST /users/me/link/microsoft`:

1. `sso_roles` = the roles, `sso_roles_at` = now, on the Microsoft `OAuthAccount` row (committed with the
   sign-in).
2. `POST {ORGANIZATION_SERVICE_URL}/internal/v1/sso-roles` with HTTP Basic
   (`INTERNAL_API_USERNAME` = `auth-service`, `ORGANIZATION_INTERNAL_API_PASSWORD`), body
   `{"user_id": <int>, "roles": [<str>...]}`, timeout 5 s.
3. 2xx → `sso_roles_synced_at` = now. Anything else (connection error, timeout, 5xx, 401) → WARNING
   `entra role sync deferred: user=<id> reason=<...>`; the sign-in still succeeds and returns tokens.

**Retry on refresh.** `POST /auth/refresh` (`refresh_access_token`) looks at the user's Microsoft
`OAuthAccount`: when `sso_roles_at` is set and `sso_roles_synced_at` is NULL or older than
`sso_roles_at`, it repeats steps 2-3 with the stored roles before answering. Refresh runs at most every
`ACCESS_TOKEN_EXPIRE_MINUTES` (60), so a sync missed at sign-in heals within the hour without a job. A
failed retry never fails the refresh.

### 4.4 Settings

| Setting | Default | Meaning |
|---|---|---|
| `ORGANIZATION_SERVICE_URL` | `http://organization-service:8000` | Where the sync call goes. |
| `ORGANIZATION_INTERNAL_API_PASSWORD` | empty | HTTP Basic password for organization-service's internal API. Empty: the sync is skipped with one WARNING at start-up ("Entra app roles are not applied"), so a deployment without the setting keeps working. |

docker-compose.yml passes both to auth-service; the password is `${INTERNAL_API_PASSWORD}` (the one
secret every internal API shares in the local stack, as project-service and ingestion already do).

## 5. organization-service

### 5.1 Storage

Migration 004:

- `organization_sso_role_mappings`: `id`, `organization_id` (FK organizations, ON DELETE CASCADE),
  `app_role` (varchar 100, not blank), `role` (varchar 50, CHECK in `admin`, `member`, `viewer`),
  `created_at`, `updated_at`; UNIQUE on `(organization_id, lower(app_role))` (a functional unique index
  on PostgreSQL; the service also checks before insert, for SQLite tests).
- `organization_members.managed_by` (varchar 20, nullable, CHECK IN (`entra`) or NULL). NULL for every
  existing row.

### 5.2 Mapping API (owners only, `require_org_role("owner")`)

| Route | Body / answer |
|---|---|
| `GET /organizations/{id}/sso-role-mappings` | `[{id, app_role, role, created_at}]`, ordered by `app_role`. |
| `POST /organizations/{id}/sso-role-mappings` | `{app_role: 1-100 chars after strip, role: admin\|member\|viewer}` → 201 with the row. 409 `{"code": "duplicate_app_role"}` when the same value exists for the organization (case-insensitive). 422 for `owner`, `billing_manager`, an unknown role, or a blank value. |
| `DELETE /organizations/{id}/sso-role-mappings/{mapping_id}` | 204. 404 when it is not this organization's. |

Non-owners get 404 for the organization as everywhere ("not found, never forbidden").

### 5.3 Members API changes

- `MemberOut` gains `managed_by: "entra" | null`.
- `DELETE /organizations/{id}/members/{member_id}` on a row with `managed_by = entra` answers 409
  `{"detail": {"code": "managed_by_entra", "message": "Managed by Entra: remove the app role instead."}}`.
- `POST /organizations/{id}/members` (add by hand) for a user who already has a managed row answers 409
  as today for an existing member (no change).

### 5.4 Internal API

`POST /internal/v1/sso-roles`, HTTP Basic with `INTERNAL_API_USERNAME` (`auth-service`) and
`INTERNAL_API_PASSWORD`, copied from project-service's `require_internal_caller` (empty password → 503,
never open). Body `{"user_id": int, "roles": [str]}` (at most 50 values; more → 422). Applies section 3
in one transaction and answers 200 `{"changes": [{organization_id, action, from, to}]}` (empty list when
nothing changed). Not routed by the gateway (`/internal/` is never exposed; same as project-service).

## 6. Dashboard

### 6.1 Organization page, "Microsoft roles" card (owners only)

Under Invitations. Shown only when the build has Microsoft sign-in (`microsoftEnabled()`), since the
card is meaningless otherwise. Content, from `GET /sso-role-mappings`:

- Lead line: "People assigned to these app roles in Entra get the role below at each Microsoft sign-in.
  Owners are always granted by hand."
- Table: App role (mono), QEOS role (word), Remove (destructive confirmation "Remove this mapping?
  Members keep their role until their next Microsoft sign-in."). Empty state: "No app roles mapped yet."
- Add row: text field "App role" (placeholder `QEOS.Member`), select "QEOS role" (admin, member, viewer),
  button Add. 409 → field error "This app role is already mapped."; other errors → Error Banner.
- Loading: skeleton rows; failure: Error Banner with Retry inside the card.

### 6.2 Members table

- A managed member shows a muted "Entra" badge after the role (tooltip and accessible name "Managed by
  Entra").
- Its Remove button is disabled, with the reason as `title` and a visually hidden text: "Managed by Entra:
  remove the app role instead." The 409 from the API shows the same sentence if it ever arrives.

No change to the sign-in pages or SSO-only mode.

## 7. Documentation

- ADR-033 (template, INDEX): decision, alternatives (security groups; fixed role names; reconcile
  everyone; additive only; dashboard passes the token on).
- SETUP §3.8 gains "App roles": IT steps (App registration → App roles → create `QEOS.Admin`,
  `QEOS.Member`, `QEOS.Viewer` for Users/Groups; Enterprise application → Users and groups → assign;
  the `roles` claim needs no optional-claim configuration), the QEOS side (owner maps values on the
  Organization page), the rules of section 3 in plain words, and the new settings in the table.
- README feature list, PRODUCT (access model), TECHNICAL_SPECIFICATION (organization-service section,
  internal API, migrations), SECURITY (what Entra can grant and cannot; the internal API; logging), TODO
  (tick "Map Entra groups / app roles to organization roles"), service READMEs (auth: settings and the
  sync; organization: tables, routes, internal API), DESIGN (the card and the badge).

## 8. Testing

- auth-service unit: `roles` parsed, absent, non-list, over 50, long values; sign-in stores roles and
  calls the sync (httpx mocked); sync failure leaves the sign-in a 200 and `sso_roles_synced_at` NULL;
  refresh retries while unsynced and stops once synced; linking syncs; Google sign-in never calls.
- organization-service integration: mapping CRUD, owner-only (admin → 404), duplicate 409, `owner`
  422; internal endpoint auth (no password → 503, wrong → 401); reconcile creates, raises, lowers,
  removes; hand-made untouched; highest wins across several matches; several organizations at once;
  organization without mappings untouched; `managed_by` in `MemberOut`; delete of a managed member 409;
  the log lines.
- dashboard: the card renders for owners with Microsoft enabled, hidden otherwise; add, duplicate 409,
  remove with confirmation; members badge and disabled Remove; `OrganizationPage` existing tests still
  pass.

## 9. Delivery

Three commits on master, each with its docs: (1) organization-service (migration 004, mapping API,
members changes, internal API) — deployable alone, nothing calls it yet; (2) auth-service (migration 009,
token roles, sync, refresh retry, compose settings); (3) dashboard. ADR-033 goes with (1). The gate for
each is the CI steps of the services it touches.
