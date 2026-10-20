"""Cucumber JSON (cucumber-jvm/js/rb classic formatter) through the same
dispatcher: a feature's scenarios become results in the shared shape."""
import base64
import hashlib
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


def test_a_passed_scenario_has_no_failed_step(tmp_path):
    assert "failed_step" not in parse_cucumber(tmp_path, steps=[step("Given ", "a", 1, "passed")])[0]


# --- the step that stopped a skipped scenario (same field, same shape) ----------------------------------

@pytest.mark.parametrize("status, reason", [
    ("undefined", "Undefined step"),
    ("pending", "Pending step"),
    ("ambiguous", "Ambiguous step"),
])
def test_a_skipped_scenario_names_the_step_that_stopped_it(tmp_path, status, reason):
    rows = parse_cucumber(tmp_path, steps=[step("Given ", "a user", 4, "passed"),
                                           step("When ", "I search Lisbon", 5, status),
                                           step("Then ", "I see results", 6, "skipped")])
    assert rows[0]["status"] == "skipped"
    assert rows[0]["failed_step"] == {"text": "When I search Lisbon", "line": 5, "pattern": "When I search Lisbon"}
    assert rows[0]["message"] == reason
    assert rows[0]["details"] == "When I search Lisbon\n" + reason


def test_a_scenario_skipped_before_any_step_ran_names_its_first_step(tmp_path):
    """A Before hook skipped it: every step is skipped, so the first one is where it stopped."""
    rows = parse_cucumber(tmp_path, steps=[step("Given ", "a user", 4, "skipped"), step("When ", "x", 5, "skipped")])
    assert rows[0]["status"] == "skipped"
    assert rows[0]["failed_step"] == {"text": "Given a user", "line": 4, "pattern": "Given a user"}
    assert rows[0]["message"] == "Skipped"


def test_the_stopping_step_keeps_cucumbers_own_message_in_details(tmp_path):
    rows = parse_cucumber(tmp_path, steps=[step("When ", "x", 5, "pending", "TODO: implement me")])
    assert rows[0]["message"] == "Pending step"
    assert rows[0]["details"] == "When x\nPending step\nTODO: implement me"


BOOKING_NOTE = ("BOOKING_ERROR:[Checkout.bookAndFinalize] A known booking error modal blocked the booking, so the "
                "booking was never confirmed and the scenario was skipped. Supplier response: The selected rate "
                "changed from 113.87 USD to 133.52 USD. Please review and change selection")


def test_what_the_stopping_step_attached_is_the_reason(tmp_path):
    """The test wrote why it stopped as a text attachment on the step (a text/plain note): that is the message,
    whole, so the reader sees why, not only "Pending step"."""
    stopped = step("And ", "I complete the booking", 22, "pending")
    stopped["embeddings"] = [{"data": b64(BOOKING_NOTE), "mime_type": "text/plain"}]
    rows = parse_cucumber(tmp_path, steps=[step("Given ", "a trip", 20, "passed"), stopped,
                                           step("Then ", "the booking confirms", 23, "skipped")])
    assert rows[0]["status"] == "skipped"
    assert rows[0]["message"] == BOOKING_NOTE
    assert rows[0]["details"] == "And I complete the booking\nPending step\n" + BOOKING_NOTE
    assert rows[0]["failed_step"]["text"] == "And I complete the booking"
    assert rows[0]["log"] == BOOKING_NOTE


def test_several_notes_on_the_stopping_step_join_and_images_do_not_count(tmp_path):
    stopped = step("When ", "x", 5, "skipped")
    stopped["embeddings"] = [{"data": b64("first line "), "mime_type": "text/x.cucumber.log+plain"},
                             {"data": b64(b"\x89PNG"), "mime_type": "image/png"},
                             {"data": b64("second"), "mime_type": "text/plain"}]
    rows = parse_cucumber(tmp_path, steps=[stopped])
    assert rows[0]["message"] == "first line\nsecond"


def test_a_blank_note_on_the_stopping_step_falls_back_to_the_status(tmp_path):
    stopped = step("When ", "x", 5, "undefined")
    stopped["embeddings"] = [{"data": b64("   \n"), "mime_type": "text/plain"}]
    assert parse_cucumber(tmp_path, steps=[stopped])[0]["message"] == "Undefined step"


def test_a_failed_step_keeps_its_error_as_the_message_even_with_a_note(tmp_path):
    failed = step("When ", "x", 5, "failed", "AssertionError: nope")
    failed["embeddings"] = [{"data": b64("some note"), "mime_type": "text/plain"}]
    assert parse_cucumber(tmp_path, steps=[failed])[0]["message"] == "AssertionError: nope"


def test_a_skipped_scenario_without_steps_has_no_step(tmp_path):
    rows = parse_cucumber(tmp_path, steps=[])
    assert rows[0]["status"] == "skipped" and "failed_step" not in rows[0] and "message" not in rows[0]


def test_the_stopping_step_carries_its_definition_and_pattern(tmp_path):
    entry = {"keyword": "When ", "name": "I search Lisbon", "line": 5, "result": {"status": "pending"},
             "match": {"location": "steps/search.js:12", "arguments": [{"val": "Lisbon", "offset": 9}]}}
    rows = parse_cucumber(tmp_path, steps=[entry])
    assert rows[0]["failed_step"] == {"text": "When I search Lisbon", "line": 5, "definition": "steps/search.js:12",
                                      "pattern": "When I search {…}"}


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


# --- contentEncoding (spec 2026-10-15 §4.2) ---------------------------------------------------------------------


def encoded_step(data, encoding, key="contentEncoding"):
    return {"keyword": "When ", "name": "a", "result": {"status": "passed"},
            "attachments": [{"body": data, "media_type": "text/plain", key: encoding}]}


def test_identity_keeps_a_base64_looking_line_as_text(tmp_path):
    assert log_of(tmp_path, [encoded_step("Finished", "IDENTITY")]) == "Finished"


def test_base64_encoding_decodes(tmp_path):
    assert log_of(tmp_path, [encoded_step(b64('tripId="1"'), "BASE64")]) == 'tripId="1"'


def test_the_snake_case_spelling_and_lowercase_count(tmp_path):
    assert log_of(tmp_path, [encoded_step("Done", "identity", key="content_encoding")]) == "Done"


def test_an_unknown_encoding_is_treated_as_absent(tmp_path):
    assert log_of(tmp_path, [encoded_step(b64("guessed"), "GZIP")]) == "guessed"


def test_invalid_base64_under_base64_encoding_is_kept_as_text(tmp_path):
    assert log_of(tmp_path, [encoded_step("not base64!", "BASE64")]) == "not base64!"


# --- step screenshots (spec 2026-10-19 §5.2) -------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 16
PNG_SHA = hashlib.sha256(PNG).hexdigest()


def image_on(entry, data=PNG, media="image/png"):
    entry.setdefault("embeddings", []).append({"data": b64(data), "mime_type": media})
    return entry


def hook(keyword, status="passed", *images):
    entry = {"keyword": keyword, "hidden": True, "result": {"status": status}}
    for data in images:
        image_on(entry, data)
    return entry


def shots_of(tmp_path, steps, background=None, **element):
    elements = [{"type": "background", "name": "", "steps": background}] if background else []
    elements.append({"type": "scenario", "name": "S", "steps": steps, **element})
    parsed = parse_file(write(tmp_path, [{"uri": "f.feature", "name": "F", "elements": elements}]))
    return parsed.results[0], parsed


def test_image_on_step_gets_that_step(tmp_path):
    row, _ = shots_of(tmp_path, [step("Given ", "a user", 4, "passed"),
                                 image_on(step("When ", "I search", 5, "passed"))],
                      background=[image_on(step("Given ", "logged in", 3, "passed"), b"bg")])
    assert row["screenshots"] == [
        {"sha256": hashlib.sha256(b"bg").hexdigest(), "media_type": "image/png", "step_text": "Given logged in",
         "step_line": 3},
        {"sha256": PNG_SHA, "media_type": "image/png", "step_text": "When I search", "step_line": 5},
    ]
    assert row["_images"] == {PNG_SHA: ("image/png", PNG), hashlib.sha256(b"bg").hexdigest(): ("image/png", b"bg")}


def test_after_hook_image_goes_to_last_step_that_ran(tmp_path):
    row, _ = shots_of(tmp_path, [step("Given ", "a", 1, "passed"), step("When ", "b", 2, "passed"),
                                 step("Then ", "c", 3, "skipped"), hook("After", "passed", PNG)])
    assert row["screenshots"] == [{"sha256": PNG_SHA, "media_type": "image/png", "step_text": "When b",
                                   "step_line": 2, "hook": "after"}]


def test_after_hook_image_on_failed_scenario_goes_to_failed_step(tmp_path):
    row, _ = shots_of(tmp_path, [step("Given ", "a", 1, "passed"), step("When ", "b", 2, "failed", "boom"),
                                 step("Then ", "c", 3, "skipped"), hook("After", "passed", PNG)])
    assert row["screenshots"][0]["step_text"] == "When b"
    assert row["screenshots"][0]["hook"] == "after"


def test_jvm_after_array_image(tmp_path):
    row, _ = shots_of(tmp_path, [step("Given ", "a", 1, "passed"), step("When ", "b", 2, "passed")],
                      after=[image_on({"result": {"status": "passed"}})])
    assert row["screenshots"] == [{"sha256": PNG_SHA, "media_type": "image/png", "step_text": "When b",
                                   "step_line": 2, "hook": "after"}]


def test_before_hook_image_goes_to_first_step(tmp_path):
    row, _ = shots_of(tmp_path, [hook("Before", "passed", PNG), step("Given ", "a", 1, "passed"),
                                 step("When ", "b", 2, "passed")])
    assert row["screenshots"] == [{"sha256": PNG_SHA, "media_type": "image/png", "step_text": "Given a",
                                   "step_line": 1, "hook": "before"}]


def test_jvm_before_array_image_goes_to_first_step(tmp_path):
    row, _ = shots_of(tmp_path, [step("Given ", "a", 1, "passed")], before=[image_on({"result": {}})])
    assert row["screenshots"][0]["step_text"] == "Given a"
    assert row["screenshots"][0]["hook"] == "before"


def test_all_skipped_with_hook_images_never_lands_on_hook_entry(tmp_path):
    row, _ = shots_of(tmp_path, [hook("Before", "passed", b"b"), step("Given ", "a", 1, "skipped"),
                                 step("Then ", "z", 2, "skipped"), hook("After", "passed", b"a")])
    assert [(s["step_text"], s["hook"]) for s in row["screenshots"]] == [("Given a", "before"), ("Then z", "after")]


def test_hook_images_without_real_steps_are_dropped(tmp_path):
    row, _ = shots_of(tmp_path, [hook("Before", "passed", PNG)])
    assert "screenshots" not in row and "_images" not in row


def test_image_over_5mb_skipped(tmp_path):
    big = b"\x00" * (5 * 1024 * 1024 + 1)
    row, parsed = shots_of(tmp_path, [image_on(image_on(step("Given ", "a", 1, "passed"), big), PNG)])
    assert [s["sha256"] for s in row["screenshots"]] == [PNG_SHA]
    assert len([w for w in parsed.warnings if "screenshot" in w]) == 1
    assert "1 screenshot" in parsed.warnings[-1]


def test_51st_image_skipped(tmp_path):
    entry = step("Given ", "a", 1, "passed")
    for number in range(52):
        image_on(entry, b"img%d" % number)
    row, parsed = shots_of(tmp_path, [entry])
    assert len(row["screenshots"]) == 50 and len(row["_images"]) == 50
    assert [w for w in parsed.warnings if "2 screenshot" in w]


def test_text_attachments_still_become_log(tmp_path):
    entry = image_on(logging_step("When ", "a", "kept"))
    row, _ = shots_of(tmp_path, [entry])
    assert row["log"] == "kept" and len(row["screenshots"]) == 1


def test_non_image_and_bad_base64_are_ignored(tmp_path):
    entry = step("When ", "a", 1, "passed")
    entry["embeddings"] = [{"data": "!!not base64!!", "mime_type": "image/png"},
                           {"data": b64("x"), "mime_type": "image/gif"},
                           {"data": PNG.decode("latin-1"), "mime_type": "image/png", "contentEncoding": "IDENTITY"}]
    row, _ = shots_of(tmp_path, [entry])
    assert "screenshots" not in row


def test_message_format_field_names(tmp_path):
    entry = step("When ", "a", 1, "passed")
    entry["attachments"] = [{"body": b64(PNG), "mediaType": "image/jpeg; x=1"}]
    row, _ = shots_of(tmp_path, [entry])
    assert row["screenshots"][0]["media_type"] == "image/jpeg"


def test_payload_does_not_contain_image_bytes(tmp_path):
    from qeos_collector.payload import build_parts
    row, _ = shots_of(tmp_path, [image_on(step("Given ", "a", 1, "passed"))])
    parts = build_parts({"ci_provider": "x"}, [row], "key")
    body = json.loads(parts[0].body)
    assert "_images" not in body["results"][0]
    assert body["results"][0]["screenshots"][0]["sha256"] == PNG_SHA
    assert b64(PNG).encode() not in parts[0].body
    assert "_images" in row  # the row itself keeps them for the upload
