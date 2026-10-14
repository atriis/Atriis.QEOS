"""Which failed steps are one step (spec 2026-10-14 §3.2).

A step is its step definition, the code that runs it, when the collector reported one (0.8.0 and later): `When I
search Lisbon` and `When I search Porto` are one step with other parameters. Without one, the step text is the
identity, compared without case and with runs of whitespace collapsed. The key is a short hash of either, safe in a
URL fragment (the run page's `#step-<key>`)."""
import hashlib
from typing import Optional, Tuple

KEY_LENGTH = 16


def step_text_identity(text: str) -> str:
    return " ".join(text.split()).lower()


def step_key(definition: Optional[str], text: str) -> Tuple[str, str]:
    """(key, by), `by` being "definition" or "text"."""
    by, identity = ("definition", definition) if definition else ("text", step_text_identity(text))
    return hashlib.sha256(f"{by}\0{identity}".encode("utf-8")).hexdigest()[:KEY_LENGTH], by
