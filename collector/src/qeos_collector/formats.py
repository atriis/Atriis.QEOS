"""One entry point for every report format: the XML root element picks the
parser. JUnit stays in junit.py; TRX (vstest), NUnit 3, xUnit.net v2 and
TestNG live here, all producing the same result-dict shape. TRX wraps its
elements in a namespace, so matching is on the local name throughout."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from typing import Iterator, Optional
from xml.parsers import expat

from qeos_collector.junit import (
    CLASS_NAME_LENGTH, MAX_DURATION_MS, MAX_FILE_BYTES, NAME_LENGTH, SUITE_LENGTH,
    ParsedFile, _cut, _first_line, _read_xml, _Refused, _seconds, _skip, _timestamp, _walk,
)

_TRX_DURATION = re.compile(r"^(\d+):(\d\d):(\d\d(?:\.\d+)?)$")

_ROOTS = "<testsuites>, <testsuite>, <TestRun> (TRX), <test-run> (NUnit 3), <assemblies> (xUnit.net) or <testng-results>"


def parse_file(path: str) -> ParsedFile:
    parsed = ParsedFile(path=path)
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return _skip(parsed, "larger than 50 MB")
        if _looks_like_json(path):
            return _parse_cucumber_file(path, parsed)
        root = _read_xml(path)
    except _Refused as exc:
        return _skip(parsed, str(exc))
    except expat.ExpatError as exc:
        return _skip(parsed, f"not well-formed XML ({expat.ErrorString(exc.code)}, line {exc.lineno})")
    except OSError as exc:
        return _skip(parsed, f"cannot be read ({exc.strerror or exc})")

    tag = _local(root.tag)
    if tag in ("testsuites", "testsuite"):
        _walk(root, "", False, parsed)
    elif tag == "TestRun":
        _trx(root, parsed)
    elif tag == "test-run":
        _nunit(root, parsed)
    elif tag == "assemblies":
        _xunit(root, parsed)
    elif tag == "testng-results":
        _testng(root, parsed)
    else:
        return _skip(parsed, f"root element is <{tag}>, not one of {_ROOTS}")
    if parsed.unnamed:
        parsed.warnings.append(f"skipped {parsed.unnamed} test case(s) without a name in {path}")
    return parsed


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_all(element: ET.Element, *names: str) -> Iterator[ET.Element]:
    """Descendants matched on local name, in document order."""
    for child in element.iter():
        if _local(child.tag) in names:
            yield child


def _text_of(element: Optional[ET.Element]) -> str:
    return "".join(element.itertext()) if element is not None else ""


def _row(suite: str, class_name: str, name: str, status: str, seconds: float) -> dict:
    return {
        "suite": suite[:SUITE_LENGTH],
        "class_name": class_name[:CLASS_NAME_LENGTH],
        "name": name[:NAME_LENGTH],
        "status": status,
        "duration_ms": round(min(seconds, MAX_DURATION_MS / 1000) * 1000),
    }


def _attach(row: dict, message: str, details: str) -> dict:
    message = message.strip() or _first_line(details)
    if message:
        row["message"] = _cut(message)
    if details.strip():
        row["details"] = _cut(details)
    return row


# --- Cucumber JSON (classic formatter: cucumber-jvm/js/rb) --------------------

# A failed step fails the scenario; an unimplemented one leaves it undecided
_CUCUMBER_FAILED = ("failed",)
_CUCUMBER_UNDECIDED = ("undefined", "pending", "ambiguous")
# Why a skipped scenario stopped at its step: the message sent with it (a hook skip leaves every step "skipped")
_SKIP_REASONS = {"undefined": "Undefined step", "pending": "Pending step", "ambiguous": "Ambiguous step",
                 "skipped": "Skipped"}

# The failed step's step definition and its text with the matched arguments replaced (spec 2026-10-14 §2)
ARGUMENT = "{…}"
DEFINITION_LENGTH = 500
STEP_TEXT_LENGTH = 1000


def _step_definition(step: dict) -> Optional[str]:
    """match.location: the code that ran the step (a file:line, or a method for cucumber-jvm)."""
    match = step.get("match")
    location = match.get("location") if isinstance(match, dict) else None
    if not isinstance(location, str) or not location.strip():
        return None
    return location.strip()[:DEFINITION_LENGTH]


def _code_point_offset(name: str, utf16_offset: int) -> Optional[int]:
    """The index into name (code points) of a UTF-16 code unit offset; None when it falls inside a surrogate pair or
    past the end."""
    units = 0
    for index, char in enumerate(name):
        if units == utf16_offset:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
    return len(name) if units == utf16_offset else None


def _step_pattern(step: dict, keyword: str, name: str) -> str:
    """The step text with each match.arguments value (offsets into the name, after the keyword) replaced by {…}; the
    text itself when there are no arguments or they do not fit the text."""
    text = f"{keyword}{name}".strip()[:STEP_TEXT_LENGTH]
    match = step.get("match")
    arguments = match.get("arguments") if isinstance(match, dict) else None
    if not isinstance(arguments, list):
        return text
    spans = []
    for argument in arguments:
        if not isinstance(argument, dict):
            return text
        value, offset = argument.get("val"), argument.get("offset")
        if value is None or value == "":
            continue  # an optional group that matched nothing
        if not isinstance(value, str) or not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            return text
        if name[offset:offset + len(value)] != value:
            # cucumber-jvm/js count offsets in UTF-16 code units, Python in code points: they differ after an emoji
            offset = _code_point_offset(name, offset)
            if offset is None or name[offset:offset + len(value)] != value:
                return text
        spans.append((offset, offset + len(value)))
    spans.sort()
    if any(start < previous_end for (_, previous_end), (start, _) in zip(spans, spans[1:])):
        return text
    parts, at = [], 0
    for start, end in spans:
        parts += [name[at:start], ARGUMENT]
        at = end
    parts.append(name[at:])
    return f"{keyword}{''.join(parts)}".strip()[:STEP_TEXT_LENGTH]


def _looks_like_json(path: str) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(64).lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith((b"[", b"{"))


def _parse_cucumber_file(path: str, parsed: ParsedFile) -> ParsedFile:
    try:
        with open(path, "rb") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return _skip(parsed, f"not well-formed JSON ({exc})")
    if isinstance(data, dict) and isinstance(data.get("suites"), list) and "config" in data:
        for suite in data["suites"]:
            _playwright_suite(suite, parsed)
        return parsed
    features = [f for f in data if isinstance(f, dict) and "elements" in f] if isinstance(data, list) else []
    if not features:
        return _skip(parsed, "not Cucumber JSON (no features with elements)")
    skips: dict = {}
    for feature in features:
        _cucumber_feature(feature, parsed, skips=skips)
    if skips.get("large"):
        parsed.warnings.append(f"skipped {skips['large']} screenshot(s) over 5 MB in {path}")
    if skips.get("over"):
        parsed.warnings.append(
            f"skipped {skips['over']} screenshot(s) beyond {MAX_SCREENSHOTS_PER_RESULT} per result in {path}")
    if parsed.unnamed:
        parsed.warnings.append(f"skipped {parsed.unnamed} test case(s) without a name in {path}")
    return parsed


# Log lines (spec 2026-10-14 log values §2.2): text attachments only. cucumber-js writes this.log() lines as
# text/x.cucumber.log+plain and the classic JSON formatter base64-encodes every attachment; images and other media
# are never part of the log
LOG_MEDIA_TYPES = ("text/x.cucumber.log+plain", "text/plain")

# Step screenshots (spec 2026-10-19 §5.2): image attachments, each tied to the step it belongs to
IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_SCREENSHOTS_PER_RESULT = 50


def _attachment_fields(attachment: object) -> "Optional[tuple[str, str, bool]]":
    """(media type without parameters, lowercased; data; whether the data is the raw content, not base64) of an
    attachment in any of the field spellings of cucumber's formats; None without a media type or data."""
    if not isinstance(attachment, dict):
        return None
    media = attachment.get("mime_type") or attachment.get("media_type") or attachment.get("mediaType")
    if not isinstance(media, str):
        return None
    data = attachment.get("data") if attachment.get("data") is not None else attachment.get("body")
    if not isinstance(data, str) or not data:
        return None
    # cucumber's message formats name the encoding; the classic JSON never does and always base64-encodes
    encoding = attachment.get("contentEncoding") or attachment.get("content_encoding")
    identity = isinstance(encoding, str) and encoding.strip().upper() == "IDENTITY"
    return media.split(";", 1)[0].strip().lower(), data, identity


def _attachment_text(attachment: object) -> Optional[str]:
    fields = _attachment_fields(attachment)
    if fields is None or fields[0] not in LOG_MEDIA_TYPES:
        return None
    _, data, identity = fields
    if identity:
        return data
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return data  # a formatter that wrote the text itself (it has spaces or other non-base64 characters)
    # A cut multi-byte character or binary bytes under a text media type become U+FFFD, never a failed parse
    return raw.decode("utf-8", errors="replace")


def _attachment_image(attachment: object) -> "Optional[tuple[str, bytes]]":
    """(media type, bytes) of an image attachment; None for anything else, for data that is not valid base64, and for
    an IDENTITY encoding (binary cannot travel as raw text)."""
    fields = _attachment_fields(attachment)
    if fields is None or fields[0] not in IMAGE_MEDIA_TYPES or fields[2]:
        return None
    try:
        return fields[0], base64.b64decode(fields[1], validate=True)
    except (binascii.Error, ValueError):
        return None


def _step_texts(step: object) -> list:
    if not isinstance(step, dict):
        return []
    texts = []
    for key in ("embeddings", "attachments"):
        attachments = step.get(key)
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            text = _attachment_text(attachment)
            if text is not None:
                texts.append(text)
    return texts


def _step_entry(step: dict) -> Optional[dict]:
    """The step as the dashboard matches it: {text, line?}, keyword and name joined and cut, with the line when it is
    a plausible one. Shared by failed_step and the screenshots. None for a step without text."""
    step_name = f"{step.get('keyword', '')}{step.get('name', '')}".strip()
    if not step_name:
        return None
    entry = {"text": step_name[:STEP_TEXT_LENGTH]}
    line = step.get("line")
    if isinstance(line, int) and not isinstance(line, bool) and 1 <= line <= 1_000_000:
        entry["line"] = line
    return entry


def _hook_kind(step: dict, real_seen: bool) -> Optional[str]:
    """"before" or "after" for a cucumber-js hook entry in the steps list, None for a real step. The keyword names it;
    a hidden entry without one is a before hook until the first real step has been seen."""
    keyword = str(step.get("keyword") or "").strip().lower()
    if keyword in ("before", "after"):
        return keyword
    if step.get("hidden") is True:
        return "after" if real_seen else "before"
    return None


def _scenario_screenshots(element: dict, steps: list, skips: dict) -> "tuple[list, dict]":
    """The scenario's image attachments as [{sha256, media_type, step_text, step_line, hook?}] in step order, plus
    {sha256: (media_type, bytes)}. An image on a real step goes to that step; one on a Before hook to the first real
    step, one on an After hook to the last real step that was not skipped (the last one when all were), each with
    `hook`. cucumber-jvm's element-level before/after follow the same rules. Skipped images are counted into `skips`."""
    before = element.get("before") if isinstance(element.get("before"), list) else []
    after = element.get("after") if isinstance(element.get("after"), list) else []
    entries = [(step, "before") for step in before if isinstance(step, dict)]
    real: list = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        kind = _hook_kind(step, bool(real))
        if kind is None:
            real.append(step)
        entries.append((step, kind))
    entries += [(step, "after") for step in after if isinstance(step, dict)]
    if not real:
        return [], {}

    ran = [step for step in real if str((step.get("result") or {}).get("status") or "") != "skipped"]
    targets = {"before": real[0], "after": (ran or real)[-1]}
    screenshots: list = []
    images: dict = {}
    for step, kind in entries:
        for key in ("embeddings", "attachments"):
            attachments = step.get(key)
            for attachment in attachments if isinstance(attachments, list) else []:
                image = _attachment_image(attachment)
                target = _step_entry(targets[kind] if kind else step) if image is not None else None
                if target is None:
                    continue
                media_type, data = image
                if len(data) > MAX_IMAGE_BYTES:
                    skips["large"] = skips.get("large", 0) + 1
                    continue
                digest = hashlib.sha256(data).hexdigest()
                reference = {"sha256": digest, "media_type": media_type, "step_text": target["text"],
                             "step_line": target.get("line")}
                if kind:
                    reference["hook"] = kind
                if reference in screenshots:  # the same image again on the same step: once, and counted once
                    continue
                if len(screenshots) >= MAX_SCREENSHOTS_PER_RESULT:
                    skips["over"] = skips.get("over", 0) + 1
                    continue
                images[digest] = (media_type, data)
                screenshots.append(reference)
    return screenshots, images


def _scenario_log(element: dict, steps: list) -> Optional[str]:
    """The scenario's text attachments in order: cucumber-jvm's scenario hooks (`before`), then its steps (cucumber-js
    hook steps and Background steps included), then `after`; joined by newlines and cut to 64 KB. None without text."""
    before = element.get("before") if isinstance(element.get("before"), list) else []
    after = element.get("after") if isinstance(element.get("after"), list) else []
    log = "\n".join(text.rstrip("\r\n") for step in [*before, *steps, *after] for text in _step_texts(step))
    return _cut(log) if log.strip() else None


def _cucumber_feature(feature: dict, parsed: ParsedFile, lines: Optional[list] = None,
                      skips: Optional[dict] = None) -> None:
    """The feature's scenarios (and outline rows) as results. With `lines`, each result's scenario line too (an int,
    or None), in step with parsed.results: run-impact's discovery reads a dry run through this parser, and then a
    scenario without a name is kept too (an empty name), so that it still runs in a stage."""
    suite = str(feature.get("name") or "")
    # Windows runners report "tests\features\a.feature"; the key must not depend on the OS (ADR-023)
    uri = str(feature.get("uri") or "").replace("\\", "/")
    skips = skips if skips is not None else {}
    background: list = []
    for element in feature.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if element.get("type") == "background":
            # The classic formatter emits the background once, before each
            # scenario it belongs to; its steps count into that scenario
            background = list(element.get("steps") or [])
            continue
        name = str(element.get("name") or "").strip()
        if not name:
            parsed.unnamed += 1
            if lines is None:
                continue
        steps = background + list(element.get("steps") or [])
        background = []
        stamp = _timestamp(element.get("start_timestamp"))
        if stamp is not None:
            parsed.suite_timestamps.append(stamp)

        statuses = [str((s.get("result") or {}).get("status") or "") for s in steps if isinstance(s, dict)]
        if any(s in _CUCUMBER_FAILED for s in statuses):
            status = "failed"
        elif all(s == "passed" for s in statuses) and statuses:
            status = "passed"
        else:  # skipped, undefined, pending, ambiguous, or no steps at all
            status = "skipped"

        nanoseconds = sum(
            result.get("duration") or 0
            for step in steps if isinstance(step, dict)
            for result in [step.get("result") or {}]
            if isinstance(result.get("duration"), (int, float)) and result.get("duration") > 0
        )
        row = _row(suite, uri, name, status, nanoseconds / 1e9)
        # The step the scenario stopped at: the failed one, or for a skipped scenario the first that did not pass
        # (undefined, pending, ambiguous, or skipped by a hook before any step ran). Sent as failed_step either way.
        if status == "failed":
            stopped_at = next(
                (s for s in steps if isinstance(s, dict)
                 and str((s.get("result") or {}).get("status") or "") in _CUCUMBER_FAILED),
                None,
            )
        elif status == "skipped":
            stopped_at = next(
                (s for s in steps if isinstance(s, dict) and str((s.get("result") or {}).get("status") or "") != "passed"),
                None,
            )
        else:
            stopped_at = None
        if stopped_at is not None:
            result = stopped_at.get("result") or {}
            message = str(result.get("error_message") or "")
            keyword, step_text = f"{stopped_at.get('keyword', '')}", f"{stopped_at.get('name', '')}"
            step_name = f"{keyword}{step_text}".strip()
            if status == "failed":
                # A failed step's message is its error's first line; details hold the step and the whole error
                _attach(row, _first_line(message), "\n".join(part for part in (step_name, message.strip()) if part))
            else:
                # A skipped scenario's message says why it stopped: what the test attached to that step as text (a
                # known-error note, whole, every line), else the step's status; details add Cucumber's own text
                reason = _SKIP_REASONS.get(str(result.get("status") or ""), "Skipped")
                note = "\n".join(text.strip() for text in _step_texts(stopped_at) if text.strip())
                _attach(row, note or reason,
                        "\n".join(part for part in (step_name, reason, note, message.strip()) if part))
            entry = _step_entry(stopped_at)
            if entry is not None:
                definition = _step_definition(stopped_at)
                if definition is not None:
                    entry["definition"] = definition
                entry["pattern"] = _step_pattern(stopped_at, keyword, step_text)
                row["failed_step"] = entry
        log = _scenario_log(element, steps)
        if log is not None:
            row["log"] = log
        screenshots, images = _scenario_screenshots(element, steps, skips)
        if screenshots:
            row["screenshots"] = screenshots
            row["_images"] = images  # private: uploaded apart, kept out of the body by payload.py
        parsed.results.append(row)
        if lines is not None:
            line = element.get("line")
            lines.append(line if isinstance(line, int) and not isinstance(line, bool) and line > 0 else None)


# --- Playwright JSON reporter --------------------------------------------------

# Playwright's own statuses; everything unexpected maps to failed, and every
# retry attempt is its own result — a flaky spec shows up as fail+pass in one
# run, exactly like Surefire reruns
_PLAYWRIGHT_STATUS = {"passed": "passed", "failed": "failed", "timedOut": "failed",
                      "interrupted": "errored", "skipped": "skipped"}


def _playwright_suite(suite: dict, parsed: ParsedFile) -> None:
    if not isinstance(suite, dict):
        return
    for child in suite.get("suites") or []:
        _playwright_suite(child, parsed)
    for spec in suite.get("specs") or []:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("title") or "").strip()
        if not name:
            parsed.unnamed += 1
            continue
        for test in spec.get("tests") or []:
            if not isinstance(test, dict):
                continue
            project = str(test.get("projectName") or "")
            for attempt in test.get("results") or []:
                if not isinstance(attempt, dict):
                    continue
                stamp = _timestamp(attempt.get("startTime"))
                if stamp is not None:
                    parsed.suite_timestamps.append(stamp)
                status = _PLAYWRIGHT_STATUS.get(str(attempt.get("status") or ""), "skipped")
                duration = attempt.get("duration")
                seconds = duration / 1000 if isinstance(duration, (int, float)) and duration > 0 else 0.0
                row = _row(project, str(spec.get("file") or ""), name, status, seconds)
                errors = attempt.get("errors") or ([attempt["error"]] if isinstance(attempt.get("error"), dict) else [])
                messages = [str(e.get("message") or "") for e in errors if isinstance(e, dict)]
                if any(m.strip() for m in messages):
                    joined = "\n\n".join(m for m in messages if m.strip())
                    _attach(row, _first_line(joined), joined)
                parsed.results.append(row)


# --- TRX (Visual Studio / vstest) -------------------------------------------

_TRX_OUTCOMES = {
    "Passed": "passed", "Warning": "passed",
    "Failed": "failed", "Timeout": "failed",
    "Error": "errored", "Aborted": "errored",
}


def _trx(root: ET.Element, parsed: ParsedFile) -> None:
    classes = {}
    for definition in _find_all(root, "UnitTest"):
        method = next(_find_all(definition, "TestMethod"), None)
        if method is not None:
            classes[definition.get("id", "")] = method.get("className", "")

    for times in _find_all(root, "Times"):
        start, finish = _timestamp(times.get("start")), _timestamp(times.get("finish"))
        if start is not None:
            parsed.suite_timestamps.append(start)
            if finish is not None and finish >= start:
                parsed.suite_seconds += (finish - start).total_seconds()

    for result in _find_all(root, "UnitTestResult"):
        name = (result.get("testName") or "").strip()
        if not name:
            parsed.unnamed += 1
            continue
        row = _row(
            "", classes.get(result.get("testId", ""), ""), name,
            _TRX_OUTCOMES.get(result.get("outcome", ""), "skipped"),
            _trx_seconds(result.get("duration")),
        )
        error = next(_find_all(result, "ErrorInfo"), None)
        if error is not None:
            message = _text_of(next(_find_all(error, "Message"), None))
            stack = _text_of(next(_find_all(error, "StackTrace"), None))
            _attach(row, message, "\n".join(part for part in (message, stack) if part.strip()))
        parsed.results.append(row)


def _trx_seconds(value: Optional[str]) -> float:
    match = _TRX_DURATION.match((value or "").strip())
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


# --- NUnit 3 -----------------------------------------------------------------


def _nunit(root: ET.Element, parsed: ParsedFile) -> None:
    stamp = _timestamp(root.get("start-time"))
    if stamp is not None:
        parsed.suite_timestamps.append(stamp)
    parsed.suite_seconds += _seconds(root.get("duration"))

    assemblies = {
        suite: suite.get("name", "")
        for suite in _find_all(root, "test-suite") if suite.get("type") == "Assembly"
    }

    def assembly_of(case: ET.Element, element: ET.Element, inherited: str) -> str:
        if element in assemblies:
            inherited = assemblies[element]
        for child in element:
            if child is case:
                return inherited
            found = assembly_of(case, child, inherited)
            if found is not None:
                return found
        return None  # type: ignore[return-value]  # case not under this element

    for case in _find_all(root, "test-case"):
        name = (case.get("name") or "").strip()
        if not name:
            parsed.unnamed += 1
            continue
        result = case.get("result", "")
        if result == "Passed" or result == "Warning":
            status = "passed"
        elif result == "Failed":
            status = "errored" if case.get("label") == "Error" else "failed"
        else:  # Skipped, Inconclusive, anything new
            status = "skipped"
        row = _row(
            assembly_of(case, root, "") or "", case.get("classname", ""), name,
            status, _seconds(case.get("duration")),
        )
        failure = next(_find_all(case, "failure"), None)
        if failure is not None:
            message = _text_of(next(_find_all(failure, "message"), None))
            stack = _text_of(next(_find_all(failure, "stack-trace"), None))
            _attach(row, message, "\n".join(part for part in (message, stack) if part.strip()))
        parsed.results.append(row)


# --- xUnit.net v2 -------------------------------------------------------------


def _xunit(root: ET.Element, parsed: ParsedFile) -> None:
    for assembly in _find_all(root, "assembly"):
        suite = os.path.basename((assembly.get("name") or "").replace("\\", "/"))
        parsed.suite_seconds += _seconds(assembly.get("time"))
        stamp = _timestamp(f"{assembly.get('run-date', '')}T{assembly.get('run-time', '')}")
        if stamp is not None:
            parsed.suite_timestamps.append(stamp)
        for test in _find_all(assembly, "test"):
            method = (test.get("method") or test.get("name") or "").strip()
            if not method:
                parsed.unnamed += 1
                continue
            status = {"Pass": "passed", "Fail": "failed"}.get(test.get("result", ""), "skipped")
            row = _row(suite, test.get("type", ""), method, status, _seconds(test.get("time")))
            failure = next(_find_all(test, "failure"), None)
            if failure is not None:
                message = _text_of(next(_find_all(failure, "message"), None))
                stack = _text_of(next(_find_all(failure, "stack-trace"), None))
                _attach(row, message, "\n".join(part for part in (message, stack) if part.strip()))
            elif status == "skipped":
                reason = _text_of(next(_find_all(test, "reason"), None))
                _attach(row, reason, "")
            parsed.results.append(row)


# --- TestNG -------------------------------------------------------------------


def _testng(root: ET.Element, parsed: ParsedFile) -> None:
    for suite in _find_all(root, "suite"):
        suite_name = suite.get("name", "")
        stamp = _timestamp(suite.get("started-at"))
        if stamp is not None:
            parsed.suite_timestamps.append(stamp)
        parsed.suite_seconds += _testng_ms(suite.get("duration-ms")) / 1000
        for klass in _find_all(suite, "class"):
            class_name = klass.get("name", "")
            for method in _find_all(klass, "test-method"):
                if (method.get("is-config") or "").lower() == "true":
                    continue  # setUp/tearDown are not tests
                name = (method.get("name") or "").strip()
                if not name:
                    parsed.unnamed += 1
                    continue
                status = {"PASS": "passed", "FAIL": "failed"}.get(method.get("status", ""), "skipped")
                row = _row(suite_name, class_name, name, status, _testng_ms(method.get("duration-ms")) / 1000)
                exception = next(_find_all(method, "exception"), None)
                if exception is not None:
                    message = _text_of(next(_find_all(exception, "message"), None))
                    stack = _text_of(next(_find_all(exception, "full-stacktrace"), None))
                    _attach(row, message, "\n".join(part for part in (message.strip(), stack.strip()) if part))
                parsed.results.append(row)


def _testng_ms(value: Optional[str]) -> float:
    try:
        ms = float(value or "")
    except ValueError:
        return 0.0
    return ms if math.isfinite(ms) and ms >= 0 else 0.0
