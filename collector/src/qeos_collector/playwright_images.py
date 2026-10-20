"""Playwright screenshots (spec 2026-10-20-playwright-screenshots-design.md): the image attachments of one attempt.

Playwright's JSON reporter lists `attachments: [{name, contentType, path?, body?}]` per attempt, not per step. An image
comes either inline (`body`, base64) or as a file on the CI disk (`path`). A report is only JSON, so a `path` is read
only when it resolves (symlinks followed) inside the working directory, is a regular file of at most 5 MB, and starts
with the magic bytes of its declared type: a careless or tampered report can never make the collector upload another
file of the CI machine. Videos and traces are not sent yet.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import Optional

IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_SCREENSHOTS_PER_RESULT = 50
STEP_TEXT_LENGTH = 1000  # the server's step_text limit
END_OF_TEST = "End of test"

# toHaveScreenshot() attaches <name>-expected, -actual and -diff: shown first, in this order, with plain labels
_COMPARISON = (("-expected", "Expected"), ("-actual", "Actual"), ("-diff", "Difference"))

# Skip reasons, in the order the warning lists them
REASONS = {
    "outside": "outside the working directory",
    "missing": "missing",
    "large": "over 5 MB",
    "not_image": "not an image of its declared type",
    "bad_body": "not valid base64",
    "media": "video or trace (not sent yet)",
    "over": f"beyond {MAX_SCREENSHOTS_PER_RESULT} per result",
}


def magic_matches(media_type: str, data: bytes) -> bool:
    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # another drive on Windows
        return False


def _read(raw_path: str, report_dir: str, root: str, skips: dict) -> Optional[bytes]:
    path = raw_path if os.path.isabs(raw_path) else os.path.join(report_dir, raw_path)
    real = os.path.realpath(path)
    if not _inside(real, root):
        skips["outside"] = skips.get("outside", 0) + 1
        return None
    try:
        info = os.stat(real)
    except OSError:
        skips["missing"] = skips.get("missing", 0) + 1
        return None
    if not os.path.isfile(real):
        skips["missing"] = skips.get("missing", 0) + 1
        return None
    if info.st_size > MAX_IMAGE_BYTES:
        skips["large"] = skips.get("large", 0) + 1
        return None
    try:
        with open(real, "rb") as fh:
            return fh.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        skips["missing"] = skips.get("missing", 0) + 1
        return None


def _failing_step(steps: object) -> Optional[dict]:
    """The deepest step with an error, depth first; None when no step failed."""
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        deeper = _failing_step(step.get("steps"))
        if deeper is not None:
            return deeper
        if step.get("error") and str(step.get("title") or "").strip():
            return step
    return None


def _label(name: str) -> "tuple[int, str]":
    """(sort rank, suffix shown after the step text) for an attachment name."""
    stem = os.path.splitext(name)[0]
    for rank, (ending, label) in enumerate(_COMPARISON):
        if stem.endswith(ending):
            return rank, label
    return len(_COMPARISON), "" if name in ("", "screenshot") else name


def attempt_screenshots(attempt: dict, report_dir: str, root: str, skips: dict) -> "tuple[list, dict]":
    """[{sha256, media_type, step_text, step_line, hook: "after"}] and {sha256: (media_type, bytes)} for an attempt.
    `root` is the resolved working directory; skips are counted into `skips` by reason (REASONS)."""
    attachments = attempt.get("attachments")
    if not isinstance(attachments, list):
        return [], {}
    failing = _failing_step(attempt.get("steps"))
    base = str(failing.get("title")).strip() if failing else END_OF_TEST
    line = None
    if failing and isinstance(failing.get("location"), dict):
        value = failing["location"].get("line")
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1_000_000:
            line = value

    found = []
    for position, attachment in enumerate(attachments):
        if not isinstance(attachment, dict):
            continue
        media = str(attachment.get("contentType") or "").split(";", 1)[0].strip().lower()
        if media.startswith("video/") or media == "application/zip":
            skips["media"] = skips.get("media", 0) + 1
            continue
        if media not in IMAGE_MEDIA_TYPES:
            continue
        data: Optional[bytes]
        if isinstance(attachment.get("body"), str):
            try:
                data = base64.b64decode(attachment["body"], validate=True)
            except (binascii.Error, ValueError):
                skips["bad_body"] = skips.get("bad_body", 0) + 1
                continue
            if len(data) > MAX_IMAGE_BYTES:
                skips["large"] = skips.get("large", 0) + 1
                continue
        elif isinstance(attachment.get("path"), str) and attachment["path"]:
            data = _read(attachment["path"], report_dir, root, skips)
            if data is None:
                continue
        else:
            continue
        if not magic_matches(media, data):
            skips["not_image"] = skips.get("not_image", 0) + 1
            continue
        rank, suffix = _label(str(attachment.get("name") or ""))
        text = f"{base} ({suffix})" if suffix else base
        found.append((rank, position, media, data, text[:STEP_TEXT_LENGTH]))

    screenshots: list = []
    images: dict = {}
    for _, _, media, data, text in sorted(found, key=lambda item: (item[0], item[1])):
        digest = hashlib.sha256(data).hexdigest()
        reference = {"sha256": digest, "media_type": media, "step_text": text, "step_line": line, "hook": "after"}
        if reference in screenshots:
            continue
        if len(screenshots) >= MAX_SCREENSHOTS_PER_RESULT:
            skips["over"] = skips.get("over", 0) + 1
            continue
        images[digest] = (media, data)
        screenshots.append(reference)
    return screenshots, images


def skip_warning(path: str, skips: dict, any_read: bool) -> "list[str]":
    """The warnings for one report: one line with the counts by reason, plus the outputDir hint when every file
    attachment was outside the working directory and none could be read."""
    parts = [f"{skips[key]} {label}" for key, label in REASONS.items() if skips.get(key)]
    if not parts:
        return []
    warnings = [f"skipped Playwright screenshot(s) in {path}: " + ", ".join(parts)]
    if skips.get("outside") and not any_read:
        warnings.append("Playwright images are outside the working directory; set outputDir inside the checkout")
    return warnings
