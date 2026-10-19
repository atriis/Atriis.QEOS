"""Run upload references screenshots by sha256; ingestion links them to results (ADR-036)."""
import hashlib

import pytest

from src.ingestion.models import Blob, CollectionSettings, ResultScreenshot, RunResult
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
