# Log values Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project defines regular-expression patterns in Settings; every test result's log is captured by the collector, masked and stored; the values the patterns find are shown on every Last runs bar's tooltip, on the test case page and on the feature page's scenario cards (copyable, optionally linked).

**Architecture:** ingestion-service stores `test_results.log` (masked, cut at 64 KB, deferred), `log_patterns`, `log_values` and a per-project re-scan counter on `collection_settings` (migration 023). Values are extracted on upload from the masked log (RE2, at most one capture group, values touching a masking marker skipped); adding a pattern queues a re-scan of the last 90 days that runs after the response under a per-project lock and is resumed at start-up. `run-strip` and `latest-results` gain `values`. Collector 0.9.0 sends `log` from Cucumber text attachments and JUnit `system-out`, retrying once without it on an older platform's 422. The dashboard adds a Log values card next to Masking, value lines in the bar tooltips, and a copyable value line under the last-result pills. The test repository's logger attaches each printed line to the running scenario.

**Tech Stack:** FastAPI 0.143, SQLAlchemy 2.1, Alembic, Pydantic 2, google-re2 (ingestion-service); Python 3.9+ stdlib (collector); React 19, TypeScript, TanStack Query 5, MSW, Vitest (dashboard); Node 24, cucumber-js 12 (test repository).

**Spec:** `docs/superpowers/specs/2026-10-14-log-values-design.md` (binding; read it before any task).

## Global Constraints

- The log is cut to **64 KB of UTF-8** (`settings.MAX_TEXT_BYTES = 65536` in ingestion, `junit.MAX_TEXT_BYTES = 65536` in the collector), keeping the start, never rejected. Masking runs before the cut.
- A value is cut to **200 characters**; at most **20 values per pattern per result**, distinct, in order of first appearance (`position`).
- At most **20 patterns per project**; a pattern is at most **256 characters**, compiled with **RE2** (`custom_masking.compile_pattern`), never matching empty text, with **at most one capture group** (with a group the value is the group's text; without, the whole match).
- Pattern name: `^[a-z][a-z0-9_]{0,31}$` (the masking name format), unique per project.
- `link_template`: optional, **at most 500 characters**, `https://` only (no `javascript:`, `data:`, `http:`), a host, **`{value}` exactly once** and not inside the host. The value is **URL-encoded** when the link is built (dashboard), and the client checks the template again.
- Re-scan: logs of the **last 90 days** only (by `test_runs.created_at`), batches, idempotent, **one scan per project at a time**; patterns added during a scan join it.
- Tooltip: at most **5 values per pattern**, then `+N more`; one line per pattern with values, values comma-separated; every bar, whatever its status.
- Values come from the **masked** log: masking first, then capture.
- Migration **023** (`platforms/ingestion-service/alembic/versions/023_log_values.py`, `down_revision = "022"`). Collector version **0.9.0** (tag `collector-v0.9.0`; the floating `collector-v0` follows it).
- Extend, never break: `run-strip` entries and `latest-results` entries only gain `values`; the Last runs bars stay `Link`s; the run-detail payload never carries `log`.
- Every 422 from `…/log-patterns` about a field is `{"detail": {"code": "name" | "pattern" | "link_template" | "limit", "message": "…"}}`; a duplicate name is 409 `{"detail": {"code": "name", "message": "…"}}`.
- Docs are updated in the same commit as the behaviour they describe (ADR-032, SETUP, SECURITY, PRODUCT, TODO, TECHNICAL_SPECIFICATION, DESIGN, README, the collector, ingestion and gateway READMEs). Tests and docs use `example.com` addresses.
- Another session works in separate worktrees: stage and commit only your own paths (`git add <paths>` then `git commit -o <paths> -m …`); never `git add -A`, never push. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Every dashboard UI task starts by invoking the `ui-ux-pro-max` skill (project rule).
- Never run `scripts/smoke_gateway.sh` or a migration against the user's running stack (compose project `qeos`); migrations are checked on a throwaway `postgres:16-alpine` container.

**How to run things (Git Bash, repo root `C:/dev/github/Atriis.QEOS`):**

- **ingestion-service**, from `platforms/ingestion-service`:
  `PY=/c/dev/projects/QA-Vision-Platform/platforms/ingestion-service/.venv/Scripts/python.exe` then
  `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/<file> -q` (one file) or `… -m pytest tests/ -q` (all).
  That venv works (36 masking/strip/latest tests passed with it at planning time) but has older pins (SQLAlchemy 2.0.29, FastAPI 0.104) and imports `qeos_shared` from the old checkout. For the delivery gate (Task 8) create a venv that matches CI:
  `py -3.11 -m venv "$HOME/.venvs/qeos-ingestion" && "$HOME/.venvs/qeos-ingestion/Scripts/python.exe" -m pip install -r requirements.txt` (run from `platforms/ingestion-service`; it installs `../../shared` editable), then use `PY="$HOME/.venvs/qeos-ingestion/Scripts/python.exe"`.
  Tests run on SQLite (`tests/conftest.py`: a temp file per run, tables created per test; SQLite does not enforce `ON DELETE CASCADE`, so deletes of children are explicit in code).
- **collector**, from `collector/`: create once `py -3.11 -m venv "$HOME/.venvs/qeos-collector" && "$HOME/.venvs/qeos-collector/Scripts/python.exe" -m pip install -e . pytest cryptography`, then `CPY="$HOME/.venvs/qeos-collector/Scripts/python.exe"; "$CPY" -m pytest -q` (all) or `"$CPY" -m pytest tests/<file> -q`. (CI: `python -m pip install . pytest cryptography` then `python -m pytest -q`.)
- **dashboard**, from `dashboard/`: `npx vitest run <files>`, `npm run lint`, `npm run typecheck`, `npm run build`. The full suite has flaky 15 s timeouts under load: run the touched files, and at the delivery gate `npx vitest run --no-file-parallelism`.
- **Architecture docs**: `python scripts/check_architecture_docs.py` from the repo root (exit 0). It reads every `include_router` prefix and checks the gateway routes it to the right service.
- **Smoke script**: never run it here; check its syntax with `bash -n scripts/smoke_gateway.sh`.
- **Migration on PostgreSQL** (Task 1): a throwaway container on port 55432, removed afterwards:
  ```bash
  docker run -d --rm --name qeos-mig-check -e POSTGRES_PASSWORD=x -p 55432:5432 postgres:16-alpine
  docker exec qeos-mig-check pg_isready -U postgres   # repeat until "accepting connections"
  ```
  then alembic from `platforms/ingestion-service` with `DATABASE_URL=postgresql://postgres:x@localhost:55432/postgres`, and `docker stop qeos-mig-check` at the end.
- **Test repository** (`C:/dev/github/Atriis.Test.Automation.OBT`): `node --test src/utils/logger.check.js`, `npx eslint src/utils/logger.js src/utils/logger.check.js tests/support/hooks.js`.

## Review Focus

1. **A link template or a value that tries to leave the URL.** `javascript:`, `data:`, `http:`, `{value}` in the host (`https://{value}.example.com/`), `{value}` twice or missing, credentials (`https://a@b/`), a template over 500 characters: the server answers 422 `link_template`. In the dashboard a value such as `../admin`, `..`, `@evil.example`, `a#b` or `x?y=1` must stay inside the template's path segment or query (encoded), never change the host, and `.`/`..` give no link at all (the chip still copies); a template that is not https (an old row, a tampered response) gives no link. Pinned in Task 3 (`test_a_link_template_that_could_leave_the_url_is_refused`) and Task 14 (`linkFor keeps every value inside the template`, `a template that is not https gives no link`).
2. **A pattern that matches thousands of times in one log.** A `(\d)`-style pattern on a 64 KB log must store at most 20 values and stop reading after 1,000 matches, so an upload stays fast whatever the patterns. Pinned in Task 3 (`test_a_pattern_matching_thousands_of_times_keeps_twenty_values_and_stops_reading`, `test_matches_after_the_first_thousand_are_not_read`).
3. **A log with binary or base64 attachments, or invalid UTF-8.** Images and other non-text attachments are never part of `log`; base64 text is decoded, invalid UTF-8 becomes U+FFFD instead of failing the parse; text that is not base64 is kept as it is; a NUL or a lone surrogate reaching the server is replaced, never a 500 or a 422. Pinned in Task 9 (`test_images_and_other_media_never_join_the_log`, `test_invalid_utf8_in_an_attachment_is_replaced_not_fatal`, `test_plain_text_data_is_kept_as_it_is`) and Task 2 (`test_a_nul_or_a_lone_surrogate_in_the_log_is_replaced_not_rejected`).
4. **A re-scan running twice, or racing with uploads.** A second scan for the same project while one runs must not start (it is picked up by the running one); a pattern added during a pass must still get values for the results that pass already walked; a result valued at upload must not get its values twice when a scan reaches it; a crashed pass stays queued and finishes on the next run. Pinned in Task 5 (`test_one_scan_per_project_at_a_time`, `test_a_pattern_added_during_a_pass_gets_its_values`, `test_a_result_valued_at_upload_is_not_valued_twice_by_the_scan`, `test_a_failed_pass_stays_queued_and_the_next_run_finishes_it`).
5. **Masked text overlapping a capture.** `token=(\S+)` on `token=[REDACTED:token]`, or a group that covers part of a marker, must capture nothing; a value next to a marker is still captured; the preview shows the same; the re-mask job removes values that became masked. Pinned in Task 3 (`test_a_value_touching_a_masking_marker_is_not_captured`), Task 6 (`test_preview_never_shows_a_masked_value`) and Task 7 (`test_a_re_masked_log_has_its_values_read_again`).

## File Structure

ingestion-service (`platforms/ingestion-service/`):

- `alembic/versions/023_log_values.py` (new) — `test_results.log`, `log_patterns`, `log_values`, `collection_settings.log_scan_*`.
- `src/ingestion/models/log_pattern.py` (new) — `LogPattern`, `LogValue`; `models/run.py` (`RunResult.log`, deferred); `models/collection_settings.py` (scan counters); `models/__init__.py`.
- `src/ingestion/utils/log_values.py` (new) — limits, `LogPatternError`, `CompiledLogPattern`, `validate_name`, `compile_log_pattern`, `validate_link_template`, `extract`.
- `src/ingestion/service/log_pattern_service.py` (new) — list, compile, add, delete patterns.
- `src/ingestion/service/log_value_service.py` (new) — rows from a log, replace a result's values, read values per result and per (test, run).
- `src/ingestion/jobs/log_scan.py` (new) — request, state, per-project lock, scan pass, run, resume.
- `src/ingestion/schemas/collect.py` (`ResultIn.log`), `schemas/log_pattern.py` (new), `api/v1/endpoints/log_patterns.py` (new), `api/v1/api.py`, `api/main.py` (start-up resume), `core/config.py` (two settings).
- `src/ingestion/service/ingest_service.py` (mask, cut, store `log`; values at upload), `service/analytics_service.py` (`values` in run-strip and latest-results), `jobs/remask.py`, `jobs/retention.py`, `api/v1/endpoints/export.py`.
- Tests: `tests/conftest.py`, `tests/unit/test_migration.py`, `tests/unit/test_log_values.py` (new), `tests/integration/test_collect_log.py` (new), `tests/integration/test_log_values_on_upload.py` (new), `tests/integration/test_log_scan.py` (new), `tests/integration/test_log_patterns.py` (new), `tests/integration/test_remask_job.py`, `test_export.py`, `test_retention_job.py`, `test_run_strip.py`, `test_latest_results.py`.

Repo: `gateway/nginx.conf.template`, `gateway/README.md`, `scripts/smoke_gateway.sh`, `docs/architecture/adr/ADR-032-log-values.md` (new), `docs/architecture/adr/INDEX.md`, `docs/SETUP.md`, `SECURITY.md`, `PRODUCT.md`, `TODO.md`, `TECHNICAL_SPECIFICATION.md`, `DESIGN.md`, `README.md`, `platforms/ingestion-service/README.md`.

Collector (`collector/`): `src/qeos_collector/formats.py` (Cucumber `log`), `junit.py` (`system-out`), `upload.py` (retry without `log`), `__init__.py` (0.9.0), `README.md`, tests `test_cucumber.py`, `test_junit.py`, `test_upload.py`, `test_package.py`.

Dashboard (`dashboard/src/`): `api/logPatterns.ts` (new), `api/analytics.ts` (`LogValueGroup`, `values`), `lib/logValues.ts` (new: `valueLines`, `mergeValues`, `linkFor`), `lib/featureQueries.ts` (`mergeStrips` merges values), `components/LogValuesCard.tsx` (new), `components/LogValuesLine.tsx` (new), `components/RunStrip.tsx`, `pages/ProjectSettingsPage.tsx`, `pages/CaseEditorPage.tsx`, `pages/FeaturePage.tsx`, `index.css`, `test/server.ts`, and their tests.

Test repository (`C:/dev/github/Atriis.Test.Automation.OBT`): `src/utils/logger.js`, `src/utils/logger.check.js` (new), `tests/support/hooks.js`.

---

## Delivery 1 — ingestion-service

### Task 1: Migration 023, models, ADR-032

**Files:**
- Create: `platforms/ingestion-service/alembic/versions/023_log_values.py`
- Create: `platforms/ingestion-service/src/ingestion/models/log_pattern.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/run.py` (imports; `RunResult`, after `failed_step_pattern`)
- Modify: `platforms/ingestion-service/src/ingestion/models/collection_settings.py`
- Modify: `platforms/ingestion-service/src/ingestion/models/__init__.py`
- Test: `platforms/ingestion-service/tests/unit/test_migration.py` (append)
- Create: `docs/architecture/adr/ADR-032-log-values.md`; Modify: `docs/architecture/adr/INDEX.md`

**Interfaces:**
- Produces (in `src.ingestion.models.log_pattern`): `LOG_VALUE_LENGTH = 200`; `class LogPattern(Base)` (table `log_patterns`: `id`, `project_id`, `name` String(32), `pattern` String(256), `link_template` String(500) nullable, `created_by_user_id`, `created_at`; unique `uq_log_pattern_project_name`); `class LogValue(Base)` (table `log_values`: `id`, `result_id` FK `test_results.id` ON DELETE CASCADE, `pattern_id` FK `log_patterns.id` ON DELETE CASCADE, `position` Integer, `value` String(200); indexes `ix_log_values_result_id`, `ix_log_values_pattern_id`). Both exported from `src.ingestion.models`.
- Produces: `RunResult.log` (Text, nullable, **deferred**: load it with `undefer(RunResult.log)` or select the column); `CollectionSettings.log_scan_requested` (int, default 0), `.log_scan_done` (int, default 0), `.log_scan_started_at` (aware datetime or None).

- [ ] **Step 1: Write the failing migration tests** — append to `platforms/ingestion-service/tests/unit/test_migration.py`:

```python
def test_log_values_tables_and_columns(migrated_engine):
    """Migration 023 (ADR-032): the result's log, the patterns, their values and the re-scan counters."""
    inspector = inspect(migrated_engine)
    assert "log" in {c["name"] for c in inspector.get_columns("test_results")}
    scan = {c["name"]: c for c in inspector.get_columns("collection_settings")}
    assert {"log_scan_requested", "log_scan_done", "log_scan_started_at"} <= set(scan)
    assert not scan["log_scan_requested"]["nullable"] and scan["log_scan_started_at"]["nullable"]
    patterns = {c["name"]: c for c in inspector.get_columns("log_patterns")}
    assert patterns["name"]["type"].length == 32 and patterns["pattern"]["type"].length == 256
    assert patterns["link_template"]["type"].length == 500 and patterns["link_template"]["nullable"]
    values = {c["name"]: c for c in inspector.get_columns("log_values")}
    assert values["value"]["type"].length == 200 and not values["position"]["nullable"]
    indexes = {ix["name"]: ix["column_names"] for ix in inspector.get_indexes("log_values")}
    assert indexes["ix_log_values_result_id"] == ["result_id"]
    assert indexes["ix_log_values_pattern_id"] == ["pattern_id"]
    cascades = {fk["referred_table"]: fk["options"].get("ondelete") for fk in inspector.get_foreign_keys("log_values")}
    assert cascades == {"test_results": "CASCADE", "log_patterns": "CASCADE"}


def test_a_log_pattern_name_is_unique_per_project(migrated_engine):
    insert = "INSERT INTO log_patterns (project_id, name, pattern) VALUES (:project, 'trip_id', 'x')"
    with migrated_engine.begin() as conn:
        conn.execute(text(insert), {"project": 1})
        conn.execute(text(insert), {"project": 2})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text(insert), {"project": 1})


def test_scan_counters_default_to_zero(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text("INSERT INTO collection_settings (project_id) VALUES (5)"))
        row = conn.execute(text(
            "SELECT log_scan_requested, log_scan_done, log_scan_started_at FROM collection_settings")).one()
    assert tuple(row) == (0, 0, None)


def test_model_declares_the_log_value_indexes():
    assert {"ix_log_values_result_id", "ix_log_values_pattern_id"} <= {
        ix.name for ix in Base.metadata.tables["log_values"].indexes}


def test_log_values_downgrade_drops_them(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_023.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "022")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert not {"log_patterns", "log_values"} & set(inspector.get_table_names())
        results = {c["name"] for c in inspector.get_columns("test_results")}
        assert "log" not in results and "failed_step_definition" in results  # 022 is still there
        assert not {"log_scan_requested", "log_scan_done", "log_scan_started_at"} & {
            c["name"] for c in inspector.get_columns("collection_settings")}
    finally:
        engine.dispose()


def test_log_values_postgres_path_adds_the_log_without_a_rewrite(monkeypatch):
    """On PostgreSQL the nullable log column is IF NOT EXISTS (metadata only, as 022)."""
    import importlib.util
    from unittest.mock import MagicMock

    spec = importlib.util.spec_from_file_location("m023", SERVICE_ROOT / "alembic" / "versions" / "023_log_values.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = MagicMock()
    fake.get_bind.return_value.dialect.name = "postgresql"
    monkeypatch.setattr(module, "op", fake)
    module.upgrade()
    executed = " ".join(str(call.args[0]) for call in fake.execute.call_args_list)
    assert "ALTER TABLE test_results ADD COLUMN IF NOT EXISTS log TEXT" in executed
    assert {call.args[0] for call in fake.create_table.call_args_list} == {"log_patterns", "log_values"}
    module.downgrade()
    executed = " ".join(str(call.args[0]) for call in fake.execute.call_args_list)
    assert "ALTER TABLE test_results DROP COLUMN IF EXISTS log" in executed


def test_the_log_is_loaded_only_when_asked():
    """Run pages load results by the thousand and never show the log."""
    assert RunResult.__mapper__.attrs["log"].deferred is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `platforms/ingestion-service`): `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_migration.py -q`
Expected: the seven new tests FAIL (`NoSuchTableError: log_patterns`, `KeyError: 'log'`, `FileNotFoundError … 023_log_values.py`); the existing ones pass.

- [ ] **Step 3: Create the models** — `platforms/ingestion-service/src/ingestion/models/log_pattern.py`:

```python
"""Log-value patterns and the values they found in each result's masked log (ADR-032)."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from src.ingestion.db.base import Base

LOG_VALUE_LENGTH = 200


class LogPattern(Base):
    """A project's pattern for values in its test logs: RE2, at most one capture group, an optional https link."""

    __tablename__ = "log_patterns"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_log_pattern_project_name"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    name = Column(String(32), nullable=False)
    pattern = Column(String(256), nullable=False)
    link_template = Column(String(500), nullable=True)
    created_by_user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LogValue(Base):
    """One distinct value one pattern found in one result's log; `position` is its order of first appearance.
    The rows go with their result and with their pattern (ON DELETE CASCADE; the code also deletes them explicitly,
    because SQLite, the tests, does not enforce it)."""

    __tablename__ = "log_values"
    __table_args__ = (
        Index("ix_log_values_result_id", "result_id"),
        # A deleted pattern's values are found by pattern
        Index("ix_log_values_pattern_id", "pattern_id"),
    )

    id = Column(Integer, primary_key=True)
    result_id = Column(Integer, ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False)
    pattern_id = Column(Integer, ForeignKey("log_patterns.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    value = Column(String(LOG_VALUE_LENGTH), nullable=False)
```

In `src/ingestion/models/run.py`, add `from sqlalchemy.orm import deferred` after the `sqlalchemy.ext.hybrid` import, and in `RunResult` after the `failed_step_pattern` column:

```python
    # The result's log (ADR-032, migration 023): its text attachments or system-out as the collector sent them, masked
    # like details and cut at 64 KB. Deferred: run pages load results by the thousand and never show it; the export,
    # the re-mask job and the log-value scan ask for it (undefer or the column itself)
    log = deferred(Column(Text, nullable=True))
```

In `src/ingestion/models/collection_settings.py` (its imports already have `Column`, `DateTime`, `Integer` and `text`), append to the class:

```python
    # The log-value re-scan (ADR-032, migration 023). Adding a pattern bumps log_scan_requested; a pass that finishes
    # sets log_scan_done to the number it started from. A scan is queued or running while requested > done;
    # log_scan_started_at is the current pass's start (None between passes)
    log_scan_requested = Column(Integer, nullable=False, default=0, server_default=text("0"))
    log_scan_done = Column(Integer, nullable=False, default=0, server_default=text("0"))
    log_scan_started_at = Column(DateTime(timezone=True), nullable=True)
```

In `src/ingestion/models/__init__.py`, add `from src.ingestion.models.log_pattern import LogPattern, LogValue` after the `job_heartbeat` import and add `"LogPattern", "LogValue"` to `__all__` (after `"JobHeartbeat"`).

- [ ] **Step 4: Create the migration** — `platforms/ingestion-service/alembic/versions/023_log_values.py`:

```python
"""test_results.log, log_patterns, log_values and the log-value re-scan counters (ADR-032)

Revision ID: 023
Revises: 022
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _postgres():
        # A nullable column without a default is a metadata-only change: the large test_results table is not
        # rewritten. IF NOT EXISTS lets a re-run go through
        op.execute("ALTER TABLE test_results ADD COLUMN IF NOT EXISTS log TEXT")
    else:
        with op.batch_alter_table("test_results") as batch:
            batch.add_column(sa.Column("log", sa.Text(), nullable=True))
    # Constant defaults: metadata-only on PostgreSQL 11+ as well
    with op.batch_alter_table("collection_settings") as batch:
        batch.add_column(sa.Column("log_scan_requested", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("log_scan_done", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("log_scan_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "log_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("pattern", sa.String(length=256), nullable=False),
        sa.Column("link_template", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "name", name="uq_log_pattern_project_name"),
    )
    op.create_index("ix_log_patterns_id", "log_patterns", ["id"])
    op.create_index("ix_log_patterns_project_id", "log_patterns", ["project_id"])
    op.create_table(
        "log_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pattern_id", sa.Integer(), sa.ForeignKey("log_patterns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
    )
    op.create_index("ix_log_values_result_id", "log_values", ["result_id"])
    op.create_index("ix_log_values_pattern_id", "log_values", ["pattern_id"])


def downgrade() -> None:
    op.drop_index("ix_log_values_pattern_id", table_name="log_values")
    op.drop_index("ix_log_values_result_id", table_name="log_values")
    op.drop_table("log_values")
    op.drop_index("ix_log_patterns_project_id", table_name="log_patterns")
    op.drop_index("ix_log_patterns_id", table_name="log_patterns")
    op.drop_table("log_patterns")
    with op.batch_alter_table("collection_settings") as batch:
        batch.drop_column("log_scan_started_at")
        batch.drop_column("log_scan_done")
        batch.drop_column("log_scan_requested")
    if _postgres():
        op.execute("ALTER TABLE test_results DROP COLUMN IF EXISTS log")
    else:
        with op.batch_alter_table("test_results") as batch:
            batch.drop_column("log")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_migration.py -q`
Expected: PASS (all, including `test_migration_columns_match_models`).

- [ ] **Step 6: Check 023 up, down and up on PostgreSQL** (throwaway container, never the `qeos` stack):

```bash
docker run -d --rm --name qeos-mig-check -e POSTGRES_PASSWORD=x -p 55432:5432 postgres:16-alpine
docker exec qeos-mig-check pg_isready -U postgres   # repeat until it prints "accepting connections"
cd platforms/ingestion-service
export DATABASE_URL=postgresql://postgres:x@localhost:55432/postgres SECRET_KEY=ci-test-secret
unset PYTHONPATH
"$PY" -m alembic upgrade head && "$PY" -m alembic downgrade 022 && "$PY" -m alembic upgrade head
docker exec qeos-mig-check psql -U postgres -c '\d log_values' -c '\d collection_settings' -c "SELECT column_name FROM information_schema.columns WHERE table_name='test_results' AND column_name='log'"
unset DATABASE_URL
docker stop qeos-mig-check
```
Expected: the three alembic commands exit 0; `\d log_values` lists both foreign keys with `ON DELETE CASCADE` and both indexes; `collection_settings` has the three `log_scan_*` columns; the last query returns one row `log`.

- [ ] **Step 7: ADR-032** — create `docs/architecture/adr/ADR-032-log-values.md`:

```markdown
# ADR-032: Log values — patterns a project defines, applied to each result's masked log, shown on every run

Status: Accepted (2026-10-14) · Spec: `docs/superpowers/specs/2026-10-14-log-values-design.md`

## Context
People want to see, on every run of a test case, values the test logged, such as the trip a booking scenario created
(`INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"`). Console output cannot be tied to a
scenario (lines interleave, runs are parallel), and the Cucumber report carried no log lines.

## Decision
- **The log travels with the result.** The test repository attaches each logged line to the running scenario; the
  collector (0.9.0) sends each result's `log` (Cucumber text attachments in step order, JUnit `system-out`), cut to
  64 KB. Other formats send none.
- **Mask first, then capture.** Ingestion masks the log with the built-in and the project's masking patterns, cuts it
  to 64 KB and stores it in `test_results.log` (migration 023, deferred so run pages never load it). Values are read
  from the masked log only; a value touching a masking marker is never captured.
- **Patterns are regular expressions, like masking patterns.** `log_patterns` (≤ 20 per project, name
  `^[a-z][a-z0-9_]{0,31}$`, ≤ 256 characters, RE2, at most one capture group, optional https `link_template` with
  `{value}` once). `log_values` holds one row per distinct value per pattern per result (≤ 20, cut to 200
  characters, ordered by first appearance); rows cascade with their result and their pattern.
- **Past runs are re-scanned.** Adding a pattern bumps a counter on `collection_settings`; a scan of the last 90
  days runs after the response, in batches, under a per-project PostgreSQL advisory lock (one scan per project),
  replacing values idempotently; patterns added meanwhile make it pass again; a queued scan is resumed when
  ingestion-service starts.
- **Read paths extend, never break.** `run-strip` entries and `latest-results` entries gain `values`; the dashboard
  shows them in the Last runs tooltips (text only) and under the last-result pills (copyable, linked when the pattern
  has a template; the dashboard URL-encodes the value and checks the template again).

## Consequences
- Logs are stored data: masked before storage, deleted by retention with their results, included in the export.
- Values hidden by masking cannot be captured (said in the Settings help).
- Logs older than 90 days get no values for a new pattern; a log over 64 KB loses its end, and a pattern stops
  reading a log after 1,000 matches.
- Older collectors send no `log`; collector 0.9.0 against an older platform retries once without it.
- Not done: searching runs by value, showing the whole log, values on the run page.
```

In `docs/architecture/adr/INDEX.md`, add after the ADR-031 row:

```markdown
| [ADR-032](ADR-032-log-values.md) | Log values: each result's log is masked, cut to 64 KB and stored; per-project RE2 patterns (one capture group, optional https link) capture values from the masked log at upload and in a 90-day re-scan when a pattern is added; `run-strip` and `latest-results` carry them for the Last runs tooltips and the case page |
```

- [ ] **Step 8: Commit**

```bash
git add platforms/ingestion-service/alembic/versions/023_log_values.py platforms/ingestion-service/src/ingestion/models/log_pattern.py platforms/ingestion-service/src/ingestion/models/run.py platforms/ingestion-service/src/ingestion/models/collection_settings.py platforms/ingestion-service/src/ingestion/models/__init__.py platforms/ingestion-service/tests/unit/test_migration.py docs/architecture/adr/ADR-032-log-values.md docs/architecture/adr/INDEX.md
git commit -o platforms/ingestion-service/alembic/versions/023_log_values.py platforms/ingestion-service/src/ingestion/models/log_pattern.py platforms/ingestion-service/src/ingestion/models/run.py platforms/ingestion-service/src/ingestion/models/collection_settings.py platforms/ingestion-service/src/ingestion/models/__init__.py platforms/ingestion-service/tests/unit/test_migration.py docs/architecture/adr/ADR-032-log-values.md docs/architecture/adr/INDEX.md -m "feat(ingestion): migration 023 for log values (log, patterns, values, re-scan counters; ADR-032)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Upload `log`: masked, cut at 64 KB, stored

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/schemas/collect.py` (`ResultIn`)
- Modify: `platforms/ingestion-service/src/ingestion/service/ingest_service.py` (`_request_hash`, the results loop in `ingest`)
- Create: `platforms/ingestion-service/tests/integration/test_collect_log.py`
- Modify: `platforms/ingestion-service/README.md` (`## Limits`, `## Masking`), `TECHNICAL_SPECIFICATION.md` (upload bullet), `SECURITY.md` (Masking bullet)

**Interfaces:**
- Consumes: `RunResult.log` (Task 1).
- Produces: `ResultIn.log: Optional[str]` (NUL and lone surrogates replaced by U+FFFD); each stored row's `log` is the masked text cut by `truncate_utf8(…, settings.MAX_TEXT_BYTES)`; the request hash leaves `log` out while it is null. The rows dict built in `ingest` carries the key `"log"` (Task 4 reads `row["log"]`).

- [ ] **Step 1: Write the failing tests** — create `platforms/ingestion-service/tests/integration/test_collect_log.py`:

```python
"""Each result's log (ADR-032): masked like details, cut at 64 KB, stored; old uploads still replay."""
import hashlib
import json

from src.ingestion.core.config import settings
from src.ingestion.models import RunResult
from src.ingestion.schemas.collect import RunUpload
from src.ingestion.service import ingest_service
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

TOKEN = "ghp_" + "a" * 36
LOG = 'INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"'


def stored(db):
    db.expire_all()
    return db.query(RunResult).order_by(RunResult.id).all()


def post(client, key, results, idem=None):
    return client.post(URL, json=upload_body(results=results), headers=key_headers(key, idem=idem))


def test_the_log_is_stored(client, make_key, db):
    _, key = make_key(project_id=1)
    assert post(client, key, [{"name": "books", "status": "passed", "log": LOG}]).status_code == 201
    [row] = stored(db)
    assert row.log == LOG


def test_the_log_is_masked_before_it_is_stored(client, make_key, db):
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "books", "status": "passed", "log": f"{LOG}\nGITHUB_TOKEN={TOKEN}"}])
    [row] = stored(db)
    assert TOKEN not in row.log and "[REDACTED:" in row.log and row.log.startswith(LOG)
    # `redacted` stays about what the run page shows: message, details and the failed step
    assert row.redacted is False


def test_a_long_log_is_cut_at_64_kb_never_rejected(client, make_key, db):
    _, key = make_key(project_id=1)
    assert post(client, key, [{"name": "long", "status": "passed", "log": "é" * 40_000}]).status_code == 201
    [row] = stored(db)
    assert len(row.log.encode("utf-8")) <= settings.MAX_TEXT_BYTES
    assert row.log == "é" * (settings.MAX_TEXT_BYTES // 2)  # cut on a character boundary, the start kept
    assert row.truncated is False  # `truncated` stays about message and details


def test_masking_happens_before_the_cut(client, make_key, db):
    _, key = make_key(project_id=1)
    log = "x" * (settings.MAX_TEXT_BYTES - 16) + " " + TOKEN
    post(client, key, [{"name": "edge", "status": "passed", "log": log}])
    [row] = stored(db)
    assert "ghp_" not in row.log


def test_a_nul_or_a_lone_surrogate_in_the_log_is_replaced_not_rejected(client, make_key, db):
    _, key = make_key(project_id=1)
    # json.dumps writes the surrogate as \ud800, which is valid JSON
    response = post(client, key, [{"name": "odd", "status": "passed", "log": "trip\x00id \ud800 end"}])
    assert response.status_code == 201, response.text
    [row] = stored(db)
    assert row.log == "trip\ufffdid \ufffd end"


def test_results_without_a_log_store_null(client, make_key, db):
    _, key = make_key(project_id=1)
    client.post(URL, json=upload_body(), headers=key_headers(key))
    assert all(r.log is None for r in stored(db))


def test_an_upload_hashed_before_migration_023_still_replays(client, make_key):
    """A part stored before the upgrade, resent after it: its results have no log key."""
    _, key = make_key(project_id=1)
    body = upload_body()
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-023")).status_code == 201
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-023")).status_code == 200
    data = RunUpload.model_validate(body).model_dump(mode="json")
    for result in data["results"]:
        result.pop("log", None)
        if result.get("failed_step") is None:
            result.pop("failed_step", None)
    for name, default in ingest_service._LATER_RUN_FIELDS.items():
        if data["run"].get(name, default) == default:
            data["run"].pop(name, None)
    old = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert ingest_service._request_hash(RunUpload.model_validate(body)) == old


def test_the_log_is_part_of_the_request_hash(client, make_key):
    _, key = make_key(project_id=1)
    assert post(client, key, [{"name": "t", "status": "passed", "log": "a"}], idem="k-log").status_code == 201
    assert post(client, key, [{"name": "t", "status": "passed", "log": "b"}], idem="k-log").status_code == 409
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_collect_log.py -q`
Expected: FAIL — uploads with `log` answer 422 (`extra_forbidden`), `row.log` is None.

- [ ] **Step 3: Accept and store the log.** In `schemas/collect.py`, in `ResultIn`, after `failed_step`:

```python
    # The result's log (ADR-032, collector 0.9.0): masked and cut to 64 KB by the service, never rejected
    log: Optional[str] = None
```
and change the free-text validator line to:

```python
    _clean_text = field_validator("message", "details", "log", mode="after")(_replace_unstorable)
```

In `service/ingest_service.py`, in `_request_hash`, extend the results loop so it starts:

```python
    # Result fields added by migrations 021, 022 and 023: absent from the hash while null, for the same reason
    for result in data["results"]:
        if result.get("log") is None:
            result.pop("log", None)
        step = result.get("failed_step")
```
(the rest of the loop is unchanged). In `ingest`, inside `for result in upload.results:`, replace the lines from `step_pattern, pattern_kinds = …` through `details, cut_details = …` with:

```python
            step_pattern, pattern_kinds = mask(step.pattern if step else None, patterns)
            log, log_kinds = mask(result.log, patterns)
            kinds = message_kinds | details_kinds | step_kinds | definition_kinds | pattern_kinds
            # The log counts in the redactions metric; `redacted` stays about the text the run page shows
            masked_kinds.update(kinds | log_kinds)
            message, cut_message = truncate_utf8(message, settings.MAX_TEXT_BYTES)
            details, cut_details = truncate_utf8(details, settings.MAX_TEXT_BYTES)
            log = truncate_utf8(log, settings.MAX_TEXT_BYTES)[0]
```
and add to the row dict, after `"failed_step_pattern": …`:

```python
                "log": log,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_collect_log.py tests/integration/test_collect_failed_step.py tests/integration/test_masking_on_ingest.py tests/integration/test_collect_endpoint.py -q`
Expected: PASS.

- [ ] **Step 5: Docs.** In `platforms/ingestion-service/README.md`:
  - under `## Limits`, after the `failed_step` bullet, add:
    `- A result may carry \`log\` (a string: the scenario's text attachments or the test case's \`system-out\`, sent by collector 0.9.0). It is masked, cut to 64 KB and stored in \`test_results.log\` (migration 023); it is never rejected for its size and never returned by the run endpoints.`
  - in `## Masking`, change the first sentence to start `Before a result is stored, its \`message\`, \`details\`, \`log\` and the failed step's …` and after the bullet `- Masking happens before the 64 KB cut, …` add `- A result's \`redacted\` flag covers what the run page shows (message, details, the failed step); masking in the log counts in \`qav_ingest_redactions_total\` only.`

  In `TECHNICAL_SPECIFICATION.md`, in the upload bullet that ends `A 422 never echoes the submitted value (no \`input\` or \`ctx\`).`, append: ` Optional \`results[].log\` (string; masked, cut to 64 KB, stored in \`test_results.log\`, migration 023; left out of the request hash while null).`

  In `SECURITY.md`, at the end of the **Masking.** bullet, append: ` Each result's log (sent by collector 0.9.0 for log values, ADR-032) is masked the same way before it is stored and cut to 64 KB; it is never shown in full.`

- [ ] **Step 6: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/schemas/collect.py platforms/ingestion-service/src/ingestion/service/ingest_service.py platforms/ingestion-service/tests/integration/test_collect_log.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md SECURITY.md
git commit -o platforms/ingestion-service/src/ingestion/schemas/collect.py platforms/ingestion-service/src/ingestion/service/ingest_service.py platforms/ingestion-service/tests/integration/test_collect_log.py platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md SECURITY.md -m "feat(ingestion): store each result's log, masked and cut at 64 KB" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Pattern validation and value extraction

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/utils/log_values.py`
- Create: `platforms/ingestion-service/tests/unit/test_log_values.py`

**Interfaces:**
- Consumes: `custom_masking.compile_pattern`, `custom_masking.validate_name`, `redaction.MARKER_PREFIX`.
- Produces (in `src.ingestion.utils.log_values`): constants `MAX_VALUE_LENGTH = 200`, `MAX_VALUES_PER_PATTERN = 20`, `MAX_LOG_PATTERNS_PER_PROJECT = 20`, `MAX_LINK_TEMPLATE_LENGTH = 500`, `MAX_MATCHES_READ = 1000`, `PLACEHOLDER = "{value}"`; `class LogPatternError(ValueError)` with `.field: str` (`"name"`, `"pattern"`, `"link_template"`, `"limit"`); `@dataclass(frozen=True) class CompiledLogPattern(id: Optional[int], name: str, regex)`; `validate_name(name: str) -> str`; `compile_log_pattern(pattern: str) -> re2 regex`; `validate_link_template(template: Optional[str]) -> Optional[str]` (None for none/blank, else the stripped template); `extract(text: Optional[str], patterns: Iterable[CompiledLogPattern]) -> list[tuple[Optional[int], int, str]]` (pattern id, position, value).

- [ ] **Step 1: Write the failing tests** — create `platforms/ingestion-service/tests/unit/test_log_values.py`:

```python
"""Log-value patterns (ADR-032): validation and extraction from a masked log."""
import pytest

from src.ingestion.utils import log_values
from src.ingestion.utils.log_values import CompiledLogPattern, LogPatternError, compile_log_pattern, extract

LOG = "\n".join([
    'INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"',
    'INFO 20:23:25 [App] Route chosen routeKey="wasToBos"',
    'INFO 20:23:26 [App] Trip id captured from booking flow tripId="3960563"',
    'INFO 20:23:27 [App] Trip id captured again tripId="3960562"',
])


def pattern(regex, name="trip_id", pattern_id=1):
    return CompiledLogPattern(pattern_id, name, compile_log_pattern(regex))


def values(text, *patterns):
    return [(pid, pos, value) for pid, pos, value in extract(text, patterns)]


def test_with_one_group_the_value_is_the_groups_text_distinct_in_log_order():
    assert values(LOG, pattern(r'tripId="(\d+)"')) == [(1, 0, "3960562"), (1, 1, "3960563")]


def test_without_a_group_the_value_is_the_whole_match():
    assert values("booked TRIP-12 and TRIP-13", pattern(r"TRIP-\d+")) == [(1, 0, "TRIP-12"), (1, 1, "TRIP-13")]


def test_each_pattern_has_its_own_positions():
    trip, route = pattern(r'tripId="(\d+)"'), pattern(r'routeKey="([^"]+)"', "route_key", 2)
    assert values(LOG, trip, route) == [(1, 0, "3960562"), (1, 1, "3960563"), (2, 0, "wasToBos")]


def test_a_value_is_cut_to_200_characters_and_blank_values_are_skipped():
    long = "a" * 300
    got = values(f'id="{long}" id="   " id="{long}b"', pattern(r'id="([^"]*)"'))
    assert got == [(1, 0, "a" * 200)]  # the cut values are the same value: kept once


def test_at_most_twenty_values_per_pattern():
    text = " ".join(f'tripId="{n}"' for n in range(50))
    got = values(text, pattern(r'tripId="(\d+)"'))
    assert [v for _, _, v in got] == [str(n) for n in range(20)]


def test_a_pattern_matching_thousands_of_times_keeps_twenty_values_and_stops_reading():
    text = "7 " * 32_000  # 64 KB of one value matched 32,000 times
    assert values(text, pattern(r"(\d)")) == [(1, 0, "7")]


def test_matches_after_the_first_thousand_are_not_read():
    text = 'id="1" ' * 1500 + 'id="2"'
    assert [v for _, _, v in values(text, pattern(r'id="(\d)"'))] == ["1"]


def test_a_value_touching_a_masking_marker_is_not_captured():
    masked = 'token=[REDACTED:token] user=[REDACTED:email] tripId="5" [REDACTED:jwt]9'
    assert values(masked, pattern(r"token=(\S+)")) == []
    assert values(masked, pattern(r"user=(\S{5})", "user")) == []       # a group covering part of a marker
    assert values(masked, pattern(r'tripId="(\d+)"')) == [(1, 0, "5")]  # next to a marker: still captured
    # The rule is about the value's own span: a match that starts in a marker but whose group lies outside it counts
    assert values(masked, pattern(r"\](\d)", "digit")) == [(1, 0, "9")]


def test_an_optional_group_that_took_no_part_gives_no_value():
    assert values("trip x", pattern(r"trip (\d+)?", "trip")) == []


def test_no_text_no_values():
    assert extract(None, [pattern(r"x")]) == [] and extract("", [pattern(r"x")]) == []


@pytest.mark.parametrize("regex, reason", [
    (r"(a)(b)", "at most one capture group"),
    (r"(?P<x>a)(?P<y>b)", "at most one capture group"),
    (r"x*", "matches empty text"),
    (r"(?=x)", "not a valid pattern"),
    ("a" * 257, "at most 256"),
    ("", "required"),
])
def test_a_pattern_is_refused_with_its_reason(regex, reason):
    with pytest.raises(LogPatternError) as err:
        compile_log_pattern(regex)
    assert err.value.field == "pattern" and reason in str(err.value)


def test_a_non_capturing_group_is_fine():
    assert compile_log_pattern(r'(?:trip|order)Id="(\d+)"').groups == 1


@pytest.mark.parametrize("name", ["Trip", "1trip", "trip-id", "", "a" * 33])
def test_a_bad_name_is_refused(name):
    with pytest.raises(LogPatternError) as err:
        log_values.validate_name(name)
    assert err.value.field == "name"


def test_a_link_template_is_optional_and_kept_as_given():
    assert log_values.validate_link_template(None) is None
    assert log_values.validate_link_template("  ") is None
    template = "https://backoffice.example.com/trips/{value}?tab=summary"
    assert log_values.validate_link_template(f" {template} ") == template


@pytest.mark.parametrize("template", [
    "javascript:alert(1)//{value}",
    "data:text/html,{value}",
    "http://backoffice.example.com/trips/{value}",
    "https://{value}.example.com/trips",
    "https://backoffice.example.com{value}/trips",
    "https://user@backoffice.example.com/trips/{value}",
    "https:{value}",
    "https:///trips/{value}",
    "https://backoffice.example.com/trips/",
    "https://backoffice.example.com/{value}/{value}",
    "https://backoffice.example.com/trips/{value} x",
    "https://backoffice.example.com/" + "a" * 490 + "/{value}",
])
def test_a_link_template_that_could_leave_the_url_is_refused(template):
    with pytest.raises(LogPatternError) as err:
        log_values.validate_link_template(template)
    assert err.value.field == "link_template"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_log_values.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ingestion.utils.log_values'`.

- [ ] **Step 3: Implement** — create `platforms/ingestion-service/src/ingestion/utils/log_values.py`:

```python
"""Log values (ADR-032): a project's patterns applied to a result's masked log.

Patterns come from users, so they compile like masking patterns (custom_masking.compile_pattern: RE2, linear time, at
most 256 characters, never matching empty text). A pattern has at most one capture group: with one, the value is the
group's text; without, the whole match. Values come from the masked log, and a value that touches a masking marker is
never captured.
"""
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from src.ingestion.utils import custom_masking
from src.ingestion.utils.redaction import MARKER_PREFIX

MAX_VALUE_LENGTH = 200
MAX_VALUES_PER_PATTERN = 20
MAX_LOG_PATTERNS_PER_PROJECT = 20
MAX_LINK_TEMPLATE_LENGTH = 500
# A 64 KB log can hold tens of thousands of matches of a loose pattern: each pattern stops reading a log after this
# many, so an upload stays fast whatever the project's patterns
MAX_MATCHES_READ = 1000
PLACEHOLDER = "{value}"

_MARKER = re.compile(re.escape(MARKER_PREFIX) + r"[a-z0-9_]{1,64}\]")
_LINK_RULE = ("The link must be an https:// address with a host and {value} once after the host, "
              "e.g. https://backoffice.example.com/trips/{value}")


class LogPatternError(ValueError):
    """A reason a person can act on, and the form field it belongs to: name, pattern, link_template or limit."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class CompiledLogPattern:
    id: Optional[int]  # None in a preview: nothing is stored
    name: str
    regex: "custom_masking.re2._Regexp"


def validate_name(name: str) -> str:
    try:
        return custom_masking.validate_name(name)
    except ValueError as exc:
        raise LogPatternError("name", str(exc)) from None


def compile_log_pattern(pattern: str):
    try:
        regex = custom_masking.compile_pattern(pattern)
    except ValueError as exc:
        raise LogPatternError("pattern", str(exc)) from None
    if regex.groups > 1:
        raise LogPatternError(
            "pattern",
            "A pattern has at most one capture group ( … ): the value is that group's text, or the whole match "
            "without one. Use (?: … ) for a group that is not the value",
        )
    return regex


def validate_link_template(template: Optional[str]) -> Optional[str]:
    """None for no link. Otherwise an https:// URL with a host, no credentials, and {value} exactly once after the
    host. The dashboard URL-encodes the value into it, so a value can never change the host or the path's structure."""
    if template is None or not template.strip():
        return None
    template = template.strip()
    if len(template) > MAX_LINK_TEMPLATE_LENGTH:
        raise LogPatternError("link_template", f"A link is at most {MAX_LINK_TEMPLATE_LENGTH} characters")
    if template.count(PLACEHOLDER) != 1 or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in template):
        raise LogPatternError("link_template", _LINK_RULE)
    try:
        parts = urlsplit(template)
        host = urlsplit(template.replace(PLACEHOLDER, "x")).hostname
    except ValueError:
        raise LogPatternError("link_template", _LINK_RULE) from None
    if parts.scheme.lower() != "https" or not host or "@" in parts.netloc or PLACEHOLDER in parts.netloc:
        raise LogPatternError("link_template", _LINK_RULE)
    return template


def extract(text: Optional[str], patterns: Iterable[CompiledLogPattern]) -> List[Tuple[Optional[int], int, str]]:
    """(pattern id, position, value) for each distinct value of each pattern, in order of first appearance: at most
    20 per pattern, each cut to 200 characters (distinct after the cut), blank ones skipped, and none that touches a
    masking marker. A pattern reads at most the first 1,000 matches."""
    if not text:
        return []
    markers = [m.span() for m in _MARKER.finditer(text)]
    found: List[Tuple[Optional[int], int, str]] = []
    for pattern in patterns:
        group = 1 if pattern.regex.groups == 1 else 0
        seen: List[str] = []
        for read, match in enumerate(pattern.regex.finditer(text)):
            if read >= MAX_MATCHES_READ or len(seen) >= MAX_VALUES_PER_PATTERN:
                break
            if match.group(group) is None:  # an optional group that took no part
                continue
            start, end = match.span(group)
            if any(start < marker_end and marker_start < end for marker_start, marker_end in markers):
                continue  # hidden by masking: never captured
            value = text[start:end].strip()[:MAX_VALUE_LENGTH]
            if value and value not in seen:
                seen.append(value)
        found.extend((pattern.id, position, value) for position, value in enumerate(seen))
    return found
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/unit/test_log_values.py tests/unit/test_custom_masking.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/utils/log_values.py platforms/ingestion-service/tests/unit/test_log_values.py
git commit -o platforms/ingestion-service/src/ingestion/utils/log_values.py platforms/ingestion-service/tests/unit/test_log_values.py -m "feat(ingestion): log-value pattern validation and extraction from the masked log" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: Pattern and value services; values captured at upload

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/service/log_pattern_service.py`
- Create: `platforms/ingestion-service/src/ingestion/service/log_value_service.py`
- Modify: `platforms/ingestion-service/src/ingestion/service/ingest_service.py` (imports; the results insert in `ingest`)
- Create: `platforms/ingestion-service/tests/integration/test_log_values_on_upload.py`

**Interfaces:**
- Consumes: `log_values.*` (Task 3), `LogPattern`, `LogValue` (Task 1), the rows' `"log"` key (Task 2).
- Produces (in `src.ingestion.service.log_pattern_service`): `class DuplicatePattern(Exception)`; `list_patterns(db, project_id) -> list[LogPattern]` (name order); `compiled_for(db, project_id) -> list[CompiledLogPattern]` (name order; a row that no longer compiles is skipped); `validate(name: str, pattern: str) -> CompiledLogPattern` (id None; raises `LogPatternError`); `add_pattern(db, project_id, name, pattern, link_template, user_id) -> LogPattern` (raises `LogPatternError`, including `field="limit"`, or `DuplicatePattern`); `delete_pattern(db, project_id, pattern_id) -> bool` (deletes its values too).
- Produces (in `src.ingestion.service.log_value_service`): `rows_for(result_id: int, log: Optional[str], patterns) -> list[dict]` (keys `result_id`, `pattern_id`, `position`, `value`); `replace_values(db, items: Sequence[tuple[int, Optional[str]]], patterns) -> int` (deletes these results' rows for these patterns, inserts the new ones; does not commit; returns the rows inserted).

- [ ] **Step 1: Write the failing tests** — create `platforms/ingestion-service/tests/integration/test_log_values_on_upload.py`:

```python
"""Values captured at upload (ADR-032): from the masked, stored log, with the project's own patterns."""
import pytest

from src.ingestion.models import LogPattern, LogValue, RunResult
from src.ingestion.service import log_pattern_service
from src.ingestion.utils.log_values import LogPatternError
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

TOKEN = "ghp_" + "a" * 36
TRIP = r'tripId="(\d+)"'
ROUTE = r'routeKey="([^"]+)"'


@pytest.fixture
def patterns(db):
    def _add(*pairs, project_id=1):
        rows = [LogPattern(project_id=project_id, name=name, pattern=regex) for name, regex in pairs]
        db.add_all(rows)
        db.commit()
        return rows
    return _add


def values_of(db):
    db.expire_all()
    rows = (db.query(RunResult.name, LogPattern.name, LogValue.position, LogValue.value)
            .join(LogValue, LogValue.result_id == RunResult.id).join(LogPattern, LogPattern.id == LogValue.pattern_id)
            .order_by(RunResult.id, LogPattern.name, LogValue.position))
    return [tuple(row) for row in rows]


def post(client, key, results, idem=None):
    response = client.post(URL, json=upload_body(results=results), headers=key_headers(key, idem=idem))
    assert response.status_code in (200, 201), response.text
    return response


def test_values_are_captured_at_upload(client, make_key, db, patterns):
    patterns(("trip_id", TRIP), ("route_key", ROUTE))
    _, key = make_key(project_id=1)
    post(client, key, [
        {"name": "books", "status": "passed", "log": 'tripId="3960562" routeKey="wasToBos" tripId="3960563"'},
        {"name": "quiet", "status": "passed"},
        {"name": "fails", "status": "failed", "log": 'tripId="3960562"'},
    ])
    assert values_of(db) == [
        ("books", "route_key", 0, "wasToBos"), ("books", "trip_id", 0, "3960562"), ("books", "trip_id", 1, "3960563"),
        ("fails", "trip_id", 0, "3960562"),
    ]


def test_without_a_group_the_whole_match_is_the_value(client, make_key, db, patterns):
    patterns(("trip", r"TRIP-\d+"))
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "t", "status": "skipped", "log": "made TRIP-12"}])
    assert values_of(db) == [("t", "trip", 0, "TRIP-12")]


def test_a_secret_is_masked_before_values_are_read(client, make_key, db, patterns):
    patterns(("token", r"GITHUB_TOKEN=(\S+)"))
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "t", "status": "passed", "log": f"GITHUB_TOKEN={TOKEN}"}])
    assert values_of(db) == []


def test_another_projects_patterns_never_apply(client, make_key, db, patterns):
    patterns(("trip_id", TRIP), project_id=2)
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "t", "status": "passed", "log": 'tripId="1"'}])
    assert values_of(db) == []


def test_a_replayed_upload_adds_no_values(client, make_key, db, patterns):
    patterns(("trip_id", TRIP))
    _, key = make_key(project_id=1)
    results = [{"name": "t", "status": "passed", "log": 'tripId="1"'}]
    assert post(client, key, results, idem="k-values").status_code == 201
    assert post(client, key, results, idem="k-values").status_code == 200
    assert values_of(db) == [("t", "trip_id", 0, "1")]


def test_the_pattern_service_validates_and_limits(db):
    with pytest.raises(LogPatternError) as err:
        log_pattern_service.add_pattern(db, 1, "trip_id", r"(a)(b)", None, 1)
    assert err.value.field == "pattern"
    with pytest.raises(LogPatternError) as err:
        log_pattern_service.add_pattern(db, 1, "trip_id", r"a", "http://backoffice.example.com/{value}", 1)
    assert err.value.field == "link_template"
    for n in range(20):
        log_pattern_service.add_pattern(db, 1, f"p{n}", f"token{n}", None, 1)
    with pytest.raises(LogPatternError) as err:
        log_pattern_service.add_pattern(db, 1, "p20", "token20", None, 1)
    assert err.value.field == "limit" and "20" in str(err.value)


def test_a_name_is_unique_per_project(db):
    log_pattern_service.add_pattern(db, 2, "same", "a", None, 1)
    log_pattern_service.add_pattern(db, 3, "same", "a", None, 1)
    with pytest.raises(log_pattern_service.DuplicatePattern):
        log_pattern_service.add_pattern(db, 2, "same", "b", None, 1)


def test_patterns_are_listed_in_name_order(db):
    for name in ("trip_id", "booking", "route_key"):
        log_pattern_service.add_pattern(db, 1, name, "a", None, 1)
    assert [p.name for p in log_pattern_service.list_patterns(db, 1)] == ["booking", "route_key", "trip_id"]


def test_deleting_a_pattern_deletes_its_values(client, make_key, db, patterns):
    trip, route = patterns(("trip_id", TRIP), ("route_key", ROUTE))
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "t", "status": "passed", "log": 'tripId="1" routeKey="r"'}])
    assert log_pattern_service.delete_pattern(db, 1, trip.id) is True
    assert values_of(db) == [("t", "route_key", 0, "r")]
    assert log_pattern_service.delete_pattern(db, 2, route.id) is False  # another project's pattern id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_log_values_on_upload.py -q`
Expected: FAIL with `ImportError: cannot import name 'log_pattern_service'`.

- [ ] **Step 3: Implement the services** — create `platforms/ingestion-service/src/ingestion/service/log_pattern_service.py`:

```python
"""A project's log-value patterns (ADR-032): named like masking patterns, RE2, at most one capture group, an
optional https link template. No edit: delete and add again."""
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.ingestion.models.log_pattern import LogPattern, LogValue
from src.ingestion.utils import log_values
from src.ingestion.utils.log_values import CompiledLogPattern, LogPatternError


class DuplicatePattern(Exception):
    pass


def list_patterns(db: Session, project_id: int) -> List[LogPattern]:
    return db.query(LogPattern).filter_by(project_id=project_id).order_by(LogPattern.name).all()


def compiled_for(db: Session, project_id: int) -> List[CompiledLogPattern]:
    """The project's patterns, ready to apply. A stored pattern that no longer compiles (validated on the way in, so
    only a library change could do this) is skipped, not fatal."""
    patterns = []
    for row in list_patterns(db, project_id):
        try:
            patterns.append(CompiledLogPattern(row.id, row.name, log_values.compile_log_pattern(row.pattern)))
        except LogPatternError:
            continue
    return patterns


def validate(name: str, pattern: str) -> CompiledLogPattern:
    """LogPatternError with a reason and its field, for a 422."""
    return CompiledLogPattern(None, log_values.validate_name(name), log_values.compile_log_pattern(pattern))


def add_pattern(db: Session, project_id: int, name: str, pattern: str, link_template: Optional[str],
                user_id: int) -> LogPattern:
    validate(name, pattern)
    template = log_values.validate_link_template(link_template)
    limit = log_values.MAX_LOG_PATTERNS_PER_PROJECT
    if db.query(LogPattern).filter_by(project_id=project_id).count() >= limit:
        raise LogPatternError("limit", f"A project has at most {limit} log-value patterns")
    row = LogPattern(project_id=project_id, name=name, pattern=pattern, link_template=template,
                     created_by_user_id=user_id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicatePattern(f"This project already has a log-value pattern named {name}")
    db.refresh(row)
    return row


def delete_pattern(db: Session, project_id: int, pattern_id: int) -> bool:
    row = db.query(LogPattern).filter_by(project_id=project_id, id=pattern_id).first()
    if row is None:
        return False
    # Its values first, explicitly: SQLite (the tests) does not enforce ON DELETE CASCADE
    db.query(LogValue).filter(LogValue.pattern_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return True
```

Create `platforms/ingestion-service/src/ingestion/service/log_value_service.py`:

```python
"""Log values (ADR-032): rows from a result's stored (masked) log, written at upload, by the re-scan and by the
re-mask job."""
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import insert
from sqlalchemy.orm import Session

from src.ingestion.models.log_pattern import LogValue
from src.ingestion.utils import log_values
from src.ingestion.utils.log_values import CompiledLogPattern


def rows_for(result_id: int, log: Optional[str], patterns: Sequence[CompiledLogPattern]) -> List[dict]:
    """The log_values rows of one result's log."""
    return [{"result_id": result_id, "pattern_id": pattern_id, "position": position, "value": value}
            for pattern_id, position, value in log_values.extract(log, patterns)]


def replace_values(db: Session, items: Sequence[Tuple[int, Optional[str]]],
                   patterns: Sequence[CompiledLogPattern]) -> int:
    """These results' values for these patterns, read again from their logs: the old rows go and the new ones come
    in, in the caller's transaction (it commits). Running it twice leaves the same rows."""
    result_ids = [result_id for result_id, _ in items]
    if not result_ids or not patterns:
        return 0
    db.query(LogValue).filter(
        LogValue.result_id.in_(result_ids), LogValue.pattern_id.in_([p.id for p in patterns])
    ).delete(synchronize_session=False)
    rows = [row for result_id, log in items for row in rows_for(result_id, log, patterns)]
    if rows:
        db.execute(insert(LogValue), rows)
    return len(rows)
```

- [ ] **Step 4: Capture values at upload.** In `service/ingest_service.py`:
  - change the models import to `from src.ingestion.models import ApiKey, LogValue, Run, RunChangedFile, RunComponent, RunResult`;
  - change the service import to `from src.ingestion.service import collection_settings_service, impact_service, log_pattern_service, log_value_service, masking_pattern_service`;
  - after the line `    patterns = tuple(masking_pattern_service.compiled_for(db, key.project_id))` that comes right after `meta = upload.run`, add `    log_patterns = tuple(log_pattern_service.compiled_for(db, key.project_id))`;
  - replace `        db.execute(insert(RunResult), rows)  # one executemany, not 20,000 ORM objects` with:

```python
        if log_patterns and any(row["log"] for row in rows):
            # Values need each result's id: one executemany with RETURNING, in the order the rows were sent (ADR-032)
            result_ids = db.execute(
                insert(RunResult).returning(RunResult.id, sort_by_parameter_order=True), rows
            ).scalars().all()
            values = [value for result_id, row in zip(result_ids, rows)
                      for value in log_value_service.rows_for(result_id, row["log"], log_patterns)]
            if values:
                db.execute(insert(LogValue), values)
        else:
            db.execute(insert(RunResult), rows)  # one executemany, not 20,000 ORM objects
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_log_values_on_upload.py tests/integration/test_collect_log.py tests/integration/test_collect_endpoint.py tests/integration/test_masking_on_ingest.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/service/log_pattern_service.py platforms/ingestion-service/src/ingestion/service/log_value_service.py platforms/ingestion-service/src/ingestion/service/ingest_service.py platforms/ingestion-service/tests/integration/test_log_values_on_upload.py
git commit -o platforms/ingestion-service/src/ingestion/service/log_pattern_service.py platforms/ingestion-service/src/ingestion/service/log_value_service.py platforms/ingestion-service/src/ingestion/service/ingest_service.py platforms/ingestion-service/tests/integration/test_log_values_on_upload.py -m "feat(ingestion): capture log values at upload from the masked log" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Re-scan past logs when a pattern is added

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/jobs/log_scan.py`
- Modify: `platforms/ingestion-service/src/ingestion/core/config.py` (two settings)
- Modify: `platforms/ingestion-service/src/ingestion/api/main.py` (start-up resume)
- Modify: `platforms/ingestion-service/tests/conftest.py` (resume off in tests)
- Create: `platforms/ingestion-service/tests/integration/test_log_scan.py`

**Interfaces:**
- Consumes: `log_pattern_service.compiled_for`, `log_value_service.replace_values` (Task 4); `CollectionSettings.log_scan_*` (Task 1).
- Produces (in `src.ingestion.jobs.log_scan`): `SCAN_DAYS = 90`; `LOCK_CLASS = 7_351_023`; `request_scan(db, project_id) -> None` (commits); `scan_state(db, project_id) -> dict` (`{"state": "idle", "since": None}` or `{"state": "running", "since": datetime | None}`); `scan_pass(db, project_id, since: datetime, batch_size: int) -> int`; `run_scan(session_factory, project_id, *, lock_engine=None, now=…, batch_size=None) -> bool` (never raises); `resume_all(session_factory) -> int`; `_project_lock(engine, project_id)` (context manager yielding bool).
- Produces (settings): `LOG_SCAN_BATCH_SIZE: int = 500`, `LOG_SCAN_RESUME_ON_STARTUP: bool = True`. Produces (in `src.ingestion.api.main`): `_resume_log_scans()` start-up hook.

- [ ] **Step 1: Settings, and the start-up resume off in tests** (first: pydantic settings refuse an unknown attribute, so the conftest line needs the field). In `src/ingestion/core/config.py`, after `RETENTION_DELETED_GRACE_DAYS: int = 7`, add:

```python
    # The log-value re-scan (ADR-032): results per committed batch, and whether a scan queued when the service
    # stopped runs again when it starts (off in the tests)
    LOG_SCAN_BATCH_SIZE: int = 500
    LOG_SCAN_RESUME_ON_STARTUP: bool = True
```

In `platforms/ingestion-service/tests/conftest.py`, after the line `from src.ingestion.models.run import FULL_SCOPE`, add:

```python
# The service resumes queued log-value scans at start-up on its own database (ADR-032); TestClient runs start-up
# hooks, and the tests drive scans themselves
settings.LOG_SCAN_RESUME_ON_STARTUP = False
```

- [ ] **Step 2: Write the failing tests** — create `platforms/ingestion-service/tests/integration/test_log_scan.py`:

```python
"""The log-value re-scan (ADR-032): past logs within 90 days, idempotent, one scan per project at a time."""
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.api import main
from src.ingestion.core.config import settings
from src.ingestion.jobs import log_scan
from src.ingestion.models import LogPattern, LogValue, RunResult
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session_factory(db):
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)


@pytest.fixture
def logged(db, seed_run):
    """logged(days_ago, log, project_id=1) -> result id: one run (stored `days_ago` before NOW) with one result."""
    def _add(days_ago, log, project_id=1):
        run = seed_run(NOW - timedelta(days=days_ago), results=(("t", "passed", 5),), project_id=project_id)
        row = db.query(RunResult).filter_by(run_id=run.id).one()
        row.log = log
        db.commit()
        return row.id
    return _add


def add_pattern(db, name, regex, project_id=1):
    row = LogPattern(project_id=project_id, name=name, pattern=regex)
    db.add(row)
    db.commit()
    return row


def values(db):
    db.expire_all()
    return sorted((v.result_id, v.pattern_id, v.position, v.value) for v in db.query(LogValue))


def scan(session_factory, project_id=1):
    return log_scan.run_scan(session_factory, project_id, now=lambda: NOW, batch_size=2)


def test_a_queued_scan_fills_values_for_the_last_90_days_only(db, session_factory, logged):
    recent = [logged(days, f'tripId="{days}"') for days in (1, 10, 89)]
    logged(91, 'tripId="91"')
    trip = add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    assert log_scan.scan_state(db, 1)["state"] == "running"
    assert scan(session_factory) is True
    assert values(db) == sorted((rid, trip.id, 0, str(days)) for rid, days in zip(recent, (1, 10, 89)))
    db.expire_all()
    assert log_scan.scan_state(db, 1) == {"state": "idle", "since": None}


def test_a_second_scan_changes_nothing(db, session_factory, logged):
    logged(1, 'tripId="1" tripId="2"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    scan(session_factory)
    first = values(db)
    log_scan.request_scan(db, 1)
    assert scan(session_factory) is True
    assert values(db) == first and len(first) == 2


def test_nothing_queued_means_nothing_to_do(db, session_factory, logged):
    logged(1, 'tripId="1"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    assert scan(session_factory) is True
    assert values(db) == []


def test_another_projects_logs_are_never_scanned(db, session_factory, logged):
    logged(1, 'tripId="1"', project_id=2)
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    scan(session_factory)
    assert values(db) == []


def test_one_scan_per_project_at_a_time(db, session_factory, logged):
    logged(1, 'tripId="1"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    with log_scan._project_lock(session_factory.kw["bind"], 1) as held:
        assert held is True
        assert scan(session_factory) is False   # the scan holding the project sees the request
        assert values(db) == []
        with log_scan._project_lock(session_factory.kw["bind"], 2) as other:
            assert other is True                # another project is not blocked
    db.expire_all()
    assert log_scan.scan_state(db, 1)["state"] == "running"  # still queued
    assert scan(session_factory) is True
    assert len(values(db)) == 1


def test_a_pattern_added_during_a_pass_gets_its_values(db, session_factory, logged, monkeypatch):
    logged(1, 'tripId="1" routeKey="wasToBos"')
    logged(2, 'tripId="2"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    real, passes = log_scan.scan_pass, []

    def pass_then_add(db_, project_id, since, batch_size):
        scanned = real(db_, project_id, since, batch_size)
        passes.append(scanned)
        if len(passes) == 1:  # added after this pass had walked every result
            with session_factory() as other:
                add_pattern(other, "route_key", r'routeKey="([^"]+)"')
                log_scan.request_scan(other, 1)
        return scanned

    monkeypatch.setattr(log_scan, "scan_pass", pass_then_add)
    assert scan(session_factory) is True
    assert passes == [2, 2]
    assert "wasToBos" in [value for *_, value in values(db)]
    db.expire_all()
    assert log_scan.scan_state(db, 1)["state"] == "idle"


def test_a_failed_pass_stays_queued_and_the_next_run_finishes_it(db, session_factory, logged, monkeypatch):
    logged(1, 'tripId="1"')
    add_pattern(db, "trip_id", r'tripId="(\d+)"')
    log_scan.request_scan(db, 1)
    real = log_scan.scan_pass

    def broken(*args):
        raise RuntimeError("database went away")

    monkeypatch.setattr(log_scan, "scan_pass", broken)
    assert scan(session_factory) is False
    db.expire_all()
    assert log_scan.scan_state(db, 1)["state"] == "running"
    monkeypatch.setattr(log_scan, "scan_pass", real)
    assert scan(session_factory) is True
    assert len(values(db)) == 1


def test_a_result_valued_at_upload_is_not_valued_twice_by_the_scan(client, make_key, db, session_factory):
    trip = add_pattern(db, "trip_id", r'tripId="(\d+)"')
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "t", "status": "passed", "log": 'tripId="1" tripId="2"'}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    at_upload = values(db)
    assert [(p, pos, v) for _, p, pos, v in at_upload] == [(trip.id, 0, "1"), (trip.id, 1, "2")]
    log_scan.request_scan(db, 1)
    assert log_scan.run_scan(session_factory, 1) is True  # the real clock: the upload is seconds old
    assert values(db) == at_upload


def test_a_deleted_pattern_leaves_no_values_behind(db, session_factory, logged):
    logged(1, 'tripId="1"')
    trip = add_pattern(db, "trip_id", r'tripId="(\d+)"')
    db.delete(trip)
    db.commit()
    log_scan.request_scan(db, 1)
    assert scan(session_factory) is True
    assert values(db) == []


def test_resume_all_runs_every_queued_project(db, session_factory, logged):
    logged(1, 'tripId="1"', project_id=1)
    logged(1, 'tripId="2"', project_id=2)
    add_pattern(db, "trip_id", r'tripId="(\d+)"', project_id=1)
    add_pattern(db, "trip_id", r'tripId="(\d+)"', project_id=2)
    log_scan.request_scan(db, 1)
    log_scan.request_scan(db, 2)
    assert log_scan.resume_all(session_factory) == 2
    assert len(values(db)) == 2


def test_the_service_resumes_queued_scans_when_it_starts(monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(log_scan, "resume_all", lambda session_factory: started.set())
    monkeypatch.setattr(settings, "LOG_SCAN_RESUME_ON_STARTUP", True)
    main._resume_log_scans()
    assert started.wait(5)


def test_resuming_can_be_switched_off(monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(log_scan, "resume_all", lambda session_factory: started.set())
    monkeypatch.setattr(settings, "LOG_SCAN_RESUME_ON_STARTUP", False)
    main._resume_log_scans()
    assert not started.wait(0.2)
```

`test_a_queued_scan_fills_values_for_the_last_90_days_only` uses `seed_run`, whose runs get `created_at = started_at`, and the scan's clock is `NOW`, so 89 days is in and 91 is out. `test_a_result_valued_at_upload_is_not_valued_twice_by_the_scan` runs on the real clock because an upload's `created_at` is the server's now.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_log_scan.py -q`
Expected: FAIL with `ImportError: cannot import name 'log_scan'`.

- [ ] **Step 4: The scan** — create `platforms/ingestion-service/src/ingestion/jobs/log_scan.py`:

```python
"""Re-scan a project's stored logs for its log-value patterns (ADR-032, spec §3.4).

Adding a pattern queues a scan (request_scan bumps collection_settings.log_scan_requested). The scan runs inside
ingestion-service after the response (a background task), and again at start-up for a scan a restart cut short
(resume_all). It walks the logs stored in the last 90 days in committed batches, oldest result first, and replaces
each result's values for the project's current patterns, so running it again changes nothing. One scan per project
at a time: a PostgreSQL advisory lock per project (an in-process lock on SQLite, the tests). A pattern added while a
scan runs bumps the counter again, and the running scan makes another pass before it stops.
"""
import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterator, Optional

from sqlalchemy import text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.core.config import settings
from src.ingestion.models import CollectionSettings, Run, RunResult
from src.ingestion.service import log_pattern_service, log_value_service

logger = logging.getLogger(__name__)

SCAN_DAYS = 90
# With the project id: one advisory lock per project (the two-key form; retention's single key 7_351_001 is apart)
LOCK_CLASS = 7_351_023
_local_guard = threading.Lock()
_local_locks: Dict[int, threading.Lock] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def request_scan(db: Session, project_id: int) -> None:
    """Queue a scan. One atomic increment, so requests that race are all counted."""
    if db.get(CollectionSettings, project_id) is None:
        db.add(CollectionSettings(project_id=project_id, collect_manual=True, discarded_count=0))
        try:
            db.commit()
        except IntegrityError:  # another request created the row first
            db.rollback()
    db.execute(
        update(CollectionSettings).where(CollectionSettings.project_id == project_id)
        .values(log_scan_requested=CollectionSettings.log_scan_requested + 1)
    )
    db.commit()


def scan_state(db: Session, project_id: int) -> dict:
    """What GET …/log-patterns reports: running while a request is not finished, since the current pass started."""
    row = db.get(CollectionSettings, project_id)
    if row is None or (row.log_scan_requested or 0) <= (row.log_scan_done or 0):
        return {"state": "idle", "since": None}
    return {"state": "running", "since": row.log_scan_started_at}


@contextmanager
def _project_lock(engine: Engine, project_id: int) -> Iterator[bool]:
    if engine.dialect.name != "postgresql":
        with _local_guard:
            lock = _local_locks.setdefault(project_id, threading.Lock())
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()
        return
    with engine.connect() as conn:
        args = {"cls": LOCK_CLASS, "project": project_id}
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:cls, :project)"), args).scalar())
        conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:cls, :project)"), args)
                conn.commit()


def scan_pass(db: Session, project_id: int, since: datetime, batch_size: int) -> int:
    """One pass over the project's logs stored since `since`; returns the results scanned. The patterns are loaded
    again for every batch, so one added or deleted meanwhile is seen from the next batch on."""
    scanned, last_id, retried = 0, 0, False
    while True:
        patterns = log_pattern_service.compiled_for(db, project_id)
        if not patterns:
            return scanned
        batch = (
            db.query(RunResult.id, RunResult.log)
            .join(Run, Run.id == RunResult.run_id)
            .filter(Run.project_id == project_id, Run.created_at >= since, RunResult.id > last_id,
                    RunResult.log.isnot(None))
            .order_by(RunResult.id).limit(batch_size).all()
        )
        if not batch:
            return scanned
        log_value_service.replace_values(db, [(row.id, row.log) for row in batch], patterns)
        try:
            db.commit()
        except IntegrityError:
            # A pattern was deleted between loading it and inserting its values (PostgreSQL's foreign key): load the
            # patterns again and redo this batch, once
            db.rollback()
            if retried:
                raise
            retried = True
            continue
        retried = False
        scanned += len(batch)
        last_id = batch[-1].id


def _scan_until_idle(session_factory: sessionmaker, project_id: int, now: Callable[[], datetime],
                     batch_size: int) -> None:
    while True:
        with session_factory() as db:
            row = db.get(CollectionSettings, project_id)
            if row is None or row.log_scan_requested <= row.log_scan_done:
                return
            generation, started = row.log_scan_requested, now()
            row.log_scan_started_at = started
            db.commit()
            # A module global, looked up at call time (the tests replace it)
            scanned = scan_pass(db, project_id, started - timedelta(days=SCAN_DAYS), batch_size)
            finished = db.execute(
                update(CollectionSettings)
                .where(CollectionSettings.project_id == project_id,
                       CollectionSettings.log_scan_requested == generation)
                .values(log_scan_done=generation, log_scan_started_at=None)
            ).rowcount
            db.commit()
        logger.info(json.dumps({"event": "log_scan", "project_id": project_id, "results_scanned": scanned,
                                "finished": bool(finished)}))
        # Not finished: a pattern was added during the pass; the next pass reads every result again


def run_scan(session_factory: sessionmaker, project_id: int, *, lock_engine: Optional[Engine] = None,
             now: Callable[[], datetime] = _utcnow, batch_size: Optional[int] = None) -> bool:
    """Run the project's queued scan until nothing is queued. False when another scan holds the project (it sees
    the request) or a pass failed (logged; the request stays queued for the next start or the next pattern)."""
    engine = lock_engine if lock_engine is not None else session_factory.kw["bind"]
    size = batch_size or settings.LOG_SCAN_BATCH_SIZE
    try:
        while True:
            with _project_lock(engine, project_id) as acquired:
                if not acquired:
                    return False
                _scan_until_idle(session_factory, project_id, now, size)
            # A request that came in between the last finish and the unlock found the lock taken: take it again
            with session_factory() as db:
                if scan_state(db, project_id)["state"] == "idle":
                    return True
    except Exception:  # a background task has nobody to raise to
        logger.exception("log-value scan failed for project %s", project_id)
        return False


def resume_all(session_factory: sessionmaker) -> int:
    """Every project with a queued scan, one after another (start-up). Returns how many were run."""
    try:
        with session_factory() as db:
            projects = [project_id for (project_id,) in db.query(CollectionSettings.project_id).filter(
                CollectionSettings.log_scan_requested > CollectionSettings.log_scan_done
            ).order_by(CollectionSettings.project_id)]
    except Exception:
        logger.exception("queued log-value scans could not be read")
        return 0
    for project_id in projects:
        run_scan(session_factory, project_id)
    return len(projects)
```

- [ ] **Step 5: Resume at start-up** — in `src/ingestion/api/main.py`, add `import threading` as the first line, add `from src.ingestion.jobs import log_scan` after `from src.ingestion.core.config import settings`, and after `metrics.REGISTRY.register(HEARTBEATS)` add:

```python
@app.on_event("startup")
def _resume_log_scans() -> None:
    """A log-value scan queued when the service last stopped (ADR-032) runs again, in a thread: start-up does not
    wait for it, and the per-project lock keeps a second worker from scanning the same project."""
    if not settings.LOG_SCAN_RESUME_ON_STARTUP:
        return
    from src.ingestion.db.session import SessionLocal

    threading.Thread(target=log_scan.resume_all, args=(SessionLocal,), name="log-scan-resume", daemon=True).start()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_log_scan.py tests/integration/test_collection_settings.py tests/integration/test_health_and_metrics.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/jobs/log_scan.py platforms/ingestion-service/src/ingestion/core/config.py platforms/ingestion-service/src/ingestion/api/main.py platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_log_scan.py
git commit -o platforms/ingestion-service/src/ingestion/jobs/log_scan.py platforms/ingestion-service/src/ingestion/core/config.py platforms/ingestion-service/src/ingestion/api/main.py platforms/ingestion-service/tests/conftest.py platforms/ingestion-service/tests/integration/test_log_scan.py -m "feat(ingestion): re-scan the last 90 days of logs for log values, one scan per project, resumed at start-up" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Endpoints `…/log-patterns`, gateway route, ingestion README section

**Files:**
- Create: `platforms/ingestion-service/src/ingestion/schemas/log_pattern.py`
- Create: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/log_patterns.py`
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/api.py`
- Modify: `gateway/nginx.conf.template` (the ingestion project-prefix location, about line 216), `gateway/README.md` (route table)
- Modify: `scripts/smoke_gateway.sh` (after the `collection settings -> ingestion-service` check)
- Create: `platforms/ingestion-service/tests/integration/test_log_patterns.py`
- Modify: `platforms/ingestion-service/README.md` (new `## Log values` after `## Masking`), `TECHNICAL_SPECIFICATION.md` (new bullet after **Masking**; the route regex near line 245)

**Interfaces:**
- Consumes: `log_pattern_service.*` (Task 4), `log_scan.request_scan`, `log_scan.run_scan`, `log_scan.scan_state` (Task 5), `log_values.extract`, `LogPatternError` (Task 3), `ingest_service.mask`, `ingest_service.truncate_utf8`.
- Produces (HTTP, prefix `/api/v1/projects/{project_id}/log-patterns`):
  - `GET ""` (READ_ROLES) → `{"patterns": [{"id", "name", "pattern", "link_template", "created_at"}], "scan": {"state": "idle" | "running", "since": iso | null}}`, patterns in name order.
  - `POST ""` (EDIT_ROLES) body `{name, pattern, link_template?}` → 201 the pattern; queues a re-scan and runs it after the response. 422 `{"detail": {"code", "message"}}` (`code` in `name`, `pattern`, `link_template`, `limit`); 409 `{"detail": {"code": "name", "message"}}`.
  - `POST "/preview"` (EDIT_ROLES) body `{name, pattern, sample}` (sample ≤ 65,536 characters) → `{"masked": str, "values": [str]}`; nothing saved.
  - `DELETE "/{pattern_id}"` (EDIT_ROLES) → 204; 404 `"Log-value pattern not found"`.
- Produces (schemas, `src.ingestion.schemas.log_pattern`): `LogPatternCreate`, `LogPatternOut`, `LogScanOut`, `LogPatternListOut`, `LogPreviewIn`, `LogPreviewOut`.

- [ ] **Step 1: Write the failing tests** — create `platforms/ingestion-service/tests/integration/test_log_patterns.py`:

```python
"""Log-value patterns through the API (ADR-032): members manage them, viewers read, adding re-scans past logs."""
from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.jobs import log_scan
from src.ingestion.models import LogPattern, LogValue, RunResult

URL = "/api/v1/projects/1/log-patterns"
TRIP = r'tripId="(\d+)"'
LINK = "https://backoffice.example.com/trips/{value}"


@pytest.fixture
def member(project_role):
    project_role(role="member", project_id=1)


def add(client, auth, name="trip_id", pattern=TRIP, link_template=None):
    body = {"name": name, "pattern": pattern}
    if link_template is not None:
        body["link_template"] = link_template
    return client.post(URL, json=body, headers=auth())


def test_a_member_adds_lists_and_removes_a_pattern(client, auth, member):
    created = add(client, auth, link_template=LINK)
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["name"], body["pattern"], body["link_template"]) == ("trip_id", TRIP, LINK)
    add(client, auth, name="booking", pattern=r'booking="(\w+)"')

    listed = client.get(URL, headers=auth()).json()
    assert [p["name"] for p in listed["patterns"]] == ["booking", "trip_id"]
    assert listed["patterns"][0]["link_template"] is None
    assert listed["scan"] == {"state": "idle", "since": None}

    assert client.delete(f"{URL}/{body['id']}", headers=auth()).status_code == 204
    assert [p["name"] for p in client.get(URL, headers=auth()).json()["patterns"]] == ["booking"]


def test_a_viewer_reads_but_cannot_change(client, auth, project_role, db):
    project_role(role="viewer", project_id=1)
    assert client.get(URL, headers=auth()).status_code == 200
    assert add(client, auth).status_code == 403
    preview = client.post(f"{URL}/preview", json={"name": "t", "pattern": "a", "sample": "a"}, headers=auth())
    assert preview.status_code == 403
    row = LogPattern(project_id=1, name="trip_id", pattern=TRIP)
    db.add(row)
    db.commit()
    assert client.delete(f"{URL}/{row.id}", headers=auth()).status_code == 403


def test_a_non_member_gets_404(client, auth, project_role):
    project_role(status_code=404, project_id=1)
    assert client.get(URL, headers=auth()).status_code == 404


@pytest.mark.parametrize("body, code, words", [
    ({"name": "Trip", "pattern": TRIP}, "name", "lowercase"),
    ({"name": "trip_id", "pattern": "a" * 257}, "pattern", "256"),
    ({"name": "trip_id", "pattern": r"(?=x)"}, "pattern", "RE2"),
    ({"name": "trip_id", "pattern": r'(trip)Id="(\d+)"'}, "pattern", "at most one capture group"),
    ({"name": "trip_id", "pattern": r"x*"}, "pattern", "matches empty text"),
    ({"name": "trip_id", "pattern": TRIP, "link_template": "http://backoffice.example.com/{value}"}, "link_template", "https://"),
    ({"name": "trip_id", "pattern": TRIP, "link_template": "javascript:alert(1)//{value}"}, "link_template", "https://"),
    ({"name": "trip_id", "pattern": TRIP, "link_template": "https://backoffice.example.com/trips"}, "link_template", "{value}"),
    ({"name": "trip_id", "pattern": TRIP, "link_template": "https://x.example.com/" + "a" * 500 + "{value}"}, "link_template", "500"),
])
def test_an_invalid_pattern_is_refused_at_its_field(client, auth, member, body, code, words):
    response = client.post(URL, json=body, headers=auth())
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code and words in detail["message"]


def test_a_duplicate_name_conflicts_at_the_name(client, auth, member):
    add(client, auth)
    response = add(client, auth, pattern=r'tripId=(\d+)')
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "name"


def test_a_project_holds_at_most_twenty_patterns(client, auth, member):
    for i in range(20):
        assert add(client, auth, name=f"p{i}", pattern=f"token{i}").status_code == 201
    response = add(client, auth, name="p20", pattern="token20")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "limit"


def test_adding_a_pattern_fills_values_of_past_runs(client, auth, member, db, seed_run):
    now = datetime.now(timezone.utc)
    recent = seed_run(now - timedelta(days=3), results=(("books", "passed", 5),))
    old = seed_run(now - timedelta(days=120), results=(("books", "passed", 5),))
    for run, trip in ((recent, "3960562"), (old, "1")):
        row = db.query(RunResult).filter_by(run_id=run.id).one()
        row.log = f'Trip id captured tripId="{trip}"'
    db.commit()

    assert add(client, auth).status_code == 201  # the scan runs after the response
    db.expire_all()
    assert [(v.value,) for v in db.query(LogValue)] == [("3960562",)]
    assert client.get(URL, headers=auth()).json()["scan"]["state"] == "idle"


def test_a_queued_scan_is_reported_as_running(client, auth, member, db):
    log_scan.request_scan(db, 1)
    assert client.get(URL, headers=auth()).json()["scan"] == {"state": "running", "since": None}


def test_preview_returns_the_masked_sample_and_the_values_saving_nothing(client, auth, member, db):
    sample = 'INFO tripId="3960562"\nINFO tripId="3960563"\nINFO tripId="3960562"'
    response = client.post(f"{URL}/preview", json={"name": "trip_id", "pattern": TRIP, "sample": sample},
                           headers=auth())
    assert response.status_code == 200, response.text
    assert response.json() == {"masked": sample, "values": ["3960562", "3960563"]}
    assert db.query(LogPattern).count() == 0


def test_preview_never_shows_a_masked_value(client, auth, member):
    sample = "login token=s3cr3t-value as ann@example.com"
    response = client.post(f"{URL}/preview", json={"name": "token", "pattern": r"token=(\S+)", "sample": sample},
                           headers=auth())
    body = response.json()
    assert "s3cr3t-value" not in body["masked"] and "[REDACTED:" in body["masked"]
    assert body["values"] == []


def test_preview_refuses_an_invalid_pattern_at_its_field_and_a_sample_over_64_kb(client, auth, member):
    bad = client.post(f"{URL}/preview", json={"name": "t", "pattern": "(a)(b)", "sample": "ab"}, headers=auth())
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "pattern"
    big = client.post(f"{URL}/preview", json={"name": "t", "pattern": "a", "sample": "a" * 65_537}, headers=auth())
    assert big.status_code == 422


def test_deleting_removes_the_patterns_values_and_an_unknown_id_is_404(client, auth, member, db, seed_run):
    run = seed_run(datetime.now(timezone.utc), results=(("books", "passed", 5),))
    row = db.query(RunResult).filter_by(run_id=run.id).one()
    row.log = 'tripId="7"'
    db.commit()
    pattern_id = add(client, auth).json()["id"]
    db.expire_all()
    assert db.query(LogValue).count() == 1
    assert client.delete(f"{URL}/{pattern_id}", headers=auth()).status_code == 204
    db.expire_all()
    assert db.query(LogValue).count() == 0
    assert client.delete(f"{URL}/{pattern_id}", headers=auth()).status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_log_patterns.py -q`
Expected: FAIL — every request answers 404 (no route).

- [ ] **Step 3: Schemas** — create `platforms/ingestion-service/src/ingestion/schemas/log_pattern.py`:

```python
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LogPatternCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The real limits (32, 256, 500) are checked by the service with a reason and its field
    name: str = Field(max_length=64)
    pattern: str = Field(max_length=1024)
    link_template: Optional[str] = Field(None, max_length=2048)


class LogPatternOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pattern: str
    link_template: Optional[str] = None
    created_at: Optional[datetime] = None


class LogScanOut(BaseModel):
    state: Literal["idle", "running"]
    since: Optional[datetime] = None


class LogPatternListOut(BaseModel):
    patterns: List[LogPatternOut]
    scan: LogScanOut


class LogPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=64)
    pattern: str = Field(max_length=1024)
    sample: str = Field(max_length=65_536)


class LogPreviewOut(BaseModel):
    masked: str
    values: List[str]
```

- [ ] **Step 4: Endpoints** — create `platforms/ingestion-service/src/ingestion/api/v1/endpoints/log_patterns.py`:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, sessionmaker

from src.ingestion.api.deps import EDIT_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.ingestion.core.config import settings
from src.ingestion.jobs import log_scan
from src.ingestion.schemas.log_pattern import (
    LogPatternCreate, LogPatternListOut, LogPatternOut, LogPreviewIn, LogPreviewOut,
)
from src.ingestion.service import ingest_service, log_pattern_service, masking_pattern_service
from src.ingestion.utils import log_values
from src.ingestion.utils.log_values import LogPatternError

router = APIRouter()  # mounted at /projects/{project_id}/log-patterns


def _refused(exc: LogPatternError) -> HTTPException:
    """The reason and the form field it belongs to, so the dashboard shows it there."""
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail={"code": exc.field, "message": str(exc)})


@router.get("", response_model=LogPatternListOut)
def list_log_patterns(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return {"patterns": log_pattern_service.list_patterns(db, access.project_id),
            "scan": log_scan.scan_state(db, access.project_id)}


@router.post("", response_model=LogPatternOut, status_code=status.HTTP_201_CREATED)
def add_log_pattern(
    payload: LogPatternCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    """Adds the pattern and queues a re-scan of the last 90 days, which runs after the response (ADR-032)."""
    try:
        row = log_pattern_service.add_pattern(
            db, access.project_id, payload.name, payload.pattern, payload.link_template, access.user_id)
    except LogPatternError as exc:
        raise _refused(exc)
    except log_pattern_service.DuplicatePattern as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "name", "message": str(exc)})
    out = LogPatternOut.model_validate(row)
    log_scan.request_scan(db, access.project_id)
    background.add_task(log_scan.run_scan, sessionmaker(bind=db.get_bind()), access.project_id)
    return out


@router.post("/preview", response_model=LogPreviewOut)
def preview_log_pattern(
    payload: LogPreviewIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    """The sample as it would be stored (masked with the built-in rules and the project's masking patterns, cut at
    64 KB) and the values this pattern finds in it. Nothing is saved."""
    try:
        pattern = log_pattern_service.validate(payload.name, payload.pattern)
    except LogPatternError as exc:
        raise _refused(exc)
    masked, _ = ingest_service.mask(payload.sample, tuple(masking_pattern_service.compiled_for(db, access.project_id)))
    masked = ingest_service.truncate_utf8(masked, settings.MAX_TEXT_BYTES)[0]
    return LogPreviewOut(masked=masked, values=[value for _, _, value in log_values.extract(masked, [pattern])])


@router.delete("/{pattern_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log_pattern(
    pattern_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    if not log_pattern_service.delete_pattern(db, access.project_id, pattern_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log-value pattern not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

In `src/ingestion/api/v1/api.py`, add `log_patterns` to the endpoints import (alphabetical: after `export`) and after the masking-patterns `include_router` add:

```python
api_router.include_router(
    log_patterns.router, prefix="/projects/{project_id}/log-patterns", tags=["log-values"]
)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_log_patterns.py tests/integration/test_masking_patterns.py -q`
Expected: PASS.

- [ ] **Step 6: Gateway.** In `gateway/nginx.conf.template`, change the comment and regex of the ingestion project-prefix location to:

```nginx
        # A regex location wins over prefix locations, so this takes /api/v1/projects/{id}/api-keys,
        # /runs, /analytics, /masking-patterns, /log-patterns, /export and /notification-channels and /collection-settings away from project-service's /api/v1/projects prefix below.
        location ~ ^/api/v1/projects/[0-9]+/(api-keys|runs|analytics|masking-patterns|log-patterns|export|notification-channels|collection-settings)(/|$) {
```

In `gateway/README.md`, in the route table row that starts ``| `/api/v1/projects/{id}/api-keys…` ``, insert `` `…/log-patterns…`, `` after `` `…/masking-patterns…`, ``.

In `scripts/smoke_gateway.sh`, after the line `check "collection settings -> ingestion-service" 200 GET …`, add:

```bash
check "log-value patterns without a token -> 401" 401 GET "$BASE/api/v1/projects/$PROJECT_ID/log-patterns"
check "log-value patterns -> ingestion-service" 200 GET "$BASE/api/v1/projects/$PROJECT_ID/log-patterns" "${AUTH[@]}"
body_has "... with the re-scan state" '"scan":{"state":"idle"'
```

Run: `python scripts/check_architecture_docs.py` (repo root). Expected: exit 0 and the line `architecture docs: … gateway routes match the stack`. Run: `bash -n scripts/smoke_gateway.sh`. Expected: no output, exit 0.

- [ ] **Step 7: Docs.** In `platforms/ingestion-service/README.md`, add after the `## Masking` section (before `## Retention`):

```markdown
## Log values

A project's patterns pick values out of each result's log (ADR-032), for example the trip a booking scenario
created. The log is masked first (built-in rules and the project's masking patterns) and cut to 64 KB; values are
read from that stored text, so a value hidden by masking is never captured.

- **Patterns:** `GET /api/v1/projects/{id}/log-patterns` (every role) → `{"patterns": [{id, name, pattern,
  link_template, created_at}], "scan": {"state": "idle" | "running", "since": … | null}}`, patterns in name order.
  `POST …` `{name, pattern, link_template?}` and `DELETE …/{pattern_id}` (owner/admin/member). Up to 20 per
  project; the name as for masking (`^[a-z][a-z0-9_]{0,31}$`, unique); the pattern RE2, at most 256 characters,
  never matching empty text, with at most one capture group (with a group the value is the group's text, without
  one the whole match). `link_template` (optional, ≤ 500 characters): an `https://` address with a host and
  `{value}` once after the host; the dashboard URL-encodes the value into it. A refusal is 422
  `{"detail": {"code": "name" | "pattern" | "link_template" | "limit", "message"}}`; a duplicate name is 409 with
  `code: "name"`. No edit: delete and add again. Deleting a pattern deletes its values.
- **Preview:** `POST …/preview` `{name, pattern, sample}` (sample ≤ 65,536 characters, owner/admin/member) → the
  sample as it would be stored (`masked`) and the values this pattern finds in it. Nothing is saved.
- **Values:** at upload, each result's log is matched with the project's patterns; one row per distinct value per
  pattern per result (`log_values`, in order of first appearance), at most 20 per pattern, each cut to 200
  characters. A pattern stops reading a log after 1,000 matches.
- **Past runs:** adding a pattern queues a re-scan of the logs stored in the last 90 days. It runs in the service
  after the response, in batches of `LOG_SCAN_BATCH_SIZE` (500), one scan per project at a time (an advisory lock),
  replacing each result's values, so it is safe to repeat; a pattern added during a scan makes it pass again. A scan
  that a restart cut short, or that failed, stays queued and runs when the service starts
  (`LOG_SCAN_RESUME_ON_STARTUP`, default true). Logs older than 90 days get no values for a new pattern.
```

In `TECHNICAL_SPECIFICATION.md`, after the **Masking** bullet (the one ending `re-masks stored\n  results.`), add:

```markdown
- **Log values** (ADR-032): `GET/POST /projects/{id}/log-patterns`, `DELETE …/{pattern_id}`, `POST …/preview`;
  tables `log_patterns` (≤ 20 per project, RE2, at most one capture group, optional https `link_template`) and
  `log_values` (≤ 20 distinct values per pattern per result, 200 characters, cascading with the result and the
  pattern); the re-scan counters `collection_settings.log_scan_requested/done/started_at` (migration 023). Values come
  from the masked `test_results.log`.
```
and in the gateway route regex near line 245, change `(api-keys|runs|analytics|masking-patterns|export|notification-channels)` to `(api-keys|runs|analytics|masking-patterns|log-patterns|export|notification-channels|collection-settings)`.

- [ ] **Step 8: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/schemas/log_pattern.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/log_patterns.py platforms/ingestion-service/src/ingestion/api/v1/api.py platforms/ingestion-service/tests/integration/test_log_patterns.py gateway/nginx.conf.template gateway/README.md scripts/smoke_gateway.sh platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md
git commit -o platforms/ingestion-service/src/ingestion/schemas/log_pattern.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/log_patterns.py platforms/ingestion-service/src/ingestion/api/v1/api.py platforms/ingestion-service/tests/integration/test_log_patterns.py gateway/nginx.conf.template gateway/README.md scripts/smoke_gateway.sh platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md -m "feat(ingestion): log-value patterns API with preview and a re-scan on add; gateway route" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Re-mask, export and retention carry the log and its values

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/jobs/remask.py`
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/export.py`
- Modify: `platforms/ingestion-service/src/ingestion/jobs/retention.py` (`_delete_in_batches`)
- Test: `platforms/ingestion-service/tests/integration/test_remask_job.py`, `test_export.py`, `test_retention_job.py` (append)
- Modify: `platforms/ingestion-service/README.md` (`## Masking` remask bullet, `## Retention`, `## Export`), `docs/SETUP.md` §4.7

**Interfaces:**
- Consumes: `log_pattern_service.compiled_for`, `log_value_service.replace_values` (Task 4), `RunResult.log` (deferred, Task 1).
- Produces: export `result` lines gain `"log"` and `"log_values": [{"pattern": name, "value": value}]` (pattern name order, then position); `remask._ProjectPatterns(db, load=masking_pattern_service.compiled_for)`.

- [ ] **Step 1: Write the failing tests.** Append to `platforms/ingestion-service/tests/integration/test_remask_job.py`:

```python
def test_a_re_masked_log_has_its_values_read_again(db, session_factory, add_run):
    from src.ingestion.models import LogPattern, LogValue

    run_id = add_run(results=[("plain message", None)])
    row = db.query(RunResult).filter_by(run_id=run_id).one()
    row.log = f'tripId="42" GITHUB_TOKEN={SECRET}'
    token = LogPattern(project_id=1, name="token", pattern=r"GITHUB_TOKEN=(\S+)")
    trip = LogPattern(project_id=1, name="trip_id", pattern=r'tripId="(\d+)"')
    db.add_all([token, trip])
    db.flush()
    db.add(LogValue(result_id=row.id, pattern_id=token.id, position=0, value=SECRET))  # stored before masking
    db.commit()

    assert run_job(session_factory) == 0

    db.expire_all()
    stored = db.query(RunResult).filter_by(run_id=run_id).one()
    assert SECRET not in stored.log and "[REDACTED:" in stored.log
    assert stored.redacted is False  # only the log changed; the run page's text did not
    assert [(v.pattern_id, v.value) for v in db.query(LogValue)] == [(trip.id, "42")]


def test_a_dry_run_leaves_the_log_and_its_values(db, session_factory, add_run):
    from src.ingestion.models import LogPattern, LogValue

    run_id = add_run(results=[("m", None)])
    row = db.query(RunResult).filter_by(run_id=run_id).one()
    row.log = f"GITHUB_TOKEN={SECRET}"
    token = LogPattern(project_id=1, name="token", pattern=r"GITHUB_TOKEN=(\S+)")
    db.add(token)
    db.flush()
    db.add(LogValue(result_id=row.id, pattern_id=token.id, position=0, value=SECRET))
    db.commit()
    assert run_job(session_factory, "--dry-run") == 0
    db.expire_all()
    assert SECRET in db.query(RunResult).filter_by(run_id=run_id).one().log
    assert db.query(LogValue).count() == 1
```

Append to `platforms/ingestion-service/tests/integration/test_export.py`:

```python
def test_the_log_and_its_values_are_exported(client, auth, project_role, stored, db):
    from src.ingestion.models import LogPattern, LogValue

    run_id = stored(1, "mine")
    bad = db.query(RunResult).filter_by(run_id=run_id, name="mine bad").one()
    bad.log = 'Trip id captured tripId="3960562" routeKey="wasToBos"'
    trip = LogPattern(project_id=1, name="trip_id", pattern=r'tripId="(\d+)"')
    route = LogPattern(project_id=1, name="route_key", pattern=r'routeKey="([^"]+)"')
    db.add_all([trip, route])
    db.flush()
    db.add_all([LogValue(result_id=bad.id, pattern_id=trip.id, position=0, value="3960562"),
                LogValue(result_id=bad.id, pattern_id=route.id, position=0, value="wasToBos")])
    db.commit()
    project_role(role="owner", project_id=1)

    _, _, ok, bad_line = lines(client.get(URL, headers=auth()))
    assert bad_line["log"] == 'Trip id captured tripId="3960562" routeKey="wasToBos"'
    assert bad_line["log_values"] == [{"pattern": "route_key", "value": "wasToBos"},
                                      {"pattern": "trip_id", "value": "3960562"}]
    assert ok["log"] is None and ok["log_values"] == []
```

Append to `platforms/ingestion-service/tests/integration/test_retention_job.py`:

```python
def test_log_values_go_with_their_results(db, session_factory, answer, add_run):
    from src.ingestion.models import LogPattern, LogValue

    old, recent = add_run(1, 40), add_run(1, 5)
    pattern = LogPattern(project_id=1, name="trip_id", pattern="x")
    db.add(pattern)
    db.flush()
    for run_id in (old, recent):
        result = db.query(RunResult).filter_by(run_id=run_id).one()
        db.add(LogValue(result_id=result.id, pattern_id=pattern.id, position=0, value=str(run_id)))
    db.commit()
    answer([live(1, 30)])

    assert run_job(session_factory) == 0

    db.expire_all()
    assert [v.value for v in db.query(LogValue)] == [str(recent)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_remask_job.py tests/integration/test_export.py tests/integration/test_retention_job.py -q`
Expected: the four new tests FAIL (the log keeps the token; `KeyError: 'log_values'`; the old value survives retention).

- [ ] **Step 3: Re-mask.** In `jobs/remask.py`:
  - change the imports to `from sqlalchemy.orm import Session, sessionmaker, undefer` and `from src.ingestion.service import log_pattern_service, log_value_service, masking_pattern_service`;
  - replace the `_ProjectPatterns` class with:

```python
class _ProjectPatterns:
    """Each project's patterns (masking, or log-value with `load=log_pattern_service.compiled_for`), loaded once
    per pass."""

    def __init__(self, db: Session, load=masking_pattern_service.compiled_for):
        self.db, self.load, self.cache = db, load, {}

    def __call__(self, project_id: int) -> tuple:
        if project_id not in self.cache:
            self.cache[project_id] = tuple(self.load(self.db, project_id))
        return self.cache[project_id]
```
  - change `_results_pass`'s signature to:

```python
def _results_pass(
    db: Session, project_id: Optional[int], batch_size: int, dry_run: bool, kinds: Counter,
    patterns_for: _ProjectPatterns, log_patterns_for: _ProjectPatterns,
) -> tuple[int, int]:
```
    add `.options(undefer(RunResult.log))` to its query (after `.join(Run, Run.id == RunResult.run_id)`), and replace the loop from `for row, row_project in batch:` up to (not including) `last_id = batch[-1][0].id` with:

```python
        relogged: dict = {}
        for row, row_project in batch:
            scanned += 1
            patterns = patterns_for(row_project)
            row_kinds: Counter = Counter()
            message, message_changed, message_cut = _remask_text(row.message, patterns, row_kinds)
            details, details_changed, details_cut = _remask_text(row.details, patterns, row_kinds)
            step, step_changed, step_cut = _remask_text(row.failed_step_text, patterns, row_kinds)
            definition, definition_changed, definition_cut = _remask_text(row.failed_step_definition, patterns, row_kinds)
            pattern, pattern_changed, pattern_cut = _remask_text(row.failed_step_pattern, patterns, row_kinds)
            log, log_changed, _ = _remask_text(row.log, patterns, row_kinds)
            shown_changed = message_changed or details_changed or step_changed or definition_changed or pattern_changed
            if not (shown_changed or log_changed):
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
                # `redacted` and `truncated` stay about the text the run page shows
                row.redacted = row.redacted or shown_changed
                row.truncated = (row.truncated or message_cut or details_cut or step_cut
                                 or definition_cut or pattern_cut)
                if log_changed:
                    row.log = log
                    relogged.setdefault(row_project, []).append((row.id, log))
        # A log that masking changed has its values read again: a value now hidden is no longer captured (ADR-032)
        for row_project, items in relogged.items():
            log_value_service.replace_values(db, items, log_patterns_for(row_project))
```
  - in `run_pass`, add `log_patterns_for = _ProjectPatterns(db, log_pattern_service.compiled_for)` after `patterns_for = _ProjectPatterns(db)` and pass it: `_results_pass(db, project_id, batch_size, dry_run, kinds, patterns_for, log_patterns_for)`;
  - in the module docstring, change "results stored before masking existed" paragraph's first sentence to: `For results stored before masking existed, or before a pattern was added. Message, details, the failed step and the log are re-masked; a log that changes has its log values read again.`

- [ ] **Step 4: Export.** In `api/v1/endpoints/export.py`:
  - change the docstring's result line to `    {"type": "result", "run_id": …, …result fields, "log", "log_values": [{"pattern", "value"}]}` and add `from sqlalchemy.orm import Session, undefer`, `from src.ingestion.models import LogPattern, LogValue, Run, RunChangedFile, RunComponent, RunResult`;
  - add before `_export`:

```python
def _log_values_of_run(db: Session, run_id: int) -> dict:
    """Each result's log values (ADR-032), patterns by name, values in log order."""
    values: dict = {}
    rows = (
        db.query(LogValue.result_id, LogPattern.name, LogValue.value)
        .join(LogPattern, LogPattern.id == LogValue.pattern_id)
        .join(RunResult, RunResult.id == LogValue.result_id)
        .filter(RunResult.run_id == run_id)
        .order_by(LogValue.result_id, LogPattern.name, LogValue.position)
    )
    for result_id, name, value in rows:
        values.setdefault(result_id, []).append({"pattern": name, "value": value})
    return values
```
  - replace the results loop in `_export` with:

```python
        values = _log_values_of_run(db, run_id)
        results = (db.query(RunResult).options(undefer(RunResult.log)).filter_by(run_id=run_id)
                   .order_by(RunResult.id).yield_per(1000))
        for result in results:
            yield _line({"type": "result", **_row(result, _RESULT_INTERNAL), "log_values": values.get(result.id, [])})
```

- [ ] **Step 5: Retention.** In `jobs/retention.py`, change `from sqlalchemy import text` to `from sqlalchemy import select, text`, the models import to `from src.ingestion.models import ApiKey, LogValue, Run, RunResult`, and in `_delete_in_batches` replace the comment and first delete with:

```python
        # Children first, explicitly: SQLite (the tests) does not enforce ON DELETE CASCADE by default. The results'
        # log values (ADR-032), then the results
        results = select(RunResult.id).where(RunResult.run_id.in_(batch))
        db.query(LogValue).filter(LogValue.result_id.in_(results)).delete(synchronize_session=False)
        db.query(RunResult).filter(RunResult.run_id.in_(batch)).delete(synchronize_session=False)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_remask_job.py tests/integration/test_export.py tests/integration/test_retention_job.py tests/integration/test_masking_patterns.py -q`
Expected: PASS.

- [ ] **Step 7: Docs.** In `platforms/ingestion-service/README.md`: in the `## Masking` re-mask bullet, change `(message, details and the failed step's text, definition and pattern; then run CI URLs and commit subjects)` to `(message, details, the failed step's text, definition and pattern, and the log, whose log values are then read again; then run CI URLs and commit subjects)`; in `## Retention`, add the sentence `A run's results go with their logs and log values.` at the end of the first paragraph; in `## Export`, add `Each result line carries its \`log\` and \`log_values\` (\`[{"pattern", "value"}]\`).` In `docs/SETUP.md` §4.7, in the export paragraph, add the same sentence.

- [ ] **Step 8: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/jobs/remask.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/export.py platforms/ingestion-service/src/ingestion/jobs/retention.py platforms/ingestion-service/tests/integration/test_remask_job.py platforms/ingestion-service/tests/integration/test_export.py platforms/ingestion-service/tests/integration/test_retention_job.py platforms/ingestion-service/README.md docs/SETUP.md
git commit -o platforms/ingestion-service/src/ingestion/jobs/remask.py platforms/ingestion-service/src/ingestion/api/v1/endpoints/export.py platforms/ingestion-service/src/ingestion/jobs/retention.py platforms/ingestion-service/tests/integration/test_remask_job.py platforms/ingestion-service/tests/integration/test_export.py platforms/ingestion-service/tests/integration/test_retention_job.py platforms/ingestion-service/README.md docs/SETUP.md -m "feat(ingestion): re-mask reads log values again; export and retention carry logs and values" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: `values` in `run-strip` and `latest-results`; smoke; delivery-1 docs and gate

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/service/log_value_service.py` (two readers)
- Modify: `platforms/ingestion-service/src/ingestion/service/analytics_service.py` (`latest_results`, `run_strip`)
- Test: `platforms/ingestion-service/tests/integration/test_run_strip.py`, `test_latest_results.py`
- Modify: `scripts/smoke_gateway.sh` (after the failed-steps block)
- Modify: `platforms/ingestion-service/README.md` (Analytics rows), `TECHNICAL_SPECIFICATION.md`, `TODO.md`

**Interfaces:**
- Consumes: `LogPattern`, `LogValue`, `RunResult`; `log_values.MAX_VALUES_PER_PATTERN`.
- Produces (in `log_value_service`): `values_by_result(db, result_ids: Iterable[int]) -> dict[int, list[{"name": str, "values": list[str], "link_template": str | None}]]`; `values_by_test_run(db, keys: Iterable[str], run_ids: Iterable[int]) -> dict[tuple[str, int], list[{"name": str, "values": list[str]}]]`. Both: patterns sorted by name (code-point order, done in Python), values in log order.
- Produces (HTTP): every `run-strip` entry gains `"values": [{"name", "values"}]` (`[]` when none; a re-run's results merged per pattern, duplicates removed, ≤ 20); every `latest-results` entry gains `"values": [{"name", "values", "link_template"}]` (`[]` when none).

- [ ] **Step 1: Write the failing tests.** In `platforms/ingestion-service/tests/integration/test_run_strip.py`, change the shape assertion in `test_each_test_gets_only_the_runs_it_was_in_oldest_to_newest` to:

```python
    assert {"run_id", "started_at", "branch", "status", "values"} == set(tests[A][0])
    assert all(entry["values"] == [] for entries in tests.values() for entry in entries)
```
and append:

```python
def test_each_bar_carries_the_values_of_its_run(client, make_key, project_role, auth, db):
    from src.ingestion.models import LogPattern

    project_role("viewer", project_id=7)
    db.add_all([LogPattern(project_id=7, name="trip_id", pattern=r'tripId="(\d+)"'),
                LogPattern(project_id=7, name="route_key", pattern=r'routeKey="([^"]+)"')])
    db.commit()
    _, key = make_key(project_id=7)
    now = datetime.now(timezone.utc)
    upload(client, key, started=now - timedelta(hours=3), results=[
        {"name": "A", "status": "passed", "log": 'tripId="3960562" routeKey="wasToBos" tripId="3960563"'},
        {"name": "B", "status": "skipped", "log": 'tripId="9"'}])
    upload(client, key, started=now - timedelta(hours=2), results=[{"name": "A", "status": "failed", "log": "no ids"}])
    upload(client, key, started=now - timedelta(hours=1), results=[   # a re-run: both attempts' values, once each
        {"name": "A", "status": "failed", "log": 'tripId="1"'},
        {"name": "A", "status": "passed", "log": 'tripId="1" tripId="2"'}])

    tests = strip(client, auth)["tests"]
    assert [e["values"] for e in tests[A]] == [
        [{"name": "route_key", "values": ["wasToBos"]}, {"name": "trip_id", "values": ["3960562", "3960563"]}],
        [],
        [{"name": "trip_id", "values": ["1", "2"]}],
    ]
    assert tests[B][0]["values"] == [{"name": "trip_id", "values": ["9"]}]  # whatever the status
    assert tests[C] == []
```

Append to `platforms/ingestion-service/tests/integration/test_latest_results.py`:

```python
LINK = "https://backoffice.example.com/trips/{value}"


def add_values(db, run, *pairs):
    """pairs: (LogPattern, [values]) for the run's one result."""
    from src.ingestion.models import LogValue

    row = db.query(RunResult).filter_by(run_id=run.id).one()
    for pattern, values in pairs:
        db.add_all([LogValue(result_id=row.id, pattern_id=pattern.id, position=i, value=v)
                    for i, v in enumerate(values)])
    db.commit()


def test_the_latest_result_carries_its_values_with_their_link(client, auth, project_role, seed_run, db):
    from src.ingestion.models import LogPattern

    project_role("viewer")
    trip = LogPattern(project_id=1, name="trip_id", pattern=r'tripId="(\d+)"', link_template=LINK)
    route = LogPattern(project_id=1, name="route_key", pattern=r'routeKey="([^"]+)"')
    db.add_all([trip, route])
    db.commit()
    older = seed_run(T0, results=(("search", "passed", 5),))
    latest = seed_run(T0 + timedelta(hours=1), results=(("search", "failed", 5),))
    add_values(db, older, (trip, ["1"]))
    add_values(db, latest, (trip, ["3960562", "3960563"]), (route, ["wasToBos"]))
    key = report_key("search")

    got = client.post(URL, json={"keys": [key]}, headers=auth()).json()["results"][key]
    assert got["values"] == [
        {"name": "route_key", "values": ["wasToBos"], "link_template": None},
        {"name": "trip_id", "values": ["3960562", "3960563"], "link_template": LINK},
    ]
    as_of = client.post(URL, json={"keys": [key], "run_id": older.id}, headers=auth()).json()["results"][key]
    assert as_of["values"] == [{"name": "trip_id", "values": ["1"], "link_template": LINK}]


def test_a_result_without_values_has_an_empty_list(client, auth, project_role, seed_run):
    project_role("viewer")
    seed_run(T0, results=(("search", "passed", 5),))
    key = report_key("search")
    assert client.post(URL, json={"keys": [key]}, headers=auth()).json()["results"][key]["values"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_run_strip.py tests/integration/test_latest_results.py -q`
Expected: FAIL with `KeyError: 'values'` and the changed set assertion.

- [ ] **Step 3: Readers** — append to `src/ingestion/service/log_value_service.py` (and extend its imports: `from typing import Dict, Iterable, List, Optional, Sequence, Tuple`, `from sqlalchemy import insert, select`, `from src.ingestion.models.log_pattern import LogPattern, LogValue`, `from src.ingestion.models.run import RunResult`):

```python
def _by_name(entries: List[dict]) -> List[dict]:
    """Patterns in code-point name order, whatever the database's collation."""
    return sorted(entries, key=lambda entry: entry["name"])


def values_by_result(db: Session, result_ids: Iterable[int]) -> Dict[int, List[dict]]:
    """Each result's values per pattern, with the pattern's link template (latest-results)."""
    ids = list(result_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(LogValue.result_id, LogPattern.name, LogPattern.link_template, LogValue.value)
        .join(LogPattern, LogPattern.id == LogValue.pattern_id)
        .where(LogValue.result_id.in_(ids))
        .order_by(LogValue.result_id, LogPattern.name, LogValue.position)
    ).all()
    out: Dict[int, List[dict]] = {}
    for result_id, name, template, value in rows:
        entries = out.setdefault(result_id, [])
        if not entries or entries[-1]["name"] != name:
            entries.append({"name": name, "values": [], "link_template": template})
        entries[-1]["values"].append(value)
    return {result_id: _by_name(entries) for result_id, entries in out.items()}


def values_by_test_run(db: Session, keys: Iterable[str], run_ids: Iterable[int]) -> Dict[Tuple[str, int], List[dict]]:
    """Each (test, run)'s values per pattern (run-strip): a re-run's results merged, first appearance first,
    duplicates removed, at most 20 per pattern."""
    keys, run_ids = list(keys), list(run_ids)
    if not keys or not run_ids:
        return {}
    rows = db.execute(
        select(RunResult.test_key, RunResult.run_id, LogPattern.name, LogValue.value)
        .join(LogValue, LogValue.result_id == RunResult.id)
        .join(LogPattern, LogPattern.id == LogValue.pattern_id)
        .where(RunResult.run_id.in_(run_ids), RunResult.test_key.in_(keys))
        .order_by(RunResult.test_key, RunResult.run_id, LogPattern.name, RunResult.id, LogValue.position)
    ).all()
    out: Dict[Tuple[str, int], List[dict]] = {}
    for key, run_id, name, value in rows:
        entries = out.setdefault((key, run_id), [])
        if not entries or entries[-1]["name"] != name:
            entries.append({"name": name, "values": []})
        values = entries[-1]["values"]
        if value not in values and len(values) < log_values.MAX_VALUES_PER_PATTERN:
            values.append(value)
    return {pair: _by_name(entries) for pair, entries in out.items()}
```

- [ ] **Step 4: Wire them in.** In `src/ingestion/service/analytics_service.py`, add `from src.ingestion.service import log_value_service` after the models import. In `latest_results`, add `RunResult.id.label("result_id"),` as the first column passed to `_latest_ranked(…)` after `filters,`, and replace the loop with:

```python
    rows = list(db.execute(select(ranked).where(ranked.c.position == 1)).mappings())
    values = log_value_service.values_by_result(db, [r["result_id"] for r in rows])
    out = {}
    for r in rows:
        entry = {"status": r["status"], "run_id": r["run_id"], "branch": r["branch"],
                 "environment": r["environment"], "started_at": as_utc(r["started_at"]),
                 "message": r["message"][:MESSAGE_EXCERPT] if r["message"] is not None else None,
                 # Log values of this result (ADR-032), with each pattern's link template
                 "values": values.get(r["result_id"], [])}
        step = failed_step_of(r["status"], r["message"], r["details"], r["failed_step_text"], r["failed_step_line"],
                              r["failed_step_definition"], r["failed_step_pattern"])
        if step:
            entry["failed_step"] = step
        out[r["test_key"]] = entry
    return out
```

In `run_strip`, after `rows = db.execute(…).all()`, add:

```python
    # Log values per bar (ADR-032): the test's results in that run, merged per pattern
    values = log_value_service.values_by_test_run(db, keys, {row.run_id for row in rows})
```
and change the append to:

```python
        tests[row.test_key].append({"run_id": row.run_id, "started_at": row.started_at, "branch": row.branch,
                                    "status": value, "values": values.get((row.test_key, row.run_id), [])})
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/integration/test_run_strip.py tests/integration/test_latest_results.py tests/integration/test_analytics_endpoints.py -q`
Expected: PASS.

- [ ] **Step 6: Smoke.** In `scripts/smoke_gateway.sh`, after the failed-steps block (after the line `body_has "... grouped by its step definition" '"by":"definition"'`), add:

```bash
# ---- log values: a pattern from Settings, a value read from an uploaded log (ADR-032) ----
check "add a log-value pattern -> ingestion-service" 201 POST "$BASE/api/v1/projects/$PROJECT_ID/log-patterns" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"name":"smoke_trip","pattern":"tripId=\"(\\d+)\"","link_template":"https://backoffice.example.com/trips/{value}"}'
LOG_BODY="{\"run\":{\"ci_provider\":\"local\",\"branch\":\"smoke-log\",\"started_at\":\"$NOW\",\"finished_at\":\"$NOW\"},\"results\":[{\"name\":\"log-trip\",\"status\":\"passed\",\"log\":\"INFO [App] Trip id captured tripId=\\\"3960562\\\"\"}]}"
check "upload a result with a log" 201 POST "$BASE/api/v1/collect/runs" \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "$LOG_BODY"
check "analytics tests finds the logged test" 200 GET "$BASE/api/v1/projects/$PROJECT_ID/analytics/tests?search=log-trip" "${AUTH[@]}"
LOG_KEY="$(sed -n 's/.*"test_key":"\([0-9a-f]\{64\}\)".*/\1/p' "$TMP/body" | head -1)"
check "latest-results -> the log value" 200 POST \
  "$BASE/api/v1/projects/$PROJECT_ID/analytics/latest-results" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"keys\":[\"${LOG_KEY:-0000000000000000000000000000000000000000000000000000000000000000}\"]}"
body_has "... with the value and its link template" '"values":[{"name":"smoke_trip","values":["3960562"],"link_template":"https://backoffice.example.com/trips/{value}"}]'
```

Run: `bash -n scripts/smoke_gateway.sh`. Expected: exit 0, no output. (Do not run the script.)

- [ ] **Step 7: Docs.** In `platforms/ingestion-service/README.md`, in the Analytics table:
  - in the `POST /latest-results` row, change `{status, run_id, branch, environment, started_at, message, failed_step?}` to `{status, run_id, branch, environment, started_at, message, values, failed_step?}` and append before ` Every project role |`: `` `values` (`[{name, values, link_template}]`, `[]` when none) are the result's log values, patterns by name, values in log order (ADR-032).``
  - in the `POST /run-strip` row, change `[{"run_id", "started_at", "branch", "status"}, ...]` to `[{"run_id", "started_at", "branch", "status", "values"}, ...]` and append: `` `values` (`[{name, values}]`, `[]` when none) are the test's log values in that run, a re-run's results merged per pattern without duplicates.``

  In `TECHNICAL_SPECIFICATION.md`, in the **Analytics** bullet, change `run-strip (each test's own last results, for case lists)` to `run-strip (each test's own last results with their log values, for case lists)` and `latest-results (each test's latest result with its failed step` to `latest-results (each test's latest result with its failed step and log values`.

  In `TODO.md`, under `### C. Results, history and evidence`, add:

```markdown
- [x] Log values (ADR-032): a project's patterns pick values (a trip id, a route) out of each result's masked log; they show on every Last runs bar's tooltip, on the test case page and on the feature page's scenario cards, copyable and optionally linked. Spec: `docs/superpowers/specs/2026-10-14-log-values-design.md`.
- [ ] Search runs by a log value (the stored values make it possible).
- [ ] Show a result's whole log in QEOS (it is stored, masked, 64 KB).
```

- [ ] **Step 8: Delivery-1 gate.** Create the CI-matching venv (see "How to run things"), then from `platforms/ingestion-service`:
  `unset PYTHONPATH; SECRET_KEY=ci-test-secret "$PY" -m pytest tests/ -q` — Expected: all pass.
  From the repo root: `python scripts/check_architecture_docs.py` — Expected: exit 0.

- [ ] **Step 9: Commit**

```bash
git add platforms/ingestion-service/src/ingestion/service/log_value_service.py platforms/ingestion-service/src/ingestion/service/analytics_service.py platforms/ingestion-service/tests/integration/test_run_strip.py platforms/ingestion-service/tests/integration/test_latest_results.py scripts/smoke_gateway.sh platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md TODO.md
git commit -o platforms/ingestion-service/src/ingestion/service/log_value_service.py platforms/ingestion-service/src/ingestion/service/analytics_service.py platforms/ingestion-service/tests/integration/test_run_strip.py platforms/ingestion-service/tests/integration/test_latest_results.py scripts/smoke_gateway.sh platforms/ingestion-service/README.md TECHNICAL_SPECIFICATION.md TODO.md -m "feat(ingestion): log values on run-strip bars and latest results; smoke through the gateway" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Delivery 2 — collector 0.9.0

### Task 9: `log` from Cucumber text attachments and JUnit `system-out`

**Files:**
- Modify: `collector/src/qeos_collector/formats.py` (imports; new helpers before `_cucumber_feature`; one line in `_cucumber_feature`)
- Modify: `collector/src/qeos_collector/junit.py` (`_add_case`)
- Test: `collector/tests/test_cucumber.py`, `collector/tests/test_junit.py` (append)
- Modify: `collector/README.md` (`## What it does with the files`)

**Interfaces:**
- Consumes: `junit._cut` (64 KB cut, keeps the start).
- Produces: each Cucumber result dict gains `"log": str` (text attachments of the scenario's hook steps, Background steps and steps in order, cucumber-jvm's scenario `before`/`after` hooks around them, joined by `\n`, cut to 64 KB) when there is text; each JUnit result (the final outcome, not Surefire's per-attempt rows) gains `"log"` from its `<system-out>` when not blank. In `formats.py`: `LOG_MEDIA_TYPES = ("text/x.cucumber.log+plain", "text/plain")`, `_attachment_text(attachment) -> Optional[str]`, `_scenario_log(element: dict, steps: list) -> Optional[str]`.

- [ ] **Step 1: Write the failing tests.** Append to `collector/tests/test_cucumber.py` (add `import base64` to its imports):

```python
# --- log (log values, spec 2026-10-14 §2.2) --------------------------------------------------------------------


def b64(data):
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def logging_step(keyword, name, *texts, media="text/x.cucumber.log+plain"):
    return {"keyword": keyword, "name": name, "line": 3, "result": {"status": "passed", "duration": 1},
            "embeddings": [{"data": b64(text), "mime_type": media} for text in texts]}


def log_of(tmp_path, steps, background=None, **element):
    elements = [{"type": "background", "keyword": "Background", "name": "", "steps": background}] if background else []
    elements.append({"type": "scenario", "keyword": "Scenario", "name": "Books a trip", "steps": steps, **element})
    parsed = parse_file(write(tmp_path, [{"uri": "features/book.feature", "name": "Booking", "elements": elements}]))
    return parsed.results[0].get("log")


def test_text_attachments_become_the_log_in_step_order_background_first(tmp_path):
    log = log_of(tmp_path,
                 [logging_step("When ", "I book", 'INFO [App] Trip id captured tripId="3960562"', "INFO [App] Paid"),
                  logging_step("Then ", "it confirms", "INFO [App] Confirmed")],
                 background=[logging_step("Given ", "I sign in", "INFO [Hooks] Signed in")])
    assert log == "\n".join(["INFO [Hooks] Signed in", 'INFO [App] Trip id captured tripId="3960562"',
                             "INFO [App] Paid", "INFO [App] Confirmed"])


def test_text_plain_counts_with_or_without_parameters(tmp_path):
    log = log_of(tmp_path, [logging_step("When ", "a", "one", media="text/plain"),
                            logging_step("When ", "b", "two", media="Text/Plain; charset=utf-8")])
    assert log == "one\ntwo"


def test_images_and_other_media_never_join_the_log(tmp_path):
    step = logging_step("When ", "a", "kept")
    step["embeddings"] += [{"data": b64(b"\x89PNG\r\n\x1a\n\x00\x00"), "mime_type": "image/png"},
                           {"data": b64('{"a": 1}'), "mime_type": "application/json"},
                           {"data": b64("<p>x</p>"), "mime_type": "text/html"}]
    assert log_of(tmp_path, [step]) == "kept"


def test_plain_text_data_is_kept_as_it_is(tmp_path):
    step = {"keyword": "When ", "name": "a", "result": {"status": "passed"},
            "embeddings": [{"data": 'INFO tripId="1" done', "mime_type": "text/plain"}]}
    assert log_of(tmp_path, [step]) == 'INFO tripId="1" done'


def test_invalid_utf8_in_an_attachment_is_replaced_not_fatal(tmp_path):
    step = {"keyword": "When ", "name": "a", "result": {"status": "passed"},
            "embeddings": [{"data": b64(b"trip \xff\xfe id"), "mime_type": "text/plain"}]}
    assert log_of(tmp_path, [step]) == "trip �� id"


def test_hook_steps_and_cucumber_jvm_scenario_hooks_count(tmp_path):
    hook = logging_step("Before", "", "INFO [Hooks] Started")  # cucumber-js: a hidden hook step
    hook["hidden"] = True
    jvm = lambda text: [{"result": {"status": "passed"}, "embeddings": [{"data": b64(text), "mime_type": "text/plain"}]}]
    log = log_of(tmp_path, [hook, logging_step("When ", "a", "INFO step")], before=jvm("jvm before"),
                 after=jvm("jvm after"))
    assert log == "jvm before\nINFO [Hooks] Started\nINFO step\njvm after"


def test_attachments_under_the_newer_names_count(tmp_path):
    step = {"keyword": "When ", "name": "a", "result": {"status": "passed"},
            "attachments": [{"body": "from attachments", "media_type": "text/x.cucumber.log+plain"},
                            {"data": b64("camel case"), "mediaType": "text/plain"}]}
    assert log_of(tmp_path, [step]) == "from attachments\ncamel case"


def test_a_failed_scenario_keeps_its_log_and_its_failed_step(tmp_path):
    failing = logging_step("When ", "I pay", "INFO [App] Paying")
    failing["result"] = {"status": "failed", "error_message": "boom"}
    parsed = parse_file(write(tmp_path, [{"uri": "f.feature", "name": "F", "elements": [
        {"type": "scenario", "name": "Pays", "steps": [failing]}]}]))
    row = parsed.results[0]
    assert row["status"] == "failed" and row["log"] == "INFO [App] Paying" and row["failed_step"]["text"] == "When I pay"


def test_the_log_is_cut_to_64_kb(tmp_path):
    assert log_of(tmp_path, [logging_step("When ", "a", "é" * 40_000)]) == "é" * 32_768


def test_no_text_means_no_log(tmp_path):
    assert log_of(tmp_path, [{"keyword": "When ", "name": "a", "result": {"status": "passed"}}]) is None
    assert log_of(tmp_path, [logging_step("When ", "a", "  \n ")]) is None


@pytest.mark.parametrize("embeddings", [
    None, "text", {"data": "x", "mime_type": "text/plain"}, [None, 3, "x"],
    [{"data": 5, "mime_type": "text/plain"}], [{"data": "eA=="}], [{"data": "", "mime_type": "text/plain"}],
    [{"data": "eA==", "mime_type": 7}],
])
def test_odd_attachment_shapes_are_skipped(tmp_path, embeddings):
    step = {"keyword": "When ", "name": "a", "result": {"status": "passed"}, "embeddings": embeddings}
    assert log_of(tmp_path, [step]) is None
```

Append to `collector/tests/test_junit.py`:

```python
def test_system_out_becomes_the_log(tmp_path):
    xml = ('<testsuite name="s">'
           '<testcase classname="C" name="books"><system-out>INFO tripId="3960562"\nINFO done\n</system-out></testcase>'
           '<testcase classname="C" name="quiet"><system-out>   </system-out></testcase>'
           '<testcase classname="C" name="none"/></testsuite>')
    rows = by_name(parse_file(write(tmp_path, xml)))
    assert rows["books"]["log"] == 'INFO tripId="3960562"\nINFO done\n'
    assert "log" not in rows["quiet"] and "log" not in rows["none"]


def test_a_long_system_out_is_cut_to_64_kb(tmp_path):
    xml = f'<testsuite name="s"><testcase classname="C" name="t"><system-out>{"x" * 70_000}</system-out></testcase></testsuite>'
    assert by_name(parse_file(write(tmp_path, xml)))["t"]["log"] == "x" * junit.MAX_TEXT_BYTES
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `collector/`): `"$CPY" -m pytest tests/test_cucumber.py tests/test_junit.py -q`
Expected: the new tests FAIL (`KeyError: 'log'` / `None != '…'`); the others pass.

- [ ] **Step 3: Cucumber.** In `collector/src/qeos_collector/formats.py`, add `import base64` and `import binascii` to the imports (alphabetical, before `import json`), and add before `def _cucumber_feature`:

```python
# Log lines (spec 2026-10-14 log values §2.2): text attachments only. cucumber-js writes this.log() lines as
# text/x.cucumber.log+plain and the classic JSON formatter base64-encodes every attachment; images and other media
# are never part of the log
LOG_MEDIA_TYPES = ("text/x.cucumber.log+plain", "text/plain")


def _attachment_text(attachment: object) -> Optional[str]:
    if not isinstance(attachment, dict):
        return None
    media = attachment.get("mime_type") or attachment.get("media_type") or attachment.get("mediaType")
    if not isinstance(media, str) or media.split(";", 1)[0].strip().lower() not in LOG_MEDIA_TYPES:
        return None
    data = attachment.get("data") if attachment.get("data") is not None else attachment.get("body")
    if not isinstance(data, str) or not data:
        return None
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return data  # a formatter that wrote the text itself (it has spaces or other non-base64 characters)
    # A cut multi-byte character or binary bytes under a text media type become U+FFFD, never a failed parse
    return raw.decode("utf-8", errors="replace")


def _step_texts(step: object) -> list:
    if not isinstance(step, dict):
        return []
    texts = []
    for key in ("embeddings", "attachments"):
        attachments = step.get(key)
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            text = _attachment_text(attachment)
            if text is not None:
                texts.append(text)
    return texts


def _scenario_log(element: dict, steps: list) -> Optional[str]:
    """The scenario's text attachments in order: cucumber-jvm's scenario hooks (`before`), then its steps (cucumber-js
    hook steps and Background steps included), then `after`; joined by newlines and cut to 64 KB. None without text."""
    before = element.get("before") if isinstance(element.get("before"), list) else []
    after = element.get("after") if isinstance(element.get("after"), list) else []
    log = "\n".join(text.rstrip("\r\n") for step in [*before, *steps, *after] for text in _step_texts(step))
    return _cut(log) if log.strip() else None
```

In `_cucumber_feature`, just before `        parsed.results.append(row)`, add:

```python
        log = _scenario_log(element, steps)
        if log is not None:
            row["log"] = log
```

- [ ] **Step 4: JUnit.** In `collector/src/qeos_collector/junit.py`, in `_add_case`, just before the final `    parsed.results.append(result)`, add:

```python
    # The test case's output, for log values (spec 2026-10-14 log values §2.2); blank output sends nothing
    out = case.find("system-out")
    log = "".join(out.itertext()) if out is not None else ""
    if log.strip():
        result["log"] = _cut(log)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `"$CPY" -m pytest tests/test_cucumber.py tests/test_junit.py tests/test_formats.py tests/test_payload.py -q`
Expected: PASS.

- [ ] **Step 6: README.** In `collector/README.md`, `## What it does with the files`:
  - at the end of the first bullet (JUnit), add: `From 0.9.0 a test case's \`<system-out>\` is sent as its \`log\` (cut to 64 KB; blank output sends nothing), for log values in QEOS.`
  - after the Cucumber bullet's `failed_step` sentences, add a sentence: `From 0.9.0 each scenario also carries \`log\`: its text attachments (\`text/x.cucumber.log+plain\`, as cucumber-js's \`this.log()\` writes them, and \`text/plain\`; decoded from base64 when so encoded) in step order, hook and Background steps included, joined by newlines and cut to 64 KB; images and other attachments never. No text, no \`log\`. QEOS masks it, stores it and reads log values from it.`
  - change the bullet `- Cuts failure messages and output to 64 KB, as the platform does.` to `- Cuts failure messages, output and logs to 64 KB, as the platform does.`

- [ ] **Step 7: Commit**

```bash
git add collector/src/qeos_collector/formats.py collector/src/qeos_collector/junit.py collector/tests/test_cucumber.py collector/tests/test_junit.py collector/README.md
git commit -o collector/src/qeos_collector/formats.py collector/src/qeos_collector/junit.py collector/tests/test_cucumber.py collector/tests/test_junit.py collector/README.md -m "feat(collector): send each result's log from Cucumber text attachments and JUnit system-out" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Retry without `log` on an older platform; version 0.9.0

**Files:**
- Modify: `collector/src/qeos_collector/upload.py`
- Test: `collector/tests/test_upload.py` (append)
- Modify: `collector/src/qeos_collector/__init__.py`, `collector/tests/test_package.py` (separate release commit)
- Modify: `collector/README.md` (compatibility paragraph), `docs/SETUP.md` (new §4.10 "Log values", collector and test-repository part)

**Interfaces:**
- Consumes: `upload.without_step_details`, `STEP_DETAILS`, `OLDER_PLATFORM` (existing).
- Produces (in `qeos_collector.upload`): `LOG_FIELD = "log"`, `OLDER_PLATFORM_LOG: str`, `_refused_fields(body: bytes) -> tuple[bool, bool]` (step details, log), `without_log(body: bytes) -> Optional[bytes]`, `_downgrade(payload: bytes, body: bytes, warn) -> Optional[bytes]`. One downgrade per part, as before: a 422 naming both kinds of field strips both in the same retry.

- [ ] **Step 1: Write the failing tests** — append to `collector/tests/test_upload.py`:

```python
LOG_PART = Part(body=json.dumps({"run": {}, "results": [
    {"name": "t", "status": "passed", "log": 'INFO tripId="3960562"'},
    {"name": "u", "status": "passed"}]}).encode("utf-8"), idempotency_key="gh-1-1-log", count=2)
LOG_422 = {"detail": [{"type": "extra_forbidden", "loc": ["body", "results", 0, "log"],
                       "msg": "Extra inputs are not permitted"}]}


def test_an_older_platform_gets_the_upload_again_without_the_log(platform):
    platform.reply(422, LOG_422)
    platform.reply(201, RECEIPT)
    warnings = []
    assert send_step(platform, warnings, part=LOG_PART) == (201, RECEIPT)
    first, second = (json.loads(r["body"]) for r in platform.requests)
    assert first["results"][0]["log"] == 'INFO tripId="3960562"'
    assert second["results"] == [{"name": "t", "status": "passed"}, {"name": "u", "status": "passed"}]
    assert {r["headers"]["Idempotency-Key"] for r in platform.requests} == {"gh-1-1-log"}
    assert len(warnings) == 1 and "log" in warnings[0] and "older than this collector" in warnings[0]


def test_a_platform_older_than_both_fields_gets_one_retry_without_either(platform):
    body = json.loads(STEP_PART.body)
    body["results"][0]["log"] = "INFO x"
    part = Part(body=json.dumps(body, ensure_ascii=False).encode("utf-8"), idempotency_key="gh-1-1-both", count=1)
    platform.reply(422, {"detail": OLD_422["detail"] + LOG_422["detail"]})
    platform.reply(201, RECEIPT)
    warnings = []
    assert send_step(platform, warnings, part=part)[0] == 201
    second = json.loads(platform.requests[1]["body"])["results"][0]
    assert "log" not in second and second["failed_step"] == {"text": "When I search Lisbon", "line": 4}
    assert len(platform.requests) == 2 and len(warnings) == 2


def test_the_retry_without_the_log_happens_once(platform):
    platform.reply(422, LOG_422)
    platform.reply(422, LOG_422)
    with pytest.raises(UploadError) as err:
        send_step(platform, [], part=LOG_PART)
    assert len(platform.requests) == 2 and err.value.retryable is False


def test_a_422_naming_the_log_of_a_part_without_one_is_not_retried(platform):
    platform.reply(422, LOG_422)
    with pytest.raises(UploadError):
        send_step(platform, [], part=PART)
    assert len(platform.requests) == 1


def test_a_422_about_something_else_keeps_the_log(platform):
    platform.reply(422, {"detail": [{"type": "string_too_long", "loc": ["body", "results", 0, "name"], "msg": "x"}]})
    with pytest.raises(UploadError):
        send_step(platform, [], part=LOG_PART)
    assert len(platform.requests) == 1


def test_without_log_strips_only_the_log():
    body = json.loads(upload.without_log(LOG_PART.body))
    assert body["results"] == [{"name": "t", "status": "passed"}, {"name": "u", "status": "passed"}]
    assert upload.without_log(PART.body) is None
    assert upload.without_log(b"not json") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `"$CPY" -m pytest tests/test_upload.py -q`
Expected: the new tests FAIL (`UploadError` on the first 422; `AttributeError: … has no attribute 'without_log'`).

- [ ] **Step 3: Implement.** In `collector/src/qeos_collector/upload.py`:
  - after `OLDER_PLATFORM = (…)`, add:

```python
LOG_FIELD = "log"
OLDER_PLATFORM_LOG = ("the platform is older than this collector and refused the results' log: sent again without "
                      "it (upgrade QEOS to see log values)")
```
  - in `upload_part`, replace the `else:` branch body (from the comment `# Spec 2026-10-14 §2: …` to `continue`) with:

```python
                # A server from before this collector forbids its newer fields (spec 2026-10-14 §2: the failed step's
                # definition and pattern; log values §2.2: `log`). Once, and only for those: nothing was stored, so
                # the same Idempotency-Key is reused
                stripped = None if downgraded or status != 422 else _downgrade(payload, body, warn)
                if stripped is None:
                    raise UploadError(_explain(status, body, response_headers))
                payload, downgraded = stripped, True
                continue
```
  - replace `_names_step_details` with:

```python
def _refused_fields(body: bytes) -> Tuple[bool, bool]:
    """(step details, log): which of this collector's newer fields a 422 forbids (FastAPI: {"detail": [{"loc": …}]})."""
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        return False, False
    if not isinstance(detail, list):
        return False, False
    locs = [error["loc"] for error in detail if isinstance(error, dict) and isinstance(error.get("loc"), list)]
    step = any(loc[-2:-1] == ["failed_step"] and loc[-1] in STEP_DETAILS for loc in locs)
    log = any(len(loc) >= 3 and loc[-1] == LOG_FIELD and loc[-3] == "results" for loc in locs)
    return step, log


def _downgrade(payload: bytes, body: bytes, warn: Callable[[str], None]) -> Optional[bytes]:
    """The payload without the newer fields the 422 names, one warning per kind; None when there is nothing to strip."""
    step, log = _refused_fields(body)
    stripped, notes = None, []
    if step:
        without = without_step_details(payload)
        if without is not None:
            payload = stripped = without
            notes.append(OLDER_PLATFORM)
    if log:
        without = without_log(payload)
        if without is not None:
            payload = stripped = without
            notes.append(OLDER_PLATFORM_LOG)
    for note in notes:
        warn(note)
    return stripped
```
  - after `without_step_details`, add:

```python
def without_log(body: bytes) -> Optional[bytes]:
    """The body without the results' `log`; None when no result has one (nothing to retry without)."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    removed = False
    for result in (data.get("results") if isinstance(data, dict) else None) or []:
        if isinstance(result, dict) and LOG_FIELD in result:
            del result[LOG_FIELD]
            removed = True
    if not removed:
        return None
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="replace")
```
  (`Callable`, `Optional` and `Tuple` are already imported from `typing` in `upload.py`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `"$CPY" -m pytest tests/test_upload.py tests/test_spool.py tests/test_cli.py -q`
Expected: PASS (the existing step-details tests included: one warning, one retry).

- [ ] **Step 5: README and SETUP.** In `collector/README.md`, after the paragraph that starts `Collector 0.8.0 also works with a platform that has migration 021 but not 022`, add:

```markdown
  Collector 0.9.0 sends `log` (above); a platform without ingestion migration 023 answers 422 naming `results.N.log`, and the collector sends the upload once more without any result's `log`, under the same Idempotency-Key, and logs one line saying the platform is older than the collector. A platform older than both 022 and 023 names both in one 422: both are stripped in that one retry.
```

In `docs/SETUP.md`, add `   - [4.10 Log values](#410-log-values)` to the Contents list after the 4.9 line, and add a new section just before `## 5. Wiring a real test repository end to end` (keep the `---` separators as the other sections do):

```markdown
### 4.10 Log values

**What it does.** Values your tests log, such as the trip a booking scenario created
(`INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"`), show on every Last runs bar's
tooltip, on the test case page and on the feature page's scenario cards (ADR-032).

**What the test repository must do.** The log has to reach the report:
- Cucumber JSON (cucumber-js): attach each log line to the running scenario with `this.log(text)`. A logger that only
  prints to the console is not enough: console lines cannot be tied to a scenario. A common way: a `Before` hook
  hands `this.log` to the logger, which attaches every line it prints, and an `After` hook takes it back.
- JUnit XML: the test case's `<system-out>` is used as is.
- Collector **0.9.0** or later sends the log (`log` on each result, cut to 64 KB). Older collectors send none; 0.9.0
  against an older QEOS retries once without it.

**Verify (4.10):** after a run, open `test-results/cucumber-report.json` and check that the steps carry
`embeddings` with `"mime_type": "text/x.cucumber.log+plain"`; `qeos-collector upload "test-results/*.json" --dry-run`
prints each result's `log`.
```

- [ ] **Step 6: Commit the feature**

```bash
git add collector/src/qeos_collector/upload.py collector/tests/test_upload.py collector/README.md docs/SETUP.md
git commit -o collector/src/qeos_collector/upload.py collector/tests/test_upload.py collector/README.md docs/SETUP.md -m "feat(collector): an older platform that refuses log gets the upload once more without it" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Version 0.9.0.** In `collector/src/qeos_collector/__init__.py` set `__version__ = "0.9.0"`; in `collector/tests/test_package.py` change `"0.8.0"` to `"0.9.0"`.

Run (from `collector/`): `"$CPY" -m pip install -e . -q && "$CPY" -m pytest -q`
Expected: all pass (the editable install refreshes the package metadata that `test_legacy_names.py` reads).

```bash
git add collector/src/qeos_collector/__init__.py collector/tests/test_package.py
git commit -o collector/src/qeos_collector/__init__.py collector/tests/test_package.py -m "release: qeos-collector 0.9.0 (log values)" -m "The version only. The pinned collector-v0.8.0 references move in a follow-up commit once the collector-v0.9.0 tag exists, so no published doc points at a missing tag." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

> **Controller note (not an implementer step):** after Delivery 1 and this task are on master and CI is green, the user tags the release commit `collector-v0.9.0` and moves the floating `collector-v0` to it (`.github/workflows/release-collector.yml` runs on the full-version tag only and checks that the tag matches `__version__`). Task 11 runs only after that tag exists.

### Task 11: Pin `collector-v0.9.0` everywhere (only after the tag exists)

**Files:**
- Modify: `IMPLEMENTATION_PLAN.md`, `README.md`, `TODO.md`, `collector-jenkins/vars/qeosCollectorUpload.groovy`, `collector/README.md`, `dashboard/src/pages/ProjectSettingsPage.tsx`, `dashboard/src/pages/ProjectSettingsPage.test.tsx`, `dashboard/src/templates/qeos-run.yml.txt`, `docs/SETUP.md`, `templates/github/qeos-run.yml`, `templates/qeos-collector.azure-pipelines.yml`, `templates/qeos-collector.gitlab-ci.yml` (the same set as commit 07313b6)

**Interfaces:** none (docs and pins).

- [ ] **Step 1: Confirm the tag exists.** Run: `git ls-remote --tags origin collector-v0.9.0`. Expected: one line. If empty, stop and tell the controller.

- [ ] **Step 2: Move every pin.** Run from the repo root:

```bash
FILES="IMPLEMENTATION_PLAN.md README.md TODO.md collector-jenkins/vars/qeosCollectorUpload.groovy collector/README.md dashboard/src/pages/ProjectSettingsPage.tsx dashboard/src/pages/ProjectSettingsPage.test.tsx dashboard/src/templates/qeos-run.yml.txt docs/SETUP.md templates/github/qeos-run.yml templates/qeos-collector.azure-pipelines.yml templates/qeos-collector.gitlab-ci.yml"
sed -i 's/collector-v0\.8\.0/collector-v0.9.0/g' $FILES
grep -rn "collector-v0\.8\.0" --include=*.md --include=*.yml --include=*.txt --include=*.ts --include=*.tsx --include=*.groovy . | grep -v "docs/superpowers" | grep -v node_modules
```
Expected: the grep prints nothing. Then in `IMPLEMENTATION_PLAN.md`, change the release-tag range `` `collector-v0.1.0`…`v0.8.0` `` (or `…\`v0.9.0\`` if sed already touched it) so it reads `` `collector-v0.1.0`…`v0.9.0` ``. Lines that name the release a feature arrived in ("collector 0.8.0", "from 0.8.0") stay as they are.

- [ ] **Step 3: Check the dashboard pin test.** From `dashboard/`: `npx vitest run src/pages/ProjectSettingsPage.test.tsx`. Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add $FILES
git commit -o $FILES -m "release: pin collector-v0.9.0 everywhere" -m "Every pinned collector-v0.8.0 moves to collector-v0.9.0: the READMEs, SETUP, the Jenkins default ref, the GitLab and Azure templates, the Run from QEOS workflow template and the Project Settings snippet (and its test); the plan's release-tag range. Lines that name the release a feature arrived in stay." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Delivery 3 — dashboard

### Task 12: Settings card "Log values"

**Files:**
- Create: `dashboard/src/api/logPatterns.ts`
- Create: `dashboard/src/components/LogValuesCard.tsx`, `dashboard/src/components/LogValuesCard.test.tsx`
- Modify: `dashboard/src/pages/ProjectSettingsPage.tsx` (after `<MaskingCard … />`), `dashboard/src/pages/ProjectSettingsPage.test.tsx`
- Modify: `dashboard/src/test/server.ts` (default handler), `dashboard/src/index.css` (after `.masking-form h4`)
- Modify: `DESIGN.md` (new `### Log Values` after `### Run Strip`), `docs/SETUP.md` §4.10

**Interfaces:**
- Consumes (HTTP, Task 6): `GET/POST /api/v1/projects/{id}/log-patterns`, `POST …/preview`, `DELETE …/{id}`; 422/409 `detail: {code, message}` parsed by `apiFetch` into `ApiError.code` / `ApiError.detail`.
- Produces (in `api/logPatterns.ts`): `interface LogPattern { id: number; name: string; pattern: string; link_template: string | null; created_at: string | null }`, `interface LogScan { state: "idle" | "running"; since: string | null }`, `interface LogPatternList { patterns: LogPattern[]; scan: LogScan }`, `interface LogPatternInput { name: string; pattern: string; link_template: string | null }`, `listLogPatterns(projectId)`, `addLogPattern(projectId, input)`, `previewLogPattern(projectId, name, pattern, sample): Promise<{ masked: string; values: string[] }>`, `removeLogPattern(projectId, patternId)`.
- Produces: `components/LogValuesCard.tsx` default export `LogValuesCard({ projectId, canEdit })`; `PATTERN_EXAMPLES`.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill before editing UI** (project rule). Read `DESIGN.md` §Components (Cards, Inputs / Fields, Error Banner, Destructive Confirmation) and `components/MaskingCard.tsx`, which this card mirrors.

- [ ] **Step 1: The API module** — create `dashboard/src/api/logPatterns.ts`:

```ts
import { apiFetch } from "./http";

// Mirrors platforms/ingestion-service/src/ingestion/schemas/log_pattern.py (ADR-032)

export interface LogPattern {
  id: number;
  name: string;
  pattern: string;
  link_template: string | null;
  created_at: string | null;
}

export interface LogScan {
  state: "idle" | "running";
  since: string | null;
}

export interface LogPatternList {
  patterns: LogPattern[];
  scan: LogScan;
}

export interface LogPatternInput {
  name: string;
  pattern: string;
  link_template: string | null;
}

const base = (projectId: number) => `/api/v1/projects/${projectId}/log-patterns`;

/** The project's patterns (name order) and whether past runs are being scanned. */
export function listLogPatterns(projectId: number): Promise<LogPatternList> {
  return apiFetch(base(projectId));
}

/** 422/409 carry `{code, message}`: `ApiError.code` names the field (name, pattern, link_template) or `limit`. */
export function addLogPattern(projectId: number, input: LogPatternInput): Promise<LogPattern> {
  return apiFetch(base(projectId), { method: "POST", body: JSON.stringify(input) });
}

/** The sample as it would be stored (masked) and the values this pattern finds in it; nothing is saved. */
export function previewLogPattern(
  projectId: number,
  name: string,
  pattern: string,
  sample: string,
): Promise<{ masked: string; values: string[] }> {
  return apiFetch(`${base(projectId)}/preview`, { method: "POST", body: JSON.stringify({ name, pattern, sample }) });
}

export function removeLogPattern(projectId: number, patternId: number): Promise<void> {
  return apiFetch(`${base(projectId)}/${patternId}`, { method: "DELETE" });
}
```

- [ ] **Step 2: Write the failing tests** — create `dashboard/src/components/LogValuesCard.test.tsx`:

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { setAccessToken } from "../auth/tokens";
import LogValuesCard from "./LogValuesCard";

const BASE = "/api/v1/projects/42/log-patterns";
const LINK = "https://backoffice.example.com/trips/{value}";
const TRIP = { id: 1, name: "trip_id", pattern: 'tripId="(\\d+)"', link_template: LINK, created_at: "2026-10-14T10:00:00Z" };
const ROUTE = { id: 2, name: "route_key", pattern: 'routeKey="([^"]+)"', link_template: null, created_at: null };
const IDLE = { state: "idle", since: null };
const list = (patterns: object[], scan: object = IDLE) => HttpResponse.json({ patterns, scan });

function renderCard(canEdit: boolean | undefined = true) {
  setAccessToken("acc");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <LogValuesCard projectId={42} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

// userEvent treats { and [ as key descriptors; paste keeps the text literal
async function pasteInto(label: RegExp, text: string) {
  await userEvent.click(screen.getByLabelText(label));
  await userEvent.paste(text);
}

async function fill(name: string, pattern: string, link?: string) {
  await userEvent.type(screen.getByLabelText(/^name/i), name);
  await pasteInto(/^regular expression/i, pattern);
  if (link) await pasteInto(/^link/i, link);
}

test("lists each pattern with its expression and its link", async () => {
  server.use(http.get(BASE, () => list([ROUTE, TRIP])));
  renderCard();
  const row = (await screen.findByText("trip_id")).closest("tr")!;
  expect(within(row).getByText('tripId="(\\d+)"')).toBeInTheDocument();
  expect(within(row).getByText(LINK)).toBeInTheDocument();
  expect(within(screen.getByText("route_key").closest("tr")!).getByText("None")).toBeInTheDocument();
});

test("the ? button explains the rule, and an example fills the expression", async () => {
  server.use(http.get(BASE, () => list([])));
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  const help = screen.getByRole("button", { name: "How values are captured" });
  expect(help).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(help);
  expect(help).toHaveAttribute("aria-expanded", "true");
  const popover = screen.getByRole("group", { name: "How values are captured" });
  expect(popover).toHaveTextContent(/one capture group/i);
  expect(popover).toHaveTextContent(/whole match/i);
  expect(popover).toHaveTextContent(/masked log/i);
  expect(within(popover).getAllByRole("button").map((b) => b.textContent))
    .toEqual(['tripId="(\\d+)"', 'routeKey="([^"]+)"', 'status="([^"]+)"']);
  await userEvent.click(within(popover).getByRole("button", { name: 'routeKey="([^"]+)"' }));
  const input = screen.getByLabelText(/^regular expression/i);
  expect(input).toHaveValue('routeKey="([^"]+)"');
  expect(input).toHaveFocus();
  expect(screen.queryByRole("group", { name: "How values are captured" })).toBeNull();
});

test("Escape closes the help and puts focus back on its button", async () => {
  server.use(http.get(BASE, () => list([])));
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  const help = screen.getByRole("button", { name: "How values are captured" });
  await userEvent.click(help);
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("group", { name: "How values are captured" })).toBeNull();
  expect(help).toHaveFocus();
});

test("preview shows the values found as name: value chips and their count, saving nothing", async () => {
  let previewed: unknown = null;
  let saved = false;
  server.use(
    http.get(BASE, () => list([])),
    http.post(`${BASE}/preview`, async ({ request }) => {
      previewed = await request.json();
      return HttpResponse.json({ masked: "…", values: ["3960562", "3960563"] });
    }),
    http.post(BASE, () => {
      saved = true;
      return HttpResponse.json(TRIP, { status: 201 });
    }),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", 'tripId="(\\d+)"');
  await pasteInto(/^log lines/i, 'INFO tripId="3960562"\nINFO tripId="3960563"');
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));

  const result = await screen.findByRole("status");
  expect(result).toHaveTextContent("2 values found");
  expect(within(result).getAllByRole("listitem").map((c) => c.textContent)).toEqual(["trip_id: 3960562", "trip_id: 3960563"]);
  expect(previewed).toEqual({ name: "trip_id", pattern: 'tripId="(\\d+)"', sample: 'INFO tripId="3960562"\nINFO tripId="3960563"' });
  expect(saved).toBe(false);
});

test("a preview that finds nothing says so", async () => {
  server.use(http.get(BASE, () => list([])), http.post(`${BASE}/preview`, () => HttpResponse.json({ masked: "x", values: [] })));
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", 'tripId="(\\d+)"');
  await pasteInto(/^log lines/i, "nothing here");
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  expect(await screen.findByRole("status")).toHaveTextContent("No values found in these lines.");
});

test("adding sends the name, expression and link, lists the pattern and clears the form", async () => {
  let sent: unknown = null;
  let added = false;
  server.use(
    http.get(BASE, () => list(added ? [TRIP] : [])),
    http.post(BASE, async ({ request }) => {
      sent = await request.json();
      added = true;
      return HttpResponse.json(TRIP, { status: 201 });
    }),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", 'tripId="(\\d+)"', LINK);
  await userEvent.click(screen.getByRole("button", { name: "Add pattern" }));

  expect(await screen.findByText("trip_id")).toBeInTheDocument();
  expect(sent).toEqual({ name: "trip_id", pattern: 'tripId="(\\d+)"', link_template: LINK });
  expect(screen.getByLabelText(/^regular expression/i)).toHaveValue("");
  expect(screen.getByLabelText(/^link/i)).toHaveValue("");
});

test("an empty link is sent as null", async () => {
  let sent: { link_template?: unknown } = {};
  server.use(
    http.get(BASE, () => list([])),
    http.post(BASE, async ({ request }) => {
      sent = (await request.json()) as typeof sent;
      return HttpResponse.json({ ...TRIP, link_template: null }, { status: 201 });
    }),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", 'tripId="(\\d+)"');
  await userEvent.click(screen.getByRole("button", { name: "Add pattern" }));
  await waitFor(() => expect(sent.link_template).toBeNull());
});

test.each([
  ["pattern", 422, /^regular expression/i, "A pattern has at most one capture group", /at most one capture group/],
  ["name", 409, /^name/i, "This project already has a log-value pattern named trip_id", /already has a log-value pattern/],
  ["link_template", 422, /^link/i, "The link must be an https:// address with a host", /must be an https:\/\/ address/],
])("a %s refusal is shown at its field", async (code, status, label, message, expected) => {
  server.use(
    http.get(BASE, () => list([])),
    http.post(BASE, () => HttpResponse.json({ detail: { code, message } }, { status })),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("trip_id", "(a)(b)", "http://backoffice.example.com/{value}");
  await userEvent.click(screen.getByRole("button", { name: "Add pattern" }));

  const field = screen.getByLabelText(label);
  await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
  expect(field).toHaveAccessibleDescription(expected);
  expect(field).toHaveFocus();
  expect(screen.queryByRole("alert")).toBeNull(); // at the field, not in a banner
  expect(screen.getByLabelText(/^regular expression/i)).toHaveValue("(a)(b)");
});

test("a limit reached is a banner", async () => {
  server.use(
    http.get(BASE, () => list([])),
    http.post(BASE, () => HttpResponse.json(
      { detail: { code: "limit", message: "A project has at most 20 log-value patterns" } }, { status: 422 })),
  );
  renderCard();
  await screen.findByText(/no log-value patterns/i);
  await fill("p20", "token20");
  await userEvent.click(screen.getByRole("button", { name: "Add pattern" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("at most 20 log-value patterns");
});

test("while past runs are scanned the card says so", async () => {
  server.use(http.get(BASE, () => list([TRIP], { state: "running", since: "2026-10-14T10:00:00Z" })));
  renderCard();
  expect(await screen.findByText("Scanning past runs…")).toBeInTheDocument();
});

test("removing asks first, then deletes", async () => {
  let removed = false;
  server.use(
    http.get(BASE, () => list(removed ? [] : [TRIP])),
    http.delete(`${BASE}/1`, () => {
      removed = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderCard();
  await screen.findByText("trip_id");
  await userEvent.click(screen.getByRole("button", { name: /remove pattern trip_id/i }));
  expect(removed).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: /^remove$/i }));
  expect(await screen.findByText(/no log-value patterns/i)).toBeInTheDocument();
});

test("viewers read the patterns but cannot change them", async () => {
  server.use(http.get(BASE, () => list([TRIP])));
  renderCard(false);
  const row = (await screen.findByText("trip_id")).closest("tr")!;
  expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/^regular expression/i)).not.toBeInTheDocument();
  expect(screen.getByText(/only owners, admins and members/i)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (from `dashboard/`): `npx vitest run src/components/LogValuesCard.test.tsx`
Expected: FAIL with `Failed to resolve import "./LogValuesCard"`.

- [ ] **Step 4: The card** — create `dashboard/src/components/LogValuesCard.tsx`:

```tsx
import { FormEvent, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/http";
import { addLogPattern, listLogPatterns, previewLogPattern, removeLogPattern } from "../api/logPatterns";
import { plural } from "../lib/words";
import ConfirmButton from "./ConfirmButton";
import ErrorBanner from "./ErrorBanner";

interface Props {
  projectId: number;
  /** Undefined while the role is loading: the list shows, the controls wait. */
  canEdit: boolean | undefined;
}

/** The help's examples (spec §4.1); clicking one fills the expression. */
export const PATTERN_EXAMPLES = ['tripId="(\\d+)"', 'routeKey="([^"]+)"', 'status="([^"]+)"'];
const FIELDS = ["name", "pattern", "link_template"] as const;
type Field = (typeof FIELDS)[number];
/** While past runs are scanned the list is read again this often, so "Scanning past runs…" goes away by itself. */
const SCAN_POLL_MS = 3000;
const HELP_LABEL = "How values are captured";

/** Settings card for log-value patterns (ADR-032), next to Masking and built like it. */
export default function LogValuesCard({ projectId, canEdit }: Props) {
  const qc = useQueryClient();
  const queryKey = ["log-patterns", projectId];
  const [name, setName] = useState("");
  const [pattern, setPattern] = useState("");
  const [link, setLink] = useState("");
  const [sample, setSample] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);
  const id = useId();
  const nameInput = useRef<HTMLInputElement>(null);
  const patternInput = useRef<HTMLInputElement>(null);
  const linkInput = useRef<HTMLInputElement>(null);
  const helpButton = useRef<HTMLButtonElement>(null);

  const patterns = useQuery({
    queryKey,
    queryFn: () => listLogPatterns(projectId),
    refetchInterval: (query) => (query.state.data?.scan.state === "running" ? SCAN_POLL_MS : false),
  });
  const preview = useMutation({
    mutationFn: (input: { name: string; pattern: string; sample: string }) =>
      previewLogPattern(projectId, input.name, input.pattern, input.sample),
  });
  const add = useMutation({
    mutationFn: () => addLogPattern(projectId, { name: name.trim(), pattern, link_template: link.trim() || null }),
    onSuccess: () => {
      setName("");
      setPattern("");
      setLink("");
      setSample("");
      preview.reset();
      return qc.invalidateQueries({ queryKey });
    },
  });
  const remove = useMutation({
    mutationFn: (patternId: number) => removeLogPattern(projectId, patternId),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });

  // A refusal about one field is shown under it; anything else (the limit, a 500) is a banner
  const error = add.error ?? preview.error;
  const errorField: Field | null =
    error instanceof ApiError && FIELDS.includes(error.code as Field) ? (error.code as Field) : null;
  const fieldError = (field: Field) => (errorField === field && error instanceof ApiError ? error.detail : null);
  const describedBy = (field: Field) => `${id}-${field}-hint${errorField === field ? ` ${id}-${field}-error` : ""}`;
  useEffect(() => {
    const target = { name: nameInput, pattern: patternInput, link_template: linkInput }[errorField ?? "name"];
    if (errorField) target.current?.focus();
  }, [error, errorField]);

  function applyExample(example: string) {
    setPattern(example);
    setHelpOpen(false);
    patternInput.current?.focus();
  }
  function closeHelpOnEscape(e: KeyboardEvent) {
    if (e.key !== "Escape" || !helpOpen) return;
    e.preventDefault();
    setHelpOpen(false);
    helpButton.current?.focus();
  }
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    preview.reset();
    add.mutate();
  }

  const rows = patterns.data?.patterns;
  const found = preview.data?.values;
  return (
    <div className="card">
      <h2>Log values</h2>
      <p className="muted">
        Show values your tests log, such as the trip a booking scenario created, on every Last runs bar and on the
        test case page. Each pattern is a regular expression matched against the result's log after masking.
      </p>

      {patterns.error != null && <ErrorBanner error={patterns.error} onRetry={() => patterns.refetch()} />}
      {patterns.isPending && <p className="muted">Loading patterns…</p>}
      {rows?.length === 0 && <p className="muted">This project has no log-value patterns.</p>}
      {rows != null && rows.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Name</th>
              <th>Pattern</th>
              <th>Link</th>
              {canEdit && <th><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td><code>{p.name}</code></td>
                <td className="wrap-anywhere"><code>{p.pattern}</code></td>
                <td className="wrap-anywhere">
                  {p.link_template ? <code>{p.link_template}</code> : <span className="muted">None</span>}
                </td>
                {canEdit && (
                  <td className="row-actions">
                    <ConfirmButton
                      label="Remove"
                      ariaLabel={`Remove pattern ${p.name}`}
                      question={`Remove ${p.name}? Its values disappear from every run.`}
                      confirmLabel="Remove"
                      onConfirm={() => remove.mutate(p.id)}
                      disabled={remove.isPending}
                    />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {patterns.data?.scan.state === "running" && <p className="muted" role="status">Scanning past runs…</p>}
      {remove.error != null && <ErrorBanner error={remove.error} />}

      {canEdit === false && <p className="muted">Only owners, admins and members can add or remove patterns.</p>}
      {canEdit && (
        <form className="form-stack masking-form" onSubmit={onSubmit}>
          <h4>Add a pattern</h4>
          <label>
            Name
            <input
              ref={nameInput}
              required
              maxLength={32}
              autoComplete="off"
              spellCheck={false}
              placeholder="trip_id"
              aria-invalid={errorField === "name" || undefined}
              aria-describedby={describedBy("name")}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <span id={`${id}-name-hint`} className="muted field-hint">
              The label in tooltips. Lowercase letters, digits, underscores.
            </span>
            {fieldError("name") && <span id={`${id}-name-error`} className="field-error">{fieldError("name")}</span>}
          </label>

          <div className="field-with-help" onKeyDown={closeHelpOnEscape}>
            <div className="field-with-help-head">
              <label htmlFor={`${id}-pattern`}>Regular expression</label>
              <button
                ref={helpButton}
                type="button"
                className="help-toggle"
                aria-label={HELP_LABEL}
                aria-expanded={helpOpen}
                aria-controls={`${id}-help`}
                onClick={() => setHelpOpen((open) => !open)}
              >
                ?
              </button>
            </div>
            {helpOpen && (
              <div id={`${id}-help`} className="help-popover" role="group" aria-label={HELP_LABEL}>
                <p>
                  With one capture group <code>( … )</code>, the value is that part. Without a group, the whole match
                  is the value. Values come from the masked log, so a masked value is never captured.
                </p>
                <p>Examples:</p>
                <ul className="help-examples">
                  {PATTERN_EXAMPLES.map((example) => (
                    <li key={example}>
                      <button type="button" className="fchip mono" onClick={() => applyExample(example)}>{example}</button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <input
              id={`${id}-pattern`}
              ref={patternInput}
              required
              maxLength={256}
              autoComplete="off"
              spellCheck={false}
              className="mono"
              placeholder={'tripId="(\\d+)"'}
              aria-invalid={errorField === "pattern" || undefined}
              aria-describedby={describedBy("pattern")}
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
            />
            <span id={`${id}-pattern-hint`} className="muted field-hint">
              RE2 syntax: no backreferences or lookarounds. At most one capture group.
            </span>
            {fieldError("pattern") && (
              <span id={`${id}-pattern-error`} className="field-error">{fieldError("pattern")}</span>
            )}
          </div>

          <label>
            <span>Link <span className="muted">(optional)</span></span>
            <input
              ref={linkInput}
              inputMode="url"
              maxLength={500}
              autoComplete="off"
              spellCheck={false}
              placeholder="https://backoffice.example.com/trips/{value}"
              aria-invalid={errorField === "link_template" || undefined}
              aria-describedby={describedBy("link_template")}
              value={link}
              onChange={(e) => setLink(e.target.value)}
            />
            <span id={`${id}-link_template-hint`} className="muted field-hint">
              Each value becomes a link here, with <code>{"{value}"}</code> replaced by the value. https only.
            </span>
            {fieldError("link_template") && (
              <span id={`${id}-link_template-error`} className="field-error">{fieldError("link_template")}</span>
            )}
          </label>

          <label>
            <span>Log lines <span className="muted">(optional, never saved)</span></span>
            <textarea
              rows={3}
              spellCheck={false}
              placeholder={'INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"'}
              value={sample}
              onChange={(e) => setSample(e.target.value)}
            />
          </label>
          {found != null && (
            <div role="status" className="preview-result">
              <span className="muted">
                {found.length === 0 ? "No values found in these lines." : `${plural(found.length, "value", "values")} found:`}
              </span>
              {found.length > 0 && (
                <ul className="chip-list" aria-label="Values found">
                  {found.map((value) => (
                    <li key={value} className="chip"><code>{preview.variables?.name}: {value}</code></li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {error != null && errorField == null && <ErrorBanner error={error} />}
          <div className="button-row">
            <button
              type="button"
              onClick={() => preview.mutate({ name: name.trim(), pattern, sample })}
              disabled={preview.isPending || !name.trim() || !pattern || !sample}
            >
              {preview.isPending ? "Previewing…" : "Preview"}
            </button>
            <button type="submit" disabled={add.isPending}>
              {add.isPending ? "Adding…" : "Add pattern"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
```

CSS — in `dashboard/src/index.css`, after `.masking-form h4 { … }`, add:

```css
/* Log values card (ADR-032): the "?" beside the expression's label opens the rule and examples inline */
.field-with-help { display: flex; flex-direction: column; gap: var(--space-1); }
.field-with-help-head { display: flex; align-items: center; gap: var(--space-2); }
.help-toggle { min-width: 24px; min-height: 24px; padding: 0; border-radius: 999px; font-weight: 600; line-height: 1; }
.help-popover { border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-1); padding: var(--space-3); font-size: 13px; max-width: 560px; }
.help-popover p { margin: 0 0 var(--space-2); }
.help-examples { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
```

- [ ] **Step 5: Wire it in.** In `dashboard/src/pages/ProjectSettingsPage.tsx`, add `import LogValuesCard from "../components/LogValuesCard";` next to the `MaskingCard` import and, right after `<MaskingCard projectId={id} canEdit={project.data == null ? undefined : canEdit} />`, add:

```tsx
      <LogValuesCard projectId={id} canEdit={project.data == null ? undefined : canEdit} />
```

In `dashboard/src/test/server.ts`, after the masking-free defaults (for example after the `latest-keys` handler), add:

```ts
  // Settings' Log values card (ADR-032): no patterns, no scan; tests about it override
  http.get("/api/v1/projects/:projectId/log-patterns", () =>
    HttpResponse.json({ patterns: [], scan: { state: "idle", since: null } })),
```

In `dashboard/src/pages/ProjectSettingsPage.test.tsx`, append:

```tsx
test("the Log values card follows Masking", async () => {
  renderPage();
  await screen.findByRole("heading", { level: 2, name: "Log values" });
  const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
  expect(headings.indexOf("Log values")).toBe(headings.indexOf("Masking") + 1);
});
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run src/components/LogValuesCard.test.tsx src/components/MaskingCard.test.tsx src/pages/ProjectSettingsPage.test.tsx` then `npm run lint` and `npm run typecheck`.
Expected: PASS; lint and typecheck clean.

- [ ] **Step 7: Docs.** In `DESIGN.md`, add after the `### Run Strip` section (before `### Run from QEOS`):

```markdown
### Log Values
Values a test logged (ADR-032), defined per project in Settings → **Log values**, the card after Masking and built like it: a `table.data` of Name, Pattern and Link ("None" in Muted text when unset) with a Remove `ConfirmButton` per row ("Its values disappear from every run."), and an add form (`form-stack masking-form`): Name; Regular expression with a 24px round **?** toggle (`help-toggle`, `aria-expanded`) that opens an inline help box (`help-popover`, a group named "How values are captured": one group is that part, no group the whole match, values come from the masked log; three example `fchip` buttons fill the field and return focus to it; Escape closes the box and returns focus to **?**); an optional Link (placeholder `https://backoffice.example.com/trips/{value}`); optional log lines with **Preview**, which lists what it found as `name: value` `chip`s with a count ("2 values found:", or "No values found in these lines."). A server refusal is shown under its own field (`field-error`, `aria-invalid`, part of the field's description, focus moved there); a limit or any other error is an `ErrorBanner`. While past runs are scanned, "Scanning past runs…" (a polite status) sits under the list, which is read again every 3 s until the scan ends. Viewers see the list only.
```

In `docs/SETUP.md` §4.10, after the **What it does.** paragraph, add:

```markdown
**Setup:** Settings → **Log values** → **Add a pattern**: a name (the label in tooltips, e.g. `trip_id`), a regular
expression (RE2; with one capture group the value is that part, e.g. `tripId="(\d+)"`; without one, the whole match)
and, optionally, a link (`https://backoffice.example.com/trips/{value}`: each value becomes a link there). The **?**
button explains the rule and offers examples. Paste a few log lines and choose **Preview** to see the values found.
Owners, admins and members can do this; at most 20 patterns per project. Adding a pattern scans the runs of the last
90 days ("Scanning past runs…"); older runs get no values for it. A value hidden by masking is never captured.
```

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/api/logPatterns.ts dashboard/src/components/LogValuesCard.tsx dashboard/src/components/LogValuesCard.test.tsx dashboard/src/pages/ProjectSettingsPage.tsx dashboard/src/pages/ProjectSettingsPage.test.tsx dashboard/src/test/server.ts dashboard/src/index.css DESIGN.md docs/SETUP.md
git commit -o dashboard/src/api/logPatterns.ts dashboard/src/components/LogValuesCard.tsx dashboard/src/components/LogValuesCard.test.tsx dashboard/src/pages/ProjectSettingsPage.tsx dashboard/src/pages/ProjectSettingsPage.test.tsx dashboard/src/test/server.ts dashboard/src/index.css DESIGN.md docs/SETUP.md -m "feat(dashboard): Log values settings card with help, preview and the re-scan state" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: Values in the Last runs tooltips (cases and feature rows)

**Files:**
- Modify: `dashboard/src/api/analytics.ts` (`LogValueGroup`, `StripEntry.values`, `LatestResult.values`)
- Create: `dashboard/src/lib/logValues.ts`, `dashboard/src/lib/logValues.test.ts`
- Modify: `dashboard/src/components/RunStrip.tsx`, `dashboard/src/components/RunStrip.test.tsx`
- Modify: `dashboard/src/lib/featureQueries.ts` (`mergeStrips`), `dashboard/src/lib/featureQueries.test.ts`
- Modify: `DESIGN.md` (`### Run Strip`)

**Interfaces:**
- Consumes (HTTP, Task 8): `run-strip` entries' `values: [{name, values}]`; `latest-results` entries' `values: [{name, values, link_template}]`.
- Produces (in `api/analytics.ts`): `export interface LogValueGroup { name: string; values: string[] }`; `StripEntry.values?: LogValueGroup[]` (absent from an older server); `LatestResult.values?: (LogValueGroup & { link_template: string | null })[]`.
- Produces (in `lib/logValues.ts`): `TOOLTIP_VALUES_MAX = 5`; `valueLines(groups: LogValueGroup[] | undefined): string[]`; `mergeValues(lists: (LogValueGroup[] | undefined)[]): LogValueGroup[]`. (Task 14 adds `linkFor` to the same file.)

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill before editing UI** (project rule). Read `DESIGN.md` §Run Strip.

- [ ] **Step 1: Write the failing tests.** Create `dashboard/src/lib/logValues.test.ts`:

```ts
import { mergeValues, valueLines } from "./logValues";

test("valueLines: one line per pattern with values, comma-separated, five at most then +N more", () => {
  expect(valueLines([
    { name: "route_key", values: ["wasToBos"] },
    { name: "empty", values: [] },
    { name: "trip_id", values: ["1", "2", "3", "4", "5", "6", "7"] },
  ])).toEqual(["route_key: wasToBos", "trip_id: 1, 2, 3, 4, 5 +2 more"]);
  expect(valueLines([{ name: "trip_id", values: ["1", "2", "3", "4", "5"] }])).toEqual(["trip_id: 1, 2, 3, 4, 5"]);
  expect(valueLines(undefined)).toEqual([]);
});

test("mergeValues: per pattern in name order, values in first-seen order, duplicates removed", () => {
  expect(mergeValues([
    [{ name: "trip_id", values: ["2", "1"] }],
    undefined,
    [{ name: "route_key", values: ["r"] }, { name: "trip_id", values: ["1", "3"] }],
  ])).toEqual([{ name: "route_key", values: ["r"] }, { name: "trip_id", values: ["2", "1", "3"] }]);
  expect(mergeValues([])).toEqual([]);
});
```

Append to `dashboard/src/components/RunStrip.test.tsx`:

```tsx
const VALUES = [
  { name: "route_key", values: ["wasToBos"] },
  { name: "trip_id", values: ["3960562", "3960563"] },
  { name: "nothing", values: [] },
];

test("each bar's tooltip and name add one line per pattern with values, whatever the status", () => {
  const statuses: StripStatus[] = ["passed", "failed", "skipped", "rerun"];
  const withValues: StripEntry[] = entries(statuses).map((e) => ({ ...e, values: VALUES }));
  render(<MemoryRouter><RunStrip projectId={5} entries={withValues} /></MemoryRouter>);
  const links = screen.getAllByRole("link");
  links.forEach((link, i) => {
    const label = link.getAttribute("aria-label")!;
    const [first, ...rest] = label.split("\n");
    expect(first).toMatch(new RegExp(`^Run #${433 + i}, .+: ${["passed", "failed", "skipped", "re-run"][i]}$`));
    expect(rest).toEqual(["route_key: wasToBos", "trip_id: 3960562, 3960563"]);
    expect(link.getAttribute("title")).toBe(label);
    expect(link).toHaveAttribute("href", `/projects/5/runs/${433 + i}`); // still a link to its run
  });
  expect(screen.getByRole("group", { name: "Last 4 runs: 1 passed, 1 failed, 1 re-run, 1 skipped" })).toBeInTheDocument();
});

test("more than five values in a tooltip end with +N more", () => {
  const [entry] = entries(["passed"]);
  render(<MemoryRouter><RunStrip projectId={5} entries={[{ ...entry, values: [{ name: "trip_id", values: ["1", "2", "3", "4", "5", "6", "7"] }] }]} /></MemoryRouter>);
  expect(screen.getByRole("link").getAttribute("title")!.split("\n")[1]).toBe("trip_id: 1, 2, 3, 4, 5 +2 more");
});

test("a bar without values (or from an older server) keeps its one-line tooltip", () => {
  render(<MemoryRouter><RunStrip projectId={5} entries={entries(["passed"]).map((e) => ({ ...e, values: [] }))} /></MemoryRouter>);
  expect(screen.getByRole("link").getAttribute("title")).not.toContain("\n");
});
```

Append to `dashboard/src/lib/featureQueries.test.ts`:

```ts
test("mergeStrips joins a run's values over its scenarios, per pattern, duplicates removed", () => {
  const a = { ...at(1, "passed"), values: [{ name: "trip_id", values: ["1"] }] };
  const b = { ...at(1, "failed"), values: [{ name: "trip_id", values: ["1", "2"] }, { name: "route_key", values: ["r"] }] };
  const c = at(2, "passed"); // an older server: no values
  const merged = mergeStrips([[a, c], [b]]);
  expect(merged[0].status).toBe("failed");
  expect(merged[0].values).toEqual([{ name: "route_key", values: ["r"] }, { name: "trip_id", values: ["1", "2"] }]);
  expect(merged[1].values).toEqual([]);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/lib/logValues.test.ts src/components/RunStrip.test.tsx src/lib/featureQueries.test.ts`
Expected: FAIL (`Failed to resolve import "./logValues"`; the tooltip has one line; `merged[0].values` undefined).

- [ ] **Step 3: Types.** In `dashboard/src/api/analytics.ts`, replace the `StripEntry` line with:

```ts
/** One pattern's values in a result or a run (log values, ADR-032): patterns in name order, values in log order. */
export interface LogValueGroup { name: string; values: string[] }
/** One result in a test's strip: the run it was in, the test's status there and its log values (absent from an older
 *  server). */
export interface StripEntry {
  run_id: number; started_at: string; branch: string | null; status: StripStatus; values?: LogValueGroup[];
}
```
and in `LatestResult`, after `failed_step?: …;`, add:

```ts
  /** Log values of this result, each pattern with its link template (ADR-032); absent from an older server. */
  values?: (LogValueGroup & { link_template: string | null })[];
```

- [ ] **Step 4: The helpers** — create `dashboard/src/lib/logValues.ts`:

```ts
import type { LogValueGroup } from "../api/analytics";

/** The most values a tooltip line shows per pattern before "+N more" (spec §4.2). */
export const TOOLTIP_VALUES_MAX = 5;

/** One tooltip line per pattern with values: "trip_id: 3960562, 3960563"; the sixth and later as "+N more". */
export function valueLines(groups: LogValueGroup[] | undefined): string[] {
  return (groups ?? [])
    .filter((g) => g.values.length > 0)
    .map((g) => {
      const more = g.values.length - TOOLTIP_VALUES_MAX;
      return `${g.name}: ${g.values.slice(0, TOOLTIP_VALUES_MAX).join(", ")}${more > 0 ? ` +${more} more` : ""}`;
    });
}

/** Several results' values as one (a feature row's run): per pattern in name order, values in first-seen order,
 *  duplicates removed. */
export function mergeValues(lists: (LogValueGroup[] | undefined)[]): LogValueGroup[] {
  const byName = new Map<string, string[]>();
  for (const list of lists) {
    for (const group of list ?? []) {
      const values = byName.get(group.name) ?? [];
      for (const value of group.values) if (!values.includes(value)) values.push(value);
      byName.set(group.name, values);
    }
  }
  return [...byName.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, values]) => ({ name, values }));
}
```

- [ ] **Step 5: The strip.** In `dashboard/src/components/RunStrip.tsx`, add `import { valueLines } from "../lib/logValues";` and replace the `const label = …` line with:

```tsx
        // Today's line, then one line per pattern with values in that run (ADR-032): the same text for the tooltip
        // and the link's name, whatever the status
        const label = [`Run #${e.run_id}, ${dateFormat.format(new Date(e.started_at))}: ${WORD[e.status]}`,
          ...valueLines(e.values)].join("\n");
```

In `dashboard/src/lib/featureQueries.ts`, add `import { mergeValues } from "./logValues";` and replace `mergeStrips` with:

```ts
export function mergeStrips(perTest: StripEntry[][], limit = 10): StripEntry[] {
  const byRun = new Map<number, StripEntry>();
  const valuesByRun = new Map<number, StripEntry["values"][]>();
  for (const entry of perTest.flat()) {
    valuesByRun.set(entry.run_id, [...(valuesByRun.get(entry.run_id) ?? []), entry.values]);
    const seen = byRun.get(entry.run_id);
    if (!seen || WORST.indexOf(entry.status) < WORST.indexOf(seen.status)) byRun.set(entry.run_id, entry);
  }
  // A feature's bar lists the log values of every scenario in that run, per pattern, without duplicates
  const runs = [...byRun.values()]
    .map((entry) => ({ ...entry, values: mergeValues(valuesByRun.get(entry.run_id) ?? []) }))
    .sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at) || a.run_id - b.run_id);
  return runs.slice(-limit);
}
```
and extend its doc comment's first sentence with `, and their log values merged per pattern`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run src/lib/logValues.test.ts src/components/RunStrip.test.tsx src/lib/featureQueries.test.ts src/pages/FeaturesView.test.tsx src/pages/TestManagement.test.tsx` then `npm run lint` and `npm run typecheck`.
Expected: PASS; lint and typecheck clean.

- [ ] **Step 7: Docs.** In `DESIGN.md` §Run Strip, after the **Links:** bullet, add:

```markdown
- **Log values:** each link's name and tooltip add one line per pattern with values in that run, whatever its status (`trip_id: 3960562, 3960563`; patterns by name, at most five values, then `+2 more`). Text only, no links; the bar stays a link. A feature row's bar merges its scenarios' values per pattern, duplicates removed.
```

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/api/analytics.ts dashboard/src/lib/logValues.ts dashboard/src/lib/logValues.test.ts dashboard/src/components/RunStrip.tsx dashboard/src/components/RunStrip.test.tsx dashboard/src/lib/featureQueries.ts dashboard/src/lib/featureQueries.test.ts DESIGN.md
git commit -o dashboard/src/api/analytics.ts dashboard/src/lib/logValues.ts dashboard/src/lib/logValues.test.ts dashboard/src/components/RunStrip.tsx dashboard/src/components/RunStrip.test.tsx dashboard/src/lib/featureQueries.ts dashboard/src/lib/featureQueries.test.ts DESIGN.md -m "feat(dashboard): log values in every Last runs bar's tooltip, merged per run on feature rows" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 14: "Log values" line on the test case page and the feature page's cards; delivery-3 docs and gate

**Files:**
- Modify: `dashboard/src/lib/logValues.ts` (`linkFor`), `dashboard/src/lib/logValues.test.ts`
- Create: `dashboard/src/components/LogValuesLine.tsx`, `dashboard/src/components/LogValuesLine.test.tsx`
- Modify: `dashboard/src/pages/CaseEditorPage.tsx` (both `LastResultPill` places, lines ~312 and ~322), `dashboard/src/pages/CaseLastResult.test.tsx`
- Modify: `dashboard/src/pages/FeaturePage.tsx` (after the `scenario-card-head` div), `dashboard/src/pages/FeaturePage.test.tsx`
- Modify: `dashboard/src/index.css`, `DESIGN.md` (`### Log Values`), `PRODUCT.md`, `README.md`

**Interfaces:**
- Consumes: `LatestResult.values` (Task 13).
- Produces (in `lib/logValues.ts`): `linkFor(template: string | null | undefined, value: string): string | null`. (in `components/LogValuesLine.tsx`): default export `LogValuesLine({ values, label = "Log values" }: { values: (LogValueGroup & { link_template?: string | null })[] | undefined; label?: string })`.

- [ ] **Step 0: Invoke the `ui-ux-pro-max` skill before editing UI** (project rule). Read `DESIGN.md` §Status Dot and Badges, §Feature Page and §Secret Block (the copy pattern).

- [ ] **Step 1: Write the failing tests.** Append to `dashboard/src/lib/logValues.test.ts` (and add `linkFor` to its import):

```ts
const T = "https://backoffice.example.com/trips/{value}";

test("linkFor keeps every value inside the template", () => {
  expect(linkFor(T, "3960562")).toBe("https://backoffice.example.com/trips/3960562");
  expect(linkFor(T, "../admin")).toBe("https://backoffice.example.com/trips/..%2Fadmin");
  expect(linkFor(T, "@evil.example")).toBe("https://backoffice.example.com/trips/%40evil.example");
  expect(linkFor(T, "a#b")).toBe("https://backoffice.example.com/trips/a%23b");
  expect(linkFor(T, "x?y=1")).toBe("https://backoffice.example.com/trips/x%3Fy%3D1");
  expect(linkFor(T, "a b")).toBe("https://backoffice.example.com/trips/a%20b");
  expect(linkFor("https://backoffice.example.com/search?trip={value}&tab=1", "a&b"))
    .toBe("https://backoffice.example.com/search?trip=a%26b&tab=1");
  // A whole path segment of dots would move up the path: no link (the chip still copies)
  expect(linkFor(T, "..")).toBeNull();
  expect(linkFor(T, ".")).toBeNull();
});

test("a template that is not https gives no link", () => {
  for (const template of [null, undefined, "", "http://backoffice.example.com/{value}", "javascript:alert(1)//{value}",
    "data:text/html,{value}", "https://{value}.example.com/", "https://backoffice.example.com{value}",
    "https://backoffice.example.com/{value}/{value}", "https://backoffice.example.com/trips",
    "https://user@backoffice.example.com/{value}", "not a url {value}"]) {
    expect(linkFor(template, "1")).toBeNull();
  }
});
```

Create `dashboard/src/components/LogValuesLine.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LogValuesLine from "./LogValuesLine";

const PLAIN = [
  { name: "route_key", values: ["wasToBos"], link_template: null },
  { name: "trip_id", values: ["3960562", "3960563"], link_template: null },
];

function setClipboard(writeText: (t: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

test("names each pattern with its values, in a group called Log values", () => {
  render(<LogValuesLine values={PLAIN} />);
  const group = screen.getByRole("group", { name: "Log values" });
  expect(group).toHaveTextContent(/^Log values/);
  expect(group).toHaveTextContent(/route_key:\s*wasToBos/);
  expect(group).toHaveTextContent(/trip_id:\s*3960562,\s*3960563/);
  expect(within(group).queryByRole("link")).toBeNull();
});

test("nothing at all without values", () => {
  const { container } = render(<LogValuesLine values={[{ name: "trip_id", values: [], link_template: null }]} />);
  expect(container).toBeEmptyDOMElement();
  const { container: none } = render(<LogValuesLine values={undefined} />);
  expect(none).toBeEmptyDOMElement();
});

test("with an https template a value is a new-tab link with the value encoded", () => {
  render(<LogValuesLine values={[{ name: "route_key", values: ["a/b c"], link_template: "https://backoffice.example.com/routes/{value}" }]} />);
  const link = screen.getByRole("link", { name: /a\/b c/ });
  expect(link).toHaveAttribute("href", "https://backoffice.example.com/routes/a%2Fb%20c");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
  expect(link).toHaveAccessibleName("a/b c (opens in a new tab)");
});

test("a template that is not https, as an old row or a tampered answer might hold, gives no link", () => {
  render(<LogValuesLine values={[{ name: "trip_id", values: ["1"], link_template: "javascript:alert(1)//{value}" }]} />);
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.getByText("1")).toBeInTheDocument();
});

test("Copy writes the value and says Copied, announced politely", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  setClipboard(writeText);
  render(<LogValuesLine values={PLAIN} label="Log values of TC-12" />);
  const group = screen.getByRole("group", { name: "Log values of TC-12" });
  const status = within(group).getByRole("status");
  expect(status).toHaveAttribute("aria-live", "polite");
  expect(status).toHaveTextContent("");
  await userEvent.click(within(group).getByRole("button", { name: "Copy trip_id 3960563" }));
  expect(writeText).toHaveBeenCalledWith("3960563");
  expect(await within(group).findByText("Copied")).toBeInTheDocument();
});

test("a blocked clipboard says so instead of claiming success", async () => {
  setClipboard(vi.fn().mockRejectedValue(new Error("denied")));
  render(<LogValuesLine values={PLAIN} />);
  await userEvent.click(screen.getByRole("button", { name: "Copy route_key wasToBos" }));
  expect(await screen.findByText(/could not copy/i)).toBeInTheDocument();
  expect(screen.queryByText("Copied")).toBeNull();
});
```

In `dashboard/src/pages/CaseLastResult.test.tsx`, change the first imports to `import { act, render, screen, waitFor, within } from "@testing-library/react";` plus `import userEvent from "@testing-library/user-event";`, and append:

```tsx
test("the log values show under the pill, each copyable, linked by its template", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  setup(kase(), result({ status: "passed", values: [
    { name: "route_key", values: ["wasToBos"], link_template: null },
    { name: "trip_id", values: ["3960562"], link_template: "https://backoffice.example.com/trips/{value}" },
  ] }));
  renderCase();
  const line = await screen.findByRole("group", { name: "Log values" });
  expect(line).toHaveTextContent(/route_key:\s*wasToBos/);
  expect(within(line).getByRole("link", { name: /3960562/ })).toHaveAttribute("href", "https://backoffice.example.com/trips/3960562");
  await userEvent.click(within(line).getByRole("button", { name: "Copy route_key wasToBos" }));
  expect(writeText).toHaveBeenCalledWith("wasToBos");
  expect(await within(line).findByText("Copied")).toBeInTheDocument();
});

test("no log values, no line", async () => {
  setup(kase(), result({ status: "passed", values: [] }));
  renderCase();
  await screen.findByText(/passed/i, { selector: ".badge *, .badge" });
  expect(screen.queryByRole("group", { name: "Log values" })).toBeNull();
});
```

In `dashboard/src/pages/FeaturePage.test.tsx`, append:

```tsx
test("a scenario card shows its log values under its pill", async () => {
  server.use(http.post(`${P}/analytics/latest-results`, () => HttpResponse.json({ results: {
    [KEY]: result("passed", { values: [{ name: "trip_id", values: ["3960562", "3960563"], link_template: null }] }),
  } })));
  renderAt();
  const cards = await screen.findAllByRole("article");
  const line = await within(cards[0]).findByRole("group", { name: "Log values of TC-12" });
  expect(line).toHaveTextContent(/trip_id:\s*3960562,\s*3960563/);
  expect(within(cards[1]).queryByRole("group", { name: /Log values/ })).toBeNull();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/lib/logValues.test.ts src/components/LogValuesLine.test.tsx src/pages/CaseLastResult.test.tsx src/pages/FeaturePage.test.tsx`
Expected: FAIL (`linkFor` is not exported; `./LogValuesLine` does not resolve; no "Log values" group on the pages).

- [ ] **Step 3: `linkFor`** — append to `dashboard/src/lib/logValues.ts`:

```ts
const PLACEHOLDER = "{value}";

/** The link for a value from its pattern's template, or null. Checked again here, whatever the server stored: only
 *  an https template with a host, no credentials and {value} once after the host. The value is URL-encoded, so it
 *  cannot change the host or the path's structure; "." and ".." (a path segment that would move up) get no link. */
export function linkFor(template: string | null | undefined, value: string): string | null {
  if (!template || template.split(PLACEHOLDER).length !== 2 || value === "." || value === "..") return null;
  // {value} must come after the host: "https://" + host, then a "/", "?" or "#", before it
  if (!/^https:\/\/[^/?#]+[/?#]/i.test(template.slice(0, template.indexOf(PLACEHOLDER)))) return null;
  let base: URL;
  let built: URL;
  try {
    base = new URL(template.replace(PLACEHOLDER, "x"));
    built = new URL(template.replace(PLACEHOLDER, encodeURIComponent(value)));
  } catch {
    return null;
  }
  if (base.protocol !== "https:" || !base.hostname || base.username || base.password) return null;
  return built.origin === base.origin ? built.href : null;
}
```

- [ ] **Step 4: The line** — create `dashboard/src/components/LogValuesLine.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { Copy } from "lucide-react";
import type { LogValueGroup } from "../api/analytics";
import { linkFor } from "../lib/logValues";

type Group = LogValueGroup & { link_template?: string | null };

/** How long "Copied" stays. */
const NOTE_MS = 2000;

/** The "Log values" line under a last-result pill (ADR-032): per pattern its values, comma-separated, patterns
 *  separated by "·". Each value copies itself; with an https link template it is also a link (new tab). Nothing when
 *  the result has no values. */
export default function LogValuesLine({ values, label = "Log values" }: { values: Group[] | undefined; label?: string }) {
  const [note, setNote] = useState("");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const groups = (values ?? []).filter((g) => g.values.length > 0);
  if (groups.length === 0) return null;

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setNote("Copied");
    } catch {
      setNote("Could not copy. Select the value and copy it by hand.");
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNote(""), NOTE_MS);
  }

  return (
    <div className="log-values" role="group" aria-label={label}>
      <span className="log-values-label">Log values</span>
      {groups.map((g, gi) => (
        <span key={g.name} className="log-values-group">
          {gi > 0 && <span className="log-values-sep" aria-hidden="true">·</span>}
          <span className="log-values-name">{g.name}:</span>
          {g.values.map((v, vi) => {
            const href = linkFor(g.link_template, v);
            return (
              <span key={v} className="log-values-item">
                <span className="log-value">
                  {href ? (
                    <a className="log-value-text" href={href} target="_blank" rel="noopener noreferrer">
                      {v}<span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  ) : (
                    <code className="log-value-text">{v}</code>
                  )}
                  <button type="button" className="log-value-copy" aria-label={`Copy ${g.name} ${v}`} title="Copy"
                    onClick={() => copy(v)}>
                    <Copy size={14} aria-hidden="true" />
                  </button>
                </span>
                {vi < g.values.length - 1 && <span aria-hidden="true">,</span>}
              </span>
            );
          })}
        </span>
      ))}
      <span className="log-values-note" role="status" aria-live="polite">{note}</span>
    </div>
  );
}
```

CSS — in `dashboard/src/index.css`, after the `.scenario-card-status { … }` rule, add:

```css
/* Log values under a last-result pill (ADR-032): label, then per pattern its values as copyable 24px chips */
.log-values { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; margin: var(--space-2) 0 var(--space-3); font-size: 13px; }
.scenario-card > .log-values { margin: 0; padding: 0 var(--space-4) var(--space-3); }
.log-values-label { font-weight: 600; color: var(--text-secondary); }
.log-values-group, .log-values-item { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.log-values-name, .log-values-sep { color: var(--text-secondary); }
.log-value { display: inline-flex; align-items: center; min-height: 24px; padding: 0 2px 0 8px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface-1); }
.log-value-text { font-family: var(--font-mono); font-size: 12.5px; overflow-wrap: anywhere; }
.log-value-copy { display: inline-flex; align-items: center; justify-content: center; min-width: 24px; min-height: 24px; padding: 0; border: 0; border-radius: 999px; background: transparent; color: var(--text-secondary); }
.log-value-copy:hover { background: var(--hover-strong); color: var(--text-primary); }
.log-values-note { color: var(--text-secondary); font-size: 12.5px; }
```

- [ ] **Step 5: The pages.** In `dashboard/src/pages/CaseEditorPage.tsx`, add `import LogValuesLine from "../components/LogValuesLine";` after the `LastResultPill` import, and after **each** of the two lines that render `<LastResultPill result={latest.data} />` add:

```tsx
              {key != null && latest.data != null && <LogValuesLine values={latest.data.values} />}
```
(keep each at the same indentation as its pill line).

In `dashboard/src/pages/FeaturePage.tsx`, add `import LogValuesLine from "../components/LogValuesLine";` after the `LastResultPill` import, and right after the closing `</div>` of `<div className="scenario-card-head">` add:

```tsx
            {result != null && <LogValuesLine values={result.values} label={`Log values of ${c.key}`} />}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run src/lib/logValues.test.ts src/components/LogValuesLine.test.tsx src/pages/CaseLastResult.test.tsx src/pages/FeaturePage.test.tsx src/pages/CaseAsOfRun.test.tsx`
Expected: PASS.

- [ ] **Step 7: Docs.** In `DESIGN.md` `### Log Values`, append the paragraph:

```markdown
Under the last-result pill on the test case page, and under each scenario card's head on the Feature page, a "Log values" line (a `group` named "Log values", or "Log values of TC-12" on a card): the label in 600 weight, then per pattern `name:` and its values as 24px pill chips (`log-value`, mono text) separated by commas, patterns separated by "·". Each chip has a 24px copy button ("Copy trip_id 3960562", lucide Copy icon) that writes the value to the clipboard and says "Copied" for 2 s in a polite live region (or that it could not copy); with the pattern's link template the value is also a link (new tab, `rel="noopener noreferrer"`, "(opens in a new tab)" for screen readers), built only from an https template with the value URL-encoded. It follows the result shown: the latest, or the run a Last runs bar opened. No values, no line.
```

In `PRODUCT.md` `## Capabilities and Constraints`, add after the Collection bullet:

```markdown
- Log values (ADR-032): per-project regular expressions (Settings › Log values, up to 20) pick values such as a trip
  id out of each result's masked log; every Last runs bar's tooltip, the test case page and the feature page's cards
  show them, copyable and optionally linked to an https page. Logs are stored masked and cut to 64 KB; adding a
  pattern re-scans the runs of the last 90 days. Needs collector 0.9.0 and a test repository that attaches its log
  lines to the scenario.
```

In `README.md`, after the **Failed steps across test cases:** bullet, add:

```markdown
- **Log values:** a project's patterns (Settings → Log values) pick values your tests log, such as the trip a booking scenario created, out of each result's masked log. Every Last runs bar's tooltip lists them per pattern, and the test case page and the feature page's cards show them as chips you can copy or open (with a per-pattern https link). Needs collector 0.9.0 and a test repository that attaches its log lines to the scenario.
```

- [ ] **Step 8: Delivery-3 gate.** From `dashboard/`: `npm run lint`, `npm run typecheck`, `npm run build`, then `npx vitest run --no-file-parallelism`. Expected: all clean and green (re-run a file alone if it shows the known 15 s timeout under load).

- [ ] **Step 9: Commit**

```bash
git add dashboard/src/lib/logValues.ts dashboard/src/lib/logValues.test.ts dashboard/src/components/LogValuesLine.tsx dashboard/src/components/LogValuesLine.test.tsx dashboard/src/pages/CaseEditorPage.tsx dashboard/src/pages/CaseLastResult.test.tsx dashboard/src/pages/FeaturePage.tsx dashboard/src/pages/FeaturePage.test.tsx dashboard/src/index.css DESIGN.md PRODUCT.md README.md
git commit -o dashboard/src/lib/logValues.ts dashboard/src/lib/logValues.test.ts dashboard/src/components/LogValuesLine.tsx dashboard/src/components/LogValuesLine.test.tsx dashboard/src/pages/CaseEditorPage.tsx dashboard/src/pages/CaseLastResult.test.tsx dashboard/src/pages/FeaturePage.tsx dashboard/src/pages/FeaturePage.test.tsx dashboard/src/index.css DESIGN.md PRODUCT.md README.md -m "feat(dashboard): copyable, linked log values under the last-result pill on case and feature pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Delivery 4 — test repository (Atriis.Test.Automation.OBT)

### Task 15: The logger attaches each printed line to the running scenario

This task works in `C:/dev/github/Atriis.Test.Automation.OBT`, on its own rules (`.github/CLAUDE.md`,
`.github/instructions/commit-guidelines.md`): a branch, a Conventional Commit with a subject of at most 80 characters,
no push (the user pushes the branch and opens the PR). Node 24, cucumber-js 12.

**Files:**
- Modify: `src/utils/logger.js`
- Create: `src/utils/logger.check.js` (a `node:test` file; not `*.test.js`/`*.spec.js`, which Playwright's default `testMatch` would pick up through `npm test`)
- Modify: `tests/support/hooks.js` (after `setDefaultTimeout(120000);`)

**Interfaces:**
- Produces (on the logger singleton and every `child()`): `attachToScenario(attach: (text: string) => void): void`, `detachFromScenario(): void`; one module-level attach function shared by all logger instances. Each line `_log` prints is also passed to it in the pretty one-line form without colour codes: `INFO  8:23:24 PM [App] Trip id captured from booking flow tripId="3960562"`.
- Consumed by: collector 0.9.0 (Task 9) reads these `text/x.cucumber.log+plain` attachments from `test-results/cucumber-report.json`.

- [ ] **Step 0: Check the repository and branch.** Run:

```bash
cd /c/dev/github/Atriis.Test.Automation.OBT
git status --short
git branch --show-current
```
Expected: branch `main`, only untracked paths that are not yours (`.agents/`, `.claude-flow/`, `.codex/`, `docs/DbQueries-CI-Setup.md`, …): leave them alone. If `src/utils/logger.js` or `tests/support/hooks.js` shows as modified, stop and ask. Then `git switch -c feat/logger-scenario-attach`.

- [ ] **Step 1: Write the failing check** — create `src/utils/logger.check.js`:

```js
/**
 * Checks the scenario attachment in logger.js (QEOS log values): `node --test src/utils/logger.check.js`.
 * Not named *.test.js or *.spec.js: Playwright's default testMatch would pick those up.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const logger = require('./logger');

function printed(fn) {
  const lines = [];
  const original = console.log;
  console.log = (line) => lines.push(line);
  try {
    fn();
  } finally {
    console.log = original;
  }
  return lines;
}

function app() {
  const child = logger.child('App');
  child.level = 'info'; // whatever LOG_LEVEL the shell has
  return child;
}

test.afterEach(() => logger.detachFromScenario());

test('outside a scenario a line is only printed', () => {
  const lines = printed(() => app().info('Trip id captured from booking flow', { tripId: '3960562' }));
  assert.equal(lines.length, 1);
});

test('inside a scenario each printed line is attached too, in the pretty form without colours', () => {
  const attached = [];
  logger.attachToScenario((text) => attached.push(text));
  const lines = printed(() => app().info('Trip id captured from booking flow', { tripId: '3960562' }));
  assert.equal(lines.length, 1); // the console output is unchanged
  assert.match(lines[0], /\x1b\[/); // and keeps its colours
  assert.equal(attached.length, 1);
  assert.match(attached[0], /^INFO {2}.+ \[App\] Trip id captured from booking flow tripId="3960562"$/);
  assert.doesNotMatch(attached[0], /\x1b\[/);
});

test('a line below the log level is neither printed nor attached', () => {
  const attached = [];
  logger.attachToScenario((text) => attached.push(text));
  const lines = printed(() => app().debug('Clicking element', { selector: '#submit' }));
  assert.deepEqual([lines, attached], [[], []]);
});

test('after the scenario nothing more is attached', () => {
  const attached = [];
  logger.attachToScenario((text) => attached.push(text));
  logger.detachFromScenario();
  printed(() => app().warn('Between scenarios'));
  assert.deepEqual(attached, []);
});

test('a failing attach never breaks logging', () => {
  logger.attachToScenario(() => {
    throw new Error('the scenario already finished');
  });
  const lines = printed(() => assert.doesNotThrow(() => app().error('Still printed')));
  assert.equal(lines.length, 1);
});

test('with LOG_FORMAT=json the console gets JSON and the scenario the pretty line', () => {
  const previous = process.env.LOG_FORMAT;
  process.env.LOG_FORMAT = 'json';
  try {
    const json = app();
    const attached = [];
    logger.attachToScenario((text) => attached.push(text));
    const lines = printed(() => json.info('Route chosen', { routeKey: 'wasToBos' }));
    assert.equal(JSON.parse(lines[0]).routeKey, 'wasToBos');
    assert.match(attached[0], /^INFO {2}.+ \[App\] Route chosen routeKey="wasToBos"$/);
  } finally {
    if (previous === undefined) delete process.env.LOG_FORMAT;
    else process.env.LOG_FORMAT = previous;
  }
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node --test src/utils/logger.check.js`
Expected: FAIL with `TypeError: logger.detachFromScenario is not a function`.

- [ ] **Step 3: The logger.** In `src/utils/logger.js`:
  - in the header comment, after the `LOG_FORMAT` line, add ` *   Inside a Cucumber scenario every printed line is also attached to it (see attachToScenario).`;
  - after the `COLORS` object, add:

```js
// The running Cucumber scenario's attach function, shared by the logger and every child logger. tests/support/hooks.js
// sets it in a Before hook and clears it in an After hook. Each printed line is also attached to the scenario, so it
// reaches test-results/cucumber-report.json and QEOS can show values from it (e.g. the trip id). Outside a scenario
// (start-up, hooks outside one) lines are only printed.
let scenarioAttach = null;
```
  - in the class, after `error(…)`, add:

```js
  /**
   * Attach every printed line to the running scenario, e.g. `logger.attachToScenario((text) => world.log(text))`.
   * @param {(text: string) => void} attach
   */
  attachToScenario(attach) {
    scenarioAttach = typeof attach === 'function' ? attach : null;
  }

  /**
   * Stop attaching: the scenario ended.
   */
  detachFromScenario() {
    scenarioAttach = null;
  }
```
  - in `_log`, after the `if (this.format === 'json') { … } else { … }` block, add `    this._attach(level, entry);`;
  - replace `_prettyPrint` with:

```js
  /**
   * Pretty print for human readability (local development)
   * @private
   */
  _prettyPrint(level, entry) {
    console.log(this._line(level, entry, COLORS[level], COLORS.reset));
  }

  /**
   * The pretty one-line form; without colours unless given
   * @private
   */
  _line(level, entry, color = '', reset = '') {
    const time = new Date(entry.timestamp).toLocaleTimeString();
    const component = entry.component ? `[${entry.component}]` : '';

    let output = `${color}${level.toUpperCase().padEnd(5)}${reset} ${time} ${component} ${entry.message}`;

    // Add context if present
    const contextKeys = Object.keys(entry).filter(k =>
      !['timestamp', 'level', 'component', 'message'].includes(k)
    );

    if (contextKeys.length > 0) {
      const contextStr = contextKeys
        .map(k => `${k}=${JSON.stringify(entry[k])}`)
        .join(' ');
      output += ` ${contextStr}`;
    }
    return output;
  }

  /**
   * Attach the line to the running scenario, if any, in the pretty form without colours
   * @private
   */
  _attach(level, entry) {
    if (!scenarioAttach) {
      return;
    }
    try {
      scenarioAttach(this._line(level, entry));
    } catch {
      // An attach that fails (the scenario already finished) never fails the test
    }
  }
```

- [ ] **Step 4: The hooks.** In `tests/support/hooks.js`, right after `setDefaultTimeout(120000);`, add:

```js
/**
 * Every logger line printed during a scenario is also attached to it (this.log), so the Cucumber JSON report carries
 * the scenario's log and QEOS can show values from it, such as the trip id. Registered before the other hooks: this
 * Before runs first, and this After runs last (cucumber-js runs After hooks in reverse order of definition).
 */
Before(function () {
  const world = this;
  logger.attachToScenario((text) => world.log(text));
});

After(function () {
  logger.detachFromScenario();
});
```

- [ ] **Step 5: Run the check and the linter**

Run: `node --test src/utils/logger.check.js` — Expected: 6 passing, 0 failing.
Run: `npx eslint src/utils/logger.js src/utils/logger.check.js tests/support/hooks.js` — Expected: no errors.
Run: `npx cucumber-js --dry-run tests/features/smoke/` — Expected: the support files load (no "instance of Cucumber that isn't running" error); dry run does not execute hooks.

- [ ] **Step 6 (when the environment allows): one real scenario.** If the local `.env` and browser are set up, run one short scenario (`npx cucumber-js tests/features/smoke/ --name "<a smoke scenario name>"`), then:

```bash
node -e "const r=require('./test-results/cucumber-report.json');const n=r.flatMap(f=>f.elements).flatMap(e=>e.steps||[]).flatMap(s=>s.embeddings||[]).filter(x=>x.mime_type==='text/x.cucumber.log+plain').length;console.log(n)"
```
Expected: a number greater than 0. If the environment is not set up, skip this step and say so in the task report.

- [ ] **Step 7: Commit** (in the test repository; do not push)

```bash
git add src/utils/logger.js src/utils/logger.check.js tests/support/hooks.js
git commit -o src/utils/logger.js src/utils/logger.check.js tests/support/hooks.js -m "feat(utils): attach logger lines to the running scenario" -m "A Before hook hands the scenario's this.log to the logger and an After hook takes it back; every line the logger prints is also attached, in the pretty one-line form without colours, so test-results/cucumber-report.json carries each scenario's log and QEOS (collector 0.9.0) can show values from it, such as the trip id. Console output is unchanged; outside a scenario lines are only printed." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage (self-review)

| Spec | Task |
|---|---|
| §2.1 test repository: Before stores the attach, After clears it, `_log` attaches the pretty line without colours, console unchanged, nothing outside a scenario | 15 |
| §2.2 collector `log`: Cucumber text attachments (both media types, base64), step order, Background, binary skipped, 64 KB, absent when empty; JUnit `system-out`; other formats none | 9 |
| §2.2 retry without `log` on a 422 naming it; release 0.9.0, floating tag | 10 (retry, version), controller note, 11 (pins) |
| §2.3 `ResultIn.log`, truncated never rejected, masked like message/details, `test_results.log`, patterns applied to the masked log | 2, 4 |
| §2.3 remask re-masks `log` and re-applies patterns; export includes; retention deletes | 7 |
| §3.1 `log_patterns` table, name format, 256 chars, RE2, ≤ 1 group, ≤ 20, link template rules, no edit | 1, 3, 4, 6 |
| §3.2 GET/POST/DELETE/preview, roles, 201/204/409/422, gateway route, architecture check | 6 |
| §3.3 `log_values`: distinct, position, 200 chars, ≤ 20, cascades, index, values from the masked log | 1, 3, 4 |
| §3.4 re-scan: 90 days, batches, idempotent, one job per project, join the same pass, `scan` state, uploads during a scan | 5, 6 |
| Migration 023 incl. the scan state on an existing per-project table (`collection_settings`) | 1 |
| §4.1 Settings card: list, delete with confirm, add form, "?" popover with three examples, Preview chips and count, errors at the field, "Scanning past runs…", viewers read-only, Link field | 12 |
| §4.2 tooltip lines, accessible label, +N more, every status, feature-row merge; run-strip `values` | 8, 13 |
| §4.3 latest-results `values` with `link_template`; case page and scenario card line; copy with "Copied"; https-only, encoded, new tab | 8, 14 |
| §5 gateway smoke (401 and a full flow) | 6, 8 |
| §6 ADR-032, SETUP, SECURITY, PRODUCT, TODO, TECHNICAL_SPECIFICATION, DESIGN, collector and ingestion READMEs | 1, 2, 6, 7, 8, 9, 10, 12, 13, 14 |

Decisions this plan takes where the spec is silent or the code differs (to report to the user):
- The scan state lives on `collection_settings` (the existing per-project table the spec allows), as two counters plus a start time: a request bumps `log_scan_requested`, a finished pass sets `log_scan_done` to the number it started from; running while requested > done. No clock comparisons, and concurrent requests are all counted.
- The re-scan runs inside ingestion-service as a background task after the `POST` (like failure notifications), not as a loop container like retention; a per-project PostgreSQL advisory lock gives "one job per project", and a start-up hook resumes a scan a restart cut short. Each pass replaces values for all current patterns (idempotent), so the new pattern and those added mid-scan are covered; "within 90 days" is by `test_runs.created_at`, as retention measures age.
- `GET …/log-patterns` returns an object `{patterns, scan}` (the spec names the `scan` field but not the envelope). Patterns are listed in name order (masking lists by id).
- Field errors are `{"detail": {"code", "message"}}` (`code` = `name`, `pattern`, `link_template` or `limit`), so the dashboard shows them at the field; the existing `ApiError.code` already parses that shape.
- A value whose span touches a masking marker is skipped ("a value hidden by masking cannot be captured"); blank values are skipped; a pattern stops reading a log after 1,000 matches (added: bounds the upload path).
- `test_results.log` is a deferred column and never part of the run-detail payload; `redacted` and `truncated` keep describing what the run page shows (masking in the log counts in the redactions metric only).
- The tooltip keeps today's first line (`Run #812, 14 Oct, 10:02: passed`, no year), the format the spec calls "today's line"; `+N more` follows the fifth value after a space (`trip_id: 1, 2, 3, 4, 5 +2 more`).
- The dashboard gives no link for the values `.` and `..` (a whole path segment of dots would move up the path even when encoded); the chip still copies.
- The collector also reads `attachments`/`media_type`/`mediaType`/`body` and cucumber-jvm's scenario `before`/`after` hook lists; base64 is detected by a strict decode (text with spaces is kept as it is); a 422 that names both the failed-step details and `log` strips both in its one retry.
