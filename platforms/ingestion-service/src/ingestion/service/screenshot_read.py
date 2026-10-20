"""Reading step screenshots (ADR-036): a result's list, one image's row, and the per-result summaries that ride on
the run detail and latest-results. Each summary is one grouped query for all the results asked about."""
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ingestion.models import Blob, ResultScreenshot, Run, RunResult


def list_for_result(db: Session, project_id: int, result_id: int) -> List[dict]:
    rows = db.execute(
        select(ResultScreenshot.id, ResultScreenshot.step_text, ResultScreenshot.step_line, ResultScreenshot.hook,
               Blob.media_type, Blob.bytes)
        .join(Blob, Blob.id == ResultScreenshot.blob_id)
        .where(ResultScreenshot.result_id == result_id, Blob.project_id == project_id)
        .order_by(ResultScreenshot.position, ResultScreenshot.id)
    ).mappings()
    return [dict(r) for r in rows]


def find_image(db: Session, project_id: int, screenshot_id: int) -> Optional[Tuple[str, str]]:
    """(sha256, media_type) of a screenshot of a result in the project's runs, else None: an id of another project
    is indistinguishable from a missing one."""
    row = db.execute(
        select(Blob.sha256, Blob.media_type)
        .join(ResultScreenshot, ResultScreenshot.blob_id == Blob.id)
        .join(RunResult, RunResult.id == ResultScreenshot.result_id)
        .join(Run, Run.id == RunResult.run_id)
        .where(ResultScreenshot.id == screenshot_id, Run.project_id == project_id, Blob.project_id == project_id)
    ).one_or_none()
    return None if row is None else (row[0], row[1])


def counts_by_result(db: Session, result_ids: Sequence[int]) -> Dict[int, int]:
    if not result_ids:
        return {}
    rows = db.execute(
        select(ResultScreenshot.result_id, func.count(ResultScreenshot.id))
        .where(ResultScreenshot.result_id.in_(result_ids)).group_by(ResultScreenshot.result_id)
    )
    return {result_id: count for result_id, count in rows}


def steps_by_result(db: Session, result_ids: Sequence[int]) -> Dict[int, List[dict]]:
    """Per result that has screenshots: its steps with the image count, in order of each step's first image."""
    if not result_ids:
        return {}
    first = func.min(ResultScreenshot.position)
    rows = db.execute(
        select(ResultScreenshot.result_id, ResultScreenshot.step_text, ResultScreenshot.step_line,
               ResultScreenshot.hook, func.count(ResultScreenshot.id).label("count"))
        .where(ResultScreenshot.result_id.in_(result_ids))
        .group_by(ResultScreenshot.result_id, ResultScreenshot.step_text, ResultScreenshot.step_line,
                  ResultScreenshot.hook)
        .order_by(ResultScreenshot.result_id, first)
    ).mappings()
    out: Dict[int, List[dict]] = {}
    for r in rows:
        out.setdefault(r["result_id"], []).append(
            {"step_text": r["step_text"], "step_line": r["step_line"], "hook": r["hook"], "count": r["count"]})
    return out
