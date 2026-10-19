"""Cases (docs/superpowers/specs/2026-10-06-test-management-design.md)."""
import re
from collections import Counter
from datetime import datetime, timezone
from typing import List, Literal, Optional

from sqlalchemy import case as sql_case, exists, false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.casebook.models import Case, CaseLabel, Suite, SuiteCase


def case_key(number: int) -> str:
    return f"TC-{number}"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


CASE_KEY = re.compile(r"^\s*(?:TC-?)?(\d{1,9})\s*$", re.IGNORECASE)


def out(row: Case, suites: Optional[list] = None) -> dict:
    return {
        "number": row.number, "key": case_key(row.number), "title": row.title, "description": row.description,
        "steps": row.steps or [], "labels": [label.label for label in row.labels], "priority": row.priority,
        "status": row.status, "automated_test_key": row.automated_test_key, "automated_name": row.automated_name,
        "created_by": row.created_by, "created_at": row.created_at, "updated_by": row.updated_by,
        "updated_at": row.updated_at, "source_path": row.source_path, "gherkin": row.gherkin,
        "feature_name": row.feature_name,
        "suites": suites or [],
    }


def get_case(db: Session, project_id: int, number: int) -> Optional[Case]:
    return db.query(Case).filter(Case.project_id == project_id, Case.number == number).one_or_none()


def suites_of(db: Session, case: Case) -> List[dict]:
    rows = (
        db.query(Suite.id, Suite.name).join(SuiteCase, SuiteCase.suite_id == Suite.id)
        .filter(SuiteCase.case_id == case.id).order_by(Suite.name).all()
    )
    return [{"id": r.id, "name": r.name} for r in rows]


def _next_number(db: Session, project_id: int) -> int:
    current = db.execute(select(func.max(Case.number)).where(Case.project_id == project_id)).scalar()
    return (current or 0) + 1


def create_case(db: Session, project_id: int, user_id: int, data: dict) -> Case:
    labels = data.pop("labels", [])
    steps = [dict(s) for s in data.pop("steps", [])]
    if not data.get("automated_test_key"):
        data["automated_test_key"], data["automated_name"] = None, None
    # Two people saving at once may pick the same number; the unique constraint catches it
    for attempt in range(3):
        row = Case(project_id=project_id, number=_next_number(db, project_id), steps=steps,
                   created_by=user_id, labels=[CaseLabel(label=label) for label in labels], **data)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise
            continue
        db.refresh(row)
        return row
    raise RuntimeError("unreachable")


REPOSITORY_FIELDS = ("title", "steps", "labels", "gherkin")


def repository_owned(row: Case, changes: dict) -> list:
    """Fields a PATCH may not change on an imported case: its .feature file owns them (ADR-023)."""
    if row.source_key is None:
        changes.pop("gherkin", None)
        return []
    return [f for f in REPOSITORY_FIELDS if f in changes]


def update_case(db: Session, row: Case, user_id: int, changes: dict) -> Case:
    if "labels" in changes:
        # Diff, not replace: replacing inserts a kept label before its old row is deleted (unique case_id, label)
        wanted = changes.pop("labels") or []
        for existing in list(row.labels):
            if existing.label not in wanted:
                row.labels.remove(existing)
        have = {existing.label for existing in row.labels}
        for label in wanted:
            if label not in have:
                row.labels.append(CaseLabel(label=label))
                have.add(label)
    if "steps" in changes:
        row.steps = [dict(s) for s in (changes.pop("steps") or [])]
    if "automated_test_key" in changes and not changes["automated_test_key"]:
        changes["automated_name"] = None
    for key in ("title", "priority", "status"):
        if key in changes and changes[key] is None:
            changes.pop(key)  # these cannot be emptied; null means "leave as it is"
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def _search_clause(search: str, search_in: str):
    """(filter, key_first ordering or None). scenario: title, Gherkin and TC key; feature: the Feature name
    or the file path; both: either."""
    pattern = f"%{_escape_like(search)}%"
    feature_match = or_(Case.feature_name.ilike(pattern, escape="\\"), Case.source_path.ilike(pattern, escape="\\"))
    if search_in == "feature":
        return feature_match, None
    text_match = or_(Case.title.ilike(pattern, escape="\\"), Case.gherkin.ilike(pattern, escape="\\"))
    key_first = None
    key = CASE_KEY.match(search)
    if key:  # "TC-12", "tc12" and "12" also find case 12, which then sorts first
        key_match = Case.number == int(key.group(1))
        text_match = or_(text_match, key_match)
        key_first = sql_case((key_match, 0), else_=1)
    return (or_(text_match, feature_match) if search_in == "both" else text_match), key_first


def filtered_cases(db: Session, project_id: int, *, search: Optional[str], labels: List[str],
                   status: Optional[str], priority: Optional[str], include_archived: bool,
                   origin: Optional[str] = None, folder: Optional[str] = None, linked: Optional[bool] = None,
                   feature: Optional[str] = None, ado: Optional[str] = None,
                   test_keys: Optional[List[str]] = None, keys_mode: str = "include", search_in: str = "scenario",
                   suite: Optional[Literal["none"]] = None):
    """The query behind GET /cases and GET /features, and the ordering a TC-key search wants (or None)."""
    query = db.query(Case).filter(Case.project_id == project_id)
    if status is not None:
        query = query.filter(Case.status == status)
    elif not include_archived:
        query = query.filter(Case.status != "archived")
    if priority is not None:
        query = query.filter(Case.priority == priority)
    if origin == "imported":
        query = query.filter(Case.source_key.isnot(None))
    elif origin == "manual":
        query = query.filter(Case.source_key.is_(None))
    key_first = None
    if search:
        clause, key_first = _search_clause(search, search_in)
        query = query.filter(clause)
    for label in {label.lower() for label in labels}:
        query = query.filter(exists().where(CaseLabel.case_id == Case.id, CaseLabel.label == label))
    if folder:
        query = query.filter(Case.source_path.like(f"{_escape_like(folder.rstrip('/'))}/%", escape="\\"))
    if linked is True:
        query = query.filter(Case.automated_test_key.isnot(None))
    elif linked is False:
        query = query.filter(Case.automated_test_key.is_(None))
    if feature is not None:
        query = query.filter(Case.feature_name == feature)
    if ado is not None:
        query = query.filter(exists().where(CaseLabel.case_id == Case.id, CaseLabel.label == f"ado-{ado}"))
    if suite == "none":  # imported, live cases that no repository suite holds (the manual-suite ones still show)
        query = query.filter(
            Case.source_key.isnot(None), Case.status != "archived",
            ~exists().where(SuiteCase.case_id == Case.id, Suite.id == SuiteCase.suite_id, Suite.origin == "repository"))
    if test_keys is not None:
        keys = list({k.lower() for k in test_keys})
        if keys_mode == "include":
            query = query.filter(Case.automated_test_key.in_(keys)) if keys else query.filter(false())
        elif keys:
            query = query.filter(or_(Case.automated_test_key.is_(None), Case.automated_test_key.notin_(keys)))
    return query, key_first


def list_cases(db: Session, project_id: int, *, limit: int, offset: int, **filters):
    query, key_first = filtered_cases(db, project_id, **filters)
    total = query.count()
    order = [key_first, Case.number] if key_first is not None else [Case.number]
    rows = query.order_by(*order).offset(offset).limit(limit).all()
    return total, rows


def label_counts(db: Session, project_id: int) -> List[dict]:
    rows = (
        db.query(CaseLabel.label, func.count(CaseLabel.id))
        .join(Case, Case.id == CaseLabel.case_id)
        .filter(Case.project_id == project_id, Case.status != "archived")
        .group_by(CaseLabel.label).order_by(CaseLabel.label).all()
    )
    return [{"label": label, "count": count} for label, count in rows]


def folder_counts(db: Session, project_id: int) -> List[dict]:
    """Every folder holding an active imported case, counting its subfolders too."""
    counts: Counter = Counter()
    rows = db.query(Case.source_path).filter(
        Case.project_id == project_id, Case.status != "archived", Case.source_path.isnot(None)).all()
    for (path,) in rows:
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            counts["/".join(parts[:i])] += 1
    return [{"path": p, "count": c} for p, c in sorted(counts.items())]


def feature_counts(db: Session, project_id: int) -> List[dict]:
    rows = (
        db.query(Case.feature_name, func.count(Case.id))
        .filter(Case.project_id == project_id, Case.status != "archived", Case.feature_name.isnot(None))
        .group_by(Case.feature_name).order_by(Case.feature_name).all()
    )
    return [{"feature": f, "count": c} for f, c in rows]
