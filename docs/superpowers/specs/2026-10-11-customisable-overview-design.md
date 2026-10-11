# Customisable Overview — design

Status: approved in conversation 2026-10-11 (sections 1–4), pending review of this written spec.
Roadmap: TODO.md "Execution intelligence and operations" item 3, plus v2 backlog F "Personal dashboard:
my suites, my recent failures". Blueprint: "Interactive dashboards with customizable widgets" (Enhanced
Collaboration). Out of scope: the old roadmap's "widget marketplace" (third-party widgets).

## 1. Goal

The project Overview becomes a set of widgets chosen from a catalogue. Two things weigh the same (user's
answer):

- **roles** want different first screens (a QA lead wants trends and the report; a developer wants their
  branch and what is failing now);
- **projects** need different things (a flaky-heavy suite, a fast-moving one).

So there is a **project default layout** (owners and admins) and a **personal layout** per user per
project (every role, viewers included), with "reset to project default". With nothing configured the
Overview looks exactly as today.

Widgets show only what the existing analytics already compute: no new metrics, no AI.

## 2. Behaviour

### 2.1 Which layout a user sees
Personal layout for this project → else the project default → else the **built-in default**, which is
today's four cards (Latest run, Failing in latest run, Pass rate this week, Flaky tests 14 d).

### 2.2 Customise (every role)
A **Customise** button in the Overview header opens edit mode. A bar reads
*"Editing your Overview"* with **Add widget**, **Reset to project default**, **Cancel**, **Save**.

Each widget card shows a toolbar: **Move up**, **Move down**, **Wide/Normal**, **Settings** (only when the
widget has settings), **Remove**. Changes apply to a draft; the live page changes only on Save.

### 2.3 Edit project default (owners and admins)
The Customise menu has a second item, **Edit project default**. Same editor; the bar reads
*"Editing the project default · everyone without a personal layout sees this"* and shows
*"Last changed by <name> on <date>"*. Save asks for confirmation.

### 2.4 Catalogue (14 widget types)

| # | Type id | Title | Data (existing query of the owning screen) | Settings |
|---|---|---|---|---|
| 1 | `latest_run` | Latest run | Runs | — (default Wide) |
| 2 | `failing_now` | Failing in latest run | Run detail / causes | rows 5\|10 |
| 3 | `pass_rate_week` | Pass rate this week | Trends (week) | branch |
| 4 | `flaky_count` | Flaky tests | Flaky | period 7\|14\|30 d |
| 5 | `pass_rate_trend` | Pass-rate trend | Trends | granularity day\|week\|month, branch |
| 6 | `failure_causes` | Failure causes | Report causes (new / recurring / resolved) | period, branch |
| 7 | `regressions` | Regressions and flips | Report regressions/instability | period, branch, rows |
| 8 | `recent_runs` | Recent runs | Runs list | branch, rows |
| 9 | `branch_health` | Branch health | Branches (latest verdict per branch) | rows |
| 10 | `slowest_tests` | Slowest tests | Report duration | period, branch, rows |
| 11 | `coverage` | Coverage | Report coverage (never-run cases, tests without a case) | period |
| 12 | `case_tiles` | Test cases | Cases KPI tiles (cases, failing, flaky) | — |
| 13 | `my_failures` | My recent failures | Runs list, `status=failed`, `author=<name>` | author name (default: the user's full name), rows |
| 14 | `my_suites` | My suites | Suites list `created_by=me` | rows |

Period values: 7, 14, 30 days. Rows: 5 or 10. Branch: "all" or one branch from the Branches list.
A type may appear more than once with different settings (e.g. two trends for `main` and `develop`).

**My recent failures** matches the run's commit author **name**: the collector stores `git log --format=%an`,
not an email. The default is the user's QEOS full name; the setting lets a user type how their name
appears in git. When nothing matches the widget says so and names the setting. Matching by email is a
later improvement (collector field + migration), tracked in TODO.

### 2.5 Templates
**Add widget** also offers three ready layouts: *QA lead* (pass-rate trend, failure causes, regressions,
coverage, case tiles), *Developer* (latest run, failing now, branch health, recent runs, my recent
failures) and *Flaky hunt* (flaky count, regressions and flips, slowest tests, pass-rate trend). Choosing
one replaces the draft; Cancel still undoes it.

### 2.6 Sizes and grid
Normal (one column of the existing `auto-fit, minmax(260px, 1fr)` grid) or Wide (the full row, as the
latest-run card today). Below two columns, Wide and Normal look the same and widgets stack in layout order.

### 2.7 Kept from today
The 30 s refresh while the tab is visible and the polite "N new runs" announcement (ADR-021); a new latest
run refreshing the pass rate and flaky figures; the new-cause marks; the "No runs yet" start panel for a
project without runs (shown instead of the widgets). Every widget title is a link to its full view with
the same filters (Trends, Report, Flaky, Runs, Branches, Cases, Suites).

### 2.8 Safeguards
- **Unsaved edits:** leaving edit mode with changes (Cancel, navigation, closing the tab) asks
  "Discard your changes?".
- **Concurrent edits:** saving sends the version editing started from. If someone saved in between, the
  editor shows "Changed by <name> on <date> since you started" with **Reload** and **Overwrite**.
- **Default changed since you customised:** when the project default's `updated_at` is later than the
  personal layout's, edit mode shows a quiet note "The project default changed on <date>" beside
  **Reset to project default**.
- **Limits:** at most 24 widgets per layout.
- **Accessibility:** moves keep focus on the moved widget and are announced in one polite live region
  ("Pass-rate trend moved to position 3 of 8"); toolbar buttons are labelled icon buttons, at least
  24×24 px (44 px on touch); status never by colour alone (DESIGN.md).
- **Failures:** each widget loads, fails and retries on its own (ErrorBanner with Retry); a widget that
  throws while rendering shows "This widget failed to load · Retry" via its own error boundary, and the
  rest of the page keeps working.
- **A branch without data:** a widget set to a branch with no runs in its period says "No runs on
  <branch> in the last N days" with its Settings button, never an error.
- No undo history: Cancel discards the draft and Reset brings the project default back.

## 3. Data and API (project-service)

### 3.1 Table
Migration `004_overview_layouts`, table `overview_layouts`:

| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `project_id` | int, FK `projects.id` ON DELETE CASCADE | |
| `user_id` | int, nullable | null = the project default |
| `layout` | JSONB | validated (3.2) |
| `version` | int, default 1 | +1 on every save |
| `updated_by` | int | user id |
| `updated_at` | timestamptz | |

Unique (`project_id`, `user_id`) for personal rows; a partial unique index on `project_id WHERE user_id IS
NULL` for the default.

### 3.2 Layout JSON and validation
```json
{"schema": 1, "widgets": [
  {"id": "w1", "type": "pass_rate_trend", "size": "wide", "settings": {"granularity": "week", "branch": "main"}}
]}
```
The server refuses with 422: a `schema` other than 1; more than 24 widgets; duplicate widget `id`s
(1–32 chars, `[A-Za-z0-9_-]`); an unknown `type`; a `size` other than `normal`/`wide`; a setting the type
does not declare or a value outside its allowed set (branch: 1–255 chars, no NUL; author name: 1–255
chars, no NUL); a body over 16 KB.

The widget list (types, settings, allowed values, limits) lives in **one file**,
`shared/qeos_shared/overview_widgets.json`: project-service loads it to validate, and the dashboard
registry imports it (the dashboard Dockerfile copies that one file). A dashboard test fails when the
registry and the file disagree.

### 3.3 Endpoints (`/api/v1/projects/{id}/overview-layout`)

| Method, path | Roles | Behaviour |
|---|---|---|
| `GET` | any project role | `{effective, source: "personal"\|"project"\|"builtin", personal: {version, updated_at}\|null, project: {version, updated_by, updated_at}\|null}`; `effective` is null for `builtin` (the dashboard holds the built-in default) |
| `PUT /personal` | any project role | body `{layout, version}` (version 0 = create); 409 when stale; returns the saved row |
| `DELETE /personal` | any project role | reset to the project default; 204 |
| `PUT /project` | owner, admin | body `{layout, version}`; 409 when stale |
| `DELETE /project` | owner, admin | back to the built-in default; 204 |

A 409 body carries `{version, updated_by, updated_at}` of the stored row.

**Gateway:** no change. The path falls under the existing `location /api/v1/projects` (project-service);
no regex location matches `overview-layout`. The smoke proves the route end to end.

### 3.4 Lifecycle
- Deleting a project deletes its layouts (cascade).
- A personal layout whose user no longer has a role in the project is never served (the role check runs
  first); no clean-up job is added — a row of a few KB is harmless.
- The project data export includes the project default, not personal layouts (user preferences).

### 3.5 test-management
The suites list gains `created_by=me` (the caller's user id), for *My suites*.

## 4. Dashboard architecture

- **Registry** `dashboard/src/overview/widgets/`: one file per type exporting `{type, title, description,
  defaultSize, settings, defaults, Component({projectId, settings, size}), link(projectId, settings)}`;
  `registry.ts` maps type → definition, checked against `overview_widgets.json`. Unknown types read from a
  stored layout are skipped (logged once).
- **Shared queries:** a widget uses the owning screen's query hook under the same key, so identical
  widgets cost one request and refresh behaviour comes from those hooks once (DESIGN.md "Requests").
- **Report widgets ask for their own section only:** `POST /analytics/report` takes `sections` and
  `branch`, so *Failure causes* sends `sections: ["failure_causes"]`, *Regressions* `["regressions"]`,
  *Slowest tests* `["duration"]`. Run-driven widgets follow the 30 s refresh; report-driven widgets
  refetch when a new latest run arrives, not on every tick.
- **Coverage** reuses the Report's existing dashboard join of test-management cases with ingestion results
  (ADR-022) unchanged.
- **Lazy loading:** each widget component is code-split (`React.lazy`) and loads only when placed.
- **Layout state:** `useOverviewLayout(projectId)` (React Query GET, mutations for PUT/DELETE);
  `overview/templates.ts` holds the built-in default and the three templates as stored-layout JSON.
- **Editor:** `OverviewEditor` works on a draft; a dirty flag drives the discard guard (React Router
  blocker + `beforeunload`); a 409 opens the conflict message (Reload / Overwrite = resend with the newer
  version).
- **Cards:** each widget sits in a card whose `h2` is the title link, inside an error boundary.
- **Today's four cards** become the first four widgets with their logic unchanged; the existing
  OverviewPage tests keep passing against the built-in default.
- UI work starts with the `ui-ux-pro-max` skill and follows DESIGN.md.

## 5. Testing

- **project-service (pytest):** every endpoint × role (viewers may save personal, only owner/admin the
  default); resolution personal → project → builtin; 409 on stale version; validation cases of 3.2; a
  departed user's layout not served; cascade on project delete.
- **test-management:** `created_by=me`.
- **Dashboard (vitest + MSW):** each of the 14 widgets with defaults, error state and link; editor move,
  size, add, remove, template, settings; discard guard; conflict dialog; focus and live announcements;
  "Edit project default" only for owner/admin; registry matches `overview_widgets.json`; existing Overview
  tests on the built-in default.
- **Gateway smoke:** GET returns builtin; PUT then GET round-trips a personal layout; a viewer's
  `PUT /project` gets 403.

## 6. Documentation

Updated in the commits that change behaviour: PRODUCT.md (Overview rules), DESIGN.md (edit mode, widget
card), README.md and docs/SETUP.md ("Customise the Overview"), TECHNICAL_SPECIFICATION.md and the
project-service README (endpoints, table), TODO.md (item 3, backlog F, the email-matching follow-up),
**ADR-028** (layouts in project-service, the shared widget file, name-based "my" matching) and its INDEX,
the blueprint's status banner.

## 7. Delivery

Three phases, each ending in a gate (all suites, smoke) and a push:

1. **Backend:** `overview_widgets.json`, migration 004, endpoints and validation, `created_by=me`, smoke.
2. **Frame:** registry with today's four cards, `useOverviewLayout`, the editor (both modes), safeguards.
3. **Catalogue:** the other ten widgets, templates, docs, ADR-028.

## 8. What this builds vs what stays TARGET

Builds the blueprint's "interactive dashboards with customizable widgets" for the project Overview, on
the current stack (project-service, PostgreSQL JSONB, React). Stays out: a widget marketplace or
third-party widgets, cross-project dashboards, free-form drag-and-drop placement, and new analytics.
No TARGET technology is introduced.

## 9. Amendments from the implementation plan (2026-10-11)

Checked against the code while planning (`docs/superpowers/plans/2026-10-11-customisable-overview.md`, its
rulings); they replace the text above where they differ:

- GET also returns the project default's `layout` (§3.3), needed for Reset and for an owner who has a
  personal layout to edit the default.
- Projects are soft-deleted: a soft-deleted project's layouts answer 404; the cascade applies to a hard
  delete (§3.4).
- The project export lives in ingestion-service and holds ingestion data only; adding the project default
  to it needs a cross-service export and is a TODO follow-up, not part of this work (§3.4).
- *My recent failures* uses the runs API's `status=failing` (§2.4); with no author setting and no full name
  it explains and sends no request.
- *Slowest tests* reads the Report's `summary` section (`summary.slowest`); the `duration` section has no
  per-test rows (§4). *Coverage* uses the `tests` section plus case areas, across all branches.
- *Branch health* shows each branch's pass rate, runs and last run over 30 days, newest first: the Branches
  API has aggregates and last-seen times, not a latest verdict (§2.4).
- Today's Overview has no "N new runs" announcement (that lives on Runs); the 30 s refresh is kept and no
  announcement is added (§2.7).
- In view mode a widget with no data shows "Change settings", which opens Customise on that widget (§2.8).
- Cancel asks "Discard your changes?"; navigation and closing the tab reuse the existing unsaved-changes
  guard and its wording.
- In project mode the reset button reads "Reset to built-in default".
- Customise ships at the Phase 2 push, so Phase 2 documents what it ships; Phase 3 completes the docs (§6, §7).
- The body limit is 64 KB (65536 bytes), not 16 KB: 24 widgets with 255-character branch and author
  settings in multibyte UTF-8 reach about 49 KB, so 16 KB would refuse layouts every field rule allows (§3.2).
- An absent `branch` setting means all branches; there is no `"all"` value, so a git branch named `all`
  stays selectable (§2.4).
