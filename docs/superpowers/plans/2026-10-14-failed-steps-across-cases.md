# Failed Steps Across Test Cases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a Cucumber step fails, show in how many test cases of the run the same step (same step definition) failed, with which errors, and since which run it has been failing.

**Architecture:** The collector (0.8.0) adds the failed step's `definition` (Cucumber `match.location`) and `pattern` (text with matched arguments as `{…}`) to `failed_step`, and retries once without them when an older server refuses them. Ingestion stores both masked (migration 022), keys each failed step by definition or else normalized text, exposes the key on `latest-results`, and answers `GET /projects/{id}/runs/{run_id}/failed-steps` (steps, error-shape groups, streak). The dashboard shows a "Failed steps" section on the run page and a spread line in the failed-step tooltip.

**Tech Stack:** Python 3.9+ stdlib (collector), FastAPI + SQLAlchemy 2.1 + Alembic + pydantic 2 (ingestion, SQLite in tests, PostgreSQL in production), React 19 + TanStack Query + react-router + vitest + msw (dashboard).

**Spec:** `docs/superpowers/specs/2026-10-14-failed-steps-across-cases-design.md` (binding). Builds on `docs/superpowers/specs/2026-10-13-failed-step-and-feature-layout-design.md`.

## Global Constraints

- Work only in the worktree `C:\dev\github\qeos-strip` (branch `failed-steps`). Never touch `C:\dev\github\<org repo checkout>` or `C:\dev\projects\QA-Vision-Platform` (except running the ingestion venv's python, read-only).
- Never write the employer/org name in code, tests, docs, commit messages or examples; use neutral placeholders (`example.com`, `acme.test`, `shop-api`). Existing install URLs that already contain the repository path stay as they are; only version strings change.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Every behaviour commit updates the docs it affects (README.md, PRODUCT.md, DESIGN.md, TECHNICAL_SPECIFICATION.md, SECURITY.md, TODO.md, service READMEs, collector README) in the same commit.
- UI tasks (12, 13): the implementer invokes the `ui-ux-pro-max` skill before editing any dashboard UI, and uses existing CSS tokens only.
- Placeholder text for a matched argument is exactly `{…}` (U+2026 HORIZONTAL ELLIPSIS inside braces); the error-shape placeholder is exactly `…`.
- Lengths (spec §2, §3.1): `definition` 1-500 characters, `pattern` 1-1000 characters; the collector cuts to these, the server rejects longer (422) and replaces NUL/unpaired surrogates (never rejects them).
- Streak window (spec §3.3): at most **50 runs** (this run included) or **90 days**; `tests` per error group at most **50** with `"more": n` beyond.
- Step key: `definition` when present, else the text lowercased with whitespace runs collapsed; `"by": "definition" | "text"`.
- Delivery (spec §7): three phases; each ends with a gate task and a push to `master`. Phase 1 ships before collector 0.8.0 is tagged.
- Pushing: `git fetch origin && git rebase origin/master`, re-run the gate if the rebase brought anything in, then `git push origin <sha>:master` with the explicit SHA that passed the gate. Another session pushes to the same `master`; never force-push.

### Commands used throughout

Run from Git Bash. Define once per shell:

```bash
WT=/c/dev/github/qeos-strip
ING_PY=/c/dev/projects/QA-Vision-Platform/platforms/ingestion-service/.venv/Scripts/python.exe
COL_PY=$WT/collector/.venv/Scripts/python.exe
```

- Ingestion tests: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q <paths>` (the venv imports `src.ingestion` from the current directory, so it tests the worktree; `qeos_shared` comes from the other checkout and is unchanged by this plan).
- Collector venv: the existing collector venv is an editable install of the *other* checkout, so it would test the wrong code. Create one for the worktree once (Task 6, Step 1):
  `cd $WT/collector && python -m venv .venv && .venv/Scripts/python.exe -m pip install -e . pytest cryptography`
  then check `$COL_PY -c "import qeos_collector; print(qeos_collector.__file__)"` prints a path under `qeos-strip`. `.venv/` is already in `collector/.gitignore`.
- Collector tests: `cd $WT/collector && $COL_PY -m pytest -q <paths>`.
- Dashboard: `cd $WT/dashboard && npm run lint && npm run typecheck && npx vitest run && npm run build` (single file: `npx vitest run src/path/file.test.tsx`).

## Review Focus

1. **A part spooled or retried before migration 022 is re-sent after it** (its `failed_step` has no `definition`/`pattern`, the new model dumps them as `null`): it must replay (200), not 409. Test in Task 2 (`test_an_upload_hashed_before_migration_022_still_replays`).
2. **A re-run inside one run** (a test failed, then passed in the same run): the last row wins, so the test is not a failure of this run and must not be listed or counted. Test in Task 10 (`test_a_re_run_that_passed_is_not_a_failed_step`).
3. **The collector is upgraded in the middle of a streak** (earlier rows have only text, later rows have a definition): the streak must not restart at the upgrade. Test in Task 10 (`test_rows_from_before_collector_0_8_count_by_their_text`).
4. **A failing test with no linked case, or only an archived one:** its link on the run page goes to the test's history, never to a broken case URL. Test in Task 12 (`a test without a case links to its history`).
5. **An older server's 422 that is not about `failed_step`, or not JSON, or a part without the fields:** no second request, the error is reported as before. Tests in Task 7 (`test_other_422s_are_not_retried`, `test_a_422_that_is_not_json_is_not_retried`, `test_a_part_without_the_fields_is_not_sent_again`).

## Rulings where the spec is silent

- **R1 Step key format:** `sha256("<by>\0<identity>")` first 16 hex characters, so it is safe in a URL fragment (`#step-<key>`) and short in JSON. `identity` is the definition, or the normalized text.
- **R2 Last row per test:** a test's result in a run is its last row (by row id), as `latest-results` with `run_id` already does. A test whose last row passed is not a failure of that run.
- **R3 Skipped results:** a result `skipped` neither continues nor stops a streak; only runs where at least one of the step's tests `passed`, `failed` or `errored` are walked and counted.
- **R4 Upgrade continuity:** a step keyed by definition also matches earlier rows whose key is the text key of one of the texts it failed with in this run (rows stored before collector 0.8.0).
- **R5 Capped wording:** no new field. The dashboard says "failing for more than 50 runs" when `since.runs >= 50`, otherwise "failing for more than 90 days".
- **R6 `last_passed` with `runs == 1`:** shown after "new in this run" when present ("new in this run · last passed in run #429").
- **R7 Section placement:** the "Failed steps" card goes directly under "Failures by cause" (above Changes / Likely affected), not after the 100-row results table, so it is reachable without paging; it renders nothing until loaded and nothing when the run has no failed step; a failed request shows an Error Banner with Retry inside the card.
- **R8 Tooltip data:** loaded at page level with one `failed-steps` query per distinct run among the page's failed results (TanStack Query shares it, 60 s stale time); with `?run=` that is one request.
- **R9 Case links on the run page:** test keys resolved through `POST /cases/search` (`keys_mode: include`, pages of 200, at most 5), lowest case number wins; archived or unlinked tests link to `/projects/:id/tests/:key`.
- **R10 Response:** the endpoint returns a plain dict (as `latest-results`), so `definition`, `last_passed` and `more` are absent rather than `null`.
- **R11 Example message:** the first line (at most 300 characters, `signature.headline`) of the first message in the group with tests ordered by name; a group without any message has `shape: ""` and `example: null`, shown as "No error message".
- **R12 422 retry:** triggered when any entry of the 422 `detail` list has `"failed_step"` in its `loc` and the body actually holds `definition` or `pattern`; the second request reuses the Idempotency-Key, does not sleep, counts as an attempt, and later 429/5xx retries keep the stripped body.
- **R13 `pattern` always sent:** as the spec states literally (equal to the text when there are no usable arguments), so existing collector test expectations gain `pattern`.
- **R14 Export:** the NDJSON export already writes every column; the new columns are asserted in its test.
- **R15 Branches:** the streak walks runs of every branch of the project (spec §3.3 says "this project"); not narrowed.

## File map

| File | Responsibility | Tasks |
|---|---|---|
| `platforms/ingestion-service/alembic/versions/022_failed_step_definition.py` (create) | columns + partial index | 1 |
| `platforms/ingestion-service/src/ingestion/models/run.py` | model columns, length constants, index | 1 |
| `platforms/ingestion-service/src/ingestion/schemas/collect.py` | `FailedStepIn` new fields, ignore unknown | 2 |
| `platforms/ingestion-service/src/ingestion/service/ingest_service.py` | mask + store, request hash | 2 |
| `platforms/ingestion-service/src/ingestion/jobs/remask.py` | re-mask new columns | 3 |
| `platforms/ingestion-service/src/ingestion/analytics/failed_steps.py` (create) | `step_key`, `step_text_identity` (Task 4), `error_shape` (Task 9) | 4, 9 |
| `platforms/ingestion-service/src/ingestion/service/analytics_service.py` | `failed_step_of` + `latest_results` additions | 4 |
| `platforms/ingestion-service/src/ingestion/service/failed_steps_service.py` (create) | grouping, errors, streak | 10 |
| `platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py` | `GET /{run_id}/failed-steps` | 10 |
| `collector/src/qeos_collector/formats.py` | `definition`, `pattern` | 6 |
| `collector/src/qeos_collector/upload.py`, `cli.py` | 422 retry without the fields | 7 |
| `collector/src/qeos_collector/__init__.py`, `collector/tests/test_package.py` | version 0.8.0 | 8 |
| `dashboard/src/api/runs.ts`, `dashboard/src/api/analytics.ts` | types + fetch | 12, 13 |
| `dashboard/src/lib/failedSteps.ts` (create) | query, texts, case lookup, page hook | 12, 13 |
| `dashboard/src/components/FailedSteps.tsx` (create) | run page section | 12 |
| `dashboard/src/components/FailedStepTip.tsx` | spread line | 13 |
| `dashboard/src/pages/RunDetailPage.tsx`, `CaseEditorPage.tsx`, `FeaturePage.tsx` | wiring | 12, 13 |
| `dashboard/src/test/server.ts` | default `failed-steps` handler | 12 |
| `dashboard/src/index.css` | section + tip styles | 12, 13 |
| `scripts/smoke_gateway.sh` | upload with definition; failed-steps | 2, 11 |

---

# Phase 1 — QEOS accepts and stores the fields

### Task 1: Migration 022 and model columns

**Files:**
- Create: `platforms/ingestion-service/alembic/versions/022_failed_step_definition.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/run.py:83` (constants) and `:108-120` (columns, index)
- Test: `platforms/ingestion-service/tests/unit/test_migration.py` (append)

**Interfaces:**
- Produces: `models.run.FAILED_STEP_DEFINITION_LENGTH = 500`, `models.run.FAILED_STEP_PATTERN_LENGTH = 1000`; `RunResult.failed_step_definition`, `RunResult.failed_step_pattern` (nullable strings); index `ix_test_results_failed_step_definition`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_migration.py`)

```python
def test_failed_step_definition_and_pattern_columns(migrated_engine):
    """Migration 022 (spec 2026-10-14 §3.1)."""
    columns = {c["name"]: c for c in inspect(migrated_engine).get_columns("test_results")}
    assert columns["failed_step_definition"]["type"].length == 500
    assert columns["failed_step_pattern"]["type"].length == 1000
    assert columns["failed_step_definition"]["nullable"] and columns["failed_step_pattern"]["nullable"]
    indexes = {ix["name"]: ix["column_names"] for ix in inspect(migrated_engine).get_indexes("test_results")}
    assert indexes["ix_test_results_failed_step_definition"] == ["failed_step_definition"]
    with migrated_engine.connect() as conn:
        sql = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE name = 'ix_test_results_failed_step_definition'")).scalar()
    assert "FAILED_STEP_DEFINITION IS NOT NULL" in sql.upper()


def test_model_declares_the_definition_index():
    assert "ix_test_results_failed_step_definition" in {ix.name for ix in Base.metadata.tables["test_results"].indexes}


def test_failed_step_definition_downgrade_drops_the_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_022.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "021")
    engine = create_engine(url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("test_results")}
        assert not {"failed_step_definition", "failed_step_pattern"} & columns
        assert "failed_step_text" in columns  # 021 is still there
        assert "ix_test_results_failed_step_definition" not in {
            ix["name"] for ix in inspect(engine).get_indexes("test_results")}
    finally:
        engine.dispose()


def test_failed_step_definition_postgres_path_is_rerunnable(monkeypatch):
    """On PostgreSQL the columns are IF NOT EXISTS and the index is built CONCURRENTLY, IF NOT EXISTS (as 016)."""
    import importlib.util
    from unittest.mock import MagicMock

    spec = importlib.util.spec_from_file_location(
        "m022", SERVICE_ROOT / "alembic" / "versions" / "022_failed_step_definition.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = MagicMock()
    fake.get_bind.return_value.dialect.name = "postgresql"
    monkeypatch.setattr(module, "op", fake)
    module.upgrade()
    executed = " ".join(str(call.args[0]) for call in fake.execute.call_args_list)
    assert "ADD COLUMN IF NOT EXISTS failed_step_definition VARCHAR(500)" in executed
    assert "ADD COLUMN IF NOT EXISTS failed_step_pattern VARCHAR(1000)" in executed
    assert fake.create_index.call_args.kwargs["postgresql_concurrently"] is True
    assert fake.create_index.call_args.kwargs["if_not_exists"] is True
    module.downgrade()
    assert fake.drop_index.call_args.kwargs["postgresql_concurrently"] is True
    assert fake.drop_index.call_args.kwargs["if_exists"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/unit/test_migration.py`
Expected: the four new tests FAIL (KeyError `failed_step_definition` / file not found); `test_migration_columns_match_models` still passes.

- [ ] **Step 3: Write the migration** `alembic/versions/022_failed_step_definition.py`

```python
"""test_results.failed_step_definition / failed_step_pattern: the failed step's step definition and its text with the
matched arguments replaced (spec 2026-10-14 §3.1)

Revision ID: 022
Revises: 021
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None

INDEX = "ix_test_results_failed_step_definition"
WHERE = "failed_step_definition IS NOT NULL"


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    where = {"postgresql_where": sa.text(WHERE), "sqlite_where": sa.text(WHERE)}
    if _postgres():
        # Nullable columns without a default are a metadata-only change. The partial index is built CONCURRENTLY, so
        # uploads are not blocked on a large table (as 016); CONCURRENTLY cannot run in a transaction, and IF NOT EXISTS
        # lets a re-run go through after a failed build
        op.execute("ALTER TABLE test_results ADD COLUMN IF NOT EXISTS failed_step_definition VARCHAR(500)")
        op.execute("ALTER TABLE test_results ADD COLUMN IF NOT EXISTS failed_step_pattern VARCHAR(1000)")
        with op.get_context().autocommit_block():
            op.create_index(INDEX, "test_results", ["failed_step_definition"], postgresql_concurrently=True,
                            if_not_exists=True, **where)
        return
    with op.batch_alter_table("test_results") as batch:
        batch.add_column(sa.Column("failed_step_definition", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("failed_step_pattern", sa.String(length=1000), nullable=True))
    op.create_index(INDEX, "test_results", ["failed_step_definition"], **where)


def downgrade() -> None:
    if _postgres():
        with op.get_context().autocommit_block():
            op.drop_index(INDEX, table_name="test_results", postgresql_concurrently=True, if_exists=True)
        op.execute("ALTER TABLE test_results DROP COLUMN IF EXISTS failed_step_pattern")
        op.execute("ALTER TABLE test_results DROP COLUMN IF EXISTS failed_step_definition")
        return
    op.drop_index(INDEX, table_name="test_results")
    with op.batch_alter_table("test_results") as batch:
        batch.drop_column("failed_step_pattern")
        batch.drop_column("failed_step_definition")
```

- [ ] **Step 4: Add the model columns** in `src/ingestion/models/run.py`

Under `FAILED_STEP_TEXT_LENGTH = 1000` add:

```python
FAILED_STEP_DEFINITION_LENGTH = 500
FAILED_STEP_PATTERN_LENGTH = 1000
```

After `failed_step_line = Column(...)` add:

```python
    # From collector 0.8.0 (spec 2026-10-14): the step definition that ran the step (Cucumber match.location) and the
    # step text with its matched arguments as {…}; both masked like the text
    failed_step_definition = Column(String(FAILED_STEP_DEFINITION_LENGTH), nullable=True)
    failed_step_pattern = Column(String(FAILED_STEP_PATTERN_LENGTH), nullable=True)
```

Append to `__table_args__` (after `ix_test_results_failing`):

```python
        # Migration 022: failed steps across test cases look rows up by step definition
        Index("ix_test_results_failed_step_definition", "failed_step_definition",
              postgresql_where=text("failed_step_definition IS NOT NULL"),
              sqlite_where=text("failed_step_definition IS NOT NULL")),
```

- [ ] **Step 5: Run the migration tests and the whole unit folder**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/unit`
Expected: PASS (including `test_migration_columns_match_models`).

- [ ] **Step 6: Commit**

```bash
cd $WT && git add platforms/ingestion-service/alembic/versions/022_failed_step_definition.py \
  platforms/ingestion-service/src/ingestion/models/run.py platforms/ingestion-service/tests/unit/test_migration.py
git commit -m "feat(ingestion): migration 022, the failed step's definition and pattern columns

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Upload accepts, masks and stores `definition` and `pattern`; unknown fields ignored

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/schemas/collect.py:99-107`
- Modify: `platforms/ingestion-service/src/ingestion/service/ingest_service.py:15` (import), `:69-79` (`_request_hash`), `:180-204` (rows)
- Modify: `scripts/smoke_gateway.sh` (after the masking block, before `# ---- analytics, through the gateway's overlap route ----`)
- Modify docs: `platforms/ingestion-service/README.md:91` and `:127`, `TECHNICAL_SPECIFICATION.md:136` and `:199`, `SECURITY.md:118-122`, `TODO.md` (new open item)
- Test: `platforms/ingestion-service/tests/unit/test_collect_schema.py:128-139`, `platforms/ingestion-service/tests/integration/test_collect_failed_step.py` (append)

**Interfaces:**
- Consumes: Task 1 constants and columns.
- Produces: `FailedStepIn.definition: Optional[str]`, `FailedStepIn.pattern: Optional[str]` (extra fields ignored); stored masked in `failed_step_definition` / `failed_step_pattern`. Smoke variables `STEP_RUN_ID` (the run id of the smoke upload) for Task 11.

- [ ] **Step 1: Update the schema tests** (`tests/unit/test_collect_schema.py`): replace the parametrized invalid test and add two tests

```python
@pytest.mark.parametrize("step", [{"text": ""}, {"text": "x" * 1001}, {"text": "x", "line": 0},
                                  {"text": "x", "line": 1_000_001}, {"text": "x", "definition": ""},
                                  {"text": "x", "definition": "d" * 501}, {"text": "x", "pattern": ""},
                                  {"text": "x", "pattern": "p" * 1001}])
def test_invalid_failed_step_is_rejected(step):
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "failed_step": step}]))


def test_failed_step_definition_and_pattern_are_optional_free_text():
    step = {"text": "When I search Lisbon", "definition": "steps/search.js:12\x00", "pattern": "When I search {…}"}
    parsed = RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "failed_step": step}]))
    got = parsed.results[0].failed_step
    assert got.definition == "steps/search.js:12\ufffd" and got.pattern == "When I search {…}"
    plain = RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "failed_step": {"text": "x"}}]))
    assert plain.results[0].failed_step.definition is None and plain.results[0].failed_step.pattern is None


def test_unknown_failed_step_fields_are_ignored():
    """Forward compatibility (spec 2026-10-14 §3.1): a newer collector's field never costs the upload."""
    step = {"text": "When x", "line": 3, "hook": "before", "location": {"uri": "f.feature"}}
    parsed = RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "failed_step": step}]))
    assert parsed.results[0].failed_step.model_dump() == {"text": "When x", "line": 3, "definition": None, "pattern": None}
```

(`_UNSTORABLE` replaces with U+FFFD; check the replacement character in `_replace_unstorable` if the assertion differs and use exactly that character.)

- [ ] **Step 2: Add the integration tests** (append to `tests/integration/test_collect_failed_step.py`)

```python
DEFINITION = "features/step_definitions/search.js:12"


def test_definition_and_pattern_are_stored(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "search", "status": "failed", "message": "boom", "failed_step": {
        "text": "When I search Lisbon", "line": 14, "definition": DEFINITION, "pattern": "When I search {…}"}}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    row = db.query(RunResult).one()
    assert (row.failed_step_definition, row.failed_step_pattern) == (DEFINITION, "When I search {…}")


def test_definition_and_pattern_are_masked(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "login", "status": "failed", "failed_step": {
        "text": "When I log in", "definition": f"steps/login.js:3 {TOKEN}", "pattern": f'When I use "{TOKEN}"'}}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    row = db.query(RunResult).one()
    assert TOKEN not in row.failed_step_definition and TOKEN not in row.failed_step_pattern
    assert "[REDACTED:github_token]" in row.failed_step_definition and row.redacted is True


def test_unknown_failed_step_fields_are_ignored_on_upload(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "t", "status": "failed",
                                 "failed_step": {"text": "When x", "line": 2, "from_a_newer_collector": True}}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    assert db.query(RunResult).one().failed_step_text == "When x"


def test_an_upload_hashed_before_migration_022_still_replays(client, make_key):
    """A part stored before the upgrade, resent after it: its failed_step has no definition or pattern."""
    from src.ingestion.schemas.collect import RunUpload
    from src.ingestion.service import ingest_service

    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "t", "status": "failed", "failed_step": {"text": "When x", "line": 2}}])
    first = client.post(URL, json=body, headers=key_headers(key, idem="k-022"))
    explicit = upload_body(results=[{"name": "t", "status": "failed", "failed_step": {
        "text": "When x", "line": 2, "definition": None, "pattern": None}}])
    explicit["run"] = body["run"]
    again = client.post(URL, json=explicit, headers=key_headers(key, idem="k-022"))
    assert (first.status_code, again.status_code) == (201, 200)
    assert ingest_service._request_hash(RunUpload.model_validate(body)) == \
        ingest_service._request_hash(RunUpload.model_validate(explicit))


def test_the_definition_is_part_of_the_request_hash(client, make_key):
    import copy

    _, key = make_key(project_id=1)
    first = upload_body(results=[{"name": "t", "status": "failed",
                                  "failed_step": {"text": "When a", "definition": "a.js:1"}}])
    second = copy.deepcopy(first)  # the same run times: only the definition differs
    second["results"][0]["failed_step"]["definition"] = "b.js:1"
    assert client.post(URL, json=first, headers=key_headers(key, idem="k-def")).status_code == 201
    assert client.post(URL, json=first, headers=key_headers(key, idem="k-def")).status_code == 200
    assert client.post(URL, json=second, headers=key_headers(key, idem="k-def")).status_code == 409
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/unit/test_collect_schema.py tests/integration/test_collect_failed_step.py`
Expected: FAIL (422 extra_forbidden on `definition`, `AttributeError: definition`).

- [ ] **Step 4: Change the schema** (`schemas/collect.py`, replace class `FailedStepIn`)

```python
class FailedStepIn(BaseModel):
    """The Cucumber step that failed (spec 2026-10-13 §2), and from collector 0.8.0 its step definition and its text
    with the matched arguments as {…} (spec 2026-10-14 §3.1). Unknown fields are ignored, not refused: a newer
    collector's addition must never cost the upload."""
    model_config = ConfigDict(extra="ignore")

    text: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    line: Optional[int] = Field(None, ge=1, le=1_000_000)
    definition: Optional[Annotated[str, StringConstraints(min_length=1, max_length=500)]] = None
    pattern: Optional[Annotated[str, StringConstraints(min_length=1, max_length=1000)]] = None

    # Free text like message/details: replaced, never rejected
    _clean_text = field_validator("text", "definition", "pattern", mode="after")(_replace_unstorable)
```

- [ ] **Step 5: Store, mask and hash** (`service/ingest_service.py`)

Import line 15 becomes:

```python
from src.ingestion.models.run import (
    FAILED_STEP_DEFINITION_LENGTH, FAILED_STEP_PATTERN_LENGTH, FAILED_STEP_TEXT_LENGTH, FULL_SCOPE,
)
```

In `_request_hash`, replace the loop over results with:

```python
    # Result fields added by migrations 021 and 022: absent from the hash while null, for the same reason
    for result in data["results"]:
        step = result.get("failed_step")
        if step is None:
            result.pop("failed_step", None)
            continue
        for name in ("definition", "pattern"):
            if step.get(name) is None:
                step.pop(name, None)
```

In the results loop of `ingest`, replace the `step_text, step_kinds = …` and `kinds = …` lines with:

```python
            step = result.failed_step
            step_text, step_kinds = mask(step.text if step else None, patterns)
            step_definition, definition_kinds = mask(step.definition if step else None, patterns)
            step_pattern, pattern_kinds = mask(step.pattern if step else None, patterns)
            kinds = message_kinds | details_kinds | step_kinds | definition_kinds | pattern_kinds
```

and in the row dict, after `"failed_step_line": …`, add:

```python
                "failed_step_definition": (step_definition[:FAILED_STEP_DEFINITION_LENGTH]
                                           if step_definition is not None else None),
                "failed_step_pattern": step_pattern[:FAILED_STEP_PATTERN_LENGTH] if step_pattern is not None else None,
```

- [ ] **Step 6: Run the tests**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/unit/test_collect_schema.py tests/integration/test_collect_failed_step.py tests/integration/test_collect_endpoint.py tests/integration/test_masking_on_ingest.py`
Expected: PASS.

- [ ] **Step 7: Smoke check** — in `scripts/smoke_gateway.sh`, after the `body_lacks "... the token itself is not stored" "$FAKE_TOKEN"` line, add:

```bash

# ---- failed steps: the step definition and pattern from collector 0.8.0 (spec 2026-10-14) ----
STEP_BODY="{\"run\":{\"ci_provider\":\"local\",\"branch\":\"smoke-step\",\"started_at\":\"$NOW\",\"finished_at\":\"$NOW\"},\"results\":[{\"name\":\"step-fails\",\"status\":\"failed\",\"message\":\"Invalid city 'Lisb0n'\",\"failed_step\":{\"text\":\"When I search Lisb0n\",\"line\":4,\"definition\":\"features/step_definitions/search.js:12\",\"pattern\":\"When I search {\\u2026}\",\"from_a_newer_collector\":1}}]}"
check "upload a failed step with its definition (and a field from a newer collector)" 201 POST "$BASE/api/v1/collect/runs" \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "$STEP_BODY"
STEP_RUN_ID="$(grep -o '"id":[0-9]*' "$TMP/body" | head -1 | cut -d: -f2)"
```

(Task 4 adds the `latest-results` check, Task 11 the `failed-steps` check, both right after this block.)

- [ ] **Step 8: Docs**

- `platforms/ingestion-service/README.md` line 91 (Limits), replace the `failed_step` bullet with:
  `- A result may carry `failed_step` `{"text": 1-1000 characters, "line": 1-1,000,000, "definition": 1-500, "pattern": 1-1000}` (the Gherkin step that failed, sent by collector 0.6.0 and later; `definition` and `pattern` from 0.8.0). They are stored in `failed_step_text`, `failed_step_line` (migration 021), `failed_step_definition` and `failed_step_pattern` (migration 022), the text fields after masking. Out-of-range values are `422`; unknown fields inside `failed_step` are ignored (a newer collector's additions never cost the upload); omitting it is fine.`
- Same README line 127: `message`, `details` and `failed_step.text` → `message`, `details` and the failed step's `text`, `definition` and `pattern`.
- `TECHNICAL_SPECIFICATION.md:136`: `` `failed_step` `{text 1-1000, line 1-1,000,000}` is stored masked`` → `` `failed_step` `{text 1-1000, line 1-1,000,000, definition 1-500, pattern 1-1000}` is stored masked; unknown fields in it are ignored``; line 199: `` `failed_step_text`/`failed_step_line` masked`` → `` `failed_step_text`/`failed_step_line`/`failed_step_definition`/`failed_step_pattern` (text fields masked; partial index on the definition)``.
- `SECURITY.md` Masking bullet, append: ` The failed Cucumber step's text, step definition and pattern are masked the same way, at upload and by the re-mask job.`
- `TODO.md`: after the "Failed step on scenarios" line add
  `- [ ] Failed steps across test cases (spec `docs/superpowers/specs/2026-10-14-failed-steps-across-cases-design.md`, plan `docs/superpowers/plans/2026-10-14-failed-steps-across-cases.md`): phase 1 server (migration 022, `failed_step.definition`/`pattern` stored masked, unknown `failed_step` fields ignored); phase 2 collector 0.8.0; phase 3 `failed-steps` endpoint, run page section, tooltip line.`

- [ ] **Step 9: Commit**

```bash
cd $WT && git add platforms/ingestion-service scripts/smoke_gateway.sh TECHNICAL_SPECIFICATION.md SECURITY.md TODO.md
git commit -m "feat(ingestion): store the failed step's definition and pattern, masked; unknown failed_step fields ignored

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Re-mask job and export cover the new columns

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/jobs/remask.py:21` (import), `:68-80`
- Modify docs: `platforms/ingestion-service/README.md:154` (re-mask) and `:238` (export)
- Test: `platforms/ingestion-service/tests/integration/test_remask_job.py` (fixture + new test), `tests/integration/test_export.py:27,60`

**Interfaces:**
- Consumes: Task 1 constants/columns.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_remask_job.py`, extend the `add_run` fixture signature and row creation:

```python
    def _add(project_id=1, results=(), ci_run_url=None, failed_steps=None, definitions=None, patterns=None):
        ...
            db.add(RunResult(run_id=run.id, test_key=f"{i:064d}", name=f"t{i}", status="failed",
                             duration_ms=1, message=message, details=details,
                             failed_step_text=(failed_steps or {}).get(i),
                             failed_step_definition=(definitions or {}).get(i),
                             failed_step_pattern=(patterns or {}).get(i)))
```

and append:

```python
def test_step_definition_and_pattern_are_masked(db, session_factory, add_run, capsys):
    run_id = add_run(results=[("plain", None)], failed_steps={0: "When I log in"},
                     definitions={0: f"steps/login.js:3 {SECRET}"}, patterns={0: f"When I use {SECRET}"})
    run_job(session_factory)
    row = results(db, run_id)[0]
    assert SECRET not in row.failed_step_definition and SECRET not in row.failed_step_pattern
    assert row.failed_step_text == "When I log in" and row.redacted is True
    assert summary(capsys)["kinds"] == {"github_token": 1}


def test_masking_that_lengthens_the_definition_is_cut_to_its_column(db, session_factory, add_run):
    from src.ingestion.models.run import FAILED_STEP_DEFINITION_LENGTH

    run_id = add_run(results=[("plain", None)], definitions={0: "x" * 480 + f" {SECRET}"})
    run_job(session_factory)
    assert len(results(db, run_id)[0].failed_step_definition) <= FAILED_STEP_DEFINITION_LENGTH
```

In `tests/integration/test_export.py`, the failing `RunResult(...)` of the `stored` fixture gains `failed_step_definition="steps/login.js:3", failed_step_pattern="When I log in"`, and after the existing `failed_step_text` assertion add:

```python
    assert (results[1]["failed_step_definition"], results[1]["failed_step_pattern"]) == ("steps/login.js:3", "When I log in")
    assert results[0]["failed_step_definition"] is None and results[0]["failed_step_pattern"] is None
```

- [ ] **Step 2: Run to verify the re-mask tests fail**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/integration/test_remask_job.py tests/integration/test_export.py`
Expected: the two re-mask tests FAIL (secret still present); export passes already (R14).

- [ ] **Step 3: Implement** (`jobs/remask.py`)

Import line 21:

```python
from src.ingestion.models.run import FAILED_STEP_DEFINITION_LENGTH, FAILED_STEP_PATTERN_LENGTH, FAILED_STEP_TEXT_LENGTH
```

Replace lines 70-80 (from `step, step_changed, step_cut = …` to `row.truncated = …`) with:

```python
            step, step_changed, step_cut = _remask_text(row.failed_step_text, patterns, row_kinds)
            definition, definition_changed, definition_cut = _remask_text(row.failed_step_definition, patterns, row_kinds)
            pattern, pattern_changed, pattern_cut = _remask_text(row.failed_step_pattern, patterns, row_kinds)
            if not (message_changed or details_changed or step_changed or definition_changed or pattern_changed):
                continue
            changed += 1
            # A result counts once per kind, the way ingest's metrics count it
            kinds.update({kind: 1 for kind in row_kinds})
            if not dry_run:
                row.message, row.details = message, details
                row.failed_step_text = step[:FAILED_STEP_TEXT_LENGTH] if step is not None else None
                row.failed_step_definition = (definition[:FAILED_STEP_DEFINITION_LENGTH]
                                              if definition is not None else None)
                row.failed_step_pattern = pattern[:FAILED_STEP_PATTERN_LENGTH] if pattern is not None else None
                row.redacted = True
                row.truncated = (row.truncated or message_cut or details_cut or step_cut
                                 or definition_cut or pattern_cut)
```

- [ ] **Step 4: Run the tests**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/integration/test_remask_job.py tests/integration/test_export.py`
Expected: PASS.

- [ ] **Step 5: Docs** — ingestion README line 154: `(message, details and the failed step text; …` → `(message, details and the failed step's text, definition and pattern; …`; line 238: `(`type: result`, with `failed_step_text` and `failed_step_line`)` → `(`type: result`, with `failed_step_text`, `failed_step_line`, `failed_step_definition` and `failed_step_pattern`)`.

- [ ] **Step 6: Commit**

```bash
cd $WT && git add platforms/ingestion-service
git commit -m "feat(ingestion): re-mask job and export cover the failed step's definition and pattern

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Step key; `latest-results` gains `definition`, `pattern` and `key`

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/analytics/failed_steps.py`
- Modify: `platforms/ingestion-service/src/ingestion/service/analytics_service.py:310-347`
- Modify: `scripts/smoke_gateway.sh` (after the Task 2 block)
- Modify docs: `platforms/ingestion-service/README.md:255` (`POST /latest-results` row)
- Test: create `platforms/ingestion-service/tests/unit/test_failed_steps_identity.py`; modify `tests/unit/test_failed_step_of.py`, `tests/integration/test_latest_results.py:22,83`

**Interfaces:**
- Produces (later tasks rely on these exact names):
  - `analytics.failed_steps.step_text_identity(text: str) -> str`
  - `analytics.failed_steps.step_key(definition: Optional[str], text: str) -> tuple[str, str]` returning `(key, by)`, `by in ("definition", "text")`, key = 16 lowercase hex
  - `analytics_service.failed_step_of(status, message, details, step_text, step_line, definition=None, pattern=None) -> Optional[dict]` returning `{"text", "line"?, "definition"?, "pattern"?, "key"}`
  - `latest-results` entries: `failed_step` `{text, line?, definition?, pattern?, key}`

- [ ] **Step 1: Write the failing unit tests** `tests/unit/test_failed_steps_identity.py`

```python
"""A failed step is its step definition, else its text (spec 2026-10-14 §3.2)."""
import re

from src.ingestion.analytics.failed_steps import step_key, step_text_identity


def test_one_definition_is_one_step_whatever_the_parameters():
    lisbon = step_key("steps/search.js:12", "When I search Lisbon")
    porto = step_key("steps/search.js:12", "When I search Porto")
    assert lisbon == porto and lisbon[1] == "definition"


def test_without_a_definition_the_text_is_compared_without_case_or_extra_spaces():
    assert step_key(None, "When I  search\tLisbon ")[0] == step_key("", "when i search lisbon")[0]
    assert step_key(None, "When I search Lisbon")[1] == "text"
    assert step_key(None, "When I search Lisbon")[0] != step_key(None, "When I search Porto")[0]


def test_a_definition_and_a_text_never_share_a_key():
    assert step_key("When I search Lisbon", "x")[0] != step_key(None, "When I search Lisbon")[0]


def test_the_key_is_short_hex_safe_in_a_url_fragment():
    assert re.fullmatch(r"[0-9a-f]{16}", step_key("steps/search.js:12", "x")[0])


def test_identity_collapses_whitespace_and_lowercases():
    assert step_text_identity("  When I   SEARCH\nLisbon ") == "when i search lisbon"
```

Replace the body of `tests/unit/test_failed_step_of.py` with:

```python
from src.ingestion.analytics.failed_steps import step_key
from src.ingestion.service.analytics_service import failed_step_of


def key(definition, text):
    return step_key(definition, text)[0]


def test_stored_step_wins():
    assert failed_step_of("failed", "boom", "When x\nboom", "When I search", 14) == {
        "text": "When I search", "line": 14, "key": key(None, "When I search")}


def test_definition_and_pattern_come_with_the_step_and_make_its_key():
    got = failed_step_of("failed", "boom", None, "When I search Lisbon", 14, "steps/search.js:12", "When I search {…}")
    assert got == {"text": "When I search Lisbon", "line": 14, "definition": "steps/search.js:12",
                   "pattern": "When I search {…}", "key": key("steps/search.js:12", "When I search Lisbon")}


def test_old_rows_take_the_first_details_line_when_it_is_not_the_message():
    assert failed_step_of("failed", "boom", "When I search Lisbon\nboom\n  at x", None, None) == {
        "text": "When I search Lisbon", "key": key(None, "When I search Lisbon")}


def test_no_step_when_details_starts_with_the_message():
    assert failed_step_of("failed", "boom", "boom\n  at x", None, None) is None


def test_errored_counts_and_passed_never_has_a_step():
    assert failed_step_of("errored", None, "Given y\nE", None, None) == {"text": "Given y", "key": key(None, "Given y")}
    assert failed_step_of("passed", None, None, "When x", 3) is None
    assert failed_step_of("failed", None, None, None, None) is None
```

- [ ] **Step 2: Update and add integration tests** (`tests/integration/test_latest_results.py`)

Add `from src.ingestion.analytics.failed_steps import step_key` to the imports. In `test_latest_on_any_branch_with_the_failed_step` the step assertion becomes
`assert got["failed_step"] == {"text": "When I search Lisbon", "line": 14, "key": step_key(None, "When I search Lisbon")[0]} and got["message"] == "boom"`;
in `test_run_id_gives_each_test_its_result_in_that_run`,
`assert got[search]["failed_step"] == {"text": "When I search Lisbon", "line": 14, "key": step_key(None, "When I search Lisbon")[0]}`. Append:

```python
def test_the_step_definition_and_pattern_and_key_come_with_the_failed_step(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0, results=(("search", "failed", 5),))
    row = db.query(RunResult).filter_by(run_id=run.id).one()
    row.failed_step_text, row.failed_step_line = "When I search Lisbon", 14
    row.failed_step_definition, row.failed_step_pattern = "steps/search.js:12", "When I search {…}"
    db.commit()
    key = report_key("search")
    got = client.post(URL, json={"keys": [key]}, headers=auth()).json()["results"][key]["failed_step"]
    assert got == {"text": "When I search Lisbon", "line": 14, "definition": "steps/search.js:12",
                   "pattern": "When I search {…}", "key": step_key("steps/search.js:12", "When I search Lisbon")[0]}
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/unit/test_failed_steps_identity.py tests/unit/test_failed_step_of.py tests/integration/test_latest_results.py`
Expected: FAIL (`ModuleNotFoundError: src.ingestion.analytics.failed_steps`).

- [ ] **Step 4: Create** `src/ingestion/analytics/failed_steps.py`

```python
"""Which failed steps are one step (spec 2026-10-14 §3.2).

A step is its step definition, the code that runs it, when the collector reported one (0.8.0 and later): `When I
search Lisbon` and `When I search Porto` are one step with other parameters. Without one, the step text is the
identity, compared without case and with runs of whitespace collapsed. The key is a short hash of either, safe in a
URL fragment (the run page's `#step-<key>`)."""
import hashlib
from typing import Optional, Tuple

KEY_LENGTH = 16


def step_text_identity(text: str) -> str:
    return " ".join(text.split()).lower()


def step_key(definition: Optional[str], text: str) -> Tuple[str, str]:
    """(key, by), `by` being "definition" or "text"."""
    by, identity = ("definition", definition) if definition else ("text", step_text_identity(text))
    return hashlib.sha256(f"{by}\0{identity}".encode("utf-8")).hexdigest()[:KEY_LENGTH], by
```

- [ ] **Step 5: Extend `failed_step_of` and `latest_results`** (`service/analytics_service.py`)

Add the import `from src.ingestion.analytics.failed_steps import step_key` and replace `failed_step_of`:

```python
def failed_step_of(status, message, details, step_text, step_line, definition=None, pattern=None) -> Optional[dict]:
    """The failed step for a failed/errored result (spec 2026-10-13 §3.3). Rows stored before the collector
    sent `failed_step` hold the step on details' first line, unless that line is just the message. From collector
    0.8.0 the step also has its definition and pattern; `key` names the step across test cases (spec 2026-10-14)."""
    if status not in ("failed", "errored"):
        return None
    if step_text:
        step = {"text": step_text, **({"line": step_line} if step_line else {})}
    else:
        first = (details or "").split("\n", 1)[0].strip()
        if not first or first == (message or "").split("\n", 1)[0].strip():
            return None
        step = {"text": first}
    if definition:
        step["definition"] = definition
    if pattern:
        step["pattern"] = pattern
    step["key"] = step_key(definition, step["text"])[0]
    return step
```

In `latest_results`, the `_latest_ranked(...)` column list gains `RunResult.failed_step_definition, RunResult.failed_step_pattern,` after `RunResult.failed_step_line,`, and the call becomes:

```python
        step = failed_step_of(r["status"], r["message"], r["details"], r["failed_step_text"], r["failed_step_line"],
                              r["failed_step_definition"], r["failed_step_pattern"])
```

- [ ] **Step 6: Run the tests**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/unit tests/integration/test_latest_results.py`
Expected: PASS.

- [ ] **Step 7: Smoke** — append after the Task 2 smoke block:

```bash
check "analytics tests finds the failed step's test" 200 GET "$BASE/api/v1/projects/$PROJECT_ID/analytics/tests?search=step-fails" "${AUTH[@]}"
STEP_KEY="$(sed -n 's/.*"test_key":"\([0-9a-f]\{64\}\)".*/\1/p' "$TMP/body" | head -1)"
check "latest-results -> the failed step's definition and key" 200 POST \
  "$BASE/api/v1/projects/$PROJECT_ID/analytics/latest-results" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"keys\":[\"${STEP_KEY:-0000000000000000000000000000000000000000000000000000000000000000}\"]}"
body_has "... with the step definition" '"definition":"features/step_definitions/search.js:12"'
body_has "... and the step key" '"key":"'
```

- [ ] **Step 8: Docs** — ingestion README `POST /latest-results` row: `{status, run_id, branch, environment, started_at, message, failed_step?}` → `{status, run_id, branch, environment, started_at, message, failed_step?}` where `failed_step` is `{text, line?, definition?, pattern?, key}` — add after the first sentence: `` `failed_step.key` names the step across test cases (its definition, else its text without case or extra spaces) and matches a row of `GET /projects/{id}/runs/{run_id}/failed-steps` (spec 2026-10-14). ``

- [ ] **Step 9: Commit**

```bash
cd $WT && git add platforms/ingestion-service scripts/smoke_gateway.sh
git commit -m "feat(ingestion): latest-results gives the failed step's definition, pattern and step key

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Phase 1 gate and push

**Files:** none (verification only; fix-ups go in their own commits).

- [ ] **Step 1: Ingestion suite**: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q` → all pass.
- [ ] **Step 2: Collector suite** (unchanged, proves nothing broke): create the collector venv now if Task 6 has not (see Commands) and run `cd $WT/collector && $COL_PY -m pytest -q` → all pass.
- [ ] **Step 3: Dashboard**: `cd $WT/dashboard && npm run lint && npm run typecheck && npx vitest run && npm run build && node --test ../templates/github/qeos-run.test.mjs` → all pass.
- [ ] **Step 4: Architecture docs**: `cd $WT && python scripts/check_architecture_docs.py && python -m pytest scripts/tests -q` → no findings, pass.
- [ ] **Step 5: Gateway smoke** (needs Docker Desktop running): `cd $WT && export SECRET_KEY=smoke INTERNAL_API_PASSWORD=smoke && docker compose up -d --build --wait --wait-timeout 300 gateway && bash scripts/smoke_gateway.sh; docker compose down --volumes`. Expected: no `FAIL` lines. If Docker is not available, say so in the report and rely on CI's "Gateway and full stack" job in Step 7.
- [ ] **Step 6: Rebase and push**: `git fetch origin && git rebase origin/master` (re-run Steps 1-4 if anything came in), then `SHA=$(git rev-parse HEAD) && git push origin $SHA:master`.
- [ ] **Step 7: Watch CI**: `gh run list --branch master --limit 3` then `gh run watch <id> --exit-status` for the CI run of `$SHA`. Phase 2 starts only when it is green (the server must accept the fields before collector 0.8.0 exists).

---

# Phase 2 — Collector 0.8.0

### Task 6: Collector sends `definition` and `pattern`

**Files:**
- Modify: `collector/src/qeos_collector/formats.py:92-186`
- Modify docs: `collector/README.md:522-524`
- Test: `collector/tests/test_cucumber.py:114-180` (update five expectations, add tests)

**Interfaces:**
- Produces: result rows whose `failed_step` is `{"text", "line"?, "definition"?, "pattern"}`; module helpers `_step_definition(step: dict) -> Optional[str]`, `_step_pattern(step: dict, keyword: str, name: str) -> str`, constant `ARGUMENT = "{…}"`.

- [ ] **Step 1: Create the worktree collector venv** (see Commands) and confirm `$COL_PY -m pytest -q tests/test_package.py` passes.

- [ ] **Step 2: Update existing expectations** in `tests/test_cucumber.py` (R13: `pattern` is always present, equal to the text without arguments):
  - `test_failed_step_carries_text_and_line`: `{"text": "When I search Lisbon", "line": 5, "pattern": "When I search Lisbon"}`
  - `test_background_step_failure_keeps_its_own_line`: `{"text": "Given logged in", "line": 3, "pattern": "Given logged in"}`
  - `test_missing_line_keeps_the_text_and_long_text_is_cut`: add `and rows[0]["failed_step"]["pattern"] == ("When " + "y" * 2000)[:1000]`
  - `test_implausible_line_numbers_are_dropped_but_text_is_kept`: `{"text": "When x", "pattern": "When x"}`
  - `test_outline_row_failure_reports_the_template_line`: `{"text": "When I pay 5", "line": 9, "pattern": "When I pay 5"}`

- [ ] **Step 3: Add the new tests** (after `test_outline_row_failure_reports_the_template_line`)

```python
def matched(keyword, name, line, status, error=None, location=None, arguments=None):
    entry = step(keyword, name, line, status, error)
    match = {}
    if location is not None:
        match["location"] = location
    if arguments is not None:
        match["arguments"] = arguments
    entry["match"] = match
    return entry


def failed_step_of(tmp_path, *args, **kwargs):
    return parse_cucumber(tmp_path, steps=[matched(*args, **kwargs)])[0]["failed_step"]


def test_cucumber_js_reports_the_definition_without_arguments(tmp_path):
    # cucumber-js's json formatter: match.location only
    got = failed_step_of(tmp_path, "When ", "I search Lisbon", 5, "failed", "boom",
                         location="features/step_definitions/search.js:12")
    assert got == {"text": "When I search Lisbon", "line": 5,
                   "definition": "features/step_definitions/search.js:12", "pattern": "When I search Lisbon"}


def test_cucumber_jvm_arguments_become_placeholders(tmp_path):
    got = failed_step_of(tmp_path, "When ", "I search Lisbon in 2 days", 5, "failed", "boom",
                         location="com.example.SearchSteps.search(java.lang.String,int)",
                         arguments=[{"val": "Lisbon", "offset": 9}, {"val": "2", "offset": 19}])
    assert got["definition"] == "com.example.SearchSteps.search(java.lang.String,int)"
    assert got["pattern"] == "When I search {…} in {…} days"


def test_ruby_arguments_in_any_order_become_placeholders(tmp_path):
    got = failed_step_of(tmp_path, "Then ", 'I see "Porto" first', 8, "failed", "e",
                         location="features/step_definitions/search_steps.rb:3",
                         arguments=[{"offset": 6, "val": '"Porto"'}])
    assert got["pattern"] == "Then I see {…} first"


def test_an_optional_group_that_matched_nothing_is_skipped(tmp_path):
    got = failed_step_of(tmp_path, "When ", "I search Porto", 5, "failed", "e", location="s.js:1",
                         arguments=[{"val": None, "offset": None}, {"val": "Porto", "offset": 9}])
    assert got["pattern"] == "When I search {…}"


def test_no_match_gives_no_definition_and_the_text_as_pattern(tmp_path):
    rows = parse_cucumber(tmp_path, steps=[step("When ", "I search Lisbon", 5, "failed", "boom")])
    assert "definition" not in rows[0]["failed_step"] and rows[0]["failed_step"]["pattern"] == "When I search Lisbon"


def test_a_blank_or_odd_location_gives_no_definition(tmp_path):
    for location in ("", "   ", 12, ["a"]):
        got = failed_step_of(tmp_path, "When ", "x", 5, "failed", "e", location=location)
        assert "definition" not in got, location


def test_a_long_location_is_cut_to_500(tmp_path):
    got = failed_step_of(tmp_path, "When ", "x", 5, "failed", "e", location="d" * 800)
    assert got["definition"] == "d" * 500


@pytest.mark.parametrize("arguments", [
    [{"val": "Lisbon", "offset": 3}],               # does not fit the text there
    [{"val": "Lisbon", "offset": -1}],
    [{"val": "Lisbon", "offset": True}],
    [{"val": "Lisbon", "offset": "9"}],
    [{"val": 7, "offset": 9}],
    ["Lisbon"],
    [{"val": "search Lisbon", "offset": 2}, {"val": "Lisbon", "offset": 9}],  # overlapping
    {"val": "Lisbon", "offset": 9},                 # not a list
])
def test_bad_arguments_leave_the_text_as_pattern(tmp_path, arguments):
    got = failed_step_of(tmp_path, "When ", "I search Lisbon", 5, "failed", "e", location="s.js:1", arguments=arguments)
    assert got["pattern"] == "When I search Lisbon"


def test_a_long_pattern_is_cut_to_1000(tmp_path):
    name = "I type " + "y" * 2000
    got = failed_step_of(tmp_path, "When ", name, 5, "failed", "e", location="s.js:1",
                         arguments=[{"val": "y" * 2000, "offset": 7}])
    assert got["pattern"] == "When I type {…}"
    long = failed_step_of(tmp_path, "When ", name, 5, "failed", "e", location="s.js:1", arguments=[])
    assert len(long["pattern"]) == 1000
```

(Add `import pytest` at the top of the file if it is not imported yet.)

- [ ] **Step 4: Run to verify they fail**

Run: `cd $WT/collector && $COL_PY -m pytest -q tests/test_cucumber.py`
Expected: FAIL (no `pattern` / `definition` keys).

- [ ] **Step 5: Implement** in `formats.py`. After `_CUCUMBER_UNDECIDED = …` add:

```python
# The failed step's step definition and its text with the matched arguments replaced (spec 2026-10-14 §2)
ARGUMENT = "{…}"
DEFINITION_LENGTH = 500
STEP_TEXT_LENGTH = 1000


def _step_definition(step: dict) -> Optional[str]:
    """match.location: the code that ran the step (a file:line, or a method for cucumber-jvm)."""
    match = step.get("match")
    location = match.get("location") if isinstance(match, dict) else None
    if not isinstance(location, str) or not location.strip():
        return None
    return location.strip()[:DEFINITION_LENGTH]


def _step_pattern(step: dict, keyword: str, name: str) -> str:
    """The step text with each match.arguments value (offsets into the name, after the keyword) replaced by {…}; the
    text itself when there are no arguments or they do not fit the text."""
    text = f"{keyword}{name}".strip()[:STEP_TEXT_LENGTH]
    match = step.get("match")
    arguments = match.get("arguments") if isinstance(match, dict) else None
    if not isinstance(arguments, list):
        return text
    spans = []
    for argument in arguments:
        if not isinstance(argument, dict):
            return text
        value, offset = argument.get("val"), argument.get("offset")
        if value is None or value == "":
            continue  # an optional group that matched nothing
        if (not isinstance(value, str) or not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
                or name[offset:offset + len(value)] != value):
            return text
        spans.append((offset, offset + len(value)))
    spans.sort()
    if any(start < previous_end for (_, previous_end), (start, _) in zip(spans, spans[1:])):
        return text
    parts, at = [], 0
    for start, end in spans:
        parts += [name[at:start], ARGUMENT]
        at = end
    parts.append(name[at:])
    return f"{keyword}{''.join(parts)}".strip()[:STEP_TEXT_LENGTH]
```

In `_cucumber_feature`, replace the `if failed_step is not None:` block (lines 172-182) with:

```python
        if failed_step is not None:
            result = failed_step.get("result") or {}
            message = str(result.get("error_message") or "")
            keyword, step_text = f"{failed_step.get('keyword', '')}", f"{failed_step.get('name', '')}"
            step_name = f"{keyword}{step_text}".strip()
            _attach(row, _first_line(message), "\n".join(part for part in (step_name, message.strip()) if part))
            if step_name:
                entry = {"text": step_name[:STEP_TEXT_LENGTH]}
                line = failed_step.get("line")
                if isinstance(line, int) and not isinstance(line, bool) and 1 <= line <= 1_000_000:
                    entry["line"] = line
                definition = _step_definition(failed_step)
                if definition is not None:
                    entry["definition"] = definition
                entry["pattern"] = _step_pattern(failed_step, keyword, step_text)
                row["failed_step"] = entry
```

- [ ] **Step 6: Run the collector suite**

Run: `cd $WT/collector && $COL_PY -m pytest -q`
Expected: PASS (other suites that build payloads from Cucumber JSON, e.g. `test_cli.py`, `test_run_impact.py`, still pass; if one compares a whole `failed_step` dict, add `"pattern"` equal to the text).

- [ ] **Step 7: Docs** — `collector/README.md`, after the sentence ending `…the other formats send none.` (line 523) insert:
  `  From 0.8.0 it also carries `definition`, the step definition that ran the step (Cucumber's `match.location`, cut to 500 characters, left out when the report has none), and `pattern`, the step text with each matched argument replaced by `{…}` (`When I search {…}`, cut to 1000 characters; the text itself when the report lists no arguments, as cucumber-js's does, or they do not fit the text). QEOS uses them to group one step's failures across test cases.`

- [ ] **Step 8: Commit**

```bash
cd $WT && git add collector/src/qeos_collector/formats.py collector/tests/test_cucumber.py collector/README.md
git commit -m "feat(collector): the failed step's step definition and pattern (match.location, arguments as {…})

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: An older server's 422 on `failed_step`: send once more without the two fields

**Files:**
- Modify: `collector/src/qeos_collector/upload.py:86-129` (+ two helpers)
- Modify: `collector/src/qeos_collector/cli.py:557,588`
- Modify docs: `collector/README.md` (same paragraph as Task 6)
- Test: `collector/tests/test_upload.py` (append), `collector/tests/test_cli.py` (append)

**Interfaces:**
- Consumes: Task 6 payload shape.
- Produces: `upload.without_step_details(body: bytes) -> Optional[bytes]`; `upload.OLDER_PLATFORM: str`; `upload_part(..., warn: Callable[[str], None] = _ignore)` keyword.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_upload.py`; add `import json` at the top)

```python
STEP_PART = Part(body=json.dumps({"run": {}, "results": [{"name": "t", "status": "failed", "failed_step": {
    "text": "When I search Lisbon", "line": 4, "definition": "steps/search.js:12", "pattern": "When I search {…}"}}]},
    ensure_ascii=False, separators=(",", ":")).encode("utf-8"), idempotency_key="gh-1-1-step", count=1)
OLD_422 = {"detail": [{"type": "extra_forbidden", "loc": ["body", "results", 0, "failed_step", "definition"],
                       "msg": "Extra inputs are not permitted"}]}


def send_step(platform, warnings, part=STEP_PART):
    fake = FakeTime()
    return upload_part(collect(platform), KEY, part, None, sleep=fake.sleep, clock=fake.clock, rand=lambda: 0.0,
                       warn=warnings.append)


def test_an_older_platform_gets_the_upload_again_without_definition_and_pattern(platform):
    platform.reply(422, OLD_422)
    platform.reply(201, RECEIPT)
    warnings = []
    assert send_step(platform, warnings) == (201, RECEIPT)
    first, second = (json.loads(r["body"]) for r in platform.requests)
    assert first["results"][0]["failed_step"]["definition"] == "steps/search.js:12"
    assert second["results"][0]["failed_step"] == {"text": "When I search Lisbon", "line": 4}
    assert {r["headers"]["Idempotency-Key"] for r in platform.requests} == {"gh-1-1-step"}
    assert len(warnings) == 1 and "older than this collector" in warnings[0]


def test_the_retry_without_the_fields_happens_once(platform):
    platform.reply(422, OLD_422)
    platform.reply(422, OLD_422)
    with pytest.raises(UploadError) as err:
        send_step(platform, [])
    assert len(platform.requests) == 2 and err.value.retryable is False


def test_a_5xx_after_the_downgrade_keeps_the_stripped_body(platform):
    platform.reply(422, OLD_422)
    platform.reply(503)
    platform.reply(201, RECEIPT)
    assert send_step(platform, [])[0] == 201
    assert all("definition" not in r["body"].decode() for r in platform.requests[1:])


def test_other_422s_are_not_retried(platform):
    platform.reply(422, {"detail": [{"type": "string_too_long", "loc": ["body", "results", 0, "name"], "msg": "x"}]})
    warnings = []
    with pytest.raises(UploadError):
        send_step(platform, warnings)
    assert len(platform.requests) == 1 and warnings == []


def test_a_422_that_is_not_json_is_not_retried(platform):
    platform.reply(422, b"<html>failed_step</html>")
    with pytest.raises(UploadError):
        send_step(platform, [])
    assert len(platform.requests) == 1


def test_a_part_without_the_fields_is_not_sent_again(platform):
    platform.reply(422, OLD_422)
    with pytest.raises(UploadError):
        send_step(platform, [], part=PART)
    assert len(platform.requests) == 1


def test_without_step_details_strips_only_the_two_fields():
    body = json.loads(upload.without_step_details(STEP_PART.body))
    assert body["results"][0]["failed_step"] == {"text": "When I search Lisbon", "line": 4}
    assert upload.without_step_details(PART.body) is None
    assert upload.without_step_details(b"not json") is None
```

Append to `tests/test_cli.py`:

```python
CUCUMBER_WITH_MATCH = [{"uri": "features/search.feature", "name": "Search", "elements": [{
    "type": "scenario", "name": "by city", "steps": [{
        "keyword": "When ", "name": "I search Lisbon", "line": 4,
        "match": {"location": "features/step_definitions/search.js:12"},
        "result": {"status": "failed", "error_message": "Invalid city"}}]}]}]


def test_an_older_platform_still_stores_the_run_and_the_log_says_why(platform, tmp_path, capsys):
    report = tmp_path / "cucumber.json"
    report.write_text(json.dumps(CUCUMBER_WITH_MATCH), encoding="utf-8")
    platform.reply(422, {"detail": [{"type": "extra_forbidden",
                                     "loc": ["body", "results", 0, "failed_step", "definition"], "msg": "x"}]})
    platform.reply(201, RECEIPT)
    assert run(["upload", str(report)], env_for(platform)) == 0
    assert "definition" not in sent(platform, 1)["results"][0]["failed_step"]
    err = capsys.readouterr().err
    assert err.count("older than this collector") == 1 and "uploaded run 42 (201)" in err
```

(`RECEIPT` already exists in `test_cli.py`; if its `id` is not 42, assert on the id it has.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd $WT/collector && $COL_PY -m pytest -q tests/test_upload.py tests/test_cli.py`
Expected: FAIL (`TypeError: upload_part() got an unexpected keyword argument 'warn'`).

- [ ] **Step 3: Implement** in `upload.py`. Add after `MAX_DETAIL_CHARS = 500`:

```python
STEP_DETAILS = ("definition", "pattern")
OLDER_PLATFORM = ("the platform is older than this collector and refused the failed step's definition and pattern: "
                  "sent again without them (upgrade QEOS to group failed steps across test cases)")


def _ignore(message: str) -> None:
    pass
```

Change the `upload_part` signature (add after `rand`): `warn: Callable[[str], None] = _ignore,` and replace its body from `started = clock()` to the end of the loop with:

```python
    started = clock()
    attempt = 0
    payload = part.body
    downgraded = False
    while True:
        attempt += 1
        try:
            status, body, response_headers = _send(endpoint, payload, headers, context)
        except (OSError, http.client.HTTPException) as exc:
            if _is_tls_error(exc):
                raise UploadError(
                    f"TLS error talking to the platform ({_reason(exc)}); if it uses a private CA, pass --ca-file"
                ) from None
            problem, wait = f"cannot reach the platform ({_reason(exc)})", _backoff(attempt, rand)
        else:
            if status in (200, 201, 202):
                return status, _json(body)
            if status == 429:
                problem, wait = "the platform answered 429", _retry_after(response_headers)
            elif status >= 500:
                problem, wait = f"the platform answered {status}", _backoff(attempt, rand)
            else:
                # Spec 2026-10-14 §2: a server from before collector 0.8.0 forbids the two new fields. Once, and only
                # for that: nothing was stored, so the same Idempotency-Key is reused
                stripped = None if downgraded or status != 422 or not _names_failed_step(body) \
                    else without_step_details(payload)
                if stripped is None:
                    raise UploadError(_explain(status, body, response_headers))
                payload, downgraded = stripped, True
                warn(OLDER_PLATFORM)
                continue
        if attempt >= MAX_ATTEMPTS:
            raise UploadError(f"{problem}; gave up after {attempt} attempts", retryable=True)
        if clock() - started + wait > TIME_BUDGET_SECONDS:
            raise UploadError(f"{problem}; gave up after {TIME_BUDGET_SECONDS} s", retryable=True)
        sleep(wait)
```

Add the helpers (after `_json`):

```python
def _names_failed_step(body: bytes) -> bool:
    """A validation error inside a result's failed_step (FastAPI's 422: {"detail": [{"loc": [...]}, ...]})."""
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        return False
    return isinstance(detail, list) and any(
        isinstance(error, dict) and isinstance(error.get("loc"), list) and "failed_step" in error["loc"]
        for error in detail
    )


def without_step_details(body: bytes) -> Optional[bytes]:
    """The body without failed_step.definition and .pattern; None when it has neither (nothing to retry without)."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    removed = False
    for result in (data.get("results") if isinstance(data, dict) else None) or []:
        step = result.get("failed_step") if isinstance(result, dict) else None
        if isinstance(step, dict):
            for name in STEP_DETAILS:
                if name in step:
                    del step[name]
                    removed = True
    if not removed:
        return None
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
```

In `cli.py`, both calls become
`status, receipt = upload_part(endpoint, api_key, part, context, sleep=sleep, clock=clock, warn=say)`
(line 557 in `_upload`, line 588 in `_resend_spooled`, whose `say` is the same `_Output`).

- [ ] **Step 4: Run the collector suite**

Run: `cd $WT/collector && $COL_PY -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Docs** — `collector/README.md`, after the Task 6 sentence add:
  `  A platform from before these fields answers 422 naming `failed_step`: the collector then sends the upload once more without `definition` and `pattern`, under the same Idempotency-Key, and logs one line saying the platform is older than the collector. No other 422 is retried.`

- [ ] **Step 6: Commit**

```bash
cd $WT && git add collector/src/qeos_collector/upload.py collector/src/qeos_collector/cli.py collector/tests collector/README.md
git commit -m "feat(collector): an older platform's 422 on failed_step gets the upload once more without definition and pattern

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Phase 2 gate, release collector-v0.8.0, pin it

Mirrors the 0.7.0 release: a version-only commit (`7ecc4d1`), the tag, then a pin commit once the tag exists (`451c727`).

**Files:**
- Modify: `collector/src/qeos_collector/__init__.py:3`, `collector/tests/test_package.py:7`
- Pin commit: every file holding `collector-v0.7.0` outside `docs/superpowers` (collector/README.md, collector-jenkins/vars/qeosCollectorUpload.groovy, dashboard/src/pages/ProjectSettingsPage.tsx and its test, dashboard/src/templates/qeos-run.yml.txt, docs/SETUP.md, README.md, templates/github/qeos-run.yml, templates/qeos-collector.azure-pipelines.yml, templates/qeos-collector.gitlab-ci.yml), `IMPLEMENTATION_PLAN.md:33`, `TODO.md`.

- [ ] **Step 1: Gate** — run Task 5 Steps 1-4 (ingestion, collector, dashboard, architecture docs). All pass.
- [ ] **Step 2: Version commit**: `__version__ = "0.8.0"` in `__init__.py`; `assert qeos_collector.__version__ == "0.8.0"` in `test_package.py`; `$COL_PY -m pip install -e . --quiet && $COL_PY -m pytest -q` passes. Commit:

```bash
cd $WT && git add collector/src/qeos_collector/__init__.py collector/tests/test_package.py
git commit -m "release: qeos-collector 0.8.0 (failed step definition and pattern)

The version only. The pinned collector-v0.7.0 references move in a follow-up commit once the collector-v0.8.0 tag exists, so no published doc points at a missing tag.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Push**: `git fetch origin && git rebase origin/master` (re-run the gate if anything came in), `SHA=$(git rev-parse HEAD) && git push origin $SHA:master`; wait for CI green on `$SHA` (`gh run watch <id> --exit-status`). Check `gh auth status` shows the account that owns pushes to this repository before any `gh`/`git push`.
- [ ] **Step 4: Tag**: `git tag collector-v0.8.0 $SHA && git push origin collector-v0.8.0`. Watch the "Release collector" workflow: `gh run list --workflow release-collector.yml --limit 1` then `gh run watch <id> --exit-status`. Expected: test, build, release, docker, float jobs green (publish skipped unless PYPI_PUBLISH is set).
- [ ] **Step 5: Verify the floating tag**: `git fetch --tags --force origin && git rev-parse collector-v0^{} collector-v0.8.0^{}` print the same SHA; `gh release view collector-v0.8.0` lists `qeos-collector.pyz`.
- [ ] **Step 6: Pin commit**:

```bash
cd $WT && git grep -l "collector-v0\.7\.0" -- . ':!docs/superpowers' | xargs sed -i 's/collector-v0\.7\.0/collector-v0.8.0/g'
git diff -U0 | grep '^[-+]' | grep -v '^[-+][-+]'
```

Review every changed line: a line that says when a feature *arrived* stays on its release. Restore in `docs/SETUP.md` the bullet `3. **Suggested tests first (Cucumber, from `collector-v0.7.0`):**` (it names the release that introduced the feature). In `IMPLEMENTATION_PLAN.md:33` change `` `collector-v0.1.0`…`v0.7.0` `` to `` `collector-v0.1.0`…`v0.8.0` ``. In `TODO.md`, the failed-steps item: append `collector 0.8.0 released (tag collector-v0.8.0, collector-v0 follows).` Then run `cd dashboard && npx vitest run src/pages/ProjectSettingsPage.test.tsx && node --test ../templates/github/qeos-run.test.mjs` (pass). Commit:

```bash
git add -A -- . ':!docs/superpowers'
git commit -m "release: pin collector-v0.8.0 everywhere

Every pinned collector-v0.7.0 moves to collector-v0.8.0: the READMEs, SETUP, the Jenkins default ref, the GitLab and Azure templates, the Run from QEOS workflow template and the Project Settings snippet (and its test); the plan's release-tag range. Lines that name the release a feature arrived in stay.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(Use `git status` first: stage only the pinned files and the two docs; never the untracked `.claude/`, `.codex/`, `__pycache__` folders.)

- [ ] **Step 7: Push** as in Step 3 and wait for CI green.

---

# Phase 3 — Failed steps across test cases

### Task 9: Error shape

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/analytics/failed_steps.py` (append)
- Test: create `platforms/ingestion-service/tests/unit/test_error_shape.py`

**Interfaces:**
- Consumes: `analytics.signature` (`headline`, `_UUID`, `_HEX_PREFIXED`, `_HEX`, `_NUMBER`, `_SPACE`).
- Produces: `analytics.failed_steps.error_shape(message: Optional[str]) -> str`, `analytics.failed_steps.PLACEHOLDER = "…"`.

- [ ] **Step 1: Write the failing tests** `tests/unit/test_error_shape.py`

```python
"""Inside a step, failures group by the shape of their error (spec 2026-10-14 §3.2)."""
from src.ingestion.analytics.failed_steps import error_shape


def test_quoted_values_are_replaced_quotes_kept():
    assert error_shape("Invalid city 'Lisb0n'") == "Invalid city '…'"
    assert error_shape('expected "ok" but was "ko"') == 'expected "…" but was "…"'
    assert error_shape("locator `#pay` not found") == "locator `…` not found"


def test_an_apostrophe_inside_a_word_is_not_a_quote():
    assert error_shape("can't find 'pay button'") == "can't find '…'"


def test_numbers_uuids_and_hex_are_replaced():
    assert error_shape("Timeout of 30000ms exceeded") == "Timeout of …ms exceeded"
    assert error_shape("order 123e4567-e89b-12d3-a456-426614174000 missing") == "order … missing"
    assert error_shape("object 0x7ffe12 at deadbeef1 freed") == "object … at … freed"


def test_two_failures_that_differ_only_in_values_share_a_shape():
    assert error_shape("Invalid city 'Lisb0n' (id 12)") == error_shape("Invalid city 'P0rto' (id 7)")


def test_only_the_first_non_empty_line_counts_and_spaces_collapse():
    assert error_shape("\n  Invalid   city 'x'\n    at Steps.search(Steps.java:12)") == "Invalid city '…'"


def test_no_message_is_the_empty_shape():
    assert error_shape(None) == "" and error_shape("   \n") == ""
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/unit/test_error_shape.py`
Expected: FAIL (`ImportError: cannot import name 'error_shape'`).

- [ ] **Step 3: Implement** — append to `analytics/failed_steps.py` (and add `import re` and the signature import at the top):

```python
from src.ingestion.analytics.signature import _HEX, _HEX_PREFIXED, _NUMBER, _SPACE, _UUID, headline

PLACEHOLDER = "…"
# A quoted value: the quote not inside a word (so "can't" is not a quote), up to the same quote on the same line
_QUOTED = re.compile(r"""(?<!\w)(['"`])(?:(?!\1)[^\n])*\1(?!\w)""")


def error_shape(message: Optional[str]) -> str:
    """The first line of the error with quoted values, UUIDs, hex strings and numbers replaced by …: failures of one
    step that differ only in their values share it (`Invalid city 'Lisb0n'` and `Invalid city 'P0rto'`)."""
    line = headline(message) or ""
    line = _QUOTED.sub(lambda m: f"{m.group(1)}{PLACEHOLDER}{m.group(1)}", line)
    for pattern in (_UUID, _HEX_PREFIXED, _HEX, _NUMBER):
        line = pattern.sub(PLACEHOLDER, line)
    return _SPACE.sub(" ", line).strip()
```

- [ ] **Step 4: Run the tests**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/unit/test_error_shape.py tests/unit/test_failed_steps_identity.py tests/unit/test_failure_signature.py`
Expected: PASS. (If `object 0x7ffe12 at deadbeef1 freed` keeps a `…` artefact such as `……`, fix the order of substitutions, not the test.)

- [ ] **Step 5: Commit**

```bash
cd $WT && git add platforms/ingestion-service
git commit -m "feat(ingestion): error shape, the first error line with quoted values, numbers, ids and hex as …

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `GET /projects/{id}/runs/{run_id}/failed-steps`

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/service/failed_steps_service.py`
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py` (import + new route after `get_run_summary`)
- Test: create `platforms/ingestion-service/tests/integration/test_failed_steps.py`

**Interfaces:**
- Consumes: `step_key`, `error_shape` (Tasks 4, 9); `analytics_service.failed_step_of`, `analytics_service._latest_ranked`; `analytics.signature.headline`; `analytics.trends.as_utc`.
- Produces: `failed_steps_service.failed_steps(db: Session, project_id: int, run: Run) -> dict`; HTTP answer
  `{"steps": [{"key", "by", "pattern", "definition"?, "cases", "errors": [{"shape", "example", "cases", "tests": [{"test_key", "name", "text"}], "more"?}], "since": {"run_id", "started_at", "runs", "capped"}, "last_passed"?: {"run_id", "started_at"}}]}`.

- [ ] **Step 1: Write the failing tests** `tests/integration/test_failed_steps.py`

```python
"""Failed steps across test cases (spec 2026-10-14 §3.2-§3.3)."""
from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.analytics.failed_steps import step_key
from src.ingestion.models import RunResult
from tests.conftest import report_key

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
SEARCH = "features/step_definitions/search.js:12"
LOGIN = "features/step_definitions/login.js:3"


def url(run_id):
    return f"/api/v1/projects/1/runs/{run_id}/failed-steps"


@pytest.fixture
def step_run(seed_run, db):
    """step_run(started_at, {name: status | (status, step_text, definition, message)}, **seed_run fields): a run whose
    failing tests carry a failed step; with a definition the pattern is "When I search {…}"."""
    def _seed(started_at, tests, **fields):
        run = seed_run(started_at, results=tuple(
            (name, spec if isinstance(spec, str) else spec[0], 5) for name, spec in tests.items()), **fields)
        for row in db.query(RunResult).filter_by(run_id=run.id):
            spec = tests[row.name]
            if isinstance(spec, tuple):
                _, text, definition, message = spec
                row.failed_step_text, row.failed_step_definition, row.message = text, definition, message
                row.failed_step_pattern = "When I search {…}" if definition == SEARCH else None
        db.commit()
        return run

    return _seed


def get(client, auth, run):
    response = client.get(url(run.id), headers=auth())
    assert response.status_code == 200, response.text
    return response.json()["steps"]


def failing(text, definition=SEARCH, message="boom"):
    return ("failed", text, definition, message)


def test_one_step_across_cases_with_its_errors(client, auth, project_role, step_run):
    project_role("viewer")
    run = step_run(T0, {
        "lisbon": failing("When I search Lisb0n", message="Invalid city 'Lisb0n'"),
        "porto": failing("When I search P0rto", message="Invalid city 'P0rto'\n  at search.js:40"),
        "faro": ("errored", "When I search Faro", SEARCH, "Timeout of 3000ms exceeded"),
        "login": failing("Given I log in", definition=LOGIN),
        "ok": "passed",
    })
    search, login = get(client, auth, run)
    assert search["key"] == step_key(SEARCH, "x")[0] and search["by"] == "definition"
    assert search["definition"] == SEARCH and search["pattern"] == "When I search {…}" and search["cases"] == 3
    invalid, timeout = search["errors"]
    assert invalid == {"shape": "Invalid city '…'", "example": "Invalid city 'Lisb0n'", "cases": 2, "tests": [
        {"test_key": report_key("lisbon"), "name": "lisbon", "text": "When I search Lisb0n"},
        {"test_key": report_key("porto"), "name": "porto", "text": "When I search P0rto"}]}
    assert timeout["shape"] == "Timeout of …ms exceeded" and timeout["cases"] == 1 and "more" not in timeout
    assert search["since"]["run_id"] == run.id and search["since"]["runs"] == 1 and search["since"]["capped"] is False
    assert search["since"]["started_at"].startswith("2026-10-01T00:00:00")
    assert "last_passed" not in search
    assert login["cases"] == 1 and login["pattern"] == "Given I log in"


def test_without_a_definition_steps_group_by_text(client, auth, project_role, step_run):
    project_role("viewer")
    run = step_run(T0, {
        "a": failing("When I search Lisbon", definition=None),
        "b": failing("when  i search lisbon", definition=None),
        "c": failing("When I search Porto", definition=None),
    })
    lisbon, porto = get(client, auth, run)
    assert lisbon["by"] == "text" and lisbon["cases"] == 2 and "definition" not in lisbon
    assert lisbon["pattern"] in ("When I search Lisbon", "when  i search lisbon")
    assert porto["cases"] == 1 and porto["pattern"] == "When I search Porto"


def test_steps_sort_by_cases_then_pattern(client, auth, project_role, step_run):
    project_role("viewer")
    run = step_run(T0, {"a": failing("Then b", definition=None), "b": failing("Given a", definition=None),
                        "c": failing("When I search x"), "d": failing("When I search y")})
    assert [s["pattern"] for s in get(client, auth, run)] == ["When I search {…}", "Given a", "Then b"]


def test_a_re_run_that_passed_is_not_a_failed_step(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0, results=(("search", "failed", 5), ("search", "passed", 5)))
    first = db.query(RunResult).filter_by(run_id=run.id, status="failed").one()
    first.failed_step_text, first.failed_step_definition = "When I search Lisbon", SEARCH
    db.commit()
    assert get(client, auth, run) == []


def test_at_most_50_tests_per_error_with_the_rest_counted(client, auth, project_role, step_run):
    project_role("viewer")
    run = step_run(T0, {f"t{i:02d}": failing(f"When I search c{i}") for i in range(55)})
    (step,) = get(client, auth, run)
    (error,) = step["errors"]
    assert step["cases"] == 55 and error["cases"] == 55 and len(error["tests"]) == 50 and error["more"] == 5


def test_a_run_without_failed_steps_answers_an_empty_list(client, auth, project_role, seed_run):
    project_role("viewer")
    run = seed_run(T0, results=(("ok", "passed", 5), ("junit", "failed", 5)))  # junit: no step, details is None
    assert get(client, auth, run) == []


def test_since_walks_back_while_the_step_keeps_failing_and_names_the_run_that_passed(
        client, auth, project_role, step_run):
    project_role("viewer")
    passed = step_run(T0, {"lisbon": "passed"})
    first = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    step_run(T0 + timedelta(hours=2), {"other": "passed"})  # without the step's tests: passed over
    step_run(T0 + timedelta(hours=3), {"lisbon": "skipped"})  # did not run: passed over (R3)
    run = step_run(T0 + timedelta(hours=4), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == first.id and step["since"]["runs"] == 2 and step["since"]["capped"] is False
    assert step["last_passed"]["run_id"] == passed.id
    assert step["last_passed"]["started_at"].startswith("2026-10-01T00:00:00")


def test_a_failure_at_another_step_stops_the_streak_without_last_passed(client, auth, project_role, step_run):
    project_role("viewer")
    step_run(T0, {"lisbon": failing("Given I log in", definition=LOGIN)})
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == run.id and step["since"]["runs"] == 1 and "last_passed" not in step


def test_the_streak_continues_while_one_of_the_tests_failed_at_the_step(client, auth, project_role, step_run):
    project_role("viewer")
    first = step_run(T0, {"lisbon": "passed", "porto": failing("When I search Porto")})
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon"),
                                             "porto": failing("When I search Porto")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == first.id and step["since"]["runs"] == 2


def test_rows_from_before_collector_0_8_count_by_their_text(client, auth, project_role, step_run):
    project_role("viewer")
    old = step_run(T0, {"lisbon": failing("When I search Lisbon", definition=None)})
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["by"] == "definition" and step["since"]["run_id"] == old.id and step["since"]["runs"] == 2


def test_impact_subset_runs_count_like_any_run(client, auth, project_role, step_run):
    project_role("viewer")
    subset = step_run(T0, {"lisbon": failing("When I search Lisbon")}, scope="impact-subset")
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == subset.id


def test_another_projects_runs_never_join_the_streak(client, auth, project_role, step_run):
    project_role("viewer")
    step_run(T0, {"lisbon": failing("When I search Lisbon")}, project_id=2)
    run = step_run(T0 + timedelta(hours=1), {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["runs"] == 1 and step["since"]["capped"] is False


def test_the_walk_stops_at_50_runs(client, auth, project_role, step_run):
    project_role("viewer")
    runs = [step_run(T0 + timedelta(minutes=i), {"lisbon": failing("When I search Lisbon")}) for i in range(51)]
    (step,) = get(client, auth, runs[-1])
    assert step["since"] == {**step["since"], "runs": 50, "capped": True, "run_id": runs[1].id}
    assert "last_passed" not in step


def test_exactly_50_runs_with_nothing_before_is_not_capped(client, auth, project_role, step_run):
    project_role("viewer")
    runs = [step_run(T0 + timedelta(minutes=i), {"lisbon": failing("When I search Lisbon")}) for i in range(50)]
    (step,) = get(client, auth, runs[-1])
    assert step["since"]["runs"] == 50 and step["since"]["capped"] is False and step["since"]["run_id"] == runs[0].id


def test_the_walk_stops_at_90_days(client, auth, project_role, step_run):
    project_role("viewer")
    step_run(T0 - timedelta(days=100), {"lisbon": failing("When I search Lisbon")})
    inside = step_run(T0 - timedelta(days=80), {"lisbon": failing("When I search Lisbon")})
    run = step_run(T0, {"lisbon": failing("When I search Lisbon")})
    (step,) = get(client, auth, run)
    assert step["since"]["run_id"] == inside.id and step["since"]["runs"] == 2 and step["since"]["capped"] is True


def test_a_run_of_another_project_or_unknown_is_404(client, auth, project_role, step_run):
    project_role("viewer")
    other = step_run(T0, {"lisbon": failing("When I search Lisbon")}, project_id=2)
    assert client.get(url(other.id), headers=auth()).status_code == 404
    assert client.get(url(999999), headers=auth()).status_code == 404


@pytest.mark.parametrize("role", ["owner", "admin", "member", "viewer"])
def test_every_project_role_reads_it(client, auth, project_role, step_run, role):
    project_role(role)
    run = step_run(T0, {"lisbon": failing("When I search Lisbon")})
    assert client.get(url(run.id), headers=auth()).status_code == 200


def test_no_project_access_is_404(client, auth, project_role, step_run):
    run = step_run(T0, {"lisbon": failing("When I search Lisbon")})
    project_role(status_code=404)
    assert client.get(url(run.id), headers=auth()).status_code == 404
```

(Check `READ_ROLES` in `src/ingestion/api/deps.py` and `project_role` in `tests/conftest.py`: parametrize over exactly the roles `READ_ROLES` holds, using the role names the other run-endpoint tests use, e.g. `tests/integration/test_runs_endpoints.py`.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/integration/test_failed_steps.py`
Expected: FAIL (404 on every request: route missing).

- [ ] **Step 3: Create** `src/ingestion/service/failed_steps_service.py`

```python
"""Failed steps across test cases (spec 2026-10-14 §3.2-§3.3): in one run, each step that failed, in how many test
cases and with which errors, and since which run it has been failing.

A test's result in a run is its last row there (a re-run's later row wins, as latest-results with run_id). A skipped
result did not run the step, so it neither continues nor stops a streak (plan ruling R3)."""
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from src.ingestion.analytics.failed_steps import error_shape, step_key
from src.ingestion.analytics.signature import headline
from src.ingestion.analytics.trends import as_utc
from src.ingestion.models import Run, RunResult
from src.ingestion.service.analytics_service import _latest_ranked, failed_step_of

COUNTED = ("passed", "failed", "errored")
MAX_TESTS = 50   # per error group
MAX_RUNS = 50    # the streak, this run included
MAX_DAYS = 90


def failed_steps(db: Session, project_id: int, run: Run) -> dict:
    groups: Dict[str, List[dict]] = defaultdict(list)
    for row in _failing_rows(db, run.id):
        groups[row["step"]["key"]].append(row)
    steps = [_step(db, project_id, run, key, rows) for key, rows in groups.items()]
    steps.sort(key=lambda s: (-s["cases"], s["pattern"].lower(), s["key"]))
    return {"steps": steps}


def _failing_rows(db: Session, run_id: int) -> List[dict]:
    ranked = _latest_ranked(
        [Run.id == run_id],
        RunResult.name, RunResult.status, RunResult.message, RunResult.details, RunResult.failed_step_text,
        RunResult.failed_step_line, RunResult.failed_step_definition, RunResult.failed_step_pattern,
    )
    rows = []
    for r in db.execute(select(ranked).where(ranked.c.position == 1)).mappings():
        step = failed_step_of(r["status"], r["message"], r["details"], r["failed_step_text"], r["failed_step_line"],
                              r["failed_step_definition"], r["failed_step_pattern"])
        if step is not None:
            rows.append({"test_key": r["test_key"], "name": r["name"], "message": r["message"], "step": step})
    return rows


def _step(db: Session, project_id: int, run: Run, key: str, rows: List[dict]) -> dict:
    definition = rows[0]["step"].get("definition")  # one key, one definition
    # Shown as the most frequent pattern, else the most frequent text (spec §3.2)
    shown = Counter(r["step"]["pattern"] for r in rows if r["step"].get("pattern")) \
        or Counter(r["step"]["text"] for r in rows)
    pattern = min(shown.items(), key=lambda item: (-item[1], item[0]))[0]
    step = {"key": key, "by": "definition" if definition else "text", "pattern": pattern}
    if definition:
        step["definition"] = definition
    step["cases"] = len(rows)
    step["errors"] = _errors(rows)
    since, last_passed = _streak(db, project_id, run, key, rows)
    step["since"] = since
    if last_passed is not None:
        step["last_passed"] = last_passed
    return step


def _errors(rows: List[dict]) -> List[dict]:
    groups: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        groups[error_shape(row["message"])].append(row)
    out = []
    for shape, members in groups.items():
        members.sort(key=lambda r: (r["name"].lower(), r["test_key"]))
        entry = {
            "shape": shape,
            "example": next((headline(r["message"]) for r in members if headline(r["message"])), None),
            "cases": len(members),
            "tests": [{"test_key": r["test_key"], "name": r["name"], "text": r["step"]["text"]}
                      for r in members[:MAX_TESTS]],
        }
        if len(members) > MAX_TESTS:
            entry["more"] = len(members) - MAX_TESTS
        out.append(entry)
    out.sort(key=lambda e: (-e["cases"], e["shape"]))
    return out


def _ran(tests: List[str]):
    """The run holds a result of one of the tests that ran (not skipped)."""
    return exists().where(RunResult.run_id == Run.id, RunResult.test_key.in_(tests), RunResult.status.in_(COUNTED))


def _streak(db: Session, project_id: int, run: Run, key: str, rows: List[dict]) -> Tuple[dict, Optional[dict]]:
    """Walk back through earlier runs of the project (by start, then id) holding any of the step's failing tests; the
    streak goes on while one of them failed at this step, at most 50 runs (this one included) or 90 days."""
    tests = sorted({r["test_key"] for r in rows})
    # Rows stored before collector 0.8.0 have no definition and are keyed by their text: the texts this step failed
    # with in this run count as this step too, so upgrading the collector does not restart the streak (ruling R4)
    keys = {key} | {step_key(None, r["step"]["text"])[0] for r in rows}
    cutoff = run.started_at - timedelta(days=MAX_DAYS)
    earlier = or_(Run.started_at < run.started_at, and_(Run.started_at == run.started_at, Run.id < run.id))
    candidates = db.execute(
        select(Run.id, Run.started_at)
        .where(Run.project_id == project_id, earlier, Run.started_at >= cutoff, _ran(tests))
        .order_by(Run.started_at.desc(), Run.id.desc())
        .limit(MAX_RUNS)
    ).all()
    walk = candidates[:MAX_RUNS - 1]
    results = _results_by_run(db, [c.id for c in walk], tests)
    since_id, since_at, runs, last_passed, stopped = run.id, run.started_at, 1, None, False
    for candidate in walk:
        then = results.get(candidate.id, [])
        if any(_key_of(r) in keys for r in then):
            since_id, since_at, runs = candidate.id, candidate.started_at, runs + 1
            continue
        stopped = True
        if any(r.status == "passed" for r in then):
            last_passed = {"run_id": candidate.id, "started_at": as_utc(candidate.started_at)}
        break
    capped = not stopped and (len(candidates) == MAX_RUNS or _ran_before(db, project_id, tests, cutoff))
    return {"run_id": since_id, "started_at": as_utc(since_at), "runs": runs, "capped": capped}, last_passed


def _results_by_run(db: Session, run_ids: List[int], tests: List[str]) -> Dict[int, list]:
    if not run_ids:
        return {}
    last = {}
    for r in db.execute(
        select(RunResult.run_id, RunResult.test_key, RunResult.status, RunResult.message, RunResult.details,
               RunResult.failed_step_text, RunResult.failed_step_definition)
        .where(RunResult.run_id.in_(run_ids), RunResult.test_key.in_(tests), RunResult.status.in_(COUNTED))
        .order_by(RunResult.id)
    ):
        last[(r.run_id, r.test_key)] = r  # a re-run's later row wins
    by_run: Dict[int, list] = defaultdict(list)
    for (run_id, _), r in last.items():
        by_run[run_id].append(r)
    return by_run


def _key_of(row) -> Optional[str]:
    step = failed_step_of(row.status, row.message, row.details, row.failed_step_text, None, row.failed_step_definition)
    return step["key"] if step else None


def _ran_before(db: Session, project_id: int, tests: List[str], cutoff) -> bool:
    return db.execute(
        select(Run.id).where(Run.project_id == project_id, Run.started_at < cutoff, _ran(tests)).limit(1)
    ).first() is not None
```

- [ ] **Step 4: Add the route** (`api/v1/endpoints/runs.py`): import `failed_steps_service` next to `impact_read, run_service` (`from src.ingestion.service import failed_steps_service, impact_read, run_service`) and add after `get_run_summary`:

```python
@project_router.get("/{run_id}/failed-steps")
def get_failed_steps(
    run_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """Each failed Cucumber step of the run across its test cases, with error groups and since when it fails
    (spec 2026-10-14 §3.3). A plain dict, so absent fields stay absent (plan ruling R10)."""
    run = run_service.get_run(db, run_id)
    # A run of another project is indistinguishable from a missing one
    if run is None or run.project_id != access.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return failed_steps_service.failed_steps(db, access.project_id, run)
```

- [ ] **Step 5: Run the tests**

Run: `cd $WT/platforms/ingestion-service && SECRET_KEY=test $ING_PY -m pytest -q tests/integration/test_failed_steps.py`
Expected: PASS. If SQLite returns naive datetimes so `run.started_at - timedelta(...)` compares wrongly with stored values, convert through `as_utc` consistently on both sides rather than changing the tests.

- [ ] **Step 6: Run the service suite**: `SECRET_KEY=test $ING_PY -m pytest -q` → PASS.

- [ ] **Step 7: Commit**

```bash
cd $WT && git add platforms/ingestion-service
git commit -m "feat(ingestion): failed steps across test cases, by step definition, with error shapes and since when

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(The docs for this endpoint land in Task 11 together with its smoke check; Task 10 and 11 are pushed together in Phase 3, never apart.)

---

### Task 11: Smoke and server docs for `failed-steps`

**Files:**
- Modify: `scripts/smoke_gateway.sh` (after the Task 4 smoke lines)
- Modify docs: `platforms/ingestion-service/README.md` (after the `…/summary` bullet, line ~112), `TECHNICAL_SPECIFICATION.md:125` (runs endpoints), `TODO.md`

- [ ] **Step 1: Smoke** — append after the Task 4 lines:

```bash
check "failed-steps of that run -> ingestion-service" 200 GET \
  "$BASE/api/v1/projects/$PROJECT_ID/runs/${STEP_RUN_ID:-0}/failed-steps" "${AUTH[@]}"
body_has "... grouped by its step definition" '"by":"definition"'
body_has "... in one test case" '"cases":1'
body_has "... with its error shape" "\"shape\":\"Invalid city '"
```

(Starlette writes JSON with `ensure_ascii=False`, so the `…` arrives raw in UTF-8; matching up to the quote keeps the check independent of the shell's locale.)

- [ ] **Step 2: Ingestion README** — after the `/summary` bullet add:

```markdown
- `GET /api/v1/projects/<id>/runs/<run_id>/failed-steps` — the run's failed Cucumber steps across its test cases (spec
  2026-10-14). A step is its step definition (`failed_step_definition`, collector 0.8.0), else its text without case
  or extra spaces (`"by": "definition" | "text"`); each test counts with its last row in the run. Per step: `key`
  (the `failed_step.key` of `latest-results`), `pattern` (the most frequent, else the text), `definition`, `cases`
  (distinct tests), `errors` grouped by shape (the first error line with quoted values, numbers, UUIDs and hex as
  `…`; one real `example`; at most 50 `tests` `{test_key, name, text}` with `more` beyond) and `since` `{run_id,
  started_at, runs, capped}`: walking back through earlier runs of the project (any branch) that ran one of those
  tests (skipped results are not counted), the streak goes on while one of them failed at this step, at most 50 runs
  or 90 days (`capped`). `last_passed` `{run_id, started_at}` is the run that ended the streak when one of the tests
  passed in it. Steps are sorted by `cases`, then pattern. Every project role; 404 for an unknown run or a run of
  another project.
```

- [ ] **Step 3: TECHNICAL_SPECIFICATION.md** line 125 list (`… run detail with status filter and changed …`): add `, failed steps across test cases (`GET /projects/{id}/runs/{run_id}/failed-steps`: by step definition or text, errors by shape, failing since, 50 runs / 90 days)` after the run detail item.

- [ ] **Step 4: TODO.md** — the failed-steps item: append `Phase 3 server: `GET /projects/{id}/runs/{run_id}/failed-steps` done.`

- [ ] **Step 5: Commit**

```bash
cd $WT && git add scripts/smoke_gateway.sh platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md TODO.md
git commit -m "docs(ingestion): failed-steps endpoint, smoke check through the gateway

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Run page "Failed steps" section

**First:** invoke the `ui-ux-pro-max` skill and check the layout below against it (disclosure rows, mono pattern, muted meta, 24px targets, focus rings, reduced motion) before writing UI code. Existing tokens only.

**Files:**
- Modify: `dashboard/src/api/runs.ts` (types + fetch, after `getRunSummary`)
- Create: `dashboard/src/lib/failedSteps.ts`, `dashboard/src/lib/failedSteps.test.ts`
- Create: `dashboard/src/components/FailedSteps.tsx`, `dashboard/src/components/FailedSteps.test.tsx`
- Modify: `dashboard/src/pages/RunDetailPage.tsx:8,150`
- Modify: `dashboard/src/test/server.ts` (default handler)
- Modify: `dashboard/src/index.css` (after the `.cause-list` rules, ~line 825)
- Modify docs: `DESIGN.md` (new `### Failed Steps (run page)` after `### Feature Page`)

**Interfaces:**
- Consumes: the Task 10 answer.
- Produces (Task 13 uses): in `api/runs.ts` the types `FailedStepTest`, `FailedStepError`, `FailedStepSince`, `RunFailedStep` and `getRunFailedSteps(projectId: number, runId: number, init?: { signal?: AbortSignal }): Promise<{ steps: RunFailedStep[] }>`; in `lib/failedSteps.ts`: `failedStepsQuery(projectId, runId)`, `sinceText(step): string`, `spreadText(step): string`, `stepAnchor(key): string`, `stepHref(projectId, runId, key): string`, `casesByTestKey(projectId, keys): Promise<Map<string, number>>`, `TEXT_GROUPED_NOTE`.

- [ ] **Step 1: Write the failing unit tests** `src/lib/failedSteps.test.ts`

```ts
import type { RunFailedStep } from "../api/runs";
import { sinceText, spreadText, stepHref } from "./failedSteps";

const step = (extra: Partial<RunFailedStep> = {}): RunFailedStep => ({
  key: "a1b2c3d4e5f60718", by: "definition", pattern: "When I search {…}", cases: 12, errors: [],
  since: { run_id: 430, started_at: "2026-10-14T09:00:00Z", runs: 5, capped: false }, ...extra,
});

test("the run page says since when, how many runs, and the last pass", () => {
  expect(sinceText(step({ last_passed: { run_id: 429, started_at: "2026-10-13T09:00:00Z" } })))
    .toMatch(/^failing since run #430, .+ \(5 runs\) · last passed in run #429$/);
  expect(sinceText(step())).toMatch(/^failing since run #430, .+ \(5 runs\)$/);
});

test("a step new in this run says so, with the last pass when there is one", () => {
  const fresh = { run_id: 61, started_at: "2026-10-14T12:00:00Z", runs: 1, capped: false };
  expect(sinceText(step({ since: fresh }))).toBe("new in this run");
  expect(sinceText(step({ since: fresh, last_passed: { run_id: 60, started_at: "2026-10-14T11:00:00Z" } })))
    .toBe("new in this run · last passed in run #60");
});

test("a capped streak names its cap: 50 runs, else 90 days", () => {
  expect(sinceText(step({ since: { run_id: 12, started_at: "2026-08-01T00:00:00Z", runs: 50, capped: true } })))
    .toBe("failing for more than 50 runs");
  expect(sinceText(step({ since: { run_id: 12, started_at: "2026-07-20T00:00:00Z", runs: 3, capped: true } })))
    .toBe("failing for more than 90 days");
});

test("the tooltip line counts the other test cases", () => {
  expect(spreadText(step())).toBe("Also failed in 11 other test cases in this run · failing since run #430");
  expect(spreadText(step({ cases: 2 }))).toBe("Also failed in 1 other test case in this run · failing since run #430");
  expect(spreadText(step({ cases: 1, since: { run_id: 61, started_at: "2026-10-14T12:00:00Z", runs: 1, capped: false } })))
    .toBe("Only this test case · new in this run");
});

test("a step's link opens its row on the run page", () => {
  expect(stepHref(42, 61, "a1b2c3d4e5f60718")).toBe("/projects/42/runs/61#step-a1b2c3d4e5f60718");
});
```

- [ ] **Step 2: Write the failing component tests** `src/components/FailedSteps.test.tsx`

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import FailedSteps from "./FailedSteps";
import { TEXT_GROUPED_NOTE } from "../lib/failedSteps";

const P = "/api/v1/projects/42";
const SEARCH = "a1b2c3d4e5f60718";
const LOGIN = "0f0f0f0f0f0f0f0f";
const STEPS = { steps: [
  { key: SEARCH, by: "definition", pattern: "When I search {…}", definition: "steps/search.js:12", cases: 3,
    errors: [
      { shape: "Invalid city '…'", example: "Invalid city 'Lisb0n'", cases: 2, tests: [
        { test_key: "k-lisbon", name: "by city Lisbon", text: "When I search Lisb0n" },
        { test_key: "k-porto", name: "by city Porto", text: "When I search P0rto" }] },
      { shape: "", example: null, cases: 1, tests: [{ test_key: "k-faro", name: "by city Faro", text: "When I search Faro" }],
        more: 4 }],
    since: { run_id: 58, started_at: "2026-10-14T09:00:00Z", runs: 4, capped: false },
    last_passed: { run_id: 57, started_at: "2026-10-13T09:00:00Z" } },
  { key: LOGIN, by: "text", pattern: "Given I log in", cases: 1,
    errors: [{ shape: "boom", example: "boom", cases: 1, tests: [{ test_key: "k-login", name: "login", text: "Given I log in" }] }],
    since: { run_id: 61, started_at: "2026-10-14T12:00:00Z", runs: 1, capped: false } },
] };

let searches: { test_keys: string[] }[] = [];
function setup(answer: object = STEPS, status = 200) {
  searches = [];
  server.use(
    http.get(`${P}/runs/61/failed-steps`, () =>
      status === 200 ? HttpResponse.json(answer) : HttpResponse.json({ detail: "boom" }, { status })),
    http.post(`${P}/cases/search`, async ({ request }) => {
      searches.push(await request.json() as { test_keys: string[] });
      return HttpResponse.json({ total: 3, items: [
        { number: 14, automated_test_key: "k-lisbon" }, { number: 12, automated_test_key: "K-LISBON" },
        { number: 13, automated_test_key: "k-porto" }] });
    }),
  );
}

function renderAt(url = "/projects/42/runs/61") {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/projects/:projectId/runs/:runId" element={<FailedSteps projectId={42} runId={61} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const rowOf = (pattern: string) => screen.getByText(pattern).closest("li") as HTMLElement;

test("one row per step, biggest first, with how wide and since when", async () => {
  setup();
  renderAt();
  expect(await screen.findByRole("heading", { name: "Failed steps" })).toBeInTheDocument();
  const rows = screen.getAllByRole("button", { expanded: false });
  expect(rows.map((b) => b.textContent)).toEqual(["When I search {…}", "Given I log in"]);
  const search = rowOf("When I search {…}");
  expect(search).toHaveTextContent("failed in 3 test cases");
  expect(search).toHaveTextContent(/failing since run #58, .+ \(4 runs\) · last passed in run #57/);
  expect(search).not.toHaveTextContent(TEXT_GROUPED_NOTE);
  const login = rowOf("Given I log in");
  expect(login).toHaveTextContent("failed in 1 test case");
  expect(login).toHaveTextContent("new in this run");
  expect(login).toHaveTextContent(TEXT_GROUPED_NOTE);
});

test("a row opens to its error groups and the test cases with the text they ran", async () => {
  setup();
  renderAt();
  const button = await screen.findByRole("button", { name: "When I search {…}" });
  expect(button).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(button);
  expect(button).toHaveAttribute("aria-expanded", "true");
  const panel = document.getElementById(button.getAttribute("aria-controls")!) as HTMLElement;
  expect(panel).toBeVisible();
  expect(within(panel).getByText("Invalid city '…'")).toBeInTheDocument();
  expect(within(panel).getByText("Invalid city 'Lisb0n'")).toBeInTheDocument();
  expect(within(panel).getByText("No error message")).toBeInTheDocument();
  expect(within(panel).getByText("When I search Lisb0n")).toBeInTheDocument();
  expect(within(panel).getByText("and 4 more")).toBeInTheDocument();
  // The lowest linked case number wins, as of this run
  expect(await within(panel).findByRole("link", { name: "by city Lisbon" })).toHaveAttribute("href", "/projects/42/cases/12?run=61");
  expect(await within(panel).findByRole("link", { name: "by city Porto" })).toHaveAttribute("href", "/projects/42/cases/13?run=61");
  expect(searches[0].test_keys).toEqual(["k-faro", "k-lisbon", "k-login", "k-porto"]);
  await userEvent.click(button);
  expect(button).toHaveAttribute("aria-expanded", "false");
});

test("a test without a case links to its history", async () => {
  setup();
  renderAt();
  await userEvent.click(await screen.findByRole("button", { name: "When I search {…}" }));
  expect(await screen.findByRole("link", { name: "by city Faro" })).toHaveAttribute("href", "/projects/42/tests/k-faro");
});

test("a link to a step's anchor opens that row", async () => {
  setup();
  renderAt(`/projects/42/runs/61#step-${LOGIN}`);
  expect(await screen.findByRole("button", { name: "Given I log in" })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: "When I search {…}" })).toHaveAttribute("aria-expanded", "false");
  expect(document.getElementById(`step-${LOGIN}`)).not.toBeNull();
});

test("a run without failed steps shows nothing", async () => {
  setup({ steps: [] });
  renderAt();
  await new Promise((r) => setTimeout(r, 50));
  expect(screen.queryByRole("heading", { name: "Failed steps" })).toBeNull();
});

test("a failed request says so with Retry inside the section", async () => {
  setup(STEPS, 500);
  renderAt();
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Failed steps" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
});
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd $WT/dashboard && npx vitest run src/lib/failedSteps.test.ts src/components/FailedSteps.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 4: API** — append to `src/api/runs.ts`:

```ts
/** A test case that failed at a step, with the text it ran ("When I search Lisb0n"). */
export interface FailedStepTest { test_key: string; name: string; text: string }

/** One step's failures that share an error shape (quoted values, numbers and ids as "…"); `shape` "" means no message. */
export interface FailedStepError { shape: string; example: string | null; cases: number; tests: FailedStepTest[]; more?: number }

export interface FailedStepSince { run_id: number; started_at: string; runs: number; capped: boolean }

/** A step that failed in the run, across its test cases (spec 2026-10-14 §3.3). */
export interface RunFailedStep {
  key: string;
  by: "definition" | "text";
  pattern: string;
  definition?: string;
  cases: number;
  errors: FailedStepError[];
  since: FailedStepSince;
  last_passed?: { run_id: number; started_at: string };
}

export function getRunFailedSteps(
  projectId: number, runId: number, init: { signal?: AbortSignal } = {},
): Promise<{ steps: RunFailedStep[] }> {
  return apiFetch(`/api/v1/projects/${projectId}/runs/${runId}/failed-steps`, init);
}
```

- [ ] **Step 5: Library** — create `src/lib/failedSteps.ts`:

```ts
import { searchCases } from "../api/cases";
import { type FailedStepSince, type RunFailedStep, getRunFailedSteps } from "../api/runs";
import { plural } from "./words";

export const TEXT_GROUPED_NOTE = "Grouped by step text: update the collector to 0.8.0 to group parameter variations.";
const STALE_MS = 60_000;
const CAP_RUNS = 50;
const SEARCH_PAGE = 200; // test-management's search limit
const SEARCH_PAGES = 5;
const day = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

/** One run's failed steps, under one key for the run page and every tooltip of that run. */
export const failedStepsQuery = (projectId: number, runId: number) => ({
  queryKey: ["failed-steps", projectId, runId] as const,
  queryFn: ({ signal }: { signal: AbortSignal }) => getRunFailedSteps(projectId, runId, { signal }),
  staleTime: STALE_MS,
});

export const stepAnchor = (key: string) => `step-${key}`;
export const stepHref = (projectId: number, runId: number, key: string) => `/projects/${projectId}/runs/${runId}#${stepAnchor(key)}`;

/** A capped streak by what capped it: 50 runs, else the 90-day window (plan ruling R5). */
const cappedText = (since: FailedStepSince) =>
  since.runs >= CAP_RUNS ? `failing for more than ${CAP_RUNS} runs` : "failing for more than 90 days";

/** The run page's line: "failing since run #430, 14 Oct (5 runs) · last passed in run #429". */
export function sinceText(step: RunFailedStep): string {
  const { since, last_passed } = step;
  const base = since.capped ? cappedText(since)
    : since.runs === 1 ? "new in this run"
    : `failing since run #${since.run_id}, ${day.format(new Date(since.started_at))} (${plural(since.runs, "run", "runs")})`;
  return last_passed ? `${base} · last passed in run #${last_passed.run_id}` : base;
}

/** The tooltip's line: "Also failed in 11 other test cases in this run · failing since run #430". */
export function spreadText(step: RunFailedStep): string {
  const others = step.cases - 1;
  const wide = others > 0 ? `Also failed in ${plural(others, "other test case", "other test cases")} in this run` : "Only this test case";
  const since = step.since.capped ? cappedText(step.since) : step.since.runs === 1 ? "new in this run" : `failing since run #${step.since.run_id}`;
  return `${wide} · ${since}`;
}

/** Test keys (lowercased) to the case each is linked to, the lowest number when several are; archived cases are left
 *  out by the search, so their tests link to their history (plan ruling R9). */
export async function casesByTestKey(projectId: number, keys: string[]): Promise<Map<string, number>> {
  const found = new Map<string, number>();
  for (let page = 0; page < SEARCH_PAGES; page++) {
    const res = await searchCases(projectId, { labels: [], test_keys: keys, keys_mode: "include", limit: SEARCH_PAGE, offset: page * SEARCH_PAGE });
    for (const c of res.items) {
      const key = c.automated_test_key?.toLowerCase();
      const known = key != null ? found.get(key) : undefined;
      if (key != null && (known == null || c.number < known)) found.set(key, c.number);
    }
    if (res.items.length === 0 || (page + 1) * SEARCH_PAGE >= res.total) break;
  }
  return found;
}
```

- [ ] **Step 6: Component** — create `src/components/FailedSteps.tsx`:

```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { FailedStepTest } from "../api/runs";
import ErrorBanner from "./ErrorBanner";
import { TEXT_GROUPED_NOTE, casesByTestKey, failedStepsQuery, sinceText, stepAnchor } from "../lib/failedSteps";
import { plural, testHistoryPath } from "../lib/words";

const ANCHOR = "#step-";

/** The run's failed steps across test cases (spec 2026-10-14 §4.1): one row per step, biggest first; a row opens to
 *  its error groups and the test cases with the text they ran. `#step-<key>` opens and scrolls to a row. */
export default function FailedSteps({ projectId, runId }: { projectId: number; runId: number }) {
  const query = useQuery(failedStepsQuery(projectId, runId));
  const steps = query.data?.steps;
  const keys = useMemo(
    () => [...new Set((steps ?? []).flatMap((s) => s.errors.flatMap((e) => e.tests.map((t) => t.test_key.toLowerCase()))))].sort(),
    [steps],
  );
  const linked = useQuery({
    queryKey: ["failed-steps-cases", projectId, keys],
    enabled: keys.length > 0,
    queryFn: () => casesByTestKey(projectId, keys),
    staleTime: 60_000,
  });
  const { hash } = useLocation();
  const target = hash.startsWith(ANCHOR) ? decodeURIComponent(hash.slice(ANCHOR.length)) : null;
  const [toggled, setToggled] = useState<ReadonlyMap<string, boolean>>(new Map());
  const scrolled = useRef<string | null>(null);
  useEffect(() => {
    if (target == null || scrolled.current === target || !steps?.some((s) => s.key === target)) return;
    scrolled.current = target;
    document.getElementById(stepAnchor(target))?.scrollIntoView?.({ block: "start" });
  }, [target, steps]);

  const hrefOf = (t: FailedStepTest) => {
    const number = linked.data?.get(t.test_key.toLowerCase());
    return number != null ? `/projects/${projectId}/cases/${number}?run=${runId}` : testHistoryPath(projectId, t.test_key);
  };

  if (query.error == null && (!steps || steps.length === 0)) return null;
  return (
    <section className="card" aria-labelledby="failed-steps">
      <h2 id="failed-steps">Failed steps</h2>
      {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
      {steps && (
        <ol className="step-list">
          {steps.map((s) => {
            const open = toggled.get(s.key) ?? s.key === target;
            const panel = `${stepAnchor(s.key)}-errors`;
            return (
              <li key={s.key} id={stepAnchor(s.key)}>
                <button type="button" className="step-head" aria-expanded={open} aria-controls={panel}
                  onClick={() => setToggled((t) => new Map(t).set(s.key, !open))}>
                  <ChevronRight size={16} aria-hidden="true" className="step-chevron" />
                  <code className="step-pattern">{s.pattern}</code>
                </button>
                <p className="step-meta">
                  failed in {plural(s.cases, "test case", "test cases")} · {sinceText(s)}
                </p>
                {s.by === "text" && <p className="muted step-note">{TEXT_GROUPED_NOTE}</p>}
                <div id={panel} className="step-errors" hidden={!open}>
                  {s.errors.map((e) => (
                    <div key={e.shape} className="step-error">
                      <h3 className="step-error-shape">
                        {e.shape ? <code>{e.shape}</code> : <span className="muted">No error message</span>}{" "}
                        <span className="muted">{plural(e.cases, "test case", "test cases")}</span>
                      </h3>
                      {e.example && e.example !== e.shape && <p className="muted step-error-example">{e.example}</p>}
                      <ul className="step-tests">
                        {e.tests.map((t) => (
                          <li key={t.test_key}>
                            <Link to={hrefOf(t)}>{t.name}</Link> <code className="muted">{t.text}</code>
                          </li>
                        ))}
                        {e.more != null && e.more > 0 && <li className="muted">and {e.more} more</li>}
                      </ul>
                    </div>
                  ))}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
```

- [ ] **Step 7: Wire the page and the test default**

`src/pages/RunDetailPage.tsx`: add `import FailedSteps from "../components/FailedSteps";` and right after the `FailureGroups` line:

```tsx
          {run.failed + run.errored > 0 && <FailedSteps projectId={Number(projectId)} runId={run.id} />}
```

`src/test/server.ts`, after the failure-groups default:

```ts
  // Run pages and failed-step tooltips ask for the run's failed steps; tests about them override this
  http.get("/api/v1/projects/:projectId/runs/:runId/failed-steps", () => HttpResponse.json({ steps: [] })),
```

- [ ] **Step 8: Styles** — in `src/index.css` after the `.cause-list summary:hover` rule:

```css
/* Run page: failed steps across test cases, one disclosure row per step */
.step-list { list-style: none; margin: 0; padding: 0; }
.step-list > li { padding: var(--space-3) 0; border-bottom: 1px solid var(--grid); scroll-margin-top: var(--space-6); }
.step-list > li:last-child { border-bottom: 0; padding-bottom: 0; }
.step-head { display: flex; align-items: flex-start; gap: var(--space-2); min-height: 24px; padding: 0; background: none; border: 0; color: var(--text); font: inherit; text-align: left; cursor: pointer; }
.step-head:focus-visible { outline: 2px solid var(--focus, currentColor); outline-offset: 2px; border-radius: var(--radius-sm); }
.step-chevron { flex: none; margin-top: 2px; transition: transform 150ms ease-out; }
.step-head[aria-expanded="true"] .step-chevron { transform: rotate(90deg); }
@media (prefers-reduced-motion: reduce) { .step-chevron { transition: none; } }
.step-pattern { font-family: var(--font-mono); overflow-wrap: anywhere; }
.step-meta, .step-note { margin: var(--space-1) 0 0 calc(16px + var(--space-2)); font-size: 13px; }
.step-meta { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.step-errors { margin: var(--space-2) 0 0 calc(16px + var(--space-2)); display: grid; gap: var(--space-3); }
.step-error-shape { margin: 0; font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.step-error-example { margin: var(--space-1) 0 0; font-size: 12.5px; overflow-wrap: anywhere; }
.step-tests { margin: var(--space-1) 0 0; padding-left: var(--space-4); font-size: 13px; }
.step-tests li { min-height: 24px; overflow-wrap: anywhere; }
```

(Use the focus token the rest of `index.css` uses for `:focus-visible`; if it is not `--focus`, use that one and drop the fallback.)

- [ ] **Step 9: Run the tests**

Run: `cd $WT/dashboard && npx vitest run src/lib/failedSteps.test.ts src/components/FailedSteps.test.tsx src/pages/RunDetailPage.test.tsx && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 10: DESIGN.md** — after the `### Feature Page` paragraph add:

```markdown
### Failed Steps (run page)
A card "Failed steps" under "Failures by cause" on a run with a failed Cucumber step (spec `docs/superpowers/specs/2026-10-14-failed-steps-across-cases-design.md`). One row per step, most test cases first: a 24px disclosure button (`aria-expanded`, chevron turning 90°, no motion under reduced motion) holding the step's pattern in mono ("When I search {…}"), then a Graphite line in tabular figures, "failed in 12 test cases · failing since run #430, 14 Oct (5 runs) · last passed in run #429" ("new in this run", "failing for more than 50 runs" or "… 90 days" when capped). A step grouped by text adds a muted note: "Grouped by step text: update the collector to 0.8.0 to group parameter variations." Open, a row lists its error groups: the shape in mono as an `h3` with its count, one real example message in muted text, and the test cases, each linked to its case as of this run (`cases/12?run=61`, the lowest case number when several link the test) or, without a case, to its history, followed by the step text it ran in muted mono; "and N more" past 50. Each row is `#step-<key>`: a link there opens and scrolls to it. The card renders nothing until loaded and nothing for a run without failed steps; a failed request is an Error Banner with Retry inside the card.
```

- [ ] **Step 11: Commit**

```bash
cd $WT && git add dashboard/src DESIGN.md
git commit -m "feat(dashboard): Failed steps on the run page, one row per step definition with its errors and since when

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Failed-step tooltip line

**First:** invoke the `ui-ux-pro-max` skill and check the tooltip line (one link, wording, 12.5px, contrast in both themes) before editing.

**Files:**
- Modify: `dashboard/src/api/analytics.ts:212-215` (`LatestResult.failed_step`)
- Modify: `dashboard/src/lib/failedSteps.ts` (append `StepSpread`, `useStepSpread`)
- Modify: `dashboard/src/components/FailedStepTip.tsx`
- Modify: `dashboard/src/pages/CaseEditorPage.tsx:~236,314`, `dashboard/src/pages/FeaturePage.tsx:52-61,~109,201-206`
- Modify: `dashboard/src/index.css` (after `.failed-tip-meta`)
- Modify docs: `DESIGN.md` (append to the Failed Steps section)
- Test: `dashboard/src/pages/CaseAsOfRun.test.tsx` (append)

**Interfaces:**
- Consumes: Task 12 `failedStepsQuery`, `spreadText`, `stepHref`; Task 4 `failed_step.key`.
- Produces: `interface StepSpread { text: string; href: string }`; `useStepSpread(projectId: number, results: (LatestResult | null | undefined)[]): (result: LatestResult | null | undefined) => StepSpread | undefined`; `FailedStepTip` prop `spread?: StepSpread`.

- [ ] **Step 1: Write the failing tests** — append to `src/pages/CaseAsOfRun.test.tsx`:

```tsx
const STEP_KEY = "a1b2c3d4e5f60718";
let stepRequests: string[] = [];
function withSteps(answer: object) {
  stepRequests = [];
  server.use(http.get(`${P}/runs/:runId/failed-steps`, ({ params }) => {
    stepRequests.push(String(params.runId));
    return HttpResponse.json(answer);
  }));
}
const spreadStep = (cases: number, runs: number) => ({ steps: [{
  key: STEP_KEY, by: "definition", pattern: "When I search {…}", cases, errors: [],
  since: { run_id: runs === 1 ? 5 : 430, started_at: "2026-10-01T10:00:00Z", runs, capped: false } }] });
const keyed = { ...failedInRun, failed_step: { ...failedInRun.failed_step, key: STEP_KEY } };

test("the tooltip says how many other test cases failed at the step, linking to its row on the run page", async () => {
  setup({ results: { [KEY.toLowerCase()]: keyed } });
  withSteps(spreadStep(12, 5));
  renderAt("/projects/42/cases/7?run=5");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  act(() => (document.querySelector(".gk-failed") as HTMLElement).focus());
  const tip = await screen.findByRole("tooltip");
  const link = await within(tip).findByRole("link", { name: "Also failed in 11 other test cases in this run · failing since run #430" });
  expect(link).toHaveAttribute("href", `/projects/42/runs/5#step-${STEP_KEY}`);
  expect(stepRequests).toEqual(["5"]);
});

test("only this test case, new in this run", async () => {
  setup({ results: { [KEY.toLowerCase()]: keyed } });
  withSteps(spreadStep(1, 1));
  renderAt("/projects/42/cases/7?run=5");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  act(() => (document.querySelector(".gk-failed") as HTMLElement).focus());
  expect(await within(await screen.findByRole("tooltip")).findByRole("link", { name: "Only this test case · new in this run" })).toBeInTheDocument();
});

test("without a step key (an older server) the tooltip has no spread line and asks nothing", async () => {
  setup({ results: { [KEY.toLowerCase()]: failedInRun } });
  withSteps(spreadStep(12, 5));
  renderAt("/projects/42/cases/7?run=5");
  await waitFor(() => expect(document.querySelector(".gk-failed")).not.toBeNull());
  act(() => (document.querySelector(".gk-failed") as HTMLElement).focus());
  expect(await screen.findByRole("tooltip")).not.toHaveTextContent(/Also failed|Only this test case/);
  expect(stepRequests).toEqual([]);
});

test("a feature page asks once per run for all its cards", async () => {
  setup({ results: { [KEY.toLowerCase()]: keyed, [OTHER.toLowerCase()]: { ...keyed, failed_step: { text: "Then it is saved", line: 8, key: STEP_KEY } } } });
  withSteps(spreadStep(2, 5));
  renderAt("/projects/42/cases/feature?path=f.feature&run=5");
  await waitFor(() => expect(document.querySelectorAll(".gk-failed").length).toBe(2));
  await waitFor(() => expect(stepRequests).toEqual(["5"]));
});
```

(Add `act` and `within` to the `@testing-library/react` import of the file.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd $WT/dashboard && npx vitest run src/pages/CaseAsOfRun.test.tsx`
Expected: the four new tests FAIL (no spread link / no request).

- [ ] **Step 3: Types** — `src/api/analytics.ts`, `LatestResult.failed_step` becomes:

```ts
  started_at: string; message: string | null;
  /** `key` names the step across the run's test cases (the run page's `#step-<key>`); `definition`/`pattern` from collector 0.8.0. */
  failed_step?: { text: string; line?: number; definition?: string; pattern?: string; key?: string };
```

- [ ] **Step 4: Hook** — append to `src/lib/failedSteps.ts` (add `import { useQueries } from "@tanstack/react-query";` and `import type { LatestResult } from "../api/analytics";` at the top):

```ts
/** The tooltip's spread line and the link to the step's row on the run page. */
export interface StepSpread { text: string; href: string }

/** For a page's failed-step tooltips: one failed-steps request per run among `results` (shared by every card and
 *  with the run page), then each result's line, once its run has answered (plan ruling R8). */
export function useStepSpread(projectId: number, results: (LatestResult | null | undefined)[]) {
  const runIds = [...new Set(results.flatMap((r) => (r?.failed_step?.key ? [r.run_id] : [])))].sort((a, b) => a - b);
  const answers = useQueries({ queries: runIds.map((runId) => failedStepsQuery(projectId, runId)) });
  return (result: LatestResult | null | undefined): StepSpread | undefined => {
    const key = result?.failed_step?.key;
    if (!result || !key) return undefined;
    const step = answers[runIds.indexOf(result.run_id)]?.data?.steps.find((s) => s.key === key);
    return step ? { text: spreadText(step), href: stepHref(projectId, result.run_id, key) } : undefined;
  };
}
```

- [ ] **Step 5: Tooltip** — `src/components/FailedStepTip.tsx` becomes:

```tsx
import { Link } from "react-router-dom";
import type { LatestResult } from "../api/analytics";
import type { StepSpread } from "../lib/failedSteps";
import { ago } from "../overview/format";

/** What the failed-step tooltip says: the error, how wide the step failed in that run (linking to its row on the run
 *  page), where and when it ran, and the way to the run. */
export default function FailedStepTip({ projectId, result, spread }: { projectId: number; result: LatestResult; spread?: StepSpread }) {
  const meta = [result.branch, result.environment, ago(result.started_at)].filter(Boolean).join(" · ");
  return (
    <>
      <span>{result.message || "No error message"}</span>
      {spread && <Link className="failed-tip-spread" to={spread.href}>{spread.text}</Link>}
      <span className="failed-tip-meta">{meta}</span>
      <Link to={`/projects/${projectId}/runs/${result.run_id}`}>Open run</Link>
    </>
  );
}
```

`src/index.css` after `.failed-tip-meta`: `.failed-tip-spread { font-size: 12.5px; }`

- [ ] **Step 6: Pages**

`CaseEditorPage.tsx`: import `{ useStepSpread }` from `"../lib/failedSteps"`; right after `useScrollToFailure(runId, failedLine != null);` add `const spreadOf = useStepSpread(id, [latest.data]);` and the tip becomes `<FailedStepTip projectId={id} result={latest.data} spread={spreadOf(latest.data)} />`.

`FeaturePage.tsx`: import `{ useStepSpread }` from `"../lib/failedSteps"` and `type StepSpread` from the same; after the `resultOf` line add `const spreadOf = useStepSpread(id, cases.map(resultOf));`. `BackgroundFailure` takes a `spread?: StepSpread` prop and passes it to its `FailedStepTip`; the card passes `spread={spreadOf(failure.result)}` to `BackgroundFailure` and to the `FailedStepTip` in `GherkinBlock`'s `failed`.

- [ ] **Step 7: Run the tests**

Run: `cd $WT/dashboard && npx vitest run src/pages/CaseAsOfRun.test.tsx src/pages/CaseLastResult.test.tsx src/pages/FeaturePage.test.tsx && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 8: DESIGN.md** — append to `### Failed Steps (run page)`:

```markdown
The failed-step tooltip on the test case page and the feature page's cards adds, under the error, one 12.5px link to the step's row on the run page: "Also failed in 11 other test cases in this run · failing since run #430" (or "Only this test case · new in this run", "… failing for more than 50 runs"). It is loaded with the tooltip's run, one request per run on the page shared by every card; without it (an older server, a request that failed) the tooltip is as before.
```

- [ ] **Step 9: Commit**

```bash
cd $WT && git add dashboard/src DESIGN.md
git commit -m "feat(dashboard): the failed-step tooltip says how wide the step failed in its run, linking to its row

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Product docs

**Files:** `README.md:79`, `PRODUCT.md:24-28`, `docs/SETUP.md` (where the red failed step and collector 0.6.0 are explained; `grep -n "failed step" docs/SETUP.md`), `TODO.md`.

- [ ] **Step 1: README.md** — after the `**Failed step:**` bullet add:
  `- **Failed steps across test cases:** the run page lists each failed Cucumber step once, by its step definition, so a shared step breaking in forty scenarios reads as one problem: in how many test cases it failed, its errors grouped by shape with the test cases under each, and since which run it has been failing (and when it last passed). The failed-step tooltip says the same in one line and links to it. Grouping parameter variations (`When I search Lisbon` / `Porto`) needs collector 0.8.0; older results group by step text.`
- [ ] **Step 2: PRODUCT.md** — line 24-28 sentence `…and shows a failing scenario's failed step in red where the team reads it.` → `…shows a failing scenario's failed step in red where the team reads it, and on each run which step failed across how many test cases and since when.`
- [ ] **Step 3: docs/SETUP.md** — next to the failed-step explanation add: `From collector 0.8.0 the run page also groups a failed step across test cases by its step definition (Cucumber's match location), so one step with other parameters is one row; with an older collector the steps group by their exact text.`
- [ ] **Step 4: TODO.md** — mark the failed-steps item `[x]`, ending `phase 3 dashboard: Failed steps on the run page, tooltip line (2026-10-14).`
- [ ] **Step 5: Commit**

```bash
cd $WT && git add README.md PRODUCT.md docs/SETUP.md TODO.md
git commit -m "docs: failed steps across test cases (README, product, setup, todo)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Phase 3 gate and push

- [ ] **Step 1**: ingestion suite, collector suite, dashboard (lint, typecheck, vitest, build, template test), architecture docs: as Task 5 Steps 1-4. All pass.
- [ ] **Step 2**: gateway smoke as Task 5 Step 5 (the new `failed-steps` checks must print `ok`).
- [ ] **Step 3**: check every doc named in spec §6 changed in this branch: `git diff origin/master --stat -- collector/README.md platforms/ingestion-service/README.md DESIGN.md PRODUCT.md README.md TECHNICAL_SPECIFICATION.md SECURITY.md TODO.md` lists them all (SECURITY and collector README changed in phases 1-2, so diff against the commit before Task 1 if they are already on master).
- [ ] **Step 4**: rebase, push the gated SHA to `master`, watch CI to green (Task 5 Steps 6-7).

---

## Self-review (done while writing)

- **Spec coverage:** §2 fields → Task 6; retry → Task 7; release and floating tag → Task 8. §3.1 schema, migration, masking, remask → Tasks 1-3. §3.2 key → Task 4; shown-as and error groups → Tasks 9-10. §3.3 endpoint, `cases`, sorting, 50 tests + `more`, `since` (streak, stop on pass, stop on other failure, 50 runs, 90 days), `last_passed`, impact-subset, 404, roles → Task 10. §3.4 → Task 4. §4.1 → Task 12; §4.2 → Task 13. §5 smoke → Tasks 2, 4, 11. §6 docs → Tasks 2-4, 6-8, 11-14. §7 phases and gates → Tasks 5, 8, 15.
- **Type consistency:** `step_key(definition, text) -> (key, by)` used in Tasks 4 and 10; `failed_step_of(..., definition=None, pattern=None)` returns `key` (Task 4) and is called with 7 positional values in Task 10; `RunFailedStep`/`FailedStepSince` fields match the endpoint answer; `failedStepsQuery`, `spreadText`, `stepHref`, `StepSpread`, `useStepSpread` named the same in Tasks 12-13.
- **Review Focus:** each of the five lines has its test in the owning task (Tasks 2, 10, 10, 12, 7).
