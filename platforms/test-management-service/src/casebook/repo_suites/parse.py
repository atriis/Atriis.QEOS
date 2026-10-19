"""Turn one suite workflow file into the legs (suites) it defines. Pure: no database, no network."""
import json
import posixpath
from dataclasses import dataclass

import yaml

WORKFLOWS_DIR = ".github/workflows"
RUNNER = "suite-runner.yml"
GROUP_PREFIX = "Suite - "


@dataclass(frozen=True)
class ParsedLeg:
    external_id: str
    name: str
    folders: tuple[str, ...]
    files: tuple[str, ...]
    shard: str | None
    globs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedWorkflow:
    workflow: str
    group_name: str
    legs: tuple[ParsedLeg, ...]


@dataclass(frozen=True)
class ParseIssue:
    workflow: str
    external_id: str | None
    message: str


GLOB_CHARS = ("*", "?", "[")


def is_glob(entry: str) -> bool:
    return any(c in entry for c in GLOB_CHARS)


def _split_paths(test_path: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Entries with `*`, `?` or `[` are globs (kept as written); other `.feature` entries are files, everything
    else is a folder (trailing slashes stripped)."""
    folders, files, globs = [], [], []
    for entry in test_path.split():
        if is_glob(entry):
            globs.append(entry)
        elif entry.endswith(".feature"):
            files.append(entry)
        else:
            folder = entry.rstrip("/")
            if folder:
                folders.append(folder)
    return tuple(folders), tuple(files), tuple(globs)


def _matrix_include(with_block: dict) -> list | None:
    matrix = with_block.get("matrix")
    if isinstance(matrix, str):
        matrix = json.loads(matrix)
    if not isinstance(matrix, dict) or not isinstance(matrix.get("include"), list):
        return None
    return matrix["include"]


def parse_workflow(path: str, content: str) -> tuple[ParsedWorkflow | None, list[ParseIssue]]:
    """`path` is the repository path. `None` means the file is unusable (keep its previous suites)."""
    workflow = posixpath.basename(path)

    def unusable(message: str):
        return None, [ParseIssue(workflow, None, message)]

    if posixpath.dirname(path) != WORKFLOWS_DIR or not workflow:
        return unusable(f"{path} is not directly inside {WORKFLOWS_DIR}")
    try:
        doc = yaml.safe_load(content)
    except (yaml.YAMLError, ValueError, RecursionError) as exc:  # never raise on repository input
        return unusable(f"The workflow is not valid YAML: {exc}")
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    caller = next(
        (j for j in (jobs or {}).values() if isinstance(j, dict) and str(j.get("uses", "")).endswith(RUNNER)),
        None,
    )
    if caller is None:
        return unusable(f"The workflow has no job that uses {RUNNER}")
    with_block = caller.get("with")
    try:
        include = _matrix_include(with_block) if isinstance(with_block, dict) else None
    except ValueError as exc:
        return unusable(f"The matrix is not valid JSON: {exc}")
    if include is None:
        return unusable("The runner job has no matrix with an include list")

    name = doc.get("name")
    group_name = str(name).strip() if name else ""
    group_name = group_name.removeprefix(GROUP_PREFIX).strip() or posixpath.splitext(workflow)[0]

    legs: list[ParsedLeg] = []
    issues: list[ParseIssue] = []
    seen: set[str] = set()
    for row in include:
        row = row if isinstance(row, dict) else {}
        external_id = str(row.get("suite_id") or "").strip()
        if not external_id:
            issues.append(ParseIssue(workflow, None, "A matrix leg has no suite_id and was skipped"))
            continue
        if external_id in seen:
            issues.append(ParseIssue(workflow, external_id, f"suite_id {external_id} appears more than once; the later leg was skipped"))
            continue
        seen.add(external_id)
        folders, files, globs = _split_paths(str(row.get("test_path") or ""))
        if not folders and not files and not globs:
            issues.append(ParseIssue(workflow, external_id, f"Leg {external_id} has no test_path and was skipped"))
            continue
        shard = str(row["shard"]).strip() if row.get("shard") else None
        legs.append(ParsedLeg(
            external_id=external_id,
            name=str(row.get("suite_name") or external_id).strip(),
            folders=folders,
            files=files,
            globs=globs,
            shard=shard or None,
        ))
    return ParsedWorkflow(workflow, group_name, tuple(legs)), issues
