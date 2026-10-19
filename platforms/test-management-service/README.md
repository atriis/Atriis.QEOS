# Test Management Service

Written test cases and suites for a project, and the link from each case to the automated test
that implements it.

- Decision: `docs/architecture/adr/ADR-022-test-management-service.md`, and for the import `docs/architecture/adr/ADR-023-gherkin-import.md`
- Design: `docs/superpowers/specs/2026-10-06-test-management-design.md`

## Run

In the platform stack: `docker compose up -d test-management-service`. That also runs
`test-management-migrate` (`alembic upgrade head`) against `testmgmt_db`. The gateway routes
`/api/v1/projects/{id}/(cases|case-labels|case-folders|case-features|features|suites|ci-target|run-requests)` here.

On its own, for the container smoke test: `SECRET_KEY=… docker compose up --build`. It answers on
port 8004, and its database is on 5437.

## Metrics

`GET /metrics` (Prometheus text, inside the Docker network only; the gateway never routes it) serves the shared request metrics from `qeos_shared.metrics` — `api_requests_total`, `http_requests_duration_seconds`, `http_requests_in_flight`, `build_info` — and the process metrics, plus `test_case_creation_total{type}` (`manual` for `POST /cases`, `api` for cases an applied Gherkin import creates). See the monitoring design, `docs/superpowers/specs/2026-10-10-monitoring-design.md`.

## Tests

```
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # Python 3.11
SECRET_KEY=test .venv/Scripts/python -m pytest -q
```

The integration tests use SQLite. `tests/unit/test_migration.py` runs the real migration.

## API (under `/api/v1/projects/{project_id}`)

Every project role reads. Owner, admin and member edit. A project the caller cannot see answers
404.

| Method | Path | |
|---|---|---|
| `GET` | `/cases?search=&label=&label=&status=&priority=&origin=&folder=&linked=&feature=&ado=&include_archived=&limit=&offset=` | `{total, items}`; archived hidden unless asked; `origin=manual` or `imported`; search also matches the Gherkin text. `search_in` (`scenario`, the default; `feature`; `both`) chooses what the search term is matched against: `scenario` is the title, Gherkin and TC key, `feature` the case's Feature name or file path, `both` either (also on `POST /cases/search`). A search of the form `TC-12`, `tc12` or `12` (1-9 digits, optional `TC`/`TC-`) also matches the case with that number, which sorts first (this applies to `POST /cases/search` too); `total` counts every match, the numbered case plus any whose title or Gherkin contains the digits. Filters are ANDed: `folder` (an imported case's `source_path` under that folder, subfolders included), `linked` (true: has an automated test), `feature` (the Gherkin Feature name), `ado` (digits only, else 422; matches the label `ado-<n>`) |
| `POST` | `/cases/search` | the same filters as a JSON body (`labels` is a list and `linked` a boolean; `folder` and `feature` up to 500 characters, `ado` 1-12 digits), plus `test_keys` (up to 20 000 64-hex keys, more is 422) and `keys_mode` (`include` default, or `exclude`, which also keeps cases with no automated test); same response as `GET /cases`; every project role may call it. It exists because a list of keys does not fit in a URL |
| `POST` | `/cases` | `title`, `description`, `steps[{action, expected}]`, `labels`, `priority`, `status`, `automated_test_key`, `automated_name` |
| `POST` | `/cases/import?dry_run=` | `{files:[{path, content}], full, allow_mass_archive, expected_plan_hash, suite_files?, suite_patterns?, source_repo?}` (`full` and `allow_mass_archive` default to `false`; `suite_files` needs `suite_patterns`, see Repository suites); returns `{plan_hash, summary, items, errors, warnings, suite_changes, suite_warnings}`; a dry run writes nothing; accepts an editor's JWT or the CI service token (ADR-024), whose changes are recorded as user 0; a `full` import that would archive over half the live imported cases is 409 `mass_archive` unless `allow_mass_archive` is true |
| `GET` / `PATCH` | `/cases/{number}` | the single read also lists the case's suites; `automated_test_key: null` unlinks |
| `GET` | `/case-labels` | labels in use (archived cases left out), with counts |
| `GET` | `/case-folders` | `[{path, count}]` folders of imported cases; a count includes subfolders and leaves out archived cases |
| `GET` | `/features?search=&search_in=&folder=&label=&status=&priority=&linked=&limit=&offset=` | `{total, items:[{feature_name, path, folder, case_count, case_numbers, test_keys, has_source, linked_count, top_priority, status_counts}]}`: the active cases the filters keep (those of `GET /cases`), grouped by `(feature_name, path)`, ordered by folder then feature name; all manual cases are one last group `{feature_name: null, path: null, folder: null}`. `case_numbers` are the first 200, by number; `test_keys` are the distinct, non-null `automated_test_key` values of those cases, sorted, at most 200; `has_source` is true when the raw file text is stored. `linked_count` is the cases with an `automated_test_key`; `top_priority` the highest priority among the group's cases (`critical` > `high` > `medium` > `low`); `status_counts` has every status key (`draft`, `ready`, `archived`), 0 when none; all three cover only the cases the filters keep, and archived cases never appear here. `search_in` is `feature` (the Feature name or the path contains the term), `scenario` (title, Gherkin, TC key) or `both` (default); case-insensitive, `%` and `_` literal. `limit` defaults to 50, at most 200. Every project role |
| `GET` | `/features/detail?path=` | `{feature_name, path, folder, content, imported_at, cases:[{number, key, title, scenario_name, status, priority, automated_test_key, line}]}`; `content` and `imported_at` are null until the file is imported again after this was added; `cases` are active only, in file order by `line` (the scenario heading's line, stored at import; derived from the stored text for older imports); cases with no `line` come last, by number; 404 when no active case has that path |
| `GET` | `/case-features` | `[{feature, count}]` Gherkin Feature names of active imported cases, sorted by feature |
| `GET` | `/case-areas` | every active case for the report's joins (ADR-026): `{generated_at, counts{cases, linked, manual}, folders, features, labels, suites[{id, name}], cases[{n, t, k, fo, fe, l, s}]}`; the four dictionaries are sorted and cases point into them by index (`fo`/`fe` null when absent); folder is the directory part of `source_path`; 409 `too_many_cases` above 50,000 cases; every project role |
| `GET` | `/suites?search=&created_by=me` | `search` (1-200 characters, no NUL, else 422): case-insensitive contains match on the suite name, `%` and `_` literal; `created_by=me` keeps the caller's own suites (any other value is a 422); every project role |
| `POST` | `/suites` | name unique per project (409) |
| `GET` / `PATCH` / `DELETE` | `/suites/{id}` | detail lists the cases in order; delete keeps the cases |
| `PUT` | `/suites/{id}/cases` | `{"cases": [3, 1, 2]}` replaces the ordered list |
| `GET` | `/ci-target` | `{available, configured, provider, repo, workflow, ref, token_last4, token_expires_at, updated_at, last_change}`; every role; the token itself is never returned |
| `PUT` | `/ci-target` | owner or admin; `{repo, workflow="qeos-run.yml", ref="main", token?}`; the token is required on the first save; checked with GitHub first: 422 "token invalid or expired" (401), "token has no Actions access to this repository. Check that the token's resource owner is "<owner>" ..." (403, naming the repository's owner, since a token made under your own account cannot reach an organization's repository), "repository or workflow not found. The workflow file must exist on the repository's default branch" (404); 503 without `TM_SECRETS_KEY` or on a GitHub rate limit |
| `DELETE` | `/ci-target` | owner or admin; 409 while a run is still active (the active run is first refreshed from GitHub, so one that already ended does not block); the audit trail (`ci_target_events`) is kept |
| `POST` | `/run-requests` | owner, admin or member; `{case_numbers: [1..200]}` or `{suite_id}`; 201 with the request (also when it is `failed_to_start`); 412 no target; 409 `run_active`; 422 names the cases that cannot run (manual, archived, unknown, or with no scenario name yet: re-import). A whole suite skips its manual cases instead (`skipped_manual` in the response; 422 when none is automated) |
| `POST` / `GET` | `/run-requests` (estimate) | `POST` also takes optional `estimate_ms` and `estimate_upper_ms` (integers 0–86 400 000, else 422; migration 008), which the dashboard got from ingestion's `POST /analytics/duration-estimate`; they are stored as sent (null when left out) and returned on every run-request read. Test Management never calls ingestion (ADR-022) |
| `GET` | `/run-requests?limit=&offset=` | `{total, items}`, newest first; an active request is refreshed from GitHub when last checked over 5 s ago; `refreshing` says whether to keep polling |
| `GET` | `/run-requests/run-urls?since=` | `{urls, truncated}`: the non-null `github_run_url` of requests made since `since` (ISO datetime; required, a naive datetime is treated as UTC; at most 500 days back), newest first, at most 5,000; every project role |
| `GET` | `/run-requests/{id}` | the same refresh rule |
| `POST` | `/run-requests/{id}/stop` | owner, admin or member; cancels on GitHub (`cancelling`, `stopped_by`); 409 `run_finished` |

Limits:

- Title: 200 characters.
- Steps: 50, each up to 2 000 characters.
- Labels: 20, each matching `[A-Za-z0-9._-]{1,40}` and stored lower-case.
- Suite cases: 1 000.
- Search filters: `folder` and `feature` up to 500 characters, `ado` 1-12 digits, `test_keys` up to 20 000.

After deploying migration 003, run a full import once to fill Feature on existing imported cases (every imported case shows as updated in that run).

## Internal API

`DELETE /internal/v1/projects/{project_id}` deletes every case, label, suite, feature file, run request and the CI
target of one project (204, also when there is nothing). The ingestion retention job calls it when it purges a
deleted project (ADR-034). HTTP Basic against `INTERNAL_API_USERNAME` (default `ingestion-service`) and
`INTERNAL_API_PASSWORD`: wrong or missing credentials answer 401, an unset password 503. The gateway does not
route `/internal`, and the route is not in the OpenAPI schema.

## Run from QEOS (Play and Stop)

Design: `docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md`.

### Setup

1. Set `TM_SECRETS_KEY` in `.env`. Generate one with
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
   Keep it in your `.env` backups: losing it means re-entering the GitHub token.
2. Copy `templates/github/qeos-run.yml` to `.github/workflows/` and
   `templates/github/qeos-run.mjs` to `.github/scripts/` **on the repository's default branch**
   before the first Play. GitHub accepts `workflow_dispatch` only for a workflow on the default branch.
3. Add the secret `QEOS_API_KEY` and the variable `QEOS_URL` in the repository.
4. An owner or admin saves the repository and token in Project Settings.

A repository set up before the QEOS rename keeps working unchanged: its CI target keeps the stored
workflow file name (`qa-vision-run.yml`), runs titled `QA Vision #<id>` still match, and the
collector still accepts `QAV_API_KEY` and `QAV_URL`. Copying the new templates is optional.

### Limits

- 200 cases per run.
- One active run per project.
- GitHub is polled at most every 5 s, only while someone views the run.
- Workers 1, retries 0.
- After a 204 dispatch (no run details returned), a run not seen 2 minutes after Play is
  `failed_to_start`. After a 200 dispatch the run id is known at once.
- After a 204 dispatch, a Stop before the run is found is applied on GitHub only within that 2-minute
  window: the request is cancelled locally, and the run is cancelled on GitHub only if it is found in time.
- A 404 on a known run (the token lost access, or the repository was changed in Settings) ends the request
  as `cancelled` while the GitHub run may continue.
- GitHub's concurrency group cancels an older pending `qeos-run` when a newer one is queued.
- The workflow file must be on the repository's default branch, and on the configured branch.

### Selection

- Selection is by file and the raw scenario name. Outline placeholders match any value.
- The same scenario name in two selected files runs in both.
- A path the workflow's path rule rejects fails the job, with a message.

After deploying migration 004, run a full import once to fill `scenario_name`. Until then, Play on an
old imported case answers 422 "re-import the .feature files first".

### Security note

- **What the token can do:** a fine-grained token limited to one repository with "Actions: Read and write".
  It can start, cancel, re-run and delete that repository's workflow runs and logs, and read its workflow
  files. It cannot read or change code.
- **Wider than QEOS's workflow:** that scope can start *any* `workflow_dispatch` workflow in the
  repository, deploy workflows included, and they run with the repository's secrets. It can also read run
  logs. Use a dedicated repository for the test workflow where you can, or keep `qeos-run.yml` the only
  workflow that has a `workflow_dispatch` trigger, so a leaked token reaches no more than that.
- **At rest:** it is stored Fernet-encrypted with `TM_SECRETS_KEY` and never returned or logged. Responses
  show the last 4 characters.
- **Who can do what:** owners and admins set and remove it. Owners, admins and members can run and stop.
- **To revoke:** on GitHub, Settings > Developer settings > Fine-grained tokens > Revoke, then Disconnect in
  Project Settings.

## Gherkin import

`POST /cases/import` reads `.feature` files, one case per scenario. The repository owns an imported
case: title, steps, labels and Gherkin are read-only (422), the rest stays editable. A scenario that
disappears from an uploaded file is archived. A confirm with `expected_plan_hash` applies exactly the
plan that was previewed, or answers 409 `plan_changed`. See ADR-023.

- `full` defaults to `false`: only the uploaded paths are compared, so the cases of a deleted or
  renamed `.feature` file are not archived or moved (a renamed file's scenarios are created again).
  `full=true` treats the batch as the whole suite: cases of missing files are archived and renamed
  files keep their case numbers. The dashboard sends it when "This is my complete features folder"
  is ticked.
- The response carries `errors` (files skipped for a syntax error) and `warnings` (skipped
  scenarios and tags).
- `summary.mass_archive` tells a dry run whether the guard would refuse the real import.
- The raw text of every file that parsed is kept (table `feature_files`, one row per project and path,
  upserted on each import, from the dashboard and from CI). A file over `IMPORT_MAX_FILE_BYTES`
  (256 KiB by default) is refused with 413 as before, so stored text is never truncated. A `full`
  import deletes the stored files that are no longer in the folder; a partial one keeps them.
  `GET /features/detail` serves the text.
- Each case also keeps the line of its scenario heading (`cases.scenario_line`, Scenario, Scenario
  Outline or Example, inside a Rule too), and a scenario that only moved within its file is an update.
  Files imported before migrations 006 and 007 have no stored text (`has_source` false) and no line
  until their next import; until then `/features/detail` finds each line by scanning the stored text
  for a real scenario heading, and orders by case number when there is no text.
- The automated link the import sets follows a move; a link picked by hand is never changed.

```
curl -k -X POST "https://localhost:8443/api/v1/projects/1/cases/import?dry_run=true" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"files":[{"path":"tests/features/a.feature","content":"Feature: A\n  Scenario: s\n    Given x\n"}]}'
```

### Repository suites

An import may also carry the test repository's suite workflows (`suite_files`: each
`.github/workflows/suite-*.yml` with its raw text), the patterns that found them (`suite_patterns`,
up to 20) and the repository (`source_repo`, `owner/name`). Each leg of a workflow's suite-runner
matrix becomes a read-only repository suite, keyed by workflow file and `suite_id`, in the same
transaction as the cases.

- A new leg is created, a changed one updated, a removed one deleted. A synced workflow that a pattern
  covers but that was not sent is deleted with all its suites; one outside every pattern is kept.
- A suite's cases are the live imported cases under its folders or equal to its files, ordered by path
  and scenario line, recomputed at every sync (at most 1000).
- A workflow that does not parse, or has no usable leg, keeps its suites. A file name QEOS could not
  dispatch is skipped.
- `suite_warnings` lists these, and an entry that matches no case, a name already used by a suite made
  in QEOS (the suite takes its `suite_id` as name) and a suite cut at 1000.
- `suite_changes` is part of `plan_hash`. An import without `suite_patterns` leaves repository suites
  as they are.

Limits (over any of them is 413, and the message names the setting):

- `IMPORT_MAX_FILES`: files per request, default 2 000.
- `IMPORT_MAX_FILE_BYTES`: one file, default 262 144.
- `IMPORT_MAX_TOTAL_BYTES`: all file content, default 10 485 760.
- `GATEWAY_IMPORT_MAX_BODY`: the gateway's body cap on the import path, default `25m`. Keep it
  above the total plus JSON escaping (about 2.5x is safe).

To raise them, change `.env` and restart the gateway and this service.
