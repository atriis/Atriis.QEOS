"""SSO-only mode (ADR-031): the settings, the start-up check and the break-glass warning."""
import logging

import pytest

from src.auth.api.main import _apply_auth_mode
from src.auth.config import Settings, settings
from src.auth.service.auth_mode import (
    AuthModeConfigError,
    available_providers,
    check_sso_only_settings,
    configured_providers,
    sso_only_providers,
    warn_if_no_break_glass,
)

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
