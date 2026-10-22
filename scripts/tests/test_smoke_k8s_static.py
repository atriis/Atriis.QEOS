"""Static checks of scripts/smoke_k8s.sh and the CI job that runs it (ADR-038, spec 5.10): nothing here needs a cluster.

The script runs against kind in CI (job helm-kind); these keep it safe to run and in step with the gateway and the job.
"""
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "smoke_k8s.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"
GATEWAY = ROOT / "gateway" / "nginx.conf.template"
VALUES_CI = ROOT / "deploy" / "helm" / "qeos" / "values-ci.yaml"


def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def helm_kind_job() -> str:
    """The helm-kind job's text, up to the next job."""
    text = CI.read_text(encoding="utf-8")
    match = re.search(r"^  helm-kind:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    assert match, "ci.yml has no helm-kind job"
    return match.group(1)


def test_bash_strict_mode():
    text = script()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert re.search(r"^set -uo pipefail$", text, re.M)


def test_executable_in_git():
    if not shutil.which("git"):
        return
    out = subprocess.run(
        ["git", "ls-files", "--stage", "scripts/smoke_k8s.sh"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    if out:  # not yet added: nothing to check
        assert out.startswith("100755"), f"scripts/smoke_k8s.sh is not executable in git: {out.strip()}"


def test_refuses_anything_but_a_local_forward_on_kind():
    text = script()
    # The URL guard allows only localhost / 127.0.0.1 over http (the port-forward), and the context must be kind-*
    assert re.search(r'case "\$BASE" in\n\s+http://localhost:\*\|http://127\.0\.0\.1:\*\) ;;', text)
    assert re.search(r'case "\$context" in\n\s+kind-\*\) ;;', text)
    guard = text.index('case "$BASE" in')
    first_request = text.index("curl ")
    first_exec = text.index("exec deploy/postgres")
    assert guard < first_request and guard < first_exec, "the guards must come before any request or kubectl exec"


def test_every_curl_has_a_timeout_and_verifies_tls():
    calls = [line for line in script().splitlines() if re.search(r"\bcurl\b", line) and not line.lstrip().startswith("#")]
    assert calls
    for line in calls:
        assert "--max-time" in line, f"curl without --max-time: {line.strip()}"
        assert not re.search(r"\s(-k|--insecure|-\w*k\w*)\s", line), f"curl skips TLS checks: {line.strip()}"


def test_the_api_key_is_never_printed():
    for line in script().splitlines():
        if re.match(r"\s*(echo|printf|pass|fail)\b", line):
            assert "API_KEY" not in line and "TOKEN" not in line, f"a secret may be printed: {line.strip()}"


def test_checks_every_health_route_of_the_gateway():
    routes = set(re.findall(r"location = /health/([\w-]+)", GATEWAY.read_text(encoding="utf-8")))
    assert routes
    match = re.search(r"for svc in ([\w\- ]+); do\n\s+check \"/health/\$svc", script())
    assert match, "no loop over the /health/<service> routes"
    assert set(match.group(1).split()) == routes


def test_success_lines():
    text = script()
    assert 'echo "all k8s checks passed"' in text
    assert 'echo "all k8s health checks passed"' in text
    # --health-only stops before the user flow, which writes to the databases
    assert text.index('if [ "$HEALTH_ONLY" = true ]') < text.index("/api/v1/auth/register")


def test_ci_job_runs_the_script_both_ways():
    job = helm_kind_job()
    assert re.search(r"bash scripts/smoke_k8s\.sh http://localhost:(\d+) \"\$NAMESPACE\" \|\|", job)
    assert re.search(r"bash scripts/smoke_k8s\.sh http://localhost:\d+ \"\$NAMESPACE\" --health-only", job)
    ports = set(re.findall(r"port-forward svc/gateway (\d+):8080", job))
    urls = set(re.findall(r"smoke_k8s\.sh http://localhost:(\d+)", job))
    assert ports and ports == urls, f"port-forward ports {ports} and smoke URLs {urls} differ"
    # The failed-upgrade check uses a migration tag that cannot exist and must see the upgrade fail
    assert "--set migrate.imageTag=does-not-exist" in job
    assert re.search(r"if helm upgrade .*\n(.*\n)*?.*then\n\s+echo \"::error::", job)


def test_ci_job_pins_kind_and_the_images_match_values_ci():
    job = helm_kind_job()
    assert re.search(r"node_image: kindest/node:v1\.\d+\.\d+@sha256:[0-9a-f]{64}", job), "kind node image not pinned"
    assert re.search(r"uses: helm/kind-action@v\d+", job)
    tag = re.search(r"^  tag: (\S+)$", VALUES_CI.read_text(encoding="utf-8"), re.M)
    assert tag, "values-ci.yaml sets no image.tag"
    assert re.search(rf"^      TAG: {re.escape(tag.group(1))}$", job, re.M), "the job builds another tag than values-ci"
    assert tag.group(1) != "local", "Compose's tag: a local kind build would replace the dev stack's images"
