"""user_exists asks auth-service's internal API with the shared Basic
credentials — no superuser bearer token involved."""
import base64

import httpx
import pytest
import respx

from src.organization.core.config import settings
from src.organization.utils.auth_client import AuthServiceUnavailable, is_active_superuser, user_exists

URL = f"{settings.AUTH_SERVICE_URL}/internal/v1/users/5"


def expected_basic():
    raw = f"{settings.INTERNAL_API_USERNAME}:{settings.INTERNAL_API_PASSWORD}".encode()
    return f"Basic {base64.b64encode(raw).decode()}"


@respx.mock
def test_an_existing_user_is_true_and_sends_basic_auth():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"id": 5, "email": "e", "is_active": True}))
    assert user_exists(5) is True
    assert route.calls.last.request.headers["Authorization"] == expected_basic()


@respx.mock
def test_a_missing_user_is_false():
    respx.get(URL).mock(return_value=httpx.Response(404))
    assert user_exists(5) is False


@respx.mock
def test_any_other_answer_is_unavailable():
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(AuthServiceUnavailable):
        user_exists(5)


@respx.mock
def test_a_connection_error_is_unavailable():
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AuthServiceUnavailable):
        user_exists(5)


@respx.mock
@pytest.mark.parametrize("body, expected", [
    ({"id": 5, "email": "e", "is_active": True, "is_superuser": True}, True),
    ({"id": 5, "email": "e", "is_active": True, "is_superuser": False}, False),
    ({"id": 5, "email": "e", "is_active": False, "is_superuser": True}, False),
    ({"id": 5, "email": "e", "is_active": True}, False),  # an auth-service from before the field
    ({"id": 5, "email": "e", "is_active": True, "is_superuser": "true"}, False),
])
def test_is_active_superuser(body, expected):
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=body))
    assert is_active_superuser(5) is expected
    assert route.calls.last.request.headers["Authorization"] == expected_basic()


@respx.mock
def test_is_active_superuser_unknown_user_is_false():
    respx.get(URL).mock(return_value=httpx.Response(404))
    assert is_active_superuser(5) is False


@respx.mock
@pytest.mark.parametrize("mock", [
    {"return_value": httpx.Response(503)},
    {"side_effect": httpx.ConnectError("refused")},
    {"return_value": httpx.Response(200, text="not json")},
])
def test_is_active_superuser_unavailable(mock):
    respx.get(URL).mock(**mock)
    with pytest.raises(AuthServiceUnavailable):
        is_active_superuser(5)
