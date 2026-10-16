"""The caller's role in a project, from project-service's GET /projects/{id}.

Contract (see the ingestion-service design spec): on 200 the body is a JSON object with an integer
`organization_id` and `my_role` in ROLES. Anything else on a 200 is treated as the service being
unavailable, so a changed or broken response can never be read as a granted role.
"""
from typing import NamedTuple

import httpx

from src.ingestion.core.config import settings

ROLES = ("owner", "admin", "member", "viewer", "billing_manager")


class ProjectInfo(NamedTuple):
    role: str
    organization_id: int


class ProjectServiceUnavailable(Exception):
    """project-service could not give a trustworthy answer."""


class ProjectNotFound(Exception):
    """The project does not exist, is deleted, or the caller may not see it."""


class InvalidCredentials(Exception):
    """project-service rejected the caller's token."""


def get_project(project_id: int, token: str) -> ProjectInfo:
    url = f"{settings.PROJECT_SERVICE_URL.rstrip('/')}/api/v1/projects/{int(project_id)}"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.PROJECT_SERVICE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ProjectServiceUnavailable(f"could not reach project-service: {exc}") from exc

    # 410: the project is pending deletion (spec 2026-10-16); for every other service it no longer exists
    if response.status_code in (404, 410):
        raise ProjectNotFound()
    if response.status_code == 401:
        raise InvalidCredentials()
    if response.status_code != 200:
        raise ProjectServiceUnavailable(f"unexpected project-service status {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise ProjectServiceUnavailable("project-service returned a non-JSON body") from exc

    if not isinstance(body, dict):
        raise ProjectServiceUnavailable("project-service response is not an object")
    role, organization_id = body.get("my_role"), body.get("organization_id")
    # bool is a subclass of int; it is not a valid id
    if role not in ROLES or not isinstance(organization_id, int) or isinstance(organization_id, bool):
        raise ProjectServiceUnavailable("project-service response does not match the expected contract")
    return ProjectInfo(role=role, organization_id=organization_id)
