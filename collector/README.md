# qeos-collector

Uploads JUnit XML test results from a CI job to the QEOS platform. Standard library only,
Python 3.9 or newer, nothing else to install. From 0.7.0 it also prints the tests a change likely affects
([`impact`](#qeos-collector-impact)) and runs them first in CI ([`run-impact`](#qeos-collector-run-impact-cucumber),
Cucumber).

## Install

```bash
pip install "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.9.1#subdirectory=collector"
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
  `ghcr.io/atriis/qeos-collector`. Releases up to 0.9.1 also published the same file as `qav-collector.pyz`
  and the same image as `ghcr.io/atriis/qav-collector`; from the next release they do not, and the
  `qav-collector` package is gone. Move a download URL or an image pin to the `qeos-collector` name.

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
          pip install "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.9.1#subdirectory=collector"
          qeos-collector upload "reports/**/*.xml"
```

### GitLab CI

```yaml
test:
  script:
    - pytest --junitxml=reports/junit.xml
  after_script:
    - pip install "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.9.1#subdirectory=collector"
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
        pip install "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.9.1#subdirectory=collector"
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
      pip install "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.9.1#subdirectory=collector"
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
| — | `QEOS_ACTION_EXTRA_ARGS` | More flags as one string, split into words as a POSIX shell would (quotes group; nothing is expanded or run; a backslash escapes, so write paths with `/`). Flags only: a `--` or a word that is no flag's value is refused (exit 2), so nothing can start a test command. The variable is not passed on to the test command. The GitHub Action passes its `extra-args` this way. GitLab's `QEOS_EXTRA_ARGS` is a different variable, which the template puts on the command line |

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

It also says whether the key may read test suggestions, which `qeos-collector impact` needs:
`Test suggestions: allowed` or `Test suggestions: not allowed`. A platform older than suggested tests first
prints neither.

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
      - run: pip install "qeos-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.9.1#subdirectory=collector"
      - run: qeos-collector import-features
        env:
          QEOS_URL: ${{ vars.QEOS_URL }}
          QEOS_API_KEY: ${{ secrets.QEOS_API_KEY }}
```

## `qeos-collector impact`

New in 0.7.0. Prints the tests the current change likely affects (test impact analysis, ADR-029), to run them first
or to feed another tool:
- **The change** is the one an upload would send: the pull- or merge-request base, else the commit's parent. The
  checkout needs that history: `fetch-depth: 0` on pull requests, `fetch-depth: 2` or more on pushes. Without it
  there is no change data and the command exits 3. A change with no changed files is never sent.
- **The scoring:** QEOS scores the change with the project API key (`POST /api/v1/collect/impact`).
- **The key's permission:** API keys are upload-only by default. A project owner or admin allows **test
  suggestions** for a key, when creating it or later in Project Settings > API keys. Without it QEOS answers 403
  and the command exits 2: "This API key may not read test suggestions. Ask a project owner or admin to allow test
  suggestions for this key." `qeos-collector check` says whether the key has it.

```bash
qeos-collector impact                     # Cucumber locations when the repository has .feature files
qeos-collector impact --format list       # suite<TAB>class<TAB>name, one test per line
qeos-collector impact --format json --out impact.json
```

- **`--format cucumber`:**
  - one `path/to/x.feature:LINE` per line, with an outline's rows each on their own line;
  - the lines come from the local `.feature` files (English keywords);
  - a scenario whose line is unknown (a `classpath:` uri, another language) is printed as a name filter,
    `--name "^Pays with card$"`. Characters special to a regular expression or to the shell become `.`. The
    filters are printed for POSIX shells (bash, sh); `run-impact` (also 0.7.0) never passes names and is the
    supported way to run the suggestion, on Windows too.
- **`--format list`:** `suite<TAB>class<TAB>name`.
- **`--format json`:** the whole suggestion, with each test's `kind` and `evidence`.
- **`--out FILE`:** write there instead of stdout, as UTF-8 with LF line endings. When there is nothing to suggest,
  or QEOS cannot answer, the file is emptied, never left with an earlier list.
- **`--url`, `--ca-file`, `--client-cert`, `--client-key`, `--branch`, `--commit`:** as for `upload`.

| Exit | Meaning |
|---|---|
| 0 | A suggestion was printed. Below 20 runs of history it holds only labelled tests: failing on this branch, test file changed, no history yet |
| 3 | Nothing to suggest: no change data (or no changed files), or no test is likely affected |
| 4 | QEOS could not be reached, was overloaded (429, 5xx), or ran out of time scoring (503 `impact_timeout`) |
| 2 | A configuration error: no URL or key, TLS trust, an invalid key (401), a key without the test suggestions permission (403), a QEOS older than this command (404) |

None of them means "tests failed": a pipeline branches on them.

## `qeos-collector run-impact` (Cucumber)

New in 0.7.0. Runs a Cucumber test command with the scenarios the change likely affects **first**, and every other
scenario after. Both are uploaded as one run (`scope` `full`, with its `stages`), so failures in the changed area show
up in minutes and the full suite still runs.

```bash
qeos-collector run-impact -- npx cucumber-js --tags "not @wip"
qeos-collector run-impact -- mvn -q test -Dcucumber.filter.tags="not @wip"
qeos-collector run-impact --cucumber js -- npm test
```

1. QEOS scores the change, as `impact` does. The key needs the **test suggestions** permission.
2. **Discovery:** the command runs as a Cucumber dry run with a JSON report, with your own tags, profiles and
   paths, to list the scenarios it would run.
3. **Stage 1:** the suggested scenarios among them, through a rerun file. A suggested test matches a scenario on
   its feature file and name, so every row of an outline with that name goes with it.
4. **Stage 2:** every other one, through a second rerun file, scenarios without a name included. No scenario runs
   twice, and no stage runs with an empty rerun file. Suggested tests that the command does not run (left out by
   its filters, or not Cucumber) are listed as skipped by the filter.
5. Both stages' JSON reports are uploaded as one run.

**What it needs:**
- **The change.** The checkout needs the history the diff needs, as for `impact`: `fetch-depth: 0` on GitHub pull
  requests, the target branch fetched on GitLab merge requests, at least 2 commits elsewhere. Without it the whole
  command runs as one stage.
- **The key's permission.** The API key needs the **test suggestions** permission, which a project owner or admin
  turns on for the key (Project Settings > API keys). Without it the whole command runs as one stage too.
- **History.** Suggestions need 20 runs with changed files. Before that, only the labelled tests (test file changed,
  failing on this branch, no history yet) are suggested.
- **Cucumber**, as below. Other runners (JUnit with Maven or Gradle, pytest, Playwright) are not supported yet.

**Scoring never skips your tests.** When QEOS cannot score the change, for whatever reason (an invalid key, a key
without the permission, a QEOS older than this command, a 422, 429 or 5xx, a timeout, no answer, no change data), the
command runs as given, as one stage `all`, and the log says why (`warning: cannot score the change: …`). When QEOS
answers that nothing is likely affected, or none of the suggested tests is among the command's scenarios, the command
also runs as one stage.

- **When the collector cannot reach QEOS as configured** (no URL or API key, as on a fork pull request without the
  secret; a key that is not printable ASCII; an unusable `--ca-file`; a broken or non-UTF-8 `.qeos.yml`), the command
  still runs as one stage `all`. Nothing is uploaded, and the log says why (`warning: not uploaded: …`). The exit
  code is the tests', or 1 with `--gate` or `--fail-on-error`.
- **When the stages cannot be planned**, the command also runs as one stage `all`, with
  `warning: cannot plan the stages: …`. That is a dry run that writes no JSON report, a dry run listing a scenario
  without a line (which could go in no rerun file, so it would run in neither stage), or an error in run-impact
  itself.
- **When a stage writes no report** (it crashed), its scenarios have no results. The run is then uploaded as
  suggested tests only (`impact-subset`), with a warning, so it never counts as a full run in the statistics.

| `--cucumber` | Detected from | What run-impact appends |
|---|---|---|
| `js` (cucumber-js) | `cucumber-js` or `@cucumber/cucumber` in the command | `--dry-run`, `--format json:FILE`, and a rerun file `.qeos-impact/…/@stage-1.txt`. Both paths are relative to the working directory: cucumber-js 12 reads a rerun file only from a relative path to a file whose name starts with `@` |
| `jvm` (Maven, Gradle) | `mvn`, `mvnw`, `gradle` or `gradlew` first | `-Dcucumber.execution.dry-run=true`, `-Dcucumber.plugin=json:FILE`, `-Dcucumber.features=@FILE`. When the command already sets `-Dcucumber.plugin=…`, `json:FILE` is added to it after a comma, so your plugins still run |
| `ruby` | `cucumber` or `bundle exec cucumber` first | `--dry-run`, `--format json --out FILE`, `@FILE` |

- **`--cucumber`:** pass it when the command hides the runner (`npm test`, a script). For `npm` and `pnpm`,
  run-impact adds the `--` the script needs.
- **A shell command line:** `qeos-collector run-impact -- bash -c 'npx cucumber-js --tags "not @wip"'` (or
  `sh -c`). The script runs as written, and Cucumber is detected from its words. run-impact appends `"$@"` to the
  script and passes its own arguments as words, never as shell text, so they reach the script's last command. The
  GitHub Action and the Jenkins step run `test-command` this way. Feature paths inside the script are not visible
  to run-impact: when they add scenarios to a stage, the stage-1 check refuses the command.
- **Gradle:** it hands `-D` properties to its own JVM, not the test JVM. Forward them in `build.gradle`:
  `test { systemProperties System.properties.findAll { it.key.startsWith("cucumber.") } }`.
- **Windows:** programs are found as a shell would (`npx.cmd`, `mvn.cmd`), never run through a shell by
  run-impact, and every path it hands Cucumber uses `/`. A `.cmd` or `.bat` runs through cmd.exe, so for
  cucumber-jvm and Ruby Cucumber the working directory must not contain `% ! & | < > ^ "`; run-impact refuses
  before running anything. The check looks at the top-level program only: a `bash -c "mvn …"` command line on a
  Windows agent whose path holds those characters is the author's responsibility.

**Feature paths.** Paths the command names (`npx cucumber-js features/checkout/`, `-Dcucumber.features=…`) are left
out of the stages: the rerun files choose the scenarios.

Paths run-impact cannot see would add scenarios to every stage, because cucumber-js adds a profile's `paths` to the
rerun file's. Such paths come from:
- an npm script;
- a profile or config file with `paths`;
- `--shard`.

So before any test runs, a dry run of stage 1 must select exactly the planned scenarios. Otherwise run-impact runs
nothing and exits 2, saying why. Select features with tags instead.

**Modes.**
- **`--fail-fast`:** when stage 1 fails, stop before stage 2. Stage 1 fails when a suggested scenario fails, or when
  the command exits non-zero without writing a report (it crashed). The run is uploaded as suggested tests only,
  stopped after stage 1. When every scenario was suggested, stage 1 was the whole suite: the run is a full run.
- **`--suggested-only`:** run stage 1 only. The run is uploaded as suggested tests only, and it never counts in the
  impact statistics or the accuracy figure. When there is no suggestion (nothing suggested, not enough history, none
  of the suggested tests among the command's scenarios, or QEOS cannot score the change), the full suite runs
  instead and the log says why.
- **`--no-fallback`** (with `--suggested-only`): in that case run nothing, upload nothing, and exit 2, 3 or 4 as
  `impact` would. It is the only way run-impact ends without running tests because of scoring.
- **`--gate`:** judges the uploaded run, as for `upload`. It exits 1 on failures outside quarantine, 1 when
  nothing could be uploaded, and 1 when a stage crashed without a report (its scenarios have no results to judge).

| Exit | When |
|---|---|
| The test command's | Without `--gate`: the first failing stage's exit code, else 0 |
| 0 / 1 | With `--gate`: the gate's verdict on the uploaded run; 1 when nothing was uploaded, or when a stage crashed without a report |
| 1 | `--fail-on-error`: the tests passed and the upload failed, or a stage crashed without a report |
| 2 | Before any test runs: no command, an unknown Cucumber (pass `--cucumber`), a command run-impact cannot narrow (profile `paths`, `--shard`), a working directory cmd.exe would change, a program that cannot be started. Running a wrong subset silently would be worse than running nothing; every other problem runs the command as given |
| 2 / 3 / 4 | `--suggested-only --no-fallback` with nothing to run: as `impact` (2 also when the collector cannot reach QEOS as configured, or the stages cannot be planned) |

**Summary.**
- **What it holds:** the suggested tests with their evidence, each stage's scenarios, failures and duration, and the
  time to the first failure ("first failure after 1m 02s (full suite 16m 15s)"). Durations read as the dashboard
  shows them.
- **In GitHub Actions** (both `GITHUB_ACTIONS` and `GITHUB_STEP_SUMMARY` set): a table in the job's step summary.
- **Anywhere else, or when that file cannot be written:** the same lines in the log.
- The API key never appears in it, even when a test name or path holds it.

**In CI.**
- **GitHub Actions:** the action's `impact: first` (or `only`) and `test-command` inputs run the tests through
  run-impact (`docs/SETUP.md`, "Suggested tests first in CI").
- **Jenkins:** `qeosCollectorUpload(impact: 'first', testCommand: '…')` (`collector-jenkins/README.md`).
- **GitLab and Azure:** the commented examples at the end of the templates in `templates/`.
- **Anywhere else:** `qeos-collector run-impact -- <your Cucumber command>` as the test step.

**What QEOS shows.** The run page has a line "Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2
(the rest) 340 tests in 14m 10s · first failure after 42.5 s (full suite 15m 15s)". A run of only the suggested
tests (`--suggested-only`, a `--fail-fast` stop, or a stage that wrote no report) is marked **Suggested only** on the
run page, in the runs list (the **Full runs only** chip hides such runs), in failure alerts and in the weekly
summary. It never counts in the impact statistics or the accuracy figure.

**The test command never sees the key.** `QEOS_API_KEY`, `QAV_API_KEY` and `QEOS_ACTION_EXTRA_ARGS` are removed from
its environment: the tests have no use for them, and their logs are not scrubbed.

**Working files** live in `.qeos-impact/<random>/` and are removed at the end. On first use run-impact writes
`.qeos-impact/.gitignore` (`*`), so git never lists them. When the working directory is read-only, they go in a
temporary directory instead, with a warning. The upload options are those of `upload` (`--url`,
`--environment`, `--component`, `--spool`, …).

**The exit code** is the test command's, from the first failing stage, so the build fails when tests fail. When the
upload fails after the tests ran, even for a configuration problem, the exit code stays the tests'.

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
`impact` and `run-impact` (0.7.0) have their own codes: see their sections. `run-impact` exits with the tests' code, and
runs them even when the collector is misconfigured.

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
  as pass+fail within one run. From 0.9.0 a test case's `<system-out>` is sent as its `log` (cut to 64 KB; blank
  output sends nothing), for log values in QEOS.
- Also reads, detected by the root element: .NET TRX (`<TestRun>`, vstest/`dotnet test`),
  NUnit 3 (`<test-run>`), xUnit.net v2 (`<assemblies>`) and TestNG (`<testng-results>`).
  Formats mix freely in one upload; every file lands in the same run.
- Cucumber JSON (the classic formatter of cucumber-jvm/js/rb): each scenario becomes one
  result (feature name as suite, feature uri as class), background steps count into their
  scenario, a failed step fails the scenario, and undefined/pending steps leave it skipped.
  A failed scenario also carries `failed_step` (`{"text": "When I search", "line": 5}`, text cut to
  1000 characters, `line` omitted when the report has none); the other formats send none.
  From 0.9.1 a skipped scenario carries `failed_step` too: the step it stopped at, the first that did not pass
  (undefined, pending, ambiguous, or skipped when a hook skipped the scenario before any step ran), in the same
  shape (text, line, definition, pattern), with `message` saying why ("Undefined step", "Pending step",
  "Ambiguous step" or "Skipped") and `details` holding the step and Cucumber's own text when it has one. A skipped
  scenario with no steps sends neither. Any platform that takes `failed_step` (migration 021) stores it.
  collector 0.6.0 sends `failed_step`; it needs a platform with ingestion migration 021, so upgrade the platform first (an older platform answers 422 and the run is not stored; this holds for 0.8.0 too, which still sends `failed_step`).
  From 0.8.0 it also carries `definition`, the step definition that ran the step (Cucumber's `match.location`, cut to 500 characters, left out when the report has none), and `pattern`, the step text with each matched argument replaced by `{…}` (`When I search {…}`, cut to 1000 characters; the text itself when the report lists no arguments, as cucumber-js's does, or they do not fit the text). QEOS uses them to group one step's failures across test cases.
  Collector 0.8.0 also works with a platform that has migration 021 but not 022 (the one that adds these two fields): that platform answers 422 naming `failed_step.definition` or `failed_step.pattern`, and the collector then sends the upload once more without `definition` and `pattern`, under the same Idempotency-Key, and logs one line saying the platform is older than the collector. No other 422 is retried (a platform without migration 021 refuses `failed_step` itself, so there is nothing to strip); uploads saved with `--spool` get the same retry when they are resent.
  Collector 0.9.0 sends `log` (above); a platform without ingestion migration 023 answers 422 naming `results.N.log`, and the collector sends the upload once more without any result's `log`, under the same Idempotency-Key, and logs one line saying the platform is older than the collector. A platform older than both 022 and 023 names both in one 422: both are stripped in that one retry.
  From 0.9.0 each scenario also carries `log`: its text attachments (`text/x.cucumber.log+plain`, as cucumber-js's `this.log()` writes them, and `text/plain`; decoded from base64 when so encoded) in step order, hook and Background steps included, joined by newlines and cut to 64 KB; images and other attachments never. No text, no `log`. QEOS masks it, stores it and reads log values from it.
- Playwright's JSON reporter (`--reporter=json`): every retry attempt is kept as its own
  result (a flaky spec shows as fail+pass in one run), project name as suite, spec file as
  class, `timedOut` counts as failed and `interrupted` as errored.
- Skips, with a warning, files over 50 MB, files that are not well-formed XML, and files that
  declare a DOCTYPE or entities (JUnit never needs one; refusing them blocks XML entity attacks).
- Cuts failure messages, output and logs to 64 KB, as the platform does.
- More than 20,000 results (or 9 MB) are sent as several runs, `part 1 of N` and so on.

## Network and security

- HTTPS is required, except for `http://localhost`, `127.0.0.1` and `::1`.
- Certificates are always verified; there is no option to turn that off. Use `--ca-file` for a
  private CA.
- `HTTPS_PROXY` and `NO_PROXY` are honoured.
- Redirects are not followed, so the key is never sent anywhere but `QEOS_URL`.
- Retries: connection errors, timeouts and 5xx answers are retried after 1, 2, 4 and 8 seconds;
  429 waits for `Retry-After` (at most 10 s). At most 5 attempts and 2 minutes per run. The one other retry is the 422 about `failed_step.definition` or `failed_step.pattern` above, sent once more without those two fields.
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
