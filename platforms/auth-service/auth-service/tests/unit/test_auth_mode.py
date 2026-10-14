"""SSO-only mode (ADR-031): the settings, the start-up check and the break-glass warning."""
import logging

import pytest
from sqlalchemy.dialects import postgresql

from src.auth.api.main import _apply_auth_mode
from src.auth.config import Settings, settings
from src.auth.models.auth_mode import AuthModeState
from src.auth.service.auth_mode import (
    AuthModeConfigError,
    available_providers,
    check_sso_only_settings,
    configured_providers,
    sso_only_providers,
    warn_if_no_break_glass,
    apply_auth_mode,
    _state_select,
)
from src.auth.service.auth_service import AuthService

TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"
LOGGER = "src.auth.service.auth_mode"


@pytest.fixture
def nothing_configured(monkeypatch):
    for name in ("AZURE_CLIENT_ID", "AZURE_ALLOWED_TENANTS", "AZURE_TENANT_ID", "GOOGLE_CLIENT_ID"):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)


def test_the_mode_is_off_by_default_and_lists_microsoft():
    assert Settings.model_fields["AUTH_SSO_ONLY"].default is False
    assert Settings.model_fields["AUTH_SSO_PROVIDERS"].default == "microsoft"


def test_with_the_mode_off_nothing_is_checked(nothing_configured, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    check_sso_only_settings()


@pytest.mark.parametrize("present, named, not_named", [
    ({}, ["AZURE_CLIENT_ID", "AZURE_ALLOWED_TENANTS"], []),
    ({"AZURE_CLIENT_ID": CLIENT_ID}, ["AZURE_ALLOWED_TENANTS"], ["set AZURE_CLIENT_ID"]),
    ({"AZURE_ALLOWED_TENANTS": TENANT}, ["AZURE_CLIENT_ID"], ["AZURE_ALLOWED_TENANTS"]),
])
def test_start_up_refuses_microsoft_naming_what_is_missing(
    nothing_configured, monkeypatch, caplog, present, named, not_named
):
    for name, value in present.items():
        monkeypatch.setattr(settings, name, value)
    with caplog.at_level(logging.ERROR, logger=LOGGER), pytest.raises(AuthModeConfigError) as raised:
        check_sso_only_settings()
    for text in (str(raised.value), caplog.text):
        for name in named:
            assert name in text
        for name in not_named:
            assert name not in text
        # The setting is named, its value never written
        assert CLIENT_ID not in text and TENANT not in text


def test_azure_tenant_id_counts_as_an_allowed_tenant(nothing_configured, monkeypatch):
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_TENANT_ID", TENANT)
    check_sso_only_settings()


def test_google_listed_but_not_configured_stops_start_up(nothing_configured, monkeypatch):
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", TENANT)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft,google")
    with pytest.raises(AuthModeConfigError, match="GOOGLE_CLIENT_ID"):
        check_sso_only_settings()


@pytest.mark.parametrize("listed", ["github", "microsoft,okta", "", " , "])
def test_an_unknown_or_empty_provider_list_stops_start_up(nothing_configured, monkeypatch, listed):
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", TENANT)
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", listed)
    with pytest.raises(AuthModeConfigError, match="AUTH_SSO_PROVIDERS"):
        check_sso_only_settings()


def test_provider_names_are_trimmed_case_insensitive_and_deduplicated(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", " Microsoft , GOOGLE,microsoft ")
    assert sso_only_providers() == ["microsoft", "google"]


def test_available_providers_follow_the_mode(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "AZURE_ALLOWED_TENANTS", TENANT)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setattr(settings, "AUTH_SSO_PROVIDERS", "microsoft")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    assert configured_providers() == ["microsoft", "google"]
    assert available_providers() == ["microsoft", "google"]
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    assert available_providers() == ["microsoft"]


def test_the_start_up_hook_refuses_before_touching_the_database(nothing_configured):
    with pytest.raises(AuthModeConfigError):
        _apply_auth_mode()


def test_no_active_superuser_is_a_warning(db, make_user, monkeypatch, caplog):
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    make_user("ann@example.com")
    make_user("gone@example.com", superuser=True, active=False)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        warn_if_no_break_glass(db)
    assert "no active superuser" in caplog.text


def test_an_active_superuser_silences_the_warning(db, make_user, monkeypatch, caplog):
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    make_user("root@example.com", superuser=True)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        warn_if_no_break_glass(db)
    assert "no active superuser" not in caplog.text


def test_no_warning_while_the_mode_is_off(db, monkeypatch, caplog):
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        warn_if_no_break_glass(db)
    assert caplog.text == ""


def _revoked(db, session_row):
    db.refresh(session_row)
    return bool(session_row.is_revoked)


def test_turning_the_mode_on_revokes_every_non_superuser_session(db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    root = make_user("root@example.com", superuser=True)
    ann_a, ann_b = AuthService.create_user_session(db, ann), AuthService.create_user_session(db, ann)
    root_s = AuthService.create_user_session(db, root)
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)

    assert apply_auth_mode(db) == 2
    assert _revoked(db, ann_a) and _revoked(db, ann_b)
    assert not _revoked(db, root_s)
    state = db.get(AuthModeState, 1)
    assert state.sso_only is True and state.applied_at is not None


def test_a_restart_with_the_mode_on_revokes_nothing(db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    apply_auth_mode(db)
    after_switch = AuthService.create_user_session(db, ann)  # e.g. a Microsoft sign-in after the switch

    assert apply_auth_mode(db) == 0
    assert not _revoked(db, after_switch)


def test_off_then_on_again_revokes_again(db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    apply_auth_mode(db)
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    assert apply_auth_mode(db) == 0
    assert db.get(AuthModeState, 1).sso_only is False
    second = AuthService.create_user_session(db, ann)

    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    assert apply_auth_mode(db) == 1
    assert _revoked(db, second)


def test_the_mode_off_records_false_and_revokes_nothing(db, make_user, monkeypatch):
    ann = make_user("ann@example.com")
    kept = AuthService.create_user_session(db, ann)
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", False)
    assert apply_auth_mode(db) == 0
    assert db.get(AuthModeState, 1).sso_only is False
    assert not _revoked(db, kept)


def test_a_null_superuser_flag_is_not_a_superuser(db, make_user, monkeypatch):
    odd = make_user("odd@example.com")
    odd.is_superuser = None
    db.commit()
    session_row = AuthService.create_user_session(db, odd)
    monkeypatch.setattr(settings, "AUTH_SSO_ONLY", True)
    assert apply_auth_mode(db) == 1
    assert _revoked(db, session_row)


def test_the_state_row_is_read_with_a_row_lock():
    # SQLite drops FOR UPDATE, so the lock that keeps two starting processes from revoking twice is
    # pinned on the PostgreSQL rendering of the very query apply_auth_mode runs
    sql = str(_state_select().compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "auth_mode_state" in sql


def test_the_start_up_hook_records_the_mode(client, db):
    # The client fixture started the app: its hook ran against this run's database
    assert db.get(AuthModeState, 1).sso_only is False
