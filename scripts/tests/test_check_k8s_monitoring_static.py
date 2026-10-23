"""Static checks of scripts/check_k8s_monitoring.sh and the CI steps around it (ADR-038 Stage 2): no cluster needed.

The script queries the kind cluster's Prometheus and the chart's Alertmanager in CI (job helm-kind); these keep it
read only, kind only, in step with the chart's job names and replicas, and run where the brief says.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_k8s_monitoring.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"
VALUES = ROOT / "deploy" / "helm" / "qeos" / "values.yaml"


def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def helm_kind_job() -> str:
    text = CI.read_text(encoding="utf-8")
    match = re.search(r"^  helm-kind:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    assert match, "ci.yml has no helm-kind job"
    return match.group(1)


def test_bash_strict_mode():
    text = script()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert re.search(r"^set -uo pipefail$", text, re.M)


def test_executable_in_git():
    in_ci = bool(os.environ.get("CI"))
    if not shutil.which("git"):
        if in_ci:
            pytest.fail("git is not on PATH")
        pytest.skip("git is not on PATH")
    out = subprocess.run(
        ["git", "ls-files", "--stage", "scripts/check_k8s_monitoring.sh"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    if not out:
        if in_ci:
            pytest.fail("scripts/check_k8s_monitoring.sh is not tracked by git")
        pytest.skip("scripts/check_k8s_monitoring.sh is not tracked yet")
    assert out.startswith("100755"), f"not executable in git: {out.strip()}"


def test_kind_only_before_any_forward():
    text = script()
    assert re.search(r'case "\$context" in\n\s+kind-\*\) ;;', text)
    assert text.index('case "$context" in') < text.index('kubectl -n "$1" port-forward')


def test_read_only():
    # Queries and port-forwards only: nothing that changes the cluster
    for verb in ("apply", "create", "delete", "patch", "exec", "label", "annotate", "scale", "rollout"):
        assert not re.search(rf"kubectl[^\n]*\s{verb}\s", script()), f"kubectl {verb} in a read-only check"


def test_expected_jobs_follow_the_chart():
    """The job counts the script waits for: each API's metricsJob with its replicas, postgres and alertmanager once."""
    services = yaml.safe_load(VALUES.read_text(encoding="utf-8"))["services"]
    jobs = {svc["metricsJob"]: svc["replicas"] for svc in services.values() if svc.get("kind") == "api"}
    assert len(jobs) == 5, f"every API has a metricsJob: {jobs}"
    jobs.update({"postgres": 1, "alertmanager": 1})
    want = " ".join(f"{job}={n}" for job, n in sorted(jobs.items()))
    assert f'want="{want}"' in script()


def test_ci_runs_it_after_the_smoke_and_policy_checks():
    job = helm_kind_job()
    monitoring = job.index('bash scripts/check_k8s_monitoring.sh "$NAMESPACE"')
    assert job.index("bash deploy/monitoring/install.sh") < job.index("helm install qeos") < monitoring
    assert job.index('bash scripts/smoke_k8s.sh http://localhost:28080 "$NAMESPACE"') < monitoring
    assert job.index('bash scripts/check_k8s_policies.sh "$NAMESPACE"') < monitoring
    assert monitoring < job.index("A failed migration leaves the release serving")


def test_ci_checks_the_chart_copies_of_the_monitoring_files():
    job = helm_kind_job()
    render = job[job.index("- name: Chart render checks"):job.index("- name: Build the images")]
    assert 'bash "$CHART/tests/monitoring_files_test.sh"' in render


def test_a_failed_query_never_equals_an_expected_value():
    """An error answer or an empty body must not pass "no target down" (want ""): fetch() checks the HTTP status, a
    non-empty JSON body and Prometheus's status field, and prints a failure line instead of nothing."""
    body = re.search(r"^fetch\(\) \{\n(.*?)^\}", script(), re.M | re.S)
    assert body, "no fetch() function"
    text = body.group(1)
    assert "%{http_code}" in text and '!= 200' in text and '! -s ' in text
    assert "'.status'" in text and "!= success" in text
    assert 'echo "fetch failed:' in text
    assert re.search(r'^query\(\) \{ fetch ', script(), re.M), "query() goes through fetch()"


def test_every_api_read_goes_through_fetch():
    """A bare curl piped into yq turns a dropped port-forward into an empty answer, which passes "no rule in error":
    curl appears only in fetch(), in forward()'s readiness poll and in status_of(), which checks the HTTP status."""
    text = script()
    assert not re.search(r"curl[^\n]*\|\s*yq", text), "curl piped straight into yq"
    allowed = {"fetch", "forward", "status_of"}
    for match in re.finditer(r"^[^#\n]*\bcurl\s", text, re.M):
        before = text[:match.start()]
        func = re.findall(r"^(\w+)\(\) \{$", before, re.M)
        closed = before.rfind("\n}\n") > before.rfind(f"{func[-1]}() {{") if func else True
        assert func and not closed and func[-1] in allowed, f"curl outside fetch/forward/status_of: {match.group(0)}"


def test_rule_groups_check_leaves_out_both_skipped_groups():
    text = script()
    assert '" qeos-host "*' in text and '" qeos-containers "*' in text
    assert "qeos-host and qeos-containers left out" in text


def test_the_port_forward_to_3000_must_start_and_be_refused():
    """A forward that never started also gives 000: the check fails unless kubectl printed "Forwarding from" and
    then reports the pod refusing the connection."""
    text = script()
    block = text[text.index('port-forward deploy/grafana "$GF_DIRECT_PORT:3000"'):]
    block = block[:block.index("# Grafana itself, as the admin")]
    assert 'grep -q "Forwarding from"' in block and 'if [ -z "$started" ]; then' in block
    assert 'fail "the port-forward to the pod' in block
    assert "connection refused|failed to connect" in block and 'fail "... the forward' in block
