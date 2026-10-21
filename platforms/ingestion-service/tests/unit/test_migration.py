"""Runs the real Alembic migration against a throwaway SQLite DB (the rest of the suite uses
create_all), catching model/migration drift and exercising the constraints."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from src.ingestion.db.base import Base
from src.ingestion.models import ApiKey, Run, RunResult  # noqa: F401  registers tables

SERVICE_ROOT = Path(__file__).resolve().parents[2]

KEY = (
    "INSERT INTO api_keys (project_id, organization_id, name, key_prefix, key_hash, created_by)"
    " VALUES (1, 1, 'k', 'qeos_abcdefgh', :hash, 1)"
)
RUN = (
    "INSERT INTO test_runs (project_id, api_key_id, idempotency_key, request_hash, ci_provider,"
    " started_at, finished_at, duration_ms, total, passed, failed, skipped, errored)"
    " VALUES (1, 1, :idem, 'h', :provider, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00',"
    " 1000, 0, 0, 0, 0, 0)"
)


@pytest.fixture
def migrated_engine(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migration_test.db').as_posix()}"
    cfg = Config()  # no ini file: env.py would otherwise reconfigure logging for the whole test run
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_migration_creates_model_tables(migrated_engine):
    tables = set(inspect(migrated_engine).get_table_names())
    assert {"api_keys", "test_runs", "test_results"} <= set(Base.metadata.tables)
    assert set(Base.metadata.tables) <= tables


def test_migration_columns_match_models(migrated_engine):
    inspector = inspect(migrated_engine)
    for table_name, table in Base.metadata.tables.items():
        migrated = {col["name"] for col in inspector.get_columns(table_name)}
        assert {col.name for col in table.columns} == migrated, f"column drift in {table_name}"


def test_key_hash_is_unique(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "a" * 64})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text(KEY), {"hash": "a" * 64})


def test_ci_provider_check(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "b" * 64})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text(RUN), {"idem": None, "provider": "travis"})
    with migrated_engine.begin() as conn:  # added by migration 011
        conn.execute(text(RUN), {"idem": None, "provider": "azure_pipelines"})


def test_idempotency_key_unique_per_project_but_nulls_do_not_collide(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "c" * 64})
        conn.execute(text(RUN), {"idem": None, "provider": "local"})
        conn.execute(text(RUN), {"idem": None, "provider": "local"})  # must not raise
        conn.execute(text(RUN), {"idem": "run-1", "provider": "local"})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text(RUN), {"idem": "run-1", "provider": "local"})


def test_result_status_check(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "d" * 64})
        conn.execute(text(RUN), {"idem": None, "provider": "local"})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO test_results (run_id, test_key, suite, class_name, name, status, duration_ms, truncated)"
                " VALUES (1, :k, '', '', 't', 'error', 0, 0)"
            ), {"k": "e" * 64})


def test_redacted_defaults_to_false(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "f" * 64})
        conn.execute(text(RUN), {"idem": None, "provider": "local"})
        conn.execute(text(
            "INSERT INTO test_results (run_id, test_key, suite, class_name, name, status, duration_ms)"
            " VALUES (1, :k, '', '', 't', 'passed', 0)"
        ), {"k": "f" * 64})
        assert conn.execute(text("SELECT redacted FROM test_results")).scalar() in (False, 0)


def test_analytics_indexes_exist(migrated_engine):
    inspector = inspect(migrated_engine)
    result_indexes = {ix["name"]: ix["column_names"] for ix in inspector.get_indexes("test_results")}
    run_indexes = {ix["name"]: ix["column_names"] for ix in inspector.get_indexes("test_runs")}
    assert result_indexes["ix_test_results_test_key_run"] == ["test_key", "run_id"]
    assert run_indexes["ix_test_runs_project_started"] == ["project_id", "started_at"]


def test_model_indexes_match_the_migration():
    assert "ix_test_results_test_key_run" in {ix.name for ix in Base.metadata.tables["test_results"].indexes}
    assert "ix_test_runs_project_started" in {ix.name for ix in Base.metadata.tables["test_runs"].indexes}


def test_key_prefix_fits_the_qeos_prefix(migrated_engine):
    """Migration 015 widens key_prefix: "qeos_" + 8 is 13 characters, over the old String(12)."""
    columns = {col["name"]: col for col in inspect(migrated_engine).get_columns("api_keys")}
    assert columns["key_prefix"]["type"].length == 16
    assert Base.metadata.tables["api_keys"].c.key_prefix.type.length == 16


def test_key_prefix_downgrade_restores_12(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_test.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "014")
    engine = create_engine(url)
    try:
        columns = {col["name"]: col for col in inspect(engine).get_columns("api_keys")}
        assert columns["key_prefix"]["type"].length == 12
    finally:
        engine.dispose()


def test_failing_results_index_is_partial(migrated_engine):
    """Migration 016: failure causes and regression candidates read only failing rows (spec: Indexes)."""
    columns = {ix["name"]: ix["column_names"] for ix in inspect(migrated_engine).get_indexes("test_results")}
    assert columns["ix_test_results_failing"] == ["run_id", "test_key"]
    with migrated_engine.connect() as conn:
        sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE name = 'ix_test_results_failing'")).scalar()
    assert "WHERE" in sql.upper() and "'failed'" in sql and "'errored'" in sql


def test_model_declares_the_failing_index():
    assert "ix_test_results_failing" in {ix.name for ix in Base.metadata.tables["test_results"].indexes}


def test_failing_index_downgrade_drops_it(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_016.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "015")
    engine = create_engine(url)
    try:
        assert "ix_test_results_failing" not in {ix["name"] for ix in inspect(engine).get_indexes("test_results")}
    finally:
        engine.dispose()


def test_failing_index_postgres_path_is_rerunnable(monkeypatch):
    """Migration 016 on PostgreSQL builds CONCURRENTLY; a re-upgrade after a failed build must not stop on an
    existing (possibly invalid) index, so create is IF NOT EXISTS and drop IF EXISTS."""
    import importlib.util
    from unittest.mock import MagicMock

    spec = importlib.util.spec_from_file_location("m016", SERVICE_ROOT / "alembic" / "versions" / "016_report_indexes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = MagicMock()
    fake.get_bind.return_value.dialect.name = "postgresql"
    monkeypatch.setattr(module, "op", fake)
    module.upgrade()
    assert fake.create_index.call_args.kwargs["postgresql_concurrently"] is True
    assert fake.create_index.call_args.kwargs["if_not_exists"] is True
    module.downgrade()
    assert fake.drop_index.call_args.kwargs["postgresql_concurrently"] is True
    assert fake.drop_index.call_args.kwargs["if_exists"] is True


def test_job_heartbeats_table(migrated_engine):
    """Migration 017 (monitoring spec §3)."""
    inspector = inspect(migrated_engine)
    assert {col["name"] for col in inspector.get_columns("job_heartbeats")} == {
        "job", "last_success_at", "last_error_at", "last_error"}
    assert inspector.get_pk_constraint("job_heartbeats")["constrained_columns"] == ["job"]


def test_job_heartbeats_downgrade_drops_it(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_017.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "016")
    engine = create_engine(url)
    try:
        assert "job_heartbeats" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_test_impact_tables(migrated_engine):
    """Migration 018 (spec 2026-10-12 §3.2, §3.4)."""
    inspector = inspect(migrated_engine)
    assert inspector.get_pk_constraint("impact_pairs")["constrained_columns"] == ["project_id", "unit_hash", "test_key"]
    # No secondary index: the primary key's leading (project_id, unit_hash) serves the unit lookups
    assert inspector.get_indexes("impact_pairs") == []
    base_unique = {uc["name"]: uc["column_names"] for uc in inspector.get_unique_constraints("impact_test_base")}
    assert base_unique["uq_impact_test_base"] == ["project_id", "test_key"]
    assert inspector.get_pk_constraint("run_impact")["constrained_columns"] == ["run_id"]
    (fk,) = inspector.get_foreign_keys("run_impact")
    assert (fk["referred_table"], fk["referred_columns"], fk["options"].get("ondelete")) == ("test_runs", ["id"], "CASCADE")


def test_model_declares_the_impact_pairs_key_and_no_other_index():
    from src.ingestion.models.impact import ImpactPair

    table = ImpactPair.__table__
    assert [col.name for col in table.primary_key.columns] == ["project_id", "unit_hash", "test_key"]
    assert not table.indexes


PAIR = ("INSERT INTO impact_pairs (project_id, unit_hash, path_unit, test_key, changed_runs, new_failures, computed_at)"
        " VALUES (1, :hash, :unit, :test, 3, 2, '2026-10-12T00:00:00+00:00')")


def test_an_impact_pair_is_keyed_by_project_unit_hash_and_test(migrated_engine):
    """No surrogate id: the key is (project_id, md5(path_unit), test_key), so a long path_unit never enters an
    index and the table never runs out of 32-bit ids (plan ruling, supersedes Ruling 27)."""
    from src.ingestion.models.impact import PATH_UNIT_LENGTH, unit_hash

    long_unit = "repo:" + "é" * (PATH_UNIT_LENGTH - 5)  # over 2,704 bytes in UTF-8
    with migrated_engine.begin() as conn:
        conn.execute(text(PAIR), {"hash": unit_hash(long_unit), "unit": long_unit, "test": "a" * 64})
        conn.execute(text(PAIR), {"hash": unit_hash(long_unit), "unit": long_unit, "test": "b" * 64})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text(PAIR), {"hash": unit_hash(long_unit), "unit": long_unit, "test": "a" * 64})


def test_unit_hash_is_the_md5_hex_of_the_utf8_path_unit():
    """Matches PostgreSQL's md5(path_unit) in a UTF-8 database, which the rollup uses."""
    from src.ingestion.models.impact import unit_hash

    assert unit_hash("src/pay/") == "3fa93b389b1e676426c191c185932113"
    assert unit_hash("é") == "66ddcd97cfdeabb2f6fb8a999b4bc76f"  # é as two UTF-8 bytes


def test_a_runs_stored_suggestion_goes_with_the_run(migrated_engine):
    """Retention and legal hold act on test_runs; the suggestion follows its run (spec §3.7)."""
    from sqlalchemy import event

    # SQLite enforces foreign keys only when asked, per connection
    event.listen(migrated_engine, "connect", lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"))
    migrated_engine.dispose()
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "d" * 64})
        conn.execute(text(RUN), {"idem": "impact", "provider": "local"})
        run_id = conn.execute(text("SELECT id FROM test_runs WHERE idempotency_key = 'impact'")).scalar()
        conn.execute(text("INSERT INTO run_impact (run_id, suggested, model_version, replayed, scored_at)"
                          " VALUES (:id, '{}', 'stats-v1', 0, '2026-10-12T00:00:00+00:00')"), {"id": run_id})
        conn.execute(text("DELETE FROM test_runs WHERE id = :id"), {"id": run_id})
        assert conn.execute(text("SELECT COUNT(*) FROM run_impact")).scalar() == 0


def test_test_impact_downgrade_drops_the_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_018.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "017")
    engine = create_engine(url)
    try:
        assert not {"impact_pairs", "impact_test_base", "run_impact"} & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_trigger_check(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "c" * 64})
        conn.execute(text(RUN), {"idem": "t1", "provider": "github_actions"})
        conn.execute(text("UPDATE test_runs SET \"trigger\" = 'manual' WHERE idempotency_key = 't1'"))
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text("UPDATE test_runs SET \"trigger\" = 'cron' WHERE idempotency_key = 't1'"))


def test_collection_settings_defaults(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text("INSERT INTO collection_settings (project_id) VALUES (5)"))
        row = conn.execute(text(
            "SELECT collect_manual, discarded_count, last_discarded_at FROM collection_settings WHERE project_id = 5"
        )).one()
    assert (bool(row[0]), row[1], row[2]) == (True, 0, None)


def test_scope_defaults_to_full_and_is_checked(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "d" * 64})
        conn.execute(text(RUN), {"idem": "s1", "provider": "github_actions"})
        row = conn.execute(text("SELECT scope, stages FROM test_runs WHERE idempotency_key = 's1'")).one()
    assert (row[0], row[1]) == ("full", None)
    with migrated_engine.begin() as conn:
        conn.execute(text("UPDATE test_runs SET scope = 'impact-subset' WHERE idempotency_key = 's1'"))
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text("UPDATE test_runs SET scope = 'partial' WHERE idempotency_key = 's1'"))


def test_api_keys_cannot_read_impact_by_default(migrated_engine):
    """Migration 020: every key, existing or new, is upload-only until an owner or admin allows it (spec §9)."""
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "e" * 64})
        assert conn.execute(text("SELECT can_read_impact FROM api_keys")).scalar() in (False, 0)


def _load_020():
    import importlib.util

    spec = importlib.util.spec_from_file_location("m020", SERVICE_ROOT / "alembic" / "versions" / "020_run_scope.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_models_scope_check_matches_the_migrations():
    """The model builds its check from SCOPES; the migration keeps a frozen copy. They must say the same."""
    (check,) = [c for c in Base.metadata.tables["test_runs"].constraints if c.name == "chk_test_runs_scope"]
    assert str(check.sqltext) == _load_020().SCOPE_IN


def test_run_scope_postgres_path_validates_the_check_in_its_own_transaction(monkeypatch):
    """Ruling (migration lock): on PostgreSQL the check is added NOT VALID, then validated in a separate statement
    inside an autocommit block, so the scan never holds the ACCESS EXCLUSIVE lock of ADD CONSTRAINT."""
    from unittest.mock import MagicMock

    module = _load_020()
    fake = MagicMock()
    fake.get_bind.return_value.dialect.name = "postgresql"
    events = []
    fake.execute.side_effect = lambda sql: events.append(sql)
    block = fake.get_context.return_value.autocommit_block.return_value
    block.__enter__.side_effect = lambda *a: events.append("<autocommit>")
    block.__exit__.side_effect = lambda *a: events.append("</autocommit>")
    monkeypatch.setattr(module, "op", fake)
    module.upgrade()
    add = next(i for i, sql in enumerate(events) if "ADD CONSTRAINT chk_test_runs_scope" in sql)
    assert events[add].rstrip().endswith("NOT VALID; END IF; END $$")
    assert "IF NOT EXISTS (SELECT 1 FROM pg_constraint" in events[add]  # re-runnable
    assert events[add + 1:] == ["<autocommit>", "ALTER TABLE test_runs VALIDATE CONSTRAINT chk_test_runs_scope",
                                "</autocommit>"]
    assert all("IF NOT EXISTS" in sql for sql in events[:add])
    assert any("can_read_impact BOOLEAN NOT NULL DEFAULT false" in sql for sql in events[:add])


def test_run_scope_downgrade_drops_the_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_020.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "019")
    engine = create_engine(url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("test_runs")}
        assert not {"scope", "stages"} & columns
        assert "trigger" in columns  # 019 is still there
        assert "can_read_impact" not in {column["name"] for column in inspect(engine).get_columns("api_keys")}
    finally:
        engine.dispose()


def test_rows_from_before_020_become_full_runs_and_upload_only_keys(tmp_path):
    """Existing data at the upgrade: every run is a full run and every key is upload-only (spec 2026-10-13 §9)."""
    url = f"sqlite:///{(tmp_path / 'upgrade_020.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "019")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(KEY), {"hash": "9" * 64})
            conn.execute(text(RUN), {"idem": "before-020", "provider": "local"})
        engine.dispose()
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            assert conn.execute(text("SELECT scope, stages FROM test_runs")).one() == ("full", None)
            assert conn.execute(text("SELECT can_read_impact FROM api_keys")).scalar() in (False, 0)
    finally:
        engine.dispose()


def test_failed_step_line_must_be_positive(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(KEY), {"hash": "d" * 64})
        conn.execute(text(RUN), {"idem": "fs", "provider": "github_actions"})
        run_id = conn.execute(text("SELECT id FROM test_runs WHERE idempotency_key = 'fs'")).scalar()
        conn.execute(text(
            "INSERT INTO test_results (run_id, test_key, suite, class_name, name, status, duration_ms, truncated,"
            " failed_step_text, failed_step_line) "
            "VALUES (:r, :k, '', '', 'n', 'failed', 1, 0, 'When x', 3)"), {"r": run_id, "k": "e" * 64})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text("UPDATE test_results SET failed_step_line = 0"))


def test_failed_step_downgrade_drops_the_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_021.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "020")
    engine = create_engine(url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("test_results")}
        assert not {"failed_step_text", "failed_step_line"} & columns
        assert "owner" in columns
        assert "scope" in {column["name"] for column in inspect(engine).get_columns("test_runs")}  # 020 is still there
    finally:
        engine.dispose()


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
    assert {"ix_log_values_result_id", "ix_log_values_pattern_id", "ix_log_values_value"} <= {
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


def test_screenshot_tables_and_setting(tmp_path):
    url = f"sqlite:///{(tmp_path / 'screenshots_025.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        insp = inspect(engine)
        assert {"blobs", "result_screenshots"} <= set(insp.get_table_names())
        assert "keep_screenshots" in {c["name"] for c in insp.get_columns("collection_settings")}
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO collection_settings (project_id) VALUES (6)"))
            assert conn.execute(text("SELECT keep_screenshots FROM collection_settings")).scalar() in (False, 0)
            conn.execute(text("INSERT INTO blobs (project_id, sha256, media_type, bytes) VALUES (1, :h, 'image/png', 3)"),
                         {"h": "a" * 64})
        with pytest.raises(IntegrityError):  # one blob per (project, sha256)
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO blobs (project_id, sha256, media_type, bytes) VALUES (1, :h, 'image/png', 3)"),
                             {"h": "a" * 64})
        command.downgrade(cfg, "024")
        insp = inspect(engine)
        assert not {"blobs", "result_screenshots"} & set(insp.get_table_names())
        assert "keep_screenshots" not in {c["name"] for c in insp.get_columns("collection_settings")}
    finally:
        engine.dispose()


def test_blobs_created_at_becomes_not_null_and_old_rows_are_backfilled(tmp_path):
    url = f"sqlite:///{(tmp_path / 'blobs_026.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "025")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:  # 025 allowed a blob without a time
            conn.execute(text("INSERT INTO blobs (project_id, sha256, media_type, bytes, created_at)"
                              " VALUES (1, :h, 'image/png', 3, NULL)"), {"h": "a" * 64})
        command.upgrade(cfg, "026")
        created = {c["name"]: c for c in inspect(engine).get_columns("blobs")}["created_at"]
        assert not created["nullable"]
        with engine.begin() as conn:
            assert conn.execute(text("SELECT created_at FROM blobs")).scalar() is not None  # backfilled
            conn.execute(text("INSERT INTO blobs (project_id, sha256, media_type, bytes) VALUES (1, :h, 'image/png', 3)"),
                         {"h": "b" * 64})  # the server default fills it
            assert conn.execute(text("SELECT COUNT(*) FROM blobs WHERE created_at IS NULL")).scalar() == 0
        command.downgrade(cfg, "025")
        assert {c["name"]: c for c in inspect(engine).get_columns("blobs")}["created_at"]["nullable"]
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def test_traces_migration_adds_kind_artifacts_and_settings(tmp_path):
    url = f"sqlite:///{(tmp_path / 'traces_027.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "026")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:  # a screenshot blob from before 027
            conn.execute(text("INSERT INTO blobs (project_id, sha256, media_type, bytes) VALUES (1, :h, 'image/png', 3)"),
                         {"h": "a" * 64})
            conn.execute(text("INSERT INTO collection_settings (project_id) VALUES (6)"))
        command.upgrade(cfg, "027")
        insp = inspect(engine)
        assert "result_artifacts" in insp.get_table_names()
        assert {"keep_traces", "trace_days"} <= {c["name"] for c in insp.get_columns("collection_settings")}
        with engine.begin() as conn:
            assert conn.execute(text("SELECT kind FROM blobs")).scalar() == "screenshot"
            row = conn.execute(text("SELECT keep_traces, trace_days FROM collection_settings")).one()
            assert row[0] in (False, 0) and row[1] == 14
            conn.execute(text("INSERT INTO blobs (project_id, sha256, media_type, bytes, kind)"
                              " VALUES (1, :h, 'application/zip', 3, 'trace')"), {"h": "b" * 64})
        with pytest.raises(IntegrityError):  # kind is screenshot or trace
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO blobs (project_id, sha256, media_type, bytes, kind)"
                                  " VALUES (1, :h, 'video/mp4', 3, 'video')"), {"h": "c" * 64})
        with pytest.raises(IntegrityError):  # trace_days is 1..90
            with engine.begin() as conn:
                conn.execute(text("UPDATE collection_settings SET trace_days = 91"))
        command.downgrade(cfg, "026")
        insp = inspect(engine)
        assert "result_artifacts" not in insp.get_table_names()
        assert "kind" not in {c["name"] for c in insp.get_columns("blobs")}
        assert "keep_traces" not in {c["name"] for c in insp.get_columns("collection_settings")}
    finally:
        engine.dispose()


def test_result_artifacts_kind_check_and_indexes(migrated_engine):
    insp = inspect(migrated_engine)
    names = {ix["name"] for ix in insp.get_indexes("result_artifacts")}
    assert {"ix_result_artifacts_result_position", "ix_result_artifacts_blob_id"} <= names
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(text("INSERT INTO result_artifacts (result_id, position, blob_id, kind) VALUES (1, 0, 1, 'video')"))
