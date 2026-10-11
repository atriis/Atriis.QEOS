"""Suites: a named, ordered list of a project's cases."""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.casebook.models import Case, Suite, SuiteCase
from src.casebook.service.case_service import _escape_like, case_key


class DuplicateName(Exception):
    pass


class BadCaseList(Exception):
    pass


def _count(db: Session, suite_id: int) -> int:
    return db.query(func.count(SuiteCase.id)).filter(SuiteCase.suite_id == suite_id).scalar()


def out(db: Session, row: Suite, with_cases: bool = False) -> dict:
    body = {"id": row.id, "name": row.name, "description": row.description, "case_count": _count(db, row.id),
            "created_at": row.created_at, "updated_at": row.updated_at}
    if with_cases:
        cases = (
            db.query(Case).join(SuiteCase, SuiteCase.case_id == Case.id)
            .filter(SuiteCase.suite_id == row.id).order_by(SuiteCase.position).all()
        )
        body["cases"] = [
            {"number": c.number, "key": case_key(c.number), "title": c.title, "status": c.status,
             "priority": c.priority, "labels": [label.label for label in c.labels],
             "automated_test_key": c.automated_test_key, "source_path": c.source_path}
            for c in cases
        ]
    return body


def list_suites(
    db: Session, project_id: int, search: Optional[str] = None, created_by: Optional[int] = None,
) -> List[Suite]:
    query = db.query(Suite).filter(Suite.project_id == project_id)
    if created_by is not None:
        query = query.filter(Suite.created_by == created_by)
    if search:
        query = query.filter(Suite.name.ilike(f"%{_escape_like(search)}%", escape="\\"))
    return query.order_by(Suite.name).all()


def get_suite(db: Session, project_id: int, suite_id: int) -> Optional[Suite]:
    return db.query(Suite).filter(Suite.project_id == project_id, Suite.id == suite_id).one_or_none()


def _commit_named(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateName()


def create_suite(db: Session, project_id: int, user_id: int, name: str, description: Optional[str]) -> Suite:
    row = Suite(project_id=project_id, name=name, description=description, created_by=user_id)
    db.add(row)
    _commit_named(db)
    db.refresh(row)
    return row


def update_suite(db: Session, row: Suite, changes: dict) -> Suite:
    if changes.get("name") is None:
        changes.pop("name", None)
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
    _commit_named(db)
    db.refresh(row)
    return row


def set_cases(db: Session, row: Suite, numbers: List[int]) -> Suite:
    if len(set(numbers)) != len(numbers):
        raise BadCaseList("A case can be in a suite once")
    found = {
        c.number: c.id for c in
        db.query(Case.number, Case.id).filter(Case.project_id == row.project_id, Case.number.in_(numbers)).all()
    } if numbers else {}
    missing = [n for n in numbers if n not in found]
    if missing:
        raise BadCaseList("No such case: " + ", ".join(case_key(n) for n in missing[:10]))
    db.query(SuiteCase).filter(SuiteCase.suite_id == row.id).delete()
    db.add_all(SuiteCase(suite_id=row.id, case_id=found[n], position=i) for i, n in enumerate(numbers))
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def delete_suite(db: Session, row: Suite) -> None:
    db.query(SuiteCase).filter(SuiteCase.suite_id == row.id).delete()
    db.delete(row)
    db.commit()
