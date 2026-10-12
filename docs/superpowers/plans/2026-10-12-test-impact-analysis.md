# Test Impact Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Phases.** P1 (analysis, ingestion-service), P2 (views, dashboard), P3 (Play and docs) each ship on their own. The last task of each phase is a gate: every suite, the CI-mirroring steps, `monitoring/check.sh`, `nginx -t`, the gateway smoke, then a push to `master`.

**Goal:** QEOS suggests which tests a change is likely to affect from the history of which tests newly failed after earlier changes to the same files or folders, explains each suggestion, stores every suggestion with its outcome, and reports honestly how often the suggestions contained the new failures.

**Architecture:**
- **ingestion-service** gains migration **018** (`impact_pairs`, `impact_test_base`, `run_impact`). Pure modules hold the definitions and thresholds (`analytics/impact_rules.py`) and the scoring (`analytics/impact_score.py`).
- **Services**, split by responsibility:
  - `service/impact_history.py`: newly failed, one run or many;
  - `service/impact_stats.py`: statistics;
  - `service/impact_service.py`: scoring and storing;
  - `service/impact_replay.py`: replay;
  - `service/impact_read.py`: the read side.
- **The `impact-rollup` job** (`jobs/impact_rollup.py`, compose service, heartbeat `impact_rollup`, JobStale at 2 days) rebuilds the statistics every 24 hours and replays history with `--backfill-days`.
- **At upload,** ingestion scores the change before it adds the run row, stores the suggestion in the upload's transaction, and writes the outcome right after the response from the stored results (a background task, as failure notifications are).
- **Endpoints:** `GET /projects/{id}/runs/{run_id}/impact`, `POST /projects/{id}/analytics/impact` and `GET /projects/{id}/analytics/impact-accuracy`. They fall under the gateway's existing `runs` and `analytics` locations.
- **dashboard** gains the run page's "Likely affected tests" card, the Report's "Test impact" section and the Overview widget `impact_accuracy`. The section and the widget share one query under the Report's key. The widget is catalogued in `shared/qeos_shared/overview_widgets.json`, so project-service validates it unchanged.
- **Run likely affected** on the Cases page scores a branch's latest change and replaces the selection with the linked cases. The existing selection bar, Run dialog and duration estimate follow that selection.

**Tech Stack:** FastAPI 0.142, Pydantic 2.13, SQLAlchemy 2.1, Alembic 1.20, pytest 9 (SQLite in tests), respx; PostgreSQL 15 (window functions, hash index); Prometheus rules with promtool unit tests; React 19, TypeScript 6, React Router 7.18, TanStack Query 5, lucide-react, vitest 5 + MSW 3 + Testing Library. NGINX gateway unchanged.

**Spec:** `docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md` (approved 2026-10-12). Executors read the spec with this plan. Where this plan decides something the spec leaves open or gets wrong against the code, the decision is under **Rulings** and repeated in the task that applies it.

## Global Constraints

Every task implicitly includes all of these. Values are copied verbatim from the spec.

- **Newly failed (§3.1):** "a test result `failed` in run R whose previous result for that test on the same branch was `passed`. When the branch has no previous result (a new PR branch), the test's latest result on the run's base branch before R is used. Tests flagged flaky or muted in the window are excluded."
- **Path units (§3.1):** "each changed path counts as itself and its parent folders up to 3 levels (`src/payment/api.py`, `src/payment/`, `src/`). When the run records a repository, units are prefixed with it (`repo-a:src/payment/`)."
- **Ignored changes (§3.1):** "lock files and generated or vendored paths (`*.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `dist/`, `build/`, `vendor/`, `node_modules/`) are not path units. A run whose change list the collector marked *truncated* is left out of the statistics. A change of more than 300 files counts at folder level only. Renames count under the new path; old history does not carry over in this release."
- **Rollup (§3.2):** "A compose job `impact-rollup` (like `analytics-rollup`) with a job heartbeat (`job_last_success_timestamp_seconds{job="impact_rollup"}`, an alert like the other jobs). Per project, over the last 90 days of runs with changed files, it writes: `impact_pairs (project_id, path_unit, test_key, changed_runs, new_failures, computed_at)` — only pairs with at least one new failure; `impact_test_base (project_id, test_key, runs, new_failures)` — each test's base rate. It replaces a project's rows in one transaction; re-running on the same day yields the same rows."
- **Scoring (§3.3):** "for each test, the best unit gives `confidence = new_failures / changed_runs` and `lift = confidence / base_rate`. A test is suggested when `changed_runs ≥ 3`, `new_failures ≥ 2` and `lift ≥ 2` (starting values, in one constants module). Order by confidence, then lift; at most 50 statistical suggestions. Always included, labelled, outside the cap: test files in the change (matched by path or file name), tests with no history, tests failing in the branch's latest run. "Not enough history" when the project has fewer than 20 runs with changed files in the window. Every scoring carries a model version, `stats-v1`."
- **Stored suggestion (§3.4):** "When a run with changed files is created, ingestion scores it **before** reading its results and stores `run_impact (run_id PK→test_runs CASCADE, suggested JSON, model_version, replayed bool, scored_at, caught JSON null, missed JSON null, evaluated_at null)`. The outcome (new failures caught and missed) is written when the run's last upload part arrives. A suggestion never sees its own run's results."
- **Endpoints (§3.5, project read access):**
  - `GET /api/v1/projects/{id}/runs/{run_id}/impact` → "the stored suggestion with evidence and its outcome, or the "no change data" / "not enough history" state".
  - `POST /api/v1/projects/{id}/analytics/impact` body `{changed_paths: [str], branch: str | null}` → "the same scoring for any change". "Limits: at most 5,000 paths, 1–1,000 characters each, no NUL; else 422."
  - `GET /api/v1/projects/{id}/analytics/impact-accuracy?days=7|14|30` → "caught, missed, the misses, and whether the figure includes replayed runs".
  - "Routing: these paths fall under the gateway's existing ingestion locations (`runs`, `analytics`)."
- **Replay (§3.6):** "`impact-rollup --backfill-days 30` (one-off): for each past run with changed files in the window, score with statistics built only from runs **before** it, store the suggestion with `replayed = true` and its real outcome. The accuracy figure reports replayed and live parts separately until live outcomes cover the window."
- **Retention, masking, performance (§3.7):** "The tables cascade from `test_runs` (run retention and legal hold apply) and are rebuilt by the rollup." "The rollup reads already-masked data only." "Budgets, measured on the existing 2M-result benchmark and recorded in the ingestion README: the rollup under 60 s per project; live scoring under 200 ms."
- **Run page card (§2.1):** "A card beside the existing Changes card".
  - Lines: "Suggested tests, strongest first. Each line: test name (link to its history) and its evidence, e.g. "newly failed in 4 of 6 runs that changed `src/payment/` (normally 3%)"".
  - Labels: "Always-included tests carry a label instead of statistics: *test file changed*, *no history yet*, *failing on this branch*."
  - Outcome: ""Suggested 12 tests · 3 newly failed · all 3 were suggested", or naming each new failure that was **missed**".
  - States: ""Not enough history yet: N runs with changed files, needs 20" (always-included tests still shown); "No change data for this run" (no changed files uploaded); loading; error with Retry."
  - "Replayed suggestions (§3.6) are marked *replayed*."
- **Run likely affected (§2.2):** "QEOS scores the branch's latest change (§3.5), maps suggested test keys to linked scenarios through the cases' `automated_test_key`, pre-selects them (the user can still edit the selection) and lists suggested tests with no linked case as "not runnable from QEOS (no linked case)". The existing duration estimate follows the selection."
- **Accuracy (§2.3):** ""Suggestions caught X% of new failures, last 30 days" (caught / (caught + missed), new failures in runs that had a stored suggestion), with the list of misses." "A **Test impact** section in the Report." "An Overview widget **Impact accuracy** (type `impact_accuracy`, setting `period` 7|14|30) added to the shared widget catalogue (`shared/qeos_shared/overview_widgets.json`), the server validation and the dashboard registry." "Replayed and live figures are distinguishable."
- **Dashboard (§4):** "one query and hook shared by the section and the widget, the widget's `staleKeys` declared in the registry." "DESIGN.md rules: status never by colour alone, tabular figures, own loading and error states. UI work starts with the `ui-ux-pro-max` skill."
- **Out of scope (§8):** "a learned model (next, once outcomes exist; no new infrastructure), embeddings and semantic similarity (Qdrant, Phase 6), coverage instrumentation, and skipping tests in CI. No TARGET technology is introduced."
- **Dashboard UI:** every task that edits a `.tsx` or `.css` file starts by invoking the `ui-ux-pro-max` skill and follows DESIGN.md. Colours come from `index.css` tokens only. lucide icons carry `aria-hidden="true"`. No `any`. Status is never shown by colour alone: a word or icon always goes with the hue (`StatusPill` does both).
- **Reuse, never duplicate:** `in_list` (`service/report_service.py`), `rank_flaky`, `rollup.rollup_inputs`/`has_rollups`, `analytics_service.flaky_inputs`/`muted_keys`, `as_utc`, `heartbeat.record_success`/`record_error`, `formatCount`, `formatPassRate`, `StatusPill`, `ErrorBanner`, `SkeletonStat`/`SkeletonStatus`, `WidgetEmpty`, `ReportFoot`, `reportLink`, `viewLink`, `ReportSection`, `useCiTarget`, `searchCases`, `listRuns`, `useDurationEstimate`.
- **Docs:** every behaviour commit updates the `.md` files it affects. Edit `.md` files with the Edit tool (or Python reading and writing UTF-8), with LF line endings, never PowerShell `Set-Content`.
- **Commands** (from the repository root; Git Bash):
  - Python, one service at a time, serially (each suite owns a temporary SQLite directory; never two suites of one service at once): `cd platforms/<svc> && SECRET_KEY=test .venv/Scripts/python -m pytest -q`. One file: append its path, for example `... -m pytest tests/unit/test_impact_rules.py -q`.
  - Shared package: `cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests -q`.
  - Dashboard: `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build`. One file: `npx vitest run <path>`.
  - Architecture docs check (CI job `docs`): `python scripts/check_architecture_docs.py && python -m pytest scripts/tests -q`.
- **Git:** work on `master`. Commit only your own paths: `git add <paths> && git commit -m "<msg>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- <paths>`. Never `git add -A`.
  - Shell scripts stay `100755`. On Windows, `git commit -- <path>` drops the executable bit. So a commit that touches `scripts/smoke_gateway.sh` stages it, runs `git update-index --chmod=+x scripts/smoke_gateway.sh`, checks `git diff --cached --name-only`, and commits the index without a pathspec.
  - Push direct to `master` only at a phase gate, after every gate step is green.

## Rulings

Decisions the spec leaves open or gets wrong against the code. Each is repeated in its task.

1. **No server-side upload parts:** each collector part is its own run, with its own POST, its own `-part-N` Idempotency-Key and the same `changes`. So "the run's last upload part" is the POST that creates the run, and each part gets its own suggestion and outcome.
2. **Upload order:** the suggestion is scored before the run row is added, so it can see neither the run nor its results, and it is stored in the upload's transaction. The outcome is computed after the response by a background task from the stored results. A failing scoring or outcome never fails the upload (it is logged as `impact_failed`, type only).
3. **Path units:** the path itself and its nearest parent folders, at most 3 (`a/b/c/d/e.py` → `a/b/c/d/e.py`, `a/b/c/d/`, `a/b/c/`, `a/b/`). Empty segments are dropped.
4. **Repository prefix:** `test_runs` records no repository today; components name repos under test, not the changed one. `path_units` takes an optional `repository`, and every caller passes `None` until the collector sends one.
5. **Ignored rules:** folder rules match a folder segment anywhere in the path, and file rules match the file name. ">300 files" counts the change's distinct uploaded paths, ignored ones included.
6. **Flaky** = `rank_flaky` with the Flaky view's defaults (`min_runs` 5, `min_flip_rate` 0.3, no limit) over the window. It reads the daily rollups when the project has them, as `GET /analytics/flaky` does. **Muted** = `muted_tests`.
7. **Failing** means `failed` or `errored`, QEOS's failing statuses everywhere. A run's outcome for a test is its last attempt (highest id) among non-skipped results. The previous result is the previous outcome on the same branch (a null branch is its own branch) within the 90 days before the run.
8. **Base branch** = `base_branch`, else `change_base_ref` without `origin/`. A `<sha>^` ref (a single-commit diff) or the run's own branch means there is none.
9. **`impact_test_base` also stores `flaky`, `suite`, `class_name`, `name`, `file`, `computed_at`,** with one row for every test that ran (non-skipped) in the window's change runs. Live scoring then never scans `test_results` for names, test files or flaky flags.
10. **"Tests with no history"** = base rows with `runs < 3`. A test the rollup has not seen cannot be named before results exist. Each label lists at most 100 tests (`MAX_PER_LABEL`), by name.
11. **Precedence and ties:** each test is listed once, in this order: statistical, then *test file changed*, then *failing on this branch*, then *no history yet*. Per test, the best unit is the one with the highest confidence, then lift, then changed runs, then the longer unit. Across tests the order is confidence, then lift, then name.
12. **Test file match:** the test's recorded `file` and a changed path match when one ends the other at a `/`, so a bare file name matches. Backslashes in the recorded file are normalised.
13. **Replay:**
    - Statistics and the history count come from runs started before the run's UTC day; *failing on this branch* comes from runs before the run itself.
    - Flaky and muted are taken as known at replay time.
    - Runs that already have a row are skipped, so live rows are never replaced and a rerun adds nothing.
    - A backfill writes no heartbeat (it is not the nightly pass), and `--loop` is refused with it. Days must be 1–90.
14. **Rollup schedule and window:**
    - The window runs from 90 days before today 00:00 UTC up to the pass's moment.
    - Projects visited: those with runs plus those with statistics, so a project whose runs are gone loses its rows.
    - "Nightly" = every 24 h from container start (no fixed hour); lock id `7351004`. JobStale fires at 2 × 24 h.
15. **Cascade:** only `run_impact` cascades from `test_runs`. `impact_pairs` and `impact_test_base` are per project and rebuilt from surviving runs at the next pass (spec §3.7 says "the tables cascade").
16. **Truncated runs** are left out of the statistics and the history count. They still get a stored suggestion and outcome, because their user sees the card.
17. **GET run impact:**
    - It adds `changed_paths` to the answer (Play needs them) and a `not_scored` state, for a run with changed files but no row: uploaded before this release, or scoring failed.
    - The run page shows the card whenever the run reported changes (`change_base_ref` not null).
    - The outcome may be pending (`outcome: null`); the card then says "outcome not recorded yet".
18. **POST /analytics/impact** needs at least one path (422 for `[]`) and applies "not enough history" too. It answers the suggestion with `model_version`.
19. **Accuracy response:**
    - It carries totals plus `live` and `replayed` parts (`runs`, `caught`, `missed`). `rate` is null when there were no new failures.
    - Misses are listed newest run first, at most 50, with `misses_total`.
    - `days` outside 7|14|30 is a 422 after the role check.
20. **Accuracy query key** = `["report", projectId, "impact-accuracy", days]`, so the Report's Refresh covers it. The widget still declares `staleKeys`, which `newRunStaleKeys` folds into the page's `["report", id]`.
21. **Report section window:** the Report's period when it is 7, 14 or 30 days ending today, else 30. Branch and other filters do not apply, and the section's note says so. `ReportSection` becomes generic over its data, with an optional `gate`, `isEmpty` and `emptyText`.
22. **Play placement:** no branch Play dialog exists; Play runs on the CI target's ref from the Cases selection bar, suites, features and case detail. So:
    - **Run likely affected** is a Cases-page header button for editors. It opens an inline panel whose branch field defaults to the CI target's ref.
    - The panel replaces the Cases selection with the linked cases. The selection bar, its Run dialog and the duration estimate follow that selection.
    - Unlinked suggestions are listed in the panel.
23. **"The branch's latest change"** = the newest of the branch's last 20 runs with changed files. Its paths come from `GET runs/{id}/impact` `changed_paths`, and `POST /analytics/impact` scores them now.
24. **Keys → cases** through `POST /cases/search` with `test_keys`, `keys_mode: include`:
    - archived cases are excluded, and test-management lowercases the keys;
    - pages of 200 (at most 5 pages);
    - cases are ordered by suggestion strength, and the selection is capped at 200 (`MAX_RUN_CASES`).
25. **The widget's empty state** (no run with a stored suggestion in the period) uses `WidgetEmpty` with Change settings. A null `rate` shows "—", never 0%.
26. **Run card details:** lists longer than 15 fold behind "Show all n". The outcome uses `StatusPill` ("All caught" in the passed tone, "Missed" in the failed tone), so status never rests on colour.
27. **Hash index on `impact_pairs.path_unit`**, and no unique constraint. A PostgreSQL btree entry over 2,704 bytes fails, and a 1,000-character path in multibyte UTF-8 passes that. Rows are written only by the rollup's replace.
28. **Docs per phase:** each behaviour task updates what it changes (ingestion README sections, TECHNICAL_SPECIFICATION, DESIGN, SETUP, catalogue counts). Task 19 completes PRODUCT, README features, SETUP "Test impact", ADR-029, INDEX, TODO, IMPLEMENTATION_PLAN and the blueprint banner.

## Review Focus

Inputs the spec implies but does not test, most likely to bite first. Each has a test in the owning task.

1. **The scoring raises at upload** (a database hiccup, an unexpected row): the upload must still answer 201 with its results stored, and no suggestion row. Task 7 `test_a_failing_scoring_never_fails_the_upload`.
2. **A late upload** (CI retried an old job, so its `started_at` is older than the branch's newest run): *failing on this branch* must come from the runs before it, not the newest. Task 7 `test_a_late_upload_reads_the_branch_as_it_was_before_the_run`.
3. **A test retried inside one run** (failed, then passed on retry): its outcome is the last attempt, so it neither newly fails nor counts as the previous failure. Task 4 `test_the_last_attempt_is_the_outcome`.
4. **A change made only of ignored or blank paths** (`poetry.lock`, `/`): the endpoint answers 200 with labels only, never a 500 or a 422. Task 9 `test_a_change_of_only_ignored_files_answers_with_labels_only`.
5. **A collector retry of the same upload** (same Idempotency-Key): no second scoring and no second row. Task 7 `test_a_replayed_upload_is_not_scored_again`.

---

## File map

**ingestion-service** (`platforms/ingestion-service/`):
- Create:
  - `alembic/versions/018_test_impact.py`;
  - `src/ingestion/models/impact.py`;
  - `src/ingestion/analytics/impact_rules.py`, `src/ingestion/analytics/impact_score.py`;
  - services `src/ingestion/service/impact_history.py`, `impact_stats.py`, `impact_service.py`, `impact_replay.py`, `impact_read.py`;
  - `src/ingestion/jobs/impact_rollup.py`;
  - `src/ingestion/schemas/impact.py`;
  - tests `tests/unit/test_impact_rules.py`, `tests/unit/test_impact_score.py`, `tests/integration/test_impact_newly_failed.py`, `tests/integration/test_impact_rollup.py`, `tests/integration/test_impact_upload.py`, `tests/integration/test_impact_replay.py`, `tests/integration/test_impact_endpoints.py`.
- Modify:
  - `src/ingestion/models/__init__.py`;
  - `src/ingestion/jobs/heartbeat.py`;
  - `src/ingestion/service/ingest_service.py`;
  - endpoints `src/ingestion/api/v1/endpoints/collect.py`, `runs.py`, `analytics.py`;
  - tests `tests/conftest.py`, `tests/unit/test_migration.py`, `tests/integration/test_heartbeat_metrics.py`;
  - `README.md`.

**Stack, monitoring, scripts:**
- Modify:
  - compose files `docker-compose.yml`, `deploy/docker-compose.prod.yml`;
  - monitoring `monitoring/prometheus/alerts.yml`, `monitoring/prometheus/tests/alerts.test.yml`, `monitoring/grafana/dashboards/jobs-uploads.json`;
  - `scripts/smoke_gateway.sh` (stays `100755`).
- Create: `scripts/impact_benchmark.py`.
- The gateway is not changed.

**shared / project-service:** Modify `shared/qeos_shared/overview_widgets.json`, `shared/tests/test_overview_widgets.py`, `shared/README.md`, `platforms/project-service/tests/unit/test_overview_layout_validation.py`.

**dashboard** (`dashboard/src/`):
- Create:
  - `api/impact.ts`, `api/impact.test.ts`;
  - `lib/impactQueries.ts`, `lib/impactQueries.test.ts`, `lib/likelyAffected.ts`;
  - `components/ImpactCard.tsx`, `components/ImpactCard.test.tsx`, `components/LikelyAffectedPanel.tsx`;
  - `pages/report/sections/ImpactSection.tsx`, `pages/report/sections/ImpactSection.test.tsx`;
  - `overview/widgets/impactAccuracy.ts`, `overview/widgets/ImpactAccuracyWidget.tsx`, `overview/widgets/impactWidget.test.tsx`;
  - `pages/RunLikelyAffected.test.tsx`.
- Modify:
  - `test/server.ts`;
  - pages `pages/RunDetailPage.tsx`, `pages/RunDetailPage.test.tsx`, `pages/report/ReportSection.tsx`, `pages/report/ReportPage.tsx`, `pages/CasesPage.tsx`;
  - Overview `overview/catalog.ts`, `overview/catalog.test.ts`, `overview/widgets/registry.ts`;
  - `index.css`.

**Docs:**
- Modify:
  - `README.md`, `TECHNICAL_SPECIFICATION.md`, `DESIGN.md`, `PRODUCT.md`;
  - `docs/SETUP.md`, `TODO.md`, `IMPLEMENTATION_PLAN.md`;
  - `ARCHITECTURE_BLUEPRINT_V1_0.md`, `docs/architecture/adr/INDEX.md`.
- Create `docs/architecture/adr/ADR-029-test-impact-analysis.md`.

---

# Phase 1 — Analysis (ingestion-service)

At the end of this phase the statistics are rebuilt nightly, every upload with changed files stores its suggestion and outcome, history can be replayed, and the three endpoints answer through the gateway.

### Task 1: Migration 018 and the three models

**Files:**
- Create: `platforms/ingestion-service/alembic/versions/018_test_impact.py`
- Create: `platforms/ingestion-service/src/ingestion/models/impact.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/__init__.py`
- Test: `platforms/ingestion-service/tests/unit/test_migration.py`

**Interfaces:**
- Consumes: migration 017 (`down_revision = "017"`); `test_runs.id`.
- Produces, in `src.ingestion.models.impact`:
  - `ImpactPair`: table `impact_pairs`, columns `id: int PK`, `project_id: int`, `path_unit: str(1101)`, `test_key: str(64)`, `changed_runs: int`, `new_failures: int`, `computed_at: datetime tz`; indexes `ix_impact_pairs_project (project_id)`, `ix_impact_pairs_path_unit (path_unit)` (hash on PostgreSQL, Ruling 27).
  - `ImpactTestBase`: table `impact_test_base`, columns `id: int PK`, `project_id: int`, `test_key: str(64)`, `runs: int`, `new_failures: int`, `flaky: bool` (default false), `suite: str(500)`, `class_name: str(500)`, `name: str(1000)`, `file: str(1000) | None`, `computed_at: datetime tz`; unique `uq_impact_test_base (project_id, test_key)`.
  - `RunImpact`: table `run_impact`, columns `run_id: int PK FK test_runs.id ON DELETE CASCADE`, `suggested: JSON`, `model_version: str(20)`, `replayed: bool` (default false), `scored_at: datetime tz`, `caught: JSON | None`, `missed: JSON | None`, `evaluated_at: datetime tz | None`.
  - All three are exported from `src.ingestion.models`.

- [ ] **Step 1: Write the failing tests**

Append to `platforms/ingestion-service/tests/unit/test_migration.py`:

```python
def test_test_impact_tables(migrated_engine):
    """Migration 018 (spec 2026-10-12 §3.2, §3.4)."""
    inspector = inspect(migrated_engine)
    pair_indexes = {ix["name"]: ix["column_names"] for ix in inspector.get_indexes("impact_pairs")}
    assert pair_indexes["ix_impact_pairs_project"] == ["project_id"]
    assert pair_indexes["ix_impact_pairs_path_unit"] == ["path_unit"]
    base_unique = {uc["name"]: uc["column_names"] for uc in inspector.get_unique_constraints("impact_test_base")}
    assert base_unique["uq_impact_test_base"] == ["project_id", "test_key"]
    assert inspector.get_pk_constraint("run_impact")["constrained_columns"] == ["run_id"]
    (fk,) = inspector.get_foreign_keys("run_impact")
    assert (fk["referred_table"], fk["referred_columns"], fk["options"].get("ondelete")) == ("test_runs", ["id"], "CASCADE")


def test_model_declares_the_path_unit_hash_index():
    from src.ingestion.models.impact import ImpactPair

    index = next(ix for ix in ImpactPair.__table__.indexes if ix.name == "ix_impact_pairs_path_unit")
    assert index.dialect_options["postgresql"]["using"] == "hash"


def test_a_runs_stored_suggestion_goes_with_the_run(migrated_engine):
    """Retention and legal hold act on test_runs; the suggestion follows its run (spec §3.7)."""
    from sqlalchemy import event

    # SQLite enforces foreign keys only when asked, per connection
    event.listen(migrated_engine, "connect", lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"))
    migrated_engine.dispose()
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "d" * 64})
        conn.execute(text(RUN), {"idem": "impact", "provider": "local"})
        run_id = conn.execute(text("SELECT id FROM test_runs WHERE idempotency_key = 'impact'")).scalar()
        conn.execute(text("INSERT INTO run_impact (run_id, suggested, model_version, replayed, scored_at)"
                          " VALUES (:id, '{}', 'stats-v1', 0, '2026-10-12T00:00:00+00:00')"), {"id": run_id})
        conn.execute(text("DELETE FROM test_runs WHERE id = :id"), {"id": run_id})
        assert conn.execute(text("SELECT COUNT(*) FROM run_impact")).scalar() == 0


def test_test_impact_downgrade_drops_the_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_018.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "017")
    engine = create_engine(url)
    try:
        assert not {"impact_pairs", "impact_test_base", "run_impact"} & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py -q`
Expected: FAIL. `test_test_impact_tables` fails with `NoSuchTableError: impact_pairs`, and the model test fails with `ModuleNotFoundError: No module named 'src.ingestion.models.impact'`.

- [ ] **Step 3: Write the migration**

Create `platforms/ingestion-service/alembic/versions/018_test_impact.py`:

```python
"""test impact analysis: impact_pairs, impact_test_base, run_impact

impact_pairs and impact_test_base are rebuilt per project by the impact-rollup job; run_impact holds the suggestion
stored with an uploaded run and its outcome, and goes with its run (spec 2026-10-12 §3.2, §3.4, plan Ruling 15).
impact_pairs.path_unit has a hash index, not a btree: a btree entry over 2,704 bytes fails, and a 1,000-character
path in multibyte UTF-8 passes that (plan Ruling 27).

Revision ID: 018
Revises: 017
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "impact_pairs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("path_unit", sa.String(length=1101), nullable=False),
        sa.Column("test_key", sa.String(length=64), nullable=False),
        sa.Column("changed_runs", sa.Integer(), nullable=False),
        sa.Column("new_failures", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_impact_pairs_project", "impact_pairs", ["project_id"])
    op.create_index("ix_impact_pairs_path_unit", "impact_pairs", ["path_unit"], postgresql_using="hash")
    op.create_table(
        "impact_test_base",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("test_key", sa.String(length=64), nullable=False),
        sa.Column("runs", sa.Integer(), nullable=False),
        sa.Column("new_failures", sa.Integer(), nullable=False),
        sa.Column("flaky", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suite", sa.String(length=500), nullable=False),
        sa.Column("class_name", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=1000), nullable=False),
        sa.Column("file", sa.String(length=1000), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "test_key", name="uq_impact_test_base"),
    )
    op.create_table(
        "run_impact",
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("test_runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("suggested", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(length=20), nullable=False),
        sa.Column("replayed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("caught", sa.JSON(), nullable=True),
        sa.Column("missed", sa.JSON(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("run_impact")
    op.drop_table("impact_test_base")
    op.drop_index("ix_impact_pairs_path_unit", table_name="impact_pairs")
    op.drop_index("ix_impact_pairs_project", table_name="impact_pairs")
    op.drop_table("impact_pairs")
```

- [ ] **Step 4: Write the models**

Create `platforms/ingestion-service/src/ingestion/models/impact.py`:

```python
"""Test impact analysis (spec docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md §3, migration 018).

impact_pairs and impact_test_base are rebuilt per project by the impact-rollup job; run_impact holds the suggestion
stored with an uploaded run, and its outcome."""
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, false

from src.ingestion.db.base import Base

PATH_UNIT_LENGTH = 1101  # a 100-character repository, ":", and a 1,000-character path


class ImpactPair(Base):
    """How often a test newly failed in the window's runs that changed one path unit (pairs with at least one)."""

    __tablename__ = "impact_pairs"
    __table_args__ = (
        Index("ix_impact_pairs_project", "project_id"),
        # Hash, not btree: a btree entry over 2,704 bytes fails (plan Ruling 27)
        Index("ix_impact_pairs_path_unit", "path_unit", postgresql_using="hash"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False)
    path_unit = Column(String(PATH_UNIT_LENGTH), nullable=False)
    test_key = Column(String(64), nullable=False)
    changed_runs = Column(Integer, nullable=False)  # the window's runs that changed the unit
    new_failures = Column(Integer, nullable=False)  # of those, the runs where the test newly failed
    computed_at = Column(DateTime(timezone=True), nullable=False)


class ImpactTestBase(Base):
    """One test's base rate over the window's runs with changed files, plus what scoring reads (plan Ruling 9)."""

    __tablename__ = "impact_test_base"
    __table_args__ = (UniqueConstraint("project_id", "test_key", name="uq_impact_test_base"),)

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False)
    test_key = Column(String(64), nullable=False)
    runs = Column(Integer, nullable=False)          # change runs with a non-skipped result of the test
    new_failures = Column(Integer, nullable=False)  # change runs where it newly failed
    flaky = Column(Boolean, nullable=False, default=False, server_default=false())
    suite = Column(String(500), nullable=False)
    class_name = Column(String(500), nullable=False)
    name = Column(String(1000), nullable=False)
    file = Column(String(1000), nullable=True)      # the test's file as the collector recorded it
    computed_at = Column(DateTime(timezone=True), nullable=False)


class RunImpact(Base):
    """The suggestion stored with an uploaded (or replayed) run, and its outcome once evaluated."""

    __tablename__ = "run_impact"

    run_id = Column(Integer, ForeignKey("test_runs.id", ondelete="CASCADE"), primary_key=True)
    suggested = Column(JSON, nullable=False)
    model_version = Column(String(20), nullable=False)
    replayed = Column(Boolean, nullable=False, default=False, server_default=false())
    scored_at = Column(DateTime(timezone=True), nullable=False)
    caught = Column(JSON, nullable=True)   # [{test_key, suite, class_name, name}]
    missed = Column(JSON, nullable=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=True)
```

In `platforms/ingestion-service/src/ingestion/models/__init__.py`, with the Edit tool, replace:

```python
from src.ingestion.models.component import RunComponent
```

with:

```python
from src.ingestion.models.component import RunComponent
from src.ingestion.models.impact import ImpactPair, ImpactTestBase, RunImpact
```

and replace:

```python
__all__ = ["ApiKey", "FlakyDaily", "FlakyRollupDay", "JobHeartbeat", "MaskingPattern", "MutedTest", "NotificationChannel", "Run", "RunChangedFile", "RunComponent", "RunResult"]
```

with:

```python
__all__ = ["ApiKey", "FlakyDaily", "FlakyRollupDay", "ImpactPair", "ImpactTestBase", "JobHeartbeat", "MaskingPattern", "MutedTest",
           "NotificationChannel", "Run", "RunChangedFile", "RunComponent", "RunImpact", "RunResult"]
```

- [ ] **Step 5: Run the migration tests and the whole suite**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py -q`
Expected: PASS. `test_migration_columns_match_models` now also covers the three new tables.

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add platforms/ingestion-service/alembic/versions/018_test_impact.py platforms/ingestion-service/src/ingestion/models/impact.py platforms/ingestion-service/src/ingestion/models/__init__.py platforms/ingestion-service/tests/unit/test_migration.py
git commit -m "feat(ingestion): migration 018 for test impact (impact_pairs, impact_test_base, run_impact)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/alembic/versions/018_test_impact.py platforms/ingestion-service/src/ingestion/models/impact.py platforms/ingestion-service/src/ingestion/models/__init__.py platforms/ingestion-service/tests/unit/test_migration.py
```

No `.md` changes in this commit: the README section arrives with the job in Task 5, which is the first behaviour that writes these tables.

---

### Task 2: Definitions: path units, ignored changes, base branch, test files

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/analytics/impact_rules.py`
- Test: `platforms/ingestion-service/tests/unit/test_impact_rules.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in `src.ingestion.analytics.impact_rules`:
  - **Constants:** `MODEL_VERSION = "stats-v1"`, `WINDOW_DAYS = 90`, `FOLDER_LEVELS = 3`, `FOLDER_ONLY_ABOVE = 300`, `MIN_CHANGED_RUNS = 3`, `MIN_NEW_FAILURES = 2`, `MIN_LIFT = 2.0`, `MAX_STATISTICAL = 50`, `MIN_HISTORY_RUNS = 20`, `MAX_PER_LABEL = 100`, `FLAKY_MIN_RUNS = 5`, `FLAKY_MIN_FLIP_RATE = 0.3`, `FAILING = ("failed", "errored")`.
  - **Functions:**
    - `is_ignored(path: str) -> bool`;
    - `path_units(path: str, *, folders_only: bool = False, repository: Optional[str] = None) -> List[str]`;
    - `change_units(paths: Iterable[str], repository: Optional[str] = None) -> Set[str]`;
    - `base_branch_of(branch: Optional[str], base_branch: Optional[str], change_base_ref: Optional[str]) -> Optional[str]`;
    - `suffixes(path: str) -> List[str]`.
  - **Class** `ChangedFiles(paths: Iterable[str])` with `.paths: Set[str]` and `.touches(test_file: Optional[str]) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `platforms/ingestion-service/tests/unit/test_impact_rules.py`:

```python
"""Test impact definitions (spec 2026-10-12 §3.1; plan Rulings 3, 4, 5, 8, 12)."""
import pytest

from src.ingestion.analytics.impact_rules import (
    FOLDER_ONLY_ABOVE, ChangedFiles, base_branch_of, change_units, is_ignored, path_units,
)


def test_a_path_counts_as_itself_and_its_parent_folders():
    assert path_units("src/payment/api.py") == ["src/payment/api.py", "src/payment/", "src/"]


def test_at_most_three_parent_folders_the_nearest_ones():
    assert path_units("a/b/c/d/e.py") == ["a/b/c/d/e.py", "a/b/c/d/", "a/b/c/", "a/b/"]


def test_a_file_at_the_root_is_only_itself():
    assert path_units("README.md") == ["README.md"]


def test_empty_segments_are_dropped():
    assert path_units("/src//payment/api.py") == ["src/payment/api.py", "src/payment/", "src/"]


def test_a_repository_prefixes_every_unit():
    assert path_units("src/payment/api.py", repository="repo-a") == [
        "repo-a:src/payment/api.py", "repo-a:src/payment/", "repo-a:src/"]


def test_folders_only_leaves_the_file_out():
    assert path_units("src/payment/api.py", folders_only=True) == ["src/payment/", "src/"]


@pytest.mark.parametrize("path", [
    "poetry.lock", "web/package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock",
    "web/dist/app.js", "build/x.o", "vendor/lib/a.go", "web/node_modules/left-pad/index.js", "/",
])
def test_lock_files_generated_or_vendored_and_blank_paths_are_ignored(path):
    assert is_ignored(path)


@pytest.mark.parametrize("path", ["src/build.py", "docs/distribution.md", "src/vendor.py", "lockfile.txt", "dist"])
def test_lookalikes_are_kept(path):
    assert not is_ignored(path)


def test_change_units_leave_ignored_paths_out():
    assert change_units(["src/a.py", "poetry.lock", "node_modules/x/y.js", "/"]) == {"src/a.py", "src/"}


def test_a_change_of_more_than_300_files_counts_at_folder_level_only():
    units = change_units([f"src/mod{i}/f.py" for i in range(FOLDER_ONLY_ABOVE + 1)])
    assert "src/mod0/f.py" not in units and {"src/mod0/", "src/"} <= units


def test_a_change_of_exactly_300_files_keeps_its_files():
    assert "src/mod0/f.py" in change_units([f"src/mod{i}/f.py" for i in range(FOLDER_ONLY_ABOVE)])


def test_ignored_paths_still_count_toward_the_300():
    paths = [f"vendor/lib{i}.go" for i in range(FOLDER_ONLY_ABOVE)] + ["src/pay/api.py"]
    assert change_units(paths) == {"src/pay/", "src/"}


@pytest.mark.parametrize("branch, base_branch, change_base_ref, expected", [
    ("feature/x", "main", "origin/main", "main"),
    ("feature/x", None, "origin/develop", "develop"),
    ("main", None, "abc1234^", None),
    ("main", "main", "origin/main", None),
    ("feature/x", None, None, None),
])
def test_the_base_branch(branch, base_branch, change_base_ref, expected):
    assert base_branch_of(branch, base_branch, change_base_ref) == expected


def test_a_test_file_matches_when_one_path_ends_the_other():
    files = ChangedFiles(["tests/test_pay.py", "src/pay/api.py"])
    assert files.touches("tests/test_pay.py")
    assert files.touches("web/tests/test_pay.py")  # recorded from another checkout root
    assert files.touches("test_pay.py")            # a file name alone
    assert files.touches("tests\\test_pay.py")     # Windows separators
    assert ChangedFiles(["web/tests/test_pay.py"]).touches("tests/test_pay.py")
    assert not files.touches("tests/test_cart.py")
    assert not files.touches("other/test_pay.py")
    assert not files.touches(None) and not files.touches("")
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_impact_rules.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.ingestion.analytics.impact_rules'`.

- [ ] **Step 3: Write the module**

Create `platforms/ingestion-service/src/ingestion/analytics/impact_rules.py`:

```python
"""Test impact analysis: the definitions and starting values (spec 2026-10-12 §3.1, §3.3). Pure: no database.

Every threshold is here, so tuning them is one file and one review."""
from typing import Iterable, List, Optional, Set

MODEL_VERSION = "stats-v1"
WINDOW_DAYS = 90             # statistics, history counts and "previous result" read the 90 days before
FOLDER_LEVELS = 3            # parent folders per changed path, the nearest ones (plan Ruling 3)
FOLDER_ONLY_ABOVE = 300      # a change of more distinct paths counts at folder level only
MIN_CHANGED_RUNS = 3
MIN_NEW_FAILURES = 2
MIN_LIFT = 2.0
MAX_STATISTICAL = 50
MIN_HISTORY_RUNS = 20        # runs with changed files in the window before statistics are used
MAX_PER_LABEL = 100          # always-included tests listed per label (plan Ruling 10)
FLAKY_MIN_RUNS = 5           # the Flaky view's defaults (plan Ruling 6)
FLAKY_MIN_FLIP_RATE = 0.3
FAILING = ("failed", "errored")

IGNORED_NAMES = frozenset({"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"})
IGNORED_SUFFIX = ".lock"
IGNORED_FOLDERS = frozenset({"dist", "build", "vendor", "node_modules"})


def _parts(path: str) -> List[str]:
    return [part for part in path.split("/") if part]


def is_ignored(path: str) -> bool:
    """Lock files by name, generated or vendored folders anywhere in the path (plan Ruling 5), and blank paths."""
    parts = _parts(path)
    if not parts:
        return True
    name = parts[-1]
    return name in IGNORED_NAMES or name.endswith(IGNORED_SUFFIX) or any(part in IGNORED_FOLDERS for part in parts[:-1])


def path_units(path: str, *, folders_only: bool = False, repository: Optional[str] = None) -> List[str]:
    """The path itself (unless folders_only) and its nearest parent folders, at most FOLDER_LEVELS, each ending in "/".
    Every unit is prefixed "<repository>:" when a repository is given (plan Ruling 4)."""
    parts = _parts(path)
    units = [] if folders_only or not parts else ["/".join(parts)]
    for depth in range(len(parts) - 1, max(0, len(parts) - 1 - FOLDER_LEVELS), -1):
        units.append("/".join(parts[:depth]) + "/")
    prefix = f"{repository}:" if repository else ""
    return [prefix + unit for unit in units]


def change_units(paths: Iterable[str], repository: Optional[str] = None) -> Set[str]:
    """The path units of one change: ignored paths add none; more than FOLDER_ONLY_ABOVE distinct paths count at
    folder level only."""
    distinct = set(paths)
    folders_only = len(distinct) > FOLDER_ONLY_ABOVE
    units: Set[str] = set()
    for path in distinct:
        if not is_ignored(path):
            units.update(path_units(path, folders_only=folders_only, repository=repository))
    return units


def base_branch_of(branch: Optional[str], base_branch: Optional[str], change_base_ref: Optional[str]) -> Optional[str]:
    """The branch a run's change goes into (plan Ruling 8): the PR base, else the diff's base ref without "origin/".
    "<sha>^" (a single-commit diff) and the run's own branch mean none."""
    candidate = base_branch or change_base_ref or ""
    if candidate.startswith("origin/"):
        candidate = candidate[len("origin/"):]
    if not candidate or candidate.endswith("^") or candidate == branch:
        return None
    return candidate


def suffixes(path: str) -> List[str]:
    """"a/b/c.py" -> ["a/b/c.py", "b/c.py", "c.py"]; backslashes count as separators."""
    parts = _parts(path.replace("\\", "/"))
    return ["/".join(parts[i:]) for i in range(len(parts))]


class ChangedFiles:
    """The change's paths, for "test file changed" (plan Ruling 12): a test's recorded file matches a changed path when
    one ends the other at a "/" (checkouts differ in their root), so a bare file name matches any path ending in it."""

    def __init__(self, paths: Iterable[str]) -> None:
        self.paths: Set[str] = {"/".join(_parts(path)) for path in paths} - {""}
        self._endings: Set[str] = {ending for path in self.paths for ending in suffixes(path)}

    def touches(self, test_file: Optional[str]) -> bool:
        if not test_file:
            return False
        endings = suffixes(test_file)
        return bool(endings) and (endings[0] in self._endings or any(ending in self.paths for ending in endings))
```

- [ ] **Step 4: Run the tests**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_impact_rules.py -q`
Expected: PASS (all of them).

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/analytics/impact_rules.py platforms/ingestion-service/tests/unit/test_impact_rules.py
git commit -m "feat(ingestion): test impact definitions (path units, ignored changes, base branch, test files)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/analytics/impact_rules.py platforms/ingestion-service/tests/unit/test_impact_rules.py
```

---

### Task 3: Scoring a change (pure)

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/analytics/impact_score.py`
- Test: `platforms/ingestion-service/tests/unit/test_impact_score.py`

**Interfaces:**
- Consumes (Task 2): `MAX_PER_LABEL`, `MAX_STATISTICAL`, `MIN_CHANGED_RUNS`, `MIN_HISTORY_RUNS`, `MIN_LIFT`, `MIN_NEW_FAILURES`, `ChangedFiles`.
- Produces, in `src.ingestion.analytics.impact_score`:
  - **Kinds:** `STATISTICAL = "statistical"`, `TEST_FILE_CHANGED = "test_file_changed"`, `FAILING_ON_BRANCH = "failing_on_branch"`, `NO_HISTORY = "no_history"`.
  - **Dataclasses** (all frozen):
    - `ImpactTest(test_key: str, suite: str, class_name: str, name: str)` with `.out() -> dict` (those four keys);
    - `PairStat(path_unit: str, test_key: str, changed_runs: int, new_failures: int)`;
    - `BaseStat(test: ImpactTest, runs: int, new_failures: int, file: Optional[str], flaky: bool)` with property `.rate -> float`.
  - **Functions:**
    - `evidence(pair: PairStat, base: BaseStat) -> Optional[dict]`, giving `{path_unit, changed_runs, new_failures, confidence, lift, base_rate}` (rounded to 4 places);
    - `suggest(units: Iterable[str], pairs: Iterable[PairStat], bases: Mapping[str, BaseStat], *, history_runs: int, changed_files: ChangedFiles, failing_on_branch: Iterable[ImpactTest]) -> dict`.
  - **The suggestion dict:** `{"state": "ok" | "not_enough_history", "history_runs": int, "needed_runs": int, "statistical_total": int, "tests": [{test_key, suite, class_name, name, kind, evidence: dict | None}]}`.
  - `suggest` reads `MIN_HISTORY_RUNS` as a module global, so tests may `monkeypatch.setattr(impact_score, "MIN_HISTORY_RUNS", n)`.

- [ ] **Step 1: Write the failing tests**

Create `platforms/ingestion-service/tests/unit/test_impact_score.py`:

```python
"""Scoring a change (spec 2026-10-12 §3.3): thresholds at their edges, ordering, the cap, each label (plan Rulings 10, 11)."""
import pytest

from src.ingestion.analytics.impact_rules import MAX_PER_LABEL, MAX_STATISTICAL, MIN_HISTORY_RUNS, ChangedFiles
from src.ingestion.analytics.impact_score import BaseStat, ImpactTest, PairStat, evidence, suggest

UNITS = {"src/pay/api.py", "src/pay/", "src/"}


def key(name):
    return name.ljust(64, "0")


def named(name):
    return ImpactTest(key(name), "s", "C", name)


def base(name, runs=40, new_failures=10, file=None, flaky=False):
    return BaseStat(named(name), runs, new_failures, file, flaky)


def pair(name, unit="src/pay/", changed_runs=4, new_failures=2):
    return PairStat(unit, key(name), changed_runs, new_failures)


def score(pairs=(), bases=(), history=MIN_HISTORY_RUNS, paths=("src/pay/api.py",), failing=(), units=UNITS):
    return suggest(units, list(pairs), {b.test.test_key: b for b in bases}, history_runs=history,
                   changed_files=ChangedFiles(paths), failing_on_branch=list(failing))


def kinds(result):
    return [(t["name"], t["kind"]) for t in result["tests"]]


@pytest.mark.parametrize("changed_runs, expected", [(2, None), (3, 0.6667)])
def test_changed_runs_must_be_at_least_3(changed_runs, expected):
    found = evidence(pair("pays", changed_runs=changed_runs), base("pays"))
    assert (found and found["confidence"]) == expected


@pytest.mark.parametrize("new_failures, kept", [(1, False), (2, True)])
def test_new_failures_must_be_at_least_2(new_failures, kept):
    found = evidence(pair("pays", changed_runs=6, new_failures=new_failures), base("pays", runs=100, new_failures=1))
    assert (found is not None) is kept


@pytest.mark.parametrize("base_runs, kept", [(38, False), (40, True)])  # lift 1.9, then exactly 2
def test_lift_must_be_at_least_2(base_runs, kept):
    assert (evidence(pair("pays"), base("pays", runs=base_runs, new_failures=10)) is not None) is kept


def test_the_evidence_holds_what_the_card_shows():
    assert evidence(pair("pays"), base("pays")) == {
        "path_unit": "src/pay/", "changed_runs": 4, "new_failures": 2, "confidence": 0.5, "lift": 2.0, "base_rate": 0.25}


def test_each_test_takes_its_best_unit_of_the_change():
    pairs = [pair("pays", "src/", changed_runs=10, new_failures=3), pair("pays", "src/pay/"),
             pair("pays", "lib/", changed_runs=3, new_failures=3)]  # lib/ is not a unit of this change
    assert [t["evidence"]["path_unit"] for t in score(pairs, [base("pays")])["tests"]] == ["src/pay/"]


def test_a_tie_goes_to_the_more_specific_unit():
    result = score([pair("pays", "src/"), pair("pays", "src/pay/")], [base("pays")])
    assert result["tests"][0]["evidence"]["path_unit"] == "src/pay/"


def test_strongest_first_by_confidence_then_lift_then_name():
    pairs = [pair("b_lower_lift"), pair("a_lower_lift"), pair("strong", changed_runs=3, new_failures=3), pair("c_higher_lift")]
    bases = [base("b_lower_lift"), base("a_lower_lift"), base("strong"), base("c_higher_lift", runs=80)]
    assert [t["name"] for t in score(pairs, bases)["tests"]] == ["strong", "c_higher_lift", "a_lower_lift", "b_lower_lift"]


def test_at_most_50_statistical_suggestions():
    names = [f"t{i:03d}" for i in range(MAX_STATISTICAL + 10)]
    result = score([pair(n) for n in names], [base(n) for n in names])
    assert len(result["tests"]) == MAX_STATISTICAL and result["statistical_total"] == MAX_STATISTICAL + 10


def test_a_flaky_test_is_never_suggested_from_statistics():
    assert score([pair("pays")], [base("pays", flaky=True)])["tests"] == []


def test_not_enough_history_leaves_statistics_out_but_keeps_the_labels():
    result = score([pair("pays")], [base("pays"), base("brand_new", runs=1, new_failures=0)], history=MIN_HISTORY_RUNS - 1)
    assert (result["state"], result["history_runs"], result["needed_runs"]) == (
        "not_enough_history", MIN_HISTORY_RUNS - 1, MIN_HISTORY_RUNS)
    assert kinds(result) == [("brand_new", "no_history")]


def test_each_label_outside_the_cap_and_each_test_once():
    names = [f"t{i:03d}" for i in range(MAX_STATISTICAL)]
    bases = [base(n) for n in names] + [base("pay_spec", runs=9, new_failures=0, file="tests/pay_spec.py"),
                                        base("brand_new", runs=2, new_failures=0), base("fresh", runs=1, new_failures=0)]
    failing = [named("cart"), named("t000")]  # t000 is already a statistical suggestion
    result = score([pair(n) for n in names], bases, paths=("src/pay/api.py", "tests/pay_spec.py"), failing=failing)
    assert kinds(result)[MAX_STATISTICAL:] == [("pay_spec", "test_file_changed"), ("cart", "failing_on_branch"),
                                               ("brand_new", "no_history"), ("fresh", "no_history")]
    assert len({t["test_key"] for t in result["tests"]}) == len(result["tests"])


def test_each_label_lists_at_most_100_tests():
    bases = [base(f"new{i:03d}", runs=0, new_failures=0) for i in range(MAX_PER_LABEL + 20)]
    assert len(score(bases=bases)["tests"]) == MAX_PER_LABEL


def test_the_whole_answer():
    assert score([pair("pays")], [base("pays")]) == {
        "state": "ok", "history_runs": MIN_HISTORY_RUNS, "needed_runs": MIN_HISTORY_RUNS, "statistical_total": 1,
        "tests": [{"test_key": key("pays"), "suite": "s", "class_name": "C", "name": "pays", "kind": "statistical",
                   "evidence": {"path_unit": "src/pay/", "changed_runs": 4, "new_failures": 2, "confidence": 0.5,
                                "lift": 2.0, "base_rate": 0.25}}],
    }
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_impact_score.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.ingestion.analytics.impact_score'`.

- [ ] **Step 3: Write the module**

Create `platforms/ingestion-service/src/ingestion/analytics/impact_score.py`:

```python
"""Scoring a change against the impact statistics (spec 2026-10-12 §3.3). Pure: the services load the rows.

For each test, the change's best path unit gives confidence = new_failures / changed_runs and lift = confidence /
base rate. A test is suggested when changed_runs >= 3, new_failures >= 2 and lift >= 2, strongest first, at most 50.
Tests whose file changed, that fail on the branch, or that have no history yet are always included, labelled,
outside that cap, each test once (plan Ruling 11). Below 20 runs with changed files in the window, statistics are
not used at all."""
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional

from src.ingestion.analytics.impact_rules import (
    MAX_PER_LABEL, MAX_STATISTICAL, MIN_CHANGED_RUNS, MIN_HISTORY_RUNS, MIN_LIFT, MIN_NEW_FAILURES, ChangedFiles,
)

STATISTICAL = "statistical"
TEST_FILE_CHANGED = "test_file_changed"
FAILING_ON_BRANCH = "failing_on_branch"
NO_HISTORY = "no_history"


@dataclass(frozen=True)
class ImpactTest:
    """A test by key and name. (Not named Test...: pytest would try to collect it.)"""

    test_key: str
    suite: str
    class_name: str
    name: str

    def out(self) -> dict:
        return {"test_key": self.test_key, "suite": self.suite, "class_name": self.class_name, "name": self.name}


@dataclass(frozen=True)
class PairStat:
    path_unit: str
    test_key: str
    changed_runs: int
    new_failures: int


@dataclass(frozen=True)
class BaseStat:
    test: ImpactTest
    runs: int
    new_failures: int
    file: Optional[str]
    flaky: bool

    @property
    def rate(self) -> float:
        return self.new_failures / self.runs if self.runs else 0.0


def evidence(pair: PairStat, base: BaseStat) -> Optional[dict]:
    """The pair's evidence when it passes all three thresholds, else None."""
    if pair.changed_runs < MIN_CHANGED_RUNS or pair.new_failures < MIN_NEW_FAILURES or base.rate <= 0:
        return None
    confidence = pair.new_failures / pair.changed_runs
    lift = confidence / base.rate
    if lift < MIN_LIFT:
        return None
    return {"path_unit": pair.path_unit, "changed_runs": pair.changed_runs, "new_failures": pair.new_failures,
            "confidence": round(confidence, 4), "lift": round(lift, 4), "base_rate": round(base.rate, 4)}


def _strength(found: dict) -> tuple:
    # Ties: more changed runs, then the more specific (longer) unit, then the unit itself for a stable answer
    return (found["confidence"], found["lift"], found["changed_runs"], len(found["path_unit"]), found["path_unit"])


def _entry(test: ImpactTest, kind: str, found: Optional[dict] = None) -> dict:
    return {**test.out(), "kind": kind, "evidence": found}


def suggest(units: Iterable[str], pairs: Iterable[PairStat], bases: Mapping[str, BaseStat], *, history_runs: int,
            changed_files: ChangedFiles, failing_on_branch: Iterable[ImpactTest]) -> dict:
    """The suggestion for one change. `pairs` may hold rows of other units (they are skipped); `bases` must hold the
    base row of every pair's test and every base row that can carry a label."""
    enough = history_runs >= MIN_HISTORY_RUNS
    best: Dict[str, dict] = {}
    if enough:
        wanted = set(units)
        for pair in pairs:
            base = bases.get(pair.test_key)
            if pair.path_unit not in wanted or base is None or base.flaky:
                continue
            found = evidence(pair, base)
            if found is not None and (pair.test_key not in best or _strength(found) > _strength(best[pair.test_key])):
                best[pair.test_key] = found
    ranked = sorted(best.items(), key=lambda item: (-item[1]["confidence"], -item[1]["lift"],
                                                   bases[item[0]].test.name, item[0]))
    tests = [_entry(bases[key].test, STATISTICAL, found) for key, found in ranked[:MAX_STATISTICAL]]
    listed = {entry["test_key"] for entry in tests}
    labelled = (
        (TEST_FILE_CHANGED, [b.test for b in bases.values() if changed_files.touches(b.file)]),
        (FAILING_ON_BRANCH, list(failing_on_branch)),
        (NO_HISTORY, [b.test for b in bases.values() if b.runs < MIN_CHANGED_RUNS]),
    )
    for kind, candidates in labelled:
        fresh = sorted({t.test_key: t for t in candidates if t.test_key not in listed}.values(),
                       key=lambda t: (t.name, t.test_key))
        for test in fresh[:MAX_PER_LABEL]:
            tests.append(_entry(test, kind))
            listed.add(test.test_key)
    return {"state": "ok" if enough else "not_enough_history", "history_runs": history_runs,
            "needed_runs": MIN_HISTORY_RUNS, "statistical_total": len(best), "tests": tests}
```

- [ ] **Step 4: Run the tests**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_impact_score.py tests/unit/test_impact_rules.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/analytics/impact_score.py platforms/ingestion-service/tests/unit/test_impact_score.py
git commit -m "feat(ingestion): score a change against the impact statistics (thresholds, ordering, cap, labels)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/analytics/impact_score.py platforms/ingestion-service/tests/unit/test_impact_score.py
```

---

### Task 4: Newly failed, for one run and in bulk

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/service/impact_history.py`
- Modify: `platforms/ingestion-service/tests/conftest.py`
- Test: `platforms/ingestion-service/tests/integration/test_impact_newly_failed.py`

**Interfaces:**
- Consumes:
  - Task 2: `FAILING`, `FLAKY_MIN_RUNS`, `FLAKY_MIN_FLIP_RATE`, `WINDOW_DAYS`, `base_branch_of`.
  - Task 3: `ImpactTest`.
  - Existing helpers:
    - `in_list(db, column, values, item_type=String)` (`service/report_service.py`);
    - `rank_flaky(flips, mixed, latest, *, min_runs, min_flip_rate, limit)`;
    - `rollup.has_rollups(db, project_id)`, `rollup.rollup_inputs(db, project_id, since_day, branch)`;
    - `analytics_service.flaky_inputs(db, project_id, since, branch)`;
    - `as_utc(dt)` (`analytics/trends.py`).
- Produces, in `src.ingestion.service.impact_history`:
  - `run_outcomes(db: Session, run_id: int) -> Dict[str, Tuple[str, ImpactTest]]`: `{key: (status, test)}`, last attempt among non-skipped results.
  - `newly_failed_in_run(db: Session, run: Run, excluded: Set[str]) -> List[ImpactTest]`, sorted by name.
  - `ChangeRun(id: int, project_id: int, branch: Optional[str], base: Optional[str], started_at: datetime, paths: Tuple[str, ...])`, a frozen dataclass; `started_at` is UTC-aware.
  - `change_runs(db, project_id: int, start: datetime, end: datetime, *, include_truncated: bool = False) -> List[ChangeRun]`, oldest first, `[start, end)`.
  - `newly_failed_bulk(db, runs: List[ChangeRun], excluded: Set[str]) -> Dict[int, Set[str]]`: `runs` are of one project, and the answer equals `newly_failed_in_run` run by run.
  - `flaky_keys(db, project_id: int, since: datetime) -> Set[str]` (Ruling 6).
  - The test fixture `seed_change_run(started_at, results=(("t1", "passed", 10),), paths=("src/app.py",), truncated=False, base_branch=None, **seed_run fields) -> Run` in `tests/conftest.py`.

- [ ] **Step 1: Add the seeding fixture**

In `platforms/ingestion-service/tests/conftest.py`, with the Edit tool, replace:

```python
def post_report(client, auth, **body):
```

with:

```python
@pytest.fixture
def seed_change_run(db, seed_run):
    """seed_change_run(started_at, results, paths=("src/app.py",), truncated=False, base_branch=None, **seed_run fields):
    a run with changed files, stored as an upload with `changes` stores it (test impact, spec 2026-10-12). Without a
    base branch the diff's base ref is a single commit ("abc1234^"), as the collector sends outside pull requests."""
    from src.ingestion.models import RunChangedFile

    def _seed(started_at, results=(("t1", "passed", 10),), paths=("src/app.py",), truncated=False, base_branch=None,
              **fields):
        run = seed_run(started_at, results=results, **fields)
        run.base_branch = base_branch
        run.change_base_ref = f"origin/{base_branch}" if base_branch else "abc1234^"
        run.changed_files = len(paths)
        run.additions, run.deletions = len(paths), 0
        run.changes_truncated = truncated
        for path in paths:
            db.add(RunChangedFile(run_id=run.id, path=path, status="M", additions=1, deletions=0))
        db.commit()
        return run

    return _seed


def post_report(client, auth, **body):
```

- [ ] **Step 2: Write the failing tests**

Create `platforms/ingestion-service/tests/integration/test_impact_newly_failed.py`:

```python
"""Newly failed (spec 2026-10-12 §3.1, plan Rulings 6, 7, 8): one run's answer, and the rollup's bulk answer that
must agree with it."""
from datetime import datetime, timedelta, timezone

from src.ingestion.models import Run
from src.ingestion.service import impact_history
from src.ingestion.service.ingest_service import test_key as key_of

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def ago(hours):
    return NOW - timedelta(hours=hours)


def newly(db, run, excluded=()):
    db.expire_all()
    return [t.name for t in impact_history.newly_failed_in_run(db, db.get(Run, run.id), set(excluded))]


def test_passed_then_failed_is_newly_failed(db, seed_run):
    seed_run(ago(3), results=(("pays", "passed", 1),))
    assert newly(db, seed_run(ago(2), results=(("pays", "failed", 1),))) == ["pays"]


def test_failed_then_failed_is_not(db, seed_run):
    seed_run(ago(3), results=(("pays", "failed", 1),))
    assert newly(db, seed_run(ago(2), results=(("pays", "failed", 1),))) == []


def test_errored_is_failing_too(db, seed_run):
    seed_run(ago(3), results=(("pays", "passed", 1),))
    assert newly(db, seed_run(ago(2), results=(("pays", "errored", 1),))) == ["pays"]


def test_a_skipped_result_is_not_the_previous_one(db, seed_run):
    seed_run(ago(4), results=(("pays", "passed", 1),))
    seed_run(ago(3), results=(("pays", "skipped", 0),))
    assert newly(db, seed_run(ago(2), results=(("pays", "failed", 1),))) == ["pays"]


def test_the_last_attempt_is_the_outcome(db, seed_run):
    seed_run(ago(5), results=(("pays", "passed", 1),))
    retried = seed_run(ago(4), results=(("pays", "failed", 1), ("pays", "passed", 1)))  # failed, passed on retry
    assert newly(db, retried) == []
    # the retried run's outcome (passed) is the previous result of the next run, whose last attempt failed
    assert newly(db, seed_run(ago(3), results=(("pays", "passed", 1), ("pays", "failed", 1)))) == ["pays"]


def test_another_branch_is_not_the_previous_result(db, seed_run):
    seed_run(ago(3), results=(("pays", "passed", 1),), branch="main")
    assert newly(db, seed_run(ago(2), results=(("pays", "failed", 1),), branch="dev")) == []


def test_a_new_branch_falls_back_to_its_base_branch(db, seed_run, seed_change_run):
    seed_run(ago(3), results=(("pays", "passed", 1),), branch="main")
    pr = seed_change_run(ago(2), results=(("pays", "failed", 1),), branch="feature/pay", base_branch="main")
    assert newly(db, pr) == ["pays"]


def test_the_base_branch_also_comes_from_the_diffs_base_ref(db, seed_run, seed_change_run):
    seed_run(ago(3), results=(("pays", "passed", 1),), branch="develop")
    pr = seed_change_run(ago(2), results=(("pays", "failed", 1),), branch="feature/pay")
    pr.change_base_ref = "origin/develop"
    db.commit()
    assert newly(db, pr) == ["pays"]


def test_the_base_branch_counts_only_results_before_the_run(db, seed_run, seed_change_run):
    seed_run(ago(4), results=(("pays", "failed", 1),), branch="main")
    pr = seed_change_run(ago(3), results=(("pays", "failed", 1),), branch="feature/pay", base_branch="main")
    seed_run(ago(2), results=(("pays", "passed", 1),), branch="main")
    assert newly(db, pr) == []


def test_excluded_tests_never_newly_fail(db, seed_run):
    seed_run(ago(3), results=(("pays", "passed", 1),))
    run = seed_run(ago(2), results=(("pays", "failed", 1),))
    assert newly(db, run, excluded={key_of("s", "C", "pays")}) == []


def test_a_previous_result_older_than_90_days_does_not_count(db, seed_run):
    seed_run(NOW - timedelta(days=91), results=(("pays", "passed", 1),))
    assert newly(db, seed_run(ago(1), results=(("pays", "failed", 1),))) == []


def test_change_runs_leave_out_truncated_runs_and_runs_without_files(db, seed_run, seed_change_run):
    kept = seed_change_run(ago(3), paths=("src/a.py", "src/b.py"))
    seed_change_run(ago(2), paths=("src/c.py",), truncated=True)
    seed_run(ago(1))
    runs = impact_history.change_runs(db, 1, NOW - timedelta(days=1), NOW)
    assert [(r.id, r.paths, r.base) for r in runs] == [(kept.id, ("src/a.py", "src/b.py"), None)]
    assert len(impact_history.change_runs(db, 1, NOW - timedelta(days=1), NOW, include_truncated=True)) == 2


def test_the_bulk_answer_agrees_with_the_one_run_answer(db, seed_run, seed_change_run):
    """The rollup's window must find exactly what an upload's outcome finds, run by run."""
    seed_run(NOW - timedelta(days=95), results=(("old", "passed", 1),))  # beyond the look-back of every run
    seed_run(ago(60), results=(("pays", "passed", 1), ("cart", "failed", 1)))
    seed_change_run(ago(50), results=(("pays", "failed", 1), ("cart", "failed", 1), ("old", "failed", 1)))
    seed_change_run(ago(40), results=(("pays", "failed", 1), ("pays", "passed", 1), ("cart", "passed", 1)))
    seed_change_run(ago(30), results=(("pays", "errored", 1), ("cart", "skipped", 0)))
    seed_run(ago(25), results=(("ship", "passed", 1),), branch="main")
    seed_change_run(ago(20), results=(("ship", "failed", 1), ("pays", "failed", 1)), branch="feature/ship",
                    base_branch="main")
    seed_run(ago(15), results=(("ship", "passed", 1),), branch="feature/ship")
    seed_change_run(ago(10), results=(("ship", "failed", 1),), branch="feature/ship", base_branch="main")
    seed_change_run(ago(5), results=(("lone", "failed", 1),), branch=None)
    runs = impact_history.change_runs(db, 1, NOW - timedelta(days=100), NOW)
    bulk = impact_history.newly_failed_bulk(db, runs, set())
    for run in runs:
        expected = {t.test_key for t in impact_history.newly_failed_in_run(db, db.get(Run, run.id), set())}
        assert bulk.get(run.id, set()) == expected, run.id
    assert sum(len(keys) for keys in bulk.values()) == 4  # pays at 50 h and 30 h, ship at 20 h (base) and 10 h


def test_flaky_keys_use_the_flaky_views_defaults(db, seed_run):
    for i, status in enumerate(("passed", "failed") * 3):
        seed_run(ago(10 - i), results=(("flips", status, 1), ("steady", "passed", 1)))
    assert impact_history.flaky_keys(db, 1, NOW - timedelta(days=14)) == {key_of("s", "C", "flips")}
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_newly_failed.py -q`
Expected: FAIL, `ImportError: cannot import name 'impact_history' from 'src.ingestion.service'`.

- [ ] **Step 4: Write the module**

Create `platforms/ingestion-service/src/ingestion/service/impact_history.py`:

```python
"""Test impact analysis: which tests newly failed (spec 2026-10-12 §3.1, plan Rulings 6, 7, 8).

A test newly failed in run R when its outcome in R fails (failed or errored; the outcome is the last attempt among
non-skipped results) and its previous outcome on R's branch within the 90 days before R passed. A branch with no
previous outcome there (a new PR branch) uses the test's latest outcome on R's base branch before R. The caller's
`excluded` set leaves out flaky and muted tests.

Two readings of the one definition: `newly_failed_in_run` for one run (an upload's outcome, replay) and
`newly_failed_bulk` for many (the rollup); tests/integration/test_impact_newly_failed.py pins them to agree.
"""
import sys
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import Integer, and_, func, or_, select
from sqlalchemy.orm import Session

from src.ingestion.analytics import rollup
from src.ingestion.analytics.flaky import rank_flaky
from src.ingestion.analytics.impact_rules import (
    FAILING, FLAKY_MIN_FLIP_RATE, FLAKY_MIN_RUNS, WINDOW_DAYS, base_branch_of,
)
from src.ingestion.analytics.impact_score import ImpactTest
from src.ingestion.analytics.trends import as_utc
from src.ingestion.models import Run, RunChangedFile, RunResult
from src.ingestion.service import analytics_service
from src.ingestion.service.report_service import in_list

LOOKBACK = timedelta(days=WINDOW_DAYS)


def run_outcomes(db: Session, run_id: int) -> Dict[str, Tuple[str, ImpactTest]]:
    """{test key: (status, test)} for one run: each test's last attempt (highest id) among its non-skipped results."""
    rows = db.execute(
        select(RunResult.test_key, RunResult.status, RunResult.suite, RunResult.class_name, RunResult.name)
        .where(RunResult.run_id == run_id, RunResult.status != "skipped")
        .order_by(RunResult.id)
    ).all()
    return {key: (status, ImpactTest(key, suite, class_name, name)) for key, status, suite, class_name, name in rows}


def _on_branch(branch: Optional[str]):
    return Run.branch.is_(None) if branch is None else Run.branch == branch


def _previous_outcomes(db: Session, run: Run, branch: Optional[str], keys: List[str]) -> Dict[str, str]:
    """Each key's outcome in the latest run on `branch` before `run` that ran it, within LOOKBACK."""
    if not keys:
        return {}
    started = as_utc(run.started_at)
    earlier = or_(Run.started_at < started, and_(Run.started_at == started, Run.id < run.id))
    ranked = (
        select(
            RunResult.test_key.label("test_key"), RunResult.status.label("status"),
            func.row_number().over(
                partition_by=RunResult.test_key, order_by=(Run.started_at.desc(), Run.id.desc(), RunResult.id.desc()),
            ).label("position"),
        )
        .join(Run, Run.id == RunResult.run_id)
        .where(Run.project_id == run.project_id, _on_branch(branch), earlier, Run.started_at >= started - LOOKBACK,
               RunResult.status != "skipped", in_list(db, RunResult.test_key, keys))
    ).subquery()
    rows = db.execute(select(ranked.c.test_key, ranked.c.status).where(ranked.c.position == 1))
    return {key: status for key, status in rows}


def newly_failed_in_run(db: Session, run: Run, excluded: Set[str]) -> List[ImpactTest]:
    """The tests that newly failed in one run, by name."""
    failing = {key: test for key, (status, test) in run_outcomes(db, run.id).items()
               if status in FAILING and key not in excluded}
    if not failing:
        return []
    previous = _previous_outcomes(db, run, run.branch, sorted(failing))
    base = base_branch_of(run.branch, run.base_branch, run.change_base_ref)
    unseen = sorted(key for key in failing if key not in previous)
    if unseen and base is not None:
        previous.update(_previous_outcomes(db, run, base, unseen))
    return sorted((test for key, test in failing.items() if previous.get(key) == "passed"),
                  key=lambda t: (t.name, t.test_key))


@dataclass(frozen=True)
class ChangeRun:
    """A run with uploaded changed files, as the statistics and replay read it."""

    id: int
    project_id: int
    branch: Optional[str]
    base: Optional[str]  # base_branch_of(...)
    started_at: datetime  # UTC
    paths: Tuple[str, ...]


def change_runs(db: Session, project_id: int, start: datetime, end: datetime, *,
                include_truncated: bool = False) -> List[ChangeRun]:
    """Runs started in [start, end) with at least one changed file, oldest first. A run whose change list the
    collector truncated is left out of the statistics (spec §3.1) unless `include_truncated` (replay scores it, as an
    upload does; plan Ruling 16)."""
    filters = [Run.project_id == project_id, Run.started_at >= start, Run.started_at < end, Run.changed_files > 0]
    if not include_truncated:
        filters.append(or_(Run.changes_truncated.is_(None), Run.changes_truncated.is_(False)))
    runs = db.execute(
        select(Run.id, Run.branch, Run.base_branch, Run.change_base_ref, Run.started_at)
        .where(*filters).order_by(Run.started_at, Run.id)
    ).all()
    paths: Dict[int, List[str]] = defaultdict(list)
    if runs:
        rows = db.execute(
            select(RunChangedFile.run_id, RunChangedFile.path)
            .where(in_list(db, RunChangedFile.run_id, [r.id for r in runs], Integer)).order_by(RunChangedFile.id)
        )
        for run_id, path in rows:
            paths[run_id].append(path)
    return [ChangeRun(r.id, project_id, r.branch, base_branch_of(r.branch, r.base_branch, r.change_base_ref),
                      as_utc(r.started_at), tuple(paths[r.id])) for r in runs]


def _last_attempts(project_id: int, start: datetime, end: datetime, *extra):
    """Non-skipped results of the project's runs started in [start, end], numbered so attempt 1 is each run's last
    attempt of each test."""
    return (
        select(
            RunResult.run_id.label("run_id"), RunResult.test_key.label("test_key"), RunResult.status.label("status"),
            Run.branch.label("branch"), Run.started_at.label("started_at"),
            func.row_number().over(partition_by=(RunResult.run_id, RunResult.test_key),
                                   order_by=RunResult.id.desc()).label("attempt"),
        )
        .join(Run, Run.id == RunResult.run_id)
        .where(Run.project_id == project_id, Run.started_at >= start, Run.started_at <= end,
               RunResult.status != "skipped", *extra)
    ).subquery()


def _branch_history(db: Session, project_id: int, branch: str, keys: List[str], start: datetime,
                    end: datetime) -> Dict[str, List[Tuple[datetime, int, str]]]:
    """{key: [(started_at, run id, status)]}, oldest first: the keys' outcomes on `branch` in [start, end]."""
    ranked = _last_attempts(project_id, start, end, Run.branch == branch, in_list(db, RunResult.test_key, keys))
    history: Dict[str, List[Tuple[datetime, int, str]]] = defaultdict(list)
    rows = db.execute(select(ranked.c.test_key, ranked.c.status, ranked.c.started_at, ranked.c.run_id)
                      .where(ranked.c.attempt == 1))
    for key, status, started_at, run_id in rows:
        history[key].append((as_utc(started_at), run_id, status))
    for outcomes in history.values():
        outcomes.sort()
    return history


def newly_failed_bulk(db: Session, runs: List[ChangeRun], excluded: Set[str]) -> Dict[int, Set[str]]:
    """{run id: newly failed keys} for many runs of one project, from one window over its outcomes (the rollup)."""
    if not runs:
        return {}
    project_id = runs[0].project_id
    first, last = min(r.started_at for r in runs), max(r.started_at for r in runs)
    ranked = _last_attempts(project_id, first - LOOKBACK, last)
    order = {"partition_by": (ranked.c.test_key, ranked.c.branch), "order_by": (ranked.c.started_at, ranked.c.run_id)}
    outcomes = (
        select(ranked.c.run_id, ranked.c.test_key, ranked.c.status,
               func.lag(ranked.c.status).over(**order).label("previous"),
               # typed, so SQLite (the tests) hands back a datetime, not text
               func.lag(ranked.c.started_at, type_=ranked.c.started_at.type).over(**order).label("previous_at"))
        .where(ranked.c.attempt == 1)
    ).subquery()
    by_id = {r.id: r for r in runs}
    newly: Dict[int, Set[str]] = defaultdict(set)
    unseen: Dict[str, List[Tuple[ChangeRun, str]]] = defaultdict(list)  # base branch -> (run, key)
    rows = db.execute(
        select(outcomes.c.run_id, outcomes.c.test_key, outcomes.c.previous, outcomes.c.previous_at)
        .where(outcomes.c.status.in_(FAILING), in_list(db, outcomes.c.run_id, list(by_id), Integer))
    )
    for run_id, key, previous, previous_at in rows:
        if key in excluded:
            continue
        run = by_id[run_id]
        if previous is not None and as_utc(previous_at) >= run.started_at - LOOKBACK:
            if previous == "passed":
                newly[run_id].add(key)
        elif run.base is not None:
            unseen[run.base].append((run, key))
    for base, pending in unseen.items():
        history = _branch_history(db, project_id, base, sorted({key for _, key in pending}), first - LOOKBACK, last)
        for run, key in pending:
            outcomes_of_key = history.get(key, [])
            at = bisect_left(outcomes_of_key, (run.started_at, run.id, ""))
            if at and outcomes_of_key[at - 1][0] >= run.started_at - LOOKBACK and outcomes_of_key[at - 1][2] == "passed":
                newly[run.id].add(key)
    return dict(newly)


def flaky_keys(db: Session, project_id: int, since: datetime) -> Set[str]:
    """Tests flagged flaky since `since` with the Flaky view's defaults (plan Ruling 6), read as GET /analytics/flaky
    reads them: from the daily rollups when the project has them."""
    if rollup.has_rollups(db, project_id):
        inputs = rollup.rollup_inputs(db, project_id, since.date(), None)
    else:
        inputs = analytics_service.flaky_inputs(db, project_id, since, None)
    ranked = rank_flaky(*inputs, min_runs=FLAKY_MIN_RUNS, min_flip_rate=FLAKY_MIN_FLIP_RATE, limit=sys.maxsize)
    return {item["test_key"] for item in ranked}
```

- [ ] **Step 5: Run the tests**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_newly_failed.py -q`
Expected: PASS. If `test_the_bulk_answer_agrees_with_the_one_run_answer` fails only on its last line, print `bulk` and recount by hand against the docstring of the scenario before touching code: the per-run comparisons above that line are the real check.

- [ ] **Step 6: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/service/impact_history.py platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_impact_newly_failed.py
git commit -m "feat(ingestion): newly failed tests for one run and in bulk, pinned to agree" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/service/impact_history.py platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_impact_newly_failed.py
```

---

### Task 5: Statistics and the `impact-rollup` job

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/service/impact_stats.py`
- Create: `platforms/ingestion-service/src/ingestion/jobs/impact_rollup.py`
- Modify: `platforms/ingestion-service/tests/conftest.py`, `platforms/ingestion-service/README.md`
- Test: `platforms/ingestion-service/tests/integration/test_impact_rollup.py`

**Interfaces:**
- Consumes:
  - Task 1: `ImpactPair`, `ImpactTestBase`.
  - Tasks 2–4: `change_units`, `WINDOW_DAYS`, `PairStat`, `BaseStat`, `ImpactTest`, `change_runs`, `newly_failed_bulk`, `flaky_keys`.
  - Existing helpers: `analytics_service.muted_keys(db, project_id) -> set`, `heartbeat.record_success/record_error(session_factory, job, ...)`, `in_list`.
- Produces:
  - In `src.ingestion.service.impact_stats`:
    - `build_statistics(db, project_id: int, start: datetime, end: datetime, flaky: Set[str], muted: Set[str]) -> Tuple[List[PairStat], List[BaseStat]]`;
    - `replace_statistics(db, project_id: int, pairs: List[PairStat], bases: List[BaseStat], computed_at: datetime) -> None` (commits);
    - `live_excluded(db, project_id: int) -> Set[str]`: base rows flagged flaky plus muted now.
  - In `src.ingestion.jobs.impact_rollup`:
    - constants `JOB = "impact_rollup"`, `LOCK_ID = 7_351_004`, `DEFAULT_INTERVAL_HOURS = 24.0`;
    - `window_start(now: datetime) -> datetime`;
    - `run_pass(db, now: Callable[[], datetime] = ...) -> dict` (`{"event": "impact_rollup", "projects", "pairs", "tests"}`);
    - `run_once(*, session_factory, lock_engine) -> bool`;
    - `main(argv=None, *, session_factory=None, lock_engine=None, stop=None, interval_hours=DEFAULT_INTERVAL_HOURS) -> int`.
  - The test fixture `seed_impact_history(start, branch="main", project_id=1) -> List[Run]`: 15 runs, one a day.

- [ ] **Step 1: Add the history fixture**

In `platforms/ingestion-service/tests/conftest.py`, with the Edit tool, replace:

```python
def post_report(client, auth, **body):
```

with:

```python
@pytest.fixture
def seed_impact_history(seed_change_run):
    """seed_impact_history(start, branch="main", project_id=1) -> runs: 15 runs with changed files, one a day from
    `start`. The first 11 change docs/guide.md and `pays` passes; the last 4 change src/pay/api.py and `pays` passes,
    fails, passes, fails. So `pays` newly failed in 2 of the 4 runs that changed src/pay/ (confidence 0.5) and in 2 of
    15 overall (base rate 0.1333, lift 3.75), and is not flaky (3 flips in 14 pairs, under the Flaky view's 0.3).
    `steady` passes in every run."""

    def _seed(start, branch="main", project_id=1):
        runs = []
        statuses = ["passed"] * 11 + ["passed", "failed", "passed", "failed"]
        for day, status in enumerate(statuses):
            paths = ("docs/guide.md",) if day < 11 else ("src/pay/api.py",)
            runs.append(seed_change_run(start + timedelta(days=day), results=(("pays", status, 5), ("steady", "passed", 5)),
                                        paths=paths, branch=branch, project_id=project_id))
        return runs

    return _seed


def post_report(client, auth, **body):
```

- [ ] **Step 2: Write the failing tests**

Create `platforms/ingestion-service/tests/integration/test_impact_rollup.py`:

```python
"""The impact-rollup job (spec 2026-10-12 §3.2; plan Rulings 6, 9, 14, 16): impact_pairs and impact_test_base."""
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.jobs import impact_rollup
from src.ingestion.models import Run, RunChangedFile, RunResult
from src.ingestion.models.impact import ImpactPair, ImpactTestBase
from src.ingestion.models.job_heartbeat import JobHeartbeat
from src.ingestion.models.muted import MutedTest
from src.ingestion.service.impact_stats import live_excluded
from src.ingestion.service.ingest_service import test_key as key_of

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
PAYS, STEADY = key_of("s", "C", "pays"), key_of("s", "C", "steady")
PAY_UNITS = ("src/pay/api.py", "src/pay/", "src/")


def rows(db, project_id=1):
    db.expire_all()
    pairs = {(p.path_unit, p.test_key): (p.changed_runs, p.new_failures)
             for p in db.query(ImpactPair).filter_by(project_id=project_id)}
    bases = {b.test_key: (b.runs, b.new_failures, b.flaky)
             for b in db.query(ImpactTestBase).filter_by(project_id=project_id)}
    return pairs, bases


def rollup(db, at=NOW):
    return impact_rollup.run_pass(db, now=lambda: at)


def hours_ago(hours):
    return NOW - timedelta(hours=hours)


def test_a_pass_writes_the_pairs_with_new_failures_and_every_tests_base_rate(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15))
    summary = rollup(db)
    pairs, bases = rows(db)
    assert pairs == {(unit, PAYS): (4, 2) for unit in PAY_UNITS}
    assert bases == {PAYS: (15, 2, False), STEADY: (15, 0, False)}
    assert summary == {"event": "impact_rollup", "projects": 1, "pairs": 3, "tests": 2}


def test_names_and_the_test_file_are_kept_for_scoring(db, seed_change_run):
    run = seed_change_run(hours_ago(1), results=(("pays", "passed", 5),))
    db.query(RunResult).filter_by(run_id=run.id).update({"file": "tests/test_pay.py"})
    db.commit()
    rollup(db)
    base = db.query(ImpactTestBase).one()
    assert (base.suite, base.class_name, base.name, base.file) == ("s", "C", "pays", "tests/test_pay.py")


def test_running_twice_the_same_day_writes_the_same_rows(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15))
    rollup(db)
    first = rows(db)
    rollup(db, NOW + timedelta(hours=6))
    assert rows(db) == first


def test_a_truncated_change_list_is_left_out_but_its_results_are_still_history(db, seed_change_run):
    seed_change_run(hours_ago(3), results=(("pays", "failed", 5),), paths=("docs/guide.md",))
    seed_change_run(hours_ago(2), results=(("pays", "passed", 5),), paths=("src/pay/api.py",), truncated=True)
    seed_change_run(hours_ago(1), results=(("pays", "failed", 5),), paths=("src/cart/x.py",))
    rollup(db)
    pairs, bases = rows(db)
    # newly failed after the truncated run's pass; the truncated run's src/pay/ is not counted
    assert pairs == {(unit, PAYS): (1, 1) for unit in ("src/cart/x.py", "src/cart/", "src/")}
    assert bases[PAYS] == (2, 1, False)


def test_a_change_of_more_than_300_files_counts_only_its_folders(db, seed_change_run):
    seed_change_run(hours_ago(2), results=(("pays", "passed", 5),), paths=("docs/guide.md",))
    seed_change_run(hours_ago(1), results=(("pays", "failed", 5),), paths=tuple(f"src/big/f{i}.py" for i in range(301)))
    rollup(db)
    assert rows(db)[0] == {("src/big/", PAYS): (1, 1), ("src/", PAYS): (1, 1)}


def test_lock_files_and_vendored_paths_make_no_pairs(db, seed_change_run):
    seed_change_run(hours_ago(2), results=(("pays", "passed", 5),), paths=("docs/guide.md",))
    seed_change_run(hours_ago(1), results=(("pays", "failed", 5),), paths=("poetry.lock", "web/node_modules/x/index.js"))
    rollup(db)
    pairs, bases = rows(db)
    assert pairs == {} and bases[PAYS] == (2, 1, False)


def test_a_flaky_test_counts_no_new_failures_and_is_flagged(db, seed_change_run):
    for hours, status in zip(range(6, 0, -1), ("passed", "failed") * 3):
        seed_change_run(hours_ago(hours), results=(("pays", status, 5),), paths=("src/pay/api.py",))
    rollup(db)
    pairs, bases = rows(db)
    assert pairs == {} and bases[PAYS] == (6, 0, True)
    assert live_excluded(db, 1) == {PAYS}


def test_a_muted_test_counts_no_new_failures(db, seed_change_run):
    seed_change_run(hours_ago(2), results=(("pays", "passed", 5),))
    seed_change_run(hours_ago(1), results=(("pays", "failed", 5),))
    db.add(MutedTest(project_id=1, test_key=PAYS, muted_by_user_id=1))
    db.commit()
    rollup(db)
    pairs, bases = rows(db)
    assert pairs == {} and bases[PAYS] == (2, 0, False)
    assert live_excluded(db, 1) == {PAYS}


def test_runs_before_the_window_are_left_out(db, seed_change_run):
    # the window starts 90 days before today 00:00 UTC: 2026-07-14 00:00
    seed_change_run(datetime(2026, 7, 13, 23, 0, tzinfo=timezone.utc), results=(("old", "passed", 5),))
    seed_change_run(datetime(2026, 7, 14, 0, 30, tzinfo=timezone.utc), results=(("new", "passed", 5),))
    rollup(db)
    assert set(rows(db)[1]) == {key_of("s", "C", "new")}


def test_each_project_has_its_own_rows(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15), project_id=1)
    seed_impact_history(start=NOW - timedelta(days=15), project_id=2)
    assert rollup(db)["projects"] == 2
    assert rows(db, 1) == rows(db, 2) and rows(db, 1)[0]


def test_a_project_whose_runs_are_gone_loses_its_rows(db, seed_impact_history):
    seed_impact_history(start=NOW - timedelta(days=15))
    rollup(db)
    db.query(RunChangedFile).delete()
    db.query(RunResult).delete()
    db.query(Run).delete()
    db.commit()
    assert rollup(db)["projects"] == 1
    assert rows(db) == ({}, {})


@pytest.fixture
def session_factory(db):
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)


def test_a_pass_records_its_heartbeat_and_logs_a_summary(db, session_factory, capsys):
    assert impact_rollup.main([], session_factory=session_factory) == 0
    db.expire_all()
    assert db.get(JobHeartbeat, "impact_rollup").last_success_at is not None
    assert '"event": "impact_rollup"' in capsys.readouterr().out


def test_a_failed_pass_records_the_error_and_exits_1(db, session_factory, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(impact_rollup, "run_pass", boom)
    assert impact_rollup.main([], session_factory=session_factory) == 1
    db.expire_all()
    heartbeat = db.get(JobHeartbeat, "impact_rollup")
    assert heartbeat.last_success_at is None and heartbeat.last_error == "RuntimeError: boom"


def test_the_loop_survives_a_failed_pass_and_stops_when_asked(session_factory, monkeypatch):
    stop = threading.Event()
    calls = []

    def flaky_pass(db, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first pass fails")
        stop.set()
        return {}

    monkeypatch.setattr(impact_rollup, "run_pass", flaky_pass)
    assert impact_rollup.main(["--loop"], session_factory=session_factory, stop=stop, interval_hours=0) == 0
    assert len(calls) == 2
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_rollup.py -q`
Expected: FAIL, `ImportError: cannot import name 'impact_rollup' from 'src.ingestion.jobs'`.

- [ ] **Step 4: Write the statistics module**

Create `platforms/ingestion-service/src/ingestion/service/impact_stats.py`:

```python
"""Test impact statistics (spec 2026-10-12 §3.2): per project, over the runs with changed files of a window, how often
each test newly failed after a change to each path unit, and each test's base rate. Written by the impact-rollup job;
replay builds the same numbers in memory for earlier windows."""
from collections import Counter
from datetime import datetime
from typing import Dict, List, Set, Tuple

from sqlalchemy import Integer, delete, func, insert, select
from sqlalchemy.orm import Session

from src.ingestion.analytics.impact_rules import change_units
from src.ingestion.analytics.impact_score import BaseStat, ImpactTest, PairStat
from src.ingestion.models import RunResult
from src.ingestion.models.impact import ImpactPair, ImpactTestBase
from src.ingestion.service import analytics_service
from src.ingestion.service.impact_history import change_runs, newly_failed_bulk
from src.ingestion.service.report_service import in_list


def _tests_in(db: Session, run_ids: List[int]) -> Dict[str, tuple]:
    """{key: (runs, suite, class_name, name, file)}: in how many of the runs each test has a non-skipped result."""
    if not run_ids:
        return {}
    rows = db.execute(
        select(RunResult.test_key, func.count(func.distinct(RunResult.run_id)), func.max(RunResult.suite),
               func.max(RunResult.class_name), func.max(RunResult.name), func.max(RunResult.file))
        .where(in_list(db, RunResult.run_id, run_ids, Integer), RunResult.status != "skipped")
        .group_by(RunResult.test_key)
    ).all()
    return {key: (runs, suite, class_name, name, file) for key, runs, suite, class_name, name, file in rows}


def build_statistics(db: Session, project_id: int, start: datetime, end: datetime, flaky: Set[str],
                     muted: Set[str]) -> Tuple[List[PairStat], List[BaseStat]]:
    """Pairs with at least one new failure, and a base row for every test that ran in the window's change runs
    (plan Ruling 9). Flaky and muted tests count no new failures (spec §3.1); flaky ones are flagged so an upload's
    outcome can leave them out without rescanning."""
    runs = change_runs(db, project_id, start, end)
    newly = newly_failed_bulk(db, runs, flaky | muted)
    changed_runs: Counter = Counter()
    new_failures: Counter = Counter()
    pairs: Counter = Counter()
    for run in runs:
        units = change_units(run.paths)
        changed_runs.update(units)
        failed = newly.get(run.id, set())
        new_failures.update(failed)
        pairs.update((unit, key) for unit in units for key in failed)
    tests = _tests_in(db, [run.id for run in runs])
    return (
        [PairStat(unit, key, changed_runs[unit], count) for (unit, key), count in sorted(pairs.items())],
        [BaseStat(ImpactTest(key, suite, class_name, name), runs_of_test, new_failures[key], file, key in flaky)
         for key, (runs_of_test, suite, class_name, name, file) in sorted(tests.items())],
    )


def replace_statistics(db: Session, project_id: int, pairs: List[PairStat], bases: List[BaseStat],
                       computed_at: datetime) -> None:
    """A project's rows replaced in one transaction: readers see the old set or the new one, never half."""
    db.execute(delete(ImpactPair).where(ImpactPair.project_id == project_id))
    db.execute(delete(ImpactTestBase).where(ImpactTestBase.project_id == project_id))
    if pairs:
        db.execute(insert(ImpactPair), [
            {"project_id": project_id, "path_unit": p.path_unit, "test_key": p.test_key,
             "changed_runs": p.changed_runs, "new_failures": p.new_failures, "computed_at": computed_at}
            for p in pairs
        ])
    if bases:
        db.execute(insert(ImpactTestBase), [
            {"project_id": project_id, "test_key": b.test.test_key, "runs": b.runs, "new_failures": b.new_failures,
             "flaky": b.flaky, "suite": b.test.suite, "class_name": b.test.class_name, "name": b.test.name,
             "file": b.file, "computed_at": computed_at}
            for b in bases
        ])
    db.commit()


def live_excluded(db: Session, project_id: int) -> Set[str]:
    """What an upload's outcome leaves out: tests the last rollup flagged flaky, and tests muted now."""
    flagged = {key for (key,) in db.execute(
        select(ImpactTestBase.test_key).where(ImpactTestBase.project_id == project_id, ImpactTestBase.flaky.is_(True)))}
    return flagged | analytics_service.muted_keys(db, project_id)
```

- [ ] **Step 5: Write the job**

Create `platforms/ingestion-service/src/ingestion/jobs/impact_rollup.py`:

```python
"""Test impact rollup (spec 2026-10-12 §3.2, plan Ruling 14): rebuild impact_pairs and impact_test_base per project.

    python -m src.ingestion.jobs.impact_rollup [--loop]

Each pass visits every project with runs, and every project that still has statistics (so a project whose runs are
gone loses them). Over the runs with changed files from 90 days before today 00:00 UTC until now, it replaces the
project's rows in one transaction; the same data gives the same rows. One pass at a time across copies (PostgreSQL
advisory lock), like the other jobs; each pass that ran writes the impact_rollup heartbeat.
"""
import argparse
import json
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Iterator, List, Optional

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.analytics.impact_rules import WINDOW_DAYS
from src.ingestion.jobs import heartbeat
from src.ingestion.models import Run
from src.ingestion.models.impact import ImpactTestBase
from src.ingestion.service import analytics_service
from src.ingestion.service.impact_history import flaky_keys
from src.ingestion.service.impact_stats import build_statistics, replace_statistics

LOCK_ID = 7_351_004  # distinct from retention's, rollup's and weekly summary's locks
DEFAULT_INTERVAL_HOURS = 24.0
JOB = "impact_rollup"


def _log(record: dict, error: bool = False) -> None:
    print(json.dumps(record), file=sys.stderr if error else sys.stdout, flush=True)


def window_start(now: datetime) -> datetime:
    """90 days before today 00:00 UTC: every pass of one day starts at the same moment."""
    today = datetime.combine(now.astimezone(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    return today - timedelta(days=WINDOW_DAYS)


def _projects(db: Session) -> List[int]:
    with_runs = {pid for (pid,) in db.execute(select(Run.project_id).distinct())}
    with_rows = {pid for (pid,) in db.execute(select(ImpactTestBase.project_id).distinct())}
    return sorted(with_runs | with_rows)


def run_pass(db: Session, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    moment = now()
    start = window_start(moment)
    projects = _projects(db)
    pairs_written = tests_written = 0
    for project_id in projects:
        pairs, bases = build_statistics(db, project_id, start, moment, flaky_keys(db, project_id, start),
                                        analytics_service.muted_keys(db, project_id))
        replace_statistics(db, project_id, pairs, bases, moment)
        pairs_written += len(pairs)
        tests_written += len(bases)
    summary = {"event": "impact_rollup", "projects": len(projects), "pairs": pairs_written, "tests": tests_written}
    _log(summary)
    return summary


@contextmanager
def _advisory_lock(engine: Engine) -> Iterator[bool]:
    if engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as conn:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}).scalar())
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
                conn.commit()


def run_once(*, session_factory: sessionmaker, lock_engine: Engine) -> bool:
    try:
        with _advisory_lock(lock_engine) as acquired:
            if not acquired:
                _log({"event": "impact_rollup", "skipped": "another copy holds the lock"})
                return True  # the copy holding the lock writes the heartbeat
            with session_factory() as db:
                run_pass(db)
    except Exception as exc:  # the loop must survive a bad pass
        message = f"{type(exc).__name__}: {exc}"
        _log({"event": "impact_rollup", "error": message}, error=True)
        heartbeat.record_error(session_factory, JOB, message)
        return False
    heartbeat.record_success(session_factory, JOB)
    return True


def main(
    argv: Optional[list] = None,
    *,
    session_factory: Optional[sessionmaker] = None,
    lock_engine: Optional[Engine] = None,
    stop: Optional[threading.Event] = None,
    interval_hours: float = DEFAULT_INTERVAL_HOURS,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true", help="run forever, one pass every 24 hours")
    args = parser.parse_args(argv)

    if session_factory is None:
        from src.ingestion.db.session import SessionLocal

        session_factory = SessionLocal
    if lock_engine is None:
        lock_engine = session_factory.kw["bind"]

    stop = stop or threading.Event()
    ok = run_once(session_factory=session_factory, lock_engine=lock_engine)
    if not args.loop:
        return 0 if ok else 1
    while not stop.wait(interval_hours * 3600):
        run_once(session_factory=session_factory, lock_engine=lock_engine)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The `_advisory_lock` follows each job's own pattern (`jobs/rollup.py`, `jobs/retention.py`, `jobs/weekly_summary.py` each hold one with their own `LOCK_ID`); there is no shared helper to reuse.

- [ ] **Step 6: Run the tests**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_rollup.py tests/integration/test_impact_newly_failed.py -q`
Expected: PASS.

- [ ] **Step 7: Document the statistics in the ingestion README**

In `platforms/ingestion-service/README.md`, with the Edit tool, replace:

```
## Operations
```

with:

```
## Test impact

QEOS suggests which tests a change is likely to affect, from which tests **newly failed** after earlier changes to
the same files or folders (spec `docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md`, ADR-029). No
coverage instrumentation, no AI: co-failure statistics on PostgreSQL.

### Statistics (the `impact-rollup` job)

- **Newly failed:** the test's outcome in run R fails (failed or errored; the outcome is the last attempt among
  non-skipped results) and its previous outcome on R's branch, within the 90 days before R, passed. A branch with
  no previous outcome there (a new PR branch) uses the test's latest outcome on the base branch before R
  (`base_branch`, else `change_base_ref` without `origin/`). Flaky tests (the Flaky view's defaults: 5 runs, 30%
  flips) and muted tests never newly fail.
- **Path units:** each changed path and its nearest parent folders, at most 3 (`src/payment/api.py`,
  `src/payment/`, `src/`). Lock files (`*.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`,
  `poetry.lock`) and anything under `dist/`, `build/`, `vendor/` or `node_modules/` are not units. A change of more
  than 300 files counts at folder level only. Runs whose change list the collector truncated are left out.
- **Tables** (migration 018), rebuilt per project in one transaction by `python -m src.ingestion.jobs.impact_rollup`
  (compose service `impact-rollup`: one pass on start, then every 24 hours, lock 7351004, heartbeat `impact_rollup`):
  - `impact_pairs (project_id, path_unit, test_key, changed_runs, new_failures, computed_at)`: only pairs with at
    least one new failure, over the runs with changed files from 90 days before today 00:00 UTC;
  - `impact_test_base (project_id, test_key, runs, new_failures, flaky, suite, class_name, name, file,
    computed_at)`: every test that ran in those runs, so scoring never scans `test_results`.
  The same data gives the same rows; a project whose runs are gone loses its rows at the next pass. The thresholds
  live in `src/ingestion/analytics/impact_rules.py`.

## Operations
```

- [ ] **Step 8: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/service/impact_stats.py platforms/ingestion-service/src/ingestion/jobs/impact_rollup.py platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_impact_rollup.py platforms/ingestion-service/README.md
git commit -m "feat(ingestion): impact-rollup job rebuilds the test impact statistics per project" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/service/impact_stats.py platforms/ingestion-service/src/ingestion/jobs/impact_rollup.py platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_impact_rollup.py platforms/ingestion-service/README.md
```

---

### Task 6: Wire the job: compose service, heartbeat, JobStale alert, architecture docs

**Files:**
- Modify:
  - `platforms/ingestion-service/src/ingestion/jobs/heartbeat.py`;
  - `platforms/ingestion-service/tests/integration/test_heartbeat_metrics.py`;
  - compose files `docker-compose.yml`, `deploy/docker-compose.prod.yml`;
  - monitoring `monitoring/prometheus/alerts.yml`, `monitoring/prometheus/tests/alerts.test.yml`, `monitoring/grafana/dashboards/jobs-uploads.json`;
  - docs `README.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md`, `TECHNICAL_SPECIFICATION.md`, `docs/SETUP.md`, `platforms/ingestion-service/README.md`.

**Interfaces:**
- Consumes (Task 5): `python -m src.ingestion.jobs.impact_rollup --loop`, `JOB = "impact_rollup"`.
- Produces:
  - `heartbeat.JOBS == ("retention", "rollup", "weekly_summary", "impact_rollup")`, so `/metrics` always exposes `job_last_success_timestamp_seconds{job="impact_rollup"}` (0 before the first pass).
  - The compose service `impact-rollup` (dev and prod).
  - JobStale for `impact_rollup` after 2 × 86400 s (Ruling 14).

- [ ] **Step 1: Write the failing heartbeat test**

In `platforms/ingestion-service/tests/integration/test_heartbeat_metrics.py`, with the Edit tool, replace:

```python
    for job in ("retention", "rollup", "weekly_summary"):
```

with:

```python
    for job in ("retention", "rollup", "weekly_summary", "impact_rollup"):
```

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_heartbeat_metrics.py -q`
Expected: FAIL on `assert 'job_last_success_timestamp_seconds{job="impact_rollup"} 0.0' in text`.

- [ ] **Step 2: Add the job to the known jobs**

In `platforms/ingestion-service/src/ingestion/jobs/heartbeat.py`, with the Edit tool, replace:

```python
JOBS = ("retention", "rollup", "weekly_summary")
```

with:

```python
JOBS = ("retention", "rollup", "weekly_summary", "impact_rollup")
```

Run the same command. Expected: PASS.

- [ ] **Step 3: Write the failing alert rule tests**

In `monitoring/prometheus/tests/alerts.test.yml`, with the Edit tool, replace:

```yaml
  - name: JobFailing after 30 minutes of an error newer than the last success
```

with:

```yaml
  - name: JobStale gives impact_rollup two days (it passes every 24 hours)
    interval: 1m
    input_series:
      # at eval_time 10m, time() = 600: impact_rollup last succeeded 172,900 s ago (> 2 days)
      - series: 'job_last_success_timestamp_seconds{job="impact_rollup",instance="ingestion-service:8000"}'
        values: '-172300+0x15'
      # rollup: 600 s ago, fresh
      - series: 'job_last_success_timestamp_seconds{job="rollup",instance="ingestion-service:8000"}'
        values: '0+0x15'
    alert_rule_test:
      - eval_time: 10m
        alertname: JobStale
        exp_alerts:
          - exp_labels: {severity: warning, job: impact_rollup, instance: "ingestion-service:8000"}
            exp_annotations: {summary: "Job impact_rollup has not succeeded for over twice its interval"}

  - name: JobStale leaves a one-day-old impact_rollup alone
    interval: 1m
    input_series:
      # 86,600 s ago at eval_time 10m: one day, under two
      - series: 'job_last_success_timestamp_seconds{job="impact_rollup",instance="ingestion-service:8000"}'
        values: '-86000+0x15'
    alert_rule_test:
      - eval_time: 10m
        alertname: JobStale
        exp_alerts: []

  - name: JobFailing after 30 minutes of an error newer than the last success
```

Run: `bash monitoring/check.sh`
Expected: FAIL in "promtool: rule unit tests" with `JobStale gives impact_rollup two days` (expected the impact_rollup alert, got none).

- [ ] **Step 4: Add the rule**

In `monitoring/prometheus/alerts.yml`, with the Edit tool, replace:

```yaml
      # 2x each job's interval: retention 24 h, rollup 6 h, weekly summary 30 min (Ruling 6)
      - alert: JobStale
        expr: |
          time() - job_last_success_timestamp_seconds{job="retention"} > 2 * 86400
          or time() - job_last_success_timestamp_seconds{job="rollup"} > 12 * 3600
          or time() - job_last_success_timestamp_seconds{job="weekly_summary"} > 3600
```

with:

```yaml
      # 2x each job's interval: retention 24 h, rollup 6 h, weekly summary 30 min (Ruling 6), impact rollup 24 h
      - alert: JobStale
        expr: |
          time() - job_last_success_timestamp_seconds{job="retention"} > 2 * 86400
          or time() - job_last_success_timestamp_seconds{job="rollup"} > 12 * 3600
          or time() - job_last_success_timestamp_seconds{job="weekly_summary"} > 3600
          or time() - job_last_success_timestamp_seconds{job="impact_rollup"} > 2 * 86400
```

In `monitoring/grafana/dashboards/jobs-uploads.json`, with the Edit tool, replace:

```
"description": "Stale above 2 days (retention), 12 h (rollup), 1 h (weekly summary). never: no success since the service started"
```

with:

```
"description": "Stale above 2 days (retention, impact rollup), 12 h (rollup), 1 h (weekly summary). never: no success since the service started"
```

Run: `bash monitoring/check.sh`
Expected: ends with `monitoring: all checks passed`.

- [ ] **Step 5: Add the compose service**

In `docker-compose.yml`, with the Edit tool, replace:

```yaml
  # Sends last week's summary to channels that ask for it, Mondays from
```

with:

```yaml
  # Rebuilds the test impact statistics (impact_pairs, impact_test_base): one pass on start, then every 24 hours.
  # One-off history replay: docker compose run --rm impact-rollup python -m src.ingestion.jobs.impact_rollup --backfill-days 30
  impact-rollup:
    image: qeos/ingestion-service:local
    pull_policy: never
    environment: *ingestion-env
    command: ["python", "-m", "src.ingestion.jobs.impact_rollup", "--loop"]
    depends_on:
      ingestion-migrate:
        condition: service_completed_successfully

  # Sends last week's summary to channels that ask for it, Mondays from
```

and replace:

```yaml
      analytics-rollup:
        condition: service_started
      weekly-summary:
        condition: service_started
```

with:

```yaml
      analytics-rollup:
        condition: service_started
      impact-rollup:
        condition: service_started
      weekly-summary:
        condition: service_started
```

In `deploy/docker-compose.prod.yml`, with the Edit tool, replace:

```yaml
  analytics-rollup:
    restart: unless-stopped
```

with:

```yaml
  analytics-rollup:
    restart: unless-stopped
  impact-rollup:
    restart: unless-stopped
```

Run: `SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose config --services | grep -x impact-rollup`
Expected: `impact-rollup`.

- [ ] **Step 6: See the architecture check fail**

Run: `python scripts/check_architecture_docs.py`
Expected: exit 1. The output names `impact-rollup` three times: not drawn in the README diagram, not listed in the README component table, and missing from the blueprint banner's Services row.

- [ ] **Step 7: Update the architecture docs**

In `README.md`, with the Edit tool, replace:

```
            JOBS["jobs: ingestion-retention<br/>analytics-rollup · weekly-summary"]
```

with:

```
            JOBS["jobs: ingestion-retention<br/>analytics-rollup · impact-rollup · weekly-summary"]
```

and replace:

```
`ingestion-retention`, `analytics-rollup` (flaky rollups) and `weekly-summary`: containers of the ingestion image |
```

with:

```
`ingestion-retention`, `analytics-rollup` (flaky rollups), `impact-rollup` (test impact statistics) and `weekly-summary`: containers of the ingestion image |
```

In `ARCHITECTURE_BLUEPRINT_V1_0.md`, with the Edit tool, replace:

```
ingestion-retention + analytics-rollup + weekly-summary jobs |
```

with:

```
ingestion-retention + analytics-rollup + impact-rollup + weekly-summary jobs |
```

In `TECHNICAL_SPECIFICATION.md`, with the Edit tool, replace:

```
jobs: ingestion-retention, analytics-rollup, weekly-summary (ingestion image, advisory locks)
```

with:

```
jobs: ingestion-retention, analytics-rollup, impact-rollup, weekly-summary (ingestion image, advisory locks)
```

and replace:

```
  every 6 h, lock 7351002); `weekly-summary` (Mondays, once per channel per
  week, lock 7351003).
```

with:

```
  every 6 h, lock 7351002); `weekly-summary` (Mondays, once per channel per
  week, lock 7351003); `impact-rollup` (test impact statistics: impact_pairs
  and impact_test_base over 90 days, every 24 h, lock 7351004; ADR-029).
```

In `docs/SETUP.md`, with the Edit tool, replace:

```
  (`ingestion-retention`, `analytics-rollup`, `weekly-summary`) and finally the gateway.
```

with:

```
  (`ingestion-retention`, `analytics-rollup`, `impact-rollup`, `weekly-summary`) and finally the gateway.
```

In `platforms/ingestion-service/README.md`, with the Edit tool, replace:

```
for `retention`, `rollup` and `weekly_summary` (always present;
```

with:

```
for `retention`, `rollup`, `weekly_summary` and `impact_rollup` (always present;
```

- [ ] **Step 8: Run the checks**

Run: `python scripts/check_architecture_docs.py && python -m pytest scripts/tests -q`
Expected: no findings (exit 0) and the script's tests pass.

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_heartbeat_metrics.py tests/integration/test_job_heartbeats.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/jobs/heartbeat.py platforms/ingestion-service/tests/integration/test_heartbeat_metrics.py docker-compose.yml deploy/docker-compose.prod.yml monitoring/prometheus/alerts.yml monitoring/prometheus/tests/alerts.test.yml monitoring/grafana/dashboards/jobs-uploads.json README.md ARCHITECTURE_BLUEPRINT_V1_0.md TECHNICAL_SPECIFICATION.md docs/SETUP.md platforms/ingestion-service/README.md
git commit -m "feat(stack): impact-rollup compose job with heartbeat and JobStale at two days" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/jobs/heartbeat.py platforms/ingestion-service/tests/integration/test_heartbeat_metrics.py docker-compose.yml deploy/docker-compose.prod.yml monitoring/prometheus/alerts.yml monitoring/prometheus/tests/alerts.test.yml monitoring/grafana/dashboards/jobs-uploads.json README.md ARCHITECTURE_BLUEPRINT_V1_0.md TECHNICAL_SPECIFICATION.md docs/SETUP.md platforms/ingestion-service/README.md
```

---

### Task 7: The suggestion stored at upload, and its outcome

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/service/impact_service.py`
- Modify: `platforms/ingestion-service/src/ingestion/service/ingest_service.py`, `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py`, `platforms/ingestion-service/README.md`
- Test: `platforms/ingestion-service/tests/integration/test_impact_upload.py`

**Interfaces:**
- Consumes:
  - Tasks 1–5: `RunImpact`, `ImpactPair`, `ImpactTestBase`, `change_units`, `ChangedFiles`, `MIN_CHANGED_RUNS`, `MODEL_VERSION`, `WINDOW_DAYS`, `FAILING`, `suggest`, `PairStat`, `BaseStat`, `ImpactTest`, `run_outcomes`, `newly_failed_in_run`, `live_excluded`.
  - Existing: `in_list`, `as_utc`.
- Produces, in `src.ingestion.service.impact_service`:
  - Scoring:
    - `history_runs(db, project_id: int, until: datetime) -> int`;
    - `failing_on_branch(db, project_id: int, branch: Optional[str], before: datetime) -> List[ImpactTest]`;
    - `load_statistics(db, project_id: int, units: Set[str]) -> Tuple[List[PairStat], Dict[str, BaseStat]]`;
    - `score_change(db, project_id: int, changed_paths: Sequence[str], branch: Optional[str], *, now: datetime) -> dict` (the suggestion dict of Task 3).
  - Storing:
    - `Scored(suggestion: dict, scored_at: datetime)`, a frozen dataclass;
    - `score_upload(db, project_id, changed_paths, branch, started_at) -> Optional[Scored]` (never raises);
    - `stored_suggestion(run_id: int, scored: Scored, *, replayed: bool) -> RunImpact`;
    - `record_outcome(row: RunImpact, newly: Sequence[ImpactTest], now: datetime) -> None`;
    - `evaluate_run(session_factory: sessionmaker, run_id: int) -> None` (never raises).
  - Behaviour: an upload with changed files stores a `run_impact` row in its transaction, and the outcome follows after the response.

- [ ] **Step 1: Write the failing tests**

Create `platforms/ingestion-service/tests/integration/test_impact_upload.py`:

```python
"""The suggestion stored with an upload, scored before its results, and its outcome (spec 2026-10-12 §3.4; plan
Rulings 1, 2, 16)."""
from datetime import datetime, timedelta, timezone

from src.ingestion.models import Run, RunResult
from src.ingestion.models.impact import ImpactTestBase, RunImpact
from src.ingestion.models.muted import MutedTest
from src.ingestion.service import impact_service
from src.ingestion.service.ingest_service import test_key as key_of

URL = "/api/v1/collect/runs"
PAYS, CART = key_of("s", "C", "pays"), key_of("s", "C", "cart")


def hours_ago(hours):
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def upload(client, key, results, paths=("src/pay/api.py",), branch="main", started=None, idempotency_key=None,
           base_branch=None):
    started = started or hours_ago(0.1)
    run = {"ci_provider": "local", "branch": branch, "started_at": started.isoformat(),
           "finished_at": (started + timedelta(seconds=30)).isoformat()}
    if base_branch:
        run["base_branch"] = base_branch
    body = {"run": run, "results": [{"suite": "s", "class_name": "C", "name": name, "status": status, "duration_ms": 5}
                                    for name, status in results]}
    if paths is not None:
        body["changes"] = {"base_ref": "origin/main", "truncated": False,
                           "files": [{"path": p, "status": "M", "additions": 1, "deletions": 0} for p in paths]}
    headers = {"Authorization": f"Bearer {key}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    response = client.post(URL, json=body, headers=headers)
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def stored(db, run_id):
    db.expire_all()
    return db.get(RunImpact, run_id)


def base_row(name, runs, flaky=False):
    return ImpactTestBase(project_id=1, test_key=key_of("s", "C", name), runs=runs, new_failures=0, flaky=flaky,
                          suite="s", class_name="C", name=name, file=None, computed_at=hours_ago(5))


def test_the_suggestion_is_stored_with_the_run_and_the_outcome_follows(client, db, make_key, seed_change_run):
    seed_change_run(hours_ago(3), results=(("pays", "passed", 5), ("old", "failed", 5)))
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed"), ("old", "failed")]))
    assert (row.model_version, row.replayed) == ("stats-v1", False)
    assert row.suggested["state"] == "not_enough_history"
    assert [(t["name"], t["kind"]) for t in row.suggested["tests"]] == [("old", "failing_on_branch")]
    assert row.caught == [] and [t["name"] for t in row.missed] == ["pays"]  # old failed before: not new
    assert row.evaluated_at is not None


def test_the_suggestion_never_sees_its_own_run_or_results(client, db, make_key, seed_change_run, monkeypatch):
    seed_change_run(hours_ago(3), results=(("pays", "passed", 5),))
    seen = {}
    real = impact_service.score_change

    def spy(session, project_id, changed_paths, branch, *, now):
        seen["runs"], seen["results"] = session.query(Run).count(), session.query(RunResult).count()
        return real(session, project_id, changed_paths, branch, now=now)

    monkeypatch.setattr(impact_service, "score_change", spy)
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed"), ("new", "failed")]))
    assert seen == {"runs": 1, "results": 1}  # only the seeded run: neither this run nor its results existed yet
    assert row.suggested["tests"] == []       # its own failures are not "failing on this branch"


def test_a_suggested_test_that_newly_fails_is_caught(client, db, make_key, seed_change_run):
    seed_change_run(hours_ago(3), results=(("pays", "passed", 5),))
    db.add(base_row("pays", runs=1))
    db.commit()
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed")]))
    assert [(t["name"], t["kind"]) for t in row.suggested["tests"]] == [("pays", "no_history")]
    assert [t["name"] for t in row.caught] == ["pays"] and row.missed == []


def test_muted_and_flagged_flaky_tests_are_left_out_of_the_outcome(client, db, make_key, seed_change_run):
    seed_change_run(hours_ago(3), results=(("pays", "passed", 5), ("cart", "passed", 5)))
    db.add(MutedTest(project_id=1, test_key=PAYS, muted_by_user_id=1))
    db.add(base_row("cart", runs=9, flaky=True))
    db.commit()
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed"), ("cart", "failed")]))
    assert row.caught == [] and row.missed == []


def test_a_new_branch_is_compared_with_its_base_branch(client, db, make_key, seed_run):
    seed_run(hours_ago(3), results=(("pays", "passed", 5),), branch="main")
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed")], branch="feature/pay", base_branch="main"))
    assert [t["name"] for t in row.missed] == ["pays"]


def test_a_late_upload_reads_the_branch_as_it_was_before_the_run(client, db, make_key, seed_run):
    seed_run(hours_ago(5), results=(("early", "failed", 5),))
    seed_run(hours_ago(1), results=(("later", "failed", 5),))
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "passed")], started=hours_ago(3)))
    assert [t["name"] for t in row.suggested["tests"]] == ["early"]


def test_no_suggestion_without_changed_files(client, db, make_key):
    _, key = make_key(project_id=1)
    assert stored(db, upload(client, key, [("pays", "failed")], paths=None)) is None
    assert stored(db, upload(client, key, [("pays", "failed")], paths=())) is None


def test_a_replayed_upload_is_not_scored_again(client, db, make_key, monkeypatch):
    _, key = make_key(project_id=1)
    started = hours_ago(1)
    run_id = upload(client, key, [("pays", "passed")], started=started, idempotency_key="ci-1")
    calls = []
    monkeypatch.setattr(impact_service, "score_change", lambda *args, **kwargs: calls.append(1) or {})
    assert upload(client, key, [("pays", "passed")], started=started, idempotency_key="ci-1") == run_id
    assert calls == [] and db.query(RunImpact).count() == 1


def test_a_failing_scoring_never_fails_the_upload(client, db, make_key, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise RuntimeError("scoring broke")

    monkeypatch.setattr(impact_service, "score_change", boom)
    _, key = make_key(project_id=1)
    run_id = upload(client, key, [("pays", "failed")])
    assert db.query(RunResult).filter_by(run_id=run_id).count() == 1
    assert stored(db, run_id) is None
    err = capsys.readouterr().err
    assert '"event": "impact_failed"' in err and '"step": "score"' in err and "scoring broke" not in err


def test_a_failing_outcome_keeps_the_suggestion_without_one(client, db, make_key, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise RuntimeError("outcome broke")

    monkeypatch.setattr(impact_service, "newly_failed_in_run", boom)
    _, key = make_key(project_id=1)
    row = stored(db, upload(client, key, [("pays", "failed")]))
    assert row is not None and row.evaluated_at is None and row.caught is None
    assert '"step": "outcome"' in capsys.readouterr().err


def test_a_truncated_change_list_is_still_scored(client, db, make_key):
    _, key = make_key(project_id=1)
    started = hours_ago(0.1)
    body = {"run": {"ci_provider": "local", "branch": "main", "started_at": started.isoformat(),
                    "finished_at": (started + timedelta(seconds=30)).isoformat()},
            "results": [{"suite": "s", "class_name": "C", "name": "pays", "status": "passed", "duration_ms": 5}],
            "changes": {"base_ref": "origin/main", "truncated": True,
                        "files": [{"path": "src/a.py", "status": "M", "additions": 1, "deletions": 0}]}}
    response = client.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 201
    assert stored(db, response.json()["id"]) is not None
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_upload.py -q`
Expected: FAIL, `ImportError: cannot import name 'impact_service' from 'src.ingestion.service'`.

- [ ] **Step 3: Write the scoring and storing module**

Create `platforms/ingestion-service/src/ingestion/service/impact_service.py`:

```python
"""Test impact scoring (spec 2026-10-12 §3.3, §3.4; plan Rulings 1, 2): a change scored against the stored
statistics; an upload's suggestion scored before its run row or results exist and stored with the run; the outcome
written right after the response from the stored results. Neither step can fail an upload."""
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.analytics.impact_rules import (
    FAILING, MIN_CHANGED_RUNS, MODEL_VERSION, WINDOW_DAYS, ChangedFiles, change_units,
)
from src.ingestion.analytics.impact_score import BaseStat, ImpactTest, PairStat, suggest
from src.ingestion.analytics.trends import as_utc
from src.ingestion.models import Run
from src.ingestion.models.impact import ImpactPair, ImpactTestBase, RunImpact
from src.ingestion.service.impact_history import newly_failed_in_run, run_outcomes
from src.ingestion.service.impact_stats import live_excluded
from src.ingestion.service.report_service import in_list


def history_runs(db: Session, project_id: int, until: datetime) -> int:
    """Runs with changed files, not truncated, started in the 90 days before `until` ("not enough history" below 20)."""
    return db.execute(
        select(func.count()).select_from(Run).where(
            Run.project_id == project_id, Run.started_at >= until - timedelta(days=WINDOW_DAYS), Run.started_at < until,
            Run.changed_files > 0, or_(Run.changes_truncated.is_(None), Run.changes_truncated.is_(False)))
    ).scalar_one()


def failing_on_branch(db: Session, project_id: int, branch: Optional[str], before: datetime) -> List[ImpactTest]:
    """The failing tests of the branch's latest run started before `before`, by name."""
    if branch is None:
        return []
    latest = db.execute(
        select(Run.id).where(Run.project_id == project_id, Run.branch == branch, Run.started_at < before)
        .order_by(Run.started_at.desc(), Run.id.desc()).limit(1)
    ).scalar()
    if latest is None:
        return []
    return sorted((test for status, test in run_outcomes(db, latest).values() if status in FAILING),
                  key=lambda t: (t.name, t.test_key))


_BASE_COLUMNS = (ImpactTestBase.test_key, ImpactTestBase.suite, ImpactTestBase.class_name, ImpactTestBase.name,
                 ImpactTestBase.runs, ImpactTestBase.new_failures, ImpactTestBase.file, ImpactTestBase.flaky)


def load_statistics(db: Session, project_id: int, units: Set[str]) -> Tuple[List[PairStat], Dict[str, BaseStat]]:
    """The rows one scoring reads: the change's pairs, their tests' base rows, and the base rows that can carry a
    label (a recorded test file, or fewer than 3 runs)."""
    pairs: List[PairStat] = []
    if units:
        pairs = [PairStat(*row) for row in db.execute(
            select(ImpactPair.path_unit, ImpactPair.test_key, ImpactPair.changed_runs, ImpactPair.new_failures)
            .where(ImpactPair.project_id == project_id, in_list(db, ImpactPair.path_unit, sorted(units))))]
    wanted = [ImpactTestBase.file.is_not(None), ImpactTestBase.runs < MIN_CHANGED_RUNS]
    keys = sorted({p.test_key for p in pairs})
    if keys:
        wanted.append(in_list(db, ImpactTestBase.test_key, keys))
    bases: Dict[str, BaseStat] = {}
    for key, suite, class_name, name, runs, new_failures, file, flaky in db.execute(
            select(*_BASE_COLUMNS).where(ImpactTestBase.project_id == project_id, or_(*wanted))):
        bases[key] = BaseStat(ImpactTest(key, suite, class_name, name), runs, new_failures, file, flaky)
    return pairs, bases


def score_change(db: Session, project_id: int, changed_paths: Sequence[str], branch: Optional[str], *,
                 now: datetime) -> dict:
    """The suggestion for a change as of `now` (spec §3.3)."""
    units = change_units(changed_paths)
    pairs, bases = load_statistics(db, project_id, units)
    return suggest(units, pairs, bases, history_runs=history_runs(db, project_id, now),
                   changed_files=ChangedFiles(changed_paths),
                   failing_on_branch=failing_on_branch(db, project_id, branch, now))


@dataclass(frozen=True)
class Scored:
    suggestion: dict
    scored_at: datetime


def _failed(step: str, exc: Exception) -> None:
    # The exception type only: a message could carry data from the upload
    print(json.dumps({"event": "impact_failed", "step": step, "error": type(exc).__name__}), file=sys.stderr, flush=True)


def score_upload(db: Session, project_id: int, changed_paths: Sequence[str], branch: Optional[str],
                 started_at: datetime) -> Optional[Scored]:
    """An upload's suggestion, scored before its run row or any of its results exists (spec §3.4), as of the run's
    start. Never raises: on failure the upload carries on without one, and the rollback loses nothing because
    nothing of the upload is written yet."""
    if not changed_paths:
        return None
    try:
        suggestion = score_change(db, project_id, changed_paths, branch, now=as_utc(started_at))
        return Scored(suggestion, datetime.now(timezone.utc))
    except Exception as exc:
        db.rollback()
        _failed("score", exc)
        return None


def stored_suggestion(run_id: int, scored: Scored, *, replayed: bool) -> RunImpact:
    return RunImpact(run_id=run_id, suggested=scored.suggestion, model_version=MODEL_VERSION, replayed=replayed,
                     scored_at=scored.scored_at)


def record_outcome(row: RunImpact, newly: Sequence[ImpactTest], now: datetime) -> None:
    """Caught: the new failures the suggestion named, in any kind; missed: the others."""
    named = {test["test_key"] for test in row.suggested["tests"]}
    row.caught = [t.out() for t in newly if t.test_key in named]
    row.missed = [t.out() for t in newly if t.test_key not in named]
    row.evaluated_at = now


def evaluate_run(session_factory: sessionmaker, run_id: int) -> None:
    """After the upload's response: the run's new failures against its stored suggestion. Never raises."""
    try:
        with session_factory() as db:
            row, run = db.get(RunImpact, run_id), db.get(Run, run_id)
            if row is None or run is None or row.evaluated_at is not None:
                return
            excluded = live_excluded(db, run.project_id)
            record_outcome(row, newly_failed_in_run(db, run, excluded), datetime.now(timezone.utc))
            db.commit()
    except Exception as exc:
        _failed("outcome", exc)
```

- [ ] **Step 4: Score in the upload, before the run row**

In `platforms/ingestion-service/src/ingestion/service/ingest_service.py`, with the Edit tool, replace:

```python
from src.ingestion.service import masking_pattern_service
```

with:

```python
from src.ingestion.service import impact_service, masking_pattern_service
```

then replace:

```python
        run.changes_truncated = upload.changes.truncated
    try:
        db.add(run)
```

with:

```python
        run.changes_truncated = upload.changes.truncated
    # Test impact (spec 2026-10-12 §3.4): scored before this run or any of its results exists, so it cannot see them
    changed_paths = [f.path for f in upload.changes.files] if upload.changes is not None else []
    scored = impact_service.score_upload(db, run.project_id, changed_paths, run.branch, meta.started_at)
    try:
        db.add(run)
```

then replace:

```python
        if upload.components:
            db.execute(insert(RunComponent), [
                {"run_id": run.id, "name": c.name, "sha": c.sha} for c in upload.components
            ])
```

with:

```python
        if upload.components:
            db.execute(insert(RunComponent), [
                {"run_id": run.id, "name": c.name, "sha": c.sha} for c in upload.components
            ])

        if scored is not None:
            db.add(impact_service.stored_suggestion(run.id, scored, replayed=False))
```

In `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py`, with the Edit tool, replace:

```python
from src.ingestion.service import ingest_service, notification_service, run_service
```

with:

```python
from src.ingestion.service import impact_service, ingest_service, notification_service, run_service
```

and replace:

```python
            background.add_task(notification_service.notify_run, sessionmaker(bind=db.get_bind()), run.id)
```

with:

```python
            background.add_task(notification_service.notify_run, sessionmaker(bind=db.get_bind()), run.id)
        if run.changed_files:
            # After the response, from the stored results: the outcome of the suggestion stored with the run (spec §3.4)
            background.add_task(impact_service.evaluate_run, sessionmaker(bind=db.get_bind()), run.id)
```

- [ ] **Step 5: Run the tests**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_upload.py tests/integration/test_collect_changes.py tests/integration/test_collect_endpoint.py tests/unit/test_ingest_service.py -q`
Expected: PASS. The existing upload tests are unchanged and still green.

Then the whole suite: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest -q`. Expected: all green.

- [ ] **Step 6: Document the upload behaviour**

In `platforms/ingestion-service/README.md`, with the Edit tool, replace:

```
## Operations
```

with:

```
### At upload

When an upload carries changed files, ingestion scores the change against the statistics **before** it stores the
run, so the suggestion cannot see the run's own results, and stores it in `run_impact` (model `stats-v1`) with the
run. Right after the response, a background task compares it with the run's new failures and writes `caught` and
`missed` (flaky and muted tests left out). A truncated change list is scored too. A failure of either step is logged
as `{"event": "impact_failed", "step": "score"|"outcome", "error": "<type>"}` and never fails the upload. A
collector upload split into parts is one run per part, so each part gets its own suggestion and outcome; a part
after the first may list the previous part's failures as *failing on this branch*. A replayed upload (same
Idempotency-Key) is not scored again.

The suggestion lists:

- statistical suggestions, at most 50: `changed_runs ≥ 3`, `new_failures ≥ 2` and `lift ≥ 2`, ordered by
  confidence then lift, each with its evidence;
- always-included tests outside that cap, each test once and at most 100 per label: *test file changed* (the
  test's recorded file and a changed path end one another), *failing on this branch* (the branch's latest run
  before this one), *no history yet* (fewer than 3 runs with changed files).

Below 20 runs with changed files in the 90 days before, it answers "not enough history" and lists only the labels.

## Operations
```

- [ ] **Step 7: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/service/impact_service.py platforms/ingestion-service/src/ingestion/service/ingest_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py platforms/ingestion-service/tests/integration/test_impact_upload.py platforms/ingestion-service/README.md
git commit -m "feat(ingestion): store each upload's test impact suggestion before its results, then its outcome" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/service/impact_service.py platforms/ingestion-service/src/ingestion/service/ingest_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py platforms/ingestion-service/tests/integration/test_impact_upload.py platforms/ingestion-service/README.md
```

---

### Task 8: Replay with `--backfill-days`

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/service/impact_replay.py`
- Modify: `platforms/ingestion-service/src/ingestion/jobs/impact_rollup.py`, `platforms/ingestion-service/README.md`
- Test: `platforms/ingestion-service/tests/integration/test_impact_replay.py`

**Interfaces:**
- Consumes:
  - Tasks 2–7: `WINDOW_DAYS`, `ChangedFiles`, `change_units`, `suggest`, `PairStat`, `change_runs`, `flaky_keys`, `newly_failed_in_run`, `build_statistics`, `Scored`, `failing_on_branch`, `history_runs`, `record_outcome`, `stored_suggestion`, `RunImpact`.
  - Existing: `analytics_service.muted_keys`, `in_list`.
- Produces:
  - In `src.ingestion.service.impact_replay`: `replay_project(db, project_id: int, start: datetime, now: datetime) -> int`, the number of runs stored.
  - In `src.ingestion.jobs.impact_rollup`:
    - `run_backfill(db, days: int, now: Callable[[], datetime] = ...) -> dict` (`{"event": "impact_backfill", "days", "projects", "runs_replayed"}`);
    - `run_backfill_once(*, session_factory, lock_engine, days: int) -> bool`;
    - `main` accepts `--backfill-days N` (1–90, refused with `--loop`; no heartbeat; Ruling 13).

- [ ] **Step 1: Write the failing tests**

Create `platforms/ingestion-service/tests/integration/test_impact_replay.py`:

```python
"""Replay (spec 2026-10-12 §3.6, plan Ruling 13): past runs scored with statistics from earlier days only, stored as
replayed with their real outcome."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.analytics import impact_score
from src.ingestion.jobs import impact_rollup
from src.ingestion.models.impact import RunImpact
from src.ingestion.models.job_heartbeat import JobHeartbeat

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
EMPTY = {"state": "ok", "history_runs": 0, "needed_runs": 20, "statistical_total": 0, "tests": []}


@pytest.fixture(autouse=True)
def ten_runs_are_enough(monkeypatch):
    monkeypatch.setattr(impact_score, "MIN_HISTORY_RUNS", 10)


def row(db, run_id):
    db.expire_all()
    return db.get(RunImpact, run_id)


def backfill(db, days=30):
    return impact_rollup.run_backfill(db, days, now=lambda: NOW)


def test_a_replayed_run_is_scored_from_the_days_before_it_only(db, seed_impact_history, seed_change_run):
    history = seed_impact_history(start=NOW - timedelta(days=15))  # one run a day, days -15 to -1, at 12:00
    today = seed_change_run(NOW - timedelta(hours=1), results=(("pays", "passed", 5), ("steady", "passed", 5)),
                            paths=("src/pay/new.py",))
    assert backfill(db)["runs_replayed"] == 16
    # Day -1: pays newly failed; before that day src/pay/ had 3 change runs and 1 new failure, too few
    last = row(db, history[-1].id)
    assert last.replayed is True and last.suggested["history_runs"] == 14
    assert [t["kind"] for t in last.suggested["tests"]] == []
    assert [t["name"] for t in last.missed] == ["pays"] and last.caught == []
    # Today: the 15 earlier runs, so pays qualifies from statistics
    pays = next(t for t in row(db, today.id).suggested["tests"] if t["name"] == "pays")
    assert pays["kind"] == "statistical"
    assert pays["evidence"] == {"path_unit": "src/pay/", "changed_runs": 4, "new_failures": 2,
                                "confidence": 0.5, "lift": 3.75, "base_rate": 0.1333}


def test_replay_keeps_live_suggestions_and_a_second_replay_adds_nothing(db, seed_change_run):
    live = seed_change_run(NOW - timedelta(hours=3), results=(("pays", "passed", 5),))
    other = seed_change_run(NOW - timedelta(hours=2), results=(("pays", "failed", 5),))
    db.add(RunImpact(run_id=live.id, suggested=EMPTY, model_version="stats-v1", replayed=False, scored_at=NOW))
    db.commit()
    assert backfill(db)["runs_replayed"] == 1
    assert row(db, live.id).replayed is False and row(db, live.id).evaluated_at is None
    assert row(db, other.id).replayed is True and [t["name"] for t in row(db, other.id).missed] == ["pays"]
    assert backfill(db)["runs_replayed"] == 0


def test_only_the_requested_days_are_replayed(db, seed_change_run):
    old = seed_change_run(NOW - timedelta(days=8))
    recent = seed_change_run(NOW - timedelta(days=2))
    backfill(db, days=7)
    assert row(db, old.id) is None and row(db, recent.id) is not None


def test_a_truncated_run_is_replayed_too(db, seed_change_run):
    run = seed_change_run(NOW - timedelta(days=1), truncated=True)
    backfill(db, days=7)
    assert row(db, run.id).replayed is True


@pytest.mark.parametrize("value", ["0", "91", "x"])
def test_backfill_days_must_be_1_to_90(value):
    with pytest.raises(SystemExit):
        impact_rollup.main(["--backfill-days", value])


def test_backfill_refuses_loop():
    with pytest.raises(SystemExit):
        impact_rollup.main(["--backfill-days", "30", "--loop"])


def test_a_backfill_is_not_the_nightly_pass_so_it_writes_no_heartbeat(db, seed_change_run, capsys):
    seed_change_run(datetime.now(timezone.utc) - timedelta(days=1))
    factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
    assert impact_rollup.main(["--backfill-days", "7"], session_factory=factory) == 0
    db.expire_all()
    assert db.get(JobHeartbeat, "impact_rollup") is None
    assert '"runs_replayed": 1' in capsys.readouterr().out
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_replay.py -q`
Expected: FAIL with `AttributeError: module 'src.ingestion.jobs.impact_rollup' has no attribute 'run_backfill'`. The argument tests fail because `--backfill-days` is unknown: argparse exits, but `test_a_backfill_is_not_the_nightly_pass...` fails.

- [ ] **Step 3: Write the replay module**

Create `platforms/ingestion-service/src/ingestion/service/impact_replay.py`:

```python
"""Replay (spec 2026-10-12 §3.6, plan Ruling 13): score past runs with changed files as if at upload, with statistics
built only from runs started before the run's day, and store each with its real outcome, marked replayed."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List

from sqlalchemy import Integer, select
from sqlalchemy.orm import Session

from src.ingestion.analytics.impact_rules import WINDOW_DAYS, ChangedFiles, change_units
from src.ingestion.analytics.impact_score import PairStat, suggest
from src.ingestion.models import Run
from src.ingestion.models.impact import RunImpact
from src.ingestion.service import analytics_service
from src.ingestion.service.impact_history import ChangeRun, change_runs, flaky_keys, newly_failed_in_run
from src.ingestion.service.impact_service import (
    Scored, failing_on_branch, history_runs, record_outcome, stored_suggestion,
)
from src.ingestion.service.impact_stats import build_statistics
from src.ingestion.service.report_service import in_list


def replay_project(db: Session, project_id: int, start: datetime, now: datetime) -> int:
    """Runs with changed files started in [start, now) that have no stored suggestion; returns how many were stored.
    A live suggestion is never replaced, so a second replay finds nothing left to do."""
    targets = change_runs(db, project_id, start, now, include_truncated=True)
    if not targets:
        return 0
    stored = {run_id for (run_id,) in db.execute(
        select(RunImpact.run_id).where(in_list(db, RunImpact.run_id, [r.id for r in targets], Integer)))}
    pending = [run for run in targets if run.id not in stored]
    if not pending:
        return 0
    # Flaky and muted as known now: one set leaves tests out of the statistics and the outcomes alike
    flaky = flaky_keys(db, project_id, now - timedelta(days=WINDOW_DAYS))
    muted = analytics_service.muted_keys(db, project_id)
    by_day: Dict[date, List[ChangeRun]] = defaultdict(list)
    for run in pending:
        by_day[run.started_at.date()].append(run)
    for day in sorted(by_day):
        day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        pairs, bases = build_statistics(db, project_id, day_start - timedelta(days=WINDOW_DAYS), day_start, flaky, muted)
        by_unit: Dict[str, List[PairStat]] = defaultdict(list)
        for pair in pairs:
            by_unit[pair.path_unit].append(pair)
        by_key = {base.test.test_key: base for base in bases}
        before = history_runs(db, project_id, day_start)
        for change in by_day[day]:
            units = change_units(change.paths)
            suggestion = suggest(units, [p for unit in units for p in by_unit.get(unit, ())], by_key,
                                 history_runs=before, changed_files=ChangedFiles(change.paths),
                                 failing_on_branch=failing_on_branch(db, project_id, change.branch, change.started_at))
            row = stored_suggestion(change.id, Scored(suggestion, now), replayed=True)
            record_outcome(row, newly_failed_in_run(db, db.get(Run, change.id), flaky | muted), now)
            db.add(row)
        db.commit()
    return len(pending)
```

- [ ] **Step 4: Add `--backfill-days` to the job**

In `platforms/ingestion-service/src/ingestion/jobs/impact_rollup.py`, with the Edit tool, replace:

```python
    python -m src.ingestion.jobs.impact_rollup [--loop]
```

with:

```python
    python -m src.ingestion.jobs.impact_rollup [--loop]
    python -m src.ingestion.jobs.impact_rollup --backfill-days 30   (one-off replay, spec §3.6)
```

then replace:

```python
from src.ingestion.service.impact_history import flaky_keys
from src.ingestion.service.impact_stats import build_statistics, replace_statistics
```

with:

```python
from src.ingestion.service.impact_history import flaky_keys
from src.ingestion.service.impact_replay import replay_project
from src.ingestion.service.impact_stats import build_statistics, replace_statistics
```

then replace the whole block from `def main(` to the end of the file:

```python
def main(
    argv: Optional[list] = None,
    *,
    session_factory: Optional[sessionmaker] = None,
    lock_engine: Optional[Engine] = None,
    stop: Optional[threading.Event] = None,
    interval_hours: float = DEFAULT_INTERVAL_HOURS,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true", help="run forever, one pass every 24 hours")
    args = parser.parse_args(argv)

    if session_factory is None:
        from src.ingestion.db.session import SessionLocal

        session_factory = SessionLocal
    if lock_engine is None:
        lock_engine = session_factory.kw["bind"]

    stop = stop or threading.Event()
    ok = run_once(session_factory=session_factory, lock_engine=lock_engine)
    if not args.loop:
        return 0 if ok else 1
    while not stop.wait(interval_hours * 3600):
        run_once(session_factory=session_factory, lock_engine=lock_engine)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

with:

```python
def run_backfill(db: Session, days: int, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Replay the last `days` days of every project (plan Ruling 13)."""
    moment = now()
    projects = sorted({pid for (pid,) in db.execute(select(Run.project_id).distinct())})
    replayed = sum(replay_project(db, project_id, moment - timedelta(days=days), moment) for project_id in projects)
    summary = {"event": "impact_backfill", "days": days, "projects": len(projects), "runs_replayed": replayed}
    _log(summary)
    return summary


def run_backfill_once(*, session_factory: sessionmaker, lock_engine: Engine, days: int) -> bool:
    """A one-off replay under the job's lock. Not the nightly pass, so no heartbeat either way."""
    try:
        with _advisory_lock(lock_engine) as acquired:
            if not acquired:
                _log({"event": "impact_backfill", "skipped": "another copy holds the lock"}, error=True)
                return False
            with session_factory() as db:
                run_backfill(db, days)
    except Exception as exc:
        _log({"event": "impact_backfill", "error": f"{type(exc).__name__}: {exc}"}, error=True)
        return False
    return True


def _days(value: str) -> int:
    days = int(value)
    if not 1 <= days <= WINDOW_DAYS:
        raise argparse.ArgumentTypeError(f"must be 1 to {WINDOW_DAYS}")
    return days


def main(
    argv: Optional[list] = None,
    *,
    session_factory: Optional[sessionmaker] = None,
    lock_engine: Optional[Engine] = None,
    stop: Optional[threading.Event] = None,
    interval_hours: float = DEFAULT_INTERVAL_HOURS,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true", help="run forever, one pass every 24 hours")
    parser.add_argument("--backfill-days", type=_days, metavar="N",
                        help="one-off: replay the last N days (1-90) of runs with changed files, then exit")
    args = parser.parse_args(argv)
    if args.backfill_days is not None and args.loop:
        parser.error("--backfill-days runs once: leave out --loop")

    if session_factory is None:
        from src.ingestion.db.session import SessionLocal

        session_factory = SessionLocal
    if lock_engine is None:
        lock_engine = session_factory.kw["bind"]

    if args.backfill_days is not None:
        ok = run_backfill_once(session_factory=session_factory, lock_engine=lock_engine, days=args.backfill_days)
        return 0 if ok else 1

    stop = stop or threading.Event()
    ok = run_once(session_factory=session_factory, lock_engine=lock_engine)
    if not args.loop:
        return 0 if ok else 1
    while not stop.wait(interval_hours * 3600):
        run_once(session_factory=session_factory, lock_engine=lock_engine)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_replay.py tests/integration/test_impact_rollup.py -q`
Expected: PASS.

- [ ] **Step 6: Document replay**

In `platforms/ingestion-service/README.md`, with the Edit tool, replace:

```
## Operations
```

with:

```
### Replay

`docker compose run --rm impact-rollup python -m src.ingestion.jobs.impact_rollup --backfill-days 30` (1 to 90
days, one-off, never with `--loop`) scores every run with changed files in those days that has no stored suggestion,
with statistics built only from runs started before that run's day (UTC), stores it with `replayed = true` and its
real outcome, and prints `{"event": "impact_backfill", ..., "runs_replayed": n}`. Live suggestions are never
replaced, so running it again adds nothing. Flaky and muted tests are the ones known at replay time. It takes the
job's lock and writes no heartbeat (it is not the nightly pass). Expect minutes on a large project: each replayed
day rebuilds 90 days of statistics.

## Operations
```

- [ ] **Step 7: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/service/impact_replay.py platforms/ingestion-service/src/ingestion/jobs/impact_rollup.py platforms/ingestion-service/tests/integration/test_impact_replay.py platforms/ingestion-service/README.md
git commit -m "feat(ingestion): replay past changes with --backfill-days, statistics from earlier days only" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/service/impact_replay.py platforms/ingestion-service/src/ingestion/jobs/impact_rollup.py platforms/ingestion-service/tests/integration/test_impact_replay.py platforms/ingestion-service/README.md
```

---

### Task 9: The three endpoints

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/schemas/impact.py`
- Create: `platforms/ingestion-service/src/ingestion/service/impact_read.py`
- Modify:
  - endpoints `platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py`, `platforms/ingestion-service/src/ingestion/api/v1/endpoints/analytics.py`;
  - docs `platforms/ingestion-service/README.md`, `TECHNICAL_SPECIFICATION.md`.
- Test: `platforms/ingestion-service/tests/integration/test_impact_endpoints.py`

**Interfaces:**
- Consumes:
  - Tasks 1–8: `RunImpact`, `RunChangedFile`, `MODEL_VERSION`, `score_change(db, project_id, changed_paths, branch, *, now)`.
  - Existing: `require_project_role(*READ_ROLES)`, `run_service.get_run`, `NO_NUL`, `analytics._now`, `as_utc`.
- Produces:
  - **Schemas** in `src.ingestion.schemas.impact`:
    - `ImpactTestOut{test_key, suite, class_name, name}`;
    - `ImpactEvidenceOut{path_unit, changed_runs, new_failures, confidence, lift, base_rate}`;
    - `SuggestedTestOut(ImpactTestOut){kind, evidence}`;
    - `SuggestionOut{state, model_version, history_runs, needed_runs, statistical_total, tests}`;
    - `OutcomeOut{evaluated_at, caught, missed}`;
    - `RunImpactOut{run_id, state: "ok"|"not_enough_history"|"no_change_data"|"not_scored", changed_paths, replayed=False, scored_at=None, suggestion=None, outcome=None}`;
    - `AccuracyPartOut{runs, caught, missed}`;
    - `MissOut(ImpactTestOut){run_id, started_at, branch, replayed}`;
    - `ImpactAccuracyOut{days, caught, missed, rate, includes_replayed, live, replayed, misses, misses_total}`.
  - **Readers** in `src.ingestion.service.impact_read`: `run_impact(db, run: Run) -> dict` and `accuracy(db, project_id: int, since: datetime, days: int) -> dict` (`MAX_MISSES = 50`).
  - **Routes:**
    - `GET /api/v1/projects/{id}/runs/{run_id}/impact` → `RunImpactOut`;
    - `POST /api/v1/projects/{id}/analytics/impact` → `SuggestionOut`;
    - `GET /api/v1/projects/{id}/analytics/impact-accuracy?days=7|14|30` → `ImpactAccuracyOut`.

- [ ] **Step 1: Write the failing tests**

Create `platforms/ingestion-service/tests/integration/test_impact_endpoints.py`:

```python
"""The three test impact endpoints (spec 2026-10-12 §3.5; plan Rulings 17, 18, 19): states, roles, limits, other
projects."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.ingestion.analytics import impact_score
from src.ingestion.api.deps import READ_ROLES
from src.ingestion.api.v1.endpoints import analytics
from src.ingestion.jobs import impact_rollup
from src.ingestion.models.impact import RunImpact
from src.ingestion.service.ingest_service import test_key as key_of

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
IMPACT = "/api/v1/projects/1/analytics/impact"
ACCURACY = "/api/v1/projects/1/analytics/impact-accuracy"


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(analytics, "_now", lambda: NOW)


@pytest.fixture
def viewer(project_role):
    project_role("viewer", project_id=1)


def run_url(run_id, project_id=1):
    return f"/api/v1/projects/{project_id}/runs/{run_id}/impact"


def ref(name):
    return {"test_key": key_of("s", "C", name), "suite": "s", "class_name": "C", "name": name}


def store(db, run, *, caught=(), missed=(), replayed=False, evaluated=True, tests=()):
    db.add(RunImpact(
        run_id=run.id, model_version="stats-v1", replayed=replayed, scored_at=NOW,
        suggested={"state": "ok", "history_runs": 25, "needed_runs": 20, "statistical_total": 0, "tests": list(tests)},
        caught=[ref(n) for n in caught] if evaluated else None, missed=[ref(n) for n in missed] if evaluated else None,
        evaluated_at=NOW if evaluated else None,
    ))
    db.commit()


# ---- GET /projects/{id}/runs/{run_id}/impact ----

def test_a_run_without_changed_files_has_no_change_data(client, auth, viewer, seed_run):
    run = seed_run(NOW - timedelta(hours=1))
    response = client.get(run_url(run.id), headers=auth())
    assert response.status_code == 200
    assert response.json() == {"run_id": run.id, "state": "no_change_data", "changed_paths": [], "replayed": False,
                               "scored_at": None, "suggestion": None, "outcome": None}


def test_changed_files_without_a_stored_suggestion_are_not_scored(client, auth, viewer, seed_change_run):
    run = seed_change_run(NOW - timedelta(hours=1))
    body = client.get(run_url(run.id), headers=auth()).json()
    assert (body["state"], body["changed_paths"], body["suggestion"]) == ("not_scored", ["src/app.py"], None)


def test_the_stored_suggestion_and_its_outcome(client, auth, viewer, seed_change_run, db):
    run = seed_change_run(NOW - timedelta(hours=1), paths=("src/pay/api.py",))
    store(db, run, missed=("pays",), tests=({**ref("old"), "kind": "failing_on_branch", "evidence": None},))
    body = client.get(run_url(run.id), headers=auth()).json()
    assert (body["state"], body["changed_paths"], body["replayed"]) == ("ok", ["src/pay/api.py"], False)
    assert body["suggestion"]["model_version"] == "stats-v1" and body["suggestion"]["history_runs"] == 25
    assert body["suggestion"]["tests"] == [{**ref("old"), "kind": "failing_on_branch", "evidence": None}]
    assert body["outcome"]["caught"] == [] and body["outcome"]["missed"] == [ref("pays")]


def test_a_suggestion_waiting_for_its_outcome(client, auth, viewer, seed_change_run, db):
    run = seed_change_run(NOW - timedelta(hours=1))
    store(db, run, evaluated=False)
    body = client.get(run_url(run.id), headers=auth()).json()
    assert body["state"] == "ok" and body["outcome"] is None


def test_a_run_of_another_project_is_not_found(client, auth, viewer, seed_change_run):
    other = seed_change_run(NOW - timedelta(hours=1), project_id=2)
    assert client.get(run_url(other.id), headers=auth()).status_code == 404
    assert client.get(run_url(999_999), headers=auth()).status_code == 404


@pytest.mark.parametrize("role", READ_ROLES)
def test_every_reading_role_reads_a_runs_impact(client, auth, project_role, seed_change_run, role):
    project_role(role, project_id=1)
    run = seed_change_run(NOW - timedelta(hours=1))
    assert client.get(run_url(run.id), headers=auth()).status_code == 200


def test_access_failures(client, auth, project_role, seed_change_run):
    run = seed_change_run(NOW - timedelta(hours=1))
    project_role(status_code=404, body={"detail": "Project not found"}, project_id=1)
    assert client.get(run_url(run.id), headers=auth()).status_code == 404
    project_role(exc=httpx.ConnectError("refused"), project_id=1)
    assert client.get(run_url(run.id), headers=auth()).status_code == 503
    assert client.get(run_url(run.id)).status_code == 401


# ---- POST /projects/{id}/analytics/impact ----

def test_scoring_a_change_suggests_from_the_statistics(client, auth, viewer, db, seed_impact_history, monkeypatch):
    monkeypatch.setattr(impact_score, "MIN_HISTORY_RUNS", 10)
    seed_impact_history(start=NOW - timedelta(days=15))
    impact_rollup.run_pass(db, now=lambda: NOW)
    response = client.post(IMPACT, json={"changed_paths": ["src/pay/new.py"], "branch": None}, headers=auth())
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["state"], body["model_version"], body["history_runs"]) == ("ok", "stats-v1", 15)
    assert [(t["name"], t["kind"]) for t in body["tests"]] == [("pays", "statistical")]


def test_the_branch_adds_its_failing_tests(client, auth, viewer, seed_run):
    seed_run(NOW - timedelta(hours=1), results=(("pays", "failed", 5),), branch="feature/x")
    body = client.post(IMPACT, json={"changed_paths": ["src/a.py"], "branch": "feature/x"}, headers=auth()).json()
    assert body["state"] == "not_enough_history"
    assert [(t["name"], t["kind"]) for t in body["tests"]] == [("pays", "failing_on_branch")]


def test_a_change_of_only_ignored_files_answers_with_labels_only(client, auth, viewer):
    response = client.post(IMPACT, json={"changed_paths": ["poetry.lock", "/"]}, headers=auth())
    assert response.status_code == 200 and response.json()["tests"] == []


def test_a_project_the_rollup_has_not_visited_answers_without_statistics(client, auth, viewer, seed_change_run):
    for day in range(1, 21):
        seed_change_run(NOW - timedelta(days=day))
    body = client.post(IMPACT, json={"changed_paths": ["src/app.py"]}, headers=auth()).json()
    assert (body["state"], body["history_runs"], body["tests"]) == ("ok", 20, [])


@pytest.mark.parametrize("body", [
    {"changed_paths": []},
    {"changed_paths": ["a"] * 5001},
    {"changed_paths": [""]},
    {"changed_paths": ["x" * 1001]},
    {"changed_paths": ["src/\u0000a.py"]},
    {"changed_paths": ["src/a.py"], "branch": "b" * 256},
    {"changed_paths": ["src/a.py"], "extra": 1},
    {"branch": "main"},
])
def test_input_limits(client, auth, viewer, body):
    assert client.post(IMPACT, json=body, headers=auth()).status_code == 422


def test_the_limits_themselves_pass(client, auth, viewer):
    body = {"changed_paths": [f"src/m{i}/f.py" for i in range(4999)] + ["x" * 1000], "branch": "b" * 255}
    assert client.post(IMPACT, json=body, headers=auth()).status_code == 200


# ---- GET /projects/{id}/analytics/impact-accuracy ----

def test_accuracy_counts_caught_and_missed_new_failures_in_the_window(client, auth, viewer, db, seed_change_run):
    a = seed_change_run(NOW - timedelta(days=2))
    store(db, a, caught=("pays", "cart"), missed=("ship",))
    store(db, seed_change_run(NOW - timedelta(days=5)), caught=("pays",))
    c = seed_change_run(NOW - timedelta(days=10))
    store(db, c, missed=("old",))
    store(db, seed_change_run(NOW - timedelta(days=1)), evaluated=False)  # outcome pending: not counted
    week = client.get(ACCURACY, params={"days": 7}, headers=auth()).json()
    assert (week["days"], week["caught"], week["missed"], week["rate"], week["includes_replayed"]) == (7, 3, 1, 0.75, False)
    assert week["live"] == {"runs": 2, "caught": 3, "missed": 1}
    assert week["replayed"] == {"runs": 0, "caught": 0, "missed": 0}
    assert [(m["name"], m["run_id"], m["replayed"]) for m in week["misses"]] == [("ship", a.id, False)]
    assert week["misses_total"] == 1
    month = client.get(ACCURACY, params={"days": 30}, headers=auth()).json()
    assert (month["caught"], month["missed"]) == (3, 2)
    assert [m["name"] for m in month["misses"]] == ["ship", "old"]  # newest run first


def test_replayed_and_live_parts_are_reported_apart(client, auth, viewer, db, seed_change_run):
    store(db, seed_change_run(NOW - timedelta(days=1)), caught=("pays",))
    store(db, seed_change_run(NOW - timedelta(days=3)), missed=("cart",), replayed=True)
    body = client.get(ACCURACY, headers=auth()).json()
    assert body["days"] == 30 and body["includes_replayed"] is True
    assert body["live"] == {"runs": 1, "caught": 1, "missed": 0}
    assert body["replayed"] == {"runs": 1, "caught": 0, "missed": 1}
    assert body["misses"][0]["replayed"] is True


def test_no_new_failures_has_no_rate(client, auth, viewer, db, seed_change_run):
    store(db, seed_change_run(NOW - timedelta(days=1)))
    body = client.get(ACCURACY, headers=auth()).json()
    assert (body["rate"], body["caught"], body["missed"], body["live"]["runs"]) == (None, 0, 0, 1)


@pytest.mark.parametrize("days", [1, 10, 31, 90])
def test_days_other_than_7_14_30_are_refused(client, auth, viewer, days):
    assert client.get(ACCURACY, params={"days": days}, headers=auth()).status_code == 422


def test_the_days_check_comes_after_the_role_check(client, auth, project_role):
    project_role(status_code=404, body={"detail": "Project not found"}, project_id=1)
    assert client.get(ACCURACY, params={"days": 10}, headers=auth()).status_code == 404


@pytest.mark.parametrize("role", READ_ROLES)
def test_every_reading_role_scores_and_reads_accuracy(client, auth, project_role, role):
    project_role(role, project_id=1)
    assert client.post(IMPACT, json={"changed_paths": ["src/a.py"]}, headers=auth()).status_code == 200
    assert client.get(ACCURACY, headers=auth()).status_code == 200


def test_scoring_and_accuracy_need_a_member(client, auth, project_role):
    project_role(status_code=404, body={"detail": "Project not found"}, project_id=1)
    assert client.post(IMPACT, json={"changed_paths": ["src/a.py"]}, headers=auth()).status_code == 404
    assert client.post(IMPACT, json={"changed_paths": ["src/a.py"]}).status_code == 401
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_endpoints.py -q`
Expected: FAIL. The GET tests answer 404 (no such route) and the POST tests answer 405.

- [ ] **Step 3: Write the schemas**

Create `platforms/ingestion-service/src/ingestion/schemas/impact.py`:

```python
"""Test impact answers (spec 2026-10-12 §3.5; plan Rulings 17-19)."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel


class ImpactTestOut(BaseModel):
    test_key: str
    suite: str
    class_name: str
    name: str


class ImpactEvidenceOut(BaseModel):
    path_unit: str
    changed_runs: int
    new_failures: int
    confidence: float
    lift: float
    base_rate: float


class SuggestedTestOut(ImpactTestOut):
    kind: Literal["statistical", "test_file_changed", "failing_on_branch", "no_history"]
    evidence: Optional[ImpactEvidenceOut] = None


class SuggestionOut(BaseModel):
    state: Literal["ok", "not_enough_history"]
    model_version: str
    history_runs: int
    needed_runs: int
    statistical_total: int
    tests: List[SuggestedTestOut]


class OutcomeOut(BaseModel):
    evaluated_at: datetime
    caught: List[ImpactTestOut]
    missed: List[ImpactTestOut]


class RunImpactOut(BaseModel):
    run_id: int
    state: Literal["ok", "not_enough_history", "no_change_data", "not_scored"]
    changed_paths: List[str]
    replayed: bool = False
    scored_at: Optional[datetime] = None
    suggestion: Optional[SuggestionOut] = None
    outcome: Optional[OutcomeOut] = None


class AccuracyPartOut(BaseModel):
    runs: int
    caught: int
    missed: int


class MissOut(ImpactTestOut):
    run_id: int
    started_at: datetime
    branch: Optional[str] = None
    replayed: bool


class ImpactAccuracyOut(BaseModel):
    days: int
    caught: int
    missed: int
    rate: Optional[float] = None
    includes_replayed: bool
    live: AccuracyPartOut
    replayed: AccuracyPartOut
    misses: List[MissOut]
    misses_total: int
```

- [ ] **Step 4: Write the read side**

Create `platforms/ingestion-service/src/ingestion/service/impact_read.py`:

```python
"""Reading test impact (spec 2026-10-12 §3.5; plan Rulings 17, 19): a run's stored suggestion and outcome, and the
accuracy figure over the runs that had a stored suggestion."""
from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ingestion.analytics.trends import as_utc
from src.ingestion.models import Run, RunChangedFile
from src.ingestion.models.impact import RunImpact

MAX_MISSES = 50


def run_impact(db: Session, run: Run) -> dict:
    paths = [path for (path,) in db.execute(
        select(RunChangedFile.path).where(RunChangedFile.run_id == run.id).order_by(RunChangedFile.id))]
    if not paths:
        return {"run_id": run.id, "state": "no_change_data", "changed_paths": []}
    row = db.get(RunImpact, run.id)
    if row is None:
        return {"run_id": run.id, "state": "not_scored", "changed_paths": paths}
    outcome = None
    if row.evaluated_at is not None:
        outcome = {"evaluated_at": row.evaluated_at, "caught": row.caught or [], "missed": row.missed or []}
    return {"run_id": run.id, "state": row.suggested["state"], "changed_paths": paths, "replayed": row.replayed,
            "scored_at": row.scored_at, "suggestion": {**row.suggested, "model_version": row.model_version},
            "outcome": outcome}


def accuracy(db: Session, project_id: int, since: datetime, days: int) -> dict:
    """caught / (caught + missed) over the runs started since `since` whose outcome is recorded, live and replayed
    apart; the misses newest run first."""
    rows = db.execute(
        select(RunImpact.run_id, RunImpact.replayed, RunImpact.caught, RunImpact.missed, Run.started_at, Run.branch)
        .join(Run, Run.id == RunImpact.run_id)
        .where(Run.project_id == project_id, Run.started_at >= since, RunImpact.evaluated_at.is_not(None))
        .order_by(Run.started_at.desc(), Run.id.desc())
    ).all()
    parts = {False: {"runs": 0, "caught": 0, "missed": 0}, True: {"runs": 0, "caught": 0, "missed": 0}}
    misses: List[dict] = []
    for run_id, replayed, caught, missed, started_at, branch in rows:
        part = parts[bool(replayed)]
        part["runs"] += 1
        part["caught"] += len(caught or [])
        part["missed"] += len(missed or [])
        misses.extend({**test, "run_id": run_id, "started_at": as_utc(started_at), "branch": branch,
                       "replayed": bool(replayed)} for test in missed or [])
    caught = parts[False]["caught"] + parts[True]["caught"]
    missed = parts[False]["missed"] + parts[True]["missed"]
    return {"days": days, "caught": caught, "missed": missed,
            "rate": round(caught / (caught + missed), 4) if caught + missed else None,
            "includes_replayed": parts[True]["runs"] > 0, "live": parts[False], "replayed": parts[True],
            "misses": misses[:MAX_MISSES], "misses_total": len(misses)}
```

- [ ] **Step 5: Add the routes**

In `platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py`, with the Edit tool, replace:

```python
from src.ingestion.service import run_service
```

with:

```python
from src.ingestion.schemas.impact import RunImpactOut
from src.ingestion.service import impact_read, run_service
```

and replace:

```python
@router.get("/{run_id}", response_model=RunDetail)
```

with:

```python
@project_router.get("/{run_id}/impact", response_model=RunImpactOut)
def get_run_impact(
    run_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """The suggestion stored with the run and its outcome (spec 2026-10-12 §3.5)."""
    run = run_service.get_run(db, run_id)
    # A run of another project is indistinguishable from a missing one
    if run is None or run.project_id != access.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return impact_read.run_impact(db, run)


@router.get("/{run_id}", response_model=RunDetail)
```

In `platforms/ingestion-service/src/ingestion/api/v1/endpoints/analytics.py`, with the Edit tool, replace:

```python
from src.ingestion.service import analytics_service, duration_service
```

with:

```python
from src.ingestion.analytics.impact_rules import MODEL_VERSION
from src.ingestion.schemas.impact import ImpactAccuracyOut, SuggestionOut
from src.ingestion.service import analytics_service, duration_service, impact_read, impact_service
```

and append at the end of the file:

```python


class ImpactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changed_paths: List[Annotated[str, StringConstraints(min_length=1, max_length=1000, pattern=NO_NUL)]] = Field(
        min_length=1, max_length=5000)
    branch: Optional[Annotated[str, StringConstraints(max_length=255, pattern=NO_NUL)]] = None


@router.post("/impact", response_model=SuggestionOut)
def impact(
    body: ImpactIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """Likely affected tests for any change (spec 2026-10-12 §3.5): Run likely affected in the dashboard now, the
    collector later."""
    suggestion = impact_service.score_change(db, access.project_id, body.changed_paths, body.branch, now=_now())
    return {**suggestion, "model_version": MODEL_VERSION}


ACCURACY_DAYS = (7, 14, 30)


@router.get("/impact-accuracy", response_model=ImpactAccuracyOut)
def impact_accuracy(
    days: int = Query(30),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """How often the stored suggestions contained the new failures, live and replayed apart (spec §2.3)."""
    if days not in ACCURACY_DAYS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="days must be 7, 14 or 30")
    return impact_read.accuracy(db, access.project_id, _now() - timedelta(days=days), days)
```

- [ ] **Step 6: Run the tests**

Run: `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_impact_endpoints.py tests/integration/test_runs_endpoints.py tests/integration/test_analytics_endpoints.py -q`
Expected: PASS.

- [ ] **Step 7: Document the endpoints**

In `platforms/ingestion-service/README.md`, with the Edit tool, replace:

```
## Operations
```

with:

```
### Endpoints (every role that can read runs)

| Endpoint | Returns |
|---|---|
| `GET /api/v1/projects/{id}/runs/{run_id}/impact` | `state`: `ok`, `not_enough_history`, `no_change_data` (no changed files uploaded) or `not_scored` (changed files, but uploaded before test impact or scoring failed); `changed_paths`; `replayed`; `suggestion` (`history_runs`, `needed_runs`, `statistical_total`, `model_version`, `tests` with `kind` and `evidence`); `outcome` (`caught`, `missed`, `evaluated_at`), null until written. A run of another project is a 404 |
| `POST /api/v1/projects/{id}/analytics/impact` | Body `{"changed_paths": [...], "branch": "main" or null}`: the same scoring for any change, as of now. 1 to 5,000 paths of 1 to 1,000 characters, no NUL, branch at most 255; else 422 |
| `GET /api/v1/projects/{id}/analytics/impact-accuracy?days=30` | `days` 7, 14 or 30 (else 422): `caught`, `missed`, `rate` (null without new failures), `includes_replayed`, the `live` and `replayed` parts (`runs`, `caught`, `missed`), and the `misses` (newest run first, at most 50; `misses_total`) |

## Operations
```

In `TECHNICAL_SPECIFICATION.md`, with the Edit tool, replace:

```
  run-strip (latest results for case lists), duration-estimate (Run from QEOS).
```

with:

```
  run-strip (latest results for case lists), duration-estimate (Run from QEOS),
  test impact (ADR-029): `POST /analytics/impact` scores a change against the
  co-failure statistics, `GET /analytics/impact-accuracy?days=7|14|30`, and
  `GET /projects/{id}/runs/{run_id}/impact` reads the suggestion stored with a
  run at upload (scored before its results) and its outcome.
```

and replace:

```
flaky_rollup_days (daily flip aggregates + computed-day markers), api_keys
```

with:

```
flaky_rollup_days (daily flip aggregates + computed-day markers), impact_pairs /
impact_test_base (test impact statistics, rebuilt nightly) and run_impact (the
suggestion stored with a run and its outcome; cascades with the run), api_keys
```

- [ ] **Step 8: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/schemas/impact.py platforms/ingestion-service/src/ingestion/service/impact_read.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/analytics.py platforms/ingestion-service/tests/integration/test_impact_endpoints.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md
git commit -m "feat(ingestion): test impact endpoints (run impact, score a change, accuracy)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- platforms/ingestion-service/src/ingestion/schemas/impact.py platforms/ingestion-service/src/ingestion/service/impact_read.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/analytics.py platforms/ingestion-service/tests/integration/test_impact_endpoints.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md
```

---

### Task 10: Gateway smoke checks for test impact

**Files:**
- Modify: `scripts/smoke_gateway.sh` (stays `100755`)

**Interfaces:**
- Consumes:
  - Tasks 6, 7, 9: the `impact-rollup` compose service, the stored suggestion and outcome, and the three routes.
  - The smoke script's `check`, `body_has`, `body_matches`, `pass`, `fail`, `at`, `AUTH`, `API_KEY`, `PROJECT_ID`, `BASE`, `TMP`, `SUFFIX`.
- Produces smoke lines proving, through the gateway on PostgreSQL:
  - two uploads with changed files where a test passes and then fails;
  - `GET …/runs/{id}/impact` with the miss;
  - one rollup pass inside the stack;
  - `POST /analytics/impact` suggesting the test, and `GET /analytics/impact-accuracy`.
- The gateway is not changed. The paths fall under `location ~ ^/api/v1/projects/[0-9]+/(api-keys|runs|analytics|masking-patterns|export|notification-channels)(/|$)` in `gateway/nginx.conf.template`, which proxies to ingestion. The only rule ahead of it is the exact `analytics/report$` location.

Ruling for this smoke: two runs cannot meet the statistical thresholds (`changed_runs ≥ 3`, `new_failures ≥ 2`). So "POST … with that path suggests the test" (spec §5) is proven by the *failing on this branch* label: run B is the branch's latest run and the test fails in it.

- [ ] **Step 1: Write the new checks**

In `scripts/smoke_gateway.sh`, with the Edit tool, replace:

```
# ---- retention: the job runs, and really reaches project-service inside the stack ----
```

with:

```
# ---- test impact (spec 2026-10-12 §5): a test passes, then fails, in two runs that changed the same file ----
# Unique names per smoke run: a rerun on the same stack must not find the test in an earlier run's statistics
IMPACT_BRANCH="smoke-impact-$SUFFIX"
IMPACT_TEST="impact-breaks-$SUFFIX"
IMPACT_CHANGES='"changes":{"base_ref":"origin/main","truncated":false,"files":[{"path":"src/impact/smoke.py","status":"M","additions":1,"deletions":0}]}'
IMPACT_RUN_A="{\"run\":{\"ci_provider\":\"local\",\"branch\":\"$IMPACT_BRANCH\",\"started_at\":\"$(at -50)\",\"finished_at\":\"$(at -45)\"},\"results\":[{\"name\":\"$IMPACT_TEST\",\"status\":\"passed\"}],$IMPACT_CHANGES}"
IMPACT_RUN_B="{\"run\":{\"ci_provider\":\"local\",\"branch\":\"$IMPACT_BRANCH\",\"started_at\":\"$(at -40)\",\"finished_at\":\"$(at -35)\"},\"results\":[{\"name\":\"$IMPACT_TEST\",\"status\":\"failed\",\"message\":\"broke\"}],$IMPACT_CHANGES}"
check "upload impact run A (changed files, the test passes)" 201 POST "$BASE/api/v1/collect/runs" \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "$IMPACT_RUN_A"
check "upload impact run B (the same file, the test fails)" 201 POST "$BASE/api/v1/collect/runs" \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "$IMPACT_RUN_B"
IMPACT_RUN_B_ID="$(grep -o '"id":[0-9]*' "$TMP/body" | head -1 | cut -d: -f2)"
IMPACT_URL="$BASE/api/v1/projects/$PROJECT_ID/runs/${IMPACT_RUN_B_ID:-0}/impact"
# The outcome is written right after the upload's response: give it up to 5 seconds
for _ in 1 2 3 4 5 6 7 8 9 10; do
  curl -ks -o "$TMP/body" "${AUTH[@]}" "$IMPACT_URL"
  grep -q '"evaluated_at"' "$TMP/body" && break
  sleep 0.5
done
check "impact of run B -> ingestion-service (runs route)" 200 GET "$IMPACT_URL" "${AUTH[@]}"
body_has "... names the changed file" '"changed_paths":["src/impact/smoke.py"]'
body_has "... scored with too little history" '"state":"not_enough_history"'
body_matches "... the new failure was missed: the suggestion was scored before the run's own results" \
  "\"missed\":\\[\\{\"test_key\":\"[0-9a-f]{64}\",\"suite\":\"\",\"class_name\":\"\",\"name\":\"$IMPACT_TEST\"\\}\\]"
if docker compose ps --status running --services 2>/dev/null | grep -qx impact-rollup; then
  pass "impact-rollup is running"
else
  fail "impact-rollup is not running"
fi
if docker compose run --rm -T impact-rollup python -m src.ingestion.jobs.impact_rollup \
     >"$TMP/impact_out" 2>"$TMP/impact_err"; then
  if grep -q '"event": "impact_rollup"' "$TMP/impact_out"; then
    pass "impact rollup pass inside the stack (window functions and the hash index on PostgreSQL)"
  else
    fail "impact rollup printed no summary: $(tail -c 300 "$TMP/impact_out")"
  fi
else
  fail "impact rollup pass: $(tail -c 400 "$TMP/impact_err")"
fi
check "score a change -> ingestion-service (analytics route)" 200 POST \
  "$BASE/api/v1/projects/$PROJECT_ID/analytics/impact" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"changed_paths\":[\"src/impact/smoke.py\"],\"branch\":\"$IMPACT_BRANCH\"}"
body_has "... suggests the test that now fails on the branch" "\"name\":\"$IMPACT_TEST\",\"kind\":\"failing_on_branch\""
check "impact accuracy -> ingestion-service (analytics route)" 200 GET \
  "$BASE/api/v1/projects/$PROJECT_ID/analytics/impact-accuracy?days=7" "${AUTH[@]}"
body_matches "... counts the miss" '"missed":[1-9]'
body_has "... no replayed runs" '"includes_replayed":false'

# ---- retention: the job runs, and really reaches project-service inside the stack ----
```

- [ ] **Step 2: Run the smoke on the current tree**

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose exec -T ingestion-service alembic current
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```

Expected:
- `018 (head)` from `alembic current`.
- Every new line prints `ok`, for example `ok    impact of run B -> ingestion-service (runs route) (200)` and `ok    ... suggests the test that now fails on the branch`.
- The run ends with `all gateway checks passed`.

Against an image built before Task 9, the first impact `check` reads `FAIL  impact of run B ...: expected 200, got 404`: that is the red state these checks guard.

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
git commit -m "test(smoke): test impact through the gateway (stored suggestion and miss, rollup pass, scoring, accuracy)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git ls-files -s scripts/smoke_gateway.sh
```

Expected: the line starts with `100755`.

---

### Task 11: Benchmark against the budgets

**Files:**
- Create: `scripts/impact_benchmark.py`
- Modify: `platforms/ingestion-service/README.md`

**Interfaces:**
- Consumes: `window_start` (Task 5), `flaky_keys` (Task 4), `build_statistics`/`replace_statistics` (Task 5), `score_change` (Task 7), `analytics_service.muted_keys`, `test_key`.
- Produces: the measured figures against "the rollup under 60 s per project; live scoring under 200 ms" (spec §3.7), in the ingestion README. The script exits 1 when a budget is missed.

- [ ] **Step 1: Write the benchmark**

Create `scripts/impact_benchmark.py`:

```python
"""One-off: test impact analysis against its budgets on a big project (spec 2026-10-12 §3.7). Not part of CI.

    docker compose exec -T ingestion-service python - < scripts/impact_benchmark.py

Seeds project 900002 like scripts/analytics_benchmark.py (90 days x 22 runs x 1,000 tests, about two million
results), each run with 3 to 12 changed files from 40 folders, then times the impact rollup of the project (budget
60 s) and live scoring of a 10-file change on main (budget 200 ms, p95 of 20), and deletes everything it seeded.
Exits 1 over a budget. Run it in a throwaway stack.
"""
import random
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select, text

from src.ingestion.db.session import SessionLocal
from src.ingestion.jobs.impact_rollup import window_start
from src.ingestion.models import ApiKey, Run, RunChangedFile, RunResult
from src.ingestion.models.impact import ImpactPair, ImpactTestBase
from src.ingestion.service import analytics_service
from src.ingestion.service.impact_history import flaky_keys
from src.ingestion.service.impact_service import score_change
from src.ingestion.service.impact_stats import build_statistics, replace_statistics
from src.ingestion.service.ingest_service import test_key

PROJECT = 900002
DAYS = 90
RUNS_PER_DAY = 22
TESTS = 1000
STATUSES = ("passed", "failed", "errored", "skipped")
WEIGHTS = (95, 3, 1, 1)
FOLDERS = [f"src/area{i}/mod{j}" for i in range(8) for j in range(5)]
ROLLUP_BUDGET_S = 60.0
SCORE_BUDGET_MS = 200.0

random.seed(11)
keys = [test_key("bench", f"Class{i // 50}", f"test_{i}") for i in range(TESTS)]
now = datetime.now(timezone.utc)
db = SessionLocal()
over = False


def changed_paths(count):
    return sorted({f"{random.choice(FOLDERS)}/file{random.randint(0, 30)}.py" for _ in range(count)})


try:
    api_key = ApiKey(project_id=PROJECT, organization_id=1, name="bench", key_prefix="qeos_bench2",
                     key_hash="e" * 64, created_by=1)
    db.add(api_key)
    db.flush()
    started_seeding = time.perf_counter()
    for day in range(DAYS):
        for number in range(RUNS_PER_DAY):
            started = now - timedelta(days=day, minutes=number * 30 + 1)
            statuses = random.choices(STATUSES, WEIGHTS, k=TESTS)
            paths = changed_paths(random.randint(3, 12))
            run = Run(project_id=PROJECT, api_key_id=api_key.id, request_hash="bench", ci_provider="local",
                      branch=random.choice(("main", "main", "feature")), commit_sha=f"{day:04x}{number // 2:03x}",
                      started_at=started, finished_at=started + timedelta(minutes=5), duration_ms=300000,
                      total=TESTS, passed=statuses.count("passed"), failed=statuses.count("failed"),
                      errored=statuses.count("errored"), skipped=statuses.count("skipped"),
                      change_base_ref="abc1234^", changed_files=len(paths), additions=len(paths), deletions=0,
                      changes_truncated=False)
            db.add(run)
            db.flush()
            db.execute(insert(RunResult), [
                {"run_id": run.id, "test_key": keys[i], "suite": "bench", "class_name": f"Class{i // 50}",
                 "name": f"test_{i}", "status": statuses[i], "duration_ms": random.randint(5, 2000),
                 "truncated": False, "redacted": False}
                for i in range(TESTS)
            ])
            db.execute(insert(RunChangedFile), [
                {"run_id": run.id, "path": path, "status": "M", "additions": 1, "deletions": 0} for path in paths
            ])
        db.commit()
    for table in ("test_runs", "test_results", "run_changed_files"):
        db.execute(text(f"ANALYZE {table}"))
    db.commit()
    print(f"seeded {DAYS * RUNS_PER_DAY} runs x {TESTS} results in {time.perf_counter() - started_seeding:.0f} s")

    start = time.perf_counter()
    since = window_start(now)
    pairs, bases = build_statistics(db, PROJECT, since, now, flaky_keys(db, PROJECT, since),
                                    analytics_service.muted_keys(db, PROJECT))
    replace_statistics(db, PROJECT, pairs, bases, now)
    rollup_s = time.perf_counter() - start
    print(f"impact rollup, one project: {rollup_s:.1f} s ({len(pairs)} pairs, {len(bases)} tests); "
          f"budget {ROLLUP_BUDGET_S:.0f} s: {'ok' if rollup_s <= ROLLUP_BUDGET_S else 'OVER'}")
    over |= rollup_s > ROLLUP_BUDGET_S

    timings = []
    for _ in range(20):
        change = changed_paths(10)
        before = time.perf_counter()
        score_change(db, PROJECT, change, "main", now=now)
        timings.append((time.perf_counter() - before) * 1000)
        db.rollback()
    p95 = statistics.quantiles(timings, n=20)[18]
    print(f"live scoring, 10 changed files: p50 {statistics.median(timings):.0f} ms, p95 {p95:.0f} ms; "
          f"budget {SCORE_BUDGET_MS:.0f} ms: {'ok' if p95 <= SCORE_BUDGET_MS else 'OVER'}")
    over |= p95 > SCORE_BUDGET_MS
finally:
    db.rollback()
    run_ids = select(Run.id).where(Run.project_id == PROJECT)
    db.execute(delete(RunChangedFile).where(RunChangedFile.run_id.in_(run_ids)))
    db.execute(delete(RunResult).where(RunResult.run_id.in_(run_ids)))
    db.execute(delete(Run).where(Run.project_id == PROJECT))
    db.execute(delete(ApiKey).where(ApiKey.project_id == PROJECT))
    db.execute(delete(ImpactPair).where(ImpactPair.project_id == PROJECT))
    db.execute(delete(ImpactTestBase).where(ImpactTestBase.project_id == PROJECT))
    db.commit()
    db.close()
sys.exit(1 if over else 0)
```

- [ ] **Step 2: Run it in a throwaway stack**

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 ingestion-service
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose exec -T ingestion-service python - < scripts/impact_benchmark.py; echo "exit $?"
```

Expected: three lines, then `exit 0`:
- `seeded 1980 runs x 1000 results in … s`;
- `impact rollup, one project: … s (… pairs, 1000 tests); budget 60 s: ok`;
- `live scoring, 10 changed files: p50 … ms, p95 … ms; budget 200 ms: ok`.

Before the run, check the host is quiet (no test suite, build or other bench running: `docker stats --no-stream` and the process list), as the README's other benchmark notes require.

If a line reads `OVER` (exit 1), stop. Do not raise a budget or push. Record the figure and report it to the user with the two measured parts:
- for the rollup, the time of `newly_failed_bulk` against `_tests_in`;
- for scoring, the time of `load_statistics` against `failing_on_branch`.

The spec's budgets are binding (spec §3.7).

Then `SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose down` (never `-v`).

- [ ] **Step 3: Record the figures**

In `platforms/ingestion-service/README.md`, with the Edit tool, replace:

```
## Operations
```

with the block below. Fill each cell from the two printed lines: the rollup's seconds, pair and test counts, and the scoring's p50 and p95. Use the measurement date.

```
### Budgets (`scripts/impact_benchmark.py`)

Measured on a throwaway stack: 1,980 runs × 1,000 tests over 90 days (about 2 million results, as the analytics
benchmark above), each run with 3 to 12 changed files from 40 folders; PostgreSQL 15 in Docker. Regenerate with
`docker compose exec -T ingestion-service python - < scripts/impact_benchmark.py` (exits 1 over a budget).

| Measure | Result | Budget (spec §3.7) |
|---|---|---|
| Impact rollup, one project (pairs, tests written) | <seconds from the "impact rollup" line> s (<pairs> pairs, <tests> tests) | under 60 s |
| Live scoring of a 10-file change on main, p95 of 20 (p50) | <p95> ms (<p50> ms) | under 200 ms |

## Operations
```

Before committing, run `grep -n "<" platforms/ingestion-service/README.md | grep -i "seconds from\|<p95>\|<p50>\|<pairs>\|<tests>"`. Expected: no output, which shows every cell holds a measured number.

- [ ] **Step 4: Commit**

```bash
git add scripts/impact_benchmark.py platforms/ingestion-service/README.md
git commit -m "perf(ingestion): test impact benchmark against its budgets, figures in the README" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- scripts/impact_benchmark.py platforms/ingestion-service/README.md
```

---

### Task 12: Phase 1 gate

**Files:** none new (fixes only, in the files of Tasks 1–11).

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

Expected: all green. Run them one after another, never two at once.

- [ ] **Step 2: Dashboard checks (unchanged in this phase, still part of CI)**

Run: `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build && node --test ../templates/github/qeos-run.test.mjs`
Expected: all green.

- [ ] **Step 3: Docs check and the ingestion container smoke**

```bash
python scripts/check_architecture_docs.py && python -m pytest scripts/tests -q
cd platforms/ingestion-service && SECRET_KEY=ci-smoke-secret docker compose up --build --detach --wait --wait-timeout 180 && curl --fail --silent --show-error http://localhost:8003/health && SECRET_KEY=ci-smoke-secret docker compose down --volumes
```

Expected:
- no findings from the docs check, and its tests pass;
- `{"status":"healthy"}` from the container smoke, whose stack uses throwaway volumes as CI's `smoke` job does.

- [ ] **Step 4: Gateway, monitoring checks and the full smoke**

```bash
docker build -t qeos/gateway:ci gateway && docker run --rm qeos/gateway:ci nginx -t && docker run --rm -e MONITORING_ENABLED=true qeos/gateway:ci nginx -t
bash monitoring/check.sh
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose exec -T ingestion-service alembic current
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```

Expected:
- `nginx: configuration file /etc/nginx/nginx.conf test is successful`, twice;
- `monitoring: all checks passed`;
- `018 (head)`;
- the smoke ends with `all gateway checks passed`.

- [ ] **Step 5: Tear down, check the script mode, push**

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose down
git ls-files -s scripts/smoke_gateway.sh
git status --short
git log --oneline origin/master..master
git push origin master
```

Expected:
- `100755` for the script;
- no modified tracked file of this plan left;
- the log lists the Phase 1 commits, and the push succeeds.

Never `docker compose down -v`.

---

# Phase 2 — Views (dashboard)

At the end of this phase every person can see:
- the likely affected tests of a run with their evidence and outcome;
- the accuracy figure in the Report;
- the accuracy as an Overview widget.

### Task 13: The impact API client and the shared query

**Files:**
- Create: `dashboard/src/api/impact.ts`, `dashboard/src/api/impact.test.ts`, `dashboard/src/lib/impactQueries.ts`, `dashboard/src/lib/impactQueries.test.ts`
- Modify: `dashboard/src/test/server.ts`

**Interfaces:**
- Consumes:
  - Task 9's three routes and their JSON;
  - `apiFetch`, `buildQuery` (`api/http.ts`), `formatCount` (`api/analytics.ts`), `REPORT_STALE_MS` (`pages/report/useReportRequest.ts`).
- Produces:
  - **Types** in `api/impact.ts`: `ImpactKind`, `ImpactTestRef`, `ImpactEvidence`, `SuggestedTest`, `ImpactSuggestion`, `ImpactOutcome`, `RunImpact`, `AccuracyPart`, `ImpactMiss`, `ImpactAccuracy`, `AccuracyDays = 7 | 14 | 30`.
  - **Calls** in `api/impact.ts`:
    - `getRunImpact(projectId: number, runId: number): Promise<RunImpact>`;
    - `scoreChange(projectId: number, changedPaths: string[], branch: string | null): Promise<ImpactSuggestion>`;
    - `getImpactAccuracy(projectId: number, days: AccuracyDays, init?: { signal?: AbortSignal }): Promise<ImpactAccuracy>`.
  - **Queries** in `lib/impactQueries.ts`:
    - `ACCURACY_DAYS`;
    - `runImpactQuery(projectId, runId)`, key `["run-impact", projectId, runId]`;
    - `impactAccuracyQuery(projectId, days)`, key `["report", projectId, "impact-accuracy", days]` (Ruling 20);
    - `useImpactAccuracy(projectId, days)`;
    - `impactAccuracyStaleKeys(projectId) -> QueryKey[]`.
  - **Formatting helpers** in `lib/impactQueries.ts`:
    - `accuracyDays(days: number, to: string, today: string): AccuracyDays` (Ruling 21);
    - `caughtText(caught: number, missed: number): string`;
    - `normally(rate: number): string`.
  - Default MSW handlers for the run impact and the accuracy.

- [ ] **Step 1: Invoke `ui-ux-pro-max`**

Invoke the `ui-ux-pro-max` skill. This task writes no markup, but its copy helpers (`caughtText`, `normally`) are the words the card, the section and the widget show: check them against DESIGN.md's voice (plain sentences, tabular figures, locale grouping).

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/api/impact.test.ts`:

```ts
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { getImpactAccuracy, getRunImpact, scoreChange } from "./impact";

const NO_ACCURACY = { days: 14, caught: 0, missed: 0, rate: null, includes_replayed: false,
  live: { runs: 0, caught: 0, missed: 0 }, replayed: { runs: 0, caught: 0, missed: 0 }, misses: [], misses_total: 0 };

test("a run's impact, a change scored, and the accuracy over 7, 14 or 30 days", async () => {
  setAccessToken("acc");
  const asked: string[] = [];
  let body: unknown;
  server.use(
    http.get("/api/v1/projects/42/runs/61/impact", ({ request }) => {
      asked.push(new URL(request.url).pathname);
      return HttpResponse.json({ run_id: 61, state: "no_change_data", changed_paths: [], replayed: false, scored_at: null,
        suggestion: null, outcome: null });
    }),
    http.post("/api/v1/projects/42/analytics/impact", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ state: "ok", model_version: "stats-v1", history_runs: 30, needed_runs: 20,
        statistical_total: 0, tests: [] });
    }),
    http.get("/api/v1/projects/42/analytics/impact-accuracy", ({ request }) => {
      asked.push(new URL(request.url).search);
      return HttpResponse.json(NO_ACCURACY);
    }),
  );
  expect((await getRunImpact(42, 61)).state).toBe("no_change_data");
  expect((await scoreChange(42, ["src/a.py"], "main")).model_version).toBe("stats-v1");
  expect(body).toEqual({ changed_paths: ["src/a.py"], branch: "main" });
  expect((await getImpactAccuracy(42, 14)).days).toBe(14);
  expect(asked).toEqual(["/api/v1/projects/42/runs/61/impact", "?days=14"]);
});
```

Create `dashboard/src/lib/impactQueries.test.ts`:

```ts
import { accuracyDays, caughtText, impactAccuracyQuery, normally } from "./impactQueries";

test("the Report's period when it is the last 7, 14 or 30 days, else 30", () => {
  expect(accuracyDays(7, "2026-10-12", "2026-10-12")).toBe(7);
  expect(accuracyDays(14, "2026-10-12", "2026-10-12")).toBe(14);
  expect(accuracyDays(30, "2026-10-12", "2026-10-12")).toBe(30);
  expect(accuracyDays(90, "2026-10-12", "2026-10-12")).toBe(30);
  expect(accuracyDays(7, "2026-10-05", "2026-10-12")).toBe(30); // a past week is not "the last 7 days"
});

test("base rates as people say them", () => {
  expect(normally(0.03)).toBe("normally 3%");
  expect(normally(0.1333)).toBe("normally 13%");
  expect(normally(0.004)).toBe("normally under 1%");
  expect(normally(0)).toBe("normally 0%");
});

test("caught out of the new failures, with the locale's grouping", () => {
  expect(caughtText(9, 3)).toBe("9 of 12 new failures");
  expect(caughtText(1, 0)).toBe("1 of 1 new failure");
  expect(caughtText(1200, 34)).toBe("1,200 of 1,234 new failures");
});

test("the accuracy lives under the Report's key, so the Report's Refresh covers it", () => {
  expect(impactAccuracyQuery(42, 7).queryKey).toEqual(["report", 42, "impact-accuracy", 7]);
});
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd dashboard && npx vitest run src/api/impact.test.ts src/lib/impactQueries.test.ts`
Expected: FAIL, `Failed to resolve import "./impact"` and `"./impactQueries"`.

- [ ] **Step 4: Write the client**

Create `dashboard/src/api/impact.ts`:

```ts
import { apiFetch, buildQuery } from "./http";

// Mirrors platforms/ingestion-service/src/ingestion/schemas/impact.py (spec 2026-10-12 §3.5)

export type ImpactKind = "statistical" | "test_file_changed" | "failing_on_branch" | "no_history";

export interface ImpactTestRef {
  test_key: string;
  suite: string;
  class_name: string;
  name: string;
}

export interface ImpactEvidence {
  path_unit: string;
  changed_runs: number;
  new_failures: number;
  confidence: number;
  lift: number;
  base_rate: number;
}

export interface SuggestedTest extends ImpactTestRef {
  kind: ImpactKind;
  /** Null for the always-included kinds, which carry a label instead. */
  evidence: ImpactEvidence | null;
}

export interface ImpactSuggestion {
  state: "ok" | "not_enough_history";
  model_version: string;
  history_runs: number;
  needed_runs: number;
  /** Statistical suggestions before the cap of 50. */
  statistical_total: number;
  tests: SuggestedTest[];
}

export interface ImpactOutcome {
  evaluated_at: string;
  caught: ImpactTestRef[];
  missed: ImpactTestRef[];
}

export interface RunImpact {
  run_id: number;
  state: "ok" | "not_enough_history" | "no_change_data" | "not_scored";
  changed_paths: string[];
  replayed: boolean;
  scored_at: string | null;
  suggestion: ImpactSuggestion | null;
  /** Null until written, right after the upload. */
  outcome: ImpactOutcome | null;
}

export interface AccuracyPart {
  runs: number;
  caught: number;
  missed: number;
}

export interface ImpactMiss extends ImpactTestRef {
  run_id: number;
  started_at: string;
  branch: string | null;
  replayed: boolean;
}

export interface ImpactAccuracy {
  days: number;
  caught: number;
  missed: number;
  /** caught / (caught + missed); null when there were no new failures. */
  rate: number | null;
  includes_replayed: boolean;
  live: AccuracyPart;
  replayed: AccuracyPart;
  misses: ImpactMiss[];
  misses_total: number;
}

export type AccuracyDays = 7 | 14 | 30;

const base = (projectId: number) => `/api/v1/projects/${projectId}`;

/** The suggestion stored with a run and its outcome. */
export function getRunImpact(projectId: number, runId: number): Promise<RunImpact> {
  return apiFetch(`${base(projectId)}/runs/${runId}/impact`);
}

/** Likely affected tests for any change, as of now. */
export function scoreChange(projectId: number, changedPaths: string[], branch: string | null): Promise<ImpactSuggestion> {
  return apiFetch(`${base(projectId)}/analytics/impact`, {
    method: "POST",
    body: JSON.stringify({ changed_paths: changedPaths, branch }),
  });
}

/** How often the stored suggestions contained the new failures, over the last 7, 14 or 30 days. */
export function getImpactAccuracy(projectId: number, days: AccuracyDays, init: { signal?: AbortSignal } = {}): Promise<ImpactAccuracy> {
  return apiFetch(`${base(projectId)}/analytics/impact-accuracy${buildQuery({ days })}`, init);
}
```

- [ ] **Step 5: Write the shared query and helpers**

Create `dashboard/src/lib/impactQueries.ts`:

```ts
import type { QueryKey } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { formatCount } from "../api/analytics";
import { type AccuracyDays, getImpactAccuracy, getRunImpact } from "../api/impact";
import { REPORT_STALE_MS } from "../pages/report/useReportRequest";

export const ACCURACY_DAYS: readonly AccuracyDays[] = [7, 14, 30];

/** A run's stored suggestion and its outcome (spec 2026-10-12 §2.1). */
export const runImpactQuery = (projectId: number, runId: number) => ({
  queryKey: ["run-impact", projectId, runId] as const,
  queryFn: () => getRunImpact(projectId, runId),
});

/** The accuracy figure under the Report's key (plan Ruling 20): the Report's Refresh and a new latest run refresh it.
 *  The Report's Test impact section and the Overview's Impact accuracy widget share it (spec §4). */
export const impactAccuracyQuery = (projectId: number, days: AccuracyDays) => ({
  queryKey: ["report", projectId, "impact-accuracy", days] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => getImpactAccuracy(projectId, days, { signal }),
  staleTime: REPORT_STALE_MS,
  retry: false,
});

export function useImpactAccuracy(projectId: number, days: AccuracyDays) {
  return useQuery(impactAccuracyQuery(projectId, days));
}

/** What a new latest run makes stale for the accuracy figure (the widget's `staleKeys`). */
export const impactAccuracyStaleKeys = (projectId: number): QueryKey[] => [["report", projectId, "impact-accuracy"]];

/** The Report's period when it is the last 7, 14 or 30 days up to today, else 30 days (plan Ruling 21). */
export function accuracyDays(days: number, to: string, today: string): AccuracyDays {
  return to === today && (ACCURACY_DAYS as readonly number[]).includes(days) ? (days as AccuracyDays) : 30;
}

/** "9 of 12 new failures". */
export function caughtText(caught: number, missed: number): string {
  const total = caught + missed;
  return `${formatCount(caught)} of ${formatCount(total)} new ${total === 1 ? "failure" : "failures"}`;
}

/** A base rate as the evidence line says it: "normally 3%", "normally under 1%". */
export function normally(rate: number): string {
  const percent = Math.round(rate * 100);
  return rate > 0 && percent === 0 ? "normally under 1%" : `normally ${percent}%`;
}
```

- [ ] **Step 6: Default handlers for the pages that now ask**

In `dashboard/src/test/server.ts`, with the Edit tool, replace:

```ts
  // Names of the people who ran or stopped something
```

with:

```ts
  // Test impact: the run page's card and the Report's section ask for these; tests about them override
  http.get("/api/v1/projects/:projectId/runs/:runId/impact", ({ params }) => HttpResponse.json({
    run_id: Number(params.runId), state: "no_change_data", changed_paths: [], replayed: false, scored_at: null,
    suggestion: null, outcome: null })),
  http.get("/api/v1/projects/:projectId/analytics/impact-accuracy", ({ request }) => HttpResponse.json({
    days: Number(new URL(request.url).searchParams.get("days") ?? 30), caught: 0, missed: 0, rate: null,
    includes_replayed: false, live: { runs: 0, caught: 0, missed: 0 }, replayed: { runs: 0, caught: 0, missed: 0 },
    misses: [], misses_total: 0 })),
  // Names of the people who ran or stopped something
```

- [ ] **Step 7: Run the tests and the checks**

Run: `cd dashboard && npx vitest run src/api/impact.test.ts src/lib/impactQueries.test.ts && npm run lint && npm run typecheck`
Expected: PASS, no lint or type errors.

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/api/impact.ts dashboard/src/api/impact.test.ts dashboard/src/lib/impactQueries.ts dashboard/src/lib/impactQueries.test.ts dashboard/src/test/server.ts
git commit -m "feat(dashboard): test impact client and the accuracy query shared under the Report's key" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/api/impact.ts dashboard/src/api/impact.test.ts dashboard/src/lib/impactQueries.ts dashboard/src/lib/impactQueries.test.ts dashboard/src/test/server.ts
```

---

### Task 14: The run page's "Likely affected tests" card

**Files:**
- Create: `dashboard/src/components/ImpactCard.tsx`, `dashboard/src/components/ImpactCard.test.tsx`
- Modify: `dashboard/src/pages/RunDetailPage.tsx`, `dashboard/src/pages/RunDetailPage.test.tsx`, `dashboard/src/index.css`, `DESIGN.md`, `docs/SETUP.md`

**Interfaces:**
- Consumes:
  - Task 13: `runImpactQuery`, `normally`, the types.
  - Existing: `StatusPill` (tones `passed`, `failed`, `neutral`), `ErrorBanner`, `SkeletonStatus`, `formatCount`.
- Produces:
  - `ImpactCard({ projectId: number; runId: number })`, a `<section>` named by its h2 "Likely affected tests";
  - `IMPACT_SHOWN = 15`;
  - on the run page, the card beside Changes whenever the run reported changes (Ruling 17).

- [ ] **Step 1: Invoke `ui-ux-pro-max`**

Invoke the `ui-ux-pro-max` skill for a status card in an analytics dashboard. Settle three things, and stay within DESIGN.md:
- the two-card row (Changes and Likely affected) and how it stacks on narrow screens;
- how the evidence line sits after the test link;
- the "All caught" and "Missed" pills.

Keep the DESIGN.md rules: tokens only, status never by colour alone, tabular figures, and a loading and error state for the card itself.

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/components/ImpactCard.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import type { RunImpact, SuggestedTest } from "../api/impact";
import ImpactCard from "./ImpactCard";

const IMPACT_URL = "/api/v1/projects/42/runs/61/impact";
const key = (name: string) => name.padEnd(64, "0");
const ref = (name: string) => ({ test_key: key(name), suite: "s", class_name: "C", name });
const statistical = (name: string): SuggestedTest => ({ ...ref(name), kind: "statistical",
  evidence: { path_unit: "src/payment/", changed_runs: 6, new_failures: 4, confidence: 0.6667, lift: 22.2, base_rate: 0.03 } });
const labelled = (name: string, kind: SuggestedTest["kind"]): SuggestedTest => ({ ...ref(name), kind, evidence: null });

function impact(extra: Partial<RunImpact> = {}): RunImpact {
  return {
    run_id: 61, state: "ok", changed_paths: ["src/payment/api.py"], replayed: false, scored_at: "2026-10-12T10:00:00Z",
    suggestion: {
      state: "ok", model_version: "stats-v1", history_runs: 34, needed_runs: 20, statistical_total: 1,
      tests: [statistical("pays"), labelled("checkout_spec", "test_file_changed"), labelled("brand_new", "no_history"),
        labelled("cart", "failing_on_branch")],
    },
    outcome: { evaluated_at: "2026-10-12T10:01:00Z", caught: [ref("pays")], missed: [] },
    ...extra,
  };
}

function renderCard(answer: RunImpact) {
  server.use(http.get(IMPACT_URL, () => HttpResponse.json(answer)));
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><ImpactCard projectId={42} runId={61} /></MemoryRouter></QueryClientProvider>);
}

const card = () => screen.findByRole("region", { name: "Likely affected tests" });

test("each suggestion links its history and shows its evidence or its label", async () => {
  renderCard(impact());
  const region = await card();
  expect(await within(region).findByRole("link", { name: "pays" })).toHaveAttribute("href", `/projects/42/tests/${key("pays")}`);
  expect(within(region).getByText(/newly failed in/)).toHaveTextContent(
    "newly failed in 4 of 6 runs that changed src/payment/ (normally 3%)");
  expect(within(region).getByText("src/payment/").tagName).toBe("CODE");
  expect(within(region).getByText("test file changed")).toBeInTheDocument();
  expect(within(region).getByText("no history yet")).toBeInTheDocument();
  expect(within(region).getByText("failing on this branch")).toBeInTheDocument();
});

test("the outcome says every new failure was suggested, with a word as well as a colour", async () => {
  renderCard(impact());
  expect(await screen.findByText("Suggested 4 tests · 1 newly failed · it was suggested")).toBeInTheDocument();
  expect(screen.getByText("All caught")).toBeInTheDocument();
});

test("a new failure that was not suggested is named as missed", async () => {
  renderCard(impact({ outcome: { evaluated_at: "2026-10-12T10:01:00Z", caught: [ref("pays")], missed: [ref("refunds")] } }));
  expect(await screen.findByText("Suggested 4 tests · 2 newly failed · 1 not suggested:")).toBeInTheDocument();
  expect(screen.getByText("Missed")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "refunds" })).toHaveAttribute("href", `/projects/42/tests/${key("refunds")}`);
});

test("not enough history still lists the tests that are always included; a pending outcome says so", async () => {
  renderCard(impact({
    state: "not_enough_history", outcome: null,
    suggestion: { state: "not_enough_history", model_version: "stats-v1", history_runs: 7, needed_runs: 20, statistical_total: 0,
      tests: [labelled("cart", "failing_on_branch")] },
  }));
  expect(await screen.findByText("Not enough history yet: 7 runs with changed files, needs 20")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "cart" })).toBeInTheDocument();
  expect(screen.getByText("Suggested 1 test · outcome not recorded yet")).toBeInTheDocument();
});

test("a run without changed files says so", async () => {
  renderCard(impact({ state: "no_change_data", changed_paths: [], scored_at: null, suggestion: null, outcome: null }));
  expect(await screen.findByText("No change data for this run")).toBeInTheDocument();
});

test("a run with changes but no stored suggestion says why", async () => {
  renderCard(impact({ state: "not_scored", suggestion: null, outcome: null, scored_at: null }));
  expect(await screen.findByText(
    "No suggestion was stored for this run: it was uploaded before test impact analysis, or scoring failed.")).toBeInTheDocument();
});

test("a replayed suggestion is marked", async () => {
  renderCard(impact({ replayed: true }));
  expect(await screen.findByText("Replayed")).toBeInTheDocument();
  expect(screen.getByText("Replayed: scored later from the runs before this one, not at upload.")).toBeInTheDocument();
});

test("no likely affected tests and no new failures", async () => {
  renderCard(impact({
    suggestion: { state: "ok", model_version: "stats-v1", history_runs: 34, needed_runs: 20, statistical_total: 0, tests: [] },
    outcome: { evaluated_at: "2026-10-12T10:01:00Z", caught: [], missed: [] },
  }));
  expect(await screen.findByText("No tests are likely affected by this change")).toBeInTheDocument();
  expect(screen.getByText("Suggested 0 tests · no new failures")).toBeInTheDocument();
});

test("long lists fold behind Show all", async () => {
  const tests = Array.from({ length: 20 }, (_, i) => statistical(`t${String(i).padStart(2, "0")}`));
  renderCard(impact({
    suggestion: { state: "ok", model_version: "stats-v1", history_runs: 34, needed_runs: 20, statistical_total: 64, tests },
    outcome: { evaluated_at: "2026-10-12T10:01:00Z", caught: [], missed: [] },
  }));
  const region = await card();
  expect(await within(region).findAllByRole("link")).toHaveLength(15);
  expect(within(region).getByText("Showing the 20 strongest of 64 statistical suggestions")).toBeInTheDocument();
  await userEvent.click(within(region).getByRole("button", { name: "Show all 20" }));
  expect(within(region).getAllByRole("link")).toHaveLength(20);
});

test("a failed load shows the error with Retry, and Retry asks again", async () => {
  let calls = 0;
  server.use(http.get(IMPACT_URL, () => (++calls === 1
    ? HttpResponse.json({ detail: "Ingestion is unavailable" }, { status: 503 })
    : HttpResponse.json(impact()))));
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><ImpactCard projectId={42} runId={61} /></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Ingestion is unavailable");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("link", { name: "pays" })).toBeInTheDocument();
});
```

In `dashboard/src/pages/RunDetailPage.test.tsx`, append:

```tsx
test("a run that reported changes shows its likely affected tests beside them", async () => {
  server.use(
    http.get("/api/v1/runs/61", () => HttpResponse.json({
      ...detail([result]), change_base_ref: "origin/main", changed_files: 1, additions: 3, deletions: 1, changes_truncated: false,
      changes: [{ path: "src/payment/api.py", status: "M", additions: 3, deletions: 1 }],
    })),
    http.get("/api/v1/projects/42/runs/61/impact", () => HttpResponse.json({
      run_id: 61, state: "not_scored", changed_paths: ["src/payment/api.py"], replayed: false, scored_at: null,
      suggestion: null, outcome: null })),
  );
  renderDetail();
  expect(await screen.findByRole("heading", { name: "Changes" })).toBeInTheDocument();
  const region = await screen.findByRole("region", { name: "Likely affected tests" });
  expect(await within(region).findByText(/No suggestion was stored for this run/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd dashboard && npx vitest run src/components/ImpactCard.test.tsx src/pages/RunDetailPage.test.tsx`
Expected: FAIL. The new suite fails with `Failed to resolve import "./ImpactCard"`, and the run page test fails with `Unable to find role="region" and name "Likely affected tests"`.

- [ ] **Step 4: Write the card**

Create `dashboard/src/components/ImpactCard.tsx`:

```tsx
import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { formatCount } from "../api/analytics";
import type { ImpactOutcome, ImpactTestRef, RunImpact, SuggestedTest } from "../api/impact";
import { normally, runImpactQuery } from "../lib/impactQueries";
import ErrorBanner from "./ErrorBanner";
import { SkeletonStatus } from "./Skeleton";
import StatusPill from "./StatusPill";

/** Lines shown before "Show all" (plan Ruling 26). */
export const IMPACT_SHOWN = 15;

const LABELS: Record<Exclude<SuggestedTest["kind"], "statistical">, string> = {
  test_file_changed: "test file changed",
  no_history: "no history yet",
  failing_on_branch: "failing on this branch",
};

const plural = (n: number, one: string, many: string) => `${formatCount(n)} ${n === 1 ? one : many}`;
const historyOf = (projectId: number, test: ImpactTestRef) => `/projects/${projectId}/tests/${encodeURIComponent(test.test_key)}`;

/** A statistical suggestion's evidence in words; an always-included test's label. */
function Evidence({ test }: { test: SuggestedTest }) {
  if (test.kind !== "statistical") return <StatusPill tone="neutral" label={LABELS[test.kind]} />;
  const e = test.evidence;
  if (e === null) return null;
  return (
    <span className="muted impact-evidence">
      newly failed in {formatCount(e.new_failures)} of {formatCount(e.changed_runs)} runs that changed <code>{e.path_unit}</code> ({normally(e.base_rate)})
    </span>
  );
}

/** "Suggested 12 tests · 3 newly failed · all 3 were suggested", or the missed ones by name (spec §2.1). */
function Outcome({ projectId, suggested, outcome }: { projectId: number; suggested: number; outcome: ImpactOutcome | null }) {
  const lead = `Suggested ${plural(suggested, "test", "tests")}`;
  if (outcome === null) return <p className="muted impact-outcome">{`${lead} · outcome not recorded yet`}</p>;
  const failed = outcome.caught.length + outcome.missed.length;
  if (failed === 0) return <p className="impact-outcome">{`${lead} · no new failures`}</p>;
  const newly = `${formatCount(failed)} newly failed`;
  if (outcome.missed.length === 0) {
    const tail = failed === 1 ? "it was suggested" : `all ${formatCount(failed)} were suggested`;
    return (
      <p className="impact-outcome">
        <StatusPill tone="passed" label="All caught" />{" "}
        <span>{`${lead} · ${newly} · ${tail}`}</span>
      </p>
    );
  }
  return (
    <div className="impact-outcome">
      <p>
        <StatusPill tone="failed" label="Missed" />{" "}
        <span>{`${lead} · ${newly} · ${formatCount(outcome.missed.length)} not suggested:`}</span>
      </p>
      <ul className="impact-list">
        {outcome.missed.map((t) => <li key={t.test_key}><Link to={historyOf(projectId, t)}>{t.name}</Link></li>)}
      </ul>
    </div>
  );
}

function Body({ projectId, data }: { projectId: number; data: RunImpact }) {
  const [all, setAll] = useState(false);
  if (data.state === "no_change_data") return <p className="muted">No change data for this run</p>;
  const s = data.suggestion;
  if (data.state === "not_scored" || s === null) {
    return <p className="muted">No suggestion was stored for this run: it was uploaded before test impact analysis, or scoring failed.</p>;
  }
  const statistical = s.tests.filter((t) => t.kind === "statistical").length;
  const shown = all ? s.tests : s.tests.slice(0, IMPACT_SHOWN);
  return (
    <>
      {data.replayed && <p className="muted">Replayed: scored later from the runs before this one, not at upload.</p>}
      {s.state === "not_enough_history" && (
        <p className="muted">{`Not enough history yet: ${plural(s.history_runs, "run", "runs")} with changed files, needs ${formatCount(s.needed_runs)}`}</p>
      )}
      <Outcome projectId={projectId} suggested={s.tests.length} outcome={data.outcome} />
      {s.tests.length === 0 ? (
        <p className="muted">No tests are likely affected by this change</p>
      ) : (
        <ul className="impact-list">
          {shown.map((t) => (
            <li key={t.test_key}><Link to={historyOf(projectId, t)}>{t.name}</Link> <Evidence test={t} /></li>
          ))}
        </ul>
      )}
      {s.statistical_total > statistical && (
        <p className="muted">{`Showing the ${formatCount(statistical)} strongest of ${formatCount(s.statistical_total)} statistical suggestions`}</p>
      )}
      {!all && s.tests.length > IMPACT_SHOWN && (
        <button type="button" onClick={() => setAll(true)}>{`Show all ${formatCount(s.tests.length)}`}</button>
      )}
    </>
  );
}

/** "Likely affected tests" beside a run's Changes (spec 2026-10-12 §2.1): the suggestion stored at upload, each test's
 *  evidence or label, and the outcome once the run's results were compared. Loads and fails on its own. */
export default function ImpactCard({ projectId, runId }: { projectId: number; runId: number }) {
  const titleId = useId();
  const query = useQuery(runImpactQuery(projectId, runId));
  return (
    <section className="card impact-card" aria-labelledby={titleId}>
      <div className="impact-head">
        <h2 id={titleId}>Likely affected tests</h2>
        {query.data?.replayed && <StatusPill tone="neutral" label="Replayed" />}
      </div>
      {query.isPending && (
        <SkeletonStatus label="Loading likely affected tests…">
          <span className="skeleton skeleton-block" style={{ height: 96 }} aria-hidden="true" />
        </SkeletonStatus>
      )}
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => void query.refetch()} />}
      {query.data && <Body projectId={projectId} data={query.data} />}
    </section>
  );
}
```

- [ ] **Step 5: Put it beside Changes**

In `dashboard/src/pages/RunDetailPage.tsx`, with the Edit tool, replace:

```tsx
import FilterBar from "../components/FilterBar";
```

with:

```tsx
import FilterBar from "../components/FilterBar";
import ImpactCard from "../components/ImpactCard";
```

and replace:

```tsx
          {run.change_base_ref !== null && (
            <div className="card">
              <h2>Changes</h2>
              <p className="muted">
                {run.changed_files} file(s), +{run.additions ?? 0} −{run.deletions ?? 0} vs {run.change_base_ref}
                {run.changes_truncated && <span> · list truncated at 1000 files</span>}
              </p>
              {run.changes.length > 0 && (
                <table className="data">
                  <thead>
                    <tr>
                      <th>File</th><th>Status</th><th className="num">+</th><th className="num">−</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.changes.map((f) => (
                      <tr key={f.path}>
                        <td>{f.path}</td>
                        <td>{f.status}</td>
                        <td className="num">{f.additions ?? "—"}</td>
                        <td className="num">{f.deletions ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
```

with:

```tsx
          {run.change_base_ref !== null && (
            <div className="run-change-cards">
              <div className="card">
                <h2>Changes</h2>
                <p className="muted">
                  {run.changed_files} file(s), +{run.additions ?? 0} −{run.deletions ?? 0} vs {run.change_base_ref}
                  {run.changes_truncated && <span> · list truncated at 1000 files</span>}
                </p>
                {run.changes.length > 0 && (
                  <table className="data">
                    <thead>
                      <tr>
                        <th>File</th><th>Status</th><th className="num">+</th><th className="num">−</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.changes.map((f) => (
                        <tr key={f.path}>
                          <td>{f.path}</td>
                          <td>{f.status}</td>
                          <td className="num">{f.additions ?? "—"}</td>
                          <td className="num">{f.deletions ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <ImpactCard projectId={Number(projectId)} runId={run.id} />
            </div>
          )}
```

(The `−` in the summary line and the header is U+2212 MINUS SIGN and `—` is U+2014, exactly as in the file today.)

Append to `dashboard/src/index.css` (Git Bash; the file keeps LF endings):

```bash
cat >> dashboard/src/index.css <<'EOF'

/* Test impact (spec 2026-10-12): a run's Changes and Likely affected tests side by side when there is room, stacked
   when not; the evidence and the outcome line use tabular figures */
.run-change-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: var(--space-4); margin-block: var(--space-4); align-items: start; }
.run-change-cards > .card { margin: 0; min-width: 0; overflow-x: auto; }
.impact-head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-3); }
.impact-head h2 { margin: 0; }
.impact-list { list-style: none; margin: 0 0 var(--space-3); padding: 0; display: grid; gap: var(--space-2); }
.impact-list li { overflow-wrap: anywhere; }
.impact-evidence, .impact-outcome { font-variant-numeric: tabular-nums; }
EOF
```

- [ ] **Step 6: Run the tests and the checks**

Run: `cd dashboard && npx vitest run src/components/ImpactCard.test.tsx src/pages/RunDetailPage.test.tsx && npm run lint && npm run typecheck`
Expected: PASS. The existing run page tests are untouched: their runs report no changes, so no card is asked for.

Then check the page by hand in the dev server (`cd dashboard && npm run dev`, against a stack with a run that has changes) at 1440 px and at 375 px:
- the cards sit side by side and then stack;
- the pills show their icons;
- keyboard focus reaches every link and the Show all button.

- [ ] **Step 7: Document**

In `DESIGN.md`, with the Edit tool, replace:

```
### Inputs / Fields
```

with:

```
### Test Impact
Likely affected tests (spec `docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md`, ADR-029).

- **Run page card** "Likely affected tests", beside Changes.
  - **Layout:** the two share a row when there is room (`.run-change-cards`) and stack on narrow screens.
  - **Suggestions,** strongest first: each is a link to the test's history, followed by its evidence in Graphite with tabular figures and the unit in a code span ("newly failed in 4 of 6 runs that changed `src/payment/` (normally 3%)"), or by a neutral Status Pill label (*test file changed*, *no history yet*, *failing on this branch*).
  - **Outcome line:**
    - "Suggested 12 tests · 3 newly failed · all 3 were suggested" with an "All caught" pill in the passed tone;
    - or "… · 1 not suggested:" with a "Missed" pill in the failed tone and each missed test linked;
    - "no new failures" when there are none, and "outcome not recorded yet" while it is written.
  - **Plain Graphite sentences** for "Not enough history yet: N runs with changed files, needs 20" (the labelled tests are still listed), "No change data for this run", and a run with no stored suggestion.
  - **Replayed:** a neutral "Replayed" pill beside the heading, and a sentence that says so.
  - Lists past 15 fold behind "Show all n". Loading is a skeleton in a status region; a failure is an Error Banner with Retry.

### Inputs / Fields
```

In `docs/SETUP.md`, with the Edit tool, replace:

```
| Run page | Results, failures grouped by cause (new, or failing for N runs in a row), owners from CODEOWNERS, changed files, components, a link to the CI job. | **Compare with previous run #N**. |
```

with:

```
| Run page | Results, failures grouped by cause (new, or failing for N runs in a row), owners from CODEOWNERS, changed files with the **likely affected tests** beside them (evidence, and which new failures were suggested or missed), components, a link to the CI job. | **Compare with previous run #N**. |
```

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/components/ImpactCard.tsx dashboard/src/components/ImpactCard.test.tsx dashboard/src/pages/RunDetailPage.tsx dashboard/src/pages/RunDetailPage.test.tsx dashboard/src/index.css DESIGN.md docs/SETUP.md
git commit -m "feat(dashboard): Likely affected tests beside a run's changes, with evidence and outcome" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/components/ImpactCard.tsx dashboard/src/components/ImpactCard.test.tsx dashboard/src/pages/RunDetailPage.tsx dashboard/src/pages/RunDetailPage.test.tsx dashboard/src/index.css DESIGN.md docs/SETUP.md
```

---

### Task 15: The Report's "Test impact" section

**Files:**
- Create: `dashboard/src/pages/report/sections/ImpactSection.tsx`, `dashboard/src/pages/report/sections/ImpactSection.test.tsx`
- Modify: `dashboard/src/pages/report/ReportSection.tsx`, `dashboard/src/pages/report/ReportPage.tsx`, `dashboard/src/pages/report/ReportPage.test.tsx`, `dashboard/src/index.css`, `DESIGN.md`, `docs/SETUP.md`

**Interfaces:**
- Consumes:
  - Task 13: `useImpactAccuracy`, `accuracyDays`, `caughtText`, and the types `ImpactAccuracy`, `AccuracyPart`, `AccuracyDays`.
  - Existing: `formatCount`, `formatPassRate`, `StatusPill`, `ReportSection`.
- Produces:
  - `ReportSection<T = Report>`: `gate?: Gate`, `isEmpty?: (data: T) => boolean` (default: `scope.runs === 0`), `emptyText?: string` (default "No runs match these filters in this period"), `noRuns?: (data: T) => ReactNode`, and `children: (data: T) => ReactNode`; `SectionQuery<T = Report>`.
  - `ImpactSection({ projectId: number; days: AccuracyDays; onResetFilters: () => void })`, anchor `report-impact`.

- [ ] **Step 1: Invoke `ui-ux-pro-max`**

Invoke the `ui-ux-pro-max` skill for a single-figure report section with a misses table. Follow DESIGN.md's Report sections:
- the figure in tabular figures;
- the live and replayed parts as a definition list;
- the "Replayed" pill;
- the table's caption for screen readers.

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/pages/report/sections/ImpactSection.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../../../test/server";
import { setAccessToken } from "../../../auth/tokens";
import type { ImpactAccuracy } from "../../../api/impact";
import ImpactSection from "./ImpactSection";

const ACCURACY_URL = "/api/v1/projects/42/analytics/impact-accuracy";
const key = (name: string) => name.padEnd(64, "0");

function accuracy(extra: Partial<ImpactAccuracy> = {}): ImpactAccuracy {
  return {
    days: 30, caught: 9, missed: 3, rate: 0.75, includes_replayed: false,
    live: { runs: 25, caught: 9, missed: 3 }, replayed: { runs: 0, caught: 0, missed: 0 },
    misses: [{ test_key: key("refunds"), suite: "s", class_name: "C", name: "refunds", run_id: 70,
      started_at: "2026-10-10T09:00:00Z", branch: "main", replayed: false }],
    misses_total: 3, ...extra,
  };
}

function renderSection(answer: () => Response, days: 7 | 14 | 30 = 30) {
  const asked: string[] = [];
  server.use(http.get(ACCURACY_URL, ({ request }) => {
    asked.push(new URL(request.url).searchParams.get("days") ?? "");
    return answer();
  }));
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><ImpactSection projectId={42} days={days} onResetFilters={() => undefined} /></MemoryRouter>
    </QueryClientProvider>,
  );
  return asked;
}

const region = () => screen.findByRole("region", { name: "Test impact" });

test("the figure, what it counts, and the misses with links", async () => {
  const asked = renderSection(() => HttpResponse.json(accuracy()));
  const section = await region();
  expect(await within(section).findByText("75.0%")).toBeInTheDocument();
  expect(within(section).getByText("Suggestions caught 9 of 12 new failures")).toBeInTheDocument();
  expect(within(section).getByText(/Last 30 days, every branch/)).toBeInTheDocument();
  expect(within(section).getByRole("link", { name: "refunds" })).toHaveAttribute("href", `/projects/42/tests/${key("refunds")}`);
  expect(within(section).getByRole("link", { name: "#70" })).toHaveAttribute("href", "/projects/42/runs/70");
  expect(within(section).getByText("And 2 more.")).toBeInTheDocument();
  expect(asked).toEqual(["30"]);
});

test("replayed and live parts are told apart", async () => {
  renderSection(() => HttpResponse.json(accuracy({
    includes_replayed: true, live: { runs: 10, caught: 3, missed: 1 }, replayed: { runs: 15, caught: 6, missed: 2 },
    misses: [{ test_key: key("refunds"), suite: "s", class_name: "C", name: "refunds", run_id: 70,
      started_at: "2026-10-10T09:00:00Z", branch: null, replayed: true }],
  })), 7);
  const section = await region();
  expect(await within(section).findByText("caught 3 of 4 new failures in 10 runs")).toBeInTheDocument();
  expect(within(section).getByText("caught 6 of 8 new failures in 15 runs")).toBeInTheDocument();
  expect(within(section).getByText("Replayed", { selector: ".pill" })).toBeInTheDocument();
  expect(within(section).getByText("no branch")).toBeInTheDocument();
});

test("no run with a stored suggestion says so plainly", async () => {
  renderSection(() => HttpResponse.json(accuracy({ caught: 0, missed: 0, rate: null, live: { runs: 0, caught: 0, missed: 0 },
    misses: [], misses_total: 0 })), 7);
  expect(await within(await region()).findByText("No run with a stored suggestion in the last 7 days")).toBeInTheDocument();
});

test("runs without new failures have no rate, never 0%", async () => {
  renderSection(() => HttpResponse.json(accuracy({ caught: 0, missed: 0, rate: null, live: { runs: 4, caught: 0, missed: 0 },
    misses: [], misses_total: 0 })));
  expect(await screen.findByText("No new failures in 4 runs with a stored suggestion")).toBeInTheDocument();
  expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
});

test("a failure shows in the section with Retry", async () => {
  let calls = 0;
  renderSection(() => (++calls === 1
    ? HttpResponse.json({ detail: "Ingestion is unavailable" }, { status: 503 })
    : HttpResponse.json(accuracy())));
  expect(await screen.findByRole("alert")).toHaveTextContent("Ingestion is unavailable");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("75.0%")).toBeInTheDocument();
});
```

In `dashboard/src/pages/report/ReportPage.test.tsx`, append:

```tsx
test("Test impact closes the report and follows a 7-day period", async () => {
  serve();
  const asked: string[] = [];
  server.use(http.get(`${P}/analytics/impact-accuracy`, ({ request }) => {
    asked.push(new URL(request.url).searchParams.get("days") ?? "");
    return HttpResponse.json({ days: 7, caught: 0, missed: 0, rate: null, includes_replayed: false,
      live: { runs: 0, caught: 0, missed: 0 }, replayed: { runs: 0, caught: 0, missed: 0 }, misses: [], misses_total: 0 });
  }));
  renderPage("?period=7");
  expect(await screen.findByRole("heading", { name: "Test impact" })).toBeInTheDocument();
  expect(await screen.findByText("No run with a stored suggestion in the last 7 days")).toBeInTheDocument();
  expect(asked).toEqual(["7"]);
});
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd dashboard && npx vitest run src/pages/report/sections/ImpactSection.test.tsx src/pages/report/ReportPage.test.tsx`
Expected: FAIL. The new suite fails with `Failed to resolve import "./ImpactSection"`, and the Report test fails with `Unable to find role="heading" and name "Test impact"`.

- [ ] **Step 4: Let `ReportSection` frame any answer**

In `dashboard/src/pages/report/ReportSection.tsx`, with the Edit tool, replace:

```tsx
/** What a section needs from its query (UseQueryResult<Report> fits). */
export interface SectionQuery {
  data: Report | undefined;
  error: unknown;
  isPending: boolean;
  refetch: () => unknown;
}

interface Props {
  id: string;
  title: string;
  gate: Gate;
  query: SectionQuery;
```

with:

```tsx
/** What a section needs from its query (UseQueryResult<Report> fits; a section with its own answer names its type). */
export interface SectionQuery<T = Report> {
  data: T | undefined;
  error: unknown;
  isPending: boolean;
  refetch: () => unknown;
}

interface Props<T> {
  id: string;
  title: string;
  /** The Report's gate. A section that does not follow the Report's filters (Test impact) leaves it out. */
  gate?: Gate;
  query: SectionQuery<T>;
```

then replace:

```tsx
  /** Extra content for "No runs match these filters in this period" */
  noRuns?: (report: Report) => ReactNode;
  onResetFilters: () => void;
  children: (report: Report) => ReactNode;
}
```

with:

```tsx
  /** Whether the answer has nothing to show; by default a Report with no runs in scope */
  isEmpty?: (data: T) => boolean;
  /** The sentence for an empty answer */
  emptyText?: string;
  /** Extra content under the empty sentence */
  noRuns?: (data: T) => ReactNode;
  onResetFilters: () => void;
  children: (data: T) => ReactNode;
}

const noRunsInScope = (data: unknown) => (data as Report).scope.runs === 0;
```

then replace:

```tsx
export default function ReportSection({ id, title, gate, query, height = 240, actions, note, noRuns, onResetFilters, children }: Props) {
  let body: ReactNode;
  if (gate.state === "blocked") {
```

with:

```tsx
export default function ReportSection<T = Report>({
  id, title, gate, query, height = 240, actions, note, isEmpty = noRunsInScope,
  emptyText = "No runs match these filters in this period", noRuns, onResetFilters, children,
}: Props<T>) {
  let body: ReactNode;
  if (gate?.state === "blocked") {
```

then replace:

```tsx
  } else if (gate.state === "wait" || query.isPending || !query.data) {
```

with:

```tsx
  } else if (gate?.state === "wait" || query.isPending || !query.data) {
```

then replace:

```tsx
  } else if (query.data.scope.runs === 0) {
    body = (
      <div className="report-empty">
        <p className="muted">No runs match these filters in this period</p>
        {noRuns?.(query.data)}
      </div>
    );
```

with:

```tsx
  } else if (isEmpty(query.data)) {
    body = (
      <div className="report-empty">
        <p className="muted">{emptyText}</p>
        {noRuns?.(query.data)}
      </div>
    );
```

- [ ] **Step 5: Write the section**

Create `dashboard/src/pages/report/sections/ImpactSection.tsx`:

```tsx
import { Link } from "react-router-dom";
import { formatCount, formatPassRate } from "../../../api/analytics";
import type { AccuracyDays, AccuracyPart, ImpactAccuracy } from "../../../api/impact";
import StatusPill from "../../../components/StatusPill";
import { caughtText, useImpactAccuracy } from "../../../lib/impactQueries";
import ReportSection from "../ReportSection";

const when = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function part(p: AccuracyPart): string {
  const runs = `${formatCount(p.runs)} ${p.runs === 1 ? "run" : "runs"}`;
  return p.caught + p.missed === 0 ? `${runs}, no new failures` : `caught ${caughtText(p.caught, p.missed)} in ${runs}`;
}

interface Props {
  projectId: number;
  days: AccuracyDays;
  onResetFilters: () => void;
}

/** Test impact (spec 2026-10-12 §2.3, plan Ruling 21): how often the suggestions stored with runs contained their new
 *  failures, over the last 7, 14 or 30 days on every branch, live and replayed apart, with the misses. */
export default function ImpactSection({ projectId, days, onResetFilters }: Props) {
  const query = useImpactAccuracy(projectId, days);
  return (
    <ReportSection
      id="report-impact" title="Test impact" query={query} height={160} onResetFilters={onResetFilters}
      note={`Last ${days} days, every branch: how often the likely affected tests stored with each run contained its new failures. The other filters do not apply.`}
      isEmpty={(a: ImpactAccuracy) => a.live.runs + a.replayed.runs === 0}
      emptyText={`No run with a stored suggestion in the last ${days} days`}
    >
      {(a: ImpactAccuracy) => (
        <>
          {a.rate === null ? (
            <p>{`No new failures in ${formatCount(a.live.runs + a.replayed.runs)} runs with a stored suggestion`}</p>
          ) : (
            <p className="impact-figure-line">
              <span className="impact-figure">{formatPassRate(a.rate)}</span>{" "}
              <span>{`Suggestions caught ${caughtText(a.caught, a.missed)}`}</span>
            </p>
          )}
          {a.includes_replayed && (
            <dl className="overview-figures">
              <div><dt>Live</dt><dd>{part(a.live)}</dd></div>
              <div><dt>Replayed</dt><dd>{part(a.replayed)}</dd></div>
            </dl>
          )}
          {a.misses.length > 0 && (
            <table className="data">
              <caption className="sr-only">New failures the suggestions missed</caption>
              <thead>
                <tr>
                  <th scope="col">Missed test</th><th scope="col">Run</th><th scope="col">Branch</th>
                  <th scope="col">Started</th><th scope="col">Suggestion</th>
                </tr>
              </thead>
              <tbody>
                {a.misses.map((m) => (
                  <tr key={`${m.run_id}-${m.test_key}`}>
                    <td><Link to={`/projects/${projectId}/tests/${encodeURIComponent(m.test_key)}`}>{m.name}</Link></td>
                    <td><Link to={`/projects/${projectId}/runs/${m.run_id}`}>{`#${m.run_id}`}</Link></td>
                    <td>{m.branch ?? "no branch"}</td>
                    <td className="num">{when.format(new Date(m.started_at))}</td>
                    <td>{m.replayed ? <StatusPill tone="neutral" label="Replayed" /> : "Live"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {a.misses_total > a.misses.length && (
            <p className="muted report-note">{`And ${formatCount(a.misses_total - a.misses.length)} more.`}</p>
          )}
        </>
      )}
    </ReportSection>
  );
}
```

- [ ] **Step 6: Close the Report with it**

In `dashboard/src/pages/report/ReportPage.tsx`, with the Edit tool, replace:

```tsx
import FailureCausesSection from "./sections/FailureCausesSection";
```

with:

```tsx
import FailureCausesSection from "./sections/FailureCausesSection";
import ImpactSection from "./sections/ImpactSection";
```

then replace:

```tsx
import { todayIn, useReportFilters } from "./useReportFilters";
```

with:

```tsx
import { accuracyDays } from "../../lib/impactQueries";
import { todayIn, useReportFilters } from "./useReportFilters";
```

then replace:

```tsx
        filters={filters} onResetFilters={clearAll} />
    </div>
```

with:

```tsx
        filters={filters} onResetFilters={clearAll} />
      <ImpactSection projectId={id} days={accuracyDays(filters.days, filters.to, today)} onResetFilters={clearAll} />
    </div>
```

Append to `dashboard/src/index.css`:

```bash
cat >> dashboard/src/index.css <<'EOF'
.impact-figure-line { display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--space-2); }
.impact-figure { font-size: 26px; font-weight: 650; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; }
EOF
```

- [ ] **Step 7: Run the tests and the checks**

Run: `cd dashboard && npx vitest run src/pages/report && npm run lint && npm run typecheck`
Expected: PASS. Every existing Report test still passes, because their sections pass a gate and the default emptiness rule is unchanged.

- [ ] **Step 8: Document**

In `DESIGN.md`, with the Edit tool, replace:

```
  - Lists past 15 fold behind "Show all n". Loading is a skeleton in a status region; a failure is an Error Banner with Retry.

### Inputs / Fields
```

with:

```
  - Lists past 15 fold behind "Show all n". Loading is a skeleton in a status region; a failure is an Error Banner with Retry.
- **Report section** "Test impact" (`#report-impact`, the Report's last section).
  - **Figure:** "75.0%" in tile size with tabular figures, then "Suggestions caught 9 of 12 new failures".
  - **Note:** the window (the Report's period when it is the last 7, 14 or 30 days, else 30), every branch, other filters not applied.
  - **Replayed runs present:** a definition list with Live and Replayed ("caught 3 of 4 new failures in 10 runs").
  - **Misses:** a table of up to 50, linking the test's history and the run, the Suggestion column reading "Live" or a neutral "Replayed" pill; "And n more." under it.
  - **No new failures:** says so instead of a rate, never 0%.
  - **Loading and failure** behave as in every Report section.

### Inputs / Fields
```

In `docs/SETUP.md`, with the Edit tool, replace:

```
| **Report** | Summary, pass rate by week, flaky tests, branches, the top failing and slowest tests. | Period 7 / 30 / 90 days; **Save as PDF** (the browser's print dialog), **Download CSV**. |
```

with:

```
| **Report** | Summary, pass rate by week, flaky tests, branches, the top failing and slowest tests, and **Test impact**: how often the likely affected tests stored with each run contained its new failures, with the misses. | Period 7 / 30 / 90 days (Test impact uses the period when it is 7 or 30 days, else 30); **Save as PDF** (the browser's print dialog), **Download CSV**. |
```

- [ ] **Step 9: Commit**

```bash
git add dashboard/src/pages/report/ReportSection.tsx dashboard/src/pages/report/sections/ImpactSection.tsx dashboard/src/pages/report/sections/ImpactSection.test.tsx dashboard/src/pages/report/ReportPage.tsx dashboard/src/pages/report/ReportPage.test.tsx dashboard/src/index.css DESIGN.md docs/SETUP.md
git commit -m "feat(dashboard): Test impact section in the Report (accuracy, live and replayed, misses)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/pages/report/ReportSection.tsx dashboard/src/pages/report/sections/ImpactSection.tsx dashboard/src/pages/report/sections/ImpactSection.test.tsx dashboard/src/pages/report/ReportPage.tsx dashboard/src/pages/report/ReportPage.test.tsx dashboard/src/index.css DESIGN.md docs/SETUP.md
```

---

### Task 16: The Overview widget `impact_accuracy`

**Files:**
- Create: `dashboard/src/overview/widgets/impactAccuracy.ts`, `dashboard/src/overview/widgets/ImpactAccuracyWidget.tsx`, `dashboard/src/overview/widgets/impactWidget.test.tsx`
- Modify:
  - catalogue `shared/qeos_shared/overview_widgets.json`, `shared/tests/test_overview_widgets.py`, `shared/README.md`;
  - `platforms/project-service/tests/unit/test_overview_layout_validation.py`;
  - dashboard `dashboard/src/overview/catalog.ts`, `dashboard/src/overview/catalog.test.ts`, `dashboard/src/overview/widgets/registry.ts`;
  - docs `DESIGN.md`, `README.md`, `PRODUCT.md`, `docs/SETUP.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md`, `TECHNICAL_SPECIFICATION.md`.

**Interfaces:**
- Consumes:
  - Task 13: `useImpactAccuracy`, `impactAccuracyStaleKeys`, `caughtText`, `AccuracyDays`.
  - Existing: `WidgetDefinition`, `WidgetProps`, `reportLink`, `ReportFoot`, `WidgetEmpty`, `SkeletonStat`, `ErrorBanner`, `formatCount`, `formatPassRate`; project-service's `validate_layout` (reads the catalogue, no code change).
- Produces:
  - Catalogue type `"impact_accuracy": {"settings": ["period"]}`.
  - `WidgetType` gains `"impact_accuracy"`.
  - `impactAccuracy: WidgetDefinition`:
    - title "Impact accuracy", `defaults: { period: 30 }`, `cardTitle` "Impact accuracy, last N days";
    - link `reportLink(projectId, period, undefined, "report-impact")`;
    - `staleKeys: impactAccuracyStaleKeys`.

- [ ] **Step 1: Invoke `ui-ux-pro-max`**

Invoke the `ui-ux-pro-max` skill for a single-figure KPI widget. Follow DESIGN.md "Overview Widgets":
- the `stat-big` figure;
- a muted line under it;
- the empty state with **Change settings**;
- a card foot linking the Report.

- [ ] **Step 2: Write the failing tests**

In `shared/tests/test_overview_widgets.py`, with the Edit tool, replace:

```python
    "my_suites": ["rows"],
}


def test_the_fourteen_types_and_their_settings():
```

with:

```python
    "my_suites": ["rows"],
    "impact_accuracy": ["period"],
}


def test_the_fifteen_types_and_their_settings():
```

In `platforms/project-service/tests/unit/test_overview_layout_validation.py`, with the Edit tool, replace:

```python
    widget("w14", "my_suites", rows=10),
)
```

with:

```python
    widget("w14", "my_suites", rows=10),
    widget("w15", "impact_accuracy", period=7),
)
```

In `dashboard/src/overview/catalog.test.ts`, with the Edit tool, replace:

```ts
  expect(Object.keys(CATALOG.types)).toHaveLength(14);
```

with:

```ts
  expect(Object.keys(CATALOG.types)).toHaveLength(15);
  expect(CATALOG.types.impact_accuracy.settings).toEqual(["period"]);
```

Create `dashboard/src/overview/widgets/impactWidget.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { partialMatchKey } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { mockOverviewData, personalState, renderOverview } from "../testing";
import { impactAccuracy } from "./impactAccuracy";
import { newRunStaleKeys } from "./registry";

const ACCURACY = {
  days: 7, caught: 9, missed: 3, rate: 0.75, includes_replayed: false,
  live: { runs: 25, caught: 9, missed: 3 }, replayed: { runs: 0, caught: 0, missed: 0 }, misses: [], misses_total: 3,
};

function accuracyAsked(answer: () => Response) {
  const asked: string[] = [];
  server.use(http.get("/api/v1/projects/42/analytics/impact-accuracy", ({ request }) => {
    asked.push(new URL(request.url).searchParams.get("days") ?? "");
    return answer();
  }));
  return asked;
}

test("Impact accuracy shows the share of new failures the suggestions caught and opens the Report's section", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal", settings: { period: 7 } }) });
  const asked = accuracyAsked(() => HttpResponse.json(ACCURACY));
  renderOverview();
  expect(await screen.findByText("75.0%")).toBeInTheDocument();
  expect(screen.getByText("Caught 9 of 12 new failures")).toBeInTheDocument();
  const heading = await screen.findByRole("heading", { name: "Impact accuracy, last 7 days" });
  expect(within(heading).getByRole("link")).toHaveAttribute("href", "/projects/42/report?period=7&branch=*#report-impact");
  expect(screen.getByRole("link", { name: "Report" })).toHaveAttribute("href", "/projects/42/report?period=7&branch=*#report-impact");
  expect(asked).toEqual(["7"]);
});

test("replayed runs are counted in and said", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal" }) });
  const asked = accuracyAsked(() => HttpResponse.json({ ...ACCURACY, days: 30, includes_replayed: true,
    replayed: { runs: 20, caught: 6, missed: 2 } }));
  renderOverview();
  expect(await screen.findByText("Includes 20 replayed runs")).toBeInTheDocument();
  expect(asked).toEqual(["30"]);
});

test("no run with a stored suggestion in the period is said plainly, with Change settings", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal" }) });
  accuracyAsked(() => HttpResponse.json({ ...ACCURACY, days: 30, caught: 0, missed: 0, rate: null,
    live: { runs: 0, caught: 0, missed: 0 } }));
  renderOverview();
  expect(await screen.findByText("No run with a stored suggestion in the last 30 days")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Change settings/ })).toBeInTheDocument();
  expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
});

test("runs without new failures show a dash, never 0%", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal" }) });
  accuracyAsked(() => HttpResponse.json({ ...ACCURACY, days: 30, caught: 0, missed: 0, rate: null,
    live: { runs: 4, caught: 0, missed: 0 } }));
  renderOverview();
  expect(await screen.findByText("No new failures in 4 runs")).toBeInTheDocument();
  expect(screen.getByText("—")).toBeInTheDocument();
});

test("a failure stays in the card with Retry", async () => {
  mockOverviewData({ layout: personalState({ id: "i", type: "impact_accuracy", size: "normal" }) });
  let calls = 0;
  accuracyAsked(() => (++calls === 1
    ? HttpResponse.json({ detail: "Ingestion is unavailable" }, { status: 503 })
    : HttpResponse.json(ACCURACY)));
  renderOverview();
  expect(await screen.findByRole("alert")).toHaveTextContent("Ingestion is unavailable");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("75.0%")).toBeInTheDocument();
});

test("a new latest run refreshes the figure through the Report's key", () => {
  expect(impactAccuracy.staleKeys?.(42)).toEqual([["report", 42, "impact-accuracy"]]);
  expect(newRunStaleKeys(42).some((key) => partialMatchKey(["report", 42, "impact-accuracy", 7], key))).toBe(true);
});
```

- [ ] **Step 3: Run them to see them fail**

```bash
cd shared && SECRET_KEY=test ../platforms/organization-service/.venv/Scripts/python -m pytest tests/test_overview_widgets.py -q
cd platforms/project-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_overview_layout_validation.py -q
cd dashboard && npx vitest run src/overview/catalog.test.ts src/overview/widgets/impactWidget.test.tsx
```

Expected: FAIL, in three places:
- the shared test lacks `impact_accuracy` in the catalogue;
- `test_every_type_with_valid_settings_passes` fails with `LayoutError` naming the unknown type `impact_accuracy`;
- the dashboard catalogue length is 14, and `./impactAccuracy` cannot be resolved.

- [ ] **Step 4: Add the type to the shared catalogue**

In `shared/qeos_shared/overview_widgets.json`, with the Edit tool, replace:

```json
    "my_suites": {"settings": ["rows"]}
```

with:

```json
    "my_suites": {"settings": ["rows"]},
    "impact_accuracy": {"settings": ["period"]}
```

Run the shared and project-service commands of Step 3 again. Expected: PASS. project-service validates against the file with no code change.

Run: `cd dashboard && npx vitest run src/overview/widgets/registry.test.ts`
Expected: FAIL, `the registry has a widget for every catalogue type, and no other`: the registry lacks `impact_accuracy`. This is the registry↔catalogue test doing its job.

- [ ] **Step 5: The dashboard's type, definition and component**

In `dashboard/src/overview/catalog.ts`, with the Edit tool, replace:

```ts
  | "my_failures" | "my_suites";
```

with:

```ts
  | "my_failures" | "my_suites" | "impact_accuracy";
```

Create `dashboard/src/overview/widgets/impactAccuracy.ts`:

```ts
import { lazy } from "react";
import { impactAccuracyStaleKeys } from "../../lib/impactQueries";
import { reportLink } from "../reportWidget";
import type { WidgetDefinition } from "./types";

export const impactAccuracy: WidgetDefinition = {
  type: "impact_accuracy",
  title: "Impact accuracy",
  description: "How often the likely affected tests suggested for a change contained its new failures, over 7, 14 or 30 days.",
  defaultSize: "normal",
  settings: ["period"],
  defaults: { period: 30 },
  cardTitle: (settings) => `Impact accuracy, last ${settings.period ?? 30} days`,
  Component: lazy(() => import("./ImpactAccuracyWidget")),
  // Every branch: the figure does not follow a branch (plan Ruling 21)
  link: (projectId, settings) => reportLink(projectId, settings.period ?? 30, undefined, "report-impact"),
  staleKeys: impactAccuracyStaleKeys,
};
```

Create `dashboard/src/overview/widgets/ImpactAccuracyWidget.tsx`:

```tsx
import { formatCount, formatPassRate } from "../../api/analytics";
import type { AccuracyDays } from "../../api/impact";
import ErrorBanner from "../../components/ErrorBanner";
import { SkeletonStat } from "../../components/Skeleton";
import { caughtText, useImpactAccuracy } from "../../lib/impactQueries";
import WidgetEmpty from "../WidgetEmpty";
import ReportFoot from "./ReportFoot";
import { impactAccuracy } from "./impactAccuracy";
import type { WidgetProps } from "./types";

/** The Report's Test impact figure (spec 2026-10-12 §2.3) under the same query: the share of new failures the stored
 *  suggestions caught over the period, on every branch, with replayed runs counted and said. */
export default function ImpactAccuracyWidget({ projectId, settings, heading, titleId, onOpenSettings }: WidgetProps) {
  const days = (settings.period ?? 30) as AccuracyDays;
  const accuracy = useImpactAccuracy(projectId, days);
  const a = accuracy.data;
  const runs = a ? a.live.runs + a.replayed.runs : 0;
  return (
    <>
      {heading}
      {accuracy.isPending && <SkeletonStat label="Loading impact accuracy…" />}
      {accuracy.error != null && <ErrorBanner error={accuracy.error} onRetry={() => void accuracy.refetch()} />}
      {a && runs === 0 && (
        <WidgetEmpty onOpenSettings={onOpenSettings} titleId={titleId}>
          {`No run with a stored suggestion in the last ${days} days`}
        </WidgetEmpty>
      )}
      {a && runs > 0 && (
        <>
          <div className="stat-big">{a.rate === null ? "—" : formatPassRate(a.rate)}</div>
          <p className="muted">{a.rate === null ? `No new failures in ${formatCount(runs)} runs` : `Caught ${caughtText(a.caught, a.missed)}`}</p>
          {a.includes_replayed && (
            <p className="muted">{`Includes ${formatCount(a.replayed.runs)} replayed ${a.replayed.runs === 1 ? "run" : "runs"}`}</p>
          )}
        </>
      )}
      <ReportFoot to={impactAccuracy.link(projectId, settings)} />
    </>
  );
}
```

In `dashboard/src/overview/widgets/registry.ts`, with the Edit tool, replace:

```ts
import { flakyCount } from "./flakyCount";
```

with:

```ts
import { flakyCount } from "./flakyCount";
import { impactAccuracy } from "./impactAccuracy";
```

and replace:

```ts
  my_suites: mySuites,
};
```

with:

```ts
  my_suites: mySuites,
  impact_accuracy: impactAccuracy,
};
```

- [ ] **Step 6: Run the tests and the checks**

Run: `cd dashboard && npx vitest run src/overview && npm run lint && npm run typecheck`
Expected: PASS. `registry.test.ts` now passes, because every catalogue type has a widget with exactly its settings and allowed defaults.

- [ ] **Step 7: Document the fifteenth widget**

Make these replacements with the Edit tool:
- `shared/README.md`: replace `the 14 widget types` with `the 15 widget types`.
- `DESIGN.md`:
  - replace `- **Catalogue (14):**` with `- **Catalogue (15):**`;
  - replace `Test cases (the four Cases KPI tiles), My recent failures and My suites.` with `Test cases (the four Cases KPI tiles), My recent failures, My suites and Impact accuracy (the Report's Test impact figure, a dash when there were no new failures, replayed runs said).`
- `README.md`: replace `pick from fourteen widgets: the built-in four, plus Pass-rate trend, Failure causes, Regressions and flips, Slowest tests, Coverage, Recent runs, Branch health, Test cases, My suites and My recent failures.` with `pick from fifteen widgets: the built-in four, plus Pass-rate trend, Failure causes, Regressions and flips, Slowest tests, Coverage, Recent runs, Branch health, Test cases, My suites, My recent failures and Impact accuracy.`
- `PRODUCT.md`: replace `- Fourteen widget types; a type may appear more than once` with `- Fifteen widget types; a type may appear more than once`.
- `docs/SETUP.md`:
  - replace `**Widgets** (14; settings are` with `**Widgets** (15; settings are`;
  - replace `- **My suites:** the suites you created.` with `- **My suites:** the suites you created.` followed by a new line `- **Impact accuracy:** how often the likely affected tests stored with each run contained its new failures, over 7, 14 or 30 days on every branch; replayed runs are counted and said.`
- `ARCHITECTURE_BLUEPRINT_V1_0.md`: replace `(realized for the project Overview: 14 widgets,` with `(realized for the project Overview: 15 widgets,`.
- `TECHNICAL_SPECIFICATION.md`: replace `customisable grid of 14 code-split widgets` with `customisable grid of 15 code-split widgets`.

Run: `grep -rn "fourteen\|Fourteen\|(14)\|14 widget\|14 code-split" README.md PRODUCT.md DESIGN.md docs/SETUP.md shared/README.md TECHNICAL_SPECIFICATION.md ARCHITECTURE_BLUEPRINT_V1_0.md`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add shared/qeos_shared/overview_widgets.json shared/tests/test_overview_widgets.py shared/README.md platforms/project-service/tests/unit/test_overview_layout_validation.py dashboard/src/overview/catalog.ts dashboard/src/overview/catalog.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/overview/widgets/impactAccuracy.ts dashboard/src/overview/widgets/ImpactAccuracyWidget.tsx dashboard/src/overview/widgets/impactWidget.test.tsx DESIGN.md README.md PRODUCT.md docs/SETUP.md ARCHITECTURE_BLUEPRINT_V1_0.md TECHNICAL_SPECIFICATION.md
git commit -m "feat(overview): Impact accuracy widget, catalogued for validation and the registry" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- shared/qeos_shared/overview_widgets.json shared/tests/test_overview_widgets.py shared/README.md platforms/project-service/tests/unit/test_overview_layout_validation.py dashboard/src/overview/catalog.ts dashboard/src/overview/catalog.test.ts dashboard/src/overview/widgets/registry.ts dashboard/src/overview/widgets/impactAccuracy.ts dashboard/src/overview/widgets/ImpactAccuracyWidget.tsx dashboard/src/overview/widgets/impactWidget.test.tsx DESIGN.md README.md PRODUCT.md docs/SETUP.md ARCHITECTURE_BLUEPRINT_V1_0.md TECHNICAL_SPECIFICATION.md
```

---

### Task 17: Phase 2 gate

**Files:** none new (fixes only, in the files of Tasks 13–16).

**Interfaces:** Consumes everything in Phases 1–2; produces a pushed `master`.

- [ ] **Step 1:** Every Python suite serially and the collector (Task 12 Step 1). Expected: all green.
- [ ] **Step 2:** `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build && node --test ../templates/github/qeos-run.test.mjs`. Expected: all green, and the build output lists an `ImpactAccuracyWidget` chunk beside the other 14 widget chunks.
- [ ] **Step 3:** `python scripts/check_architecture_docs.py && python -m pytest scripts/tests -q`; `bash monitoring/check.sh`; `docker build -t qeos/gateway:ci gateway && docker run --rm qeos/gateway:ci nginx -t && docker run --rm -e MONITORING_ENABLED=true qeos/gateway:ci nginx -t`. Expected:
  - no findings, and the docs check's tests pass;
  - `monitoring: all checks passed`;
  - `test is successful` twice.
- [ ] **Step 4:** Run the per-service container smoke for project-service, whose catalogue validation changed:

```bash
cd platforms/project-service && SECRET_KEY=ci-smoke-secret docker compose up --build --detach --wait --wait-timeout 180 && curl --fail --silent --show-error http://localhost:8002/health && SECRET_KEY=ci-smoke-secret docker compose down --volumes
```

Expected: `{"status":"healthy"}`.

Then run the full stack and the smoke:

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```

Expected: `all gateway checks passed`.

- [ ] **Step 5:** Check by hand at `https://localhost:8443` with the stack still up, on a project with a run that has changed files (upload one with the collector or reuse the smoke's `smoke-impact-*` runs):
  - the run page shows Likely affected tests beside Changes, side by side at desktop width and stacked at 375 px;
  - the Report ends with Test impact, and its note names the window;
  - Customise → Add widget lists Impact accuracy, it saves, and its title opens the Report at `#report-impact`;
  - keyboard focus reaches every link and button, and dark mode keeps the pills readable.

  Then `docker compose down` (never `-v`).
- [ ] **Step 6:** `git ls-files -s scripts/smoke_gateway.sh` shows `100755`; `git status --short` shows no modified file of this plan; `git log --oneline origin/master..master` lists the Phase 2 commits; `git push origin master`.

---

# Phase 3 — Play and docs

At the end of this phase a member runs the likely affected tests of a branch from QEOS, and the documentation (spec §6), ADR-029 and the roadmap record what shipped.

### Task 18: "Run likely affected" on the Cases page

**Files:**
- Create: `dashboard/src/lib/likelyAffected.ts`, `dashboard/src/components/LikelyAffectedPanel.tsx`, `dashboard/src/pages/RunLikelyAffected.test.tsx`
- Modify: `dashboard/src/pages/CasesPage.tsx`, `dashboard/src/index.css`, `DESIGN.md`, `docs/SETUP.md`

**Interfaces:**
- Consumes:
  - Tasks 9 and 13: `getRunImpact`, `scoreChange`, `ImpactSuggestion`, `SuggestedTest`.
  - Existing:
    - `listRuns(projectId, { limit, offset, branch })`;
    - `searchCases(projectId, CaseSearchBody)` (test-management `POST /cases/search`, `limit` ≤ 200, keys lowercased server-side);
    - `Case`, `Run`, `MAX_RUN_CASES = 200`;
    - `useCiTarget(projectId)` (`ref`);
    - `useCanEdit`, `ErrorBanner`, `formatCount`;
    - the Cases page's `picked: Map<number, { title: string; testKey: string | null }>` selection, its `RunControl` and `useDurationEstimate`.
- Produces:
  - In `lib/likelyAffected.ts`:
    - `RECENT_RUNS = 20`;
    - `LikelyAffected { run: Run; suggestion: ImpactSuggestion; cases: Case[]; unlinked: SuggestedTest[] }`;
    - `linkCases(projectId: number, tests: SuggestedTest[]): Promise<{ cases: Case[]; unlinked: SuggestedTest[] }>`;
    - `findLikelyAffected(projectId: number, branch: string): Promise<LikelyAffected | null>`.
  - `LikelyAffectedPanel({ projectId: number; onSelect: (cases: Case[]) => void; onClose: () => void })`.
  - The Cases page header button **Run likely affected** (editors).

- [ ] **Step 1: Invoke `ui-ux-pro-max`**

Invoke the `ui-ux-pro-max` skill for an inline, non-modal panel on a list page. It holds:
- a branch field and a primary **Find tests**;
- a status sentence;
- a list of the tests that cannot run.

Follow DESIGN.md "Run from QEOS": no modal, focus into the panel on open and back to the trigger on close, Escape closes it. Keep the page's single primary: the panel's **Find tests** is primary only while it is open.

- [ ] **Step 2: Write the failing tests**

Create `dashboard/src/pages/RunLikelyAffected.test.tsx`:

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import type { SuggestedTest } from "../api/impact";
import CasesPage from "./CasesPage";

const P = "/api/v1/projects/42";
const TARGET = { available: true, configured: true, provider: "github", repo: "acme/obt", workflow: "qeos-run.yml",
  ref: "main", token_last4: "a1b2", token_expires_at: null, updated_at: "2026-10-07T10:00:00Z", last_change: null };
const key = (name: string) => name.padEnd(64, "0");
const suggested = (name: string, kind: SuggestedTest["kind"]): SuggestedTest => ({
  test_key: key(name), suite: "s", class_name: "C", name, kind, evidence: null });
const kase = (number: number, title: string, testKey: string) => ({
  number, key: `TC-${number}`, title, description: null, steps: [], labels: [], priority: "medium", status: "ready",
  automated_test_key: testKey, automated_name: null, created_by: 1, created_at: "2026-10-06T10:00:00Z", updated_by: null,
  updated_at: null, suites: [], source_path: "tests/features/a.feature", gherkin: "Scenario: x", feature_name: "A",
});
const RUN = {
  id: 70, project_id: 42, ci_provider: "github_actions", ci_run_url: null, commit_sha: "abcdef1234567890", branch: "main",
  environment: null, agent_version: null, commit_author: null, commit_message: null, pr_number: null, base_branch: null,
  started_at: "2026-10-12T09:00:00Z", finished_at: "2026-10-12T09:04:00Z", duration_ms: 240000, total: 3, passed: 3,
  failed: 0, skipped: 0, errored: 0, change_base_ref: "origin/main", changed_files: 2, additions: 4, deletions: 1,
  changes_truncated: false, created_at: "2026-10-12T09:05:00Z",
};

function asRole(role: string) {
  server.use(http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: role })));
}

beforeEach(() => {
  asRole("member");
  server.use(
    http.get(`${P}/case-features`, () => HttpResponse.json([])),
    http.get(`${P}/case-folders`, () => HttpResponse.json([])),
    http.get(`${P}/case-labels`, () => HttpResponse.json([])),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 0, items: [] })),
    http.get(`${P}/ci-target`, () => HttpResponse.json(TARGET)),
    http.get(`${P}/run-requests`, () => HttpResponse.json({ total: 0, items: [] })),
  );
});

function mockImpact({ runs = [RUN], tests, cases, impact }: {
  runs?: object[]; tests: SuggestedTest[]; cases: object[]; impact?: () => Response;
}) {
  const bodies = { impact: [] as unknown[], search: [] as unknown[], estimate: [] as { test_keys: string[] }[] };
  server.use(
    http.get(`${P}/runs`, ({ request }) =>
      HttpResponse.json(new URL(request.url).searchParams.get("branch") === "main" ? runs : [])),
    http.get(`${P}/runs/70/impact`, () => HttpResponse.json({ run_id: 70, state: "ok",
      changed_paths: ["src/pay/api.py", "src/cart/x.py"], replayed: false, scored_at: null, suggestion: null, outcome: null })),
    http.post(`${P}/analytics/impact`, async ({ request }) => {
      bodies.impact.push(await request.json());
      return impact ? impact() : HttpResponse.json({ state: "ok", model_version: "stats-v1", history_runs: 30, needed_runs: 20,
        statistical_total: 1, tests });
    }),
    http.post(`${P}/cases/search`, async ({ request }) => {
      const body = (await request.json()) as { test_keys: string[] };
      // The Cases tiles ask with other keys; only the panel's question gets the linked cases
      if (!tests.some((t) => body.test_keys.includes(t.test_key))) return HttpResponse.json({ total: 0, items: [] });
      bodies.search.push(body);
      return HttpResponse.json({ total: cases.length, items: cases });
    }),
    http.post(`${P}/analytics/duration-estimate`, async ({ request }) => {
      bodies.estimate.push((await request.json()) as { test_keys: string[] });
      return HttpResponse.json({ estimate_ms: 360000, upper_ms: 420000, tests_with_history: 2, tests_without_history: 0,
        environment_used: 0, model: { overhead_ms: 0, factor: 1, runs: 5, fitted: true } });
    }),
  );
  return bodies;
}

function renderCases() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/projects/42/cases?group=scenario"]}>
        <Routes><Route path="/projects/:projectId/cases" element={<CasesPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function findTests() {
  await userEvent.click(await screen.findByRole("button", { name: "Run likely affected" }));
  const panel = screen.getByRole("region", { name: "Run likely affected" });
  await waitFor(() => expect(within(panel).getByLabelText("Branch")).toHaveValue("main"));
  await userEvent.click(within(panel).getByRole("button", { name: "Find tests" }));
  return panel;
}

test("selects the linked cases, lists the unlinked tests, and the duration estimate follows the selection", async () => {
  const bodies = mockImpact({
    tests: [suggested("pays", "statistical"), suggested("cart", "failing_on_branch"), suggested("orphan", "no_history")],
    cases: [kase(2, "Cart totals", key("cart")), kase(1, "Pay by card", key("pays"))],
  });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("Selected 2 linked cases for 3 likely affected tests")).toBeInTheDocument();
  expect(bodies.impact).toEqual([{ changed_paths: ["src/pay/api.py", "src/cart/x.py"], branch: "main" }]);
  expect(bodies.search[0]).toMatchObject({ test_keys: [key("pays"), key("cart"), key("orphan")], keys_mode: "include",
    limit: 200, offset: 0 });
  expect(within(panel).getByRole("heading", { name: "Not runnable from QEOS (no linked case)" })).toBeInTheDocument();
  expect(within(panel).getByRole("link", { name: "orphan" })).toHaveAttribute("href", `/projects/42/tests/${key("orphan")}`);
  expect(within(panel).getByRole("link", { name: "run #70" })).toHaveAttribute("href", "/projects/42/runs/70");
  // The ordinary selection: the bar's Run, and its estimate asked for exactly the selected cases' tests
  const bar = await screen.findByRole("region", { name: "Selected cases" });
  expect(within(bar).getByRole("button", { name: "Run selected (2)" })).toBeInTheDocument();
  await waitFor(() => expect(bodies.estimate.length).toBeGreaterThan(0));
  expect([...bodies.estimate.at(-1)!.test_keys].sort()).toEqual([key("cart"), key("pays")].sort());
  // Still a selection the person edits
  await userEvent.click(within(bar).getByRole("button", { name: "Clear selection" }));
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});

test("a branch with no run carrying change data says so and selects nothing", async () => {
  mockImpact({ runs: [{ ...RUN, changed_files: null, change_base_ref: null }], tests: [], cases: [] });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("No run on main has change data yet")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});

test("suggestions with no linked case select nothing and are all listed", async () => {
  mockImpact({ tests: [suggested("orphan", "statistical")], cases: [] });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByText("1 likely affected test, none linked to a case")).toBeInTheDocument();
  expect(within(panel).getByRole("link", { name: "orphan" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Selected cases" })).not.toBeInTheDocument();
});

test("a failure shows with Retry, and Escape closes the panel back to its button", async () => {
  let calls = 0;
  mockImpact({ tests: [suggested("pays", "statistical")], cases: [kase(1, "Pay by card", key("pays"))],
    impact: () => (++calls === 1
      ? HttpResponse.json({ detail: "Ingestion is unavailable" }, { status: 503 })
      : HttpResponse.json({ state: "ok", model_version: "stats-v1", history_runs: 30, needed_runs: 20, statistical_total: 1,
        tests: [suggested("pays", "statistical")] })) });
  renderCases();
  const panel = await findTests();
  expect(await within(panel).findByRole("alert")).toHaveTextContent("Ingestion is unavailable");
  await userEvent.click(within(panel).getByRole("button", { name: "Retry" }));
  expect(await within(panel).findByText("Selected 1 linked case for 1 likely affected test")).toBeInTheDocument();
  // Retry is gone once the request succeeds: press Escape from inside the panel
  await userEvent.click(within(panel).getByLabelText("Branch"));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("region", { name: "Run likely affected" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run likely affected" })).toHaveFocus();
});

test("viewers do not get the button", async () => {
  asRole("viewer");
  renderCases();
  expect(await screen.findByRole("heading", { level: 1, name: "Test cases" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Run likely affected" })).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd dashboard && npx vitest run src/pages/RunLikelyAffected.test.tsx`
Expected: FAIL with `Unable to find role="button" and name "Run likely affected"`. The viewer test passes already.

- [ ] **Step 4: Write the mapping**

Create `dashboard/src/lib/likelyAffected.ts`:

```ts
import { type Case, searchCases } from "../api/cases";
import { getRunImpact, type ImpactSuggestion, scoreChange, type SuggestedTest } from "../api/impact";
import { listRuns, type Run } from "../api/runs";

/** How far back the branch's latest change is looked for (plan Ruling 23). */
export const RECENT_RUNS = 20;
const PAGE = 200; // test-management's search limit
const MAX_PAGES = 5;

export interface LikelyAffected {
  /** The branch's latest run with changed files. */
  run: Run;
  suggestion: ImpactSuggestion;
  /** Cases linked to suggested tests, strongest suggestion first. */
  cases: Case[];
  /** Suggested tests no case links to: not runnable from QEOS. */
  unlinked: SuggestedTest[];
}

/** Suggested test keys to cases through `automated_test_key` (plan Ruling 24). Archived cases are left out by the search;
 *  test-management compares keys lowercased. */
export async function linkCases(projectId: number, tests: SuggestedTest[]): Promise<{ cases: Case[]; unlinked: SuggestedTest[] }> {
  if (tests.length === 0) return { cases: [], unlinked: [] };
  const keys = tests.map((t) => t.test_key.toLowerCase());
  const cases: Case[] = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const found = await searchCases(projectId, { labels: [], test_keys: keys, keys_mode: "include", limit: PAGE, offset: page * PAGE });
    cases.push(...found.items);
    if (found.items.length === 0 || cases.length >= found.total) break;
  }
  const rank = new Map(keys.map((key, index) => [key, index]));
  const position = (c: Case) => rank.get(c.automated_test_key?.toLowerCase() ?? "") ?? keys.length;
  cases.sort((a, b) => position(a) - position(b) || a.number - b.number);
  const linked = new Set(cases.map((c) => c.automated_test_key?.toLowerCase()));
  return { cases, unlinked: tests.filter((t) => !linked.has(t.test_key.toLowerCase())) };
}

/** The branch's latest change scored now (spec 2026-10-12 §2.2): the newest of its last 20 runs with changed files gives
 *  the paths, POST /analytics/impact scores them, and the cases' automated_test_key maps the tests. Null when no recent
 *  run of the branch carries change data. */
export async function findLikelyAffected(projectId: number, branch: string): Promise<LikelyAffected | null> {
  const runs = await listRuns(projectId, { limit: RECENT_RUNS, offset: 0, branch });
  const run = runs.find((r) => (r.changed_files ?? 0) > 0);
  if (run === undefined) return null;
  const { changed_paths: paths } = await getRunImpact(projectId, run.id);
  if (paths.length === 0) return null;
  const suggestion = await scoreChange(projectId, paths, branch);
  return { run, suggestion, ...(await linkCases(projectId, suggestion.tests)) };
}
```

- [ ] **Step 5: Write the panel**

Create `dashboard/src/components/LikelyAffectedPanel.tsx`:

```tsx
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { X } from "lucide-react";
import { formatCount } from "../api/analytics";
import type { Case } from "../api/cases";
import { MAX_RUN_CASES } from "../api/runRequests";
import { type LikelyAffected, findLikelyAffected } from "../lib/likelyAffected";
import { useCiTarget } from "../lib/useRunGate";
import ErrorBanner from "./ErrorBanner";

interface Props {
  projectId: number;
  /** Replaces the Cases selection with these cases: the selection bar's Run, its dialog and the estimate follow. */
  onSelect: (cases: Case[]) => void;
  onClose: () => void;
}

const tests = (n: number) => `${formatCount(n)} likely affected ${n === 1 ? "test" : "tests"}`;

function summary(found: LikelyAffected, branch: string): string {
  const total = found.suggestion.tests.length;
  if (total === 0) return `No tests are likely affected by the latest change on ${branch}`;
  const linked = found.cases.length;
  if (linked === 0) return `${tests(total)}, none linked to a case`;
  const selected = Math.min(linked, MAX_RUN_CASES);
  const capped = linked > MAX_RUN_CASES ? ` (the first ${MAX_RUN_CASES}: at most ${MAX_RUN_CASES} cases per run)` : "";
  return `Selected ${formatCount(selected)} linked ${selected === 1 ? "case" : "cases"}${capped} for ${tests(total)}`;
}

/** Run likely affected (spec 2026-10-12 §2.2, plan Ruling 22): scores a branch's latest change and selects the linked
 *  cases; the person reviews the selection and runs it from the selection bar. Inline, never modal. */
export default function LikelyAffectedPanel({ projectId, onSelect, onClose }: Props) {
  const ids = useId();
  const target = useCiTarget(projectId);
  const [branch, setBranch] = useState("");
  const edited = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const ref = target.data?.ref;
  // The CI target's branch until the person types their own
  useEffect(() => {
    if (!edited.current && ref) setBranch(ref);
  }, [ref]);
  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  const find = useMutation({
    mutationFn: (name: string) => findLikelyAffected(projectId, name),
    onSuccess: (found) => {
      if (found !== null && found.cases.length > 0) onSelect(found.cases.slice(0, MAX_RUN_CASES));
    },
  });
  const asked = find.variables ?? "";
  const found = find.data;
  return (
    <section className="card likely-affected" aria-labelledby={`${ids}-title`}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <div className="likely-affected-head">
        <h2 id={`${ids}-title`}>Run likely affected</h2>
        <button type="button" className="ghost" aria-label="Close Run likely affected" onClick={onClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <p className="muted">Selects the cases linked to the tests a branch's latest change is likely to affect. Review the selection, then run it.</p>
      <form className="likely-affected-form" onSubmit={(e) => {
        e.preventDefault();
        const name = branch.trim();
        if (name) find.mutate(name);
      }}>
        <label>
          Branch
          <input ref={inputRef} value={branch} maxLength={255} required
            onChange={(e) => { edited.current = true; setBranch(e.target.value); }} />
        </label>
        <button type="submit" className="primary" disabled={find.isPending || branch.trim() === ""}>
          {find.isPending ? "Finding…" : "Find tests"}
        </button>
      </form>
      <p role="status">
        {find.isSuccess && (found === null ? `No run on ${asked} has change data yet` : summary(found, asked))}
      </p>
      {find.error != null && <ErrorBanner error={find.error} onRetry={() => find.mutate(asked || branch.trim())} />}
      {found && (
        <>
          <p className="muted">
            From the latest change on {asked}: <Link to={`/projects/${projectId}/runs/${found.run.id}`}>{`run #${found.run.id}`}</Link>
            {`, ${formatCount(found.run.changed_files ?? 0)} changed files.`}
            {found.suggestion.state === "not_enough_history"
              && ` Not enough history yet for statistics: ${formatCount(found.suggestion.history_runs)} runs with changed files, needs ${formatCount(found.suggestion.needed_runs)}.`}
          </p>
          {found.unlinked.length > 0 && (
            <>
              <h3>Not runnable from QEOS (no linked case)</h3>
              <ul className="impact-list">
                {found.unlinked.map((t) => (
                  <li key={t.test_key}><Link to={`/projects/${projectId}/tests/${encodeURIComponent(t.test_key)}`}>{t.name}</Link></li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
```

Append to `dashboard/src/index.css`:

```bash
cat >> dashboard/src/index.css <<'EOF'
/* Run likely affected: an inline panel on the Cases page, never a modal */
.likely-affected-head { display: flex; justify-content: space-between; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); }
.likely-affected-head h2 { margin: 0; }
.likely-affected-form { display: flex; flex-wrap: wrap; align-items: end; gap: var(--space-3); margin-bottom: var(--space-3); }
.likely-affected-form label { min-width: min(100%, 280px); }
EOF
```

- [ ] **Step 6: Put it on the Cases page**

In `dashboard/src/pages/CasesPage.tsx`, with the Edit tool, make these replacements:

1. Replace `import { Plus, Upload } from "lucide-react";` with `import { Crosshair, Plus, Upload } from "lucide-react";`.
2. Replace `import FeatureList from "../components/FeatureList";` with:

   ```tsx
   import FeatureList from "../components/FeatureList";
   import LikelyAffectedPanel from "../components/LikelyAffectedPanel";
   ```

3. Replace:

   ```tsx
     const [picked, setPicked] = useState<Map<number, Picked>>(new Map());
   ```

   with:

   ```tsx
     const [picked, setPicked] = useState<Map<number, Picked>>(new Map());
     const [impactOpen, setImpactOpen] = useState(false);
     const impactButtonRef = useRef<HTMLButtonElement>(null);
     function closeImpact() {
       setImpactOpen(false);
       impactButtonRef.current?.focus();
     }
   ```

4. Replace:

   ```tsx
           actions={canEdit ? (
             <>
               <Link className="button" to="import">
   ```

   with:

   ```tsx
           actions={canEdit ? (
             <>
               <button ref={impactButtonRef} type="button" aria-expanded={impactOpen} onClick={() => setImpactOpen(true)}>
                 <Crosshair size={16} aria-hidden="true" /> Run likely affected
               </button>
               <Link className="button" to="import">
   ```

5. Replace:

   ```tsx
         <CasesKpis projectId={id} />
         <RunPanel projectId={id} />
   ```

   with:

   ```tsx
         <CasesKpis projectId={id} />
         <RunPanel projectId={id} />
         {canEdit && impactOpen && (
           <LikelyAffectedPanel projectId={id} onClose={closeImpact}
             onSelect={(cases) => setPicked(new Map(cases.map((c) => [c.number, { title: c.title, testKey: c.automated_test_key }])))} />
         )}
   ```

- [ ] **Step 7: Run the tests and the checks**

Run: `cd dashboard && npx vitest run src/pages/RunLikelyAffected.test.tsx src/pages/RunFromQeos.test.tsx src/pages/DurationEstimate.test.tsx src/pages/CasesFilters.test.tsx && npm run lint && npm run typecheck`
Expected: PASS. The Run from QEOS, estimate and filter tests are unchanged and still green.

Check by hand in the dev server at 1440 px and 375 px:
- the panel sits under the Run panel;
- focus lands in Branch;
- Escape returns focus to the button;
- the status sentence is read once by a screen reader.

- [ ] **Step 8: Document**

In `DESIGN.md`, with the Edit tool, replace:

```
- **Run panel:** a card with `role="status"`.
```

with:

```
- **Run likely affected** (Cases page header, editors; spec 2026-10-12 §2.2): a secondary button with the Crosshair icon. It opens an inline card, never a modal:
  - **Form:** a Branch field (focused; defaults to the CI target's branch) and a primary **Find tests**.
  - **Status sentence** (`role="status"`): "Selected 2 linked cases for 3 likely affected tests", "1 likely affected test, none linked to a case", or "No run on main has change data yet".
  - **Source:** a muted line with the run it came from.
  - **Unlinked tests** under "Not runnable from QEOS (no linked case)", each linked to its history.
  - **Selection:** the linked cases replace the Cases selection, so the selection bar, its Run dialog and the duration estimate follow. The person can still change it.
  - **Closing:** Escape or the close button, with focus back on the header button. An error is an Error Banner with Retry.
- **Run panel:** a card with `role="status"`.
```

In `docs/SETUP.md`, with the Edit tool, replace:

```
**Prerequisites**
```

(it occurs once, in 4.3) with:

```
**Run likely affected.** On **Test cases**, members and above can choose **Run likely affected**:

1. Enter a branch; it defaults to the CI target's branch. Choose **Find tests**.
2. QEOS takes the branch's latest run with changed files, scores that change (see [Test impact](#test-impact)) and selects the cases linked to the suggested tests.
3. Review the selection; the estimate follows it. Then **Run selected** as usual.

Suggested tests that no case links to are listed as *not runnable from QEOS (no linked case)*. Link them by setting the case's automated test.

**Prerequisites**
```


- [ ] **Step 9: Commit**

```bash
git add dashboard/src/lib/likelyAffected.ts dashboard/src/components/LikelyAffectedPanel.tsx dashboard/src/pages/RunLikelyAffected.test.tsx dashboard/src/pages/CasesPage.tsx dashboard/src/index.css DESIGN.md docs/SETUP.md
git commit -m "feat(dashboard): Run likely affected selects the cases linked to a branch's likely affected tests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- dashboard/src/lib/likelyAffected.ts dashboard/src/components/LikelyAffectedPanel.tsx dashboard/src/pages/RunLikelyAffected.test.tsx dashboard/src/pages/CasesPage.tsx dashboard/src/index.css DESIGN.md docs/SETUP.md
```

---

### Task 19: Documentation, ADR-029 and the roadmap

**Files:**
- Create: `docs/architecture/adr/ADR-029-test-impact-analysis.md`
- Modify: `docs/architecture/adr/INDEX.md`, `PRODUCT.md`, `README.md`, `docs/SETUP.md`, `TECHNICAL_SPECIFICATION.md`, `TODO.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md`

**Interfaces:**
- Consumes: everything that shipped in Tasks 1–18, with the ingestion README sections (Tasks 5–11), DESIGN (Tasks 14–16, 18) and the catalogue counts (Task 16) already done.
- Produces the spec §6 documents that remain:
  - PRODUCT (impact rules), README features, SETUP "Test impact", TECHNICAL_SPECIFICATION (dashboard);
  - ADR-029 and its INDEX row;
  - TODO (item 4 done, and the follow-ups), IMPLEMENTATION_PLAN, and the blueprint banner.

- [ ] **Step 1: Write ADR-029**

Create `docs/architecture/adr/ADR-029-test-impact-analysis.md`:

```markdown
# ADR-029: Test impact analysis from co-failure statistics, with every suggestion stored and evaluated

Status: Accepted (2026-10-12) · Spec: `docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md` · Plan: `docs/superpowers/plans/2026-10-12-test-impact-analysis.md`

## Context
TODO.md "Execution intelligence and operations", item 4: suggest which tests to run for a change, from collected
commits' changed files and later failures, with no coverage instrumentation. QEOS already stores both:
- every upload's changed files (`run_changed_files`, with the base ref and the collector's truncation flag);
- every test's results.

Teams want the likely affected tests first, and a suggestion nobody can check would be guesswork, so how often the
suggestions were right must be measured honestly. Qdrant and the QIP services stay TARGET behind "Phase 6 AI engine
work begins" (blueprint banner).

## Decision
- **Statistics, not a model, on PostgreSQL in ingestion-service.**
  - *Newly failed:* a test's outcome fails (failed or errored; last attempt) after it passed on the same branch
    within 90 days, or on the base branch for a new branch. Flaky and muted tests are excluded.
  - *Path units:* each changed path and its nearest 3 parent folders. Lock files and generated or vendored folders
    are ignored; a change of more than 300 files counts at folder level only; truncated change lists are left out.
  - *Rollup:* the `impact-rollup` job (every 24 hours, heartbeat `impact_rollup`, JobStale at two days) rebuilds, per
    project, `impact_pairs` (unit × test with new failures) and `impact_test_base` (every test's base rate, plus
    its name, file and flaky flag) over 90 days (migration 018).
  - *Scoring:* a test is suggested when `changed_runs ≥ 3`, `new_failures ≥ 2` and `lift ≥ 2`. Suggestions are
    ordered by confidence then lift, at most 50, and labelled tests come outside that cap: test file changed,
    failing on this branch, no history yet. Below 20 runs with changed files there are no statistics. The model
    version is `stats-v1`, and the thresholds sit in one constants module.
- **The evaluation is stored at upload.** A run's suggestion is scored before its run row or any result exists, and
  stored in `run_impact` in the upload's own transaction. Right after the response, the run's new failures are
  compared with it (`caught`, `missed`). Accuracy = caught ÷ (caught + missed) over runs with a stored suggestion.
  `--backfill-days` replays history with statistics from earlier days only, marked `replayed` and reported apart.
  Neither scoring nor evaluation can fail an upload.
- **Where people see it:**
  - the run page's "Likely affected tests" card beside Changes;
  - the Report's "Test impact" section;
  - the Overview widget `impact_accuracy` (in the shared catalogue, so project-service validates it unchanged);
  - "Run likely affected" on the Cases page. Play has no branch dialog, so this scores a branch's latest change,
    selects the linked cases (`automated_test_key`), and lists the tests no case links to.
- **Collector parts:** a collector upload split into parts is one run per part, so each part has its own suggestion
  and outcome.

## Alternatives rejected
- **Coverage instrumentation:** a per-language agent in every customer's CI, and the spec rules it out.
- **A learned model now:** there are no outcomes yet to train or judge it on. It comes after a few weeks of stored
  outcomes, on the same features with no new infrastructure, and must beat `stats-v1` on the same accuracy figure.
- **Code embeddings and semantic similarity:** they need Qdrant, a TARGET technology behind the Phase 6 trigger.
- **Scoring only when someone looks:** a suggestion computed after the fact can see later data, so its accuracy
  would flatter it. Storing it at upload, before the results, keeps the figure honest.
- **Live statistics without a rollup:** the window over about 2 million results costs seconds, while the budget is
  200 ms per scoring.
- **Skipping tests in CI:** considered only once the accuracy figure supports it. Release B runs the suggested tests
  first, never instead.

## Consequences
- **Upload cost:** each upload with changed files pays one scoring (budget 200 ms) and an evaluation after its
  response.
- **Rollup cost:** the rollup runs under 60 s per project on the 2M-result benchmark (figures in the ingestion
  README).
- **Retention:** `run_impact` goes with its run (retention and legal hold apply). The statistics are rebuilt from the
  runs that remain.
- **Known limits:**
  - runs record no repository yet, so path units carry no repository prefix;
  - a rename starts a new history;
  - replay uses the flaky and muted tests known at replay time;
  - a part after the first of a split upload may list the previous part's failures as *failing on this branch*.
- **Follow-ups in TODO.md:**
  - release B (the collector runs the suggested tests first);
  - the learned model;
  - Phase 6 embeddings;
  - accuracy in the weekly summary;
  - the collector sending the repository.
```

In `docs/architecture/adr/INDEX.md`, with the Edit tool, replace the ADR-028 row:

```
| [ADR-028](ADR-028-customisable-overview.md) | The customisable Overview: layouts in project-service (project default and personal, optimistic versions), one widget catalogue file shared by validation and the dashboard registry, refresh keys declared per widget, "my" widgets matched exactly by commit author name |
```

with itself followed by:

```
| [ADR-029](ADR-029-test-impact-analysis.md) | Test impact analysis: co-failure statistics on PostgreSQL rebuilt by the impact-rollup job, every suggestion stored at upload before its results and evaluated against its new failures, accuracy shown live and replayed apart; a learned model and embeddings come later |
```

- [ ] **Step 2: Product rules and the README**

In `PRODUCT.md`, with the Edit tool, replace:

```
## Accessibility & Inclusion
```

with:

```
## Test Impact Rules

- QEOS suggests the tests a change is likely to affect from history only: which tests newly failed after earlier
  changes to the same files or folders. No coverage instrumentation, no AI (ADR-029).
- Every suggestion explains itself: the file or folder, in how many of the runs that changed it the test newly
  failed, and how often it fails otherwise. Tests whose file changed, that already fail on the branch, or that have
  no history yet are always included, with that label instead of statistics.
- Honest by construction (Principle 1): the suggestion stored with a run is made before its results are read, and
  its outcome is recorded (which new failures it caught and which it missed). The accuracy figure counts only
  those. Replayed history is shown apart from live suggestions.
- Below 20 runs with changed files, QEOS says "Not enough history yet" rather than guessing.
- Suggestions decide what to run **first**, never what to skip. Skipping tests is considered only when the accuracy
  figure supports it.
- **Run likely affected** selects the linked cases. A suggested test with no linked case is listed as not runnable
  from QEOS, never silently dropped.

## Accessibility & Inclusion
```

In `README.md`, with the Edit tool, replace:

```
- **Failure causes:** new, recurring and resolved failures, grouped by cause.
```

with:

```
- **Failure causes:** new, recurring and resolved failures, grouped by cause.
- **Test impact:** for each change, the tests it is likely to affect, from which tests newly failed after earlier changes to the same files (no coverage instrumentation). Each suggestion shows its evidence. QEOS records what every suggestion caught and missed, and reports that accuracy in the Report and on the Overview. **Run likely affected** selects their cases for a run from QEOS.
```

- [ ] **Step 3: The setup guide**

In `docs/SETUP.md`, with the Edit tool, replace:

```
#### Customise the Overview
```

with:

```
#### Test impact

Nothing to configure. Upload results with changed files: the collector sends them by default, and `--no-changes`
turns that off. The `impact-rollup` job (started by compose) rebuilds the statistics every 24 hours.

- **Run page:** **Likely affected tests** beside **Changes**. Suggested tests come strongest first, each with its
  evidence ("newly failed in 4 of 6 runs that changed `src/payment/` (normally 3%)"). Tests always included carry
  a label instead: *test file changed*, *failing on this branch* or *no history yet*. Once the run's results are
  compared, the outcome says which new failures were suggested and which were missed.
- **Not enough history yet:** until the project has 20 runs with changed files in 90 days, only the labelled tests
  are listed.
- **Report → Test impact** and the Overview widget **Impact accuracy:** caught ÷ (caught + missed) new failures in
  runs that had a stored suggestion, over 7, 14 or 30 days, with the misses.
- **Run likely affected** on **Test cases:** see [4.3](#43-run-from-qeos-play-and-stop).
- **From history:** to fill the figure from past runs, run once
  `docker compose run --rm impact-rollup python -m src.ingestion.jobs.impact_rollup --backfill-days 30`. Those
  runs are scored with statistics from earlier days only, marked *replayed* and counted apart.
- **What counts:**
  - a test newly fails when it fails after passing on the same branch (or on the base branch for a new branch);
    flaky and muted tests never do;
  - lock files and `dist/`, `build/`, `vendor/`, `node_modules/` are ignored;
  - a change of more than 300 files counts by folder;
  - a change list the collector truncated (over 1,000 files) is still scored but not learned from.
- **Monitoring:** the job's heartbeat is `impact_rollup`, and the JobStale alert fires after two days without a pass.

#### Customise the Overview
```

- [ ] **Step 4: The technical specification**

In `TECHNICAL_SPECIFICATION.md`, with the Edit tool, replace:

```
(pick-two pass-rate comparison), runs (list + detail incl. changed files and
```

with:

```
(pick-two pass-rate comparison), runs (list + detail incl. changed files with
the likely affected tests and their outcome, ADR-029, and
```

then replace:

```
requested runs, report, test cases (Scenario and Feature views, editor,
Gherkin import, Feature page), suites, project settings (API keys, CI
```

with:

```
requested runs, report (incl. Test impact accuracy), test cases (Scenario and
Feature views, editor, Gherkin import, Feature page, Run likely affected),
suites, project settings (API keys, CI
```

- [ ] **Step 5: TODO, the implementation plan and the blueprint banner**

In `TODO.md`, with the Edit tool, replace:

```
4. [ ] Test impact analysis: from collected commits' changed files and later failures, suggest which tests to run for a change (history-based; no coverage instrumentation)
```

with:

```
4. [x] Test impact analysis (done 2026-10-12, ADR-029, spec `docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md`): co-failure statistics on PostgreSQL rebuilt by the `impact-rollup` job (ingestion migration 018, heartbeat `impact_rollup`); each upload with changed files stores its suggestion before its results and its outcome after; `GET /runs/{id}/impact`, `POST /analytics/impact`, `GET /analytics/impact-accuracy`; the run page card, the Report's Test impact section, the Overview widget Impact accuracy, and Run likely affected on Test cases; `--backfill-days` replays history
   - [ ] Release B: a collector command that runs the suggested tests first (never instead of the full suite), from `POST /analytics/impact`
   - [ ] A learned model on the same features once a few weeks of outcomes exist; it must beat `stats-v1` on the same accuracy figure, with no new infrastructure
   - [ ] Code embeddings and semantic similarity (Qdrant) when "Phase 6 AI engine work begins"
   - [ ] The accuracy figure in the weekly summary
   - [ ] The collector sends the repository, so path units carry it (spec §3.1; runs record none today)
```

then replace:

```
Updated 2026-10-11. Phases 1–3 are delivered, test management (Phase 4) is in use, and the Report,
```

with:

```
Updated 2026-10-12. Phases 1–3 are delivered, test management (Phase 4) is in use, and the Report,
```

then replace:

```
Overview (item 3, ADR-028). What runs today: README.md and
```

with:

```
Overview (item 3, ADR-028) and test impact analysis (item 4, ADR-029). What runs today: README.md and
```

In `IMPLEMENTATION_PLAN.md`, with the Edit tool, replace:

```
   project default and personal layouts), then test impact analysis.
```

with:

```
   project default and personal layouts), then test impact analysis (done 2026-10-12, ADR-029:
   co-failure statistics, suggestions stored at upload with their outcome, accuracy in the Report and on
   the Overview, Run likely affected). Next from that line: release B, a collector command that runs the
   suggested tests first.
```

In `ARCHITECTURE_BLUEPRINT_V1_0.md`, with the Edit tool, replace:

```
> **IMPLEMENTATION STATUS — read this first (updated 2026-10-11).**
```

with:

```
> **IMPLEMENTATION STATUS — read this first (updated 2026-10-12).**
```

and replace:

```
duration; ADR-026) on PostgreSQL
```

with:

```
duration; ADR-026) and test impact analysis (likely affected tests from co-failure statistics, each suggestion stored at upload and its accuracy measured; ADR-029) on PostgreSQL
```

- [ ] **Step 6: Check the documents**

```bash
python scripts/check_architecture_docs.py && python -m pytest scripts/tests -q
grep -rn "ADR-029" docs/architecture/adr/INDEX.md TODO.md README.md PRODUCT.md ARCHITECTURE_BLUEPRINT_V1_0.md TECHNICAL_SPECIFICATION.md IMPLEMENTATION_PLAN.md | wc -l
python - <<'EOF'
import pathlib
for name in ["docs/architecture/adr/ADR-029-test-impact-analysis.md", "docs/architecture/adr/INDEX.md", "PRODUCT.md",
             "README.md", "docs/SETUP.md", "TECHNICAL_SPECIFICATION.md", "TODO.md", "IMPLEMENTATION_PLAN.md",
             "ARCHITECTURE_BLUEPRINT_V1_0.md"]:
    data = pathlib.Path(name).read_bytes()
    data.decode("utf-8")
    assert b"\r\n" not in data, f"{name} has CRLF line endings"
print("utf-8, LF")
EOF
```

Expected:
- no findings from the docs check, and its tests pass;
- at least `7` from the grep count;
- `utf-8, LF`.

The SETUP links `#test-impact` (Task 18) and `#43-run-from-qeos-play-and-stop` now both resolve: open the file in a Markdown preview and follow them.

- [ ] **Step 7: Commit**

```bash
git add docs/architecture/adr/ADR-029-test-impact-analysis.md docs/architecture/adr/INDEX.md PRODUCT.md README.md docs/SETUP.md TECHNICAL_SPECIFICATION.md TODO.md IMPLEMENTATION_PLAN.md ARCHITECTURE_BLUEPRINT_V1_0.md
git commit -m "docs: test impact analysis (ADR-029, product rules, setup, TODO item 4 done, blueprint banner)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docs/architecture/adr/ADR-029-test-impact-analysis.md docs/architecture/adr/INDEX.md PRODUCT.md README.md docs/SETUP.md TECHNICAL_SPECIFICATION.md TODO.md IMPLEMENTATION_PLAN.md ARCHITECTURE_BLUEPRINT_V1_0.md
```

---

### Task 20: Phase 3 gate

**Files:** none new (fixes only, in the files of Tasks 18–19).

**Interfaces:** Consumes everything; produces a pushed `master`.

- [ ] **Step 1:** Every Python suite serially and the collector (Task 12 Step 1). Expected: all green.
- [ ] **Step 2:** `cd dashboard && npm run lint && npm run typecheck && npx vitest run --maxWorkers=4 && npm run build && node --test ../templates/github/qeos-run.test.mjs`. Expected: all green.
- [ ] **Step 3:** `python scripts/check_architecture_docs.py && python -m pytest scripts/tests -q`; `bash monitoring/check.sh`; `docker build -t qeos/gateway:ci gateway && docker run --rm qeos/gateway:ci nginx -t && docker run --rm -e MONITORING_ENABLED=true qeos/gateway:ci nginx -t`. Expected:
  - no findings, and the docs check's tests pass;
  - `monitoring: all checks passed`;
  - `test is successful` twice.
- [ ] **Step 4:** The full stack and the smoke:

```bash
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret docker compose up -d --build --wait --wait-timeout 300 gateway
SECRET_KEY=ci-gateway-secret INTERNAL_API_PASSWORD=ci-internal-secret bash scripts/smoke_gateway.sh
```

Expected: `all gateway checks passed`.

- [ ] **Step 5:** Check by hand at `https://localhost:8443`, with a configured CI target and cases linked to the tests of the smoke's `smoke-impact-*` branch, or to tests of a branch of your own:
  - **Test cases → Run likely affected:** type the branch, then **Find tests**;
  - the linked cases are selected and the selection bar shows its estimate;
  - unlinked tests are listed under *not runnable from QEOS (no linked case)*;
  - Escape closes the panel back to its button.

  Then `docker compose down` (never `-v`).
- [ ] **Step 6:** `git ls-files -s scripts/smoke_gateway.sh` shows `100755`; `git status --short` shows no modified file of this plan; `git log --oneline origin/master..master` lists the Phase 3 commits; `git push origin master`.

---

## Self-review

**Spec coverage.**
- **§1 scope.** This release is A plus C:
  - A, the analysis and its views: Tasks 1–16;
  - C, Run likely affected: Task 18.
  - B, a learned model and embeddings are not built, and are recorded in TODO (Task 19) and ADR-029.
- **§2.1 card:** evidence text, labels, outcome sentences, the four states and *replayed* → Task 14 (Rulings 17, 26).
- **§2.2 Run likely affected** → Task 18. The placement (no branch Play dialog exists, Ruling 22), the branch's latest change (Ruling 23), the key → case mapping (Ruling 24), the "not runnable" list, and the duration estimate following the selection are all tested in `RunLikelyAffected.test.tsx`.
- **§2.3 accuracy:**
  - the endpoint → Task 9;
  - the Report section → Task 15 (Ruling 21);
  - the widget in the catalogue, validation and registry → Task 16;
  - replayed and live apart → Tasks 9, 15, 16.
- **§3.1 definitions:**
  - newly failed → Task 4 (Rulings 7, 8; flaky Ruling 6);
  - path units, ignored paths, >300 files, repository prefix → Task 2 (Rulings 3, 4, 5);
  - truncated runs → Tasks 4 and 5 (Ruling 16).
- **§3.2 rollup:**
  - tables → Task 1 (Rulings 9, 27);
  - the job and its same-day idempotence → Task 5 (Ruling 14);
  - compose, heartbeat, alert and promtool tests → Task 6.
- **§3.3 scoring** (thresholds, order, cap, labels, not enough history, `stats-v1`) → Task 3 (Rulings 10, 11, 12).
- **§3.4 stored suggestion and outcome:**
  - Task 7 (Rulings 1, 2);
  - the proof that the suggestion cannot see its own results is `test_the_suggestion_never_sees_its_own_run_or_results`.
- **§3.5 endpoints, roles, limits, 404s** → Task 9 (Rulings 17–19); routing → Task 10 (no gateway change).
- **§3.6 replay** → Task 8 (Ruling 13).
- **§3.7:**
  - cascade → Task 1 (`test_a_runs_stored_suggestion_goes_with_the_run`, Ruling 15);
  - masked data: the rollup reads only stored results and paths, which ingestion masks at upload;
  - budgets → Task 11.
- **§4 dashboard:** one query and hook (Task 13, Ruling 20), `staleKeys` (Task 16), DESIGN rules and `ui-ux-pro-max` (Tasks 13–16, 18).
- **§5 testing:** ingestion items → Tasks 1–9 and 11; dashboard items → Tasks 13–16 and 18; smoke → Task 10.
- **§6 docs:**
  - the ingestion README → Tasks 5–11;
  - monitoring and job names → Task 6;
  - DESIGN → Tasks 14–16, 18;
  - SETUP → Tasks 6, 14–16, 18, 19;
  - PRODUCT, README, TECHNICAL_SPECIFICATION, TODO, ADR-029 with INDEX, and the banner → Tasks 6, 9, 16, 19.
- **§7 three phases with gates and pushes** → Tasks 12, 17, 20.
- **§8:** nothing TARGET is introduced.

**Placeholder scan.**
- No "TBD", "similar to Task N" or undefined helper. Every code step shows its code, and every doc step shows the exact old and new text.
- The one fill-in is deliberate: Task 11 Step 3's benchmark figures, which only the measurement can give. A grep proves they were filled before the commit.

**Type consistency.**
- **Backend:**
  - `ImpactTest`, `PairStat`, `BaseStat`, `suggest(...)` and `evidence(...)` (Task 3) are what Tasks 4, 5, 7 and 8 build and pass.
  - `ChangeRun` and `change_runs(..., include_truncated=)` (Task 4) are used by Tasks 5 and 8.
  - `newly_failed_bulk(db, runs, excluded)` (Task 4) is used by `build_statistics` (Task 5).
  - `newly_failed_in_run(db, run, excluded)` (Task 4) is used by Tasks 7 and 8.
  - `build_statistics(db, project_id, start, end, flaky, muted)`, `replace_statistics` and `live_excluded` (Task 5) are used by Tasks 7, 8 and 11.
  - `Scored`, `stored_suggestion(run_id, scored, *, replayed)`, `record_outcome(row, newly, now)`, `failing_on_branch`, `history_runs` and `score_change(..., *, now)` (Task 7) are used by Tasks 8, 9 and 11.
  - `run_backfill(db, days, now=)` (Task 8) is used by the Task 8 tests.
  - The suggestion dict keys (`state`, `history_runs`, `needed_runs`, `statistical_total`, `tests[].kind/evidence`) match `SuggestionOut` (Task 9) and the dashboard's `ImpactSuggestion` (Task 13).
- **Dashboard:**
  - `RunImpact`, `ImpactAccuracy`, `AccuracyPart`, `AccuracyDays` and `SuggestedTest` (Task 13) are used by Tasks 14–16 and 18.
  - `impactAccuracyQuery`'s key `["report", id, "impact-accuracy", days]` matches `impactAccuracyStaleKeys` and the widget test.
  - `ReportSection<T>` (Task 15) is used by `ImpactSection` only; the other sections keep their `Report` default.
  - `findLikelyAffected` and `linkCases` (Task 18) use `getRunImpact` and `scoreChange` from Task 13.

**Review Focus:**
1. → Task 7 `test_a_failing_scoring_never_fails_the_upload`.
2. → Task 7 `test_a_late_upload_reads_the_branch_as_it_was_before_the_run`.
3. → Task 4 `test_the_last_attempt_is_the_outcome`.
4. → Task 9 `test_a_change_of_only_ignored_files_answers_with_labels_only`.
5. → Task 7 `test_a_replayed_upload_is_not_scored_again`.

All five have their test in the owning task.
