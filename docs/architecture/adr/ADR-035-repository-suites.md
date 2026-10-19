# ADR-035: Repository suites: the CI suite workflows become read-only suites in QEOS

Status: Accepted (2026-10-19) · Spec: `docs/superpowers/specs/2026-10-19-repository-suites-design.md`

Stage 1 (sync and read-only suites) and stage 2 (running them from QEOS, see "Running them" below) are shipped.
Stage 2 amends ADR-025: the workflow is per row, and there is one active run per workflow.

## Context

A test repository often defines its suites as the matrix legs of GitHub Actions workflows: one workflow per product
area, one leg per suite, each leg naming the folders or files it runs. People see and start those suites only in
GitHub. QEOS shows test cases and results, but its Suites tab held only suites made by hand, so it could not say
what the nightly runs.

The test cases already follow the repository (ADR-023): it owns them and QEOS never fetches its files. Suites should
follow it the same way.

## Decision

- **A repository suite is one matrix leg** of a suite workflow, keyed by workflow file and the leg's `suite_id`.
  The workflow is the **group** shown on the Suites tab.
- **The repository sends the workflows**, as it sends the `.feature` files. `qeos-collector import-features
  --suites PATTERN` (repeatable) sends the raw workflow files, the patterns and `GITHUB_REPOSITORY` in the same
  `POST /cases/import`. The collector parses no YAML: test-management reads each file with a safe loader and takes
  `suite_id`, `suite_name`, `test_path` and `shard` from the legs. Nothing else is stored; the workflow keeps its
  parallelism, retry and timeouts.
- **Same transaction, same plan.** Suites sync with the cases. A dry run and `plan_hash` include the suite changes.
  A new leg is created, a changed one updated, a missing one deleted. The patterns are authoritative for the
  workflows they cover: a covered, previously synced workflow that is gone loses its whole group, and a workflow no
  pattern covers is left alone, so a narrower pattern never deletes other groups. A workflow that does not parse, or
  has no legs, keeps its previous suites.
- **Only `.github/workflows/<name>.yml`** with a name matching `^[A-Za-z0-9._-]{1,100}\.ya?ml$` is accepted, so the
  bare file name identifies the workflow without ambiguity.
- **Membership is computed from the cases.** The live imported cases under the leg's folders and files, ordered by
  path then line, cut at 1000 (`MAX_SUITE_CASES`) with a warning. It is recomputed at each sync, so new, moved and
  archived cases follow. An import without suite fields (the dashboard, an older collector) changes no suite but
  recomputes their cases too.
- **Read-only.** Changing a repository suite answers 409 `repository_suite`: "Managed by the repository: change the
  workflow instead."
- **Warnings, not silence.** `suite_warnings` reports a `test_path` that matches no case, a leg without `suite_id` or
  `test_path`, a repeated `suite_id`, a cut suite, and a name clash with a hand-made suite (the repository suite then
  takes its `suite_id` as name). A suite with a warning is still synced with what matched. `--strict` fails on warnings.
- **No superuser, no new secret.** Suites travel with the existing import and its project API key (ADR-024).
- Test-management migration 009 adds `origin`, `workflow`, `group_name`, `external_id`, `shard`, `test_paths` and
  `source_repo` to suites, and `workflow` to run requests (used in stage 2).
- Around it: `POST /suites/{id}/cases/append` and **Add to suite** on the Test Cases selection, and the **Not in any
  suite** filter (`GET /cases?suite=none`: imported live cases in no repository suite; hand-made suites do not count).

## Running them (stage 2)

- **Run and Run all.** `POST /run-requests` takes exactly one of `case_numbers`, `suite_id` or `workflow_group`
  (the bare workflow file; Run all of a group). A repository suite or group dispatches **its own workflow**, for
  example `suite-flights.yml`, on the CI target's repository and branch, with the inputs
  `{"suites": "<suite_id>" or "", "request_id": "<id>"}`. The workflow runs the leg with the settings of the
  nightly. QEOS finds the run by its title `QEOS #<id>`. Hand-made suites and case selections still use the
  CI target's workflow (`qeos-run.yml`).
- **One active run per workflow** (test-management migration 010; ADR-025 said one per project). Each request
  records its workflow, and the unique index is on project and workflow. Two different workflows can run at once.
- **Busy check before the dispatch.** QEOS asks GitHub whether that workflow has a queued, in progress, waiting,
  pending or requested run on any branch (suite workflows' `concurrency` groups are not branch-scoped, so a
  run on any branch holds the group). If so: 409 `workflow_busy` ("<Group> is already running on GitHub
  (started HH:MM). Try again when it finishes."). This also covers a run that did not start from QEOS, such as the
  nightly. If GitHub cannot be asked: 503 `github_unavailable`, and nothing is started.
- **Same repository.** A repository suite whose recorded `source_repo` differs from the CI target's repository
  (case-insensitive) answers 409 `repository_mismatch` ("Set up Run from QEOS in Project Settings for
  <source_repo>"). A suite with no `source_repo` is not checked.
- **Relaxed case checks.** The 200-case cap and the manual, archived and unnamed checks do not apply: the
  workflow decides what runs. The request stores QEOS's view of the membership as its selection.
- **Only synced names are dispatched.** QEOS dispatches workflow names taken from synced suite rows or from the
  CI target, never from browser input. The token scope is unchanged (SECURITY.md).
- **The repository changes too.** The workflow gains the `suites` and `request_id` inputs, a select job that
  filters the matrix, and the run name `QEOS #<id>`. A QEOS run skips Allure history and "latest run" lookups, so
  it cannot disturb the nightly's reports. `templates/github/repository-suites.md` lists the changes for other
  repositories. QEOS-made suites keep using `qeos-run.yml`.
- Responses include `workflow`. The dashboard shows Run on each repository suite and its page, and Run all on each
  group; its gate is per workflow, and it shows the refusals (busy with a link to GitHub, mismatch with a link to
  Project Settings, unavailable with Retry).

## Alternatives considered

- **Tags as suites** (`@regression`, `@smoke`). Rejected: `@regression` covers nearly every scenario and `@smoke`
  and `@sanity` are tiny, so tags do not match what the nightly runs.
- **A generic `qeos-run.yml` for repository suites.** Rejected for repository suites: a run from QEOS would use
  other settings than the nightly for the same suite (parallelism, retry, sharding, timeouts, reports), and the
  results could not be compared. Stage 2 runs the repository's own workflow instead. `qeos-run.yml` stays for suites
  made in QEOS.
- **QEOS reads the workflows from GitHub.** Rejected: QEOS keeps no read access to repositories (ADR-023).
- **A collector that parses YAML.** Rejected: the collector has no dependencies and stays that way.

## Consequences

- The Suites tab shows what the repository runs, kept in step by the sync. The repository stays the owner.
- Each repository needs the `--suites` option in its sync workflow, and its trigger paths must include the suite
  workflows. Without them nothing syncs.
- A server older than this version answers 422 to the new fields, so the sync workflow changes only after QEOS is
  upgraded.
- Test-management now depends on PyYAML, used with `safe_load` only.
- Membership is QEOS's view of the folders. The workflow decides what really runs.
- The repository's workflows must have the new inputs before a run works. The OBT change is merged only after QEOS
  runs this version and collector 0.10.0 is tagged.
- The busy check reads the newest 100 runs of the workflow, and the dashboard gate reads the newest 50 requests.
  A busier history could miss an active run; GitHub's own concurrency rules still apply.
