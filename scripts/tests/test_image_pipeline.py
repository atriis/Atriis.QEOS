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
