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
- **Co-failure statistics, not a model, on PostgreSQL in ingestion-service.**
  - *Scoring:* a change is split into path units (each changed file plus its nearest 3 parent folders; lock files
    and generated or vendored folders are ignored, a change of more than 300 files counts at folder level only,
    truncated change lists are left out of the statistics). The units are scored for tests that *newly failed*
    after earlier changes to the same units. A newly failed test fails (failed or errored, last attempt) after it
    passed on the same branch within 90 days, or on the base branch for a new branch. Flaky and muted tests are
    excluded.
  - *What is stored:* `impact_pairs` holds only the pairs that pass every threshold: `changed_runs >= 3`,
    `new_failures >= 2` and lift `>= 2`, where a base rate of 0 passes. It is keyed by
    `(project_id, unit_hash, test_key)` with `unit_hash = md5(path_unit)` (migration 018). `impact_test_base`
    holds every test's base rate, names, file and flaky flag.
  - *Rollup:* the `impact-rollup` job (every 24 hours, heartbeat `impact_rollup`, JobStale after 2 days)
    rebuilds both tables per project over 90 days inside PostgreSQL with one `INSERT ... SELECT` each.
  - *Suggestion:* ordered by confidence then lift, at most 50; labelled tests come outside that cap: test file
    changed, failing on this branch, no history yet. Below 20 runs with changed files there are no statistics.
    The model version is `stats-v1`, and the thresholds sit in one constants module.
- **The evaluation is stored before the results.** At upload the change is scored before the run row or any of its
  results exist, within one total 2 s budget, and the suggestion is stored in `run_impact` in the upload's own
  transaction. After the response, the run's new failures are compared with it (`caught`, `missed`); a nightly
  catch-up writes the outcomes still missing, capped at 500 per pass. Neither step can fail an upload.
- **Why that is honest.** A suggestion made after the fact can see later data, so its accuracy would flatter it.
  A suggestion stored before its results exist cannot. The figure is the catch rate, caught ÷ (caught + missed)
  over runs with a stored suggestion, and it always has the average suggestion size beside it, because suggesting
  every test catches everything. `--backfill-days` replays history with statistics from earlier days only, under
  its own lock, and marks those suggestions "replayed"; live and replayed are shown separately.
- **Endpoints** (any role that reads runs): `GET /runs/{id}/impact`, `POST /analytics/impact` and
  `GET /analytics/impact-accuracy`. They have input limits (1 to 5,000 paths of up to 1,000 characters) and answer
  503 `impact_timeout` when the 2 s budget runs out.
- **Where people see it:**
  - the run page's "Likely affected tests" card beside Changes (it polls for a pending outcome; a run without
    change data gets a compact one-line card);
  - the Report's "Test impact" section;
  - the Overview widget `impact_accuracy`, in the shared catalogue (now 15 widgets), so project-service
    validates it unchanged;
  - "Run likely affected" on the Test cases page: it scores a branch's newest change, selects the linked cases
    (`automated_test_key`) and lists the tests no case links to.

## Why ML and embeddings come later
- **A learned model** has nothing to train or be judged on until outcomes accumulate. Every stored outcome is a
  labelled example, so after a few weeks the same features can feed a model with no new infrastructure. It
  must beat `stats-v1` on the same catch rate, with the same average size beside it, before it replaces it.
- **Code embeddings and semantic similarity** need Qdrant, a TARGET technology. The blueprint's adoption trigger is
  "Phase 6 AI engine work begins"; until it fires, nothing here adds a vector store.
- **Release B**, running the suggested tests first in CI, is built for collector 0.7.0 (section below). Skipping
  tests stays opt-in (`--suggested-only`), and such runs never feed the accuracy figure.

## Deviations from the first spec (spec §9)
- Ingestion has no upload parts: the collector sends each part as its own run, so each part has its own
  suggestion and outcome. Scoring happens in the upload's transaction, the outcome after the response.
- Runs record no repository, so path units carry no repository prefix yet (TODO.md).
- "Failed" includes `errored`, and a test's outcome is its last attempt.
- Only `run_impact` cascades from `test_runs`; the statistics are rebuilt nightly from the runs that remain.
- `impact_test_base` also stores names, file and flaky flag, so live scoring never scans results; "no history" means
  fewer than 3 runs.
- There is no Play dialog per branch: Run likely affected is a button on the Test cases page that scores the
  newest change with changed files among the branch's last 20 runs.
- The Report section uses the Report's period when it is the last 7, 14 or 30 days ending today, else 30.
- The accuracy figure also shows the average suggestion size.
- `impact_pairs` stores only pairs that pass every threshold, lift included, computed at rollup time. A test is
  suggested through the strongest passing unit of the change, and a threshold change applies at the next rollup.
- Replay takes its own lock and may run long on a large project; it is a one-off.

## Performance design
The first design missed its budgets: per-row inserts and whole-project loads. The shipped one:
- the rollup builds both tables inside PostgreSQL with `INSERT ... SELECT`, reusing the Report's outcome logic
  rather than a second newly-failed implementation;
- `impact_pairs` has no surrogate id, so there is no 32-bit id to exhaust, and a long path never enters an index;
- live scoring reads only the rows for the change's unit hashes, and only suggestible pairs are stored;
- one total 2 s deadline covers every scoring statement on the upload path (each PostgreSQL statement is capped at
  the time left).

Measured on 2026-10-12 on about 2 million results, 1,980 runs, one commit per run:

| Measure | Result | Budget |
|---|---|---|
| Rollup, one project | 19.0 s | under 60 s |
| Live scoring, p95 | 50 ms | under 200 ms |
| Scoring inside the upload, p50 | 32 ms | within the 2 s total |
| Outcome after the response, p50 | 502 ms | not in the request |

Storing every pair first gave 143,987 pairs and a scoring p95 of 249 ms; filtering by every threshold at rollup
time is what met the budget. The figures are in the ingestion README "Budgets".

## Alternatives rejected
- **Coverage instrumentation:** a per-language agent in every customer's CI, which the spec rules out.
- **A learned model now:** no outcomes yet to train or judge it on.
- **Code embeddings now:** they need Qdrant, behind the Phase 6 trigger.
- **Scoring only when someone looks:** it could see later data, so the accuracy would flatter it.
- **Live statistics without a rollup:** the window over about 2 million results costs seconds, against a budget of
  200 ms per scoring.
- **Skipping tests in CI by default:** a team opts in (`--suggested-only`). Release B runs the suggested tests first
  and the full suite every time otherwise.

## Release B: suggested tests first in CI (2026-10-13)

Spec `docs/superpowers/specs/2026-10-13-suggested-tests-first-design.md`, plan
`docs/superpowers/plans/2026-10-13-suggested-tests-first.md`. Collector 0.7.0.

- **Two stages, one run.** `run-impact` runs the suggested scenarios first and every other one after, and uploads
  both as one run with its `stages` (names, sizes, failures, durations, the time to the first failure). A failure
  in the changed area shows up in minutes, and the full suite still runs.
- **The Cucumber mechanism:**
  - a dry run with a JSON report discovers the scenarios, read by the upload's own Cucumber JSON parser;
  - two rerun files hold the suggested scenarios and the rest (matched on the feature uri and the scenario name);
  - a second dry run checks that the rerun file alone selects stage 1, because cucumber-js adds profile `paths` to
    it and `--shard` drops scenarios. On a mismatch nothing runs (exit 2): a wrong subset run silently would be
    worse. This keeps "no scenario runs twice, none is left out" true.

  The same mechanism serves cucumber-js, cucumber-jvm (system properties) and Ruby. Other runners are follow-ups.
- **The honest subset exclusion.** Runs record `scope` and `stages` (migration 020).
  - A run of only the suggested tests (`--suggested-only`, a `--fail-fast` stop, or a stage that wrote no report)
    is `impact-subset`.
  - It stays out of the statistics, the history count, replay, the outcome evaluation and the accuracy figure. A
    subset cannot show what the suggestion missed, so counting it would flatter the catch rate.
  - Its suggestion is stored and answered as `not_evaluated`, a state derived from the scope.
  - Its results count everywhere else: trends, flaky detection, the Report, and as history for later runs.
- **The safety rule.** Scoring never costs a test run. When the change cannot be scored (no change data, 401, 403,
  404, 422, 429, 5xx, a timeout, no answer), when the collector cannot reach QEOS as configured (no URL or key, as on
  a fork pull request), or when the stages cannot be planned, the command runs as given, as one stage, and the log
  says why. Only `--suggested-only --no-fallback` ends without tests (exit 2, 3 or 4, as `impact`).
- **Never skipping by default.** `first` runs the full suite every time. `only` is opt-in, with the full suite as
  fallback when there is no suggestion. Partial runs are labelled on the run page, in the runs list, in failure
  alerts and in the weekly summary.
- **The per-key permission (user decision).** `POST /api/v1/collect/impact` runs the same scoring, limits and 503
  `impact_timeout` as `POST /analytics/impact`, for the key's project; the analytics route needs a user token, which
  CI does not have. API keys are upload-only by default: only a key an owner or admin allowed (`can_read_impact`)
  reads its project's suggestions (test names, path units, aggregate evidence, which named tests failed on the
  branch); any other gets 403 `impact_not_allowed`, and `run-impact` then runs everything.
- **Consequences:**
  - a `run-impact` run costs two extra dry runs (discovery and the stage-1 check), seconds for cucumber-js and a
    build start for Maven;
  - Gradle users forward `cucumber.*` system properties to the test task;
  - the request hash leaves `scope` and `stages` out at their defaults, so uploads stored before migration 020
    still replay;
  - CI integrations hand the test command over as `bash -c "$QEOS_TEST_COMMAND"` and never put input text into a
    script.

## Consequences
- **Upload cost:** each upload with changed files pays one scoring (32 ms p50 measured) and an evaluation after
  its response.
- **Rollup cost:** 19.0 s per project on the benchmark, once every 24 hours; a stalled job raises JobStale after
  two days.
- **Retention:** `run_impact` goes with its run (retention and legal hold apply). The statistics are rebuilt from
  the runs that remain.
- **Known limits:**
  - runs record no repository yet, so path units carry no repository prefix;
  - a rename starts a new history;
  - replay uses the flaky and muted tests known at replay time;
  - a part after the first of a split upload may list the previous part's failures as *failing on this branch*;
  - the random-failure benchmark suggested about 76 tests per change, so thresholds need tuning on real data.
- **Follow-ups in TODO.md:** run-impact formats beyond Cucumber, the learned model, Phase 6 embeddings, the
  accuracy figure in the weekly summary, a repository prefix for path units, a narrow layout for Report tables,
  `impact_test_base.id` as a BigInteger (or dropped for `(project_id, test_key)`) before real scale, and threshold
  tuning on real data while watching `avg_suggested`.
