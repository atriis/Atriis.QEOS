"""Failure notifications: channels per project, a message when a run with failures is stored."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.ingestion.core.config import settings
from src.ingestion.models.notification_channel import NotificationChannel
from src.ingestion.models.run import SUBSET_SCOPE
from src.ingestion.service import notification_service
from src.ingestion.utils import notify_targets

URL = "/api/v1/projects/1/notification-channels"
SLACK = "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXXXXXXabcd"
TEAMS = "https://prod-12.westeurope.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=s3cr3t"
HOOK = "https://alerts.example.com/qa"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(notify_targets, "resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(settings, "DASHBOARD_URL", "https://qeos.example.com")


@pytest.fixture
def member(project_role):
    project_role(role="member", project_id=1)


def add(client, auth, **body):
    payload = {"name": "QA Test Automation", "kind": "slack", "url": SLACK, **body}
    return client.post(URL, json=payload, headers=auth())


def upload(failed=1, branch="main", **run):
    now = datetime.now(timezone.utc)
    results = [{"suite": "checkout", "class_name": "Cart", "name": f"case {i}", "status": "failed",
                "duration_ms": 1, "message": "expected 1, password=hunter2"} for i in range(failed)]
    results.append({"suite": "checkout", "class_name": "Cart", "name": "ok", "status": "passed", "duration_ms": 1})
    meta = {"ci_provider": "github_actions", "branch": branch, "commit_sha": "3f2a9c1deadbeef",
            "started_at": (now - timedelta(seconds=30)).isoformat(), "finished_at": now.isoformat(), **run}
    return {"run": meta, "results": results}


def send(client, key, body, idem=None):
    headers = {"Authorization": f"Bearer {key}"}
    if idem:
        headers["Idempotency-Key"] = idem
    return client.post("/api/v1/collect/runs", json=body, headers=headers)


def channel(db, **values):
    row = NotificationChannel(**{"project_id": 1, "name": "QA", "kind": "slack", "url": SLACK, "enabled": True, **values})
    db.add(row)
    db.commit()
    return row


# --- managing channels ---------------------------------------------------------------------

def test_a_member_adds_a_channel_and_never_sees_the_url_again(client, auth, member):
    created = add(client, auth)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["target"] == "hooks.slack.com/…abcd"
    assert "url" not in body and SLACK not in created.text
    listed = client.get(URL, headers=auth())
    assert SLACK not in listed.text and listed.json()[0]["kind"] == "slack"


def test_a_refused_url_says_why(client, auth, member):
    response = add(client, auth, kind="webhook", url="https://10.0.0.1/hook")
    assert response.status_code == 422
    assert "public" in response.json()["detail"]


def test_viewers_read_but_cannot_change(client, auth, project_role):
    project_role(role="viewer", project_id=1)
    assert client.get(URL, headers=auth()).status_code == 200
    assert add(client, auth).status_code == 403


def test_disable_change_branch_and_remove(client, auth, member):
    cid = add(client, auth).json()["id"]
    patched = client.patch(f"{URL}/{cid}", json={"enabled": False, "branch": "main"}, headers=auth())
    assert patched.status_code == 200 and patched.json()["enabled"] is False
    assert patched.json()["branch"] == "main"
    assert client.delete(f"{URL}/{cid}", headers=auth()).status_code == 204
    assert client.get(URL, headers=auth()).json() == []


def test_at_most_ten_channels(client, auth, member):
    for i in range(10):
        assert add(client, auth, name=f"c{i}").status_code == 201
    response = add(client, auth, name="c10")
    assert response.status_code == 422 and "10" in response.json()["detail"]


def test_send_test_reports_the_outcome(client, auth, member, http):
    route = http.post(SLACK).mock(return_value=httpx.Response(200, text="ok"))
    cid = add(client, auth).json()["id"]
    response = client.post(f"{URL}/{cid}/test", headers=auth())
    assert response.status_code == 200 and response.json() == {"status": "delivered", "error": None}
    assert "test message" in route.calls.last.request.content.decode().lower()

    http.post(SLACK).mock(return_value=httpx.Response(404, text="no_service"))
    failed = client.post(f"{URL}/{cid}/test", headers=auth()).json()
    assert failed["status"] == "failed" and "404" in failed["error"]
    assert client.get(URL, headers=auth()).json()[0]["last_status"] == "failed"


# --- delivery on ingest --------------------------------------------------------------------

def test_a_failed_run_is_announced_with_counts_tests_and_a_link(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db)
    route = http.post(SLACK).mock(return_value=httpx.Response(200, text="ok"))

    created = send(client, key, upload(failed=7))
    assert created.status_code == 201

    assert route.call_count == 1
    payload = json.loads(route.calls.last.request.content)
    text = json.dumps(payload, ensure_ascii=False)
    assert "7 of 8 tests failed" in payload["text"]
    assert "main" in text and "3f2a9c1" in text
    assert f"https://qeos.example.com/projects/1/runs/{created.json()['id']}" in text
    assert "checkout › Cart › case 0" in text and "case 5" not in text   # first five only
    assert "hunter2" not in text                                           # stored masked, sent masked
    db.expire_all()
    stored = db.query(NotificationChannel).one()
    assert stored.last_status == "delivered" and stored.last_sent_at is not None


def test_teams_gets_an_adaptive_card(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db, kind="teams", url=TEAMS)
    route = http.post(TEAMS).mock(return_value=httpx.Response(202))
    send(client, key, upload())
    payload = json.loads(route.calls.last.request.content)
    attachment = payload["attachments"][0]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert attachment["content"]["type"] == "AdaptiveCard"


def test_a_generic_webhook_gets_the_run_summary(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db, kind="webhook", url=HOOK)
    route = http.post(HOOK).mock(return_value=httpx.Response(204))
    created = send(client, key, upload(failed=2))
    body = json.loads(route.calls.last.request.content)
    assert body["event"] == "run.failed" and body["run"]["id"] == created.json()["id"]
    assert body["run"]["failed"] == 2 and len(body["failures"]) == 2


def test_passing_runs_disabled_channels_other_branches_and_replays_send_nothing(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db, branch="main")
    channel(db, enabled=False)
    route = http.post(SLACK).mock(return_value=httpx.Response(200))

    send(client, key, upload(failed=0))                     # all passed
    send(client, key, upload(branch="feature/x"))           # branch filter
    send(client, key, upload(), idem="run-1")
    send(client, key, upload(), idem="run-1")               # replay of a stored run
    assert route.call_count == 1                             # only the first main failure, once


def test_another_projects_channel_is_never_used(client, db, make_key, http):
    _, key = make_key(project_id=2)
    channel(db)                                              # belongs to project 1
    route = http.post(SLACK).mock(return_value=httpx.Response(200))
    send(client, key, upload())
    assert route.call_count == 0


def test_a_delivery_failure_is_recorded_and_the_upload_still_succeeds(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db)
    http.post(SLACK).mock(side_effect=httpx.ConnectTimeout("slow"))
    assert send(client, key, upload()).status_code == 201
    db.expire_all()
    stored = db.query(NotificationChannel).one()
    assert stored.last_status == "failed" and "ConnectTimeout" in stored.last_error


def test_a_webhook_host_that_now_resolves_privately_is_not_called(client, db, make_key, http, monkeypatch):
    _, key = make_key(project_id=1)
    channel(db, kind="webhook", url=HOOK)
    route = http.post(HOOK).mock(return_value=httpx.Response(200))
    monkeypatch.setattr(notify_targets, "resolve", lambda host: ["10.0.0.9"])
    send(client, key, upload())
    assert route.call_count == 0
    db.expire_all()
    assert "public" in db.query(NotificationChannel).one().last_error


def test_an_email_channel_mails_the_summary(client, db, make_key, monkeypatch):
    from src.ingestion.service import notification_service

    sent = []
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(notification_service, "send_mail", lambda s, to, subject, body: sent.append((to, subject, body)))
    _, key = make_key(project_id=1)
    channel(db, kind="email", url="qa@example.com, lead@example.com")
    created = send(client, key, upload(failed=2))
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == ["qa@example.com", "lead@example.com"]
    assert subject == "QA: 2 of 3 tests failed"
    assert "checkout › Cart › case 1" in body and "hunter2" not in body
    assert f"https://qeos.example.com/projects/1/runs/{created.json()['id']}" in body
    db.expire_all()
    assert db.query(NotificationChannel).one().last_status == "delivered"


def test_email_without_smtp_is_a_recorded_failure_not_a_silent_drop(client, db, make_key, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    _, key = make_key(project_id=1)
    channel(db, kind="email", url="qa@example.com")
    assert send(client, key, upload()).status_code == 201
    db.expire_all()
    stored = db.query(NotificationChannel).one()
    assert stored.last_status == "failed" and "SMTP is not configured" in stored.last_error


def test_an_email_channel_shows_its_addresses(client, auth, member):
    created = add(client, auth, kind="email", url="qa@example.com")
    assert created.status_code == 201, created.text
    assert created.json()["target"] == "qa@example.com"


# ---- runs of only the suggested tests (spec 2026-10-13 §3.3; plan Ruling 17) ----
SUBSET_STAGES = {"stages": [{"name": "suggested", "duration_s": 60.0, "tests": 3, "failed": 2}],
                 "time_to_first_failure_s": 12.0}


def test_a_subset_run_is_announced_as_suggested_tests_only(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db)
    route = http.post(SLACK).mock(return_value=httpx.Response(200, text="ok"))
    assert send(client, key, upload(failed=2, scope=SUBSET_SCOPE, stages=SUBSET_STAGES)).status_code == 201
    payload = json.loads(route.calls.last.request.content)
    assert payload["text"] == "QA: 2 of 3 tests failed · Suggested tests only"


def test_a_fail_fast_stop_says_it_stopped_after_stage_1(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db, kind="webhook", url=HOOK)
    route = http.post(HOOK).mock(return_value=httpx.Response(204))
    stopped = {**SUBSET_STAGES, "stopped_after_stage": 1}
    assert send(client, key, upload(failed=2, scope=SUBSET_SCOPE, stages=stopped)).status_code == 201
    body = json.loads(route.calls.last.request.content)
    assert (body["run"]["scope"], body["run"]["stopped_after_stage"]) == (SUBSET_SCOPE, 1)


def test_a_full_run_keeps_its_headline_and_says_it_is_full(client, db, make_key, http):
    _, key = make_key(project_id=1)
    channel(db)
    route = http.post(SLACK).mock(return_value=httpx.Response(200, text="ok"))
    send(client, key, upload(failed=2))
    assert json.loads(route.calls.last.request.content)["text"] == "QA: 2 of 3 tests failed"
    hook = notification_service.webhook_payload("QA", notification_service.RunSummary(
        project_id=1, run_id=5, total=3, failed=2, errored=0, branch="main", commit_sha=None, commit_message=None,
        ci_run_url=None))
    assert (hook["run"]["scope"], hook["run"]["stopped_after_stage"]) == ("full", None)


def test_the_email_subject_carries_the_label():
    summary = notification_service.RunSummary(
        project_id=1, run_id=5, total=3, failed=2, errored=0, branch="main", commit_sha=None, commit_message=None,
        ci_run_url=None, scope=SUBSET_SCOPE, stages={**SUBSET_STAGES, "stopped_after_stage": 1})
    assert notification_service.email_payload("QA", summary)["subject"] == (
        "QA: 2 of 3 tests failed · Suggested tests only, stopped after stage 1")
