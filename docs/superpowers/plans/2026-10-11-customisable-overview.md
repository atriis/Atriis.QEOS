# Customisable Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Phases.** P1 (backend), P2 (frame), P3 (catalogue) each ship on their own. The last task of each phase is a gate: every suite, the CI-mirroring steps, the gateway smoke, then a push to `master`.

**Goal:** The project Overview becomes a grid of widgets chosen from a 14-type catalogue, with a project default layout (owners and admins) and a personal layout per user per project (every role), falling back to today's four cards when nothing is configured.

**Architecture:**
- **`shared/qeos_shared/overview_widgets.json`** is the one widget catalogue (types, settings, allowed values, limits). `qeos_shared.overview_widgets.load_catalog()` reads it with `importlib.resources`; the dashboard imports the same file.
- **project-service** gains migration **004** `overview_layouts` (one row per project default, `user_id` NULL, and one per user), validation of a layout against the catalogue, and five endpoints under `/api/v1/projects/{id}/overview-layout` with optimistic versions (409 carries the stored row). The role check runs first, so a departed user's layout is never served. **test-management** gains `GET /suites?created_by=me`.
- **dashboard** gains `src/overview/`: the catalogue import, a registry (one definition file per type, each component code-split with `React.lazy`), `WidgetCard` (h2 title link, its own error boundary), `useOverviewLayout`, a pure draft reducer, `OverviewEditor` for personal and project modes (discard guard, 409 dialog, focus and live announcements), templates and the ten further widgets. Widgets reuse the owning screen's query under the same key; report widgets ask `POST /analytics/report` for their own section only.

**Tech Stack:** FastAPI 0.142, Pydantic 2.13, SQLAlchemy 2.1, Alembic 1.20, pytest 9 (SQLite in tests), respx. React 19, TypeScript 6, React Router 7.18 (data router, `useBlocker` via `UnsavedGuard`), TanStack Query 5, Recharts 2, lucide-react, vitest 5 + MSW 3 + Testing Library. NGINX gateway unchanged.

**Spec:** `docs/superpowers/specs/2026-10-11-customisable-overview-design.md` (approved 2026-10-11). Executors read the spec with this plan. Where this plan decides something the spec leaves open or gets wrong against the code, the decision is under **Rulings** and repeated in the task that applies it.

## Global Constraints

Every task implicitly includes all of these. Values are copied from the spec.

- **Resolution:** "Personal layout for this project → else the project default → else the **built-in default**, which is today's four cards (Latest run, Failing in latest run, Pass rate this week, Flaky tests 14 d)." "With nothing configured the Overview looks exactly as today."
- **Roles:** project default: "owners and admins"; personal layout: "every role, viewers included". Endpoint roles: `GET`, `PUT /personal`, `DELETE /personal`: "any project role"; `PUT /project`, `DELETE /project`: "owner, admin".
- **Endpoints:** `GET /api/v1/projects/{id}/overview-layout` → `{effective, source: "personal"|"project"|"builtin", personal: {version, updated_at}|null, project: {version, updated_by, updated_at}|null}`; "`effective` is null for `builtin` (the dashboard holds the built-in default)". `PUT /personal` and `PUT /project`: "body `{layout, version}` (version 0 = create); 409 when stale; returns the saved row". `DELETE /personal`: "reset to the project default; 204". `DELETE /project`: "back to the built-in default; 204". "A 409 body carries `{version, updated_by, updated_at}` of the stored row."
- **Table** `overview_layouts`: `id` serial PK; `project_id` int, FK `projects.id` ON DELETE CASCADE; `user_id` int nullable ("null = the project default"); `layout` JSONB; `version` int default 1 ("+1 on every save"); `updated_by` int; `updated_at` timestamptz. "Unique (`project_id`, `user_id`) for personal rows; a partial unique index on `project_id WHERE user_id IS NULL` for the default." Migration name `004_overview_layouts`.
- **Layout JSON:** `{"schema": 1, "widgets": [{"id": "w1", "type": "pass_rate_trend", "size": "wide", "settings": {"granularity": "week", "branch": "main"}}]}`.
- **422 refusals:** "a `schema` other than 1; more than 24 widgets; duplicate widget `id`s (1–32 chars, `[A-Za-z0-9_-]`); an unknown `type`; a `size` other than `normal`/`wide`; a setting the type does not declare or a value outside its allowed set (branch: 1–255 chars, no NUL; author name: 1–255 chars, no NUL); a body over 16 KB."
- **Catalogue (14 types):** `latest_run` (— , default Wide), `failing_now` (rows 5|10), `pass_rate_week` (branch), `flaky_count` (period 7|14|30 d), `pass_rate_trend` (granularity day|week|month, branch), `failure_causes` (period, branch), `regressions` (period, branch, rows), `recent_runs` (branch, rows), `branch_health` (rows), `slowest_tests` (period, branch, rows), `coverage` (period), `case_tiles` (—), `my_failures` (author name, rows), `my_suites` (rows). "Period values: 7, 14, 30 days. Rows: 5 or 10. Branch: "all" or one branch from the Branches list." "A type may appear more than once with different settings."
- **Titles (spec §2.4):** Latest run, Failing in latest run, Pass rate this week, Flaky tests, Pass-rate trend, Failure causes, Regressions and flips, Recent runs, Branch health, Slowest tests, Coverage, Test cases, My recent failures, My suites.
- **Templates:** "*QA lead* (pass-rate trend, failure causes, regressions, coverage, case tiles), *Developer* (latest run, failing now, branch health, recent runs, my recent failures) and *Flaky hunt* (flaky count, regressions and flips, slowest tests, pass-rate trend). Choosing one replaces the draft; Cancel still undoes it."
- **Editor copy:** button **Customise**; bar *"Editing your Overview"* with **Add widget**, **Reset to project default**, **Cancel**, **Save**; widget toolbar **Move up**, **Move down**, **Wide/Normal**, **Settings** (only when the widget has settings), **Remove**. Project mode: menu item **Edit project default**; bar *"Editing the project default · everyone without a personal layout sees this"* and *"Last changed by <name> on <date>"*; "Save asks for confirmation." "Changes apply to a draft; the live page changes only on Save."
- **Safeguards:** "Discard your changes?" on leaving edit mode with changes (Cancel, navigation, closing the tab); 409 → "Changed by <name> on <date> since you started" with **Reload** and **Overwrite** ("Overwrite = resend with the newer version"); "The project default changed on <date>" beside **Reset to project default** when the default's `updated_at` is later than the personal layout's; "at most 24 widgets per layout"; moves keep focus on the moved widget and are announced in one polite live region ("Pass-rate trend moved to position 3 of 8"); toolbar buttons are labelled icon buttons, "at least 24×24 px (44 px on touch)"; status never by colour alone; each widget "loads, fails and retries on its own (ErrorBanner with Retry)"; a widget that throws shows "This widget failed to load · Retry"; a widget set to a branch with no runs in its period says "No runs on <branch> in the last N days" with its Settings button, never an error. "No undo history."
- **Grid:** "Normal (one column of the existing `auto-fit, minmax(260px, 1fr)` grid) or Wide (the full row, as the latest-run card today)."
- **Kept from today:** "The 30 s refresh while the tab is visible", "a new latest run refreshing the pass rate and flaky figures; the new-cause marks; the "No runs yet" start panel for a project without runs (shown instead of the widgets). Every widget title is a link to its full view with the same filters."
- **Requests:** "a widget uses the owning screen's query hook under the same key, so identical widgets cost one request". Report widgets send their own section only. "Run-driven widgets follow the 30 s refresh; report-driven widgets refetch when a new latest run arrives, not on every tick." Coverage "reuses the Report's existing dashboard join of test-management cases with ingestion results (ADR-022) unchanged." Each widget component is "code-split (`React.lazy`) and loads only when placed." "Unknown types read from a stored layout are skipped (logged once)."
- **My recent failures:** matches the run's commit author **name** (`git log --format=%an`); "The default is the user's QEOS full name; the setting lets a user type how their name appears in git. When nothing matches the widget says so and names the setting."
- **Gateway:** "no change. The path falls under the existing `location /api/v1/projects` (project-service); no regex location matches `overview-layout`. The smoke proves the route end to end."
- **Out of scope (spec §8):** "a widget marketplace or third-party widgets, cross-project dashboards, free-form drag-and-drop placement, and new analytics. No TARGET technology is introduced." "Widgets show only what the existing analytics already compute: no new metrics, no AI."
- **Dashboard UI:** every task that edits a `.tsx` or `.css` file starts by invoking the `ui-ux-pro-max` skill and follows DESIGN.md. Colours from `index.css` tokens only; lucide icons with `aria-hidden="true"`; no `any`.
- **Docs:** every behaviour commit updates the `.md` files it affects. Edit `.md` files with the Edit tool (or Python reading and writing UTF-8), LF line endings, never PowerShell `Set-Content`.
- **Commands:**
  - Python, one service, serially (each suite shares its own `test.db` directory; never two suites of one service at once): `cd platforms/<svc> && SECRET_KEY=test .venv/Scripts/python -m pytest -q`. One file: append its path.
  - Shared package: `cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests -q`.
  - Dashboard: `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build`. One file: `npx vitest run <path>`.
- **Git:** work on `master`. Commit only your own paths: `git add <paths> && git commit -m "<msg>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- <paths>`. Never `git add -A`. Shell scripts stay `100755`: on Windows `git commit -- <path>` drops the executable bit, so a commit that touches `scripts/smoke_gateway.sh` stages it, runs `git update-index --chmod=+x scripts/smoke_gateway.sh`, checks `git diff --cached --name-only`, and commits the index without a pathspec. Push direct to `master` only at a phase gate, after every gate step is green.

## Rulings

Decisions the spec leaves open or gets wrong against the code. Each is repeated in its task.

1. **Loader:** `importlib.resources.files("qeos_shared") / "overview_widgets.json"`. Every service installs shared editable (`-e ../../shared`, mirrored in each Dockerfile with `COPY shared/ ./shared/`), so the file is read from the source tree; `[tool.setuptools.package-data]` declares it so a wheel carries it too.
2. **Catalogue shape:** the JSON holds `schema`, `max_widgets`, `max_body_bytes`, `widget_id_pattern`, `sizes`, `settings` (`rows`, `period`, `granularity` as `{"kind": "choice", "values": [...]}`; `branch`, `author` as `{"kind": "text", "min_length": 1, "max_length": 255}`) and `types` (each listing its setting names). Titles, descriptions, default sizes and default values live in the dashboard registry.
3. **`branch: "all"`** is every branch (spec §2.4 fixes the word); a git branch literally named `all` cannot be chosen in a widget.
4. **GET's `project` object also carries `layout`.** Reset to project default needs it in the draft, and an owner who has a personal layout must edit the project default from the project layout, not from `effective` (spec §3.3 lists only version, updated_by, updated_at).
5. **409 body:** `{"detail": {"code": "stale_version", "message": "…", "current": {"version", "updated_by", "updated_at"} | null}}`: FastAPI's detail convention, which the dashboard's `ApiError` already reads; `current` is null when the row was deleted meanwhile. `ApiError` gains a `body` field so the editor can read `current`.
6. *(Superseded 2026-10-11: the limit is **65536 bytes (64 KB)** everywhere this plan says 16 KB / 16384 — spec §9; the branch value `"all"` is likewise replaced by an absent `branch` setting.)* **16 KB** is 16384 bytes of the raw request body, refused with 422 by a dependency that runs after the role check.
7. **Versions:** `version: 0` creates (409 when a row exists, including the insert race caught as an IntegrityError); `version: n` updates only when the stored version is `n` (409 otherwise, including a missing row). DELETE carries no version: last write wins.
8. **Stored widgets:** `settings` may be left out and any setting may be missing (the registry default applies); unknown top-level or widget keys are 422; a boolean or a float never passes as an integer.
9. **Cascade:** projects are soft-deleted (`deleted_at`), so `ON DELETE CASCADE` fires only on a hard delete, which no code path does today; a soft-deleted project's layouts are unreachable because `require_project_role` answers 404. The cascade is proven in the migration test with SQLite foreign keys on.
10. **Export (spec §3.4):** the project export is ingestion-service's NDJSON of ingestion data only (project settings and repositories are not in it either). Putting the project default in it needs a cross-service export; this plan does not build it and records it in TODO.md.
11. **Runs status:** the runs API takes `status=failing|passing`; My recent failures sends `status=failing` (spec §2.4 writes `failed`).
12. **Slowest tests reads `summary.slowest` with `sections: ["summary"]`.** The `duration` section holds time buckets only, no per-test rows (spec §4 says `["duration"]`).
13. **Coverage sends `sections: ["tests"]`** plus `GET /case-areas` under the Report's keys (the ADR-026 join), across all branches.
14. **Branch health** shows each branch's pass rate, runs and last run over 30 days, newest first: the Branches API has no latest verdict per branch and no new metrics are added.
15. **Pass-rate trend days:** day → 30, week → 90, month → 90, the Trends view's own day choices, so the title link opens the same chart under the same query key.
16. **Report widgets** default to period 30 and branch `all`; their title link opens the Report with `period=7|30` (or `from`/`to` for 14 days), `branch=*` for all branches, and the section anchor.
17. **Lazy loading vs "one file per type":** each type has a definition file `widgets/<camelType>.ts` (metadata, `link`, a `React.lazy` component) and a component file `widgets/<PascalType>Widget.tsx` (the chunk). The definition file is the type's file in the spec's sense.
18. **Widget props** add `heading` (the card's h2 link, placed by the widget, e.g. in the latest run's head row beside its badge) and `onOpenSettings` (the empty-branch and no-name buttons) to the spec's `{projectId, settings, size}`.
19. **Title links:** Latest run → Runs; Failing in latest run → Runs `?status=failing`; My recent failures → Runs `?status=failing&author=…` only when the author setting is set (the default name is not known to `link`).
20. **Reset in the editor** puts the fallback (the project default; the built-in default in project mode, where the button reads "Reset to built-in default") into the draft. Save then DELETEs the stored layout instead of saving a copy, so later default changes keep reaching that user; any further edit makes it a normal save again.
21. **Unsaved edits:** Cancel asks in place "Discard your changes?" (Discard / Keep editing); navigation and closing the tab reuse `UnsavedGuard` and its existing wording. Edit mode starts from a frozen snapshot, so a background refetch never replaces the draft.
22. **Project-mode Save** confirms with `ConfirmButton`, which gains optional `triggerClassName`, `confirmClassName` and `cancelLabel` so the confirm step is primary, not danger.
23. **Names:** "Last changed by" and the conflict line show the member's email from `useUserNames`, the dashboard's only source of people's names.
24. **My recent failures without an author:** with no author setting and no QEOS full name the widget explains and offers its settings without a request (an empty author would match every run: the API's author filter is a substring match).
25. **Docs per phase:** Phase 2 ships Customise, so its editor tasks update DESIGN.md, README.md and docs/SETUP.md for what ships then; Phase 3's docs task completes them with the catalogue and templates, plus PRODUCT.md, TODO.md, ADR-028, its INDEX and the blueprint banner.
26. **"N new runs":** today's Overview has no such announcement (it lives on Runs); the 30 s poll is kept and nothing is announced.
27. **Refreshed on a new latest run:** the `trends`, `flaky`, `report`, `branches` and `latest-keys` queries of the project.
28. **Editing drops stored widgets of unknown types** (logged once); a layout of zero widgets may be saved, and the page then says so.
29. **`case_tiles` defaults to Wide:** its four KPI tiles need the row.
30. **A failed layout GET:** the page shows the built-in default under a banner with Retry; Customise stays hidden until the layout loads.
31. **Failing in latest run:** its title is the catalogue's, so the card heading changes from today's "Failing in this run" (no test pins the old heading).

## Review Focus

Inputs the spec implies but does not test, most likely to bite first. Each has a test in the owning task.

1. **A background refetch while someone edits** (window refocus, the 60 s stale time): the draft must survive untouched. Task 13 `a background refetch while editing keeps the draft`.
2. **A user with no QEOS full name** (SSO without a name claim, registration without one) opening My recent failures: no request with an empty author (it would list every failed run as "mine"); the widget names the setting. Task 20 `with no full name and no setting, My recent failures asks for a name and sends nothing`.
3. **An owner who has a personal layout choosing Edit project default:** the editor must start from the project default, not from the owner's own layout, and Save must send the project version. Task 14 `an owner with a personal layout edits the project default, not their own`.
4. **A stored layout naming a widget type this dashboard does not know** (saved by a newer version, or a Phase 3 type during Phase 2): skipped and logged once, the rest renders. Task 11 `a stored widget of an unknown type is skipped and logged once`.
5. **Settings sent with the wrong JSON type** (`true`, `5.0`, `"5"` for rows): refused, never stored to break a widget later. Task 3 `test_refused` cases `rows=True`, `rows=5.0`, `rows="5"`.

---

## File map

**shared** — Create `shared/qeos_shared/overview_widgets.json`, `shared/qeos_shared/overview_widgets.py`, `shared/tests/test_overview_widgets.py`. Modify `shared/pyproject.toml`, `shared/README.md`.

**project-service** (`platforms/project-service/`) — Create `alembic/versions/004_overview_layouts.py`, `src/project/models/overview_layout.py`, `src/project/schemas/overview_layout.py`, `src/project/service/overview_layout_service.py`, `src/project/api/v1/endpoints/overview_layout.py`, `tests/unit/test_overview_layout_validation.py`, `tests/integration/test_overview_layout.py`. Modify `src/project/models/__init__.py`, `src/project/api/v1/api.py`, `tests/unit/test_migration.py`, `README.md`.

**test-management-service** (`platforms/test-management-service/`) — Modify `src/casebook/api/v1/endpoints/suites.py`, `src/casebook/service/suite_service.py`, `tests/integration/test_suites.py`, `README.md`.

**Stack and docs** — Modify `scripts/smoke_gateway.sh`, `dashboard/Dockerfile`, `TECHNICAL_SPECIFICATION.md`, `DESIGN.md`, `PRODUCT.md`, `README.md`, `docs/SETUP.md`, `TODO.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md`, `docs/architecture/adr/INDEX.md`. Create `docs/architecture/adr/ADR-028-customisable-overview.md`. The gateway is not changed.

**dashboard** (`dashboard/`) — Modify `tsconfig.json`, `vite.config.ts`, `src/index.css`, `src/test/server.ts`, `src/api/http.ts`, `src/api/http.test.ts`, `src/api/auth.ts`, `src/api/cases.ts`, `src/lib/healthQueries.ts`, `src/lib/useCanEdit.ts`, `src/components/ConfirmButton.tsx`, `src/components/ConfirmButton.test.tsx`, `src/pages/OverviewPage.tsx`, `src/pages/TrendsPage.tsx`, `src/pages/BranchesPage.tsx`, `src/pages/RunsPage.tsx`. Create:
- `src/api/overviewLayout.ts`, `src/api/overviewLayout.test.ts`, `src/lib/healthQueries.test.ts`, `src/lib/runQueries.ts`;
- `src/overview/`: `catalog.ts`, `catalog.test.ts`, `templates.ts`, `useOverviewLayout.ts`, `useOverviewLayout.test.ts`, `queries.ts`, `useLatestRun.ts`, `format.ts`, `WidgetBoundary.tsx`, `WidgetBoundary.test.tsx`, `WidgetCard.tsx`, `WidgetGrid.tsx`, `draft.ts`, `draft.test.ts`, `session.ts`, `session.test.ts`, `WidgetToolbar.tsx`, `WidgetSettingsForm.tsx`, `AddWidgetPanel.tsx`, `CustomiseMenu.tsx`, `OverviewEditor.tsx`, `OverviewEditor.test.tsx`, `ProjectDefault.test.tsx`, `reportWidget.ts`, `EmptyBranch.tsx`, `testing.tsx`, `UnknownWidget.test.tsx`, `templates.test.tsx`;
- `src/overview/widgets/`: `types.ts`, `registry.ts`, `registry.test.ts`, and per type a definition and a component: `latestRun.ts`/`LatestRunWidget.tsx`, `failingNow.ts`/`FailingNowWidget.tsx`, `passRateWeek.ts`/`PassRateWeekWidget.tsx`, `flakyCount.ts`/`FlakyCountWidget.tsx`, `passRateTrend.ts`/`PassRateTrendWidget.tsx`, `failureCauses.ts`/`FailureCausesWidget.tsx`, `regressions.ts`/`RegressionsWidget.tsx`, `slowestTests.ts`/`SlowestTestsWidget.tsx`, `coverage.ts`/`CoverageWidget.tsx`, `recentRuns.ts`/`RecentRunsWidget.tsx`, `branchHealth.ts`/`BranchHealthWidget.tsx`, `caseTiles.ts`/`CaseTilesWidget.tsx`, `mySuites.ts`/`MySuitesWidget.tsx`, `myFailures.ts`/`MyFailuresWidget.tsx`; tests `frameWidgets.test.tsx`, `trendWidgets.test.tsx`, `reportWidgets.test.tsx`, `runWidgets.test.tsx`, `personalWidgets.test.tsx`.

---

# Phase 1 — Backend

Useful by itself: layouts can be stored and read through the gateway, and the suites list filters by creator.

### Task 1: The widget catalogue file and its loader in `qeos_shared`

**Files:**
- Create: `shared/qeos_shared/overview_widgets.json`
- Create: `shared/qeos_shared/overview_widgets.py`
- Create: `shared/tests/test_overview_widgets.py`
- Modify: `shared/pyproject.toml`, `shared/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `qeos_shared.overview_widgets.FILE_NAME: str = "overview_widgets.json"`; `qeos_shared.overview_widgets.load_catalog() -> dict` (cached; callers must not mutate it) with keys `schema: int`, `max_widgets: int`, `max_body_bytes: int`, `widget_id_pattern: str`, `sizes: list[str]`, `settings: dict[str, dict]`, `types: dict[str, {"settings": list[str]}]` (Ruling 2). The dashboard imports the same JSON file in Task 8.

- [ ] **Step 1: Write the failing test**

Create `shared/tests/test_overview_widgets.py`:

```python
"""The Overview widget catalogue (spec docs/superpowers/specs/2026-10-11-customisable-overview-design.md §2.4, §3.2)."""
import re
import tomllib
from pathlib import Path

from qeos_shared.overview_widgets import FILE_NAME, load_catalog

TYPES = {
    "latest_run": [],
    "failing_now": ["rows"],
    "pass_rate_week": ["branch"],
    "flaky_count": ["period"],
    "pass_rate_trend": ["granularity", "branch"],
    "failure_causes": ["period", "branch"],
    "regressions": ["period", "branch", "rows"],
    "recent_runs": ["branch", "rows"],
    "branch_health": ["rows"],
    "slowest_tests": ["period", "branch", "rows"],
    "coverage": ["period"],
    "case_tiles": [],
    "my_failures": ["author", "rows"],
    "my_suites": ["rows"],
}


def test_the_fourteen_types_and_their_settings():
    catalog = load_catalog()
    assert {name: spec["settings"] for name, spec in catalog["types"].items()} == TYPES


def test_limits_and_sizes():
    catalog = load_catalog()
    assert catalog["schema"] == 1
    assert catalog["max_widgets"] == 24
    assert catalog["max_body_bytes"] == 16 * 1024
    assert catalog["sizes"] == ["normal", "wide"]
    pattern = re.compile(catalog["widget_id_pattern"])
    assert pattern.fullmatch("w1")
    assert pattern.fullmatch("A_b-9" * 6 + "xy")  # 32 characters
    assert not pattern.fullmatch("")
    assert not pattern.fullmatch("x" * 33)
    assert not pattern.fullmatch("bad id")


def test_allowed_values():
    settings = load_catalog()["settings"]
    assert settings["rows"] == {"kind": "choice", "values": [5, 10]}
    assert settings["period"] == {"kind": "choice", "values": [7, 14, 30]}
    assert settings["granularity"] == {"kind": "choice", "values": ["day", "week", "month"]}
    for name in ("branch", "author"):
        assert settings[name] == {"kind": "text", "min_length": 1, "max_length": 255}


def test_every_setting_a_type_names_is_declared():
    catalog = load_catalog()
    for spec in catalog["types"].values():
        assert set(spec["settings"]) <= set(catalog["settings"])


def test_a_wheel_carries_the_file():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert FILE_NAME in pyproject["tool"]["setuptools"]["package-data"]["qeos_shared"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests/test_overview_widgets.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qeos_shared.overview_widgets'`.

- [ ] **Step 3: Write the catalogue and the loader**

Create `shared/qeos_shared/overview_widgets.json`:

```json
{
  "schema": 1,
  "max_widgets": 24,
  "max_body_bytes": 16384,
  "widget_id_pattern": "^[A-Za-z0-9_-]{1,32}$",
  "sizes": ["normal", "wide"],
  "settings": {
    "rows": {"kind": "choice", "values": [5, 10]},
    "period": {"kind": "choice", "values": [7, 14, 30]},
    "granularity": {"kind": "choice", "values": ["day", "week", "month"]},
    "branch": {"kind": "text", "min_length": 1, "max_length": 255},
    "author": {"kind": "text", "min_length": 1, "max_length": 255}
  },
  "types": {
    "latest_run": {"settings": []},
    "failing_now": {"settings": ["rows"]},
    "pass_rate_week": {"settings": ["branch"]},
    "flaky_count": {"settings": ["period"]},
    "pass_rate_trend": {"settings": ["granularity", "branch"]},
    "failure_causes": {"settings": ["period", "branch"]},
    "regressions": {"settings": ["period", "branch", "rows"]},
    "recent_runs": {"settings": ["branch", "rows"]},
    "branch_health": {"settings": ["rows"]},
    "slowest_tests": {"settings": ["period", "branch", "rows"]},
    "coverage": {"settings": ["period"]},
    "case_tiles": {"settings": []},
    "my_failures": {"settings": ["author", "rows"]},
    "my_suites": {"settings": ["rows"]}
  }
}
```

Create `shared/qeos_shared/overview_widgets.py`:

```python
"""The Overview widget catalogue: one JSON file that project-service validates layouts against and the
dashboard registry imports (spec docs/superpowers/specs/2026-10-11-customisable-overview-design.md §3.2).

The file sits beside this module. Services install this package editable (`-e ../../shared`, mirrored in
each Dockerfile), so it is read from the source tree; `package-data` in pyproject.toml makes a wheel carry
it as well.
"""
import json
from functools import lru_cache
from importlib.resources import files

FILE_NAME = "overview_widgets.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    """The parsed catalogue, read once per process. Callers must not mutate it."""
    return json.loads(files("qeos_shared").joinpath(FILE_NAME).read_text(encoding="utf-8"))
```

In `shared/pyproject.toml`, after the existing `[tool.setuptools]` block (`packages = ["qeos_shared"]`), append:

```toml

# The Overview widget catalogue is data, not code: listed so a wheel carries it (qeos_shared.overview_widgets)
[tool.setuptools.package-data]
qeos_shared = ["overview_widgets.json"]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests -q`
Expected: PASS, 0 failed (the existing shared tests included).

- [ ] **Step 5: Document it**

In `shared/README.md`, with the Edit tool, replace:

```
  route template, never the raw path. One uvicorn worker is assumed (see the module docstring).
```

with:

```
  route template, never the raw path. One uvicorn worker is assumed (see the module docstring).
- `load_catalog()` (`qeos_shared.overview_widgets`) — the Overview widget catalogue,
  `overview_widgets.json` beside the module: the 14 widget types, their settings and allowed values,
  and the layout limits (24 widgets, 16 KB). project-service validates layouts against it; the
  dashboard registry imports the same file (its Dockerfile copies it) and a dashboard test fails when
  the two disagree.
```

- [ ] **Step 6: Commit**

```bash
git add shared/qeos_shared/overview_widgets.json shared/qeos_shared/overview_widgets.py shared/tests/test_overview_widgets.py shared/pyproject.toml shared/README.md
git commit -m "feat(shared): Overview widget catalogue file and its loader" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- shared/qeos_shared/overview_widgets.json shared/qeos_shared/overview_widgets.py shared/tests/test_overview_widgets.py shared/pyproject.toml shared/README.md
```

---

### Task 2: Migration 004 `overview_layouts` and the model

**Files:**
- Create: `platforms/project-service/alembic/versions/004_overview_layouts.py`
- Create: `platforms/project-service/src/project/models/overview_layout.py`
- Modify: `platforms/project-service/src/project/models/__init__.py`
- Test: `platforms/project-service/tests/unit/test_migration.py`

**Interfaces:**
- Consumes: `src.project.models.project.SettingsJSON` (JSON with a JSONB variant), `src.project.db.base.Base`.
- Produces: `src.project.models.overview_layout.OverviewLayout` (columns `id`, `project_id`, `user_id`, `layout`, `version`, `updated_by`, `updated_at`), exported from `src.project.models`. Constraint names `uq_overview_layouts_project_user`, `uq_overview_layouts_project_default`.

- [ ] **Step 1: Write the failing tests**

In `platforms/project-service/tests/unit/test_migration.py`, change the import lines:

```python
from sqlalchemy import create_engine, inspect, text
```

to:

```python
from sqlalchemy import create_engine, event, inspect, text
```

and:

```python
from src.project.models import Project, Repository  # noqa: F401  registers tables
```

to:

```python
from src.project.models import OverviewLayout, Project, Repository  # noqa: F401  registers tables
```

Append to the end of the file:

```python
EMPTY_LAYOUT = '{"schema": 1, "widgets": []}'


def _insert_layout(conn, user_id, project_id=1):
    conn.execute(
        text(
            "INSERT INTO overview_layouts (project_id, user_id, layout, version, updated_by)"
            " VALUES (:project_id, :user_id, :layout, 1, 1)"
        ),
        {"project_id": project_id, "user_id": user_id, "layout": EMPTY_LAYOUT},
    )


def test_one_project_default_per_project(migrated_engine):
    with migrated_engine.begin() as conn:
        _insert_project(conn, "P", "p")
        _insert_layout(conn, None)
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            _insert_layout(conn, None)


def test_one_personal_layout_per_user_and_project(migrated_engine):
    with migrated_engine.begin() as conn:
        _insert_project(conn, "P", "p")
        _insert_layout(conn, 7)
        _insert_layout(conn, 8)  # another user's: fine
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            _insert_layout(conn, 7)


def test_deleting_a_project_deletes_its_layouts(migrated_engine):
    # SQLite enforces foreign keys only when asked, per connection
    event.listen(migrated_engine, "connect", lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"))
    migrated_engine.dispose()
    with migrated_engine.begin() as conn:
        _insert_project(conn, "P", "p")
        _insert_layout(conn, None)
        _insert_layout(conn, 7)
        conn.execute(text("DELETE FROM projects WHERE slug = 'p'"))
        assert conn.execute(text("SELECT COUNT(*) FROM overview_layouts")).scalar() == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py -q`
Expected: FAIL with `ImportError: cannot import name 'OverviewLayout' from 'src.project.models'`.

- [ ] **Step 3: Write the model and the migration**

Create `platforms/project-service/src/project/models/overview_layout.py`:

```python
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.sql import func

from src.project.db.base import Base
from src.project.models.project import SettingsJSON

# The project default is the row without a user
_DEFAULT_ROW = text("user_id IS NULL")


class OverviewLayout(Base):
    """An Overview layout (spec 2026-10-11 §3.1): the project default (user_id NULL) or one user's personal layout.

    `layout` is validated against shared/qeos_shared/overview_widgets.json before it is stored. `version` grows by one
    on every save; a save names the version it started from, and a stale one is refused (409).
    """

    __tablename__ = "overview_layouts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    # No FK: users live in auth-service's database
    user_id = Column(Integer, nullable=True)
    layout = Column(SettingsJSON, nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # NULLs are distinct in a unique constraint, so this holds the personal rows only
        UniqueConstraint("project_id", "user_id", name="uq_overview_layouts_project_user"),
        Index(
            "uq_overview_layouts_project_default", "project_id",
            unique=True, sqlite_where=_DEFAULT_ROW, postgresql_where=_DEFAULT_ROW,
        ),
    )
```

Replace `platforms/project-service/src/project/models/__init__.py` with:

```python
from src.project.models.overview_layout import OverviewLayout
from src.project.models.project import Project
from src.project.models.repository import Repository

__all__ = ["OverviewLayout", "Project", "Repository"]
```

Create `platforms/project-service/alembic/versions/004_overview_layouts.py`:

```python
"""overview layouts: one project default and one personal layout per user, per project

Revision ID: 004
Revises: 003
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

DEFAULT_ROW = sa.text("user_id IS NULL")


def upgrade() -> None:
    op.create_table(
        "overview_layouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("layout", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "user_id", name="uq_overview_layouts_project_user"),
    )
    op.create_index("ix_overview_layouts_project_id", "overview_layouts", ["project_id"])
    op.create_index(
        "uq_overview_layouts_project_default", "overview_layouts", ["project_id"],
        unique=True, sqlite_where=DEFAULT_ROW, postgresql_where=DEFAULT_ROW,
    )


def downgrade() -> None:
    op.drop_index("uq_overview_layouts_project_default", table_name="overview_layouts")
    op.drop_index("ix_overview_layouts_project_id", table_name="overview_layouts")
    op.drop_table("overview_layouts")
```

- [ ] **Step 4: Run them to verify they pass**

Run: `cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py -q`
Expected: PASS, 0 failed (`test_migration_columns_match_models` now also covers `overview_layouts`).

- [ ] **Step 5: Run the whole service suite**

Run: `cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: PASS, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add platforms/project-service/alembic/versions/004_overview_layouts.py platforms/project-service/src/project/models/overview_layout.py platforms/project-service/src/project/models/__init__.py platforms/project-service/tests/unit/test_migration.py
git commit -m "feat(project): overview_layouts table (migration 004)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/project-service/alembic/versions/004_overview_layouts.py platforms/project-service/src/project/models/overview_layout.py platforms/project-service/src/project/models/__init__.py platforms/project-service/tests/unit/test_migration.py
```

---

### Task 3: Layout validation from the shared catalogue

**Files:**
- Create: `platforms/project-service/src/project/schemas/overview_layout.py`
- Test: `platforms/project-service/tests/unit/test_overview_layout_validation.py`

**Interfaces:**
- Consumes: `qeos_shared.overview_widgets.load_catalog() -> dict` (Task 1).
- Produces, in `src.project.schemas.overview_layout`:
  - `CATALOG: dict`, `MAX_WIDGETS: int` (24), `MAX_BODY_BYTES: int` (16384);
  - `class LayoutError(ValueError)`;
  - `validate_layout(layout: Any) -> dict` (returns the same object, raises `LayoutError` with a message naming the place, e.g. `widgets[2].settings.rows: 7 is not one of 5, 10`);
  - `class LayoutIn(BaseModel)`: `layout: dict` (validated), `version: int` (`ge=0`), `extra="forbid"`;
  - `class PersonalMeta(BaseModel)`: `version: int`, `updated_at: datetime`;
  - `class ProjectMeta(BaseModel)`: `version: int`, `updated_by: int`, `updated_at: datetime`, `layout: dict` (Ruling 4);
  - `class OverviewLayoutOut(BaseModel)`: `effective: Optional[dict]`, `source: Literal["personal", "project", "builtin"]`, `personal: Optional[PersonalMeta]`, `project: Optional[ProjectMeta]`;
  - `class LayoutRowOut(BaseModel)`: `layout: dict`, `version: int`, `updated_by: int`, `updated_at: datetime`.

- [ ] **Step 1: Write the failing test**

Create `platforms/project-service/tests/unit/test_overview_layout_validation.py`:

```python
"""Layout validation against shared/qeos_shared/overview_widgets.json (spec 2026-10-11 §3.2; plan Ruling 8)."""
import pytest
from pydantic import ValidationError

from src.project.schemas.overview_layout import LayoutError, LayoutIn, validate_layout


def widget(id="w1", type="latest_run", size="normal", **settings):
    return {"id": id, "type": type, "size": size, "settings": settings}


def layout(*widgets, schema=1):
    return {"schema": schema, "widgets": list(widgets)}


EVERY_TYPE = layout(
    widget("w1", "latest_run", "wide"),
    widget("w2", "failing_now", rows=10),
    widget("w3", "pass_rate_week", branch="all"),
    widget("w4", "flaky_count", period=30),
    widget("w5", "pass_rate_trend", granularity="month", branch="release/2026.10"),
    widget("w6", "failure_causes", period=7, branch="main"),
    widget("w7", "regressions", period=14, branch="all", rows=5),
    widget("w8", "recent_runs", branch="develop", rows=10),
    widget("w9", "branch_health", rows=5),
    widget("w10", "slowest_tests", period=30, branch="all", rows=10),
    widget("w11", "coverage", period=30),
    widget("w12", "case_tiles", "wide"),
    widget("w13", "my_failures", author="Ada Lovelace", rows=5),
    widget("w14", "my_suites", rows=10),
)


def test_every_type_with_valid_settings_passes():
    assert validate_layout(EVERY_TYPE) is EVERY_TYPE


def test_settings_may_be_left_out_and_a_type_may_repeat():
    value = layout({"id": "a", "type": "pass_rate_trend", "size": "normal"}, widget("b", "pass_rate_trend", branch="develop"))
    assert validate_layout(value) is value


def test_the_limits_themselves_pass():
    value = layout(*[widget(f"w{i}") for i in range(23)], widget("x" * 32, "recent_runs", branch="b" * 255))
    assert validate_layout(value) is value


@pytest.mark.parametrize("bad, message", [
    (layout(schema=2), "schema must be 1"),
    ({"widgets": []}, "schema must be 1"),
    (layout(schema=True), "schema must be 1"),
    ({"schema": 1, "widgets": [], "theme": "dark"}, "unknown key 'theme'"),
    ({"schema": 1, "widgets": {}}, "widgets must be a list"),
    (layout(*[widget(f"w{i}") for i in range(25)]), "at most 24 widgets"),
    (layout(widget("w1"), widget("w1")), "duplicate id 'w1'"),
    (layout(widget("")), "widgets[0].id"),
    (layout(widget("x" * 33)), "widgets[0].id"),
    (layout(widget("bad id")), "widgets[0].id"),
    (layout(widget(7)), "widgets[0].id"),
    (layout(widget(type="marketplace")), "unknown type 'marketplace'"),
    (layout(widget(size="huge")), "size: must be normal or wide"),
    (layout({"id": "w1", "type": "latest_run"}), "missing 'size'"),
    (layout({**widget(), "colour": "red"}), "unknown key 'colour'"),
    (layout({**widget(), "settings": []}), "settings must be an object"),
    (layout(widget(rows=5)), "latest_run has no setting 'rows'"),
    (layout(widget(type="failing_now", rows=7)), "7 is not one of 5, 10"),
    (layout(widget(type="failing_now", rows="5")), "is not one of 5, 10"),
    (layout(widget(type="failing_now", rows=True)), "is not one of 5, 10"),
    (layout(widget(type="failing_now", rows=5.0)), "is not one of 5, 10"),
    (layout(widget(type="flaky_count", period=21)), "is not one of 7, 14, 30"),
    (layout(widget(type="pass_rate_trend", granularity="year")), "is not one of day, week, month"),
    (layout(widget(type="recent_runs", branch="")), "1-255 characters"),
    (layout(widget(type="recent_runs", branch="x" * 256)), "1-255 characters"),
    (layout(widget(type="recent_runs", branch="a\x00b")), "no NUL"),
    (layout(widget(type="recent_runs", branch=3)), "1-255 characters"),
    (layout(widget(type="my_failures", author="y" * 256)), "1-255 characters"),
    ("not an object", "layout must be an object"),
    (layout("w1"), "widgets[0] must be an object"),
])
def test_refused(bad, message):
    with pytest.raises(LayoutError) as caught:
        validate_layout(bad)
    assert message in str(caught.value)


def test_the_request_body_validates_the_layout_and_the_version():
    assert LayoutIn(layout=layout(widget()), version=0).version == 0
    with pytest.raises(ValidationError):
        LayoutIn(layout=layout(widget()), version=-1)
    with pytest.raises(ValidationError):
        LayoutIn(layout=layout(widget(type="marketplace")), version=0)
    with pytest.raises(ValidationError):
        LayoutIn(layout=layout(widget()), version=0, extra=True)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_overview_layout_validation.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.project.schemas.overview_layout'`.

- [ ] **Step 3: Write the validation and the bodies**

Create `platforms/project-service/src/project/schemas/overview_layout.py`:

```python
"""Overview layouts: request and response bodies, and validation against the shared widget catalogue
(shared/qeos_shared/overview_widgets.json; spec 2026-10-11 §3.2, plan Ruling 8)."""
import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from qeos_shared.overview_widgets import load_catalog

CATALOG = load_catalog()
MAX_WIDGETS: int = CATALOG["max_widgets"]
MAX_BODY_BYTES: int = CATALOG["max_body_bytes"]
_WIDGET_ID = re.compile(CATALOG["widget_id_pattern"])
_LAYOUT_KEYS = {"schema", "widgets"}
_WIDGET_KEYS = {"id", "type", "size", "settings"}
_REQUIRED_WIDGET_KEYS = {"id", "type", "size"}


class LayoutError(ValueError):
    """The layout breaks a catalogue rule; the message names where."""


def _check_setting(where: str, name: str, value: Any) -> None:
    spec = CATALOG["settings"][name]
    if spec["kind"] == "choice":
        allowed = spec["values"]
        # A bool is an int and 5.0 == 5 in Python: only the exact JSON type of the allowed values passes
        if isinstance(value, bool) or type(value) is not type(allowed[0]) or value not in allowed:
            raise LayoutError(f"{where}: {value!r} is not one of {', '.join(str(v) for v in allowed)}")
        return
    low, high = spec["min_length"], spec["max_length"]
    if not isinstance(value, str) or not low <= len(value) <= high or "\x00" in value:
        raise LayoutError(f"{where}: must be {low}-{high} characters with no NUL")


def validate_layout(layout: Any) -> dict:
    """Returns the layout unchanged, or raises LayoutError at the first rule it breaks."""
    if not isinstance(layout, dict):
        raise LayoutError("layout must be an object")
    extra = set(layout) - _LAYOUT_KEYS
    if extra:
        raise LayoutError(f"layout: unknown key {sorted(extra)[0]!r}")
    schema = layout.get("schema")
    if isinstance(schema, bool) or schema != CATALOG["schema"]:
        raise LayoutError(f"schema must be {CATALOG['schema']}")
    widgets = layout.get("widgets")
    if not isinstance(widgets, list):
        raise LayoutError("widgets must be a list")
    if len(widgets) > MAX_WIDGETS:
        raise LayoutError(f"a layout holds at most {MAX_WIDGETS} widgets")
    seen: set = set()
    for index, widget in enumerate(widgets):
        where = f"widgets[{index}]"
        if not isinstance(widget, dict):
            raise LayoutError(f"{where} must be an object")
        missing = _REQUIRED_WIDGET_KEYS - set(widget)
        if missing:
            raise LayoutError(f"{where}: missing {sorted(missing)[0]!r}")
        extra = set(widget) - _WIDGET_KEYS
        if extra:
            raise LayoutError(f"{where}: unknown key {sorted(extra)[0]!r}")
        widget_id = widget["id"]
        if not isinstance(widget_id, str) or not _WIDGET_ID.fullmatch(widget_id):
            raise LayoutError(f"{where}.id: 1-32 characters of A-Z, a-z, 0-9, _ and -")
        if widget_id in seen:
            raise LayoutError(f"{where}.id: duplicate id {widget_id!r}")
        seen.add(widget_id)
        widget_type = widget["type"]
        if not isinstance(widget_type, str) or widget_type not in CATALOG["types"]:
            raise LayoutError(f"{where}.type: unknown type {widget_type!r}")
        if not isinstance(widget["size"], str) or widget["size"] not in CATALOG["sizes"]:
            raise LayoutError(f"{where}.size: must be normal or wide")
        settings = widget.get("settings", {})
        if not isinstance(settings, dict):
            raise LayoutError(f"{where}.settings must be an object")
        declared = CATALOG["types"][widget_type]["settings"]
        for name, value in settings.items():
            if name not in declared:
                raise LayoutError(f"{where}.settings: {widget_type} has no setting {name!r}")
            _check_setting(f"{where}.settings.{name}", name, value)
    return layout


class LayoutIn(BaseModel):
    """PUT body: the layout and the version editing started from (0 creates; plan Ruling 7)."""

    model_config = ConfigDict(extra="forbid")

    layout: dict
    version: int = Field(ge=0)

    @field_validator("layout")
    @classmethod
    def _valid(cls, value: dict) -> dict:
        return validate_layout(value)


class PersonalMeta(BaseModel):
    version: int
    updated_at: datetime


class ProjectMeta(BaseModel):
    version: int
    updated_by: int
    updated_at: datetime
    # Reset to project default and "Edit project default" need it even when a personal layout wins (plan Ruling 4)
    layout: dict


class OverviewLayoutOut(BaseModel):
    effective: Optional[dict] = None
    source: Literal["personal", "project", "builtin"]
    personal: Optional[PersonalMeta] = None
    project: Optional[ProjectMeta] = None


class LayoutRowOut(BaseModel):
    layout: dict
    version: int
    updated_by: int
    updated_at: datetime
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_overview_layout_validation.py -q`
Expected: PASS, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add platforms/project-service/src/project/schemas/overview_layout.py platforms/project-service/tests/unit/test_overview_layout_validation.py
git commit -m "feat(project): validate Overview layouts against the shared widget catalogue" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/project-service/src/project/schemas/overview_layout.py platforms/project-service/tests/unit/test_overview_layout_validation.py
```

---
### Task 4: The five layout endpoints, roles, versions and the departed-user rule

**Files:**
- Create: `platforms/project-service/src/project/service/overview_layout_service.py`
- Create: `platforms/project-service/src/project/api/v1/endpoints/overview_layout.py`
- Modify: `platforms/project-service/src/project/api/v1/api.py`
- Test: `platforms/project-service/tests/integration/test_overview_layout.py`
- Docs: `platforms/project-service/README.md`, `TECHNICAL_SPECIFICATION.md`

**Interfaces:**
- Consumes: `OverviewLayout` (Task 2); `LayoutIn`, `LayoutRowOut`, `OverviewLayoutOut`, `PersonalMeta`, `ProjectMeta`, `MAX_BODY_BYTES` (Task 3); `require_project_role`, `READ_ROLES`, `MANAGE_ROLES`, `ProjectAccess`, `get_db` from `src.project.api.deps`.
- Produces:
  - `overview_layout_service.StaleVersion(current: Optional[OverviewLayout])` (attribute `current`);
  - `overview_layout_service.get_row(db, project_id: int, user_id: Optional[int]) -> Optional[OverviewLayout]` (`user_id=None` is the project default);
  - `overview_layout_service.save(db, project_id: int, user_id: Optional[int], layout: dict, version: int, by: int) -> OverviewLayout` (raises `StaleVersion`);
  - `overview_layout_service.delete(db, project_id: int, user_id: Optional[int]) -> None`;
  - HTTP: `GET /api/v1/projects/{id}/overview-layout` → `OverviewLayoutOut`; `PUT …/personal` and `PUT …/project` (body `LayoutIn`) → `LayoutRowOut`; `DELETE …/personal`, `DELETE …/project` → 204; 409 `{"detail": {"code": "stale_version", "message": str, "current": {"version": int, "updated_by": int, "updated_at": str} | null}}` (Ruling 5); 422 for a body over 16384 bytes (Ruling 6). The dashboard (Task 9) and the smoke (Task 6) rely on these shapes.

- [ ] **Step 1: Write the failing tests**

Create `platforms/project-service/tests/integration/test_overview_layout.py`:

```python
"""Overview layouts: /api/v1/projects/{id}/overview-layout (spec 2026-10-11 §3.3, §3.4; plan Rulings 4-7)."""
import pytest

ALL_ROLES = ("owner", "admin", "member", "viewer", "billing_manager")


def url(project_id: int, path: str = "") -> str:
    return f"/api/v1/projects/{project_id}/overview-layout{path}"


def layout(*types: str) -> dict:
    return {"schema": 1, "widgets": [{"id": f"w{i + 1}", "type": t, "size": "normal"} for i, t in enumerate(types)]}


def put(client, auth, project_id, scope, body_layout, version, user=1):
    return client.put(url(project_id, f"/{scope}"), json={"layout": body_layout, "version": version}, headers=auth(user))


# (method, path, body, roles allowed, success status): the endpoint table of spec §3.3
ROUTES = [
    ("GET", "", None, ALL_ROLES, 200),
    ("PUT", "/personal", {"layout": layout("latest_run"), "version": 0}, ALL_ROLES, 200),
    ("DELETE", "/personal", None, ALL_ROLES, 204),
    ("PUT", "/project", {"layout": layout("latest_run"), "version": 0}, ("owner", "admin"), 200),
    ("DELETE", "/project", None, ("owner", "admin"), 204),
]


@pytest.mark.parametrize("method, path, body, allowed, ok", ROUTES)
@pytest.mark.parametrize("role", ALL_ROLES)
def test_role_matrix(client, auth, org_role, make_project, method, path, body, allowed, ok, role):
    project = make_project()
    org_role(role)
    response = client.request(method, url(project.id, path), json=body, headers=auth())
    assert response.status_code == (ok if role in allowed else 403)


@pytest.mark.parametrize("method, path, body, allowed, ok", ROUTES)
def test_a_non_member_gets_404_everywhere(client, auth, org_role, make_project, method, path, body, allowed, ok):
    project = make_project()
    org_role(status_code=404, body={"detail": "Not a member"})
    assert client.request(method, url(project.id, path), json=body, headers=auth()).status_code == 404


def test_a_deleted_projects_layouts_are_unreachable(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    put(client, auth, project.id, "project", layout("latest_run"), 0)
    assert client.delete(f"/api/v1/projects/{project.id}", headers=auth()).status_code == 204
    assert client.get(url(project.id), headers=auth()).status_code == 404


def test_nothing_saved_is_the_builtin_default(client, auth, org_role, make_project):
    project = make_project()
    org_role("viewer")
    assert client.get(url(project.id), headers=auth()).json() == {
        "effective": None, "source": "builtin", "personal": None, "project": None,
    }


def test_the_project_default_reaches_everyone_without_a_personal_layout(client, auth, org_role, make_project):
    project = make_project()
    org_role("admin")
    saved = put(client, auth, project.id, "project", layout("pass_rate_trend"), 0, user=3)
    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    assert saved.json()["updated_by"] == 3
    assert saved.json()["layout"] == layout("pass_rate_trend")
    org_role("viewer")
    body = client.get(url(project.id), headers=auth(9)).json()
    assert body["source"] == "project"
    assert body["effective"] == layout("pass_rate_trend")
    assert body["personal"] is None
    assert body["project"]["version"] == 1
    assert body["project"]["updated_by"] == 3
    assert body["project"]["layout"] == layout("pass_rate_trend")


def test_a_personal_layout_wins_and_belongs_to_its_user_only(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    put(client, auth, project.id, "project", layout("latest_run"), 0)
    org_role("viewer")
    assert put(client, auth, project.id, "personal", layout("my_suites"), 0, user=5).status_code == 200
    mine = client.get(url(project.id), headers=auth(5)).json()
    assert mine["source"] == "personal"
    assert mine["effective"] == layout("my_suites")
    assert mine["personal"]["version"] == 1
    # Reset and "Edit project default" need the default even when the personal layout wins
    assert mine["project"]["layout"] == layout("latest_run")
    other = client.get(url(project.id), headers=auth(6)).json()
    assert other["source"] == "project"
    assert other["effective"] == layout("latest_run")


def test_each_save_bumps_the_version(client, auth, org_role, make_project):
    project = make_project()
    org_role("member")
    put(client, auth, project.id, "personal", layout("latest_run"), 0, user=5)
    second = put(client, auth, project.id, "personal", layout("coverage"), 1, user=5)
    assert second.status_code == 200
    assert second.json()["version"] == 2
    assert second.json()["layout"] == layout("coverage")


def test_a_stale_version_is_409_with_the_stored_row(client, auth, org_role, make_project):
    project = make_project()
    org_role("admin")
    put(client, auth, project.id, "project", layout("latest_run"), 0, user=3)
    put(client, auth, project.id, "project", layout("coverage"), 1, user=4)  # someone saved in between
    stale = put(client, auth, project.id, "project", layout("my_suites"), 1, user=3)
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "stale_version"
    assert detail["current"]["version"] == 2
    assert detail["current"]["updated_by"] == 4
    assert detail["current"]["updated_at"]
    assert client.get(url(project.id), headers=auth(3)).json()["effective"] == layout("coverage")


def test_creating_over_an_existing_layout_is_409(client, auth, org_role, make_project):
    project = make_project()
    org_role("viewer")
    put(client, auth, project.id, "personal", layout("latest_run"), 0, user=5)
    again = put(client, auth, project.id, "personal", layout("coverage"), 0, user=5)
    assert again.status_code == 409
    assert again.json()["detail"]["current"]["version"] == 1


def test_updating_a_layout_that_is_gone_is_409_without_a_row(client, auth, org_role, make_project):
    project = make_project()
    org_role("viewer")
    response = put(client, auth, project.id, "personal", layout("latest_run"), 3, user=5)
    assert response.status_code == 409
    assert response.json()["detail"]["current"] is None


def test_reset_personal_falls_back_to_the_project_default(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    put(client, auth, project.id, "project", layout("latest_run"), 0)
    put(client, auth, project.id, "personal", layout("coverage"), 0)
    assert client.delete(url(project.id, "/personal"), headers=auth()).status_code == 204
    body = client.get(url(project.id), headers=auth()).json()
    assert body["source"] == "project"
    assert body["personal"] is None


def test_deleting_the_default_falls_back_to_builtin(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    put(client, auth, project.id, "project", layout("latest_run"), 0)
    assert client.delete(url(project.id, "/project"), headers=auth()).status_code == 204
    assert client.get(url(project.id), headers=auth()).json()["source"] == "builtin"


def test_deleting_what_is_not_there_is_still_204(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    assert client.delete(url(project.id, "/personal"), headers=auth()).status_code == 204
    assert client.delete(url(project.id, "/project"), headers=auth()).status_code == 204


def test_a_departed_users_layout_is_not_served_and_returns_if_they_rejoin(client, auth, org_role, make_project):
    project = make_project()
    org_role("member")
    put(client, auth, project.id, "personal", layout("my_suites"), 0, user=5)
    org_role(status_code=404, body={"detail": "Not a member"})  # removed from the organization
    assert client.get(url(project.id), headers=auth(5)).status_code == 404
    org_role("viewer")  # invited back
    assert client.get(url(project.id), headers=auth(5)).json()["source"] == "personal"


@pytest.mark.parametrize("bad", [
    {"layout": {"schema": 2, "widgets": []}, "version": 0},
    {"layout": layout("marketplace"), "version": 0},
    {"layout": layout("latest_run"), "version": -1},
    {"layout": layout("latest_run")},
    {"layout": layout("latest_run"), "version": 0, "extra": True},
])
def test_invalid_bodies_are_422(client, auth, org_role, make_project, bad):
    project = make_project()
    org_role("owner")
    assert client.put(url(project.id, "/personal"), json=bad, headers=auth()).status_code == 422


def test_a_viewer_is_refused_the_default_before_the_body_is_judged(client, auth, org_role, make_project):
    project = make_project()
    org_role("viewer")
    response = client.put(url(project.id, "/project"), json={"layout": {"schema": 9}, "version": 0}, headers=auth())
    assert response.status_code == 403


def test_a_body_over_16_kb_is_422(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    body = {"layout": layout("latest_run"), "version": 0, "pad": "x" * 17_000}
    response = client.put(url(project.id, "/personal"), json=body, headers=auth())
    assert response.status_code == 422
    assert "16 KB" in response.text


def test_the_largest_valid_layout_fits(client, auth, org_role, make_project):
    project = make_project()
    org_role("owner")
    widgets = [
        {"id": f"w{i}", "type": "my_failures", "size": "normal", "settings": {"author": "a" * 255, "rows": 10}}
        for i in range(24)
    ]
    assert put(client, auth, project.id, "personal", {"schema": 1, "widgets": widgets}, 0).status_code == 200
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_overview_layout.py -q`
Expected: FAIL: every request answers 404 (no route), e.g. `assert 404 == 200`.

- [ ] **Step 3: Write the service**

Create `platforms/project-service/src/project/service/overview_layout_service.py`:

```python
"""Overview layouts: one optional project default (user_id NULL) and one optional personal layout per user.

A save names the version it started from (plan Ruling 7): 0 creates, n updates only while the stored version
is n. Anything else raises StaleVersion with the stored row, or None when there is no row."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session

from src.project.models.overview_layout import OverviewLayout


class StaleVersion(Exception):
    def __init__(self, current: Optional[OverviewLayout]):
        super().__init__("the layout changed since this edit started")
        self.current = current


def _scope(db: Session, project_id: int, user_id: Optional[int]) -> Query:
    query = db.query(OverviewLayout).filter(OverviewLayout.project_id == project_id)
    if user_id is None:
        return query.filter(OverviewLayout.user_id.is_(None))
    return query.filter(OverviewLayout.user_id == user_id)


def get_row(db: Session, project_id: int, user_id: Optional[int]) -> Optional[OverviewLayout]:
    return _scope(db, project_id, user_id).one_or_none()


def save(db: Session, project_id: int, user_id: Optional[int], layout: dict, version: int, by: int) -> OverviewLayout:
    now = datetime.now(timezone.utc)
    if version == 0:
        existing = get_row(db, project_id, user_id)
        if existing is not None:
            raise StaleVersion(existing)
        db.add(OverviewLayout(
            project_id=project_id, user_id=user_id, layout=layout, version=1, updated_by=by, updated_at=now,
        ))
        try:
            db.commit()
        except IntegrityError:
            # Another request created it between the read and the insert
            db.rollback()
            raise StaleVersion(get_row(db, project_id, user_id))
    else:
        changed = _scope(db, project_id, user_id).filter(OverviewLayout.version == version).update(
            {
                OverviewLayout.layout: layout,
                OverviewLayout.version: OverviewLayout.version + 1,
                OverviewLayout.updated_by: by,
                OverviewLayout.updated_at: now,
            },
            synchronize_session=False,
        )
        db.commit()
        if changed == 0:
            raise StaleVersion(get_row(db, project_id, user_id))
    # commit() expired every loaded row, so this reads the stored values
    return get_row(db, project_id, user_id)


def delete(db: Session, project_id: int, user_id: Optional[int]) -> None:
    _scope(db, project_id, user_id).delete(synchronize_session=False)
    db.commit()
```

- [ ] **Step 4: Write the endpoints and mount them**

Create `platforms/project-service/src/project/api/v1/endpoints/overview_layout.py`:

```python
"""The project Overview's layout (spec 2026-10-11 §3.3). GET resolves personal -> project default -> built-in
(`effective` null: the dashboard holds the built-in default). The role check runs before anything is read, so a
personal layout of someone who has left the organization is never served (§3.4)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from src.project.api.deps import MANAGE_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.project.models.overview_layout import OverviewLayout
from src.project.schemas.overview_layout import (
    MAX_BODY_BYTES, LayoutIn, LayoutRowOut, OverviewLayoutOut, PersonalMeta, ProjectMeta,
)
from src.project.service import overview_layout_service as layouts

router = APIRouter()  # mounted at /projects/{project_id}/overview-layout


async def limit_body(request: Request) -> None:
    """Refuses a body over the catalogue's 16 KB (plan Ruling 6). Declared after the role dependency, so it runs after it."""
    if len(await request.body()) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"The layout body is over {MAX_BODY_BYTES // 1024} KB",
        )


def _row(row: OverviewLayout) -> LayoutRowOut:
    return LayoutRowOut(layout=row.layout, version=row.version, updated_by=row.updated_by, updated_at=row.updated_at)


def _conflict(exc: layouts.StaleVersion) -> HTTPException:
    current = exc.current
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "stale_version",
            "message": "This layout was changed since you started editing it",
            "current": None if current is None else {
                "version": current.version,
                "updated_by": current.updated_by,
                "updated_at": current.updated_at.isoformat(),
            },
        },
    )


def _save(db: Session, project_id: int, user_id: Optional[int], payload: LayoutIn, by: int) -> LayoutRowOut:
    try:
        return _row(layouts.save(db, project_id, user_id, payload.layout, payload.version, by=by))
    except layouts.StaleVersion as exc:
        raise _conflict(exc)


@router.get("", response_model=OverviewLayoutOut)
def get_layout(
    project_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    personal = layouts.get_row(db, project_id, access.user_id)
    project = layouts.get_row(db, project_id, None)
    source = "personal" if personal else "project" if project else "builtin"
    effective = personal.layout if personal else project.layout if project else None
    return OverviewLayoutOut(
        effective=effective,
        source=source,
        personal=PersonalMeta(version=personal.version, updated_at=personal.updated_at) if personal else None,
        project=ProjectMeta(
            version=project.version, updated_by=project.updated_by, updated_at=project.updated_at, layout=project.layout,
        ) if project else None,
    )


@router.put("/personal", response_model=LayoutRowOut)
def save_personal(
    project_id: int,
    payload: LayoutIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
    _limit: None = Depends(limit_body),
):
    return _save(db, project_id, access.user_id, payload, by=access.user_id)


@router.delete("/personal", status_code=status.HTTP_204_NO_CONTENT)
def reset_personal(
    project_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    layouts.delete(db, project_id, access.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/project", response_model=LayoutRowOut)
def save_project_default(
    project_id: int,
    payload: LayoutIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
    _limit: None = Depends(limit_body),
):
    return _save(db, project_id, None, payload, by=access.user_id)


@router.delete("/project", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_default(
    project_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    layouts.delete(db, project_id, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Replace `platforms/project-service/src/project/api/v1/api.py` with:

```python
from fastapi import APIRouter

from src.project.api.v1.endpoints import overview_layout, projects, repositories

api_router = APIRouter()
api_router.include_router(projects.org_router, prefix="/organizations/{org_id}/projects", tags=["projects"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(
    repositories.router, prefix="/projects/{project_id}/repositories", tags=["repositories"]
)
api_router.include_router(
    overview_layout.router, prefix="/projects/{project_id}/overview-layout", tags=["overview-layout"]
)

__all__ = ["api_router"]
```

- [ ] **Step 5: Run them to verify they pass**

Run: `cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_overview_layout.py -q`
Expected: PASS, 0 failed.

- [ ] **Step 6: Run the whole service suite**

Run: `cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: PASS, 0 failed.

- [ ] **Step 7: Document the endpoints and the table**

In `platforms/project-service/README.md`, with the Edit tool, replace:

```
## Internal API
```

with:

````
## Overview layouts

The project Overview is a grid of widgets (spec `docs/superpowers/specs/2026-10-11-customisable-overview-design.md`).
Table `overview_layouts` (migration 004): one optional project default (`user_id` NULL) and one optional
personal layout per user, each a JSONB `layout` with a `version`.

| Method, path (`/api/v1/projects/{id}/overview-layout`) | Roles | Behaviour |
|---|---|---|
| `GET` | every project role | `{effective, source, personal, project}`: the caller's personal layout, else the project default, else `source: "builtin"` with `effective: null` (the dashboard holds the built-in default). `personal` is `{version, updated_at}`, `project` is `{version, updated_by, updated_at, layout}`, each `null` when absent |
| `PUT /personal` | every project role | `{"layout": …, "version": n}`; `0` creates. Returns `{layout, version, updated_by, updated_at}` |
| `DELETE /personal` | every project role | back to the project default; 204 |
| `PUT /project` | owner, admin | as `PUT /personal`, for the project default |
| `DELETE /project` | owner, admin | back to the built-in default; 204 |

```json
{"schema": 1, "widgets": [{"id": "w1", "type": "pass_rate_trend", "size": "wide", "settings": {"granularity": "week", "branch": "main"}}]}
```

- **Validation** follows `shared/qeos_shared/overview_widgets.json`, the same file the dashboard registry
  imports: `schema` 1, at most 24 widgets, unique ids of 1–32 characters `[A-Za-z0-9_-]`, a known `type`,
  `size` `normal` or `wide`, only the settings the type declares with allowed values (branch and author
  name: 1–255 characters, no NUL), a body of at most 16 KB. Anything else is a 422.
- **Versions:** a save names the version it started from. If the stored version differs (someone saved in
  between), or a row already exists for `version: 0`, the answer is 409 with
  `{"detail": {"code": "stale_version", "message": …, "current": {version, updated_by, updated_at} | null}}`.
  DELETE takes no version.
- **Lifecycle:** the role check runs first, so the personal layout of someone who left the organization is
  never served (the row stays; it is a few KB). Deleting a project row deletes its layouts (`ON DELETE
  CASCADE`); a soft-deleted project's layouts answer 404 like the project.

## Internal API
````

In `TECHNICAL_SPECIFICATION.md`, with the Edit tool, replace:

```
held project), internal retention endpoint (HTTP Basic, INTERNAL_API_PASSWORD)
consumed by the retention job.
```

with:

```
held project), internal retention endpoint (HTTP Basic, INTERNAL_API_PASSWORD)
consumed by the retention job. Overview layouts (`/projects/{id}/overview-layout`):
GET resolves personal → project default → built-in; `PUT`/`DELETE /personal` for
every role, `/project` for owner/admin; a save names its `version` (0 creates) and
a stale one is a 409 carrying the stored row; layouts are validated against
`shared/qeos_shared/overview_widgets.json` (24 widgets, 16 KB).
```

and replace:

```
cases, case_labels, suites, suite_cases, feature_files, ci_targets,
run_requests.
```

with:

```
cases, case_labels, suites, suite_cases, feature_files, ci_targets,
run_requests. Project: projects, repositories, overview_layouts (a JSONB layout
per project default or user, with a version for conflict checks).
```

- [ ] **Step 8: Commit**

```bash
git add platforms/project-service/src/project/service/overview_layout_service.py platforms/project-service/src/project/api/v1/endpoints/overview_layout.py platforms/project-service/src/project/api/v1/api.py platforms/project-service/tests/integration/test_overview_layout.py platforms/project-service/README.md TECHNICAL_SPECIFICATION.md
git commit -m "feat(project): Overview layout endpoints with role rules and version conflicts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/project-service/src/project/service/overview_layout_service.py platforms/project-service/src/project/api/v1/endpoints/overview_layout.py platforms/project-service/src/project/api/v1/api.py platforms/project-service/tests/integration/test_overview_layout.py platforms/project-service/README.md TECHNICAL_SPECIFICATION.md
```

---

### Task 5: test-management `created_by=me` on the suites list

**Files:**
- Modify: `platforms/test-management-service/src/casebook/api/v1/endpoints/suites.py`
- Modify: `platforms/test-management-service/src/casebook/service/suite_service.py`
- Test: `platforms/test-management-service/tests/integration/test_suites.py`
- Docs: `platforms/test-management-service/README.md`, `TECHNICAL_SPECIFICATION.md`

**Interfaces:**
- Consumes: `ProjectAccess.user_id` from `src.casebook.api.deps`.
- Produces: `GET /api/v1/projects/{id}/suites?created_by=me` (only `me` is accepted, else 422); `suite_service.list_suites(db, project_id: int, search: Optional[str] = None, created_by: Optional[int] = None) -> List[Suite]`. The dashboard's My suites widget (Task 20) calls it.

- [ ] **Step 1: Write the failing tests**

Append to `platforms/test-management-service/tests/integration/test_suites.py`:

```python
def test_created_by_me_lists_only_the_callers_suites(client, auth, project_role):
    project_role("member")
    assert client.post(f"{BASE}/suites", json={"name": "Mine"}, headers=auth(1)).status_code == 201
    assert client.post(f"{BASE}/suites", json={"name": "Theirs"}, headers=auth(2)).status_code == 201
    mine = client.get(f"{BASE}/suites", params={"created_by": "me"}, headers=auth(1)).json()
    assert [s["name"] for s in mine] == ["Mine"]
    everyone = client.get(f"{BASE}/suites", headers=auth(1)).json()
    assert [s["name"] for s in everyone] == ["Mine", "Theirs"]


def test_created_by_me_combines_with_search(client, auth, project_role):
    project_role("member")
    for name in ("Smoke", "Regression"):
        client.post(f"{BASE}/suites", json={"name": name}, headers=auth(1))
    found = client.get(f"{BASE}/suites", params={"created_by": "me", "search": "smo"}, headers=auth(1)).json()
    assert [s["name"] for s in found] == ["Smoke"]


@pytest.mark.parametrize("value", ["someone", "1", ""])
def test_created_by_takes_only_me(client, auth, project_role, value):
    project_role("viewer")
    assert client.get(f"{BASE}/suites", params={"created_by": value}, headers=auth()).status_code == 422
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd platforms/test-management-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_suites.py -q`
Expected: FAIL: `test_created_by_me_lists_only_the_callers_suites` gets both names; `test_created_by_takes_only_me` gets 200.

- [ ] **Step 3: Implement the filter**

In `platforms/test-management-service/src/casebook/service/suite_service.py`, replace:

```python
def list_suites(db: Session, project_id: int, search: Optional[str] = None) -> List[Suite]:
    query = db.query(Suite).filter(Suite.project_id == project_id)
    if search:
```

with:

```python
def list_suites(
    db: Session, project_id: int, search: Optional[str] = None, created_by: Optional[int] = None,
) -> List[Suite]:
    query = db.query(Suite).filter(Suite.project_id == project_id)
    if created_by is not None:
        query = query.filter(Suite.created_by == created_by)
    if search:
```

In `platforms/test-management-service/src/casebook/api/v1/endpoints/suites.py`, replace:

```python
from typing import Optional
```

with:

```python
from typing import Literal, Optional
```

and replace:

```python
@router.get("", response_model=list[SuiteOut])
def list_suites(
    search: Optional[str] = Query(None, min_length=1, max_length=200, pattern=r"^[^\x00]*$"),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return [suite_service.out(db, row) for row in suite_service.list_suites(db, access.project_id, search)]
```

with:

```python
@router.get("", response_model=list[SuiteOut])
def list_suites(
    search: Optional[str] = Query(None, min_length=1, max_length=200, pattern=r"^[^\x00]*$"),
    # "me": the caller's own suites (the Overview's My suites widget); no other value is accepted
    created_by: Optional[Literal["me"]] = Query(None),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    mine = access.user_id if created_by == "me" else None
    rows = suite_service.list_suites(db, access.project_id, search, created_by=mine)
    return [suite_service.out(db, row) for row in rows]
```

- [ ] **Step 4: Run them to verify they pass**

Run: `cd platforms/test-management-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_suites.py -q`
Expected: PASS, 0 failed.

- [ ] **Step 5: Run the whole service suite**

Run: `cd platforms/test-management-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: PASS, 0 failed.

- [ ] **Step 6: Document it**

In `platforms/test-management-service/README.md`, with the Edit tool, replace:

```
| `GET` | `/suites?search=` | `search` (1-200 characters, no NUL, else 422): case-insensitive contains match on the suite name, `%` and `_` literal; every project role |
```

with:

```
| `GET` | `/suites?search=&created_by=me` | `search` (1-200 characters, no NUL, else 422): case-insensitive contains match on the suite name, `%` and `_` literal; `created_by=me` keeps the caller's own suites (any other value is a 422); every project role |
```

In `TECHNICAL_SPECIFICATION.md`, with the Edit tool, replace:

```
  `PUT /suites/{id}/cases` (≤1000, unknown or repeated numbers are a 422); deleting a suite keeps
  its cases.
```

with:

```
  `PUT /suites/{id}/cases` (≤1000, unknown or repeated numbers are a 422); deleting a suite keeps
  its cases. `GET /suites?created_by=me` lists the caller's own suites.
```

- [ ] **Step 7: Commit**

```bash
git add platforms/test-management-service/src/casebook/api/v1/endpoints/suites.py platforms/test-management-service/src/casebook/service/suite_service.py platforms/test-management-service/tests/integration/test_suites.py platforms/test-management-service/README.md TECHNICAL_SPECIFICATION.md
git commit -m "feat(test-management): suites list filter created_by=me" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/test-management-service/src/casebook/api/v1/endpoints/suites.py platforms/test-management-service/src/casebook/service/suite_service.py platforms/test-management-service/tests/integration/test_suites.py platforms/test-management-service/README.md TECHNICAL_SPECIFICATION.md
```

---

### Task 6: Gateway smoke checks for Overview layouts

**Files:**
- Modify: `scripts/smoke_gateway.sh` (stays `100755`)

**Interfaces:**
- Consumes: the endpoints of Task 4; the smoke script's `check`, `body_has`, `AUTH`, `INVITEE_AUTH`, `INVITEE`, `ORG_ID`, `PROJECT_ID`, `BASE`, `TMP`; organization-service `GET`/`POST /organizations/{id}/members` and `DELETE /organizations/{id}/members/{member_id}` (an owner may remove a member and add a user back with any role; `MemberOut` serialises `id, organization_id, user_id, email, …` in that order).
- Produces: smoke lines proving the route through the gateway: builtin GET, personal round-trip, a viewer's `PUT /project` refused with 403. The gateway itself is not changed: the path falls under `location /api/v1/projects`, and no regex location in `gateway/nginx.conf.template` matches `overview-layout` (they name `cases/import`, `case-areas`, `cases|case-labels|case-folders|case-features|case-areas|features|suites|ci-target|run-requests`, `analytics/report`, and `api-keys|runs|analytics|masking-patterns|export|notification-channels`).

- [ ] **Step 1: Write the new checks**

In `scripts/smoke_gateway.sh`, with the Edit tool, replace:

```
body_has "... the invitee's email is on their row" "$INVITEE"
```

with:

```
body_has "... the invitee's email is on their row" "$INVITEE"

# ---- Overview layouts -> project-service (spec 2026-10-11 §3.3): no gateway rule names the path ----
LAYOUT_URL="$BASE/api/v1/projects/$PROJECT_ID/overview-layout"
LAYOUT_BODY='{"version":0,"layout":{"schema":1,"widgets":[{"id":"w1","type":"pass_rate_trend","size":"wide","settings":{"granularity":"week","branch":"main"}}]}}'
check "overview layout -> project-service (nothing saved yet)" 200 GET "$LAYOUT_URL" "${INVITEE_AUTH[@]}"
body_has "... the built-in default" '"source":"builtin"'
check "save a personal overview layout" 200 PUT "$LAYOUT_URL/personal" "${INVITEE_AUTH[@]}" \
  -H "Content-Type: application/json" -d "$LAYOUT_BODY"
body_has "... version 1" '"version":1'
check "read the personal layout back" 200 GET "$LAYOUT_URL" "${INVITEE_AUTH[@]}"
body_has "... served as personal" '"source":"personal"'
body_has "... with its widget" '"type":"pass_rate_trend"'
# A viewer keeps a personal layout but never sets the project default: make the invitee a viewer
check "list members to find the invitee" 200 GET "$BASE/api/v1/organizations/$ORG_ID/members" "${AUTH[@]}"
INVITEE_ROW="$(grep -o "\"id\":[0-9]*,\"organization_id\":$ORG_ID,\"user_id\":[0-9]*,\"email\":\"$INVITEE\"" "$TMP/body" | head -1)"
INVITEE_MEMBER_ID="$(printf '%s' "$INVITEE_ROW" | sed -n 's/^"id":\([0-9]*\),.*/\1/p')"
INVITEE_USER_ID="$(printf '%s' "$INVITEE_ROW" | sed -n 's/.*"user_id":\([0-9]*\),.*/\1/p')"
check "remove the invitee's member role" 204 DELETE \
  "$BASE/api/v1/organizations/$ORG_ID/members/${INVITEE_MEMBER_ID:-0}" "${AUTH[@]}"
check "add the invitee back as a viewer" 201 POST "$BASE/api/v1/organizations/$ORG_ID/members" "${AUTH[@]}" \
  -H "Content-Type: application/json" -d "{\"user_id\":${INVITEE_USER_ID:-0},\"role\":\"viewer\"}"
check "a viewer's PUT of the project default is refused" 403 PUT "$LAYOUT_URL/project" "${INVITEE_AUTH[@]}" \
  -H "Content-Type: application/json" -d "$LAYOUT_BODY"
check "the viewer's personal layout survived the role change" 200 GET "$LAYOUT_URL" "${INVITEE_AUTH[@]}"
body_has "... still personal" '"source":"personal"'
check "the owner sets the project default" 200 PUT "$LAYOUT_URL/project" "${AUTH[@]}" \
  -H "Content-Type: application/json" -d "$LAYOUT_BODY"
```

- [ ] **Step 2: Run the smoke on the current tree**

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```
Expected: the new lines print `ok`, for example `ok    a viewer's PUT of the project default is refused (403)`, and the run ends with `all gateway checks passed`. (Against an image built before Task 4, the first new check reads `FAIL  overview layout -> project-service (nothing saved yet): expected 200, got 404`: that is the red state these checks guard.)

- [ ] **Step 3: Tear down**

Run: `SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose down` (never `-v`).

- [ ] **Step 4: Commit, keeping the executable bit**

```bash
git add scripts/smoke_gateway.sh
git update-index --chmod=+x scripts/smoke_gateway.sh
git diff --cached --name-only
```
Expected: exactly `scripts/smoke_gateway.sh`. If anything else is listed, unstage it with `git restore --staged <path>` first.

```bash
git commit -m "test(smoke): Overview layouts through the gateway (builtin, personal round-trip, viewer 403)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git ls-files -s scripts/smoke_gateway.sh
```
Expected: the line starts with `100755`.

---

### Task 7: Phase 1 gate

**Files:** none new (fixes only, in the files of Tasks 1–6).

**Interfaces:** Consumes everything in Phase 1; produces a pushed `master`.

- [ ] **Step 1: Every Python suite, serially**

```bash
cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests -q
cd platforms/organization-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/auth-service/auth-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/test-management-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd collector && .venv/Scripts/python -m pytest -q
```
Expected: all green.

- [ ] **Step 2: Dashboard checks (unchanged in this phase, still part of CI)**

Run: `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build && node --test ../templates/github/qeos-run.test.mjs`
Expected: all green.

- [ ] **Step 3: Per-service container smoke for the two changed services**

```bash
cd platforms/project-service && SECRET_KEY=ci-smoke-secret docker compose up --build --detach --wait --wait-timeout 180 && curl --fail --silent --show-error http://localhost:8002/health && SECRET_KEY=ci-smoke-secret docker compose down --volumes
cd platforms/test-management-service && SECRET_KEY=ci-smoke-secret docker compose up --build --detach --wait --wait-timeout 180 && curl --fail --silent --show-error http://localhost:8004/health && SECRET_KEY=ci-smoke-secret docker compose down --volumes
```
Expected: `{"status":"healthy"}` twice. These per-service stacks use throwaway volumes, as CI's `smoke` job does.

- [ ] **Step 4: Gateway, monitoring checks and the full smoke**

```bash
docker build -t qeos/gateway:ci gateway && docker run --rm qeos/gateway:ci nginx -t
bash monitoring/check.sh
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose exec -T project-service alembic current
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```
Expected: `nginx: configuration file /etc/nginx/nginx.conf test is successful`; `monitoring: all checks passed`; `004 (head)`; the smoke ends with `all gateway checks passed`.

- [ ] **Step 5: Tear down, check the script mode, push**

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose down
git ls-files -s scripts/smoke_gateway.sh
git status --short
git log --oneline origin/master..master
git push origin master
```
Expected: `100755` for the script; no modified tracked file of this plan left; the log lists the Phase 1 commits; the push succeeds. Never `docker compose down -v`.

---

# Phase 2 — Frame

Useful by itself: the Overview is widget-based with today's four cards, and every role can customise it; owners and admins edit the project default.

### Task 8: The catalogue in the dashboard, the built-in default, and the Dockerfile

**Files:**
- Create: `dashboard/src/overview/catalog.ts`, `dashboard/src/overview/templates.ts`
- Test: `dashboard/src/overview/catalog.test.ts`
- Modify: `dashboard/tsconfig.json`, `dashboard/vite.config.ts`, `dashboard/Dockerfile`

**Interfaces:**
- Consumes: `shared/qeos_shared/overview_widgets.json` (Task 1).
- Produces, in `src/overview/catalog.ts`:
  - types `WidgetSize = "normal" | "wide"`, `SettingName = "rows" | "period" | "granularity" | "branch" | "author"`, `WidgetType` (the 14 ids), `SettingSpec`, `Catalog`;
  - `interface WidgetSettings { rows?: number; period?: number; granularity?: TrendBucket; branch?: string; author?: string }`;
  - `interface StoredWidget { id: string; type: string; size: WidgetSize; settings?: WidgetSettings }`, `interface StoredLayout { schema: number; widgets: StoredWidget[] }`;
  - `CATALOG: Catalog`, `MAX_WIDGETS: number`, `ALL = "all"`;
  - `isValidSetting(name: SettingName, value: unknown): boolean`, `isValidWidgetId(id: string): boolean`, `layoutProblems(layout: StoredLayout): string[]` (empty when project-service would accept it).
- Produces, in `src/overview/templates.ts`: `BUILTIN_DEFAULT: StoredLayout` (w1 `latest_run` wide, w2 `failing_now` rows 5, w3 `pass_rate_week` branch `all`, w4 `flaky_count` period 14).

- [ ] **Step 1: Write the failing test**

Create `dashboard/src/overview/catalog.test.ts`:

```ts
import { ALL, CATALOG, MAX_WIDGETS, type StoredLayout, isValidSetting, isValidWidgetId, layoutProblems } from "./catalog";
import { BUILTIN_DEFAULT } from "./templates";

test("the dashboard reads the shared catalogue file", () => {
  expect(CATALOG.schema).toBe(1);
  expect(MAX_WIDGETS).toBe(24);
  expect(Object.keys(CATALOG.types)).toHaveLength(14);
  expect(CATALOG.types.my_failures.settings).toEqual(["author", "rows"]);
});

test("settings are checked against their allowed values", () => {
  expect(isValidSetting("rows", 10)).toBe(true);
  expect(isValidSetting("rows", 7)).toBe(false);
  expect(isValidSetting("rows", "5")).toBe(false);
  expect(isValidSetting("period", 14)).toBe(true);
  expect(isValidSetting("granularity", "month")).toBe(true);
  expect(isValidSetting("branch", ALL)).toBe(true);
  expect(isValidSetting("branch", "")).toBe(false);
  expect(isValidSetting("branch", "x".repeat(256))).toBe(false);
  expect(isValidSetting("author", "a\u0000b")).toBe(false);
});

test("widget ids follow the catalogue pattern", () => {
  expect(isValidWidgetId("w1")).toBe(true);
  expect(isValidWidgetId("x".repeat(33))).toBe(false);
  expect(isValidWidgetId("bad id")).toBe(false);
});

test("the built-in default is today's four cards and a layout the server accepts", () => {
  expect(BUILTIN_DEFAULT.widgets.map((w) => [w.type, w.size])).toEqual([
    ["latest_run", "wide"], ["failing_now", "normal"], ["pass_rate_week", "normal"], ["flaky_count", "normal"],
  ]);
  expect(layoutProblems(BUILTIN_DEFAULT)).toEqual([]);
});

test("layoutProblems names what the server would refuse", () => {
  const bad: StoredLayout = {
    schema: 1,
    widgets: [
      { id: "a", type: "failing_now", size: "normal", settings: { rows: 7 } },
      { id: "a", type: "nope", size: "normal" },
      { id: "c", type: "latest_run", size: "normal", settings: { branch: "main" } },
    ],
  };
  expect(layoutProblems(bad)).toEqual(["widgets[0].settings.rows", "widgets[1].id duplicate", "widgets[1].type", "widgets[2].settings.branch"]);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd dashboard && npx vitest run src/overview/catalog.test.ts`
Expected: FAIL with `Failed to resolve import "./catalog"`.

- [ ] **Step 3: Write the catalogue module and the built-in default**

Create `dashboard/src/overview/catalog.ts`:

```ts
import raw from "../../../shared/qeos_shared/overview_widgets.json";
import type { TrendBucket } from "../api/analytics";

/** The Overview widget catalogue, shared with project-service (spec 2026-10-11 §3.2): the types, their settings and
 *  allowed values, and the layout limits. project-service validates saved layouts against the same file, and
 *  widgets/registry.test.ts fails when the registry and this file disagree. The Dockerfile copies the file. */

export type WidgetSize = "normal" | "wide";
export type SettingName = "rows" | "period" | "granularity" | "branch" | "author";
export type WidgetType =
  | "latest_run" | "failing_now" | "pass_rate_week" | "flaky_count" | "pass_rate_trend" | "failure_causes"
  | "regressions" | "recent_runs" | "branch_health" | "slowest_tests" | "coverage" | "case_tiles"
  | "my_failures" | "my_suites";

export interface ChoiceSetting { kind: "choice"; values: (string | number)[] }
export interface TextSetting { kind: "text"; min_length: number; max_length: number }
export type SettingSpec = ChoiceSetting | TextSetting;

export interface Catalog {
  schema: number;
  max_widgets: number;
  max_body_bytes: number;
  widget_id_pattern: string;
  sizes: WidgetSize[];
  settings: Record<SettingName, SettingSpec>;
  types: Record<WidgetType, { settings: SettingName[] }>;
}

export const CATALOG = raw as unknown as Catalog;
export const MAX_WIDGETS = CATALOG.max_widgets;
const WIDGET_ID = new RegExp(CATALOG.widget_id_pattern);

/** Every branch (spec §2.4); any other branch value names one branch. */
export const ALL = "all";

export interface WidgetSettings {
  rows?: number;
  period?: number;
  granularity?: TrendBucket;
  branch?: string;
  author?: string;
}

/** A widget as stored: `type` is a string because a stored layout may name a type this dashboard does not know. */
export interface StoredWidget {
  id: string;
  type: string;
  size: WidgetSize;
  settings?: WidgetSettings;
}

export interface StoredLayout {
  schema: number;
  widgets: StoredWidget[];
}

export function isValidSetting(name: SettingName, value: unknown): boolean {
  const spec = CATALOG.settings[name];
  if (spec.kind === "choice") return spec.values.some((allowed) => allowed === value);
  return typeof value === "string" && value.length >= spec.min_length && value.length <= spec.max_length && !value.includes("\u0000");
}

export function isValidWidgetId(id: string): boolean {
  return WIDGET_ID.test(id);
}

/** What project-service would refuse in this layout (its validation, mirrored for the templates' tests). */
export function layoutProblems(layout: StoredLayout): string[] {
  const problems: string[] = [];
  if (layout.schema !== CATALOG.schema) problems.push("schema");
  if (layout.widgets.length > MAX_WIDGETS) problems.push("widgets");
  const seen = new Set<string>();
  layout.widgets.forEach((widget, index) => {
    const at = `widgets[${index}]`;
    if (!isValidWidgetId(widget.id)) problems.push(`${at}.id`);
    else if (seen.has(widget.id)) problems.push(`${at}.id duplicate`);
    seen.add(widget.id);
    const type = (CATALOG.types as Record<string, { settings: SettingName[] } | undefined>)[widget.type];
    if (type === undefined) {
      problems.push(`${at}.type`);
      return;
    }
    if (!CATALOG.sizes.includes(widget.size)) problems.push(`${at}.size`);
    for (const [name, value] of Object.entries(widget.settings ?? {})) {
      if (!type.settings.includes(name as SettingName) || !isValidSetting(name as SettingName, value)) {
        problems.push(`${at}.settings.${name}`);
      }
    }
  });
  return problems;
}
```

Create `dashboard/src/overview/templates.ts`:

```ts
import type { StoredLayout } from "./catalog";

/** What the Overview shows when neither a personal layout nor a project default exists: today's four cards
 *  (spec §2.1). The API answers `effective: null` in that case; the dashboard holds this layout. */
export const BUILTIN_DEFAULT: StoredLayout = {
  schema: 1,
  widgets: [
    { id: "w1", type: "latest_run", size: "wide", settings: {} },
    { id: "w2", type: "failing_now", size: "normal", settings: { rows: 5 } },
    { id: "w3", type: "pass_rate_week", size: "normal", settings: { branch: "all" } },
    { id: "w4", type: "flaky_count", size: "normal", settings: { period: 14 } },
  ],
};
```

In `dashboard/tsconfig.json`, replace:

```json
    "skipLibCheck": true,
```

with:

```json
    "skipLibCheck": true,
    "resolveJsonModule": true,
```

In `dashboard/vite.config.ts`, replace:

```ts
    proxy: { "/api": { target: "https://localhost:8443", secure: false } },
```

with:

```ts
    proxy: { "/api": { target: "https://localhost:8443", secure: false } },
    // The Overview widget catalogue lives in shared/ (one file for project-service and the dashboard)
    fs: { allow: [".", "../shared/qeos_shared/overview_widgets.json"] },
```

In `dashboard/Dockerfile`, replace:

```dockerfile
COPY dashboard/ ./
```

with:

```dockerfile
COPY dashboard/ ./
# The Overview widget catalogue is shared with project-service (spec 2026-10-11 §3.2). src/overview/catalog.ts
# imports ../../../shared/..., which from /app/src/overview resolves to /shared/.
COPY shared/qeos_shared/overview_widgets.json /shared/qeos_shared/overview_widgets.json
```

- [ ] **Step 4: Run it to verify it passes, and typecheck**

Run: `cd dashboard && npx vitest run src/overview/catalog.test.ts && npm run typecheck`
Expected: PASS, 5 tests; typecheck exits 0.

- [ ] **Step 5: Build the image to prove the Dockerfile copy**

Run: `SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose build dashboard`
Expected: the build succeeds (no `Could not resolve "../../../shared/qeos_shared/overview_widgets.json"` from `vite build`).

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/overview/catalog.ts dashboard/src/overview/templates.ts dashboard/src/overview/catalog.test.ts dashboard/tsconfig.json dashboard/vite.config.ts dashboard/Dockerfile
git commit -m "feat(dashboard): read the shared Overview widget catalogue; built-in default layout" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/catalog.ts dashboard/src/overview/templates.ts dashboard/src/overview/catalog.test.ts dashboard/tsconfig.json dashboard/vite.config.ts dashboard/Dockerfile
```

---

### Task 9: The layout API client and `useOverviewLayout`

**Files:**
- Create: `dashboard/src/api/overviewLayout.ts`, `dashboard/src/overview/useOverviewLayout.ts`
- Test: `dashboard/src/api/overviewLayout.test.ts`, `dashboard/src/overview/useOverviewLayout.test.ts`, `dashboard/src/api/http.test.ts`
- Modify: `dashboard/src/api/http.ts`, `dashboard/src/test/server.ts`

**Interfaces:**
- Consumes: `apiFetch`, `ApiError` (`src/api/http.ts`); `StoredLayout` (Task 8); the endpoints of Task 4.
- Produces:
  - `ApiError` gains a fourth constructor parameter `public body?: unknown` (the parsed error body; Ruling 5);
  - in `src/api/overviewLayout.ts`: `type LayoutSource = "personal" | "project" | "builtin"`; `type LayoutMode = "personal" | "project"`; `interface PersonalMeta { version: number; updated_at: string }`; `interface ProjectMeta { version: number; updated_by: number; updated_at: string; layout: StoredLayout }`; `interface OverviewLayoutState { effective: StoredLayout | null; source: LayoutSource; personal: PersonalMeta | null; project: ProjectMeta | null }`; `interface LayoutRow { layout: StoredLayout; version: number; updated_by: number; updated_at: string }`; `interface StoredVersion { version: number; updated_by: number; updated_at: string }`; `getOverviewLayout(projectId: number): Promise<OverviewLayoutState>`; `saveLayout(projectId: number, mode: LayoutMode, layout: StoredLayout, version: number): Promise<LayoutRow>`; `deleteLayout(projectId: number, mode: LayoutMode): Promise<void>`; `conflictOf(error: unknown): StoredVersion | null | undefined` (undefined: not a stale-version 409; null: the row is gone);
  - in `src/overview/useOverviewLayout.ts`: `layoutKey(projectId: number)` → `["overview-layout", projectId]`; `afterSave(old: OverviewLayoutState, mode: LayoutMode, row: LayoutRow): OverviewLayoutState`; `afterReset(old: OverviewLayoutState, mode: LayoutMode): OverviewLayoutState`; `useOverviewLayout(projectId: number)` returning `{ query, save, reset }` where `save.mutateAsync({ mode, layout, version })` resolves to a `LayoutRow` and `reset.mutateAsync(mode)` to `void`;
  - `src/test/server.ts` answers `GET /api/v1/projects/:projectId/overview-layout` with the builtin state by default.

- [ ] **Step 1: Write the failing tests**

Append to `dashboard/src/api/http.test.ts`:

```ts
test("an error keeps its parsed body for callers that need more than the message", async () => {
  setAccessToken("acc");
  server.use(
    http.put("/api/v1/thing", () => HttpResponse.json(
      { detail: { code: "stale_version", message: "Changed meanwhile", current: { version: 4 } } }, { status: 409 },
    )),
  );
  const error = await apiFetch("/api/v1/thing", { method: "PUT", body: "{}" }).catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).detail).toBe("Changed meanwhile");
  expect((error as ApiError).code).toBe("stale_version");
  expect((error as ApiError).body).toEqual({ detail: { code: "stale_version", message: "Changed meanwhile", current: { version: 4 } } });
});
```

Create `dashboard/src/api/overviewLayout.test.ts`:

```ts
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { ApiError } from "./http";
import { conflictOf, deleteLayout, getOverviewLayout, saveLayout } from "./overviewLayout";

const LAYOUT = { schema: 1, widgets: [{ id: "w1", type: "latest_run", size: "wide" as const }] };

beforeEach(() => setAccessToken("acc"));

test("reads the layout state", async () => {
  server.use(http.get("/api/v1/projects/42/overview-layout", () =>
    HttpResponse.json({ effective: null, source: "builtin", personal: null, project: null })));
  await expect(getOverviewLayout(42)).resolves.toEqual({ effective: null, source: "builtin", personal: null, project: null });
});

test("saves a personal or project layout with the version editing started from", async () => {
  const sent: { mode: string; body: unknown }[] = [];
  server.use(http.put("/api/v1/projects/42/overview-layout/:mode", async ({ request, params }) => {
    sent.push({ mode: String(params.mode), body: await request.json() });
    return HttpResponse.json({ layout: LAYOUT, version: 3, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
  }));
  await expect(saveLayout(42, "personal", LAYOUT, 2)).resolves.toMatchObject({ version: 3 });
  await saveLayout(42, "project", LAYOUT, 0);
  expect(sent).toEqual([
    { mode: "personal", body: { layout: LAYOUT, version: 2 } },
    { mode: "project", body: { layout: LAYOUT, version: 0 } },
  ]);
});

test("deletes a layout", async () => {
  const deleted: string[] = [];
  server.use(http.delete("/api/v1/projects/42/overview-layout/:mode", ({ params }) => {
    deleted.push(String(params.mode));
    return new HttpResponse(null, { status: 204 });
  }));
  await expect(deleteLayout(42, "project")).resolves.toBeUndefined();
  expect(deleted).toEqual(["project"]);
});

test("conflictOf reads the stored version a stale save names, and nothing from other errors", () => {
  const current = { version: 5, updated_by: 7, updated_at: "2026-10-11T09:00:00Z" };
  expect(conflictOf(new ApiError(409, "Changed", "stale_version", { detail: { code: "stale_version", current } }))).toEqual(current);
  expect(conflictOf(new ApiError(409, "Changed", "stale_version", { detail: { code: "stale_version", current: null } }))).toBeNull();
  expect(conflictOf(new ApiError(409, "Duplicate"))).toBeUndefined();
  expect(conflictOf(new ApiError(422, "schema must be 1"))).toBeUndefined();
  expect(conflictOf(new Error("boom"))).toBeUndefined();
});
```

Create `dashboard/src/overview/useOverviewLayout.test.ts`:

```ts
import type { LayoutRow, OverviewLayoutState } from "../api/overviewLayout";
import { afterReset, afterSave } from "./useOverviewLayout";

const A = { schema: 1, widgets: [{ id: "a", type: "latest_run", size: "wide" as const }] };
const B = { schema: 1, widgets: [{ id: "b", type: "my_suites", size: "normal" as const }] };
const row = (version = 2): LayoutRow => ({ layout: A, version, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
const builtin: OverviewLayoutState = { effective: null, source: "builtin", personal: null, project: null };
const withDefault: OverviewLayoutState = {
  effective: B, source: "project", personal: null,
  project: { version: 1, updated_by: 3, updated_at: "2026-10-01T00:00:00Z", layout: B },
};
const withPersonal: OverviewLayoutState = {
  ...withDefault, effective: A, source: "personal", personal: { version: 4, updated_at: "2026-10-02T00:00:00Z" },
};

test("a personal save becomes what this user sees", () => {
  expect(afterSave(withDefault, "personal", row(1))).toEqual({
    ...withDefault, effective: A, source: "personal", personal: { version: 1, updated_at: "2026-10-11T10:00:00Z" },
  });
});

test("a project save shows only when no personal layout wins", () => {
  const project = { version: 2, updated_by: 7, updated_at: "2026-10-11T10:00:00Z", layout: A };
  expect(afterSave(builtin, "project", row())).toEqual({ ...builtin, effective: A, source: "project", project });
  expect(afterSave(withPersonal, "project", row())).toEqual({ ...withPersonal, project });
});

test("resets fall back one level", () => {
  expect(afterReset(withPersonal, "personal")).toEqual({ ...withPersonal, personal: null, effective: B, source: "project" });
  expect(afterReset(withDefault, "project")).toEqual({ ...withDefault, project: null, effective: null, source: "builtin" });
  expect(afterReset(withPersonal, "project")).toEqual({ ...withPersonal, project: null });
  expect(afterReset({ ...withPersonal, project: null }, "personal")).toMatchObject({ effective: null, source: "builtin" });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/api/http.test.ts src/api/overviewLayout.test.ts src/overview/useOverviewLayout.test.ts`
Expected: FAIL: `Failed to resolve import "./overviewLayout"`, `Failed to resolve import "./useOverviewLayout"`, and in http.test.ts `expected undefined to deeply equal { detail: … }`.

- [ ] **Step 3: Keep the error body on `ApiError`**

In `dashboard/src/api/http.ts`, replace:

```ts
    /** Machine-readable reason, when the API sends an object detail ({code, message}). */
    public code?: string,
  ) {
```

with:

```ts
    /** Machine-readable reason, when the API sends an object detail ({code, message}). */
    public code?: string,
    /** The parsed JSON body, for callers that need more than the message (a 409's stored version). */
    public body?: unknown,
  ) {
```

replace:

```ts
  let detail = `Request failed with status ${response.status}`;
  let code: string | undefined;
  try {
    const body = await response.json();
```

with:

```ts
  let detail = `Request failed with status ${response.status}`;
  let code: string | undefined;
  let parsed: unknown;
  try {
    const body = await response.json();
    parsed = body;
```

and replace:

```ts
  return new ApiError(response.status, detail, code);
}
```

with:

```ts
  return new ApiError(response.status, detail, code, parsed);
}
```

- [ ] **Step 4: Write the client and the hook**

Create `dashboard/src/api/overviewLayout.ts`:

```ts
import { ApiError, apiFetch } from "./http";
import type { StoredLayout } from "../overview/catalog";

// Types mirror platforms/project-service/src/project/schemas/overview_layout.py

export type LayoutSource = "personal" | "project" | "builtin";
export type LayoutMode = "personal" | "project";

export interface PersonalMeta { version: number; updated_at: string }
/** `layout` is the project default itself, present even when a personal layout wins (plan Ruling 4). */
export interface ProjectMeta { version: number; updated_by: number; updated_at: string; layout: StoredLayout }

export interface OverviewLayoutState {
  /** null: nothing is saved, the dashboard shows its built-in default. */
  effective: StoredLayout | null;
  source: LayoutSource;
  personal: PersonalMeta | null;
  project: ProjectMeta | null;
}

export interface LayoutRow { layout: StoredLayout; version: number; updated_by: number; updated_at: string }

/** The stored row a 409 names. */
export interface StoredVersion { version: number; updated_by: number; updated_at: string }

const base = (projectId: number) => `/api/v1/projects/${projectId}/overview-layout`;

export function getOverviewLayout(projectId: number): Promise<OverviewLayoutState> {
  return apiFetch(base(projectId));
}

/** `version` is the one editing started from; 0 creates. A stale version is a 409 (see conflictOf). */
export function saveLayout(projectId: number, mode: LayoutMode, layout: StoredLayout, version: number): Promise<LayoutRow> {
  return apiFetch(`${base(projectId)}/${mode}`, { method: "PUT", body: JSON.stringify({ layout, version }) });
}

export function deleteLayout(projectId: number, mode: LayoutMode): Promise<void> {
  return apiFetch(`${base(projectId)}/${mode}`, { method: "DELETE" });
}

/** The stored version a stale save names: undefined when the error is something else, null when the row is gone. */
export function conflictOf(error: unknown): StoredVersion | null | undefined {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== "stale_version") return undefined;
  const detail = (error.body as { detail?: { current?: StoredVersion | null } } | undefined)?.detail;
  return detail?.current ?? null;
}
```

Create `dashboard/src/overview/useOverviewLayout.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type LayoutMode, type LayoutRow, type OverviewLayoutState, deleteLayout, getOverviewLayout, saveLayout,
} from "../api/overviewLayout";
import type { StoredLayout } from "./catalog";

export const layoutKey = (projectId: number) => ["overview-layout", projectId] as const;

/** The state after a successful save, so the page shows it at once (a refetch follows). */
export function afterSave(old: OverviewLayoutState, mode: LayoutMode, row: LayoutRow): OverviewLayoutState {
  if (mode === "personal") {
    return { ...old, effective: row.layout, source: "personal", personal: { version: row.version, updated_at: row.updated_at } };
  }
  const project = { version: row.version, updated_by: row.updated_by, updated_at: row.updated_at, layout: row.layout };
  return old.source === "personal" ? { ...old, project } : { ...old, project, effective: row.layout, source: "project" };
}

/** The state after a reset: personal falls back to the project default, the project default to the built-in one. */
export function afterReset(old: OverviewLayoutState, mode: LayoutMode): OverviewLayoutState {
  if (mode === "personal") {
    return { ...old, personal: null, effective: old.project?.layout ?? null, source: old.project ? "project" : "builtin" };
  }
  return old.source === "personal" ? { ...old, project: null } : { ...old, project: null, effective: null, source: "builtin" };
}

export function useOverviewLayout(projectId: number) {
  const queryClient = useQueryClient();
  const key = layoutKey(projectId);
  const query = useQuery({ queryKey: key, queryFn: () => getOverviewLayout(projectId), staleTime: 60_000 });
  const apply = (next: (old: OverviewLayoutState) => OverviewLayoutState) => {
    queryClient.setQueryData<OverviewLayoutState>(key, (old) => (old ? next(old) : old));
    void queryClient.invalidateQueries({ queryKey: key });
  };
  const save = useMutation({
    mutationFn: (args: { mode: LayoutMode; layout: StoredLayout; version: number }) =>
      saveLayout(projectId, args.mode, args.layout, args.version),
    onSuccess: (row, args) => apply((old) => afterSave(old, args.mode, row)),
  });
  const reset = useMutation({
    mutationFn: (mode: LayoutMode) => deleteLayout(projectId, mode),
    onSuccess: (_, mode) => apply((old) => afterReset(old, mode)),
  });
  return { query, save, reset };
}
```

In `dashboard/src/test/server.ts`, replace:

```ts
  // Names of the people who ran or stopped something
```

with:

```ts
  // The Overview's layout: nothing saved, so the built-in four cards; tests about layouts override
  http.get("/api/v1/projects/:projectId/overview-layout", () =>
    HttpResponse.json({ effective: null, source: "builtin", personal: null, project: null })),
  // Names of the people who ran or stopped something
```

- [ ] **Step 5: Run them to verify they pass**

Run: `cd dashboard && npx vitest run src/api/http.test.ts src/api/overviewLayout.test.ts src/overview/useOverviewLayout.test.ts && npm run typecheck`
Expected: PASS; typecheck exits 0.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/api/overviewLayout.ts dashboard/src/api/overviewLayout.test.ts dashboard/src/api/http.ts dashboard/src/api/http.test.ts dashboard/src/overview/useOverviewLayout.ts dashboard/src/overview/useOverviewLayout.test.ts dashboard/src/test/server.ts
git commit -m "feat(dashboard): Overview layout API client and useOverviewLayout" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/api/overviewLayout.ts dashboard/src/api/overviewLayout.test.ts dashboard/src/api/http.ts dashboard/src/api/http.test.ts dashboard/src/overview/useOverviewLayout.ts dashboard/src/overview/useOverviewLayout.test.ts dashboard/src/test/server.ts
```

---

### Task 10: The widget frame: props, error boundary, latest-run queries

**Files:**
- Create: `dashboard/src/overview/widgets/types.ts`, `dashboard/src/overview/WidgetBoundary.tsx`, `dashboard/src/overview/format.ts`, `dashboard/src/overview/queries.ts`, `dashboard/src/overview/useLatestRun.ts`
- Test: `dashboard/src/overview/WidgetBoundary.test.tsx`

**Interfaces:**
- Consumes: `listRuns`, `getFailureGroups`, `Run` (`src/api/runs.ts`); `LIVE_REFRESH_MS` (`src/lib/live.ts`); `SettingName`, `WidgetSettings`, `WidgetSize`, `WidgetType` (Task 8).
- Produces:
  - `src/overview/widgets/types.ts`: `interface WidgetProps { projectId: number; settings: WidgetSettings; size: WidgetSize; heading: ReactNode; onOpenSettings?: () => void }` (Ruling 18); `interface WidgetDefinition { type: WidgetType; title: string; description: string; defaultSize: WidgetSize; settings: SettingName[]; defaults: WidgetSettings; cardTitle?: (settings: WidgetSettings) => string; Component: LazyExoticComponent<ComponentType<WidgetProps>>; link: (projectId: number, settings: WidgetSettings) => string }`;
  - `src/overview/WidgetBoundary.tsx`: default export `WidgetBoundary` (props `heading: ReactNode`, `title: string`, `children: ReactNode`);
  - `src/overview/format.ts`: `ago(iso: string): string` (moved unchanged from OverviewPage), `formatDay(iso: string): string`;
  - `src/overview/queries.ts`: `latestRunQuery(projectId: number)` (key `["runs", projectId, "latest"]`, `refetchInterval: LIVE_REFRESH_MS`), `failureGroupsQuery(run: Run | undefined)` (key `["failure-groups", run?.id]`), `newRunStaleKeys(projectId: number): (readonly unknown[])[]` (Ruling 27);
  - `src/overview/useLatestRun.ts`: `useLatestRun(projectId: number): { runs: UseQueryResult<Run[]>; latest: Run | undefined }` (invalidates `newRunStaleKeys` when the latest run id changes).

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill (Skill tool, `ui-ux-pro-max`) and read DESIGN.md "Error Banner" and "Cards / Containers".

- [ ] **Step 2: Write the failing test**

Create `dashboard/src/overview/WidgetBoundary.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WidgetBoundary from "./WidgetBoundary";

let failing = true;
function Fragile() {
  if (failing) throw new Error("render broke");
  return <p>Widget body</p>;
}

test("a widget that throws shows its own failure with Retry, and the rest keeps working", async () => {
  const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
  render(
    <>
      <section aria-label="fragile">
        <WidgetBoundary heading={<h2>Pass-rate trend</h2>} title="Pass-rate trend"><Fragile /></WidgetBoundary>
      </section>
      <p>Another widget</p>
    </>,
  );
  expect(screen.getByRole("heading", { name: "Pass-rate trend" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("This widget failed to load");
  expect(screen.getByText("Another widget")).toBeInTheDocument();
  failing = false;
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(screen.getByText("Widget body")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  quiet.mockRestore();
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd dashboard && npx vitest run src/overview/WidgetBoundary.test.tsx`
Expected: FAIL with `Failed to resolve import "./WidgetBoundary"`.

- [ ] **Step 4: Write the frame modules**

Create `dashboard/src/overview/widgets/types.ts`:

```ts
import type { ComponentType, LazyExoticComponent, ReactNode } from "react";
import type { SettingName, WidgetSettings, WidgetSize, WidgetType } from "../catalog";

export interface WidgetProps {
  projectId: number;
  /** The stored settings over the widget's defaults, each one valid. */
  settings: WidgetSettings;
  size: WidgetSize;
  /** The card's h2, a link to the full view (spec §2.7): the widget places it, first or in a head row with a badge. */
  heading: ReactNode;
  /** Opens this widget's settings (the empty-branch and no-name buttons); absent where that is not possible. */
  onOpenSettings?: () => void;
}

/** One widget type (plan Ruling 17): this metadata lives in `widgets/<type>.ts`, the component in its own chunk. */
export interface WidgetDefinition {
  type: WidgetType;
  /** The name in the Add widget list, and the card title unless `cardTitle` says otherwise. */
  title: string;
  description: string;
  defaultSize: WidgetSize;
  /** Exactly the catalogue's settings for this type (registry.test.ts checks it). */
  settings: SettingName[];
  defaults: WidgetSettings;
  cardTitle?: (settings: WidgetSettings) => string;
  /** Code-split: loads only when a layout places the widget. */
  Component: LazyExoticComponent<ComponentType<WidgetProps>>;
  /** The full view with the same filters (spec §2.7). */
  link: (projectId: number, settings: WidgetSettings) => string;
}
```

Create `dashboard/src/overview/WidgetBoundary.tsx`:

```tsx
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  heading: ReactNode;
  title: string;
  children: ReactNode;
}

interface State {
  failed: boolean;
}

/** One widget's render failure stays in its card (spec §2.8): "This widget failed to load · Retry", and the rest of
 *  the page keeps working. Retry renders the widget again. */
export default class WidgetBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Overview widget "${this.props.title}" failed to render`, error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <>
        {this.props.heading}
        <div className="error-banner" role="alert">
          <span>This widget failed to load</span>
          <button type="button" onClick={() => this.setState({ failed: false })}>Retry</button>
        </div>
      </>
    );
  }
}
```

Create `dashboard/src/overview/format.ts`:

```ts
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

/** "3 minutes ago", "yesterday" (moved unchanged from OverviewPage). */
export function ago(iso: string): string {
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  const steps: [number, Intl.RelativeTimeFormatUnit][] = [[60, "second"], [60, "minute"], [24, "hour"], [30, "day"], [12, "month"]];
  let value = seconds;
  for (const [size, unit] of steps) {
    if (Math.abs(value) < size) return relative.format(Math.round(value), unit);
    value /= size;
  }
  return relative.format(Math.round(value), "year");
}

/** A calendar day in the reader's locale, e.g. "11 Oct 2026". */
export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
```

Create `dashboard/src/overview/queries.ts`:

```ts
import { getFailureGroups, listRuns, type Run } from "../api/runs";
import { LIVE_REFRESH_MS } from "../lib/live";

/** The project's newest run, polled every 30 s while the tab is visible (ADR-021). The page, Latest run and Failing in
 *  latest run share this one query. */
export const latestRunQuery = (projectId: number) => ({
  queryKey: ["runs", projectId, "latest"] as const,
  queryFn: () => listRuns(projectId, { limit: 1, offset: 0 }),
  refetchInterval: LIVE_REFRESH_MS,
});

/** The latest run's failures grouped by cause; asked only when something failed. */
export const failureGroupsQuery = (run: Run | undefined) => ({
  queryKey: ["failure-groups", run?.id] as const,
  queryFn: () => getFailureGroups(run!.id),
  enabled: run !== undefined && run.failed + run.errored > 0,
});

/** What a new latest run makes stale (plan Ruling 27): figures that are not polled refetch once, not on every tick. */
export const newRunStaleKeys = (projectId: number): (readonly unknown[])[] => [
  ["trends", projectId], ["flaky", projectId], ["report", projectId], ["branches", projectId], ["latest-keys", projectId],
];
```

Create `dashboard/src/overview/useLatestRun.ts`:

```ts
import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { latestRunQuery, newRunStaleKeys } from "./queries";

/** The latest run, and a refresh of the non-polled figures when a new one arrives (spec §2.7). */
export function useLatestRun(projectId: number) {
  const queryClient = useQueryClient();
  const runs = useQuery(latestRunQuery(projectId));
  const latest = runs.data?.[0];
  const shown = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (shown.current !== undefined && latest?.id !== shown.current) {
      for (const queryKey of newRunStaleKeys(projectId)) void queryClient.invalidateQueries({ queryKey });
    }
    shown.current = latest?.id;
  }, [latest?.id, projectId, queryClient]);
  return { runs, latest };
}
```

- [ ] **Step 5: Run it to verify it passes, and typecheck**

Run: `cd dashboard && npx vitest run src/overview/WidgetBoundary.test.tsx && npm run typecheck && npm run lint`
Expected: PASS; typecheck and lint exit 0.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/overview/widgets/types.ts dashboard/src/overview/WidgetBoundary.tsx dashboard/src/overview/WidgetBoundary.test.tsx dashboard/src/overview/format.ts dashboard/src/overview/queries.ts dashboard/src/overview/useLatestRun.ts
git commit -m "feat(dashboard): Overview widget frame (props, error boundary, latest-run queries)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/widgets/types.ts dashboard/src/overview/WidgetBoundary.tsx dashboard/src/overview/WidgetBoundary.test.tsx dashboard/src/overview/format.ts dashboard/src/overview/queries.ts dashboard/src/overview/useLatestRun.ts
```

---

### Task 11: The registry with today's four cards, `WidgetCard`, and the Overview on widgets

**Files:**
- Create: `dashboard/src/overview/widgets/registry.ts`, `dashboard/src/overview/widgets/latestRun.ts`, `dashboard/src/overview/widgets/LatestRunWidget.tsx`, `dashboard/src/overview/widgets/failingNow.ts`, `dashboard/src/overview/widgets/FailingNowWidget.tsx`, `dashboard/src/overview/widgets/passRateWeek.ts`, `dashboard/src/overview/widgets/PassRateWeekWidget.tsx`, `dashboard/src/overview/widgets/flakyCount.ts`, `dashboard/src/overview/widgets/FlakyCountWidget.tsx`, `dashboard/src/overview/WidgetCard.tsx`, `dashboard/src/overview/WidgetGrid.tsx`, `dashboard/src/overview/testing.tsx`
- Test: `dashboard/src/overview/widgets/registry.test.ts`, `dashboard/src/overview/widgets/frameWidgets.test.tsx`, `dashboard/src/overview/UnknownWidget.test.tsx`, `dashboard/src/lib/healthQueries.test.ts`, and the existing `dashboard/src/pages/OverviewPage.test.tsx` (unchanged, must pass)
- Modify: `dashboard/src/pages/OverviewPage.tsx`, `dashboard/src/lib/healthQueries.ts`, `dashboard/src/index.css`

**Interfaces:**
- Consumes: Tasks 8–10 (`CATALOG`, `isValidSetting`, `StoredLayout`, `StoredWidget`, `WidgetSettings`, `ALL`, `BUILTIN_DEFAULT`, `useOverviewLayout`, `WidgetProps`, `WidgetDefinition`, `WidgetBoundary`, `latestRunQuery`, `failureGroupsQuery`, `useLatestRun`, `ago`); `flakyHealthQuery`, `passRateWeeksQuery`, `FLAKY_DEFAULTS` (`src/lib/healthQueries.ts`).
- Produces:
  - `src/overview/widgets/registry.ts`: `REGISTRY: Partial<Record<WidgetType, WidgetDefinition>>`; `definitionOf(type: string): WidgetDefinition | undefined` (warns once per unknown type); `knownWidgets(layout: StoredLayout): StoredWidget[]`; `addableDefinitions(): WidgetDefinition[]` (catalogue order); `withDefaults(def: WidgetDefinition, stored: WidgetSettings | undefined): WidgetSettings`; `widgetTitle(widget: StoredWidget): string`;
  - `src/overview/WidgetCard.tsx`: default export, props `{ projectId: number; widget: StoredWidget; tools?: ReactNode; onOpenSettings?: () => void }`; renders `<section class="card[ wide]" aria-labelledby="ov-<id>-title" data-widget-id="<id>" tabIndex={-1}>`;
  - `src/overview/WidgetGrid.tsx`: default export, props `{ projectId: number; layout: StoredLayout; onOpenSettings?: (widgetId: string) => void }`;
  - `src/lib/healthQueries.ts`: `passRateWeeksQuery(projectId: number, tz: string, branch?: string)` (the branch joins the key only when set), `flakyWindowQuery(projectId: number, windowDays: number)` (the Flaky view's key `["flaky", id, windowDays, 5, 0.3, "", false]`);
  - `src/overview/testing.tsx` (test helpers, imported only by tests): `RUN`, `FAILING_RUN`, `BUILTIN_STATE: OverviewLayoutState`, `personalState(...widgets: StoredWidget[]): OverviewLayoutState`, `projectState(layout: StoredLayout, extra?: Partial<OverviewLayoutState>): OverviewLayoutState`, `mockOverviewData(opts?: { role?: string; layout?: OverviewLayoutState; runs?: object[] }): void`, `renderOverview(): { qc: QueryClient }` (a data router with the Overview at `/projects/42/overview` and a link "Elsewhere").

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill and read DESIGN.md "Layout" (Overview grid), "Cards / Containers", "Accessibility Plumbing" and "KPI Tiles" ("Requests").

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/overview/testing.tsx`:

```tsx
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, RouterProvider, createMemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import type { OverviewLayoutState } from "../api/overviewLayout";
import OverviewPage from "../pages/OverviewPage";
import type { StoredLayout, StoredWidget } from "./catalog";

/** Test helpers for the Overview: imported only by *.test.tsx files. */

export const RUN = {
  id: 61, project_id: 42, ci_provider: "github_actions", ci_run_url: null, commit_sha: "abcdef1234567890",
  branch: "main", environment: "staging", agent_version: "0.1.0", commit_author: "Ada Lovelace",
  commit_message: "fix(cart): keep totals stable", pr_number: null, base_branch: null,
  started_at: "2026-10-04T10:00:00Z", finished_at: "2026-10-04T10:04:00Z", duration_ms: 240000,
  total: 24, passed: 24, failed: 0, skipped: 0, errored: 0, change_base_ref: null, changed_files: null,
  additions: null, deletions: null, changes_truncated: null, created_at: "2026-10-04T10:05:00Z",
};
export const FAILING_RUN = { ...RUN, passed: 21, failed: 3 };

export const BUILTIN_STATE: OverviewLayoutState = { effective: null, source: "builtin", personal: null, project: null };

export function personalState(...widgets: StoredWidget[]): OverviewLayoutState {
  return { effective: { schema: 1, widgets }, source: "personal", personal: { version: 1, updated_at: "2026-10-10T10:00:00Z" }, project: null };
}

export function projectState(layout: StoredLayout, extra: Partial<OverviewLayoutState> = {}): OverviewLayoutState {
  return {
    effective: layout, source: "project", personal: null,
    project: { version: 2, updated_by: 7, updated_at: "2026-10-09T10:00:00Z", layout },
    ...extra,
  };
}

/** The project, its runs, its layout and its members (user 7 is ada@example.com). */
export function mockOverviewData({ role = "member", layout = BUILTIN_STATE, runs = [RUN] }: {
  role?: string; layout?: OverviewLayoutState; runs?: object[];
} = {}) {
  server.use(
    http.get("/api/v1/projects/42", () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: role })),
    http.get("/api/v1/projects/42/runs", () => HttpResponse.json(runs)),
    http.get("/api/v1/projects/42/overview-layout", () => HttpResponse.json(layout)),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([
      { id: 1, organization_id: 1, user_id: 7, email: "ada@example.com", role: "owner", status: "active", created_at: "2026-10-01T00:00:00Z" },
    ])),
  );
}

/** The Overview in a data router (so the unsaved-changes guard is active), beside a link away from it. */
export function renderOverview() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/projects/:projectId/overview", element: <><OverviewPage /><Link to="/elsewhere">Elsewhere</Link></> },
      { path: "/elsewhere", element: <p>Elsewhere page</p> },
    ],
    { initialEntries: ["/projects/42/overview"] },
  );
  render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
  return { qc };
}
```

Create `dashboard/src/overview/widgets/registry.test.ts`:

```ts
import { CATALOG, type SettingName, type WidgetType, isValidSetting, layoutProblems } from "../catalog";
import { BUILTIN_DEFAULT } from "../templates";
import { REGISTRY } from "./registry";

// Catalogue types whose widgets arrive in Phase 3; each of Tasks 16-20 removes its own, Task 21 removes the set
const PENDING = new Set<string>([
  "pass_rate_trend", "failure_causes", "regressions", "recent_runs", "branch_health", "slowest_tests", "coverage",
  "case_tiles", "my_failures", "my_suites",
]);

test("the registry has a widget for every catalogue type, and no other", () => {
  const expected = Object.keys(CATALOG.types).filter((type) => !PENDING.has(type)).sort();
  expect(Object.keys(REGISTRY).sort()).toEqual(expected);
});

test("each widget declares exactly its catalogue settings, with allowed defaults", () => {
  for (const [type, def] of Object.entries(REGISTRY)) {
    expect(def.type).toBe(type);
    expect([...def.settings].sort()).toEqual([...CATALOG.types[type as WidgetType].settings].sort());
    for (const [name, value] of Object.entries(def.defaults)) {
      expect(def.settings).toContain(name);
      expect(isValidSetting(name as SettingName, value)).toBe(true);
    }
    expect(CATALOG.sizes).toContain(def.defaultSize);
  }
});

test("the built-in default uses registered widgets only and is a valid stored layout", () => {
  expect(layoutProblems(BUILTIN_DEFAULT)).toEqual([]);
  for (const widget of BUILTIN_DEFAULT.widgets) expect(Object.keys(REGISTRY)).toContain(widget.type);
});
```

Create `dashboard/src/overview/widgets/frameWidgets.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { FAILING_RUN, mockOverviewData, personalState, renderOverview } from "../testing";

const headingLink = async (name: string) => within(await screen.findByRole("heading", { name })).getByRole("link");

const cause = (i: number) => ({
  signature: `s${i}`, headline: `Cause ${i}`, count: 1, failed: 1, errored: 0,
  tests: [{ id: i, test_key: `k${i}`, suite: "s", class_name: "c", name: `test ${i}`, status: "failed" }],
  history: { window: 10, seen_in: 2, streak: 2, since_run_id: 60, since_started_at: "2026-10-03T10:00:00Z" },
});

test("each of the first four widgets links its title to the full view with the same filters", async () => {
  mockOverviewData({ layout: personalState(
    { id: "a", type: "latest_run", size: "wide" },
    { id: "b", type: "failing_now", size: "normal" },
    { id: "c", type: "pass_rate_week", size: "normal", settings: { branch: "main" } },
    { id: "d", type: "flaky_count", size: "normal", settings: { period: 30 } },
  ) });
  renderOverview();
  expect(await headingLink("Latest run")).toHaveAttribute("href", "/projects/42/runs");
  expect(await headingLink("Failing in latest run")).toHaveAttribute("href", "/projects/42/runs?status=failing");
  expect(await headingLink("Pass rate this week")).toHaveAttribute("href", "/projects/42/trends?bucket=week&branch=main");
  expect(await headingLink("Flaky tests, last 30 days")).toHaveAttribute("href", "/projects/42/flaky?window=30");
});

test("settings reach the requests: a branch for the weekly pass rate, a window for flaky tests", async () => {
  const trends: URLSearchParams[] = [];
  const flaky: URLSearchParams[] = [];
  mockOverviewData({ layout: personalState(
    { id: "c", type: "pass_rate_week", size: "normal", settings: { branch: "main" } },
    { id: "d", type: "flaky_count", size: "normal", settings: { period: 30 } },
  ) });
  server.use(
    http.get("/api/v1/projects/42/analytics/trends", ({ request }) => {
      trends.push(new URL(request.url).searchParams);
      return HttpResponse.json({ tz: "UTC", bucket: "week", days: [] });
    }),
    http.get("/api/v1/projects/42/analytics/flaky", ({ request }) => {
      flaky.push(new URL(request.url).searchParams);
      return HttpResponse.json([]);
    }),
  );
  renderOverview();
  await waitFor(() => expect(trends.length).toBeGreaterThan(0));
  await waitFor(() => expect(flaky.length).toBeGreaterThan(0));
  expect(trends[0].get("branch")).toBe("main");
  expect(trends[0].get("bucket")).toBe("week");
  expect(flaky[0].get("window_days")).toBe("30");
  expect(flaky[0].get("include_muted")).toBeNull();
});

test("Failing in latest run lists up to ten causes when its rows are 10", async () => {
  mockOverviewData({ runs: [FAILING_RUN], layout: personalState({ id: "b", type: "failing_now", size: "normal", settings: { rows: 10 } }) });
  server.use(http.get("/api/v1/runs/61/failure-groups", () =>
    HttpResponse.json({ total: 7, groups: Array.from({ length: 7 }, (_, i) => cause(i)) })));
  renderOverview();
  expect(await screen.findByText("Cause 6")).toBeInTheDocument();
});
```

Create `dashboard/src/overview/UnknownWidget.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { mockOverviewData, personalState, renderOverview } from "./testing";

test("a stored widget of an unknown type is skipped and logged once", async () => {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  mockOverviewData({ layout: personalState(
    { id: "x1", type: "from_a_newer_dashboard", size: "wide" },
    { id: "x2", type: "from_a_newer_dashboard", size: "normal" },
    { id: "w1", type: "latest_run", size: "wide" },
  ) });
  renderOverview();
  expect(await screen.findByRole("region", { name: "Latest run" })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
  expect(warn.mock.calls.filter(([message]) => String(message).includes("from_a_newer_dashboard"))).toHaveLength(1);
  warn.mockRestore();
});
```

Create `dashboard/src/lib/healthQueries.test.ts`:

```ts
import { flakyHealthQuery, flakyWindowQuery, passRateWeeksQuery } from "./healthQueries";

test("the weekly pass rate adds a branch to its key only when one is chosen, so the Cases tile shares the default", () => {
  expect(passRateWeeksQuery(42, "UTC").queryKey).toEqual(["trends", 42, "overview-weeks", "UTC"]);
  expect(passRateWeeksQuery(42, "UTC", "main").queryKey).toEqual(["trends", 42, "overview-weeks", "UTC", "main"]);
});

test("another flaky window uses the Flaky view's own key", () => {
  expect(flakyHealthQuery(42).queryKey).toEqual(["flaky", 42, "health"]);
  expect(flakyWindowQuery(42, 30).queryKey).toEqual(["flaky", 42, 30, 5, 0.3, "", false]);
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/overview/widgets/registry.test.ts src/overview/widgets/frameWidgets.test.tsx src/overview/UnknownWidget.test.tsx src/lib/healthQueries.test.ts`
Expected: FAIL: `Failed to resolve import "./registry"`; in healthQueries.test.ts `flakyWindowQuery is not a function`; the page tests find no heading "Failing in latest run" (today's card says "Failing in this run").

- [ ] **Step 4: Extend the shared health queries**

In `dashboard/src/lib/healthQueries.ts`, replace:

```ts
/** This week's and last week's pass rate (two weekly buckets). Overview and the Cases tile share it. */
export const passRateWeeksQuery = (projectId: number, tz: string) => ({
  queryKey: ["trends", projectId, "overview-weeks", tz] as const,
  queryFn: () => getTrends(projectId, { days: 14, tz, bucket: "week" }),
  staleTime: HEALTH_STALE_MS,
});
```

with:

```ts
/** The Flaky view's own query at its default thresholds for another window, quarantined tests left out (its "Show
 *  quarantined" off): the Overview's Flaky tests widget set to 7 or 30 days shares the view's answer. */
export const flakyWindowQuery = (projectId: number, windowDays: number) => ({
  queryKey: ["flaky", projectId, windowDays, FLAKY_DEFAULTS.minRuns, FLAKY_DEFAULTS.minFlipRate, "", false] as const,
  queryFn: () => getFlaky(projectId, { windowDays, minRuns: FLAKY_DEFAULTS.minRuns, minFlipRate: FLAKY_DEFAULTS.minFlipRate }),
  staleTime: HEALTH_STALE_MS,
});

/** This week's and last week's pass rate (two weekly buckets). Overview and the Cases tile share it; a branch (the
 *  Overview widget's setting) joins the key only when one is chosen. */
export const passRateWeeksQuery = (projectId: number, tz: string, branch?: string) => ({
  queryKey: (branch
    ? ["trends", projectId, "overview-weeks", tz, branch]
    : ["trends", projectId, "overview-weeks", tz]) as readonly unknown[],
  queryFn: () => getTrends(projectId, { days: 14, tz, bucket: "week", branch }),
  staleTime: HEALTH_STALE_MS,
});
```

- [ ] **Step 5: Write the four widgets (today's cards, logic unchanged)**

Create `dashboard/src/overview/widgets/LatestRunWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Clock, GitBranch, GitCommitHorizontal, Server } from "lucide-react";
import { formatDuration } from "../../api/analytics";
import RunStatusBadge from "../../components/RunStatusBadge";
import StatusDot from "../../components/StatusDot";
import { ago } from "../format";
import { failureGroupsQuery, latestRunQuery } from "../queries";
import type { WidgetProps } from "./types";

/** The latest run's verdict in words, what it ran on and its counts (today's card, unchanged). */
export default function LatestRunWidget({ projectId, heading }: WidgetProps) {
  const runs = useQuery(latestRunQuery(projectId));
  const latest = runs.data?.[0];
  const causes = useQuery(failureGroupsQuery(latest));
  // The page shows the "No runs yet" panel instead of the widgets, so this lasts at most one poll
  if (!latest) return <>{heading}</>;
  const broken = latest.failed + latest.errored;
  // Failures of quarantined tests are shown but do not decide the verdict
  const held = causes.data?.quarantined ?? 0;
  const blocking = causes.data?.blocking ?? broken;
  return (
    <>
      <div className="card-head">
        {heading}
        <RunStatusBadge verdict={blocking > 0 ? "failed" : "passed"} note={blocking === 0 && held > 0 ? `${held} quarantined` : undefined} />
      </div>
      {latest.commit_message && <p>{latest.commit_message}</p>}
      <div className="meta">
        {latest.branch && <span><GitBranch size={14} aria-hidden="true" /> {latest.branch}</span>}
        {latest.commit_sha && <span><GitCommitHorizontal size={14} aria-hidden="true" /> <code>{latest.commit_sha.slice(0, 7)}</code></span>}
        {latest.environment && <span><Server size={14} aria-hidden="true" /> {latest.environment}</span>}
        <span><Clock size={14} aria-hidden="true" /> {ago(latest.started_at)} · {formatDuration(latest.duration_ms)}</span>
      </div>
      <div className="meta">
        <span><StatusDot status="passed" label={`${latest.passed} passed`} /></span>
        <span><StatusDot status="failed" label={`${latest.failed} failed`} /></span>
        <span><StatusDot status="errored" label={`${latest.errored} errored`} /></span>
        <span><StatusDot status="skipped" label={`${latest.skipped} skipped`} /></span>
      </div>
      <div className="card-foot">
        <Link className="link-arrow" to={`/projects/${projectId}/runs/${latest.id}`}>Open run #{latest.id} <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
```

Create `dashboard/src/overview/widgets/latestRun.ts`:

```ts
import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const latestRun: WidgetDefinition = {
  type: "latest_run",
  title: "Latest run",
  description: "The newest run's verdict, commit, branch and counts.",
  defaultSize: "wide",
  settings: [],
  defaults: {},
  Component: lazy(() => import("./LatestRunWidget")),
  link: (projectId) => `/projects/${projectId}/runs`,
};
```

Create `dashboard/src/overview/widgets/FailingNowWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import ErrorBanner from "../../components/ErrorBanner";
import { isNewCause } from "../../components/FailureGroups";
import { failureGroupsQuery, latestRunQuery } from "../queries";
import type { WidgetProps } from "./types";

/** The latest run's failures grouped by cause, new causes marked (today's card; `rows` causes, 5 by default). */
export default function FailingNowWidget({ projectId, settings, heading }: WidgetProps) {
  const rows = settings.rows ?? 5;
  const runs = useQuery(latestRunQuery(projectId));
  const latest = runs.data?.[0];
  const causes = useQuery(failureGroupsQuery(latest));
  if (!latest) return <>{heading}</>;
  const broken = latest.failed + latest.errored;
  const groups = causes.data?.groups ?? [];
  return (
    <>
      {heading}
      {broken === 0 && <p className="muted">Nothing failed in the latest run.</p>}
      {broken > 0 && causes.isPending && <p className="muted">Loading failures…</p>}
      {causes.error != null && <ErrorBanner error={causes.error} onRetry={() => causes.refetch()} />}
      {groups.length > 0 && (
        <>
          <p className="muted">
            {causes.data!.total} {causes.data!.total === 1 ? "test" : "tests"} · {groups.length}{" "}
            {groups.length === 1 ? "cause" : "causes"}
          </p>
          <ul className="fail-list">
            {groups.slice(0, rows).map((g) => {
              const first = g.tests[0];
              return (
                <li key={g.signature}>
                  <span className="cause-title">
                    {isNewCause(g.history) && <span className="badge badge-new">New</span>}
                    {g.headline ? <span className="msg">{g.headline}</span> : <span className="where">No error message</span>}
                  </span>
                  <span>
                    <Link to={`/projects/${projectId}/tests/${encodeURIComponent(first.test_key)}`}>{first.name}</Link>
                    {g.count > 1 && <span className="where"> and {g.count - 1} more</span>}
                    {(g.quarantined ?? 0) > 0 && <span className="where"> · {g.quarantined === g.count ? "in quarantine" : `${g.quarantined} in quarantine`}</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {broken > 0 && (groups.length > rows || groups.some((g) => g.count > 1)) && (
        <div className="card-foot">
          <Link className="link-arrow" to={`/projects/${projectId}/runs/${latest.id}`}>All {broken} failures by cause <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      )}
    </>
  );
}
```

Create `dashboard/src/overview/widgets/failingNow.ts`:

```ts
import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const failingNow: WidgetDefinition = {
  type: "failing_now",
  title: "Failing in latest run",
  description: "The latest run's failures grouped by cause, new causes marked.",
  defaultSize: "normal",
  settings: ["rows"],
  defaults: { rows: 5 },
  Component: lazy(() => import("./FailingNowWidget")),
  // The run's own page is the card foot's link; the title opens every run with failures (plan Ruling 19)
  link: (projectId) => `/projects/${projectId}/runs?status=failing`,
};
```

Create `dashboard/src/overview/widgets/PassRateWeekWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { formatPassRate } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import { passRateWeeksQuery } from "../../lib/healthQueries";
import { ALL } from "../catalog";
import type { WidgetProps } from "./types";

/** This week's pass rate against last week's, as the API computed them (today's card; optionally one branch). */
export default function PassRateWeekWidget({ projectId, settings, heading }: WidgetProps) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const branch = settings.branch ?? ALL;
  const weeks = useQuery(passRateWeeksQuery(projectId, tz, branch === ALL ? undefined : branch));
  const buckets = weeks.data?.days ?? [];
  const thisWeek = buckets[buckets.length - 1];
  const lastWeek = buckets.length > 1 ? buckets[buckets.length - 2] : undefined;
  return (
    <>
      {heading}
      {weeks.isPending && <SkeletonStatus label="Loading pass rate…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
      {weeks.error != null && <ErrorBanner error={weeks.error} onRetry={() => weeks.refetch()} />}
      {thisWeek && (
        <>
          <div className="stat-big">{formatPassRate(thisWeek.pass_rate)}</div>
          <p className="muted">
            {thisWeek.runs} {thisWeek.runs === 1 ? "run" : "runs"} this week
            {" · "}
            {lastWeek && lastWeek.pass_rate !== null
              ? `${formatPassRate(lastWeek.pass_rate)} the week before`
              : "no runs the week before"}
          </p>
        </>
      )}
      <div className="card-foot">
        <Link className="link-arrow" to={`/projects/${projectId}/trends`}>Trends <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
```

Create `dashboard/src/overview/widgets/passRateWeek.ts`:

```ts
import { lazy } from "react";
import { ALL } from "../catalog";
import type { WidgetDefinition } from "./types";

export const passRateWeek: WidgetDefinition = {
  type: "pass_rate_week",
  title: "Pass rate this week",
  description: "This week's pass rate against last week's.",
  defaultSize: "normal",
  settings: ["branch"],
  defaults: { branch: ALL },
  Component: lazy(() => import("./PassRateWeekWidget")),
  link: (projectId, settings) => {
    const params = new URLSearchParams({ bucket: "week" });
    if (settings.branch && settings.branch !== ALL) params.set("branch", settings.branch);
    return `/projects/${projectId}/trends?${params}`;
  },
};
```

Create `dashboard/src/overview/widgets/FlakyCountWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import type { FlakyRow } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import { FLAKY_DEFAULTS, flakyHealthQuery, flakyWindowQuery } from "../../lib/healthQueries";
import type { WidgetProps } from "./types";

/** Confirmed and suspected flaky tests over the window (today's card at 14 days). */
export default function FlakyCountWidget({ projectId, settings, heading }: WidgetProps) {
  const period = settings.period ?? FLAKY_DEFAULTS.windowDays;
  // 14 days is the Cases tile's query (quarantined tests included, counted out here); other windows are the Flaky view's
  const source = period === FLAKY_DEFAULTS.windowDays ? flakyHealthQuery(projectId) : flakyWindowQuery(projectId, period);
  const flaky = useQuery<FlakyRow[]>({ queryKey: source.queryKey, queryFn: source.queryFn, staleTime: source.staleTime });
  const unmuted = flaky.data?.filter((r) => !r.muted) ?? [];
  const confirmed = unmuted.filter((r) => r.reason === "same_commit").length;
  const suspected = unmuted.filter((r) => r.reason === "flips").length;
  return (
    <>
      {heading}
      {flaky.isPending && <SkeletonStatus label="Loading flaky tests…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
      {flaky.error != null && <ErrorBanner error={flaky.error} onRetry={() => flaky.refetch()} />}
      {flaky.data && (
        <>
          <div className="stat-big">{confirmed + suspected}</div>
          <p className="muted">{confirmed} confirmed · {suspected} suspected</p>
        </>
      )}
      <div className="card-foot">
        <Link className="link-arrow" to={`/projects/${projectId}/flaky`}>Flaky tests <ArrowRight size={14} aria-hidden="true" /></Link>
      </div>
    </>
  );
}
```

Create `dashboard/src/overview/widgets/flakyCount.ts`:

```ts
import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const flakyCount: WidgetDefinition = {
  type: "flaky_count",
  title: "Flaky tests",
  description: "Confirmed and suspected flaky tests over 7, 14 or 30 days.",
  defaultSize: "normal",
  settings: ["period"],
  defaults: { period: 14 },
  cardTitle: (settings) => `Flaky tests, last ${settings.period ?? 14} days`,
  Component: lazy(() => import("./FlakyCountWidget")),
  link: (projectId, settings) =>
    (settings.period ?? 14) === 14 ? `/projects/${projectId}/flaky` : `/projects/${projectId}/flaky?window=${settings.period}`,
};
```

- [ ] **Step 6: Write the registry, the card and the grid**

Create `dashboard/src/overview/widgets/registry.ts`:

```ts
import { CATALOG, type StoredLayout, type StoredWidget, type WidgetSettings, type WidgetType, isValidSetting } from "../catalog";
import { failingNow } from "./failingNow";
import { flakyCount } from "./flakyCount";
import { latestRun } from "./latestRun";
import { passRateWeek } from "./passRateWeek";
import type { WidgetDefinition } from "./types";

/** Widget type → definition. registry.test.ts fails when this and overview_widgets.json disagree. */
export const REGISTRY: Partial<Record<WidgetType, WidgetDefinition>> = {
  latest_run: latestRun,
  failing_now: failingNow,
  pass_rate_week: passRateWeek,
  flaky_count: flakyCount,
};

const warned = new Set<string>();

/** The definition, or undefined for a type this dashboard does not know (a layout saved by a newer version): such
 *  widgets are skipped, logged once per type (spec §4). */
export function definitionOf(type: string): WidgetDefinition | undefined {
  const def = Object.hasOwn(REGISTRY, type) ? REGISTRY[type as WidgetType] : undefined;
  if (def === undefined && !warned.has(type)) {
    warned.add(type);
    console.warn(`Overview: skipping widget type "${type}", which this dashboard does not know`);
  }
  return def;
}

export function knownWidgets(layout: StoredLayout): StoredWidget[] {
  return layout.widgets.filter((widget) => definitionOf(widget.type) !== undefined);
}

/** What Add widget offers, in catalogue order. */
export function addableDefinitions(): WidgetDefinition[] {
  return (Object.keys(CATALOG.types) as WidgetType[]).flatMap((type) => REGISTRY[type] ?? []);
}

/** The widget's defaults overlaid with each stored setting that is still valid. */
export function withDefaults(def: WidgetDefinition, stored: WidgetSettings | undefined): WidgetSettings {
  const out: Record<string, unknown> = { ...def.defaults };
  for (const name of def.settings) {
    const value = stored?.[name];
    if (value !== undefined && isValidSetting(name, value)) out[name] = value;
  }
  return out as WidgetSettings;
}

export function widgetTitle(widget: StoredWidget): string {
  const def = definitionOf(widget.type);
  if (def === undefined) return widget.type;
  return def.cardTitle ? def.cardTitle(withDefaults(def, widget.settings)) : def.title;
}
```

Create `dashboard/src/overview/WidgetCard.tsx`:

```tsx
import { Suspense, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { SkeletonStatus } from "../components/Skeleton";
import type { StoredWidget } from "./catalog";
import WidgetBoundary from "./WidgetBoundary";
import { definitionOf, withDefaults } from "./widgets/registry";

interface Props {
  projectId: number;
  widget: StoredWidget;
  /** Edit mode: the widget's toolbar and, while open, its settings form, above the widget. */
  tools?: ReactNode;
  onOpenSettings?: () => void;
}

/** One widget in its card (spec §4): the h2 is the title link to the full view, and the widget renders inside its own
 *  error boundary and Suspense (its code loads on demand). Nothing for a type this dashboard does not know. */
export default function WidgetCard({ projectId, widget, tools, onOpenSettings }: Props) {
  const def = definitionOf(widget.type);
  if (def === undefined) return null;
  const settings = withDefaults(def, widget.settings);
  const title = def.cardTitle ? def.cardTitle(settings) : def.title;
  const titleId = `ov-${widget.id}-title`;
  const heading = <h2 id={titleId}><Link to={def.link(projectId, settings)}>{title}</Link></h2>;
  const Body = def.Component;
  const loading = (
    <>
      {heading}
      <SkeletonStatus label={`Loading ${title}…`}><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>
    </>
  );
  return (
    <section className={widget.size === "wide" ? "card wide" : "card"} aria-labelledby={titleId} data-widget-id={widget.id} tabIndex={-1}>
      {tools}
      <WidgetBoundary heading={heading} title={title}>
        <Suspense fallback={loading}>
          <Body projectId={projectId} settings={settings} size={widget.size} heading={heading} onOpenSettings={onOpenSettings} />
        </Suspense>
      </WidgetBoundary>
    </section>
  );
}
```

Create `dashboard/src/overview/WidgetGrid.tsx`:

```tsx
import type { StoredLayout } from "./catalog";
import WidgetCard from "./WidgetCard";
import { knownWidgets } from "./widgets/registry";

interface Props {
  projectId: number;
  layout: StoredLayout;
  /** Opens edit mode on this widget's settings (the empty-branch and no-name buttons). */
  onOpenSettings?: (widgetId: string) => void;
}

/** The live Overview: the layout's widgets in order on the `auto-fit, minmax(260px, 1fr)` grid. */
export default function WidgetGrid({ projectId, layout, onOpenSettings }: Props) {
  const widgets = knownWidgets(layout);
  if (widgets.length === 0) return <p className="muted">This Overview has no widgets. Use Customise to add some.</p>;
  return (
    <div className="overview-grid">
      {widgets.map((widget) => (
        <WidgetCard
          key={widget.id}
          projectId={projectId}
          widget={widget}
          onOpenSettings={onOpenSettings ? () => onOpenSettings(widget.id) : undefined}
        />
      ))}
    </div>
  );
}
```

In `dashboard/src/index.css`, replace:

```css
.overview-grid > .card.wide { grid-column: 1 / -1; }
```

with:

```css
.overview-grid > .card.wide { grid-column: 1 / -1; }
/* A card takes focus after a move or a removal; regions take focus without a ring (DESIGN.md Accessibility Plumbing) */
.overview-grid > .card:focus { outline: none; }
/* Each widget's h2 is its title link to the full view */
.overview-grid h2 a { color: inherit; text-decoration: none; }
.overview-grid h2 a:hover { text-decoration: underline; }
```

- [ ] **Step 7: Put the Overview on widgets**

Replace `dashboard/src/pages/OverviewPage.tsx` with:

```tsx
import { Link, useParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import ErrorBanner from "../components/ErrorBanner";
import PageHeader from "../components/PageHeader";
import { SkeletonCard, SkeletonStatus } from "../components/Skeleton";
import { BUILTIN_DEFAULT } from "../overview/templates";
import { useLatestRun } from "../overview/useLatestRun";
import { useOverviewLayout } from "../overview/useOverviewLayout";
import WidgetGrid from "../overview/WidgetGrid";

/** "What is broken now" in one screen, as widgets (spec 2026-10-11): the personal layout, else the project default,
 *  else the built-in four cards. Each widget loads, fails and retries on its own. */
export default function OverviewPage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const { runs, latest } = useLatestRun(id);
  const { query: layout } = useOverviewLayout(id);

  function body() {
    if (runs.error != null) return <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} />;
    if (runs.isPending || layout.isPending) {
      return (
        <SkeletonStatus label="Loading overview…" className="overview-grid">
          <SkeletonCard className="wide" height={96} />
          <SkeletonCard height={120} />
          <SkeletonCard height={120} />
          <SkeletonCard height={120} />
        </SkeletonStatus>
      );
    }
    if (!latest) return <NoRunsYet projectId={id} />;
    return (
      <>
        {layout.error != null && <LayoutUnavailable onRetry={() => layout.refetch()} />}
        <WidgetGrid projectId={id} layout={layout.data?.effective ?? BUILTIN_DEFAULT} />
      </>
    );
  }

  return (
    <>
      <PageHeader title="Overview" />
      {body()}
    </>
  );
}

/** Shown instead of the widgets until the first upload (spec §2.7). */
function NoRunsYet({ projectId }: { projectId: number }) {
  return (
    <div className="card">
      <h2>No runs yet</h2>
      <p className="muted">
        Results appear here after the first upload from CI. Create an API key, paste the CI
        snippet into your pipeline, and the next build reports its tests.
      </p>
      <Link className="link-arrow" to={`/projects/${projectId}/settings`}>Set up an API key and CI <ArrowRight size={14} aria-hidden="true" /></Link>
    </div>
  );
}

/** The layout could not be read: the built-in default is shown under this banner (plan Ruling 30). */
function LayoutUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="error-banner" role="alert">
      <span>Your Overview layout could not be loaded, so the default is shown.</span>
      <button type="button" onClick={onRetry}>Retry</button>
    </div>
  );
}
```

- [ ] **Step 8: Run the new and the existing Overview tests**

Run: `cd dashboard && npx vitest run src/overview src/lib/healthQueries.test.ts src/pages/OverviewPage.test.tsx src/components/CasesKpis.test.tsx`
Expected: PASS. The seven existing OverviewPage tests pass unchanged against the built-in default; the Cases KPI tiles still share the weekly pass-rate and flaky queries.

- [ ] **Step 9: Lint, typecheck, build**

Run: `cd dashboard && npm run lint && npm run typecheck && npm run build`
Expected: exit 0; the build output lists separate chunks `LatestRunWidget-*.js`, `FailingNowWidget-*.js`, `PassRateWeekWidget-*.js`, `FlakyCountWidget-*.js` (code-split).

- [ ] **Step 10: Commit**

```bash
git add dashboard/src/overview/widgets/registry.ts dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/frameWidgets.test.tsx dashboard/src/overview/widgets/latestRun.ts dashboard/src/overview/widgets/LatestRunWidget.tsx dashboard/src/overview/widgets/failingNow.ts dashboard/src/overview/widgets/FailingNowWidget.tsx dashboard/src/overview/widgets/passRateWeek.ts dashboard/src/overview/widgets/PassRateWeekWidget.tsx dashboard/src/overview/widgets/flakyCount.ts dashboard/src/overview/widgets/FlakyCountWidget.tsx dashboard/src/overview/WidgetCard.tsx dashboard/src/overview/WidgetGrid.tsx dashboard/src/overview/testing.tsx dashboard/src/overview/UnknownWidget.test.tsx dashboard/src/lib/healthQueries.ts dashboard/src/lib/healthQueries.test.ts dashboard/src/pages/OverviewPage.tsx dashboard/src/index.css
git commit -m "feat(dashboard): Overview on a widget registry with today's four cards" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/widgets/registry.ts dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/frameWidgets.test.tsx dashboard/src/overview/widgets/latestRun.ts dashboard/src/overview/widgets/LatestRunWidget.tsx dashboard/src/overview/widgets/failingNow.ts dashboard/src/overview/widgets/FailingNowWidget.tsx dashboard/src/overview/widgets/passRateWeek.ts dashboard/src/overview/widgets/PassRateWeekWidget.tsx dashboard/src/overview/widgets/flakyCount.ts dashboard/src/overview/widgets/FlakyCountWidget.tsx dashboard/src/overview/WidgetCard.tsx dashboard/src/overview/WidgetGrid.tsx dashboard/src/overview/testing.tsx dashboard/src/overview/UnknownWidget.test.tsx dashboard/src/lib/healthQueries.ts dashboard/src/lib/healthQueries.test.ts dashboard/src/pages/OverviewPage.tsx dashboard/src/index.css
```

---

### Task 12: The draft reducer

**Files:**
- Create: `dashboard/src/overview/draft.ts`
- Test: `dashboard/src/overview/draft.test.ts`

**Interfaces:**
- Consumes: `MAX_WIDGETS`, `StoredLayout`, `StoredWidget`, `WidgetSettings`, `WidgetSize` (Task 8).
- Produces: `interface Draft { layout: StoredLayout; reset: boolean }`; `type DraftAction = { kind: "move"; id: string; by: -1 | 1 } | { kind: "size"; id: string } | { kind: "remove"; id: string } | { kind: "add"; id: string; type: string; size: WidgetSize; settings: WidgetSettings } | { kind: "settings"; id: string; settings: WidgetSettings } | { kind: "replace"; layout: StoredLayout } | { kind: "reset"; layout: StoredLayout }`; `nextWidgetId(widgets: StoredWidget[]): string`; `draftReducer(draft: Draft, action: DraftAction): Draft`; `isDirty(draft: Draft, start: StoredLayout): boolean`. `reset: true` means Save deletes the stored layout (Ruling 20).

- [ ] **Step 1: Write the failing test**

Create `dashboard/src/overview/draft.test.ts`:

```ts
import type { StoredLayout } from "./catalog";
import { type Draft, draftReducer, isDirty, nextWidgetId } from "./draft";

const layout = (ids: string[]): StoredLayout => ({
  schema: 1, widgets: ids.map((id) => ({ id, type: "latest_run", size: "normal", settings: {} })),
});
const draft = (ids: string[]): Draft => ({ layout: layout(ids), reset: false });
const ids = (d: Draft) => d.layout.widgets.map((w) => w.id);

test("move swaps with the neighbour and stops at the ends", () => {
  expect(ids(draftReducer(draft(["a", "b", "c"]), { kind: "move", id: "c", by: -1 }))).toEqual(["a", "c", "b"]);
  expect(ids(draftReducer(draft(["a", "b", "c"]), { kind: "move", id: "a", by: 1 }))).toEqual(["b", "a", "c"]);
  const start = draft(["a", "b"]);
  expect(draftReducer(start, { kind: "move", id: "a", by: -1 })).toBe(start);
  expect(draftReducer(start, { kind: "move", id: "b", by: 1 })).toBe(start);
});

test("size toggles between normal and wide", () => {
  const wide = draftReducer(draft(["a"]), { kind: "size", id: "a" });
  expect(wide.layout.widgets[0].size).toBe("wide");
  expect(draftReducer(wide, { kind: "size", id: "a" }).layout.widgets[0].size).toBe("normal");
});

test("remove drops the widget", () => {
  expect(ids(draftReducer(draft(["a", "b"]), { kind: "remove", id: "a" }))).toEqual(["b"]);
});

test("add appends with the given id, never past 24 widgets nor over a taken id", () => {
  const added = draftReducer(draft(["a"]), { kind: "add", id: "w2", type: "coverage", size: "normal", settings: { period: 30 } });
  expect(added.layout.widgets[1]).toEqual({ id: "w2", type: "coverage", size: "normal", settings: { period: 30 } });
  const full = draft(Array.from({ length: 24 }, (_, i) => `w${i + 1}`));
  expect(draftReducer(full, { kind: "add", id: "w25", type: "coverage", size: "normal", settings: {} })).toBe(full);
  const one = draft(["a"]);
  expect(draftReducer(one, { kind: "add", id: "a", type: "coverage", size: "normal", settings: {} })).toBe(one);
});

test("settings replace that widget's settings only", () => {
  const next = draftReducer(draft(["a", "b"]), { kind: "settings", id: "b", settings: { rows: 10 } });
  expect(next.layout.widgets.map((w) => w.settings)).toEqual([{}, { rows: 10 }]);
});

test("replace (a template) takes a copy, so editing the draft never changes the template", () => {
  const template = layout(["t1", "t2"]);
  const next = draftReducer(draft(["a"]), { kind: "replace", layout: template });
  expect(ids(next)).toEqual(["t1", "t2"]);
  const edited = draftReducer(next, { kind: "settings", id: "t1", settings: { rows: 5 } });
  expect(edited.layout.widgets[0].settings).toEqual({ rows: 5 });
  expect(template.widgets[0].settings).toEqual({});
});

test("reset marks the draft so Save deletes; any later edit clears the mark", () => {
  const reset = draftReducer(draft(["a"]), { kind: "reset", layout: layout(["d1"]) });
  expect(reset.reset).toBe(true);
  expect(ids(reset)).toEqual(["d1"]);
  expect(draftReducer(reset, { kind: "size", id: "d1" }).reset).toBe(false);
});

test("nextWidgetId skips ids in use", () => {
  expect(nextWidgetId(layout(["w1", "w3"]).widgets)).toBe("w4");
  expect(nextWidgetId(layout(["a", "b"]).widgets)).toBe("w3");
  expect(nextWidgetId([])).toBe("w1");
});

test("isDirty compares with where editing started", () => {
  const start = layout(["a", "b"]);
  const same: Draft = { layout: start, reset: false };
  expect(isDirty(same, start)).toBe(false);
  const moved = draftReducer(same, { kind: "move", id: "b", by: -1 });
  expect(isDirty(moved, start)).toBe(true);
  expect(isDirty(draftReducer(moved, { kind: "move", id: "b", by: 1 }), start)).toBe(false);
  expect(isDirty({ layout: start, reset: true }, start)).toBe(true);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd dashboard && npx vitest run src/overview/draft.test.ts`
Expected: FAIL with `Failed to resolve import "./draft"`.

- [ ] **Step 3: Write the reducer**

Create `dashboard/src/overview/draft.ts`:

```ts
import { MAX_WIDGETS, type StoredLayout, type StoredWidget, type WidgetSettings, type WidgetSize } from "./catalog";

/** The editor's working copy (spec §2.2: changes apply to a draft; the live page changes only on Save). */
export interface Draft {
  layout: StoredLayout;
  /** Reset was pressed and nothing changed since: Save deletes the stored layout instead of saving a copy (Ruling 20). */
  reset: boolean;
}

export type DraftAction =
  | { kind: "move"; id: string; by: -1 | 1 }
  | { kind: "size"; id: string }
  | { kind: "remove"; id: string }
  | { kind: "add"; id: string; type: string; size: WidgetSize; settings: WidgetSettings }
  | { kind: "settings"; id: string; settings: WidgetSettings }
  | { kind: "replace"; layout: StoredLayout }
  | { kind: "reset"; layout: StoredLayout };

/** "w<n>", the first n from the widget count up that no widget uses. */
export function nextWidgetId(widgets: StoredWidget[]): string {
  const taken = new Set(widgets.map((w) => w.id));
  let n = widgets.length + 1;
  while (taken.has(`w${n}`)) n += 1;
  return `w${n}`;
}

const copy = (layout: StoredLayout): StoredLayout => ({
  schema: layout.schema,
  widgets: layout.widgets.map((w) => ({ ...w, settings: { ...w.settings } })),
});

function edited(draft: Draft, widgets: StoredWidget[]): Draft {
  return { layout: { ...draft.layout, widgets }, reset: false };
}

export function draftReducer(draft: Draft, action: DraftAction): Draft {
  const widgets = draft.layout.widgets;
  switch (action.kind) {
    case "move": {
      const from = widgets.findIndex((w) => w.id === action.id);
      const to = from + action.by;
      if (from < 0 || to < 0 || to >= widgets.length) return draft;
      const next = [...widgets];
      [next[from], next[to]] = [next[to], next[from]];
      return edited(draft, next);
    }
    case "size":
      return edited(draft, widgets.map((w): StoredWidget => (w.id === action.id ? { ...w, size: w.size === "wide" ? "normal" : "wide" } : w)));
    case "remove":
      return edited(draft, widgets.filter((w) => w.id !== action.id));
    case "add":
      if (widgets.length >= MAX_WIDGETS || widgets.some((w) => w.id === action.id)) return draft;
      return edited(draft, [...widgets, { id: action.id, type: action.type, size: action.size, settings: { ...action.settings } }]);
    case "settings":
      return edited(draft, widgets.map((w): StoredWidget => (w.id === action.id ? { ...w, settings: { ...action.settings } } : w)));
    case "replace":
      return { layout: copy(action.layout), reset: false };
    case "reset":
      return { layout: copy(action.layout), reset: true };
  }
}

export function isDirty(draft: Draft, start: StoredLayout): boolean {
  return draft.reset || JSON.stringify(draft.layout) !== JSON.stringify(start);
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd dashboard && npx vitest run src/overview/draft.test.ts && npm run typecheck`
Expected: PASS, 9 tests; typecheck exits 0.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/overview/draft.ts dashboard/src/overview/draft.test.ts
git commit -m "feat(dashboard): Overview editor draft reducer" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/draft.ts dashboard/src/overview/draft.test.ts
```

---

### Task 13: `OverviewEditor`: Customise, the draft, and its safeguards

**Files:**
- Create: `dashboard/src/overview/session.ts`, `dashboard/src/overview/WidgetToolbar.tsx`, `dashboard/src/overview/WidgetSettingsForm.tsx`, `dashboard/src/overview/AddWidgetPanel.tsx`, `dashboard/src/overview/CustomiseMenu.tsx`, `dashboard/src/overview/OverviewEditor.tsx`
- Test: `dashboard/src/overview/session.test.ts`, `dashboard/src/overview/OverviewEditor.test.tsx`, `dashboard/src/components/ConfirmButton.test.tsx`
- Modify: `dashboard/src/components/ConfirmButton.tsx`, `dashboard/src/lib/healthQueries.ts`, `dashboard/src/pages/BranchesPage.tsx`, `dashboard/src/pages/OverviewPage.tsx`, `dashboard/src/index.css`
- Docs: `DESIGN.md`, `docs/SETUP.md`

**Interfaces:**
- Consumes: Tasks 8–12 (`MAX_WIDGETS`, `CATALOG`, `ALL`, `StoredLayout`, `StoredWidget`, `WidgetSettings`, `SettingName`, `BUILTIN_DEFAULT`, `useOverviewLayout`, `conflictOf`, `StoredVersion`, `LayoutMode`, `OverviewLayoutState`, `WidgetCard`, `WidgetGrid`, `definitionOf`, `knownWidgets`, `withDefaults`, `widgetTitle`, `addableDefinitions`, `WidgetDefinition`, `draftReducer`, `isDirty`, `nextWidgetId`, `formatDay`, `useLatestRun`); `UnsavedGuard`, `ConfirmButton`, `ErrorBanner`, `useUserNames(projectId)` (email or "user #id"); `getBranches`.
- Produces:
  - `src/overview/session.ts`: `interface EditSession { mode: LayoutMode; start: StoredLayout; version: number; fallback: StoredLayout; defaultChangedAt: string | null; lastChange: { by: number; at: string } | null; openSettingsFor: string | null }`; `startSession(state: OverviewLayoutState, mode: LayoutMode, openSettingsFor?: string | null): EditSession`;
  - `src/overview/OverviewEditor.tsx`: default export, props `{ projectId: number; session: EditSession; onClose: () => void; onReload: () => void }` (both modes, the 409 dialog and the default-changed note are in this file; Task 14 opens project mode to owners and admins);
  - `src/overview/CustomiseMenu.tsx`: default export, props `{ canManage: boolean; onPick: (mode: LayoutMode) => void; triggerRef: RefObject<HTMLButtonElement | null> }`;
  - `src/overview/AddWidgetPanel.tsx`: default export, props `{ id: string; full: boolean; onAdd: (def: WidgetDefinition) => void; onClose: () => void }`;
  - `src/overview/WidgetToolbar.tsx`, `src/overview/WidgetSettingsForm.tsx` (props `{ projectId: number; widget: StoredWidget; onApply: (settings: WidgetSettings) => void; onClose: () => void }`);
  - `ConfirmButton` gains optional `triggerClassName?: string`, `confirmClassName?: string` (default `"danger"`), `cancelLabel?: string` (default `"Cancel"`) (Ruling 22);
  - `src/lib/healthQueries.ts`: `branchesViewQuery(projectId: number, days = 30)` (key `["branches", projectId, days]`, the Branches view's own query).

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill and read DESIGN.md "Buttons", "Destructive Confirmation", "Inputs / Fields", "Accessibility Plumbing" and "Named Rules" (Coarse Pointer).

- [ ] **Step 2: Write the failing tests**

Append to `dashboard/src/components/ConfirmButton.test.tsx`:

```tsx
test("a consequential save can confirm in primary, with its own back-out word", async () => {
  render(
    <ConfirmButton label="Save" triggerClassName="primary" question="Everyone sees this." confirmLabel="Save for everyone"
      confirmClassName="primary" cancelLabel="Back" onConfirm={() => {}} />,
  );
  expect(screen.getByRole("button", { name: "Save" })).toHaveClass("primary");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByRole("button", { name: "Save for everyone" })).toHaveClass("primary");
  expect(screen.getByRole("button", { name: "Save for everyone" })).not.toHaveClass("danger");
  expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
});
```

Create `dashboard/src/overview/session.test.ts`:

```ts
import type { OverviewLayoutState } from "../api/overviewLayout";
import type { StoredLayout } from "./catalog";
import { startSession } from "./session";
import { BUILTIN_DEFAULT } from "./templates";

const MINE: StoredLayout = { schema: 1, widgets: [{ id: "m1", type: "flaky_count", size: "normal" }] };
const DEFAULT: StoredLayout = { schema: 1, widgets: [{ id: "d1", type: "latest_run", size: "wide" }] };
const project = { version: 4, updated_by: 7, updated_at: "2026-10-05T10:00:00Z", layout: DEFAULT };
const personalOver: OverviewLayoutState = {
  effective: MINE, source: "personal", personal: { version: 2, updated_at: "2026-10-01T10:00:00Z" }, project,
};

test("personal editing starts from what the user sees, with the project default as the reset target", () => {
  const session = startSession(personalOver, "personal");
  expect(session).toMatchObject({ mode: "personal", start: MINE, version: 2, fallback: DEFAULT, lastChange: null, openSettingsFor: null });
});

test("project editing starts from the project default even when a personal layout wins", () => {
  expect(startSession(personalOver, "project")).toMatchObject({
    mode: "project", start: DEFAULT, version: 4, fallback: BUILTIN_DEFAULT, defaultChangedAt: null,
    lastChange: { by: 7, at: "2026-10-05T10:00:00Z" },
  });
});

test("with nothing saved both modes start from the built-in default at version 0", () => {
  const builtin: OverviewLayoutState = { effective: null, source: "builtin", personal: null, project: null };
  expect(startSession(builtin, "personal")).toMatchObject({ start: BUILTIN_DEFAULT, version: 0, fallback: BUILTIN_DEFAULT });
  expect(startSession(builtin, "project")).toMatchObject({ start: BUILTIN_DEFAULT, version: 0, lastChange: null });
});

test("the default-changed date shows only when the default is newer than the personal layout", () => {
  expect(startSession(personalOver, "personal").defaultChangedAt).toBe("2026-10-05T10:00:00Z");
  const newerMine = { ...personalOver, personal: { version: 2, updated_at: "2026-10-06T10:00:00Z" } };
  expect(startSession(newerMine, "personal").defaultChangedAt).toBeNull();
});

test("widgets of unknown types are left out of the draft, and a widget's settings can open at once", () => {
  vi.spyOn(console, "warn").mockImplementation(() => {});
  const odd: OverviewLayoutState = { ...personalOver, effective: { schema: 1, widgets: [...MINE.widgets, { id: "x", type: "gone_type", size: "wide" }] } };
  const session = startSession(odd, "personal", "m1");
  expect(session.start.widgets.map((w) => w.id)).toEqual(["m1"]);
  expect(session.openSettingsFor).toBe("m1");
});
```

Create `dashboard/src/overview/OverviewEditor.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import type { OverviewLayoutState } from "../api/overviewLayout";
import type { StoredLayout } from "./catalog";
import { BUILTIN_DEFAULT } from "./templates";
import { BUILTIN_STATE, mockOverviewData, personalState, projectState, renderOverview } from "./testing";

const PUT_PERSONAL = "/api/v1/projects/42/overview-layout/personal";
type Sent = { layout: StoredLayout; version: number };

/** Records personal saves; the layout GET then answers what was saved last (the refetch after Save reads it). */
function capturePuts(): Sent[] {
  const bodies: Sent[] = [];
  server.use(
    http.put(PUT_PERSONAL, async ({ request }) => {
      const body = (await request.json()) as Sent;
      bodies.push(body);
      return HttpResponse.json({ layout: body.layout, version: body.version + 1, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
    }),
    http.get("/api/v1/projects/42/overview-layout", () => {
      const last = bodies[bodies.length - 1];
      if (last === undefined) return HttpResponse.json(BUILTIN_STATE);
      return HttpResponse.json({ ...personalState(...last.layout.widgets), personal: { version: last.version + 1, updated_at: "2026-10-11T10:00:00Z" } });
    }),
  );
  return bodies;
}

async function startEditing() {
  await userEvent.click(await screen.findByRole("button", { name: "Customise" }));
  expect(await screen.findByText("Editing your Overview")).toBeInTheDocument();
}

const titles = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
const MINE = { id: "m1", type: "flaky_count", size: "normal" as const };
const mineOverDefault = (personalUpdatedAt: string): OverviewLayoutState => ({
  ...projectState(BUILTIN_DEFAULT), effective: { schema: 1, widgets: [MINE] }, source: "personal",
  personal: { version: 3, updated_at: personalUpdatedAt },
});

test("Customise edits a draft and Save sends it with the version editing started from", async () => {
  mockOverviewData();
  const puts = capturePuts();
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Move Pass rate this week up" }));
  expect(titles()).toEqual(["Latest run", "Pass rate this week", "Failing in latest run", "Flaky tests, last 14 days"]);
  expect(puts).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0].version).toBe(0);
  expect(puts[0].layout.widgets.map((w) => w.id)).toEqual(["w1", "w3", "w2", "w4"]);
  expect(await screen.findByRole("button", { name: "Customise" })).toHaveFocus();
  expect(screen.queryByText("Editing your Overview")).not.toBeInTheDocument();
  expect(titles()).toEqual(["Latest run", "Pass rate this week", "Failing in latest run", "Flaky tests, last 14 days"]);
});

test("a move keeps focus on the moved widget and is announced in one polite live region", async () => {
  mockOverviewData();
  renderOverview();
  await startEditing();
  const name = "Move Flaky tests, last 14 days up";
  await userEvent.click(screen.getByRole("button", { name }));
  expect(screen.getByRole("button", { name })).toHaveFocus();
  expect(screen.getByText("Flaky tests, last 14 days moved to position 3 of 4")).toHaveAttribute("aria-live", "polite");
  await userEvent.click(screen.getByRole("button", { name }));
  await userEvent.click(screen.getByRole("button", { name }));
  // At the top its Move up is disabled, so focus rests on the widget itself
  expect(screen.getByRole("region", { name: "Flaky tests, last 14 days" })).toHaveFocus();
  expect(screen.getByText("Flaky tests, last 14 days moved to position 1 of 4")).toBeInTheDocument();
});

test("Wide and Normal resize a widget in the draft", async () => {
  mockOverviewData();
  renderOverview();
  await startEditing();
  const toggle = screen.getByRole("button", { name: "Show Pass rate this week wide" });
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(toggle);
  expect(screen.getByRole("region", { name: "Pass rate this week" })).toHaveClass("wide");
  expect(screen.getByRole("button", { name: "Show Pass rate this week wide" })).toHaveAttribute("aria-pressed", "true");
});

test("Remove and Add change the draft, move focus sensibly and say so", async () => {
  mockOverviewData();
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Flaky tests, last 14 days" }));
  expect(screen.queryByRole("region", { name: "Flaky tests, last 14 days" })).not.toBeInTheDocument();
  expect(screen.getByText("Flaky tests, last 14 days removed")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Pass rate this week" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Add widget" }));
  const panel = screen.getByRole("region", { name: "Add a widget" });
  await userEvent.click(within(panel).getByRole("button", { name: "Add Flaky tests" }));
  expect(await screen.findByRole("region", { name: "Flaky tests, last 14 days" })).toHaveFocus();
  expect(screen.getByText("Flaky tests added at position 4 of 4")).toBeInTheDocument();
});

test("Settings change a widget's settings, which Save sends", async () => {
  mockOverviewData();
  const puts = capturePuts();
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Failing in latest run settings" }));
  const form = screen.getByRole("form", { name: "Failing in latest run settings" });
  await userEvent.selectOptions(within(form).getByLabelText("Rows"), "10");
  await userEvent.click(within(form).getByRole("button", { name: "Apply" }));
  expect(screen.getByRole("button", { name: "Failing in latest run settings" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0].layout.widgets[1]).toEqual({ id: "w2", type: "failing_now", size: "normal", settings: { rows: 10 } });
});

test("leaving with changes asks first: Cancel asks in place, navigation and closing the tab are guarded", async () => {
  mockOverviewData();
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByText("Editing your Overview")).not.toBeInTheDocument(); // nothing changed: it leaves at once
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Discard" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  await userEvent.click(screen.getByRole("link", { name: "Elsewhere" }));
  expect(await screen.findByRole("alertdialog", { name: "Unsaved changes" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Stay" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(screen.queryByText("Editing your Overview")).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Latest run" })).toBeInTheDocument();
});

test("a background refetch while editing keeps the draft", async () => {
  mockOverviewData();
  const { qc } = renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  server.use(http.get("/api/v1/projects/42/overview-layout", () =>
    HttpResponse.json(personalState({ id: "z", type: "flaky_count", size: "normal" }))));
  await qc.invalidateQueries({ queryKey: ["overview-layout", 42] });
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
  expect(titles()).toEqual(["Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"]);
});

test("Reset to project default puts the default in the draft, and Save then deletes the personal layout", async () => {
  mockOverviewData({ layout: mineOverDefault("2026-10-10T10:00:00Z") });
  const deleted: string[] = [];
  server.use(http.delete("/api/v1/projects/42/overview-layout/:mode", ({ params }) => {
    deleted.push(String(params.mode));
    return new HttpResponse(null, { status: 204 });
  }));
  renderOverview();
  await startEditing();
  expect(titles()).toEqual(["Flaky tests, last 14 days"]);
  await userEvent.click(screen.getByRole("button", { name: "Reset to project default" }));
  expect(titles()).toEqual(["Latest run", "Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"]);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(deleted).toEqual(["personal"]));
  expect(await screen.findByRole("button", { name: "Customise" })).toBeInTheDocument();
});

test("the editor notes when the project default changed after the personal layout was saved", async () => {
  mockOverviewData({ layout: mineOverDefault("2026-10-01T10:00:00Z") });
  renderOverview();
  await startEditing();
  expect(screen.getByText(/^The project default changed on /)).toBeInTheDocument();
});

test("a layout of 24 widgets cannot take another", async () => {
  const many = Array.from({ length: 24 }, (_, i) => ({ id: `w${i + 1}`, type: "flaky_count", size: "normal" as const }));
  mockOverviewData({ layout: personalState(...many) });
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Add widget" }));
  const panel = screen.getByRole("region", { name: "Add a widget" });
  expect(within(panel).getByText(/at most 24 widgets/)).toBeInTheDocument();
  expect(within(panel).getByRole("button", { name: "Add Latest run" })).toBeDisabled();
});

test("a stale save shows who changed it; Overwrite resends with their version", async () => {
  mockOverviewData({ layout: personalState(...BUILTIN_DEFAULT.widgets) });
  const versions: number[] = [];
  server.use(http.put(PUT_PERSONAL, async ({ request }) => {
    const body = (await request.json()) as Sent;
    versions.push(body.version);
    if (versions.length === 1) {
      return HttpResponse.json({ detail: { code: "stale_version", message: "Changed",
        current: { version: 5, updated_by: 7, updated_at: "2026-10-11T09:00:00Z" } } }, { status: 409 });
    }
    return HttpResponse.json({ layout: body.layout, version: 6, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
  }));
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  const dialog = await screen.findByRole("alertdialog", { name: "The layout changed while you were editing" });
  expect(dialog).toHaveTextContent(/Changed by ada@example\.com on .+ since you started/);
  expect(within(dialog).getByRole("button", { name: "Reload" })).toHaveFocus();
  await userEvent.click(within(dialog).getByRole("button", { name: "Overwrite" }));
  await waitFor(() => expect(versions).toEqual([1, 5]));
  expect(await screen.findByRole("button", { name: "Customise" })).toBeInTheDocument();
});

test("Reload after a conflict starts editing again from the stored layout", async () => {
  mockOverviewData({ layout: personalState(...BUILTIN_DEFAULT.widgets) });
  server.use(http.put(PUT_PERSONAL, () => HttpResponse.json({ detail: { code: "stale_version", message: "Changed",
    current: { version: 2, updated_by: 7, updated_at: "2026-10-11T09:00:00Z" } } }, { status: 409 })));
  renderOverview();
  await startEditing();
  await userEvent.click(screen.getByRole("button", { name: "Remove Latest run" }));
  server.use(http.get("/api/v1/projects/42/overview-layout", () => HttpResponse.json({
    ...personalState({ id: "n1", type: "flaky_count", size: "wide" }), personal: { version: 2, updated_at: "2026-10-11T09:00:00Z" },
  })));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await userEvent.click(await screen.findByRole("button", { name: "Reload" }));
  await waitFor(() => expect(titles()).toEqual(["Flaky tests, last 14 days"]));
  expect(screen.getByText("Editing your Overview")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/components/ConfirmButton.test.tsx src/overview/session.test.ts src/overview/OverviewEditor.test.tsx`
Expected: FAIL: `Failed to resolve import "./session"`; the editor tests fail with `Unable to find an accessible element with the role "button" and name "Customise"`; the ConfirmButton test fails with `expected <button> to have class "primary"`.

- [ ] **Step 4: Extend `ConfirmButton` and add the Branches view's query**

In `dashboard/src/components/ConfirmButton.tsx`, replace:

```tsx
  onConfirm: () => void;
  disabled?: boolean;
}
```

with:

```tsx
  onConfirm: () => void;
  disabled?: boolean;
  /** The trigger's class, e.g. "primary" for a Save that confirms first. */
  triggerClassName?: string;
  /** "danger" (the default) for destructive actions; "primary" for a consequential save that destroys nothing. */
  confirmClassName?: string;
  /** The back-out button's text ("Cancel" by default). */
  cancelLabel?: string;
}
```

replace:

```tsx
export default function ConfirmButton({ label, ariaLabel, question, confirmLabel, onConfirm, disabled }: Props) {
```

with:

```tsx
export default function ConfirmButton({
  label, ariaLabel, question, confirmLabel, onConfirm, disabled, triggerClassName, confirmClassName = "danger", cancelLabel = "Cancel",
}: Props) {
```

replace:

```tsx
      <button type="button" ref={triggerRef} aria-label={ariaLabel} onClick={() => setAsking(true)} disabled={disabled}>
```

with:

```tsx
      <button type="button" ref={triggerRef} className={triggerClassName} aria-label={ariaLabel} onClick={() => setAsking(true)} disabled={disabled}>
```

replace:

```tsx
        className="danger"
```

with:

```tsx
        className={confirmClassName}
```

and replace:

```tsx
      <button type="button" onClick={cancel}>Cancel</button>
```

with:

```tsx
      <button type="button" onClick={cancel}>{cancelLabel}</button>
```

In `dashboard/src/lib/healthQueries.ts`, replace:

```ts
import { getFlaky, getTrends } from "../api/analytics";
```

with:

```ts
import { getBranches, getFlaky, getTrends } from "../api/analytics";

/** The Branches view's own query (30 days by default): the branch setting and Branch health share its answer. */
export const branchesViewQuery = (projectId: number, days = 30) => ({
  queryKey: ["branches", projectId, days] as const,
  queryFn: () => getBranches(projectId, { days }),
});
```

In `dashboard/src/pages/BranchesPage.tsx`, replace:

```tsx
import { formatPassRate, getBranches, getTrends } from "../api/analytics";
```

with:

```tsx
import { formatPassRate, getTrends } from "../api/analytics";
import { branchesViewQuery } from "../lib/healthQueries";
```

and replace:

```tsx
  const branchesQuery = useQuery({
    queryKey: ["branches", id, days],
    queryFn: () => getBranches(id, { days }),
  });
```

with:

```tsx
  const branchesQuery = useQuery(branchesViewQuery(id, days));
```

- [ ] **Step 5: Write the edit session, the toolbar, the settings form, the Add panel and the Customise button**

Create `dashboard/src/overview/session.ts`:

```ts
import type { LayoutMode, OverviewLayoutState } from "../api/overviewLayout";
import type { StoredLayout } from "./catalog";
import { BUILTIN_DEFAULT } from "./templates";
import { knownWidgets } from "./widgets/registry";

/** Where an edit starts, frozen when Customise is pressed: a background refetch never replaces the draft (Ruling 21). */
export interface EditSession {
  mode: LayoutMode;
  start: StoredLayout;
  /** Sent with Save; 0 creates. */
  version: number;
  /** What Reset puts in the draft: the project default (personal mode) or the built-in default (project mode). */
  fallback: StoredLayout;
  /** Personal mode: the project default's date when it changed after this personal layout (spec §2.8). */
  defaultChangedAt: string | null;
  /** Project mode: who changed the default last. */
  lastChange: { by: number; at: string } | null;
  /** A widget whose settings open at once (the empty-branch and no-name buttons). */
  openSettingsFor: string | null;
}

// Widgets of unknown types are left out of the draft (plan Ruling 28)
const known = (layout: StoredLayout): StoredLayout => ({ ...layout, widgets: knownWidgets(layout) });

export function startSession(state: OverviewLayoutState, mode: LayoutMode, openSettingsFor: string | null = null): EditSession {
  if (mode === "personal") {
    const defaultIsNewer = state.personal !== null && state.project !== null
      && Date.parse(state.project.updated_at) > Date.parse(state.personal.updated_at);
    return {
      mode,
      start: known(state.effective ?? BUILTIN_DEFAULT),
      version: state.personal?.version ?? 0,
      fallback: known(state.project?.layout ?? BUILTIN_DEFAULT),
      defaultChangedAt: defaultIsNewer && state.project ? state.project.updated_at : null,
      lastChange: null,
      openSettingsFor,
    };
  }
  return {
    mode,
    // The project default itself, never the editor's own personal layout (plan Ruling 4)
    start: known(state.project?.layout ?? BUILTIN_DEFAULT),
    version: state.project?.version ?? 0,
    fallback: BUILTIN_DEFAULT,
    defaultChangedAt: null,
    lastChange: state.project ? { by: state.project.updated_by, at: state.project.updated_at } : null,
    openSettingsFor,
  };
}
```

Create `dashboard/src/overview/WidgetToolbar.tsx`:

```tsx
import { ArrowDown, ArrowUp, Maximize2, SlidersHorizontal, Trash2 } from "lucide-react";

interface Props {
  title: string;
  first: boolean;
  last: boolean;
  wide: boolean;
  hasSettings: boolean;
  settingsOpen: boolean;
  onMove: (by: -1 | 1) => void;
  onSize: () => void;
  onSettings: () => void;
  onRemove: () => void;
}

/** Edit mode only (spec §2.2): labelled icon buttons, each named for its widget, 28 px (44 px on touch). */
export default function WidgetToolbar({ title, first, last, wide, hasSettings, settingsOpen, onMove, onSize, onSettings, onRemove }: Props) {
  return (
    <div className="widget-toolbar" role="group" aria-label={`${title} widget`}>
      <button type="button" className="ghost widget-tool" data-tool="up" aria-label={`Move ${title} up`} disabled={first} onClick={() => onMove(-1)}>
        <ArrowUp size={16} aria-hidden="true" />
      </button>
      <button type="button" className="ghost widget-tool" data-tool="down" aria-label={`Move ${title} down`} disabled={last} onClick={() => onMove(1)}>
        <ArrowDown size={16} aria-hidden="true" />
      </button>
      <button type="button" className="ghost widget-tool" data-tool="size" aria-label={`Show ${title} wide`} aria-pressed={wide} onClick={onSize}>
        <Maximize2 size={16} aria-hidden="true" />
      </button>
      {hasSettings && (
        <button type="button" className="ghost widget-tool" data-tool="settings" aria-label={`${title} settings`} aria-expanded={settingsOpen} onClick={onSettings}>
          <SlidersHorizontal size={16} aria-hidden="true" />
        </button>
      )}
      <button type="button" className="ghost widget-tool" data-tool="remove" aria-label={`Remove ${title}`} onClick={onRemove}>
        <Trash2 size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
```

Create `dashboard/src/overview/WidgetSettingsForm.tsx`:

```tsx
import { type FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { branchesViewQuery } from "../lib/healthQueries";
import { ALL, CATALOG, type SettingName, type StoredWidget, type WidgetSettings } from "./catalog";
import { definitionOf, widgetTitle, withDefaults } from "./widgets/registry";

const LABELS: Record<SettingName, string> = {
  rows: "Rows", period: "Period", granularity: "View", branch: "Branch", author: "Your name in git",
};
const VIEW_NAMES: Record<string, string> = { day: "Daily", week: "Weekly", month: "Monthly" };

interface Props {
  projectId: number;
  widget: StoredWidget;
  onApply: (settings: WidgetSettings) => void;
  onClose: () => void;
}

/** A widget's settings, inline in its card: only the values the catalogue allows. Escape closes it. */
export default function WidgetSettingsForm({ projectId, widget, onApply, onClose }: Props) {
  const def = definitionOf(widget.type);
  const [values, setValues] = useState<WidgetSettings>(() => (def ? withDefaults(def, widget.settings) : {}));
  const branches = useQuery({ ...branchesViewQuery(projectId), enabled: def?.settings.includes("branch") ?? false });
  if (def === undefined) return null;
  const title = widgetTitle(widget);
  const fieldId = (name: SettingName) => `ov-${widget.id}-${name}`;
  const set = (name: SettingName, value: string | number) => setValues((v) => ({ ...v, [name]: value }) as WidgetSettings);
  const branchNames = [...new Set((branches.data ?? []).flatMap((b) => (b.branch ? [b.branch] : [])))].sort();
  if (values.branch && values.branch !== ALL && !branchNames.includes(values.branch)) branchNames.unshift(values.branch);

  function submit(event: FormEvent) {
    event.preventDefault();
    const out: WidgetSettings = { ...values };
    const author = out.author?.trim();
    // Empty means "my QEOS full name", the widget's default
    if (author) out.author = author;
    else delete out.author;
    onApply(out);
  }

  return (
    <form
      className="widget-settings"
      aria-label={`${title} settings`}
      onSubmit={submit}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
    >
      {def.settings.map((name) => {
        const spec = CATALOG.settings[name];
        if (name === "branch") {
          return (
            <div className="widget-setting" key={name}>
              <label htmlFor={fieldId(name)}>{LABELS[name]}</label>
              <select id={fieldId(name)} value={values.branch ?? ALL} onChange={(e) => set(name, e.target.value)}>
                <option value={ALL}>All branches</option>
                {branchNames.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>
          );
        }
        if (spec.kind === "text") {
          return (
            <div className="widget-setting" key={name}>
              <label htmlFor={fieldId(name)}>{LABELS[name]}</label>
              <input
                id={fieldId(name)}
                value={values.author ?? ""}
                maxLength={spec.max_length}
                aria-describedby={`${fieldId(name)}-hint`}
                onChange={(e) => set(name, e.target.value)}
              />
              <span className="muted" id={`${fieldId(name)}-hint`}>As git records it. Empty: your QEOS full name.</span>
            </div>
          );
        }
        return (
          <div className="widget-setting" key={name}>
            <label htmlFor={fieldId(name)}>{LABELS[name]}</label>
            <select
              id={fieldId(name)}
              value={String(values[name] ?? "")}
              onChange={(e) => set(name, typeof spec.values[0] === "number" ? Number(e.target.value) : e.target.value)}
            >
              {spec.values.map((v) => (
                <option key={String(v)} value={String(v)}>
                  {name === "period" ? `${v} days` : name === "granularity" ? VIEW_NAMES[String(v)] : String(v)}
                </option>
              ))}
            </select>
          </div>
        );
      })}
      <div className="button-row">
        <button type="submit" className="primary">Apply</button>
        <button type="button" onClick={onClose}>Close</button>
      </div>
    </form>
  );
}
```

Create `dashboard/src/overview/AddWidgetPanel.tsx`:

```tsx
import { X } from "lucide-react";
import { MAX_WIDGETS } from "./catalog";
import { addableDefinitions } from "./widgets/registry";
import type { WidgetDefinition } from "./widgets/types";

interface Props {
  id: string;
  /** The layout holds MAX_WIDGETS already. */
  full: boolean;
  onAdd: (def: WidgetDefinition) => void;
  onClose: () => void;
}

/** Every widget type with a one-line description (spec §2.2 Add widget). Escape closes it. */
export default function AddWidgetPanel({ id, full, onAdd, onClose }: Props) {
  return (
    <section
      id={id}
      className="card"
      aria-labelledby={`${id}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <div className="card-head">
        <h2 id={`${id}-title`}>Add a widget</h2>
        <button type="button" className="ghost widget-tool" aria-label="Close the widget list" onClick={onClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      {full && <p className="muted">A layout holds at most {MAX_WIDGETS} widgets. Remove one to add another.</p>}
      <ul className="add-widget-list">
        {addableDefinitions().map((def) => (
          <li key={def.type}>
            <div>
              <strong>{def.title}</strong>
              <p className="muted">{def.description}</p>
            </div>
            <button type="button" aria-label={`Add ${def.title}`} disabled={full} onClick={() => onAdd(def)}>Add</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

Create `dashboard/src/overview/CustomiseMenu.tsx`:

```tsx
import { type RefObject, useEffect, useRef, useState } from "react";
import { ChevronDown, LayoutGrid } from "lucide-react";
import type { LayoutMode } from "../api/overviewLayout";

interface Props {
  /** Owners and admins also get "Edit project default" (spec §2.3). */
  canManage: boolean;
  onPick: (mode: LayoutMode) => void;
  triggerRef: RefObject<HTMLButtonElement | null>;
}

/** Customise in the Overview header. For owners and admins it is a disclosure, as the account menu is: Escape closes
 *  it and returns focus to the button; a click or focus outside closes it. */
export default function CustomiseMenu({ canManage, onPick, triggerRef }: Props) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const outside = (e: Event) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("focusin", outside);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("focusin", outside);
    };
  }, [open]);

  if (!canManage) {
    return (
      <button type="button" ref={triggerRef} onClick={() => onPick("personal")}>
        <LayoutGrid size={15} aria-hidden="true" /> Customise
      </button>
    );
  }
  const pick = (mode: LayoutMode) => {
    setOpen(false);
    onPick(mode);
  };
  return (
    <div
      className="customise-menu"
      ref={box}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.preventDefault();
          setOpen(false);
          triggerRef.current?.focus();
        }
      }}
    >
      <button type="button" ref={triggerRef} aria-expanded={open} aria-controls="customise-options" onClick={() => setOpen((o) => !o)}>
        <LayoutGrid size={15} aria-hidden="true" /> Customise <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <ul id="customise-options" className="customise-popup">
          <li><button type="button" className="menu-item" onClick={() => pick("personal")}>Customise your Overview</button></li>
          <li><button type="button" className="menu-item" onClick={() => pick("project")}>Edit project default</button></li>
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Write the editor**

Create `dashboard/src/overview/OverviewEditor.tsx`:

```tsx
import { useEffect, useReducer, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { type StoredVersion, conflictOf } from "../api/overviewLayout";
import ConfirmButton from "../components/ConfirmButton";
import ErrorBanner from "../components/ErrorBanner";
import UnsavedGuard from "../components/UnsavedGuard";
import { useUserNames } from "../lib/useUserNames";
import AddWidgetPanel from "./AddWidgetPanel";
import { MAX_WIDGETS, type StoredWidget, type WidgetSettings } from "./catalog";
import { type Draft, draftReducer, isDirty, nextWidgetId } from "./draft";
import { formatDay } from "./format";
import type { EditSession } from "./session";
import { useOverviewLayout } from "./useOverviewLayout";
import WidgetCard from "./WidgetCard";
import WidgetSettingsForm from "./WidgetSettingsForm";
import WidgetToolbar from "./WidgetToolbar";
import { definitionOf, widgetTitle } from "./widgets/registry";
import type { WidgetDefinition } from "./widgets/types";

interface Props {
  projectId: number;
  session: EditSession;
  /** Leave edit mode: after Save, or a Cancel that discards. */
  onClose: () => void;
  /** After a 409: start again from the stored layout. */
  onReload: () => void;
}

type FocusTarget = { id: string; tool: "up" | "down" | "settings" | "card" } | { id: null; tool: "add" };

/** Edit mode (spec §2.2, §2.3, §2.8): the page shows the draft; Save stores it (or deletes the stored layout after a
 *  Reset), Cancel discards it after asking. Moves keep focus and are announced in one polite live region. */
export default function OverviewEditor({ projectId, session, onClose, onReload }: Props) {
  const { save, reset } = useOverviewLayout(projectId);
  const nameOf = useUserNames(projectId);
  const [draft, dispatch] = useReducer(draftReducer, session.start, (layout): Draft => ({ layout, reset: false }));
  const [settingsFor, setSettingsFor] = useState<string | null>(session.openSettingsFor);
  const [adding, setAdding] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [conflict, setConflict] = useState<StoredVersion | null | undefined>(undefined);
  const [failure, setFailure] = useState<unknown>(null);
  const titleRef = useRef<HTMLParagraphElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const focusAfter = useRef<FocusTarget | null>(null);
  const widgets = draft.layout.widgets;
  const dirty = isDirty(draft, session.start);
  const busy = save.isPending || reset.isPending;
  const project = session.mode === "project";

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  useEffect(() => {
    if (conflict !== undefined) reloadRef.current?.focus();
  }, [conflict]);

  // Focus follows the widget that moved, the neighbour of one removed, or the one added
  useEffect(() => {
    const target = focusAfter.current;
    if (target === null) return;
    focusAfter.current = null;
    if (target.id === null) {
      addRef.current?.focus();
      return;
    }
    const card = gridRef.current?.querySelector<HTMLElement>(`[data-widget-id="${target.id}"]`);
    const tool = target.tool === "card" ? null : card?.querySelector<HTMLButtonElement>(`[data-tool="${target.tool}"]`);
    if (tool && !tool.disabled) tool.focus();
    else card?.focus();
  }, [draft, settingsFor]);

  function move(widget: StoredWidget, index: number, by: -1 | 1) {
    dispatch({ kind: "move", id: widget.id, by });
    focusAfter.current = { id: widget.id, tool: by < 0 ? "up" : "down" };
    setAnnouncement(`${widgetTitle(widget)} moved to position ${index + by + 1} of ${widgets.length}`);
  }

  function toggleSize(widget: StoredWidget) {
    dispatch({ kind: "size", id: widget.id });
    setAnnouncement(`${widgetTitle(widget)} is now ${widget.size === "wide" ? "normal width" : "wide"}`);
  }

  function remove(widget: StoredWidget, index: number) {
    const neighbour = widgets[index + 1] ?? widgets[index - 1];
    dispatch({ kind: "remove", id: widget.id });
    if (settingsFor === widget.id) setSettingsFor(null);
    focusAfter.current = neighbour ? { id: neighbour.id, tool: "card" } : { id: null, tool: "add" };
    setAnnouncement(`${widgetTitle(widget)} removed`);
  }

  function add(def: WidgetDefinition) {
    const id = nextWidgetId(widgets);
    dispatch({ kind: "add", id, type: def.type, size: def.defaultSize, settings: { ...def.defaults } });
    setAdding(false);
    focusAfter.current = { id, tool: "card" };
    setAnnouncement(`${def.title} added at position ${widgets.length + 1} of ${widgets.length + 1}`);
  }

  function applySettings(widget: StoredWidget, settings: WidgetSettings) {
    dispatch({ kind: "settings", id: widget.id, settings });
    setSettingsFor(null);
    focusAfter.current = { id: widget.id, tool: "settings" };
    setAnnouncement(`${widgetTitle({ ...widget, settings })} settings applied`);
  }

  function resetDraft() {
    dispatch({ kind: "reset", layout: session.fallback });
    setSettingsFor(null);
    setAnnouncement(project ? "The built-in default is in the draft" : "The project default is in the draft");
  }

  async function commit(version: number = session.version) {
    setFailure(null);
    setConflict(undefined);
    try {
      if (draft.reset) {
        // Delete rather than save a copy, so later changes to the default still arrive (plan Ruling 20)
        if (session.version > 0) await reset.mutateAsync(session.mode);
      } else {
        await save.mutateAsync({ mode: session.mode, layout: draft.layout, version });
      }
      onClose();
    } catch (error) {
      const stored = conflictOf(error);
      if (stored !== undefined) setConflict(stored);
      else setFailure(error);
    }
  }

  return (
    <>
      <UnsavedGuard dirty={dirty} />
      <div className="overview-edit-bar" role="region" aria-label="Overview editor">
        <div>
          <p className="overview-edit-title" ref={titleRef} tabIndex={-1}>
            {project ? "Editing the project default · everyone without a personal layout sees this" : "Editing your Overview"}
          </p>
          {project && session.lastChange && (
            <p className="overview-note">Last changed by {nameOf(session.lastChange.by)} on {formatDay(session.lastChange.at)}</p>
          )}
        </div>
        <div className="button-row">
          <button type="button" ref={addRef} aria-expanded={adding} aria-controls="overview-add" onClick={() => setAdding((a) => !a)}>
            <Plus size={15} aria-hidden="true" /> Add widget
          </button>
          <button type="button" onClick={resetDraft}>{project ? "Reset to built-in default" : "Reset to project default"}</button>
          {session.defaultChangedAt && (
            <span className="overview-note">The project default changed on {formatDay(session.defaultChangedAt)}</span>
          )}
          {dirty ? (
            <ConfirmButton label="Cancel" question="Discard your changes?" confirmLabel="Discard" cancelLabel="Keep editing" onConfirm={onClose} />
          ) : (
            <button type="button" onClick={onClose}>Cancel</button>
          )}
          {project ? (
            <ConfirmButton
              label="Save"
              triggerClassName="primary"
              question="Everyone without a personal layout will see this layout."
              confirmLabel="Save for everyone"
              confirmClassName="primary"
              cancelLabel="Back"
              disabled={busy || !dirty}
              onConfirm={() => void commit()}
            />
          ) : (
            <button type="button" className="primary" disabled={busy || !dirty} onClick={() => void commit()}>Save</button>
          )}
        </div>
        {failure != null && <ErrorBanner error={failure} />}
        {conflict !== undefined && (
          <div className="error-banner" role="alertdialog" aria-label="The layout changed while you were editing">
            <span>
              {conflict
                ? `Changed by ${nameOf(conflict.updated_by)} on ${formatDay(conflict.updated_at)} since you started`
                : "This layout was removed since you started"}
            </span>
            <button type="button" ref={reloadRef} onClick={onReload}>Reload</button>
            <button type="button" onClick={() => void commit(conflict?.version ?? 0)}>Overwrite</button>
          </div>
        )}
      </div>
      {adding && (
        <AddWidgetPanel
          id="overview-add"
          full={widgets.length >= MAX_WIDGETS}
          onAdd={add}
          onClose={() => {
            setAdding(false);
            addRef.current?.focus();
          }}
        />
      )}
      <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
      <div className="overview-grid" ref={gridRef}>
        {widgets.map((widget, index) => {
          const title = widgetTitle(widget);
          const hasSettings = (definitionOf(widget.type)?.settings.length ?? 0) > 0;
          return (
            <WidgetCard
              key={widget.id}
              projectId={projectId}
              widget={widget}
              onOpenSettings={hasSettings ? () => setSettingsFor(widget.id) : undefined}
              tools={
                <>
                  <WidgetToolbar
                    title={title}
                    first={index === 0}
                    last={index === widgets.length - 1}
                    wide={widget.size === "wide"}
                    hasSettings={hasSettings}
                    settingsOpen={settingsFor === widget.id}
                    onMove={(by) => move(widget, index, by)}
                    onSize={() => toggleSize(widget)}
                    onSettings={() => setSettingsFor((open) => (open === widget.id ? null : widget.id))}
                    onRemove={() => remove(widget, index)}
                  />
                  {settingsFor === widget.id && (
                    <WidgetSettingsForm
                      projectId={projectId}
                      widget={widget}
                      onApply={(settings) => applySettings(widget, settings)}
                      onClose={() => {
                        setSettingsFor(null);
                        focusAfter.current = { id: widget.id, tool: "settings" };
                      }}
                    />
                  )}
                </>
              }
            />
          );
        })}
      </div>
      {widgets.length === 0 && <p className="muted">No widgets in this layout. Add one, or reset to the default.</p>}
    </>
  );
}
```

- [ ] **Step 7: Put Customise and the editor on the page**

Replace `dashboard/src/pages/OverviewPage.tsx` with:

```tsx
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { LayoutMode } from "../api/overviewLayout";
import ErrorBanner from "../components/ErrorBanner";
import PageHeader from "../components/PageHeader";
import { SkeletonCard, SkeletonStatus } from "../components/Skeleton";
import CustomiseMenu from "../overview/CustomiseMenu";
import OverviewEditor from "../overview/OverviewEditor";
import { type EditSession, startSession } from "../overview/session";
import { BUILTIN_DEFAULT } from "../overview/templates";
import { useLatestRun } from "../overview/useLatestRun";
import { useOverviewLayout } from "../overview/useOverviewLayout";
import WidgetGrid from "../overview/WidgetGrid";

/** "What is broken now" in one screen, as widgets (spec 2026-10-11): the personal layout, else the project default,
 *  else the built-in four cards. Customise edits a draft of it (OverviewEditor). */
export default function OverviewPage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const { runs, latest } = useLatestRun(id);
  const { query: layout } = useOverviewLayout(id);
  const [session, setSession] = useState<EditSession | null>(null);
  // A new key for every start, so Reload after a conflict always begins a fresh draft
  const [sessionKey, setSessionKey] = useState(0);
  const customiseRef = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);

  // Leaving edit mode hands focus back to Customise
  useEffect(() => {
    if (session === null && wasEditing.current) customiseRef.current?.focus();
    wasEditing.current = session !== null;
  }, [session]);

  function begin(mode: LayoutMode, openSettingsFor: string | null = null) {
    if (!layout.data) return;
    setSession(startSession(layout.data, mode, openSettingsFor));
    setSessionKey((k) => k + 1);
  }

  async function reload() {
    if (session === null) return;
    const fresh = await layout.refetch();
    if (fresh.data) {
      setSession(startSession(fresh.data, session.mode));
      setSessionKey((k) => k + 1);
    }
  }

  // Customise needs the stored layout (plan Ruling 30) and a project with runs
  const canCustomise = session === null && layout.data !== undefined && latest !== undefined;

  function body() {
    if (runs.error != null) return <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} />;
    if (runs.isPending || layout.isPending) {
      return (
        <SkeletonStatus label="Loading overview…" className="overview-grid">
          <SkeletonCard className="wide" height={96} />
          <SkeletonCard height={120} />
          <SkeletonCard height={120} />
          <SkeletonCard height={120} />
        </SkeletonStatus>
      );
    }
    if (!latest) return <NoRunsYet projectId={id} />;
    if (session !== null) {
      return (
        <OverviewEditor key={sessionKey} projectId={id} session={session} onClose={() => setSession(null)} onReload={() => void reload()} />
      );
    }
    return (
      <>
        {layout.error != null && <LayoutUnavailable onRetry={() => layout.refetch()} />}
        <WidgetGrid projectId={id} layout={layout.data?.effective ?? BUILTIN_DEFAULT} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Overview"
        actions={canCustomise ? <CustomiseMenu canManage={false} triggerRef={customiseRef} onPick={(mode) => begin(mode)} /> : undefined}
      />
      {body()}
    </>
  );
}

/** Shown instead of the widgets until the first upload (spec §2.7). */
function NoRunsYet({ projectId }: { projectId: number }) {
  return (
    <div className="card">
      <h2>No runs yet</h2>
      <p className="muted">
        Results appear here after the first upload from CI. Create an API key, paste the CI
        snippet into your pipeline, and the next build reports its tests.
      </p>
      <Link className="link-arrow" to={`/projects/${projectId}/settings`}>Set up an API key and CI <ArrowRight size={14} aria-hidden="true" /></Link>
    </div>
  );
}

/** The layout could not be read: the built-in default is shown under this banner (plan Ruling 30). */
function LayoutUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="error-banner" role="alert">
      <span>Your Overview layout could not be loaded, so the default is shown.</span>
      <button type="button" onClick={onRetry}>Retry</button>
    </div>
  );
}
```

In `dashboard/src/index.css`, replace:

```css
.overview-grid h2 a:hover { text-decoration: underline; }
```

with:

```css
.overview-grid h2 a:hover { text-decoration: underline; }
/* Overview edit mode (DESIGN.md "Overview Widgets and Edit Mode") */
.overview-edit-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) var(--space-4); margin-bottom: var(--space-4); background: var(--accent-soft); border: 1px solid var(--border-strong); border-radius: var(--radius); }
.overview-edit-bar .error-banner { flex-basis: 100%; }
.overview-edit-title { margin: 0; font-weight: 600; }
.overview-edit-title:focus { outline: none; }
.overview-note { margin: 0; font-size: 13px; color: var(--text-secondary); }
.widget-toolbar { display: flex; justify-content: flex-end; gap: var(--space-1); margin-bottom: var(--space-2); }
button.widget-tool { min-width: 28px; min-height: 28px; padding: 4px; justify-content: center; }
@media (pointer: coarse) { button.widget-tool { min-width: 44px; min-height: 44px; } }
.widget-settings { display: flex; flex-wrap: wrap; align-items: flex-end; gap: var(--space-3); padding: var(--space-3); margin-bottom: var(--space-3); background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-sm); }
.widget-setting { display: flex; flex-direction: column; gap: var(--space-1); font-size: 13px; }
.add-widget-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--space-3); }
.add-widget-list li { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-3); padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-sm); }
.add-widget-list p { margin: var(--space-1) 0 0; font-size: 13px; }
.customise-menu { position: relative; }
.customise-popup { position: absolute; inset-inline-end: 0; top: calc(100% + 6px); z-index: 50; min-width: 240px; list-style: none; margin: 0; padding: var(--space-1); background: var(--surface-1); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: var(--shadow-2); }
```

- [ ] **Step 8: Run them to verify they pass**

Run: `cd dashboard && npx vitest run src/components/ConfirmButton.test.tsx src/overview src/pages/OverviewPage.test.tsx src/pages/BranchesPage.test.tsx src/pages/UnsavedChanges.test.tsx`
Expected: PASS.

- [ ] **Step 9: Lint, typecheck, build**

Run: `cd dashboard && npm run lint && npm run typecheck && npm run build`
Expected: exit 0.

- [ ] **Step 10: Document edit mode**

In `DESIGN.md`, with the Edit tool, replace:

```
- **Overview grid:** `auto-fit, minmax(260px, 1fr)` with a 16px gap. A *wide* card spans the full row; the latest run gets this.
```

with:

```
- **Overview grid:** `auto-fit, minmax(260px, 1fr)` with a 16px gap. A *wide* widget spans the full row (the latest run by default); below two columns wide and normal look the same and widgets stack in layout order.
```

and replace:

```
### Page Header
Every signed-in page starts with
```

with:

```
### Overview Widgets and Edit Mode
The Overview is a grid of widgets (spec `docs/superpowers/specs/2026-10-11-customisable-overview-design.md`). Each widget is a card whose `h2` is a link to its full view with the same filters. It loads, fails and retries on its own (Error Banner with Retry); a widget that throws while rendering shows "This widget failed to load" with Retry in its own card while the rest of the page keeps working. A widget's code loads only when a layout places it. Widgets reuse the query of the screen that owns the figure, under the same key (as KPI Tiles do).

- **Customise** (page header, every role) opens edit mode. A bar in Cyan Wash with a Hairline Strong border reads "Editing your Overview" and holds **Add widget**, **Reset to project default**, **Cancel** and **Save** (primary, enabled once something changed). The page shows the draft; nothing is stored until Save. Focus moves to the bar's title on entry and back to Customise on exit.
- **Widget toolbar** (edit mode only): ghost icon buttons, 28px (44px under `pointer: coarse`), each named for its widget: "Move Pass rate this week up", "Show Pass rate this week wide" (`aria-pressed`), "Pass rate this week settings" (only for a widget with settings), "Remove Pass rate this week". Settings open an inline form in the card (selects for rows, period, view and branch, a text field for the git author name) with Apply (primary) and Close; Escape closes it.
- **Focus and announcements:** a move keeps focus on the moved widget's button, or on the card itself when that button becomes disabled at an end; a removal moves focus to the next widget, or to Add widget; one polite live region says what changed ("Pass rate this week moved to position 2 of 4").
- **Add widget** opens a card listing every widget type with a one-line description and an Add button. At 24 widgets the buttons are disabled and the card says why.
- **Leaving:** Cancel with changes asks in place "Discard your changes?" (Discard in danger, Keep editing); navigating away or closing the tab uses the unsaved-changes guard.
- **Conflict:** when the same layout was saved elsewhere meanwhile, an alertdialog in the bar reads "Changed by <email> on <date> since you started" with Reload (focused) and Overwrite.
- **Default changed:** a muted note "The project default changed on <date>" beside Reset to project default, when the default is newer than the personal layout.

### Page Header
Every signed-in page starts with
```

In `docs/SETUP.md`, with the Edit tool, replace:

```
| **Overview** | Latest run, its failures grouped by cause, the pass rate this week, flaky tests in the last 14 days. | — |
```

with:

```
| **Overview** | Widgets; by default the latest run, its failures grouped by cause, the pass rate this week and flaky tests in the last 14 days. | **Customise** (every role): move, resize, remove and add widgets, change their settings, then **Save**. See [Customise the Overview](#customise-the-overview). |
```

and replace:

```
**Verify (4.4):** after two or more uploads, **Trends** shows points, and **Compare with previous
run** appears on the newer run.
```

with:

```
#### Customise the Overview

Every role can arrange their own Overview, per project: **Customise** in the Overview header opens
edit mode. Move widgets up or down, make them wide or normal, open a widget's settings (rows, period,
branch), remove it, or **Add widget**. The page shows your draft; nothing changes until **Save**.
**Reset to project default** puts the default back in the draft, and Save then removes your own
layout, so later changes to the default reach you again. **Cancel** discards the draft, asking first
when you changed something. If the same layout was saved elsewhere meanwhile, Save offers **Reload**
(start again from the stored layout) or **Overwrite**. A layout holds at most 24 widgets.

**Verify (4.4):** after two or more uploads, **Trends** shows points, and **Compare with previous
run** appears on the newer run.
```

- [ ] **Step 11: Commit**

```bash
git add dashboard/src/overview/session.ts dashboard/src/overview/session.test.ts dashboard/src/overview/WidgetToolbar.tsx dashboard/src/overview/WidgetSettingsForm.tsx dashboard/src/overview/AddWidgetPanel.tsx dashboard/src/overview/CustomiseMenu.tsx dashboard/src/overview/OverviewEditor.tsx dashboard/src/overview/OverviewEditor.test.tsx dashboard/src/components/ConfirmButton.tsx dashboard/src/components/ConfirmButton.test.tsx dashboard/src/lib/healthQueries.ts dashboard/src/pages/BranchesPage.tsx dashboard/src/pages/OverviewPage.tsx dashboard/src/index.css DESIGN.md docs/SETUP.md
git commit -m "feat(dashboard): Customise the Overview (draft editor, discard guard, conflicts, focus and announcements)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/session.ts dashboard/src/overview/session.test.ts dashboard/src/overview/WidgetToolbar.tsx dashboard/src/overview/WidgetSettingsForm.tsx dashboard/src/overview/AddWidgetPanel.tsx dashboard/src/overview/CustomiseMenu.tsx dashboard/src/overview/OverviewEditor.tsx dashboard/src/overview/OverviewEditor.test.tsx dashboard/src/components/ConfirmButton.tsx dashboard/src/components/ConfirmButton.test.tsx dashboard/src/lib/healthQueries.ts dashboard/src/pages/BranchesPage.tsx dashboard/src/pages/OverviewPage.tsx dashboard/src/index.css DESIGN.md docs/SETUP.md
```

---

### Task 14: Edit project default for owners and admins

**Files:**
- Test: `dashboard/src/overview/ProjectDefault.test.tsx`
- Modify: `dashboard/src/lib/useCanEdit.ts`, `dashboard/src/pages/OverviewPage.tsx`
- Docs: `DESIGN.md`, `docs/SETUP.md`, `README.md`

**Interfaces:**
- Consumes: `CustomiseMenu` (`canManage`), `OverviewEditor` project mode, `startSession(state, "project")` (Task 13); `getProject(projectId).my_role`.
- Produces: `useCanManage(projectId: number): boolean | undefined` in `src/lib/useCanEdit.ts` (mirrors `MANAGE_ROLES` = owner, admin).

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill and read DESIGN.md "Destructive Confirmation" and the "Overview Widgets and Edit Mode" section written in Task 13.

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/overview/ProjectDefault.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import type { StoredLayout } from "./catalog";
import { mockOverviewData, projectState, renderOverview } from "./testing";

const PUT_PROJECT = "/api/v1/projects/42/overview-layout/project";
const TEAM: StoredLayout = { schema: 1, widgets: [
  { id: "t1", type: "latest_run", size: "wide" }, { id: "t2", type: "failing_now", size: "normal", settings: { rows: 10 } },
] };
const MINE: StoredLayout = { schema: 1, widgets: [{ id: "m1", type: "flaky_count", size: "normal" }] };
const titles = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);

async function openProjectEditor() {
  await userEvent.click(await screen.findByRole("button", { name: "Customise", expanded: false }));
  await userEvent.click(screen.getByRole("button", { name: "Edit project default" }));
}

test.each(["member", "viewer", "billing_manager"])("a %s customises their own Overview only", async (role) => {
  mockOverviewData({ role });
  renderOverview();
  const customise = await screen.findByRole("button", { name: "Customise" });
  await waitFor(() => expect(customise).not.toHaveAttribute("aria-expanded"));
  await userEvent.click(customise);
  expect(await screen.findByText("Editing your Overview")).toBeInTheDocument();
  expect(screen.queryByText("Edit project default")).not.toBeInTheDocument();
});

test.each(["owner", "admin"])("an %s can choose to edit the project default", async (role) => {
  mockOverviewData({ role, layout: projectState(TEAM) });
  renderOverview();
  await openProjectEditor();
  expect(await screen.findByText("Editing the project default · everyone without a personal layout sees this")).toBeInTheDocument();
  expect(screen.getByText(/^Last changed by ada@example\.com on /)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reset to built-in default" })).toBeInTheDocument();
});

test("saving the project default asks first, then sends the default's version", async () => {
  mockOverviewData({ role: "owner", layout: projectState(TEAM) });
  const sent: { version: number; layout: StoredLayout }[] = [];
  server.use(http.put(PUT_PROJECT, async ({ request }) => {
    const body = (await request.json()) as { version: number; layout: StoredLayout };
    sent.push(body);
    return HttpResponse.json({ layout: body.layout, version: 3, updated_by: 7, updated_at: "2026-10-11T10:00:00Z" });
  }));
  renderOverview();
  await openProjectEditor();
  await userEvent.click(await screen.findByRole("button", { name: "Remove Latest run" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByText("Everyone without a personal layout will see this layout.")).toBeInTheDocument();
  expect(sent).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "Save for everyone" }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0].version).toBe(2);
  expect(sent[0].layout.widgets.map((w) => w.id)).toEqual(["t2"]);
});

test("an owner with a personal layout edits the project default, not their own", async () => {
  mockOverviewData({ role: "owner", layout: {
    ...projectState(TEAM), effective: MINE, source: "personal", personal: { version: 1, updated_at: "2026-10-10T10:00:00Z" },
  } });
  renderOverview();
  expect(await screen.findByRole("region", { name: "Flaky tests, last 14 days" })).toBeInTheDocument();
  await openProjectEditor();
  await waitFor(() => expect(titles()).toEqual(["Latest run", "Failing in latest run"]));
});

test("Reset to built-in default then Save deletes the project default", async () => {
  mockOverviewData({ role: "admin", layout: projectState(TEAM) });
  const deleted: string[] = [];
  server.use(http.delete("/api/v1/projects/42/overview-layout/:mode", ({ params }) => {
    deleted.push(String(params.mode));
    return new HttpResponse(null, { status: 204 });
  }));
  renderOverview();
  await openProjectEditor();
  await userEvent.click(await screen.findByRole("button", { name: "Reset to built-in default" }));
  expect(titles()).toEqual(["Latest run", "Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"]);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await userEvent.click(screen.getByRole("button", { name: "Save for everyone" }));
  await waitFor(() => expect(deleted).toEqual(["project"]));
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/overview/ProjectDefault.test.tsx`
Expected: the member/viewer/billing_manager cases pass; the owner and admin cases FAIL with `Unable to find an accessible element with the role "button" and name "Customise"` matching `expanded: false` (Customise is still a plain button).

- [ ] **Step 4: Offer the project default to owners and admins**

In `dashboard/src/lib/useCanEdit.ts`, append:

```ts

// Mirrors MANAGE_ROLES in project-service's api/deps.py
const MANAGE_ROLES = ["owner", "admin"];

/** Whether the signed-in person may manage this project (e.g. set its Overview default); undefined while the role loads. */
export function useCanManage(projectId: number): boolean | undefined {
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId) });
  return project.data == null ? undefined : MANAGE_ROLES.includes(project.data.my_role ?? "");
}
```

In `dashboard/src/pages/OverviewPage.tsx`, replace:

```tsx
import { SkeletonCard, SkeletonStatus } from "../components/Skeleton";
```

with:

```tsx
import { SkeletonCard, SkeletonStatus } from "../components/Skeleton";
import { useCanManage } from "../lib/useCanEdit";
```

replace:

```tsx
  const { query: layout } = useOverviewLayout(id);
  const [session, setSession] = useState<EditSession | null>(null);
```

with:

```tsx
  const { query: layout } = useOverviewLayout(id);
  const canManage = useCanManage(id);
  const [session, setSession] = useState<EditSession | null>(null);
```

and replace:

```tsx
        actions={canCustomise ? <CustomiseMenu canManage={false} triggerRef={customiseRef} onPick={(mode) => begin(mode)} /> : undefined}
```

with:

```tsx
        actions={canCustomise ? <CustomiseMenu canManage={canManage === true} triggerRef={customiseRef} onPick={(mode) => begin(mode)} /> : undefined}
```

- [ ] **Step 5: Run them to verify they pass**

Run: `cd dashboard && npx vitest run src/overview src/pages/OverviewPage.test.tsx`
Expected: PASS.

- [ ] **Step 6: Lint, typecheck, build**

Run: `cd dashboard && npm run lint && npm run typecheck && npm run build`
Expected: exit 0.

- [ ] **Step 7: Document the project default**

In `DESIGN.md`, with the Edit tool, replace:

```
- **Default changed:** a muted note "The project default changed on <date>" beside Reset to project default, when the default is newer than the personal layout.
```

with:

```
- **Default changed:** a muted note "The project default changed on <date>" beside Reset to project default, when the default is newer than the personal layout.
- **Edit project default** (owners and admins): Customise becomes a disclosure with "Customise your Overview" and "Edit project default". The bar reads "Editing the project default · everyone without a personal layout sees this" with "Last changed by <email> on <date>" under it, and its reset reads "Reset to built-in default". Save confirms in place ("Everyone without a personal layout will see this layout.", **Save for everyone**, **Back**); the confirm step is primary, not danger, because nothing is destroyed.
```

In `docs/SETUP.md`, with the Edit tool, replace:

```
(start again from the stored layout) or **Overwrite**. A layout holds at most 24 widgets.
```

with:

```
(start again from the stored layout) or **Overwrite**. A layout holds at most 24 widgets.

Owners and admins also set the **project default**, which everyone without a personal layout sees:
**Customise → Edit project default**. The bar says who changed it last; Save asks for confirmation;
**Reset to built-in default** goes back to the four standard cards.
```

and replace:

```
| **Overview** | Widgets; by default the latest run, its failures grouped by cause, the pass rate this week and flaky tests in the last 14 days. | **Customise** (every role): move, resize, remove and add widgets, change their settings, then **Save**. See [Customise the Overview](#customise-the-overview). |
```

with:

```
| **Overview** | Widgets; by default the latest run, its failures grouped by cause, the pass rate this week and flaky tests in the last 14 days. | **Customise** (every role): move, resize, remove and add widgets, change their settings, then **Save**. Owners and admins: **Edit project default**. See [Customise the Overview](#customise-the-overview). |
```

In `README.md`, with the Edit tool, replace:

```
- **Failure causes:** new, recurring and resolved failures, grouped by cause.
```

with:

```
- **Failure causes:** new, recurring and resolved failures, grouped by cause.
- **Customisable Overview:** each person arranges their own Overview from widgets, and owners and admins
  set the project's default layout.
```

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/overview/ProjectDefault.test.tsx dashboard/src/lib/useCanEdit.ts dashboard/src/pages/OverviewPage.tsx DESIGN.md docs/SETUP.md README.md
git commit -m "feat(dashboard): owners and admins edit the Overview project default" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/ProjectDefault.test.tsx dashboard/src/lib/useCanEdit.ts dashboard/src/pages/OverviewPage.tsx DESIGN.md docs/SETUP.md README.md
```

---

### Task 15: Phase 2 gate

**Files:** none new (fixes only, in the files of Tasks 8–14).

**Interfaces:** Consumes everything in Phases 1–2; produces a pushed `master`.

- [ ] **Step 1:** Every Python suite serially and the collector (Task 7 Step 1). Expected: all green.
- [ ] **Step 2:** `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build && node --test ../templates/github/qeos-run.test.mjs`. Expected: all green; the build lists the four widget chunks.
- [ ] **Step 3:** `bash monitoring/check.sh`; `docker build -t qeos/gateway:ci gateway && docker run --rm qeos/gateway:ci nginx -t`. Expected: `monitoring: all checks passed`; `test is successful`.
- [ ] **Step 4:** The full stack and the smoke (this also builds the dashboard image with the copied catalogue file):

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```
Expected: `all gateway checks passed`.

- [ ] **Step 5:** By hand at `https://localhost:8443`, signed in as an owner of a project with runs: the Overview shows the four cards; Customise → move Flaky tests up, make it wide, Save, reload the page: the layout stays. Customise → Edit project default → Save for everyone. Sign in as a member of the same organization in another browser: they see the project default and a plain Customise. Then `docker compose down` (never `-v`).
- [ ] **Step 6:** `git ls-files -s scripts/smoke_gateway.sh` shows `100755`; `git status --short` shows no modified file of this plan; `git push origin master`.

---

# Phase 3 — Catalogue

Useful by itself: the ten further widgets, the three templates, the empty-branch state, and the documentation of the whole feature.

### Task 16: Pass-rate trend, the empty-branch state, and Settings from the live page

**Files:**
- Create: `dashboard/src/overview/EmptyBranch.tsx`, `dashboard/src/overview/widgets/passRateTrend.ts`, `dashboard/src/overview/widgets/PassRateTrendWidget.tsx`
- Test: `dashboard/src/overview/widgets/trendWidgets.test.tsx`, `dashboard/src/overview/widgets/registry.test.ts`
- Modify: `dashboard/src/overview/widgets/registry.ts`, `dashboard/src/overview/widgets/PassRateWeekWidget.tsx`, `dashboard/src/lib/healthQueries.ts`, `dashboard/src/pages/TrendsPage.tsx`, `dashboard/src/pages/OverviewPage.tsx`, `dashboard/src/index.css`

**Interfaces:**
- Consumes: `WidgetProps.onOpenSettings`, `WidgetGrid.onOpenSettings`, `startSession(state, "personal", widgetId)` (Tasks 11, 13); `getTrends`, `TrendBucket`, `formatPassRate`; `formatTick`, `formatPointLabel` (`src/lib/chartFormat.ts`).
- Produces:
  - `src/overview/EmptyBranch.tsx`: default export, props `{ branch: string; days?: number; onOpenSettings?: () => void }`: "No runs on <branch> in the last N days" (or "No runs on <branch>" without days) and a **Change settings** button;
  - `src/lib/healthQueries.ts`: `trendsViewQuery(projectId: number, tz: string, days: number, bucket: TrendBucket, branch: string, environment = "")` (the Trends view's key `["trends", id, days, bucket, branch, environment]`; TrendsPage uses it too);
  - `src/overview/widgets/passRateTrend.ts`: `TREND_DAYS: Record<TrendBucket, number>` (day 30, week 90, month 90; Ruling 15), `passRateTrend: WidgetDefinition`;
  - the live page opens edit mode on a widget's settings when its empty-branch button is pressed.

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill and read DESIGN.md "Chart Series", "Chart Textures", "Data Tables" and "Error Banner" (empty states are plain sentences).

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/overview/widgets/trendWidgets.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { mockOverviewData, personalState, renderOverview } from "../testing";

const bucket = (date: string, runs: number, pass_rate: number | null) => ({
  date, runs, total: runs * 10, passed: 0, failed: 0, errored: 0, skipped: 0, pass_rate, avg_run_duration_ms: 1, max_run_duration_ms: 1,
});
const WEEKS = { tz: "UTC", bucket: "week", days: [bucket("2026-09-21", 10, 0.833), bucket("2026-09-28", 12, 0.958)] };
const NO_RUNS = { tz: "UTC", bucket: "day", days: [bucket("2026-10-03", 0, null), bucket("2026-10-04", 0, null)] };

function trendsAsked(answer: object) {
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/analytics/trends", ({ request }) => {
    asked.push(new URL(request.url).searchParams);
    return HttpResponse.json(answer);
  }));
  return asked;
}

test("Pass-rate trend asks the Trends view's query for weekly buckets over 90 days and links to that view", async () => {
  mockOverviewData({ layout: personalState({ id: "t", type: "pass_rate_trend", size: "wide" }) });
  const asked = trendsAsked(WEEKS);
  renderOverview();
  const heading = await screen.findByRole("heading", { name: "Pass-rate trend" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/trends?days=90&bucket=week");
  expect(await screen.findByText(/Pass rate per week, from 83\.3% to 95\.8%/)).toBeInTheDocument();
  expect(screen.getByText(/Latest week: 95\.8%/)).toBeInTheDocument();
  await waitFor(() => expect(asked.length).toBeGreaterThan(0));
  expect(asked[0].get("days")).toBe("90");
  expect(asked[0].get("bucket")).toBe("week");
  expect(asked[0].get("branch")).toBeNull();
});

test("Pass-rate trend shows its error with Retry inside its own card", async () => {
  mockOverviewData({ layout: personalState({ id: "t", type: "pass_rate_trend", size: "wide" }) });
  server.use(http.get("/api/v1/projects/42/analytics/trends", () => HttpResponse.json({ detail: "Trends are down" }, { status: 500 })));
  renderOverview();
  const card = await screen.findByRole("region", { name: "Pass-rate trend" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Trends are down");
  expect(within(card).getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("a branch without runs says so with its settings button, which opens that widget's settings", async () => {
  mockOverviewData({ layout: personalState({ id: "t", type: "pass_rate_trend", size: "normal", settings: { granularity: "day", branch: "release" } }) });
  const asked = trendsAsked(NO_RUNS);
  renderOverview();
  expect(await screen.findByText("No runs on release in the last 30 days")).toBeInTheDocument();
  expect(asked[0].get("branch")).toBe("release");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Change settings" }));
  expect(await screen.findByText("Editing your Overview")).toBeInTheDocument();
  expect(screen.getByRole("form", { name: "Pass-rate trend settings" })).toBeInTheDocument();
});

test("Pass rate this week on a branch without runs says so instead of showing nothing", async () => {
  mockOverviewData({ layout: personalState({ id: "p", type: "pass_rate_week", size: "normal", settings: { branch: "release" } }) });
  trendsAsked({ tz: "UTC", bucket: "week", days: [] });
  renderOverview();
  expect(await screen.findByText("No runs on release in the last 14 days")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Change settings" })).toBeInTheDocument();
});
```

In `dashboard/src/overview/widgets/registry.test.ts`, replace:

```ts
  "pass_rate_trend", "failure_causes", "regressions", "recent_runs", "branch_health", "slowest_tests", "coverage",
```

with:

```ts
  "failure_causes", "regressions", "recent_runs", "branch_health", "slowest_tests", "coverage",
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/overview/widgets/trendWidgets.test.tsx src/overview/widgets/registry.test.ts`
Expected: FAIL: the registry test lists `pass_rate_trend` as missing; no heading "Pass-rate trend" (the type is skipped as unknown); no "No runs on release in the last 14 days".

- [ ] **Step 4: Share the Trends view's query**

In `dashboard/src/lib/healthQueries.ts`, replace:

```ts
import { getBranches, getFlaky, getTrends } from "../api/analytics";
```

with:

```ts
import { type TrendBucket, getBranches, getFlaky, getTrends } from "../api/analytics";

/** The Trends view's own query; its key holds no time zone (the browser's zone is the same for both). The Overview's
 *  Pass-rate trend asks it with the view's day choices, so the two share one answer. */
export const trendsViewQuery = (projectId: number, tz: string, days: number, bucket: TrendBucket, branch: string, environment = "") => ({
  queryKey: ["trends", projectId, days, bucket, branch, environment] as const,
  queryFn: () => getTrends(projectId, { days, tz, bucket, branch: branch || undefined, environment: environment || undefined }),
});
```

In `dashboard/src/pages/TrendsPage.tsx`, replace:

```tsx
import { TrendBucket, formatDuration, formatPassRate, getTrends } from "../api/analytics";
```

with:

```tsx
import { TrendBucket, formatDuration, formatPassRate } from "../api/analytics";
import { trendsViewQuery } from "../lib/healthQueries";
```

and replace:

```tsx
  const query = useQuery({
    queryKey: ["trends", id, days, bucket, branch, environment],
    queryFn: () =>
      getTrends(id, { days, tz, bucket, branch: branch || undefined, environment: environment || undefined }),
  });
```

with:

```tsx
  const query = useQuery(trendsViewQuery(id, tz, days, bucket, branch, environment));
```

- [ ] **Step 5: Write the empty-branch state and the widget**

Create `dashboard/src/overview/EmptyBranch.tsx`:

```tsx
import { SlidersHorizontal } from "lucide-react";

interface Props {
  branch: string;
  /** The widget's period; without one the sentence names only the branch. */
  days?: number;
  onOpenSettings?: () => void;
}

/** A widget set to a branch with no runs in its period (spec §2.8): said plainly, never an error, with the way out. */
export default function EmptyBranch({ branch, days, onOpenSettings }: Props) {
  return (
    <div className="overview-empty">
      <p className="muted">{days === undefined ? `No runs on ${branch}` : `No runs on ${branch} in the last ${days} days`}</p>
      {onOpenSettings && (
        <button type="button" onClick={onOpenSettings}><SlidersHorizontal size={15} aria-hidden="true" /> Change settings</button>
      )}
    </div>
  );
}
```

Create `dashboard/src/overview/widgets/passRateTrend.ts`:

```ts
import { lazy } from "react";
import type { TrendBucket } from "../../api/analytics";
import { ALL } from "../catalog";
import type { WidgetDefinition } from "./types";

/** Days asked per view: the Trends view's own choices (plan Ruling 15), so the title link opens the same chart. */
export const TREND_DAYS: Record<TrendBucket, number> = { day: 30, week: 90, month: 90 };

export const passRateTrend: WidgetDefinition = {
  type: "pass_rate_trend",
  title: "Pass-rate trend",
  description: "The pass rate per day, week or month, on all branches or one.",
  defaultSize: "wide",
  settings: ["granularity", "branch"],
  defaults: { granularity: "week", branch: ALL },
  Component: lazy(() => import("./PassRateTrendWidget")),
  link: (projectId, settings) => {
    const bucket = settings.granularity ?? "week";
    const params = new URLSearchParams({ days: String(TREND_DAYS[bucket]), bucket });
    if (settings.branch && settings.branch !== ALL) params.set("branch", settings.branch);
    return `/projects/${projectId}/trends?${params}`;
  },
};
```

Create `dashboard/src/overview/widgets/PassRateTrendWidget.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatPassRate } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import { formatPointLabel, formatTick } from "../../lib/chartFormat";
import { trendsViewQuery } from "../../lib/healthQueries";
import { ALL } from "../catalog";
import EmptyBranch from "../EmptyBranch";
import { TREND_DAYS } from "./passRateTrend";
import type { WidgetProps } from "./types";

const axisTick = { fill: "var(--text-secondary)", fontSize: 12 } as const;
const tooltipStyle = { background: "var(--surface-1)", border: "1px solid var(--border)", borderRadius: 6 } as const;

/** The pass rate per bucket, as the Trends view computes it; a line with markers, summarised for assistive tech. */
export default function PassRateTrendWidget({ projectId, settings, size, heading, onOpenSettings }: WidgetProps) {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const bucket = settings.granularity ?? "week";
  const branch = settings.branch ?? ALL;
  const days = TREND_DAYS[bucket];
  const query = useQuery(trendsViewQuery(projectId, tz, days, bucket, branch === ALL ? "" : branch));
  const buckets = query.data?.days ?? [];
  const noRuns = query.data !== undefined && buckets.every((d) => d.runs === 0);
  const rated = buckets.filter((d) => d.pass_rate !== null);
  const points = buckets.map((d) => ({ date: d.date, ratePct: d.pass_rate === null ? null : d.pass_rate * 100 }));
  const last = rated[rated.length - 1];
  const summary = rated.length === 0 ? "" :
    `Pass rate per ${bucket}, from ${formatPassRate(rated[0].pass_rate)} to ${formatPassRate(last.pass_rate)}.`;
  return (
    <>
      {heading}
      {query.isPending && <SkeletonStatus label="Loading pass-rate trend…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {noRuns && (branch === ALL
        ? <p className="muted">No runs in the last {days} days.</p>
        : <EmptyBranch branch={branch} days={days} onOpenSettings={onOpenSettings} />)}
      {query.data && !noRuns && (
        <>
          <figure className="chart-figure">
            <figcaption className="sr-only">{summary}</figcaption>
            <ResponsiveContainer width="100%" height={size === "wide" ? 220 : 160}>
              <LineChart data={points} margin={{ left: 0, right: 8, top: 8 }} accessibilityLayer>
                <CartesianGrid stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(v: string) => formatTick(v, bucket)} stroke="var(--text-muted)" tick={axisTick} />
                <YAxis domain={[0, 100]} unit="%" width={44} stroke="var(--text-muted)" tick={axisTick} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelFormatter={(v) => formatPointLabel(String(v), bucket)}
                  formatter={(v) => [`${Number(v).toFixed(1)}%`, "Pass rate"]}
                />
                <Line type="monotone" dataKey="ratePct" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </figure>
          {last && <p className="muted">Latest {bucket}: {formatPassRate(last.pass_rate)}</p>}
        </>
      )}
    </>
  );
}
```

In `dashboard/src/overview/widgets/registry.ts`, replace:

```ts
import type { WidgetDefinition } from "./types";
```

with:

```ts
import { passRateTrend } from "./passRateTrend";
import type { WidgetDefinition } from "./types";
```

and replace:

```ts
  flaky_count: flakyCount,
};
```

with:

```ts
  flaky_count: flakyCount,
  pass_rate_trend: passRateTrend,
};
```

- [ ] **Step 6: Give Pass rate this week the empty-branch state**

In `dashboard/src/overview/widgets/PassRateWeekWidget.tsx`, replace:

```tsx
import { ALL } from "../catalog";
```

with:

```tsx
import { ALL } from "../catalog";
import EmptyBranch from "../EmptyBranch";
```

replace:

```tsx
export default function PassRateWeekWidget({ projectId, settings, heading }: WidgetProps) {
```

with:

```tsx
export default function PassRateWeekWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
```

replace:

```tsx
  const lastWeek = buckets.length > 1 ? buckets[buckets.length - 2] : undefined;
```

with:

```tsx
  const lastWeek = buckets.length > 1 ? buckets[buckets.length - 2] : undefined;
  // A chosen branch with no runs in the two weeks is said, never left blank (spec §2.8)
  const emptyBranch = branch !== ALL && weeks.data !== undefined && buckets.every((b) => b.runs === 0);
```

and replace:

```tsx
      {thisWeek && (
        <>
          <div className="stat-big">{formatPassRate(thisWeek.pass_rate)}</div>
```

with:

```tsx
      {emptyBranch && <EmptyBranch branch={branch} days={14} onOpenSettings={onOpenSettings} />}
      {!emptyBranch && thisWeek && (
        <>
          <div className="stat-big">{formatPassRate(thisWeek.pass_rate)}</div>
```

- [ ] **Step 7: Let the live page open a widget's settings**

In `dashboard/src/pages/OverviewPage.tsx`, replace:

```tsx
        <WidgetGrid projectId={id} layout={layout.data?.effective ?? BUILTIN_DEFAULT} />
```

with:

```tsx
        <WidgetGrid
          projectId={id}
          layout={layout.data?.effective ?? BUILTIN_DEFAULT}
          onOpenSettings={(widgetId) => begin("personal", widgetId)}
        />
```

In `dashboard/src/index.css`, replace:

```css
.customise-menu { position: relative; }
```

with:

```css
.customise-menu { position: relative; }
.overview-empty { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-2); }
```

- [ ] **Step 8: Run them to verify they pass**

Run: `cd dashboard && npx vitest run src/overview src/pages/OverviewPage.test.tsx src/pages/TrendsPage.test.tsx`
Expected: PASS.

- [ ] **Step 9: Lint, typecheck**

Run: `cd dashboard && npm run lint && npm run typecheck`
Expected: exit 0.

- [ ] **Step 10: Commit**

```bash
git add dashboard/src/overview/EmptyBranch.tsx dashboard/src/overview/widgets/passRateTrend.ts dashboard/src/overview/widgets/PassRateTrendWidget.tsx dashboard/src/overview/widgets/trendWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/overview/widgets/PassRateWeekWidget.tsx dashboard/src/lib/healthQueries.ts dashboard/src/pages/TrendsPage.tsx dashboard/src/pages/OverviewPage.tsx dashboard/src/index.css
git commit -m "feat(dashboard): Pass-rate trend widget and the empty-branch state" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/EmptyBranch.tsx dashboard/src/overview/widgets/passRateTrend.ts dashboard/src/overview/widgets/PassRateTrendWidget.tsx dashboard/src/overview/widgets/trendWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/overview/widgets/PassRateWeekWidget.tsx dashboard/src/lib/healthQueries.ts dashboard/src/pages/TrendsPage.tsx dashboard/src/pages/OverviewPage.tsx dashboard/src/index.css
```

---

### Task 17: Report widgets asking for their own section: Failure causes, Regressions and flips

**Files:**
- Create: `dashboard/src/overview/reportWidget.ts`, `dashboard/src/overview/widgets/failureCauses.ts`, `dashboard/src/overview/widgets/FailureCausesWidget.tsx`, `dashboard/src/overview/widgets/regressions.ts`, `dashboard/src/overview/widgets/RegressionsWidget.tsx`
- Test: `dashboard/src/overview/widgets/reportWidgets.test.tsx`, `dashboard/src/overview/widgets/registry.test.ts`
- Modify: `dashboard/src/overview/widgets/registry.ts`

**Interfaces:**
- Consumes: `computeGate`, `useReportSection`, `REPORT_STALE_MS` (`src/pages/report/useReportRequest.ts`); `ALL_BRANCHES`, `ReportFilters`, `addDays`, `todayIn` (`src/pages/report/useReportFilters.ts`); `ReportSectionName` (`src/api/report.ts`); `EmptyBranch` (Task 16); `formatDay` (Task 10).
- Produces, in `src/overview/reportWidget.ts`: `reportFilters(period: number, branch: string, today: string): ReportFilters`; `useWidgetReport(projectId: number, section: ReportSectionName, period: number, branch: string): UseQueryResult<Report>` (the Report's own key `["report", projectId, section, {filters}, null]`, `sections: [section]`; refetched by `newRunStaleKeys`, not polled); `reportLink(projectId: number, period: number, branch: string, anchor: string): string` (Ruling 16).

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill and read DESIGN.md "Report: Failure Causes and Regressions" and "Status Dot and Badges".

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/overview/widgets/reportWidgets.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { addDays } from "../../pages/report/useReportFilters";
import { CAUSES_REPORT, REGRESSIONS_REPORT, emptyReport } from "../../pages/report/testFixtures";
import { mockOverviewData, personalState, renderOverview } from "../testing";

type ReportBody = { from: string; to: string; branch: string | null; sections: string[] };

function reportAsked(answer: (sections: string[]) => object) {
  const bodies: ReportBody[] = [];
  server.use(http.post("/api/v1/projects/42/analytics/report", async ({ request }) => {
    const body = (await request.json()) as ReportBody;
    bodies.push(body);
    return HttpResponse.json(answer(body.sections));
  }));
  return bodies;
}

test("Failure causes asks only for its section over the last 30 days on every branch", async () => {
  mockOverviewData({ layout: personalState({ id: "c", type: "failure_causes", size: "normal" }) });
  const bodies = reportAsked(() => CAUSES_REPORT);
  renderOverview();
  expect(await screen.findByText(/2124 failures from 37 causes/)).toBeInTheDocument();
  expect(screen.getByText(/1 new · 2 recurring among the top 3 · 1 resolved/)).toBeInTheDocument();
  expect(screen.getByText("TimeoutError: locator('#pay-button') after 30000 ms")).toBeInTheDocument();
  expect(screen.getByText("New")).toBeInTheDocument();
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].sections).toEqual(["failure_causes"]);
  expect(bodies[0].branch).toBeNull();
  expect(bodies[0].from).toBe(addDays(bodies[0].to, -29));
  const heading = screen.getByRole("heading", { name: "Failure causes" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-causes");
});

test("Regressions and flips counts what started failing, what was fixed and the flips, and lists the newly failing", async () => {
  mockOverviewData({ layout: personalState({ id: "r", type: "regressions", size: "normal", settings: { period: 7, branch: "main", rows: 5 } }) });
  const bodies = reportAsked(() => REGRESSIONS_REPORT);
  renderOverview();
  expect(await screen.findByText("9 newly failing · 5 fixed · 51 flips")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "pays" })).toHaveAttribute("href", `/projects/42/tests/${"pays".padEnd(64, "0")}`);
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].sections).toEqual(["regressions"]);
  expect(bodies[0].branch).toBe("main");
  expect(bodies[0].from).toBe(addDays(bodies[0].to, -6));
  const heading = screen.getByRole("heading", { name: "Regressions and flips" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/report?period=7&branch=main#report-regressions");
});

test("two identical report widgets cost one request", async () => {
  mockOverviewData({ layout: personalState(
    { id: "a", type: "failure_causes", size: "normal" },
    { id: "b", type: "failure_causes", size: "normal" },
  ) });
  const bodies = reportAsked(() => CAUSES_REPORT);
  renderOverview();
  expect(await screen.findAllByText(/2124 failures from 37 causes/)).toHaveLength(2);
  expect(bodies).toHaveLength(1);
});

test("a report widget on a branch without runs says so; a failing one shows its error with Retry", async () => {
  mockOverviewData({ layout: personalState(
    { id: "c", type: "failure_causes", size: "normal", settings: { period: 14, branch: "release" } },
    { id: "r", type: "regressions", size: "normal" },
  ) });
  server.use(http.post("/api/v1/projects/42/analytics/report", async ({ request }) => {
    const body = (await request.json()) as ReportBody;
    return body.sections[0] === "failure_causes"
      ? HttpResponse.json(emptyReport())
      : HttpResponse.json({ detail: "Report is down" }, { status: 500 });
  }));
  renderOverview();
  expect(await screen.findByText("No runs on release in the last 14 days")).toBeInTheDocument();
  const regressions = screen.getByRole("region", { name: "Regressions and flips" });
  expect(await within(regressions).findByRole("alert")).toHaveTextContent("Report is down");
  expect(within(regressions).getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
```

In `dashboard/src/overview/widgets/registry.test.ts`, replace:

```ts
  "failure_causes", "regressions", "recent_runs", "branch_health", "slowest_tests", "coverage",
```

with:

```ts
  "recent_runs", "branch_health", "slowest_tests", "coverage",
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/overview/widgets/reportWidgets.test.tsx src/overview/widgets/registry.test.ts`
Expected: FAIL: no heading "Failure causes" (unknown type, skipped); the registry test lists `failure_causes` and `regressions` as missing.

- [ ] **Step 4: Write the report helper**

Create `dashboard/src/overview/reportWidget.ts`:

```ts
import type { ReportSectionName } from "../api/report";
import { ALL_BRANCHES, type ReportFilters, addDays, todayIn } from "../pages/report/useReportFilters";
import { computeGate, useReportSection } from "../pages/report/useReportRequest";
import { ALL } from "./catalog";

// A widget filters by period and branch only, so the Report's case-areas and Play-URL inputs are never needed
const NOT_NEEDED = { data: undefined, error: null, refetch: () => undefined };

const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/** The Report's filters for a widget: the last `period` days up to today, every branch or one. */
export function reportFilters(period: number, branch: string, today: string): ReportFilters {
  return {
    preset: null, from: addDays(today, -(period - 1)), to: today, days: period,
    branch: branch === ALL ? ALL_BRANCHES : branch, environment: "", ci: "", origin: "any", area: null, suite: null,
  };
}

/** One Report section for a widget (spec §4): `sections: [section]` under the Report's own query key, so the Report page
 *  with the same period and branch reuses the answer. Not polled; a new latest run invalidates it (newRunStaleKeys). */
export function useWidgetReport(projectId: number, section: ReportSectionName, period: number, branch: string) {
  const tz = browserZone();
  const gate = computeGate({
    filters: reportFilters(period, branch, todayIn(tz)), tz, defaultBranch: null, caseAreas: NOT_NEEDED, runUrls: NOT_NEEDED,
  });
  return useReportSection(projectId, gate, section);
}

/** The Report with the same period and branch, at the widget's section (plan Ruling 16). */
export function reportLink(projectId: number, period: number, branch: string, anchor: string): string {
  const params = new URLSearchParams();
  if (period === 7 || period === 30) {
    params.set("period", String(period));
  } else {
    const today = todayIn(browserZone());
    params.set("from", addDays(today, -(period - 1)));
    params.set("to", today);
  }
  params.set("branch", branch === ALL ? ALL_BRANCHES : branch);
  return `/projects/${projectId}/report?${params}#${anchor}`;
}
```

- [ ] **Step 5: Write the two widgets**

Create `dashboard/src/overview/widgets/FailureCausesWidget.tsx`:

```tsx
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import { ALL } from "../catalog";
import EmptyBranch from "../EmptyBranch";
import { useWidgetReport } from "../reportWidget";
import type { WidgetProps } from "./types";

const SHOWN = 5;

/** The Report's failure causes for the period: how many, new against recurring, resolved, and the top causes. */
export default function FailureCausesWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
  const period = settings.period ?? 30;
  const branch = settings.branch ?? ALL;
  const query = useWidgetReport(projectId, "failure_causes", period, branch);
  const section = query.data?.failure_causes;
  const emptyBranch = query.data !== undefined && branch !== ALL && query.data.scope.runs === 0;
  const groups = section?.groups ?? [];
  const fresh = groups.filter((g) => g.status === "new").length;
  return (
    <>
      {heading}
      {query.isPending && <SkeletonStatus label="Loading failure causes…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {emptyBranch && <EmptyBranch branch={branch} days={period} onOpenSettings={onOpenSettings} />}
      {section && !emptyBranch && section.failures === 0 && <p className="muted">No failures in the last {period} days.</p>}
      {section && !emptyBranch && section.failures > 0 && (
        <>
          <p className="muted">{section.failures} failures from {section.groups_total} causes</p>
          <p className="muted">{fresh} new · {groups.length - fresh} recurring among the top {groups.length} · {section.resolved.length} resolved</p>
          <ul className="fail-list">
            {groups.slice(0, SHOWN).map((g) => (
              <li key={g.signature}>
                <span className="cause-title">
                  {g.status === "new" && <span className="badge badge-new">New</span>}
                  {g.headline ? <span className="msg">{g.headline}</span> : <span className="where">No error message</span>}
                </span>
                <span className="where">{g.occurrences} {g.occurrences === 1 ? "failure" : "failures"} in {g.runs} {g.runs === 1 ? "run" : "runs"}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
```

Create `dashboard/src/overview/widgets/failureCauses.ts`:

```ts
import { lazy } from "react";
import { ALL } from "../catalog";
import { reportLink } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const failureCauses: WidgetDefinition = {
  type: "failure_causes",
  title: "Failure causes",
  description: "Failures grouped by cause over a period: new, recurring and resolved.",
  defaultSize: "normal",
  settings: ["period", "branch"],
  defaults: { period: 30, branch: ALL },
  Component: lazy(() => import("./FailureCausesWidget")),
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, settings.branch ?? ALL, "report-causes"),
};
```

Create `dashboard/src/overview/widgets/RegressionsWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import { ALL } from "../catalog";
import EmptyBranch from "../EmptyBranch";
import { formatDay } from "../format";
import { useWidgetReport } from "../reportWidget";
import type { WidgetProps } from "./types";

/** The Report's regressions for the period: newly failing, fixed, flips, and the newly failing tests. */
export default function RegressionsWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
  const period = settings.period ?? 30;
  const branch = settings.branch ?? ALL;
  const rows = settings.rows ?? 5;
  const query = useWidgetReport(projectId, "regressions", period, branch);
  const section = query.data?.regressions;
  const emptyBranch = query.data !== undefined && branch !== ALL && query.data.scope.runs === 0;
  const flips = section?.flakiness.reduce((sum, day) => sum + day.flips, 0) ?? 0;
  const items = section?.newly_failing.items ?? [];
  return (
    <>
      {heading}
      {query.isPending && <SkeletonStatus label="Loading regressions…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {emptyBranch && <EmptyBranch branch={branch} days={period} onOpenSettings={onOpenSettings} />}
      {section && !emptyBranch && (
        <>
          <p className="muted">{section.newly_failing.total} newly failing · {section.fixed.total} fixed · {flips} flips</p>
          {items.length === 0 ? (
            <p className="muted">Nothing started failing in the last {period} days.</p>
          ) : (
            <ul className="fail-list">
              {items.slice(0, rows).map((item) => (
                <li key={`${item.test_key}-${item.branch ?? ""}`}>
                  <span><Link to={`/projects/${projectId}/tests/${encodeURIComponent(item.test_key)}`}>{item.name}</Link></span>
                  <span className="where">{item.branch ?? "no branch"} · failing since {formatDay(item.failing_since)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </>
  );
}
```

Create `dashboard/src/overview/widgets/regressions.ts`:

```ts
import { lazy } from "react";
import { ALL } from "../catalog";
import { reportLink } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const regressions: WidgetDefinition = {
  type: "regressions",
  title: "Regressions and flips",
  description: "Tests that started failing, tests fixed, and result flips over a period.",
  defaultSize: "normal",
  settings: ["period", "branch", "rows"],
  defaults: { period: 30, branch: ALL, rows: 5 },
  Component: lazy(() => import("./RegressionsWidget")),
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, settings.branch ?? ALL, "report-regressions"),
};
```

In `dashboard/src/overview/widgets/registry.ts`, replace:

```ts
import type { WidgetDefinition } from "./types";
```

with:

```ts
import { failureCauses } from "./failureCauses";
import { regressions } from "./regressions";
import type { WidgetDefinition } from "./types";
```

and replace:

```ts
  pass_rate_trend: passRateTrend,
};
```

with:

```ts
  pass_rate_trend: passRateTrend,
  failure_causes: failureCauses,
  regressions: regressions,
};
```

- [ ] **Step 6: Run them to verify they pass**

Run: `cd dashboard && npx vitest run src/overview src/pages/report`
Expected: PASS (the Report page's own tests are untouched).

- [ ] **Step 7: Lint, typecheck**

Run: `cd dashboard && npm run lint && npm run typecheck`
Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/overview/reportWidget.ts dashboard/src/overview/widgets/failureCauses.ts dashboard/src/overview/widgets/FailureCausesWidget.tsx dashboard/src/overview/widgets/regressions.ts dashboard/src/overview/widgets/RegressionsWidget.tsx dashboard/src/overview/widgets/reportWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts
git commit -m "feat(dashboard): Failure causes and Regressions widgets ask the report for their own section" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/reportWidget.ts dashboard/src/overview/widgets/failureCauses.ts dashboard/src/overview/widgets/FailureCausesWidget.tsx dashboard/src/overview/widgets/regressions.ts dashboard/src/overview/widgets/RegressionsWidget.tsx dashboard/src/overview/widgets/reportWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts
```

---

### Task 18: Slowest tests and Coverage

**Files:**
- Create: `dashboard/src/overview/widgets/slowestTests.ts`, `dashboard/src/overview/widgets/SlowestTestsWidget.tsx`, `dashboard/src/overview/widgets/coverage.ts`, `dashboard/src/overview/widgets/CoverageWidget.tsx`
- Test: `dashboard/src/overview/widgets/reportWidgets.test.tsx`, `dashboard/src/overview/widgets/registry.test.ts`
- Modify: `dashboard/src/overview/widgets/registry.ts`, `dashboard/src/index.css`

**Interfaces:**
- Consumes: `useWidgetReport`, `reportLink` (Task 17); `getCaseAreas` (`src/api/cases.ts`); `decodeTests`, `neverRun`, `unlinkedTestCount` (`src/lib/reportScope.ts`); `REPORT_STALE_MS`, `caseAreasMessage` (`src/pages/report/useReportRequest.ts`); `formatDuration`.
- Produces: `slowestTests: WidgetDefinition` (reads `summary.slowest` with `sections: ["summary"]`, Ruling 12); `coverage: WidgetDefinition` (`sections: ["tests"]` plus `["case-areas", projectId]`, across all branches, Ruling 13).

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill and read DESIGN.md "Report: By Area, Coverage and Duration" and "Delta Tiles".

- [ ] **Step 2: Write the failing tests**

In `dashboard/src/overview/widgets/reportWidgets.test.tsx`, replace:

```tsx
import { CAUSES_REPORT, REGRESSIONS_REPORT, emptyReport } from "../../pages/report/testFixtures";
```

with:

```tsx
import { CAUSES_REPORT, REGRESSIONS_REPORT, SUMMARY_REPORT, TESTS_REPORT, emptyReport } from "../../pages/report/testFixtures";
```

and append to the end of the file:

```tsx
const key = (n: number) => n.toString(16).padStart(64, "0");
const AREAS_WIRE = {
  generated_at: "v1", counts: { cases: 4, linked: 3, manual: 1 },
  folders: ["features/booking", "features/payments"], features: ["Booking", "Payments"], labels: ["smoke"],
  suites: [{ id: 12, name: "Regression" }],
  cases: [
    { n: 1, t: "Book one-way", k: key(1), fo: 0, fe: 0, l: [0], s: [0] },
    { n: 2, t: "Pay by card", k: key(2), fo: 1, fe: 1, l: [], s: [0] },
    { n: 3, t: "Refund", k: key(3), fo: 1, fe: 1, l: [], s: [] },
    { n: 4, t: "Manual check", k: null, fo: null, fe: null, l: [], s: [] },
  ],
};

test("Slowest tests reads the summary's slowest tests and links to the report", async () => {
  mockOverviewData({ layout: personalState({ id: "s", type: "slowest_tests", size: "normal" }) });
  const bodies = reportAsked(() => SUMMARY_REPORT);
  renderOverview();
  expect(await screen.findByRole("link", { name: "slow one" })).toBeInTheDocument();
  expect(screen.getByText("1m 21s on average · 30 runs")).toBeInTheDocument();
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].sections).toEqual(["summary"]);
  const heading = screen.getByRole("heading", { name: "Slowest tests" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-summary");
});

test("Coverage joins the cases with the tests section like the Report does", async () => {
  mockOverviewData({ layout: personalState({ id: "v", type: "coverage", size: "normal" }) });
  const bodies = reportAsked(() => TESTS_REPORT);
  server.use(http.get("/api/v1/projects/42/case-areas", () => HttpResponse.json(AREAS_WIRE)));
  renderOverview();
  expect(await screen.findByText("Automated, not run in 30 days")).toBeInTheDocument();
  expect(screen.getByText("Active cases").nextElementSibling).toHaveTextContent("4");
  expect(screen.getByText("Automated, not run in 30 days").nextElementSibling).toHaveTextContent("1");
  expect(screen.getByText("Tests without a case").nextElementSibling).toHaveTextContent("1");
  await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0].sections).toEqual(["tests"]);
  expect(bodies[0].branch).toBeNull();
  const heading = screen.getByRole("heading", { name: "Coverage" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/report?period=30&branch=*#report-coverage");
});

test("Coverage says when the cases cannot be loaded, with Retry", async () => {
  mockOverviewData({ layout: personalState({ id: "v", type: "coverage", size: "normal" }) });
  reportAsked(() => TESTS_REPORT);
  server.use(http.get("/api/v1/projects/42/case-areas", () => HttpResponse.json({ detail: "down" }, { status: 500 })));
  renderOverview();
  const card = await screen.findByRole("region", { name: "Coverage" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Cases could not be loaded");
  expect(within(card).getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
```

In `dashboard/src/overview/widgets/registry.test.ts`, replace:

```ts
  "recent_runs", "branch_health", "slowest_tests", "coverage",
```

with:

```ts
  "recent_runs", "branch_health",
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/overview/widgets/reportWidgets.test.tsx src/overview/widgets/registry.test.ts`
Expected: FAIL: no link "slow one", no "Automated, not run in 30 days"; the registry test lists `slowest_tests` and `coverage` as missing.

- [ ] **Step 4: Write the two widgets**

Create `dashboard/src/overview/widgets/SlowestTestsWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import { formatDuration } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import { ALL } from "../catalog";
import EmptyBranch from "../EmptyBranch";
import { useWidgetReport } from "../reportWidget";
import type { WidgetProps } from "./types";

/** The tests with the longest average duration in the period: the summary's `slowest`, the per-test numbers the
 *  report computes (the duration section has no per-test rows; plan Ruling 12). */
export default function SlowestTestsWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
  const period = settings.period ?? 30;
  const branch = settings.branch ?? ALL;
  const rows = settings.rows ?? 5;
  const query = useWidgetReport(projectId, "summary", period, branch);
  const emptyBranch = query.data !== undefined && branch !== ALL && query.data.scope.runs === 0;
  const slowest = query.data?.summary?.slowest ?? [];
  return (
    <>
      {heading}
      {query.isPending && <SkeletonStatus label="Loading slowest tests…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {emptyBranch && <EmptyBranch branch={branch} days={period} onOpenSettings={onOpenSettings} />}
      {query.data && !emptyBranch && slowest.length === 0 && <p className="muted">No tests ran in the last {period} days.</p>}
      {query.data && !emptyBranch && slowest.length > 0 && (
        <ol className="fail-list">
          {slowest.slice(0, rows).map((t) => (
            <li key={t.test_key}>
              <span><Link to={`/projects/${projectId}/tests/${encodeURIComponent(t.test_key)}`}>{t.name}</Link></span>
              <span className="where">{formatDuration(t.avg_duration_ms)} on average · {t.executions} {t.executions === 1 ? "run" : "runs"}</span>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
```

Create `dashboard/src/overview/widgets/slowestTests.ts`:

```ts
import { lazy } from "react";
import { ALL } from "../catalog";
import { reportLink } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const slowestTests: WidgetDefinition = {
  type: "slowest_tests",
  title: "Slowest tests",
  description: "The tests with the longest average duration over a period.",
  defaultSize: "normal",
  settings: ["period", "branch", "rows"],
  defaults: { period: 30, branch: ALL, rows: 5 },
  Component: lazy(() => import("./SlowestTestsWidget")),
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, settings.branch ?? ALL, "report-summary"),
};
```

Create `dashboard/src/overview/widgets/CoverageWidget.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { getCaseAreas } from "../../api/cases";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import { decodeTests, neverRun, unlinkedTestCount } from "../../lib/reportScope";
import { REPORT_STALE_MS, caseAreasMessage } from "../../pages/report/useReportRequest";
import { ALL } from "../catalog";
import { useWidgetReport } from "../reportWidget";
import type { WidgetProps } from "./types";

/** The Report's coverage join, unchanged (ADR-026): test-management's case areas under the Report's key, and the tests
 *  section over the period, across every branch (plan Ruling 13). */
export default function CoverageWidget({ projectId, settings, heading }: WidgetProps) {
  const period = settings.period ?? 30;
  const areas = useQuery({
    queryKey: ["case-areas", projectId], queryFn: ({ signal }) => getCaseAreas(projectId, { signal }),
    staleTime: REPORT_STALE_MS, retry: false,
  });
  const tests = useWidgetReport(projectId, "tests", period, ALL);
  const section = tests.data?.tests;
  const rows = section ? decodeTests(section) : [];
  // A test cut off by the 50,000-row cap would look never run, so those two counts are not shown then
  const cut = section?.truncated === true;
  return (
    <>
      {heading}
      {(areas.isPending || tests.isPending) && !areas.error && !tests.error && (
        <SkeletonStatus label="Loading coverage…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>
      )}
      {areas.error != null && (
        <div className="error-banner" role="alert">
          <span>{caseAreasMessage(areas.error)}</span>
          <button type="button" onClick={() => areas.refetch()}>Retry</button>
        </div>
      )}
      {tests.error != null && <ErrorBanner error={tests.error} onRetry={() => tests.refetch()} />}
      {areas.data && section && (
        <>
          <dl className="overview-figures">
            <div><dt>Active cases</dt><dd>{areas.data.counts.cases}</dd></div>
            <div><dt>Linked (automated)</dt><dd>{areas.data.counts.linked}</dd></div>
            <div><dt>Manual</dt><dd>{areas.data.counts.manual}</dd></div>
            {!cut && <div><dt>Automated, not run in {period} days</dt><dd>{neverRun(areas.data, rows, { kind: "all" }).length}</dd></div>}
            {!cut && <div><dt>Tests without a case</dt><dd>{unlinkedTestCount(areas.data, rows)}</dd></div>}
          </dl>
          {cut && <p className="muted">The test list was cut at 50,000 tests, so cases not run and tests without a case are not counted.</p>}
        </>
      )}
    </>
  );
}
```

Create `dashboard/src/overview/widgets/coverage.ts`:

```ts
import { lazy } from "react";
import { ALL } from "../catalog";
import { reportLink } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const coverage: WidgetDefinition = {
  type: "coverage",
  title: "Coverage",
  description: "Linked and manual cases, automated cases not run, and tests without a case.",
  defaultSize: "normal",
  settings: ["period"],
  defaults: { period: 30 },
  Component: lazy(() => import("./CoverageWidget")),
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, ALL, "report-coverage"),
};
```

In `dashboard/src/overview/widgets/registry.ts`, replace:

```ts
import type { WidgetDefinition } from "./types";
```

with:

```ts
import { coverage } from "./coverage";
import { slowestTests } from "./slowestTests";
import type { WidgetDefinition } from "./types";
```

and replace:

```ts
  regressions: regressions,
};
```

with:

```ts
  regressions: regressions,
  slowest_tests: slowestTests,
  coverage: coverage,
};
```

In `dashboard/src/index.css`, replace:

```css
.overview-empty { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-2); }
```

with:

```css
.overview-empty { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-2); }
.overview-figures { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: var(--space-3); margin: 0; }
.overview-figures dt { font-size: 12px; color: var(--text-secondary); }
.overview-figures dd { margin: 0; font-size: 22px; font-weight: 650; font-variant-numeric: tabular-nums; }
```

- [ ] **Step 5: Run them to verify they pass**

Run: `cd dashboard && npx vitest run src/overview`
Expected: PASS.

- [ ] **Step 6: Lint, typecheck**

Run: `cd dashboard && npm run lint && npm run typecheck`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/overview/widgets/slowestTests.ts dashboard/src/overview/widgets/SlowestTestsWidget.tsx dashboard/src/overview/widgets/coverage.ts dashboard/src/overview/widgets/CoverageWidget.tsx dashboard/src/overview/widgets/reportWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/index.css
git commit -m "feat(dashboard): Slowest tests and Coverage widgets" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/widgets/slowestTests.ts dashboard/src/overview/widgets/SlowestTestsWidget.tsx dashboard/src/overview/widgets/coverage.ts dashboard/src/overview/widgets/CoverageWidget.tsx dashboard/src/overview/widgets/reportWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/index.css
```

---

### Task 19: Recent runs and Branch health

**Files:**
- Create: `dashboard/src/lib/runQueries.ts`, `dashboard/src/overview/widgets/recentRuns.ts`, `dashboard/src/overview/widgets/RecentRunsWidget.tsx`, `dashboard/src/overview/widgets/branchHealth.ts`, `dashboard/src/overview/widgets/BranchHealthWidget.tsx`
- Test: `dashboard/src/overview/widgets/runWidgets.test.tsx`, `dashboard/src/overview/widgets/registry.test.ts`
- Modify: `dashboard/src/overview/widgets/registry.ts`, `dashboard/src/pages/RunsPage.tsx`

**Interfaces:**
- Consumes: `listRuns`, `RunFilters` (`src/api/runs.ts`); `LIVE_REFRESH_MS`; `branchesViewQuery` (Task 13); `runVerdict` (`src/components/RunStatusBadge.tsx`); `RunVerdictPill` (`src/components/StatusPill.tsx`); `EmptyBranch` (Task 16); `ago`.
- Produces: `src/lib/runQueries.ts`: `RUNS_PAGE_SIZE = 50`; `runsFirstPageQuery(projectId: number, filters: RunFilters)` (the Runs view's key `["runs", projectId, filters, 0]`, `limit: RUNS_PAGE_SIZE`, polled every 30 s). `recentRuns`, `branchHealth: WidgetDefinition`. RunsPage takes its page size from `RUNS_PAGE_SIZE`.

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill and read DESIGN.md "Status Dot and Badges" (Status pill).

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/overview/widgets/runWidgets.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { FAILING_RUN, RUN, mockOverviewData, personalState, renderOverview } from "../testing";

function runsAsked(answer: (params: URLSearchParams) => object[]) {
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/runs", ({ request }) => {
    const params = new URL(request.url).searchParams;
    asked.push(params);
    return HttpResponse.json(answer(params));
  }));
  return asked;
}

test("Recent runs shares the Runs view's first page for its branch and shows each verdict in words", async () => {
  mockOverviewData({ layout: personalState({ id: "r", type: "recent_runs", size: "normal", settings: { branch: "develop", rows: 5 } }) });
  const asked = runsAsked((p) => (p.get("branch") === "develop" ? [{ ...FAILING_RUN, id: 70, branch: "develop" }] : [RUN]));
  renderOverview();
  expect(await screen.findByRole("link", { name: "Run #70" })).toHaveAttribute("href", "/projects/42/runs/70");
  expect(screen.getByText("Failed")).toBeInTheDocument();
  const page = asked.find((p) => p.get("branch") === "develop")!;
  expect(page.get("limit")).toBe("50");
  expect(page.get("offset")).toBe("0");
  const heading = screen.getByRole("heading", { name: "Recent runs" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/runs?branch=develop");
});

test("Recent runs on a branch without runs says so with its settings button", async () => {
  mockOverviewData({ layout: personalState({ id: "r", type: "recent_runs", size: "normal", settings: { branch: "gone" } }) });
  runsAsked((p) => (p.get("branch") === "gone" ? [] : [RUN]));
  renderOverview();
  expect(await screen.findByText("No runs on gone")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Change settings" }));
  expect(await screen.findByRole("form", { name: "Recent runs settings" })).toBeInTheDocument();
});

test("Branch health lists branches newest first with pass rate, runs and last run, and links to Branches", async () => {
  mockOverviewData({ layout: personalState({ id: "b", type: "branch_health", size: "normal" }) });
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/analytics/branches", ({ request }) => {
    asked.push(new URL(request.url).searchParams);
    return HttpResponse.json([
      { branch: "main", runs: 40, total: 400, passed: 390, failed: 10, errored: 0, skipped: 0, pass_rate: 0.975, last_seen: "2026-10-01T10:00:00Z" },
      { branch: "develop", runs: 1, total: 10, passed: 5, failed: 5, errored: 0, skipped: 0, pass_rate: 0.5, last_seen: "2026-10-04T10:00:00Z" },
    ]);
  }));
  renderOverview();
  const card = await screen.findByRole("region", { name: "Branch health" });
  await waitFor(() => expect(within(card).getAllByRole("listitem")).toHaveLength(2));
  const [first, second] = within(card).getAllByRole("listitem");
  expect(first).toHaveTextContent(/develop.*50\.0% pass rate · 1 run · last/);
  expect(second).toHaveTextContent(/main.*97\.5% pass rate · 40 runs · last/);
  expect(asked[0].get("days")).toBe("30");
  expect(within(screen.getByRole("heading", { name: "Branch health" })).getByRole("link")).toHaveAttribute("href", "/projects/42/branches");
});

test("Branch health shows its error with Retry", async () => {
  mockOverviewData({ layout: personalState({ id: "b", type: "branch_health", size: "normal" }) });
  server.use(http.get("/api/v1/projects/42/analytics/branches", () => HttpResponse.json({ detail: "Branches are down" }, { status: 500 })));
  renderOverview();
  const card = await screen.findByRole("region", { name: "Branch health" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Branches are down");
});
```

In `dashboard/src/overview/widgets/registry.test.ts`, replace:

```ts
  "recent_runs", "branch_health",
  "case_tiles", "my_failures", "my_suites",
```

with:

```ts
  "case_tiles", "my_failures", "my_suites",
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/overview/widgets/runWidgets.test.tsx src/overview/widgets/registry.test.ts`
Expected: FAIL: no link "Run #70", no region "Branch health"; the registry test lists `recent_runs` and `branch_health` as missing.

- [ ] **Step 4: Share the Runs view's first page**

Create `dashboard/src/lib/runQueries.ts`:

```ts
import { listRuns, type RunFilters } from "../api/runs";
import { LIVE_REFRESH_MS } from "./live";

/** The Runs view's page size. */
export const RUNS_PAGE_SIZE = 50;

/** The Runs view's first page for these filters, under its own key and polled as it is (ADR-021). Undefined filter
 *  fields drop out of the key, so `{ branch: "main" }` is the view's key with only Branch applied. */
export const runsFirstPageQuery = (projectId: number, filters: RunFilters) => ({
  queryKey: ["runs", projectId, filters, 0] as const,
  queryFn: () => listRuns(projectId, { limit: RUNS_PAGE_SIZE, offset: 0, ...filters }),
  refetchInterval: LIVE_REFRESH_MS,
});
```

In `dashboard/src/pages/RunsPage.tsx`, replace:

```tsx
import { pageOffset, withOffset } from "../lib/useUrlState";
```

with:

```tsx
import { pageOffset, withOffset } from "../lib/useUrlState";
import { RUNS_PAGE_SIZE } from "../lib/runQueries";
```

and replace:

```tsx
const PAGE = 50;
```

with:

```tsx
// Shared with the Overview's run widgets, so their first page is this view's answer
const PAGE = RUNS_PAGE_SIZE;
```

- [ ] **Step 5: Write the two widgets**

Create `dashboard/src/overview/widgets/RecentRunsWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { RunFilters } from "../../api/runs";
import ErrorBanner from "../../components/ErrorBanner";
import { runVerdict } from "../../components/RunStatusBadge";
import { SkeletonStatus } from "../../components/Skeleton";
import { RunVerdictPill } from "../../components/StatusPill";
import { runsFirstPageQuery } from "../../lib/runQueries";
import { ALL } from "../catalog";
import EmptyBranch from "../EmptyBranch";
import { ago } from "../format";
import type { WidgetProps } from "./types";

/** The newest runs with their verdicts in words, from the Runs view's first page (polled every 30 s). */
export default function RecentRunsWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
  const rows = settings.rows ?? 5;
  const branch = settings.branch ?? ALL;
  const filters: RunFilters = branch === ALL ? {} : { branch };
  const runs = useQuery(runsFirstPageQuery(projectId, filters));
  const list = runs.data ?? [];
  return (
    <>
      {heading}
      {runs.isPending && <SkeletonStatus label="Loading recent runs…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
      {runs.error != null && <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} />}
      {runs.data && list.length === 0 && (branch === ALL
        ? <p className="muted">No runs yet.</p>
        : <EmptyBranch branch={branch} onOpenSettings={onOpenSettings} />)}
      {list.length > 0 && (
        <ul className="fail-list">
          {list.slice(0, rows).map((run) => (
            <li key={run.id}>
              <span className="cause-title">
                <RunVerdictPill verdict={runVerdict(run)} /> <Link to={`/projects/${projectId}/runs/${run.id}`}>Run #{run.id}</Link>
              </span>
              <span className="where">{run.branch ?? "no branch"} · {ago(run.started_at)} · {run.passed} passed, {run.failed + run.errored} failed</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
```

Create `dashboard/src/overview/widgets/recentRuns.ts`:

```ts
import { lazy } from "react";
import { ALL } from "../catalog";
import type { WidgetDefinition } from "./types";

export const recentRuns: WidgetDefinition = {
  type: "recent_runs",
  title: "Recent runs",
  description: "The newest runs with their verdicts, on all branches or one.",
  defaultSize: "normal",
  settings: ["branch", "rows"],
  defaults: { branch: ALL, rows: 5 },
  Component: lazy(() => import("./RecentRunsWidget")),
  link: (projectId, settings) =>
    settings.branch && settings.branch !== ALL
      ? `/projects/${projectId}/runs?${new URLSearchParams({ branch: settings.branch })}`
      : `/projects/${projectId}/runs`,
};
```

Create `dashboard/src/overview/widgets/BranchHealthWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { formatPassRate } from "../../api/analytics";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import { branchesViewQuery } from "../../lib/healthQueries";
import { ago } from "../format";
import type { WidgetProps } from "./types";

/** Each branch's pass rate, runs and last run over 30 days, newest first: the Branches view's numbers (plan Ruling 14). */
export default function BranchHealthWidget({ projectId, settings, heading }: WidgetProps) {
  const rows = settings.rows ?? 5;
  const branches = useQuery(branchesViewQuery(projectId));
  const list = [...(branches.data ?? [])].sort((a, b) => b.last_seen.localeCompare(a.last_seen)).slice(0, rows);
  return (
    <>
      {heading}
      {branches.isPending && <SkeletonStatus label="Loading branch health…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
      {branches.error != null && <ErrorBanner error={branches.error} onRetry={() => branches.refetch()} />}
      {branches.data && list.length === 0 && <p className="muted">No runs in the last 30 days.</p>}
      {list.length > 0 && (
        <ul className="fail-list">
          {list.map((b) => (
            <li key={b.branch ?? "(no branch)"}>
              <span>
                {b.branch
                  ? <Link to={`/projects/${projectId}/runs?${new URLSearchParams({ branch: b.branch })}`}>{b.branch}</Link>
                  : <span className="where">No branch</span>}
              </span>
              <span className="where">{formatPassRate(b.pass_rate)} pass rate · {b.runs} {b.runs === 1 ? "run" : "runs"} · last {ago(b.last_seen)}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
```

Create `dashboard/src/overview/widgets/branchHealth.ts`:

```ts
import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const branchHealth: WidgetDefinition = {
  type: "branch_health",
  title: "Branch health",
  description: "Each branch's pass rate, runs and last run over 30 days.",
  defaultSize: "normal",
  settings: ["rows"],
  defaults: { rows: 5 },
  Component: lazy(() => import("./BranchHealthWidget")),
  link: (projectId) => `/projects/${projectId}/branches`,
};
```

In `dashboard/src/overview/widgets/registry.ts`, replace:

```ts
import type { WidgetDefinition } from "./types";
```

with:

```ts
import { branchHealth } from "./branchHealth";
import { recentRuns } from "./recentRuns";
import type { WidgetDefinition } from "./types";
```

and replace:

```ts
  coverage: coverage,
};
```

with:

```ts
  coverage: coverage,
  recent_runs: recentRuns,
  branch_health: branchHealth,
};
```

- [ ] **Step 6: Run them to verify they pass**

Run: `cd dashboard && npx vitest run src/overview src/pages/RunsPage.test.tsx`
Expected: PASS.

- [ ] **Step 7: Lint, typecheck**

Run: `cd dashboard && npm run lint && npm run typecheck`
Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/lib/runQueries.ts dashboard/src/overview/widgets/recentRuns.ts dashboard/src/overview/widgets/RecentRunsWidget.tsx dashboard/src/overview/widgets/branchHealth.ts dashboard/src/overview/widgets/BranchHealthWidget.tsx dashboard/src/overview/widgets/runWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/pages/RunsPage.tsx
git commit -m "feat(dashboard): Recent runs and Branch health widgets" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/lib/runQueries.ts dashboard/src/overview/widgets/recentRuns.ts dashboard/src/overview/widgets/RecentRunsWidget.tsx dashboard/src/overview/widgets/branchHealth.ts dashboard/src/overview/widgets/BranchHealthWidget.tsx dashboard/src/overview/widgets/runWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/pages/RunsPage.tsx
```

---

### Task 20: Test cases, My suites and My recent failures

**Files:**
- Create: `dashboard/src/overview/widgets/caseTiles.ts`, `dashboard/src/overview/widgets/CaseTilesWidget.tsx`, `dashboard/src/overview/widgets/mySuites.ts`, `dashboard/src/overview/widgets/MySuitesWidget.tsx`, `dashboard/src/overview/widgets/myFailures.ts`, `dashboard/src/overview/widgets/MyFailuresWidget.tsx`
- Test: `dashboard/src/overview/widgets/personalWidgets.test.tsx`, `dashboard/src/overview/widgets/registry.test.ts`
- Modify: `dashboard/src/overview/widgets/registry.ts`, `dashboard/src/api/cases.ts`, `dashboard/src/api/auth.ts`

**Interfaces:**
- Consumes: `CasesKpis` (`src/components/CasesKpis.tsx`, unchanged); `listSuites` (`src/api/cases.ts`); `getMe` (`src/api/auth.ts`, query key `["me"]` as UserMenu uses); `runsFirstPageQuery` (Task 19); `GET /suites?created_by=me` (Task 5).
- Produces: `listSuites(projectId: number, opts: { search?: string; createdBy?: "me" } = {}, init = {})`; `getMe()` typed with `full_name?: string | null`; `caseTiles` (default Wide, Ruling 29), `mySuites`, `myFailures: WidgetDefinition`.

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill and read DESIGN.md "KPI Tiles" and "Error Banner" (empty states say what is absent and how data arrives).

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/overview/widgets/personalWidgets.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { FAILING_RUN, RUN, mockOverviewData, personalState, renderOverview } from "../testing";

const me = (full_name: string | null) =>
  server.use(http.get("/api/v1/users/me", () => HttpResponse.json({ id: 7, email: "ada@example.com", mfa_enabled: false, full_name })));

function failingRunsAsked(answer: object[]) {
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/runs", ({ request }) => {
    const params = new URL(request.url).searchParams;
    if (params.get("status") !== "failing") return HttpResponse.json([RUN]);
    asked.push(params);
    return HttpResponse.json(answer);
  }));
  return asked;
}

test("My recent failures matches the commit author by the user's full name", async () => {
  mockOverviewData({ layout: personalState({ id: "f", type: "my_failures", size: "normal" }) });
  me("Ada Lovelace");
  const asked = failingRunsAsked([FAILING_RUN]);
  renderOverview();
  expect(await screen.findByRole("link", { name: "Run #61" })).toHaveAttribute("href", "/projects/42/runs/61");
  expect(asked[0].get("author")).toBe("Ada Lovelace");
  expect(asked[0].get("limit")).toBe("50");
  const heading = screen.getByRole("heading", { name: "My recent failures" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/runs?status=failing");
});

test("with no full name and no setting, My recent failures asks for a name and sends nothing", async () => {
  mockOverviewData({ layout: personalState({ id: "f", type: "my_failures", size: "normal" }) });
  me(null);
  const asked = failingRunsAsked([FAILING_RUN]);
  renderOverview();
  expect(await screen.findByText(/Your QEOS profile has no full name/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Change settings" })).toBeInTheDocument();
  expect(asked).toHaveLength(0);
});

test("when nothing matches, My recent failures says so and names the setting", async () => {
  mockOverviewData({ layout: personalState({ id: "f", type: "my_failures", size: "normal", settings: { author: "A. Lovelace", rows: 5 } }) });
  me("Ada Lovelace");
  const asked = failingRunsAsked([]);
  renderOverview();
  expect(await screen.findByText(/No failed runs by “A\. Lovelace”/)).toBeInTheDocument();
  expect(screen.getByText(/Your name in git/)).toBeInTheDocument();
  expect(asked[0].get("author")).toBe("A. Lovelace");
  const heading = screen.getByRole("heading", { name: "My recent failures" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/runs?status=failing&author=A.%20Lovelace");
  await userEvent.click(screen.getByRole("button", { name: "Change settings" }));
  expect(await screen.findByRole("form", { name: "My recent failures settings" })).toBeInTheDocument();
});

test("My suites lists the caller's own suites and links to Suites", async () => {
  mockOverviewData({ layout: personalState({ id: "s", type: "my_suites", size: "normal" }) });
  const asked: URLSearchParams[] = [];
  server.use(http.get("/api/v1/projects/42/suites", ({ request }) => {
    asked.push(new URL(request.url).searchParams);
    return HttpResponse.json([{ id: 5, name: "Smoke", description: null, case_count: 3, created_at: "2026-10-01T00:00:00Z", updated_at: null }]);
  }));
  renderOverview();
  expect(await screen.findByRole("link", { name: "Smoke" })).toHaveAttribute("href", "/projects/42/suites/5");
  expect(screen.getByText("3 cases")).toBeInTheDocument();
  expect(asked[0].get("created_by")).toBe("me");
  expect(within(screen.getByRole("heading", { name: "My suites" })).getByRole("link")).toHaveAttribute("href", "/projects/42/suites");
});

test("My suites shows its error with Retry", async () => {
  mockOverviewData({ layout: personalState({ id: "s", type: "my_suites", size: "normal" }) });
  server.use(http.get("/api/v1/projects/42/suites", () => HttpResponse.json({ detail: "Suites are down" }, { status: 500 })));
  renderOverview();
  const card = await screen.findByRole("region", { name: "My suites" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Suites are down");
});

test("Test cases shows the Cases tiles and links to Cases", async () => {
  mockOverviewData({ layout: personalState({ id: "c", type: "case_tiles", size: "wide" }) });
  server.use(http.get("/api/v1/projects/42/cases", ({ request }) =>
    HttpResponse.json({ total: new URL(request.url).searchParams.get("origin") === "imported" ? 4 : 12, items: [] })));
  renderOverview();
  expect(await screen.findByRole("group", { name: "Cases 12, 4 imported" })).toBeInTheDocument();
  expect(within(screen.getByRole("heading", { name: "Test cases" })).getByRole("link")).toHaveAttribute("href", "/projects/42/cases");
  await waitFor(() => expect(screen.getByRole("region", { name: "Test cases" })).toHaveClass("wide"));
});
```

In `dashboard/src/overview/widgets/registry.test.ts`, replace:

```ts
  "case_tiles", "my_failures", "my_suites",
]);
```

with:

```ts
]);
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/overview/widgets/personalWidgets.test.tsx src/overview/widgets/registry.test.ts`
Expected: FAIL: no heading "My recent failures", "My suites", "Test cases"; the registry test lists the three types as missing.

- [ ] **Step 4: Extend the API clients**

In `dashboard/src/api/cases.ts`, replace:

```ts
export function listSuites(projectId: number, opts: { search?: string } = {}, init: { signal?: AbortSignal } = {}): Promise<Suite[]> {
  const q = buildQuery({ search: opts.search || undefined });
```

with:

```ts
export function listSuites(
  projectId: number, opts: { search?: string; createdBy?: "me" } = {}, init: { signal?: AbortSignal } = {},
): Promise<Suite[]> {
  const q = buildQuery({ search: opts.search || undefined, created_by: opts.createdBy });
```

In `dashboard/src/api/auth.ts`, replace:

```ts
export function getMe(): Promise<{ id: number; email: string; mfa_enabled: boolean; monitoring_url?: string | null }> {
```

with:

```ts
export function getMe(): Promise<{ id: number; email: string; mfa_enabled: boolean; full_name?: string | null; monitoring_url?: string | null }> {
```

- [ ] **Step 5: Write the three widgets**

Create `dashboard/src/overview/widgets/CaseTilesWidget.tsx`:

```tsx
import CasesKpis from "../../components/CasesKpis";
import type { WidgetProps } from "./types";

/** The Cases view's four KPI tiles, unchanged: each tile loads, fails and retries on its own. */
export default function CaseTilesWidget({ projectId, heading }: WidgetProps) {
  return (
    <>
      {heading}
      <CasesKpis projectId={projectId} />
    </>
  );
}
```

Create `dashboard/src/overview/widgets/caseTiles.ts`:

```ts
import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const caseTiles: WidgetDefinition = {
  type: "case_tiles",
  title: "Test cases",
  description: "The Cases tiles: cases, pass rate, failing linked cases and flaky tests.",
  // Four tiles need the row (plan Ruling 29)
  defaultSize: "wide",
  settings: [],
  defaults: {},
  Component: lazy(() => import("./CaseTilesWidget")),
  link: (projectId) => `/projects/${projectId}/cases`,
};
```

Create `dashboard/src/overview/widgets/MySuitesWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listSuites } from "../../api/cases";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import type { WidgetProps } from "./types";

/** The suites the signed-in person created. The Suites view invalidates ["suites", id], which covers this key. */
export default function MySuitesWidget({ projectId, settings, heading }: WidgetProps) {
  const rows = settings.rows ?? 5;
  const suites = useQuery({ queryKey: ["suites", projectId, "mine"] as const, queryFn: () => listSuites(projectId, { createdBy: "me" }) });
  const list = suites.data ?? [];
  return (
    <>
      {heading}
      {suites.isPending && <SkeletonStatus label="Loading your suites…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>}
      {suites.error != null && <ErrorBanner error={suites.error} onRetry={() => suites.refetch()} />}
      {suites.data && list.length === 0 && <p className="muted">You have not created a suite in this project yet.</p>}
      {list.length > 0 && (
        <ul className="fail-list">
          {list.slice(0, rows).map((suite) => (
            <li key={suite.id}>
              <span><Link to={`/projects/${projectId}/suites/${suite.id}`}>{suite.name}</Link></span>
              <span className="where">{suite.case_count} {suite.case_count === 1 ? "case" : "cases"}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
```

Create `dashboard/src/overview/widgets/mySuites.ts`:

```ts
import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const mySuites: WidgetDefinition = {
  type: "my_suites",
  title: "My suites",
  description: "The suites you created in this project.",
  defaultSize: "normal",
  settings: ["rows"],
  defaults: { rows: 5 },
  Component: lazy(() => import("./MySuitesWidget")),
  link: (projectId) => `/projects/${projectId}/suites`,
};
```

Create `dashboard/src/overview/widgets/MyFailuresWidget.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { SlidersHorizontal } from "lucide-react";
import { getMe } from "../../api/auth";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStatus } from "../../components/Skeleton";
import { runsFirstPageQuery } from "../../lib/runQueries";
import { ago } from "../format";
import type { WidgetProps } from "./types";

/** Failed runs whose commit author is the signed-in person, matched by name: the collector stores `git log --format=%an`
 *  (spec §2.4). The default name is the QEOS full name; the setting holds the name as git records it. */
export default function MyFailuresWidget({ projectId, settings, heading, onOpenSettings }: WidgetProps) {
  const rows = settings.rows ?? 5;
  const me = useQuery({ queryKey: ["me"], queryFn: getMe, staleTime: 5 * 60_000, enabled: settings.author === undefined });
  const author = (settings.author ?? me.data?.full_name ?? "").trim();
  // An empty author would match every run (the filter is a substring match): never ask without a name (plan Ruling 24)
  const runs = useQuery({ ...runsFirstPageQuery(projectId, { status: "failing", author }), enabled: author !== "" });
  const list = runs.data ?? [];
  const settingsButton = onOpenSettings && (
    <button type="button" onClick={onOpenSettings}><SlidersHorizontal size={15} aria-hidden="true" /> Change settings</button>
  );
  const waitingForName = settings.author === undefined && me.isPending;
  return (
    <>
      {heading}
      {(waitingForName || (author !== "" && runs.isPending)) && (
        <SkeletonStatus label="Loading your failures…"><span className="skeleton stat-skeleton" aria-hidden="true" /></SkeletonStatus>
      )}
      {me.error != null && settings.author === undefined && <ErrorBanner error={me.error} onRetry={() => me.refetch()} />}
      {!waitingForName && me.error == null && author === "" && (
        <div className="overview-empty">
          <p className="muted">
            Your QEOS profile has no full name, so this widget cannot tell which runs are yours. Set "Your name in git" in
            its settings.
          </p>
          {settingsButton}
        </div>
      )}
      {runs.error != null && <ErrorBanner error={runs.error} onRetry={() => runs.refetch()} />}
      {runs.data && list.length === 0 && (
        <div className="overview-empty">
          <p className="muted">
            No failed runs by “{author}”. If git records your name differently, set "Your name in git" in this widget's settings.
          </p>
          {settingsButton}
        </div>
      )}
      {list.length > 0 && (
        <ul className="fail-list">
          {list.slice(0, rows).map((run) => (
            <li key={run.id}>
              <span><Link to={`/projects/${projectId}/runs/${run.id}`}>Run #{run.id}</Link></span>
              <span className="where">{run.branch ?? "no branch"} · {ago(run.started_at)} · {run.failed + run.errored} failed</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
```

Create `dashboard/src/overview/widgets/myFailures.ts`:

```ts
import { lazy } from "react";
import type { WidgetDefinition } from "./types";

export const myFailures: WidgetDefinition = {
  type: "my_failures",
  title: "My recent failures",
  description: "Failed runs whose commit author is you, matched by your name in git.",
  defaultSize: "normal",
  settings: ["author", "rows"],
  // No author: the widget uses the signed-in person's QEOS full name
  defaults: { rows: 5 },
  Component: lazy(() => import("./MyFailuresWidget")),
  // The default name is not known here, so only a set author joins the link (plan Ruling 19)
  link: (projectId, settings) =>
    settings.author
      ? `/projects/${projectId}/runs?status=failing&author=${encodeURIComponent(settings.author)}`
      : `/projects/${projectId}/runs?status=failing`,
};
```

In `dashboard/src/overview/widgets/registry.ts`, replace:

```ts
import type { WidgetDefinition } from "./types";
```

with:

```ts
import { caseTiles } from "./caseTiles";
import { myFailures } from "./myFailures";
import { mySuites } from "./mySuites";
import type { WidgetDefinition } from "./types";
```

and replace:

```ts
  branch_health: branchHealth,
};
```

with:

```ts
  branch_health: branchHealth,
  case_tiles: caseTiles,
  my_failures: myFailures,
  my_suites: mySuites,
};
```

- [ ] **Step 6: Run them to verify they pass**

Run: `cd dashboard && npx vitest run src/overview src/components/CasesKpis.test.tsx src/components/CommandPalette.test.tsx src/components/UserMenu.test.tsx`
Expected: PASS (the palette's suite search and the account menu still use `listSuites` and `getMe` unchanged).

- [ ] **Step 7: Lint, typecheck**

Run: `cd dashboard && npm run lint && npm run typecheck`
Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/overview/widgets/caseTiles.ts dashboard/src/overview/widgets/CaseTilesWidget.tsx dashboard/src/overview/widgets/mySuites.ts dashboard/src/overview/widgets/MySuitesWidget.tsx dashboard/src/overview/widgets/myFailures.ts dashboard/src/overview/widgets/MyFailuresWidget.tsx dashboard/src/overview/widgets/personalWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/api/cases.ts dashboard/src/api/auth.ts
git commit -m "feat(dashboard): Test cases, My suites and My recent failures widgets" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/widgets/caseTiles.ts dashboard/src/overview/widgets/CaseTilesWidget.tsx dashboard/src/overview/widgets/mySuites.ts dashboard/src/overview/widgets/MySuitesWidget.tsx dashboard/src/overview/widgets/myFailures.ts dashboard/src/overview/widgets/MyFailuresWidget.tsx dashboard/src/overview/widgets/personalWidgets.test.tsx dashboard/src/overview/widgets/registry.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/api/cases.ts dashboard/src/api/auth.ts
```

---

### Task 21: The three templates

**Files:**
- Modify: `dashboard/src/overview/templates.ts`, `dashboard/src/overview/AddWidgetPanel.tsx`, `dashboard/src/overview/OverviewEditor.tsx`
- Test: `dashboard/src/overview/templates.test.tsx`, `dashboard/src/overview/widgets/registry.test.ts`

**Interfaces:**
- Consumes: the full registry (Tasks 11, 16–20); `draftReducer` `replace` action (Task 12); `widgetTitle` (Task 11).
- Produces: `interface LayoutTemplate { name: "qa_lead" | "developer" | "flaky_hunt"; label: string; layout: StoredLayout }`, `TEMPLATES: LayoutTemplate[]` in `src/overview/templates.ts`; `AddWidgetPanel` gains the required prop `onTemplate: (template: LayoutTemplate) => void`.

- [ ] **Step 1: Invoke the UI skill**

Invoke the `ui-ux-pro-max` skill and read the "Overview Widgets and Edit Mode" section of DESIGN.md.

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/overview/templates.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { emptyReport } from "../pages/report/testFixtures";
import { mockOverviewData, renderOverview } from "./testing";

const titles = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);

beforeEach(() => {
  // What the template widgets ask for, answered quietly
  server.use(
    http.post("/api/v1/projects/42/analytics/report", () => HttpResponse.json(emptyReport())),
    http.get("/api/v1/projects/42/cases", () => HttpResponse.json({ total: 0, items: [] })),
    http.get("/api/v1/projects/42/case-areas", () => HttpResponse.json({
      generated_at: "v1", counts: { cases: 0, linked: 0, manual: 0 }, folders: [], features: [], labels: [], suites: [], cases: [],
    })),
    http.get("/api/v1/projects/42/analytics/branches", () => HttpResponse.json([])),
  );
});

async function useTemplate(label: string) {
  await userEvent.click(await screen.findByRole("button", { name: "Customise" }));
  await userEvent.click(screen.getByRole("button", { name: "Add widget" }));
  await userEvent.click(within(screen.getByRole("region", { name: "Add a widget" })).getByRole("button", { name: `Use the ${label} layout` }));
}

test("a template replaces the draft, says so, and Cancel still undoes it", async () => {
  mockOverviewData();
  renderOverview();
  await useTemplate("QA lead");
  expect(titles()).toEqual(["Pass-rate trend", "Failure causes", "Regressions and flips", "Coverage", "Test cases"]);
  expect(screen.getByText("QA lead layout applied: 5 widgets")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Pass-rate trend" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(titles()).toEqual(["Latest run", "Failing in latest run", "Pass rate this week", "Flaky tests, last 14 days"]);
});

test.each([
  ["Developer", ["Latest run", "Failing in latest run", "Branch health", "Recent runs", "My recent failures"]],
  ["Flaky hunt", ["Flaky tests, last 30 days", "Regressions and flips", "Slowest tests", "Pass-rate trend"]],
])("the %s template holds the widgets the spec names", async (label, expected) => {
  mockOverviewData();
  renderOverview();
  await useTemplate(label);
  expect(titles()).toEqual(expected);
});
```

In `dashboard/src/overview/widgets/registry.test.ts`, replace:

```ts
import { BUILTIN_DEFAULT } from "../templates";
```

with:

```ts
import { BUILTIN_DEFAULT, TEMPLATES } from "../templates";
```

replace:

```ts
// Catalogue types whose widgets arrive in Phase 3; each of Tasks 16-20 removes its own, Task 21 removes the set
const PENDING = new Set<string>([
]);

test("the registry has a widget for every catalogue type, and no other", () => {
  const expected = Object.keys(CATALOG.types).filter((type) => !PENDING.has(type)).sort();
  expect(Object.keys(REGISTRY).sort()).toEqual(expected);
});
```

with:

```ts
test("the registry has a widget for every catalogue type, and no other", () => {
  expect(Object.keys(REGISTRY).sort()).toEqual(Object.keys(CATALOG.types).sort());
});
```

and append to the end of the file:

```ts
test("each template is a valid stored layout of registered widgets", () => {
  expect(TEMPLATES.map((t) => t.label)).toEqual(["QA lead", "Developer", "Flaky hunt"]);
  for (const template of TEMPLATES) {
    expect(layoutProblems(template.layout)).toEqual([]);
    for (const widget of template.layout.widgets) expect(Object.keys(REGISTRY)).toContain(widget.type);
  }
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd dashboard && npx vitest run src/overview/templates.test.tsx src/overview/widgets/registry.test.ts`
Expected: FAIL: `TEMPLATES` is not exported yet, so the registry test fails with `Cannot read properties of undefined (reading 'map')`, and the page tests find no button "Use the QA lead layout".

- [ ] **Step 4: Write the templates**

Append to `dashboard/src/overview/templates.ts`:

```ts

export interface LayoutTemplate {
  name: "qa_lead" | "developer" | "flaky_hunt";
  label: string;
  layout: StoredLayout;
}

/** Ready layouts offered by Add widget (spec §2.5). Choosing one replaces the draft; Cancel still undoes it. */
export const TEMPLATES: LayoutTemplate[] = [
  {
    name: "qa_lead",
    label: "QA lead",
    layout: { schema: 1, widgets: [
      { id: "w1", type: "pass_rate_trend", size: "wide", settings: { granularity: "week", branch: "all" } },
      { id: "w2", type: "failure_causes", size: "normal", settings: { period: 30, branch: "all" } },
      { id: "w3", type: "regressions", size: "normal", settings: { period: 30, branch: "all", rows: 5 } },
      { id: "w4", type: "coverage", size: "normal", settings: { period: 30 } },
      { id: "w5", type: "case_tiles", size: "wide", settings: {} },
    ] },
  },
  {
    name: "developer",
    label: "Developer",
    layout: { schema: 1, widgets: [
      { id: "w1", type: "latest_run", size: "wide", settings: {} },
      { id: "w2", type: "failing_now", size: "normal", settings: { rows: 5 } },
      { id: "w3", type: "branch_health", size: "normal", settings: { rows: 5 } },
      { id: "w4", type: "recent_runs", size: "normal", settings: { branch: "all", rows: 5 } },
      { id: "w5", type: "my_failures", size: "normal", settings: { rows: 5 } },
    ] },
  },
  {
    name: "flaky_hunt",
    label: "Flaky hunt",
    layout: { schema: 1, widgets: [
      { id: "w1", type: "flaky_count", size: "normal", settings: { period: 30 } },
      { id: "w2", type: "regressions", size: "normal", settings: { period: 30, branch: "all", rows: 10 } },
      { id: "w3", type: "slowest_tests", size: "normal", settings: { period: 30, branch: "all", rows: 5 } },
      { id: "w4", type: "pass_rate_trend", size: "wide", settings: { granularity: "day", branch: "all" } },
    ] },
  },
];
```

Replace `dashboard/src/overview/AddWidgetPanel.tsx` with:

```tsx
import { X } from "lucide-react";
import { MAX_WIDGETS } from "./catalog";
import { type LayoutTemplate, TEMPLATES } from "./templates";
import { addableDefinitions, widgetTitle } from "./widgets/registry";
import type { WidgetDefinition } from "./widgets/types";

interface Props {
  id: string;
  /** The layout holds MAX_WIDGETS already. */
  full: boolean;
  onAdd: (def: WidgetDefinition) => void;
  /** Replaces the draft with a template (spec §2.5). */
  onTemplate: (template: LayoutTemplate) => void;
  onClose: () => void;
}

/** Templates first, then every widget type with a one-line description (spec §2.2, §2.5). Escape closes it. */
export default function AddWidgetPanel({ id, full, onAdd, onTemplate, onClose }: Props) {
  return (
    <section
      id={id}
      className="card"
      aria-labelledby={`${id}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <div className="card-head">
        <h2 id={`${id}-title`}>Add a widget</h2>
        <button type="button" className="ghost widget-tool" aria-label="Close the widget list" onClick={onClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <h3>Start from a template</h3>
      <p className="muted">A template replaces the draft; Cancel still undoes it.</p>
      <ul className="add-widget-list">
        {TEMPLATES.map((template) => (
          <li key={template.name}>
            <div>
              <strong>{template.label}</strong>
              <p className="muted">{template.layout.widgets.map((w) => widgetTitle(w)).join(", ")}</p>
            </div>
            <button type="button" aria-label={`Use the ${template.label} layout`} onClick={() => onTemplate(template)}>Use</button>
          </li>
        ))}
      </ul>
      <h3>Widgets</h3>
      {full && <p className="muted">A layout holds at most {MAX_WIDGETS} widgets. Remove one to add another.</p>}
      <ul className="add-widget-list">
        {addableDefinitions().map((def) => (
          <li key={def.type}>
            <div>
              <strong>{def.title}</strong>
              <p className="muted">{def.description}</p>
            </div>
            <button type="button" aria-label={`Add ${def.title}`} disabled={full} onClick={() => onAdd(def)}>Add</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

In `dashboard/src/overview/OverviewEditor.tsx`, replace:

```tsx
import AddWidgetPanel from "./AddWidgetPanel";
```

with:

```tsx
import AddWidgetPanel from "./AddWidgetPanel";
import type { LayoutTemplate } from "./templates";
```

replace:

```tsx
  function resetDraft() {
```

with:

```tsx
  function applyTemplate(template: LayoutTemplate) {
    dispatch({ kind: "replace", layout: template.layout });
    setAdding(false);
    setSettingsFor(null);
    const first = template.layout.widgets[0];
    focusAfter.current = first ? { id: first.id, tool: "card" } : { id: null, tool: "add" };
    setAnnouncement(`${template.label} layout applied: ${template.layout.widgets.length} widgets`);
  }

  function resetDraft() {
```

and replace:

```tsx
          onAdd={add}
```

with:

```tsx
          onAdd={add}
          onTemplate={applyTemplate}
```

- [ ] **Step 5: Run them to verify they pass**

Run: `cd dashboard && npx vitest run src/overview`
Expected: PASS (the registry now equals the catalogue: 14 types).

- [ ] **Step 6: Lint, typecheck, build**

Run: `cd dashboard && npm run lint && npm run typecheck && npm run build`
Expected: exit 0; the build lists 14 `*Widget-*.js` chunks.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/overview/templates.ts dashboard/src/overview/templates.test.tsx dashboard/src/overview/AddWidgetPanel.tsx dashboard/src/overview/OverviewEditor.tsx dashboard/src/overview/widgets/registry.test.ts
git commit -m "feat(dashboard): Overview templates (QA lead, Developer, Flaky hunt)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/overview/templates.ts dashboard/src/overview/templates.test.tsx dashboard/src/overview/AddWidgetPanel.tsx dashboard/src/overview/OverviewEditor.tsx dashboard/src/overview/widgets/registry.test.ts
```

---

### Task 22: Documentation, ADR-028 and the blueprint banner

**Files:**
- Create: `docs/architecture/adr/ADR-028-customisable-overview.md`
- Modify: `PRODUCT.md`, `DESIGN.md`, `README.md`, `docs/SETUP.md`, `TODO.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md`, `docs/architecture/adr/INDEX.md`

**Interfaces:**
- Consumes: everything shipped in Tasks 1–21 and Rulings 10, 24 (follow-ups).
- Produces: the documentation set of spec §6.

- [ ] **Step 1: PRODUCT.md, the Overview rules**

In `PRODUCT.md`, with the Edit tool, replace:

```
## Accessibility & Inclusion
```

with:

```
## Overview Rules

- The Overview is the triage screen (Principle 2), built from widgets over the existing analytics: no
  widget computes a new metric, and none uses AI.
- What a person sees: their personal layout for the project, else the project default (set by owners
  and admins), else the built-in four cards (latest run, failing in latest run, pass rate this week,
  flaky tests in 14 days). With nothing configured it looks as it always did.
- Every role, viewers included, may keep a personal layout; "Reset to project default" removes it, so
  later changes to the default reach that person again.
- Fourteen widget types; a type may appear more than once with different settings (period 7, 14 or
  30 days; 5 or 10 rows; all branches or one). Three templates: QA lead, Developer, Flaky hunt.
  At most 24 widgets per layout.
- "My" widgets match by name: My recent failures uses the commit author name git records, with the
  person's QEOS full name as the default and a setting for how git spells it. Matching by email is a
  later improvement (TODO.md).
- Honest states per widget (Principle 1): a branch with no runs in the period says "No runs on
  <branch> in the last N days"; a failure stays in its own card with Retry; missing data is never
  shown as zero.

## Accessibility & Inclusion
```

- [ ] **Step 2: DESIGN.md, the catalogue, templates and the empty-branch state**

In `DESIGN.md`, with the Edit tool, replace:

```
A *wide* widget spans the full row (the latest run by default);
```

with:

```
A *wide* widget spans the full row (the latest run and the test-case tiles by default);
```

replace:

```
- **Add widget** opens a card listing every widget type with a one-line description and an Add button. At 24 widgets the buttons are disabled and the card says why.
```

with:

```
- **Add widget** opens a card with **Start from a template** (QA lead, Developer, Flaky hunt; each lists its widgets, and Use replaces the draft) above **Widgets** (every type with a one-line description and an Add button). At 24 widgets the Add buttons are disabled and the card says why.
```

and replace:

```
the confirm step is primary, not danger, because nothing is destroyed.
```

with:

```
the confirm step is primary, not danger, because nothing is destroyed.
- **Catalogue:** Latest run, Failing in latest run, Pass rate this week, Flaky tests, Pass-rate trend (a line with markers and a sentence for screen readers), Failure causes, Regressions and flips, Recent runs (each verdict as a Status Pill), Branch health, Slowest tests, Coverage (plain figures in a definition list), Test cases (the four Cases KPI tiles), My recent failures and My suites. Report widgets ask for their own section and refresh when a new latest run arrives; run widgets poll every 30 seconds.
- **Empty branch:** a widget set to a branch with no runs in its period says "No runs on <branch> in the last N days" with a **Change settings** button that opens Customise on that widget's settings. It is never an error. My recent failures without a name to match says so and offers the same button.
```

- [ ] **Step 3: README.md and docs/SETUP.md**

In `README.md`, with the Edit tool, replace:

```
- **Customisable Overview:** each person arranges their own Overview from widgets, and owners and admins
  set the project's default layout.
```

with:

```
- **Customisable Overview:** each person arranges their own Overview from 14 widgets or a template
  (QA lead, Developer, Flaky hunt), and owners and admins set the project's default layout.
```

replace:

```
- analytics, the report and notifications;
```

with:

```
- analytics, the report, notifications and the customisable Overview;
```

and replace:

```
**Next**, in the agreed order: a customisable Overview, then test impact analysis. The full plan is in
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
```

with:

```
**Next:** test impact analysis. The full plan is in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
```

In `docs/SETUP.md`, with the Edit tool, replace:

```
**Reset to built-in default** goes back to the four standard cards.
```

with:

```
**Reset to built-in default** goes back to the four standard cards.

**Widgets:** Latest run, Failing in latest run, Pass rate this week, Flaky tests, Pass-rate trend,
Failure causes, Regressions and flips, Recent runs, Branch health, Slowest tests, Coverage, Test cases,
My recent failures and My suites. **Add widget** also offers three templates, *QA lead*, *Developer*
and *Flaky hunt*; choosing one replaces the draft, and Cancel still undoes it. **My recent failures**
finds failed runs by the commit author's name as git records it: by default your QEOS full name. If
git spells it differently, or your profile has no full name, set it in the widget's settings. A widget
set to a branch with no runs in its period says so, with a button to change its settings.
```

- [ ] **Step 4: TODO.md and IMPLEMENTATION_PLAN.md**

In `TODO.md`, with the Edit tool, replace:

```
3. [ ] Customisable Overview: a widget catalogue over the existing analytics; a project default layout set by owners/admins, a personal layout per user with "reset to project default"
```

with:

```
3. [x] Customisable Overview (done 2026-10-11, ADR-028, spec `docs/superpowers/specs/2026-10-11-customisable-overview-design.md`): 14 widgets over the existing analytics and three templates; a project default (owners/admins) and a personal layout per user with "reset to project default" (project-service migration 004, optimistic versions, 409 Reload/Overwrite); one widget catalogue file shared by validation and the dashboard registry; test-management `GET /suites?created_by=me`
```

replace:

```
- [ ] Report origin marker (ADR-026 fallback): a Play workflow input → collector field → ingestion `test_runs.origin` column and a backfill. Only if the URL match proves unreliable.
```

with:

```
- [ ] Report origin marker (ADR-026 fallback): a Play workflow input → collector field → ingestion `test_runs.origin` column and a backfill. Only if the URL match proves unreliable.
- [ ] My recent failures by email (ADR-028 follow-up): the collector records the commit author's email (`git log --format=%ae`), ingestion stores it (column and migration), and the widget matches the signed-in user's email instead of a name
- [ ] The project export includes the Overview project default (ADR-028, spec §3.4): needs project-service data in the export, which today holds ingestion data only
```

replace:

```
- [ ] Personal dashboard: my suites, my recent failures *(suggested)*
```

with:

```
- [x] Personal dashboard: my suites, my recent failures — the My suites and My recent failures Overview widgets (ADR-028)
```

and replace:

```
shipped (item 2 under "Execution intelligence and operations", ADR-027). What runs today: README.md and
```

with:

```
shipped (item 2 under "Execution intelligence and operations", ADR-027), and so has the customisable
Overview (item 3, ADR-028). What runs today: README.md and
```

In `IMPLEMENTATION_PLAN.md`, with the Edit tool, replace:

```
   operations"): customisable Overview, test impact analysis.
```

with:

```
   operations"): customisable Overview (done 2026-10-11, ADR-028), then test impact analysis.
```

- [ ] **Step 5: ADR-028 and its INDEX row**

Create `docs/architecture/adr/ADR-028-customisable-overview.md`:

```markdown
# ADR-028: The customisable Overview: layouts in project-service, one shared widget catalogue, "my" widgets matched by name

Status: Accepted (2026-10-11) · Spec: `docs/superpowers/specs/2026-10-11-customisable-overview-design.md` · Plan: `docs/superpowers/plans/2026-10-11-customisable-overview.md`

## Context
The Overview was four fixed cards. Roles want different first screens (a QA lead wants trends and the
report, a developer their branch and what is failing now) and projects need different things (a
flaky-heavy suite, a fast-moving one). The blueprint's "interactive dashboards with customizable
widgets" (Enhanced Collaboration) and v2 backlog F "Personal dashboard: my suites, my recent failures"
ask for the same thing. Everything a widget shows is already computed by ingestion's analytics and the
Report; nothing new is measured.

## Decision
- **Layouts live in project-service**, table `overview_layouts` (migration 004): one optional project
  default per project (`user_id` NULL, a partial unique index) and one optional personal layout per user
  per project (unique `project_id, user_id`), each a JSONB layout with a `version`.
  `GET /projects/{id}/overview-layout` resolves personal → project default → built-in (`effective:
  null`; the dashboard holds the built-in four cards) and also returns the project default itself, which
  Reset and "Edit project default" need. Every role may save and reset a personal layout; owners and
  admins set the project default. The project role is checked on every request, so the personal layout of
  someone who left the organization is never served; such rows are not cleaned up (a few KB each).
- **Optimistic versions:** a save names the version it started from (0 creates); a stale one is a 409
  whose detail carries the stored `{version, updated_by, updated_at}`, which the editor turns into Reload
  or Overwrite. Reset deletes the stored layout rather than saving a copy, so later default changes
  still arrive.
- **One widget catalogue file**, `shared/qeos_shared/overview_widgets.json`: the 14 types, their settings
  and allowed values, and the limits (24 widgets, 16 KB). project-service validates against it
  (`qeos_shared.overview_widgets.load_catalog()`); the dashboard registry imports the same file (the
  dashboard Dockerfile copies it), and a dashboard test fails when the two disagree.
- **Widgets reuse the owning screen's query under the same key**, so two identical widgets, or a widget
  and its full view, cost one request. Report widgets send `sections: [their section]` to
  `POST /analytics/report` and refresh when a new latest run arrives; run widgets poll every 30 s
  (ADR-021). Each widget is code-split and fails in its own card.
- **"My" widgets match by name.** The collector stores the commit author name (`git log --format=%an`),
  not an email, so My recent failures filters the runs list by `author=<name>`: the person's QEOS full
  name by default, or the name as git records it (a widget setting). It never asks without a name. My
  suites uses test-management's `GET /suites?created_by=me`.

## Alternatives rejected
- **Layouts in browser storage:** no project default, and nothing follows a person to another machine.
- **A layout store outside project-service:** layouts belong to a project and its roles, and
  project-service already answers who may do what in a project.
- **Separate widget lists in Python and TypeScript:** they would drift; one file and a check test keep
  them equal.
- **Matching "my" by email now:** needs a collector field, an ingestion column and a migration; tracked
  in TODO.md.
- **Drag-and-drop placement, a widget marketplace, cross-project dashboards:** out of scope (spec §8).
  Move up/down and wide/normal cover the need with keyboard-first controls.

## Consequences
- The gateway is unchanged: `/api/v1/projects/{id}/overview-layout` falls under the existing
  project-service location, and the smoke proves the route.
- The project export (ingestion's NDJSON) does not include the project default; that needs
  project-service data in the export (TODO.md).
- A name shared by two committers, or a changed git name, can mislead My recent failures; the setting is
  the remedy until email matching exists.
- A new widget type means an entry in the catalogue file and in the dashboard registry; the shared test
  and the registry test fail until both agree.
```

In `docs/architecture/adr/INDEX.md`, with the Edit tool, replace:

```
| [ADR-027](ADR-027-monitoring-profile.md) | Monitoring is an opt-in Prometheus/Alertmanager/Grafana compose profile; blueprint metric names; job heartbeats in a table; Grafana behind a QEOS cookie hand-off |
```

with:

```
| [ADR-027](ADR-027-monitoring-profile.md) | Monitoring is an opt-in Prometheus/Alertmanager/Grafana compose profile; blueprint metric names; job heartbeats in a table; Grafana behind a QEOS cookie hand-off |
| [ADR-028](ADR-028-customisable-overview.md) | The customisable Overview: layouts in project-service (project default and personal, optimistic versions), one widget catalogue file shared by validation and the dashboard registry, "my" widgets matched by commit author name |
```

- [ ] **Step 6: The blueprint banner**

In `ARCHITECTURE_BLUEPRINT_V1_0.md`, with the Edit tool, replace:

```
Collaboration (dashboards, report, notifications)
```

with:

```
Collaboration (customisable Overview dashboards with a project default and personal layouts, report, notifications)
```

- [ ] **Step 7: Check the documents**

Run: `git diff --stat -- PRODUCT.md DESIGN.md README.md docs/SETUP.md TODO.md IMPLEMENTATION_PLAN.md ARCHITECTURE_BLUEPRINT_V1_0.md docs/architecture/adr/INDEX.md && git diff --check -- PRODUCT.md DESIGN.md README.md docs/SETUP.md TODO.md IMPLEMENTATION_PLAN.md ARCHITECTURE_BLUEPRINT_V1_0.md docs/architecture/adr/INDEX.md && file docs/architecture/adr/ADR-028-customisable-overview.md`
Expected: eight files changed; `git diff --check` prints nothing (no trailing whitespace, no CRLF); `file` reports `UTF-8 Unicode text` (or `ASCII text`), without `CRLF`.

- [ ] **Step 8: Commit**

```bash
git add docs/architecture/adr/ADR-028-customisable-overview.md PRODUCT.md DESIGN.md README.md docs/SETUP.md TODO.md IMPLEMENTATION_PLAN.md ARCHITECTURE_BLUEPRINT_V1_0.md docs/architecture/adr/INDEX.md
git commit -m "docs: customisable Overview (ADR-028, product rules, design, setup, TODO, blueprint)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docs/architecture/adr/ADR-028-customisable-overview.md PRODUCT.md DESIGN.md README.md docs/SETUP.md TODO.md IMPLEMENTATION_PLAN.md ARCHITECTURE_BLUEPRINT_V1_0.md docs/architecture/adr/INDEX.md
```

---

### Task 23: Phase 3 gate

**Files:** none new (fixes only, in the files of Tasks 16–22).

**Interfaces:** Consumes everything; produces a pushed `master`.

- [ ] **Step 1:** Every Python suite serially and the collector (Task 7 Step 1). Expected: all green.
- [ ] **Step 2:** `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build && node --test ../templates/github/qeos-run.test.mjs`. Expected: all green; 14 widget chunks in the build output.
- [ ] **Step 3:** `bash monitoring/check.sh`; `docker build -t qeos/gateway:ci gateway && docker run --rm qeos/gateway:ci nginx -t`. Expected: `monitoring: all checks passed`; `test is successful`.
- [ ] **Step 4:** The full stack and the smoke:

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```
Expected: `all gateway checks passed`.

- [ ] **Step 5:** By hand at `https://localhost:8443` on a project with runs: Customise → Add widget → Use the Developer layout → Save; every widget loads or says plainly why not; set Recent runs to a branch with no runs and see "No runs on <branch>" with Change settings; open the browser's network panel and confirm two Failure causes widgets with the same settings send one `POST /analytics/report` with `"sections":["failure_causes"]`. Then `docker compose down` (never `-v`).
- [ ] **Step 6:** `git ls-files -s scripts/smoke_gateway.sh` shows `100755`; `git status --short` shows no modified file of this plan; `git push origin master`.

---

## Self-review

**Spec coverage.**
- §1 goal, project default and personal layout, built-in default → Tasks 4, 8, 11, 13, 14. "No new metrics, no AI" → Global Constraints; every widget reads an existing query (Tasks 11, 16–20).
- §2.1 resolution → Task 4 (`get_layout`), Task 11 (`effective ?? BUILTIN_DEFAULT`). §2.2 Customise, bar, toolbar, draft → Tasks 12, 13. §2.3 Edit project default, bar text, "Last changed by", confirmation → Tasks 13 (code), 14 (entry point, tests). §2.4 catalogue of 14 → Tasks 1, 11, 16–20; settings and allowed values → Tasks 1, 3, 8, 13 (form); repeated types → Task 3 test, Task 17 "two identical report widgets". My recent failures by name, default full name, "nothing matches" naming the setting → Task 20 (Rulings 11, 24); email follow-up in TODO → Task 22. §2.5 templates → Task 21. §2.6 sizes and grid → Tasks 11 (CSS, `wide`), 13 (toggle), DESIGN in Tasks 13, 22. §2.7 30 s refresh → Tasks 10, 19, 20; a new run refreshing pass rate and flaky → Task 10 (`newRunStaleKeys`); new-cause marks → Task 11 (Failing in latest run); "No runs yet" → Task 11; title links → every widget definition, tested in Tasks 11, 16–20. "N new runs": Ruling 26. §2.8 discard guard, conflict, default changed, 24-widget limit, focus and live region, 24/44 px buttons, per-widget failure and error boundary, empty branch, no undo → Tasks 10, 13, 16 (and 17–19 for report and run widgets).
- §3.1 table → Task 2. §3.2 validation cases and the shared file → Tasks 1, 3 (Ruling 8), 4 (16 KB, Ruling 6); dashboard test against the file → Tasks 11, 21. §3.3 endpoints, roles, 409 body, gateway unchanged → Task 4 (Rulings 4, 5, 7), Task 6 (smoke, gateway check). §3.4 cascade → Task 2 (Ruling 9); departed user → Task 4; export → Ruling 10 and TODO in Task 22. §3.5 `created_by=me` → Task 5.
- §4 registry, one file per type → Task 11 (Ruling 17); shared queries → Tasks 11, 13, 16, 19 (`flakyWindowQuery`, `branchesViewQuery`, `trendsViewQuery`, `runsFirstPageQuery`); report widgets with their own section → Tasks 17, 18 (Rulings 12, 13); coverage join unchanged → Task 18; lazy loading → Tasks 10, 11; `useOverviewLayout`, `templates.ts` → Tasks 8, 9, 21; editor, blocker, `beforeunload`, conflict → Task 13; cards with h2 link inside an error boundary → Tasks 10, 11; today's four cards with existing tests → Task 11; `ui-ux-pro-max` → every dashboard UI task.
- §5 testing: every endpoint × role, resolution, 409, validation, departed user, cascade → Tasks 2, 3, 4; `created_by=me` → Task 5; each of the 14 widgets with defaults, error state and link → Task 11 (`frameWidgets`, existing OverviewPage tests), Tasks 16–20; editor move, size, add, remove, template, settings, discard guard, conflict, focus and announcements → Tasks 13, 21; "Edit project default" only for owner/admin → Task 14; registry matches the file → Tasks 11, 21; existing Overview tests → Task 11; smoke → Task 6.
- §6 documentation → Tasks 4, 5 (service READMEs, TECHNICAL_SPECIFICATION), 1 (shared README), 13, 14 (DESIGN, SETUP, README for what Phase 2 ships; Ruling 25), 22 (PRODUCT, DESIGN, README, SETUP, TODO, ADR-028, INDEX, blueprint banner, IMPLEMENTATION_PLAN).
- §7 three phases with gates and pushes → Tasks 7, 15, 23. §8 nothing outside scope is built.

**Placeholder scan.** No "TBD", "TODO" (other than the TODO.md file name), "similar to Task N" or undefined helpers. Every code step shows the code; every doc step shows the exact old and new text. Task 6 Step 2 explains the red state of the smoke rather than requiring an old image to be built.

**Type consistency.** Backend: `OverviewLayout`, `validate_layout`, `LayoutIn`, `OverviewLayoutOut`, `ProjectMeta.layout`, `LayoutRowOut`, `StaleVersion.current`, `get_row/save/delete(db, project_id, user_id, …)` match between Tasks 2–4. The 409 detail shape (`code`, `message`, `current`) in Task 4 matches `conflictOf` in Task 9 and the editor tests in Task 13. Dashboard: `StoredLayout`, `StoredWidget`, `WidgetSettings`, `ALL`, `MAX_WIDGETS` (Task 8); `OverviewLayoutState`, `LayoutMode`, `LayoutRow`, `StoredVersion`, `saveLayout`, `deleteLayout` (Task 9); `WidgetProps` (with `heading`, `onOpenSettings`) and `WidgetDefinition` (Task 10) are what every widget file implements; `REGISTRY`, `definitionOf`, `knownWidgets`, `withDefaults`, `widgetTitle`, `addableDefinitions` (Task 11) are what Tasks 13 and 21 call; `Draft`, `DraftAction` (`add` carries `id`), `nextWidgetId`, `isDirty` (Task 12) match the editor; `EditSession.openSettingsFor` (Task 13) is used by Task 16; `AddWidgetPanel` gains `onTemplate` in Task 21 together with the editor change; `useWidgetReport`/`reportLink` (Task 17) are used in Task 18; `branchesViewQuery` (Task 13) in Task 19; `runsFirstPageQuery` (Task 19) in Task 20; the registry test's `PENDING` literal shrinks in Tasks 16–20 with matching old strings and disappears in Task 21. Test helpers `mockOverviewData`, `personalState`, `projectState`, `renderOverview`, `RUN`, `FAILING_RUN`, `BUILTIN_STATE` are defined once in Task 11.

**Review Focus.** 1 → Task 13 `a background refetch while editing keeps the draft`. 2 → Task 20 `with no full name and no setting, My recent failures asks for a name and sends nothing`. 3 → Task 14 `an owner with a personal layout edits the project default, not their own` (and Task 13 `session.test.ts`). 4 → Task 11 `a stored widget of an unknown type is skipped and logged once`. 5 → Task 3 `test_refused` cases for `rows=True`, `rows=5.0`, `rows="5"`.
