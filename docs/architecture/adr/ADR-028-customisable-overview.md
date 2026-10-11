# ADR-028: The customisable Overview: layouts in project-service, one shared widget catalogue, "my" widgets matched by name

Status: Accepted (2026-10-11) · Spec: `docs/superpowers/specs/2026-10-11-customisable-overview-design.md` · Plan: `docs/superpowers/plans/2026-10-11-customisable-overview.md`

## Context
The Overview used to be four fixed cards. Roles want different first screens: a QA lead wants trends
and the report, while a developer wants their branch and what is failing now. Projects need different
things too, such as a suite with many flaky tests or one that moves fast. Two existing items ask for
the same thing:
- the blueprint's "interactive dashboards with customizable widgets" (Enhanced Collaboration);
- v2 backlog F, "Personal dashboard: my suites, my recent failures".

Everything a widget shows is already computed by ingestion's analytics, the Report or test management.
Nothing new is measured, and no widget uses AI.

## Decision
- **Layouts live in project-service**, in the table `overview_layouts` (migration 004).
  - **Rows.** Each project has at most one project default (`user_id` NULL, a partial unique index). Each user has at most one personal layout per project (unique `project_id, user_id`). Each row is a JSONB layout with a `version`.
  - **What `GET /projects/{id}/overview-layout` returns.**
    - The effective layout, resolved as personal, then project default, then built-in. For built-in it returns `effective: null`, because the dashboard holds the built-in four cards.
    - The project default's own layout. Reset needs it, and so does "Edit project default" for an owner who has a personal layout.
  - **Roles.** Every role may save and reset a personal layout. Owners and admins set the project default.
  - **Access checks.** The project role is checked on every request, so a person who left the organization never gets their personal layout served. Such rows are not cleaned up, since each is a few KB. A soft-deleted project's layouts answer 404, and a hard delete cascades.
- **Optimistic versions.**
  - A save names the version it started from; version 0 creates the row.
  - A stale save gets a 409 whose detail carries the stored `{version, updated_by, updated_at}`. The editor turns that into **Reload** or **Overwrite**.
  - Reset deletes the stored layout rather than saving a copy, so later changes to the default still arrive.
  - `DELETE /project` carries no version yet (TODO.md follow-up).
- **One widget catalogue file**, `shared/qeos_shared/overview_widgets.json`, holds:
  - the 14 types, their settings and the allowed values;
  - the limits: 24 widgets and a **64 KB** body. 16 KB in the first spec would have refused layouts that every field rule allows: 24 widgets with 255-character branch and author names in multibyte UTF-8 reach about 49 KB.

  Both sides read the same file:
  - project-service validates against it (`qeos_shared.overview_widgets.load_catalog()`);
  - the dashboard registry imports it, and the dashboard Dockerfile copies it;
  - a dashboard test fails when the registry and the file disagree.
- **An absent `branch` setting means all branches.** There is no `"all"` value, so a git branch named `all` stays selectable.
  - **Trends and Runs links** then name no branch.
  - **Report links** pass `branch=*`, because the Report reads no branch as the default branch.
- **Widgets reuse the owning screen's query under the same key.** Two identical widgets, or a widget and its full view, therefore cost one request.
  - Report widgets send only their own section to `POST /analytics/report`:
    - Failure causes sends `failure_causes`, and Regressions sends `regressions`.
    - Slowest tests sends `summary` and reads `summary.slowest`, because the `duration` section has no per-test rows.
    - Coverage sends `tests` and joins the Report's case areas, across all branches.
  - Run widgets poll every 30 seconds (ADR-021).
  - Each widget is code-split and fails in its own card.
- **Refresh on a new run is registry-driven.**
  - Each widget definition declares `staleKeys`: the query-key prefixes of its figures that are not polled.
  - When the latest run changes, the Overview invalidates the page's own keys, then each widget's keys.
  - A key that a broader one already covers is dropped, so no query is refetched twice.
- **"My" widgets match by name.** The collector stores the commit author's name (`git log --format=%an`), not an email.
  - My recent failures asks the runs list for `status=failing&author=<name>`.
    - The name is the person's QEOS full name by default, or the name as git records it, set in the widget's settings. A stored setting of only spaces counts as unset.
    - The API's author filter is a substring match, so the widget then keeps only runs whose author is exactly that name, ignoring case and surrounding spaces. "Ann" does not show Joanna's runs.
    - Without a name it explains and sends no request, because an empty author would match every run.
  - My suites uses test management's `GET /suites?created_by=me`.

## Deviations from the first spec (spec §9)
- `GET` also returns the project default's `layout`.
- A soft-deleted project's layouts answer 404; the cascade applies to a hard delete.
- The project export does not include the project default. See Consequences.
- My recent failures uses the runs API's `status=failing`.
- Slowest tests reads `summary.slowest`.
- Coverage uses the `tests` section plus case areas, across all branches.
- Branch health shows each branch's pass rate, runs and last run over 30 days, newest first. The Branches API has aggregates and last-seen times, not a latest verdict.
- No "N new runs" announcement was added to the Overview; that lives on Runs. The 30-second refresh is kept.
- In view mode, a widget with nothing to show offers **Change settings**, which opens Customise on that widget.
- Cancel asks "Discard your changes?". Navigation and closing the tab reuse the existing unsaved-changes guard.
- In project mode, the reset button reads "Reset to built-in default".
- The body limit is 64 KB, not 16 KB.
- An absent `branch` means all branches.

## Alternatives rejected
- **Layouts in browser storage:** no project default, and nothing follows a person to another machine.
- **A layout store outside project-service:** layouts belong to a project and its roles, and project-service already answers who may do what in a project.
- **Separate widget lists in Python and TypeScript:** they would drift. One file plus a check test keeps them equal.
- **Matching "my" by email now:** it needs a collector field, an ingestion column and a migration. It is tracked in TODO.md.
- **A fixed list of keys to refresh on a new run:** every new widget would have to remember to edit it. Declaring the keys with the widget keeps them together.
- **Drag-and-drop placement, a widget marketplace, cross-project dashboards:** out of scope (spec §8). Move up/down and wide/normal cover the need with keyboard-first controls.

## Consequences
- **Gateway:** unchanged. `/api/v1/projects/{id}/overview-layout` falls under the existing project-service location, and the smoke test proves the route.
- **Project export:** ingestion's NDJSON export does not include the project default yet. That needs project-service data in the export (TODO.md follow-up).
- **Name matching:**
  - A name shared by two committers, or a changed git name, can mislead My recent failures. The setting is the remedy until email matching exists (TODO.md).
  - Recent runs reads the newest page of runs (50); older runs beyond it do not appear. My recent failures reads the newest 50 *failing* runs whose author contains the name, then keeps the exact name. A name that is a common substring of other authors' names can therefore push the person's own runs off that page.
- **New widget types:** each needs an entry in the catalogue file and in the dashboard registry, plus its `staleKeys`. The shared test and the registry test fail until both agree.
