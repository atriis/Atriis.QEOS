# Failed step on scenarios, feature page as scenario cards — design

Status: approved in conversation 2026-10-13 (sections 1–2 and both self-review amendments), pending review of
this written spec.
Blueprint: dashboard (Collaboration), ingestion (Intelligence/QIP), collector (Integrations); PostgreSQL only.

## 1. Goal and scope

Two dashboard changes, decided with the user:

- **Feature page (layout A):** instead of one numbered block with the whole `.feature` file, the page shows
  the feature's header, its Background once, then **one card per scenario** laid out like the scenario page.
- **Failed step:** on the scenario page and on every scenario card, the step that failed in the scenario's
  **latest result on any branch** is shown in red; hovering or focusing it shows the error, branch,
  environment, time and a link to the run.

How the failed step is found (approach 3): the collector records the failing step's **line and text**; the
dashboard uses the line when the text at that line still matches, and falls back to matching the text.
Results stored before the collector change get the text fallback from data already stored.

Not in scope: other example rows of a Scenario Outline (a case is linked to its first example row's results,
as everywhere in QEOS today); a branch picker; status on the case list.

## 2. Collector (0.6.0)

For a **failed** Cucumber scenario, each result gains

```json
"failed_step": {"text": "When I search Lisbon", "line": 14}
```

- `text`: the step's keyword and text as Cucumber reports it, cut to 1000 characters.
- `line`: the step's line in the `.feature` file (Cucumber JSON's `step.line`). For an outline it is the
  template step's line; for a Background step, the Background step's line.
- Left out when the scenario passed or was skipped, when no step failed, and for formats without steps
  (JUnit, Playwright, …). A missing or non-integer line leaves `line` out and keeps `text`.
- `details` keeps its current content (step text, then the error), so nothing reading it changes.

Release `collector-v0.6.0`; the floating `collector-v0` follows it.

## 3. Server (ingestion-service)

### 3.1 Data (migration 021, or the next free number when implemented)

`test_results` gains `failed_step_text` (String(1000), nullable) and `failed_step_line` (Integer, nullable,
check `> 0`). Existing rows stay null.

### 3.2 Upload

- `ResultIn.failed_step`: optional `{text: 1–1000 chars, line: optional int 1–1_000_000}`; extra fields 422.
- `failed_step_text` is **masked** with the built-in and the project's patterns, like `message` and
  `details` (step text can hold literal accounts or tokens).
- The re-mask job (`jobs/remask.py`) re-masks `failed_step_text` too.
- The project data export includes both new fields.

### 3.3 `POST /api/v1/projects/{id}/analytics/latest-results`

Body `{"keys": [<test_key>, …]}`, 1–500 distinct keys. Any project member (READ_ROLES). Answer:

```json
{"results": {"<test_key>": {"status": "failed", "run_id": 812, "branch": "main", "environment": "staging",
  "started_at": "…", "message": "expected 1 but was 0",
  "failed_step": {"text": "When I search Lisbon", "line": 14}}}}
```

- One entry per key that has at least one result: its latest result on **any branch** (latest run
  `started_at`, ties by run id). Keys without results are absent.
- `failed_step` is present only for `failed` / `errored` results. From the new columns when set; otherwise,
  for older results, `text` = the first line of `details` **when it differs from the first line of
  `message`** (then it is the step the collector wrote there), `line` absent; otherwise `failed_step` absent.
- Reuses the "latest result per test" query behind `analytics/latest-keys` rather than a second one.
- Gateway: no change (`/projects/{id}/analytics/…` already routes to ingestion).

## 4. Dashboard

### 4.1 `locateFailedStep(source, scenarioLine, failedStep) → stepIndex | null`

A pure function (`src/lib/failedStep.ts`):

1. From `source` (the `.feature` text) take, in order, the steps of the Background that applies to the
   scenario (feature- or rule-level) and the steps of the scenario starting at `scenarioLine`, each with its
   line. Data-table rows and `"""`/```` ``` ```` doc strings are not steps. Reuses `gherkinTokens.ts`.
2. If `failedStep.line` is one of those lines **and** that step's text matches `failedStep.text`, return its
   index.
3. Otherwise return the index of the first step whose text matches.
4. Otherwise `null` (nothing turns red).

Matching ignores surrounding whitespace; in the case's step, each `<placeholder>` matches any non-empty text
(`When I search <city>` matches `When I search Lisbon`).

Without a source (a case with no `source_path`, e.g. written by hand and linked to a test), the same
matching runs over the case's own Gherkin with text only.

The index maps onto the displayed Gherkin, which lists the Background steps, then the scenario's steps, in
that order (test-management's render).

### 4.2 Scenario page

- Latest result from `latest-results` for the case's `automated_test_key`; the source from the existing
  feature endpoint for `source_path`.
- Status pill above the Gherkin: passed / failed / errored / skipped / no runs yet, with the time.
- The failed step: red background **and** a "failed" marker (not colour alone).
- Tooltip on hover **and keyboard focus** (the step is focusable when it carries one): error message,
  branch, environment, time, "Open run" link. Escape closes it.

### 4.3 Feature page (layout A)

- Header: feature name, description, path, and counts of scenarios by last status.
- The Background once.
- One card per scenario in file order: case key and title (link to the case), status pill, the scenario's
  Gherkin with the failed step and tooltip as in 4.2.
- One `latest-results` request for all the feature's cases, in batches of 500.
- The existing "Scenarios not found in the file" card stays.

The layout is checked with ui-ux-pro-max before it is built; existing CSS tokens only.

## 5. Testing

- **Collector:** `failed_step` for a failed step (text and line), an outline step (template line), a
  Background step, a passed or skipped scenario (absent), a missing line, text over 1000 characters, JUnit
  (absent).
- **Ingestion:** schema (valid, too long, line 0, extra field); masking of `failed_step_text`; re-mask;
  export; `latest-results`: latest on any branch, keys without results absent, the old-row fallback (differs
  / same as message / no details), passed results without `failed_step`, 500-key limit, roles; migration.
- **Dashboard:** `locateFailedStep` (by line, stale line falls back to text, text only, outline placeholder,
  Background step, data table and doc string skipped, no match, no source); scenario page and feature page
  components (status pill, red step, tooltip on hover and focus, links, batching); lint, typecheck, build.

## 6. Documentation

TECHNICAL_SPECIFICATION (payload field, endpoint), ingestion README, collector README (`failed_step`),
SETUP (what the red step means and that line accuracy needs collector 0.6.0), PRODUCT, TODO.

## 7. Delivery

Each step lands on master after the full CI mirror passes.

1. **Server:** migration, upload, masking, re-mask, export, `latest-results`. Existing history gets
   text-matched red steps as soon as the dashboard ships.
2. **Collector 0.6.0** and its release.
3. **Dashboard** and docs.
