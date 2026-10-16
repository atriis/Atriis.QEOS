"""Purge one project's test-management data (spec 2026-10-16): the purge job calls it once the project's
deletion window is over. Children first: SQLite (the tests) does not enforce ON DELETE CASCADE."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.casebook.models import Case, CaseLabel, CiTarget, CiTargetEvent, FeatureFile, RunRequest, Suite, SuiteCase


def purge_project(db: Session, project_id: int) -> dict:
    cases = select(Case.id).where(Case.project_id == project_id)
    suites = select(Suite.id).where(Suite.project_id == project_id)
    deleted = {
        "suite_cases": db.query(SuiteCase).filter(SuiteCase.suite_id.in_(suites)).delete(synchronize_session=False),
        "case_labels": db.query(CaseLabel).filter(CaseLabel.case_id.in_(cases)).delete(synchronize_session=False),
    }
    for model in (Suite, Case, FeatureFile, RunRequest, CiTargetEvent, CiTarget):
        deleted[model.__tablename__] = (
            db.query(model).filter(model.project_id == project_id).delete(synchronize_session=False))
    db.commit()
    return deleted
