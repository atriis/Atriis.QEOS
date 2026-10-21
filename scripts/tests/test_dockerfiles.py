"""Every platform image runs as a non-root user (ADR-038): the same images run on AKS, where the cluster refuses root.

nginx-based images start from nginx-unprivileged, which listens on 8080/8443 and keeps its pid and temp files in /tmp.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PYTHON_IMAGES = [
    "platforms/auth-service/auth-service/Dockerfile",
    "platforms/organization-service/Dockerfile",
    "platforms/project-service/Dockerfile",
    "platforms/ingestion-service/Dockerfile",
    "platforms/test-management-service/Dockerfile",
]
NGINX_IMAGES = ["gateway/Dockerfile", "dashboard/Dockerfile"]


def final_stage(path: str) -> str:
    """The Dockerfile from its last FROM on: the stage that becomes the image."""
    text = (ROOT / path).read_text(encoding="utf-8")
    starts = [m.start() for m in re.finditer(r"^FROM\s", text, re.M)]
    assert starts, f"{path} has no FROM"
    return text[starts[-1]:]


def users(stage: str) -> list[str]:
    return re.findall(r"^USER\s+(\S+)", stage, re.M)


@pytest.mark.parametrize("path", PYTHON_IMAGES + NGINX_IMAGES)
def test_image_runs_as_a_non_root_user(path):
    found = users(final_stage(path))
    assert found, f"{path}: no USER in the final stage, so the image runs as root"
    user = found[-1].split(":")[0]
    assert user not in ("root", "0"), f"{path}: the last USER is {found[-1]}"


@pytest.mark.parametrize("path", PYTHON_IMAGES)
def test_python_images_run_as_qeos_10001(path):
    stage = final_stage(path)
    assert users(stage)[-1:] == ["10001"], f"{path}: expected USER 10001"
    assert re.search(r"useradd\b[^\n]*--uid 10001\b[^\n]*\bqeos\b", stage), f"{path}: no user qeos with uid 10001"


@pytest.mark.parametrize("path", NGINX_IMAGES)
def test_nginx_images_start_from_nginx_unprivileged(path):
    assert re.match(r"FROM nginxinc/nginx-unprivileged:", final_stage(path)), path


def test_compose_publishes_the_gateway_on_unprivileged_container_ports():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"${GATEWAY_HTTPS_PORT:-8443}:8443"' in compose
    assert '"${GATEWAY_HTTP_PORT:-8080}:8080"' in compose


def test_prod_edge_proxies_to_the_gateway_https_container_port():
    assert "reverse_proxy https://gateway:8443" in (ROOT / "deploy/Caddyfile").read_text(encoding="utf-8")
