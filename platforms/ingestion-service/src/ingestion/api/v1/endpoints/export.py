"""Download everything stored for a project as NDJSON: before deleting it, or for a legal or
audit request. One line per object, streamed, so memory stays flat however large the project.

    {"type": "export", "format": 1, "project_id": …, "exported_at": …}
    {"type": "run", …run fields, "changed_files": […], "components": […]}
    {"type": "result", "run_id": …, …result fields, "log", "log_values": [{"pattern", "value"}]}      (the run's results follow its run line)
"""
import json
from datetime import date, datetime, timezone
from typing import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, undefer

from src.ingestion.api.deps import ProjectAccess, get_db, require_project_role
from src.ingestion.models import LogPattern, LogValue, Run, RunChangedFile, RunComponent, RunResult

router = APIRouter()  # mounted at /projects/{project_id}/export

EXPORT_ROLES = ("owner", "admin")
FORMAT_VERSION = 1
# Bookkeeping that means nothing outside this service
_RUN_INTERNAL = {"request_hash", "idempotency_key", "api_key_id"}
_RESULT_INTERNAL = {"id"}


def _plain(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def _row(obj, skip=frozenset()) -> dict:
    return {c.name: _plain(getattr(obj, c.key)) for c in obj.__table__.columns if c.name not in skip}


def _line(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")


def _log_values_of_run(db: Session, run_id: int) -> dict:
    """Each result's log values (ADR-032), patterns by name, values in log order."""
    values: dict = {}
    rows = (
        db.query(LogValue.result_id, LogPattern.name, LogValue.value)
        .join(LogPattern, LogPattern.id == LogValue.pattern_id)
        .join(RunResult, RunResult.id == LogValue.result_id)
        .filter(RunResult.run_id == run_id)
        .order_by(LogValue.result_id, LogPattern.name, LogValue.position)
    )
    for result_id, name, value in rows:
        values.setdefault(result_id, []).append({"pattern": name, "value": value})
    return values


def _export(db: Session, project_id: int) -> Iterator[bytes]:
    yield _line({
        "type": "export", "format": FORMAT_VERSION, "project_id": project_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    })
    run_ids = [run_id for (run_id,) in db.query(Run.id).filter(Run.project_id == project_id).order_by(Run.id)]
    for run_id in run_ids:
        run = db.get(Run, run_id)
        record = {"type": "run", **_row(run, _RUN_INTERNAL)}
        record["changed_files"] = [
            {"path": f.path, "status": f.status, "additions": f.additions, "deletions": f.deletions}
            for f in db.query(RunChangedFile).filter_by(run_id=run_id).order_by(RunChangedFile.id)
        ]
        record["components"] = [
            {"name": c.name, "sha": c.sha}
            for c in db.query(RunComponent).filter_by(run_id=run_id).order_by(RunComponent.id)
        ]
        yield _line(record)
        values = _log_values_of_run(db, run_id)
        results = (db.query(RunResult).options(undefer(RunResult.log)).filter_by(run_id=run_id)
                   .order_by(RunResult.id).yield_per(1000))
        for result in results:
            yield _line({"type": "result", **_row(result, _RESULT_INTERNAL), "log_values": values.get(result.id, [])})
        db.expunge_all()  # keep the session from growing with every exported row


@router.get("")
def export_project(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EXPORT_ROLES)),
):
    filename = f"qeos-project-{access.project_id}-{datetime.now(timezone.utc):%Y%m%d}.ndjson"
    return StreamingResponse(
        _export(db, access.project_id),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
