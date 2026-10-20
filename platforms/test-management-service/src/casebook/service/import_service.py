"""Gherkin import against the database (ADR-023): load, plan, apply in one transaction."""
import hashlib
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.casebook.gherkin_import.parse import parse_feature
from src.casebook.gherkin_import.plan import Existing, Plan, build_plan, link_is_import_owned
from src.casebook.models import Case, CaseLabel, FeatureFile
from src.casebook.repo_suites import sync as suite_sync

PATH_LENGTH = 500
DRIVE = re.compile(r"^[A-Za-z]:")


class ImportConflict(Exception):
    """Another import into the same project committed first."""


def normalise_path(path: str) -> str:
    slashed = path.replace("\\", "/")
    # Empty and "." segments name the same file: "tests//a.feature" and "./tests/./a.feature" are "tests/a.feature"
    clean = "/".join(part for part in slashed.split("/") if part not in ("", "."))
    if (not clean or slashed.startswith("/") or DRIVE.match(clean) or ".." in clean.split("/")
            or len(clean) > PATH_LENGTH):
        raise ValueError(f"path not allowed: {path!r} (relative to the repository root, no '..')")
    return clean


def load_existing(db: Session, project_id: int) -> List[Existing]:
    # Case.labels is lazy="selectin": the labels of all these rows load in one extra query, not one per case
    rows = db.query(Case).filter(Case.project_id == project_id, Case.source_key.isnot(None)).all()
    return [
        Existing(id=r.id, number=r.number, source_key=r.source_key, source_path=r.source_path or "",
                 status=r.status, title=r.title, gherkin=r.gherkin or "",
                 labels=tuple(sorted(l.label for l in r.labels)), priority=r.priority,
                 automated_test_key=r.automated_test_key, automated_name=r.automated_name, feature_name=r.feature_name,
                 scenario_name=r.scenario_name, scenario_line=r.scenario_line)
        for r in rows
    ]


def plan_import(db: Session, project_id: int, files: List[Tuple[str, str]], full: bool) -> Plan:
    parsed = [parse_feature(path, content) for path, content in files]
    plan = build_plan(parsed, load_existing(db, project_id), full)
    raw = dict(files)
    plan.sources = [(f.path, f.feature_name[:500], raw[f.path]) for f in parsed if not f.errors]
    return plan


def store_sources(db: Session, project_id: int, plan: Plan, now: datetime) -> None:
    """Keep the raw text of every file that parsed (upsert by path). A full import also drops the stored
    files that are no longer in the folder: their cases were archived by the same plan. Not committed here."""
    kept = {row.path: row for row in db.query(FeatureFile).filter(
        FeatureFile.project_id == project_id, FeatureFile.path.in_([p for p, _, _ in plan.sources])).all()}
    for path, feature_name, content in plan.sources:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        row = kept.get(path)
        if row is None:
            db.add(FeatureFile(project_id=project_id, path=path, feature_name=feature_name, content=content,
                               content_sha256=digest, imported_at=now))
        elif row.content_sha256 != digest or row.feature_name != feature_name:
            row.feature_name, row.content, row.content_sha256, row.imported_at = feature_name, content, digest, now
    if plan.full:
        stale = db.query(FeatureFile).filter(FeatureFile.project_id == project_id)
        if plan.uploaded:
            stale = stale.filter(FeatureFile.path.notin_(plan.uploaded))
        stale.delete(synchronize_session=False)


def _content(row: Case, scenario) -> None:
    """Call before row.source_path is overwritten: whether the link is import-owned depends on the old path."""
    if link_is_import_owned(row.automated_test_key, row.automated_name, scenario.feature_name, row.source_path or ""):
        row.automated_test_key, row.automated_name = scenario.test_key, scenario.test_name[:1500]
    row.title = scenario.title
    row.gherkin = scenario.gherkin
    row.feature_name = scenario.feature_name[:500]
    row.scenario_name = scenario.name
    row.scenario_line = scenario.line
    wanted = set(scenario.labels)
    for existing in list(row.labels):
        if existing.label not in wanted:
            row.labels.remove(existing)
    have = {existing.label for existing in row.labels}
    for label in scenario.labels:
        if label not in have:
            row.labels.append(CaseLabel(label=label))
    if scenario.priority is not None:
        row.priority = scenario.priority


def apply_plan(db: Session, project_id: int, user_id: int, plan: Plan,
               suite_plan: Optional[suite_sync.SuitePlan] = None) -> Plan:
    now = datetime.now(timezone.utc)
    ids = [i.case_id for i in plan.items if i.case_id is not None]
    rows = {r.id: r for r in db.query(Case).filter(Case.id.in_(ids)).all()} if ids else {}
    next_number = (db.execute(select(func.max(Case.number)).where(Case.project_id == project_id)).scalar() or 0) + 1
    for item in plan.items:
        if item.action in ("unchanged", "skip"):
            continue
        if item.action == "create":
            s = item.parsed
            row = Case(project_id=project_id, number=next_number, title=s.title, description=s.description,
                       steps=[], gherkin=s.gherkin, feature_name=s.feature_name[:500], scenario_name=s.name, scenario_line=s.line, source_path=s.path, source_key=s.source_key,
                       # a synced case is ready to run as written; a case made in QEOS starts as draft
                       priority=s.priority or "medium", status="ready", created_by=user_id,
                       automated_test_key=s.test_key, automated_name=s.test_name[:1500],
                       labels=[CaseLabel(label=label) for label in s.labels])
            db.add(row)
            item.case_number = next_number
            next_number += 1
            continue
        row = rows[item.case_id]
        if item.action == "archive":
            row.status = "archived"
        else:  # update, move, reactivate
            _content(row, item.parsed)
            row.source_path, row.source_key = item.parsed.path, item.parsed.source_key
            if item.action == "reactivate":  # back in the repository: ready again, like a new synced case
                row.status = "ready"
        row.updated_by, row.updated_at = user_id, now
    store_sources(db, project_id, plan, now)
    try:
        db.flush()
        if suite_plan is not None:  # repository suites follow the cases in the same transaction
            suite_sync.apply_suites(db, project_id, user_id, suite_plan)
        else:  # no suite fields: the suites stay, their cases still follow
            suite_sync.recompute_members(db, project_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ImportConflict() from exc
    return plan
