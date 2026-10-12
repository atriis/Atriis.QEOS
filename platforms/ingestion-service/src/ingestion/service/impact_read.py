"""Reading test impact (spec 2026-10-12 §3.5, §9; plan Rulings 17, 19): a run's stored suggestion and outcome, and the
accuracy figure over the runs whose outcome is recorded, with the average suggestion size beside it (suggesting every
test would catch everything; the average shows it)."""
from datetime import datetime
from typing import List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ingestion.analytics.trends import as_utc
from src.ingestion.models import Run, RunChangedFile
from src.ingestion.models.impact import RunImpact

MAX_MISSES = 50


def run_impact(db: Session, run: Run) -> dict:
    paths = [path for (path,) in db.execute(
        select(RunChangedFile.path).where(RunChangedFile.run_id == run.id).order_by(RunChangedFile.id))]
    if not paths:
        return {"run_id": run.id, "state": "no_change_data", "changed_paths": []}
    row = db.get(RunImpact, run.id)
    if row is None:  # uploaded before test impact, or scoring failed (plan Ruling 17)
        return {"run_id": run.id, "state": "not_scored", "changed_paths": paths}
    outcome = None
    if row.evaluated_at is not None:
        outcome = {"evaluated_at": as_utc(row.evaluated_at), "caught": row.caught or [], "missed": row.missed or []}
    return {"run_id": run.id, "state": row.suggested["state"], "changed_paths": paths, "replayed": row.replayed,
            "scored_at": as_utc(row.scored_at), "suggestion": {**row.suggested, "model_version": row.model_version},
            "outcome": outcome}


def _suggested_count(db: Session):
    """The number of tests in a stored suggestion, counted in the database (the suggestions are not read)."""
    if db.get_bind().dialect.name == "postgresql":
        return func.json_array_length(RunImpact.suggested.op("->")("tests"))
    return func.json_array_length(RunImpact.suggested, "$.tests")  # SQLite (the tests)


def accuracy(db: Session, project_id: int, since: datetime, days: int) -> dict:
    """caught / (caught + missed) over the runs started since `since` whose outcome is recorded, live and replayed
    apart, with the suggested tests per such run; the misses newest run first, at most MAX_MISSES."""
    rows = db.execute(
        select(RunImpact.run_id, RunImpact.replayed, RunImpact.caught, RunImpact.missed, _suggested_count(db),
               Run.started_at, Run.branch)
        .join(Run, Run.id == RunImpact.run_id)
        .where(Run.project_id == project_id, Run.started_at >= since, RunImpact.evaluated_at.is_not(None))
        .order_by(Run.started_at.desc(), Run.id.desc())
    ).all()
    parts = {flag: {"runs": 0, "caught": 0, "missed": 0, "suggested": 0} for flag in (False, True)}
    misses: List[dict] = []
    for run_id, replayed, caught, missed, suggested, started_at, branch in rows:
        part = parts[bool(replayed)]
        part["runs"] += 1
        part["caught"] += len(caught or [])
        part["missed"] += len(missed or [])
        part["suggested"] += suggested or 0
        if len(misses) < MAX_MISSES:
            misses.extend({**test, "run_id": run_id, "started_at": as_utc(started_at), "branch": branch,
                           "replayed": bool(replayed)} for test in (missed or [])[:MAX_MISSES - len(misses)])
    total = {key: parts[False][key] + parts[True][key] for key in parts[False]}
    return {"days": days, "caught": total["caught"], "missed": total["missed"],
            "rate": round(total["caught"] / (total["caught"] + total["missed"]), 4)
            if total["caught"] + total["missed"] else None,
            "avg_suggested": round(total["suggested"] / total["runs"], 1) if total["runs"] else None,
            "includes_replayed": parts[True]["runs"] > 0, "live": parts[False], "replayed": parts[True],
            "misses": misses, "misses_total": total["missed"]}
