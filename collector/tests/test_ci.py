import json

import pytest

from qeos_collector.ci import CIInfo, detect, detect_trigger, sanitize_key

GITHUB = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_SHA": "a" * 40,
    "GITHUB_REF_NAME": "main",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "acme/shop",
    "GITHUB_RUN_ID": "123",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_JOB": "test",
}


def test_github_actions():
    assert detect(GITHUB) == CIInfo(
        provider="github_actions",
        commit="a" * 40,
        branch="main",
        run_url="https://github.com/acme/shop/actions/runs/123",
        idempotency_key="gh-123-2-test",
    )


def test_github_pull_request_uses_the_head_branch():
    info = detect({**GITHUB, "GITHUB_REF_NAME": "42/merge", "GITHUB_HEAD_REF": "feature/cart"})
    assert info.branch == "feature/cart"


def test_github_without_a_run_id_has_no_key_and_no_run_url():
    env = dict(GITHUB)
    del env["GITHUB_RUN_ID"]
    info = detect(env)
    assert info.provider == "github_actions"
    assert info.idempotency_key is None and info.run_url is None


def test_github_attempt_defaults_to_1():
    env = dict(GITHUB)
    del env["GITHUB_RUN_ATTEMPT"]
    assert detect(env).idempotency_key == "gh-123-1-test"


def test_gitlab_ci():
    env = {
        "GITLAB_CI": "true",
        "CI_COMMIT_SHA": "b" * 40,
        "CI_COMMIT_REF_NAME": "develop",
        "CI_JOB_URL": "https://gitlab.com/acme/shop/-/jobs/77",
        "CI_JOB_ID": "77",
    }
    assert detect(env) == CIInfo(
        provider="gitlab_ci",
        commit="b" * 40,
        branch="develop",
        run_url="https://gitlab.com/acme/shop/-/jobs/77",
        idempotency_key="gl-77",
    )


def test_jenkins_strips_origin_and_sanitises_the_build_tag():
    env = {
        "JENKINS_URL": "https://ci.acme.test/",
        "GIT_COMMIT": "c" * 40,
        "GIT_BRANCH": "origin/release/1.2",
        "BUILD_URL": "https://ci.acme.test/job/shop/12/",
        "BUILD_TAG": "jenkins-shop tests-12",
    }
    assert detect(env) == CIInfo(
        provider="jenkins",
        commit="c" * 40,
        branch="release/1.2",
        run_url="https://ci.acme.test/job/shop/12/",
        idempotency_key="jk-jenkins-shop-tests-12",
    )


def test_no_ci_is_local():
    assert detect({}) == CIInfo(provider="local")
    assert detect({"GITHUB_ACTIONS": "false", "GITLAB_CI": ""}) == CIInfo(provider="local")


def test_blank_variables_count_as_missing():
    assert detect({**GITHUB, "GITHUB_SHA": "  ", "GITHUB_HEAD_REF": ""}).commit is None
    assert detect({**GITHUB, "GITHUB_HEAD_REF": ""}).branch == "main"


def test_sanitize_key():
    assert sanitize_key("a bé\n") == "a-b--"
    assert sanitize_key("x" * 300) == "x" * 200
    assert sanitize_key("") is None


def test_github_pull_request_number_and_base():
    env = {"GITHUB_ACTIONS": "true", "GITHUB_SERVER_URL": "https://github.com",
           "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "9", "GITHUB_SHA": "abc",
           "GITHUB_HEAD_REF": "feature-x", "GITHUB_REF_NAME": "123/merge",
           "GITHUB_BASE_REF": "main"}
    info = detect(env)
    assert info.pr_number == 123
    assert info.base_branch == "main"


def test_github_push_has_no_pr():
    env = {"GITHUB_ACTIONS": "true", "GITHUB_REF_NAME": "main", "GITHUB_SHA": "abc"}
    info = detect(env)
    assert info.pr_number is None and info.base_branch is None


def test_gitlab_merge_request_number_and_base():
    env = {"GITLAB_CI": "true", "CI_JOB_ID": "7", "CI_COMMIT_SHA": "abc",
           "CI_COMMIT_REF_NAME": "feature", "CI_MERGE_REQUEST_IID": "45",
           "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop"}
    info = detect(env)
    assert info.pr_number == 45
    assert info.base_branch == "develop"


AZURE = {
    "TF_BUILD": "True",
    "BUILD_SOURCEVERSION": "c" * 40,
    "BUILD_SOURCEBRANCH": "refs/heads/main",
    "BUILD_SOURCEBRANCHNAME": "main",
    "SYSTEM_COLLECTIONURI": "https://dev.azure.com/acme/",
    "SYSTEM_TEAMPROJECT": "Shop QA",
    "BUILD_BUILDID": "321",
    "SYSTEM_JOBID": "12f1170f-54f2-53f3-20dd-22fc7dff55f9",
    "SYSTEM_JOBATTEMPT": "1",
}


def test_azure_pipelines():
    assert detect(AZURE) == CIInfo(
        provider="azure_pipelines",
        commit="c" * 40,
        branch="main",
        # The team project name may hold spaces: it is a path segment, so it is encoded
        run_url="https://dev.azure.com/acme/Shop%20QA/_build/results?buildId=321",
        idempotency_key="az-321-1-12f1170f-54f2-53f3-20dd-22fc7dff55f9",
    )


def test_azure_branch_keeps_its_slashes():
    assert detect({**AZURE, "BUILD_SOURCEBRANCH": "refs/heads/feature/cart"}).branch == "feature/cart"


def test_azure_pull_request_uses_the_source_branch_number_and_target():
    info = detect({
        **AZURE,
        "BUILD_REASON": "PullRequest",
        "BUILD_SOURCEBRANCH": "refs/pull/42/merge",
        "SYSTEM_PULLREQUEST_SOURCEBRANCH": "refs/heads/feature/cart",
        "SYSTEM_PULLREQUEST_TARGETBRANCH": "refs/heads/main",
        "SYSTEM_PULLREQUEST_PULLREQUESTID": "42",
    })
    assert (info.branch, info.pr_number, info.base_branch) == ("feature/cart", 42, "main")


def test_azure_pull_request_from_a_github_repository_uses_the_pr_number():
    # For GitHub-hosted code the id is GitHub's internal one; the number is what people see
    info = detect({
        **AZURE,
        "BUILD_REASON": "PullRequest",
        "SYSTEM_PULLREQUEST_SOURCEBRANCH": "feature/cart",
        "SYSTEM_PULLREQUEST_TARGETBRANCH": "main",
        "SYSTEM_PULLREQUEST_PULLREQUESTID": "1789012345",
        "SYSTEM_PULLREQUEST_PULLREQUESTNUMBER": "7",
    })
    assert (info.branch, info.pr_number, info.base_branch) == ("feature/cart", 7, "main")


def test_azure_job_retry_gets_a_new_key():
    assert detect({**AZURE, "SYSTEM_JOBATTEMPT": "2"}).idempotency_key.startswith("az-321-2-")


def test_azure_without_a_build_id_has_no_key_and_no_url():
    info = detect({k: v for k, v in AZURE.items() if k != "BUILD_BUILDID"})
    assert info.run_url is None and info.idempotency_key is None


GH = {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "1", "GITHUB_REPOSITORY": "acme/obt",
      "GITHUB_SERVER_URL": "https://github.com"}


def gh(**extra):
    return {**GH, **extra}


@pytest.mark.parametrize("env, event, expected", [
    (gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="octocat"), {}, "manual"),
    (gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="github-actions[bot]"), {}, "automatic"),
    (gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="octocat"),
     {"inputs": {"request_id": "42"}}, "qeos"),
    (gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_ACTOR="octocat"), {}, "manual"),  # no TRIGGERING_ACTOR
    (gh(GITHUB_EVENT_NAME="schedule", GITHUB_RUN_ATTEMPT="2", GITHUB_TRIGGERING_ACTOR="octocat"), {}, "manual"),
    (gh(GITHUB_EVENT_NAME="schedule", GITHUB_RUN_ATTEMPT="2", GITHUB_TRIGGERING_ACTOR="renovate[bot]"), {}, "automatic"),
    (gh(GITHUB_EVENT_NAME="push", GITHUB_RUN_ATTEMPT="1", GITHUB_TRIGGERING_ACTOR="octocat"), {}, "automatic"),
    (gh(GITHUB_EVENT_NAME="schedule"), {}, "automatic"),
    (gh(GITHUB_EVENT_NAME="repository_dispatch", GITHUB_TRIGGERING_ACTOR="octocat"), {}, "automatic"),
    (gh(), {}, None),  # no event name: unknown
    ({"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "web"}, {}, "manual"),
    ({"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "push", "CI_JOB_MANUAL": "true"}, {}, "manual"),
    ({"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "schedule"}, {}, "automatic"),
    ({"GITLAB_CI": "true"}, {}, None),
    ({"TF_BUILD": "True", "BUILD_REASON": "Manual"}, {}, "manual"),
    ({"TF_BUILD": "True", "BUILD_REASON": "IndividualCI"}, {}, "automatic"),
    ({"JENKINS_URL": "https://ci.example", "BUILD_CAUSE": "MANUALTRIGGER"}, {}, "manual"),
    ({"JENKINS_URL": "https://ci.example", "BUILD_CAUSE": "USERIDCAUSE"}, {}, "manual"),
    ({"JENKINS_URL": "https://ci.example", "BUILD_CAUSE": "TIMERTRIGGER"}, {}, "automatic"),
    ({"JENKINS_URL": "https://ci.example"}, {}, None),
    ({}, {}, None),
])
def test_trigger_classification(env, event, expected):
    assert detect_trigger(env, read_event=lambda _path: event) == expected


def test_detect_fills_trigger(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"request_id": "7"}}), encoding="utf-8")
    env = gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="octocat", GITHUB_EVENT_PATH=str(event))
    assert detect(env).trigger == "qeos"


@pytest.mark.parametrize("content", [None, "not json", "[1, 2]", '{"inputs": "x"}'])
def test_unreadable_event_payload_is_not_qeos(tmp_path, content):
    env = gh(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_TRIGGERING_ACTOR="octocat")
    if content is not None:
        (tmp_path / "e.json").write_text(content, encoding="utf-8")
        env["GITHUB_EVENT_PATH"] = str(tmp_path / "e.json")
    else:
        env["GITHUB_EVENT_PATH"] = str(tmp_path / "missing.json")
    assert detect(env).trigger == "manual"
