"""The few GitHub REST calls Play and Stop need (run-from-QEOS spec, "GitHub client").

https://api.github.com only, never following redirects, 10 s timeout. The token goes in a header and
never into an exception, a message or a log line; httpx errors are replaced, not chained."""
import re
from datetime import datetime, timezone
from typing import NamedTuple, Optional

import httpx

API = "https://api.github.com"
TIMEOUT_SECONDS = 10.0
REPO = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
WORKFLOW = re.compile(r"^[A-Za-z0-9._-]{1,100}\.ya?ml$")
EXPIRY_HEADER = "github-authentication-token-expiration"

UNAUTHORIZED = "token invalid or expired"
FORBIDDEN = "token has no Actions access to this repository"
NOT_FOUND = ("repository or workflow not found. The workflow file must exist on the repository's "
             "default branch")


def forbidden(owner: str) -> str:
    """The 403 message, naming the account the token must belong to: a fine-grained token made under the
    user's own account (the default) cannot reach an organization's repository, which is the usual cause."""
    return (f"{FORBIDDEN}. Check that the token's resource owner is \"{owner}\" (the repository's owner, not your "
            f"own account unless you own it), that it can reach this repository with Actions: Read and write, and "
            f"that \"{owner}\" has approved it")


class GitHubError(Exception):
    """GitHub refused, or could not be reached (status 0)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class RateLimited(GitHubError):
    def __init__(self, retry_after: int):
        super().__init__(429, f"GitHub rate limit, try again in {retry_after} s")
        self.retry_after = retry_after


def _check_names(repo: str, workflow: Optional[str] = None) -> None:
    if not REPO.fullmatch(repo) or repo.split("/")[1] in (".", ".."):
        raise ValueError("repository name not allowed")
    if workflow is not None and not WORKFLOW.fullmatch(workflow):
        raise ValueError("workflow file name not allowed")


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=API, timeout=TIMEOUT_SECONDS, follow_redirects=False,
        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                 "Authorization": f"Bearer {token}", "User-Agent": "qeos-test-management"},
    )


def _retry_after(response: httpx.Response) -> Optional[int]:
    if response.status_code not in (403, 429):
        return None
    retry = response.headers.get("retry-after", "")
    if retry.isdigit():
        return max(1, int(retry))
    if response.headers.get("x-ratelimit-remaining") == "0":
        reset = response.headers.get("x-ratelimit-reset", "")
        if reset.isdigit():
            return max(1, int(reset) - int(datetime.now(timezone.utc).timestamp()))
        return 60
    if response.status_code == 429:  # GitHub sends no headers on some secondary limits
        return 60
    return None


def _send(token: str, method: str, path: str, **kwargs) -> httpx.Response:
    try:
        with _client(token) as client:
            response = client.request(method, path, **kwargs)
    except httpx.HTTPError:
        raise GitHubError(0, "GitHub could not be reached, try again") from None
    wait = _retry_after(response)
    if wait is not None:
        raise RateLimited(wait)
    if 300 <= response.status_code < 400:
        raise GitHubError(response.status_code, "GitHub answered with a redirect, which QEOS does not follow")
    if response.status_code == 401:
        raise GitHubError(401, UNAUTHORIZED)
    if response.status_code == 403:
        raise GitHubError(403, forbidden(path.split("/")[2]) if path.startswith("/repos/") else FORBIDDEN)
    if response.status_code == 404:
        raise GitHubError(404, NOT_FOUND)
    if response.status_code >= 400:
        raise GitHubError(response.status_code, f"GitHub answered {response.status_code}")
    return response


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        raise GitHubError(response.status_code, "GitHub answered with something that is not JSON") from None
    if not isinstance(body, dict):
        raise GitHubError(response.status_code, "GitHub answered with an unexpected body")
    return body


def parse_expiry(value: Optional[str]) -> Optional[datetime]:
    """GitHub sends e.g. '2027-03-12 00:00:00 UTC'; a numeric offset is read too; anything else is unknown."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip().replace(" UTC", " +0000"), "%Y-%m-%d %H:%M:%S %z").astimezone(timezone.utc)
    except ValueError:
        return None


def github_time(moment: datetime) -> str:
    """UTC with a Z: a '+00:00' offset would reach GitHub as a space inside the query."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _created(run: dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(run.get("created_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return None


def check_target(token: str, repo: str, workflow: str) -> Optional[datetime]:
    """The token can see the repository and the workflow file. Returns the token's expiry, if any."""
    _check_names(repo, workflow)
    response = _send(token, "GET", f"/repos/{repo}")
    _send(token, "GET", f"/repos/{repo}/actions/workflows/{workflow}")
    return parse_expiry(response.headers.get(EXPIRY_HEADER))


class DispatchResult(NamedTuple):
    run_id: int
    html_url: Optional[str]


def dispatch(token: str, repo: str, workflow: str, ref: str, inputs: dict) -> Optional[DispatchResult]:
    """Start the workflow. GitHub answers 200 with {workflow_run_id, run_url, html_url} when it returns run
    details; a 204, or a 200 without a usable id, gives None: the caller falls back to title matching."""
    _check_names(repo, workflow)
    response = _send(token, "POST", f"/repos/{repo}/actions/workflows/{workflow}/dispatches",
                     json={"ref": ref, "inputs": inputs, "return_run_details": True})
    if response.status_code != 200:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    run_id = body.get("workflow_run_id") if isinstance(body, dict) else None
    if type(run_id) is not int:  # bool is an int, and a string id is not trusted either
        return None
    html_url = body.get("html_url")
    return DispatchResult(run_id=run_id, html_url=html_url if isinstance(html_url, str) else None)


def find_run(token: str, repo: str, workflow: str, title: "str | tuple[str, ...]", since: datetime,
             exclude_ids: frozenset = frozenset()) -> Optional[dict]:
    """The oldest workflow_dispatch run of the workflow, created at or after `since`, whose display_title
    is exactly `title` (or one of several titles) and whose id no other request has claimed."""
    titles = (title,) if isinstance(title, str) else tuple(title)
    _check_names(repo, workflow)
    if since.tzinfo is None:  # naive datetimes (SQLite) are UTC
        since = since.replace(tzinfo=timezone.utc)
    response = _send(token, "GET", f"/repos/{repo}/actions/workflows/{workflow}/runs",
                     params={"event": "workflow_dispatch", "created": f">={github_time(since)}", "per_page": 100})
    runs = _json(response).get("workflow_runs") or []
    matches = []
    for run in runs:
        if not isinstance(run, dict) or run.get("display_title") not in titles:
            continue
        if run.get("event") != "workflow_dispatch" or run.get("id") in exclude_ids:
            continue
        created = _created(run)
        if created is not None and created < since:
            continue
        matches.append(run)
    return min(matches, key=lambda r: (_created(r) or since, r.get("id", 0))) if matches else None


BUSY_STATUSES = ("queued", "in_progress", "waiting", "pending", "requested")


def busy_run(token: str, repo: str, workflow: str, ref: str) -> Optional[dict]:
    """The newest run of the workflow on `ref` that has not finished, or None. GitHub filters by one status
    per call, so the newest 100 runs on the branch are read and filtered here: an unfinished run older than
    the last 100 cannot exist while the workflow's concurrency group holds."""
    _check_names(repo, workflow)
    response = _send(token, "GET", f"/repos/{repo}/actions/workflows/{workflow}/runs",
                     params={"branch": ref, "per_page": 100})
    runs = [run for run in _json(response).get("workflow_runs") or []
            if isinstance(run, dict) and run.get("status") in BUSY_STATUSES]
    return max(runs, key=lambda r: (_created(r) or datetime.min.replace(tzinfo=timezone.utc), r.get("id", 0))) \
        if runs else None


def get_run(token: str, repo: str, run_id: int) -> dict:
    _check_names(repo)
    return _json(_send(token, "GET", f"/repos/{repo}/actions/runs/{int(run_id)}"))


def cancel_run(token: str, repo: str, run_id: int) -> None:
    _check_names(repo)
    _send(token, "POST", f"/repos/{repo}/actions/runs/{int(run_id)}/cancel")
