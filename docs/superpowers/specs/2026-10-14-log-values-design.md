# Log values: patterns captured from test logs — design

Status: sections 1–3 approved in conversation 2026-10-14; pending review of this written spec.
Blueprint: collector (Integrations), ingestion (Intelligence), dashboard (Collaboration); PostgreSQL only.
New ADR-032.

## 1. Goal and scope

People want to see, on every run of a test case, values the test logged, for example the trip a booking
scenario created: `INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"`.

- A project defines **log-value patterns** in Settings, next to Masking, as regular expressions (the same
  form as masking patterns, for uniformity).
- Each test result's log is captured, masked and stored; the patterns are applied to it.
- Every Last runs bar, whatever the run's status, shows in its tooltip the values found in that run, one
  line per pattern, values comma-separated. The test case page and the feature page's scenario cards show
  them for the run shown.
- The same value may appear in several scenarios (e.g. one trip used by two scenarios); values are per
  result, so each scenario shows it.

Not in scope: searching runs by value (TODO, later), showing the whole log in QEOS (the stored log makes it
possible later), log values on the run detail page, a helper that builds a pattern from a clicked value.

## 2. Getting the logs in

### 2.1 Test repository (Atriis.Test.Automation.OBT)

Today `src/utils/logger.js` writes only to the console, so the Cucumber JSON report has no log lines and
console output cannot be tied to a scenario reliably (lines interleave; parallel runs).

- A `Before` hook stores the running scenario's `this.log` where the logger can reach it (one module-level
  "current attach" function, cleared in `After`).
- `logger._log` also passes each line it prints, in the pretty one-line form without colour codes, to that
  function. Console output is unchanged. With no current scenario (start-up, hooks outside a scenario) it
  only prints.
- Result: each step in `test-results/cucumber-report.json` carries its log lines as text attachments.

### 2.2 Collector 0.9.0

- Each result gains `log` (string): for Cucumber JSON, the scenario's text attachments (`embeddings` /
  attachments with media type `text/x.cucumber.log+plain` or `text/plain`, decoded from base64 when so
  encoded), in step order, Background steps included, joined by newlines; for JUnit, the test case's
  `system-out`. Images and other binary attachments are never included.
- `log` is cut to 64 KB of UTF-8 (the same cut as `details`), keeping the start.
- Left out when there is no text. Other formats: no `log`.
- An older QEOS that rejects `log` (422 naming the field) gets the upload once more without it, as for
  `failed_step` details.
- Release `collector-v0.9.0`; the floating `collector-v0` follows it.

### 2.3 Ingestion on upload

1. `ResultIn.log`: optional string; the service truncates at 64 KB like `details`, never rejects.
2. The log is masked with the built-in and the project's masking patterns, like `message` and `details`.
3. Stored in `test_results.log` (Text, nullable).
4. The project's log-value patterns are applied to the masked log; values are stored in `log_values`.

The re-mask job (`jobs/remask.py`) re-masks `log` too, then re-applies the log-value patterns to the results
it changed. The project data export includes `log` and the values. Retention deletes them with their
results.

## 3. Settings: log-value patterns

### 3.1 Patterns

- Table `log_patterns (id, project_id, name, pattern, created_by_user_id, created_at)`, unique
  `(project_id, name)`.
- Name: the masking name format (`^[a-z][a-z0-9_]{0,31}$`), shown as the label in tooltips.
- Pattern: a regular expression, at most 256 characters, compiled with RE2 (linear time, as masking), with
  **at most one capture group**: with a group, the value is the group's text; without, the whole match.
- At most 20 patterns per project.
- No edit (as masking): delete and add again.

### 3.2 Endpoints (ingestion, mounted like masking)

- `GET /api/v1/projects/{id}/log-patterns`: any project member (READ_ROLES).
- `POST …/log-patterns`: owner, admin, member (EDIT_ROLES). 201 with the pattern; 422 invalid name,
  invalid or too long regex, more than one group, limit reached; 409 duplicate name.
- `DELETE …/log-patterns/{pattern_id}`: EDIT_ROLES; 204; its values are deleted with it.
- `POST …/log-patterns/preview`: EDIT_ROLES. Body `{name, pattern, sample}` (sample up to 64 KB). Returns the
  sample as it would be stored (masked) and the values this pattern finds in it. Nothing is saved.
- Gateway: `/projects/{id}/…` already routes to ingestion for the existing prefixes; `log-patterns` is
  added to the ingestion location list (and to `scripts/check_architecture_docs.py` routes if it tracks
  them).

### 3.3 Values

- Table `log_values (id, result_id, pattern_id, position, value)`: one row per distinct value per pattern per
  result, `position` = order of first appearance in the log; value cut to 200 characters; at most 20 values
  per pattern per result. Foreign keys cascade on result and pattern delete. Index `(result_id)`.
- Values come from the masked log: a value hidden by masking cannot be captured (stated in the help).

### 3.4 Re-scan

- Adding a pattern queues a re-scan of the project: stored logs of the last 90 days are matched against
  the new pattern in batches inside ingestion-service (like the retention job); values are inserted
  idempotently. One job per project at a time: patterns added while a scan runs join the same pass.
- `GET …/log-patterns` reports `scan: {"state": "idle" | "running", "since": <started_at or null>}` so the
  card can show "Scanning past runs…".
- Logs older than 90 days get no values for a new pattern.
- Uploads during a scan are matched with all current patterns at upload.

Migration **023** (ingestion): `test_results.log`, `log_patterns`, `log_values`, the scan state (one row per
project, or a column on an existing per-project table if one exists).

## 4. Dashboard

### 4.1 Settings card "Log values" (after Masking)

- List: name and pattern, Delete (with confirm, as masking).
- Add form: name, regular expression, a **"?"** button opening a popover with the rule (one group = that
  part; no group = whole match; values come from the masked log) and three clickable examples that fill
  the field: `tripId="(\d+)"`, `routeKey="([^"]+)"`, `status="([^"]+)"`.
- **Preview**: paste log lines; shows the values found as `name: value` chips and their count, from
  `…/preview`. Errors from the server shown at the field (422 text).
- While a re-scan runs: "Scanning past runs…" under the list.
- Viewers see the list without the form, as masking.

### 4.2 Last runs bar tooltip

- `run-strip` entries gain `values: [{"name": "trip_id", "values": ["3960562"]}, …]` (patterns in name
  order, values in log order; empty list when none).
- The bar's tooltip (`title`) and its accessible label: today's line, then one line per pattern with values,
  values comma-separated:
  ```
  Run #812, 14 Oct 2026: passed
  trip_id: 3960562, 3960563
  route_key: wasToBos
  ```
  At most 5 values per pattern, then "+N more". For every bar, whatever the status.
- Feature rows (one bar = several scenarios): per run, the values of all its scenarios, merged per pattern,
  duplicates removed.

### 4.3 Test case page and feature page cards

- `latest-results` gains the same `values` for the result it returns (latest, or the run opened from a bar).
- Under the last-result pill: "Log values" line, `trip_id: 3960562 · route_key: wasToBos` (values within a
  pattern comma-separated), only when there are values. Same line under each scenario card's pill.

## 5. Testing

- **Test repo:** the logger attaches to the current scenario and still prints; nothing attached outside a
  scenario.
- **Collector:** `log` from Cucumber text attachments (plain and base64), step order, Background included,
  binary skipped, 64 KB cut, absent when empty; JUnit `system-out`; retry without `log` on a 422.
- **Ingestion:** `log` masked and stored; values extracted with group / without group; distinct and ordered;
  200-character and 20-value caps; pattern validation (name, length, RE2, groups, limit, duplicate); preview;
  delete cascades; re-scan fills past results within 90 days only, idempotent, one job per project; remask
  re-applies; export includes; retention deletes; `run-strip` and `latest-results` values; migration 023 up
  and down on PostgreSQL.
- **Dashboard:** settings card (list, add, help popover examples, preview chips, errors, scanning state,
  viewer read-only); tooltip lines for passed, failed, skipped bars, accessible label, "+N more"; feature
  row merge; case page and feature card line; lint, typecheck, build.
- **Gateway smoke:** `GET …/log-patterns` routed (401 without a token).

## 6. Documentation

ADR-032. SETUP (Settings → Log values; the test-repo logger change; collector 0.9.0), SECURITY (logs are
masked before storage; retention), PRODUCT, TODO (search runs by value; show the log), TECHNICAL_SPECIFICATION
(payload `log`, endpoints, tables), DESIGN (card, tooltip, case-page line), collector and ingestion READMEs.

## 7. Delivery

Each step lands on master after the full CI mirror passes.

1. **Ingestion:** migration 023, `log` upload/mask/store, patterns and endpoints, extraction, re-scan,
   remask/export/retention, `run-strip` and `latest-results` values, smoke, docs.
2. **Collector 0.9.0** and its release.
3. **Dashboard:** settings card, tooltip, case and feature page lines, docs.
4. **Test repo** (Atriis.Test.Automation.OBT): the logger change, on its own repository and branch rules.
