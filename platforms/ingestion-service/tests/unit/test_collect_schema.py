from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.ingestion.schemas.collect import RunUpload

NOW = datetime.now(timezone.utc)


def body(run=None, results=None):
    r = {"ci_provider": "github_actions", "started_at": (NOW - timedelta(minutes=5)).isoformat(),
         "finished_at": NOW.isoformat()}
    r.update(run or {})
    return {"run": r, "results": results if results is not None else [{"name": "t", "status": "passed"}]}


def test_minimal_upload_is_valid_with_defaults():
    upload = RunUpload.model_validate(body())
    result = upload.results[0]
    assert (result.suite, result.class_name, result.duration_ms) == ("", "", 0)


def test_error_status_becomes_errored():
    upload = RunUpload.model_validate(body(results=[{"name": "t", "status": "error"}]))
    assert upload.results[0].status == "errored"


@pytest.mark.parametrize(
    "run",
    [
        {"ci_provider": "travis"},
        {"started_at": "2026-09-29T10:00:00"},                              # no timezone
        {"started_at": NOW.isoformat(), "finished_at": (NOW - timedelta(seconds=1)).isoformat()},
        {"finished_at": (NOW + timedelta(days=1)).isoformat()},
        {"commit_sha": "xyz1234"},
        {"commit_sha": "abc12"},
        {"ci_run_url": "javascript:alert(1)"},
        {"branch": "b" * 256},
        {"unexpected": "field"},
    ],
)
def test_invalid_run_fields(run):
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(run=run))


def test_finished_at_slightly_in_the_future_is_accepted():
    RunUpload.model_validate(body(run={"finished_at": (NOW + timedelta(minutes=10)).isoformat()}))


@pytest.mark.parametrize(
    "result",
    [
        {"status": "passed"},                        # no name
        {"name": "   ", "status": "passed"},
        {"name": "t", "status": "flaky"},
        {"name": "t", "status": "passed", "duration_ms": -1},
        {"name": "t", "status": "passed", "extra": 1},
        {"name": "n" * 1001, "status": "passed"},
    ],
)
def test_invalid_results(result):
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(results=[result]))


def test_empty_results_are_rejected():
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(results=[]))


def test_too_many_results_are_rejected():
    from src.ingestion.core.config import settings

    too_many = [{"name": f"t{i}", "status": "passed"} for i in range(settings.MAX_RESULTS_PER_RUN + 1)]
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(results=too_many))


def test_long_text_is_accepted_by_the_schema():
    # truncation is the service's job; the schema must not reject long text
    RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "details": "x" * 200_000}]))


def test_a_run_longer_than_the_maximum_span_is_rejected():
    # the run's duration_ms is an int32 column; a start years back would overflow it (500 on PostgreSQL)
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(run={"started_at": (NOW - timedelta(days=8)).isoformat()}))


def test_a_long_but_plausible_run_is_accepted():
    RunUpload.model_validate(body(run={"started_at": (NOW - timedelta(days=6)).isoformat()}))


@pytest.mark.parametrize("field", ["message", "details"])
@pytest.mark.parametrize("raw, cleaned", [("a\x00b", "a�b"), ("x\ud800y", "x�y"), ("\udfff", "�")])
def test_nul_and_lone_surrogates_in_free_text_are_replaced_not_rejected(field, raw, cleaned):
    # real stdout captured into JUnit output contains NUL bytes; PostgreSQL text cannot store them
    upload = RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", field: raw}]))
    assert getattr(upload.results[0], field) == cleaned


@pytest.mark.parametrize("field", ["name", "suite", "class_name", "file"])
@pytest.mark.parametrize("bad", ["a\x00b", "x\ud800y"])
def test_nul_or_lone_surrogate_in_a_result_identity_field_is_rejected(field, bad):
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(results=[{"name": "t", "status": "passed", field: bad}]))


@pytest.mark.parametrize("field", ["branch", "environment", "agent_version"])
def test_nul_in_run_metadata_is_rejected(field):
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(run={field: "a\x00b"}))


@pytest.mark.parametrize("trigger", ["manual", "automatic", "qeos", None])
def test_trigger_values(trigger):
    run = {} if trigger is None else {"trigger": trigger}
    assert RunUpload.model_validate(body(run=run)).run.trigger == trigger


def test_an_unknown_trigger_is_rejected():
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(run={"trigger": "cron"}))


def test_failed_step_is_optional_and_validated():
    ok = body(results=[{"name": "t", "status": "failed", "failed_step": {"text": "When I search Lisbon", "line": 14}}])
    assert RunUpload.model_validate(ok).results[0].failed_step.line == 14
    no_line = body(results=[{"name": "t", "status": "failed", "failed_step": {"text": "When x"}}])
    assert RunUpload.model_validate(no_line).results[0].failed_step.line is None


@pytest.mark.parametrize("step", [{"text": ""}, {"text": "x" * 1001}, {"text": "x", "line": 0},
                                  {"text": "x", "line": 1_000_001}, {"text": "x", "definition": ""},
                                  {"text": "x", "definition": "d" * 501}, {"text": "x", "pattern": ""},
                                  {"text": "x", "pattern": "p" * 1001}])
def test_invalid_failed_step_is_rejected(step):
    with pytest.raises(ValidationError):
        RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "failed_step": step}]))


def test_failed_step_definition_and_pattern_are_optional_free_text():
    step = {"text": "When I search Lisbon", "definition": "steps/search.js:12\x00", "pattern": "When I search {…}"}
    parsed = RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "failed_step": step}]))
    got = parsed.results[0].failed_step
    assert got.definition == "steps/search.js:12�" and got.pattern == "When I search {…}"
    plain = RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "failed_step": {"text": "x"}}]))
    assert plain.results[0].failed_step.definition is None and plain.results[0].failed_step.pattern is None


def test_unknown_failed_step_fields_are_ignored():
    """Forward compatibility (spec 2026-10-14 §3.1): a newer collector's field never costs the upload."""
    step = {"text": "When x", "line": 3, "hook": "before", "location": {"uri": "f.feature"}}
    parsed = RunUpload.model_validate(body(results=[{"name": "t", "status": "failed", "failed_step": step}]))
    assert parsed.results[0].failed_step.model_dump() == {"text": "When x", "line": 3, "definition": None, "pattern": None}
