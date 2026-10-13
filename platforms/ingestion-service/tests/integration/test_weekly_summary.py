"""Weekly summary: last ISO week's numbers on channels that ask for it, once per week."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.core.config import settings
from src.ingestion.jobs import weekly_summary as job
from src.ingestion.models import Run, RunResult
from src.ingestion.models.notification_channel import NotificationChannel
from src.ingestion.models.run import FULL_SCOPE, SUBSET_SCOPE
from src.ingestion.service import notification_service, weekly_summary
from src.ingestion.utils import notify_targets

SLACK = "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXXXXXXabcd"
HOOK = "https://alerts.example.com/qa"
URL = "/api/v1/projects/1/notification-channels"
# Monday 2026-10-05; last week is 2026-W40, Mon 09-28 .. Mon 10-05
MONDAY = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
LAST_WEEK = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
WEEK_BEFORE = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(notify_targets, "resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(settings, "DASHBOARD_URL", "https://qeos.example.com")
    monkeypatch.setattr(settings, "WEEKLY_SUMMARY_HOUR_UTC", 7)


@pytest.fixture
def session_factory(db):
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)


@pytest.fixture
def add_run(db, make_key):
    key_row, _ = make_key(project_id=1)

    def _add(when, results, project_id=1, branch="main", scope=FULL_SCOPE, stages=None):
        statuses = [s for _, s in results]
        run = Run(project_id=project_id, api_key_id=key_row.id, request_hash="h", ci_provider="local",
                  branch=branch, scope=scope, stages=stages, started_at=when, finished_at=when + timedelta(minutes=1), duration_ms=60000,
                  total=len(statuses), passed=statuses.count("passed"), failed=statuses.count("failed"),
                  skipped=statuses.count("skipped"), errored=statuses.count("errored"), created_at=when)
        db.add(run)
        db.flush()
        for name, status in results:
            db.add(RunResult(run_id=run.id, test_key=name.ljust(64, "0")[:64], suite="checkout", class_name="Cart",
                             name=name, status=status, duration_ms=1))
        db.commit()
        return run

    return _add


def channel(db, **values):
    row = NotificationChannel(**{"project_id": 1, "name": "QA", "kind": "slack", "url": SLACK, "enabled": True,
                                 "weekly_summary": True, **values})
    db.add(row)
    db.commit()
    return row


# --- the numbers ---------------------------------------------------------------------------

def test_previous_iso_week_bounds_and_label():
    start, end, label = weekly_summary.previous_week(MONDAY)
    assert (start, end, label) == (datetime(2026, 9, 28, tzinfo=timezone.utc), datetime(2026, 10, 5, tzinfo=timezone.utc), "2026-W40")
    # Any day of a week points at the week before it
    assert weekly_summary.previous_week(datetime(2026, 10, 11, 23, 59, tzinfo=timezone.utc))[2] == "2026-W40"


def test_summary_counts_last_week_only_and_compares_with_the_week_before(db, add_run):
    add_run(LAST_WEEK, [("a", "passed"), ("b", "failed"), ("c", "skipped")])
    add_run(LAST_WEEK + timedelta(days=1), [("a", "passed"), ("b", "failed"), ("d", "errored")])
    add_run(WEEK_BEFORE, [("a", "passed"), ("b", "passed")])
    add_run(MONDAY, [("a", "failed")])                       # this week: not counted
    add_run(LAST_WEEK, [("x", "failed")], project_id=2)      # other project: not counted

    s = weekly_summary.build(db, 1, MONDAY, branch=None)
    assert (s.label, s.runs, s.executions, s.failed, s.errored, s.skipped) == ("2026-W40", 2, 6, 2, 1, 1)
    assert s.pass_rate == pytest.approx(2 / 5)
    assert s.previous_pass_rate == pytest.approx(1.0)
    assert [(t["name"], t["failures"]) for t in s.top_failing] == [("b", 2), ("d", 1)]
    assert s.link == "https://qeos.example.com/projects/1/report"


def test_summary_honours_the_channel_branch(db, add_run):
    add_run(LAST_WEEK, [("a", "failed")], branch="main")
    add_run(LAST_WEEK, [("a", "passed")], branch="feature/x")
    s = weekly_summary.build(db, 1, MONDAY, branch="feature/x")
    assert (s.runs, s.failed, s.pass_rate) == (1, 0, 1.0)


def test_top_failing_lists_five_at_most(db, add_run):
    add_run(LAST_WEEK, [(f"t{i}", "failed") for i in range(8)])
    assert len(weekly_summary.build(db, 1, MONDAY, branch=None).top_failing) == 5


# --- messages ------------------------------------------------------------------------------

def test_payloads_for_every_kind(db, add_run):
    add_run(LAST_WEEK, [("a", "passed"), ("b", "failed")])
    s = weekly_summary.build(db, 1, MONDAY, branch=None)
    slack = json.dumps(weekly_summary.PAYLOADS["slack"]("QA", s), ensure_ascii=False)
    assert "QA: week 2026-W40" in slack and "50%" in slack and "checkout › Cart › b" in slack
    assert "https://qeos.example.com/projects/1/report" in slack
    teams = weekly_summary.PAYLOADS["teams"]("QA", s)
    assert teams["attachments"][0]["content"]["type"] == "AdaptiveCard"
    hook = weekly_summary.PAYLOADS["webhook"]("QA", s)
    assert hook["event"] == "weekly.summary" and hook["week"] == "2026-W40" and hook["runs"] == 1
    mail = weekly_summary.PAYLOADS["email"]("QA", s)
    assert mail["subject"].startswith("QA: week 2026-W40") and "Pass rate: 50%" in mail["body"]


def test_a_quiet_week_still_says_so(db):
    s = weekly_summary.build(db, 1, MONDAY, branch=None)
    assert s.runs == 0 and s.pass_rate is None
    assert "No runs" in weekly_summary.PAYLOADS["email"]("QA", s)["body"]


# --- the job -------------------------------------------------------------------------------

def test_the_job_sends_once_per_week_to_channels_that_ask(db, add_run, session_factory, http):
    add_run(LAST_WEEK, [("a", "failed")])
    channel(db)
    channel(db, name="alerts only", url=HOOK, kind="webhook", weekly_summary=False)
    channel(db, name="off", url=HOOK + "/off", kind="webhook", enabled=False)
    slack = http.post(SLACK).mock(return_value=httpx.Response(200, text="ok"))
    other = http.post(url__startswith=HOOK).mock(return_value=httpx.Response(200))

    assert job.run_pass(session_factory, lambda: MONDAY) == {"event": "weekly_summary", "week": "2026-W40", "sent": 1, "failed": 0}
    assert job.run_pass(session_factory, lambda: MONDAY + timedelta(hours=3))["sent"] == 0   # already sent
    assert slack.call_count == 1 and other.call_count == 0
    db.expire_all()
    row = db.query(NotificationChannel).filter_by(name="QA").one()
    assert (row.last_weekly_week, row.last_status) == ("2026-W40", "delivered")


def test_the_job_waits_for_the_configured_hour_on_monday(db, add_run, session_factory, http):
    channel(db)
    route = http.post(SLACK).mock(return_value=httpx.Response(200))
    early = MONDAY.replace(hour=6, minute=59)
    assert job.run_pass(session_factory, lambda: early)["sent"] == 0
    # Missed Monday (job was down): still sent later in the week
    assert job.run_pass(session_factory, lambda: MONDAY + timedelta(days=2))["sent"] == 1
    assert route.call_count == 1


def test_a_failed_delivery_is_recorded_and_not_retried_that_week(db, session_factory, http):
    channel(db)
    route = http.post(SLACK).mock(return_value=httpx.Response(500))
    assert job.run_pass(session_factory, lambda: MONDAY)["failed"] == 1
    assert job.run_pass(session_factory, lambda: MONDAY + timedelta(hours=1))["sent"] == 0
    assert route.call_count == 1
    db.expire_all()
    row = db.query(NotificationChannel).one()
    assert row.last_status == "failed" and "500" in row.last_error and row.last_weekly_week == "2026-W40"


def test_failure_alerts_can_be_switched_off_per_channel(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db, on_failure=False)
    route = http.post(SLACK).mock(return_value=httpx.Response(200))
    now = datetime.now(timezone.utc)
    body = {"run": {"ci_provider": "local", "started_at": (now - timedelta(seconds=5)).isoformat(),
                    "finished_at": now.isoformat()},
            "results": [{"name": "t", "status": "failed", "duration_ms": 1}]}
    assert client.post("/api/v1/collect/runs", json=body, headers={"Authorization": f"Bearer {key}"}).status_code == 201
    assert route.call_count == 0


# --- the API -------------------------------------------------------------------------------

def test_channels_expose_and_change_both_switches(client, auth, project_role):
    project_role(role="member", project_id=1)
    created = client.post(URL, json={"name": "QA", "kind": "slack", "url": SLACK, "weekly_summary": True,
                                     "on_failure": False}, headers=auth())
    assert created.status_code == 201, created.text
    assert (created.json()["weekly_summary"], created.json()["on_failure"]) == (True, False)
    cid = created.json()["id"]
    changed = client.patch(f"{URL}/{cid}", json={"weekly_summary": False, "on_failure": True}, headers=auth()).json()
    assert (changed["weekly_summary"], changed["on_failure"]) == (False, True)
    # Defaults keep today's behaviour
    plain = client.post(URL, json={"name": "B", "kind": "slack", "url": SLACK}, headers=auth()).json()
    assert (plain["weekly_summary"], plain["on_failure"]) == (False, True)


def test_send_last_weeks_summary_on_demand(client, auth, project_role, db, add_run, http, monkeypatch):
    project_role(role="member", project_id=1)
    add_run(datetime.now(timezone.utc) - timedelta(days=7), [("a", "failed")])
    row = channel(db, weekly_summary=False)
    route = http.post(SLACK).mock(return_value=httpx.Response(200))
    response = client.post(f"{URL}/{row.id}/test?message=weekly", headers=auth())
    assert response.status_code == 200 and response.json()["status"] == "delivered"
    assert "week" in json.loads(route.calls.last.request.content)["text"]
    db.expire_all()
    assert db.get(NotificationChannel, row.id).last_weekly_week is None   # on demand never blocks the scheduled send


def test_unknown_test_message_is_422(client, auth, project_role, db):
    project_role(role="member", project_id=1)
    row = channel(db)
    assert client.post(f"{URL}/{row.id}/test?message=daily", headers=auth()).status_code == 422


def test_runs_that_ran_only_suggested_tests_are_labelled(db, add_run):
    one_stage = {"stages": [{"name": "suggested", "duration_s": 60.0, "tests": 1, "failed": 1}],
                 "time_to_first_failure_s": 5.0}
    add_run(LAST_WEEK, [("a", "passed")])
    add_run(LAST_WEEK, [("b", "failed")], scope=SUBSET_SCOPE, stages={**one_stage, "stopped_after_stage": 1})
    add_run(LAST_WEEK, [("c", "passed")], scope=SUBSET_SCOPE, stages={**one_stage, "time_to_first_failure_s": None})
    add_run(LAST_WEEK, [("d", "passed")], branch="other", scope=SUBSET_SCOPE, stages=one_stage)
    s = weekly_summary.build(db, 1, MONDAY, branch="main")
    assert (s.runs, s.subset_runs, s.stopped_runs) == (3, 2, 1)  # the other branch's run is not this summary's
    assert s.pass_rate == pytest.approx(2 / 3)  # subset runs still count in the pass rate (spec §3.1)
    slack = json.dumps(weekly_summary.PAYLOADS["slack"]("QA", s), ensure_ascii=False)
    assert "Suggested tests only: 2 of 3 runs (1 stopped after stage 1)" in slack
    hook = weekly_summary.PAYLOADS["webhook"]("QA", s)
    assert (hook["suggested_only_runs"], hook["stopped_after_stage_1_runs"]) == (2, 1)


def test_a_week_of_full_runs_has_no_label(db, add_run):
    add_run(LAST_WEEK, [("a", "passed")])
    s = weekly_summary.build(db, 1, MONDAY, branch=None)
    assert s.subset_runs == 0
    assert "Suggested tests only" not in "\n".join(weekly_summary._lines(s))
    assert weekly_summary.PAYLOADS["webhook"]("QA", s)["suggested_only_runs"] == 0
