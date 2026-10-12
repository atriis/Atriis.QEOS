"""Ingestion's /metrics reads job_heartbeats on each scrape; a failed read never breaks /metrics (spec §3)."""
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError

from src.ingestion.api import main
from src.ingestion.models.job_heartbeat import JobHeartbeat
from src.ingestion.utils import metrics

SUCCESS = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
ERROR = datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc)


def sample(name, job):
    return metrics.REGISTRY.get_sample_value(name, {"job": job})


def test_every_known_job_is_exposed_at_zero_before_its_first_pass(client):
    text = client.get("/metrics").text
    for job in ("retention", "rollup", "weekly_summary", "impact_rollup"):
        assert f'job_last_success_timestamp_seconds{{job="{job}"}} 0.0' in text
        assert f'job_last_error_timestamp_seconds{{job="{job}"}} 0.0' in text


def test_heartbeat_rows_become_unix_timestamps_and_the_error_text_stays_out(client, db):
    db.add(JobHeartbeat(job="rollup", last_success_at=SUCCESS, last_error_at=ERROR, last_error="RuntimeError: boom"))
    db.commit()
    text = client.get("/metrics").text
    assert sample("job_last_success_timestamp_seconds", "rollup") == SUCCESS.timestamp()
    assert sample("job_last_error_timestamp_seconds", "rollup") == ERROR.timestamp()
    assert sample("job_last_success_timestamp_seconds", "retention") == 0.0
    assert "boom" not in text


def test_a_failing_heartbeat_read_leaves_the_job_series_out_and_metrics_still_answers(client):
    def broken():
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    before = metrics.REGISTRY.get_sample_value("job_heartbeat_read_errors_total")
    good = main.HEARTBEATS.session_factory
    main.HEARTBEATS.session_factory = broken
    try:
        response = client.get("/metrics")
    finally:
        main.HEARTBEATS.session_factory = good
    assert response.status_code == 200
    assert "job_last_success_timestamp_seconds" not in response.text
    assert "qav_ingest_runs_total" in response.text and "api_requests_total" in response.text
    assert metrics.REGISTRY.get_sample_value("job_heartbeat_read_errors_total") == before + 1


def test_a_statement_timeout_is_a_read_error_and_metrics_answers_fast(client):
    import time

    def timing_out():
        raise OperationalError("SELECT", {}, Exception("canceling statement due to statement timeout"))

    before = metrics.REGISTRY.get_sample_value("job_heartbeat_read_errors_total")
    good = main.HEARTBEATS.session_factory
    main.HEARTBEATS.session_factory = timing_out
    try:
        start = time.monotonic()
        response = client.get("/metrics")
        elapsed = time.monotonic() - start
    finally:
        main.HEARTBEATS.session_factory = good
    assert response.status_code == 200 and elapsed < 2
    assert "job_last_success_timestamp_seconds" not in response.text
    assert metrics.REGISTRY.get_sample_value("job_heartbeat_read_errors_total") == before + 1


def test_the_collector_has_its_own_engine_not_the_apps_session_factory():
    from src.ingestion.db.session import SessionLocal

    assert main.HEARTBEATS.session_factory is not SessionLocal
    assert main.HEARTBEATS.session_factory.kw["bind"] is not SessionLocal.kw["bind"]
