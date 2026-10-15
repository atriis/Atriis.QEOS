# Log values follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A result's whole masked log opens on demand (run page, test case page, feature cards) with its values marked; the Runs list and a run's rows can be filtered by a log value; a crashed re-scan reports `queued`; the collector honours `contentEncoding`; the masking preview never answers 500 to an odd sample.

**Architecture:** ingestion-service adds `GET …/runs/{run_id}/results/{result_id}/log` (one SELECT of the deferred column plus the result's values), `value`/`pattern` filters on the runs list and the run detail (a correlated EXISTS over `log_values`, backed by migration 024's `(value, pattern_id)` index), `result_id` on `latest-results`, and a `queued` scan state. The dashboard adds a `LogPanel` component (fetch on click, `<mark>` on values, copy, download), a "Log value" filter on the Runs page that carries into the run page, and a "runs" link on every value chip. The collector reads `contentEncoding`.

**Tech Stack:** FastAPI 0.143, SQLAlchemy 2.1, Alembic, Pydantic 2 (ingestion); Python 3.9+ stdlib (collector); React 19, TypeScript, TanStack Query 5, react-router 7, MSW, Vitest (dashboard).

**Spec:** `docs/superpowers/specs/2026-10-15-log-values-follow-ups-design.md` (binding; read it before any task). Background: `docs/superpowers/specs/2026-10-14-log-values-design.md`, ADR-032.

## Global Constraints

- The log endpoint answers `{"log": str | null, "values": [{"name", "values"}]}`; 404 `"Run not found"` for a run outside the project, 404 `"Result not found"` for a result outside the run. The run payload (`GET /api/v1/runs/{id}`) never carries `log`.
- `value`: **1–200 characters, no NUL**, exact and case-sensitive; `pattern`: `^[a-z][a-z0-9_]{0,31}$`; `pattern` without `value` is **422**. Both on `GET /api/v1/projects/{id}/runs` and `GET /api/v1/runs/{run_id}`; the run's counts never change with the filter.
- Migration **024** (`platforms/ingestion-service/alembic/versions/024_log_values_value_index.py`, `down_revision = "023"`): index `ix_log_values_value` on `(value, pattern_id)`, nothing else.
- Scan states: `idle` | `queued` (requested > done, no `log_scan_started_at`) | `running` (with `since`). A failed pass clears `log_scan_started_at`. The card polls every **3 s** while running, every **30 s** while queued, never while idle.
- `latest-results` entries gain `result_id` (an integer). Extend, never break.
- Dashboard: `LogPanel` fetches nothing until pressed; values are wrapped in `<mark title="<pattern>">`, longer value first on overlap, text only; download file name `<test name>-run-<run id>.txt` with every character outside `[A-Za-z0-9._-]` replaced by `_`; "Copied" lives 2 s in a polite live region.
- Runs page URL keys: `value` and `pattern`; one chip "Log value <pattern>: <value>" (or "Log value: <value>"); removing it drops both keys; run links carry both keys while the filter is on. Run page: `?value=…&pattern=…` scopes the rows; note "N of M results hold <pattern> <value>" (or "hold <value>") with a "Show all results" link.
- Collector: `contentEncoding` / `content_encoding` — `IDENTITY` keeps the text, `BASE64` decodes, anything else or absent keeps today's strict-base64 guess; invalid base64 or UTF-8 never fails the parse.
- Docs are updated in the same commit as the behaviour (ADR-032, TECHNICAL_SPECIFICATION, DESIGN, ingestion README, SETUP §4.10, TODO, collector README). Tests and docs use `example.com`.
- Another session may work in this tree: stage and commit only your own paths (`git add <paths>` then `git commit -o <paths> -m …`); never `git add -A`. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Push only when the user clears a SHA.
- Every dashboard UI task starts by invoking the `ui-ux-pro-max` skill (project rule).
- Never run `scripts/smoke_gateway.sh` or a migration against the user's running stack (compose project `qeos`); migrations are checked on a throwaway `postgres:16-alpine` container.

**How to run things (Git Bash, repo root `C:/dev/github/Atriis.QEOS`):**

- **ingestion-service**, from `platforms/ingestion-service`: `PY="$HOME/.venvs/qeos-ingestion/Scripts/python.exe"` (the CI-matching venv; if missing: `py -3.11 -m venv "$HOME/.venvs/qeos-ingestion" && "$HOME/.venvs/qeos-ingestion/Scripts/python.exe" -m pip install -r requirements.txt`), then `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/<file> -q`. The full suite (`"$PY" -m pytest tests/ -q`) takes about 10 minutes. Tests run on SQLite (a temp file per run; SQLite does not enforce `ON DELETE CASCADE`).
- **collector**, from `collector/`: `CPY="$HOME/.venvs/qeos-collector/Scripts/python.exe"` (if missing: `py -3.11 -m venv "$HOME/.venvs/qeos-collector" && "$CPY" -m pip install -e . pytest cryptography`); `"$CPY" -m pytest tests/<file> -q` or `"$CPY" -m pytest -q`.
- **dashboard**, from `dashboard/`: `npx vitest run <files>`, `npm run lint`, `npm run typecheck`, `npm run build`; at the gate `npx vitest run --no-file-parallelism` (about 5 minutes).
- **Architecture docs**: `python scripts/check_architecture_docs.py` from the repo root (exit 0).
- **Smoke script**: never run it here; `bash -n scripts/smoke_gateway.sh` only.
- **Migration on PostgreSQL** (Task 1): `docker run -d --rm --name qeos-mig-check -e POSTGRES_PASSWORD=x -p 55432:5432 postgres:16-alpine`, wait for `docker exec qeos-mig-check pg_isready -U postgres` to say "accepting connections", then from `platforms/ingestion-service` with `DATABASE_URL=postgresql://postgres:x@localhost:55432/postgres SECRET_KEY=ci-test-secret`: `"$PY" -m alembic upgrade head && "$PY" -m alembic downgrade 023 && "$PY" -m alembic upgrade head`; `docker stop qeos-mig-check` at the end.
- **Writing files:** when a step says "create" or "append", write the block exactly; when it says "replace", the old text is quoted so it can be matched exactly. Prefer the editor's exact-match edit over shell heredocs for any text containing backslashes.

## Review Focus

1. **A value with characters special to URLs or HTML** (`<b>`, `&`, `%`, `?`, `#`, a space, a quote): the runs link, the Runs page filter and the run page note must carry it round-trip exactly, and the marked log must show it as text. Pinned in Task 6 (`markValues keeps text as text`), Task 7 (`the runs link encodes the value`), Task 8 (`the value filter round-trips through the URL`).
2. **A log with hundreds of values, overlapping ones, or a value that is a substring of another:** marking must prefer the longer value, never mark inside a mark, and stay fast on 64 KB. Pinned in Task 6 (`overlapping values mark the longer one`, `a 64 KB log with many values is marked in well under a second`).
3. **A result id that belongs to another run or another project in the URL:** 404 without leaking the other result's existence beyond "not found". Pinned in Task 2 (`test_a_result_of_another_run_is_404`, `test_a_run_of_another_project_is_404`).
4. **`pattern` without `value`, a value over 200 characters or with a NUL, an unknown pattern name:** 422 or an empty list, never a 500. Pinned in Task 3 (`test_pattern_without_value_is_422`, `test_an_impossible_value_is_422`, `test_an_unknown_pattern_matches_nothing`).
5. **An older server** (no `result_id` in `latest-results`, no log endpoint): the case page shows no Log button when `result_id` is absent; the panel reads a 404 as "No log for this result." Pinned in Task 6 (`a 404 reads as no log`) and Task 7 (`without a result id there is no Log button`).

## File Structure

ingestion-service (`platforms/ingestion-service/`):
- `alembic/versions/024_log_values_value_index.py` (new); `src/ingestion/models/log_pattern.py` (the index on the model).
- `src/ingestion/schemas/run.py` (`ResultLogOut`, `LogValueOut`); `src/ingestion/schemas/log_pattern.py` (`LogScanOut.state`); `src/ingestion/schemas/masking_pattern.py` (the sample validator).
- `src/ingestion/service/run_service.py` (`RunFilters.value/pattern`, `_value_rows`, `list_runs`, `list_results`, `result_log`); `src/ingestion/service/analytics_service.py` (`result_id` in `latest_results`); `src/ingestion/jobs/log_scan.py` (`scan_state`, the failed pass).
- `src/ingestion/api/v1/endpoints/runs.py` (the log endpoint, the two filters on both routes).
- Tests: `tests/unit/test_migration.py`, `tests/integration/test_result_log.py` (new), `test_runs_endpoints.py`, `test_latest_results.py`, `test_log_scan.py`, `test_log_patterns.py`, `test_masking_patterns.py`.

Collector (`collector/`): `src/qeos_collector/formats.py` (`_attachment_text`), `tests/test_cucumber.py`, `README.md`.

Dashboard (`dashboard/src/`): `api/runs.ts` (`ResultLog`, `getResultLog`, `RunFilters.value/pattern`, `getRun` opts), `api/analytics.ts` (`LatestResult.result_id`), `api/logPatterns.ts` (`LogScan.state`), `lib/logValues.ts` (`markValues`, `logFileName`), `components/LogPanel.tsx` (new) + test, `components/LogValuesLine.tsx` (runs link), `components/LogValuesCard.tsx` (queued), `pages/RunDetailPage.tsx`, `pages/RunsPage.tsx`, `pages/CaseEditorPage.tsx`, `pages/FeaturePage.tsx`, `index.css`, and their tests.

Repo: `scripts/smoke_gateway.sh`, `docs/architecture/adr/ADR-032-log-values.md`, `TECHNICAL_SPECIFICATION.md`, `DESIGN.md`, `docs/SETUP.md`, `TODO.md`, `platforms/ingestion-service/README.md`.

---

### Task 1: Migration 024 — the value index

**Files:**
- Create: `platforms/ingestion-service/alembic/versions/024_log_values_value_index.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/log_pattern.py` (`LogValue.__table_args__`)
- Test: `platforms/ingestion-service/tests/unit/test_migration.py` (append; modify `test_model_declares_the_log_value_indexes`)

**Interfaces:**
- Produces: index `ix_log_values_value` on `log_values (value, pattern_id)` in both the migration and the model (the suite's `test_migration_columns_match_models` only checks columns; the index test below checks the index).

- [ ] **Step 1: Write the failing tests.** In `tests/unit/test_migration.py`, replace the body of `test_model_declares_the_log_value_indexes` so it reads:

```python
def test_model_declares_the_log_value_indexes():
    assert {"ix_log_values_result_id", "ix_log_values_pattern_id", "ix_log_values_value"} <= {
        ix.name for ix in Base.metadata.tables["log_values"].indexes}
```

and append:

```python
def test_log_values_are_indexed_by_value(migrated_engine):
    """Migration 024: the runs search by a log value (spec 2026-10-15 §3.1) reads (value, pattern_id)."""
    indexes = {ix["name"]: ix["column_names"] for ix in inspect(migrated_engine).get_indexes("log_values")}
    assert indexes["ix_log_values_value"] == ["value", "pattern_id"]


def test_the_value_index_downgrade_drops_it(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_024.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "023")
    engine = create_engine(url)
    try:
        names = {ix["name"] for ix in inspect(engine).get_indexes("log_values")}
        assert "ix_log_values_value" not in names and "ix_log_values_result_id" in names  # 023 is still there
    finally:
        engine.dispose()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `platforms/ingestion-service`): `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_migration.py -q`
Expected: `test_model_declares_the_log_value_indexes` and `test_log_values_are_indexed_by_value` FAIL (`KeyError: 'ix_log_values_value'` / the set assertion); `test_the_value_index_downgrade_drops_it` passes already (no 024 yet) and is meaningful after Step 4.

- [ ] **Step 3: The model.** In `src/ingestion/models/log_pattern.py`, replace

```python
    __table_args__ = (
        Index("ix_log_values_result_id", "result_id"),
        # A deleted pattern's values are found by pattern
        Index("ix_log_values_pattern_id", "pattern_id"),
    )
```
with
```python
    __table_args__ = (
        Index("ix_log_values_result_id", "result_id"),
        # A deleted pattern's values are found by pattern
        Index("ix_log_values_pattern_id", "pattern_id"),
        # The runs search by a value (migration 024, spec 2026-10-15 §3.1): value first, the pattern narrows it
        Index("ix_log_values_value", "value", "pattern_id"),
    )
```

- [ ] **Step 4: The migration** — create `platforms/ingestion-service/alembic/versions/024_log_values_value_index.py`:

```python
"""log_values indexed by (value, pattern_id) for the runs search by a log value (spec 2026-10-15 §3.1)

Revision ID: 024
Revises: 023
Create Date: 2026-10-15
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_log_values_value", "log_values", ["value", "pattern_id"])


def downgrade() -> None:
    op.drop_index("ix_log_values_value", table_name="log_values")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_migration.py -q`
Expected: PASS (all).

- [ ] **Step 6: Check 024 up, down and up on PostgreSQL** (throwaway container, see "How to run things"; `downgrade 023` instead of 022). Then `docker exec qeos-mig-check psql -U postgres -c '\d log_values'`.
Expected: the three alembic commands exit 0; `\d log_values` lists `ix_log_values_value btree (value, pattern_id)`.

- [ ] **Step 7: Commit**

```bash
git add platforms/ingestion-service/alembic/versions/024_log_values_value_index.py platforms/ingestion-service/src/ingestion/models/log_pattern.py platforms/ingestion-service/tests/unit/test_migration.py
git commit -o platforms/ingestion-service/alembic/versions/024_log_values_value_index.py platforms/ingestion-service/src/ingestion/models/log_pattern.py platforms/ingestion-service/tests/unit/test_migration.py -m "feat(ingestion): migration 024 indexes log values by value for the runs search" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: The log endpoint and `result_id` on latest-results

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/schemas/run.py` (two schemas after `ResultOut`)
- Modify: `platforms/ingestion-service/src/ingestion/service/run_service.py` (imports; `result_log` after `list_results`)
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py` (imports; a route on `project_router` after `get_failed_steps`)
- Modify: `platforms/ingestion-service/src/ingestion/service/analytics_service.py` (`latest_results` entry)
- Create: `platforms/ingestion-service/tests/integration/test_result_log.py`
- Test: `platforms/ingestion-service/tests/integration/test_latest_results.py` (append)

**Interfaces:**
- Consumes: `log_value_service.values_by_result(db, ids) -> {result_id: [{"name", "values", "link_template"}]}` (existing).
- Produces (HTTP): `GET /api/v1/projects/{id}/runs/{run_id}/results/{result_id}/log` → `{"log": str | null, "values": [{"name": str, "values": [str]}]}`; `latest-results` entries carry `"result_id": int`.
- Produces (Python): `run_service.result_log(db, run_id, result_id) -> tuple[bool, Optional[str]]` (found, log); `schemas.run.LogValueOut`, `schemas.run.ResultLogOut`.

- [ ] **Step 1: Write the failing tests** — create `platforms/ingestion-service/tests/integration/test_result_log.py`:

```python
"""A result's whole masked log on demand (spec 2026-10-15 §2.1), with its values; never in the run payload."""
from datetime import datetime, timezone

import pytest

from src.ingestion.models import LogPattern, LogValue, RunResult

ALL_ROLES = ("owner", "admin", "member", "viewer", "billing_manager")
T0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
LOG = 'INFO [App] Trip id captured tripId="3960562"\nINFO [App] Route chosen routeKey="wasToBos"'


def url(run_id, result_id, project_id=1):
    return f"/api/v1/projects/{project_id}/runs/{run_id}/results/{result_id}/log"


@pytest.fixture
def logged(db, seed_run):
    """logged(log, project_id=1) -> (run, result) with the log stored and two values captured."""
    def _make(log=LOG, project_id=1):
        run = seed_run(T0, results=(("books", "passed", 5),), project_id=project_id)
        row = db.query(RunResult).filter_by(run_id=run.id).one()
        row.log = log
        trip = LogPattern(project_id=project_id, name="trip_id", pattern=r'tripId="(\d+)"')
        route = LogPattern(project_id=project_id, name="route_key", pattern=r'routeKey="([^"]+)"')
        db.add_all([trip, route])
        db.flush()
        if log:
            db.add_all([LogValue(result_id=row.id, pattern_id=trip.id, position=0, value="3960562"),
                        LogValue(result_id=row.id, pattern_id=route.id, position=0, value="wasToBos")])
        db.commit()
        return run, row
    return _make


def test_the_log_is_returned_with_its_values(client, auth, project_role, logged):
    run, row = logged()
    project_role("viewer")
    response = client.get(url(run.id, row.id), headers=auth())
    assert response.status_code == 200, response.text
    assert response.json() == {"log": LOG, "values": [
        {"name": "route_key", "values": ["wasToBos"]}, {"name": "trip_id", "values": ["3960562"]}]}


def test_a_result_without_a_log_answers_null_and_no_values(client, auth, project_role, logged):
    run, row = logged(log=None)
    project_role("viewer")
    assert client.get(url(run.id, row.id), headers=auth()).json() == {"log": None, "values": []}


@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_role_reads_the_log(client, auth, project_role, logged, role):
    run, row = logged()
    project_role(role)
    assert client.get(url(run.id, row.id), headers=auth()).status_code == 200


def test_a_result_of_another_run_is_404(client, auth, project_role, logged, seed_run, db):
    run, row = logged()
    other = seed_run(T0, results=(("quiet", "passed", 5),))
    project_role("viewer")
    response = client.get(url(other.id, row.id), headers=auth())
    assert response.status_code == 404 and response.json()["detail"] == "Result not found"
    assert client.get(url(run.id, row.id + 1000), headers=auth()).status_code == 404


def test_a_run_of_another_project_is_404(client, auth, project_role, logged):
    run, row = logged(project_id=2)
    project_role("viewer", project_id=1)
    response = client.get(url(run.id, row.id, project_id=1), headers=auth())
    assert response.status_code == 404 and response.json()["detail"] == "Run not found"


def test_the_run_payload_never_carries_the_log(client, auth, project_role, logged):
    run, _ = logged()
    project_role("viewer")
    [result] = client.get(f"/api/v1/runs/{run.id}", headers=auth()).json()["results"]
    assert "log" not in result
```

Append to `platforms/ingestion-service/tests/integration/test_latest_results.py`:

```python
def test_the_latest_result_names_its_result_id(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0, results=(("search", "passed", 5),))
    row = db.query(RunResult).filter_by(run_id=run.id).one()
    key = report_key("search")
    got = client.post(URL, json={"keys": [key]}, headers=auth()).json()["results"][key]
    assert got["result_id"] == row.id and got["run_id"] == run.id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_result_log.py tests/integration/test_latest_results.py -q`
Expected: the log tests FAIL with 404 bodies `{"detail":"Not Found"}` (no route) except `test_the_run_payload_never_carries_the_log`, which passes already; `test_the_latest_result_names_its_result_id` FAILS with `KeyError: 'result_id'`.

- [ ] **Step 3: Schemas.** In `src/ingestion/schemas/run.py`, after the `ResultOut` class, add:

```python
class LogValueOut(BaseModel):
    """One pattern's values in a result (ADR-032), values in log order."""

    name: str
    values: list[str]


class ResultLogOut(BaseModel):
    """A result's whole masked log, on demand (spec 2026-10-15 §2.1): never part of the run payload."""

    log: Optional[str] = None
    values: list[LogValueOut] = []
```

- [ ] **Step 4: Service.** In `src/ingestion/service/run_service.py`, change `from sqlalchemy import func` to `from sqlalchemy import func, select`, and after `list_results` add:

```python
def result_log(db: Session, run_id: int, result_id: int) -> tuple[bool, Optional[str]]:
    """(found, log): one result's stored, masked log, read as a column (it is deferred on the model, and the run
    payload never carries it). Not found when the result is not in that run."""
    row = db.execute(
        select(RunResult.log).where(RunResult.id == result_id, RunResult.run_id == run_id)
    ).one_or_none()
    return (False, None) if row is None else (True, row[0])
```

- [ ] **Step 5: Endpoint.** In `src/ingestion/api/v1/endpoints/runs.py`, extend the schemas import to include `LogValueOut, ResultLogOut` (keep it alphabetical inside the parentheses) and the service import to `from src.ingestion.service import failed_steps_service, impact_read, log_value_service, run_service`. After `get_failed_steps` add:

```python
@project_router.get("/{run_id}/results/{result_id}/log", response_model=ResultLogOut)
def get_result_log(
    run_id: int,
    result_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """A result's whole masked log, with the values its project's patterns found in it (spec 2026-10-15 §2.1).
    Read on demand: the run payload never carries the log."""
    run = run_service.get_run(db, run_id)
    # A run of another project is indistinguishable from a missing one
    if run is None or run.project_id != access.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    found, log = run_service.result_log(db, run.id, result_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")
    values = log_value_service.values_by_result(db, [result_id]).get(result_id, [])
    return ResultLogOut(log=log, values=[LogValueOut(name=v["name"], values=v["values"]) for v in values])
```

- [ ] **Step 6: `result_id` on latest-results.** In `src/ingestion/service/analytics_service.py`, in `latest_results`, replace

```python
        entry = {"status": r["status"], "run_id": r["run_id"], "branch": r["branch"],
```
with
```python
        entry = {"status": r["status"], "run_id": r["run_id"], "result_id": r["result_id"], "branch": r["branch"],
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_result_log.py tests/integration/test_latest_results.py tests/integration/test_runs_endpoints.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/schemas/run.py platforms/ingestion-service/src/ingestion/service/run_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py platforms/ingestion-service/src/ingestion/service/analytics_service.py platforms/ingestion-service/tests/integration/test_result_log.py platforms/ingestion-service/tests/integration/test_latest_results.py
git commit -o platforms/ingestion-service/src/ingestion/schemas/run.py platforms/ingestion-service/src/ingestion/service/run_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py platforms/ingestion-service/src/ingestion/service/analytics_service.py platforms/ingestion-service/tests/integration/test_result_log.py platforms/ingestion-service/tests/integration/test_latest_results.py -m "feat(ingestion): a result's whole masked log on demand, with its values; latest-results names the result" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Runs filtered by a log value; a run's rows scoped by one

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/service/run_service.py` (`RunFilters`, `_value_rows`, `list_runs`, `list_results`)
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py` (`list_runs`, `get_run`)
- Test: `platforms/ingestion-service/tests/integration/test_runs_endpoints.py` (append)

**Interfaces:**
- Consumes: `LogPattern`, `LogValue` (models); `NO_NUL` (existing import in runs.py).
- Produces: `RunFilters.value: Optional[str]`, `RunFilters.pattern: Optional[str]`; `run_service.list_results(db, run_id, status, value=None, pattern=None)`; `run_service.PATTERN_NAME = r"^[a-z][a-z0-9_]{0,31}$"`; HTTP `value` and `pattern` query parameters on `GET /projects/{id}/runs` and `GET /runs/{run_id}`; 422 `{"detail": "pattern needs value"}` when `pattern` comes alone.

- [ ] **Step 1: Write the failing tests.** Append to `tests/integration/test_runs_endpoints.py`:

```python
# --- log values: runs with a value, a run's rows holding it (spec 2026-10-15 §3) ---------------------------------


def with_value(db, run, name, value, project_id=1, result_index=0):
    """Gives one of the run's results a captured log value under pattern `name` (created on first use)."""
    from src.ingestion.models import LogPattern, LogValue

    pattern = db.query(LogPattern).filter_by(project_id=project_id, name=name).first()
    if pattern is None:
        pattern = LogPattern(project_id=project_id, name=name, pattern="x")
        db.add(pattern)
        db.flush()
    result = db.query(RunResult).filter_by(run_id=run.id).order_by(RunResult.id).all()[result_index]
    db.add(LogValue(result_id=result.id, pattern_id=pattern.id, position=0, value=value))
    db.commit()
    return result


def test_list_filters_by_log_value(client, auth, project_role, make_run, db):
    hit = make_run(minutes_ago=2)
    other = make_run(minutes_ago=1)
    with_value(db, hit, "trip_id", "3960562")
    with_value(db, other, "trip_id", "3960563")
    project_role("viewer")
    body = client.get("/api/v1/projects/1/runs?value=3960562", headers=auth()).json()
    assert [r["id"] for r in body] == [hit.id]
    assert client.get("/api/v1/projects/1/runs?value=396056", headers=auth()).json() == []  # exact, not a prefix


def test_list_filters_by_log_value_and_pattern(client, auth, project_role, make_run, db):
    trip = make_run(minutes_ago=2)
    route = make_run(minutes_ago=1)
    with_value(db, trip, "trip_id", "42")
    with_value(db, route, "route_key", "42")
    project_role("viewer")
    both = client.get("/api/v1/projects/1/runs?value=42", headers=auth()).json()
    assert {r["id"] for r in both} == {trip.id, route.id}
    only = client.get("/api/v1/projects/1/runs?value=42&pattern=trip_id", headers=auth()).json()
    assert [r["id"] for r in only] == [trip.id]


def test_pattern_without_value_is_422(client, auth, project_role, make_run):
    run = make_run()
    project_role("viewer")
    assert client.get("/api/v1/projects/1/runs?pattern=trip_id", headers=auth()).status_code == 422
    assert client.get(f"/api/v1/runs/{run.id}?pattern=trip_id", headers=auth()).status_code == 422


@pytest.mark.parametrize("value", ["", "a" * 201, "nul%00here"])
def test_an_impossible_value_is_422(client, auth, project_role, value):
    project_role("viewer")
    assert client.get(f"/api/v1/projects/1/runs?value={value}", headers=auth()).status_code == 422


def test_an_unknown_pattern_matches_nothing(client, auth, project_role, make_run, db):
    run = make_run()
    with_value(db, run, "trip_id", "1")
    project_role("viewer")
    assert client.get("/api/v1/projects/1/runs?value=1&pattern=nothing", headers=auth()).json() == []


def test_another_projects_value_never_matches(client, auth, project_role, make_run, db):
    theirs = make_run(project_id=2)
    with_value(db, theirs, "trip_id", "3960562", project_id=2)
    mine = make_run()
    project_role("viewer")
    assert client.get("/api/v1/projects/1/runs?value=3960562", headers=auth()).json() == []
    assert [r["id"] for r in client.get("/api/v1/projects/1/runs", headers=auth()).json()] == [mine.id]


def test_value_combines_with_the_other_filters(client, auth, project_role, make_run, db):
    green = make_run(statuses=("passed",), branch="main", minutes_ago=2)
    red = make_run(statuses=("failed",), branch="main", minutes_ago=1)
    with_value(db, green, "trip_id", "7")
    with_value(db, red, "trip_id", "7")
    project_role("viewer")
    body = client.get("/api/v1/projects/1/runs?value=7&status=failing&branch=main", headers=auth()).json()
    assert [r["id"] for r in body] == [red.id]


def test_get_run_scopes_its_rows_to_the_value_and_keeps_its_counts(client, auth, project_role, make_run, db):
    run = make_run(statuses=("passed", "failed", "passed"))
    holder = with_value(db, run, "trip_id", "3960562", result_index=1)
    project_role("viewer")
    body = client.get(f"/api/v1/runs/{run.id}?value=3960562", headers=auth()).json()
    assert [r["id"] for r in body["results"]] == [holder.id]
    assert body["total"] == 3 and body["failed"] == 1  # the run's counts describe the run
    assert client.get(f"/api/v1/runs/{run.id}?value=3960562&pattern=route_key", headers=auth()).json()["results"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_runs_endpoints.py -q -k "log_value or pattern or impossible or another_projects_value or combines or scopes"`
Expected: FAIL — the lists ignore `value` (every run comes back), `pattern` alone answers 200, the impossible values answer 200.

- [ ] **Step 3: Service.** In `src/ingestion/service/run_service.py`:
  - change the models import to `from src.ingestion.models import LogPattern, LogValue, MutedTest, Run, RunChangedFile, RunComponent, RunResult`;
  - in `RunFilters`, after `scope: Optional[str] = None  # …`, add:

```python
    # Log values (spec 2026-10-15 §3.1): runs with a result holding exactly `value`, under `pattern` when given
    value: Optional[str] = None
    pattern: Optional[str] = None
```
  - after the `RunFilters` class add:

```python
PATTERN_NAME = r"^[a-z][a-z0-9_]{0,31}$"


def _value_rows(value: str, pattern: Optional[str]):
    """The log_values rows of the enclosing RunResult that hold `value` (and `pattern`): an EXISTS, correlated to
    RunResult. Patterns belong to projects, so another project's values never match a project's runs."""
    rows = (
        select(LogValue.id)
        .join(LogPattern, LogPattern.id == LogValue.pattern_id)
        .where(LogValue.result_id == RunResult.id, LogValue.value == value)
    )
    if pattern is not None:
        rows = rows.where(LogPattern.name == pattern)
    return rows.correlate(RunResult).exists()
```
  - in `list_runs`, before `return query.order_by(…)`, add:

```python
    if f.value is not None:
        holders = select(RunResult.id).where(RunResult.run_id == Run.id, _value_rows(f.value, f.pattern))
        query = query.filter(holders.correlate(Run).exists())
```
  - replace `list_results` with:

```python
def list_results(db: Session, run_id: int, status: Optional[str], value: Optional[str] = None,
                 pattern: Optional[str] = None) -> list[RunResult]:
    query = db.query(RunResult).filter(RunResult.run_id == run_id)
    if status is not None:
        query = query.filter(RunResult.status == status)
    if value is not None:  # only the rows holding this log value (spec 2026-10-15 §3.1)
        query = query.filter(_value_rows(value, pattern))
    return query.order_by(RunResult.id).all()
```

- [ ] **Step 4: Endpoints.** In `src/ingestion/api/v1/endpoints/runs.py`:
  - in `list_runs`, after the `scope` parameter add:

```python
    # Log values (spec 2026-10-15 §3.1): exact, case-sensitive; `pattern` narrows `value` and needs it
    value: Optional[str] = Query(None, min_length=1, max_length=200, pattern=NO_NUL),
    pattern: Optional[str] = Query(None, pattern=run_service.PATTERN_NAME),
```
    and before `filters = run_service.RunFilters(` add:

```python
    if pattern is not None and value is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="pattern needs value")
```
    and pass `value=value, pattern=pattern,` to `RunFilters(...)` after `scope=scope`.
  - in `get_run`, after the `status_filter` parameter add the same two `value` / `pattern` parameters, the same 422 check right after `run = run_service.get_run(db, run_id)`'s 404 (before `db.rollback()`), and change `results = run_service.list_results(db, run.id, status_filter)` to `results = run_service.list_results(db, run.id, status_filter, value, pattern)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_runs_endpoints.py tests/integration/test_result_log.py tests/integration/test_run_compare.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/service/run_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py platforms/ingestion-service/tests/integration/test_runs_endpoints.py
git commit -o platforms/ingestion-service/src/ingestion/service/run_service.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/runs.py platforms/ingestion-service/tests/integration/test_runs_endpoints.py -m "feat(ingestion): runs filtered by a log value; a run's rows scoped to the results holding it" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The `queued` scan state and the masking preview sample

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/jobs/log_scan.py` (`scan_state`, `run_scan`, new `_clear_started`)
- Modify: `platforms/ingestion-service/src/ingestion/schemas/log_pattern.py` (`LogScanOut.state`)
- Modify: `platforms/ingestion-service/src/ingestion/schemas/masking_pattern.py` (`MaskingPreviewIn`)
- Test: `tests/integration/test_log_scan.py` (modify one, append two), `tests/integration/test_log_patterns.py` (modify one), `tests/integration/test_masking_patterns.py` (append)

**Interfaces:**
- Produces: `scan_state` → `{"state": "idle" | "queued" | "running", "since": datetime | None}`; `LogScanOut.state: Literal["idle", "queued", "running"]`; a failed pass leaves `log_scan_started_at` None.

- [ ] **Step 1: Write the failing tests.** In `tests/integration/test_log_scan.py`, in `test_a_failed_pass_stays_queued_and_the_next_run_finishes_it`, replace `assert log_scan.scan_state(db, 1)["state"] == "running"` with `assert log_scan.scan_state(db, 1) == {"state": "queued", "since": None}`, and append:

```python
def test_a_request_is_queued_until_a_pass_starts(db, logged):
    logged(1, 'tripId="1"')
    assert log_scan.scan_state(db, 1) == {"state": "idle", "since": None}
    log_scan.request_scan(db, 1)
    assert log_scan.scan_state(db, 1) == {"state": "queued", "since": None}


def test_a_pass_in_progress_is_running_since_it_started(db, session_factory, logged, monkeypatch):
    logged(1, 'tripId="1"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    real, seen = log_scan.scan_pass, []

    def observing(db_, project_id, since, batch_size):
        with session_factory() as other:
            seen.append(log_scan.scan_state(other, project_id))
        return real(db_, project_id, since, batch_size)

    monkeypatch.setattr(log_scan, "scan_pass", observing)
    assert scan(session_factory) is True
    assert seen[0]["state"] == "running" and seen[0]["since"] is not None
```

In `tests/integration/test_log_patterns.py`, replace `test_a_queued_scan_is_reported_as_running` with:

```python
def test_a_queued_scan_is_reported_as_queued(client, auth, member, db):
    log_scan.request_scan(db, 1)
    assert client.get(URL, headers=auth()).json()["scan"] == {"state": "queued", "since": None}
```

Append to `tests/integration/test_masking_patterns.py`:

```python
def test_preview_replaces_a_nul_or_a_lone_surrogate_in_the_sample_never_500(client, auth, member):
    """A crafted JSON body: the sample is cleaned like an uploaded log, not refused and not a 500."""
    import json

    body = json.dumps({"name": "customer_id", "pattern": r"CUST-\d{6}", "sample": "CUST-123456\x00 \ud800 end"})
    response = client.post(f"{URL}/preview", content=body.encode("ascii"),
                           headers={**auth(), "Content-Type": "application/json"})
    assert response.status_code == 200, response.text
    assert response.json()["masked"] == "[REDACTED:customer_id]\ufffd \ufffd end"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_log_scan.py tests/integration/test_log_patterns.py tests/integration/test_masking_patterns.py -q`
Expected: the three scan-state assertions FAIL (`running` where `queued` is expected), the `seen[0]` test passes already (kept as the guard), the masking preview test FAILS with 422 `string_unicode`.

- [ ] **Step 3: The scan state.** In `src/ingestion/jobs/log_scan.py`, replace `scan_state` with:

```python
def scan_state(db: Session, project_id: int) -> dict:
    """What GET …/log-patterns reports: idle; queued (a request waits for the next add or start-up, e.g. after a
    failed pass); running, since the current pass started."""
    row = db.get(CollectionSettings, project_id)
    if row is None or (row.log_scan_requested or 0) <= (row.log_scan_done or 0):
        return {"state": "idle", "since": None}
    if row.log_scan_started_at is None:
        return {"state": "queued", "since": None}
    return {"state": "running", "since": row.log_scan_started_at}
```

and in `run_scan` replace

```python
    except Exception:  # a background task has nobody to raise to
        logger.exception("log-value scan failed for project %s", project_id)
        return False
```
with
```python
    except Exception:  # a background task has nobody to raise to
        logger.exception("log-value scan failed for project %s", project_id)
        _clear_started(session_factory, project_id)  # the request stays queued; the state says so
        return False


def _clear_started(session_factory: sessionmaker, project_id: int) -> None:
    try:
        with session_factory() as db:
            db.execute(update(CollectionSettings).where(CollectionSettings.project_id == project_id)
                       .values(log_scan_started_at=None))
            db.commit()
    except Exception:
        logger.exception("the failed log-value scan pass of project %s could not be recorded", project_id)
```

In `src/ingestion/schemas/log_pattern.py`, change `state: Literal["idle", "running"]` to `state: Literal["idle", "queued", "running"]`.

- [ ] **Step 4: The masking preview sample.** In `src/ingestion/schemas/masking_pattern.py`, change the pydantic import to `from pydantic import BaseModel, ConfigDict, Field, field_validator`, add `from src.ingestion.schemas.collect import _replace_unstorable` after it, and replace the `MaskingPreviewIn` class with:

```python
class MaskingPreviewIn(MaskingPatternCreate):
    sample: str = Field(max_length=10_000)

    # Like an uploaded message: a NUL or a lone surrogate is replaced, never refused. Before the length check,
    # which cannot read a lone surrogate
    _clean_sample = field_validator("sample", mode="before")(
        lambda value: _replace_unstorable(value) if isinstance(value, str) else value
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_log_scan.py tests/integration/test_log_patterns.py tests/integration/test_masking_patterns.py tests/integration/test_masking_on_ingest.py -q`
Expected: PASS.

- [ ] **Step 6: Docs.** In `platforms/ingestion-service/README.md`, in the `## Log values` section's `- **Patterns:**` bullet, change `"scan": {"state": "idle" | "running", "since": … | null}` to `"scan": {"state": "idle" | "queued" | "running", "since": … | null}`; in the `- **Past runs:**` bullet, change `A scan\n  that a restart cut short, or that failed, stays queued and runs when the service starts` to `A scan\n  that a restart cut short, or that failed, is reported \`queued\` and runs when a pattern is added or the service starts`. In `TECHNICAL_SPECIFICATION.md`, in the **Log values** bullet, after `the re-scan counters \`collection_settings.log_scan_requested/done/started_at\` (migration 023)`, add `; \`GET …/log-patterns\` reports the scan as \`idle\`, \`queued\` or \`running\``.

- [ ] **Step 7: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/jobs/log_scan.py platforms/ingestion-service/src/ingestion/schemas/log_pattern.py platforms/ingestion-service/src/ingestion/schemas/masking_pattern.py platforms/ingestion-service/tests/integration/test_log_scan.py platforms/ingestion-service/tests/integration/test_log_patterns.py platforms/ingestion-service/tests/integration/test_masking_patterns.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md
git commit -o platforms/ingestion-service/src/ingestion/jobs/log_scan.py platforms/ingestion-service/src/ingestion/schemas/log_pattern.py platforms/ingestion-service/src/ingestion/schemas/masking_pattern.py platforms/ingestion-service/tests/integration/test_log_scan.py platforms/ingestion-service/tests/integration/test_log_patterns.py platforms/ingestion-service/tests/integration/test_masking_patterns.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md -m "fix(ingestion): a failed log-value scan pass is reported queued; the masking preview cleans its sample" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Collector honours `contentEncoding`

**Files:**
- Modify: `collector/src/qeos_collector/formats.py` (`_attachment_text`)
- Test: `collector/tests/test_cucumber.py` (append)
- Modify: `collector/README.md` (the `From 0.9.0 each scenario also carries \`log\`` sentence)

**Interfaces:**
- Consumes: `b64`, `log_of` helpers (existing in the test file).
- Produces: `_attachment_text` reads `contentEncoding` / `content_encoding`: `IDENTITY` keeps the text; `BASE64`, anything else or absent: strict base64 decode, else the text as it is.

- [ ] **Step 1: Write the failing tests.** Append to `collector/tests/test_cucumber.py`:

```python
# --- contentEncoding (spec 2026-10-15 §4.2) ---------------------------------------------------------------------


def encoded_step(data, encoding, key="contentEncoding"):
    return {"keyword": "When ", "name": "a", "result": {"status": "passed"},
            "attachments": [{"body": data, "media_type": "text/plain", key: encoding}]}


def test_identity_keeps_a_base64_looking_line_as_text(tmp_path):
    assert log_of(tmp_path, [encoded_step("Finished", "IDENTITY")]) == "Finished"


def test_base64_encoding_decodes(tmp_path):
    assert log_of(tmp_path, [encoded_step(b64('tripId="1"'), "BASE64")]) == 'tripId="1"'


def test_the_snake_case_spelling_and_lowercase_count(tmp_path):
    assert log_of(tmp_path, [encoded_step("Done", "identity", key="content_encoding")]) == "Done"


def test_an_unknown_encoding_is_treated_as_absent(tmp_path):
    assert log_of(tmp_path, [encoded_step(b64("guessed"), "GZIP")]) == "guessed"


def test_invalid_base64_under_base64_encoding_is_kept_as_text(tmp_path):
    assert log_of(tmp_path, [encoded_step("not base64!", "BASE64")]) == "not base64!"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `collector/`): `"$CPY" -m pytest tests/test_cucumber.py -q -k "identity or base64_encoding or snake_case or unknown_encoding or invalid_base64"`
Expected: `test_identity_keeps_a_base64_looking_line_as_text` and `test_the_snake_case_spelling_and_lowercase_count` FAIL ("Finished" and "Done" decode to bytes and come back as replacement characters); the other three pass already (today's guess) and stay as guards.

- [ ] **Step 3: Implement.** In `collector/src/qeos_collector/formats.py`, replace the end of `_attachment_text` from `    try:\n        raw = base64.b64decode(data, validate=True)` to its `return` with:

```python
    # cucumber's message formats name the encoding; the classic JSON never does and always base64-encodes
    encoding = attachment.get("contentEncoding") or attachment.get("content_encoding")
    if isinstance(encoding, str) and encoding.strip().upper() == "IDENTITY":
        return data
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return data  # a formatter that wrote the text itself (it has spaces or other non-base64 characters)
    # A cut multi-byte character or binary bytes under a text media type become U+FFFD, never a failed parse
    return raw.decode("utf-8", errors="replace")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `"$CPY" -m pytest tests/test_cucumber.py tests/test_formats.py -q`
Expected: PASS.

- [ ] **Step 5: README.** In `collector/README.md`, in the sentence that starts `From 0.9.0 each scenario also carries \`log\``, change `decoded from base64 when so encoded)` to `decoded from base64 when so encoded; an attachment's \`contentEncoding\` is honoured when present: \`IDENTITY\` keeps the text, \`BASE64\` decodes)`.

- [ ] **Step 6: Commit**

```bash
git add collector/src/qeos_collector/formats.py collector/tests/test_cucumber.py collector/README.md
git commit -o collector/src/qeos_collector/formats.py collector/tests/test_cucumber.py collector/README.md -m "fix(collector): an attachment's contentEncoding decides whether its log text is decoded" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `LogPanel` and the Log button on the run page

**Files:**
- Modify: `dashboard/src/api/runs.ts` (`ResultLog`, `getResultLog` after `getRunFailedSteps`)
- Modify: `dashboard/src/lib/logValues.ts` (`markValues`, `logFileName`), `dashboard/src/lib/logValues.test.ts` (append)
- Create: `dashboard/src/components/LogPanel.tsx`, `dashboard/src/components/LogPanel.test.tsx`
- Modify: `dashboard/src/pages/RunDetailPage.tsx` (import; the message cell), `dashboard/src/pages/RunDetailPage.test.tsx` (append)
- Modify: `dashboard/src/index.css` (after the `.log-values-note` rule)

**Interfaces:**
- Consumes (HTTP, Task 2): `GET /api/v1/projects/{id}/runs/{run_id}/results/{result_id}/log`.
- Produces (in `api/runs.ts`): `interface ResultLog { log: string | null; values: LogValueGroup[] }`, `getResultLog(projectId, runId, resultId): Promise<ResultLog>`.
- Produces (in `lib/logValues.ts`): `interface LogSegment { text: string; name?: string }`, `markValues(text: string, groups: LogValueGroup[]): LogSegment[]`, `logFileName(name: string, runId: number): string`.
- Produces: `components/LogPanel.tsx` default export `LogPanel({ projectId, runId, resultId, name }: { projectId: number; runId: number; resultId: number; name: string })`.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill before editing UI** (project rule). Read `DESIGN.md` §Log Values and the `Message` component (`dashboard/src/components/Message.tsx`), whose toggle this panel mirrors.

- [ ] **Step 1: Write the failing tests.** Append to `dashboard/src/lib/logValues.test.ts` (and add `logFileName, markValues` to its import from `./logValues`):

```ts
test("markValues wraps each value with its pattern name and keeps everything else as text", () => {
  const segments = markValues('INFO tripId="3960562" <b>&amp;</b> routeKey="wasToBos"', [
    { name: "trip_id", values: ["3960562"] },
    { name: "route_key", values: ["wasToBos"] },
  ]);
  expect(segments).toEqual([
    { text: 'INFO tripId="' }, { text: "3960562", name: "trip_id" },
    { text: '" <b>&amp;</b> routeKey="' }, { text: "wasToBos", name: "route_key" }, { text: '"' },
  ]);
  expect(markValues("plain", [])).toEqual([{ text: "plain" }]);
  expect(markValues("", [{ name: "x", values: ["x"] }])).toEqual([{ text: "" }]);
});

test("overlapping values mark the longer one, never inside a mark", () => {
  const segments = markValues("id=3960562 and 396", [
    { name: "short", values: ["396"] },
    { name: "long", values: ["3960562"] },
  ]);
  expect(segments).toEqual([
    { text: "id=" }, { text: "3960562", name: "long" }, { text: " and " }, { text: "396", name: "short" },
  ]);
});

test("a 64 KB log with many values is marked in well under a second", () => {
  const text = Array.from({ length: 3000 }, (_, i) => `INFO line ${i} tripId="${1000 + (i % 200)}"`).join("\n");
  const groups = Array.from({ length: 20 }, (_, g) => ({
    name: `p${g}`, values: Array.from({ length: 20 }, (_, i) => String(1000 + g * 20 + i)),
  }));
  const started = performance.now();
  const marked = markValues(text, groups).filter((s) => s.name).length;
  expect(performance.now() - started).toBeLessThan(1000);
  expect(marked).toBe(3000);
});

test("logFileName keeps letters, digits, dots, dashes and underscores", () => {
  expect(logFileName("Books a trip / Lisbon?", 61)).toBe("Books_a_trip_Lisbon_-run-61.txt");
  expect(logFileName("", 7)).toBe("result-run-7.txt");
});
```

Create `dashboard/src/components/LogPanel.test.tsx`:

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import LogPanel from "./LogPanel";

const URL = "/api/v1/projects/42/runs/61/results/5/log";
const LOG = 'INFO tripId="3960562"\nINFO routeKey="wasToBos"';
const VALUES = [{ name: "route_key", values: ["wasToBos"] }, { name: "trip_id", values: ["3960562"] }];

function renderPanel() {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <LogPanel projectId={42} runId={61} resultId={5} name="Books a trip" />
    </QueryClientProvider>,
  );
}

// jsdom has no object URLs: the download link only needs a href
beforeEach(() => {
  Object.defineProperty(globalThis.URL, "createObjectURL", { value: vi.fn(() => "blob:log"), configurable: true });
  Object.defineProperty(globalThis.URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
});

test("nothing is fetched until Log is pressed; then once, marked, with copy and download", async () => {
  let calls = 0;
  server.use(http.get(URL, () => { calls++; return HttpResponse.json({ log: LOG, values: VALUES }); }));
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  renderPanel();
  const button = screen.getByRole("button", { name: "Log of Books a trip" });
  expect(button).toHaveAttribute("aria-expanded", "false");
  expect(calls).toBe(0);

  await userEvent.click(button);
  const panel = await screen.findByRole("region", { name: "Log of Books a trip" });
  expect(button).toHaveAttribute("aria-expanded", "true");
  const marks = within(panel).getAllByText((_, el) => el?.tagName === "MARK");
  expect(marks.map((m) => [m.textContent, m.getAttribute("title")])).toEqual([["3960562", "trip_id"], ["wasToBos", "route_key"]]);
  expect(within(panel).getByRole("link", { name: "Download" })).toHaveAttribute("download", "Books_a_trip-run-61.txt");
  await userEvent.click(within(panel).getByRole("button", { name: "Copy log" }));
  expect(writeText).toHaveBeenCalledWith(LOG);
  expect(await within(panel).findByText("Copied")).toBeInTheDocument();

  await userEvent.click(button);
  expect(screen.queryByRole("region", { name: "Log of Books a trip" })).toBeNull();
  expect(button).toHaveFocus();
  await userEvent.click(button);
  await screen.findByRole("region", { name: "Log of Books a trip" });
  expect(calls).toBe(1);
});

test("a result without a log says so", async () => {
  server.use(http.get(URL, () => HttpResponse.json({ log: null, values: [] })));
  renderPanel();
  await userEvent.click(screen.getByRole("button", { name: "Log of Books a trip" }));
  expect(await screen.findByText("No log for this result.")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Download" })).toBeNull();
});

test("a 404 reads as no log (an older server)", async () => {
  server.use(http.get(URL, () => HttpResponse.json({ detail: "Not Found" }, { status: 404 })));
  renderPanel();
  await userEvent.click(screen.getByRole("button", { name: "Log of Books a trip" }));
  expect(await screen.findByText("No log for this result.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a failed request shows the error with a retry", async () => {
  let failures = 1;
  server.use(http.get(URL, () => failures-- > 0
    ? HttpResponse.json({ detail: "boom" }, { status: 500 })
    : HttpResponse.json({ log: "ok", values: [] })));
  renderPanel();
  await userEvent.click(screen.getByRole("button", { name: "Log of Books a trip" }));
  const alert = await screen.findByRole("alert");
  await userEvent.click(within(alert).getByRole("button", { name: /retry/i }));
  await waitFor(() => expect(screen.getByText("ok")).toBeInTheDocument());
});
```

Append to `dashboard/src/pages/RunDetailPage.test.tsx`:

```tsx
test("each row offers the result's log, fetched only when opened", async () => {
  let fetched = 0;
  server.use(
    http.get("/api/v1/runs/61", () => HttpResponse.json(detail([result]))),
    http.get("/api/v1/projects/42/runs/61/results/1/log", () => {
      fetched++;
      return HttpResponse.json({ log: "INFO boom happened", values: [] });
    }),
  );
  renderDetail();
  const button = await screen.findByRole("button", { name: "Log of test_ok" });
  expect(fetched).toBe(0);
  await userEvent.click(button);
  expect(await screen.findByText("INFO boom happened")).toBeInTheDocument();
  expect(fetched).toBe(1);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `dashboard/`): `npx vitest run src/lib/logValues.test.ts src/components/LogPanel.test.tsx src/pages/RunDetailPage.test.tsx`
Expected: FAIL (`markValues` / `logFileName` are not exported; `./LogPanel` does not resolve; no "Log of test_ok" button).

- [ ] **Step 3: API and helpers.** In `dashboard/src/api/runs.ts`, add `import type { LogValueGroup } from "./analytics";` after the `./http` import (keep imports grouped), and after `getRunFailedSteps` add:

```ts
/** A result's whole masked log with the values its project's patterns found in it (spec 2026-10-15 §2.1). Read on
 *  demand: the run payload never carries it. */
export interface ResultLog { log: string | null; values: LogValueGroup[] }

export function getResultLog(projectId: number, runId: number, resultId: number): Promise<ResultLog> {
  return apiFetch(`/api/v1/projects/${projectId}/runs/${runId}/results/${resultId}/log`);
}
```

Append to `dashboard/src/lib/logValues.ts`:

```ts
export interface LogSegment { text: string; name?: string }

/** The log cut into plain text and marked values: each occurrence of a value becomes a segment named after its
 *  pattern; on overlap the longer value wins and nothing is marked inside a mark. Linear in the text: at each
 *  position only the values that start with that character are tried. */
export function markValues(text: string, groups: LogValueGroup[]): LogSegment[] {
  const byFirst = new Map<string, { value: string; name: string }[]>();
  for (const g of groups) {
    for (const value of g.values) {
      if (!value) continue;
      const list = byFirst.get(value[0]) ?? [];
      list.push({ value, name: g.name });
      byFirst.set(value[0], list);
    }
  }
  for (const list of byFirst.values()) list.sort((a, b) => b.value.length - a.value.length);
  if (byFirst.size === 0 || text === "") return [{ text }];
  const out: LogSegment[] = [];
  let plainFrom = 0;
  let i = 0;
  while (i < text.length) {
    const hit = byFirst.get(text[i])?.find((c) => text.startsWith(c.value, i));
    if (!hit) {
      i += 1;
      continue;
    }
    if (i > plainFrom) out.push({ text: text.slice(plainFrom, i) });
    out.push({ text: hit.value, name: hit.name });
    i += hit.value.length;
    plainFrom = i;
  }
  if (plainFrom < text.length) out.push({ text: text.slice(plainFrom) });
  return out;
}

/** "<test name>-run-<id>.txt" with anything outside letters, digits, dots, dashes and underscores as "_". */
export function logFileName(name: string, runId: number): string {
  const safe = name.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "");
  return `${safe || "result"}-run-${runId}.txt`;
}
```

- [ ] **Step 4: The panel** — create `dashboard/src/components/LogPanel.tsx`:

```tsx
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../api/http";
import { getResultLog } from "../api/runs";
import { logFileName, markValues } from "../lib/logValues";
import ErrorBanner from "./ErrorBanner";

/** How long "Copied" stays. */
const NOTE_MS = 2000;

/** A result's whole masked log, on demand (spec 2026-10-15 §2.2): a "Log" button that fetches once when pressed and
 *  opens the text inline with its values marked, a copy button and a download link. A 404 (an older server, a result
 *  that is gone) reads as no log. */
export default function LogPanel({ projectId, runId, resultId, name }: {
  projectId: number; runId: number; resultId: number; name: string;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const id = useId();
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const query = useQuery({
    queryKey: ["result-log", projectId, runId, resultId],
    queryFn: () => getResultLog(projectId, runId, resultId),
    enabled: open,
    staleTime: Infinity,
  });
  const missing = query.error instanceof ApiError && query.error.status === 404;
  const log = query.data?.log ?? null;
  const segments = useMemo(() => (log == null ? [] : markValues(log, query.data?.values ?? [])), [log, query.data?.values]);
  const href = useMemo(() => (log == null ? null : URL.createObjectURL(new Blob([log], { type: "text/plain" }))), [log]);
  useEffect(() => () => { if (href) URL.revokeObjectURL(href); }, [href]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(log ?? "");
      setNote("Copied");
    } catch {
      setNote("Could not copy. Select the log and copy it by hand.");
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNote(""), NOTE_MS);
  }

  const label = `Log of ${name}`;
  return (
    <div className="log-panel">
      <button type="button" className="log-panel-toggle" aria-expanded={open} aria-controls={id} aria-label={label}
        onClick={() => setOpen((v) => !v)}>
        {open ? "Hide log" : "Log"}
      </button>
      {open && (
        <div id={id} className="log-panel-body" role="region" aria-label={label}>
          {query.isPending && <p className="muted">Loading log…</p>}
          {query.error != null && !missing && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
          {(missing || (query.data != null && log == null)) && <p className="muted">No log for this result.</p>}
          {log != null && (
            <>
              <div className="log-panel-tools">
                <button type="button" onClick={copy}>Copy log</button>
                {href && <a href={href} download={logFileName(name, runId)}>Download</a>}
                <span className="log-values-note" role="status" aria-live="polite">{note}</span>
              </div>
              <pre className="log-full">
                {segments.map((s, i) => (s.name ? <mark key={i} title={s.name}>{s.text}</mark> : s.text))}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
```

CSS — in `dashboard/src/index.css`, after the `.log-values-note { … }` rule, add:

```css
/* A result's whole log (spec 2026-10-15 §2.2): the toggle sits with the message; the body opens under it */
.log-panel { margin-top: 4px; }
.log-panel-body { margin-top: var(--space-2); }
.log-panel-tools { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); }
.log-full { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; max-height: 60vh; overflow: auto; padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-1); font-family: var(--font-mono); font-size: 12.5px; }
.log-full mark { background: var(--accent-soft); color: inherit; border-radius: 2px; padding: 0 1px; }
```

- [ ] **Step 5: The run page.** In `dashboard/src/pages/RunDetailPage.tsx`, add `import LogPanel from "../components/LogPanel";` after the `ImpactCard` import, and replace

```tsx
                      <td><Message text={r.message} name={r.name} /></td>
```
with
```tsx
                      <td>
                        <Message text={r.message} name={r.name} />
                        <LogPanel projectId={Number(projectId)} runId={run.id} resultId={r.id} name={r.name} />
                      </td>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run src/lib/logValues.test.ts src/components/LogPanel.test.tsx src/pages/RunDetailPage.test.tsx` then `npm run lint` and `npm run typecheck`.
Expected: PASS; lint and typecheck clean.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/api/runs.ts dashboard/src/lib/logValues.ts dashboard/src/lib/logValues.test.ts dashboard/src/components/LogPanel.tsx dashboard/src/components/LogPanel.test.tsx dashboard/src/pages/RunDetailPage.tsx dashboard/src/pages/RunDetailPage.test.tsx dashboard/src/index.css
git commit -o dashboard/src/api/runs.ts dashboard/src/lib/logValues.ts dashboard/src/lib/logValues.test.ts dashboard/src/components/LogPanel.tsx dashboard/src/components/LogPanel.test.tsx dashboard/src/pages/RunDetailPage.tsx dashboard/src/pages/RunDetailPage.test.tsx dashboard/src/index.css -m "feat(dashboard): a result's whole log opens on demand on the run page, values marked, copy and download" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The log on the case and feature pages; a "runs" link on every value chip

**Files:**
- Modify: `dashboard/src/api/analytics.ts` (`LatestResult.result_id`)
- Modify: `dashboard/src/components/LogValuesLine.tsx` (`projectId` prop, the runs link), `dashboard/src/components/LogValuesLine.test.tsx` (append)
- Modify: `dashboard/src/pages/CaseEditorPage.tsx` (both pill places), `dashboard/src/pages/CaseLastResult.test.tsx` (append)
- Modify: `dashboard/src/pages/FeaturePage.tsx` (the scenario card), `dashboard/src/pages/FeaturePage.test.tsx` (append)
- Modify: `dashboard/src/index.css` (after the `.log-value-copy:hover` rule)

**Interfaces:**
- Consumes: `LogPanel` (Task 6); `latest-results` `result_id` (Task 2).
- Produces: `LatestResult.result_id?: number` (absent from an older server); `LogValuesLine({ values, label, projectId })`: with `projectId` each chip gets a link named "Runs with <pattern> <value>" to `/projects/<id>/runs?value=<encoded>&pattern=<name>`.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill before editing UI** (project rule).

- [ ] **Step 1: Write the failing tests.** Append to `dashboard/src/components/LogValuesLine.test.tsx` (add `import { MemoryRouter } from "react-router-dom";` to its imports):

```tsx
test("with a project each value links to the runs holding it, the value encoded", () => {
  render(
    <MemoryRouter>
      <LogValuesLine projectId={42} values={[{ name: "route_key", values: ["a b&c?#/x"], link_template: null }]} />
    </MemoryRouter>,
  );
  const link = screen.getByRole("link", { name: "Runs with route_key a b&c?#/x" });
  expect(link).toHaveAttribute("href", "/projects/42/runs?value=a%20b%26c%3F%23%2Fx&pattern=route_key");
  expect(screen.getByRole("button", { name: "Copy route_key a b&c?#/x" })).toBeInTheDocument();
});

test("without a project there is no runs link", () => {
  render(<LogValuesLine values={PLAIN} />);
  expect(screen.queryByRole("link")).toBeNull();
});
```

Append to `dashboard/src/pages/CaseLastResult.test.tsx`:

```tsx
test("the case page offers the shown result's log and links each value to its runs", async () => {
  server.use(http.get(`${P}/runs/9/results/77/log`, () => HttpResponse.json({ log: "INFO tripId=\"3960562\"", values: [] })));
  setup(kase(), result({ status: "passed", result_id: 77, values: [
    { name: "trip_id", values: ["3960562"], link_template: null },
  ] }));
  renderCase();
  const line = await screen.findByRole("group", { name: "Log values" });
  expect(within(line).getByRole("link", { name: "Runs with trip_id 3960562" }))
    .toHaveAttribute("href", "/projects/42/runs?value=3960562&pattern=trip_id");
  await userEvent.click(screen.getByRole("button", { name: "Log of TC-7" }));
  expect(await screen.findByText(/INFO tripId=/)).toBeInTheDocument();
});

test("without a result id there is no Log button (an older server)", async () => {
  setup(kase(), result({ status: "passed", values: [] }));
  renderCase();
  await screen.findByText(/passed/i, { selector: ".badge *, .badge" });
  expect(screen.queryByRole("button", { name: /^Log of/ })).toBeNull();
});
```

Append to `dashboard/src/pages/FeaturePage.test.tsx`:

```tsx
test("a scenario card offers its result's log and links its values to their runs", async () => {
  server.use(
    http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
      [KEY]: result("passed", { result_id: 77, values: [{ name: "trip_id", values: ["3960562"], link_template: null }] }),
    } })),
    http.get(`${P}/runs/9/results/77/log`, () => HttpResponse.json({ log: "INFO tripId=\"3960562\"", values: [] })),
  );
  renderAt();
  const cards = await screen.findAllByRole("article");
  const line = await within(cards[0]).findByRole("group", { name: "Log values of TC-12" });
  expect(within(line).getByRole("link", { name: "Runs with trip_id 3960562" })).toHaveAttribute("href", "/projects/42/runs?value=3960562&pattern=trip_id");
  await userEvent.click(within(cards[0]).getByRole("button", { name: "Log of TC-12" }));
  expect(await within(cards[0]).findByText(/INFO tripId=/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/components/LogValuesLine.test.tsx src/pages/CaseLastResult.test.tsx src/pages/FeaturePage.test.tsx`
Expected: FAIL (no runs link; no "Log of TC-7" / "Log of TC-12" button).

- [ ] **Step 3: The type.** In `dashboard/src/api/analytics.ts`, in `LatestResult`, after `started_at: string; message: string | null;` add:

```ts
  /** The id of the result shown, for its log (spec 2026-10-15 §2.1); absent from an older server. */
  result_id?: number;
```

- [ ] **Step 4: The chip's runs link.** In `dashboard/src/components/LogValuesLine.tsx`:
  - add `import { Link } from "react-router-dom";` after the `lucide-react` import;
  - change the signature to `export default function LogValuesLine({ values, label = "Log values", projectId }: { values: Group[] | undefined; label?: string; projectId?: number })` and extend the doc comment with ` With \`projectId\`, each value also links to the runs that hold it.`;
  - after the copy `</button>` inside `.log-value`, add:

```tsx
                  {projectId != null && (
                    <Link className="log-value-runs" aria-label={`Runs with ${g.name} ${v}`}
                      to={`/projects/${projectId}/runs?value=${encodeURIComponent(v)}&pattern=${g.name}`}>
                      runs
                    </Link>
                  )}
```

CSS — in `dashboard/src/index.css`, after the `.log-value-copy:hover { … }` rule, add:

```css
.log-value-runs { font-size: 11.5px; padding: 0 6px; border-left: 1px solid var(--border); }
```

- [ ] **Step 5: The pages.** In `dashboard/src/pages/CaseEditorPage.tsx`, add `import LogPanel from "../components/LogPanel";` after the `LogValuesLine` import, and replace each of the two lines

```tsx
{key != null && latest.data != null && <LogValuesLine values={latest.data.values} />}
```
(keeping each line's indentation) with
```tsx
{key != null && latest.data != null && <LogValuesLine values={latest.data.values} projectId={id} />}
{key != null && latest.data?.result_id != null && <LogPanel projectId={id} runId={latest.data.run_id} resultId={latest.data.result_id} name={c?.key ?? "this case"} />}
```

In `dashboard/src/pages/FeaturePage.tsx`, add `import LogPanel from "../components/LogPanel";` after the `LogValuesLine` import, and replace

```tsx
            {result != null && <LogValuesLine values={result.values} label={`Log values of ${c.key}`} />}
```
with
```tsx
            {result != null && <LogValuesLine values={result.values} label={`Log values of ${c.key}`} projectId={id} />}
            {result?.result_id != null && <LogPanel projectId={id} runId={result.run_id} resultId={result.result_id} name={c.key} />}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run src/components/LogValuesLine.test.tsx src/pages/CaseLastResult.test.tsx src/pages/FeaturePage.test.tsx src/pages/CaseAsOfRun.test.tsx` then `npm run lint` and `npm run typecheck`.
Expected: PASS; clean.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/api/analytics.ts dashboard/src/components/LogValuesLine.tsx dashboard/src/components/LogValuesLine.test.tsx dashboard/src/pages/CaseEditorPage.tsx dashboard/src/pages/CaseLastResult.test.tsx dashboard/src/pages/FeaturePage.tsx dashboard/src/pages/FeaturePage.test.tsx dashboard/src/index.css
git commit -o dashboard/src/api/analytics.ts dashboard/src/components/LogValuesLine.tsx dashboard/src/components/LogValuesLine.test.tsx dashboard/src/pages/CaseEditorPage.tsx dashboard/src/pages/CaseLastResult.test.tsx dashboard/src/pages/FeaturePage.tsx dashboard/src/pages/FeaturePage.test.tsx dashboard/src/index.css -m "feat(dashboard): the shown result's log on the case page and the feature cards; each value links to its runs" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: The Runs page "Log value" filter, the run page scoped by it, the queued card

**Files:**
- Modify: `dashboard/src/api/runs.ts` (`RunFilters.value/pattern`, `getRun` options), `dashboard/src/api/logPatterns.ts` (`LogScan.state`)
- Modify: `dashboard/src/pages/RunsPage.tsx`, `dashboard/src/pages/RunsPage.test.tsx` (append)
- Modify: `dashboard/src/pages/RunDetailPage.tsx`, `dashboard/src/pages/RunDetailPage.test.tsx` (append)
- Modify: `dashboard/src/components/LogValuesCard.tsx`, `dashboard/src/components/LogValuesCard.test.tsx` (append)

**Interfaces:**
- Consumes (HTTP, Tasks 3 and 4): `value`/`pattern` on the runs list and the run detail; `scan.state` `queued`; `GET …/log-patterns` for the pattern names.
- Produces: `RunFilters.value?: string; pattern?: string`; `getRun(runId, status?, extra?: { value?: string; pattern?: string }, init?)`; `LogScan.state: "idle" | "queued" | "running"`.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill before editing UI** (project rule). Read `DESIGN.md` §Filter Chips.

- [ ] **Step 1: Write the failing tests.** Append to `dashboard/src/pages/RunsPage.test.tsx`:

```tsx
test("the value filter round-trips through the URL, shows one chip and carries into each run link", async () => {
  const seen: string[] = [];
  server.use(
    http.get("/api/v1/projects/42/log-patterns", () => HttpResponse.json({
      patterns: [{ id: 1, name: "trip_id", pattern: "x", link_template: null, created_at: null }], scan: { state: "idle", since: null } })),
    http.get("/api/v1/projects/42/runs", ({ request }) => {
      const q = new URL(request.url).searchParams;
      seen.push(`${q.get("value")}|${q.get("pattern")}`);
      return HttpResponse.json([run(61)]);
    }),
  );
  renderRuns("/projects/42/runs?value=a%20b%26c&pattern=trip_id");
  const chip = await screen.findByRole("button", { name: "Remove filter Log value trip_id: a b&c" });
  await waitFor(() => expect(seen).toContain("a b&c|trip_id"));
  expect(screen.getByRole("link", { name: /#61/ })).toHaveAttribute("href", "/projects/42/runs/61?value=a+b%26c&pattern=trip_id");

  await userEvent.click(chip);
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(""));
  await waitFor(() => expect(seen.at(-1)).toBe("null|null"));
});

test("the value filter is typed in More filters with a pattern from the project's list", async () => {
  server.use(
    http.get("/api/v1/projects/42/log-patterns", () => HttpResponse.json({
      patterns: [{ id: 1, name: "trip_id", pattern: "x", link_template: null, created_at: null }], scan: { state: "idle", since: null } })),
    http.get("/api/v1/projects/42/runs", () => HttpResponse.json([])),
  );
  renderRuns();
  await screen.findByRole("heading", { level: 1, name: "Runs" });
  await userEvent.type(screen.getByLabelText("Log value"), "3960562");
  await userEvent.selectOptions(await screen.findByLabelText("Pattern"), "trip_id");
  await userEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("value=3960562&pattern=trip_id"));
});
```

Append to `dashboard/src/pages/RunDetailPage.test.tsx`:

```tsx
test("with ?value the rows are the results holding it, under a note with a way back to all", async () => {
  const seen: string[] = [];
  server.use(http.get("/api/v1/runs/61", ({ request }) => {
    const q = new URL(request.url).searchParams;
    seen.push(`${q.get("value")}|${q.get("pattern")}`);
    return HttpResponse.json(detail(q.get("value") ? [result] : [result, { ...result, id: 2, name: "test_other" }]));
  }));
  renderDetail("/projects/42/runs/61?value=3960562&pattern=trip_id");
  expect(await screen.findByText("1 of 24 results hold trip_id 3960562")).toBeInTheDocument();
  await waitFor(() => expect(seen).toContain("3960562|trip_id"));
  expect(screen.queryByText("test_other")).toBeNull();
  await userEvent.click(screen.getByRole("link", { name: "Show all results" }));
  expect(await screen.findByText("test_other")).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent("/projects/42/runs/61");
});

test("a value no result holds says so, once, with the way back", async () => {
  server.use(http.get("/api/v1/runs/61", () => HttpResponse.json(detail([]))));
  renderDetail("/projects/42/runs/61?value=nothing");
  expect(await screen.findByText("No results in this run hold nothing.")).toBeInTheDocument();
  expect(screen.queryByText("No results in this run.")).toBeNull();
  expect(screen.getByRole("link", { name: "Show all results" })).toBeInTheDocument();
});
```

Append to `dashboard/src/components/LogValuesCard.test.tsx`:

```tsx
test("a queued scan says it waits", async () => {
  server.use(http.get(BASE, () => list([TRIP], { state: "queued", since: null })));
  renderCard();
  expect(await screen.findByText("Scan queued; it runs when a pattern is added or the service restarts.")).toBeInTheDocument();
});

test("the list is polled every 3 s while running, every 30 s while queued, never while idle", () => {
  expect(scanPollInterval("running")).toBe(3000);
  expect(scanPollInterval("queued")).toBe(30_000);
  expect(scanPollInterval("idle")).toBe(false);
  expect(scanPollInterval(undefined)).toBe(false);
});
```
(add `scanPollInterval` to the test file's import: `import LogValuesCard, { scanPollInterval } from "./LogValuesCard";`)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/pages/RunsPage.test.tsx src/pages/RunDetailPage.test.tsx src/components/LogValuesCard.test.tsx`
Expected: FAIL (no "Log value" chip or field; the run link has no query; no note on the run page; the queued text is absent).

- [ ] **Step 3: API types.** In `dashboard/src/api/runs.ts`, in `RunFilters` after the `scope` field add:

```ts
  /** Runs with a result holding exactly this log value (spec 2026-10-15 §3.1), under `pattern` when given. */
  value?: string;
  pattern?: string;
```
and replace `getRun` with:

```ts
export function getRun(
  runId: number,
  status?: RunStatusFilter,
  extra: { value?: string; pattern?: string } = {},
  init: { signal?: AbortSignal } = {},
): Promise<RunDetail> {
  // With `value`, only the results holding that log value come back; the run's counts are unchanged
  const q = buildQuery({ status, ...extra });
  return apiFetch(`/api/v1/runs/${runId}${q}`, init);
}
```
In `dashboard/src/api/logPatterns.ts`, change `state: "idle" | "running";` to `state: "idle" | "queued" | "running";`.

- [ ] **Step 4: The Runs page.** In `dashboard/src/pages/RunsPage.tsx`:
  - add `import { listLogPatterns } from "../api/logPatterns";` after the `../api/runs` import;
  - change `KEYS` to `["status", "branch", "environment", "ci_provider", "commit", "pr", "author", "scope", "from", "to", "value", "pattern"] as const` and `ADVANCED` to `["environment", "ci_provider", "commit", "pr", "author", "scope", "from", "to", "value", "pattern"] as const`;
  - in `FILTER_NAMES` add `value: "Log value", pattern: "Pattern",`;
  - replace `appliedFilters` with:

```tsx
function appliedFilters(v: Values): AppliedFilter[] {
  // The log value and its pattern are one filter ("Log value trip_id: 3960562"); removing it drops both keys
  return KEYS.filter((k) => v[k] !== "" && k !== "pattern").map((k) => {
    const scope = k === "scope" ? asScope(v[k]) : undefined;
    return {
      key: k,
      name: k === "value" && v.pattern ? `Log value ${v.pattern}` : FILTER_NAMES[k],
      value: k === "status" ? (v[k] === "failing" ? "With failures" : v[k] === "passing" ? "All green" : v[k])
        : k === "ci_provider" ? CI_LABELS[v[k]] ?? v[k] : k === "pr" ? `#${v[k]}`
        : scope ? SCOPE_LABELS[scope] : v[k],
    };
  });
}
```
  - in `toFilters`, add `value: v.value || undefined,` and `pattern: v.value ? v.pattern || undefined : undefined,` after `scope: asScope(v.scope),`;
  - in `patchFilters`, after `for (const [k, v] of Object.entries(patch)) { … }` and before `next.delete("offset");`, add `if (patch.value === "") next.delete("pattern");`;
  - after the `const [moreOpen, setMoreOpen] = useState(advancedActive > 0);` line (the patterns query reads `moreOpen`) add:

```tsx
  // The pattern names for the Log value filter (spec 2026-10-15 §3.2), read once More filters is open or a pattern
  // is already in the URL; a project without patterns offers none
  const patterns = useQuery({
    queryKey: ["log-patterns", id], queryFn: () => listLogPatterns(id), staleTime: 60_000,
    enabled: moreOpen || applied.pattern !== "",
  });
  const patternOptions = (patterns.data?.patterns ?? []).map((p) => ({ value: p.name, label: p.name }));
  // While the value filter is on, each run opens scoped to the results holding it
  const runSearch = applied.value
    ? `?${new URLSearchParams({ value: applied.value, ...(applied.pattern ? { pattern: applied.pattern } : {}) })}` : "";
```
  - in the "More filters" `<FilterBar>`, after the `To` label, add:

```tsx
            <label>
              Log value
              <input value={form.value} onChange={(e) => set("value", e.target.value)} maxLength={200}
                spellCheck={false} autoComplete="off" placeholder="3960562" />
            </label>
            {patternOptions.length > 0 && (
              <FilterSelect label="Pattern" value={form.pattern} emptyLabel="Any pattern" onChange={(v) => set("pattern", v)}
                options={patternOptions} />
            )}
```
  - change the run link `<Link to={`${r.id}`}>#{r.id}</Link>` to `<Link to={`${r.id}${runSearch}`}>#{r.id}</Link>`.

- [ ] **Step 5: The run page.** In `dashboard/src/pages/RunDetailPage.tsx`:
  - change `const DEFAULTS = { status: "" } as const;` to `const DEFAULTS = { status: "", value: "", pattern: "" } as const;`;
  - after `const status: RunStatusFilter | "" = …;` add:

```tsx
  // Rows scoped to a log value (spec 2026-10-15 §3.2): the counts stay the run's
  const scoped = values.value ? { value: values.value, ...(values.pattern ? { pattern: values.pattern } : {}) } : {};
```
  - change the query to `queryKey: ["run", id, status, scoped.value ?? "", scoped.pattern ?? ""]` and `queryFn: () => getRun(id, status || undefined, scoped)`;
  - right after the `<p role="status" className="muted">{query.isPlaceholderData && "Updating results…"}</p>` line add:

```tsx
          {scoped.value && (
            <p className="muted log-scope-note">
              {run.results.length === 0
                ? `No results in this run hold ${scoped.pattern ? `${scoped.pattern} ` : ""}${scoped.value}.`
                : `${run.results.length} of ${run.total} results hold ${scoped.pattern ? `${scoped.pattern} ` : ""}${scoped.value}`}
              {" "}
              <Link to={`/projects/${projectId}/runs/${run.id}${status ? `?status=${status}` : ""}`}>Show all results</Link>
            </p>
          )}
```
    and change the empty state `{run.results.length === 0 ? (\n            <p className="muted">No {status || ""} results in this run.</p>` so the generic line is skipped while scoped: `{run.results.length === 0 ? (\n            !scoped.value && <p className="muted">No {status || ""} results in this run.</p>`.

- [ ] **Step 6: The queued card.** In `dashboard/src/components/LogValuesCard.tsx`:
  - after `const SCAN_POLL_MS = 3000;` add:

```tsx
/** A queued scan waits for the next add or restart: a slow poll is enough to notice when it starts. */
const QUEUED_POLL_MS = 30_000;

/** How often the list is read again for a scan state: 3 s running, 30 s queued, not at all when idle. */
export function scanPollInterval(state: LogScan["state"] | undefined): number | false {
  return state === "running" ? SCAN_POLL_MS : state === "queued" ? QUEUED_POLL_MS : false;
}
```
    with `import type { LogScan } from "../api/logPatterns";` added to the imports;
  - replace the `refetchInterval` line with `refetchInterval: (query) => scanPollInterval(query.state.data?.scan.state),`;
  - after the `Scanning past runs…` line add:

```tsx
      {patterns.data?.scan.state === "queued" && (
        <p className="muted" role="status">Scan queued; it runs when a pattern is added or the service restarts.</p>
      )}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npx vitest run src/pages/RunsPage.test.tsx src/pages/RunDetailPage.test.tsx src/components/LogValuesCard.test.tsx src/pages/CaseAsOfRun.test.tsx` then `npm run lint`, `npm run typecheck`, `npm run build`.
Expected: PASS; clean.

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/api/runs.ts dashboard/src/api/logPatterns.ts dashboard/src/pages/RunsPage.tsx dashboard/src/pages/RunsPage.test.tsx dashboard/src/pages/RunDetailPage.tsx dashboard/src/pages/RunDetailPage.test.tsx dashboard/src/components/LogValuesCard.tsx dashboard/src/components/LogValuesCard.test.tsx
git commit -o dashboard/src/api/runs.ts dashboard/src/api/logPatterns.ts dashboard/src/pages/RunsPage.tsx dashboard/src/pages/RunsPage.test.tsx dashboard/src/pages/RunDetailPage.tsx dashboard/src/pages/RunDetailPage.test.tsx dashboard/src/components/LogValuesCard.tsx dashboard/src/components/LogValuesCard.test.tsx -m "feat(dashboard): runs filtered by a log value, the run page scoped to its holders; a queued scan says so" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Smoke, docs and the gate

**Files:**
- Modify: `scripts/smoke_gateway.sh` (after the `body_has "... with the value and its link template"` line)
- Modify: `docs/architecture/adr/ADR-032-log-values.md`, `TECHNICAL_SPECIFICATION.md`, `DESIGN.md`, `docs/SETUP.md`, `TODO.md`, `platforms/ingestion-service/README.md`

**Interfaces:** none (smoke and docs).

- [ ] **Step 1: Smoke.** In `scripts/smoke_gateway.sh`, after the line `body_has "... with the value and its link template" …`, add:

```bash
LOG_RUN_ID="$(sed -n 's/.*"run_id":\([0-9]*\).*/\1/p' "$TMP/body" | head -1)"
LOG_RESULT_ID="$(sed -n 's/.*"result_id":\([0-9]*\).*/\1/p' "$TMP/body" | head -1)"
check "the result's whole log -> ingestion-service" 200 GET \
  "$BASE/api/v1/projects/$PROJECT_ID/runs/${LOG_RUN_ID:-0}/results/${LOG_RESULT_ID:-0}/log" "${AUTH[@]}"
body_has "... masked text with its values" '"values":[{"name":"smoke_trip","values":["3960562"]}]'
check "runs searched by the log value" 200 GET "$BASE/api/v1/projects/$PROJECT_ID/runs?value=3960562&pattern=smoke_trip" "${AUTH[@]}"
body_has "... lists the run that holds it" '"branch":"smoke-log"'
```

Run: `bash -n scripts/smoke_gateway.sh`. Expected: exit 0, no output.

- [ ] **Step 2: Docs.**
  - `docs/architecture/adr/ADR-032-log-values.md`, in `## Consequences`, replace `- Not done: searching runs by value, showing the whole log, values on the run page.` with:

```markdown
- Follow-ups (spec `docs/superpowers/specs/2026-10-15-log-values-follow-ups-design.md`): the whole masked log is
  readable on demand (`GET …/runs/{run_id}/results/{result_id}/log`, never in the run payload), with its values
  marked in the dashboard, copyable and downloadable; runs and a run's rows are searchable by an exact value
  (`value`, `pattern`; index `ix_log_values_value`, migration 024); a crashed re-scan is reported `queued`.
- Not done: searching by a partial value, value chips on the run page's rows.
```
  - `TECHNICAL_SPECIFICATION.md`, in the **Read** bullet, change `runs list per project (filters: branch, failing/passing, environment, CI, commit\n  prefix, PR, author, started-at range, scope), run detail with status filter and changed\n  files,` to `runs list per project (filters: branch, failing/passing, environment, CI, commit\n  prefix, PR, author, started-at range, scope, an exact log \`value\` with an optional \`pattern\`), run detail with status and log-value filters and changed\n  files, a result's whole masked log (\`GET /projects/{id}/runs/{run_id}/results/{result_id}/log\`, with its values),`.
  - `DESIGN.md`: in `### Log Values`, append the paragraph:

```markdown
Each value chip also carries a "runs" link ("Runs with trip_id 3960562") to the Runs page filtered by that value and pattern. Next to the message on each run-page row, and under the Log values line on the test case page and the scenario cards, a **Log** toggle (`log-panel-toggle`, `aria-expanded`, named "Log of <test>") opens the result's whole masked log inline (`log-full`: mono, wrapping, 60vh scroll), fetched only when first opened; every occurrence of one of the result's values is a `mark` titled with its pattern name. Above the text: **Copy log** (with "Copied" in a polite live region) and a **Download** link (`<test>-run-<id>.txt`). "No log for this result." in Muted text when there is none, or on a 404 from an older server; a failed request is an `ErrorBanner` with Retry.
```
    and in `### Filter Chips`, after the **Applied chips** bullet, add:

```markdown
- **Log value:** on Runs, the `value` and `pattern` keys are one chip, "Log value trip_id: 3960562" (or "Log value: 3960562"); removing it drops both. While it is on, each run's link carries the two keys, and the run page shows only the results holding the value, under "3 of 120 results hold trip_id 3960562" with a "Show all results" link; the counts, tiles, failed steps and groups stay the whole run's.
```
  - `docs/SETUP.md` §4.10, after the **Setup:** paragraph add:

```markdown
**Reading and searching.** Every value chip copies its value, opens the pattern's link when there is one, and
links to the runs that hold it ("runs"). The **Log** button next to a result (run page rows, the test case page,
the feature page's cards) opens the result's whole masked log with the values marked, to copy or download. On
the Runs page, **More filters → Log value** (with an optional pattern) lists the runs holding a value; opening one
of them shows only the results that hold it, with "Show all results" to widen.
```
  - `TODO.md`, under `### C. Results, history and evidence`, change `- [ ] Search runs by a log value (the stored values make it possible).` to `- [x] Search runs by a log value: \`value\`/\`pattern\` on the runs list and the run page, a Log value filter on Runs, a "runs" link on every value chip (spec \`docs/superpowers/specs/2026-10-15-log-values-follow-ups-design.md\`).` and `- [ ] Show a result's whole log in QEOS (it is stored, masked, 64 KB).` to `- [x] Show a result's whole log: on demand on the run page, the case page and the feature cards, values marked, copy and download (same spec).`
  - `platforms/ingestion-service/README.md`: in the bullet starting `` - `GET /api/v1/projects/<id>/runs?limit=&offset=` ``, after the `branch_contains` clause add `` `value` (1–200 characters, exact and case-sensitive: runs with a result holding that log value) with an optional `pattern` (the pattern's name; needs `value`, else 422), ``; in the `## Log values` section, after the `- **Values:**` bullet, add:

```markdown
- **Reading and searching:** `GET /api/v1/projects/{id}/runs/{run_id}/results/{result_id}/log` (every role) →
  `{"log": …, "values": [{name, values}]}`, the stored masked log of one result with its values, read on demand (the
  run payload never carries it); 404 for a run of another project or a result of another run. `GET …/runs?value=`
  and `GET /api/v1/runs/{run_id}?value=` (with an optional `pattern`) find the runs, and a run's results, holding
  exactly that value (`ix_log_values_value`, migration 024).
```

- [ ] **Step 3: The gate.** From `platforms/ingestion-service`: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` — all pass. From `collector/`: `"$CPY" -m pytest -q` — all pass. From `dashboard/`: `npm run lint`, `npm run typecheck`, `npm run build`, `npx vitest run --no-file-parallelism` — clean and green. From the repo root: `python scripts/check_architecture_docs.py` — exit 0; `bash -n scripts/smoke_gateway.sh` — exit 0.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_gateway.sh docs/architecture/adr/ADR-032-log-values.md TECHNICAL_SPECIFICATION.md DESIGN.md docs/SETUP.md TODO.md platforms/ingestion-service/README.md
git commit -o scripts/smoke_gateway.sh docs/architecture/adr/ADR-032-log-values.md TECHNICAL_SPECIFICATION.md DESIGN.md docs/SETUP.md TODO.md platforms/ingestion-service/README.md -m "docs: log values follow-ups — the whole log, search by value, queued scans; smoke through the gateway" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Spec coverage (self-review)

| Spec | Task |
|---|---|
| §2.1 endpoint, 404s, `values`, never in the run payload; `result_id` on latest-results | 2 |
| §2.2 LogPanel on the three pages: fetch on press, inline, marks, copy, download, null, 404, error | 6, 7 |
| §3.1 `value`/`pattern` on the runs list and the run detail; 422; EXISTS; migration 024 index | 1, 3 |
| §3.2 Runs page filter and chip, run links carry it, run page note and "Show all results", chip runs link | 7, 8 |
| §4.1 `queued` state, cleared `started_at`, card text and polls | 4, 8 |
| §4.2 collector `contentEncoding` | 5 |
| §4.3 masking preview sample | 4 |
| §5 tests; gateway smoke | each task; 9 |
| §6 docs | 4, 5, 9 |

Decisions the plan takes where the spec is silent:
- `markValues` tries, at each position, only the values starting with that character (longest first), so marking is linear in the text; a value that is a prefix of a longer one is marked only where the longer does not match.
- The run page's "Show all results" keeps a `status` filter in force and drops only `value` and `pattern`.
- The Runs page offers the Pattern select only when the project has patterns; the value field is always there.
- `getRun` gains an `extra` object rather than two positional parameters, so existing callers are untouched.
- The masking preview keeps its `max_length=10_000` sample; only the cleaning is added.
