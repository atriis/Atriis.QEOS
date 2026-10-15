"""Project-defined masking patterns, applied after the built-in rules in redaction.py.

The patterns come from users, so they run on RE2 (google-re2), not Python's backtracking `re`:
RE2 matches in time linear in the input, so no pattern can stall ingestion however it is
written ((a+)+$ included). The price is RE2's syntax: no backreferences or lookarounds.
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Set, Tuple

import re2

from src.ingestion.utils.redaction import MARKER_PREFIX, marker

MAX_PATTERN_LENGTH = 256
MAX_PATTERNS_PER_PROJECT = 20

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}\Z")  # \Z, not $: a trailing newline is not part of a name
# Text already masked; custom patterns only ever see what lies between these
_EXISTING_MARKER = re.compile(re.escape(MARKER_PREFIX) + r"[a-z0-9_]{1,64}\]")
# What the database cannot store (the set schemas/collect.py replaces in free text)
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


@dataclass(frozen=True)
class CustomPattern:
    name: str
    regex: "re2._Regexp"


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.match(name):
        raise ValueError(
            "The name must be 1-32 lowercase letters, digits or underscores, starting with a letter"
        )
    return name


@lru_cache(maxsize=1024)
def compile_pattern(pattern: str) -> "re2._Regexp":
    """Compile or raise ValueError with a reason a person can act on. Cached: ingest compiles
    the same few patterns for every upload."""
    if not pattern:
        raise ValueError("A pattern is required")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"A pattern is at most {MAX_PATTERN_LENGTH} characters")
    if _UNSTORABLE.search(pattern):
        # RE2 compiles these, but PostgreSQL cannot store them: a 422 here, not a 500 on the insert
        raise ValueError("A pattern must not contain NUL or unpaired surrogate characters")
    try:
        compiled = re2.compile(pattern)
    except re2.error as exc:
        detail = exc.args[0].decode() if exc.args and isinstance(exc.args[0], bytes) else str(exc)
        raise ValueError(
            f"This is not a valid pattern ({detail}). Patterns use RE2 syntax: "
            "no backreferences or lookarounds"
        ) from None
    if compiled.search("") is not None:
        # It would match between every pair of characters and bury the text in markers
        raise ValueError("This pattern matches empty text; it must match at least one character")
    return compiled


def apply(text: str, patterns: Iterable[CustomPattern]) -> Tuple[str, Set[str]]:
    found: Set[str] = set()
    patterns = list(patterns)
    if not text or not patterns:
        return text, found

    def mask_segment(segment: str) -> str:
        for pattern in patterns:
            def replace(_match, name=pattern.name):
                found.add(name)
                return marker(name)

            segment = pattern.regex.sub(replace, segment)
        return segment

    pieces, last = [], 0
    for existing in _EXISTING_MARKER.finditer(text):
        pieces.append(mask_segment(text[last:existing.start()]))
        pieces.append(existing.group(0))
        last = existing.end()
    pieces.append(mask_segment(text[last:]))
    return "".join(pieces), found
