"""run-impact's runs: scope and stages stored and read back, the request hash of older uploads unchanged, split uploads,
and the runs list filter (spec 2026-10-13 §3.1, §3.2; plan Rulings 5, 6)."""
import json

import pytest

from src.ingestion.models import Run
from src.ingestion.schemas.collect import RunUpload
from src.ingestion.service import ingest_service
from tests.integration.test_collect_endpoint import URL, key_headers, upload_body

TWO_STAGES = {"stages": [{"name": "suggested", "duration_s": 65.0, "tests": 12, "failed": 1},
                         {"name": "rest", "duration_s": 850.0, "tests": 340, "failed": 0}],
              "time_to_first_failure_s": 42.5}
STOPPED = {"stages": [{"name": "suggested", "duration_s": 65.0, "tests": 12, "failed": 1}],
           "time_to_first_failure_s": 30.0, "stopped_after_stage": 1}
# An upload as collectors before 0.6.0 send it, and its request hash as ingestion computed it before migration 020
# (computed on 2026-10-13 with the code at b1e2cf2)
LEGACY_BODY = {"run": {"ci_provider": "local", "branch": "main", "started_at": "2026-10-01T10:00:00+00:00",
                       "finished_at": "2026-10-01T10:04:00+00:00"},
               "results": [{"suite": "s", "class_name": "C", "name": "pays", "status": "passed", "duration_ms": 5}]}
LEGACY_HASH = "39a4af616b1b54a1f4b5b77ec176ee5c0cff13a1e7841c782532210d4d4469e8"
STAGE = {"name": "rest", "duration_s": 1, "tests": 1, "failed": 0}


def test_a_two_stage_run_is_stored_with_its_scope_and_stages(client, make_key, db, auth, project_role):
    _, key = make_key(project_id=1)
    response = client.post(URL, json=upload_body(scope="full", stages=TWO_STAGES), headers=key_headers(key))
    assert response.status_code == 201
    run = db.get(Run, response.json()["id"])
    assert run.scope == "full"
    assert run.stages == {**TWO_STAGES, "stopped_after_stage": None}
    project_role("viewer")
    detail = client.get(f"/api/v1/runs/{run.id}", headers=auth()).json()
    assert detail["scope"] == "full"
    assert detail["stages"]["time_to_first_failure_s"] == 42.5
    assert [s["name"] for s in detail["stages"]["stages"]] == ["suggested", "rest"]


def test_an_upload_without_them_is_a_full_run_without_stages(client, make_key, db, auth, project_role):
    _, key = make_key(project_id=1)
    run_id = client.post(URL, json=upload_body(), headers=key_headers(key)).json()["id"]
    run = db.get(Run, run_id)
    assert (run.scope, run.stages) == ("full", None)
    project_role("viewer")
    detail = client.get(f"/api/v1/runs/{run_id}", headers=auth()).json()
    assert (detail["scope"], detail["stages"]) == ("full", None)


def test_a_fail_fast_stop_is_a_subset_run(client, make_key, db):
    _, key = make_key(project_id=1)
    response = client.post(URL, json=upload_body(scope="impact-subset", stages=STOPPED), headers=key_headers(key))
    assert response.status_code == 201
    run = db.get(Run, response.json()["id"])
    assert (run.scope, run.stages["stopped_after_stage"]) == ("impact-subset", 1)


@pytest.mark.parametrize("run_fields", [
    {"scope": "partial"},
    {"scope": "full", "stages": STOPPED},  # a run that stopped did not run in full
    {"stages": {"stages": []}},
    {"stages": {"stages": TWO_STAGES["stages"] * 2}},
    {"stages": {"stages": [{**STAGE, "name": "warmup"}]}},
    {"stages": {"stages": [{**STAGE, "duration_s": -1}]}},
    {"stages": {"stages": [{**STAGE, "duration_s": 604801}]}},
    {"stages": {"stages": [{**STAGE, "tests": -1}]}},
    {"stages": {"stages": [STAGE], "time_to_first_failure_s": -0.5}},
    {"scope": "impact-subset", "stages": {"stages": [STAGE], "stopped_after_stage": 2}},
    {"stages": {"stages": [{**STAGE, "extra": 1}]}},
    {"stages": {"stages": [STAGE], "extra": 1}},
])
def test_invalid_scope_or_stages_are_422(client, make_key, run_fields):
    _, key = make_key(project_id=1)
    assert client.post(URL, json=upload_body(**run_fields), headers=key_headers(key)).status_code == 422


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_nan_duration_is_422(client, make_key, value):
    """Ruling C1: the 422 handler must not crash on a value JSON cannot carry back (it used to echo `input`)."""
    _, key = make_key(project_id=1)
    body = json.dumps(upload_body(scope="full", stages=TWO_STAGES)).replace("65.0", value, 1)
    response = client.post(URL, content=body, headers={**key_headers(key), "Content-Type": "application/json"})
    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"][-1] == "duration_s"
    assert not {"input", "ctx"} & set(error)


def test_a_422_never_echoes_the_body(client, make_key):
    """ADR-025, as in test-management: a 422 body carries no `input` or `ctx`, so it never sends a value back."""
    _, key = make_key(project_id=1)
    body = upload_body(commit_message="token ghp_" + "a" * 36, scope="partial")
    response = client.post(URL, json=body, headers=key_headers(key))
    assert response.status_code == 422
    assert "ghp_" not in response.text
    assert all(not {"input", "ctx"} & set(error) for error in response.json()["detail"])


def test_an_upload_from_before_migration_020_still_replays(client, make_key):
    """Review Focus 1: a spooled part stored before the upgrade comes back with the same key and body."""
    assert ingest_service._request_hash(RunUpload.model_validate(LEGACY_BODY)) == LEGACY_HASH
    explicit = {**LEGACY_BODY, "run": {**LEGACY_BODY["run"], "scope": "full"}}
    assert ingest_service._request_hash(RunUpload.model_validate(explicit)) == LEGACY_HASH
    _, key = make_key(project_id=1)
    first = client.post(URL, json=LEGACY_BODY, headers=key_headers(key, idem="spooled-1"))
    again = client.post(URL, json=explicit, headers=key_headers(key, idem="spooled-1"))
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]


def test_the_scope_is_part_of_the_request_hash(client, make_key):
    _, key = make_key(project_id=1)
    body = upload_body()
    assert client.post(URL, json=body, headers=key_headers(key, idem="k-scope")).status_code == 201
    subset = {**body, "run": {**body["run"], "scope": "impact-subset", "stages": STOPPED}}
    assert client.post(URL, json=subset, headers=key_headers(key, idem="k-scope")).status_code == 409


def test_a_split_upload_keeps_the_stages_on_its_first_part_only(client, make_key, db):
    """Ruling (split uploads): every part may carry `stages`, but they describe the whole run, so ingestion keeps the
    first non-null `stages` among the parts of one run (keys `<key>-part-N`); `scope` stays on every part."""
    _, key = make_key(project_id=1)
    bodies = {}

    def part(number, stages):
        bodies[number] = upload_body(scope="impact-subset", stages=stages)
        response = client.post(URL, json=bodies[number], headers=key_headers(key, idem=f"job-7-part-{number}"))
        assert response.status_code == 201, response.text
        return db.get(Run, response.json()["id"])

    first, second, third = part(1, None), part(2, STOPPED), part(3, STOPPED)
    assert (first.stages, second.stages["stopped_after_stage"], third.stages) == (None, 1, None)
    assert {first.scope, second.scope, third.scope} == {"impact-subset"}
    # Another run's parts, and an unsplit upload, keep their own stages
    other = client.post(URL, json=upload_body(scope="impact-subset", stages=STOPPED),
                        headers=key_headers(key, idem="job-70-part-1")).json()["id"]
    plain = client.post(URL, json=upload_body(scope="impact-subset", stages=STOPPED),
                        headers=key_headers(key, idem="job-7")).json()["id"]
    assert db.get(Run, other).stages is not None and db.get(Run, plain).stages is not None
    # A part resent as it was still replays: the hash is the request's, not what was stored
    again = client.post(URL, json=bodies[3], headers=key_headers(key, idem="job-7-part-3"))
    assert (again.status_code, again.json()["id"]) == (200, third.id)


def test_the_runs_list_filters_on_scope(client, make_key, auth, project_role):
    _, key = make_key(project_id=1)
    full = client.post(URL, json=upload_body(), headers=key_headers(key)).json()["id"]
    subset = client.post(URL, json=upload_body(scope="impact-subset", stages=STOPPED),
                         headers=key_headers(key)).json()["id"]
    project_role("viewer")

    def ids(**params):
        return [r["id"] for r in client.get("/api/v1/projects/1/runs", params=params, headers=auth()).json()]

    assert ids() == [subset, full]
    assert ids(scope="full") == [full]
    assert ids(scope="impact-subset") == [subset]
    assert client.get("/api/v1/projects/1/runs", params={"scope": "partial"}, headers=auth()).status_code == 422
