"""Static checks of scripts/check_k8s_policies.sh and the CI steps around it (ADR-038, spec 5.3): no cluster needed.

The script runs throwaway pods in the release namespace of a kind cluster (job helm-kind) and calls the Services from
there; these keep it safe to run, its checks well formed, and the namespace it runs in restricted.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_k8s_policies.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"
VALUES = ROOT / "deploy" / "helm" / "qeos" / "values.yaml"


def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def helm_kind_job() -> str:
    text = CI.read_text(encoding="utf-8")
    match = re.search(r"^  helm-kind:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    assert match, "ci.yml has no helm-kind job"
    return match.group(1)


def checks() -> list[list[str]]:
    block = re.search(r"^CHECKS=\(\n(.*?)^\)", script(), re.M | re.S)
    assert block, "no CHECKS list"
    return [line.split() for line in re.findall(r'^\s+"([^"]+)"$', block.group(1), re.M)]


def workloads_with_a_service() -> set[str]:
    # services.<name>.kind in values.yaml: api, dashboard and gateway get a Service (templates/services.yaml)
    names, current = set(), None
    for line in VALUES.read_text(encoding="utf-8").splitlines():
        if m := re.match(r"^  ([a-z][\w-]*):$", line):
            current = m.group(1)
        elif (m := re.match(r"^    kind: (\w+)$", line)) and current and m.group(1) in ("api", "dashboard", "gateway"):
            names.add(current)
    return names


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
        ["git", "ls-files", "--stage", "scripts/check_k8s_policies.sh"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    if not out:
        if in_ci:
            pytest.fail("scripts/check_k8s_policies.sh is not tracked by git")
        pytest.skip("scripts/check_k8s_policies.sh is not tracked yet")
    assert out.startswith("100755"), f"not executable in git: {out.strip()}"


def test_kind_only_before_any_pod():
    text = script()
    assert re.search(r'case "\$context" in\n\s+kind-\*\) ;;', text)
    guard = text.index('case "$context" in')
    assert guard < text.index("apply -f -") and guard < text.index("--dry-run=server")


def test_curl_image_pinned_by_digest_and_pod_is_restricted():
    text = script()
    assert re.search(r'^IMAGE="curlimages/curl:[\d.]+@sha256:[0-9a-f]{64}"$', text, re.M)
    pod = text[text.index("kind: Pod"):text.index("\nYAML\n")]
    for setting in ("runAsNonRoot: true", "readOnlyRootFilesystem: true", "allowPrivilegeEscalation: false",
                    'drop: ["ALL"]', "type: RuntimeDefault", "runAsUser: $CURL_UID"):
        assert setting in pod, f"the throwaway pod lacks {setting}"


def test_every_in_cluster_curl_times_out():
    calls = [line for line in script().splitlines() if re.search(r"\bexec\b.*\bcurl\b", line)]
    assert calls
    for line in calls:
        assert re.search(r"\s-m \d+\s", line), f"curl without -m: {line.strip()}"


def test_checks_are_well_formed_and_never_borrow_a_served_workload():
    served = workloads_with_a_service()
    assert {"auth-service", "gateway", "dashboard"} <= served
    rows = checks()
    assert rows
    for row in rows:
        assert len(row) == 3, f"not FROM URL EXPECT: {row}"
        source, url, expect = row
        assert re.fullmatch(r"blocked|\d{3}", expect), f"EXPECT is a status or blocked: {row}"
        assert url.startswith("http://"), row
        # A Service selecting the throwaway pod would send it real traffic
        assert source == "stranger" or source not in served, f"{source} has a Service: {row}"
    # What the brief asks: a pod that is no caller times out on auth-service; and a caller gets through
    assert ["stranger", "http://auth-service:8000/health", "blocked"] in rows
    assert any(expect.isdigit() for _, _, expect in rows), "no positive control"


def test_ci_restricts_the_namespace_and_runs_the_check_after_the_install():
    job = helm_kind_job()
    # Create-if-missing: deploy/monitoring/install.sh may have created and labelled it already
    assert 'kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -' in job
    assert 'kubectl label namespace "$NAMESPACE" --overwrite pod-security.kubernetes.io/enforce=restricted' in job
    install = job.index("helm install qeos")
    assert job.index("pod-security.kubernetes.io/enforce=restricted") < install
    check = job.index('bash scripts/check_k8s_policies.sh "$NAMESPACE"')
    assert install < check < job.index("A failed migration leaves the release serving")
