# Collector Agent — Design

**Date:** 2026-09-29
**Status:** Draft — awaiting review
**Scope:** `collector/` — the `qav-collector` Python command-line tool that runs in a customer's CI job, reads JUnit XML reports, and uploads them to ingestion-service's `POST /api/v1/collect/runs`. Plus its tests, a CI job, an end-to-end check through the running stack, and docs.

## Problem

The roadmap's 30-day plan ends week 3 with a "Collector Agent MVP: simple HTTP-based data collector, JUnit XML parser, basic authentication to platform, retry mechanism for failed uploads", and its success metrics include "install collector agent in a CI pipeline" and "submit test results from a simple test suite". ingestion-service can now receive runs, but nothing produces them from a real test suite.

## Decisions (agreed during brainstorming)

| Question | Decision |
|---|---|
| Form | A Python package with a command-line tool, `qav-collector`, standard library only |
| Distribution | Lives in `collector/` in this repository; installed from a git tag; PyPI later |
| Formats | JUnit XML only, behind a small parser interface |

## Package

```
collector/
  pyproject.toml            # qav-collector 0.1.0, requires-python >=3.9, no dependencies
  src/qav_collector/
    __init__.py             # __version__
    cli.py                  # argument parsing, exit codes, output
    junit.py                # JUnit XML -> results
    ci.py                   # CI detection (GitHub Actions, GitLab CI, Jenkins)
    payload.py              # merge, run times, splitting into parts
    upload.py               # HTTP client with retries
  tests/
    fixtures/               # representative JUnit files
    test_junit.py  test_ci.py  test_payload.py  test_upload.py  test_cli.py
  README.md
```

Entry point: `qav-collector = qav_collector.cli:main`.

## Command line

```
qav-collector upload PATTERN [PATTERN ...] [options]
qav-collector --version
```

Options (each also readable from the named environment variable; a flag wins over the variable, and both win over CI detection):

| Option | Env var | Meaning |
|---|---|---|
| `--url` | `QAV_URL` | Platform base URL (required unless `--dry-run`) |
| — | `QAV_API_KEY` | API key — **environment only**, never a flag (flags appear in process lists and in CI logs that echo commands) |
| `--ci-provider` | `QAV_CI_PROVIDER` | One of `github_actions`, `gitlab_ci`, `jenkins`, `other`, `local` |
| `--branch`, `--commit`, `--ci-run-url`, `--environment` | `QAV_BRANCH`, `QAV_COMMIT`, `QAV_CI_RUN_URL`, `QAV_ENVIRONMENT` | Run metadata |
| `--idempotency-key` | `QAV_IDEMPOTENCY_KEY` | Overrides the CI-derived key |
| `--ca-file` | `QAV_CA_FILE` | Extra certificate to trust (e.g. the local stack's self-signed one) |
| `--fail-on-error` | `QAV_FAIL_ON_ERROR=1` | Exit 1 if the upload ultimately fails |
| `--dry-run` | — | Parse and print the JSON that would be sent; no upload, no key needed |

Glob patterns support `**`; matches are de-duplicated.

### Exit codes

| Code | When |
|---|---|
| 0 | Uploaded; or nothing to upload (files matched, no test cases); or upload failed **without** `--fail-on-error` (a warning is printed) |
| 1 | Upload failed and `--fail-on-error` is set |
| 2 | Usage or configuration error: no `QAV_URL`, no `QAV_API_KEY` (unless `--dry-run`), no file matched, an `http://` URL that is not localhost, an unreadable `--ca-file` |

By default the collector never breaks the customer's build because the platform is unreachable; a misconfigured collector always fails loudly.

### Output

One line per step on stderr, prefixed `qav:` — e.g. `qav: parsed 3 files, 412 results (7 failed, 2 errored, 5 skipped)`, `qav: uploaded run 42 (201)`, `qav: skipped reports/x.xml: not well-formed XML`. `--dry-run` prints the JSON payload(s) on stdout. The API key never appears in any output: every message is checked against it and the key replaced with `***` before printing.

## CI detection

| CI | Detected when | commit | branch | run URL | idempotency key |
|---|---|---|---|---|---|
| GitHub Actions | `GITHUB_ACTIONS=true` | `GITHUB_SHA` | `GITHUB_HEAD_REF` if set (pull requests), else `GITHUB_REF_NAME` | `GITHUB_SERVER_URL/GITHUB_REPOSITORY/actions/runs/GITHUB_RUN_ID` | `gh-GITHUB_RUN_ID-GITHUB_RUN_ATTEMPT-GITHUB_JOB` |
| GitLab CI | `GITLAB_CI=true` | `CI_COMMIT_SHA` | `CI_COMMIT_REF_NAME` | `CI_JOB_URL` | `gl-CI_JOB_ID` |
| Jenkins | `JENKINS_URL` set | `GIT_COMMIT` | `GIT_BRANCH` without a leading `origin/` | `BUILD_URL` | `jk-BUILD_TAG` |
| none | — | — | — | — | `local`; `ci_provider` `local` |

The key sent is that prefix plus `-` and 12 random hex characters, new for every invocation (`gh-123-2-test-3f9c0a1b2d4e`). The CI identifiers alone are not unique: every leg of a matrix and every upload step in one job share them, and since the server answers 409 when a key comes back with a different body (`finished_at` alone always differs), a shared key would lose every upload after the first. Deduplication therefore works within one invocation: the collector's own retries reuse the key, so a POST that timed out after the server stored the run is replayed (200), not stored twice. An explicit `--idempotency-key` / `QAV_IDEMPOTENCY_KEY` is used as given. *(Revised after the final review; the first version used the bare CI identifiers.)* Keys are reduced to printable ASCII and cut to 200 characters to leave room for the `-part-N` suffix.

## JUnit parsing

### Accepting files

- Files larger than 50 MB are skipped with a warning.
- Any file that declares a `<!DOCTYPE` or `<!ENTITY` is skipped: JUnit never needs one, and refusing them rules out entity-expansion attacks without a third-party XML library. The declaration is caught by expat's own handler while parsing, so it is refused in any encoding (a byte search would miss a UTF-16 file).
- Files that are not well-formed XML are skipped with a warning; the other files are still processed.
- Root `<testsuites>` or `<testsuite>`; any other root element → skipped with a warning.

### Mapping `<testcase>` → result

| Result field | Source |
|---|---|
| `suite` | `name` of the nearest enclosing `<testsuite>` (nested suites are walked recursively); `""` if none |
| `class_name` | `classname` attribute, `""` if absent |
| `name` | `name` attribute; a test case without a usable name is skipped (counted and reported) |
| `file` | `file` attribute, if present |
| `duration_ms` | `round(float(time) × 1000)`; commas are removed first (`"1,200.5"`); missing, negative or not a number → 0 |
| `status` | `<error>` → `errored`; else `<failure>` → `failed`; else `<skipped>` → `skipped`; else `passed` |
| `message` | the deciding `<error>`/`<failure>`/`<skipped>` element's `message` attribute, else the first line of its text |
| `details` | that element's text |

- Surefire's `<flakyFailure>`, `<flakyError>`, `<rerunFailure>`, `<rerunError>` are ignored — they record earlier attempts; the final outcome is what the elements above say.
- `message` and `details` are cut to 64 KB of UTF-8 at a character boundary (the server's limit); NUL and unpaired surrogates are replaced with U+FFFD (the server would otherwise do it, or reject them in identity fields).
- Identity fields (`suite`, `class_name`, `name`, `file`) containing NUL or unpaired surrogates: the test case is skipped with a warning (the server would reject the whole run).
- String fields are cut to the server's lengths (`suite`/`class_name` 500, `name`/`file` 1000).

### Parser interface

`junit.py` exposes `parse_file(path) -> ParsedFile(results, suite_timestamps, suite_seconds, warnings)`. Other formats later implement the same function in their own module; `cli.py` picks a parser per file (today: always JUnit).

## Building the upload

- All matched files are merged into **one run per CI job**.
- `started_at` = the earliest `<testsuite timestamp>` across all files (timestamps without a zone are read as UTC); if none, `finished_at − Σ suite time` (or of result durations when suites carry no `time`).
- `finished_at` = the collector's current time.
- `started_at` is clamped into `[finished_at − 7 days, finished_at]` (the server rejects spans over 7 days and starts after the finish).
- Metadata: `ci_provider`, `ci_run_url`, `commit_sha` (sent only if it matches `^[0-9a-fA-F]{7,40}$`), `branch`, `environment`, `agent_version` (`qav-collector/<version>`).
- **Splitting:** more than 20,000 results → parts of 20,000. A part whose JSON is over 9 MB is halved again until it fits the gateway's 10 MB body limit. Each part is its own run; its `Idempotency-Key` is `<key>-part-<n>` (n from 1), so a retried POST of a part replays that part. With a single part the key has no suffix.
- No results at all → `qav: no test results found`, exit 0, nothing sent.

## Upload

`POST {url}/api/v1/collect/runs` with `Authorization: Bearer <key>`, `Content-Type: application/json`, `Idempotency-Key`, `User-Agent: qav-collector/<version>`; standard-library `urllib`, 30 s timeout per attempt; TLS verified with the system store, plus `--ca-file` if given. Parts are sent in order; the first part that ultimately fails stops the upload, and the message names the parts already stored. Every request carries an `Idempotency-Key`, so retrying a POST can never store a run twice.

Time budget: no new attempt starts once 120 s have passed since a part's first attempt, so a dead platform delays the CI job by about 2 minutes per part at most (not 5 × 30 s plus the waits).

| Response | Action |
|---|---|
| 201, or 200 (replay of a stored run) | Success; print the run id |
| connection error, timeout, 502, 503, 504 | Retry: waits 1, 2, 4, 8 s (each ×(1 + random 0–0.25)); at most 5 attempts |
| 429 | Retry after `Retry-After` seconds (capped at 10; 1 if missing), same attempt budget |
| 401 | Stop: "the API key is invalid or revoked" |
| 409 | Stop: "this Idempotency-Key was already used for different results" |
| 413, 422, any other 4xx | Stop; print the server's `detail` (truncated to 500 characters) |
| any other 5xx | Stop after the attempt budget, as for 502 |

- `http://` URLs are allowed only for `localhost`, `127.0.0.1` and `::1`; otherwise exit 2.
- There is no option to disable certificate verification.
- `HTTPS_PROXY` / `NO_PROXY` are honoured by `urllib`.

## Testing

pytest from `collector/`; no network except a local test server.

- **Parser** — fixtures modelled on real output from pytest `--junitxml`, Maven Surefire (with `flakyFailure`/`rerunFailure`), Playwright's JUnit reporter and Cucumber-JS's JUnit formatter; plus root `<testsuite>`, nested suites, `error` vs `failure` precedence, `skipped` with and without a message, `time` as `"1,200.5"`/missing/garbage, timestamps with and without zones; skipped files: DOCTYPE, ENTITY, not well-formed, over 50 MB (size patched), wrong root.
- **CI detection** — one test per provider with a fake environment, GitHub pull-request branch, Jenkins `origin/`, flag and variable precedence, key sanitising.
- **Payload** — merge across files, run-time derivation and clamping, `commit_sha` filtering, splitting by count and by size with the `-part-N` keys, empty input.
- **Upload** — a real `http.server` on a local port in a thread: 201/200 success; retries on 503 and connection refused with the sleep function injected; `Retry-After`; no retry on 401/409/422; attempt budget and the 120 s time budget (clock injected); a timed-out POST retried with the same key; the key never appears in output or exceptions; the `http://` rule.
- **CLI** — every exit code, `--dry-run` output, `--fail-on-error`, missing configuration.
- **End to end** — the CI `gateway` job's smoke test runs the collector from `collector/src` (`python -m qav_collector`; installing it is covered by the `collector` job, which runs `pip install .` and the `qav-collector` entry point), writes a small JUnit file, and uploads it through the running stack with the key the smoke test created (`--ca-file` with the gateway's certificate); then reads the run back through the gateway and checks its counts.

## Packaging, CI, release

- `collector/pyproject.toml`: `name = "qav-collector"`, `version = "0.1.0"`, `requires-python = ">=3.9"`, no dependencies, the script entry point.
- CI: a new job `collector` running its tests on Python 3.9 and 3.12; the `gateway` job's smoke test gains the end-to-end upload.
- Release: a git tag `collector-v0.1.0`, created by the maintainer. Customers install with `pip install "qav-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.1.0#subdirectory=collector"`.

## Documentation

- `collector/README.md`: install, the three CI setups (GitHub Actions workflow step, GitLab CI job, Jenkins `sh` step), `--dry-run`, options and exit codes, security notes (key only from the environment, HTTPS rule).
- Root README: `collector/` in the project structure.
- `TODO.md`: collector items done, and the **Collector — nice to have** list below.

## Collector — nice to have (TODO.md)

Distribution
- Publish to PyPI (trusted publishing from a tag), so `pip install qav-collector` / `pipx run qav-collector` work.
- A ready-made GitHub Action (`uses: …/qav-collector@v1`) and a GitLab CI component.
- A Jenkins shared-library step.
- A Docker image and a single-file build (zipapp) for runners without pip.

Formats
- Cucumber JSON (features, scenarios, tags, steps) — needs ingestion fields for tags and steps.
- Playwright JSON (retries, attachments, projects/browsers).
- TestNG XML, NUnit XML, xUnit.net XML, .NET TRX.

Richer data
- Keep each retry attempt as its own result, so flaky tests become visible.
- Git metadata: commit author and message, pull-request number, base branch.
- Test ownership from CODEOWNERS.
- Artifact upload (screenshots, videos, traces) once ingestion accepts them.

Reliability and operations
- Keep a failed upload on disk and `qav-collector retry` it later.
- Stream partial results during long runs instead of one upload at the end.
- `qav-collector check` — verify the URL, certificate and key without uploading.
- A `.qav.yml` config file as an alternative to flags and environment variables.
- Client certificates (mTLS) — roadmap Phase 2.

## Out of scope

Everything in the list above, plus changes to ingestion-service's API.
