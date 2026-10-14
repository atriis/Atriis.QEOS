"""Failed steps across test cases (spec 2026-10-14 §3.2-§3.3): in one run, each step that failed, in how many test
cases and with which errors, and since which run it has been failing.

A test's result in a run is its last row there (a re-run's later row wins, as latest-results with run_id); a skipped
last row did not run the step, so it neither continues nor stops a streak (plan rulings R3, P10). The streak walks
earlier runs of the run's branch only (ruling R15). All the steps' streaks come from the same two queries over the
union of the run's failing tests (ruling P12), never from queries per step."""
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session

from src.ingestion.analytics.failed_steps import error_shape, step_key
from src.ingestion.analytics.signature import headline
from src.ingestion.analytics.trends import as_utc
from src.ingestion.models import Run, RunResult
from src.ingestion.service.analytics_service import _latest_ranked, failed_step_of

COUNTED = ("passed", "failed", "errored")
MAX_TESTS = 50   # per error group
MAX_RUNS = 50    # the streak, this run included
MAX_DAYS = 90
MESSAGE_CHARS = 2000  # of an error message read from the database; error_shape reads at most this much


def failed_steps(db: Session, project_id: int, run: Run) -> dict:
    groups: Dict[str, List[dict]] = defaultdict(list)
    for row in _failing_rows(db, run.id):
        groups[row["step"]["key"]].append(row)
    if not groups:
        return {"steps": []}
    history = _History(db, project_id, run, {r["test_key"] for rows in groups.values() for r in rows})
    steps = [_step(history, key, rows) for key, rows in groups.items()]
    steps.sort(key=lambda s: (-s["cases"], s["pattern"].lower(), s["key"]))
    return {"steps": steps}


def _failing_rows(db: Session, run_id: int) -> List[dict]:
    # Only the first MESSAGE_CHARS of the message come over (the error shape and example read its first line), and
    # no details. Only rows with a stored failed step count: JUnit and pytest failures have none, and the case page's
    # fallback to details' first line would show their exception and code lines as steps.
    ranked = _latest_ranked(
        [Run.id == run_id],
        RunResult.name, RunResult.status, func.substr(RunResult.message, 1, MESSAGE_CHARS).label("message"),
        RunResult.failed_step_text, RunResult.failed_step_line, RunResult.failed_step_definition,
        RunResult.failed_step_pattern,
    )
    rows = []
    stored = select(ranked).where(ranked.c.position == 1, ranked.c.failed_step_text.is_not(None))
    for r in db.execute(stored).mappings():
        step = failed_step_of(r["status"], r["message"], None, r["failed_step_text"], r["failed_step_line"],
                              r["failed_step_definition"], r["failed_step_pattern"])
        if step is not None:
            rows.append({"test_key": r["test_key"], "name": r["name"], "message": r["message"], "step": step})
    return rows


def _step(history: "_History", key: str, rows: List[dict]) -> dict:
    definition = rows[0]["step"].get("definition")  # one key, one definition
    # Shown as the most frequent pattern, else the most frequent text (spec §3.2)
    shown = Counter(r["step"]["pattern"] for r in rows if r["step"].get("pattern")) \
        or Counter(r["step"]["text"] for r in rows)
    pattern = min(shown.items(), key=lambda item: (-item[1], item[0]))[0]
    step = {"key": key, "by": "definition" if definition else "text", "pattern": pattern}
    if definition:
        step["definition"] = definition
    step["cases"] = len(rows)
    step["errors"] = _errors(rows)
    since, last_passed = history.streak(key, rows)
    step["since"] = since
    if last_passed is not None:
        step["last_passed"] = last_passed
    return step


def _errors(rows: List[dict]) -> List[dict]:
    groups: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        groups[error_shape(row["message"])].append(row)
    out = []
    for shape, members in groups.items():
        members.sort(key=lambda r: (r["name"].lower(), r["test_key"]))
        entry = {
            "shape": shape,
            "example": next((headline(r["message"]) for r in members if headline(r["message"])), None),
            "cases": len(members),
            "tests": [{"test_key": r["test_key"], "name": r["name"], "text": r["step"]["text"]}
                      for r in members[:MAX_TESTS]],
        }
        if len(members) > MAX_TESTS:
            entry["more"] = len(members) - MAX_TESTS
        out.append(entry)
    out.sort(key=lambda e: (-e["cases"], e["shape"]))
    return out


class _History:
    """The earlier runs of the project on the run's branch (every branch when it has none) that ran any of the run's
    failing tests, newest first, each with the tests' last results there."""

    def __init__(self, db: Session, project_id: int, run: Run, tests: Set[str]):
        self.db, self.run, self.tests = db, run, sorted(tests)
        # Same branch as the run (user decision 2026-10-14, ruling R15); a run without a branch walks every branch
        self.scope = [Run.project_id == project_id, Run.branch == run.branch if run.branch else true()]
        self.cutoff = run.started_at - timedelta(days=MAX_DAYS)
        self.started: Dict[int, object] = {}
        self.results: Dict[str, List[Tuple[int, object]]] = defaultdict(list)  # test -> [(run id, row)]
        self._load()
        self._before: Optional[Set[str]] = None

    def _last_rows(self, *filters):
        """Each test's last row in each run within the scope, kept only when it ran (not skipped)."""
        last = (
            select(RunResult.run_id, RunResult.test_key, RunResult.status, RunResult.failed_step_text, RunResult.failed_step_definition, Run.started_at,
                   func.row_number().over(partition_by=(RunResult.run_id, RunResult.test_key),
                                          order_by=RunResult.id.desc()).label("last"))
            .join(Run, Run.id == RunResult.run_id)
            .where(*self.scope, RunResult.test_key.in_(self.tests), *filters)
        ).subquery()
        return select(last).where(last.c.last == 1, last.c.status.in_(COUNTED)).subquery()

    def _load(self) -> None:
        """One query: per test, its at most MAX_RUNS latest earlier runs in the window. A step's MAX_RUNS latest runs
        are each among the MAX_RUNS latest of one of its tests, so every step's walk is in here."""
        run = self.run
        earlier = or_(Run.started_at < run.started_at, and_(Run.started_at == run.started_at, Run.id < run.id))
        ran = self._last_rows(earlier, Run.started_at >= self.cutoff)
        ranked = select(ran, func.row_number().over(
            partition_by=ran.c.test_key, order_by=(ran.c.started_at.desc(), ran.c.run_id.desc())).label("position")
        ).subquery()
        for r in self.db.execute(select(ranked).where(ranked.c.position <= MAX_RUNS)):
            self.started[r.run_id] = r.started_at
            self.results[r.test_key].append((r.run_id, r))

    def _ran_before_window(self, tests: Iterable[str]) -> bool:
        """Any of the tests ran on the branch before the window; one query for every step that asks."""
        if self._before is None:
            ran = self._last_rows(Run.started_at < self.cutoff)
            self._before = set(self.db.execute(select(ran.c.test_key).distinct()).scalars())
        return any(t in self._before for t in tests)

    def streak(self, key: str, rows: List[dict]) -> Tuple[dict, Optional[dict]]:
        """Walk back through the earlier runs holding any of the step's failing tests; the streak goes on while one of
        them failed at this step, at most MAX_RUNS runs (this one included) or MAX_DAYS days."""
        tests = {r["test_key"] for r in rows}
        # Rows stored before collector 0.8.0 have no definition and are keyed by their text: the texts this step failed
        # with in this run count as this step too, so upgrading the collector does not restart the streak (ruling R4)
        keys = {key} | {step_key(None, r["step"]["text"])[0] for r in rows}
        by_run: Dict[int, list] = defaultdict(list)
        for test in tests:
            for run_id, result in self.results.get(test, ()):
                by_run[run_id].append(result)
        candidates = sorted(by_run, key=lambda run_id: (self.started[run_id], run_id), reverse=True)[:MAX_RUNS]
        run = self.run
        since_id, since_at, runs, last_passed, stopped, full = run.id, run.started_at, 1, None, False, False
        for run_id in candidates:
            then = by_run[run_id]
            if any(_key_of(r) in keys for r in then):
                if runs == MAX_RUNS:  # one more than the cap: the streak is longer than we count
                    full = True
                    break
                since_id, since_at, runs = run_id, self.started[run_id], runs + 1
                continue
            stopped = True
            if any(r.status == "passed" for r in then):
                last_passed = {"run_id": run_id, "started_at": as_utc(self.started[run_id])}
            break
        capped = full or (not stopped and self._ran_before_window(tests))
        return {"run_id": since_id, "started_at": as_utc(since_at), "runs": runs, "capped": capped}, last_passed


def _key_of(row) -> Optional[str]:
    """The step key of a history row: only rows with a stored failed step have one (no message or details are loaded)."""
    step = failed_step_of(row.status, None, None, row.failed_step_text, None, row.failed_step_definition)
    return step["key"] if step else None
