from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from src.casebook.api.deps import EDIT_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.casebook.schemas.suite import SuiteCasesIn, SuiteCreate, SuiteDetail, SuiteOut, SuiteUpdate
from src.casebook.service import suite_service

router = APIRouter()  # mounted at /projects/{project_id}/suites

DUPLICATE = "A suite with this name already exists in the project"
READ_ONLY = {"code": "repository_suite", "message": "Managed by the repository: change the workflow instead."}


def _suite_or_404(db: Session, access: ProjectAccess, suite_id: int):
    row = suite_service.get_suite(db, access.project_id, suite_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suite not found")
    return row


def _manual_suite_or_409(db: Session, access: ProjectAccess, suite_id: int):
    row = _suite_or_404(db, access, suite_id)
    try:
        suite_service.ensure_manual(row)
    except suite_service.RepositorySuite:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=READ_ONLY)
    return row


@router.get("", response_model=list[SuiteOut])
def list_suites(
    search: Optional[str] = Query(None, min_length=1, max_length=200, pattern=r"^[^\x00]*$"),
    # "me": the caller's own suites (the Overview's My suites widget); no other value is accepted
    created_by: Optional[Literal["me"]] = Query(None),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    mine = access.user_id if created_by == "me" else None
    rows = suite_service.list_suites(db, access.project_id, search, created_by=mine)
    return [suite_service.out(db, row) for row in rows]


@router.post("", response_model=SuiteOut, status_code=status.HTTP_201_CREATED)
def create_suite(
    payload: SuiteCreate,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    try:
        row = suite_service.create_suite(db, access.project_id, access.user_id, payload.name, payload.description)
    except suite_service.DuplicateName:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE)
    return suite_service.out(db, row)


@router.get("/{suite_id}", response_model=SuiteDetail)
def get_suite(
    suite_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return suite_service.out(db, _suite_or_404(db, access, suite_id), with_cases=True)


@router.patch("/{suite_id}", response_model=SuiteOut)
def update_suite(
    suite_id: int,
    payload: SuiteUpdate,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    row = _manual_suite_or_409(db, access, suite_id)
    try:
        row = suite_service.update_suite(db, row, payload.model_dump(exclude_unset=True))
    except suite_service.DuplicateName:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE)
    return suite_service.out(db, row)


@router.put("/{suite_id}/cases", response_model=SuiteDetail)
def set_suite_cases(
    suite_id: int,
    payload: SuiteCasesIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    row = _manual_suite_or_409(db, access, suite_id)
    try:
        row = suite_service.set_cases(db, row, payload.cases)
    except suite_service.BadCaseList as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return suite_service.out(db, row, with_cases=True)


@router.delete("/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_suite(
    suite_id: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    suite_service.delete_suite(db, _manual_suite_or_409(db, access, suite_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
