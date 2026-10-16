import logging

import pytest

from src.auth.service.sso_service import _app_roles


@pytest.mark.parametrize("claims, expected", [
    ({}, []),
    ({"roles": "QEOS.Admin"}, []),
    ({"roles": {"a": 1}}, []),
    ({"roles": ["QEOS.Admin", 7, None, "  ", " QEOS.Member "]}, ["QEOS.Admin", "QEOS.Member"]),
    ({"roles": ["QEOS.Admin", "qeos.admin", "QEOS.Viewer"]}, ["QEOS.Admin", "QEOS.Viewer"]),
    ({"roles": ["x" * 150]}, ["x" * 100]),
])
def test_roles_claim_shapes(claims, expected):
    assert _app_roles(claims) == expected


def test_more_than_50_roles_keeps_50_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        got = _app_roles({"roles": [f"R{i}" for i in range(60)]})
    assert got == [f"R{i}" for i in range(50)]
    assert "60 app roles" in caplog.text
