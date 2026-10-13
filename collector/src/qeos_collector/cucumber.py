"""Cucumber helpers for test impact (spec 2026-10-13 §2): where a suggested scenario is, as a Cucumber location.

`impact --format cucumber` reads the lines from the local .feature files (plan Ruling 14): English keywords only; a
classpath: uri, a file in another language or one outside the working directory gives no line, and the scenario is
named instead. run-impact takes its lines from Cucumber's own dry run."""
from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

_SCENARIO = ("Scenario", "Example")
_OUTLINE = ("Scenario Outline", "Scenario Template")
_EXAMPLES = ("Examples", "Scenarios")
_BLOCKS = ("Feature", "Rule", "Background")
_LANGUAGE = re.compile(r"^#\s*language\s*:\s*(\S+)")
# Special in a regular expression or in a double-quoted shell word: each becomes "." (any character) in a name filter
_UNSAFE = frozenset('\\^$.|?*+()[]{}"`!')
# Folders never looked into for .feature files
_PRUNE = frozenset({".git", "node_modules", ".venv", "venv", "target", "build", "dist", ".qeos-impact"})


def _cells(row: str) -> List[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _fill(name: str, header: List[str], values: List[str]) -> str:
    for column, value in zip(header, values):
        name = name.replace(f"<{column}>", value)
    return name


def scan_feature(text: str) -> List[Tuple[str, int]]:
    """(name, line) for each scenario, and for each example row of an outline, named as Cucumber names it: the
    outline's name with the row's values in place of <placeholders>. Empty for a file in another language."""
    found: List[Tuple[str, int]] = []
    outline: Optional[dict] = None
    fence: Optional[str] = None  # inside a doc string: its opening delimiter
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip().lstrip("\ufeff")
        if fence is not None:
            if line.startswith(fence):
                fence = None
            continue
        if line.startswith(('"""', "```")):
            fence = line[:3]
            continue
        if not line or line.startswith("@"):
            continue
        if line.startswith("#"):
            language = _LANGUAGE.match(line)
            if language and language.group(1).lower() != "en":
                return []
            continue
        if line.startswith("|"):
            if outline is not None and outline["examples"]:
                if outline["header"] is None:
                    outline["header"] = _cells(line)
                else:
                    found.append((_fill(outline["name"], outline["header"], _cells(line)), number))
            continue
        keyword, colon, rest = line.partition(":")
        if not colon:
            continue
        keyword = keyword.strip()
        if keyword in _SCENARIO:
            # Gherkin 6+: Examples after a plain Scenario make it an outline; until then it is one scenario
            found.append((rest.strip(), number))
            outline = {"name": rest.strip(), "examples": False, "header": None, "plain": True}
        elif keyword in _OUTLINE:
            outline = {"name": rest.strip(), "examples": False, "header": None, "plain": False}
        elif keyword in _EXAMPLES and outline is not None:
            if outline["plain"]:  # its own line is not run: only its rows are
                found.pop()
                outline["plain"] = False
            outline["examples"], outline["header"] = True, None
        elif keyword in _BLOCKS:
            outline = None
    return found


def locate(cwd: str, test: dict) -> List[str]:
    """`uri:line` for each scenario (or outline row) of the test's feature file that has the test's name; empty when
    the file cannot be read here."""
    uri = str(test.get("class_name") or "")
    if uri.startswith("classpath:"):
        return []
    relative = uri[len("file:"):] if uri.startswith("file:") else uri
    if not relative.endswith(".feature"):
        return []
    root = os.path.realpath(cwd)
    path = os.path.realpath(os.path.join(root, relative))
    try:
        if os.path.commonpath([root, path]) != root:
            return []
        with open(path, encoding="utf-8-sig") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError, ValueError):  # ValueError: another Windows drive
        return []
    name = str(test.get("name") or "")
    return [f"{uri}:{line}" for found, line in scan_feature(text) if found == name]


def name_filter(name: str) -> str:
    """`--name "^…$"` for a scenario whose line is unknown. Characters special to a regular expression or to a
    double-quoted shell word, and control characters, become "." so the line is safe to paste and still matches."""
    return '--name "^' + "".join("." if c in _UNSAFE or c < " " else c for c in name) + '$"'


def has_feature_files(cwd: str) -> bool:
    """Whether the working directory holds a .feature file (vendored and build folders are not looked into)."""
    for _root, directories, files in os.walk(cwd):
        directories[:] = [d for d in directories if d not in _PRUNE]
        if any(name.endswith(".feature") for name in files):
            return True
    return False
