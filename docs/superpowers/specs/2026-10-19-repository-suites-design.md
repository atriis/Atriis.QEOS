# Repository suites: sync the CI suite workflows into QEOS and run them from QEOS

Date: 2026-10-19 · Status: for approval (builder check done) · Decision record to write: ADR-035

## 1. Intent

The test repository (Atriis.Test.Automation.OBT, "OBT") already defines its suites: the matrix legs of its
GitHub Actions suite workflows. Today people see and start them only in GitHub. QEOS shows test cases and
results, but its Suites tab holds only suites made by hand.

The user wants:

1. **Every suite of the five suite workflows in QEOS**, under Test Cases → Suites, with what each contains,
   kept in step with the repository.
2. **To run them from QEOS** instead of from GitHub, and the run must be the same as the nightly one
   (per-suite parallelism, retry, sharding, timeouts, Allure, upload).
3. **To keep making suites in QEOS**: filter Test Cases, tick cases, add them to a new or existing suite.

Why: QEOS becomes the one place to see what is tested, start it, and read the results. A suite run from
QEOS must not behave differently from the nightly, or its results cannot be compared.

## 2. Decisions taken with the user

- A **repository suite** is one matrix leg (`suite_id`) of one of these workflows: `suite-flights.yml`
  (25 legs), `suite-hotels.yml` (2), `suite-shell.yml` (28), `suite-transportation.yml` (13),
  `suite-preprod.yml` (4). The workflow is a **group** in QEOS (Flights, Hotels, Shell, Transportation,
  Preprod).
- Repository suites are **read-only in QEOS**. The repository owns them, as it owns imported cases
  (ADR-023). To change one, change the workflow.
- **Run starts the repository's own workflow** (option b), not the generic `qeos-run.yml`:
  - one suite: the workflow with `suites=<suite_id>`;
  - a whole group ("Run all"): the workflow with `suites` blank, as a manual run today.
  The repository workflows gain an input for that (section 5).
- Suites made in QEOS keep working as today, plus **Add to suite** from the Test Cases selection.
- In this version also: `qeos-run.yml` in OBT (so QEOS-made suites can run), a **"Not in any suite"**
  filter on Test Cases, and **sync warnings for broken suite paths**.
- Later (TODO): last result per suite on the Suites list; copy a repository suite into an editable one; a quiet window before the nightly.

## 3. Goals, non-goals, anti-goals

**Goals**
- The Suites tab shows the five groups and their suites, each with its cases, matching the workflows on
  the default branch after every push that changes them.
- Run on a repository suite produces the same GitHub run the nightly produces for that leg, and its
  results arrive in QEOS through the existing upload step.
- Making a suite from a filtered selection takes no more than: filter, tick, Add to suite, name.

**Non-goals**
- Editing workflows from QEOS. Scheduling runs from QEOS. Other CI providers.
- Tag-based suites (`@regression` covers nearly everything; `@smoke`/`@sanity` are tiny).
- Showing which half of a sharded folder ran where (GitHub decides at run time).

**Anti-goals** (a failure even if it works)
- A suite run from QEOS that runs with different settings than the nightly for that suite.
- A QEOS suite list that silently disagrees with the workflows (an empty suite from a typo, a suite left
  behind after its leg was deleted).
- Any change to how the nightly, the scheduler, the reruns or manual GitHub runs behave when `suites` is
  blank.

## 4. Constraints

- QEOS never runs tests (ADR-025). It dispatches GitHub workflows with the project's CI token; results come
  back through the collector upload already in `suite-runner.yml` (line 273).
- ADR-025 allows one active run request per project (partial unique index). This design changes it to one per (project, workflow), see 5.4.
- The collector has **no dependencies** (`collector/pyproject.toml`: `dependencies = []`); it cannot parse
  YAML. The feature import already sends raw file contents and lets the server parse them.
- Imported cases are identified by `source_path` + scenario (ADR-023); suites hold case rows
  (`suite_cases`, ordered, max 1000 per suite, `MAX_SUITE_CASES`).
- `workflow_dispatch` inputs: at most 10 per workflow, 65 535 characters in total (`MAX_INPUT_CHARS`).
- GitHub only.

## 5. How it works

### 5.1 What the repository changes (OBT)

Each of the five caller workflows gains two `workflow_dispatch` inputs, and passes them to
`suite-runner.yml`:

```yaml
suites:      # space-separated suite_ids to run; blank = every leg (today's behaviour)
  type: string
  default: ''
request_id:  # set by QEOS; blank otherwise
  type: string
  default: ''
```

- `suite-runner.yml` filters its matrix and `expected-suites` to the listed `suite_ids` (a small job that
  builds the filtered matrix with `jq` before the test job). An unknown `suite_id` fails the run with a
  clear message rather than running nothing.
- `run-name` is **exactly** `QEOS #<request_id>` when `request_id` is set (`github_client.find_run`
  compares the title exactly), so QEOS can match the run when GitHub answers the dispatch with 204
  (ADR-025's fallback). Without `request_id`, today's run-names are unchanged. `suite-preprod.yml` has no
  `run-name` today and gains one with the same rule.
- **QEOS runs stay out of the nightly's history** (user decision): when `request_id` is set, the run does
  not publish Allure history, and every "latest run" lookup (`suite-runner.yml`'s `history-workflow`
  download, `rerun-runner.yml` / `rerun-*.yml` with a blank `run_id`) skips runs whose title starts with
  `QEOS #`. The nightly's trend and the manual reruns behave exactly as today.
- `qeos-sync-cases.yml` also triggers on `.github/workflows/suite-*.yml` and passes the five files to the
  sync (5.2).
- New `qeos-run.yml` (from `templates/github/qeos-run.yml`), adapted to run like a suite leg:
  `--profile ci`, `--retry 1`, the same environment secrets, and the collector upload. Used only by suites
  made in QEOS.
- QEOS ships these as templates and documentation; the repository owner applies them. The QEOS side must
  not depend on OBT-specific names beyond what the sync reads from the files.

### 5.2 Sync (collector → test-management)

- `qeos-collector import-features` gains `--suites PATTERN` (repeatable). It reads the matching workflow
  files and sends their raw contents with the feature files, in the same request:
  `{"files": [...], "full": true, "suite_files": [{"path", "content"}]}`. No YAML parsing in the collector.
- test-management parses each workflow file with a safe YAML loader (add PyYAML, `safe_load` only). It reads
  `name` (the group's display name, e.g. "Suite - Flights" shown as "Flights"), and the `with.matrix` JSON
  of the job that calls `suite-runner.yml`, taking `suite_id`, `suite_name`, `test_path` and `shard` from
  each `include` row. Other keys (parallel, retry, timeouts) are not stored: the workflow keeps them.
- `test_path` is split on spaces. Each entry ending in `/` is a folder; each ending in `.feature` is a file.
  A suite's cases are the imported, non-archived cases whose `source_path` is under one of its folders or
  equal to one of its files, ordered by `source_path` then scenario line.
- Sync rules, applied in the import's single transaction, keyed by (workflow path, `suite_id`):
  - new leg → create the repository suite; changed name or paths → update it; leg gone → delete the suite
    (its past run requests keep their `suite_id` as a plain number, as when a hand-made suite is deleted).
  - membership is recomputed at every sync, so new, moved or archived cases follow automatically.
  - the `--suites` patterns are authoritative for what they cover: a previously synced workflow whose path
    matches one of this sync's patterns but is no longer present (deleted or renamed) has its whole group
    deleted. A previously synced workflow that matches none of the patterns is left alone, so a narrower
    pattern never deletes other groups. The collector sends its patterns with the request. *(My call.)*
  - the collector also sends the repository (`GITHUB_REPOSITORY`, `owner/name`); each repository suite
    records it as `source_repo`. *(My call.)*
- **Warnings (goal 3 of the extras):** the import result gains `suite_warnings`, and the collector prints
  them, for: a `test_path` entry that matches no imported case; a leg without `suite_id` or `test_path`;
  a duplicate `suite_id` in one workflow; a matrix that does not parse. A suite with a warning is still
  synced (with what did match); a workflow that does not parse is skipped and keeps its previous suites.
  `--strict` (already on the command) turns warnings into a failure.
- A suite over 1000 cases is a warning and is cut at 1000 (today's limit); none of OBT's legs is near it
  (largest folder ≈ 106 scenarios).
- Dry run reports the suite changes too, and they are part of `plan_hash`.

### 5.3 Data (test-management)

`suites` gains:
- `origin`: `manual` (default, existing rows) or `repository`;
- `workflow` (the bare file name, e.g. `suite-flights.yml`, the form `github_client` and `ci_targets`
  already validate with `^[A-Za-z0-9._-]{1,100}\.ya?ml$`), `group_name` (e.g. "Flights") and `source_repo`,
  repository only. The sync takes only files directly under `.github/workflows/`, so the bare name is
  unambiguous. *(My call.)*
- `external_id` (`suite_id`, e.g. `flights-amadeus-non-booking`), repository only, unique per
  (project, workflow);
- `shard` (e.g. `1/2`), nullable, display only;
- `test_paths` (JSON list), repository only, for display and the warnings.

Repository suite names are the leg's `suite_name`. Name uniqueness per project stays; on a clash with a
hand-made suite, the repository suite is created with its `suite_id` as name and a warning.

A new migration; existing rows become `origin = manual`.

### 5.4 API

- `GET /suites` returns `origin`, `group_name`, `workflow`, `source_repo`, `external_id`, `shard` as well; the
  dashboard groups by `group_name`.
- `PATCH`, `PUT /cases` and `DELETE` on a repository suite answer **409 `repository_suite`** ("Managed by
  the repository: change the workflow instead.").
- `POST /suites` (hand-made) unchanged.
- New `POST /suites/{id}/cases:append` with `{"cases": [numbers]}`: appends to a hand-made suite, skips
  cases already in it, keeps the order, 409 on a repository suite, 422 above 1000 in total. Used by Add to
  suite (a `PUT` would race with another editor and needs the whole list).
- `GET /cases?suite=none`: cases (imported and not archived) in no **repository** suite. This is the
  "Not in any suite" filter: its point is tests the nightly never runs, so hand-made suites do not count.
  (Builder: if a filter covering both kinds is cheap, offer `suite=none-any` too; not required.)
- Run requests: `POST /run-requests` accepts, besides `case_numbers` or `suite_id`,
  `{"workflow_group": "<workflow>"}` for Run all. For a repository `suite_id` or a `workflow_group`,
  dispatch goes to that suite's `workflow` with inputs `{"suites": "<suite_id>" | "", "request_id":
  "<id>"}` on the CI target's repo and ref, with the CI target's token. Hand-made suites and case selections
  keep dispatching the CI target's workflow (`qeos-run.yml`) with `paths`/`names`.
- `run_requests` gains `workflow` (the file dispatched), so refresh and the 204 title match look in the
  right workflow. Existing rows: the CI target's workflow.
- **What a repository run stores** *(my call)*: it does not go through `build_selection`'s case checks
  (`MAX_CASES = 200`, archived, "unnamed", manual, empty), because the workflow runs its folders whatever
  QEOS thinks of the cases. `selection` holds QEOS's view of the membership at dispatch (case numbers, keys
  and names, for the run page and the estimate), `case_count` its size, and `skipped_manual` 0. A suite or
  group whose membership is empty may still be run (the workflow decides); the Run dialog says "QEOS has no
  imported cases for this suite; the workflow runs its folders as configured". `MAX_INPUT_CHARS` is not at
  risk: the inputs are a few `suite_id`s.
- **Repository and CI target** *(my call)*: Run on a repository suite needs a CI target whose `repo` equals
  the suite's `source_repo` (case-insensitive). Without one, Run is disabled with "Set up Run from QEOS in
  Project Settings for <source_repo>". QEOS dispatches only a `workflow` taken from a synced suite row,
  never a name sent by the browser.
- **One active run per workflow** (user decision): the "one active request per project" rule becomes one
  active request per (project, workflow). Hand-made suites and selections share the CI target's workflow
  slot as today; Flights, Hotels, Shell, Transportation, Preprod each have their own. The partial unique
  index changes accordingly, and the "already running" message names the workflow.
- **Busy on GitHub** (user decision): before dispatching to a repository workflow, QEOS asks GitHub for runs
  of that workflow that are `queued`, `in_progress`, `waiting` or `pending` on the ref. If there is one,
  Run is refused (409 `workflow_busy`): "Flights is already running on GitHub (started 21:00). Try again
  when it finishes." with a link to that run. This avoids GitHub's `concurrency` group cancelling a waiting
  nightly or the QEOS run. If GitHub cannot be asked, the dispatch is refused, not sent blind. A "quiet
  window" before the nightly is out of scope (TODO).

### 5.5 Dashboard

- **Suites tab:** groups first (Flights, Hotels, Shell, Transportation, Preprod; then "Made in QEOS"), each
  collapsible with its suite count and a **Run all** button; each suite row shows name, case count, a
  "From repository" marker, "Half 1 of 2" when sharded, and **Run**. Hand-made suites keep today's columns
  and New suite form.
- **Suite page** for a repository suite: the cases (read-only), the workflow file and `suite_id`, its
  `test_path` entries, a note that it is managed by the repository, and Run. No move, remove or add.
  Sharded: "GitHub splits this folder between Half 1 and Half 2 at run time; both list the whole folder."
- **Test Cases:** the selection bar gets **Add to suite** next to Run selected: pick an existing hand-made
  suite or type a new name; confirm with how many were added and how many were already there; link to the
  suite. A **"Not in any suite"** filter joins the existing filters.
- **Run:** same `RunControl` as today; a repository run says which workflow and suite it starts. If that
  workflow already has an active QEOS request, or is busy on GitHub, the dialog shows the reason and a link
  to the run instead of starting.
- Follow `DESIGN.md` and the `ui-ux-pro-max` skill; reuse `table.data`, `ConfirmButton`, `ErrorBanner`.

## 6. Things to keep in mind

- **Shards:** both halves list the whole folder; Run on "Half 1 of 2" runs only that leg, as on GitHub.
- **Preprod** holds explicit files from all domains; those cases are also in their domain suites. Fine.
- **Blocked folders** (`*_blocked`) are in no workflow, so their cases show under "Not in any suite". That
  is correct and useful.
- **Token scope:** the CI token already may dispatch any workflow in the repository (ADR-025 consequence);
  nothing new to grant. QEOS dispatches only a `workflow` that came from a synced suite, never a path
  sent by the browser.
- **Results:** the uploaded run's environment and name come from `suite-runner.yml`'s upload step;
  QEOS-started runs must be findable from the run request (link to the GitHub run, as today).
- **Docs:** ADR-035 (repository suites; amends ADR-025 for per-suite workflows), SETUP (sync `--suites`,
  the OBT workflow changes, `qeos-run.yml`), collector README, test-management README, DESIGN, TODO
  (follow-ups: last result per suite; copy a repository suite; quiet window before the nightly).

## 7. Left to the builder

- The exact `jq` filter in `suite-runner.yml` and the error text for an unknown `suite_id`.
- How the server finds "the job that calls `suite-runner.yml`" (any job whose `uses` ends with
  `suite-runner.yml`; the `matrix` input may be a JSON string or a YAML mapping, accept both).
- Group display name rule (strip a leading "Suite - "; fall back to the file name).
- Pagination and collapse state of groups; keyboard and screen-reader details per DESIGN.md.
- Test layout, following each service's existing tests.

## 8. Calls made without the user (check these)

- A repository run skips the case checks of hand-made runs and stores QEOS's view of the membership (5.4).
- A deleted or renamed workflow removes its group when it matches the sync's `--suites` pattern (5.2).
- Suites record `source_repo`; Run needs a CI target on the same repository (5.4).
- Workflows are stored and dispatched by bare file name (5.3).
- The QEOS run-name is exactly `QEOS #<id>` (5.1).
- PyYAML `safe_load` in test-management to read the workflows (5.2).
- "Not in any suite" counts repository suites only (5.4).
- A name clash with a hand-made suite falls back to the `suite_id` as name, with a warning (5.3).
