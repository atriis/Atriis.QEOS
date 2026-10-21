"""Reading traces (ADR-037): a result's list, one trace's blob, and the per-result counts that ride on the run detail.
As for screenshots, every read goes through `_own`, so a row whose blob belongs to another project is invisible."""
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ingestion.models import Blob, ResultArtifact, Run, RunResult


def _own(project_id: int, *columns):
    """A select over the artifact rows whose blob is the project's own."""
    return (
        select(*columns).select_from(ResultArtifact)
        .join(Blob, Blob.id == ResultArtifact.blob_id)
        .where(Blob.project_id == project_id)
    )


def list_for_result(db: Session, project_id: int, result_id: int) -> List[dict]:
    rows = db.execute(
        _own(project_id, ResultArtifact.id, ResultArtifact.kind, ResultArtifact.name, Blob.bytes)
        .where(ResultArtifact.result_id == result_id)
        .order_by(ResultArtifact.position, ResultArtifact.id)
    ).mappings()
    return [dict(r) for r in rows]


def find_file(db: Session, project_id: int, artifact_id: int) -> Optional[Tuple[str, str, int]]:
    """(sha256, media_type, bytes) of an artifact of a result in the project's runs, else None: an id of another
    project is indistinguishable from a missing one."""
    row = db.execute(
        _own(project_id, Blob.sha256, Blob.media_type, Blob.bytes)
        .join(RunResult, RunResult.id == ResultArtifact.result_id)
        .join(Run, Run.id == RunResult.run_id)
        .where(ResultArtifact.id == artifact_id, Run.project_id == project_id)
    ).one_or_none()
    return None if row is None else (row[0], row[1], row[2])


def trace_counts_by_result(db: Session, project_id: int, result_ids: Sequence[int]) -> Dict[int, int]:
    if not result_ids:
        return {}
    rows = db.execute(
        _own(project_id, ResultArtifact.result_id, func.count(ResultArtifact.id))
        .where(ResultArtifact.result_id.in_(result_ids), ResultArtifact.kind == "trace")
        .group_by(ResultArtifact.result_id)
    )
    return {result_id: count for result_id, count in rows}
