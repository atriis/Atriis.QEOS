# ADR-033: Entra app roles map to organization roles

- Status: Accepted
- Date: 2026-10-16
- Authors: QEOS maintainers
- Decision Owner: Platform owner
- Supersedes: None
- Superseded By: None

Spec: `docs/superpowers/specs/2026-10-16-entra-app-roles-design.md`

---

# Context

## Business Problem
A person who signs in with Microsoft should get their organization role from the company directory. Joining,
changing role and leaving should follow Entra ID, not a hand-made invitation.

## Technical Problem
Microsoft sign-in (ADR-031) proves who the person is, but a new Microsoft user has no organization, and an
owner must add each colleague by hand. The ID token can carry the person's Entra app roles in its `roles`
claim, and QEOS ignores it today.

## Architectural Drivers
- Directory-controlled access for people; CI keys and service calls unchanged.
- Whoever edits assignments in Entra must not be able to take over an organization.
- A deployment that configures nothing behaves exactly as today.

## Stakeholders
IT administrators of the Entra tenants, organization owners, every QEOS user, security reviewers.

## Constraints
PostgreSQL only; auth-service owns sign-in and organization-service owns memberships, so the two talk over
the internal API (HTTP Basic, never routed by the gateway).

## Assumptions
The QEOS app registration lists app roles and IT assigns people or groups to them. The tenants that sign in
are already on the `AZURE_ALLOWED_TENANTS` allowlist, and every one of them is trusted to assign these roles.

## Architecture Principles
One owner per concern, least privilege, fail safe (a missed sync never blocks a sign-in).

## Quality Attributes Involved
Security, operability, auditability.

---

# Decision

IT assigns people to app roles on the QEOS app registration. The ID token carries them in `roles`. Each
organization owner maps app role values to a QEOS role. At every Microsoft sign-in, and when a password
user links Microsoft, QEOS keeps the memberships in step.

- App roles, not security groups. The mapping is per organization and edited by its owners only.
- A mapping grants `admin`, `member` or `viewer`, never `owner` (`billing_manager` is not offered).
- Per organization that has at least one mapping, the matching mappings are those whose `app_role` equals a
  token value, compared case-insensitively. The highest match wins: `admin` > `member` > `viewer`.
- No member row and a match: a row is created with `managed_by = entra`.
- A managed row and a match: the role is set to the winning role when it differs.
- A managed row and no match: the row is deleted.
- A hand-made row (`managed_by` NULL): never touched, whatever the token says.
- An organization without any mapping is never touched. Deleting a mapping touches no member; the next
  sign-in of each person reconciles them.
- A managed member cannot be removed by hand: `DELETE` answers 409 `managed_by_entra`.
- An organization is reconciled only after an active superuser approved it (amendment of 2026-10-17, below).
  Until then its mappings change nobody, and revoking the approval stops the sync and keeps the members it made.
- auth-service sends the roles to `POST /internal/v1/sso-roles` of organization-service. A failed call is
  logged, never fails the sign-in, and is repeated on refresh.
- Every change is logged at INFO by organization-service.

## Success Metrics / Evaluation Criteria
A person assigned to an app role gets the mapped role at their next Microsoft sign-in without an
invitation. A person who loses the app role loses the managed membership at their next Microsoft sign-in. No change to
a hand-made member or to an organization without mappings.

## Scope
Memberships of people who sign in with Microsoft. Not: CI API keys, collector uploads, superusers, the
Grafana session, project access (it still follows the organization role), Google sign-in, SCIM.

## Affected Components/Services/Domains
organization-service (Collaboration), auth-service (Identity), dashboard.

## Implementation Boundaries
organization-service owns the mapping, the reconcile rules and the log lines. auth-service only reads
`roles` from the verified token and passes them on. The gateway never routes `/internal/`.

---

# Alternatives Considered

## Security groups
### Pros
- Groups already exist in most tenants.
### Cons
- A token lists at most 200 groups, then switches to an "overage" link that needs Microsoft Graph.
- QEOS would store and show raw group GUIDs.
### Decision
Not Selected
### Rejected because
App roles have readable values, no overage, and Entra handles nesting.

## Fixed role names in auth-service
### Pros
- No mapping to store or edit.
### Cons
- One mapping for every organization.
### Decision
Not Selected
### Rejected because
Organizations on one deployment need different mappings, and owners should edit their own.

## Reconcile everyone
### Pros
- One simple rule: the token is the truth.
### Cons
- A hand-made owner would lose access when Entra omits them.
### Decision
Not Selected
### Rejected because
Hand-made memberships must stay safe; only rows marked `managed_by = entra` follow the token.

## Additive only
### Pros
- Never removes anything.
### Cons
- Leaving a role in Entra would do nothing in QEOS.
### Decision
Not Selected
### Rejected because
Leaving and role changes must follow the directory.

## The dashboard passes the token to organization-service
### Pros
- No internal call from auth-service.
### Cons
- organization-service would need a second token verifier and the tenant settings.
### Decision
Not Selected
### Rejected because
auth-service already verifies the token; one owner per concern.

---

# Consequences

## Positive
- Joining, changing role and leaving follow the company directory.
- Deployments that configure nothing are unchanged.

## Negative
- Entra can grant at most admin. An organization keeps at least one hand-made owner.
- Managed members cannot be removed by hand; the app role is removed in Entra instead.
- Sync is best effort. A missed sync heals on the next refresh, within 60 minutes.
- A removed app role takes effect at the person's next Microsoft sign-in, not at once. A refresh never asks Entra again: it only re-sends roles already stored while a push is pending.
- A session the person already holds lasts until its refresh token expires (30 days); see the known limitation in SETUP section 3.8.
- A linked user who signs in with a password (outside SSO-only mode) is not reconciled at that sign-in.

---

# Implementation

## Affected Components/Services
organization-service: migrations 004 and 005, `OrganizationSsoRoleMapping`, `OrganizationMember.managed_by`,
`Organization.entra_sync_approved_at`, `sso_role_service`, mapping and approval routes, `POST /internal/v1/sso-roles`,
members `DELETE`. auth-service: token
`roles`, sync call, refresh retry (migration 009), `is_superuser` in the internal user lookup. Dashboard: the
"Microsoft roles" card with its approval status, the "Entra" badge, and the superusers' "Microsoft roles approval"
card on the Security page.

## Affected Domains
Identity, Collaboration.

## Deployment Implications
organization-service gains `INTERNAL_CALLER_USERNAME` (default `auth-service`). Its `INTERNAL_API_PASSWORD`
must be set, or the internal endpoint answers 503. Deploy organization-service first; nothing calls it
until auth-service is updated.

## Operational Considerations
Watch the INFO lines `entra role: org=<id> user=<id> <created|updated|removed> <old>-><new> roles=<values>`
and the auth-service WARNING `entra role sync deferred`.

## Migration Considerations
Migration 004 adds `organization_sso_role_mappings` and `organization_members.managed_by` (NULL for every
existing row). Migration 005 adds the approval columns. Deploy auth-service (`is_superuser` in its internal user
lookup) before organization-service, or approvals answer 403.

---

# Risks

| Risk | Mitigation |
|------|------------|
| An Entra editor reaches the mapping editor | Mappings never grant `owner`; only owners edit them |
| Any user creates an organization, maps a common app role, and Entra pulls everyone holding it into that organization (a membership the person cannot leave, and their email addresses in the member list) | Found in a review on 2026-10-17. A superuser approves each organization before reconcile touches it (amendment below) |
| A mapping change removes people by mistake | Nothing changes until each person's next sign-in; every change is logged |
| The sync call fails | Sign-in succeeds; retried at the next token refresh while the push is pending |
| An administrator of one allowed tenant grants roles in every organization | `AZURE_ALLOWED_TENANTS` may list several tenants and a mapping carries no tenant, so an administrator of any allowed tenant can grant every mapped role in every organization that maps that value. List only tenants you trust that much; mappings scoped to a tenant are on the TODO list |

---

# Amendment 2026-10-17: a superuser approves each organization

**Problem.** Any active user may create an organization and own it. An owner's mapping alone let that user make
Entra add every person holding a mapped app role (the values are documented) to their organization, as a managed
member nobody can remove by hand, and read those people's email addresses in its member list. No data of the
people's own organizations was reachable.

**Decision.** reconcile touches an organization only when `organizations.entra_sync_approved_at` is set. An active
superuser sets or clears it with `PUT /api/v1/organizations/{id}/entra-sync` `{"approved": true|false}`, and lists
the organizations that have a mapping or an approval with `GET /api/v1/organizations/entra-sync`. organization-service
asks auth-service's internal API whether the caller is an active superuser at each call (the access token carries
only `sub`); auth-service unreachable answers 502 and changes nothing. Owners still edit their own mappings and see
whether their organization is approved (`entra_sync_approved` on the organization).

- Revoking stops the sync. Members Entra created stay, still managed, and no sign-in changes them.
- Migration 005 adds `entra_sync_approved_at` and `entra_sync_approved_by`, NULL for every organization: mappings
  made before it stay paused until a superuser approves.
- Each approval and revocation is logged at WARNING with the organization and the superuser.

**Alternatives.** Superusers alone edit mappings: superusers are rarely members of every organization, and owners
know their own roles. App role values named after the organization (`QEOS.<slug>.Member`): IT's assignment would be
the approval, but IT would create roles per organization. A deployment allowlist in `.env`: a restart per
organization.

---

# Related Decisions
- ADR-031: SSO-only mode
- ADR-016: SSO sign-ins bypass platform MFA

---

# Change Log
| Date | Version | Description |
|------|---------|-------------|
| 2026-10-16 | 1.0 | Initial version |
| 2026-10-17 | 1.1 | Amendment: Entra role sync per organization needs a superuser's approval |

---

# References
- `docs/superpowers/specs/2026-10-16-entra-app-roles-design.md`
- `docs/SETUP.md` §3.8

---

# Review
When SCIM provisioning is built, or when `owner` should be grantable from Entra.
