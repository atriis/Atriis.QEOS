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


def image_list() -> list[dict]:
    """deploy/images.txt, the one image list: "name context dockerfile" lines, # comments."""
    entries = []
    for line in (ROOT / "deploy" / "images.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            image, context, dockerfile = line.split()
            entries.append({"image": image, "context": context, "dockerfile": dockerfile})
    return entries


def test_the_image_list_is_every_image_the_chart_uses():
    built = [entry["image"] for entry in image_list()]
    assert len(built) == len(set(built)), f"an image appears twice in deploy/images.txt: {built}"
    assert set(built) == chart_images()


def test_ci_scan_matrix_matches_the_image_list():
    scan = load(WORKFLOWS / "ci.yml")["jobs"]["image-scan"]["strategy"]["matrix"]["include"]
    assert scan == image_list()


def test_every_listed_dockerfile_exists():
    for entry in image_list():
        assert (ROOT / entry["dockerfile"]).is_file(), entry


def test_the_workflows_read_the_image_list_and_list_no_image_themselves():
    # One source: the build matrix comes from the config job, the release and the deploy check read the file
    jobs = build_jobs()
    assert jobs["images"]["strategy"]["matrix"]["include"] == "${{ fromJSON(needs.config.outputs.images) }}"
    assert "deploy/images.txt" in step(jobs["config"], "Read the image list")["run"]
    release = step(jobs["release"], "Tag the images with the version")["run"]
    check = step(load(WORKFLOWS / "deploy-aks.yml")["jobs"]["deploy"], "Check that every image exists")["run"]
    for run in (release, check):
        assert "awk '!/^[[:space:]]*(#|$)/ {print $1}' deploy/images.txt" in run
    for name in ("build-platform.yml", "deploy-aks.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "test-management-service" not in text, f"{name} lists an image itself"


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
    assert release["if"].startswith("github.event_name == 'push' && github.ref_type == 'tag'")
    script = "\n".join(s.get("run", "") + s.get("uses", "") for s in release["steps"])
    for forbidden in ("docker build ", "docker push", "docker tag", "trivy", "az acr import"):
        assert forbidden not in script, forbidden
    run = step(release, "Tag the images with the version")["run"]
    # Without --prefer-index=false imagetools wraps a single image manifest in a new index: another digest
    assert 'docker buildx imagetools create --prefer-index=false --tag "$image:$VERSION" "$image@${want[$name]}"' in run
    assert "imagetools create --tag" not in run and run.count("--prefer-index=false") == 2
    # The dry-run check of every image comes before the first push
    assert run.index("--dry-run") < run.index("imagetools create --prefer-index=false --tag")


def test_build_runs_queue_and_the_azure_check_is_written_once():
    build = load(WORKFLOWS / "build-platform.yml")
    # Master's builds run one at a time, never cancelled
    assert build["concurrency"] == {
        "group": "build-platform-${{ github.event_name == 'workflow_run' && 'master' || github.ref }}",
        "cancel-in-progress": False,
    }
    text = (WORKFLOWS / "build-platform.yml").read_text(encoding="utf-8")
    assert text.count("Check that Azure is configured") == 1
    for job in ("images", "release"):
        assert build["jobs"][job]["needs"] == "config" and "needs.config.outputs.configured == 'true'" in build["jobs"][job]["if"]


def bash() -> str:
    found = shutil.which("bash")
    # Windows' System32\bash.exe is WSL, which does not see this environment's PATH
    if not found or "system32" in found.lower():
        pytest.skip("no bash")
    return found


def run_release(tmp_path: Path, registry: dict, **stub_env: str) -> tuple:
    """The release step's script against stub az, docker and jq over a registry of files {"name:tag": digest}.

    AZ_ERROR makes az fail as a sign-in would; WRAP_IMAGE makes imagetools plan another manifest for that image."""
    reg = tmp_path / "registry"
    reg.mkdir()
    for ref, digest in registry.items():
        (reg / ref.replace(":", "_")).write_text(digest)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    # az acr repository show --name ACR --image qeos/NAME:TAG --query digest -o tsv
    (stubs / "az").write_text(
        '#!/bin/sh\n[ -z "$AZ_ERROR" ] || { echo "ERROR: $AZ_ERROR" >&2; exit 1; }\n'
        'ref="${7#qeos/}"; f="$REG/$(echo "$ref" | tr : _)"\n'
        '[ -f "$f" ] || { echo "ERROR: manifest unknown: manifest tagged by $ref is not found" >&2; exit 1; }\n'
        'cat "$f"; echo\n', newline="\n")
    # docker buildx imagetools inspect --raw REG/qeos/NAME@DIGEST, and
    # docker buildx imagetools create --prefer-index=false [--dry-run] --tag REG/qeos/NAME:VERSION REG/qeos/NAME@DIGEST:
    # a copy keeps the digest; for WRAP_IMAGE the plan is another manifest
    (stubs / "docker").write_text(
        '#!/bin/sh\nlast=""; dry=""; dst=""; prev=""\n'
        'for a in "$@"; do [ "$a" = --dry-run ] && dry=1; [ "$prev" = --tag ] && dst="$a"; prev="$a"; last="$a"; done\n'
        'src="${last##*@}"; name="${last##*/qeos/}"; name="${name%@*}"\n'
        'if [ "$3" = inspect ]; then echo "{\\"manifest\\":\\"$src\\"}"; exit 0; fi\n'
        'if [ -n "$dry" ]; then\n'
        '  if [ "$name" = "$WRAP_IMAGE" ]; then echo "{\\"index\\":\\"$src\\"}"; else echo "{\\"manifest\\":\\"$src\\"}"; fi\n'
        '  exit 0\nfi\n'
        'echo "$*" >> "$REG/../docker.log"\n'
        'printf %s "$src" > "$REG/$(echo "${dst##*/qeos/}" | tr : _)"\n', newline="\n")
    # jq -S -c . on one-line JSON leaves it as it is (a developer's machine may have no jq)
    (stubs / "jq").write_text('#!/bin/sh\ncat\n', newline="\n")
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(step(build_jobs()["release"], "Tag the images with the version")["run"], newline="\n")
    env = dict(os.environ, PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}", REG=reg.as_posix(),
               ACR_NAME="acrqeos", SHA="a" * 40, VERSION="1.2.3", MSYS_NO_PATHCONV="1", AZ_ERROR="", WRAP_IMAGE="")
    env.update(stub_env)
    out = subprocess.run([bash(), "-e", script.as_posix()], env=env, capture_output=True, text=True, cwd=ROOT)
    after = {f.name.replace("_", ":", 1): f.read_text().strip() for f in reg.iterdir()}
    log = (tmp_path / "docker.log").read_text() if (tmp_path / "docker.log").exists() else ""
    return out, after, log


SHA = "a" * 40
IMAGES = [entry["image"] for entry in image_list()]


def test_release_gives_the_version_the_sha_images_digest(tmp_path):
    built = {f"{name}:{SHA}": f"sha256:{i:064x}" for i, name in enumerate(IMAGES)}
    out, after, log = run_release(tmp_path, built)
    assert out.returncode == 0, out.stdout + out.stderr
    for i, name in enumerate(IMAGES):
        assert after[f"{name}:1.2.3"] == after[f"{name}:{SHA}"] == f"sha256:{i:064x}"
    assert log.count("buildx imagetools create --prefer-index=false --tag") == 7


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


def test_release_tags_nothing_when_imagetools_would_change_a_digest(tmp_path):
    # Every image's planned manifest is checked before the first push: AcrPush cannot delete a wrong tag
    built = {f"{name}:{SHA}": f"sha256:{i:064x}" for i, name in enumerate(IMAGES)}
    out, after, log = run_release(tmp_path, built, WRAP_IMAGE="gateway")
    assert out.returncode != 0 and "would not copy qeos/gateway" in out.stdout
    assert log == "" and not any(ref.endswith(":1.2.3") for ref in after)


def test_release_prints_a_registry_error_rather_than_missing(tmp_path):
    built = {f"{name}:{SHA}": f"sha256:{i:064x}" for i, name in enumerate(IMAGES)}
    out, after, log = run_release(tmp_path, built, AZ_ERROR="unauthorized: authentication required")
    assert out.returncode != 0
    assert "::error::Could not read qeos/auth-service:" in out.stderr and "unauthorized" in out.stderr
    assert "Not in acrqeos" not in out.stdout and log == ""


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
    # One wait_idle, written once and sourced by both steps that edit the authorised ranges
    text = (WORKFLOWS / "deploy-aks.yml").read_text(encoding="utf-8")
    assert text.count("wait_idle() {") == 1
    for name in ("Allow this runner to reach the API server", "Remove this runner from the API server's ranges"):
        assert '. "$RUNNER_TEMP/aks-helpers.sh"' in step(job, name)["run"]
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


# ---- deploy-aks.yml's scripts, run against stubs ----

def deploy_step(name: str) -> str:
    return step(load(WORKFLOWS / "deploy-aks.yml")["jobs"]["deploy"], name)["run"]


def stub_bin(tmp_path: Path, **scripts: str) -> Path:
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    # Waits take no time in tests
    scripts.setdefault("sleep", "#!/bin/sh\nexit 0\n")
    for name, body in scripts.items():
        (stubs / name).write_text(body, newline="\n")
        (stubs / name).chmod(0o755)
    return stubs


def run_step(tmp_path: Path, run: str, stubs: Path, cwd: Path, **env: str) -> subprocess.CompletedProcess:
    script = tmp_path / "step.sh"
    script.write_text(run, newline="\n")
    output = tmp_path / "output"
    output.touch()
    full = dict(os.environ, PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}", GITHUB_OUTPUT=output.as_posix(),
                RUNNER_TEMP=tmp_path.as_posix(), MSYS_NO_PATHCONV="1")
    full.update(env)
    return subprocess.run([bash(), "-e", script.as_posix()], env=full, capture_output=True, text=True, cwd=cwd)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def history(tmp_path):
    """A repository with two commits on master: (repo, older sha, newer sha)."""
    if not shutil.which("git"):
        pytest.skip("no git")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    for n in (1, 2):
        (repo / "f").write_text(str(n))
        git(repo, "add", "f")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", f"c{n}")
    newer = git(repo, "rev-parse", "HEAD")
    return repo, git(repo, "rev-parse", "HEAD~1"), newer


def forward(tmp_path, history, deployed: str, ref: str, allow: str = "false", helm_fails: str = ""):
    repo = history[0]
    helm = ('#!/bin/sh\n[ -z "$HELM_FAILS" ] || { echo "$HELM_FAILS" >&2; exit 1; }\n'
            'echo "{\\"image\\":{\\"tag\\":\\"$DEPLOYED\\"}}"\n')
    stubs = stub_bin(tmp_path, helm=helm, jq="#!/bin/sh\nsed -n 's/.*\"tag\":\"\\([^\"]*\\)\".*/\\1/p'\n")
    out = run_step(tmp_path, deploy_step("Check that the deploy goes forward"), stubs, repo, DEPLOYED=deployed,
                   HELM_FAILS=helm_fails, TAG=ref, REF=ref, ALLOW_ROLLBACK=allow, ENVIRONMENT="staging", NAMESPACE="qeos")
    return out, (tmp_path / "output").read_text()


def test_an_older_build_never_rolls_the_environment_back(tmp_path, history):
    _, older, newer = history
    out, output = forward(tmp_path, history, deployed=newer, ref=older)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "deploy=false" in output and "::notice::Not deployed" in out.stdout


def test_a_manual_rollback_deploys_when_asked(tmp_path, history):
    _, older, newer = history
    out, output = forward(tmp_path, history, deployed=newer, ref=older, allow="true")
    assert out.returncode == 0 and "deploy=true" in output and "::warning::Rolling staging back" in out.stdout


@pytest.mark.parametrize("case", ["newer", "same", "first install"])
def test_newer_same_and_first_deploys_go_ahead(tmp_path, history, case):
    _, older, newer = history
    if case == "first install":
        out, output = forward(tmp_path, history, deployed="", ref=newer, helm_fails="Error: release: not found")
    else:
        out, output = forward(tmp_path, history, deployed=older if case == "newer" else newer, ref=newer)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "deploy=true" in output and "deploy=false" not in output


def test_an_unreadable_release_stops_the_deploy(tmp_path, history):
    _, _, newer = history
    out, output = forward(tmp_path, history, deployed="", ref=newer, helm_fails="Error: Kubernetes cluster unreachable")
    assert out.returncode != 0 and "Could not read the release's values" in out.stdout and "deploy=" not in output


def cleanup(tmp_path, az: str) -> subprocess.CompletedProcess:
    stubs = stub_bin(tmp_path, az=az)
    helpers = run_step(tmp_path, deploy_step("Write the cluster helpers"), stubs, tmp_path)
    assert helpers.returncode == 0, helpers.stderr
    return run_step(tmp_path, deploy_step("Remove this runner from the API server's ranges"), stubs, tmp_path,
                    RUNNER_IP="198.51.100.9", AKS_NAME="aks-qeos-staging", AKS_RESOURCE_GROUP="rg",
                    JOB_TIMEOUT_MINUTES="100", STATE=(tmp_path / "state").as_posix())


# az aks show: provisioningState, or the ranges; the first ranges read fails once (a transient error) when FLAKY is set
AZ_RANGES = """#!/bin/sh
case "$*" in
  *provisioningState*) echo Succeeded ;;
  *authorizedIpRanges*)
    if [ ! -e "$STATE.read" ]; then : > "$STATE.read"; echo "ERROR: (ServiceUnavailable) try again" >&2; exit 1; fi
    if [ -e "$STATE.removed" ]; then echo 203.0.113.7/32; else printf '203.0.113.7/32\n198.51.100.9/32\n'; fi ;;
  *update*) %s ;;
esac
"""


def test_cleanup_retries_a_failed_read_and_removes_the_address(tmp_path):
    out = cleanup(tmp_path, AZ_RANGES % ': > "$STATE.removed"; echo "$*" > "$STATE.update"')
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Could not read the authorised ranges, retrying" in out.stdout and "198.51.100.9/32 removed" in out.stdout
    assert "--api-server-authorized-ip-ranges 203.0.113.7/32 " in (tmp_path / "state.update").read_text() + " "


def test_every_cleanup_failure_says_to_remove_the_address_by_hand(tmp_path):
    out = cleanup(tmp_path, AZ_RANGES % 'echo "ERROR: (AuthorizationFailed) no" >&2; exit 1')
    assert out.returncode != 0
    assert "::error::198.51.100.9/32 may still be authorised on aks-qeos-staging: remove it by hand" in out.stdout
