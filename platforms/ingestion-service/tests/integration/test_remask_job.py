"""The one-off re-mask command: results stored before masking existed (or before a pattern was
added) get the masking that ingest applies today. Safe to run more than once."""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.core.config import settings
from src.ingestion.jobs import remask
from src.ingestion.models import Run, RunResult
from src.ingestion.models.run import FAILED_STEP_TEXT_LENGTH

WHEN = datetime(2026, 9, 1, tzinfo=timezone.utc)
SECRET = "ghp_" + "a" * 36


@pytest.fixture
def session_factory(db):
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)


@pytest.fixture
def add_run(db, make_key):
    keys = {}

    def _add(project_id=1, results=(), ci_run_url=None, failed_steps=None, definitions=None,
             patterns=None):
        if project_id not in keys:
            keys[project_id] = make_key(project_id=project_id)[0]
        run = Run(project_id=project_id, api_key_id=keys[project_id].id, request_hash="h", ci_provider="local",
                  ci_run_url=ci_run_url, started_at=WHEN, finished_at=WHEN, duration_ms=0,
                  total=len(results), passed=0, failed=len(results), skipped=0, errored=0)
        db.add(run)
        db.flush()
        for i, (message, details) in enumerate(results):
            db.add(RunResult(run_id=run.id, test_key=f"{i:064d}", name=f"t{i}", status="failed",
                             duration_ms=1, message=message, details=details,
                             failed_step_text=(failed_steps or {}).get(i),
                             failed_step_definition=(definitions or {}).get(i),
                             failed_step_pattern=(patterns or {}).get(i)))
        db.commit()
        return run.id

    return _add


def run_job(session_factory, *args):
    return remask.main(list(args), session_factory=session_factory)


def summary(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def results(db, run_id):
    db.expire_all()
    return db.query(RunResult).filter_by(run_id=run_id).order_by(RunResult.id).all()


def test_masks_what_ingest_would_mask_today(db, session_factory, add_run, capsys):
    run_id = add_run(results=[
        (f"auth failed with {SECRET}", "password=hunter2 at line 3"),
        ("plain assertion error", None),
    ], ci_run_url="https://user:pw@ci.example.com/build/1")
    assert run_job(session_factory, "--batch-size", "1") == 0

    first, second = results(db, run_id)
    assert SECRET not in first.message and "[REDACTED:github_token]" in first.message
    assert "hunter2" not in first.details
    assert first.redacted is True
    assert second.message == "plain assertion error" and second.redacted is False
    assert "pw@" not in db.get(Run, run_id).ci_run_url

    report = summary(capsys)
    assert report["event"] == "remask"
    assert report["results_scanned"] == 2
    assert report["results_changed"] == 1
    assert report["runs_changed"] == 1
    assert report["kinds"] == {"github_token": 1, "password": 1, "url_password": 1}


def test_a_second_pass_changes_nothing(db, session_factory, add_run, capsys):
    add_run(results=[(f"token {SECRET}", None)])
    run_job(session_factory)
    capsys.readouterr()
    run_job(session_factory)
    assert summary(capsys)["results_changed"] == 0


def test_dry_run_reports_and_changes_nothing(db, session_factory, add_run, capsys):
    run_id = add_run(results=[(f"token {SECRET}", None)])
    assert run_job(session_factory, "--dry-run") == 0
    assert results(db, run_id)[0].message == f"token {SECRET}"
    report = summary(capsys)
    assert report["dry_run"] is True and report["results_changed"] == 1


def test_project_filter_leaves_other_projects_alone(db, session_factory, add_run):
    mine = add_run(project_id=1, results=[(f"token {SECRET}", None)])
    other = add_run(project_id=2, results=[(f"token {SECRET}", None)])
    run_job(session_factory, "--project", "1")
    assert SECRET not in results(db, mine)[0].message
    assert results(db, other)[0].message == f"token {SECRET}"


def test_masking_that_lengthens_text_is_cut_back_to_the_limit(db, session_factory, add_run, monkeypatch):
    monkeypatch.setattr(settings, "MAX_TEXT_BYTES", 40)
    run_id = add_run(results=[("x" * 26 + " password=ab", None)])  # 40 bytes until "ab" becomes a marker
    run_job(session_factory)
    row = results(db, run_id)[0]
    assert len(row.message.encode()) <= 40
    assert row.truncated is True and row.redacted is True
    assert row.message == "x" * 26 + " password=[RED"  # the secret is gone; the cut lands in the marker


def test_commit_subjects_already_stored_are_masked(db, session_factory, add_run, capsys):
    run_id = add_run(results=[("plain", None)])
    run = db.get(Run, run_id)
    run.commit_message = f"rotate {SECRET}"
    db.commit()
    run_job(session_factory)
    db.expire_all()
    assert SECRET not in db.get(Run, run_id).commit_message
    assert summary(capsys)["runs_changed"] == 1


def test_failed_step_text_is_masked_when_nothing_else_is(db, session_factory, add_run, capsys):
    run_id = add_run(results=[("plain", None)], failed_steps={0: f"When I log in with {SECRET}"})
    run_job(session_factory)
    row = results(db, run_id)[0]
    assert SECRET not in row.failed_step_text and "[REDACTED:github_token]" in row.failed_step_text
    assert row.message == "plain" and row.redacted is True
    report = summary(capsys)
    assert report["results_changed"] == 1 and report["kinds"] == {"github_token": 1}


def test_failed_step_text_is_cut_back_to_its_column_length(db, session_factory, add_run):
    run_id = add_run(results=[("plain", None)], failed_steps={0: "x" * 985 + " password=ab"})  # 997 chars
    run_job(session_factory)
    row = results(db, run_id)[0]
    assert len(row.failed_step_text) == FAILED_STEP_TEXT_LENGTH
    assert "password=[RED" in row.failed_step_text and "ab" not in row.failed_step_text[985:]


def test_step_definition_and_pattern_are_masked(db, session_factory, add_run, capsys):
    run_id = add_run(results=[("plain", None)], failed_steps={0: "When I log in"},
                     definitions={0: f"steps/login.js:3 {SECRET}"}, patterns={0: f"When I use {SECRET}"})
    run_job(session_factory)
    row = results(db, run_id)[0]
    assert SECRET not in row.failed_step_definition and SECRET not in row.failed_step_pattern
    assert row.failed_step_text == "When I log in" and row.redacted is True
    assert summary(capsys)["kinds"] == {"github_token": 1}


def test_masking_that_lengthens_the_definition_is_cut_to_its_column(db, session_factory, add_run):
    from src.ingestion.models.run import FAILED_STEP_DEFINITION_LENGTH

    run_id = add_run(results=[("plain", None)], definitions={0: "x" * 480 + f" {SECRET}"})
    run_job(session_factory)
    assert len(results(db, run_id)[0].failed_step_definition) <= FAILED_STEP_DEFINITION_LENGTH


def test_a_re_masked_log_has_its_values_read_again(db, session_factory, add_run):
    from src.ingestion.models import LogPattern, LogValue

    run_id = add_run(results=[("plain message", None)])
    row = db.query(RunResult).filter_by(run_id=run_id).one()
    row.log = f'tripId="42" GITHUB_TOKEN={SECRET}'
    token = LogPattern(project_id=1, name="token", pattern=r"GITHUB_TOKEN=(\S+)")
    trip = LogPattern(project_id=1, name="trip_id", pattern=r'tripId="(\d+)"')
    db.add_all([token, trip])
    db.flush()
    db.add(LogValue(result_id=row.id, pattern_id=token.id, position=0, value=SECRET))  # stored before masking
    db.commit()

    assert run_job(session_factory) == 0

    db.expire_all()
    stored = db.query(RunResult).filter_by(run_id=run_id).one()
    assert SECRET not in stored.log and "[REDACTED:" in stored.log
    assert stored.redacted is False  # only the log changed; the run page's text did not
    assert [(v.pattern_id, v.value) for v in db.query(LogValue)] == [(trip.id, "42")]


def test_a_dry_run_leaves_the_log_and_its_values(db, session_factory, add_run):
    from src.ingestion.models import LogPattern, LogValue

    run_id = add_run(results=[("m", None)])
    row = db.query(RunResult).filter_by(run_id=run_id).one()
    row.log = f"GITHUB_TOKEN={SECRET}"
    token = LogPattern(project_id=1, name="token", pattern=r"GITHUB_TOKEN=(\S+)")
    db.add(token)
    db.flush()
    db.add(LogValue(result_id=row.id, pattern_id=token.id, position=0, value=SECRET))
    db.commit()
    assert run_job(session_factory, "--dry-run") == 0
    db.expire_all()
    assert SECRET in db.query(RunResult).filter_by(run_id=run_id).one().log
    assert db.query(LogValue).count() == 1
