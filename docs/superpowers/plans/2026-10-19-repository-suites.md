# Repository Suites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The OBT suite workflows' matrix legs appear as read-only suites in QEOS (synced with the cases), run from QEOS through the repository's own workflows, and hand-made suites can be filled from the Test Cases selection.

**Architecture:** The collector sends the raw workflow files with the feature import; test-management parses them (PyYAML `safe_load`), plans suite changes inside the existing import transaction, and stores repository suites as `suites` rows with `origin = repository` whose `suite_cases` are recomputed at every sync. Run requests gain a per-row `workflow`; repository runs dispatch that workflow with `suites`/`request_id` inputs after checking GitHub is not already running it. Stage 1 (Tasks 1–8) ships sync, display and editing; stage 2 (Tasks 9–12) ships running.

**Tech Stack:** test-management (FastAPI, SQLAlchemy, Alembic, pytest, respx), collector (stdlib only, pytest), dashboard (React, TanStack Query, Vitest, msw), GitHub Actions YAML in OBT.

**Spec:** `docs/superpowers/specs/2026-10-19-repository-suites-design.md`

## Global Constraints

- The collector keeps `dependencies = []`; it never parses YAML. test-management parses with `yaml.safe_load` only (add `PyYAML` to `platforms/test-management-service/requirements.txt`).
- Repository suites are read-only: `PATCH`, `PUT /cases`, `DELETE` on them answer 409 `{"code": "repository_suite", "message": "Managed by the repository: change the workflow instead."}`.
- A workflow is stored and dispatched by bare file name matching `^[A-Za-z0-9._-]{1,100}\.ya?ml$`; only files directly under `.github/workflows/` are synced.
- QEOS dispatches only a `workflow` taken from a synced suite row (or the CI target), never a name from the browser.
- A QEOS-started repository run has run-name exactly `QEOS #<request_id>`.
- Old payloads must keep working: `ImportRequest` is `extra="forbid"`, so the collector sends `suite_files`/`suite_patterns`/`source_repo` only when `--suites` is given; the dashboard's own import never sends them.
- `MAX_SUITE_CASES = 1000`: a repository suite over it is cut at 1000 with a warning.
- One active run request per (project, workflow).
- OBT changes go on branch `qeos/repository-suites` with a pull request; never push OBT `main`. QEOS commits go to `master` after the CI-equivalent checks (each Python suite touched, dashboard `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build`, `python scripts/check_architecture_docs.py`).
- Every behaviour commit updates the affected `.md` (README, SETUP, service READMEs, DESIGN, TECHNICAL_SPECIFICATION, SECURITY, TODO).
- Dashboard UI work: invoke the `ui-ux-pro-max` skill first; follow `DESIGN.md`.

## Review Focus

1. **`matrix` given as a YAML mapping, not a JSON string**, or the caller job named differently: the parser accepts both forms and finds the job by `uses` ending in `suite-runner.yml` (test in Task 2).
2. **`test_path` with repeated spaces, a trailing space, or a folder without a trailing `/`**: entries split on any whitespace; an entry not ending in `.feature` is a folder whether or not it ends in `/` (test in Task 2).
3. **A case archived or moved after the last sync**: membership excludes archived cases and follows `source_path` at the next sync, without duplicating `suite_cases` rows (test in Task 3).
4. **GitHub cannot be asked whether the workflow is busy** (timeout, 5xx, rate limit): the run is refused with 503-style detail, never dispatched blind (test in Task 9).
5. **A sync whose `--suites` pattern matches no file at all** (typo in the workflow): no group is deleted unless a previously synced workflow matches the pattern, and the collector prints that the pattern matched nothing (test in Task 4).

---

## Stage 1 — sync, display, editing

### Task 1: Repository suite columns and read-only guard

**Files:**
- Create: `platforms/test-management-service/alembic/versions/009_repository_suites.py`
- Modify: `platforms/test-management-service/src/casebook/models/suite.py`, `src/casebook/schemas/suite.py`, `src/casebook/service/suite_service.py`, `src/casebook/api/v1/endpoints/suites.py`
- Test: `platforms/test-management-service/tests/integration/test_repository_suites_api.py`, extend `tests/unit/test_migration*.py` if it checks columns

**Interfaces:**
- Produces: `Suite.origin: str` (`"manual"` | `"repository"`, server default `manual`), `Suite.workflow: str | None`, `Suite.group_name: str | None`, `Suite.external_id: str | None`, `Suite.shard: str | None`, `Suite.test_paths: list[str] | None` (JSON), `Suite.source_repo: str | None`; unique index `uq_suites_repository_leg` on `(project_id, workflow, external_id)` where `origin = 'repository'`; check `origin IN ('manual','repository')`. `RunRequest.workflow: str | None` (String 100). `suite_service.RepositorySuite(Exception)`; `suite_service.ensure_manual(row: Suite) -> None` raises it.
- `SuiteOut` gains `origin, workflow, group_name, external_id, shard, test_paths, source_repo`.

- [ ] **Step 1: Write failing tests** — `test_list_returns_origin_fields` (a manual suite lists `origin == "manual"` and `workflow is None`); `test_repository_suite_is_read_only` (insert a `Suite(origin="repository", workflow="suite-flights.yml", external_id="flights-amadeus-non-booking", group_name="Flights")` directly; `PATCH`, `PUT /cases`, `DELETE` each answer 409 with `detail["code"] == "repository_suite"`).
- [ ] **Step 2: Run** `python -m pytest tests/integration/test_repository_suites_api.py -q` — FAIL.
- [ ] **Step 3: Implement** migration 009 (batch mode for SQLite, existing rows `origin = 'manual'`, add `run_requests.workflow` nullable, backfill it from `ci_targets.workflow` per project), model fields, schema fields, `ensure_manual` called in the three endpoints before any change.
- [ ] **Step 4: Run** the new tests and the whole service suite `python -m pytest tests/ -q` — PASS (migration drift test included).
- [ ] **Step 5: Commit** `feat(test-management): repository suite columns; repository suites are read-only`

### Task 2: Workflow parser

**Files:**
- Create: `platforms/test-management-service/src/casebook/repo_suites/__init__.py`, `src/casebook/repo_suites/parse.py`
- Modify: `platforms/test-management-service/requirements.txt` (add `PyYAML==6.0.2`)
- Test: `platforms/test-management-service/tests/unit/test_repo_suites_parse.py`, fixtures copied from OBT into `tests/fixtures/workflows/` (`suite-flights.yml`, `suite-preprod.yml`, trimmed to 3 legs each)

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class ParsedLeg:
      external_id: str; name: str; folders: tuple[str, ...]; files: tuple[str, ...]; shard: str | None
  @dataclass(frozen=True)
  class ParsedWorkflow:
      workflow: str; group_name: str; legs: tuple[ParsedLeg, ...]
  @dataclass(frozen=True)
  class ParseIssue:
      workflow: str; external_id: str | None; message: str
  def parse_workflow(path: str, content: str) -> tuple[ParsedWorkflow | None, list[ParseIssue]]
  ```
  `path` is the repository path (`.github/workflows/suite-flights.yml`); `ParsedWorkflow.workflow` is the bare name. `None` means the file is unusable (keep its previous suites).

- [ ] **Step 1: Write failing tests**:
  - `test_flights_fixture` → `group_name == "Flights"`, first leg `external_id == "flights-amadeus-non-booking"`, `folders == ("tests/features/flights/flights_amadeus/flights_amadeus_non_booking",)`, `shard is None`; a shard leg has `shard == "1/2"`.
  - `test_preprod_fixture` → leg `files` are the listed `.feature` paths, `folders == ()`.
  - `test_matrix_as_mapping` (Review Focus 1) — same result when `with.matrix` is a YAML mapping.
  - `test_whitespace_and_folder_without_slash` (Review Focus 2) — `"a/  b.feature  c "` gives `folders == ("a", "c")`, `files == ("b.feature",)`.
  - Issues: `test_leg_without_suite_id` and `test_leg_without_test_path` (leg skipped, one `ParseIssue` each); `test_duplicate_suite_id` (second skipped, issue); `test_bad_yaml` and `test_no_runner_job` → `(None, [issue])`; `test_path_outside_workflows_dir` → `(None, [issue])`.
  - `test_group_name_fallback` → `name: "Nightly things"` stays `"Nightly things"`; missing `name` → file stem `suite-x` → `"suite-x"`.
- [ ] **Step 2: Run** `python -m pytest tests/unit/test_repo_suites_parse.py -q` — FAIL.
- [ ] **Step 3: Implement** `parse_workflow`: `yaml.safe_load`; group name strips a leading `"Suite - "`; the caller job is any job whose `uses` ends with `suite-runner.yml`; `with.matrix` may be a `str` (parse with `json.loads`) or a `dict`; read `include`; normalise folder entries by stripping trailing `/`.
- [ ] **Step 4: Run** the tests — PASS.
- [ ] **Step 5: Commit** `feat(test-management): parse suite workflows into repository suite legs`

### Task 3: Sync plan and apply inside the import

**Files:**
- Create: `platforms/test-management-service/src/casebook/repo_suites/sync.py`
- Modify: `src/casebook/schemas/case_import.py`, `src/casebook/api/v1/endpoints/case_import.py`, `src/casebook/service/import_service.py` (only to call the sync after `apply_plan` in the same transaction), `src/casebook/gherkin_import/plan.py` (`plan_hash` input)
- Test: `platforms/test-management-service/tests/integration/test_repository_suites_sync.py`

**Interfaces:**
- Consumes: `parse_workflow` (Task 2), `Suite` fields (Task 1).
- Produces:
  - `ImportRequest` gains `suite_files: list[ImportFile] | None = None`, `suite_patterns: list[str] | None = Field(None, max_length=20)` (each ≤ 200 chars), `source_repo: str | None = Field(None, pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")`. `suite_files` without `suite_patterns` → 422.
  - `ImportResult` gains `suite_changes: list[{"action": "created"|"updated"|"deleted", "workflow", "external_id", "name"}]` and `suite_warnings: list[{"workflow", "external_id", "message"}]` (both default `[]`).
  - `sync.plan_suites(db, project_id, files: list[tuple[str, str]], patterns: list[str], source_repo: str | None, case_paths: list[tuple[int, str]]) -> SuitePlan` where `case_paths` are the (case id, source_path) of live imported cases **after** the case plan; `SuitePlan.changes`, `SuitePlan.warnings`, `SuitePlan.hash_input() -> list`.
  - `sync.apply_suites(db, project_id, user_id, plan: SuitePlan) -> None` (no commit; the import commits).
- Rules (spec 5.2/5.3): membership = live imported cases whose `source_path` equals a file or starts with `folder + "/"`, ordered by `source_path` then `scenario_line`; recomputed at every sync (delete and re-insert `suite_cases` only when the ordered list changed). Deletion by pattern: a stored `workflow` whose `.github/workflows/<workflow>` matches one of `patterns` (`fnmatch`) and is not among the sent files → delete its suites. Name clash with a manual suite → name = `external_id`, warning `"Name taken by a suite made in QEOS; using <external_id>"`. Warnings also for: a folder/file entry matching no live case (`"<entry> matches no imported case"`), every `ParseIssue`, a suite cut at 1000 (`"Over 1000 cases; only the first 1000 are in the suite"`). `plan_hash` includes `SuitePlan.hash_input()`.

- [ ] **Step 1: Write failing tests** (through `POST /cases/import` with feature files + `suite_files` from the fixtures):
  - `test_first_sync_creates_groups_and_members` — the amadeus leg holds exactly the cases under its folder, in path/line order.
  - `test_resync_updates_name_and_paths` and `test_leg_removed_deletes_suite`.
  - `test_archived_and_moved_cases_follow` (Review Focus 3) — archive one case and move another between folders by re-importing; members follow; no duplicate `suite_cases`.
  - `test_deleted_workflow_matching_pattern_deletes_group`; `test_workflow_outside_pattern_is_kept` (sync with pattern `.github/workflows/suite-hotels.yml` keeps Flights).
  - `test_unparsable_workflow_keeps_previous_suites` and its warning.
  - `test_name_clash_uses_suite_id`; `test_entry_matching_nothing_warns`.
  - `test_dry_run_reports_suite_changes_and_hash_changes` — `plan_hash` differs when only a workflow changed.
  - `test_without_suite_files_nothing_changes` — an old payload leaves repository suites alone.
  - `test_source_repo_stored`.
- [ ] **Step 2: Run** `python -m pytest tests/integration/test_repository_suites_sync.py -q` — FAIL.
- [ ] **Step 3: Implement** `plan_suites` / `apply_suites` and wire them in `import_cases` (plan after the case plan, include in dry run output and `plan_hash`, apply in the same transaction as `apply_plan`).
- [ ] **Step 4: Run** the new tests and `python -m pytest tests/ -q` — PASS.
- [ ] **Step 5: Commit** `feat(test-management): sync repository suites with the case import`

### Task 4: Collector `--suites`

**Files:**
- Modify: `collector/src/qeos_collector/cli.py` (import-features options, lines ~139-155), `collector/src/qeos_collector/features.py` (`run_import`, `report`), `collector/README.md`, collector version (wherever `dynamic` version is read)
- Test: `collector/tests/test_features.py`, `collector/tests/fake_qeos.py` (accept and echo the new fields)

**Interfaces:**
- Consumes: the request/response fields of Task 3.
- Produces: `qeos-collector import-features [PATTERN...] --suites PATTERN` (repeatable). `run_import(..., suite_files: list | None = None, suite_patterns: list | None = None, source_repo: str | None = None)`. `report` prints suite changes as `Suites: N created, N updated, N deleted` and each warning as `warning: <workflow> <external_id>: <message>`.

- [ ] **Step 1: Write failing tests**: `test_suites_files_sent_with_patterns_and_repo` (`GITHUB_REPOSITORY=atriis/obt` in env → payload has `suite_files`, `suite_patterns`, `source_repo`); `test_no_suites_option_sends_old_payload` (keys absent); `test_suite_warnings_printed`; `test_strict_fails_on_suite_warning` (exit 1); `test_pattern_matching_no_file_is_reported` (Review Focus 5: prints `--suites pattern matched no file: <pattern>` and still sends the pattern).
- [ ] **Step 2: Run** `python -m pytest collector/tests/test_features.py -q` — FAIL.
- [ ] **Step 3: Implement** using the existing `collect_files` for the suite patterns.
- [ ] **Step 4: Run** `python -m pytest collector -q` — PASS.
- [ ] **Step 5: Commit** `feat(collector): import-features --suites sends the suite workflows`; bump the collector minor version and record the release steps (tag `collector-vX.Y.0`, move `collector-v0`) for Task 8.

### Task 5: Append to a suite and the "Not in any suite" filter

**Files:**
- Modify: `src/casebook/schemas/suite.py`, `src/casebook/service/suite_service.py`, `src/casebook/api/v1/endpoints/suites.py`, `src/casebook/schemas/case.py` (`CaseSearch`), `src/casebook/api/v1/endpoints/cases.py`, `src/casebook/service/case_service.py` (`filtered_cases`)
- Test: `tests/integration/test_suite_append.py`, `tests/integration/test_cases_suite_filter.py`

**Interfaces:**
- Produces: `POST /projects/{pid}/suites/{sid}/cases/append` body `SuiteCasesIn` → `{"added": int, "already": int, "suite": SuiteDetail}`; `suite_service.append_cases(db, row, numbers) -> tuple[int, int]` (raises `RepositorySuite`, `BadCaseList`; 422 above 1000 total). `filtered_cases(..., suite: Literal["none"] | None = None)`; `GET /cases?suite=none` and `CaseSearch.suite: Literal["none"] | None`.
  (Path is `/cases/append`, not `cases:append`: FastAPI routes on `/` segments.)

- [ ] **Step 1: Write failing tests**: `test_append_skips_existing_keeps_order`, `test_append_to_repository_suite_is_409`, `test_append_over_1000_is_422`, `test_append_unknown_case_is_422`; `test_none_lists_imported_cases_in_no_repository_suite` (a case only in a manual suite is listed; manual-origin cases and archived cases are not), the same through `POST /cases/search`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** `suite=none`: imported (`source_key` not null), not archived, `NOT EXISTS` a `suite_cases` row joined to a `suites` row with `origin = 'repository'`.
- [ ] **Step 4: Run** `python -m pytest tests/ -q` — PASS.
- [ ] **Step 5: Commit** `feat(test-management): append cases to a suite; filter cases in no repository suite`

### Task 6: Dashboard — grouped Suites tab and read-only repository suite page

**Files:**
- Modify: `dashboard/src/api/cases.ts` (`Suite` gains the Task 1 fields), `dashboard/src/pages/SuitesPage.tsx`, `dashboard/src/pages/SuiteDetailPage.tsx`, `DESIGN.md`
- Test: `dashboard/src/pages/SuitesPage.test.tsx`, `dashboard/src/pages/SuiteDetailPage.test.tsx`

**Interfaces:**
- Consumes: `SuiteOut` fields (Task 1).
- Produces: `groupSuites(suites: Suite[]): { group: string; workflow: string | null; suites: Suite[] }[]` exported from `SuitesPage.tsx` (repository groups ordered by name, then `"Made in QEOS"` last).

- [ ] **Step 0:** invoke the `ui-ux-pro-max` skill.
- [ ] **Step 1: Write failing tests**: groups render as headings "Flights" / "Made in QEOS" with suite counts; a sharded suite shows "Half 1 of 2"; a repository row shows "From repository"; the New suite form still creates a manual suite; the repository detail page shows workflow `suite-flights.yml`, `flights-amadeus-non-booking`, its `test_paths`, the note "Managed by the repository: change the workflow to change this suite.", the case list, and has no Save, Move, Remove or "Find cases to add" controls; a manual suite page is unchanged.
- [ ] **Step 2: Run** `npx vitest run src/pages/SuitesPage.test.tsx src/pages/SuiteDetailPage.test.tsx` — FAIL.
- [ ] **Step 3: Implement** with collapsible groups (`<details>`/`<summary>` or the existing disclosure pattern), `table.data`, sharded note "GitHub splits this folder between Half 1 and Half 2 at run time; both list the whole folder." No Run buttons yet (Task 10).
- [ ] **Step 4: Run** the tests, then `npm run lint && npm run typecheck` — PASS.
- [ ] **Step 5: Commit** `feat(dashboard): repository suites grouped by workflow, read-only suite page`

### Task 7: Dashboard — Add to suite and "Not in any suite"

**Files:**
- Modify: `dashboard/src/api/cases.ts` (`appendSuiteCases`, `CaseQuery.suite`, `CaseSearchBody.suite`), `dashboard/src/pages/CasesPage.tsx`, `DESIGN.md`
- Create: `dashboard/src/components/AddToSuiteDialog.tsx`
- Test: `dashboard/src/components/AddToSuiteDialog.test.tsx`, `dashboard/src/pages/CasesPage.test.tsx` (extend)

**Interfaces:**
- Consumes: Task 5 endpoints.
- Produces: `appendSuiteCases(projectId: number, suiteId: number, numbers: number[]): Promise<{ added: number; already: number; suite: SuiteDetail }>`; `<AddToSuiteDialog projectId numbers onDone />`.

- [ ] **Step 0:** invoke the `ui-ux-pro-max` skill.
- [ ] **Step 1: Write failing tests**: the selection bar shows "Add to suite" next to "Run selected"; the dialog lists only manual suites; choosing one sends the selected numbers and shows "Added 3 cases to Smoke (2 were already there)." with a link to the suite; "New suite" with a name creates it then appends; an empty name shows a field error; a 409 name clash shows "A suite with this name already exists."; the "Suite" filter offers "Not in any suite" and sends `suite: "none"` in the search body; the selection survives the dialog closing.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** reusing the existing dialog and `FilterSelect` patterns.
- [ ] **Step 4: Run** the tests, `npm run lint`, `npm run typecheck` — PASS.
- [ ] **Step 5: Commit** `feat(dashboard): add the selected cases to a suite; Not in any suite filter`

### Task 8: Stage 1 docs, ADR-035, collector release, OBT sync trigger

**Files:**
- Create: `docs/architecture/adr/ADR-035-repository-suites.md` (sync and read-only parts; the run part is completed in Task 12), add to `docs/architecture/adr/INDEX.md`
- Modify: `docs/SETUP.md` (Gherkin sync section: `--suites ".github/workflows/suite-*.yml"`, the trigger paths, what syncs, warnings), `platforms/test-management-service/README.md`, `collector/README.md`, `TECHNICAL_SPECIFICATION.md`, `README.md` feature list, `TODO.md` (tick the stage-1 parts), `dashboard/src/pages/ProjectSettingsPage.tsx` sync template (lines ~72-97: add the workflow paths to `on.push.paths` and the `--suites` option)
- OBT (branch `qeos/repository-suites`): `.github/workflows/qeos-sync-cases.yml` — `paths: ["tests/features/**", ".github/workflows/suite-*.yml"]` and `--suites ".github/workflows/suite-*.yml"`

- [ ] **Step 1:** Update the Project Settings template test (`ProjectSettingsPage.test.tsx`) to expect the new paths and option; run it — FAIL; change the template; run — PASS.
- [ ] **Step 2:** Write the docs and ADR-035 (context, decision, alternatives from the spec: tags, generic `qeos-run.yml`; consequences).
- [ ] **Step 3:** Run every CI-equivalent check (Global Constraints) — all green.
- [ ] **Step 4:** Commit `docs: repository suites stage 1 (ADR-035)` and push to `master`; tag the collector release as recorded in Task 4 and move `collector-v0`; wait for CI green.
- [ ] **Step 5:** In OBT, create branch `qeos/repository-suites`, commit the sync change, push the branch, open a PR titled "QEOS: sync suite workflows into QEOS suites" (body: what changes, that nightly behaviour is unchanged, and **merge only after the QEOS at the repository's `QEOS_URL` runs this test-management version**: an older server answers 422 to the new fields and every case sync would fail). After merge, run "QEOS sync test cases" by hand once and check the Suites tab shows the five groups.

## Stage 2 — run from QEOS

### Task 9: Repository runs in test-management

**Files:**
- Create: `platforms/test-management-service/alembic/versions/010_run_request_per_workflow.py`
- Modify: `src/casebook/models/ci.py` (index), `src/casebook/schemas/ci.py` (`RunRequestIn`), `src/casebook/service/run_request_service.py`, `src/casebook/utils/github_client.py`, `src/casebook/api/v1/endpoints/run_requests.py`
- Test: `tests/integration/test_repository_runs.py`, `tests/unit/test_github_client.py` (extend)

**Interfaces:**
- Consumes: `Suite.origin/workflow/external_id/source_repo` (Task 1), `RunRequest.workflow` (Task 1).
- Produces:
  - `RunRequestIn.workflow_group: str | None` (bare workflow name); exactly one of `case_numbers`, `suite_id`, `workflow_group`.
  - `github_client.busy_run(token, repo, workflow, ref) -> dict | None` — the newest run of the workflow on `ref` with status in `queued, in_progress, waiting, pending, requested`; raises `GitHubError` / `RateLimited` as other calls.
  - `run_request_service.WorkflowBusy(Exception)` with `run_url: str | None, started_at: datetime | None, group_name: str`; `RepositoryNotTarget(Exception)`.
  - API errors: 409 `{"code": "workflow_busy", "message": "<Group> is already running on GitHub (started HH:MM). Try again when it finishes.", "run_url"}`; 409 `{"code": "repository_mismatch", "message": "Set up Run from QEOS in Project Settings for <source_repo>"}`; 503 `{"code": "github_unavailable", "message": "GitHub could not be asked whether <Group> is running; try again."}`; 409 run-active message names the workflow.
  - Index `uq_run_requests_one_active` becomes unique on `(project_id, workflow)` with the same `ACTIVE_WHERE`; migration 010 fills null `workflow` first.
- Rules: a repository `suite_id` or a `workflow_group` builds `selection` from the suite(s)' current members (number, key, name, path) without `build_selection`'s checks; `skipped_manual = 0`; inputs `{"suites": "<external_id>" | "", "request_id": "<id>"}`; dispatched to `suite.workflow` on the CI target's repo and ref; requires `ci_target.repo.lower() == suite.source_repo.lower()`. `refresh`, `_match` and Stop use `row.workflow`.

- [ ] **Step 1: Write failing tests** (respx for GitHub): `test_run_repository_suite_dispatches_its_workflow` (URL `/actions/workflows/suite-flights.yml/dispatches`, inputs exactly `{"suites": "flights-amadeus-non-booking", "request_id": "<id>"}`); `test_run_all_sends_blank_suites`; `test_large_group_is_not_capped_at_200`; `test_empty_membership_still_runs`; `test_busy_workflow_is_409_and_nothing_dispatched`; `test_github_unreachable_refuses` (Review Focus 4: timeout and 500 on the busy check → 503, no dispatch, no row left active); `test_repository_mismatch_is_409`; `test_two_workflows_run_at_once` and `test_same_workflow_twice_is_run_active`; `test_hand_made_suite_still_uses_ci_target_workflow`; `test_unknown_workflow_group_is_404`; `test_refresh_matches_title_in_row_workflow` (204 path, title `QEOS #<id>`).
- [ ] **Step 2: Run** `python -m pytest tests/integration/test_repository_runs.py -q` — FAIL.
- [ ] **Step 3: Implement** the service branches, `busy_run`, migration 010, endpoint error mapping.
- [ ] **Step 4: Run** `python -m pytest tests/ -q` — PASS (existing run-request tests unchanged).
- [ ] **Step 5: Commit** `feat(test-management): run repository suites through their own workflows, one active run per workflow`

### Task 10: Dashboard — Run and Run all for repository suites

**Files:**
- Modify: `dashboard/src/api/` run-request client (where `RunControl` posts; add `workflow_group`), `dashboard/src/components/RunControl.tsx`, `dashboard/src/pages/SuitesPage.tsx`, `dashboard/src/pages/SuiteDetailPage.tsx`, `DESIGN.md`
- Test: `dashboard/src/components/RunControl.test.tsx` (or the existing run tests), `SuitesPage.test.tsx`, `SuiteDetailPage.test.tsx`

**Interfaces:**
- Consumes: Task 9 request and error codes; the project's CI target (`GET /ci-target`: `repo`, `configured`).

- [ ] **Step 0:** invoke the `ui-ux-pro-max` skill.
- [ ] **Step 1: Write failing tests**: each repository suite row and the repository suite page have "Run" (accessible name "Run <suite name>"); each group has "Run all" ("Run all <group>"); the dialog says "Starts suite-flights.yml for flights-amadeus-non-booking on GitHub."; Run all says "Starts suite-flights.yml for all its suites."; an empty suite shows "QEOS has no imported cases for this suite; the workflow runs its folders as configured."; 409 `workflow_busy` shows its message and a "View on GitHub" link; `repository_mismatch` disables Run with its message and a link to Project Settings; 503 `github_unavailable` shows its message with Retry.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** on top of `RunControl`.
- [ ] **Step 4: Run** tests, `npm run lint`, `npm run typecheck` — PASS.
- [ ] **Step 5: Commit** `feat(dashboard): run repository suites and whole workflows from Suites`

### Task 11: OBT workflow changes and `qeos-run.yml` (PR) plus QEOS templates

**Files:**
- OBT branch `qeos/repository-suites`: `.github/workflows/suite-flights.yml`, `suite-hotels.yml`, `suite-shell.yml`, `suite-transportation.yml`, `suite-preprod.yml`, `suite-runner.yml`, `rerun-runner.yml` (and `rerun-*.yml` if they resolve "latest run" themselves), new `.github/workflows/qeos-run.yml`
- QEOS: `templates/github/repository-suites.md` (the snippets below, for other customers), `templates/github/qeos-run.yml` only if a general improvement falls out

**Interfaces:**
- Consumes: run-name contract and inputs of Task 9.
- Produces (OBT): each caller workflow's `workflow_dispatch.inputs` gains `suites` (string, default `''`) and `request_id` (string, default `''`), passed to `suite-runner.yml` as `with: suites, request_id`; `run-name` = `QEOS #<request_id>` when set, else today's expression (`suite-preprod.yml` gains a `run-name`). `suite-runner.yml` gains inputs `suites`, `request_id`; a first job `select` builds the filtered `matrix` and `expected-suites` with `jq` (blank = unchanged) and fails with `::error::Unknown suite_id: <id>` for an unknown id; the test job uses `fromJSON(needs.select.outputs.matrix)`; when `request_id` is set it does not download or publish Allure history. Every "latest run" lookup (`history-workflow` download, `rerun-runner.yml` blank `run_id`) filters out runs whose `display_title` starts with `QEOS #`. `qeos-run.yml`: the QEOS template's inputs (`paths`, `names`, `request_id`), run-name `QEOS #<request_id>`, `npx cucumber-js --profile ci --retry 1`, the same environment secrets as `suite-runner.yml`, the collector upload step copied from `suite-runner.yml:273`.

- [ ] **Step 1:** Make the changes on the OBT branch. Validate every changed workflow with `actionlint` if available locally; otherwise `python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))"` per file and a `jq` dry run of the filter on the Flights matrix (`suites="flights-amadeus-non-booking"` → 1 row; blank → 25; `"nope"` → error).
- [ ] **Step 2:** Push the branch and open a PR "QEOS: run suites from QEOS (suites/request_id inputs, qeos-run.yml)" whose body states: blank inputs keep the nightly, scheduler, reruns and manual runs unchanged; QEOS runs skip Allure history; how to test (dispatch Suite - Flights by hand with `suites=flights-amadeus-non-booking`).
- [ ] **Step 3:** Write `templates/github/repository-suites.md` in QEOS with the input block, the `jq` select job and the run-name rule.
- [ ] **Step 4:** Commit in QEOS `docs(templates): repository suites workflow snippets`.

### Task 12: Stage 2 docs, end-to-end check, push

**Files:**
- Modify: `docs/architecture/adr/ADR-035-repository-suites.md` (run part; amends ADR-025: per-row workflow, one active run per workflow), `docs/architecture/adr/ADR-025-run-tests-through-customer-ci.md` (a line pointing to ADR-035), `docs/SETUP.md` (Run from QEOS: repository suites, busy refusal, CI target must match the suites' repository), `docs/MICROSOFT_SIGN_IN.md` untouched, `platforms/test-management-service/README.md`, `SECURITY.md` (dispatch only synced workflow names; token scope unchanged), `TECHNICAL_SPECIFICATION.md`, `DESIGN.md`, `TODO.md` (tick the project; keep the three follow-ups)

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2:** Run every CI-equivalent check — all green.
- [ ] **Step 3:** Commit `docs: repository suites stage 2 (ADR-035, ADR-025)` and push to `master`; wait for CI green.
- [ ] **Step 4:** After the OBT PR is merged: rebuild the local stack (`docker compose up -d --build --wait gateway`), run one small repository suite from QEOS (`flights-ua-ndc-booking` or the smallest leg), and check: the GitHub run is titled `QEOS #<id>`, only that leg ran, results appear under Runs, and a second Run on the same workflow is refused as busy.
