from datetime import datetime, timezone
from pathlib import Path

import pytest

from qeos_collector import junit
from qeos_collector.junit import parse_file

FIXTURES = Path(__file__).parent / "fixtures"


def write(tmp_path, xml, name="report.xml", encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(xml.encode(encoding))
    return str(path)


def by_name(parsed):
    return {r["name"]: r for r in parsed.results}


def test_pytest_report():
    parsed = parse_file(str(FIXTURES / "pytest.xml"))

    assert not parsed.skipped and parsed.warnings == []
    assert [r["status"] for r in parsed.results] == ["passed", "failed", "skipped", "errored"]
    results = by_name(parsed)
    assert results["test_add"] == {
        "suite": "pytest", "class_name": "tests.test_math", "name": "test_add",
        "status": "passed", "duration_ms": 1,
    }
    assert results["test_div"]["message"] == "assert 1 == 2"
    assert "E       assert 1 == 2" in results["test_div"]["details"]
    assert results["test_skip"]["message"] == "not on CI"
    assert results["test_conn"]["message"] == 'failed on setup with "ConnectionError"'
    assert results["test_conn"]["duration_ms"] == 500
    assert parsed.suite_timestamps == [datetime(2026, 9, 29, 9, 0, 0, 123456, tzinfo=timezone.utc)]
    assert parsed.suite_seconds == pytest.approx(1.234)


def test_surefire_report_ignores_rerun_and_flaky_elements():
    parsed = parse_file(str(FIXTURES / "surefire.xml"))

    results = by_name(parsed)
    assert results["addsItem"]["status"] == "passed"
    # Failed once, passed on a rerun: the final outcome is a pass
    assert results["flakyCheckout"]["status"] == "passed"
    assert "message" not in results["flakyCheckout"]
    assert results["brokenTotal"]["status"] == "failed"
    assert results["brokenTotal"]["message"] == "expected 3 but was 2"
    assert results["brokenTotal"]["details"].startswith("org.opentest4j.AssertionFailedError")
    assert "RERUN" not in results["brokenTotal"]["details"]
    assert {r["suite"] for r in parsed.results} == {"com.example.CartTest"}
    assert parsed.suite_seconds == pytest.approx(1200.5)
    assert parsed.suite_timestamps == []


def test_playwright_report():
    parsed = parse_file(str(FIXTURES / "playwright.xml"))

    results = by_name(parsed)
    assert results["login › shows the form"]["status"] == "passed"
    bad = results["login › rejects a bad password"]
    assert bad["status"] == "failed"
    assert bad["duration_ms"] == 2300
    assert bad["message"] == "login.spec.ts:12:5 rejects a bad password"
    assert "toBeVisible" in bad["details"]
    assert parsed.suite_timestamps == [datetime(2026, 9, 29, 9, 58, tzinfo=timezone.utc)]


def test_cucumber_js_report():
    parsed = parse_file(str(FIXTURES / "cucumber.xml"))

    assert [(r["class_name"], r["name"], r["status"]) for r in parsed.results] == [
        ("Checkout", "Pay with card", "passed"),
        ("Checkout", "Pay with voucher", "failed"),
        ("Checkout", "Pay later", "skipped"),
    ]
    results = by_name(parsed)
    assert results["Pay with voucher"]["message"] == "expected paid"
    assert "message" not in results["Pay later"] and "details" not in results["Pay later"]


def test_nested_suites_use_the_nearest_suite_name_and_count_time_once(tmp_path):
    xml = (
        '<testsuites><testsuite name="outer" time="3">'
        '<testsuite name="inner" time="2" timestamp="2026-09-29T10:00:00"><testcase name="deep"/></testsuite>'
        '<testcase name="shallow"/>'
        '</testsuite></testsuites>'
    )
    parsed = parse_file(write(tmp_path, xml))

    assert {r["name"]: r["suite"] for r in parsed.results} == {"deep": "inner", "shallow": "outer"}
    assert parsed.suite_seconds == 3
    assert parsed.suite_timestamps == [datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)]


def test_a_case_outside_any_suite(tmp_path):
    parsed = parse_file(write(tmp_path, '<testsuites><testcase name="t" classname="c" file="a/b.py"/></testsuites>'))

    assert parsed.results == [
        {"suite": "", "class_name": "c", "name": "t", "status": "passed", "duration_ms": 0, "file": "a/b.py"}
    ]


def test_error_beats_failure_beats_skipped(tmp_path):
    xml = (
        '<testsuite name="s">'
        '<testcase name="both"><failure message="f"/><error message="e"/></testcase>'
        '<testcase name="fs"><skipped/><failure message="f"/></testcase>'
        '</testsuite>'
    )
    results = by_name(parse_file(write(tmp_path, xml)))

    assert results["both"]["status"] == "errored" and results["both"]["message"] == "e"
    assert results["fs"]["status"] == "failed" and results["fs"]["message"] == "f"


def test_the_message_falls_back_to_the_first_line_of_the_text(tmp_path):
    xml = '<testsuite><testcase name="t"><failure>\n\n  AssertionError: nope\n  at line 3</failure></testcase></testsuite>'
    result = parse_file(write(tmp_path, xml)).results[0]

    assert result["message"] == "AssertionError: nope"
    assert result["details"].strip().startswith("AssertionError: nope")


@pytest.mark.parametrize("time_attr, expected", [
    ('time="1,200.5"', 1200500),
    ("", 0),
    ('time="abc"', 0),
    ('time="-1"', 0),
    ('time="nan"', 0),
    ('time="inf"', 0),
    ('time="1e12"', 2_147_483_647),
    ('time="1e306"', 2_147_483_647),  # finite, but times 1000 it is inf
])
def test_duration(tmp_path, time_attr, expected):
    xml = f'<testsuite><testcase name="t" {time_attr}/></testsuite>'
    assert parse_file(write(tmp_path, xml)).results[0]["duration_ms"] == expected


@pytest.mark.parametrize("stamp, expected", [
    ("2026-09-29T10:00:00Z", datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)),
    ("2026-09-29T12:00:00+02:00", datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)),
    ("2026-09-29T10:00:00", datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)),
    ("yesterday", None),
    ("0001-01-01T00:00:00+05:00", None),  # before datetime.min once converted to UTC
    ("9999-12-31T23:00:00-05:00", None),  # after datetime.max once converted to UTC
])
def test_suite_timestamps(tmp_path, stamp, expected):
    parsed = parse_file(write(tmp_path, f'<testsuite timestamp="{stamp}"><testcase name="t"/></testsuite>'))

    assert parsed.suite_timestamps == ([] if expected is None else [expected])
    assert all(t.tzinfo == timezone.utc for t in parsed.suite_timestamps)


def test_long_text_is_cut_to_64_kb_on_a_character_boundary(tmp_path):
    text = "é" * 40000  # 80,000 bytes of UTF-8
    xml = f'<testsuite><testcase name="t"><failure message="{text}">{text}</failure></testcase></testsuite>'
    result = parse_file(write(tmp_path, xml)).results[0]

    assert result["details"] == "é" * 32768
    assert result["message"] == "é" * 32768


def test_identity_fields_are_cut_to_the_servers_lengths(tmp_path):
    xml = (
        f'<testsuite name="{"s" * 600}">'
        f'<testcase classname="{"c" * 600}" name="{"n" * 1200}" file="{"f" * 1200}"/>'
        '</testsuite>'
    )
    result = parse_file(write(tmp_path, xml)).results[0]

    assert [len(result[k]) for k in ("suite", "class_name", "name", "file")] == [500, 500, 1000, 1000]


def test_test_cases_without_a_name_are_skipped_and_reported(tmp_path):
    path = write(tmp_path, '<testsuite><testcase name="  "/><testcase/><testcase name="ok"/></testsuite>')
    parsed = parse_file(path)

    assert [r["name"] for r in parsed.results] == ["ok"]
    assert parsed.warnings == [f"skipped 2 test case(s) without a name in {path}"]
    assert not parsed.skipped


@pytest.mark.parametrize("xml, reason", [
    ('<?xml version="1.0"?><!DOCTYPE testsuite><testsuite><testcase name="t"/></testsuite>', "DOCTYPE"),
    ('<!DOCTYPE lol [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]><testsuite name="&lol2;"/>', "DOCTYPE"),
    ('<testsuite><testcase name="t">', "not well-formed"),
    ('<testsuite><testcase name="&#0;"/></testsuite>', "not well-formed"),
    ("", "not well-formed"),
    ("<html><body/></html>", "root element is <html>"),
])
def test_files_that_are_skipped(tmp_path, xml, reason):
    path = write(tmp_path, xml)
    parsed = parse_file(path)

    assert parsed.skipped and parsed.results == []
    assert len(parsed.warnings) == 1
    assert parsed.warnings[0].startswith(f"skipped {path}: ")
    assert reason in parsed.warnings[0]


def test_a_doctype_is_refused_in_any_encoding(tmp_path):
    xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE t [<!ENTITY a "b">]><testsuite><testcase name="&a;"/></testsuite>'
    parsed = parse_file(write(tmp_path, xml, encoding="utf-16"))

    assert parsed.skipped and "DOCTYPE" in parsed.warnings[0]


def test_a_utf8_bom_is_fine(tmp_path):
    path = tmp_path / "bom.xml"
    path.write_bytes(b"\xef\xbb\xbf" + '<testsuite><testcase name="café"/></testsuite>'.encode("utf-8"))

    assert [r["name"] for r in parse_file(str(path)).results] == ["café"]


def test_a_utf16_report_is_fine(tmp_path):
    xml = '<?xml version="1.0" encoding="UTF-16"?><testsuite><testcase name="t"/></testsuite>'
    assert [r["name"] for r in parse_file(write(tmp_path, xml, encoding="utf-16")).results] == ["t"]


def test_files_over_50_mb_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(junit, "MAX_FILE_BYTES", 10)
    parsed = parse_file(write(tmp_path, '<testsuite><testcase name="t"/></testsuite>'))

    assert parsed.skipped and "larger than 50 MB" in parsed.warnings[0]


def test_a_missing_file_is_skipped(tmp_path):
    parsed = parse_file(str(tmp_path / "missing.xml"))

    assert parsed.skipped and "cannot be read" in parsed.warnings[0]


def test_surefire_rerun_attempts_become_their_own_results():
    parsed = parse_file(str(FIXTURES / "surefire-reruns.xml"))
    rows = [(r["name"], r["status"], r.get("message")) for r in parsed.results]
    assert rows == [
        # Earlier attempts first, final outcome last -- execution order.
        ("eventually passes", "failed", "expected 2 but was 1"),
        ("eventually passes", "failed", "expected 2 but was 3"),
        ("eventually passes", "passed", None),
        ("eventually errors out", "errored", "boom first"),
        ("eventually errors out", "errored", "boom final"),
        ("plain pass", "passed", None),
    ]
    attempts = [r for r in parsed.results if r["name"] == "eventually passes"]
    assert attempts[0]["duration_ms"] == 0  # per-attempt time is not recorded by Surefire
    assert attempts[2]["duration_ms"] == 1500
    assert "first attempt trace" in attempts[0]["details"]


def test_system_out_becomes_the_log(tmp_path):
    xml = ('<testsuite name="s">'
           '<testcase classname="C" name="books"><system-out>INFO tripId="3960562"\nINFO done\n</system-out></testcase>'
           '<testcase classname="C" name="quiet"><system-out>   </system-out></testcase>'
           '<testcase classname="C" name="none"/></testsuite>')
    rows = by_name(parse_file(write(tmp_path, xml)))
    assert rows["books"]["log"] == 'INFO tripId="3960562"\nINFO done\n'
    assert "log" not in rows["quiet"] and "log" not in rows["none"]


def test_a_long_system_out_is_cut_to_64_kb(tmp_path):
    xml = f'<testsuite name="s"><testcase classname="C" name="t"><system-out>{"x" * 70_000}</system-out></testcase></testsuite>'
    assert by_name(parse_file(write(tmp_path, xml)))["t"]["log"] == "x" * junit.MAX_TEXT_BYTES
