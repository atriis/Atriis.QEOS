"""The gateway's configuration as gateway/entrypoint.sh renders it (ADR-038): Compose keeps today's file byte for byte,
Kubernetes gets the cluster DNS, the namespace's service names, HTTP only behind the edge and its own rates.

The real entrypoint runs (sh and envsubst, no Docker), rendering into a temporary directory; the fixtures were rendered
by the gateway image before these settings existed, with Compose's defaults.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "gateway"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not (shutil.which("sh") and shutil.which("envsubst")), reason="needs sh and envsubst (gettext)"
)

KUBERNETES = {
    "UPSTREAM_SUFFIX": ".qeos.svc.cluster.local",
    "GATEWAY_RESOLVER": "kube-dns.kube-system.svc.cluster.local",
    "GATEWAY_TLS": "off",
    "GATEWAY_PUBLIC_PORT": "443",
    "GRAFANA_UPSTREAM": "grafana.qeos-monitoring.svc.cluster.local:3000",
    # Today's rates halved: two replicas each allow their own (spec 2026-10-21, section 5.4)
    "RATE_API": "10r/s",
    "RATE_AUTH": "150r/m",
    "RATE_COLLECT": "5r/s",
    "RATE_COLLECT_BLOBS": "25r/s",
    "RATE_COLLECT_ARTIFACTS": "5r/s",
}
SETTINGS = ["GATEWAY_HTTPS_PORT", "GATEWAY_IMPORT_MAX_BODY", "MONITORING_ENABLED", "GATEWAY_TRUSTED_PROXIES",
            "NGINX_RENDER_DIR", "NGINX_CERT_DIR", "GATEWAY_TEMPLATE_DIR", *KUBERNETES]


def render(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    """Runs entrypoint.sh with `true` as the command; the configuration lands in tmp_path/render."""
    render_dir = tmp_path / "render"
    cert_dir = render_dir / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)
    if env.get("GATEWAY_TLS") != "off":
        # A certificate already there: no openssl needed, as with compose's volume after the first start
        (cert_dir / "tls.crt").write_text("crt")
        (cert_dir / "tls.key").write_text("key")
    clean = {k: v for k, v in os.environ.items() if k not in SETTINGS}
    clean.update(
        NGINX_RENDER_DIR=render_dir.as_posix(),
        NGINX_CERT_DIR=cert_dir.as_posix(),
        GATEWAY_TEMPLATE_DIR=GATEWAY.as_posix(),
        # Git Bash on Windows: leave the paths in the environment as they are
        MSYS2_ENV_CONV_EXCL="*",
        MSYS_NO_PATHCONV="1",
    )
    clean.update(env)
    return subprocess.run(["sh", (GATEWAY / "entrypoint.sh").as_posix(), "true"], env=clean,
                          capture_output=True, text=True)


def rendered(tmp_path: Path, name: str) -> str:
    """A rendered file with the temporary directory put back to Compose's /etc/nginx, newlines as LF."""
    render_dir = (tmp_path / "render").as_posix()
    text = (tmp_path / "render" / name).read_text(encoding="utf-8")
    return text.replace(render_dir, "/etc/nginx")


def ok(tmp_path: Path, **env: str) -> tuple[str, str]:
    result = render(tmp_path, **env)
    assert result.returncode == 0, result.stderr
    return rendered(tmp_path, "nginx.conf"), rendered(tmp_path, "grafana.conf")


def active(conf: str) -> list[str]:
    """The lines nginx reads: no comments, no blank lines."""
    return [line.strip() for line in conf.splitlines() if line.strip() and not line.strip().startswith("#")]


def upstream_hosts(conf: str) -> list[str]:
    return re.findall(r"^\s*set \$\w+ http://([^:/;]+):\d+;", conf, re.M)


# ---- Compose: nothing changes ----

def test_compose_render_is_todays_file_byte_for_byte(tmp_path):
    nginx_conf, grafana_conf = ok(tmp_path)
    assert nginx_conf == (FIXTURES / "gateway-compose.conf").read_text(encoding="utf-8")
    assert grafana_conf == (GATEWAY / "grafana-off.conf").read_text(encoding="utf-8")


def test_compose_render_with_monitoring_is_todays_grafana_location(tmp_path):
    _, grafana_conf = ok(tmp_path, MONITORING_ENABLED="true")
    assert grafana_conf == (FIXTURES / "gateway-compose-grafana-on.conf").read_text(encoding="utf-8")


def test_compose_upstreams_have_no_suffix(tmp_path):
    nginx_conf, grafana_conf = ok(tmp_path, MONITORING_ENABLED="true")
    hosts = upstream_hosts(nginx_conf) + upstream_hosts(grafana_conf)
    assert hosts and all("." not in host for host in hosts), hosts


# ---- Kubernetes ----

@pytest.fixture
def kubernetes(tmp_path):
    return ok(tmp_path, MONITORING_ENABLED="true", **KUBERNETES)


def test_kubernetes_render_substitutes_everything(kubernetes):
    for conf in kubernetes:
        assert "${" not in conf


def test_kubernetes_upstreams_carry_the_suffix(kubernetes):
    nginx_conf, grafana_conf = kubernetes
    hosts = upstream_hosts(nginx_conf) + upstream_hosts(grafana_conf)
    service_hosts = [h for h in hosts if not h.startswith("grafana.")]
    assert len(service_hosts) >= 30, hosts
    assert all(h.endswith(".qeos.svc.cluster.local") for h in service_hosts), hosts
    assert "set $grafana_upstream http://grafana.qeos-monitoring.svc.cluster.local:3000;" in grafana_conf


def test_kubernetes_resolver_is_the_cluster_dns(kubernetes):
    assert "resolver kube-dns.kube-system.svc.cluster.local valid=10s ipv6=off;" in active(kubernetes[0])


def test_kubernetes_serves_every_location_over_http_on_8080_only(kubernetes, tmp_path):
    nginx_conf, _ = kubernetes
    lines = active(nginx_conf)
    assert [line for line in lines if line.startswith("listen")] == ["listen 8080;"]
    assert lines.count("server {") == 1
    assert not [line for line in lines if line.startswith("ssl_")]
    # The routes are still there, in that one server
    assert "location /api/v1/collect/artifacts {" in lines
    assert "include /etc/nginx/grafana.conf;" in lines
    # No certificate is made: TLS ends at the edge
    assert not any((tmp_path / "render" / "certs").iterdir())


def test_kubernetes_tells_the_services_the_public_scheme_is_https(kubernetes):
    for conf in kubernetes:
        protos = [line for line in active(conf) if "X-Forwarded-Proto" in line]
        assert protos and all(line == "proxy_set_header X-Forwarded-Proto https;" for line in protos), protos


def test_kubernetes_redirects_use_the_public_port(kubernetes):
    assert "proxy_redirect http://$host/ https://$host:443/;" in active(kubernetes[0])


def test_kubernetes_rates(kubernetes):
    lines = active(kubernetes[0])
    for zone, rate in [("api", "10r/s"), ("auth", "150r/m"), ("collect", "5r/s"), ("collect_blobs", "25r/s"),
                       ("collect_artifacts", "5r/s")]:
        assert f"limit_req_zone $binary_remote_addr zone={zone}:10m rate={rate};" in lines


def test_public_port_defaults_to_the_https_port(tmp_path):
    nginx_conf, _ = ok(tmp_path, GATEWAY_HTTPS_PORT="9443")
    assert "proxy_redirect http://$host/ https://$host:9443/;" in nginx_conf
    assert "return 301 https://$host:9443$request_uri;" in nginx_conf


# ---- Refused values ----

@pytest.mark.parametrize("name,value", [
    ("GATEWAY_TLS", "maybe"),
    ("RATE_API", "20r/s; allow all"),
    ("RATE_AUTH", "fast"),
    ("RATE_COLLECT", "10r/s\nallow all"),
    ("UPSTREAM_SUFFIX", "qeos.svc"),
    ("UPSTREAM_SUFFIX", ".qeos;x"),
    ("GATEWAY_RESOLVER", "10.0.0.10; include /etc/passwd"),
    ("GRAFANA_UPSTREAM", "grafana:3000; deny all"),
    ("GATEWAY_PUBLIC_PORT", "443x"),
])
def test_bad_values_stop_the_gateway_naming_the_setting(tmp_path, name, value):
    result = render(tmp_path, **{name: value})
    assert result.returncode != 0
    assert name in result.stderr
