"""Cucumber helpers for test impact (spec 2026-10-13 §2): where a suggested scenario is, as a Cucumber location.

`impact --format cucumber` reads the lines from the local .feature files (plan Ruling 14): English keywords only; a
classpath: uri, a file in another language or one outside the working directory gives no line, and the scenario is
named instead. run-impact takes its lines from Cucumber's own dry run, and this module holds its Cucumber arguments
(plan Rulings 7, 8, 9, 21)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, List, Optional, Sequence, Tuple

from qeos_collector import formats
from qeos_collector.junit import CLASS_NAME_LENGTH, NAME_LENGTH, ParsedFile

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


# --- run-impact (Phase 3) -------------------------------------------------------------

FLAVOURS = ("js", "jvm", "ruby")
_JVM_PLUGIN = "-Dcucumber.plugin="
WORKDIR = ".qeos-impact"  # run-impact's files, under the working directory (plan Ruling 16)
# Options that take a value, so their value is never read as a feature path
_JS_VALUE_OPTIONS = frozenset({
    "-c", "--config", "-f", "--format", "--format-options", "--i18n-keywords", "-i", "--import", "-l", "--loader",
    "--language", "--name", "--order", "-p", "--profile", "--parallel", "--plugin", "--plugin-options", "-r",
    "--require", "--require-module", "--retry", "--retry-tag-filter", "--shard", "-t", "--tags", "--world-parameters",
})
_RUBY_VALUE_OPTIONS = frozenset({
    "-r", "--require", "-f", "--format", "-o", "--out", "-t", "--tags", "-n", "--name", "-p", "--profile", "-e",
    "--exclude", "-l", "--lines", "--i18n", "--order", "--retry", "--snippet-type", "--language",
})


@dataclass(frozen=True)
class Scenario:
    """A scenario, or an outline row, as a Cucumber dry run reports it."""

    feature: str  # the feature's name: a result's suite
    uri: str      # "/"-separated: a result's class_name
    name: str
    line: int

    @property
    def location(self) -> str:
        return f"{self.uri}:{self.line}"

    @property
    def key(self) -> Tuple[str, str]:
        """(class_name, name) as an upload stores them (formats._row cuts them the same way): what a suggested test
        is matched on. Not the suite: a renamed feature keeps its scenarios."""
        return self.uri[:CLASS_NAME_LENGTH], self.name[:NAME_LENGTH]


def _program(token: str) -> str:
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".cmd", ".exe", ".bat", ".ps1"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_cucumber_js(token: str) -> bool:
    return _program(token) == "cucumber-js" or "@cucumber/cucumber" in token.replace("\\", "/")


def detect_flavour(command: Sequence[str]) -> Optional[str]:
    """js, jvm or ruby from the command; None when it does not show (`npm test`, a script): --cucumber then says."""
    if any(_is_cucumber_js(token) for token in command):
        return "js"
    names = [_program(token) for token in command]
    first = names[0] if names else ""
    if first in ("mvn", "mvnw", "gradle", "gradlew"):
        return "jvm"
    if first == "cucumber" or (first == "bundle" and "cucumber" in names):
        return "ruby"
    return None


def with_separator(flavour: str, command: Sequence[str]) -> List[str]:
    """npm and pnpm hand arguments to the script only after "--"."""
    if flavour == "js" and command and _program(command[0]) in ("npm", "pnpm") and "--" not in command[1:]:
        return [*command, "--"]
    return list(command)


def _runner_index(flavour: str, command: Sequence[str]) -> Optional[int]:
    for index, token in enumerate(command):
        if (flavour == "js" and _is_cucumber_js(token)) or (flavour == "ruby" and _program(token) == "cucumber"):
            return index
    return None


def _names_features(arg: str, cwd: str) -> bool:
    plain = re.sub(r"(:\d+)+$", "", arg)
    return (plain.endswith(".feature") or any(c in plain for c in "*?[") or os.path.basename(plain).startswith("@")
            or os.path.isdir(os.path.join(cwd, plain)))


def strip_paths(flavour: str, command: Sequence[str], cwd: str) -> Tuple[List[str], List[str]]:
    """(the command without the feature paths it names, those paths). Such paths would add scenarios to every stage
    (cucumber-js adds them to the rerun file's). Only what the command shows: paths inside an npm script or a profile
    stay, and run-impact's stage-1 check catches them (plan Ruling 8)."""
    if flavour == "jvm":
        removed = [arg for arg in command if arg.startswith("-Dcucumber.features=")]
        return [arg for arg in command if arg not in removed], removed
    start = _runner_index(flavour, command)
    if start is None:
        return list(command), []
    values = _JS_VALUE_OPTIONS if flavour == "js" else _RUBY_VALUE_OPTIONS
    kept, removed, takes_value = list(command[: start + 1]), [], False
    for arg in command[start + 1:]:
        if takes_value:
            kept.append(arg)
            takes_value = False
        elif arg.startswith("-"):
            kept.append(arg)
            takes_value = arg in values  # "--tags @x"; "--tags=@x" carries its own value
        elif _names_features(arg, cwd):
            removed.append(arg)
        else:
            kept.append(arg)
    return kept, removed


def dry_run_arguments(flavour: str) -> List[str]:
    return ["-Dcucumber.execution.dry-run=true"] if flavour == "jvm" else ["--dry-run"]


def _relative(path: PurePath, cwd: str) -> str:
    """Relative to the working directory, with "/". On another Windows drive there is no relative path: then the
    absolute one (a rerun file cucumber-js cannot read, which run-impact's checks catch)."""
    try:
        return PurePath(os.path.relpath(str(path), cwd)).as_posix()
    except ValueError:
        return path.as_posix()


def report_arguments(flavour: str, report: PurePath, cwd: str) -> List[str]:
    """A Cucumber JSON report at `report`, written with "/" whatever the runner's OS (plan Ruling 21). cucumber-js
    gets it relative to the working directory: `json:C:/…` has two colons, which it warns about (12.6.0)."""
    if flavour == "js":
        return ["--format", f"json:{_relative(report, cwd)}"]
    if flavour == "ruby":
        return ["--format", "json", "--out", report.as_posix()]
    return [f"{_JVM_PLUGIN}json:{report.as_posix()}"]


def with_report(flavour: str, argv: Sequence[str], report: PurePath, cwd: str) -> List[str]:
    """argv with a Cucumber JSON report at `report`. A cucumber-jvm command that already sets cucumber.plugin keeps
    its plugins: ours joins the last such property with a comma, since a second -D would replace it."""
    if flavour == "jvm":
        at = [i for i, arg in enumerate(argv) if arg.startswith(_JVM_PLUGIN)]
        if at:
            plugins = argv[at[-1]][len(_JVM_PLUGIN):].strip().rstrip(",")
            merged = list(argv)
            merged[at[-1]] = _JVM_PLUGIN + (f"{plugins}," if plugins else "") + f"json:{report.as_posix()}"
            return merged
    return [*argv, *report_arguments(flavour, report, cwd)]


def rerun_argument(flavour: str, rerun: PurePath, cwd: str) -> str:
    if flavour == "js":
        # cucumber-js 12 reads an argument as a rerun file only when its file name starts with "@", and joins the
        # argument to the working directory: a relative path (verified on 12.6.0)
        return _relative(rerun, cwd)
    if flavour == "ruby":
        return "@" + rerun.as_posix()
    return "-Dcucumber.features=@" + rerun.as_posix()


class Incomplete(ValueError):
    """A dry run listed scenarios that cannot be put in a rerun file (no line): run-impact cannot plan the stages."""


def read_scenarios(path) -> List[Scenario]:
    """The scenarios of a Cucumber JSON report (a dry run's), in report order, read by the upload's own parser
    (formats._cucumber_feature): a background is not one, and a scenario without a name keeps an empty name. Raises
    OSError or ValueError when there is no readable report, and Incomplete when Cucumber listed more scenarios than
    could be read: one left out of both stages would never run."""
    with open(path, "rb") as handle:
        data = json.load(handle)
    scenarios: List[Scenario] = []
    listed = 0
    for feature in data if isinstance(data, list) else []:
        if not isinstance(feature, dict) or "elements" not in feature:
            continue
        elements = feature.get("elements")
        listed += sum(1 for element in elements if isinstance(element, dict) and element.get("type") != "background"
                      ) if isinstance(elements, list) else 0
        parsed, lines = ParsedFile(path=str(path)), []  # type: ParsedFile, List[Optional[int]]
        formats._cucumber_feature(feature, parsed, lines)
        scenarios.extend(Scenario(row["suite"], row["class_name"], row["name"], line)
                         for row, line in zip(parsed.results, lines) if line is not None)
    if len(scenarios) != listed:
        raise Incomplete(f"listed {listed} scenario(s), of which {listed - len(scenarios)} without a line")
    return scenarios


def rerun_text(scenarios: Sequence[Scenario]) -> str:
    """One `uri:line[:line…]` entry per feature file, in first-seen order: the format cucumber-js, cucumber-jvm and
    Ruby Cucumber all read."""
    lines: Dict[str, List[int]] = {}
    for scenario in scenarios:
        lines.setdefault(scenario.uri, []).append(scenario.line)
    return "".join(f"{uri}:{':'.join(str(n) for n in sorted(set(found)))}\n" for uri, found in lines.items())


def write_rerun(path, scenarios: Sequence[Scenario]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(rerun_text(scenarios))


def _test_key(test: dict) -> Tuple[str, str]:
    return str(test.get("class_name") or "").replace("\\", "/"), str(test.get("name") or "")


def split(tests: Sequence[dict], scenarios: Sequence[Scenario]) -> Tuple[List[Scenario], List[Scenario], List[dict]]:
    """(stage 1, stage 2, suggested tests not among the scenarios). Every scenario lands in exactly one stage, in
    report order. A suggested test matches on (class_name, name): for Cucumber, the feature's uri and the scenario's
    name, so the rows of an outline that share its name go with it. A scenario without a name is never suggested:
    it runs in stage 2."""
    wanted = {_test_key(test) for test in tests}
    first = [s for s in scenarios if s.name and s.key in wanted]
    rest = [s for s in scenarios if not (s.name and s.key in wanted)]
    found = {s.key for s in first}
    return first, rest, [test for test in tests if _test_key(test) not in found]
