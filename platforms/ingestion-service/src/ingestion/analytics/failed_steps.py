"""Which failed steps are one step (spec 2026-10-14 §3.2).

A step is its step definition, the code that runs it, when the collector reported one (0.8.0 and later): `When I
search Lisbon` and `When I search Porto` are one step with other parameters. Without one, the step text is the
identity, compared without case and with runs of whitespace collapsed. The key is a short hash of either, safe in a
URL fragment (the run page's `#step-<key>`)."""
import hashlib
import re
from typing import Optional, Tuple

from src.ingestion.analytics.signature import _HEX, _HEX_PREFIXED, _NUMBER, _SPACE, _UUID, HEADLINE

KEY_LENGTH = 16


def step_text_identity(text: str) -> str:
    return " ".join(text.split()).lower()


def step_key(definition: Optional[str], text: str) -> Tuple[str, str]:
    """(key, by), `by` being "definition" or "text"."""
    by, identity = ("definition", definition) if definition else ("text", step_text_identity(text))
    return hashlib.sha256(f"{by}\0{identity}".encode("utf-8")).hexdigest()[:KEY_LENGTH], by


PLACEHOLDER = "…"
# A quoted value: the quote not inside a word (so "can't" is not a quote), up to the same quote on the same line
_QUOTED = re.compile(r"""(?<!\w)(['"`])(?:(?!\1)[^\n])*\1(?!\w)""")


# An HTTP status code (100-599) right after status/HTTP/code is part of the error, not a value. After got/returned/
# expected it is one only when the line also speaks of a status (`expected status 200 but got 500`, not
# `expected 3 items, got 250 rows`).
_STATUS_AFTER = re.compile(r"\b(?:status|http|code)\s*[:=]?\s*$", re.IGNORECASE)
_OUTCOME_AFTER = re.compile(r"\b(?:got|returned|expected)\s*[:=]?\s*$", re.IGNORECASE)
_STATUS_WORD = re.compile(r"\b(?:status|http|code|response)\b", re.IGNORECASE)
_STATUS_CODE = re.compile(r"[1-5]\d\d")
_MAX_LINE = 2000  # the line is capped before normalising, so a huge message costs no more than a long one


def _first_line(message: Optional[str]) -> str:
    for line in (message or "").splitlines():
        if line.strip():
            return line.strip()[:_MAX_LINE]
    return ""


def _number(line: str, match: "re.Match[str]", has_status_word: bool) -> str:
    if not _STATUS_CODE.fullmatch(match.group()):
        return PLACEHOLDER
    before = line[: match.start()]
    if _STATUS_AFTER.search(before) or (has_status_word and _OUTCOME_AFTER.search(before)):
        return match.group()
    return PLACEHOLDER


def error_shape(message: Optional[str]) -> str:
    """The first line of the error with quoted values, UUIDs, hex strings and numbers replaced by …: failures of one
    step that differ only in their values share it (`Invalid city 'Lisb0n'` and `Invalid city 'P0rto'`). HTTP status
    codes stay (`status 500` is not `status 404`; `expected status 200 but got 500` keeps both). The values are
    replaced first and the line cut after, so no token is cut half way and the length of a value never changes the
    shape."""
    line = _first_line(message)
    has_status_word = bool(_STATUS_WORD.search(line))
    line = _QUOTED.sub(lambda m: f"{m.group(1)}{PLACEHOLDER}{m.group(1)}", line)
    for pattern in (_UUID, _HEX_PREFIXED, _HEX):
        line = pattern.sub(PLACEHOLDER, line)
    line = _NUMBER.sub(lambda m: _number(line, m, has_status_word), line)
    return _SPACE.sub(" ", line).strip()[:HEADLINE]
