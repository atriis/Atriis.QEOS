# Playwright screenshots: send the images a Playwright test attached, like Cucumber step screenshots

Date: 2026-10-20 · Status: for approval · Follow-up of ADR-036 (spec `2026-10-19-step-screenshots-design.md`)

## 1. Intent

ADR-036 brought step screenshots for Cucumber JSON: the collector uploads the images a scenario attached, and
QEOS shows them on the result. Teams that run Playwright's own test runner (`@playwright/test`) get nothing: the
collector reads their JSON report (`--reporter=json`) but drops every attachment. The failure screenshot
Playwright takes with `screenshot: "only-on-failure"` is exactly what someone reading a failed result wants.

This design reuses everything ADR-036 built (MinIO storage, blob endpoints, the project switch, the viewer). Only
the collector learns to find Playwright's images.

## 2. What a Playwright JSON report gives

Each test attempt (`suites[].specs[].tests[].results[]`) has `attachments: [{name, contentType, path?, body?}]`:

- `path`: a file on the CI disk, usually absolute, under the `outputDir` (`test-results/…`). Screenshots
  (`name: "screenshot"`), videos (`video`, `video/webm`) and traces (`trace`, `application/zip`) come this way.
- `body`: base64 content, for attachments made in memory with `testInfo.attach(name, {body, contentType})`.

Attachments belong to the attempt, not to a step: there is no per-step data. An attempt does have `steps[]`
(titles of `test.step` blocks, hooks and `expect` calls, with an `error` on the one that failed).

## 3. Goals, non-goals, anti-goals

**Goals**
- Image attachments (`image/png`, `image/jpeg`, `image/webp`) of a Playwright attempt reach QEOS on that attempt's
  result, and show in the existing viewer and run-detail camera count.
- Both forms work: `path` (read from disk) and `body` (decoded).
- Retries keep their own images: each attempt is already its own result.

**Non-goals**
- Videos and traces (`video/webm`, `application/zip`): the next NEXT_STEPS item, with its own design (size,
  playback, a trace viewer). This design skips them, with one count in the output.
- Playwright's JUnit reporter (`[[ATTACHMENT|path]]` lines in `system-out`): later, if a team uses it.
- Placing images on a precise step: the report has no such data.

**Anti-goals**
- The collector uploading any file a report names. A report is just JSON; a tampered or careless one could point
  at `~/.ssh/id_rsa` or `/etc/passwd`. Only files under the working directory that really are images may be read
  (section 4.2).
- Any change for Cucumber users, or for Playwright users with screenshots off.

## 4. How it works

### 4.1 Server: no change

The run payload already accepts `screenshots: [{sha256, media_type, step_text, step_line?, hook?}]` on any result
(`ResultIn.screenshots`), and the blob endpoints, the project switch ("Keep screenshots from uploads"), retention,
purge, export references, masking of `step_text` and the viewer are runner-agnostic. Nothing changes in ingestion,
the gateway or the dashboard.

### 4.2 Collector 0.13.0 (`formats.py` `_playwright_suite`, `upload.py`)

For each attempt, collect attachments whose `contentType` is one of the three image types:

- **`body`**: base64-decode. Invalid base64: skip, counted.
- **`path`**: read the file only when **all** of these hold, else skip it, counted:
  - the path, resolved (symlinks followed, `os.path.realpath`), is inside the collector's working directory —
    the same rule the upload patterns already follow ("patterns cannot reach outside the working directory").
    Playwright writes absolute paths under the project's `test-results/`, which is inside the checkout in CI;
  - it is a regular file of at most 5 MB (checked with `os.stat` before reading);
  - its first bytes match the declared type (PNG, JPEG or WebP magic bytes, the same check ingestion makes).
  A file that no longer exists (the CI step cleaned up) is skipped, counted. A relative `path` (a custom
  `outputDir`) is resolved from the report file's folder before the check.
- **Visual comparisons.** A failed `toHaveScreenshot()` attaches `<name>-expected`, `<name>-actual` and
  `<name>-diff` images. They are labelled "Expected", "Actual" and "Difference" (in that order, before the
  attempt's other images) instead of the raw names.
- **Step reference** (the viewer groups by it):
  - `hook: "after"` for every Playwright image (taken by the test, not on a known step);
  - `step_text`: the title of the attempt's failing step when there is one (the deepest step in `steps[]` with an
    `error`), else `"End of test"`; for an attachment whose `name` is not `"screenshot"`, the `name` is appended in
    parentheses, so `testInfo.attach("checkout page", …)` reads "End of test (checkout page)"; cut to 1,000
    characters (the server's `step_text` limit, `ScreenshotIn` in ingestion `schemas/collect.py`);
  - `step_line`: the failing step's `location.line` when present, else none.
- The existing limits and rules apply unchanged: 5 MB per image, 50 per result, 5,000 per run, de-duplication by
  sha256, the capability check, `--no-screenshots` / `QEOS_NO_SCREENSHOTS` / `no-screenshots: true` in `.qeos.yml`,
  the 120-second image budget, 4 parallel uploads, the 422 downgrade.
- Output: one line as today (`screenshots: N stored, M skipped`) plus, when any were skipped for a Playwright
  reason, one summary line with counts by reason (outside the working directory, missing, too large, not an image,
  video/trace not sent yet). Never print the skipped paths' contents; the paths themselves may be printed. When
  every path attachment was outside the working directory, add once: "Playwright images are outside the working
  directory; set `outputDir` inside the checkout".

### 4.3 Docs

- Collector README: "Step screenshots" section gets a Playwright subsection (what is sent, the working-directory
  rule, videos and traces not yet, the `playwright.config` lines `use: { screenshot: "only-on-failure" }` and
  `reporter: [["json", { outputFile: "results.json" }]]`); the formats table marks Playwright attachments.
- SETUP (step screenshots section) one paragraph; NEXT_STEPS and TODO: this item done; SECURITY: the
  working-directory rule for reading report-named files.
- ADR-036 consequences: one line that Playwright images use the same path.

## 5. Tests (collector)

Fixtures: a Playwright JSON report with one failing attempt (a failing `test.step` with `location`), one passing
retry, attachments by `path` (PNG inside the working directory), by `body` (JPEG), a `video/webm`, a
`application/zip` trace, a `text/plain` attachment, a path outside the working directory, a symlink inside the
working directory pointing outside it, a missing file, a 6 MB PNG, and a `.png` file that is really text.

- the failing attempt sends two screenshots with `hook: "after"`, the failing step's title and line; the passing
  retry sends its own;
- `body` and `path` both work; the same image twice uploads once;
- outside path, symlink escape, missing, too large, wrong magic bytes, video, trace: skipped and counted by reason,
  the run still uploads;
- `--no-screenshots` and the capability check behave as for Cucumber (reuse the existing tests' fixtures);
- a Cucumber report's behaviour is unchanged (existing tests).

## 6. Calls made without the user (check these)

- Images only; videos and traces wait for their own design.
- `path` attachments are read only inside the working directory, symlinks resolved, magic bytes checked.
- All Playwright images are "after" hook images, labelled with the failing step's title or "End of test".
- Collector version 0.13.0; no server change.
