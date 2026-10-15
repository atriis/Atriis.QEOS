"""Log values (ADR-032): rows from a result's stored (masked) log, written at upload, by the re-scan and by the
re-mask job."""
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import insert
from sqlalchemy.orm import Session

from src.ingestion.models.log_pattern import LogValue
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
