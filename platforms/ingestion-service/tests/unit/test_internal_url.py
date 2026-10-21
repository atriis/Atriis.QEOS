import pytest

from src.ingestion.jobs.retention import RetentionError, parse_internal_url


def test_embedded_credentials_are_unchanged():
    ep = parse_internal_url("http://svc:s3cret@project-service:8000/base/")
    assert ep.url == "http://project-service:8000/base/internal/v1/projects/retention"
    assert ep.username == "svc"
    assert ep.password == "s3cret"
    assert ep.display == "http://svc:***@project-service:8000/base"
    assert ep.base == "http://project-service:8000/base"


def test_embedded_credentials_win_over_the_password_argument():
    ep = parse_internal_url("http://svc:inline@host:8000", password="other", username="someone")
    assert (ep.username, ep.password) == ("svc", "inline")


def test_bare_url_takes_the_default_username_and_given_password():
    ep = parse_internal_url("http://project-service:8000", password="s3cret")
    assert ep.username == "ingestion-service"
    assert ep.password == "s3cret"
    assert ep.url == "http://project-service:8000/internal/v1/projects/retention"
    assert ep.base == "http://project-service:8000"
    assert ep.display == "http://ingestion-service:***@project-service:8000"
    assert "s3cret" not in ep.display


def test_bare_url_uses_the_given_username():
    ep = parse_internal_url("https://tm.internal", password="pw", username="caller")
    assert ep.username == "caller"
    assert ep.display == "https://caller:***@tm.internal"


def test_bare_url_without_a_password_raises():
    with pytest.raises(RetentionError):
        parse_internal_url("http://project-service:8000")
    with pytest.raises(RetentionError):
        parse_internal_url("http://project-service:8000", password="")


def test_password_with_special_characters_is_not_quoted_into_the_url():
    pw = "p@ss:w/ord#?%40"
    ep = parse_internal_url("http://project-service:8000", password=pw)
    assert ep.password == pw
    assert pw not in ep.url and "p@ss" not in ep.url
    assert "p@ss" not in ep.display and "ord" not in ep.display
    assert ep.url == "http://project-service:8000/internal/v1/projects/retention"


def test_bad_scheme_or_host_still_raises_with_the_setting_name():
    with pytest.raises(RetentionError, match="TEST_MANAGEMENT_INTERNAL_URL"):
        parse_internal_url("ftp://host", name="TEST_MANAGEMENT_INTERNAL_URL", password="pw")
    with pytest.raises(RetentionError):
        parse_internal_url("http://:80", password="pw")
