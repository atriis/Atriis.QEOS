"""Playwright screenshots (spec 2026-10-20): image attachments of each attempt, read from the report (`body`) or from
disk (`path`, only inside the working directory, real images, at most 5 MB). Videos and traces are not sent yet."""
import base64
import hashlib
import json
import os

import pytest

from qeos_collector.formats import parse_file

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 32
DIFF = b"\x89PNG\r\n\x1a\n" + b"\x02" * 32


def sha(data):
    return hashlib.sha256(data).hexdigest()


def report(tmp_path, attempts):
    data = {"config": {"version": "1.47.0"}, "suites": [{
        "title": "checkout.spec.ts", "file": "checkout.spec.ts", "suites": [],
        "specs": [{"title": "pays", "file": "checkout.spec.ts",
                   "tests": [{"projectName": "chromium", "results": attempts}]}]}]}
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def attachment(name, content_type, path=None, body=None):
    entry = {"name": name, "contentType": content_type}
    if path is not None:
        entry["path"] = str(path)
    if body is not None:
        entry["body"] = base64.b64encode(body).decode()
    return entry


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test-results").mkdir()
    return tmp_path


FAILING_STEPS = [
    {"title": "Before Hooks", "steps": []},
    {"title": "open the cart", "steps": [
        {"title": "expect(locator).toBeVisible()", "error": {"message": "timeout"},
         "location": {"file": "checkout.spec.ts", "line": 42}}],
     "error": {"message": "timeout"}},
]


def test_failure_screenshot_from_disk_and_body_on_the_failing_step(workdir):
    shot = workdir / "test-results" / "test-failed-1.png"
    shot.write_bytes(PNG)
    path = report(workdir, [{"status": "failed", "duration": 10, "retry": 0, "steps": FAILING_STEPS,
                             "attachments": [attachment("screenshot", "image/png", path=shot),
                                             attachment("checkout page", "image/jpeg", body=JPEG)]},
                            {"status": "passed", "duration": 10, "retry": 1, "steps": [],
                             "attachments": [attachment("screenshot", "image/png", path=shot)]}])
    parsed = parse_file(path)
    failed, passed = parsed.results
    assert failed["screenshots"] == [
        {"sha256": sha(PNG), "media_type": "image/png", "step_text": "expect(locator).toBeVisible()",
         "step_line": 42, "hook": "after"},
        {"sha256": sha(JPEG), "media_type": "image/jpeg", "step_text": "expect(locator).toBeVisible() (checkout page)",
         "step_line": 42, "hook": "after"},
    ]
    assert failed["_images"] == {sha(PNG): ("image/png", PNG), sha(JPEG): ("image/jpeg", JPEG)}
    assert passed["screenshots"] == [{"sha256": sha(PNG), "media_type": "image/png", "step_text": "End of test",
                                      "step_line": None, "hook": "after"}]


def test_visual_comparison_images_come_first_with_plain_labels(workdir):
    files = {}
    for kind, data in (("actual", PNG), ("expected", JPEG), ("diff", DIFF)):
        files[kind] = workdir / "test-results" / f"cart-{kind}.png"
        files[kind].write_bytes(data)
    path = report(workdir, [{"status": "failed", "duration": 10, "retry": 0, "steps": [], "attachments": [
        attachment("trace", "application/zip", path=workdir / "test-results" / "trace.zip"),
        attachment("cart-actual.png", "image/png", path=files["actual"]),
        attachment("cart-expected.png", "image/jpeg", path=files["expected"]),
        attachment("cart-diff.png", "image/png", path=files["diff"]),
    ]}])
    texts = [s["step_text"] for s in parse_file(path).results[0]["screenshots"]]
    assert texts == ["End of test (Expected)", "End of test (Actual)", "End of test (Difference)"]


def test_unsafe_or_unusable_attachments_are_skipped_and_counted(workdir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "secret.png"
    outside.write_bytes(PNG)
    link = workdir / "test-results" / "link.png"
    try:
        os.symlink(outside, link)
        has_link = True
    except (OSError, NotImplementedError):  # Windows without symlink rights
        has_link = False
    big = workdir / "test-results" / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (6 * 1024 * 1024))
    fake = workdir / "test-results" / "fake.png"
    fake.write_bytes(b"not an image")
    good = workdir / "test-results" / "good.png"
    good.write_bytes(PNG)
    attachments = [
        attachment("screenshot", "image/png", path=outside),
        attachment("screenshot", "image/png", path=workdir / "test-results" / "gone.png"),
        attachment("screenshot", "image/png", path=big),
        attachment("screenshot", "image/png", path=fake),
        attachment("video", "video/webm", path=workdir / "test-results" / "video.webm"),
        attachment("notes", "text/plain", body=b"hello"),
        attachment("screenshot", "image/png", path=good),
    ]
    if has_link:
        attachments.append(attachment("screenshot", "image/png", path=link))
    path = report(workdir, [{"status": "failed", "duration": 10, "retry": 0, "attachments": attachments}])
    parsed = parse_file(path)
    assert [s["sha256"] for s in parsed.results[0]["screenshots"]] == [sha(PNG)]  # only good.png
    warning = next(w for w in parsed.warnings if "Playwright" in w)
    assert "outside the working directory" in warning and "missing" in warning and "over 5 MB" in warning
    assert "not an image" in warning and "video or trace" in warning


def test_relative_path_is_resolved_from_the_report_folder(workdir):
    (workdir / "out").mkdir()
    (workdir / "out" / "shot.png").write_bytes(PNG)
    reports = workdir / "reports"
    reports.mkdir()
    path = report(reports, [{"status": "failed", "duration": 10, "retry": 0,
                             "attachments": [attachment("screenshot", "image/png", path="../out/shot.png")]}])
    assert parse_file(path).results[0]["screenshots"][0]["sha256"] == sha(PNG)


def test_all_images_outside_the_working_directory_gives_the_outputdir_hint(workdir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("tmp-results") / "shot.png"
    outside.write_bytes(PNG)
    path = report(workdir, [{"status": "failed", "duration": 10, "retry": 0,
                             "attachments": [attachment("screenshot", "image/png", path=outside)]}])
    parsed = parse_file(path)
    assert "screenshots" not in parsed.results[0]
    assert any("set outputDir inside the checkout" in w for w in parsed.warnings)


def test_invalid_base64_body_is_skipped(workdir):
    path = report(workdir, [{"status": "failed", "duration": 10, "retry": 0,
                             "attachments": [{"name": "screenshot", "contentType": "image/png", "body": "!!not base64"}]}])
    parsed = parse_file(path)
    assert "screenshots" not in parsed.results[0]


def test_a_report_without_attachments_is_unchanged(workdir):
    path = report(workdir, [{"status": "passed", "duration": 10, "retry": 0}])
    row = parse_file(path).results[0]
    assert "screenshots" not in row and "_images" not in row
