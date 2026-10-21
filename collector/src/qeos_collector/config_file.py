"""`.qeos.yml`: optional per-project defaults, read from the working directory.

`.qav.yml`, the name before the QEOS rename, is read when `.qeos.yml` does not exist.

Parsed by a deliberately small built-in reader — flat `key: value` pairs and
string lists — so the collector keeps zero dependencies (the single-file
zipapp depends on that). It is a YAML subset: nested mappings, anchors and
multi-line scalars are rejected rather than misread.
"""
from __future__ import annotations

import os
from typing import Dict, List, Union

from qeos_collector.upload import ConfigError

FILE_NAME = ".qeos.yml"
LEGACY_FILE_NAME = ".qav.yml"  # deprecated; read only when FILE_NAME is missing

STRING_KEYS = ("url", "environment", "ca-file", "spool", "ci-provider", "branch")
BOOL_KEYS = ("fail-on-error", "no-changes", "no-screenshots", "no-artifacts", "gate")
LIST_KEYS = ("patterns", "components", "features")
KNOWN = (*STRING_KEYS, *BOOL_KEYS, *LIST_KEYS)

Value = Union[str, bool, List[str]]


def uses_legacy_file(directory: str) -> bool:
    """True when only the deprecated `.qav.yml` exists, so it is the one read."""
    return (not os.path.exists(os.path.join(directory, FILE_NAME))
            and os.path.exists(os.path.join(directory, LEGACY_FILE_NAME)))


def load_config(directory: str) -> Dict[str, Value]:
    name = LEGACY_FILE_NAME if uses_legacy_file(directory) else FILE_NAME
    path = os.path.join(directory, name)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    except UnicodeDecodeError as exc:
        raise ConfigError(f"cannot read {path}: it is not UTF-8 text (byte {exc.start})") from None

    config: Dict[str, Value] = {}
    current_list: "List[str] | None" = None
    for number, raw in enumerate(lines, start=1):
        line = raw.split("#", 1)[0] if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        where = f"{path}:{number}"
        if line.startswith((" ", "\t")):
            item = line.strip()
            if current_list is None or not item.startswith("- "):
                raise ConfigError(f"{where}: only flat `key: value` pairs and `- item` lists are supported")
            current_list.append(_unquote(item[2:]))
            continue
        current_list = None
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator:
            raise ConfigError(f"{where}: expected `key: value`")
        if key not in KNOWN:
            allowed = ", ".join(KNOWN)
            raise ConfigError(f"{where}: unknown key {key!r} (allowed: {allowed}); the API key is environment-only")
        value = value.strip()
        if key in LIST_KEYS:
            if value:
                raise ConfigError(f"{where}: {key} must be a `- item` list on the following lines")
            config[key] = current_list = []
        elif key in BOOL_KEYS:
            if value.lower() not in ("true", "false"):
                raise ConfigError(f"{where}: {key} must be true or false")
            config[key] = value.lower() == "true"
        else:
            if not value:
                raise ConfigError(f"{where}: {key} has no value")
            config[key] = _unquote(value)
    return config


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value
