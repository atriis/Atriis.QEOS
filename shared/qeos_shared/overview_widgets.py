"""The Overview widget catalogue: one JSON file that project-service validates layouts against and the
dashboard registry imports (spec docs/superpowers/specs/2026-10-11-customisable-overview-design.md §3.2).

The file sits beside this module. Services install this package editable (`-e ../../shared`, mirrored in
each Dockerfile), so it is read from the source tree; `package-data` in pyproject.toml makes a wheel carry
it as well.
"""
import json
from functools import lru_cache
from importlib.resources import files

FILE_NAME = "overview_widgets.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    """The parsed catalogue, read once per process. Callers must not mutate it."""
    return json.loads(files("qeos_shared").joinpath(FILE_NAME).read_text(encoding="utf-8"))
