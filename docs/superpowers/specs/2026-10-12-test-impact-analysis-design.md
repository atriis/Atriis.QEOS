# Test impact analysis — design

Status: approved in conversation 2026-10-12 (sections 1–4), pending review of this written spec.
Roadmap: TODO.md "Execution intelligence and operations" item 4 ("from collected commits' changed files and
later failures, suggest which tests to run for a change (history-based; no coverage instrumentation)").
Blueprint: analytics on existing data, PostgreSQL only; Qdrant / QIP stay TARGET behind "Phase 6 AI engine
work begins" (banner lines 10, 29).

## 1. Goal and scope

Suggest which tests a change is likely to affect, from history: which tests **newly failed** after earlier
changes to the same files or folders. Explain every suggestion with its evidence, and measure honestly how
often the suggestions contained the failures that actually happened.

Decided with the user:

- **This release:** A, the analysis with its in-app views, and C, "Run likely affected" in Run from QEOS.
- **Next release:** B, a collector command that runs suggested tests **first** (never instead of the full
  suite). Skipping tests is considered only once the accuracy figure (§2.3) supports it.
- **Method:** co-failure statistics (§3), plus recording every suggestion and its outcome. A learned model
  on the same features (no new infrastructure) comes after a few weeks of outcomes and must beat the
  statistics on the same accuracy figure. Code embeddings / semantic similarity need Qdrant and wait for
  Phase 6; they are not built now.

## 2. Behaviour

### 2.1 Run page: "Likely affected tests"
A card beside the existing Changes card, for runs with changed files.

- Suggested tests, strongest first. Each line: test name (link to its history) and its evidence, e.g.
  "newly failed in 4 of 6 runs that changed `src/payment/` (normally 3%)".
- Always-included tests carry a label instead of statistics: *test file changed*, *no history yet*,
  *failing on this branch*.
- **Outcome** once the run's results are in: "Suggested 12 tests · 3 newly failed · all 3 were suggested", or
  naming each new failure that was **missed**.
- States: "Not enough history yet: N runs with changed files, needs 20" (always-included tests still shown);
  "No change data for this run" (no changed files uploaded); loading; error with Retry.
- Replayed suggestions (§3.6) are marked *replayed*.

### 2.2 Run from QEOS: "Run likely affected" (C)
In the Play dialog for a branch, a choice **Run likely affected**: QEOS scores the branch's latest change
(§3.5), maps suggested test keys to linked scenarios through the cases' `automated_test_key`, pre-selects
them (the user can still edit the selection) and lists suggested tests with no linked case as "not runnable
from QEOS (no linked case)". The existing duration estimate follows the selection.

### 2.3 Accuracy ("trust figure")
"Suggestions caught X% of new failures, last 30 days" (caught / (caught + missed), new failures in runs that
had a stored suggestion), with the list of misses.

- A **Test impact** section in the Report.
- An Overview widget **Impact accuracy** (type `impact_accuracy`, setting `period` 7|14|30) added to the
  shared widget catalogue (`shared/qeos_shared/overview_widgets.json`), the server validation and the
  dashboard registry.
- Replayed and live figures are distinguishable (§3.6).

## 3. Data and computation (ingestion-service)

### 3.1 Definitions
- **Newly failed:** a test result `failed` in run R whose previous result for that test on the same branch
  was `passed`. When the branch has no previous result (a new PR branch), the test's latest result on the
  run's base branch before R is used. Tests flagged flaky or muted in the window are excluded.
- **Path units:** each changed path counts as itself and its parent folders up to 3 levels
  (`src/payment/api.py`, `src/payment/`, `src/`). When the run records a repository, units are prefixed with
  it (`repo-a:src/payment/`).
- **Ignored changes:** lock files and generated or vendored paths (`*.lock`, `package-lock.json`,
  `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `dist/`, `build/`, `vendor/`, `node_modules/`) are not path
  units. A run whose change list the collector marked *truncated* is left out of the statistics. A change
  of more than 300 files counts at folder level only. Renames count under the new path; old history does not
  carry over in this release.

### 3.2 Nightly rollup
A compose job `impact-rollup` (like `analytics-rollup`) with a job heartbeat
(`job_last_success_timestamp_seconds{job="impact_rollup"}`, an alert like the other jobs). Per project, over
the last 90 days of runs with changed files, it writes:

- `impact_pairs (project_id, path_unit, test_key, changed_runs, new_failures, computed_at)` — only pairs with
  at least one new failure;
- `impact_test_base (project_id, test_key, runs, new_failures)` — each test's base rate.

It replaces a project's rows in one transaction; re-running on the same day yields the same rows.

### 3.3 Scoring a change
From those tables, for the change's path units: for each test, the best unit gives
`confidence = new_failures / changed_runs` and `lift = confidence / base_rate`. A test is suggested when
`changed_runs ≥ 3`, `new_failures ≥ 2` and `lift ≥ 2` (starting values, in one constants module). Order by
confidence, then lift; at most 50 statistical suggestions. Always included, labelled, outside the cap: test
files in the change (matched by path or file name), tests with no history, tests failing in the branch's
latest run. "Not enough history" when the project has fewer than 20 runs with changed files in the window.
Every scoring carries a model version, `stats-v1`.

### 3.4 Stored suggestion and outcome
When a run with changed files is created, ingestion scores it **before** reading its results and stores
`run_impact (run_id PK→test_runs CASCADE, suggested JSON, model_version, replayed bool, scored_at,
caught JSON null, missed JSON null, evaluated_at null)`. The outcome (new failures caught and missed) is
written when the run's last upload part arrives. A suggestion never sees its own run's results.

### 3.5 Endpoints (project read access)
- `GET /api/v1/projects/{id}/runs/{run_id}/impact` → the stored suggestion with evidence and its outcome, or
  the "no change data" / "not enough history" state.
- `POST /api/v1/projects/{id}/analytics/impact` body `{changed_paths: [str], branch: str | null}` → the same
  scoring for any change (used by Play now, by the collector in release B). Limits: at most 5,000 paths,
  1–1,000 characters each, no NUL; else 422.
- `GET /api/v1/projects/{id}/analytics/impact-accuracy?days=7|14|30` → caught, missed, the misses, and
  whether the figure includes replayed runs.

Routing: these paths fall under the gateway's existing ingestion locations (`runs`, `analytics`).

### 3.6 Replay
`impact-rollup --backfill-days 30` (one-off): for each past run with changed files in the window, score with
statistics built only from runs **before** it, store the suggestion with `replayed = true` and its real
outcome. The accuracy figure reports replayed and live parts separately until live outcomes cover the window.

### 3.7 Retention, masking, performance
- The tables cascade from `test_runs` (run retention and legal hold apply) and are rebuilt by the rollup.
- The rollup reads already-masked data only.
- Budgets, measured on the existing 2M-result benchmark and recorded in the ingestion README: the rollup
  under 60 s per project; live scoring under 200 ms.

## 4. Dashboard

- Run page card (§2.1), Report section and Overview widget (§2.3) — one query and hook shared by the section
  and the widget, the widget's `staleKeys` declared in the registry.
- Play dialog choice (§2.2).
- DESIGN.md rules: status never by colour alone, tabular figures, own loading and error states. UI work
  starts with the `ui-ux-pro-max` skill.

## 5. Testing

- **ingestion (pytest):** newly failed (passed→failed counts; failed→failed, flaky, muted do not; base-branch
  fallback); path units (levels, repository prefix, ignored files, truncated runs, >300-file changes);
  scoring thresholds at their edges (`changed_runs` 2/3, lift 1.9/2), ordering, cap, each always-included
  kind; stored suggestion before results and outcome after the last part (a test proves the suggestion
  cannot see its own results); replay uses only earlier runs; accuracy over a window; endpoints (roles,
  input limits, 404 for other projects); job heartbeat, same-day rerun idempotent, retention cascade;
  benchmark against the budgets.
- **dashboard (vitest):** the card in each state, the Report section, the widget (registry ↔ catalogue
  test), Play "Run likely affected" including unlinked tests and the duration estimate.
- **smoke:** two runs with changed files where a test passes then fails; run the rollup once;
  `GET …/runs/{id}/impact` answers; `POST /analytics/impact` with that path suggests the test.

## 6. Documentation

PRODUCT.md (impact rules), DESIGN.md (card, section, widget), README.md, docs/SETUP.md ("Test impact"),
TECHNICAL_SPECIFICATION.md, the ingestion-service README (job, tables, benchmark), monitoring (the new job's
heartbeat alert), TODO.md (item 4 done; follow-ups: release B collector command, the learned model, Phase 6
embeddings, accuracy in the weekly summary), the blueprint banner, and **ADR-029** (statistical method,
evaluation stored at upload, why ML and embeddings come later) with its INDEX row.

## 7. Delivery

Three phases, each ending in a gate (all suites, smoke) and a push:

1. **Analysis:** migration (`impact_pairs`, `impact_test_base`, `run_impact`), the rollup job and heartbeat,
   scoring, stored suggestion and outcome, replay, the three endpoints, smoke, benchmark.
2. **Views:** run page card, Report section, Overview widget (catalogue + validation + registry).
3. **Play and docs:** "Run likely affected", the remaining docs, ADR-029.

## 8. What this builds vs what stays TARGET

Builds history-based test impact analysis on PostgreSQL inside ingestion-service, with an honest,
recorded evaluation. Stays out: a learned model (next, once outcomes exist; no new infrastructure),
embeddings and semantic similarity (Qdrant, Phase 6), coverage instrumentation, and skipping tests in CI.
No TARGET technology is introduced.

## 9. Amendments from the implementation plan (2026-10-12)

Checked against the code while planning (`docs/superpowers/plans/2026-10-12-test-impact-analysis.md`, its
rulings); they replace the text above where they differ:

- Ingestion has no upload parts: the collector sends each part as its own run, so each part gets its own
  suggestion and outcome. The suggestion is scored before the run row is written, in the upload's
  transaction; the outcome is written after the response. Neither can fail an upload (§3.4).
- Runs record no repository today, so path units carry no repository prefix yet; follow-up in TODO (§3.1).
- "Failed" includes `errored`, as everywhere in QEOS; a test's outcome is its last attempt (§3.1).
- Only `run_impact` cascades from `test_runs`; the aggregate tables are rebuilt nightly from the runs that
  remain (§3.7).
- `impact_test_base` also stores each test's names, file and flaky flag, so live scoring never scans results.
  "No history" means fewer than 3 runs (§3.2, §3.3).
- There is no Play dialog per branch: **Run likely affected** is a button on the Test cases page that opens a
  panel, scores the branch's newest change with changed files among its last 20 runs, and replaces the
  selection; Play then runs it as usual (§2.2).
- The Report section uses the Report's period when it is 7, 14 or 30 days ending today, else 30 (§2.3).
- The smoke proves the suggestion through the *failing on this branch* label, since two runs cannot meet the
  statistical thresholds (§5).
- The new compose job is added to the README diagram, component table and blueprint Services row, which CI's
  architecture-docs check requires (§6).
- Performance design (pre-flight measurement missed the budgets with per-row inserts and whole-project
  loads): the rollup builds both statistics tables inside PostgreSQL with `INSERT … SELECT`; `impact_pairs`
  is keyed by `(project_id, unit_hash, test_key)` with `unit_hash = md5(path_unit)` (no surrogate id); live
  scoring reads only the rows for the change's unit hashes. Budgets unchanged (§3.7), measured with one commit
  per run.
- Replay takes its own lock and may run long on large projects; it is a one-off (§3.6).
- The accuracy figure also shows the average suggestion size, so a high catch rate from suggesting nearly
  everything is visible (§2.3).
- `impact_pairs` keeps only pairs with at least `MIN_NEW_FAILURES` (2) new failures, since a pair with one
  can never be suggested; the nightly rebuild applies a changed threshold the next night (§3.2).
- `impact_pairs` stores only pairs that pass every threshold, lift included (computed against
  `impact_test_base` at rollup time), so live scoring reads only suggestible rows (benchmark: whole-pair loads
  missed the 200 ms budget). A test is suggested through the strongest passing unit of the change. Threshold
  changes apply at the next rollup; replay applies the same rule (§3.2, §3.3).

