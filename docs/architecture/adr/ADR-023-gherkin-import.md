# ADR-023: Gherkin import: the repository owns imported cases

Status: Accepted (2026-10-06) · Spec: `docs/superpowers/specs/2026-10-06-gherkin-import-design.md`

## Context
The `.feature` files live in the product test repositories, not in QEOS. Test management
(ADR-022) kept cases written by hand. Teams that already have hundreds of scenarios in Git do not
want to type them again, and do not want two copies that drift apart.

Automated results are identified by `test_key`: for Cucumber JSON, suite = feature name,
class_name = the result's `uri`, name = scenario name. A case can only show its latest result when
its link carries the same key.

On 2026-10-06 the user chose one endpoint for the dashboard upload now and a later
`qeos-collector import-features` CI command, with the repository as the source of truth.

## Decision
- **Field ownership.** For an imported case, title, steps, labels and Gherkin text come from the
  file and are read-only in QEOS (`PATCH` answers 422). Steps stay empty: the Gherkin text
  replaces them. Priority, status, description, suites and the
  automated-test link stay editable. A `@priority:` tag sets the priority; without one the case
  keeps its current priority.
- **`source_key`.** `sha256(source_path \0 scenario name)`, unique per project. A case with no
  `source_key` is manual and behaves as before. `source_path` is relative to the repository root and
  `/`-separated; empty and `.` segments are dropped, and an absolute path or `..` is 422.
- **Path prefix.** The dashboard has an optional path prefix that it puts in front of every path,
  so the paths match the `uri` the runner reports (for example `tests/` when the chosen folder is
  `features/`).
- **Moves are matched on the Gherkin text.** If an imported case would be archived and a new
  scenario with exactly the same Gherkin text (which includes the scenario name) appears at another
  path in the same batch, the case keeps its number and gets the new path and key. Matching is
  one-to-one; if several candidates match, none is treated as a move.
- **Status.** A case created by the import starts as `ready` (a case made in QEOS starts as
  `draft`). Later syncs never change a status set in QEOS (amended 2026-10-20).
- **Reactivation.** If the key belongs to an archived case, the case returns to `ready`, and is
  updated if needed. A scenario that disappears is archived, never deleted.
- **`plan_hash`.** The import builds a plan (create, update, unchanged, move, reactivate, archive,
  skip). A dry run returns it with `plan_hash`: a sha256 over the plan's actions (action, path,
  scenario, case number), sorted, so file order never changes it. It does not cover content; the
  confirm re-sends the same files. A confirm sends `expected_plan_hash`; if the rebuilt plan differs, it is
  409 `plan_changed` and nothing is written. The user applies exactly what they previewed.
- **One transaction.** A real import applies the whole plan or nothing. Archiving is scoped to the
  uploaded paths, so uploading one folder never archives cases from another. Only `full=true` also
  archives imported cases whose path is not in the batch. The dashboard sends `full=true` only when
  the user ticks "This is my complete features folder" (off by default); the CLI's import-features is full by
  default (`--no-full` turns it off). Manual cases are never touched, and a file
  that fails to parse never archives its cases. Two imports racing hit the unique `source_key`
  index; the loser gets 409 `import_conflict`.
- **Import-owned links.** The import sets a case's automated link to
  `test_key(feature name, source_path, scenario name)`. A link is import-owned when it is empty or
  equals `test_key(feature name, the case's current source_path, its automated_name)`; an update,
  move or reactivation refreshes an import-owned link, and the plan counts a stale one as an
  update. Any other link was picked by hand and is never touched. No column records who set it.
- **`test_key` lives in `qeos_shared`.** It moved out of ingestion's `ingest_service.py`. Ingestion
  and test-management import the same function, and a contract test (a `.feature` fixture and its
  Cucumber JSON) holds the two sides together.
- **A separate gateway body limit.** JSON escaping makes the request larger than the file content,
  so the import path has its own NGINX `location` with `GATEWAY_IMPORT_MAX_BODY` (default `25m`).
  Other routes keep 10 MB. The service limits are `IMPORT_MAX_FILES` (2 000),
  `IMPORT_MAX_FILE_BYTES` (256 KB) and `IMPORT_MAX_TOTAL_BYTES` (10 MB), all read from the
  environment.
- Parsing happens on the server with Cucumber's official parser (`gherkin-official`), one case per
  `Scenario` or `Scenario Outline`, and the Gherkin is kept as text, not converted to steps.

## Consequences
- The automated link only matches Cucumber JSON results whose `uri` equals the imported path. The
  path must be the one the runner reports, from the directory it runs in (hence the path prefix
  option). JUnit results use another identity and will not match.
- An outline whose name has `<placeholders>` links to the name filled from its first Examples row;
  the other rows are found through the test search in the editor.
- An archived case that reappears at a new path becomes a new case, not a move: moves are only
  detected against cases that would be archived in the same batch. The old case stays archived.
- When a case moves, or an outline's first Examples row changes, an import-owned link is refreshed
  to the new key; a hand-picked link is kept.
- If the `Feature:` name itself changes, the old link no longer looks import-owned, so it is kept;
  the user relinks the case by hand.
- Unlinking an imported case by hand (setting the link to null) does not stick: the next import
  that touches the case fills it again.
- With the complete-folder option off (the default), the cases of a deleted or renamed `.feature`
  file are not archived or moved, and a renamed file's scenarios are created again. Ticking the
  option archives them and keeps a renamed file's case numbers (a move).
- A `full=true` import can archive many cases at once. The dashboard discloses it before the
  confirm: the button reads "Import N changes (archives M)", and an alert appears when more than
  half of the imported cases would be archived.
- A leading byte-order mark (as Windows editors save) is dropped before parsing.
- The collector normalises a Cucumber `uri` to `/`, so results uploaded from Windows link to
  imported cases. Results uploaded from Windows before that change keep their backslash keys and
  do not link.
- A server-side mass-archive guard protects every client. With `full=true`, an import that would
  archive more than half of the live imported cases is 409 `mass_archive` (with `archived` and
  `live`) unless the body has `allow_mass_archive: true`. A dry run reports it as
  `summary.mass_archive`. The dashboard sends the flag when its alert is showing; the CLI passes
  `--allow-mass-archive`.
- API-key access for the CLI is ADR-024. JUnit import is a later slice.
- Raising a limit is an `.env` change and a restart of the gateway and the service; no code change.

## Related Decisions
- [ADR-022: Test management is its own service](ADR-022-test-management-service.md)
- [ADR-035: Repository suites](ADR-035-repository-suites.md): the suite workflows sync with the same import, in the same transaction.
