"""Log-value patterns through the API (ADR-032): members manage them, viewers read, adding re-scans past logs."""
from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.jobs import log_scan
from src.ingestion.models import LogPattern, LogValue, RunResult

URL = "/api/v1/projects/1/log-patterns"
TRIP = r'tripId="(\d+)"'
LINK = "https://backoffice.example.com/trips/{value}"


@pytest.fixture
def member(project_role):
    project_role(role="member", project_id=1)


def add(client, auth, name="trip_id", pattern=TRIP, link_template=None):
    body = {"name": name, "pattern": pattern}
    if link_template is not None:
        body["link_template"] = link_template
    return client.post(URL, json=body, headers=auth())


def test_a_member_adds_lists_and_removes_a_pattern(client, auth, member):
    created = add(client, auth, link_template=LINK)
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["name"], body["pattern"], body["link_template"]) == ("trip_id", TRIP, LINK)
    add(client, auth, name="booking", pattern=r'booking="(\w+)"')

    listed = client.get(URL, headers=auth()).json()
    assert [p["name"] for p in listed["patterns"]] == ["booking", "trip_id"]
    assert listed["patterns"][0]["link_template"] is None
    assert listed["scan"] == {"state": "idle", "since": None}

    assert client.delete(f"{URL}/{body['id']}", headers=auth()).status_code == 204
    assert [p["name"] for p in client.get(URL, headers=auth()).json()["patterns"]] == ["booking"]


def test_a_viewer_reads_but_cannot_change(client, auth, project_role, db):
    project_role(role="viewer", project_id=1)
    assert client.get(URL, headers=auth()).status_code == 200
    assert add(client, auth).status_code == 403
    preview = client.post(f"{URL}/preview", json={"name": "t", "pattern": "a", "sample": "a"}, headers=auth())
    assert preview.status_code == 403
    row = LogPattern(project_id=1, name="trip_id", pattern=TRIP)
    db.add(row)
    db.commit()
    assert client.delete(f"{URL}/{row.id}", headers=auth()).status_code == 403


def test_a_non_member_gets_404(client, auth, project_role):
    project_role(status_code=404, project_id=1)
    assert client.get(URL, headers=auth()).status_code == 404


@pytest.mark.parametrize("body, code, words", [
    ({"name": "Trip", "pattern": TRIP}, "name", "lowercase"),
    ({"name": "trip_id", "pattern": "a" * 257}, "pattern", "256"),
    ({"name": "trip_id", "pattern": r"(?=x)"}, "pattern", "RE2"),
    ({"name": "trip_id", "pattern": r'(trip)Id="(\d+)"'}, "pattern", "at most one capture group"),
    ({"name": "trip_id", "pattern": r"x*"}, "pattern", "matches empty text"),
    ({"name": "trip_id", "pattern": TRIP, "link_template": "http://backoffice.example.com/{value}"}, "link_template", "https://"),
    ({"name": "trip_id", "pattern": TRIP, "link_template": "javascript:alert(1)//{value}"}, "link_template", "https://"),
    ({"name": "trip_id", "pattern": TRIP, "link_template": "https://backoffice.example.com/trips"}, "link_template", "{value}"),
    ({"name": "trip_id", "pattern": TRIP, "link_template": "https://x.example.com/" + "a" * 500 + "{value}"}, "link_template", "500"),
])
def test_an_invalid_pattern_is_refused_at_its_field(client, auth, member, body, code, words):
    response = client.post(URL, json=body, headers=auth())
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code and words in detail["message"]


def test_a_duplicate_name_conflicts_at_the_name(client, auth, member):
    add(client, auth)
    response = add(client, auth, pattern=r'tripId=(\d+)')
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "name"


def test_a_project_holds_at_most_twenty_patterns(client, auth, member):
    for i in range(20):
        assert add(client, auth, name=f"p{i}", pattern=f"token{i}").status_code == 201
    response = add(client, auth, name="p20", pattern="token20")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "limit"


def test_adding_a_pattern_fills_values_of_past_runs(client, auth, member, db, seed_run):
    now = datetime.now(timezone.utc)
    recent = seed_run(now - timedelta(days=3), results=(("books", "passed", 5),))
    old = seed_run(now - timedelta(days=120), results=(("books", "passed", 5),))
    for run, trip in ((recent, "3960562"), (old, "1")):
        row = db.query(RunResult).filter_by(run_id=run.id).one()
        row.log = f'Trip id captured tripId="{trip}"'
    db.commit()

    assert add(client, auth).status_code == 201  # the scan runs after the response
    db.expire_all()
    assert [(v.value,) for v in db.query(LogValue)] == [("3960562",)]
    assert client.get(URL, headers=auth()).json()["scan"]["state"] == "idle"


def test_a_queued_scan_is_reported_as_queued(client, auth, member, db):
    log_scan.request_scan(db, 1)
    assert client.get(URL, headers=auth()).json()["scan"] == {"state": "queued", "since": None}


def test_preview_returns_the_masked_sample_and_the_values_saving_nothing(client, auth, member, db):
    sample = 'INFO tripId="3960562"\nINFO tripId="3960563"\nINFO tripId="3960562"'
    response = client.post(f"{URL}/preview", json={"name": "trip_id", "pattern": TRIP, "sample": sample},
                           headers=auth())
    assert response.status_code == 200, response.text
    assert response.json() == {"masked": sample, "values": ["3960562", "3960563"]}
    assert db.query(LogPattern).count() == 0


def test_preview_never_shows_a_masked_value(client, auth, member):
    sample = "login token=s3cr3t-value as ann@example.com"
    response = client.post(f"{URL}/preview", json={"name": "token", "pattern": r"token=(\S+)", "sample": sample},
                           headers=auth())
    body = response.json()
    assert "s3cr3t-value" not in body["masked"] and "[REDACTED:" in body["masked"]
    assert body["values"] == []


def test_preview_refuses_an_invalid_pattern_at_its_field_and_a_sample_over_64_kb(client, auth, member):
    bad = client.post(f"{URL}/preview", json={"name": "t", "pattern": "(a)(b)", "sample": "ab"}, headers=auth())
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "pattern"
    big = client.post(f"{URL}/preview", json={"name": "t", "pattern": "a", "sample": "a" * 65_537}, headers=auth())
    assert big.status_code == 422


def test_deleting_removes_the_patterns_values_and_an_unknown_id_is_404(client, auth, member, db, seed_run):
    run = seed_run(datetime.now(timezone.utc), results=(("books", "passed", 5),))
    row = db.query(RunResult).filter_by(run_id=run.id).one()
    row.log = 'tripId="7"'
    db.commit()
    pattern_id = add(client, auth).json()["id"]
    db.expire_all()
    assert db.query(LogValue).count() == 1
    assert client.delete(f"{URL}/{pattern_id}", headers=auth()).status_code == 204
    db.expire_all()
    assert db.query(LogValue).count() == 0
    assert client.delete(f"{URL}/{pattern_id}", headers=auth()).status_code == 404


def test_preview_replaces_a_nul_or_a_lone_surrogate_in_the_sample_never_500(client, auth, member):
    """A crafted JSON body (a textarea cannot hold one): the sample is cleaned like an uploaded log."""
    import json

    body = json.dumps({"name": "trip_id", "pattern": TRIP, "sample": 'tripId="7"\x00 \ud800 end'})
    response = client.post(f"{URL}/preview", content=body.encode("ascii"),
                           headers={**auth(), "Content-Type": "application/json"})
    assert response.status_code == 200, response.text
    assert response.json() == {"masked": 'tripId="7"\ufffd \ufffd end', "values": ["7"]}
