from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.casebook.api.deps import EDIT_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.casebook.schemas.case import (
    CaseCreate, CaseList, CaseOut, CaseSearch, CaseUpdate, FeatureCount, FolderCount, LabelCount, Priority, Status,
)
from src.casebook.service import case_service
from src.casebook.utils import metrics

router = APIRouter()         # mounted at /projects/{project_id}/cases
labels_router = APIRouter()  # mounted at /projects/{project_id}/case-labels
folders_router = APIRouter()   # mounted at /projects/{project_id}/case-folders
features_router = APIRouter()  # mounted at /projects/{project_id}/case-features

NO_NUL = r"^[^\x00]*$"


def _case_or_404(db: Session, access: ProjectAccess, number: int):
    row = case_service.get_case(db, access.project_id, number)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return row


@router.get("", response_model=CaseList)
def list_cases(
    search: Optional[str] = Query(None, max_length=200, pattern=NO_NUL),
    search_in: Literal["scenario", "feature", "both"] = Query("scenario"),
    label: List[str] = Query([], max_length=20),
    status_filter: Optional[Status] = Query(None, alias="status"),
    priority: Optional[Priority] = Query(None),
    include_archived: bool = Query(False),
    origin: Optional[Literal["manual", "imported"]] = Query(None),
    folder: Optional[str] = Query(None, max_length=500, pattern=NO_NUL),
    linked: Optional[bool] = Query(None),
    feature: Optional[str] = Query(None, max_length=500, pattern=NO_NUL),
    ado: Optional[str] = Query(None, pattern=r"^[0-9]{1,12}$"),
    suite: Optional[Literal["none"]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    total, rows = case_service.list_cases(
        db, access.project_id, search=search, search_in=search_in, labels=label, status=status_filter, priority=priority,
        include_archived=include_archived, origin=origin, limit=limit, offset=offset,
        folder=folder, linked=linked, feature=feature, ado=ado, suite=suite,
    )
    return {"total": total, "items": [case_service.out(r) for r in rows]}


@router.post("/search", response_model=CaseList)
def search_cases(
    body: CaseSearch,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    """GET /cases' filters in a body, so a latest-result filter can send thousands of test keys."""
    data = body.model_dump()
    labels, limit, offset = data.pop("labels"), data.pop("limit"), data.pop("offset")
    total, rows = case_service.list_cases(db, access.project_id, labels=labels, limit=limit, offset=offset, **data)
    return {"total": total, "items": [case_service.out(r) for r in rows]}


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    row = case_service.create_case(db, access.project_id, access.user_id, payload.model_dump())
    metrics.CASES_CREATED.labels(type="manual").inc()
    return case_service.out(row)


@router.get("/{number}", response_model=CaseOut)
def get_case(
    number: int,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    row = _case_or_404(db, access, number)
    return case_service.out(row, case_service.suites_of(db, row))


@router.patch("/{number}", response_model=CaseOut)
def update_case(
    number: int,
    payload: CaseUpdate,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    row = _case_or_404(db, access, number)
    changes = payload.model_dump(exclude_unset=True)
    owned = case_service.repository_owned(row, changes)
    if owned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"{', '.join(owned)} come from {row.source_path}; change the .feature file instead")
    row = case_service.update_case(db, row, access.user_id, changes)
    return case_service.out(row, case_service.suites_of(db, row))


@labels_router.get("", response_model=list[LabelCount])
def list_labels(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return case_service.label_counts(db, access.project_id)


@folders_router.get("", response_model=list[FolderCount])
def list_folders(db: Session = Depends(get_db), access: ProjectAccess = Depends(require_project_role(*READ_ROLES))):
    return case_service.folder_counts(db, access.project_id)


@features_router.get("", response_model=list[FeatureCount])
def list_features(db: Session = Depends(get_db), access: ProjectAccess = Depends(require_project_role(*READ_ROLES))):
    return case_service.feature_counts(db, access.project_id)
