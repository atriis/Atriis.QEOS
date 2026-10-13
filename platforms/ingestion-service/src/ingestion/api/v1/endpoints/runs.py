from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.ingestion.api.deps import (
    READ_ROLES, Caller, ProjectAccess, check_project_role, get_caller, get_db, require_project_role,
)
from src.ingestion.api.v1.endpoints.analytics import NO_NUL
from src.ingestion.models.run import CI_PROVIDERS, SCOPES
from src.ingestion.schemas.run import (
    ChangedFileOut, ComponentOut, FailureGroupsOut, ResultOut, RunComparison, RunDetail, RunOut, RunSummary,
)
from src.ingestion.schemas.impact import RunImpactOut
from src.ingestion.service import impact_read, run_service

project_router = APIRouter()  # mounted at /projects/{project_id}/runs
router = APIRouter()          # mounted at /runs


@project_router.get("", response_model=list[RunOut])
def list_runs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    branch: Optional[str] = Query(None, max_length=255, pattern=NO_NUL),
    branch_contains: Optional[str] = Query(None, max_length=255, pattern=NO_NUL),
    status_filter: Optional[Literal["failing", "passing"]] = Query(None, alias="status"),
    environment: Optional[str] = Query(None, max_length=100, pattern=NO_NUL),
    ci_provider: Optional[Literal[CI_PROVIDERS]] = Query(None),
    commit: Optional[str] = Query(None, pattern=r"^[0-9a-fA-F]{4,40}$"),
    pr: Optional[int] = Query(None, ge=1),
    author: Optional[str] = Query(None, max_length=255, pattern=NO_NUL),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    scope: Optional[Literal[SCOPES]] = Query(None),  # "full" hides runs of only the suggested tests
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    filters = run_service.RunFilters(
        branch=branch, branch_contains=branch_contains, status=status_filter, environment=environment, ci_provider=ci_provider,
        commit=commit, pr=pr, author=author, since=since, until=until, scope=scope,
    )
    return run_service.list_runs(db, access.project_id, limit, offset, filters)


@project_router.get("/{run_id}/summary", response_model=RunSummary)
def get_run_summary(
    run_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    run = run_service.get_run(db, run_id)
    # A run of another project is indistinguishable from a missing one
    if run is None or run.project_id != access.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return RunSummary.from_run(run)


@project_router.get("/{run_id}/impact", response_model=RunImpactOut)
def get_run_impact(
    run_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """The suggestion stored with the run and its outcome (spec 2026-10-12 §3.5)."""
    run = run_service.get_run(db, run_id)
    # A run of another project is indistinguishable from a missing one
    if run is None or run.project_id != access.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return impact_read.run_impact(db, run)


@router.get("/{run_id}", response_model=RunDetail)
def get_run(
    run_id: int,
    status_filter: Optional[Literal["passed", "failed", "skipped", "errored"]] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    run = run_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    # The project comes from the run row, never from the URL
    project_id = run.project_id
    # End the read-only transaction before the HTTP access check, so a slow
    # project-service never holds this connection out of the pool
    db.rollback()
    check_project_role(project_id, caller, READ_ROLES, "Run not found")
    run = run_service.get_run(db, run_id)
    held = run_service.quarantined_failures(db, run)
    results = run_service.list_results(db, run.id, status_filter)
    changes = run_service.list_changes(db, run.id)
    components = run_service.list_components(db, run.id)
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        **run_service.quarantine_counts(db, run, held),
        results=[
            ResultOut.model_validate(r).model_copy(
                update={"quarantined": r.status in ("failed", "errored") and r.test_key in held})
            for r in results
        ],
        changes=[ChangedFileOut.model_validate(f) for f in changes],
        components=[ComponentOut.model_validate(c) for c in components],
    )


@router.get("/{run_id}/failure-groups", response_model=FailureGroupsOut)
def get_failure_groups(
    run_id: int,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    run = run_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    project_id = run.project_id
    # As get_run: no connection held during the access check
    db.rollback()
    check_project_role(project_id, caller, READ_ROLES, "Run not found")
    return run_service.failure_groups(db, run_service.get_run(db, run_id))


@router.get("/{run_id}/compare/{base_id}", response_model=RunComparison)
def compare_runs(
    run_id: int,
    base_id: int,
    db: Session = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    head, base = run_service.get_run(db, run_id), run_service.get_run(db, base_id)
    # Two runs of different projects are never compared: one of them may be invisible to the caller
    if head is None or base is None or head.project_id != base.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    project_id = head.project_id
    db.rollback()
    check_project_role(project_id, caller, READ_ROLES, "Run not found")
    head, base = run_service.get_run(db, run_id), run_service.get_run(db, base_id)
    return run_service.compare_runs(db, base, head)
