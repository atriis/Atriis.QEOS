"""Traces (spec 2026-10-21-traces-and-videos-design.md §4.2): the Playwright trace zips a report names.

Playwright's JSON reporter lists a trace as an attachment `{name: "trace", contentType: "application/zip", path}`;
a Cucumber scenario names one with a reference attachment, media type `application/vnd.qeos.artifact+json` and
content `{"kind": "trace", "path": "test-results/traces/x.zip"}`. A trace is read under the 0.13.0 screenshot file
rules: it must resolve (symlinks followed) inside the working directory, be a regular file of at most 100 MB and
start with `PK\\x03\\x04`, so a careless or tampered report can never make the collector upload another file of the CI
machine. It is hashed by streaming here and read again only when it is uploaded, in 1 MB chunks, checked against
that hash as it goes. Videos are not sent yet.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from typing import Iterator, List, Optional

from qeos_collector.playwright_images import _inside

TRACE_MEDIA_TYPE = "application/zip"
REFERENCE_MEDIA_TYPE = "application/vnd.qeos.artifact+json"
ZIP_MAGIC = b"PK\x03\x04"
MAX_TRACE_BYTES = 100 * 1024 * 1024
MAX_TRACES_PER_RESULT = 5
NAME_LENGTH = 200  # the server's limit
CHUNK_BYTES = 1024 * 1024

# Skip reasons, in the order the trace line lists them
REASONS = {
    "outside": "outside the working directory",
    "missing": "missing",
    "large": "over 100 MB",
    "not_zip": "not a ZIP file",
    "inline": "inline in the report (only files are sent)",
    "bad_reference": "not a valid reference",
    "video": "video (not sent yet)",
    "over": f"beyond {MAX_TRACES_PER_RESULT} per result",
}


class TraceChanged(Exception):
    """The file is not the one the report pointed at any more (changed, grew, shrank or went away)."""


class TraceFile:
    """A trace file named by the report: its resolved path, size, SHA-256 (computed by streaming) and the name shown
    for it. Its bytes are never held in memory: `chunks` reads them again for the upload."""

    __slots__ = ("path", "size", "sha256", "name")

    def __init__(self, path: str, size: int, sha256: str, name: str):
        self.path, self.size, self.sha256, self.name = path, size, sha256, name

    def chunks(self) -> Iterator[bytes]:
        """The file in CHUNK_BYTES pieces. The size and hash are checked as it goes, and the last piece is yielded only
        once they match: a file that changed raises TraceChanged before the upload is complete, so QEOS never stores
        other bytes under this hash."""
        try:
            with open(self.path, "rb") as fh:
                digest = hashlib.sha256()
                read = 0
                chunk = fh.read(CHUNK_BYTES)
                while True:
                    following = fh.read(CHUNK_BYTES) if chunk else b""
                    digest.update(chunk)
                    read += len(chunk)
                    if read > self.size:
                        raise TraceChanged()
                    if not following:
                        if read != self.size or digest.hexdigest() != self.sha256:
                            raise TraceChanged()
                        if chunk:
                            yield chunk
                        return
                    yield chunk
                    chunk = following
        except OSError:
            raise TraceChanged() from None


def count(skips: dict, reason: str) -> None:
    skips[reason] = skips.get(reason, 0) + 1


def read_trace(raw_path: str, folders: List[str], root: str, name: str, skips: dict) -> Optional[TraceFile]:
    """The TraceFile for a path the report names, or None (counted into `skips`). A relative path is tried in each of
    `folders` in turn, the first that exists wins; every candidate must resolve inside `root`."""
    if os.path.isabs(raw_path):
        candidates = [raw_path]
    else:
        candidates = [os.path.join(folder, raw_path) for folder in folders]
    real = os.path.realpath(candidates[0])
    for candidate in candidates:
        if os.path.lexists(candidate):
            real = os.path.realpath(candidate)
            break
    if not _inside(real, root):
        count(skips, "outside")
        return None
    try:
        info = os.stat(real)
    except OSError:
        count(skips, "missing")
        return None
    if not os.path.isfile(real):
        count(skips, "missing")
        return None
    if info.st_size > MAX_TRACE_BYTES:
        count(skips, "large")
        return None
    digest = hashlib.sha256()
    head = b""
    size = 0
    try:
        with open(real, "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK_BYTES), b""):
                if not head:
                    head = chunk[:len(ZIP_MAGIC)]
                    if head != ZIP_MAGIC:
                        count(skips, "not_zip")
                        return None
                digest.update(chunk)
                size += len(chunk)
                if size > MAX_TRACE_BYTES:  # grew since the stat
                    count(skips, "large")
                    return None
    except OSError:
        count(skips, "missing")
        return None
    if head != ZIP_MAGIC:  # empty
        count(skips, "not_zip")
        return None
    return TraceFile(real, size, digest.hexdigest(), name[:NAME_LENGTH])


def references(found: List[TraceFile], skips: dict) -> "tuple[list, dict]":
    """[{sha256, kind: "trace", name}] and {sha256: TraceFile} for one result: each trace once, at most
    MAX_TRACES_PER_RESULT (the rest counted)."""
    artifacts: list = []
    files: dict = {}
    for trace in found:
        if trace.sha256 in files:
            continue
        if len(artifacts) >= MAX_TRACES_PER_RESULT:
            count(skips, "over")
            continue
        files[trace.sha256] = trace
        artifacts.append({"sha256": trace.sha256, "kind": "trace", "name": trace.name})
    return artifacts, files


def attempt_traces(attempt: dict, report_dir: str, root: str, skips: dict) -> "tuple[list, dict]":
    """The trace attachments of one Playwright attempt (contentType application/zip, any name); see `references`."""
    attachments = attempt.get("attachments")
    if not isinstance(attachments, list):
        return [], {}
    found = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        media = str(attachment.get("contentType") or "").split(";", 1)[0].strip().lower()
        if media != TRACE_MEDIA_TYPE:
            continue
        path = attachment.get("path")
        if not isinstance(path, str) or not path:
            if attachment.get("body") is not None:
                count(skips, "inline")
            continue
        name = str(attachment.get("name") or "").strip() or os.path.basename(path)
        trace = read_trace(path, [report_dir], root, name, skips)
        if trace is not None:
            found.append(trace)
    return references(found, skips)


def reference_trace(data: str, identity: bool, report_dir: str, root: str, skips: dict) -> Optional[TraceFile]:
    """The trace a Cucumber reference attachment names, or None (counted). The classic JSON formatter base64-encodes
    the content; cucumber's message formats carry it as text (IDENTITY), and a formatter that wrote the text itself is
    read as text too. A relative path is looked up from the report's folder, then from the working directory (where
    the test run wrote it)."""
    text = data
    if not identity:
        try:
            text = base64.b64decode(data, validate=True).decode("utf-8")
        except (binascii.Error, ValueError):
            text = data
    try:
        value = json.loads(text)
    except ValueError:
        count(skips, "bad_reference")
        return None
    kind = value.get("kind") if isinstance(value, dict) else None
    if kind == "video":
        count(skips, "video")
        return None
    path = value.get("path") if isinstance(value, dict) else None
    if kind != "trace" or not isinstance(path, str) or not path.strip():
        count(skips, "bad_reference")
        return None
    path = path.strip()
    name = os.path.basename(path.replace("\\", "/")) or "trace"
    return read_trace(path, [report_dir, root], root, name, skips)


def reasons(skips: dict) -> str:
    """'1 missing, 2 over 100 MB': the counts by reason, in REASONS order."""
    return ", ".join(f"{skips[key]} {label}" for key, label in REASONS.items() if skips.get(key))
