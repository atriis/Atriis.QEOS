# Suggested tests first in CI (test impact release B) — design

Status: approved in conversation 2026-10-13 (sections 1–3), pending review of this written spec.
Builds on test impact analysis (ADR-029, spec `2026-10-12-test-impact-analysis-design.md`): uses the
existing `POST /api/v1/projects/{id}/analytics/impact`. Roadmap: TODO.md follow-up "release B".

## 1. Goal

In CI, run the tests likely affected by a change **first**, so failures in the changed area show up in
minutes, while the full suite still runs. Optionally, a team may run **only** the suggested tests; such
runs are marked partial and never distort the statistics or the accuracy figure.

Decided with the user: Cucumber and a plain list now; JUnit/Maven/Gradle, pytest and Playwright/JS
formats as small follow-ups. Two stages in one run by default; a suggested-only mode with a safe fallback.

## 2. Collector

### 2.1 `qeos-collector impact`
Computes the changed files as uploads do (`gitdiff.collect_changes`: the PR or merge-request base, else
the previous commit), calls `POST /analytics/impact` with `{changed_paths, branch}` and prints the
suggestion.

- `--format cucumber` (default for `.feature` projects): one `path/to/x.feature:LINE` per line; when a
  scenario has no known line, a `--name "<scenario>"` filter instead. Scenario outline rows are individual
  lines.
- `--format list`: one test per line, `suite<TAB>class<TAB>name`.
- `--format json`: the full suggestion with evidence and kinds.
- `--out FILE`: write there instead of stdout.
- Exit codes: `0` a suggestion was printed; `3` nothing to suggest or not enough history; `4` QEOS
  unreachable or timed out (503 `impact_timeout`). A pipeline branches on them; none means "tests failed".

### 2.2 `qeos-collector run-impact [options] -- <test command>`
- **Discovery:** runs the test command in Cucumber's dry-run mode (`--dry-run --format json`, with the
  user's own tags, profiles and paths) to list the scenarios the command would run.
- **Stage 1:** the suggested scenarios that discovery found, passed through a rerun file (`@file`), which
  both `cucumber` (JVM, Ruby) and `cucumber-js` accept, so no command-line length limit applies. Suggested
  scenarios excluded by the user's filters are reported as skipped by the filter.
- **Stage 2:** every other discovered scenario, through a second rerun file; no scenario runs twice.
- **Upload:** both stages' reports are uploaded as **one run** with `scope = full` and its `stages`.
- `--fail-fast`: stop after a failing stage 1; upload it with `scope = impact-subset` and
  `stopped_after_stage = 1`.
- `--suggested-only`: run stage 1 only, `scope = impact-subset`. When there is no suggestion (exit 3 or 4
  of the scoring), run the **full suite** instead and log why, unless `--no-fallback`.
- `--gate` keeps its meaning (exit 1 on failures outside quarantine) and judges the uploaded run.
- **CI summary:** in GitHub Actions, a table in the job's step summary (`$GITHUB_STEP_SUMMARY`) with the
  suggested tests and their evidence, both stages' durations and the time to the first failure; elsewhere
  the same as text in the log.
- Paths are normalised for Windows runners.

## 3. QEOS

### 3.1 Ingestion
- Runs gain `scope` (`full` default, `impact-subset`) and `stages` (JSON: each stage's duration, test count
  and failures; `time_to_first_failure_s`; `stopped_after_stage`). New collector payload fields and a
  migration; older collectors send nothing, meaning `full`.
- `impact-subset` runs are excluded from the impact statistics (nightly rollup), the outcome evaluation and
  the accuracy figure; their suggestion is stored with state `not_evaluated`. They still count in
  pass-rate trends and flaky detection.

### 3.2 Dashboard
- Run page: a "Suggested tests first" line with stage 1 and 2 durations and "first failure after N min
  (full suite M min)"; a subset run reads "Suggested tests only" (and "stopped after stage 1" for
  `--fail-fast`). The impact card of a subset run says "Suggested tests only, not evaluated".
- Runs list: a "Suggested only" pill; a run filter hides subset runs.

### 3.3 Notifications
Failed-run alerts and the weekly summary label a subset run "Suggested tests only" and a fail-fast stop
"stopped after stage 1", so a partial run is never read as a full verdict.

## 4. Integrations

- GitHub Action: input `impact: first | only | off` (default `off`) and `test-command`; `first`/`only` wrap
  the command in `run-impact` (`only` = `--suggested-only`).
- Jenkins library: the same as a step option. GitLab and Azure templates: a commented example.
- Run from QEOS (`qeos-run.mjs`) is unchanged: Play already selects the scenarios.

## 5. Testing

- Collector: formats; exit codes; discovery honours tags; rerun files; outline rows; no scenario twice;
  one combined upload; `--fail-fast`; `--suggested-only` with fallback and `--no-fallback`; `--gate`
  on the combined run; step summary; Windows paths.
- Ingestion: `scope` and `stages` stored; subset runs excluded from statistics, outcomes and accuracy;
  migration.
- Dashboard: the run-page line, the pill, the filter, the card's "not evaluated" state.
- Smoke: a two-stage upload; a subset upload left out of the statistics.

## 6. Documentation

Collector README (`impact`, `run-impact`, exit codes), docs/SETUP.md ("Suggested tests first in CI"),
PRODUCT.md, README.md, TODO.md (release B done; JUnit/Maven/Gradle, pytest and Playwright/JS formats as
follow-ups), ADR-029 (release B section), the ingestion README (`scope`, `stages`).

## 7. Delivery

Three phases, each ending in a gate (all suites, smoke) and a push:

1. QEOS side: `scope` and `stages`, the exclusions, the dashboard, notifications.
2. Collector `impact` command.
3. `run-impact` and the integrations; docs; collector release `0.6.0` (the floating `collector-v0` tag
   follows the existing release flow).

## 8. What this builds vs what stays out

Builds suggested-tests-first execution in the customer's CI, using the existing scoring. Stays out: other
runner formats (follow-ups), skipping tests by default, executing tests on QEOS infrastructure (ADR-025),
the team run queue and local runner (v2 roadmap). No TARGET technology is introduced.

## 9. Amendments from the implementation plan (2026-10-13)

The plan's 23 rulings (`docs/superpowers/plans/2026-10-13-suggested-tests-first.md`) replace the text above
where they differ. The main ones:

- The collector scores through a new `POST /api/v1/collect/impact` authenticated by the project API key
  (`/analytics/impact` needs a person's sign-in). **Each API key has a "can read test suggestions"
  permission, off by default (user's decision 2026-10-13)**: owners and admins set it when creating a key or
  later; without it the endpoint answers 403 and the collector exits 2 with that explanation. Existing keys
  stay upload-only.
- Exit codes: 0 when any test is listed (a "not enough history" suggestion that still lists labelled tests is
  0); 3 when nothing is listed or there is no change data; 4 for unreachable, 429, 5xx or timeout; 2 for
  configuration problems (401, 403, 404, TLS).
- `not_evaluated` is derived from the run's `scope`, returned as an `evaluation` field; subset runs are never
  evaluated and are left out of the statistics, `history_runs`, outcomes and accuracy, while their results
  still count as history, *failing on this branch*, trends and flaky detection.
- One Cucumber mechanism for cucumber-js, cucumber-jvm and Ruby: a JSON dry run, then rerun files of
  `uri:line`, with per-flavour arguments (`--cucumber js|jvm|ruby` when detection fails). A stage-1 dry run
  must select exactly the plan before any test runs. No stage runs with an empty rerun file.
- The request hash leaves out `scope` and `stages` at their defaults, so older uploads still replay.
- The weekly summary gains a count line for subset runs (it lists no individual runs).
- Release B ships as collector 0.7.0 (0.6.0 was taken by the failed-step release).

