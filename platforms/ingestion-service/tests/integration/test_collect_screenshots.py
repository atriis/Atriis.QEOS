"""Run upload references screenshots by sha256; ingestion links them to results (ADR-036)."""
import hashlib

import pytest

from src.ingestion.models import Blob, CollectionSettings, ResultScreenshot, Run, RunResult
from src.ingestion.models.masking_pattern import MaskingPattern
from src.ingestion.utils.artifact_store import MemoryArtifactStore, get_artifact_store
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

SHA_A = hashlib.sha256(b"a").hexdigest()
SHA_B = hashlib.sha256(b"b").hexdigest()
SHA_C = hashlib.sha256(b"c").hexdigest()


def shot(sha, step="Given a step", **extra):
    return {"sha256": sha, "media_type": "image/png", "step_text": step, **extra}


@pytest.fixture
def key(client, db, make_key):
    from src.ingestion.api.main import app

    app.dependency_overrides[get_artifact_store] = lambda: MemoryArtifactStore()
    _, plain = make_key(project_id=7)
    db.add(CollectionSettings(project_id=7, collect_manual=True, keep_screenshots=True, discarded_count=0))
    for project, sha in ((7, SHA_A), (7, SHA_B), (8, SHA_C)):
        db.add(Blob(project_id=project, sha256=sha, media_type="image/png", bytes=1))
    db.commit()
    return plain


def post(client, key, screenshots, name="t"):
    results = [{"name": name, "status": "failed", "screenshots": screenshots}]
    return client.post(URL, json=upload_body(results=results), headers=key_headers(key))


def linked(db):
    db.expire_all()
    return [(s.position, s.blob_id, s.step_text, s.step_line, s.hook)
            for s in db.query(ResultScreenshot).order_by(ResultScreenshot.position)]


def blob_id(db, project, sha):
    return db.query(Blob).filter_by(project_id=project, sha256=sha).one().id


def test_screenshots_linked_in_order(client, key, db):
    response = post(client, key, [shot(SHA_B, "second", step_line=4, hook="after"), shot(SHA_A, "first"),
                                  shot(SHA_B, "again")])
    assert response.status_code == 201, response.text
    assert linked(db) == [
        (0, blob_id(db, 7, SHA_B), "second", 4, "after"),
        (1, blob_id(db, 7, SHA_A), "first", None, None),
        (2, blob_id(db, 7, SHA_B), "again", None, None),
    ]
    assert db.query(ResultScreenshot).first().result_id == db.query(RunResult).one().id


def test_reference_without_blob_dropped(client, key, db):
    assert post(client, key, [shot("f" * 64, "gone"), shot(SHA_A, "kept")]).status_code == 201
    assert [row[2] for row in linked(db)] == ["kept"]


def test_reference_to_other_projects_blob_dropped(client, key, db):
    assert post(client, key, [shot(SHA_C)]).status_code == 201
    assert linked(db) == []


def test_screenshots_dropped_when_setting_off(client, key, db):
    db.query(CollectionSettings).update({"keep_screenshots": False})
    db.commit()
    assert post(client, key, [shot(SHA_A)]).status_code == 201
    assert linked(db) == [] and db.query(RunResult).count() == 1


def test_screenshots_dropped_without_a_store(client, key, db):
    from src.ingestion.api.main import app

    app.dependency_overrides[get_artifact_store] = lambda: None
    assert post(client, key, [shot(SHA_A)]).status_code == 201
    assert linked(db) == []


def test_step_text_masked(client, key, db):
    db.add(MaskingPattern(project_id=7, name="customer_id", pattern=r"CUST-\d{6}"))
    db.commit()
    assert post(client, key, [shot(SHA_A, "Given CUST-123456 logs in")]).status_code == 201
    assert linked(db)[0][2] == "Given [REDACTED:customer_id] logs in"
    assert db.query(RunResult).one().redacted is True


def test_a_malformed_screenshot_is_dropped_not_a_422(client, key, db):
    response = post(client, key, [{"sha256": "nope", "step_text": "x"}, "junk", shot(SHA_A, "ok")])
    assert response.status_code == 201, response.text
    assert [row[2] for row in linked(db)] == ["ok"]
    assert response.json()["screenshots_dropped"] == 2


def test_positions_have_no_gaps_when_an_entry_is_dropped(client, key, db):
    assert post(client, key, [shot("f" * 64), shot(SHA_A, "a"), shot(SHA_B, "b")]).status_code == 201
    assert [(row[0], row[2]) for row in linked(db)] == [(0, "a"), (1, "b")]


def test_the_receipt_counts_dropped_references(client, key, db):
    from src.ingestion.utils import metrics

    def count(reason):
        return metrics.REGISTRY.get_sample_value("qav_ingest_screenshots_dropped_total", {"reason": reason}) or 0.0

    before = count("unknown")
    response = post(client, key, [shot("f" * 64), shot(SHA_C), shot(SHA_A)])
    assert response.json()["screenshots_dropped"] == 2
    assert count("unknown") == before + 2
    db.query(CollectionSettings).update({"keep_screenshots": False})
    db.commit()
    off = client.post(URL, json=upload_body(results=[{"name": "u", "status": "failed", "screenshots": [shot(SHA_A)]}]),
                      headers=key_headers(key))
    assert off.json()["screenshots_dropped"] == 1


def test_a_deeply_nested_entry_is_dropped_not_a_500(client, key, db):
    deep = "x"
    for _ in range(100):
        deep = {"a": deep}
    response = post(client, key, [{**shot(SHA_A), "step_text": deep}, shot(SHA_B, "ok")])
    assert response.status_code == 201, response.text
    assert [row[2] for row in linked(db)] == ["ok"] and response.json()["screenshots_dropped"] == 1


def test_a_failing_screenshot_insert_keeps_the_run(client, key, db, monkeypatch):
    from src.ingestion.service import ingest_service
    from src.ingestion.utils import metrics

    real = ingest_service._blob_ids

    def gone_after_lookup(*args, **kwargs):
        # The lookup runs as usual; the ids come back unusable (NOT NULL fails the insert, as a deleted blob's FK would)
        return {sha: None for sha in real(*args, **kwargs)}

    def count():
        return metrics.REGISTRY.get_sample_value("qav_ingest_screenshots_dropped_total", {"reason": "gone"}) or 0.0

    before = count()
    monkeypatch.setattr(ingest_service, "_blob_ids", gone_after_lookup)
    response = post(client, key, [shot(SHA_A)])
    assert response.status_code == 201, response.text
    assert linked(db) == [] and db.query(RunResult).count() == 1
    assert db.get(Run, response.json()["id"]) is not None
    assert response.json()["screenshots_dropped"] == 1
    assert count() == before + 1


def test_a_replay_does_not_report_dropped_references(client, key, db):
    body = upload_body(results=[{"name": "t", "status": "failed", "screenshots": [shot("f" * 64)]}])
    first = client.post(URL, json=body, headers=key_headers(key, "k2"))
    again = client.post(URL, json=body, headers=key_headers(key, "k2"))
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["screenshots_dropped"] == 1 and again.json()["screenshots_dropped"] is None


def test_the_request_hash_of_valid_screenshots_is_unchanged(client, key):
    """A part spooled by an earlier build (screenshots dumped from ScreenshotIn) still replays."""
    import hashlib
    import json

    from src.ingestion.schemas.collect import RunUpload
    from src.ingestion.service import ingest_service

    body = upload_body(results=[{"name": "t", "status": "failed", "screenshots": [shot(SHA_A, step_line=2)]}])
    data = RunUpload.model_validate(body).model_dump(mode="json")
    assert data["results"][0]["screenshots"] == [
        {"sha256": SHA_A, "media_type": "image/png", "step_text": "Given a step", "step_line": 2, "hook": None}]
    for name, default in ingest_service._LATER_RUN_FIELDS.items():
        if data["run"].get(name, default) == default:
            data["run"].pop(name, None)
    for result in data["results"]:
        result.pop("log", None)
        result.pop("failed_step", None)
        result.pop("artifacts", None)  # dumps before migration 027 had no artifacts key
    old = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert ingest_service._request_hash(RunUpload.model_validate(body)) == old


def test_one_query_links_all_hashes(client, key, db):
    from sqlalchemy import event

    selects = []

    def count(conn, cursor, statement, *args):
        if "FROM blobs" in statement:
            selects.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        assert post(client, key, [shot(SHA_A), shot(SHA_B), shot(SHA_A)]).status_code == 201
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    # collect_run's own blob lookups: exactly one (the key's settings are read from another table)
    assert len(selects) == 1


def test_a_replay_with_screenshots_is_idempotent(client, key, db):
    results = [{"name": "t", "status": "failed", "screenshots": [shot(SHA_A)]}]
    body = upload_body(results=results)  # the times are made once: a replay is the same payload
    first = client.post(URL, json=body, headers=key_headers(key, "k1"))
    again = client.post(URL, json=body, headers=key_headers(key, "k1"))
    assert (first.status_code, again.status_code) == (201, 200)
    assert len(linked(db)) == 1
