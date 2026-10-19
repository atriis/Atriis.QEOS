# ADR-025: Run tests from QEOS through the customer's CI (workflow_dispatch, encrypted PAT, no execution on our side)

Status: Accepted (2026-10-07) · Spec: `docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md`

Amended by ADR-035: repository suites run their own workflow, and the limit is one active run per workflow.

## Context
Users asked to start tests from the Cases page: one case, a selection, or a whole suite. The tests
live in the customer's repository, need the customer's environment and secrets, and already run in
the customer's CI (ADR-023 imports their `.feature` files; the collector uploads the results). QA
Vision has no runners. Executing customer code on our infrastructure would make us run untrusted
code with network access and would need isolation, quotas and secret handling that the platform does
not have.

## Decision
- **QEOS never executes tests.** Play dispatches a GitHub Actions workflow in the customer's
  repository (`POST .../actions/workflows/{file}/dispatches` with `return_run_details`). The workflow
  runs Cucumber and uploads the results with the collector, so the run shows up in Results as any CI
  run does.
- **One credential per project: a personal access token.** A fine-grained token limited to one
  repository with "Actions: Read and write". It is stored Fernet-encrypted with `TM_SECRETS_KEY` in
  test-management (`ci_targets`), never returned (only the last 4 characters) and never logged.
  Owners and admins set it; the save is checked against GitHub first. Every 422 drops pydantic's
  `input` and `ctx`, so a token cannot come back in an error.
- **No worker.** State is refreshed by the GETs the dashboard already polls (at most every 5 s per
  request, at most 3 rows per list call, and no database transaction open during a GitHub call).
  Writes are conditional on the status that was read, so Stop is never overwritten.
- **One active run per project and workflow** (amended by ADR-035: first one per project, now one per workflow,
  so a repository suite can run beside a case selection), enforced by a partial unique index. A request is matched to its
  GitHub run through the run details of the dispatch, or by the title `QEOS #<id>` when GitHub
  answers 204 (`QA Vision #<id>`, set by workflows copied before the QEOS rename, still matches).
- **Selection becomes files and names.** `paths` and `names` are JSON arrays sent as workflow inputs.
  A whole-suite run skips manual cases and records `skipped_manual`; an explicit selection rejects
  them.
- **The workflow ships as a template** (`templates/github/qeos-run.yml` and `.mjs`), copyable
  from Project Settings. The customer owns it and must have it on the configured branch and on the
  default branch.

## Alternatives rejected
- **Run the tests on QEOS's infrastructure.** A far larger security surface, and the customer
  would have to hand over secrets and network access.
- **A GitHub App.** Short-lived installation tokens owned by no person are better, but need app
  registration, a callback and an installation flow. Parked in TODO.
- **A worker that polls GitHub.** One more moving part for a state that only matters while someone
  looks at it.
- **The token in the customer's repository secrets.** QEOS must call GitHub, so it needs the
  token itself.

## Consequences
- The token can dispatch any `workflow_dispatch` workflow in that repository (deploys included, with
  the repository's secrets) and read run logs. The README tells customers to use a dedicated
  repository or least privilege.
- A lost or changed `TM_SECRETS_KEY` makes stored tokens unreadable; owners save them again.
- GitHub only: other CI providers, run parameters and scheduled runs are future work.
- A run whose GitHub record disappears ends as cancelled "The run is no longer on GitHub", while the
  run may still continue there.
- Cucumber `--name` applies to every listed file, so a name picked from one file also runs a
  same-named scenario in another.

## Related Decisions
- [ADR-022: Test management is its own service](ADR-022-test-management-service.md)
- [ADR-023: Gherkin import: the repository owns imported cases](ADR-023-gherkin-import.md)
- [ADR-024: Service tokens for CI imports](ADR-024-service-tokens-for-ci-imports.md)
