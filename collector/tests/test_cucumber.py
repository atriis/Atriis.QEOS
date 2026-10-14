"""Cucumber JSON (cucumber-jvm/js/rb classic formatter) through the same
dispatcher: a feature's scenarios become results in the shared shape."""
import json
from datetime import datetime, timezone

import pytest

from qeos_collector.formats import parse_file


def write(tmp_path, data, name="cucumber.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def by_name(parsed):
    return {r["name"]: r for r in parsed.results}


CUCUMBER = [
    {
        "uri": "features/checkout.feature",
        "name": "Checkout",
        "keyword": "Feature",
        "elements": [
            {
                "type": "background",
                "keyword": "Background",
                "name": "Signed in",
                "steps": [
                    {"keyword": "Given ", "name": "a signed-in shopper",
                     "result": {"status": "passed", "duration": 50_000_000}},
                ],
            },
            {
                "type": "scenario",
                "keyword": "Scenario",
                "name": "Pays with a stored card",
                "start_timestamp": "2026-10-01T10:00:00.000Z",
                "steps": [
                    {"keyword": "When ", "name": "the shopper pays",
                     "result": {"status": "passed", "duration": 1_400_000_000}},
                    {"keyword": "Then ", "name": "the order confirms",
                     "result": {"status": "passed", "duration": 50_000_000}},
                ],
            },
            {
                "type": "scenario",
                "keyword": "Scenario",
                "name": "Refunds",
                "steps": [
                    {"keyword": "When ", "name": "the shopper refunds",
                     "result": {"status": "failed", "duration": 200_000_000,
                                "error_message": "AssertionError: no refund button"}},
                    {"keyword": "Then ", "name": "the money returns",
                     "result": {"status": "skipped"}},
                ],
            },
            {
                "type": "scenario",
                "keyword": "Scenario",
                "name": "Gift wrap",
                "steps": [
                    {"keyword": "When ", "name": "the shopper wraps",
                     "result": {"status": "undefined"}},
                ],
            },
        ],
    },
]


def test_cucumber_scenarios_become_results(tmp_path):
    parsed = parse_file(write(tmp_path, CUCUMBER))
    assert not parsed.skipped
    results = by_name(parsed)
    assert "Signed in" not in results  # background steps fold into the scenarios

    pays = results["Pays with a stored card"]
    assert pays["status"] == "passed"
    assert pays["suite"] == "Checkout"
    assert pays["class_name"] == "features/checkout.feature"
    # background 50ms + steps 1400ms + 50ms
    assert pays["duration_ms"] == 1500

    refunds = results["Refunds"]
    assert refunds["status"] == "failed"
    assert refunds["message"] == "AssertionError: no refund button"
    assert "the shopper refunds" in refunds["details"]

    assert results["Gift wrap"]["status"] == "skipped"
    assert parsed.suite_timestamps == [datetime(2026, 10, 1, 10, tzinfo=timezone.utc)]


def test_non_cucumber_json_is_skipped_with_a_reason(tmp_path):
    parsed = parse_file(write(tmp_path, {"not": "cucumber"}))
    assert parsed.skipped
    assert "not Cucumber JSON" in parsed.warnings[0]


def test_broken_json_is_skipped(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("[{", encoding="utf-8")
    parsed = parse_file(str(path))
    assert parsed.skipped


def test_a_windows_uri_is_reported_with_forward_slashes(tmp_path):
    """Results uploaded from Windows must carry the same key as those from Linux and the Gherkin import."""
    feature = {**CUCUMBER[0], "uri": "tests\\features\\a.feature"}
    parsed = parse_file(write(tmp_path, [feature]))
    assert {r["class_name"] for r in parsed.results} == {"tests/features/a.feature"}


# --- failed_step ---------------------------------------------------------------

def step(keyword, name, line, status, error=None):
    result = {"status": status}
    if error is not None:
        result["error_message"] = error
    entry = {"keyword": keyword, "name": name, "result": result}
    if line is not None:
        entry["line"] = line
    return entry


def parse_cucumber(tmp_path, steps, background=None):
    elements = []
    if background is not None:
        elements.append({"type": "background", "steps": background})
    elements.append({"type": "scenario", "name": "S", "steps": steps})
    return parse_file(write(tmp_path, [{"uri": "f.feature", "name": "F", "elements": elements}])).results


def test_failed_step_carries_text_and_line(tmp_path):
    rows = parse_cucumber(tmp_path, steps=[step("Given ", "a user", 4, "passed"),
                                           step("When ", "I search Lisbon", 5, "failed", "boom")])
    assert rows[0]["failed_step"] == {"text": "When I search Lisbon", "line": 5, "pattern": "When I search Lisbon"}


def test_background_step_failure_keeps_its_own_line(tmp_path):
    rows = parse_cucumber(tmp_path, background=[step("Given ", "logged in", 3, "failed", "nope")],
                          steps=[step("When ", "x", 7, "skipped")])
    assert rows[0]["failed_step"] == {"text": "Given logged in", "line": 3, "pattern": "Given logged in"}


def test_passed_and_skipped_scenarios_have_no_failed_step(tmp_path):
    assert "failed_step" not in parse_cucumber(tmp_path, steps=[step("Given ", "a", 1, "passed")])[0]
    assert "failed_step" not in parse_cucumber(tmp_path, steps=[step("Given ", "a", 1, "pending")])[0]


def test_missing_line_keeps_the_text_and_long_text_is_cut(tmp_path):
    rows = parse_cucumber(tmp_path, steps=[step("When ", "y" * 2000, None, "failed", "e")])
    assert rows[0]["failed_step"]["text"] == ("When " + "y" * 2000)[:1000] and "line" not in rows[0]["failed_step"] \
        and rows[0]["failed_step"]["pattern"] == ("When " + "y" * 2000)[:1000]


def test_junit_results_have_no_failed_step():
    from pathlib import Path
    parsed = parse_file(str(Path(__file__).parent / "fixtures" / "pytest.xml"))
    assert parsed.results and all("failed_step" not in r for r in parsed.results)


def test_whitespace_only_step_name_gives_no_failed_step(tmp_path):
    rows = parse_cucumber(tmp_path, steps=[step("", " ", 2, "failed", "e")])
    assert "failed_step" not in rows[0]


def test_implausible_line_numbers_are_dropped_but_text_is_kept(tmp_path):
    for bad in (True, 0, 2_000_000, 3.5):
        rows = parse_cucumber(tmp_path, steps=[step("When ", "x", bad, "failed", "e")])
        assert rows[0]["failed_step"] == {"text": "When x", "pattern": "When x"}, bad


def test_outline_row_failure_reports_the_template_line(tmp_path):
    # cucumber expands an outline row into a scenario whose steps report the template step's line
    elements = [{"type": "scenario", "keyword": "Scenario Outline", "name": "S row 2", "line": 12,
                 "steps": [step("When ", "I pay 5", 9, "failed", "e")]}]
    rows = parse_file(write(tmp_path, [{"uri": "f.feature", "name": "F", "elements": elements}])).results
    assert rows[0]["failed_step"] == {"text": "When I pay 5", "line": 9, "pattern": "When I pay 5"}


def matched(keyword, name, line, status, error=None, location=None, arguments=None):
    entry = step(keyword, name, line, status, error)
    match = {}
    if location is not None:
        match["location"] = location
    if arguments is not None:
        match["arguments"] = arguments
    entry["match"] = match
    return entry


def failed_step_of(tmp_path, *args, **kwargs):
    return parse_cucumber(tmp_path, steps=[matched(*args, **kwargs)])[0]["failed_step"]


def test_cucumber_js_reports_the_definition_without_arguments(tmp_path):
    # cucumber-js's json formatter: match.location only
    got = failed_step_of(tmp_path, "When ", "I search Lisbon", 5, "failed", "boom",
                         location="features/step_definitions/search.js:12")
    assert got == {"text": "When I search Lisbon", "line": 5,
                   "definition": "features/step_definitions/search.js:12", "pattern": "When I search Lisbon"}


def test_cucumber_jvm_arguments_become_placeholders(tmp_path):
    got = failed_step_of(tmp_path, "When ", "I search Lisbon in 2 days", 5, "failed", "boom",
                         location="com.example.SearchSteps.search(java.lang.String,int)",
                         arguments=[{"val": "Lisbon", "offset": 9}, {"val": "2", "offset": 19}])
    assert got["definition"] == "com.example.SearchSteps.search(java.lang.String,int)"
    assert got["pattern"] == "When I search {…} in {…} days"


def test_ruby_arguments_in_any_order_become_placeholders(tmp_path):
    got = failed_step_of(tmp_path, "Then ", 'I see "Porto" first', 8, "failed", "e",
                         location="features/step_definitions/search_steps.rb:3",
                         arguments=[{"offset": 6, "val": '"Porto"'}])
    assert got["pattern"] == "Then I see {…} first"


def test_an_optional_group_that_matched_nothing_is_skipped(tmp_path):
    got = failed_step_of(tmp_path, "When ", "I search Porto", 5, "failed", "e", location="s.js:1",
                         arguments=[{"val": None, "offset": None}, {"val": "Porto", "offset": 9}])
    assert got["pattern"] == "When I search {…}"


def test_no_match_gives_no_definition_and_the_text_as_pattern(tmp_path):
    rows = parse_cucumber(tmp_path, steps=[step("When ", "I search Lisbon", 5, "failed", "boom")])
    assert "definition" not in rows[0]["failed_step"] and rows[0]["failed_step"]["pattern"] == "When I search Lisbon"


def test_a_blank_or_odd_location_gives_no_definition(tmp_path):
    for location in ("", "   ", 12, ["a"]):
        got = failed_step_of(tmp_path, "When ", "x", 5, "failed", "e", location=location)
        assert "definition" not in got, location


def test_a_long_location_is_cut_to_500(tmp_path):
    got = failed_step_of(tmp_path, "When ", "x", 5, "failed", "e", location="d" * 800)
    assert got["definition"] == "d" * 500


@pytest.mark.parametrize("arguments", [
    [{"val": "Lisbon", "offset": 3}],               # does not fit the text there
    [{"val": "Lisbon", "offset": -1}],
    [{"val": "Lisbon", "offset": True}],
    [{"val": "Lisbon", "offset": "9"}],
    [{"val": 7, "offset": 9}],
    ["Lisbon"],
    [{"val": "search Lisbon", "offset": 2}, {"val": "Lisbon", "offset": 9}],  # overlapping
    {"val": "Lisbon", "offset": 9},                 # not a list
])
def test_bad_arguments_leave_the_text_as_pattern(tmp_path, arguments):
    got = failed_step_of(tmp_path, "When ", "I search Lisbon", 5, "failed", "e", location="s.js:1", arguments=arguments)
    assert got["pattern"] == "When I search Lisbon"


def test_a_long_pattern_is_cut_to_1000(tmp_path):
    name = "I type " + "y" * 2000
    got = failed_step_of(tmp_path, "When ", name, 5, "failed", "e", location="s.js:1",
                         arguments=[{"val": "y" * 2000, "offset": 7}])
    assert got["pattern"] == "When I type {…}"
    long = failed_step_of(tmp_path, "When ", name, 5, "failed", "e", location="s.js:1", arguments=[])
    assert len(long["pattern"]) == 1000
