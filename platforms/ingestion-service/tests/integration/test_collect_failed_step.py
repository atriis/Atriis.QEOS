"""The failing Cucumber step is stored per result, masked like the message (spec 2026-10-13 §3.2)."""
from src.ingestion.models import RunResult
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

TOKEN = "ghp_" + "a" * 36


def test_failed_step_is_stored(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "search", "status": "failed", "message": "boom",
                                 "failed_step": {"text": "When I search Lisbon", "line": 14}}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    row = db.query(RunResult).one()
    assert (row.failed_step_text, row.failed_step_line) == ("When I search Lisbon", 14)


def test_failed_step_text_is_masked(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "login", "status": "failed",
                                 "failed_step": {"text": f'When I log in with token "{TOKEN}"', "line": 3}}])
    client.post(URL, json=body, headers=key_headers(key))
    row = db.query(RunResult).one()
    assert TOKEN not in row.failed_step_text and row.redacted is True


def test_results_without_failed_step_store_null(client, make_key, db):
    _, key = make_key(project_id=1)
    client.post(URL, json=upload_body(), headers=key_headers(key))
    assert all(r.failed_step_text is None and r.failed_step_line is None for r in db.query(RunResult))
