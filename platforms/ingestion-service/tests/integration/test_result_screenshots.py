"""Read a result's screenshots and their images (ADR-036)."""
import hashlib
from datetime import datetime, timezone

import pytest

from src.ingestion.models import Blob, ResultScreenshot, RunResult
from src.ingestion.utils import artifact_store
from src.ingestion.utils.artifact_store import MemoryArtifactStore, get_artifact_store, screenshot_key

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
SHA = hashlib.sha256(PNG).hexdigest()


@pytest.fixture
def store():
    from src.ingestion.api.main import app

    memory = MemoryArtifactStore()
    app.dependency_overrides[get_artifact_store] = lambda: memory
    return memory


def add_blob(db, project_id=1, sha=SHA, media_type="image/png", size=len(PNG)):
    blob = Blob(project_id=project_id, sha256=sha, media_type=media_type, bytes=size)
    db.add(blob)
    db.flush()
    return blob


def add_shot(db, result, blob, position, step="Given a step", line=None, hook=None):
    row = ResultScreenshot(result_id=result.id, position=position, blob_id=blob.id, step_text=step,
                           step_line=line, hook=hook)
    db.add(row)
    db.commit()
    return row


def result_of(db, run):
    return db.query(RunResult).filter_by(run_id=run.id).first()


def test_list_in_position_order(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0)
    result = result_of(db, run)
    blob = add_blob(db)
    add_shot(db, result, blob, 1, "second", line=5)
    add_shot(db, result, blob, 0, "first", hook="before")
    body = client.get(f"/api/v1/projects/1/runs/{run.id}/results/{result.id}/screenshots", headers=auth()).json()
    assert [s["step_text"] for s in body["screenshots"]] == ["first", "second"]
    first = body["screenshots"][0]
    assert first["hook"] == "before" and first["step_line"] is None
    assert first["media_type"] == "image/png" and first["bytes"] == len(PNG) and isinstance(first["id"], int)


def test_list_empty_when_none(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0)
    result = result_of(db, run)
    resp = client.get(f"/api/v1/projects/1/runs/{run.id}/results/{result.id}/screenshots", headers=auth())
    assert resp.status_code == 200 and resp.json() == {"screenshots": []}


def test_list_non_member_and_other_project_404(client, auth, project_role, seed_run, db):
    run = seed_run(T0)
    other = seed_run(T0, project_id=2)
    result = result_of(db, run)
    project_role("viewer")
    # a run of another project, and a result that is not in the run
    assert client.get(f"/api/v1/projects/1/runs/{other.id}/results/{result_of(db, other).id}/screenshots",
                      headers=auth()).status_code == 404
    assert client.get(f"/api/v1/projects/1/runs/{run.id}/results/{result_of(db, other).id}/screenshots",
                      headers=auth()).status_code == 404
    project_role(status_code=404)
    assert client.get(f"/api/v1/projects/1/runs/{run.id}/results/{result.id}/screenshots",
                      headers=auth()).status_code == 404


def test_image_bytes_and_headers(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    result = result_of(db, seed_run(T0))
    shot = add_shot(db, result, add_blob(db), 0)
    store.put(screenshot_key(1, SHA), PNG, "image/png")
    resp = client.get(f"/api/v1/projects/1/screenshots/{shot.id}", headers=auth())
    assert resp.status_code == 200 and resp.content == PNG
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "private, max-age=3600"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_image_of_another_project_404(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    result = result_of(db, seed_run(T0, project_id=2))
    shot = add_shot(db, result, add_blob(db, project_id=2), 0)
    store.put(screenshot_key(2, SHA), PNG, "image/png")
    assert client.get(f"/api/v1/projects/1/screenshots/{shot.id}", headers=auth()).status_code == 404
    assert client.get("/api/v1/projects/1/screenshots/99999", headers=auth()).status_code == 404


def test_image_non_member_404(client, auth, project_role, seed_run, db, store):
    result = result_of(db, seed_run(T0))
    shot = add_shot(db, result, add_blob(db), 0)
    project_role(status_code=404)
    assert client.get(f"/api/v1/projects/1/screenshots/{shot.id}", headers=auth()).status_code == 404


def test_image_404_when_object_missing(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    result = result_of(db, seed_run(T0))
    shot = add_shot(db, result, add_blob(db), 0)
    assert client.get(f"/api/v1/projects/1/screenshots/{shot.id}", headers=auth()).status_code == 404


def test_image_503_without_store(client, auth, project_role, seed_run, db, store):
    from src.ingestion.api.main import app

    project_role("viewer")
    result = result_of(db, seed_run(T0))
    shot = add_shot(db, result, add_blob(db), 0)
    app.dependency_overrides[get_artifact_store] = lambda: None
    assert client.get(f"/api/v1/projects/1/screenshots/{shot.id}", headers=auth()).status_code == 503


def test_image_holds_no_transaction_while_reading(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    shot = add_shot(db, result_of(db, seed_run(T0)), add_blob(db), 0)
    store.put(screenshot_key(1, SHA), PNG, "image/png")
    seen = []
    original = store.get
    store.get = lambda key: (seen.append(db.in_transaction()), original(key))[1]
    assert client.get(f"/api/v1/projects/1/screenshots/{shot.id}", headers=auth()).status_code == 200
    assert seen == [False]


def test_image_503_with_retry_after_when_the_store_is_busy(client, auth, project_role, seed_run, db, store,
                                                           monkeypatch):
    project_role("viewer")
    shot = add_shot(db, result_of(db, seed_run(T0)), add_blob(db), 0)
    store.put(screenshot_key(1, SHA), PNG, "image/png")
    monkeypatch.setattr(artifact_store, "SLOT_WAIT_SECONDS", 0)
    for _ in range(artifact_store.STORE_CALLS):
        assert artifact_store._slots.acquire(blocking=False)
    try:
        resp = client.get(f"/api/v1/projects/1/screenshots/{shot.id}", headers=auth())
    finally:
        for _ in range(artifact_store.STORE_CALLS):
            artifact_store._slots.release()
    assert resp.status_code == 503 and resp.headers["retry-after"] == artifact_store.BUSY_RETRY_AFTER


def test_row_pointing_at_another_projects_blob_is_not_served(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    run = seed_run(T0)
    result = result_of(db, run)
    shot = add_shot(db, result, add_blob(db, project_id=2), 0)
    store.put(screenshot_key(2, SHA), PNG, "image/png")
    store.put(screenshot_key(1, SHA), PNG, "image/png")
    assert client.get(f"/api/v1/projects/1/screenshots/{shot.id}", headers=auth()).status_code == 404
    listed = client.get(f"/api/v1/projects/1/runs/{run.id}/results/{result.id}/screenshots", headers=auth())
    assert listed.json() == {"screenshots": []}
    detail = client.get(f"/api/v1/runs/{run.id}", headers=auth()).json()
    assert [r["screenshot_count"] for r in detail["results"] if r["id"] == result.id] == [0]
    key = result.test_key
    latest = client.post("/api/v1/projects/1/analytics/latest-results", json={"keys": [key]}, headers=auth())
    assert "screenshot_steps" not in latest.json()["results"][key]
