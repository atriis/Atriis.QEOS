# qeos-collector

Uploads JUnit XML test results from a CI job to the QEOS platform. Standard library only,
Python 3.9 or newer, nothing else to install.

## Install

```bash
pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@collector-v0.5.1#subdirectory=collector"
```

### Renamed from `qav-collector` (0.4.0)

The collector was `qav-collector` before QEOS got its name. Version 0.4.0, the `collector-v0.4.0`
tag that comes with this release, is the first one called `qeos-collector`. The old names keep
working, so a pipeline that already uses them does not break:

- The `qav-collector` command still runs the collector, after one stderr line:
  `qav-collector is deprecated; use qeos-collector`.
- Every `QAV_*` environment variable (`QAV_URL`, `QAV_API_KEY`, `QAV_ENVIRONMENT`, ...) still works
  when its `QEOS_*` name is not set, with a one-line deprecation warning. If both are set, the
  `QEOS_*` name wins.
- `.qav.yml` is read when there is no `.qeos.yml`, with a deprecation warning.
- API keys that start with `qav_` keep authenticating; new keys start with `qeos_`.

Older tags (`collector-v0.3.0` and before) install the package under its old name, `qav-collector`.

Things that do not rename themselves in your CI configuration:

- **Azure Pipelines:** the template and snippet map `QEOS_API_KEY: $(QEOS_API_KEY)`. A pipeline whose
  secret variable is still named `QAV_API_KEY` must rename it, or map `QEOS_API_KEY: $(QAV_API_KEY)`:
  an undefined secret reaches the collector as the literal text `$(QEOS_API_KEY)`, and the upload
  fails with 401 (without failing the pipeline, by default).
- **GitLab template:** `templates/qav-collector.gitlab-ci.yml` became `templates/qeos-collector.gitlab-ci.yml`,
  its jobs `.qav-collector` / `qav-collector-upload` became `.qeos-collector` / `qeos-collector-upload`
  (rename a job override), and its variables became `QEOS_PATTERNS`, `QEOS_EXTRA_ARGS` and
  `QEOS_COLLECTOR_REF`. The `QAV_*` versions of those three still apply when the new ones are unset.
- **Release assets:** the single-file build is `qeos-collector.pyz` and the image is
  `ghcr.io/carneiru/qeos-collector`. Each release also publishes the same file as `qav-collector.pyz`
  and the same image as `ghcr.io/carneiru/qav-collector`, so existing download URLs and image pins keep
  getting updates.

## Use

Create an API key for the project in the platform, store it as a CI secret named `QEOS_API_KEY`,
and run the collector after the tests — also when they fail:

```bash
export QEOS_URL=https://qeos.example.com
qeos-collector upload "reports/**/*.xml"
```

All matching files become **one run**. On GitHub Actions, GitLab CI, Jenkins and Azure Pipelines the commit, branch
and job URL are detected automatically. If an upload is retried after the platform stored it but
the answer was lost, the collector's Idempotency-Key makes the platform return the stored run
instead of storing it twice.

### GitHub Actions

```yaml
      - name: Run tests
        run: pytest --junitxml=reports/junit.xml

      - name: Upload results to QEOS
        if: always()
        env:
          QEOS_URL: https://qeos.example.com
          QEOS_API_KEY: ${{ secrets.QEOS_API_KEY }}
        run: |
          pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@collector-v0.5.1#subdirectory=collector"
          qeos-collector upload "reports/**/*.xml"
```

### GitLab CI

```yaml
test:
  script:
    - pytest --junitxml=reports/junit.xml
  after_script:
    - pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@collector-v0.5.1#subdirectory=collector"
    - qeos-collector upload "reports/**/*.xml"
  variables:
    QEOS_URL: https://qeos.example.com
  # QEOS_API_KEY: a masked CI/CD variable in the project settings
```

The remote template uploads from its own `.post` job, where `CI_JOB_MANUAL` (a per-job value) is not seen, so
a manual test job inside an automatic pipeline would be stored as automatic. Pass `--trigger manual` through
`QEOS_EXTRA_ARGS`, or upload from the test job itself (as above).

### Jenkins

```groovy
post {
  always {
    withCredentials([string(credentialsId: 'qeos-api-key', variable: 'QEOS_API_KEY')]) {
      sh '''
        pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@collector-v0.5.1#subdirectory=collector"
        QEOS_URL=https://qeos.example.com qeos-collector upload "target/surefire-reports/*.xml"
      '''
    }
  }
}
```

`import-features` skips itself when the branch is not the sync branch (the repository's default branch, or `QEOS_IMPORT_BRANCH`).
If the agent provides no branch (a pipeline without SCM, `GIT_BRANCH` unset) the command cannot tell and
runs. Guard the stage with `when { branch '<default branch>' }` or make sure `GIT_BRANCH` is set; the server's
mass-archive guard is the backstop.

### Azure Pipelines

```yaml
steps:
  - script: mvn test   # or pytest --junitxml=reports/junit.xml, dotnet test --logger trx, …
  - script: |
      pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@collector-v0.5.1#subdirectory=collector"
      qeos-collector upload "**/TEST-*.xml"
    displayName: Upload test results to QEOS
    condition: always()        # report results even when the tests failed
    continueOnError: true      # a failed upload does not fail the pipeline
    env:
      QEOS_URL: https://qeos.example.com
      QEOS_API_KEY: $(QEOS_API_KEY)   # a secret variable reaches scripts only when mapped like this
```

Commit, branch (the source branch on a pull request), PR number, target branch and the build URL
are detected from `TF_BUILD` and the `BUILD_*` / `SYSTEM_*` variables; a retried job
(`System.JobAttempt`) is a new run. Reusable step template: `templates/qeos-collector.azure-pipelines.yml`.
Hosted agents cannot reach a platform on `localhost`: use a self-hosted agent on that network or
a deployment with a public address.

### See what would be sent

```bash
qeos-collector upload "reports/**/*.xml" --dry-run
```

prints the JSON and uploads nothing; no URL or key is needed.

## Options

Each option can also be set with the environment variable next to it. A flag wins over the
variable, and both win over what is detected from the CI system.

| Option | Variable | Meaning |
|---|---|---|
| `--url` | `QEOS_URL` | Platform URL (required unless `--dry-run`) |
| — | `QEOS_API_KEY` | The project's API key. Environment only, never a flag |
| `--ci-provider` | `QEOS_CI_PROVIDER` | `github_actions`, `gitlab_ci`, `jenkins`, `other` or `local` |
| `--branch` | `QEOS_BRANCH` | Branch name |
| `--commit` | `QEOS_COMMIT` | Commit SHA (7 to 40 hex characters; anything else is left out) |
| `--ci-run-url` | `QEOS_CI_RUN_URL` | Link to the CI job |
| `--environment` | `QEOS_ENVIRONMENT` | e.g. `staging` |
| `--idempotency-key` | `QEOS_IDEMPOTENCY_KEY` | Overrides the key derived from the CI job |
| `--ca-file` | `QEOS_CA_FILE` | Extra CA certificate to trust (a private CA, or the local stack's self-signed one) |
| `--component` | `QEOS_COMPONENTS` | `NAME@SHA` of a repo/version this run exercised, e.g. the product build an E2E suite ran against. Flag repeatable; variable comma-separated. Up to 20 |
| `--client-cert` | `QEOS_CLIENT_CERT` | Client certificate for mTLS, presented when the server asks for one |
| `--client-key` | `QEOS_CLIENT_KEY` | Private key belonging to `--client-cert` |
| `--trigger` | `QEOS_TRIGGER` | `manual`, `automatic` or `qeos`: how the run started. Overrides detection (see below) |
| `--fail-on-error` | `QEOS_FAIL_ON_ERROR=1` | Exit 1 if the upload fails |
| `--gate` | `QEOS_GATE=1` | Exit 1 if the run has failures outside quarantine, or could not be uploaded (see below) |
| `--spool` | `QEOS_SPOOL` | Directory keeping parts a failed upload could not deliver; the next invocation resends them first, under their original Idempotency-Key (so nothing is ever stored twice). Capped at 100 files; rejected uploads (401/409) are never spooled. Point it at a persistent runner path — a wiped workspace wipes the spool |
| `--dry-run` | — | Print the JSON; upload nothing |

## Run trigger and manual runs

The collector tells the platform how each run started (`run.trigger`), so a project can choose not to
collect manual runs (Project Settings, Collection). An explicit `--trigger` / `QEOS_TRIGGER` wins
(the legacy `QAV_TRIGGER` still works, with a deprecation warning); otherwise the CI environment decides:

| CI | `qeos` | `manual` | `automatic` |
|---|---|---|---|
| GitHub Actions | `GITHUB_EVENT_NAME=workflow_dispatch` and the event payload (`GITHUB_EVENT_PATH`) has `inputs.request_id` | `workflow_dispatch` without `request_id` and `GITHUB_TRIGGERING_ACTOR` not ending in `[bot]`; or `GITHUB_RUN_ATTEMPT` > 1 with a triggering actor not ending in `[bot]` | every other event (`push`, `pull_request`, `schedule`, `repository_dispatch`, ...) and dispatches by a bot |
| GitLab CI | — | `CI_PIPELINE_SOURCE=web`, or `CI_JOB_MANUAL=true` | any other `CI_PIPELINE_SOURCE` |
| Azure Pipelines | — | `BUILD_REASON=Manual` | any other `BUILD_REASON` |
| Jenkins | — | `BUILD_CAUSE` contains `MANUALTRIGGER` or `USERIDCAUSE` (needs a plugin that sets it) | `BUILD_CAUSE` set to anything else |

`GITHUB_TRIGGERING_ACTOR` falls back to `GITHUB_ACTOR`. An unreadable or missing event payload means no
`request_id`. Anything not matched is unknown: the field is left out and the run is collected. Jenkins
without `BUILD_CAUSE` is unknown; use `--trigger` there.

When the project has switched manual collection off and the run is manual, the platform answers 202 and
stores nothing. The collector prints
`qeos: run not collected: manual runs are not collected for this project` and sends no further parts. It
exits 0, also with `--fail-on-error` (that flag is about upload failures). With `--gate` the verdict comes
from the local results instead, since the platform has none to give: it prints
`gate: decided on local results (run not collected)` and exits 1 when any test failed or errored, else 0.
A person's re-run of a failing job therefore still fails the required check. If earlier parts of the run were
already stored, `stored before the discard: …` names them.

Any `--trigger` / `QEOS_TRIGGER` value other than `manual`, `automatic` or `qeos` is a configuration error
(exit 2). Collectors older than 0.5.0 send no trigger, so their runs are always collected.

Two cases to know:

- **A script dispatching with a person's token.** A scheduler that calls `workflow_dispatch` with a
  personal access token looks manual (the triggering actor is that person). Use a GitHub App or
  `GITHUB_TOKEN` for automated dispatches, or pass `--trigger automatic` in that workflow.
- **The container image.** It sees only the variables passed to it. Without `GITHUB_EVENT_NAME`,
  `GITHUB_TRIGGERING_ACTOR`, `GITHUB_RUN_ATTEMPT` and the event file (`GITHUB_EVENT_PATH`, mounted), the
  trigger is unknown and the run is collected. The composite action and `pip` installs see the runner's
  environment and need nothing extra.

## `qeos-collector check`

Verifies the setup without uploading — run it once when wiring a new pipeline:

```
qeos-collector check "reports/**/*.xml" --url https://qeos.example.com
```

It checks, in order: the URL shape, the TLS trust (`--ca-file` honoured), the
API key (a `GET /api/v1/collect/key` names the project it belongs to), and —
when patterns are given — that report files match and parse. Exits 2 on the
first failed check, 0 when everything passes.

## `qeos-collector import-features`

Keeps the project's test cases in sync with the Gherkin `.feature` files in your repository.
The API key (`QEOS_API_KEY`, environment only) is traded for a 5-minute import token that works
only for the case import of that project; changes it makes are recorded as made by CI.

```
qeos-collector import-features                       # every **/*.feature
qeos-collector import-features "features/**/*.feature" --dry-run
```

- **Branch rule.** It runs only on the sync branch: `--branch`, else `$QEOS_IMPORT_BRANCH`, else
  the repository's default branch. The default branch comes from the GitHub Actions event payload
  (`repository.default_branch`), GitLab's `CI_DEFAULT_BRANCH`, or the clone's `origin/HEAD`, and is
  `master` when none of them says (Azure Pipelines and most Jenkins agents: set
  `QEOS_IMPORT_BRANCH`). On any other detected branch it prints `skipped: on <branch>; cases sync from <name>`
  and exits 0, so the same pipeline step can run on every build.
- **Full by default.** The import is a full sync: cases of deleted `.feature` files are archived.
  `--no-full` compares only the files given and never archives anything.
- **Mass-archive guard.** The platform refuses a full import that would archive more than half of
  the imported cases (409). If that is intended, pass `--allow-mass-archive`.
- **Patterns.** Arguments, else `features:` in `.qeos.yml`, else `**/*.feature`. Paths with a `node_modules` segment are always skipped, and so are dot-directories; patterns cannot reach outside the working directory.
- `--dry-run` prints the plan and changes nothing; `--strict` exits 1 when a file fails to parse.

```yaml
features:
  - "features/**/*.feature"
```

| Code | When |
|---|---|
| 0 | Imported; skipped (not the sync branch); or parse errors without `--strict` |
| 1 | Network or TLS failure; 401/403/404, 409 or 413 from the platform; or parse errors with `--strict` |
| 2 | A configuration error: no URL, no key, no file matched, a file that is not UTF-8 text |

GitHub Actions:

```yaml
on:
  push:
    branches: [master]
jobs:
  import-features:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install "qeos-collector @ git+https://github.com/carneiru/QA-Vision-Platform@collector-v0.5.1#subdirectory=collector"
      - run: qeos-collector import-features
        env:
          QEOS_URL: ${{ vars.QEOS_URL }}
          QEOS_API_KEY: ${{ secrets.QEOS_API_KEY }}
```

## `.qeos.yml`

Project defaults, read from the working directory — flags beat environment
variables beat the file. Flat keys and string lists only (a built-in reader,
no YAML dependency); the API key is never accepted here:

```yaml
url: https://qeos.example.com
environment: staging
ca-file: certs/internal-ca.pem
spool: .qeos-spool
fail-on-error: true
patterns:
  - "reports/**/*.xml"
components:
  - product-api@a1b2c3d4e5f6
features:
  - "features/**/*.feature"
```

## CODEOWNERS

When the working directory has a `CODEOWNERS` file (root, `.github/` or
`docs/`), every result whose `file` matches a pattern carries its owners
(git semantics: last matching line wins). Shown on the run detail view —
a failing test names the team that owns it.

## Exit codes

| Code | When |
|---|---|
| 0 | Uploaded; nothing to upload; not collected (discarded, without `--gate`); or the upload failed and neither `--fail-on-error` nor `--gate` is set |
| 1 | The upload failed and `--fail-on-error` or `--gate` is set; or `--gate` found failures outside quarantine (on a discarded run: any failure or error in the local results) |
| 2 | A usage or configuration error: no URL or key, no file matched, an `http://` URL that is not localhost, an unusable `--ca-file`, an invalid `--trigger` / `QEOS_TRIGGER` |

By default an unreachable platform never turns a build red; a misconfigured collector always does.

## Gating on quarantine (`--gate`)

Quarantine a flaky test in the dashboard (Flaky view → Quarantine) and it keeps running and
showing up, but its failures stop counting. With `--gate`, the collector decides the build:

- It exits 1 when the run has failures outside quarantine, and 0 when every failure is
  quarantined.
- It fails closed: an upload that did not happen exits 1, because nothing was checked.
- The test step itself must not fail the job, so the collector can decide. In GitHub Actions use
  `continue-on-error: true` on the test step; in Azure Pipelines use `continueOnError: true`; in
  GitLab use `allow_failure: true` on the test command's job, or `|| true`.
- Older platforms that do not report quarantine count every failure.

## What it does with the files

- Reads `<testsuites>`/`<testsuite>` reports: pytest, Maven Surefire, Playwright, cucumber-js and
  anything else that writes JUnit XML. A test's status is `errored` if it has an `<error>`,
  else `failed` for `<failure>`, else `skipped` for `<skipped>`, else `passed`. Surefire's
  `flakyFailure`/`rerunFailure` elements become per-attempt results, so flaky tests show up
  as pass+fail within one run.
- Also reads, detected by the root element: .NET TRX (`<TestRun>`, vstest/`dotnet test`),
  NUnit 3 (`<test-run>`), xUnit.net v2 (`<assemblies>`) and TestNG (`<testng-results>`).
  Formats mix freely in one upload; every file lands in the same run.
- Cucumber JSON (the classic formatter of cucumber-jvm/js/rb): each scenario becomes one
  result (feature name as suite, feature uri as class), background steps count into their
  scenario, a failed step fails the scenario, and undefined/pending steps leave it skipped.
- Playwright's JSON reporter (`--reporter=json`): every retry attempt is kept as its own
  result (a flaky spec shows as fail+pass in one run), project name as suite, spec file as
  class, `timedOut` counts as failed and `interrupted` as errored.
- Skips, with a warning, files over 50 MB, files that are not well-formed XML, and files that
  declare a DOCTYPE or entities (JUnit never needs one; refusing them blocks XML entity attacks).
- Cuts failure messages and output to 64 KB, as the platform does.
- More than 20,000 results (or 9 MB) are sent as several runs, `part 1 of N` and so on.

## Network and security

- HTTPS is required, except for `http://localhost`, `127.0.0.1` and `::1`.
- Certificates are always verified; there is no option to turn that off. Use `--ca-file` for a
  private CA.
- `HTTPS_PROXY` and `NO_PROXY` are honoured.
- Redirects are not followed, so the key is never sent anywhere but `QEOS_URL`.
- Retries: connection errors, timeouts and 5xx answers are retried after 1, 2, 4 and 8 seconds;
  429 waits for `Retry-After` (at most 10 s). At most 5 attempts and 2 minutes per run.
- The API key is never printed.

## Develop

```bash
cd collector
uv venv --seed --python 3.9 .venv
.venv/Scripts/python -m pip install -e . pytest    # .venv/bin/python on Linux/macOS
.venv/Scripts/python -m pytest -q
```

A release is a git tag `collector-v<version>` on this repository, matching `__version__` in
`src/qeos_collector/__init__.py`.
