# Step Screenshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a camera button on each Gherkin step (and a count on each run result) that has screenshots, with images collected from Cucumber JSON, stored in MinIO, and served through ingestion.

**Architecture:** The collector extracts image attachments per step, uploads them content-addressed (`PUT /collect/blobs/{sha256}`) before the run, then references them in the run payload. Ingestion stores bytes in an S3-compatible bucket behind a small `ArtifactStore` interface, rows in `blobs` and `result_screenshots`, and streams images to the dashboard over the normal Bearer-auth API. The dashboard places buttons by step text/line with the existing `locateFailedStep` logic.

**Tech Stack:** Python 3 stdlib (collector), FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL (ingestion), boto3 against MinIO, React + TypeScript + TanStack Query + Vitest (dashboard), nginx gateway, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-19-step-screenshots-design.md`

## Global Constraints

- Image types: `image/png`, `image/jpeg`, `image/webp` only.
- Limits: 5 MB per image; 50 screenshots per result; 5,000 images per run (collector); collector image phase budget 120 seconds; 4 parallel PUTs.
- Object key: `screenshots/{project_id}/{sha256}`; bucket `qeos-artifacts`, private.
- Env: `ARTIFACTS_S3_ENDPOINT`, `ARTIFACTS_S3_BUCKET`, `ARTIFACTS_S3_ACCESS_KEY`, `ARTIFACTS_S3_SECRET_KEY`. Unset = screenshots off; QEOS still works.
- Setting `collection_settings.keep_screenshots`, default **false**, edited by `MANAGE_ROLES`.
- Unreferenced blobs are deleted after **7 days**; referenced ones follow result retention.
- Image response headers: `Cache-Control: private, max-age=3600`, `X-Content-Type-Options: nosniff`.
- Gateway: `/api/v1/collect/blobs` own rate zone 50 r/s burst 100, `client_max_body_size 6m`; `screenshots` added to the ingestion project-route regex.
- Collector version `0.10.0`, standard library only. Flag `--no-screenshots` / env `QEOS_NO_SCREENSHOTS=1`.
- Export: references only (`step_text, step_line, hook, media_type, bytes, sha256`), never image bytes.
- No image problem ever fails a run upload.
- Every commit updates the affected .md files (README, SECURITY, data privacy spec, NEXT_STEPS, TODO, blueprint, service READMEs). Full suites and the dashboard lint/typecheck/build green before any push; push direct to master.

## Review Focus

1. Same image on two steps / two results / two runs: one object, two rows; deleting one result keeps the object. Test in Task 5.
2. Blob PUT whose body hash does not match the path, or PNG bytes sent as `image/jpeg`: 400, nothing stored. Test in Task 3.
3. Scenario where every step is skipped (Before hook failed) with a Before/After hook image: image goes to first/last real step, never to a hook entry. Test in Task 7.
4. Run upload referencing a sha256 stored for **another** project: dropped, never linked. Test in Task 4.
5. Case Gherkin edited after the run so the step text no longer matches: images appear under the "Screenshots" link, not on a wrong line. Test in Task 10.

---

### Task 1: Artifact storage and MinIO

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/utils/artifact_store.py`
- Modify: `platforms/ingestion-service/src/ingestion/core/config.py`, `platforms/ingestion-service/requirements.txt` (add `boto3` pinned), `docker-compose.yml`, `deploy/docker-compose.prod.yml`, `.env.example` files used by compose, `deploy/README.md` (backup of `qeos_minio_data`)
- Create: `docs/architecture/adr/ADR-036-artifact-storage-step-screenshots.md`; Modify: `docs/architecture/adr/INDEX.md`, `ARCHITECTURE_BLUEPRINT_V1_0.md` (MinIO row: CURRENT, trigger met)
- Test: `platforms/ingestion-service/tests/unit/test_artifact_store.py`

**Interfaces:**
- Produces:
  - `class ArtifactStore(Protocol)`: `put(key: str, data: bytes, media_type: str) -> None`, `get(key: str) -> bytes`, `delete(keys: list[str]) -> None`, `delete_prefix(prefix: str) -> int`
  - `class MemoryArtifactStore(ArtifactStore)` (tests; `objects: dict[str, tuple[bytes, str]]`)
  - `class S3ArtifactStore(ArtifactStore)` (boto3, `endpoint_url`, path-style addressing)
  - `def get_artifact_store() -> Optional[ArtifactStore]` — FastAPI dependency; `None` when any `ARTIFACTS_S3_*` is unset; cached singleton
  - `def screenshot_key(project_id: int, sha256: str) -> str` → `"screenshots/{project_id}/{sha256}"`

- [ ] **Step 1: Write failing tests** — `test_memory_store_put_get_delete`, `test_delete_prefix_only_removes_that_project` (keys under `screenshots/1/` and `screenshots/10/`; `delete_prefix("screenshots/1/")` leaves the `10` key — the prefix must end with `/`), `test_get_artifact_store_is_none_without_config`, `test_screenshot_key`.
- [ ] **Step 2: Run** `pytest platforms/ingestion-service/tests/unit/test_artifact_store.py -v` — FAIL (module missing).
- [ ] **Step 3: Implement** the module and the four `ARTIFACTS_S3_*` settings (all `Optional[str] = None`). `S3ArtifactStore.delete` uses `delete_objects` in chunks of 1,000; `delete_prefix` pages `list_objects_v2`.
- [ ] **Step 4: Run** the test file — PASS.
- [ ] **Step 5: Compose.** Add `minio` (image pinned by digest, `server /data`, volume `qeos_minio_data`, no published port, healthcheck) and one-shot `minio-init` (`mc mb --ignore-existing local/qeos-artifacts`, no anonymous policy) to both compose files; give `ingestion-service`, `ingestion-retention` the four env vars and `depends_on: minio-init: service_completed_successfully`. Run `docker compose config -q` — no output.
- [ ] **Step 6: Write ADR-036** (context: blueprint trigger; decision: MinIO, content-addressed per project, served through ingestion, off by default; consequences: backups, no image masking). Update INDEX and blueprint row.
- [ ] **Step 7: Commit** `feat(ingestion): artifact storage on MinIO for screenshots (ADR-036)`.

### Task 2: Schema — blobs, result_screenshots, keep_screenshots

**Files:**
- Create: `platforms/ingestion-service/alembic/versions/025_screenshots.py`, `platforms/ingestion-service/src/ingestion/models/screenshot.py`
- Modify: `models/__init__.py`, `models/collection_settings.py`, `schemas/collection_settings.py`, `service/collection_settings_service.py`, `api/v1/endpoints/collection_settings.py`
- Test: `tests/unit/test_migration.py` (extend), `tests/integration/test_collection_settings.py` (extend)

**Interfaces:**
- Produces:
  - `Blob`: table `blobs` — `id` PK, `project_id` int not null, `sha256` char(64), `media_type` str(32), `bytes` int, `created_at` tz; unique `(project_id, sha256)`
  - `ResultScreenshot`: table `result_screenshots` — `id` PK, `result_id` FK `test_results.id` ON DELETE CASCADE, `position` int, `blob_id` FK `blobs.id` (no cascade; the GC owns blob deletion), `step_text` str(1000), `step_line` int null, `hook` str(8) null; index `(result_id, position)`, index `(blob_id)`
  - `CollectionSettings.keep_screenshots: bool`, server default false; exposed in `CollectionSettingsOut`/`In` as `keep_screenshots`

- [ ] **Step 1: Write failing tests** — migration upgrade/downgrade round trip creates and drops both tables and the column; `test_keep_screenshots_defaults_false`, `test_member_cannot_set_keep_screenshots` (403), `test_admin_sets_keep_screenshots`.
- [ ] **Step 2: Run** those tests — FAIL.
- [ ] **Step 3: Implement** migration 025 (down_revision `024`), models, schema field, service update.
- [ ] **Step 4: Run** `pytest platforms/ingestion-service/tests -k "migration or collection_settings" -v` — PASS.
- [ ] **Step 5: Commit** `feat(ingestion): screenshot tables and keep_screenshots setting (ADR-036)`.

### Task 3: Blob endpoints and key capability

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/blobs.py`, `platforms/ingestion-service/src/ingestion/service/blob_service.py`
- Modify: `api/v1/api.py`, `schemas/collect.py` (`KeyCheck`), `api/v1/endpoints/collect.py` (`check_key`), `gateway/nginx.conf.template`
- Test: `tests/integration/test_collect_blobs.py`, `tests/integration/test_collect_key.py` (extend)

**Interfaces:**
- Consumes: `get_artifact_store`, `screenshot_key`, `Blob`, `CollectionSettings.keep_screenshots`.
- Produces:
  - `def screenshots_enabled(db: Session, project_id: int, store: Optional[ArtifactStore]) -> bool`
  - `def sniff_image(data: bytes) -> Optional[str]` — PNG `\x89PNG\r\n\x1a\n`, JPEG `\xff\xd8\xff`, WebP `RIFF....WEBP`
  - `def store_blob(db, store, project_id: int, sha256: str, media_type: str, data: bytes) -> Blob` (idempotent: existing row returned, no second put)
  - `HEAD /api/v1/collect/blobs/{sha256}` → 200 / 404; `PUT` same path → 201 new, 200 existing, 400 bad hash/type/magic, 413 > 5 MB, 403 when `screenshots_enabled` is false, 410 project pending deletion (from `get_api_key`)
  - `KeyCheck.screenshots: bool`

- [ ] **Step 1: Write failing tests** (memory store via `app.dependency_overrides[get_artifact_store]`): `test_put_then_head_200`, `test_put_twice_stores_once`, `test_put_hash_mismatch_400`, `test_put_png_bytes_as_jpeg_400`, `test_put_unsupported_type_400` (`image/gif`), `test_put_over_5mb_413`, `test_put_when_setting_off_403`, `test_put_when_no_store_403`, `test_head_other_projects_blob_404`, `test_key_check_reports_screenshots` (false by default, true with setting on + store).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** Path param validated `^[0-9a-f]{64}$` (else 404). Read body with a 5 MB + 1 cap before hashing. Row insert uses `ON CONFLICT (project_id, sha256) DO NOTHING`; object put happens before the row commit.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Gateway.** Add `limit_req_zone ... zone=collect_blobs:10m rate=50r/s;` and `location /api/v1/collect/blobs { client_max_body_size 6m; limit_req zone=collect_blobs burst=100 nodelay; proxy to ingestion }` before the `/api/v1/collect` location. Run the gateway config test used in CI (`nginx -t` in the gateway image) — OK.
- [ ] **Step 6: Commit** `feat(ingestion): content-addressed screenshot upload (ADR-036)`.

### Task 4: Screenshots on run upload, masking, re-mask

**Files:**
- Modify: `schemas/collect.py` (`ResultIn`), `service/ingest_service.py`, `jobs/remask.py`
- Test: `tests/unit/test_collect_schema.py`, `tests/integration/test_collect_screenshots.py` (new), `tests/integration/test_remask_job.py`

**Interfaces:**
- Consumes: `Blob`, `ResultScreenshot`, `screenshots_enabled`.
- Produces: `class ScreenshotIn(BaseModel)` (`extra="forbid"`): `sha256: constr(pattern=r"^[0-9a-f]{64}$")`, `media_type: Literal["image/png","image/jpeg","image/webp"]`, `step_text: str` (max 1000), `step_line: Optional[int]` (1..1_000_000), `hook: Optional[Literal["before","after"]]`; `ResultIn.screenshots: Optional[list[ScreenshotIn]]` max 50.

- [ ] **Step 1: Write failing tests** — schema: 51 items rejected, bad sha rejected; ingest: `test_screenshots_linked_in_order`, `test_reference_without_blob_dropped`, `test_reference_to_other_projects_blob_dropped`, `test_screenshots_dropped_when_setting_off`, `test_step_text_masked` (project pattern masks a value in `step_text`); remask: `test_remask_updates_screenshot_step_text`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** After results are inserted, one query maps `(project_id, sha256)` → blob id for all referenced hashes; insert `result_screenshots` with `position` = index in the list; unknown hashes skipped and counted in the existing ingest log line. Mask `step_text` with the same call used for `failed_step_text`. Extend `remask.py` to the new column in the same batch loop.
- [ ] **Step 4: Run** — PASS, plus `pytest platforms/ingestion-service/tests -q` all green.
- [ ] **Step 5: Commit** `feat(ingestion): link screenshots to results on upload (ADR-036)`.

### Task 5: Retention GC, purge, export

**Files:**
- Modify: `jobs/retention.py`, `jobs/purge.py`, `api/v1/endpoints/export.py`
- Test: `tests/integration/test_retention_job.py`, `tests/integration/test_purge.py`, `tests/integration/test_export.py`

**Interfaces:**
- Consumes: `ArtifactStore`, `Blob`, `ResultScreenshot`.
- Produces: `def collect_unreferenced_blobs(db: Session, store: Optional[ArtifactStore], now: datetime, batch: int = 500) -> int` in `retention.py`, run after result deletion under the same advisory lock.

- [ ] **Step 1: Write failing tests** — `test_gc_deletes_unreferenced_blob_older_than_7_days`, `test_gc_keeps_unreferenced_blob_6_days_old`, `test_gc_keeps_blob_still_referenced_by_other_result` (Review Focus 1), `test_retention_deletes_screenshot_rows_with_results`, `test_purge_deletes_project_objects_and_rows` (other project's objects untouched), `test_export_includes_screenshot_references_without_bytes`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** GC: select blob ids with `NOT EXISTS` reference and `created_at < now - 7 days`, delete objects then rows per batch; no store configured → rows only. Purge: `store.delete_prefix(f"screenshots/{project_id}/")` before deleting rows. Export: each result line gains `screenshots` list (omitted when empty); bump the export format version per its existing rule.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(ingestion): screenshot cleanup with retention, purge and export references (ADR-036)`.

### Task 6: Read endpoints

**Files:**
- Modify: `api/v1/endpoints/runs.py`, `schemas/run.py`, `service/run_service.py`, `api/v1/endpoints/analytics.py`, `schemas/analytics.py`, `service/analytics_service.py`, `gateway/nginx.conf.template:216`
- Test: `tests/integration/test_result_screenshots.py` (new), `tests/integration/test_latest_results.py`, `tests/integration/test_runs_endpoints.py`

**Interfaces:**
- Produces:
  - `GET /api/v1/projects/{p}/runs/{r}/results/{result_id}/screenshots` → `{"screenshots": [{"id", "step_text", "step_line", "hook", "media_type", "bytes"}]}`
  - `GET /api/v1/projects/{p}/screenshots/{id}` → bytes, `Content-Type` from blob, the two headers from Global Constraints; 503 when no store
  - `LatestResult.screenshot_steps: Optional[list[{"step_text", "step_line", "hook", "count"}]]` (absent when none)
  - `RunResultOut.screenshot_count: int` (0 when none)

- [ ] **Step 1: Write failing tests** — list in position order; non-member 404; screenshot id of another project 404; image bytes and headers; `latest-results` groups two images on the same step into `count: 2`; run detail `screenshot_count`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** with `READ_ROLES`; `screenshot_steps` and `screenshot_count` via one grouped query per request (no N+1). Add `screenshots` to the regex at `gateway/nginx.conf.template:216`.
- [ ] **Step 4: Run** — PASS; full ingestion suite green.
- [ ] **Step 5: Commit** `feat(ingestion): read screenshots per result and step (ADR-036)`.

### Task 7: Collector — find images per step

**Files:**
- Modify: `collector/src/qeos_collector/formats.py`
- Test: `collector/tests/test_cucumber.py`

**Interfaces:**
- Produces:
  - `IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")`
  - `def _attachment_image(attachment: object) -> Optional[tuple[str, bytes]]` → `(media_type, data)`
  - row key `"screenshots": [{"sha256", "media_type", "step_text", "step_line", "hook"?}]` plus a private `"_images": {sha256: (media_type, bytes)}` on the row; `payload.py` strips `_images` before serialising
  - `MAX_IMAGE_BYTES = 5 * 1024 * 1024`, `MAX_SCREENSHOTS_PER_RESULT = 50`

- [ ] **Step 1: Write failing tests** — `test_image_on_step_gets_that_step`, `test_after_hook_image_goes_to_last_step_that_ran` (cucumber-js hidden After entry), `test_after_hook_image_on_failed_scenario_goes_to_failed_step`, `test_jvm_after_array_image`, `test_before_hook_image_goes_to_first_step`, `test_all_skipped_with_hook_images_never_lands_on_hook_entry` (Review Focus 3), `test_image_over_5mb_skipped`, `test_51st_image_skipped`, `test_text_attachments_still_become_log` (existing behaviour unchanged), `test_payload_does_not_contain_image_bytes`.
- [ ] **Step 2: Run** `pytest collector/tests/test_cucumber.py -v` — FAIL.
- [ ] **Step 3: Implement.** Reuse `_attachment_text`'s field-name and encoding rules. Step `text`/`line` are produced the same way as `failed_step`. Real steps exclude entries with `hidden: true` or keyword `Before`/`After`.
- [ ] **Step 4: Run** — PASS; `pytest collector -q` green.
- [ ] **Step 5: Commit** `feat(collector): read step screenshots from Cucumber JSON (ADR-036)`.

### Task 8: Collector — upload images

**Files:**
- Modify: `collector/src/qeos_collector/upload.py`, `cli.py`, `payload.py`, `__init__.py` (`0.10.0`), `collector/README.md`, `collector/CHANGELOG.md` if present
- Test: `collector/tests/test_upload.py`, `collector/tests/fake_qeos.py` (blob routes + `screenshots` on `/collect/key`)

**Interfaces:**
- Consumes: rows with `screenshots` and `_images` (Task 7); `KeyCheck.screenshots`, blob endpoints (Task 3).
- Produces: `def upload_images(base_url: str, key: str, images: dict[str, tuple[str, bytes]], budget_seconds: float = 120.0, workers: int = 4) -> set[str]` — returns the sha256s that are stored; the caller removes other references before the run POST. `MAX_IMAGES_PER_RUN = 5000`.

- [ ] **Step 1: Write failing tests** — `test_images_uploaded_then_run_references_them`, `test_head_200_skips_put`, `test_key_without_screenshots_field_skips_images` (older QEOS), `test_screenshots_false_skips_images`, `test_failed_put_drops_only_that_reference`, `test_budget_exhausted_drops_remaining` (fake server delays; budget 0.5 s), `test_connection_error_skips_all_images_run_still_uploads`, `test_no_screenshots_flag`, `test_422_downgrade_removes_screenshots`, `test_5001st_image_skipped_with_one_warning`.
- [ ] **Step 2: Run** `pytest collector/tests/test_upload.py -v` — FAIL.
- [ ] **Step 3: Implement** with `urllib` + `concurrent.futures.ThreadPoolExecutor`; same headers and redirect/https rules as the run POST; one summary warning line (`screenshots: N stored, M skipped`). Spool keeps `screenshots` but never images.
- [ ] **Step 4: Run** — PASS; `pytest collector -q` and the zipapp test green.
- [ ] **Step 5: Docs.** collector README: what is sent, the flag, the limits, the OBT `AfterStep` example from spec §5.6.
- [ ] **Step 6: Commit** `feat(collector): upload step screenshots, 0.10.0 (ADR-036)`.

### Task 9: Dashboard — API and viewer

> Invoke `ui-ux-pro-max` before UI edits.

**Files:**
- Create: `dashboard/src/api/screenshots.ts`, `dashboard/src/components/ScreenshotViewer.tsx`, `dashboard/src/components/ScreenshotViewer.test.tsx`
- Modify: `dashboard/src/api/analytics.ts` (`LatestResult.screenshot_steps?`), `dashboard/src/api/runs.ts` (`RunResult.screenshot_count`)

**Interfaces:**
- Produces:
  - `type Screenshot = { id: number; step_text: string; step_line: number | null; hook: "before" | "after" | null; media_type: string; bytes: number }`
  - `getResultScreenshots(projectId, runId, resultId): Promise<{ screenshots: Screenshot[] }>`
  - `getScreenshotBlob(projectId, id): Promise<Blob>` (through `http.ts`, so the Bearer header and refresh apply)
  - `<ScreenshotViewer projectId runId resultId initialStep?: { text: string; line: number | null } open onClose />`

- [ ] **Step 1: Write failing tests** — groups by step with "Start of scenario"/"End of scenario" labels for hooks; opens on `initialStep`; ArrowRight/ArrowLeft page, Escape closes; no image fetched until open; object URLs revoked on close (`URL.revokeObjectURL` spy); error state when a fetch fails.
- [ ] **Step 2: Run** `npm --prefix dashboard test -- ScreenshotViewer` — FAIL.
- [ ] **Step 3: Implement** with the existing dialog pattern (`DeleteProjectDialog` focus trap), lazy fetch per shown image, "Open full size" link to the blob URL in a new tab.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(dashboard): screenshot viewer (ADR-036)`.

### Task 10: Dashboard — buttons, run counts, setting

**Files:**
- Modify: `dashboard/src/pages/CaseEditorPage.tsx`, `dashboard/src/pages/FeaturePage.tsx`, `dashboard/src/pages/RunDetailPage.tsx`, `dashboard/src/components/CollectionCard.tsx`, `dashboard/src/api/collection.ts`
- Create: `dashboard/src/lib/screenshotLines.ts` + `screenshotLines.test.ts`
- Test: `CaseEditorPage` / `FeaturePage` / `RunDetailPage` / `CollectionCard` tests

**Interfaces:**
- Consumes: `locateFailedStep` (`lib/failedStep.ts`), `ScreenshotViewer`, `LatestResult.screenshot_steps`.
- Produces: `placeScreenshots(gherkinLines, steps: LatestResult["screenshot_steps"]): { byLine: Map<number, { count: number; step: {text; line} }>; unplaced: number }`

- [ ] **Step 1: Write failing tests** — `placeScreenshots` puts two steps on their lines; edited Gherkin step → `unplaced` (Review Focus 5); CaseEditorPage shows a camera button with count 2 on that line and a "Screenshots" link only when `unplaced > 0`; no button when `screenshot_steps` absent; FeaturePage puts Background-step images on the scenario's "Screenshots" link, not on the shared Background; RunDetailPage shows the count only when `screenshot_count > 0`; CollectionCard toggle visible to owner/admin, read-only for member, default off.
- [ ] **Step 2: Run** `npm --prefix dashboard test` — FAIL on the new tests.
- [ ] **Step 3: Implement** via `GherkinBlock` `annotations`; button `aria-label="Screenshots for this step (2)"`.
- [ ] **Step 4: Run** `npm --prefix dashboard run lint && npm --prefix dashboard run typecheck && npm --prefix dashboard test && npm --prefix dashboard run build` — all green.
- [ ] **Step 5: Commit** `feat(dashboard): screenshot buttons on steps and run results (ADR-036)`.

### Task 11: Docs gate and push

**Files:** `README.md`, `SECURITY.md`, `docs/superpowers/specs/2026-09-30-data-privacy-design.md` (screenshots are not masked; off by default), `PRODUCT.md`, `NEXT_STEPS.md` (separate image retention, Playwright attachments, videos/traces), `TODO.md` (tick `TODO.md:117`, `:179`, `:387`, `:468` as far as delivered), `platforms/ingestion-service/README.md`, monitoring dashboard (MinIO storage used panel).

- [ ] **Step 1:** Check every file above against the shipped behaviour; fix gaps.
- [ ] **Step 2:** Run the full pre-push suite mirroring `ci.yml` (all service pytest suites, collector, dashboard lint/typecheck/test/build, `docker compose config -q`) — all green.
- [ ] **Step 3:** Commit `docs: step screenshots shipped (ADR-036)`; push master by explicit SHA (`git push origin <sha>:master`).
