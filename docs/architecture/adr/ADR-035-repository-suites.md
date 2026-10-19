# ADR-035: Repository suites: the CI suite workflows become read-only suites in QEOS

Status: Accepted (2026-10-19) · Spec: `docs/superpowers/specs/2026-10-19-repository-suites-design.md`

Stage 1 (sync and read-only suites) is shipped. Running a repository suite from QEOS is stage 2: it is not built
yet, and this ADR will gain its run part when it is.

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
  archived cases follow.
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

## Alternatives considered

- **Tags as suites** (`@regression`, `@smoke`). Rejected: `@regression` covers nearly every scenario and `@smoke`
  and `@sanity` are tiny, so tags do not match what the nightly runs.
- **A generic `qeos-run.yml` for repository suites.** Rejected for repository suites: a run from QEOS would use
  other settings than the nightly for the same suite (parallelism, retry, sharding, timeouts, reports), and the
  results could not be compared. Running the repository's own workflow is stage 2. `qeos-run.yml` stays for suites
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
