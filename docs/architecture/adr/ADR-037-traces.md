# ADR-037: Playwright traces kept in artifact storage, with their own switch

Status: Accepted (2026-10-21) · Spec: `docs/superpowers/specs/2026-10-21-traces-and-videos-design.md`

## Context

A failed browser test is hard to debug from a message and one screenshot. Playwright's trace (a ZIP with page
snapshots, network calls and the action list) answers most questions, but it lives only in the CI job's artifacts,
which expire and need a GitHub sign-in. ADR-036 put MinIO behind ingestion for step screenshots; traces can use it.

## Decision

- **Same store, new prefix.** A trace is `artifacts/{project_id}/{sha256}`, content-addressed per project like a
  screenshot. `blobs.kind` (`screenshot` or `trace`, migration 027) tells them apart; `result_artifacts` links a
  result to at most 5 traces.
- **Own upload route.** `HEAD|PUT /api/v1/collect/artifacts/{sha256}`, `application/zip` only, first bytes
  `PK\x03\x04`, at most 100 MB. The body streams to a temporary object, is checked (size, magic, SHA-256), then
  copied to its final key. The gateway streams it unbuffered with a 101 MB limit.
- **Separate switch and retention.** `keep_traces` (off by default) and `trace_days` (1 to 90, default 14) sit next
  to `keep_screenshots` in the project's collection settings. A trace expires after `trace_days` from the run's
  start, whatever the results' retention. An unreferenced trace is deleted after 7 days.
- **Collector 0.14.0 reads references, not bytes.** It finds traces in Playwright's JSON (zip attachments) and in
  Cucumber reports (`application/vnd.qeos.artifact+json`, `{"kind": "trace", "path": ...}`), only inside the
  working directory, and hashes and streams them only when the key check says `artifacts: true`.
  `--no-artifacts` turns it off for a run.
- **Stage 1 is a download.** Run results and the case and feature panels get a Trace button; the user opens the file
  with `npx playwright show-trace`. The viewer in the browser is stage 2. Videos come later (design section 8).

## Consequences

- **Privacy.** A trace holds page snapshots and network traffic: cookies, tokens and personal data of test accounts.
  QEOS cannot mask it. The switch is off by default and its text says so; the read is streamed as a download with
  `Cache-Control: private, no-store`, for project readers only.
- **Size.** Traces are far larger than images. Storage grows faster; the 14-day default and the per-run limits
  (5 per result, 500 per run, 300 s and 2 at a time in the collector) keep it bounded. The Grafana panel is now
  "Artifact storage used".
- A project purge deletes `artifacts/{project_id}/`; the export names traces but never carries the files.
- The VM backup of the MinIO volume now holds traces too.
- Stage 2 will serve Playwright's trace viewer from QEOS's own origin, opened by one-time links, so no trace
  leaves the platform.
