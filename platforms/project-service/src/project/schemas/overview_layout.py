"""Overview layouts: request and response bodies, and validation against the shared widget catalogue
(shared/qeos_shared/overview_widgets.json; spec 2026-10-11 §3.2, plan Ruling 8)."""
import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from qeos_shared.overview_widgets import load_catalog

CATALOG = load_catalog()
MAX_WIDGETS: int = CATALOG["max_widgets"]
MAX_BODY_BYTES: int = CATALOG["max_body_bytes"]
_WIDGET_ID = re.compile(CATALOG["widget_id_pattern"])
_LAYOUT_KEYS = {"schema", "widgets"}
_WIDGET_KEYS = {"id", "type", "size", "settings"}
_REQUIRED_WIDGET_KEYS = {"id", "type", "size"}


class LayoutError(ValueError):
    """The layout breaks a catalogue rule; the message names where."""


def _check_setting(where: str, name: str, value: Any) -> None:
    spec = CATALOG["settings"][name]
    if spec["kind"] == "choice":
        allowed = spec["values"]
        # A bool is an int and 5.0 == 5 in Python: only the exact JSON type of the allowed values passes
        if isinstance(value, bool) or type(value) is not type(allowed[0]) or value not in allowed:
            raise LayoutError(f"{where}: {value!r} is not one of {', '.join(str(v) for v in allowed)}")
        return
    low, high = spec["min_length"], spec["max_length"]
    if not isinstance(value, str) or not low <= len(value) <= high or "\x00" in value:
        raise LayoutError(f"{where}: must be {low}-{high} characters with no NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate: JSON allows it, PostgreSQL would reject it
        raise LayoutError(f"{where}: must be valid text (a lone surrogate is not)")


def validate_layout(layout: Any) -> dict:
    """Returns the layout unchanged, or raises LayoutError at the first rule it breaks."""
    if not isinstance(layout, dict):
        raise LayoutError("layout must be an object")
    extra = set(layout) - _LAYOUT_KEYS
    if extra:
        raise LayoutError(f"layout: unknown key {sorted(extra)[0]!r}")
    schema = layout.get("schema")
    if type(schema) is not int or schema != CATALOG["schema"]:
        raise LayoutError(f"schema must be {CATALOG['schema']}")
    widgets = layout.get("widgets")
    if not isinstance(widgets, list):
        raise LayoutError("widgets must be a list")
    if len(widgets) > MAX_WIDGETS:
        raise LayoutError(f"a layout holds at most {MAX_WIDGETS} widgets")
    seen: set = set()
    for index, widget in enumerate(widgets):
        where = f"widgets[{index}]"
        if not isinstance(widget, dict):
            raise LayoutError(f"{where} must be an object")
        missing = _REQUIRED_WIDGET_KEYS - set(widget)
        if missing:
            raise LayoutError(f"{where}: missing {sorted(missing)[0]!r}")
        extra = set(widget) - _WIDGET_KEYS
        if extra:
            raise LayoutError(f"{where}: unknown key {sorted(extra)[0]!r}")
        widget_id = widget["id"]
        if not isinstance(widget_id, str) or not _WIDGET_ID.fullmatch(widget_id):
            raise LayoutError(f"{where}.id: 1-32 characters of A-Z, a-z, 0-9, _ and -")
        if widget_id in seen:
            raise LayoutError(f"{where}.id: duplicate id {widget_id!r}")
        seen.add(widget_id)
        widget_type = widget["type"]
        if not isinstance(widget_type, str) or widget_type not in CATALOG["types"]:
            raise LayoutError(f"{where}.type: unknown type {widget_type!r}")
        if not isinstance(widget["size"], str) or widget["size"] not in CATALOG["sizes"]:
            raise LayoutError(f"{where}.size: must be normal or wide")
        settings = widget.get("settings", {})
        if not isinstance(settings, dict):
            raise LayoutError(f"{where}.settings must be an object")
        declared = CATALOG["types"][widget_type]["settings"]
        for name, value in settings.items():
            if name not in declared:
                raise LayoutError(f"{where}.settings: {widget_type} has no setting {name!r}")
            _check_setting(f"{where}.settings.{name}", name, value)
    return layout


class LayoutIn(BaseModel):
    """PUT body: the layout and the version editing started from (0 creates; plan Ruling 7)."""

    model_config = ConfigDict(extra="forbid")

    layout: dict
    version: StrictInt = Field(ge=0)

    @field_validator("layout")
    @classmethod
    def _valid(cls, value: dict) -> dict:
        return validate_layout(value)


class PersonalMeta(BaseModel):
    version: int
    updated_at: datetime


class ProjectMeta(BaseModel):
    version: int
    updated_by: int
    updated_at: datetime
    # Reset to project default and "Edit project default" need it even when a personal layout wins (plan Ruling 4)
    layout: dict


class OverviewLayoutOut(BaseModel):
    effective: Optional[dict] = None
    source: Literal["personal", "project", "builtin"]
    personal: Optional[PersonalMeta] = None
    project: Optional[ProjectMeta] = None


class LayoutRowOut(BaseModel):
    layout: dict
    version: int
    updated_by: int
    updated_at: datetime
