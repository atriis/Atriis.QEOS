"""qeos-collector import-features (ADR-024)."""
import json
import subprocess

import pytest

from qeos_collector.cli import main

KEY = "qeos_test_key_123"
GRANT = {"token": "t0k", "expires_in": 300, "project_id": 7}
SUMMARY = {"created": 1, "updated": 0, "moved": 0, "reactivated": 0, "archived": 0, "unchanged": 0,
           "skipped": 0, "mass_archive": False}
RESULT = {"plan_hash": "a" * 64, "summary": SUMMARY,
          "items": [{"action": "create", "path": "features/a.feature", "scenario": "S", "case_number": 1}],
          "errors": [], "warnings": []}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "features" / "sub").mkdir(parents=True)
    (tmp_path / "features" / "a.feature").write_text("Feature: A\n  Scenario: S\n    Given x\n", encoding="utf-8")
    (tmp_path / "features" / "sub" / "b.feature").write_text("Feature: B\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def env(platform, **extra):
    return {"QEOS_URL": platform.url, "QEOS_API_KEY": KEY, **extra}


def sent(platform, i):
    return json.loads(platform.requests[i]["body"])


def test_it_trades_the_key_then_runs_a_full_import(platform, repo):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features"], env(platform)) == 0
    token, imp = platform.requests
    assert token["path"] == "/api/v1/collect/token"
    assert token["headers"]["Authorization"] == f"Bearer {KEY}"
    assert imp["path"] == "/api/v1/projects/7/cases/import?dry_run=false"
    assert imp["headers"]["Authorization"] == "Bearer t0k"
    body = sent(platform, 1)
    assert [f["path"] for f in body["files"]] == ["features/a.feature", "features/sub/b.feature"]
    assert body["full"] is True and "allow_mass_archive" not in body


def test_flags_reach_the_request(platform, repo):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features", "features/*.feature", "--no-full", "--allow-mass-archive"], env(platform)) == 0
    body = sent(platform, 1)
    assert [f["path"] for f in body["files"]] == ["features/a.feature"]
    assert body["full"] is False and body["allow_mass_archive"] is True


def test_qeos_yml_features_are_the_default_patterns(platform, repo):
    (repo / ".qeos.yml").write_text("features:\n  - features/sub/*.feature\n", encoding="utf-8")
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features"], env(platform)) == 0
    assert [f["path"] for f in sent(platform, 1)["files"]] == ["features/sub/b.feature"]


def test_a_pull_request_build_skips(platform, repo, capsys):
    ci = {"GITHUB_ACTIONS": "true", "GITHUB_REF_NAME": "12/merge", "GITHUB_HEAD_REF": "feature-x"}
    assert main(["import-features"], env(platform, **ci)) == 0
    assert platform.requests == []
    assert "skipped: on feature-x; cases sync from master" in capsys.readouterr().err


def test_the_sync_branch_can_be_named(platform, repo):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    ci = {"GITHUB_ACTIONS": "true", "GITHUB_REF_NAME": "main"}
    assert main(["import-features", "--branch", "main"], env(platform, **ci)) == 0
    assert len(platform.requests) == 2


def github_event(tmp_path, default_branch):
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"repository": {"default_branch": default_branch}}), encoding="utf-8")
    return {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_PATH": str(path)}


def test_github_default_branch_is_the_sync_branch(platform, repo, tmp_path_factory):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    ci = {**github_event(tmp_path_factory.mktemp("event"), "main"), "GITHUB_REF_NAME": "main"}
    assert main(["import-features"], env(platform, **ci)) == 0
    assert len(platform.requests) == 2


def test_github_master_skips_when_the_default_branch_is_main(platform, repo, capsys, tmp_path_factory):
    ci = {**github_event(tmp_path_factory.mktemp("event"), "main"), "GITHUB_REF_NAME": "master"}
    assert main(["import-features"], env(platform, **ci)) == 0
    assert platform.requests == []
    assert "skipped: on master; cases sync from main" in capsys.readouterr().err


def test_an_unreadable_github_event_falls_back_to_master(platform, repo, capsys):
    ci = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_PATH": str(repo / "missing.json"), "GITHUB_REF_NAME": "main"}
    assert main(["import-features"], env(platform, **ci)) == 0
    assert "skipped: on main; cases sync from master" in capsys.readouterr().err


def test_gitlab_default_branch_is_the_sync_branch(platform, repo):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    ci = {"GITLAB_CI": "true", "CI_COMMIT_REF_NAME": "main", "CI_DEFAULT_BRANCH": "main"}
    assert main(["import-features"], env(platform, **ci)) == 0
    assert len(platform.requests) == 2


def test_the_named_sync_branch_beats_the_default_branch(platform, repo, capsys):
    ci = {"GITLAB_CI": "true", "CI_COMMIT_REF_NAME": "main", "CI_DEFAULT_BRANCH": "main",
          "QEOS_IMPORT_BRANCH": "release"}
    assert main(["import-features"], env(platform, **ci)) == 0
    assert "skipped: on main; cases sync from release" in capsys.readouterr().err


def test_the_clone_origin_head_names_the_default_branch(platform, repo, capsys):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk"],
                   cwd=repo, check=True)
    ci = {"JENKINS_URL": "https://ci", "GIT_BRANCH": "origin/master"}
    assert main(["import-features"], env(platform, **ci)) == 0
    assert "skipped: on master; cases sync from trunk" in capsys.readouterr().err


def test_dry_run_asks_for_a_plan_and_prints_it(platform, repo, capsys):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features", "--dry-run"], env(platform)) == 0
    assert platform.requests[1]["path"].endswith("dry_run=true")
    err = capsys.readouterr().err
    assert "would import: 1 created" in err and "features/a.feature" in err


def test_a_refused_mass_archive_fails_the_build(platform, repo, capsys):
    platform.reply(200, GRANT)
    platform.reply(409, {"detail": {"code": "mass_archive", "message": "This would archive 9 of 10 imported cases.",
                                    "archived": 9, "live": 10}})
    assert main(["import-features"], env(platform)) == 1
    err = capsys.readouterr().err
    assert "This would archive 9 of 10" in err
    assert "(pass --allow-mass-archive to go ahead)" in err


def test_a_bad_key_fails_the_build(platform, repo):
    platform.reply(401, {"detail": "Invalid API key"})
    assert main(["import-features"], env(platform)) == 1


def test_parse_errors_fail_only_with_strict(platform, repo):
    broken = {**RESULT, "errors": [{"path": "features/sub/b.feature", "line": 2, "message": "(2:1): expected"}]}
    for argv, code in ((["import-features"], 0), (["import-features", "--strict"], 1)):
        platform.reply(200, GRANT)
        platform.reply(200, broken)
        assert main(argv, env(platform)) == code


@pytest.mark.parametrize("environment", [{"QEOS_API_KEY": KEY}, {"QEOS_URL": "https://qeos.example"}])
def test_missing_url_or_key_is_a_configuration_error(repo, environment):
    assert main(["import-features"], environment) == 2


def test_no_matching_files_is_a_configuration_error(platform, repo):
    assert main(["import-features", "nothing/**/*.feature"], env(platform)) == 2


def test_an_unreadable_file_is_a_configuration_error(platform, repo, capsys):
    (repo / "features" / "latin.feature").write_bytes(b"Feature: caf\xe9\n")
    assert main(["import-features"], env(platform)) == 2
    assert "latin.feature" in capsys.readouterr().err


def test_a_non_json_token_reply_fails_the_build(platform, repo, capsys):
    platform.reply(200, b"<html>captive portal</html>")
    assert main(["import-features"], env(platform)) == 1
    assert "the platform sent an unexpected response" in capsys.readouterr().err


def test_a_token_reply_without_project_id_fails_the_build(platform, repo, capsys):
    platform.reply(200, {"token": "t0k"})
    assert main(["import-features"], env(platform)) == 1
    assert "unexpected response" in capsys.readouterr().err


def test_a_malformed_import_result_fails_the_build(platform, repo, capsys):
    platform.reply(200, GRANT)
    platform.reply(200, {"summary": {}})
    assert main(["import-features"], env(platform)) == 1
    assert "unexpected response" in capsys.readouterr().err


def test_a_non_object_error_entry_fails_the_build(platform, repo, capsys):
    platform.reply(200, GRANT)
    platform.reply(200, {**RESULT, "errors": ["boom"]})
    assert main(["import-features"], env(platform)) == 1
    assert "unexpected response" in capsys.readouterr().err


def test_a_too_large_import_fails_the_build(platform, repo):
    platform.reply(200, GRANT)
    platform.reply(413, {"detail": "too many files"})
    assert main(["import-features"], env(platform)) == 1


def test_an_unreachable_platform_fails_the_build(repo):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert main(["import-features"], {"QEOS_URL": f"http://127.0.0.1:{port}", "QEOS_API_KEY": KEY}) == 1


def test_node_modules_are_not_imported(platform, repo):
    (repo / "node_modules" / "x").mkdir(parents=True)
    (repo / "node_modules" / "x" / "a.feature").write_text("Feature: Third party\n", encoding="utf-8")
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features"], env(platform)) == 0
    assert all("node_modules" not in f["path"] for f in sent(platform, 1)["files"])


def test_patterns_outside_the_working_directory_are_refused(platform, repo):
    (repo.parent / "outside.feature").write_text("Feature: O\n", encoding="utf-8")
    assert main(["import-features", "../*.feature"], env(platform)) == 2


SUITE_FILE = ".github/workflows/suite-flights.yml"


@pytest.fixture
def suites(repo):
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "suite-flights.yml").write_text("name: flights\n", encoding="utf-8")
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    return repo


def test_suites_files_sent_with_patterns_and_repo(platform, suites):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    argv = ["import-features", "--suites", "./.github/workflows/suite-*.yml"]
    assert main(argv, env(platform, GITHUB_REPOSITORY="atriis/obt")) == 0
    body = sent(platform, 1)
    assert body["suite_files"] == [{"path": SUITE_FILE, "content": "name: flights\n"}]
    assert body["suite_patterns"] == [".github/workflows/suite-*.yml"]
    assert body["source_repo"] == "atriis/obt"
    assert [f["path"] for f in body["files"]] == ["features/a.feature", "features/sub/b.feature"]


def test_no_suites_option_sends_old_payload(platform, suites):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features"], env(platform, GITHUB_REPOSITORY="atriis/obt")) == 0
    body = sent(platform, 1)
    assert set(body) == {"files", "full"}


def test_suite_warnings_printed(platform, suites, capsys):
    result = {**RESULT, "suite_changes": [
        {"action": "created", "workflow": SUITE_FILE, "external_id": "a", "name": "A"},
        {"action": "created", "workflow": SUITE_FILE, "external_id": "b", "name": "B"},
        {"action": "updated", "workflow": SUITE_FILE, "external_id": "c", "name": "C"},
        {"action": "deleted", "workflow": SUITE_FILE, "external_id": "d", "name": "D"}],
        "suite_warnings": [{"workflow": SUITE_FILE, "external_id": "x", "message": "no such tag"}]}
    platform.reply(200, GRANT)
    platform.reply(200, result)
    assert main(["import-features", "--suites", ".github/workflows/suite-*.yml"], env(platform)) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert "Suites: 2 created, 1 updated, 1 deleted" in text
    assert f"warning: {SUITE_FILE} x: no such tag" in text


def test_strict_fails_on_suite_warning(platform, suites):
    result = {**RESULT, "suite_changes": [],
              "suite_warnings": [{"workflow": SUITE_FILE, "external_id": "x", "message": "m"}]}
    for argv, code in ((["import-features", "--suites", SUITE_FILE], 0),
                       (["import-features", "--suites", SUITE_FILE, "--strict"], 1)):
        platform.reply(200, GRANT)
        platform.reply(200, result)
        assert main(argv, env(platform)) == code


def test_pattern_matching_no_file_is_reported(platform, repo, capsys):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features", "--suites", ".github/workflows/suite-*.yml"], env(platform)) == 0
    out = capsys.readouterr()
    assert "--suites pattern matched no file: .github/workflows/suite-*.yml" in out.out + out.err
    body = sent(platform, 1)
    assert body["suite_files"] == [] and body["suite_patterns"] == [".github/workflows/suite-*.yml"]
