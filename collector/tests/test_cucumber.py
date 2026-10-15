"""Cucumber JSON (cucumber-jvm/js/rb classic formatter) through the same
dispatcher: a feature's scenarios become results in the shared shape."""
import base64
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


def test_a_non_dict_match_gives_no_definition_and_the_text_as_pattern(tmp_path):
    for odd in ("x", ["a"], None, 3):
        entry = step("When ", "I search Lisbon", 5, "failed", "e")
        entry["match"] = odd
        got = parse_cucumber(tmp_path, steps=[entry])[0]["failed_step"]
        assert "definition" not in got and got["pattern"] == "When I search Lisbon", odd


def test_an_empty_argument_value_is_skipped(tmp_path):
    got = failed_step_of(tmp_path, "When ", "I search Porto", 5, "failed", "e", location="s.js:1",
                         arguments=[{"val": "", "offset": 3}, {"val": "Porto", "offset": 9}])
    assert got["pattern"] == "When I search {…}"


def test_non_ascii_text_with_arguments_becomes_a_pattern(tmp_path):
    got = failed_step_of(tmp_path, "Então ", "vejo São Paulo e Brasília", 5, "failed", "e", location="s.js:1",
                         arguments=[{"val": "São Paulo", "offset": 5}, {"val": "Brasília", "offset": 17}])
    assert got["pattern"] == "Então vejo {…} e {…}"


def test_utf16_offsets_after_an_emoji_still_give_the_pattern(tmp_path):
    # cucumber-jvm/js count offsets in UTF-16 code units: the emoji is two of them
    got = failed_step_of(tmp_path, "When ", "I send 😀 to Lisbon", 5, "failed", "e", location="s.js:1",
                         arguments=[{"val": "Lisbon", "offset": 13}])
    assert got["pattern"] == "When I send 😀 to {…}"


def test_offsets_that_fit_neither_unit_fall_back_to_the_text(tmp_path):
    got = failed_step_of(tmp_path, "When ", "I send 😀 to Lisbon", 5, "failed", "e", location="s.js:1",
                         arguments=[{"val": "Lisbon", "offset": 40}])
    assert got["pattern"] == "When I send 😀 to Lisbon"


# --- log (log values, spec 2026-10-14 §2.2) --------------------------------------------------------------------


def b64(data):
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def logging_step(keyword, name, *texts, media="text/x.cucumber.log+plain"):
    return {"keyword": keyword, "name": name, "line": 3, "result": {"status": "passed", "duration": 1},
            "embeddings": [{"data": b64(text), "mime_type": media} for text in texts]}


def log_of(tmp_path, steps, background=None, **element):
    elements = [{"type": "background", "keyword": "Background", "name": "", "steps": background}] if background else []
    elements.append({"type": "scenario", "keyword": "Scenario", "name": "Books a trip", "steps": steps, **element})
    parsed = parse_file(write(tmp_path, [{"uri": "features/book.feature", "name": "Booking", "elements": elements}]))
    return parsed.results[0].get("log")


def test_text_attachments_become_the_log_in_step_order_background_first(tmp_path):
    log = log_of(tmp_path,
                 [logging_step("When ", "I book", 'INFO [App] Trip id captured tripId="3960562"', "INFO [App] Paid"),
                  logging_step("Then ", "it confirms", "INFO [App] Confirmed")],
                 background=[logging_step("Given ", "I sign in", "INFO [Hooks] Signed in")])
    assert log == "\n".join(["INFO [Hooks] Signed in", 'INFO [App] Trip id captured tripId="3960562"',
                             "INFO [App] Paid", "INFO [App] Confirmed"])


def test_text_plain_counts_with_or_without_parameters(tmp_path):
    log = log_of(tmp_path, [logging_step("When ", "a", "one", media="text/plain"),
                            logging_step("When ", "b", "two", media="Text/Plain; charset=utf-8")])
    assert log == "one\ntwo"


def test_images_and_other_media_never_join_the_log(tmp_path):
    step = logging_step("When ", "a", "kept")
    step["embeddings"] += [{"data": b64(b"\x89PNG\r\n\x1a\n\x00\x00"), "mime_type": "image/png"},
                           {"data": b64('{"a": 1}'), "mime_type": "application/json"},
                           {"data": b64("<p>x</p>"), "mime_type": "text/html"}]
    assert log_of(tmp_path, [step]) == "kept"


def test_plain_text_data_is_kept_as_it_is(tmp_path):
    step = {"keyword": "When ", "name": "a", "result": {"status": "passed"},
            "embeddings": [{"data": 'INFO tripId="1" done', "mime_type": "text/plain"}]}
    assert log_of(tmp_path, [step]) == 'INFO tripId="1" done'


def test_invalid_utf8_in_an_attachment_is_replaced_not_fatal(tmp_path):
    step = {"keyword": "When ", "name": "a", "result": {"status": "passed"},
            "embeddings": [{"data": b64(b"trip \xff\xfe id"), "mime_type": "text/plain"}]}
    assert log_of(tmp_path, [step]) == "trip �� id"


def test_hook_steps_and_cucumber_jvm_scenario_hooks_count(tmp_path):
    hook = logging_step("Before", "", "INFO [Hooks] Started")  # cucumber-js: a hidden hook step
    hook["hidden"] = True
    jvm = lambda text: [{"result": {"status": "passed"}, "embeddings": [{"data": b64(text), "mime_type": "text/plain"}]}]
    log = log_of(tmp_path, [hook, logging_step("When ", "a", "INFO step")], before=jvm("jvm before"),
                 after=jvm("jvm after"))
    assert log == "jvm before\nINFO [Hooks] Started\nINFO step\njvm after"


def test_attachments_under_the_newer_names_count(tmp_path):
    step = {"keyword": "When ", "name": "a", "result": {"status": "passed"},
            "attachments": [{"body": "from attachments", "media_type": "text/x.cucumber.log+plain"},
                            {"data": b64("camel case"), "mediaType": "text/plain"}]}
    assert log_of(tmp_path, [step]) == "from attachments\ncamel case"


def test_a_failed_scenario_keeps_its_log_and_its_failed_step(tmp_path):
    failing = logging_step("When ", "I pay", "INFO [App] Paying")
    failing["result"] = {"status": "failed", "error_message": "boom"}
    parsed = parse_file(write(tmp_path, [{"uri": "f.feature", "name": "F", "elements": [
        {"type": "scenario", "name": "Pays", "steps": [failing]}]}]))
    row = parsed.results[0]
    assert row["status"] == "failed" and row["log"] == "INFO [App] Paying" and row["failed_step"]["text"] == "When I pay"


def test_the_log_is_cut_to_64_kb(tmp_path):
    assert log_of(tmp_path, [logging_step("When ", "a", "é" * 40_000)]) == "é" * 32_768


def test_no_text_means_no_log(tmp_path):
    assert log_of(tmp_path, [{"keyword": "When ", "name": "a", "result": {"status": "passed"}}]) is None
    assert log_of(tmp_path, [logging_step("When ", "a", "  \n ")]) is None


@pytest.mark.parametrize("embeddings", [
    None, "text", {"data": "x", "mime_type": "text/plain"}, [None, 3, "x"],
    [{"data": 5, "mime_type": "text/plain"}], [{"data": "eA=="}], [{"data": "", "mime_type": "text/plain"}],
    [{"data": "eA==", "mime_type": 7}],
])
def test_odd_attachment_shapes_are_skipped(tmp_path, embeddings):
    step = {"keyword": "When ", "name": "a", "result": {"status": "passed"}, "embeddings": embeddings}
    assert log_of(tmp_path, [step]) is None
