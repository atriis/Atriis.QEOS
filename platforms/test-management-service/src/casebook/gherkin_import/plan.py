"""Parsed scenarios + the project's imported cases -> what an import would do (ADR-023). Pure."""
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from qeos_shared.keys import test_key
from src.casebook.gherkin_import.parse import Issue, ParsedFile, ParsedScenario

SUMMARY_NAMES = {"create": "created", "update": "updated", "move": "moved", "reactivate": "reactivated",
                 "archive": "archived", "unchanged": "unchanged", "skip": "skipped"}


@dataclass
class Item:
    action: str
    path: str
    scenario: Optional[str]
    case_id: Optional[int] = None
    case_number: Optional[int] = None
    parsed: Optional[ParsedScenario] = None


@dataclass
class Plan:
    items: List[Item]
    errors: List[Issue] = field(default_factory=list)
    warnings: List[Issue] = field(default_factory=list)
    plan_hash: str = ""
    # The raw files an apply keeps (path, feature name, content): those that parsed. `uploaded` is every
    # path in the request, so a full import knows which stored files vanished from the folder.
    sources: List[tuple] = field(default_factory=list)
    uploaded: set = field(default_factory=set)
    full: bool = False

    def summary(self) -> dict:
        counts = {name: 0 for name in SUMMARY_NAMES.values()}
        for item in self.items:
            counts[SUMMARY_NAMES[item.action]] += 1
        return counts


@dataclass(frozen=True)
class Existing:
    id: int
    number: int
    source_key: str
    source_path: str
    status: str
    title: str
    gherkin: str
    labels: tuple
    priority: str
    automated_test_key: Optional[str] = None
    automated_name: Optional[str] = None
    feature_name: Optional[str] = None
    scenario_name: Optional[str] = None
    scenario_line: Optional[int] = None


def link_is_import_owned(key: Optional[str], name: Optional[str], feature_name: str, source_path: str) -> bool:
    """True when the case's automated link is empty or is the one an import computed for its current path.

    A link picked by hand never equals that key, so it is never touched. If the Feature name changes,
    an import-set link no longer looks import-owned either and is kept (ADR-023)."""
    if not key:
        return True
    return key == test_key(feature_name, source_path, name or "")


def _differs(case: Existing, scenario: ParsedScenario) -> bool:
    stale_link = (
        link_is_import_owned(case.automated_test_key, case.automated_name, scenario.feature_name, case.source_path)
        and case.automated_test_key != scenario.test_key
    )
    return (
        case.title != scenario.title or case.gherkin != scenario.gherkin or case.labels != scenario.labels
        or (scenario.priority is not None and scenario.priority != case.priority) or stale_link
        or case.feature_name != scenario.feature_name[:500] or case.scenario_name != scenario.name
        or case.scenario_line != scenario.line
    )


def plan_hash(items: List[Item], suites: Optional[list] = None) -> str:
    """Over the sorted actions (action, path, scenario, case number), so the order files arrived in never
    changes it. It does not cover content: the confirm re-sends the same files. `suites` is a repository
    suite plan's hash_input(), when the import syncs suites."""
    rows = sorted([i.action, i.path, i.scenario or "", i.case_number or 0] for i in items)
    hashed = rows if suites is None else {"cases": rows, "suites": suites}
    return hashlib.sha256(json.dumps(hashed, separators=(",", ":")).encode("utf-8")).hexdigest()


def is_mass_archive(summary: dict, full: bool) -> bool:
    """A full import that would archive more than half of the imported cases that are live today
    (each of them is in a full plan as unchanged, updated, moved or archived). ADR-023."""
    live = summary["archived"] + summary["unchanged"] + summary["updated"] + summary["moved"]
    return full and live > 0 and summary["archived"] * 2 > live


def uploaded_paths(files: List[ParsedFile]) -> List[str]:
    return [f.path for f in files]


def build_plan(files: List[ParsedFile], existing: List[Existing], full: bool) -> Plan:
    plan = Plan(items=[], uploaded=set(uploaded_paths(files)), full=full)
    by_key: Dict[str, Existing] = {c.source_key: c for c in existing}
    uploaded = {f.path for f in files}
    broken = {f.path for f in files if f.errors}
    incoming: Dict[str, ParsedScenario] = {}
    for parsed_file in files:
        plan.errors += parsed_file.errors
        plan.warnings += parsed_file.warnings
        if parsed_file.errors:
            plan.items.append(Item("skip", parsed_file.path, None))
        for warning in parsed_file.warnings:
            if warning.skipped:
                plan.items.append(Item("skip", parsed_file.path, None))
        for scenario in parsed_file.scenarios:
            incoming[scenario.source_key] = scenario

    creates: List[ParsedScenario] = []
    for key, scenario in incoming.items():
        case = by_key.get(key)
        if case is None:
            creates.append(scenario)
            continue
        if case.status == "archived":
            action = "reactivate"
        elif _differs(case, scenario):
            action = "update"
        else:
            action = "unchanged"
        plan.items.append(Item(action, scenario.path, scenario.name, case.id, case.number, scenario))

    gone = [
        c for c in existing
        if c.source_key not in incoming and c.status != "archived" and c.source_path not in broken
        and (c.source_path in uploaded or full)
    ]

    # A move: exactly one gone case and exactly one new scenario share the same Gherkin text
    gone_by_text, new_by_text = defaultdict(list), defaultdict(list)
    for case in gone:
        gone_by_text[case.gherkin].append(case)
    for scenario in creates:
        new_by_text[scenario.gherkin].append(scenario)
    moved_cases, moved_scenarios = set(), set()
    for text, cases in gone_by_text.items():
        scenarios = new_by_text.get(text, [])
        if len(cases) == 1 and len(scenarios) == 1:
            case, scenario = cases[0], scenarios[0]
            plan.items.append(Item("move", scenario.path, scenario.name, case.id, case.number, scenario))
            moved_cases.add(case.id)
            moved_scenarios.add(scenario.source_key)

    for scenario in creates:
        if scenario.source_key not in moved_scenarios:
            plan.items.append(Item("create", scenario.path, scenario.name, parsed=scenario))
    for case in gone:
        if case.id not in moved_cases:
            plan.items.append(Item("archive", case.source_path, case.title, case.id, case.number))

    plan.items.sort(key=lambda i: (i.path, i.scenario or "", i.action))
    plan.plan_hash = plan_hash(plan.items)
    return plan
