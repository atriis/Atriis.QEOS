"""Custom masking patterns per project: managed through the API, applied at ingest and by the
re-mask command, and only ever to the project that owns them."""
import json

import pytest
from sqlalchemy.orm import sessionmaker

from src.ingestion.jobs import remask
from src.ingestion.models import Run, RunResult
from src.ingestion.models.masking_pattern import MaskingPattern

URL = "/api/v1/projects/1/masking-patterns"


@pytest.fixture
def member(project_role):
    project_role(role="member", project_id=1)


def add(client, auth, name="customer_id", pattern=r"CUST-\d{6}"):
    return client.post(URL, json={"name": name, "pattern": pattern}, headers=auth())


def test_a_member_adds_lists_and_removes_a_pattern(client, auth, member):
    created = add(client, auth)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "customer_id" and body["pattern"] == r"CUST-\d{6}"

    listed = client.get(URL, headers=auth()).json()
    assert [p["name"] for p in listed] == ["customer_id"]

    assert client.delete(f"{URL}/{body['id']}", headers=auth()).status_code == 204
    assert client.get(URL, headers=auth()).json() == []


def test_a_viewer_can_read_but_not_change(client, auth, project_role):
    project_role(role="viewer", project_id=1)
    assert client.get(URL, headers=auth()).status_code == 200
    assert add(client, auth).status_code == 403


def test_an_unsafe_pattern_is_refused_with_its_reason(client, auth, member):
    response = add(client, auth, pattern=r"x*")
    assert response.status_code == 422
    assert "matches empty text" in response.json()["detail"]


def test_a_duplicate_name_conflicts(client, auth, member):
    add(client, auth)
    assert add(client, auth, pattern=r"CUST-\d{7}").status_code == 409


def test_a_project_holds_at_most_twenty_patterns(client, auth, member):
    for i in range(20):
        assert add(client, auth, name=f"p{i}", pattern=f"token{i}").status_code == 201
    response = add(client, auth, name="p20", pattern="token20")
    assert response.status_code == 422
    assert "20" in response.json()["detail"]


def test_preview_shows_what_a_pattern_would_mask_without_saving(client, auth, member, db):
    db.add(MaskingPattern(project_id=1, name="ticket", pattern=r"JIRA-\d+"))
    db.commit()
    response = client.post(f"{URL}/preview", json={"name": "customer_id", "pattern": r"CUST-\d{6}",
                                                   "sample": "for CUST-123456 and CUST-1, JIRA-7, ana@example.com"},
                           headers=auth())
    assert response.status_code == 200, response.text
    # What would be stored: built-in masking and the project's other patterns too; the count is
    # this pattern's matches
    assert response.json() == {
        "masked": "for [REDACTED:customer_id] and CUST-1, [REDACTED:ticket], [REDACTED:email]", "matches": 1,
    }
    assert db.query(MaskingPattern).count() == 1


def collect_body(message):
    return {
        "run": {"ci_provider": "github_actions","started_at": "2026-10-05T10:00:00Z", "finished_at": "2026-10-05T10:01:00Z"},
        "results": [{"name": "t", "status": "failed", "duration_ms": 1, "message": message}],
    }


def test_ingest_applies_the_projects_patterns_and_no_other_projects(client, db, make_key):
    _, key_one = make_key(project_id=1)
    _, key_two = make_key(project_id=2)
    db.add(MaskingPattern(project_id=1, name="customer_id", pattern=r"CUST-\d{6}"))
    db.commit()

    for key in (key_one, key_two):
        response = client.post("/api/v1/collect/runs", json=collect_body("bad CUST-123456"),
                               headers={"Authorization": f"Bearer {key}"})
        assert response.status_code in (200, 201), response.text

    by_project = {run.project_id: run for run in db.query(Run)}
    mine = db.query(RunResult).filter_by(run_id=by_project[1].id).one()
    other = db.query(RunResult).filter_by(run_id=by_project[2].id).one()
    assert mine.message == "bad [REDACTED:customer_id]" and mine.redacted is True
    assert other.message == "bad CUST-123456" and other.redacted is False


def test_remask_applies_patterns_added_after_ingest(client, db, make_key, capsys):
    _, key = make_key(project_id=1)
    client.post("/api/v1/collect/runs", json=collect_body("bad CUST-123456"), headers={"Authorization": f"Bearer {key}"})
    db.add(MaskingPattern(project_id=1, name="customer_id", pattern=r"CUST-\d{6}"))
    db.commit()

    assert remask.main([], session_factory=sessionmaker(bind=db.get_bind())) == 0
    db.expire_all()
    assert db.query(RunResult).one().message == "bad [REDACTED:customer_id]"
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["kinds"] == {"customer_id": 1}


def test_preview_replaces_a_nul_or_a_lone_surrogate_in_the_sample_never_500(client, auth, member):
    """A crafted JSON body: the sample is cleaned like an uploaded log, not refused and not a 500."""
    import json

    body = json.dumps({"name": "customer_id", "pattern": r"CUST-\d{6}", "sample": "CUST-123456\x00 \ud800 end"})
    response = client.post(f"{URL}/preview", content=body.encode("ascii"),
                           headers={**auth(), "Content-Type": "application/json"})
    assert response.status_code == 200, response.text
    assert response.json()["masked"] == "[REDACTED:customer_id]\ufffd \ufffd end"
