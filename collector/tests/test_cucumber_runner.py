"""run-impact's Cucumber adapters (spec 2026-10-13 §2.2; plan Rulings 7, 8, 9, 21)."""
import json
from pathlib import PureWindowsPath

import pytest

from qeos_collector import cucumber
from qeos_collector.cucumber import Scenario


@pytest.mark.parametrize("command, flavour", [
    (["npx", "cucumber-js", "--tags", "@smoke"], "js"),
    (["node_modules/.bin/cucumber-js"], "js"),
    (["C:\\proj\\node_modules\\.bin\\cucumber-js.cmd"], "js"),
    (["node", "node_modules/@cucumber/cucumber/bin/cucumber.js"], "js"),
    (["mvn", "-q", "test", "-Dcucumber.filter.tags=@smoke"], "jvm"),
    (["./mvnw", "verify"], "jvm"),
    (["mvnw.cmd", "verify"], "jvm"),
    (["gradle", "test"], "jvm"),
    (["./gradlew", "test"], "jvm"),
    (["cucumber", "--tags", "@smoke"], "ruby"),
    (["bundle", "exec", "cucumber"], "ruby"),
    (["npm", "test"], None),
    (["python", "fake_cucumber.py"], None),
    ([], None),
])
def test_the_flavour_is_detected_from_the_command(command, flavour):
    assert cucumber.detect_flavour(command) == flavour


def test_npm_and_pnpm_get_the_separator_once():
    assert cucumber.with_separator("js", ["npm", "test"]) == ["npm", "test", "--"]
    assert cucumber.with_separator("js", ["pnpm", "run", "bdd", "--", "--tags", "@x"]) == [
        "pnpm", "run", "bdd", "--", "--tags", "@x"]
    assert cucumber.with_separator("js", ["yarn", "bdd"]) == ["yarn", "bdd"]
    assert cucumber.with_separator("jvm", ["mvn", "test"]) == ["mvn", "test"]


def test_visible_feature_paths_are_left_out_of_the_stage_commands(tmp_path):
    (tmp_path / "tests" / "features" / "smoke").mkdir(parents=True)
    (tmp_path / "support").mkdir()
    command = ["npx", "cucumber-js", "tests/features/smoke/", "--tags", "@smoke", "--require", "support",
               "-f", "json:out.json", "--format=progress", "features/a.feature:3:7", "features/**/*.feature",
               "@rerun.txt"]
    kept, removed = cucumber.strip_paths("js", command, str(tmp_path))
    assert kept == ["npx", "cucumber-js", "--tags", "@smoke", "--require", "support", "-f", "json:out.json",
                    "--format=progress"]
    assert removed == ["tests/features/smoke/", "features/a.feature:3:7", "features/**/*.feature", "@rerun.txt"]


def test_ruby_and_jvm_paths_are_left_out_too(tmp_path):
    assert cucumber.strip_paths("ruby", ["bundle", "exec", "cucumber", "features/pay.feature", "--tags", "@x"],
                                str(tmp_path)) == (["bundle", "exec", "cucumber", "--tags", "@x"],
                                                   ["features/pay.feature"])
    assert cucumber.strip_paths("jvm", ["mvn", "test", "-Dcucumber.features=src/test/resources/features"],
                                str(tmp_path)) == (["mvn", "test"], ["-Dcucumber.features=src/test/resources/features"])


def test_a_command_without_a_visible_runner_is_left_as_it_is(tmp_path):
    assert cucumber.strip_paths("js", ["npm", "run", "bdd", "--"], str(tmp_path)) == (["npm", "run", "bdd", "--"], [])


def test_jvm_and_ruby_get_their_own_arguments_with_forward_slashes():
    report = PureWindowsPath(r"C:\work\.qeos-impact\ab12\stage-1.json")
    rerun = PureWindowsPath(r"C:\work\.qeos-impact\ab12\@stage-1.txt")
    assert cucumber.dry_run_arguments("js") == ["--dry-run"]
    assert cucumber.dry_run_arguments("ruby") == ["--dry-run"]
    assert cucumber.dry_run_arguments("jvm") == ["-Dcucumber.execution.dry-run=true"]
    assert cucumber.report_arguments("ruby", report, "C:/work") == ["--format", "json", "--out",
                                                                    "C:/work/.qeos-impact/ab12/stage-1.json"]
    assert cucumber.report_arguments("jvm", report, "C:/work") == [
        "-Dcucumber.plugin=json:C:/work/.qeos-impact/ab12/stage-1.json"]
    assert cucumber.rerun_argument("ruby", rerun, "C:/work") == "@C:/work/.qeos-impact/ab12/@stage-1.txt"
    assert cucumber.rerun_argument("jvm", rerun, "C:/work") == "-Dcucumber.features=@C:/work/.qeos-impact/ab12/@stage-1.txt"


def test_cucumber_js_gets_relative_paths_so_no_drive_colon_reaches_it(tmp_path):
    """cucumber-js 12 reads a rerun file only from a relative path to a file named @…, and warns about the colons
    of `json:C:/…` (plan Ruling 21; seen on 12.6.0)."""
    rerun = tmp_path / ".qeos-impact" / "ab12" / "@stage-1.txt"
    report = tmp_path / ".qeos-impact" / "ab12" / "stage-1.json"
    assert cucumber.rerun_argument("js", rerun, str(tmp_path)) == ".qeos-impact/ab12/@stage-1.txt"
    assert cucumber.report_arguments("js", report, str(tmp_path)) == ["--format",
                                                                      "json:.qeos-impact/ab12/stage-1.json"]


DRY_RUN = [
    {"uri": "features\\pay.feature", "name": "Pay", "elements": [
        {"type": "background", "name": "", "line": 3, "steps": []},
        {"type": "scenario", "name": "Pays with card", "line": 4, "steps": []},
        {"type": "scenario", "name": "Pays 10", "line": 12, "steps": []},
        {"type": "scenario", "name": "Pays 20", "line": 13, "steps": []},
        {"type": "scenario", "name": "", "line": 20, "steps": []}]},
    {"uri": "classpath:features/cart.feature", "name": "Cart", "elements": [
        {"type": "scenario", "name": " Adds ", "line": 3, "steps": []}]},
    {"uri": "features/empty.feature", "name": "No elements key"},
]


def test_a_dry_run_report_lists_scenarios_and_outline_rows_with_forward_slashes(tmp_path):
    report = tmp_path / "discovery.json"
    report.write_text(json.dumps(DRY_RUN), encoding="utf-8")
    assert cucumber.read_scenarios(report) == [
        Scenario("Pay", "features/pay.feature", "Pays with card", 4),
        Scenario("Pay", "features/pay.feature", "Pays 10", 12),
        Scenario("Pay", "features/pay.feature", "Pays 20", 13),
        Scenario("Pay", "features/pay.feature", "", 20),  # unnamed: kept, so it still runs in a stage
        Scenario("Cart", "classpath:features/cart.feature", "Adds", 3),
    ]


@pytest.mark.parametrize("element", [
    {"type": "scenario", "name": "No line", "steps": []},
    {"type": "scenario", "name": "Bad line", "line": True, "steps": []},
    {"type": "scenario", "name": "Zero line", "line": 0, "steps": []},
])
def test_a_scenario_without_a_usable_line_makes_the_report_incomplete(tmp_path, element):
    """It could go in no rerun file, so it would run in neither stage: run-impact must not plan with it."""
    report = tmp_path / "discovery.json"
    report.write_text(json.dumps([{**DRY_RUN[0], "elements": [*DRY_RUN[0]["elements"], element]}]), encoding="utf-8")
    with pytest.raises(cucumber.Incomplete, match="listed 5 scenario.s., of which 1 without a line"):
        cucumber.read_scenarios(report)


def test_an_unnamed_scenario_stays_out_of_an_upload():
    """The upload parser still skips it (no name, no test): only discovery keeps it."""
    from qeos_collector import formats
    from qeos_collector.junit import ParsedFile

    parsed = ParsedFile(path="x")
    formats._cucumber_feature(DRY_RUN[0], parsed)
    assert [row["name"] for row in parsed.results] == ["Pays with card", "Pays 10", "Pays 20"]
    assert parsed.unnamed == 1


def test_an_unnamed_scenario_is_never_suggested():
    scenarios = [Scenario("Pay", "features/pay.feature", "", 20), Scenario("Pay", "features/pay.feature", "Pays", 4)]
    first, rest, _missing = cucumber.split([{"class_name": "features/pay.feature", "name": ""},
                                            {"class_name": "features/pay.feature", "name": "Pays"}], scenarios)
    assert ([s.line for s in first], [s.line for s in rest]) == ([4], [20])


def test_a_jvm_command_keeps_its_own_plugins():
    report = PureWindowsPath(r"C:\work\.qeos-impact\ab12\stage-1.json")
    assert cucumber.with_report("jvm", ["mvn", "test", "-Dcucumber.plugin=pretty, html:out.html"], report, "C:/work") == [
        "mvn", "test", "-Dcucumber.plugin=pretty, html:out.html,json:C:/work/.qeos-impact/ab12/stage-1.json"]
    assert cucumber.with_report("jvm", ["mvn", "test", "-Dcucumber.plugin="], report, "C:/work") == [
        "mvn", "test", "-Dcucumber.plugin=json:C:/work/.qeos-impact/ab12/stage-1.json"]
    assert cucumber.with_report("jvm", ["mvn", "test"], report, "C:/work") == [
        "mvn", "test", "-Dcucumber.plugin=json:C:/work/.qeos-impact/ab12/stage-1.json"]
    assert cucumber.with_report("ruby", ["cucumber"], report, "C:/work") == [
        "cucumber", "--format", "json", "--out", "C:/work/.qeos-impact/ab12/stage-1.json"]


def test_scenarios_are_read_by_the_upload_parser(tmp_path, monkeypatch):
    """One Cucumber JSON parser (plan Ruling: no second parser): what the upload parser sees is what discovery sees."""
    from qeos_collector import formats

    report = tmp_path / "discovery.json"
    report.write_text(json.dumps(DRY_RUN), encoding="utf-8")
    real = formats._cucumber_feature

    def renamed(feature, parsed, lines=None):
        real({**feature, "name": "Renamed"}, parsed, lines)

    monkeypatch.setattr(formats, "_cucumber_feature", renamed)
    assert {s.feature for s in cucumber.read_scenarios(report)} == {"Renamed"}


def test_a_missing_or_broken_report_raises(tmp_path):
    with pytest.raises(OSError):
        cucumber.read_scenarios(tmp_path / "none.json")
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        cucumber.read_scenarios(tmp_path / "bad.json")


def test_rerun_files_group_lines_by_file_and_end_lines_with_lf(tmp_path):
    scenarios = [Scenario("Pay", "features/pay.feature", "Pays 20", 13),
                 Scenario("Cart", "features/cart.feature", "Adds", 3),
                 Scenario("Pay", "features/pay.feature", "Pays with card", 4)]
    assert cucumber.rerun_text(scenarios) == "features/pay.feature:4:13\nfeatures/cart.feature:3\n"
    path = tmp_path / "@stage-1.txt"
    cucumber.write_rerun(path, scenarios)
    assert path.read_bytes() == b"features/pay.feature:4:13\nfeatures/cart.feature:3\n"


def test_the_plan_puts_every_scenario_in_exactly_one_stage():
    scenarios = [Scenario("Pay", "features/pay.feature", "Pays with card", 4),
                 Scenario("Pay", "features/pay.feature", "Pays 10", 12),
                 Scenario("Pay", "features/pay.feature", "Pays 10", 14),
                 Scenario("Cart", "features/cart.feature", "Adds", 3)]
    tests = [{"suite": "Pay", "class_name": "features/pay.feature", "name": "Pays 10"},
             {"suite": "Cart", "class_name": "features/cart.feature", "name": "Gone away"},
             {"suite": "api", "class_name": "PayTest", "name": "refunds"}]
    first, rest, missing = cucumber.split(tests, scenarios)
    assert [s.line for s in first] == [12, 14]  # an outline whose rows share the name: every row
    assert [s.location for s in rest] == ["features/pay.feature:4", "features/cart.feature:3"]
    assert [t["name"] for t in missing] == ["Gone away", "refunds"]
    assert {s.location for s in first} | {s.location for s in rest} == {s.location for s in scenarios}


def test_a_suggestion_matches_on_the_feature_uri_and_the_scenario_name():
    """class_name is the feature uri for Cucumber JSON uploads (checked on stored results); a renamed feature keeps its
    scenarios' history under the old suite, so the suite does not take part. Another file's scenario of the same name
    does not match."""
    scenarios = [Scenario("Payments", "features/pay.feature", "Pays 10", 12),
                 Scenario("Other", "features/other.feature", "Pays 10", 5)]
    first, rest, missing = cucumber.split([{"suite": "Pay", "class_name": "features/pay.feature",
                                            "name": "Pays 10"}], scenarios)
    assert ([s.location for s in first], [s.location for s in rest], missing) == (
        ["features/pay.feature:12"], ["features/other.feature:5"], [])


def test_a_long_name_matches_as_the_upload_stored_it():
    """The upload cuts class_name and name (formats._row); the suggestion carries the cut values."""
    long_name = "x" * 1200
    scenarios = [Scenario("Pay", "features/pay.feature", long_name, 4)]
    first, _rest, _missing = cucumber.split([{"class_name": "features/pay.feature", "name": long_name[:1000]}],
                                            scenarios)
    assert [s.line for s in first] == [4]
