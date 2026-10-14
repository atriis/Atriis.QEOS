# Failed steps across test cases — design

Status: approved in conversation 2026-10-14 (where it shows: option A; a step is its step definition, so the
same step with other parameters is one step and different errors are listed inside it; the five self-review
additions), pending review of this written spec.
Blueprint: collector (Integrations), ingestion (Intelligence/QIP), dashboard (Collaboration); PostgreSQL only.
Builds on the failed step (spec 2026-10-13 `failed-step-and-feature-layout`).

## 1. Goal and scope

When a Cucumber step fails, answer two questions:

1. **How wide:** in this run, on how many test cases did the same step fail, and with which errors?
   A shared step (a login or Background step) breaking in many cases is one problem, not many.
2. **Since when:** since which run has this step been failing, and when did it last pass?

"The same step" means the same **step definition** (the code that runs it). `When I search Lisbon` and
`When I search Porto` are one step with different parameters; if Porto fails with "Invalid city" and Lisbon
with a timeout, the step shows both errors.

Not in scope: formats without steps (JUnit, pytest, Playwright): they have no failed step; notifications and
the weekly summary; other example rows of a Scenario Outline beyond what is already stored (a case links to
its first row's results, as everywhere in QEOS).

## 2. Collector (0.8.0)

For a failed Cucumber scenario, `failed_step` gains two optional fields:

```json
"failed_step": {"text": "When I search Lisbon", "line": 14,
                "definition": "features/step_definitions/search.js:12",
                "pattern": "When I search {…}"}
```

- `definition`: the failed step's `match.location` from the Cucumber JSON (cucumber-js, cucumber-jvm and Ruby
  all report it), cut to 500 characters. Left out when the step has no match (undefined step) or no location.
- `pattern`: the step text with each `match.arguments` value (by its `offset` and `val`) replaced by `{…}`,
  keyword included, cut to 1000 characters. When the arguments are missing or their offsets do not fit the text,
  `pattern` is the text itself.
- **Older servers.** Today's server forbids unknown fields in `failed_step` (422). When an upload is refused with
  a 422 whose error names `failed_step`, the collector sends it **once more without `definition` and `pattern`**
  and logs one line saying the server is older than this collector. Nothing else is retried.

Release `collector-v0.8.0`; the floating `collector-v0` follows it.

## 3. QEOS

### 3.1 Ingestion and storage
- `FailedStepIn` accepts `definition` (1-500) and `pattern` (1-1000), both free text replaced, never rejected,
  and from now on **ignores** unknown fields instead of forbidding them (forward compatibility).
- Migration `022`: `test_results.failed_step_definition` (VARCHAR 500) and `failed_step_pattern`
  (VARCHAR 1000), nullable; index on `(failed_step_definition)` where not null.
- Both are **masked** like `failed_step_text` (secrets and personal data), and re-masked by the remask job.

### 3.2 Step identity and error grouping
- **Step key:** `definition` when present; otherwise the exact step text (case-insensitive, spaces collapsed).
  Results stored before collector 0.8.0 therefore group by text: outline rows with other values stay separate
  until the team updates the collector. The answer says which key it used (`"by": "definition" | "text"`).
- **Shown as:** the `pattern` (most frequent in the group), else the text.
- **Error groups:** inside a step, failures group by the error's **shape**: the first line of the message with
  quoted values, numbers (durations, ids, counts), UUIDs and long hex strings replaced by `…`. Each group keeps one
  real example message.

### 3.3 `GET /api/v1/projects/{id}/runs/{run_id}/failed-steps`
Every project role (as the run endpoints); a run of another project is 404. Answer:

```json
{"steps": [{
  "key": "…", "by": "definition", "pattern": "When I search {…}", "definition": "…search.js:12",
  "cases": 12,
  "errors": [{"shape": "Invalid city '…'", "example": "Invalid city 'Lisb0n'", "cases": 3,
              "tests": [{"test_key": "…", "name": "…", "text": "When I search Lisb0n"}]}],
  "since": {"run_id": 430, "started_at": "…", "runs": 5, "capped": false},
  "last_passed": {"run_id": 429, "started_at": "…"}
}]}
```

- `cases`: distinct tests of the run that failed at this step; steps sorted by `cases`, then pattern.
- `tests` per error group: at most 50, with `"more": n` beyond.
- **`since`:** walk back through earlier runs (by start time) of this project **on the same branch as the run**
  (every branch when the run has no branch; user decision 2026-10-14) that contain any of the step's
  failing tests in this run. The streak continues while at least one of them failed at this step key, and stops
  at the first run where none did. `since` is the oldest run of the streak, `runs` its length including this run.
  The walk covers at most **50 runs or 90 days**; past that `capped: true` ("failing for more than 50 runs").
- **`last_passed`:** the run that stopped the streak when one of those tests passed in it; absent when the
  streak was stopped by a failure elsewhere, or capped.
- `impact-subset` runs count like any run (they ran the tests).

### 3.4 Latest results
`latest-results` (and its `run_id` form) gains, on a result with a failed step, `failed_step.definition`,
`failed_step.pattern` and `failed_step.key`, so the dashboard can link a tooltip to its row on the run page.

## 4. Dashboard

### 4.1 Run page: "Failed steps"
A section under the run's results, shown when the run has a failed step:
- One row per step, sorted by test cases: the pattern in mono, "failed in 12 test cases", then
  "failing since run #430, 14 Oct (5 runs) · last passed in run #429" (or "new in this run" when `runs` is 1,
  or "failing for more than 50 runs").
- A row is a disclosure (`aria-expanded`): it lists the error groups (shape as heading, its count, the example
  message) and under each the test cases with the text they ran (`When I search Lisb0n`), each linking to the
  case as of this run (`cases/N?run=…`) when the test is linked to a case, else to its history.
- Each row has an anchor (`#step-<key>`), so links can open it expanded.
- A step grouped by text says so in muted text: "Grouped by step text: update the collector to 0.8.0 to group
  parameter variations."

### 4.2 Failed-step tooltip (case and feature pages)
Under the error: "Also failed in 11 other test cases in this run · failing since run #430" (or "Only this test
case · new in this run"), linking to the step's row on the run page. Loaded with the tooltip's run (one request
per page, shared by every card).

## 5. Testing

- Collector: `definition` and `pattern` from cucumber-js, cucumber-jvm and Ruby JSON; no match, no arguments,
  bad offsets; the 422 retry without the fields (once, logged) and no retry on other 422s.
- Ingestion: fields stored and masked, remask; unknown fields ignored; migration; grouping by definition and by
  text; error shapes (quoted values, numbers, UUIDs, hex); `since` across runs (streak, stop on pass, stop on
  other failure, cap at 50 runs and at 90 days); `last_passed`; 404 for another project; role access.
- Dashboard: the section (sort, disclosure, anchors, text-grouped note, links), the tooltip line.
- Smoke: an upload with `definition`, then `failed-steps` for its run.

## 6. Documentation

Collector README (the two fields, the retry), ingestion README (`failed-steps`, `latest-results` additions,
storage), DESIGN.md (Failed steps section, tooltip line), PRODUCT.md, README.md (features), TECHNICAL_SPECIFICATION,
SECURITY.md (the new masked columns), TODO.md.

## 7. Delivery

Three phases, each ending in a gate (all suites, smoke) and a push to master:

1. QEOS: accept and store the fields (migration, masking, ignore unknown fields), `latest-results` additions.
   Ships first, so collector 0.8.0 never meets a server that refuses it without the retry.
2. Collector 0.8.0: the fields and the retry; release.
3. QEOS: `failed-steps` endpoint, run page section, tooltip line; docs.
