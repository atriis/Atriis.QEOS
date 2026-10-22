"""build-platform.yml pushes the images the Helm chart pulls (ADR-038), and listens to the workflow that is called CI.

A service added to the chart without a matrix entry would deploy an image nobody pushed; a renamed CI workflow would
stop the build without an error. A release tag must reuse master's images, never build new ones, and the build and
deploy jobs must sign in as two different Azure identities.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(workflow: dict) -> dict:
    # YAML 1.1 reads the key `on` as True
    return workflow.get("on", workflow.get(True))


def chart_images() -> set[str]:
    """The image every entry under services: runs; its own name unless it names the image of another (the loop jobs)."""
    values = load(ROOT / "deploy" / "helm" / "qeos" / "values.yaml")
    return {svc.get("image", name) for name, svc in values["services"].items()}


def test_matrix_builds_every_image_the_chart_uses():
    matrix = load(WORKFLOWS / "build-platform.yml")["jobs"]["images"]["strategy"]["matrix"]["include"]
    built = [entry["image"] for entry in matrix]
    assert len(built) == len(set(built)), f"an image appears twice in the matrix: {built}"
    assert set(built) == chart_images()


def test_ci_scan_matrix_matches_the_push_matrix():
    push = load(WORKFLOWS / "build-platform.yml")["jobs"]["images"]["strategy"]["matrix"]["include"]
    scan = load(WORKFLOWS / "ci.yml")["jobs"]["image-scan"]["strategy"]["matrix"]["include"]
    assert scan == push


def test_every_matrix_dockerfile_exists():
    matrix = load(WORKFLOWS / "build-platform.yml")["jobs"]["images"]["strategy"]["matrix"]["include"]
    for entry in matrix:
        assert (ROOT / entry["dockerfile"]).is_file(), entry


def test_trigger_names_the_ci_workflow():
    listened = triggers(load(WORKFLOWS / "build-platform.yml"))["workflow_run"]["workflows"]
    assert listened == [load(WORKFLOWS / "ci.yml")["name"]]


def test_deploy_listens_to_the_build_and_deploys_the_commit_it_recorded():
    build = load(WORKFLOWS / "build-platform.yml")
    deploy = load(WORKFLOWS / "deploy-aks.yml")
    assert triggers(deploy)["workflow_run"]["workflows"] == [build["name"]]
    # build-platform's job built uploads the artifact deploy-aks's target job downloads from the triggering run
    upload = [s for s in build["jobs"]["built"]["steps"] if s.get("uses", "").startswith("actions/upload-artifact@")]
    download = [s for s in deploy["jobs"]["target"]["steps"] if s.get("uses", "").startswith("actions/download-artifact@")]
    assert len(upload) == len(download) == 1
    assert upload[0]["with"]["name"] == download[0]["with"]["name"] == "built-sha"
    assert download[0]["with"]["run-id"] == "${{ github.event.workflow_run.id }}"
    assert build["jobs"]["built"]["needs"] == "images"


def test_deploy_checks_every_image_the_build_pushes():
    pushed = {entry["image"] for entry in load(WORKFLOWS / "build-platform.yml")["jobs"]["images"]["strategy"]["matrix"]["include"]}
    check = next(s for s in load(WORKFLOWS / "deploy-aks.yml")["jobs"]["deploy"]["steps"] if s.get("name") == "Check that every image exists")
    listed = set(check["run"].split("for name in ", 1)[1].split("; do", 1)[0].replace("\\", " ").split())
    assert listed == pushed


def test_deploy_concurrency_is_on_the_deploy_job_only():
    # At workflow level a run that deploys nothing would cancel a pending real deploy
    deploy = load(WORKFLOWS / "deploy-aks.yml")
    assert "concurrency" not in deploy
    assert deploy["jobs"]["deploy"]["concurrency"]["cancel-in-progress"] is False


# ---- A platform-v* tag tags what master's build pushed; it never builds (spec 5.2) ----

def build_jobs() -> dict:
    return load(WORKFLOWS / "build-platform.yml")["jobs"]


def step(job: dict, name: str) -> dict:
    return next(s for s in job["steps"] if s.get("name") == name)


def test_a_tag_never_builds_or_pushes_the_sha():
    jobs = build_jobs()
    # The build job runs for green CI runs on master only; the tag job builds and pushes nothing
    assert jobs["images"]["if"].startswith("github.event_name == 'workflow_run' &&")
    release = jobs["release"]
    assert release["if"] == "github.event_name == 'push' && github.ref_type == 'tag'"
    script = "\n".join(s.get("run", "") + s.get("uses", "") for s in release["steps"])
    for forbidden in ("docker build ", "docker push", "docker tag", "trivy", "az acr import"):
        assert forbidden not in script, forbidden
    run = step(release, "Tag the images with the version")["run"]
    assert 'docker buildx imagetools create --tag "$image:$VERSION" "$image@${want[$name]}"' in run


def test_the_release_tags_every_image_the_build_pushes():
    pushed = [entry["image"] for entry in build_jobs()["images"]["strategy"]["matrix"]["include"]]
    run = step(build_jobs()["release"], "Tag the images with the version")["run"]
    listed = run.split("images=(", 1)[1].split(")", 1)[0].split()
    assert listed == pushed


def bash() -> str:
    found = shutil.which("bash")
    # Windows' System32\bash.exe is WSL, which does not see this environment's PATH
    if not found or "system32" in found.lower():
        pytest.skip("no bash")
    return found


def run_release(tmp_path: Path, registry: dict) -> tuple:
    """The release step's script against stub az and docker over a registry of files {"name:tag": digest}."""
    reg = tmp_path / "registry"
    reg.mkdir()
    for ref, digest in registry.items():
        (reg / ref.replace(":", "_")).write_text(digest)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    # az acr repository show --name ACR --image qeos/NAME:TAG --query digest -o tsv
    (stubs / "az").write_text(
        '#!/bin/sh\nref="${7#qeos/}"; f="$REG/$(echo "$ref" | tr : _)"\n'
        '[ -f "$f" ] || { echo "manifest unknown" >&2; exit 3; }\ncat "$f"; echo\n', newline="\n")
    # docker buildx imagetools create --tag REG/qeos/NAME:VERSION REG/qeos/NAME@DIGEST: the registry gets the same digest
    (stubs / "docker").write_text(
        '#!/bin/sh\necho "$*" >> "$REG/../docker.log"\ndst="${5##*/qeos/}"; src="${6##*@}"\n'
        'printf %s "$src" > "$REG/$(echo "$dst" | tr : _)"\n', newline="\n")
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(step(build_jobs()["release"], "Tag the images with the version")["run"], newline="\n")
    env = dict(os.environ, PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}", REG=reg.as_posix(),
               ACR_NAME="acrqeos", SHA="a" * 40, VERSION="1.2.3", MSYS_NO_PATHCONV="1")
    out = subprocess.run([bash(), "-e", script.as_posix()], env=env, capture_output=True, text=True)
    after = {f.name.replace("_", ":", 1): f.read_text().strip() for f in reg.iterdir()}
    log = (tmp_path / "docker.log").read_text() if (tmp_path / "docker.log").exists() else ""
    return out, after, log


SHA = "a" * 40
IMAGES = ["auth-service", "organization-service", "project-service", "ingestion-service", "test-management-service",
          "dashboard", "gateway"]


def test_release_gives_the_version_the_sha_images_digest(tmp_path):
    built = {f"{name}:{SHA}": f"sha256:{i:064x}" for i, name in enumerate(IMAGES)}
    out, after, log = run_release(tmp_path, built)
    assert out.returncode == 0, out.stdout + out.stderr
    for i, name in enumerate(IMAGES):
        assert after[f"{name}:1.2.3"] == after[f"{name}:{SHA}"] == f"sha256:{i:064x}"
    assert log.count("buildx imagetools create") == 7


def test_release_with_a_missing_sha_image_tags_nothing(tmp_path):
    built = {f"{name}:{SHA}": f"sha256:{i:064x}" for i, name in enumerate(IMAGES) if name != "gateway"}
    out, after, log = run_release(tmp_path, built)
    assert out.returncode != 0
    assert f"::error::Not in acrqeos: qeos/gateway:{SHA}" in out.stdout
    assert log == "" and not any(ref.endswith(":1.2.3") for ref in after)


def test_release_never_moves_an_existing_version(tmp_path):
    built = {f"{name}:{SHA}": f"sha256:{i:064x}" for i, name in enumerate(IMAGES)}
    built["dashboard:1.2.3"] = "sha256:" + "f" * 64
    out, after, log = run_release(tmp_path, built)
    assert out.returncode != 0 and "never moved" in out.stdout
    assert log == "" and after["dashboard:1.2.3"] == "sha256:" + "f" * 64


# ---- Two Azure identities: the build one (AcrPush) and the deploy one (the cluster), never the same variable ----

def test_build_and_deploy_sign_in_as_different_identities():
    build = (WORKFLOWS / "build-platform.yml").read_text(encoding="utf-8")
    deploy_text = (WORKFLOWS / "deploy-aks.yml").read_text(encoding="utf-8")
    for source in (build, deploy_text):
        assert "vars.AZURE_CLIENT_ID" not in source and "env.AZURE_CLIENT_ID" not in source
    assert build.count("client-id: ${{ env.AZURE_BUILD_CLIENT_ID }}") == 2
    assert "vars.AZURE_DEPLOY_CLIENT_ID" not in build
    assert "vars.AZURE_BUILD_CLIENT_ID" not in deploy_text
    deploy = load(WORKFLOWS / "deploy-aks.yml")["jobs"]
    # Only the job that declares the GitHub environment reads the deploy identity (an environment variable)
    assert deploy["deploy"]["environment"] == "${{ needs.target.outputs.environment }}"
    assert deploy["deploy"]["env"]["AZURE_DEPLOY_CLIENT_ID"] == "${{ vars.AZURE_DEPLOY_CLIENT_ID }}"
    assert "environment" not in deploy["target"] and "AZURE_DEPLOY_CLIENT_ID" not in str(deploy["target"])
    logins = [s for s in deploy["deploy"]["steps"] if s.get("uses", "").startswith("azure/login@")]
    assert len(logins) == 2 and all(s["with"]["client-id"] == "${{ env.AZURE_DEPLOY_CLIENT_ID }}" for s in logins)


# ---- deploy-aks.yml: the runner's address is always removed within the job's time ----

def test_the_runner_cleanup_fits_in_the_job():
    job = load(WORKFLOWS / "deploy-aks.yml")["jobs"]["deploy"]
    assert job["env"]["JOB_TIMEOUT_MINUTES"] == job["timeout-minutes"]
    # Every step that waits has a budget; with the cleanup's 25 minutes and a few for the rest, they fit in the job
    budgets = {s["name"]: s["timeout-minutes"] for s in job["steps"] if "timeout-minutes" in s}
    assert set(budgets) == {"Allow this runner to reach the API server", "Deploy the chart", "Check the edge"}
    assert sum(budgets.values()) + 25 + 10 <= job["timeout-minutes"]
    cleanup = step(job, "Remove this runner from the API server's ranges")["run"]
    assert "deadline=$(( now + 25 * 60 ))" in cleanup
    assert "job_end=$(( ${JOB_STARTED:-$now} + (JOB_TIMEOUT_MINUTES - 2) * 60 ))" in cleanup
    assert "for _ in 1 2 3 4 5" not in cleanup and "seq 120" not in cleanup
    assert 'echo "JOB_STARTED=$(date +%s)" >> "$GITHUB_ENV"' in step(job, "Check the configuration")["run"]


def test_a_failed_artifact_download_is_a_warning():
    target = load(WORKFLOWS / "deploy-aks.yml")["jobs"]["target"]
    check = step(target, "Check the environment and the tag")
    assert check["env"]["BUILT_OUTCOME"] == "${{ steps.built.outcome }}"
    assert '"$BUILT_OUTCOME" != failure' in check["run"] and "::warning::Nothing deployed" in check["run"]
