# ADR-033: Project deletion — 7 days pending and restorable, then purged in every service

Status: Accepted (2026-10-16) · Spec: `docs/superpowers/specs/2026-10-16-project-deletion-design.md`

## Context

Projects could be soft-deleted through the API only. There was no confirmation and no restore. The retention job
revoked the keys at once and emptied ingestion's runs after 7 days, but left test-management's data and the project
row behind for ever.

## Decision

- **Delete.** Owners and admins delete a project from Settings → Data after typing its name exactly. project-service
  records `deleted_at` and `deleted_by`. A project on legal hold cannot be deleted (409).
- **Pending.** For `PROJECT_DELETE_GRACE_DAYS` (7) the project is pending:
  - `GET /api/v1/projects/{id}` answers 410 with `{code: "pending_deletion", organization_id, deleted_at,
    deleted_by, purge_at}` to every member, so the dashboard shows a notice with the date. Every other route of it
    answers 404, and non-members always get 404. Other services read 410 as "not found".
  - Owners and admins list it with `include_pending=true` (each row carries `deletion`), greyed with **Restore**.
    Members never get it from a list.
  - `POST /api/v1/projects/{id}/restore` (owners and admins) brings it back as it was, API keys included. A name or
    slug taken meanwhile by a live project answers 409: rename that one first.
  - Nothing is deleted during the window: retention skips the project, and keys are not revoked. Uploads answer
    410 "Project scheduled for deletion" (ingestion reads the internal feed, cached 60 s, failing open).
- **Purge.** After the window the ingestion retention job purges it, each step recorded in
  `projects.purge_state` through project-service's internal API:
  1. `started`: refused (409) for a live project; once recorded, a restore is refused. This is the one atomic
     check between a restore and the purge.
  2. `test_management`: test-management's internal `DELETE /internal/v1/projects/{id}` removes cases, labels,
     suites, feature files, run requests and the CI target.
  3. `ingestion`: runs, results, log values and patterns, masking patterns, API keys, settings, channels, muted
     tests, rollups and impact data.
  4. The project row, overview layouts and repositories, through project-service's internal
     `DELETE /internal/v1/projects/{id}`, accepted only once both data steps are recorded.

  A failed step leaves the project pending with what was done recorded; the next pass resumes there. The pass then
  reports the failure in its heartbeat. Without `TEST_MANAGEMENT_INTERNAL_URL` nothing is purged, and each pass
  says so.

## Consequences

- Deleting is reversible for 7 days and final after. The export is offered before deleting.
- Uploads now read project-service's internal feed once a minute. A project-service outage never stops them.
- `RETENTION_DELETED_GRACE_DAYS` is replaced by `PROJECT_DELETE_GRACE_DAYS`, set once in compose for
  project-service and the retention job. `TEST_MANAGEMENT_INTERNAL_URL` is new. The retention summary drops
  `keys_revoked` and gains `projects_purged` and `purge_failures`.
- The confirmation is in place, like every destructive action (DESIGN.md: no modal).
