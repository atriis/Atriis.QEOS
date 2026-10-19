"""Repository suites from the test repository's suite workflows: plan with the import, apply in its transaction.

Spec docs/superpowers/specs/2026-10-19-repository-suites-design.md, 5.2 and 5.3. A suite is keyed by
(workflow file, suite_id); its cases are the live imported cases under its folders or equal to its files."""
import posixpath
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.casebook.models import Case, Suite, SuiteCase
from src.casebook.repo_suites.parse import WORKFLOWS_DIR, ParsedLeg, parse_workflow
from src.casebook.schemas.suite import MAX_SUITE_CASES

# The names github_client and ci_targets accept: QEOS can only dispatch a workflow named like this
WORKFLOW_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}\.ya?ml$")
NAME_LENGTH = 100  # Suite.name, Suite.workflow, Suite.group_name, Suite.shard
EXTERNAL_ID_LENGTH = 200


@dataclass
class _Leg:
    """One repository suite as this sync wants it; suite_id is the existing row, None for a new one."""
    suite_id: Optional[int]
    workflow: str
    external_id: str
    name: str
    group_name: str
    shard: Optional[str]
    test_paths: List[str]


@dataclass
class SuitePlan:
    changes: List[dict] = field(default_factory=list)
    warnings: List[dict] = field(default_factory=list)
    legs: List[_Leg] = field(default_factory=list)  # every leg of the workflows synced, changed or not
    deleted: List[int] = field(default_factory=list)  # suite ids
    source_repo: Optional[str] = None

    def hash_input(self) -> list:
        return sorted([c["action"], c["workflow"], c["external_id"], c["name"]] for c in self.changes)


def _warn(plan: SuitePlan, workflow: str, external_id: Optional[str], message: str) -> None:
    plan.warnings.append({"workflow": workflow, "external_id": external_id, "message": message})


def _entries(leg: ParsedLeg) -> List[str]:
    return [folder + "/" for folder in leg.folders] + list(leg.files)


def _matches(entry: str, path: str) -> bool:
    return path.startswith(entry) if entry.endswith("/") else path == entry


def _members(test_paths: List[str], cases: List[Tuple[int, str]]) -> List[int]:
    return [case_id for case_id, path in cases if any(_matches(entry, path) for entry in test_paths)]


def case_paths_after(db: Session, project_id: int, case_plan) -> List[Tuple[int, str]]:
    """(case id, source_path) of the live imported cases once the case plan is applied. A case the plan
    creates has no id yet: it gets a negative stand-in (only counts and paths matter to the plan)."""
    rows = db.query(Case.id, Case.source_path).filter(
        Case.project_id == project_id, Case.source_key.isnot(None), Case.source_path.isnot(None),
        Case.status != "archived").all()
    live: Dict[int, str] = {case_id: path for case_id, path in rows}
    for n, item in enumerate(case_plan.items):
        if item.action == "archive":
            live.pop(item.case_id, None)
        elif item.action in ("update", "move", "reactivate"):
            live[item.case_id] = item.parsed.path
        elif item.action == "create":
            live[-1 - n] = item.parsed.path
    return list(live.items())


def plan_suites(db: Session, project_id: int, files: List[Tuple[str, str]], patterns: List[str],
                source_repo: Optional[str], case_paths: List[Tuple[int, str]]) -> SuitePlan:
    plan = SuitePlan(source_repo=source_repo)
    stored = db.query(Suite).filter(Suite.project_id == project_id).all()
    repository: Dict[Tuple[str, str], Suite] = {
        (s.workflow, s.external_id): s for s in stored if s.origin == "repository"}
    manual_names = {s.name for s in stored if s.origin != "repository"}

    sent, synced = set(), {}  # bare names sent; the workflows whose legs replace their stored suites
    for path, content in sorted(files):
        name = posixpath.basename(path)
        if posixpath.dirname(path) == WORKFLOWS_DIR:
            sent.add(name)
        if not WORKFLOW_NAME.match(name) or len(name) > NAME_LENGTH:
            _warn(plan, name, None, f"{name} is not a workflow file name QEOS can run; skipped")
            continue
        parsed, issues = parse_workflow(path, content)
        for issue in issues:
            _warn(plan, issue.workflow, issue.external_id, issue.message)
        legs = [leg for leg in (parsed.legs if parsed else ()) if len(leg.external_id) <= EXTERNAL_ID_LENGTH]
        for leg in (parsed.legs if parsed else ()):
            if len(leg.external_id) > EXTERNAL_ID_LENGTH:
                _warn(plan, name, None, f"A suite_id is over {EXTERNAL_ID_LENGTH} characters; its leg was skipped")
        if legs:  # otherwise the file is unusable: keep its suites
            synced[name] = (parsed.group_name[:NAME_LENGTH], legs)

    wanted = {(workflow, leg.external_id) for workflow, (_, legs) in synced.items() for leg in legs}
    covered = lambda workflow: any(fnmatchcase(f"{WORKFLOWS_DIR}/{workflow}", p) for p in patterns)  # noqa: E731
    gone = [row for key, row in repository.items()
            if (key[0] in synced and key not in wanted) or (key[0] not in sent and covered(key[0]))]
    for row in gone:
        plan.deleted.append(row.id)
        plan.changes.append({"action": "deleted", "workflow": row.workflow, "external_id": row.external_id,
                             "name": row.name})

    # Names this sync hands out: those of the suites it neither deletes nor syncs stay taken
    renamed = {s.id for (workflow, _), s in repository.items() if workflow in synced}
    taken = manual_names | {s.name for s in repository.values() if s.id not in renamed and s.id not in plan.deleted}
    for workflow, (group_name, legs) in sorted(synced.items()):
        for parsed_leg in legs:
            external_id = parsed_leg.external_id
            name = _free_name(plan, parsed_leg.name[:NAME_LENGTH], workflow, external_id, manual_names, taken)
            taken.add(name)
            row = repository.get((workflow, external_id))
            leg = _Leg(row.id if row else None, workflow, external_id, name, group_name,
                       parsed_leg.shard[:NAME_LENGTH] if parsed_leg.shard else None, _entries(parsed_leg))
            plan.legs.append(leg)
            _warn_membership(plan, leg, case_paths)
            if row is None:
                action = "created"
            elif (row.name, row.group_name, row.shard, row.test_paths) != (leg.name, leg.group_name, leg.shard,
                                                                          leg.test_paths) \
                    or (source_repo is not None and row.source_repo != source_repo):
                action = "updated"
            else:
                continue
            plan.changes.append({"action": action, "workflow": workflow, "external_id": external_id, "name": name})
    plan.changes.sort(key=lambda c: (c["workflow"], c["external_id"], c["action"]))
    return plan


def _free_name(plan: SuitePlan, wanted: str, workflow: str, external_id: str, manual: set, taken: set) -> str:
    """The leg's suite_name, or its suite_id when that name is taken (then the workflow, then a number)."""
    if wanted not in taken:
        return wanted
    name, n = external_id[:NAME_LENGTH], 2
    while name in taken:
        suffix = f" ({posixpath.splitext(workflow)[0]})" if n == 2 else f" ({n})"
        name = external_id[:NAME_LENGTH - len(suffix)] + suffix
        n += 1
    owner = "a suite made in QEOS" if wanted in manual else "another repository suite"
    _warn(plan, workflow, external_id, f"Name taken by {owner}; using {name}")
    return name


def _warn_membership(plan: SuitePlan, leg: _Leg, case_paths: List[Tuple[int, str]]) -> None:
    for entry in leg.test_paths:
        if not any(_matches(entry, path) for _, path in case_paths):
            _warn(plan, leg.workflow, leg.external_id, f"{entry} matches no imported case")
    if len(_members(leg.test_paths, case_paths)) > MAX_SUITE_CASES:
        _warn(plan, leg.workflow, leg.external_id,
              f"Over {MAX_SUITE_CASES} cases; only the first {MAX_SUITE_CASES} are in the suite")


def apply_suites(db: Session, project_id: int, user_id: int, plan: SuitePlan) -> None:
    """Write the plan, then recompute every repository suite's cases. Not committed here: the import commits
    the cases and the suites together."""
    now = datetime.now(timezone.utc)
    if plan.deleted:
        db.query(SuiteCase).filter(SuiteCase.suite_id.in_(plan.deleted)).delete(synchronize_session=False)
        db.query(Suite).filter(Suite.id.in_(plan.deleted)).delete(synchronize_session=False)
    rows = {r.id: r for r in db.query(Suite).filter(
        Suite.id.in_([leg.suite_id for leg in plan.legs if leg.suite_id is not None])).all()}
    # Two suites may swap names in one sync: park the renamed ones first, so the unique name never clashes
    renamed = [rows[leg.suite_id] for leg in plan.legs if leg.suite_id is not None and rows[leg.suite_id].name != leg.name]
    for row in renamed:
        row.name = f"~qeos-sync-{row.id}"
    db.flush()
    for leg in plan.legs:
        row = rows.get(leg.suite_id)
        if row is None:
            row = Suite(project_id=project_id, created_by=user_id, origin="repository", workflow=leg.workflow,
                        external_id=leg.external_id)
            db.add(row)
        values = {"name": leg.name, "group_name": leg.group_name, "shard": leg.shard, "test_paths": leg.test_paths}
        if plan.source_repo is not None:
            values["source_repo"] = plan.source_repo
        if any(getattr(row, k) != v for k, v in values.items()):
            for key, value in values.items():
                setattr(row, key, value)
            if row.id is not None:
                row.updated_at = now
    db.flush()
    _recompute_members(db, project_id, now)


def _recompute_members(db: Session, project_id: int, now: datetime) -> None:
    cases = [(case_id, path) for case_id, path, _ in db.query(Case.id, Case.source_path, Case.scenario_line).filter(
        Case.project_id == project_id, Case.source_key.isnot(None), Case.source_path.isnot(None),
        Case.status != "archived").order_by(Case.source_path, Case.scenario_line, Case.id).all()]
    suites = db.query(Suite).filter(Suite.project_id == project_id, Suite.origin == "repository").all()
    current: Dict[int, List[int]] = {s.id: [] for s in suites}
    for suite_id, case_id in db.query(SuiteCase.suite_id, SuiteCase.case_id).filter(
            SuiteCase.suite_id.in_(list(current))).order_by(SuiteCase.suite_id, SuiteCase.position).all():
        current[suite_id].append(case_id)
    for suite in suites:
        wanted = _members(suite.test_paths or [], cases)[:MAX_SUITE_CASES]
        if wanted == current[suite.id]:
            continue
        db.query(SuiteCase).filter(SuiteCase.suite_id == suite.id).delete(synchronize_session=False)
        db.add_all(SuiteCase(suite_id=suite.id, case_id=case_id, position=i) for i, case_id in enumerate(wanted))
        suite.updated_at = now
    db.flush()
