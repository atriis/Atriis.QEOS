# Step screenshots: show the screenshots a test took, on the step that took them

Date: 2026-10-19 · Status: shipped 2026-10-20 (approved 2026-10-19) · Decision record: ADR-036

## 1. Intent

The test repository (Atriis.Test.Automation.OBT, "OBT") already takes a screenshot at the end of every
scenario (`tests/support/hooks.js` `After` hook, `this.attach(screenshot, "image/png")`). The image lands in
the Cucumber JSON report, and QEOS drops it: the collector reads text attachments only.

The user wants a small screenshot button on each step of a result that has a screenshot:

- if the tests take a screenshot on every step, every step shows the button;
- if they take one only at the end (today), only that step shows it;
- if they take none, nothing changes.

Why: when a scenario fails, the person reading the result in QEOS wants to see what the page looked like
at that step, without downloading CI artifacts or re-running the test.

## 2. Decisions taken with the user

- The button is **driven by the data**: shown on a step only when that step has at least one image. There
  is no "screenshot mode" setting in QEOS; the test repository decides how often to capture.
- A screenshot taken in an **After hook** (scenario level) is shown on the **last step that ran** (the
  failed step when the scenario failed), labelled "End of scenario". A Before-hook image goes on the
  first step, labelled "Start of scenario". So today's OBT screenshots appear with no change to OBT.
- Several images on one step: one button with a count; the viewer pages through them.
- The project export carries **screenshot references only** (step, type, size, sha256), not the images.
- Images are stored in **artifact storage (MinIO, S3-compatible)**. This is the blueprint's adoption
  trigger for MinIO ("Artifacts feature (screenshots/videos/traces) starts"), so this feature adopts it.

## 3. Goals, non-goals, anti-goals

Goals:

- Cucumber JSON image attachments (`image/png`, `image/jpeg`, `image/webp`) reach QEOS with the step
  they belong to.
- The test case page and feature page (Gherkin view, latest result or "as of run") show a camera button
  on each Gherkin line that has images.
- The run detail page shows, per result row, a camera count that opens the same viewer, grouped by step.
- Images follow the same retention, legal hold and project purge as the results they belong to.

Non-goals (this version):

- Playwright JSON attachments (they are file paths on the CI disk, and QEOS has no per-step data for
  Playwright). TODO.
- Videos and traces. The storage built here is reused for them later.
- Masking inside images (no OCR). See anti-goals and section 6.
- Changing OBT. An optional `AfterStep` hook is described in section 5.6 as guidance only.

Anti-goals (failure even if it works):

- A run upload that fails, or gets slower in a way CI notices, because of screenshots. Images are best
  effort: any image problem is a warning, never a failed upload.
- Images readable by anyone who is not a reader of the project, or reachable by a guessable URL.
- Storage that grows without bound: images must be deleted with their results.
- A dashboard page that downloads every image up front.

## 4. Constraints

- Gateway body limit is 10 MB (`gateway/nginx.conf.template:14`); the collector already splits run
  payloads at 9 MB. Images cannot travel inside the run JSON.
- `ResultIn` and `RunUpload` use `extra="forbid"`; a new field needs the collector's 422 downgrade path
  (`upload.py` `_downgrade`).
- `/api/v1/collect` is rate limited to 10 r/s, burst 20. Hundreds of image uploads need their own limit.
- The dashboard holds the access token in memory and sends it as a Bearer header. A plain `<img src>`
  cannot send it.
- QEOS stores no step list today. The only step-level data is the stopped-at step (`failed_step_*`). The
  dashboard finds a step by matching text and line against the case's Gherkin (`locateFailedStep`).
- Collector: standard library only (no boto3, no requests).
- Production runs on one VM with Docker Compose (ADR-019). Backups must cover the new volume.

## 5. How it works

### 5.1 Storage (new: MinIO)

- New compose service `minio` (pinned image digest) in `docker-compose.yml` and
  `deploy/docker-compose.prod.yml`, volume `qeos_minio_data`, not published outside the Docker network.
  A one-shot `minio-init` creates the bucket `qeos-artifacts` (private, no public policy).
- Only ingestion-service talks to it, through an S3-compatible client (`boto3` or `minio` Python
  package, builder's choice) configured by `ARTIFACTS_S3_ENDPOINT`, `ARTIFACTS_S3_BUCKET`,
  `ARTIFACTS_S3_ACCESS_KEY`, `ARTIFACTS_S3_SECRET_KEY`. Any S3 service can replace MinIO later.
- If the variables are not set, screenshots are off: the key check reports `screenshots: false`, the
  blob PUT answers 403, and the collector skips images. QEOS keeps working without object storage.
- Object key: `screenshots/{project_id}/{sha256}`. Content-addressed per project, so the same image
  uploaded twice is stored once and a retry is free.

### 5.2 Collector 0.11.0

Parsing (`formats.py`):

- For each Cucumber step (and cucumber-jvm `before`/`after` hook entries), collect attachments whose
  media type is `image/png`, `image/jpeg` or `image/webp` (all three names: `embeddings`/`attachments`,
  `mime_type`/`media_type`/`mediaType`; base64 unless `contentEncoding` is `IDENTITY`).
- Each image gets a step reference:
  - an image on a real step: that step's `{text, line}` (same text/line rules as `failed_step`);
  - an image on an After hook (cucumber-js `hidden` hook step with keyword `After`, or cucumber-jvm
    `after`): the last step whose status is not `skipped`, or the last step if all were skipped,
    with `hook: "after"`;
  - an image on a Before hook: the first step, with `hook: "before"`.
- "Last step that ran" and "first step" count real steps only: cucumber-js hook entries (`hidden: true`,
  keyword `Before`/`After`) sit in the same `steps` list and are skipped when picking the step.
- Limits: images over 5 MB are skipped with a warning; at most 50 images per result and 5,000 per run
  (the rest skipped, one warning with the count). Background steps keep their own line numbers.

Upload (`upload.py`), before the run POST:

1. Capability: the existing key check `GET /api/v1/collect/key` gains a field `screenshots: true|false`
   (true when storage is configured and the project setting is on). Missing field (older QEOS), false,
   or a failed key check: skip images, one line in the output, send the run without `screenshots`.
   A HEAD response has no body, so this is the only "off" signal.
2. For each distinct image (by sha256): `HEAD /api/v1/collect/blobs/{sha256}`. 200: already stored,
   skip. 404: upload it.
3. `PUT /api/v1/collect/blobs/{sha256}` with the raw bytes and `Content-Type`. Up to 4 in parallel
   (`concurrent.futures`, standard library). Retries on 429 and 5xx, but the whole image phase has its
   own budget of 120 seconds; when it runs out, the remaining images are skipped. A connection error on
   the first request skips all images at once.
4. A failed or skipped image is left out of the run payload and counted in one warning. The run upload
   still happens.
5. Spool (`spool.py`): parts resent on a later invocation keep their `screenshots`; references whose
   blob was cleaned up in the meantime are dropped by ingestion (see Cleanup). Images are not spooled.

Payload: each result gains `screenshots: [{sha256, media_type, step_text, step_line, hook?}]` in step
order. On a 422 the downgrade removes `screenshots` too.

Flag `--no-screenshots` (env `QEOS_NO_SCREENSHOTS=1`) skips all of this.

### 5.3 Ingestion

Blob endpoints (API key auth, same as `/collect/runs`):

- `HEAD|PUT /api/v1/collect/blobs/{sha256}`. PUT checks: body ≤ 5 MB, `Content-Type` in the three image
  types, magic bytes match the type, sha256 of the body equals the path (else 400). Stores
  `screenshots/{project_id}/{sha256}` and a row in `blobs` (project_id, sha256, media_type, bytes,
  created_at). Idempotent.
- Answers 410 for a project pending deletion, as `/collect/runs` does.

Run upload:

- `ResultIn.screenshots`: optional list, max 50, each with sha256 (64 hex), media_type (one of three),
  step_text (≤1000), step_line (1..1e6, optional), hook (`before`|`after`, optional).
- New table `result_screenshots`: id, result_id (FK `test_results`, ON DELETE CASCADE), position,
  blob_id (FK `blobs`), step_text, step_line, hook. Alembic migration 025 (migration 026 later made `blobs.created_at` NOT NULL).
- A reference whose blob is not in `blobs` for this project is dropped silently (counted in logs).
- `step_text` is masked with the project's masking patterns, like `failed_step_text`, and the re-mask
  job (`jobs/remask.py`) re-masks `result_screenshots.step_text` when patterns change, as it does for
  `failed_step_text`.

Cleanup:

- Retention (`jobs/retention.py`): results are deleted as today; `result_screenshots` goes with them by
  cascade. Then a garbage pass deletes `blobs` rows (and their objects) that no `result_screenshots` row
  references and that are older than 7 days (the 7 days cover blobs uploaded before their run, including
  a spooled part resent days later). Same advisory lock, batches of 500.
- Project purge (`jobs/purge.py`): delete every object under `screenshots/{project_id}/`, then the rows.

Export (`export.py`, decided with the user: references only):

- Each exported result carries its `screenshots: [{step_text, step_line, hook, media_type, bytes,
  sha256}]` in position order. The image files are not in the export.
- The export docs (README / SECURITY data-export section) say plainly that screenshot images are not
  exported, only their references, and are deleted with the project.

Read endpoints (JWT, `READ_ROLES`, 404 for non-members, as other run reads):

- `GET /api/v1/projects/{p}/runs/{r}/results/{result_id}/screenshots` →
  `{screenshots: [{id, step_text, step_line, hook, media_type, bytes}]}` in position order.
- `GET /api/v1/projects/{p}/screenshots/{id}` → the image bytes, streamed from storage by ingestion,
  with `Cache-Control: private, max-age=3600`, `Content-Type` from the row, `X-Content-Type-Options:
  nosniff`. No presigned URLs: one auth path, and storage stays private.
- `latest-results` (`analytics.py`) adds `screenshot_steps: [{step_text, step_line, hook, count}]` per
  result (only when the result has screenshots), grouped by step, so the Gherkin view can place buttons
  without a second request. Text is needed, not just the line: the dashboard's step matching
  (`lib/failedStep.ts` `locateFailedStep`) trusts the line only when the text also matches.
- `RunDetail.results[]` adds `screenshot_count`.

Gateway:

- New location `/api/v1/collect/blobs` with its own rate zone (50 r/s, burst 100) and
  `client_max_body_size 6m`.
- Add `screenshots` to the ingestion project-route regex (`gateway/nginx.conf.template:216`), or
  `/projects/{p}/screenshots/{id}` falls through to project-service.

### 5.4 Dashboard

- **Gherkin view** (`GherkinBlock` on `CaseEditorPage` and `FeaturePage`): for each entry in
  `screenshot_steps`, a small camera button on the matching line through the existing `annotations`
  map (not used by any page yet), with the count when above 1. Matching reuses `locateFailedStep`
  (text, then line). A step that cannot be matched in the shown Gherkin (case edited since the run)
  puts its images under a "Screenshots" link next to the result pill instead.
- **Background steps on FeaturePage**: the Background is shown once for all scenarios, so a button
  there would belong to no single result. Images on a Background step go to that scenario's
  "Screenshots" link. On `CaseEditorPage` (one case) they sit on the Background line.
- **Run detail page** (`RunDetailPage` results table): a camera count next to `LogPanel` when
  `screenshot_count > 0`.
- **Viewer** (new `ScreenshotViewer`): a dialog that lists the result's screenshots grouped by step
  ("Then the booking is confirmed", "End of scenario"), opens on the clicked step, previous/next with
  arrow keys, Escape closes, full size in a new tab. Images are fetched only when the dialog opens, with
  the Bearer token, turned into blob URLs, and revoked on close.
- Follows the existing dashboard patterns and the ui-ux-pro-max check for the new UI.

### 5.5 Settings

Project Settings gains a toggle "Keep screenshots from uploads" (owner/admin), **off by default**. It
is a new column `keep_screenshots` on ingestion's `collection_settings` (migration 025, edited with
`MANAGE_ROLES` like the other collection settings), so ingestion reads it locally. When off, the key
check reports `screenshots: false`, the blob PUT answers 403, and run uploads drop `screenshots`. Turning it off later does not delete images already stored; they age out with retention.

### 5.6 OBT guidance (not built here)

The README section for screenshots shows an optional `AfterStep` hook:

```js
AfterStep(async function () {
  if (process.env.QEOS_STEP_SHOTS !== "1") return;
  this.attach(await this.page.screenshot({ animations: "disabled", timeout: 10000 }), "image/png");
});
```

so a team can turn per-step screenshots on for one run without slowing the nightly.

## 6. Things to keep in mind

- **Privacy.** Screenshots can show names, emails and booking data, and QEOS cannot mask an image. This
  is why the setting is off by default and the SECURITY and data privacy docs must say so plainly.
- **Size.** A 200-scenario run with one image each is about 20–100 MB; with per-step images it can be
  several GB. Retention days apply to images as to results; NEXT_STEPS records a possible separate,
  shorter image retention if storage grows.
- **Backups.** The MinIO volume must be in the VM backup; the deploy README says how.
- **Monitoring.** MinIO exposes Prometheus metrics; add storage used to the existing Grafana dashboard.

## 7. Left to the builder

- S3 client package choice, MinIO image digest, and the exact compose healthcheck.
- Viewer layout details, within the existing design system.
- Whether `blobs` dedupe uses `ON CONFLICT DO NOTHING` or a pre-check.

## 8. Calls made without the user (check these)

- Screenshots are **off by default** per project (privacy), switched on by an owner or admin.
- Images follow the **same retention** as results (no separate image retention yet).
- Images are served **through ingestion** (no presigned URLs).
- **Cucumber only**; Playwright attachments later.
- Limits: 5 MB per image, 50 per result, 5,000 per run.
- Accepted types: PNG, JPEG, WebP only.
- MinIO in production too (same VM), not an external S3 service.
- Capability signal on the key check (`screenshots: true|false`), not on HEAD.
- Image upload phase capped at 120 seconds; unreferenced blobs cleaned after 7 days.
- Background-step images on FeaturePage go to the scenario's "Screenshots" link.
