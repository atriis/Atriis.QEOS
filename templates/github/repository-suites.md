# Repository suites: workflow snippets

QEOS can show each leg of your CI suite workflows as a suite, and run one leg from its Suites page.
This page has the three changes your workflows need. Atriis.Test.Automation.OBT is the worked example
(its `suite-*.yml` and `suite-runner.yml`).

It assumes the usual shape: a caller workflow per group (for example `suite-flights.yml`) with one job
that calls a reusable runner workflow (`suite-runner.yml`) and passes it a `matrix` JSON string with an
`include` list. Each row has `suite_id`, `suite_name` and `test_path` (space-separated folders ending in
`/` or `.feature` files), plus an optional whitespace-separated `expected-suites` list.

With the inputs left blank, nothing changes: every leg runs, the run keeps its usual title, and any
nightly, scheduler, rerun or manual run behaves as before.

## 1. Sync the workflows

In `qeos-sync-cases.yml`, sync the caller workflows along with the `.feature` files, and run the sync
when either one changes. List each caller workflow by name:

```yaml
on:
  push:
    paths:
      - "tests/features/**"
      - ".github/workflows/suite-flights.yml"
      - ".github/workflows/suite-hotels.yml"
```

```yaml
      - run: >-
          qeos-collector import-features "tests/features/**/*.feature"
          --suites .github/workflows/suite-flights.yml
          --suites .github/workflows/suite-hotels.yml
```

`--suites` needs collector 0.10.0 or later. The QEOS server must also be new enough to accept it:
an older one answers 422 and the whole sync fails.

You can use a glob such as `--suites ".github/workflows/suite-*.yml"`, but only if it matches
nothing except callers. A runner, a scheduler or a workflow whose matrix is not plain JSON (for
example one with `${{ inputs.parallel }}` in it) gives a warning at every sync and makes `--strict`
fail. In OBT, `suite-*.yml` also matches `suite-runner.yml`, `suite-scheduler.yml` and
`suite-custom-run.yml`, so OBT lists its five callers by name.

## 2. The inputs and the run-name (each caller workflow)

QEOS dispatches the caller with exactly `{"suites": "<suite_id>", "request_id": "<id>"}` on the CI
target's branch. It finds the run by its title, which must be **exactly** `QEOS #<request_id>`.

```yaml
name: Suite - Flights
# QEOS finds its run by the exact title "QEOS #<request_id>"; other runs keep their usual title.
run-name: ${{ inputs.request_id && format('QEOS #{0}', inputs.request_id) || 'Suite - Flights' }}

on:
  workflow_dispatch:
    inputs:
      suites:
        description: 'Set by QEOS: space-separated suite_ids to run. Blank = every leg.'
        required: false
        type: string
        default: ''
      request_id:
        description: 'Set by QEOS. Leave blank.'
        required: false
        type: string
        default: ''

jobs:
  suite:
    uses: ./.github/workflows/suite-runner.yml
    secrets: inherit
    with:
      suites: ${{ inputs.suites }}
      request_id: ${{ inputs.request_id }}
      # ...matrix, expected-suites and your other inputs as today
```

If the workflow already has a `run-name`, put the QEOS rule first and keep yours as the fallback:
`${{ inputs.request_id && format('QEOS #{0}', inputs.request_id) || <your expression> }}`.
A workflow without a `run-name` is titled with its `name`, so use that as the fallback.

QEOS treats a workflow as busy while any of its runs is queued, in progress, waiting, pending or
requested, and does not start a run then. A QEOS run still holds the workflow's `concurrency` group
while it runs. A scheduled run that starts meanwhile (a nightly, for example) waits behind it.
GitHub keeps only one pending run per group, so a second run that arrives while one is already
waiting replaces the waiting one. Leave a quiet window before scheduled runs, or keep QEOS runs short.

## 3. The runner: inputs and the select job

Add the two inputs to the runner's `workflow_call` inputs:

```yaml
      suites:
        description: Space-separated suite_ids to run (set by QEOS). Blank = every leg of the matrix.
        required: false
        type: string
        default: ''
      request_id:
        description: QEOS run request id.
        required: false
        type: string
        default: ''
```

Add a first job that narrows the matrix and `expected-suites` to the requested legs. A blank `suites`
passes both through unchanged. An unknown `suite_id` fails the run before any test runner starts.
`jq` is preinstalled on GitHub's Ubuntu runners.

```yaml
jobs:
  select:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    outputs:
      matrix: ${{ steps.filter.outputs.matrix }}
      expected-suites: ${{ steps.filter.outputs.expected-suites }}
    steps:
      - name: Filter the matrix to the requested suites
        id: filter
        shell: bash
        env:
          MATRIX: ${{ inputs.matrix }}
          EXPECTED_SUITES: ${{ inputs.expected-suites }}
          SUITES: ${{ inputs.suites }}
        run: |
          set -euo pipefail
          wanted=$(jq -cn --arg s "$SUITES" '[$s | splits("\\s+") | select(length > 0)]')
          if [ "$wanted" = "[]" ]; then
            matrix=$(jq -c '.' <<<"$MATRIX")
            expected=$(jq -rn --arg s "$EXPECTED_SUITES" '[$s | splits("\\s+") | select(length > 0)] | join(" ")')
          else
            unknown=$(jq -r --argjson wanted "$wanted" \
              '[.include[].suite_id] as $known | $wanted[] | select(. as $w | any($known[]; . == $w) | not)' <<<"$MATRIX")
            if [ -n "$unknown" ]; then
              while read -r id; do echo "::error::Unknown suite_id: $id"; done <<<"$unknown"
              exit 1
            fi
            matrix=$(jq -c --argjson wanted "$wanted" \
              '.include |= map(select(.suite_id as $id | any($wanted[]; . == $id)))' <<<"$MATRIX")
            expected=$(jq -rn --arg s "$EXPECTED_SUITES" --argjson wanted "$wanted" \
              '[$s | splits("\\s+") | select(length > 0) | select(. as $id | any($wanted[]; . == $id))] | join(" ")')
          fi
          echo "matrix=$matrix" >> "$GITHUB_OUTPUT"
          echo "expected-suites=$expected" >> "$GITHUB_OUTPUT"

  test:
    needs: select
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.select.outputs.matrix) }}
    # ...steps as today
```

Any later job that reads `expected-suites` (a report or reconciliation step) should add `select` to
its `needs` and read `${{ needs.select.outputs.expected-suites }}` instead of the input. Otherwise a
run of one leg reports every other leg as missing.

## Keep QEOS runs out of your history

A QEOS run usually runs one leg, so it should not become anyone's "latest run":

- Skip trend history when `request_id` is set: add `&& inputs.request_id == ''` to the `if:` of the
  steps that download and upload it (for Allure, the `allure-history` artifact).
- Any lookup of "the latest run" of a suite workflow (a rerun job with a blank run id, for example)
  should skip runs whose title starts with `QEOS #`:

  ```bash
  gh run list --workflow "$SUITE_WORKFLOW" --branch main --limit 30 --json databaseId,status,conclusion,displayTitle \
    --jq '[.[] | select(.status == "completed" and (.conclusion == "success" or .conclusion == "failure") and (.displayTitle | startswith("QEOS #") | not))][0].databaseId'
  ```

  A lookup that takes the newest run with a given artifact already skips QEOS runs, as long as those
  runs never upload that artifact.

## Suites made in QEOS

Suites built by hand in QEOS (a list of scenarios, not a workflow leg) run through `qeos-run.yml`
and `qeos-run.mjs` in this folder. Adapt `qeos-run.yml` to run like your suite legs: the same
cucumber profile and retry, the same secrets, the same post-run steps, and the same results upload. OBT's copy uses
`--profile ci` and `--retry 1`.
