# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two confirmed audiences, served equally:

- **QA / SDET engineers** triaging CI results daily: which tests failed, which
  are flaky, what regressed on which branch or environment. Per-test
  drill-down is their job.
- **Engineering managers** reading suite health weekly: pass-rate trends, run
  volume, flaky counts. Aggregates over drill-down.

## Product Purpose

QEOS ingests test results from any CI (JUnit XML, Cucumber and Playwright
JSON and more via the `qeos-collector` agent), stores them per project, and
turns them into analytics: trends, per-test statistics and history, run
comparison, failures grouped by cause, flaky-test detection with quarantine,
and a filterable, printable Report per period. It also keeps a test-case
catalogue in sync with the team's Gherkin features and starts runs in the
team's own GitHub Actions, and shows a failing scenario's failed step in red
(and a skipped scenario's stopping step in yellow) where the team reads it, and
on each run which step failed across how many test cases and since when. Success: a team answers "what is broken, what is
flaky, what is getting worse" from one place instead of scrolling CI logs.

## Positioning

AI-powered test analysis is the destination (Phase 6: failure pattern
recognition, risk-based prioritization, predictive analytics — not yet
built). Today's honest claim: a self-hosted platform whose flaky detection
distinguishes **confirmed** flakiness (same commit + environment, both passed
and failed) from **suspected** (statistical flip rate) — present that
distinction, never blur it. Do not market AI capabilities that do not exist
yet.

## Operating Context

- Results arrive from CI (GitHub Actions, GitLab CI, Azure Pipelines,
  Jenkins) via the collector; engineers open the dashboard after a red build,
  a failure notification (Slack, Teams, email) or when a flaky ticket lands;
  managers open it in weekly reviews or read the weekly summary.
- Microservices behind one NGINX gateway: auth-service (JWT, MFA, Google and
  Microsoft SSO, an optional Microsoft-only sign-in mode with a superuser break-glass), organization-service (orgs, members, roles, invitations),
  project-service (projects, repositories, settings), ingestion-service (runs,
  results, analytics, report, notifications), test-management-service (cases,
  suites, Gherkin sync, runs from QEOS), `dashboard/` (React SPA).
- Everything is deployed as containers from the repository-root
  docker-compose (production: one VM behind a Caddy TLS edge); same-origin
  API at `/api/v1/*`.

## Capabilities and Constraints

- Analytics API (read-only apart from quarantine): trends by day, week or
  month in any IANA time zone; per-test list, history; flaky detection with
  `window_days` up to 90, served from daily rollups (3.9 s at 90 days on ~2M
  results, against 11.3 s live — see the ingestion README).
- Collection: a project can switch off collection of runs a person started by hand in CI
  (Settings › Collection, owners and admins); the platform answers 202 and counts what it skipped.
- Log values (ADR-032): per-project regular expressions (Settings › Log values, up to 20) pick values such as a trip
  id out of each result's masked log; every Last runs bar's tooltip, the test case page and the feature page's cards
  show them, copyable and optionally linked to an https page. Logs are stored masked and cut to 64 KB; adding a
  pattern re-scans the runs of the last 90 days. Needs collector 0.9.0 and a test repository that attaches its log
  lines to the scenario.
- Access model: organization membership grants project access; roles are
  owner/admin/member/viewer/billing_manager (viewers and billing managers
  read only).
- `test_key` values contain `/`, `::`, spaces — always URL-encoded.
- `pass_rate` is a 0..1 fraction or null; null renders as "—".
- Internal tool: every dashboard surface is an authenticated Operate
  surface. No marketing or landing pages are planned.

## Evidence on Hand

- Real ingested runs exist only in dev/test stacks; production data is
  per-deployment. Screens show real ingested data or honest empty states —
  never fabricated metrics, testimonials, or benchmarks.
- Benchmarks documented in `platforms/ingestion-service/README.md`.

## Product Principles

1. Truth over polish: numbers shown are exactly what the API computed;
   absence of data is shown as absence, not zero.
2. Triage speed first: an engineer lands on "what is broken now" in one
   screen; depth (history, commits) is one click away.
3. Confirmed vs suspected is a first-class distinction wherever flakiness
   appears.
4. Same platform truth for both audiences: managers get aggregates of the
   same data engineers drill into, not a separate metric set.
5. Self-hosted modesty: no claims (AI or otherwise) ahead of shipped
   capability.

## Overview Rules

- The Overview is the triage screen (Principle 2), built from widgets over the existing analytics: no
  widget computes a new metric, and none uses AI.
- What a person sees: their personal layout for the project, else the project default (set by owners
  and admins), else the built-in four cards (latest run, failing in latest run, pass rate this week,
  flaky tests in 14 days). With nothing configured it looks as it always did.
- Every role, viewers included, may keep a personal layout; "Reset to project default" removes it, so
  later changes to the default reach that person again.
- Fifteen widget types; a type may appear more than once with different settings (period 7, 14 or
  30 days; 5 or 10 rows; all branches or one, where no branch setting means all branches). Three
  templates: QA lead, Developer, Flaky hunt. At most 24 widgets per layout.
- "My" widgets match by name: My recent failures shows failed runs whose commit author, as git records
  it, is exactly the person's name (ignoring case): their QEOS full name by default, or how git spells
  it, set in the widget. It reads the newest 50 failing runs whose author contains the name, then keeps
  the exact name, so a name that is a common substring of others' names can push the person's own runs
  off that page. Matching by email is a later improvement
  (TODO.md). My suites lists the suites the person created.
- Honest states per widget (Principle 1): a branch with no runs in the period says "No runs on
  <branch> in the last N days"; a failure stays in its own card with Retry; missing data is never
  shown as zero.

## Test Impact Rules

- QEOS suggests the tests a change is likely to affect from history only: which tests newly failed after earlier
  changes to the same files or folders (a path unit is the file plus its 3 nearest parent folders; noisy files such
  as lock files are ignored). No coverage instrumentation, no AI (ADR-029).
- Every suggestion explains itself: the file or folder, in how many of the runs that changed it the test newly
  failed, and how often it fails otherwise. Tests whose file changed, that already fail on the branch, or that have
  no history yet are always included, with that label instead of statistics.
- Honest by construction (Principle 1): the suggestion stored with a run is made before its results are read, and
  its outcome is recorded (which new failures it caught and which it missed). The trust figure is the catch rate,
  always with the average suggestion size beside it, so suggesting everything cannot look good. Live suggestions
  and replayed history (`--backfill-days`) are shown separately.
- Below 20 runs with changed files, QEOS says "Not enough history yet" rather than guessing; a run with no change
  data gets a compact one-line card, not an empty one.
- Suggestions decide what to run **first**; runs never skip tests by default.
  - In CI, the collector's `run-impact` (0.7.0, Cucumber) runs them first and then the rest of the suite, as one
    run.
  - When QEOS cannot score a change (no key, a key without the permission, no history of the change, QEOS out of
    reach), the whole suite runs and the log says why: a suggestion never costs a test run.
  - CI reads suggestions only with an API key a project owner or admin has allowed to (keys are upload-only by
    default).
  - A team may opt into running only them (`--suggested-only`, with the full suite as fallback when there is no
    suggestion).
  - Such runs are marked "Suggested tests only" on the run page, the runs list, failure alerts and the weekly summary.
  - They never count in the impact statistics or the accuracy figure: a run of only the suggested tests cannot
    show what the suggestion missed.
- **Run likely affected** selects the linked cases. A suggested test with no linked case is listed as not runnable
  from QEOS, never silently dropped.

## Accessibility & Inclusion

- WCAG AA: chart and table contrast meets AA; status is never conveyed by
  color alone (labels/legends always present); colorblind-validated status
  palette (passed #0ca30c, failed #d03b3b, errored #c4501f light / #ec835a
  dark, skipped yellow #a16207 light / #facc15 dark; DESIGN.md holds the tokens).
- Dark and light mode are both first-class, following the OS preference.
