# Log values follow-ups: the whole log, search by value, three review fixes — design

Status: design approved in conversation 2026-10-15; pending review of this written spec.
Builds on: `docs/superpowers/specs/2026-10-14-log-values-design.md` (ADR-032).
Blueprint: ingestion (Intelligence), dashboard (Collaboration), collector (Integrations); PostgreSQL only.
ADR-032 gains a consequences note; no new ADR.

## 1. Goal and scope

Log values (ADR-032) store each result's masked log (64 KB) and the values a project's patterns find in it.
Two things people asked for next, and three small findings from the feature's review:

1. **See the whole log** of a result, on the run page and wherever the log values already show.
2. **Find the runs** that hold a given value (the runs that touched trip 3960562).
3. Review fixes: a crashed re-scan that stays "Scanning past runs…"; the collector guessing base64 instead of
   honouring an attachment's `contentEncoding`; the masking preview answering 500 to a sample with a lone surrogate.

Not in scope: searching by a partial value, logs on the Overview or the run list, diffing two logs, values on
the run page's rows (the run page shows the log itself; values stay on the case and feature pages).

## 2. The whole log, on demand

### 2.1 Endpoint (ingestion)

`GET /api/v1/projects/{id}/runs/{run_id}/results/{result_id}/log` — every project role (READ_ROLES).

- Answers `{"log": "<masked text>" }`, or `{"log": null}` when the result has none (an older collector, no
  attachments, JUnit without `system-out`).
- 404 `"Run not found"` when the run is not the project's; 404 `"Result not found"` when the result is not in that
  run. Nothing else is read: one `SELECT log FROM test_results WHERE id = … AND run_id = …`.
- The log is stored masked and cut at upload; the endpoint returns it as stored. No `Cache-Control` beyond the
  gateway's defaults.
- The run payload (`GET …/runs/{run_id}`) never carries the log; the column stays deferred.
- `latest-results` entries gain `result_id` (the id of the result shown), so the case page and the feature cards
  can ask for that result's log. Extend, never break: nothing else in the entry changes.

### 2.2 Dashboard

One component, `LogPanel`, used in three places:

- **Run page:** a "Log" button in each result row, next to the message. Its accessible name is "Log of <test name>".
- **Test case page:** under the last-result pill, beside the "Log values" line (shown whether or not there are
  values, because a log can exist without values).
- **Feature page:** the same under each scenario card's head.

Behaviour:

- Nothing is fetched until the button is pressed. The first press fetches the log (TanStack Query, keyed by run and
  result id, kept while the page lives); the button toggles `aria-expanded`, and the text opens inline under the
  row or pill as a `<pre class="log-full">`: monospace, wrapping, the full 64 KB. "Hide log" closes it; the button
  keeps its place (as the message toggle does today).
- A "Copy log" button copies the text and says "Copied" in a polite live region (the same pattern as the value
  chips).
- `{"log": null}` shows "No log for this result." in Muted text inside the panel. A request error shows the
  usual `ErrorBanner` with a retry.
- An older server (no endpoint, 404 on a result that exists) reads as "No log for this result."; the button is
  always offered so the layout does not change with the server version.

## 3. Search runs by a log value

### 3.1 Ingestion

`GET /api/v1/projects/{id}/runs` gains two query parameters:

- `value` (1–200 characters, no NUL): only runs with at least one result whose `log_values` row has exactly this
  value. Comparison is exact and case-sensitive, as stored.
- `pattern` (the masking name format, `^[a-z][a-z0-9_]{0,31}$`): narrows `value` to that pattern. `pattern`
  without `value` is 422.

Implementation: `EXISTS (SELECT 1 FROM test_results r JOIN log_values v ON v.result_id = r.id [JOIN log_patterns p
ON p.id = v.pattern_id] WHERE r.run_id = test_runs.id AND v.value = :value [AND p.name = :pattern])`, combined
with the existing filters (branch, status, environment, dates, …) and paging. Patterns are per project and the
run is already filtered by project, so another project's values never match.

Migration **024** adds `ix_log_values_value` on `(value, pattern_id)`; `down_revision = "023"`. Nothing else
changes in the tables.

### 3.2 Dashboard

- Runs page: a "Log value" entry in the filter bar: a text field for the value and an optional pattern select
  (the project's pattern names, from `GET …/log-patterns`). In the URL as `?value=3960562&pattern=trip_id`;
  shown as a removable chip "Log value trip_id: 3960562" (or "Log value: 3960562") like the other filters;
  cleared with them.
- Each value chip on the case page and the scenario cards gains a "runs" link (accessible name "Runs with
  trip_id 3960562") to `/projects/{id}/runs?value=<encoded>&pattern=<name>`. The chip keeps its copy button and,
  when the pattern has a template, its https link.

## 4. Review fixes

### 4.1 A crashed re-scan pass

Today a pass that raises leaves `log_scan_requested > log_scan_done` with `log_scan_started_at` set, so the card
says "Scanning past runs…" and polls every 3 s until a pattern is added or the service restarts.

- `run_scan` clears `log_scan_started_at` when a pass fails (the request stays queued).
- `scan_state` reports a third state: `queued` (requested > done and no `log_scan_started_at`). `running` keeps
  its `since`; `idle` is unchanged. `LogScanOut.state` becomes `"idle" | "queued" | "running"`.
- The card shows "Scan queued; it runs when a pattern is added or the service restarts." for `queued` and polls
  every 30 s (every 3 s while `running`). Right after adding a pattern the state is `queued` for the instant
  before the background task starts; the add's refetch and the 30 s poll cover it.

### 4.2 Collector: `contentEncoding`

`_attachment_text` reads `contentEncoding` / `content_encoding` when present: `BASE64` decodes (invalid base64
or UTF-8 still never fails the parse: U+FFFD, or the text kept as it is), `IDENTITY` keeps the text as it is; any
other value is treated as absent. Without the field the current guess stays (strict base64 decode, else the text
as it is), because the classic cucumber-js/jvm JSON always base64-encodes and never writes the field.

### 4.3 Masking preview sample

`MaskingPreviewIn.sample` gets the same `mode="before"` `_replace_unstorable` validator as the log-value preview:
a NUL or a lone surrogate is replaced, never a 500 and never a 422 about the sample.

## 5. Testing

- **Ingestion:** the log endpoint (text, null, 404 run of another project, 404 result of another run, every role
  reads); `latest-results` carries `result_id`; the runs filter (`value`, `value`+`pattern`, `pattern` alone is
  422, another project's value never matches, combined with `status`/`branch`, paging); migration 024 up, down
  and up on PostgreSQL, the index in the model; `scan_state` `queued` after a failed pass and `running` during
  one; the masking preview sample with a lone surrogate (200, replaced).
- **Collector:** `contentEncoding: BASE64` decodes, `IDENTITY` keeps a base64-looking line as text, absent field
  keeps today's behaviour, `content_encoding` spelling, unknown value ignored.
- **Dashboard:** `LogPanel` (no fetch until pressed, fetch once, open/close with focus kept, copy with "Copied",
  null text, error with retry); the run page row button; the case page and feature card buttons; the Runs page
  filter (URL, chip, clearing, the pattern select from the patterns list); the chip's runs link (encoded value);
  the queued card state and its poll interval; lint, typecheck, build.
- **Gateway smoke:** `GET …/runs/{run}/results/{result}/log` through the gateway (200 with the smoke upload's log)
  and `GET …/runs?value=3960562` listing that run.

## 6. Documentation

ADR-032 (consequences: the log is readable on demand; runs searchable by value), TECHNICAL_SPECIFICATION (endpoint,
filter, index, `queued`), DESIGN (Log panel, the filter chip, the chip's runs link, the queued state), ingestion
README (endpoint, runs filter, scan states), docs/SETUP §4.10 (find the runs for a value; read the log), TODO
(the two items done), collector README (`contentEncoding`).

## 7. Delivery

One delivery on master after the full CI mirror passes, in this order inside it: migration 024 and the ingestion
endpoint and filter, the scan state and masking preview fixes, the collector fix, the dashboard, docs and smoke.
No collector release is forced by this (the `contentEncoding` fix ships with the next tag).
