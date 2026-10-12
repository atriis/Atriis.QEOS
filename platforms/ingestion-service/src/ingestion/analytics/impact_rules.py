"""Test impact analysis: the definitions and starting values (spec 2026-10-12 §3.1, §3.3). Pure: no database.

Every threshold is here, so tuning them is one file and one review."""
from typing import Iterable, List, Optional, Set

MODEL_VERSION = "stats-v1"
WINDOW_DAYS = 90             # statistics, history counts and "previous result" read the 90 days before
FOLDER_LEVELS = 3            # parent folders per changed path, the nearest ones (plan Ruling 3)
FOLDER_ONLY_ABOVE = 300      # a change of more distinct paths counts at folder level only
MIN_CHANGED_RUNS = 3
MIN_NEW_FAILURES = 2
MIN_LIFT = 2.0
MAX_STATISTICAL = 50
MIN_HISTORY_RUNS = 20        # runs with changed files in the window before statistics are used
MAX_PER_LABEL = 100          # always-included tests listed per label (plan Ruling 10)
FLAKY_MIN_RUNS = 5           # the Flaky view's defaults (plan Ruling 6)
FLAKY_MIN_FLIP_RATE = 0.3
FAILING = ("failed", "errored")

IGNORED_NAMES = frozenset({"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"})
IGNORED_SUFFIX = ".lock"
IGNORED_FOLDERS = frozenset({"dist", "build", "vendor", "node_modules"})


def _parts(path: str) -> List[str]:
    return [part for part in path.split("/") if part]


def is_ignored(path: str) -> bool:
    """Lock files by name, generated or vendored folders anywhere in the path (plan Ruling 5), and blank paths."""
    parts = _parts(path)
    if not parts:
        return True
    name = parts[-1]
    return name in IGNORED_NAMES or name.endswith(IGNORED_SUFFIX) or any(part in IGNORED_FOLDERS for part in parts[:-1])


def path_units(path: str, *, folders_only: bool = False, repository: Optional[str] = None) -> List[str]:
    """The path itself (unless folders_only) and its nearest parent folders, at most FOLDER_LEVELS, each ending in "/".
    Every unit is prefixed "<repository>:" when a repository is given (plan Ruling 4)."""
    parts = _parts(path)
    units = [] if folders_only or not parts else ["/".join(parts)]
    for depth in range(len(parts) - 1, max(0, len(parts) - 1 - FOLDER_LEVELS), -1):
        units.append("/".join(parts[:depth]) + "/")
    prefix = f"{repository}:" if repository else ""
    return [prefix + unit for unit in units]


def change_units(paths: Iterable[str], repository: Optional[str] = None) -> Set[str]:
    """The path units of one change: ignored paths add none; more than FOLDER_ONLY_ABOVE distinct paths count at
    folder level only."""
    distinct = set(paths)
    folders_only = len(distinct) > FOLDER_ONLY_ABOVE
    units: Set[str] = set()
    for path in distinct:
        if not is_ignored(path):
            units.update(path_units(path, folders_only=folders_only, repository=repository))
    return units


def base_branch_of(branch: Optional[str], base_branch: Optional[str], change_base_ref: Optional[str]) -> Optional[str]:
    """The branch a run's change goes into (plan Ruling 8): the PR base, else the diff's base ref without "origin/".
    "<sha>^" (a single-commit diff) and the run's own branch mean none."""
    candidate = base_branch or change_base_ref or ""
    if candidate.startswith("origin/"):
        candidate = candidate[len("origin/"):]
    if not candidate or candidate.endswith("^") or candidate == branch:
        return None
    return candidate


def suffixes(path: str) -> List[str]:
    """"a/b/c.py" -> ["a/b/c.py", "b/c.py", "c.py"]; backslashes count as separators."""
    parts = _parts(path.replace("\\", "/"))
    return ["/".join(parts[i:]) for i in range(len(parts))]


class ChangedFiles:
    """The change's paths, for "test file changed" (plan Ruling 12): a test's recorded file matches a changed path when
    one ends the other at a "/" (checkouts differ in their root), so a bare file name matches any path ending in it."""

    def __init__(self, paths: Iterable[str]) -> None:
        self.paths: Set[str] = {"/".join(_parts(path)) for path in paths} - {""}
        self._endings: Set[str] = {ending for path in self.paths for ending in suffixes(path)}

    def touches(self, test_file: Optional[str]) -> bool:
        if not test_file:
            return False
        endings = suffixes(test_file)
        return bool(endings) and (endings[0] in self._endings or any(ending in self.paths for ending in endings))
