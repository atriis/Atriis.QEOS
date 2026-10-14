# Suggested Tests First in CI (Test Impact Release B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In CI, run the Cucumber scenarios a change likely affects first and the rest after, as one run, with an opt-in "suggested tests only" mode whose runs never distort the impact statistics or the accuracy figure.

**Architecture:**
- **ingestion-service:** stores each run's `scope` (`full` or `impact-subset`) and `stages` (migration 020). It leaves subset runs out of the impact statistics, the outcome evaluation and the accuracy figure, and gives the collector its own API-key route to the existing scoring, `POST /api/v1/collect/impact`.
- **Dashboard and notifications:** they label partial runs.
- **The collector:**
  - It gains `impact`, which prints the suggestion.
  - It gains `run-impact`, which:
    - discovers scenarios with a Cucumber dry run;
    - splits them into two rerun files;
    - checks with a second dry run that the rerun file alone decides what runs;
    - runs the two stages;
    - uploads both JSON reports as one run.
- **Release:** collector 0.6.0.

**Tech Stack:**
- **ingestion-service:** FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, pytest (SQLite in tests), PostgreSQL 15.
- **Collector:** Python stdlib only (3.9+), pytest.
- **Dashboard:** React 19, TypeScript 6, TanStack Query 5, vitest, MSW 3 and Testing Library.
- **Runtime targets:** cucumber-js (12.6.0 verified locally), cucumber-jvm through Maven/Gradle system properties, and Ruby Cucumber.
- **Integrations:** a GitHub composite action, a Jenkins shared library, GitLab and Azure templates, and the NGINX gateway (unchanged).

**Spec:** `docs/superpowers/specs/2026-10-13-suggested-tests-first-design.md` (builds on `docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md` and its §9, and ADR-029).

> **Phases.** Each phase ships on its own (spec §7), and its last task is a gate:
> - every suite;
> - dashboard lint, typecheck, vitest and build;
> - the collector suite;
> - `monitoring/check.sh`;
> - `scripts/check_architecture_docs.py`;
> - `nginx -t`;
> - the gateway smoke;
> - then a push to `master`.
>
> The phases are:
> - **P1, QEOS side:** Tasks 1–10.
> - **P2, collector `impact`:** Tasks 11–14.
> - **P3, `run-impact`, integrations, docs and collector 0.6.0:** Tasks 15–22.

## Global Constraints

Quoted from the spec; every task's requirements include them.

- **Goal (§1):** "run the tests likely affected by a change **first**, so failures in the changed area show up in minutes, while the full suite still runs. Optionally, a team may run **only** the suggested tests; such runs are marked partial and never distort the statistics or the accuracy figure."
- **Scope (§1):** "Cucumber and a plain list now; JUnit/Maven/Gradle, pytest and Playwright/JS formats as small follow-ups. Two stages in one run by default; a suggested-only mode with a safe fallback."
- **`impact` (§2.1):** "Computes the changed files as uploads do (`gitdiff.collect_changes`: the PR or merge-request base, else the previous commit), calls `POST /analytics/impact` with `{changed_paths, branch}` and prints the suggestion."
  - "`--format cucumber` (default for `.feature` projects): one `path/to/x.feature:LINE` per line; when a scenario has no known line, a `--name "<scenario>"` filter instead. Scenario outline rows are individual lines."
  - "`--format list`: one test per line, `suite<TAB>class<TAB>name`."
  - "`--format json`: the full suggestion with evidence and kinds."
  - "`--out FILE`: write there instead of stdout."
  - "Exit codes: `0` a suggestion was printed; `3` nothing to suggest or not enough history; `4` QEOS unreachable or timed out (503 `impact_timeout`). A pipeline branches on them; none means "tests failed"."
- **`run-impact` (§2.2):**
  - "**Discovery:** runs the test command in Cucumber's dry-run mode (`--dry-run --format json`, with the user's own tags, profiles and paths) to list the scenarios the command would run."
  - "**Stage 1:** the suggested scenarios that discovery found, passed through a rerun file (`@file`), which both `cucumber` (JVM, Ruby) and `cucumber-js` accept, so no command-line length limit applies. Suggested scenarios excluded by the user's filters are reported as skipped by the filter."
  - "**Stage 2:** every other discovered scenario, through a second rerun file; no scenario runs twice."
  - "**Upload:** both stages' reports are uploaded as **one run** with `scope = full` and its `stages`."
  - "`--fail-fast`: stop after a failing stage 1; upload it with `scope = impact-subset` and `stopped_after_stage = 1`."
  - "`--suggested-only`: run stage 1 only, `scope = impact-subset`. When there is no suggestion (exit 3 or 4 of the scoring), run the **full suite** instead and log why, unless `--no-fallback`."
  - "`--gate` keeps its meaning (exit 1 on failures outside quarantine) and judges the uploaded run."
  - "**CI summary:** in GitHub Actions, a table in the job's step summary (`$GITHUB_STEP_SUMMARY`) with the suggested tests and their evidence, both stages' durations and the time to the first failure; elsewhere the same as text in the log."
  - "Paths are normalised for Windows runners."
- **Ingestion (§3.1):**
  - "Runs gain `scope` (`full` default, `impact-subset`) and `stages` (JSON: each stage's duration, test count and failures; `time_to_first_failure_s`; `stopped_after_stage`). New collector payload fields and a migration; older collectors send nothing, meaning `full`."
  - "`impact-subset` runs are excluded from the impact statistics (nightly rollup), the outcome evaluation and the accuracy figure; their suggestion is stored with state `not_evaluated`. They still count in pass-rate trends and flaky detection."
- **Dashboard (§3.2):**
  - "Run page: a "Suggested tests first" line with stage 1 and 2 durations and "first failure after N min (full suite M min)"; a subset run reads "Suggested tests only" (and "stopped after stage 1" for `--fail-fast`). The impact card of a subset run says "Suggested tests only, not evaluated"."
  - "Runs list: a "Suggested only" pill; a run filter hides subset runs."
- **Notifications (§3.3):** "Failed-run alerts and the weekly summary label a subset run "Suggested tests only" and a fail-fast stop "stopped after stage 1", so a partial run is never read as a full verdict."
- **Integrations (§4):** "GitHub Action: input `impact: first | only | off` (default `off`) and `test-command`; `first`/`only` wrap the command in `run-impact` (`only` = `--suggested-only`)." "Jenkins library: the same as a step option. GitLab and Azure templates: a commented example." "Run from QEOS (`qeos-run.mjs`) is unchanged: Play already selects the scenarios."
- **Testing (§5):**
  - "Collector: formats; exit codes; discovery honours tags; rerun files; outline rows; no scenario twice; one combined upload; `--fail-fast`; `--suggested-only` with fallback and `--no-fallback`; `--gate` on the combined run; step summary; Windows paths."
  - "Ingestion: `scope` and `stages` stored; subset runs excluded from statistics, outcomes and accuracy; migration."
  - "Dashboard: the run-page line, the pill, the filter, the card's "not evaluated" state."
  - "Smoke: a two-stage upload; a subset upload left out of the statistics."
- **Documentation (§6):** "Collector README (`impact`, `run-impact`, exit codes), docs/SETUP.md ("Suggested tests first in CI"), PRODUCT.md, README.md, TODO.md (release B done; JUnit/Maven/Gradle, pytest and Playwright/JS formats as follow-ups), ADR-029 (release B section), the ingestion README (`scope`, `stages`)."
- **Delivery (§7):** "Three phases, each ending in a gate (all suites, smoke) and a push" … "collector release `0.6.0` (the floating `collector-v0` tag follows the existing release flow)."
- **Out of scope (§8):** "other runner formats (follow-ups), skipping tests by default, executing tests on QEOS infrastructure (ADR-025), the team run queue and local runner (v2 roadmap). No TARGET technology is introduced."

**Project rules (every task):**
- **TDD.** Write the failing test, watch it fail, write the code, watch it pass, commit.
- **Docs in the same commit.** Every behaviour commit updates the `.md` files it affects. Edit them with the Edit tool, or with Python reading and writing UTF-8, with LF line endings; never with PowerShell `Set-Content`.
- **Dashboard UI tasks** (any `.tsx` or `.css` edit):
  - start by invoking the `ui-ux-pro-max` skill (Skill tool) and follow DESIGN.md;
  - take colours from `index.css` tokens only;
  - give lucide icons `aria-hidden="true"`;
  - never use `any`;
  - never show status by colour alone.
- **Reuse the shared helpers, never duplicate them:**
  - dashboard: `formatCount`, `formatDuration`, `plural`, `StatusPill`, `ErrorBanner`, `FilterSelect`, `FilterChips`;
  - ingestion: `impact_service.score_change`, `Deadline`, `ScoringTimeout`;
  - collector: `gitdiff.collect_changes`, `formats.parse_file`, `upload._send`, `make_context`, `endpoint_for`, and `cli._upload` / `_gate`.
- **Commands** (from the repository root, Git Bash):
  - Python suites run serially, one suite at a time, never two at once:
    - a service: `cd platforms/<svc> && SECRET_KEY=test .venv/Scripts/python -m pytest -q`;
    - the collector: `cd collector && .venv/Scripts/python -m pytest -q`;
    - one file: append its path.
  - Dashboard: `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build`; one file: `npx vitest run <path>`.
- **Git:**
  - Work on `master`, as GitHub account `carneiru`. Commit only your own paths: `git add <paths> && git commit -m "<msg>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- <paths>`. Never `git add -A`, and never commit anything under `.superpowers/`.
  - Shell scripts stay `100755`. On Windows, `git commit -- <path>` drops the executable bit, so a commit touching `scripts/smoke_gateway.sh` does this instead:
    1. stage the script;
    2. run `git update-index --chmod=+x scripts/smoke_gateway.sh`;
    3. check `git diff --cached --name-only`;
    4. commit the index without a pathspec.
  - Push to `master` only at a phase gate, after every gate step is green.
  - Never write the employer's name in code, tests, docs or commits; use `acme`, `example-org`.

## Rulings

Decisions the spec leaves open or gets wrong against the code. Each is repeated in its task.

1. **The collector scores through `POST /api/v1/collect/impact`, not `POST /projects/{id}/analytics/impact`.**
   - **Why not the analytics route:** it takes a user JWT and asks project-service for a role (`require_project_role`), while the collector holds only the project API key.
   - **The new route:**
     - authenticates with the API key (`get_api_key`), and the project comes from the key;
     - takes the same body (`ImpactIn`: 1–5,000 paths of 1–1,000 characters, no NUL, optional branch);
     - gives the same answer (`SuggestionOut`) and the same 503 `impact_timeout`;
     - runs one shared function, `analytics.score_or_503`.
   - **Routing:** the gateway already routes `/api/v1/collect` to ingestion, under its own rate limit.
   - **Security:** a project API key can now read its project's suggestions (test names, path units); SECURITY.md says so.
2. **Exit codes of `impact`, and of the scoring inside `run-impact`:**
   - **3:** the suggestion lists no tests, whatever its `state`. Also 3 when there is no change data.
   - **0:** "Not enough history" that still lists labelled tests (*failing on this branch*, *test file changed*, *no history yet*) prints them and exits 0. `impact_score.suggest` includes those labels below 20 runs, and they are worth running first.
   - **4:** unreachable, 429, 5xx, or 503 `impact_timeout`.
   - **2:** configuration problems, as everywhere in the collector: no URL or key, a TLS trust error, 401, 404 (a platform older than this release), or another 4xx.
3. **`not_evaluated` is derived, not stored.**
   - `run_impact` gets no new column, and a subset run's suggestion keeps `evaluated_at` null for good.
   - `GET /runs/{id}/impact` gains `evaluation`: `pending`, `evaluated` or `not_evaluated`, from `test_runs.scope`; `null` without a stored suggestion.
   - The background evaluation is not scheduled for subset runs. `impact_service.evaluate` returns early for them, and `evaluate_pending` selects only full runs, so subset rows never take the nightly pass's 500 places.
4. **What "excluded" means.**
   - Subset runs are left out of:
     - `change_runs` (so the rollup's statistics and replay's targets);
     - `history_runs` (the 20-run threshold);
     - the outcome evaluation;
     - `impact_read.accuracy`.
   - Their results stay everywhere else, because they are real results:
     - the newly-failed history of later full runs;
     - *failing on this branch*;
     - trends, flaky detection, the Report;
     - the weekly pass rate.
5. **The request hash leaves `scope` and `stages` out at their defaults (`full`, null).**
   - So an upload stored before migration 020 replays (200) instead of answering 409, for example a spooled part resent after the upgrade.
   - `trigger` stays as it is: its hash change shipped with migration 019.
6. **The shape of `stages`:**
   - `stages`: 1–2 items of `{name: "suggested"|"rest"|"all", duration_s: 0–604800, tests ≥ 0, failed ≥ 0}`;
   - `time_to_first_failure_s`: null, or 0–604800;
   - `stopped_after_stage`: only `1`, and only with `scope = impact-subset`;
   - no NaN or infinity; no other key (422 otherwise).
   - The time to the first failure is the earlier stages' wall time plus, in report order, the durations of the failing stage's scenarios up to the first failed or errored one. With parallel workers it is an upper bound.
   - A split upload sends `scope` and `stages` on every part, as it does `changes`.
7. **One Cucumber mechanism for all three flavours** (verified on cucumber-js 12.6.0 in this session; cucumber-jvm and Ruby from their documented options).
   - **Discovery** is a dry run with a JSON report.
   - **Rerun files** hold one `uri:line[:line…]` entry per feature file. Outline rows are their own lines: the JSON element's `line` is the example row's, and every runner filters on it.
   - **Arguments run-impact appends** to the user's command:

     | Flavour | Dry run | JSON report | Rerun file |
     |---|---|---|---|
     | `js` (cucumber-js) | `--dry-run` | `--format json:<abs>` | `<relative>/@stage-N.txt` |
     | `jvm` (Maven/Gradle) | `-Dcucumber.execution.dry-run=true` | `-Dcucumber.plugin=json:<abs>` | `-Dcucumber.features=@<abs>` |
     | `ruby` | `--dry-run` | `--format json --out <abs>` | `@<abs>` |

   - **cucumber-js 12** reads a positional argument as a rerun file only when its *file name* starts with `@`, and joins it to the working directory. So the path is relative and the file is named `@stage-N.txt`.
   - **Gradle** must forward `cucumber.*` system properties to the test JVM (SETUP says how).
   - **`--cucumber js|jvm|ruby`** sets the flavour. Without it, the flavour is detected:
     - `js`: a `cucumber-js` program anywhere in the command, or `@cucumber/cucumber` in an argument;
     - `jvm`: the first program is `mvn`, `mvnw`, `gradle` or `gradlew`;
     - `ruby`: the first program is `cucumber`, or `bundle … cucumber`.

     Otherwise (`npm test`, `python …`) run-impact asks for `--cucumber` (exit 2). For `js` through `npm`/`pnpm`, run-impact adds `--` when the command has none.
8. **Feature paths the command names.** cucumber-js 12 adds profile `paths` and positional paths to the rerun file's (verified: `ADDITIVE_ARRAYS` includes `paths`), and `--shard` drops scenarios. So:
   - run-impact leaves the paths it can see out of the stage commands:
     - `js`/`ruby`: positional arguments after the runner that end in `.feature[:N]`, contain a glob, name an `@` file or an existing directory;
     - `jvm`: `-Dcucumber.features=…`;
   - **before any test runs**, a dry run of stage 1's command must select exactly the planned scenarios. If it does not, run-impact runs nothing and exits 2, naming the likely causes.

   That one extra dry run is the price of "no scenario runs twice".
9. **No stage ever runs with an empty rerun file.** An empty file runs nothing in cucumber-js 12, but everything in some runners.
   - **The suggestion matches no discovered scenario,** or there is no suggestion in `first` mode: the user's command runs unchanged, plus the JSON report, as one stage `all` with `scope = full`.
   - **Every discovered scenario is suggested:** one stage `suggested`, with `scope = full`.
10. **`--no-fallback` only goes with `--suggested-only`** (exit 2 otherwise). With it, when nothing can run, run-impact runs and uploads nothing, and exits 3 or 4 as `impact` would (3 when no suggested scenario was discovered).
11. **`--fail-fast` stops when stage 1's report has a failed or errored scenario,** not on a nonzero exit code alone: undefined steps exit nonzero.
12. **run-impact's exit code:**
    - **Without `--gate`:** the test command's (the first nonzero stage exit code, else 0). A failed upload changes it only with `--fail-on-error` and passing tests.
    - **With `--gate`:** the gate on the uploaded run (`_gate`, quarantine aware; a discarded run is judged on its local results), and 1 when nothing was uploaded.
13. **Suggested tests that discovery did not find** are logged as "skipped by the filter: N suggested test(s) are not among this command's scenarios (left out by its filters, or not Cucumber)". run-impact cannot tell a tag filter from a JUnit test in the suggestion.
14. **`impact --format cucumber` reads the local `.feature` files:**
    - the file is `class_name`, the uri Cucumber reported; a `file:` prefix is dropped;
    - English keywords only;
    - an outline row's name is the outline's with the row's values in place of `<placeholders>`.
    A `classpath:` uri, a file in another language, or a file outside the working directory gives no line, and a name filter is printed instead: `--name "^…$"`. In it, each character special to a regular expression or a double-quoted shell word becomes `.`, so the line is safe to paste and still matches.
15. **`impact` output:**
    - The default `--format` is `cucumber` when the working directory holds a `.feature` file (a pruned walk), else `list`.
    - `--out` is written even on exit 3 or 4, empty, so a later step never reads a stale list.
    - Messages go to stderr; only the suggestion goes to stdout or the file.
16. **Working files** live in `.qeos-impact/<random>/` under the working directory: the rerun files must be relative for cucumber-js. They are removed at the end, and `.qeos-impact` too when empty.
17. **The weekly summary lists no runs,** so it labels subset runs with a count line: "Suggested tests only: 2 of 12 runs (1 stopped after stage 1)". The webhook carries `suggested_only_runs` and `stopped_after_stage_1_runs`. Failure alerts append " · Suggested tests only" or " · Suggested tests only, stopped after stage 1" to their headline (and so to the e-mail subject), and the webhook carries `run.scope` and `run.stopped_after_stage`.
18. **Dashboard words:**
    - **Durations:** the dashboard's `formatDuration` ("42.5 s", "14m 10s") rather than the spec's illustrative "N min".
    - **Stages:** "stage N (suggested | the rest | full suite) X tests in D".
    - **Runs list:**
      - `GET /runs` takes `scope=full|impact-subset`;
      - the quick chip "Full runs only" and the "Runs" filter set it;
      - the pill reads "Suggested only", with the note "stopped after stage 1" for a fail-fast stop.
    - **Impact card:** "Suggested tests only, not evaluated: …", with a "Not evaluated" pill, and it never polls.
19. **Migration `020`** (down-revision `019`):
    - `test_runs.scope` is `VARCHAR(20) NOT NULL DEFAULT 'full'` with the check `chk_test_runs_scope`. A constant default makes it a metadata-only change on PostgreSQL 11+, with no table rewrite.
    - `test_runs.stages` is `JSON NULL`.
    - Re-check `alembic/versions` before Task 1 and take the next free number if another branch landed first.
20. **Step summary:** written only when `GITHUB_ACTIONS=true` and `GITHUB_STEP_SUMMARY` is set; appended as Markdown, and the log says so in one line. When the file cannot be written, the same lines go to the log. Anywhere else, the lines go to the log.
21. **Windows runners:**
    - `run_command` resolves the program with `shutil.which` (PATHEXT: `npx.cmd`, `mvn.cmd`);
    - every path handed to Cucumber is written with `/` (`PurePath.as_posix()`);
    - discovered uris have `\` replaced by `/`;
    - rerun files and `--out` are written with LF.
22. **The GitHub Action:**
    - `patterns` becomes optional;
    - the new step reads `test-command` from an environment variable, and `eval "set -- $QEOS_TEST_COMMAND"` keeps the workflow author's quoting;
    - CI's `collector-action` job also runs the action with `impact: first` against `https://qeos.example.invalid` and `tests/fake_cucumber.py`: no suggestion (exit 4 of the scoring), so the full suite runs as one stage, the upload fails, and the job still exits 0.
23. **Release 0.6.0 follows the existing flow:**
    1. bump `__version__` and `test_package.py`;
    2. move every pinned `collector-v0.5.2` to `collector-v0.6.0`, except the troubleshooting row that names 0.5.2 as the fix;
    3. push and see CI green;
    4. `git tag collector-v0.6.0` and push the tag.

    `release-collector.yml` then builds, tests, publishes the GitHub release and the GHCR image, and its `float` job moves `collector-v0` to the same commit.

## Review Focus

The inputs and failure modes most likely to bite a user that the spec's own test list does not name, most likely first. Each is pinned by a test in the task that owns the code.

1. **A spooled upload, stored before migration 020, resent after the deploy**: it must replay (200, the same run), never 409. Pinned in Task 2 by `test_an_upload_from_before_migration_020_still_replays`, which asserts the pre-020 request hash as a literal.
2. **Old subset suggestions without an outcome**: they must never fill the nightly pass's 500 places and starve full runs of their outcome. Pinned in Task 3 by `test_subset_suggestions_never_take_the_nightly_passes_places`.
3. **A Cucumber profile, an npm script or `--shard` that names its own feature paths**: they would make stage 1 run unplanned scenarios, and so run scenarios twice. run-impact must refuse before any test runs, and upload nothing. Pinned in Task 16 by `test_a_command_that_adds_its_own_paths_is_refused_before_any_test_runs`.
4. **Every discovered scenario suggested, or none of them**: no stage may start with an empty rerun file, which some runners read as "everything". Pinned in Task 16 by `test_every_scenario_suggested_runs_one_stage_and_no_empty_rerun_file` and `test_no_suggested_scenario_runs_the_command_as_one_stage`.
5. **`impact --out FILE` when nothing is suggested (3) or QEOS is down (4)**: the file must be emptied, never left with an earlier step's list. Pinned in Task 13 by `test_out_is_emptied_when_nothing_is_suggested`.

## File map

**ingestion-service** (`platforms/ingestion-service/`)
- `alembic/versions/020_run_scope.py` (new): `test_runs.scope`, `test_runs.stages`.
- `src/ingestion/models/run.py`: `FULL_SCOPE`, `SUBSET_SCOPE`, `SCOPES`, the two columns and the check.
- `src/ingestion/schemas/collect.py`: `StageIn`, `StagesIn`, `RunIn.scope`, `RunIn.stages`.
- `src/ingestion/schemas/run.py`: `StageOut`, `StagesOut`, `RunOut.scope`, `RunOut.stages`.
- `src/ingestion/schemas/impact.py`: `RunImpactOut.evaluation`.
- `src/ingestion/service/ingest_service.py`: stores the fields, and the request hash leaves them out at their defaults.
- `src/ingestion/service/run_service.py`, `api/v1/endpoints/runs.py`: the runs list's `scope` filter.
- `src/ingestion/service/impact_history.py`, `impact_service.py`, `impact_read.py`: the exclusions and `evaluation`.
- `src/ingestion/api/v1/endpoints/analytics.py`: `score_or_503`, shared by both scoring routes.
- `src/ingestion/api/v1/endpoints/collect.py`: `POST /collect/impact`; no evaluation is scheduled for subset runs.
- `src/ingestion/service/notification_service.py`, `weekly_summary.py`: the labels.
- tests:
  - new: `tests/integration/test_collect_scope.py`, `test_impact_subset.py`, `test_collect_impact.py`;
  - changed: `tests/unit/test_migration.py`, `tests/conftest.py` (`seed_run` takes `scope` and `stages`), `test_notifications.py`, `test_weekly_summary.py`.

**dashboard** (`dashboard/src/`)
- `api/runs.ts`: `RunScope`, `RunStage`, `RunStages`, `Run.scope`, `Run.stages`, `RunFilters.scope`.
- `api/impact.ts`: `RunImpact.evaluation`.
- `lib/runScope.ts` (new) and its test: `isSubset`, `stoppedAfterStage1`, `stagesLine`.
- `pages/RunDetailPage.tsx` and its test: the line and the pill.
- `pages/RunsPage.tsx` and its test: the pill, the quick chip and the filter.
- `lib/impactQueries.ts`, `components/ImpactCard.tsx` and its test: not evaluated, and no polling.
- `index.css`: `.run-stages`.

**collector** (`collector/`)
- `src/qeos_collector/cucumber.py` (new):
  - P2: `scan_feature`, `locate`, `name_filter`, `has_feature_files`;
  - P3: `Scenario`, `FLAVOURS`, `WORKDIR`, `detect_flavour`, `with_separator`, `strip_paths`, `dry_run_arguments`, `report_arguments`, `rerun_argument`, `read_scenarios`, `rerun_text`, `write_rerun`, `split`.
- `src/qeos_collector/impact.py` (new): `Target`, `Suggestion`, `resolve`, `fetch`, `render`, `run`, `SUGGESTED`/`NOTHING`/`UNAVAILABLE`.
- `src/qeos_collector/run_impact.py` (new): `Stage`, `run_command`, `first_failure_after`, `stages_payload`, `run`.
- `src/qeos_collector/summary.py` (new): `STAGES`, `duration`, `cell`, `why`, `markdown`, `text`, `publish`.
- `src/qeos_collector/payload.py`: `SCOPES`, and `build_run(scope=, stages=)`.
- `src/qeos_collector/cli.py`:
  - the `impact` and `run-impact` subcommands;
  - `_run_options`, `_flags`, `_verdict`, `_usable_key`, `_upload_reports`;
  - `_upload(reports=, scope=, stages=)`.
- `src/qeos_collector/__init__.py`: `0.6.0`.
- tests:
  - new: `tests/test_cucumber_locate.py`, `test_impact_client.py`, `test_impact_command.py`, `test_cucumber_runner.py`, `test_run_impact.py`, `test_summary.py`, `tests/fake_cucumber.py`, `tests/fixtures/fake-cucumber-spec.json`;
  - changed: `tests/test_payload.py`, `test_package.py`.
- `README.md`: `impact`, `run-impact`, exit codes.

**Integrations and docs**
- `collector-action/action.yml`, `.github/workflows/ci.yml` (the action job), `collector-jenkins/vars/qeosCollectorUpload.groovy`, `collector-jenkins/README.md`, `templates/qeos-collector.gitlab-ci.yml`, `templates/qeos-collector.azure-pipelines.yml`.
- `scripts/smoke_gateway.sh` (stays `100755`).
- `docs/SETUP.md`, `PRODUCT.md`, `README.md`, `TODO.md`, `DESIGN.md`, `SECURITY.md`, `TECHNICAL_SPECIFICATION.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md` (banner line), `docs/architecture/adr/ADR-029-test-impact-analysis.md`, `platforms/ingestion-service/README.md`.
- Pinned refs moved in Task 21: `README.md`, `collector/README.md`, `collector-jenkins/vars/qeosCollectorUpload.groovy`, `dashboard/src/pages/ProjectSettingsPage.tsx` and its test, `dashboard/src/templates/qeos-run.yml.txt`, `docs/SETUP.md`, `templates/github/qeos-run.yml`, `templates/qeos-collector.azure-pipelines.yml`, `templates/qeos-collector.gitlab-ci.yml`.

The gateway, the compose files, the monitoring rules and `qeos-run.mjs` are not changed.

---

# Phase 1 — QEOS side (ingestion, dashboard, notifications, smoke)

At the end of this phase QEOS:
- stores and shows `scope` and `stages`;
- leaves subset runs out of the impact statistics, outcomes and accuracy;
- labels partial runs in its messages;
- answers the collector's scoring with an API key.

### Task 1: Migration 020 and the run's `scope` and `stages` columns

**Files:**
- Create: `platforms/ingestion-service/alembic/versions/020_run_scope.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/run.py`
- Test: `platforms/ingestion-service/tests/unit/test_migration.py`

**Interfaces:**
- Consumes: migration `019` (head today).
- Produces:
  - in `models/run.py`: `FULL_SCOPE = "full"`, `SUBSET_SCOPE = "impact-subset"`, `SCOPES = (FULL_SCOPE, SUBSET_SCOPE)`;
  - `Run.scope` (`String(20)`, not null, default and server default `'full'`);
  - `Run.stages` (`JSON`, nullable);
  - the check constraint `chk_test_runs_scope`.

Ruling 19 applies.

- [ ] **Step 1: Write the failing migration tests.** Append them to `tests/unit/test_migration.py`, where `migrated_engine`, `KEY`, `RUN`, `SERVICE_ROOT`, `Config`, `command`, `create_engine`, `inspect`, `text`, `IntegrityError` and `pytest` already exist. The existing `test_migration_columns_match_models` also fails until the model and the migration agree.

```python
def test_scope_defaults_to_full_and_is_checked(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "d" * 64})
        conn.execute(text(RUN), {"idem": "s1", "provider": "github_actions"})
        row = conn.execute(text("SELECT scope, stages FROM test_runs WHERE idempotency_key = 's1'")).one()
    assert (row[0], row[1]) == ("full", None)
    with migrated_engine.begin() as conn:
        conn.execute(text("UPDATE test_runs SET scope = 'impact-subset' WHERE idempotency_key = 's1'"))
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text("UPDATE test_runs SET scope = 'partial' WHERE idempotency_key = 's1'"))


def test_run_scope_downgrade_drops_the_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_020.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "019")
    engine = create_engine(url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("test_runs")}
        assert not {"scope", "stages"} & columns
        assert "trigger" in columns  # 019 is still there
    finally:
        engine.dispose()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py -q`
Expected: FAIL, with `no such column: scope` and a downgrade error naming `019`.

- [ ] **Step 3: The model.** In `src/ingestion/models/run.py`, replace the import block:

```python
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, text,
)
```

with:

```python
from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false,
    text,
)
```

After `TRIGGERS = ("manual", "automatic", "qeos")` add:

```python
# run-impact (spec 2026-10-13 §3.1): a full run, or one that ran only the suggested tests
FULL_SCOPE, SUBSET_SCOPE = "full", "impact-subset"
SCOPES = (FULL_SCOPE, SUBSET_SCOPE)
```

In `Run`, after the `trigger` column, add:

```python
    # Migration 020: "impact-subset" when only the suggested tests ran (run-impact --suggested-only or --fail-fast);
    # every older upload is a full run. stages: run-impact's stages, null for an ordinary upload
    scope = Column(String(20), nullable=False, default=FULL_SCOPE, server_default=FULL_SCOPE)
    stages = Column(JSON, nullable=True)
```

In `Run.__table_args__`, after the `chk_test_runs_trigger` line, add:

```python
        CheckConstraint("scope IN ('full','impact-subset')", name="chk_test_runs_scope"),
```

- [ ] **Step 4: The migration.** Create `alembic/versions/020_run_scope.py`:

```python
"""test_runs.scope and test_runs.stages: suggested tests first in CI (test impact release B)

run-impact uploads a run with its stages; a run of only the suggested tests is scope 'impact-subset' and stays out of
the impact statistics, the outcome evaluation and the accuracy figure (spec 2026-10-13 §3.1). Every existing run is a
full run: on PostgreSQL 11+ a constant default makes this a metadata-only change, with no table rewrite.

Revision ID: 020
Revises: 019
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("test_runs") as batch:
        batch.add_column(sa.Column("scope", sa.String(length=20), nullable=False, server_default="full"))
        batch.add_column(sa.Column("stages", sa.JSON(), nullable=True))
        batch.create_check_constraint("chk_test_runs_scope", "scope IN ('full','impact-subset')")


def downgrade() -> None:
    with op.batch_alter_table("test_runs") as batch:
        batch.drop_constraint("chk_test_runs_scope", type_="check")
        batch.drop_column("stages")
        batch.drop_column("scope")
```

- [ ] **Step 5: Run the migration tests and the whole suite**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py -q && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: PASS. The full suite stays green because the new column has a default.

- [ ] **Step 6: Commit**

```bash
git add platforms/ingestion-service/alembic/versions/020_run_scope.py platforms/ingestion-service/src/ingestion/models/run.py platforms/ingestion-service/tests/unit/test_migration.py
git commit -m "feat(ingestion): test_runs.scope and stages (migration 020)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/alembic/versions/020_run_scope.py platforms/ingestion-service/src/ingestion/models/run.py platforms/ingestion-service/tests/unit/test_migration.py
```

No `.md` changes in this commit: Task 2 documents the payload fields that use these columns.

### Task 2: The payload fields, stored and read back; the request hash; the runs list filter

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/schemas/collect.py`
- Modify: `platforms/ingestion-service/src/ingestion/service/ingest_service.py`
- Modify: `platforms/ingestion-service/src/ingestion/schemas/run.py`
- Modify: `platforms/ingestion-service/src/ingestion/service/run_service.py`
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py`
- Modify: `platforms/ingestion-service/README.md`, `TECHNICAL_SPECIFICATION.md`
- Test: `platforms/ingestion-service/tests/integration/test_collect_scope.py` (new)

**Interfaces:**
- Consumes: `Run.scope` and `Run.stages` (Task 1).
- Produces:
  - the upload fields `run.scope` (`"full"` | `"impact-subset"`, default `"full"`) and `run.stages` (`StagesIn`);
  - `RunOut.scope: str` and `RunOut.stages: Optional[StagesOut]`, so `GET /runs/{id}` and `GET /projects/{id}/runs` carry them;
  - `GET /projects/{id}/runs?scope=full|impact-subset`;
  - `run_service.RunFilters.scope`.

Rulings 5 and 6 apply.

- [ ] **Step 1: Write the failing tests.** Create `tests/integration/test_collect_scope.py`:

```python
"""run-impact's runs: scope and stages stored and read back, the request hash of older uploads unchanged, and the runs
list filter (spec 2026-10-13 §3.1, §3.2; plan Rulings 5, 6)."""
import json

import pytest

from src.ingestion.models import Run
from src.ingestion.schemas.collect import RunUpload
from src.ingestion.service import ingest_service
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

TWO_STAGES = {"stages": [{"name": "suggested", "duration_s": 65.0, "tests": 12, "failed": 1},
                         {"name": "rest", "duration_s": 850.0, "tests": 340, "failed": 0}],
              "time_to_first_failure_s": 42.5}
STOPPED = {"stages": [{"name": "suggested", "duration_s": 65.0, "tests": 12, "failed": 1}],
           "time_to_first_failure_s": 30.0, "stopped_after_stage": 1}
# An upload as collectors before 0.6.0 send it, and its request hash as ingestion computed it before migration 020
# (computed on 2026-10-13 with the code at b1e2cf2)
LEGACY_BODY = {"run": {"ci_provider": "local", "branch": "main", "started_at": "2026-10-01T10:00:00+00:00",
                       "finished_at": "2026-10-01T10:04:00+00:00"},
               "results": [{"suite": "s", "class_name": "C", "name": "pays", "status": "passed", "duration_ms": 5}]}
LEGACY_HASH = "39a4af616b1b54a1f4b5b77ec176ee5c0cff13a1e7841c782532210d4d4469e8"
STAGE = {"name": "rest", "duration_s": 1, "tests": 1, "failed": 0}


def test_a_two_stage_run_is_stored_with_its_scope_and_stages(client, make_key, db, auth, project_role):
    _, key = make_key(project_id=1)
    response = client.post(URL, json=upload_body(scope="full", stages=TWO_STAGES), headers=key_headers(key))
    assert response.status_code == 201
    run = db.get(Run, response.json()["id"])
    assert run.scope == "full"
    assert run.stages == {**TWO_STAGES, "stopped_after_stage": None}
    project_role("viewer")
    detail = client.get(f"/api/v1/runs/{run.id}", headers=auth()).json()
    assert detail["scope"] == "full"
    assert detail["stages"]["time_to_first_failure_s"] == 42.5
    assert [s["name"] for s in detail["stages"]["stages"]] == ["suggested", "rest"]


def test_an_upload_without_them_is_a_full_run_without_stages(client, make_key, db, auth, project_role):
    _, key = make_key(project_id=1)
    run_id = client.post(URL, json=upload_body(), headers=key_headers(key)).json()["id"]
    run = db.get(Run, run_id)
    assert (run.scope, run.stages) == ("full", None)
    project_role("viewer")
    detail = client.get(f"/api/v1/runs/{run_id}", headers=auth()).json()
    assert (detail["scope"], detail["stages"]) == ("full", None)


def test_a_fail_fast_stop_is_a_subset_run(client, make_key, db):
    _, key = make_key(project_id=1)
    response = client.post(URL, json=upload_body(scope="impact-subset", stages=STOPPED), headers=key_headers(key))
    assert response.status_code == 201
    run = db.get(Run, response.json()["id"])
    assert (run.scope, run.stages["stopped_after_stage"]) == ("impact-subset", 1)


@pytest.mark.parametrize("run_fields", [
    {"scope": "partial"},
    {"scope": "full", "stages": STOPPED},  # a run that stopped did not run in full
    {"stages": {"stages": []}},
    {"stages": {"stages": TWO_STAGES["stages"] * 2}},
    {"stages": {"stages": [{**STAGE, "name": "warmup"}]}},
    {"stages": {"stages": [{**STAGE, "duration_s": -1}]}},
    {"stages": {"stages": [{**STAGE, "duration_s": 604801}]}},
    {"stages": {"stages": [{**STAGE, "tests": -1}]}},
    {"stages": {"stages": [STAGE], "time_to_first_failure_s": -0.5}},
    {"scope": "impact-subset", "stages": {"stages": [STAGE], "stopped_after_stage": 2}},
    {"stages": {"stages": [{**STAGE, "extra": 1}]}},
    {"stages": {"stages": [STAGE], "extra": 1}},
])
def test_invalid_scope_or_stages_are_422(client, make_key, run_fields):
    _, key = make_key(project_id=1)
    assert client.post(URL, json=upload_body(**run_fields), headers=key_headers(key)).status_code == 422


def test_a_nan_duration_is_422(client, make_key):
    _, key = make_key(project_id=1)
    body = json.dumps(upload_body(scope="full", stages=TWO_STAGES)).replace("65.0", "NaN", 1)
    response = client.post(URL, content=body, headers={**key_headers(key), "Content-Type": "application/json"})
    assert response.status_code == 422


def test_an_upload_from_before_migration_020_still_replays(client, make_key):
    """Review Focus 1: a spooled part stored before the upgrade comes back with the same key and body."""
    assert ingest_service._request_hash(RunUpload.model_validate(LEGACY_BODY)) == LEGACY_HASH
    explicit = {**LEGACY_BODY, "run": {**LEGACY_BODY["run"], "scope": "full"}}
    assert ingest_service._request_hash(RunUpload.model_validate(explicit)) == LEGACY_HASH
    _, key = make_key(project_id=1)
    first = client.post(URL, json=LEGACY_BODY, headers=key_headers(key, idem="spooled-1"))
    again = client.post(URL, json=explicit, headers=key_headers(key, idem="spooled-1"))
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]


def test_the_scope_is_part_of_the_request_hash(client, make_key):
    _, key = make_key(project_id=1)
    body = upload_body()
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-scope")).status_code == 201
    subset = {**body, "run": {**body["run"], "scope": "impact-subset", "stages": STOPPED}}
    assert client.post(URL, json=subset, headers=key_headers(key, idem="k-scope")).status_code == 409


def test_the_runs_list_filters_on_scope(client, make_key, auth, project_role):
    _, key = make_key(project_id=1)
    full = client.post(URL, json=upload_body(), headers=key_headers(key)).json()["id"]
    subset = client.post(URL, json=upload_body(scope="impact-subset", stages=STOPPED),
                         headers=key_headers(key)).json()["id"]
    project_role("viewer")

    def ids(**params):
        return [r["id"] for r in client.get("/api/v1/projects/1/runs", params=params, headers=auth()).json()]

    assert ids() == [subset, full]
    assert ids(scope="full") == [full]
    assert ids(scope="impact-subset") == [subset]
    assert client.get("/api/v1/projects/1/runs", params={"scope": "partial"}, headers=auth()).status_code == 422
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_collect_scope.py -q`
Expected: FAIL, for these reasons:
- `RunIn` forbids extra fields, so `scope` and `stages` are 422;
- `detail["scope"]` raises `KeyError`;
- the `scope` query parameter is ignored.

- [ ] **Step 3: The upload schema.** In `src/ingestion/schemas/collect.py`, before `class RunIn`, add:

```python
MAX_STAGE_SECONDS = MAX_RUN_SPAN.total_seconds()


class StageIn(BaseModel):
    """One stage of a run-impact run (spec 2026-10-13 §3.1, plan Ruling 6)."""

    model_config = ConfigDict(extra="forbid")

    name: Literal["suggested", "rest", "all"]
    duration_s: float = Field(ge=0, le=MAX_STAGE_SECONDS, allow_inf_nan=False)
    tests: int = Field(ge=0, le=2_147_483_647)
    failed: int = Field(ge=0, le=2_147_483_647)


class StagesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[StageIn] = Field(min_length=1, max_length=2)
    # From the start of stage 1 to the end of the first failing scenario; None without a failure
    time_to_first_failure_s: Optional[float] = Field(None, ge=0, le=MAX_STAGE_SECONDS, allow_inf_nan=False)
    stopped_after_stage: Optional[Literal[1]] = None  # --fail-fast stopped after a failing stage 1
```

In `RunIn`, after the `trigger` field, add:

```python
    # run-impact (spec 2026-10-13 §3.1): "impact-subset" when only the suggested tests ran; absent: a full run
    scope: Literal["full", "impact-subset"] = "full"
    stages: Optional[StagesIn] = None
```

In `RunIn._times_make_sense`, before `return self`, add:

```python
        if self.stages is not None and self.stages.stopped_after_stage is not None and self.scope != "impact-subset":
            raise ValueError("stopped_after_stage needs scope impact-subset: a run that stopped did not run in full")
```

- [ ] **Step 4: Store them, and keep the request hash of older uploads.** In `src/ingestion/service/ingest_service.py`, replace:

```python
def _request_hash(upload: RunUpload) -> str:
    canonical = json.dumps(upload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

with:

```python
# Run fields added by migration 020, at their defaults: left out of the hash, so an upload stored before them (a spooled
# part resent after the upgrade) still replays instead of answering 409 (plan Ruling 5)
_LATER_RUN_FIELDS = {"scope": "full", "stages": None}


def _request_hash(upload: RunUpload) -> str:
    data = upload.model_dump(mode="json")
    for name, default in _LATER_RUN_FIELDS.items():
        if data["run"].get(name, default) == default:
            data["run"].pop(name, None)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

In `ingest()`, in the `Run(...)` constructor, after `trigger=meta.trigger,` add:

```python
        scope=meta.scope,
        stages=meta.stages.model_dump(mode="json") if meta.stages is not None else None,
```

- [ ] **Step 5: Read them back.** In `src/ingestion/schemas/run.py`, before `class RunOut`, add:

```python
class StageOut(BaseModel):
    name: str
    duration_s: float
    tests: int
    failed: int


class StagesOut(BaseModel):
    """run-impact's stages (spec 2026-10-13 §3.1)."""

    stages: list[StageOut]
    time_to_first_failure_s: Optional[float] = None
    stopped_after_stage: Optional[int] = None
```

In `RunOut`, after `trigger: Optional[str] = None`, add:

```python
    scope: str = "full"  # "impact-subset": only the suggested tests ran
    stages: Optional[StagesOut] = None
```

- [ ] **Step 6: The runs list filter.** In `src/ingestion/service/run_service.py`, add a field to `RunFilters`, after `until`:

```python
    scope: Optional[Literal["full", "impact-subset"]] = None  # "full" hides runs of only the suggested tests
```

In `list_runs`, before the `return`, add:

```python
    if f.scope is not None:
        query = query.filter(Run.scope == f.scope)
```

In `src/ingestion/api/v1/endpoints/runs.py`, in `list_runs`, add the parameter `scope: Optional[Literal["full", "impact-subset"]] = Query(None),` after `until`, and pass it on. The filters call becomes:

```python
    filters = run_service.RunFilters(
        branch=branch, branch_contains=branch_contains, status=status_filter, environment=environment, ci_provider=ci_provider,
        commit=commit, pr=pr, author=author, since=since, until=until, scope=scope,
    )
```

- [ ] **Step 7: Run the tests**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_collect_scope.py tests/integration/test_collect_endpoint.py tests/integration/test_collect_trigger.py tests/integration/test_runs_endpoints.py -q`
Expected: PASS.

- [ ] **Step 8: Docs.**

In `platforms/ingestion-service/README.md`, under "For a CI pipeline", after the paragraph ending "this is accepted (ADR-030).", add:

```markdown
   A run uploaded by `qeos-collector run-impact` (collector 0.6.0, migration 020) also carries:
   - `"scope": "full" | "impact-subset"`: default `full`; `impact-subset` when only the suggested tests ran;
   - `"stages"`:
     - `stages`: 1 or 2 items of `{"name": "suggested" | "rest" | "all", "duration_s", "tests", "failed"}`;
     - `time_to_first_failure_s`: null without a failure;
     - `stopped_after_stage`: `1`, only with `impact-subset`.

   Anything else is `422`. Unlike `trigger`, these two fields are left out of the request hash while they hold
   their defaults, so an upload stored before them still replays instead of answering `409`.
```

In "## Reading results", in the runs-list bullet, replace `` `since` (inclusive) and `until` `` with `` `scope` (`full` hides runs of only the suggested tests; `impact-subset` shows only them), `since` (inclusive) and `until` ``.

In `TECHNICAL_SPECIFICATION.md` §2.4:
- In the **Collect** bullet, after "nothing is stored (ADR-030).", add: "Optional `run.scope` (`full` default, `impact-subset`) and `run.stages` (run-impact's stages: duration, tests and failures per stage, `time_to_first_failure_s`, `stopped_after_stage`; migration 020), left out of the request hash at their defaults."
- In the **Read** bullet, replace "started-at range)" with "started-at range, scope)".

- [ ] **Step 9: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/schemas/collect.py platforms/ingestion-service/src/ingestion/service/ingest_service.py platforms/ingestion-service/src/ingestion/schemas/run.py platforms/ingestion-service/src/ingestion/service/run_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py platforms/ingestion-service/tests/integration/test_collect_scope.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md
git commit -m "feat(ingestion): run scope and stages in the upload, read back and filterable; older uploads keep their request hash" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/schemas/collect.py platforms/ingestion-service/src/ingestion/service/ingest_service.py platforms/ingestion-service/src/ingestion/schemas/run.py platforms/ingestion-service/src/ingestion/service/run_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py platforms/ingestion-service/tests/integration/test_collect_scope.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md
```

### Task 3: Subset runs left out of the statistics, the outcomes and the accuracy figure

**Files:**
- Modify: `platforms/ingestion-service/tests/conftest.py` (`seed_run` takes `scope` and `stages`)
- Modify: `platforms/ingestion-service/src/ingestion/service/impact_history.py` (`change_runs`)
- Modify: `platforms/ingestion-service/src/ingestion/service/impact_service.py` (`history_runs`, `evaluate`, `evaluate_pending`)
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py` (no evaluation scheduled for subset runs)
- Modify: `platforms/ingestion-service/src/ingestion/service/impact_read.py` (`run_impact`, `accuracy`)
- Modify: `platforms/ingestion-service/src/ingestion/schemas/impact.py` (`RunImpactOut.evaluation`)
- Modify: `platforms/ingestion-service/README.md`, `TECHNICAL_SPECIFICATION.md`, `PRODUCT.md`
- Test: `platforms/ingestion-service/tests/integration/test_impact_subset.py` (new)

**Interfaces:**
- Consumes: `FULL_SCOPE` and `SUBSET_SCOPE` (Task 1); the upload fields (Task 2).
- Produces:
  - `RunImpactOut.evaluation: Optional[Literal["pending", "evaluated", "not_evaluated"]]`, None without a stored suggestion;
  - `seed_run(..., scope="full", stages=None)`, which `seed_change_run(..., **fields)` passes through.

Rulings 3 and 4 apply.

- [ ] **Step 1: Let the fixtures seed subset runs.** In `tests/conftest.py`, change `seed_run`'s inner function signature from

```python
    def _seed(started_at, results=(("t1", "passed", 10),), project_id=1, branch="main", environment=None,
              ci_provider="local", ci_run_url=None, duration_ms=1000, commit_sha=None):
```

to

```python
    def _seed(started_at, results=(("t1", "passed", 10),), project_id=1, branch="main", environment=None,
              ci_provider="local", ci_run_url=None, duration_ms=1000, commit_sha=None, scope="full", stages=None):
```

and, in its `Run(...)` call, after `commit_sha=commit_sha,`, add `scope=scope, stages=stages,`.

- [ ] **Step 2: Write the failing tests.** Create `tests/integration/test_impact_subset.py`:

```python
"""Runs of only the suggested tests (scope impact-subset) stay out of the impact statistics, the outcome evaluation and
the accuracy figure; their suggestion is stored and answered as not evaluated (spec 2026-10-13 §3.1; plan Rulings 3,
4)."""
from datetime import datetime, timedelta, timezone

from src.ingestion.api.v1.endpoints import analytics
from src.ingestion.jobs import impact_rollup
from src.ingestion.models.impact import ImpactPair, ImpactTestBase, RunImpact
from src.ingestion.service import impact_replay, impact_service
from src.ingestion.service.impact_history import change_runs
from src.ingestion.service.ingest_service import test_key as key_of

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
SUBSET = "impact-subset"
STOPPED = {"stages": [{"name": "suggested", "duration_s": 60.0, "tests": 2, "failed": 1}],
           "time_to_first_failure_s": 20.0, "stopped_after_stage": 1}
TWO_STAGES = {"stages": [{"name": "suggested", "duration_s": 60.0, "tests": 1, "failed": 1},
                         {"name": "rest", "duration_s": 600.0, "tests": 3, "failed": 0}],
              "time_to_first_failure_s": 20.0}
SUGGESTED = {"state": "ok", "history_runs": 25, "needed_runs": 20, "statistical_total": 0, "tests": []}
UPLOAD = "/api/v1/collect/runs"


def statistics(db, project_id=1):
    db.expire_all()
    pairs = {(p.path_unit, p.test_key): (p.changed_runs, p.new_failures)
             for p in db.query(ImpactPair).filter_by(project_id=project_id)}
    bases = {b.test_key: (b.runs, b.new_failures) for b in db.query(ImpactTestBase).filter_by(project_id=project_id)}
    return pairs, bases


def ref(name):
    return {"test_key": key_of("s", "C", name), "suite": "s", "class_name": "C", "name": name}


def stored(db, run, *, evaluated, missed=()):
    db.add(RunImpact(run_id=run.id, suggested=SUGGESTED, model_version="stats-v1", replayed=False, scored_at=NOW,
                     caught=[] if evaluated else None, missed=[ref(n) for n in missed] if evaluated else None,
                     evaluated_at=NOW if evaluated else None))
    db.commit()


def upload(client, key, results, *, scope="full", stages=None):
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    run = {"ci_provider": "local", "branch": "main", "started_at": started.isoformat(),
           "finished_at": (started + timedelta(seconds=30)).isoformat(), "scope": scope}
    if stages is not None:
        run["stages"] = stages
    body = {"run": run,
            "results": [{"suite": "s", "class_name": "C", "name": name, "status": status, "duration_ms": 5}
                        for name, status in results],
            "changes": {"base_ref": "origin/main", "truncated": False,
                        "files": [{"path": "src/pay/api.py", "status": "M", "additions": 1, "deletions": 0}]}}
    response = client.post(UPLOAD, json=body, headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_subset_runs_add_nothing_to_the_statistics(db, seed_impact_history, seed_change_run):
    seed_impact_history(NOW - timedelta(days=20))
    impact_rollup.run_pass(db, now=lambda: NOW)
    before = statistics(db)
    assert before[0]  # the history gives `pays` its pairs
    for hours in (30, 20, 10):
        seed_change_run(NOW - timedelta(hours=hours), results=(("pays", "failed", 5), ("only-in-subsets", "failed", 5)),
                        paths=("src/pay/api.py",), scope=SUBSET, stages=STOPPED)
    impact_rollup.run_pass(db, now=lambda: NOW)
    assert statistics(db) == before
    assert key_of("s", "C", "only-in-subsets") not in statistics(db)[1]


def test_history_runs_count_only_full_runs(db, seed_change_run):
    for hours in (1, 2, 3):
        seed_change_run(NOW - timedelta(hours=hours))
    seed_change_run(NOW - timedelta(hours=5), scope=SUBSET, stages=STOPPED)
    assert impact_service.history_runs(db, 1, NOW) == 3


def test_replay_never_scores_a_subset_run(db, seed_change_run):
    full = seed_change_run(NOW - timedelta(days=2))
    subset = seed_change_run(NOW - timedelta(days=1), scope=SUBSET, stages=STOPPED)
    assert [r.id for r in change_runs(db, 1, NOW - timedelta(days=30), NOW, include_truncated=True)] == [full.id]
    assert impact_replay.replay_project(db, 1, NOW - timedelta(days=30), NOW) == 1
    db.expire_all()
    assert db.get(RunImpact, full.id) is not None
    assert db.get(RunImpact, subset.id) is None


def test_a_subset_upload_stores_its_suggestion_and_is_never_evaluated(client, db, make_key, monkeypatch):
    scheduled = []
    monkeypatch.setattr(impact_service, "evaluate_run", lambda factory, run_id: scheduled.append(run_id))
    _, key = make_key(project_id=1)
    run_id = upload(client, key, [("pays", "failed")], scope=SUBSET, stages=STOPPED)
    db.expire_all()
    row = db.get(RunImpact, run_id)
    assert row is not None and row.evaluated_at is None
    assert scheduled == []  # no outcome is written after the response
    assert impact_service.evaluate(db, run_id, datetime.now(timezone.utc)) is False
    db.expire_all()
    assert db.get(RunImpact, run_id).evaluated_at is None


def test_a_two_stage_upload_is_evaluated_as_before(client, db, make_key, monkeypatch):
    scheduled = []
    monkeypatch.setattr(impact_service, "evaluate_run", lambda factory, run_id: scheduled.append(run_id))
    _, key = make_key(project_id=1)
    run_id = upload(client, key, [("pays", "failed")], scope="full", stages=TWO_STAGES)
    assert scheduled == [run_id]


def test_subset_suggestions_never_take_the_nightly_passes_places(db, seed_change_run, monkeypatch):
    """Review Focus 2: three old subset suggestions and a full one; with room for two, the full one is evaluated."""
    monkeypatch.setattr(impact_service, "MAX_PENDING_PER_PASS", 2)
    subsets = [seed_change_run(NOW - timedelta(hours=10 - i), scope=SUBSET, stages=STOPPED) for i in range(3)]
    full = seed_change_run(NOW - timedelta(hours=2))
    for run, scored_at in [(run, NOW - timedelta(hours=9)) for run in subsets] + [(full, NOW - timedelta(hours=1))]:
        db.add(RunImpact(run_id=run.id, suggested=SUGGESTED, model_version="stats-v1", replayed=False,
                         scored_at=scored_at))
    db.commit()
    assert impact_service.evaluate_pending(db, NOW) == 1
    db.expire_all()
    assert db.get(RunImpact, full.id).evaluated_at is not None
    assert all(db.get(RunImpact, run.id).evaluated_at is None for run in subsets)


def test_the_accuracy_figure_leaves_subset_runs_out(client, auth, project_role, db, seed_change_run, monkeypatch):
    monkeypatch.setattr(analytics, "_now", lambda: NOW)
    project_role("viewer", project_id=1)
    stored(db, seed_change_run(NOW - timedelta(days=1)), evaluated=True, missed=("cart",))
    # An outcome on a subset run, as one written before this release would be: never counted
    stored(db, seed_change_run(NOW - timedelta(days=2), scope=SUBSET, stages=STOPPED), evaluated=True, missed=("ship",))
    body = client.get("/api/v1/projects/1/analytics/impact-accuracy", params={"days": 7}, headers=auth()).json()
    assert (body["missed"], body["live"]["runs"]) == (1, 1)
    assert [m["name"] for m in body["misses"]] == ["cart"]


def test_the_run_impact_answer_says_whether_it_was_evaluated(client, auth, project_role, db, seed_change_run):
    project_role("viewer", project_id=1)
    subset = seed_change_run(NOW - timedelta(days=1), scope=SUBSET, stages=STOPPED)
    pending = seed_change_run(NOW - timedelta(days=2))
    done = seed_change_run(NOW - timedelta(days=3))
    stored(db, subset, evaluated=False)
    stored(db, pending, evaluated=False)
    stored(db, done, evaluated=True)

    def answer(run):
        return client.get(f"/api/v1/projects/1/runs/{run.id}/impact", headers=auth()).json()

    assert (answer(subset)["evaluation"], answer(subset)["outcome"]) == ("not_evaluated", None)
    assert answer(pending)["evaluation"] == "pending"
    assert answer(done)["evaluation"] == "evaluated"


def test_a_run_without_change_data_has_no_evaluation(client, auth, project_role, seed_run):
    project_role("viewer", project_id=1)
    run = seed_run(NOW - timedelta(days=1))
    body = client.get(f"/api/v1/projects/1/runs/{run.id}/impact", headers=auth()).json()
    assert (body["state"], body.get("evaluation")) == ("no_change_data", None)
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_subset.py -q`
Expected: FAIL in every test except `test_a_two_stage_upload_is_evaluated_as_before` and `test_a_run_without_change_data_has_no_evaluation`:
- the statistics change;
- the counts include subset runs;
- `scheduled == [run_id]`;
- `KeyError: 'evaluation'`.

- [ ] **Step 4: Leave subset runs out of the statistics and replay.** In `src/ingestion/service/impact_history.py`:
- add `from src.ingestion.models.run import FULL_SCOPE`;
- in `change_runs`, replace the first `filters = [...]` line with:

```python
    # Runs of only the suggested tests are left out (spec 2026-10-13 §3.1); their results stay in every run's history
    filters = [Run.project_id == project_id, Run.started_at >= start, Run.started_at < end, Run.changed_files > 0,
               Run.scope == FULL_SCOPE]
```

- change the docstring's first sentence to: "Full runs started in [start, end) with at least one changed file, oldest first; runs of only the suggested tests are never in the statistics or replayed (spec 2026-10-13 §3.1)."

- [ ] **Step 5: The history count and the evaluation.** In `src/ingestion/service/impact_service.py`:
- add `from src.ingestion.models.run import FULL_SCOPE`;
- in `history_runs`, add `Run.scope == FULL_SCOPE,` to the `.where(...)` after `Run.changed_files > 0,`;
- in `evaluate`, replace the first two statements with:

```python
    row, run = db.get(RunImpact, run_id), db.get(Run, run_id)
    # A run of only the suggested tests cannot show what the suggestion missed: never evaluated (spec 2026-10-13 §3.1)
    if row is None or run is None or row.evaluated_at is not None or run.scope != FULL_SCOPE:
        return False
```

In `evaluate_pending`, replace the `run_ids = ...` statement with:

```python
    run_ids = [run_id for (run_id,) in db.execute(
        select(RunImpact.run_id).join(Run, Run.id == RunImpact.run_id)
        .where(RunImpact.evaluated_at.is_(None), RunImpact.scored_at < now - PENDING_AFTER, Run.scope == FULL_SCOPE)
        .order_by(RunImpact.scored_at, RunImpact.run_id).limit(MAX_PENDING_PER_PASS))]
```

In `src/ingestion/api/v1/endpoints/collect.py`:
- add `from src.ingestion.models.run import FULL_SCOPE`;
- replace `if run.changed_files:` with `if run.changed_files and run.scope == FULL_SCOPE:`;
- above it, add the comment `# A run of only the suggested tests is never evaluated (spec 2026-10-13 §3.1)`.

- [ ] **Step 6: The answers.** In `src/ingestion/schemas/impact.py`, in `RunImpactOut`, after `outcome`, add:

```python
    # not_evaluated: the run ran only the suggested tests (spec 2026-10-13 §3.1); None without a stored suggestion
    evaluation: Optional[Literal["pending", "evaluated", "not_evaluated"]] = None
```

In `src/ingestion/service/impact_read.py`:
- add `from src.ingestion.models.run import FULL_SCOPE`;
- in `run_impact`, replace the final `return` with:

```python
    evaluation = ("not_evaluated" if run.scope != FULL_SCOPE
                  else "evaluated" if row.evaluated_at is not None else "pending")
    return {"run_id": run.id, "state": row.suggested["state"], "changed_paths": paths, "replayed": row.replayed,
            "scored_at": as_utc(row.scored_at), "suggestion": {**row.suggested, "model_version": row.model_version},
            "outcome": outcome, "evaluation": evaluation}
```

- in `accuracy`, the `.where(...)` becomes:

```python
        .where(Run.project_id == project_id, Run.started_at >= since, RunImpact.evaluated_at.is_not(None),
               Run.scope == FULL_SCOPE)
```

- [ ] **Step 7: Run the tests, then the whole impact area**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_subset.py tests/integration/test_impact_upload.py tests/integration/test_impact_rollup.py tests/integration/test_impact_replay.py tests/integration/test_impact_endpoints.py tests/integration/test_impact_newly_failed.py -q`
Expected: PASS.

- [ ] **Step 8: Docs.**

In `platforms/ingestion-service/README.md`, "## Test impact":
- In "### Statistics", after the **Path units** bullet, add:

  ```markdown
  - **Runs of only the suggested tests** (`scope = impact-subset`: collector `run-impact --suggested-only`, or a
    `--fail-fast` stop) are left out of the statistics, the 20-run history count and replay. Their results still
    count everywhere else:
    - as earlier outcomes for later runs;
    - *failing on this branch*;
    - trends, flaky detection and the Report.
  ```

- In "### At upload", after "A replayed upload (same Idempotency-Key) is not scored again.", add:

  ```markdown
  A run of only the suggested tests has its suggestion stored, but it is never evaluated, neither after the
  response nor by the nightly pass, which selects full runs only. It could not show what the suggestion missed.
  ```

- In "### Endpoints", in the `GET …/runs/{run_id}/impact` row, append: "; `evaluation`: `pending`, `evaluated` or `not_evaluated` (the run ran only the suggested tests), null without a stored suggestion".
- In the `impact-accuracy` row, after "whose outcome is written", add "(full runs only)".

In `TECHNICAL_SPECIFICATION.md`, after "(`ok`, `not_enough_history`, `no_change_data` or `not_scored`).", add: "Its `evaluation` is `not_evaluated` for a run of only the suggested tests (`scope = impact-subset`), which the statistics, the outcome evaluation and the accuracy figure leave out."

In `PRODUCT.md`, "## Test Impact Rules", replace the bullet starting "- Suggestions decide what to run **first**" with:

```markdown
- Suggestions decide what to run **first**, never what to skip by default.
  - In CI, the collector's `run-impact` runs them first and then the rest of the suite, as one run.
  - A team may opt into running only them (`--suggested-only`, with the full suite as fallback when there is no
    suggestion).
  - Such runs are marked "Suggested tests only" wherever a run is shown or announced.
  - They never count in the impact statistics or the accuracy figure: a run of only the suggested tests cannot
    show what the suggestion missed.
```

- [ ] **Step 9: Commit**

```bash
git add platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_impact_subset.py platforms/ingestion-service/src/ingestion/service/impact_history.py platforms/ingestion-service/src/ingestion/service/impact_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py platforms/ingestion-service/src/ingestion/service/impact_read.py platforms/ingestion-service/src/ingestion/schemas/impact.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md PRODUCT.md
git commit -m "feat(ingestion): runs of only the suggested tests stay out of impact statistics, outcomes and accuracy (not_evaluated)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_impact_subset.py platforms/ingestion-service/src/ingestion/service/impact_history.py platforms/ingestion-service/src/ingestion/service/impact_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py platforms/ingestion-service/src/ingestion/service/impact_read.py platforms/ingestion-service/src/ingestion/schemas/impact.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md PRODUCT.md
```

### Task 4: `POST /api/v1/collect/impact`: the scoring with the project API key

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/analytics.py` (`score_or_503`)
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py` (the route)
- Modify: `platforms/ingestion-service/README.md`, `TECHNICAL_SPECIFICATION.md`, `SECURITY.md`
- Test: `platforms/ingestion-service/tests/integration/test_collect_impact.py` (new)

**Interfaces:**
- Consumes: `impact_service.score_change`, `Deadline` and `ScoringTimeout`; `ImpactIn`; `get_api_key`.
- Produces:
  - `analytics.score_or_503(db: Session, project_id: int, body: ImpactIn) -> dict`, in the `SuggestionOut` shape;
  - `POST /api/v1/collect/impact`:
    - body `{"changed_paths": [...], "branch": str | null}`;
    - answers 200 with `SuggestionOut`;
    - 401 for a bad key, 422 for bad input;
    - 503 `{"detail": {"code": "impact_timeout", "message": ...}}`.

  Phase 2's collector calls it.

Ruling 1 applies.

- [ ] **Step 1: Write the failing tests.** Create `tests/integration/test_collect_impact.py`:

```python
"""POST /api/v1/collect/impact: the collector's scoring with the project API key (spec 2026-10-13 §2.1; plan Ruling
1)."""
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import OperationalError

from src.ingestion.api.v1.endpoints import analytics
from src.ingestion.service import impact_service

URL = "/api/v1/collect/impact"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(analytics, "_now", lambda: NOW)


def headers(key):
    return {"Authorization": f"Bearer {key}"}


def test_the_key_scores_a_change_in_its_own_project(client, make_key, seed_run, http):
    seed_run(datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc), results=(("cart", "failed", 5),), branch="feature/x",
             project_id=7)
    seed_run(datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc), results=(("elsewhere", "failed", 5),),
             branch="feature/x", project_id=8)
    _, key = make_key(project_id=7)
    response = client.post(URL, json={"changed_paths": ["src/cart/x.py"], "branch": "feature/x"}, headers=headers(key))
    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "stats-v1"
    assert [(t["name"], t["kind"]) for t in body["tests"]] == [("cart", "failing_on_branch")]
    assert not http.calls  # the key names the project: project-service is never asked


@pytest.mark.parametrize("value", ["qeos_not_a_real_key", None])
def test_a_bad_or_revoked_key_is_401(client, make_key, value):
    _, revoked = make_key(project_id=7, revoked=True)
    response = client.post(URL, json={"changed_paths": ["a.py"]}, headers=headers(value or revoked))
    assert response.status_code == 401


def test_a_user_token_is_not_a_key(client, auth):
    assert client.post(URL, json={"changed_paths": ["a.py"]}, headers=auth()).status_code == 401


@pytest.mark.parametrize("body", [
    {"changed_paths": []},
    {"changed_paths": ["a\x00b"]},
    {"changed_paths": ["x" * 1001]},
    {"changed_paths": ["a.py"] * 5001},
    {"changed_paths": ["a.py"], "branch": "b" * 256},
    {"changed_paths": ["a.py"], "extra": 1},
])
def test_input_limits(client, make_key, body):
    _, key = make_key(project_id=7)
    assert client.post(URL, json=body, headers=headers(key)).status_code == 422


def test_a_scoring_timeout_answers_503_with_its_code(client, make_key, monkeypatch):
    def out_of_time(*args, **kwargs):
        raise impact_service.ScoringTimeout()

    monkeypatch.setattr(impact_service, "score_change", out_of_time)
    _, key = make_key(project_id=7)
    response = client.post(URL, json={"changed_paths": ["a.py"]}, headers=headers(key))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "impact_timeout"


def test_another_database_error_is_not_a_timeout(client, make_key, monkeypatch):
    def broken(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("disk full"))

    monkeypatch.setattr(impact_service, "score_change", broken)
    _, key = make_key(project_id=7)
    with pytest.raises(OperationalError):
        client.post(URL, json={"changed_paths": ["a.py"]}, headers=headers(key))
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_collect_impact.py -q`
Expected: FAIL, with 404 or 405 on `/api/v1/collect/impact`.

- [ ] **Step 3: One shared scoring.** In `src/ingestion/api/v1/endpoints/analytics.py`, above `@router.post("/impact", response_model=SuggestionOut)`, add:

```python
def _impact_timeout() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail={"code": "impact_timeout", "message": impact_service.SCORING_TIMEOUT_MESSAGE})


def score_or_503(db: Session, project_id: int, body: ImpactIn) -> dict:
    """The scoring POST /analytics/impact and POST /collect/impact both answer with (spec 2026-10-13 §2.1): one total
    2 s budget, a timeout a 503 `impact_timeout`, the read-only transaction ended before the response."""
    try:
        deadline = impact_service.Deadline()
        deadline.step(db)
        suggestion = impact_service.score_change(db, project_id, body.changed_paths, body.branch, now=_now(),
                                                 deadline=deadline)
    except impact_service.ScoringTimeout:
        raise _impact_timeout()
    except OperationalError as exc:
        if report_service.is_timeout(exc):
            raise _impact_timeout()
        raise
    finally:
        db.rollback()  # read-only: end the transaction (and its SET LOCAL) before the response
    return {**suggestion, "model_version": MODEL_VERSION}
```

Then replace everything in `impact(...)` after its docstring (the `try:` … `return {**suggestion, ...}` block) with:

```python
    return score_or_503(db, access.project_id, body)
```

- [ ] **Step 4: The route.** In `src/ingestion/api/v1/endpoints/collect.py`:
- add `from src.ingestion.api.v1.endpoints.analytics import ImpactIn, score_or_503` and `from src.ingestion.schemas.impact import SuggestionOut`;
- after `import_token`, add:

```python
@router.post("/impact", response_model=SuggestionOut)
def collect_impact(body: ImpactIn, db: Session = Depends(get_db), key: ApiKey = Depends(get_api_key)):
    """Likely affected tests for a change, for `qeos-collector impact` and `run-impact` (spec 2026-10-13 §2): the
    scoring of POST /projects/{id}/analytics/impact for the key's own project, with the key instead of a user's token.
    Reads only; stores nothing."""
    return score_or_503(db, key.project_id, body)
```

- [ ] **Step 5: Run the tests, and the existing endpoint tests (the refactor)**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_collect_impact.py tests/integration/test_impact_endpoints.py tests/integration/test_collect_endpoint.py -q`
Expected: PASS.

- [ ] **Step 6: Docs.**

In `platforms/ingestion-service/README.md`, "### Endpoints (every role that can read runs)", add a row under the `POST …/analytics/impact` row:

```markdown
| `POST /api/v1/collect/impact` (project API key, not a user token) | The same scoring, body, limits and 503 for the key's own project, for `qeos-collector impact` and `run-impact` (spec 2026-10-13). It reads only; the gateway's `/api/v1/collect` rate limit applies |
```

In `TECHNICAL_SPECIFICATION.md`, in the **Collect** bullet, after "that only test-management's import accepts (ADR-024).", add: "`POST /collect/impact` scores a change for the key's project with the analytics route's scoring, limits and 503 `impact_timeout`, for the collector's `impact` and `run-impact`."

In `SECURITY.md`, replace the **CI uploads** bullet with:

```markdown
- **CI uploads.** Per-project API keys, stored as SHA-256 hashes and shown once. A key can also:
  - be traded for a 5-minute service token that only the Gherkin import accepts;
  - read its own project's test impact suggestions (`POST /api/v1/collect/impact`: test names and changed-path
    units, never results or messages), which the collector needs to run the likely affected tests first.
```

- [ ] **Step 7: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/api/v1/endpoints/analytics.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py platforms/ingestion-service/tests/integration/test_collect_impact.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md SECURITY.md
git commit -m "feat(ingestion): POST /collect/impact scores a change with the project API key, for the collector" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/api/v1/endpoints/analytics.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py platforms/ingestion-service/tests/integration/test_collect_impact.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md SECURITY.md
```

### Task 5: Notifications label partial runs

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/service/notification_service.py`
- Modify: `platforms/ingestion-service/src/ingestion/service/weekly_summary.py`
- Modify: `platforms/ingestion-service/README.md` ("## Failure notifications")
- Test: `platforms/ingestion-service/tests/integration/test_notifications.py`, `tests/integration/test_weekly_summary.py`

**Interfaces:**
- Consumes: `SUBSET_SCOPE` (Task 1); `Run.scope` and `Run.stages`.
- Produces:
  - `notification_service.scope_label(scope: Optional[str], stages: Optional[dict]) -> Optional[str]`;
  - `RunSummary.scope: str = "full"`, `RunSummary.stages: Optional[dict] = None`, and the `RunSummary.partial` property;
  - `WeeklySummary.subset_runs: int` and `WeeklySummary.stopped_runs: int`;
  - the webhook keys `run.scope`, `run.stopped_after_stage`, `suggested_only_runs` and `stopped_after_stage_1_runs`.

Ruling 17 applies.

- [ ] **Step 1: Write the failing tests.** Append to `tests/integration/test_notifications.py` (`upload`, `send`, `channel`, `SLACK` and `HOOK` already exist there), and add `from src.ingestion.service import notification_service` to its imports:

```python
SUBSET_STAGES = {"stages": [{"name": "suggested", "duration_s": 60.0, "tests": 3, "failed": 2}],
                 "time_to_first_failure_s": 12.0}


def test_a_subset_run_is_announced_as_suggested_tests_only(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db)
    route = http.post(SLACK).mock(return_value=httpx.Response(200, text="ok"))
    assert send(client, key, upload(failed=2, scope="impact-subset", stages=SUBSET_STAGES)).status_code == 201
    payload = json.loads(route.calls.last.request.content)
    assert payload["text"] == "QA: 2 of 3 tests failed · Suggested tests only"


def test_a_fail_fast_stop_says_it_stopped_after_stage_1(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db, kind="webhook", url=HOOK)
    route = http.post(HOOK).mock(return_value=httpx.Response(204))
    stopped = {**SUBSET_STAGES, "stopped_after_stage": 1}
    assert send(client, key, upload(failed=2, scope="impact-subset", stages=stopped)).status_code == 201
    body = json.loads(route.calls.last.request.content)
    assert (body["run"]["scope"], body["run"]["stopped_after_stage"]) == ("impact-subset", 1)


def test_a_full_run_keeps_its_headline(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db)
    route = http.post(SLACK).mock(return_value=httpx.Response(200, text="ok"))
    send(client, key, upload(failed=2))
    assert json.loads(route.calls.last.request.content)["text"] == "QA: 2 of 3 tests failed"


def test_the_email_subject_carries_the_label():
    summary = notification_service.RunSummary(
        project_id=1, run_id=5, total=3, failed=2, errored=0, branch="main", commit_sha=None, commit_message=None,
        ci_run_url=None, scope="impact-subset", stages={**SUBSET_STAGES, "stopped_after_stage": 1})
    assert notification_service.email_payload("QA", summary)["subject"] == (
        "QA: 2 of 3 tests failed · Suggested tests only, stopped after stage 1")
```

In `tests/integration/test_weekly_summary.py`:
- change the `add_run` fixture's inner signature to `def _add(when, results, project_id=1, branch="main", scope="full", stages=None):`;
- in its `Run(...)` call, add `scope=scope, stages=stages,`;
- append:

```python
def test_runs_that_ran_only_suggested_tests_are_labelled(db, add_run):
    one_stage = {"stages": [{"name": "suggested", "duration_s": 60.0, "tests": 1, "failed": 1}],
                 "time_to_first_failure_s": 5.0}
    add_run(LAST_WEEK, [("a", "passed")])
    add_run(LAST_WEEK, [("b", "failed")], scope="impact-subset", stages={**one_stage, "stopped_after_stage": 1})
    add_run(LAST_WEEK, [("c", "passed")], scope="impact-subset", stages={**one_stage, "time_to_first_failure_s": None})
    s = weekly_summary.build(db, 1, MONDAY, branch=None)
    assert (s.runs, s.subset_runs, s.stopped_runs) == (3, 2, 1)
    assert s.pass_rate == pytest.approx(2 / 3)  # subset runs still count in the pass rate (spec §3.1)
    slack = json.dumps(weekly_summary.PAYLOADS["slack"]("QA", s), ensure_ascii=False)
    assert "Suggested tests only: 2 of 3 runs (1 stopped after stage 1)" in slack
    hook = weekly_summary.PAYLOADS["webhook"]("QA", s)
    assert (hook["suggested_only_runs"], hook["stopped_after_stage_1_runs"]) == (2, 1)


def test_a_week_of_full_runs_has_no_label(db, add_run):
    add_run(LAST_WEEK, [("a", "passed")])
    s = weekly_summary.build(db, 1, MONDAY, branch=None)
    assert s.subset_runs == 0
    assert "Suggested tests only" not in "\n".join(weekly_summary._lines(s))
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_notifications.py tests/integration/test_weekly_summary.py -q`
Expected: FAIL:
- the headline has no label;
- `RunSummary` has no `scope`;
- `WeeklySummary` has no `subset_runs`.

- [ ] **Step 3: Failure alerts.** In `src/ingestion/service/notification_service.py`:
- add `from src.ingestion.models.run import SUBSET_SCOPE`;
- before `@dataclass class RunSummary`, add:

```python
def scope_label(scope: Optional[str], stages: Optional[dict]) -> Optional[str]:
    """How a run that ran only part of its suite is named in messages (spec 2026-10-13 §3.3), so it is never read as a
    full verdict; None for a full run."""
    if scope != SUBSET_SCOPE:
        return None
    if isinstance(stages, dict) and stages.get("stopped_after_stage") == 1:
        return "Suggested tests only, stopped after stage 1"
    return "Suggested tests only"
```

In `RunSummary`, after `quarantined: int = 0  # failures of quarantined tests: mentioned, not counted`, add:

```python
    scope: str = "full"
    stages: Optional[dict] = None

    @property
    def partial(self) -> Optional[str]:
        return scope_label(self.scope, self.stages)
```

Replace `_headline` with:

```python
def _headline(channel_name: str, s: RunSummary) -> str:
    if s.test:
        return f"{channel_name}: QEOS test message. This channel is set up correctly."
    headline = f"{channel_name}: {s.broken} of {s.total} tests failed"
    return f"{headline} · {s.partial}" if s.partial else headline
```

In `webhook_payload`, in the `"run": {...}` dict, after `"url": s.link`, add:

```python
                "scope": s.scope, "stopped_after_stage": (s.stages or {}).get("stopped_after_stage"),
```

In `_summary`, in the `RunSummary(...)` call, after `quarantined=quarantined,`, add `scope=run.scope, stages=run.stages,`.

- [ ] **Step 4: The weekly summary.** In `src/ingestion/service/weekly_summary.py`:
- add `from src.ingestion.models.run import SUBSET_SCOPE`;
- in `WeeklySummary`, after `top_failing`, add:

```python
    subset_runs: int = 0   # runs of only the suggested tests (spec 2026-10-13 §3.3)
    stopped_runs: int = 0  # of those, the ones a failing stage 1 stopped
```

After `_totals`, add:

```python
def _subset_runs(db: Session, project_id: int, start: datetime, end: datetime,
                 branch: Optional[str]) -> Tuple[int, int]:
    """The week's runs of only the suggested tests, and how many of them a failing stage 1 stopped."""
    query = db.query(Run.stages).filter(Run.project_id == project_id, Run.started_at >= start, Run.started_at < end,
                                        Run.scope == SUBSET_SCOPE)
    if branch is not None:
        query = query.filter(Run.branch == branch)
    stages = [row[0] for row in query.all()]
    return len(stages), sum(1 for s in stages if isinstance(s, dict) and s.get("stopped_after_stage") == 1)
```

In `build`, before `failures = func.count(...)`, add:

```python
    s.subset_runs, s.stopped_runs = _subset_runs(db, project_id, start, end, branch)
```

In `_lines`, replace the `lines = [...]` list with:

```python
    lines = [
        f"{days}{scope}",
        f"Runs: {s.runs} · Test executions: {s.executions}",
    ]
    if s.subset_runs:
        stopped = f" ({s.stopped_runs} stopped after stage 1)" if s.stopped_runs else ""
        lines.append(f"Suggested tests only: {s.subset_runs} of {s.runs} runs{stopped}")
    lines += [
        f"Pass rate: {_pct(s.pass_rate)} (week before: {_pct(s.previous_pass_rate)})",
        f"Failed: {s.failed} · Errored: {s.errored} · Skipped: {s.skipped}",
    ]
```

In `webhook_payload`, after `"top_failing": s.top_failing,`, add `"suggested_only_runs": s.subset_runs, "stopped_after_stage_1_runs": s.stopped_runs,`.

- [ ] **Step 5: Run the tests**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_notifications.py tests/integration/test_weekly_summary.py -q`
Expected: PASS.

- [ ] **Step 6: Docs.** In `platforms/ingestion-service/README.md`, "## Failure notifications", after the first paragraph (it ends with the design spec path), add:

```markdown
A run of only the suggested tests (`scope = impact-subset`, collector `run-impact`) is labelled so it is never read as
a full verdict:
- **Failure alerts:**
  - the headline (and so the e-mail subject) ends " · Suggested tests only", or " · Suggested tests only, stopped
    after stage 1" for a `--fail-fast` stop;
  - the webhook carries `run.scope` and `run.stopped_after_stage`.
- **Weekly summary:**
  - a line says "Suggested tests only: N of M runs (K stopped after stage 1)";
  - its webhook carries `suggested_only_runs` and `stopped_after_stage_1_runs`.
```

- [ ] **Step 7: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/service/notification_service.py platforms/ingestion-service/src/ingestion/service/weekly_summary.py platforms/ingestion-service/tests/integration/test_notifications.py platforms/ingestion-service/tests/integration/test_weekly_summary.py platforms/ingestion-service/README.md
git commit -m "feat(ingestion): failure alerts and the weekly summary label runs of only the suggested tests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/service/notification_service.py platforms/ingestion-service/src/ingestion/service/weekly_summary.py platforms/ingestion-service/tests/integration/test_notifications.py platforms/ingestion-service/tests/integration/test_weekly_summary.py platforms/ingestion-service/README.md
```

### Task 6: Dashboard: run types and the run page's "Suggested tests first" line

**Files:**
- Modify: `dashboard/src/api/runs.ts`
- Create: `dashboard/src/lib/runScope.ts`, `dashboard/src/lib/runScope.test.ts`
- Modify: `dashboard/src/pages/RunDetailPage.tsx`, `dashboard/src/pages/RunDetailPage.test.tsx`
- Modify: `dashboard/src/index.css`, `DESIGN.md`

**Interfaces:**
- Consumes: `RunOut.scope` and `RunOut.stages` (Task 2).
- Produces:
  - in `api/runs.ts`: `RunScope = "full" | "impact-subset"`; `RunStage { name: "suggested" | "rest" | "all"; duration_s: number; tests: number; failed: number }`; `RunStages { stages: RunStage[]; time_to_first_failure_s: number | null; stopped_after_stage: 1 | null }`;
  - `Run.scope?: RunScope` and `Run.stages?: RunStages | null` (optional: older servers omit them); `RunFilters.scope?: RunScope`;
  - in `lib/runScope.ts`: `isSubset(run: Pick<Run, "scope">): boolean`, `stoppedAfterStage1(run: Pick<Run, "stages">): boolean`, `stagesLine(run: Pick<Run, "scope" | "stages">): string | null`.

Ruling 18 applies.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill** (Skill tool), and read DESIGN.md's "Likely affected tests" section before touching `.tsx` or `.css`.

- [ ] **Step 1: The types.** In `dashboard/src/api/runs.ts`, before `export interface Run`, add:

```ts
/** "impact-subset": only the suggested tests ran (`run-impact --suggested-only`, or a `--fail-fast` stop). */
export type RunScope = "full" | "impact-subset";

/** One stage of a `run-impact` run (spec 2026-10-13 §3.1). */
export interface RunStage {
  name: "suggested" | "rest" | "all";
  duration_s: number;
  tests: number;
  failed: number;
}

export interface RunStages {
  stages: RunStage[];
  /** From the start of stage 1 to the end of the first failing scenario; null without a failure. */
  time_to_first_failure_s: number | null;
  stopped_after_stage: 1 | null;
}
```

In `Run`, after `base_branch: string | null;`, add:

```ts
  /** Older servers omit it: a full run. */
  scope?: RunScope;
  /** run-impact's stages; null (or absent) for an ordinary upload. */
  stages?: RunStages | null;
```

In `RunFilters`, after `until?: string; // ISO instant, exclusive`, add:

```ts
  /** "full" hides runs of only the suggested tests. */
  scope?: RunScope;
```

- [ ] **Step 2: Write the failing tests.** Create `dashboard/src/lib/runScope.test.ts`:

```ts
import type { RunStages } from "../api/runs";
import { isSubset, stagesLine, stoppedAfterStage1 } from "./runScope";

const two: RunStages = {
  stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }, { name: "rest", duration_s: 850, tests: 340, failed: 0 }],
  time_to_first_failure_s: 42.5,
  stopped_after_stage: null,
};
const stopped: RunStages = {
  stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }],
  time_to_first_failure_s: 30,
  stopped_after_stage: 1,
};

test("a two-stage run names both stages and when the first failure came", () => {
  expect(stagesLine({ scope: "full", stages: two })).toBe(
    "Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2 (the rest) 340 tests in 14m 10s"
    + " · first failure after 42.5 s (full suite 15m 15s)");
});

test("a run without failures says so", () => {
  expect(stagesLine({ scope: "full", stages: { ...two, time_to_first_failure_s: null } })).toBe(
    "Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2 (the rest) 340 tests in 14m 10s · no failures");
});

test("a run with nothing to suggest ran the full suite as one stage", () => {
  const all: RunStages = { stages: [{ name: "all", duration_s: 900, tests: 352, failed: 0 }], time_to_first_failure_s: null,
    stopped_after_stage: null };
  expect(stagesLine({ scope: "full", stages: all })).toBe("Suggested tests first: stage 1 (full suite) 352 tests in 15m 00s · no failures");
});

test("a fail-fast stop is suggested tests only, stopped after stage 1", () => {
  expect(stagesLine({ scope: "impact-subset", stages: stopped })).toBe(
    "Suggested tests only, stopped after stage 1: stage 1 (suggested) 12 tests in 1m 05s · first failure after 30.0 s");
});

test("a suggested-only run without stages still says what it was", () => {
  expect(stagesLine({ scope: "impact-subset", stages: null })).toBe("Suggested tests only");
});

test("an ordinary upload, or an older server, has no line", () => {
  expect(stagesLine({ scope: "full", stages: null })).toBeNull();
  expect(stagesLine({})).toBeNull();
});

test("one test is singular", () => {
  const one: RunStages = { stages: [{ name: "suggested", duration_s: 2, tests: 1, failed: 0 }], time_to_first_failure_s: null,
    stopped_after_stage: null };
  expect(stagesLine({ scope: "impact-subset", stages: one })).toBe("Suggested tests only: stage 1 (suggested) 1 test in 2.0 s · no failures");
});

test("isSubset and stoppedAfterStage1", () => {
  expect(isSubset({ scope: "impact-subset" })).toBe(true);
  expect(isSubset({ scope: "full" })).toBe(false);
  expect(isSubset({})).toBe(false);
  expect(stoppedAfterStage1({ stages: stopped })).toBe(true);
  expect(stoppedAfterStage1({ stages: two })).toBe(false);
  expect(stoppedAfterStage1({ stages: null })).toBe(false);
});
```

Append to `dashboard/src/pages/RunDetailPage.test.tsx`:

```tsx
test("a run-impact run says how its stages went", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json({
    ...detail([]), scope: "full",
    stages: { stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }, { name: "rest", duration_s: 850, tests: 340, failed: 0 }],
      time_to_first_failure_s: 42.5, stopped_after_stage: null },
  })));
  renderDetail();
  expect(await screen.findByText("Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2 (the rest) 340 tests"
    + " in 14m 10s · first failure after 42.5 s (full suite 15m 15s)")).toBeInTheDocument();
  expect(screen.queryByText("Suggested only", { selector: ".pill" })).not.toBeInTheDocument();
});

test("a suggested-only run says so, with a word as well as the line", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json({
    ...detail([]), scope: "impact-subset",
    stages: { stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }], time_to_first_failure_s: 30, stopped_after_stage: 1 },
  })));
  renderDetail();
  expect(await screen.findByText(
    "Suggested tests only, stopped after stage 1: stage 1 (suggested) 12 tests in 1m 05s · first failure after 30.0 s")).toBeInTheDocument();
  expect(screen.getByText("Suggested only", { selector: ".pill" })).toBeInTheDocument();
});

test("an ordinary upload has no stages line", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([]))));
  renderDetail();
  await screen.findByText("abcdef1");
  expect(screen.queryByText(/^Suggested tests/)).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd dashboard && npx vitest run src/lib/runScope.test.ts src/pages/RunDetailPage.test.tsx`
Expected: FAIL: `./runScope` cannot be resolved, and the line is not on the page.

- [ ] **Step 4: The words.** Create `dashboard/src/lib/runScope.ts`:

```ts
import { formatDuration } from "../api/analytics";
import type { Run, RunStage } from "../api/runs";
import { plural } from "./words";

const STAGE: Record<RunStage["name"], string> = { suggested: "suggested", rest: "the rest", all: "full suite" };

const seconds = (s: number): string => formatDuration(Math.round(s * 1000));

/** Only the suggested tests ran: `run-impact --suggested-only`, or a `--fail-fast` stop. */
export function isSubset(run: Pick<Run, "scope">): boolean {
  return run.scope === "impact-subset";
}

export function stoppedAfterStage1(run: Pick<Run, "stages">): boolean {
  return run.stages?.stopped_after_stage === 1;
}

/** The run page's line for a run uploaded by `run-impact` (spec 2026-10-13 §3.2); null for an ordinary upload. */
export function stagesLine(run: Pick<Run, "scope" | "stages">): string | null {
  const subset = isSubset(run);
  const s = run.stages ?? null;
  if (s === null) return subset ? "Suggested tests only" : null;
  const head = !subset ? "Suggested tests first"
    : stoppedAfterStage1(run) ? "Suggested tests only, stopped after stage 1" : "Suggested tests only";
  const stages = s.stages.map((stage, i) =>
    `stage ${i + 1} (${STAGE[stage.name]}) ${plural(stage.tests, "test", "tests")} in ${seconds(stage.duration_s)}`);
  const total = s.stages.reduce((sum, stage) => sum + stage.duration_s, 0);
  const failure = s.time_to_first_failure_s === null ? "no failures"
    : subset ? `first failure after ${seconds(s.time_to_first_failure_s)}`
    : `first failure after ${seconds(s.time_to_first_failure_s)} (full suite ${seconds(total)})`;
  return `${head}: ${[...stages, failure].join(" · ")}`;
}
```

- [ ] **Step 5: The run page.** In `dashboard/src/pages/RunDetailPage.tsx`:
- add `import StatusPill from "../components/StatusPill";` and `import { isSubset, stagesLine } from "../lib/runScope";`;
- after `const run = query.data;`, add `const stagesText = run ? stagesLine(run) : null;`;
- after the paragraph that renders `run.commit_author` / `commit_message` / `pr_number` / `base_branch` (before `{previousRun && (`), add:

```tsx
          {stagesText !== null && (
            <p className="run-stages">
              {isSubset(run) && <><StatusPill tone="neutral" label="Suggested only" />{" "}</>}
              <span>{stagesText}</span>
            </p>
          )}
```

At the end of `dashboard/src/index.css`, add:

```css
/* run-impact's stages on the run page (spec 2026-10-13 §3.2): figures line up from run to run */
.run-stages { font-variant-numeric: tabular-nums; }
```

- [ ] **Step 6: Run the tests**

Run: `cd dashboard && npx vitest run src/lib/runScope.test.ts src/pages/RunDetailPage.test.tsx`
Expected: PASS.

- [ ] **Step 7: DESIGN.md.** In the "Likely affected tests" section, after the **Run page card** bullet and its sub-bullets, add:

```markdown
- **Suggested tests first** (spec `docs/superpowers/specs/2026-10-13-suggested-tests-first-design.md`):
  - **Run page line** (`.run-stages`, tabular figures), under the run's metadata, only for a run uploaded by
    `run-impact`. For example: "Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2 (the rest)
    340 tests in 14m 10s · first failure after 42.5 s (full suite 15m 15s)".
    - A run of only the suggested tests starts with a neutral "Suggested only" Status Pill and reads "Suggested
      tests only", or "Suggested tests only, stopped after stage 1" after a `--fail-fast` stop.
    - Durations use `formatDuration`, as everywhere else.
```

- [ ] **Step 8: Lint, typecheck, commit**

Run: `cd dashboard && npm run lint && npm run typecheck`
Expected: no errors.

```bash
git add dashboard/src/api/runs.ts dashboard/src/lib/runScope.ts dashboard/src/lib/runScope.test.ts dashboard/src/pages/RunDetailPage.tsx dashboard/src/pages/RunDetailPage.test.tsx dashboard/src/index.css DESIGN.md
git commit -m "feat(dashboard): the run page says how a run-impact run's stages went, and marks suggested-only runs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/api/runs.ts dashboard/src/lib/runScope.ts dashboard/src/lib/runScope.test.ts dashboard/src/pages/RunDetailPage.tsx dashboard/src/pages/RunDetailPage.test.tsx dashboard/src/index.css DESIGN.md
```

### Task 7: Dashboard: the runs list's "Suggested only" pill and filter

**Files:**
- Modify: `dashboard/src/pages/RunsPage.tsx`, `dashboard/src/pages/RunsPage.test.tsx`, `DESIGN.md`

**Interfaces:**
- Consumes: `RunFilters.scope`, `isSubset`, `stoppedAfterStage1` (Task 6); `GET /runs?scope=` (Task 2).
- Produces: the URL key `scope` (`full` | `impact-subset`) on the runs list; the quick chip "Full runs only"; the "Runs" filter under More filters.

Ruling 18 applies.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill** (Skill tool).

- [ ] **Step 1: Write the failing tests.**
- In `dashboard/src/pages/RunsPage.test.tsx`, change the first import to `import { render, screen, waitFor, within } from "@testing-library/react";`.
- Append:

```tsx
const subsetRun = (id: number) => ({
  ...run(id), scope: "impact-subset",
  stages: { stages: [{ name: "suggested", duration_s: 65, tests: 12, failed: 1 }], time_to_first_failure_s: 30, stopped_after_stage: 1 },
});

test("a suggested-only run carries a pill, and Full runs only asks the server to leave them out", async () => {
  const scopes: (string | null)[] = [];
  server.use(http.get("/api/v1/projects/42/runs", ({ request }) => {
    const scope = new URL(request.url).searchParams.get("scope");
    scopes.push(scope);
    return HttpResponse.json(scope === "full" ? [run(61)] : [subsetRun(62), run(61)]);
  }));
  renderRuns();
  const row = (await screen.findByRole("link", { name: "#62" })).closest("tr")!;
  expect(within(row).getByText("Suggested only · stopped after stage 1")).toBeInTheDocument();
  expect(within(screen.getByRole("link", { name: "#61" }).closest("tr")!).queryByText(/Suggested only/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Full runs only" }));
  await waitFor(() => expect(screen.queryByRole("link", { name: "#62" })).not.toBeInTheDocument());
  expect(scopes[scopes.length - 1]).toBe("full");
  expect(screen.getByTestId("location")).toHaveTextContent("scope=full");
});

test("the Runs filter names the applied scope", async () => {
  server.use(http.get("/api/v1/projects/42/runs", () => HttpResponse.json([])));
  renderRuns("/projects/42/runs?scope=impact-subset");
  expect(await screen.findByText("Runs: Suggested tests only")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Full runs only" })).toHaveAttribute("aria-pressed", "false");
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd dashboard && npx vitest run src/pages/RunsPage.test.tsx`
Expected: FAIL: no pill, no "Full runs only" chip, and no "Runs" filter.

- [ ] **Step 3: The pill and the filter.** In `dashboard/src/pages/RunsPage.tsx`:
- replace `import { RunVerdictPill } from "../components/StatusPill";` with `import StatusPill, { RunVerdictPill } from "../components/StatusPill";`;
- add `import { isSubset, stoppedAfterStage1 } from "../lib/runScope";`;
- replace the block from `const KEYS = [...]` through the end of `function appliedFilters` (it holds `KEYS`, `ADVANCED`, `type Key`, `type Values`, `QUICK`, `FILTER_NAMES` and `appliedFilters`) with:

```tsx
const KEYS = ["status", "branch", "environment", "ci_provider", "commit", "pr", "author", "scope", "from", "to"] as const;
const ADVANCED = ["environment", "ci_provider", "commit", "pr", "author", "scope", "from", "to"] as const;
type Key = (typeof KEYS)[number];
type Values = Record<Key, string>;

/** run-impact's partial runs (spec 2026-10-13 §3.2): "full" hides them. */
const SCOPE_LABELS: Record<string, string> = { full: "Full suite only", "impact-subset": "Suggested tests only" };

const QUICK: QuickChip[] = [
  { key: "status", value: "failing", label: "Failed" },
  { key: "status", value: "passing", label: "Passed" },
  { key: "branch", value: "main", label: "main" },
  { key: "scope", value: "full", label: "Full runs only" },
];
const FILTER_NAMES: Record<Key, string> = {
  status: "Status", branch: "Branch", environment: "Environment", ci_provider: "CI", commit: "Commit",
  pr: "Pull request", author: "Author", scope: "Runs", from: "From", to: "To",
};
function appliedFilters(v: Values): AppliedFilter[] {
  return KEYS.filter((k) => v[k] !== "").map((k) => ({
    key: k,
    name: FILTER_NAMES[k],
    value: k === "status" ? (v[k] === "failing" ? "With failures" : v[k] === "passing" ? "All green" : v[k])
      : k === "ci_provider" ? CI_LABELS[v[k]] ?? v[k] : k === "pr" ? `#${v[k]}`
      : k === "scope" ? SCOPE_LABELS[v[k]] ?? v[k] : v[k],
  }));
}
```

- in `toFilters`, after the `author:` line, add:

```tsx
    scope: v.scope === "full" || v.scope === "impact-subset" ? v.scope : undefined,
```

- in the More filters `FilterBar`, after the Author `<label>…</label>`, add:

```tsx
            <FilterSelect label="Runs" value={form.scope} onChange={(v) => set("scope", v)}
              options={Object.entries(SCOPE_LABELS).map(([value, label]) => ({ value, label }))} />
```

- in the table's first cell, replace `<Link to={`${r.id}`}>#{r.id}</Link>` with:

```tsx
                    <Link to={`${r.id}`}>#{r.id}</Link>
                    {isSubset(r) && (
                      <>{" "}<StatusPill tone="neutral" label="Suggested only"
                        note={stoppedAfterStage1(r) ? "stopped after stage 1" : undefined} /></>
                    )}
```

- [ ] **Step 4: Run the tests**

Run: `cd dashboard && npx vitest run src/pages/RunsPage.test.tsx src/pages/listLayout.test.tsx src/pages/urlState.test.tsx`
Expected: PASS.

- [ ] **Step 5: DESIGN.md.** Under the **Suggested tests first** bullet (Task 6), add:

```markdown
  - **Runs list:**
    - the same neutral pill beside the run number ("Suggested only · stopped after stage 1" for a stop);
    - the quick chip **Full runs only**;
    - the **Runs** filter under More filters: Full suite only, or Suggested tests only.
```

- [ ] **Step 6: Lint, typecheck, commit**

Run: `cd dashboard && npm run lint && npm run typecheck`
Expected: no errors.

```bash
git add dashboard/src/pages/RunsPage.tsx dashboard/src/pages/RunsPage.test.tsx DESIGN.md
git commit -m "feat(dashboard): runs list marks suggested-only runs and can hide them" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/pages/RunsPage.tsx dashboard/src/pages/RunsPage.test.tsx DESIGN.md
```

### Task 8: Dashboard: the impact card's "not evaluated" state

**Files:**
- Modify: `dashboard/src/api/impact.ts`, `dashboard/src/lib/impactQueries.ts`
- Modify: `dashboard/src/components/ImpactCard.tsx`, `dashboard/src/components/ImpactCard.test.tsx`, `DESIGN.md`

**Interfaces:**
- Consumes: `RunImpactOut.evaluation` (Task 3).
- Produces: `RunImpact.evaluation?: "pending" | "evaluated" | "not_evaluated" | null`. `impactPollInterval` returns `false` for `not_evaluated`.

Rulings 3 and 18 apply.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill** (Skill tool).

- [ ] **Step 1: Write the failing tests.** In `dashboard/src/components/ImpactCard.test.tsx`, before `describe("a pending outcome", ...)`, add:

```tsx
test("a suggested-only run is not evaluated, and says why", async () => {
  renderCard(impact({ outcome: null, evaluation: "not_evaluated" }));
  expect(await screen.findByText("Suggested tests only, not evaluated: only the suggested tests ran, so this run cannot"
    + " show what the suggestion missed.")).toBeInTheDocument();
  expect(screen.getByText("Not evaluated", { selector: ".pill" })).toBeInTheDocument();
  expect(screen.queryByText(/outcome not recorded yet/)).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "pays" })).toBeInTheDocument(); // the suggestion itself is still listed
});
```

Inside `describe("a pending outcome", ...)`, add:

```tsx
  test("is never asked for when the run is not evaluated", async () => {
    let calls = 0;
    server.use(http.get(IMPACT_URL, () => { calls += 1; return HttpResponse.json(impact({ outcome: null, evaluation: "not_evaluated" })); }));
    mount();
    expect(await screen.findByText(/Suggested tests only, not evaluated/)).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(IMPACT_POLL_MS * 3));
    expect(calls).toBe(1);
  });
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd dashboard && npx vitest run src/components/ImpactCard.test.tsx`
Expected: FAIL. The type has no `evaluation`, the card says "outcome not recorded yet", and it keeps polling.

- [ ] **Step 3: The type and the polling.** In `dashboard/src/api/impact.ts`, in `RunImpact`, after `outcome`, add:

```ts
  /** `not_evaluated`: the run ran only the suggested tests, so it cannot show what the suggestion missed (spec 2026-10-13
   *  §3.1). Null without a stored suggestion; older servers omit it. */
  evaluation?: "pending" | "evaluated" | "not_evaluated" | null;
```

In `dashboard/src/lib/impactQueries.ts`, in `impactPollInterval`, replace the `pending` line with:

```ts
  const pending = data !== undefined && data.suggestion !== null && data.outcome === null && data.evaluation !== "not_evaluated";
```

- [ ] **Step 4: The card.** In `dashboard/src/components/ImpactCard.tsx`, in `Body`, replace:

```tsx
      <Outcome projectId={projectId} branch={branch} suggested={s.tests.length} outcome={data.outcome} />
```

with:

```tsx
      {data.evaluation === "not_evaluated" ? (
        <p className="muted impact-outcome">
          Suggested tests only, not evaluated: only the suggested tests ran, so this run cannot show what the suggestion missed.
        </p>
      ) : (
        <Outcome projectId={projectId} branch={branch} suggested={s.tests.length} outcome={data.outcome} />
      )}
```

In `ImpactCard`'s heading row, after `{query.data?.replayed && <StatusPill tone="neutral" label="Replayed" />}`, add:

```tsx
        {query.data?.evaluation === "not_evaluated" && <StatusPill tone="neutral" label="Not evaluated" />}
```

- [ ] **Step 5: Run the tests**

Run: `cd dashboard && npx vitest run src/components/ImpactCard.test.tsx src/lib/impactQueries.test.ts`
Expected: PASS.

- [ ] **Step 6: DESIGN.md.** Under the **Suggested tests first** bullet, add:

```markdown
  - **Impact card of a subset run:**
    - a neutral "Not evaluated" pill beside the heading;
    - instead of the outcome, the sentence "Suggested tests only, not evaluated: only the suggested tests ran, so
      this run cannot show what the suggestion missed.";
    - the suggestion is still listed, and the card never polls.
```

- [ ] **Step 7: Lint, typecheck, commit**

Run: `cd dashboard && npm run lint && npm run typecheck`
Expected: no errors.

```bash
git add dashboard/src/api/impact.ts dashboard/src/lib/impactQueries.ts dashboard/src/components/ImpactCard.tsx dashboard/src/components/ImpactCard.test.tsx DESIGN.md
git commit -m "feat(dashboard): the impact card of a suggested-only run says it is not evaluated, and stops polling" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/api/impact.ts dashboard/src/lib/impactQueries.ts dashboard/src/components/ImpactCard.tsx dashboard/src/components/ImpactCard.test.tsx DESIGN.md
```

### Task 9: Gateway smoke: a two-stage upload, a subset upload left out of the statistics, the collector's scoring

**Files:**
- Modify: `scripts/smoke_gateway.sh` (stays `100755`)

**Interfaces:**
- Consumes: Tasks 1–5 through the gateway on PostgreSQL. It reuses `IMPACT_BRANCH`, `IMPACT_TEST`, `IMPACT_CHANGES`, `API_KEY`, `AUTH`, `PROJECT_ID`, `SUFFIX`, `at`, `check`, `body_has`, `body_lacks`, `pass` and `fail` from the script.
- Produces smoke lines proving:
  - a two-stage upload is stored as `full` with its stages;
  - a subset upload is `not_evaluated`, left out by `scope=full`, and absent from `impact_test_base` after a rollup pass;
  - `POST /api/v1/collect/impact` answers with the API key.

The gateway itself is not changed: `/api/v1/collect` already routes to ingestion.

- [ ] **Step 1: Two-stage and subset uploads, before the rollup pass.** With the Edit tool, after this line of `scripts/smoke_gateway.sh`:

```bash
check "impact of a run that is not there -> 404" 404 GET "$BASE/api/v1/projects/$PROJECT_ID/runs/999999999/impact" "${AUTH[@]}"
```

insert:

```bash
# ---- suggested tests first (spec 2026-10-13 §5): a two-stage run, and a run of only the suggested tests ----
# The subset run also fails IMPACT_TEST, so the branch's latest run still names it ("failing on this branch" below).
SUBSET_TEST="subset-only-$SUFFIX"
STAGES_FULL='"scope":"full","stages":{"stages":[{"name":"suggested","duration_s":65.0,"tests":1,"failed":1},{"name":"rest","duration_s":850.0,"tests":1,"failed":0}],"time_to_first_failure_s":42.5}'
STAGES_STOPPED='"scope":"impact-subset","stages":{"stages":[{"name":"suggested","duration_s":65.0,"tests":2,"failed":2}],"time_to_first_failure_s":30.0,"stopped_after_stage":1}'
TWO_STAGE_RUN="{\"run\":{\"ci_provider\":\"local\",\"branch\":\"$IMPACT_BRANCH\",\"started_at\":\"$(at -34)\",\"finished_at\":\"$(at -33)\",$STAGES_FULL},\"results\":[{\"name\":\"$IMPACT_TEST\",\"status\":\"failed\",\"message\":\"broke\"},{\"name\":\"steady-$SUFFIX\",\"status\":\"passed\"}],$IMPACT_CHANGES}"
SUBSET_RUN="{\"run\":{\"ci_provider\":\"local\",\"branch\":\"$IMPACT_BRANCH\",\"started_at\":\"$(at -32)\",\"finished_at\":\"$(at -31)\",$STAGES_STOPPED},\"results\":[{\"name\":\"$IMPACT_TEST\",\"status\":\"failed\",\"message\":\"broke\"},{\"name\":\"$SUBSET_TEST\",\"status\":\"failed\",\"message\":\"broke\"}],$IMPACT_CHANGES}"
check "upload a two-stage run (run-impact, scope full)" 201 POST "$BASE/api/v1/collect/runs" \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "$TWO_STAGE_RUN"
TWO_STAGE_ID="$(grep -o '"id":[0-9]*' "$TMP/body" | head -1 | cut -d: -f2)"
check "read the two-stage run" 200 GET "$BASE/api/v1/runs/${TWO_STAGE_ID:-0}" "${AUTH[@]}"
body_has "... stored as a full run" '"scope":"full"'
body_has "... with its time to the first failure" '"time_to_first_failure_s":42.5'
check "upload a run of only the suggested tests, stopped after stage 1" 201 POST "$BASE/api/v1/collect/runs" \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "$SUBSET_RUN"
SUBSET_ID="$(grep -o '"id":[0-9]*' "$TMP/body" | head -1 | cut -d: -f2)"
check "impact of the suggested-only run" 200 GET "$BASE/api/v1/projects/$PROJECT_ID/runs/${SUBSET_ID:-0}/impact" "${AUTH[@]}"
body_has "... is not evaluated" '"evaluation":"not_evaluated"'
body_has "... and has no outcome" '"outcome":null'
check "the runs list without suggested-only runs" 200 GET \
  "$BASE/api/v1/projects/$PROJECT_ID/runs?scope=full&branch=$IMPACT_BRANCH" "${AUTH[@]}"
body_lacks "... leaves the suggested-only run out" "\"id\":${SUBSET_ID:-0},"
body_has "... and keeps the two-stage run" "\"id\":${TWO_STAGE_ID:-0},"
```

- [ ] **Step 2: After the rollup pass, the subset run's test is not in the statistics.** After this block:

```bash
else
  fail "impact rollup pass: $(tail -c 400 "$TMP/impact_err")"
fi
```

insert:

```bash
IMPACT_BASE_ROWS="$(docker compose exec -T postgres psql -U postgres -d ingestion_db -tAc \
  "SELECT count(*) FROM impact_test_base WHERE name = '$IMPACT_TEST'" | tr -d '\r ')"
SUBSET_BASE_ROWS="$(docker compose exec -T postgres psql -U postgres -d ingestion_db -tAc \
  "SELECT count(*) FROM impact_test_base WHERE name = '$SUBSET_TEST'" | tr -d '\r ')"
if [ "${IMPACT_BASE_ROWS:-0}" != "0" ] && [ "$SUBSET_BASE_ROWS" = "0" ]; then
  pass "the rollup counted today's full runs and left the suggested-only run out of the statistics"
else
  fail "impact_test_base: $IMPACT_TEST has ${IMPACT_BASE_ROWS:-?} row(s) (want 1+), $SUBSET_TEST has ${SUBSET_BASE_ROWS:-?} (want 0)"
fi
```

- [ ] **Step 3: The collector's scoring with the API key.** After these lines:

```bash
check "score a change without paths -> 422" 422 POST \
  "$BASE/api/v1/projects/$PROJECT_ID/analytics/impact" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"changed_paths":[]}'
```

insert:

```bash
check "score a change with the API key -> /api/v1/collect/impact" 200 POST "$BASE/api/v1/collect/impact" \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d "{\"changed_paths\":[\"src/impact/smoke.py\"],\"branch\":\"$IMPACT_BRANCH\"}"
body_has "... suggests the test failing on the branch, as the collector reads it" "\"name\":\"$IMPACT_TEST\",\"kind\":\"failing_on_branch\""
check "the collector's scoring without a key -> 401" 401 POST "$BASE/api/v1/collect/impact" \
  -H "Content-Type: application/json" -d '{"changed_paths":["src/impact/smoke.py"]}'
```

- [ ] **Step 4: Run the smoke against a fresh stack**

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose exec -T ingestion-service alembic current
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```

Expected:
- `020 (head)`;
- the new lines print `ok`;
- the run ends with `all gateway checks passed`.

- [ ] **Step 5: Commit, keeping the executable bit**

```bash
git add scripts/smoke_gateway.sh
git update-index --chmod=+x scripts/smoke_gateway.sh
git diff --cached --name-only
```

Expected: exactly `scripts/smoke_gateway.sh`. If anything else is listed, unstage it with `git restore --staged <path>` first.

```bash
git commit -m "test(smoke): a two-stage run, a suggested-only run left out of the statistics, and the collector's scoring" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git ls-files -s scripts/smoke_gateway.sh
```

Expected: `100755`.

### Task 10: Phase 1 gate

**Files:** `TODO.md`, plus fixes only, in the files of Tasks 1–9.

**Interfaces:**
- Consumes: everything in Phase 1.
- Produces: a pushed `master` with the QEOS side live.

- [ ] **Step 1: TODO.** In `TODO.md`, replace the line

```markdown
   - [ ] Release B: a collector command that runs the suggested tests first (never instead of the full suite), from `POST /analytics/impact`
```

with

```markdown
   - [ ] Release B, suggested tests first in CI (spec `docs/superpowers/specs/2026-10-13-suggested-tests-first-design.md`):
     - QEOS side done 2026-10-13:
       - run `scope` and `stages` (ingestion migration 020);
       - runs of only the suggested tests left out of the statistics, outcomes and accuracy (`not_evaluated`);
       - `POST /collect/impact`;
       - labels in the dashboard and in the alerts.
     - Pending: the collector's `impact` and `run-impact`.
```

Commit it: `git add TODO.md && git commit -m "docs(todo): release B, QEOS side done" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- TODO.md`

- [ ] **Step 2: Every Python suite, serially**

```bash
cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests -q
cd platforms/organization-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/auth-service/auth-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd platforms/test-management-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q
cd collector && .venv/Scripts/python -m pytest -q
```

Expected: all green. Run them one after another (each from the repository root), never two at once.

- [ ] **Step 3: Dashboard, as CI runs it**

Run: `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build && node --test ../templates/github/qeos-run.test.mjs`
Expected: all green.

- [ ] **Step 4: Docs check, monitoring, the ingestion container smoke**

```bash
python scripts/check_architecture_docs.py && python -m pytest scripts/tests -q
bash monitoring/check.sh
cd platforms/ingestion-service && SECRET_KEY=ci-smoke-secret docker compose up --build --detach --wait --wait-timeout 180 && curl --fail --silent --show-error http://localhost:8003/health && SECRET_KEY=ci-smoke-secret docker compose down --volumes
```

Expected:
- no findings from the docs check, and its tests pass;
- `monitoring: all checks passed`;
- `{"status":"healthy"}` (that stack uses throwaway volumes, as CI's `smoke` job does).

- [ ] **Step 5: NGINX and the full smoke**

```bash
docker build -t qeos/gateway:ci gateway && docker run --rm qeos/gateway:ci nginx -t && docker run --rm -e MONITORING_ENABLED=true qeos/gateway:ci nginx -t
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose exec -T ingestion-service alembic current
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```

Expected:
- `nginx: configuration file /etc/nginx/nginx.conf test is successful`, twice;
- `020 (head)`;
- the smoke ends with `all gateway checks passed`.

- [ ] **Step 6: Tear down, check, push**

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose down
git ls-files -s scripts/smoke_gateway.sh
git status --short
git log --oneline origin/master..master
git push origin master
sha="$(git rev-parse HEAD)"
until run_id="$(gh run list --workflow ci.yml --commit "$sha" --json databaseId --jq '.[0].databaseId')" && [ -n "$run_id" ]; do sleep 5; done
gh run watch --exit-status "$run_id"
```

Expected:
- `100755`;
- no modified tracked file of this plan (untracked `.claude/`, `.codex/`, `.github/hooks/` and `__pycache__/` were there before and stay uncommitted);
- the log lists the Phase 1 commits;
- the push succeeds as `carneiru`, and CI on `master` is green.

Never `docker compose down -v`.

---

# Phase 2 — Collector `impact`

At the end of this phase, `qeos-collector impact` prints the likely affected tests for the current change, as Cucumber locations, a list or JSON, with exit codes a pipeline can branch on. No collector release yet: Phase 3 releases 0.6.0.

### Task 11: Feature-file lines for the suggested scenarios

**Files:**
- Create: `collector/src/qeos_collector/cucumber.py`
- Test: `collector/tests/test_cucumber_locate.py` (new)

**Interfaces:**
- Consumes: nothing new; stdlib only.
- Produces, in `qeos_collector.cucumber`:
  - `scan_feature(text: str) -> List[Tuple[str, int]]`;
  - `locate(cwd: str, test: dict) -> List[str]` (`"uri:line"` strings);
  - `name_filter(name: str) -> str`;
  - `has_feature_files(cwd: str) -> bool`.

  Phase 3 adds the runner adapters to the same module.

Ruling 14 applies.

- [ ] **Step 1: Write the failing tests.** Create `collector/tests/test_cucumber_locate.py`:

```python
"""Where a suggested scenario is, read from the local .feature files (spec 2026-10-13 §2.1; plan Ruling 14)."""
from qeos_collector.cucumber import has_feature_files, locate, name_filter, scan_feature

PAY = (
    "@payments\n"                                        # 1
    "Feature: Pay\n"                                     # 2
    "\n"                                                 # 3
    "  Background:\n"                                    # 4
    "    Given a shopper\n"                              # 5
    "\n"                                                 # 6
    "  @smoke\n"                                         # 7
    "  Scenario: Pays with card\n"                       # 8
    "    When the shopper pays: by card\n"               # 9
    "      | card | 4111 |\n"                            # 10
    "\n"                                                 # 11
    "  Scenario Outline: Pays <amount> in <currency>\n"  # 12
    "    When the shopper pays <amount>\n"               # 13
    "\n"                                                 # 14
    "    Examples:\n"                                    # 15
    "      | amount | currency |\n"                      # 16
    "      | 10     | EUR      |\n"                      # 17
    "      | 20     | USD      |\n"                      # 18
    "\n"                                                 # 19
    "  Rule: refunds\n"                                  # 20
    "    Example: Refunds a payment\n"                   # 21
    "      Then the money returns\n"                     # 22
)


def test_scenarios_and_outline_rows_have_their_own_lines():
    assert scan_feature(PAY) == [("Pays with card", 8), ("Pays 10 in EUR", 17), ("Pays 20 in USD", 18),
                                 ("Refunds a payment", 21)]


def test_a_scenario_template_with_scenarios():
    text = "Feature: F\n  Scenario Template: T <x>\n    Scenarios:\n      | x |\n      | a |\n"
    assert scan_feature(text) == [("T a", 5)]


def test_a_feature_in_another_language_gives_no_lines():
    assert scan_feature("# language: fr\nFonctionnalité: Payer\n  Scénario: Paie\n") == []
    assert scan_feature("# language: en\nFeature: Pay\n  Scenario: Pays\n") == [("Pays", 3)]


def test_locate_reads_the_tests_feature_file(tmp_path):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "pay.feature").write_text(PAY, encoding="utf-8")
    test = {"suite": "Pay", "class_name": "features/pay.feature", "name": "Pays with card"}
    assert locate(str(tmp_path), test) == ["features/pay.feature:8"]
    assert locate(str(tmp_path), {**test, "class_name": "file:features/pay.feature"}) == ["file:features/pay.feature:8"]
    assert locate(str(tmp_path), {**test, "name": "Pays 20 in USD"}) == ["features/pay.feature:18"]


def test_windows_line_endings_and_a_byte_order_mark_change_nothing(tmp_path):
    (tmp_path / "pay.feature").write_bytes(("﻿" + PAY.replace("\n", "\r\n")).encode("utf-8"))
    assert locate(str(tmp_path), {"class_name": "pay.feature", "name": "Pays 20 in USD"}) == ["pay.feature:18"]


def test_locate_gives_nothing_it_cannot_read_here(tmp_path):
    (tmp_path / "pay.feature").write_text(PAY, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    for class_name in ("classpath:features/pay.feature", "missing.feature", "PayTest", "../pay.feature",
                       str(tmp_path / "pay.feature")):
        assert locate(str(tmp_path / "sub"), {"class_name": class_name, "name": "Pays with card"}) == []


def test_a_name_filter_is_anchored_and_safe_to_paste():
    assert name_filter("Gone away") == '--name "^Gone away$"'
    assert name_filter('Pay $5 (card) "now"!') == '--name "^Pay .5 .card. .now..$"'
    assert name_filter("a\tb\nc") == '--name "^a.b.c$"'


def test_feature_files_are_found_outside_vendored_folders(tmp_path):
    assert not has_feature_files(str(tmp_path))
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "a.feature").write_text("Feature: A\n", encoding="utf-8")
    assert not has_feature_files(str(tmp_path))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "b.feature").write_text("Feature: B\n", encoding="utf-8")
    assert has_feature_files(str(tmp_path))
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_cucumber_locate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'qeos_collector.cucumber'`.

- [ ] **Step 3: Write the module.** Create `collector/src/qeos_collector/cucumber.py`:

```python
"""Cucumber helpers for test impact (spec 2026-10-13 §2): where a suggested scenario is, as a Cucumber location.

`impact --format cucumber` reads the lines from the local .feature files (plan Ruling 14): English keywords only; a
classpath: uri, a file in another language or one outside the working directory gives no line, and the scenario is
named instead. run-impact takes its lines from Cucumber's own dry run."""
from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

_SCENARIO = ("Scenario", "Example")
_OUTLINE = ("Scenario Outline", "Scenario Template")
_EXAMPLES = ("Examples", "Scenarios")
_BLOCKS = ("Feature", "Rule", "Background")
_LANGUAGE = re.compile(r"^#\s*language\s*:\s*(\S+)")
# Special in a regular expression or in a double-quoted shell word: each becomes "." (any character) in a name filter
_UNSAFE = frozenset('\\^$.|?*+()[]{}"`!')
# Folders never looked into for .feature files
_PRUNE = frozenset({".git", "node_modules", ".venv", "venv", "target", "build", "dist", ".qeos-impact"})


def _cells(row: str) -> List[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _fill(name: str, header: List[str], values: List[str]) -> str:
    for column, value in zip(header, values):
        name = name.replace(f"<{column}>", value)
    return name


def scan_feature(text: str) -> List[Tuple[str, int]]:
    """(name, line) for each scenario, and for each example row of an outline, named as Cucumber names it: the
    outline's name with the row's values in place of <placeholders>. Empty for a file in another language."""
    found: List[Tuple[str, int]] = []
    outline: Optional[dict] = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("@"):
            continue
        if line.startswith("#"):
            language = _LANGUAGE.match(line)
            if language and language.group(1).lower() != "en":
                return []
            continue
        if line.startswith("|"):
            if outline is not None and outline["examples"]:
                if outline["header"] is None:
                    outline["header"] = _cells(line)
                else:
                    found.append((_fill(outline["name"], outline["header"], _cells(line)), number))
            continue
        keyword, colon, rest = line.partition(":")
        if not colon:
            continue
        keyword = keyword.strip()
        if keyword in _SCENARIO:
            outline = None
            found.append((rest.strip(), number))
        elif keyword in _OUTLINE:
            outline = {"name": rest.strip(), "examples": False, "header": None}
        elif keyword in _EXAMPLES and outline is not None:
            outline["examples"], outline["header"] = True, None
        elif keyword in _BLOCKS:
            outline = None
    return found


def locate(cwd: str, test: dict) -> List[str]:
    """`uri:line` for each scenario (or outline row) of the test's feature file that has the test's name; empty when
    the file cannot be read here."""
    uri = str(test.get("class_name") or "")
    if uri.startswith("classpath:"):
        return []
    relative = uri[len("file:"):] if uri.startswith("file:") else uri
    if not relative.endswith(".feature"):
        return []
    root = os.path.realpath(cwd)
    path = os.path.realpath(os.path.join(root, relative))
    try:
        if os.path.commonpath([root, path]) != root:
            return []
        with open(path, encoding="utf-8-sig") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError, ValueError):  # ValueError: another Windows drive
        return []
    name = str(test.get("name") or "")
    return [f"{uri}:{line}" for found, line in scan_feature(text) if found == name]


def name_filter(name: str) -> str:
    """`--name "^…$"` for a scenario whose line is unknown. Characters special to a regular expression or to a
    double-quoted shell word, and control characters, become "." so the line is safe to paste and still matches."""
    return '--name "^' + "".join("." if c in _UNSAFE or c < " " else c for c in name) + '$"'


def has_feature_files(cwd: str) -> bool:
    """Whether the working directory holds a .feature file (vendored and build folders are not looked into)."""
    for _root, directories, files in os.walk(cwd):
        directories[:] = [d for d in directories if d not in _PRUNE]
        if any(name.endswith(".feature") for name in files):
            return True
    return False
```

- [ ] **Step 4: Run the tests**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_cucumber_locate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add collector/src/qeos_collector/cucumber.py collector/tests/test_cucumber_locate.py
git commit -m "feat(collector): scenario and outline-row lines from local feature files, for impact suggestions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- collector/src/qeos_collector/cucumber.py collector/tests/test_cucumber_locate.py
```

No `.md` changes: nothing a user can call yet. Task 13 documents the command.

### Task 12: Asking QEOS for the change's suggestion (exit codes 0, 3, 4)

**Files:**
- Create: `collector/src/qeos_collector/impact.py`
- Test: `collector/tests/test_impact_client.py` (new)

**Interfaces:**
- Consumes:
  - `gitdiff.collect_changes(env, commit) -> Optional[dict]`;
  - `upload._send`, `_json`, `_detail`, `_reason`, `_is_tls_error`, `endpoint_for`, `make_context`, `ConfigError`, `COLLECT_PATH`;
  - `ci.detect`, `config_file.load_config`;
  - `POST /api/v1/collect/impact` (Task 4).
- Produces, in `qeos_collector.impact`:
  - `SUGGESTED = 0`, `NOTHING = 3`, `UNAVAILABLE = 4`;
  - `Target(url: str, context: ssl.SSLContext, commit: Optional[str], branch: Optional[str])`;
  - `Suggestion(code: int, reason: str = "", data: Optional[dict] = None, paths: List[str] = [])`, with the property `tests -> List[dict]`;
  - `resolve(args, env, api_key, cwd) -> Target`, which reads `args.url`, `ca_file`, `client_cert`, `client_key`, `commit`, `branch` when present;
  - `fetch(target, api_key, env, *, collect=None, send=None) -> Suggestion`. Its `collect_changes` is looked up at call time, so tests patch `impact.collect_changes`.

Rulings 1 and 2 apply.

- [ ] **Step 1: Write the failing tests.** Create `collector/tests/test_impact_client.py`:

```python
"""Asking QEOS for the change's suggestion (spec 2026-10-13 §2.1; plan Rulings 1, 2)."""
import json
import re
from types import SimpleNamespace

import pytest

from qeos_collector import impact
from qeos_collector.upload import ConfigError

KEY = "qeos_impact_client_key"
CHANGES = {"base_ref": "origin/main", "truncated": False,
           "files": [{"path": "src/pay/api.py", "status": "M", "additions": 3, "deletions": 1},
                     {"path": "features/pay.feature", "status": "M", "additions": 1, "deletions": 0}]}
LABELLED = {"test_key": "c" * 64, "suite": "api", "class_name": "PayTest", "name": "refunds",
            "kind": "failing_on_branch", "evidence": None}


def answer(tests, state="ok"):
    return {"state": state, "model_version": "stats-v1", "history_runs": 34 if state == "ok" else 7, "needed_runs": 20,
            "statistical_total": 0, "tests": tests}


def target(url, commit="abc1234", branch="feature/pay"):
    return impact.Target(url=url, context=None, commit=commit, branch=branch)


def fetch(url, changes=CHANGES):
    return impact.fetch(target(url), KEY, {}, collect=lambda env, commit: changes)


def no_args(**values):
    return SimpleNamespace(**{"url": None, "ca_file": None, "commit": None, "branch": None, **values})


def test_the_change_and_branch_are_sent_with_the_key(platform):
    platform.reply(200, answer([LABELLED]))
    found = fetch(platform.url)
    assert found.code == impact.SUGGESTED and found.tests == [LABELLED]
    request = platform.requests[0]
    assert request["path"] == "/api/v1/collect/impact"
    assert request["headers"]["Authorization"] == f"Bearer {KEY}"
    assert json.loads(request["body"]) == {"changed_paths": ["src/pay/api.py", "features/pay.feature"],
                                           "branch": "feature/pay"}


def test_the_commit_reaches_the_diff():
    seen = []
    found = impact.fetch(target("https://qeos.acme.test", commit="def5678"), KEY, {"X": "1"},
                         collect=lambda env, commit: seen.append((dict(env), commit)))
    assert seen == [({"X": "1"}, "def5678")]
    assert found.code == impact.NOTHING  # the stand-in diff returned None: no change data


def test_not_enough_history_with_labelled_tests_is_still_a_suggestion(platform):
    platform.reply(200, answer([LABELLED], state="not_enough_history"))
    assert fetch(platform.url).code == impact.SUGGESTED


@pytest.mark.parametrize("state, reason", [
    ("ok", "no test is likely affected by this change"),
    ("not_enough_history", "not enough history yet (7 of 20 runs with changed files)"),
])
def test_an_empty_suggestion_is_nothing_to_suggest(platform, state, reason):
    platform.reply(200, answer([], state=state))
    found = fetch(platform.url)
    assert found.code == impact.NOTHING and reason in found.reason


@pytest.mark.parametrize("changes", [None, {**CHANGES, "files": []}])
def test_no_change_data_asks_nothing(platform, changes):
    found = fetch(platform.url, changes)
    assert found.code == impact.NOTHING and platform.requests == []


@pytest.mark.parametrize("status, body, reason", [
    (503, {"detail": {"code": "impact_timeout", "message": "slow"}}, "impact_timeout"),
    (503, {"detail": "Service unavailable"}, "answered 503"),
    (502, b"bad gateway", "answered 502"),
    (429, {"detail": "slow down"}, "answered 429"),
    (200, {"unexpected": True}, "unexpected answer"),
])
def test_an_overloaded_slow_or_odd_platform_is_unavailable(platform, status, body, reason):
    platform.reply(status, body)
    found = fetch(platform.url)
    assert found.code == impact.UNAVAILABLE and reason in found.reason


def test_an_unreachable_platform_is_unavailable():
    found = fetch("http://127.0.0.1:9")
    assert found.code == impact.UNAVAILABLE and "cannot reach the platform" in found.reason


@pytest.mark.parametrize("status, message", [
    (401, "invalid or revoked (401)"),
    (404, "older than suggested tests first"),
    (422, "refused the change (422)"),
])
def test_configuration_problems_raise(platform, status, message):
    platform.reply(status, {"detail": "nope"})
    with pytest.raises(ConfigError, match=re.escape(message)):
        fetch(platform.url)


def test_resolve_takes_flags_then_the_environment_then_the_file(tmp_path):
    (tmp_path / ".qeos.yml").write_text("url: https://from-file.acme.test\nbranch: from-file\n", encoding="utf-8")
    found = impact.resolve(no_args(), {"QEOS_BRANCH": "from-env"}, KEY, str(tmp_path))
    assert (found.url, found.branch, found.commit) == ("https://from-file.acme.test", "from-env", None)
    flagged = impact.resolve(no_args(url="https://flag.acme.test", commit="abc1234", branch="flag"), {}, KEY,
                             str(tmp_path))
    assert (flagged.url, flagged.commit, flagged.branch) == ("https://flag.acme.test", "abc1234", "flag")


@pytest.mark.parametrize("env, key, message", [
    ({}, KEY, "QEOS_URL is not set"),
    ({"QEOS_URL": "http://qeos.acme.test"}, KEY, "https://"),
    ({"QEOS_URL": "https://qeos.acme.test"}, "", "QEOS_API_KEY is not set"),
])
def test_resolve_refuses_what_can_never_work(tmp_path, env, key, message):
    with pytest.raises(ConfigError, match=re.escape(message)):
        impact.resolve(no_args(), env, key, str(tmp_path))
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_impact_client.py -q`
Expected: FAIL with `ImportError: cannot import name 'impact'`.

- [ ] **Step 3: Write the client.** Create `collector/src/qeos_collector/impact.py`:

```python
"""The suggestion for the current change, from QEOS (spec 2026-10-13 §2.1; plan Rulings 1, 2).

The change is what an upload would send (gitdiff.collect_changes: the pull- or merge-request base, else the commit's
parent); QEOS scores it with POST /api/v1/collect/impact and the project API key. Codes:
- SUGGESTED (0): a suggestion with tests;
- NOTHING (3): nothing to suggest, or no change data;
- UNAVAILABLE (4): QEOS unreachable, overloaded or out of time.
A configuration problem raises ConfigError (exit 2), as everywhere in the collector."""
from __future__ import annotations

import http.client
import json
import ssl
from dataclasses import dataclass, field
from typing import Callable, List, Mapping, Optional

from qeos_collector import __version__
from qeos_collector.ci import detect
from qeos_collector.config_file import load_config
from qeos_collector.gitdiff import collect_changes
from qeos_collector.upload import (
    COLLECT_PATH, ConfigError, _detail, _is_tls_error, _json, _reason, _send, endpoint_for, make_context,
)

IMPACT_PATH = "/api/v1/collect/impact"
SUGGESTED, NOTHING, UNAVAILABLE = 0, 3, 4
MAX_PATHS = 5000  # the endpoint's cap; the collector's own diff stops at 1,000 files


@dataclass(frozen=True)
class Target:
    url: str
    context: Optional[ssl.SSLContext]
    commit: Optional[str]
    branch: Optional[str]


@dataclass
class Suggestion:
    code: int                    # SUGGESTED, NOTHING or UNAVAILABLE
    reason: str = ""             # why there is no suggestion, for the log
    data: Optional[dict] = None  # QEOS's answer (SuggestionOut)
    paths: List[str] = field(default_factory=list)

    @property
    def tests(self) -> List[dict]:
        return list((self.data or {}).get("tests") or [])


def impact_url(url: str) -> str:
    return endpoint_for(url)[: -len(COLLECT_PATH)] + IMPACT_PATH


def resolve(args, env: Mapping[str, str], api_key: str, cwd: str) -> Target:
    """Where to ask and about what: a flag, then the environment, then .qeos.yml, then CI detection, as `upload`
    reads them."""
    config = load_config(cwd)

    def pick(flag: Optional[str], name: str, file_key: Optional[str] = None) -> Optional[str]:
        value = (flag or "").strip() or env.get(name, "").strip()
        if not value and file_key:
            from_file = config.get(file_key)
            value = from_file.strip() if isinstance(from_file, str) else ""
        return value or None

    url = pick(getattr(args, "url", None), "QEOS_URL", "url")
    if not url:
        raise ConfigError("QEOS_URL is not set (or pass --url, or url: in .qeos.yml)")
    impact_url(url)  # the shape: https://, or http:// for localhost only
    if not api_key:
        raise ConfigError("QEOS_API_KEY is not set; the API key is read from the environment only")
    context = make_context(pick(getattr(args, "ca_file", None), "QEOS_CA_FILE", "ca-file"),
                           client_cert=pick(getattr(args, "client_cert", None), "QEOS_CLIENT_CERT"),
                           client_key=pick(getattr(args, "client_key", None), "QEOS_CLIENT_KEY"))
    ci = detect(env)
    return Target(url=url, context=context,
                  commit=pick(getattr(args, "commit", None), "QEOS_COMMIT") or ci.commit,
                  branch=pick(getattr(args, "branch", None), "QEOS_BRANCH", "branch") or ci.branch)


def fetch(target: Target, api_key: str, env: Mapping[str, str], *, collect: Optional[Callable] = None,
          send: Optional[Callable] = None) -> Suggestion:
    """QEOS's suggestion for the change an upload would send. An unreachable QEOS is UNAVAILABLE, never an error."""
    changes = (collect or collect_changes)(env, target.commit)
    if changes is None:
        return Suggestion(NOTHING, "no change data (no pull-request base, and no commit to compare with its parent)")
    paths = [f["path"] for f in changes["files"]][:MAX_PATHS]
    if not paths:
        return Suggestion(NOTHING, f"no changed files against {changes['base_ref']}")
    body = json.dumps({"changed_paths": paths, "branch": target.branch}).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": f"qeos-collector/{__version__}"}
    try:
        status, raw, _ = (send or _send)(impact_url(target.url), body, headers, target.context)
    except (OSError, http.client.HTTPException) as exc:
        if _is_tls_error(exc):
            raise ConfigError(f"TLS error talking to the platform ({_reason(exc)}); if it uses a private CA, "
                              "pass --ca-file") from None
        return Suggestion(UNAVAILABLE, f"cannot reach the platform ({_reason(exc)})", paths=paths)
    if status == 200:
        data = _json(raw)
        if not isinstance(data.get("tests"), list):
            return Suggestion(UNAVAILABLE, "the platform sent an unexpected answer (no tests list)", paths=paths)
        if data["tests"]:
            return Suggestion(SUGGESTED, data=data, paths=paths)
        if data.get("state") == "not_enough_history":
            reason = (f"not enough history yet ({data.get('history_runs')} of {data.get('needed_runs')} runs with "
                      "changed files) and nothing labelled to run first")
        else:
            reason = "no test is likely affected by this change"
        return Suggestion(NOTHING, reason, data=data, paths=paths)
    if status == 401:
        raise ConfigError("the API key is invalid or revoked (401)")
    if status == 404:
        raise ConfigError("the platform has no /api/v1/collect/impact (404): it is older than suggested tests first, "
                          "or QEOS_URL is wrong")
    if status == 429 or status >= 500:
        detail = _json(raw).get("detail")
        if isinstance(detail, dict) and detail.get("code") == "impact_timeout":
            return Suggestion(UNAVAILABLE, "QEOS ran out of time scoring the change (impact_timeout)", paths=paths)
        return Suggestion(UNAVAILABLE, f"the platform answered {status}", paths=paths)
    raise ConfigError(f"the platform refused the change ({status}): {_detail(raw)}")
```

- [ ] **Step 4: Run the tests**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_impact_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add collector/src/qeos_collector/impact.py collector/tests/test_impact_client.py
git commit -m "feat(collector): ask QEOS for the change's likely affected tests with the project API key" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- collector/src/qeos_collector/impact.py collector/tests/test_impact_client.py
```

### Task 13: `qeos-collector impact`: formats, `--out`, the command, its docs and smoke line

**Files:**
- Modify: `collector/src/qeos_collector/impact.py` (`FORMATS`, `render`, `run`)
- Modify: `collector/src/qeos_collector/cli.py` (the `impact` subcommand, `_usable_key`)
- Modify: `collector/README.md`, `scripts/smoke_gateway.sh` (stays `100755`)
- Test: `collector/tests/test_impact_command.py` (new)

**Interfaces:**
- Consumes:
  - `cucumber.locate`, `name_filter` and `has_feature_files` (Task 11);
  - `impact.resolve`, `fetch` and `Suggestion` (Task 12).
- Produces:
  - `impact.FORMATS = ("cucumber", "list", "json")`;
  - `impact.render(data: dict, fmt: str, locate: Callable[[dict], List[str]]) -> str`;
  - `impact.run(args, env, api_key, say, cwd) -> int`;
  - `cli._usable_key(api_key: str) -> None` (raises `ConfigError`);
  - the CLI `qeos-collector impact [--format cucumber|list|json] [--out FILE] [--url] [--ca-file] [--branch] [--commit]`.

Rulings 2, 14 and 15 apply.

- [ ] **Step 1: Write the failing tests.** Create `collector/tests/test_impact_command.py`:

```python
"""qeos-collector impact (spec 2026-10-13 §2.1; plan Rulings 2, 14, 15)."""
import json

import pytest

from qeos_collector import impact
from qeos_collector.cli import main

KEY = "qeos_impact_command_key"
CHANGES = {"base_ref": "origin/main", "truncated": False,
           "files": [{"path": "src/pay/api.py", "status": "M", "additions": 3, "deletions": 1}]}
PAY = ("Feature: Pay\n\n  Scenario: Pays with card\n    Given a shopper\n\n  Scenario Outline: Pays <amount>\n"
       "    Given a shopper with <amount>\n\n    Examples:\n      | amount |\n      | 10     |\n      | 20     |\n")
SUGGESTION = {
    "state": "ok", "model_version": "stats-v1", "history_runs": 34, "needed_runs": 20, "statistical_total": 1,
    "tests": [
        {"test_key": "a" * 64, "suite": "Pay", "class_name": "features/pay.feature", "name": "Pays 20",
         "kind": "statistical", "evidence": {"path_unit": "src/pay/", "changed_runs": 6, "new_failures": 4,
                                             "confidence": 0.6667, "lift": 22.2, "base_rate": 0.03}},
        {"test_key": "b" * 64, "suite": "Cart", "class_name": "features/cart.feature", "name": "Gone away",
         "kind": "no_history", "evidence": None},
        {"test_key": "c" * 64, "suite": "api\tv2", "class_name": "PayTest", "name": "refunds\nlater",
         "kind": "failing_on_branch", "evidence": None},
    ],
}
CUCUMBER_OUT = 'features/pay.feature:12\n--name "^Gone away$"\n--name "^refunds.later$"\n'


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "pay.feature").write_text(PAY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(impact, "collect_changes", lambda env, commit: CHANGES)
    return tmp_path


def env_for(platform, **extra):
    return {"QEOS_URL": platform.url, "QEOS_API_KEY": KEY, **extra}


def test_cucumber_lines_where_the_file_says_and_names_elsewhere(platform, repo, capsys):
    platform.reply(200, SUGGESTION)
    assert main(["impact"], env_for(platform)) == 0
    out, err = capsys.readouterr()
    assert out == CUCUMBER_OUT
    assert "qeos: 3 likely affected test(s) for 1 changed file(s)" in err


def test_list_is_tab_separated_one_test_per_line(platform, repo, capsys):
    platform.reply(200, SUGGESTION)
    assert main(["impact", "--format", "list"], env_for(platform)) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Pay\tfeatures/pay.feature\tPays 20", "Cart\tfeatures/cart.feature\tGone away", "api v2\tPayTest\trefunds later"]


def test_json_is_the_whole_suggestion(platform, repo, capsys):
    platform.reply(200, SUGGESTION)
    assert main(["impact", "--format", "json"], env_for(platform)) == 0
    assert json.loads(capsys.readouterr().out) == SUGGESTION


def test_out_writes_the_file_with_lf_and_prints_nothing(platform, repo, capsys):
    platform.reply(200, SUGGESTION)
    assert main(["impact", "--out", "suggested.txt"], env_for(platform)) == 0
    assert (repo / "suggested.txt").read_bytes() == CUCUMBER_OUT.encode("utf-8")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("status, body, code", [
    (200, {**SUGGESTION, "tests": []}, 3),
    (503, {"detail": {"code": "impact_timeout", "message": "slow"}}, 4),
])
def test_out_is_emptied_when_nothing_is_suggested(platform, repo, status, body, code):
    """Review Focus 5: a later step must never read an earlier step's list."""
    (repo / "suggested.txt").write_text("features/old.feature:3\n", encoding="utf-8")
    platform.reply(status, body)
    assert main(["impact", "--out", "suggested.txt"], env_for(platform)) == code
    assert (repo / "suggested.txt").read_text(encoding="utf-8") == ""


def test_without_feature_files_the_default_is_a_list(platform, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(impact, "collect_changes", lambda env, commit: CHANGES)
    platform.reply(200, SUGGESTION)
    assert main(["impact"], env_for(platform)) == 0
    assert capsys.readouterr().out.startswith("Pay\tfeatures/pay.feature\tPays 20\n")


def test_nothing_to_suggest_exits_3_and_says_why(platform, repo, capsys):
    platform.reply(200, {**SUGGESTION, "tests": []})
    assert main(["impact"], env_for(platform)) == 3
    out, err = capsys.readouterr()
    assert out == "" and "qeos: no suggestion: no test is likely affected by this change" in err


def test_an_unreachable_platform_exits_4(repo, capsys):
    assert main(["impact"], {"QEOS_URL": "http://127.0.0.1:9", "QEOS_API_KEY": KEY}) == 4
    assert "cannot reach the platform" in capsys.readouterr().err


@pytest.mark.parametrize("env, message", [
    ({"QEOS_API_KEY": KEY}, "QEOS_URL is not set"),
    ({"QEOS_URL": "https://qeos.acme.test"}, "QEOS_API_KEY is not set"),
    ({"QEOS_URL": "https://qeos.acme.test", "QEOS_API_KEY": "qeos_has space"}, "printable ASCII"),
])
def test_configuration_errors_exit_2(repo, capsys, env, message):
    assert main(["impact"], env) == 2
    assert message in capsys.readouterr().err


def test_a_revoked_key_exits_2(platform, repo):
    platform.reply(401, {"detail": "Invalid API key"})
    assert main(["impact"], env_for(platform)) == 2


def test_an_unknown_format_is_a_usage_error(repo):
    assert main(["impact", "--format", "yaml"], {}) == 2


def test_the_key_never_appears_in_the_output(platform, repo, capsys):
    platform.reply(200, {**SUGGESTION, "tests": [{**SUGGESTION["tests"][1], "name": f"leak {KEY}"}]})
    main(["impact", "--format", "list"], env_for(platform))
    out, err = capsys.readouterr()
    assert KEY not in err  # stderr is scrubbed; stdout is the suggestion itself, as QEOS sent it
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_impact_command.py -q`
Expected: FAIL: `main` exits 2 with `invalid choice: 'impact'`.

- [ ] **Step 3: Rendering and the command.** In `collector/src/qeos_collector/impact.py`:
- extend the imports with `import re` and `import sys`;
- change `from qeos_collector import __version__` to `from qeos_collector import __version__, cucumber`;
- after `MAX_PATHS`, add `FORMATS = ("cucumber", "list", "json")`;
- at the end of the module, add:

```python
def _cell(value) -> str:
    return re.sub(r"[\t\r\n]+", " ", str(value or ""))


def render(data: dict, fmt: str, locate: Callable[[dict], List[str]]) -> str:
    """The suggestion as `--format` says (spec 2026-10-13 §2.1): one entry per line, each line once."""
    tests = list(data.get("tests") or [])
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if fmt == "list":
        lines = ["\t".join(_cell(test.get(key)) for key in ("suite", "class_name", "name")) for test in tests]
    else:
        lines = [line for test in tests
                 for line in (locate(test) or [cucumber.name_filter(str(test.get("name") or ""))])]
    seen: set = set()
    unique = [line for line in lines if not (line in seen or seen.add(line))]
    return "".join(f"{line}\n" for line in unique)


def _print(text: str) -> None:
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:  # a console that cannot show the characters
        sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii"))
    sys.stdout.flush()


def run(args, env: Mapping[str, str], api_key: str, say: Callable[[str], None], cwd: str) -> int:
    """qeos-collector impact: the suggestion on stdout (or --out), messages on stderr, the suggestion's code as the
    exit code (plan Rulings 2, 15)."""
    target = resolve(args, env, api_key, cwd)
    fmt = args.format or ("cucumber" if cucumber.has_feature_files(cwd) else "list")
    found = fetch(target, api_key, env)
    text = ""
    if found.code == SUGGESTED:
        text = render(found.data or {}, fmt, lambda test: cucumber.locate(cwd, test))
        say(f"{len(found.tests)} likely affected test(s) for {len(found.paths)} changed file(s)")
    else:
        say(f"no suggestion: {found.reason}")
    if args.out:
        try:
            # Emptied when there is no suggestion: a later step never reads a stale list
            with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError as exc:
            raise ConfigError(f"cannot write {args.out}: {exc.strerror or exc}") from None
    else:
        _print(text)
    return found.code
```

- [ ] **Step 4: The CLI.** In `collector/src/qeos_collector/cli.py`:
- change `from qeos_collector import __version__, features` to `from qeos_collector import __version__, features, impact`;
- in `build_parser`, before `return parser`, add:

```python
    impact_cmd = commands.add_parser(
        "impact",
        help="print the tests the current change likely affects, from QEOS",
        description="Ask QEOS which tests the change likely affects: the files an upload would send as changed (the "
        "pull- or merge-request base, else the commit's parent). Exit codes: 0 a suggestion was printed, 3 nothing "
        "to suggest, 4 QEOS unreachable or out of time, 2 a configuration error; none of them means tests failed. "
        "The API key is read from QEOS_API_KEY only.",
    )
    impact_cmd.add_argument("--format", choices=impact.FORMATS,
                            help="cucumber: one path/to/x.feature:LINE per line (the default when the working "
                                 "directory has .feature files); list: suite<TAB>class<TAB>name; json: the whole "
                                 "suggestion")
    impact_cmd.add_argument("--out", metavar="FILE",
                            help="write the suggestion to FILE instead of stdout (emptied when there is none)")
    impact_cmd.add_argument("--url", help="platform URL (default: $QEOS_URL)")
    impact_cmd.add_argument("--ca-file", help="trust exactly this CA certificate (default: $QEOS_CA_FILE)")
    impact_cmd.add_argument("--branch", help="default: $QEOS_BRANCH, else detected")
    impact_cmd.add_argument("--commit", help="the commit whose change is scored (default: $QEOS_COMMIT, else detected)")
```

- in `main`, after the `import-features` block, add:

```python
    if args.command == "impact":
        try:
            _usable_key(api_key)
            return impact.run(args, env, api_key, say, os.getcwd())
        except ConfigError as exc:
            say(str(exc))
            return 2
```

- after `main_deprecated`, add:

```python
def _usable_key(api_key: str) -> None:
    """Refused before any request: http.client would otherwise quote the key in an error the scrubbing misses."""
    if api_key and not _API_KEY.match(api_key):
        raise ConfigError("QEOS_API_KEY must be printable ASCII without spaces; check the CI secret")
```

- [ ] **Step 5: Run the tests, then the whole collector suite**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_impact_command.py -q && .venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: The smoke line.** In `scripts/smoke_gateway.sh`, inside the collector block, after:

```bash
  body_has "... with the collector's counts" '"total":3,"passed":1,"failed":1,"skipped":1,"errored":0'
```

insert:

```bash
  # qeos-collector impact (spec 2026-10-13 §2.1): the last commit's changed files, scored through the gateway with
  # the API key. 0 (a suggestion) and 3 (nothing to suggest) both mean QEOS answered; 4 means it was not reached
  impact_rc=0
  (cd collector/src && QEOS_URL="$BASE" QEOS_API_KEY="$API_KEY" "$PY" -m qeos_collector impact --format json \
     --commit "$(git rev-parse HEAD)" --ca-file "$TMP/gateway.crt" --out "$TMP/impact.json") \
     2>"$TMP/impact_cli_err" || impact_rc=$?
  case "$impact_rc" in
    0|3) pass "collector impact scores the last commit through the gateway (exit $impact_rc)" ;;
    *) fail "collector impact exited $impact_rc: $(tail -c 400 "$TMP/impact_cli_err")" ;;
  esac
  if grep -qF -- "$API_KEY" "$TMP/impact_cli_err"; then
    fail "collector impact output contains the API key"
  else
    pass "collector impact output never shows the API key"
  fi
```

- [ ] **Step 7: Docs.** In `collector/README.md`, before "## `.qeos.yml`", add:

~~~markdown
## `qeos-collector impact`

Prints the tests the current change likely affects (test impact analysis, ADR-029), to run them first or to feed
another tool:
- **The change** is the one an upload would send: the pull- or merge-request base, else the commit's parent. The
  checkout needs that history: `fetch-depth: 0` on GitHub pull requests.
- **The scoring:** QEOS scores the change with the project API key (`POST /api/v1/collect/impact`).

```bash
qeos-collector impact                     # Cucumber locations when the repository has .feature files
qeos-collector impact --format list       # suite<TAB>class<TAB>name, one test per line
qeos-collector impact --format json --out impact.json
```

- **`--format cucumber`:**
  - one `path/to/x.feature:LINE` per line, with an outline's rows each on their own line;
  - the lines come from the local `.feature` files (English keywords);
  - a scenario whose line is unknown (a `classpath:` uri, another language) is printed as a name filter,
    `--name "^Pays with card$"`. Characters special to a regular expression or to the shell become `.`.
- **`--format list`:** `suite<TAB>class<TAB>name`.
- **`--format json`:** the whole suggestion, with each test's `kind` and `evidence`.
- **`--out FILE`:** write there instead of stdout. When there is nothing to suggest, the file is emptied, never left
  with an earlier list.
- **`--url`, `--ca-file`, `--branch`, `--commit`:** as for `upload`.

| Exit | Meaning |
|---|---|
| 0 | A suggestion was printed. Below 20 runs of history it holds only labelled tests: failing on this branch, test file changed, no history yet |
| 3 | Nothing to suggest: no change data, or no test is likely affected |
| 4 | QEOS could not be reached, was overloaded (429, 5xx), or ran out of time scoring (503 `impact_timeout`) |
| 2 | A configuration error: no URL or key, TLS trust, an invalid key (401), a QEOS older than this command (404) |

None of them means "tests failed": a pipeline branches on them.
~~~

In "## Exit codes", after the sentence "By default an unreachable platform never turns a build red; a misconfigured collector always does.", add: "`impact` (and `run-impact`) have their own codes, 3 and 4 included: see their sections."

- [ ] **Step 8: Commit, keeping the script's executable bit**

```bash
git add collector/src/qeos_collector/impact.py collector/src/qeos_collector/cli.py collector/tests/test_impact_command.py collector/README.md scripts/smoke_gateway.sh
git update-index --chmod=+x scripts/smoke_gateway.sh
git diff --cached --name-only
```

Expected: exactly those five paths.

```bash
git commit -m "feat(collector): qeos-collector impact prints the likely affected tests (cucumber, list, json; exit 0/3/4)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git ls-files -s scripts/smoke_gateway.sh
```

Expected: `100755`.

### Task 14: Phase 2 gate

**Files:** `TODO.md`, plus fixes only, in the files of Tasks 11–13.

**Interfaces:**
- Consumes: Phase 2.
- Produces: a pushed `master`. There is no tag yet: the collector release is Task 21.

- [ ] **Step 1: TODO.** In `TODO.md`, in the release B entry Task 10 wrote, replace

```markdown
     - Pending: the collector's `impact` and `run-impact`.
```

with

```markdown
     - `qeos-collector impact` done 2026-10-13: cucumber, list and json formats, `--out`, exit codes 0, 3 and 4.
     - Pending: `run-impact`, the integrations, and collector 0.6.0.
```

Commit it: `git add TODO.md && git commit -m "docs(todo): release B, collector impact done" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- TODO.md`

- [ ] **Step 2: The collector suite on the Python versions CI uses**

Run: `cd collector && .venv/Scripts/python -m pytest -q`
Then the same with Python 3.9, if installed:
- `py -3.9 -m venv ../.venv39-collector`;
- `../.venv39-collector/Scripts/python -m pip install -q . pytest cryptography`;
- `../.venv39-collector/Scripts/python -m pytest -q`.

Expected: green. If 3.9 is not installed, say so in the gate notes; CI's matrix runs it.

- [ ] **Step 3: Every other suite, the dashboard, the checks.** Run, in order, as in Task 10:
  - Step 2 (every Python suite, serially);
  - Step 3 (dashboard);
  - Step 4 (docs check, `bash monitoring/check.sh`, the ingestion container smoke);
  - Step 5 (`nginx -t` twice, the stack, `alembic current` = `020 (head)`, `bash scripts/smoke_gateway.sh`).

  Expected: all green, and the smoke ends with `all gateway checks passed`, including `collector impact scores the last commit through the gateway`.

- [ ] **Step 4: Tear down, check, push.** Run Task 10 Step 6 again.
  Expected:
  - `100755`;
  - no stray tracked changes;
  - the log lists the Phase 2 commits;
  - CI on `master` is green.

---

# Phase 3 — `run-impact`, integrations, docs, collector 0.6.0

At the end of this phase:
- `qeos-collector run-impact` runs a Cucumber suite with the likely affected scenarios first, then the rest, and uploads one run;
- the GitHub Action, the Jenkins step and the GitLab/Azure templates offer it;
- the docs and ADR-029 describe it;
- collector 0.6.0 is tagged, and `collector-v0` follows.

### Task 15: Cucumber runner adapters: flavours, arguments, discovery reports, rerun files, the plan

**Files:**
- Modify: `collector/src/qeos_collector/cucumber.py`
- Test: `collector/tests/test_cucumber_runner.py` (new)

**Interfaces:**
- Consumes: `junit.SUITE_LENGTH`, `CLASS_NAME_LENGTH` and `NAME_LENGTH`.
- Produces, in `qeos_collector.cucumber`:
  - `FLAVOURS = ("js", "jvm", "ruby")`, `WORKDIR = ".qeos-impact"`;
  - `Scenario(feature: str, uri: str, name: str, line: int)`, with the properties `location -> str` and `key -> Tuple[str, str, str]`;
  - `detect_flavour(command) -> Optional[str]`;
  - `with_separator(flavour, command) -> List[str]`;
  - `strip_paths(flavour, command, cwd) -> Tuple[List[str], List[str]]`;
  - `dry_run_arguments(flavour) -> List[str]`;
  - `report_arguments(flavour, report: PurePath) -> List[str]`;
  - `rerun_argument(flavour, rerun: PurePath, cwd: str) -> str`;
  - `read_scenarios(path) -> List[Scenario]`, which raises `OSError`/`ValueError`;
  - `rerun_text(scenarios) -> str`;
  - `write_rerun(path, scenarios) -> None`;
  - `split(tests, scenarios) -> Tuple[List[Scenario], List[Scenario], List[dict]]`.

Rulings 7, 8, 9 and 21 apply.

- [ ] **Step 1: Write the failing tests.** Create `collector/tests/test_cucumber_runner.py`:

```python
"""run-impact's Cucumber adapters (spec 2026-10-13 §2.2; plan Rulings 7, 8, 9, 21)."""
import json
from pathlib import PureWindowsPath

import pytest

from qeos_collector import cucumber
from qeos_collector.cucumber import Scenario


@pytest.mark.parametrize("command, flavour", [
    (["npx", "cucumber-js", "--tags", "@smoke"], "js"),
    (["node_modules/.bin/cucumber-js"], "js"),
    (["C:\\proj\\node_modules\\.bin\\cucumber-js.cmd"], "js"),
    (["node", "node_modules/@cucumber/cucumber/bin/cucumber.js"], "js"),
    (["mvn", "-q", "test", "-Dcucumber.filter.tags=@smoke"], "jvm"),
    (["./mvnw", "verify"], "jvm"),
    (["mvnw.cmd", "verify"], "jvm"),
    (["gradle", "test"], "jvm"),
    (["./gradlew", "test"], "jvm"),
    (["cucumber", "--tags", "@smoke"], "ruby"),
    (["bundle", "exec", "cucumber"], "ruby"),
    (["npm", "test"], None),
    (["python", "fake_cucumber.py"], None),
    ([], None),
])
def test_the_flavour_is_detected_from_the_command(command, flavour):
    assert cucumber.detect_flavour(command) == flavour


def test_npm_and_pnpm_get_the_separator_once():
    assert cucumber.with_separator("js", ["npm", "test"]) == ["npm", "test", "--"]
    assert cucumber.with_separator("js", ["pnpm", "run", "bdd", "--", "--tags", "@x"]) == [
        "pnpm", "run", "bdd", "--", "--tags", "@x"]
    assert cucumber.with_separator("js", ["yarn", "bdd"]) == ["yarn", "bdd"]
    assert cucumber.with_separator("jvm", ["mvn", "test"]) == ["mvn", "test"]


def test_visible_feature_paths_are_left_out_of_the_stage_commands(tmp_path):
    (tmp_path / "tests" / "features" / "smoke").mkdir(parents=True)
    (tmp_path / "support").mkdir()
    command = ["npx", "cucumber-js", "tests/features/smoke/", "--tags", "@smoke", "--require", "support",
               "-f", "json:out.json", "--format=progress", "features/a.feature:3:7", "features/**/*.feature",
               "@rerun.txt"]
    kept, removed = cucumber.strip_paths("js", command, str(tmp_path))
    assert kept == ["npx", "cucumber-js", "--tags", "@smoke", "--require", "support", "-f", "json:out.json",
                    "--format=progress"]
    assert removed == ["tests/features/smoke/", "features/a.feature:3:7", "features/**/*.feature", "@rerun.txt"]


def test_ruby_and_jvm_paths_are_left_out_too(tmp_path):
    assert cucumber.strip_paths("ruby", ["bundle", "exec", "cucumber", "features/pay.feature", "--tags", "@x"],
                                str(tmp_path)) == (["bundle", "exec", "cucumber", "--tags", "@x"],
                                                   ["features/pay.feature"])
    assert cucumber.strip_paths("jvm", ["mvn", "test", "-Dcucumber.features=src/test/resources/features"],
                                str(tmp_path)) == (["mvn", "test"], ["-Dcucumber.features=src/test/resources/features"])


def test_a_command_without_a_visible_runner_is_left_as_it_is(tmp_path):
    assert cucumber.strip_paths("js", ["npm", "run", "bdd", "--"], str(tmp_path)) == (["npm", "run", "bdd", "--"], [])


def test_each_flavour_gets_its_own_arguments_with_forward_slashes():
    report = PureWindowsPath(r"C:\work\.qeos-impact\ab12\stage-1.json")
    rerun = PureWindowsPath(r"C:\work\.qeos-impact\ab12\@stage-1.txt")
    assert cucumber.dry_run_arguments("js") == ["--dry-run"]
    assert cucumber.dry_run_arguments("ruby") == ["--dry-run"]
    assert cucumber.dry_run_arguments("jvm") == ["-Dcucumber.execution.dry-run=true"]
    assert cucumber.report_arguments("js", report) == ["--format", "json:C:/work/.qeos-impact/ab12/stage-1.json"]
    assert cucumber.report_arguments("ruby", report) == ["--format", "json", "--out",
                                                         "C:/work/.qeos-impact/ab12/stage-1.json"]
    assert cucumber.report_arguments("jvm", report) == ["-Dcucumber.plugin=json:C:/work/.qeos-impact/ab12/stage-1.json"]
    assert cucumber.rerun_argument("ruby", rerun, "C:/work") == "@C:/work/.qeos-impact/ab12/@stage-1.txt"
    assert cucumber.rerun_argument("jvm", rerun, "C:/work") == "-Dcucumber.features=@C:/work/.qeos-impact/ab12/@stage-1.txt"


def test_cucumber_js_gets_a_relative_rerun_file_named_with_an_at(tmp_path):
    rerun = tmp_path / ".qeos-impact" / "ab12" / "@stage-1.txt"
    assert cucumber.rerun_argument("js", rerun, str(tmp_path)) == ".qeos-impact/ab12/@stage-1.txt"


DRY_RUN = [
    {"uri": "features\\pay.feature", "name": "Pay", "elements": [
        {"type": "background", "name": "", "line": 3, "steps": []},
        {"type": "scenario", "name": "Pays with card", "line": 4, "steps": []},
        {"type": "scenario", "name": "Pays 10", "line": 12, "steps": []},
        {"type": "scenario", "name": "Pays 20", "line": 13, "steps": []},
        {"type": "scenario", "name": "No line", "steps": []}]},
    {"uri": "classpath:features/cart.feature", "name": "Cart", "elements": [
        {"type": "scenario", "name": " Adds ", "line": 3, "steps": []}]},
]


def test_a_dry_run_report_lists_scenarios_and_outline_rows_with_forward_slashes(tmp_path):
    report = tmp_path / "discovery.json"
    report.write_text(json.dumps(DRY_RUN), encoding="utf-8")
    assert cucumber.read_scenarios(report) == [
        Scenario("Pay", "features/pay.feature", "Pays with card", 4),
        Scenario("Pay", "features/pay.feature", "Pays 10", 12),
        Scenario("Pay", "features/pay.feature", "Pays 20", 13),
        Scenario("Cart", "classpath:features/cart.feature", "Adds", 3),
    ]


def test_a_missing_or_broken_report_raises(tmp_path):
    with pytest.raises(OSError):
        cucumber.read_scenarios(tmp_path / "none.json")
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        cucumber.read_scenarios(tmp_path / "bad.json")


def test_rerun_files_group_lines_by_file_and_end_lines_with_lf(tmp_path):
    scenarios = [Scenario("Pay", "features/pay.feature", "Pays 20", 13),
                 Scenario("Cart", "features/cart.feature", "Adds", 3),
                 Scenario("Pay", "features/pay.feature", "Pays with card", 4)]
    assert cucumber.rerun_text(scenarios) == "features/pay.feature:4:13\nfeatures/cart.feature:3\n"
    path = tmp_path / "@stage-1.txt"
    cucumber.write_rerun(path, scenarios)
    assert path.read_bytes() == b"features/pay.feature:4:13\nfeatures/cart.feature:3\n"


def test_the_plan_puts_every_scenario_in_exactly_one_stage():
    scenarios = [Scenario("Pay", "features/pay.feature", "Pays with card", 4),
                 Scenario("Pay", "features/pay.feature", "Pays 10", 12),
                 Scenario("Pay", "features/pay.feature", "Pays 10", 14),
                 Scenario("Cart", "features/cart.feature", "Adds", 3)]
    tests = [{"suite": "Pay", "class_name": "features/pay.feature", "name": "Pays 10"},
             {"suite": "Cart", "class_name": "features/cart.feature", "name": "Gone away"},
             {"suite": "api", "class_name": "PayTest", "name": "refunds"}]
    first, rest, missing = cucumber.split(tests, scenarios)
    assert [s.line for s in first] == [12, 14]  # an outline whose rows share the name: every row
    assert [s.location for s in rest] == ["features/pay.feature:4", "features/cart.feature:3"]
    assert [t["name"] for t in missing] == ["Gone away", "refunds"]
    assert {s.location for s in first} | {s.location for s in rest} == {s.location for s in scenarios}
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_cucumber_runner.py -q`
Expected: FAIL with `AttributeError: module 'qeos_collector.cucumber' has no attribute 'detect_flavour'`.

- [ ] **Step 3: The adapters.** In `collector/src/qeos_collector/cucumber.py`:
- replace the module docstring's last sentence with "run-impact takes its lines from Cucumber's own dry run, and this module holds its Cucumber arguments (plan Rulings 7, 8, 9, 21).";
- change the imports to:

```python
import json
import os
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, List, Optional, Sequence, Tuple

from qeos_collector.junit import CLASS_NAME_LENGTH, NAME_LENGTH, SUITE_LENGTH
```

- append:

```python
# --- run-impact (Phase 3) -------------------------------------------------------------

FLAVOURS = ("js", "jvm", "ruby")
WORKDIR = ".qeos-impact"  # run-impact's files, under the working directory (plan Ruling 16)
# Options that take a value, so their value is never read as a feature path
_JS_VALUE_OPTIONS = frozenset({
    "-c", "--config", "-f", "--format", "--format-options", "--i18n-keywords", "-i", "--import", "-l", "--loader",
    "--language", "--name", "--order", "-p", "--profile", "--parallel", "--plugin", "--plugin-options", "-r",
    "--require", "--require-module", "--retry", "--retry-tag-filter", "--shard", "-t", "--tags", "--world-parameters",
})
_RUBY_VALUE_OPTIONS = frozenset({
    "-r", "--require", "-f", "--format", "-o", "--out", "-t", "--tags", "-n", "--name", "-p", "--profile", "-e",
    "--exclude", "-l", "--lines", "--i18n", "--order", "--retry", "--snippet-type", "--language",
})


@dataclass(frozen=True)
class Scenario:
    """A scenario, or an outline row, as a Cucumber dry run reports it."""

    feature: str  # the feature's name: a result's suite
    uri: str      # "/"-separated: a result's class_name
    name: str
    line: int

    @property
    def location(self) -> str:
        return f"{self.uri}:{self.line}"

    @property
    def key(self) -> Tuple[str, str, str]:
        """(suite, class_name, name) as an upload stores them (formats._row cuts them the same way)."""
        return self.feature[:SUITE_LENGTH], self.uri[:CLASS_NAME_LENGTH], self.name[:NAME_LENGTH]


def _program(token: str) -> str:
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".cmd", ".exe", ".bat", ".ps1"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_cucumber_js(token: str) -> bool:
    return _program(token) == "cucumber-js" or "@cucumber/cucumber" in token.replace("\\", "/")


def detect_flavour(command: Sequence[str]) -> Optional[str]:
    """js, jvm or ruby from the command; None when it does not show (`npm test`, a script): --cucumber then says."""
    if any(_is_cucumber_js(token) for token in command):
        return "js"
    names = [_program(token) for token in command]
    first = names[0] if names else ""
    if first in ("mvn", "mvnw", "gradle", "gradlew"):
        return "jvm"
    if first == "cucumber" or (first == "bundle" and "cucumber" in names):
        return "ruby"
    return None


def with_separator(flavour: str, command: Sequence[str]) -> List[str]:
    """npm and pnpm hand arguments to the script only after "--"."""
    if flavour == "js" and command and _program(command[0]) in ("npm", "pnpm") and "--" not in command[1:]:
        return [*command, "--"]
    return list(command)


def _runner_index(flavour: str, command: Sequence[str]) -> Optional[int]:
    for index, token in enumerate(command):
        if (flavour == "js" and _is_cucumber_js(token)) or (flavour == "ruby" and _program(token) == "cucumber"):
            return index
    return None


def _names_features(arg: str, cwd: str) -> bool:
    plain = re.sub(r"(:\d+)+$", "", arg)
    return (plain.endswith(".feature") or any(c in plain for c in "*?[") or os.path.basename(plain).startswith("@")
            or os.path.isdir(os.path.join(cwd, plain)))


def strip_paths(flavour: str, command: Sequence[str], cwd: str) -> Tuple[List[str], List[str]]:
    """(the command without the feature paths it names, those paths). Such paths would add scenarios to every stage
    (cucumber-js adds them to the rerun file's). Only what the command shows: paths inside an npm script or a profile
    stay, and run-impact's stage-1 check catches them (plan Ruling 8)."""
    if flavour == "jvm":
        removed = [arg for arg in command if arg.startswith("-Dcucumber.features=")]
        return [arg for arg in command if arg not in removed], removed
    start = _runner_index(flavour, command)
    if start is None:
        return list(command), []
    values = _JS_VALUE_OPTIONS if flavour == "js" else _RUBY_VALUE_OPTIONS
    kept, removed, takes_value = list(command[: start + 1]), [], False
    for arg in command[start + 1:]:
        if takes_value:
            kept.append(arg)
            takes_value = False
        elif arg.startswith("-"):
            kept.append(arg)
            takes_value = arg in values  # "--tags @x"; "--tags=@x" carries its own value
        elif _names_features(arg, cwd):
            removed.append(arg)
        else:
            kept.append(arg)
    return kept, removed


def dry_run_arguments(flavour: str) -> List[str]:
    return ["-Dcucumber.execution.dry-run=true"] if flavour == "jvm" else ["--dry-run"]


def report_arguments(flavour: str, report: PurePath) -> List[str]:
    """A Cucumber JSON report at `report`, written with "/" whatever the runner's OS (plan Ruling 21)."""
    target = report.as_posix()
    if flavour == "js":
        return ["--format", f"json:{target}"]
    if flavour == "ruby":
        return ["--format", "json", "--out", target]
    return [f"-Dcucumber.plugin=json:{target}"]


def rerun_argument(flavour: str, rerun: PurePath, cwd: str) -> str:
    if flavour == "js":
        # cucumber-js 12 reads an argument as a rerun file only when its file name starts with "@", and joins the
        # argument to the working directory: a relative path (verified on 12.6.0)
        return PurePath(os.path.relpath(str(rerun), cwd)).as_posix()
    if flavour == "ruby":
        return "@" + rerun.as_posix()
    return "-Dcucumber.features=@" + rerun.as_posix()


def read_scenarios(path) -> List[Scenario]:
    """The scenarios of a Cucumber JSON report (a dry run's), in report order; a background is not one. Raises OSError
    or ValueError when there is no readable report."""
    with open(path, "rb") as handle:
        data = json.load(handle)
    scenarios: List[Scenario] = []
    for feature in data if isinstance(data, list) else []:
        if not isinstance(feature, dict):
            continue
        uri = str(feature.get("uri") or "").replace("\\", "/")  # Windows runners report "features\\x.feature"
        for element in feature.get("elements") or []:
            if not isinstance(element, dict) or element.get("type") == "background":
                continue
            name, line = str(element.get("name") or "").strip(), element.get("line")
            if name and isinstance(line, int) and not isinstance(line, bool) and line > 0:
                scenarios.append(Scenario(str(feature.get("name") or ""), uri, name, line))
    return scenarios


def rerun_text(scenarios: Sequence[Scenario]) -> str:
    """One `uri:line[:line…]` entry per feature file, in first-seen order: the format cucumber-js, cucumber-jvm and
    Ruby Cucumber all read."""
    lines: Dict[str, List[int]] = {}
    for scenario in scenarios:
        lines.setdefault(scenario.uri, []).append(scenario.line)
    return "".join(f"{uri}:{':'.join(str(n) for n in sorted(set(found)))}\n" for uri, found in lines.items())


def write_rerun(path, scenarios: Sequence[Scenario]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(rerun_text(scenarios))


def _test_key(test: dict) -> Tuple[str, str, str]:
    return str(test.get("suite") or ""), str(test.get("class_name") or ""), str(test.get("name") or "")


def split(tests: Sequence[dict], scenarios: Sequence[Scenario]) -> Tuple[List[Scenario], List[Scenario], List[dict]]:
    """(stage 1, stage 2, suggested tests not among the scenarios). Every scenario lands in exactly one stage, in
    report order. A suggested test matches by (suite, class_name, name), so the rows of an outline that share its
    name go with it."""
    wanted = {_test_key(test) for test in tests}
    first = [s for s in scenarios if s.key in wanted]
    rest = [s for s in scenarios if s.key not in wanted]
    found = {s.key for s in first}
    return first, rest, [test for test in tests if _test_key(test) not in found]
```

- [ ] **Step 4: Run the tests**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_cucumber_runner.py tests/test_cucumber_locate.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add collector/src/qeos_collector/cucumber.py collector/tests/test_cucumber_runner.py
git commit -m "feat(collector): Cucumber adapters for run-impact (flavours, dry-run and rerun arguments, the stage plan)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- collector/src/qeos_collector/cucumber.py collector/tests/test_cucumber_runner.py
```

### Task 16: `run-impact`: discovery, the stage-1 check, two stages, one upload

**Files:**
- Create: `collector/src/qeos_collector/run_impact.py`
- Create: `collector/tests/fake_cucumber.py`, `collector/tests/fixtures/fake-cucumber-spec.json`
- Modify: `collector/src/qeos_collector/payload.py` (`SCOPES`, `build_run(scope=, stages=)`)
- Modify: `collector/src/qeos_collector/cli.py`:
  - `_run_options`, `_flags`, `_verdict`, `_upload_reports`;
  - `_upload(reports=, scope=, stages=)`;
  - the `run-impact` subcommand.
- Modify: `collector/README.md`
- Test: `collector/tests/test_run_impact.py` (new), `collector/tests/test_payload.py`

**Interfaces:**
- Consumes:
  - `impact.resolve`, `fetch`, `SUGGESTED` and `NOTHING` (Task 12);
  - the Task 15 adapters;
  - `formats.parse_file`;
  - `cli._upload` and `_gate`.
- Produces:
  - `run_impact.Stage(name, returncode, duration_s, report)`, with the properties `tests` and `failed`;
  - `run_impact.run_command(argv) -> int`;
  - `first_failure_after(stages) -> Optional[float]`;
  - `stages_payload(stages, stopped_after_stage=None) -> dict`;
  - `run_impact.run(args, env, api_key, say, cwd, *, upload, judge, gate, fail_on_error, clock, runner=run_command) -> int`;
  - `payload.build_run(..., scope=None, stages=None)`;
  - `cli._upload(..., reports=None, scope=None, stages=None)`;
  - the CLI `qeos-collector run-impact [upload options] [--cucumber js|jvm|ruby] -- COMMAND`.

  Task 17 adds `--fail-fast`, `--suggested-only` and `--no-fallback` to the parser's handling; the flags are declared here.

Rulings 6, 7, 8, 9, 12, 13, 16 and 21 apply.

- [ ] **Step 1: The stand-in Cucumber.** Create `collector/tests/fixtures/fake-cucumber-spec.json`:

```json
{"features": [
  {"uri": "features/pay.feature", "name": "Pay", "scenarios": [
    {"name": "Pays with card", "line": 4, "tags": ["@smoke"], "status": "passed", "seconds": 2},
    {"name": "Pays 10", "line": 12, "status": "failed", "seconds": 3},
    {"name": "Pays 20", "line": 13, "status": "passed", "seconds": 1}]},
  {"uri": "features/cart.feature", "name": "Cart", "scenarios": [
    {"name": "Adds", "line": 3, "tags": ["@smoke"], "status": "passed", "seconds": 1},
    {"name": "Removes", "line": 7, "status": "passed", "seconds": 1}]}
]}
```

Create `collector/tests/fake_cucumber.py`:

```python
"""A stand-in for Cucumber in run-impact's tests and in CI's collector-action job.

It reads a scenario catalogue from FAKE_CUCUMBER_SPEC and understands the arguments run-impact adds for each flavour
(plan Ruling 7). It writes a Cucumber JSON report and exits 1 when a scenario it ran failed. When FAKE_CUCUMBER_LOG is
set, it appends one JSON line per invocation: {"argv", "dry_run", "ran", "rerun"}.

Two more variables:
- FAKE_CUCUMBER_EXTRA names a feature uri it always adds to a rerun selection, as a profile's `paths` would;
- FAKE_CUCUMBER_WINDOWS=1 reports uris with backslashes, as a Windows runner does."""
import json
import os
import sys


def read_rerun(path):
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    wanted = set()
    for entry in text.split("\n"):
        entry = entry.strip()
        if entry:
            uri, *lines = entry.split(":")
            wanted.update((uri, int(line)) for line in lines)
    return text, wanted


def main(argv):
    with open(os.environ["FAKE_CUCUMBER_SPEC"], encoding="utf-8") as handle:
        spec = json.load(handle)
    dry_run, report, rerun, wanted, tags = False, None, None, None, []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--dry-run", "-Dcucumber.execution.dry-run=true"):
            dry_run = True
        elif arg == "--format" and i + 1 < len(argv):
            i += 1
            if argv[i].startswith("json:"):
                report = argv[i][len("json:"):]
        elif arg == "--out" and i + 1 < len(argv):
            i += 1
            report = argv[i]
        elif arg.startswith("-Dcucumber.plugin=json:"):
            report = arg[len("-Dcucumber.plugin=json:"):]
        elif arg.startswith("-Dcucumber.features=@"):
            rerun, wanted = read_rerun(arg[len("-Dcucumber.features=@"):])
        elif arg in ("--tags", "-t") and i + 1 < len(argv):
            i += 1
            tags.append(argv[i])
        elif arg.startswith("@"):  # Ruby: @path
            rerun, wanted = read_rerun(arg[1:])
        elif os.path.basename(arg).startswith("@"):  # cucumber-js 12: a relative path to a file named @...
            rerun, wanted = read_rerun(os.path.join(os.getcwd(), arg))
        i += 1
    extra = os.environ.get("FAKE_CUCUMBER_EXTRA")
    windows = os.environ.get("FAKE_CUCUMBER_WINDOWS") == "1"
    ran, features, failed = [], [], False
    for feature in spec["features"]:
        elements = []
        for scenario in feature["scenarios"]:
            if any(tag not in scenario.get("tags", []) for tag in tags):
                continue
            if wanted is not None and (feature["uri"], scenario["line"]) not in wanted and feature["uri"] != extra:
                continue
            status = "skipped" if dry_run else scenario.get("status", "passed")
            failed = failed or status == "failed"
            elements.append({"type": "scenario", "keyword": "Scenario", "name": scenario["name"],
                             "line": scenario["line"],
                             "steps": [{"keyword": "Given ", "name": "a step",
                                        "result": {"status": status,
                                                   "duration": int(scenario.get("seconds", 1) * 1e9)}}]})
            ran.append(f"{feature['uri']}:{scenario['line']}")
        if elements:
            uri = feature["uri"].replace("/", "\\") if windows else feature["uri"]
            features.append({"uri": uri, "name": feature["name"], "keyword": "Feature", "elements": elements})
    if report:
        with open(report, "w", encoding="utf-8") as handle:
            json.dump(features, handle)
    log = os.environ.get("FAKE_CUCUMBER_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "dry_run": dry_run, "ran": ran, "rerun": rerun}) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 2: Write the failing tests.** Append to `collector/tests/test_payload.py`:

```python
def test_scope_and_stages_are_sent_only_when_given():
    from datetime import datetime, timezone

    from qeos_collector.payload import build_run

    moment = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)
    base = {"ci_provider": "local", "started_at": moment, "finished_at": moment}
    plain = build_run(**base)
    assert "scope" not in plain and "stages" not in plain  # an ordinary upload hashes as before (plan Ruling 5)
    stages = {"stages": [{"name": "all", "duration_s": 1.0, "tests": 1, "failed": 0}], "time_to_first_failure_s": None}
    run = build_run(**base, scope="impact-subset", stages=stages)
    assert (run["scope"], run["stages"]) == ("impact-subset", stages)
    assert "scope" not in build_run(**base, scope="partial")
```

Create `collector/tests/test_run_impact.py`:

```python
"""qeos-collector run-impact against a stand-in Cucumber (tests/fake_cucumber.py) and a fake platform (spec 2026-10-13
§2.2; plan Rulings 6-13, 16, 21)."""
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from qeos_collector import cli, impact, run_impact
from qeos_collector.cli import main
from qeos_collector.upload import ConfigError

KEY = "qeos_run_impact_secret"
FAKE = str(Path(__file__).with_name("fake_cucumber.py"))
SPEC = Path(__file__).with_name("fixtures") / "fake-cucumber-spec.json"
CHANGES = {"base_ref": "origin/main", "truncated": False,
           "files": [{"path": "src/pay/api.py", "status": "M", "additions": 3, "deletions": 1}]}
RECEIPT = {"id": 77, "project_id": 1, "total": 5, "passed": 4, "failed": 1, "skipped": 0, "errored": 0,
           "quarantined": 0, "blocking": 1, "created_at": "2026-10-13T10:00:00Z"}
PAYS_WITH_CARD = ("Pay", "features/pay.feature", "Pays with card")
PAYS_10 = ("Pay", "features/pay.feature", "Pays 10")
PAYS_20 = ("Pay", "features/pay.feature", "Pays 20")
ADDS = ("Cart", "features/cart.feature", "Adds")
REMOVES = ("Cart", "features/cart.feature", "Removes")
GONE = ("Cart", "features/cart.feature", "Gone away")


def suggested(*tests):
    return {"state": "ok", "model_version": "stats-v1", "history_runs": 34, "needed_runs": 20,
            "statistical_total": len(tests),
            "tests": [{"test_key": f"{i:064d}", "suite": suite, "class_name": uri, "name": name, "kind": "statistical",
                       "evidence": {"path_unit": "src/pay/", "changed_runs": 6, "new_failures": 4, "confidence": 0.67,
                                    "lift": 22.2, "base_rate": 0.03}}
                      for i, (suite, uri, name) in enumerate(tests)]}


@pytest.fixture
def cucumber(tmp_path, monkeypatch):
    """The stand-in's catalogue and log, the working directory, and the change; returns its invocations."""
    log = tmp_path / "cucumber.log"
    monkeypatch.setenv("FAKE_CUCUMBER_SPEC", str(SPEC))
    monkeypatch.setenv("FAKE_CUCUMBER_LOG", str(log))
    monkeypatch.delenv("FAKE_CUCUMBER_EXTRA", raising=False)
    monkeypatch.delenv("FAKE_CUCUMBER_WINDOWS", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(impact, "collect_changes", lambda env, commit: CHANGES)
    monkeypatch.setattr(cli, "collect_changes", lambda env, commit: CHANGES)

    def invocations():
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    return invocations


def env_for(platform, **extra):
    return {"QEOS_URL": platform.url, "QEOS_API_KEY": KEY, **extra}


def run(argv, env):
    ticks = itertools.count(0, 60)  # each clock reading is 60 s after the last: each stage takes 60 s
    return main(argv, env, sleep=lambda seconds: None, clock=lambda: next(ticks))


def command(*options):
    return ["run-impact", "--cucumber", "js", *options, "--", sys.executable, FAKE]


def uploads(platform):
    return [json.loads(r["body"]) for r in platform.requests if r["path"] == "/api/v1/collect/runs"]


def test_the_suggested_scenarios_run_first_then_the_rest_and_none_twice(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_10, GONE))
    platform.reply(201, RECEIPT)
    assert run(command(), env_for(platform)) == 1  # stage 1's failure is the test command's exit code
    calls = cucumber()
    assert [c["dry_run"] for c in calls] == [True, True, False, False]  # discovery, the stage-1 check, two stages
    first, second = calls[2]["ran"], calls[3]["ran"]
    assert first == ["features/pay.feature:12"]
    assert sorted(second) == ["features/cart.feature:3", "features/cart.feature:7", "features/pay.feature:13",
                              "features/pay.feature:4"]
    assert sorted(first + second) == sorted(calls[0]["ran"])  # every discovered scenario, once
    assert calls[2]["rerun"] == "features/pay.feature:12\n"
    [body] = uploads(platform)  # one combined upload
    assert len(body["results"]) == 5
    assert body["run"]["scope"] == "full"
    stages = body["run"]["stages"]
    assert [(s["name"], s["tests"], s["failed"], s["duration_s"]) for s in stages["stages"]] == [
        ("suggested", 1, 1, 60.0), ("rest", 4, 0, 60.0)]
    assert stages["time_to_first_failure_s"] == 3.0
    assert "stopped_after_stage" not in stages
    err = capsys.readouterr().err
    assert "skipped by the filter: 1 suggested test(s) are not among this command's scenarios" in err
    assert "Gone away" in err


def test_discovery_honours_the_commands_tags(platform, cucumber):
    platform.reply(200, suggested(ADDS, PAYS_10))
    platform.reply(201, RECEIPT)
    assert run([*command(), "--tags", "@smoke"], env_for(platform)) == 0
    calls = cucumber()
    assert sorted(calls[0]["ran"]) == ["features/cart.feature:3", "features/pay.feature:4"]
    assert calls[2]["ran"] == ["features/cart.feature:3"]
    assert calls[3]["ran"] == ["features/pay.feature:4"]
    assert all("--tags" in c["argv"] for c in calls)


def test_an_outline_row_is_its_own_line(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    calls = cucumber()
    assert calls[2]["rerun"] == "features/pay.feature:13\n"
    assert calls[2]["ran"] == ["features/pay.feature:13"]
    assert "features/pay.feature:12" in calls[3]["ran"]


def test_a_command_that_adds_its_own_paths_is_refused_before_any_test_runs(platform, cucumber, monkeypatch, capsys):
    """Review Focus 3: a profile's `paths` would add scenarios to stage 1, which would then run them twice."""
    monkeypatch.setenv("FAKE_CUCUMBER_EXTRA", "features/cart.feature")
    platform.reply(200, suggested(PAYS_10))
    assert run(command(), env_for(platform)) == 2
    assert all(c["dry_run"] for c in cucumber())  # nothing ran for real
    assert uploads(platform) == []
    assert "cannot narrow this command" in capsys.readouterr().err


def test_every_scenario_suggested_runs_one_stage_and_no_empty_rerun_file(platform, cucumber):
    """Review Focus 4: stage 2 would have an empty rerun file, which some runners read as everything."""
    platform.reply(200, suggested(PAYS_WITH_CARD, PAYS_10, PAYS_20, ADDS, REMOVES))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    assert [c["dry_run"] for c in cucumber()] == [True, True, False]
    [body] = uploads(platform)
    assert body["run"]["scope"] == "full"
    assert [s["name"] for s in body["run"]["stages"]["stages"]] == ["suggested"]


def test_no_suggested_scenario_runs_the_command_as_one_stage(platform, cucumber):
    """Review Focus 4: stage 1 would have an empty rerun file."""
    platform.reply(200, suggested(GONE))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    calls = cucumber()
    assert [c["dry_run"] for c in calls] == [True, False]
    assert calls[1]["rerun"] is None and len(calls[1]["ran"]) == 5
    [body] = uploads(platform)
    assert body["run"]["scope"] == "full"
    assert [s["name"] for s in body["run"]["stages"]["stages"]] == ["all"]


def test_a_windows_runners_backslashes_become_forward_slashes(platform, cucumber, monkeypatch):
    monkeypatch.setenv("FAKE_CUCUMBER_WINDOWS", "1")
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    calls = cucumber()
    assert calls[2]["rerun"] == "features/pay.feature:12\n" and calls[2]["ran"] == ["features/pay.feature:12"]
    assert {r["class_name"] for r in uploads(platform)[0]["results"]} == {"features/pay.feature",
                                                                          "features/cart.feature"}


def test_the_command_may_come_without_the_separator(platform, cucumber):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    assert run(["run-impact", "--cucumber", "js", sys.executable, FAKE], env_for(platform)) == 1
    assert len(cucumber()) == 4


def test_no_command_is_a_usage_error(platform, cucumber, capsys):
    assert run(["run-impact", "--cucumber", "js"], env_for(platform)) == 2
    assert "give the test command after --" in capsys.readouterr().err


def test_an_undetectable_cucumber_needs_the_option(platform, cucumber, capsys):
    assert run(["run-impact", "--", sys.executable, FAKE], env_for(platform)) == 2
    assert "pass --cucumber js, jvm or ruby" in capsys.readouterr().err


def test_a_dry_run_that_writes_no_report_is_explained(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_10))
    assert run(["run-impact", "--cucumber", "js", "--", sys.executable, "-c", "pass"], env_for(platform)) == 2
    assert "wrote no JSON report" in capsys.readouterr().err


def test_the_working_files_are_removed(platform, cucumber, tmp_path):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    assert not (tmp_path / ".qeos-impact").exists()


def test_the_program_is_looked_up_as_a_shell_would(monkeypatch):
    """A Windows runner's npx is npx.cmd: found through PATHEXT by shutil.which (plan Ruling 21)."""
    seen = []
    monkeypatch.setattr(run_impact.shutil, "which", lambda name: "C:/tools/npx.cmd" if name == "npx" else None)
    monkeypatch.setattr(run_impact.subprocess, "run",
                        lambda argv, check: seen.append(argv) or subprocess.CompletedProcess(argv, 1))
    assert run_impact.run_command(["npx", "cucumber-js", "--dry-run"]) == 1
    assert seen == [["C:/tools/npx.cmd", "cucumber-js", "--dry-run"]]


def test_a_missing_program_is_a_configuration_error():
    with pytest.raises(ConfigError, match="cannot run no-such-cucumber-xyz"):
        run_impact.run_command(["no-such-cucumber-xyz"])
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_run_impact.py tests/test_payload.py -q`
Expected: FAIL. `run_impact` cannot be imported, `run-impact` is an invalid choice, and `build_run` takes no `scope`.

- [ ] **Step 4: The payload.** In `collector/src/qeos_collector/payload.py`:
- after `TRIGGERS = ...`, add `SCOPES = ("full", "impact-subset")  # run-impact (spec 2026-10-13 §3.1)`;
- add the parameters `scope: Optional[str] = None, stages: Optional[dict] = None,` to `build_run` after `trigger`;
- before `return run`, add:

```python
    # Only run-impact sends them, so an ordinary upload's body and request hash stay as they were
    if scope in SCOPES:
        run["scope"] = scope
    if stages:
        run["stages"] = stages
```

- [ ] **Step 5: The module.** Create `collector/src/qeos_collector/run_impact.py`:

```python
"""qeos-collector run-impact: the scenarios a change likely affects first, then the rest, uploaded as one run (spec
2026-10-13 §2.2; plan Rulings 6-13, 16, 21).

1. QEOS scores the change (impact.fetch: the upload's changed files, POST /api/v1/collect/impact).
2. Discovery: the test command as given, as a Cucumber dry run with a JSON report: the scenarios it would run.
3. The plan:
   - the suggested scenarios among them go in stage 1's rerun file, every other one in stage 2's, so none runs twice;
   - feature paths the command shows are left out of the stage commands;
   - a dry run of stage 1 checks that its rerun file alone decides what runs. A profile's `paths`, an npm script or
     `--shard` would not let it; then nothing runs.
4. The stages' JSON reports are uploaded as one run, with its scope and stages."""
from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from qeos_collector import cucumber, impact
from qeos_collector.formats import parse_file
from qeos_collector.junit import ParsedFile
from qeos_collector.upload import ConfigError

FULL, SUBSET = "full", "impact-subset"
FAILING = ("failed", "errored")
SHOWN_MISSING = 5

# (stage reports, scope, stages) -> the last receipt, or None when nothing was stored
Upload = Callable[[List[ParsedFile], str, dict], Optional[dict]]


@dataclass
class Stage:
    name: str  # "suggested", "rest" or "all"
    returncode: int
    duration_s: float
    report: ParsedFile

    @property
    def tests(self) -> int:
        return len(self.report.results)

    @property
    def failed(self) -> int:
        return sum(1 for row in self.report.results if row["status"] in FAILING)


def run_command(argv: Sequence[str]) -> int:
    """The command's exit code. The program is looked up with shutil.which, so a Windows runner finds npx.cmd or
    mvn.cmd through PATHEXT, which a bare CreateProcess does not (plan Ruling 21)."""
    program = shutil.which(argv[0]) or argv[0]
    try:
        return subprocess.run([program, *argv[1:]], check=False).returncode
    except OSError as exc:
        raise ConfigError(f"cannot run {argv[0]}: {exc.strerror or exc}") from None


def first_failure_after(stages: Sequence[Stage]) -> Optional[float]:
    """Seconds from the start of stage 1 to the end of the first failing scenario: the earlier stages' wall time, plus
    the failing stage's scenarios in report order (plan Ruling 6). With parallel workers, an upper bound."""
    offset = 0.0
    for stage in stages:
        elapsed = 0.0
        for row in stage.report.results:
            elapsed += row["duration_ms"] / 1000
            if row["status"] in FAILING:
                return round(offset + elapsed, 3)
        offset += stage.duration_s
    return None


def stages_payload(stages: Sequence[Stage], stopped_after_stage: Optional[int] = None) -> dict:
    payload = {
        "stages": [{"name": s.name, "duration_s": round(s.duration_s, 3), "tests": s.tests, "failed": s.failed}
                   for s in stages],
        "time_to_first_failure_s": first_failure_after(stages),
    }
    if stopped_after_stage is not None:
        payload["stopped_after_stage"] = stopped_after_stage
    return payload


class _Cucumber:
    """The dry runs and stages of one invocation, their files in one working directory."""

    def __init__(self, flavour: str, workdir: Path, cwd: str, runner: Callable[[Sequence[str]], int],
                 clock: Callable[[], float], say: Callable[[str], None]):
        self.flavour, self.workdir, self.cwd = flavour, workdir, cwd
        self.runner, self.clock, self.say = runner, clock, say

    def _rerun(self, label: str, scenarios: Sequence[cucumber.Scenario]) -> str:
        path = self.workdir / f"@{label}.txt"
        cucumber.write_rerun(path, scenarios)
        return cucumber.rerun_argument(self.flavour, path, self.cwd)

    def dry_run(self, command: Sequence[str], label: str,
                plan: Optional[Sequence[cucumber.Scenario]] = None) -> List[cucumber.Scenario]:
        report = self.workdir / f"{label}.json"
        extra = list(cucumber.dry_run_arguments(self.flavour))
        if plan is not None:
            extra.append(self._rerun(label, plan))
        extra += cucumber.report_arguments(self.flavour, report)
        code = self.runner([*command, *extra])
        try:
            return cucumber.read_scenarios(report)
        except (OSError, ValueError):
            raise ConfigError(f"the Cucumber dry run ({label}) wrote no JSON report ({command[0]} exited {code}); "
                              f"is --cucumber {self.flavour} right for this command?") from None

    def stage(self, number: int, name: str, command: Sequence[str],
              scenarios: Optional[Sequence[cucumber.Scenario]] = None) -> Stage:
        report = self.workdir / f"stage-{number}.json"
        extra = [] if scenarios is None else [self._rerun(f"stage-{number}", scenarios)]
        extra += cucumber.report_arguments(self.flavour, report)
        self.say(f"stage {number} ({name}): "
                 + ("the command as given" if scenarios is None else f"{len(scenarios)} scenario(s)"))
        started = self.clock()
        code = self.runner([*command, *extra])
        return Stage(name, code, max(0.0, self.clock() - started), parse_file(str(report)))


def _command(args) -> List[str]:
    command = list(args.test_command or [])
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise ConfigError("give the test command after --, e.g. qeos-collector run-impact -- npx cucumber-js")
    return command


def _check_selection(steps: _Cucumber, command: Sequence[str], plan: Sequence[cucumber.Scenario]) -> None:
    """Stage 1's command, as a dry run, must select exactly the plan (plan Ruling 8); otherwise scenarios would run
    twice, or not at all. Nothing has run yet when this refuses."""
    selected = {s.location for s in steps.dry_run(command, "stage-1-check", plan)}
    planned = {s.location for s in plan}
    if selected == planned:
        return
    extra, left_out = sorted(selected - planned), sorted(planned - selected)
    problems = []
    if extra:
        problems.append(f"run {len(extra)} scenario(s) it did not plan (e.g. {extra[0]})")
    if left_out:
        problems.append(f"leave out {len(left_out)} it planned (e.g. {left_out[0]})")
    raise ConfigError(
        "run-impact cannot narrow this command: with the rerun file, stage 1 would " + " and ".join(problems)
        + ". Feature paths in a Cucumber profile or config (`paths`), inside an npm script, or a --shard option change "
          "what runs; select features with tags instead, or call Cucumber directly. Nothing was run.")


def _without_suggestion(args, say: Callable[[str], None], command: Sequence[str], steps: _Cucumber) -> List[Stage]:
    """Nothing to run first: the full suite as one stage, or nothing at all with --suggested-only --no-fallback."""
    if args.suggested_only and args.no_fallback:
        say("nothing run (--no-fallback)")
        return []
    say("running the full suite instead (--suggested-only falls back to it)" if args.suggested_only
        else "running the full suite as one stage")
    return [steps.stage(1, "all", command)]


def _run_stages(args, say, command, flavour, cwd, found: impact.Suggestion,
                steps: _Cucumber) -> Tuple[List[Stage], str, Optional[int], List[dict]]:
    """(stages, scope, stopped_after_stage, suggested tests not discovered); no stages when nothing may run."""
    if found.code != impact.SUGGESTED:
        say(f"no suggestion: {found.reason}")
        return _without_suggestion(args, say, command, steps), FULL, None, []
    discovered = steps.dry_run(command, "discovery")
    first, rest, missing = cucumber.split(found.tests, discovered)
    say(f"{len(discovered)} scenario(s) in this command, {len(first)} of them suggested")
    if missing:
        names = ", ".join(str(test.get("name")) for test in missing[:SHOWN_MISSING])
        more = f" and {len(missing) - SHOWN_MISSING} more" if len(missing) > SHOWN_MISSING else ""
        say(f"skipped by the filter: {len(missing)} suggested test(s) are not among this command's scenarios "
            f"(left out by its filters, or not Cucumber): {names}{more}")
    if not first:
        say("no suggested scenario is among them")
        return _without_suggestion(args, say, command, steps), FULL, None, missing
    narrowed, removed = cucumber.strip_paths(flavour, command, cwd)
    if removed:
        say(f"the stages leave out the command's own feature paths ({' '.join(removed)}): the rerun files choose")
    _check_selection(steps, narrowed, first)
    stages = [steps.stage(1, "suggested", narrowed, first)]
    if rest:
        stages.append(steps.stage(2, "rest", narrowed, rest))
    return stages, FULL, None, missing


def _finish(say, stages: List[Stage], scope: str, stopped: Optional[int], *, upload: Upload,
            judge: Callable[[dict], int], gate: bool, fail_on_error: bool) -> int:
    """Upload the stages as one run, then the exit code (plan Ruling 12)."""
    payload = stages_payload(stages, stopped)
    receipt = upload([stage.report for stage in stages], scope, payload)
    tests = next((stage.returncode for stage in stages if stage.returncode != 0), 0)
    if gate:
        if receipt is None:
            say("gate failed: the gate cannot pass without an upload")
            return 1
        return judge(receipt)
    if receipt is None and fail_on_error and tests == 0:
        return 1
    return tests


def run(args, env: Mapping[str, str], api_key: str, say: Callable[[str], None], cwd: str, *, upload: Upload,
        judge: Callable[[dict], int], gate: bool, fail_on_error: bool, clock: Callable[[], float],
        runner: Callable[[Sequence[str]], int] = run_command) -> int:
    command = _command(args)
    flavour = args.cucumber or cucumber.detect_flavour(command)
    if flavour is None:
        raise ConfigError(f"cannot tell which Cucumber `{' '.join(command)}` runs; pass --cucumber js, jvm or ruby")
    if args.no_fallback and not args.suggested_only:
        raise ConfigError("--no-fallback only goes with --suggested-only")
    command = cucumber.with_separator(flavour, command)
    target = impact.resolve(args, env, api_key, cwd)
    base = Path(cwd, cucumber.WORKDIR)
    workdir = base / uuid.uuid4().hex[:12]
    try:
        workdir.mkdir(parents=True)
    except OSError as exc:
        raise ConfigError(f"cannot create {workdir}: {exc.strerror or exc}") from None
    try:
        steps = _Cucumber(flavour, workdir, cwd, runner, clock, say)
        found = impact.fetch(target, api_key, env)
        stages, scope, stopped, _missing = _run_stages(args, say, command, flavour, cwd, found, steps)
        if not stages:  # --suggested-only --no-fallback: nothing ran, nothing to upload
            return found.code if found.code != impact.SUGGESTED else impact.NOTHING
        return _finish(say, stages, scope, stopped, upload=upload, judge=judge, gate=gate,
                       fail_on_error=fail_on_error)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        try:
            base.rmdir()  # only when empty: another invocation's files stay
        except OSError:
            pass
```

- [ ] **Step 6: The CLI.** In `collector/src/qeos_collector/cli.py`:
- change the package import to `from qeos_collector import __version__, cucumber, features, impact, run_impact`.
- In `build_parser`, move the upload options that `run-impact` shares into a helper, and declare `run-impact`. Replace the block from `upload.add_argument("--url", ...)` through `upload.add_argument("--dry-run", ...)` with:

```python
    _run_options(upload)
    upload.add_argument("--no-changes", action="store_true",
                        help="skip git code-change collection (default: $QEOS_NO_CHANGES)")
    upload.add_argument("--dry-run", action="store_true", help="print the JSON that would be sent; upload nothing")
```

- define `_run_options` above `build_parser`, holding the moved lines unchanged except that `--no-changes` and `--dry-run` stay with `upload`:

```python
def _run_options(parser: argparse.ArgumentParser) -> None:
    """What every uploading command takes: where to send the run, and what to say about it."""
    parser.add_argument("--url", help="platform URL (default: $QEOS_URL)")
    parser.add_argument("--ci-provider", choices=CI_PROVIDERS, help="default: $QEOS_CI_PROVIDER, else detected")
    parser.add_argument("--trigger", help="manual, automatic or qeos (default: $QEOS_TRIGGER, else detected; ADR-030)")
    parser.add_argument("--branch", help="default: $QEOS_BRANCH, else detected")
    parser.add_argument("--commit", help="full or short SHA (default: $QEOS_COMMIT, else detected)")
    parser.add_argument("--ci-run-url", help="default: $QEOS_CI_RUN_URL, else detected")
    parser.add_argument("--environment", help="e.g. staging (default: $QEOS_ENVIRONMENT)")
    parser.add_argument("--idempotency-key", help="default: $QEOS_IDEMPOTENCY_KEY, else derived from the CI job")
    parser.add_argument("--ca-file", help="trust exactly this CA certificate, e.g. a private or self-signed one "
                                          "(default: $QEOS_CA_FILE)")
    parser.add_argument("--component", action="append", default=[], metavar="NAME@SHA",
                        help="a repo/version this run exercised, e.g. product-api@3f2a9c1; repeatable "
                             "(default: $QEOS_COMPONENTS, comma separated)")
    parser.add_argument("--fail-on-error", action="store_true",
                        help="exit 1 if the upload fails (default: $QEOS_FAIL_ON_ERROR)")
    parser.add_argument("--gate", action="store_true",
                        help="exit 1 when the run has failures outside quarantine, or when it could not be "
                             "uploaded (default: $QEOS_GATE)")
    parser.add_argument("--client-cert", help="client certificate for mTLS (default: $QEOS_CLIENT_CERT)")
    parser.add_argument("--client-key", help="private key for --client-cert (default: $QEOS_CLIENT_KEY)")
    parser.add_argument("--spool", metavar="DIR",
                        help="keep parts a failed upload could not deliver in DIR and resend them on "
                             "the next invocation (default: $QEOS_SPOOL)")
```

- in `build_parser`, before `return parser`, add:

```python
    run_impact_cmd = commands.add_parser(
        "run-impact",
        help="run a Cucumber command with the likely affected scenarios first, then the rest, and upload one run",
        description="Ask QEOS which tests the change likely affects, run those scenarios first and every other one "
        "after, and upload both as one run. Cucumber only: cucumber-js, cucumber-jvm through Maven or Gradle, or Ruby "
        "Cucumber. Put the test command after --. The API key is read from QEOS_API_KEY only.",
    )
    _run_options(run_impact_cmd)
    run_impact_cmd.add_argument("--cucumber", choices=cucumber.FLAVOURS,
                                help="which Cucumber the command runs (default: detected from the command)")
    run_impact_cmd.add_argument("--fail-fast", action="store_true",
                                help="stop after stage 1 when a suggested scenario fails; the run is uploaded as "
                                     "suggested tests only")
    run_impact_cmd.add_argument("--suggested-only", action="store_true",
                                help="run only the suggested scenarios (the full suite when there is no suggestion)")
    run_impact_cmd.add_argument("--no-fallback", action="store_true",
                                help="with --suggested-only: when there is no suggestion, run nothing and exit 3 or 4")
    run_impact_cmd.add_argument("test_command", nargs=argparse.REMAINDER, metavar="-- COMMAND",
                                help="the Cucumber test command, after --")
    run_impact_cmd.set_defaults(patterns=[], no_changes=False, dry_run=False)
```

- in `main`, replace:

```python
    fail_on_error = args.fail_on_error or env.get("QEOS_FAIL_ON_ERROR", "").strip().lower() in _TRUE
    gate = args.gate or env.get("QEOS_GATE", "").strip().lower() in _TRUE
    if not (fail_on_error and gate):
        try:
            file_config = load_config(os.getcwd())
            fail_on_error = fail_on_error or file_config.get("fail-on-error") is True
            gate = gate or file_config.get("gate") is True
        except ConfigError:
            pass  # _upload reads the file itself and reports the problem properly
```

with:

```python
    fail_on_error, gate = _flags(args, env)
    if args.command == "run-impact":
        try:
            _usable_key(api_key)
            return run_impact.run(
                args, env, api_key, say, os.getcwd(), gate=gate, fail_on_error=fail_on_error, clock=clock,
                upload=lambda reports, scope, stages: _upload_reports(
                    args, env, api_key, say, reports, scope, stages, now=now, sleep=sleep, clock=clock),
                judge=lambda receipt: _verdict(receipt, say),
            )
        except ConfigError as exc:
            say(str(exc))
            return 2
```

- further down in `main`, replace:

```python
        if receipt.get("discarded"):  # not collected: the platform has no verdict to give
            if not gate:
                return 0
            say("gate: decided on local results (run not collected)")
            return _gate({"blocking": receipt["failed"] + receipt["errored"]}, say)
        return _gate(receipt, say) if gate else 0
```

with:

```python
        return _verdict(receipt, say) if gate else 0
```

- after `_gate`, add:

```python
def _flags(args, env: Mapping[str, str]) -> "tuple[bool, bool]":
    """(--fail-on-error, --gate): a flag, then the environment, then .qeos.yml."""
    fail_on_error = args.fail_on_error or env.get("QEOS_FAIL_ON_ERROR", "").strip().lower() in _TRUE
    gate = args.gate or env.get("QEOS_GATE", "").strip().lower() in _TRUE
    if not (fail_on_error and gate):
        try:
            file_config = load_config(os.getcwd())
            fail_on_error = fail_on_error or file_config.get("fail-on-error") is True
            gate = gate or file_config.get("gate") is True
        except ConfigError:
            pass  # _upload reads the file itself and reports the problem properly
    return fail_on_error, gate


def _verdict(receipt: dict, say: _Output) -> int:
    """The gate on a receipt. A run the platform did not collect has no verdict there: its local counts decide."""
    if receipt.get("discarded"):
        say("gate: decided on local results (run not collected)")
        return _gate({"blocking": receipt["failed"] + receipt["errored"]}, say)
    return _gate(receipt, say)


def _upload_reports(args, env, api_key, say, reports, scope, stages, *, now, sleep, clock) -> Optional[dict]:
    """run-impact's upload of its stage reports as one run: the last receipt, or None when nothing was stored (what
    went wrong is already said). A configuration error still raises."""
    try:
        receipt = _upload(args, env, api_key, say, now=now, sleep=sleep, clock=clock, reports=reports, scope=scope,
                          stages=stages)
    except _UploadFailed:
        return None
    except ConfigError:
        raise
    except Exception as exc:  # a bug in the collector must not hide the tests' own result
        say(f"unexpected error: {type(exc).__name__}: {exc}")
        return None
    return receipt if isinstance(receipt, dict) else None
```

- change `_upload`'s signature to `def _upload(args, env, api_key, say, *, now, sleep, clock, reports=None, scope=None, stages=None) -> "int | dict":`, and replace:

```python
    patterns = args.patterns or list(file_config.get("patterns") or [])
    if not patterns:
        raise ConfigError("no report patterns given (arguments, or patterns: in .qeos.yml)")
    files = _expand(patterns)
    if not files:
        raise ConfigError(f"no file matched {' '.join(patterns)}")
    parsed = [parse_file(path) for path in files]
```

with:

```python
    if reports is not None:  # run-impact's stage reports
        parsed = list(reports)
    else:
        patterns = args.patterns or list(file_config.get("patterns") or [])
        if not patterns:
            raise ConfigError("no report patterns given (arguments, or patterns: in .qeos.yml)")
        files = _expand(patterns)
        if not files:
            raise ConfigError(f"no file matched {' '.join(patterns)}")
        parsed = [parse_file(path) for path in files]
```

- in its `build_run(...)` call, after `trigger=trigger,`, add `scope=scope, stages=stages,`.

- [ ] **Step 7: Run the tests, then the whole collector suite**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_run_impact.py tests/test_payload.py -q && .venv/Scripts/python -m pytest -q`
Expected: PASS, with `test_cli.py` unchanged and green: `upload` keeps its options and its gate.

- [ ] **Step 8: Docs.** In `collector/README.md`, after the `impact` section (Task 13), add:

~~~markdown
## `qeos-collector run-impact` (Cucumber)

Runs a Cucumber test command with the scenarios the change likely affects **first**, and every other scenario after.
Both are uploaded as one run (`scope` `full`, with its `stages`), so failures in the changed area show up in minutes
and the full suite still runs.

```bash
qeos-collector run-impact -- npx cucumber-js --tags "not @wip"
qeos-collector run-impact -- mvn -q test -Dcucumber.filter.tags="not @wip"
qeos-collector run-impact --cucumber js -- npm test
```

1. QEOS scores the change, as `impact` does.
2. **Discovery:** the command runs as a Cucumber dry run with a JSON report, with your own tags, profiles and
   paths, to list the scenarios it would run.
3. **Stage 1:** the suggested scenarios among them, through a rerun file.
4. **Stage 2:** every other one, through a second rerun file. No scenario runs twice. Suggested tests that the
   command does not run (left out by its filters, or not Cucumber) are listed as skipped by the filter.
5. Both stages' JSON reports are uploaded as one run.

| `--cucumber` | Detected from | What run-impact appends |
|---|---|---|
| `js` (cucumber-js) | `cucumber-js` or `@cucumber/cucumber` in the command | `--dry-run`, `--format json:FILE`, and a rerun file `.qeos-impact/…/@stage-1.txt`: a relative path to a file whose name starts with `@`, as cucumber-js 12 requires |
| `jvm` (Maven, Gradle) | `mvn`, `mvnw`, `gradle` or `gradlew` first | `-Dcucumber.execution.dry-run=true`, `-Dcucumber.plugin=json:FILE`, `-Dcucumber.features=@FILE` |
| `ruby` | `cucumber` or `bundle exec cucumber` first | `--dry-run`, `--format json --out FILE`, `@FILE` |

- **`--cucumber`:** pass it when the command hides the runner (`npm test`, a script). For `npm` and `pnpm`,
  run-impact adds the `--` the script needs.
- **Gradle:** it hands `-D` properties to its own JVM, not the test JVM. Forward them in `build.gradle`:
  `test { systemProperties System.properties.findAll { it.key.startsWith("cucumber.") } }`.

**Feature paths.** Paths the command names (`npx cucumber-js features/checkout/`, `-Dcucumber.features=…`) are left
out of the stages: the rerun files choose the scenarios.

Paths run-impact cannot see would add scenarios to every stage, because cucumber-js adds a profile's `paths` to the
rerun file's. Such paths come from:
- an npm script;
- a profile or config file with `paths`;
- `--shard`.

So before any test runs, a dry run of stage 1 must select exactly the planned scenarios. Otherwise run-impact runs
nothing and exits 2, saying why. Select features with tags instead.

**Working files** live in `.qeos-impact/` and are removed at the end. The upload options are those of `upload`
(`--url`, `--environment`, `--component`, `--spool`, …).

**The exit code** is the test command's, from the first failing stage, so the build fails when tests fail.
~~~

- [ ] **Step 9: Commit**

```bash
git add collector/src/qeos_collector/run_impact.py collector/src/qeos_collector/payload.py collector/src/qeos_collector/cli.py collector/tests/fake_cucumber.py collector/tests/fixtures/fake-cucumber-spec.json collector/tests/test_run_impact.py collector/tests/test_payload.py collector/README.md
git commit -m "feat(collector): run-impact runs the suggested Cucumber scenarios first, then the rest, as one run" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- collector/src/qeos_collector/run_impact.py collector/src/qeos_collector/payload.py collector/src/qeos_collector/cli.py collector/tests/fake_cucumber.py collector/tests/fixtures/fake-cucumber-spec.json collector/tests/test_run_impact.py collector/tests/test_payload.py collector/README.md
```

### Task 17: `--fail-fast`, `--suggested-only` with its fallback, `--no-fallback`, `--gate`

**Files:**
- Modify: `collector/src/qeos_collector/run_impact.py` (`_run_stages`)
- Modify: `collector/README.md`
- Test: `collector/tests/test_run_impact.py`

**Interfaces:**
- Consumes: Task 16.
- Produces: the modes of spec §2.2:
  - with `--suggested-only` or a `--fail-fast` stop: scope `impact-subset`, and `stopped_after_stage: 1` after a stop;
  - the fallback to the full suite (scope `full`, one stage `all`);
  - exit 3 or 4 with `--no-fallback`.

Rulings 9–12 apply. The fallback and `--no-fallback` paths already live in `_without_suggestion` (Task 16); this task adds the two stage-1 exits and pins every mode with tests.

- [ ] **Step 1: Write the failing tests.** Append to `collector/tests/test_run_impact.py`:

```python
def test_fail_fast_stops_after_a_failing_stage_1_and_uploads_a_subset(platform, cucumber):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    assert run(command("--fail-fast"), env_for(platform)) == 1
    assert [c["dry_run"] for c in cucumber()] == [True, True, False]  # stage 2 never started
    [body] = uploads(platform)
    assert body["run"]["scope"] == "impact-subset"
    assert body["run"]["stages"]["stopped_after_stage"] == 1
    assert len(body["results"]) == 1


def test_fail_fast_with_a_passing_stage_1_runs_the_rest(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(201, RECEIPT)
    assert run(command("--fail-fast"), env_for(platform)) == 1  # Pays 10 fails in stage 2
    assert len(cucumber()) == 4
    assert uploads(platform)[0]["run"]["scope"] == "full"


def test_suggested_only_runs_stage_1_as_a_subset(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(201, RECEIPT)
    assert run(command("--suggested-only"), env_for(platform)) == 0
    assert [c["dry_run"] for c in cucumber()] == [True, True, False]
    run_ = uploads(platform)[0]["run"]
    assert run_["scope"] == "impact-subset"
    assert "stopped_after_stage" not in run_["stages"]


@pytest.mark.parametrize("status, answer", [
    (200, suggested()),                                                 # nothing to suggest (3)
    (503, {"detail": {"code": "impact_timeout", "message": "slow"}}),  # QEOS out of time (4)
])
def test_suggested_only_falls_back_to_the_full_suite(platform, cucumber, capsys, status, answer):
    platform.reply(status, answer)
    platform.reply(201, RECEIPT)
    assert run(command("--suggested-only"), env_for(platform)) == 1  # the full suite's Pays 10 fails
    calls = cucumber()
    assert [c["dry_run"] for c in calls] == [False] and len(calls[0]["ran"]) == 5
    assert uploads(platform)[0]["run"]["scope"] == "full"
    assert "running the full suite instead (--suggested-only falls back to it)" in capsys.readouterr().err


@pytest.mark.parametrize("status, answer, code", [(200, suggested(), 3), (503, {"detail": "busy"}, 4)])
def test_no_fallback_runs_nothing_and_exits_3_or_4(platform, cucumber, status, answer, code):
    platform.reply(status, answer)
    assert run(command("--suggested-only", "--no-fallback"), env_for(platform)) == code
    assert cucumber() == [] and uploads(platform) == []


def test_no_fallback_when_no_suggested_scenario_is_discovered_exits_3(platform, cucumber):
    platform.reply(200, suggested(GONE))
    assert run(command("--suggested-only", "--no-fallback"), env_for(platform)) == 3
    assert [c["dry_run"] for c in cucumber()] == [True] and uploads(platform) == []


def test_no_fallback_without_suggested_only_is_a_usage_error(platform, cucumber, capsys):
    assert run(command("--no-fallback"), env_for(platform)) == 2
    assert "--no-fallback only goes with --suggested-only" in capsys.readouterr().err


def test_the_gate_judges_the_uploaded_run(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, {**RECEIPT, "quarantined": 1, "blocking": 0})
    assert run(command("--gate"), env_for(platform)) == 0  # the only failure is quarantined
    assert "gate passed: 1 failure(s) in quarantine, not counted" in capsys.readouterr().err


def test_the_gate_fails_on_failures_outside_quarantine(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(201, {**RECEIPT, "blocking": 1})
    assert run(command("--gate"), env_for(platform)) == 1


def test_the_gate_fails_closed_without_an_upload(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(command("--gate", "--suggested-only"), env_for(platform)) == 1
    assert "gate cannot pass without an upload" in capsys.readouterr().err


def test_without_the_gate_a_failed_upload_keeps_the_tests_exit_code(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(command("--suggested-only"), env_for(platform)) == 0  # Pays 20 passed


def test_fail_on_error_fails_a_passing_run_whose_upload_failed(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(command("--suggested-only", "--fail-on-error"), env_for(platform)) == 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_run_impact.py -q`
Expected:
- FAIL: `test_fail_fast_stops_after_a_failing_stage_1_and_uploads_a_subset` (stage 2 still runs; scope `full`);
- FAIL: `test_suggested_only_runs_stage_1_as_a_subset`;
- FAIL: `test_without_the_gate_a_failed_upload_keeps_the_tests_exit_code` (stage 2's failure makes the exit code 1);
- PASS already: the fallback, `--no-fallback` and gate tests. Their code is Task 16's `_without_suggestion` and `_finish`.

- [ ] **Step 3: The two stage-1 exits.** In `run_impact._run_stages`, replace:

```python
    stages = [steps.stage(1, "suggested", narrowed, first)]
    if rest:
        stages.append(steps.stage(2, "rest", narrowed, rest))
    return stages, FULL, None, missing
```

with:

```python
    stages = [steps.stage(1, "suggested", narrowed, first)]
    if args.suggested_only:
        return stages, SUBSET, None, missing
    if args.fail_fast and stages[0].failed:  # a failed or errored scenario, not just a nonzero exit (plan Ruling 11)
        say("stage 1 failed: stopping before stage 2 (--fail-fast)")
        return stages, SUBSET, 1, missing
    if rest:  # every scenario suggested: one stage, still the full suite (plan Ruling 9)
        stages.append(steps.stage(2, "rest", narrowed, rest))
    return stages, FULL, None, missing
```

- [ ] **Step 4: Run the tests**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_run_impact.py -q`
Expected: PASS.

- [ ] **Step 5: Docs.** In `collector/README.md`, in the `run-impact` section, before "**Working files**", add:

```markdown
**Modes.**
- **`--fail-fast`:** when a suggested scenario fails, stop after stage 1. The run is uploaded as suggested tests
  only, stopped after stage 1.
- **`--suggested-only`:** run stage 1 only. The run is uploaded as suggested tests only, and it never counts in the
  impact statistics or the accuracy figure. When there is no suggestion (nothing suggested, not enough history, QEOS
  out of reach), the full suite runs instead and the log says why.
- **`--no-fallback`** (with `--suggested-only`): in that case run nothing, upload nothing, and exit 3 or 4 as
  `impact` would.
- **`--gate`:** judges the uploaded run, as for `upload`. It exits 1 on failures outside quarantine, and 1 when
  nothing could be uploaded.

| Exit | When |
|---|---|
| The test command's | Without `--gate`: the first failing stage's exit code, else 0 |
| 0 / 1 | With `--gate`: the gate's verdict on the uploaded run |
| 1 | `--fail-on-error`, the tests passed and the upload failed |
| 2 | Configuration: no command, an unknown Cucumber (pass `--cucumber`), a command run-impact cannot narrow, a dry run without a JSON report, no URL or key |
| 3 / 4 | `--suggested-only --no-fallback` with nothing to run: as `impact` |
```

- [ ] **Step 6: Commit**

```bash
git add collector/src/qeos_collector/run_impact.py collector/tests/test_run_impact.py collector/README.md
git commit -m "feat(collector): run-impact --fail-fast and --suggested-only (with fallback and --no-fallback), gated on the uploaded run" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- collector/src/qeos_collector/run_impact.py collector/tests/test_run_impact.py collector/README.md
```

### Task 18: The CI summary (GitHub step summary, or the log)

**Files:**
- Create: `collector/src/qeos_collector/summary.py`
- Modify: `collector/src/qeos_collector/run_impact.py` (`_finish` publishes the summary)
- Modify: `collector/README.md`
- Test: `collector/tests/test_summary.py` (new), `collector/tests/test_run_impact.py`

**Interfaces:**
- Consumes: `Stage` (anything with `name`, `tests`, `failed` and `duration_s`), `stages_payload` (Task 16), the suggested tests and the missing ones.
- Produces, in `qeos_collector.summary`:
  - `STAGES`, `LABELS`;
  - `duration(seconds) -> str`, `cell(value) -> str`, `why(test, *, markdown=False) -> str`;
  - `outcome(stages, payload, scope) -> str`;
  - `text(...) -> List[str]`, `markdown(...) -> str`;
  - `publish(env, say, tests, missing, stages, payload, scope) -> None`.

Ruling 20 applies.

- [ ] **Step 1: Write the failing tests.** Create `collector/tests/test_summary.py`:

```python
"""run-impact's summary (spec 2026-10-13 §2.2; plan Ruling 20)."""
from types import SimpleNamespace

import pytest

from qeos_collector import summary

STAT = {"name": "Pays | 10", "kind": "statistical",
        "evidence": {"path_unit": "src/pay/", "changed_runs": 6, "new_failures": 4}}
LABEL = {"name": "refunds\nlater", "kind": "failing_on_branch", "evidence": None}


def stage(name, tests, failed, seconds):
    return SimpleNamespace(name=name, tests=tests, failed=failed, duration_s=seconds)


@pytest.mark.parametrize("seconds, text", [(0.4, "400 ms"), (3.0, "3.0 s"), (42.5, "42.5 s"), (60, "1m 00s"),
                                           (65, "1m 05s"), (915, "15m 15s")])
def test_durations_read_as_the_dashboard_says_them(seconds, text):
    assert summary.duration(seconds) == text


def test_cells_escape_pipes_and_line_breaks():
    assert summary.cell("a|b\r\nc") == "a\\|b c"


def test_why_names_the_evidence_or_the_label():
    assert summary.why(STAT) == "newly failed in 4 of 6 runs that changed src/pay/"
    assert summary.why(STAT, markdown=True) == "newly failed in 4 of 6 runs that changed `src/pay/`"
    assert summary.why(LABEL) == "failing on this branch"


def test_the_markdown_has_the_stages_the_first_failure_and_the_suggested_tests():
    md = summary.markdown([STAT, LABEL], [{"name": "Gone"}],
                          [stage("suggested", 1, 1, 60), stage("rest", 4, 0, 60)],
                          {"time_to_first_failure_s": 3.0}, "full")
    assert "### QEOS: suggested tests first" in md
    assert "| 1 | suggested tests | 1 | 1 | 1m 00s |" in md
    assert "| 2 | the rest | 4 | 0 | 1m 00s |" in md
    assert "First failure after 3.0 s (full suite 2m 00s)." in md
    assert "| Pays \\| 10 | newly failed in 4 of 6 runs that changed `src/pay/` |" in md
    assert "| refunds later | failing on this branch |" in md
    assert "Not among this command's scenarios (left out by its filters, or not Cucumber): Gone." in md


def test_a_subset_says_suggested_tests_only():
    lines = summary.text([STAT], [], [stage("suggested", 1, 1, 60)],
                         {"time_to_first_failure_s": 3.0, "stopped_after_stage": 1}, "impact-subset")
    assert lines[:2] == ["stage 1 (suggested tests): 1 scenario(s), 1 failed, 1m 00s",
                         "suggested tests only, stopped after stage 1: first failure after 3.0 s"]


def test_a_run_without_failures_says_so():
    assert summary.outcome([stage("all", 5, 0, 60)], {"time_to_first_failure_s": None}, "full") == "no failures"
```

Append to `collector/tests/test_run_impact.py`:

```python
def test_github_actions_gets_a_step_summary_table(platform, cucumber, tmp_path, capsys):
    step_summary = tmp_path / "step-summary.md"
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform, GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(step_summary)))
    text = step_summary.read_text(encoding="utf-8")
    assert "| 1 | suggested tests | 1 | 1 | 1m 00s |" in text
    assert "| 2 | the rest | 4 | 0 | 1m 00s |" in text
    assert "First failure after 3.0 s (full suite 2m 00s)." in text
    assert "| Pays 10 | newly failed in 4 of 6 runs that changed `src/pay/` |" in text
    assert "qeos: summary written to the job's step summary" in capsys.readouterr().err


def test_elsewhere_the_summary_is_in_the_log(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    err = capsys.readouterr().err
    assert "qeos: stage 1 (suggested tests): 1 scenario(s), 1 failed, 1m 00s" in err
    assert "qeos: first failure after 3.0 s (full suite 2m 00s)" in err
    assert "qeos:   Pays 10: newly failed in 4 of 6 runs that changed src/pay/" in err


def test_an_unwritable_step_summary_falls_back_to_the_log(platform, cucumber, tmp_path, capsys):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform, GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(tmp_path)))  # a directory
    err = capsys.readouterr().err
    assert "cannot write the step summary" in err
    assert "qeos: first failure after 3.0 s (full suite 2m 00s)" in err
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_summary.py tests/test_run_impact.py -q`
Expected: FAIL. `qeos_collector.summary` does not exist, and no summary is written.

- [ ] **Step 3: The summary.** Create `collector/src/qeos_collector/summary.py`:

```python
"""run-impact's summary (spec 2026-10-13 §2.2, plan Ruling 20): the suggested tests with their evidence, each stage's
size, failures and duration, and the time to the first failure. A table in the GitHub Actions job's step summary;
anywhere else, the same as lines in the log."""
from __future__ import annotations

import re
from typing import Callable, List, Mapping, Sequence

STAGES = {"suggested": "suggested tests", "rest": "the rest", "all": "full suite"}
LABELS = {"test_file_changed": "test file changed", "failing_on_branch": "failing on this branch",
          "no_history": "no history yet"}
SHOWN = 50


def duration(seconds: float) -> str:
    """As the dashboard says it (formatDuration): 400 ms, 42.5 s, 1m 05s."""
    ms = round(seconds * 1000)
    if ms < 1000:
        return f"{ms} ms"
    if seconds < 60:
        return f"{ms / 1000:.1f} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes}m {rest:02d}s"


def cell(value) -> str:
    """Text for a Markdown table cell: pipes escaped, line breaks as one space."""
    return re.sub(r"\s*[\r\n]+\s*", " ", str(value or "")).replace("|", "\\|")


def why(test: dict, *, markdown: bool = False) -> str:
    evidence = test.get("evidence")
    if test.get("kind") == "statistical" and isinstance(evidence, dict):
        unit = str(evidence.get("path_unit") or "")
        return (f"newly failed in {evidence.get('new_failures')} of {evidence.get('changed_runs')} runs that changed "
                + (f"`{unit}`" if markdown else unit))
    return LABELS.get(str(test.get("kind")), str(test.get("kind") or ""))


def outcome(stages: Sequence, payload: dict, scope: str) -> str:
    first = payload.get("time_to_first_failure_s")
    if scope == "impact-subset":
        head = "suggested tests only" + (", stopped after stage 1" if payload.get("stopped_after_stage") == 1 else "")
        return f"{head}: " + ("no failures" if first is None else f"first failure after {duration(first)}")
    if first is None:
        return "no failures"
    return f"first failure after {duration(first)} (full suite {duration(sum(s.duration_s for s in stages))})"


def text(tests: Sequence[dict], missing: Sequence[dict], stages: Sequence, payload: dict, scope: str) -> List[str]:
    lines = [f"stage {i} ({STAGES.get(s.name, s.name)}): {s.tests} scenario(s), {s.failed} failed, "
             f"{duration(s.duration_s)}" for i, s in enumerate(stages, start=1)]
    lines.append(outcome(stages, payload, scope))
    lines += [f"  {test.get('name')}: {why(test)}" for test in tests[:SHOWN]]
    if len(tests) > SHOWN:
        lines.append(f"  … and {len(tests) - SHOWN} more")
    return lines


def markdown(tests: Sequence[dict], missing: Sequence[dict], stages: Sequence, payload: dict, scope: str) -> str:
    said = outcome(stages, payload, scope)
    lines = ["### QEOS: suggested tests first", "", "| Stage | What | Scenarios | Failed | Duration |",
             "|---:|---|---:|---:|---:|"]
    lines += [f"| {i} | {STAGES.get(s.name, s.name)} | {s.tests} | {s.failed} | {duration(s.duration_s)} |"
              for i, s in enumerate(stages, start=1)]
    lines += ["", said[0].upper() + said[1:] + "."]
    if tests:
        lines += ["", f"<details><summary>Suggested tests ({len(tests)})</summary>", "", "| Test | Why |", "|---|---|"]
        lines += [f"| {cell(test.get('name'))} | {cell(why(test, markdown=True))} |" for test in tests[:SHOWN]]
        if len(tests) > SHOWN:
            lines.append(f"| … and {len(tests) - SHOWN} more | |")
        lines += ["", "</details>"]
    if missing:
        lines += ["", "Not among this command's scenarios (left out by its filters, or not Cucumber): "
                  + ", ".join(cell(test.get("name")) for test in missing[:SHOWN]) + "."]
    return "\n".join(lines) + "\n\n"


def publish(env: Mapping[str, str], say: Callable[[str], None], tests: Sequence[dict], missing: Sequence[dict],
            stages: Sequence, payload: dict, scope: str) -> None:
    path = env.get("GITHUB_STEP_SUMMARY", "").strip() if env.get("GITHUB_ACTIONS") == "true" else ""
    if path:
        try:
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(markdown(tests, missing, stages, payload, scope))
            say("summary written to the job's step summary")
            return
        except OSError as exc:
            say(f"cannot write the step summary ({exc.strerror or exc}); here it is")
    for line in text(tests, missing, stages, payload, scope):
        say(line)
```

- [ ] **Step 4: Publish it.** In `collector/src/qeos_collector/run_impact.py`:
- import `summary`: `from qeos_collector import cucumber, impact, summary`;
- change `_finish` to take the environment and the suggestion, and publish before the upload:

```python
def _finish(env: Mapping[str, str], say, found: impact.Suggestion, missing: List[dict], stages: List[Stage],
            scope: str, stopped: Optional[int], *, upload: Upload, judge: Callable[[dict], int], gate: bool,
            fail_on_error: bool) -> int:
    """Publish the summary, upload the stages as one run, then the exit code (plan Rulings 12, 20)."""
    payload = stages_payload(stages, stopped)
    summary.publish(env, say, found.tests, missing, stages, payload, scope)
    receipt = upload([stage.report for stage in stages], scope, payload)
    tests = next((stage.returncode for stage in stages if stage.returncode != 0), 0)
    if gate:
        if receipt is None:
            say("gate failed: the gate cannot pass without an upload")
            return 1
        return judge(receipt)
    if receipt is None and fail_on_error and tests == 0:
        return 1
    return tests
```

- in `run`, replace:

```python
        stages, scope, stopped, _missing = _run_stages(args, say, command, flavour, cwd, found, steps)
        if not stages:  # --suggested-only --no-fallback: nothing ran, nothing to upload
            return found.code if found.code != impact.SUGGESTED else impact.NOTHING
        return _finish(say, stages, scope, stopped, upload=upload, judge=judge, gate=gate,
                       fail_on_error=fail_on_error)
```

  with:

```python
        stages, scope, stopped, missing = _run_stages(args, say, command, flavour, cwd, found, steps)
        if not stages:  # --suggested-only --no-fallback: nothing ran, nothing to upload
            return found.code if found.code != impact.SUGGESTED else impact.NOTHING
        return _finish(env, say, found, missing, stages, scope, stopped, upload=upload, judge=judge, gate=gate,
                       fail_on_error=fail_on_error)
```

- [ ] **Step 5: Run the tests, then the whole collector suite**

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_summary.py tests/test_run_impact.py -q && .venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Docs.** In `collector/README.md`, in the `run-impact` section, before "**Working files**", add:

```markdown
**Summary.**
- **What it holds:** the suggested tests with their evidence, each stage's scenarios, failures and duration, and the
  time to the first failure ("first failure after 1m 02s (full suite 16m 15s)").
- **In GitHub Actions:** a table in the job's step summary (`$GITHUB_STEP_SUMMARY`).
- **Anywhere else:** the same lines in the log.
```

- [ ] **Step 7: Commit**

```bash
git add collector/src/qeos_collector/summary.py collector/src/qeos_collector/run_impact.py collector/tests/test_summary.py collector/tests/test_run_impact.py collector/README.md
git commit -m "feat(collector): run-impact summary in the GitHub step summary, or the log elsewhere" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- collector/src/qeos_collector/summary.py collector/src/qeos_collector/run_impact.py collector/tests/test_summary.py collector/tests/test_run_impact.py collector/README.md
```

### Task 19: Integrations: the GitHub Action, the Jenkins step, the GitLab and Azure examples

**Files:**
- Modify: `collector-action/action.yml`
- Modify: `.github/workflows/ci.yml` (the `collector-action` job)
- Create: `collector/tests/fixtures/fake-cucumber-green.json`
- Modify: `collector-jenkins/vars/qeosCollectorUpload.groovy`, `collector-jenkins/README.md`
- Modify: `templates/qeos-collector.gitlab-ci.yml`, `templates/qeos-collector.azure-pipelines.yml`

**Interfaces:**
- Consumes: `qeos-collector run-impact` (Tasks 16–18).
- Produces:
  - the action inputs `impact: first | only | off` (default `off`) and `test-command`, with `patterns` now optional;
  - the Jenkins options `impact: 'first' | 'only' | 'off'` and `testCommand`;
  - commented examples in the GitLab and Azure templates;
  - CI exercises `impact: first` on every push.

`qeos-run.mjs` is not changed (spec §4). Ruling 22 applies.

- [ ] **Step 1: The action.** Replace `collector-action/action.yml` with:

```yaml
name: QEOS collector
description: >-
  Upload test reports as one run to a QEOS platform, or run a Cucumber test
  command with the tests a change likely affects first (impact: first or only).
  Provide the project API key as the QEOS_API_KEY environment variable on the
  step - never as an input, so it stays out of the action log.
  QAV_API_KEY, the name before the QEOS rename, still works with a deprecation warning.

inputs:
  url:
    description: Platform URL (e.g. https://qeos.example.com)
    required: true
  patterns:
    description: >-
      Report glob patterns, space separated (** matches directories), uploaded when
      impact is off. Default: the patterns list in .qeos.yml
    required: false
    default: ""
  environment:
    description: Environment label stored on the run (e.g. staging)
    required: false
    default: ""
  extra-args:
    description: Extra qeos-collector flags (e.g. --fail-on-error --no-changes, or --cucumber js with impact)
    required: false
    default: ""
  impact:
    description: >-
      off (default): upload the reports in patterns. first: run test-command with the
      likely affected scenarios first, then the rest, and upload both as one run. only:
      run only the likely affected scenarios (the full suite when there is no
      suggestion). Cucumber only; collector 0.6.0 or later.
    required: false
    default: "off"
  test-command:
    description: The Cucumber command to run with impact first or only, e.g. npx cucumber-js --tags "not @wip"
    required: false
    default: ""

runs:
  using: composite
  steps:
    - name: Install qeos-collector (pinned to this action's ref)
      shell: bash
      # From the action's own checkout: GitHub downloads the whole repository at the ref the
      # workflow names, so ../collector is that same version. GITHUB_ACTION_REPOSITORY and
      # GITHUB_ACTION_REF are not reliable here (empty when the action runs inside a reusable
      # workflow), which made the old git+https install fail with "empty revision".
      run: python -m pip install --quiet "$GITHUB_ACTION_PATH/../collector"
    - name: Upload test results
      if: inputs.impact == 'off'
      shell: bash
      run: |
        qeos-collector upload ${{ inputs.patterns }} \
          --url "${{ inputs.url }}" \
          ${{ inputs.environment && format('--environment "{0}"', inputs.environment) || '' }} \
          ${{ inputs.extra-args }}
    - name: Run the tests, the likely affected ones first
      if: inputs.impact != 'off'
      shell: bash
      env:
        QEOS_IMPACT_MODE: ${{ inputs.impact }}
        QEOS_TEST_COMMAND: ${{ inputs.test-command }}
        QEOS_ACTION_URL: ${{ inputs.url }}
        QEOS_ACTION_ENVIRONMENT: ${{ inputs.environment }}
      run: |
        case "$QEOS_IMPACT_MODE" in
          first) mode="" ;;
          only) mode="--suggested-only" ;;
          *) echo "::error::impact must be off, first or only, not '$QEOS_IMPACT_MODE'"; exit 2 ;;
        esac
        if [ -z "$QEOS_TEST_COMMAND" ]; then
          echo "::error::impact $QEOS_IMPACT_MODE needs test-command"
          exit 2
        fi
        # The command as the workflow author wrote it, quotes included
        eval "set -- $QEOS_TEST_COMMAND"
        qeos-collector run-impact --url "$QEOS_ACTION_URL" \
          ${QEOS_ACTION_ENVIRONMENT:+--environment "$QEOS_ACTION_ENVIRONMENT"} \
          $mode ${{ inputs.extra-args }} -- "$@"
```

- [ ] **Step 2: CI runs it on every push.** Create `collector/tests/fixtures/fake-cucumber-green.json`:

```json
{"features": [
  {"uri": "features/smoke.feature", "name": "Smoke", "scenarios": [
    {"name": "Opens the shop", "line": 3, "tags": ["@smoke"], "status": "passed", "seconds": 1},
    {"name": "Not tagged", "line": 6, "status": "passed", "seconds": 1}]}
]}
```

In `.github/workflows/ci.yml`, in the `collector-action` job, after the step `- name: Run the action` and its `with:` block, add:

```yaml
      # impact: first, as consumers use it, with a stand-in Cucumber. There is no QEOS to ask, so the suite runs as
      # one stage, and the failed upload does not fail the step (no --fail-on-error)
      - name: Run the action with impact first
        uses: ./collector-action
        env:
          QEOS_API_KEY: qeos_ci_placeholder_key
          FAKE_CUCUMBER_SPEC: collector/tests/fixtures/fake-cucumber-green.json
        with:
          url: https://qeos.example.invalid
          impact: first
          test-command: python collector/tests/fake_cucumber.py --tags "@smoke"
          extra-args: --cucumber js
```

- [ ] **Step 3: Check the action's script locally.** It is the same command line the step builds:

```bash
QEOS_API_KEY=qeos_ci_placeholder_key FAKE_CUCUMBER_SPEC=collector/tests/fixtures/fake-cucumber-green.json \
QEOS_TEST_COMMAND='python collector/tests/fake_cucumber.py --tags "@smoke"' \
bash -c 'eval "set -- $QEOS_TEST_COMMAND"; collector/.venv/Scripts/python -m qeos_collector run-impact --url https://qeos.example.invalid --cucumber js -- "$@"'; echo "exit $?"
```

Expected, in order:
- `qeos: no suggestion: …` (no change data locally, or the platform cannot be reached);
- `qeos: running the full suite as one stage`;
- `qeos: stage 1 (all): the command as given`;
- `qeos: no failures`;
- an `upload failed: cannot reach the platform …` line after the retries;
- `exit 0`.

Then run `git grep -n "impact" collector-action/action.yml` and check that each of the two new inputs appears in `inputs:` and in the new step.

- [ ] **Step 4: The Jenkins step.** In `collector-jenkins/vars/qeosCollectorUpload.groovy`, replace everything from the line `//   }` that closes the usage example down to the end of the file with:

```groovy
//   }
//
// Suggested tests first (collector 0.6.0, Cucumber): the step runs the tests itself, so call it in
// the test stage, not in `post`. A failing test fails the build, as the test command would:
//
//   qeosCollectorUpload(impact: 'first', testCommand: 'npx cucumber-js --tags "not @wip"')
//   qeosCollectorUpload(impact: 'only', testCommand: 'mvn -q test')   // only the likely affected
//
// The agent needs Python 3.9+ and git on PATH. The collector is installed
// pinned to this library's `ref` (a collector-v* tag), so builds stay
// reproducible. `source` overrides the whole pip requirement (e.g. a local
// checkout or an internal mirror).
def call(Map config = [:]) {
    String patterns = config.patterns ?: 'reports/**/*.xml'
    String ref = config.ref ?: 'collector-v0.5.2'
    String impact = (config.impact ?: 'off').toString()
    if (!(impact in ['off', 'first', 'only'])) {
        error("qeosCollectorUpload: impact must be 'off', 'first' or 'only', not '${impact}'")
    }
    if (impact != 'off' && !config.testCommand) {
        error("qeosCollectorUpload: impact '${impact}' needs testCommand, the Cucumber command to run")
    }
    String source = config.source ?:
        "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@${ref}#subdirectory=collector"
    String args = [
        config.environment ? "--environment '${config.environment}'" : '',
        config.caFile ? "--ca-file '${config.caFile}'" : '',
        config.failOnError ? '--fail-on-error' : '',
        config.extraArgs ?: '',
    ].findAll().join(' ')
    String command = impact == 'off'
        ? "upload ${patterns} ${args}"
        : "run-impact ${args} ${impact == 'only' ? '--suggested-only' : ''} -- ${config.testCommand}"
    // A venv in the workspace: modern Debian/Ubuntu agents refuse system pip
    // installs (PEP 668), and --user can collide between jobs on one agent
    sh """
        python3 -m venv --clear .qeos-venv
        .qeos-venv/bin/python -m pip install --quiet '${source}'
        .qeos-venv/bin/python -m qeos_collector ${command}
    """
}
```

The `ref` default moves to `collector-v0.6.0` in Task 21. In `collector-jenkins/README.md`, after the "## Use" example's parameter paragraph, add:

~~~markdown
### Suggested tests first (Cucumber)

With collector 0.6.0, the step can run the tests itself, the scenarios a change likely affects first:

```groovy
stage('Test') {
  steps {
    withCredentials([string(credentialsId: 'qeos-api-key', variable: 'QEOS_API_KEY')]) {
      withEnv(['QEOS_URL=https://qeos.example.com']) {
        qeosCollectorUpload(impact: 'first', testCommand: 'npx cucumber-js --tags "not @wip"')
      }
    }
  }
}
```

- **`impact`:**
  - `first`: the likely affected scenarios run first, then the rest, as one run;
  - `only`: only the likely affected ones (the full suite when there is no suggestion);
  - `off` (the default): upload `patterns` as before.
- **`testCommand`:** the Cucumber command (`npx cucumber-js …`, `mvn -q test …`, `bundle exec cucumber …`). Add
  `extraArgs: '--cucumber js'` when the command hides the runner (`npm test`).
- **Where to call it:** in the test stage, not in `post`. A failing test fails the build, as the test command
  would. See the collector README, `run-impact`.
~~~

- [ ] **Step 5: GitLab and Azure examples.** At the end of `templates/qeos-collector.gitlab-ci.yml`, add:

```yaml

# Suggested tests first (Cucumber, collector 0.6.0): run the test command through run-impact instead of
# uploading reports afterwards. The likely affected scenarios run first, then the rest, as one run; add
# --suggested-only to run only them (the full suite runs when there is no suggestion). The merge request's
# target branch must be in the clone, or there is no change to score.
#
# e2e:
#   image: node:22
#   variables:
#     GIT_DEPTH: "0"
#   script:
#     - git fetch --quiet origin "+refs/heads/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME:refs/remotes/origin/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"
#     - apt-get update -qq && apt-get install -y -qq python3-pip > /dev/null
#     - pip install --quiet --break-system-packages "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.6.0#subdirectory=collector"
#     - qeos-collector run-impact --url "$QEOS_URL" -- npx cucumber-js --tags "not @wip"
#   rules:
#     - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

In `templates/qeos-collector.azure-pipelines.yml`, after the header paragraph that ends "the upload fails with 401.", add:

```yaml
#
# Suggested tests first (Cucumber, collector 0.6.0): instead of this template after the tests, run the
# tests through run-impact, the likely affected scenarios first, then the rest, as one run (add
# --suggested-only to run only them). The commit's parent must be in the clone:
#
#   steps:
#     - checkout: self
#       fetchDepth: 2
#     - script: |
#         python -m pip install --quiet "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.6.0#subdirectory=collector"
#         qeos-collector run-impact --url https://qeos.example.com -- npx cucumber-js --tags "not @wip"
#       displayName: Tests, the likely affected first
#       env:
#         QEOS_API_KEY: $(QEOS_API_KEY)
```

- [ ] **Step 6: Commit**

```bash
git add collector-action/action.yml .github/workflows/ci.yml collector/tests/fixtures/fake-cucumber-green.json collector-jenkins/vars/qeosCollectorUpload.groovy collector-jenkins/README.md templates/qeos-collector.gitlab-ci.yml templates/qeos-collector.azure-pipelines.yml
git commit -m "feat(integrations): impact first/only in the GitHub Action and the Jenkins step; GitLab and Azure examples" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- collector-action/action.yml .github/workflows/ci.yml collector/tests/fixtures/fake-cucumber-green.json collector-jenkins/vars/qeosCollectorUpload.groovy collector-jenkins/README.md templates/qeos-collector.gitlab-ci.yml templates/qeos-collector.azure-pipelines.yml
```

### Task 20: Docs: SETUP, README, PRODUCT, TODO, TECHNICAL_SPECIFICATION, ADR-029 release B, the roadmap

**Files:**
- Modify: `docs/SETUP.md`, `README.md`, `TODO.md`, `TECHNICAL_SPECIFICATION.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md` (banner line 14), `docs/architecture/adr/ADR-029-test-impact-analysis.md`, `docs/architecture/adr/INDEX.md`

**Interfaces:**
- Consumes: the whole feature.
- Produces: the user-facing documentation (spec §6). PRODUCT.md was updated in Task 3; the collector and ingestion READMEs in their tasks.

- [ ] **Step 1: SETUP.** In `docs/SETUP.md`, before `### 4.2 Test cases`, add:

~~~markdown
#### 4.1.10 Suggested tests first in CI (Cucumber)

Collector 0.6.0 can run your Cucumber suite with the scenarios a change likely affects **first** and the rest after,
as one run, so failures in the changed area show up in minutes ([Test impact](#test-impact)).

**What it needs:**
- runs with changed files, as for test impact;
- a checkout with the history the diff needs: `fetch-depth: 0` on GitHub pull requests, the target branch fetched on
  GitLab merge requests, at least 2 commits elsewhere.

**GitHub Actions:** the action runs the tests itself, in place of the test step:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- uses: atriis/Atriis.QEOS/collector-action@collector-v0.6.0
  with:
    url: ${{ vars.QEOS_URL }}
    impact: first                       # or only: the likely affected scenarios alone
    test-command: npx cucumber-js --tags "not @wip"
    # extra-args: --cucumber js         # when the command hides the runner (npm test)
  env:
    QEOS_API_KEY: ${{ secrets.QEOS_API_KEY }}
```

**Jenkins:** `qeosCollectorUpload(impact: 'first', testCommand: '…')` in the test stage
([collector-jenkins/README.md](../collector-jenkins/README.md)). **GitLab and Azure:** the commented examples at the
end of the templates in `templates/`. **Any CI:** `qeos-collector run-impact -- <your Cucumber command>`; see the
collector README for the options, the modes and the exit codes.

**What you see in QEOS:**
- **The run page** says "Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2 (the rest) …
  · first failure after 42.5 s (full suite 15m 15s)".
- **With `impact: only`, or a `--fail-fast` stop,** the run is marked **Suggested only**, on the run page, in the
  runs list (the **Full runs only** chip hides such runs), in failure alerts and in the weekly summary. It never
  counts in the impact statistics or the accuracy figure: a run of only the suggested tests cannot show what the
  suggestion missed. Its impact card says "Suggested tests only, not evaluated".

**Cucumber setups.** run-impact reads the scenarios with a dry run and selects them with rerun files. Feature paths
it can see in the command are left out of the stages. Paths it cannot see change what runs:
- a cucumber-js profile or config with `paths`;
- an npm script that names feature folders;
- `--shard`.

It checks this before any test runs and stops with exit 2, saying so. Select features with tags instead, or call
Cucumber directly. With Gradle, forward `cucumber.*` system properties to the test task (collector README).
~~~

In "#### Test impact", after the **Run likely affected** bullet, add:

```markdown
- **In CI:** run the likely affected scenarios first with collector 0.6.0 ([4.1.10](#4110-suggested-tests-first-in-ci-cucumber)).
```

In "## 8. Troubleshooting", add these rows after the "No changed files on runs" row:

```markdown
| `impact` / `run-impact`: "no suggestion: no change data" | The diff has no base: on GitHub pull requests check out with `fetch-depth: 0`; on GitLab fetch the merge request's target branch; elsewhere check out at least 2 commits. `run-impact` then runs the full suite as one stage. |
| `run-impact`: "cannot narrow this command" | Something outside the command selects features: a profile or config with `paths`, an npm script naming folders, or `--shard`. Select features with tags, or call Cucumber directly ([4.1.10](#4110-suggested-tests-first-in-ci-cucumber)). Nothing ran. |
| `run-impact`: "cannot tell which Cucumber" | The command hides the runner (`npm test`, a script): pass `--cucumber js`, `jvm` or `ruby` (in the action: `extra-args: --cucumber js`). |
```

- [ ] **Step 2: README.** In `README.md`, "### Results and analytics", at the end of the **Test impact** bullet, add: " In CI, collector 0.6.0 runs the likely affected Cucumber scenarios first and the rest after, as one run (`run-impact`, or the GitHub Action's `impact: first`). Runs of only the suggested tests are marked as such and never count in the accuracy figure."

Replace the line "**Next:** release B (a collector command that runs the suggested tests first), then tuning test impact on real data." with "**Next:** tuning test impact on real data, and `run-impact` formats beyond Cucumber (JUnit with Maven/Gradle, pytest, Playwright)."

In the delivered list just above it, after the line "- test impact analysis (ADR-029): …;", add "- suggested tests first in CI (test impact release B): `qeos-collector impact` and `run-impact`, collector 0.6.0;".

- [ ] **Step 3: TODO.** In `TODO.md`, replace the whole release B entry (the parent line and its sub-items that Tasks 10 and 14 wrote) with:

```markdown
   - [x] Release B, suggested tests first in CI (done 2026-10-13; spec `docs/superpowers/specs/2026-10-13-suggested-tests-first-design.md`, ADR-029 "Release B"):
     - `qeos-collector impact` (cucumber, list, json; exit 0/3/4) and `run-impact` (two stages, one run, `--fail-fast`, `--suggested-only`);
     - run scope and stages (ingestion migration 020);
     - subset runs out of the statistics, outcomes and accuracy;
     - `POST /collect/impact`;
     - the action's `impact` input and the Jenkins step's `impact` option;
     - collector 0.6.0.
   - [ ] Follow-up: run-impact formats beyond Cucumber, as small follow-ups: JUnit with Maven/Gradle (`-Dtest=`), pytest (node ids), Playwright/JS (`--grep` or file:line)
   - [ ] Follow-up: verify run-impact on a real cucumber-jvm project with Maven and with Gradle (system-property forwarding), and on Ruby Cucumber; the adapters follow their documented options, and only cucumber-js 12.6.0 was run during planning
```

In the collector section (after the "Collector 0.5.2 (2026-10-13)" line), add:

```markdown
- [x] Collector 0.6.0 (2026-10-13): `impact` and `run-impact` (suggested tests first, Cucumber); the action's `impact` and `test-command` inputs, the Jenkins step's `impact` and `testCommand`; tag `collector-v0.6.0`
```

- [ ] **Step 4: TECHNICAL_SPECIFICATION.** In "## 7. Collector", after "Also `qeos-collector check` and `import-features`.", add:

```markdown
`qeos-collector impact` prints the suggestion for the change (POST /collect/impact; cucumber, list or json; exit 0
printed, 3 nothing to suggest, 4 QEOS unreachable or out of time). `qeos-collector run-impact -- <cucumber command>`
works in four steps:
- it discovers the scenarios with a Cucumber dry run (cucumber-js, cucumber-jvm through Maven/Gradle system
  properties, Ruby);
- it checks with a second dry run that rerun files alone select them;
- it runs the suggested ones, then the rest, from two rerun files;
- it uploads one run with `scope` and `stages` (`--fail-fast`, `--suggested-only` mark it `impact-subset`).
```

- [ ] **Step 5: ADR-029.**
- In "## Why ML and embeddings come later", replace the bullet "**Release B**, a collector command that runs the suggested tests first (never instead of the full suite), is not built. Skipping tests is considered only once the accuracy figure supports it." with "**Release B**, running the suggested tests first in CI, shipped with collector 0.6.0 (section below). Skipping tests stays opt-in (`--suggested-only`), and such runs never feed the accuracy figure."
- Before "## Consequences", add:

```markdown
## Release B: suggested tests first in CI (2026-10-13)

Spec `docs/superpowers/specs/2026-10-13-suggested-tests-first-design.md`, plan
`docs/superpowers/plans/2026-10-13-suggested-tests-first.md`.

- **The collector asks with its API key.**
  - `POST /api/v1/collect/impact` runs the same scoring, limits and 503 `impact_timeout` as `POST /analytics/impact`,
    for the key's project.
  - The analytics route needs a user token, which CI does not have.
  - A project key can therefore read its project's suggestions: test names and path units, never results.
- **`qeos-collector impact`** prints the suggestion as Cucumber locations, a list or JSON. Its exit codes are 0
  (printed), 3 (nothing to suggest) and 4 (QEOS unreachable or out of time).
- **`run-impact`, the Cucumber mechanism:**
  - a dry run with a JSON report discovers the scenarios;
  - two rerun files hold the suggested scenarios and the rest;
  - a second dry run checks that the rerun file alone selects stage 1, because cucumber-js adds profile `paths` to
    it and `--shard` drops scenarios. This keeps "no scenario runs twice" true.

  The same mechanism serves cucumber-js, cucumber-jvm (system properties) and Ruby. Other runners are follow-ups.
- **Runs record `scope` and `stages`** (migration 020).
  - A run of only the suggested tests (`--suggested-only`, or a `--fail-fast` stop) is `impact-subset`.
  - It stays out of the statistics, the history count, replay, the outcome evaluation and the accuracy figure. A
    subset cannot show what the suggestion missed, so counting it would flatter the catch rate.
  - Its suggestion is stored and answered as `not_evaluated`, a state derived from the scope, not a stored column.
  - Its results count everywhere else: trends, flaky detection, the Report, and as history for later runs.
- **Never skipping by default.** `first` runs the full suite every time. `only` is opt-in, with the full suite as
  fallback when there is no suggestion. Partial runs are labelled on the run page, in the runs list, in failure
  alerts and in the weekly summary.
- **Consequences:**
  - a `run-impact` run costs two extra dry runs (discovery and the stage-1 check), seconds for cucumber-js and a
    build start for Maven;
  - Gradle users forward `cucumber.*` system properties to the test task;
  - the request hash leaves `scope` and `stages` out at their defaults, so uploads stored before migration 020
    still replay.
```

In `docs/architecture/adr/INDEX.md`, in the ADR-029 row, append to its description: "; release B (2026-10-13): suggested tests first in CI, partial runs kept out of the accuracy figure".

- [ ] **Step 6: Roadmap and banner.**
- In `IMPLEMENTATION_PLAN.md`, replace "Next from that line: release B, a collector command that runs the suggested tests first." with "Release B followed (done 2026-10-13): suggested tests first in CI with collector 0.6.0 (`impact`, `run-impact`). Next from that line: tuning on real data and other runner formats."
- In `ARCHITECTURE_BLUEPRINT_V1_0.md` line 14, replace "each suggestion stored at upload and its accuracy measured; ADR-029)" with "each suggestion stored at upload and its accuracy measured, and run first in CI by the collector; ADR-029)".

- [ ] **Step 7: Checks and commit**

Run: `python scripts/check_architecture_docs.py && python -m pytest scripts/tests -q`
Expected: no findings, and the tests pass. The check reads the banner's Services row, which is unchanged.

```bash
git grep -n "release B (a collector command" -- ':!docs/superpowers'
```

Expected: nothing.

```bash
git add docs/SETUP.md README.md TODO.md TECHNICAL_SPECIFICATION.md IMPLEMENTATION_PLAN.md ARCHITECTURE_BLUEPRINT_V1_0.md docs/architecture/adr/ADR-029-test-impact-analysis.md docs/architecture/adr/INDEX.md
git commit -m "docs: suggested tests first in CI (ADR-029 release B, setup, product, roadmap)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docs/SETUP.md README.md TODO.md TECHNICAL_SPECIFICATION.md IMPLEMENTATION_PLAN.md ARCHITECTURE_BLUEPRINT_V1_0.md docs/architecture/adr/ADR-029-test-impact-analysis.md docs/architecture/adr/INDEX.md
```

### Task 21: Collector 0.6.0: the version and the pinned references

**Files:**
- Modify: `collector/src/qeos_collector/__init__.py`, `collector/tests/test_package.py`
- Modify (`collector-v0.5.2` → `collector-v0.6.0`): `README.md`, `collector/README.md`, `collector-jenkins/vars/qeosCollectorUpload.groovy`, `dashboard/src/pages/ProjectSettingsPage.tsx`, `dashboard/src/pages/ProjectSettingsPage.test.tsx`, `dashboard/src/templates/qeos-run.yml.txt`, `docs/SETUP.md`, `templates/github/qeos-run.yml`, `templates/qeos-collector.azure-pipelines.yml`, `templates/qeos-collector.gitlab-ci.yml`
- Modify: `IMPLEMENTATION_PLAN.md` (the release tags range)

**Interfaces:**
- Consumes: Tasks 15–20.
- Produces: a commit whose `__version__` matches the tag Task 22 pushes. `release-collector.yml` fails the build when they differ.

Ruling 23 applies.

- [ ] **Step 1: The failing test.** In `collector/tests/test_package.py`, change `"0.5.2"` to `"0.6.0"`.

Run: `cd collector && .venv/Scripts/python -m pytest tests/test_package.py -q`
Expected: FAIL (`'0.5.2' == '0.6.0'`).

- [ ] **Step 2: The version.** In `collector/src/qeos_collector/__init__.py`, set `__version__ = "0.6.0"`. Then reinstall the package so `importlib.metadata` sees it:

Run: `cd collector && .venv/Scripts/python -m pip install -q -e . && .venv/Scripts/python -m pytest tests/test_package.py -q`
Expected: PASS.

- [ ] **Step 3: Move the pinned references.** Run, from the repository root:

```bash
git grep -n "collector-v0.5.2" -- ':!docs/superpowers'
python - <<'PY'
from pathlib import Path

FILES = ["README.md", "collector/README.md", "collector-jenkins/vars/qeosCollectorUpload.groovy",
         "dashboard/src/pages/ProjectSettingsPage.tsx", "dashboard/src/pages/ProjectSettingsPage.test.tsx",
         "dashboard/src/templates/qeos-run.yml.txt", "docs/SETUP.md", "templates/github/qeos-run.yml",
         "templates/qeos-collector.azure-pipelines.yml", "templates/qeos-collector.gitlab-ci.yml"]
for name in FILES:
    path = Path(name)
    text = path.read_bytes().decode("utf-8")
    # The troubleshooting row names 0.5.2 as the release that fixed "empty revision": history, kept
    lines = [line if "empty revision" in line else line.replace("collector-v0.5.2", "collector-v0.6.0")
             for line in text.split("\n")]
    path.write_bytes("\n".join(lines).encode("utf-8"))
PY
git grep -n "collector-v0.5.2" -- ':!docs/superpowers'
```

Expected: the first `git grep` lists the files above. The second lists only the `docs/SETUP.md` troubleshooting row containing "empty revision". `git diff --stat` shows only the files above, with no line-ending churn.

In `IMPLEMENTATION_PLAN.md`, replace "`collector-v0.1.0`…`v0.5.1`" with "`collector-v0.1.0`…`v0.6.0`".

- [ ] **Step 4: Dashboard and collector checks** (`COLLECTOR_REF` and the template test changed)

Run: `cd dashboard && npm run lint && npm run typecheck && npx vitest run src/pages/ProjectSettingsPage.test.tsx src/templates/templates.test.ts && node --test ../templates/github/qeos-run.test.mjs`
Then: `cd collector && .venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add collector/src/qeos_collector/__init__.py collector/tests/test_package.py README.md collector/README.md collector-jenkins/vars/qeosCollectorUpload.groovy dashboard/src/pages/ProjectSettingsPage.tsx dashboard/src/pages/ProjectSettingsPage.test.tsx dashboard/src/templates/qeos-run.yml.txt docs/SETUP.md templates/github/qeos-run.yml templates/qeos-collector.azure-pipelines.yml templates/qeos-collector.gitlab-ci.yml IMPLEMENTATION_PLAN.md
git commit -m "release: qeos-collector 0.6.0 (impact, run-impact)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- collector/src/qeos_collector/__init__.py collector/tests/test_package.py README.md collector/README.md collector-jenkins/vars/qeosCollectorUpload.groovy dashboard/src/pages/ProjectSettingsPage.tsx dashboard/src/pages/ProjectSettingsPage.test.tsx dashboard/src/templates/qeos-run.yml.txt docs/SETUP.md templates/github/qeos-run.yml templates/qeos-collector.azure-pipelines.yml templates/qeos-collector.gitlab-ci.yml IMPLEMENTATION_PLAN.md
```

No tag yet: Task 22 tags after the gate and a green CI.

### Task 22: Phase 3 gate, push, tag `collector-v0.6.0`

**Files:** fixes only, in the files of Tasks 15–21.

**Interfaces:**
- Consumes: everything.
- Produces:
  - a pushed `master`, with CI green;
  - the tag `collector-v0.6.0`;
  - a GitHub release with the wheel, the sdist and `qeos-collector.pyz`;
  - the GHCR image `qeos-collector:0.6.0`;
  - `collector-v0` moved to the same commit.

- [ ] **Step 1: Every suite, the dashboard, the checks.** Run, in order, as in Task 10:
  - Step 2 (every Python suite, serially, the collector included);
  - Step 3 (dashboard lint, typecheck, vitest, build, `node --test ../templates/github/qeos-run.test.mjs`);
  - Step 4 (`check_architecture_docs.py` and its tests, `bash monitoring/check.sh`, the ingestion container smoke);
  - Step 5 (`nginx -t` twice, the stack up, `alembic current` = `020 (head)`, `bash scripts/smoke_gateway.sh`).

  Then the collector on Python 3.9 as in Task 14 Step 2.

  Expected: all green. The smoke ends with `all gateway checks passed`.

- [ ] **Step 2: A real cucumber-js, once.** It confirms the js adapter against the runner, beyond the stand-in. This needs network access to npm. The URL is unreachable on purpose: there is no suggestion, so the suite runs as one stage. That proves the arguments and the report.

```bash
mkdir -p ../qeos-cuke-check/features && cd ../qeos-cuke-check
printf 'Feature: Pay\n\n  Scenario: Pays with card\n    Given a shopper\n' > features/pay.feature
npm init -y >/dev/null && npm install --silent @cucumber/cucumber@12.6.0
QEOS_API_KEY=qeos_placeholder ../Atriis.QEOS/collector/.venv/Scripts/python -m qeos_collector run-impact --url https://qeos.example.invalid -- npx cucumber-js; echo "exit $?"
cd ../Atriis.QEOS && rm -rf ../qeos-cuke-check
```

Expected:
- `stage 1 (all): the command as given`;
- `stage 1 (full suite): 1 scenario(s), 0 failed, …`;
- `exit 1`: the undefined step fails the scenario as cucumber-js reports it, and the exit code is cucumber-js's own.

If npm is not reachable, skip this step and say so in the gate notes; the TODO follow-up from Task 20 keeps the runner checks open.

- [ ] **Step 3: Push, and wait for CI on `master`**

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose down
git ls-files -s scripts/smoke_gateway.sh
git status --short
git log --oneline origin/master..master
gh auth status
git push origin master
sha="$(git rev-parse HEAD)"
until run_id="$(gh run list --workflow ci.yml --commit "$sha" --json databaseId --jq '.[0].databaseId')" && [ -n "$run_id" ]; do sleep 5; done
gh run watch --exit-status "$run_id"
```

Expected:
- `100755`;
- no stray tracked changes;
- `gh` logged in as `carneiru`;
- CI green, including "collector-action installs and runs" with its new impact step.

- [ ] **Step 4: Tag the release; the release workflow moves `collector-v0`**

```bash
git tag collector-v0.6.0
git push origin collector-v0.6.0
until run_id="$(gh run list --workflow release-collector.yml --commit "$sha" --json databaseId --jq '.[0].databaseId')" && [ -n "$run_id" ]; do sleep 5; done
gh run watch --exit-status "$run_id"
git fetch --tags --force origin
git rev-parse collector-v0.6.0^{commit} collector-v0^{commit}
gh release view collector-v0.6.0 --json assets --jq '.assets[].name'
```

Expected:
- the release workflow is green: test, build, release, docker and float;
- both `rev-parse` lines print the same commit, so `collector-v0` now points at 0.6.0;
- the assets list the wheel, the sdist, `qeos-collector.pyz` and `qav-collector.pyz`.

A Docker Hub 429 in the docker job is transient: rerun that job once with `gh run rerun --failed`.

- [ ] **Step 5: Rebuild the local stack's dashboard and ingestion** (the developer's stack, not CI)

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait ingestion-migrate ingestion-service dashboard gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```

Expected: `all gateway checks passed`. Never `docker compose down -v`.

---

## Self-review

**1. Spec coverage** (each spec item → task):
- **§2.1 `impact`:**
  - changed files by `gitdiff.collect_changes`: Task 12 `fetch`;
  - the formats: Task 13 `render` (cucumber with outline rows and `--name`, list, json);
  - `--out`: Task 13;
  - exit codes 0, 3 and 4: Tasks 12 and 13, Ruling 2;
  - the endpoint: Task 4, Ruling 1.
- **§2.2 `run-impact`:**
  - discovery with the user's tags, profiles and paths: Task 16 (`test_discovery_honours_the_commands_tags`);
  - stage 1 through a rerun file, and filtered-out suggestions reported: Task 16 (`skipped by the filter`);
  - stage 2 and no scenario twice: Task 16 (union equals discovery), plus the stage-1 check (Ruling 8, Review Focus 3);
  - one combined upload with `scope = full` and `stages`: Task 16;
  - `--fail-fast`, `--suggested-only` with fallback, `--no-fallback`: Task 17;
  - `--gate` on the combined run: Task 17;
  - the CI summary: Task 18;
  - Windows paths: Tasks 15 and 16 (`as_posix`, backslash uris, `shutil.which`, LF rerun files).
- **§3.1 Ingestion:**
  - `scope` and `stages`, the migration and the payload: Tasks 1 and 2;
  - older collectors mean `full`: Task 2 (`test_an_upload_without_them_is_a_full_run_without_stages`);
  - the exclusions and `not_evaluated`: Task 3;
  - subset runs still in trends and flaky detection: Task 3 (only `change_runs`, `history_runs`, the evaluation and the accuracy change) and Task 5 (the weekly pass rate counts them).
- **§3.2 Dashboard:**
  - the run-page line, "Suggested tests only" and "stopped after stage 1": Task 6;
  - the pill and the filter: Task 7;
  - the card's "not evaluated": Task 8.
- **§3.3 Notifications:** Task 5.
- **§4 Integrations:** the action, Jenkins, GitLab and Azure: Task 19; `qeos-run.mjs` unchanged.
- **§5 Testing:** every listed item has a test in the task named above. The smoke covers a two-stage upload and a subset upload left out of the statistics (Task 9), plus the collector's scoring (Tasks 9 and 13).
- **§6 Documentation:**
  - collector README: Tasks 13, 16, 17, 18;
  - SETUP, PRODUCT, README, TODO and ADR-029: Tasks 3, 10, 14, 20;
  - the ingestion README: Tasks 2–5.
- **§7 Delivery:** three phases, gates in Tasks 10, 14 and 22; release 0.6.0 with `collector-v0` in Tasks 21 and 22.
- **§8:** nothing outside scope is built. Other formats are TODO follow-ups (Task 20).

**2. Placeholder scan.** Searched for "TBD", "TODO" (only the `TODO.md` file name appears), "implement later", "similar to", "appropriate", "handle edge cases": none. Every code step shows its code, and every command shows its expected result. `<svc>` and `<path>` appear only in the generic command rules of the Global Constraints, which name what to substitute.

**3. Type and name consistency.**
- **Collector names:** `impact.SUGGESTED`/`NOTHING`/`UNAVAILABLE`, `Target`, `Suggestion.tests`, `resolve` and `fetch` are used the same way in Tasks 12, 13 and 16–18.
- **Scenarios:** `cucumber.Scenario.location` and `.key` match `split` and `_check_selection`.
- **The run module:** `run_impact.Stage` (`name`, `returncode`, `duration_s`, `report`, `tests`, `failed`) matches `summary`'s attribute use.
- **The `_finish` signature** changes once, in Task 18, together with its single caller.
- **Server constants:** `FULL_SCOPE` and `SUBSET_SCOPE` come from `models/run.py` in every service module.
- **The `evaluation` values** match between `schemas/impact.py`, `impact_read`, `api/impact.ts` and `ImpactCard`.
- **Payload shapes:**
  - `RunStages` and `RunStage` in TypeScript mirror `StagesOut` and `StageOut`;
  - the stage names `suggested`, `rest` and `all` are the same in `StageIn`, `stages_payload`, `summary.STAGES` and `runScope.STAGE`.

**4. Review Focus.**
- **Checked:**
  - an older upload's replay;
  - the nightly pass's cap;
  - feature paths outside run-impact's view;
  - empty rerun files;
  - a stale `--out` file;
  - Windows `.cmd` programs and backslash uris (Tasks 15 and 16);
  - NaN and out-of-range stages (Task 2);
  - a subset card that polls (Task 8);
  - a weekly pass rate that must still count subset runs (Task 5).
- **The five most likely to bite** are listed at the top, each with its test in the owning task.

**Spec gaps and contradictions with the code (resolved by Rulings):**
- **§2.1 names `POST /analytics/impact` for the collector,** which accepts only a user JWT plus a project-service role check. The collector holds an API key, hence `POST /collect/impact` (Ruling 1).
- **§2.1 maps "not enough history" to exit 3,** but such a suggestion can still list labelled tests worth running first. Exit 3 applies only when no test is listed (Ruling 2).
- **§3.1 "stored with state `not_evaluated`":** `run_impact` has no state column. The state is derived from `test_runs.scope` and exposed as `evaluation` (Ruling 3).
- **§2.2 "a rerun file (`@file`), which both `cucumber` (JVM, Ruby) and `cucumber-js` accept":**
  - cucumber-js 12 reads `@`-prefixed *file names* relative to the working directory;
  - cucumber-jvm reads a rerun file through `cucumber.features=@file` rather than a positional argument under Maven;
  - cucumber-js adds profile `paths` to the rerun file's.

  Hence Rulings 7 and 8 (per-flavour arguments and the stage-1 check).
- **§3.3 "the weekly summary labels a subset run":** the weekly summary lists no runs, so it gets a count line (Ruling 17).
- **§3.2 "N min (full suite M min)":** the dashboard's `formatDuration` is used instead (Ruling 18).
- **A change the spec does not mention:** the request hash. A new field changes it for every older body, so `scope` and `stages` are left out at their defaults (Ruling 5).
