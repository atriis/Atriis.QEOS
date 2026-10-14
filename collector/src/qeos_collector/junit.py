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
    # Surefire records earlier attempts of a re-run test as flakyFailure/flakyError
    # (the test ultimately passed) or rerunFailure/rerunError (it ultimately failed).
    # Each becomes its own result, before the final outcome, so flaky tests become
    # visible as pass+fail within one run. Per-attempt time is not recorded: 0 ms.
    ATTEMPTS = (("flakyFailure", "failed"), ("flakyError", "errored"),
                ("rerunFailure", "failed"), ("rerunError", "errored"))
    for tag, attempt_status in ATTEMPTS:
        for attempt in case.findall(tag):
            row = {
                "suite": suite[:SUITE_LENGTH],
                "class_name": (case.get("classname") or "")[:CLASS_NAME_LENGTH],
                "name": name[:NAME_LENGTH],
                "status": attempt_status,
                "duration_ms": 0,
            }
            text = "".join(attempt.itertext())
            message = attempt.get("message") or _first_line(text)
            if message:
                row["message"] = _cut(message)
            if text.strip():
                row["details"] = _cut(text)
            parsed.results.append(row)

    # Element truthiness means "has children", so compare with None explicitly.
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
        # Clamped before multiplying: a finite 1e306 s would become inf ms, which round() rejects
        "duration_ms": round(min(_seconds(case.get("time")), MAX_DURATION_MS / 1000) * 1000),
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
    try:
        return stamp.astimezone(timezone.utc)
    except OverflowError:  # e.g. 0001-01-01T00:00:00+05:00 falls before datetime.min in UTC
        return None


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _cut(text: str) -> str:
    data = text.encode("utf-8", errors="replace")  # a lone surrogate (a cut emoji in a report) must not abort the parse
    if len(data) <= MAX_TEXT_BYTES:
        return text
    # errors="ignore" drops only the character the cut split in two
    return data[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")
