"""qeos-collector impact (spec 2026-10-13 §2.1; plan Rulings 2, 14, 15)."""
import json

import pytest

from qeos_collector import impact
from qeos_collector.cli import main

KEY = "qeos_impact_command_key"
CHANGES = {"base_ref": "origin/main", "truncated": False,
           "files": [{"path": "src/pay/api.py", "status": "M", "additions": 3, "deletions": 1}]}
PAY = ("Feature: Pay\n\n  Scenario: Pays with card\n    Given a shopper\n\n  Scenario Outline: Pays <amount>\n"
       "    Given a shopper with <amount>\n\n    Examples:\n      | amount |\n      | 10     |\n      | 20     |\n")
SUGGESTION = {
    "state": "ok", "model_version": "stats-v1", "history_runs": 34, "needed_runs": 20, "statistical_total": 1,
    "tests": [
        {"test_key": "a" * 64, "suite": "Pay", "class_name": "features/pay.feature", "name": "Pays 20",
         "kind": "statistical", "evidence": {"path_unit": "src/pay/", "changed_runs": 6, "new_failures": 4,
                                             "confidence": 0.6667, "lift": 22.2, "base_rate": 0.03}},
        {"test_key": "b" * 64, "suite": "Cart", "class_name": "features/cart.feature", "name": "Gone away",
         "kind": "no_history", "evidence": None},
        {"test_key": "c" * 64, "suite": "api\tv2", "class_name": "PayTest", "name": "refunds\nlater",
         "kind": "failing_on_branch", "evidence": None},
    ],
}
CUCUMBER_OUT = 'features/pay.feature:12\n--name "^Gone away$"\n--name "^refunds.later$"\n'


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "features").mkdir()
    (tmp_path / "features" / "pay.feature").write_text(PAY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(impact, "collect_changes", lambda env, commit: CHANGES)
    return tmp_path


def env_for(platform, **extra):
    return {"QEOS_URL": platform.url, "QEOS_API_KEY": KEY, **extra}


def test_cucumber_lines_where_the_file_says_and_names_elsewhere(platform, repo, capsys):
    platform.reply(200, SUGGESTION)
    assert main(["impact"], env_for(platform)) == 0
    out, err = capsys.readouterr()
    assert out == CUCUMBER_OUT
    assert "qeos: 3 likely affected test(s) for 1 changed file(s)" in err


def test_list_is_tab_separated_one_test_per_line(platform, repo, capsys):
    platform.reply(200, SUGGESTION)
    assert main(["impact", "--format", "list"], env_for(platform)) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Pay\tfeatures/pay.feature\tPays 20", "Cart\tfeatures/cart.feature\tGone away", "api v2\tPayTest\trefunds later"]


def test_json_is_the_whole_suggestion(platform, repo, capsys):
    platform.reply(200, SUGGESTION)
    assert main(["impact", "--format", "json"], env_for(platform)) == 0
    assert json.loads(capsys.readouterr().out) == SUGGESTION


def test_out_writes_the_file_with_lf_and_prints_nothing(platform, repo, capsys):
    platform.reply(200, SUGGESTION)
    assert main(["impact", "--out", "suggested.txt"], env_for(platform)) == 0
    assert (repo / "suggested.txt").read_bytes() == CUCUMBER_OUT.encode("utf-8")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("status, body, code", [
    (200, {**SUGGESTION, "tests": []}, 3),
    (503, {"detail": {"code": "impact_timeout", "message": "slow"}}, 4),
])
def test_out_is_emptied_when_nothing_is_suggested(platform, repo, status, body, code):
    """Review Focus 5: a later step must never read an earlier step's list."""
    (repo / "suggested.txt").write_text("features/old.feature:3\n", encoding="utf-8")
    platform.reply(status, body)
    assert main(["impact", "--out", "suggested.txt"], env_for(platform)) == code
    assert (repo / "suggested.txt").read_text(encoding="utf-8") == ""


def test_without_feature_files_the_default_is_a_list(platform, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(impact, "collect_changes", lambda env, commit: CHANGES)
    platform.reply(200, SUGGESTION)
    assert main(["impact"], env_for(platform)) == 0
    assert capsys.readouterr().out.startswith("Pay\tfeatures/pay.feature\tPays 20\n")


def test_nothing_to_suggest_exits_3_and_says_why(platform, repo, capsys):
    platform.reply(200, {**SUGGESTION, "tests": []})
    assert main(["impact"], env_for(platform)) == 3
    out, err = capsys.readouterr()
    assert out == "" and "qeos: no suggestion: no test is likely affected by this change" in err


def test_an_unreachable_platform_exits_4(repo, capsys):
    assert main(["impact"], {"QEOS_URL": "http://127.0.0.1:9", "QEOS_API_KEY": KEY}) == 4
    assert "cannot reach the platform" in capsys.readouterr().err


@pytest.mark.parametrize("env, message", [
    ({"QEOS_API_KEY": KEY}, "QEOS_URL is not set"),
    ({"QEOS_URL": "https://qeos.acme.test"}, "QEOS_API_KEY is not set"),
    ({"QEOS_URL": "https://qeos.acme.test", "QEOS_API_KEY": "qeos_has space"}, "printable ASCII"),
])
def test_configuration_errors_exit_2(repo, capsys, env, message):
    assert main(["impact"], env) == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("command", [["impact"], ["import-features"], ["check"], ["upload", "x.xml"]])
def test_every_command_that_sends_the_key_refuses_an_unusable_one_first(platform, repo, capsys, command):
    """One key check (pre-flight defect 5): nothing is sent with a key http.client would quote in an error."""
    assert main(command, env_for(platform, QEOS_API_KEY="qeos_has space")) == 2
    assert "printable ASCII" in capsys.readouterr().err and platform.requests == []


def test_a_revoked_key_exits_2(platform, repo):
    platform.reply(401, {"detail": "Invalid API key"})
    assert main(["impact"], env_for(platform)) == 2


def test_a_key_without_the_permission_exits_2_and_says_who_can_allow_it(platform, repo, capsys):
    platform.reply(403, {"detail": {"code": "impact_not_allowed", "message": "not allowed"}})
    assert main(["impact"], env_for(platform)) == 2
    assert ("qeos: This API key may not read test suggestions. Ask a project owner or admin to allow test "
            "suggestions for this key.") in capsys.readouterr().err.splitlines()


@pytest.mark.parametrize("key, replies", [
    (KEY, [(403, {"detail": {"code": "impact_not_allowed", "message": "not allowed"}})]),
    ("qeos_has space", []),  # refused before any request
])
def test_out_is_emptied_on_a_configuration_error_too(platform, repo, key, replies):
    (repo / "suggested.txt").write_text("features/old.feature:3\n", encoding="utf-8")
    for status, body in replies:
        platform.reply(status, body)
    assert main(["impact", "--out", "suggested.txt"], env_for(platform, QEOS_API_KEY=key)) == 2
    assert (repo / "suggested.txt").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize("tests", [["not a test"], [None], [SUGGESTION["tests"][0], 7]])
def test_a_tests_list_that_is_not_tests_is_an_unexpected_answer(platform, repo, capsys, tests):
    (repo / "suggested.txt").write_text("features/old.feature:3\n", encoding="utf-8")
    platform.reply(200, {**SUGGESTION, "tests": tests})
    assert main(["impact", "--out", "suggested.txt"], env_for(platform)) == 4
    assert (repo / "suggested.txt").read_text(encoding="utf-8") == ""
    assert "unexpected answer" in capsys.readouterr().err


def test_feature_files_are_looked_for_only_for_a_suggestion(platform, repo, monkeypatch):
    def walked(cwd):
        raise AssertionError("has_feature_files ran without a suggestion")
    monkeypatch.setattr(impact.cucumber, "has_feature_files", walked)
    platform.reply(200, {**SUGGESTION, "tests": []})
    assert main(["impact"], env_for(platform)) == 3


def test_an_empty_change_is_never_sent(platform, repo, monkeypatch, capsys):
    monkeypatch.setattr(impact, "collect_changes", lambda env, commit: {**CHANGES, "files": []})
    assert main(["impact"], env_for(platform)) == 3
    assert platform.requests == [] and "no changed files against origin/main" in capsys.readouterr().err


def test_an_unknown_format_is_a_usage_error(repo):
    assert main(["impact", "--format", "yaml"], {}) == 2


def test_the_key_never_appears_in_the_output(platform, repo, capsys):
    """A platform that echoes the key in a refusal: stderr is scrubbed, nothing reaches stdout or --out."""
    (repo / "suggested.txt").write_text("features/old.feature:3\n", encoding="utf-8")
    platform.reply(422, {"detail": [{"loc": ["header"], "msg": f"bad key {KEY}", "type": "value_error"}]})
    assert main(["impact", "--out", "suggested.txt"], env_for(platform)) == 2
    out, err = capsys.readouterr()
    assert "refused the change (422)" in err and "***" in err
    assert KEY not in out and KEY not in err
    assert KEY not in (repo / "suggested.txt").read_text(encoding="utf-8")
