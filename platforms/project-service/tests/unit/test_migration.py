"""Runs the real Alembic migration against a throwaway SQLite DB, so model/migration drift
and the partial unique indexes are exercised (the rest of the suite uses create_all)."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from src.project.db.base import Base
from src.project.models import OverviewLayout, Project, Repository  # noqa: F401  registers tables

SERVICE_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def migrated_engine(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migration_test.db').as_posix()}"
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def _insert_project(conn, name, slug, deleted=False):
    conn.execute(
        text(
            "INSERT INTO projects (organization_id, name, slug, settings, created_by, deleted_at)"
            " VALUES (1, :name, :slug, '{}', 1, :deleted_at)"
        ),
        {"name": name, "slug": slug, "deleted_at": "2026-01-01T00:00:00+00:00" if deleted else None},
    )


def test_migration_creates_model_tables(migrated_engine):
    tables = set(inspect(migrated_engine).get_table_names())
    assert {"projects", "repositories"} <= set(Base.metadata.tables)
    assert set(Base.metadata.tables) <= tables


def test_migration_columns_match_models(migrated_engine):
    inspector = inspect(migrated_engine)
    for table_name, table in Base.metadata.tables.items():
        migrated = {col["name"] for col in inspector.get_columns(table_name)}
        assert {col.name for col in table.columns} == migrated, f"column drift in {table_name}"


def test_migration_creates_partial_unique_indexes(migrated_engine):
    names = {index["name"] for index in inspect(migrated_engine).get_indexes("projects")}
    assert {"uq_project_org_name", "uq_project_org_slug"} <= names


def test_live_duplicate_name_is_rejected(migrated_engine):
    with migrated_engine.begin() as conn:
        _insert_project(conn, "Checkout", "checkout")
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            _insert_project(conn, "Checkout", "checkout-2")


def test_deleted_projects_name_and_slug_can_be_reused(migrated_engine):
    with migrated_engine.begin() as conn:
        _insert_project(conn, "Checkout", "checkout", deleted=True)
        _insert_project(conn, "Checkout", "checkout")  # must not raise


def test_repository_provider_check(migrated_engine):
    with migrated_engine.begin() as conn:
        _insert_project(conn, "P", "p")
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO repositories (project_id, provider, owner, name, full_name_key, url,"
                    " default_branch, default_branch_is_user_set, verification_status)"
                    " VALUES (1, 'bitbucket', 'a', 'b', 'a/b', 'https://bitbucket.org/a/b', 'main', 0, 'unchecked')"
                )
            )
    with migrated_engine.begin() as conn:  # added by migration 003
        conn.execute(
            text(
                "INSERT INTO repositories (project_id, provider, owner, name, full_name_key, url,"
                " default_branch, default_branch_is_user_set, verification_status)"
                " VALUES (1, 'azure_devops', 'a/p', 'r', 'a/p/r', 'https://dev.azure.com/a/p/_git/r', 'main', 0,"
                " 'unchecked')"
            )
        )


def test_repository_unique_per_project_provider_key(migrated_engine):
    insert = text(
        "INSERT INTO repositories (project_id, provider, owner, name, full_name_key, url,"
        " default_branch, default_branch_is_user_set, verification_status)"
        " VALUES (1, 'github', :owner, 'shop', 'acme/shop', 'https://github.com/acme/shop', 'main', 0, 'unchecked')"
    )
    with migrated_engine.begin() as conn:
        _insert_project(conn, "P", "p")
        conn.execute(insert, {"owner": "acme"})
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(insert, {"owner": "Acme"})


EMPTY_LAYOUT = '{"schema": 1, "widgets": []}'


def _insert_layout(conn, user_id, project_id=1):
    conn.execute(
        text(
            "INSERT INTO overview_layouts (project_id, user_id, layout, version, updated_by)"
            " VALUES (:project_id, :user_id, :layout, 1, 1)"
        ),
        {"project_id": project_id, "user_id": user_id, "layout": EMPTY_LAYOUT},
    )


def test_one_project_default_per_project(migrated_engine):
    with migrated_engine.begin() as conn:
        _insert_project(conn, "P", "p")
        _insert_layout(conn, None)
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            _insert_layout(conn, None)


def test_one_personal_layout_per_user_and_project(migrated_engine):
    with migrated_engine.begin() as conn:
        _insert_project(conn, "P", "p")
        _insert_layout(conn, 7)
        _insert_layout(conn, 8)  # another user's: fine
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            _insert_layout(conn, 7)


def test_deleting_a_project_deletes_its_layouts(migrated_engine):
    # SQLite enforces foreign keys only when asked, per connection
    event.listen(migrated_engine, "connect", lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"))
    migrated_engine.dispose()
    with migrated_engine.begin() as conn:
        _insert_project(conn, "P", "p")
        _insert_layout(conn, None)
        _insert_layout(conn, 7)
        conn.execute(text("DELETE FROM projects WHERE slug = 'p'"))
        assert conn.execute(text("SELECT COUNT(*) FROM overview_layouts")).scalar() == 0


def test_downgrading_004_drops_the_table_and_its_indexes(tmp_path):
    url = f"sqlite:///{(tmp_path / 'downgrade_test.db').as_posix()}"
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "003")
    engine = create_engine(url)
    try:
        assert "overview_layouts" not in inspect(engine).get_table_names()
        with engine.connect() as conn:
            leftovers = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '%overview_layouts%'")).all()
        assert leftovers == []
    finally:
        engine.dispose()
