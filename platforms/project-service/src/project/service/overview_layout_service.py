"""Overview layouts: one optional project default (user_id NULL) and one optional personal layout per user.

A save names the version it started from (plan Ruling 7): 0 creates, n updates only while the stored version
is n. Anything else raises StaleVersion with the stored row, or None when there is no row."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session

from src.project.models.overview_layout import OverviewLayout


class StaleVersion(Exception):
    def __init__(self, current: Optional[OverviewLayout]):
        super().__init__("the layout changed since this edit started")
        self.current = current


def _scope(db: Session, project_id: int, user_id: Optional[int]) -> Query:
    query = db.query(OverviewLayout).filter(OverviewLayout.project_id == project_id)
    if user_id is None:
        return query.filter(OverviewLayout.user_id.is_(None))
    return query.filter(OverviewLayout.user_id == user_id)


def get_row(db: Session, project_id: int, user_id: Optional[int]) -> Optional[OverviewLayout]:
    return _scope(db, project_id, user_id).one_or_none()


def save(db: Session, project_id: int, user_id: Optional[int], layout: dict, version: int, by: int) -> OverviewLayout:
    now = datetime.now(timezone.utc)
    if version == 0:
        existing = get_row(db, project_id, user_id)
        if existing is not None:
            raise StaleVersion(existing)
        db.add(OverviewLayout(
            project_id=project_id, user_id=user_id, layout=layout, version=1, updated_by=by, updated_at=now,
        ))
        try:
            db.commit()
        except IntegrityError:
            # Another request created it between the read and the insert
            db.rollback()
            raise StaleVersion(get_row(db, project_id, user_id))
    else:
        changed = _scope(db, project_id, user_id).filter(OverviewLayout.version == version).update(
            {
                OverviewLayout.layout: layout,
                OverviewLayout.version: OverviewLayout.version + 1,
                OverviewLayout.updated_by: by,
                OverviewLayout.updated_at: now,
            },
            synchronize_session=False,
        )
        db.commit()
        if changed == 0:
            raise StaleVersion(get_row(db, project_id, user_id))
    # commit() expired every loaded row, so this reads the stored values
    return get_row(db, project_id, user_id)


def delete(db: Session, project_id: int, user_id: Optional[int]) -> None:
    _scope(db, project_id, user_id).delete(synchronize_session=False)
    db.commit()
