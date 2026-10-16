# Project deletion: confirm, 7 days pending, restore, then purge everywhere — design

Status: design agreed in conversation 2026-10-16; pending review of this written spec.
Blueprint: Platform (project-service), Intelligence (ingestion retention), Execution (test-management), dashboard.
New ADR-034 (replaces the 7-day grace described in SETUP §4.7).

## 1. Goal and scope

Owners and admins can delete a project from the dashboard. Deleting asks for confirmation, then the project waits
7 days, greyed out and restorable by any owner or admin of its organization. After 7 days everything that
belongs to the project is deleted, in every service, for good.

What exists today: `DELETE /api/v1/projects/{id}` (owners and admins) sets `deleted_at`; the project disappears from
lists and answers 404; ingestion retention revokes its keys on the next pass and deletes its runs after 7 days. There
is no dashboard button, no confirmation, no restore, and test-management data and the project row are never removed.

Not in scope: deleting an organization (it has its own soft delete), deleting a single run, scheduling a deletion
for a later date, changing the 7 days from the dashboard.

## 2. States

| State | `deleted_at` | Who sees it | What works |
|---|---|---|---|
| Live | null | every member | everything |
| Pending deletion | set, less than 7 days ago | owners and admins: in the project list, greyed; others: a notice page on its URLs | Restore; nothing else |
| Purged | row gone | nobody | nothing |

`PROJECT_DELETE_GRACE_DAYS` (default 7, decided 2026-10-16) sets the window, in project-service and in the purge
job; it replaces ingestion's `RETENTION_DELETED_GRACE_DAYS` (same default, so nothing changes for existing setups).

## 3. project-service

- Migration: `projects.deleted_by` (integer, nullable) and `projects.purge_state` (JSON, nullable: which services
  confirmed their part, see §5).
- `DELETE /api/v1/projects/{id}` (owners and admins): sets `deleted_at` now and `deleted_by` the caller. 409
  `"Release the legal hold before deleting this project"` while a legal hold is on. Deleting a pending project again
  changes nothing (204). A legal hold cannot be placed on a pending project (409).
- `POST /api/v1/projects/{id}/restore` (owners and admins of the project's organization): clears `deleted_at`,
  `deleted_by`, `purge_state`; 200 with the project. 404 when the project is live or already purged.
- `GET /api/v1/organizations/{org}/projects` gains `include_pending=true`: owners and admins of the organization then
  also get pending projects, each with `deletion: {"deleted_at", "deleted_by", "deleted_by_name", "purge_at"}`. Other
  roles never get pending projects.
- `GET /api/v1/projects/{id}` for a pending project: 410 `{"detail": {"code": "pending_deletion", "purge_at": …,
  "deleted_by_name": …}}` for every member (so the dashboard can show the notice page instead of a bare 404). Every
  other project route answers 404 as today. A non-member still gets 404.
- The membership check other services call (`check_project_role`) keeps answering "no access" for a pending
  project: test-management and ingestion refuse its requests without knowing about deletion.

## 4. Uploads and keys during the 7 days

Ingestion asks project-service whether the key's project is pending (the internal retention feed already carries
`deleted` and `deleted_at`; a cached lookup per upload, 60 s). A pending project's upload answers 410 `"Project
scheduled for deletion"`; nothing is stored. Keys are not revoked during the window, so a restore brings them back
as they were. The collector already treats a refused upload as a warning, never a failed pipeline, by default.

## 5. The purge

After `PROJECT_DELETE_GRACE_DAYS`, the ingestion retention job (it already runs on a loop under an advisory lock and
reads the internal project feed) purges the project, in this order, each step idempotent:

1. **test-management:** new internal endpoint `DELETE /internal/v1/projects/{id}` (HTTP Basic, the internal
   credentials) deletes the project's cases, steps, labels, suites, folders, feature imports, run requests and CI
   target. 204, also when nothing was there.
2. **ingestion:** runs, results, logs, log values, log patterns, masking patterns, API keys, collection settings,
   notification channels, impact data, muted tests, rollups.
3. **project-service:** new internal endpoint `DELETE /internal/v1/projects/{id}` deletes the overview layouts,
   repositories, memberships and the project row. Called only after steps 1 and 2 succeeded.

Each confirmed step is recorded in `purge_state` (through `POST /internal/v1/projects/{id}/purge-state`), so a pass
that fails halfway resumes where it stopped on the next pass. No legal hold can exist on a pending project (§3), so the purge never meets one. A restore that
races with a purge: the purge re-reads `deleted_at` before step 1 and before step 3 and stops if it is cleared.

The pass logs one JSON line per purged project (`{"event": "project_purged", "project_id", "steps"}`) and the job
heartbeat stays as today.

## 6. Dashboard

- **Settings → Data → Delete project** (owners and admins; a danger zone at the end of the Data card). A dialog:
  what is deleted ("its runs, results, logs, test cases, suites, API keys and settings"), when ("permanently on
  23 Oct 2026, 14:05; until then any owner or admin can restore it"), a link to **Download all results** first, and a
  field "Type the project name to confirm". **Delete project** (danger button) is enabled only when the name matches
  exactly. Under a legal hold the button is disabled with the reason.
- After deleting: back to the organization's project list.
- **Project list (owners and admins):** pending projects stay in the list, greyed (muted text, no link), with a
  badge "Deletion pending · removed on 23 Oct, 14:05 · deleted by Pedro Carneiro" and a **Restore** button. Restore
  asks no confirmation (it only undoes) and returns the project to normal at once.
- **A pending project's URL:** owners and admins see the same badge with Restore; other members see "This project is
  scheduled for deletion on 23 Oct 2026, 14:05. Ask an owner or admin if this is a mistake."
- The project picker and the switcher leave pending projects out.

## 7. Testing

- project-service: delete sets `deleted_by`; delete under legal hold 409; delete twice is 204; restore by owner,
  admin (200), by member/viewer (403/404); restore of live or purged 404; `include_pending` only for owners/admins;
  410 body for a pending project's `GET`; internal delete removes row, memberships, layouts, repositories; purge
  state round-trip; migration up/down.
- test-management: internal delete removes every kind of row of that project and nothing of another; 204 on empty;
  401 without the internal credentials.
- ingestion: upload to a pending project 410, nothing stored; purge after the grace (and not before) in order; a
  failed test-management step leaves the project for the next pass and resumes from `purge_state`; a restored project
  is never purged; legal hold blocks it; everything of the project gone, nothing of another touched.
- dashboard: delete dialog (name must match, legal hold disables, export link, danger button), navigation after
  delete, greyed row with badge and Restore for owners/admins, hidden for members, the pending notice page for
  members, Restore round trip; lint, typecheck, build.
- Gateway smoke: create a throwaway project, delete it, it is listed pending with `include_pending`, restore it.

## 8. Documentation

ADR-034. SETUP §4.7 (replace the 7-day text: delete, 7 days pending, restore, purge everywhere), SECURITY (data deletion), PRODUCT,
TECHNICAL_SPECIFICATION (endpoints, states, `PROJECT_DELETE_GRACE_DAYS`), DESIGN (dialog, greyed row, notice page),
the project-service, ingestion and test-management READMEs, `.env.example`.

## 9. Delivery

One delivery on master after the full CI mirror: project-service (migration, endpoints), test-management (internal
delete), ingestion (410 on upload, purge), dashboard, docs and smoke.
