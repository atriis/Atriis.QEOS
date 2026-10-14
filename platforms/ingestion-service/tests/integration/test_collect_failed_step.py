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


def test_an_upload_hashed_before_migration_021_still_replays(client, make_key):
    """A part spooled before the upgrade has no failed_step key; resent after it, it replays instead of 409."""
    from src.ingestion.service import ingest_service
    from src.ingestion.schemas.collect import RunUpload

    _, key = make_key(project_id=1)
    body = upload_body()
    assert all("failed_step" not in r for r in body["results"])
    first = client.post(URL, json=body, headers=key_headers(key, idem="k-021"))
    explicit = {**body, "results": [{**r, "failed_step": None} for r in body["results"]]}
    again = client.post(URL, json=explicit, headers=key_headers(key, idem="k-021"))
    assert (first.status_code, again.status_code) == (201, 200)
    assert ingest_service._request_hash(RunUpload.model_validate(body)) == \
        ingest_service._request_hash(RunUpload.model_validate(explicit))


def test_the_failed_step_text_is_part_of_the_request_hash(client, make_key):
    _, key = make_key(project_id=1)

    def with_step(text):
        return upload_body(results=[{"name": "t", "status": "failed", "failed_step": {"text": text, "line": 1}}])

    assert client.post(URL, json=with_step("When a"), headers=key_headers(key, idem="k-step")).status_code == 201
    assert client.post(URL, json=with_step("When b"), headers=key_headers(key, idem="k-step")).status_code == 409


def test_a_nul_in_the_step_text_is_replaced_not_rejected(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "nul", "status": "failed",
                                 "failed_step": {"text": "When I send a\x00b", "line": 2}}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    row = db.query(RunResult).one()
    assert "\x00" not in row.failed_step_text and row.failed_step_text.startswith("When I send a")


DEFINITION = "features/step_definitions/search.js:12"


def test_definition_and_pattern_are_stored(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "search", "status": "failed", "message": "boom", "failed_step": {
        "text": "When I search Lisbon", "line": 14, "definition": DEFINITION, "pattern": "When I search {…}"}}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    row = db.query(RunResult).one()
    assert (row.failed_step_definition, row.failed_step_pattern) == (DEFINITION, "When I search {…}")


def test_definition_and_pattern_are_masked(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "login", "status": "failed", "failed_step": {
        "text": "When I log in", "definition": f"steps/login.js:3 {TOKEN}", "pattern": f'When I use "{TOKEN}"'}}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    row = db.query(RunResult).one()
    assert TOKEN not in row.failed_step_definition and TOKEN not in row.failed_step_pattern
    assert "[REDACTED:github_token]" in row.failed_step_definition and row.redacted is True


def test_unknown_failed_step_fields_are_ignored_on_upload(client, make_key, db):
    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "t", "status": "failed",
                                 "failed_step": {"text": "When x", "line": 2, "from_a_newer_collector": True}}])
    assert client.post(URL, json=body, headers=key_headers(key)).status_code == 201
    assert db.query(RunResult).one().failed_step_text == "When x"


def test_an_upload_hashed_before_migration_022_still_replays(client, make_key):
    """A part stored before the upgrade, resent after it: its failed_step has no definition or pattern keys."""
    import hashlib
    import json

    from src.ingestion.schemas.collect import RunUpload
    from src.ingestion.service import ingest_service

    _, key = make_key(project_id=1)
    body = upload_body(results=[{"name": "t", "status": "failed", "failed_step": {"text": "When x", "line": 2}}])
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-022")).status_code == 201
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-022")).status_code == 200
    # The hash the pre-022 code stored: the dump of a failed_step that had only text and line
    data = RunUpload.model_validate(body).model_dump(mode="json")
    for result in data["results"]:
        result["failed_step"].pop("definition", None)
        result["failed_step"].pop("pattern", None)
    for name, default in ingest_service._LATER_RUN_FIELDS.items():
        if data["run"].get(name, default) == default:
            data["run"].pop(name, None)
    old = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert ingest_service._request_hash(RunUpload.model_validate(body)) == old


def test_the_definition_is_part_of_the_request_hash(client, make_key):
    import copy

    _, key = make_key(project_id=1)
    first = upload_body(results=[{"name": "t", "status": "failed",
                                  "failed_step": {"text": "When a", "definition": "a.js:1"}}])
    second = copy.deepcopy(first)  # the same run times: only the definition differs
    second["results"][0]["failed_step"]["definition"] = "b.js:1"
    assert client.post(URL, json=first, headers=key_headers(key, idem="k-def")).status_code == 201
    assert client.post(URL, json=first, headers=key_headers(key, idem="k-def")).status_code == 200
    assert client.post(URL, json=second, headers=key_headers(key, idem="k-def")).status_code == 409
