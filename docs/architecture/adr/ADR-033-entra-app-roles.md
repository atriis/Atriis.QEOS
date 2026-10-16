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
IT administrators of the Entra tenant, organization owners, every QEOS user, security reviewers.

## Constraints
PostgreSQL only; auth-service owns sign-in and organization-service owns memberships, so the two talk over
the internal API (HTTP Basic, never routed by the gateway).

## Assumptions
The QEOS app registration lists app roles and IT assigns people or groups to them. The tenant is already on
the `AZURE_ALLOWED_TENANTS` allowlist.

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
- auth-service sends the roles to `POST /internal/v1/sso-roles` of organization-service. A failed call is
  logged, never fails the sign-in, and is repeated on refresh.
- Every change is logged at INFO by organization-service.

## Success Metrics / Evaluation Criteria
A person assigned to an app role gets the mapped role at their next Microsoft sign-in without an
invitation. A person who loses the app role loses the managed membership within 60 minutes. No change to
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
- A removed app role takes effect at the person's next sign-in or refresh, not at once.

---

# Implementation

## Affected Components/Services
organization-service: migration 004, `OrganizationSsoRoleMapping`, `OrganizationMember.managed_by`,
`sso_role_service`, mapping routes, `POST /internal/v1/sso-roles`, members `DELETE`. auth-service: token
`roles`, sync call, refresh retry (migration 009). Dashboard: the "Microsoft roles" card and the "Entra" badge.

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
existing row).

---

# Risks

| Risk | Mitigation |
|------|------------|
| An Entra editor reaches the mapping editor | Mappings never grant `owner`; only owners edit them |
| A mapping change removes people by mistake | Nothing changes until each person's next sign-in; every change is logged |
| The sync call fails | Sign-in succeeds; retried on refresh within 60 minutes |

---

# Related Decisions
- ADR-031: SSO-only mode
- ADR-016: SSO sign-ins bypass platform MFA

---

# Change Log
| Date | Version | Description |
|------|---------|-------------|
| 2026-10-16 | 1.0 | Initial version |

---

# References
- `docs/superpowers/specs/2026-10-16-entra-app-roles-design.md`
- `docs/SETUP.md` §3.8

---

# Review
When SCIM provisioning is built, or when `owner` should be grantable from Entra.
