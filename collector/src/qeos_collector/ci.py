"""Run metadata from the CI system's environment variables."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Mapping, Optional
from urllib.parse import quote

# The server takes Idempotency-Keys up to 255 characters; this leaves room for "-part-N"
MAX_KEY_LENGTH = 200


@dataclass
class CIInfo:
    provider: str
    commit: Optional[str] = None
    branch: Optional[str] = None
    run_url: Optional[str] = None
    idempotency_key: Optional[str] = None
    pr_number: Optional[int] = None
    base_branch: Optional[str] = None
    trigger: Optional[str] = None


def detect(env: Mapping[str, str]) -> CIInfo:
    trigger = detect_trigger(env)

    def get(name: str) -> Optional[str]:
        return env.get(name, "").strip() or None

    if get("GITHUB_ACTIONS") == "true":
        server, repo, run_id = get("GITHUB_SERVER_URL"), get("GITHUB_REPOSITORY"), get("GITHUB_RUN_ID")
        return CIInfo(
            provider="github_actions",
            commit=get("GITHUB_SHA"),
            # On pull requests GITHUB_REF_NAME is "<number>/merge"; the head branch is the useful one
            branch=get("GITHUB_HEAD_REF") or get("GITHUB_REF_NAME"),
            # On a PR, GITHUB_REF_NAME is "<number>/merge"
            pr_number=_pr_from_ref(get("GITHUB_REF_NAME")) if get("GITHUB_HEAD_REF") else None,
            base_branch=get("GITHUB_BASE_REF"),
            run_url=f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else None,
            # A re-run attempt is a new execution, so it gets a new key on purpose
            idempotency_key=_key("gh", run_id, get("GITHUB_RUN_ATTEMPT") or "1", get("GITHUB_JOB")) if run_id else None,
            trigger=trigger,
        )
    if get("GITLAB_CI") == "true":
        job_id = get("CI_JOB_ID")
        return CIInfo(
            provider="gitlab_ci",
            commit=get("CI_COMMIT_SHA"),
            branch=get("CI_COMMIT_REF_NAME"),
            run_url=get("CI_JOB_URL"),
            idempotency_key=_key("gl", job_id) if job_id else None,
            trigger=trigger,
            pr_number=_int_or_none(get("CI_MERGE_REQUEST_IID")),
            base_branch=get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME"),
        )
    if (get("TF_BUILD") or "").lower() == "true":
        collection, team_project, build_id = get("SYSTEM_COLLECTIONURI"), get("SYSTEM_TEAMPROJECT"), get("BUILD_BUILDID")
        pull_request = get("BUILD_REASON") == "PullRequest"
        branch = _azure_branch(get("SYSTEM_PULLREQUEST_SOURCEBRANCH")) if pull_request else None
        return CIInfo(
            provider="azure_pipelines",
            commit=get("BUILD_SOURCEVERSION"),
            branch=branch or _azure_branch(get("BUILD_SOURCEBRANCH")) or get("BUILD_SOURCEBRANCHNAME"),
            run_url=(
                f"{collection.rstrip('/')}/{quote(team_project)}/_build/results?buildId={build_id}"
                if collection and team_project and build_id else None
            ),
            # For code on GitHub, the PR id is GitHub's internal one; the number is the visible one
            pr_number=_int_or_none(get("SYSTEM_PULLREQUEST_PULLREQUESTNUMBER") or get("SYSTEM_PULLREQUEST_PULLREQUESTID"))
            if pull_request else None,
            base_branch=_azure_branch(get("SYSTEM_PULLREQUEST_TARGETBRANCH")) if pull_request else None,
            # A retried job is a new execution, so it gets a new key on purpose
            idempotency_key=_key("az", build_id, get("SYSTEM_JOBATTEMPT") or "1", get("SYSTEM_JOBID")) if build_id else None,
            trigger=trigger,
        )
    if get("JENKINS_URL"):
        branch, tag = get("GIT_BRANCH"), get("BUILD_TAG")
        if branch and branch.startswith("origin/"):
            branch = branch[len("origin/"):]
        return CIInfo(
            provider="jenkins",
            commit=get("GIT_COMMIT"),
            branch=branch,
            run_url=get("BUILD_URL"),
            idempotency_key=_key("jk", tag) if tag else None,
            trigger=trigger,
        )
    return CIInfo(provider="local")


def sanitize_key(raw: str) -> Optional[str]:
    """Printable ASCII without spaces, at most MAX_KEY_LENGTH characters."""
    cleaned = "".join(c if "!" <= c <= "~" else "-" for c in raw)[:MAX_KEY_LENGTH]
    return cleaned or None


def _key(*parts: Optional[str]) -> Optional[str]:
    return sanitize_key("-".join(p for p in parts if p))


def _int_or_none(value: Optional[str]) -> Optional[int]:
    try:
        number = int(value or "")
        return number if number > 0 else None
    except ValueError:
        return None


def _azure_branch(ref: Optional[str]) -> Optional[str]:
    """refs/heads/feature/x -> feature/x. Azure Repos gives full refs, GitHub-hosted code plain
    names; a refs/pull/... merge ref is not a branch anyone works on."""
    if not ref:
        return None
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    return None if ref.startswith("refs/") else ref


def _pr_from_ref(ref_name: Optional[str]) -> Optional[int]:
    if ref_name and ref_name.endswith("/merge"):
        return _int_or_none(ref_name.split("/", 1)[0])
    return None


def _read_event(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _person(actor: Optional[str]) -> bool:
    return bool(actor) and not actor.endswith("[bot]")


def detect_trigger(env: Mapping[str, str], read_event: Callable[[str], dict] = _read_event) -> Optional[str]:
    """manual, automatic or qeos (ADR-030); None when the environment does not say."""
    def get(name: str) -> Optional[str]:
        return env.get(name, "").strip() or None

    if get("GITHUB_ACTIONS") == "true":
        event = get("GITHUB_EVENT_NAME")
        if event is None:
            return None
        actor = get("GITHUB_TRIGGERING_ACTOR") or get("GITHUB_ACTOR")
        if event == "workflow_dispatch":
            payload = read_event(get("GITHUB_EVENT_PATH") or "")
            inputs = payload.get("inputs")
            if isinstance(inputs, dict) and inputs.get("request_id"):
                return "qeos"
            return "manual" if _person(actor) else "automatic"
        attempt = _int_or_none(get("GITHUB_RUN_ATTEMPT")) or 1
        return "manual" if attempt > 1 and _person(actor) else "automatic"
    if get("GITLAB_CI") == "true":
        source = get("CI_PIPELINE_SOURCE")
        if source == "web" or get("CI_JOB_MANUAL") == "true":
            return "manual"
        return "automatic" if source else None
    if (get("TF_BUILD") or "").lower() == "true":
        reason = get("BUILD_REASON")
        return None if reason is None else ("manual" if reason == "Manual" else "automatic")
    if get("JENKINS_URL"):
        cause = (get("BUILD_CAUSE") or "").upper()
        if not cause:
            return None
        return "manual" if "MANUALTRIGGER" in cause or "USERIDCAUSE" in cause else "automatic"
    return None
