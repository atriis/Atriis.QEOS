# ADR-032: Log values — patterns a project defines, applied to each result's masked log, shown on every run

Status: Accepted (2026-10-14) · Spec: `docs/superpowers/specs/2026-10-14-log-values-design.md`

## Context
People want to see, on every run of a test case, values the test logged, such as the trip a booking scenario created
(`INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"`). Console output cannot be tied to a
scenario (lines interleave, runs are parallel), and the Cucumber report carried no log lines.

## Decision
- **The log travels with the result.** The test repository attaches each logged line to the running scenario; the
  collector (0.9.0) sends each result's `log` (Cucumber text attachments in step order, JUnit `system-out`), cut to
  64 KB. Other formats send none.
- **Mask first, then capture.** Ingestion masks the log with the built-in and the project's masking patterns, cuts it
  to 64 KB and stores it in `test_results.log` (migration 023, deferred so run pages never load it). Values are read
  from the masked log only; a value touching a masking marker is never captured.
- **Patterns are regular expressions, like masking patterns.** `log_patterns` (≤ 20 per project, name
  `^[a-z][a-z0-9_]{0,31}$`, ≤ 256 characters, RE2, at most one capture group, optional https `link_template` with
  `{value}` once). `log_values` holds one row per distinct value per pattern per result (≤ 20, cut to 200
  characters, ordered by first appearance); rows cascade with their result and their pattern.
- **Past runs are re-scanned.** Adding a pattern bumps a counter on `collection_settings`; a scan of the last 90
  days runs after the response, in batches, under a per-project PostgreSQL advisory lock (one scan per project),
  replacing values idempotently; patterns added meanwhile make it pass again; a queued scan is resumed when
  ingestion-service starts.
- **Read paths extend, never break.** `run-strip` entries and `latest-results` entries gain `values`; the dashboard
  shows them in the Last runs tooltips (text only) and under the last-result pills (copyable, linked when the pattern
  has a template; the dashboard URL-encodes the value and checks the template again).

## Consequences
- Logs are stored data: masked before storage, deleted by retention with their results, included in the export.
- Values hidden by masking cannot be captured (said in the Settings help).
- Logs older than 90 days get no values for a new pattern; a log over 64 KB loses its end, and a pattern stops
  reading a log after 1,000 matches.
- Older collectors send no `log`; collector 0.9.0 against an older platform retries once without it.
- Not done: searching runs by value, showing the whole log, values on the run page.
