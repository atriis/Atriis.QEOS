# Collector Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `qav-collector`, a standard-library-only Python CLI that reads JUnit XML reports in a CI job and uploads them to ingestion-service's `POST /api/v1/collect/runs`, with retries, CI detection, and an end-to-end check through the running stack.

**Architecture:** A `collector/` package with one module per concern: `junit.py` (XML → result dicts), `ci.py` (CI environment → metadata), `payload.py` (run times, metadata filtering, splitting into parts), `upload.py` (HTTP with retries and a time budget), `cli.py` (argument/env resolution, output, exit codes). Each module is tested on its own; the CLI tests and the upload tests use a real local HTTP server in a thread.

**Tech Stack:** Python ≥ 3.9 standard library (`xml.parsers.expat`, `urllib.request`, `ssl`, `argparse`); pytest for tests; setuptools for packaging; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-29-collector-agent-design.md`

## Global Constraints

- Runtime: `requires-python = ">=3.9"`, **no runtime dependencies** (standard library only). pytest is a test-only dependency.
- Python 3.9 syntax only: every module with annotations starts with `from __future__ import annotations`; use `Optional[...]`/`List[...]` from `typing` in anything evaluated at runtime (dataclass fields are fine with the future import); no `match`, no `X | Y` outside annotations, no `datetime.UTC` (use `timezone.utc`), no parenthesised multi-item `with`, no `zip(strict=...)`, no `dataclass(slots=...|kw_only=...)`.
- Package: `qav-collector`, version `0.1.0` (single source: `qav_collector.__version__`), entry point `qav-collector = qav_collector.cli:main`.
- Limits (copy exactly): 20,000 results per part; 9 MB (`9 * 1024 * 1024`) per part body; 50 MB per report file; 64 KB (`65536` bytes of UTF-8) for `message`/`details`; identity lengths `suite` 500, `class_name` 500, `name` 1000, `file` 1000; `branch` 255, `environment` 100, `ci_run_url` 2048; `duration_ms` ≤ 2,147,483,647; run span ≤ 7 days.
- Upload: 30 s timeout per attempt; at most 5 attempts; backoff 1, 2, 4, 8 s, each × (1 + random 0–0.25); `Retry-After` capped at 10 s, 1 s if missing; no new attempt once 120 s have passed since a part's first attempt; every request carries an `Idempotency-Key`; redirects are never followed; TLS always verified.
- Output: one line per step on stderr, prefixed `qav: `; the API key never appears in any output (replaced with `***`). The API key comes from `QAV_API_KEY` only — never a flag.
- Exit codes: 0 success / nothing to upload / upload failed without `--fail-on-error`; 1 upload failed with `--fail-on-error`; 2 usage or configuration error.
- Dev environment: from `collector/`, `uv venv --seed --python 3.9 .venv` then `$PY -m pip install -e . pytest`, where `PY=.venv/Scripts/python` on Windows (Git Bash) and `PY=.venv/bin/python` on Linux/macOS. All test commands below run from `collector/`.
- Git: commit as the configured user (carneiru). Before every `git add`, run `git status --short` and do not commit stray or empty files you did not create. Never push tags.

## Review Focus

1. **Redirects** (e.g. `QAV_URL=http://localhost:8080`, which the gateway answers with 301): the collector must not follow them — following would re-send the `Authorization` header to wherever `Location` points — and must say where it was redirected. Pinned by `test_redirects_are_not_followed` (Task 4).
2. **TLS failures** (self-signed certificate without `--ca-file`, TLS to a plain-HTTP port): must stop at once with a hint about `--ca-file`, not burn 5 attempts and 2 minutes. Pinned by `test_tls_errors_are_not_retried` (Task 4).
3. **Metadata the server would reject** (`BUILD_URL` that is not http(s), `--commit HEAD`, a 300-character branch, undecodable bytes in an environment variable): must be dropped or cut, never turn the whole run into a 422. Pinned by the `build_run` tests (Task 3).
4. **Absurd times** (`time="nan"`, `"inf"`, `"1e12"`, suite times summing past 7 days): must yield a valid `duration_ms` and no `OverflowError`. Pinned by `test_duration` (Task 1) and `test_started_at_is_clamped_to_seven_days_and_to_finished_at` (Task 3).
5. **Encodings** (UTF-8 BOM from .NET/Windows tools, UTF-16 files): must parse, and a DOCTYPE in a UTF-16 file must still be refused. Pinned by `test_a_utf8_bom_is_fine` and `test_a_doctype_is_refused_in_any_encoding` (Task 1).

---

### Task 1: Package skeleton and JUnit parser

**Files:**
- Create: `collector/pyproject.toml`
- Create: `collector/.gitignore`
- Create: `collector/README.md` (one paragraph; completed in Task 7)
- Create: `collector/src/qav_collector/__init__.py`
- Create: `collector/src/qav_collector/junit.py`
- Create: `collector/tests/fixtures/pytest.xml`, `surefire.xml`, `playwright.xml`, `cucumber.xml`
- Test: `collector/tests/test_junit.py`, `collector/tests/test_package.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `qav_collector.__version__: str` = `"0.1.0"`
  - `qav_collector.junit.parse_file(path: str) -> ParsedFile`
  - `qav_collector.junit.ParsedFile` dataclass: `path: str`, `results: List[dict]`, `suite_timestamps: List[datetime]` (aware, UTC), `suite_seconds: float`, `warnings: List[str]`, `skipped: bool`
  - Each result dict has keys `suite`, `class_name`, `name`, `status` (`passed`/`failed`/`skipped`/`errored`), `duration_ms`, and optionally `file`, `message`, `details` (absent, never `None`).
  - Warning strings: a skipped file → `f"skipped {path}: {reason}"`; unnamed test cases → `f"skipped {n} test case(s) without a name in {path}"`.
  - Module constants tests may patch: `junit.MAX_FILE_BYTES`.

- [ ] **Step 1: Create the package files**

`collector/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "qav-collector"
dynamic = ["version"]
description = "Uploads JUnit XML test results from CI to the QA Vision platform"
readme = "README.md"
requires-python = ">=3.9"
dependencies = []

[project.scripts]
qav-collector = "qav_collector.cli:main"

[tool.setuptools.dynamic]
version = { attr = "qav_collector.__version__" }

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`collector/.gitignore`:

```
.venv/
__pycache__/
*.egg-info/
build/
dist/
.pytest_cache/
```

`collector/README.md`:

```markdown
# qav-collector

Uploads JUnit XML test results from a CI job to the QA Vision platform. Standard library only,
Python 3.9 or newer.
```

`collector/src/qav_collector/__init__.py`:

```python
"""qav-collector: uploads JUnit XML test results from CI to the QA Vision platform."""

__version__ = "0.1.0"
```

- [ ] **Step 2: Create the dev environment**

Run (from `collector/`):

```bash
uv venv --seed --python 3.9 .venv
PY=.venv/Scripts/python   # .venv/bin/python on Linux/macOS
$PY -m pip install -e . pytest
```

Expected: `Successfully installed ... qav-collector-0.1.0 ...` (pytest and its dependencies too).

- [ ] **Step 3: Write the fixtures**

`collector/tests/fixtures/pytest.xml` (shape of `pytest --junitxml`):

```xml
<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="1.234" timestamp="2026-09-29T10:00:00.123456+01:00" hostname="runner">
    <testcase classname="tests.test_math" name="test_add" time="0.001" />
    <testcase classname="tests.test_math" name="test_div" time="0.002">
      <failure message="assert 1 == 2">def test_div():
&gt;       assert 1 == 2
E       assert 1 == 2

tests/test_math.py:8: AssertionError</failure>
    </testcase>
    <testcase classname="tests.test_math" name="test_skip" time="0.000">
      <skipped type="pytest.skip" message="not on CI">tests/test_math.py:10: not on CI</skipped>
    </testcase>
    <testcase classname="tests.test_db" name="test_conn" time="0.500">
      <error message="failed on setup with &quot;ConnectionError&quot;">conftest.py:5: ConnectionError</error>
    </testcase>
  </testsuite>
</testsuites>
```

`collector/tests/fixtures/surefire.xml` (Maven Surefire with a rerun plugin; root is `<testsuite>`; `time` uses a thousands separator):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuite xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="com.example.CartTest" time="1,200.5" tests="3" errors="0" skipped="0" failures="1">
  <properties>
    <property name="java.version" value="21"/>
  </properties>
  <testcase name="addsItem" classname="com.example.CartTest" time="0.012"/>
  <testcase name="flakyCheckout" classname="com.example.CartTest" time="0.300">
    <flakyFailure message="timeout" type="java.lang.AssertionError">
      <stackTrace>at com.example.CartTest.flakyCheckout(CartTest.java:40)</stackTrace>
    </flakyFailure>
  </testcase>
  <testcase name="brokenTotal" classname="com.example.CartTest" time="0.050">
    <failure message="expected 3 but was 2" type="org.opentest4j.AssertionFailedError">org.opentest4j.AssertionFailedError: expected 3 but was 2
    at com.example.CartTest.brokenTotal(CartTest.java:55)</failure>
    <rerunFailure message="expected 3 but was 2" type="org.opentest4j.AssertionFailedError">
      <stackTrace>RERUN at com.example.CartTest.brokenTotal(CartTest.java:55)</stackTrace>
    </rerunFailure>
  </testcase>
</testsuite>
```

`collector/tests/fixtures/playwright.xml` (Playwright's `junit` reporter; save as UTF-8, it contains `›`):

```xml
<testsuites id="" name="" tests="2" failures="1" skipped="0" errors="0" time="3.5">
<testsuite name="login.spec.ts" timestamp="2026-09-29T09:58:00.000Z" hostname="chromium" tests="2" failures="1" skipped="0" time="3.4" errors="0">
<testcase name="login › shows the form" classname="login.spec.ts" time="1.1">
</testcase>
<testcase name="login › rejects a bad password" classname="login.spec.ts" time="2.3">
<failure message="login.spec.ts:12:5 rejects a bad password" type="FAILURE">
<![CDATA[  login.spec.ts:12:5 › rejects a bad password

    Error: expect(received).toBeVisible()]]>
</failure>
<system-out>
<![CDATA[
[[ATTACHMENT|test-results/login-rejects/test-failed-1.png]]
]]>
</system-out>
</testcase>
</testsuite>
</testsuites>
```

`collector/tests/fixtures/cucumber.xml` (cucumber-js `junit` formatter):

```xml
<?xml version="1.0"?>
<testsuite failures="1" skipped="1" name="cucumber-js" time="0.9" tests="3">
  <testcase classname="Checkout" name="Pay with card" time="0.5"/>
  <testcase classname="Checkout" name="Pay with voucher" time="0.3">
    <failure type="AssertionError" message="expected paid"><![CDATA[Then the order is paid # steps.js:20
AssertionError: expected paid]]></failure>
  </testcase>
  <testcase classname="Checkout" name="Pay later" time="0.1">
    <skipped/>
  </testcase>
</testsuite>
```

- [ ] **Step 4: Write the failing tests**

`collector/tests/test_package.py`:

```python
from importlib.metadata import version

import qav_collector


def test_the_version_has_a_single_source():
    assert qav_collector.__version__ == "0.1.0"
    assert version("qav-collector") == qav_collector.__version__
```

`collector/tests/test_junit.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from qav_collector import junit
from qav_collector.junit import parse_file

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
])
def test_duration(tmp_path, time_attr, expected):
    xml = f'<testsuite><testcase name="t" {time_attr}/></testsuite>'
    assert parse_file(write(tmp_path, xml)).results[0]["duration_ms"] == expected


@pytest.mark.parametrize("stamp, expected", [
    ("2026-09-29T10:00:00Z", datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)),
    ("2026-09-29T12:00:00+02:00", datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)),
    ("2026-09-29T10:00:00", datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)),
    ("yesterday", None),
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
```

- [ ] **Step 5: Run the tests to see them fail**

Run: `$PY -m pytest -q`
Expected: `test_package.py` passes; `test_junit.py` errors at collection with `ImportError: cannot import name 'junit' from 'qav_collector'`.

- [ ] **Step 6: Write the parser**

`collector/src/qav_collector/junit.py`:

```python
"""JUnit XML -> result dicts in the shape POST /api/v1/collect/runs expects.

The XML is read with expat directly rather than through ElementTree's parser, so a DOCTYPE or
ENTITY declaration is refused the moment expat reports it -- in whatever encoding the file uses.
JUnit never needs a DTD, and refusing one rules out entity-expansion attacks without a
third-party library. Expat also rejects NUL and surrogate code points as not well-formed, so no
result can carry characters the server cannot store.
"""
from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from xml.parsers import expat

MAX_FILE_BYTES = 50 * 1024 * 1024
# The server truncates message/details at 64 KB of UTF-8 and rejects longer identity fields
MAX_TEXT_BYTES = 65536
MAX_DURATION_MS = 2_147_483_647
SUITE_LENGTH = 500
CLASS_NAME_LENGTH = 500
NAME_LENGTH = 1000
FILE_LENGTH = 1000


class _Refused(Exception):
    pass


@dataclass
class ParsedFile:
    path: str
    results: List[dict] = field(default_factory=list)
    suite_timestamps: List[datetime] = field(default_factory=list)
    suite_seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)
    skipped: bool = False
    unnamed: int = 0


def parse_file(path: str) -> ParsedFile:
    parsed = ParsedFile(path=path)
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return _skip(parsed, "larger than 50 MB")
        root = _read_xml(path)
    except _Refused as exc:
        return _skip(parsed, str(exc))
    except expat.ExpatError as exc:
        return _skip(parsed, f"not well-formed XML ({expat.ErrorString(exc.code)}, line {exc.lineno})")
    except OSError as exc:
        return _skip(parsed, f"cannot be read ({exc.strerror or exc})")
    if root.tag not in ("testsuites", "testsuite"):
        return _skip(parsed, f"root element is <{root.tag}>, not <testsuites> or <testsuite>")
    _walk(root, "", False, parsed)
    if parsed.unnamed:
        parsed.warnings.append(f"skipped {parsed.unnamed} test case(s) without a name in {path}")
    return parsed


def _skip(parsed: ParsedFile, reason: str) -> ParsedFile:
    parsed.skipped = True
    parsed.warnings.append(f"skipped {parsed.path}: {reason}")
    return parsed


def _read_xml(path: str) -> ET.Element:
    builder = ET.TreeBuilder()
    parser = expat.ParserCreate()

    def refuse(*_args):
        raise _Refused("contains a DOCTYPE or ENTITY declaration")

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    parser.buffer_text = True
    with open(path, "rb") as fh:
        parser.ParseFile(fh)
    return builder.close()


def _walk(element: ET.Element, suite: str, nested: bool, parsed: ParsedFile) -> None:
    if element.tag == "testsuite":
        suite = element.get("name", "")
        stamp = _timestamp(element.get("timestamp"))
        if stamp is not None:
            parsed.suite_timestamps.append(stamp)
        if not nested:
            # A nested suite's time is already part of its parent's
            parsed.suite_seconds += _seconds(element.get("time"))
        nested = True
    for child in element:
        if child.tag in ("testsuite", "testsuites"):
            _walk(child, suite, nested, parsed)
        elif child.tag == "testcase":
            _add_case(child, suite, parsed)


def _add_case(case: ET.Element, suite: str, parsed: ParsedFile) -> None:
    name = (case.get("name") or "").strip()
    if not name:
        parsed.unnamed += 1
        return
    # Element truthiness means "has children", so compare with None explicitly.
    # Surefire's flakyFailure/rerunFailure/... record earlier attempts and are not looked at.
    error, failure, skipped = case.find("error"), case.find("failure"), case.find("skipped")
    if error is not None:
        status, outcome = "errored", error
    elif failure is not None:
        status, outcome = "failed", failure
    elif skipped is not None:
        status, outcome = "skipped", skipped
    else:
        status, outcome = "passed", None

    result = {
        "suite": suite[:SUITE_LENGTH],
        "class_name": (case.get("classname") or "")[:CLASS_NAME_LENGTH],
        "name": name[:NAME_LENGTH],
        "status": status,
        "duration_ms": min(round(_seconds(case.get("time")) * 1000), MAX_DURATION_MS),
    }
    file = case.get("file")
    if file:
        result["file"] = file[:FILE_LENGTH]
    if outcome is not None:
        text = "".join(outcome.itertext())
        message = outcome.get("message") or _first_line(text)
        if message:
            result["message"] = _cut(message)
        if text.strip():
            result["details"] = _cut(text)
    parsed.results.append(result)


def _seconds(value: Optional[str]) -> float:
    try:
        seconds = float((value or "").replace(",", ""))
    except ValueError:
        return 0.0
    if not math.isfinite(seconds) or seconds < 0:
        return 0.0
    return seconds


def _timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _cut(text: str) -> str:
    data = text.encode("utf-8")
    if len(data) <= MAX_TEXT_BYTES:
        return text
    # errors="ignore" drops only the character the cut split in two
    return data[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")
```

- [ ] **Step 7: Run the tests to see them pass**

Run: `$PY -m pytest -q`
Expected: all tests pass, no errors.

- [ ] **Step 8: Commit**

```bash
cd ..   # repository root
git status --short
git add collector/pyproject.toml collector/.gitignore collector/README.md collector/src collector/tests
git commit -m "feat(collector): package skeleton and JUnit XML parser

Parses pytest, Surefire, Playwright and cucumber-js JUnit output with
expat directly, refusing any DOCTYPE/ENTITY declaration in any encoding.
Maps status by error > failure > skipped, cuts text to the server's
limits, and skips unreadable, oversized or malformed files with a warning.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: CI detection

**Files:**
- Create: `collector/src/qav_collector/ci.py`
- Test: `collector/tests/test_ci.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `qav_collector.ci.CIInfo` dataclass: `provider: str`, `commit: Optional[str] = None`, `branch: Optional[str] = None`, `run_url: Optional[str] = None`, `idempotency_key: Optional[str] = None`
  - `qav_collector.ci.detect(env: Mapping[str, str]) -> CIInfo` (provider one of `github_actions`, `gitlab_ci`, `jenkins`, `local`; key is `None` when the CI variables that make it are missing, and always `None` for `local`)
  - `qav_collector.ci.sanitize_key(raw: str) -> Optional[str]` — printable ASCII without spaces (`!`..`~`), other characters become `-`, cut to 200; `None` if empty.

- [ ] **Step 1: Write the failing tests**

`collector/tests/test_ci.py`:

```python
from qav_collector.ci import CIInfo, detect, sanitize_key

GITHUB = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_SHA": "a" * 40,
    "GITHUB_REF_NAME": "main",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "acme/shop",
    "GITHUB_RUN_ID": "123",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_JOB": "test",
}


def test_github_actions():
    assert detect(GITHUB) == CIInfo(
        provider="github_actions",
        commit="a" * 40,
        branch="main",
        run_url="https://github.com/acme/shop/actions/runs/123",
        idempotency_key="gh-123-2-test",
    )


def test_github_pull_request_uses_the_head_branch():
    info = detect({**GITHUB, "GITHUB_REF_NAME": "42/merge", "GITHUB_HEAD_REF": "feature/cart"})
    assert info.branch == "feature/cart"


def test_github_without_a_run_id_has_no_key_and_no_run_url():
    env = dict(GITHUB)
    del env["GITHUB_RUN_ID"]
    info = detect(env)
    assert info.provider == "github_actions"
    assert info.idempotency_key is None and info.run_url is None


def test_github_attempt_defaults_to_1():
    env = dict(GITHUB)
    del env["GITHUB_RUN_ATTEMPT"]
    assert detect(env).idempotency_key == "gh-123-1-test"


def test_gitlab_ci():
    env = {
        "GITLAB_CI": "true",
        "CI_COMMIT_SHA": "b" * 40,
        "CI_COMMIT_REF_NAME": "develop",
        "CI_JOB_URL": "https://gitlab.com/acme/shop/-/jobs/77",
        "CI_JOB_ID": "77",
    }
    assert detect(env) == CIInfo(
        provider="gitlab_ci",
        commit="b" * 40,
        branch="develop",
        run_url="https://gitlab.com/acme/shop/-/jobs/77",
        idempotency_key="gl-77",
    )


def test_jenkins_strips_origin_and_sanitises_the_build_tag():
    env = {
        "JENKINS_URL": "https://ci.acme.test/",
        "GIT_COMMIT": "c" * 40,
        "GIT_BRANCH": "origin/release/1.2",
        "BUILD_URL": "https://ci.acme.test/job/shop/12/",
        "BUILD_TAG": "jenkins-shop tests-12",
    }
    assert detect(env) == CIInfo(
        provider="jenkins",
        commit="c" * 40,
        branch="release/1.2",
        run_url="https://ci.acme.test/job/shop/12/",
        idempotency_key="jk-jenkins-shop-tests-12",
    )


def test_no_ci_is_local():
    assert detect({}) == CIInfo(provider="local")
    assert detect({"GITHUB_ACTIONS": "false", "GITLAB_CI": ""}) == CIInfo(provider="local")


def test_blank_variables_count_as_missing():
    assert detect({**GITHUB, "GITHUB_SHA": "  ", "GITHUB_HEAD_REF": ""}).commit is None
    assert detect({**GITHUB, "GITHUB_HEAD_REF": ""}).branch == "main"


def test_sanitize_key():
    assert sanitize_key("a bé\n") == "a-b--"
    assert sanitize_key("x" * 300) == "x" * 200
    assert sanitize_key("") is None
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `$PY -m pytest tests/test_ci.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'qav_collector.ci'`.

- [ ] **Step 3: Write the module**

`collector/src/qav_collector/ci.py`:

```python
"""Run metadata from the CI system's environment variables."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

# The server takes Idempotency-Keys up to 255 characters; this leaves room for "-part-N"
MAX_KEY_LENGTH = 200


@dataclass
class CIInfo:
    provider: str
    commit: Optional[str] = None
    branch: Optional[str] = None
    run_url: Optional[str] = None
    idempotency_key: Optional[str] = None


def detect(env: Mapping[str, str]) -> CIInfo:
    def get(name: str) -> Optional[str]:
        return env.get(name, "").strip() or None

    if get("GITHUB_ACTIONS") == "true":
        server, repo, run_id = get("GITHUB_SERVER_URL"), get("GITHUB_REPOSITORY"), get("GITHUB_RUN_ID")
        return CIInfo(
            provider="github_actions",
            commit=get("GITHUB_SHA"),
            # On pull requests GITHUB_REF_NAME is "<number>/merge"; the head branch is the useful one
            branch=get("GITHUB_HEAD_REF") or get("GITHUB_REF_NAME"),
            run_url=f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else None,
            # A re-run attempt is a new execution, so it gets a new key on purpose
            idempotency_key=_key("gh", run_id, get("GITHUB_RUN_ATTEMPT") or "1", get("GITHUB_JOB")) if run_id else None,
        )
    if get("GITLAB_CI") == "true":
        job_id = get("CI_JOB_ID")
        return CIInfo(
            provider="gitlab_ci",
            commit=get("CI_COMMIT_SHA"),
            branch=get("CI_COMMIT_REF_NAME"),
            run_url=get("CI_JOB_URL"),
            idempotency_key=_key("gl", job_id) if job_id else None,
        )
    if get("JENKINS_URL"):
        branch, tag = get("GIT_BRANCH"), get("BUILD_TAG")
        if branch and branch.startswith("origin/"):
            branch = branch[len("origin/"):]
        return CIInfo(
            provider="jenkins",
            commit=get("GIT_COMMIT"),
            branch=branch,
            run_url=get("BUILD_URL"),
            idempotency_key=_key("jk", tag) if tag else None,
        )
    return CIInfo(provider="local")


def sanitize_key(raw: str) -> Optional[str]:
    """Printable ASCII without spaces, at most MAX_KEY_LENGTH characters."""
    cleaned = "".join(c if "!" <= c <= "~" else "-" for c in raw)[:MAX_KEY_LENGTH]
    return cleaned or None


def _key(*parts: Optional[str]) -> Optional[str]:
    return sanitize_key("-".join(p for p in parts if p))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `$PY -m pytest -q`
Expected: all tests pass, no errors.

- [ ] **Step 5: Commit**

```bash
cd ..
git status --short
git add collector/src/qav_collector/ci.py collector/tests/test_ci.py
git commit -m "feat(collector): detect GitHub Actions, GitLab CI and Jenkins

Commit, branch (PR head branch on GitHub, origin/ stripped on Jenkins),
run URL and a per-job Idempotency-Key, sanitised to printable ASCII.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Building the upload

**Files:**
- Create: `collector/src/qav_collector/payload.py`
- Test: `collector/tests/test_payload.py`

**Interfaces:**
- Consumes: `qav_collector.__version__` (Task 1). Result dicts shaped as Task 1 produces them (`duration_ms`, `status` keys are read).
- Produces:
  - `qav_collector.payload.Part` dataclass: `body: bytes`, `idempotency_key: str`, `count: int`
  - `run_times(timestamps: Sequence[datetime], suite_seconds: float, results: Sequence[dict], now: datetime) -> Tuple[datetime, datetime]` → `(started_at, finished_at)`
  - `build_run(*, ci_provider: str, started_at: datetime, finished_at: datetime, ci_run_url: Optional[str] = None, commit_sha: Optional[str] = None, branch: Optional[str] = None, environment: Optional[str] = None) -> Dict[str, str]`
  - `build_parts(run: dict, results: List[dict], idempotency_key: str) -> List[Part]` (one part keeps the key unchanged; several get `-part-1`, `-part-2`, ...)
  - `summarize(results: Sequence[dict]) -> Dict[str, int]` with keys `passed`, `failed`, `skipped`, `errored`
  - Module constants tests may patch: `payload.MAX_RESULTS_PER_PART`, `payload.MAX_PART_BYTES` (read at call time).

- [ ] **Step 1: Write the failing tests**

`collector/tests/test_payload.py`:

```python
import json
from datetime import datetime, timedelta, timezone

import pytest

from qav_collector import __version__, payload
from qav_collector.payload import build_parts, build_run, run_times, summarize

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
RUN = {"ci_provider": "local", "started_at": "x", "finished_at": "x"}


def result(name, status="passed", duration_ms=0):
    return {"suite": "", "class_name": "", "name": name, "status": status, "duration_ms": duration_ms}


def test_started_at_is_the_earliest_suite_timestamp():
    early, late = NOW - timedelta(minutes=10), NOW - timedelta(minutes=5)
    assert run_times([late, early], 99, [], NOW) == (early, NOW)


def test_without_timestamps_started_at_is_now_minus_the_suite_time():
    assert run_times([], 90.5, [], NOW) == (NOW - timedelta(seconds=90.5), NOW)


def test_without_suite_time_the_result_durations_are_summed():
    results = [result("a", duration_ms=1500), result("b", duration_ms=500)]
    assert run_times([], 0, results, NOW)[0] == NOW - timedelta(seconds=2)


def test_started_at_is_clamped_to_seven_days_and_to_finished_at():
    assert run_times([NOW - timedelta(days=30)], 0, [], NOW)[0] == NOW - timedelta(days=7)
    assert run_times([NOW + timedelta(hours=2)], 0, [], NOW)[0] == NOW
    # Suite times that add up to centuries must not overflow timedelta
    assert run_times([], 1e300, [], NOW)[0] == NOW - timedelta(days=7)


def test_build_run_sends_what_the_server_accepts():
    run = build_run(
        ci_provider="github_actions",
        started_at=NOW - timedelta(minutes=1),
        finished_at=NOW,
        ci_run_url="https://github.com/acme/shop/actions/runs/1",
        commit_sha="a" * 40,
        branch="main",
        environment="staging",
    )
    assert run == {
        "ci_provider": "github_actions",
        "agent_version": f"qav-collector/{__version__}",
        "started_at": "2026-09-29T11:59:00+00:00",
        "finished_at": "2026-09-29T12:00:00+00:00",
        "ci_run_url": "https://github.com/acme/shop/actions/runs/1",
        "commit_sha": "a" * 40,
        "branch": "main",
        "environment": "staging",
    }


@pytest.mark.parametrize("field, value", [
    ("commit_sha", "HEAD"),
    ("commit_sha", "abc"),
    ("ci_run_url", "ftp://ci.acme.test/1"),
    ("ci_run_url", "https://has a space"),
    ("ci_run_url", "https://ci.acme.test/" + "a" * 2048),
    ("branch", ""),
    ("environment", None),
])
def test_invalid_or_empty_metadata_is_left_out(field, value):
    run = build_run(ci_provider="local", started_at=NOW, finished_at=NOW, **{field: value})
    assert field not in run


def test_long_metadata_is_cut():
    run = build_run(ci_provider="local", started_at=NOW, finished_at=NOW, branch="b" * 300, environment="e" * 150)
    assert len(run["branch"]) == 255 and len(run["environment"]) == 100


def test_undecodable_metadata_is_made_storable():
    # os.environ holds undecodable bytes as lone surrogates, which UTF-8 cannot encode
    run = build_run(ci_provider="local", started_at=NOW, finished_at=NOW, branch="bad\udcff")
    assert run["branch"] == "bad?"
    json.dumps(run, ensure_ascii=False).encode("utf-8")


def test_one_part_keeps_the_key_as_is():
    parts = build_parts(RUN, [result("a"), result("b")], "gh-1-1-test")

    assert [(p.idempotency_key, p.count) for p in parts] == [("gh-1-1-test", 2)]
    assert json.loads(parts[0].body) == {"run": RUN, "results": [result("a"), result("b")]}


def test_more_results_than_the_server_takes_are_split_into_numbered_parts(monkeypatch):
    monkeypatch.setattr(payload, "MAX_RESULTS_PER_PART", 3)
    parts = build_parts(RUN, [result(str(i)) for i in range(7)], "k")

    assert [(p.idempotency_key, p.count) for p in parts] == [("k-part-1", 3), ("k-part-2", 3), ("k-part-3", 1)]
    assert [r["name"] for p in parts for r in json.loads(p.body)["results"]] == [str(i) for i in range(7)]
    assert all(json.loads(p.body)["run"] == RUN for p in parts)


def test_a_part_over_the_size_limit_is_halved_until_it_fits(monkeypatch):
    rows = [dict(result(str(i)), details="x" * 1000) for i in range(8)]
    monkeypatch.setattr(payload, "MAX_PART_BYTES", 2500)
    parts = build_parts(RUN, rows, "k")

    assert all(len(p.body) <= 2500 for p in parts)
    assert [p.count for p in parts] == [2, 2, 2, 2]
    assert [p.idempotency_key for p in parts] == ["k-part-1", "k-part-2", "k-part-3", "k-part-4"]


def test_a_single_result_is_never_split_further(monkeypatch):
    monkeypatch.setattr(payload, "MAX_PART_BYTES", 10)
    parts = build_parts(RUN, [result("a"), result("b")], "k")

    assert [p.count for p in parts] == [1, 1]


def test_summarize():
    results = [result("a"), result("b", "failed"), result("c", "errored"), result("d", "skipped"), result("e")]
    assert summarize(results) == {"passed": 2, "failed": 1, "errored": 1, "skipped": 1}
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `$PY -m pytest tests/test_payload.py -q`
Expected: collection error `ImportError: cannot import name 'payload' from 'qav_collector'`.

- [ ] **Step 3: Write the module**

`collector/src/qav_collector/payload.py`:

```python
"""The upload body: run times, run metadata, and splitting into parts the server accepts."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from qav_collector import __version__

MAX_RESULTS_PER_PART = 20000
# The gateway accepts bodies up to 10 MB
MAX_PART_BYTES = 9 * 1024 * 1024
MAX_RUN_SPAN = timedelta(days=7)
BRANCH_LENGTH = 255
ENVIRONMENT_LENGTH = 100
RUN_URL_LENGTH = 2048
_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")
_RUN_URL = re.compile(r"^https?://\S+$")


@dataclass
class Part:
    body: bytes
    idempotency_key: str
    count: int


def run_times(
    timestamps: Sequence[datetime], suite_seconds: float, results: Sequence[dict], now: datetime
) -> Tuple[datetime, datetime]:
    finished = now
    if timestamps:
        started = min(timestamps)
    else:
        seconds = suite_seconds if suite_seconds > 0 else sum(r["duration_ms"] for r in results) / 1000
        started = finished - timedelta(seconds=min(seconds, MAX_RUN_SPAN.total_seconds()))
    # The server rejects runs longer than 7 days and starts after the finish
    started = min(max(started, finished - MAX_RUN_SPAN), finished)
    return started, finished


def build_run(
    *,
    ci_provider: str,
    started_at: datetime,
    finished_at: datetime,
    ci_run_url: Optional[str] = None,
    commit_sha: Optional[str] = None,
    branch: Optional[str] = None,
    environment: Optional[str] = None,
) -> Dict[str, str]:
    """Metadata the server would reject is left out or cut, so it never costs the whole run."""
    run = {
        "ci_provider": ci_provider,
        "agent_version": f"qav-collector/{__version__}",
        "started_at": started_at.astimezone(timezone.utc).isoformat(),
        "finished_at": finished_at.astimezone(timezone.utc).isoformat(),
    }
    ci_run_url, commit_sha = _storable(ci_run_url), _storable(commit_sha)
    branch, environment = _storable(branch), _storable(environment)
    if ci_run_url and len(ci_run_url) <= RUN_URL_LENGTH and _RUN_URL.match(ci_run_url):
        run["ci_run_url"] = ci_run_url
    if commit_sha and _SHA.match(commit_sha):
        run["commit_sha"] = commit_sha
    if branch:
        run["branch"] = branch[:BRANCH_LENGTH]
    if environment:
        run["environment"] = environment[:ENVIRONMENT_LENGTH]
    return run


def build_parts(run: dict, results: List[dict], idempotency_key: str) -> List[Part]:
    chunks = [results[i:i + MAX_RESULTS_PER_PART] for i in range(0, len(results), MAX_RESULTS_PER_PART)]
    encoded: List[Tuple[bytes, int]] = []
    for chunk in chunks:
        encoded.extend(_fit(run, chunk))
    if len(encoded) == 1:
        body, count = encoded[0]
        return [Part(body=body, idempotency_key=idempotency_key, count=count)]
    # Numbered keys, so a re-run of the same CI job replays exactly the same parts
    return [
        Part(body=body, idempotency_key=f"{idempotency_key}-part-{number}", count=count)
        for number, (body, count) in enumerate(encoded, start=1)
    ]


def summarize(results: Sequence[dict]) -> Dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errored": 0}
    for result in results:
        counts[result["status"]] += 1
    return counts


def _fit(run: dict, chunk: List[dict]) -> List[Tuple[bytes, int]]:
    body = json.dumps({"run": run, "results": chunk}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) <= MAX_PART_BYTES or len(chunk) == 1:
        return [(body, len(chunk))]
    middle = len(chunk) // 2
    return _fit(run, chunk[:middle]) + _fit(run, chunk[middle:])


def _storable(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    # Lone surrogates (undecodable bytes in os.environ or argv) become "?"
    return value.encode("utf-8", errors="replace").decode("utf-8").strip() or None
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `$PY -m pytest -q`
Expected: all tests pass, no errors.

- [ ] **Step 5: Commit**

```bash
cd ..
git status --short
git add collector/src/qav_collector/payload.py collector/tests/test_payload.py
git commit -m "feat(collector): build the run and split it into parts

started_at from the earliest suite timestamp (else now minus the suite
time), clamped to the server's 7-day window; metadata the server would
reject is dropped or cut; more than 20,000 results or 9 MB are split into
parts with -part-N Idempotency-Keys.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Upload client

**Files:**
- Create: `collector/src/qav_collector/upload.py`
- Create: `collector/tests/conftest.py` (the fake platform, shared with Task 5)
- Test: `collector/tests/test_upload.py`

**Interfaces:**
- Consumes: `qav_collector.payload.Part` (Task 3), `qav_collector.__version__` (Task 1).
- Produces:
  - `qav_collector.upload.ConfigError(Exception)` — a setting that can never work (CLI exits 2)
  - `qav_collector.upload.UploadError(Exception)` — the part was not stored; `str()` is a user-facing message without the key
  - `endpoint_for(url: str) -> str` — validates the URL (https, or http for `localhost`/`127.0.0.1`/`::1`), returns `<url without trailing slash>/api/v1/collect/runs`; raises `ConfigError`
  - `make_context(ca_file: Optional[str]) -> ssl.SSLContext` — raises `ConfigError` when the file cannot be loaded
  - `upload_part(endpoint: str, api_key: str, part: Part, context: Optional[ssl.SSLContext] = None, *, sleep=time.sleep, clock=time.monotonic, rand=random.random) -> Tuple[int, dict]` → `(status 200|201, parsed receipt)`; raises `UploadError`
  - Module constant tests may patch: `upload.TIMEOUT_SECONDS` (read at call time).
  - `tests/conftest.py` fixture `platform` → `FakePlatform` with `.url` (`http://127.0.0.1:<port>`), `.reply(status, body=None, headers=None, delay=0.0)` (queued in order; `body` a dict/list for JSON or `bytes`), `.requests` (list of `{"path", "headers", "body"}`; `headers` is case-insensitive).

- [ ] **Step 1: Write the fake platform**

`collector/tests/conftest.py`:

```python
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakePlatform:
    """Answers POSTs with scripted responses, in order, and records every request."""

    def __init__(self):
        self.url = ""
        self.responses = []
        self.requests = []

    def reply(self, status, body=None, headers=None, delay=0.0):
        self.responses.append((status, {} if body is None else body, headers or {}, delay))


@pytest.fixture
def platform():
    fake = FakePlatform()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            with lock:
                fake.requests.append({"path": self.path, "headers": self.headers, "body": body})
                if fake.responses:
                    status, payload, headers, delay = fake.responses.pop(0)
                else:
                    status, payload, headers, delay = 500, {"detail": "no response scripted"}, {}, 0.0
            time.sleep(delay)
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            pass  # the client hung up first (the timeout tests do that on purpose)

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 2: Write the failing tests**

`collector/tests/test_upload.py`:

```python
import socket
import threading

import pytest

from qav_collector import __version__, upload
from qav_collector.payload import Part
from qav_collector.upload import ConfigError, UploadError, endpoint_for, make_context, upload_part

KEY = "qav_test_key_123"
PART = Part(body=b'{"run":{},"results":[]}', idempotency_key="gh-1-1-test", count=0)
RECEIPT = {"id": 42, "project_id": 1, "total": 2, "passed": 1, "failed": 1, "skipped": 0, "errored": 0,
           "created_at": "2026-09-29T12:00:00Z"}


class FakeTime:
    """sleep() only records; clock() advances by `step` on every call, plus whatever was slept."""

    def __init__(self, step=0.0):
        self.now = 0.0
        self.step = step
        self.sleeps = []

    def clock(self):
        value = self.now
        self.now += self.step
        return value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def send(endpoint, fake=None, context=None):
    fake = fake or FakeTime()
    return upload_part(endpoint, KEY, PART, context, sleep=fake.sleep, clock=fake.clock, rand=lambda: 0.0)


def collect(platform):
    return platform.url + "/api/v1/collect/runs"


def closed_port_endpoint():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/api/v1/collect/runs"


def test_a_stored_run_is_returned_with_its_status(platform):
    platform.reply(201, RECEIPT)

    assert send(collect(platform)) == (201, RECEIPT)
    request = platform.requests[0]
    assert request["path"] == "/api/v1/collect/runs"
    assert request["body"] == PART.body
    assert request["headers"]["Authorization"] == f"Bearer {KEY}"
    assert request["headers"]["Idempotency-Key"] == "gh-1-1-test"
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["headers"]["User-Agent"] == f"qav-collector/{__version__}"


def test_a_replay_counts_as_success(platform):
    platform.reply(200, RECEIPT)
    assert send(collect(platform)) == (200, RECEIPT)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_errors_are_retried_with_backoff(platform, status):
    platform.reply(status)
    platform.reply(status)
    platform.reply(201, RECEIPT)
    fake = FakeTime()

    assert send(collect(platform), fake) == (201, RECEIPT)
    assert fake.sleeps == [1, 2]
    assert {r["headers"]["Idempotency-Key"] for r in platform.requests} == {"gh-1-1-test"}


def test_backoff_has_up_to_25_percent_jitter(platform):
    platform.reply(503)
    platform.reply(201, RECEIPT)
    fake = FakeTime()

    upload_part(collect(platform), KEY, PART, sleep=fake.sleep, clock=fake.clock, rand=lambda: 1.0)
    assert fake.sleeps == [1.25]


def test_an_unreachable_platform_is_retried_until_the_attempt_budget():
    fake = FakeTime()

    with pytest.raises(UploadError, match=r"cannot reach the platform .*gave up after 5 attempts"):
        send(closed_port_endpoint(), fake)
    assert fake.sleeps == [1, 2, 4, 8]


def test_429_waits_for_retry_after_capped_at_10_seconds(platform):
    platform.reply(429, headers={"Retry-After": "3"})
    platform.reply(429, headers={"Retry-After": "60"})
    platform.reply(429)
    platform.reply(201, RECEIPT)
    fake = FakeTime()

    assert send(collect(platform), fake) == (201, RECEIPT)
    assert fake.sleeps == [3, 10, 1]


def test_no_new_attempt_starts_after_120_seconds(platform):
    for _ in range(5):
        platform.reply(503)
    fake = FakeTime(step=40)  # every clock() call is 40 s later

    with pytest.raises(UploadError, match="gave up after 120 s"):
        send(collect(platform), fake)
    assert len(platform.requests) == 3


def test_a_timed_out_post_is_retried_with_the_same_key(platform, monkeypatch):
    monkeypatch.setattr(upload, "TIMEOUT_SECONDS", 0.3)
    platform.reply(201, RECEIPT, delay=1.0)  # stored, but the answer comes too late
    platform.reply(200, RECEIPT)             # the retry is answered as a replay
    fake = FakeTime()

    assert send(collect(platform), fake) == (200, RECEIPT)
    assert fake.sleeps == [1]
    assert [r["headers"]["Idempotency-Key"] for r in platform.requests] == ["gh-1-1-test", "gh-1-1-test"]


@pytest.mark.parametrize("status, body, message", [
    (401, {"detail": "Invalid API key"}, "the API key is invalid or revoked (401)"),
    (409, {"detail": "Idempotency-Key reused"}, "this Idempotency-Key was already used for different results (409)"),
    (413, {"detail": "Request Entity Too Large"}, "the platform rejected the upload (413): Request Entity Too Large"),
    (422, {"detail": [{"loc": ["body", "run"], "msg": "Field required"}]},
     'the platform rejected the upload (422): [{"loc": ["body", "run"]'),
    (400, b"not json", "the platform rejected the upload (400): not json"),
])
def test_client_errors_are_not_retried(platform, status, body, message):
    platform.reply(status, body)
    fake = FakeTime()

    with pytest.raises(UploadError) as info:
        send(collect(platform), fake)
    assert message in str(info.value)
    assert fake.sleeps == [] and len(platform.requests) == 1


def test_the_servers_detail_is_cut_to_500_characters(platform):
    platform.reply(422, {"detail": "x" * 2000})

    with pytest.raises(UploadError) as info:
        send(collect(platform))
    assert str(info.value).endswith("x" * 500)
    assert "x" * 501 not in str(info.value)


@pytest.mark.parametrize("status", [301, 307, 308])
def test_redirects_are_not_followed(platform, status):
    # Following would re-send the Authorization header to wherever Location points
    platform.reply(status, headers={"Location": platform.url + "/elsewhere"})

    with pytest.raises(UploadError, match=f"redirected to {platform.url}/elsewhere \\({status}\\)"):
        send(collect(platform))
    assert [r["path"] for r in platform.requests] == ["/api/v1/collect/runs"]


@pytest.fixture
def not_tls():
    """A port that answers a TLS ClientHello with plain HTTP, which fails the handshake at once.

    The ClientHello is read before answering: closing a socket with unread data sends a reset,
    which the client would see as a (retryable) dropped connection instead of a TLS error.
    """
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)

    def serve():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn:
                conn.recv(65536)
                conn.sendall(b"HTTP/1.0 400 Bad Request\r\n\r\n")

    threading.Thread(target=serve, daemon=True).start()
    yield f"https://127.0.0.1:{listener.getsockname()[1]}/api/v1/collect/runs"
    listener.close()


def test_tls_errors_are_not_retried(not_tls):
    fake = FakeTime()

    with pytest.raises(UploadError, match="TLS error .*--ca-file"):
        send(not_tls, fake, context=make_context(None))
    assert fake.sleeps == []


@pytest.mark.parametrize("url, endpoint", [
    ("https://qav.acme.test", "https://qav.acme.test/api/v1/collect/runs"),
    ("https://qav.acme.test/", "https://qav.acme.test/api/v1/collect/runs"),
    (" https://qav.acme.test:8443 ", "https://qav.acme.test:8443/api/v1/collect/runs"),
    ("http://localhost:8080", "http://localhost:8080/api/v1/collect/runs"),
    ("http://127.0.0.1:9", "http://127.0.0.1:9/api/v1/collect/runs"),
    ("http://[::1]:9", "http://[::1]:9/api/v1/collect/runs"),
])
def test_endpoint_for(url, endpoint):
    assert endpoint_for(url) == endpoint


@pytest.mark.parametrize("url", ["http://qav.acme.test", "ftp://qav.acme.test", "qav.acme.test", "", "https://", "http://[::1"])
def test_endpoint_for_refuses_what_cannot_work(url):
    with pytest.raises(ConfigError, match="https://"):
        endpoint_for(url)


def test_make_context_refuses_an_unusable_ca_file(tmp_path):
    not_a_cert = tmp_path / "not-a-cert.pem"
    not_a_cert.write_text("hello")

    for path in (str(not_a_cert), str(tmp_path / "missing.pem")):
        with pytest.raises(ConfigError, match="cannot use --ca-file"):
            make_context(path)
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `$PY -m pytest tests/test_upload.py -q`
Expected: collection error `ImportError: cannot import name 'upload' from 'qav_collector'`.

- [ ] **Step 4: Write the module**

`collector/src/qav_collector/upload.py`:

```python
"""POST one part to /api/v1/collect/runs, retrying what is worth retrying."""
from __future__ import annotations

import http.client
import json
import math
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Mapping, Optional, Tuple

from qav_collector import __version__
from qav_collector.payload import Part

COLLECT_PATH = "/api/v1/collect/runs"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (1, 2, 4, 8)
TIME_BUDGET_SECONDS = 120
MAX_RETRY_AFTER_SECONDS = 10
MAX_DETAIL_CHARS = 500


class ConfigError(Exception):
    """A setting that can never work."""


class UploadError(Exception):
    """The platform did not store the part."""


def endpoint_for(url: str) -> str:
    url = url.strip()
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        parts, host = None, None
    secure = parts is not None and parts.scheme == "https" and bool(host)
    local = parts is not None and parts.scheme == "http" and host in LOCAL_HOSTS
    if not (secure or local):
        raise ConfigError(f"QAV_URL must be an https:// URL (http:// only for localhost), got {url!r}")
    return url.rstrip("/") + COLLECT_PATH


def make_context(ca_file: Optional[str]) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if ca_file:
        try:
            context.load_verify_locations(cafile=ca_file)
        except (OSError, ssl.SSLError) as exc:
            raise ConfigError(f"cannot use --ca-file {ca_file}: {exc}") from None
    return context


def upload_part(
    endpoint: str,
    api_key: str,
    part: Part,
    context: Optional[ssl.SSLContext] = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    rand: Callable[[], float] = random.random,
) -> Tuple[int, dict]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Always sent: a retried POST whose first attempt was stored is then replayed, not stored twice
        "Idempotency-Key": part.idempotency_key,
        "User-Agent": f"qav-collector/{__version__}",
    }
    started = clock()
    attempt = 0
    while True:
        attempt += 1
        try:
            status, body, response_headers = _send(endpoint, part.body, headers, context)
        except (OSError, http.client.HTTPException) as exc:
            if _is_tls_error(exc):
                raise UploadError(
                    f"TLS error talking to the platform ({_reason(exc)}); if it uses a private CA, pass --ca-file"
                ) from None
            problem, wait = f"cannot reach the platform ({_reason(exc)})", _backoff(attempt, rand)
        else:
            if status in (200, 201):
                return status, _json(body)
            if status == 429:
                problem, wait = "the platform answered 429", _retry_after(response_headers)
            elif status >= 500:
                problem, wait = f"the platform answered {status}", _backoff(attempt, rand)
            else:
                raise UploadError(_explain(status, body, response_headers))
        if attempt >= MAX_ATTEMPTS:
            raise UploadError(f"{problem}; gave up after {attempt} attempts")
        if clock() - started + wait > TIME_BUDGET_SECONDS:
            raise UploadError(f"{problem}; gave up after {TIME_BUDGET_SECONDS} s")
        sleep(wait)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Following a redirect would re-send the Authorization header to wherever it points
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _send(
    endpoint: str, body: bytes, headers: Mapping[str, str], context: Optional[ssl.SSLContext]
) -> Tuple[int, bytes, Mapping[str, str]]:
    # build_opener keeps the default ProxyHandler, so HTTPS_PROXY / NO_PROXY are honoured
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _NoRedirect)
    request = urllib.request.Request(endpoint, data=body, headers=dict(headers), method="POST")
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(), exc.headers
        finally:
            exc.close()


def _is_tls_error(exc: BaseException) -> bool:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    # An EOF during the handshake is a dropped connection, worth retrying; the rest will not heal
    return isinstance(reason, ssl.SSLError) and not isinstance(reason, ssl.SSLEOFError)


def _reason(exc: BaseException) -> str:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return str(reason) or type(reason).__name__


def _backoff(attempt: int, rand: Callable[[], float]) -> float:
    base = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]
    return base * (1 + 0.25 * rand())


def _retry_after(headers: Mapping[str, str]) -> float:
    try:
        seconds = float(headers.get("Retry-After") or "")
    except ValueError:
        return 1.0
    if not math.isfinite(seconds) or seconds < 0:
        return 1.0
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def _json(body: bytes) -> dict:
    try:
        value = json.loads(body)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _explain(status: int, body: bytes, headers: Mapping[str, str]) -> str:
    if status == 401:
        return "the API key is invalid or revoked (401)"
    if status == 409:
        return "this Idempotency-Key was already used for different results (409)"
    if 300 <= status < 400:
        return f"the platform redirected to {headers.get('Location', '?')} ({status}); set QAV_URL to that address"
    return f"the platform rejected the upload ({status}): {_detail(body)}"


def _detail(body: bytes) -> str:
    try:
        detail = json.loads(body)["detail"]
    except (ValueError, KeyError, TypeError):
        text = body.decode("utf-8", errors="replace")
    else:
        text = detail if isinstance(detail, str) else json.dumps(detail)
    return text[:MAX_DETAIL_CHARS]
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `$PY -m pytest -q`
Expected: all tests pass, no errors. `test_an_unreachable_platform_is_retried_until_the_attempt_budget` takes a few seconds on Windows (a refused connect is retried by the OS); that is expected.

If `test_tls_errors_are_not_retried` sees a `ConnectionResetError` instead of an `ssl.SSLError` on some platform, fix the `not_tls` fixture (it must drain the ClientHello before answering), never `_is_tls_error`: connection resets must stay retryable.

- [ ] **Step 6: Commit**

```bash
cd ..
git status --short
git add collector/src/qav_collector/upload.py collector/tests/conftest.py collector/tests/test_upload.py
git commit -m "feat(collector): upload with retries, a time budget, and no redirects

Retries connection errors, timeouts and 5xx with 1/2/4/8 s backoff and
jitter, honours Retry-After on 429 (capped at 10 s), stops after 5
attempts or 120 s, and never retries 4xx or TLS failures. Redirects are
not followed, so the API key is never re-sent elsewhere.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Command line

**Files:**
- Create: `collector/src/qav_collector/cli.py`
- Create: `collector/src/qav_collector/__main__.py`
- Test: `collector/tests/test_cli.py`

**Interfaces:**
- Consumes: `junit.parse_file`, `ParsedFile` (Task 1); `ci.detect`, `ci.sanitize_key` (Task 2); `payload.run_times`, `build_run`, `build_parts`, `summarize` (Task 3); `upload.ConfigError`, `UploadError`, `endpoint_for`, `make_context`, `upload_part` (Task 4); the `platform` fixture (Task 4's `conftest.py`).
- Produces:
  - `qav_collector.cli.main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None, *, now=<utc now>, sleep=time.sleep, clock=time.monotonic) -> int` (the exit code; the console script calls `sys.exit` on it)
  - `python -m qav_collector` runs `main`.
  - stderr messages the Task 6 smoke script parses: `qav: uploaded run <id> (<status>)`, and for several parts `qav: uploaded run <id> (<status>), part <n> of <total>`.

- [ ] **Step 1: Write the failing tests**

`collector/tests/test_cli.py`:

```python
import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from qav_collector import __version__, cli, payload
from qav_collector.cli import main

KEY = "qav_cli_secret_key"
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
CONFIGURED = {"QAV_URL": "https://qav.acme.test", "QAV_API_KEY": KEY}


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "reports" / "junit.xml"
    path.parent.mkdir()
    path.write_text(REPORT, encoding="utf-8")
    return path


def env_for(platform, **extra):
    return {"QAV_URL": platform.url, "QAV_API_KEY": KEY, **extra}


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
    assert "qav: parsed 1 file(s), 2 results (1 failed, 0 errored, 0 skipped)" in err
    assert "qav: uploaded run 42 (201)" in err


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
    assert platform.requests[0]["headers"]["Idempotency-Key"] == "gh-123-2-test"


def test_flags_beat_variables(platform, report):
    platform.reply(201, RECEIPT)
    env = env_for(platform, **GITHUB, QAV_BRANCH="from-env", QAV_IDEMPOTENCY_KEY="from env")

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
    env = env_for(platform, **GITHUB, QAV_BRANCH="from-env", QAV_COMMIT="b" * 40,
                  QAV_IDEMPOTENCY_KEY="from env", QAV_CI_PROVIDER="other")

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
    assert "qav: dry run: 1 part(s), nothing uploaded" in captured.err


def test_parts_are_uploaded_in_order_and_a_failure_names_what_was_stored(platform, report, monkeypatch, capsys):
    monkeypatch.setattr(payload, "MAX_RESULTS_PER_PART", 1)
    platform.reply(201, RECEIPT)
    platform.reply(401, {"detail": "Invalid API key"})

    assert run(["upload", str(report), "--idempotency-key", "job-7"], env_for(platform)) == 0
    assert [r["headers"]["Idempotency-Key"] for r in platform.requests] == ["job-7-part-1", "job-7-part-2"]
    err = capsys.readouterr().err
    assert "qav: uploaded run 42 (201), part 1 of 2" in err
    assert "qav: upload failed: the API key is invalid or revoked (401)" in err
    assert "qav: stored before the failure: run 42 (part 1 of 2)" in err
    assert "qav: not failing the build (pass --fail-on-error to change that)" in err


def test_an_upload_failure_exits_0_by_default(platform, report):
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(["upload", str(report)], env_for(platform)) == 0


@pytest.mark.parametrize("argv_extra, env_extra", [
    (["--fail-on-error"], {}),
    ([], {"QAV_FAIL_ON_ERROR": "1"}),
    ([], {"QAV_FAIL_ON_ERROR": "true"}),
])
def test_fail_on_error_exits_1(platform, report, argv_extra, env_extra):
    platform.reply(401, {"detail": "Invalid API key"})
    assert run(["upload", str(report), *argv_extra], env_for(platform, **env_extra)) == 1


@pytest.mark.parametrize("argv_extra, env, message", [
    ([], {"QAV_API_KEY": KEY}, "QAV_URL is not set"),
    ([], {"QAV_URL": "https://qav.acme.test"}, "QAV_API_KEY is not set"),
    ([], {"QAV_URL": "http://qav.acme.test", "QAV_API_KEY": KEY}, "must be an https:// URL"),
    (["--ca-file", "missing.pem"], CONFIGURED, "cannot use --ca-file"),
    ([], {**CONFIGURED, "QAV_CA_FILE": "missing.pem"}, "cannot use --ca-file"),
    ([], {**CONFIGURED, "QAV_CI_PROVIDER": "travis"}, "QAV_CI_PROVIDER must be one of"),
    (["--fail-on-error"], {"QAV_API_KEY": KEY}, "QAV_URL is not set"),
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
    assert "qav: no test results found" in capsys.readouterr().err


def test_skipped_files_are_reported_and_the_rest_uploaded(platform, report, capsys):
    broken = report.parent / "broken.xml"
    broken.write_text("<testsuite>", encoding="utf-8")
    platform.reply(201, RECEIPT)

    assert run(["upload", str(report.parent / "*.xml")], env_for(platform)) == 0
    assert len(sent(platform)["results"]) == 2
    err = capsys.readouterr().err
    assert f"qav: skipped {broken}: not well-formed XML" in err
    assert "parsed 1 file(s)" in err


def test_usage_errors_exit_2(capsys):
    assert run([], {}) == 2
    assert run(["upload"], {}) == 2
    assert run(["upload", "x.xml", "--ci-provider", "travis"], {}) == 2


def test_version(capsys):
    assert run(["--version"], {}) == 0
    assert capsys.readouterr().out.strip() == f"qav-collector {__version__}"


def test_python_dash_m_runs_the_cli():
    completed = subprocess.run([sys.executable, "-m", "qav_collector", "--version"], capture_output=True, text=True)
    assert completed.returncode == 0
    assert completed.stdout.strip() == f"qav-collector {__version__}"


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
    assert "qav: unexpected error: RuntimeError: boom ***" in err
    assert KEY not in err
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `$PY -m pytest tests/test_cli.py -q`
Expected: collection error `ImportError: cannot import name 'cli' from 'qav_collector'`.

- [ ] **Step 3: Write the CLI**

`collector/src/qav_collector/cli.py`:

```python
"""qav-collector command line: parse JUnit XML reports and upload them as one run."""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Mapping, Optional, Sequence

from qav_collector import __version__
from qav_collector.ci import detect, sanitize_key
from qav_collector.junit import parse_file
from qav_collector.payload import build_parts, build_run, run_times, summarize
from qav_collector.upload import ConfigError, UploadError, endpoint_for, make_context, upload_part

CI_PROVIDERS = ("github_actions", "gitlab_ci", "jenkins", "other", "local")
_TRUE = ("1", "true", "yes")


class _UploadFailed(Exception):
    pass


class _Output:
    """One stderr line per message, prefixed "qav:"; the API key never reaches them."""

    def __init__(self, secret: str):
        self.secret = secret

    def __call__(self, message: str) -> None:
        if self.secret:
            message = message.replace(self.secret, "***")
        line = f"qav: {message}"
        try:
            print(line, file=sys.stderr)
        except UnicodeEncodeError:  # a console that cannot show the characters
            print(line.encode("ascii", "backslashreplace").decode("ascii"), file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qav-collector", description="Upload JUnit XML test results to the QA Vision platform."
    )
    parser.add_argument("--version", action="version", version=f"qav-collector {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    upload = commands.add_parser(
        "upload",
        help="parse JUnit XML files and upload them as one run",
        description="Parse the JUnit XML files matching PATTERN (** matches any directories) and upload "
        "them as one run. The API key is read from the QAV_API_KEY environment variable only.",
    )
    upload.add_argument("patterns", nargs="+", metavar="PATTERN")
    upload.add_argument("--url", help="platform URL (default: $QAV_URL)")
    upload.add_argument("--ci-provider", choices=CI_PROVIDERS, help="default: $QAV_CI_PROVIDER, else detected")
    upload.add_argument("--branch", help="default: $QAV_BRANCH, else detected")
    upload.add_argument("--commit", help="full or short SHA (default: $QAV_COMMIT, else detected)")
    upload.add_argument("--ci-run-url", help="default: $QAV_CI_RUN_URL, else detected")
    upload.add_argument("--environment", help="e.g. staging (default: $QAV_ENVIRONMENT)")
    upload.add_argument("--idempotency-key", help="default: $QAV_IDEMPOTENCY_KEY, else derived from the CI job")
    upload.add_argument("--ca-file", help="extra CA certificate to trust (default: $QAV_CA_FILE)")
    upload.add_argument("--fail-on-error", action="store_true",
                        help="exit 1 if the upload fails (default: $QAV_FAIL_ON_ERROR)")
    upload.add_argument("--dry-run", action="store_true", help="print the JSON that would be sent; upload nothing")
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    env = os.environ if env is None else env
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, --version, usage errors
        return exc.code if isinstance(exc.code, int) else 2
    if args.command is None:
        parser.print_usage(sys.stderr)
        return 2

    api_key = env.get("QAV_API_KEY", "").strip()
    say = _Output(api_key)
    fail_on_error = args.fail_on_error or env.get("QAV_FAIL_ON_ERROR", "").strip().lower() in _TRUE
    try:
        return _upload(args, env, api_key, say, now=now, sleep=sleep, clock=clock)
    except ConfigError as exc:
        say(str(exc))
        return 2
    except _UploadFailed:
        pass
    except Exception as exc:  # a bug in the collector must not break the build either
        say(f"unexpected error: {type(exc).__name__}: {exc}")
    if fail_on_error:
        return 1
    say("not failing the build (pass --fail-on-error to change that)")
    return 0


def _upload(args, env: Mapping[str, str], api_key: str, say: _Output, *, now, sleep, clock) -> int:
    def pick(flag: Optional[str], name: str, detected: Optional[str] = None) -> Optional[str]:
        return (flag or "").strip() or env.get(name, "").strip() or detected

    endpoint, context = "", None
    if not args.dry_run:
        url = pick(args.url, "QAV_URL")
        if not url:
            raise ConfigError("QAV_URL is not set (or pass --url)")
        if not api_key:
            raise ConfigError("QAV_API_KEY is not set; the API key is read from the environment only")
        endpoint = endpoint_for(url)
        context = make_context(pick(args.ca_file, "QAV_CA_FILE"))

    ci = detect(env)
    provider = pick(args.ci_provider, "QAV_CI_PROVIDER", ci.provider)
    if provider not in CI_PROVIDERS:
        raise ConfigError(f"QAV_CI_PROVIDER must be one of {', '.join(CI_PROVIDERS)}, got {provider!r}")

    files = _expand(args.patterns)
    if not files:
        raise ConfigError(f"no file matched {' '.join(args.patterns)}")
    parsed = [parse_file(path) for path in files]
    for report in parsed:
        for warning in report.warnings:
            say(warning)
    results = [result for report in parsed for result in report.results]
    if not results:
        say("no test results found")
        return 0
    counts = summarize(results)
    say(
        f"parsed {sum(1 for report in parsed if not report.skipped)} file(s), {len(results)} results "
        f"({counts['failed']} failed, {counts['errored']} errored, {counts['skipped']} skipped)"
    )

    started, finished = run_times(
        [stamp for report in parsed for stamp in report.suite_timestamps],
        sum(report.suite_seconds for report in parsed),
        results,
        now(),
    )
    run = build_run(
        ci_provider=provider,
        started_at=started,
        finished_at=finished,
        ci_run_url=pick(args.ci_run_url, "QAV_CI_RUN_URL", ci.run_url),
        commit_sha=pick(args.commit, "QAV_COMMIT", ci.commit),
        branch=pick(args.branch, "QAV_BRANCH", ci.branch),
        environment=pick(args.environment, "QAV_ENVIRONMENT"),
    )
    # Outside CI there is nothing stable to derive a key from; a random one still makes the
    # collector's own retries safe
    key = sanitize_key(pick(args.idempotency_key, "QAV_IDEMPOTENCY_KEY", ci.idempotency_key) or "")
    parts = build_parts(run, results, key or f"local-{uuid.uuid4()}")

    if args.dry_run:
        for part in parts:
            print(json.dumps(json.loads(part.body), indent=2))
        say(f"dry run: {len(parts)} part(s), nothing uploaded")
        return 0

    stored: List[str] = []
    for number, part in enumerate(parts, start=1):
        of = f"part {number} of {len(parts)}"
        try:
            status, receipt = upload_part(endpoint, api_key, part, context, sleep=sleep, clock=clock)
        except UploadError as exc:
            say(f"upload failed: {exc}")
            if stored:
                say(f"stored before the failure: {', '.join(stored)}")
            raise _UploadFailed() from None
        run_id = receipt.get("id", "?")
        say(f"uploaded run {run_id} ({status})" + (f", {of}" if len(parts) > 1 else ""))
        stored.append(f"run {run_id} ({of})")
    return 0


def _expand(patterns: Sequence[str]) -> List[str]:
    files: List[str] = []
    seen = set()
    for pattern in patterns:
        for path in sorted(glob.glob(pattern, recursive=True)):
            identity = os.path.normcase(os.path.realpath(path))
            if os.path.isfile(path) and identity not in seen:
                seen.add(identity)
                files.append(path)
    return files
```

`collector/src/qav_collector/__main__.py`:

```python
from qav_collector.cli import main

raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `$PY -m pytest -q`
Expected: all tests pass, no errors.

- [ ] **Step 5: Try the real entry point**

Run (from `collector/`):

```bash
.venv/Scripts/qav-collector --version          # .venv/bin/qav-collector on Linux/macOS
.venv/Scripts/qav-collector upload "tests/fixtures/*.xml" --dry-run > /dev/null; echo "exit $?"
.venv/Scripts/qav-collector upload "tests/fixtures/*.xml"; echo "exit $?"
```

Expected: `qav-collector 0.1.0`; then `qav: parsed 4 file(s), 12 results (4 failed, 1 errored, 2 skipped)`, `qav: dry run: 1 part(s), nothing uploaded`, `exit 0`; then `qav: QAV_URL is not set (or pass --url)`, `exit 2`.

- [ ] **Step 6: Commit**

```bash
cd ..
git status --short
git add collector/src/qav_collector/cli.py collector/src/qav_collector/__main__.py collector/tests/test_cli.py
git commit -m "feat(collector): qav-collector upload command

Flags beat QAV_* variables beat CI detection; the API key comes from
QAV_API_KEY only and is scrubbed from every line of output. --dry-run
prints the JSON. Exit 0 on success or (by default) on a failed upload,
1 with --fail-on-error, 2 on a usage or configuration error.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: CI job and end-to-end upload through the stack

**Files:**
- Modify: `.github/workflows/ci.yml` (new `collector` job after the `smoke` job)
- Modify: `scripts/smoke_gateway.sh` (collector block inserted after the `... with the failed result` check and before `revoke the key`)

**Interfaces:**
- Consumes: `python -m qav_collector upload` and its `qav: uploaded run <id> (<status>)` line (Task 5); the smoke script's existing `$BASE`, `$API_KEY`, `$TMP`, `AUTH`, `check`, `body_has`, `pass`, `fail`.
- Produces: 4 more smoke checks (the script prints `all gateway checks passed` when everything passes).

Ruling carried from the spec: the smoke test runs the collector from `collector/src` with `python -m qav_collector` instead of installing it, so the script also works on a developer machine without touching its Python; installing (`pip install .`) and the `qav-collector` entry point are verified by the `collector` job.

- [ ] **Step 1: Add the `collector` job**

In `.github/workflows/ci.yml`, insert this job between the `smoke` job and the `gateway` job (same indentation as `smoke:`):

```yaml
  collector:
    name: Collector (Python ${{ matrix.python }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        # The oldest supported version and a current one
        python: ["3.9", "3.12"]
    defaults:
      run:
        working-directory: collector
    steps:
      - uses: actions/checkout@v7

      - uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python }}

      # A regular (not editable) install, so the tests run against the package as customers get it
      - name: Install the collector and pytest
        run: python -m pip install . pytest

      - name: The entry point works
        run: qav-collector --version

      - name: Run tests
        run: python -m pytest -q
```

- [ ] **Step 2: Add the end-to-end block to the smoke script**

In `scripts/smoke_gateway.sh`, insert after the line `body_has "... with the failed result" '"name":"fails"'` and before `check "revoke the key" ...` (the key must still be valid):

```bash

# ---- the collector, end to end: JUnit file -> qav-collector -> gateway -> ingestion ----
# Runs from collector/src, so nothing is installed; the CI collector job covers installing it.
PY=""
for candidate in python3 python; do
  if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  fail "collector: no Python 3.9+ found (tried python3, python)"
else
  # The gateway's self-signed certificate, so the collector verifies TLS instead of skipping it
  docker compose exec -T gateway cat /etc/nginx/certs/tls.crt > "$TMP/gateway.crt"
  cat > "$TMP/junit.xml" <<'XML'
<testsuites>
  <testsuite name="smoke">
    <testcase classname="smoke" name="passes" time="0.1"/>
    <testcase classname="smoke" name="fails" time="0.2"><failure message="boom">boom</failure></testcase>
    <testcase classname="smoke" name="skips"><skipped/></testcase>
  </testsuite>
</testsuites>
XML
  if (cd collector/src && QAV_URL="$BASE" QAV_API_KEY="$API_KEY" "$PY" -m qav_collector upload \
        "$TMP/junit.xml" --ca-file "$TMP/gateway.crt" --branch smoke-collector --fail-on-error) \
        2>"$TMP/collector_err"; then
    pass "collector uploads a JUnit file through the gateway"
  else
    fail "collector upload: $(tail -c 400 "$TMP/collector_err")"
  fi
  if grep -qF -- "$API_KEY" "$TMP/collector_err"; then
    fail "collector output contains the API key"
  else
    pass "collector output never shows the API key"
  fi
  COLLECTOR_RUN_ID="$(sed -n 's/.*uploaded run \([0-9][0-9]*\).*/\1/p' "$TMP/collector_err" | head -1)"
  check "read the collector's run" 200 GET "$BASE/api/v1/runs/${COLLECTOR_RUN_ID:-0}" "${AUTH[@]}"
  body_has "... with the collector's counts" '"total":3,"passed":1,"failed":1,"skipped":1,"errored":0'
fi
```

- [ ] **Step 3: Check the field order the counts assertion relies on**

Run: `grep -n "total\|passed\|failed\|skipped\|errored" platforms/ingestion-service/src/ingestion/schemas/run.py`
Expected: in `RunOut`, `total`, `passed`, `failed`, `skipped`, `errored` are declared consecutively in that order (FastAPI serialises fields in declaration order, so `'"total":3,"passed":1,"failed":1,"skipped":1,"errored":0'` appears verbatim). If the order differs, split the `body_has` into one check per field and record a ledger ruling.

- [ ] **Step 4: Run the smoke test locally**

Run (repository root, Git Bash; port 8080 is taken on this machine, hence `GATEWAY_HTTP_PORT`):

```bash
export SECRET_KEY=local-smoke-secret GATEWAY_HTTP_PORT=18080
docker compose up -d --build --wait --wait-timeout 300 gateway
bash scripts/smoke_gateway.sh
```

Expected: every line starts with `ok`, including `ok    collector uploads a JUnit file through the gateway`, `ok    collector output never shows the API key`, `ok    read the collector's run (200)`, `ok    ... with the collector's counts`; last line `all gateway checks passed`.

If the collector upload fails with `TLS error ... certificate verify failed` only under Python 3.13+ (its default `VERIFY_X509_STRICT`), the gateway's generated certificate is missing an extension strict mode requires: add `-addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,digitalSignature,keyCertSign"` to the `openssl req` command in `gateway/entrypoint.sh`, delete the stored certificate (`docker compose exec gateway rm /etc/nginx/certs/tls.crt /etc/nginx/certs/tls.key` then `docker compose restart gateway`), re-run, and record a ledger ruling. Do not add any option to disable verification.

Then stop the stack (keep the data volume):

```bash
docker compose down
```

- [ ] **Step 5: Commit**

```bash
git status --short
git add .github/workflows/ci.yml scripts/smoke_gateway.sh
git commit -m "ci: collector tests on Python 3.9 and 3.12; end-to-end upload in the smoke test

The gateway smoke test now uploads a JUnit file with qav-collector
through the running stack (TLS verified against the gateway's
certificate), checks the key never appears in its output, and reads the
run back to compare the counts.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Documentation and TODO

**Files:**
- Modify: `collector/README.md` (full content)
- Modify: `README.md` (project structure)
- Modify: `TODO.md` (collector done; nice-to-have list)

**Interfaces:**
- Consumes: the CLI options, messages and exit codes from Task 5; the install tag from the spec.
- Produces: documentation only.

- [ ] **Step 1: Write the collector README**

Replace `collector/README.md` with:

````markdown
# qav-collector

Uploads JUnit XML test results from a CI job to the QA Vision platform. Standard library only,
Python 3.9 or newer, nothing else to install.

## Install

```bash
pip install "qav-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.1.0#subdirectory=collector"
```

## Use

Create an API key for the project in the platform, store it as a CI secret named `QAV_API_KEY`,
and run the collector after the tests — also when they fail:

```bash
export QAV_URL=https://qav.example.com
qav-collector upload "reports/**/*.xml"
```

All matching files become **one run**. On GitHub Actions, GitLab CI and Jenkins the commit, branch
and job URL are detected automatically, and a re-run of the same job replays the run it already
stored instead of storing it twice.

### GitHub Actions

```yaml
      - name: Run tests
        run: pytest --junitxml=reports/junit.xml

      - name: Upload results to QA Vision
        if: always()
        env:
          QAV_URL: https://qav.example.com
          QAV_API_KEY: ${{ secrets.QAV_API_KEY }}
        run: |
          pip install "qav-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.1.0#subdirectory=collector"
          qav-collector upload "reports/**/*.xml"
```

### GitLab CI

```yaml
test:
  script:
    - pytest --junitxml=reports/junit.xml
  after_script:
    - pip install "qav-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.1.0#subdirectory=collector"
    - qav-collector upload "reports/**/*.xml"
  variables:
    QAV_URL: https://qav.example.com
  # QAV_API_KEY: a masked CI/CD variable in the project settings
```

### Jenkins

```groovy
post {
  always {
    withCredentials([string(credentialsId: 'qav-api-key', variable: 'QAV_API_KEY')]) {
      sh '''
        pip install "qav-collector @ git+https://github.com/atriis/Atriis.QEOS@collector-v0.1.0#subdirectory=collector"
        QAV_URL=https://qav.example.com qav-collector upload "target/surefire-reports/*.xml"
      '''
    }
  }
}
```

### See what would be sent

```bash
qav-collector upload "reports/**/*.xml" --dry-run
```

prints the JSON and uploads nothing; no URL or key is needed.

## Options

Each option can also be set with the environment variable next to it. A flag wins over the
variable, and both win over what is detected from the CI system.

| Option | Variable | Meaning |
|---|---|---|
| `--url` | `QAV_URL` | Platform URL (required unless `--dry-run`) |
| — | `QAV_API_KEY` | The project's API key. Environment only, never a flag |
| `--ci-provider` | `QAV_CI_PROVIDER` | `github_actions`, `gitlab_ci`, `jenkins`, `other` or `local` |
| `--branch` | `QAV_BRANCH` | Branch name |
| `--commit` | `QAV_COMMIT` | Commit SHA (7 to 40 hex characters; anything else is left out) |
| `--ci-run-url` | `QAV_CI_RUN_URL` | Link to the CI job |
| `--environment` | `QAV_ENVIRONMENT` | e.g. `staging` |
| `--idempotency-key` | `QAV_IDEMPOTENCY_KEY` | Overrides the key derived from the CI job |
| `--ca-file` | `QAV_CA_FILE` | Extra CA certificate to trust (a private CA, or the local stack's self-signed one) |
| `--fail-on-error` | `QAV_FAIL_ON_ERROR=1` | Exit 1 if the upload fails |
| `--dry-run` | — | Print the JSON; upload nothing |

## Exit codes

| Code | When |
|---|---|
| 0 | Uploaded; nothing to upload; or the upload failed and `--fail-on-error` is not set |
| 1 | The upload failed and `--fail-on-error` is set |
| 2 | A usage or configuration error: no URL or key, no file matched, an `http://` URL that is not localhost, an unusable `--ca-file` |

By default an unreachable platform never turns a build red; a misconfigured collector always does.

## What it does with the files

- Reads `<testsuites>`/`<testsuite>` reports: pytest, Maven Surefire, Playwright, cucumber-js and
  anything else that writes JUnit XML. A test's status is `errored` if it has an `<error>`,
  else `failed` for `<failure>`, else `skipped` for `<skipped>`, else `passed`. Surefire's
  `flakyFailure`/`rerunFailure` elements are earlier attempts and are ignored.
- Skips, with a warning, files over 50 MB, files that are not well-formed XML, and files that
  declare a DOCTYPE or entities (JUnit never needs one; refusing them blocks XML entity attacks).
- Cuts failure messages and output to 64 KB, as the platform does.
- More than 20,000 results (or 9 MB) are sent as several runs, `part 1 of N` and so on.

## Network and security

- HTTPS is required, except for `http://localhost`, `127.0.0.1` and `::1`.
- Certificates are always verified; there is no option to turn that off. Use `--ca-file` for a
  private CA.
- `HTTPS_PROXY` and `NO_PROXY` are honoured.
- Redirects are not followed, so the key is never sent anywhere but `QAV_URL`.
- Retries: connection errors, timeouts and 5xx answers are retried after 1, 2, 4 and 8 seconds;
  429 waits for `Retry-After` (at most 10 s). At most 5 attempts and 2 minutes per run.
- The API key is never printed.

## Develop

```bash
cd collector
uv venv --seed --python 3.9 .venv
.venv/Scripts/python -m pip install -e . pytest    # .venv/bin/python on Linux/macOS
.venv/Scripts/python -m pytest -q
```

A release is a git tag `collector-v<version>` on this repository, matching `__version__` in
`src/qav_collector/__init__.py`.
````

- [ ] **Step 2: Add the collector to the root README's project structure**

In `README.md`, in the project structure block, after the line `├── gateway/                        # NGINX gateway: routing, rate limits, TLS`, add:

```
├── collector/                      # qav-collector: uploads JUnit results from CI (see collector/README.md)
```

- [ ] **Step 3: Update TODO.md**

In `TODO.md`, replace the line

```
- [ ] Collector agent MVP (JUnit XML parser, uploader with retry) — *next spec*
```

with

```
- [x] Collector agent MVP (JUnit XML parser, uploader with retry) — `collector/`, see below
```

and insert, immediately before the line `### Phase 4: Test Management`, this block:

```markdown
### Collector agent (Phase 2, step 2)
- [x] `qav-collector upload`: JUnit XML (pytest, Surefire, Playwright, cucumber-js), one run per CI job
- [x] GitHub Actions, GitLab CI and Jenkins detection; retry-safe Idempotency-Keys; parts past 20,000 results / 9 MB
- [x] Retries with backoff and a 2-minute budget; HTTPS and verified TLS; the key never printed
- [x] CI: tests on Python 3.9 and 3.12; end-to-end upload through the gateway in the smoke test
- [ ] Tag `collector-v0.1.0` (maintainer)
- [ ] Phase 2 exit criteria: agents on 3 CI platforms in real projects; 10k test executions ingested

### Collector — nice to have
Distribution
- [ ] Publish to PyPI (trusted publishing from a tag): `pip install qav-collector`, `pipx run qav-collector`
- [ ] A ready-made GitHub Action (`uses: …/qav-collector@v1`) and a GitLab CI component
- [ ] A Jenkins shared-library step
- [ ] A Docker image and a single-file (zipapp) build for runners without pip

Formats
- [ ] Cucumber JSON (features, scenarios, tags, steps) — needs ingestion fields for tags and steps
- [ ] Playwright JSON (retries, attachments, projects/browsers)
- [ ] TestNG XML, NUnit XML, xUnit.net XML, .NET TRX

Richer data
- [ ] Keep each retry attempt as its own result, so flaky tests become visible
- [ ] Git metadata: commit author and message, pull-request number, base branch
- [ ] Test ownership from CODEOWNERS
- [ ] Artifact upload (screenshots, videos, traces) once ingestion accepts them

Reliability and operations
- [ ] Keep a failed upload on disk and `qav-collector retry` it later
- [ ] Stream partial results during long runs instead of one upload at the end
- [ ] `qav-collector check`: verify the URL, certificate and key without uploading
- [ ] A `.qav.yml` config file as an alternative to flags and environment variables
- [ ] Client certificates (mTLS) — roadmap Phase 2
```

- [ ] **Step 4: Check the documents**

Run (from `collector/`): `$PY -m pytest -q` — Expected: all pass (the README is packaged as the long description; nothing else changed).
Run (repository root): `grep -n "collector" README.md TODO.md | head -20` — Expected: the structure line, the `[x] Collector agent MVP` line and the two new TODO sections.

- [ ] **Step 5: Commit**

```bash
git status --short
git add collector/README.md README.md TODO.md
git commit -m "docs(collector): README with CI setups, options and exit codes; TODO

Adds the collector to the project structure, marks the MVP done, and
records the nice-to-have list (PyPI, Action/component, more formats,
flaky tracking, offline retry, check command, config file, mTLS).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
