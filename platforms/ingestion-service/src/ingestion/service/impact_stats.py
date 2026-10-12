"""Test impact statistics (spec 2026-10-12 §3.2): per project, over the runs with changed files of a window, how often
each test newly failed after a change to each path unit, and each test's base rate. Written by the impact-rollup job;
replay reads the same numbers for earlier windows.

Built inside the database. Python computes only what impact_rules.py defines: each run's path units (once per run)
and, through impact_history, which tests newly failed in it. Both are staged in temporary tables with one insert
each (on PostgreSQL one statement over unnest() of array parameters: 0.4 s where executemany took about 7 s for the
benchmark's 115,000 rows); the counting, the join with test_results and the writes are SQL: one INSERT ... SELECT per table, with
unit_hash = md5(path_unit) computed there (tests register md5 on SQLite)."""
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, List, Sequence, Set, Tuple

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, MetaData, String, Table, bindparam, case, delete, false, func, insert, literal,
    select, text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, aliased

from src.ingestion.analytics.impact_rules import change_units
from src.ingestion.analytics.impact_score import BaseStat, ImpactTest, PairStat
from src.ingestion.models import RunResult
from src.ingestion.models.impact import ImpactPair, ImpactTestBase
from src.ingestion.service import analytics_service
from src.ingestion.service.impact_history import change_runs, newly_failed_bulk
from src.ingestion.service.report_service import in_list

_STAGE = MetaData()
_RUNS = Table("impact_stage_runs", _STAGE, Column("run_id", Integer, nullable=False), prefixes=["TEMPORARY"])
_UNITS = Table("impact_stage_units", _STAGE, Column("run_id", Integer, nullable=False),
               Column("path_unit", String, nullable=False), prefixes=["TEMPORARY"])
_NEWLY = Table("impact_stage_newly", _STAGE, Column("run_id", Integer, nullable=False),
               Column("test_key", String(64), nullable=False), prefixes=["TEMPORARY"])


def _stage(db: Session, table: Table, columns: Sequence[list]) -> None:
    """Insert the rows given column by column (equal-length lists) into a staging table."""
    if not columns[0]:
        return
    if db.get_bind().dialect.name == "postgresql":
        arrays = [bindparam(f"c{i}", values, type_=ARRAY(column.type))
                  for i, (column, values) in enumerate(zip(table.columns, columns))]
        names = [c.name for c in table.columns]
        rows = func.unnest(*arrays).table_valued(*names).render_derived(name="staged")  # several arrays: FROM only
        db.execute(insert(table).from_select(names, select(*rows.columns)))
    else:  # SQLite (the tests)
        db.execute(insert(table), [dict(zip(table.columns.keys(), row)) for row in zip(*columns)])


@contextmanager
def _staged(db: Session, project_id: int, start: datetime, end: datetime, excluded: Set[str]) -> Iterator[None]:
    """The window's change runs, their path units and their new failures, in temporary tables for the block."""
    runs = change_runs(db, project_id, start, end)
    newly = newly_failed_bulk(db, runs, excluded)
    connection = db.connection()
    for table in _STAGE.sorted_tables:
        connection.execute(text(f"DROP TABLE IF EXISTS {table.name}"))  # a pass that died mid-way on this connection
        table.create(connection)
    _stage(db, _RUNS, [[run.id for run in runs]])
    units = [(run.id, unit) for run in runs for unit in sorted(change_units(run.paths))]
    _stage(db, _UNITS, [[run_id for run_id, _ in units], [unit for _, unit in units]])
    failed = [(run_id, key) for run_id, keys in sorted(newly.items()) for key in sorted(keys)]
    _stage(db, _NEWLY, [[run_id for run_id, _ in failed], [key for _, key in failed]])
    yield
    # Not in a finally: after an error the transaction is aborted and the caller's rollback removes the tables
    for table in reversed(_STAGE.sorted_tables):
        table.drop(connection, checkfirst=False)


def _pairs(project_id: int, computed_at: datetime):
    """(project_id, unit_hash, test_key, path_unit, changed_runs, new_failures, computed_at): pairs with at least one
    new failure."""
    changed = (select(_UNITS.c.path_unit, func.count().label("changed_runs"))
               .group_by(_UNITS.c.path_unit).subquery())
    counted = (select(_UNITS.c.path_unit, _NEWLY.c.test_key, func.count().label("new_failures"))
               .join(_NEWLY, _NEWLY.c.run_id == _UNITS.c.run_id)
               .group_by(_UNITS.c.path_unit, _NEWLY.c.test_key).subquery())
    return (
        select(literal(project_id, Integer).label("project_id"), func.md5(counted.c.path_unit).label("unit_hash"),
               counted.c.test_key, counted.c.path_unit, changed.c.changed_runs, counted.c.new_failures,
               literal(computed_at, DateTime(timezone=True)).label("computed_at"))
        .join(changed, changed.c.path_unit == counted.c.path_unit)
    )


def _bases(db: Session, project_id: int, flaky: Set[str], computed_at: datetime):
    """(project_id, test_key, runs, new_failures, flaky, suite, class_name, name, file, computed_at): every test with a
    non-skipped result in the window's change runs (plan Ruling 9). Names and file are those of the test's row in the
    newest such run (the highest run id).

    The counting carries only (test, run), hashed twice: on the benchmark's 2 million results 3.7 s, against 8.5 s for
    one count(DISTINCT) carrying the names (a 600-byte-wide sort to disk). The names are then read for one row per
    test, by primary key."""
    per_run = (
        select(RunResult.test_key, RunResult.run_id)
        .join(_RUNS, _RUNS.c.run_id == RunResult.run_id)
        .where(RunResult.status != "skipped")
        .group_by(RunResult.test_key, RunResult.run_id)
    ).subquery()
    counted = (select(per_run.c.test_key, func.count().label("runs"), func.max(per_run.c.run_id).label("newest"))
               .group_by(per_run.c.test_key)).subquery()
    newest_row = (select(func.max(RunResult.id))
                  .where(RunResult.test_key == counted.c.test_key, RunResult.run_id == counted.c.newest)
                  .scalar_subquery())
    tested = select(counted.c.test_key, counted.c.runs, newest_row.label("row_id")).subquery()
    named = aliased(RunResult)
    newly = select(_NEWLY.c.test_key, func.count().label("new_failures")).group_by(_NEWLY.c.test_key).subquery()
    flagged = in_list(db, tested.c.test_key, sorted(flaky)) if flaky else false()
    return (
        select(literal(project_id, Integer).label("project_id"), tested.c.test_key, tested.c.runs,
               func.coalesce(newly.c.new_failures, 0).label("new_failures"),
               case((flagged, literal(True, Boolean)), else_=literal(False, Boolean)).label("flaky"),
               named.suite, named.class_name, named.name, named.file,
               literal(computed_at, DateTime(timezone=True)).label("computed_at"))
        .select_from(tested)
        .join(named, named.id == tested.c.row_id)
        .outerjoin(newly, newly.c.test_key == tested.c.test_key)
    )


def build_statistics(db: Session, project_id: int, start: datetime, end: datetime, flaky: Set[str],
                     muted: Set[str]) -> Tuple[List[PairStat], List[BaseStat]]:
    """The statistics of a window, read back without writing (replay). Flaky and muted tests count no new failures
    (spec §3.1); flaky ones are flagged."""
    with _staged(db, project_id, start, end, flaky | muted):
        pair_rows = _pairs(project_id, end)
        base_rows = _bases(db, project_id, flaky, end)
        pairs = db.execute(pair_rows.order_by(pair_rows.selected_columns.path_unit,
                                              pair_rows.selected_columns.test_key)).all()
        bases = db.execute(base_rows.order_by(base_rows.selected_columns.test_key)).all()
    return (
        [PairStat(row.path_unit, row.test_key, row.changed_runs, row.new_failures) for row in pairs],
        [BaseStat(ImpactTest(row.test_key, row.suite, row.class_name, row.name), row.runs, row.new_failures,
                  row.file, bool(row.flaky)) for row in bases],
    )


def rebuild_statistics(db: Session, project_id: int, start: datetime, end: datetime, flaky: Set[str], muted: Set[str],
                       computed_at: datetime) -> Tuple[int, int]:
    """Replace a project's rows in one transaction (readers see the old set or the new one, never half): one
    INSERT ... SELECT per table. Returns (pairs, tests) written. The same data gives the same rows."""
    with _staged(db, project_id, start, end, flaky | muted):
        db.execute(delete(ImpactPair).where(ImpactPair.project_id == project_id))
        db.execute(delete(ImpactTestBase).where(ImpactTestBase.project_id == project_id))
        pair_columns = ["project_id", "unit_hash", "test_key", "path_unit", "changed_runs", "new_failures",
                        "computed_at"]
        pairs = db.execute(insert(ImpactPair).from_select(pair_columns, _pairs(project_id, computed_at))).rowcount
        base_columns = ["project_id", "test_key", "runs", "new_failures", "flaky", "suite", "class_name", "name",
                        "file", "computed_at"]
        tests = db.execute(
            insert(ImpactTestBase).from_select(base_columns, _bases(db, project_id, flaky, computed_at))).rowcount
    db.commit()
    return pairs, tests


def live_excluded(db: Session, project_id: int) -> Set[str]:
    """What an upload's outcome leaves out: tests the last rollup flagged flaky, and tests muted now."""
    flagged = {key for (key,) in db.execute(
        select(ImpactTestBase.test_key).where(ImpactTestBase.project_id == project_id, ImpactTestBase.flaky.is_(True)))}
    return flagged | analytics_service.muted_keys(db, project_id)
