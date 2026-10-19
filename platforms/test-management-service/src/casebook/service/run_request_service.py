"""Play: a run request dispatches the project's CI workflow; GETs refresh it from GitHub (no worker)."""
import json
from datetime import datetime, timedelta, timezone
from typing import List, NamedTuple, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.casebook.models import Case, CiTarget, RunRequest, Suite, SuiteCase
from src.casebook.models.ci import ACTIVE_STATUSES
from src.casebook.service.case_service import case_key
from src.casebook.utils import github_client, secret_box

THROTTLE = timedelta(seconds=5)
START_TIMEOUT = timedelta(minutes=2)
MATCH_WINDOW = timedelta(minutes=1)
MAX_CASES = 200
MAX_INPUT_CHARS = 65000  # GitHub refuses workflow_dispatch inputs over 65 535 characters in total
NOT_STARTED = "The workflow did not start"
RUN_GONE = "The run is no longer on GitHub"
AMBIGUOUS_START = "GitHub did not confirm the start; checking…"
QUEUED_ON_GITHUB = ("queued", "waiting", "requested", "pending")
RUN_URL_PREFIX = "https://github.com/"


class NoTarget(Exception):
    """The project has no CI target."""


class BadSelection(Exception):
    """The selection cannot run; the message names the case numbers."""


class SuiteNotFound(Exception):
    pass


class AlreadyFinished(Exception):
    """Stop on a request that is no longer active."""


class RunActive(Exception):
    def __init__(self, request_id: Optional[int], label: Optional[str] = None):
        super().__init__(f"A run of {label} is in progress" if label else "A run is in progress")
        self.request_id = request_id
        self.label = label


class WorkflowBusy(Exception):
    """GitHub already runs (or queues) the repository workflow: a dispatch would race its concurrency group."""

    def __init__(self, group_name: str, run_url: Optional[str], started_at: Optional[datetime]):
        started = f" (started {started_at.astimezone(timezone.utc):%H:%M})" if started_at else ""
        super().__init__(f"{group_name} is already running on GitHub{started}. Try again when it finishes.")
        self.group_name, self.run_url, self.started_at = group_name, run_url, started_at


class GitHubUnavailable(Exception):
    """GitHub could not be asked whether the workflow is running: QEOS does not dispatch blind."""

    def __init__(self, group_name: str, retry_after: Optional[int] = None):
        super().__init__(f"GitHub could not be asked whether {group_name} is running; try again.")
        self.group_name, self.retry_after = group_name, retry_after


class RepositoryNotTarget(Exception):
    """The repository suite was synced from another repository than the CI target's."""

    def __init__(self, source_repo: str):
        super().__init__(f"Set up Run from QEOS in Project Settings for {source_repo}")
        self.source_repo = source_repo


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(moment: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands DateTime(timezone=True) back naive; every time stored here is UTC."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=timezone.utc)


def run_title(request_id: int) -> str:
    return f"QEOS #{request_id}"


def run_titles(request_id: int) -> tuple:
    """The run-name the workflow template sets, then the one workflows copied before the QEOS
    rename still set, so their runs keep matching."""
    return run_title(request_id), f"QA Vision #{request_id}"


def _keys(numbers: List[int]) -> str:
    return ", ".join(case_key(n) for n in numbers)


def _numbers(db: Session, project_id: int, case_numbers: Optional[List[int]], suite_id: Optional[int]) -> List[int]:
    if suite_id is None:
        return list(dict.fromkeys(case_numbers or []))
    suite = db.query(Suite).filter(Suite.project_id == project_id, Suite.id == suite_id).one_or_none()
    if suite is None:
        raise SuiteNotFound()
    rows = (db.query(Case.number).join(SuiteCase, SuiteCase.case_id == Case.id)
            .filter(SuiteCase.suite_id == suite.id).order_by(SuiteCase.position).all())
    return [r.number for r in rows]


def build_selection(db: Session, project_id: int, case_numbers: Optional[List[int]],
                    suite_id: Optional[int]) -> Tuple[List[dict], int]:
    """The cases to run and how many manual ones were left out. A whole suite skips its manual cases (it
    mixes both kinds by design); an explicit selection rejects them, so a click is never silently dropped."""
    numbers = _numbers(db, project_id, case_numbers, suite_id)
    if not numbers:
        raise BadSelection("Nothing to run: the suite has no cases")
    found = {c.number: c for c in db.query(Case).filter(Case.project_id == project_id, Case.number.in_(numbers))}
    manual = [n for n in numbers if n in found and not found[n].source_path]
    skipped = 0
    if suite_id is not None:
        skipped = len(manual)
        numbers = [n for n in numbers if n not in manual]
        manual = []
        if not numbers:
            raise BadSelection("This suite has no automated cases")
    if len(numbers) > MAX_CASES:
        raise BadSelection(f"At most {MAX_CASES} cases per run; this selection has {len(numbers)}")
    unknown = [n for n in numbers if n not in found]
    archived = [n for n in numbers if n in found and found[n].source_path and found[n].status == "archived"]
    unnamed = [n for n in numbers if n in found and found[n].source_path and found[n].status != "archived"
               and not found[n].scenario_name]
    problems = []
    if unknown:
        problems.append(f"No such case: {_keys(unknown)}")
    if manual:
        problems.append(f"Manual cases cannot run: {_keys(manual)}")
    if archived:
        problems.append(f"Archived cases cannot run: {_keys(archived)}")
    if unnamed:
        problems.append(f"{_keys(unnamed)}: re-import the .feature files first")
    if problems:
        raise BadSelection(". ".join(problems))
    return [{"case_number": n, "path": found[n].source_path, "name": found[n].scenario_name} for n in numbers], skipped


def dispatch_inputs(request_id: int, selection: List[dict]) -> dict:
    """paths: a JSON array of the files, once each (a path may contain a space); names: a JSON array of
    the raw scenario names; request_id: the row id, which the workflow puts in its run-name."""
    paths = list(dict.fromkeys(item["path"] for item in selection))
    return {"paths": json.dumps(paths, ensure_ascii=False),
            "names": json.dumps([item["name"] for item in selection], ensure_ascii=False),
            "request_id": str(request_id)}


def _target_and_token(db: Session, project_id: int) -> Tuple[CiTarget, str]:
    target = db.get(CiTarget, project_id)
    if target is None:
        raise NoTarget()
    return target, secret_box.decrypt(target.token_encrypted)


def active_request(db: Session, project_id: int, workflow: Optional[str] = None) -> Optional[RunRequest]:
    """The active request of one workflow (the index allows one), or with no workflow the project's oldest."""
    query = db.query(RunRequest).filter(RunRequest.project_id == project_id, RunRequest.status.in_(ACTIVE_STATUSES))
    if workflow is not None:
        return query.filter(RunRequest.workflow == workflow).one_or_none()
    return query.order_by(RunRequest.id).first()


def active_requests(db: Session, project_id: int) -> List[RunRequest]:
    return db.query(RunRequest).filter(
        RunRequest.project_id == project_id, RunRequest.status.in_(ACTIVE_STATUSES)).order_by(RunRequest.id).all()


def _pending_cancel(row: RunRequest, at: datetime) -> bool:
    """Stopped before GitHub listed its run: keep looking for 2 minutes, so it is cancelled there too."""
    return (row.status == "cancelled" and row.github_run_id is None and row.stopped_at is not None
            and at - aware(row.requested_at) < START_TIMEOUT)


def needs_refresh(row: RunRequest, at: datetime) -> bool:
    return row.status in ACTIVE_STATUSES or _pending_cancel(row, at)


def _claimed(db: Session, project_id: int, own_id: int) -> frozenset:
    rows = db.query(RunRequest.github_run_id).filter(
        RunRequest.project_id == project_id, RunRequest.id != own_id, RunRequest.github_run_id.isnot(None)).all()
    return frozenset(r[0] for r in rows)


def safe_run_url(url: Optional[str]) -> Optional[str]:
    """Only a github.com page is stored, so the dashboard never renders an untrusted link."""
    return url if isinstance(url, str) and url.startswith(RUN_URL_PREFIX) else None


def _match(row: RunRequest, repo: str, workflow: str, token: str, claimed: frozenset) -> Optional[dict]:
    """The 204 fallback only: GitHub gave no run details at dispatch, so find the run by its title."""
    run = github_client.find_run(token, repo, workflow, run_titles(row.id), aware(row.requested_at) - MATCH_WINDOW,
                                 claimed)
    if run is not None:
        row.github_run_id = int(run["id"])
        row.github_run_url = safe_run_url(run.get("html_url"))
    return run


def _map_status(row: RunRequest, run: dict) -> None:
    status, conclusion = run.get("status"), run.get("conclusion")
    if status == "completed":
        row.conclusion = str(conclusion)[:30] if conclusion else None
        row.status = "cancelled" if conclusion == "cancelled" else "completed"
    elif row.status == "cancelling":
        return  # stays cancelling until GitHub reports the run completed
    elif status == "in_progress":
        row.status = "running"
    elif status in QUEUED_ON_GITHUB:
        row.status = "queued"


def _apply_github(row: RunRequest, repo: str, workflow: str, token: str, claimed: frozenset, at: datetime) -> None:
    """Asks GitHub and records the answer on `row`, a detached copy: no database is touched here."""
    if _pending_cancel(row, at):
        try:
            found = _match(row, repo, workflow, token, claimed)
        except github_client.GitHubError:
            return  # GitHub cannot be asked now: the next GET tries again, within the 2 minutes
        if found is not None:
            try:
                github_client.cancel_run(token, repo, row.github_run_id)
            except github_client.GitHubError as exc:
                if exc.status not in (404, 409):  # 404/409: it is gone or already ended, nothing left to cancel
                    raise
        return
    if row.github_run_id is None:
        expired = at - aware(row.requested_at) >= START_TIMEOUT
        try:
            run = _match(row, repo, workflow, token, claimed)
        except github_client.GitHubError as exc:
            # GitHub cannot be asked: wait, but a permanent refusal must not hold the slot for ever
            if expired:
                row.status, row.error = "failed_to_start", f"{NOT_STARTED}: {exc.message}"[:500]
            else:
                row.error = exc.message[:500]
            return
        if run is None:
            if expired:
                row.status, row.error = "failed_to_start", NOT_STARTED
            else:
                row.error = None
            return
        row.error = None
    else:
        try:
            run = github_client.get_run(token, repo, row.github_run_id)
        except github_client.GitHubError as exc:
            if exc.status == 404:  # the run (or its repository) is gone: nothing left to wait for
                row.status, row.error = "cancelled", RUN_GONE
                return
            raise
        row.error = None
    _map_status(row, run)


CHANGEABLE = ("status", "conclusion", "github_run_id", "github_run_url", "error")
REFRESH_PER_LIST = 3  # GitHub calls are slow: a list GET refreshes a few rows, the next poll the rest


def _due(row: RunRequest, at: datetime, force: bool = False) -> bool:
    if not needs_refresh(row, at):
        return False
    checked = aware(row.checked_at)
    return force or checked is None or at - checked >= THROTTLE


def refresh(db: Session, row: RunRequest, force: bool = False) -> RunRequest:
    """Bring a request up to date with GitHub, at most every 5 s unless forced. A GitHub failure (rate
    limit, outage) or an unreadable token leaves the state as it was; checked_at still moves, so a failing
    GitHub is not asked on every GET.

    GitHub is asked with no transaction open, on a detached copy of the row. The result is written with
    `UPDATE ... WHERE status = <the status read>`, so a Stop or another refresh that got in first is never
    overwritten (a cancelling request is never turned back into running)."""
    at = now()
    if not _due(row, at, force):
        return row
    target = db.get(CiTarget, row.project_id)
    if target is None:
        return row
    rid, repo, workflow, encrypted = row.id, target.repo, row.workflow or target.workflow, target.token_encrypted
    before = {name: getattr(row, name) for name in CHANGEABLE}
    work = RunRequest(id=rid, project_id=row.project_id, requested_at=row.requested_at, stopped_at=row.stopped_at,
                      **before)
    claimed = _claimed(db, row.project_id, rid) if row.github_run_id is None else frozenset()
    db.commit()  # the read transaction ends here
    changes = {}
    try:
        _apply_github(work, repo, workflow, secret_box.decrypt(encrypted), claimed, at)
        changes = {name: getattr(work, name) for name in CHANGEABLE if getattr(work, name) != before[name]}
    except (github_client.GitHubError, secret_box.SecretsUnavailable) as exc:
        # A known run we cannot read (token revoked, GitHub down): keep its status, say why it is stale
        if isinstance(exc, github_client.GitHubError) and before["github_run_id"] is not None:
            changes = {"error": exc.message[:500]}
    db.query(RunRequest).filter(RunRequest.id == rid, RunRequest.status == before["status"]).update(
        {**changes, "checked_at": at}, synchronize_session=False)
    try:
        db.commit()
    except IntegrityError:  # another Play closed this row and started a new one meanwhile
        db.rollback()
    db.refresh(row)
    return row


class RepositoryRun(NamedTuple):
    """A run of repository suites: their own workflow, the leg's suite id (blank: the whole workflow)."""
    workflow: str
    suites_input: str
    group_name: str
    suites: List[Suite]


def _repository_run(db: Session, project_id: int, suite_id: Optional[int],
                    workflow_group: Optional[str]) -> Optional[RepositoryRun]:
    """None for a hand-made suite or a case selection. The workflow dispatched is always one a synced suite
    row names, never the request's own text (a workflow_group must match such a row)."""
    if workflow_group is not None:
        suites = (db.query(Suite).filter(Suite.project_id == project_id, Suite.origin == "repository",
                                         Suite.workflow == workflow_group).order_by(Suite.id).all())
        if not suites:
            raise SuiteNotFound()
        return RepositoryRun(suites[0].workflow, "", suites[0].group_name or suites[0].workflow, suites)
    if suite_id is None:
        return None
    suite = db.query(Suite).filter(Suite.project_id == project_id, Suite.id == suite_id).one_or_none()
    if suite is None:
        raise SuiteNotFound()
    if suite.origin != "repository":
        return None
    return RepositoryRun(suite.workflow, suite.external_id or "", suite.group_name or suite.workflow, [suite])


def _members(db: Session, suites: List[Suite]) -> List[dict]:
    """QEOS's view of the suites' membership, by suite then position, each case once. The workflow runs its
    folders whatever QEOS thinks of the cases, so none of build_selection's checks apply."""
    selection, seen = [], set()
    for suite in suites:
        cases = (db.query(Case).join(SuiteCase, SuiteCase.case_id == Case.id)
                 .filter(SuiteCase.suite_id == suite.id).order_by(SuiteCase.position).all())
        for case in cases:
            if case.number not in seen:
                seen.add(case.number)
                selection.append({"case_number": case.number, "key": case_key(case.number),
                                  "path": case.source_path, "name": case.scenario_name})
    return selection


def _check_repository(target: CiTarget, run: RepositoryRun) -> None:
    """A suite synced without GITHUB_REPOSITORY (source_repo null) runs against the CI target as it is."""
    for suite in run.suites:
        if suite.source_repo and suite.source_repo.lower() != target.repo.lower():
            raise RepositoryNotTarget(suite.source_repo)


def _check_not_busy(target: CiTarget, token: str, run: RepositoryRun) -> None:
    """A dispatch while the workflow runs or waits would let its concurrency group cancel one of the two."""
    try:
        busy = github_client.busy_run(token, target.repo, run.workflow, target.ref)
    except github_client.RateLimited as exc:
        raise GitHubUnavailable(run.group_name, exc.retry_after) from None
    except github_client.GitHubError:
        raise GitHubUnavailable(run.group_name) from None
    if busy is None:
        return
    started = busy.get("run_started_at") or busy.get("created_at")
    try:
        started_at = datetime.fromisoformat(str(started).replace("Z", "+00:00")) if started else None
    except ValueError:
        started_at = None
    raise WorkflowBusy(run.group_name, safe_run_url(busy.get("html_url")), aware(started_at))


def create(db: Session, project_id: int, user_id: int, case_numbers: Optional[List[int]],
           suite_id: Optional[int], estimate_ms: Optional[int] = None,
           estimate_upper_ms: Optional[int] = None, workflow_group: Optional[str] = None) -> RunRequest:
    target, token = _target_and_token(db, project_id)
    repository = _repository_run(db, project_id, suite_id, workflow_group)
    if repository is None:
        selection, skipped_manual = build_selection(db, project_id, case_numbers, suite_id)
        preview = dispatch_inputs(0, selection)
        if len(preview["paths"]) + len(preview["names"]) + 20 > MAX_INPUT_CHARS:
            raise BadSelection("This selection is too large for one GitHub dispatch: select fewer cases")
        workflow, label = target.workflow, target.workflow
    else:
        _check_repository(target, repository)
        selection, skipped_manual = _members(db, repository.suites), 0
        workflow, label = repository.workflow, repository.group_name
    active = active_request(db, project_id, workflow)
    if active is not None:
        refresh(db, active, force=True)  # a run that ended while nobody looked must not block Play
        if active.status in ACTIVE_STATUSES:
            raise RunActive(active.id, label)
    if repository is not None:
        _check_not_busy(target, token, repository)  # before the row exists: a refusal holds no slot
    row = RunRequest(project_id=project_id, requested_by=user_id, requested_at=now(), selection=selection,
                     suite_id=suite_id, status="queued", skipped_manual=skipped_manual, workflow=workflow,
                     estimate_ms=estimate_ms, estimate_upper_ms=estimate_upper_ms)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise RunActive(None, label)  # another Play committed first (the partial unique index)
    db.refresh(row)
    if repository is None:
        inputs = dispatch_inputs(row.id, selection)
    else:
        inputs = {"suites": repository.suites_input, "request_id": str(row.id)}
    try:
        started = github_client.dispatch(token, target.repo, workflow, target.ref, inputs)
    except github_client.RateLimited:
        db.delete(row)
        db.commit()
        raise
    except github_client.GitHubError as exc:
        if exc.status == 0 or exc.status >= 500:
            # a timeout or a 5xx may still have started a run: the title match settles it
            row.error = AMBIGUOUS_START
            db.commit()
            return row
        row.status, row.error = "failed_to_start", exc.message[:500]
        db.commit()
        return row
    if started is not None:  # 200 with run details: Stop and polling work on this run at once
        row.github_run_id = started.run_id
        row.github_run_url = safe_run_url(started.html_url)
        db.commit()
    # On None (a 204), the row keeps no run id: polling matches it by title (the fallback)
    return row


def list_requests(db: Session, project_id: int, limit: int, offset: int) -> Tuple[int, List[RunRequest]]:
    query = db.query(RunRequest).filter(RunRequest.project_id == project_id)
    total = query.count()
    rows = query.order_by(RunRequest.requested_at.desc(), RunRequest.id.desc()).offset(offset).limit(limit).all()
    at = now()
    never = datetime.min.replace(tzinfo=timezone.utc)
    due = sorted((r for r in rows if _due(r, at)), key=lambda r: aware(r.checked_at) or never)
    for row in due[:REFRESH_PER_LIST]:  # least recently asked first, so no row starves
        refresh(db, row)
    return total, rows


def get_request(db: Session, project_id: int, request_id: int) -> Optional[RunRequest]:
    row = db.query(RunRequest).filter(RunRequest.project_id == project_id, RunRequest.id == request_id).one_or_none()
    return refresh(db, row) if row is not None else None


def out(row: RunRequest) -> dict:
    selection = row.selection or []
    return {
        "id": row.id, "requested_by": row.requested_by, "requested_at": aware(row.requested_at),
        "selection": selection, "case_count": len(selection), "suite_id": row.suite_id, "workflow": row.workflow,
        "status": row.status,
        "conclusion": row.conclusion, "github_run_id": row.github_run_id, "github_run_url": row.github_run_url,
        "stopped_by": row.stopped_by, "stopped_at": aware(row.stopped_at), "error": row.error,
        "checked_at": aware(row.checked_at), "skipped_manual": row.skipped_manual or 0,
        "estimate_ms": row.estimate_ms, "estimate_upper_ms": row.estimate_upper_ms, "refreshing": needs_refresh(row, now()),
    }


ACTIVE_STOPPABLE = ("queued", "running")


def _stopped(db: Session, row: RunRequest, user_id: int, at: datetime, **changes) -> RunRequest:
    """Write the stop only while the request is still queued or running, so a refresh that saw the run end
    (or another Stop) in between is never overwritten. A lost race: 409, or the row as the other Stop left it."""
    done = db.query(RunRequest).filter(
        RunRequest.id == row.id, RunRequest.status.in_(ACTIVE_STOPPABLE)).update(
        {"stopped_by": user_id, "stopped_at": at, **changes}, synchronize_session=False)
    db.commit()
    db.refresh(row)
    if not done and row.status != "cancelling":
        raise AlreadyFinished()
    return row


def stop(db: Session, row: RunRequest, user_id: int) -> RunRequest:
    """Cancel on GitHub and mark cancelling. The run id normally came with Play (a 200 dispatch); only
    after a 204 can a request still have none: it is cancelled locally, then on GitHub once a GET matches
    it (for 2 minutes after the request, then it is left alone)."""
    if row.status == "cancelling":
        return row  # already stopping: keep who stopped it first
    if row.status not in ACTIVE_STATUSES:
        raise AlreadyFinished()
    at = now()
    if row.github_run_id is None:
        return _stopped(db, row, user_id, at, status="cancelled")
    target, token = _target_and_token(db, row.project_id)
    try:
        github_client.cancel_run(token, target.repo, row.github_run_id)
    except github_client.RateLimited:
        raise  # nothing changes; the caller answers 503 with Retry-After
    except github_client.GitHubError as exc:
        if exc.status == 409:  # the run ended just now
            refresh(db, row, force=True)
            raise AlreadyFinished()
        if exc.status == 404:  # GitHub no longer knows the run: there is nothing left to stop
            return _stopped(db, row, user_id, at, status="cancelled", error=RUN_GONE)
        db.rollback()
        row.error = exc.message[:500]
        db.commit()
        raise
    return _stopped(db, row, user_id, at, status="cancelling")


MAX_RUN_URLS = 5000
RUN_URLS_MAX_AGE_DAYS = 500  # a previous report period reaches 491 days back (spec Ruling 5)


def run_urls(db: Session, project_id: int, since: datetime) -> tuple:
    """GitHub run URLs (html_url) of the project's Play requests made since `since`, newest first;
    (urls, truncated)."""
    rows = db.execute(
        select(RunRequest.github_run_url)
        .where(RunRequest.project_id == project_id, RunRequest.requested_at >= since,
               RunRequest.github_run_url.is_not(None))
        .order_by(RunRequest.requested_at.desc(), RunRequest.id.desc())
        .limit(MAX_RUN_URLS + 1)
    ).all()
    urls = [url for (url,) in rows]
    return urls[:MAX_RUN_URLS], len(urls) > MAX_RUN_URLS
