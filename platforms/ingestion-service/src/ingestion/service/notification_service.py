"""Failure notifications (docs/superpowers/specs/2026-10-05-failure-notifications-design.md).

Delivery never holds a database session open across the HTTP call: data is read, the session
is released, messages are sent, and the outcomes are written in a new short transaction.
"""
import logging
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

import httpx
from qeos_shared.mail import MailNotConfigured, send_mail
from sqlalchemy.orm import Session

from src.ingestion.core.config import settings
from src.ingestion.models import Run, RunResult
from src.ingestion.models.notification_channel import NotificationChannel
from src.ingestion.models.run import FULL_SCOPE, SUBSET_SCOPE
from src.ingestion.service import run_service
from src.ingestion.utils import notify_targets

logger = logging.getLogger(__name__)

MAX_CHANNELS_PER_PROJECT = 10
MAX_LISTED_FAILURES = 5
FAILING = ("failed", "errored")


# --- channels ----------------------------------------------------------------------------

def list_channels(db: Session, project_id: int) -> List[NotificationChannel]:
    return db.query(NotificationChannel).filter_by(project_id=project_id).order_by(NotificationChannel.id).all()


def add_channel(db: Session, project_id: int, name: str, kind: str, url: str, branch: Optional[str],
                user_id: int, on_failure: bool = True, weekly_summary: bool = False) -> NotificationChannel:
    url = notify_targets.validate_target(kind, url)  # ValueError -> 422
    if db.query(NotificationChannel).filter_by(project_id=project_id).count() >= MAX_CHANNELS_PER_PROJECT:
        raise ValueError(f"A project has at most {MAX_CHANNELS_PER_PROJECT} notification channels")
    row = NotificationChannel(project_id=project_id, name=name, kind=kind, url=url, branch=branch or None,
                              enabled=True, on_failure=on_failure, weekly_summary=weekly_summary,
                              created_by_user_id=user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_channel(db: Session, project_id: int, channel_id: int) -> Optional[NotificationChannel]:
    return db.query(NotificationChannel).filter_by(project_id=project_id, id=channel_id).first()


def update_channel(db: Session, row: NotificationChannel, changes: dict) -> NotificationChannel:
    for key in ("name", "enabled", "branch", "on_failure", "weekly_summary"):
        if key in changes:
            value = changes[key]
            setattr(row, key, (value or None) if key == "branch" else value)
    db.commit()
    db.refresh(row)
    return row


def delete_channel(db: Session, row: NotificationChannel) -> None:
    db.delete(row)
    db.commit()


# --- messages ----------------------------------------------------------------------------

def stopped_after_stage_1(stages: Optional[dict]) -> bool:
    """run-impact's --fail-fast stopped the run after a failing stage 1 (spec 2026-10-13 §3.1)."""
    return isinstance(stages, dict) and stages.get("stopped_after_stage") == 1


def scope_label(scope: Optional[str], stages: Optional[dict]) -> Optional[str]:
    """How a run that ran only part of its suite is named in messages (spec 2026-10-13 §3.3), so it is never read as a
    full verdict; None for a full run."""
    if scope != SUBSET_SCOPE:
        return None
    if stopped_after_stage_1(stages):
        return "Suggested tests only, stopped after stage 1"
    return "Suggested tests only"


@dataclass
class RunSummary:
    project_id: int
    run_id: Optional[int]
    total: int
    failed: int
    errored: int
    branch: Optional[str]
    commit_sha: Optional[str]
    commit_message: Optional[str]
    ci_run_url: Optional[str]
    failures: List[dict] = field(default_factory=list)
    test: bool = False
    quarantined: int = 0  # failures of quarantined tests: mentioned, not counted
    scope: str = FULL_SCOPE
    stages: Optional[dict] = None

    @property
    def partial(self) -> Optional[str]:
        return scope_label(self.scope, self.stages)

    @property
    def broken(self) -> int:
        return self.failed + self.errored - self.quarantined

    @property
    def link(self) -> Optional[str]:
        if not settings.DASHBOARD_URL or self.run_id is None:
            return None
        return f"{settings.DASHBOARD_URL.rstrip('/')}/projects/{self.project_id}/runs/{self.run_id}"


def _test_label(failure: dict) -> str:
    return " › ".join(part for part in (failure["suite"], failure["class_name"], failure["name"]) if part)


def _headline(channel_name: str, s: RunSummary) -> str:
    if s.test:
        return f"{channel_name}: QEOS test message. This channel is set up correctly."
    headline = f"{channel_name}: {s.broken} of {s.total} tests failed"
    return f"{headline} · {s.partial}" if s.partial else headline


def _context(s: RunSummary) -> str:
    bits = []
    if s.branch:
        bits.append(f"branch {s.branch}")
    if s.commit_sha:
        bits.append(f"commit {s.commit_sha[:7]}" + (f" ({s.commit_message})" if s.commit_message else ""))
    if s.quarantined:
        bits.append(f"{s.quarantined} quarantined, not counted")
    return " · ".join(bits)


def slack_payload(channel_name: str, s: RunSummary) -> dict:
    lines = [f"*{_headline(channel_name, s)}*"]
    if _context(s):
        lines.append(_context(s))
    lines += [f"• {_test_label(f)}" for f in s.failures]
    if s.broken > len(s.failures) and s.failures:
        lines.append(f"… and {s.broken - len(s.failures)} more")
    links = [f"<{s.link}|Open in QEOS>"] if s.link else []
    if s.ci_run_url:
        links.append(f"<{s.ci_run_url}|CI job>")
    if links:
        lines.append(" · ".join(links))
    return {"text": _headline(channel_name, s), "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]}


def teams_payload(channel_name: str, s: RunSummary) -> dict:
    body = [{"type": "TextBlock", "text": _headline(channel_name, s), "weight": "Bolder", "size": "Medium", "wrap": True}]
    if _context(s):
        body.append({"type": "TextBlock", "text": _context(s), "isSubtle": True, "wrap": True})
    for f in s.failures:
        body.append({"type": "TextBlock", "text": f"- {_test_label(f)}", "wrap": True, "spacing": "None"})
    if s.broken > len(s.failures) and s.failures:
        body.append({"type": "TextBlock", "text": f"… and {s.broken - len(s.failures)} more", "isSubtle": True})
    actions = []
    if s.link:
        actions.append({"type": "Action.OpenUrl", "title": "Open in QEOS", "url": s.link})
    if s.ci_run_url:
        actions.append({"type": "Action.OpenUrl", "title": "CI job", "url": s.ci_run_url})
    card = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
            "version": "1.4", "body": body, "actions": actions}
    return {"type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}


def webhook_payload(channel_name: str, s: RunSummary) -> dict:
    return {
        "event": "test" if s.test else "run.failed",
        "channel": channel_name,
        "project_id": s.project_id,
        "run": {"id": s.run_id, "total": s.total, "failed": s.failed, "errored": s.errored,
                "branch": s.branch, "commit_sha": s.commit_sha, "commit_message": s.commit_message,
                "ci_run_url": s.ci_run_url, "url": s.link,
                "scope": s.scope, "stopped_after_stage": 1 if stopped_after_stage_1(s.stages) else None},
        "failures": s.failures,
    }


def email_payload(channel_name: str, s: RunSummary) -> dict:
    lines = [_headline(channel_name, s), ""]
    if _context(s):
        lines += [_context(s), ""]
    if s.failures:
        lines.append("Failing tests:")
        lines += [f"  - {_test_label(f)}" for f in s.failures]
        if s.broken > len(s.failures):
            lines.append(f"  … and {s.broken - len(s.failures)} more")
        lines.append("")
    if s.link:
        lines.append(f"Open in QEOS: {s.link}")
    if s.ci_run_url:
        lines.append(f"CI job: {s.ci_run_url}")
    lines += ["", "You get this because the address is a notification channel of this project in QEOS."]
    return {"subject": _headline(channel_name, s), "body": chr(10).join(lines)}


PAYLOADS = {"slack": slack_payload, "teams": teams_payload, "webhook": webhook_payload, "email": email_payload}


# --- delivery ----------------------------------------------------------------------------

def deliver(kind: str, url: str, payload: dict) -> Tuple[str, Optional[str]]:
    """("delivered", None) or ("failed", reason). Never raises."""
    if kind == "email":
        try:
            send_mail(settings, notify_targets.recipients(url), payload["subject"], payload["body"])
        except MailNotConfigured as exc:
            return "failed", str(exc)
        except (smtplib.SMTPException, OSError) as exc:
            return "failed", f"{type(exc).__name__}: {exc}"
        return "delivered", None
    try:
        notify_targets.check_resolves_publicly(url)
        response = httpx.post(url, json=payload, timeout=settings.NOTIFY_TIMEOUT_SECONDS, follow_redirects=False)
    except ValueError as exc:
        return "failed", str(exc)
    except httpx.HTTPError as exc:
        return "failed", f"{type(exc).__name__}: {exc}"
    if 200 <= response.status_code < 300:
        return "delivered", None
    return "failed", f"The endpoint answered {response.status_code}"


def record(db: Session, channel_id: int, outcome: Tuple[str, Optional[str]]) -> None:
    row = db.get(NotificationChannel, channel_id)
    if row is None:  # removed while the message was in flight
        return
    row.last_status, error = outcome
    row.last_error = error[:500] if error else None
    row.last_sent_at = datetime.now(timezone.utc)


def _summary(db: Session, run: Run, held: set, quarantined: int) -> RunSummary:
    query = db.query(RunResult.suite, RunResult.class_name, RunResult.name, RunResult.status, RunResult.message).filter(
        RunResult.run_id == run.id, RunResult.status.in_(FAILING))
    if held:
        query = query.filter(RunResult.test_key.notin_(held))
    failures = query.order_by(RunResult.id).limit(MAX_LISTED_FAILURES).all()
    return RunSummary(
        project_id=run.project_id, run_id=run.id, total=run.total, failed=run.failed, errored=run.errored,
        branch=run.branch, commit_sha=run.commit_sha, commit_message=run.commit_message, ci_run_url=run.ci_run_url,
        failures=[{"suite": f.suite, "class_name": f.class_name, "name": f.name, "status": f.status,
                   "message": (f.message or "")[:300] or None} for f in failures],
        quarantined=quarantined, scope=run.scope, stages=run.stages,
    )


def notify_run(session_factory: Callable[[], Session], run_id: int) -> None:
    """Background task after a run is stored: announce it on every matching channel."""
    try:
        with session_factory() as db:
            run = db.get(Run, run_id)
            if run is None or run.failed + run.errored == 0:
                return
            held = run_service.quarantined_failures(db, run)
            counts = run_service.quarantine_counts(db, run, held)
            if counts["blocking"] == 0:  # only quarantined tests failed: nothing to announce
                return
            summary = _summary(db, run, held, counts["quarantined"])
            targets = [
                (c.id, c.name, c.kind, c.url)
                for c in list_channels(db, run.project_id)
                if c.enabled and c.on_failure and (c.branch is None or c.branch == run.branch)
            ]
        if not targets:
            return
        outcomes = [(cid, deliver(kind, url, PAYLOADS[kind](name, summary))) for cid, name, kind, url in targets]
        with session_factory() as db:
            for cid, outcome in outcomes:
                record(db, cid, outcome)
            db.commit()
    except Exception:  # a background task has nobody to raise to: log it
        logger.exception("failure notification for run %s could not be completed", run_id)


def send_test(db: Session, row: NotificationChannel) -> Tuple[str, Optional[str]]:
    cid, name, kind, url, project_id = row.id, row.name, row.kind, row.url, row.project_id
    db.rollback()  # no transaction open across the HTTP call
    sample = RunSummary(project_id=project_id, run_id=None, total=0, failed=0, errored=0, branch=None,
                        commit_sha=None, commit_message=None, ci_run_url=None, test=True)
    outcome = deliver(kind, url, PAYLOADS[kind](name, sample))
    record(db, cid, outcome)
    db.commit()
    return outcome
