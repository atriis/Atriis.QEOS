"""Asking QEOS for the change's suggestion (spec 2026-10-13 §2.1; plan Rulings 1, 2)."""
import json
import re
from types import SimpleNamespace

import pytest

from qeos_collector import impact
from qeos_collector.upload import ConfigError

KEY = "qeos_impact_client_key"
CHANGES = {"base_ref": "origin/main", "truncated": False,
           "files": [{"path": "src/pay/api.py", "status": "M", "additions": 3, "deletions": 1},
                     {"path": "features/pay.feature", "status": "M", "additions": 1, "deletions": 0}]}
LABELLED = {"test_key": "c" * 64, "suite": "api", "class_name": "PayTest", "name": "refunds",
            "kind": "failing_on_branch", "evidence": None}


def answer(tests, state="ok"):
    return {"state": state, "model_version": "stats-v1", "history_runs": 34 if state == "ok" else 7, "needed_runs": 20,
            "statistical_total": 0, "tests": tests}


def target(url, commit="abc1234", branch="feature/pay"):
    return impact.Target(url=url, context=None, commit=commit, branch=branch)


def fetch(url, changes=CHANGES):
    return impact.fetch(target(url), KEY, {}, collect=lambda env, commit: changes)


def no_args(**values):
    return SimpleNamespace(**{"url": None, "ca_file": None, "commit": None, "branch": None, **values})


def test_the_change_and_branch_are_sent_with_the_key(platform):
    platform.reply(200, answer([LABELLED]))
    found = fetch(platform.url)
    assert found.code == impact.SUGGESTED and found.tests == [LABELLED]
    request = platform.requests[0]
    assert request["path"] == "/api/v1/collect/impact"
    assert request["headers"]["Authorization"] == f"Bearer {KEY}"
    assert json.loads(request["body"]) == {"changed_paths": ["src/pay/api.py", "features/pay.feature"],
                                           "branch": "feature/pay"}


def test_the_commit_reaches_the_diff():
    seen = []
    found = impact.fetch(target("https://qeos.acme.test", commit="def5678"), KEY, {"X": "1"},
                         collect=lambda env, commit: seen.append((dict(env), commit)))
    assert seen == [({"X": "1"}, "def5678")]
    assert found.code == impact.NOTHING  # the stand-in diff returned None: no change data


def test_not_enough_history_with_labelled_tests_is_still_a_suggestion(platform):
    platform.reply(200, answer([LABELLED], state="not_enough_history"))
    assert fetch(platform.url).code == impact.SUGGESTED


@pytest.mark.parametrize("state, reason", [
    ("ok", "no test is likely affected by this change"),
    ("not_enough_history", "not enough history yet (7 of 20 runs with changed files)"),
])
def test_an_empty_suggestion_is_nothing_to_suggest(platform, state, reason):
    platform.reply(200, answer([], state=state))
    found = fetch(platform.url)
    assert found.code == impact.NOTHING and reason in found.reason


@pytest.mark.parametrize("changes", [None, {**CHANGES, "files": []}])
def test_no_change_data_asks_nothing(platform, changes):
    found = fetch(platform.url, changes)
    assert found.code == impact.NOTHING and platform.requests == []


@pytest.mark.parametrize("status, body, reason", [
    (503, {"detail": {"code": "impact_timeout", "message": "slow"}}, "impact_timeout"),
    (503, {"detail": "Service unavailable"}, "answered 503"),
    (502, b"bad gateway", "answered 502"),
    (429, {"detail": "slow down"}, "answered 429"),
    (200, {"unexpected": True}, "unexpected answer"),
])
def test_an_overloaded_slow_or_odd_platform_is_unavailable(platform, status, body, reason):
    platform.reply(status, body)
    found = fetch(platform.url)
    assert found.code == impact.UNAVAILABLE and reason in found.reason


def test_an_unreachable_platform_is_unavailable():
    found = fetch("http://127.0.0.1:9")
    assert found.code == impact.UNAVAILABLE and "cannot reach the platform" in found.reason


@pytest.mark.parametrize("status, message", [
    (401, "invalid or revoked (401)"),
    (404, "older than suggested tests first"),
    (422, "refused the change (422)"),
])
def test_configuration_problems_raise(platform, status, message):
    platform.reply(status, {"detail": "nope"})
    with pytest.raises(ConfigError, match=re.escape(message)):
        fetch(platform.url)


def test_a_key_without_the_permission_says_who_can_allow_it(platform):
    """Per-key permission (user ruling): 403 impact_not_allowed is a configuration problem (exit 2)."""
    platform.reply(403, {"detail": {"code": "impact_not_allowed", "message": "This API key may not read test "
                                                                           "suggestions."}})
    with pytest.raises(ConfigError) as raised:
        fetch(platform.url)
    assert str(raised.value) == impact.NOT_ALLOWED


def test_another_403_is_a_configuration_problem_with_the_platforms_message(platform):
    platform.reply(403, {"detail": {"code": "project_archived", "message": "The project is archived"}})
    with pytest.raises(ConfigError, match=re.escape("refused the change (403)")):
        fetch(platform.url)


def test_a_422_list_detail_is_shown(platform):
    platform.reply(422, {"detail": [{"loc": ["body", "changed_paths"], "msg": "too long", "type": "value_error"}]})
    with pytest.raises(ConfigError, match="too long"):
        fetch(platform.url)


@pytest.mark.parametrize("body", [b"<html><body><h1>429 Too Many Requests</h1></body></html>",
                                  {"detail": {"code": "impact_timeout", "message": "slow"}}])
def test_a_429_body_is_never_read(platform, body):
    """nginx answers 429 with an HTML page: the body is never parsed, whatever it holds."""
    platform.reply(429, body)
    found = fetch(platform.url)
    assert found.code == impact.UNAVAILABLE and found.reason == "the platform answered 429"


def test_resolve_takes_flags_then_the_environment_then_the_file(tmp_path):
    (tmp_path / ".qeos.yml").write_text("url: https://from-file.acme.test\nbranch: from-file\n", encoding="utf-8")
    found = impact.resolve(no_args(), {"QEOS_BRANCH": "from-env"}, KEY, str(tmp_path))
    assert (found.url, found.branch, found.commit) == ("https://from-file.acme.test", "from-env", None)
    flagged = impact.resolve(no_args(url="https://flag.acme.test", commit="abc1234", branch="flag"), {}, KEY,
                             str(tmp_path))
    assert (flagged.url, flagged.commit, flagged.branch) == ("https://flag.acme.test", "abc1234", "flag")


@pytest.mark.parametrize("env, key, message", [
    ({}, KEY, "QEOS_URL is not set"),
    ({"QEOS_URL": "http://qeos.acme.test"}, KEY, "https://"),
    ({"QEOS_URL": "https://qeos.acme.test"}, "", "QEOS_API_KEY is not set"),
])
def test_resolve_refuses_what_can_never_work(tmp_path, env, key, message):
    with pytest.raises(ConfigError, match=re.escape(message)):
        impact.resolve(no_args(), env, key, str(tmp_path))
