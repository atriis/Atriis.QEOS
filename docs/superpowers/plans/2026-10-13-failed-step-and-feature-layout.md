# Failed step on scenarios, feature page as scenario cards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show, on the scenario page and on a feature page laid out as one card per scenario, the step that failed in each scenario's latest result, in red with the error on hover/focus.

**Architecture:** The collector records the failing Cucumber step's text and line per result; ingestion stores and masks them and answers the latest result per test key in bulk (`POST analytics/latest-results`), deriving the step text from `details` for older rows. The dashboard locates the step with one pure function (line first, text fallback, `<placeholder>`-aware) and renders it in `GherkinBlock`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic (ingestion); stdlib Python 3.9+ (collector); React 19, TypeScript, TanStack Query, MSW, Vitest (dashboard).

**Spec:** `docs/superpowers/specs/2026-10-13-failed-step-and-feature-layout-design.md`

## Global Constraints

- Result payload field, exactly: `"failed_step": {"text": <1–1000 chars>, "line": <optional int 1–1_000_000>}`; extra fields 422.
- Columns: `test_results.failed_step_text` String(1000) nullable; `test_results.failed_step_line` Integer nullable, check `> 0`.
- `failed_step_text` is masked like `message`/`details` (built-in + project patterns), re-masked by `jobs/remask.py`.
- Endpoint: `POST /api/v1/projects/{id}/analytics/latest-results`, body `{"keys": [...]}`, 1–500 distinct 64-hex keys, READ_ROLES; answer `{"results": {key: {status, run_id, branch, environment, started_at, message, failed_step?}}}`; latest on **any branch** (run `started_at` desc, run id desc); keys without results absent.
- `failed_step` only for `failed`/`errored`. Older rows: `text` = first line of `details` when it differs from the first line of `message`; `line` absent.
- Migration: next free revision after the latest in `platforms/ingestion-service/alembic/versions` (021 at planning time; another session adds migrations — check first).
- Collector version `0.6.0`, tag `collector-v0.6.0`; `collector-v0` floats to it automatically.
- **Order (hard):** the server delivery (Tasks 1–4) is pushed **and the local stack's ingestion rebuilt** before `collector-v0.6.0` is tagged — workflows on `@collector-v0` get 0.6.0 immediately, and an old server rejects `failed_step` with 422.
- Dashboard: existing CSS tokens only; colour never the only signal; tooltip on hover **and** keyboard focus, Escape closes it.
- Never write the employer's name in code, tests, docs or commits.
- Each delivery lands on master after the full local CI mirror passes (`.github/workflows/ci.yml`; dashboard `npx vitest run --maxWorkers=3`).
- `platforms/ingestion-service` is being changed concurrently by another session (impact work): re-read every file before editing; stage only your own files.

## Review Focus

1. **A Scenario Outline whose example values contain regex characters** (`When I pay "$10.00 (EUR)"`) — the placeholder matcher must escape the template, not treat it as a regex. Pinned in Task 6 (`matches a template with regex characters`).
2. **A failed step inside a data table or doc string context** (a step followed by a table) — the table rows are never taken as steps; the step's own line still matches. Pinned in Task 6 (`skips data tables and doc strings`).
3. **A failure in a Background step on the feature page** — the shared Background block stays neutral and the scenario's card says which Background step failed. Pinned in Task 9 (`a Background failure is named on the card`).
4. **A feature file with CRLF line endings** — lines and text still match. Pinned in Task 6 (`handles CRLF`).
5. **`latest-results` with mixed-case keys** — keys are matched case-insensitively and answered under the key as sent lowercased. Pinned in Task 3 (`keys are case-insensitive`).

---

## Delivery 1 — server

### Task 1: Store and mask the failed step (migration, schema, ingest)

**Files:**
- Create: `platforms/ingestion-service/alembic/versions/021_failed_step.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/run.py` (`RunResult` columns + check)
- Modify: `platforms/ingestion-service/src/ingestion/schemas/collect.py` (`FailedStepIn`, `ResultIn.failed_step`)
- Modify: `platforms/ingestion-service/src/ingestion/service/ingest_service.py` (rows dict)
- Test: `platforms/ingestion-service/tests/unit/test_migration.py`, `tests/unit/test_collect_schema.py`, `tests/integration/test_collect_failed_step.py`

**Interfaces:**
- Produces: `RunResult.failed_step_text`, `RunResult.failed_step_line`; `FAILED_STEP_TEXT_LENGTH = 1000` in `models/run.py`.

- [ ] **Step 1: Failing tests.** Append to `tests/unit/test_migration.py` (it has `migrated_engine`, `KEY`, `RUN`; read how `RESULT` rows are inserted there, or insert one minimal row with the columns `test_results` requires):

```python
def test_failed_step_line_must_be_positive(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "d" * 64})
        conn.execute(text(RUN), {"idem": "fs", "provider": "github_actions"})
        run_id = conn.execute(text("SELECT id FROM test_runs WHERE idempotency_key = 'fs'")).scalar()
        conn.execute(text(
            "INSERT INTO test_results (run_id, test_key, suite, class_name, name, status, duration_ms, failed_step_text, failed_step_line) "
            "VALUES (:r, :k, '', '', 'n', 'failed', 1, 'When x', 3)"), {"r": run_id, "k": "e" * 64})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text("UPDATE test_results SET failed_step_line = 0"))
```

(If `test_results` has more NOT NULL columns than listed — `truncated`, `redacted` — add them with their defaults; read the model.)

Append to `tests/unit/test_collect_schema.py` (helper `body(run=None, results=None)` exists):

```python
def test_failed_step_is_optional_and_validated():
    ok = body(results=[{"name": "t", "status": "failed", "failed_step": {"text": "When I search Lisbon", "line": 14}}])
    assert RunUpload.model_validate(ok).results[0].failed_step.line == 14
    no_line = body(results=[{"name": "t", "status": "failed", "failed_step": {"text": "When x"}}])
    assert RunUpload.model_validate(no_line).results[0].failed_step.line is None


@pytest.mark.parametrize("step", [{"text": ""}, {"text": "x" * 1001}, {"text": "x", "line": 0},
                                  {"text": "x", "line": 1_000_001}, {"text": "x", "extra": 1}])
def test_invalid_failed_step_is_rejected(step):
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "failed_step": step}]))
```

Create `tests/integration/test_collect_failed_step.py`:

```python
"""The failing Cucumber step is stored per result, masked like the message (spec 2026-10-13 §3.2)."""
from src.ingestion.models import RunResult
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

TOKEN = "ghp_" + "a" * 36


def test_failed_step_is_stored(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "search", "status": "failed", "message": "boom",
                                 "failed_step": {"text": "When I search Lisbon", "line": 14}}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    row = db.query(RunResult).one()
    assert (row.failed_step_text, row.failed_step_line) == ("When I search Lisbon", 14)


def test_failed_step_text_is_masked(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "login", "status": "failed",
                                 "failed_step": {"text": f'When I log in with token "{TOKEN}"', "line": 3}}])
    client.post(URL, json=body, headers=key_headers(key))
    row = db.query(RunResult).one()
    assert TOKEN not in row.failed_step_text and row.redacted is True


def test_results_without_failed_step_store_null(client, make_key, db):
    _, key = make_key(project_id=1)
    client.post(URL, json=upload_body(), headers=key_headers(key))
    assert all(r.failed_step_text is None and r.failed_step_line is None for r in db.query(RunResult))
```

And in `tests/integration/test_export.py` add an assertion that an exported result line carries `failed_step_text` and `failed_step_line` keys (the exporter writes every column; read the file's existing result-line test and extend it).

- [ ] **Step 2: Run** `cd platforms/ingestion-service && SECRET_KEY=test .venv/Scripts/python -m pytest tests/unit/test_migration.py tests/unit/test_collect_schema.py tests/integration/test_collect_failed_step.py tests/integration/test_export.py -q` — FAIL.

- [ ] **Step 3: Model** — in `models/run.py`: `FAILED_STEP_TEXT_LENGTH = 1000`; in `RunResult` after `details`:

```python
    # The Cucumber step that failed, as the collector reported it (spec 2026-10-13); masked like message
    failed_step_text = Column(String(FAILED_STEP_TEXT_LENGTH), nullable=True)
    failed_step_line = Column(Integer, nullable=True)  # its line in the .feature file
```

and in `RunResult.__table_args__` (create the tuple if absent, keeping existing entries):
`CheckConstraint("failed_step_line > 0", name="chk_test_results_failed_step_line")`.

- [ ] **Step 4: Migration** `021_failed_step.py` (style of `019_collection_settings.py`; `down_revision` = the current head):

```python
"""test_results.failed_step_text / failed_step_line: the Cucumber step that failed (spec 2026-10-13)"""
import sqlalchemy as sa
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("test_results") as batch:
        batch.add_column(sa.Column("failed_step_text", sa.String(length=1000), nullable=True))
        batch.add_column(sa.Column("failed_step_line", sa.Integer(), nullable=True))
        batch.create_check_constraint("chk_test_results_failed_step_line", "failed_step_line > 0")


def downgrade() -> None:
    with op.batch_alter_table("test_results") as batch:
        batch.drop_constraint("chk_test_results_failed_step_line", type_="check")
        batch.drop_column("failed_step_line")
        batch.drop_column("failed_step_text")
```

- [ ] **Step 5: Schema** — in `schemas/collect.py`, before `ResultIn`:

```python
class FailedStepIn(BaseModel):
    """The Cucumber step that failed (spec 2026-10-13 §2)."""
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    line: Optional[int] = Field(None, ge=1, le=1_000_000)
```

and in `ResultIn`: `failed_step: Optional[FailedStepIn] = None`. Add `"text"` handling of NUL like the other text fields if `ResultIn` rejects unstorable characters (reuse `_reject_unstorable` via a validator on `FailedStepIn.text`).

- [ ] **Step 6: Ingest** — in `ingest_service.ingest()`'s result loop, mask the step text with the same patterns before truncating, add its kinds to `kinds`, and add the two keys to the row dict:

```python
            step_text, step_kinds = mask(result.failed_step.text if result.failed_step else None, patterns)
            kinds = message_kinds | details_kinds | step_kinds
            ...
                "failed_step_text": step_text[:FAILED_STEP_TEXT_LENGTH] if step_text is not None else None,
                "failed_step_line": result.failed_step.line if result.failed_step else None,
```

(keep `kinds` computed once; adjust the existing line rather than duplicating it).

- [ ] **Step 7: Run the new tests, then the whole ingestion suite** — PASS.
- [ ] **Step 8: Commit** — `feat(ingestion): store the failed Cucumber step per result, masked (migration 021)`

### Task 2: Re-mask the failed step text

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/jobs/remask.py`
- Test: `platforms/ingestion-service/tests/integration/test_remask_job.py`

**Interfaces:** Consumes `RunResult.failed_step_text` (Task 1).

- [ ] **Step 1: Failing test** — read `test_remask_job.py`'s existing result test (it seeds a result whose `message` holds a value a newly added pattern matches, runs the job, asserts it is masked) and add the same for `failed_step_text`:

```python
def test_remask_covers_the_failed_step(db, make_key, ...):  # same fixtures as the message test above it
    # seed a result with failed_step_text='When I open account CUST-123456', add the pattern r"CUST-\d{6}",
    # run the job exactly as the message test does, then:
    assert "CUST-123456" not in row.failed_step_text and "[REDACTED" in row.failed_step_text
```

Write it in full by copying the message test's seeding and job call; only the column and value differ.

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** — in `remask.py`'s per-row loop, alongside `message`/`details`:

```python
            step, step_changed, step_cut = _remask_text(row.failed_step_text, patterns, row_kinds)
            if not (message_changed or details_changed or step_changed):
                ...
            row.failed_step_text = step[:FAILED_STEP_TEXT_LENGTH] if step is not None else None
```

Make the row query also select rows whose `failed_step_text` is not null if it filters on message/details today.
- [ ] **Step 4: Run** `tests/integration/test_remask_job.py` — PASS.
- [ ] **Step 5: Commit** — `feat(ingestion): the re-mask job covers the failed step text`

### Task 3: `latest-results` endpoint

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/service/analytics_service.py` (`_latest_ranked`, `latest_results`, `failed_step_of`; `latest_keys` reuses `_latest_ranked`)
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/analytics.py` (`LatestResultsIn`, route)
- Test: `platforms/ingestion-service/tests/unit/test_failed_step_of.py`, `tests/integration/test_latest_results.py`

**Interfaces:**
- Produces: `analytics_service.latest_results(db, project_id, keys: list[str]) -> dict[str, dict]`; `analytics_service.failed_step_of(status, message, details, step_text, step_line) -> dict | None`. Response shape per Global Constraints.

- [ ] **Step 1: Failing unit tests** `tests/unit/test_failed_step_of.py`:

```python
from src.ingestion.service.analytics_service import failed_step_of


def test_stored_step_wins():
    assert failed_step_of("failed", "boom", "When x\nboom", "When I search", 14) == {"text": "When I search", "line": 14}


def test_old_rows_take_the_first_details_line_when_it_is_not_the_message():
    assert failed_step_of("failed", "boom", "When I search Lisbon\nboom\n  at x", None, None) == {"text": "When I search Lisbon"}


def test_no_step_when_details_starts_with_the_message():
    assert failed_step_of("failed", "boom", "boom\n  at x", None, None) is None


def test_errored_counts_and_passed_never_has_a_step():
    assert failed_step_of("errored", None, "Given y\nE", None, None) == {"text": "Given y"}
    assert failed_step_of("passed", None, None, "When x", 3) is None
    assert failed_step_of("failed", None, None, None, None) is None
```

- [ ] **Step 2: Failing integration tests** `tests/integration/test_latest_results.py` — use `seed_run` from `tests/conftest.py` (read its signature: `_seed(started_at, results=((name, status, ms),), project_id=1, branch="main", environment=None, ...)`; if it cannot set message/details/failed_step, insert `RunResult` rows directly with `db` after seeding the run):

```python
"""Latest result per test key on any branch, with the failed step (spec 2026-10-13 §3.3)."""
from datetime import datetime, timedelta, timezone

from src.ingestion.models import RunResult
from tests.conftest import report_key

URL = "/api/v1/projects/1/analytics/latest-results"
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_latest_on_any_branch_with_the_failed_step(client, auth, project_role, seed_run, db):
    project_role("viewer")
    seed_run(T0, results=(("search", "passed", 5),), branch="main")
    run = seed_run(T0 + timedelta(hours=1), results=(("search", "failed", 5),), branch="feature/x")
    row = db.query(RunResult).filter_by(run_id=run.id).one()
    row.message, row.failed_step_text, row.failed_step_line = "boom", "When I search Lisbon", 14
    db.commit()
    key = report_key("search")
    body = client.post(URL, json={"keys": [key]}, headers=auth()).json()
    got = body["results"][key]
    assert got["status"] == "failed" and got["branch"] == "feature/x" and got["run_id"] == run.id
    assert got["failed_step"] == {"text": "When I search Lisbon", "line": 14} and got["message"] == "boom"


def test_keys_without_results_are_absent(client, auth, project_role):
    project_role("viewer")
    assert client.post(URL, json={"keys": ["a" * 64]}, headers=auth()).json() == {"results": {}}


def test_keys_are_case_insensitive(client, auth, project_role, seed_run):
    project_role("viewer")
    seed_run(T0, results=(("search", "passed", 5),))
    key = report_key("search")
    assert key.lower() in client.post(URL, json={"keys": [key.upper()]}, headers=auth()).json()["results"]


def test_limits_and_roles(client, auth, project_role):
    project_role("viewer")
    assert client.post(URL, json={"keys": []}, headers=auth()).status_code == 422
    assert client.post(URL, json={"keys": [f"{i:064x}" for i in range(501)]}, headers=auth()).status_code == 422
    assert client.post(URL, json={"keys": ["not-a-key"]}, headers=auth()).status_code == 422
    project_role(status_code=404)
    assert client.post(URL, json={"keys": ["a" * 64]}, headers=auth()).status_code == 404
```

(`report_key(name)` in conftest builds the test key `seed_run` uses; confirm and adapt names.)

- [ ] **Step 3: Run** both files — FAIL.

- [ ] **Step 4: Service** — in `analytics_service.py`:

```python
def _latest_ranked(filters, *columns):
    """Each test's results ranked newest first (run start, then run id): position 1 is its latest."""
    return (
        select(RunResult.test_key, *columns,
               func.row_number().over(partition_by=RunResult.test_key,
                                      order_by=(Run.started_at.desc(), Run.id.desc())).label("position"))
        .join(Run, Run.id == RunResult.run_id).where(*filters)
    ).subquery()


def failed_step_of(status, message, details, step_text, step_line) -> Optional[dict]:
    """The failed step for a failed/errored result (spec 2026-10-13 §3.3). Rows stored before the collector
    sent `failed_step` hold the step on details' first line, unless that line is just the message."""
    if status not in ("failed", "errored"):
        return None
    if step_text:
        return {"text": step_text, **({"line": step_line} if step_line else {})}
    first = (details or "").split("\n", 1)[0].strip()
    if first and first != (message or "").split("\n", 1)[0].strip():
        return {"text": first}
    return None


def latest_results(db: Session, project_id: int, keys: List[str]) -> dict:
    keys = sorted({k.lower() for k in keys})
    ranked = _latest_ranked(
        [Run.project_id == project_id, RunResult.test_key.in_(keys)],
        RunResult.status, RunResult.message, RunResult.details, RunResult.failed_step_text,
        RunResult.failed_step_line, Run.id.label("run_id"), Run.branch, Run.environment, Run.started_at,
    )
    out = {}
    for r in db.execute(select(ranked).where(ranked.c.position == 1)).mappings():
        entry = {"status": r["status"], "run_id": r["run_id"], "branch": r["branch"],
                 "environment": r["environment"], "started_at": r["started_at"], "message": r["message"]}
        step = failed_step_of(r["status"], r["message"], r["details"], r["failed_step_text"], r["failed_step_line"])
        if step:
            entry["failed_step"] = step
        out[r["test_key"]] = entry
    return out
```

Rewrite `latest_keys`'s `ranked` as `_latest_ranked(filters, RunResult.status)` with identical behaviour (its tests must stay green).

- [ ] **Step 5: Route** — in `endpoints/analytics.py`, next to `RunStripIn`:

```python
class LatestResultsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: List[Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]] = Field(min_length=1, max_length=500)


@router.post("/latest-results")
def latest_results(
    body: LatestResultsIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """Each test's latest result on any branch, with the failed step (scenario and feature pages)."""
    return {"results": analytics_service.latest_results(db, access.project_id, body.keys)}
```

- [ ] **Step 6: Run** the two new files, `tests/integration/test_latest_keys.py` and the analytics tests — PASS.
- [ ] **Step 7: Commit** — `feat(ingestion): latest-results, each test's latest result with the failed step`

### Task 4: Server docs, push, rebuild the local stack

**Files:** `TECHNICAL_SPECIFICATION.md`, `platforms/ingestion-service/README.md`, `TODO.md`.

- [ ] **Step 1:** TECHNICAL_SPECIFICATION: `failed_step` in the result payload table; `latest-results` in the ingestion API list. ingestion README: the two columns (masked, re-masked, exported), the endpoint and its old-row fallback. TODO: item under the cases/dashboard section, server part done (date).
- [ ] **Step 2:** `python scripts/check_architecture_docs.py` (the endpoint is under `analytics`, already routed).
- [ ] **Step 3:** Full CI mirror, commit `docs: failed step and latest-results, server side`, `git pull --rebase`, push, watch CI green.
- [ ] **Step 4:** Rebuild the local stack's ingestion so it accepts `failed_step` before collector 0.6.0 exists:
  `docker compose up -d --build --wait ingestion-migrate ingestion-service gateway`; confirm `ingestion-migrate` ran the new revision; `bash scripts/smoke_gateway.sh` (with `.env` sourced).

## Delivery 2 — collector 0.6.0

### Task 5: Send `failed_step`, release 0.6.0

**Files:**
- Modify: `collector/src/qeos_collector/formats.py` (Cucumber parser)
- Modify: `collector/src/qeos_collector/__init__.py` (`0.6.0`), `collector/tests/test_package.py`
- Modify: `collector/README.md`, every `collector-v0.5.2` pin outside `docs/superpowers` (keep TODO history lines), `TODO.md`
- Test: `collector/tests/test_cucumber.py`

**Interfaces:** Produces result rows with optional `"failed_step": {"text": str, "line": int?}` — exactly the server's `FailedStepIn`.

- [ ] **Step 1: Failing tests** in `collector/tests/test_cucumber.py` — read its helper that builds a Cucumber JSON file (features → elements → steps with `keyword`, `name`, `line`, `result.status`, `result.error_message`) and add:

```python
def test_failed_step_carries_text_and_line(tmp_path):
    rows = parse_cucumber(tmp_path, steps=[step("Given ", "a user", 4, "passed"),
                                           step("When ", "I search Lisbon", 5, "failed", "boom")])
    assert rows[0]["failed_step"] == {"text": "When I search Lisbon", "line": 5}


def test_background_step_failure_keeps_its_own_line(tmp_path):
    rows = parse_cucumber(tmp_path, background=[step("Given ", "logged in", 3, "failed", "nope")],
                          steps=[step("When ", "x", 7, "skipped")])
    assert rows[0]["failed_step"] == {"text": "Given logged in", "line": 3}


def test_passed_and_skipped_scenarios_have_no_failed_step(tmp_path):
    assert "failed_step" not in parse_cucumber(tmp_path, steps=[step("Given ", "a", 1, "passed")])[0]
    assert "failed_step" not in parse_cucumber(tmp_path, steps=[step("Given ", "a", 1, "pending")])[0]


def test_missing_line_keeps_the_text_and_long_text_is_cut(tmp_path):
    rows = parse_cucumber(tmp_path, steps=[step("When ", "y" * 2000, None, "failed", "e")])
    assert rows[0]["failed_step"]["text"] == ("When " + "y" * 2000)[:1000] and "line" not in rows[0]["failed_step"]
```

`step(keyword, name, line, status, error=None)` and `parse_cucumber(tmp_path, steps, background=None)` are small helpers you add at the top of the test section if the file has none: write the JSON (`[{"uri": "f.feature", "name": "F", "elements": [{"type": "background", "steps": background}, {"type": "scenario", "name": "S", "steps": steps}]}]`, background element only when given) and return `parse_file(path).results` (use the module's real parse entry point). Also assert a JUnit fixture parse (`tests/fixtures/pytest.xml`) yields no `failed_step` key.

- [ ] **Step 2: Run** `cd collector && .venv/Scripts/python -m pytest tests/test_cucumber.py -q` — FAIL.
- [ ] **Step 3: Implement** in `_cucumber_feature`, inside `if failed_step is not None:` after `_attach(...)`:

```python
            if step_name:
                entry = {"text": step_name[:1000]}
                line = failed_step.get("line")
                if isinstance(line, int) and not isinstance(line, bool) and 1 <= line <= 1_000_000:
                    entry["line"] = line
                row["failed_step"] = entry
```

- [ ] **Step 4:** `__version__ = "0.6.0"`, `test_package.py`; move `collector-v0.5.2` pins to `collector-v0.6.0` (`git grep -n "collector-v0.5.2" -- ':!docs/superpowers'` empty after, except TODO history); collector README: `failed_step` in the payload section; TODO line.
- [ ] **Step 5: Run** the collector suite (`.venv/Scripts/pip install -e . --no-deps` first so the package metadata reads 0.6.0), dashboard checks (COLLECTOR_REF), architecture check — PASS.
- [ ] **Step 6:** Confirm Task 4 Step 4 is done (local ingestion accepts `failed_step`: post one upload with it through the gateway or run `tests/integration/test_collect_failed_step.py` against the rebuilt image's code). Commit `release: qeos-collector 0.6.0 (failed step)`, pull --rebase, push, CI green, then `git tag collector-v0.6.0 <commit>` and push it; watch "Release collector": the `float` job must move `collector-v0` (`git ls-remote --tags origin collector-v0 collector-v0.6.0` show the same commit).

## Delivery 3 — dashboard

### Task 6: `locateFailedStep` and friends

**Files:**
- Create: `dashboard/src/lib/failedStep.ts`
- Modify: `dashboard/src/lib/gherkinTokens.ts` (export `STEPS`, `HEADINGS`)
- Test: `dashboard/src/lib/failedStep.test.ts`

**Interfaces:**
- Produces:
  - `export interface FailedStep { text: string; line?: number }`
  - `export interface StepLine { line: number; text: string }` (1-based line in the given text; `text` = keyword + step, trimmed)
  - `export function stepLines(text: string, from?: number, to?: number): StepLine[]` — steps between lines `from`..`to` inclusive (defaults: whole text)
  - `export function scenarioSteps(source: string, scenarioLine: number): StepLine[]` — the applicable Background's steps, then the scenario's
  - `export function matchesStep(template: string, actual: string): boolean`
  - `export function locateFailedStep(steps: StepLine[], failed: FailedStep): number | null` — index into `steps`

- [ ] **Step 1: Failing tests** `failedStep.test.ts`:

```ts
import { locateFailedStep, matchesStep, scenarioSteps, stepLines } from "./failedStep";

const FEATURE = [
  "Feature: Search",                 // 1
  "  Background:",                   // 2
  "    Given I am logged in",        // 3
  "",                                // 4
  "  Scenario Outline: by city",     // 5
  "    When I search <city>",        // 6
  "    Then I see results",          // 7
  "      | name |",                  // 8
  "      | x    |",                  // 9
  "    Examples:",                   // 10
  "      | city   |",                // 11
  "      | Lisbon |",                // 12
  "",                                // 13
  "  Scenario: docs",                // 14
  "    Given a note:",               // 15
  '      """',                       // 16
  "      Then not a step",           // 17
  '      """',                       // 18
  "    Then it is saved",            // 19
].join("\n");

test("scenarioSteps returns the Background's steps then the scenario's, with lines", () => {
  expect(scenarioSteps(FEATURE, 5)).toEqual([
    { line: 3, text: "Given I am logged in" },
    { line: 6, text: "When I search <city>" },
    { line: 7, text: "Then I see results" },
  ]);
});

test("skips data tables and doc strings", () => {
  expect(scenarioSteps(FEATURE, 14).map((s) => s.line)).toEqual([3, 15, 19]);
});

test("matches by line when the text agrees", () => {
  const steps = scenarioSteps(FEATURE, 5);
  expect(locateFailedStep(steps, { text: "When I search Lisbon", line: 6 })).toBe(1);
});

test("a stale line falls back to the text", () => {
  const steps = scenarioSteps(FEATURE, 5);
  expect(locateFailedStep(steps, { text: "Then I see results", line: 6 })).toBe(2);
});

test("text only, and a Background step", () => {
  const steps = scenarioSteps(FEATURE, 5);
  expect(locateFailedStep(steps, { text: "Given I am logged in" })).toBe(0);
  expect(locateFailedStep(steps, { text: "When I book" })).toBeNull();
});

test("matches a template with regex characters", () => {
  expect(matchesStep('When I pay "<amount>"', 'When I pay "$10.00 (EUR)"')).toBe(true);
  expect(matchesStep("When I pay (cash)", "When I pay (cash)")).toBe(true);
  expect(matchesStep("When I pay (cash)", "When I pay cash")).toBe(false);
});

test("handles CRLF", () => {
  expect(stepLines("Scenario: s\r\n  Given a\r\n  When b\r\n")).toEqual([{ line: 2, text: "Given a" }, { line: 3, text: "When b" }]);
});

test("a Rule resets the Background", () => {
  const ruled = ["Feature: F", "  Background:", "    Given outer", "  Rule: r", "    Scenario: s", "      When x"].join("\n");
  expect(scenarioSteps(ruled, 5).map((s) => s.text)).toEqual(["When x"]);
});
```

- [ ] **Step 2: Run** `cd dashboard && npx vitest run src/lib/failedStep.test.ts` — FAIL.
- [ ] **Step 3: Implement** `failedStep.ts` (export `STEPS` and `HEADINGS` from `gherkinTokens.ts` first):

```ts
import { HEADINGS, STEPS } from "./gherkinTokens";

export interface FailedStep { text: string; line?: number }
export interface StepLine { line: number; text: string }

const BACKGROUND = ["Background:", "Contexto:"];
const RULE = ["Rule:", "Regra:"];
const isStep = (t: string) => STEPS.some((k) => t.startsWith(k));
const isHeading = (t: string, set: string[] = HEADINGS) => set.some((h) => t.startsWith(h));

/** Steps between 1-based lines from..to; table rows and doc strings are not steps. */
export function stepLines(text: string, from = 1, to = Number.MAX_SAFE_INTEGER): StepLine[] {
  const lines = text.split(/\r?\n/);
  const out: StepLine[] = [];
  let fence: string | null = null;
  lines.forEach((raw, i) => {
    const n = i + 1;
    const t = raw.trim();
    if (fence) { if (t.startsWith(fence)) fence = null; return; }
    if (t.startsWith('"""') || t.startsWith("```")) { fence = t.slice(0, 3); return; }
    if (n >= from && n <= to && isStep(t)) out.push({ line: n, text: t });
  });
  return out;
}

/** The steps a scenario runs: its Background's (feature- or rule-level), then its own. */
export function scenarioSteps(source: string, scenarioLine: number): StepLine[] {
  const lines = source.split(/\r?\n/);
  let background: [number, number] | null = null;
  let end = lines.length;
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim();
    const n = i + 1;
    if (n < scenarioLine) {
      if (isHeading(t, RULE)) background = null;
      else if (isHeading(t, BACKGROUND)) background = [n, n];
      else if (background && isHeading(t)) background = [background[0], n - 1];
      else if (background && background[1] === background[0] && n === scenarioLine - 1) background = [background[0], n];
    } else if (n > scenarioLine && (isHeading(t) && !t.startsWith("Examples:") && !t.startsWith("Exemplos:") || t.startsWith("@"))) {
      end = n - 1;
      break;
    }
  }
  const bg = background ? stepLines(source, background[0], background[1] === background[0] ? scenarioLine - 1 : background[1]) : [];
  return [...bg, ...stepLines(source, scenarioLine, end)];
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** A step of the case against the step that ran: each <placeholder> matches any non-empty text. */
export function matchesStep(template: string, actual: string): boolean {
  const pattern = template.trim().split(/<[^<>"]+>/).map(escape).join(".+");
  return new RegExp(`^${pattern}$`).test(actual.trim());
}

export function locateFailedStep(steps: StepLine[], failed: FailedStep): number | null {
  if (failed.line != null) {
    const at = steps.findIndex((s) => s.line === failed.line);
    if (at >= 0 && matchesStep(steps[at].text, failed.text)) return at;
  }
  const byText = steps.findIndex((s) => matchesStep(s.text, failed.text));
  return byText >= 0 ? byText : null;
}
```

Simplify `scenarioSteps`'s Background bookkeeping if a clearer version passes the same tests (the contract is the tests, not this exact loop).

- [ ] **Step 4: Run** — PASS; `npm run lint && npm run typecheck`.
- [ ] **Step 5: Commit** — `feat(dashboard): locate the failed step in a scenario (line first, then text)`

### Task 7: API, `GherkinBlock` failed line, tooltip, status pill

**Files:**
- Modify: `dashboard/src/api/analytics.ts` (`LatestResult`, `getLatestResults`)
- Modify: `dashboard/src/components/GherkinBlock.tsx` (`failed` prop)
- Create: `dashboard/src/components/FailedStepTip.tsx`, `dashboard/src/components/LastResultPill.tsx`
- Modify: `dashboard/src/index.css` (`.gk-failed`, `.failed-tip`)
- Test: `dashboard/src/components/GherkinBlock.test.tsx`, `FailedStepTip.test.tsx`, `LastResultPill.test.tsx`

**Interfaces:**
- Produces:
  - `export interface LatestResult { status: string; run_id: number; branch: string | null; environment: string | null; started_at: string; message: string | null; failed_step?: { text: string; line?: number } }`
  - `export function getLatestResults(projectId: number, keys: string[]): Promise<{ results: Record<string, LatestResult> }>` (POST; callers batch by 500)
  - `GherkinBlock` prop `failed?: { line: number; tip: ReactNode }` — `line` is 1-based in `text`
  - `FailedStepTip({ projectId, result }: { projectId: number; result: LatestResult })`
  - `LastResultPill({ result }: { result: LatestResult | null | undefined })`

- [ ] **Step 0: ui-ux-pro-max** — invoke the skill for the failed-line treatment (red background plus a visible "failed" marker and icon, not colour alone), the tooltip (hover and focus, Escape, placement, contrast, touch) and the pill; existing tokens only (`--status-failed`, `.badge`, `StatusDot`). Record the recommendations in the report.

- [ ] **Step 1: Failing tests:**

```tsx
// GherkinBlock.test.tsx (add)
test("marks the failed line and shows its tip on focus", async () => {
  render(<GherkinBlock text={"Scenario: s\n  When a\n  Then b"} failed={{ line: 2, tip: <span>boom</span> }} />);
  const line = screen.getByText(/When a/).closest(".gk-failed") as HTMLElement;
  expect(line).toHaveTextContent(/failed/i);
  line.focus();
  expect(await screen.findByRole("tooltip")).toHaveTextContent("boom");
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).toBeNull();
});

// FailedStepTip.test.tsx
test("shows the error, branch, environment, time and a run link", () => {
  render(<MemoryRouter><FailedStepTip projectId={3} result={{ status: "failed", run_id: 9, branch: "main",
    environment: "staging", started_at: new Date().toISOString(), message: "boom", failed_step: { text: "When a" } }} /></MemoryRouter>);
  expect(screen.getByText("boom")).toBeInTheDocument();
  expect(screen.getByText(/main/)).toBeInTheDocument();
  expect(screen.getByText(/staging/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /open run/i })).toHaveAttribute("href", "/projects/3/runs/9");
});

// LastResultPill.test.tsx
test.each([["failed", /failed/i], ["errored", /errored/i], ["passed", /passed/i], ["skipped", /skipped/i]])(
  "shows %s", (status, text) => {
    render(<LastResultPill result={{ status, run_id: 1, branch: null, environment: null, started_at: new Date().toISOString(), message: null }} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
test("no runs yet", () => {
  render(<LastResultPill result={null} />);
  expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**

`api/analytics.ts`:

```ts
export interface LatestResult {
  status: string; run_id: number; branch: string | null; environment: string | null;
  started_at: string; message: string | null; failed_step?: { text: string; line?: number };
}

/** Each test's latest result on any branch, with the failed step; at most 500 keys per call. */
export function getLatestResults(projectId: number, keys: string[]): Promise<{ results: Record<string, LatestResult> }> {
  return apiFetch(`/api/v1/projects/${projectId}/analytics/latest-results`, { method: "POST", body: JSON.stringify({ keys }) });
}
```

`GherkinBlock`: accept `failed`; in both render branches, the line whose 1-based number equals `failed.line` gets `className="gk-failed"`, `tabIndex={0}`, `aria-describedby` pointing at the tooltip, a visible marker (`<span className="gk-failed-mark"><XCircle aria-hidden /> failed</span>`), and shows `failed.tip` in a `role="tooltip"` element while hovered or focused; Escape hides it. Keep the existing markup for every other line.

`FailedStepTip`: message (or "No error message"), then `branch · environment · ago(started_at)` (omit missing parts), then `<Link to={`/projects/${projectId}/runs/${result.run_id}`}>Open run</Link>`.

`LastResultPill`: `<span className="badge"><StatusDot status={s} /> {Label} · {ago(started_at)}</span>`; `null`/`undefined` → `badge badge-muted` "No runs yet".

CSS: `.gk-failed` background from `--status-failed` at low alpha via an existing token or `color-mix(in srgb, var(--status-failed) 14%, transparent)`, left border `var(--status-failed)`; `.gk-failed-mark`; `.failed-tip` uses the existing tooltip/popover tokens.

- [ ] **Step 4: Run** the three test files, `npm run lint && npm run typecheck` — PASS.
- [ ] **Step 5: Commit** — `feat(dashboard): failed line in GherkinBlock, failed-step tooltip, last-result pill`

### Task 8: Scenario page

**Files:**
- Modify: `dashboard/src/pages/CaseEditorPage.tsx`
- Test: `dashboard/src/pages/CaseEditorPage.test.tsx` (or the existing case page test file — find it)

**Interfaces:** Consumes Tasks 6–7; `featureDetailQuery(id, path)` from `lib/featureQueries`.

- [ ] **Step 1: Failing tests** (MSW handlers as the existing case page tests use; register `latest-results` and `features/detail`):

```tsx
test("the failed step is red with its error, located through the feature file", async () => {
  // case: source_path "f.feature", line 5, automated_test_key KEY, gherkin "Background:\n  Given I am logged in\nScenario Outline: by city\n  When I search <city>\n  Then I see results"
  // features/detail content = FEATURE from failedStep.test.ts
  // latest-results: { [KEY]: { status: "failed", run_id: 9, branch: "main", environment: null, started_at: <now>, message: "boom", failed_step: { text: "When I search Lisbon", line: 6 } } }
  renderCase();
  const failed = (await screen.findByText(/When I search/)).closest(".gk-failed");
  expect(failed).not.toBeNull();
  expect(screen.getByText(/failed/i, { selector: ".badge *, .badge" })).toBeInTheDocument();
});

test("without a source file it matches the case's own Gherkin by text", async () => { /* no source_path; same latest-results without line */ });
test("a passed latest result marks nothing and shows Passed", async () => { /* status passed, no failed_step */ });
test("no automated test key: no pill, no request", async () => { /* automated_test_key null; assert latest-results not called */ });
```

Write the four tests in full with the file's existing render helper and fixtures.

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** in the case page:

```tsx
const key = c?.automated_test_key ?? null;
const latest = useQuery({
  queryKey: ["latest-results", id, key],
  enabled: key != null,
  queryFn: () => getLatestResults(id, [key!]).then((r) => r.results[key!.toLowerCase()] ?? null),
});
const feature = useQuery({ ...featureDetailQuery(id, c?.source_path ?? ""), enabled: !!c?.source_path && latest.data?.failed_step != null });
const failedLine = useMemo(() => {
  const step = latest.data?.failed_step;
  if (!c?.gherkin || !step) return null;
  const shown = stepLines(c.gherkin);                        // steps as the case displays them
  const source = feature.data?.content;
  const scenarioLine = feature.data?.cases.find((fc) => fc.number === c.number)?.line ?? null;
  const index = source && scenarioLine
    ? locateFailedStep(scenarioSteps(source, scenarioLine), step)
    : locateFailedStep(shown, { text: step.text });          // no source: text only
  return index != null && shown[index] ? shown[index].line : null;
}, [c, latest.data, feature.data]);
```

Render `<LastResultPill result={latest.data} />` above the Gherkin when `key != null`, and pass `failed={failedLine != null ? { line: failedLine, tip: <FailedStepTip projectId={id} result={latest.data!} /> } : undefined}` to the case's `GherkinBlock`.

- [ ] **Step 4: Run** the page tests, lint, typecheck — PASS.
- [ ] **Step 5: Commit** — `feat(dashboard): scenario page shows the last result and the failed step`

### Task 9: Feature page as scenario cards

**Files:**
- Create: `dashboard/src/lib/featureBlocks.ts`
- Modify: `dashboard/src/pages/FeaturePage.tsx`
- Test: `dashboard/src/lib/featureBlocks.test.ts`, `dashboard/src/pages/FeaturePage.test.tsx`

**Interfaces:**
- Produces: `export interface Block { start: number; end: number; text: string }` (1-based, inclusive lines of the file); `export function splitFeature(content: string, headingLines: number[]): { preamble: Block | null; scenarios: Map<number, Block> }` — keyed by heading line; a scenario block starts at its heading, moved up over directly preceding `@tag`/`#comment` lines, and ends before the next block's start (trailing blank lines dropped); the preamble is everything before the first block.

- [ ] **Step 1: Failing tests** `featureBlocks.test.ts`:

```ts
import { splitFeature } from "./featureBlocks";

const FILE = ["Feature: F", "  Background:", "    Given bg", "", "  @smoke", "  Scenario: one", "    When a", "",
              "  Scenario: two", "    When b", ""].join("\n");

test("splits the preamble and each scenario, tags included", () => {
  const { preamble, scenarios } = splitFeature(FILE, [6, 9]);
  expect(preamble).toEqual({ start: 1, end: 3, text: "Feature: F\n  Background:\n    Given bg" });
  expect(scenarios.get(6)).toEqual({ start: 5, end: 7, text: "  @smoke\n  Scenario: one\n    When a" });
  expect(scenarios.get(9)).toEqual({ start: 9, end: 10, text: "  Scenario: two\n    When b" });
});
```

`FeaturePage.test.tsx` — add, with the file's existing MSW setup (`features/detail` with `content` = `FILE`, two cases at lines 6 and 9 with automated keys, `latest-results` answering case two failed on `When b` line 10, and a third request-count assertion):

```tsx
test("one card per scenario with its status, Background once", async () => { /* 2 cards (role="article" or the card heading), each with the case key link, the preamble shown once */ });
test("the failed step is red on its card, with the error", async () => { /* card two has .gk-failed on "When b" and a tooltip on focus */ });
test("a Background failure is named on the card", async () => { /* failed_step { text: "Given bg", line: 3 } → card shows "Failed in Background: Given bg"; the preamble has no .gk-failed */ });
test("one latest-results request per 500 cases", async () => { /* 501 cases → 2 POSTs */ });
test("a file stored before raw content: cards from each case's Gherkin, text matching", async () => { /* content null → rebuilt path */ });
```

Write each in full.

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** `splitFeature` and the page:
  - Keys of the feature's cases with an `automated_test_key` → `useQueries`/one `useQuery` that calls `getLatestResults` per batch of 500 and merges `results`.
  - Header: `PageHeader` as today + path + counts by `LastResultPill` status ("3 passed · 1 failed · 2 no runs").
  - Content stored: `splitFeature(content, cases' lines)`; preamble rendered once with `GherkinBlock` (no `failed`); each case → card (`<article className="card scenario-card">`): header row with the case key + title `Link`, `LastResultPill`, the existing `lastRuns(...)` strip; body `GherkinBlock` of the block text, numbered from `block.start` (add an optional `startLine` prop to `GherkinBlock` so the line numbers match the file, if `numbered` is used). Failed line: `locateFailedStep(scenarioSteps(content, case.line), step)` → that step's file line; if it is inside the block → `failed={{ line: fileLine - block.start + 1, tip }}`; if it is in the preamble (Background) → a line on the card `Failed in Background: <step text>` that carries the same tooltip (focusable).
  - Content not stored: the existing rebuilt path supplies each case's Gherkin; each card shows it; failed line by text over `stepLines(gherkin)`.
  - "Scenarios not found in the file" card unchanged; `RunControl` "Run feature" unchanged.
- [ ] **Step 4: Run** both test files, the whole dashboard suite (`--maxWorkers=3`), lint, typecheck, build — PASS.
- [ ] **Step 5: Commit** — `feat(dashboard): feature page as scenario cards with the failed step`

### Task 10: Docs, push, rebuild

**Files:** `docs/SETUP.md`, `collector/README.md` (if not done in Task 5), `PRODUCT.md`, `TODO.md`, `README.md` (Features).

- [ ] **Step 1:** SETUP: what the red step and the pill mean (latest result on any branch; hover/focus for the error; exact line needs collector 0.6.0, older results are matched by text; the outline first-row limit). PRODUCT and README Features: one line each. TODO: item done (date).
- [ ] **Step 2:** Employer-name check (case-insensitive `git grep` prints nothing), full CI mirror, commit `docs: failed step and feature cards`, pull --rebase, push, CI green.
- [ ] **Step 3:** `docker compose up -d --build --wait dashboard gateway`; open a feature page with a failed scenario in the local stack and confirm the red step and tooltip (report what you saw, or why it could not be checked).
