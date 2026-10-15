"""Log values (ADR-032): rows from a result's stored (masked) log, written at upload, by the re-scan and by the
re-mask job."""
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from src.ingestion.models.log_pattern import LogPattern, LogValue
from src.ingestion.models.run import RunResult
from src.ingestion.utils import log_values
from src.ingestion.utils.log_values import CompiledLogPattern


def rows_for(result_id: int, log: Optional[str], patterns: Sequence[CompiledLogPattern]) -> List[dict]:
    """The log_values rows of one result's log."""
    return [{"result_id": result_id, "pattern_id": pattern_id, "position": position, "value": value}
            for pattern_id, position, value in log_values.extract(log, patterns)]


def replace_values(db: Session, items: Sequence[Tuple[int, Optional[str]]],
                   patterns: Sequence[CompiledLogPattern]) -> int:
    """These results' values for these patterns, read again from their logs: the old rows go and the new ones come
    in, in the caller's transaction (it commits). Running it twice leaves the same rows."""
    result_ids = [result_id for result_id, _ in items]
    if not result_ids or not patterns:
        return 0
    db.query(LogValue).filter(
        LogValue.result_id.in_(result_ids), LogValue.pattern_id.in_([p.id for p in patterns])
    ).delete(synchronize_session=False)
    rows = [row for result_id, log in items for row in rows_for(result_id, log, patterns)]
    if rows:
        db.execute(insert(LogValue), rows)
    return len(rows)


def _by_name(entries: List[dict]) -> List[dict]:
    """Patterns in code-point name order, whatever the database's collation."""
    return sorted(entries, key=lambda entry: entry["name"])


def values_by_result(db: Session, result_ids: Iterable[int]) -> Dict[int, List[dict]]:
    """Each result's values per pattern, with the pattern's link template (latest-results)."""
    ids = list(result_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(LogValue.result_id, LogPattern.name, LogPattern.link_template, LogValue.value)
        .join(LogPattern, LogPattern.id == LogValue.pattern_id)
        .where(LogValue.result_id.in_(ids))
        .order_by(LogValue.result_id, LogPattern.name, LogValue.position)
    ).all()
    out: Dict[int, List[dict]] = {}
    for result_id, name, template, value in rows:
        entries = out.setdefault(result_id, [])
        if not entries or entries[-1]["name"] != name:
            entries.append({"name": name, "values": [], "link_template": template})
        entries[-1]["values"].append(value)
    return {result_id: _by_name(entries) for result_id, entries in out.items()}


def values_by_test_run(db: Session, keys: Iterable[str], run_ids: Iterable[int]) -> Dict[Tuple[str, int], List[dict]]:
    """Each (test, run)'s values per pattern (run-strip): a re-run's results merged, first appearance first,
    duplicates removed, at most 20 per pattern."""
    keys, run_ids = list(keys), list(run_ids)
    if not keys or not run_ids:
        return {}
    rows = db.execute(
        select(RunResult.test_key, RunResult.run_id, LogPattern.name, LogValue.value)
        .join(LogValue, LogValue.result_id == RunResult.id)
        .join(LogPattern, LogPattern.id == LogValue.pattern_id)
        .where(RunResult.run_id.in_(run_ids), RunResult.test_key.in_(keys))
        .order_by(RunResult.test_key, RunResult.run_id, LogPattern.name, RunResult.id, LogValue.position)
    ).all()
    out: Dict[Tuple[str, int], List[dict]] = {}
    for key, run_id, name, value in rows:
        entries = out.setdefault((key, run_id), [])
        if not entries or entries[-1]["name"] != name:
            entries.append({"name": name, "values": []})
        values = entries[-1]["values"]
        if value not in values and len(values) < log_values.MAX_VALUES_PER_PATTERN:
            values.append(value)
    return {pair: _by_name(entries) for pair, entries in out.items()}
