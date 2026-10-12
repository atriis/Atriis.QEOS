"""Queries behind POST /analytics/report (docs/superpowers/specs/2026-10-08-report-deep-analysis-design.md).

One scoped-runs query over the previous period plus the period feeds every section. Counting stays in
SQL; sequences, streaks and signatures are computed in Python over the rows (src/ingestion/analytics).
The handler never writes."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence

from sqlalchemy import Integer, String, and_, any_, bindparam, case, distinct, false, func, not_, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.ingestion.analytics.report_causes import Occurrence, group_causes
from src.ingestion.analytics.report_stats import mean, percentile
from src.ingestion.analytics.report_streaks import Outcome, build_sequences, classify_streaks, count_flips, flips_by_bucket
from src.ingestion.analytics.report_period import Period, bucket_index, bucket_starts, iso, local_day
from src.ingestion.analytics.signature import headline, signature
from src.ingestion.analytics.trends import as_utc, pass_rate
from src.ingestion.models import Run, RunResult
from src.ingestion.service.analytics_service import muted_keys

STATEMENT_TIMEOUT = "20s"  # below the gateway's 30 s proxy_read_timeout
REPORT_TIMEOUT_MESSAGE = "This report took too long. Narrow the period or the filters."
QUERY_CANCELED = "57014"


@dataclass(frozen=True)
class Scope:
    project_id: int
    period: Period
    previous: Period
    branch: Optional[str]
    environment: Optional[str]
    ci_provider: Optional[str]
    origin: str                       # any | ci | qeos
    urls: tuple                       # lower-cased Play run URLs (origin != any)
    keys: Optional[tuple]             # lower-cased, de-duplicated test keys, or None

    @classmethod
    def from_request(cls, project_id: int, body, period: Period) -> "Scope":
        keys = None if body.test_keys is None else tuple(sorted({k.lower() for k in body.test_keys}))
        urls = tuple(sorted({u.lower() for u in (body.requested_run_urls or [])}))
        return cls(project_id=project_id, period=period, previous=period.previous(),
                   branch=body.branch or None, environment=body.environment or None,
                   ci_provider=body.ci_provider or None, origin=body.origin, urls=urls, keys=keys)


@dataclass(frozen=True)
class ScopedRun:
    id: int
    started_at: datetime
    branch: Optional[str]
    duration_ms: int
    total: int
    passed: int
    failed: int
    errored: int
    skipped: int
    current: bool  # in the period; False: in the previous period


def in_list(db: Session, column, values: Sequence, item_type=String):
    """`column IN values`. PostgreSQL gets one array parameter (`= ANY(:x)`), so 20,000 keys stay one
    bind; SQLite (the tests) gets an expanding IN."""
    values = list(values)
    if db.get_bind().dialect.name == "postgresql":
        return column == any_(bindparam(None, values, type_=ARRAY(item_type)))
    return column.in_(values)


def run_filters(db: Session, scope: Scope) -> list:
    """Project and window, then branch, environment, CI provider and origin. These are checked on the
    window's few thousand runs, so they need no index."""
    filters = [Run.project_id == scope.project_id, Run.started_at >= scope.previous.start,
               Run.started_at < scope.period.end]
    if scope.branch:
        filters.append(Run.branch == scope.branch)
    if scope.environment:
        filters.append(Run.environment == scope.environment)
    if scope.ci_provider:
        filters.append(Run.ci_provider == scope.ci_provider)
    if scope.origin == "qeos":
        filters.append(requested_from_qeos(db, scope))
    elif scope.origin == "ci":
        if scope.urls:  # no Play URLs: every run is CI
            filters.append(not_(requested_from_qeos(db, scope)))
    return filters


def requested_from_qeos(db: Session, scope: Scope):
    """A GitHub Actions run whose URL is one of a Play's github_run_url (ADR-026). The match is on the
    lower-cased URL; a trailing slash makes it another URL. Never sends an empty list to in_list."""
    if not scope.urls:
        return false()
    # A NULL URL makes the AND false, never NULL, so not_() of it keeps the run.
    return and_(Run.ci_provider == "github_actions", Run.ci_run_url.is_not(None),
                in_list(db, func.lower(Run.ci_run_url), scope.urls))


def key_filter(db: Session, scope: Scope) -> list:
    """The test_keys restriction for any query over test_results ([] without keys)."""
    return [] if scope.keys is None else [in_list(db, RunResult.test_key, scope.keys)]


def scoped_runs(db: Session, scope: Scope) -> List[ScopedRun]:
    rows = db.execute(
        select(Run.id, Run.started_at, Run.branch, Run.duration_ms, Run.total, Run.passed, Run.failed,
               Run.errored, Run.skipped)
        .where(*run_filters(db, scope))
        .order_by(Run.started_at, Run.id)
    ).all()
    start = scope.period.start
    return [ScopedRun(r.id, as_utc(r.started_at), r.branch, r.duration_ms, r.total, r.passed, r.failed,
                      r.errored, r.skipped, as_utc(r.started_at) >= start) for r in rows]


def runs_with_results(db: Session, scope: Scope, runs: List[ScopedRun]) -> set:
    """Ids of the runs that count: every scoped run, or with test_keys the runs that have at least one
    result for those keys."""
    if scope.keys is None or not runs:
        return {r.id for r in runs}
    rows = db.execute(
        select(RunResult.run_id).distinct()
        .where(in_list(db, RunResult.run_id, [r.id for r in runs], Integer), *key_filter(db, scope))
    ).all()
    return {run_id for (run_id,) in rows}


# Section name -> builder(db, scope, runs, context) -> dict. Tasks 4, 17, 19, 24, 25 register theirs.
SECTION_BUILDERS: Dict[str, Callable] = {}


@dataclass(frozen=True)
class Context:
    """What every section shares: the bucket and its starts, and the runs that count."""
    bucket: str
    starts: list
    counted: set


def build_report(db: Session, scope: Scope, sections: List[str], bucket: str, now: datetime) -> dict:
    runs = scoped_runs(db, scope)
    counted = runs_with_results(db, scope, runs)
    context = Context(bucket=bucket, starts=bucket_starts(scope.period, bucket), counted=counted)
    out = {
        "period": scope.period.out(),
        "previous_period": scope.previous.out(),
        "tz": scope.period.zone.key,
        "bucket": bucket,
        "generated_at": iso(now),
        "scope": {
            "runs": sum(1 for r in runs if r.current and r.id in counted),
            "previous_runs": sum(1 for r in runs if not r.current and r.id in counted),
            "test_keys": None if scope.keys is None else len(scope.keys),
        },
    }
    for name in sections:
        builder = SECTION_BUILDERS.get(name)
        out[name] = builder(db, scope, runs, context) if builder else None
    return out


def limit_statement_time(db: Session) -> None:
    """Every report query in this transaction is cancelled after 20 s (PostgreSQL only)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))


def is_timeout(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    return (getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)) == QUERY_CANCELED


FAILING = ("failed", "errored")
TOP = 10
MAX_FACETS = 50


@dataclass
class Counts:
    executions: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    duration_ms: int = 0  # sum of result durations; only filled when test_keys are set

    def add(self, other: "Counts") -> None:
        self.executions += other.executions
        self.passed += other.passed
        self.failed += other.failed
        self.errored += other.errored
        self.skipped += other.skipped
        self.duration_ms += other.duration_ms

    def out(self) -> dict:
        return {"executions": self.executions, "passed": self.passed, "failed": self.failed,
                "errored": self.errored, "skipped": self.skipped,
                "pass_rate": pass_rate(self.passed, self.executions, self.skipped)}


def _count(*statuses: str):
    return func.sum(case((RunResult.status.in_(statuses), 1), else_=0))


def run_counts(db: Session, scope: Scope, runs: List[ScopedRun]) -> Dict[int, Counts]:
    """Per counted run. Without test_keys the run's own counters (computed from its results at upload);
    with test_keys the results for those keys, which also gives the summed test time."""
    if scope.keys is None:
        return {r.id: Counts(r.total, r.passed, r.failed, r.errored, r.skipped) for r in runs}
    if not runs:
        return {}
    rows = db.execute(
        select(RunResult.run_id, func.count(RunResult.id), _count("passed"), _count("failed"), _count("errored"),
               _count("skipped"), func.sum(RunResult.duration_ms))
        .where(in_list(db, RunResult.run_id, [r.id for r in runs], Integer), *key_filter(db, scope))
        .group_by(RunResult.run_id)
    ).all()
    return {run_id: Counts(n, int(p or 0), int(f or 0), int(e or 0), int(s or 0), int(d or 0))
            for run_id, n, p, f, e, s, d in rows}


def _test_figures(db: Session, scope: Scope, ids: list) -> tuple:
    """(distinct tests executed, distinct tests with a failing execution) over the given runs."""
    if not ids:
        return 0, 0
    # Grouped, not count(DISTINCT): a hash over the keys instead of sorting every row by a 64-character key
    per_test = (
        select(RunResult.test_key, func.max(case((RunResult.status.in_(FAILING), 1), else_=0)).label("failing"))
        .where(in_list(db, RunResult.run_id, ids, Integer), *key_filter(db, scope))
        .group_by(RunResult.test_key)
    ).subquery()
    tests, failing = db.execute(select(func.count(), func.sum(per_test.c.failing))).one()
    return int(tests or 0), int(failing or 0)


def _totals(db: Session, scope: Scope, runs: List[ScopedRun], counts: Dict[int, Counts]) -> dict:
    total = Counts()
    for r in runs:
        total.add(counts[r.id])
    tests, failing = _test_figures(db, scope, [r.id for r in runs])
    durations = [r.duration_ms for r in runs]
    return {"runs": len(runs), **total.out(), "tests": tests, "failing_tests": failing,
            "avg_run_duration_ms": round(sum(durations) / len(durations)) if durations else None}


def _bucket_rows(scope: Scope, context: Context, runs, counts, shift_days: int) -> List[dict]:
    """One entry per bucket of the period. shift_days moves a previous-period run onto the bucket that
    lies `days` later, so the previous period lines up bucket by bucket (Ruling 2)."""
    per = [Counts() for _ in context.starts]
    per_runs = [0] * len(context.starts)
    zone = scope.period.zone
    for r in runs:
        index = bucket_index(local_day(r.started_at, zone) + timedelta(days=shift_days), context.starts, context.bucket)
        if index is None:
            continue
        per[index].add(counts[r.id])
        per_runs[index] += 1
    return [{"date": (start - timedelta(days=shift_days)).isoformat(), "runs": per_runs[i], **per[i].out()}
            for i, start in enumerate(context.starts)]


def _test_rows(db: Session, scope: Scope, ids: list, *, slowest: bool) -> List[dict]:
    """The 10 most failing (only tests with a failure) or slowest tests, ordered as /tests orders them."""
    if not ids:
        return []
    failures = _count(*FAILING)
    average = func.avg(RunResult.duration_ms)
    query = (
        select(RunResult.test_key, func.max(RunResult.suite), func.max(RunResult.class_name),
               func.max(RunResult.name), func.count(RunResult.id), failures, _count("passed"), _count("skipped"),
               average)
        .where(in_list(db, RunResult.run_id, ids, Integer), *key_filter(db, scope))
        .group_by(RunResult.test_key)
    )
    query = query.order_by(average.desc(), RunResult.test_key) if slowest else \
        query.having(failures > 0).order_by(failures.desc(), RunResult.test_key)
    out = []
    for key, suite, class_name, name, n, failed, passed, skipped, avg in db.execute(query.limit(TOP)).all():
        row = {"test_key": key, "suite": suite, "class_name": class_name, "name": name, "executions": n}
        if slowest:
            row["avg_duration_ms"] = round(float(avg)) if avg is not None else None
        else:
            row["failures"] = int(failed)
            row["pass_rate"] = pass_rate(int(passed), n, int(skipped))
        out.append(row)
    return out


def _branches(runs: List[ScopedRun], counts: Dict[int, Counts]) -> List[dict]:
    grouped: Dict[Optional[str], list] = {}
    for r in runs:
        grouped.setdefault(r.branch, []).append(r)
    rows = []
    for branch, members in grouped.items():
        total = Counts()
        for r in members:
            total.add(counts[r.id])
        rows.append({"branch": branch, "runs": len(members), "executions": total.executions,
                     "failures": total.failed + total.errored,
                     "pass_rate": pass_rate(total.passed, total.executions, total.skipped)})
    rows.sort(key=lambda b: (-b["runs"], b["branch"] is None, b["branch"] or ""))
    return rows[:TOP]


def _facets(db: Session, scope: Scope) -> dict:
    """The period's busiest values, ignoring every other filter, so they offer a way out of an empty result."""
    out = {}
    for name, column in (("branches", Run.branch), ("environments", Run.environment), ("ci_providers", Run.ci_provider)):
        rows = db.execute(
            select(column, func.count(Run.id))
            .where(Run.project_id == scope.project_id, Run.started_at >= scope.period.start,
                   Run.started_at < scope.period.end, column.is_not(None))
            .group_by(column).order_by(func.count(Run.id).desc(), column).limit(MAX_FACETS)
        ).all()
        out[name] = [value for value, _ in rows]
    return out


def summary(db: Session, scope: Scope, runs: List[ScopedRun], context: Context) -> dict:
    counted = [r for r in runs if r.id in context.counted]
    counts = run_counts(db, scope, counted)
    current = [r for r in counted if r.current]
    previous = [r for r in counted if not r.current]
    current_ids = [r.id for r in current]
    return {
        "current": _totals(db, scope, current, counts),
        "previous": _totals(db, scope, previous, counts) if previous else None,
        "buckets": _bucket_rows(scope, context, current, counts, 0),
        "previous_buckets": _bucket_rows(scope, context, previous, counts, scope.period.days),
        "top_failing": _test_rows(db, scope, current_ids, slowest=False),
        "slowest": _test_rows(db, scope, current_ids, slowest=True),
        "branches": _branches(current, counts),
        "facets": _facets(db, scope),
    }


SECTION_BUILDERS["summary"] = summary


MESSAGE_PREFIX = 2000  # only the first line names a cause; this bounds memory on long stack traces


def _bucket_of(scope: Scope, context: Context, run: ScopedRun) -> Optional[int]:
    if not run.current:
        return None
    return bucket_index(local_day(run.started_at, scope.period.zone), context.starts, context.bucket)


def failure_causes(db: Session, scope: Scope, runs: List[ScopedRun], context: Context) -> dict:
    """The failing rows of the in-scope runs of both periods (through ix_test_results_failing), grouped by
    signature in Python, as the run view does."""
    by_id = {r.id: r for r in runs if r.id in context.counted}
    if not by_id:
        return group_causes([], len(context.starts))
    rows = db.execute(
        select(RunResult.run_id, RunResult.test_key, RunResult.suite, RunResult.class_name, RunResult.name,
               RunResult.status, func.substr(RunResult.message, 1, MESSAGE_PREFIX))
        .where(in_list(db, RunResult.run_id, list(by_id), Integer), RunResult.status.in_(FAILING),
               *key_filter(db, scope))
    ).all()
    muted = {key.lower() for key in muted_keys(db, scope.project_id)}
    occurrences = []
    for run_id, key, suite, class_name, name, status, message in rows:
        run = by_id[run_id]
        occurrences.append(Occurrence(signature(message), headline(message), key, suite, class_name, name, status,
                                      run_id, run.started_at, run.current, key.lower() in muted,
                                      _bucket_of(scope, context, run)))
    return group_causes(occurrences, len(context.starts))


SECTION_BUILDERS["failure_causes"] = failure_causes


MAX_NEWLY = 100
MAX_FIXED = 100
MAX_LONGEST = 50


def _candidates(db: Session, scope: Scope, ids: list) -> Dict[str, tuple]:
    """Tests with at least one failing execution in scope (previous period plus period): a test that never
    failed cannot regress, be fixed or flip. The partial index serves this read."""
    rows = db.execute(
        select(RunResult.test_key, func.max(RunResult.suite), func.max(RunResult.class_name), func.max(RunResult.name))
        .where(in_list(db, RunResult.run_id, ids, Integer), RunResult.status.in_(FAILING), *key_filter(db, scope))
        .group_by(RunResult.test_key)
    ).all()
    return {key: (suite, class_name, name) for key, suite, class_name, name in rows}


def _outcomes(db: Session, ids: list, keys: list, by_id: Dict[int, ScopedRun], *,
              with_headlines: bool = True) -> List[Outcome]:
    """The outcomes that streaks and flips depend on, per test and branch.

    A test's outcome in a run is its last attempt (highest id) among non-skipped rows. Only the failing outcomes
    and the outcomes right before and right after one on the same branch are returned: a pass between two passes
    starts, ends and flips nothing, so every streak, fix, time to fix and flip is the same as over the full
    sequence, from about a tenth of the rows. Only a sequence's last outcome, when it fails, gets its headline (the
    only one the section shows); the ranking never reads `message`.

    One sort and one window over the attempts in sequence order (run start, run, then attempt): a row is its run's
    outcome when the next row belongs to another run, and the row before a run's first attempt is the previous
    outcome. Only across a retried run is the next row not the next outcome, so an outcome that was retried, or is
    followed by a retried run, is kept whatever its neighbours.

    Test impact's "newly failed" reads the same outcomes (service/impact_history.py): every failing outcome comes with
    the one before it on its branch. `by_id` values need only `branch` and `started_at`; `with_headlines=False` skips
    the headline read, which only this section shows."""
    if not ids or not keys:
        return []
    keys = list(keys)
    filters = (in_list(db, RunResult.run_id, ids, Integer), RunResult.status != "skipped",
               in_list(db, RunResult.test_key, keys))
    numbered_rows = db.get_bind().dialect.name == "postgresql"
    if numbered_rows:
        # The sort partitions on the key's number, not the 64-character key: about a third faster on 4 million rows.
        # The rows also carry the number, not the key, through the sort (narrower); it maps back to the key below.
        numbered = (func.unnest(bindparam(None, keys, type_=ARRAY(String)))
                    .table_valued("test_key", with_ordinality="number").render_derived(name="numbered_keys"))
        sequence_key = numbered.c.number
        attempts = (select(RunResult.run_id, sequence_key.label("test_key"), RunResult.status, RunResult.id)
                    .join(Run, Run.id == RunResult.run_id)
                    .join(numbered, numbered.c.test_key == RunResult.test_key).where(*filters))
    else:
        sequence_key = RunResult.test_key
        attempts = (select(RunResult.run_id, RunResult.test_key, RunResult.status, RunResult.id)
                    .join(Run, Run.id == RunResult.run_id).where(*filters))
    order = {"partition_by": (sequence_key, Run.branch), "order_by": (Run.started_at, RunResult.run_id, RunResult.id)}
    ranked = attempts.add_columns(
        func.lag(RunResult.status).over(**order).label("status_before"),
        func.lead(RunResult.status).over(**order).label("status_after"),
        func.lag(RunResult.run_id).over(**order).label("run_before"),
        func.lead(RunResult.run_id).over(**order).label("run_after"),
        func.lead(RunResult.run_id, 2).over(**order).label("run_after_2"),
    ).subquery()
    c = ranked.c
    rows = db.execute(
        select(c.run_id, c.test_key, c.status, c.id, c.run_after)
        .where(or_(c.run_after.is_(None), c.run_after != c.run_id),           # the run's last attempt
               or_(c.status.in_(FAILING), c.status_before.in_(FAILING), c.status_after.in_(FAILING),
                   c.run_before == c.run_id,     # this run was retried: the row before is not the previous outcome
                   c.run_after == c.run_after_2))  # the next run was: the row after is not the next outcome
    ).all()
    # A failing outcome with nothing after it ends its sequence: its headline is shown
    headlines = _headlines(db, [row_id for _, _, status, row_id, after in rows
                                if with_headlines and after is None and status in FAILING])
    out = []
    for run_id, key, status, row_id, _ in rows:
        if numbered_rows:
            key = keys[key - 1]  # WITH ORDINALITY counts from 1
        run = by_id[run_id]
        passed = status == "passed"
        out.append(Outcome(key, run.branch, run_id, run.started_at, passed, None if passed else headlines.get(row_id)))
    return out


def _headlines(db: Session, result_ids: list) -> Dict[int, Optional[str]]:
    if not result_ids:
        return {}
    rows = db.execute(
        select(RunResult.id, func.substr(RunResult.message, 1, MESSAGE_PREFIX))
        .where(in_list(db, RunResult.id, result_ids, Integer))
    ).all()
    return {result_id: headline(message) for result_id, message in rows}


def _tests_executed(db: Session, scope: Scope, counted: List[ScopedRun], context: Context) -> List[int]:
    """Distinct tests with a non-skipped result per bucket of the period: one count per bucket."""
    per_bucket: List[list] = [[] for _ in context.starts]
    for run in counted:
        index = _bucket_of(scope, context, run)
        if index is not None:
            per_bucket[index].append(run.id)
    out = []
    for ids in per_bucket:
        if not ids:
            out.append(0)
            continue
        executed = (
            select(RunResult.test_key).distinct()   # hashed; count(DISTINCT) would sort every row of the bucket
            .where(in_list(db, RunResult.run_id, ids, Integer), RunResult.status != "skipped", *key_filter(db, scope))
        ).subquery()
        out.append(int(db.execute(select(func.count()).select_from(executed)).scalar() or 0))
    return out


def _serialise(item: dict, identity: Dict[str, tuple]) -> dict:
    suite, class_name, name = identity[item["test_key"]]
    out = {k: (iso(v) if isinstance(v, datetime) else v) for k, v in item.items()}
    out.update(suite=suite, class_name=class_name, name=name)
    return out


def regressions(db: Session, scope: Scope, runs: List[ScopedRun], context: Context) -> dict:
    counted = [r for r in runs if r.id in context.counted]
    by_id = {r.id: r for r in counted}
    ids = list(by_id)
    identity = _candidates(db, scope, ids) if ids else {}
    sequences = build_sequences(_outcomes(db, ids, sorted(identity), by_id))
    lists = classify_streaks(sequences, scope.period.start, scope.previous.start)

    def capped(name: str, cap: int) -> dict:
        items = lists[name]
        return {"total": len(items), "items": [_serialise(i, identity) for i in items[:cap]]}

    zone = scope.period.zone
    flips, flaky = flips_by_bucket(
        sequences, scope.period.start,
        lambda moment: bucket_index(local_day(moment, zone), context.starts, context.bucket), len(context.starts))
    executed = _tests_executed(db, scope, counted, context)
    return {
        "newly_failing": capped("newly_failing", MAX_NEWLY),
        "fixed": capped("fixed", MAX_FIXED),
        "longest_failing": capped("longest_failing", MAX_LONGEST),
        "time_to_fix": lists["time_to_fix"],
        "flakiness": [{"date": start.isoformat(), "tests_executed": executed[i], "flaky_tests": len(flaky[i]),
                       "flips": flips[i]} for i, start in enumerate(context.starts)],
    }


SECTION_BUILDERS["regressions"] = regressions


TESTS_COLUMNS = ["test_key", "executions", "passed", "failed", "errored", "skipped", "flips", "pairs",
                 "duration_ms_sum", "last_status"]
TESTS_ROW_CAP = 50_000
LAST_STATUS_FIRST_BATCH = 16  # runs; each later batch doubles


def _last_status(db: Session, current: Dict[int, ScopedRun], keys: list) -> Dict[str, str]:
    """Each test's newest result in the period (run start, run id, then the last attempt), skipped included.

    The runs are read newest first in doubling batches, each asked only for the tests not found yet: no window
    over every result of the period (a sort of millions of rows), and usually only the newest runs are read. The
    keys come from the scoped rows, so the test_keys filter needs no repeating."""
    newest = sorted(current.values(), key=lambda r: (r.started_at, r.id), reverse=True)
    wanted = set(keys)
    out: Dict[str, str] = {}
    start, size = 0, LAST_STATUS_FIRST_BATCH
    while wanted and start < len(newest):
        rank = {r.id: position for position, r in enumerate(newest[start:start + size])}  # 0 is the newest
        start, size = start + size, size * 2
        best: Dict[str, tuple] = {}
        for key, run_id, row_id, status in db.execute(
            select(RunResult.test_key, RunResult.run_id, RunResult.id, RunResult.status)
            .where(in_list(db, RunResult.run_id, list(rank), Integer), in_list(db, RunResult.test_key, sorted(wanted)))
        ).all():
            order = (rank[run_id], -row_id)
            if key not in best or order < best[key][0]:
                best[key] = (order, status)
        for key, (_, status) in best.items():
            out[key] = status
        wanted -= best.keys()
    return out


def _per_branch(db: Session, scope: Scope, ids: list) -> list:
    """Per (test, branch): executions, the four counts and the summed duration, in one pass over the period."""
    return db.execute(
        select(RunResult.test_key, Run.branch, func.count(RunResult.id), _count("passed"), _count("failed"),
               _count("errored"), _count("skipped"), func.sum(RunResult.duration_ms))
        .join(Run, Run.id == RunResult.run_id)
        .where(in_list(db, RunResult.run_id, ids, Integer), *key_filter(db, scope))
        .group_by(RunResult.test_key, Run.branch)
    ).all()


def _repeated_attempts(db: Session, scope: Scope, ids: list) -> Dict[tuple, int]:
    """Per (test, branch): the non-skipped rows beyond the first of a test in one run (retries), so that
    non-skipped rows minus these is the number of runs with an outcome. First the runs with a repeated test (per
    run, rows against distinct tests: a small sort per run, by byte order since only equality matters), then
    the extra rows in those runs only."""
    key = RunResult.test_key.collate("C") if db.get_bind().dialect.name == "postgresql" else RunResult.test_key
    retried = db.execute(
        select(RunResult.run_id)
        .where(in_list(db, RunResult.run_id, ids, Integer), RunResult.status != "skipped", *key_filter(db, scope))
        .group_by(RunResult.run_id)
        .having(func.count(RunResult.id) > func.count(distinct(key)))
    ).scalars().all()
    if not retried:
        return {}
    rows = db.execute(
        select(RunResult.test_key, Run.branch, func.count(RunResult.id) - func.count(distinct(RunResult.run_id)))
        .join(Run, Run.id == RunResult.run_id)
        .where(in_list(db, RunResult.run_id, list(retried), Integer), RunResult.status != "skipped",
               *key_filter(db, scope))
        .group_by(RunResult.test_key, Run.branch)
    ).all()
    return {(test, branch): int(extra) for test, branch, extra in rows if extra}


def tests_section(db: Session, scope: Scope, runs: List[ScopedRun], context: Context) -> dict:
    """One row per test executed in scope in the period, columnar (a key in every object would double the payload).

    `pairs` is the sum over branches of (non-skipped outcomes - 1): the denominator of a flip rate. The counts
    come per (test, branch) in one pass; outcomes are the non-skipped rows less the repeated attempts. No
    count(DISTINCT) over the period: it sorts every row by a 64-character key."""
    current = {r.id: r for r in runs if r.current and r.id in context.counted}
    if not current:
        return {"columns": TESTS_COLUMNS, "rows": [], "truncated": False}
    ids = list(current)
    totals: Dict[str, List[int]] = {}       # executions, passed, failed, errored, skipped, duration
    outcomes: Dict[tuple, int] = {}
    for key, branch, n, p, f, e, s, d in _per_branch(db, scope, ids):
        row = totals.setdefault(key, [0, 0, 0, 0, 0, 0])
        for i, value in enumerate((n, p, f, e, s, d)):
            row[i] += int(value or 0)
        outcomes[(key, branch)] = int(n) - int(s or 0)
    for sequence, extra in _repeated_attempts(db, scope, ids).items():
        outcomes[sequence] -= extra
    pairs: Dict[str, int] = {}
    for (key, _), count in outcomes.items():
        pairs[key] = pairs.get(key, 0) + max(count - 1, 0)
    # Most failing first, then by key (lower-case hex: byte order is the database's order)
    ordered = sorted(totals.items(), key=lambda item: (-(item[1][2] + item[1][3]), item[0]))
    truncated = len(ordered) > TESTS_ROW_CAP
    ordered = ordered[:TESTS_ROW_CAP]
    last = _last_status(db, current, [key for key, _ in ordered])
    # Only a test with a failure can flip: the others have 0, so their sequences are never read
    failing = sorted(key for key, (_, _, failed, errored, _, _) in ordered if failed + errored > 0)
    flips = count_flips(build_sequences(_outcomes(db, ids, failing, current)))
    rows = [[key, n, p, f, e, s, flips.get(key, 0), pairs.get(key, 0), d, last.get(key)]
            for key, (n, p, f, e, s, d) in ordered]
    if not truncated:
        rows.sort(key=lambda row: row[0])
    return {"columns": TESTS_COLUMNS, "rows": rows, "truncated": truncated}


SECTION_BUILDERS["tests"] = tests_section


def duration_section(db: Session, scope: Scope, runs: List[ScopedRun], context: Context) -> dict:
    """Without test_keys: each run's wall time. With them: per run, the summed duration of the in-scope results --
    time in the selected tests, not wall time, since shards and workers run in parallel."""
    counted = [r for r in runs if r.id in context.counted]
    sums = run_counts(db, scope, counted) if scope.keys is not None else None

    def value(run: ScopedRun) -> int:
        return sums[run.id].duration_ms if sums is not None else run.duration_ms

    per_bucket: List[List[int]] = [[] for _ in context.starts]
    previous: List[int] = []
    for run in counted:
        if not run.current:
            previous.append(value(run))
            continue
        index = _bucket_of(scope, context, run)
        if index is not None:
            per_bucket[index].append(value(run))
    return {
        "basis": "run_wall_time" if scope.keys is None else "test_time",
        "buckets": [{"date": start.isoformat(), "runs": len(v), "avg_ms": mean(v), "p50_ms": percentile(v, 0.5),
                     "p90_ms": percentile(v, 0.9), "max_ms": max(v) if v else None}
                    for start, v in zip(context.starts, per_bucket)],
        "previous": {"runs": len(previous), "avg_ms": mean(previous), "p50_ms": percentile(previous, 0.5),
                     "p90_ms": percentile(previous, 0.9)} if previous else None,
    }


SECTION_BUILDERS["duration"] = duration_section
