from fastapi import APIRouter
from src.organization.api.v1.endpoints import organizations, members, invitations, invitation_accept, sso_role_mappings

api_router = APIRouter()
api_router.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
api_router.include_router(members.router, prefix="/organizations/{org_id}/members", tags=["members"])
api_router.include_router(invitations.router, prefix="/organizations/{org_id}/invitations", tags=["invitations"])
api_router.include_router(invitation_accept.router, prefix="/invitations", tags=["invitations"])
api_router.include_router(sso_role_mappings.router, prefix="/organizations/{org_id}/sso-role-mappings",
                          tags=["sso-role-mappings"])

__all__ = ["api_router"]
