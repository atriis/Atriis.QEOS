"""Traces on results (ADR-037): the run upload refers to them, the run pages list and download them, the export
names them."""
import hashlib
import json
from datetime import datetime, timezone

import pytest

from src.ingestion.models import Blob, CollectionSettings, ResultArtifact, ResultScreenshot, RunResult
from src.ingestion.utils import artifact_store
from src.ingestion.utils.artifact_store import MemoryArtifactStore, artifact_key, get_artifact_store
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
ZIP = b"PK\x03\x04" + bytes(range(256)) * 4  # 1,028 bytes, every offset tells where it is
SHA = hashlib.sha256(ZIP).hexdigest()
SHA_B = hashlib.sha256(b"b").hexdigest()
SHA_OTHER = hashlib.sha256(b"other").hexdigest()
SHA_SHOT = hashlib.sha256(b"shot").hexdigest()


def trace(sha, name=None, **extra):
    entry = {"sha256": sha, "kind": "trace", **extra}
    if name is not None:
        entry["name"] = name
    return entry


# ---- run upload ----

@pytest.fixture
def key(client, db, make_key):
    from src.ingestion.api.main import app

    app.dependency_overrides[get_artifact_store] = lambda: MemoryArtifactStore()
    _, plain = make_key(project_id=7)
    db.add(CollectionSettings(project_id=7, collect_manual=True, keep_screenshots=True, keep_traces=True,
                              trace_days=14, discarded_count=0))
    db.add_all([
        Blob(project_id=7, sha256=SHA, kind="trace", media_type="application/zip", bytes=len(ZIP)),
        Blob(project_id=7, sha256=SHA_B, kind="trace", media_type="application/zip", bytes=5),
        Blob(project_id=8, sha256=SHA_OTHER, kind="trace", media_type="application/zip", bytes=5),
        Blob(project_id=7, sha256=SHA_SHOT, kind="screenshot", media_type="image/png", bytes=5),
    ])
    db.commit()
    return plain


def post(client, key, artifacts, **result):
    results = [{"name": "t", "status": "failed", "artifacts": artifacts, **result}]
    return client.post(URL, json=upload_body(results=results), headers=key_headers(key))


def linked(db):
    db.expire_all()
    return [(a.position, a.blob_id, a.kind, a.name)
            for a in db.query(ResultArtifact).order_by(ResultArtifact.position)]


def blob_id(db, project, sha):
    return db.query(Blob).filter_by(project_id=project, sha256=sha).one().id


def test_traces_linked_in_order(client, key, db):
    response = post(client, key, [trace(SHA_B, "retry"), trace(SHA, "trace")])
    assert response.status_code == 201, response.text
    assert linked(db) == [(0, blob_id(db, 7, SHA_B), "trace", "retry"), (1, blob_id(db, 7, SHA), "trace", "trace")]
    assert db.query(ResultArtifact).first().result_id == db.query(RunResult).one().id


def test_unknown_other_project_and_screenshot_hashes_are_dropped(client, key, db):
    response = post(client, key, [trace("f" * 64), trace(SHA_OTHER), trace(SHA_SHOT), trace(SHA)])
    assert response.status_code == 201, response.text
    assert linked(db) == [(0, blob_id(db, 7, SHA), "trace", None)]


def test_switch_off_ignores_the_references(client, key, db):
    db.query(CollectionSettings).update({"keep_traces": False})
    db.commit()
    assert post(client, key, [trace(SHA)]).status_code == 201
    assert linked(db) == [] and db.query(RunResult).count() == 1


def test_without_a_store_the_references_are_ignored(client, key, db):
    from src.ingestion.api.main import app

    app.dependency_overrides[get_artifact_store] = lambda: None
    assert post(client, key, [trace(SHA)]).status_code == 201
    assert linked(db) == []


def test_a_malformed_reference_is_dropped_not_a_422(client, key, db):
    response = post(client, key, [{"sha256": "nope", "kind": "trace"}, trace(SHA_B, kind="video"), "junk",
                                  trace(SHA, "x" * 201), trace(SHA)])
    assert response.status_code == 201, response.text
    assert linked(db) == [(0, blob_id(db, 7, SHA), "trace", None)]


def test_fields_a_newer_collector_adds_are_ignored_up_to_eight_keys(client, key, db):
    newer = {**trace(SHA, "newer"), "media_type": "application/zip", "a": 1, "b": 2, "c": 3, "d": 4}  # 8 keys
    too_many = {**newer, "e": 5}  # 9: dropped before it is validated
    response = post(client, key, [too_many, newer])
    assert response.status_code == 201, response.text
    assert linked(db) == [(0, blob_id(db, 7, SHA), "trace", "newer")]


def test_more_than_five_traces_is_a_422(client, key, db):
    assert post(client, key, [trace(SHA)] * 6).status_code == 422


def test_screenshots_and_traces_together(client, key, db):
    from src.ingestion.models import Blob as B

    db.add(B(project_id=7, sha256="a" * 64, media_type="image/png", bytes=1))
    db.commit()
    shot = {"sha256": "a" * 64, "media_type": "image/png", "step_text": "Given x"}
    assert post(client, key, [trace(SHA)], screenshots=[shot]).status_code == 201
    assert len(linked(db)) == 1 and db.query(ResultScreenshot).count() == 1


def test_a_screenshot_reference_to_a_trace_blob_is_dropped(client, key, db):
    shot = {"sha256": SHA, "media_type": "image/png", "step_text": "Given x"}
    response = client.post(URL, json=upload_body(results=[{"name": "t", "status": "failed", "screenshots": [shot]}]),
                           headers=key_headers(key))
    assert response.status_code == 201 and db.query(ResultScreenshot).count() == 0


def test_a_replay_of_an_upload_without_artifacts_still_matches(client, key, db):
    body = upload_body(results=[{"name": "t", "status": "passed"}])
    assert client.post(URL, json=body, headers=key_headers(key, idem="k1")).status_code == 201
    assert client.post(URL, json=body, headers=key_headers(key, idem="k1")).status_code == 200


# ---- reads ----

@pytest.fixture
def store():
    from src.ingestion.api.main import app

    memory = MemoryArtifactStore()
    app.dependency_overrides[get_artifact_store] = lambda: memory
    return memory


def result_of(db, run):
    return db.query(RunResult).filter_by(run_id=run.id).order_by(RunResult.id).first()


def add_trace(db, result, project_id=1, sha=SHA, position=0, name="trace", size=len(ZIP)):
    blob = db.query(Blob).filter_by(project_id=project_id, sha256=sha).one_or_none()
    if blob is None:
        blob = Blob(project_id=project_id, sha256=sha, kind="trace", media_type="application/zip", bytes=size)
        db.add(blob)
        db.flush()
    row = ResultArtifact(result_id=result.id, position=position, blob_id=blob.id, kind="trace", name=name)
    db.add(row)
    db.commit()
    return row


def list_url(run, result):
    return f"/api/v1/projects/1/runs/{run.id}/results/{result.id}/artifacts"


def test_list_in_position_order(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0)
    result = result_of(db, run)
    second = add_trace(db, result, sha=SHA_B, position=1, name="retry", size=5)
    first = add_trace(db, result, position=0)
    resp = client.get(list_url(run, result), headers=auth())
    assert resp.status_code == 200
    assert resp.json() == {"artifacts": [
        {"id": first.id, "kind": "trace", "name": "trace", "bytes": len(ZIP)},
        {"id": second.id, "kind": "trace", "name": "retry", "bytes": 5},
    ]}


def test_list_empty_when_none(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0)
    assert client.get(list_url(run, result_of(db, run)), headers=auth()).json() == {"artifacts": []}


def test_list_non_member_and_other_project_404(client, auth, project_role, seed_run, db):
    run, other = seed_run(T0), seed_run(T0, project_id=2)
    project_role("viewer")
    assert client.get(list_url(other, result_of(db, other)), headers=auth()).status_code == 404
    assert client.get(list_url(run, result_of(db, other)), headers=auth()).status_code == 404
    project_role(status_code=404)
    assert client.get(list_url(run, result_of(db, run)), headers=auth()).status_code == 404


def download(client, auth, artifact_id, project_id=1, **headers):
    return client.get(f"/api/v1/projects/{project_id}/artifacts/{artifact_id}", headers={**auth(), **headers})


def test_download_streams_the_whole_file(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    resp = download(client, auth, row.id)
    assert resp.status_code == 200 and resp.content == ZIP
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["content-disposition"] == f'attachment; filename="trace-{row.id}.zip"'
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-length"] == str(len(ZIP))
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_download_never_reads_the_whole_object_at_once(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    store.get = lambda key: pytest.fail("the download must stream, not get() the object")
    store.get_range = lambda *args: pytest.fail("the download must stream, not get_range() the object")
    assert download(client, auth, row.id).content == ZIP
    assert download(client, auth, row.id, Range="bytes=4-9").content == ZIP[4:10]


@pytest.mark.parametrize("header, start, end", [
    ("bytes=0-3", 0, 3),
    ("bytes=100-199", 100, 199),
    ("bytes=1000-", 1000, len(ZIP) - 1),
    ("bytes=-22", len(ZIP) - 22, len(ZIP) - 1),
    ("bytes=1020-5000", 1020, len(ZIP) - 1),  # an end past the file is cut to it
    ("bytes=-5000", 0, len(ZIP) - 1),  # a suffix longer than the file is the whole file
    ("Bytes=0-3", 0, 3),  # the unit is case-insensitive (RFC 9110 14.1)
    ("BYTES=-22", len(ZIP) - 22, len(ZIP) - 1),
])
def test_a_range_answers_206(client, auth, project_role, seed_run, db, store, header, start, end):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    resp = download(client, auth, row.id, Range=header)
    assert resp.status_code == 206, resp.text
    assert resp.content == ZIP[start:end + 1]
    assert resp.headers["content-range"] == f"bytes {start}-{end}/{len(ZIP)}"
    assert resp.headers["content-length"] == str(end - start + 1)
    assert resp.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize("header", ["bytes=1028-", "bytes=5000-6000", "bytes=-0"])
def test_a_range_past_the_end_answers_416(client, auth, project_role, seed_run, db, store, header):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    resp = download(client, auth, row.id, Range=header)
    assert resp.status_code == 416
    assert resp.headers["content-range"] == f"bytes */{len(ZIP)}"


@pytest.mark.parametrize("header", ["bytes=0-1,5-6", "bytes=9-3", "items=0-1", "bytes=a-b", "bytes=-"])
def test_several_or_unreadable_ranges_get_the_whole_file(client, auth, project_role, seed_run, db, store, header):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    resp = download(client, auth, row.id, Range=header)
    assert resp.status_code == 200 and resp.content == ZIP


def test_download_of_another_project_404(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0, project_id=2)), project_id=2)
    store.put(artifact_key(2, SHA), ZIP, "application/zip")
    assert download(client, auth, row.id).status_code == 404
    assert download(client, auth, 99999).status_code == 404


def test_download_non_member_404(client, auth, project_role, seed_run, db, store):
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    project_role(status_code=404)
    assert download(client, auth, row.id).status_code == 404


def test_download_404_when_object_missing(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    assert download(client, auth, row.id).status_code == 404
    assert download(client, auth, row.id, Range="bytes=0-3").status_code == 404


def test_download_503_without_store(client, auth, project_role, seed_run, db):
    from src.ingestion.api.main import app

    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    app.dependency_overrides[get_artifact_store] = lambda: None
    assert download(client, auth, row.id).status_code == 503


def test_download_503_with_retry_after_when_the_store_is_busy(client, auth, project_role, seed_run, db, store,
                                                               monkeypatch):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    monkeypatch.setattr(artifact_store, "SLOT_WAIT_SECONDS", 0)
    for _ in range(artifact_store.STORE_CALLS):
        assert artifact_store._slots.acquire(blocking=False)
    try:
        resp = download(client, auth, row.id)
    finally:
        for _ in range(artifact_store.STORE_CALLS):
            artifact_store._slots.release()
    assert resp.status_code == 503 and resp.headers["retry-after"] == artifact_store.BUSY_RETRY_AFTER


def test_download_holds_no_transaction_while_reading(client, auth, project_role, seed_run, db, store):
    project_role("viewer")
    row = add_trace(db, result_of(db, seed_run(T0)))
    store.put(artifact_key(1, SHA), ZIP, "application/zip")
    seen = []
    original = store.open
    store.open = lambda key: (seen.append(db.in_transaction()), original(key))[1]
    assert download(client, auth, row.id).status_code == 200
    assert seen == [False]


def test_run_detail_trace_count(client, auth, project_role, seed_run, db):
    project_role("viewer")
    run = seed_run(T0, results=(("a", "failed", 1), ("b", "passed", 1)))
    first = result_of(db, run)
    add_trace(db, first, position=0)
    add_trace(db, first, sha=SHA_B, position=1, size=5)
    results = client.get(f"/api/v1/runs/{run.id}", headers=auth()).json()["results"]
    assert [(r["name"], r["trace_count"]) for r in results] == [("a", 2), ("b", 0)]


def test_export_line_names_the_traces_without_bytes(client, auth, project_role, seed_run, db):
    project_role("owner")
    run = seed_run(T0, results=(("a", "failed", 1), ("b", "passed", 1)))
    first = result_of(db, run)
    add_trace(db, first, sha=SHA_B, position=1, name="retry", size=5)
    add_trace(db, first, position=0)
    response = client.get("/api/v1/projects/1/export", headers=auth())
    _, _, failed, passed = [json.loads(line) for line in response.text.splitlines() if line]
    assert "artifacts" not in passed  # omitted when empty
    assert failed["artifacts"] == [
        {"kind": "trace", "name": "trace", "bytes": len(ZIP), "sha256": SHA},
        {"kind": "trace", "name": "retry", "bytes": 5, "sha256": SHA_B},
    ]


def test_latest_results_carry_trace_count_in_this_project_only(client, auth, project_role, seed_run, db):
    from tests.conftest import report_key

    project_role("viewer")
    run = seed_run(T0, results=(("a", "failed", 1), ("b", "passed", 1), ("c", "passed", 1)))
    rows = {r.name: r for r in db.query(RunResult).filter_by(run_id=run.id)}
    add_trace(db, rows["a"], position=0)
    add_trace(db, rows["a"], sha=SHA_B, position=1, size=5)
    add_trace(db, rows["c"], project_id=2, sha=SHA_OTHER, size=5)  # a blob of another project does not count
    keys = [report_key(n) for n in "abc"]
    got = client.post("/api/v1/projects/1/analytics/latest-results", json={"keys": keys}, headers=auth()).json()["results"]
    assert [got[k]["trace_count"] for k in keys] == [2, 0, 0]
