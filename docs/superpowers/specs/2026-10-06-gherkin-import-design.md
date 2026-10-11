# Test management, second slice: import cases from Gherkin `.feature` files

Roadmap Phase 4 ("Test Management"), the slice named "Gherkin import" in IMPLEMENTATION_PLAN and
`TODO.md` ("Import existing TCs from the repo"). It builds on
[the first slice](2026-10-06-test-management-design.md) and ADR-022. Decisions made by the user on
2026-10-06:

- The `.feature` files live in the product's test repositories, not in this one. They reach QA
  Vision through **one endpoint** that serves both the dashboard upload (this slice) and a later
  `qav-collector import-features` CI command.
- **The repository owns the content of an imported case.** Title, Gherkin text and labels come from
  the file and are read-only in QA Vision. Status, description, suites and the automated-test link
  stay editable. A scenario that disappears from a file is archived, never deleted.
- **One case per `Scenario Outline`.** Its Examples tables stay in the case's Gherkin text.
- **Parsing happens on the server**, with Cucumber's official parser (`gherkin-official`).
- **The scenario's Gherkin is kept verbatim**, not converted to `{action, expected}` steps.
- A confirm applies **exactly the plan that was previewed** (`plan_hash`).

## What real files look like

The design was checked against a real Cucumber repository's `tests/features` (2026-10-06):

- 991 files, 1 042 scenarios, 13 outlines, 5 Backgrounds, no `Rule`, no `# language` header.
  The folder is 4.7 MB.
- It runs with cucumber-js from the repository root. It writes Cucumber JSON
  (`test-results/cucumber-report.json`), so a result's `uri` is `tests/features/…`.
- Tags carry structure: `@priority:high` (on about a third of the scenarios) and `@ado:81284`
  (Azure DevOps work items, on about a fifth). Most of the rest are plain labels such as
  `@regression` and `@flights`.

The limits and the tag rules below follow from this.

## Data model (migration 002)

New nullable columns on `cases`:

| Column | Meaning |
|---|---|
| `source_path` String(500) | path of the `.feature` file relative to the repository root, `/`-separated |
| `source_key` String(64) | `sha256(source_path \0 scenario name)`; unique per project |
| `gherkin` Text | the scenario as written, Background steps first |

- A case with `source_key` NULL is a **manual** case and behaves exactly as today.
- A case with `source_key` set is **imported**. `PATCH` rejects changes to `title`, `steps`,
  `labels` and `gherkin` with 422. `priority`, `status`, `description` and
  `automated_test_key`/`automated_name` stay editable.
- The list gets an `origin=manual|imported` filter. Search also matches the Gherkin text.

## From scenario to case

Each `Scenario`, `Example` or `Scenario Outline`, including those inside a `Rule`, becomes one case:

| Gherkin | Case |
|---|---|
| scenario name | `title`, cut to 200 characters; `source_key` uses the full name |
| Feature and Rule Background steps, then the scenario line, its steps with data tables and doc strings, and an outline's Examples | `gherkin`, re-rendered from the AST with the file's keywords and a fixed two-space indentation |
| scenario description | `description` (on create only; editable afterwards) |
| tags of the Feature, the Rule and the scenario, de-duplicated | see "Tags" |
| — | `steps` stays empty |
| — | `automated_test_key = test_key(feature name, source_path, scenario name)` when the link is import-owned (see below) |

### Tags

- `@priority:<low|medium|high|critical>` sets `priority`, and is not a label. With no priority tag,
  the case keeps its current priority (`medium` when new).
- Every other tag drops the `@`, is lower-cased, and has `:` replaced by `-`.
  For example, `@ado:81284` becomes `ado-81284`, which the later Azure DevOps slice can read.
- A tag that is still not a valid label is skipped with a warning. So is any tag past the 20th.

### The link to automated results

The formula is the one ingestion uses for Cucumber JSON: suite = feature name, class_name = `uri`,
name = scenario name. cucumber-js names each row of an outline after the outline, with any
`<placeholder>` in the name filled from that row. So:

- When an outline's name has no placeholders, every row shares one key, and the link covers all
  rows.
- When it has placeholders, the link uses the name filled from the first Examples row. The other
  rows can still be found through the test search in the editor.

**Who owns the link.** A link is import-owned when it is empty, or equals
`test_key(feature name, the case's current source_path, its automated_name)`. Create, update, move
and reactivate refresh an import-owned link to the scenario's key, and the plan counts a stale one
as an `update`. Any other link was picked by hand and is never touched. If the `Feature:` name
changes, an import-set link no longer looks import-owned and is kept (the user relinks by hand).
Unlinking an imported case by hand is undone by the next import that touches it.

It only matches when `source_path` equals the `uri` the runner reports, which is the path from the
directory cucumber-js runs in. It also only matches results uploaded as Cucumber JSON: cucumber-js
JUnit output identifies tests differently. The collector normalises a Cucumber `uri` to
`/`-separated, so results from Windows runners match too.

`test_key()` moves from `ingestion/service/ingest_service.py` into `qav_shared`. Both services
import it from there, so the formula has one definition. A contract test (see Testing) holds the
two sides together.

### Per-file and per-scenario problems

These are reported and never block the rest of the batch:

- **Syntax error:** the whole file is skipped, with the parser's line and message. A leading
  byte-order mark is dropped first, so it is not one.
- **Two scenarios with the same name in one file:** the second is skipped, since both would have
  the same `source_key`.

## API

`POST /api/v1/projects/{id}/cases/import?dry_run=true|false`

- It sits under `/cases/`, so the gateway regex already routes it. It is declared before
  `/cases/{number}`.
- Body: `{files: [{path, content}], full: false, expected_plan_hash?: string}`.
- Limits: up to 2 000 files, 256 KB per file, 10 MB of file content in total. Over any limit is
  413, and the message names the limit and its setting. Each limit is a service setting, read from
  the environment like ingestion's `MAX_RESULTS_PER_RUN`: `IMPORT_MAX_FILES`,
  `IMPORT_MAX_FILE_BYTES` and `IMPORT_MAX_TOTAL_BYTES`.
- The gateway caps every request body at 10 MB, and JSON escaping makes the body larger than the
  file content. So the import path gets its own NGINX `location`, with `client_max_body_size` set
  from `GATEWAY_IMPORT_MAX_BODY` (default `25m`, substituted by `entrypoint.sh` like
  `GATEWAY_HTTPS_PORT`). The other routes keep 10 MB.
- To raise the limits, change these variables in `.env` and restart the gateway and the
  test-management service. No code changes. The service README and `.env.example` list them.
- Paths: `\` becomes `/`, and empty and `.` segments are dropped (`tests//a.feature` and
  `./tests/./a.feature` are `tests/a.feature`). An absolute path, a drive letter, `..`, a NUL
  character in a path or content, or the same path twice is 422.
- Roles: owner, admin and member, as for `POST /cases`. Viewer is 403. A project the caller cannot
  see is 404.
- Authentication is the user's JWT. API-key access for the CLI comes with the CLI command.

### The plan

The import parses every file, then compares the scenarios with the project's imported cases:

| Action | When |
|---|---|
| `create` | the `source_key` is new |
| `update` | the key exists and the title, Gherkin, labels or priority tag changed |
| `unchanged` | the key exists and nothing changed |
| `move` | an imported case would be archived, and a new scenario with exactly the same Gherkin text (which includes the scenario's full name) appears at another path in the same batch. The case keeps its number and gets the new path and key. Matching is one-to-one; when several candidates match, none of them is treated as a move. |
| `reactivate` | the key belongs to an archived case; it returns to `draft`, and is also updated if needed |
| `archive` | an imported, non-archived case whose `source_path` is among the uploaded paths but whose scenario is gone. With `full=true`, also the cases whose path is not in the batch at all. |
| `skip` | a scenario that cannot be imported (duplicate name, or a file with a syntax error) |

Manual cases are never part of the plan. A file that fails to parse never archives its cases.

- **`dry_run=true`** returns the plan and writes nothing.
- **`dry_run=false`** rebuilds the plan and applies it in **one transaction**. If
  `expected_plan_hash` is given and differs from the rebuilt plan's hash, it is 409
  `plan_changed` and nothing is written.
- `plan_hash` is a sha256 over the plan's actions (action, path, scenario, case number), sorted.
  File order in the request does not change it. It does not cover content; the confirm re-sends
  the same files.
- Two imports racing into the same project hit the unique `source_key` index. The loser gets 409
  `import_conflict` ("another import is running, try again").

Response, 200:

```json
{
  "plan_hash": "…64 hex…",
  "summary": {"created": 12, "updated": 3, "moved": 2, "reactivated": 0,
              "archived": 1, "unchanged": 40, "skipped": 1},
  "items": [{"action": "create", "path": "tests/features/a.feature",
             "scenario": "Pay by card", "case_number": null}],
  "errors": [{"path": "tests/features/b.feature", "line": 14, "message": "…"}]
}
```

`case_number` is the existing case's number, or the new one after a real import. It is null for a
`create` in a dry run.

## Dashboard

**Entry:** an "Import from Gherkin" button on Cases, shown only to editors. It opens a page,
`cases/import`.

**Choose:** the page offers drag and drop, "Choose folder" (`webkitdirectory`) and
"Choose files".

- Only `*.feature` files are kept, read as text, with their relative paths.
- An optional **path prefix** is added in front of every path. Its hint explains that paths must
  match what the runner reports, for example `tests/` when the chosen folder is `features/`.
- A checkbox, "This is my complete features folder", off by default, sends `full=true` with the
  preview and the confirm. Its hint says what each setting does: off, the cases of a deleted or
  renamed `.feature` file are left as they are (a renamed file's scenarios are created again); on,
  they are archived and a renamed file keeps its case numbers. Changing it clears the preview.
- "Preview" calls the dry run.

**Preview:**

- Counters across the top. Each one filters the table below.
- A table of action, path, scenario and `TC-n`. Unchanged rows are hidden by default.
- File errors appear in their own block.
- "Import N changes" sends `expected_plan_hash`. It is disabled when there is nothing to change.
- On 409 `plan_changed`, the page shows the new preview with "Something changed since your
  preview".

**Result:** the page shows the summary and links to Cases filtered by `origin=imported`.

**Elsewhere:**

- Imported cases carry a small icon in the list.
- The editor of an imported case shows:
  - an "Imported from `<path>`" badge;
  - the Gherkin read-only with highlighting. A small in-house tokenizer handles keywords, tags,
    tables and doc strings; there is no new library;
  - title and labels read-only.

## Testing

Service, pytest:

- `tests/unit/test_gherkin_parse.py`, with fixtures in `tests/fixtures/`. It covers:
  - Feature and Rule Backgrounds, outlines with Examples, data tables and doc strings;
  - tag inheritance, `@priority:` and `@ado:` handling, and a Gherkin file in another language;
  - duplicate names and syntax errors with their line;
  - Gherkin re-rendering.
- `tests/integration/test_import.py` covers:
  - every plan action, `full=true`, and manual cases left alone;
  - a dry run writing nothing, and a failing apply writing nothing;
  - `plan_changed` 409, the limits (413 and 422), and roles (403 and 404);
  - read-only fields on imported cases;
  - **idempotency**: importing the same batch twice gives all `unchanged` and the same
    `plan_hash`, whatever the file order.
- `tests/unit/test_migration.py`: 002 upgrades and downgrades.
- **Contract test:** one `.feature` fixture and its Cucumber JSON result. The key that the
  collector parse plus `qav_shared.test_key` produce must equal the key the import computes.
- `shared/tests`: `test_key` moved, with its existing behaviour.

Gateway smoke: import one minimal feature (`created: 1`). A body over 10 MB on the import path
must reach the service rather than get NGINX's 413.

Dashboard, vitest:

- choose, preview and import;
- the `plan_changed` path;
- the imported editor's read-only state;
- the origin filter.

**Acceptance (manual, not committed):** dry-run a real Cucumber repository's `tests/features` with
prefix `tests/`. Expect 0 parse errors and about 1 042 scenarios. A sample of the computed
`automated_test_key`s must exist among that project's results in QA Vision. The company's files are
not copied into this repository.

## Documentation

- ADR-023 "Gherkin import: the repository owns imported cases" records field ownership, the source
  key, moves, and the plan hash.
- In the first slice's spec, "Import from Gherkin" leaves "Out of scope".
- IMPLEMENTATION_PLAN and `TODO.md` mark the slice done, and list the CLI command as next.
- The service README documents the endpoint, with a `curl` example.

## Out of scope (later slices)

- `qav-collector import-features` and API-key access to test-management. That slice also adds a
  guard: a `full=true` import that would archive more than half of the imported cases is refused
  without `--allow-mass-archive`.
- JUnit XML import.
- Reading `# Test Name:` / `# Description:` comment headers. Comments are not in the Gherkin AST.
- Showing, in the preview, which cases already match an automated result.
