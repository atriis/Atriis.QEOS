import json
import re
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from qeos_collector import __version__, cli, payload
from qeos_collector.cli import main

KEY = "qeos_cli_secret_key"
NOW = datetime(2026, 9, 29, 10, 5, tzinfo=timezone.utc)
RECEIPT = {"id": 42, "project_id": 1, "total": 2, "passed": 1, "failed": 1, "skipped": 0, "errored": 0,
           "created_at": "2026-09-29T10:05:00Z"}
REPORT = (
    '<testsuites><testsuite name="s" timestamp="2026-09-29T10:00:00Z">'
    '<testcase classname="c" name="passes" time="0.1"/>'
    '<testcase classname="c" name="fails" time="0.2"><failure message="boom">boom</failure></testcase>'
    '</testsuite></testsuites>'
)
GITHUB = {
    "GITHUB_ACTIONS": "true", "GITHUB_SHA": "a" * 40, "GITHUB_REF_NAME": "main",
    "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "acme/shop",
    "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_JOB": "test",
}
CONFIGURED = {"QEOS_URL": "https://qeos.acme.test", "QEOS_API_KEY": KEY}


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "reports" / "junit.xml"
    path.parent.mkdir()
    path.write_text(REPORT, encoding="utf-8")
    return path


def env_for(platform, **extra):
    return {"QEOS_URL": platform.url, "QEOS_API_KEY": KEY, **extra}


def run(argv, env):
    return main(argv, env, now=lambda: NOW, sleep=lambda seconds: None)


def sent(platform, index=0):
    return json.loads(platform.requests[index]["body"])


def test_uploads_one_run(platform, report, capsys):
    platform.reply(201, RECEIPT)

    assert run(["upload", str(report)], env_for(platform)) == 0
    body = sent(platform)
    assert body["run"]["ci_provider"] == "local"
    assert body["run"]["started_at"] == "2026-09-29T10:00:00+00:00"
    assert body["run"]["finished_at"] == "2026-09-29T10:05:00+00:00"
    assert [r["name"] for r in body["results"]] == ["passes", "fails"]
    assert platform.requests[0]["headers"]["Idempotency-Key"].startswith("local-")
    err = capsys.readouterr().err
    assert "qeos: parsed 1 file(s), 2 results (1 failed, 0 errored, 0 skipped)" in err
    assert "qeos: uploaded run 42 (201)" in err


def test_each_local_invocation_gets_a_new_key(platform, report):
    platform.reply(201, RECEIPT)
    platform.reply(201, RECEIPT)
    run(["upload", str(report)], env_for(platform))
    run(["upload", str(report)], env_for(platform))

    keys = [r["headers"]["Idempotency-Key"] for r in platform.requests]
    assert keys[0] != keys[1]


def test_glob_patterns_merge_files_and_skip_duplicates(platform, report, capsys):
    nested = report.parent / "sub" / "more.xml"
    nested.parent.mkdir()
    nested.write_text(REPORT, encoding="utf-8")
    platform.reply(201, RECEIPT)

    assert run(["upload", str(report.parent / "**" / "*.xml"), str(report)], env_for(platform)) == 0
    assert len(platform.requests) == 1
    assert len(sent(platform)["results"]) == 4
    assert "parsed 2 file(s), 4 results" in capsys.readouterr().err


def test_github_actions_metadata_and_key(platform, report):
    platform.reply(201, RECEIPT)

    assert run(["upload", str(report)], env_for(platform, **GITHUB)) == 0
    body = sent(platform)
    assert body["run"]["ci_provider"] == "github_actions"
    assert body["run"]["commit_sha"] == "a" * 40
    assert body["run"]["branch"] == "main"
    assert body["run"]["ci_run_url"] == "https://github.com/acme/shop/actions/runs/123"
    assert re.fullmatch(r"gh-123-2-test-[0-9a-f]{12}", platform.requests[0]["headers"]["Idempotency-Key"])


def test_matrix_legs_and_repeated_uploads_in_one_job_get_different_keys(platform, report):
    # Every leg of a GitHub matrix (and every upload step in one job) sees the same run id, attempt
    # and job id; the server answers 409 when one key comes with a different body, so a shared key
    # would lose every upload after the first
    platform.reply(201, RECEIPT)
    platform.reply(201, dict(RECEIPT, id=43))

    assert run(["upload", str(report)], env_for(platform, **GITHUB)) == 0
    assert run(["upload", str(report)], env_for(platform, **GITHUB)) == 0
    first, second = (r["headers"]["Idempotency-Key"] for r in platform.requests)
    assert first != second
    assert first.startswith("gh-123-2-test-") and second.startswith("gh-123-2-test-")


def test_flags_beat_variables(platform, report):
    platform.reply(201, RECEIPT)
    env = env_for(platform, **GITHUB, QEOS_BRANCH="from-env", QEOS_IDEMPOTENCY_KEY="from env")

    argv = ["upload", str(report), "--branch", "from-flag", "--ci-provider", "other",
            "--idempotency-key", "from flag", "--environment", "staging"]
    assert run(argv, env) == 0
    body = sent(platform)
    assert body["run"]["branch"] == "from-flag"
    assert body["run"]["ci_provider"] == "other"
    assert body["run"]["environment"] == "staging"
    assert platform.requests[0]["headers"]["Idempotency-Key"] == "from-flag"


def test_variables_beat_detection(platform, report):
    platform.reply(201, RECEIPT)
    env = env_for(platform, **GITHUB, QEOS_BRANCH="from-env", QEOS_COMMIT="b" * 40,
                  QEOS_IDEMPOTENCY_KEY="from env", QEOS_CI_PROVIDER="other")

    assert run(["upload", str(report)], env) == 0
    body = sent(platform)
    assert body["run"]["branch"] == "from-env"
    assert body["run"]["commit_sha"] == "b" * 40
    assert body["run"]["ci_provider"] == "other"
    assert platform.requests[0]["headers"]["Idempotency-Key"] == "from-env"


def test_dry_run_prints_the_json_and_needs_no_key(report, capsys):
    assert run(["upload", str(report), "--dry-run"], {}) == 0

    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert [r["name"] for r in body["results"]] == ["passes", "fails"]
    assert body["run"]["ci_provider"] == "local"
    assert "qeos: dry run: 1 part(s), nothing uploaded" in captured.err


def test_parts_are_uploaded_in_order_and_a_failure_names_what_was_stored(platform, report, monkeypatch, capsys):
    monkeypatch.setattr(payload, "MAX_RESULTS_PER_PART", 1)
    platform.reply(201, RECEIPT)
    platform.reply(401, {"detail": "Invalid API key"})

    assert run(["upload", str(report), "--idempotency-key", "job-7"], env_for(platform)) == 0
    assert [r["headers"]["Idempotency-Key"] for r in platform.requests] == ["job-7-part-1", "job-7-part-2"]
    err = capsys.readouterr().err
    assert "qeos: uploaded run 42 (201), part 1 of 2" in err
    assert "qeos: upload failed: the API key is invalid or revoked (401)" in err
    assert "qeos: stored before the failure: run 42 (part 1 of 2)" in err
    assert "qeos: not failing the build (pass --fail-on-error to change that)" in err


def test_an_upload_failure_exits_0_by_default(platform, report):
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(["upload", str(report)], env_for(platform)) == 0


@pytest.mark.parametrize("argv_extra, env_extra", [
    (["--fail-on-error"], {}),
    ([], {"QEOS_FAIL_ON_ERROR": "1"}),
    ([], {"QEOS_FAIL_ON_ERROR": "true"}),
])
def test_fail_on_error_exits_1(platform, report, argv_extra, env_extra):
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(["upload", str(report), *argv_extra], env_for(platform, **env_extra)) == 1


@pytest.mark.parametrize("argv_extra, env, message", [
    ([], {"QEOS_API_KEY": KEY}, "QEOS_URL is not set"),
    ([], {"QEOS_URL": "https://qeos.acme.test"}, "QEOS_API_KEY is not set"),
    ([], {"QEOS_URL": "http://qeos.acme.test", "QEOS_API_KEY": KEY}, "must be an https:// URL"),
    (["--ca-file", "missing.pem"], CONFIGURED, "cannot use --ca-file"),
    ([], {**CONFIGURED, "QEOS_CA_FILE": "missing.pem"}, "cannot use --ca-file"),
    ([], {**CONFIGURED, "QEOS_CI_PROVIDER": "travis"}, "QEOS_CI_PROVIDER must be one of"),
    (["--fail-on-error"], {"QEOS_API_KEY": KEY}, "QEOS_URL is not set"),
])
def test_configuration_errors_exit_2(report, capsys, argv_extra, env, message):
    assert run(["upload", str(report), *argv_extra], env) == 2
    assert message in capsys.readouterr().err


def test_no_file_matched_exits_2(tmp_path, capsys):
    assert run(["upload", str(tmp_path / "*.xml")], CONFIGURED) == 2
    assert "no file matched" in capsys.readouterr().err


def test_files_without_test_cases_upload_nothing(platform, tmp_path, capsys):
    empty = tmp_path / "empty.xml"
    empty.write_text("<testsuites/>", encoding="utf-8")

    assert run(["upload", str(empty)], env_for(platform)) == 0
    assert platform.requests == []
    assert "qeos: no test results found" in capsys.readouterr().err


def test_skipped_files_are_reported_and_the_rest_uploaded(platform, report, capsys):
    broken = report.parent / "broken.xml"
    broken.write_text("<testsuite>", encoding="utf-8")
    platform.reply(201, RECEIPT)

    assert run(["upload", str(report.parent / "*.xml")], env_for(platform)) == 0
    assert len(sent(platform)["results"]) == 2
    err = capsys.readouterr().err
    assert f"qeos: skipped {broken}: not well-formed XML" in err
    assert "parsed 1 file(s)" in err


def test_usage_errors_exit_2(capsys):
    assert run([], {}) == 2
    assert run(["upload"], {}) == 2
    assert run(["upload", "x.xml", "--ci-provider", "travis"], {}) == 2


@pytest.mark.parametrize("bad_key", ["qeos_first\nsecond", "qeos_has xyzzy", "qeos_café"])
def test_an_unusable_api_key_is_a_configuration_error_and_is_never_printed(report, capsys, bad_key):
    assert run(["upload", str(report)], {"QEOS_URL": "https://qeos.acme.test", "QEOS_API_KEY": bad_key}) == 2
    err = capsys.readouterr().err
    assert "QEOS_API_KEY" in err
    for piece in bad_key.split():
        assert piece not in err


def test_version(capsys):
    assert run(["--version"], {}) == 0
    assert capsys.readouterr().out.strip() == f"qeos-collector {__version__}"


def test_python_dash_m_runs_the_cli():
    completed = subprocess.run([sys.executable, "-m", "qeos_collector", "--version"], capture_output=True, text=True)
    assert completed.returncode == 0
    assert completed.stdout.strip() == f"qeos-collector {__version__}"


def test_the_key_never_appears_in_the_output(platform, report, capsys):
    platform.reply(422, {"detail": f"bad token {KEY}"})

    run(["upload", str(report)], env_for(platform))
    err = capsys.readouterr().err
    assert KEY not in err
    assert "bad token ***" in err


@pytest.mark.parametrize("argv_extra, code", [([], 0), (["--fail-on-error"], 1)])
def test_an_unexpected_error_follows_the_upload_failure_rule(platform, report, monkeypatch, capsys, argv_extra, code):
    def explode(*args, **kwargs):
        raise RuntimeError(f"boom {KEY}")

    monkeypatch.setattr(cli, "upload_part", explode)

    assert run(["upload", str(report), *argv_extra], env_for(platform)) == code
    err = capsys.readouterr().err
    assert "qeos: unexpected error: RuntimeError: boom ***" in err
    assert KEY not in err


SHA_A = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def test_component_flags_are_sent(platform, report):
    platform.reply(201, RECEIPT)

    argv = ["upload", str(report), "--component", f"product-api@{SHA_A}", "--component", "web@0f1e2d3c"]
    assert run(argv, env_for(platform)) == 0
    assert sent(platform)["components"] == [
        {"name": "product-api", "sha": SHA_A},
        {"name": "web", "sha": "0f1e2d3c"},
    ]


def test_components_from_environment(platform, report):
    platform.reply(201, RECEIPT)

    env = env_for(platform, QEOS_COMPONENTS=f"product-api@{SHA_A},web@0f1e2d3c")
    assert run(["upload", str(report)], env) == 0
    assert sent(platform)["components"] == [
        {"name": "product-api", "sha": SHA_A},
        {"name": "web", "sha": "0f1e2d3c"},
    ]


def test_component_flags_beat_the_environment(platform, report):
    platform.reply(201, RECEIPT)

    env = env_for(platform, QEOS_COMPONENTS="ignored@0f1e2d3c")
    assert run(["upload", str(report), "--component", "web@aa11bb22"], env) == 0
    assert sent(platform)["components"] == [{"name": "web", "sha": "aa11bb22"}]


def test_no_components_means_no_components_key(platform, report):
    platform.reply(201, RECEIPT)

    assert run(["upload", str(report)], env_for(platform)) == 0
    assert "components" not in sent(platform)


@pytest.mark.parametrize("value, complaint", [
    ("missing-separator", "NAME@SHA"),
    ("api@not-hex!", "hexadecimal"),
    ("@0f1e2d3c", "NAME@SHA"),
    ("api@0f1e2d3c,api@aa11bb22", "unique"),
])
def test_bad_components_are_a_config_error(platform, report, capsys, value, complaint):
    env = env_for(platform, QEOS_COMPONENTS=value)
    assert run(["upload", str(report)], env) == 2
    assert complaint in capsys.readouterr().err


def test_check_passes_and_uploads_nothing(platform, report, capsys):
    platform.reply(200, {"project_id": 7, "name": "ci"})

    assert run(["check", str(report)], env_for(platform)) == 0
    err = capsys.readouterr().err
    assert "qeos: url: ok" in err
    assert "qeos: key: ok (project 7, key 'ci')" in err
    assert "qeos: reports: 1 file(s), 2 results" in err
    assert [r["path"] for r in platform.requests] == ["/api/v1/collect/key"]


@pytest.mark.parametrize("allowed, line", [(True, "qeos: Test suggestions: allowed"),
                                           (False, "qeos: Test suggestions: not allowed")])
def test_check_says_whether_the_key_may_read_test_suggestions(platform, capsys, allowed, line):
    platform.reply(200, {"project_id": 7, "name": "ci", "can_read_impact": allowed})

    assert run(["check"], env_for(platform)) == 0
    assert line in capsys.readouterr().err.splitlines()


def test_check_against_an_older_platform_says_nothing_about_test_suggestions(platform, capsys):
    platform.reply(200, {"project_id": 7, "name": "ci"})

    assert run(["check"], env_for(platform)) == 0
    assert "Test suggestions" not in capsys.readouterr().err


def test_check_without_patterns_checks_config_only(platform, capsys):
    platform.reply(200, {"project_id": 7, "name": "ci"})

    assert run(["check"], env_for(platform)) == 0
    assert "reports:" not in capsys.readouterr().err


def test_check_reports_a_bad_key(platform, capsys):
    platform.reply(401, {"detail": "Invalid API key"})

    assert run(["check"], env_for(platform)) == 2
    assert "invalid or revoked" in capsys.readouterr().err


def test_check_fails_when_no_file_matches(platform, capsys):
    platform.reply(200, {"project_id": 7, "name": "ci"})

    assert run(["check", "no-such-*.xml"], env_for(platform)) == 2
    assert "no file matched" in capsys.readouterr().err


def test_check_needs_a_url(capsys):
    assert run(["check"], {"QEOS_API_KEY": KEY}) == 2
    assert "QEOS_URL" in capsys.readouterr().err


def test_check_needs_a_key(platform, capsys):
    assert run(["check"], {"QEOS_URL": platform.url}) == 2
    assert "QEOS_API_KEY" in capsys.readouterr().err


def test_a_failed_upload_is_spooled_for_the_next_run(platform, report, tmp_path, capsys):
    for _ in range(5):
        platform.reply(503, {"detail": "down"})

    assert run(["upload", str(report), "--spool", str(tmp_path), "--idempotency-key", "job-9"],
               env_for(platform)) == 0
    err = capsys.readouterr().err
    assert "qeos: spooled 1 part(s) for the next run" in err
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1


def test_spooled_parts_are_resent_before_the_current_run(platform, report, tmp_path, capsys):
    for _ in range(5):
        platform.reply(503, {"detail": "down"})
    assert run(["upload", str(report), "--spool", str(tmp_path), "--idempotency-key", "job-9"],
               env_for(platform)) == 0

    platform.reply(201, RECEIPT)  # the spooled part
    platform.reply(201, RECEIPT)  # the current run
    assert run(["upload", str(report), "--spool", str(tmp_path), "--idempotency-key", "job-10"],
               env_for(platform)) == 0
    keys = [r["headers"]["Idempotency-Key"] for r in platform.requests[5:]]
    assert keys == ["job-9", "job-10"]
    assert list(tmp_path.glob("*.json")) == []
    assert "qeos: resent 1 spooled part(s)" in capsys.readouterr().err


def test_a_still_failing_spooled_part_is_kept_and_the_run_continues(platform, report, tmp_path, capsys):
    for _ in range(5):
        platform.reply(503, {"detail": "down"})
    assert run(["upload", str(report), "--spool", str(tmp_path), "--idempotency-key", "job-9"],
               env_for(platform)) == 0

    for _ in range(5):
        platform.reply(503, {"detail": "still down"})  # the spooled part
    platform.reply(201, RECEIPT)  # the current run succeeds
    assert run(["upload", str(report), "--spool", str(tmp_path), "--idempotency-key", "job-10"],
               env_for(platform)) == 0
    assert len(list(tmp_path.glob("*.json"))) == 1
    err = capsys.readouterr().err
    assert "qeos: a spooled part still fails" in err
    assert "qeos: uploaded run 42 (201)" in err


def test_a_rejected_upload_is_not_spooled(platform, report, tmp_path):
    platform.reply(401, {"detail": "Invalid API key"})

    assert run(["upload", str(report), "--spool", str(tmp_path)], env_for(platform)) == 0
    assert list(tmp_path.glob("*.json")) == []


def test_no_spool_flag_means_no_spooling(platform, report, tmp_path):
    for _ in range(5):
        platform.reply(503, {"detail": "down"})
    assert run(["upload", str(report)], env_for(platform)) == 0
    assert list(tmp_path.glob("*.json")) == []


def test_a_trx_report_uploads_like_junit(platform, tmp_path, capsys):
    platform.reply(201, RECEIPT)
    trx = tmp_path / "results.trx"
    trx.write_text(
        '<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">'
        '<Results><UnitTestResult testId="i1" testName="Adds" outcome="Passed" duration="00:00:01.5000000"/>'
        '<UnitTestResult testId="i2" testName="Pays" outcome="Failed"/></Results>'
        '<TestDefinitions><UnitTest id="i1"><TestMethod className="Shop.Cart" name="Adds"/></UnitTest>'
        '<UnitTest id="i2"><TestMethod className="Shop.Cart" name="Pays"/></UnitTest></TestDefinitions>'
        '</TestRun>',
        encoding="utf-8",
    )

    assert run(["upload", str(trx)], env_for(platform)) == 0
    body = sent(platform)
    assert [(r["name"], r["status"]) for r in body["results"]] == [("Adds", "passed"), ("Pays", "failed")]
    assert "qeos: parsed 1 file(s), 2 results" in capsys.readouterr().err


def test_config_file_supplies_defaults_and_flags_win(platform, tmp_path, monkeypatch, capsys):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "junit.xml").write_text(REPORT, encoding="utf-8")
    (tmp_path / ".qeos.yml").write_text(
        f"url: {platform.url}\nenvironment: from-file\npatterns:\n  - \"reports/**/*.xml\"\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    platform.reply(201, RECEIPT)

    # no patterns and no --url on the command line: both come from .qeos.yml
    assert run(["upload"], {"QEOS_API_KEY": KEY}) == 0
    assert sent(platform)["run"]["environment"] == "from-file"

    platform.reply(201, RECEIPT)
    assert run(["upload", "--environment", "from-flag"], {"QEOS_API_KEY": KEY}) == 0
    assert sent(platform, 1)["run"]["environment"] == "from-flag"


def test_no_patterns_anywhere_is_a_config_error(platform, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run(["upload"], env_for(platform)) == 2
    assert "no report patterns" in capsys.readouterr().err


def test_codeowners_attach_owners_to_results(platform, tmp_path, monkeypatch):
    (tmp_path / "CODEOWNERS").write_text("*.xml @org/qa-team\n", encoding="utf-8")
    report_path = tmp_path / "junit.xml"
    report_path.write_text(
        '<testsuite name="s"><testcase classname="c" name="ok" time="0.1" file="tests/login.xml"/>'
        '<testcase classname="c" name="nofile" time="0.1"/></testsuite>',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    platform.reply(201, RECEIPT)

    assert run(["upload", str(report_path)], env_for(platform)) == 0
    results = {r["name"]: r for r in sent(platform)["results"]}
    assert results["ok"]["owner"] == "@org/qa-team"
    assert "owner" not in results["nofile"]


# --- the quarantine-aware gate ---------------------------------------------------------------

def test_gate_passes_when_only_quarantined_tests_failed(platform, report, capsys):
    platform.reply(201, {**RECEIPT, "quarantined": 1, "blocking": 0})
    assert run(["upload", str(report), "--gate"], env_for(platform)) == 0
    assert "qeos: gate passed: 1 failure(s) in quarantine, not counted" in capsys.readouterr().err


def test_gate_fails_on_failures_outside_quarantine(platform, report, capsys):
    platform.reply(201, {**RECEIPT, "quarantined": 0, "blocking": 1})
    assert run(["upload", str(report), "--gate"], env_for(platform)) == 1
    assert "qeos: gate failed: 1 failing test(s) outside quarantine" in capsys.readouterr().err


def test_without_the_gate_failures_never_fail_the_build(platform, report):
    platform.reply(201, {**RECEIPT, "blocking": 1})
    assert run(["upload", str(report)], env_for(platform)) == 0


def test_gate_from_the_environment_and_the_last_part_decides(platform, report, monkeypatch):
    monkeypatch.setattr(payload, "MAX_RESULTS_PER_PART", 1)
    platform.reply(201, {**RECEIPT, "blocking": 0})
    platform.reply(201, {**RECEIPT, "blocking": 1})   # the receipt counts the whole run so far
    assert run(["upload", str(report)], env_for(platform, QEOS_GATE="true")) == 1


def test_gate_against_an_older_platform_counts_every_failure(platform, report, capsys):
    platform.reply(201, RECEIPT)   # no quarantine fields: failed + errored decide
    assert run(["upload", str(report), "--gate"], env_for(platform)) == 1
    assert "does not report quarantine" in capsys.readouterr().err


def test_gate_fails_closed_when_the_upload_fails(platform, report, capsys):
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(["upload", str(report), "--gate"], env_for(platform)) == 1
    assert "gate cannot pass without an upload" in capsys.readouterr().err


DISCARDED = {"discarded": True, "reason": "manual runs are not collected for this project"}
NOTICE = "qeos: run not collected: manual runs are not collected for this project"


def test_a_discarded_run_prints_the_notice_and_exits_zero(platform, report, capsys):
    platform.reply(202, DISCARDED)

    assert run(["upload", str(report)], env_for(platform)) == 0
    assert NOTICE in capsys.readouterr().err


def test_a_discarded_first_part_stops_the_upload(platform, report, monkeypatch):
    monkeypatch.setattr(payload, "MAX_RESULTS_PER_PART", 1)  # two results, two parts
    platform.reply(202, DISCARDED)

    assert run(["upload", str(report)], env_for(platform)) == 0
    assert len(platform.requests) == 1


def test_gate_on_a_discarded_run_is_decided_on_the_local_results(platform, report, capsys):
    # REPORT has a failing test: not collected, but the required check must still fail
    platform.reply(202, DISCARDED)

    assert run(["upload", "--gate", str(report)], env_for(platform)) == 1
    err = capsys.readouterr().err
    assert NOTICE in err
    assert "gate: decided on local results (run not collected)" in err
    assert "gate failed" in err


def test_gate_on_a_discarded_run_passes_when_every_result_passes(platform, tmp_path, capsys):
    green = tmp_path / "green.xml"
    green.write_text('<testsuite name="s" tests="1"><testcase classname="c" name="ok"/></testsuite>',
                     encoding="utf-8")
    platform.reply(202, DISCARDED)

    assert run(["upload", "--gate", str(green)], env_for(platform)) == 0
    assert "gate passed" in capsys.readouterr().err


def test_fail_on_error_alone_on_a_discarded_run_exits_zero(platform, report):
    platform.reply(202, DISCARDED)

    assert run(["upload", "--fail-on-error", str(report)], env_for(platform)) == 0


def test_a_discard_after_stored_parts_names_what_was_stored(platform, report, monkeypatch, capsys):
    monkeypatch.setattr(payload, "MAX_RESULTS_PER_PART", 1)
    platform.reply(201, RECEIPT)
    platform.reply(202, DISCARDED)

    assert run(["upload", str(report)], env_for(platform)) == 0
    err = capsys.readouterr().err
    assert NOTICE in err
    assert "stored before the discard: run " in err


def test_trigger_flag_overrides_detection(platform, report):
    platform.reply(201, RECEIPT)
    env = env_for(platform, GITHUB_ACTIONS="true", GITHUB_EVENT_NAME="workflow_dispatch",
                  GITHUB_TRIGGERING_ACTOR="octocat")

    run(["upload", "--trigger", "automatic", str(report)], env)
    assert sent(platform)["run"]["trigger"] == "automatic"


def test_trigger_variable_is_sent(platform, report):
    platform.reply(201, RECEIPT)

    run(["upload", str(report)], env_for(platform, QEOS_TRIGGER="qeos"))
    assert sent(platform)["run"]["trigger"] == "qeos"


def test_an_invalid_trigger_is_a_config_error(platform, report):
    assert run(["upload", "--trigger", "cron", str(report)], env_for(platform)) == 2


def test_a_discarded_spooled_part_is_counted_apart_from_resent_ones(platform, report, tmp_path, capsys):
    for _ in range(5):
        platform.reply(503, {"detail": "down"})
    assert run(["upload", str(report), "--spool", str(tmp_path), "--idempotency-key", "job-9"],
               env_for(platform)) == 0

    platform.reply(202, DISCARDED)  # the spooled part
    platform.reply(201, RECEIPT)    # the current run
    assert run(["upload", str(report), "--spool", str(tmp_path), "--idempotency-key", "job-10"],
               env_for(platform)) == 0
    err = capsys.readouterr().err
    assert "resent" not in err
    assert "1 spooled part(s) not collected (discarded by the platform)" in err
    assert list(tmp_path.glob("*.json")) == []


def test_the_trigger_error_names_flag_and_variable(platform, report, capsys):
    assert run(["upload", "--trigger", "cron", str(report)], env_for(platform)) == 2
    assert "--trigger / QEOS_TRIGGER must be one of" in capsys.readouterr().err



def test_qeos_action_extra_args_are_split_as_words(tmp_path, monkeypatch, capsys):
    """The GitHub Action hands extra-args over as one environment string (no shell): shlex splits it."""
    import shutil as _shutil
    from pathlib import Path as _Path

    _shutil.copy(_Path(__file__).with_name("fixtures") / "pytest.xml", tmp_path / "r.xml")
    monkeypatch.chdir(tmp_path)
    env = {"QEOS_ACTION_EXTRA_ARGS": '--dry-run --environment "staging east" --no-changes'}
    assert main(["upload", "r.xml"], env) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["run"]["environment"] == "staging east"


def test_qeos_action_extra_args_that_cannot_be_split_are_a_usage_error(capsys):
    assert main(["upload", "r.xml"], {"QEOS_ACTION_EXTRA_ARGS": '--environment "open'}) == 2
    assert "QEOS_ACTION_EXTRA_ARGS cannot be split" in capsys.readouterr().err


def test_the_gitlab_templates_qeos_extra_args_is_not_read(tmp_path, monkeypatch, capsys):
    """The GitLab template already passes QEOS_EXTRA_ARGS on the command line: reading it too would double flags."""
    import shutil as _shutil
    from pathlib import Path as _Path

    _shutil.copy(_Path(__file__).with_name("fixtures") / "pytest.xml", tmp_path / "r.xml")
    monkeypatch.chdir(tmp_path)
    env = {"QEOS_ACTION_EXTRA_ARGS": "--dry-run --no-changes", "QEOS_EXTRA_ARGS": "--environment gitlab"}
    assert main(["upload", "r.xml"], env) == 0
    assert "environment" not in json.loads(capsys.readouterr().out)["run"]
