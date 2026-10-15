"""A project's log-value patterns (ADR-032): named like masking patterns, RE2, at most one capture group, an
optional https link template. No edit: delete and add again."""
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.ingestion.models.log_pattern import LogPattern, LogValue
from src.ingestion.utils import log_values
from src.ingestion.utils.log_values import CompiledLogPattern, LogPatternError


class DuplicatePattern(Exception):
    pass


def list_patterns(db: Session, project_id: int) -> List[LogPattern]:
    return db.query(LogPattern).filter_by(project_id=project_id).order_by(LogPattern.name).all()


def compiled_for(db: Session, project_id: int) -> List[CompiledLogPattern]:
    """The project's patterns, ready to apply. A stored pattern that no longer compiles (validated on the way in, so
    only a library change could do this) is skipped, not fatal."""
    patterns = []
    for row in list_patterns(db, project_id):
        try:
            patterns.append(CompiledLogPattern(row.id, row.name, log_values.compile_log_pattern(row.pattern)))
        except LogPatternError:
            continue
    return patterns


def validate(name: str, pattern: str) -> CompiledLogPattern:
    """LogPatternError with a reason and its field, for a 422."""
    return CompiledLogPattern(None, log_values.validate_name(name), log_values.compile_log_pattern(pattern))


def add_pattern(db: Session, project_id: int, name: str, pattern: str, link_template: Optional[str],
                user_id: int) -> LogPattern:
    validate(name, pattern)
    template = log_values.validate_link_template(link_template)
    limit = log_values.MAX_LOG_PATTERNS_PER_PROJECT
    if db.query(LogPattern).filter_by(project_id=project_id).count() >= limit:
        raise LogPatternError("limit", f"A project has at most {limit} log-value patterns")
    row = LogPattern(project_id=project_id, name=name, pattern=pattern, link_template=template,
                     created_by_user_id=user_id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicatePattern(f"This project already has a log-value pattern named {name}")
    db.refresh(row)
    return row


def delete_pattern(db: Session, project_id: int, pattern_id: int) -> bool:
    row = db.query(LogPattern).filter_by(project_id=project_id, id=pattern_id).first()
    if row is None:
        return False
    # Its values first, explicitly: SQLite (the tests) does not enforce ON DELETE CASCADE
    db.query(LogValue).filter(LogValue.pattern_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return True
