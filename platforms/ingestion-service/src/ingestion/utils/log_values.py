"""Log values (ADR-032): a project's patterns applied to a result's masked log.

Patterns come from users, so they compile like masking patterns (custom_masking.compile_pattern: RE2, linear time, at
most 256 characters, never matching empty text). A pattern has at most one capture group: with one, the value is the
group's text; without, the whole match. Values come from the masked log, and a value that touches a masking marker is
never captured.
"""
import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from src.ingestion.utils import custom_masking
from src.ingestion.utils.redaction import MARKER_PREFIX

MAX_VALUE_LENGTH = 200
MAX_VALUES_PER_PATTERN = 20
MAX_LOG_PATTERNS_PER_PROJECT = 20
MAX_LINK_TEMPLATE_LENGTH = 500
# A 64 KB log can hold tens of thousands of matches of a loose pattern: each pattern stops reading a log after this
# many, so an upload stays fast whatever the project's patterns
MAX_MATCHES_READ = 1000
PLACEHOLDER = "{value}"

_MARKER = re.compile(re.escape(MARKER_PREFIX) + r"[a-z0-9_]{1,64}\]")
_LINK_RULE = ("The link must be an https:// address with a host and {value} once after the host, "
              "e.g. https://backoffice.example.com/trips/{value}")


class LogPatternError(ValueError):
    """A reason a person can act on, and the form field it belongs to: name, pattern, link_template or limit."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class CompiledLogPattern:
    id: Optional[int]  # None in a preview: nothing is stored
    name: str
    regex: "custom_masking.re2._Regexp"


def validate_name(name: str) -> str:
    try:
        return custom_masking.validate_name(name)
    except ValueError as exc:
        raise LogPatternError("name", str(exc)) from None


def compile_log_pattern(pattern: str):
    try:
        regex = custom_masking.compile_pattern(pattern)
    except ValueError as exc:
        raise LogPatternError("pattern", str(exc)) from None
    if regex.groups > 1:
        raise LogPatternError(
            "pattern",
            "A pattern has at most one capture group ( … ): the value is that group's text, or the whole match "
            "without one. Use (?: … ) for a group that is not the value",
        )
    return regex


def validate_link_template(template: Optional[str]) -> Optional[str]:
    """None for no link. Otherwise an https:// URL with a host, no credentials, and {value} exactly once after the
    host. The dashboard URL-encodes the value into it, so a value can never change the host or the path's structure."""
    if template is None or not template.strip():
        return None
    template = template.strip()
    if len(template) > MAX_LINK_TEMPLATE_LENGTH:
        raise LogPatternError("link_template", f"A link is at most {MAX_LINK_TEMPLATE_LENGTH} characters")
    if template.count(PLACEHOLDER) != 1 or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in template):
        raise LogPatternError("link_template", _LINK_RULE)
    try:
        parts = urlsplit(template)
        host = urlsplit(template.replace(PLACEHOLDER, "x")).hostname
    except ValueError:
        raise LogPatternError("link_template", _LINK_RULE) from None
    if parts.scheme.lower() != "https" or not host or "@" in parts.netloc or PLACEHOLDER in parts.netloc:
        raise LogPatternError("link_template", _LINK_RULE)
    return template


def extract(text: Optional[str], patterns: Iterable[CompiledLogPattern]) -> List[Tuple[Optional[int], int, str]]:
    """(pattern id, position, value) for each distinct value of each pattern, in order of first appearance: at most
    20 per pattern, each cut to 200 characters (distinct after the cut), blank ones skipped, and none that touches a
    masking marker. A pattern reads at most the first 1,000 matches."""
    if not text:
        return []
    # Markers come sorted and never overlap, so the only marker that can touch a span [start, end) is the last one
    # starting before end: one bisect per match, not a walk over every marker of a marker-dense log
    markers = [m.span() for m in _MARKER.finditer(text)]
    marker_starts = [marker_start for marker_start, _ in markers]
    found: List[Tuple[Optional[int], int, str]] = []
    for pattern in patterns:
        group = 1 if pattern.regex.groups == 1 else 0
        seen: List[str] = []
        for read, match in enumerate(pattern.regex.finditer(text)):
            if read >= MAX_MATCHES_READ or len(seen) >= MAX_VALUES_PER_PATTERN:
                break
            if match.group(group) is None:  # an optional group that took no part
                continue
            start, end = match.span(group)
            last = bisect_right(marker_starts, end - 1) - 1
            if last >= 0 and markers[last][1] > start:
                continue  # hidden by masking: never captured
            value = text[start:end].strip()[:MAX_VALUE_LENGTH]
            if value and value not in seen:
                seen.append(value)
        found.extend((pattern.id, position, value) for position, value in enumerate(seen))
    return found
