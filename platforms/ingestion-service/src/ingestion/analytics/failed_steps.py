"""Which failed steps are one step (spec 2026-10-14 §3.2).

A step is its step definition, the code that runs it, when the collector reported one (0.8.0 and later): `When I
search Lisbon` and `When I search Porto` are one step with other parameters. Without one, the step text is the
identity, compared without case and with runs of whitespace collapsed. The key is a short hash of either, safe in a
URL fragment (the run page's `#step-<key>`)."""
import hashlib
import re
from typing import Optional, Tuple

from src.ingestion.analytics.signature import _HEX, _HEX_PREFIXED, _NUMBER, _SPACE, _UUID, headline

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


def error_shape(message: Optional[str]) -> str:
    """The first line of the error with quoted values, UUIDs, hex strings and numbers replaced by …: failures of one
    step that differ only in their values share it (`Invalid city 'Lisb0n'` and `Invalid city 'P0rto'`)."""
    line = headline(message) or ""
    line = _QUOTED.sub(lambda m: f"{m.group(1)}{PLACEHOLDER}{m.group(1)}", line)
    for pattern in (_UUID, _HEX_PREFIXED, _HEX, _NUMBER):
        line = pattern.sub(PLACEHOLDER, line)
    return _SPACE.sub(" ", line).strip()
