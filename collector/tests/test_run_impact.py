"""qeos-collector run-impact against a stand-in Cucumber (tests/fake_cucumber.py) and a fake platform (spec 2026-10-13
§2.2; plan Rulings 6-13, 16, 21; the controller's safety ruling: scoring problems never skip tests)."""
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from qeos_collector import cli, impact, run_impact
from qeos_collector.cli import main
from qeos_collector.upload import ConfigError

KEY = "qeos_run_impact_secret"
FAKE = str(Path(__file__).with_name("fake_cucumber.py"))
SPEC = Path(__file__).with_name("fixtures") / "fake-cucumber-spec.json"
CHANGES = {"base_ref": "origin/main", "truncated": False,
           "files": [{"path": "src/pay/api.py", "status": "M", "additions": 3, "deletions": 1}]}
RECEIPT = {"id": 77, "project_id": 1, "total": 5, "passed": 4, "failed": 1, "skipped": 0, "errored": 0,
           "quarantined": 0, "blocking": 1, "created_at": "2026-10-13T10:00:00Z"}
PAYS_WITH_CARD = ("Pay", "features/pay.feature", "Pays with card")
PAYS_10 = ("Pay", "features/pay.feature", "Pays 10")
PAYS_20 = ("Pay", "features/pay.feature", "Pays 20")
ADDS = ("Cart", "features/cart.feature", "Adds")
REMOVES = ("Cart", "features/cart.feature", "Removes")
GONE = ("Cart", "features/cart.feature", "Gone away")
ALL_FIVE = ["features/cart.feature:3", "features/cart.feature:7", "features/pay.feature:12", "features/pay.feature:13",
            "features/pay.feature:4"]


def suggested(*tests):
    return {"state": "ok", "model_version": "stats-v1", "history_runs": 34, "needed_runs": 20,
            "statistical_total": len(tests),
            "tests": [{"test_key": f"{i:064d}", "suite": suite, "class_name": uri, "name": name, "kind": "statistical",
                       "evidence": {"path_unit": "src/pay/", "changed_runs": 6, "new_failures": 4, "confidence": 0.67,
                                    "lift": 22.2, "base_rate": 0.03}}
                      for i, (suite, uri, name) in enumerate(tests)]}


@pytest.fixture
def cucumber(tmp_path, monkeypatch):
    """The stand-in's catalogue and log, the working directory, and the change; returns its invocations."""
    log = tmp_path / "cucumber.log"
    monkeypatch.setenv("FAKE_CUCUMBER_SPEC", str(SPEC))
    monkeypatch.setenv("FAKE_CUCUMBER_LOG", str(log))
    monkeypatch.delenv("FAKE_CUCUMBER_EXTRA", raising=False)
    monkeypatch.delenv("FAKE_CUCUMBER_WINDOWS", raising=False)
    monkeypatch.delenv("FAKE_CUCUMBER_CRASH", raising=False)
    monkeypatch.delenv("FAKE_CUCUMBER_EXIT", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(impact, "collect_changes", lambda env, commit: CHANGES)
    monkeypatch.setattr(cli, "collect_changes", lambda env, commit: CHANGES)

    def invocations():
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    return invocations


def env_for(platform, **extra):
    return {"QEOS_URL": platform.url, "QEOS_API_KEY": KEY, **extra}


def run(argv, env):
    ticks = itertools.count(0, 60)  # each clock reading is 60 s after the last: each stage takes 60 s
    return main(argv, env, sleep=lambda seconds: None, clock=lambda: next(ticks))


def command(*options, flavour="js"):
    return ["run-impact", "--cucumber", flavour, *options, "--", sys.executable, FAKE]


def uploads(platform):
    return [json.loads(r["body"]) for r in platform.requests if r["path"] == "/api/v1/collect/runs"]


def test_the_suggested_scenarios_run_first_then_the_rest_and_none_twice(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_10, GONE))
    platform.reply(201, RECEIPT)
    assert run(command(), env_for(platform)) == 1  # stage 1's failure is the test command's exit code
    calls = cucumber()
    assert [c["dry_run"] for c in calls] == [True, True, False, False]  # discovery, the stage-1 check, two stages
    first, second = calls[2]["ran"], calls[3]["ran"]
    assert first == ["features/pay.feature:12"]
    assert sorted(second) == ["features/cart.feature:3", "features/cart.feature:7", "features/pay.feature:13",
                              "features/pay.feature:4"]
    assert sorted(first + second) == sorted(calls[0]["ran"])  # every discovered scenario, once
    assert calls[2]["rerun"] == "features/pay.feature:12\n"
    [body] = uploads(platform)  # one combined upload
    assert len(body["results"]) == 5
    assert body["run"]["scope"] == "full"
    stages = body["run"]["stages"]
    assert [(s["name"], s["tests"], s["failed"], s["duration_s"]) for s in stages["stages"]] == [
        ("suggested", 1, 1, 60.0), ("rest", 4, 0, 60.0)]
    assert stages["time_to_first_failure_s"] == 3.0
    assert "stopped_after_stage" not in stages
    err = capsys.readouterr().err
    assert "skipped by the filter: 1 suggested test(s) are not among this command's scenarios" in err
    assert "Gone away" in err


def test_the_first_failure_counts_the_earlier_stages_wall_time(platform, cucumber):
    """Pays 10 fails in stage 2: stage 1's 60 s, then the scenarios before it in stage 2 (2 s), then its own 3 s."""
    platform.reply(200, suggested(ADDS))
    platform.reply(201, RECEIPT)
    assert run(command(), env_for(platform)) == 1
    stages = uploads(platform)[0]["run"]["stages"]
    assert [s["name"] for s in stages["stages"]] == ["suggested", "rest"]
    assert stages["time_to_first_failure_s"] == 65.0


def test_discovery_honours_the_commands_tags(platform, cucumber):
    platform.reply(200, suggested(ADDS, PAYS_10))
    platform.reply(201, RECEIPT)
    assert run([*command(), "--tags", "@smoke"], env_for(platform)) == 0
    calls = cucumber()
    assert sorted(calls[0]["ran"]) == ["features/cart.feature:3", "features/pay.feature:4"]
    assert calls[2]["ran"] == ["features/cart.feature:3"]
    assert calls[3]["ran"] == ["features/pay.feature:4"]
    assert all("--tags" in c["argv"] for c in calls)


def test_an_outline_row_is_its_own_line(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    calls = cucumber()
    assert calls[2]["rerun"] == "features/pay.feature:13\n"
    assert calls[2]["ran"] == ["features/pay.feature:13"]
    assert "features/pay.feature:12" in calls[3]["ran"]


def test_a_command_that_adds_its_own_paths_is_refused_before_any_test_runs(platform, cucumber, monkeypatch, capsys):
    """Review Focus 3: a profile's `paths` would add scenarios to stage 1, which would then run them twice."""
    monkeypatch.setenv("FAKE_CUCUMBER_EXTRA", "features/cart.feature")
    platform.reply(200, suggested(PAYS_10))
    assert run(command(), env_for(platform)) == 2
    assert all(c["dry_run"] for c in cucumber())  # nothing ran for real
    assert uploads(platform) == []
    err = capsys.readouterr().err
    assert "cannot narrow this command" in err and "`paths`" in err and "--shard" in err


def test_every_scenario_suggested_runs_one_stage_and_no_empty_rerun_file(platform, cucumber):
    """Review Focus 4: stage 2 would have an empty rerun file, which some runners read as everything."""
    platform.reply(200, suggested(PAYS_WITH_CARD, PAYS_10, PAYS_20, ADDS, REMOVES))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    assert [c["dry_run"] for c in cucumber()] == [True, True, False]
    [body] = uploads(platform)
    assert body["run"]["scope"] == "full"
    assert [s["name"] for s in body["run"]["stages"]["stages"]] == ["suggested"]


def test_no_suggested_scenario_runs_the_command_as_one_stage(platform, cucumber):
    """Review Focus 4: stage 1 would have an empty rerun file."""
    platform.reply(200, suggested(GONE))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    calls = cucumber()
    assert [c["dry_run"] for c in calls] == [True, False]
    assert calls[1]["rerun"] is None and len(calls[1]["ran"]) == 5
    [body] = uploads(platform)
    assert body["run"]["scope"] == "full"
    assert [s["name"] for s in body["run"]["stages"]["stages"]] == ["all"]


@pytest.mark.parametrize("status, answer, cause", [
    (401, {"detail": "Invalid API key"}, "invalid or revoked (401)"),
    (403, {"detail": {"code": "impact_not_allowed", "message": "no"}}, "may not read test suggestions"),
    (403, {"detail": "Forbidden"}, "refused the change (403)"),
    (404, {"detail": "Not Found"}, "(404)"),
    (422, {"detail": [{"msg": "bad"}]}, "refused the change (422)"),
    (429, b"<html>Too Many Requests</html>", "answered 429"),
    (500, {"detail": "boom"}, "answered 500"),
    (503, {"detail": {"code": "impact_timeout", "message": "slow"}}, "impact_timeout"),
])
def test_a_scoring_problem_runs_the_whole_command_unchanged(platform, cucumber, capsys, status, answer, cause):
    """The safety ruling: run-impact never skips the user's tests because of scoring."""
    platform.reply(status, answer)
    platform.reply(201, RECEIPT)
    assert run(command(), env_for(platform)) == 1  # the full suite ran: Pays 10 failed
    calls = cucumber()
    assert [c["dry_run"] for c in calls] == [False]  # no discovery either: the command as given
    assert calls[0]["rerun"] is None and sorted(calls[0]["ran"]) == ALL_FIVE
    [body] = uploads(platform)
    assert body["run"]["scope"] == "full" and len(body["results"]) == 5
    assert [s["name"] for s in body["run"]["stages"]["stages"]] == ["all"]
    err = capsys.readouterr().err
    assert "warning: cannot score the change" in err and cause in err
    assert "running the full suite as one stage" in err


def test_an_unreachable_platform_runs_the_whole_command(platform, cucumber, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise ConnectionRefusedError(10061, "refused")

    monkeypatch.setattr(impact, "_send", refuse)
    platform.reply(201, RECEIPT)
    assert run(command(), env_for(platform)) == 1
    assert [c["dry_run"] for c in cucumber()] == [False]
    assert "warning: cannot score the change: cannot reach the platform" in capsys.readouterr().err


def test_no_change_data_runs_the_whole_command(platform, cucumber, monkeypatch, capsys):
    monkeypatch.setattr(impact, "collect_changes", lambda env, commit: None)
    platform.reply(201, RECEIPT)
    assert run(command(), env_for(platform)) == 1
    assert [c["dry_run"] for c in cucumber()] == [False]
    assert "warning: cannot score the change: no change data" in capsys.readouterr().err


def test_a_bug_while_scoring_runs_the_whole_command(platform, cucumber, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise KeyError("files")

    monkeypatch.setattr(impact, "fetch", broken)
    platform.reply(201, RECEIPT)
    assert run(command(), env_for(platform)) == 1
    assert [c["dry_run"] for c in cucumber()] == [False]
    assert "warning: cannot score the change: unexpected error: KeyError" in capsys.readouterr().err


def test_nothing_to_suggest_is_said_plainly(platform, cucumber, capsys):
    platform.reply(200, suggested())
    platform.reply(201, RECEIPT)
    assert run(command(), env_for(platform)) == 1
    err = capsys.readouterr().err
    assert "no suggestion: no test is likely affected by this change" in err and "warning" not in err


def test_a_windows_runners_backslashes_become_forward_slashes(platform, cucumber, monkeypatch):
    monkeypatch.setenv("FAKE_CUCUMBER_WINDOWS", "1")
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    calls = cucumber()
    assert calls[2]["rerun"] == "features/pay.feature:12\n" and calls[2]["ran"] == ["features/pay.feature:12"]
    assert {r["class_name"] for r in uploads(platform)[0]["results"]} == {"features/pay.feature",
                                                                          "features/cart.feature"}


def test_cucumber_js_is_handed_relative_paths_only(platform, cucumber, tmp_path):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    added = [arg for call in cucumber() for arg in call["argv"]]
    assert added and not any(str(tmp_path) in arg or tmp_path.as_posix() in arg for arg in added)
    assert all("\\" not in arg for arg in added)
    stage_1 = cucumber()[2]["argv"]
    assert stage_1[-3].startswith(".qeos-impact/") and stage_1[-3].endswith("/@stage-1.txt")
    assert stage_1[-2:][0] == "--format" and stage_1[-1].startswith("json:.qeos-impact/")


@pytest.mark.parametrize("flavour, rerun_prefix, report_option", [
    ("jvm", "-Dcucumber.features=@", "-Dcucumber.plugin=json:"),
    ("ruby", "@", "--out"),
])
def test_jvm_and_ruby_command_lines(platform, cucumber, tmp_path, flavour, rerun_prefix, report_option):
    """Recorded command lines: what Maven/Gradle and Ruby Cucumber are handed, with absolute "/" paths."""
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    assert run(command(flavour=flavour), env_for(platform)) == 1
    calls = cucumber()
    assert [c["dry_run"] for c in calls] == [True, True, False, False]
    dry = "-Dcucumber.execution.dry-run=true" if flavour == "jvm" else "--dry-run"
    assert dry in calls[0]["argv"] and dry in calls[1]["argv"] and dry not in calls[2]["argv"]
    stage_1 = calls[2]["argv"]
    reruns = [arg for arg in stage_1 if arg.startswith(rerun_prefix)]
    assert len(reruns) == 1 and reruns[0].startswith(rerun_prefix + tmp_path.as_posix() + "/.qeos-impact/")
    assert reruns[0].endswith("/@stage-1.txt")
    assert report_option in " ".join(stage_1) and "\\" not in " ".join(stage_1[1:])
    assert calls[2]["ran"] == ["features/pay.feature:12"] and len(calls[3]["ran"]) == 4
    assert [s["name"] for s in uploads(platform)[0]["run"]["stages"]["stages"]] == ["suggested", "rest"]


def test_the_command_may_come_without_the_separator(platform, cucumber):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    assert run(["run-impact", "--cucumber", "js", sys.executable, FAKE], env_for(platform)) == 1
    assert len(cucumber()) == 4


def test_no_command_is_a_usage_error(platform, cucumber, capsys):
    assert run(["run-impact", "--cucumber", "js"], env_for(platform)) == 2
    assert "give the test command after --" in capsys.readouterr().err


def test_an_undetectable_cucumber_needs_the_option(platform, cucumber, capsys):
    assert run(["run-impact", "--", sys.executable, FAKE], env_for(platform)) == 2
    assert "pass --cucumber js, jvm or ruby" in capsys.readouterr().err


def test_a_dry_run_that_writes_no_report_is_explained(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_10))
    assert run(["run-impact", "--cucumber", "js", "--", sys.executable, "-c", "pass"], env_for(platform)) == 2
    assert "wrote no JSON report" in capsys.readouterr().err


def test_a_key_that_cannot_be_sent_is_refused_before_anything_runs(platform, cucumber, capsys):
    assert run(command(), env_for(platform, QEOS_API_KEY="bad key")) == 2
    assert cucumber() == [] and platform.requests == []
    assert "printable ASCII" in capsys.readouterr().err


def test_an_upload_configuration_error_after_the_tests_keeps_their_exit_code(platform, cucumber, capsys):
    """The tests already ran: their result is not replaced by a configuration exit code."""
    platform.reply(200, suggested(PAYS_20))
    assert run(command("--component", "not-a-component"), env_for(platform)) == 1  # stage 2's Pays 10 failed
    assert len(cucumber()) == 4 and uploads(platform) == []
    assert "must look like NAME@SHA" in capsys.readouterr().err


def test_the_working_files_are_removed_and_ignored_by_git(platform, cucumber, tmp_path):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    base = tmp_path / ".qeos-impact"
    assert [p.name for p in base.iterdir()] == [".gitignore"]
    assert base.joinpath(".gitignore").read_bytes() == b"*\n"


def test_an_existing_gitignore_is_left_as_it_is(platform, cucumber, tmp_path):
    (tmp_path / ".qeos-impact").mkdir()
    (tmp_path / ".qeos-impact" / ".gitignore").write_text("# mine\n*\n", encoding="utf-8")
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    run(command(), env_for(platform))
    assert (tmp_path / ".qeos-impact" / ".gitignore").read_text(encoding="utf-8") == "# mine\n*\n"


def test_the_program_is_looked_up_as_a_shell_would(monkeypatch):
    """A Windows runner's npx is npx.cmd: found through PATHEXT by shutil.which (plan Ruling 21)."""
    seen = []
    monkeypatch.setattr(run_impact.shutil, "which", lambda name: "C:/tools/npx.cmd" if name == "npx" else None)
    monkeypatch.setattr(run_impact.subprocess, "run",
                        lambda argv, check: seen.append(argv) or subprocess.CompletedProcess(argv, 1))
    assert run_impact.run_command(["npx", "cucumber-js", "--dry-run"]) == 1
    assert seen == [["C:/tools/npx.cmd", "cucumber-js", "--dry-run"]]


def test_a_missing_program_is_a_configuration_error():
    with pytest.raises(ConfigError, match="cannot run no-such-cucumber-xyz"):
        run_impact.run_command(["no-such-cucumber-xyz"])


@pytest.mark.parametrize("folder, flavour, refused", [
    ("C:/ci/50%off", "jvm", True),
    ("C:/ci/a&b", "ruby", True),
    ("C:/ci/a&b", "js", False),   # cucumber-js gets relative paths: the folder never reaches cmd.exe
    ("C:/ci/plain", "jvm", False),
])
def test_cmd_exe_never_sees_a_folder_it_would_expand(monkeypatch, folder, flavour, refused):
    """mvn.cmd and cucumber.bat run through cmd.exe, which expands % and splits on & even inside quotes."""
    monkeypatch.setattr(run_impact, "_WINDOWS", True)
    monkeypatch.setattr(run_impact.shutil, "which", lambda name: f"C:/tools/{name}.cmd")
    if refused:
        with pytest.raises(ConfigError, match="cmd.exe"):
            run_impact.check_paths(flavour, ["mvn", "test"], folder)
    else:
        run_impact.check_paths(flavour, ["mvn", "test"], folder)


def test_cmd_exe_is_not_a_concern_off_windows_or_for_an_exe(monkeypatch):
    monkeypatch.setattr(run_impact, "_WINDOWS", False)
    run_impact.check_paths("jvm", ["mvn", "test"], "/ci/50%off")
    monkeypatch.setattr(run_impact, "_WINDOWS", True)
    monkeypatch.setattr(run_impact.shutil, "which", lambda name: "C:/tools/cucumber.exe")
    run_impact.check_paths("ruby", ["cucumber"], "C:/ci/50%off")


# --- the modes (Task 17) -------------------------------------------------------------------


def test_fail_fast_stops_after_a_failing_stage_1_and_uploads_a_subset(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, RECEIPT)
    assert run(command("--fail-fast"), env_for(platform)) == 1
    assert [c["dry_run"] for c in cucumber()] == [True, True, False]  # stage 2 never started
    [body] = uploads(platform)
    assert body["run"]["scope"] == "impact-subset"
    assert body["run"]["stages"]["stopped_after_stage"] == 1
    assert [s["name"] for s in body["run"]["stages"]["stages"]] == ["suggested"]
    assert len(body["results"]) == 1
    assert "stage 1 failed: stopping before stage 2 (--fail-fast)" in capsys.readouterr().err


def test_fail_fast_with_a_passing_stage_1_runs_the_rest(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(201, RECEIPT)
    assert run(command("--fail-fast"), env_for(platform)) == 1  # Pays 10 fails in stage 2
    assert len(cucumber()) == 4
    run_ = uploads(platform)[0]["run"]
    assert run_["scope"] == "full" and "stopped_after_stage" not in run_["stages"]


def test_fail_fast_counts_a_stage_that_crashed_without_a_report_as_failed(platform, cucumber, monkeypatch):
    """The crashed-stage ruling: a non-zero exit with no report is a failure, so stage 2 does not start."""
    monkeypatch.setenv("FAKE_CUCUMBER_CRASH", "1")
    platform.reply(200, suggested(PAYS_20))
    assert run(command("--fail-fast"), env_for(platform)) == 3  # the crashed command's own exit code
    assert [c["dry_run"] for c in cucumber()] == [True, True, False]
    assert uploads(platform) == []  # no results to upload


def test_fail_fast_does_not_stop_on_a_non_zero_exit_with_a_clean_report(platform, cucumber, monkeypatch):
    """Undefined steps make cucumber-js exit 1 with no failed scenario: not a stage-1 failure (plan Ruling 11)."""
    monkeypatch.setenv("FAKE_CUCUMBER_EXIT", "1")
    platform.reply(200, suggested(PAYS_20))
    platform.reply(201, RECEIPT)
    assert run(command("--fail-fast"), env_for(platform)) == 1
    assert [c["dry_run"] for c in cucumber()] == [True, True, False, False]
    assert uploads(platform)[0]["run"]["scope"] == "full"


def test_without_fail_fast_a_crashed_stage_1_still_runs_the_rest(platform, cucumber, monkeypatch):
    monkeypatch.setenv("FAKE_CUCUMBER_CRASH", "1")
    platform.reply(200, suggested(PAYS_20))
    assert run(command(), env_for(platform)) == 3
    assert [c["dry_run"] for c in cucumber()] == [True, True, False, False]


def test_suggested_only_runs_stage_1_as_a_subset(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(201, RECEIPT)
    assert run(command("--suggested-only"), env_for(platform)) == 0
    assert [c["dry_run"] for c in cucumber()] == [True, True, False]
    run_ = uploads(platform)[0]["run"]
    assert run_["scope"] == "impact-subset"
    assert [s["name"] for s in run_["stages"]["stages"]] == ["suggested"]
    assert "stopped_after_stage" not in run_["stages"]


@pytest.mark.parametrize("status, answer", [
    (200, suggested()),                                                    # nothing to suggest (3)
    (503, {"detail": {"code": "impact_timeout", "message": "slow"}}),     # QEOS out of time (4)
    (403, {"detail": {"code": "impact_not_allowed", "message": "no"}}),   # an upload-only key (2)
])
def test_suggested_only_falls_back_to_the_full_suite(platform, cucumber, capsys, status, answer):
    platform.reply(status, answer)
    platform.reply(201, RECEIPT)
    assert run(command("--suggested-only"), env_for(platform)) == 1  # the full suite's Pays 10 fails
    calls = cucumber()
    assert [c["dry_run"] for c in calls] == [False] and len(calls[0]["ran"]) == 5
    run_ = uploads(platform)[0]["run"]
    assert run_["scope"] == "full" and [s["name"] for s in run_["stages"]["stages"]] == ["all"]
    assert "running the full suite instead (--suggested-only falls back to it)" in capsys.readouterr().err


def test_suggested_only_without_a_suggested_scenario_falls_back_too(platform, cucumber):
    platform.reply(200, suggested(GONE))
    platform.reply(201, RECEIPT)
    assert run(command("--suggested-only"), env_for(platform)) == 1
    assert [c["dry_run"] for c in cucumber()] == [True, False]
    assert uploads(platform)[0]["run"]["scope"] == "full"


@pytest.mark.parametrize("status, answer, code", [
    (200, suggested(), 3),
    (503, {"detail": "busy"}, 4),
    (401, {"detail": "Invalid API key"}, 2),
    (403, {"detail": {"code": "impact_not_allowed", "message": "no"}}, 2),
])
def test_no_fallback_runs_nothing_and_exits_as_impact_would(platform, cucumber, status, answer, code):
    platform.reply(status, answer)
    assert run(command("--suggested-only", "--no-fallback"), env_for(platform)) == code
    assert cucumber() == [] and uploads(platform) == []


def test_no_fallback_when_no_suggested_scenario_is_discovered_exits_3(platform, cucumber):
    platform.reply(200, suggested(GONE))
    assert run(command("--suggested-only", "--no-fallback"), env_for(platform)) == 3
    assert [c["dry_run"] for c in cucumber()] == [True] and uploads(platform) == []


def test_no_fallback_without_suggested_only_is_a_usage_error(platform, cucumber, capsys):
    assert run(command("--no-fallback"), env_for(platform)) == 2
    assert cucumber() == [] and platform.requests == []
    assert "--no-fallback only goes with --suggested-only" in capsys.readouterr().err


def test_the_gate_judges_the_uploaded_run(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, {**RECEIPT, "quarantined": 1, "blocking": 0})
    assert run(command("--gate"), env_for(platform)) == 0  # the tests exited 1; the only failure is quarantined
    assert "gate passed: 1 failure(s) in quarantine, not counted" in capsys.readouterr().err


def test_the_gate_fails_on_failures_outside_quarantine(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(201, {**RECEIPT, "blocking": 1})
    assert run(command("--gate", "--suggested-only"), env_for(platform)) == 1  # Pays 20 passed; the gate decides


def test_the_gate_is_read_from_the_environment(platform, cucumber):
    platform.reply(200, suggested(PAYS_10))
    platform.reply(201, {**RECEIPT, "quarantined": 1, "blocking": 0})
    assert run(command(), env_for(platform, QEOS_GATE="true")) == 0


def test_the_gate_fails_closed_without_an_upload(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(command("--gate", "--suggested-only"), env_for(platform)) == 1
    assert "gate cannot pass without an upload" in capsys.readouterr().err


def test_a_discarded_run_is_gated_on_its_local_results(platform, cucumber, capsys):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(202, {"discarded": True, "reason": "manual runs are off"})
    assert run(command("--gate", "--suggested-only"), env_for(platform)) == 0  # Pays 20 passed
    assert "gate: decided on local results (run not collected)" in capsys.readouterr().err


def test_without_the_gate_a_failed_upload_keeps_the_tests_exit_code(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(command("--suggested-only"), env_for(platform)) == 0  # Pays 20 passed


def test_fail_on_error_fails_a_passing_run_whose_upload_failed(platform, cucumber):
    platform.reply(200, suggested(PAYS_20))
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(command("--suggested-only", "--fail-on-error"), env_for(platform)) == 1
