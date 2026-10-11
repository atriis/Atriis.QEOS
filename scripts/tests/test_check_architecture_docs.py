"""scripts/check_architecture_docs.py on a small repository built per test, then on the real one."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_architecture_docs.py"
spec = importlib.util.spec_from_file_location("check_architecture_docs", SCRIPT)
docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs)

COMPOSE = """name: qeos
services:
  postgres:
    image: postgres:15
  auth-migrate:
    image: x
  auth-service:
    depends_on:
      auth-migrate:
        condition: service_completed_successfully
  weekly-summary:
    image: x
  prometheus:
    profiles: [monitoring]
volumes:
  data:
"""
PROD = """services:
  auth-service:
    image: x
  edge:
    image: caddy
"""
NGINX = "location / { set $upstream http://auth-service:8000; proxy_pass $upstream; }\n"
README = """# QEOS

## Architecture

```mermaid
flowchart TB
    AUTH[auth-service] --> PG[("PostgreSQL 15")]
    JOBS["weekly-summary"]
    PROM[Prometheus]
```

| Component | Path | Responsibility |
|---|---|---|
| auth-service | [`auth/`](auth/) | Users |
| PostgreSQL | [`db/`](db/) | `postgres` |
| Jobs | [`jobs/`](jobs/) | `weekly-summary` |
| Monitoring | [`mon/`](mon/) | Prometheus |
| Production | [`deploy/`](deploy/) | behind `edge` |

## Next
"""
BANNER = "# Blueprint\n\n> | Area | Status |\n> |---|---|\n> | Services | CURRENT: auth, weekly-summary job |\n"


@pytest.fixture
def repo(tmp_path):
    files = {"docker-compose.yml": COMPOSE, "deploy/docker-compose.prod.yml": PROD, "gateway/nginx.conf.template": NGINX,
             "README.md": README, "ARCHITECTURE_BLUEPRINT_V1_0.md": BANNER}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    for d in ("auth", "db", "jobs", "mon"):
        (tmp_path / d).mkdir()

    def edit(rel, old, new):
        path = tmp_path / rel
        text = path.read_text(encoding="utf-8")
        assert old in text
        path.write_text(text.replace(old, new), encoding="utf-8")
    return tmp_path, edit


def test_a_matching_repository_has_no_problems(repo):
    root, _ = repo
    assert docs.check(root) == []


def test_one_shot_jobs_are_not_required(repo):
    root, _ = repo
    assert "auth-migrate" not in docs.compose_services((root / "docker-compose.yml").read_text())


def test_a_new_compose_service_must_be_drawn_listed_and_in_the_banner(repo):
    root, edit = repo
    edit("docker-compose.yml", "volumes:", "  billing-service:\n    image: x\nvolumes:")
    assert docs.check(root) == [
        "README.md diagram: compose service 'billing-service' is not drawn",
        "README.md component table: compose service 'billing-service' is not listed",
        "ARCHITECTURE_BLUEPRINT_V1_0.md status banner: service 'billing-service' is missing from the Services row"]


def test_a_monitoring_service_is_not_required_in_the_banner(repo):
    root, edit = repo
    edit("docker-compose.yml", "volumes:", "  cadvisor:\n    profiles: [monitoring]\nvolumes:")
    assert all("banner" not in p for p in docs.check(root))


def test_a_drawn_service_that_does_not_run_is_reported(repo):
    root, edit = repo
    edit("README.md", "PROM[Prometheus]", "PROM[Prometheus]\n    QIP[qip-service]")
    assert docs.check(root) == ["documentation names 'qip-service', which docker-compose.yml does not run"]


def test_a_production_only_service_must_be_listed(repo):
    root, edit = repo
    edit("README.md", "behind `edge`", "behind a proxy")
    assert docs.check(root) == [
        "README.md component table: production service 'edge' (deploy/docker-compose.prod.yml) is not listed"]


def test_a_gateway_upstream_must_be_a_compose_service(repo):
    root, edit = repo
    edit("gateway/nginx.conf.template", "auth-service:8000", "old-service:8000")
    assert docs.check(root) == ["gateway proxies to 'old-service', which docker-compose.yml does not run"]


def test_a_table_path_must_exist(repo):
    root, edit = repo
    edit("README.md", "[`jobs/`](jobs/)", "[`jobs/`](gone/)")
    assert docs.check(root) == ["README.md component table: path 'gone/' does not exist"]


def test_a_missing_section_is_reported_not_crashed_on(repo):
    root, edit = repo
    edit("README.md", "## Architecture", "## Overview")
    assert docs.check(root) == ["README.md: no Architecture section", "README.md: no Mermaid diagram",
                                "README.md: no component table"]


def test_the_real_repository_matches():
    assert docs.check() == []
