"""Each result's log (ADR-032): masked like details, cut at 64 KB, stored; old uploads still replay."""
import hashlib
import json

from src.ingestion.core.config import settings
from src.ingestion.models import RunResult
from src.ingestion.schemas.collect import RunUpload
from src.ingestion.service import ingest_service
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

TOKEN = "ghp_" + "a" * 36
LOG = 'INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"'


def stored(db):
    db.expire_all()
    return db.query(RunResult).order_by(RunResult.id).all()


def post(client, key, results, idem=None):
    return client.post(URL, json=upload_body(results=results), headers=key_headers(key, idem=idem))


def test_the_log_is_stored(client, make_key, db):
    _, key = make_key(project_id=1)
    assert post(client, key, [{"name": "books", "status": "passed", "log": LOG}]).status_code == 201
    [row] = stored(db)
    assert row.log == LOG


def test_the_log_is_masked_before_it_is_stored(client, make_key, db):
    _, key = make_key(project_id=1)
    post(client, key, [{"name": "books", "status": "passed", "log": f"{LOG}\nGITHUB_TOKEN={TOKEN}"}])
    [row] = stored(db)
    assert TOKEN not in row.log and "[REDACTED:" in row.log and row.log.startswith(LOG)
    # `redacted` stays about what the run page shows: message, details and the failed step
    assert row.redacted is False


def test_a_long_log_is_cut_at_64_kb_never_rejected(client, make_key, db):
    _, key = make_key(project_id=1)
    assert post(client, key, [{"name": "long", "status": "passed", "log": "é" * 40_000}]).status_code == 201
    [row] = stored(db)
    assert len(row.log.encode("utf-8")) <= settings.MAX_TEXT_BYTES
    assert row.log == "é" * (settings.MAX_TEXT_BYTES // 2)  # cut on a character boundary, the start kept
    assert row.truncated is False  # `truncated` stays about message and details


def test_masking_happens_before_the_cut(client, make_key, db):
    _, key = make_key(project_id=1)
    log = "x" * (settings.MAX_TEXT_BYTES - 16) + " " + TOKEN
    post(client, key, [{"name": "edge", "status": "passed", "log": log}])
    [row] = stored(db)
    assert "ghp_" not in row.log


def test_a_nul_or_a_lone_surrogate_in_the_log_is_replaced_not_rejected(client, make_key, db):
    _, key = make_key(project_id=1)
    # json.dumps (ensure_ascii) writes the surrogate as \ud800, which is valid JSON; the client's own json= encodes
    # UTF-8 directly and cannot carry a lone surrogate, so the body is encoded here
    body = json.dumps(upload_body(results=[{"name": "odd", "status": "passed", "log": "trip\x00id \ud800 end"}]))
    response = client.post(URL, content=body.encode("ascii"),
                           headers={**key_headers(key), "Content-Type": "application/json"})
    assert response.status_code == 201, response.text
    [row] = stored(db)
    assert row.log == "trip\ufffdid \ufffd end"


def test_results_without_a_log_store_null(client, make_key, db):
    _, key = make_key(project_id=1)
    client.post(URL, json=upload_body(), headers=key_headers(key))
    assert all(r.log is None for r in stored(db))


def test_an_upload_hashed_before_migration_023_still_replays(client, make_key):
    """A part stored before the upgrade, resent after it: its results have no log key."""
    _, key = make_key(project_id=1)
    body = upload_body()
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-023")).status_code == 201
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-023")).status_code == 200
    data = RunUpload.model_validate(body).model_dump(mode="json")
    for result in data["results"]:
        result.pop("log", None)
        if result.get("failed_step") is None:
            result.pop("failed_step", None)
    for name, default in ingest_service._LATER_RUN_FIELDS.items():
        if data["run"].get(name, default) == default:
            data["run"].pop(name, None)
    old = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert ingest_service._request_hash(RunUpload.model_validate(body)) == old


def test_the_log_is_part_of_the_request_hash(client, make_key):
    _, key = make_key(project_id=1)
    assert post(client, key, [{"name": "t", "status": "passed", "log": "a"}], idem="k-log").status_code == 201
    assert post(client, key, [{"name": "t", "status": "passed", "log": "b"}], idem="k-log").status_code == 409
