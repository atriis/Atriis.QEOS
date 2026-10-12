"""Scoring a change against the impact statistics (spec 2026-10-12 §3.3). Pure: the services load the rows.

For each test, the change's best path unit gives confidence = new_failures / changed_runs and lift = confidence /
base rate. A test is suggested when changed_runs >= 3, new_failures >= 2 and lift >= 2, strongest first, at most 50.
Tests whose file changed, that fail on the branch, or that have no history yet (fewer than NO_HISTORY_RUNS change
runs) are always included, labelled, outside that cap, each test once (plan Ruling 11). Below 20 runs with changed
files in the window, statistics are not used at all."""
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional

from src.ingestion.analytics.impact_rules import (
    MAX_PER_LABEL, MAX_STATISTICAL, MIN_CHANGED_RUNS, MIN_HISTORY_RUNS, MIN_LIFT, MIN_NEW_FAILURES, NO_HISTORY_RUNS,
    ChangedFiles,
)

STATISTICAL = "statistical"
TEST_FILE_CHANGED = "test_file_changed"
FAILING_ON_BRANCH = "failing_on_branch"
NO_HISTORY = "no_history"


@dataclass(frozen=True)
class ImpactTest:
    """A test by key and name. (Not named Test...: pytest would try to collect it.)"""

    test_key: str
    suite: str
    class_name: str
    name: str

    def out(self) -> dict:
        return {"test_key": self.test_key, "suite": self.suite, "class_name": self.class_name, "name": self.name}


@dataclass(frozen=True)
class PairStat:
    path_unit: str
    test_key: str
    changed_runs: int
    new_failures: int


@dataclass(frozen=True)
class BaseStat:
    test: ImpactTest
    runs: int
    new_failures: int
    file: Optional[str]
    flaky: bool

    @property
    def rate(self) -> float:
        return self.new_failures / self.runs if self.runs else 0.0


def evidence(pair: PairStat, base: BaseStat) -> Optional[dict]:
    """The pair's evidence when it passes all three thresholds, else None."""
    if pair.changed_runs < MIN_CHANGED_RUNS or pair.new_failures < MIN_NEW_FAILURES or base.rate <= 0:
        return None
    confidence = pair.new_failures / pair.changed_runs
    lift = confidence / base.rate
    if lift < MIN_LIFT:
        return None
    return {"path_unit": pair.path_unit, "changed_runs": pair.changed_runs, "new_failures": pair.new_failures,
            "confidence": round(confidence, 4), "lift": round(lift, 4), "base_rate": round(base.rate, 4)}


def _strength(found: dict) -> tuple:
    # Ties: more changed runs, then the more specific (longer) unit, then the unit itself for a stable answer
    return (found["confidence"], found["lift"], found["changed_runs"], len(found["path_unit"]), found["path_unit"])


def _entry(test: ImpactTest, kind: str, found: Optional[dict] = None) -> dict:
    return {**test.out(), "kind": kind, "evidence": found}


def suggest(units: Iterable[str], pairs: Iterable[PairStat], bases: Mapping[str, BaseStat], *, history_runs: int,
            changed_files: ChangedFiles, failing_on_branch: Iterable[ImpactTest]) -> dict:
    """The suggestion for one change. `pairs` may hold rows of other units (they are skipped); `bases` must hold the
    base row of every pair's test and every base row that can carry a label."""
    enough = history_runs >= MIN_HISTORY_RUNS
    best: Dict[str, dict] = {}
    if enough:
        wanted = set(units)
        for pair in pairs:
            base = bases.get(pair.test_key)
            if pair.path_unit not in wanted or base is None or base.flaky:
                continue
            found = evidence(pair, base)
            if found is not None and (pair.test_key not in best or _strength(found) > _strength(best[pair.test_key])):
                best[pair.test_key] = found
    ranked = sorted(best.items(), key=lambda item: (-item[1]["confidence"], -item[1]["lift"],
                                                   bases[item[0]].test.name, item[0]))
    tests = [_entry(bases[key].test, STATISTICAL, found) for key, found in ranked[:MAX_STATISTICAL]]
    listed = {entry["test_key"] for entry in tests}
    labelled = (
        (TEST_FILE_CHANGED, [b.test for b in bases.values() if changed_files.touches(b.file)]),
        (FAILING_ON_BRANCH, list(failing_on_branch)),
        (NO_HISTORY, [b.test for b in bases.values() if b.runs < NO_HISTORY_RUNS]),
    )
    for kind, candidates in labelled:
        fresh = sorted({t.test_key: t for t in candidates if t.test_key not in listed}.values(),
                       key=lambda t: (t.name, t.test_key))
        for test in fresh[:MAX_PER_LABEL]:
            tests.append(_entry(test, kind))
            listed.add(test.test_key)
    return {"state": "ok" if enough else "not_enough_history", "history_runs": history_runs,
            "needed_runs": MIN_HISTORY_RUNS, "statistical_total": len(best), "tests": tests}
