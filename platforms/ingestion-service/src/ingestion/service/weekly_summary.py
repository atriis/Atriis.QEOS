"""Weekly summary (docs/superpowers/specs/2026-10-05-weekly-summary-design.md).

Last ISO week's numbers for one project (optionally one branch), and the message each channel
kind gets. Delivery reuses the failure notifications' `deliver` and its rules: no database
session is held across the HTTP or SMTP call.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.ingestion.core.config import settings
from src.ingestion.models import Run, RunResult
from src.ingestion.models.notification_channel import NotificationChannel
from src.ingestion.models.run import SUBSET_SCOPE
from src.ingestion.service.notification_service import FAILING, _test_label, deliver, record, stopped_after_stage_1

TOP_FAILING = 5


def previous_week(now: datetime) -> Tuple[datetime, datetime, str]:
    """[Monday 00:00, next Monday 00:00) UTC of the ISO week before `now`'s, and its label."""
    now = now.astimezone(timezone.utc)
    this_monday = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(days=now.weekday())
    start = this_monday - timedelta(days=7)
    year, week, _ = start.isocalendar()
    return start, this_monday, f"{year}-W{week:02d}"


@dataclass
class WeeklySummary:
    project_id: int
    label: str
    start: datetime
    end: datetime
    branch: Optional[str]
    runs: int = 0
    executions: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    previous_pass_rate: Optional[float] = None
    top_failing: List[dict] = field(default_factory=list)
    subset_runs: int = 0   # runs of only the suggested tests (spec 2026-10-13 §3.3; plan Ruling 17)
    stopped_runs: int = 0  # of those, the ones a failing stage 1 stopped

    @property
    def pass_rate(self) -> Optional[float]:
        return _rate(self.passed, self.executions - self.skipped)

    @property
    def link(self) -> Optional[str]:
        if not settings.DASHBOARD_URL:
            return None
        return f"{settings.DASHBOARD_URL.rstrip('/')}/projects/{self.project_id}/report"


def _rate(passed: int, counted: int) -> Optional[float]:
    return passed / counted if counted > 0 else None


def _totals(db: Session, project_id: int, start: datetime, end: datetime, branch: Optional[str]):
    query = db.query(
        func.count(Run.id), func.coalesce(func.sum(Run.total), 0), func.coalesce(func.sum(Run.passed), 0),
        func.coalesce(func.sum(Run.failed), 0), func.coalesce(func.sum(Run.errored), 0),
        func.coalesce(func.sum(Run.skipped), 0),
    ).filter(Run.project_id == project_id, Run.started_at >= start, Run.started_at < end)
    if branch is not None:
        query = query.filter(Run.branch == branch)
    return query.one()


def _subset_runs(db: Session, project_id: int, start: datetime, end: datetime,
                 branch: Optional[str]) -> Tuple[int, int]:
    """The week's runs of only the suggested tests, and how many of them a failing stage 1 stopped."""
    query = db.query(Run.stages).filter(Run.project_id == project_id, Run.started_at >= start, Run.started_at < end,
                                        Run.scope == SUBSET_SCOPE)
    if branch is not None:
        query = query.filter(Run.branch == branch)
    stages = [row[0] for row in query.all()]
    return len(stages), sum(1 for s in stages if stopped_after_stage_1(s))


def build(db: Session, project_id: int, now: datetime, branch: Optional[str]) -> WeeklySummary:
    start, end, label = previous_week(now)
    runs, total, passed, failed, errored, skipped = _totals(db, project_id, start, end, branch)
    s = WeeklySummary(project_id=project_id, label=label, start=start, end=end, branch=branch, runs=runs,
                      executions=total, passed=passed, failed=failed, errored=errored, skipped=skipped)
    _, p_total, p_passed, _, _, p_skipped = _totals(db, project_id, start - timedelta(days=7), start, branch)
    s.previous_pass_rate = _rate(p_passed, p_total - p_skipped)
    s.subset_runs, s.stopped_runs = _subset_runs(db, project_id, start, end, branch)

    failures = func.count(RunResult.id).label("failures")
    query = (
        db.query(RunResult.suite, RunResult.class_name, RunResult.name, failures)
        .join(Run, Run.id == RunResult.run_id)
        .filter(Run.project_id == project_id, Run.started_at >= start, Run.started_at < end,
                RunResult.status.in_(FAILING))
    )
    if branch is not None:
        query = query.filter(Run.branch == branch)
    rows = (query.group_by(RunResult.test_key, RunResult.suite, RunResult.class_name, RunResult.name)
            .order_by(failures.desc(), RunResult.name).limit(TOP_FAILING).all())
    s.top_failing = [{"suite": r.suite, "class_name": r.class_name, "name": r.name, "failures": r.failures}
                     for r in rows]
    return s


# --- messages ----------------------------------------------------------------------------

def _pct(rate: Optional[float]) -> str:
    return "—" if rate is None else f"{rate * 100:.0f}%"


def _headline(channel_name: str, s: WeeklySummary) -> str:
    if s.runs == 0:
        return f"{channel_name}: week {s.label}, no runs"
    return f"{channel_name}: week {s.label}, pass rate {_pct(s.pass_rate)}"


def _lines(s: WeeklySummary) -> List[str]:
    days = f"{s.start:%d %b} – {(s.end - timedelta(days=1)):%d %b %Y}"
    scope = f" on branch {s.branch}" if s.branch else ""
    if s.runs == 0:
        return [f"No runs were uploaded{scope} between {days}. If tests should have run, check the CI job."]
    lines = [
        f"{days}{scope}",
        f"Runs: {s.runs} · Test executions: {s.executions}",
    ]
    if s.subset_runs:
        stopped = f" ({s.stopped_runs} stopped after stage 1)" if s.stopped_runs else ""
        lines.append(f"Suggested tests only: {s.subset_runs} of {s.runs} runs{stopped}")
    lines += [
        f"Pass rate: {_pct(s.pass_rate)} (week before: {_pct(s.previous_pass_rate)})",
        f"Failed: {s.failed} · Errored: {s.errored} · Skipped: {s.skipped}",
    ]
    if s.top_failing:
        lines.append("Failed most often:")
        lines += [f"  - {_test_label(t)} ({t['failures']}×)" for t in s.top_failing]
    return lines


def slack_payload(channel_name: str, s: WeeklySummary) -> dict:
    lines = [f"*{_headline(channel_name, s)}*"] + _lines(s)
    if s.link:
        lines.append(f"<{s.link}|Open the report>")
    return {"text": _headline(channel_name, s),
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]}


def teams_payload(channel_name: str, s: WeeklySummary) -> dict:
    body = [{"type": "TextBlock", "text": _headline(channel_name, s), "weight": "Bolder", "size": "Medium", "wrap": True}]
    body += [{"type": "TextBlock", "text": line, "wrap": True, "spacing": "None"} for line in _lines(s)]
    actions = [{"type": "Action.OpenUrl", "title": "Open the report", "url": s.link}] if s.link else []
    card = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
            "version": "1.4", "body": body, "actions": actions}
    return {"type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}


def webhook_payload(channel_name: str, s: WeeklySummary) -> dict:
    return {
        "event": "weekly.summary", "channel": channel_name, "project_id": s.project_id, "week": s.label,
        "start": s.start.isoformat(), "end": s.end.isoformat(), "branch": s.branch, "runs": s.runs,
        "executions": s.executions, "passed": s.passed, "failed": s.failed, "errored": s.errored,
        "skipped": s.skipped, "pass_rate": s.pass_rate, "previous_pass_rate": s.previous_pass_rate,
        "top_failing": s.top_failing, "suggested_only_runs": s.subset_runs,
        "stopped_after_stage_1_runs": s.stopped_runs, "url": s.link,
    }


def email_payload(channel_name: str, s: WeeklySummary) -> dict:
    lines = [_headline(channel_name, s), ""] + _lines(s) + [""]
    if s.link:
        lines.append(f"Open the report: {s.link}")
    lines += ["", "You get this because the address is a notification channel of this project in QEOS,",
              "with the weekly summary switched on."]
    return {"subject": _headline(channel_name, s), "body": chr(10).join(lines)}


PAYLOADS = {"slack": slack_payload, "teams": teams_payload, "webhook": webhook_payload, "email": email_payload}


def send_now(db: Session, row: NotificationChannel, now: Optional[datetime] = None) -> Tuple[str, Optional[str]]:
    """Last week's summary on demand (Settings). Leaves the scheduled send untouched."""
    cid, name, kind, url = row.id, row.name, row.kind, row.url
    summary = build(db, row.project_id, now or datetime.now(timezone.utc), row.branch)
    db.rollback()  # no transaction open across the HTTP call
    outcome = deliver(kind, url, PAYLOADS[kind](name, summary))
    record(db, cid, outcome)
    db.commit()
    return outcome
