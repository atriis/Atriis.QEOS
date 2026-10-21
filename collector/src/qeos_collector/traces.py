"""Traces (spec 2026-10-21-traces-and-videos-design.md §4.2): the Playwright trace zips a report names.

Playwright's JSON reporter lists a trace as an attachment `{name: "trace", contentType: "application/zip", path}`;
a Cucumber scenario names one with a reference attachment, media type `application/vnd.qeos.artifact+json` and
content `{"kind": "trace", "path": "test-results/traces/x.zip"}`. A trace is read under the 0.13.0 screenshot file
rules: it must resolve (symlinks followed) inside the working directory, be a regular file of at most 100 MB and
start with `PK\\x03\\x04`, so a careless or tampered report can never make the collector upload another file of the CI
machine. Reading the report only checks that (a stat and four bytes): a trace is hashed when it is about to be
uploaded, after the key check said the project keeps traces, and then streamed in 1 MB chunks, checked against that
hash as it goes. With traces turned off, the report's traces are only counted. Videos are not sent yet.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from typing import Callable, Iterator, List, Mapping, Optional

from qeos_collector.playwright_images import _inside

TRACE_MEDIA_TYPE = "application/zip"
REFERENCE_MEDIA_TYPE = "application/vnd.qeos.artifact+json"
ZIP_MAGIC = b"PK\x03\x04"
MAX_TRACE_BYTES = 100 * 1024 * 1024
MAX_TRACES_PER_RESULT = 5
NAME_LENGTH = 200  # the server's limit
CHUNK_BYTES = 1024 * 1024
OFF = "off"  # counted, never listed: the trace line says traces are off instead
_TRUE = ("1", "true", "yes")

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
    """The file is not the one the report pointed at any more (changed, grew, shrank, moved or went away)."""


class TraceTimeout(Exception):
    """The trace phase's deadline passed while a trace was read."""


def _never() -> float:
    return 0.0


class TraceFile:
    """A trace file named by the report: its resolved path, size, the name shown for it and the working directory it
    must stay in. `sha256` is None until `digest` computed it. The bytes are never held in memory."""

    __slots__ = ("path", "size", "sha256", "name", "root")

    def __init__(self, path: str, size: int, sha256: Optional[str], name: str, root: str):
        self.path, self.size, self.sha256, self.name, self.root = path, size, sha256, name, root

    def _open(self):
        """The file, only while its path still resolves to itself inside the working directory (a symlink put in its
        place since the report was read is not followed)."""
        if os.path.realpath(self.path) != self.path or not _inside(self.path, self.root):
            raise TraceChanged()
        return open(self.path, "rb")

    def digest(self, deadline: float = float("inf"), clock: Callable[[], float] = _never) -> str:
        """Hashes the file by streaming and records its size and SHA-256. Raises TraceChanged when it is no longer a
        trace QEOS takes (over 100 MB, not a ZIP, gone) and TraceTimeout when the deadline passes."""
        digest = hashlib.sha256()
        size = 0
        try:
            with self._open() as fh:
                for chunk in iter(lambda: fh.read(CHUNK_BYTES), b""):
                    if clock() >= deadline:
                        raise TraceTimeout()
                    if size == 0 and not chunk.startswith(ZIP_MAGIC):
                        raise TraceChanged()
                    digest.update(chunk)
                    size += len(chunk)
                    if size > MAX_TRACE_BYTES:
                        raise TraceChanged()
        except OSError:
            raise TraceChanged() from None
        if size == 0:
            raise TraceChanged()
        self.size, self.sha256 = size, digest.hexdigest()
        return self.sha256

    def chunks(self, deadline: float = float("inf"), clock: Callable[[], float] = _never) -> Iterator[bytes]:
        """The file in CHUNK_BYTES pieces for its upload. The size and hash are checked as it goes, and the last piece
        is yielded only once they match: a file that changed raises TraceChanged before the upload is complete, so
        QEOS never stores other bytes under this hash. The deadline is checked before each piece (TraceTimeout), so a
        slow upload cannot outlive the phase."""
        try:
            with self._open() as fh:
                digest = hashlib.sha256()
                read = 0
                chunk = fh.read(CHUNK_BYTES)
                while True:
                    if clock() >= deadline:
                        raise TraceTimeout()
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


def turned_off(flag: bool, env: Mapping[str, str], file_config: Mapping[str, object]) -> bool:
    """--no-artifacts, QEOS_NO_ARTIFACTS or `no-artifacts: true` in .qeos.yml."""
    return (bool(flag) or env.get("QEOS_NO_ARTIFACTS", "").strip().lower() in _TRUE
            or file_config.get("no-artifacts") is True)


def count(skips: dict, reason: str) -> None:
    skips[reason] = skips.get(reason, 0) + 1


def _resolve(raw_path: str, folders: List[str]) -> str:
    """The real path of what the report names. A relative path is tried in each of `folders` in turn, the first that
    exists wins (no file is opened)."""
    if os.path.isabs(raw_path):
        return os.path.realpath(raw_path)
    candidates = [os.path.join(folder, raw_path) for folder in folders]
    for candidate in candidates:
        if os.path.lexists(candidate):
            return os.path.realpath(candidate)
    return os.path.realpath(candidates[0])


def _check(real: str, root: str, name: str, skips: dict) -> Optional[TraceFile]:
    """A TraceFile (not hashed yet) for a resolved path, or None (counted into `skips`): inside `root`, a regular file
    of at most 100 MB that starts with PK\\x03\\x04. Only four bytes are read."""
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
    try:
        with open(real, "rb") as fh:
            head = fh.read(len(ZIP_MAGIC))
    except OSError:
        count(skips, "missing")
        return None
    if head != ZIP_MAGIC:
        count(skips, "not_zip")
        return None
    return TraceFile(real, info.st_size, None, name[:NAME_LENGTH], root)


def checked(candidates: List["tuple[str, List[str], str]"], root: str, skips: dict, read: bool) -> List[TraceFile]:
    """The traces of one result from its (raw path, folders, name) candidates: each resolved file once, at most
    MAX_TRACES_PER_RESULT, the cap applied before any file is read. With `read` False they are only counted (OFF)."""
    if not read:
        for _ in candidates:
            count(skips, OFF)
        return []
    unique: dict = {}
    for raw_path, folders, name in candidates:
        real = _resolve(raw_path, folders)
        if real in unique:
            continue
        if len(unique) >= MAX_TRACES_PER_RESULT:
            count(skips, "over")
            continue
        unique[real] = name
    found = []
    for real, name in unique.items():
        trace = _check(real, root, name, skips)
        if trace is not None:
            found.append(trace)
    return found


def attempt_traces(attempt: dict, report_dir: str, root: str, skips: dict, read: bool = True) -> List[TraceFile]:
    """The trace attachments of one Playwright attempt (contentType application/zip, any name, the name kept); see
    `checked`."""
    attachments = attempt.get("attachments")
    if not isinstance(attachments, list):
        return []
    candidates = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        media = str(attachment.get("contentType") or "").split(";", 1)[0].strip().lower()
        if media != TRACE_MEDIA_TYPE:
            continue
        path = attachment.get("path")
        if not isinstance(path, str) or not path:
            if attachment.get("body") is not None:
                count(skips, "inline" if read else OFF)
            continue
        name = str(attachment.get("name") or "").strip() or os.path.basename(path)
        candidates.append((path, [report_dir], name))
    return checked(candidates, root, skips, read)


def reference_path(data: str, identity: bool, skips: dict) -> "Optional[tuple[str, str]]":
    """(path, name) of the trace a Cucumber reference attachment names, or None (counted). The classic JSON formatter
    base64-encodes the content; cucumber's message formats carry it as text (IDENTITY), and a formatter that wrote the
    text itself is read as text too."""
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
    return path, os.path.basename(path.replace("\\", "/")) or "trace"


def reasons(skips: dict) -> str:
    """'1 missing, 2 over 100 MB': the counts by reason, in REASONS order."""
    return ", ".join(f"{skips[key]} {label}" for key, label in REASONS.items() if skips.get(key))
