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


ROUTE_COMPOSE = """services:
  auth-service:
    image: x
  project-service:
    image: x
  runs-service:
    image: x
"""
ROUTE_NGINX = """server {
    listen 8080;
    location / { return 301 https://$host$request_uri; }
}
server {
    listen 8443 ssl;
    location ~ ^/api/v1/projects/[0-9]+/(runs|analytics)(/|$) {
        set $upstream http://runs-service:8000;
        proxy_pass $upstream;
    }
    location /api/v1/projects {
        set $upstream http://project-service:8000;
        proxy_pass $upstream;
    }
    location = /api/v1/auth/login {
        limit_req zone=auth;
        set $upstream http://auth-service:8000;
        proxy_pass $upstream;
    }
    location /api/v1/auth {
        set $upstream http://auth-service:8000;
        proxy_pass $upstream;
    }
    location /api/ { return 404; }
    location / {
        set $upstream http://dashboard:8080;
        proxy_pass $upstream;
    }
}
"""
ROUTE_README = """# Gateway

## Routes

| Path | Service |
|---|---|
| `/api/v1/projects/{id}/runs…`, `…/analytics…` | runs-service |
| `/api/v1/projects…` | project-service |
| `/api/v1/auth…` | auth-service |
| `/health` | the gateway itself |

## Next
"""
APIS = {
    "auth-service/auth-service/src/auth": 'api_router.include_router(auth.router, prefix="/auth", tags=["auth"])\n',
    "project-service/src/project": 'api_router.include_router(projects.router, prefix="/projects")\n'
                                   'api_router.include_router(\n    repos.router, prefix="/projects/{project_id}/repositories"\n)\n',
    "runs-service/src/runs": 'api_router.include_router(runs.router, prefix="/projects/{project_id}/runs")\n'
                             'api_router.include_router(analytics.router, prefix="/projects/{project_id}/analytics")\n'
                             'api_router.include_router(report.router, prefix="/projects/{project_id}/analytics")\n',
}


@pytest.fixture
def routes(tmp_path):
    files = {"docker-compose.yml": ROUTE_COMPOSE, "gateway/nginx.conf.template": ROUTE_NGINX,
             "gateway/README.md": ROUTE_README,
             **{f"platforms/{d}/api/v1/api.py": text for d, text in APIS.items()},
             "platforms/runs-service/.venv/lib/x/api/v1/api.py": 'include_router(x, prefix="/nowhere")\n'}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")

    def edit(rel, old, new):
        path = tmp_path / rel
        text = path.read_text(encoding="utf-8")
        assert old in text
        path.write_text(text.replace(old, new), encoding="utf-8")
    return tmp_path, edit


def test_matching_routes_have_no_problems(routes):
    root, _ = routes
    assert docs.check_routes(root) == []


def test_nginx_picks_exact_then_regex_then_longest_prefix():
    locations = docs.https_locations(ROUTE_NGINX)
    assert docs.route(locations, "/api/v1/auth/login")[0] == "="
    assert docs.route(locations, "/api/v1/projects/1/runs")[2] == "runs-service"
    assert docs.route(locations, "/api/v1/projects/1/repositories")[2] == "project-service"
    assert docs.route(locations, "/api/v1/nothing")[2] is None
    assert docs.route(locations, "/login")[2] == "dashboard"


def test_continued_paths_in_the_routes_table_take_the_first_path_s_base():
    assert docs.documented_routes(ROUTE_README)[:2] == [
        ("/api/v1/projects/{id}/runs", "runs-service"), ("/api/v1/projects/{id}/analytics", "runs-service")]


def test_a_new_api_prefix_the_gateway_sends_elsewhere_is_reported(routes):
    root, edit = routes
    edit("platforms/runs-service/src/runs/api/v1/api.py", "\n",
         '\napi_router.include_router(x.router, prefix="/projects/{project_id}/flaky")\n')
    assert docs.check_routes(root) == [
        "gateway: /api/v1/projects/1/flaky (runs-service's /projects/{id}/flaky) goes to project-service",
        "gateway/README.md Routes: /api/v1/projects/{id}/flaky belongs to runs-service, the table says project-service"]


def test_a_gateway_route_without_a_service_route_is_reported(routes):
    root, edit = routes
    edit("gateway/nginx.conf.template", "(runs|analytics)", "(runs|analytics|trends)")
    assert docs.check_routes(root) == [
        "gateway: location ^/api/v1/projects/[0-9]+/(runs|analytics|trends)(/|$) sends "
        "/api/v1/projects/1/trends to runs-service, which has no such route"]


def test_a_routes_table_row_naming_the_wrong_service_is_reported(routes):
    root, edit = routes
    edit("gateway/README.md", "`/api/v1/auth…` | auth-service", "`/api/v1/auth…` | project-service")
    assert docs.check_routes(root) == [
        "gateway/README.md Routes: /api/v1/auth belongs to auth-service, the table says project-service",
        "gateway/README.md Routes: /api/v1/auth is listed for project-service, the gateway sends it to auth-service"]


def test_a_missing_routes_table_is_reported(routes):
    root, edit = routes
    edit("gateway/README.md", "## Routes", "## Paths")
    assert docs.check_routes(root) == ["gateway/README.md: no Routes table"]


def test_a_gateway_without_an_https_server_is_reported_not_crashed_on(routes):
    root, edit = routes
    edit("gateway/nginx.conf.template", "listen 8443 ssl;", "listen 8443;")
    assert docs.check_routes(root) == ["gateway/nginx.conf.template: no HTTPS server block (`listen <port> ssl`)"]


def test_the_kubernetes_template_forms_are_read_like_the_plain_ones(routes):
    # entrypoint.sh renders the listen and the namespace suffix (ADR-038); the routes are the same
    root, edit = routes
    edit("gateway/nginx.conf.template", "listen 8443 ssl;", "listen ${MAIN_LISTEN};")
    edit("gateway/nginx.conf.template", "http://project-service:8000", "http://project-service${UPSTREAM_SUFFIX}:8000")
    assert docs.check_routes(root) == []
    edit("gateway/nginx.conf.template", "http://auth-service:8000", "http://runs-service${UPSTREAM_SUFFIX}:8000")
    assert "gateway: /api/v1/auth (auth-service's /auth) goes to runs-service" in docs.check_routes(root)


def test_a_suffixed_gateway_upstream_must_be_a_compose_service(repo):
    root, edit = repo
    edit("gateway/nginx.conf.template", "auth-service:8000", "old-service${UPSTREAM_SUFFIX}:8000")
    assert docs.check(root) == ["gateway proxies to 'old-service', which docker-compose.yml does not run"]


def test_the_real_repository_matches():
    assert docs.check() == []
    assert docs.check_routes() == []
