from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.ingestion.api.deps import MANAGE_ROLES, READ_ROLES, ProjectAccess, get_db, require_project_role
from src.ingestion.schemas.collection_settings import CollectionSettingsIn, CollectionSettingsOut
from src.ingestion.service import collection_settings_service

router = APIRouter()  # mounted at /projects/{project_id}/collection-settings


@router.get("", response_model=CollectionSettingsOut)
def get_collection_settings(
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*READ_ROLES)),
):
    return collection_settings_service.get(db, access.project_id)


@router.put("", response_model=CollectionSettingsOut)
def put_collection_settings(
    payload: CollectionSettingsIn,
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*MANAGE_ROLES)),
):
    return collection_settings_service.put(db, access.project_id, payload.collect_manual, access.user_id)
