"""Runs the real Alembic migration against a throwaway SQLite DB (the rest of the suite uses
create_all), catching model/migration drift and exercising the constraints."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import src.casebook.models  # noqa: F401  registers tables
from src.casebook.db.base import Base

SERVICE_ROOT = Path(__file__).resolve().parents[2]

CASE = ("INSERT INTO cases (project_id, number, title, steps, created_by, priority, status)"
        " VALUES (:project, :number, 't', '[]', 1, :priority, :status)")


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


def test_migration_creates_every_model_table(migrated_engine):
    assert set(Base.metadata.tables) <= set(inspect(migrated_engine).get_table_names())


def test_migration_columns_match_models(migrated_engine):
    inspector = inspect(migrated_engine)
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in inspector.get_columns(name)} == {c.name for c in table.columns}, name


def test_numbers_are_unique_per_project(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(CASE), {"project": 1, "number": 1, "priority": "low", "status": "draft"})
        conn.execute(text(CASE), {"project": 2, "number": 1, "priority": "low", "status": "draft"})
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text(CASE), {"project": 1, "number": 1, "priority": "low", "status": "draft"})


@pytest.mark.parametrize("priority, status", [("urgent", "draft"), ("low", "deleted")])
def test_priority_and_status_are_constrained(migrated_engine, priority, status):
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text(CASE), {"project": 1, "number": 1, "priority": priority, "status": status})


SOURCED = ("INSERT INTO cases (project_id, number, title, steps, created_by, source_key)"
           " VALUES (:project, :number, 't', '[]', 1, :key)")


def test_source_keys_are_unique_per_project_and_manual_cases_are_free(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(SOURCED), {"project": 1, "number": 1, "key": "k" * 64})
        conn.execute(text(SOURCED), {"project": 2, "number": 1, "key": "k" * 64})
        conn.execute(text(SOURCED), {"project": 1, "number": 2, "key": None})
        conn.execute(text(SOURCED), {"project": 1, "number": 3, "key": None})
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text(SOURCED), {"project": 1, "number": 4, "key": "k" * 64})


def test_downgrade_to_001_drops_the_source_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'down.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "001")
    engine = create_engine(url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("cases")}
    finally:
        engine.dispose()
    assert not columns & {"source_path", "source_key", "gherkin"}


def test_downgrade_to_002_drops_feature_name(tmp_path):
    url = f"sqlite:///{(tmp_path / 'down3.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "002")
    engine = create_engine(url)
    try:
        assert "feature_name" not in {c["name"] for c in inspect(engine).get_columns("cases")}
    finally:
        engine.dispose()


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


FILE = ("INSERT INTO feature_files (project_id, path, feature_name, content, content_sha256, imported_at)"
        " VALUES (:project, :path, 'F', 'x', :sha, '2026-10-08 10:00:00')")


def test_feature_files_are_unique_per_project_and_path(migrated_engine):
    sha = "a" * 64
    with migrated_engine.begin() as conn:
        conn.execute(text(FILE), {"project": 1, "path": "a.feature", "sha": sha})
        conn.execute(text(FILE), {"project": 2, "path": "a.feature", "sha": sha})
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text(FILE), {"project": 1, "path": "a.feature", "sha": sha})


def test_downgrade_to_005_drops_feature_files_and_upgrades_again(tmp_path):
    url = f"sqlite:///{(tmp_path / 'down6.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "005")
    engine = create_engine(url)
    try:
        assert "feature_files" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.upgrade(cfg, "head")


def test_migration_007_adds_a_nullable_scenario_line_and_downgrades(tmp_path):
    url = f"sqlite:///{(tmp_path / 'down7.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        column = next(c for c in inspect(engine).get_columns("cases") if c["name"] == "scenario_line")
        assert column["nullable"] is True
    finally:
        engine.dispose()
    command.downgrade(cfg, "006")
    engine = create_engine(url)
    try:
        assert "scenario_line" not in {c["name"] for c in inspect(engine).get_columns("cases")}
        assert "feature_files" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.upgrade(cfg, "head")


def test_migration_008_adds_nullable_run_estimates_and_downgrades(tmp_path):
    url = f"sqlite:///{(tmp_path / 'down8.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        columns = {c["name"]: c for c in inspect(engine).get_columns("run_requests")}
        assert columns["estimate_ms"]["nullable"] is True and columns["estimate_upper_ms"]["nullable"] is True
        with engine.begin() as conn:
            conn.execute(text(RUN), {"project": 1, "status": "completed"})
            assert conn.execute(text("SELECT estimate_ms, estimate_upper_ms FROM run_requests")).one() == (None, None)
    finally:
        engine.dispose()
    command.downgrade(cfg, "007")
    engine = create_engine(url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("run_requests")}
        assert not columns & {"estimate_ms", "estimate_upper_ms"}
        assert "scenario_line" in {c["name"] for c in inspect(engine).get_columns("cases")}
    finally:
        engine.dispose()
    command.upgrade(cfg, "head")


SUITE = "INSERT INTO suites (project_id, name, created_by) VALUES (:project, :name, 1)"
LEG = ("INSERT INTO suites (project_id, name, created_by, origin, workflow, external_id)"
       " VALUES (:project, :name, 1, :origin, :workflow, :external_id)")


def test_migration_009_repository_suite_columns_and_constraints(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(SUITE), {"project": 1, "name": "Smoke"})
        assert conn.execute(text("SELECT origin FROM suites")).scalar_one() == "manual"
        leg = {"project": 1, "origin": "repository", "workflow": "w.yml", "external_id": "a"}
        conn.execute(text(LEG), {**leg, "name": "A"})
        conn.execute(text(LEG), {**leg, "name": "B", "workflow": "x.yml"})
        conn.execute(text(LEG), {**leg, "name": "C", "project": 2})
        # the same leg id is free for manual suites
        conn.execute(text(LEG), {**leg, "name": "D", "origin": "manual"})
        conn.execute(text(LEG), {**leg, "name": "E", "origin": "manual"})
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text(LEG), {**leg, "name": "F"})
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text(LEG), {**leg, "name": "G", "origin": "other"})


def test_migration_009_backfills_run_workflow_and_downgrades(tmp_path):
    url = f"sqlite:///{(tmp_path / 'down9.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "008")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO ci_targets (project_id, provider, repo, workflow, ref, token_encrypted, token_last4,"
                " updated_by, updated_at) VALUES (1, 'github', 'o/r', 'qa.yml', 'main', 'x', 'abcd', 1,"
                " '2026-10-08 10:00:00')"))
            conn.execute(text(RUN), {"project": 1, "status": "completed"})
            conn.execute(text(RUN), {"project": 2, "status": "completed"})
            conn.execute(text(SUITE), {"project": 1, "name": "Old"})
    finally:
        engine.dispose()
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("SELECT project_id, workflow FROM run_requests ORDER BY project_id")).all()
            assert rows == [(1, "qa.yml"), (2, None)]
            assert conn.execute(text("SELECT origin FROM suites")).scalar_one() == "manual"
            conn.execute(text(RUN), {"project": 1, "status": "running"})
        with pytest.raises(IntegrityError), engine.begin() as conn:  # the one-active index survives
            conn.execute(text(RUN), {"project": 1, "status": "queued"})
    finally:
        engine.dispose()
    command.downgrade(cfg, "008")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "workflow" not in {c["name"] for c in inspector.get_columns("run_requests")}
        assert "origin" not in {c["name"] for c in inspector.get_columns("suites")}
    finally:
        engine.dispose()
    command.upgrade(cfg, "head")
