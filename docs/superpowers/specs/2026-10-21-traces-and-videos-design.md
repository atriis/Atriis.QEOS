# Traces: keep a failed test's Playwright trace in QEOS, one click from the result

Date: 2026-10-21 · Status: for approval · Scope: traces now; videos documented for later (section 8) · Follow-up of ADR-036 (step screenshots) · Decision record to write: ADR-037

## 1. Intent

A failed UI test is easiest to understand from its Playwright **trace** (every action, the DOM before and after,
console and network) or its **video**. OBT already records a trace for every failed scenario in CI
(`tests/support/world.js` starts tracing when `CI` is set, `tests/support/hooks.js` saves
`test-results/traces/<scenario>_<time>.zip` on failure) and the suite runner uploads the folder as a GitHub
artifact (`<suite_id>-traces`). To use one today, someone finds the run on GitHub, downloads the artifact, unzips it,
finds the right file and runs `npx playwright show-trace`. Nobody does that for a routine failure.

Goal: on a failed result in QEOS, **Trace** opens that test's trace in the browser, with no download and no command
line. Videos follow later (decided with the user 2026-10-21: section 8). It reuses ADR-036's storage (MinIO through ingestion), upload path and
project switch pattern.

## 2. Goals, non-goals, anti-goals

**Goals**
- Traces (`application/zip`) of a result reach QEOS from:
  - Playwright's JSON reporter (attachments named `trace` with a `path`, already parsed since 0.13.0 and skipped as
    "video or trace");
  - Cucumber JSON, through a small reference attachment the test suite adds (section 4.2), since a trace is a file on
    disk, not something cucumber-js can embed sensibly.
- The result shows a **Trace** button that opens Playwright's own trace viewer, served by QEOS from the same
  origin. The trace can also be downloaded.
- They are kept for a shorter, separate retention (default 14 days), because they are large.

**Not now**
- Videos: still skipped and counted by the collector ("video (not sent yet)"); section 8 keeps their design.

**Non-goals**
- Recording traces or videos: the test suite decides (OBT records traces on failure; videos are opt-in).
- Traces of passing tests by default: the collector sends what the report names; OBT names only failures.
- Searching inside traces, or showing trace steps in QEOS's own UI.

**Anti-goals**
- Unmasked secrets spreading quietly. A trace holds DOM snapshots and network requests and responses, so it can
  carry session cookies, tokens and personal data of test accounts; QEOS cannot mask it. Off by default, with its own
  project switch and a plain warning (section 4.6).
- Uploads that stall CI. Artifacts are large; their phase has its own time budget and never delays or fails the run
  upload.
- A trace viewer loaded from a third-party site (`trace.playwright.dev`) or any URL that works without QEOS sign-in.

## 3. Constraints

- The gateway's body limit is 10 MB and the blob location allows 6 MB (`client_max_body_size 6m`). Traces are
  typically 1-30 MB.
- Ingestion's blob PUT reads the body to check type, size and SHA-256 (ADR-036). Larger artifacts must stream.
- The dashboard reads with a Bearer JWT in memory, never a cookie (ADR-013 keeps the refresh token in an httpOnly
  cookie for `/api/v1/auth` only). Playwright's trace viewer fetches the trace by URL, so it cannot send that header.
- The collector stays standard-library only and works without these features (older QEOS, switch off).

## 4. How it works

### 4.1 Storage and limits (ingestion)

- Object key `artifacts/{project_id}/{sha256}`, same bucket, same `blobs` table with a new column `kind`
  (`screenshot` default for existing rows, `trace`; `video` is reserved for section 8). Purge deletes the `artifacts/{project_id}/` prefix too.
- `HEAD|PUT /api/v1/collect/artifacts/{sha256}` (API key, as `/collect/blobs`): `Content-Type` `application/zip`
  (the endpoint takes a list of types, so videos add theirs later); at most **100 MB**; the body is streamed to MinIO (multipart upload) while its SHA-256
  and size are computed; a mismatch with the path, or the first bytes not matching the type (ZIP `PK\x03\x04`),
  deletes the object and answers 400. 403 when the project's artifact
  switch is off or storage is not configured; 410 for a project pending deletion.
- Gateway: new location `/api/v1/collect/artifacts` with `client_max_body_size 101m`, request buffering off, its own
  rate zone (10 r/s, burst 20).
- Run upload: `ResultIn.artifacts: [{sha256, kind: trace, media_type, name?}]`, at most 5 per result; new table
  `result_artifacts` (result_id FK cascade, position, blob_id, kind, name). A reference whose blob is not stored for
  this project is dropped, as for screenshots.

### 4.2 Collector 0.14.0

- **Playwright JSON**: attachments with `contentType` `application/zip` (name `trace`) become artifacts; videos stay
  skipped and counted as today. Traces are read under the same rules as 0.13.0 screenshot files (inside the working directory, symlinks
  resolved, magic bytes) with the 100 MB cap, hashed by streaming and read again only for upload (0.13.1).
- **Cucumber JSON**: a scenario may attach a reference, media type `application/vnd.qeos.artifact+json`, content
  `{"kind": "trace", "path": "test-results/traces/x.zip"}` (`"video"` is reserved and skipped for now). The collector resolves `path` under the
  same rules. The reference is never part of the log (its media type is not a text type) nor a screenshot.
- Key check: `GET /api/v1/collect/key` gains `artifacts: true|false`; false, missing (older QEOS) or a failed check
  skips them, one line in the output.
- Upload: after screenshots and before the run, `HEAD` then `PUT` per artifact, 2 at a time, streaming the file from
  disk (no full read into memory), retries as for images; its own budget of **5 minutes**; when it runs out, the
  rest are skipped, counted, and the run goes without them. `--no-artifacts`, `QEOS_NO_ARTIFACTS=1` or
  `no-artifacts: true` in `.qeos.yml` turn it off. At most 5 artifacts per result, 500 per run.
- Output: `artifacts: N stored (X MB), M skipped` with reasons, like screenshots.

### 4.3 OBT change (a pull request in OBT, not built by QEOS)

In the After hook, right after `tracing.stop({ path: tracePath })`:

```js
this.attach(JSON.stringify({ kind: "trace", path: tracePath }), "application/vnd.qeos.artifact+json");
```

and the `qeos-sync`/upload step needs nothing new. QEOS ships the snippet in `templates/github/` and SETUP.

### 4.4 Reading and the trace viewer

- `GET /api/v1/projects/{p}/runs/{r}/results/{id}/artifacts` → `[{id, kind, media_type, name, bytes}]` (JWT, read roles).
- `GET /api/v1/projects/{p}/artifacts/{id}` → the file, streamed, `Content-Disposition: attachment` for download,
  supports `Range` (the trace viewer reads parts of the zip).
- **Viewer link.** `POST /api/v1/projects/{p}/artifacts/{id}/link` (JWT, read roles) returns a one-time URL
  `/api/v1/artifact-links/{token}`: a random token (32 bytes), stored hashed, valid **60 seconds**, usable for
  **one** full download plus Range requests within those 60 s from the same client IP, bound to that artifact and
  user. The trace viewer fetches it. No Bearer header needed, nothing reusable later, nothing guessable.
- **Self-hosted trace viewer.** The dashboard build copies Playwright's trace viewer
  (`playwright-core/lib/vite/traceViewer`, version pinned in `dashboard/package.json`) to `/trace-viewer/`, served by
  the dashboard container from the same origin. **Trace** opens
  `/trace-viewer/index.html?trace=<one-time URL>` in a new tab. No third-party site is involved.

### 4.5 Dashboard

- Run detail results table: a **Trace** button next to the camera count when present.
- Result panel on the case and feature pages: the same button next to the result pill.
- Project Settings: **Keep traces from uploads** (owner or admin, off by default), with the warning text
  of section 4.6, and **Keep them for N days** (1-90, default 14).

### 4.6 Privacy and retention

- Separate switch, off by default. The settings text says: "Traces contain page snapshots and network traffic, which
  can include cookies, tokens and personal data of your test accounts. QEOS cannot mask them. Turn this on only if
  every project reader may see that."
- Retention: the retention job deletes `result_artifacts` older than the project's artifact days (independently of
  the results, which keep their own retention), then garbage-collects unreferenced `trace` blobs after 7 days,
  as for screenshots. The export carries artifact references only.
- SECURITY.md: the switch, the one-time links (hashed, 60 s, single artifact, single user, IP bound), the trace
  viewer self-hosted.

## 5. Stages

1. **Traces, download only**: storage, upload endpoint, collector (Cucumber reference + Playwright), retention,
   settings, a **Download trace** button with "open it with `npx playwright show-trace`". Useful on its own.
2. **Trace viewer in the browser**: one-time links and the self-hosted viewer.

## 6. Things to keep in mind

- **Size.** A failing OBT nightly with 100 failed scenarios and 10 MB traces stores about 1 GB per night; 14-day
  retention keeps about 14 GB per project. The Grafana "Screenshot storage used" panel covers the bucket; rename it
  "Artifact storage used".
- **Self-hosting the trace viewer** relies on Playwright's packaged viewer working from a sub-path; its service
  worker needs the same origin. If a Playwright update breaks it, stage 1's download still works.
- **Older collectors** never send artifacts; older QEOS answers `artifacts` missing in the key check.

## 7. Calls made without the user (check these)

- Traces only for now (the user moved videos to later, section 8); viewer in stage 2.
- A separate, off-by-default switch and a separate 14-day retention for traces (videos will share them).
- 100 MB per artifact, 5 per result, 500 per run, 5-minute upload budget.
- Cucumber suites reference trace files with a small attachment instead of embedding them.
- One-time, 60-second, IP-bound links so the self-hosted trace viewer can fetch a trace without the Bearer token.
- Collector 0.14.0; ADR-037.

## 8. Later: videos (documented, not built)

Kept here so the next step starts from a design, not from scratch. Everything above is built so videos only add:

- Types: `video/webm` and `video/mp4` on the artifact endpoint (magic bytes WebM `\x1a\x45\xdf\xa3`, MP4 `ftyp` at
  offset 4), `kind: video` in `blobs`, `result_artifacts` and `ResultIn.artifacts`.
- Collector: Playwright attachments named `video`, and the Cucumber reference with `"kind": "video"`, become artifacts
  instead of being skipped.
- Dashboard: a **Video** button next to **Trace**; the video plays in the existing screenshot viewer dialog
  (`<video controls>` on a blob URL fetched with the Bearer token; over 50 MB, a one-time link instead), with Range
  requests for seeking.
- The same switch and retention as traces ("Keep traces and videos from uploads").
- Sizes: videos are typically 1-20 MB; OBT would need `recordVideo` in `world.js`, usually only for failed scenarios
  (`retain-on-failure` style), to keep storage in check.
