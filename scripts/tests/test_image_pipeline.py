"""build-platform.yml pushes the images the Helm chart pulls (ADR-038), and listens to the workflow that is called CI.

A service added to the chart without a matrix entry would deploy an image nobody pushed; a renamed CI workflow would
stop the build without an error.
"""
from pathlib import Path

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
