"""alembic/env.py must take the database URL from the service settings, so migrations run
wherever the service runs -- the root docker-compose stack runs them in a one-shot container
whose only source of truth is DATABASE_URL. Offline mode renders the SQL without connecting,
so these tests need no database. (The migrations use now() defaults, which SQLite rejects, so
an online SQLite run is not an option here.)"""
from pathlib import Path

from alembic import command
from alembic.config import Config

from src.auth.config import settings

SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _config() -> Config:
    # No ini file on purpose: env.py only calls logging.config.fileConfig when the Config has a
    # file, and fileConfig disables every logger that already exists in this process -- which
    # silently breaks caplog-based tests (test_email_sender) that run afterwards.
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    return cfg


def test_alembic_ini_does_not_hardcode_a_database_url():
    assert not Config(str(SERVICE_ROOT / "alembic.ini")).get_main_option("sqlalchemy.url")


def test_env_py_falls_back_to_the_settings_url(monkeypatch, capsys):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://svc:pw@dbhost:5432/auth_db")
    cfg = _config()
    cfg.set_main_option("sqlalchemy.url", "")  # nothing passed explicitly: env.py must use settings

    command.upgrade(cfg, "head", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE TABLE users" in sql
    assert "CREATE TABLE pending_registrations" in sql


def test_migration_008_adds_the_mode_state_and_the_link_allowance(monkeypatch, capsys):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://svc:pw@dbhost:5432/auth_db")
    cfg = _config()
    cfg.set_main_option("sqlalchemy.url", "")

    command.upgrade(cfg, "007:008", sql=True)
    up = capsys.readouterr().out
    assert "CREATE TABLE auth_mode_state" in up
    assert "ADD COLUMN microsoft_link_allowed_until" in up
    assert "INSERT INTO auth_mode_state (id, sso_only) VALUES (1, false)" in up

    command.downgrade(cfg, "008:007", sql=True)
    down = capsys.readouterr().out
    assert "DROP TABLE auth_mode_state" in down
    assert "DROP COLUMN microsoft_link_allowed_until" in down
