# Run from QA Vision (Play and Stop v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution: subagent-driven.** A fresh implementer subagent per task, a fresh reviewer per task, then one whole-branch review.

**Goal:** People press Play on a case, a selection of cases or a suite. QA Vision dispatches the customer's GitHub Actions workflow `qa-vision-run.yml` for exactly those scenarios, follows the run, and can stop it.

**Architecture:**
- **test-management-service** gains three tables (migration 004), a Fernet "secret box" for the GitHub token, a small GitHub REST client, and two routers: `ci-target` (the per-project repository, workflow, branch and token) and `run-requests` (Play, polling and Stop).
  - There is no worker. A `GET` of an active request refreshes it from GitHub, at most every 5 s.
- **The gateway** routes `ci-target` and `run-requests` to test-management.
- **The dashboard** adds:
  - a Settings section (owners and admins);
  - Play on a case, a selection and a suite, behind an inline confirmation;
  - a `role="status"` run panel with Stop;
  - a "Requested runs" tab under Runs.
- **The OBT side** is delivered as two template files under `templates/github/`, which the user copies into the OBT repository. This plan never commits to the OBT repository.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pydantic 2, httpx and respx (already used for outbound stubs), and `cryptography` (Fernet, new). React 18, TS, TanStack Query 5, vitest and msw 2, lucide-react. Node 22 `node:test` for the template script.

**Spec:** `docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md`. The spec is binding. Executors read it with this plan.

## Global Constraints

Copied from the spec. Every task implicitly includes all of them.

- **Roles:**
  - `GET ci-target`, `GET run-requests` and `GET run-requests/{rid}` are open to every project role.
  - `PUT ci-target` and `DELETE ci-target` are for `owner` and `admin`.
  - `POST run-requests` and `POST run-requests/{rid}/stop` are for `owner`, `admin` and `member`.
  - `viewer` and `billing_manager` see state only.
  - The Settings section "Run from QA Vision" is visible to `owner` and `admin` only.
- **Limits:**
  - `case_numbers` holds 1 to 200 entries, so at most 200 cases per run.
  - **At most one active QA Vision run per project.** A partial unique index on `run_requests.project_id` covers `status IN ('queued','running','cancelling')`.
  - A `GET` refreshes an active request when `checked_at` is older than **5 seconds**.
  - **2 minutes** after the request with no matched run (fallback only, after a 204 dispatch), the status becomes `failed_to_start` with "The workflow did not start".
  - The expiry warning starts **14 days** before `token_expires_at`.
  - After **5 minutes** without results, the panel says "Results not received: check the QA Vision upload step".
  - Workers are fixed at 1 and retries at 0.
- **Regexes and names:**
  - repo: `^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$`.
  - workflow: `^[A-Za-z0-9._-]{1,100}\.ya?ml$`.
  - ref: a branch name, default `main`, following git branch-name rules (`git check-ref-format --branch`: no whitespace or control characters, none of `~ ^ : ? * [` or backslash, no `..`, `@{` or `//`, no leading or trailing `/`, no leading `-`, no trailing `.`, no part ending in `.lock`), at most 255 characters. Final fix wave A3.
  - OBT path: starts with `tests/features/`, ends with `.feature`, holds no control character and none of `\ : * ? " < > |`, and has no `..` segment. Arguments reach cucumber-js as an array, never through a shell.
  - Scenario selection is by file and **raw Gherkin scenario name**: `--name "^<name>$"`. In a Scenario Outline each `<placeholder>` becomes `.*`.
- **GitHub client:**
  - It uses `httpx` with a 10-second timeout and calls `https://api.github.com` only, **never following redirects**.
  - It sends `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`.
  - The repo and workflow are validated by regex before they go into a URL.
  - A rate limit (403 or 429 with `x-ratelimit-remaining: 0`) is reported as "GitHub rate limit, try again in N s", and the request does not change state.
  - Token expiry comes from the `github-authentication-token-expiration` response header. It is NULL when the header is absent.
- **GitHub messages (PUT, 422), verbatim:**
  - 401: "token invalid or expired".
  - 403: "token has no Actions access to this repository".
  - 404: "repository or workflow not found. The workflow file must exist on the repository's default branch".
- **Secrets:**
  - The token is encrypted with Fernet from `cryptography`, keyed by the `TM_SECRETS_KEY` environment variable.
  - Without the key, `PUT ci-target` returns 503 with "Running tests from QA Vision is not configured on this server", and `GET` reports `"available": false`.
  - **No response, log line or error message ever carries the token.** Responses show `token_last4` only.
- **Matching and status:**
  - The dispatch is `POST /repos/{repo}/actions/workflows/{workflow}/dispatches` with `{ref, inputs: {paths, names, request_id}, return_run_details: true}`.
  - **On 200**, GitHub's body `{workflow_run_id, run_url, html_url}` gives the run directly. The row stores `github_run_id` and `github_run_url` (the `html_url`, only if it starts with `https://github.com/`) at once, so Stop works immediately.
  - **On 204 (fallback only)**, the row keeps no run id. Polling then lists runs with `event=workflow_dispatch` and `created>=` the request time minus 1 minute, and matches on `display_title == "QA Vision #<id>"`.
  - GitHub's `queued`, `waiting`, `requested` and `pending` map to `queued`. `in_progress` maps to `running`. `completed` maps to `completed`, or to `cancelled` when the conclusion is `cancelled`, and the `conclusion` is stored.
- **Dashboard copy, verbatim:**
  - Settings: "Connected: owner/name · token …a1b2 · expires 12 Mar 2027", "Last changed by <name> on <date>", "The GitHub token expires on <date>. Replace it in Settings", "Replace token" and "Disconnect".
  - Play: "Run", "Run selected (n)" and "Run suite".
  - Confirmation: "+n more", "`repo` @ `ref`", "Tests may create real bookings in staging", "Run" and "Cancel".
  - Disabled Play: "Configure in Settings" (linked), "Viewers can't run tests", "A run is in progress" and "GitHub token expired".
  - Panel: "Queued", "Running · n tests · started by <name> · <elapsed>", "Passed", "Failed", "Cancelled", "Didn't start: <error>", "View in GitHub", "Stop this run?", "Stopping…", "Stopped by <name>", "Waiting for results…" and "Results not received: check the QA Vision upload step".
- **Dashboard rules:**
  - Colours come from tokens only (`index.css` `:root` and its dark block).
  - Icons are lucide SVGs with `aria-hidden`. The panel is `role="status"`. Every control has a label and works by keyboard.
  - No `any`.
  - **Invoke the `ui-ux-pro-max` skill before any dashboard UI edit.**
- **Git:**
  - Work on `master` and never push.
  - Commit only your own paths: `git add <paths> && git commit -m "<msg>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- <paths>`.
  - Never `docker compose down -v`.
  - Never commit to the real test repository, which is read-only for this plan.
- **Test commands:**
  - **test-management**: from the service folder, `cd platforms/test-management-service`, run `SECRET_KEY=test .venv/Scripts/python -m pytest <target> -q` in Git Bash. The venv is Python 3.11 (`.venv/Scripts/python`). `SECRET_KEY` is the only env var the tests need; CI sets `SECRET_KEY: ci-test-secret`.
  - The tests share `./test.db`, so **never run two pytest processes in this service at once.**
  - **Dashboard**: from `dashboard/`, run `npx vitest run <file>`. Before reporting a dashboard task, run all four CI steps: `npm run lint`, `npm run typecheck`, `npx vitest run` and `npm run build`. Their output must be pristine.
  - msw runs with `onUnhandledRequest: "error"`, so every new request needs a handler (Task 7 adds global defaults).

## Rulings on spec gaps

These rulings apply to every task, and the reviewers check them.

1. **`paths` is a JSON array string, not space-separated.**
   - The spec's own path regex allows spaces, and OBT has `tests/features/shell/shell_approval_flows/29744_hotel_+_approval_flow _determined_by_the_financial_reference.feature`.
   - A space-separated list cannot carry that path, while `names` already uses JSON. So `inputs.paths` is `json.dumps([...deduplicated paths])`.
   - Controller ruling: the path rule is widened (see Global Constraints) so this file runs. The service stays repo-agnostic and does not mirror OBT's layout.
2. **Same scenario name in two selected files.**
   - The parser already skips a duplicate name inside one file.
   - Across files, `--name` applies to every selected path. Selecting "Log in" from `a.feature` together with any case from `b.feature` also runs a "Log in" scenario in `b.feature`.
   - v1 accepts this over-selection, and the README documents it.
3. **`GET ci-target` also returns `token_expires_at` and `last_change: {action, user_id, at} | null`**, the newest `ci_target_events` row, kept after a delete. The dashboard needs them for "expires …" and "Last changed by …".
4. **Response shapes:**
   - `POST run-requests` answers 201 with the row, even when the row is `failed_to_start`, so the panel shows "Didn't start: <error>".
   - The list answers `{total, items}`.
   - Each row carries `refreshing: bool`. It is true while the server still checks GitHub for it, and the dashboard polls while it is true.
   - A 409 for an active run carries `detail = {code: "run_active", message: "A run is in progress", run_request_id}`.
   - A 409 for Stop on a finished run carries `{code: "run_finished", message: "This run has already finished"}`.
5. **A GitHub rate limit answers 503 with `Retry-After`.** The dashboard's ErrorBanner replaces any 429 detail with a generic text. A rate-limited dispatch deletes the just-inserted `queued` row, so the state is unchanged.
6. **Token handling outside pydantic.**
   - The token is validated in the endpoint, because pydantic's 422 echoes `input` and would leak a near-valid token.
   - The token is stripped, then must match `^[A-Za-z0-9_]{20,255}$`.
   - `""` and `null` mean "keep the stored token".
7. **Event actions.**
   - A save without an existing target is `created`.
   - A save with a token on an existing target is `token_replaced`.
   - Any other save is `updated`.
8. **Stop of a `queued` request with no `github_run_id`.** This happens only after a 204 dispatch: a 200 dispatch stores the id at Play, so Stop cancels on GitHub at once. Such a request becomes `cancelled` locally with `stopped_by` and `stopped_at`. For 2 minutes after the request, `refreshing` stays true and a `GET` keeps looking for its run. When found, the service stores it and cancels it on GitHub.
9. **Matching (the 204 fallback only) is defensive.** Polling skips it whenever `github_run_id` is already known. `find_run` keeps only runs that:
   - have `event == "workflow_dispatch"`;
   - were created at or after `since`, checked client-side too;
   - are not already claimed by another request.
   Of those, it picks the oldest.
10. **The confirmation "dialog" is an inline, non-modal `role="dialog"` card.** DESIGN.md says "There is no modal". Focus moves to Cancel, and Escape cancels and returns focus to the trigger.
11. **Names** come from the organization members list (`email`), with "user #<id>" as fallback.
12. **When the panel shows.**
    - On Cases, the panel shows the newest request while it is active or `refreshing`, or when it was requested less than 60 minutes ago.
    - The 5-minute results clock starts at `checked_at`, the moment the end was seen.
    - On a case detail, the panel shows only while that case is in the active request.
13. **"Requested runs"** is the route `runs/requested`, with view tabs (Runs | Requested runs) like Cases | Suites.
14. **Disabled-reason precedence:**
    1. "Viewers can't run tests" (any role outside owner, admin and member);
    2. "Running tests from QA Vision is not configured on this server" (`available` false);
    3. "Configure in Settings" (link);
    4. "GitHub token expired" (link);
    5. "A run is in progress".
15. **`DELETE ci-target`** answers 409 on any active row. It does not refresh from GitHub first; the spec asks the pre-409 refresh only for Play.
16. **Repo names `.` and `..`** are rejected in addition to the spec regex.
17. **Template copies.** The dashboard keeps byte-identical copies of the two templates in `dashboard/src/templates/*.txt`, imported with `?raw`, with a vitest drift test. The dashboard Docker build context is `dashboard/` only, so `../templates` cannot be imported.
18. **The workflow template** guards the job with `if: github.ref == 'refs/heads/main'`. The help block replaces `main` with the configured branch.
19. **HTML report.** The script adds `--format html:test-results/cucumber-report.html`, because OBT's `cucumber.js` has no HTML formatter.
20. **`github_run_url`**, from the dispatch's `html_url` or from a matched run's `html_url`, is stored only if it starts with `https://github.com/`. Otherwise it is NULL, so the dashboard never renders an untrusted link.

## Review Focus

1. **Scenario names with regex characters, quotes, `$`, backslashes, `[ ]` or `|`** must select exactly that scenario and nothing longer or shorter.
   - Task 10: `regex characters, quotes and dollars in a name match only that name`.
   - Task 4: the raw name reaches the dispatch unchanged (`test_cases_become_files_and_raw_names_and_the_dispatch_body_is_exact`).
2. **Scenario Outline names with `<placeholders>`**, including a placeholder name with regex characters, must match every example row.
   - The case stores the raw outline name, not the first-example name. This is pinned in Task 1 (`test_import_records_the_raw_scenario_name_untruncated`).
   - The pattern is pinned in Task 10 (`an outline's placeholders match the example values cucumber-js puts in`).
3. **A token pasted with surrounding spaces or a trailing newline** must be trimmed, work, and show the right last 4. A malformed token must never be echoed in the 422. Task 3: `test_a_pasted_token_with_whitespace_is_trimmed` and `test_a_malformed_token_is_422_and_not_echoed`.
4. **A double click on Run** must dispatch once.
   - Task 4: `test_double_click_dispatches_once` (the second POST is 409, and the dispatch route is called once). The first request already holds its run id from the 200 dispatch, so the pre-409 refresh asks GitHub for that run, not for the run list.
   - Task 8: `a double click on Run starts one run`.
5. **A run from someone else's manual dispatch, or clocks that disagree (the 204 fallback).**
   - With a 200 dispatch, the run id comes from GitHub's answer and nothing is matched. Task 4: `test_a_200_dispatch_stores_the_run_at_once_and_polling_never_lists_runs`.
   - Only a `workflow_dispatch` run created since request time minus 1 minute, sent as UTC `...Z` (a `+00:00` offset would arrive as a space), and not already claimed, may match.
   - A run created 50 s "before" the request by GitHub's clock still matches.
   - Task 2: `test_find_run_skips_older_runs_other_events_and_claimed_ids` and `test_find_run_sends_created_in_utc_z`.
   - Task 4: `test_the_run_list_is_asked_from_a_minute_before_the_request_in_utc`.

---

## Task order and concurrency

| Chain | Tasks | Notes |
|---|---|---|
| Backend | 1 → 2 → 3 → 4 → 5 → 6 | All in `platforms/test-management-service` (6 also touches gateway, scripts and docs). Strictly sequential: one pytest process at a time, and each task consumes the previous one's interfaces. |
| Dashboard | 7 → 8 → 9 → 10 | All in `dashboard/` (10 also touches `templates/`, `.github/workflows/ci.yml` and `TODO.md`). Sequential: shared files (`index.css`, `test/server.ts`, the pages) and one `npm run build` at a time. msw stubs the API, so this chain does not wait for the backend. |

**The two chains may run concurrently.** Their files are disjoint:
- `DESIGN.md` is only in Task 9 and `TODO.md` only in Task 10.
- README, `.env.example`, `docker-compose.yml`, the gateway and the smoke script are only in Task 6.

The manual end-to-end check at the end needs both chains done.

---

### Task 1: Migration 004, models, and `cases.scenario_name` filled by the import

**Files:**
- Create: `platforms/test-management-service/alembic/versions/004_run_from_qa_vision.py`
- Create: `platforms/test-management-service/src/casebook/models/ci.py`
- Modify: `platforms/test-management-service/src/casebook/models/case.py` (add `scenario_name` after `feature_name`)
- Modify: `platforms/test-management-service/src/casebook/models/__init__.py`
- Modify: `platforms/test-management-service/src/casebook/gherkin_import/plan.py` (`Existing.scenario_name`, `_differs`)
- Modify: `platforms/test-management-service/src/casebook/service/import_service.py` (`load_existing`, `_content`, create)
- Test: `platforms/test-management-service/tests/unit/test_migration.py` (append)
- Test: `platforms/test-management-service/tests/unit/test_import_plan.py` (append)

**Interfaces:**
- Produces:
  - `Case.scenario_name: Text | None`, the raw scenario name, untruncated.
  - From `src.casebook.models.ci`: `CiTarget`, `RunRequest`, `CiTargetEvent` (columns exactly as in the spec tables), plus `ACTIVE_STATUSES = ("queued", "running", "cancelling")`, `RUN_STATUSES` and `EVENT_ACTIONS = ("created", "updated", "token_replaced", "deleted")`.
  - All re-exported from `src.casebook.models`.

- [ ] **Step 1: Write the failing migration tests.** Append to `tests/unit/test_migration.py`:

```python
RUN = ("INSERT INTO run_requests (project_id, requested_by, requested_at, selection, status)"
       " VALUES (:project, 1, '2026-10-07 10:00:00', '[]', :status)")


def test_one_active_run_per_project(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(RUN), {"project": 1, "status": "running"})
        conn.execute(text(RUN), {"project": 1, "status": "completed"})
        conn.execute(text(RUN), {"project": 1, "status": "failed_to_start"})
        conn.execute(text(RUN), {"project": 2, "status": "queued"})
    for status in ("queued", "running", "cancelling"):
        with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
            conn.execute(text(RUN), {"project": 1, "status": status})


def test_run_status_is_constrained(migrated_engine):
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text(RUN), {"project": 1, "status": "paused"})


def test_downgrade_to_003_drops_the_run_tables_and_scenario_name(tmp_path):
    url = f"sqlite:///{(tmp_path / 'down4.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "003")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert not {"ci_targets", "run_requests", "ci_target_events"} & set(inspector.get_table_names())
        assert "scenario_name" not in {c["name"] for c in inspector.get_columns("cases")}
    finally:
        engine.dispose()
    command.upgrade(cfg, "head")  # and up again
```

The existing `test_migration_creates_every_model_table` and `test_migration_columns_match_models` then also cover the three new tables against the models.

- [ ] **Step 2: Write the failing import tests.** Append to `tests/unit/test_import_plan.py`:

```python
OUTLINE = (
    "Feature: A\n"
    f"  Scenario: {'x' * 250}\n    Given x\n"
    "  Scenario Outline: Book <city> flight\n    Given <city>\n    Examples:\n      | city |\n      | Rome |\n"
)


def test_import_records_the_raw_scenario_name_untruncated(db):
    run(db, [(A, OUTLINE)])
    assert {c.scenario_name for c in db.query(Case).all()} == {"x" * 250, "Book <city> flight"}
    assert db.query(Case).filter(Case.scenario_name == "x" * 250).one().title == "x" * 200


def test_a_case_imported_before_scenario_names_gets_one_on_the_next_import(db):
    run(db, [(A, FEATURE)])
    for case in db.query(Case).all():
        case.scenario_name = None
    db.commit()
    assert run(db, [(A, FEATURE)]).summary()["updated"] == 2
    assert {c.scenario_name for c in db.query(Case).all()} == {"one", "two"}
    assert {i.action for i in import_service.plan_import(db, 1, [(A, FEATURE)], False).items} == {"unchanged"}


def test_a_manual_case_keeps_no_scenario_name(db):
    db.add(Case(project_id=1, number=1, title="manual", steps=[], created_by=1))
    db.commit()
    run(db, [(A, FEATURE)])
    assert db.query(Case).filter(Case.title == "manual").one().scenario_name is None
```

- [ ] **Step 3: Run the tests and check they fail.**

Run: `cd platforms/test-management-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py tests/unit/test_import_plan.py -q`
Expected: FAIL (`no such table: run_requests`, `Case has no attribute scenario_name`).

- [ ] **Step 4: Implement the models.** `src/casebook/models/ci.py`:

```python
"""Running tests from QA Vision (docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md)."""
from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, Text, text

from src.casebook.db.base import Base

ACTIVE_STATUSES = ("queued", "running", "cancelling")
RUN_STATUSES = ("queued", "running", "completed", "cancelling", "cancelled", "failed_to_start")
EVENT_ACTIONS = ("created", "updated", "token_replaced", "deleted")
ACTIVE_WHERE = "status IN ('queued','running','cancelling')"


class CiTarget(Base):
    """Where Play dispatches for one project: a GitHub repository, workflow file, branch and token."""

    __tablename__ = "ci_targets"

    project_id = Column(Integer, primary_key=True, autoincrement=False)
    provider = Column(String(20), nullable=False, default="github")
    repo = Column(String(200), nullable=False)
    workflow = Column(String(200), nullable=False)
    ref = Column(String(255), nullable=False, default="main")
    token_encrypted = Column(Text, nullable=False)  # Fernet ciphertext; never returned
    token_last4 = Column(String(4), nullable=False)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class RunRequest(Base):
    """One Play. The partial unique index keeps one active request per project."""

    __tablename__ = "run_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','cancelling','cancelled','failed_to_start')",
            name="chk_run_requests_status",
        ),
        Index("uq_run_requests_one_active", "project_id", unique=True,
              postgresql_where=text(ACTIVE_WHERE), sqlite_where=text(ACTIVE_WHERE)),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False, index=True)
    requested_by = Column(Integer, nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False)
    selection = Column(JSON, nullable=False)  # [{"case_number", "path", "name"}]
    suite_id = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False)
    conclusion = Column(String(30), nullable=True)
    github_run_id = Column(BigInteger, nullable=True)
    github_run_url = Column(Text, nullable=True)
    stopped_by = Column(Integer, nullable=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(String(500), nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=True)


class CiTargetEvent(Base):
    """Audit trail of the credential; kept when the target is deleted."""

    __tablename__ = "ci_target_events"
    __table_args__ = (
        CheckConstraint("action IN ('created','updated','token_replaced','deleted')", name="chk_ci_target_events_action"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)
    at = Column(DateTime(timezone=True), nullable=False)
```

In `models/case.py`, add this after `feature_name`:

```python
    # The raw Gherkin scenario name (untruncated); Play selects by file + this name. NULL for manual cases
    scenario_name = Column(Text, nullable=True)
```

`models/__init__.py`:

```python
from src.casebook.models.case import Case, CaseLabel
from src.casebook.models.ci import CiTarget, CiTargetEvent, RunRequest
from src.casebook.models.suite import Suite, SuiteCase

__all__ = ["Case", "CaseLabel", "CiTarget", "CiTargetEvent", "RunRequest", "Suite", "SuiteCase"]
```

- [ ] **Step 5: Implement migration 004.** `alembic/versions/004_run_from_qa_vision.py`:

```python
"""cases.scenario_name; ci_targets, run_requests, ci_target_events (run from QA Vision)

Revision ID: 004
Revises: 003
Create Date: 2026-10-07
"""
import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

ACTIVE_WHERE = "status IN ('queued','running','cancelling')"


def upgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.add_column(sa.Column("scenario_name", sa.Text(), nullable=True))

    op.create_table(
        "ci_targets",
        sa.Column("project_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("repo", sa.String(200), nullable=False),
        sa.Column("workflow", sa.String(200), nullable=False),
        sa.Column("ref", sa.String(255), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("token_last4", sa.String(4), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "run_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("selection", sa.JSON(), nullable=False),
        sa.Column("suite_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("conclusion", sa.String(30), nullable=True),
        sa.Column("github_run_id", sa.BigInteger(), nullable=True),
        sa.Column("github_run_url", sa.Text(), nullable=True),
        sa.Column("stopped_by", sa.Integer(), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','cancelling','cancelled','failed_to_start')",
            name="chk_run_requests_status",
        ),
    )
    op.create_index("ix_run_requests_project_id", "run_requests", ["project_id"])
    op.create_index("uq_run_requests_one_active", "run_requests", ["project_id"], unique=True,
                    postgresql_where=sa.text(ACTIVE_WHERE), sqlite_where=sa.text(ACTIVE_WHERE))

    op.create_table(
        "ci_target_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('created','updated','token_replaced','deleted')",
                           name="chk_ci_target_events_action"),
    )
    op.create_index("ix_ci_target_events_project_id", "ci_target_events", ["project_id"])


def downgrade() -> None:
    op.drop_table("ci_target_events")
    op.drop_table("run_requests")
    op.drop_table("ci_targets")
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("scenario_name")
```

- [ ] **Step 6: Make the import fill `scenario_name`.**
- In `gherkin_import/plan.py`:
  - add the field `scenario_name: Optional[str] = None` at the end of `Existing`;
  - in `_differs`, add `or case.scenario_name != scenario.name` to the returned expression. Cases imported before 004 then show as `update` once, as `feature_name` did with 003.
- In `service/import_service.py`:
  - `load_existing`: pass `scenario_name=r.scenario_name`;
  - `_content`: add `row.scenario_name = scenario.name` next to `row.feature_name = ...`;
  - the `create` branch: add `scenario_name=s.name` to `Case(...)`.

- [ ] **Step 7: Run the two files, then the whole suite, and check they pass.**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py tests/unit/test_import_plan.py -q`, then `SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: PASS. The existing duplicate-name parse test (`test_every_scenario_and_outline_becomes_one_case_and_duplicate_names_are_skipped`) still passes.

- [ ] **Step 8: Commit.**

```bash
P=platforms/test-management-service
FILES="$P/alembic/versions/004_run_from_qa_vision.py $P/src/casebook/models/ci.py $P/src/casebook/models/case.py $P/src/casebook/models/__init__.py $P/src/casebook/gherkin_import/plan.py $P/src/casebook/service/import_service.py $P/tests/unit/test_migration.py $P/tests/unit/test_import_plan.py"
git add $FILES && git commit -m "feat(test-management): migration 004 — run tables and cases.scenario_name filled by the import" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

---

### Task 2: Secret box (Fernet) and the GitHub client

**Files:**
- Modify: `platforms/test-management-service/requirements.txt` (add `cryptography==43.0.3` after `httpx`)
- Modify: `platforms/test-management-service/src/casebook/core/config.py` (`TM_SECRETS_KEY`)
- Create: `platforms/test-management-service/src/casebook/utils/secret_box.py`
- Create: `platforms/test-management-service/src/casebook/utils/github_client.py`
- Modify: `platforms/test-management-service/tests/conftest.py` (fixtures `secrets_key`, `no_secrets_key` and `github`)
- Test: `platforms/test-management-service/tests/unit/test_secret_box.py`, `platforms/test-management-service/tests/unit/test_github_client.py`

**Interfaces:**
- Produces, in `secret_box`:
  - `NOT_CONFIGURED: str`;
  - `class SecretsUnavailable(Exception)`;
  - `is_available() -> bool`;
  - `encrypt(plain: str) -> str`;
  - `decrypt(ciphertext: str) -> str`. It raises `SecretsUnavailable` without a key, or when the ciphertext no longer opens.
- Produces, in `github_client`:
  - `API = "https://api.github.com"`, `REPO`, `WORKFLOW` (compiled regexes), `EXPIRY_HEADER`, `UNAUTHORIZED`, `FORBIDDEN` and `NOT_FOUND` (the verbatim messages);
  - `class GitHubError(Exception)` with `.status: int` (0 when there was no answer) and `.message: str`;
  - `class RateLimited(GitHubError)` with `.retry_after: int` and the message `"GitHub rate limit, try again in {n} s"`;
  - `parse_expiry(value: str | None) -> datetime | None`;
  - `github_time(moment: datetime) -> str`, which returns `YYYY-MM-DDTHH:MM:SSZ` in UTC;
  - `check_target(token, repo, workflow) -> datetime | None`, which returns the token expiry;
  - `class DispatchResult(NamedTuple)` with `run_id: int` and `html_url: str | None`;
  - `dispatch(token, repo, workflow, ref, inputs: dict) -> DispatchResult | None`. It sends `return_run_details: true`. A 200 with an integer `workflow_run_id` gives a `DispatchResult`. A 204, or a 200 without a usable id, gives `None`, and the caller falls back to matching;
  - `find_run(token, repo, workflow, title: str, since: datetime, exclude_ids: frozenset = frozenset()) -> dict | None`;
  - `get_run(token, repo, run_id: int) -> dict`;
  - `cancel_run(token, repo, run_id: int) -> None`.
  - Every function raises `ValueError` for a bad repo or workflow before any request.
- Produces, in conftest:
  - fixtures `secrets_key` (a fresh Fernet key) and `no_secrets_key` (`""`);
  - fixture `github`, a `GitHubStub` on the shared respx router. Its attributes are `repo = "acme/obt"` and `workflow = "qa-vision-run.yml"`. Its methods:
    - `check(status=200, workflow_status=None, expires="2027-03-12 00:00:00 UTC", headers=None)` returns the workflow route;
    - `dispatch(run_id=None, status=None, headers=None)`: with `run_id` it answers 200 `{workflow_run_id, run_url, html_url}` (the normal path); without it, 204 (the fallback) or the given `status`;
    - `runs(*runs)`, `run(body)` and `cancel(run_id, status=202)` each return their route;
    - `run_body(run_id, request_id, status="queued", conclusion=None, title=None, created_at="2026-10-07T10:00:05Z") -> dict`.

- [ ] **Step 1: Add the dependency and the setting, and install.**

In `requirements.txt`, after `httpx==0.27.0`, add `cryptography==43.0.3`.

In `core/config.py`, add this to `Settings`:

```python
    # Running tests from QA Vision: the Fernet key that encrypts each project's GitHub token.
    # Empty turns the feature off (GET ci-target says available=false, PUT answers 503). Generate one:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    TM_SECRETS_KEY: str = ""
```

Run: `.venv/Scripts/python -m pip install -r requirements.txt`
Expected: `Successfully installed cryptography-43.0.3 ...`

- [ ] **Step 2: Add the conftest fixtures.** Append to `tests/conftest.py`. Move `import httpx` to the top imports, and add `from cryptography.fernet import Fernet`.

```python
GH = "https://api.github.com"


@pytest.fixture
def secrets_key(monkeypatch):
    """TM_SECRETS_KEY set to a fresh Fernet key for this test."""
    monkeypatch.setattr(settings, "TM_SECRETS_KEY", Fernet.generate_key().decode())


@pytest.fixture
def no_secrets_key(monkeypatch):
    monkeypatch.setattr(settings, "TM_SECRETS_KEY", "")


class GitHubStub:
    """GitHub's REST API on the test's respx router: each method answers one endpoint, and a later
    call with the same name replaces the earlier answer. Nothing reaches the real api.github.com."""

    repo = "acme/obt"
    workflow = "qa-vision-run.yml"

    def __init__(self, router):
        self.router = router

    def _url(self, path: str) -> str:
        return f"{GH}/repos/{self.repo}{path}"

    def check(self, status=200, workflow_status=None, expires="2027-03-12 00:00:00 UTC", headers=None):
        extra = {"github-authentication-token-expiration": expires} if expires else {}
        extra.update(headers or {})
        self.router.get(self._url(""), name="gh-repo").mock(
            return_value=httpx.Response(status, json={"full_name": self.repo}, headers=extra))
        return self.router.get(self._url(f"/actions/workflows/{self.workflow}"), name="gh-workflow").mock(
            return_value=httpx.Response(workflow_status if workflow_status is not None else status,
                                        json={"id": 1, "path": f".github/workflows/{self.workflow}"}))

    def dispatch(self, run_id=None, status=None, headers=None):
        """With run_id: GitHub's 200 with run details (return_run_details). Without: a 204, the fallback."""
        if run_id is not None:
            body = {"workflow_run_id": run_id, "run_url": f"{GH}/repos/{self.repo}/actions/runs/{run_id}",
                    "html_url": f"https://github.com/{self.repo}/actions/runs/{run_id}"}
            response = httpx.Response(status or 200, json=body, headers=headers or {})
        else:
            response = httpx.Response(status or 204, headers=headers or {})
        return self.router.post(self._url(f"/actions/workflows/{self.workflow}/dispatches"), name="gh-dispatch").mock(
            return_value=response)

    def runs(self, *runs):
        return self.router.get(self._url(f"/actions/workflows/{self.workflow}/runs"), name="gh-runs").mock(
            return_value=httpx.Response(200, json={"total_count": len(runs), "workflow_runs": list(runs)}))

    def run(self, body):
        return self.router.get(self._url(f"/actions/runs/{body['id']}"), name=f"gh-run-{body['id']}").mock(
            return_value=httpx.Response(200, json=body))

    def cancel(self, run_id, status=202):
        return self.router.post(self._url(f"/actions/runs/{run_id}/cancel"), name=f"gh-cancel-{run_id}").mock(
            return_value=httpx.Response(status, json={}))

    def run_body(self, run_id, request_id, status="queued", conclusion=None, title=None,
                 created_at="2026-10-07T10:00:05Z"):
        return {"id": run_id, "display_title": title or f"QA Vision #{request_id}", "status": status,
                "conclusion": conclusion, "event": "workflow_dispatch", "created_at": created_at,
                "html_url": f"https://github.com/{self.repo}/actions/runs/{run_id}"}


@pytest.fixture
def github(http):
    return GitHubStub(http)
```

- [ ] **Step 3: Write the failing tests.** `tests/unit/test_secret_box.py`:

```python
"""The GitHub token at rest: Fernet with TM_SECRETS_KEY."""
import pytest
from cryptography.fernet import Fernet

from src.casebook.core.config import settings
from src.casebook.utils import secret_box

TOKEN = "github_pat_" + "a" * 40


def test_round_trip_and_the_ciphertext_hides_the_token(secrets_key):
    sealed = secret_box.encrypt(TOKEN)
    assert TOKEN not in sealed and secret_box.decrypt(sealed) == TOKEN
    assert secret_box.is_available()


def test_without_a_key_nothing_can_be_sealed(no_secrets_key):
    assert not secret_box.is_available()
    with pytest.raises(secret_box.SecretsUnavailable) as err:
        secret_box.encrypt(TOKEN)
    assert str(err.value) == "Running tests from QA Vision is not configured on this server"


def test_a_malformed_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "TM_SECRETS_KEY", "not-a-fernet-key")
    assert not secret_box.is_available()


def test_a_token_sealed_with_another_key_cannot_be_read(secrets_key, monkeypatch):
    sealed = secret_box.encrypt(TOKEN)
    monkeypatch.setattr(settings, "TM_SECRETS_KEY", Fernet.generate_key().decode())
    with pytest.raises(secret_box.SecretsUnavailable) as err:
        secret_box.decrypt(sealed)
    assert TOKEN not in str(err.value)
```

`tests/unit/test_github_client.py`:

```python
"""The GitHub REST client: api.github.com only, no redirects, specific messages, no token in errors."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.casebook.utils import github_client as gh

TOKEN = "github_pat_" + "a" * 40


def test_check_sends_the_api_headers_and_returns_the_expiry(github):
    route = github.check()
    assert gh.check_target(TOKEN, github.repo, github.workflow) == datetime(2027, 3, 12, tzinfo=timezone.utc)
    sent = route.calls.last.request
    assert sent.url.host == "api.github.com"
    assert sent.headers["Accept"] == "application/vnd.github+json"
    assert sent.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert sent.headers["Authorization"] == f"Bearer {TOKEN}"


def test_a_token_without_expiry_returns_none(github):
    github.check(expires=None)
    assert gh.check_target(TOKEN, github.repo, github.workflow) is None


@pytest.mark.parametrize("value, expected", [
    ("2027-03-12 00:00:00 UTC", datetime(2027, 3, 12, tzinfo=timezone.utc)),
    ("2027-03-12 01:00:00 +0100", datetime(2027, 3, 12, tzinfo=timezone.utc)),
    ("soon", None), ("", None), (None, None)])
def test_expiry_header_parsing(value, expected):
    assert gh.parse_expiry(value) == expected


@pytest.mark.parametrize("status, message", [(401, gh.UNAUTHORIZED), (403, gh.FORBIDDEN), (404, gh.NOT_FOUND)])
def test_check_failures_have_specific_messages_without_the_token(github, status, message):
    github.check(status=status)
    with pytest.raises(gh.GitHubError) as err:
        gh.check_target(TOKEN, github.repo, github.workflow)
    assert (err.value.status, err.value.message) == (status, message)
    assert TOKEN not in str(err.value)


def test_a_workflow_missing_from_the_default_branch_is_the_404_message(github):
    github.check(workflow_status=404)
    with pytest.raises(gh.GitHubError) as err:
        gh.check_target(TOKEN, github.repo, github.workflow)
    assert "default branch" in err.value.message


def test_a_rate_limit_says_when_to_retry(github):
    reset = int(datetime.now(timezone.utc).timestamp()) + 42
    github.check(status=403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)})
    with pytest.raises(gh.RateLimited) as err:
        gh.check_target(TOKEN, github.repo, github.workflow)
    assert 40 <= err.value.retry_after <= 42
    assert err.value.message == f"GitHub rate limit, try again in {err.value.retry_after} s"


def test_redirects_are_not_followed(http):
    http.get(f"{gh.API}/repos/acme/obt").mock(
        return_value=httpx.Response(301, headers={"location": "https://evil.example/steal"}))
    with pytest.raises(gh.GitHubError):  # following it would hit an unrouted host and raise something else
        gh.check_target(TOKEN, "acme/obt", "qa-vision-run.yml")


def test_a_network_error_is_a_github_error_without_details(http):
    http.get(f"{gh.API}/repos/acme/obt").mock(side_effect=httpx.ConnectTimeout("boom"))
    with pytest.raises(gh.GitHubError) as err:
        gh.check_target(TOKEN, "acme/obt", "qa-vision-run.yml")
    assert err.value.status == 0 and TOKEN not in err.value.message


@pytest.mark.parametrize("repo, workflow", [
    ("acme", "x.yml"), ("acme/obt/x", "x.yml"), ("acme/..", "x.yml"), ("acme/.", "x.yml"),
    ("a" * 40 + "/x", "x.yml"), ("acme/obt", "x.json"), ("acme/obt", "../x.yml"), ("acme/obt", "a/x.yml")])
def test_names_are_checked_before_any_request(http, repo, workflow):
    with pytest.raises(ValueError):
        gh.check_target(TOKEN, repo, workflow)
    assert not http.calls


def test_dispatch_asks_for_run_details_and_returns_the_run(github):
    route = github.dispatch(run_id=501)
    result = gh.dispatch(TOKEN, github.repo, github.workflow, "main", {"paths": "[]", "names": "[]", "request_id": "7"})
    assert result == gh.DispatchResult(run_id=501, html_url=f"https://github.com/{github.repo}/actions/runs/501")
    assert route.calls.last.request.read() == (
        b'{"ref": "main", "inputs": {"paths": "[]", "names": "[]", "request_id": "7"}, "return_run_details": true}')


def test_a_204_dispatch_returns_none_for_the_matching_fallback(github):
    github.dispatch()
    assert gh.dispatch(TOKEN, github.repo, github.workflow, "main", {"request_id": "7"}) is None


@pytest.mark.parametrize("body", [{}, {"workflow_run_id": "501"}, {"workflow_run_id": True}, ["x"]])
def test_a_200_without_a_usable_run_id_also_falls_back(http, body):
    http.post(f"{gh.API}/repos/acme/obt/actions/workflows/qa-vision-run.yml/dispatches").mock(
        return_value=httpx.Response(200, json=body))
    assert gh.dispatch(TOKEN, "acme/obt", "qa-vision-run.yml", "main", {"request_id": "7"}) is None


def test_find_run_matches_the_exact_title(github):
    since = datetime(2026, 10, 7, 9, 59, tzinfo=timezone.utc)
    github.runs(github.run_body(2, 8), github.run_body(4, 7, title="QA Vision #77"), github.run_body(3, 7))
    assert gh.find_run(TOKEN, github.repo, github.workflow, "QA Vision #7", since)["id"] == 3


def test_find_run_sends_created_in_utc_z(github):
    route = github.runs()
    since = datetime(2026, 10, 7, 10, 59, tzinfo=timezone(timedelta(hours=1)))
    assert gh.find_run(TOKEN, github.repo, github.workflow, "QA Vision #7", since) is None
    params = route.calls.last.request.url.params
    assert params["created"] == ">=2026-10-07T09:59:00Z"
    assert params["event"] == "workflow_dispatch"


def test_find_run_skips_older_runs_other_events_and_claimed_ids(github):
    since = datetime(2026, 10, 7, 9, 59, tzinfo=timezone.utc)
    github.runs(
        github.run_body(1, 7, created_at="2026-10-07T09:40:00Z"),   # an older manual dispatch with the same title
        {**github.run_body(2, 7), "event": "push"},
        github.run_body(3, 7),                                       # already another request's run
        github.run_body(5, 7, created_at="2026-10-07T09:59:20Z"),
        github.run_body(4, 7, created_at="2026-10-07T09:59:10Z"),   # ours: GitHub's clock is 50 s behind ours
    )
    run = gh.find_run(TOKEN, github.repo, github.workflow, "QA Vision #7", since, exclude_ids=frozenset({3}))
    assert run["id"] == 4   # the oldest remaining match


def test_get_and_cancel_a_run(github):
    github.run(github.run_body(9, 7, status="in_progress"))
    cancel = github.cancel(9)
    assert gh.get_run(TOKEN, github.repo, 9)["status"] == "in_progress"
    gh.cancel_run(TOKEN, github.repo, 9)
    assert cancel.call_count == 1


def test_cancelling_a_finished_run_is_a_409_github_error(github):
    github.cancel(9, status=409)
    with pytest.raises(gh.GitHubError) as err:
        gh.cancel_run(TOKEN, github.repo, 9)
    assert err.value.status == 409
```

`test_dispatch_asks_for_run_details_and_returns_the_run` compares bytes, which depends on httpx's `json=` serialisation (default separators). If httpx 0.27 serialises differently, compare `json.loads(route.calls.last.request.read())` instead. Do not change the asserted content.

- [ ] **Step 4: Run the tests and check they fail.**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_secret_box.py tests/unit/test_github_client.py -q`
Expected: FAIL (`ModuleNotFoundError: src.casebook.utils.secret_box`).

- [ ] **Step 5: Implement `utils/secret_box.py`.**

```python
"""The GitHub token at rest: Fernet with TM_SECRETS_KEY. Nothing here logs or returns the plain token."""
from cryptography.fernet import Fernet, InvalidToken

from src.casebook.core.config import settings

NOT_CONFIGURED = "Running tests from QA Vision is not configured on this server"
UNREADABLE = "The stored GitHub token cannot be read with this server's key: replace it in Settings"


class SecretsUnavailable(Exception):
    """No usable TM_SECRETS_KEY, or a stored token sealed with another key."""


def _fernet() -> Fernet:
    key = settings.TM_SECRETS_KEY.strip()
    if not key:
        raise SecretsUnavailable(NOT_CONFIGURED)
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise SecretsUnavailable(NOT_CONFIGURED) from None


def is_available() -> bool:
    try:
        _fernet()
    except SecretsUnavailable:
        return False
    return True


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    box = _fernet()
    try:
        return box.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise SecretsUnavailable(UNREADABLE) from None
```

- [ ] **Step 6: Implement `utils/github_client.py`.**

```python
"""The few GitHub REST calls Play and Stop need (run-from-QA-Vision spec, "GitHub client").

https://api.github.com only, never following redirects, 10 s timeout. The token goes in a header and
never into an exception, a message or a log line; httpx errors are replaced, not chained."""
import re
from datetime import datetime, timezone
from typing import NamedTuple, Optional

import httpx

API = "https://api.github.com"
TIMEOUT_SECONDS = 10.0
REPO = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
WORKFLOW = re.compile(r"^[A-Za-z0-9._-]{1,100}\.ya?ml$")
EXPIRY_HEADER = "github-authentication-token-expiration"

UNAUTHORIZED = "token invalid or expired"
FORBIDDEN = "token has no Actions access to this repository"
NOT_FOUND = ("repository or workflow not found. The workflow file must exist on the repository's "
             "default branch")


class GitHubError(Exception):
    """GitHub refused, or could not be reached (status 0)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class RateLimited(GitHubError):
    def __init__(self, retry_after: int):
        super().__init__(429, f"GitHub rate limit, try again in {retry_after} s")
        self.retry_after = retry_after


def _check_names(repo: str, workflow: Optional[str] = None) -> None:
    if not REPO.match(repo) or repo.split("/")[1] in (".", ".."):
        raise ValueError("repository name not allowed")
    if workflow is not None and not WORKFLOW.match(workflow):
        raise ValueError("workflow file name not allowed")


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=API, timeout=TIMEOUT_SECONDS, follow_redirects=False,
        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                 "Authorization": f"Bearer {token}", "User-Agent": "qa-vision-test-management"},
    )


def _retry_after(response: httpx.Response) -> Optional[int]:
    if response.status_code not in (403, 429):
        return None
    retry = response.headers.get("retry-after", "")
    if retry.isdigit():
        return max(1, int(retry))
    if response.headers.get("x-ratelimit-remaining") == "0":
        reset = response.headers.get("x-ratelimit-reset", "")
        if reset.isdigit():
            return max(1, int(reset) - int(datetime.now(timezone.utc).timestamp()))
        return 60
    return None


def _send(token: str, method: str, path: str, **kwargs) -> httpx.Response:
    try:
        with _client(token) as client:
            response = client.request(method, path, **kwargs)
    except httpx.HTTPError:
        raise GitHubError(0, "GitHub could not be reached, try again") from None
    wait = _retry_after(response)
    if wait is not None:
        raise RateLimited(wait)
    if response.is_redirect:
        raise GitHubError(response.status_code, "GitHub answered with a redirect, which QA Vision does not follow")
    if response.status_code == 401:
        raise GitHubError(401, UNAUTHORIZED)
    if response.status_code == 403:
        raise GitHubError(403, FORBIDDEN)
    if response.status_code == 404:
        raise GitHubError(404, NOT_FOUND)
    if response.status_code >= 400:
        raise GitHubError(response.status_code, f"GitHub answered {response.status_code}")
    return response


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        raise GitHubError(response.status_code, "GitHub answered with something that is not JSON") from None
    if not isinstance(body, dict):
        raise GitHubError(response.status_code, "GitHub answered with an unexpected body")
    return body


def parse_expiry(value: Optional[str]) -> Optional[datetime]:
    """GitHub sends e.g. '2027-03-12 00:00:00 UTC'; a numeric offset is read too; anything else is unknown."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip().replace(" UTC", " +0000"), "%Y-%m-%d %H:%M:%S %z").astimezone(timezone.utc)
    except ValueError:
        return None


def github_time(moment: datetime) -> str:
    """UTC with a Z: a '+00:00' offset would reach GitHub as a space inside the query."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _created(run: dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(run.get("created_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return None


def check_target(token: str, repo: str, workflow: str) -> Optional[datetime]:
    """The token can see the repository and the workflow file. Returns the token's expiry, if any."""
    _check_names(repo, workflow)
    response = _send(token, "GET", f"/repos/{repo}")
    _send(token, "GET", f"/repos/{repo}/actions/workflows/{workflow}")
    return parse_expiry(response.headers.get(EXPIRY_HEADER))


class DispatchResult(NamedTuple):
    run_id: int
    html_url: Optional[str]


def dispatch(token: str, repo: str, workflow: str, ref: str, inputs: dict) -> Optional[DispatchResult]:
    """Start the workflow. GitHub answers 200 with {workflow_run_id, run_url, html_url} when it returns run
    details; a 204, or a 200 without a usable id, gives None: the caller falls back to title matching."""
    _check_names(repo, workflow)
    response = _send(token, "POST", f"/repos/{repo}/actions/workflows/{workflow}/dispatches",
                     json={"ref": ref, "inputs": inputs, "return_run_details": True})
    if response.status_code != 200:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    run_id = body.get("workflow_run_id") if isinstance(body, dict) else None
    if type(run_id) is not int:  # bool is an int, and a string id is not trusted either
        return None
    html_url = body.get("html_url")
    return DispatchResult(run_id=run_id, html_url=html_url if isinstance(html_url, str) else None)


def find_run(token: str, repo: str, workflow: str, title: str, since: datetime,
             exclude_ids: frozenset = frozenset()) -> Optional[dict]:
    """The oldest workflow_dispatch run of the workflow, created at or after `since`, whose display_title
    is exactly `title` and whose id no other request has claimed."""
    _check_names(repo, workflow)
    response = _send(token, "GET", f"/repos/{repo}/actions/workflows/{workflow}/runs",
                     params={"event": "workflow_dispatch", "created": f">={github_time(since)}", "per_page": 100})
    runs = _json(response).get("workflow_runs") or []
    matches = []
    for run in runs:
        if not isinstance(run, dict) or run.get("display_title") != title:
            continue
        if run.get("event", "workflow_dispatch") != "workflow_dispatch" or run.get("id") in exclude_ids:
            continue
        created = _created(run)
        if created is not None and created < since:
            continue
        matches.append(run)
    return min(matches, key=lambda r: (_created(r) or since, r.get("id", 0))) if matches else None


def get_run(token: str, repo: str, run_id: int) -> dict:
    _check_names(repo)
    return _json(_send(token, "GET", f"/repos/{repo}/actions/runs/{int(run_id)}"))


def cancel_run(token: str, repo: str, run_id: int) -> None:
    _check_names(repo)
    _send(token, "POST", f"/repos/{repo}/actions/runs/{int(run_id)}/cancel")
```

- [ ] **Step 7: Run the two files, then the whole suite, and check they pass.**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_secret_box.py tests/unit/test_github_client.py -q`, then `SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit.**

```bash
P=platforms/test-management-service
FILES="$P/requirements.txt $P/src/casebook/core/config.py $P/src/casebook/utils/secret_box.py $P/src/casebook/utils/github_client.py $P/tests/conftest.py $P/tests/unit/test_secret_box.py $P/tests/unit/test_github_client.py"
git add $FILES && git commit -m "feat(test-management): GitHub client and Fernet token box for running tests from QA Vision" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

---

### Task 3: `ci-target` endpoints, encryption and the audit trail

**Files:**
- Create: `platforms/test-management-service/src/casebook/schemas/ci.py`
- Create: `platforms/test-management-service/src/casebook/service/ci_target_service.py`
- Create: `platforms/test-management-service/src/casebook/api/v1/endpoints/ci_target.py`
- Modify: `platforms/test-management-service/src/casebook/api/deps.py` (`MANAGE_ROLES`)
- Modify: `platforms/test-management-service/src/casebook/api/v1/api.py`
- Test: `platforms/test-management-service/tests/integration/test_ci_target.py`

**Interfaces:**
- Consumes: Task 1's `CiTarget`, `CiTargetEvent`, `RunRequest` and `ACTIVE_STATUSES`, and Task 2's `secret_box` and `github_client`.
- Produces:
  - `GET /api/v1/projects/{id}/ci-target` → `CiTargetOut`:

    ```json
    {"available": true, "configured": true, "provider": "github", "repo": "acme/obt", "workflow": "qa-vision-run.yml",
     "ref": "main", "token_last4": "a1b2", "token_expires_at": "2027-03-12T00:00:00Z", "updated_at": "...",
     "last_change": {"action": "created", "user_id": 7, "at": "..."}}
    ```

    When nothing is configured, the target fields are `null` and `configured` is `false`.
  - `PUT` with body `{repo, workflow="qa-vision-run.yml", ref="main", token?}` → `CiTargetOut`. Its errors:
    - 422 for a bad name, a bad token, a missing first token, or GitHub's 401, 403 or 404;
    - 503 when not configured, or on a GitHub rate limit (with `Retry-After`);
    - 502 when GitHub is unreachable or answers another error.
  - `DELETE` → 204; 404 with no target; 409 while a run is active.
  - `deps.MANAGE_ROLES = ("owner", "admin")`.
  - In `schemas.ci`:
    - `CiTargetIn` and `clean_token(raw: str | None) -> str | None`, which raises `ValueError`;
    - `CiTargetOut`, `CiTargetChange` and `DEFAULT_WORKFLOW = "qa-vision-run.yml"`.
  - In `ci_target_service`:
    - `TokenRequired`;
    - `now() -> datetime`;
    - `get_target(db, project_id) -> CiTarget | None`;
    - `out(db, project_id) -> dict`;
    - `save_target(db, project_id, user_id, repo, workflow, ref, token: str | None) -> CiTarget`;
    - `delete_target(db, project_id, user_id) -> bool`;
    - `has_active_run(db, project_id) -> bool`.

- [ ] **Step 1: Write the failing tests.** `tests/integration/test_ci_target.py`:

```python
"""GET/PUT/DELETE /ci-target. GitHub is stubbed (the `github` fixture); the token never comes back."""
import logging
from datetime import datetime, timezone

import pytest

from src.casebook.models import CiTarget, CiTargetEvent, RunRequest

URL = "/api/v1/projects/1/ci-target"
TOKEN = "github_pat_11AAAAAAA0" + "b" * 30 + "a1b2"
BODY = {"repo": "acme/obt", "workflow": "qa-vision-run.yml", "ref": "main", "token": TOKEN}
NOT_CONFIGURED = "Running tests from QA Vision is not configured on this server"


@pytest.fixture
def owner(project_role, secrets_key):
    project_role("owner")


def put(client, auth, **changes):
    return client.put(URL, json={**BODY, **changes}, headers=auth())


def github_calls(http):
    return [c for c in http.calls if c.request.url.host == "api.github.com"]


def test_save_checks_github_stores_ciphertext_and_shows_last4_only(client, auth, owner, github, db, caplog):
    caplog.set_level(logging.DEBUG)
    github.check()
    r = put(client, auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True and body["configured"] is True
    assert (body["repo"], body["workflow"], body["ref"], body["token_last4"]) == ("acme/obt", "qa-vision-run.yml", "main", "a1b2")
    assert body["token_expires_at"].startswith("2027-03-12")
    assert body["last_change"]["action"] == "created" and body["last_change"]["user_id"] == 1
    assert TOKEN not in r.text and TOKEN not in client.get(URL, headers=auth()).text
    assert TOKEN not in db.get(CiTarget, 1).token_encrypted
    assert TOKEN not in caplog.text


def test_a_token_without_expiry_stores_null(client, auth, owner, github):
    github.check(expires=None)
    assert put(client, auth).json()["token_expires_at"] is None


@pytest.mark.parametrize("status, message", [
    (401, "token invalid or expired"),
    (403, "token has no Actions access to this repository"),
    (404, "repository or workflow not found. The workflow file must exist on the repository's default branch")])
def test_github_refusals_are_422_with_a_specific_message(client, auth, owner, github, db, status, message):
    github.check(status=status)
    r = put(client, auth)
    assert r.status_code == 422 and r.json()["detail"] == message
    assert db.get(CiTarget, 1) is None and db.query(CiTargetEvent).count() == 0


def test_a_rate_limit_is_503_with_retry_after_and_stores_nothing(client, auth, owner, github, db):
    github.check(status=429, headers={"retry-after": "30"})
    r = put(client, auth)
    assert r.status_code == 503 and r.json()["detail"] == "GitHub rate limit, try again in 30 s"
    assert r.headers["retry-after"] == "30" and db.get(CiTarget, 1) is None


@pytest.mark.parametrize("changes", [
    {"repo": "acme"}, {"repo": "acme/obt/x"}, {"repo": "acme/.."}, {"repo": "a b/c"},
    {"workflow": "run.json"}, {"workflow": "../run.yml"},
    {"ref": "-x"}, {"ref": "a..b"}, {"ref": "a\x00b"}, {"ref": "x" * 256}])
def test_bad_names_are_422_before_github_is_asked(client, auth, owner, http, changes):
    assert put(client, auth, **changes).status_code == 422
    assert not github_calls(http)


def test_a_pasted_token_with_whitespace_is_trimmed(client, auth, owner, github):
    workflow_route = github.check()
    r = put(client, auth, token=f"  {TOKEN}\r\n")
    assert r.status_code == 200, r.text
    assert r.json()["token_last4"] == "a1b2"
    assert workflow_route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


def test_a_malformed_token_is_422_and_not_echoed(client, auth, owner, http):
    bad = TOKEN + "!"
    r = put(client, auth, token=bad)
    assert r.status_code == 422
    assert bad not in r.text and TOKEN not in r.text
    assert not github_calls(http)


def test_the_first_save_needs_a_token(client, auth, owner, github):
    github.check()
    r = client.put(URL, json={"repo": "acme/obt"}, headers=auth())
    assert r.status_code == 422 and "token" in r.json()["detail"]


def test_events_for_create_update_token_replacement_and_delete(client, auth, owner, github, db):
    github.check()
    assert put(client, auth).status_code == 200
    updated = client.put(URL, json={"repo": "acme/obt", "ref": "release"}, headers=auth())  # keeps the stored token
    assert updated.status_code == 200 and updated.json()["ref"] == "release" and updated.json()["token_last4"] == "a1b2"
    assert put(client, auth, token="github_pat_" + "c" * 30 + "zzzz").json()["token_last4"] == "zzzz"
    assert client.delete(URL, headers=auth()).status_code == 204
    assert [e.action for e in db.query(CiTargetEvent).order_by(CiTargetEvent.id)] == [
        "created", "updated", "token_replaced", "deleted"]
    after = client.get(URL, headers=auth()).json()
    assert after["configured"] is False and after["repo"] is None and after["last_change"]["action"] == "deleted"


@pytest.mark.parametrize("role", ["member", "viewer", "billing_manager"])
def test_only_owners_and_admins_change_it_but_every_role_reads(client, auth, project_role, secrets_key, github, role):
    project_role(role)
    github.check()
    assert put(client, auth).status_code == 403
    assert client.delete(URL, headers=auth()).status_code == 403
    assert client.get(URL, headers=auth()).status_code == 200


def test_an_admin_may_save_and_disconnect(client, auth, project_role, secrets_key, github):
    project_role("admin")
    github.check()
    assert put(client, auth).status_code == 200
    assert client.delete(URL, headers=auth()).status_code == 204


def test_without_a_secrets_key_get_says_unavailable_and_put_is_503(client, auth, project_role, no_secrets_key, http):
    project_role("owner")
    assert client.get(URL, headers=auth()).json()["available"] is False
    r = put(client, auth)
    assert r.status_code == 503 and r.json()["detail"] == NOT_CONFIGURED
    assert TOKEN not in r.text and not github_calls(http)


def test_delete_without_a_target_is_404(client, auth, owner):
    assert client.delete(URL, headers=auth()).status_code == 404


def test_delete_is_409_while_a_run_is_active(client, auth, owner, github, db):
    github.check()
    put(client, auth)
    db.add(RunRequest(project_id=1, requested_by=1, requested_at=datetime.now(timezone.utc), selection=[], status="running"))
    db.commit()
    assert client.delete(URL, headers=auth()).status_code == 409
    assert db.get(CiTarget, 1) is not None
```

- [ ] **Step 2: Run the tests and check they fail.**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_ci_target.py -q`
Expected: FAIL (404 on every route).

- [ ] **Step 3: Implement the schemas.** `src/casebook/schemas/ci.py`:

```python
"""Running tests from QA Vision: the CI target and run requests."""
import re
from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

REPO_PATTERN = r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$"
WORKFLOW_PATTERN = r"^[A-Za-z0-9._-]{1,100}\.ya?ml$"
TOKEN = re.compile(r"^[A-Za-z0-9_]{20,255}$")
DEFAULT_WORKFLOW = "qa-vision-run.yml"


class CiTargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: Annotated[str, StringConstraints(strip_whitespace=True, pattern=REPO_PATTERN)]
    workflow: Annotated[str, StringConstraints(strip_whitespace=True, pattern=WORKFLOW_PATTERN)] = DEFAULT_WORKFLOW
    ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] = "main"
    # Checked by clean_token in the endpoint, never by pydantic: pydantic's 422 echoes the input back
    token: Optional[str] = None

    @field_validator("repo")
    @classmethod
    def _not_dots(cls, value: str) -> str:
        if value.split("/")[1] in (".", ".."):
            raise ValueError("not a repository name")
        return value

    @field_validator("ref")
    @classmethod
    def _branch_name(cls, value: str) -> str:
        if "\x00" in value or ".." in value or value.startswith("-"):
            raise ValueError("not a branch name: no NUL, no '..', no leading '-'")
        return value


def clean_token(raw: Optional[str]) -> Optional[str]:
    """Strip what a paste adds (spaces, a newline). None or empty means 'keep the stored token'.
    The error message never contains the value."""
    if raw is None or not raw.strip():
        return None
    token = raw.strip()
    if not TOKEN.match(token):
        raise ValueError("token: not a GitHub token (letters, digits and _ only)")
    return token


class CiTargetChange(BaseModel):
    action: str
    user_id: int
    at: datetime


class CiTargetOut(BaseModel):
    available: bool
    configured: bool
    provider: Optional[str] = None
    repo: Optional[str] = None
    workflow: Optional[str] = None
    ref: Optional[str] = None
    token_last4: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_change: Optional[CiTargetChange] = None
```

- [ ] **Step 4: Implement the service.** `src/casebook/service/ci_target_service.py`:

```python
"""A project's CI target (where Play dispatches) and its audit trail."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.casebook.models import CiTarget, CiTargetEvent, RunRequest
from src.casebook.models.ci import ACTIVE_STATUSES
from src.casebook.utils import github_client, secret_box


class TokenRequired(Exception):
    """The first save of a target must carry a token."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def get_target(db: Session, project_id: int) -> Optional[CiTarget]:
    return db.get(CiTarget, project_id)


def _last_change(db: Session, project_id: int) -> Optional[CiTargetEvent]:
    return (db.query(CiTargetEvent).filter(CiTargetEvent.project_id == project_id)
            .order_by(CiTargetEvent.at.desc(), CiTargetEvent.id.desc()).first())


def out(db: Session, project_id: int) -> dict:
    row = get_target(db, project_id)
    change = _last_change(db, project_id)
    body = {
        "available": secret_box.is_available(), "configured": row is not None,
        "last_change": {"action": change.action, "user_id": change.user_id, "at": change.at} if change else None,
    }
    if row is not None:
        body.update(provider=row.provider, repo=row.repo, workflow=row.workflow, ref=row.ref,
                    token_last4=row.token_last4, token_expires_at=row.token_expires_at, updated_at=row.updated_at)
    return body


def has_active_run(db: Session, project_id: int) -> bool:
    return db.query(RunRequest.id).filter(
        RunRequest.project_id == project_id, RunRequest.status.in_(ACTIVE_STATUSES)).first() is not None


def save_target(db: Session, project_id: int, user_id: int, repo: str, workflow: str, ref: str,
                token: Optional[str]) -> CiTarget:
    """Checks the token with GitHub before anything is stored. Raises secret_box.SecretsUnavailable,
    TokenRequired and github_client.GitHubError (RateLimited included)."""
    if not secret_box.is_available():
        raise secret_box.SecretsUnavailable(secret_box.NOT_CONFIGURED)
    row = get_target(db, project_id)
    if token is None and row is None:
        raise TokenRequired()
    plain = token if token is not None else secret_box.decrypt(row.token_encrypted)
    expires = github_client.check_target(plain, repo, workflow)
    action = "created" if row is None else ("token_replaced" if token is not None else "updated")
    if row is None:
        row = CiTarget(project_id=project_id, provider="github")
        db.add(row)
    row.repo, row.workflow, row.ref = repo, workflow, ref
    if token is not None:
        row.token_encrypted, row.token_last4 = secret_box.encrypt(plain), plain[-4:]
    row.token_expires_at = expires
    row.updated_by, row.updated_at = user_id, now()
    db.add(CiTargetEvent(project_id=project_id, user_id=user_id, action=action, at=row.updated_at))
    db.commit()
    return row


def delete_target(db: Session, project_id: int, user_id: int) -> bool:
    row = get_target(db, project_id)
    if row is None:
        return False
    db.delete(row)
    db.add(CiTargetEvent(project_id=project_id, user_id=user_id, action="deleted", at=now()))
    db.commit()
    return True
```

- [ ] **Step 5: Implement the endpoints.** In `api/deps.py`, add `MANAGE_ROLES = ("owner", "admin")` under `EDIT_ROLES`, and add `"MANAGE_ROLES"` to `__all__`.

`src/casebook/api/v1/endpoints/ci_target.py`:

```python
"""GET/PUT/DELETE /projects/{id}/ci-target (run-from-QA-Vision spec)."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from src.casebook.api.deps import MANAGE_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.casebook.schemas.ci import CiTargetIn, CiTargetOut, clean_token
from src.casebook.service import ci_target_service
from src.casebook.utils import github_client, secret_box

router = APIRouter()  # mounted at /projects/{project_id}/ci-target


def github_failure(exc: github_client.GitHubError, refused_status: int) -> HTTPException:
    """GitHub's answer as ours: a rate limit is 503 with Retry-After (a 429 detail is hidden by the
    dashboard), a refusal of the token or names is `refused_status`, the rest is 502."""
    if isinstance(exc, github_client.RateLimited):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message,
                             headers={"Retry-After": str(exc.retry_after)})
    if exc.status in (401, 403, 404):
        return HTTPException(refused_status, detail=exc.message)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=exc.message)


@router.get("", response_model=CiTargetOut)
def get_ci_target(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return ci_target_service.out(db, access.project_id)


@router.put("", response_model=CiTargetOut)
def put_ci_target(
    payload: CiTargetIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    try:
        token = clean_token(payload.token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    try:
        ci_target_service.save_target(db, access.project_id, access.user_id, payload.repo, payload.workflow,
                                      payload.ref, token)
    except secret_box.SecretsUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except ci_target_service.TokenRequired:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="token: required on the first save")
    except github_client.GitHubError as exc:
        raise github_failure(exc, status.HTTP_422_UNPROCESSABLE_ENTITY)
    return ci_target_service.out(db, access.project_id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_ci_target(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    if ci_target_service.has_active_run(db, access.project_id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A run is in progress: stop it or wait for it to end")
    if not ci_target_service.delete_target(db, access.project_id, access.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No CI target configured")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

In `api/v1/api.py`, import `ci_target` and add:

```python
api_router.include_router(ci_target.router, prefix="/projects/{project_id}/ci-target", tags=["runs"])
```

- [ ] **Step 6: Run the new file, then the whole suite, and check they pass.**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_ci_target.py -q`, then `SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
P=platforms/test-management-service
FILES="$P/src/casebook/schemas/ci.py $P/src/casebook/service/ci_target_service.py $P/src/casebook/api/v1/endpoints/ci_target.py $P/src/casebook/api/deps.py $P/src/casebook/api/v1/api.py $P/tests/integration/test_ci_target.py"
git add $FILES && git commit -m "feat(test-management): ci-target endpoints — check the token with GitHub, store it encrypted, audit changes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

---

### Task 4: Run requests: Play, list, get, polling, refresh before 409, `failed_to_start`

**Files:**
- Modify: `platforms/test-management-service/src/casebook/schemas/ci.py` (run request schemas)
- Create: `platforms/test-management-service/src/casebook/service/run_request_service.py`
- Create: `platforms/test-management-service/src/casebook/api/v1/endpoints/run_requests.py`
- Modify: `platforms/test-management-service/src/casebook/api/v1/api.py`
- Test: `platforms/test-management-service/tests/integration/test_run_requests.py`

**Interfaces:**
- Consumes:
  - Task 1's models;
  - Task 2's `github_client.dispatch` (returns `DispatchResult | None`), `find_run`, `get_run`, `GitHubError` and `RateLimited`, and `secret_box.decrypt` and `SecretsUnavailable`;
  - Task 3's `github_failure(exc, refused_status)` from `endpoints/ci_target.py`.
- Produces:
  - `POST /run-requests` with body `{case_numbers: [int≥1] (1..200)}` or `{suite_id: int}`, exactly one of the two. It answers 201 with `RunRequestOut`, or:
    - 412 when there is no target;
    - 422 for a bad selection (the message names the case numbers);
    - 404 for an unknown suite;
    - 409 `{code: "run_active", message, run_request_id}`;
    - 503 when not configured or rate-limited.
  - `GET /run-requests?limit=1..100 (20)&offset=0..` answers `{total, items: [RunRequestOut]}`, newest first.
  - `GET /run-requests/{request_id}` answers `RunRequestOut`, or 404.
  - `RunRequestOut`:

    ```
    {id, requested_by, requested_at, selection: [{case_number, path, name}], case_count, suite_id, status,
     conclusion, github_run_id, github_run_url, stopped_by, stopped_at, error, checked_at, refreshing}
    ```
  - In `run_request_service`:
    - the constants `THROTTLE = timedelta(seconds=5)`, `START_TIMEOUT = timedelta(minutes=2)`, `MATCH_WINDOW = timedelta(minutes=1)`, `MAX_CASES = 200`, `MAX_INPUT_CHARS = 65000` and `NOT_STARTED = "The workflow did not start"`;
    - the exceptions `NoTarget`, `BadSelection`, `SuiteNotFound` and `RunActive(request_id: int | None)`;
    - `now()`, `aware(dt)` and `run_title(request_id) -> "QA Vision #<id>"`;
    - `build_selection(db, project_id, case_numbers, suite_id) -> list[dict]`;
    - `dispatch_inputs(request_id, selection) -> dict`;
    - `active_request(db, project_id)`;
    - `needs_refresh(row, at) -> bool`;
    - `refresh(db, row, force=False)`;
    - `create(db, project_id, user_id, case_numbers, suite_id) -> RunRequest`;
    - `list_requests(db, project_id, limit, offset) -> (int, list)`;
    - `get_request(db, project_id, request_id)`;
    - `out(row) -> dict`;
    - `safe_run_url(url) -> str | None`, which keeps a URL only if it starts with `https://github.com/`;
    - the private helpers `_target_and_token`, `_match` and `_apply_github`, which Task 5 extends.
  - **Run id at Play.** After a 200 dispatch, `create` stores `github_run_id` and `github_run_url` before answering, and polling goes straight to `get_run`. Only after a 204 does the row keep no id. Then `_match` (title matching) and the 2-minute `failed_to_start` apply, as the fallback.

- [ ] **Step 1: Write the failing tests.** `tests/integration/test_run_requests.py`:

```python
"""POST/GET run-requests: Play dispatches the CI workflow; GETs refresh from GitHub (stubbed)."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.casebook.models import Case, CiTarget, RunRequest, Suite, SuiteCase
from src.casebook.service import run_request_service
from src.casebook.utils import secret_box

BASE = "/api/v1/projects/1"
URL = f"{BASE}/run-requests"
TOKEN = "github_pat_" + "d" * 40
CHECKOUT, LOGIN = "tests/features/checkout.feature", "tests/features/login.feature"
VOUCHER_NAME = 'Pay with a "voucher" (50% off) $5 [promo]'
FEATURE = (
    "Feature: Checkout\n"
    "  Scenario: Pay by card\n    Given x\n"
    f"  Scenario: {VOUCHER_NAME}\n    Given y\n"
    "  Scenario Outline: Book <city> flight\n    Given <city>\n    Examples:\n      | city |\n      | Rome |\n"
)
# The import numbers cases in (path, scenario) order; the manual case comes last
BOOK, CARD, VOUCHER, LOG_IN, MANUAL = 1, 2, 3, 4, 5


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.at

    def tick(self, **delta):
        self.at += timedelta(**delta)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(run_request_service, "now", c)
    return c


@pytest.fixture
def project(client, auth, project_role, secrets_key, db, github):
    project_role("member")
    files = [{"path": CHECKOUT, "content": FEATURE},
             {"path": LOGIN, "content": "Feature: Login\n  Scenario: Log in\n    Given z\n"}]
    assert client.post(f"{BASE}/cases/import", json={"files": files}, headers=auth()).status_code == 200
    assert client.post(f"{BASE}/cases", json={"title": "Manual"}, headers=auth()).status_code == 201
    assert {c.number: c.scenario_name for c in db.query(Case)} == {
        BOOK: "Book <city> flight", CARD: "Pay by card", VOUCHER: VOUCHER_NAME, LOG_IN: "Log in", MANUAL: None}
    db.add(CiTarget(project_id=1, provider="github", repo=github.repo, workflow=github.workflow, ref="main",
                    token_encrypted=secret_box.encrypt(TOKEN), token_last4=TOKEN[-4:], updated_by=1,
                    updated_at=datetime.now(timezone.utc)))
    db.commit()
    return client


def play(client, auth, **body):
    return client.post(URL, json=body, headers=auth())


def get(client, auth, rid):
    r = client.get(f"{URL}/{rid}", headers=auth())
    assert r.status_code == 200, r.text
    return r.json()


def test_cases_become_files_and_raw_names_and_the_dispatch_body_is_exact(project, auth, github, clock):
    route = github.dispatch(run_id=500)
    r = play(project, auth, case_numbers=[CARD, BOOK, LOG_IN, CARD])
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["case_count"], body["refreshing"], body["requested_by"]) == ("queued", 3, True, 1)
    assert body["selection"][0] == {"case_number": CARD, "path": CHECKOUT, "name": "Pay by card"}
    assert json.loads(route.calls.last.request.read()) == {
        "ref": "main",
        "inputs": {
            "paths": json.dumps([CHECKOUT, LOGIN]),
            "names": json.dumps(["Pay by card", "Book <city> flight", "Log in"]),
            "request_id": str(body["id"]),
        },
        "return_run_details": True,
    }
    assert TOKEN not in r.text


def test_a_200_dispatch_stores_the_run_at_once_and_polling_never_lists_runs(project, auth, github, http, clock):
    github.dispatch(run_id=501)
    body = play(project, auth, case_numbers=[CARD]).json()
    assert (body["status"], body["github_run_id"], body["github_run_url"]) == (
        "queued", 501, f"https://github.com/{github.repo}/actions/runs/501")
    run = github.run(github.run_body(501, body["id"], status="in_progress"))
    clock.tick(minutes=3)  # well past the 2-minute fallback limit: a known run never becomes failed_to_start
    assert get(project, auth, body["id"])["status"] == "running"
    assert run.call_count == 1
    assert not [c for c in http.calls if c.request.url.path.endswith(f"/workflows/{github.workflow}/runs")]


def test_a_dispatch_url_outside_github_is_not_stored(project, auth, github, http, clock):
    http.post(f"https://api.github.com/repos/{github.repo}/actions/workflows/{github.workflow}/dispatches",
              name="gh-dispatch").mock(
        return_value=httpx.Response(200, json={"workflow_run_id": 501, "html_url": "javascript:alert(1)"}))
    body = play(project, auth, case_numbers=[CARD]).json()
    assert body["github_run_id"] == 501 and body["github_run_url"] is None


def test_a_name_with_quotes_and_regex_characters_is_sent_raw(project, auth, github, clock):
    route = github.dispatch()
    assert play(project, auth, case_numbers=[VOUCHER]).status_code == 201
    assert json.loads(json.loads(route.calls.last.request.read())["inputs"]["names"]) == [VOUCHER_NAME]


def test_a_suite_expands_in_its_order(project, auth, db, github, clock):
    suite = Suite(project_id=1, name="Smoke", created_by=1)
    db.add(suite)
    db.commit()
    ids = {c.number: c.id for c in db.query(Case)}
    db.add_all([SuiteCase(suite_id=suite.id, case_id=ids[LOG_IN], position=0),
                SuiteCase(suite_id=suite.id, case_id=ids[CARD], position=1)])
    db.commit()
    github.dispatch()
    r = play(project, auth, suite_id=suite.id)
    assert r.status_code == 201, r.text
    assert r.json()["suite_id"] == suite.id
    assert [c["case_number"] for c in r.json()["selection"]] == [LOG_IN, CARD]


def test_an_empty_suite_is_422_and_an_unknown_one_404(project, auth, db, github):
    suite = Suite(project_id=1, name="Empty", created_by=1)
    db.add(suite)
    db.commit()
    dispatch = github.dispatch()
    assert play(project, auth, suite_id=suite.id).status_code == 422
    assert play(project, auth, suite_id=999).status_code == 404
    assert not dispatch.called


def test_manual_archived_and_unknown_cases_are_rejected_with_their_numbers(project, auth, db, github):
    db.query(Case).filter(Case.number == BOOK).one().status = "archived"
    db.commit()
    dispatch = github.dispatch()
    r = play(project, auth, case_numbers=[BOOK, CARD, MANUAL, 99])
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "TC-99" in detail and "TC-5" in detail and "TC-1" in detail and "TC-2" not in detail
    assert not dispatch.called


def test_a_case_without_scenario_name_asks_for_a_reimport(project, auth, db, github):
    db.query(Case).filter(Case.number == CARD).one().scenario_name = None
    db.commit()
    r = play(project, auth, case_numbers=[CARD])
    assert r.status_code == 422
    assert "re-import the .feature files first" in r.json()["detail"] and "TC-2" in r.json()["detail"]


@pytest.mark.parametrize("body", [
    {"case_numbers": []}, {"case_numbers": list(range(1, 202))}, {}, {"case_numbers": [1], "suite_id": 1},
    {"case_numbers": [0]}])
def test_bad_bodies_are_422(project, auth, body):
    assert project.post(URL, json=body, headers=auth()).status_code == 422


def test_a_selection_too_large_for_one_dispatch_is_422(project, auth, github):
    big = "Feature: Big\n" + "".join(f"  Scenario: {'x' * 330} {i}\n    Given x\n" for i in range(200))
    imported = project.post(f"{BASE}/cases/import", json={"files": [{"path": "tests/features/big.feature", "content": big}]},
                            headers=auth())
    assert imported.status_code == 200
    dispatch = github.dispatch()
    r = play(project, auth, case_numbers=list(range(6, 206)))
    assert r.status_code == 422 and "too large" in r.json()["detail"]
    assert not dispatch.called


def test_a_viewer_is_403(project, auth, project_role):
    project_role("viewer")
    assert play(project, auth, case_numbers=[CARD]).status_code == 403
    assert project.get(URL, headers=auth()).status_code == 200


def test_no_target_is_412(project, auth, db):
    db.query(CiTarget).delete()
    db.commit()
    assert play(project, auth, case_numbers=[CARD]).status_code == 412


def test_a_failed_dispatch_is_failed_to_start_and_frees_the_slot(project, auth, github, clock):
    github.dispatch(status=404)
    r = play(project, auth, case_numbers=[CARD])
    assert r.status_code == 201
    assert r.json()["status"] == "failed_to_start" and "default branch" in r.json()["error"]
    assert r.json()["refreshing"] is False
    github.dispatch()
    assert play(project, auth, case_numbers=[CARD]).status_code == 201


def test_a_rate_limited_dispatch_leaves_nothing_behind(project, auth, github, db, clock):
    github.dispatch(status=429, headers={"retry-after": "30"})
    r = play(project, auth, case_numbers=[CARD])
    assert r.status_code == 503 and r.json()["detail"] == "GitHub rate limit, try again in 30 s"
    assert db.query(RunRequest).count() == 0


def test_an_active_run_still_running_on_github_is_409(project, auth, github, clock):
    github.dispatch(run_id=500)
    first = play(project, auth, case_numbers=[CARD]).json()
    github.run(github.run_body(500, first["id"], status="in_progress"))
    r = play(project, auth, case_numbers=[BOOK])
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "run_active" and r.json()["detail"]["run_request_id"] == first["id"]


def test_a_run_that_finished_unseen_does_not_block_the_next_play(project, auth, github, clock):
    github.dispatch(run_id=500)
    first = play(project, auth, case_numbers=[CARD]).json()
    github.run(github.run_body(500, first["id"], status="completed", conclusion="success"))
    github.dispatch(run_id=600)
    second = play(project, auth, case_numbers=[BOOK])  # inside the 5 s throttle: the pre-409 refresh ignores it
    assert second.status_code == 201, second.text
    assert get(project, auth, first["id"])["status"] == "completed"


def test_double_click_dispatches_once(project, auth, github, clock):
    dispatch = github.dispatch(run_id=500)
    github.run(github.run_body(500, 1, status="queued"))  # the pre-409 refresh asks for that run: still queued
    a = play(project, auth, case_numbers=[CARD])
    b = play(project, auth, case_numbers=[CARD])
    assert (a.status_code, b.status_code) == (201, 409)
    assert dispatch.call_count == 1


@pytest.mark.parametrize("gh_status, conclusion, status", [
    ("queued", None, "queued"), ("waiting", None, "queued"), ("requested", None, "queued"),
    ("pending", None, "queued"), ("in_progress", None, "running"), ("completed", "success", "completed"),
    ("completed", "failure", "completed"), ("completed", "timed_out", "completed"),
    ("completed", "cancelled", "cancelled")])
def test_github_status_maps_to_ours(project, auth, github, clock, gh_status, conclusion, status):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status=gh_status, conclusion=conclusion))
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["conclusion"]) == (status, conclusion)
    assert body["refreshing"] is (status in ("queued", "running"))


# --- The 204 fallback: GitHub gave no run details, so polling matches the run by its title ---

def test_after_a_204_the_run_is_matched_by_display_title(project, auth, github, clock):
    github.dispatch()  # 204: no run details
    started = play(project, auth, case_numbers=[CARD]).json()
    rid = started["id"]
    assert started["github_run_id"] is None and started["github_run_url"] is None
    github.runs(github.run_body(400, rid + 1), github.run_body(501, rid))
    clock.tick(seconds=6)
    matched = get(project, auth, rid)
    assert (matched["status"], matched["github_run_id"]) == ("queued", 501)
    assert matched["github_run_url"] == f"https://github.com/{github.repo}/actions/runs/501"
    github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    assert get(project, auth, rid)["status"] == "running"


def test_a_run_url_outside_github_is_not_stored(project, auth, github, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs({**github.run_body(501, rid), "html_url": "javascript:alert(1)"})
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert body["github_run_id"] == 501 and body["github_run_url"] is None


def test_github_is_asked_at_most_every_5_seconds(project, auth, github, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    runs = github.runs()
    clock.tick(seconds=6)
    get(project, auth, rid)
    clock.tick(seconds=3)
    get(project, auth, rid)
    project.get(URL, headers=auth())
    assert runs.call_count == 1
    clock.tick(seconds=3)
    get(project, auth, rid)
    assert runs.call_count == 2


def test_the_run_list_is_asked_from_a_minute_before_the_request_in_utc(project, auth, github, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    runs = github.runs()
    clock.tick(seconds=6)
    get(project, auth, rid)
    params = runs.calls.last.request.url.params
    assert params["created"] == ">=2026-10-07T09:59:00Z" and params["event"] == "workflow_dispatch"


def test_a_run_never_seen_after_2_minutes_failed_to_start(project, auth, github, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs()
    clock.tick(seconds=119)
    assert get(project, auth, rid)["status"] == "queued"
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["error"], body["refreshing"]) == ("failed_to_start", "The workflow did not start", False)
    assert play(project, auth, case_numbers=[BOOK]).status_code == 201


def test_a_github_outage_during_refresh_changes_nothing(project, auth, github, http, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    http.get(f"https://api.github.com/repos/{github.repo}/actions/workflows/{github.workflow}/runs",
             name="gh-runs").mock(return_value=httpx.Response(503))
    clock.tick(minutes=3)
    body = get(project, auth, rid)
    assert body["status"] == "queued" and body["error"] is None


def test_the_list_is_newest_first_with_a_total(project, auth, github, clock):
    github.dispatch(status=404)
    first = play(project, auth, case_numbers=[CARD]).json()  # failed_to_start frees the slot
    github.dispatch()
    second = play(project, auth, case_numbers=[LOG_IN]).json()
    github.runs()
    page = project.get(f"{URL}?limit=1", headers=auth()).json()
    assert page["total"] == 2 and [i["id"] for i in page["items"]] == [second["id"]]
    assert project.get(f"{URL}?limit=1&offset=1", headers=auth()).json()["items"][0]["id"] == first["id"]


def test_another_projects_request_is_404(project, auth, github, project_role, clock):
    github.dispatch()
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    project_role("member", project_id=2)
    assert project.get(f"/api/v1/projects/2/run-requests/{rid}", headers=auth()).status_code == 404
```

- [ ] **Step 2: Run the tests and check they fail.**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_run_requests.py -q`
Expected: FAIL (404 or 405 on `/run-requests`).

- [ ] **Step 3: Add the schemas.** Append to `schemas/ci.py`. Add `model_validator` to the pydantic import.

```python
MAX_RUN_CASES = 200


class RunRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_numbers: Optional[Annotated[List[Annotated[int, Field(ge=1)]], Field(min_length=1, max_length=MAX_RUN_CASES)]] = None
    suite_id: Optional[int] = Field(None, ge=1)

    @model_validator(mode="after")
    def _one_of(self):
        if (self.case_numbers is None) == (self.suite_id is None):
            raise ValueError("send case_numbers or suite_id, not both")
        return self


class SelectedCase(BaseModel):
    case_number: int
    path: str
    name: str


class RunRequestOut(BaseModel):
    id: int
    requested_by: int
    requested_at: datetime
    selection: List[SelectedCase]
    case_count: int
    suite_id: Optional[int] = None
    status: str
    conclusion: Optional[str] = None
    github_run_id: Optional[int] = None
    github_run_url: Optional[str] = None
    stopped_by: Optional[int] = None
    stopped_at: Optional[datetime] = None
    error: Optional[str] = None
    checked_at: Optional[datetime] = None
    refreshing: bool  # true while the server still checks GitHub for it: poll


class RunRequestList(BaseModel):
    total: int
    items: List[RunRequestOut]
```

- [ ] **Step 4: Implement the service.** `src/casebook/service/run_request_service.py`:

```python
"""Play: a run request dispatches the project's CI workflow; GETs refresh it from GitHub (no worker)."""
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.casebook.models import Case, CiTarget, RunRequest, Suite, SuiteCase
from src.casebook.models.ci import ACTIVE_STATUSES
from src.casebook.service.case_service import case_key
from src.casebook.utils import github_client, secret_box

THROTTLE = timedelta(seconds=5)
START_TIMEOUT = timedelta(minutes=2)
MATCH_WINDOW = timedelta(minutes=1)
MAX_CASES = 200
MAX_INPUT_CHARS = 65000  # GitHub refuses workflow_dispatch inputs over 65 535 characters in total
NOT_STARTED = "The workflow did not start"
QUEUED_ON_GITHUB = ("queued", "waiting", "requested", "pending")
RUN_URL_PREFIX = "https://github.com/"


class NoTarget(Exception):
    """The project has no CI target."""


class BadSelection(Exception):
    """The selection cannot run; the message names the case numbers."""


class SuiteNotFound(Exception):
    pass


class RunActive(Exception):
    def __init__(self, request_id: Optional[int]):
        super().__init__("A run is in progress")
        self.request_id = request_id


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(moment: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands DateTime(timezone=True) back naive; every time stored here is UTC."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=timezone.utc)


def run_title(request_id: int) -> str:
    return f"QA Vision #{request_id}"


def _keys(numbers: List[int]) -> str:
    return ", ".join(case_key(n) for n in numbers)


def _numbers(db: Session, project_id: int, case_numbers: Optional[List[int]], suite_id: Optional[int]) -> List[int]:
    if suite_id is None:
        return list(dict.fromkeys(case_numbers or []))
    suite = db.query(Suite).filter(Suite.project_id == project_id, Suite.id == suite_id).one_or_none()
    if suite is None:
        raise SuiteNotFound()
    rows = (db.query(Case.number).join(SuiteCase, SuiteCase.case_id == Case.id)
            .filter(SuiteCase.suite_id == suite.id).order_by(SuiteCase.position).all())
    return [r.number for r in rows]


def build_selection(db: Session, project_id: int, case_numbers: Optional[List[int]],
                    suite_id: Optional[int]) -> List[dict]:
    numbers = _numbers(db, project_id, case_numbers, suite_id)
    if not numbers:
        raise BadSelection("Nothing to run: the suite has no cases")
    if len(numbers) > MAX_CASES:
        raise BadSelection(f"At most {MAX_CASES} cases per run; this selection has {len(numbers)}")
    found = {c.number: c for c in db.query(Case).filter(Case.project_id == project_id, Case.number.in_(numbers))}
    unknown = [n for n in numbers if n not in found]
    manual = [n for n in numbers if n in found and not found[n].source_path]
    archived = [n for n in numbers if n in found and found[n].source_path and found[n].status == "archived"]
    unnamed = [n for n in numbers if n in found and found[n].source_path and found[n].status != "archived"
               and not found[n].scenario_name]
    problems = []
    if unknown:
        problems.append(f"No such case: {_keys(unknown)}")
    if manual:
        problems.append(f"Manual cases cannot run: {_keys(manual)}")
    if archived:
        problems.append(f"Archived cases cannot run: {_keys(archived)}")
    if unnamed:
        problems.append(f"{_keys(unnamed)}: re-import the .feature files first")
    if problems:
        raise BadSelection(". ".join(problems))
    return [{"case_number": n, "path": found[n].source_path, "name": found[n].scenario_name} for n in numbers]


def dispatch_inputs(request_id: int, selection: List[dict]) -> dict:
    """paths: a JSON array of the files, once each (a path may contain a space); names: a JSON array of
    the raw scenario names; request_id: the row id, which the workflow puts in its run-name."""
    paths = list(dict.fromkeys(item["path"] for item in selection))
    return {"paths": json.dumps(paths, ensure_ascii=False),
            "names": json.dumps([item["name"] for item in selection], ensure_ascii=False),
            "request_id": str(request_id)}


def _target_and_token(db: Session, project_id: int) -> Tuple[CiTarget, str]:
    target = db.get(CiTarget, project_id)
    if target is None:
        raise NoTarget()
    return target, secret_box.decrypt(target.token_encrypted)


def active_request(db: Session, project_id: int) -> Optional[RunRequest]:
    return db.query(RunRequest).filter(
        RunRequest.project_id == project_id, RunRequest.status.in_(ACTIVE_STATUSES)).one_or_none()


def needs_refresh(row: RunRequest, at: datetime) -> bool:
    return row.status in ACTIVE_STATUSES


def _claimed(db: Session, project_id: int, own_id: int) -> frozenset:
    rows = db.query(RunRequest.github_run_id).filter(
        RunRequest.project_id == project_id, RunRequest.id != own_id, RunRequest.github_run_id.isnot(None)).all()
    return frozenset(r[0] for r in rows)


def safe_run_url(url: Optional[str]) -> Optional[str]:
    """Only a github.com page is stored, so the dashboard never renders an untrusted link."""
    return url if isinstance(url, str) and url.startswith(RUN_URL_PREFIX) else None


def _match(db: Session, row: RunRequest, target: CiTarget, token: str) -> Optional[dict]:
    """The 204 fallback only: GitHub gave no run details at dispatch, so find the run by its title."""
    run = github_client.find_run(token, target.repo, target.workflow, run_title(row.id),
                                 aware(row.requested_at) - MATCH_WINDOW, _claimed(db, row.project_id, row.id))
    if run is not None:
        row.github_run_id = int(run["id"])
        row.github_run_url = safe_run_url(run.get("html_url"))
    return run


def _map_status(row: RunRequest, run: dict) -> None:
    status, conclusion = run.get("status"), run.get("conclusion")
    if status == "completed":
        row.conclusion = str(conclusion)[:30] if conclusion else None
        row.status = "cancelled" if conclusion == "cancelled" else "completed"
    elif row.status == "cancelling":
        return  # stays cancelling until GitHub reports the run completed
    elif status == "in_progress":
        row.status = "running"
    elif status in QUEUED_ON_GITHUB:
        row.status = "queued"


def _apply_github(db: Session, row: RunRequest, target: CiTarget, token: str, at: datetime) -> None:
    if row.github_run_id is None:
        run = _match(db, row, target, token)
        if run is None:
            if at - aware(row.requested_at) >= START_TIMEOUT:
                row.status, row.error = "failed_to_start", NOT_STARTED
            return
    else:
        run = github_client.get_run(token, target.repo, row.github_run_id)
    _map_status(row, run)


def refresh(db: Session, row: RunRequest, force: bool = False) -> RunRequest:
    """Bring a request up to date with GitHub, at most every 5 s unless forced. A GitHub failure (rate
    limit, outage) or an unreadable token leaves the state as it was; checked_at still moves, so a failing
    GitHub is not asked on every GET."""
    at = now()
    if not needs_refresh(row, at):
        return row
    checked = aware(row.checked_at)
    if not force and checked is not None and at - checked < THROTTLE:
        return row
    target = db.get(CiTarget, row.project_id)
    if target is None:
        return row
    try:
        _apply_github(db, row, target, secret_box.decrypt(target.token_encrypted), at)
    except (github_client.GitHubError, secret_box.SecretsUnavailable):
        db.rollback()
    row.checked_at = at
    db.commit()
    return row


def create(db: Session, project_id: int, user_id: int, case_numbers: Optional[List[int]],
           suite_id: Optional[int]) -> RunRequest:
    target, token = _target_and_token(db, project_id)
    selection = build_selection(db, project_id, case_numbers, suite_id)
    preview = dispatch_inputs(0, selection)
    if len(preview["paths"]) + len(preview["names"]) + 20 > MAX_INPUT_CHARS:
        raise BadSelection("This selection is too large for one GitHub dispatch: select fewer cases")
    active = active_request(db, project_id)
    if active is not None:
        refresh(db, active, force=True)  # a run that ended while nobody looked must not block Play
        if active.status in ACTIVE_STATUSES:
            raise RunActive(active.id)
    row = RunRequest(project_id=project_id, requested_by=user_id, requested_at=now(), selection=selection,
                     suite_id=suite_id, status="queued")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise RunActive(None)  # another Play committed first (the partial unique index)
    db.refresh(row)
    try:
        started = github_client.dispatch(token, target.repo, target.workflow, target.ref,
                                         dispatch_inputs(row.id, selection))
    except github_client.RateLimited:
        db.delete(row)
        db.commit()
        raise
    except github_client.GitHubError as exc:
        row.status, row.error = "failed_to_start", exc.message[:500]
        db.commit()
        return row
    if started is not None:  # 200 with run details: Stop and polling work on this run at once
        row.github_run_id = started.run_id
        row.github_run_url = safe_run_url(started.html_url)
        db.commit()
    # On None (a 204), the row keeps no run id: polling matches it by title (the fallback)
    return row


def list_requests(db: Session, project_id: int, limit: int, offset: int) -> Tuple[int, List[RunRequest]]:
    query = db.query(RunRequest).filter(RunRequest.project_id == project_id)
    total = query.count()
    rows = query.order_by(RunRequest.requested_at.desc(), RunRequest.id.desc()).offset(offset).limit(limit).all()
    for row in rows:
        refresh(db, row)
    return total, rows


def get_request(db: Session, project_id: int, request_id: int) -> Optional[RunRequest]:
    row = db.query(RunRequest).filter(RunRequest.project_id == project_id, RunRequest.id == request_id).one_or_none()
    return refresh(db, row) if row is not None else None


def out(row: RunRequest) -> dict:
    selection = row.selection or []
    return {
        "id": row.id, "requested_by": row.requested_by, "requested_at": aware(row.requested_at),
        "selection": selection, "case_count": len(selection), "suite_id": row.suite_id, "status": row.status,
        "conclusion": row.conclusion, "github_run_id": row.github_run_id, "github_run_url": row.github_run_url,
        "stopped_by": row.stopped_by, "stopped_at": aware(row.stopped_at), "error": row.error,
        "checked_at": aware(row.checked_at), "refreshing": needs_refresh(row, now()),
    }
```

- [ ] **Step 5: Implement the endpoints.** `src/casebook/api/v1/endpoints/run_requests.py`:

```python
"""POST/GET /projects/{id}/run-requests (run-from-QA-Vision spec): Play and its state."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.casebook.api.deps import EDIT_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.casebook.api.v1.endpoints.ci_target import github_failure
from src.casebook.schemas.ci import RunRequestIn, RunRequestList, RunRequestOut
from src.casebook.service import run_request_service as runs
from src.casebook.utils import github_client, secret_box

router = APIRouter()  # mounted at /projects/{project_id}/run-requests

NO_TARGET = "No CI target: configure one in Project Settings"


def _row_or_404(db: Session, access: ProjectAccess, request_id: int):
    row = runs.get_request(db, access.project_id, request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run request not found")
    return row


@router.post("", response_model=RunRequestOut, status_code=status.HTTP_201_CREATED)
def create_run_request(
    payload: RunRequestIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    try:
        row = runs.create(db, access.project_id, access.user_id, payload.case_numbers, payload.suite_id)
    except runs.NoTarget:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, detail=NO_TARGET)
    except secret_box.SecretsUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except runs.SuiteNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Suite not found")
    except runs.BadSelection as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except runs.RunActive as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": "run_active", "message": "A run is in progress", "run_request_id": exc.request_id})
    except github_client.RateLimited as exc:
        raise github_failure(exc, status.HTTP_502_BAD_GATEWAY)
    return runs.out(row)


@router.get("", response_model=RunRequestList)
def list_run_requests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    total, rows = runs.list_requests(db, access.project_id, limit, offset)
    return {"total": total, "items": [runs.out(r) for r in rows]}


@router.get("/{request_id}", response_model=RunRequestOut)
def get_run_request(
    request_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return runs.out(_row_or_404(db, access, request_id))
```

In `api/v1/api.py`, import `run_requests` and add:

```python
api_router.include_router(run_requests.router, prefix="/projects/{project_id}/run-requests", tags=["runs"])
```

- [ ] **Step 6: Run the new file, then the whole suite, and check they pass.**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_run_requests.py -q`, then `SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
P=platforms/test-management-service
FILES="$P/src/casebook/schemas/ci.py $P/src/casebook/service/run_request_service.py $P/src/casebook/api/v1/endpoints/run_requests.py $P/src/casebook/api/v1/api.py $P/tests/integration/test_run_requests.py"
git add $FILES && git commit -m "feat(test-management): run requests — Play dispatches the workflow, GETs poll GitHub" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

---

### Task 5: Stop

**Files:**
- Modify: `platforms/test-management-service/src/casebook/service/run_request_service.py` (`AlreadyFinished`, `stop`, `_pending_cancel`, `needs_refresh`, `_apply_github`)
- Modify: `platforms/test-management-service/src/casebook/api/v1/endpoints/run_requests.py` (route)
- Test: `platforms/test-management-service/tests/integration/test_run_requests.py` (append)

**Interfaces:**
- Consumes: everything in Task 4, and `github_client.cancel_run`.
- Produces:
  - `POST /run-requests/{request_id}/stop` answers 200 with `RunRequestOut`, or:
    - 409 `{code: "run_finished", message: "This run has already finished"}`;
    - 404 for an unknown request;
    - 403 for a viewer;
    - 412 or 503 as for Play;
    - 502 for another GitHub error.
  - In `run_request_service`: `class AlreadyFinished(Exception)`, `stop(db, row, user_id) -> RunRequest`, and `_pending_cancel(row, at) -> bool`.
  - **Normal path:** after a 200 dispatch the run id is known from Play, so Stop cancels on GitHub at once. **Fallback (204 only):** a request with no run id yet is cancelled locally, then cancelled on GitHub once matched.

- [ ] **Step 1: Write the failing tests.** Append to `tests/integration/test_run_requests.py`:

```python
def known_run(project, auth, github, clock, status="in_progress"):
    """A request whose GitHub run (id 501, from the 200 dispatch) is in the given state."""
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status=status))
    clock.tick(seconds=6)
    assert get(project, auth, rid)["github_run_id"] == 501
    return rid


def test_stop_right_after_play_cancels_the_run_at_once(project, auth, github, clock):
    github.dispatch(run_id=501)
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.run(github.run_body(501, rid, status="queued"))
    cancel = github.cancel(501)
    r = project.post(f"{URL}/{rid}/stop", headers=auth(7))  # no tick, no matching: the id came with Play
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["stopped_by"]) == ("cancelling", 7)
    assert cancel.call_count == 1


def test_stop_cancels_on_github_and_records_who(project, auth, github, clock):
    rid = known_run(project, auth, github, clock)
    cancel = github.cancel(501)
    r = project.post(f"{URL}/{rid}/stop", headers=auth(7))
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["stopped_by"]) == ("cancelling", 7) and r.json()["stopped_at"]
    assert cancel.call_count == 1
    github.run(github.run_body(501, rid, status="in_progress"))
    clock.tick(seconds=6)
    assert get(project, auth, rid)["status"] == "cancelling"  # until GitHub says it ended
    github.run(github.run_body(501, rid, status="completed", conclusion="cancelled"))
    clock.tick(seconds=6)
    after = get(project, auth, rid)
    assert (after["status"], after["stopped_by"], after["refreshing"]) == ("cancelled", 7, False)


def test_stopping_a_finished_run_is_409(project, auth, github, clock):
    rid = known_run(project, auth, github, clock, status="completed")
    cancel = github.cancel(501)
    r = project.post(f"{URL}/{rid}/stop", headers=auth())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "run_finished"
    assert not cancel.called


def test_a_run_that_ends_while_stopping_is_409(project, auth, github, clock):
    rid = known_run(project, auth, github, clock)
    github.cancel(501, status=409)
    github.run(github.run_body(501, rid, status="completed", conclusion="success"))
    assert project.post(f"{URL}/{rid}/stop", headers=auth()).status_code == 409
    assert get(project, auth, rid)["status"] == "completed"


def test_after_a_204_a_queued_request_without_a_run_is_cancelled_locally_then_on_github(project, auth, github, clock):
    github.dispatch()  # 204: no run details, the fallback
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs()
    r = project.post(f"{URL}/{rid}/stop", headers=auth(7))
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["stopped_by"], r.json()["refreshing"]) == ("cancelled", 7, True)
    assert play(project, auth, case_numbers=[LOG_IN]).status_code == 201  # the slot is free
    github.runs(github.run_body(501, rid))
    cancel = github.cancel(501)
    clock.tick(seconds=6)
    body = get(project, auth, rid)
    assert (body["status"], body["github_run_id"], body["refreshing"]) == ("cancelled", 501, False)
    assert cancel.call_count == 1


def test_after_a_204_a_stopped_request_whose_run_never_appears_stops_looking_after_2_minutes(project, auth, github, clock):
    github.dispatch()  # 204
    rid = play(project, auth, case_numbers=[CARD]).json()["id"]
    github.runs()
    project.post(f"{URL}/{rid}/stop", headers=auth())
    clock.tick(minutes=2, seconds=1)
    body = get(project, auth, rid)
    assert (body["status"], body["refreshing"]) == ("cancelled", False)


def test_a_viewer_cannot_stop_and_an_unknown_request_is_404(project, auth, github, clock, project_role):
    rid = known_run(project, auth, github, clock)
    project_role("viewer")
    assert project.post(f"{URL}/{rid}/stop", headers=auth()).status_code == 403
    project_role("member")
    assert project.post(f"{URL}/9999/stop", headers=auth()).status_code == 404
```

- [ ] **Step 2: Run the tests and check they fail.**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_run_requests.py -q -k "stop or stopped or stopping"`.

`test_stop_right_after_play_cancels_the_run_at_once` and the `known_run` helper rely on Task 4's run id at Play. The two `after_a_204` tests cover the fallback.
Expected: FAIL (405 on `/stop`).

- [ ] **Step 3: Implement.** In `run_request_service.py`, add these below `RunActive`:

```python
class AlreadyFinished(Exception):
    """Stop on a request that is no longer active."""
```

Replace `needs_refresh` and `_apply_github` with:

```python
def _pending_cancel(row: RunRequest, at: datetime) -> bool:
    """Stopped before GitHub listed its run: keep looking for 2 minutes, so it is cancelled there too."""
    return (row.status == "cancelled" and row.github_run_id is None and row.stopped_at is not None
            and at - aware(row.requested_at) < START_TIMEOUT)


def needs_refresh(row: RunRequest, at: datetime) -> bool:
    return row.status in ACTIVE_STATUSES or _pending_cancel(row, at)


def _apply_github(db: Session, row: RunRequest, target: CiTarget, token: str, at: datetime) -> None:
    if _pending_cancel(row, at):
        if _match(db, row, target, token) is not None:
            try:
                github_client.cancel_run(token, target.repo, row.github_run_id)
            except github_client.GitHubError as exc:
                if exc.status != 409:  # 409: it already ended, nothing left to cancel
                    raise
        return
    if row.github_run_id is None:
        run = _match(db, row, target, token)
        if run is None:
            if at - aware(row.requested_at) >= START_TIMEOUT:
                row.status, row.error = "failed_to_start", NOT_STARTED
            return
    else:
        run = github_client.get_run(token, target.repo, row.github_run_id)
    _map_status(row, run)
```

Add at the end of the file:

```python
def stop(db: Session, row: RunRequest, user_id: int) -> RunRequest:
    """Cancel on GitHub and mark cancelling. The run id normally came with Play (a 200 dispatch); only
    after a 204 can a request still have none: it is cancelled locally, then on GitHub once a GET matches it."""
    if row.status not in ACTIVE_STATUSES:
        raise AlreadyFinished()
    at = now()
    if row.github_run_id is None:
        row.status, row.stopped_by, row.stopped_at = "cancelled", user_id, at
        db.commit()
        return row
    target, token = _target_and_token(db, row.project_id)
    try:
        github_client.cancel_run(token, target.repo, row.github_run_id)
    except github_client.GitHubError as exc:
        if exc.status != 409:
            raise
        refresh(db, row, force=True)
        raise AlreadyFinished()
    row.status, row.stopped_by, row.stopped_at = "cancelling", user_id, at
    db.commit()
    return row
```

In `endpoints/run_requests.py`, add:

```python
@router.post("/{request_id}/stop", response_model=RunRequestOut)
def stop_run_request(
    request_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    row = _row_or_404(db, access, request_id)
    try:
        row = runs.stop(db, row, access.user_id)
    except runs.AlreadyFinished:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": "run_finished", "message": "This run has already finished"})
    except runs.NoTarget:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, detail=NO_TARGET)
    except secret_box.SecretsUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except github_client.GitHubError as exc:
        raise github_failure(exc, status.HTTP_502_BAD_GATEWAY)
    return runs.out(row)
```

- [ ] **Step 4: Run the file, then the whole suite, and check they pass.**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest tests/integration/test_run_requests.py -q`, then `SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
P=platforms/test-management-service
FILES="$P/src/casebook/service/run_request_service.py $P/src/casebook/api/v1/endpoints/run_requests.py $P/tests/integration/test_run_requests.py"
git add $FILES && git commit -m "feat(test-management): stop a run request" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

---

### Task 6: Gateway, smoke, README, `.env.example`, compose

**Files:**
- Modify: `gateway/nginx.conf.template` (the test-management regex location, line ~154)
- Modify: `scripts/smoke_gateway.sh` (after the "case features" check, line ~118)
- Modify: `docker-compose.yml` (`x-testmgmt-env`, line ~58)
- Modify: `.env.example`
- Modify: `platforms/test-management-service/README.md`

**Interfaces:**
- Consumes: Tasks 3, 4 and 5 routes.
- Produces: `/api/v1/projects/{id}/(ci-target|run-requests)` reach test-management through the gateway.

- [ ] **Step 1: Add the smoke checks first.** In `scripts/smoke_gateway.sh`, after the `case features -> test-management-service` check:

```bash
check "ci target -> test-management-service" 200 GET "$BASE/api/v1/projects/$PROJECT_ID/ci-target" "${AUTH[@]}"
body_has "... says whether running from QA Vision is available" '"available"'
check "run requests -> test-management-service" 200 GET "$BASE/api/v1/projects/$PROJECT_ID/run-requests" "${AUTH[@]}"
body_has "... an empty list" '"total":0'
```

- [ ] **Step 2: Run the smoke and check it fails.** Run `set -a; . ./.env; set +a; docker compose up -d --build --wait test-management-service gateway`, then `bash scripts/smoke_gateway.sh`.
Expected: the two new checks FAIL. Without the route, project-service answers 404.

- [ ] **Step 3: Route, configure and document.**
- **`gateway/nginx.conf.template`:**

```nginx
        location ~ ^/api/v1/projects/[0-9]+/(cases|case-labels|case-folders|case-features|suites|ci-target|run-requests)(/|$) {
```

- **`docker-compose.yml`:** under `x-testmgmt-env`, add `TM_SECRETS_KEY: ${TM_SECRETS_KEY:-}`.
- **`.env.example`:** add after the Gherkin import limits:

```bash
# Running tests from QA Vision (test-management-service): the Fernet key that encrypts each project's
# GitHub token. Empty turns the feature off (Settings says so). Generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Changing it makes stored tokens unreadable: owners then save the token again in Settings.
#TM_SECRETS_KEY=
```

- **`platforms/test-management-service/README.md`:**
  - In "Run", the gateway list becomes `/api/v1/projects/{id}/(cases|case-labels|case-folders|case-features|suites|ci-target|run-requests)`.
  - Add these rows to the API table:

| Method | Path | |
|---|---|---|
| `GET` | `/ci-target` | `{available, configured, provider, repo, workflow, ref, token_last4, token_expires_at, updated_at, last_change}`; every role; the token itself is never returned |
| `PUT` | `/ci-target` | owner or admin; `{repo, workflow="qa-vision-run.yml", ref="main", token?}`; the token is required on the first save; checked with GitHub first: 422 "token invalid or expired" (401), "token has no Actions access to this repository" (403), "repository or workflow not found. The workflow file must exist on the repository's default branch" (404); 503 without `TM_SECRETS_KEY` or on a GitHub rate limit |
| `DELETE` | `/ci-target` | owner or admin; 409 while a run is active; the audit trail (`ci_target_events`) is kept |
| `POST` | `/run-requests` | owner, admin or member; `{case_numbers: [1..200]}` or `{suite_id}`; 201 with the request (also when it is `failed_to_start`); 412 no target; 409 `run_active`; 422 names the cases that cannot run (manual, archived, unknown, or with no scenario name yet: re-import) |
| `GET` | `/run-requests?limit=&offset=` | `{total, items}`, newest first; an active request is refreshed from GitHub when last checked over 5 s ago; `refreshing` says whether to keep polling |
| `GET` | `/run-requests/{id}` | the same refresh rule |
| `POST` | `/run-requests/{id}/stop` | owner, admin or member; cancels on GitHub (`cancelling`, `stopped_by`); 409 `run_finished` |

  - Add a section `## Run from QA Vision (Play and Stop)`. It covers:
    - **Design:** link the spec `docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md`.
    - **Setup:**
      1. Set `TM_SECRETS_KEY` (the generation command, as in `.env.example`).
      2. Copy `templates/github/qa-vision-run.yml` to `.github/workflows/` and `templates/github/qa-vision-run.mjs` to `.github/scripts/` **on the repository's default branch** before the first Play. GitHub accepts `workflow_dispatch` only for a workflow on the default branch.
      3. Add the secret `QAV_API_KEY` and the variable `QAV_URL` in the repository.
      4. An owner or admin saves the repository and token in Project Settings.
    - **Limits:**
      - 200 cases per run;
      - one active run per project;
      - GitHub is polled at most every 5 s, only while someone views the run;
      - a run not seen 2 minutes after Play is `failed_to_start`;
      - workers 1, retries 0.
    - **Selection:**
      - Selection is by file and the raw scenario name. Outline placeholders match any value.
      - The same scenario name in two selected files runs in both.
      - A path the workflow's path rule rejects fails the job, with a message.
    - **After deploying migration 004:** run a full import once to fill `scenario_name`. Until then, Play on an old imported case answers 422 "re-import the .feature files first".
    - **Security note:**
      - **What the token can do:** a fine-grained token limited to one repository with "Actions: Read and write". It can start, cancel, re-run and delete that repository's workflow runs and logs, and read its workflow files. It cannot read or change code.
      - **At rest:** it is stored Fernet-encrypted with `TM_SECRETS_KEY` and never returned or logged. Responses show the last 4 characters.
      - **Who can do what:** owners and admins set and remove it. Owners, admins and members can run and stop.
      - **To revoke:** on GitHub, Settings › Developer settings › Fine-grained tokens › Revoke, then Disconnect in Project Settings.

- [ ] **Step 3b: Make sure the repo-root `.env` has a `TM_SECRETS_KEY`.** The end-to-end check needs it. The command generates a key with `Fernet.generate_key()` and appends it only if the variable is missing. It never prints the key: no `echo`, no `cat .env`, and nothing about it in the report beyond "present" or "added". Run it from the repo root in Git Bash:

```bash
grep -q '^TM_SECRETS_KEY=.' .env 2>/dev/null && echo "TM_SECRETS_KEY present" || {
  platforms/test-management-service/.venv/Scripts/python -c "from cryptography.fernet import Fernet; import sys; sys.stdout.write('TM_SECRETS_KEY=' + Fernet.generate_key().decode() + '\n')" >> .env
  echo "TM_SECRETS_KEY added"
}
```

`.env` is git-ignored, so it is never committed. If `.env` does not end with a newline, add one first (`[ -n "$(tail -c1 .env)" ] && printf '\n' >> .env`) so the key starts on its own line.

- [ ] **Step 4: Rebuild, run the smoke, and check it passes.** Run `set -a; . ./.env; set +a; docker compose up -d --build --wait test-management-service gateway`, then `bash scripts/smoke_gateway.sh`. Every check, the four new ones included, should be ok.

`test-management-migrate` runs `alembic upgrade head` (004) as a dependency of the service. Never use `down -v`.

- [ ] **Step 5: Commit.**

```bash
FILES="gateway/nginx.conf.template scripts/smoke_gateway.sh docker-compose.yml .env.example platforms/test-management-service/README.md"
git add $FILES && git commit -m "feat(gateway): route ci-target and run-requests; docs: Play and Stop, TM_SECRETS_KEY; smoke" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

---

### Task 7: Dashboard API client and the "Run from QA Vision" Settings section

**Files:**
- Create: `dashboard/src/api/runRequests.ts`
- Create: `dashboard/src/lib/useUserNames.ts`
- Create: `dashboard/src/components/CiTargetCard.tsx`
- Modify: `dashboard/src/pages/ProjectSettingsPage.tsx` (mount for owner and admin)
- Modify: `dashboard/src/test/server.ts` (global defaults)
- Modify: `dashboard/src/index.css` (`.warn-note`)
- Test: `dashboard/src/components/CiTargetCard.test.tsx`, `dashboard/src/pages/ProjectSettingsPage.test.tsx` (append)

**Interfaces:**
- Consumes: Task 3's and Task 4's HTTP shapes. msw stubs them; no backend is needed.
- Produces, in `src/api/runRequests.ts`:

```ts
export interface CiTargetChange { action: "created" | "updated" | "token_replaced" | "deleted"; user_id: number; at: string }
export interface CiTarget { available: boolean; configured: boolean; provider: string | null; repo: string | null;
  workflow: string | null; ref: string | null; token_last4: string | null; token_expires_at: string | null;
  updated_at: string | null; last_change: CiTargetChange | null }
export interface CiTargetInput { repo: string; workflow: string; ref: string; token?: string }
export type RunRequestStatus = "queued" | "running" | "completed" | "cancelling" | "cancelled" | "failed_to_start";
export interface SelectedCase { case_number: number; path: string; name: string }
export interface RunRequest { id: number; requested_by: number; requested_at: string; selection: SelectedCase[];
  case_count: number; suite_id: number | null; status: RunRequestStatus; conclusion: string | null;
  github_run_id: number | null; github_run_url: string | null; stopped_by: number | null; stopped_at: string | null;
  error: string | null; checked_at: string | null; refreshing: boolean }
export type RunSelection = { case_numbers: number[] } | { suite_id: number };
export const MAX_RUN_CASES = 200;
export const EXPIRY_WARNING_DAYS = 14;
export function isActive(r: RunRequest): boolean;
export function tokenState(target: CiTarget, now?: number): "ok" | "expiring" | "expired";
export function formatDay(iso: string): string;          // "12 Mar 2027", in UTC
export function getCiTarget(projectId: number): Promise<CiTarget>;
export function saveCiTarget(projectId: number, body: CiTargetInput): Promise<CiTarget>;
export function deleteCiTarget(projectId: number): Promise<void>;
export function createRunRequest(projectId: number, selection: RunSelection): Promise<RunRequest>;
export function listRunRequests(projectId: number, q: { limit: number; offset: number }): Promise<{ total: number; items: RunRequest[] }>;
export function getRunRequest(projectId: number, requestId: number): Promise<RunRequest>;
export function stopRunRequest(projectId: number, requestId: number): Promise<RunRequest>;
```

- Also produces:
  - `useUserNames(projectId): (userId: number | null) => string`, which gives the email, or "user #<id>";
  - `CiTargetCard({ projectId })` (default export) and `ExpiryWarning({ target })` (named export);
  - the query key `["ci-target", projectId]`.

- [ ] **Step 1: Invoke `ui-ux-pro-max`.** Searches: `"settings form secret token field replace" --domain ux` and `"warning banner expiry accessible" --domain ux`.

- [ ] **Step 2: Add the global msw defaults.** Append these handlers inside `setupServer(...)` in `src/test/server.ts`:

```ts
  // Run from QA Vision: pages that show Play or the run panel ask for these; tests about them override
  http.get("/api/v1/projects/:projectId/ci-target", () =>
    HttpResponse.json({ available: true, configured: false, provider: null, repo: null, workflow: null, ref: null,
      token_last4: null, token_expires_at: null, updated_at: null, last_change: null })),
  http.get("/api/v1/projects/:projectId/run-requests", () => HttpResponse.json({ total: 0, items: [] })),
  // Names of the people who ran or stopped something
  http.get("/api/v1/organizations/:orgId/members", () => HttpResponse.json([])),
```

- [ ] **Step 3: Write the failing tests.** `src/components/CiTargetCard.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CiTargetCard from "./CiTargetCard";

const P = "/api/v1/projects/42";
const NONE = { available: true, configured: false, provider: null, repo: null, workflow: null, ref: null,
  token_last4: null, token_expires_at: null, updated_at: null, last_change: null };
const CONNECTED = { ...NONE, configured: true, provider: "github", repo: "acme/obt", workflow: "qa-vision-run.yml",
  ref: "main", token_last4: "a1b2", token_expires_at: "2027-03-12T00:00:00Z", updated_at: "2026-10-07T10:00:00Z",
  last_change: { action: "created", user_id: 7, at: "2026-10-07T10:00:00Z" } };
const TOKEN = "github_pat_xyz0000000000000000a1b2";

function renderCard() {
  setAccessToken("acc");
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, name: "Web", organization_id: 1, my_role: "owner" })),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([
      { id: 1, organization_id: 1, user_id: 7, email: "ana@example.com", role: "owner", status: "active",
        created_at: "2026-01-01T00:00:00Z", updated_at: null }])),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><CiTargetCard projectId={42} /></MemoryRouter></QueryClientProvider>);
}

test("a first save sends repo, workflow, branch and token, then shows the connection", async () => {
  let sent: unknown = null;
  let target: typeof NONE | typeof CONNECTED = NONE;
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(target)),
    http.put(`${P}/ci-target`, async ({ request }) => {
      sent = await request.json();
      target = CONNECTED;
      return HttpResponse.json(CONNECTED);
    }),
  );
  renderCard();
  await userEvent.type(await screen.findByLabelText("Repository"), "acme/obt");
  expect(screen.getByLabelText("Workflow file")).toHaveValue("qa-vision-run.yml");
  expect(screen.getByLabelText("Branch")).toHaveValue("main");
  await userEvent.type(screen.getByLabelText("Token"), TOKEN);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("Connected: acme/obt · token …a1b2 · expires 12 Mar 2027")).toBeInTheDocument();
  expect(sent).toEqual({ repo: "acme/obt", workflow: "qa-vision-run.yml", ref: "main", token: TOKEN });
  expect(await screen.findByText("Last changed by ana@example.com on 7 Oct 2026")).toBeInTheDocument();
  expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Replace token" })).toBeInTheDocument();
});

test("GitHub's specific refusal shows next to the form", async () => {
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(NONE)),
    http.put(`${P}/ci-target`, () =>
      HttpResponse.json({ detail: "token has no Actions access to this repository" }, { status: 422 })),
  );
  renderCard();
  await userEvent.type(await screen.findByLabelText("Repository"), "acme/obt");
  await userEvent.type(screen.getByLabelText("Token"), TOKEN);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("token has no Actions access to this repository");
});

test("saving keeps the stored token; Replace token sends a new one", async () => {
  const bodies: unknown[] = [];
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(CONNECTED)),
    http.put(`${P}/ci-target`, async ({ request }) => { bodies.push(await request.json()); return HttpResponse.json(CONNECTED); }),
  );
  renderCard();
  const branch = await screen.findByLabelText("Branch");
  await userEvent.clear(branch);
  await userEvent.type(branch, "release");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(bodies).toEqual([{ repo: "acme/obt", workflow: "qa-vision-run.yml", ref: "release" }]));
  await userEvent.click(screen.getByRole("button", { name: "Replace token" }));
  expect(screen.getByLabelText("Token")).toHaveFocus();
  await userEvent.type(screen.getByLabelText("Token"), "github_pat_new0000000000000000zzzz");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(bodies).toHaveLength(2));
  expect(bodies[1]).toMatchObject({ token: "github_pat_new0000000000000000zzzz" });
});

test("disconnect asks first, then removes the target", async () => {
  let deleted = false;
  let target: typeof NONE | typeof CONNECTED = CONNECTED;
  server.use(
    http.get(`${P}/ci-target`, () => HttpResponse.json(target)),
    http.delete(`${P}/ci-target`, () => { deleted = true; target = NONE; return new HttpResponse(null, { status: 204 }); }),
  );
  renderCard();
  await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  expect(deleted).toBe(false);
  expect(screen.getByText(/Disconnect acme\/obt\?/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(deleted).toBe(true));
  await waitFor(() => expect(screen.getByLabelText("Repository")).toHaveValue(""));
});

test("a server without TM_SECRETS_KEY says so and shows no form", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...NONE, available: false })));
  renderCard();
  expect(await screen.findByText(/not configured on this server/i)).toBeInTheDocument();
  expect(screen.queryByLabelText("Repository")).not.toBeInTheDocument();
});

test("from 14 days before expiry the card warns; after expiry it says expired", async () => {
  const soon = new Date(Date.now() + 5 * 86_400_000).toISOString();
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, token_expires_at: soon })));
  renderCard();
  expect(await screen.findByText(/^The GitHub token expires on .+\. Replace it in Settings$/)).toBeInTheDocument();
});

test("an expired token says so", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, token_expires_at: "2020-01-01T00:00:00Z" })));
  renderCard();
  expect(await screen.findByText("The GitHub token expired on 1 Jan 2020. Replace it in Settings")).toBeInTheDocument();
});
```

Append to `src/pages/ProjectSettingsPage.test.tsx`:

```tsx
test("Run from QA Vision is shown to owners and admins", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage("admin");
  expect(await screen.findByRole("heading", { name: "Run from QA Vision" })).toBeInTheDocument();
});

test("members do not see Run from QA Vision", async () => {
  server.use(http.get("/api/v1/projects/42/api-keys", () => HttpResponse.json([])));
  renderPage("member");
  await screen.findByRole("button", { name: /add repository/i }); // the role has loaded
  expect(screen.queryByRole("heading", { name: "Run from QA Vision" })).not.toBeInTheDocument();
});
```

- [ ] **Step 4: Run the tests and check they fail.**

Run: `cd dashboard && npx vitest run src/components/CiTargetCard.test.tsx src/pages/ProjectSettingsPage.test.tsx`
Expected: FAIL (`Failed to resolve import "./CiTargetCard"`).

- [ ] **Step 5: Implement the API client.** `src/api/runRequests.ts` holds the types from Interfaces, plus:

```ts
import { apiFetch, buildQuery } from "./http";

// Mirrors platforms/test-management-service/src/casebook/schemas/ci.py

export interface CiTargetChange { action: "created" | "updated" | "token_replaced" | "deleted"; user_id: number; at: string }

export interface CiTarget {
  /** False when the server has no TM_SECRETS_KEY: nothing can be configured. */
  available: boolean;
  configured: boolean;
  provider: string | null;
  repo: string | null;
  workflow: string | null;
  ref: string | null;
  token_last4: string | null;
  token_expires_at: string | null;
  updated_at: string | null;
  last_change: CiTargetChange | null;
}

export interface CiTargetInput {
  repo: string;
  workflow: string;
  ref: string;
  /** Only when setting or replacing it; without it the stored token is kept. */
  token?: string;
}

export type RunRequestStatus = "queued" | "running" | "completed" | "cancelling" | "cancelled" | "failed_to_start";

export interface SelectedCase { case_number: number; path: string; name: string }

export interface RunRequest {
  id: number;
  requested_by: number;
  requested_at: string;
  selection: SelectedCase[];
  case_count: number;
  suite_id: number | null;
  status: RunRequestStatus;
  conclusion: string | null;
  github_run_id: number | null;
  github_run_url: string | null;
  stopped_by: number | null;
  stopped_at: string | null;
  error: string | null;
  checked_at: string | null;
  /** True while the server still checks GitHub for this request: keep polling. */
  refreshing: boolean;
}

export type RunSelection = { case_numbers: number[] } | { suite_id: number };

export const MAX_RUN_CASES = 200;
export const EXPIRY_WARNING_DAYS = 14;
const DAY_MS = 86_400_000;
const base = (projectId: number) => `/api/v1/projects/${projectId}`;

export function isActive(r: RunRequest): boolean {
  return r.status === "queued" || r.status === "running" || r.status === "cancelling";
}

/** "expiring" from EXPIRY_WARNING_DAYS before token_expires_at; a token without expiry is always "ok". */
export function tokenState(target: CiTarget, now: number = Date.now()): "ok" | "expiring" | "expired" {
  if (!target.token_expires_at) return "ok";
  const expires = Date.parse(target.token_expires_at);
  if (expires <= now) return "expired";
  return expires - now <= EXPIRY_WARNING_DAYS * DAY_MS ? "expiring" : "ok";
}

/** "12 Mar 2027", read in UTC so the day never shifts with the viewer's time zone. */
export function formatDay(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(iso));
}

export function getCiTarget(projectId: number): Promise<CiTarget> {
  return apiFetch(`${base(projectId)}/ci-target`);
}

export function saveCiTarget(projectId: number, body: CiTargetInput): Promise<CiTarget> {
  return apiFetch(`${base(projectId)}/ci-target`, { method: "PUT", body: JSON.stringify(body) });
}

export function deleteCiTarget(projectId: number): Promise<void> {
  return apiFetch(`${base(projectId)}/ci-target`, { method: "DELETE" });
}

export function createRunRequest(projectId: number, selection: RunSelection): Promise<RunRequest> {
  return apiFetch(`${base(projectId)}/run-requests`, { method: "POST", body: JSON.stringify(selection) });
}

export function listRunRequests(projectId: number, q: { limit: number; offset: number }): Promise<{ total: number; items: RunRequest[] }> {
  return apiFetch(`${base(projectId)}/run-requests${buildQuery(q)}`);
}

export function getRunRequest(projectId: number, requestId: number): Promise<RunRequest> {
  return apiFetch(`${base(projectId)}/run-requests/${requestId}`);
}

export function stopRunRequest(projectId: number, requestId: number): Promise<RunRequest> {
  return apiFetch(`${base(projectId)}/run-requests/${requestId}/stop`, { method: "POST", body: "{}" });
}
```

- [ ] **Step 6: Implement `useUserNames`.** `src/lib/useUserNames.ts`:

```ts
import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { getProject, listMembers } from "../api/orgs";

/** A person's name for "started by", "stopped by" and "last changed by": their email from the
 *  organization's members, or "user #<id>" while it loads or when it is unknown. */
export function useUserNames(projectId: number): (userId: number | null) => string {
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId) });
  const orgId = project.data?.organization_id;
  const members = useQuery({
    queryKey: ["org", orgId, "members"],
    queryFn: () => listMembers(orgId as number),
    enabled: orgId != null,
    staleTime: 5 * 60_000,
  });
  return useCallback(
    (userId: number | null) => {
      if (userId == null) return "someone";
      return members.data?.find((m) => m.user_id === userId)?.email ?? `user #${userId}`;
    },
    [members.data],
  );
}
```

- [ ] **Step 7: Implement `CiTargetCard`.** `src/components/CiTargetCard.tsx`:

```tsx
import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { CiTarget, deleteCiTarget, formatDay, getCiTarget, saveCiTarget, tokenState } from "../api/runRequests";
import { useUserNames } from "../lib/useUserNames";
import ConfirmButton from "./ConfirmButton";
import ErrorBanner from "./ErrorBanner";

const DEFAULT_WORKFLOW = "qa-vision-run.yml";
const DEFAULT_BRANCH = "main";

/** Owners and admins see this from 14 days before the token expires (Settings and the run panel). */
export function ExpiryWarning({ target }: { target: CiTarget }) {
  const state = tokenState(target);
  if (state === "ok" || !target.token_expires_at) return null;
  const day = formatDay(target.token_expires_at);
  return (
    <p className="note warn-note" role="note">
      <CircleAlert size={16} aria-hidden="true" />
      <span>
        {state === "expired"
          ? `The GitHub token expired on ${day}. Replace it in Settings`
          : `The GitHub token expires on ${day}. Replace it in Settings`}
      </span>
    </p>
  );
}

/** Settings › Run from QA Vision: the repository, workflow, branch and token Play dispatches with. */
export default function CiTargetCard({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const queryKey = ["ci-target", projectId];
  const target = useQuery({ queryKey, queryFn: () => getCiTarget(projectId) });
  const nameOf = useUserNames(projectId);
  const [repo, setRepo] = useState("");
  const [workflow, setWorkflow] = useState(DEFAULT_WORKFLOW);
  const [ref, setRef] = useState(DEFAULT_BRANCH);
  const [token, setToken] = useState("");
  const [replacing, setReplacing] = useState(false);

  const data = target.data;
  useEffect(() => {
    if (!data) return;
    setRepo(data.repo ?? "");
    setWorkflow(data.workflow ?? DEFAULT_WORKFLOW);
    setRef(data.ref ?? DEFAULT_BRANCH);
    setToken("");
    setReplacing(false);
  }, [data]);

  const save = useMutation({
    mutationFn: () => saveCiTarget(projectId, {
      repo: repo.trim(), workflow: workflow.trim(), ref: ref.trim(), ...(token.trim() ? { token: token.trim() } : {}),
    }),
    onSuccess: (saved) => qc.setQueryData(queryKey, saved),
  });
  const disconnect = useMutation({
    mutationFn: () => deleteCiTarget(projectId),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <div className="card">
      <h3>Run from QA Vision</h3>
      <p className="muted">
        Play runs the selected scenarios in this repository's GitHub Actions, through a dedicated workflow.
        QA Vision never runs test code itself.
      </p>
      {target.error != null && <ErrorBanner error={target.error} onRetry={() => target.refetch()} />}
      {target.isPending && <p className="muted">Loading…</p>}
      {data && !data.available && (
        <p className="note" role="note">
          Running tests from QA Vision is not configured on this server. An administrator sets{" "}
          <code>TM_SECRETS_KEY</code> on test-management-service.
        </p>
      )}
      {data?.available && (
        <>
          {data.configured && (
            <>
              <p className="success-note" role="status">
                <CheckCircle2 size={16} aria-hidden="true" />
                <span>
                  {`Connected: ${data.repo} · token …${data.token_last4} · `}
                  {data.token_expires_at ? `expires ${formatDay(data.token_expires_at)}` : "no expiry"}
                </span>
              </p>
              <ExpiryWarning target={data} />
            </>
          )}
          {data.last_change && (
            <p className="muted">{`Last changed by ${nameOf(data.last_change.user_id)} on ${formatDay(data.last_change.at)}`}</p>
          )}
          <form className="form-stack" onSubmit={onSubmit}>
            <label>
              Repository
              <input required value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="owner/name"
                pattern="[A-Za-z0-9\-]{1,39}/[A-Za-z0-9._\-]{1,100}" title="owner/name, as on github.com"
                autoComplete="off" spellCheck={false} />
            </label>
            <label>
              Workflow file
              <input required value={workflow} onChange={(e) => setWorkflow(e.target.value)} autoComplete="off" spellCheck={false} />
            </label>
            <label>
              Branch
              <input required value={ref} onChange={(e) => setRef(e.target.value)} autoComplete="off" spellCheck={false} />
            </label>
            {data.configured && !replacing ? (
              <div>
                <button type="button" onClick={() => setReplacing(true)}>Replace token</button>
              </div>
            ) : (
              <label>
                Token
                <input type="password" required={!data.configured} value={token} autoFocus={replacing}
                  onChange={(e) => setToken(e.target.value)} autoComplete="off" spellCheck={false} />
              </label>
            )}
            <div className="button-row">
              <button className="primary" type="submit" disabled={save.isPending}>
                {save.isPending ? "Checking with GitHub…" : "Save"}
              </button>
            </div>
          </form>
          {save.error != null && <ErrorBanner error={save.error} />}
          {data.configured && (
            <ConfirmButton
              label="Disconnect"
              question={`Disconnect ${data.repo}? Nobody can run tests from QA Vision until a token is saved again.`}
              confirmLabel="Disconnect"
              onConfirm={() => disconnect.mutate()}
              disabled={disconnect.isPending}
            />
          )}
          {disconnect.error != null && <ErrorBanner error={disconnect.error} />}
        </>
      )}
    </div>
  );
}
```

In `index.css`, after `.note`, add:

```css
/* A warning note (token expiry, the Play confirmation): amber edge, text stays Ink */
.warn-note { display: flex; gap: var(--space-2); align-items: flex-start; border-color: var(--status-rerun); background: color-mix(in srgb, var(--status-rerun) 10%, transparent); }
.warn-note svg { color: var(--status-rerun); flex-shrink: 0; margin-top: 2px; }
```

In `ProjectSettingsPage.tsx`, import `CiTargetCard` and render it after the "Wire up your CI" card:

```tsx
      {project.data != null && MANAGE_ROLES.includes(project.data.my_role ?? "") && <CiTargetCard projectId={id} />}
```

- [ ] **Step 8: Run the tests and the four CI steps, and check they pass.**

Run: `npx vitest run src/components/CiTargetCard.test.tsx src/pages/ProjectSettingsPage.test.tsx`, then `npm run lint && npm run typecheck && npx vitest run && npm run build`
Expected: PASS, with pristine output. If an existing test now trips over the new card, for example on an ambiguous `role="status"` for an owner, fix that test's query. Do not change the behaviour.

- [ ] **Step 9: Commit.**

```bash
D=dashboard/src
FILES="$D/api/runRequests.ts $D/lib/useUserNames.ts $D/components/CiTargetCard.tsx $D/components/CiTargetCard.test.tsx $D/pages/ProjectSettingsPage.tsx $D/pages/ProjectSettingsPage.test.tsx $D/test/server.ts $D/index.css"
git add $FILES && git commit -m "feat(dashboard): Run from QA Vision settings section" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

---

### Task 8: Play from a case, a selection and a suite, with the confirmation and disabled reasons

**Files:**
- Create: `dashboard/src/lib/useRunGate.ts`
- Create: `dashboard/src/components/RunControl.tsx`
- Modify: `dashboard/src/pages/CaseEditorPage.tsx` (Run on imported, non-archived cases)
- Modify: `dashboard/src/pages/CasesPage.tsx` (checkboxes, "Select all", the "Run selected (n)" bar)
- Modify: `dashboard/src/pages/SuiteDetailPage.tsx` ("Run suite")
- Modify: `dashboard/src/index.css` (Play, confirmation and selection styles)
- Test: `dashboard/src/pages/RunFromQaVision.test.tsx`

**Interfaces:**
- Consumes: Task 7's `runRequests.ts` (types, `createRunRequest`, `listRunRequests`, `getCiTarget`, `isActive`, `tokenState`, `MAX_RUN_CASES`).
- Produces:

```ts
// src/lib/useRunGate.ts
export const RUN_POLL_MS = 5_000;
export type RunGate = { ok: true; target: CiTarget } | { ok: false; reason: string; toSettings: boolean };
export function useLatestRunRequest(projectId: number): UseQueryResult<RunRequest | null>; // key ["run-requests", id, "latest"], polls every 5 s while refreshing
export function useCiTarget(projectId: number): UseQueryResult<CiTarget>;                    // key ["ci-target", id]
export function useRunGate(projectId: number): RunGate | undefined;                          // undefined while loading
export function gate(role: string | undefined, target: CiTarget, latest: RunRequest | null, now?: number): RunGate;
// src/components/RunControl.tsx (default export)
export default function RunControl(props: { projectId: number; cases: { number: number; title: string }[];
  selection: RunSelection; label: string; onStarted?: () => void }): JSX.Element;
```

- [ ] **Step 1: Invoke `ui-ux-pro-max`.** Searches: `"confirmation before risky action inline" --domain ux`, `"bulk selection table sticky action bar" --domain ux` and `"disabled button reason text" --domain ux`.

- [ ] **Step 2: Write the failing tests.** `src/pages/RunFromQaVision.test.tsx`:

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { delay, http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import CasesPage from "./CasesPage";
import CaseEditorPage from "./CaseEditorPage";
import SuiteDetailPage from "./SuiteDetailPage";

const P = "/api/v1/projects/42";
const TARGET = { available: true, configured: true, provider: "github", repo: "acme/obt", workflow: "qa-vision-run.yml",
  ref: "main", token_last4: "a1b2", token_expires_at: null, updated_at: "2026-10-07T10:00:00Z", last_change: null };

const kase = (number: number, extra: object = {}) => ({
  number, key: `TC-${number}`, title: `Case ${number}`, description: null, steps: [], labels: [], priority: "medium",
  status: "draft", automated_test_key: null, automated_name: null, created_by: 1, created_at: "2026-10-06T10:00:00Z",
  updated_by: null, updated_at: null, suites: [], source_path: "tests/features/a.feature", gherkin: "Scenario: x",
  feature_name: "A", ...extra,
});

const runRequest = (extra: object = {}) => ({
  id: 9, requested_by: 7, requested_at: new Date().toISOString(),
  selection: [{ case_number: 1, path: "tests/features/a.feature", name: "Case 1" }], case_count: 1, suite_id: null,
  // After a 200 dispatch the request carries its GitHub run from the start
  status: "queued", conclusion: null, github_run_id: 501, github_run_url: "https://github.com/acme/obt/actions/runs/501",
  stopped_by: null, stopped_at: null,
  error: null, checked_at: null, refreshing: true, ...extra,
});

function asRole(role: string) {
  server.use(http.get(P, () => HttpResponse.json({ id: 42, organization_id: 1, name: "Web", my_role: role })));
}

beforeEach(() => {
  asRole("member");
  server.use(
    http.get(`${P}/case-features`, () => HttpResponse.json([])),
    http.get(`${P}/case-folders`, () => HttpResponse.json([])),
    http.get(`${P}/case-labels`, () => HttpResponse.json([])),
    http.get(`${P}/cases`, () => HttpResponse.json({ total: 0, items: [] })),
    http.get(`${P}/ci-target`, () => HttpResponse.json(TARGET)),
    http.get(`${P}/run-requests`, () => HttpResponse.json({ total: 0, items: [] })),
  );
});

function renderAt(url: string) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/projects/:projectId/cases" element={<CasesPage />} />
          <Route path="/projects/:projectId/cases/:caseNumber" element={<CaseEditorPage />} />
          <Route path="/projects/:projectId/suites/:suiteId" element={<SuiteDetailPage />} />
          <Route path="/projects/:projectId/settings" element={<p>Settings page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function listing(items: object[], total = items.length) {
  server.use(http.get(`${P}/cases`, ({ request }) => {
    const sp = new URL(request.url).searchParams;
    const offset = Number(sp.get("offset") ?? 0);
    const limit = Number(sp.get("limit") ?? 50);
    return HttpResponse.json({ total, items: items.slice(offset, offset + limit) });
  }));
}

test("Run on an imported case asks first, then starts it", async () => {
  let sent: unknown = null;
  server.use(
    http.get(`${P}/cases/1`, () => HttpResponse.json(kase(1))),
    http.post(`${P}/run-requests`, async ({ request }) => { sent = await request.json(); return HttpResponse.json(runRequest(), { status: 201 }); }),
  );
  renderAt("/projects/42/cases/1");
  await userEvent.click(await screen.findByRole("button", { name: "Run" }));
  const dialog = screen.getByRole("dialog", { name: "Run 1 test?" });
  expect(within(dialog).getByText("TC-1 · Case 1")).toBeInTheDocument();
  expect(within(dialog).getByText("acme/obt @ main")).toBeInTheDocument();
  expect(within(dialog).getByText("Tests may create real bookings in staging")).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
  expect(sent).toBeNull();
  await userEvent.click(within(dialog).getByRole("button", { name: "Run" }));
  await waitFor(() => expect(sent).toEqual({ case_numbers: [1] }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

test("Cancel and Escape close the dialog without a request and return focus to Run", async () => {
  let posts = 0;
  server.use(
    http.get(`${P}/cases/1`, () => HttpResponse.json(kase(1))),
    http.post(`${P}/run-requests`, () => { posts += 1; return HttpResponse.json(runRequest(), { status: 201 }); }),
  );
  renderAt("/projects/42/cases/1");
  const run = await screen.findByRole("button", { name: "Run" });
  await userEvent.click(run);
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(run).toHaveFocus();
  await userEvent.click(run);
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(run).toHaveFocus();
  expect(posts).toBe(0);
});

test("a double click on Run starts one run", async () => {
  let posts = 0;
  server.use(
    http.get(`${P}/cases/1`, () => HttpResponse.json(kase(1))),
    http.post(`${P}/run-requests`, async () => { posts += 1; await delay(50); return HttpResponse.json(runRequest(), { status: 201 }); }),
  );
  renderAt("/projects/42/cases/1");
  await userEvent.click(await screen.findByRole("button", { name: "Run" }));
  await userEvent.dblClick(within(screen.getByRole("dialog")).getByRole("button", { name: "Run" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(posts).toBe(1);
});

test("the server's refusal shows inside the dialog", async () => {
  server.use(
    http.get(`${P}/cases/1`, () => HttpResponse.json(kase(1))),
    http.post(`${P}/run-requests`, () => HttpResponse.json(
      { detail: "TC-1: re-import the .feature files first" }, { status: 422 })),
  );
  renderAt("/projects/42/cases/1");
  await userEvent.click(await screen.findByRole("button", { name: "Run" }));
  const dialog = screen.getByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Run" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("re-import the .feature files first");
});

test("a manual case has no Run", async () => {
  server.use(http.get(`${P}/cases/2`, () => HttpResponse.json(kase(2, { source_path: null, gherkin: null }))));
  renderAt("/projects/42/cases/2");
  await screen.findByRole("heading", { name: /TC-2/ });
  expect(screen.queryByRole("button", { name: "Run" })).not.toBeInTheDocument();
});

test("selected rows run together; manual cases have no checkbox", async () => {
  let sent: unknown = null;
  listing([kase(1), kase(2, { source_path: null }), kase(3)]);
  server.use(http.post(`${P}/run-requests`, async ({ request }) => { sent = await request.json(); return HttpResponse.json(runRequest(), { status: 201 }); }));
  renderAt("/projects/42/cases");
  await userEvent.click(await screen.findByRole("checkbox", { name: "Select TC-1 Case 1" }));
  expect(screen.queryByRole("checkbox", { name: /TC-2/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox", { name: "Select TC-3 Case 3" }));
  await userEvent.click(screen.getByRole("button", { name: "Run selected (2)" }));
  const dialog = screen.getByRole("dialog", { name: "Run 2 tests?" });
  await userEvent.click(within(dialog).getByRole("button", { name: "Run" }));
  await waitFor(() => expect(sent).toEqual({ case_numbers: [1, 3] }));
  await waitFor(() => expect(screen.queryByRole("button", { name: /Run selected/ })).not.toBeInTheDocument());
});

test("the dialog lists ten cases and then how many more", async () => {
  listing(Array.from({ length: 12 }, (_, i) => kase(i + 1)));
  renderAt("/projects/42/cases");
  await userEvent.click(await screen.findByRole("checkbox", { name: "Select all imported cases on this page" }));
  await userEvent.click(screen.getByRole("button", { name: "Run selected (12)" }));
  const dialog = screen.getByRole("dialog", { name: "Run 12 tests?" });
  expect(within(dialog).getAllByRole("listitem")).toHaveLength(10);
  expect(within(dialog).getByText("+2 more")).toBeInTheDocument();
});

test("at most 200 cases can be selected", async () => {
  listing(Array.from({ length: 260 }, (_, i) => kase(i + 1)));
  renderAt("/projects/42/cases");
  for (let page = 0; page < 4; page++) {
    await userEvent.click(await screen.findByRole("checkbox", { name: "Select all imported cases on this page" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("link", { name: `Case ${(page + 1) * 50 + 1}` });
  }
  expect(screen.getByRole("button", { name: "Run selected (200)" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Select TC-201 Case 201" })).toBeDisabled();
  expect(screen.getByText("At most 200 cases per run")).toBeInTheDocument();
});

test("Run suite sends the suite id", async () => {
  let sent: unknown = null;
  server.use(
    http.get(`${P}/suites/5`, () => HttpResponse.json({
      id: 5, name: "Smoke", description: null, case_count: 2, created_at: "2026-10-06T10:00:00Z", updated_at: null,
      cases: [1, 2].map((n) => ({ number: n, key: `TC-${n}`, title: `Case ${n}`, status: "draft", priority: "medium",
        labels: [], automated_test_key: null })) })),
    http.post(`${P}/run-requests`, async ({ request }) => { sent = await request.json(); return HttpResponse.json(runRequest(), { status: 201 }); }),
  );
  renderAt("/projects/42/suites/5");
  await userEvent.click(await screen.findByRole("button", { name: "Run suite" }));
  await userEvent.click(within(screen.getByRole("dialog", { name: "Run 2 tests?" })).getByRole("button", { name: "Run" }));
  await waitFor(() => expect(sent).toEqual({ suite_id: 5 }));
});

test.each([
  ["no target", "member", { ...TARGET, configured: false }, [], "Configure in Settings"],
  ["a viewer", "viewer", TARGET, [], "Viewers can't run tests"],
  ["an active run", "member", TARGET, [runRequest({ status: "running" })], "A run is in progress"],
  ["an expired token", "member", { ...TARGET, token_expires_at: "2020-01-01T00:00:00Z" }, [], "GitHub token expired"],
])("Run is disabled, with the reason, for %s", async (_, role, target, items, reason) => {
  asRole(role);
  server.use(
    http.get(`${P}/cases/1`, () => HttpResponse.json(kase(1))),
    http.get(`${P}/ci-target`, () => HttpResponse.json(target)),
    http.get(`${P}/run-requests`, () => HttpResponse.json({ total: items.length, items })),
  );
  renderAt("/projects/42/cases/1");
  expect(await screen.findByText(reason)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
});

test("Configure in Settings links to the project's settings", async () => {
  server.use(
    http.get(`${P}/cases/1`, () => HttpResponse.json(kase(1))),
    http.get(`${P}/ci-target`, () => HttpResponse.json({ ...TARGET, configured: false })),
  );
  renderAt("/projects/42/cases/1");
  expect(await screen.findByRole("link", { name: "Configure in Settings" })).toHaveAttribute("href", "/projects/42/settings");
});
```

- [ ] **Step 3: Run the tests and check they fail.**

Run: `npx vitest run src/pages/RunFromQaVision.test.tsx`
Expected: FAIL (no "Run" button).

- [ ] **Step 4: Implement the gate.** `src/lib/useRunGate.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { getProject } from "../api/orgs";
import { CiTarget, RunRequest, getCiTarget, isActive, listRunRequests, tokenState } from "../api/runRequests";

export const RUN_POLL_MS = 5_000;
// Mirrors EDIT_ROLES in test-management's api/deps.py: who may run and stop
const RUN_ROLES = ["owner", "admin", "member"];

export type RunGate = { ok: true; target: CiTarget } | { ok: false; reason: string; toSettings: boolean };

/** The project's newest run request; polled every 5 s while the server still checks it with GitHub. */
export function useLatestRunRequest(projectId: number) {
  return useQuery({
    queryKey: ["run-requests", projectId, "latest"],
    queryFn: async (): Promise<RunRequest | null> => (await listRunRequests(projectId, { limit: 1, offset: 0 })).items[0] ?? null,
    refetchInterval: (query) => (query.state.data?.refreshing ? RUN_POLL_MS : false),
  });
}

export function useCiTarget(projectId: number) {
  return useQuery({ queryKey: ["ci-target", projectId], queryFn: () => getCiTarget(projectId) });
}

/** Whether Play may start a run, and if not the reason to show; first matching reason wins. */
export function gate(role: string | undefined, target: CiTarget, latest: RunRequest | null, now: number = Date.now()): RunGate {
  if (!RUN_ROLES.includes(role ?? "")) return { ok: false, reason: "Viewers can't run tests", toSettings: false };
  if (!target.available) return { ok: false, reason: "Running tests from QA Vision is not configured on this server", toSettings: false };
  if (!target.configured) return { ok: false, reason: "Configure in Settings", toSettings: true };
  if (tokenState(target, now) === "expired") return { ok: false, reason: "GitHub token expired", toSettings: true };
  if (latest && isActive(latest)) return { ok: false, reason: "A run is in progress", toSettings: false };
  return { ok: true, target };
}

/** Undefined while the role, the target or the newest request is still loading. */
export function useRunGate(projectId: number): RunGate | undefined {
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId) });
  const target = useCiTarget(projectId);
  const latest = useLatestRunRequest(projectId);
  if (!project.data || !target.data || latest.isPending) return undefined;
  return gate(project.data.my_role, target.data, latest.data ?? null);
}
```

- [ ] **Step 5: Implement `RunControl`.** `src/components/RunControl.tsx`:

```tsx
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Play } from "lucide-react";
import { RunSelection, createRunRequest } from "../api/runRequests";
import { useRunGate } from "../lib/useRunGate";
import ErrorBanner from "./ErrorBanner";

const SHOWN = 10;

interface Props {
  projectId: number;
  /** The cases the confirmation lists, in order. */
  cases: { number: number; title: string }[];
  selection: RunSelection;
  /** Visible text of the trigger: "Run", "Run selected (3)", "Run suite". */
  label: string;
  onStarted?: () => void;
}

/** Play: a trigger, the reason it is disabled, and an inline confirmation (no modal, DESIGN.md). */
export default function RunControl({ projectId, cases, selection, label, onStarted }: Props) {
  const gate = useRunGate(projectId);
  const qc = useQueryClient();
  const ids = useId();
  const [open, setOpen] = useState(false);
  const sending = useRef(false); // a double click must send one request, before React re-renders
  const triggerRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  const start = useMutation({
    mutationFn: () => createRunRequest(projectId, selection),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["run-requests", projectId] });
      setOpen(false);
      onStarted?.();
    },
    onSettled: () => {
      sending.current = false;
    },
  });

  useEffect(() => {
    if (open) cancelRef.current?.focus();
  }, [open]);

  function close() {
    setOpen(false);
    start.reset();
    triggerRef.current?.focus();
  }

  function confirm() {
    if (sending.current) return;
    sending.current = true;
    start.mutate();
  }

  const n = cases.length;
  const blocked = gate === undefined || !gate.ok || n === 0;
  return (
    <div className="run-control">
      <button ref={triggerRef} type="button" className="primary" disabled={blocked} onClick={() => setOpen(true)}
        aria-describedby={gate && !gate.ok ? `${ids}-why` : undefined}>
        <Play size={16} aria-hidden="true" /> {label}
      </button>
      {gate && !gate.ok && (
        <span id={`${ids}-why`} className="run-reason">
          {gate.toSettings ? <Link to={`/projects/${projectId}/settings`}>{gate.reason}</Link> : gate.reason}
        </span>
      )}
      {open && gate?.ok && (
        <div className="card run-confirm" role="dialog" aria-labelledby={`${ids}-title`}
          onKeyDown={(e) => { if (e.key === "Escape") close(); }}>
          <h3 id={`${ids}-title`}>{n === 1 ? "Run 1 test?" : `Run ${n} tests?`}</h3>
          <ul className="run-confirm-cases">
            {cases.slice(0, SHOWN).map((c) => <li key={c.number}>{`TC-${c.number} · ${c.title}`}</li>)}
          </ul>
          {n > SHOWN && <p className="muted">{`+${n - SHOWN} more`}</p>}
          <p>{`${gate.target.repo} @ ${gate.target.ref}`}</p>
          <p className="note warn-note" role="note">
            <CircleAlert size={16} aria-hidden="true" />
            <span>Tests may create real bookings in staging</span>
          </p>
          {start.error != null && <ErrorBanner error={start.error} />}
          <div className="button-row">
            <button type="button" className="primary" onClick={confirm} disabled={start.isPending}>
              {start.isPending ? "Starting…" : "Run"}
            </button>
            <button ref={cancelRef} type="button" onClick={close}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
```

`userEvent.dblClick` on the dialog's Run button. The first click switches the label to "Starting…", and `sending` swallows the second click. The test holds the element reference, so the name change does not break it.

- [ ] **Step 6: Place Play on the three pages.**
- **`CaseEditorPage.tsx`:** import `RunControl`. Right after `<h2>…</h2>`, add:

```tsx
      {c?.source_path && c.status !== "archived" && (
        <RunControl projectId={id} cases={[{ number: c.number, title: c.title }]} selection={{ case_numbers: [c.number] }} label="Run" />
      )}
```

- **`SuiteDetailPage.tsx`:** import `RunControl`. After the description paragraph, add the code below. It runs the saved list; unsaved reorders are not sent.

```tsx
      <RunControl projectId={id} cases={suite.data.cases.map((c) => ({ number: c.number, title: c.title }))}
        selection={{ suite_id: sid }} label="Run suite" />
```

- **`CasesPage.tsx`:**
  - Import `Case` from `../api/cases`, `MAX_RUN_CASES` from `../api/runRequests`, and `RunControl`.
  - Add state and helpers:

```tsx
  const [picked, setPicked] = useState<Map<number, string>>(new Map());
  const runnable = (c: Case) => c.source_path != null && c.status !== "archived";
  function toggle(c: Case) {
    setPicked((now) => {
      const next = new Map(now);
      if (next.has(c.number)) next.delete(c.number);
      else if (next.size < MAX_RUN_CASES) next.set(c.number, c.title);
      return next;
    });
  }
  function toggleAll(on: boolean, rows: Case[]) {
    setPicked((now) => {
      const next = new Map(now);
      for (const c of rows) {
        if (!on) next.delete(c.number);
        else if (next.size < MAX_RUN_CASES) next.set(c.number, c.title);
      }
      return next;
    });
  }
```

  - Inside the `data.items.length > 0` branch, compute `const pageRunnable = data.items.filter(runnable);`.
  - When `canEdit`, add a first header cell:

```tsx
<th className="select-col">
  <input type="checkbox" aria-label="Select all imported cases on this page" disabled={pageRunnable.length === 0}
    checked={pageRunnable.length > 0 && pageRunnable.every((c) => picked.has(c.number))}
    onChange={(e) => toggleAll(e.target.checked, pageRunnable)} />
</th>
```

  - When `canEdit`, add a first row cell:

```tsx
<td className="select-col">
  {runnable(c) && (
    <input type="checkbox" aria-label={`Select ${c.key} ${c.title}`} checked={picked.has(c.number)}
      disabled={!picked.has(c.number) && picked.size >= MAX_RUN_CASES} onChange={() => toggle(c)} />
  )}
</td>
```

  - Above the table card, when `canEdit && picked.size > 0`:

```tsx
<div className="run-selection" role="region" aria-label="Selected cases">
  <RunControl projectId={id} cases={[...picked].map(([number, title]) => ({ number, title }))}
    selection={{ case_numbers: [...picked.keys()] }} label={`Run selected (${picked.size})`}
    onStarted={() => setPicked(new Map())} />
  <button type="button" className="ghost" onClick={() => setPicked(new Map())}>Clear selection</button>
  {picked.size >= MAX_RUN_CASES && <span className="muted">At most 200 cases per run</span>}
</div>
```

- **CSS:** in `index.css`, add:

```css
/* Run from QA Vision: Play, the reason it is disabled, the inline confirmation and the selection bar */
.run-control { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3); margin: var(--space-3) 0; }
.run-control > button svg { vertical-align: -3px; }
.run-reason { color: var(--text-secondary); font-size: 13px; }
.run-confirm { flex-basis: 100%; max-width: 560px; margin: 0; }
.run-confirm h3 { margin-top: 0; }
.run-confirm-cases { margin: 0 0 var(--space-2); padding-left: var(--space-5); overflow-wrap: anywhere; }
.run-selection { position: sticky; bottom: 0; z-index: 1; display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); margin: var(--space-3) 0; background: var(--surface-1); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: var(--shadow-2); }
.run-selection .run-control { margin: 0; }
.select-col { width: 36px; }
.select-col input { width: 18px; height: 18px; }
@media (pointer: coarse) { .select-col input { width: 24px; height: 24px; } }
```

- [ ] **Step 7: Run the tests and the four CI steps, and check they pass.**

Run: `npx vitest run src/pages/RunFromQaVision.test.tsx`, then `npm run lint && npm run typecheck && npx vitest run && npm run build`
Expected: PASS, with pristine output. `TestManagement.test.tsx` renders imported cases as a member. If a new checkbox or Run button makes one of its queries ambiguous, narrow that query with `within(...)`. Do not change the behaviour.

- [ ] **Step 8: Commit.**

```bash
D=dashboard/src
FILES="$D/lib/useRunGate.ts $D/components/RunControl.tsx $D/pages/CaseEditorPage.tsx $D/pages/CasesPage.tsx $D/pages/SuiteDetailPage.tsx $D/pages/RunFromQaVision.test.tsx $D/index.css"
git add $FILES && git commit -m "feat(dashboard): Play from a case, a selection and a suite, with a confirmation" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

Add `dashboard/src/pages/TestManagement.test.tsx` to `FILES` only if you had to touch it.

---

### Task 9: Run panel with Stop, and the "Requested runs" tab

**Files:**
- Create: `dashboard/src/lib/runStatus.ts`
- Create: `dashboard/src/components/RunPanel.tsx`
- Create: `dashboard/src/pages/RequestedRunsPage.tsx`
- Modify: `dashboard/src/pages/CasesPage.tsx` (panel at the top)
- Modify: `dashboard/src/pages/CaseEditorPage.tsx` (panel for this case)
- Modify: `dashboard/src/pages/RunsPage.tsx` (view tabs)
- Modify: `dashboard/src/App.tsx` (route `runs/requested`)
- Modify: `dashboard/src/index.css` (panel)
- Modify: `DESIGN.md` (a new "Run from QA Vision" component section)
- Test: `dashboard/src/components/RunPanel.test.tsx`, `dashboard/src/pages/RequestedRunsPage.test.tsx`

**Interfaces:**
- Consumes:
  - Task 7's `runRequests.ts`, `useUserNames` and `ExpiryWarning`;
  - Task 8's `useLatestRunRequest`, `useCiTarget` and `RUN_POLL_MS`;
  - `listRuns` and `Run` from `api/runs.ts`, and `formatDuration` from `api/analytics.ts`.
- Produces:

```ts
// src/lib/runStatus.ts
export type RunTone = "queued" | "running" | "passed" | "failed" | "cancelled" | "error";
export const RESULTS_WAIT_MS = 5 * 60_000;
export const MATCH_SLACK_MS = 10 * 60_000;
export function describeRun(r: RunRequest, nameOf: (id: number | null) => string, now?: number): { text: string; tone: RunTone };
export function matchRun(runs: Run[], url: string | null): Run | undefined; // ci_run_url equal, ignoring case
// src/components/RunPanel.tsx (default export)
export default function RunPanel(props: { projectId: number; caseNumber?: number }): JSX.Element | null;
// src/pages/RequestedRunsPage.tsx (default export), route /projects/:projectId/runs/requested
```

- [ ] **Step 1: Invoke `ui-ux-pro-max`.** Searches: `"live status region progress polling" --domain ux`, `"stop running job confirmation" --domain ux` and `"status icon not color only" --domain ux`.

- [ ] **Step 2: Write the failing tests.** `src/components/RunPanel.test.tsx`:

```tsx
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import { RunRequest } from "../api/runRequests";
import RunPanel from "./RunPanel";

const P = "/api/v1/projects/42";
const member = (user_id: number, email: string) => ({ id: user_id, organization_id: 1, user_id, email, role: "member",
  status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: null });
const req = (extra: Partial<RunRequest> = {}): RunRequest => ({
  id: 9, requested_by: 7, requested_at: new Date(Date.now() - 65_000).toISOString(),
  selection: [{ case_number: 1, path: "tests/features/a.feature", name: "A" }, { case_number: 2, path: "tests/features/a.feature", name: "B" }],
  case_count: 2, suite_id: null, status: "running", conclusion: null, github_run_id: 501,
  github_run_url: "https://github.com/Acme/OBT/actions/runs/501", stopped_by: null, stopped_at: null, error: null,
  checked_at: new Date().toISOString(), refreshing: true, ...extra,
});

function show(get: () => RunRequest[], role = "member", caseNumber?: number) {
  setAccessToken("acc");
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, name: "Web", organization_id: 1, my_role: role })),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([member(7, "ana@example.com"), member(8, "rui@example.com")])),
    http.get(`${P}/run-requests`, () => { const items = get(); return HttpResponse.json({ total: items.length, items }); }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><RunPanel projectId={42} caseNumber={caseNumber} /></MemoryRouter></QueryClientProvider>);
}

const panel = () => screen.findByRole("status", { name: "Run from QA Vision" });

test.each([
  ["queued", req({ status: "queued" }), /^Queued$/],
  ["queued after a 204 dispatch (no run yet)", req({ status: "queued", github_run_id: null, github_run_url: null }), /^Queued$/],
  ["running", req(), /^Running · 2 tests · started by ana@example\.com · 1m 0[5-9]s$/],
  ["passed", req({ status: "completed", conclusion: "success", refreshing: false }), /^Passed$/],
  ["failed", req({ status: "completed", conclusion: "failure", refreshing: false }), /^Failed$/],
  ["cancelled on GitHub", req({ status: "cancelled", conclusion: "cancelled", refreshing: false }), /^Cancelled$/],
  ["stopped", req({ status: "cancelled", conclusion: "cancelled", stopped_by: 8, refreshing: false }), /^Stopped by rui@example\.com$/],
  ["not started", req({ status: "failed_to_start", error: "The workflow did not start", github_run_id: null, github_run_url: null, refreshing: false }),
    /^Didn't start: The workflow did not start$/],
])("the panel reads %s", async (_, r, text) => {
  show(() => [r]);
  expect(await within(await panel()).findByText(text)).toBeInTheDocument();
});

test("View in GitHub opens the run", async () => {
  show(() => [req()]);
  expect(await within(await panel()).findByRole("link", { name: /view in github/i }))
    .toHaveAttribute("href", "https://github.com/Acme/OBT/actions/runs/501");
});

test("Stop asks first, then shows Stopping…", async () => {
  let stopped = false;
  let current = req();
  server.use(http.post(`${P}/run-requests/9/stop`, () => {
    stopped = true;
    current = req({ status: "cancelling", stopped_by: 7 });
    return HttpResponse.json(current);
  }));
  show(() => [current]);
  await userEvent.click(await screen.findByRole("button", { name: "Stop the run" }));
  expect(screen.getByText("Stop this run?")).toBeInTheDocument();
  expect(stopped).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "Stop run" }));
  expect(await screen.findByText("Stopping…")).toBeInTheDocument();
  expect(stopped).toBe(true);
});

test("viewers see the state but no Stop", async () => {
  show(() => [req()], "viewer");
  await within(await panel()).findByText(/^Running/);
  expect(screen.queryByRole("button", { name: "Stop the run" })).not.toBeInTheDocument();
});

test("the panel polls every 5 s while the request is active and stops when it ends", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    let calls = 0;
    show(() => { calls += 1; return [calls === 1 ? req() : req({ status: "completed", conclusion: "failure", refreshing: false })]; });
    expect(await screen.findByText(/^Running/)).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(await screen.findByText("Failed")).toBeInTheDocument();
    const after = calls;
    await act(() => vi.advanceTimersByTimeAsync(15_000));
    expect(calls).toBe(after);
  } finally {
    vi.useRealTimers();
  }
});

test("a finished run links to its results, matching the CI URL whatever its case", async () => {
  server.use(http.get(`${P}/runs`, () => HttpResponse.json([
    { id: 76, ci_run_url: "https://github.com/acme/obt/actions/runs/500" },
    { id: 77, ci_run_url: "https://github.com/acme/obt/actions/runs/501" }])));
  show(() => [req({ status: "completed", conclusion: "success", refreshing: false })]);
  expect(await screen.findByRole("link", { name: "Open the results (run #77)" })).toHaveAttribute("href", "/projects/42/runs/77");
});

test("until results arrive it waits; after 5 minutes it says they were not received", async () => {
  show(() => [req({ status: "completed", conclusion: "success", refreshing: false })]);
  expect(await screen.findByText("Waiting for results…")).toBeInTheDocument();
});

test("after 5 minutes without results it points at the upload step", async () => {
  show(() => [req({ status: "completed", conclusion: "success", refreshing: false,
    checked_at: new Date(Date.now() - 6 * 60_000).toISOString() })]);
  expect(await screen.findByText("Results not received: check the QA Vision upload step")).toBeInTheDocument();
});

test("on a case detail the panel shows only while that case is in the active request", async () => {
  let asked = false;
  show(() => { asked = true; return [req()]; }, "member", 3);
  await waitFor(() => expect(asked).toBe(true));
  expect(screen.queryByRole("status", { name: "Run from QA Vision" })).not.toBeInTheDocument();
});

test("on a case detail of a selected case the panel shows", async () => {
  show(() => [req()], "member", 2);
  expect(await panel()).toBeInTheDocument();
});

test("owners see the expiry warning above the panel; members do not", async () => {
  const soon = new Date(Date.now() + 3 * 86_400_000).toISOString();
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ available: true, configured: true, provider: "github",
    repo: "acme/obt", workflow: "qa-vision-run.yml", ref: "main", token_last4: "a1b2", token_expires_at: soon,
    updated_at: null, last_change: null })));
  show(() => [], "owner");
  expect(await screen.findByText(/^The GitHub token expires on .+\. Replace it in Settings$/)).toBeInTheDocument();
});
```

The fourth case in `test.each`, "failed", must find exactly `Failed`. The status column of the Requested runs page uses the same `describeRun`.

`src/pages/RequestedRunsPage.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import RequestedRunsPage from "./RequestedRunsPage";

const P = "/api/v1/projects/42";
const member = (user_id: number, email: string) => ({ id: user_id, organization_id: 1, user_id, email, role: "member",
  status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: null });
const base = { requested_at: "2026-10-07T10:00:00Z", suite_id: null, conclusion: null, github_run_id: null,
  github_run_url: null, stopped_by: null, stopped_at: null, error: null, checked_at: "2026-10-07T10:05:00Z", refreshing: false };

function renderPage(items: object[], runs: object[] = []) {
  setAccessToken("acc");
  server.use(
    http.get(P, () => HttpResponse.json({ id: 42, name: "Web", organization_id: 1, my_role: "member" })),
    http.get("/api/v1/organizations/1/members", () => HttpResponse.json([member(7, "ana@example.com"), member(8, "rui@example.com")])),
    http.get(`${P}/run-requests`, () => HttpResponse.json({ total: items.length, items })),
    http.get(`${P}/runs`, () => HttpResponse.json(runs)),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/projects/42/runs/requested"]}>
        <Routes><Route path="/projects/:projectId/runs/requested" element={<RequestedRunsPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("lists who requested, how many cases, the status, who stopped it, and the links", async () => {
  renderPage([
    { ...base, id: 10, requested_by: 7, selection: [{ case_number: 1, path: "a", name: "A" }, { case_number: 2, path: "a", name: "B" }],
      case_count: 2, status: "completed", conclusion: "success", github_run_id: 501,
      github_run_url: "https://github.com/acme/obt/actions/runs/501" },
    { ...base, id: 9, requested_by: 7, selection: [{ case_number: 1, path: "a", name: "A" }], case_count: 1,
      status: "cancelled", stopped_by: 8, stopped_at: "2026-10-07T10:01:00Z" },
  ], [{ id: 77, ci_run_url: "https://github.com/ACME/obt/actions/runs/501" }]);
  const rows = await screen.findAllByRole("row");
  expect(rows).toHaveLength(3);
  const first = within(rows[1]);
  expect(await first.findByText("ana@example.com")).toBeInTheDocument();
  expect(first.getByText("2")).toBeInTheDocument();
  expect(first.getByText("Passed")).toBeInTheDocument();
  expect(first.getByRole("link", { name: /github/i })).toHaveAttribute("href", "https://github.com/acme/obt/actions/runs/501");
  expect(await first.findByRole("link", { name: "Run #77" })).toHaveAttribute("href", "/projects/42/runs/77");
  expect(within(rows[2]).getByText("rui@example.com")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute("href", "/projects/42/runs");
});

test("with no requests yet it says so", async () => {
  renderPage([]);
  expect(await screen.findByText("No runs requested from QA Vision yet.")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run the tests and check they fail.**

Run: `npx vitest run src/components/RunPanel.test.tsx src/pages/RequestedRunsPage.test.tsx`
Expected: FAIL (imports do not resolve).

- [ ] **Step 4: Implement `runStatus.ts`.**

```ts
import { formatDuration } from "../api/analytics";
import { RunRequest } from "../api/runRequests";
import { Run } from "../api/runs";

export type RunTone = "queued" | "running" | "passed" | "failed" | "cancelled" | "error";
export const RESULTS_WAIT_MS = 5 * 60_000;
/** Results are looked up from this long before the request, so clock skew never hides them. */
export const MATCH_SLACK_MS = 10 * 60_000;

/** What a run request's state reads as, in the panel and in the Requested runs tab. */
export function describeRun(r: RunRequest, nameOf: (id: number | null) => string, now: number = Date.now()): { text: string; tone: RunTone } {
  switch (r.status) {
    case "queued":
      return { text: "Queued", tone: "queued" };
    case "running": {
      const tests = r.case_count === 1 ? "1 test" : `${r.case_count} tests`;
      const elapsed = formatDuration(Math.max(0, now - Date.parse(r.requested_at)));
      return { text: `Running · ${tests} · started by ${nameOf(r.requested_by)} · ${elapsed}`, tone: "running" };
    }
    case "cancelling":
      return { text: "Stopping…", tone: "cancelled" };
    case "cancelled":
      return { text: r.stopped_by != null ? `Stopped by ${nameOf(r.stopped_by)}` : "Cancelled", tone: "cancelled" };
    case "failed_to_start":
      return { text: `Didn't start: ${r.error ?? "unknown error"}`, tone: "error" };
    case "completed":
      return r.conclusion === "success" ? { text: "Passed", tone: "passed" } : { text: "Failed", tone: "failed" };
  }
}

/** The QA Vision test run this request's GitHub run uploaded: same CI URL, ignoring case
 *  (GitHub may return owner/repo with different capitals). */
export function matchRun(runs: Run[], url: string | null): Run | undefined {
  if (!url) return undefined;
  const wanted = url.toLowerCase();
  return runs.find((r) => r.ci_run_url?.toLowerCase() === wanted);
}
```

- [ ] **Step 5: Implement `RunPanel.tsx`.**

```tsx
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, CircleSlash, CircleX, Clock, ExternalLink, LoaderCircle } from "lucide-react";
import { getProject } from "../api/orgs";
import { listRuns } from "../api/runs";
import { isActive, stopRunRequest } from "../api/runRequests";
import { useCiTarget, useLatestRunRequest } from "../lib/useRunGate";
import { MATCH_SLACK_MS, RESULTS_WAIT_MS, RunTone, describeRun, matchRun } from "../lib/runStatus";
import { useUserNames } from "../lib/useUserNames";
import { ExpiryWarning } from "./CiTargetCard";
import ConfirmButton from "./ConfirmButton";
import ErrorBanner from "./ErrorBanner";

const RECENT_MS = 60 * 60_000;
const RESULTS_POLL_MS = 10_000;
const MANAGE_ROLES = ["owner", "admin"];
const RUN_ROLES = ["owner", "admin", "member"];
const ICONS: Record<RunTone, typeof Clock> = {
  queued: Clock, running: LoaderCircle, passed: CheckCircle2, failed: CircleX, cancelled: CircleSlash, error: CircleAlert,
};

interface Props {
  projectId: number;
  /** On a case detail: show only while this case is in the active request. */
  caseNumber?: number;
}

/** The newest run requested from QA Vision: its state, View in GitHub, Stop, then its results. */
export default function RunPanel({ projectId, caseNumber }: Props) {
  const qc = useQueryClient();
  const latest = useLatestRunRequest(projectId);
  const target = useCiTarget(projectId);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId) });
  const nameOf = useUserNames(projectId);
  const r = latest.data ?? null;
  const ended = r != null && !isActive(r);
  const finishedAt = r?.checked_at ? Date.parse(r.checked_at) : null;
  const waitedTooLong = finishedAt !== null && Date.now() - finishedAt > RESULTS_WAIT_MS;
  const results = useQuery({
    queryKey: ["run-requests", projectId, "results", r?.id],
    queryFn: async () => {
      const since = new Date(Date.parse(r!.requested_at) - MATCH_SLACK_MS).toISOString();
      return matchRun(await listRuns(projectId, { limit: 20, offset: 0, since }), r!.github_run_url) ?? null;
    },
    enabled: ended && r.github_run_url != null && r.status !== "failed_to_start",
    refetchInterval: (q) => (q.state.data || waitedTooLong ? false : RESULTS_POLL_MS),
  });
  const stop = useMutation({
    mutationFn: () => stopRunRequest(projectId, r!.id),
    onSuccess: (updated) => qc.setQueryData(["run-requests", projectId, "latest"], updated),
  });

  const role = project.data?.my_role ?? "";
  const warning = MANAGE_ROLES.includes(role) && target.data ? <ExpiryWarning target={target.data} /> : null;
  const live = r != null && (isActive(r) || r.refreshing);
  const visible = r != null && (caseNumber === undefined
    ? live || Date.now() - Date.parse(r.requested_at) < RECENT_MS
    : live && r.selection.some((s) => s.case_number === caseNumber));
  if (!visible || r == null) return caseNumber === undefined ? warning : null;

  const { text, tone } = describeRun(r, nameOf);
  const Icon = ICONS[tone];
  const canStop = RUN_ROLES.includes(role) && (r.status === "queued" || r.status === "running");
  return (
    <>
      {warning}
      <section className={`card run-panel run-tone-${tone}`} role="status" aria-label="Run from QA Vision">
        <p className="run-panel-state">
          <Icon size={18} aria-hidden="true" />
          <span>{text}</span>
        </p>
        <div className="run-panel-actions">
          {r.github_run_url && (
            <a href={r.github_run_url} target="_blank" rel="noopener noreferrer" className="link-arrow">
              View in GitHub <ExternalLink size={13} aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          )}
          {canStop && (
            <ConfirmButton label="Stop" ariaLabel="Stop the run" question="Stop this run?" confirmLabel="Stop run"
              onConfirm={() => stop.mutate()} disabled={stop.isPending} />
          )}
        </div>
        {ended && r.github_run_url && r.status !== "failed_to_start" && (
          results.data ? (
            <p><Link to={`/projects/${projectId}/runs/${results.data.id}`}>{`Open the results (run #${results.data.id})`}</Link></p>
          ) : waitedTooLong ? (
            <p className="muted">Results not received: check the QA Vision upload step</p>
          ) : (
            <p className="muted">Waiting for results…</p>
          )
        )}
        {stop.error != null && <ErrorBanner error={stop.error} />}
      </section>
    </>
  );
}
```

If the linter rejects the non-null assertions (`r!`), capture `const rid = r?.id` and `const requestedAt = r?.requested_at` before the queries, and guard inside `queryFn` with an early `return null`.

- [ ] **Step 6: Implement `RequestedRunsPage.tsx`, the tab and the route.**

```tsx
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { listRunRequests } from "../api/runRequests";
import { listRuns } from "../api/runs";
import ErrorBanner from "../components/ErrorBanner";
import { MATCH_SLACK_MS, describeRun, matchRun } from "../lib/runStatus";
import { RUN_POLL_MS } from "../lib/useRunGate";
import { useUserNames } from "../lib/useUserNames";

const PAGE = 50;

/** Runs → Requested runs: every Play, who pressed it, how it ended, and where its results are. */
export default function RequestedRunsPage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const [offset, setOffset] = useState(0);
  const nameOf = useUserNames(id);
  const list = useQuery({
    queryKey: ["run-requests", id, "page", offset],
    queryFn: () => listRunRequests(id, { limit: PAGE, offset }),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.refreshing) ? RUN_POLL_MS : false),
  });
  const items = list.data?.items ?? [];
  const oldest = items.length > 0 ? Math.min(...items.map((r) => Date.parse(r.requested_at))) : null;
  const runs = useQuery({
    queryKey: ["run-requests", id, "page-results", offset, oldest],
    queryFn: () => listRuns(id, { limit: 100, offset: 0, since: new Date((oldest ?? 0) - MATCH_SLACK_MS).toISOString() }),
    enabled: oldest !== null && items.some((r) => r.github_run_url),
  });

  return (
    <section>
      <h2 className="sr-only">Requested runs</h2>
      <div className="view-tabs">
        <Link to=".." relative="path">Runs</Link>
        <span aria-current="page">Requested runs</span>
      </div>
      {list.error != null && <ErrorBanner error={list.error} onRetry={() => list.refetch()} />}
      {list.isPending && <p className="muted">Loading requested runs…</p>}
      {list.data && list.data.total === 0 && <p className="muted">No runs requested from QA Vision yet.</p>}
      {items.length > 0 && (
        <div className="card" tabIndex={0} role="region" aria-label="Requested runs">
          <table className="data">
            <thead>
              <tr>
                <th>Date</th><th>Requested by</th><th>Cases</th><th>Status</th>
                <th className="hide-narrow">Stopped by</th><th>Links</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const result = matchRun(runs.data ?? [], r.github_run_url);
                return (
                  <tr key={r.id}>
                    <td>{new Date(r.requested_at).toLocaleString()}</td>
                    <td>{nameOf(r.requested_by)}</td>
                    <td className="num">{r.case_count}</td>
                    <td>{describeRun(r, nameOf).text}</td>
                    <td className="hide-narrow">{r.stopped_by != null ? nameOf(r.stopped_by) : "—"}</td>
                    <td className="row-actions">
                      {r.github_run_url && (
                        <a href={r.github_run_url} target="_blank" rel="noopener noreferrer" className="link-arrow">
                          GitHub <ExternalLink size={13} aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span>
                        </a>
                      )}
                      {result && <Link to={`/projects/${id}/runs/${result.id}`}>{`Run #${result.id}`}</Link>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="filters">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
            <span className="muted">{offset + 1}–{offset + items.length} of {list.data?.total}</span>
            <button disabled={offset + PAGE >= (list.data?.total ?? 0)} onClick={() => setOffset(offset + PAGE)}>Next</button>
          </div>
        </div>
      )}
    </section>
  );
}
```

`App.tsx`: add `<Route path="runs/requested" element={<RequestedRunsPage />} />` before `runs/:runId`, and import it.

`RunsPage.tsx`: right after `<h2 className="sr-only">Runs</h2>`, add:

```tsx
      <div className="view-tabs">
        <span aria-current="page">Runs</span>
        <Link to="requested">Requested runs</Link>
      </div>
```

- **`CasesPage.tsx`:** import `RunPanel`, and render `<RunPanel projectId={id} />` right after the `view-tabs` div.
- **`CaseEditorPage.tsx`:** import `RunPanel`, and render `{c && <RunPanel projectId={id} caseNumber={c.number} />}` right after the Run control.

CSS, in `index.css`:

```css
/* Run from QA Vision: the run panel (a role="status" card) */
.run-panel { display: grid; gap: var(--space-2); margin-bottom: var(--space-4); }
.run-panel-state { display: flex; align-items: center; gap: var(--space-2); margin: 0; font-weight: 600; }
.run-panel-state svg { flex-shrink: 0; color: var(--text-secondary); }
.run-panel-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); }
.run-tone-running .run-panel-state svg { color: var(--accent); }
.run-tone-passed .run-panel-state svg { color: var(--status-passed); }
.run-tone-failed .run-panel-state svg, .run-tone-error .run-panel-state svg { color: var(--status-failed); }
@media (prefers-reduced-motion: no-preference) {
  .run-tone-running .run-panel-state svg { animation: run-spin 1.2s linear infinite; }
}
@keyframes run-spin { to { transform: rotate(360deg); } }
```

**`DESIGN.md`:** add `### Run from QA Vision` under Components, after "Run Strip". Cover:
- **Play:** a Primary button with the Play icon ("Run", "Run selected (n)", "Run suite"). When disabled, the reason sits beside it in Graphite text, linked when Settings can fix it.
- **Confirmation:** an inline, non-modal card with `role="dialog"` that lists up to 10 cases then "+n more", `repo @ branch`, and the amber `.warn-note` "Tests may create real bookings in staging". Focus goes to Cancel, Escape backs out, and Run reads "Starting…" and ignores a second click.
- **Selection bar:** sticky at the bottom of the list, with checkboxes on imported rows for editors only. A 200-case cap disables the remaining boxes.
- **Run panel:** a card with `role="status"`. It has one state line with an 18px lucide icon whose shape differs per state (clock, spinning loader, check, cross, slash, alert), with colours from tokens. It has "View in GitHub". Stop uses the Destructive Confirmation pattern ("Stop this run?" then "Stop run"), then "Stopping…", then "Stopped by <name>". The results line says "Waiting for results…", or links the results, or after 5 minutes "Results not received: check the QA Vision upload step".
- **Token expiry:** the amber `.warn-note` for owners and admins, from 14 days before expiry.
- **Requested runs:** a tab beside Runs.

- [ ] **Step 7: Run the tests and the four CI steps, and check they pass.**

Run: `npx vitest run src/components/RunPanel.test.tsx src/pages/RequestedRunsPage.test.tsx`, then `npm run lint && npm run typecheck && npx vitest run && npm run build`
Expected: PASS, with pristine output. If the fake-timer polling test is flaky in this vitest version, replace the two `advanceTimersByTimeAsync` calls with real waiting. Use `await screen.findByText("Failed", undefined, { timeout: 7000 })`, then `await new Promise((r) => setTimeout(r, 6000))` before the final count. Keep the same assertions.

- [ ] **Step 8: Commit.**

```bash
D=dashboard/src
FILES="$D/lib/runStatus.ts $D/components/RunPanel.tsx $D/components/RunPanel.test.tsx $D/pages/RequestedRunsPage.tsx $D/pages/RequestedRunsPage.test.tsx $D/pages/CasesPage.tsx $D/pages/CaseEditorPage.tsx $D/pages/RunsPage.tsx $D/App.tsx $D/index.css DESIGN.md"
git add $FILES && git commit -m "feat(dashboard): run panel with Stop, and the Requested runs tab" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

---

### Task 10: The `qa-vision-run` workflow template, its script, the help block, and TODO

**Files:**
- Create: `templates/github/qa-vision-run.yml`
- Create: `templates/github/qa-vision-run.mjs`
- Create: `templates/github/qa-vision-run.test.mjs`
- Create: `dashboard/src/templates/qa-vision-run.yml.txt` and `dashboard/src/templates/qa-vision-run.mjs.txt` (byte-identical copies)
- Create: `dashboard/src/templates/templates.test.ts` (drift)
- Modify: `dashboard/src/components/CiTargetCard.tsx` (help block)
- Modify: `dashboard/src/components/CiTargetCard.test.tsx` (help test)
- Modify: `.github/workflows/ci.yml` (dashboard job: a template test step)
- Modify: `TODO.md` (section B)

**Interfaces:**
- Consumes: the dispatch inputs from Task 4: `paths` (a JSON array string), `names` (a JSON array string) and `request_id`. Also Task 7's `CiTargetCard`.
- Produces, from `templates/github/qa-vision-run.mjs`:

```js
export function parsePaths(raw: string | undefined): string[];   // throws unless under tests/features/, ending .feature, without control or reserved characters or ".."
export function parseNames(raw: string | undefined): string[];   // throws unless a non-empty JSON array of non-empty strings
export function namePattern(name: string): string;               // "^" + escaped name with <placeholder> -> ".*" + "$"
export function cucumberArgs(paths: string[], names: string[]): string[];
export function countScenarios(report: unknown): number;
```

The user copies `qa-vision-run.yml` into the OBT repository's `.github/workflows/` and `qa-vision-run.mjs` into `.github/scripts/`. **This task does not touch the OBT repository.**

- [ ] **Step 1: Invoke `ui-ux-pro-max`** for the help block. Search: `"setup instructions code block copy" --domain ux`.

- [ ] **Step 2: Write the failing script tests.** `templates/github/qa-vision-run.test.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { countScenarios, cucumberArgs, namePattern, parseNames, parsePaths } from "./qa-vision-run.mjs";

const matches = (name, actual) => new RegExp(namePattern(name)).test(actual);

test("regex characters, quotes and dollars in a name match only that name", () => {
  const name = `Pay with a "voucher" (50% off) $5 [promo] *now*? a+b|c \\ d. ^x {2} it's`;
  assert.ok(matches(name, name));
  assert.ok(!matches(name, `${name} again`));
  assert.ok(!matches(name, `X${name}`));
  assert.ok(!matches("Pay.by card", "Pay by card"));
  assert.ok(!matches("a+b", "aab"));
});

test("an outline's placeholders match the example values cucumber-js puts in", () => {
  assert.equal(namePattern("Book <city> flight"), "^Book .* flight$");
  assert.ok(matches("Book <city> flight", "Book Rome flight"));
  assert.ok(!matches("Book <city> flight", "Book Rome train"));
  assert.ok(matches("<carrier> flights are flagged as eligible for the traveler's unused ticket",
    "TAP Air Portugal (TP) flights are flagged as eligible for the traveler's unused ticket"));
  assert.ok(matches("Price <a.b> (<x|y>)", "Price 1.5 (yes)"));
});

test("paths must be .feature files under tests/features, never with ..", () => {
  assert.deepEqual(
    parsePaths('["tests/features/a.feature","tests/features/a.feature","tests/features/b c.feature","tests/features/x_+_y (1).feature"]'),
    ["tests/features/a.feature", "tests/features/b c.feature", "tests/features/x_+_y (1).feature"],
  );
  for (const bad of ['["../x.feature"]', '["tests/features/../../etc/x.feature"]', '["tests/features/a.js"]',
    '["tests/features/a.feature; rm -rf /"]', '["tests/features/a\\b.feature"]', '["tests/features/a\\nb.feature"]', '"tests/features/a.feature"',
    "[]", "not json", undefined]) {
    assert.throws(() => parsePaths(bad), undefined, String(bad));
  }
});

test("names must be a non-empty JSON array of non-empty strings", () => {
  assert.deepEqual(parseNames('["a", "b <c>"]'), ["a", "b <c>"]);
  for (const bad of ["[]", '[""]', "[1]", '{"a":1}', "nope", undefined]) assert.throws(() => parseNames(bad));
});

test("cucumber-js gets one --name per scenario as an argument array, with workers 1 and retries 0", () => {
  assert.deepEqual(cucumberArgs(["tests/features/a.feature"], ['say "hi"', "x"]), [
    "cucumber-js", "tests/features/a.feature", "--name", '^say "hi"$', "--name", "^x$",
    "--profile", "ci", "--format", "html:test-results/cucumber-report.html", "--parallel", "1", "--retry", "0",
  ]);
});

test("scenarios are counted from the cucumber JSON report, backgrounds left out", () => {
  assert.equal(countScenarios([{ elements: [{ type: "background" }, { type: "scenario" }] }, { elements: [{ type: "scenario" }] }]), 2);
  assert.equal(countScenarios([]), 0);
  assert.equal(countScenarios({}), 0);
});
```

Run: `node --test templates/github/qa-vision-run.test.mjs`
Expected: FAIL (`Cannot find module './qa-vision-run.mjs'`).

- [ ] **Step 3: Write the script.** `templates/github/qa-vision-run.mjs`:

```js
// QA Vision: run the scenarios a QA Vision Play selected. qa-vision-run.yml calls this.
// Copy to .github/scripts/qa-vision-run.mjs in the test repository.
//
// The inputs arrive only through environment variables (QAV_PATHS, QAV_NAMES), never through ${{ }}
// inside run:, and cucumber-js is started with an argument array, never through a shell: a scenario
// name is data and can never become a command.
import { spawn } from "node:child_process";
import { appendFileSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

// Arguments go to cucumber-js as an array, never through a shell, so only path traversal,
// control characters and characters a file name cannot hold are refused (OBT has names with + and spaces).
const FEATURE_PATH = /^tests\/features\/[^\u0000-\u001f\\:*?"<>|]+\.feature$/;
const PLACEHOLDER = /<[^<>]+>/g;
const REPORT = "test-results/cucumber-report.json";
const NO_MATCH =
  "No scenario matched this QA Vision selection. A scenario was probably renamed or moved since the last " +
  "import: re-import the .feature files in QA Vision, then run it again.";

function jsonArrayOfStrings(raw, variable) {
  let value;
  try {
    value = JSON.parse(raw ?? "");
  } catch {
    throw new Error(`${variable} is not JSON`);
  }
  if (!Array.isArray(value) || value.length === 0 || !value.every((item) => typeof item === "string" && item.length > 0)) {
    throw new Error(`${variable} must be a non-empty JSON array of non-empty strings`);
  }
  return value;
}

/** The selected .feature files, once each: only under tests/features, never with "..". */
export function parsePaths(raw) {
  const paths = jsonArrayOfStrings(raw, "QAV_PATHS");
  for (const path of paths) {
    if (!FEATURE_PATH.test(path) || path.split("/").includes("..")) {
      throw new Error(`path not allowed: ${JSON.stringify(path)}`);
    }
  }
  return [...new Set(paths)];
}

export function parseNames(raw) {
  return jsonArrayOfStrings(raw, "QAV_NAMES");
}

/** A scenario name as a cucumber-js --name pattern: the whole name, literally, except that each
 *  Scenario Outline <placeholder> matches the example value cucumber-js puts in its place. */
export function namePattern(name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return `^${escaped.replace(PLACEHOLDER, ".*")}$`;
}

export function cucumberArgs(paths, names) {
  return [
    "cucumber-js",
    ...paths,
    ...names.flatMap((name) => ["--name", namePattern(name)]),
    "--profile", "ci",
    "--format", "html:test-results/cucumber-report.html",
    "--parallel", "1",
    "--retry", "0",
  ];
}

/** Scenarios in a cucumber-js JSON report (a Background is not a scenario). */
export function countScenarios(report) {
  if (!Array.isArray(report)) return 0;
  return report.reduce((total, feature) => {
    const elements = Array.isArray(feature?.elements) ? feature.elements : [];
    return total + elements.filter((element) => element?.type !== "background").length;
  }, 0);
}

function run(args) {
  return new Promise((resolve) => {
    const child = spawn("npx", args, { stdio: "inherit", shell: false });
    child.on("error", () => resolve(1));
    child.on("close", (code) => resolve(code ?? 1));
  });
}

async function main() {
  const paths = parsePaths(process.env.QAV_PATHS);
  const names = parseNames(process.env.QAV_NAMES);
  const code = await run(cucumberArgs(paths, names));
  let report = [];
  try {
    report = JSON.parse(readFileSync(REPORT, "utf8"));
  } catch {
    // no report: cucumber-js stopped before running anything, and its own output says why
  }
  if (countScenarios(report) === 0) {
    console.log(`::warning title=QA Vision::${NO_MATCH}`);
    if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `### QA Vision\n\n${NO_MATCH}\n`);
  }
  process.exitCode = code;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.log(`::error title=QA Vision::${error.message}`);
    process.exitCode = 1;
  });
}
```

Run: `node --test templates/github/qa-vision-run.test.mjs`
Expected: PASS (6 tests).

- [ ] **Step 4: Write the workflow.** `templates/github/qa-vision-run.yml`:

```yaml
# QA Vision: run selected scenarios on demand (QA-Vision-Platform docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md).
# Copy to .github/workflows/qa-vision-run.yml on the repository's DEFAULT branch (GitHub dispatches only
# workflows found there) and qa-vision-run.mjs to .github/scripts/qa-vision-run.mjs.
# Needs the repository secret QAV_API_KEY and the repository variable QAV_URL; the ENV secret feeds
# ./.github/actions/setup-test-env as in the other suites.
name: QA Vision run
run-name: "QA Vision #${{ inputs.request_id }}"

on:
  workflow_dispatch:
    inputs:
      paths:
        description: JSON array of .feature paths (set by QA Vision)
        required: true
        type: string
      names:
        description: JSON array of scenario names (set by QA Vision)
        required: true
        type: string
      request_id:
        description: QA Vision run request id
        required: true
        type: string

permissions:
  contents: read

jobs:
  run:
    name: QA Vision run
    # Only the branch configured in QA Vision (Project Settings › Run from QA Vision)
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-24.04
    timeout-minutes: 120
    concurrency:
      group: qa-vision-run
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5

      - uses: ./.github/actions/setup-test-env
        with:
          env-file-content: ${{ secrets.ENV }}

      - name: Run the selected scenarios
        run: node .github/scripts/qa-vision-run.mjs
        env:
          CI: "true"
          QAV_PATHS: ${{ inputs.paths }}
          QAV_NAMES: ${{ inputs.names }}

      - name: Upload results to QA Vision
        if: always()
        uses: carneiru/QA-Vision-Platform/collector-action@collector-v0.3.0
        with:
          url: ${{ vars.QAV_URL }}
          patterns: test-results/cucumber-report.json
        env:
          QAV_API_KEY: ${{ secrets.QAV_API_KEY }}

      - name: Upload the Cucumber HTML report
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: qa-vision-run-${{ inputs.request_id }}-report
          path: test-results/cucumber-report.html
          if-no-files-found: ignore
```

- [ ] **Step 5: Make the dashboard copies, and write the failing dashboard tests.** Copy both files byte for byte:

```bash
cp templates/github/qa-vision-run.yml dashboard/src/templates/qa-vision-run.yml.txt
cp templates/github/qa-vision-run.mjs dashboard/src/templates/qa-vision-run.mjs.txt
```

`dashboard/src/templates/templates.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import workflowYaml from "./qa-vision-run.yml.txt?raw";
import runnerScript from "./qa-vision-run.mjs.txt?raw";

// The dashboard's Docker build sees only dashboard/, so the help block reads these copies; they must
// stay identical to the templates people copy from the repository.
const repoFile = (name: string) =>
  readFileSync(fileURLToPath(new URL(`../../../templates/github/${name}`, import.meta.url)), "utf8");

test("the dashboard's copies match templates/github", () => {
  expect(workflowYaml).toBe(repoFile("qa-vision-run.yml"));
  expect(runnerScript).toBe(repoFile("qa-vision-run.mjs"));
});
```

Append to `dashboard/src/components/CiTargetCard.test.tsx`:

```tsx
test("the help block holds the workflow for the configured branch and the script, ready to copy", async () => {
  server.use(http.get(`${P}/ci-target`, () => HttpResponse.json({ ...CONNECTED, ref: "release" })));
  renderCard();
  await userEvent.click(await screen.findByText("How to set it up"));
  const workflow = screen.getByLabelText("qa-vision-run.yml");
  expect(workflow).toHaveTextContent("if: github.ref == 'refs/heads/release'");
  expect(workflow).toHaveTextContent('run-name: "QA Vision #${{ inputs.request_id }}"');
  expect(screen.getByLabelText("qa-vision-run.mjs")).toHaveTextContent('"--retry", "0"');
  expect(screen.getByText(/Actions: Read and write/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy qa-vision-run.yml" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy qa-vision-run.mjs" })).toBeInTheDocument();
});
```

Run: `npx vitest run src/templates/templates.test.ts src/components/CiTargetCard.test.tsx`
Expected: the drift test passes, because the files were just copied. The help test FAILS (no "How to set it up").

- [ ] **Step 6: Add the help block.** In `CiTargetCard.tsx`:

```tsx
import workflowYaml from "../templates/qa-vision-run.yml.txt?raw";
import runnerScript from "../templates/qa-vision-run.mjs.txt?raw";

/** The template, guarded to the branch configured here. */
function workflowFor(ref: string | null): string {
  return ref ? workflowYaml.replace("refs/heads/main", `refs/heads/${ref}`) : workflowYaml;
}

function CopyBlock({ name, code }: { name: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <>
      <pre className="code-block" tabIndex={0} aria-label={name}><code>{code}</code></pre>
      <button type="button" aria-label={`Copy ${name}`} onClick={async () => {
        try {
          await navigator.clipboard.writeText(code);
          setCopied(true);
        } catch {
          setCopied(false); // clipboard blocked: the text stays selectable
        }
      }}>
        {copied ? "Copied" : "Copy"}
      </button>
    </>
  );
}
```

Render this inside the `data?.available` fragment, after the Disconnect control:

```tsx
          <details className="run-help">
            <summary>How to set it up</summary>
            <ol>
              <li>
                On GitHub, create a <strong>fine-grained personal access token</strong> (Settings › Developer settings ›
                Fine-grained tokens): repository access <strong>only {data.repo ?? "this repository"}</strong>, permission{" "}
                <strong>Actions: Read and write</strong>. Paste it in Token above.
              </li>
              <li>
                Add this workflow as <code>.github/workflows/qa-vision-run.yml</code> on the repository's{" "}
                <strong>default branch</strong> (GitHub only dispatches workflows found there):
                <CopyBlock name="qa-vision-run.yml" code={workflowFor(data.ref)} />
              </li>
              <li>
                Add the script it runs as <code>.github/scripts/qa-vision-run.mjs</code>:
                <CopyBlock name="qa-vision-run.mjs" code={runnerScript} />
              </li>
              <li>
                In the repository's Settings › Secrets and variables › Actions, add the secret <code>QAV_API_KEY</code>{" "}
                (a project API key from this page) and the variable <code>QAV_URL</code> ={" "}
                <code>{window.location.origin}</code>.
              </li>
            </ol>
          </details>
```

In `index.css`, add:

```css
.run-help { margin-top: var(--space-4); }
.run-help summary { cursor: pointer; font-weight: 600; }
.run-help li { margin-bottom: var(--space-3); }
```

- [ ] **Step 7: Add the CI step.** In `.github/workflows/ci.yml`, in the `dashboard` job after the `Tests` step (working directory `dashboard`), add:

```yaml
      - name: Workflow template tests (templates/github)
        run: node --test ../templates/github/qa-vision-run.test.mjs
```

- [ ] **Step 8: Update `TODO.md` section B.**
- Mark `Run a single TC, a selection ("bunch"), or a whole suite` and `First version triggers the customer's CI (GitHub Actions workflow_dispatch)…` as `[x]`, with "(v1 Play and Stop, 2026-10-07; spec `docs/superpowers/specs/2026-10-07-run-from-qa-vision-design.md`)".
- Under `Live run progress and cancel a running job`, add "(cancel done in v1 as Stop; live step progress is out of scope)".
- Add the future phases as unchecked items:
  - Pause and Resume (BeforeStep hook, screenshot on pause, time limit, fail open);
  - Stop followed by a resuming re-run, plus "Re-run failures";
  - a GitHub App instead of the personal token;
  - run parameters, scheduled runs, and more CI providers;
  - a dedicated execution-service.

- [ ] **Step 9: Run every check and confirm it passes.**

Run: `node --test templates/github/qa-vision-run.test.mjs`, then `cd dashboard && npm run lint && npm run typecheck && npx vitest run && npm run build && node --test ../templates/github/qa-vision-run.test.mjs`
Expected: PASS, with pristine output.

- [ ] **Step 10: Commit.**

```bash
FILES="templates/github/qa-vision-run.yml templates/github/qa-vision-run.mjs templates/github/qa-vision-run.test.mjs dashboard/src/templates/qa-vision-run.yml.txt dashboard/src/templates/qa-vision-run.mjs.txt dashboard/src/templates/templates.test.ts dashboard/src/components/CiTargetCard.tsx dashboard/src/components/CiTargetCard.test.tsx dashboard/src/index.css .github/workflows/ci.yml TODO.md"
git add $FILES && git commit -m "feat: qa-vision-run workflow template for the test repo, with its help block; TODO" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $FILES
```

---

## After all tasks: end to end (manual, needs the user)

This is the spec's "End to end" check. It is not a task: it needs the user's GitHub token and the user's change to the OBT repository.

1. `TM_SECRETS_KEY` is in `.env` (Task 6 Step 3b). Then run `set -a; . ./.env; set +a; docker compose up -d --build --wait` and `bash scripts/smoke_gateway.sh`. Never use `down -v`.
2. The user copies `templates/github/qa-vision-run.yml` and `.mjs` into the OBT repository on its default branch. The user adds `QAV_API_KEY` and `QAV_URL` there, with the tunnel's public URL, because hosted runners cannot reach localhost.
3. An owner saves `owner/test-repo`, `qa-vision-run.yml`, the branch and the token in Settings. The card reads "Connected: … · token …xxxx · expires …".
4. Run a full import of OBT's `.feature` files, which fills `scenario_name`.
5. Press Run on one OBT case.
   - The panel goes from "Queued" to "Running · 1 test · …", then to "Passed" or "Failed".
   - "View in GitHub" opens the run.
   - The panel then links the results, and they appear in Last runs.
6. Press Run on a second case and Stop it. The panel ends on "Stopped by <you>".

## Future phases (not in v1, copied from the spec; no tasks)

1. **Pause and Resume.**
   - A cucumber `BeforeStep` hook in the customer repo asks QA Vision whether to continue. Pause holds before the next step, with the browser still open.
   - A screenshot taken on pause is sent to QA Vision.
   - A pause has a limit (for example 15 minutes) and then stops automatically.
   - The hook fails open: if QA Vision is unreachable, the test runs on.
2. **Stop followed by a resuming re-run**, built on Pause, plus "Re-run failures" of a finished run.
3. **A GitHub App** instead of the personal token: short-lived installation tokens owned by no single person. This is the TODO item "connect repository".
4. **Run parameters** (environment, workers, retries), scheduled runs, and more CI providers (GitLab, Azure Pipelines).
5. **A dedicated `execution-service`** once execution outgrows test-management.

## Self-review (done while writing)

- **Spec coverage:**

  | Spec part | Task |
  |---|---|
  | Migration 004 and `scenario_name` | 1 |
  | Token encryption and GitHub client | 2 |
  | `ci-target` endpoints, saving a target, the events, PUT, GET and DELETE | 3 |
  | Starting a run, 412, 422, the 409 refresh, dispatch with `return_run_details` (run id stored at Play on 200), polling, the 204 fallback (title matching and 2-min `failed_to_start`), the status map | 4 |
  | Stop at once with the run id from Play; the 204 fallback for a queued request with no run id | 5 |
  | Gateway, smoke, README (endpoints, `TM_SECRETS_KEY`, default branch, security note) and `.env.example` | 6 |
  | Settings section: fields, save, the specific error, the audit line, expiry, Disconnect, server not configured | 7 |
  | Help block | 10 |
  | Play on case, selection and suite; the dialog; the disabled reasons | 8 |
  | Run panel: states, 5-s poll, Stop, "View in GitHub", results and the 5-min message, a11y | 9 |
  | Requested runs tab and DESIGN.md | 9 |
  | OBT workflow, script and TODO.md | 10 |
  | Spec testing list | Tasks 1–5 (pytest) and 7–10 (vitest, `node:test`) |
  | E2E | Manual section |

- **Placeholders:** none. Every code step carries the code. The two conditional instructions (httpx byte serialisation, fake timers) give the exact fallback.
- **Type consistency:**
  - `RunRequestOut` fields match the TS `RunRequest`.
  - `refreshing` is used by `useLatestRunRequest`, `RunPanel` and `RequestedRunsPage`.
  - The query keys `["ci-target", id]`, `["run-requests", id, "latest"]` and `["project", id]` are shared across Tasks 7–9.
  - `github_failure` is defined in Task 3 and imported in Tasks 4 and 5.
  - `_match` and `_apply_github` are defined in Task 4 and replaced in Task 5.
  - `DispatchResult(run_id, html_url)` is defined in Task 2 and consumed by `create` in Task 4. `safe_run_url` is used for both the dispatch `html_url` and a matched run's `html_url`. The `github.dispatch(run_id=...)` stub (200) and `github.dispatch()` stub (204) are used the same way in Tasks 2, 4 and 5.
- **Review Focus:** five lines, each pinned by a named test in its owning task.
  - Duplicate scenario names inside one file are already pinned by the existing parse test.
  - The cross-file case is Ruling 2.
