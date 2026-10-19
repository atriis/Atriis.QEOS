"""A project's collection settings (ADR-030). No row: the defaults."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.ingestion.models import CollectionSettings


def get(db: Session, project_id: int) -> CollectionSettings:
    row = db.get(CollectionSettings, project_id)
    if row is None:  # not added to the session: reading never writes
        row = CollectionSettings(project_id=project_id, collect_manual=True, keep_screenshots=False, discarded_count=0)
    return row


def put(db: Session, project_id: int, collect_manual: Optional[bool], keep_screenshots: Optional[bool],
        user_id: int) -> CollectionSettings:
    row = db.get(CollectionSettings, project_id)
    if row is None:
        row = CollectionSettings(project_id=project_id, collect_manual=True, keep_screenshots=False, discarded_count=0)
        db.add(row)
    # None: the caller left the field out, keep what is stored
    if collect_manual is not None:
        row.collect_manual = collect_manual
    if keep_screenshots is not None:
        row.keep_screenshots = keep_screenshots
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = user_id
    db.commit()
    db.refresh(row)
    return row


def collects_manual(db: Session, project_id: int) -> bool:
    row = db.get(CollectionSettings, project_id)
    return True if row is None else bool(row.collect_manual)


def count_discard(db: Session, project_id: int) -> None:
    """One atomic UPDATE: parallel matrix uploads must not lose increments. A row exists whenever
    collection is off, because only put() can switch it off."""
    db.execute(
        update(CollectionSettings)
        .where(CollectionSettings.project_id == project_id)
        .values(discarded_count=CollectionSettings.discarded_count + 1,
                last_discarded_at=datetime.now(timezone.utc))
    )
    db.commit()
